"""Belge dosyalari (F64/F68): PDF, metin, Word, Excel/CSV, EPUB -> sayfa numarali metin oturumu.

Belgeler videolarla ayni hatta girer: metin `qa` onbellegine bir oturum olarak
yazilir (segment konumu = sayfa numarasi), sonra indekslenir ve koleksiyon
sohbetinde [V3 s.12] gibi atiflanir.

- PDF: Qt'nin PDF modulu (QtPdf, PySide6 ile gelir) metin katmanini okur. Metin
  katmani olmayan taranmis PDF'ler simdilik okunamaz (NoTextError); ileride gorsel
  modelle okunacak.
- .txt / .md: metin TEXT_PAGE_LINES satirlik "sayfalara" bolunur; atif ve
  goruntuleyicide konum bu sayfa numarasidir.
- .docx (F68): paragraflar; sayfa sonlari (Word'un kaydettigi isaretler) korunur,
  yoksa ~VIRTUAL_PAGE_CHARS karakterlik sayfalar.
- .xlsx / .csv (F68): her calisma sayfasi bir "sayfa"; satirlar ilk satirdaki
  basliklarla 'Baslik: deger' olarak yazilir (sayfa basina en fazla SHEET_ROWS satir).
- .epub (F68): her bolum (okuma sirasi) bir "sayfa".
Word/Excel/EPUB zip icindeki XML/HTML'den okunur; ek kutuphane gerekmez.

Kaynak dosyalar SALT-OKUNUR.
"""
from __future__ import annotations

import csv
import html.parser
import io
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import qa
from app_core import save_json

KIND_SUFFIXES = {'pdf': ('.pdf',), 'text': ('.txt', '.md'), 'word': ('.docx',),
                 'sheet': ('.xlsx', '.csv'), 'epub': ('.epub',)}
SUFFIXES = tuple(suffix for suffixes in KIND_SUFFIXES.values() for suffix in suffixes)
TEXT_PAGE_LINES = 60
VIRTUAL_PAGE_CHARS = 3000
SHEET_ROWS = 5000
_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_PKG = '{http://schemas.openxmlformats.org/package/2006/relationships}'
_OPF = '{http://www.idpf.org/2007/opf}'
_CONTAINER = '{urn:oasis:names:tc:opendocument:xmlns:container}'
_BLOCKS = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote',
           'section', 'article', 'pre', 'table', 'ul', 'ol', 'dt', 'dd'}
PARAGRAPH_CHARS = 600
_SENTENCE = re.compile(r'(?<=[.!?…])\s+')


class NoTextError(ValueError):
    """Belgede okunabilir metin yok (ornegin taranmis PDF)."""


def kind_of(path):
    suffix = Path(path).suffix.lower()
    return next((kind for kind, suffixes in KIND_SUFFIXES.items() if suffix in suffixes), None)


def paragraphs(text):
    """Sayfa metnini paragraflara boler; cok uzun paragraflar cumle sinirindan bolunur."""
    blocks = re.split(r'\n\s*\n|\r\n\s*\r\n', str(text).replace('\r\n', '\n'))
    result = []
    for block in blocks:
        block = ' '.join(block.split())
        while len(block) > PARAGRAPH_CHARS:
            cut = max((match.end() for match in _SENTENCE.finditer(block, 0, PARAGRAPH_CHARS)),
                      default=0)
            if cut <= 0:
                cut = block.rfind(' ', 0, PARAGRAPH_CHARS)
            if cut <= 0:
                cut = PARAGRAPH_CHARS
            result.append(block[:cut].strip())
            block = block[cut:].strip()
        if block:
            result.append(block)
    return result


def pdf_pages(path):
    """PDF'in sayfa metinleri (QtPdf; arayuz disi thread'de de calisir)."""
    from PySide6.QtPdf import QPdfDocument
    document = QPdfDocument(None)
    try:
        status = document.load(str(path))
        if status != QPdfDocument.Error.None_:
            reason = {QPdfDocument.Error.IncorrectPassword: 'parola korumalı',
                      QPdfDocument.Error.UnsupportedSecurityScheme: 'desteklenmeyen şifreleme',
                      QPdfDocument.Error.InvalidFileFormat: 'geçersiz PDF',
                      QPdfDocument.Error.FileNotFound: 'dosya bulunamadı'}.get(status, status.name)
            raise ValueError(f'PDF açılamadı ({reason}): {Path(path).name}')
        return [document.getAllText(page).text() for page in range(document.pageCount())]
    finally:
        document.close()


