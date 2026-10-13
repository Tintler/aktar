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
- Gorsel okuma (F69): metin katmani olmayan PDF sayfalari goruntuye cevrilip, gorsel
  dosyalari (jpg/png/webp/bmp/gif) dogrudan gorsel modele (LM Studio) verilir. Sayfa
  sonuclari ayri bir onbellege yazilir; uzun taramada kesilirse kaldigi sayfadan surer.
Word/Excel/EPUB zip icindeki XML/HTML'den okunur; ek kutuphane gerekmez.

Kaynak dosyalar SALT-OKUNUR.
"""
from __future__ import annotations

import csv
import html.parser
import json
import io
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import qa
from app_core import save_json

KIND_SUFFIXES = {'pdf': ('.pdf',), 'text': ('.txt', '.md'), 'word': ('.docx',),
                 'sheet': ('.xlsx', '.csv'), 'epub': ('.epub',),
                 'image': ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif')}
IMAGE_SUFFIXES = KIND_SUFFIXES['image']
OCR_MIN_CHARS = 20      # bundan az metinli PDF sayfasi taranmis sayilir
RENDER_LONG_SIDE = 2000  # gorsel modele giden goruntunun uzun kenari (piksel)
OCR_PROMPT = ('Bu bir belge sayfasının görüntüsü. Sayfadaki tüm metni olduğu gibi, okuma '
              'sırasıyla yaz; paragrafları boş satırla ayır, tabloları satır satır yaz. '
              'Açıklama ya da yorum ekleme. Sayfada metin yoksa hiçbir şey yazma.')
IMAGE_PROMPT = ('Bu görseli Türkçe olarak 2-4 cümleyle tarif et (ne görülüyor, önemli '
                'ayrıntılar). Ardından görselde okunabilen tüm yazıları aynen yaz. Biçim:\n'
                'AÇIKLAMA: <tarif>\n\nYAZI: <görseldeki yazılar; yoksa "yok">')
SUFFIXES = tuple(suffix for kind, suffixes in KIND_SUFFIXES.items() if kind != 'image'
                 for suffix in suffixes)  # belgeler; gorseller kutuphanede ayri tur
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


def _png(image):
    from PySide6.QtCore import QBuffer
    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(buffer.data())


def render_pdf_page(path, page):
    """PDF sayfasinin beyaz zeminli PNG goruntusu (QtPdf seffaf cizer; model siyah gorur)."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtPdf import QPdfDocument
    document = QPdfDocument(None)
    try:
        document.load(str(path))
        size = document.pagePointSize(page)
        scale = RENDER_LONG_SIDE / max(size.width(), size.height(), 1.0)
        target = QSize(max(1, int(size.width() * scale)), max(1, int(size.height() * scale)))
        rendered = document.render(page, target)
    finally:
        document.close()
    image = QImage(rendered.size(), QImage.Format_RGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    painter.drawImage(0, 0, rendered)
    painter.end()
    return _png(image)


def image_bytes(path):
    """Gorsel dosyasi -> modele gidecek PNG (uzun kenar en fazla RENDER_LONG_SIDE)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    image = QImage(str(path))
    if image.isNull():
        raise ValueError('Görsel açılamadı: ' + Path(path).name)
    if max(image.width(), image.height()) > RENDER_LONG_SIDE:
        image = image.scaled(RENDER_LONG_SIDE, RENDER_LONG_SIDE, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
    flat = QImage(image.size(), QImage.Format_RGB32)
    flat.fill(QColor('white'))
    painter = QPainter(flat)
    painter.drawImage(0, 0, image)
    painter.end()
    return _png(flat)


def scanned_pages(path):
    """PDF'te metin katmani olmayan (OCR gereken) sayfa numaralari (1'den baslar)."""
    return [number for number, text in enumerate(pdf_pages(path), 1)
            if len(' '.join(text.split())) < OCR_MIN_CHARS]


def needs_vision(path):
    """Gorsel model gerekiyor mu: gorsel dosyasi ya da taranmis sayfasi olan PDF."""
    kind = kind_of(path)
    return kind == 'image' or (kind == 'pdf' and bool(scanned_pages(path)))


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


def extract(path, ocr=None, progress=None, cancelled=None, done=None):
    """(sayfa sayisi, segmentler, gorselle okunan sayfa sayisi).

    segment: {'start': sayfa, 'end': sayfa, 'text'}. `ocr(png, prompt) -> metin`
    verilirse metinsiz PDF sayfalari ve gorseller okunur; `done` ({sayfa: metin})
    daha once okunan sayfalari tasir ve her yeni sayfadan sonra guncellenir.
    """
    kind = kind_of(path)
    if kind == 'image':
        if ocr is None:
            raise NoTextError('Görsel, görü modeliyle okunmadı.')
        pages = [ocr(image_bytes(path), IMAGE_PROMPT)]
        if progress:
            progress(1, 1)
        return 1, _segments(pages), 1
    pages = pages_of(path)
    read = 0
    if kind == 'pdf' and ocr is not None:
        missing = [number for number, text in enumerate(pages, 1)
                   if len(' '.join(text.split())) < OCR_MIN_CHARS]
        done = {} if done is None else done
        for index, number in enumerate(missing, 1):
            if cancelled and cancelled():
                from app_core import GracefulStop
                raise GracefulStop('Görsel okuma durduruldu; okunan sayfalar kaydedildi.')
            if str(number) not in done:
                done[str(number)] = ocr(render_pdf_page(path, number - 1), OCR_PROMPT)
            pages[number - 1] = done[str(number)]
            read += 1
            if progress:
                progress(index, len(missing))
    segments = _segments(pages)
    segments = [{'start': float(number), 'end': float(number), 'text': paragraph}
                for number, text in enumerate(pages, 1) for paragraph in paragraphs(text)]
    if not segments:
        raise NoTextError('Belgede okunabilir metin yok' + (
            ' (taranmış PDF olabilir; görü modeliyle okunmadı).' if kind == 'pdf' else '.'))
    return len(pages), segments, read


def _segments(pages):
    return [{'start': float(number), 'end': float(number), 'text': paragraph}
            for number, text in enumerate(pages, 1) for paragraph in paragraphs(text)]


def load_session(path, base=None, log=print, ocr=None, progress=None, cancelled=None):
    """Belgenin metin oturumu: onbellekte varsa oradan, yoksa cikarir. (veri, onbellek yolu).

    `ocr` verilirse taranmis sayfalar/gorseller okunur; sayfa sonuclari ayri onbellekte
    (kesilirse kaldigi sayfadan devam)."""
    path = Path(path)
    source = {'kind': kind_of(path)}
    cache = qa.cache_path(path, qa.source_key(source), base)
    cached = qa.load_cache(cache)
    if cached:
        return cached, cache
    partial_path = qa.cache_path(path, 'ocr-pages', base).with_suffix('.ocr')
    try:
        partial = json.loads(partial_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        partial = {}

    class Pages(dict):  # her yeni sayfa diske yazilir
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            save_json(partial_path, dict(self))

    done = Pages(partial)
    pages, segments, read = extract(path, ocr, progress, cancelled, done)
    source['pages'] = pages
    if read:
        source['vision_pages'] = read
    if ocr is None and source['kind'] == 'pdf':
        unread = len(scanned_pages(path))
        if unread:  # karisik PDF: metinli sayfalar kullanilir, taranmislar sonra okunur
            source['unread_pages'] = unread
    data = {'version': qa.CACHE_VERSION, 'video': str(path), 'title': path.stem,
            'source': source, 'duration': float(pages), 'chapters': [],
            'segments': segments, 'sections': [], 'mode': '', 'overview': None}
    save_json(cache, data)
    try:
        partial_path.unlink()
    except OSError:
        pass
    log(f'Belge metni hazır: {pages} sayfa, {len(segments)} paragraf'
        + (f' ({read} sayfa görü modeliyle okundu).' if read else '.'))
    return data, cache
