"""Gazete (F225): telefon uygulamasi icin yerel ag sunucusu.

Yalnizca Gazete sayfasinda acikca baslatilinca calisir, pencere kapaninca durur. Yalnizca yerel ag
(ozel adres) ve bu bilgisayardan gelen istekleri kabul eder. Telefon bir kez, Aktar'da gosterilen alti
haneli kodla eslenir ve bir anahtar alir; eslenen telefonlar APP_DIR/gazete/telefonlar.json'da kalir
(Gazete sayfasindan silinebilir). Kod her baslatmada yenilenir.

Uclar (JSON, UTF-8; /api/durum ve /api/eslestir disinda 'X-Anahtar' basligi gerekir):
  GET  /api/durum                -> {uygulama, surum, eslesmis}
  POST /api/eslestir {kod, ad}   -> {anahtar}
  GET  /api/sayi                 -> {ad, baslik, sayfalar, makaleler: [{id, sayfa, baslik, ses}]}
  POST /api/bul?x=0.5&y=0.5      govde JPEG kare -> {bulundu, sayfa, x, y, makale | null}
  GET  /api/makale/<id>          -> {id, sayfa, baslik, metin, ses}
  GET  /api/ses/<id>             -> audio/mpeg (Range destekli)
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DEFAULT_PORT = 8642
MAX_FRAME = 6 * 1024 * 1024
MAX_JSON = 16 * 1024
PAIR_TRIES = 10            # yanlis kod denemesi siniri (kod yenilenene kadar)
CHUNK = 256 * 1024


def lan_addresses():
    """Bu bilgisayarin yerel ag IPv4 adresleri (telefonda yazilacak adres)."""
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in found and ipaddress.ip_address(address).is_private and not address.startswith('127.'):
                found.append(address)
    except OSError:
        pass
    try:   # varsayilan yolun adresi (paket gonderilmez)
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(('10.255.255.255', 1))
            address = probe.getsockname()[0]
        finally:
            probe.close()
        if address not in found and ipaddress.ip_address(address).is_private and not address.startswith('127.'):
            found.insert(0, address)
    except OSError:
        pass
    return found


def allowed_client(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local


class Phones:
    """Eslenen telefonlar: {anahtar: {ad, eslesme, son}} JSON dosyasinda."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding='utf-8')
        temp.replace(self.path)

    def add(self, name):
        token = secrets.token_urlsafe(24)
        with self._lock:
            value = self._read()
            value[token] = {'ad': str(name or 'Telefon')[:60], 'eslesme': time.strftime('%Y-%m-%d %H:%M')}
            self._write(value)
        return token

    def check(self, token):
        if not token:
            return False
        with self._lock:
            value = self._read()
            for known in value:
                if hmac.compare_digest(known, token):
                    return True
        return False

    def listing(self):
        with self._lock:
            return [{'id': token[:8], **info} for token, info in self._read().items()]

    def remove(self, short_id):
        with self._lock:
            value = self._read()
            kept = {token: info for token, info in value.items() if token[:8] != short_id}
            self._write(kept)
            return len(kept) != len(value)


class GazeteServer:
    """backend: current() -> (ad, sayi verisi) | (None, None); locate(ad, kare baytlari, (x, y)) ->
    {page, x, y} | None; audio(ad, makale) -> Path | None; article_at(veri, sayfa, x, y) -> makale | None;
    text(makale) -> okunacak metin."""

    def __init__(self, backend, phones, version='', log=print):
        self.backend = backend
        self.phones = phones
        self.version = version
        self.log = log
        self.code = ''
        self._tries = 0
        self._server = None
        self._thread = None

    @property
    def running(self):
        return self._server is not None

    def start(self, port=DEFAULT_PORT, host='0.0.0.0'):
        if self._server is not None:
            return self.info()
        self.code = f'{secrets.randbelow(1_000_000):06d}'
        self._tries = 0
        handler = type('GazeteHandler', (_Handler,), {'owner': self})
        server = ThreadingHTTPServer((host, int(port)), handler)
        server.daemon_threads = True
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name='aktar-gazete-server', daemon=True)
        self._thread.start()
        return self.info()

    def stop(self):
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        self.code = ''

    def info(self):
        port = self._server.server_address[1] if self._server else None
        return {'running': self._server is not None, 'port': port, 'code': self.code,
                'addresses': [f'http://{address}:{port}' for address in lan_addresses()] if port else []}

    def pair(self, code, name):
        if not self.code or self._tries >= PAIR_TRIES:
            return None
        if not hmac.compare_digest(str(code or '').strip(), self.code):
            self._tries += 1
            return None
        token = self.phones.add(name)
        self.log(f'Gazete: telefon eşlendi ({str(name or "Telefon")[:60]}).')
        return token


def _summary(article):
    return {'id': article['id'], 'sayfa': article['page'], 'baslik': article.get('title', ''),
            'ses': bool(article.get('audio'))}


