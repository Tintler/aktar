"""Sesli okumanin arka ucu (Bridge'e karisan sinif); Cevirgec bridge.py'nin sesli okuma bolumu.

Ses motorlari (EMA Lightning, VoxCPM ...) ayri surecler olarak calisir (tts.py, engines/protocol.py);
paketler APP_DIR/ses-motorlari altina kurulur, hazirlanan cumleler APP_DIR/ses-onbellegi'nde tutulur.
Motor sureci yalnizca okurken baslar ve pencere kapaninca durdurulur (uygulama kapaliyken hicbir sey
calismaz). Secimler ui.json 'tts' altindadir.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import audiobook
import voice_presets
from app_core import APP_DIR, ROOT
from tts import Engines


PREVIEW_TEXT = 'Merhaba, dublajda sesim böyle duyulacak.'   # F149 ses onizlemesi


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

    def tts_load(self, language=None, voice=None):
        """Kitap dili icin secilen motoru ve sesi (arka planda) hazirlar. `voice`: sayfanin kendi sesi
        (sohbet, dublaj): '' okuyucunun sesi, 'preset:<kimlik>' ses kaydi ya da '<motor>/<ses>'."""
        device = self.ui_prefs().get('tts', {}).get('device', 'auto')
        override = self._voice_override(voice)
        return self._engines().load(self._override_language(override, language), device, override)

    def tts_say(self, text, speed=1.0, book=None, language='tr', voice=None):
        try:
            override = self._voice_override(voice)
            return self._engines().say(text, speed, book, self._override_language(override, language), override)
        except Exception as error:
            return _error(error)

    def tts_preview(self, voice='', text=''):
        """F149: bir sesi dinletir (dublaj ses secicileri): motor o sese hazirlanir (bloklar), kisa bir
        metin okunur. `text` bossa ornek cumle. Donen: tts_say gibi {'audio', 'duration'} ya da {'error'}."""
        running = getattr(self, '_tool_running', None)
        if (running is not None and running() and self._tool['kind'] == 'dub') or self._audiobook_running():
            return {'error': 'Ses motoru şu an dublaj ya da sesli kitap için kullanılıyor.'}
        try:
            override = self._voice_override(voice)
            language = self._override_language(override, 'tr')
            engines = self._engines()
            device = self.ui_prefs().get('tts', {}).get('device', 'auto')
            for _attempt in range(3):   # baska bir ses yukleniyorsa o bitince yeniden istenir
                engines.load(language, device, override)
                deadline = time.monotonic() + 600
                while engines.state == 'loading' and time.monotonic() < deadline:
                    time.sleep(0.2)
                if engines.state != 'ready':
                    return {'error': engines.message or 'Ses motoru yüklenemedi.'}
                if (engines.current.get('engine'), engines.current.get('voice')) == engines.choice(language, override):
                    break
            text = ' '.join(str(text or '').split())[:200] or PREVIEW_TEXT
            return engines.say(text, 1.0, None, language, override)
        except Exception as error:
            return _error(error)

    # ------------------------------------------------------------------ sayfa sesleri (F141)
    def _voice_override(self, ref):
        """Ses secimi -> tts.Engines override'i ({'voice', 'options'}) ya da None (okuyucunun sesi)."""
        ref = str(ref or '').strip()
        if not ref:
            return None
        if ref.startswith('preset:'):
            preset = voice_presets.get(APP_DIR, ref[7:])
            if preset is None:
                return None
            return {'voice': preset['voice'], 'options': dict(preset.get('options') or {})}
        if re.fullmatch(r'[\w-]+/[\w.-]+', ref):
            return {'voice': ref, 'options': None}
        return None

    def _override_language(self, override, language=None):
        if override:
            spec = self._voice_specs().get(override['voice'])
            if spec:
                return spec.get('language') or 'tr'
        return language or 'tr'

    def tts_voices(self):
        """Sohbet ve dublaj ses secicileri icin: kayitli sesler ve motor sesleri [{value, label, group}]."""
        specs = self._voice_specs()
        result = []
        try:
            presets = voice_presets.list_presets(APP_DIR)
        except OSError:
            presets = []
        for item in presets:
            if item.get('voice') in specs:
                result.append({'value': 'preset:' + item['id'], 'label': item.get('name') or item['id'],
                               'group': 'Kayıtlı sesler', 'language': specs[item['voice']].get('language', 'tr')})
        for value, spec in specs.items():
            name = spec.get('name') or value
            result.append({'value': value, 'label': spec['engine_name'] if name == spec['engine_name'] else f'{spec["engine_name"]} · {name}',
                           'group': 'Ses motorları', 'language': spec.get('language', 'tr'),
                           # F148: tarif/kayit isteyen ses (kayitli ses olarak ayarlanir; dublaj konusmacilarinda gizli)
                           'configurable': bool(spec.get('options'))})
        return result

    # ------------------------------------------------------------------ sesli kitap (F141)
    def _audiobook_running(self):
        job = getattr(self, '_audiobook_job', None)
        return job is not None and job.is_alive()

    def tts_audiobook(self, title, author, chapters, speed=1.0, book=None, language='tr', fmt='m4b', cover=True):
        """Kitabin tamamini sesli kitap olarak yazar: 'm4b' (bolum isaretli tek dosya) ya da 'mp3'
        (secilen klasore bolum basina bir dosya). Ilerleme ve sonuc 'tts_audiobook' olayiyla gelir."""
        if self._audiobook_running():
            return {'error': 'Bir sesli kitap kaydı zaten sürüyor.'}
        fmt = fmt if fmt in audiobook.FORMATS else 'm4b'
        engines = self._engines()
        if engines.state != 'ready':
            return {'error': 'Ses motoru hazır değil.'}
        name = audiobook.safe_name(title)
        if fmt == 'mp3':
            target = self._dialog('open_folder', 'Sesli kitabın kaydedileceği klasörü seç')
        else:
            target = self._dialog('save_file', 'Sesli kitabı kaydet', name + '.m4b', ('Sesli kitap (*.m4b)',))
            if target and not str(target).lower().endswith('.m4b'):
                target = str(target) + '.m4b'
        if not target:
            return None
        art = None
        if cover and book:
            try:
                art = self._shelf().cover(book)
            except (ValueError, OSError, KeyError):
                art = None
        cancel = threading.Event()
        self._audiobook_cancel = cancel

        def progress(done, total, chapter, count):
            self._emit('tts_audiobook', {'done': done, 'total': total, 'chapter': chapter, 'chapters': count,
                                         'title': title, 'book': book})

        def work():
            try:
                result = audiobook.build(engines, chapters, target, fmt, title, author, art, speed, book,
                                         language or 'tr', progress, cancel, self._log)
                self._log('Sesli kitap kaydedildi: ' + result['output'])
                self._emit('tts_audiobook', dict(result, finished=True, format=fmt, title=title))
            except audiobook.Stopped as error:
                self._emit('tts_audiobook', {'finished': True, 'cancelled': True, 'error': str(error)})
            except Exception as error:
                self._log(f'HATA: Sesli kitap kaydedilemedi: {error}')
                self._emit('tts_audiobook', {'finished': True, 'error': str(error)})

        self._audiobook_job = threading.Thread(target=work, name='aktar-tts-audiobook', daemon=True)
        self._audiobook_job.start()
        return {'started': True, 'target': str(target)}

    def tts_audiobook_cancel(self):
        cancel = getattr(self, '_audiobook_cancel', None)
        if cancel:
            cancel.set()
        return True

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

    # ------------------------------------------------------------------ ses onayarlari (F137)
    def _voice_specs(self):
        """Kullanilabilir motorlarin sesleri: '<motor>/<ses>' -> motor.json ses kaydi (motor adiyla)."""
        specs = {}
        for engine in self._engines().engines():
            if not engine['mode']:
                continue
            for voice in engine['voices']:
                specs[f'{engine["id"]}/{voice["id"]}'] = dict(voice, engine_name=engine['name'])
        return specs

    def tts_presets(self):
        """{'presets', 'active'}: okuyucudaki ses secicinin listesi ve secili onayar."""
        try:
            items = voice_presets.list_presets(APP_DIR)
        except OSError as error:
            return _error(error)
        return {'presets': items, 'active': self.ui_prefs().get('tts', {}).get('active_preset', '')}

    def tts_preset_save(self, values):
        try:
            saved = voice_presets.save(APP_DIR, values, self._voice_specs())
        except (ValueError, OSError) as error:
            return _error(error)
        if self.ui_prefs().get('tts', {}).get('active_preset') == saved['id']:
            self._apply_preset(saved)       # duzenlenen secili ses hemen gecerli olur
        return dict(self.tts_presets(), saved=saved)

    def tts_preset_delete(self, ident):
        try:
            voice_presets.remove(APP_DIR, str(ident or ''))
        except (ValueError, OSError) as error:
            return _error(error)
        tts = dict(self.ui_prefs().get('tts', {}))
        if tts.get('active_preset') == ident:
            tts['active_preset'] = ''
            self.save_ui_prefs({'tts': tts})
        return self.tts_presets()

    def tts_preset_image(self, path=None):
        """Ses resmi: yol verilmezse dosya penceresi acilir. {'image': data URL}; vazgecilirse None."""
        path = path or self._dialog('open_file', 'Ses resmi seç', ('Görseller (' + ';'.join(voice_presets.IMAGE_TYPES) + ')',))
        if not path:
            return None
        try:
            return {'image': voice_presets.image_from_file(path)}
        except ValueError as error:
            return _error(error)
        except OSError as error:
            return {'error': f'Görsel açılamadı: {path} ({error.strerror or error})'}

    def tts_preset_apply(self, ident):
        """Onayari secili ses yapar (ui.json 'tts'); ident bos ise secim kalkar, Ayarlar'daki ses gecerli olur.
        Guncel tts tercihlerini dondurur; okuyucu motoru tts_load ile yeniden hazirlar."""
        if not ident:
            tts = dict(self.ui_prefs().get('tts', {}), active_preset='')
            self.save_ui_prefs({'tts': tts})
            return {'tts': tts}
        preset = voice_presets.get(APP_DIR, str(ident))
        if preset is None:
            return {'error': 'Ses kaydı bulunamadı.'}
        if preset['voice'] not in self._voice_specs():
            return {'error': 'Bu sesin motoru kurulu değil; Ayarlar → Sesli okuma bölümünden kurun.'}
        return {'tts': self._apply_preset(preset)}

    def _apply_preset(self, preset):
        spec = self._voice_specs().get(preset['voice'], {})
        language = spec.get('language', 'tr')
        tts = dict(self.ui_prefs().get('tts', {}))
        tts['voices'] = dict(tts.get('voices') or {}, **{language: preset['voice']})
        tts['options'] = dict(tts.get('options') or {}, **{preset['voice']: dict(preset.get('options') or {})})
        tts['active_preset'] = preset['id']
        self.save_ui_prefs({'tts': tts})
        return tts

    def _stop_tts_for_close(self):
        """Pencere kapaninca: hazirlama durur, motor sureci kapatilir."""
        self.tts_prepare_cancel()
        self.tts_audiobook_cancel()
        job = getattr(self, '_audiobook_job', None)
        if job is not None and job.is_alive():
            job.join(5)
        cached = getattr(self, '_engines_cache', None)
        if cached is not None:
            cached.shutdown()
