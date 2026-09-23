"""Seri (TV dizisi/anime) bazli glossary + continuity deposu.

Seri iceriklerde bolumler arasi tutarlilik icin glossary VE continuity kararlari
birlikte seri duzeyinde saklanir (hitap bicimleri sen/siz, isim yazimi, tekrar
eden kaliplar). Depo: uygulama dizini altindaki `series/<slug>.json`.

Yazma FileLock ile korunur; korumali klasorde (C:\\Program Files gibi) yazma
basarisiz olursa anlamli RuntimeError uretilir, sessizce yutulmaz.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from app_core import APP_DIR, FileLock, _dedupe_glossary, read, save_json

_TR_ASCII = str.maketrans({
    'ı': 'i', 'İ': 'i', 'ş': 's', 'Ş': 's', 'ğ': 'g', 'Ğ': 'g',
    'ç': 'c', 'Ç': 'c', 'ö': 'o', 'Ö': 'o', 'ü': 'u', 'Ü': 'u',
})

_GENERIC_FOLDER_HINTS = {
    'anime', 'tv', 'video', 'videos', 'downloads', 'download', 'qbit',
    'qbittorrent', 'media', 'series', 'dizi', 'season', 'sezon',
}


def series_dir():
    """Seri deposu klasoru. Test/gelistirme icin AKTAR_SERIES_DIR ile gecersiz kilinabilir."""
    override = os.environ.get('AKTAR_SERIES_DIR')
    return Path(override) if override else APP_DIR / 'series'


def slugify(title):
    """Seri basligini ASCII dosya adina cevirir: 'Game of Thrones' -> 'game-of-thrones'."""
    text = str(title).translate(_TR_ASCII)
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r'[^A-Za-z0-9]+', '-', text).strip('-').lower()
    if not text:
        raise ValueError('Seri başlığı geçerli bir dosya adı üretmedi.')
    return text


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _path(slug):
    return series_dir() / (slug + '.json')


def _lock_path(slug):
    return series_dir() / (slug + '.lock')


def list_series():
    """{slug: data} sozlugu; bozuk dosyalar atlanir."""
    result = {}
    directory = series_dir()
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob('*.json')):
        try:
            value = json.loads(read(path))
        except (ValueError, OSError):
            continue
        if isinstance(value, dict) and str(value.get('title', '')).strip():
            result[path.stem] = value
    return result


def load_series(slug):
    path = _path(slug)
    if not path.exists():
        raise ValueError('Seri bulunamadı: ' + str(slug))
    value = json.loads(read(path))
    if not isinstance(value, dict):
        raise ValueError('Seri dosyası geçersiz: ' + str(slug))
    return value


def save_series(data, slug=None):
    slug = slug or slugify(data.get('title', ''))
    directory = series_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RuntimeError(
            'Seri klasörü oluşturulamadı (yazma izni yok): ' + str(directory)
        ) from error
    with FileLock(_lock_path(slug)):
        try:
            save_json(_path(slug), data)
        except OSError as error:
            raise RuntimeError(
                'Seri dosyası yazılamadı (yazma izni yok): ' + str(_path(slug))
            ) from error
    return slug


def create_series(title, folder_hints=None):
    title = str(title).strip()
    if not title:
        raise ValueError('Seri başlığı boş olamaz.')
    slug = slugify(title)
    if _path(slug).exists():
        raise ValueError('Bu seri zaten var: ' + title)
    hints = [str(item).strip() for item in (folder_hints or [])
             if valid_folder_hint(item)]
    data = {
        'title': title,
        'created': _now(),
        'folder_hints': hints or [title],
        'glossary': [],
        'decisions': [],
        'episodes': [],
    }
    save_series(data, slug=slug)
    return data


def valid_folder_hint(value):
    """Genel indirme/sezon klasorlerini seri eslestirme ipucu olarak reddeder."""
    text = str(value).strip()
    folded = text.casefold()
    if not text or folded in _GENERIC_FOLDER_HINTS:
        return False
    if re.fullmatch(r'(?:s|season|sezon)[ ._-]*\d{1,2}', folded):
        return False
    return len(text) >= 3


def suggest_series(video_path):
    """Video klasor adi veya dosya adi bir seriyle eslesiyorsa slug doner, yoksa None.

    Yalnizca ONERIDIR; kullanici her zaman elle secebilir. Alt klasorler
    (S01 gibi) ve degisebilen klasor adlari nedeniyle klasor adina guvenilmez.
    """
    matches = matching_series(video_path)
    return matches[0] if len(matches) == 1 else None


def matching_series(video_path):
    """Video icin tum olasi seri slug'larini dondurur; belirsizlik gizlenmez."""
    video = Path(video_path)
    candidates = {video.parent.name.strip().casefold(), video.stem.strip().casefold()}
    matches = []
    for slug, data in list_series().items():
        hints = [str(item).strip().casefold() for item in data.get('folder_hints', [])
                 if valid_folder_hint(item)]
        hints.append(str(data.get('title', '')).strip().casefold())
        if any(hint and hint in candidates for hint in hints):
            matches.append(slug)
    return matches


