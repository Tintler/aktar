"""Telefon sesi (F229): Sesli Haber telefon uygulamasina yerel agda Aktar'in sesini veren sunucu.

Sunucu phone_server.py'de. Ayarlar > Baglantilar'dan acilir/kapanir; 'autostart' aciksa Aktar acilinca
kendiliginden acilir. Pencere kapaninca durur. Ses motoru baska bir is icin kullaniliyorsa (sesli kitap, dublaj,
okuyucuda baska sesle okuma ...) istek 503 ile reddedilir, telefon kendi sesine duser.
Tercihler ui.json 'phone': {voice, port, autostart}.
"""
from __future__ import annotations

import base64
import threading

import phone_server
from app_core import APP_DIR
from version import VERSION

DEFAULT_VOICE = 'ema-lightning/default'


class PhoneMixin:
    _phone_server = None

    def _phone_prefs(self):
        value = self.ui_prefs().get('phone')
        return value if isinstance(value, dict) else {}

    def _phone_set_prefs(self, **values):
        self.save_ui_prefs({'phone': {**self._phone_prefs(), **values}})

    def _phone_voice(self):
        return self._phone_prefs().get('voice') or DEFAULT_VOICE

    def _phone_phones(self):
        return phone_server.Phones(APP_DIR / 'telefon' / 'telefonlar.json')

    def _phone_busy(self, override):
        """Ses motorunu kullanan bir is varsa nedeni, yoksa None."""
        running = getattr(self, '_tool_running', None)
        if running is not None and running() and self._tool['kind'] in ('dub', 'dubgen'):
            return 'Aktar dublaj için sesi kullanıyor.'
        for name, reason in (('_audiobook_job', 'Aktar sesli kitap kaydediyor.'),
                             ('_speech_job', 'Aktar metinden ses kaydediyor.'),
                             ('_prepare_job', 'Aktar okuyucu için ses hazırlıyor.'),
                             ('_emotion_job', 'Aktar duygu etiketleri oluşturuyor.')):
            job = getattr(self, name, None)
            if job is not None and job.is_alive():
                return reason
        if getattr(self, '_art_planning', lambda: False)():
            return 'Aktar kitap görselleri planlıyor.'
        awake = getattr(self, '_keep_awake', None)
        if awake is not None and awake.active:   # okuyucu sesli okuyor: baska sese gecilirse okuma bozulur
            engines = self._engines()
            language = self._override_language(override, 'tr')
            if (engines.current.get('engine'), engines.current.get('voice')) != engines.choice(language, override):
                return 'Aktar başka bir sesle kitap okuyor.'
        return None

    def _phone_speak(self, text, speed):
        """Sunucu is parcaciginda: metni telefonun sesiyle okur, WAV baytlari."""
        voice = self._phone_voice()
        override = self._voice_override(voice)
        if override is None:
            raise phone_server.Busy('Telefon sesi bulunamadı: ' + voice)
        reason = self._phone_busy(override)
        if reason:
            raise phone_server.Busy(reason)
        language = self._override_language(override, 'tr')
        error = self._load_and_wait(language, override)
        if error:
            raise phone_server.Busy(error)
        result = self._engines().say(text, speed, None, language, override)
        return base64.b64decode(result.get('audio') or '')

    def phone_state(self):
        server = self._phone_server
        info = server.info() if server else {'running': False, 'port': None, 'code': '', 'addresses': []}
        prefs = self._phone_prefs()
        info.update(phones=self._phone_phones().listing(), voice=self._phone_voice(),
                    autostart=bool(prefs.get('autostart')),
                    default_port=int(prefs.get('port') or phone_server.DEFAULT_PORT))
        return info

    def phone_start(self, port=None):
        if self._phone_server is None:
            self._phone_server = phone_server.PhoneServer(self._phone_speak, self._phone_phones(), VERSION, self._log)
        try:
            port = int(port or self._phone_prefs().get('port') or phone_server.DEFAULT_PORT)
        except (TypeError, ValueError):
            port = phone_server.DEFAULT_PORT
        if not self._phone_server.running:
            try:
                self._phone_server.start(port)
            except OSError as error:
                return {'error': f'Sunucu {port} kapısında açılamadı: {error}'}
            self._phone_set_prefs(port=port)
            self._log(f'Telefon sesi: sunucu açıldı (kapı {port}).')
        return self.phone_state()

    def phone_stop(self):
        if self._phone_server is not None and self._phone_server.running:
            self._phone_server.stop()
            self._log('Telefon sesi: sunucu kapatıldı.')
        return self.phone_state()

    def phone_set(self, voice=None, autostart=None):
        if voice is not None:
            self._phone_set_prefs(voice=str(voice or ''))
        if autostart is not None:
            self._phone_set_prefs(autostart=bool(autostart))
        return self.phone_state()

    def phone_remove(self, phone_id):
        self._phone_phones().remove(str(phone_id))
        return self.phone_state()

    def _phone_startup(self):
        """Uygulama acilisinda: istendiyse sunucu kendiliginden acilir (pencere kapaninca durur)."""
        if self._phone_prefs().get('autostart'):
            threading.Thread(target=self.phone_start, name='aktar-phone-boot', daemon=True).start()

    def _stop_phone_for_close(self):
        if self._phone_server is not None:
            self._phone_server.stop()
