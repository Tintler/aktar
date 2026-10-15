"""Not ve vurgu (F113) testleri: dosya basina saklama ve koleksiyon sohbeti baglami."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import collection_qa  # noqa: E402
import library  # noqa: E402
import notes  # noqa: E402
import qa  # noqa: E402
import search_index  # noqa: E402
from app_core import DEFAULT_CONFIG, save_json  # noqa: E402
from test_collection_qa import QUIET, FakeClient  # noqa: E402


class NotesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(self.root / 'store')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.work = self.root / 'work'
        self.cfg = dict(DEFAULT_CONFIG, embedding_model='emb', auto_retry_count=1)
        search_index._MEMO.clear()

    def video(self, name, *texts):
        path = self.root / name
        path.write_bytes(b'x')
        source = {'kind': 'subtitle', 'stream': 2, 'language': 'tr', 'title': ''}
        segments = [{'start': 30.0 + index * 10, 'end': 38.0 + index * 10, 'text': text}
                    for index, text in enumerate(texts)]
        data = qa.build_data(path, segments, source, {'duration': 120.0, 'chapters': []})
        save_json(qa.cache_path(path, qa.source_key(source), self.work), data)
        search_index.build(path, self.cfg, FakeClient(), self.work, log=QUIET)
        return path

    def document(self, name, *pages):
        path = self.root / name
        path.write_bytes(b'x')
        segments = [{'start': float(page), 'end': float(page), 'text': text}
                    for page, text in enumerate(pages, 1)]
        data = qa.build_data(path, segments, {'kind': 'pdf'})
        save_json(qa.cache_path(path, qa.source_key({'kind': 'pdf'}), self.work), data)
        search_index.build(path, self.cfg, FakeClient(), self.work, log=QUIET)
        return path

    def test_add_update_delete_sorted_and_not_a_collection(self):
        path = self.root / 'Ders.mkv'
        late = notes.add(path, 95.5, 'Sonra tekrar izle')
        early = notes.add(path, 12, '', quote='  önemli   cümle ', color='green')
        self.assertEqual([note['id'] for note in notes.load(path)], [early['id'], late['id']])
        self.assertEqual(notes.load(path)[0]['quote'], 'önemli cümle')
        self.assertEqual(notes.load(path)[0]['color'], 'green')
        self.assertTrue(notes.notes_path(path).name.endswith('.notes.json'))
        library.create_collection('Dersler')
        self.assertEqual(list(library.list_collections()), ['dersler'])
        with self.assertRaises(ValueError):
            notes.add(path, 1, '   ')
        self.assertTrue(notes.update(path, late['id'], text='Düzeltildi', color='nope'))
        self.assertEqual(notes.load(path)[1]['text'], 'Düzeltildi')
        self.assertEqual(notes.load(path)[1]['color'], 'yellow')
        self.assertTrue(notes.delete(path, early['id']))
        self.assertFalse(notes.delete(path, early['id']))
        notes.update(path, late['id'], text='')  # metni ve alintisi bosalan not silinir
        self.assertEqual(notes.load(path), [])
        self.assertFalse(notes.notes_path(path).exists())

    def test_notes_enter_collection_context_and_can_be_cited(self):
        videos = [self.video('01 Regresyon.mkv', 'doğrusal regresyon', 'regresyon hatası'),
                  self.document('Kitap.pdf', 'giriş', 'budama ezberi önler')]
        notes.add(videos[0], 41, 'Sınavda çıkacak')
        notes.add(videos[1], 2, 'Bunu özetle', quote='budama ezberi')
        notes.add(self.root / 'koleksiyon-disi.mkv', 5, 'girmemeli')
        chat = collection_qa.CollectionQA(videos, 'ML', lambda: dict(self.cfg), log=QUIET,
                                          base=self.work)
        client = FakeClient('Hocanın dediği gibi sınavda çıkar [V1 0:41]; kitapta da var [V2 s.2].')
        turn = chat.ask('budama', client)
        context = client.messages[0]['content']
        self.assertIn('USER NOTES (written by the user):\n[V1 0:41] Sınavda çıkacak\n'
                      '[V2 s.2] «budama ezberi» Bunu özetle', context)
        self.assertNotIn('girmemeli', context)
        cites = [cite['label'] for kind, value in turn['parts'] if kind == 'cite' for cite in value]
        self.assertEqual(cites, ['V1 0:41', 'V2 s.2'])

    def test_notes_share_limits_context(self):
        videos = [self.video('01 Regresyon.mkv', 'doğrusal regresyon')]
        chat = collection_qa.CollectionQA(videos, 'ML', lambda: dict(self.cfg), log=QUIET,
                                          base=self.work)
        chat.notes = {str(videos[0]): [{'at': 30.0 + index, 'text': 'x' * 200, 'quote': ''}
                                       for index in range(100)]}
        cfg = dict(self.cfg, qa_context_chars=10000)
        text, labels = chat.notes_text(cfg)
        self.assertLessEqual(len(text), 1000 + 40)
        self.assertEqual(list(labels), ['V1'])
        chat.notes = {}
        self.assertEqual(chat.notes_text(cfg), ('', {}))


if __name__ == '__main__':
    unittest.main()
