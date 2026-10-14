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

KIND_SUFFIXES = {'pdf': ('.pdf',), 'text': ('.txt', '.md'),
                 'word': ('.docx', '.odt', '.rtf', '.doc'),
                 'sheet': ('.xlsx', '.csv', '.ods', '.xls'),
                 'slides': ('.pptx', '.odp', '.ppt'), 'epub': ('.epub',),
                 'html': ('.html', '.htm'),
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
_A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
_P = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
_ODF_TEXT = '{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'
_ODF_TABLE = '{urn:oasis:names:tc:opendocument:xmlns:table:1.0}'
_ODF_DRAW = '{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}'
_ODF_OFFICE = '{urn:oasis:names:tc:opendocument:xmlns:office:1.0}'
ODS_REPEAT_LIMIT = 50  # bos tekrar eden hucre/satirlar (sayfa sonuna kadar) atlanir
# Eski ikili Office bicimleri LibreOffice ile modern bicime cevrilip okunur.
LEGACY_TARGETS = {'.doc': 'docx', '.xls': 'xlsx', '.ppt': 'pptx'}
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


def _png(image, quality=-1):
    from PySide6.QtCore import QBuffer
    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, 'PNG', quality)
    return bytes(buffer.data())


class PdfRenderer:
    """PDF bir kez acilir, sayfalar sirayla cizilir (her sayfada yeniden yukleme yok)."""

    def __init__(self, path):
        from PySide6.QtPdf import QPdfDocument
        self.document = QPdfDocument(None)
        self.document.load(str(path))

    def png(self, page, gray=False):
        """Beyaz zeminli PNG (QtPdf seffaf cizer; model siyah gorur). `gray`: Tesseract icin
        gri tonlu ve az sikistirilmis; kodlama ~10 kat hizli."""
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QColor, QImage, QPainter
        size = self.document.pagePointSize(page)
        scale = RENDER_LONG_SIDE / max(size.width(), size.height(), 1.0)
        target = QSize(max(1, int(size.width() * scale)), max(1, int(size.height() * scale)))
        rendered = self.document.render(page, target)
        image = QImage(rendered.size(), QImage.Format_RGB32)
        image.fill(QColor('white'))
        painter = QPainter(image)
        painter.drawImage(0, 0, rendered)
        painter.end()
        if gray:
            return _png(image.convertToFormat(QImage.Format_Grayscale8), 90)
        return _png(image)

    def close(self):
        self.document.close()


def render_pdf_page(path, page):
    """PDF sayfasinin beyaz zeminli PNG goruntusu."""
    renderer = PdfRenderer(path)
    try:
        return renderer.png(page)
    finally:
        renderer.close()


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


def tesseract_path(cfg=None):
    """Tesseract programi: ayardaki yol, PATH, Program Files ya da uygulamadaki bin/tesseract."""
    import os
    import shutil
    from app_core import APP_DIR, EXE_SUFFIX
    configured = str((cfg or {}).get('tesseract_path', '')).strip()
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which('tesseract')
    if found:
        return found
    candidates = [APP_DIR / 'bin' / 'tesseract' / ('tesseract' + EXE_SUFFIX)]
    if os.name == 'nt':
        for root in (os.environ.get('ProgramFiles', r'C:\Program Files'),
                     os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                     os.environ.get('LOCALAPPDATA', '')):
            if root:
                candidates.append(Path(root) / 'Tesseract-OCR' / 'tesseract.exe')
                candidates.append(Path(root) / 'Programs' / 'Tesseract-OCR' / 'tesseract.exe')
    return next((str(item) for item in candidates if item.is_file()), None)


_PHRASE_LOOP = re.compile(r'(\S.{8,200}?)(?:\s*\1){3,}', re.DOTALL)


