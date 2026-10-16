"""Oynatici icin yerel video sunucusu (yalnizca 127.0.0.1).

Web arayuzu videoyu HTML5 <video> ile oynatir. Tarayicinin dogrudan calabildigi dosyalar
(MP4/WebM; H.264/VP9/AV1 + AAC/MP3/Opus) oldugu gibi, Range istekleriyle sunulur. Digerleri
(MKV, AVI, AC3/DTS ses, ikinci ses parcasi) ffmpeg ile ANINDA parcali MP4'e paketlenir:
goruntu mumkunse kopyalanir (yeniden kodlanmaz), ses AAC'ye cevrilir. Bu akista sarma,
ffmpeg'i istenen andan yeniden baslatarak yapilir; arayuz `offset` kadar kaydirarak gosterir.

Her dosya rastgele bir anahtarla kaydedilir; sunucu kayitli olmayan dosyayi vermez.
Kaynak dosyalar yalnizca okunur.
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import subprocess
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import media

BROWSER_CONTAINERS = {'.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mov': 'video/mp4', '.webm': 'video/webm'}
BROWSER_VIDEO = {'h264', 'vp8', 'vp9', 'av1'}
BROWSER_AUDIO = {'aac', 'mp3', 'opus', 'vorbis', 'flac'}
CHUNK = 256 * 1024
KEYFRAME_WINDOW = 30.0   # sarma: bu kadar geriye kadar anahtar kare aranir


def _creationflags():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0


def probe(path):
    """Oynatma icin akislar: {'duration', 'video': {index, codec}|None, 'audio': [..], 'format'}."""
    command = [media.ffprobe_path(), '-v', 'error', '-show_streams', '-show_format', '-show_chapters',
               '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                            creationflags=_creationflags())
    if result.returncode != 0:
        raise RuntimeError('ffprobe videoyu okuyamadı: ' + (result.stderr or '').strip())
    value = json.loads(result.stdout or '{}')
    streams = value.get('streams', []) or []
    video = next((item for item in streams if item.get('codec_type') == 'video'
                  and not (item.get('disposition') or {}).get('attached_pic')), None)
    audio = [item for item in streams if item.get('codec_type') == 'audio']
    try:
        duration = float((value.get('format') or {}).get('duration') or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    chapters = []
    for item in value.get('chapters', []) or []:
        try:
            begin, end = float(item['start_time']), float(item['end_time'])
        except (KeyError, TypeError, ValueError):
            continue
        if end > begin:
            chapters.append({'start': begin, 'end': end, 'title': str((item.get('tags') or {}).get('title', '')).strip()})
    return {'duration': duration, 'chapters': sorted(chapters, key=lambda item: item['start']),
            'video': {'index': video.get('index'), 'codec': str(video.get('codec_name', '')).lower(),
                      'height': int(video.get('height') or 0), 'profile': str(video.get('profile', '')),
                      'level': int(video.get('level') or 0), 'pix_fmt': str(video.get('pix_fmt', ''))} if video else None,
            'audio': [{'index': item.get('index'), 'codec': str(item.get('codec_name', '')).lower()}
                      for item in audio]}


def hevc_ok(video, extra):
    """Arayuzun bildirdigi `extra` kodlarla (WebView'in kendi cozebildikleri) HEVC calinabilir mi:
    'hevc' 8 bit Main, 'hevc10' 10 bit Main 10 icindir (donanim cozucusu varsa)."""
    if video is None or video['codec'] != 'hevc':
        return False
    return ('hevc10' if '10' in video.get('pix_fmt', '') else 'hevc') in set(extra or ())


def plan(path, info, audio_index=None, transcode=False, extra=()):
    """Nasil oynatilacak: {'mode': 'direct'|'stream', 'video': 'copy'|'x264'|None, 'audio': index}.

    Ilk ses parcasi disinda bir parca secildiyse ya da kap/codec tarayiciya uygun degilse
    ffmpeg akisi kullanilir. Tarayici kopyalanan goruntuyu cozemezse (H.264 4:4:4 / 10 bit
    gibi) arayuz `transcode` ile yeniden ister: goruntu x264 ile yeniden kodlanir. `extra`:
    arayuzun bu bilgisayarda cozebildigini bildirdigi ek kodlar (bkz. hevc_ok)."""
    audio = info['audio']
    if audio_index is None and audio:
        audio_index = audio[0]['index']
    video = info['video']
    video_mode = None if video is None else ('copy' if (video['codec'] in BROWSER_VIDEO or hevc_ok(video, extra)) and not transcode
                                       else 'x264')
    first = audio[0]['index'] if audio else None
    chosen = next((item for item in audio if item['index'] == audio_index), None)
    direct = (Path(path).suffix.lower() in BROWSER_CONTAINERS and video_mode != 'x264'
              and (not audio or (audio_index == first and chosen and chosen['codec'] in BROWSER_AUDIO)))
    return {'mode': 'direct' if direct else 'stream', 'video': video_mode,
            'audio': chosen['index'] if chosen else None}


H264_PROFILES = {'baseline': 0x42, 'constrained baseline': 0x42, 'main': 0x4D, 'extended': 0x58, 'high': 0x64,
                 'high 10': 0x6E, 'high 4:2:2': 0x7A, 'high 4:4:4 predictive': 0xF4}


def stream_mime(info, plan_value):
    """Akisin MSE (MediaSource) tur dizgesi: 'video/mp4; codecs="avc1.64001f, mp4a.40.2"'."""
    codecs = []
    video = info['video']
    if plan_value['video'] == 'x264':
        codecs.append('avc1.640028')
    elif plan_value['video'] == 'copy' and video is not None:
        if video['codec'] == 'h264':
            # Bilinmeyen/egzotik profilde genel High dizgesi: tarayici cozemezse arayuz x264 ister.
            profile = H264_PROFILES.get(video['profile'].lower())
            level = video['level'] if 0 < video['level'] < 256 else 0x28
            codecs.append(f'avc1.{profile:02X}00{level:02X}' if profile in (0x42, 0x4D, 0x64) else 'avc1.640028')
        elif video['codec'] == 'hevc':
            ten = '10' in video.get('pix_fmt', '')
            level = video['level'] if 0 < video['level'] < 256 else 120
            codecs.append(f'hvc1.{2 if ten else 1}.{4 if ten else 6}.L{level}.B0')
        elif video['codec'] == 'vp9':
            codecs.append('vp09.00.10.08')
        elif video['codec'] == 'vp8':
            codecs.append('vp8')
        elif video['codec'] == 'av1':
            codecs.append('av01.0.05M.08')
    if plan_value['audio'] is not None:
        codecs.append('mp4a.40.2')
    return 'video/mp4; codecs="' + ', '.join(codecs) + '"'


def keyframe_before(path, seconds, video_index):
    """`seconds` anindan onceki son anahtar karenin zamani (bulunamazsa `seconds`)."""
    if seconds <= 0.5:
        return 0.0
    begin = max(0.0, seconds - KEYFRAME_WINDOW)
    command = [media.ffprobe_path(), '-v', 'error', '-select_streams', str(video_index), '-skip_frame', 'nokey',
               '-show_entries', 'frame=pts_time,best_effort_timestamp_time', '-of', 'csv=p=0',
               '-read_intervals', f'{begin:.3f}%{seconds + 0.05:.3f}', str(path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15,
                                creationflags=_creationflags())
    except (OSError, subprocess.TimeoutExpired):
        return seconds
    best = None
    for line in (result.stdout or '').splitlines():
        for value in line.split(','):
            try:
                time = float(value)
            except ValueError:
                continue
            if time <= seconds + 0.05 and (best is None or time > best):
                best = time
            break
    return best if best is not None else seconds


def stream_command(path, start, video_index, video_mode, audio_index, height=0, codec=''):
    """Parcali MP4 ureten ffmpeg komutu (stdout'a)."""
    command = [media.ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-nostdin']
    if start > 0:
        command += ['-ss', f'{start:.3f}']
    command += ['-i', str(path)]
    if video_index is not None:
        command += ['-map', f'0:{video_index}']
    if audio_index is not None:
        command += ['-map', f'0:{audio_index}']
    command += ['-sn', '-dn']
    if video_mode == 'copy':
        command += ['-c:v', 'copy']
        if codec == 'hevc':
            command += ['-tag:v', 'hvc1']   # MSE/WebView 'hev1' etiketli HEVC'yi kabul etmez
    elif video_mode == 'x264':
        command += ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23', '-pix_fmt', 'yuv420p']
        if height > 1080:
            command += ['-vf', 'scale=-2:1080']
    if audio_index is not None:
        command += ['-c:a', 'aac', '-b:a', '192k', '-ac', '2']
    command += ['-movflags', 'frag_keyframe+empty_moov+default_base_moof', '-f', 'mp4', 'pipe:1']
    return command


class _Handler(BaseHTTPRequestHandler):
    server_version = 'Aktar'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass  # konsola istek gunlugu yazilmaz

    def end_headers(self):
        # Arayuz baska bir yerel kokenden (pywebview sunucusu) fetch ile okur (Media Source).
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def _send_error(self, code):
        self.send_response(code)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):  # noqa: N802 - http.server adi
        parts = urlsplit(self.path)
        segments = parts.path.strip('/').split('/')
        if len(segments) not in (2, 3) or segments[0] not in ('f', 's', 'p'):
            return self._send_error(404)
        path = self.server.owner.files.get(segments[1])
        if path is None or not path.is_file():
            return self._send_error(404)
        if segments[0] == 'p' and len(segments) == 3:
            return self._page(path, segments[2], parse_qs(parts.query))
        if len(segments) != 2:
            return self._send_error(404)
        if segments[0] == 'f':
            return self._file(path)
        query = parse_qs(parts.query)
        return self._stream(path, query)

    def _file(self, path):
        size = path.stat().st_size
        start, end = 0, size - 1
        header = self.headers.get('Range', '')
        partial = header.startswith('bytes=')
        if partial:
            first, _, last = header[6:].split(',')[0].partition('-')
            try:
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                else:
                    start = max(0, size - int(last))
            except ValueError:
                return self._send_error(416)
            if start > end or start >= size:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', BROWSER_CONTAINERS.get(path.suffix.lower())
                         or mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        remaining = end - start + 1
        try:
            with path.open('rb') as stream:
                stream.seek(start)
                while remaining > 0:
                    data = stream.read(min(CHUNK, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except (ConnectionError, OSError):
            pass  # oynatici istegi biraktiginda (sarma) baglanti kopar

    def _page(self, path, number, query):
        """PDF sayfasinin PNG goruntusu (belge goruntuleyici); son cizilenler bellekte tutulur."""
        try:
            page = int(number)
            width = max(200, min(3000, int(query.get('w', ['1400'])[0])))
        except ValueError:
            return self._send_error(400)
        try:
            data = self.server.owner.page_png(path, page, width)
        except (ValueError, IndexError, OSError):
            return self._send_error(404)
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'max-age=3600')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionError, OSError):
            pass

    def _stream(self, path, query):
        def number(key, default=None):
            try:
                return int(query[key][0])
            except (KeyError, ValueError, IndexError):
                return default
        try:
            start = max(0.0, float(query.get('t', ['0'])[0]))
        except ValueError:
            start = 0.0
        video_mode = query.get('v', ['copy'])[0]
        if video_mode not in ('copy', 'x264', 'none'):
            return self._send_error(400)
        command = stream_command(path, start, None if video_mode == 'none' else number('vi'),
                                 None if video_mode == 'none' else video_mode, number('a'), number('h', 0),
                                 query.get('c', [''])[0])
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       stdin=subprocess.DEVNULL, creationflags=_creationflags())
        except OSError:
            return self._send_error(500)
        self.server.owner.track(process)
        self.send_response(200)
        self.send_header('Content-Type', 'video/mp4')
        self.send_header('Accept-Ranges', 'none')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                data = process.stdout.read1(CHUNK) if hasattr(process.stdout, 'read1') else process.stdout.read(CHUNK)
                if not data:
                    break
                self.wfile.write(data)
        except (ConnectionError, OSError):
            pass  # sarma ya da kapanis: tarayici baglantiyi birakti
        finally:
            self.server.owner.stop(process)


class MediaServer:
    PAGE_CACHE = 48   # bellekte tutulan en fazla cizilmis PDF sayfasi

    def __init__(self):
        self.files = {}
        self._processes = set()
        self._lock = threading.Lock()
        self._server = None
        self._pages = OrderedDict()

    def page_png(self, path, page, width):
        """Belge goruntuleyici icin PDF sayfasi (1'den baslar), uzun kenar ~`width` piksel."""
        import documents
        key = (str(path), int(page), int(width))
        with self._lock:
            if key in self._pages:
                self._pages.move_to_end(key)
                return self._pages[key]
        data = documents.render_pdf_page(path, int(page) - 1, long_side=int(width))
        with self._lock:
            self._pages[key] = data
            while len(self._pages) > self.PAGE_CACHE:
                self._pages.popitem(last=False)
        return data

    def page_url(self, path, page, width=1400):
        return f'{self.start().base}/p/{self.register(path)}/{int(page)}?w={int(width)}'

    def start(self):
        if self._server is None:
            self._server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
            self._server.daemon_threads = True
            self._server.owner = self
            threading.Thread(target=self._server.serve_forever, name='aktar-media', daemon=True).start()
        return self

    @property
    def base(self):
        host, port = self._server.server_address[:2]
        return f'http://{host}:{port}'

    def register(self, path):
        path = Path(path)
        for token, known in self.files.items():
            if known == path:
                return token
        token = secrets.token_urlsafe(16)
        self.files[token] = path
        return token

    def file_url(self, path):
        return f'{self.start().base}/f/{self.register(path)}'

    def stream_url(self, path, start, plan_value, info):
        video = info['video']
        mode = plan_value['video'] or 'none'
        query = f't={start:.3f}&v={mode}'
        if video is not None:
            query += f'&vi={video["index"]}&h={video.get("height") or 0}&c={video["codec"]}'
        if plan_value['audio'] is not None:
            query += f'&a={plan_value["audio"]}'
        return f'{self.start().base}/s/{self.register(path)}?{query}'

    def track(self, process):
        with self._lock:
            self._processes.add(process)

    def stop(self, process):
        with self._lock:
            self._processes.discard(process)
        if process.poll() is None:
            process.kill()
        try:
            process.wait(3)
        except subprocess.TimeoutExpired:
            pass
        if process.stdout:
            process.stdout.close()

    def shutdown(self):
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            self.stop(process)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

