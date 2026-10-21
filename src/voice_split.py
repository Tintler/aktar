"""Ses ayirma ve konusmaci ayrimi (F146): sherpa-onnx ile yerelde.

  - Vokal ayirma: videonun sesi konusma (vokal) ve geri kalan (muzik, efekt) olarak ikiye ayrilir
    (UVR-MDX-NET-Voc_FT). Dublaj (dub.py) muzigi ve efektleri tam duzeyde korur, yalnizca ozgun
    konusmayi kisar.
  - Konusmaci ayrimi: kim ne zaman konusuyor (pyannote segmentasyon + WeSpeaker embedding +
    kumeleme). Dublajda konusmaci basina ayri ses, transkriptte ve soru-cevapta 'K1: ...' etiketleri.

Calisma yeri speech.py gibidir: kaynak koddan calisirken sherpa-onnx kuruluysa uygulama icinde, derlenmis
Aktar'da aktar-whisper paketinde (whisper_cli.py --task separate|diarize). Modeller ilk kullanimda
k2-fsa/sherpa-onnx GitHub surumlerinden models/sherpa altina bir kez indirilir; sonra ag kullanilmaz.
Sonuclar work_files altinda onbellekte durur (video degisirse yenilenir). Kaynak video SALT-OKUNUR.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tarfile
import urllib.request
import wave
from pathlib import Path

import media
import qa
import speech
from app_core import APP_DIR, GracefulStop, atomic, digest, read, save_json

RELEASES = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/'
MODELS = {
    'separation': {'file': 'UVR-MDX-NET-Voc_FT.onnx', 'url': RELEASES + 'source-separation-models/UVR-MDX-NET-Voc_FT.onnx',
                   'size': 66762795, 'vocals': 0},
    'segmentation': {'file': 'sherpa-onnx-pyannote-segmentation-3-0/model.onnx', 'archive': True,
                     'url': RELEASES + 'speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2'},
    'embedding': {'file': 'wespeaker_en_voxceleb_resnet34_LM.onnx',
                  'url': RELEASES + 'speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx'},
    # F172: ses olaylari (AudioSet: gulme, aglama, ic cekme...) ve konusma/sessizlik (duraklamalar)
    'tagging': {'file': 'sherpa-onnx-ced-mini-audio-tagging-2024-04-19/model.int8.onnx', 'archive': True,
                'extra': ['sherpa-onnx-ced-mini-audio-tagging-2024-04-19/class_labels_indices.csv'],
                'url': RELEASES + 'audio-tagging-models/sherpa-onnx-ced-mini-audio-tagging-2024-04-19.tar.bz2'},
    'vad': {'file': 'silero_vad.onnx', 'url': RELEASES + 'asr-models/silero_vad.onnx'},
}
TAGGING_LABELS = 'sherpa-onnx-ced-mini-audio-tagging-2024-04-19/class_labels_indices.csv'
# F172: dublaja aktarilan ses olaylari -> AudioSet sinif adlari (class_labels_indices.csv)
SOUNDS = {
    'laugh': ('Laughter', 'Giggle', 'Snicker', 'Belly laugh', 'Chuckle, chortle'),
    'cry': ('Crying, sobbing', 'Wail, moan'),
    'sigh': ('Sigh',),
    'whisper': ('Whispering',),
    'shout': ('Shout', 'Yell', 'Screaming', 'Battle cry'),
    'breath': ('Gasp', 'Breathing'),
    'cough': ('Cough', 'Throat clearing'),
}
EXPRESSION_WINDOW = 2.0   # ses olayi penceresi (sn)
EXPRESSION_HOP = 0.5
SEPARATION_RATE = 44100
DIARIZATION_RATE = 16000
CHUNK_SECONDS = 30     # ayirma bu uzunlukta parcalarla yapilir (bellek + ilerleme + durdurma)
OVERLAP_SECONDS = 1    # parcalar arasinda yumusak gecis
THRESHOLD = 0.5        # kumeleme esigi (kucuk: daha cok konusmaci)
INSTALL_HINT = ('Ses ayırma ve konuşmacı ayrımı için sherpa-onnx gerekir: ' +
                ('py -3 -m pip install -r requirements-whisper.txt' if os.name == 'nt'
                 else '.venv/bin/pip install -r requirements-whisper.txt') +
                ' (derlenmiş Aktar\'da yeni aktar-whisper paketi).')


# --- calisma yeri -------------------------------------------------------------
def backend():
    """'inprocess' | 'helper' | None."""
    if not getattr(sys, 'frozen', False):
        try:
            import sherpa_onnx  # noqa: F401
            return 'inprocess'
        except ImportError:
            pass
    return 'helper' if speech.helper_command() else None


def available():
    if backend():
        return True, ''
    return False, INSTALL_HINT


def model_dir():
    return APP_DIR / 'models' / 'sherpa'


def model_path(name, folder=None):
    return Path(folder or model_dir()) / MODELS[name]['file']


def ensure_models(names, log=print, progress=None, cancelled=None, folder=None):
    """Eksik modelleri indirir (ilk kullanim). progress(indirilen_bayt, toplam_bayt)."""
    folder = Path(folder or model_dir())
    for name in names:
        spec = MODELS[name]
        target = folder / spec['file']
        if target.exists():
            continue
        folder.mkdir(parents=True, exist_ok=True)
        download = folder / (Path(spec['url']).name + '.part')
        log(f'Model indiriliyor (bir kez): {Path(spec["url"]).name}')
        request = urllib.request.Request(spec['url'], headers={'User-Agent': 'Aktar'})
        try:
            with urllib.request.urlopen(request, timeout=60) as response, open(download, 'wb') as out:
                total = int(response.headers.get('Content-Length') or spec.get('size') or 0)
                done = 0
                while True:
                    if cancelled and cancelled():
                        raise GracefulStop('İndirme durduruldu.')
                    block = response.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    if progress:
                        progress(done, total)
        except GracefulStop:
            download.unlink(missing_ok=True)
            raise
        except OSError as error:
            download.unlink(missing_ok=True)
            raise RuntimeError(f'Model indirilemedi ({Path(spec["url"]).name}): {error}') from None
        if spec.get('archive'):
            with tarfile.open(download, 'r:bz2') as archive:
                for name in spec.get('extra', []) + [spec['file']]:   # model en son: varligi butunlugun isareti
                    member = archive.getmember(name)
                    member.name = name
                    archive.extract(member, folder, filter='data')
            download.unlink(missing_ok=True)
        else:
            os.replace(download, target)


# --- onbellek -------------------------------------------------------------------
def _cache_file(video, kind, extension, audio_track=None, base=None):
    video = Path(video).resolve()
    stat = video.stat()
    key = digest(f'{kind}|{video}|{stat.st_size}|{int(stat.st_mtime)}|{speech.track_suffix(audio_track)}')[:16]
    stem = re.sub(r'[^\w.-]+', '_', video.stem)[:40] or 'video'
    return Path(base or qa.work_dir()) / kind / f'{stem}.{key}{extension}'


def speakers_path(video, base=None):
    """Konusmaci ayriminin onbellegi (ses izinden bagimsiz: ayni videoda konusmacilar ayni)."""
    return _cache_file(video, 'speakers', '.json', None, base)


def stems_paths(video, audio_track=None, base=None):
    """(konusma, muzik/efekt) onbellek dosyalari."""
    root = _cache_file(video, 'stems', '', audio_track, base)
    return root.with_name(root.name + '.vocals.m4a'), root.with_name(root.name + '.background.m4a')


def load_speakers(video, base=None):
    """{'turns': [{start, end, speaker}], 'count', 'names': {'0': 'Ali'}} ya da None."""
    try:
        value = json.loads(read(speakers_path(video, base)))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get('turns'), list):
        return None
    value.setdefault('names', {})
    return value


def save_names(video, names, base=None):
    """Konusmaci adlarini kaydeder ({'0': 'Ali'}; bos ad varsayilana doner)."""
    data = load_speakers(video, base)
    if data is None:
        raise ValueError('Bu videoda konuşmacılar henüz ayrılmadı.')
    clean = {}
    for key, value in (names or {}).items():
        text = ' '.join(str(value or '').split())[:40]
        if text and str(key).isdigit() and int(key) < int(data.get('count') or 0):
            clean[str(int(key))] = text
    data['names'] = clean
    save_json(speakers_path(video, base), data)
    return data


def speaker_name(data, speaker):
    if speaker is None:
        return ''
    return (data or {}).get('names', {}).get(str(speaker)) or f'K{int(speaker) + 1}'


def speaker_of(start, end, turns, tolerance=1.0):
    """Araliga en cok ortusen konusmaci; ortusme yoksa `tolerance` icindeki en yakin; yoksa None."""
    best, overlap = None, 0.0
    for turn in turns:
        common = min(end, turn['end']) - max(start, turn['start'])
        if common > overlap:
            best, overlap = turn['speaker'], common
    if best is not None:
        return best
    middle, nearest, gap = (start + end) / 2, None, tolerance
    for turn in turns:
        distance = max(turn['start'] - middle, middle - turn['end'], 0.0)
        if distance <= gap:
            nearest, gap = turn['speaker'], distance
    return nearest


def label(segments, data):
    """Segmentlerin kopyasi; her birine 'speaker' (ad) eklenir. Konusmaci verisi yoksa ayni liste."""
    turns = (data or {}).get('turns') or []
    if not turns:
        return segments
    result = []
    for item in segments:
        copy = dict(item)
        if not item.get('visual'):
            speaker = speaker_of(float(item['start']), float(item['end']), turns)
            if speaker is not None:
                copy['speaker'] = speaker_name(data, speaker)
        result.append(copy)
    return result


def sample_turn(data, speaker, max_seconds=5.0):
    """F148: konusmacinin ornek parcasi -- en uzun konusmasi (ust uste binen konusma az olsun diye), en fazla
    `max_seconds`. None: konusmaci yok."""
    turns = [turn for turn in (data or {}).get('turns') or [] if turn['speaker'] == speaker]
    if not turns:
        return None
    best = max(turns, key=lambda turn: turn['end'] - turn['start'])
    return {'start': best['start'], 'end': min(best['end'], best['start'] + max_seconds)}


def clip_base64(video, start, end, audio_track=None):
    """Videonun sesinden [start, end] araligi: 22 kHz mono WAV, base64 (arayuzde calinir)."""
    import base64
    import tempfile
    track = '0:a:0' if audio_track is None else f'0:{int(audio_track)}'
    with tempfile.TemporaryDirectory(prefix='aktar-ornek-') as folder:
        target = Path(folder) / 'ornek.wav'
        result = media._run([media.ffmpeg_path(), '-v', 'error', '-y', '-ss', f'{max(0.0, float(start)):.2f}',
                             '-t', f'{max(0.3, float(end) - float(start)):.2f}', '-i', str(video), '-map', track,
                             '-vn', '-ac', '1', '-ar', '22050', '-c:a', 'pcm_s16le', str(target)])
        if result.returncode != 0 or not target.exists():
            raise RuntimeError('Örnek ses çıkarılamadı: ' + (result.stderr or '').strip()[-300:])
        return base64.b64encode(target.read_bytes()).decode('ascii')


def signature(data):
    """Konusmaci verisinin kisa imzasi (arama indeksi anahtari icin; adlar degisince de degisir)."""
    if not data or not data.get('turns'):
        return ''
    return digest(json.dumps([len(data['turns']), data.get('count'), sorted((data.get('names') or {}).items())]))[:8]


def renumber(turns):
    """Konusmacilari ilk konustuklari sirayla 0, 1, 2... numaralar; turlar zamana gore sirali."""
    turns = sorted(turns, key=lambda turn: (turn['start'], turn['end']))
    order = {}
    for turn in turns:
        order.setdefault(turn['speaker'], len(order))
    return [dict(turn, speaker=order[turn['speaker']]) for turn in turns], len(order)


def summary(data, lines=None):
    """Arayuz icin konusmacilar: [{id, name, turns, seconds, lines, sample}] (konusma suresine gore)."""
    if not data:
        return []
    stats = {}
    for turn in data['turns']:
        item = stats.setdefault(turn['speaker'], {'id': turn['speaker'], 'turns': 0, 'seconds': 0.0, 'lines': 0, 'sample': ''})
        item['turns'] += 1
        item['seconds'] += turn['end'] - turn['start']
    for line in lines or []:
        speaker = speaker_of(line['start'], line['end'], data['turns'])
        if speaker in stats:
            stats[speaker]['lines'] += 1
            if not stats[speaker]['sample']:
                stats[speaker]['sample'] = str(line.get('text', ''))[:90]
    for item in stats.values():
        item['name'] = speaker_name(data, item['id'])
        item['seconds'] = round(item['seconds'], 1)
    return sorted(stats.values(), key=lambda item: -item['seconds'])


# --- isler (uygulama icinde ya da aktar-whisper paketinde) -------------------------
def _read_frames(stream, count):
    import numpy as np
    channels = stream.getnchannels()
    data = np.frombuffer(stream.readframes(count), dtype='<i2').astype(np.float32) / 32768.0
    return np.ascontiguousarray(data.reshape(-1, channels).T)


def _write_frames(stream, audio):
    import numpy as np
    stream.writeframes((np.clip(audio.T, -1.0, 1.0) * 32767.0).round().astype('<i2').tobytes())


def run_separate(audio, vocals_out, background_out, model, progress=None, cancelled=None, threads=0):
    """44,1 kHz stereo WAV'i parcalar halinde ayirir; iki stereo WAV yazar. progress(sn, toplam_sn)."""
    import numpy as np
    import sherpa_onnx

    threads = threads or max(1, min(8, (os.cpu_count() or 2) - 1))
    config = sherpa_onnx.OfflineSourceSeparationConfig(model=sherpa_onnx.OfflineSourceSeparationModelConfig(
        uvr=sherpa_onnx.OfflineSourceSeparationUvrModelConfig(model=str(model)), num_threads=threads))
    if not config.validate():
        raise RuntimeError('Ses ayırma modeli geçersiz: ' + str(model))
    separator = sherpa_onnx.OfflineSourceSeparation(config)
    vocals_index = MODELS['separation']['vocals']
    with wave.open(str(audio), 'rb') as source:
        rate, total = source.getframerate(), source.getnframes()
        if total <= 0:
            raise ValueError('Ayrılacak ses boş.')
        hop, overlap = CHUNK_SECONDS * rate, OVERLAP_SECONDS * rate
        outputs = [wave.open(str(path), 'wb') for path in (vocals_out, background_out)]
        for out in outputs:   # baslik en basta: hata olsa da dosyalar duzgun kapanir
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(rate)
        try:
            tails, out_rate = None, None
            for start in range(0, total, hop):
                if cancelled and cancelled():
                    raise GracefulStop('Ses ayırma durduruldu.')
                count = min(hop + overlap, total - start)
                source.setpos(start)
                chunk = _read_frames(source, count)
                result = separator.process(rate, chunk)
                if out_rate is None:
                    out_rate = result.sample_rate
                    if out_rate != rate:   # henuz ses yazilmadi; hiz degistirilebilir
                        for out in outputs:
                            out.setframerate(out_rate)
                length = count * out_rate // rate   # model parcayi kendi pencere boyuna doldurabilir; fazlasi atilir
                stems = [np.array(item.data, dtype=np.float32)[:, :length] for item in result.stems]
                vocals = stems[vocals_index]
                rest = stems[1 - vocals_index] if len(stems) > 1 else chunk[:, :vocals.shape[1]] - vocals
                parts = []
                for index, stem in enumerate((vocals, rest)):
                    if stem.shape[0] == 1:
                        stem = np.repeat(stem, 2, axis=0)
                    if tails is not None:
                        length = min(tails[index].shape[1], stem.shape[1])
                        fade = np.linspace(0.0, 1.0, length, dtype=np.float32)
                        stem[:, :length] = tails[index][:, :length] * (1 - fade) + stem[:, :length] * fade
                    parts.append(stem)
                last = start + count >= total
                cut = parts[0].shape[1] if last else min(hop * out_rate // rate, parts[0].shape[1])
                for out, stem in zip(outputs, parts):
                    _write_frames(out, stem[:, :cut])
                tails = None if last else [stem[:, cut:] for stem in parts]
                if progress:
                    progress(int((total if last else start + hop) / rate), int(total / rate))
                if last:
                    break
        finally:
            for out in outputs:
                out.close()


def run_diarize(audio, segmentation, embedding, speakers=0, threshold=THRESHOLD, progress=None, cancelled=None,
                threads=0):
    """16 kHz mono WAV -> [{start, end, speaker}] (konusmacilar ilk konusma sirasiyla 0, 1, ...)."""
    import sherpa_onnx

    threads = threads or max(1, min(8, (os.cpu_count() or 2) - 1))
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),
            num_threads=threads),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=threads),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=int(speakers) if speakers else -1,
                                                    threshold=float(threshold)),
        min_duration_on=0.3, min_duration_off=0.5)
    if not config.validate():
        raise RuntimeError('Konuşmacı ayrımı modelleri geçersiz.')
    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    samples = speech.read_wav(audio)

    def callback(done, total):
        if progress:
            progress(int(done), int(total))
        return 1 if cancelled and cancelled() else 0

    result = diarizer.process(samples, callback=callback)
    if cancelled and cancelled():
        raise GracefulStop('Konuşmacı ayrımı durduruldu.')
    turns = [{'start': round(float(item.start), 2), 'end': round(float(item.end), 2), 'speaker': int(item.speaker)}
             for item in result.sort_by_start_time()]
    return renumber(turns)[0]


