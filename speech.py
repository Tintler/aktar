"""Konusmadan metin (F48/F50): altyazisiz videolar icin faster-whisper ile transkript.

Iki calisma yolu (`backend()`):
  - 'inprocess': kaynak koddan calisirken faster-whisper kuruluysa (requirements-whisper.txt)
  - 'helper': uygulama klasorundeki ayri `aktar-whisper/aktar-whisper(.exe)` paketi
    (Windows'ta DERLE_WHISPER.cmd, Linux'ta derle_whisper.sh ile derlenir; ffmpeg'in
    bin/ icinde durmasi gibi). Derlenmis Aktar faster-whisper'i icermez; paket
    yanindaysa onu alt surec olarak calistirir.
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
from app_core import APP_DIR, EXE_SUFFIX, WINDOWS, GracefulStop, read, save_json

DEFAULT_MODEL = 'large-v3-turbo'
MODELS = ('large-v3-turbo', 'large-v3', 'medium', 'small', 'base')
DEVICES = ('auto', 'cuda', 'cpu')
CUE_CHARS = 84       # bir altyazi cue'sunda en fazla karakter (2 x 42)
CUE_SECONDS = 6.0    # bir cue'nun en uzun suresi
LINE_CHARS = 42      # gosterimde satir genisligi
HELPER_NAME = 'aktar-whisper'
BUILD_WHISPER_SCRIPT = 'DERLE_WHISPER.cmd' if WINDOWS else 'derle_whisper.sh'
INSTALL_HINT = ('Konuşmadan metin için faster-whisper kurulu değil. Kurmak için uygulama '
                'klasöründe: ' + ('py -3 -m pip install -r requirements-whisper.txt' if WINDOWS
                                  else './kur.sh --whisper ya da .venv/bin/pip install -r '
                                       'requirements-whisper.txt') +
                ' (veya aktar-whisper paketini uygulama klasörüne koyun; KULLANIM.md 1.5).')
_SENTENCE_END = re.compile(r'[.?!…]["\')\]]*$')


FROZEN_HINT = (f'Konuşmadan metin (Whisper) paketi bulunamadı. Aktar{EXE_SUFFIX} ile aynı klasöre '
               f'"aktar-whisper" klasörünü koyun ({BUILD_WHISPER_SCRIPT} ile derlenir; '
               'KULLANIM.md 1.5).')


def helper_command():
    """Ayri Whisper paketinin calistirma komutu (liste) veya None."""
    candidate = APP_DIR / HELPER_NAME / (HELPER_NAME + EXE_SUFFIX)
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
# ctranslate2 4.x: CUDA 12 + cuDNN 9. pip paketleri Windows'ta <paket>/bin/*.dll,
# Linux'ta <paket>/lib/*.so.* olarak kurulur.
CUDA_MARKERS_WINDOWS = ('cublas64_12.dll', 'cudnn64_9.dll')
CUDA_MARKERS_LINUX = ('libcublas.so.12', 'libcudnn.so.9')
_CUDA_MARKERS = CUDA_MARKERS_WINDOWS if WINDOWS else CUDA_MARKERS_LINUX
_CUDA_SUBDIR, _CUDA_GLOB = ('bin', '*.dll') if WINDOWS else ('lib', 'lib*.so*')
_cuda_dirs_added = []


def check_cuda_dir(folder):
    """Kullanicinin gosterdigi klasorde eksik cuBLAS/cuDNN kutuphaneleri (bos liste: tamam)."""
    folder = Path(folder)
    return [name for name in _CUDA_MARKERS if not (folder / name).is_file()]


def _cuda_dll_dirs(extra=''):
    """NVIDIA kutuphane klasorleri, oncelik sirasiyla: Ayarlar'da gosterilen klasor (baska
    programlarla ortak kullanilan cuBLAS/cuDNN), aktar-whisper paketine derleme betigiyle
    konanlar, pip'le kurulanlar (nvidia-cublas-cu12, nvidia-cudnn-cu12)."""
    folders = [Path(extra)] if str(extra or '').strip() else []
    frozen_root = getattr(sys, '_MEIPASS', None)
    if frozen_root:  # paket: _internal/nvidia/<kutuphane>/bin|lib (namespace paket import edilemeyebilir)
        folders += [Path(frozen_root) / 'nvidia' / name / _CUDA_SUBDIR for name in _CUDA_LIBS]
    for name in _CUDA_LIBS:
        try:
            module = __import__('nvidia.' + name, fromlist=['__path__'])
        except ImportError:
            continue
        folders += [Path(root) / _CUDA_SUBDIR for root in getattr(module, '__path__', [])]
    # Bos klasorler (ornegin pip kaldirmasindan kalanlar) sayilmaz.
    return list(dict.fromkeys(folder for folder in folders
                              if folder.is_dir() and any(folder.glob(_CUDA_GLOB))))


