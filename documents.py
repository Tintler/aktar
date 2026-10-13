"""Belge dosyalari (F64): PDF ve duz metin -> sayfa numarali metin oturumu.

Belgeler videolarla ayni hatta girer: metin `qa` onbellegine bir oturum olarak
yazilir (segment konumu = sayfa numarasi), sonra indekslenir ve koleksiyon
sohbetinde [V3 s.12] gibi atiflanir.

- PDF: Qt'nin PDF modulu (QtPdf, PySide6 ile gelir) metin katmanini okur. Metin
  katmani olmayan taranmis PDF'ler simdilik okunamaz (NoTextError); ileride gorsel
  modelle okunacak.
- .txt / .md: metin TEXT_PAGE_LINES satirlik "sayfalara" bolunur; atif ve
  goruntuleyicide konum bu sayfa numarasidir.

Kaynak dosyalar SALT-OKUNUR.
"""
from __future__ import annotations

import re
from pathlib import Path

import qa
from app_core import save_json

PDF_SUFFIXES = ('.pdf',)
TEXT_SUFFIXES = ('.txt', '.md')
SUFFIXES = PDF_SUFFIXES + TEXT_SUFFIXES
TEXT_PAGE_LINES = 60
PARAGRAPH_CHARS = 600
_SENTENCE = re.compile(r'(?<=[.!?…])\s+')


class NoTextError(ValueError):
    """Belgede okunabilir metin yok (ornegin taranmis PDF)."""


def kind_of(path):
    suffix = Path(path).suffix.lower()
    return 'pdf' if suffix in PDF_SUFFIXES else 'text' if suffix in TEXT_SUFFIXES else None


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


def extract(path):
    """(sayfa sayisi, segmentler). segment: {'start': sayfa, 'end': sayfa, 'text'}."""
    kind = kind_of(path)
    if kind is None:
        raise ValueError('Desteklenmeyen belge türü: ' + Path(path).name)
    pages = pdf_pages(path) if kind == 'pdf' else text_pages(path)
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