def run_expression(audio, tagging, labels, vad, progress=None, cancelled=None, threads=0):
    """F172: 16 kHz mono WAV -> ses olaylari ve konusma araliklari:
    {'hop', 'window', 'sounds': {grup: [olasilik, ...]} (her `hop` sn'de bir, pencere basi i*hop),
     'speech': [[bas, son], ...]}."""
    import numpy as np
    import sherpa_onnx

    threads = threads or max(1, min(8, (os.cpu_count() or 2) - 1))
    tagger = sherpa_onnx.AudioTagging(sherpa_onnx.AudioTaggingConfig(
        model=sherpa_onnx.AudioTaggingModelConfig(ced=str(tagging), num_threads=threads), labels=str(labels), top_k=60))
    samples = np.ascontiguousarray(speech.read_wav(audio))
    rate = DIARIZATION_RATE
    window, hop = int(EXPRESSION_WINDOW * rate), int(EXPRESSION_HOP * rate)
    group_of = {name: group for group, names in SOUNDS.items() for name in names}
    starts = list(range(0, max(1, len(samples) - hop), hop))
    sounds = {group: [0.0] * len(starts) for group in SOUNDS}
    # konusma araliklari (sessizlikler duraklamadir)
    config = sherpa_onnx.VadModelConfig(silero_vad=sherpa_onnx.SileroVadModelConfig(
        model=str(vad), threshold=0.5, min_silence_duration=0.25, min_speech_duration=0.2, max_speech_duration=30),
        sample_rate=rate, num_threads=1)
    detector = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=60)
    found = []

    def drain():
        while not detector.empty():
            segment = detector.front
            found.append([round(segment.start / rate, 2), round((segment.start + len(segment.samples)) / rate, 2)])
            detector.pop()

    step = 512
    for begin in range(0, len(samples), step * 200):
        if cancelled and cancelled():
            raise GracefulStop('İfade çözümlemesi durduruldu.')
        chunk = samples[begin:begin + step * 200]
        for offset in range(0, len(chunk), step):
            detector.accept_waveform(chunk[offset:offset + step])
        drain()
    detector.flush()
    drain()
    total = len(starts)
    for number, begin in enumerate(starts):
        if cancelled and number % 50 == 0 and cancelled():
            raise GracefulStop('İfade çözümlemesi durduruldu.')
        piece = samples[begin:begin + window]
        if len(piece) < rate // 4:
            continue
        stream = tagger.create_stream()
        stream.accept_waveform(rate, piece)
        for event in tagger.compute(stream):
            group = group_of.get(event.name)
            if group and event.prob > sounds[group][number]:
                sounds[group][number] = round(float(event.prob), 2)
        if progress and (number % 50 == 0 or number + 1 == total):
            progress(number + 1, total)
    return {'hop': EXPRESSION_HOP, 'window': EXPRESSION_WINDOW, 'sounds': sounds, 'speech': found}


