"""Backlog sitesi (F94): kisisel oyun/anime/manga/film/kitap takip sitesinden kayit arama.

Site Cloudflare'de calisir; okuma uclari herkese aciktir, anahtar gerekmez:
  GET <backlog_url>/api?view=titles          -> bolum basina benzersiz basliklar
  GET <backlog_url>/api?view=lookup&q=<ad>   -> eslesen kayitlarin kisa alanlari

Genel sohbette her mesajda baslik listesi (onbellekten) soruyla yerelde eslestirilir;
gecen basliklar icin lookup yapilir ve sonuc "BACKLOG RECORDS" notu olarak baglama eklenir.
Model tool calling'e gerek kalmaz; eslesme yoksa siteye istek gitmez (liste onbellekteyse).
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 8.0
TITLES_TTL = 600.0        # baslik listesi bu kadar saniye onbellekte kalir
FAIL_TTL = 60.0           # hata sonrasi bu kadar saniye tekrar denenmez (sohbet yavaslamasin)
MIN_TITLE_CHARS = 4       # bundan kisa basliklar ("Up", "Her") siradan kelimelerle karisir
MAX_TITLES = 4            # bir soruda en fazla bu kadar baslik aranir
LOOKUP_LIMIT = 8
SECTION_LABELS = {'games': 'game', 'anime': 'anime', 'manga': 'manga', 'screen': 'film/TV', 'books': 'book'}
USER_AGENT = 'Aktar (backlog lookup)'

_LOCK = threading.Lock()
_TITLES = {'url': '', 'time': 0.0, 'items': [], 'error': ''}


def base_url(value):
    """Ayardaki adresi kok adrese cevirir; bos ya da gecersizse ''."""
    text = str(value or '').strip().rstrip('/')
    if text.endswith('/api'):
        text = text[:-4]
    parts = urllib.parse.urlsplit(text)
    if not parts.netloc:
        return ''
    local = parts.hostname in ('127.0.0.1', 'localhost')
    if parts.scheme != 'https' and not (parts.scheme == 'http' and local):
        return ''
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))


def valid_url(value):
    return not str(value or '').strip() or bool(base_url(value))


def fold(text):
    """Sitedeki lookupFold ile ayni: aksan ve noktalama atilir, kucuk harf, tek bosluk."""
    text = unicodedata.normalize('NFKD', str(text or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = text.replace('ı', 'i').lower()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def _get(url, params):
    request = urllib.request.Request(url + '/api?' + urllib.parse.urlencode(params),
                                     headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        try:
            data = json.loads(error.read().decode('utf-8'))
        except (ValueError, OSError):
            data = {}
        raise RuntimeError(f'Backlog HTTP {error.code}: {data.get("error") or error.reason}') from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise RuntimeError('Backlog sitesine ulaşılamadı: ' + str(getattr(error, 'reason', error))) from error
    if not isinstance(data, dict) or not data.get('ok'):
        raise RuntimeError('Backlog yanıtı geçersiz: ' + str(data.get('error', '') if isinstance(data, dict) else ''))
    return data


def titles(url, force=False, now=None):
    """[(katlanmis baslik, baslik)] - uzun basliklar once. Onbellekli; hata RuntimeError."""
    now = time.monotonic() if now is None else now
    with _LOCK:
        fresh = _TITLES['url'] == url and not force
        if fresh and _TITLES['items'] and now - _TITLES['time'] < TITLES_TTL:
            return _TITLES['items']
        if fresh and _TITLES['error'] and now - _TITLES['time'] < FAIL_TTL:
            raise RuntimeError(_TITLES['error'])
    try:
        data = _get(url, {'view': 'titles'})
    except RuntimeError as error:
        with _LOCK:
            _TITLES.update(url=url, time=now, items=[], error=str(error))
        raise
    items = {}
    for values in (data.get('sections') or {}).values():
        for title in values or []:
            key = fold(title)
            if len(key) >= MIN_TITLE_CHARS and not key.replace(' ', '').isdigit():
                items.setdefault(key, str(title))
    ordered = sorted(items.items(), key=lambda item: -len(item[0]))
    with _LOCK:
        _TITLES.update(url=url, time=now, items=ordered, error='')
    return ordered


def forget():
    with _LOCK:
        _TITLES.update(url='', time=0.0, items=[], error='')


def find_titles(text, known, limit=MAX_TITLES):
    """Metinde kelime sinirlariyla gecen basliklar; uzun eslesmenin icindeki kisa olanlar atlanir."""
    haystack = ' ' + fold(text) + ' '
    found = []
    for key, title in known:
        if ' ' + key + ' ' not in haystack or any(key in other for other, _ in found):
            continue
        found.append((key, title))
        if len(found) >= limit:
            break
    return [title for _, title in found]


def lookup(url, title, limit=LOOKUP_LIMIT):
    return _get(url, {'view': 'lookup', 'q': title, 'limit': limit}).get('results') or []


def _hours(minutes):
    try:
        value = float(minutes)
    except (TypeError, ValueError):
        return str(minutes)
    return f'{value / 60:.1f} h' if value else '0 h'


def format_record(record):
    section = record.get('section', '')
    fields = []
    for key, value in record.items():
        if key in ('section', 'id'):
            continue
        if key == 'Playtime':
            value = _hours(value)
        elif re.fullmatch(r'\d{4}-\d{2}-\d{2}T[\d:.]+Z', str(value)):
            value = str(value)[:10]
        fields.append(f'{key}: {value}')
    return f'- [{SECTION_LABELS.get(section, section)}] ' + ' | '.join(fields)


def notes(question, cfg, log=print):
    """Soruda gecen basliklarin kayitlari (model icin not metni) ya da ''."""
    url = base_url(cfg.get('backlog_url', ''))
    if not url:
        return ''
    try:
        found = find_titles(question, titles(url))
        if not found:
            return ''
        records, seen = [], set()
        for title in found:
            for record in lookup(url, title):
                key = record.get('id') or json.dumps(record, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    records.append(record)
    except RuntimeError as error:
        log('Backlog araması yapılamadı: ' + str(error))
        return ''
    if not records:
        return ''
    log(f'Backlog: {", ".join(found)} için {len(records)} kayıt.')
    return ('BACKLOG RECORDS (automatic lookup in the user\'s own game/anime/manga/film/book tracker for titles '
            'mentioned in the conversation; one line per copy/entry; may be irrelevant):\n'
            + '\n'.join(format_record(record) for record in records))


def check(value):
    """Ayarlar sayfasi icin: {'ok', 'message'}."""
    url = base_url(value)
    if not url:
        return {'ok': False, 'message': 'Adres https:// ile başlamalı (örn. https://site.pages.dev).'}
    try:
        count = len(titles(url, force=True))
    except RuntimeError as error:
        return {'ok': False, 'message': str(error)}
    return {'ok': True, 'message': f'Bağlandı · {count} başlık'}
