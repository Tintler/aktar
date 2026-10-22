"""Altyazi Cevir sayfasinin arka ucu (Bridge'e karisan sinif).

Akis eski arayuzle aynidir: video -> ffprobe ile altyazi akislari -> tek akis secilir ->
Cevir: altyazi cikarilir, (istege bagli) on analiz onaya sunulur, ceviri yapilir, ceviri
sonu onerileri onaya sunulur ve <video>_TR.<uzanti> yazilir. Onay pencereleri arayuzde
acilir; is parcacigi submit_review gelene kadar bekler.

Altyazisi olmayan videoda "Whisper ile olustur" konusmadan metin cikarir (speech.transcribe,
onbellekli), videonun yanina <video>.srt yazar ve listeye 'whisper' akisini ekler; bu akis
secilince ceviri kaynagi o transkripttir.
"""
from __future__ import annotations

import threading
from pathlib import Path

import languages
import series
import speech
import subtitle
import subtitle_export
import subtitle_ocr
from app_core import (APP_DIR, GracefulStop, PauseController, TranslationEngine, _dedupe_glossary,
                      load_config, merge_glossaries, read, render_output)
from media import MEDIA_EXTENSIONS, extract_subtitle, subtitle_streams, unique_output_path, unique_source_path
from transcript_export import srt_time

WHISPER_STREAM = 'whisper'   # Whisper transkriptinin akis listesindeki anahtari


def clean_glossary(items):
    """Arayuzden gelen sozluk satirlari: iki alan da dolu olanlar, ilk yazilan kazanir."""
    result = []
    for item in items or []:
        source = str((item or {}).get('source', '')).strip()
        target = str((item or {}).get('target', '')).strip()
        if source and target:
            result.append({'source': source, 'target': target})
    return _dedupe_glossary(result)


def review_payload(phase, candidates, current, series_title=''):
    """Onay penceresinin verisi: mevcut seri terimleriyle cakisan oneriler gosterilmez."""
    current = _dedupe_glossary(current or [])
    existing = {item['source'].casefold() for item in current}
    terms = [dict(item) for item in candidates.get('terms', [])
             if str(item.get('source', '')).strip().casefold() not in existing]
    decisions = [dict(item) if isinstance(item, dict) else {'value': str(item)}
                 for item in candidates.get('decisions', [])]
    title = 'Ön analiz önerileri' if phase == 'pre' else 'Çeviri sonu önerileri'
    if series_title:
        title += ' · ' + series_title
    return {'phase': phase, 'title': title, 'terms': terms, 'decisions': decisions,
            'existing': len(current), 'has_series': bool(series_title)}


def review_values(values, has_series):
    """Arayuzun dondurdugu secimleri eski diyalogun values() bicimine cevirir."""
    result = {'series_terms': [], 'chapter_terms': [], 'series_decisions': [], 'chapter_decisions': []}
    for term in (values or {}).get('terms', []):
        source = str(term.get('source', '')).strip()
        target = str(term.get('target', '')).strip()
        if not source or not target:
            continue
        scope = 'series' if has_series and term.get('scope') == 'series' else 'chapter'
        item = {key: value for key, value in term.items() if key != 'scope'}
        item.update(source=source, target=target)
        result[scope + '_terms'].append(item)
    for decision in (values or {}).get('decisions', []):
        value = str(decision.get('value', '')).strip()
        if value:
            scope = 'series' if has_series and decision.get('scope') == 'series' else 'chapter'
            result[scope + '_decisions'].append(value)
    return result


def whisper_srt(segments):
    """Whisper segmentlerinden SRT metni (satirlar 42 karakterde bolunur)."""
    cues = []
    for segment in segments:
        text = str(segment.get('text', '')).strip()
        if not text:
            continue
        start = float(segment['start'])
        end = max(float(segment['end']), start + 0.5)
        cues.append(subtitle.Cue(speech.wrap_lines(text).split('\n'), start=srt_time(start), end=srt_time(end)))
    if not cues:
        raise ValueError('Transkriptte altyazı satırı yok.')
    return subtitle.render_srt(cues)