# --- uygulama tarafi -----------------------------------------------------------------
def _run(task, arguments, local, progress=None, cancelled=None, log=print):
    """Isi uygulama icinde (`local()`) ya da aktar-whisper paketinde calistirir."""
    mode = backend()
    if mode is None:
        raise RuntimeError(INSTALL_HINT)
    if mode == 'inprocess':
        return local()
    return speech.run_helper_task(['--task', task] + arguments, progress=progress, cancelled=cancelled, log=log)


def _extract(video, output, audio_track, rate, channels):
    track = '0:a:0' if audio_track is None else f'0:{int(audio_track)}'
    result = media._run([media.ffmpeg_path(), '-v', 'error', '-y', '-i', str(video), '-map', track, '-vn',
                         '-ac', str(channels), '-ar', str(rate), '-c:a', 'pcm_s16le', str(output)])
    if result.returncode != 0 or not Path(output).exists():
        detail = (result.stderr or '').strip()
        if 'matches no streams' in detail:
            raise ValueError('Videoda ses akışı yok.')
        raise RuntimeError('Ses çıkarılamadı: ' + detail[-300:])


def _encode(source, target):
    partial = Path(target).with_name(Path(target).stem + '.part.m4a')
    result = media._run([media.ffmpeg_path(), '-v', 'error', '-y', '-i', str(source), '-c:a', 'aac', '-b:a', '256k',
                         str(partial)])
    if result.returncode != 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError('Ayrılan ses kaydedilemedi: ' + (result.stderr or '').strip()[-300:])
    os.replace(partial, target)


