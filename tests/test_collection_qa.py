"""Koleksiyona soru sor (arama -> baglam -> atif dogrulama) testleri; LM Studio gerektirmez."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import collection_qa  # noqa: E402
import qa  # noqa: E402
import search_index  # noqa: E402
from app_core import DEFAULT_CONFIG, save_json  # noqa: E402

QUIET = (lambda _message: None)
TOPICS = ('regresyon', 'budama', 'ağaç', 'ezber')


class FakeClient:
    def __init__(self, answer=''):
        self.answer = answer
        self.embedded = []
        self.messages = None

    def embed(self, texts):
        self.embedded.append(list(texts))
        return [[float(text.lower().count(word)) + 0.01 for word in TOPICS] for text in texts]

    def chat(self, messages):
        self.messages = messages
        return self.answer


class CollectionQATests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.work = self.root / 'work'
        self.cfg = dict(DEFAULT_CONFIG, embedding_model='emb', auto_retry_count=1)
        search_index._MEMO.clear()
        self.videos = [self.video('01 Regresyon.mkv', 'doğrusal regresyon', 'regresyon hatası'),
                       self.video('07 Ağaç.mkv', 'karar ağacı', 'budama ezberi önler')]

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

    def session(self, answer):
        client = FakeClient(answer)
        chat = collection_qa.CollectionQA(self.videos, 'ML', lambda: dict(self.cfg),
                                          log=QUIET, base=self.work)
        return chat, client

    def test_answer_cites_videos_and_drops_invented_ones(self):
        chat, client = self.session('Budama ezberi önler [V2 0:41]. Uydurma [V9 0:30] '
                                    've yanlış zaman [V1 50:00]. Regresyon [V1 0:30-0:45; V2 0:40].')
        turn = chat.ask('budama ne işe yarar', client)
        context = client.messages[0]['content']
        self.assertIn('### V2 · 07 Ağaç', context)
        self.assertIn('[0:30] karar ağacı budama ezberi önler', context)
        self.assertIn('task: search result | query: budama ne işe yarar', client.embedded[-1][0])
        cites = [cite for kind, value in turn['parts'] if kind == 'cite' for cite in value]
        self.assertEqual([cite['label'] for cite in cites], ['V2 0:41', 'V1 0:30-0:45', 'V2 0:40'])
        self.assertEqual(cites[0]['video'], str(self.videos[1]))
        text = ''.join(value for kind, value in turn['parts'] if kind == 'text')
        self.assertNotIn('V9', text)
        self.assertNotIn('50:00', text)
        self.assertEqual([(item['label'], item['count']) for item in turn['sources']],
                         [('V2', 2), ('V1', 1)])

    def test_follow_up_question_searches_with_previous_question(self):
        chat, client = self.session('Cevap [V1 0:30].')
        chat.ask('regresyon nedir', client)
        chat.ask('peki neden?', client)
        self.assertIn('regresyon nedir peki neden?', client.embedded[-1][0])
        self.assertEqual([item['role'] for item in client.messages],
                         ['system', 'user', 'assistant', 'user'])

    def test_unlabelled_time_is_kept_only_for_single_video_context(self):
        chat, _client = self.session('')
        videos = {'V1': self.videos[0]}
        parts = chat.split_citations('Burada [0:31] anlatılıyor.', videos)
        self.assertEqual(parts[1][1][0]['label'], 'V1 0:31')
        parts = chat.split_citations('Burada [0:31] anlatılıyor.',
                                     {'V1': self.videos[0], 'V2': self.videos[1]})
        self.assertEqual([kind for kind, _value in parts], ['text'])

    def test_empty_index_raises_helpful_error(self):
        chat = collection_qa.CollectionQA([self.root / 'yok.mkv'], 'ML', lambda: dict(self.cfg),
                                          log=QUIET, base=self.work)
        with self.assertRaises(ValueError):
            chat.ask('soru', FakeClient('x'))


if __name__ == '__main__':
    unittest.main()
