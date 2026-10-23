"""Drama 3'u OpenRouter uzerinden calistirma (F188): Drama 3 TR motorunun bulut kipi.

Drama 3 TR motoru (drama3_tr) ui.json tts.drama3_tr_backend == 'openrouter' iken modeli yerel klasorden degil
OpenRouter'daki fish-audio/drama-3'ten ister. Ses onayarlari (klon kaydi + metni) aynen kullanilir: kayit her
istekte input_references ile gider (OpenRouter'da klonlama durumsuzdur, ayrica yukleme yok). Bulutta calisan
model orijinal Fish Audio Drama 3'tur; yerel klasordeki 32 uzmanli Turkce konusmaci (kasparovabi) degildir.

API anahtari ui.json'a yazilmaz: isletim sistemi deposunda 'Aktar/openrouter-api-key' (secret_store); denemeler
icin AKTAR_OPENROUTER_API_KEY / OPENROUTER_API_KEY ortam degiskenleri onceliklidir. Saf stdlib HTTP istemcisi.
"""
from __future__ import annotations

import array
import base64
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

import drama3

API_URL = 'https://openrouter.ai/api/v1'
MODEL = 'fish-audio/drama-3'
PROVIDER = 'fish-audio'        # provider.options anahtari: yalnizca bu saglayiciya iletilir
SECRET_KEY = 'openrouter-api-key'
ENV_KEYS = ('AKTAR_OPENROUTER_API_KEY', 'OPENROUTER_API_KEY')
PCM_RATE = 44100               # response_format 'pcm': 16 bit, isaretli, little-endian, mono
REQUEST_TIMEOUT = 90         # 200 karakterlik parca ~3-5 sn; takilan istek yeniden denenir
CHECK_TIMEOUT = 15
RETRY_WAITS = (2, 5, 12)       # 429 (hiz siniri) ve 5xx icin bekleyip yeniden deneme (sn)
READ_CHUNK = 64 * 1024
MAX_AUDIO_BASE = 10.0          # max_seconds: 10 sn + metin / 5 karakter/sn (olagan okuma 12-17 karakter/sn)
MIN_CHARS_PER_SECOND = 5.0
SLOW_NOTE = 30                 # bundan uzun suren istek Konsol'a yazilir
# Fish arada bir sesi gercek zamandan cok yavas akitir (olcumde 68 karakter 62 sn; normali 1-2 sn): STALL_AFTER sn'den
# sonra gelen ses gecen surenin STALL_RATE katindan azsa istek kesilip yeniden gonderilir
STALL_AFTER = 15
STALL_RATE = 0.5
REFERENCE_BITRATE = '64k'      # klon kaydi her istekte gider: MP3 (20 sn ~160 KB) WAV'dan ~10 kat kucuk
TITLE = 'Aktar'


class CloudError(drama3.ServerError):
    """OpenRouter istegi basarisiz oldu (anahtar, bakiye, hiz siniri ya da saglayici hatasi)."""


# ---------------------------------------------------------------- API anahtari
_key_lock = threading.Lock()
_key_cache = {}


def api_key():
    """OpenRouter API anahtari ('' = yok)."""
    for name in ENV_KEYS:
        if os.environ.get(name):
            return os.environ[name].strip()
    with _key_lock:
        if 'value' not in _key_cache:
            try:
                import secret_store
                _key_cache['value'] = str(secret_store.get_secret(SECRET_KEY) or '').strip()
            except Exception:  # depo yok/erisilemiyor: anahtarsiz
                _key_cache['value'] = ''
        return _key_cache['value']


def set_api_key(value):
    """Anahtari isletim sistemi deposuna yazar; bos deger siler."""
    import secret_store
    value = str(value or '').strip()
    if value:
        secret_store.set_secret(SECRET_KEY, value)
    else:
        secret_store.delete_secret(SECRET_KEY)
    with _key_lock:
        _key_cache['value'] = value


def _headers(key):
    return {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
            'X-Title': TITLE, 'HTTP-Referer': 'https://github.com/Tintler/aktar'}