def separate(video, audio_track=None, base=None, log=print, progress=None, cancelled=None):
    """Videonun sesini konusma ve muzik/efekt olarak ayirir (onbellekli). Donen: (konusma, muzik) m4a yollari.
    progress(islenen, toplam, asama): asama 'download' (bayt) ya da 'separate' (saniye)."""
    vocals, background = stems_paths(video, audio_track, base)
    if vocals.exists() and background.exists():
        log('Ayrılmış ses önbellekten yüklendi.')
        return vocals, background
    ensure_models(['separation'], log, lambda done, total: progress and progress(done, total, 'download'), cancelled)
    folder = vocals.parent
    folder.mkdir(parents=True, exist_ok=True)
    stem = vocals.name[:-len('.vocals.m4a')]
    work = [folder / f'{stem}.{name}.wav' for name in ('input', 'vocals', 'background')]
    try:
        log('Ses ayrılıyor (konuşma / müzik ve efektler); işlemcide videonun yarısı kadar sürebilir…')
        _extract(video, work[0], audio_track, SEPARATION_RATE, 2)
        model = model_path('separation')
        _run('separate', [str(work[0]), '--vocals', str(work[1]), '--background', str(work[2]), '--model', str(model)],
             lambda: run_separate(work[0], work[1], work[2], model,
                                  lambda done, total: progress and progress(done, total, 'separate'), cancelled),
             lambda done, total: progress and progress(done, total, 'separate'), cancelled, log)
        _encode(work[1], vocals)
        _encode(work[2], background)
    finally:
        for path in work:
            path.unlink(missing_ok=True)
    log('Ses ayrıldı.')
    return vocals, background


