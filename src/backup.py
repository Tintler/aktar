"""Yedekleme ve tasima (F239): kullanici verisi tek ZIP dosyasina yazilir, baska bilgisayarda (Windows <-> Linux) geri
yuklenir.

Yedege girenler (APP_DIR altinda): ayarlar (config.json, ui.json, istem dosyalari), kitaplik (book_library.json),
Kutuphane koleksiyonlari ve sohbetleri (library/), altyazi serileri ve sozlukleri (series/), temalar, ses onayarlari,
duygu etiketleri, karakter sesleri, kitap ozetleri, kitap gorselleri, Ekran Ceviri profilleri, eslenen telefonlar.
Istege bagli gruplar: calisma dosyalari (work_files: transkriptler, indeksler, dublaj projeleri; buyuk olabilir) ve
hazirlanmis sesler (ses-onbellegi; ucretli bulut sesleri dahil). Modeller, ses motorlari ve programin kendisi yedege
girmez (yeniden indirilir/kurulur). API anahtarlari isletim sisteminin sifre deposundadir: yedege girmez, yeni
bilgisayarda yeniden girilir.

Geri yuklemeden once mevcut veri APP_DIR/yedekler/geri-yukleme-oncesi-<zaman>.zip olarak saklanir. Geri yuklenen
yollar (kitaplar, koleksiyon klasorleri) yeni bilgisayarda yoksa relink() secilen klasorde ayni adli dosya/klasoru
arayip yollari duzeltir.
"""
from __future__ import annotations

import json
import os
import platform
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

VERSION = 1
MANIFEST = 'aktar-yedek.json'
BACKUP_DIR = 'yedekler'

# (grup, ad, yollar): yollar APP_DIR'e gore; klasorler icindekilerle
CORE = ('config.json', 'ui.json', 'book_library.json', 'translation_prompt.txt', 'book_translation_prompt.txt',
        'library', 'series', 'themes', 'ses-presetleri', 'duygu-etiketleri', 'karakter-sesleri', 'kitap-ozetleri',
        'kitap-gorselleri', 'oyun-ceviri', 'telefon/telefonlar.json')
GROUPS = {
    'core': {'label': 'Ayarlar ve kullanıcı verisi', 'paths': CORE, 'always': True},
    'work': {'label': 'Çalışma dosyaları (transkriptler, indeksler, dublaj projeleri)', 'paths': ('work_files',)},
    'audio': {'label': 'Hazırlanmış sesler (sesli okuma önbelleği, ücretli bulut sesleri dahil)', 'paths': ('ses-onbellegi',)},
}
SKIP_NAMES = {'__pycache__'}
SKIP_SUFFIXES = ('.lock', '.tmp', '.part')
SKIP_DIRS = {('work_files', 'stems')}   # ayrilmis muzik/ses parcalari: yeniden uretilir, cok buyuk


def _files(root, relative):
    """APP_DIR/relative altindaki dosyalar (relative POSIX yollariyla)."""
    base = Path(root) / relative
    if base.is_file():
        yield relative, base
        return
    if not base.is_dir():
        return
    for folder, names, files in os.walk(base):
        rel_folder = Path(folder).relative_to(root)
        names[:] = [name for name in names if name not in SKIP_NAMES
                    and tuple((rel_folder / name).parts[:2]) not in SKIP_DIRS]
        for name in files:
            if name.endswith(SKIP_SUFFIXES):
                continue
            path = Path(folder) / name
            yield (rel_folder / name).as_posix(), path


def sizes(root):
    """{grup: {'label', 'bytes', 'files', 'always'}} yedek penceresi icin."""
    result = {}
    for key, group in GROUPS.items():
        total = count = 0
        for relative in group['paths']:
            for _name, path in _files(root, relative):
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
                count += 1
        result[key] = {'label': group['label'], 'bytes': total, 'files': count, 'always': bool(group.get('always'))}
    return result