def _message(error):
    """HTTPError -> kullaniciya gosterilecek Turkce aciklama."""
    detail = drama3._detail(error)
    code = error.code
    if code == 401:
        return 'OpenRouter API anahtarı geçersiz ya da süresi dolmuş (Ayarlar → Ses → Drama 3 TR).'
    if code == 402:
        return 'OpenRouter bakiyesi ya da anahtarın harcama sınırı yetersiz: ' + detail
    if code == 403:
        return 'OpenRouter isteği reddetti (anahtarın bu modele izni yok ya da içerik denetimi): ' + detail
    if code == 413:
        return 'Klon kaydı OpenRouter için çok büyük: ' + detail
    if code == 429:
        return 'OpenRouter hız sınırına takıldı; biraz sonra yeniden deneyin.'
    return f'OpenRouter ses üretemedi (HTTP {code}): {detail}'


def _open(request, timeout):
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, OSError) as error:
        raise CloudError(f'OpenRouter\'a ulaşılamadı: {getattr(error, "reason", None) or error}') from error


def key_info(key=None, timeout=CHECK_TIMEOUT):
    """Anahtarin durumu (ucretsiz istek, GET /key): {'ok', 'message', 'limit', 'usage', 'remaining'}."""
    key = key if key is not None else api_key()
    if not key:
        return {'ok': False, 'message': 'OpenRouter API anahtarı kaydedilmedi.'}
    request = urllib.request.Request(API_URL + '/key', headers=_headers(key))
    try:
        with _open(request, timeout) as response:
            data = (json.loads(response.read().decode('utf-8')) or {}).get('data') or {}
    except urllib.error.HTTPError as error:
        return {'ok': False, 'message': _message(error)}
    except (CloudError, ValueError) as error:
        return {'ok': False, 'message': str(error)}
    usage, limit = data.get('usage'), data.get('limit')
    remaining = data.get('limit_remaining')
    parts = ['OpenRouter anahtarı çalışıyor']
    if isinstance(usage, (int, float)):
        parts.append(f'harcanan ${usage:.4f}')
    if isinstance(remaining, (int, float)):
        parts.append(f'kalan sınır ${remaining:.4f}')
    elif limit is None:
        parts.append('harcama sınırı yok')
    return {'ok': True, 'message': ' · '.join(parts), 'limit': limit, 'usage': usage, 'remaining': remaining}


# ---------------------------------------------------------------- ses uretimi
def reference_audio(wav):
    """Hazirlanmis klon kaydi (WAV bayt) -> istege konacak (bayt, bicim): MP3, ffmpeg kodlayamazsa WAV."""
    try:
        return drama3._ffmpeg(['-f', 'wav', '-i', 'pipe:0', '-ac', '1', '-c:a', 'libmp3lame', '-b:a',
                               REFERENCE_BITRATE, '-f', 'mp3', 'pipe:1'], wav), 'mp3'
    except (RuntimeError, OSError):
        return wav, 'wav'


def request_body(text, audio, audio_format, reference_text, settings=None):
    settings = settings or {}
    data = 'data:audio/{0};base64,{1}'.format('mpeg' if audio_format == 'mp3' else audio_format,
                                              base64.b64encode(audio).decode('ascii'))
    body = {'model': MODEL, 'input': text, 'response_format': 'pcm',
            'input_references': [{'type': 'input_audio', 'input_audio': {'data': data, 'format': audio_format}},
                                 {'type': 'text', 'text': reference_text}]}
    options = {key: settings[key] for key in ('temperature', 'top_p') if key in settings}
    if options:
        body['provider'] = {'options': {PROVIDER: options}}
    return body


def max_seconds(text):
    """Bir parcanin en fazla ses suresi: Drama 3 bazen metni bitirince susmaz, sessizlik uretmeyi surdurur."""
    return MAX_AUDIO_BASE + len(text) / MIN_CHARS_PER_SECOND


