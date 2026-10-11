"""Konusmadan metin (F48): altyazisiz videolar icin faster-whisper ile transkript.

Istege bagli bagimlilik (requirements-whisper.txt). Kurulu degilse `available()`
anlamli Turkce mesaj dondurur; uygulamanin geri kalani etkilenmez. Kaynak video
SALT-OKUNUR: ffmpeg yalnizca ilk ses akisini work_files/qa altina 16 kHz mono WAV
olarak cikarir; WAV transkript bitince silinir. Model APP_DIR/models/whisper
altina iner (tasinabilir; ilk kullanimda indirilir).

Sonuc kelime zamanlarindan okunabilir altyazi cue'larina toplanir; ayni segment
listesi hem soru-cevap transkripti hem oynaticida altyazi olarak kullanilir.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import media
import qa
from app_core import APP_DIR, GracefulStop, read, save_json

DEFAULT_MODEL = 'large-v3-turbo'
MODELS = ('large-v3-turbo', 'large-v3', 'medium', 'small', 'base')
DEVICES = ('auto', 'cuda', 'cpu')
CUE_CHARS = 84       # bir altyazi cue'sunda en fazla karakter (2 x 42)
CUE_SECONDS = 6.0    # bir cue'nun en uzun suresi
LINE_CHARS = 42      # gosterimde satir genisligi
INSTALL_HINT = ('Konuşmadan metin için faster-whisper kurulu değil. Kurmak için uygulama '
                'klasöründe: py -3 -m pip install -r requirements-whisper.txt')
_SENTENCE_END = re.compile(r'[.?!…]["\')\]]*$')


FROZEN_HINT = ('Konuşmadan metin (Whisper) derlenmiş .exe sürümünde bulunmuyor. Bu özellik için '
               'uygulamayı kaynak koddan çalıştırın (KULLANIM.md 1.5).')


def available():
    """(kurulu mu, kurulu degilse kullaniciya gosterilecek mesaj)."""
    if getattr(sys, 'frozen', False):
        return False, FROZEN_HINT  # DERLE.cmd faster-whisper'i bilerek disarida birakir
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False, INSTALL_HINT
    return True, ''


def model_dir():
    return APP_DIR / 'models' / 'whisper'


# --- saf yardimcilar -------------------------------------------------------
def regroup_words(words, max_chars=CUE_CHARS, max_seconds=CUE_SECONDS):
    """Kelime zamanlarini [(start, end, kelime)] okunabilir altyazi cue'larina toplar.

    Cumle sonunda (yeterince uzunsa) veya karakter/sure siniri asilinca boler.
    Donen: [{'start', 'end', 'text'}] (tek satir metin).
    """
    cues = []
    current = None
    for start, end, text in words:
        token = ' '.join(str(text).split())
        if not token:
            continue
        too_long = current and (len(current['text']) + 1 + len(token) > max_chars
                                or float(end) - current['start'] > max_seconds)
        # Cumleyi bitiren kelime sinirlari az asiyorsa tek basina yetim cue olmasin.
        if too_long and _SENTENCE_END.search(token)                 and len(current['text']) + 1 + len(token) <= max_chars + 12                 and float(end) - current['start'] <= max_seconds + 2:
            too_long = False
        if too_long:
            cues.append(current)
            current = None
        if current is None:
            current = {'start': float(start), 'end': float(end), 'text': token}
        else:
            current['text'] += ' ' + token
            current['end'] = float(end)
        if _SENTENCE_END.search(token) and len(current['text']) >= 20:
            cues.append(current)
            current = None
    if current:
        cues.append(current)
    return cues


def wrap_lines(text, width=LINE_CHARS):
    """Uzun cue'yu gosterim icin ortaya en yakin bosluktan iki satira boler."""
    text = ' '.join(str(text).split())
    if len(text) <= width:
        return text
    middle = len(text) // 2
    spaces = [index for index, char in enumerate(text) if char == ' ']
    if not spaces:
        return text
    cut = min(spaces, key=lambda index: abs(index - middle))
    return text[:cut] + '\n' + text[cut + 1:]


def display_segments(segments):
    """Oynaticida gosterim icin satirlara bolunmus kopyalar."""
    return [dict(item, text=wrap_lines(item['text'])) for item in segments]


def language_label(code):
    names = {'en': 'İngilizce', 'tr': 'Türkçe', 'ja': 'Japonca', 'de': 'Almanca',
             'fr': 'Fransızca', 'es': 'İspanyolca', 'ko': 'Korece', 'zh': 'Çince',
             'it': 'İtalyanca', 'ru': 'Rusça', 'pt': 'Portekizce'}
    return names.get(str(code), str(code or '?'))


# --- onbellek ----------------------------------------------------------------
def cache_path(video, model_name=DEFAULT_MODEL, language='', base=None):
    return qa.cache_path(video, f'whisper-segments:{model_name}:{language or "auto"}', base)


def load_cached(video, model_name=DEFAULT_MODEL, language='', base=None):
    """Daha once cikarilmis transkript varsa dondurur, yoksa None."""
    try:
        path = cache_path(video, model_name, language, base)
        value = json.loads(read(path))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not value.get('segments'):
        return None
    return value


