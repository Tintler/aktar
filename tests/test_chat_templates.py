from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chat_templates  # noqa: E402
import library  # noqa: E402


class ChatTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(Path(self.temp.name) / 'store')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_defaults_until_saved(self):
        names = [item['name'] for item in chat_templates.load()]
        self.assertIn('Finans analisti', names)
        self.assertFalse(chat_templates.path().exists())

    def test_save_cleans_and_keeps_ids_unique(self):
        saved = chat_templates.save([
            {'id': 'a', 'name': '  Bir   ', 'text': 'Kısa yaz.'},
            {'id': 'a', 'name': 'İki', 'text': 'Uzun yaz.'},
            {'id': '../x', 'name': 'Üç', 'text': 'Tablo kullan.'},
            {'name': 'Boş metin', 'text': '  '},
        ])
        self.assertEqual([item['name'] for item in saved], ['Bir', 'İki', 'Üç'])
        self.assertEqual(len({item['id'] for item in saved}), 3)
        self.assertEqual(saved[0]['id'], 'a')
        self.assertEqual(chat_templates.load(), saved)

    def test_empty_list_stays_empty(self):
        chat_templates.save([])
        self.assertEqual(chat_templates.load(), [])

    def test_instruction_with_template_and_note(self):
        chat_templates.save([{'id': 'f', 'name': 'Finans', 'text': 'Tablo kullan.'}])
        text, name = chat_templates.instruction('f', 'Tutarlar TL.')
        self.assertEqual(name, 'Finans')
        self.assertTrue(text.startswith('USER INSTRUCTIONS'))
        self.assertIn('Tablo kullan.', text)
        self.assertIn('About this collection: Tutarlar TL.', text)
        self.assertEqual(chat_templates.instruction('yok'), ('', ''))
        self.assertEqual(chat_templates.instruction('', '  '), ('', ''))
        self.assertIn('Not.', chat_templates.instruction('', 'Not.')[0])

    def test_file_is_not_a_collection(self):
        chat_templates.save(list(chat_templates.DEFAULTS))
        self.assertEqual(library.list_collections(), {})


if __name__ == '__main__':
    unittest.main()
