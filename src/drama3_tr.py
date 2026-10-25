"""Drama 3 TR ses motoru (F176): kasparovabi/drama-3-tr (tam Drama 3 okuyucu + 32 uzmanli Turkce konusmaci).

Model Aktar klasorunde degil, kullanicinin sectigi klasorde durur (ui.json tts.drama3_tr_dir; ~45 GB, hizli
NVMe onerilir). Klasor reponun kendisidir: engine.py, fish-speech/, models/drama-3/ (orijinal fishaudio/drama-3
checkpoint'i ve codec), speaker.safetensors ve Python ortami (.venv). Aktar, engines/drama3-tr/server.py'yi o
ortamin Python'uyla alt surec olarak baslatir; surec ses motoru durunca ya da Aktar kapaninca kapanir; Aktar
cokse de: Windows'ta is nesnesi, her platformda da sunucu betigi stdin borusu kapaninca kendini kapatir. Klon kaydi istek basina gider, sunucu yeniden
baslamaz (dublajda konusmaci basina ses).

Metin bolme, duygu etiketi, klon kaydi hazirlama ve atlama denetimleri drama3 ile ortaktir.
"""
from __future__ import annotations

import array
import base64
import collections
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave

import drama3
import tr_numbers

ENGINE_ID = 'drama3-tr'
PREF_DIR = 'drama3_tr_dir'
PREF_BACKEND = 'drama3_tr_backend'   # F188: 'local' (klasordeki model) | 'openrouter' (bulut, openrouter_tts)
BACKENDS = ('local', 'openrouter')
SERVER_SCRIPT = 'server.py'          # engines/drama3-tr/server.py, veri klasorune kopyalanip calistirilir
REQUIRED = ('engine.py', 'checkpoint.py', 'prepare_data.py', 'disk.py', 'fish-speech/fish_speech',
            'models/drama-3/codec.pth', 'speaker.safetensors')
PYTHONS = ('.venv/Scripts/python.exe', 'venv/Scripts/python.exe', '.venv/bin/python', 'venv/bin/python')
START_TIMEOUT = 900        # model yukleme (diskten 41,5 GB okuyucu) + codec; ilk acilista uzun surebilir
REQUEST_TIMEOUT = 300
STOP_TIMEOUT = 10
LOG_LINES = 40
# Model karti: temperature 1.0, top-p 0.9; yonerge yonlendirmesi (cfg) 4 fisiltiyi belirgin bicimde artirdi
SETTINGS = {'max_chars': (200, 60, 400), 'cfg': (4.0, 0.0, 6.0), 'temperature': (1.0, 0.5, 1.3)}
TOP_P = 0.9
RETRIES = 1                # susan/takilan parca icin ek deneme (sonuncusu etiketsiz)
# F176: ilk istek CUDA grafiklerini yakalar ve kaydin on okumasini yapar (kullanicinin olcumunde 51 sn, sonrakiler
# 4-12 sn); yuklemede bu metinle bir kez istenir, okuma basladiginda ilk cumle beklemez
WARMUP_TEXT = 'Merhaba.'


class ServerError(drama3.ServerError):
    """Drama 3 TR sunucusu baslatilamadi ya da hata dondurdu."""


# ---------------------------------------------------------------- klasor denetimi
def python_path(folder):
    folder = Path(folder)
    for name in PYTHONS:
        if (folder / name).is_file():
            return folder / name
    return None


def check_folder(folder):
    """Secilen klasorun durumu: {'ok', 'folder', 'python', 'missing': [...], 'message'}."""
    text = str(folder or '').strip()
    if not text:
        return {'ok': False, 'folder': '', 'python': None, 'missing': [],
                'message': 'Drama 3 TR klasörü seçilmedi (Ayarlar → Ses).'}
    root = Path(text)
    if not root.is_dir():
        return {'ok': False, 'folder': text, 'python': None, 'missing': [], 'message': f'Klasör bulunamadı: {text}'}
    missing = [name for name in REQUIRED if not (root / name).exists()]
    python = python_path(root)
    if python is None:
        missing.append('.venv (Python ortamı)')
    if missing:
        return {'ok': False, 'folder': str(root), 'python': None, 'missing': missing,
                'message': 'Drama 3 TR klasöründe eksikler var: ' + ', '.join(missing)}
    return {'ok': True, 'folder': str(root), 'python': str(python), 'missing': [],
            'message': f'Drama 3 TR klasörü hazır ({root})'}


