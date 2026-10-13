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

import copy
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

import media
import qa
import search_index
import series
import speech
from app_core import APP_DIR, FileLock, load_config, read, save_json
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


def _embedding_cfg(cfg):
    """describe/plan icin ayarlar; okunamazsa indeks kapali sayilir."""
    if cfg is not None:
        return cfg
    try:
        return load_config()
    except (OSError, ValueError, RuntimeError):
        return {'embedding_model': ''}


def is_indexed(video, session, cfg, base=None):
    if not str(cfg.get('embedding_model', '')).strip() or session is None:
        return False
    try:
        return search_index.index_path(video, session, cfg, base).exists()
    except OSError:
        return False


def describe(entry, base=None, cfg=None):
    """Tablo icin durum: {'status', 'source', 'duration'}.

    status: 'missing' | 'ready' (transkript + indeks) | 'transcript' (metin hazir,
    indeks yok ya da embedding modeli secilmedi) | 'no_subtitle' (yoklandi, metin
    altyazi yok: Whisper bekliyor) | 'pending'.
    """
    if entry['missing']:
        return {'status': 'missing', 'source': '', 'duration': 0.0}
    sessions = qa.cached_sessions(entry['path'], base) if entry['kind'] == 'video' else []
    if not sessions:
        probed = cached_probe(entry['path'], base) if entry['kind'] == 'video' else None
        if probed is None:
            return {'status': 'pending', 'source': '', 'duration': 0.0}
        return {'status': 'pending' if probed['subtitles'] else 'no_subtitle', 'source': '',
                'duration': probed['duration']}
    best = search_index.pick_session(sessions)
    source = best['source']
    if source.get('kind') == 'subtitle':
        label = 'Altyazı' + (' · ' + source['language'] if source.get('language') else '')
    else:
        label = 'Whisper' + (' · ' + source['model'] if source.get('model') else '')
    indexed = is_indexed(entry['path'], best, _embedding_cfg(cfg), base)
    return {'status': 'ready' if indexed else 'transcript', 'source': label,
            'duration': float(best.get('duration') or 0.0)}


# --- yoklama onbellegi + toplu transkript (F56) ---------------------------------
_PROBE_LOCK = threading.Lock()
_PROBE_STORES = {}  # depo dosyasi -> {damga: ozet}; ayni surecte tek kopya


def _probe_file(base=None):
    return Path(base or qa.work_dir()) / 'library' / 'probe.json'


def _stamp(path):
    """Dosya degisirse (boyut/tarih) eski yoklama gecersiz olsun."""
    stat = Path(path).stat()
    return f'{_key(path)}|{stat.st_size}|{int(stat.st_mtime)}'


def _probe_store(base):
    file = str(_probe_file(base))
    store = _PROBE_STORES.get(file)
    if store is None:
        try:
            store = json.loads(read(file))
        except (OSError, ValueError):
            store = {}
        if not isinstance(store, dict):
            store = {}
        _PROBE_STORES[file] = store
    return store


def cached_probe(path, base=None):
    """Daha once yoklanmissa {'duration', 'subtitles'}; ffprobe calistirmaz."""
    try:
        stamp = _stamp(path)
    except OSError:
        return None
    with _PROBE_LOCK:
        value = _probe_store(base).get(stamp)
    return copy.deepcopy(value) if isinstance(value, dict) else None


def probe(path, base=None):
    """Sure + altyazi akislari (onbellekli; yoksa tek ffprobe cagrisi)."""
    cached = cached_probe(path, base)
    if cached is not None:
        return cached
    value = media.probe_summary(path)
    stamp = _stamp(path)
    prefix = _key(path) + '|'
    with _PROBE_LOCK:
        store = _probe_store(base)
        for old in [item for item in store if item.startswith(prefix)]:
            del store[old]
        store[stamp] = value
        try:
            save_json(_probe_file(base), store)
        except OSError:
            pass  # onbellek yazilamazsa yalnizca bir dahaki sefere tekrar yoklanir
    return copy.deepcopy(value)


def plan(entries, base=None, progress=None, cancelled=None, cfg=None):
    """Toplu hazirlik plani; gerekirse videolari yoklar.

    Donen: {'ready': [entry], 'index': [entry] (transkript var, indeks yok),
            'subtitle': [entry], 'whisper': [entry], 'failed': [(entry, hata)],
            'whisper_seconds': float}. Embedding modeli secili degilse transkripti
    olan her video 'ready' sayilir.
    """
    cfg = _embedding_cfg(cfg)
    result = {'ready': [], 'index': [], 'subtitle': [], 'whisper': [], 'failed': [],
              'whisper_seconds': 0.0}
    videos = [entry for entry in entries if not entry['missing'] and entry['kind'] == 'video']
    for index, entry in enumerate(videos):
        if cancelled and cancelled():
            break
        session = search_index.pick_session(qa.cached_sessions(entry['path'], base))
        if session is not None:
            indexed = (not str(cfg.get('embedding_model', '')).strip()
                       or is_indexed(entry['path'], session, cfg, base))
            result['ready' if indexed else 'index'].append(entry)
        else:
            try:
                info = probe(entry['path'], base)
            except (RuntimeError, ValueError, OSError) as error:
                result['failed'].append((entry, str(error)))
                info = None
            if info is not None and qa.pick_subtitle_stream(info['subtitles']):
                result['subtitle'].append(entry)
            elif info is not None:
                result['whisper'].append(entry)
                result['whisper_seconds'] += info['duration']
        if progress:
            progress(index + 1, len(videos))
    return result


def transcribe(entry, cfg, allow_whisper=True, base=None, log=print, progress=None,
               cancelled=None):
    """Tek videonun transkriptini qa onbellegine yazar.

    Donen: 'cached' (zaten vardi) | 'subtitle' | 'whisper' | 'skipped' (altyazi yok,
    Whisper izni yok). Soru Sor paneli ayni onbellegi kullanir (ayni akis secimi).
    """
    path = entry['path']
    if qa.cached_sessions(path, base):
        return 'cached'
    info = probe(path, base)
    stream = qa.pick_subtitle_stream(info['subtitles'])
    if stream is not None:
        qa.load_subtitle_session(path, stream, base, log)
        return 'subtitle'
    result = speech.load_cached(path, cfg['whisper_model'], cfg['whisper_language'], base)
    if result is None:
        if not allow_whisper:
            return 'skipped'
        result = speech.transcribe(path, cfg['whisper_model'], cfg['whisper_device'],
                                   cfg['whisper_language'], base=base, progress=progress,
                                   cancelled=cancelled, log=log,
                                   cuda_dir=cfg.get('whisper_cuda_dir', ''))
    qa.load_whisper_session(path, result, base, log)
    return 'whisper'


def index(entry, cfg, base=None, log=print, cancelled=None, client=None):
    """Transkripti olan videoyu embedding ile indeksler (F57).

    Donen: 'indexed' | 'skipped' (embedding modeli secilmedi) | 'no_transcript'.
    """
    if not str(cfg.get('embedding_model', '')).strip():
        return 'skipped'
    path = search_index.build(entry['path'], cfg, client=client, base=base, log=log,
                              cancelled=cancelled)
    return 'indexed' if path is not None else 'no_transcript'