def trim_repetition(text, min_chars=25):
    """Gorsel modelin dongusunu keser: daha once gecen cumle (min_chars+) tekrar gelirse atilir.
    (temiz metin, atilan cumle sayisi). Tekrarsiz paragraflar oldugu gibi kalir."""
    # Cumle icinde donen ifade ("X'in yeni versiyonu olan X'in yeni versiyonu olan ..."): bir kez
    removed = 0

    def collapse(match):
        nonlocal removed
        removed += 1
        return match.group(1)
    text = _PHRASE_LOOP.sub(collapse, text)
    seen = set()
    kept = []
    for paragraph in re.split(r'\n\s*\n', text):
        sentences = re.split(r'(?<=[.!?…])\s+', ' '.join(paragraph.split()))
        fresh = []
        for sentence in sentences:
            key = sentence.casefold()
            if len(key) >= min_chars and key in seen:
                removed += 1
                continue
            seen.add(key)
            fresh.append(sentence)
        if len(fresh) == len(sentences):
            kept.append(paragraph)
        elif fresh:
            kept.append(' '.join(fresh))
    return '\n\n'.join(part for part in kept if part.strip()), removed


def ocr_engine(cfg):
    """Taranmis sayfalar icin kullanilacak motor: 'tesseract' ya da 'vision'."""
    engine = cfg.get('ocr_engine', 'auto')
    if engine == 'auto':
        return 'tesseract' if tesseract_path(cfg) else 'vision'
    return engine


def tesseract_workers():
    """Ayni anda calisan Tesseract sayisi: bir-iki cekirdek arayuze kalir, en fazla 8."""
    import os
    return max(1, min(8, (os.cpu_count() or 2) - 2))