def read_text(path):
    data = Path(path).read_bytes()
    for encoding in ('utf-8-sig', 'cp1254'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1')


def text_pages(path):
    lines = read_text(path).splitlines()
    return ['\n'.join(lines[start:start + TEXT_PAGE_LINES])
            for start in range(0, len(lines), TEXT_PAGE_LINES)] or ['']


def _virtual_pages(paragraph_list, size=VIRTUAL_PAGE_CHARS):
    """Sayfa bilgisi olmayan metni ~size karakterlik sayfalara boler (paragraf bolunmez)."""
    pages, current = [], []
    for paragraph in paragraph_list:
        if current and sum(len(item) + 2 for item in current) + len(paragraph) > size:
            pages.append('\n\n'.join(current))
            current = []
        current.append(paragraph)
    if current:
        pages.append('\n\n'.join(current))
    return pages or ['']


def word_pages(path):
    """.docx paragraflari; Word'un sayfa sonu isaretlerinden sayfalar."""
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read('word/document.xml'))
    pages, current = [[]], []
    for paragraph in root.iter(_W + 'p'):
        for node in paragraph.iter():
            if node.tag == _W + 't':
                current.append(node.text or '')
            elif node.tag == _W + 'tab':
                current.append('\t')
            elif ((node.tag == _W + 'br' and node.get(_W + 'type') == 'page')
                  or node.tag == _W + 'lastRenderedPageBreak'):
                if ''.join(current).strip():
                    pages[-1].append(''.join(current))
                current = []
                if pages[-1]:
                    pages.append([])
        if ''.join(current).strip():
            pages[-1].append(''.join(current))
        current = []
    pages = [page for page in pages if page]
    if len(pages) <= 1:  # sayfa isareti yok: sanal sayfalar
        return _virtual_pages([text for page in pages for text in page])
    return ['\n\n'.join(page) for page in pages]


def _column(reference):
    letters = re.match(r'[A-Z]+', reference or '')
    value = 0
    for letter in (letters.group(0) if letters else ''):
        value = value * 26 + ord(letter) - 64
    return value - 1


def _rows_text(name, rows):
    """Tablo satirlari -> 'Baslik: deger; ...' paragraflari (ilk dolu satir baslik)."""
    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if not rows:
        return f'{name}\n\n(boş sayfa)'
    header = [str(cell).strip() or f'Sütun {index + 1}' for index, cell in enumerate(rows[0])]
    lines = [f'{name} · sütunlar: ' + ', '.join(header)]
    for number, row in enumerate(rows[1:SHEET_ROWS + 1], 2):
        cells = [f'{header[index] if index < len(header) else f"Sütun {index + 1}"}: {value}'
                 for index, value in enumerate(row) if str(value).strip()]
        lines.append(f'Satır {number}: ' + '; '.join(cells))
    if len(rows) > SHEET_ROWS + 1:
        lines.append(f'(+{len(rows) - SHEET_ROWS - 1} satır daha; ilk {SHEET_ROWS} satır alındı)')
    return '\n\n'.join(lines)


def sheet_pages(path):
    """.xlsx calisma sayfalari ya da .csv: her sayfa bir 'sayfa'."""
    if Path(path).suffix.lower() == '.csv':
        text = read_text(path)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t|')
        except csv.Error:
            dialect = csv.excel
        return [_rows_text(Path(path).stem, list(csv.reader(io.StringIO(text), dialect)))]
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared = []
        if 'xl/sharedStrings.xml' in names:
            for item in ElementTree.fromstring(archive.read('xl/sharedStrings.xml')):
                shared.append(''.join(node.text or '' for node in item.iter(_S + 't')))
        targets = {}
        if 'xl/_rels/workbook.xml.rels' in names:
            for rel in ElementTree.fromstring(archive.read('xl/_rels/workbook.xml.rels')):
                target = rel.get('Target', '').lstrip('/')
                targets[rel.get('Id')] = target if target.startswith('xl/') else 'xl/' + target
        pages = []
        workbook = ElementTree.fromstring(archive.read('xl/workbook.xml'))
        for sheet in workbook.iter(_S + 'sheet'):
            target = targets.get(sheet.get(_REL + 'id'))
            if target not in names:
                continue
            rows = []
            for row in ElementTree.fromstring(archive.read(target)).iter(_S + 'row'):
                cells = {}
                for cell in row.iter(_S + 'c'):
                    kind, value = cell.get('t'), cell.find(_S + 'v')
                    if kind == 'inlineStr':
                        text = ''.join(node.text or '' for node in cell.iter(_S + 't'))
                    elif value is None:
                        continue
                    elif kind == 's':
                        index = int(value.text or 0)
                        text = shared[index] if index < len(shared) else ''
                    elif kind == 'b':
                        text = 'DOĞRU' if value.text == '1' else 'YANLIŞ'
                    else:
                        text = value.text or ''
                    cells[_column(cell.get('r')) if cell.get('r') else len(cells)] = text
                if cells:
                    rows.append([cells.get(index, '') for index in range(max(cells) + 1)])
            pages.append(_rows_text(sheet.get('name') or f'Sayfa{len(pages) + 1}', rows))
    return pages or ['']