# --- ses + transkript ---------------------------------------------------------
def extract_audio(video, output):
    """Ilk ses akisini 16 kHz mono WAV olarak cikarir (video degismez)."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [media.ffmpeg_path(), '-v', 'error', '-y', '-i', str(video), '-map', '0:a:0',
               '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(output)]
    result = media._run(command)
    if result.returncode != 0 or not output.exists():
        detail = (result.stderr or '').strip()
        if 'matches no streams' in detail:
            raise ValueError('Videoda ses akışı yok; konuşmadan metin çıkarılamaz.')
        raise RuntimeError('Ses çıkarılamadı: ' + detail)
    return output


def _add_cuda_dll_dirs():
    """pip ile kurulan NVIDIA kutuphanelerini (nvidia-cublas-cu12, nvidia-cudnn-cu12)
    Windows DLL arama yoluna ekler; kurulu degillerse sessizce gecer."""
    if os.name != 'nt':
        return
    for name in ('nvidia.cublas', 'nvidia.cudnn'):
        try:
            module = __import__(name, fromlist=['__path__'])
        except ImportError:
            continue
        for root in getattr(module, '__path__', []):
            folder = Path(root) / 'bin'
            if folder.is_dir():
                os.add_dll_directory(str(folder))
                os.environ['PATH'] = str(folder) + os.pathsep + os.environ.get('PATH', '')


def _device_plan(device):
    """[(cihaz, compute_type)] deneme sirasi. 'auto': CUDA varsa once GPU."""
    if device == 'cpu':
        return [('cpu', 'int8')]
    _add_cuda_dll_dirs()
    if device == 'cuda':
        return [('cuda', 'float16')]
    try:
        import ctranslate2
        has_cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:  # ctranslate2 CUDA sorgusu ortamdan ortama farkli hata verebilir
        has_cuda = False
    return ([('cuda', 'float16')] if has_cuda else []) + [('cpu', 'int8')]


def transcribe(video, model_name=DEFAULT_MODEL, device='auto', language='', base=None,
               progress=None, cancelled=None, log=print):
    """Videonun konusmasini zaman damgali cue'lara cevirir (onbellekli).

    Donen: {'segments', 'language', 'model', 'duration', 'device'}.
    `progress(islenen_saniye, toplam_saniye)`; `cancelled()` True ise GracefulStop.
    """
    cached = load_cached(video, model_name, language, base)
    if cached:
        log('Konuşmadan metin önbellekten yüklendi.')
        return cached
    ok, message = available()
    if not ok:
        raise RuntimeError(message)
    from faster_whisper import WhisperModel

    folder = Path(base or qa.work_dir()) / 'qa'
    stem = re.sub(r'[^\w.-]+', '_', Path(video).stem)[:40] or 'video'
    audio = extract_audio(video, folder / f'{stem}.audio.wav')
    log('Ses çıkarıldı; Whisper modeli yükleniyor (ilk kullanımda indirilir): ' + model_name)
    try:
        errors = []
        for target, compute_type in _device_plan(device):
            try:
                model = WhisperModel(model_name, device=target, compute_type=compute_type,
                                     download_root=str(model_dir()))
                result = _run_model(model, audio, language, progress, cancelled)
            except GracefulStop:
                raise
            except Exception as error:  # CUDA DLL eksikligi vb. calisma aninda cikar
                errors.append(f'{target}: {error}')
                log(f'Whisper {target} ile çalışamadı: {error}')
                continue
            result.update(model=model_name, device=target)
            break
        else:
            raise RuntimeError('Konuşmadan metin başarısız: ' + ' | '.join(errors))
    finally:
        try:
            audio.unlink()
        except OSError:
            pass
    if not result['segments']:
        raise ValueError('Seste konuşma bulunamadı.')
    save_json(cache_path(video, model_name, language, base), result)
    log(f'Konuşmadan metin hazır: {len(result["segments"])} satır, dil: '
        f'{language_label(result["language"])}, cihaz: {result["device"]}.')
    return result


def read_wav(path):
    """16 kHz mono PCM WAV -> float32 dizi. faster-whisper'in PyAV ile cozmesine gerek
    kalmaz (faster-whisper 1.2.1, PyAV 15+ ile 'metadata_errors' hatasi veriyor)."""
    import wave
    import numpy as np
    with wave.open(str(path), 'rb') as stream:
        frames = stream.readframes(stream.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _run_model(model, audio, language, progress, cancelled):
    iterator, info = model.transcribe(read_wav(audio), language=language or None, vad_filter=True,
                                      word_timestamps=True, beam_size=5)
    total = int(getattr(info, 'duration', 0) or 0)
    words = []
    for segment in iterator:
        if cancelled and cancelled():
            raise GracefulStop('Konuşmadan metin durduruldu.')
        if segment.words:
            words.extend((word.start, word.end, word.word) for word in segment.words)
        else:
            words.append((segment.start, segment.end, segment.text))
        if progress:
            progress(int(segment.end), total)
    return {'segments': regroup_words(words), 'language': getattr(info, 'language', '') or '',
            'duration': float(total)}
