"""Model sunucusu (F152): LM Studio ya da OpenAI uyumlu herhangi bir sunucu.

provider (config.json):
  'lmstudio'  LM Studio. Standart /v1 uclarina ek olarak LM Studio REST API'si (/api/v1) kullanilir:
              modelleri kalici yukleme/bosaltma, yuklu modelin gercek context uzunlugu ve kitap
              cevirisinde /api/v1/chat.
  'openai'    OpenAI uyumlu /v1 sunucusu: Ollama, llama.cpp, vLLM, OpenAI, OpenRouter ... Yalnizca
              standart alanlar gonderilir; kitap cevirisi /chat/completions ile yapilir.

Adres kurali: http yalnizca bu bilgisayar ve yerel ag (ozel IP, .local, tek parcali ad) icindir;
internetteki sunucular https olmali (API anahtari ve metinler sifresiz gitmesin).

API anahtari config.json'a yazilmaz: isletim sistemi deposunda 'Aktar/llm-api-key' (secret_store)
olarak saklanir. LM_STUDIO_API_KEY ya da AKTAR_API_KEY ortam degiskeni verilmisse o kullanilir.
"""
from __future__ import annotations

import ipaddress
import json
import os
import threading
from urllib.parse import urlparse

PROVIDERS = ('lmstudio', 'openai')
SECRET_KEY = 'llm-api-key'

# Ayarlardaki hazir sunucu secenekleri (adres + tur doldurulur, kullanici degistirebilir).
PRESETS = (
    {'id': 'lmstudio', 'label': 'LM Studio', 'base_url': 'http://127.0.0.1:1234/v1', 'provider': 'lmstudio'},
    {'id': 'ollama', 'label': 'Ollama', 'base_url': 'http://127.0.0.1:11434/v1', 'provider': 'openai'},
    {'id': 'llamacpp', 'label': 'llama.cpp (llama-server)', 'base_url': 'http://127.0.0.1:8080/v1', 'provider': 'openai'},
    {'id': 'vllm', 'label': 'vLLM', 'base_url': 'http://127.0.0.1:8000/v1', 'provider': 'openai'},
    {'id': 'openai', 'label': 'OpenAI', 'base_url': 'https://api.openai.com/v1', 'provider': 'openai'},
    {'id': 'openrouter', 'label': 'OpenRouter', 'base_url': 'https://openrouter.ai/api/v1', 'provider': 'openai'},
)

_LAN_SUFFIXES = ('.local', '.lan', '.home.arpa', '.internal', '.localdomain')
_CGNAT = ipaddress.ip_network('100.64.0.0/10')  # Tailscale vb.


def provider(cfg):
    return str((cfg or {}).get('provider') or 'lmstudio').strip().lower()


def is_lmstudio(cfg):
    return provider(cfg) == 'lmstudio'


def scope(url):
    """'local' (bu bilgisayar), 'lan' (yerel ag) ya da 'internet'."""
    host = (urlparse(str(url or '').strip()).hostname or '').lower().rstrip('.')
    if not host:
        return 'internet'
    if host == 'localhost' or host.endswith('.localhost'):
        return 'local'
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return 'lan' if '.' not in host or host.endswith(_LAN_SUFFIXES) else 'internet'
    if address.is_loopback:
        return 'local'
    if address.is_private or address.is_link_local or (address.version == 4 and address in _CGNAT):
        return 'lan'
    return 'internet'


def validate(cfg):
    url = str(cfg.get('base_url') or '').strip()
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('base_url bir http(s) adresi olmalı (ör. http://127.0.0.1:1234/v1).')
    if parsed.username or parsed.password:
        raise ValueError('base_url içinde kullanıcı adı/şifre olmamalı; API anahtarını ayrıca girin.')
    if parsed.scheme == 'http' and scope(url) == 'internet':
        raise ValueError('İnternetteki sunucular https olmalı; http yalnızca bu bilgisayar ve yerel ağ içindir.')
    if provider(cfg) not in PROVIDERS:
        raise ValueError('provider lmstudio veya openai olmalı.')


def sends_extensions(cfg):
    """Standart disi alanlar (chat_template_kwargs, reasoning_effort='none') gonderilebilir mi?
    LM Studio ve yereldeki sunucular (llama.cpp, vLLM, Ollama) bunlari tanir ya da yok sayar;
    internetteki API'ler (OpenAI vb.) bilinmeyen alan icin istegi reddeder."""
    return is_lmstudio(cfg) or scope(cfg.get('base_url')) != 'internet'


_key_lock = threading.Lock()
_key_cache = {}


def api_key():
    """Sunucu API anahtari ('' = yok)."""
    for name in ('AKTAR_API_KEY', 'LM_STUDIO_API_KEY'):
        if os.environ.get(name):
            return os.environ[name]
    with _key_lock:
        if 'value' not in _key_cache:
            try:
                import secret_store
                _key_cache['value'] = str(secret_store.get_secret(SECRET_KEY) or '').strip()
            except Exception:  # depo yok/erisilemiyor: anahtarsiz devam
                _key_cache['value'] = ''
        return _key_cache['value']


def set_api_key(value):
    """Anahtari isletim sistemi deposuna yazar; bos deger anahtari siler."""
    import secret_store
    value = str(value or '').strip()
    if value:
        secret_store.set_secret(SECRET_KEY, value)
    else:
        secret_store.delete_secret(SECRET_KEY)
    with _key_lock:
        _key_cache['value'] = value


def headers():
    result = {'Content-Type': 'application/json'}
    token = api_key()
    if token:
        result['Authorization'] = 'Bearer ' + token
    return result


def http_error(error):
    """HTTPError'dan kisa, anlasilir ileti (sunucunun hata aciklamasi dahil)."""
    detail = ''
    try:
        body = error.read().decode('utf-8', errors='replace')[:2000]
        try:
            value = json.loads(body)
            message = value.get('error', value)
            detail = str(message.get('message') if isinstance(message, dict) else message)
        except (ValueError, AttributeError):
            detail = body
    except Exception:
        pass
    hint = {401: ' (API anahtarı eksik ya da hatalı)', 403: ' (erişim izni yok)',
            404: ' (adres ya da model bulunamadı)', 429: ' (istek sınırı aşıldı; biraz bekleyin)'}.get(error.code, '')
    detail = ' '.join(detail.split())[:400]
    return f'HTTP {error.code}: model sunucusu isteği reddetti{hint}' + (f': {detail}' if detail else '.')
