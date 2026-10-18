"""E-kitap bicimlerinden EPUB (F153): MOBI/AZW3/AZW/PRC ve FB2 (FB2.ZIP, FBZ).

Kitap Cevir ve Okuma yalnizca EPUB isler; baska bir bicim acilinca once buradan EPUB uretilir ve
akisin geri kalani aynen o EPUB ile calisir. Kaynak dosyaya dokunulmaz; EPUB uygulama klasorundeki
work_files/ebooks altina yazilir (kaynagin ozetiyle adlanir, ikinci acilista yeniden uretilmez).

- FB2: XML dogrudan okunur (bolumler, basliklar, siir, alinti, dipnotlar, gorseller, kapak).
- MOBI/AZW3: Calibre kuruluysa (ebook-convert) en dogru sonuc icin o kullanilir. Yoksa yerlesik okuyucu:
  PalmDB kayitlari, PalmDOC acma, EXTH (ad, yazar, dil, kapak), gorseller. KF8'de (AZW3) metin parcalari
  sirasiyla okunur; bicim yaklasiktir. HUFF/CDIC sikistirma ve DRM'li kitaplar desteklenmez.
"""
from __future__ import annotations

import base64
import hashlib
import html
import os
import re
import shutil
import struct
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET

MOBI_SUFFIXES = ('.mobi', '.azw3', '.azw', '.prc')
FB2_SUFFIXES = ('.fb2', '.fbz', '.fb2.zip')
SUFFIXES = MOBI_SUFFIXES + FB2_SUFFIXES
DIALOG_FILTER = 'E-kitap (*.epub *.mobi *.azw3 *.azw *.prc *.fb2 *.fbz *.zip)'
CHUNK_CHARS = 40000          # baslik bulunamazsa bolum boyu


def suffix(path):
    name = Path(path).name.lower()
    return '.fb2.zip' if name.endswith('.fb2.zip') else Path(name).suffix


def supported(path):
    return suffix(path) in SUFFIXES


def output_dir():
    from app_core import APP_DIR
    return Path(APP_DIR) / 'work_files' / 'ebooks'


def ensure_epub(path, log=print, folder=None):
    """EPUB ise kendisi; desteklenen bicimse donusturulmus EPUB'un yolu."""
    path = Path(path)
    kind = suffix(path)
    if kind == '.epub':
        return path
    if kind not in SUFFIXES:
        raise ValueError('Desteklenmeyen e-kitap biçimi: ' + path.name)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', path.name[:-len(kind)])[:80].rstrip(' .') or 'kitap'
    target = Path(folder or output_dir()) / f'{stem}-{digest}.epub'
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind in FB2_SUFFIXES:
        fb2_to_epub(path, target)
    else:
        calibre = calibre_converter()
        if calibre:
            log(f'E-kitap Calibre ile EPUB\'a dönüştürülüyor: {path.name}')
            try:
                _calibre_convert(calibre, path, target)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                log(f'UYARI: Calibre dönüştüremedi ({error}); yerleşik okuyucu deneniyor.')
                mobi_to_epub(path, target)
        else:
            log(f'E-kitap yerleşik okuyucuyla EPUB\'a dönüştürülüyor: {path.name}')
            mobi_to_epub(path, target)
    log('EPUB hazır: ' + str(target))
    return target


# ---------------------------------------------------------------------- Calibre
def calibre_converter():
    found = shutil.which('ebook-convert')
    if found:
        return found
    candidates = []
    if os.name == 'nt':
        for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
            if base:
                candidates += [Path(base) / 'Calibre2' / 'ebook-convert.exe', Path(base) / 'Calibre' / 'ebook-convert.exe']
    else:
        candidates += [Path('/usr/bin/ebook-convert'), Path('/opt/calibre/ebook-convert')]
    return next((str(item) for item in candidates if item.is_file()), None)


def _calibre_convert(exe, source, target):
    temp = target.with_name(target.stem + '.tmp.epub')
    hide = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if os.name == 'nt' else {}
    result = subprocess.run([exe, str(source), str(temp)], capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=900, **hide)
    if result.returncode != 0 or not temp.is_file():
        temp.unlink(missing_ok=True)
        lines = (result.stderr or result.stdout or '').strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f'çıkış kodu {result.returncode}')
    temp.replace(target)


