"""Kitap Cevir sayfasinin arka ucu (Bridge'e karisan sinif); Cevirgec bridge.py'nin ceviri bolumu.

Akis Cevirgec ile aynidir: EPUB + calisma klasoru -> prepare (bolumlere ayirma) -> ilk calistirmada
terim sozlugu onayi -> model denetimi -> (istege bagli) on analiz bolum secimi -> is parcaciginda
run_book. On analiz terim onerileri arayuzde onaylanir; is parcacigi book_submit_review gelene kadar
bekler. Ceviri kurallari book_core'dadir; burada yalnizca arayuz akisi var.

Altyazi cevirisiyle (bridge_translate) karismasin diye metotlar `book_`, olaylar `book_` onekli,
nitelikler `_bk_` oneklidir. Ortak LM Studio ayarlari config.json ust duzeyinde, kitaba ozel
ayarlar "book" bolumundedir (book_core.load_config).
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import threading
import traceback

import book_core
from book_core import (DEFAULT_CONFIG as BOOK_DEFAULTS, SHARED_CONFIG_KEYS, Client, GracefulStop, PauseController,
                       TranslationEngine, _dedupe_glossary, analysis_from_checkpoints, analysis_terms,
                       chapters_containing, first_heading, load_analysis_selection, read, render_analysis, rows,
                       save_json, validate_rerun)
from epub_import import prepare
from epub_meta import book_info

# Kitaba ozel ayarlar (config.json "book" bolumu); digerleri ust duzeyden gelir.
BOOK_KEYS = tuple(key for key in BOOK_DEFAULTS if key not in SHARED_CONFIG_KEYS)
BOOK_LOCKED_WHILE_RUNNING = ('chunk_chars', 'max_tokens', 'notes_max_tokens', 'fallback_context_length',
                             'context_safety_tokens', 'token_estimation_enabled')
EXCLUDED_FROM_ANALYSIS = re.compile(
    r'\b(cover|title page|copyright|contents|table of contents|dedication|acknowledg(?:e)?ments?|'
    r'about the author|newsletter|sign[ -]?up|bibliography|index|also by|other books|imprint)\b', re.I)
PHASE_LABELS = {'analysis': 'Ön analiz', 'analysis_saved': 'Ön analiz', 'translation': 'Çevriliyor',
                'notes': 'Notlar hazırlanıyor'}


def validate_glossary_rows(items):
    """Iki alan da dolu ya da ikisi de bos; ayni kaynak terim iki kez olamaz."""
    result = []
    for item in items or []:
        source = str(item.get('source', '')).strip()
        target = str(item.get('target', '')).strip()
        if bool(source) != bool(target):
            raise ValueError('Her sözlük satırında iki alan da dolu olmalı.')
        if source:
            result.append({'source': source, 'target': target})
    if len({item['source'].casefold() for item in result}) != len(result):
        raise ValueError('Aynı İngilizce terim birden fazla kez girilmiş.')
    return result


def book_section(stored, incoming=None, locked=()):
    """config.json "book" bolumu: kayitli degerler + sayfadan gelenler, turleri varsayilana gore."""
    value = {key: BOOK_DEFAULTS[key] for key in BOOK_KEYS}
    value.update({key: item for key, item in dict(stored or {}).items() if key in BOOK_KEYS})
    for key, item in dict(incoming or {}).items():
        if key not in BOOK_KEYS or key in locked:
            continue
        default = BOOK_DEFAULTS[key]
        try:
            if isinstance(default, bool):
                item = bool(item)
            elif isinstance(default, int):
                item = int(item)
            elif isinstance(default, float):
                item = float(item)
            else:
                item = str(item).strip()
        except (TypeError, ValueError):
            raise ValueError(f'{key} için geçersiz değer.') from None
        value[key] = item
    return value


def _error(error):
    return {'error': str(error)}


class BookMixin:
    def _init_book(self):
        self._bk_lock = threading.RLock()
        self._bk_book = None
        self._bk_epub = None
        self._bk_work_parent = None
        self._bk_fresh = False           # bu oturumda hazirlandi, sozluk henuz onaylanmadi
        self._bk_controller = None
        self._bk_thread = None
        self._bk_runtime = 'idle'
        self._bk_phase = 'Başlatılmadı'
        self._bk_current = ''
        self._bk_active_filename = None
        self._bk_active_phase = None
        self._bk_active_fraction = 0.0
        self._bk_last_saved = ''
        self._bk_review_event = None
        self._bk_review_values = None

    def _book_running(self):
        thread = self._bk_thread
        return thread is not None and thread.is_alive()

    # ------------------------------------------------------------------ yardimcilar
    def _book_log(self, message):
        stamp = datetime.now().strftime('%H:%M:%S')
        line = f'[{stamp}] {message}'
        book = self._bk_book
        if book:
            try:
                with (book / 'translation.log').open('a', encoding='utf-8', newline='\n') as stream:
                    stream.write(line + '\n')
            except OSError:
                pass
        if 'kaydedildi' in str(message).lower():
            self._bk_last_saved = stamp
        self._emit('book_log', {'line': line, 'last_saved': self._bk_last_saved})

    def _book_status(self):
        return {'runtime': self._bk_runtime, 'phase': self._bk_phase, 'current': self._bk_current,
                'last_saved': self._bk_last_saved, 'progress': self._book_progress()}

    def _book_push_status(self):
        self._emit('book_status', self._book_status())

    def _book_idle_error(self, action):
        if self._bk_runtime != 'idle':
            return {'error': f'Çalışan çeviri tamamlanmadan veya durmadan {action}.'}
        return None

    def _book_chapter_states(self):
        """Grup basliklariyla duz bolum listesi."""
        book = self._bk_book
        if not book:
            return []
        result, seen_groups = [], set()
        for filename, status in rows(read(book / '00-CONTEXT.md')):
            source_title = first_heading(read(book / 'source' / filename), Path(filename).stem)
            hierarchy = [part.strip() for part in source_title.split(' — ') if part.strip()]
            title = hierarchy[-1] if hierarchy else Path(filename).stem
            translated = book / 'translation' / filename
            if translated.exists():
                title = first_heading(read(translated), title).split(' — ')[-1].strip()
            state_path = book / '_python_translation' / filename / 'state.json'
            state = json.loads(read(state_path)) if state_path.exists() else {}
            if status == 'done' or state.get('complete'):
                label, kind = 'Tamamlandı', 'done'
            elif state.get('parts') or translated.exists():
                label, kind = 'Devam edecek', 'partial'
            else:
                label, kind = ('Sıradaki', 'next') if status == 'next' else ('Bekliyor', 'waiting')
            if filename == self._bk_active_filename and self._bk_active_phase in PHASE_LABELS:
                label, kind = PHASE_LABELS[self._bk_active_phase], 'active'
            key = ()
            for depth, group in enumerate(hierarchy[:-1]):
                key += (group,)
                if key not in seen_groups:
                    seen_groups.add(key)
                    result.append({'type': 'group', 'label': group, 'depth': depth})
            result.append({'type': 'chapter', 'filename': filename, 'title': title, 'label': label,
                           'kind': kind, 'depth': max(0, len(hierarchy) - 1)})
        return result

    def _book_progress(self):
        book = self._bk_book
        if not book:
            return {'done': 0, 'total': 0, 'percent': 0}
        try:
            states = rows(read(book / '00-CONTEXT.md'))
        except OSError:
            return {'done': 0, 'total': 0, 'percent': 0}
        total = len(states)
        done = sum(1 for _name, status in states if status == 'done')
        fraction = self._bk_active_fraction if self._bk_active_phase in ('translation', 'notes') else 0
        percent = int(min(100, (done + fraction) * 100 / total)) if total else 0
        return {'done': done, 'total': total, 'percent': percent}

    def _book_card(self):
        epub = self._bk_epub
        card = {'epub': str(epub) if epub else '', 'folder': str(self._bk_work_parent) if self._bk_work_parent else '',
                'project': str(self._bk_book) if self._bk_book else '', 'title': '', 'author': '', 'cover': None,
                'chars': 0}
        if epub and Path(epub).exists():
            card.update(book_info(epub))
        elif self._bk_book:
            context = read(self._bk_book / '00-CONTEXT.md')
            title = re.search(r'\*\*Title:\*\*\s*(.+)', context)
            author = re.search(r'\*\*Author:\*\*\s*(.+)', context)
            card['title'] = title.group(1).strip() if title else self._bk_book.name
            card['author'] = author.group(1).strip() if author else ''
        if self._bk_book:
            card['chars'] = sum(len(read(path)) for path in (self._bk_book / 'source').glob('*.md'))
            # Uretilen Turkce EPUB (epub_output.output_path: "<ad> TR.epub", varsa "<ad> TR 2.epub"...)
            outputs = sorted(self._bk_book.glob('*.epub'), key=lambda path: path.stat().st_mtime)
            card['output'] = str(outputs[-1]) if outputs else ''
        return card

    def _book_detach(self):
        """Yeni EPUB ya da klasor onceki projeyi birakir."""
        self._bk_book = None
        self._bk_fresh = False
        self._bk_phase = 'Başlatılmadı'
        self._bk_current = ''
        self._bk_active_filename = self._bk_active_phase = None
        self._bk_active_fraction = 0.0

    def _book_analysis_text(self):
        book = self._bk_book
        if not book:
            return ''
        merged = analysis_from_checkpoints(book)
        if merged:
            return render_analysis(merged)
        path = book / 'BOOK-ANALYSIS.md'
        return read(path) if path.exists() else ''

    # ------------------------------------------------------------------ durum
    def book_snapshot(self):
        with self._bk_lock:
            return {'book': self._book_card(), 'chapters': self._book_chapter_states(),
                    'status': self._book_status(), 'analysis': self._book_analysis_text()}

    # ------------------------------------------------------------------ secim
    def book_choose_epub(self, path=None):
        """path: pencereye birakilan EPUB; verilmezse dosya penceresi acilir."""
        blocked = self._book_idle_error('seçim değiştirilemez')
        if blocked:
            return blocked
        value = path or self._dialog('open_file', 'Kaynak EPUB seç', ('EPUB (*.epub)',))
        if not value:
            return None
        if Path(value).suffix.lower() != '.epub' or not Path(value).is_file():
            return {'error': 'EPUB dosyası değil: ' + str(value)}
        with self._bk_lock:
            self._book_detach()
            self._bk_epub = Path(value)
            if not self._bk_work_parent:
                self._bk_work_parent = self._bk_epub.parent
        return self.book_snapshot()

    def book_choose_folder(self):
        blocked = self._book_idle_error('seçim değiştirilemez')
        if blocked:
            return blocked
        value = self._dialog('open_folder', 'Çalışma klasörünü seç')
        if not value:
            return None
        with self._bk_lock:
            self._book_detach()
            self._bk_work_parent = Path(value)
        return self.book_snapshot()

    def book_open_project(self, path=None):
        blocked = self._book_idle_error('başka proje açılamaz')
        if blocked:
            return blocked
        value = path or self._dialog('open_folder', 'Mevcut çeviri projesini seç')
        if not value:
            return None
        book = Path(value)
        if not (book / '00-CONTEXT.md').is_file() or not (book / 'source').is_dir():
            return {'error': '00-CONTEXT.md ve source klasörü bulunamadı.'}
        with self._bk_lock:
            self._book_detach()
            self._bk_book = book
            self._bk_work_parent = book.parent
            marker = book / 'epub-import.json'
            epub = json.loads(read(marker)).get('epub', '') if marker.exists() else ''
            self._bk_epub = Path(epub) if epub else None
            self._bk_phase = 'Mevcut proje hazır'
        return self.book_snapshot()

    def book_preview(self, filename):
        book = self._bk_book
        if not book or not filename:
            return None
        source = read(book / 'source' / filename)
        target = book / 'translation' / filename
        translated = read(target) if target.exists() else ''
        return {'source': source, 'translation': translated, 'translated': target.exists(),
                'source_chars': len(source), 'translation_chars': len(translated)}

    # ------------------------------------------------------------------ baslatma akisi
    def book_prepare(self):
        """1. adim: EPUB'u bol. Yeni projede onaylanacak sozlugu dondurur."""
        blocked = self._book_idle_error('yeni çeviri başlatılamaz')
        if blocked:
            return blocked
        with self._bk_lock:
            if self._bk_book and not self._bk_fresh:
                return {'ok': True, 'glossary_required': False}
            if not self._bk_book:
                if not self._bk_work_parent or not self._bk_epub:
                    return {'error': 'Önce kaynak EPUB dosyasını ve çalışma klasörünü seçin.'}
                try:
                    self._bk_book = prepare(self._bk_epub, self._bk_work_parent)
                except Exception as error:
                    self._bk_book = None
                    return _error(error)
                self._bk_fresh = True
            glossary_path = self._bk_book / 'glossary.json'
            existing = json.loads(read(glossary_path)) if glossary_path.exists() else []
            return {'ok': True, 'glossary_required': True, 'glossary': existing}

    def book_confirm_glossary(self, items):
        """1b: ilk calistirmadan once secilen sozlugu kaydeder."""
        with self._bk_lock:
            if not self._bk_book:
                return {'error': 'Proje hazırlanmadı.'}
            try:
                values = validate_glossary_rows(items)
                save_json(self._bk_book / 'glossary.json', values)
            except (ValueError, OSError) as error:
                return _error(error)
            self._bk_fresh = False
        return self.book_snapshot()

    def book_cancel_prepare(self):
        with self._bk_lock:
            if self._bk_fresh:
                self._bk_book = None
                self._bk_fresh = False
        return self.book_snapshot()

    def book_model_check(self):
        """2. adim: LM Studio secili modeli sunmuyorsa engelle, sorgulanamadiysa uyar."""
        configured = book_core.load_config()['model']
        models = getattr(self, '_models', {}) or {}
        names = models.get('names') or []
        if models.get('state') == 'ok' and names and configured not in names:
            return {'block': 'Ayarlar sayfasından LM Studio’nun sunduğu modellerden birini seçin.'}
        if models.get('state') != 'ok':
            return {'warn': 'LM Studio model listesi sorgulanamadı. Sunucunun açık olduğunu doğrulayın; '
                            'aksi hâlde çeviri istekleri başarısız olabilir.'}
        return {}

    def book_analysis_candidates(self):
        """3. adim (istege bagli): on analize onerilen bolumler ve varsayilan secim."""
        book = self._bk_book
        if not book:
            return {'error': 'Proje hazırlanmadı.'}
        available = []
        for filename, _status in rows(read(book / '00-CONTEXT.md')):
            title = first_heading(read(book / 'source' / filename), Path(filename).stem)
            available.append({'filename': filename, 'title': title,
                              'story': not EXCLUDED_FROM_ANALYSIS.search(title)})
        existing = load_analysis_selection(book)
        selected = set(existing or [item['filename'] for item in available if item['story']])
        if not selected:
            selected = {item['filename'] for item in available}
        for item in available:
            item['checked'] = item['filename'] in selected
        return {'chapters': available}

    def book_start(self, analysis_files=None):
        """4. adim: tum kitabi (istege bagli on analizle) is parcaciginda cevirir."""
        blocked = self._book_idle_error('yeni çeviri başlatılamaz')
        if blocked:
            return blocked
        if not self._bk_book or self._bk_fresh:
            return {'error': 'Proje hazırlanmadı.'}
        if analysis_files is not None and not analysis_files:
            return {'error': 'En az bir bölüm seçin veya ön analizi kapatın.'}
        try:
            book_core.load_config()
        except (OSError, ValueError) as error:
            return {'error': 'Ayarlar geçersiz: ' + str(error)}
        self._book_launch(analysis_files=analysis_files)
        return self._book_status()

    def book_rerun(self, filenames):
        blocked = self._book_idle_error('bölüm yeniden çevrilemez')
        if blocked:
            return blocked
        try:
            validate_rerun(self._bk_book, list(filenames))
        except Exception as error:
            return _error(error)
        self._book_launch(rerun_files=list(filenames))
        return self._book_status()

    def book_validate_rerun(self, filename):
        if not self._bk_book:
            return {'error': 'Önce bir proje seçin.'}
        try:
            validate_rerun(self._bk_book, [filename])
        except Exception as error:
            return _error(error)
        return {'ok': True}

    def book_control(self):
        """Duraklat / devam et."""
        # Denetleyici _book_apply_state'i kendi kilidi altinda cagirir; _bk_lock altinda cagrilmaz.
        with self._bk_lock:
            runtime, controller = self._bk_runtime, self._bk_controller
        if controller and runtime == 'running':
            controller.request_pause()
        elif controller and runtime == 'paused':
            controller.resume()
        return self._book_status()

    def book_stop(self):
        """Gecerli istek bitince durur; kaydedilen parcalar bir sonraki baslatmada surer."""
        with self._bk_lock:
            controller = self._bk_controller
            if self._bk_review_event is not None:
                self._bk_review_values = None
                self._bk_review_event.set()
        if controller:
            controller.request_close()
        return self._book_status()

    def _book_launch(self, analysis_files=None, rerun_files=None):
        with self._bk_lock:
            self._bk_controller = PauseController(self._book_apply_state)
            self._bk_runtime = 'running'
            self._bk_phase = ('Bölüm yeniden çevriliyor' if rerun_files is not None else
                              'Ön analiz hazırlanıyor' if analysis_files is not None else 'Çeviri çalışıyor')
            self._bk_thread = threading.Thread(target=self._book_work,
                                               args=(self._bk_book, analysis_files, rerun_files),
                                               name='aktar-book-translation', daemon=True)
            self._bk_thread.start()
        self._book_push_status()

    def _book_ensure_model_loaded(self):
        """Model yuklu degilse once yuklenir; ceviri gercek context uzunlugunu gorur."""
        cfg = book_core.load_config()
        try:
            book_core.Client(cfg, self._book_log).context_length()
        except Exception as error:
            self._book_log(f'UYARI: Model önceden yüklenemedi, ilk istekte yüklenmesi beklenecek: {error}')

    def _book_work(self, book, analysis_files, rerun_files):
        outcome, message = 'failed', ''
        try:
            self._book_ensure_model_loaded()
            engine = TranslationEngine(book_core.load_config, self._bk_controller, self._book_log,
                                       self._book_on_progress)
            if analysis_files is not None:
                engine.run_analysis(book, analysis_files)
                pending = analysis_terms(book)
                if pending:
                    values = self._book_ask_review(book, pending)
                    if values is not None:
                        save_json(book / 'glossary.json', values)
                        self._book_log('Terim önerileri kabul edildi; sözlük güncellendi.')
                    else:
                        self._book_log('Terim önerileri kabul edilmedi; mevcut sözlük korunuyor.')
            if rerun_files is not None:
                engine.rerun_chapters(book, rerun_files)
                outcome, message = 'done', 'Seçilen bölümler yeniden çevrildi.'
            else:
                engine.run_book(book)
                outcome, message = 'done', 'Çeviri tamamlandı.'
        except GracefulStop:
            outcome, message = 'stopped', 'Çeviri durduruldu; kaydedilen kısım bir sonraki başlatmada sürer.'
        except Exception as error:
            self._book_log(traceback.format_exc())
            outcome, message = 'failed', str(error)
        finally:
            self._book_finish(outcome, message)

    def _book_finish(self, outcome, message):
        with self._bk_lock:
            self._book_log(message)
            self._bk_runtime = 'idle'
            self._bk_active_filename = self._bk_active_phase = None
            self._bk_active_fraction = 0.0
            self._bk_phase = {'done': 'Tamamlandı', 'stopped': 'Durduruldu', 'failed': 'Hata'}[outcome]
            self._bk_controller = None
        self._emit('book_finished', {'outcome': outcome, 'message': message, 'snapshot': self.book_snapshot()})

    def _book_apply_state(self, state):
        with self._bk_lock:
            self._bk_runtime = state
            if state == 'paused':
                self._bk_phase = 'Duraklatıldı'
            elif state == 'running':
                self._bk_phase = 'Çeviri çalışıyor'
            elif state == 'pausing':
                self._bk_phase = 'Duraklatılıyor… (geçerli istek bitince)'
            elif state == 'closing':
                self._bk_phase = 'Geçerli istek bitince duracak'
        self._book_push_status()

    def _book_on_progress(self, **data):
        phase = data.get('phase')
        refresh = False
        with self._bk_lock:
            if phase == 'complete':
                self._bk_active_filename = self._bk_active_phase = None
                refresh = True
            elif phase == 'chapter_complete':
                self._bk_active_filename = self._bk_active_phase = None
                self._bk_active_fraction = 0.0
                refresh = True
            else:
                filename = data.get('filename', '')
                part = int(data.get('part', 0))
                parts = max(1, int(data.get('parts', 1)))
                previous = self._bk_active_phase
                changed = filename != self._bk_active_filename or (phase != previous)
                self._bk_active_filename, self._bk_active_phase = filename, phase
                self._bk_active_fraction = part / parts
                labels = {'analysis': 'ön analiz', 'analysis_saved': 'ön analiz', 'translation': 'çeviri',
                          'notes': 'notlar'}
                if phase in ('analysis', 'analysis_saved'):
                    self._bk_phase = 'Ön analiz yapılıyor'
                elif phase in ('translation', 'notes'):
                    self._bk_phase = 'Çeviri çalışıyor'
                self._bk_current = f'{filename} — {labels.get(phase, phase)} {part}/{parts}'
                refresh = changed
                if phase == 'analysis_saved':
                    self._emit('book_analysis', {'text': self._book_analysis_text()})
        if refresh:
            self._emit('book_chapters', {'chapters': self._book_chapter_states()})
        self._book_push_status()

    # ------------------------------------------------------------------ terim onayi (is parcacigi bekler)
    def _book_ask_review(self, book, pending):
        glossary_path = book / 'glossary.json'
        current = _dedupe_glossary(json.loads(read(glossary_path)) if glossary_path.exists() else [])
        existing = {item['source'].casefold() for item in current}
        proposed = [{'source': str(item.get('source', '')).strip(),
                     'target': str(item.get('suggested_target', '')).strip(),
                     'scope': item.get('scope', 'book'), 'reason': str(item.get('reason', '') or '')}
                    for item in pending
                    if str(item.get('suggested_target', '')).strip()
                    and str(item.get('source', '')).strip().casefold() not in existing]
        if not proposed:
            return None
        event = threading.Event()
        with self._bk_lock:
            self._bk_review_event, self._bk_review_values = event, None
        self._emit('book_review', {'current': current, 'proposed': proposed})
        while not event.wait(0.5):
            controller = self._bk_controller
            if controller and controller._close_requested:
                return None
        return self._bk_review_values

    def book_submit_review(self, values=None):
        """values: {'source','target'} satirlari (mevcut + kabul edilen oneriler) ya da reddetmek icin None."""
        with self._bk_lock:
            event = self._bk_review_event
            if event is None:
                return False
            self._bk_review_values = _dedupe_glossary(
                [{'source': str(item.get('source', '')).strip(), 'target': str(item.get('target', '')).strip()}
                 for item in values if str(item.get('source', '')).strip() and str(item.get('target', '')).strip()]
            ) if values is not None else None
            self._bk_review_event = None
        event.set()
        return True

    # ------------------------------------------------------------------ sozluk
    def book_get_glossary(self):
        if not self._bk_book:
            return {'error': 'Önce bir proje seçin.'}
        path = self._bk_book / 'glossary.json'
        return {'glossary': json.loads(read(path)) if path.exists() else []}

    def book_save_glossary(self, items):
        """Duzenlenen sozlugu kaydeder; degisikligin etkiledigi cevrilmis bolumleri dondurur."""
        blocked = self._book_idle_error('sözlük düzenlenemez')
        if blocked:
            return blocked
        if not self._bk_book:
            return {'error': 'Önce bir proje seçin.'}
        try:
            new_glossary = validate_glossary_rows(items)
        except ValueError as error:
            return _error(error)
        path = self._bk_book / 'glossary.json'
        existing = json.loads(read(path)) if path.exists() else []
        old_map = {item.get('source', '').casefold(): item.get('target', '') for item in existing}
        new_map = {item.get('source', '').casefold(): item.get('target', '') for item in new_glossary}
        changed = sorted({key for key in set(old_map) | set(new_map) if old_map.get(key) != new_map.get(key)})
        if not changed:
            return {'changed': False, 'affected': []}
        save_json(path, new_glossary)
        return {'changed': True, 'affected': chapters_containing(self._bk_book, changed)}

    # ------------------------------------------------------------------ ayarlar ve kapanis
    def _book_settings(self, stored):
        """Ayarlar sayfasi icin "book" bolumu ve varsayilanlari."""
        return book_section(stored), {key: BOOK_DEFAULTS[key] for key in BOOK_KEYS}

    def _book_locked(self):
        return list(BOOK_LOCKED_WHILE_RUNNING) if self._book_running() else []

    def _book_merge_settings(self, value, incoming):
        """save_settings: "book" bolumunu birlestirir ve book_core kurallariyla dogrular."""
        section = book_section(value.get('book'), incoming, self._book_locked())
        combined = dict(BOOK_DEFAULTS)
        combined.update({key: value[key] for key in SHARED_CONFIG_KEYS if key in value})
        combined.update(section)
        book_core.validate_config(combined)
        value['book'] = section
        return value

    def _stop_book_for_close(self):
        if self._book_running():
            self.book_stop()
            self._bk_thread.join(5)
