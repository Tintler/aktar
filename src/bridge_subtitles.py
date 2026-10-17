"""Altyazi araclari ve klip (F118) arka ucu (Bridge'e karisan sinif).

Oynatici ve Altyazi Cevir sayfalarinin ortak araclari:
  - subtitle_export: altyaziyi zamanlama duzeltmesiyle istenen bicimde kaydeder (Whisper
    transkriptinde kelime zamanli/karaoke bicimler dahil).
  - subtitle_align: altyaziyi Whisper'in konusma zamanlarina gore otomatik hizalar.
  - subtitle_ocr: goruntu tabanli (PGS/VobSub) akisi OCR ile okuyup videonun yanina SRT yazar.
  - whisper_words: kelime zamanlari olmayan eski Whisper transkriptini yeniden cikarir.
  - clip_save: secilen araligi altyazili/altyazisiz klip olarak kaydeder.
  - dub_create: secili altyaziyi sesli okuma motoruyla seslendirip videoya dublaj parcasi ekler (dub.py).
  - speakers_find / dub_speakers / speakers_rename (F146): konusmaci ayrimi (voice_split.py); dublajda
    konusmaci basina ses, transkriptte ve soru-cevapta etiket.

Altyazi kaynaklari oynaticinin anahtarlariyla verilir: 'stream:<index>', 'file:<yol>',
'whisper', 'ocr:<index>'. Uzun isler tek bir arka plan is parcaciginda calisir ve 'subtool'
olayiyla ilerler; pencere kapaninca durdurulur.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

import clip
import dub
import media_server
import qa
import speech
import subtitle
import subtitle_export
import subtitle_ocr
import subtitle_sync
import voice_split
from app_core import GracefulStop, load_config, read
from media import extract_subtitle, subtitle_streams

WHISPER_KEY = 'whisper'
_SAFE = re.compile(r'[^\w.-]+')


class Source:
    """Cozumlenmis altyazi kaynagi: belge (kind, payload) ya da Whisper sonucu."""

    def __init__(self, label, language='', kind='', payload=None, whisper=None):
        self.label = label
        self.language = language
        self.kind = kind
        self.payload = payload
        self.whisper = whisper

    @property
    def words(self):
        return bool(self.whisper) and speech.has_words(self.whisper)

    def intervals(self):
        if self.whisper:
            return [(item['start'], item['end']) for item in self.whisper['segments']]
        return subtitle_sync.cue_intervals(self.kind, self.payload)

    def render(self, fmt, timing=None, length=None, style=None):
        if self.whisper:
            return subtitle_export.render_whisper(self.whisper, fmt, timing, length, style)
        return subtitle_export.render_document(self.kind, self.payload, fmt, timing, length, style)

    def extension(self, fmt):
        return subtitle_export.extension(fmt, 'srt' if self.whisper else self.kind)


class SubtitleToolsMixin:
    def _init_subtools(self):
        self._tool = None   # {'kind', 'path', 'thread', 'cancel'}

    def _tool_running(self):
        return self._tool is not None and self._tool['thread'].is_alive()

    def _stop_subtools_for_close(self):
        tool = self._tool
        if tool is not None:
            tool['cancel'].set()
            tool['thread'].join(5)

    # ------------------------------------------------------------------ kaynak
    def _whisper_for(self, path):
        """Acik sayfadaki (oynatici / Altyazi Cevir) ya da onbellekteki Whisper transkripti."""
        player = getattr(self, '_player_video', None)
        if player is not None and player.path == path and player.whisper:
            return player.whisper
        if getattr(self, '_video', None) == path and getattr(self, '_whisper', None):
            return self._whisper
        cfg = load_config()
        return speech.load_cached(path, cfg['whisper_model'], cfg['whisper_language'])

    def _stream(self, path, index):
        player = getattr(self, '_player_video', None)
        streams = player.streams if player is not None and player.path == path and player.streams else None
        if streams is None and getattr(self, '_video', None) == path and getattr(self, '_streams', None):
            streams = [item for item in self._streams if item.get('index') != WHISPER_KEY]
        if streams is None:
            streams = subtitle_streams(path)
        stream = next((item for item in streams if item.get('index') == index), None)
        if stream is None:
            raise ValueError('Altyazı akışı bulunamadı.')
        return stream

    def _source(self, path, key):
        """Anahtardaki altyaziyi okur. Hata: ValueError (kullaniciya gosterilir)."""
        path = Path(str(path))
        key = str(key or '')
        if key == WHISPER_KEY or key.startswith(WHISPER_KEY + ':'):
            result = self._whisper_for(path)
            if not result:
                raise ValueError('Bu videonun Whisper transkripti yok; önce sesten oluşturun.')
            return Source('Whisper', result.get('language', ''), whisper=result)
        if key.startswith('ocr:') or key.startswith('stream:'):
            index = int(key.split(':', 1)[1])
            stream = self._stream(path, index)
            if key.startswith('ocr:') or stream.get('image'):
                cached = subtitle_ocr.load_cached(path, index)
                if not cached:
                    raise ValueError('Görüntü tabanlı altyazı henüz okunmadı; önce OCR ile okuyun.')
                kind, payload = subtitle_export.segments_document(cached['segments'])
                return Source('OCR', stream.get('language', ''), kind, payload)
            if not stream.get('supported'):
                raise ValueError('Desteklenmeyen altyazı codec: ' + str(stream.get('codec')))
            stem = _SAFE.sub('_', path.stem)[:40] or 'video'
            target = qa.work_dir() / 'qa' / f'{stem}.s{index}.tools.{stream["extension"]}'
            extract_subtitle(path, index, target, codec=stream.get('codec', ''))
            kind, payload = subtitle.parse_by_extension(read(target), target.suffix)
            return Source(stream.get('title') or stream.get('codec', ''), stream.get('language', ''), kind, payload)
        if key.startswith('file:'):
            file = Path(key[5:])
            kind, payload = subtitle.parse_by_extension(read(file), file.suffix)
            return Source(file.name, '', kind, payload)
        raise ValueError('Bilinmeyen altyazı kaynağı.')

    def subtitle_info(self, path, key):
        """Disa aktarma penceresi icin: kaynagin bicimi, kelime zamani var mi, bicim listesi."""
        try:
            source = self._source(path, key)
        except (RuntimeError, ValueError, OSError) as error:
            return {'error': str(error)}
        whisper = source.whisper is not None
        formats = [{'id': name, 'label': label + (f' (.{source.kind})' if name == 'source' and not whisper else ''),
                    'words': needs}
                   for name, (label, _, needs) in subtitle_export.FORMATS.items()
                   if not (needs and not whisper) and not (name == 'source' and whisper)]
        return {'kind': 'srt' if whisper else source.kind, 'whisper': whisper, 'words': source.words,
                'language': source.language, 'formats': formats, 'style': subtitle_export.DEFAULT_STYLE}

    # ------------------------------------------------------------------ disa aktarma
    def _default_subtitle_name(self, path, source, fmt):
        language = _SAFE.sub('', str(source.language or ''))[:8]
        parts = [Path(path).stem] + ([language] if language else []) + (['karaoke'] if fmt == 'karaoke' else [])
        return '.'.join(parts) + '.' + source.extension(fmt)

    def subtitle_export(self, path, key, fmt='source', timing=None, style=None):
        """Altyaziyi (zamanlama duzeltmesiyle) kayit penceresinde secilen yere yazar."""
        path = Path(str(path))
        try:
            source = self._source(path, key)
            if fmt in subtitle_export.WORD_FORMATS and not source.words:
                return {'error': 'Bu transkriptte kelime zamanları yok. Önce "Kelime zamanlarını çıkar" '
                                 'ile Whisper\'ı yeniden çalıştırın.', 'need_words': True}
            text = source.render(fmt, subtitle_sync.Timing.of(timing), style=style)
        except (RuntimeError, ValueError, OSError) as error:
            return {'error': 'Dışa aktarılamadı: ' + str(error)}
        ext = source.extension(fmt)
        names = {'srt': 'SubRip', 'ass': 'Advanced SubStation', 'ssa': 'SubStation', 'vtt': 'WebVTT', 'json': 'JSON'}
        target = self._dialog('save_file', 'Altyazıyı kaydet', self._default_subtitle_name(path, source, fmt),
                              (f'{names.get(ext, ext.upper())} (*.{ext})',), str(path.parent))
        if not target:
            return None
        target = Path(target)
        if target.suffix.lower() != '.' + ext:
            target = target.with_name(target.name + '.' + ext)
        if target.resolve() == path.resolve():
            return {'error': 'Altyazı videonun üzerine yazılamaz.'}
        try:
            target.write_text(text, encoding='utf-8', newline='\n')
        except OSError as error:
            return {'error': 'Kaydedilemedi: ' + str(error)}
        self._log(f'Altyazı kaydedildi: {target}')
        return {'path': str(target), 'name': target.name, 'folder': str(target.parent)}

    # ------------------------------------------------------------------ arka plan isleri
    def subtool_state(self):
        tool = self._tool
        return {'kind': tool['kind'], 'path': str(tool['path'])} if self._tool_running() else None

    def subtool_cancel(self):
        if self._tool_running():
            self._tool['cancel'].set()
            self._log('Altyazı aracı durduruluyor…')
        return True

    def _start_tool(self, kind, path, work):
        """`work(cancel, progress)` -> sonuc sozlugu; bitince 'subtool' olayi gonderilir."""
        if self._tool_running():
            return {'error': 'Önceki altyazı/klip işi sürüyor.'}
        cancel = threading.Event()
        path = Path(str(path))

        def progress(done, total, stage=''):
            self._emit('subtool', {'kind': kind, 'path': str(path), 'state': 'running', 'stage': stage,
                                   'progress': {'done': float(done), 'total': float(total or 0)}})

        def run():
            try:
                result = work(cancel, progress)
            except GracefulStop as stop:
                self._emit('subtool', {'kind': kind, 'path': str(path), 'state': 'cancelled', 'message': str(stop)})
            except (RuntimeError, ValueError, OSError) as error:
                self._log(str(error))
                self._emit('subtool', {'kind': kind, 'path': str(path), 'state': 'error', 'message': str(error)})
            except Exception as error:  # beklenmeyen hata arayuzu kilitli birakmasin
                self._log('Beklenmeyen hata: ' + repr(error))
                self._emit('subtool', {'kind': kind, 'path': str(path), 'state': 'error',
                                       'message': 'Beklenmeyen hata: ' + repr(error)})
            else:
                self._emit('subtool', {'kind': kind, 'path': str(path), 'state': 'done', 'result': result})

        thread = threading.Thread(target=run, name='aktar-subtool-' + kind, daemon=True)
        self._tool = {'kind': kind, 'path': path, 'thread': thread, 'cancel': cancel}
        # 'running' isten once gider: is cok cabuk biterse 'done' ondan sonra gelmeli.
        self._emit('subtool', {'kind': kind, 'path': str(path), 'state': 'running', 'stage': '',
                               'progress': {'done': 0, 'total': 0}})
        thread.start()
        return {'started': True}

    def _transcribe(self, path, cancel, progress, need_words=False, audio_track=None):
        cfg = load_config()
        result = speech.transcribe(path, cfg['whisper_model'], cfg['whisper_device'], cfg['whisper_language'],
                                   progress=lambda done, total: progress(done, total, 'whisper'),
                                   cancelled=cancel.is_set, log=self._log, cuda_dir=cfg.get('whisper_cuda_dir', ''),
                                   audio_track=audio_track, need_words=need_words)
        player = getattr(self, '_player_video', None)
        if player is not None and player.path == path and (
                need_words or not player.whisper or player.whisper.get('audio_track') == audio_track):
            player.whisper = result
            self._push_player(player)
        if getattr(self, '_video', None) == path and audio_track is None:
            self._whisper = result
        if hasattr(self, '_forget_native_sources'):
            self._forget_native_sources(path)   # mpv altyazisi yeni transkriptten uretilsin
        return result

    def subtitle_align(self, path, key, audio_index=None):
        """Altyaziyi Whisper konusma zamanlarina gore hizalar (Whisper yoksa once cikarilir)."""
        path = Path(str(path))
        if str(key).startswith(WHISPER_KEY):
            return {'error': 'Whisper transkripti zaten sesle hizalı.'}
        ok, message = speech.available()
        whisper = self._whisper_for(path)

        def work(cancel, progress):
            source = self._source(path, key)
            result = whisper
            if not result:
                if not ok:
                    raise ValueError(message)
                self._log('Otomatik hizalama için önce konuşmadan metin çıkarılıyor…')
                result = self._transcribe(path, cancel, progress, audio_track=self._player_track(path, audio_index))
            progress(0, 0, 'align')
            found = subtitle_sync.auto_align(source.intervals(), subtitle_sync.speech_intervals(result['segments']))
            self._log(f'Otomatik hizalama: kaydırma {found["offset"]:+.2f} sn, hız x{found["scale"]:.5f}, '
                      f'uyum {found["before"]:.2f} -> {found["score"]:.2f} ({found["confidence"]}).')
            return found
        return self._start_tool('align', path, work)

    def _player_track(self, path, audio_index):
        player = getattr(self, '_player_video', None)
        if player is not None and player.path == path and audio_index is not None:
            return self._audio_track_arg(player, audio_index)
        return None

    def whisper_words(self, path, audio_index=None):
        """Kelime zamanlari icin Whisper'i (gerekirse yeniden) calistirir."""
        path = Path(str(path))
        ok, message = speech.available()
        if not ok:
            return {'error': message}
        track = self._player_track(path, audio_index)

        def work(cancel, progress):
            result = self._transcribe(path, cancel, progress, need_words=True, audio_track=track)
            if not speech.has_words(result):
                # Eski aktar-whisper paketi kelime zamanlarini dondurmez; is sessizce "bitmesin".
                raise RuntimeError('Whisper kelime zamanlarını döndürmedi. Aktar\'ın yanındaki "aktar-whisper" '
                                   'klasörü bu sürümden eski olabilir: yeni derlenen dist\\aktar-whisper '
                                   'klasörünü Aktar ile aynı yere kopyalayın.')
            return {'segments': len(result['segments']), 'words': speech.has_words(result)}
        return self._start_tool('whisper', path, work)

    def subtitle_ocr(self, path, stream_index):
        """Goruntu tabanli altyaziyi okur; videonun yanina <video>.<dil>.srt yazar."""
        path = Path(str(path))
        try:
            stream = self._stream(path, int(stream_index))
        except (RuntimeError, ValueError) as error:
            return {'error': str(error)}
        if not stream.get('image'):
            return {'error': 'Bu akış zaten metin tabanlı.'}

        def work(cancel, progress):
            cfg = load_config()
            result = subtitle_ocr.recognize(path, stream, cfg, log=self._log, cancelled=cancel.is_set,
                                            progress=lambda stage, done, total: progress(done, total, stage))
            kind, payload = subtitle_export.segments_document(result['segments'])
            language = _SAFE.sub('', str(stream.get('language') or ''))[:8]
            target = _unique(path, path.stem + ('.' + language if language else ''), 'srt')
            target.write_text(subtitle.render_srt(payload), encoding='utf-8', newline='\n')
            self._log(f'OCR altyazısı yazıldı: {target}')
            self._after_ocr(path, int(stream['index']))
            return {'key': f'ocr:{int(stream["index"])}', 'output': str(target), 'name': target.name,
                    'lines': len(result['segments'])}
        return self._start_tool('ocr', path, work)

    def _after_ocr(self, path, index):
        """OCR bitti: Altyazi Cevir'deki akis cevrilebilir olur, oynaticinin CC menusu yenilenir."""
        if hasattr(self, '_forget_native_sources'):
            self._forget_native_sources(path)
        if getattr(self, '_video', None) == path:
            for item in self._streams:
                if item.get('index') == index:
                    item.update(supported=True, ocr=True, extension='srt')
            self._push_translate()
        player = getattr(self, '_player_video', None)
        if player is not None and player.path == path:
            self._push_player(player)

    # ------------------------------------------------------------------ dublaj (F141)
    def _dub_segments(self, path, key):
        source = self._source(path, key)
        if source.whisper:
            return source.whisper['segments']
        return qa.transcript_from_cues(subtitle.cues_of(source.kind, source.payload))

    def _wait_voice(self, engines, language, device, override, cancel):
        """Motoru verilen sese hazirlar (bloklar); durdurulursa GracefulStop."""
        engines.load(language, device, override)
        while engines.state == 'loading':
            if cancel.is_set():
                raise GracefulStop('Dublaj durduruldu.')
            cancel.wait(0.2)
        if engines.state != 'ready':
            raise RuntimeError(engines.message or 'Ses motoru yüklenemedi.')

    def _voice_spec(self, engines, ref, fallback_language='tr'):
        override = self._voice_override(ref)
        language = self._override_language(override, fallback_language)
        engine_id, _voice = engines.choice(language, override)
        can_speed = any(item['id'] == engine_id and item['speed'] for item in engines.engines())
        return {'override': override, 'language': language, 'can_speed': can_speed}

    def _auto_voices(self, speakers, main):
        """Atanmamis konusmacilara farkli Turkce sesler: en cok konusan ana sesi alir, digerleri sirayla."""
        specs = self._voice_specs()

        def ready(value):   # kayitli onayar ya da her secenegi varsayilanli ses (klon gibi kayit isteyenler degil)
            spec = specs.get(value)
            return value.startswith('preset:') or (spec is not None and all(
                str(option.get('default') or '').strip() for option in spec.get('options') or []))
        same = {main}
        if not str(main).startswith('preset:'):   # ana ses bos ya da motor sesiyse gercekte hangi ses oldugu
            engine_id, voice_id = self._engines().choice('tr', self._voice_override(main))
            same.add(f'{engine_id}/{voice_id}')
        refs = [item['value'] for item in self.tts_voices()
                if item.get('language') == 'tr' and item['value'] not in same and ready(item['value'])]
        result, index = {}, 0
        for number, item in enumerate(speakers):
            if number == 0 or not refs:
                result[str(item['id'])] = main or ''
            else:
                result[str(item['id'])] = refs[index % len(refs)]
                index += 1
        return result

    def dub_create(self, path, key, options=None, timing=None, voice='', voices=None):
        """Secili altyaziyi seslendirip videonun yanina dublajli kopya (.dublaj.mkv) ya da ses (.m4a) yazar.
        `voice`: '' (sesli okumanin Turkce sesi), 'preset:<kimlik>' ya da '<motor>/<ses>'.
        F146: options.separate -> muzik/efekt korunur; options.speakers -> konusmaci basina ses
        (`voices` {'0': ses}; verilmeyen konusmacilara farkli sesler otomatik atanir)."""
        path = Path(str(path))
        if not key:
            return {'error': 'Seslendirilecek altyazıyı seçin (CC menüsü).'}
        options = dub.options_of(options)
        if options['separate'] or options['speakers']:
            ok, message = voice_split.available()
            if not ok:
                return {'error': message}
        try:
            segments = self._dub_segments(path, key)
        except (RuntimeError, ValueError, OSError) as error:
            return {'error': str(error)}
        override = self._voice_override(voice)
        language = self._override_language(override, 'tr')
        engines = self._engines()
        engine_id, _voice = engines.choice(language, override)
        if engine_id is None:
            return {'error': 'Dublaj için kurulu ses motoru yok; Ayarlar → Ses → Sesli okuma bölümünden kurun.'}
        can_speed = any(item['id'] == engine_id and item['speed'] for item in engines.engines())
        stem = path.stem + '.dublaj'
        target = _unique(path, stem, options['format'])
        player = getattr(self, '_player_video', None)
        info = player.info if player is not None and player.path == path and player.info else None
        device = self.ui_prefs().get('tts', {}).get('device', 'auto')
        # '' otomatik (atanmaz), '=' ana ses, digerleri ses secimi
        chosen = {str(k): (voice if str(v) == '=' else str(v)) for k, v in (voices or {}).items() if v}

        def load_voice(cancel, progress):
            def load(other, other_language):
                progress(0, 0, 'engine')
                self._wait_voice(engines, other_language, device, other, cancel)
            return load

        def work(cancel, progress):
            probed = info or media_server.probe(path)
            has_audio = bool(probed.get('audio'))
            stems, plan, specs = None, None, None
            if options['speakers']:
                speakers = voice_split.diarize(path, options['audio'], log=self._log, progress=progress,
                                               cancelled=cancel.is_set)
                lines = dub.lines_of(segments, timing)
                mapping = dict(self._auto_voices(voice_split.summary(speakers, lines), voice), **chosen)
                plan = dub.voice_plan(lines, speakers, {k: v for k, v in mapping.items() if v and v != voice})
                specs = {ref: self._voice_spec(engines, ref) for ref in set(plan) if ref}
                self._log(f'Dublaj: {speakers["count"]} konuşmacı, {len(specs) + 1} ses.')
            if options['separate'] and has_audio:
                stems = voice_split.separate(path, options['audio'], log=self._log, progress=progress,
                                             cancelled=cancel.is_set)
            progress(0, 0, 'engine')
            self._wait_voice(engines, language, device, override, cancel)
            self._log(f'Dublaj başlıyor: {path.name} ({len(segments)} satır) -> {target.name}')
            result = dub.build(engines, path, segments, target, options, timing, language, override,
                               duration=probed.get('duration') or 0.0, has_audio=has_audio,
                               can_speed=can_speed, progress=progress, cancelled=cancel.is_set, log=self._log,
                               plan=plan, voices=specs, stems=stems, load_voice=load_voice(cancel, progress))
            self._log('Dublaj kaydedildi: ' + result['output'])
            return dict(result, name=target.name)
        return self._start_tool('dub', path, work)

    # ------------------------------------------------------------------ konusmacilar (F146)
    def dub_speakers(self, path, key=None, timing=None):
        """Konusmaci ayrimi hazirsa konusmacilar [{id, name, seconds, lines, sample}], yoksa bos liste."""
        path = Path(str(path))
        ok, message = voice_split.available()
        try:
            data = voice_split.load_speakers(path)
        except OSError:
            data = None
        lines = []
        if data and key:
            try:
                lines = dub.lines_of(self._dub_segments(path, key), timing)
            except (RuntimeError, ValueError, OSError):
                lines = []
        return {'available': ok, 'message': message, 'ready': data is not None,
                'speakers': voice_split.summary(data, lines)}

    def speakers_find(self, path, audio=None, count=0):
        """Konusmacilari (yeniden) ayirir: arka planda 'diarize' isi. `audio`: ses akisinin GLOBAL index'i,
        `count`: konusmaci sayisi (0: otomatik)."""
        path = Path(str(path))
        ok, message = voice_split.available()
        if not ok:
            return {'error': message}
        track = None if audio in (None, '') else int(audio)
        count = max(0, min(20, int(count or 0)))

        def work(cancel, progress):
            data = voice_split.diarize(path, track, count, log=self._log, progress=progress,
                                       cancelled=cancel.is_set, fresh=True)
            self._after_speakers(path)
            return {'speakers': data['count']}
        return self._start_tool('diarize', path, work)

    def speakers_rename(self, path, names):
        path = Path(str(path))
        try:
            data = voice_split.save_names(path, names)
        except (OSError, ValueError) as error:
            return {'error': str(error)}
        self._after_speakers(path)
        return {'speakers': voice_split.summary(data)}

    def _after_speakers(self, path):
        """Konusmacilar degisti: kutuphane satiri (transkript etiketleri) yenilenir."""
        refresh = getattr(self, '_refresh_entry', None)
        if refresh is not None:
            try:
                refresh(path)
            except Exception as error:  # kutuphane acik degilse onemsiz
                self._log('Kütüphane satırı yenilenemedi: ' + str(error))

    # ------------------------------------------------------------------ klip
    def clip_save(self, path, start, end, options=None, key=None, timing=None, fmt='source', style=None):
        """Secilen araligi klip olarak kaydeder (kayit penceresi -> arka planda FFmpeg)."""
        path = Path(str(path))
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            return {'error': 'Klip aralığı geçersiz.'}
        if end - start < 0.1:
            return {'error': 'Klip en az 0,1 saniye olmalı.'}
        options = clip.options_of(options)
        text, ext = None, 'srt'
        if options['subtitles'] != 'none':
            if not key:
                return {'error': 'Klibe eklenecek altyazıyı seçin (CC menüsü).'}
            try:
                source = self._source(path, key)
                if fmt in subtitle_export.WORD_FORMATS and not source.words:
                    return {'error': 'Bu transkriptte kelime zamanları yok; önce kelime zamanlarını çıkarın.',
                            'need_words': True}
                timing = subtitle_sync.Timing.of(timing)
                window = subtitle_sync.Timing(timing.scale, timing.offset - start)
                style = dict(style or {})
                if options['subtitles'] == 'burn':
                    if options['font_size']:
                        style['size'] = options['font_size']
                    # Duz altyazi yakilirken secilen boyut ve renkle ASS'ye cevrilir (kaynagin ASS stilleri
                    # 'Kaynagin bicimi' secilirse korunur); kelime vurgulu SRT boyutu force_style ile alir.
                    if fmt in ('srt', 'vtt') or (fmt == 'source' and (source.whisper or source.kind not in ('ass', 'ssa'))):
                        fmt = 'ass'
                text = source.render(fmt, window, end - start, style)
                ext = source.extension(fmt)
            except (RuntimeError, ValueError, OSError) as error:
                return {'error': 'Klip altyazısı hazırlanamadı: ' + str(error)}
            if ext == 'json':
                return {'error': 'JSON klibe eklenemez; bir altyazı biçimi seçin.'}
        name = clip.default_name(path, start, end, options['format'])
        target = self._dialog('save_file', 'Klibi kaydet', name, (f'{options["format"].upper()} (*.{options["format"]})',),
                              str(path.parent))
        if not target:
            return None
        target = Path(target)
        if target.suffix.lower() != '.' + options['format']:
            target = target.with_name(target.name + '.' + options['format'])
        if target.resolve() == path.resolve():
            return {'error': 'Klip kaynak videonun üzerine yazılamaz.'}
        player = getattr(self, '_player_video', None)
        info = player.info if player is not None and player.path == path and player.info else None

        def work(cancel, progress):
            probed = info or media_server.probe(path)
            self._log(f'Klip kaydediliyor: {target.name} ({qa.format_time(start)}–{qa.format_time(end)})')
            result = clip.save(path, start, end, target, options, probed, text, ext,
                               progress=lambda done, total: progress(done, total, 'clip'), cancelled=cancel.is_set)
            self._log('Klip kaydedildi: ' + result['output'])
            return dict(result, name=target.name)
        return self._start_tool('clip', path, work)


def _unique(video, stem, extension):
    directory = Path(video).parent
    candidate = directory / f'{stem}.{extension}'
    index = 2
    while candidate.exists():
        candidate = directory / f'{stem} ({index}).{extension}'
        index += 1
    return candidate