def tesseract_reader(cfg, log=print):
    """(png) -> metin; Tesseract yoksa anlasilir hata. Turkce dil verisi yoksa 'eng'e duser."""
    import os
    import subprocess
    import tempfile
    exe = tesseract_path(cfg)
    if exe is None:
        raise ValueError('Tesseract bulunamadı: kurun (Windows: UB Mannheim Tesseract, Türkçe dil '
                         'paketiyle; Linux: tesseract-ocr tesseract-ocr-tur) ya da Ayarlar\'da '
                         'yolunu gösterin; veya OCR motoru olarak görü modelini seçin.')
    hide = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if os_name() == 'nt' else {}
    wanted = str(cfg.get('tesseract_lang', 'tur+eng')).strip() or 'tur+eng'
    try:
        listed = subprocess.run([exe, '--list-langs'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=60, **hide)
        available = set((listed.stdout or '').split())
    except (OSError, subprocess.SubprocessError):
        available = set()
    langs = [lang for lang in wanted.split('+') if not available or lang in available]
    if not langs:
        log(f'UYARI: Tesseract dil verisi yok ({wanted}); eng kullanılıyor.')
        langs = ['eng']
    elif len(langs) < len(wanted.split('+')):
        log(f'UYARI: Tesseract\'ta eksik dil verisi; kullanılan: {"+".join(langs)}')

    # Sayfalar paralel okunur (bkz. _ocr_pages); her Tesseract tek cekirdek kullanir,
    # yoksa kendi is parcaciklari birbirini yavaslatir.
    env = dict(os.environ, OMP_THREAD_LIMIT='1')

    def read(png):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'sayfa.png'
            image.write_bytes(png)
            result = subprocess.run([exe, str(image), 'stdout', '-l', '+'.join(langs),
                                     '--psm', '3'], capture_output=True, timeout=600,
                                    env=env, **hide)
        if result.returncode != 0:
            raise ValueError('Tesseract hatası: '
                             + result.stderr.decode('utf-8', 'replace').strip()[:200])
        return result.stdout.decode('utf-8', 'replace')
    return read


def scanned_pages(path):
    """PDF'te metin katmani olmayan (OCR gereken) sayfa numaralari (1'den baslar)."""
    return [number for number, text in enumerate(pdf_pages(path), 1)
            if len(' '.join(text.split())) < OCR_MIN_CHARS]


def needs_vision(path):
    """Gorsel model gerekiyor mu: gorsel dosyasi ya da taranmis sayfasi olan PDF."""
    kind = kind_of(path)
    return kind == 'image' or (kind == 'pdf' and bool(scanned_pages(path)))


def pptx_pages(path):
    """.pptx slaytlari sunum sirasiyla; her slayt bir 'sayfa' (paragraf = a:p)."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        rels = {}
        if 'ppt/_rels/presentation.xml.rels' in names:
            for rel in ElementTree.fromstring(archive.read('ppt/_rels/presentation.xml.rels')):
                target = rel.get('Target', '').lstrip('/')
                rels[rel.get('Id')] = target if target.startswith('ppt/') else 'ppt/' + target
        order = [rels.get(item.get(_REL + 'id')) for item in ElementTree.fromstring(
            archive.read('ppt/presentation.xml')).iter(_P + 'sldId')]
        pages = []
        for target in order:
            if target not in names:
                continue
            slide = ElementTree.fromstring(archive.read(target))
            lines = [''.join(node.text or '' for node in paragraph.iter(_A + 't'))
                     for paragraph in slide.iter(_A + 'p')]
            pages.append('\n\n'.join(line for line in lines if line.strip()))
    return pages or ['']


def _odf_text(element):
    """OpenDocument metin ogesinin duz metni (bosluk/sekme/satir sonu ogeleri dahil)."""
    parts = [element.text or '']
    for child in element:
        if child.tag == _ODF_TEXT + 's':
            parts.append(' ' * int(child.get(_ODF_TEXT + 'c', '1')))
        elif child.tag == _ODF_TEXT + 'tab':
            parts.append('\t')
        elif child.tag == _ODF_TEXT + 'line-break':
            parts.append('\n')
        else:
            parts.append(_odf_text(child))
        parts.append(child.tail or '')
    return ''.join(parts)


def _odf_content(path):
    with zipfile.ZipFile(path) as archive:
        return ElementTree.fromstring(archive.read('content.xml'))


def odt_pages(path):
    """.odt baslik ve paragraflari; sayfa bilgisi olmadigi icin sanal sayfalar."""
    body = _odf_content(path)
    paragraphs_list = [_odf_text(node) for node in body.iter()
                       if node.tag in (_ODF_TEXT + 'p', _ODF_TEXT + 'h')]
    return _virtual_pages([text for text in paragraphs_list if text.strip()])


def ods_pages(path):
    """.ods calisma sayfalari (Excel ile ayni satir bicimi)."""
    pages = []
    for table in _odf_content(path).iter(_ODF_TABLE + 'table'):
        rows = []
        for row in table.iter(_ODF_TABLE + 'table-row'):
            cells = []
            for cell in row:
                if cell.tag not in (_ODF_TABLE + 'table-cell', _ODF_TABLE + 'covered-table-cell'):
                    continue
                value = '\n'.join(_odf_text(node) for node in cell.iter(_ODF_TEXT + 'p'))
                repeat = int(cell.get(_ODF_TABLE + 'number-columns-repeated', '1'))
                cells.extend([value] * min(repeat, ODS_REPEAT_LIMIT if value else 1))
            while cells and not cells[-1].strip():
                cells.pop()
            repeat = int(row.get(_ODF_TABLE + 'number-rows-repeated', '1'))
            rows.extend([cells] * (min(repeat, ODS_REPEAT_LIMIT) if cells else 1))
        pages.append(_rows_text(table.get(_ODF_TABLE + 'name') or f'Sayfa{len(pages) + 1}', rows))
    return pages or ['']


def odp_pages(path):
    """.odp slaytlari (draw:page); her slayt bir 'sayfa'."""
    pages = []
    for slide in _odf_content(path).iter(_ODF_DRAW + 'page'):
        lines = [_odf_text(node) for node in slide.iter()
                 if node.tag in (_ODF_TEXT + 'p', _ODF_TEXT + 'h')]
        pages.append('\n\n'.join(line for line in lines if line.strip()))
    return pages or ['']


_RTF_TOKEN = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([^\\{}]+)",
                        re.S)
_RTF_SKIP = {'fonttbl', 'colortbl', 'stylesheet', 'info', 'pict', 'header', 'footer',
             'headerl', 'headerr', 'footerl', 'footerr', 'listtable', 'listoverridetable',
             'themedata', 'colorschememapping', 'datastore', 'latentstyles', 'xmlnstbl',
             'rsidtbl', 'generator', 'object', 'fldinst'}


def rtf_text(data):
    """RTF -> duz metin (denetim kelimeleri atilir; \\'xx ve \\uN karakterleri cozulur)."""
    codepage = re.search(r'\\ansicpg(\d+)', data)
    encoding = f'cp{codepage.group(1)}' if codepage else 'cp1254'
    out, stack, skip, uc_skip = [], [], False, 0
    for word, number, hexcode, symbol, brace, plain in _RTF_TOKEN.findall(data):
        if brace == '{':
            stack.append(skip)
        elif brace == '}':
            skip = stack.pop() if stack else False
        elif skip:
            continue
        elif word:
            if word in _RTF_SKIP:
                skip = True
            elif word in ('par', 'line', 'sect', 'page', 'row'):
                out.append('\n\n' if word != 'line' else '\n')
            elif word in ('tab', 'cell'):
                out.append('\t')
            elif word == 'u' and number:
                value = int(number)
                out.append(chr(value + 65536 if value < 0 else value))
                uc_skip = 1
        elif hexcode:
            if uc_skip:
                uc_skip -= 1
                continue
            try:
                out.append(bytes([int(hexcode, 16)]).decode(encoding))
            except (UnicodeDecodeError, LookupError):
                out.append(bytes([int(hexcode, 16)]).decode('latin-1'))
        elif symbol:
            if symbol == '*':
                skip = True
            elif symbol in '\\{}':
                out.append(symbol)
            elif symbol == '~':
                out.append(' ')
        elif plain:
            plain = plain.replace('\r', '').replace('\n', '')
            out.append(plain[uc_skip:])  # \uN'den sonraki yedek karakter atlanir
            uc_skip = 0
    return re.sub(r'\n\s*\n+', '\n\n', ''.join(out)).strip()


def rtf_pages(path):
    text = rtf_text(Path(path).read_bytes().decode('latin-1'))
    return _virtual_pages([part for part in text.split('\n\n') if part.strip()])


def html_pages(path):
    text = html_text(read_text(path))
    return _virtual_pages([part for part in text.split('\n\n') if part.strip()])


def office_converter():
    """LibreOffice (soffice) yolu ya da None (eski .doc/.xls/.ppt icin)."""
    import os
    import shutil
    found = shutil.which('soffice') or shutil.which('libreoffice')
    if found:
        return found
    if os.name == 'nt':
        for root in (os.environ.get('ProgramFiles', r'C:\Program Files'),
                     os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')):
            candidate = Path(root) / 'LibreOffice' / 'program' / 'soffice.exe'
            if candidate.is_file():
                return str(candidate)
    return None


def convert_legacy(path, folder=None):
    """Eski Office dosyasini LibreOffice ile modern bicime cevirir (onbellekli kopya)."""
    import subprocess
    import tempfile
    path = Path(path)
    target = LEGACY_TARGETS[path.suffix.lower()]
    soffice = office_converter()
    if soffice is None:
        raise ValueError(f'Eski Office biçimi ({path.suffix}): okumak için LibreOffice kurun ya da '
                         f'dosyayı .{target} olarak kaydedin.')
    folder = Path(folder or (qa.work_dir() / 'converted'))
    stamp = qa.cache_path(path, 'converted').stem.split('.')[-1]
    output = folder / f'{path.stem}.{stamp}.{target}'
    if output.is_file():
        return output
    with tempfile.TemporaryDirectory() as temp:
        kwargs = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if os_name() == 'nt' else {}
        result = subprocess.run([soffice, '--headless', '--convert-to', target, '--outdir', temp,
                                 str(path)], capture_output=True, text=True, timeout=300, **kwargs)
        produced = Path(temp) / f'{path.stem}.{target}'
        if result.returncode != 0 or not produced.is_file():
            raise ValueError(f'LibreOffice dönüştüremedi: {path.name} '
                             + (result.stderr or result.stdout or '').strip()[:200])
        folder.mkdir(parents=True, exist_ok=True)
        output.write_bytes(produced.read_bytes())
    return output


def os_name():
    import os
    return os.name


def legacy_pages(path):
    converted = convert_legacy(path)
    return SUFFIX_READERS[converted.suffix.lower()](converted)


SUFFIX_READERS = {'.pdf': pdf_pages, '.txt': text_pages, '.md': text_pages,
                  '.docx': word_pages, '.odt': odt_pages, '.rtf': rtf_pages,
                  '.xlsx': sheet_pages, '.csv': sheet_pages, '.ods': ods_pages,
                  '.pptx': pptx_pages, '.odp': odp_pages, '.epub': epub_pages,
                  '.html': html_pages, '.htm': html_pages,
                  '.doc': legacy_pages, '.xls': legacy_pages, '.ppt': legacy_pages}


def pages_of(path):
    """Belgenin sayfa metinleri (turune gore)."""
    kind = kind_of(path)
    if kind is None:
        raise ValueError('Desteklenmeyen belge türü: ' + Path(path).name)
    try:
        return SUFFIX_READERS[Path(path).suffix.lower()](path)
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
        _ocr_pages(path, missing, ocr, done, progress, cancelled)
        for number in missing:
            pages[number - 1] = done[str(number)]
            read += 1
    segments = _segments(pages)
    segments = [{'start': float(number), 'end': float(number), 'text': paragraph}
                for number, text in enumerate(pages, 1) for paragraph in paragraphs(text)]
    if not segments:
        raise NoTextError('Belgede okunabilir metin yok' + (
            ' (taranmış PDF olabilir; görü modeliyle okunmadı).' if kind == 'pdf' else '.'))
    return len(pages), segments, read


def _ocr_pages(path, missing, ocr, done, progress=None, cancelled=None):
    """Eksik sayfalari `ocr` ile okuyup `done`a yazar. Sayfalar bu is parcaciginda cizilir,
    okuma `ocr.workers` kadar paralel yapilir (Tesseract: cekirdek sayisi; gorsel model: 1).
    Durdurulunca baslamamis sayfalar iptal edilir, okunanlar `done`da kalir."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    workers = max(1, int(getattr(ocr, 'workers', 1)))
    gray = bool(getattr(ocr, 'grayscale', False))
    total = len(missing)
    finished = sum(1 for number in missing if str(number) in done)
    todo = iter([number for number in missing if str(number) not in done])
    if progress and finished:
        progress(finished, total)
    renderer = PdfRenderer(path) if finished < total else None
    pool = ThreadPoolExecutor(workers)
    running = {}
    stopped = False
    try:
        while True:
            stopped = stopped or bool(cancelled and cancelled())
            while not stopped and len(running) < workers * 2:
                number = next(todo, None)
                if number is None:
                    break
                running[pool.submit(ocr, renderer.png(number - 1, gray), OCR_PROMPT)] = number
            if stopped:
                for future in [item for item in running if item.cancel()]:
                    del running[future]
            if not running:
                break
            completed, _pending = wait(running, return_when=FIRST_COMPLETED)
            for future in completed:
                number = running.pop(future)
                done[str(number)] = future.result()
                finished += 1
                if progress:
                    progress(finished, total)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        if renderer is not None:
            renderer.close()
    if stopped:
        from app_core import GracefulStop
        raise GracefulStop('Görsel okuma durduruldu; okunan sayfalar kaydedildi.')


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
