"""Cok sesli sesli kitap (F239, deneysel): karakter atamasi ve karakter sesleri (Bridge'e karisan sinif).

Atama kitapligin sag tik menusunden butun kitap icin bir kez yapilir (book_cast, olay 'tts_cast'); sesler kitabin
"Karakter sesleri" penceresinde secilir, okuyucudaki "Cok sesli" cipi acip kapatir. Okuma, Hazirla ve Kaydet ayni
yoldan gecer: tts.Engines her cumlenin sesini `_cast_voice` ile sorar (anlatici ya da karakter). Karakter sesleri
okuyucunun sesiyle ayni motordan olmali (motor degistirmek her konusmada yeniden yukleme olurdu).
"""
from __future__ import annotations

import threading
from pathlib import Path

import book_cast
import app_core


def _error(error):
    return {'error': str(error)}


class CastMixin:
    def _cast_store(self):
        directory = Path(app_core.APP_DIR)
        store = getattr(self, '_cast_cache', None)
        if store is None or store.directory != directory / book_cast.STORE_DIR:
            self._cast_cache = store = book_cast.Store(directory)
        return store

    def _cast_voice(self, book, text):
        """tts.Engines icin: text None -> kitap cok sesli mi okunuyor; yoksa cumleyi soyleyen karakterin sesi
        (override) ya da None (anlatici)."""
        try:
            data = self._cast_store().load(book)
        except (OSError, ValueError):
            return None
        if not data or not data.get('enabled') or not data.get('voices'):
            return None if text is not None else False
        if text is None:
            return True
        name = (data.get('speakers') or {}).get(' '.join(str(text).split()))
        ref = (data.get('voices') or {}).get(name) if name else None
        return self._voice_override(ref) if ref else None

    def _cast_local(self):
        """Karakter atamasi bu bilgisayarin ya da yerel agin dil modeliyle suruyor mu (ses motoru beklemeli)."""
        job = getattr(self, '_cast_job', None)
        return job is not None and job.is_alive() and not getattr(self, '_cast_remote', False)

    def _cast_running(self):
        job = getattr(self, '_cast_job', None)
        return job is not None and job.is_alive()

    def tts_cast_books(self):
        try:
            return {'books': self._cast_store().books(), 'partials': self._cast_store().partials()}
        except OSError:
            return {'books': [], 'partials': {}}

    def tts_cast_info(self, book, language='tr'):
        """Kitabin karakterleri, ses secimleri ve secilebilecek sesler (okuyucunun sesiyle ayni motor ve dil)."""
        try:
            info = self._cast_store().info(book)
        except (OSError, ValueError) as error:
            return _error(error)
        engines = self._engines()
        engine_id, voice_id = engines.choice(language)
        options, narrator = [], ''
        for item in self.tts_voices():
            override = self._voice_override(item['value'])
            if not override or item.get('configurable') or item.get('language', 'tr') != (language or 'tr'):
                continue
            if override['voice'].partition('/')[0] != engine_id:
                continue
            options.append({'value': item['value'], 'label': item['label'], 'group': item['group']})
        prefs = self.ui_prefs().get('tts', {})
        chosen = (prefs.get('voices') or {}).get(language or 'tr') or ''
        if prefs.get('active_preset'):   # okuyucuda kayitli ses secili: anlatim onunla okunur
            chosen = 'preset:' + str(prefs['active_preset'])
        fallback = f'{engine_id}/{voice_id}' if engine_id else ''
        labels = {item['value']: item['label'] for item in self.tts_voices()}
        narrator = labels.get(chosen) or labels.get(fallback) or fallback
        engine = next((item['name'] for item in engines.engines() if item['id'] == engine_id), engine_id or '')
        return {'info': info, 'voices': options, 'narrator': narrator, 'engine': engine,
                'partial': self._cast_store().load_partial(book) is not None}

    def tts_cast_set(self, book, voices=None, enabled=None, rename=None):
        try:
            return {'info': self._cast_store().update(book, voices, enabled, rename)}
        except (OSError, ValueError) as error:
            return _error(error)

    def tts_cast_clear(self, book):
        try:
            self._cast_store().clear(book)
        except (OSError, ValueError) as error:
            return _error(error)
        return True

    def tts_cast_cancel(self):
        cancel = getattr(self, '_cast_cancel', None)
        if cancel is not None:
            cancel.set()
        return True

    def tts_cast_create(self, book, sections, title='', resume=False):
        """Butun kitabin konusmalarini karakterlere atar (arka planda, olay 'tts_cast'). `sections`:
        [{'sentences', 'breaks'}] okuyucunun bolmesiyle. Yerel dil modeliyle calisirken ses motoru durdurulur ve
        bu isin yukledigi model sonunda bosaltilir (duygu etiketleri gibi). Ara kayitla ilerler; `resume` surdurur."""
        from bridge_tts import remote_llm
        store = self._cast_store()
        try:
            store._path(book)
        except ValueError as error:
            return _error(error)
        sections = [{'sentences': [' '.join(str(s).split()) for s in (part or {}).get('sentences') or ()],
                     'breaks': [int(b) for b in (part or {}).get('breaks') or ()]} for part in sections or ()]
        total = sum(len(part['sentences']) for part in sections)
        if not total:
            return _error('Kitapta metin yok.')
        key = book_cast.resume_key(sections)
        partial = None
        if resume:
            partial = store.load_partial(book, key)
            if partial is None:
                return _error('Yarım kalan atama sürdürülemiyor: kitabın metni ya da bölme ayarı değişmiş. Baştan başlatın.')
        remote = remote_llm()
        if self._cast_running():
            return _error('Karakter ataması zaten sürüyor.')
        if not remote and (self._emotion_local() or getattr(self, '_art_planning_local', lambda: False)()):
            return _error('Başka bir iş bu bilgisayarın dil modelini kullanıyor (duygu etiketleri ya da görsel '
                          'planı); bitince yeniden deneyin.')
        for name in ('_prepare_job', '_audiobook_job') if not remote else ():
            running = getattr(self, name, None)
            if running is not None and running.is_alive():
                return _error('Ses hazırlanırken ya da sesli kitap kaydedilirken karakter ataması yapılamaz.')
        if not resume:
            store.clear_partial(book)
        cancel = threading.Event()
        self._cast_cancel, self._cast_remote = cancel, remote

        def progress(done, count):
            self._emit('tts_cast', {'book': book, 'title': title, 'done': done, 'total': count})

        def checkpoint(state):
            try:
                store.save_partial(book, key, state, total)
            except OSError as error:
                self._log(f'UYARI: Karakter atamasının ara kaydı yazılamadı: {error}')

        def work():
            from app_core import Client, keep_loaded, load_config, unload_models
            client, loaded = None, []
            try:
                engines = getattr(self, '_engines_cache', None)
                if not remote and engines is not None and engines.state != 'idle' and not engines._exporting:
                    engines.stop_worker()   # ses motoru bellegi bosalsin
                    engines._set('idle', '')
                client = Client(load_config(), log=self._log)
                loaded = keep_loaded(client, [client.cfg.get('model')], self._log)

                def ask(prompt):
                    return client.chat([{'role': 'user', 'content': prompt}], temperature=0, max_tokens=2500)
                result = book_cast.attribute_book(sections, ask, cancel, progress, partial, checkpoint)
                info = store.save(book, sections, result)
                store.clear_partial(book)
                self._log(f'Karakter ataması: {info["assigned"]}/{info["speech"]} konuşma, '
                          f'{len(info["characters"])} karakter ({title or book}).')
                self._emit('tts_cast', {'book': book, 'title': title, 'finished': True, 'info': info})
            except book_cast.Cancelled:
                self._emit('tts_cast', {'book': book, 'title': title, 'finished': True, 'cancelled': True})
            except Exception as error:
                self._log(f'UYARI: Karakter ataması yapılamadı: {error}')
                self._emit('tts_cast', {'book': book, 'title': title, 'finished': True, 'error': str(error)})
            finally:
                if loaded:
                    unload_models(client, loaded)

        self._cast_job = threading.Thread(target=work, name='aktar-tts-cast', daemon=True)
        self._cast_job.start()
        return {'started': True, 'total': total}
