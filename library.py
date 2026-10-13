"""Kutuphane: adlandirilmis koleksiyonlar ve kaynak klasor taramasi.

Qt'den bagimsizdir; library_panel.py ve testler ayni mantigi kullanir.
Koleksiyon = kaynak klasorler (alt klasorler dahil) + tek tek eklenen dosyalar
- cikarilan dosyalar. Depo: uygulama dizini altindaki `library/<slug>.json`.

Klasorler koleksiyon her acildiginda yeniden taranir (canli izleme yok): yeni
bulunan dosyalar 'yeni' isaretlenir, diskten kaybolanlar listeden dusmez,
'kayip' gorunur (harici disk takili degilse geri gelebilir); kullanici
koleksiyondan cikarana kadar kalir. Kaynak dosyalar SALT-OKUNUR: koleksiyonu
silmek yalnizca JSON kaydini siler.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import qa
import series
from app_core import APP_DIR, FileLock, read, save_json
from media import VIDEO_EXTENSIONS

VERSION = 1
# Ileride: 'pdf', 'text', 'image', 'table' (her tur kendi metin cikaricisiyla).
KINDS = {'video': VIDEO_EXTENSIONS}
SKIPPED_DIRS = {'$recycle.bin', 'system volume information', '__pycache__', 'node_modules'}


def library_dir():
    """Koleksiyon deposu. Test/gelistirme icin AKTAR_LIBRARY_DIR ile gecersiz kilinabilir."""
    override = os.environ.get('AKTAR_LIBRARY_DIR')
    return Path(override) if override else APP_DIR / 'library'


def kind_of(path):
    """Dosya turu ('video'...) ya da desteklenmiyorsa None."""
    suffix = Path(path).suffix.lower()
    return next((kind for kind, suffixes in KINDS.items() if suffix in suffixes), None)


def supported_suffixes():
    return tuple(suffix for suffixes in KINDS.values() for suffix in suffixes)


def _key(path):
    """Yol karsilastirma anahtari (Windows'ta buyuk/kucuk harf duyarsiz)."""
    return os.path.normcase(os.path.normpath(str(path)))


def _clean(path):
    return str(Path(os.path.abspath(str(path))))


def _now():
    return datetime.now().isoformat(timespec='seconds')


def natural_key(text):
    """'Ders 2' 'Ders 10'dan once gelsin: sayilar sayisal siralanir."""
    return [(0, int(part), '') if part.isdigit() else (1, 0, part)
            for part in re.split(r'(\d+)', str(text).casefold()) if part]


# --- depo ---------------------------------------------------------------------
def _path(slug):
    return library_dir() / (slug + '.json')


def _slug_for(title):
    try:
        base = series.slugify(title)
    except ValueError:
        base = 'koleksiyon'
    slug, number = base, 2
    while _path(slug).exists():
        slug, number = f'{base}-{number}', number + 1
    return slug


def list_collections():
    """{slug: data}, basliga gore sirali; bozuk dosyalar atlanir."""
    directory = library_dir()
    found = {}
    if directory.is_dir():
        for path in directory.glob('*.json'):
            try:
                value = json.loads(read(path))
            except (ValueError, OSError):
                continue
            if isinstance(value, dict) and str(value.get('title', '')).strip():
                found[path.stem] = value
    return dict(sorted(found.items(), key=lambda item: (natural_key(item[1]['title']),
                                                        natural_key(item[0]))))


def load_collection(slug):
    path = _path(slug)
    if not path.exists():
        raise ValueError('Koleksiyon bulunamadı: ' + str(slug))
    value = json.loads(read(path))
    if not isinstance(value, dict):
        raise ValueError('Koleksiyon dosyası geçersiz: ' + str(slug))
    for field in ('folders', 'files', 'excluded', 'known'):
        value.setdefault(field, [])
    return value


def save_collection(data, slug):
    directory = library_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RuntimeError('Kütüphane klasörü oluşturulamadı (yazma izni yok): '
                           + str(directory)) from error
    data['updated'] = _now()
    with FileLock(directory / (slug + '.lock')):
        try:
            save_json(_path(slug), data)
        except OSError as error:
            raise RuntimeError('Koleksiyon dosyası yazılamadı (yazma izni yok): '
                               + str(_path(slug))) from error
    return slug


def create_collection(title, folders=(), files=()):
    """Yeni koleksiyon kaydeder; (slug, data) dondurur. Basliklar tekrar edebilir."""
    title = ' '.join(str(title).split())
    if not title:
        raise ValueError('Koleksiyon adı boş olamaz.')
    data = {'version': VERSION, 'title': title, 'created': _now(), 'updated': _now(),
            'folders': [], 'files': [], 'excluded': [], 'known': [], 'scanned': False}
    for folder in folders:
        add_folder(data, folder)
    add_files(data, files)
    slug = _slug_for(title)
    save_collection(data, slug)
    return slug, data


def rename_collection(slug, title):
    title = ' '.join(str(title).split())
    if not title:
        raise ValueError('Koleksiyon adı boş olamaz.')
    data = load_collection(slug)
    data['title'] = title
    save_collection(data, slug)
    return data


def delete_collection(slug):
    """Yalnizca koleksiyon kaydini siler; kaynak dosyalara dokunulmaz."""
    for path in (_path(slug), library_dir() / (slug + '.lock')):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def default_title(paths):
    """Birakilan klasorun adi; dosyalar icin ilk dosyanin klasoru."""
    for path in paths:
        path = Path(path)
        name = path.name if path.is_dir() else path.parent.name
        if name.strip():
            return name
    return 'Koleksiyon'


# --- icerik -------------------------------------------------------------------
def _inside(path, folder):
    path, folder = _key(path), _key(folder)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def add_folder(data, folder):
    """Kaynak klasor ekler. Zaten kapsanan klasor eklenmez; kapsadiklari birlesir."""
    folder = _clean(folder)
    if any(_inside(folder, existing) for existing in data['folders']):
        return False
    data['folders'] = [item for item in data['folders'] if not _inside(item, folder)]
    data['folders'].append(folder)
    data['files'] = [item for item in data['files'] if not _inside(item, folder)]
    return True


def remove_folder(data, folder):
    key = _key(folder)
    before = len(data['folders'])
    data['folders'] = [item for item in data['folders'] if _key(item) != key]
    data['known'] = [item for item in data['known'] if not _inside(item, folder)]
    data['excluded'] = [item for item in data['excluded'] if not _inside(item, folder)]
    return len(data['folders']) != before


def add_files(data, paths):
    """Desteklenen dosyalari ekler (cikarilmislarsa geri alir). Eklenen sayisi."""
    added = 0
    for path in paths:
        if kind_of(path) is None:
            continue
        path = _clean(path)
        key = _key(path)
        if any(_key(item) == key for item in data['excluded']):
            data['excluded'] = [item for item in data['excluded'] if _key(item) != key]
            added += 1
            continue
        if (any(_inside(path, folder) for folder in data['folders'])
                or any(_key(item) == key for item in data['files'])):
            continue
        data['files'].append(path)
        added += 1
    return added


def exclude(data, paths):
    """Dosyalari koleksiyondan cikarir (diskte kalir; klasor taramasi da atlar)."""
    keys = {_key(path) for path in paths}
    data['files'] = [item for item in data['files'] if _key(item) not in keys]
    data['known'] = [item for item in data['known'] if _key(item) not in keys]
    for path in paths:
        path = _clean(path)
        if (any(_inside(path, folder) for folder in data['folders'])
                and _key(path) not in {_key(item) for item in data['excluded']}):
            data['excluded'].append(path)


def _walk(folder):
    """Klasordeki desteklenen dosyalar (alt klasorler dahil, gizli/sistem klasorleri haric)."""
    found = []
    for root, dirs, files in os.walk(folder, onerror=lambda _error: None):
        dirs[:] = [name for name in dirs
                   if not name.startswith('.') and name.casefold() not in SKIPPED_DIRS]
        found.extend(os.path.join(root, name) for name in files if kind_of(name))
    return found


def scan(data):
    """Koleksiyonu diskle karsilastirir. (entries, changed) dondurur.

    entry: {'path': Path, 'kind', 'root': kaynak klasor ya da None,
            'missing': bool, 'new': bool}. `changed` ise cagiran kaydetmelidir.
    """
    excluded = {_key(item) for item in data['excluded']}
    known = {_key(item) for item in data['known']}
    first = not data.get('scanned')
    entries = {}

    def add(path, root, missing=False):
        key = _key(path)
        if key in excluded or key in entries:
            return
        entries[key] = {'path': Path(path), 'kind': kind_of(path), 'root': root,
                        'missing': missing, 'new': not first and not missing and key not in known}

    for folder in data['folders']:
        for path in _walk(folder):
            add(path, folder)
    for path in data['files']:
        add(path, None, missing=not Path(path).is_file())
    # Daha once gorulup artik diskte olmayanlar (cikarilmadikca listede kalir).
    for path in data['known']:
        if _key(path) not in entries:
            root = next((folder for folder in data['folders'] if _inside(path, folder)), None)
            add(path, root, missing=True)

    present = sorted(str(item['path']) for item in entries.values())
    changed = first or {_key(path) for path in present} != known
    data['known'] = present
    data['scanned'] = True
    folders = [_key(folder) for folder in data['folders']]

    def order(item):
        root = _key(item['root']) if item['root'] else ''
        rank = folders.index(root) if root in folders else len(folders)
        relative = (os.path.relpath(str(item['path']), item['root']) if item['root']
                    else item['path'].name)
        return rank, natural_key(relative)

    return sorted(entries.values(), key=order), changed


def describe(entry, base=None):
    """Tablo icin durum: {'status', 'source', 'duration'}.

    status: 'missing' | 'ready' (ozet hazir) | 'transcript' (metin hazir) | 'pending'.
    """
    if entry['missing']:
        return {'status': 'missing', 'source': '', 'duration': 0.0}
    sessions = qa.cached_sessions(entry['path'], base) if entry['kind'] == 'video' else []
    if not sessions:
        return {'status': 'pending', 'source': '', 'duration': 0.0}
    best = max(sessions, key=lambda item: bool(item.get('overview')))
    source = best['source']
    if source.get('kind') == 'subtitle':
        label = 'Altyazı' + (' · ' + source['language'] if source.get('language') else '')
    else:
        label = 'Whisper' + (' · ' + source['model'] if source.get('model') else '')
    return {'status': 'ready' if best.get('overview') else 'transcript', 'source': label,
            'duration': float(best.get('duration') or 0.0)}
