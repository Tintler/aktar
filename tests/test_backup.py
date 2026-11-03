"""F239: yedekleme, geri yukleme ve bulunamayan yollari yeniden baglama."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import backup  # noqa: E402


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.app = self.base / 'app'
        (self.app / 'library').mkdir(parents=True)
        (self.app / 'config.json').write_text('{"model": "a"}', encoding='utf-8')
        (self.app / 'ui.json').write_text('{}', encoding='utf-8')
        (self.app / 'ses-presetleri').mkdir()
        (self.app / 'ses-presetleri' / 'kayit.wav').write_bytes(b'RIFF')
        (self.app / 'work_files' / 'qa').mkdir(parents=True)
        (self.app / 'work_files' / 'qa' / 'x.json').write_text('{}', encoding='utf-8')
        (self.app / 'work_files' / 'stems').mkdir()
        (self.app / 'work_files' / 'stems' / 'big.wav').write_bytes(b'0' * 100)
        (self.app / 'models').mkdir()
        (self.app / 'models' / 'model.bin').write_bytes(b'0')
        (self.app / 'ses-onbellegi' / 'abc').mkdir(parents=True)
        (self.app / 'ses-onbellegi' / 'abc' / 'a.wav').write_bytes(b'0')

    def names(self, path):
        with zipfile.ZipFile(path) as archive:
            return sorted(archive.namelist())

    def test_create_includes_user_data_only(self):
        target = self.base / 'out' / 'yedek.zip'
        result = backup.create(self.app, target, ())
        self.assertEqual(self.names(target), [backup.MANIFEST, 'config.json', 'ses-presetleri/kayit.wav', 'ui.json'])
        self.assertEqual(result['files'], 3)
        backup.create(self.app, target, ('work', 'audio'))
        names = self.names(target)
        self.assertIn('work_files/qa/x.json', names)
        self.assertIn('ses-onbellegi/abc/a.wav', names)
        self.assertNotIn('work_files/stems/big.wav', names)
        self.assertFalse(any(name.startswith('models/') for name in names))
        sizes = backup.sizes(self.app)
        self.assertTrue(sizes['core']['always'])
        self.assertEqual(sizes['audio']['files'], 1)

    def test_restore_backs_up_current_data_first_and_rejects_unsafe_names(self):
        target = self.base / 'yedek.zip'
        backup.create(self.app, target, ())
        with zipfile.ZipFile(target, 'a') as archive:
            archive.writestr('../kacak.txt', 'x')
            archive.writestr('models/kotu.bin', 'x')
        (self.app / 'config.json').write_text('{"model": "yeni"}', encoding='utf-8')
        result = backup.restore(self.app, target)
        self.assertEqual(json.loads((self.app / 'config.json').read_text(encoding='utf-8')), {'model': 'a'})
        self.assertFalse((self.base / 'kacak.txt').exists())
        self.assertFalse((self.app / 'models' / 'kotu.bin').exists())
        with zipfile.ZipFile(result['before']) as archive:
            self.assertEqual(json.loads(archive.read('config.json')), {'model': 'yeni'})

    def test_inspect_rejects_other_zip(self):
        other = self.base / 'baska.zip'
        with zipfile.ZipFile(other, 'w') as archive:
            archive.writestr('a.txt', 'x')
        with self.assertRaises(ValueError):
            backup.inspect(other)

    def test_relink_books_and_collection_folders(self):
        moved = self.base / 'yeni' / 'Kitaplar'
        (moved / 'Videolar' / 'alt').mkdir(parents=True)
        (moved / 'roman.epub').write_bytes(b'x')
        (moved / 'tek.pdf').write_bytes(b'x')
        (self.app / 'book_library.json').write_text(json.dumps({'books': [
            {'id': '1', 'path': 'C:\\Eski\\Kitaplar\\roman.epub'}, {'id': '2', 'path': '/yok/kayip.epub'}]}),
            encoding='utf-8')
        (self.app / 'library' / 'ders.json').write_text(json.dumps({
            'title': 'Ders', 'folders': ['D:\\Eski\\Videolar'], 'files': ['D:\\Eski\\tek.pdf'],
            'excluded': ['D:\\Eski\\Videolar\\alt\\x.mp4'], 'known': []}), encoding='utf-8')
        self.assertEqual(backup.missing(self.app), {'books': ['C:\\Eski\\Kitaplar\\roman.epub', '/yok/kayip.epub'],
                                                    'folders': ['D:\\Eski\\Videolar'], 'files': ['D:\\Eski\\tek.pdf']})
        result = backup.relink(self.app, self.base / 'yeni')
        self.assertEqual((result['books'], result['folders'], result['files'], result['left']), (1, 1, 1, 1))
        books = json.loads((self.app / 'book_library.json').read_text(encoding='utf-8'))['books']
        self.assertEqual(books[0]['path'], str(moved / 'roman.epub'))
        collection = json.loads((self.app / 'library' / 'ders.json').read_text(encoding='utf-8'))
        self.assertEqual(collection['folders'], [str(moved / 'Videolar')])
        self.assertEqual(collection['excluded'], [str(moved / 'Videolar' / 'alt' / 'x.mp4')])


if __name__ == '__main__':
    unittest.main()
