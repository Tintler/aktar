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

import audio_trim
import audiobook
import drama3_tags
import emotion_tags
import text_speech
import voice_presets
from app_core import APP_DIR, ROOT
from tts import Engines


PREVIEW_TEXT = 'Merhaba, dublajda sesim böyle duyulacak.'   # F149 ses onizlemesi
PREVIEW_RECORDING = 12.0   # kayitli sesin klon kaydindan calinan en uzun sure (sn)


def _error(error):
    return {'error': str(error)}


class TtsMixin:
    def _engines(self):
        directory = Path(APP_DIR)
        cached = getattr(self, '_engines_cache', None)
        if cached is None or cached.app_dir != directory:
            self._engines_cache = Engines(directory, Path(ROOT) / 'engines', emit=self._emit,
                                          prefs=lambda: self.ui_prefs().get('tts', {}),
                                          transcribe=self._tts_transcribe, log=self._log, emotion=self._emotion_tag)
        return self._engines_cache

    # ------------------------------------------------------------------ duygu etiketleri (F168, deneysel)
    def _emotion_store(self):
        directory = Path(APP_DIR)
        store = getattr(self, '_emotion_cache', None)
        if store is None or store.directory != directory / emotion_tags.STORE_DIR:
            self._emotion_cache = store = emotion_tags.Store(directory)
        return store

    def _emotion_enabled(self):
        """ui.json tts.emotion_tags: 'off' kapali; yoksa (ya da eski 'words'/'llm') etiketli surum kullanilir."""
        return (self.ui_prefs().get('tts', {}).get('emotion_tags') or 'on') != 'off'

    def _emotion_allowed(self):
        """F171: Ayarlar'da secilen etiketler (ui.json tts.emotion_allowed; yoksa calistigi bilinenler)."""
        return drama3_tags.allowed(self.ui_prefs().get('tts', {}).get('emotion_allowed'))

    def _emotion_tag(self, book, text):
        """tts.Engines'in sordugu cumle etiketi: kitabin etiketli surumunden; kapaliysa ya da surum yoksa ''."""
        if not self._emotion_enabled():
            return ''
        try:
            return self._emotion_store().tag(book, text, self._emotion_allowed())
        except (OSError, ValueError):
            return ''

    def tts_emotion_catalog(self):
        """F171: Drama 3 etiket katalogu ve secili olanlar (Ayarlar)."""
        return {'tags': drama3_tags.public(), 'allowed': list(self._emotion_allowed())}

    def tts_emotions_books(self):
        """F170: etiketli surumu olan kitaplar (kitaplikta isaret icin)."""
        try:
            return self._emotion_store().books()
        except OSError:
            return []

    def tts_emotions_info(self, book, language='tr'):
        """F170: okuyucu icin: kitabin etiketli surumu, kitabin motoru etiket destekliyor mu (Drama 3), acik mi."""
        try:
            info = self._emotion_store().info(book)
        except (OSError, ValueError) as error:
            return _error(error)
        engines = self._engines()
        engine_id, _voice = engines.choice(language)
        supported = bool(engine_id and engines._manifests().get(engine_id, {}).get('emotion_tags'))
        allowed = self._emotion_allowed()
        missing = [tag for tag in allowed if info and tag not in (info.get('allowed') or drama3_tags.DEFAULT_TAGS)]
        return {'info': info, 'engine': supported, 'enabled': self._emotion_enabled(), 'allowed': list(allowed),
                'missing': missing}

    def tts_emotions_create(self, book, sections, method='llm', title=''):
        """F170: butun kitabin etiketli surumunu arka planda olusturur (kitapligin sag tik menusu). `sections`:
        [{'sentences', 'breaks'}] okuyucunun bolmesiyle. Okurken etiketleme yapilmaz: ses motoru ile dil modeli
        ayni anda bellegi dolduruyordu; is basinda ses motoru durdurulur, model sunucusunda bu isin yukledigi
        model sonunda bosaltilir. Ilerleme ve bitis 'tts_emotions' olayiyla."""
        if not hasattr(self, '_emotion_lock'):
            self._emotion_lock = threading.Lock()
        method = method if method in emotion_tags.METHODS else 'llm'
        allowed = self._emotion_allowed()
        if not allowed:
            return _error("Ayarlar → Ses'te Drama 3 için en az bir duygu etiketi seçin.")
        try:
            self._emotion_store()._path(book)
        except ValueError as error:
            return _error(error)
        sections = [{'sentences': [' '.join(str(s).split()) for s in (part or {}).get('sentences') or ()],
                     'breaks': [int(b) for b in (part or {}).get('breaks') or ()]} for part in sections or ()]
        total = sum(len(part['sentences']) for part in sections)
        if not total:
            return _error('Kitapta etiketlenecek metin yok.')
        with self._emotion_lock:
            job = getattr(self, '_emotion_job', None)
            if job is not None and job.is_alive():
                return _error('Duygu etiketleri zaten oluşturuluyor.')
            for name in ('_prepare_job', '_audiobook_job'):
                running = getattr(self, name, None)
                if running is not None and running.is_alive():
                    return _error('Ses hazırlanırken ya da sesli kitap kaydedilirken duygu etiketi oluşturulamaz.')
            cancel = threading.Event()
            self._emotion_cancel = cancel

            def progress(done, count):
                self._emit('tts_emotions', {'book': book, 'title': title, 'done': done, 'total': count})

            def work():
                from app_core import Client, keep_loaded, load_config, unload_models
                client, loaded = None, []
                try:
                    engines = getattr(self, '_engines_cache', None)
                    if engines is not None and engines.state != 'idle' and not engines._exporting:
                        engines.stop_worker()   # ses motoru bellegi bosalsin
                        engines._set('idle', '')
                    ask = None
                    if method == 'llm':
                        client = Client(load_config(), log=self._log)
                        loaded = keep_loaded(client, [client.cfg.get('model')], self._log)
                        ask = lambda prompt: client.chat([{'role': 'user', 'content': prompt}], temperature=0,
                                                         max_tokens=1500)
                    progress(0, total)
                    tags = emotion_tags.tag_book(sections, ask, cancel, progress, allowed)
                    info = self._emotion_store().save(book, method, sections, tags, allowed)
                    self._log(f'Duygu etiketleri: {info["tagged"]} konuşma etiketlendi ({title or book}).')
                    self._emit('tts_emotions', {'book': book, 'title': title, 'finished': True, 'info': info})
                except emotion_tags.Cancelled:
                    self._emit('tts_emotions', {'book': book, 'title': title, 'finished': True, 'cancelled': True})
                except Exception as error:
                    self._log(f'UYARI: Duygu etiketleri oluşturulamadı: {error}')
                    self._emit('tts_emotions', {'book': book, 'title': title, 'finished': True, 'error': str(error)})
                finally:
                    if loaded:
                        unload_models(client, loaded)

            self._emotion_job = threading.Thread(target=work, name='aktar-tts-emotions', daemon=True)
            self._emotion_job.start()
        return {'started': True, 'total': total}

    def tts_emotions_cancel(self):
        cancel = getattr(self, '_emotion_cancel', None)
        if cancel is not None:
            cancel.set()
        return True

    def tts_emotions_clear(self, book=None):
        """Kitabin etiketli surumunu siler (kitap verilmezse hepsini)."""
        try:
            self._emotion_store().clear(book)
        except (OSError, ValueError) as error:
            return _error(error)
        return True

    def _tts_transcribe(self, audio, language):
        """F158: klon kaydinin metni (Drama 3): Ayarlar'daki Whisper modeliyle kelime zamanli bolumler."""
        import speech
        from app_core import load_config
        ok, message = speech.available()
        if not ok:
            raise RuntimeError('Kaydın metni yazılmadı ve Whisper kullanılamıyor: ' + message)
        cfg = load_config()
        return speech.clip_segments(audio, cfg.get('whisper_model') or speech.DEFAULT_MODEL,
                                    cfg.get('whisper_device') or 'auto', language or '', self._log,
                                    cfg.get('whisper_cuda_dir') or '')['segments']

    def tts_server_check(self, url=None):
        """F158: Drama 3 sunucusunun saglik denetimi (Ayarlar'daki "Baglantiyi dene"). `url` bossa kayitli adres."""
        import drama3
        url = drama3.normalize_url(url or self.ui_prefs().get('tts', {}).get('drama3_url'))
        try:
            data = drama3.health(url)
        except drama3.ServerError as error:
            return _error(error)
        waiting = data.get('pending_completions')
        return {'ok': True, 'url': url,
                'message': f'Drama 3 sunucusu çalışıyor ({url})' + (f' · bekleyen istek: {waiting}' if waiting else '')}

    def tts_folder_check(self, folder=None):
        """F173: Drama 3 TR model klasorunun denetimi (Ayarlar'daki "Denetle"); sunucuyu baslatmaz."""
        import drama3_tr
        return drama3_tr.check_folder(folder if folder is not None else
                                      self.ui_prefs().get('tts', {}).get(drama3_tr.PREF_DIR))

    def tts_status(self):
        return self._engines().status()

    def tts_engines(self):
        return self._engines().engines()

    def tts_runtime(self):
        """F183: bellekte tutulan (isinmis) ses motoru, sol alttaki panel icin; motor hic acilmadiysa None.
        Yalnizca bellekteki durumu okur, motora istek atmaz."""
        engines = getattr(self, '_engines_cache', None)
        return {'engine': engines.runtime() if engines is not None else None}

    def tts_unload(self):
        """F183: isinmis ses motorunu durdurur (bellek bosalir); motoru kullanan is surerken reddedilir."""
        running = getattr(self, '_tool_running', None)
        if (running is not None and running() and self._tool['kind'] in ('dub', 'dubgen')) or any(
                getattr(self, name, None) is not None and getattr(self, name).is_alive()
                for name in ('_prepare_job', '_audiobook_job', '_speech_job')):
            return _error('Ses motoru şu an bir iş için kullanılıyor (ses hazırlama, kayıt ya da dublaj).')
        engines = getattr(self, '_engines_cache', None)
        if engines is not None:
            try:
                engines.unload()
            except RuntimeError as error:
                return _error(error)
            self._log('Ses motoru bellekten boşaltıldı.')
        return self.tts_runtime()

    def tts_load(self, language=None, voice=None):
        """Kitap dili icin secilen motoru ve sesi (arka planda) hazirlar. `voice`: sayfanin kendi sesi
        (sohbet, dublaj): '' okuyucunun sesi, 'preset:<kimlik>' ses kaydi ya da '<motor>/<ses>'."""
        job = getattr(self, '_emotion_job', None)
        if job is not None and job.is_alive():   # F170: dil modeli calisirken ses motoru bellege yuklenmez
            return {'state': 'error', 'message': 'Duygu etiketleri oluşturulurken ses motoru başlatılmaz; '
                    'bitmesini bekleyin ya da sağ üstteki işlerden durdurun.'}
        device = self.ui_prefs().get('tts', {}).get('device', 'auto')
        override = self._voice_override(voice)
        return self._engines().load(self._override_language(override, language), device, override)

    def tts_say(self, text, speed=1.0, book=None, language='tr', voice=None):
        try:
            override = self._voice_override(voice)
            return self._engines().say(text, speed, book, self._override_language(override, language), override)
        except Exception as error:
            return _error(error)

    def tts_group_chars(self, language='tr'):
        """F177: okuyucunun tek istekte birlestirebilecegi ardisik cumlelerin karakter siniri (0: cumle cumle)."""
        try:
            return self._engines().group_chars(language)
        except Exception as error:
            return _error(error)

    def tts_preview(self, voice='', text=''):
        """F149: bir sesi dinletir (dublaj ses secicileri): motor o sese hazirlanir (bloklar), kisa bir
        metin okunur. `text` bossa ornek cumle. Kayitli ses klon kaydi tasiyorsa motor yuklenmez, o kaydin
        basi calinir. Donen: tts_say gibi {'audio', 'duration'} ya da {'error'}."""
        recording = self._preset_recording(voice)
        if recording is not None:
            try:
                import voice_split
                return {'audio': voice_split.clip_base64(recording, 0, PREVIEW_RECORDING), 'recording': True}
            except (RuntimeError, OSError) as error:
                return _error(error)
        running = getattr(self, '_tool_running', None)
        if (running is not None and running() and self._tool['kind'] == 'dub') or self._audiobook_running():
            return {'error': 'Ses motoru şu an dublaj ya da sesli kitap için kullanılıyor.'}
        try:
            override = self._voice_override(voice)
            language = self._override_language(override, 'tr')
            error = self._load_and_wait(language, override)
            if error:
                return {'error': error}
            text = ' '.join(str(text or '').split())[:200] or PREVIEW_TEXT
            return self._engines().say(text, 1.0, None, language, override)
        except Exception as error:
            return _error(error)

    def _load_and_wait(self, language, override, cancel=None):
        """Motoru o sese hazirlar ve bitmesini bekler (bloklar). Hata metni ya da None."""
        engines = self._engines()
        device = self.ui_prefs().get('tts', {}).get('device', 'auto')
        for _attempt in range(3):   # baska bir ses yukleniyorsa o bitince yeniden istenir
            engines.load(language, device, override)
            deadline = time.monotonic() + 600
            while engines.state == 'loading' and time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    return 'Durduruldu.'
                time.sleep(0.2)
            if engines.state != 'ready':
                return engines.message or 'Ses motoru yüklenemedi.'
            if (engines.current.get('engine'), engines.current.get('voice')) == engines.choice(language, override):
                return None
        return 'Ses motoru başka bir ses için kullanılıyor.'

    def _preset_recording(self, ref):
        """Kayitli sesin (preset:<kimlik>) klon kaydi dosyasi; yoksa None (tarifli ses ya da motor sesi)."""
        ref = str(ref or '')
        if not ref.startswith('preset:'):
            return None
        preset = voice_presets.get(APP_DIR, ref[7:])
        for value in ((preset or {}).get('options') or {}).values():
            path = Path(str(value))
            if path.suffix.lower() in voice_presets.AUDIO_TYPES and path.is_file():
                return path
        return None

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

    def tts_cached_flags(self, book, sentences, speed=1.0, language='tr'):
        """F185: cumle basina hazir mi (okuyucu hazir cumleyi gruplamadan, onbellekten tek basina okur)."""
        try:
            return self._engines().cached_flags(book, sentences, speed, language or 'tr')
        except Exception as error:
            return _error(error)

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

    def tts_reference_peaks(self, path):
        """F173: klon kaydinin dalga bicimi {'duration', 'peaks'} (onayar penceresinde aralik secmek icin)."""
        try:
            return audio_trim.peaks(str(path))
        except (ValueError, RuntimeError, OSError) as error:
            return _error(error)

    def tts_reference_transcript(self, path, language='tr'):
        """F174: klon kaydinin kelime zamanli metni (Whisper, onbellekli): {'words': [[bas, son, kelime], ...]}."""
        import qa
        import speech
        from app_core import load_config
        try:
            model = load_config().get('whisper_model') or speech.DEFAULT_MODEL
            return audio_trim.transcript(str(path), self._tts_transcribe, qa.work_dir() / 'kayit-metni',
                                         language or '', model)
        except (ValueError, RuntimeError, OSError) as error:
            return _error(error)

    def tts_reference_audio(self, path):
        """F173/F174: kaydi dinlemek icin {'audio': base64, 'mime'} (secim ve oynatma imleci arayuzde)."""
        try:
            return audio_trim.listen_base64(str(path))
        except (ValueError, RuntimeError, OSError) as error:
            return _error(error)

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

    def tts_preset_order(self, ids):
        """F179: kayitli seslerin sirasi (Metinden ses > Kayitli sesler); tum ses secicileri bu sirayla listeler."""
        try:
            voice_presets.reorder(APP_DIR, [str(ident) for ident in ids or []])
        except OSError as error:
            return _error(error)
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

    # ------------------------------------------------------------------ metinden ses (F178)
    def _speech_running(self):
        job = getattr(self, '_speech_job', None)
        return job is not None and job.is_alive()

    def tts_speech_folder(self):
        """Ciktinin yazilacagi klasor (pencereyle secilir): {'folder'}; vazgecilirse None."""
        chosen = self._dialog('open_folder', 'Ses dosyalarının kaydedileceği klasörü seç')
        return {'folder': str(chosen)} if chosen else None

    def tts_speech_read(self, path):
        """Birakilan metin dosyasinin icerigi: {'text', 'name'}."""
        try:
            return {'text': text_speech.read_text(path), 'name': Path(path).stem}
        except (ValueError, OSError) as error:
            return _error(error)

    def tts_speech_create(self, sentences, gaps=None, breaks=None, voice='', folder='', name='', speed=1.0, fmt='wav'):
        """Metni `voice` sesiyle (''=Ayarlardaki ses, 'preset:<kimlik>', '<motor>/<ses>') okutup `folder`'a yazar.
        `breaks`: paragraf sonu cumle dizinleri. Arka planda; ilerleme ve sonuc 'tts_speech' olayiyla gelir."""
        if self._speech_running():
            return {'error': 'Bir ses kaydı zaten sürüyor.'}
        running = getattr(self, '_tool_running', None)
        if (running is not None and running() and self._tool['kind'] in ('dub', 'dubgen')) or self._audiobook_running():
            return {'error': 'Ses motoru şu an dublaj ya da sesli kitap için kullanılıyor.'}
        sentences = list(sentences or ())
        pairs = text_speech.clean(sentences, gaps)
        if not pairs:
            return {'error': 'Seslendirilecek metin yok.'}
        if sum(len(text) for text, _gap in pairs) > text_speech.TEXT_LIMIT:
            return {'error': 'Metin çok uzun (en fazla 200.000 karakter).'}
        folder = str(folder or '').strip()
        if not folder or not Path(folder).is_dir():
            return {'error': 'Kayıt klasörü bulunamadı; bir klasör seçin.'}
        fmt = fmt if fmt in text_speech.FORMATS else 'wav'
        override = self._voice_override(voice)
        if voice and override is None:
            return {'error': 'Seçilen ses bulunamadı.'}
        language = self._override_language(override, 'tr')
        # breaks gelen dizinlerdir; bos cumleler atlandigi icin pairs dizinlerine cevrilir
        kept = [i for i, text in enumerate(sentences) if ' '.join(str(text).split())]
        wanted = {int(i) for i in (breaks or ()) if isinstance(i, (int, float))}
        marks = [index for index, original in enumerate(kept) if original in wanted]
        try:
            target = text_speech.output_path(folder, name, pairs[0][0], fmt)
        except OSError as error:
            return _error(error)
        cancel = threading.Event()
        self._speech_cancel = cancel

        def work():
            try:
                self._emit('tts_speech', {'done': 0, 'total': len(pairs), 'loading': True})
                error = self._load_and_wait(language, override, cancel)
                if cancel.is_set():
                    raise text_speech.Cancelled('Durduruldu.')
                if error:
                    raise RuntimeError(error)
                engines = self._engines()
                groups = text_speech.group(pairs, engines.group_chars(language, override), marks)
                seconds = text_speech.write(engines, groups, speed, target, language, override,
                                            lambda done, total: self._emit('tts_speech', {'done': done, 'total': total}),
                                            cancel)
                self._log('Metinden ses kaydedildi: ' + str(target))
                try:
                    url = self._media.file_url(target)   # sayfada dinlemek icin
                except Exception:
                    url = ''
                self._emit('tts_speech', {'finished': True, 'path': str(target), 'url': url, 'duration': seconds,
                                          'count': len(pairs)})
            except text_speech.Cancelled:
                self._emit('tts_speech', {'finished': True, 'cancelled': True})
            except Exception as error:
                self._log(f'HATA: Metinden ses kaydedilemedi: {error}')
                self._emit('tts_speech', {'finished': True, 'error': str(error)})

        self._speech_job = threading.Thread(target=work, name='aktar-tts-speech', daemon=True)
        self._speech_job.start()
        return {'started': True, 'path': str(target), 'total': len(pairs)}

    def tts_speech_cancel(self):
        cancel = getattr(self, '_speech_cancel', None)
        if cancel:
            cancel.set()
        return True

    def _stop_tts_for_close(self):
        """Pencere kapaninca: hazirlama durur, motor sureci kapatilir."""
        self.tts_prepare_cancel()
        self.tts_audiobook_cancel()
        self.tts_speech_cancel()
        cancel = getattr(self, '_emotion_cancel', None)
        if cancel is not None:
            cancel.set()   # F168: model sunucusuyla etiketleme
        job = getattr(self, '_audiobook_job', None)
        if job is not None and job.is_alive():
            job.join(5)
        cached = getattr(self, '_engines_cache', None)
        if cached is not None:
            cached.shutdown()