def _add_cuda_dll_dirs(extra=''):
    """NVIDIA kutuphane klasorlerini yukleyiciye tanitir (her klasor bir kez).

    Windows: DLL arama yoluna eklenir. Linux: LD_LIBRARY_PATH surec basladiktan sonra
    okunmadigi icin kutuphaneler RTLD_GLOBAL ile onceden yuklenir; ctranslate2 sonra
    ayni soname'i (libcublas.so.12 ...) dlopen edince bunlar kullanilir. NVIDIA
    surucusu yoksa (GPU yok) Linux'ta hicbir sey yuklenmez.
    """
    if not WINDOWS and not os.path.exists('/proc/driver/nvidia/version'):
        return []
    new = [folder for folder in _cuda_dll_dirs(extra) if folder not in _cuda_dirs_added]
    for folder in new:
        if WINDOWS:
            os.add_dll_directory(str(folder))
        os.environ['PATH'] = str(folder) + os.pathsep + os.environ.get('PATH', '')
        _cuda_dirs_added.append(folder)
    if new and not WINDOWS:
        _preload_shared_libs([path for folder in new for path in sorted(folder.glob(_CUDA_GLOB))])
    return list(_cuda_dirs_added)


def _preload_shared_libs(paths):
    """Linux: .so dosyalarini RTLD_GLOBAL ile yukler. Birbirine bagimli kutuphaneler
    (cuDNN alt kutuphaneleri cuBLAS'a bagli olabilir) icin, ilerleme durana kadar
    basarisiz olanlar tekrar denenir. Donen: yuklenemeyenler."""
    import ctypes

    pending = [path for path in paths if path.is_file()]
    while pending:
        failed = []
        for path in pending:
            try:
                ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                failed.append(path)
        if len(failed) == len(pending):
            return failed
        pending = failed
    return []


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
               progress=None, cancelled=None, log=print, cuda_dir=''):
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
                        cancelled=cancelled, log=log, download_root=str(model_dir()),
                        cuda_dir=cuda_dir)
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
                cancelled=None, log=print, download_root=None, cuda_dir=''):
    """WAV'i faster-whisper ile cozer; GPU calismazsa bir sonraki cihaza (CPU) duser.

    Hem uygulama icinde hem ayri paketin (whisper_cli.py) icinde calisir.
    Donen: {'segments', 'language', 'duration', 'device'}.
    """
    from faster_whisper import WhisperModel

    if device != 'cpu':
        if str(cuda_dir or '').strip():
            missing = check_cuda_dir(cuda_dir)
            if missing:
                log(f'UYARI: GPU kütüphane klasöründe eksik: {", ".join(missing)} ({cuda_dir})')
        added = _add_cuda_dll_dirs(cuda_dir)
        log('GPU kütüphaneleri: ' + (', '.join(str(folder) for folder in added) if added
                                    else 'bulunamadı (Ayarlar\'da GPU kütüphane klasörü '
                                         'gösterilmedi, nvidia-cublas-cu12 / nvidia-cudnn-cu12 '
                                         'de kurulu değil); GPU varsa yine de denenecek.'))
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
                cancelled=None, log=print, download_root=None, cuda_dir=''):
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
    if str(cuda_dir or '').strip():
        command += ['--cuda-dir', str(cuda_dir)]
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
