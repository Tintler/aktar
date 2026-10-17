"""Okuyucuda kitap ici arama (F147): kelime ya da cumle tum bolumlerde aranir (Calibre'deki gibi).

Buyuk/kucuk harf ve Turkce I/ı/İ/i farki gozetilmez; sorgudaki bosluklar metindeki her bosluk dizisine
(satir sonu dahil) uyar. Sonuc her eslesme icin bolum, bolumdeki kacinci eslesme oldugu ve cevresindeki
metindir; arayuz bolumu acip ayni sirada eslesmeyi vurgular (web/src/lib/booksearch.js ayni katlamayi
kullanir). Kaynak kitap SALT-OKUNUR.
"""
from __future__ import annotations

import re
import zipfile

LIMIT = 500        # en fazla eslesme
CONTEXT = 60       # eslesmenin iki yanindaki metin (karakter)
_FOLD = {'İ': 'i', 'I': 'i', 'ı': 'i'}


def fold(text):
    """Harf harf katlama (uzunluk degismez, konumlar ozgun metinle ayni kalir)."""
    result = []
    for char in str(text):
        folded = _FOLD.get(char)
        if folded is None:
            lower = char.lower()
            folded = lower if len(lower) == 1 else char
        result.append(folded)
    return ''.join(result)


def pattern(query):
    """Sorgu -> katlanmis metinde aranacak duzenli ifade (None: bos sorgu)."""
    words = fold(query).split()
    if not words:
        return None
    return re.compile(r'\s+'.join(re.escape(word) for word in words))


def section_texts(book):
    """book_reader.EpubBook bolumlerinin duz metni (documents.html_text ile; okuyucunun sirasiyla)."""
    import documents
    from epub_import import decode_document
    with zipfile.ZipFile(book.path) as archive:
        for section in book.sections:
            yield documents.html_text(decode_document(archive.read(section['path']), section['path']))


def search(book, query, limit=LIMIT):
    """{'results': [{section, title, index, before, match, after}], 'total', 'more'}."""
    found = pattern(query)
    results, total = [], 0
    if found is None:
        return {'results': results, 'total': 0, 'more': False}
    for number, text in enumerate(section_texts(book)):
        folded = fold(text)
        for index, match in enumerate(found.finditer(folded)):
            total += 1
            if len(results) >= limit:
                continue
            start, end = match.span()
            before = ' '.join(text[max(0, start - CONTEXT):start].split())
            after = ' '.join(text[end:end + CONTEXT].split())
            results.append({'section': number, 'title': book.section_title(number), 'index': index,
                            'before': ('…' if start > CONTEXT else '') + before,
                            'match': ' '.join(text[start:end].split()),
                            'after': after + ('…' if end + CONTEXT < len(text) else '')})
    return {'results': results, 'total': total, 'more': total > len(results)}