class _Handler(BaseHTTPRequestHandler):
    owner: GazeteServer = None
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass

    # ---------------------------------------------------------------- yanitlar
    def _json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._json({'hata': message}, status)

    def _body(self, limit):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = -1
        if length < 0 or length > limit:
            return None
        return self.rfile.read(length)

    def _gate(self, auth=True):
        if not allowed_client(self.client_address[0]):
            self._error(403, 'Yalnızca yerel ağdan erişilebilir.')
            return False
        if auth and not self.owner.phones.check(self.headers.get('X-Anahtar', '')):
            self._error(401, 'Telefon eşlenmemiş.')
            return False
        return True

    def _issue(self):
        name, data = self.owner.backend.current()
        if not name:
            self._error(404, 'Henüz hazırlanmış gazete yok.')
            return None, None
        return name, data

    def _find(self, data, article_id):
        return next((a for a in data.get('articles', []) if a['id'] == article_id), None)

    # ---------------------------------------------------------------- uclar
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/durum':
            if self._gate(auth=False):
                self._json({'uygulama': 'Aktar', 'surum': self.owner.version,
                            'eslesmis': self.owner.phones.check(self.headers.get('X-Anahtar', ''))})
            return
        if not self._gate():
            return
        name, data = self._issue()
        if not name:
            return
        if path == '/api/sayi':
            articles = sorted(data.get('articles', []), key=lambda a: (a['page'], a['head'][1] if a.get('head') else 0))
            self._json({'ad': name, 'baslik': data.get('title', name), 'sayfalar': len(data.get('pages', [])),
                        'makaleler': [_summary(a) for a in articles]})
        elif path.startswith('/api/makale/'):
            article = self._find(data, path.rsplit('/', 1)[1])
            if article is None:
                self._error(404, 'Makale bulunamadı.')
            else:
                self._json(dict(_summary(article), metin=self.owner.backend.text(article)))
        elif path.startswith('/api/ses/'):
            article = self._find(data, path.rsplit('/', 1)[1])
            audio = self.owner.backend.audio(name, article) if article else None
            if audio is None:
                self._error(404, 'Bu makalenin sesi hazır değil.')
            else:
                self._file(audio)
        else:
            self._error(404, 'Bilinmeyen adres.')

    def do_POST(self):
        parts = urlsplit(self.path)
        if parts.path == '/api/eslestir':
            if not self._gate(auth=False):
                return
            raw = self._body(MAX_JSON)
            try:
                value = json.loads(raw or b'{}')
            except ValueError:
                value = None
            if not isinstance(value, dict):
                self._error(400, 'Geçersiz istek.')
                return
            token = self.owner.pair(value.get('kod'), value.get('ad'))
            if token is None:
                self._error(403, 'Kod yanlış; Aktar\'ın Gazete sayfasındaki kodu girin.')
            else:
                self._json({'anahtar': token})
            return
        if not self._gate():
            return
        if parts.path != '/api/bul':
            self._error(404, 'Bilinmeyen adres.')
            return
        frame = self._body(MAX_FRAME)
        if not frame:
            self._error(400, 'Kare gönderilmedi ya da çok büyük.')
            return
        name, data = self._issue()
        if not name:
            return
        query = parse_qs(parts.query)
        try:
            point = (min(1.0, max(0.0, float(query.get('x', ['0.5'])[0]))),
                     min(1.0, max(0.0, float(query.get('y', ['0.5'])[0]))))
        except ValueError:
            point = (0.5, 0.5)
        try:
            spot = self.owner.backend.locate(name, frame, point)
        except ValueError as error:
            self._error(400, str(error))
            return
        except Exception as error:   # OpenCV yok ya da beklenmeyen hata: sunucu ayakta kalsin
            self.owner.log(f'HATA: Gazete eşleştirme: {error}')
            self._error(500, 'Eşleştirme yapılamadı.')
            return
        if spot is None:
            self._json({'bulundu': False})
            return
        article = self.owner.backend.article_at(data, spot['page'], spot['x'], spot['y'])
        self._json({'bulundu': True, 'sayfa': spot['page'], 'x': round(spot['x']), 'y': round(spot['y']),
                    'makale': _summary(article) if article else None})

    def _file(self, path):
        size = path.stat().st_size
        start, end = 0, size - 1
        header = self.headers.get('Range', '')
        partial = header.startswith('bytes=')
        if partial:
            try:
                first, _sep, last = header[6:].split(',')[0].partition('-')
                if first:
                    start = int(first)
                    end = int(last) if last else size - 1
                else:
                    start = max(0, size - int(last))
                end = min(end, size - 1)
                if start > end:
                    raise ValueError
            except ValueError:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', 'audio/mpeg')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with open(path, 'rb') as handle:
            handle.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = handle.read(min(CHUNK, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)