def whisper_entry(result):
    """Whisper transkriptinin akis listesindeki satiri (subtitle_streams kaydi bicimi)."""
    return {'index': WHISPER_STREAM, 'codec': 'whisper', 'language': str(result.get('language') or ''),
            'title': f"Konuşmadan metin · {result.get('model', '')} · {len(result.get('segments', []))} satır",
            'supported': True, 'image': False, 'extension': 'srt', 'whisper': True}


class TranslateMixin:
    def _init_translate(self):
        self._video = None
        self._streams = []
        self._probing = False
        self._series_slug = ''
        self._chapter_glossary = []
        self._analysis_text = ''
        self._progress = {'done': 0, 'total': 0}
        self._worker = None              # threading.Thread
        self._job = ''                   # 'translate' | 'whisper' (calisan isin turu)
        self._whisper = None             # acik videonun Whisper transkripti (speech.transcribe sonucu)
        self._pause = None               # PauseController
        self._cancelled = False
        self._review_event = None
        self._review_values = None
        self._pending_close = None

    def _running(self):
        return self._worker is not None and self._worker.is_alive()

    # ------------------------------------------------------------------ durum
    def translate_state(self):
        video = self._video
        series_list = [{'slug': slug, 'title': data['title']} for slug, data in series.list_series().items()]
        return {
            'video': {'path': str(video), 'name': video.name, 'folder': str(video.parent)} if video else None,
            'streams': self._streams, 'probing': self._probing,
            'series': series_list, 'series_slug': self._series_slug,
            'chapter_glossary': self._chapter_glossary, 'analysis': self._analysis_text,
            'running': self._running(), 'paused': bool(self._pause and self._pause.pause_requested),
            'progress': self._progress, 'job': self._job if self._running() else '',
            'whisper_available': speech.available()[0],
            'languages': self.translation_languages(),
        }

    def translation_languages(self):
        """Secili ceviri dil cifti ve secenekler (Altyazi Cevir ve Kitap Cevir sayfalari)."""
        try:
            source, target = languages.pair(load_config())
        except (OSError, ValueError):
            source, target = languages.DEFAULT_SOURCE, languages.DEFAULT_TARGET
        return {'source': source, 'target': target, 'choices': languages.choices()}

    def set_translation_languages(self, source, target):
        """Altyazi ve yeni kitap cevirileri icin dil ciftini config.json'a yazar (F151).
        Acik kitap projeleri kendi dil ciftini (epub-import.json) korur."""
        if self._running():
            return {'error': 'Çeviri sürerken dil değiştirilemez.'}
        result = self.save_settings({'source_language': str(source or ''), 'target_language': str(target or '')})
        if result.get('error'):
            return result
        return self.translation_languages()

    def _push_translate(self):
        self._emit('translate', self.translate_state())

    # ------------------------------------------------------------------ video
    def choose_video(self):
        if self._running():
            return {'error': 'Çeviri sürerken başka video açılamaz.'}
        pattern = 'Video ya da ses (' + ';'.join('*' + item for item in MEDIA_EXTENSIONS) + ')'
        path = self._dialog('open_file', 'Video ya da ses dosyası seç', (pattern,))
        return self.open_video(path) if path else None

    def open_video(self, path):
        """Videoyu acar ve akislari arka planda yoklar. Birden cok seri eslesirse secim istenir."""
        if self._running():
            return {'error': 'Çeviri sürerken başka video açılamaz.'}
        path = Path(str(path or ''))
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            return {'error': 'Bu dosya bir video ya da ses dosyası değil: ' + path.name}
        if not path.is_file():
            return {'error': 'Video bulunamadı: ' + str(path)}
        self._video = path
        self._streams = []
        self._whisper = None
        self._analysis_text = ''
        self._progress = {'done': 0, 'total': 0}
        self._probing = True
        self._log('Video açıldı: ' + str(path))
        choices = []
        if not self._series_slug:
            matches = series.matching_series(path)
            if len(matches) == 1:
                self._series_slug = matches[0]
                self._log('Seri önerisi: ' + series.load_series(matches[0])['title'])
            elif len(matches) > 1:
                choices = [{'slug': slug, 'title': series.load_series(slug)['title']} for slug in matches]

        def probe():
            try:
                streams = subtitle_streams(path)
            except (RuntimeError, ValueError) as error:
                streams = []
                self._log(str(error))
                self._emit('toast', {'message': str(error), 'kind': 'error'})
            for item in streams:
                if item.get('image') and subtitle_ocr.is_ready(path, item['index']):
                    item.update(supported=True, ocr=True, extension='srt')   # OCR ile okunmus (F118)
            cached = self._cached_whisper(path)
            if self._video != path:
                return
            if cached:
                self._whisper = cached
                streams.append(whisper_entry(cached))
            self._streams = streams
            self._probing = False
            if not streams:
                self._log('Bu videoda altyazı akışı yok.')
            self._push_translate()

        threading.Thread(target=probe, name='aktar-probe', daemon=True).start()
        state = self.translate_state()
        state['series_choices'] = choices
        return state

    def close_video(self):
        if self._running():
            return {'error': 'Çeviri sürerken video kapatılamaz.'}
        self._video = None
        self._streams = []
        self._whisper = None
        self._analysis_text = ''
        self._progress = {'done': 0, 'total': 0}
        return self.translate_state()

    # ------------------------------------------------------------------ Whisper
    @staticmethod
    def _cached_whisper(path):
        try:
            cfg = load_config()
            return speech.load_cached(path, cfg['whisper_model'], cfg['whisper_language'])
        except (RuntimeError, ValueError, OSError):
            return None

    def generate_subtitle(self):
        """Konusmadan metinle altyazi olusturur: <video>.srt yazilir, 'whisper' akisi eklenir."""
        if self._running():
            return {'error': 'Önceki iş sürüyor.'}
        if self._video is None:
            return {'error': 'Önce bir video açın.'}
        ok, message = speech.available()
        if not ok:
            return {'error': message}
        self._pause = None
        self._cancelled = False
        self._review_event = None
        self._job = 'whisper'
        self._progress = {'done': 0, 'total': 0}
        self._worker = threading.Thread(target=self._run_whisper, name='aktar-whisper-subtitle',
                                        daemon=True, args=(self._video,))
        self._worker.start()
        return self.translate_state()

    def _run_whisper(self, video):
        output, error = '', ''
        self._push_translate()
        try:
            cfg = load_config()
            result = speech.transcribe(video, cfg['whisper_model'], cfg['whisper_device'], cfg['whisper_language'],
                                       progress=self._on_progress, cancelled=lambda: self._cancelled,
                                       log=self._log, cuda_dir=cfg.get('whisper_cuda_dir', ''))
            if self._cancelled:
                raise GracefulStop('Altyazı oluşturma iptal edildi.')
            text = whisper_srt(result['segments'])
            target = unique_source_path(video, 'srt')
            target.write_text(text, encoding='utf-8', newline='\n')
            output = str(target)
            if self._video == video:
                self._whisper = result
                self._streams = [item for item in self._streams if item['index'] != WHISPER_STREAM]
                self._streams.append(whisper_entry(result))
        except GracefulStop as stop:
            error = str(stop) or 'Altyazı oluşturma iptal edildi.'
        except (RuntimeError, ValueError, OSError) as failure:
            error = 'Altyazı oluşturulamadı: ' + str(failure)
        except Exception as failure:  # beklenmeyen hata arayuzu kilitli birakmasin
            error = 'Beklenmeyen hata: ' + repr(failure)
        self._log(error or 'Altyazı yazıldı: ' + output)
        self._worker = None
        self._job = ''
        self._progress = {'done': 0, 'total': 0}
        cancelled = bool(error) and 'ptal' in error.casefold()
        self._emit('subtitle_ready', {'output': output, 'name': Path(output).name if output else '',
                                      'error': error, 'cancelled': cancelled})
        self._push_translate()

    # ------------------------------------------------------------------ seri
    def set_series(self, slug):
        slug = str(slug or '')
        if slug and slug not in series.list_series():
            return {'error': 'Seri bulunamadı.'}
        self._series_slug = slug
        if slug:
            self._log('Seri seçildi: ' + series.load_series(slug)['title'])
        return self.translate_state()

    def guess_series_title(self):
        return series.guess_series_title(self._video) if self._video is not None else ''

    def create_series(self, title):
        title = str(title or '').strip()
        if not title:
            return {'error': 'Seri başlığı boş olamaz.'}
        hints = [self._video.parent.name] if self._video is not None else []
        try:
            data = series.create_series(title, hints, languages.target(load_config()))
        except (ValueError, RuntimeError) as error:
            return {'error': str(error)}
        self._series_slug = series.slugify(title)
        self._log('Seri oluşturuldu: ' + data['title'])
        return self.translate_state()

    def series_data(self, slug=None):
        slug = slug or self._series_slug
        if not slug:
            return {'error': 'Önce bir seri seçin veya yeni seri oluşturun.'}
        data = series.load_series(slug)
        return {'slug': slug, 'title': data['title'],
                'glossary': [{'source': str(item.get('source', '')), 'target': str(item.get('target', ''))}
                             for item in data.get('glossary', []) if isinstance(item, dict)],
                'decisions': [str(item) for item in data.get('decisions', []) if str(item).strip()]}

    def save_series_glossary(self, items, slug=None):
        slug = slug or self._series_slug
        if not slug:
            return {'error': 'Önce bir seri seçin veya yeni seri oluşturun.'}
        data = series.load_series(slug)
        # Eski kayitlarin ek alanlari (origin, first_seen, locked) korunur.
        old = {str(item.get('source', '')).casefold(): item
               for item in data.get('glossary', []) if isinstance(item, dict)}
        updated = []
        for item in clean_glossary(items):
            saved = dict(old.get(item['source'].casefold(), {}))
            saved.update(item)
            updated.append(saved)
        data['glossary'] = updated
        try:
            series.save_series(data, slug=slug)
        except RuntimeError as error:
            return {'error': str(error)}
        self._log('Seri terimleri güncellendi.')
        return True

    def save_series_decisions(self, lines, slug=None):
        slug = slug or self._series_slug
        if not slug:
            return {'error': 'Önce bir seri seçin veya yeni seri oluşturun.'}
        data = series.load_series(slug)
        if isinstance(lines, str):
            lines = lines.splitlines()
        data['decisions'] = list(dict.fromkeys(str(line).strip() for line in lines or [] if str(line).strip()))
        try:
            series.save_series(data, slug=slug)
        except RuntimeError as error:
            return {'error': str(error)}
        self._log('Seri süreklilik kararları güncellendi.')
        return True

    def set_chapter_glossary(self, items):
        self._chapter_glossary = clean_glossary(items)
        self._log(f'Bölüm terimleri: {len(self._chapter_glossary)} giriş')
        return self.translate_state()

    # ------------------------------------------------------------------ ceviri
    def start_translation(self, stream_index, do_analysis=False):
        if self._running():
            return {'error': 'Çeviri zaten sürüyor.'}
        if self._video is None:
            return {'error': 'Önce bir video açın.'}
        stream = next((item for item in self._streams if item['index'] == stream_index), None)
        if stream is None:
            return {'error': 'Önce bir altyazı akışı işaretleyin.'}
        if stream['index'] == WHISPER_STREAM and not (self._whisper or {}).get('segments'):
            return {'error': 'Whisper transkripti bulunamadı; yeniden oluşturun.'}
        if stream['image'] and not stream.get('ocr'):
            return {'error': 'Görüntü tabanlı altyazıyı önce "OCR ile oku" ile metne çevirin.'}
        if not stream['supported']:
            return {'error': 'Desteklenmeyen altyazı codec: ' + stream['codec']}
        glossary = list(self._chapter_glossary)
        decisions = []
        slug = self._series_slug
        target = languages.target(load_config())
        if slug and series.series_language(slug) != target:
            # Seri sozlugu baska bir hedef dile ait: karsiliklari bu ceviriye uymaz (F151).
            self._log(f'UYARI: seri sözlüğü {languages.label(series.series_language(slug))} '
                      f'çeviriler içindir; {languages.label(target)} çeviride kullanılmadı.')
            slug = None
        if slug:
            # Bolum terimleri seri terimlerini EZER (sonraki katman kazanir).
            glossary = merge_glossaries(series.series_glossary(slug), glossary)
            decisions = series.series_decisions(slug)
        self._pause = PauseController()
        self._cancelled = False
        self._job = 'translate'
        self._review_event = threading.Event()
        self._progress = {'done': 0, 'total': 0}
        self._analysis_text = ''
        self._worker = threading.Thread(
            target=self._run_translation, name='aktar-translate', daemon=True,
            args=(self._video, stream, glossary, decisions, bool(do_analysis), slug))
        self._worker.start()
        return self.translate_state()

    def toggle_pause(self):
        pause = self._pause
        if not self._running() or pause is None:
            return self.translate_state()
        if pause.pause_requested:
            pause.resume()
            self._log('Devam ediliyor.')
        else:
            pause.request_pause()
            self._log('Duraklatıldı.')
        return self.translate_state()

    def cancel_translation(self):
        if not self._running():
            return self.translate_state()
        self._cancelled = True
        if self._review_event is not None:
            self._review_values = None
            self._review_event.set()  # onay bekleniyorsa is parcacigini serbest birak
        if self._pause is not None:
            self._pause.request_close()
        self._log('İptal isteniyor...')
        return self.translate_state()

    def submit_review(self, values):
        """Onay penceresinin sonucu (None = Atla)."""
        event = self._review_event
        self._review_values = values
        if event is not None:
            event.set()
        return True

    def _stop_translation_for_close(self):
        if self._running():
            self.cancel_translation()
            self._worker.join(5)

    def _review(self, phase, candidates, video, slug):
        if not candidates.get('terms') and not candidates.get('decisions'):
            return None
        current, title = [], ''
        if slug:
            data = series.load_series(slug)
            current, title = data.get('glossary', []), data['title']
        payload = review_payload(phase, candidates, current, title)
        self._review_values = None
        self._review_event.clear()
        self._emit('review', payload)
        self._review_event.wait()
        if self._cancelled:
            raise GracefulStop('Çeviri iptal edildi.')
        raw = self._review_values
        if raw is None:
            return None
        values = review_values(raw, payload['has_series'])
        if slug:
            terms = [dict(item, origin=('pre_analysis' if phase == 'pre' else 'post_analysis'),
                          first_seen=video.name, locked=True)
                     for item in values['series_terms']]
            try:
                series.add_knowledge(slug, terms, values['series_decisions'], video.name)
                self._log('Seri terimleri/süreklilik kararları güncellendi.')
            except (RuntimeError, ValueError) as error:
                self._log('UYARI: seri kaydedilemedi: ' + str(error))
        return values

    def _show_analysis(self, candidates):
        lines = ['Ön analiz - yapay zekâ önerileri:', '']
        for item in candidates.get('terms', []):
            lines.append(f"- {item['source']} -> {item['target']} "
                         f"[{item.get('type', 'term')}, x{item.get('count', 1)}]")
        if candidates.get('decisions'):
            lines.extend(['', 'Süreklilik:'])
            lines.extend('- ' + (item['value'] if isinstance(item, dict) else str(item))
                         for item in candidates['decisions'])
        if not candidates.get('terms') and not candidates.get('decisions'):
            lines.append('Aday terim bulunamadı.')
        self._analysis_text = '\n'.join(lines)
        self._emit('analysis', {'text': self._analysis_text})

    def _on_progress(self, done, total):
        self._progress = {'done': int(done), 'total': int(total)}
        self._emit('progress', self._progress)

    def _run_translation(self, video, stream, glossary, decisions, do_analysis, slug):
        """Cikarma + (istege bagli on analiz) + ceviri zinciri; eski RunWorker.run ile ayni."""
        work_dir = APP_DIR / 'work_files'
        output, error = '', ''
        self._push_translate()
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            video_name = video.stem
            if stream['index'] == WHISPER_STREAM:
                kind, payload = 'srt', subtitle.parse_srt(whisper_srt(self._whisper['segments']))
                self._log('Kaynak: Whisper transkripti (' + str(len(payload)) + ' satır).')
            elif stream.get('ocr'):
                cached = subtitle_ocr.load_cached(video, stream['index'])
                if not cached:
                    raise ValueError('OCR sonucu bulunamadı; altyazıyı yeniden OCR ile okuyun.')
                kind, payload = subtitle_export.segments_document(cached['segments'])
                self._log('Kaynak: OCR ile okunan altyazı (' + str(len(payload)) + ' satır).')
            else:
                source = work_dir / f"{video_name}.{stream['extension']}"
                extract_subtitle(video, stream['index'], source, codec=stream['codec'])
                self._log('Kaynak altyazı çıkarıldı: ' + str(source))
                kind, payload = subtitle.parse_by_extension(read(source), source.suffix)
            cues = subtitle.cues_of(kind, payload)
            engine = TranslationEngine(load_config, log=self._log)
            if do_analysis:
                candidates = engine.analyze_terms(
                    cues, glossary=glossary, checkpoint=work_dir / f'{video_name}.pre-analysis.state.json',
                    pause=self._pause)
                self._show_analysis(candidates)
                self._log('Ön analiz: ' + str(len(candidates['terms'])) + ' terim, '
                          + str(len(candidates['decisions'])) + ' süreklilik adayı bulundu.')
                accepted = self._review('pre', candidates, video, slug)
                if accepted is not None:
                    glossary = merge_glossaries(glossary, accepted['series_terms'] + accepted['chapter_terms'])
                    decisions = list(dict.fromkeys(
                        decisions + accepted['series_decisions'] + accepted['chapter_decisions']))
                    self._log('Ön analiz önerileri bu çeviriye uygulandı.')
            translated = engine.translate(cues, glossary=glossary, decisions=decisions,
                                          checkpoint=work_dir / f'{video_name}.state.json', pause=self._pause,
                                          progress=self._on_progress)
            post = engine.analyze_terms(
                cues, glossary=glossary, translated_cues=translated,
                checkpoint=work_dir / f'{video_name}.post-analysis.state.json', pause=self._pause)
            self._log('Çeviri sonu analizi: ' + str(len(post['terms'])) + ' terim, '
                      + str(len(post['decisions'])) + ' süreklilik adayı bulundu.')
            accepted_post = self._review('post', post, video, slug)
            if accepted_post is not None:
                learned = accepted_post['series_terms'] + accepted_post['chapter_terms']
                translated = engine.enforce_episode_terms(cues, translated, learned, pause=self._pause)
            if self._cancelled:
                raise GracefulStop('Çeviri iptal edildi.')
            cfg = load_config()
            target = unique_output_path(video, kind, languages.output_tag(cfg))
            text, _ = render_output(kind, payload, translated, log=self._log, language=languages.target(cfg))
            target.write_text(text, encoding='utf-8', newline='\n')
            output = str(target)
        except GracefulStop as stop:
            error = str(stop)
        except (RuntimeError, ValueError, OSError) as failure:
            error = str(failure)
        except Exception as failure:  # beklenmeyen hata arayuzu kilitli birakmasin
            error = 'Beklenmeyen hata: ' + repr(failure)
        if error:
            self._log(error)
        else:
            self._log('Çeviri yazıldı: ' + output)
            if slug:
                try:
                    series.add_episode(slug, video.name)
                except (RuntimeError, ValueError) as series_error:
                    self._log('UYARI: bölüm kaydedilemedi: ' + str(series_error))
        self._worker = None
        self._job = ''
        cancelled = bool(error) and any(marker in error.casefold() for marker in ('ptal', 'kapatıl'))
        self._emit('finished', {'output': output, 'name': Path(output).name if output else '',
                                'error': error, 'cancelled': cancelled})
        self._push_translate()
