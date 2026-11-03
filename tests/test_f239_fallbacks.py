"""F239: OpenRouter gibi sunucuda olmayan embedding/OCR modeli -- anahtar kelime aramasi ve gorsel model zinciri;
okuyucuda "Simdiye kadar" ozeti (book_recap). Model sunucusu gerektirmez."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import book_recap  # noqa: E402
import llm_provider  # noqa: E402
import search_index  # noqa: E402
from app_core import DEFAULT_CONFIG, Client  # noqa: E402

QUIET = (lambda _message: None)


def lines(texts, page=None):
    return [{'start': float(page if page is not None else index), 'end': float(page if page is not None else index),
             'text': text} for index, text in enumerate(texts)]


class KeywordSearchTests(unittest.TestCase):
    def test_finds_suffixed_turkish_word(self):
        sources = [('a.mp4', 'A', lines(['Hava bugün çok güzeldi.'] * 3 + ['Matbaanın gecikmesi tartışıldı.']
                                        + ['Yemek yendi.'] * 3))]
        hits = search_index.keyword_search(sources, 'Matbaa neden gecikti?', limit=1)
        self.assertEqual(len(hits), 1)
        self.assertIn('Matbaanın', hits[0]['text'])

    def test_no_terms_spreads_over_text(self):
        sources = [('a.mp4', 'A', lines([f'Satır {n} ' + 'x' * 1300 for n in range(10)]))]
        hits = search_index.keyword_search(sources, 'Şimdiye kadar neler oldu?', limit=4)
        self.assertEqual(len(hits), 4)
        self.assertEqual(len({hit['start'] for hit in hits}), 4)
        self.assertEqual(hits[0]['start'], 0.0)

    def test_document_windows_stay_on_page(self):
        windows = search_index.keyword_windows(lines(['bir'], 1) + lines(['iki'], 2), pages=True)
        self.assertEqual([(w['start'], w['end']) for w in windows], [(1.0, 1.0), (2.0, 2.0)])


class MissingModelTests(unittest.TestCase):
    def test_messages(self):
        for text in ('HTTP 400: model sunucusu isteği reddetti: Model text-embedding-embeddinggemma-2 does not exist',
                     'HTTP 400: glm-ocr is not a valid model ID',
                     'HTTP 404: No endpoints found that support image input',
                     'HTTP 404: model_not_found'):
            self.assertTrue(llm_provider.missing_model(text), text)
        self.assertFalse(llm_provider.missing_model('HTTP 429: istek sınırı aşıldı'))
        self.assertFalse(llm_provider.missing_model('Model sunucusuna baglanilamadi'))

    def test_vision_falls_back_to_chat_model(self):
        cfg = dict(DEFAULT_CONFIG, model='sohbet', vision_model='')
        client = Client(cfg, log=QUIET)
        sent = []

        def request(route, payload):
            sent.append((payload['model'], payload['messages'][0]['content'][0]['text']))
            if payload['model'] == 'glm-ocr':
                raise RuntimeError('HTTP 400: model sunucusu isteği reddetti: glm-ocr is not a valid model ID')
            return {'choices': [{'message': {'content': 'metin'}}]}
        with mock.patch.object(client, 'request', side_effect=request):
            self.assertEqual(client.vision('Text Recognition:', b'png', model='glm-ocr', fallback_prompt='Oku'), 'metin')
            client.vision('Text Recognition:', b'png', model='glm-ocr', fallback_prompt='Oku')
        self.assertEqual(sent, [('glm-ocr', 'Text Recognition:'), ('sohbet', 'Oku'), ('sohbet', 'Oku')])

    def test_other_errors_are_not_swallowed(self):
        client = Client(dict(DEFAULT_CONFIG, model='sohbet'), log=QUIET)
        with mock.patch.object(client, 'request', side_effect=RuntimeError('HTTP 429: sınır')):
            with self.assertRaises(RuntimeError):
                client.vision('x', b'png', model='glm-ocr')


class FakeBook:
    def __init__(self, texts, titles):
        self.texts = texts
        self.toc = [{'section': n, 'title': t, 'depth': 0} for n, t in enumerate(titles)]


class FakeClient:
    def __init__(self):
        self.calls = []

    def chat(self, messages, **_kwargs):
        system, user = messages[0]['content'], messages[1]['content']
        self.calls.append((system, user))
        if system == book_recap.SECTION_TASK:
            if 'Künye' in user:
                return json.dumps({'story': False, 'summary': '', 'people': []})
            name = 'Ali' if 'Ali' in user else 'Ayşe'
            return json.dumps({'story': True, 'summary': f'{name} bir şey yaptı.',
                               'people': [{'name': name, 'note': f'{name} kahraman.'}]})
        if system == book_recap.RECAP_TASK:
            return 'Ali yola çıktı (s.2). Ayşe ona katıldı (s.3).'
        if system == book_recap.PEOPLE_TASK:
            return json.dumps({'people': [{'name': 'Ali', 'about': 'Kahraman.', 'first': 2},
                                          {'name': 'ali', 'about': 'tekrar'}]})
        raise AssertionError(system)


class RecapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        body = ' Lorem ipsum dolor sit amet.' * 20
        self.book = FakeBook(['Künye ' + body, 'Ali yola çıktı.' + body, 'Ayşe geldi.' + body,
                              'Gelecek bölüm sırrı' + body], ['Künye', 'Bir', 'İki', 'Üç'])
        texts = self.book.texts
        patcher = mock.patch('book_search.section_texts', lambda book: iter(texts))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_build_stops_at_reading_point_and_caches(self):
        store = book_recap.Store('kitap1', self.temp.name)
        client = FakeClient()
        recap = book_recap.build(self.book, 2, 0.5, client, 'm', store, log=QUIET)
        sent = '\n'.join(user for _system, user in client.calls)
        self.assertNotIn('sırrı', sent)                       # okunmayan bolum modele gitmez
        self.assertEqual(recap['until'], 2)
        self.assertEqual([p['name'] for p in recap['people']], ['Ali'])
        self.assertIn('(s.2)', recap['text'])
        saved = store.load()
        self.assertEqual(sorted(saved['sections']), ['0', '1'])  # yarim bolum kalici degil
        client2 = FakeClient()
        book_recap.build(self.book, 2, 0.5, client2, 'm', store, log=QUIET)
        sections = [user for system, user in client2.calls if system == book_recap.SECTION_TASK]
        self.assertEqual(len(sections), 1)                    # yalnizca acik bolumun okunan kismi

    def test_cut_and_chunks(self):
        self.assertEqual(book_recap.cut('bir iki üç dört', 1.0), 'bir iki üç dört')
        self.assertEqual(book_recap.cut('bir iki üç dört', 0.5), 'bir iki')
        parts = book_recap.chunks('\n'.join(['a' * 100] * 10), size=250)
        self.assertTrue(all(len(part) <= 250 for part in parts))
        self.assertEqual(sum(part.count('a') for part in parts), 1000)

    def test_condense_keeps_latest_group(self):
        notes = [{'section': n, 'summary': 'olay ' * 40} for n in range(30)]

        class Shrink:
            def chat(self, messages, **_kwargs):
                return 'kısa özet'
        text = book_recap.condense(Shrink(), notes, limit=2000, log=QUIET)
        self.assertLessEqual(len(text), 2000)
        self.assertIn('s.30:', text)


if __name__ == '__main__':
    unittest.main()


class CastAttributionTests(unittest.TestCase):
    def test_parse_merges_names_and_skips_narration(self):
        import book_cast
        mask = [False, True, True, False]
        raw = '{"speakers": {"1": "ali", "2": "?", "3": "Ayşe", "9": "X"}, "new": [{"name": "Ayşe", "gender": "female"}]}'
        found, new = book_cast.parse(raw, 0, 4, mask, {'ali': 'Ali'})
        self.assertEqual(found, {1: 'Ali'})
        self.assertEqual(new, [{'name': 'Ayşe', 'gender': 'female'}])

    def test_attribute_book_and_store(self):
        import book_cast
        sections = [{'sentences': ['Ali kapıyı açtı.', '“Kim var orada?” diye sordu Ali.', '“Benim,” dedi Ayşe.'],
                     'breaks': [0, 1, 2]},
                    {'sentences': ['“Evet,” dedi Ali.'], 'breaks': [0]}]

        def ask(prompt):
            if 'Kim var' in prompt:
                return '{"speakers": {"1": "Ali", "2": "Ayşe"}, "new": [{"name": "Ali", "gender": "male"}, {"name": "Ayşe", "gender": "female"}]}'
            self.assertIn('Ali, Ayşe', prompt)   # bilinen karakterler sonraki bolume gider
            return '{"speakers": {"0": "ali"}, "new": []}'
        states = []
        result = book_cast.attribute_book(sections, ask, checkpoint=states.append)
        self.assertEqual(result['sections'], [['', 'Ali', 'Ayşe'], ['Ali']])
        self.assertEqual(len(states), 2)
        with tempfile.TemporaryDirectory() as folder:
            store = book_cast.Store(folder)
            info = store.save('abcdef12', sections, result)
            self.assertEqual([(c['name'], c['gender'], c['lines']) for c in info['characters']],
                             [('Ali', 'male', 2), ('Ayşe', 'female', 1)])
            self.assertEqual(store.speaker('abcdef12', '“Evet,”  dedi Ali.'), 'Ali')
            store.update('abcdef12', voices={'Ali': 'piper/tr-two'}, enabled=True, rename={'Ayşe': 'Ali'})
            info = store.info('abcdef12')
            self.assertEqual([(c['name'], c['lines']) for c in info['characters']], [('Ali', 3)])
            self.assertEqual(store.speaker('abcdef12', '“Benim,” dedi Ayşe.'), 'Ali')
            store.save('abcdef12', sections, result)     # yeniden atama ses secimini korur
            self.assertEqual(store.info('abcdef12')['voices'], {'Ali': 'piper/tr-two'})

    def test_resume_skips_finished_sections(self):
        import book_cast
        sections = [{'sentences': ['“A,” dedi Ali.'], 'breaks': [0]}, {'sentences': ['“B,” dedi Ali.'], 'breaks': [0]}]
        asked = []
        partial = {'sections': [['Ali']], 'characters': {'ali': {'name': 'Ali', 'gender': 'male'}}}
        book_cast.attribute_book(sections, lambda prompt: asked.append(prompt) or '{"speakers": {"0": "Ali"}}',
                                 partial=partial)
        self.assertEqual(len(asked), 1)
        self.assertIn('“B,”', asked[0])