def diarize(video, audio_track=None, speakers=0, base=None, log=print, progress=None, cancelled=None, fresh=False):
    """Konusmacilari ayirir (onbellekli; `fresh` ile yeniden). Konusmaci sayisi degismezse verilen adlar korunur.
    Donen: load_speakers bicimi. progress(islenen, toplam, asama): 'download' ya da 'diarize'."""
    cached = load_speakers(video, base)
    if cached is not None and not fresh and (not speakers or int(speakers) == cached.get('count')):
        log('Konuşmacılar önbellekten yüklendi.')
        return cached
    ensure_models(['segmentation', 'embedding'], log, lambda done, total: progress and progress(done, total, 'download'),
                  cancelled)
    target = speakers_path(video, base)
    target.parent.mkdir(parents=True, exist_ok=True)
    audio = target.with_suffix('.wav')
    try:
        log('Konuşmacılar ayrılıyor…')
        _extract(video, audio, audio_track, DIARIZATION_RATE, 1)
        segmentation, embedding = model_path('segmentation'), model_path('embedding')
        report = lambda done, total: progress and progress(done, total, 'diarize')  # noqa: E731
        turns = _run('diarize', [str(audio), '--segmentation', str(segmentation), '--embedding', str(embedding),
                                 '--speakers', str(int(speakers or 0))],
                     lambda: run_diarize(audio, segmentation, embedding, speakers, progress=report, cancelled=cancelled),
                     report, cancelled, log)
    finally:
        audio.unlink(missing_ok=True)
    if not turns:
        raise ValueError('Seste konuşma bulunamadı.')
    turns, count = renumber(turns)
    names = (cached or {}).get('names', {}) if cached and cached.get('count') == count else {}
    data = {'version': 1, 'video': str(video), 'turns': turns, 'count': count, 'names': names}
    save_json(target, data)
    log(f'Konuşmacılar ayrıldı: {count} konuşmacı, {len(turns)} konuşma parçası.')
    return data


