"""Temizlik (F242): kaynagi artik olmayan kayitlari bulur ve secilenleri siler.

Kitaba ait kayitlar kitap kimligiyle (book_reader.book_id, dosya yolunun sha1'i) ayri klasorlerde durur: hazirlanmis
sesler, sesli kitap parcalari, duygu etiketleri, karakter sesleri, ozetler, kitap gorselleri. Kitapliktan kaldirmak
bunlara dokunmaz (ayni dosya yeniden eklenince ayni kimlikle geri gelir); kitapligda olmayan kimliklerin kayitlari
'yetim' sayilir. Ayrica dosyasi bulunamayan kitaplar, kaynak videosu/belgesi bulunamayan transkript ve arama indeksi
onbellekleri (work_files/qa, work_files/index; icindeki 'video' yolu) ve hicbir kitabin kullanmadigi donusturulmus
e-kitaplar (work_files/ebooks) listelenir. Hicbir sey kendiliginden silinmez: find() listeler, remove() yalnizca
verilen kimlikleri siler. Harici disk takili degilse dosyalar 'bulunamadi' gorunur; arayuz bunu soyler.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

BOOK_ID = re.compile(r'[0-9a-f]{8,40}')

# (tur, etiket, kitap kimligine gore yollar)
BOOK_PARTS = (
    ('audio', 'Hazırlanmış sesler', lambda b: [Path('ses-onbellegi') / b]),
    ('audiobook', 'Sesli kitap bölüm parçaları', lambda b: [Path('sesli-kitap') / b]),
    ('emotion', 'Duygu etiketleri', lambda b: [Path('duygu-etiketleri') / f'{b}.json', Path('duygu-etiketleri') / f'{b}.txt',
                                              Path('duygu-etiketleri') / 'yarim' / f'{b}.json']),
    ('cast', 'Karakter sesleri', lambda b: [Path('karakter-sesleri') / f'{b}.json', Path('karakter-sesleri') / 'yarim' / f'{b}.json']),
    ('recap', 'Kitap özeti', lambda b: [Path('kitap-ozetleri') / f'{b}.json']),
    ('art', 'Kitap görselleri', lambda b: [Path('kitap-gorselleri') / b]),
)
# kitap kimligiyle adlanan kayitlarin bulundugu klasorler (yetim aramasi): klasor -> (dosya mi, klasor mu)
_SCAN = (('ses-onbellegi', 'dir'), ('sesli-kitap', 'dir'), ('kitap-gorselleri', 'dir'), ('duygu-etiketleri', 'file'),
         ('duygu-etiketleri/yarim', 'file'), ('karakter-sesleri', 'file'), ('karakter-sesleri/yarim', 'file'),
         ('kitap-ozetleri', 'file'))


def _size(path):
    """(dosya sayisi, bayt)."""
    try:
        if path.is_file():
            return 1, path.stat().st_size
        files = [item for item in path.rglob('*') if item.is_file()]
        return len(files), sum(item.stat().st_size for item in files)
    except OSError:
        return 0, 0


def _library(root):
    try:
        data = json.loads((Path(root) / 'book_library.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    books = data.get('books') if isinstance(data, dict) else None
    return [book for book in books or () if isinstance(book, dict) and book.get('id')]


def book_parts(root, book):
    """Bir kitabin diskteki kayitlari: [{'kind', 'label', 'files', 'bytes'}] (olmayanlar listelenmez)."""
    if not BOOK_ID.fullmatch(str(book or '')):
        return []
    root = Path(root)
    result = []
    for kind, label, paths in BOOK_PARTS:
        files = size = 0
        for path in paths(book):
            if (root / path).exists():
                count, total = _size(root / path)
                files, size = files + max(count, 1), size + total
        if files:
            result.append({'kind': kind, 'label': label, 'files': files, 'bytes': size})
    return result


def remove_book_data(root, book, kinds=None):
    """Kitabin kayitlarini siler (`kinds` verilirse yalnizca o turler). Donen: silinen dosya sayisi ve bayt."""
    if not BOOK_ID.fullmatch(str(book or '')):
        raise ValueError('Geçersiz kitap kimliği.')
    root = Path(root)
    files = size = 0
    for kind, _label, paths in BOOK_PARTS:
        if kinds is not None and kind not in kinds:
            continue
        for path in paths(book):
            target = root / path
            if not target.exists():
                continue
            count, total = _size(target)
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            files, size = files + count, size + total
    return {'files': files, 'bytes': size}


def _title_of(root, book):
    """Yetim kaydin hangi kitaba ait oldugu: kayitlardaki 'title' (yoksa '')."""
    for path in (Path('kitap-gorselleri') / book / 'plan.json', Path('duygu-etiketleri') / f'{book}.json',
                 Path('karakter-sesleri') / f'{book}.json', Path('duygu-etiketleri') / 'yarim' / f'{book}.json',
                 Path('karakter-sesleri') / 'yarim' / f'{book}.json', Path('kitap-ozetleri') / f'{book}.json'):
        try:
            data = json.loads((Path(root) / path).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        title = data.get('title') if isinstance(data, dict) else None
        if isinstance(title, str) and title.strip():
            return title.strip()
    return ''


def _source_exists(path):
    try:
        return Path(path).exists()
    except (OSError, ValueError):
        return False


def _cache_source(path):
    """work_files/qa ve work_files/index JSON'undaki kaynak yolu (yoksa None)."""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    source = data.get('video') if isinstance(data, dict) else None
    return (source, data.get('title') or Path(source).stem) if isinstance(source, str) and source else None


