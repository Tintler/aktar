"""Genel sohbet (assistant.py), tekil dosya listesi ve dosya sohbeti kaydi testleri; LM Studio gerektirmez."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import assistant  # noqa: E402
import library  # noqa: E402
import qa  # noqa: E402
import search_index  # noqa: E402
from app_core import DEFAULT_CONFIG, save_json  # noqa: E402

QUIET = (lambda _message: None)
TOPICS = ('regresyon', 'budama', 'ağaç', 'ezber')


class FakeClient:
    def __init__(self, answer='', finish='stop'):
        self.answer = answer
        self.finish = finish
        self.messages = None

    def embed(self, texts):
        # Son boyut: konu sozcugu gecmeyen metinler (selamlasma vb.) ayri bir yone duser.
        vectors = [[float(text.lower().count(word)) + 0.01 for word in TOPICS] for text in texts]
        return [vector + [1.0 if max(vector) < 1 else 0.01] for vector in vectors]

    def chat_stream(self, messages, on_delta=None, temperature=None, max_tokens=None, cancelled=None,
                    on_reasoning=None):
        self.messages = messages
        if on_delta:
            on_delta('<think>plan')
            on_delta(self.answer)
        return self.answer, self.finish


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(self.root / 'library')})
        patcher.start()
        self.addCleanup(patcher.stop)


class ConversationStoreTests(StoreTestCase):
    def test_save_load_list_rename_delete(self):
        data = assistant.new_conversation()
        data['title'] = assistant.make_title('Regresyon nedir?')
        data['entries'] = [('user', 'Regresyon nedir?'), ('pending', 'x'),
                           ('assistant', {'parts': [('text', 'Bir yöntem.')], 'sources': []})]
        data['history'] = [{'question': 'Regresyon nedir?', 'answer': 'Bir yöntem.', 'parts': []}]
        assistant.save_conversation(data)

        loaded = assistant.load_conversation(data['id'])
        self.assertEqual([kind for kind, _item in loaded['entries']], ['user', 'assistant'])
        self.assertEqual(loaded['history'], [{'question': 'Regresyon nedir?', 'answer': 'Bir yöntem.'}])
        self.assertEqual([item['title'] for item in assistant.list_conversations()], ['Regresyon nedir?'])

        assistant.rename_conversation(data['id'], '  Yeni   ad ')
        self.assertEqual(assistant.list_conversations()[0]['title'], 'Yeni ad')
        assistant.delete_conversation(data['id'])
        self.assertEqual(assistant.list_conversations(), [])
        with self.assertRaises(ValueError):
            assistant.load_conversation(data['id'])

    def test_conversations_are_not_collections(self):
        assistant.save_conversation(dict(assistant.new_conversation(), title='Sohbet'))
        library.touch_recent(self.root / 'tek.pdf')
        self.assertEqual(library.list_collections(), {})

    def test_invalid_id_is_rejected(self):
        with self.assertRaises(ValueError):
            assistant.load_conversation('../config')

    def test_text_helpers(self):
        self.assertEqual(assistant.make_title('kısa'), 'kısa')
        long = assistant.make_title('kelime ' * 30)
        self.assertTrue(long.endswith('…'))
        self.assertLessEqual(len(long), assistant.TITLE_CHARS + 1)
        self.assertEqual(assistant.strip_citations('Puan 98 [V1 s.1]. Süre [V2 1:02-1:30; V3 0:10].'),
                         'Puan 98. Süre.')
        self.assertEqual(assistant.visible_text('<think>gizli</think>Merhaba'), 'Merhaba')
        self.assertEqual(assistant.visible_text('Merhaba <think>yarım'), 'Merhaba')


class RecentFilesTests(StoreTestCase):
    def test_touch_moves_to_front_and_forget_clears_chat(self):
        first, second = self.root / 'a.pdf', self.root / 'b.mkv'
        library.touch_recent(first)
        library.touch_recent(second)
        library.touch_recent(first)
        self.assertEqual([Path(item['path']).name for item in library.load_recent()], ['a.pdf', 'b.mkv'])

        key = library.file_chat_key(first)
        library.save_chat(key, [('user', 'soru'), ('assistant', {'parts': [], 'sources': []})],
                          [{'question': 'soru', 'answer': 'cevap'}])
        self.assertEqual(len(library.load_chat(key)['entries']), 2)
        library.forget_recent(first)
        self.assertEqual([Path(item['path']).name for item in library.load_recent()], ['b.mkv'])
        self.assertEqual(library.load_chat(key)['entries'], [])

    def test_chat_key_is_stable_and_path_based(self):
        self.assertEqual(library.file_chat_key(self.root / 'a.pdf'), library.file_chat_key(self.root / 'a.pdf'))
        self.assertNotEqual(library.file_chat_key(self.root / 'a.pdf'), library.file_chat_key(self.root / 'b.pdf'))


class AssistantTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.root / 'work'
        patcher = mock.patch.object(qa, 'work_dir', lambda: self.work)
        patcher.start()
        self.addCleanup(patcher.stop)
        search_index._MEMO.clear()
        self.cfg = dict(DEFAULT_CONFIG, embedding_model='emb', auto_retry_count=1)
        self.videos = [self.video('01 Regresyon.mkv', 'doğrusal regresyon', 'regresyon hatası'),
                       self.video('07 Ağaç.mkv', 'karar ağacı', 'budama ezberi önler')]

    def video(self, name, *texts):
        path = self.root / name
        path.write_bytes(b'x')
        source = {'kind': 'subtitle', 'stream': 2, 'language': 'tr', 'title': ''}
        segments = [{'start': 30.0 + index * 10, 'end': 38.0 + index * 10, 'text': text}
                    for index, text in enumerate(texts)]
        data = qa.build_data(path, segments, source, {'duration': 120.0, 'chapters': []})
        save_json(qa.cache_path(path, qa.source_key(source)), data)
        search_index.build(path, self.cfg, FakeClient(), log=QUIET)
        return path

    def bot(self, history=None):
        return assistant.Assistant(history, config_provider=lambda: self.cfg, log=QUIET,
                                   snapshot=lambda: (self.videos, 'LIBRARY OVERVIEW (collections):\n- Ders (2 dosya)'))

    def test_relevant_question_gets_notes_and_verified_citations(self):
        client = FakeClient('Regresyon hatası anlatılıyor [V1 0:40]. Uydurma [V9 1:00].')
        deltas = []
        turn = self.bot().ask('regresyon hatası nedir?', on_delta=deltas.append, client=client)
        system = client.messages[0]['content']
        self.assertIn('LIBRARY NOTES (automatic', system)
        self.assertIn('01 Regresyon', system)
        self.assertNotIn('07 Ağaç', system)  # ilgisiz dosya esigin altinda kalir
        cites = [item for kind, value in turn['parts'] if kind == 'cite' for item in value]
        self.assertEqual([cite['label'] for cite in cites], ['V1 0:40'])
        self.assertEqual([source['title'] for source in turn['sources']], ['01 Regresyon'])
        self.assertEqual(deltas[0], '')  # dusunce akisi gizlenir

    def test_unrelated_question_has_no_notes_and_no_citations(self):
        client = FakeClient('Merhaba! Size nasıl yardımcı olabilirim?')
        turn = self.bot().ask('merhaba', client=client)
        system = client.messages[0]['content']
        self.assertNotIn('LIBRARY NOTES (automatic', system)
        self.assertIn('LIBRARY OVERVIEW', system)
        self.assertEqual(turn['parts'], [('text', 'Merhaba! Size nasıl yardımcı olabilirim?')])
        self.assertEqual(turn['sources'], [])

    def test_history_is_sent_without_citations(self):
        client = FakeClient('Tamam.')
        bot = self.bot([{'question': 'regresyon?', 'answer': 'Anlatılıyor [V1 0:40].'}])
        bot.ask('teşekkürler', client=client)
        self.assertEqual(client.messages[2], {'role': 'assistant', 'content': 'Anlatılıyor.'})
        self.assertEqual(len(bot.history), 2)

    def test_stopped_and_truncated_answers(self):
        stopped = self.bot().ask('merhaba', client=FakeClient('Yarım', finish='cancelled'))
        self.assertTrue(stopped['stopped'])
        cut = self.bot().ask('merhaba', client=FakeClient('Uzun', finish='length'))
        self.assertIn('token sınırında kesildi', cut['answer'])
        with self.assertRaises(ValueError):
            self.bot().ask('merhaba', client=FakeClient(''))

    def test_without_embedding_model_chat_still_works(self):
        self.cfg['embedding_model'] = ''
        client = FakeClient('Paris.')
        turn = self.bot().ask('regresyon başkenti?', client=client)
        self.assertNotIn('LIBRARY NOTES (automatic', client.messages[0]['content'])
        self.assertEqual(turn['answer'], 'Paris.')


if __name__ == '__main__':
    unittest.main()
