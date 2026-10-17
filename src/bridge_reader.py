"""Okuma sayfasinin arka ucu (Bridge'e karisan sinif); Cevirgec bridge.py'nin okuma bolumu.

Kisisel EPUB kitapligi (book_reader.Library, APP_DIR/book_library.json): kitap ekleme/kaldirma,
kapak, bolum cizimi, okuma konumu ve yer imleri. Aktar'in Kutuphane'siyle (bridge_library)
karismasin diye kitaplik metotlari `shelf_`, okuyucu metotlari `reader_` onekli; olay 'shelf'.

F146 kitapla sohbet (`reader_chat_*`, olay 'reader_chat'): okunan kitap Dosya incele'nin belge
sohbetiyle (bridge_document) hazirlanir; sayfa s.N okuyucunun N. bolumudur (documents.epub_pages).
"Okudugum yere kadar" secilirse sonraki bolumler modele hic gitmez.
"""
from __future__ import annotations

from pathlib import Path
import re
import webbrowser
import zipfile

import book_core
from book_reader import Library

BOOK_GREETING = ('Bu kitaba soru sorun: "3. bölümde ne oldu?", "X kimdir?" gibi. Cevaptaki bölüm atfına '
                 'tıklayınca kitap o bölüme gider.')
TOC_CHARS = 4000   # modele verilen icindekiler listesinin en fazla uzunlugu
FOCUS_LIMIT = 2    # sorunun adini verdigi en fazla bolum
_CHAPTER_WORDS = r'(?:bolum|bolumu|bolumde|bolumun|kisim|kisimda|chapter|part|book|kitap)'
_ROMAN = ['', 'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x', 'xi', 'xii', 'xiii', 'xiv', 'xv', 'xvi',
          'xvii', 'xviii', 'xix', 'xx']


def _fold(text):
    """Eslestirme icin: Turkce ve Ingilizce harfler ayni bicime (ı/I/İ -> i, ö -> o ...)."""
    text = str(text).replace('İ', 'i').casefold().replace('ı', 'i')
    for a, b in (('ö', 'o'), ('ü', 'u'), ('ş', 's'), ('ç', 'c'), ('ğ', 'g'), ('â', 'a'), ('î', 'i'), ('û', 'u')):
        text = text.replace(a, b)
    return ' '.join(re.sub(r'[^\w.]+', ' ', text).split())


def focus_sections(question, toc):
    """F146: sorunun adini verdigi bolumler (0'dan bolum numaralari): icindekiler basligi soruda geciyorsa
    ya da "3. bolum" / "chapter 3" / "bolum III" denmisse. En fazla FOCUS_LIMIT."""
    asked = _fold(question)
    found = []

    def add(section):
        if section not in found and len(found) < FOCUS_LIMIT:
            found.append(section)

    for entry in sorted(toc, key=lambda item: -len(item['title'])):   # uzun baslik once (ozgul)
        title = _fold(entry['title']).strip('. ')
        if len(title) >= 4 and re.search(r'(?<!\w)' + re.escape(title) + r'(?!\w)', asked):
            add(entry['section'])
    # "3. bolum", "3 uncu bolum" (3'uncu), "bolum 3", "chapter 3"; _fold kesme isaretini bosluga cevirir
    numbers = [int(a or b) for a, b in re.findall(
        r'\b(\d{1,3})\.?\s*(?:[a-z]{2,4}\s+)?' + _CHAPTER_WORDS + r'\b|\b' + _CHAPTER_WORDS + r'\s+(\d{1,3})\b',
        asked)]
    for number in numbers:
        roman = _ROMAN[number] if number < len(_ROMAN) else ''
        named = re.compile(r'^(?:' + _CHAPTER_WORDS + r'\s+)?(?:' + str(number) + (r'|' + roman if roman else '')
                           + r')\b')
        match = next((entry['section'] for entry in toc if named.search(_fold(entry['title']))), None)
        if match is None:
            top = [entry for entry in toc if entry['depth'] == 0]
            match = top[number - 1]['section'] if 0 < number <= len(top) else None
        if match is not None:
            add(match)
    return found


def _error(error):
    return {'error': str(error)}