def find(root):
    """Temizlenebilecek kayitlar: {'books': [...], 'missing': [...], 'caches': [...], 'ebooks': [...]}; her ogede
    'id' (remove() icin), etiket ve boyut."""
    root = Path(root)
    library = _library(root)
    known = {book['id'] for book in library}
    orphans = set()
    for folder, kind in _SCAN:
        directory = root / folder
        if not directory.is_dir():
            continue
        for item in directory.iterdir():
            name = item.name if kind == 'dir' else item.name.rpartition('.')[0]
            if (item.is_dir() if kind == 'dir' else item.is_file()) and BOOK_ID.fullmatch(name) and name not in known:
                orphans.add(name)
    books = []
    for book in sorted(orphans):
        parts = book_parts(root, book)
        if parts:
            books.append({'id': 'book:' + book, 'book': book, 'title': _title_of(root, book), 'parts': parts,
                          'bytes': sum(part['bytes'] for part in parts)})
    missing = []
    for book in library:
        if not _source_exists(book.get('path', '')):
            parts = book_parts(root, book['id'])
            missing.append({'id': 'missing:' + book['id'], 'book': book['id'], 'title': book.get('title') or '',
                            'path': book.get('path', ''), 'parts': parts, 'bytes': sum(part['bytes'] for part in parts)})
    caches = {}
    for folder in ('qa', 'index'):
        directory = root / 'work_files' / folder
        if not directory.is_dir():
            continue
        for item in sorted(directory.glob('*.json')):
            found = _cache_source(item)
            if not found or _source_exists(found[0]):
                continue
            entry = caches.setdefault(found[0], {'id': 'cache:' + found[0], 'path': found[0], 'title': found[1],
                                                 'files': 0, 'bytes': 0})
            entry['files'] += 1
            entry['bytes'] += _size(item)[1]
    ebooks = []
    directory = root / 'work_files' / 'ebooks'
    if directory.is_dir():
        used = {str(Path(book.get('path', ''))).casefold() for book in library}
        for item in sorted(directory.glob('*.epub')):
            if str(item).casefold() not in used and str(item.resolve()).casefold() not in used:
                ebooks.append({'id': 'ebook:' + item.name, 'title': item.stem, 'bytes': _size(item)[1]})
    return {'books': books, 'missing': missing, 'caches': list(caches.values()), 'ebooks': ebooks}


def remove(root, ids):
    """find() kimliklerini siler (her seferinde yeniden denetlenir: bu arada kaynagi geri gelen silinmez).
    Dosyasi bulunamayan kitap kitapliktan da kaldirilir. Donen: {'removed', 'files', 'bytes', 'books': [...]}"""
    root = Path(root)
    current = find(root)
    allowed = {item['id']: item for group in current.values() for item in group}
    removed = files = size = 0
    dropped = []
    for key in ids or ():
        item = allowed.get(key)
        if item is None:
            continue
        kind = key.partition(':')[0]
        if kind in ('book', 'missing'):
            result = remove_book_data(root, item['book'])
            files, size = files + result['files'], size + result['bytes']
            if kind == 'missing':
                dropped.append(item['book'])
        elif kind == 'cache':
            for folder in ('qa', 'index'):
                for path in (root / 'work_files' / folder).glob('*.json') if (root / 'work_files' / folder).is_dir() else ():
                    found = _cache_source(path)
                    if found and found[0] == item['path']:
                        files, size = files + 1, size + _size(path)[1]
                        path.unlink()
        elif kind == 'ebook':
            path = root / 'work_files' / 'ebooks' / key.partition(':')[2]
            if path.is_file():
                files, size = files + 1, size + _size(path)[1]
                path.unlink()
        removed += 1
    return {'removed': removed, 'files': files, 'bytes': size, 'books': dropped}