def expression_path(video, audio_track=None, vocals=False, base=None):
    """F172: ses olaylari / konusma araliklari onbellegi (ayrilmis konusmadan cikarildiysa ayri)."""
    return _cache_file(video, 'expression', '.vocals.json' if vocals else '.json', audio_track, base)


def expression(video, audio_track=None, vocals=None, base=None, log=print, progress=None, cancelled=None):
    """F172: videonun konusmasindaki gulme, aglama, ic cekme... ve duraklamalar (onbellekli). `vocals`: ayrilmis
    konusma dosyasi (verilirse muzik karismaz, daha guvenilir). Donen: run_expression bicimi.
    progress(islenen, toplam, asama): 'download' ya da 'expression'."""
    target = expression_path(video, audio_track, bool(vocals), base)
    try:
        cached = json.loads(read(target))
        if isinstance(cached, dict) and isinstance(cached.get('sounds'), dict):
            log('Ses ifadeleri önbellekten yüklendi.')
            return cached
    except (OSError, ValueError):
        pass
    ensure_models(['tagging', 'vad'], log, lambda done, total: progress and progress(done, total, 'download'), cancelled)
    target.parent.mkdir(parents=True, exist_ok=True)
    audio = target.with_suffix('.wav')
    try:
        log('Konuşmadaki gülme, ağlama, duraklama gibi ifadeler çıkarılıyor…')
        _extract(vocals or video, audio, None if vocals else audio_track, DIARIZATION_RATE, 1)
        tagging, vad = model_path('tagging'), model_path('vad')
        labels = model_dir() / TAGGING_LABELS
        report = lambda done, total: progress and progress(done, total, 'expression')  # noqa: E731
        data = _run('expression', [str(audio), '--tagging', str(tagging), '--labels', str(labels), '--vad', str(vad)],
                    lambda: run_expression(audio, tagging, labels, vad, progress=report, cancelled=cancelled),
                    report, cancelled, log)
    finally:
        audio.unlink(missing_ok=True)
    data = dict(data, version=1, video=str(video))
    atomic(target, json.dumps(data, ensure_ascii=False, separators=(',', ':')))   # binlerce olasilik: sikistirilmis
    return data
