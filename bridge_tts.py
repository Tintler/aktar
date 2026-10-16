"""Sesli okumanin arka ucu (Bridge'e karisan sinif); Cevirgec bridge.py'nin sesli okuma bolumu.

Ses motorlari (EMA Lightning, VoxCPM ...) ayri surecler olarak calisir (tts.py, engines/protocol.py);
paketler APP_DIR/ses-motorlari altina kurulur, hazirlanan cumleler APP_DIR/ses-onbellegi'nde tutulur.
Motor sureci yalnizca okurken baslar ve pencere kapaninca durdurulur (uygulama kapaliyken hicbir sey
calismaz). Secimler ui.json 'tts' altindadir.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from app_core import APP_DIR, ROOT
from tts import Engines


def _error(error):
    return {'error': str(error)}


class TtsMixin:
    def _engines(self):
        directory = Path(APP_DIR)
        cached = getattr(self, '_engines_cache', None)
        if cached is None or cached.app_dir != directory:
            self._engines_cache = Engines(directory, Path(ROOT) / 'engines', emit=self._emit,
                                          prefs=lambda: self.ui_prefs().get('tts', {}))
        return self._engines_cache

    def tts_status(self):
        return self._engines().status()

    def tts_engines(self):
        return self._engines().engines()

    def tts_load(self, language=None):
        """Kitap dili icin secilen motoru ve sesi (arka planda) hazirlar."""
        device = self.ui_prefs().get('tts', {}).get('device', 'auto')
        return self._engines().load(language or 'tr', device)

    def tts_say(self, text, speed=1.0, book=None, language='tr'):
        try:
            return self._engines().say(text, speed, book, language or 'tr')
        except Exception as error:
            return _error(error)

    def tts_cached(self, book, sentences, speed=1.0, language='tr'):
        """Bu cumlelerden kacinin sesi hazir (motor yuklenmeden okunabilir)."""
        return self._engines().cached(book, sentences, speed, language or 'tr')

    def tts_prepare(self, book, sentences, speed=1.0, language='tr'):
        """Cumleleri arka planda kitabin onbellegine uretir (ayni anda tek is)."""
        job = getattr(self, '_prepare_job', None)
        if job and job.is_alive():
            return {'error': 'Bir hazırlama zaten sürüyor.'}
        cancel = threading.Event()
        self._prepare_cancel = cancel
        engines = self._engines()

        def work():
            try:
                done = engines.prepare(book, sentences, speed, language or 'tr',
                                       lambda d, t: self._emit('tts_prepare', {'book': book, 'done': d, 'total': t}),
                                       cancel)
                self._emit('tts_prepare', {'book': book, 'finished': True, 'cancelled': cancel.is_set(), 'done': done})
            except Exception as error:
                self._emit('tts_prepare', {'book': book, 'finished': True, 'error': str(error)})

        self._prepare_job = threading.Thread(target=work, name='aktar-tts-prepare', daemon=True)
        self._prepare_job.start()
        return {'started': True, 'total': len([s for s in sentences if str(s).strip()])}

    def tts_prepare_cancel(self):
        cancel = getattr(self, '_prepare_cancel', None)
        if cancel:
            cancel.set()
        return True

    def tts_cache_info(self):
        return self._engines().cache_info()

    def tts_cache_clear(self, book=None):
        return self._engines().clear_cache(book)

    def tts_choose_reference(self):
        """Ses klonlamak icin kayit (yalnizca yol; dosyayi motor okur)."""
        return self._dialog('open_file', 'Ses kaydı seç', ('Ses kaydı (*.wav;*.mp3;*.flac;*.ogg;*.m4a)',))

    def tts_install_file(self):
        """Diskten secilen ses motoru paketini (zip) kurar."""
        path = self._dialog('open_file', 'Ses motoru paketi seç', ('Ses motoru paketi (*.zip)',))
        if not path:
            return None
        return self._engine_job(lambda: self._engines().install_zip(path), 'kuruldu')

    def _engine_job(self, job, verb):
        def work():
            try:
                engine_id = job()
                self._emit('tts_engines', {'engines': self._engines().engines(), 'done': f'Ses motoru {verb}: {engine_id}'})
            except Exception as error:
                self._emit('tts_engines', {'engines': self._engines().engines(), 'error': str(error)})

        threading.Thread(target=work, name='aktar-tts-install', daemon=True).start()
        return {'started': True}

    def tts_remove(self, engine_id):
        try:
            return self._engines().remove(engine_id)
        except (ValueError, OSError) as error:
            return _error(error)

    def tts_export(self, title, sentences, speed=1.0, book=None, language='tr', gaps=None):
        """Kayit yerini sorar, bolumu tek WAV olarak arka planda yazar (hazir cumleler onbellekten gelir,
        gerisi icin motor gerekir). `gaps`: her cumleden sonraki sessizlik (okuyucudaki gibi)."""
        engines = self._engines()
        texts = [text for text in sentences if str(text).strip()]
        if engines.state != 'ready' and engines.cached(book, texts, speed, language or 'tr') < len(texts):
            return {'error': 'Ses motoru hazır değil ve bölümün sesi önceden hazırlanmamış.'}
        if engines.status()['exporting']:
            return {'error': 'Bir kayıt zaten sürüyor.'}
        name = re.sub(r'[\\/:*?"<>|]+', ' ', str(title or 'bolum')).strip()[:120] or 'bolum'
        path = self._dialog('save_file', 'Sesi kaydet', name + '.wav', ('WAV ses dosyası (*.wav)',))
        if not path:
            return None
        if not str(path).lower().endswith('.wav'):
            path = str(path) + '.wav'

        def work():
            try:
                count = engines.export(sentences, speed, path,
                                       lambda done, total: self._emit('tts_export', {'done': done, 'total': total}),
                                       book, language or 'tr', gaps)
                self._emit('tts_export', {'finished': True, 'path': str(path), 'count': count})
            except Exception as error:
                self._emit('tts_export', {'finished': True, 'error': str(error)})

        threading.Thread(target=work, name='aktar-tts-export', daemon=True).start()
        return {'started': True, 'path': str(path)}

    def _stop_tts_for_close(self):
        """Pencere kapaninca: hazirlama durur, motor sureci kapatilir."""
        self.tts_prepare_cancel()
        cached = getattr(self, '_engines_cache', None)
        if cached is not None:
            cached.shutdown()