def create(root, target, groups=('core',), progress=None, cancelled=None, version=''):
    """Yedek ZIP'i yazar. Donen: {'path', 'files', 'bytes'}. Yarim kalan dosya silinir."""
    root, target = Path(root), Path(target)
    chosen = ['core'] + [key for key in groups if key in GROUPS and key != 'core']
    entries = [(name, path) for key in chosen for relative in GROUPS[key]['paths'] for name, path in _files(root, relative)]
    total = sum(path.stat().st_size for _name, path in entries if path.exists())
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.part')
    done = 0
    try:
        with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            manifest = {'version': VERSION, 'app_version': version, 'created': datetime.now().isoformat(timespec='seconds'),
                        'platform': platform.system(), 'root': str(root), 'groups': chosen,
                        'files': len(entries), 'bytes': total}
            archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
            for name, path in entries:
                if cancelled and cancelled():
                    raise InterruptedError('Yedekleme durduruldu.')
                try:
                    # sesler ve gorseller zaten sikistirilmis: yeniden sikistirmak yalnizca zaman alir
                    compress = zipfile.ZIP_STORED if path.suffix.lower() in ('.wav', '.png', '.jpg', '.mp3', '.m4b', '.mp4', '.webp') \
                        else zipfile.ZIP_DEFLATED
                    archive.write(path, name, compress_type=compress)
                    done += path.stat().st_size
                except FileNotFoundError:
                    continue
                if progress:
                    progress(done, total)
        os.replace(partial, target)
    except BaseException:
        try:
            partial.unlink()
        except OSError:
            pass
        raise
    return {'path': str(target), 'files': len(entries), 'bytes': total}


def inspect(path):
    """Yedegin bilgisi: manifest + gruplar; Aktar yedegi degilse ValueError."""
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read(MANIFEST).decode('utf-8'))
            names = archive.namelist()
    except KeyError:
        raise ValueError('Bu dosya bir Aktar yedeği değil.') from None
    except (zipfile.BadZipFile, ValueError, OSError) as error:
        raise ValueError(f'Yedek okunamadı: {error}') from None
    if not isinstance(manifest, dict) or int(manifest.get('version') or 0) > VERSION:
        raise ValueError('Yedek, Aktar\'ın daha yeni bir sürümüyle alınmış; önce Aktar\'ı güncelleyin.')
    return dict(manifest, entries=len([name for name in names if name != MANIFEST]))


def _safe(name):
    """ZIP icindeki yol APP_DIR'in disina cikmasin (.., mutlak yol, surucu harfi)."""
    parts = PurePosixPath(name.replace('\\', '/')).parts
    if not parts or name.startswith('/') or ':' in parts[0] or any(part in ('..', '') for part in parts):
        return None
    allowed = {PurePosixPath(item).parts[0] for group in GROUPS.values() for item in group['paths']}
    return parts if parts[0] in allowed else None


def restore(root, path, version='', progress=None):
    """Yedegi APP_DIR'e acar (ayni adli dosyalarin ustune yazar). Once mevcut veri yedeklenir. Donen:
    {'files', 'before': onceki verinin yedegi, 'manifest'}."""
    root = Path(root)
    manifest = inspect(path)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    before = create(root, root / BACKUP_DIR / f'geri-yukleme-oncesi-{stamp}.zip', ('core',), version=version)
    count = 0
    with zipfile.ZipFile(path) as archive:
        members = [info for info in archive.infolist() if info.filename != MANIFEST and not info.is_dir()]
        total = sum(info.file_size for info in members)
        done = 0
        for info in members:
            parts = _safe(info.filename)
            if parts is None:
                continue
            target = root.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + '.part')
            with archive.open(info) as source, open(temp, 'wb') as out:
                while True:
                    chunk = source.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(temp, target)
            count += 1
            done += info.file_size
            if progress:
                progress(done, total)
    return {'files': count, 'before': before['path'], 'manifest': manifest}