class _HtmlText(html.parser.HTMLParser):
    """EPUB bolumu HTML'inden okunur metin (blok etiketlerinde paragraf)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.skip += 1
        elif tag in _BLOCKS:
            self.parts.append('\n\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head'):
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCKS:
            self.parts.append('\n\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(markup):
    parser = _HtmlText()
    parser.feed(markup)
    return re.sub(r'\n\s*\n+', '\n\n', ''.join(parser.parts)).strip()


def epub_pages(path):
    """EPUB bolumleri okuma sirasiyla (spine); her bolum bir 'sayfa'."""
    with zipfile.ZipFile(path) as archive:
        container = ElementTree.fromstring(archive.read('META-INF/container.xml'))
        rootfile = next(container.iter(_CONTAINER + 'rootfile')).get('full-path')
        package = ElementTree.fromstring(archive.read(rootfile))
        folder = posixpath.dirname(rootfile)
        manifest = {item.get('id'): item.get('href') for item in package.iter(_OPF + 'item')}
        pages = []
        for ref in package.iter(_OPF + 'itemref'):
            href = manifest.get(ref.get('idref'))
            if not href:
                continue
            name = posixpath.normpath(posixpath.join(folder, href.split('#')[0]))
            try:
                markup = archive.read(name).decode('utf-8', errors='replace')
            except KeyError:
                continue
            text = html_text(markup)
            if text:
                pages.append(text)
    return pages or ['']


PAGE_READERS = {'pdf': pdf_pages, 'text': text_pages, 'word': word_pages,
                'sheet': sheet_pages, 'epub': epub_pages}


def pages_of(path):
    """Belgenin sayfa metinleri (turune gore)."""
    kind = kind_of(path)
    if kind is None:
        raise ValueError('Desteklenmeyen belge türü: ' + Path(path).name)
    try:
        return PAGE_READERS[kind](path)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, StopIteration) as error:
        raise ValueError(f'Belge okunamadı ({type(error).__name__}): {Path(path).name}') from None


def extract(path):
    """(sayfa sayisi, segmentler). segment: {'start': sayfa, 'end': sayfa, 'text'}."""
    kind = kind_of(path)
    pages = pages_of(path)
    segments = [{'start': float(number), 'end': float(number), 'text': paragraph}
                for number, text in enumerate(pages, 1) for paragraph in paragraphs(text)]
    if not segments:
        raise NoTextError('Belgede okunabilir metin yok' + (
            ' (taranmış PDF olabilir; görsel okuma sonraki sürümde).' if kind == 'pdf' else '.'))
    return len(pages), segments


def load_session(path, base=None, log=print):
    """Belgenin metin oturumu: onbellekte varsa oradan, yoksa cikarir. (veri, onbellek yolu)."""
    path = Path(path)
    source = {'kind': kind_of(path)}
    cache = qa.cache_path(path, qa.source_key(source), base)
    cached = qa.load_cache(cache)
    if cached:
        return cached, cache
    pages, segments = extract(path)
    source['pages'] = pages
    data = {'version': qa.CACHE_VERSION, 'video': str(path), 'title': path.stem,
            'source': source, 'duration': float(pages), 'chapters': [],
            'segments': segments, 'sections': [], 'mode': '', 'overview': None}
    save_json(cache, data)
    log(f'Belge metni hazır: {pages} sayfa, {len(segments)} paragraf.')
    return data, cache