class ReaderMixin:
    def _shelf(self):
        directory = Path(book_core.APP_DIR)
        if getattr(self, '_shelf_cache', None) is None or self._shelf_cache.directory != directory:
            self._shelf_cache = Library(directory)
        return self._shelf_cache

    def _reading(self, action, *args):
        try:
            return action(*args)
        except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
            return _error(error)

    def shelf_list(self):
        return self._reading(self._shelf().list)

    def shelf_add(self, paths=None):
        """EPUB ekler (yol verilmezse coklu secim penceresi acilir)."""
        if paths is None:
            paths = self._dialog('open_files', 'Kitaplığa EPUB ekle', ('EPUB (*.epub)',))
            if not paths:
                return None
        result = self._reading(self._shelf().add, list(paths))
        if 'error' not in result:
            result['books'] = self._shelf().list()
            self._emit('shelf', result)
        return result

    def shelf_remove(self, book_id):
        return self._reading(lambda: (self._shelf().remove(book_id), self._shelf().list())[1])

    def shelf_cover(self, book_id):
        return self._reading(self._shelf().cover, book_id)

    def reader_open(self, book_id):
        return self._reading(self._shelf().open, book_id)

    def reader_section(self, book_id, number):
        return self._reading(self._shelf().section, book_id, number)

    def reader_save_position(self, book_id, section, offset):
        return self._reading(self._shelf().save_position, book_id, section, offset)

    def reader_add_bookmark(self, book_id, section, offset, label):
        return self._reading(self._shelf().add_bookmark, book_id, section, offset, label)

    def reader_remove_bookmark(self, book_id, bookmark_id):
        return self._reading(self._shelf().remove_bookmark, book_id, bookmark_id)

    def reader_open_link(self, url):
        """Kitaptaki http(s)/mailto baglantisini sistem tarayicisinda acar."""
        if not re.match(r'^(?:https?://|mailto:)', str(url), re.I):
            return {'error': 'Yalnızca web ve e-posta bağlantıları açılabilir.'}
        webbrowser.open(str(url))
        return True

    # ------------------------------------------------------------------ kitapla sohbet (F146)
    def _push_book_chat(self, doc):
        if doc is getattr(self, '_book_chat', None):
            self._emit('reader_chat', {'book': self._book_chat_id, 'chat': self._doc_chat(doc)})

    def reader_chat_open(self, book_id):
        """Okuyucudaki kitabin sohbetini acar (ayni kitapsa korunur); kitap arka planda hazirlanir."""
        from bridge_document import DocumentSession
        try:
            entry, _book = self._shelf()._book(book_id)
        except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
            return _error(error)
        path = Path(entry['path'])
        current = getattr(self, '_book_chat', None)
        if current is None or current.path != path:
            if current is not None:
                current.cancelled.set()
            self._book_chat = DocumentSession(path, BOOK_GREETING)
            self._book_chat.note = 'Kitap hazırlanıyor…'
            self._book_chat_id = book_id
            self._start_doc_prepare(self._book_chat, self._push_book_chat)
        return {'book': book_id, 'chat': self._doc_chat(self._book_chat)}

    def _book_toc(self, book_id, until=None):
        """Modele icindekiler: 's.N = baslik' satirlari (sinir varsa yalnizca okunan kisim)."""
        try:
            _entry, book = self._shelf()._book(book_id)
        except (ValueError, OSError, KeyError, zipfile.BadZipFile):
            return ''
        lines, seen = [], set()
        for item in book.toc:
            if until is not None and item['section'] > until:
                break
            title = ' '.join(str(item['title']).split())
            if title and (item['section'], title) not in seen:
                seen.add((item['section'], title))
                lines.append(f'{"  " * item["depth"]}s.{item["section"] + 1} = {title}')
        text = '\n'.join(lines)
        if len(text) > TOC_CHARS:
            text = text[:TOC_CHARS].rsplit('\n', 1)[0] + '\n…'
        return text

    def reader_chat_ask(self, question, think=None, template=None, until=None):
        """Kitaba soru. `until`: okunan son bolum (0'dan; None: tum kitap) -- sonrasi baglama girmez."""
        doc = getattr(self, '_book_chat', None)
        if doc is None:
            return None
        book_id = self._book_chat_id
        until = None if until in (None, '') else max(0, int(until))
        toc = self._book_toc(book_id, until)
        extra = ('This document is a book; call it "kitap" (never video or document). Each page s.N is section N '
                 'of the book in reading order; cite with s.N as usual. When the user names a chapter ("chapter 3", "3. bölüm"), find it by its title in the '
                 'table of contents below.')
        if toc:
            extra += '\nTABLE OF CONTENTS:\n' + toc
        if until is not None:
            extra += (f'\nThe user has read up to s.{until + 1}. Never reveal or hint at anything that happens '
                      'after that point; if the answer is only later in the book, say so without details.')

        try:
            focus = focus_sections(question, self._shelf()._book(book_id)[1].toc)
        except (ValueError, OSError, KeyError, zipfile.BadZipFile):
            focus = []

        def limit():
            doc.session.page_limit = None if until is None else until + 1
            doc.session.focus_pages = [section + 1 for section in focus]
        return self._ask_document(doc, question, think, template, self._push_book_chat, extra, limit)

    def reader_chat_clear(self):
        return self._clear_document_chat(getattr(self, '_book_chat', None))