# ---------------------------------------------------------------- alt surec Aktar'a baglanir
def _bind_to_parent(process):
    """Windows: alt sureci 'kapaninca oldur' is nesnesine koyar; Aktar cokse de sunucu arkada kalmaz.
    Donen tutamac surec boyunca saklanmali."""
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)

    class Basic(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('Reads', 'Writes', 'Others', 'ReadBytes', 'WriteBytes',
                                                         'OtherBytes')]

    class Extended(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', Counters), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t)]

    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))   # ExtendedLimitInformation
    kernel.AssignProcessToJobObject(job, int(process._handle))
    return job


def child_env():
    """Sunucu surecinin ortami: Aktar'in kendisine ekledikleri cikar (F176). Whisper'in CUDA 12 klasorleri
    (speech._add_cuda_dll_dirs) ve Aktar'in bin\\ / paket klasoru PATH'te onde kalirsa klasordeki torch (CUDA 13)
    yanlis DLL'leri yukleyip takilabiliyor; paketli Aktar'in PyInstaller degiskenleri de alt surece gecmemeli."""
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(('_PYI_', '_MEIPASS')) and key.upper() not in ('PYTHONHOME', 'PYTHONPATH')}
    speech = sys.modules.get('speech')
    added = {os.path.normcase(os.path.abspath(str(folder))) for folder in getattr(speech, '_cuda_dirs_added', [])}
    roots = [Path(sys._MEIPASS)] if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS') else []
    roots.append(Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False)
                  else Path(__file__).resolve().parent.parent)
    roots = [os.path.normcase(os.path.abspath(str(root))) for root in roots]

    def own(entry):
        entry = os.path.normcase(os.path.abspath(entry))
        return entry in added or any(entry == root or entry.startswith(root + os.sep) for root in roots)

    for key in [name for name in env if name.upper() == 'PATH']:
        env[key] = os.pathsep.join(entry for entry in env[key].split(os.pathsep) if entry and not own(entry))
    env.update(PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
    return env


def _spawn(command, **options):
    """Popen; paketli Aktar'da Windows DLL arama klasoru (SetDllDirectory, PyInstaller'in gecici klasoru) alt
    surece miras kalmasin diye baslatirken sifirlanir."""
    reset = os.name == 'nt' and getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')
    if reset:
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        return subprocess.Popen(command, **options)
    finally:
        if reset:
            ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class Server:
    """Klasordeki Python ile calisan sunucu sureci: baslatir, hazir olmasini bekler, durdurur."""

    def __init__(self, folder, python, script, log=None):
        self.folder, self.python, self.script = Path(folder), Path(python), Path(script)
        self._log = log or (lambda _message: None)
        self.port = None
        self.process = None
        self._job = None
        self._lines = collections.deque(maxlen=LOG_LINES)
        self._ready = threading.Event()
        self.stage = ''

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}'

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        self.port = free_port()
        env = child_env()
        command = [str(self.python), '-u', str(self.script), '--folder', str(self.folder), '--port', str(self.port),
                   '--speaker', str(self.folder / 'speaker.safetensors')]
        # Aktar cokerse sunucu arkada kalmasin. Windows: is nesnesi (_bind_to_parent); stdin DEVNULL, cunku stdin
        # borusunu okuyan bir is parcacigi torch import'unu kilitliyordu (stdin'e bakan cagri okuma bitene kadar
        # bekliyor). Linux: stdin acik kalir, Aktar kapanir ya da cokerse boru kapanir, sunucu betigi kendini
        # kapatir (PR_SET_PDEATHSIG sureci baslatan is parcacigina bagli; yukleme bitince sunucu kapaniyordu).
        windows = os.name == 'nt'
        extra = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if windows else {}
        self.process = _spawn(command, cwd=str(self.folder), env=env,
                              stdin=subprocess.DEVNULL if windows else subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **extra)
        try:
            self._job = _bind_to_parent(self.process)
        except OSError:
            self._job = None
        threading.Thread(target=self._read, name='drama3-tr-log', daemon=True).start()

    def _read(self):
        for raw in self.process.stdout:
            line = raw.decode('utf-8', 'replace').rstrip()
            if not line:
                continue
            self._lines.append(line)
            if line.startswith('AKTAR STAGE '):
                self.stage = line[len('AKTAR STAGE '):]
            elif line.startswith('AKTAR READY'):
                self._ready.set()
            self._log(f'Drama 3 TR: {line}')

    def tail(self, count=8):
        return '\n'.join(list(self._lines)[-count:])

    def wait_ready(self, timeout=START_TIMEOUT, on_stage=None):
        end, shown = time.monotonic() + timeout, None
        while not self._ready.wait(0.25):
            if on_stage and self.stage and self.stage != shown:
                shown = self.stage
                on_stage(shown)
            if not self.alive:
                raise ServerError('Drama 3 TR sunucusu başlarken kapandı. Son satırlar:\n' + (self.tail() or '(çıktı yok)'))
            if time.monotonic() > end:
                self.stop()
                raise ServerError(f'Drama 3 TR sunucusu {timeout // 60} dakikada hazır olmadı. Son satırlar:\n'
                                  + (self.tail() or '(çıktı yok)'))

    def stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(STOP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    pass
        for pipe in filter(None, (process.stdin, process.stdout)):
            try:
                pipe.close()
            except OSError:
                pass
        if self._job is not None and os.name == 'nt':
            import ctypes
            ctypes.WinDLL('kernel32').CloseHandle(ctypes.c_void_p(self._job))
            self._job = None


def speech(url, text, reference, settings, timeout=REQUEST_TIMEOUT, retries=1):
    """Bir parcayi WAV bayt olarak uretir; 500'de `retries` kez yeniden dener."""
    body = json.dumps({'text': text, 'reference': reference, 'cfg': settings['cfg'],
                       'temperature': settings['temperature'], 'top_p': TOP_P}, ensure_ascii=False).encode('utf-8')
    for attempt in range(retries + 1):
        request = urllib.request.Request(url + '/tts', data=body, method='POST',
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code >= 500 and attempt < retries:
                continue
            raise ServerError(f'Drama 3 TR sunucusu ses üretemedi (HTTP {error.code}): {drama3._detail(error)}') from error
        except (urllib.error.URLError, OSError) as error:
            raise ServerError(f'Drama 3 TR sunucusuna ulaşılamadı: {getattr(error, "reason", None) or error}') from error
    raise ServerError('Drama 3 TR sunucusu ses üretemedi.')   # pragma: no cover


def backend(prefs):
    """F188: secili calisma yeri ('local' varsayilan)."""
    value = str((prefs or {}).get(PREF_BACKEND) or 'local')
    return value if value in BACKENDS else 'local'


# ---------------------------------------------------------------- motor (tts.InlineWorker)
class Engine:
    """tts.InlineWorker'in cagirdigi motor: load() sunucuyu baslatir ve kaydi hazirlar, say() WAV dondurur."""

    def __init__(self, data_dir, prefs=None, stage=None, transcribe=None, log=None, script=None):
        self.data_dir = Path(data_dir)
        self._prefs = prefs or (lambda: {})
        self._stage = stage or (lambda _message: None)
        self._transcribe = transcribe
        self._log = log or (lambda _message: None)
        self._script = Path(script) if script else Path(__file__).resolve().parent.parent / 'engines' / ENGINE_ID / SERVER_SCRIPT
        self._lock = threading.Lock()
        self.server = None
        self.reference = None
        self.cloud = False       # F188: son yukleme OpenRouter kipinde
        self._warm = None        # (sunucu, kayit anahtari): isitma istegi yapildi

    def _server_script(self):
        """Sunucu betiginin veri klasorundeki kopyasi (paketli Aktar'da kaynak gecici klasorde durur)."""
        target = self.data_dir / 'aktar_server.py'
        source = self._script
        if not source.is_file():
            raise ServerError(f'Drama 3 TR sunucu betiği bulunamadı: {source}')
        data = source.read_bytes()
        if not target.is_file() or target.read_bytes() != data:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return target

    def _ensure_server(self):
        state = check_folder(self._prefs().get(PREF_DIR))
        if not state['ok']:
            raise ValueError(state['message'])
        server = self.server
        if server and server.alive and server.folder == Path(state['folder']):
            return server
        self.stop()
        self._stage('Drama 3 TR sunucusu başlatılıyor…')
        server = Server(state['folder'], state['python'], self._server_script(), self._log)
        server.start()
        self.server = server
        server.wait_ready(on_stage=self._stage)
        return server

    def load(self, voice, options):
        reference = (options or {}).get('reference')
        if not reference:
            raise ValueError('Drama 3 TR için bir ses kaydı seçin (Ayarlar → Ses ya da okuyucudaki ses seçici).')
        self._stage('Klon kaydı hazırlanıyor…')
        prepared = drama3.prepare_reference(reference, (options or {}).get('reference_text'),
                                            self.data_dir / 'kayitlar', self._transcribe, 'tr', self._log)
        data = base64.b64decode(prepared['data'])
        key = hashlib.sha1(data + prepared['text'].encode('utf-8')).hexdigest()[:20]
        path = self.data_dir / 'kayitlar' / f'{key}.ref.wav'
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if backend(self._prefs()) == 'openrouter':
            return self._load_cloud(key, data, prepared)
        self.cloud = False
        server = self._ensure_server()
        self.reference = {'key': key, 'path': str(path), 'text': prepared['text']}
        if self._warm != (server, key):
            self._stage('Drama 3 TR ısınıyor (ilk açılışta bir dakika kadar sürebilir)…')
            speech(server.url, WARMUP_TEXT, self.reference, self.settings())
            self._warm = (server, key)
        return {'device': 'sunucu', 'reference_text': prepared['text'], 'reference_seconds': prepared['seconds']}

    def _load_cloud(self, key, data, prepared):
        """F188: OpenRouter kipi: yerel sunucu durur (GPU bosalir), kayit istege konacak bicimde (MP3) saklanir.
        Isitma istegi yapilmaz (ucretli ve gereksiz)."""
        import openrouter_tts
        if not openrouter_tts.api_key():
            raise ValueError('OpenRouter API anahtarı kaydedilmedi (Ayarlar → Ses → Drama 3 TR).')
        self.stop()
        self._stage('Klon kaydı OpenRouter için hazırlanıyor…')
        audio, audio_format = openrouter_tts.reference_audio(data)
        self.reference = {'key': key, 'text': prepared['text'], 'audio': audio, 'format': audio_format}
        self.cloud = True
        self._log(f'Drama 3 TR OpenRouter kipinde: klon kaydı {prepared["seconds"]} sn, '
                  f'{len(audio) // 1024} KB {audio_format.upper()} her istekle gidecek')
        return {'device': 'bulut', 'reference_text': prepared['text'], 'reference_seconds': prepared['seconds']}

    def _speech(self, text, settings):
        if self.cloud:
            import openrouter_tts
            return openrouter_tts.speech(text, self.reference, {'temperature': settings['temperature'], 'top_p': TOP_P},
                                         log=self._log)
        return speech(self.server.url, text, self.reference, settings)

    def settings(self):
        given = (self._prefs().get('engine_settings') or {}).get(ENGINE_ID) or {}
        result = {}
        for key, (default, low, high) in SETTINGS.items():
            try:
                value = float(given[key])
            except (KeyError, TypeError, ValueError):
                value = default
            result[key] = min(high, max(low, value))
        result['max_chars'] = int(result['max_chars'])
        return result

    def _piece(self, piece, settings):
        """Bir parca: [(ornekler, hiz)]. Susan ya da takilan (cok uzun) parca yeniden istenir, son deneme
        etiketsiz. F176: fisilti icin drama3'teki gibi uc deneme (F169) yapilmaz: her istek ~4 sn sabit sure
        ekliyor ve yonerge gucu fisiltiyi zaten belirginlestiriyor."""
        untagged = drama3.untag(piece)
        best = None
        attempts = 1 + RETRIES
        for attempt in range(attempts):
            text = untagged if untagged and attempt == attempts - 1 else piece
            samples, rate = drama3.read_pcm(self._speech(drama3.model_text(text), settings))
            if not drama3.fell_silent(text, samples, rate):
                return [(samples, rate)]
            self._log(f'Drama 3 TR: model cümlenin bir kısmını atladı, yeniden deneniyor ({attempt + 1}): {piece[:60]}')
            score = drama3.voiced_seconds(samples, rate)
            if best is None or score > best[0]:
                best = (score, (samples, rate))
        self._log(f'UYARI: Drama 3 TR bu parçayı tam okuyamadı: {piece[:80]}')
        return [best[1]]

    def say(self, text, speed=1.0, tag=''):
        text = tr_numbers.spoken(drama3.tagged(text, tag) if tag else text)   # F198: '44. bölüm', 'IV. Murad'
        if self.reference is None or not (self.cloud or (self.server and self.server.alive)):
            raise RuntimeError('Ses motoru hazır değil.')
        clips, rate = [], None
        settings = self.settings()
        with self._lock:
            for piece, gap in drama3.split_text(text, settings['max_chars'], split_tags=False):
                parts = self._piece(piece, settings)
                for number, (samples, piece_rate) in enumerate(parts):
                    if rate is not None and piece_rate != rate:
                        raise ServerError('Drama 3 TR sunucusu parçalar için farklı örnekleme hızları döndürdü.')
                    rate = piece_rate
                    clips.append((drama3.shorten_silences(samples, rate),
                                  gap if number == len(parts) - 1 else drama3.CLAUSE_GAP))
        if not clips:
            return drama3.wav_bytes(array.array('h'), 44100), 0.0
        data = drama3.change_speed(drama3.wav_bytes(drama3.join_clips(clips, rate), rate), speed)
        with wave.open(io.BytesIO(data)) as stream:
            duration = stream.getnframes() / stream.getframerate()
        return data, duration

    def stop(self):
        server, self.server = self.server, None
        if server:
            server.stop()