# ---------------------------------------------------------------- tasima: bulunamayan yollar
def _book_paths(root):
    try:
        data = json.loads((Path(root) / 'book_library.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None, []
    return data, [book.get('path', '') for book in data.get('books') or () if isinstance(book, dict)]


def _collections(root):
    folder = Path(root) / 'library'
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else ():
        if path.name.endswith(('.chat.json', '.overview.json', '.data.json')):
            continue
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and isinstance(value.get('folders'), list):
            yield path, value


def _name(path):
    """Yolun son parcasi (Windows ve POSIX ayiriciyla yazilmis yollar icin)."""
    return str(path).replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]


def missing(root):
    """Bu bilgisayarda bulunamayan yollar: {'books': [...], 'folders': [...], 'files': [...]}"""
    _data, books = _book_paths(root)
    result = {'books': [path for path in books if path and not Path(path).exists()], 'folders': [], 'files': []}
    for _path, value in _collections(root):
        result['folders'] += [item for item in value.get('folders') or () if not Path(item).exists()]
        result['files'] += [item for item in value.get('files') or () if not Path(item).exists()]
    for key in ('folders', 'files'):
        result[key] = list(dict.fromkeys(result[key]))
    return result


def _index(search, depth=8, limit=200000):
    """Secilen klasorun altindaki dosya ve klasorler: ({ad: [yol]}, {ad: [yol]})."""
    files, folders = {}, {}
    search = Path(search)
    seen = 0
    for folder, names, items in os.walk(search):
        if len(Path(folder).relative_to(search).parts) >= depth:
            names[:] = []
        names[:] = [name for name in names if not name.startswith('.') and name not in SKIP_NAMES]
        for name in names:
            folders.setdefault(name.casefold(), []).append(str(Path(folder) / name))
        for name in items:
            files.setdefault(name.casefold(), []).append(str(Path(folder) / name))
            seen += 1
        if seen > limit:
            break
    folders.setdefault(search.name.casefold(), []).insert(0, str(search))
    return files, folders


def _replace_prefix(value, old, new):
    text, prefix = str(value).replace('\\', '/'), str(old).replace('\\', '/').rstrip('/')
    if text.casefold() == prefix.casefold():
        return new
    if text.casefold().startswith(prefix.casefold() + '/'):
        return str(Path(new) / Path(*text[len(prefix) + 1:].split('/')))
    return value


def relink(root, search):
    """Bulunamayan kitap ve koleksiyon yollarini `search` klasorunde ayni adla arar ve duzeltir (tek eslesmeyi alir;
    ayni adli birden cok aday varsa ilki). Donen: {'books', 'folders', 'files', 'left'} (duzeltilen/kalan sayilari)."""
    root = Path(root)
    files, folders = _index(search)
    fixed = {'books': 0, 'folders': 0, 'files': 0}
    data, _books = _book_paths(root)
    if data is not None:
        changed = False
        for book in data.get('books') or ():
            path = book.get('path', '')
            if path and not Path(path).exists():
                found = files.get(_name(path).casefold())
                if found:
                    book['path'] = found[0]
                    fixed['books'] += 1
                    changed = True
        if changed:
            _write_json(root / 'book_library.json', data)
    for path, value in _collections(root):
        changed = False
        for old in list(value.get('folders') or ()):
            if Path(old).exists():
                continue
            found = folders.get(_name(old).casefold())
            if not found:
                continue
            new = found[0]
            for field in ('folders', 'files', 'excluded', 'known'):
                value[field] = [_replace_prefix(item, old, new) for item in value.get(field) or ()]
            fixed['folders'] += 1
            changed = True
        for index, old in enumerate(list(value.get('files') or ())):
            if Path(old).exists():
                continue
            found = files.get(_name(old).casefold())
            if found:
                value['files'][index] = found[0]
                fixed['files'] += 1
                changed = True
        if changed:
            _write_json(path, value)
    left = missing(root)
    return dict(fixed, left=sum(len(items) for items in left.values()))


def _write_json(path, value):
    temp = Path(path).with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)
