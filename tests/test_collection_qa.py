"""Koleksiyona soru sor (arama -> baglam -> atif dogrulama) testleri; LM Studio gerektirmez."""
from __future__ import annotations

import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

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

    def test_live_reasoning_streams_final_answer(self):
        chat, client = self.session('kullanilmaz')
        seen = []

        def chat_stream(messages, cancelled=None, on_reasoning=None, **_kwargs):
            client.messages = messages
            for piece in ('Plan', 'Plan yap'):
                on_reasoning(piece)
            client.last_reasoning = 'Plan yap'
            return 'Budama ezberi önler [V2 0:41].', 'stop'

        client.chat_stream = chat_stream
        turn = chat.ask('budama ne işe yarar', client, think=True, on_reasoning=seen.append)
        self.assertEqual(seen, ['Plan', 'Plan yap'])
        self.assertEqual(turn['thinking'], 'Plan yap')
        self.assertEqual([cite['label'] for kind, value in turn['parts'] if kind == 'cite' for cite in value],
                         ['V2 0:41'])

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

    def test_video_summaries_feed_collection_overview_and_context(self):
        """F61: video ozetleri -> koleksiyon ozeti; ikisi de soru baglamina girer."""
        summaries = iter(['{"summary": "Regresyon dersi.", "topics": ["regresyon"], '
                          '"questions": ["a?"]}',
                          '{"summary": "Ağaç dersi.", "topics": ["budama"], "questions": ["b?"]}'])

        with unittest.mock.patch('app_core.Client.chat', lambda _self, _messages: next(summaries)):
            for video in self.videos:
                summary = collection_qa.summarize_video(video, lambda: dict(self.cfg), QUIET,
                                                        base=self.work)
                self.assertTrue(summary['summary'])
        self.assertEqual([item['summary'] for item in
                          collection_qa.video_summaries(self.videos, self.work)],
                         ['Regresyon dersi.', 'Ağaç dersi.'])
        client = FakeClient('{"summary": "İki derslik ML serisi.", "topics": ["regresyon", '
                            '"ağaçlar"], "questions": ["Hangi derste budama var?"]}')
        overview = collection_qa.build_overview('ML', self.videos, self.cfg, client, QUIET,
                                                self.work)
        self.assertEqual(overview['summary'], 'İki derslik ML serisi.')
        self.assertIn('V2 07 Ağaç: Ağaç dersi.', client.messages[1]['content'])
        self.assertEqual(len(overview['videos']), 2)
        chat = collection_qa.CollectionQA(self.videos, 'ML', lambda: dict(self.cfg), log=QUIET,
                                          base=self.work, overview=overview)
        answer = FakeClient('Seri iki dersten oluşur [V1 0:30].')
        chat.ask('bu seride neler var', answer)
        context = answer.messages[0]['content']
        self.assertIn('COLLECTION OVERVIEW:\nİki derslik ML serisi.', context)
        self.assertIn('V1 = 01 Regresyon: Regresyon dersi.', context)

    def test_questions_use_qa_model_and_summaries_use_analysis_model(self):
        """F72: soru-cevap 'qa_model' ile; ozet/analiz 'model' ile yapilir."""
        cfg = dict(self.cfg, model='analiz', qa_model='soru')
        used = []

        def chat(client, messages):
            used.append(client.cfg['model'])
            if 'JSON' in messages[0]['content']:
                return '{"summary": "Özet.", "topics": [], "questions": []}'
            return 'Cevap [V1 0:30].'

        embed = lambda client, texts: FakeClient().embed(texts)  # noqa: E731
        with unittest.mock.patch('app_core.Client.chat', chat), \
                unittest.mock.patch('app_core.Client.embed', embed):
            chat_session = collection_qa.CollectionQA(self.videos, 'ML', lambda: dict(cfg),
                                                      log=QUIET, base=self.work)
            chat_session.ask('regresyon nedir')
            self.assertEqual(used, ['soru'])
            collection_qa.summarize_video(self.videos[0], lambda: dict(cfg), QUIET,
                                          base=self.work)
            self.assertEqual(set(used[1:]), {'analiz'})
            used.clear()
            same = dict(cfg, qa_model='')
            collection_qa.CollectionQA(self.videos, 'ML', lambda: dict(same), log=QUIET,
                                       base=self.work).ask('regresyon')
            self.assertEqual(used, ['analiz'])

    def statement(self, folder, name, text):
        path = self.root / folder / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'x')
        source = {'kind': 'pdf'}
        data = qa.build_data(path, [{'start': 1.0, 'end': 1.0, 'text': text}], source)
        save_json(qa.cache_path(path, qa.source_key(source), self.work), data)
        search_index.build(path, self.cfg, FakeClient(), self.work, log=QUIET)
        return path

    def test_current_state_question_adds_latest_statement_of_each_series(self):
        """F95: 'su an' sorusunda arama eski ayi secse de her serinin son ekstresi baglama girer."""
        self.assertEqual(collection_qa.series_key('E/2025-03-03 World Gold Hesap.pdf'),
                         collection_qa.series_key('E/2026-09-02 World Gold Hesap.pdf'))
        self.assertEqual(collection_qa.series_key('E/2025-02-05 2025 Ocak ayı hesap.pdf'),
                         collection_qa.series_key('E/2026-09-04 2026 Ağustos ayı hesap.pdf'))
        gold = [self.statement('E', f'2026-0{month} World Gold Hesap.pdf', f'altın bakiye {month}0 gram')
                for month in (1, 2, 3)]
        cash = [self.statement('E', f'2026-0{month} {name} ayı hesap.pdf', f'dolar bakiye {month}00')
                for month, name in ((1, 'Ocak'), (2, 'Şubat'))]
        videos = gold + cash + self.videos
        dates = {str(path): path.stem[:7] for path in gold + cash}
        chat = collection_qa.CollectionQA(videos, 'Finans', lambda: dict(self.cfg), log=QUIET,
                                          base=self.work, dates=dates)
        client = FakeClient('Cevap.')
        old_only = [{'video': str(gold[0]), 'start': 1.0, 'end': 1.0}]  # arama eski ayi secer
        with unittest.mock.patch('collection_qa.today', lambda: '2026-10-15'),                 unittest.mock.patch('search_index.search', lambda *args, **kwargs: old_only):
            chat.ask('şu an güncel varlıklarım ne kadar', client)
        context = client.messages[0]['content']
        self.assertIn('TODAY: 2026-10-15', context)
        self.assertIn('altın bakiye 30 gram', context)
        self.assertIn('dolar bakiye 200', context)
        self.assertIn('MOST RECENT DOCUMENT OF EACH SERIES (use for current values): '
                      'V3 (date: 2026-03), V5 (date: 2026-02)', context)
        # tarihli belgeler kronolojik: eski ocak ekstresi son ekstreden once gelir
        self.assertLess(context.index('### V1 '), context.index('### V3 '))
        # guncel durum sorulmayinca son ekstre zorla eklenmez
        client = FakeClient('Cevap.')
        chat.ask('regresyon', client)
        self.assertNotIn('MOST RECENT', client.messages[0]['content'])

    def test_latest_statement_puts_balance_page_before_disclaimer_page(self):
        """F96: ekstrenin 1. sayfasi uyari metni, bakiye 2. sayfada; dar butcede bakiye girer."""
        path = self.root / 'E' / '2026-10-02 Sermaye Piyasasi Ekstresi.pdf'
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'x')
        source = {'kind': 'pdf'}
        segments = [{'start': 1.0, 'end': 1.0, 'text': 'Ekstre gönderim tercihinizi şubeden '
                     'değiştirebilirsiniz. ' * 12},
                    {'start': 2.0, 'end': 2.0, 'text': 'DÖNEM SONU KAPANIŞ BAKİYENİZ Fon USD '
                     '32.498 adet 1,143134 +37.149,57'}]
        save_json(qa.cache_path(path, qa.source_key(source), self.work),
                  qa.build_data(path, segments, source))
        chat = collection_qa.CollectionQA([path] + self.videos, 'Finans',
                                          lambda: dict(self.cfg, qa_context_chars=1000), log=QUIET,
                                          base=self.work, dates={str(path): '2026-10-02'})
        hits = chat.latest_hits(chat.latest_documents('güncel fon bakiyem'), chat.config_provider())
        self.assertEqual([hit['start'] for hit in hits], [2.0])

    def test_undated_inventory_survives_many_statement_series(self):
        """F97: tarihsiz envanter, 25 tarihli seri arasinda da guncel durum baglamina girer."""
        source = {'kind': 'sheet'}
        statements, dates = [], {}
        for number in range(25):
            path = self.statement('E', f'2026-09-0{number % 9 + 1} Banka{chr(65 + number)} ekstre.pdf',
                                  f'Banka{chr(65 + number)} bakiye 1.000,00 TL')
            statements.append(path)
            dates[str(path)] = '2026-09'
        inventory = self.root / 'Inventory.xlsx'
        inventory.write_bytes(b'x')
        rows = ['Toplamlar (tüm satırlardan hesaplandı): Cins = Altın (3 satır): Miktar(g) toplamı 21']
        rows += [f'Satır {row}: Cins: Altın; Miktar(g): 7' for row in range(2, 5)]
        segments = [{'start': 1.0, 'end': 1.0, 'text': text} for text in rows]
        save_json(qa.cache_path(inventory, qa.source_key(source), self.work),
                  qa.build_data(inventory, segments, source))
        chat = collection_qa.CollectionQA(statements + [inventory] + self.videos, 'Finans',
                                          lambda: dict(self.cfg), log=QUIET, base=self.work,
                                          dates=dates)
        latest = chat.latest_documents('şu an varlıklarım', self.cfg)
        self.assertIn(('', inventory), latest)
        self.assertLessEqual(len(latest), collection_qa.LATEST_SERIES)
        client = FakeClient('Cevap.')
        with unittest.mock.patch('search_index.search', lambda *args, **kwargs: []):
            chat.ask('şu an varlıklarım', client)
        context = client.messages[0]['content']
        self.assertIn('Miktar(g) toplamı 21', context)
        self.assertIn('V26 (undated)', context)
        # tutar izi olmayan tarihsiz belge (video, kilavuz) listeye girmez
        self.assertNotIn(('', self.videos[0]), latest)

    def test_empty_index_raises_helpful_error(self):
        chat = collection_qa.CollectionQA([self.root / 'yok.mkv'], 'ML', lambda: dict(self.cfg),
                                          log=QUIET, base=self.work)
        with self.assertRaises(ValueError):
            chat.ask('soru', FakeClient('x'))


if __name__ == '__main__':
    unittest.main()
