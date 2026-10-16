"""Oynatici + videoya soru sor arka ucu (Bridge'e karisan sinif; eski qa_panel.VideoQAPanel).

Video media_server uzerinden HTML5 <video>'ya verilir. Hazirlik (transkript -> video haritasi
ve ozet), soru-cevap, Whisper ve altyazi yukleme arka plan is parcaciklarindadir; sonuclar
'player' olayiyla gelir. Ayni video yeniden acilinca sohbet korunur; baska video acilinca
oncekinin isleri durdurulur.
"""
from __future__ import annotations

import threading
from pathlib import Path

import chat_templates
import library
import media_server
import qa
import speech
import subtitle_ocr
from app_core import GracefulStop, load_config, save_json
from bridge_library import pending_entry, reasoning_feed
from media import audio_label, audio_streams, sidecar_subtitles, subtitle_streams

GREETING = ('Merhaba! İzlediğiniz videoyla ilgili sorularınız mı var? '
            'Size yardımcı olmaktan memnuniyet duyarım.')
NO_SUBTITLE = ('Bu videoda metin tabanlı altyazı yok. Soru sormak için konuşmayı sesten '
               'metne çevirebilirsiniz (Whisper; ilk kullanımda model indirilir).')
WHISPER_KEY = 'whisper'


def subtitle_sources(video, streams):
    """CC menusu kaynaklari: videodaki metin akislari, goruntu tabanli akislar (OCR ile okunur)
    ve videonun yanindaki dosyalar."""
    sources = []
    for item in streams or []:
        if item.get('image'):
            ready = subtitle_ocr.is_ready(video, item['index'])
            label = ' · '.join(part for part in (item.get('language') or '', item.get('title') or '',
                                                 item.get('codec') or '') if part)
            sources.append({'key': f'ocr:{item["index"]}', 'kind': 'image', 'ready': ready,
                            'label': (label or ('Akış ' + str(item['index']))) + (' · OCR' if ready else '')})
            continue
        if not item.get('supported'):
            continue
        label = ' · '.join(part for part in (item.get('language') or '', item.get('title') or '',
                                             (item.get('extension') or '').upper()) if part)
        sources.append({'key': f'stream:{item["index"]}', 'kind': 'stream', 'stream': item,
                        'label': label or ('Akış ' + str(item['index']))})
    for path in sidecar_subtitles(video):
        sources.append({'key': 'file:' + str(path), 'kind': 'file', 'path': str(path), 'label': path.name})
    return sources


def video_parts(parts, video):
    """qa.split_citations ciktisi -> sohbet bileseninin JSON bicimi (atif: o ana git)."""
    result = []
    for kind, value in parts:
        if kind == 'cite':
            result.append({'type': 'cite', 'items': [{'path': str(video), 'start': item['start'],
                                                       'label': item['label'], 'title': ''} for item in value]})
        else:
            result.append({'type': 'text', 'text': str(value)})
    return result


class VideoSession:
    """Acik videonun durumu: akislar, transkript oturumu, sohbet ve calisan isler."""

    def __init__(self, path):
        self.path = Path(path)
        self.info = None              # media_server.probe
        self.streams = None           # altyazi akislari
        self.audio = []               # media.audio_streams
        self.session = None           # qa.VideoQA
        self.key = library.file_chat_key(self.path)
        saved = library.load_chat(self.key)   # onceki acilistan kalan sohbet
        self.entries = [('note', GREETING)] + saved['entries']
        self.history = saved['history']
        self.chips = None             # {'title', 'items': [{label, action, value}]}
        self.status = 'Hazırlanıyor…'
        self.progress = None          # {'done', 'total'} ya da None (belirsiz)
        self.preparing = False
        self.transcribing = False
        self.asking = False
        self.ready = False
        self.source_key = ''          # soru-cevap transkript kaynagi
        self.whisper = None           # speech sonucu (onbellekte varsa)
        self.cancel = threading.Event()
        self.prepare_track = None


