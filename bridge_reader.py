"""Okuma sayfasinin arka ucu (Bridge'e karisan sinif); Cevirgec bridge.py'nin okuma bolumu.

Kisisel EPUB kitapligi (book_reader.Library, APP_DIR/book_library.json): kitap ekleme/kaldirma,
kapak, bolum cizimi, okuma konumu ve yer imleri. Aktar'in Kutuphane'siyle (bridge_library)
karismasin diye kitaplik metotlari `shelf_`, okuyucu metotlari `reader_` onekli; olay 'shelf'.
"""
from __future__ import annotations

from pathlib import Path
import re
import webbrowser
import zipfile

import book_core
from book_reader import Library


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
