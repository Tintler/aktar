"""F242: temizlik -- kitapligda olmayan kitaplarin kayitlari, dosyasi bulunamayan kitaplar, kaynagi olmayan
onbellekler, kullanilmayan donusturulmus e-kitaplar; yalnizca secilen silinir."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import cleanup  # noqa: E402

KEPT = 'aaaaaaaaaaaaaaaa'
GONE = 'bbbbbbbbbbbbbbbb'
LOST = 'cccccccccccccccc'


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.app = self.base / 'app'
        self.app.mkdir()
        epub = self.base / 'kitap.epub'
        epub.write_bytes(b'x')
        (self.app / 'book_library.json').write_text(json.dumps({'books': [
            {'id': KEPT, 'path': str(epub), 'title': 'Duran'},
            {'id': LOST, 'path': str(self.base / 'yok.epub'), 'title': 'Kayıp'}]}), encoding='utf-8')
        for book in (KEPT, GONE, LOST):
            self.write(f'ses-onbellegi/{book}/a.wav', b'0' * 10)
            self.write(f'duygu-etiketleri/{book}.json', json.dumps({'title': 'Etiketli ' + book[0]}).encode())
        self.write(f'duygu-etiketleri/yarim/{GONE}.json', b'{}')
        self.write(f'karakter-sesleri/{GONE}.json', b'{}')
        self.write(f'kitap-gorselleri/{GONE}/plan.json', b'{}')
        self.write('kitap-gorselleri/is-akisi.json', b'{}')   # kitaba ait degil, dokunulmaz
        video = self.base / 'video.mp4'
        video.write_bytes(b'v')
        self.write('work_files/qa/video.1.json', json.dumps({'video': str(video)}).encode())
        self.write('work_files/qa/silinen.2.json', json.dumps({'video': str(self.base / 'silinen.mp4'), 'title': 'Silinen'}).encode())
        self.write('work_files/index/silinen.3.json', json.dumps({'video': str(self.base / 'silinen.mp4')}).encode())
        self.write('work_files/ebooks/eski-1234.epub', b'e')

    def write(self, name, data):
        path = self.app / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_find_lists_only_unowned_records(self):
        found = cleanup.find(self.app)
        self.assertEqual([item['book'] for item in found['books']], [GONE])
        self.assertEqual(found['books'][0]['title'], 'Etiketli b')
        self.assertEqual({part['kind'] for part in found['books'][0]['parts']}, {'audio', 'emotion', 'cast', 'art'})
        self.assertEqual([item['book'] for item in found['missing']], [LOST])
        self.assertEqual([(item['title'], item['files']) for item in found['caches']], [('Silinen', 2)])
        self.assertEqual([item['id'] for item in found['ebooks']], ['ebook:eski-1234.epub'])

    def test_remove_deletes_only_chosen(self):
        result = cleanup.remove(self.app, ['book:' + GONE, 'cache:' + str(self.base / 'silinen.mp4'), 'book:' + KEPT,
                                           'ebook:../book_library.json'])
        self.assertEqual(result['removed'], 2)
        self.assertFalse((self.app / 'ses-onbellegi' / GONE).exists())
        self.assertFalse((self.app / 'duygu-etiketleri' / 'yarim' / f'{GONE}.json').exists())
        self.assertFalse((self.app / 'kitap-gorselleri' / GONE).exists())
        self.assertTrue((self.app / 'kitap-gorselleri' / 'is-akisi.json').exists())
        self.assertTrue((self.app / 'ses-onbellegi' / KEPT / 'a.wav').exists())   # kitapligdaki kitap secilemez
        self.assertTrue((self.app / 'book_library.json').exists())
        self.assertTrue((self.app / 'work_files' / 'qa' / 'video.1.json').exists())
        self.assertFalse((self.app / 'work_files' / 'index' / 'silinen.3.json').exists())
        self.assertTrue((self.app / 'work_files' / 'ebooks' / 'eski-1234.epub').exists())
        result = cleanup.remove(self.app, ['missing:' + LOST, 'ebook:eski-1234.epub'])
        self.assertEqual(result['books'], [LOST])
        self.assertFalse((self.app / 'ses-onbellegi' / LOST).exists())
        self.assertFalse((self.app / 'work_files' / 'ebooks' / 'eski-1234.epub').exists())

    def test_book_parts_and_remove_book_data(self):
        parts = cleanup.book_parts(self.app, KEPT)
        self.assertEqual([part['kind'] for part in parts], ['audio', 'emotion'])
        self.assertEqual(cleanup.book_parts(self.app, '../x'), [])
        cleanup.remove_book_data(self.app, KEPT)
        self.assertEqual(cleanup.book_parts(self.app, KEPT), [])
        with self.assertRaises(ValueError):
            cleanup.remove_book_data(self.app, '..')


if __name__ == '__main__':
    unittest.main()