class PlayerMixin:
    def _init_player(self):
        self._media = media_server.MediaServer()
        self._player_video = None            # VideoSession

    # ------------------------------------------------------------------ durum
    def _player_state(self):
        video = self._player_video
        if video is None:
            return None
        info = video.info or {'duration': 0.0, 'chapters': []}
        marks = [{'start': item['start'], 'title': item.get('title', '')} for item in info.get('chapters') or []]
        if len(marks) < 2 and video.session is not None:
            data = video.session.data
            marks = [{'start': item['start'], 'title': item.get('title', '')} for item in data.get('chapters') or []]
            if len(marks) < 2:
                marks = [{'start': item['start'], 'title': qa.section_label(item)}
                         for item in data.get('sections') or [] if qa.section_label(item)]
        sources = []
        for item in video.streams or []:
            if item.get('supported'):
                label = ' · '.join(part for part in (item.get('language') or '', item.get('title') or '',
                                                     item.get('codec', '')) if part)
                sources.append({'key': f'stream:{item["index"]}', 'label': label or ('Akış ' + str(item['index']))})
        if len(video.audio) > 1:
            sources += [{'key': f'{WHISPER_KEY}:{item["index"]}', 'label': 'Sesten (Whisper) · ' + audio_label(item)}
                        for item in video.audio]
        elif video.streams is not None:
            sources.append({'key': WHISPER_KEY, 'label': 'Sesten (Whisper)'})
        entries = []
        for kind, value in video.entries:
            if kind == 'assistant':
                turn = value if isinstance(value, dict) else {'parts': value}  # F100 oncesi: yalniz parcalar
                entries.append({'kind': 'assistant', 'parts': video_parts(turn['parts'], video.path), 'sources': [],
                                'thinking': str(turn.get('thinking') or ''), 'think': turn.get('think'),
                                'template': str(turn.get('template') or '')})
            elif kind == 'pending':
                entries.append(pending_entry(value))
            else:
                entries.append({'kind': kind, 'text': str(value)})
        return {'path': str(video.path), 'name': video.path.name, 'duration': info.get('duration') or 0.0,
                'engine': self._engine() if hasattr(self, '_engine') else 'web',
                'marks': marks, 'audio': [{'index': item['index'], 'label': audio_label(item)} for item in video.audio],
                'subtitles': [{'key': item['key'], 'label': item['label'], 'kind': item['kind'],
                               'ready': item.get('ready', True)}
                              for item in subtitle_sources(video.path, video.streams)] if video.streams is not None else None,
                'whisper': self._whisper_label(video) if video.whisper else '',
                'whisper_words': speech.has_words(video.whisper) if video.whisper else False,
                'transcribing': video.transcribing,
                'qa': {'status': video.status, 'progress': video.progress, 'busy': video.preparing or video.asking
                       or video.transcribing, 'ready': video.ready, 'asking': video.asking,
                       'sources': sources, 'source': video.source_key, 'entries': entries, 'chips': video.chips}}

    def _push_player(self, video):
        if video is self._player_video:
            self._emit('player', self._player_state())

    def _whisper_label(self, video, result=None):
        result = result or video.whisper
        label = 'Whisper · ' + speech.language_label(result.get('language'))
        if len(video.audio) > 1:
            track = result.get('audio_track')
            stream = next((item for item in video.audio if item['index'] == track),
                          video.audio[0] if track is None else None)
            if stream is not None:
                label += ' (' + audio_label(stream) + ')'
        return label

    # ------------------------------------------------------------------ acma
    def player_open(self, path):
        """Videoyu acar; ayni video zaten aciksa durumu (sohbet, hazirlik) korunur."""
        path = Path(str(path))
        if not path.is_file():
            return {'error': 'Dosya bulunamadı: ' + str(path)}
        if self._player_video is not None and self._player_video.path == path:
            return self._player_state()
        if self._player_video is not None:
            self._player_video.cancel.set()
        video = self._player_video = VideoSession(path)
        try:
            video.info = media_server.probe(path)
        except (RuntimeError, ValueError, OSError) as error:
            return {'error': 'Video okunamadı: ' + str(error)}
        try:
            cfg = load_config()
            video.whisper = speech.load_cached(path, cfg['whisper_model'], cfg['whisper_language'])
        except (OSError, ValueError):
            video.whisper = None
        self._log('[Soru] Soru Sor hazırlanıyor: ' + path.name)
        self._start_prepare(video)
        return self._player_state()

    def player_source(self, audio_index=None, start=0.0, force_stream=False, transcode=False, codecs=None,
                      software=False):
        """Oynaticinin kaynagi: {'url', 'offset', 'mode'}. Akista `offset`ten itibaren baslar.

        `force_stream`: tarayici dosyayi dogrudan calamadiysa ffmpeg akisi; `transcode`: akistaki
        kopyalanmis goruntuyu de cozemediyse goruntu H.264'e yeniden kodlanir (Ayarlar'daki GPU
        kodlayicisiyla, F120). `software`: GPU kodlamasi basarisiz oldu, islemci (libx264) kullanilir.
        `codecs`: WebView'in bu bilgisayarda cozebildigi ek kodlar (['hevc', 'hevc10']); varsa HEVC
        donusturulmeden calinir."""
        video = self._player_video
        if video is None:
            return {'error': 'Açık video yok.'}
        info = video.info
        if not load_config().get('video_direct_hevc', True):
            codecs = []   # Ayarlar: HEVC her zaman donusturulur
        chosen = media_server.plan(video.path, info, audio_index, transcode=bool(transcode),
                                   extra=[str(item) for item in codecs or []])
        codec = (info['video'] or {}).get('codec', '')
        if force_stream or transcode:
            chosen['mode'] = 'stream'
        if chosen['mode'] == 'direct':
            return {'url': self._media.file_url(video.path), 'offset': 0.0, 'mode': 'direct', 'audio': chosen['audio'],
                    'codec': codec}
        start = max(0.0, min(float(start or 0.0), max(0.0, info['duration'] - 1)))
        if chosen['video'] == 'copy' and info['video'] is not None:
            # Goruntu kopyalaninca akis anahtar kareden baslar; arayuz farki kendisi sarar.
            start = media_server.keyframe_before(video.path, start, info['video']['index'])
        if chosen['video'] == 'x264':
            choice = 'off' if software else str(load_config().get('video_hw', 'auto'))
            chosen['encoder'] = media_server.hw_encoder(choice)
            note = (video.path, chosen['encoder'])
            if getattr(video, 'encoder_note', None) != note:   # her sarmada degil, degisince yazilir
                video.encoder_note = note
                source = (info['video'] or {}).get('codec', '?').upper()
                self._log(f'[Oynatıcı] {source} → H.264 dönüştürülüyor: {media_server.encoder_label(chosen["encoder"])}'
                          + (' (GPU kodlaması başarısız oldu)' if software else ''))
        return {'url': self._media.stream_url(video.path, start, chosen, info), 'offset': start,
                'mode': 'stream', 'audio': chosen['audio'], 'transcode': chosen['video'] == 'x264',
                'encoder': chosen.get('encoder') or '', 'encoder_label': media_server.encoder_label(chosen.get('encoder'))
                if chosen['video'] == 'x264' else '',
                'mime': media_server.stream_mime(info, chosen), 'duration': info['duration'], 'codec': codec}

    def player_note(self, text):
        """Oynaticinin tani notu (takilma, F121) Konsol'a yazilir."""
        self._log('[Oynatıcı] ' + ' '.join(str(text or '').split())[:300])
        return True

    def player_close(self):
        """Oynatici sayfasindan cikildi: sunucudaki akislar durur, hazirlik surer."""
        return True

    # ------------------------------------------------------------------ altyazi (CC)
    def subtitle_load(self, key):
        """Gosterilecek altyazinin satirlari: [{'start', 'end', 'text'}] (Whisper'da 'words' da:
        oynatici o an soylenen kelimeyi vurgular)."""
        video = self._player_video
        if video is None:
            return {'error': 'Açık video yok.'}
        try:
            if key == WHISPER_KEY:
                if not video.whisper:
                    return {'error': 'Whisper transkripti yok.'}
                return [{'start': float(item['start']), 'end': float(item['end']), 'text': str(item['text']),
                         'words': item.get('words') or []}
                        for item in sorted(speech.display_segments(video.whisper['segments']),
                                           key=lambda item: item['start'])]
            elif str(key).startswith('ocr:'):
                cached = subtitle_ocr.load_cached(video.path, int(str(key).split(':', 1)[1]))
                if not cached:
                    return {'error': 'Bu altyazı henüz OCR ile okunmadı.'}
                segments = cached['segments']
            elif str(key).startswith('stream:'):
                index = int(str(key).split(':', 1)[1])
                stream = next((item for item in video.streams or [] if item['index'] == index), None)
                if stream is None:
                    return {'error': 'Altyazı akışı bulunamadı.'}
                segments = qa.subtitle_segments(video.path, stream, keep_lines=True)
            elif str(key).startswith('file:'):
                segments = qa.file_segments(str(key)[5:])
            else:
                return {'error': 'Bilinmeyen altyazı kaynağı.'}
        except (RuntimeError, ValueError, OSError) as error:
            return {'error': 'Altyazı yüklenemedi: ' + str(error)}
        return [{'start': float(item['start']), 'end': float(item['end']), 'text': str(item['text'])}
                for item in sorted(segments, key=lambda item: item['start'])]

    def whisper_generate(self, audio_index=None):
        """CC menusunden: konusmadan metin cikar; bitince 'player' + 'whisper_ready' olayi."""
        video = self._player_video
        ok, message = speech.available()
        if video is None or not ok:
            return {'error': message or 'Açık video yok.'}
        if video.transcribing or video.preparing:
            return {'error': 'Önceki iş bitince tekrar deneyin.'}
        track = self._audio_track_arg(video, audio_index)
        video.transcribing = True
        video.status = 'Konuşmadan metin çıkarılıyor…'
        video.progress = None

        def work():
            try:
                cfg = load_config()
                result = speech.transcribe(video.path, cfg['whisper_model'], cfg['whisper_device'],
                                           cfg['whisper_language'], progress=lambda done, total: self._whisper_progress(video, done, total),
                                           cancelled=video.cancel.is_set, log=lambda message: self._log('[Soru] ' + str(message)),
                                           cuda_dir=cfg.get('whisper_cuda_dir', ''), audio_track=track)
            except (GracefulStop, RuntimeError, ValueError, OSError) as error:
                video.entries.append(('error', 'Konuşmadan metin çıkarılamadı: ' + str(error)))
            else:
                video.whisper = result
                self._emit('whisper_ready', {'path': str(video.path)})
            video.transcribing = False
            video.progress = None
            video.status = self._ready_status(video) if video.ready else video.status
            self._push_player(video)

        threading.Thread(target=work, name='aktar-whisper', daemon=True).start()
        self._push_player(video)
        return self._player_state()

    def _audio_track_arg(self, video, audio_index):
        """Whisper icin ses akisi: ilk akis None (eski onbellekler gecerli kalsin)."""
        if audio_index is None or not video.audio or audio_index == video.audio[0]['index']:
            return None
        return int(audio_index)

    def _whisper_progress(self, video, done, total):
        video.progress = {'done': int(done), 'total': max(1, int(total))}
        video.status = f'Konuşmadan metin: {qa.format_time(done)} / {qa.format_time(total)}'
        self._push_player(video)

    # ------------------------------------------------------------------ hazirlik
    def _ready_status(self, video):
        data = video.session.data
        mode = 'tüm transkript' if data.get('mode') == 'full' else f'{len(data["sections"])} bölüm'
        return f'Hazır · {qa.format_time(data.get("duration", 0))} · {mode}'

    def _start_prepare(self, video, stream=None, whisper=False, audio_track=None):
        """Akis tespiti -> transkript (altyazi veya Whisper) -> video haritasi/ozet (eski PrepareWorker)."""
        if video.preparing:
            return
        video.preparing = True
        video.ready = False
        video.chips = None
        video.progress = None
        video.status = ('Konuşmadan metin çıkarılıyor…' if whisper else 'Transkript hazırlanıyor…') \
            if video.session is None else 'Video hazırlanıyor…'
        log = lambda message: self._log('[Soru] ' + str(message))  # noqa: E731

        def work():
            overview, error = None, ''
            try:
                if video.session is None:
                    if not video.audio:
                        try:
                            video.audio = audio_streams(video.path)
                        except (RuntimeError, ValueError):
                            video.audio = []
                    if video.streams is None:
                        video.streams = subtitle_streams(video.path)
                    chosen = None if whisper else (stream or qa.pick_subtitle_stream(video.streams))
                    cfg = load_config()
                    use_whisper = whisper
                    if chosen is None and not whisper:
                        # Altyazi yok: daha once cikarilmis Whisper transkripti varsa onu kullan.
                        use_whisper = speech.load_cached(video.path, cfg['whisper_model'], cfg['whisper_language'],
                                                         audio_track=audio_track) is not None
                    video.prepare_track = audio_track
                    if chosen is not None:
                        video.source_key = f'stream:{chosen["index"]}'
                    elif len(video.audio) > 1:
                        track = audio_track if audio_track is not None else (video.audio[0]['index'] if video.audio else None)
                        video.source_key = f'{WHISPER_KEY}:{track}'
                    else:
                        video.source_key = WHISPER_KEY
                    self._push_player(video)
                    if chosen is None and not use_whisper:
                        raise ValueError(NO_SUBTITLE)
                    if use_whisper:
                        result = speech.transcribe(
                            video.path, cfg['whisper_model'], cfg['whisper_device'], cfg['whisper_language'],
                            progress=lambda done, total: self._whisper_progress(video, done, total),
                            cancelled=video.cancel.is_set, log=log, cuda_dir=cfg.get('whisper_cuda_dir', ''),
                            audio_track=audio_track)
                        video.whisper = result
                        data, path = qa.load_whisper_session(video.path, result, log=log)
                    else:
                        data, path = qa.load_subtitle_session(video.path, chosen, log=log)
                    video.session = qa.VideoQA(data, config_provider=load_config, log=log,
                                               save=lambda value, path=path: save_json(path, value))
                    video.session.history = list(video.history)
                    video.status = f'Transkript hazır ({len(data["segments"])} satır). Video özetleniyor…'
                    video.progress = None
                    self._push_player(video)

                def progress(done, total):
                    video.progress = {'done': int(done), 'total': max(1, int(total))}
                    if total > 1:
                        video.status = f'Video haritası çıkarılıyor: {done} / {total}'
                    self._push_player(video)

                overview = video.session.prepare(progress=progress, cancelled=video.cancel.is_set)
            except GracefulStop as stop:
                error = str(stop)
            except (RuntimeError, ValueError, OSError) as failure:
                error = str(failure)
            except Exception as failure:  # beklenmeyen hata oynaticiyi kilitlemesin
                error = 'Beklenmeyen hata: ' + repr(failure)
            video.preparing = False
            video.progress = None
            if error:
                log(error)
                video.status = 'Altyazı yok · video oynatılabilir' if error == NO_SUBTITLE else 'Hazırlık tamamlanamadı.'
                video.entries.append(('error', error))
                if error == NO_SUBTITLE:
                    video.chips = {'title': 'Altyazı olmadan da soru sorabilirsiniz:',
                                   'items': [{'label': 'Sesten transkript çıkar (Whisper)', 'action': 'whisper'}]}
                elif video.session is not None:
                    video.chips = {'title': 'LM Studio açık ve model yüklü olduğunda tekrar deneyin:',
                                   'items': [{'label': 'Tekrar dene', 'action': 'retry'}]}
            elif overview is not None or video.session is not None:
                video.status = self._ready_status(video)
                video.ready = True
                if not video.session.history:
                    video.chips = {'title': 'Ne soracağınızı bilmiyor musunuz? Birini seçin:',
                                   'items': [{'label': text, 'action': 'ask'} for text in video.session.questions()]}
            self._push_player(video)

        threading.Thread(target=work, name='aktar-video-prepare', daemon=True).start()

    def player_prepare(self, action='retry'):
        """Oneri dugmeleri: 'retry' hazirligi yeniden dener, 'whisper' sesten transkript cikarir."""
        video = self._player_video
        if video is None:
            return None
        if action == 'whisper':
            ok, message = speech.available()
            if not ok:
                video.entries.append(('error', message))
                return self._player_state()
        self._start_prepare(video, whisper=action == 'whisper')
        return self._player_state()

    def player_set_source(self, key):
        """Soru-cevapta kullanilacak transkript kaynagi degisti: sohbet sifirlanir, yeniden hazirlanir."""
        video = self._player_video
        if video is None or video.preparing or video.transcribing or video.asking or key == video.source_key:
            return self._player_state()
        stream, track, whisper = None, None, False
        if str(key).startswith(WHISPER_KEY):
            whisper = True
            if key != WHISPER_KEY:
                track = self._audio_track_arg(video, int(str(key).split(':', 1)[1]))
            ok, message = speech.available()
            if not ok:
                video.entries.append(('error', message))
                return self._player_state()
        else:
            index = int(str(key).split(':', 1)[1])
            stream = next((item for item in video.streams or [] if item['index'] == index), None)
            if stream is None:
                return self._player_state()
        video.session = None
        video.entries = [('note', GREETING)]
        video.history = []
        library.clear_chat(video.key)  # sohbet eski transkriptin zamanlarina atif yapiyordu
        self._start_prepare(video, stream=stream, whisper=whisper, audio_track=track)
        return self._player_state()

    # ------------------------------------------------------------------ soru-cevap
    def player_ask(self, question, think=None, template=None):
        video = self._player_video
        text = ' '.join(str(question or '').split())
        if video is None or not text or video.session is None or not video.ready or video.asking:
            return self._player_state()
        video.asking = True
        video.chips = None
        video.entries += [('user', text), ('pending', 'Yanıt hazırlanıyor…')]
        instructions, name = chat_templates.instruction(template)

        def work():
            try:
                turn = video.session.ask(text, think=think, on_reasoning=reasoning_feed(
                    lambda: video.entries, lambda: self._push_player(video)),
                    instructions=instructions, template=name)
            except (GracefulStop, RuntimeError, ValueError, OSError) as error:
                self._log('[Soru] ' + str(error))
                video.entries = [item for item in video.entries if item[0] != 'pending']
                video.entries.append(('error', 'Yanıt alınamadı: ' + str(error)))
            else:
                video.entries = [item for item in video.entries if item[0] != 'pending']
                video.entries.append(('assistant', {'parts': turn['parts'], 'thinking': turn.get('thinking', ''),
                                                    'think': turn.get('think'), 'template': name}))
            video.history = video.session.history
            library.save_chat(video.key, video.entries, video.history)
            video.asking = False
            self._push_player(video)

        threading.Thread(target=work, name='aktar-video-ask', daemon=True).start()
        return self._player_state()

    def player_clear_chat(self):
        """Acik videonun sohbetini ve kayitli gecmisini siler."""
        video = self._player_video
        if video is None or video.asking:
            return self._player_state()
        library.clear_chat(video.key)
        video.entries = [('note', GREETING)]
        video.history = []
        if video.session is not None:
            video.session.history = []
            if video.ready:
                video.chips = {'title': 'Ne soracağınızı bilmiyor musunuz? Birini seçin:',
                               'items': [{'label': text, 'action': 'ask'} for text in video.session.questions()]}
        return self._player_state()

    def _stop_player_for_close(self):
        if self._player_video is not None:
            self._player_video.cancel.set()
        self._media.shutdown()
