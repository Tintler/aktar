"""Telefon sesi (F229): telefondaki Sesli Haber uygulamasi icin yerel ag seslendirme sunucusu.

Telefon haberi kendisi indirir, okunacak cumleyi buraya gonderir ve Aktar'in sesiyle (varsayilan EMA Lightning)
okunmus WAV'i alir; Aktar'a ulasamazsa telefonun kendi sesine duser. Sunucu yalnizca Aktar acikken calisir
(Ayarlar > Baglantilar'dan acilir ya da Aktar acilinca kendiliginden), pencere kapaninca durur. Yalnizca yerel
ag (ozel adres) ve bu bilgisayardan gelen istekleri kabul eder; internete acilmaz. Telefon bir kez, Aktar'da
gosterilen alti haneli kodla eslenir ve bir anahtar alir; eslenen telefonlar APP_DIR/telefon/telefonlar.json'da
kalir. Kod her baslatmada yenilenir.

Uclar (JSON, UTF-8; /api/durum ve /api/eslestir disinda 'X-Anahtar' basligi gerekir):
  GET  /api/durum                -> {uygulama, surum, eslesmis}
  POST /api/eslestir {kod, ad}   -> {anahtar}
  POST /api/oku {metin, hiz}     -> audio/wav (tek cumle; en fazla TEXT_LIMIT karakter)
Hata yanitlari {hata}: 401 eslenmemis, 403 yerel ag disi ya da yanlis kod, 503 ses motoru mesgul/hazir degil.
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
from urllib.parse import urlsplit

DEFAULT_PORT = 8642
MAX_JSON = 16 * 1024
TEXT_LIMIT = 1000          # tek istekte okunacak en uzun metin (telefon cumle cumle gonderir)
PAIR_TRIES = 10            # yanlis kod denemesi siniri (kod yenilenene kadar)
SPEEDS = (0.5, 2.0)


class Busy(Exception):
    """Ses motoru baska bir is icin kullaniliyor ya da yuklenemedi: telefon kendi sesine duser (503)."""


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
        if ipaddress.ip_address(address).is_private and not address.startswith('127.'):
            if address in found:
                found.remove(address)
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


def clean_text(value):
    text = ' '.join(str(value or '').split())
    return text[:TEXT_LIMIT]


def clamp_speed(value):
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return 1.0
    if speed != speed:   # NaN
        return 1.0
    return min(SPEEDS[1], max(SPEEDS[0], speed))


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
            for known in self._read():
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


class PhoneServer:
    """speak(metin, hiz) -> WAV baytlari; motor mesgulse Busy. Istekler sirayla okunur (tek motor)."""

    def __init__(self, speak, phones, version='', log=print):
        self.speak = speak
        self.phones = phones
        self.version = version
        self.log = log
        self.code = ''
        self._tries = 0
        self._server = None
        self._thread = None
        self._speak_lock = threading.Lock()

    @property
    def running(self):
        return self._server is not None

    def start(self, port=DEFAULT_PORT, host='0.0.0.0'):
        if self._server is not None:
            return self.info()
        handler = type('PhoneHandler', (_Handler,), {'owner': self})
        server = ThreadingHTTPServer((host, int(port)), handler)
        server.daemon_threads = True
        self.code = f'{secrets.randbelow(1_000_000):06d}'
        self._tries = 0
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name='aktar-phone-server', daemon=True)
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
                'addresses': [f'{address}:{port}' for address in lan_addresses()] if port else []}

    def pair(self, code, name):
        if not self.code or self._tries >= PAIR_TRIES:
            return None
        if not hmac.compare_digest(str(code or '').strip(), self.code):
            self._tries += 1
            return None
        token = self.phones.add(name)
        self.log(f'Telefon sesi: telefon eşlendi ({str(name or "Telefon")[:60]}).')
        return token

    def say(self, text, speed):
        with self._speak_lock:
            return self.speak(text, speed)


class _Handler(BaseHTTPRequestHandler):
    owner: PhoneServer = None
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass

    def _send(self, status, body, kind):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value, status=200):
        self._send(status, json.dumps(value, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

    def _error(self, status, message):
        self._json({'hata': message}, status)

    def _body_json(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_JSON:
            return None
        try:
            value = json.loads(self.rfile.read(length) or b'{}')
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def _gate(self, auth=True):
        if not allowed_client(self.client_address[0]):
            self._error(403, 'Yalnızca yerel ağdan erişilebilir.')
            return False
        if auth and not self.owner.phones.check(self.headers.get('X-Anahtar', '')):
            self._error(401, 'Telefon eşlenmemiş.')
            return False
        return True

    def do_GET(self):
        if urlsplit(self.path).path != '/api/durum':
            if self._gate():
                self._error(404, 'Bilinmeyen adres.')
            return
        if self._gate(auth=False):
            self._json({'uygulama': 'Aktar', 'surum': self.owner.version,
                        'eslesmis': self.owner.phones.check(self.headers.get('X-Anahtar', ''))})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == '/api/eslestir':
            if not self._gate(auth=False):
                return
            value = self._body_json()
            if value is None:
                self._error(400, 'Geçersiz istek.')
                return
            token = self.owner.pair(value.get('kod'), value.get('ad'))
            if token is None:
                self._error(403, "Kod yanlış; Aktar'daki kodu girin.")
            else:
                self._json({'anahtar': token})
            return
        if not self._gate():
            return
        if path != '/api/oku':
            self._error(404, 'Bilinmeyen adres.')
            return
        value = self._body_json()
        text = clean_text((value or {}).get('metin'))
        if not text:
            self._error(400, 'Okunacak metin yok.')
            return
        try:
            audio = self.owner.say(text, clamp_speed(value.get('hiz', 1.0)))
        except Busy as error:
            self._error(503, str(error) or 'Ses motoru meşgul.')
            return
        except Exception as error:   # beklenmeyen motor hatasi: sunucu ayakta kalsin, telefon kendi sesine gecer
            self.owner.log(f'HATA: Telefon sesi: {error}')
            self._error(503, 'Ses üretilemedi.')
            return
        if not audio:
            self._error(503, 'Ses motoru ses üretmedi.')
            return
        try:
            self._send(200, audio, 'audio/wav')
        except (BrokenPipeError, ConnectionResetError):
            pass