def _read(response, text, started, timeout, log, clock=time.monotonic):
    """Yaniti parca parca okur: toplam `timeout` ya da max_seconds(text)'ten uzun ses gelirse keser (CloudError).
    Ses akarak geldigi icin soketin zaman asimi bu durumda hic dolmuyordu (F188: Hazirla dakikalarca bekledi)."""
    limit = int(max_seconds(text) * PCM_RATE * 2)
    parts, total, noted = [], 0, started
    while True:
        chunk = response.read(READ_CHUNK)
        if not chunk:
            return b''.join(parts)
        parts.append(chunk)
        total += len(chunk)
        now = clock()
        if total > limit:
            raise CloudError(f'model {max_seconds(text):.0f} sn\'den uzun ses üretti (metin {len(text)} karakter)')
        if now - started > timeout:
            raise CloudError(f'yanıt {timeout} sn\'de bitmedi ({total / (PCM_RATE * 2):.0f} sn ses geldi)')
        if now - started > STALL_AFTER and total / (PCM_RATE * 2) < (now - started) * STALL_RATE:
            raise CloudError(f'ses çok yavaş geliyor ({now - started:.0f} sn\'de {total / (PCM_RATE * 2):.1f} sn ses)')
        if now - noted > SLOW_NOTE:
            noted = now
            log(f'OpenRouter: {now - started:.0f} sn\'dir sürüyor, {total / (PCM_RATE * 2):.0f} sn ses geldi')


def speech(text, reference, settings=None, key=None, timeout=REQUEST_TIMEOUT, waits=RETRY_WAITS, sleep=time.sleep,
           log=None):
    """Bir parcayi WAV bayt olarak uretir. reference: {'audio', 'format', 'text'}. 429, 5xx ve zaman asiminda
    `waits` surelerince bekleyip yeniden dener; basarisiz uretim OpenRouter'da ucretlendirilmez. `log`: Konsol."""
    log = log or (lambda _message: None)
    key = key if key is not None else api_key()
    if not key:
        raise CloudError('OpenRouter API anahtarı kaydedilmedi (Ayarlar → Ses → Drama 3 TR).')
    body = json.dumps(request_body(text, reference['audio'], reference['format'], reference['text'], settings),
                      ensure_ascii=False).encode('utf-8')
    for attempt in range(len(waits) + 1):
        request = urllib.request.Request(API_URL + '/audio/speech', data=body, method='POST', headers=_headers(key))
        started = time.monotonic()
        try:
            with _open(request, timeout) as response:
                kind = response.headers.get('Content-Type', '')
                raw = _read(response, text, started, timeout, log)
            log(f'OpenRouter: {len(text)} karakter, {time.monotonic() - started:.1f} sn'
                + (f' ({attempt + 1}. deneme)' if attempt else ''))
            break
        except urllib.error.HTTPError as error:
            if (error.code == 429 or error.code >= 500) and attempt < len(waits):
                log(f'OpenRouter HTTP {error.code}: {drama3._detail(error)} — {waits[attempt]} sn sonra yeniden denenecek')
                error.close()
                sleep(waits[attempt])
                continue
            message = _message(error)
            log('OpenRouter hatası: ' + message)
            raise CloudError(message) from error
        except (CloudError, TimeoutError) as error:     # baglanti koptu, yanit gelmedi ya da _read kesti
            if attempt < len(waits):
                log(f'OpenRouter isteği yarım kaldı ({time.monotonic() - started:.0f} sn): {error} — yeniden denenecek')
                sleep(waits[attempt])
                continue
            raise CloudError(f'OpenRouter {len(waits) + 1} denemede ses üretemedi: {error}') from error
    if 'json' in kind:
        try:
            detail = (json.loads(raw.decode('utf-8')).get('error') or {}).get('message')
        except (ValueError, AttributeError):
            detail = None
        raise CloudError('OpenRouter ses yerine hata döndürdü: ' + str(detail or raw[:200]))
    if raw[:4] == b'RIFF':
        return raw
    samples = array.array('h', raw[:len(raw) // 2 * 2])
    if sys.byteorder == 'big':
        samples.byteswap()
    return drama3.wav_bytes(samples, PCM_RATE)
