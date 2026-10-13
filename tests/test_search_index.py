"""Kutuphane indeksi (parcalama, embedding, arama) testleri; LM Studio gerektirmez."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import qa  # noqa: E402
import search_index  # noqa: E402
from app_core import DEFAULT_CONFIG, Client, save_json, validate_config  # noqa: E402

TOPICS = ('regresyon', 'budama', 'ağaç', 'düzenlileştirme')


class FakeClient:
    """Metindeki konu kelimelerinden deterministik vektor uretir."""

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(text.lower().count(word)) + 0.01 for word in TOPICS] for text in texts]


def segments(*texts, step=40.0):
    return [{'start': index * step, 'end': index * step + step - 1, 'text': text}
            for index, text in enumerate(texts)]


class SearchIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.cfg = dict(DEFAULT_CONFIG, embedding_model='emb')
        search_index._MEMO.clear()

    def video(self, name, *texts):
        path = self.root / name
        path.write_bytes(b'x')
        source = {'kind': 'subtitle', 'stream': 2, 'language': 'tr', 'title': ''}
        data = qa.build_data(path, segments(*texts), source, {'duration': 0.0, 'chapters': []})
        save_json(qa.cache_path(path, qa.source_key(source), self.work), data)
        return path

    def test_chunks_cover_transcript_with_one_line_overlap(self):
        chunks = search_index.chunk_lines(segments('a', 'b', 'c', 'd', 'e'), max_seconds=90)
        self.assertEqual([chunk['text'] for chunk in chunks], ['a b', 'b c', 'c d', 'd e'])
        self.assertEqual((chunks[0]['start'], chunks[-1]['end']), (0.0, 199.0))

    def test_build_is_cached_and_search_ranks_by_meaning(self):
        client = FakeClient()
        first = self.video('01 Regresyon.mkv', 'doğrusal regresyon', 'regresyon hatası')
        second = self.video('07 Ağaç.mkv', 'karar ağacı budama', 'budama derinliği')
        for path in (first, second):
            self.assertTrue(search_index.build(path, self.cfg, client, self.work).exists())
        calls = len(client.calls)
        search_index.build(first, self.cfg, client, self.work)
        self.assertEqual(len(client.calls), calls, 'mevcut indeks yeniden uretilmemeli')
        self.assertTrue(all(text.startswith('title: ') for text in client.calls[0]))
        hits = search_index.search([first, second], 'budama nasıl yapılır', self.cfg,
                                   client, limit=2, base=self.work)
        self.assertEqual([hit['title'] for hit in hits], ['07 Ağaç', '01 Regresyon'])
        self.assertIn('task: search result | query: budama', client.calls[-1][0])
        self.assertGreaterEqual(hits[0]['score'], hits[1]['score'])
        self.assertIn('start', hits[0])

    def test_index_path_changes_with_model_and_missing_transcript_returns_none(self):
        path = self.video('a.mkv', 'regresyon')
        session = search_index.primary_session(path, self.work)
        other = dict(self.cfg, embedding_model='baska')
        self.assertNotEqual(search_index.index_path(path, session, self.cfg, self.work),
                            search_index.index_path(path, session, other, self.work))
        empty = self.root / 'b.mkv'
        empty.write_bytes(b'x')
        self.assertIsNone(search_index.build(empty, self.cfg, FakeClient(), self.work))

    def test_client_embed_orders_by_index_and_requires_model(self):
        client = Client(dict(DEFAULT_CONFIG, embedding_model='emb'))
        reply = {'data': [{'index': 1, 'embedding': [0, 1]}, {'index': 0, 'embedding': [1, 0]}]}
        with mock.patch.object(client, 'request', return_value=reply) as request:
            self.assertEqual(client.embed(['a', 'b']), [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(request.call_args.args[0], '/embeddings')
        self.assertEqual(request.call_args.args[1]['model'], 'emb')
        with self.assertRaises(ValueError):
            Client(dict(DEFAULT_CONFIG)).embed(['a'])

    def test_templates_must_keep_placeholders(self):
        validate_config(dict(DEFAULT_CONFIG))
        with self.assertRaises(ValueError):
            validate_config(dict(DEFAULT_CONFIG, embedding_query_template='query: '))


if __name__ == '__main__':
    unittest.main()
