"""Konusmadan metin (F48/F50): altyazisiz videolar icin faster-whisper ile transkript.

Iki calisma yolu (`backend()`):
  - 'inprocess': kaynak koddan calisirken faster-whisper kuruluysa (requirements-whisper.txt)
  - 'helper': uygulama klasorundeki ayri `aktar-whisper/aktar-whisper.exe` paketi
    (DERLE_WHISPER.cmd ile derlenir; ffmpeg'in bin/ icinde durmasi gibi). Aktar.exe
    faster-whisper'i icermez; paket yanindaysa onu alt surec olarak calistirir.
Ikisi de yoksa `available()` anlamli Turkce mesaj dondurur. Kaynak video
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
import subprocess
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
HELPER_NAME = 'aktar-whisper'
INSTALL_HINT = ('Konuşmadan metin için faster-whisper kurulu değil. Kurmak için uygulama '
                'klasöründe: py -3 -m pip install -r requirements-whisper.txt '
                '(veya aktar-whisper paketini uygulama klasörüne koyun; KULLANIM.md 1.5).')
_SENTENCE_END = re.compile(r'[.?!…]["\')\]]*$')


FROZEN_HINT = ('Konuşmadan metin (Whisper) paketi bulunamadı. Aktar.exe ile aynı klasöre '
               '"aktar-whisper" klasörünü koyun (DERLE_WHISPER.cmd ile derlenir; KULLANIM.md 1.5).')


def helper_command():
    """Ayri Whisper paketinin calistirma komutu (liste) veya None."""
    candidate = APP_DIR / HELPER_NAME / (HELPER_NAME + '.exe')
    return [str(candidate)] if candidate.exists() else None


def backend():
    """'inprocess' | 'helper' | None. Derlenmis Aktar.exe faster-whisper icermez."""
    if not getattr(sys, 'frozen', False):
        try:
            import faster_whisper  # noqa: F401
            return 'inprocess'
        except ImportError:
            pass
    return 'helper' if helper_command() else None


def available():
    """(kullanilabilir mi, degilse kullaniciya gosterilecek mesaj)."""
    if backend():
        return True, ''
    return False, FROZEN_HINT if getattr(sys, 'frozen', False) else INSTALL_HINT


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


_CUDA_LIBS = ('cublas', 'cudnn')
_cuda_dirs_added = []


def _cuda_dll_dirs():
    """pip'le kurulan (nvidia-cublas-cu12, nvidia-cudnn-cu12) veya aktar-whisper paketine
    DERLE_WHISPER.cmd ile konan NVIDIA DLL klasorleri."""
    folders = []
    frozen_root = getattr(sys, '_MEIPASS', None)
    if frozen_root:  # paket: _internal/nvidia/<kutuphane>/bin (namespace paket import edilemeyebilir)
        folders += [Path(frozen_root) / 'nvidia' / name / 'bin' for name in _CUDA_LIBS]
    for name in _CUDA_LIBS:
        try:
            module = __import__('nvidia.' + name, fromlist=['__path__'])
        except ImportError:
            continue
        folders += [Path(root) / 'bin' for root in getattr(module, '__path__', [])]
    return list(dict.fromkeys(folder for folder in folders if folder.is_dir()))


def _add_cuda_dll_dirs():
    """NVIDIA DLL klasorlerini Windows DLL arama yoluna bir kez ekler; eklenenleri dondurur."""
    if os.name != 'nt' or _cuda_dirs_added:
        return list(_cuda_dirs_added)
    for folder in _cuda_dll_dirs():
        os.add_dll_directory(str(folder))
        os.environ['PATH'] = str(folder) + os.pathsep + os.environ.get('PATH', '')
        _cuda_dirs_added.append(folder)
    return list(_cuda_dirs_added)


def _device_plan(device):
    """[(cihaz, compute_type)] deneme sirasi. 'auto': CUDA varsa once GPU."""
    if device == 'cpu':
        return [('cpu', 'int8')]
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
    mode = backend()
    if mode is None:
        raise RuntimeError(available()[1])

    folder = Path(base or qa.work_dir()) / 'qa'
    stem = re.sub(r'[^\w.-]+', '_', Path(video).stem)[:40] or 'video'
    audio = extract_audio(video, folder / f'{stem}.audio.wav')
    log('Ses çıkarıldı; Whisper modeli yükleniyor (ilk kullanımda indirilir): ' + model_name)
    try:
        runner = run_whisper if mode == 'inprocess' else _run_helper
        result = runner(audio, model_name, device, language, progress=progress,
                        cancelled=cancelled, log=log, download_root=str(model_dir()))
        result.update(model=model_name)
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


def run_whisper(audio, model_name=DEFAULT_MODEL, device='auto', language='', progress=None,
                cancelled=None, log=print, download_root=None):
    """WAV'i faster-whisper ile cozer; GPU calismazsa bir sonraki cihaza (CPU) duser.

    Hem uygulama icinde hem ayri paketin (whisper_cli.py) icinde calisir.
    Donen: {'segments', 'language', 'duration', 'device'}.
    """
    from faster_whisper import WhisperModel

    if device != 'cpu':
        added = _add_cuda_dll_dirs()
        log('GPU kütüphaneleri: ' + (', '.join(f'{f.parent.name} ({f})' for f in added) if added
                                    else 'bulunamadı (nvidia-cublas-cu12 / nvidia-cudnn-cu12 '
                                         'kurulu değil); GPU varsa yine de denenecek.'))
    errors = []
    for target, compute_type in _device_plan(device):
        try:
            model = WhisperModel(model_name, device=target, compute_type=compute_type,
                                 download_root=download_root or str(model_dir()))
            result = _run_model(model, audio, language, progress, cancelled)
        except GracefulStop:
            raise
        except Exception as error:  # CUDA DLL eksikligi vb. calisma aninda cikar
            errors.append(f'{target}: {error}')
            log(f'Whisper {target} ile çalışamadı: {error}')
            continue
        result['device'] = target
        return result
    raise RuntimeError('Konuşmadan metin başarısız: ' + ' | '.join(errors))


def _run_helper(audio, model_name=DEFAULT_MODEL, device='auto', language='', progress=None,
                cancelled=None, log=print, download_root=None):
    """Ayri aktar-whisper paketini alt surec olarak calistirir (JSON satir protokolu).

    Paket stdout'a satir basina bir JSON yazar: {"progress": [i, n]}, {"log": "..."},
    {"result": {...}} veya {"error": "..."}. stderr (model indirme cubuklari vb.)
    work_files/qa altindaki gunluk dosyasina gider; hata olursa sonu mesaja eklenir.
    """
    command = helper_command()
    if command is None:
        raise RuntimeError(FROZEN_HINT)
    command = command + [str(audio), '--model', model_name, '--device', device,
                         '--language', language or '', '--models-dir',
                         str(download_root or model_dir())]
    log_path = Path(audio).with_suffix('.whisper.log')
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    result, error = None, ''
    with open(log_path, 'w', encoding='utf-8', errors='replace') as stderr:
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr,
                                       stdin=subprocess.DEVNULL, text=True, encoding='utf-8',
                                       errors='replace', **kwargs)
        except OSError as failure:
            raise RuntimeError('Whisper paketi çalıştırılamadı: ' + str(failure)) from None
        try:
            for line in process.stdout:
                if cancelled and cancelled():
                    raise GracefulStop('Konuşmadan metin durduruldu.')
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if 'progress' in message and progress:
                    progress(*message['progress'])
                elif 'log' in message:
                    log(str(message['log']))
                elif 'result' in message:
                    result = message['result']
                elif 'error' in message:
                    error = str(message['error'])
        finally:
            if process.poll() is None:
                process.kill()
            process.stdout.close()
            process.wait()
    try:
        tail = log_path.read_text(encoding='utf-8', errors='replace').strip()[-400:]
        log_path.unlink()
    except OSError:
        tail = ''
    if result is None:
        raise RuntimeError('Whisper paketi hata verdi: ' + (error or tail or
                                                             f'çıkış kodu {process.returncode}'))
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