# ---------------------------------------------------------------------- EPUB yazici
STYLE = ('body{font-family:serif;line-height:1.45;margin:5%;}img{max-width:100%;height:auto;}'
         '.poem{margin:1em 2em;}.poem p{text-indent:0;margin:0;}.author{text-align:right;font-style:italic;}'
         'blockquote{margin:1em 1.5em;}.epigraph{font-style:italic;}')


def _page(title, body, language):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{language}" '
            f'xml:lang="{language}"><head><title>{html.escape(title)}</title>'
            '<link rel="stylesheet" type="text/css" href="../style.css"/></head>'
            f'<body>{body}</body></html>')


def write_epub(path, title, author, language, chapters, images=None, cover=None):
    """chapters: [{'title', 'body' (XHTML parcasi), 'file' (istege bagli ad)}];
    images: {ad: (mime, bayt)} -> OEBPS/images/<ad>; cover: images icindeki ad."""
    path = Path(path)
    language = language or 'en'
    images = images or {}
    ident = 'urn:uuid:' + str(uuid.uuid4())
    modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    manifest, spine, nav, ncx, files = [], [], [], [], []
    for number, chapter in enumerate(chapters, 1):
        name = chapter.get('file') or f'text/c{number:04d}.xhtml'
        label = html.escape(chapter['title'] or f'{number}')
        files.append((f'OEBPS/{name}', _page(chapter['title'] or str(number), chapter['body'], language)))
        manifest.append(f'<item id="c{number}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{number}"/>')
        if chapter.get('toc', True):
            nav.append(f'<li><a href="{name}">{label}</a></li>')
            ncx.append(f'<navPoint id="n{number}" playOrder="{len(ncx) + 1}"><navLabel><text>{label}</text></navLabel>'
                       f'<content src="{name}"/></navPoint>')
    for number, (name, (mime, _data)) in enumerate(sorted(images.items()), 1):
        properties = ' properties="cover-image"' if name == cover else ''
        manifest.append(f'<item id="i{number}" href="images/{name}" media-type="{mime}"{properties}/>')
    cover_meta = ''
    if cover in images:
        index = sorted(images).index(cover) + 1
        cover_meta = f'<meta name="cover" content="i{index}"/>'
    nav_doc = _page(title, '<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>' + ''.join(nav) + '</ol></nav>',
                    language).replace('<link rel="stylesheet" type="text/css" href="../style.css"/>',
                                      '<link rel="stylesheet" type="text/css" href="style.css"/>')
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="bookid">{ident}</dc:identifier><dc:title>{html.escape(title)}</dc:title>'
           + (f'<dc:creator>{html.escape(author)}</dc:creator>' if author else '')
           + f'<dc:language>{html.escape(language)}</dc:language><meta property="dcterms:modified">{modified}</meta>'
           + cover_meta + '</metadata><manifest>'
           '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
           '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
           '<item id="css" href="style.css" media-type="text/css"/>' + ''.join(manifest)
           + '</manifest><spine toc="ncx">' + ''.join(spine) + '</spine></package>')
    toc = ('<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="{ident}"/></head><docTitle><text>{html.escape(title)}</text></docTitle>'
           '<navMap>' + ''.join(ncx) + '</navMap></ncx>')
    container = ('<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                 '</rootfiles></container>')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        archive.writestr('META-INF/container.xml', container)
        archive.writestr('OEBPS/content.opf', opf)
        archive.writestr('OEBPS/nav.xhtml', nav_doc)
        archive.writestr('OEBPS/toc.ncx', toc)
        archive.writestr('OEBPS/style.css', STYLE)
        for name, content in files:
            archive.writestr(name, content)
        for name, (_mime, data) in images.items():
            archive.writestr(f'OEBPS/images/{name}', data)
    temp.replace(path)
    return path


def _language(value):
    value = str(value or '').strip().lower().replace('_', '-')
    return value.split('-')[0] if re.fullmatch(r'[a-z]{2,3}(-[a-z0-9]+)*', value) else ''


# ---------------------------------------------------------------------- FB2
def _local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def _href(node):
    for key, value in node.attrib.items():
        if _local(key) == 'href':
            return value
    return ''


def _text(node):
    return ' '.join(''.join(node.itertext()).split())


def _fb2_bytes(path):
    data = Path(path).read_bytes()
    if data[:2] == b'PK':
        with zipfile.ZipFile(path) as archive:
            name = next((item for item in archive.namelist() if item.lower().endswith('.fb2')), None)
            if name is None:
                raise ValueError('Arşivde .fb2 dosyası yok: ' + Path(path).name)
            data = archive.read(name)
    return data


class _Fb2:
    BLOCK_TAGS = {'p', 'subtitle', 'empty-line', 'poem', 'cite', 'epigraph', 'table', 'image', 'text-author'}

    def __init__(self, root):
        self.root = root
        self.images = {}
        self.image_names = {}
        for node in root:
            if _local(node.tag) == 'binary' and node.get('id'):
                mime = node.get('content-type') or 'image/jpeg'
                extension = {'image/png': 'png', 'image/gif': 'gif', 'image/svg+xml': 'svg'}.get(mime, 'jpg')
                name = f'{len(self.images) + 1:04d}.{extension}'
                try:
                    self.images[name] = (mime, base64.b64decode(''.join((node.text or '').split())))
                except ValueError:
                    continue
                self.image_names[node.get('id')] = name
        self.note_file = 'text/notes.xhtml'
        self.note_ids = set()

    def inline(self, node):
        out = [html.escape(node.text or '')]
        for child in node:
            tag = _local(child.tag)
            inner = self.inline(child)
            if tag == 'emphasis':
                out.append(f'<em>{inner}</em>')
            elif tag == 'strong':
                out.append(f'<strong>{inner}</strong>')
            elif tag == 'strikethrough':
                out.append(f'<s>{inner}</s>')
            elif tag in ('sub', 'sup', 'code'):
                out.append(f'<{tag}>{inner}</{tag}>')
            elif tag == 'a':
                target = _href(child)
                if target.startswith('#') and target[1:] in self.note_ids:
                    out.append(f'<a href="../{self.note_file}{html.escape(target, quote=True)}"><sup>{inner}</sup></a>')
                elif re.match(r'https?://', target):
                    out.append(f'<a href="{html.escape(target, quote=True)}">{inner}</a>')
                else:
                    out.append(inner)
            elif tag == 'image':
                out.append(self.image(child))
            else:
                out.append(inner)
            out.append(html.escape(child.tail or ''))
        return ''.join(out)

    def image(self, node):
        name = self.image_names.get(_href(node).lstrip('#'))
        return f'<img src="../images/{name}" alt=""/>' if name else ''

    def anchor(self, node):
        ident = node.get('id')
        return f' id="{html.escape(ident, quote=True)}"' if ident else ''

    def blocks(self, node, level):
        out = []
        for child in node:
            tag = _local(child.tag)
            if tag == 'title':
                text = ' — '.join(self.inline(p) for p in child if _local(p.tag) == 'p') or self.inline(child)
                out.append(f'<h{min(level, 6)}{self.anchor(child)}>{text}</h{min(level, 6)}>')
            elif tag == 'p':
                out.append(f'<p{self.anchor(child)}>{self.inline(child)}</p>')
            elif tag == 'subtitle':
                out.append(f'<h{min(level + 1, 6)}>{self.inline(child)}</h{min(level + 1, 6)}>')
            elif tag == 'empty-line':
                out.append('<p>&#160;</p>')
            elif tag == 'image':
                out.append(f'<div class="image">{self.image(child)}</div>')
            elif tag == 'poem':
                out.append('<div class="poem">' + self.blocks(child, level + 1) + '</div>')
            elif tag == 'stanza':
                out.append('<p>' + '<br/>'.join(self.inline(v) for v in child if _local(v.tag) == 'v') + '</p>')
            elif tag == 'v':
                out.append(f'<p>{self.inline(child)}</p>')
            elif tag == 'cite':
                out.append('<blockquote>' + self.blocks(child, level + 1) + '</blockquote>')
            elif tag == 'epigraph':
                out.append('<blockquote class="epigraph">' + self.blocks(child, level + 1) + '</blockquote>')
            elif tag == 'text-author':
                out.append(f'<p class="author">{self.inline(child)}</p>')
            elif tag == 'table':
                rows = []
                for row in child:
                    cells = ''.join(f'<{_local(c.tag)}>{self.inline(c)}</{_local(c.tag)}>' for c in row
                                    if _local(c.tag) in ('td', 'th'))
                    rows.append(f'<tr>{cells}</tr>')
                out.append('<table>' + ''.join(rows) + '</table>')
            elif tag == 'section':
                out.append(f'<div{self.anchor(child)}>' + self.blocks(child, level + 1) + '</div>')
        return ''.join(out)

    def chapters(self, body):
        """Bolum = dogrudan metin tasiyan ya da alt bolumu olmayan section. Yalnizca alt bolumlerden
        olusan ust section'larin (kisim) basligi sonraki bolumun basina eklenir."""
        result, pending = [], []

        def walk(section, depth):
            children = [c for c in section if _local(c.tag) == 'section']
            direct = [c for c in section if _local(c.tag) in self.BLOCK_TAGS]
            title_node = next((c for c in section if _local(c.tag) == 'title'), None)
            if children and not direct:
                if title_node is not None:
                    pending.append(f'<h1{self.anchor(section)}>{self.inline_title(title_node)}</h1>')
                for child in children:
                    walk(child, depth + 1)
                return
            title = _text(title_node) if title_node is not None else ''
            body_html = ''.join(pending) + f'<div{self.anchor(section)}>' + self.blocks(section, 1 if not pending else 2) + '</div>'
            pending.clear()
            result.append({'title': title, 'body': body_html})

        sections = [c for c in body if _local(c.tag) == 'section']
        intro = [c for c in body if _local(c.tag) in ('title', 'epigraph', 'image', 'p')]
        if intro:
            wrapper = ET.Element('section')
            wrapper.extend(intro)
            result.append({'title': _text(intro[0]) if _local(intro[0].tag) == 'title' else '',
                           'body': self.blocks(wrapper, 1), 'toc': bool(_local(intro[0].tag) == 'title')})
        for section in sections:
            walk(section, 1)
        if pending:
            result.append({'title': '', 'body': ''.join(pending)})
        return result

    def inline_title(self, node):
        return ' — '.join(self.inline(p) for p in node if _local(p.tag) == 'p') or self.inline(node)


def fb2_to_epub(source, target):
    try:
        root = ET.fromstring(_fb2_bytes(source))
    except ET.ParseError as error:
        raise ValueError(f'FB2 okunamadı: {error}') from None
    if _local(root.tag) != 'FictionBook':
        raise ValueError('FB2 değil: ' + Path(source).name)
    info = next((n for n in root.iter() if _local(n.tag) == 'title-info'), None)
    title, author, language, cover = Path(source).stem, '', 'en', None
    book = _Fb2(root)
    if info is not None:
        for node in info:
            tag = _local(node.tag)
            if tag == 'book-title' and _text(node):
                title = _text(node)
            elif tag == 'author' and not author:
                parts = {_local(n.tag): _text(n) for n in node}
                author = ' '.join(parts.get(k, '') for k in ('first-name', 'middle-name', 'last-name') if parts.get(k)) \
                    or parts.get('nickname', '')
            elif tag == 'lang' and _language(_text(node)):
                language = _language(_text(node))
            elif tag == 'coverpage':
                image = next((n for n in node if _local(n.tag) == 'image'), None)
                if image is not None:
                    cover = book.image_names.get(_href(image).lstrip('#'))
    bodies = [n for n in root if _local(n.tag) == 'body']
    notes = [b for b in bodies if b.get('name') in ('notes', 'comments')]
    main = [b for b in bodies if b not in notes]
    for body in notes:
        book.note_ids.update(n.get('id') for n in body.iter() if n.get('id'))
    chapters = []
    for body in main:
        chapters.extend(book.chapters(body))
    if notes:
        chapters.append({'title': 'Notes', 'file': book.note_file,
                         'body': ''.join(book.blocks(body, 1) for body in notes)})
    chapters = [c for c in chapters if re.sub(r'<[^>]+>|&#160;|\s', '', c['body'])]
    if not chapters:
        raise ValueError('FB2 içinde metin bulunamadı.')
    if cover:
        chapters.insert(0, {'title': title, 'body': f'<div class="image"><img src="../images/{cover}" alt=""/></div>',
                            'toc': False})
    return write_epub(target, title, author, language, chapters, book.images, cover)


# ---------------------------------------------------------------------- MOBI / AZW3
class MobiError(ValueError):
    pass


def _u16(data, offset):
    return struct.unpack_from('>H', data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from('>I', data, offset)[0]


def palmdoc_decompress(data):
    out = bytearray()
    index, size = 0, len(data)
    while index < size:
        byte = data[index]
        index += 1
        if byte == 0 or 0x09 <= byte <= 0x7F:
            out.append(byte)
        elif byte <= 0x08:
            out += data[index:index + byte]
            index += byte
        elif byte >= 0xC0:
            out += bytes((0x20, byte ^ 0x80))
        else:
            if index >= size:
                break
            pair = (byte << 8) | data[index]
            index += 1
            distance, length = (pair >> 3) & 0x7FF, (pair & 7) + 3
            if distance == 0 or distance > len(out):
                continue
            for _ in range(length):
                out.append(out[-distance])
    return bytes(out)


def _trailing_size(record, flags):
    """Metin kaydinin sonundaki ek veri (extra data flags) boyu."""
    size = 0
    for bit in range(1, 16):
        if flags & (1 << bit):
            # Sondan geriye degisken uzunluklu sayi: her baytin 7 biti, ilk baytin ust biti bitirir.
            value, shift, position = 0, 0, len(record) - size - 1
            for _ in range(4):
                if position < 0:
                    break
                byte = record[position]
                value |= (byte & 0x7F) << shift
                shift += 7
                position -= 1
                if byte & 0x80:
                    break
            size += value
    if flags & 1 and len(record) > size:
        size += (record[len(record) - size - 1] & 0x3) + 1
    return size


def _image_kind(data):
    if data[:3] == b'\xff\xd8\xff':
        return 'image/jpeg', 'jpg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png', 'png'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif', 'gif'
    return None, None


class MobiBook:
    def __init__(self, data):
        if len(data) < 78 or data[60:68] not in (b'BOOKMOBI', b'TEXtREAd'):
            raise MobiError('MOBI/AZW dosyası değil (KFX biçimi desteklenmez; Calibre ile EPUB\'a çevirin).')
        self.data = data
        count = _u16(data, 76)
        offsets = [_u32(data, 78 + i * 8) for i in range(count)]
        self.records = [(offsets[i], offsets[i + 1] if i + 1 < count else len(data)) for i in range(count)]
        self.base = 0
        self._read_header(0)
        boundary = self.exth.get(121)
        if self.version >= 8 or boundary is None:
            return
        # Birlesik dosya (MOBI7 + KF8): KF8 kismi daha temiz HTML verir.
        try:
            # EXTH 121: KF8 basliginin kayit numarasi; bir onceki kayit 'BOUNDARY' isaretidir.
            index = struct.unpack('>I', boundary[0])[0]
            if 1 < index < len(self.records) and self.record(index - 1)[:8] == b'BOUNDARY':
                kf8 = MobiBook.__new__(MobiBook)
                kf8.data, kf8.records, kf8.base = data, self.records, index
                kf8._read_header(index)
                if kf8.version >= 8:
                    self.__dict__.update(kf8.__dict__)
        except (struct.error, MobiError, IndexError):
            pass

    def record(self, index):
        start, end = self.records[index]
        return self.data[start:end]

    def _read_header(self, index):
        rec0 = self.record(index)
        self.compression = _u16(rec0, 0)
        self.text_records = _u16(rec0, 8)
        encryption = _u16(rec0, 12)
        if encryption:
            raise MobiError('Bu kitap DRM ile korunuyor; yalnızca DRM içermeyen kitaplar açılabilir.')
        self.exth = {}
        self.title, self.encoding, self.first_image, self.extra_flags, self.version = '', 'cp1252', None, 0, 6
        if rec0[16:20] != b'MOBI':
            return  # yalin PalmDOC
        header_length = _u32(rec0, 20)
        self.encoding = 'utf-8' if _u32(rec0, 28) == 65001 else 'cp1252'
        self.version = _u32(rec0, 36)
        name_offset, name_length = _u32(rec0, 84), _u32(rec0, 88)
        self.title = rec0[name_offset:name_offset + name_length].decode(self.encoding, 'replace')
        first_image = _u32(rec0, 108)
        self.first_image = None if first_image in (0, 0xFFFFFFFF) else first_image + self.base
        if header_length >= 0xE4:
            self.extra_flags = _u16(rec0, 16 + 0xE2)
        if _u32(rec0, 128) & 0x40:
            start = 16 + header_length
            if rec0[start:start + 4] == b'EXTH':
                count, position = _u32(rec0, start + 8), start + 12
                for _ in range(count):
                    kind, size = _u32(rec0, position), _u32(rec0, position + 4)
                    self.exth.setdefault(kind, []).append(rec0[position + 8:position + size])
                    position += size

    def meta(self, kind):
        values = self.exth.get(kind)
        return values[0].decode(self.encoding, 'replace').strip() if values else ''

    def text(self):
        if self.compression == 17480:
            raise MobiError('HUFF/CDIC sıkıştırmalı MOBI yerleşik okuyucuyla açılamıyor; Calibre kurun.')
        if self.compression not in (1, 2):
            raise MobiError(f'Bilinmeyen MOBI sıkıştırması: {self.compression}')
        chunks = []
        for index in range(self.base + 1, self.base + 1 + self.text_records):
            record = self.record(index)
            trailing = _trailing_size(record, self.extra_flags)
            if trailing:
                record = record[:len(record) - trailing]
            chunks.append(palmdoc_decompress(record) if self.compression == 2 else record)
        return b''.join(chunks).decode(self.encoding, 'replace')

    def image(self, number):
        """recindex / kindle:embed numarasi (1 tabanli) -> (mime, uzanti, bayt) ya da None."""
        if self.first_image is None:
            return None
        index = self.first_image + number - 1
        if not 0 <= index < len(self.records):
            return None
        data = self.record(index)
        mime, extension = _image_kind(data)
        return (mime, extension, data) if mime else None


_BLOCK = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'li', 'tr', 'table', 'ul', 'ol',
          'section', 'article', 'center', 'pre', 'dd', 'dt', 'figure', 'figcaption'}
_INLINE = {'em': 'em', 'i': 'em', 'strong': 'strong', 'b': 'strong', 'sup': 'sup', 'sub': 'sub', 'u': 'em',
           'small': None, 'span': None, 'font': None, 'a': None, 'big': None, 'code': 'code', 's': 's'}


class _MobiHtml(HTMLParser):
    """MOBI/KF8 HTML'ini sade bloklara cevirir: [('break'|'h1'..'h6'|'p'|'img', icerik)]."""

    def __init__(self, image_ref):
        super().__init__(convert_charrefs=True)
        self.image_ref = image_ref
        self.items = []
        self.kind = 'p'
        self.buffer = []
        self.open_inline = []
        self.skip = 0

    def flush(self):
        for tag in reversed(self.open_inline):
            self.buffer.append(f'</{tag}>')
        self.open_inline = []
        text = ''.join(self.buffer).strip()
        if re.sub(r'<[^>]+>|\s', '', text):
            self.items.append((self.kind, text))
        self.buffer, self.kind = [], 'p'

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        if tag in ('script', 'style', 'head', 'title'):
            self.skip += 1
            return
        if tag == 'mbp:pagebreak' or (tag in ('div', 'p') and 'page-break-before' in (attrs.get('style') or '').lower()):
            self.flush()
            self.items.append(('break', ''))
            return
        if tag in _BLOCK:
            self.flush()
            if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                self.kind = tag
            elif tag == 'blockquote':
                self.kind = 'blockquote'
            return
        if tag == 'br':
            self.buffer.append('<br/>')
            return
        if tag == 'img':
            ref = self.image_ref(attrs)
            if ref:
                kind = self.kind  # baslik icindeki resim basligi bozmasin
                self.flush()
                self.items.append(('img', ref))
                self.kind = kind
            return
        mapped = _INLINE.get(tag)
        if mapped:
            self.buffer.append(f'<{mapped}>')
            self.open_inline.append(mapped)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ('script', 'style', 'head', 'title'):
            self.skip = max(0, self.skip - 1)
            return
        if tag in _BLOCK:
            self.flush()
            return
        mapped = _INLINE.get(tag)
        if mapped and mapped in self.open_inline:
            while self.open_inline:
                last = self.open_inline.pop()
                self.buffer.append(f'</{last}>')
                if last == mapped:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.buffer.append(html.escape(data))

    def close(self):
        super().close()
        self.flush()


_KINDLE_EMBED = re.compile(r'kindle:embed:([0-9A-Va-v]{4})')


def mobi_to_epub(source, target):
    book = MobiBook(Path(source).read_bytes())
    raw = book.text()
    images, used = {}, {}

    def image_ref(attrs):
        number = None
        if attrs.get('recindex'):
            try:
                number = int(attrs['recindex'])
            except ValueError:
                return None
        else:
            match = _KINDLE_EMBED.search(attrs.get('src') or '')
            if match:
                number = int(match.group(1), 32)
        if not number:
            return None
        if number not in used:
            found = book.image(number)
            if not found:
                return None
            mime, extension, data = found
            name = f'{number:04d}.{extension}'
            images[name] = (mime, data)
            used[number] = name
        return used[number]

    parser = _MobiHtml(image_ref)
    parser.feed(raw)
    parser.close()
    chapters = _mobi_chapters(parser.items)
    if not chapters:
        raise MobiError('Kitapta okunabilir metin bulunamadı.')
    title = book.meta(503) or book.title or Path(source).stem
    author = book.meta(100)
    language = _language(book.meta(524)) or 'en'
    cover = None
    if book.exth.get(201):
        try:
            number = struct.unpack('>I', book.exth[201][0])[0] + 1
            cover = image_ref({'recindex': str(number)})
        except struct.error:
            cover = None
    if cover:
        chapters.insert(0, {'title': title, 'body': f'<div class="image"><img src="../images/{cover}" alt=""/></div>',
                            'toc': False})
    return write_epub(target, title, author, language, chapters, images, cover)


def _render(kind, content):
    if kind == 'img':
        return f'<div class="image"><img src="../images/{content}" alt=""/></div>'
    if kind == 'blockquote':
        return f'<blockquote><p>{content}</p></blockquote>'
    return f'<{kind}>{content}</{kind}>'


def _mobi_chapters(items):
    """Sayfa sonlarindan, yoksa h1/h2 basliklarindan, o da yoksa sabit boydan bolumlere ayirir."""
    def plain(text):
        return html.unescape(re.sub(r'<[^>]+>', ' ', text)).split()

    groups, current = [], []
    for kind, content in items:
        if kind == 'break':
            if current:
                groups.append(current)
            current = []
            continue
        if kind in ('h1', 'h2') and any(k not in ('img', 'h1', 'h2') for k, _ in current):
            groups.append(current)
            current = []
        current.append((kind, content))
    if current:
        groups.append(current)
    if len(groups) == 1 and sum(len(c) for _k, c in groups[0]) > CHUNK_CHARS * 1.5:
        single, groups, current, size = groups[0], [], [], 0
        for item in single:
            current.append(item)
            size += len(item[1])
            if size >= CHUNK_CHARS and item[0] == 'p':
                groups.append(current)
                current, size = [], 0
        if current:
            groups.append(current)
    chapters = []
    for group in groups:
        if not any(kind != 'img' for kind, _ in group) and chapters:
            chapters[-1]['body'] += ''.join(_render(k, c) for k, c in group)
            continue
        heading = next((c for k, c in group if k in ('h1', 'h2', 'h3')), None)
        if heading is None:
            position = next((i for i, (k, _c) in enumerate(group) if k == 'p'), None)
            words = plain(group[position][1]) if position is not None else []
            title = ' '.join(words) if 0 < len(words) <= 12 else f'{len(chapters) + 1}'
            if 0 < len(words) <= 12:
                # Baslik etiketi olmayan eski MOBI: kisa ilk paragraf bolum basligidir (ceviride iki kez gecmesin).
                group = list(group)
                group[position] = ('h1', group[position][1])
        else:
            title = ' '.join(plain(heading))
        chapters.append({'title': title, 'body': ''.join(_render(k, c) for k, c in group)})
    return chapters