def guess_series_title(video_path):
    """Fansub/kalite/bolum eklerini dosya adindan ayiklayarak baslik onerir."""
    name = re.sub(r'\[[^\]]*\]', ' ', Path(video_path).stem)
    name = re.sub(r'\(\s*(?:2160p|1080p|720p|480p|WEB[- .]?DL|BluRay|x26[45]|HEVC)\s*\)',
                  ' ', name, flags=re.I)
    name = re.sub(r'\b(?:2160p|1080p|720p|480p|WEB[- .]?DL|BluRay|x26[45]|HEVC)\b',
                  ' ', name, flags=re.I)
    name = re.sub(r'\b(?:S\d{1,2}E\d{1,3}|\d{1,2}x\d{1,3})\b.*$', ' ', name, flags=re.I)
    name = re.sub(r'\s+-\s+(?:\d{1,3})(?:v\d+)?\s*$', ' ', name, flags=re.I)
    return ' '.join(name.split()).strip(' -_.')


def add_episode(slug, filename):
    data = load_series(slug)
    filename = str(filename).strip()
    if not filename:
        raise ValueError('Bölüm dosya adı boş olamaz.')
    episodes = [item for item in data.get('episodes', []) if isinstance(item, dict)]
    if not any(str(item.get('file', '')) == filename for item in episodes):
        episodes.append({'file': filename, 'date': _now()})
    data['episodes'] = episodes
    save_series(data, slug=slug)
    return data


def series_glossary(slug):
    if not slug:
        return []
    return _dedupe_glossary(load_series(slug).get('glossary', []))


def series_decisions(slug):
    if not slug:
        return []
    return [str(item).strip() for item in load_series(slug).get('decisions', []) if str(item).strip()]


def add_knowledge(slug, terms=None, decisions=None, episode=''):
    """Onaylanmis terim/continuity kararlarini meta veriyi koruyarak seriye ekler.

    Mevcut kullanici karari her zaman kazanir. Yeni bir onerinin ayni source icin
    farkli hedefi varsa sessizce ezilmez; arayuzun catismayi gostermesi gerekir.
    """
    data = load_series(slug)
    glossary = [item for item in data.get('glossary', []) if isinstance(item, dict)]
    known = {str(item.get('source', '')).strip().casefold() for item in glossary}
    for item in terms or []:
        source = str(item.get('source', '')).strip()
        target = str(item.get('target', '')).strip()
        key = source.casefold()
        if not source or not target or key in known:
            continue
        known.add(key)
        entry = {'source': source, 'target': target}
        for field in ('type', 'origin', 'first_seen', 'locked'):
            if field in item:
                entry[field] = item[field]
        if episode and 'first_seen' not in entry:
            entry['first_seen'] = str(episode)
        glossary.append(entry)
    data['glossary'] = glossary
    current = [str(item).strip() for item in data.get('decisions', []) if str(item).strip()]
    decision_keys = {item.casefold() for item in current}
    for item in decisions or []:
        value = str(item.get('value', item) if isinstance(item, dict) else item).strip()
        if value and value.casefold() not in decision_keys:
            decision_keys.add(value.casefold()); current.append(value)
    data['decisions'] = current
    save_series(data, slug=slug)
    return data
