import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import drama3
import emotion_tags
from tts import Engines
from test_drama3 import RATE, REPO, FakeServer, talk

BOOK = '0123456789abcdef'


class TaggingTests(unittest.TestCase):
    def tags(self, sentences, breaks=None):
        breaks = range(len(sentences)) if breaks is None else breaks
        return emotion_tags.tag_sentences(sentences, breaks)

    def test_cue_in_the_speech_sentence(self):
        self.assertEqual(self.tags(['"Hadi gel!" diye bağırdı.', '— Çok komiksin, dedi gülerek.']),
                         ['[shouting]', '[laughs]'])

    def test_narration_gives_its_tag_to_the_speech(self):
        sentences = ['Ayşe güldü.', '— Çok komiksin, dedi.', 'Kadın içini çekerek baktı:', '— Ne yapalım.',
                     'Adam öfkeyle vurdu.', 'Kimse konuşmadı.']
        self.assertEqual(self.tags(sentences, [1, 2, 3, 4, 5]), ['', '[laughs]', '', '[sighs]', '', ''])

    def test_speech_before_the_narration_in_the_paragraph(self):
        self.assertEqual(self.tags(['“Sessiz ol.”', 'Bunu fısıldayarak söyledi.'], [1]), ['[fısıldar]', ''])

    def test_words_inside_quotes_are_not_cues(self):
        self.assertEqual(self.tags(['“Neden bağırıyorsun, gülme!” dedi.']), [''])
        self.assertEqual(self.tags(['— Neden bağırdın? dedi.']), [''])

    def test_whisper_wins_over_anger(self):
        self.assertEqual(self.tags(['— Git, diye fısıldadı öfkeyle.']), ['[fısıldar]'])

    def test_turkish_capitals(self):
        self.assertEqual(self.tags(['“Dur!” Öfkeyle KIZGIN BAĞIRDI.']), ['[shouting]'])

    def test_no_speech_no_tag(self):
        self.assertEqual(self.tags(['Herkes güldü.', 'Sonra eve döndüler.'], [1]), ['', ''])

    def test_quoted_word_is_not_speech(self):
        self.assertFalse(emotion_tags.is_speech('Yakasındaki ağır «lutr»un parlaklığı gülerek baktı.'))
        self.assertTrue(emotion_tags.is_speech('“Sessiz ol,” dedi.'))
        self.assertTrue(emotion_tags.is_speech('Beğenemiyor musun? diye güldü.'))

    def test_distant_speech_gets_no_tag(self):
        sentences = ['Genç bize doğru gülerek koşuyordu.', 'Ben bir şey sormadım.', 'Gözlerini açtı:', '- Ne o?']
        self.assertEqual(self.tags(sentences, [3]), ['', '', '', ''])

    def test_continuation_tags_the_previous_speech(self):
        self.assertEqual(self.tags(['— Gerçekten mi?', 'Diye güldü.'], [0, 1]), ['[laughs]', ''])
        self.assertEqual(self.tags(['Beğenemiyor musun? diye güldü, kuruntuyu bırak.']), ['[laughs]'])

    def test_paragraphs(self):
        self.assertEqual(emotion_tags.paragraphs(5, [1, 3]), [(0, 2), (2, 4), (4, 5)])
        self.assertEqual(emotion_tags.paragraphs(0, []), [])


class LlmTests(unittest.TestCase):
    def test_answer_is_validated(self):
        sentences = ['Ali geldi.', '— Merhaba!', '— Git buradan!']
        answer = 'Tamam: {"0": "[laughs]", "1": "laughs", "2": "[crying]", "9": "[angry]"}'
        self.assertEqual(emotion_tags.parse_llm(answer, sentences, 0, 3), {1: '[laughs]'})
        self.assertEqual(emotion_tags.parse_llm('bilmiyorum', sentences, 0, 3), {})

    def test_batches(self):
        sentences = ['— Söz.'] * (emotion_tags.LLM_BATCH + 5)
        prompts = []

        def ask(prompt):
            prompts.append(prompt)
            return json.dumps({str(emotion_tags.LLM_BATCH): '[sighs]'})

        tags = emotion_tags.tag_with_llm(sentences, [], ask)
        self.assertEqual(len(prompts), 2)
        self.assertEqual(tags[emotion_tags.LLM_BATCH], '[sighs]')
        self.assertEqual(sum(map(bool, tags)), 1)

    def test_answer_tagging_everything_is_ignored(self):
        sentences = ['— Söz.'] * 10
        everything = json.dumps({str(i): '[laughs]' for i in range(10)})
        self.assertEqual(emotion_tags.tag_with_llm(sentences, [], lambda _prompt: everything), [''] * 10)


class BookTaggingTests(unittest.TestCase):
    SECTIONS = [{'sentences': ['— Çok komiksin, dedi gülerek.', '— Peki.'], 'breaks': [0, 1]},
                {'sentences': ['Adam öfkeyle vurdu.', '— Yeter!', '— Sus.'], 'breaks': [1, 2]}]

    def test_words_only(self):
        seen = []
        tags = emotion_tags.tag_book(self.SECTIONS, progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(tags, [['[laughs]', ''], ['', '[angry]', '']])
        self.assertEqual(seen[-1], (5, 5))

    def test_model_tag_wins_and_words_fill_the_rest(self):
        def ask(prompt):
            return json.dumps({'1': '[sighs]'} if 'Peki' in prompt else {'2': '[fısıldar]'})
        tags = emotion_tags.tag_book(self.SECTIONS, ask)
        self.assertEqual(tags, [['[laughs]', '[sighs]'], ['', '[angry]', '[fısıldar]']])

    def test_cancel(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(emotion_tags.Cancelled):
            emotion_tags.tag_book(self.SECTIONS, cancel=cancel)


class StoreTests(unittest.TestCase):
    def test_save_and_lookup(self):
        sections = BookTaggingTests.SECTIONS
        with tempfile.TemporaryDirectory() as folder:
            store = emotion_tags.Store(folder)
            self.assertIsNone(store.info(BOOK))
            self.assertEqual(store.tag(BOOK, '— Yeter!'), '')
            info = store.save(BOOK, 'llm', sections, [['[laughs]', ''], ['', '[angry]', '']])
            self.assertEqual((info['method'], info['sentences'], info['tagged']), ('llm', 5, 2))
            fresh = emotion_tags.Store(folder)
            self.assertEqual(fresh.tag(BOOK, ' —  Yeter! '), '[angry]')
            self.assertEqual(fresh.tag(BOOK, '— Sus.'), '')
            self.assertEqual(fresh.books(), [BOOK])
            text = Path(info['text']).read_text(encoding='utf-8')
            self.assertEqual(text, '[laughs] — Çok komiksin, dedi gülerek.\n— Peki.\n\n'
                                   'Adam öfkeyle vurdu. [angry] — Yeter!\n— Sus.\n')
            fresh.clear(BOOK)
            self.assertEqual(emotion_tags.Store(folder).tag(BOOK, '— Yeter!'), '')
            self.assertFalse(Path(info['text']).exists())

    def test_old_realtime_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / emotion_tags.STORE_DIR / f'{BOOK}.json'
            path.parent.mkdir()
            path.write_text(json.dumps({'version': 1, 'words': {'— Bir.': '[laughs]'}, 'llm': {}}), encoding='utf-8')
            store = emotion_tags.Store(folder)
            self.assertEqual(store.tag(BOOK, '— Bir.'), '')
            self.assertEqual(store.books(), [])

    def test_bad_book_id(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                emotion_tags.Store(folder).save('../x', 'words', [{'sentences': ['a']}], [['[laughs]']])


class BridgeTests(unittest.TestCase):
    """F170: kitabin etiketli surumu kitapliktan arka planda olusturulur; okurken etiketleme yapilmaz."""

    def setUp(self):
        import bridge_tts
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(bridge_tts, 'APP_DIR', Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

        class FakeBridge(bridge_tts.TtsMixin):
            def __init__(self):
                self.prefs, self.events, self.logs = {}, [], []

            def ui_prefs(self):
                return {'tts': self.prefs}

            def _emit(self, name, data):
                self.events.append((name, data))

            def _log(self, message):
                self.logs.append(message)

        self.bridge = FakeBridge()

    def finish(self):
        self.bridge._emotion_job.join(10)
        return self.bridge.events[-1][1]

    def test_words_method_saves_the_book_and_tags_sentences(self):
        result = self.bridge.tts_emotions_create(BOOK, BookTaggingTests.SECTIONS, 'words', 'Kitap')
        self.assertEqual(result, {'started': True, 'total': 5})
        done = self.finish()
        self.assertTrue(done['finished'])
        self.assertEqual(done['info']['tagged'], 2)
        catalog = self.bridge.tts_emotion_catalog()
        self.assertEqual(catalog['allowed'], ['[fısıldar]', '[shouting]', '[angry]', '[laughs]', '[sighs]'])
        self.assertEqual(len(catalog['tags']), len(drama3.EMOTION_TAGS))
        self.bridge.prefs['emotion_allowed'] = ['[laughs]', '[sad]']
        self.assertEqual(self.bridge._emotion_tag(BOOK, '— Yeter!'), '')   # [angry] secimden cikarildi
        self.assertEqual(self.bridge.tts_emotions_info(BOOK)['missing'], ['[sad]'])
        self.bridge.prefs['emotion_allowed'] = []
        self.assertIn('error', self.bridge.tts_emotions_create(BOOK, BookTaggingTests.SECTIONS, 'words'))
        del self.bridge.prefs['emotion_allowed']
        self.assertEqual(self.bridge.tts_emotions_books(), [BOOK])
        self.assertEqual(self.bridge._emotion_tag(BOOK, '— Yeter!'), '[angry]')
        self.bridge.prefs['emotion_tags'] = 'off'
        self.assertEqual(self.bridge._emotion_tag(BOOK, '— Yeter!'), '')
        self.bridge.prefs['emotion_tags'] = 'llm'     # eski deger: acik sayilir
        self.assertEqual(self.bridge._emotion_tag(BOOK, '— Yeter!'), '[angry]')
        self.assertTrue(self.bridge.tts_emotions_clear(BOOK))
        self.assertEqual(self.bridge._emotion_tag(BOOK, '— Yeter!'), '')

    def test_model_method_loads_and_releases_the_model(self):
        class FakeClient:
            def __init__(self, cfg, log=None):
                self.cfg = {'model': 'sohbet'}

            def chat(self, messages, temperature=None, max_tokens=None):
                return '{"1": "[sighs]"}' if 'Peki' in messages[0]['content'] else '{}'

        with patch('app_core.Client', FakeClient), patch('app_core.load_config', return_value={}), \
                patch('app_core.keep_loaded', return_value=['sohbet:1']) as keep, \
                patch('app_core.unload_models') as unload:
            self.bridge.tts_emotions_create(BOOK, BookTaggingTests.SECTIONS, 'llm')
            done = self.finish()
        self.assertEqual(done['info']['method'], 'llm')
        self.assertEqual(keep.call_args[0][1], ['sohbet'])
        self.assertEqual(unload.call_args[0][1], ['sohbet:1'])
        self.assertEqual(self.bridge._emotion_tag(BOOK, '— Peki.'), '[sighs]')

    def test_model_error_is_reported(self):
        with patch('app_core.Client', side_effect=RuntimeError('Model sunucusuna bağlanılamadı')), \
                patch('app_core.load_config', return_value={}):
            self.bridge.tts_emotions_create(BOOK, BookTaggingTests.SECTIONS, 'llm')
            done = self.finish()
        self.assertIn('bağlanılamadı', done['error'])
        self.assertEqual(self.bridge.tts_emotions_books(), [])

    def test_refusals(self):
        self.assertIn('error', self.bridge.tts_emotions_create('../x', BookTaggingTests.SECTIONS, 'words'))
        self.assertIn('error', self.bridge.tts_emotions_create(BOOK, [{'sentences': []}], 'words'))
        release = threading.Event()
        self.bridge._prepare_job = threading.Thread(target=release.wait)
        self.bridge._prepare_job.start()
        try:
            self.assertIn('error', self.bridge.tts_emotions_create(BOOK, BookTaggingTests.SECTIONS, 'words'))
        finally:
            release.set()
            self.bridge._prepare_job.join()

    def test_engine_is_not_loaded_while_tagging(self):
        release = threading.Event()
        self.bridge._emotion_job = threading.Thread(target=release.wait)
        self.bridge._emotion_job.start()
        try:
            self.assertEqual(self.bridge.tts_load('tr')['state'], 'error')
            self.assertIn('error', self.bridge.tts_emotions_create(BOOK, BookTaggingTests.SECTIONS, 'words'))
        finally:
            release.set()
            self.bridge._emotion_job.join()


class CatalogTests(unittest.TestCase):
    """F171: Drama 3 etiket katalogu; yalnizca Ayarlar'da secilenler kullanilir."""

    def test_catalog_is_consistent(self):
        import drama3_tags
        self.assertEqual(len(set(drama3_tags.ALL_TAGS)), len(drama3_tags.ALL_TAGS))
        self.assertEqual(drama3_tags.DEFAULT_TAGS, ('[fısıldar]', '[shouting]', '[angry]', '[laughs]', '[sighs]'))
        self.assertTrue(all(tag.startswith('<') for tag in drama3_tags.PAIRED_TAGS))
        self.assertEqual(drama3_tags.allowed(None), drama3_tags.DEFAULT_TAGS)
        self.assertEqual(drama3_tags.allowed(['[laughs]', '[yok]', '[sad]']), ('[sad]', '[laughs]'))
        self.assertEqual(drama3_tags.allowed([]), ())
        self.assertEqual(set(drama3.EMOTION_TAGS), set(drama3_tags.ALL_TAGS))

    def test_words_use_only_chosen_tags(self):
        sentences = ['— Yine mi geldin? dedi üzgünce.', '— Gel buraya, diye bağırdı hüzünle.']
        self.assertEqual(emotion_tags.tag_sentences(sentences, [0, 1]), ['', '[shouting]'])
        self.assertEqual(emotion_tags.tag_sentences(sentences, [0, 1], ['[sad]']), ['[sad]', '[sad]'])
        self.assertEqual(emotion_tags.tag_sentences(sentences, [0, 1], []), ['', ''])

    def test_prompt_and_answer_follow_the_choice(self):
        prompt = emotion_tags.llm_prompt(['[sad]', '<soft>'])
        self.assertIn('[sad] (', prompt)
        self.assertIn('<soft> (', prompt)
        self.assertNotIn('[laughs]', prompt)
        self.assertIn('{"12": "[sad]", "15": "<soft>"}', prompt)
        sentences = ['— Bir.', '— İki.', '— Üç.']
        answer = '{"0": "<soft>", "1": "laughs", "2": "sad"}'
        self.assertEqual(emotion_tags.parse_llm(answer, sentences, 0, 3, ['<soft>', '[sad]']), {0: '<soft>', 2: '[sad]'})

    def test_store_skips_tags_removed_from_the_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            store = emotion_tags.Store(folder)
            info = store.save(BOOK, 'words', [{'sentences': ['— Bir.', '— İki.']}], [['[sad]', '[laughs]']],
                              ['[sad]', '[laughs]'])
            self.assertEqual(info['allowed'], ['[sad]', '[laughs]'])
            self.assertEqual(store.tag(BOOK, '— Bir.', ['[sad]', '[laughs]']), '[sad]')
            self.assertEqual(store.tag(BOOK, '— Bir.'), '')        # varsayilan secimde [sad] yok
            self.assertEqual(store.tag(BOOK, '— İki.'), '[laughs]')

    def test_paired_tag_wraps_the_speech_and_is_balanced(self):
        self.assertEqual(drama3.tagged('O fısıldayarak: “Sessiz ol,” dedi.', '<whisper>'),
                         'O fısıldayarak: <whisper>“Sessiz ol,”</whisper> dedi.')
        self.assertEqual(drama3.tagged('— Ne yapalım.', '<slow>'), '— <slow>Ne yapalım.</slow>')
        long = drama3.tagged('— Bir iki üç dört beş altı yedi sekiz dokuz on, on bir on iki on üç on dört on beş on '
                             'altı on yedi.', '<soft>')
        pieces = [p for p, _gap in drama3.split_text(long, 60)]
        self.assertEqual(len(pieces), 2)
        self.assertTrue(all(p.count('<soft>') == 1 and p.endswith('</soft>') for p in pieces))
        self.assertEqual(drama3.untag('[laughs] <soft>Gel.</soft>'), 'Gel.')
        self.assertEqual(drama3.untag('Gel.'), '')


class Drama3TextTests(unittest.TestCase):
    def test_tag_goes_before_the_quote(self):
        self.assertEqual(drama3.tagged('O fısıldayarak: “Sessiz ol,” dedi.', '[fısıldar]'),
                         'O fısıldayarak: [fısıldar] “Sessiz ol,” dedi.')
        self.assertEqual(drama3.tagged('"Gel!" diye bağırdı.', '[shouting]'), '[shouting] "Gel!" diye bağırdı.')
        self.assertEqual(drama3.tagged('— Ne yapalım.', '[sighs]'), '[sighs] — Ne yapalım.')
        self.assertEqual(drama3.tagged('Metin.', '[dances]'), 'Metin.')

    def test_split_puts_the_tag_at_a_piece_start(self):
        pieces = [p for p, _gap in drama3.split_text('Adam öfkeyle vurdu. [angry] “Yeter, git!”')]
        self.assertEqual(pieces, ['Adam öfkeyle vurdu.', '[angry] “Yeter, git!”'])
        pieces = [p for p, _gap in drama3.split_text('O fısıldayarak: [fısıldar] “Sessiz ol.”')]
        self.assertEqual(pieces, ['O fısıldayarak:', '[fısıldar] “Sessiz ol.”'])

    def test_laugh_does_not_count_as_overlong(self):
        samples = talk(3.5)
        self.assertTrue(drama3.fell_silent('“Evet!”', samples, RATE))
        self.assertFalse(drama3.fell_silent('[laughs] “Evet!”', samples, RATE))


class TaggedPieceTests(unittest.TestCase):
    def engine(self, replies):
        server = FakeServer()
        self.addCleanup(server.close)
        server.replies = replies
        engine = drama3.Engine(tempfile.gettempdir(), prefs=lambda: {'drama3_url': server.url})
        engine.reference = {'text': 'Kayıt.', 'data': 'QUJD', 'seconds': 3}
        return engine, server

    def test_endless_laugh_is_requested_without_the_tag(self):
        from test_drama3 import spoken, silence, tone
        engine, server = self.engine([(200, drama3.wav_bytes(tone(drama3.CAP_SECONDS) + silence(0.5), RATE)),
                                      (200, spoken(3.0))])
        engine.say('- Bu kim? dedim, sen bu dört yüz bin liralık adamın nasıl velinimeti oluyorsun?', 1.0, '[laughs]')
        self.assertEqual([body['input'] for _, body in server.requests],
                         ['[laughs] - Bu kim? dedim, sen bu dört yüz bin liralık adamın nasıl velinimeti oluyorsun?',
                          '- Bu kim? dedim, sen bu dört yüz bin liralık adamın nasıl velinimeti oluyorsun?'])

    def test_last_retry_drops_the_tag(self):
        from test_drama3 import silence, tone
        cut = drama3.wav_bytes(tone(1.0) + silence(5.0), RATE)
        engine, server = self.engine([(200, cut)] * 3)
        engine.say('— Kaç kere söyledim, kapıyı açık bırakmayın, dedi adam!', 1.0, '[angry]')
        inputs = [body['input'] for _, body in server.requests]
        self.assertEqual(len(inputs), 1 + len(drama3.SILENT_RETRY_TEMPERATURES))
        self.assertTrue(all(text.startswith('[angry] ') for text in inputs[:-1]))
        self.assertFalse(inputs[-1].startswith('['))


class EngineTests(unittest.TestCase):
    """tts.Engines etiketi motor.json "emotion_tags" olan motora iletir ve onbellek anahtarina katar."""

    def setUp(self):
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prefs = {'drama3_url': self.server.url, 'voices': {'tr': 'drama3/clone'},
                      'options': {'drama3/clone': {'reference': 'C:/ses/kayit.wav', 'reference_text': 'Merhaba.'}}}
        self.table = {'— Gel buraya.': '[shouting]'}
        self.engines = Engines(Path(self.temp.name), REPO / 'engines', prefs=lambda: self.prefs,
                               emotion=lambda book, text: self.table.get(text, ''))
        self.addCleanup(self.engines.shutdown)

    def test_tag_reaches_the_server_and_the_cache_key(self):
        plain = Engines(Path(self.temp.name), REPO / 'engines', prefs=lambda: self.prefs)
        self.assertNotEqual(self.engines._cache_path(BOOK, '— Gel buraya.', 1.0, 'tr'),
                            plain._cache_path(BOOK, '— Gel buraya.', 1.0, 'tr'))
        self.assertEqual(self.engines._cache_path(BOOK, '— Otur.', 1.0, 'tr'), plain._cache_path(BOOK, '— Otur.', 1.0, 'tr'))
        self.assertEqual(self.engines.emotion_tag(None, '— Gel buraya.'), '')
        self.assertEqual(self.engines.emotion_tag(BOOK, '— Gel buraya.', override={'voice': 'drama3/clone'}), '')
        prepared = {'text': 'Merhaba.', 'data': 'QUJD', 'seconds': 4.0}
        with patch('drama3.prepare_reference', return_value=prepared):
            self.engines.load('tr')
            end = time.time() + 20
            while self.engines.state == 'loading' and time.time() < end:
                time.sleep(0.05)
        self.assertEqual(self.engines.state, 'ready', self.engines.message)
        self.engines.say('— Gel buraya.', 1.0, BOOK)
        self.assertEqual(self.server.requests[-1][1]['input'], '[shouting] — Gel buraya.')
        self.engines.say('— Gel buraya.', 1.0, None)    # kitap disi (sohbet): etiket yok
        self.assertEqual(self.server.requests[-1][1]['input'], '— Gel buraya.')

    def test_emotion_cache_tag_renews_only_that_tag(self):
        self.table['— Sus.'] = '[fısıldar]'
        before = {text: self.engines._cache_path(BOOK, text, 1.0, 'tr') for text in self.table}
        manifest = json.loads((REPO / 'engines' / 'drama3' / 'motor.json').read_text(encoding='utf-8'))
        manifest['emotion_cache_tags'] = {'[fısıldar]': 'baska'}
        with patch.object(self.engines, '_manifests', return_value={'drama3': manifest}):
            self.assertNotEqual(self.engines._cache_path(BOOK, '— Sus.', 1.0, 'tr'), before['— Sus.'])
            self.assertEqual(self.engines._cache_path(BOOK, '— Gel buraya.', 1.0, 'tr'), before['— Gel buraya.'])

    def test_engine_without_flag_gets_no_tag(self):
        manifest = json.loads((REPO / 'engines' / 'drama3' / 'motor.json').read_text(encoding='utf-8'))
        manifest.pop('emotion_tags')
        with patch.object(self.engines, '_manifests', return_value={'drama3': manifest}):
            self.assertEqual(self.engines.emotion_tag(BOOK, '— Gel buraya.'), '')



class AudiobookKeyTests(unittest.TestCase):
    def test_tags_change_the_stored_chapter(self):
        import audiobook
        from test_audiobook_dub import FakeEngines
        with tempfile.TemporaryDirectory() as folder:
            engines = FakeEngines(folder)
            chapter = {'title': 'Bir', 'sentences': ['— Gel.', 'Gitti.'], 'gaps': [0.3, 0.3]}
            plain = audiobook.chapter_key(engines, chapter, 1.0, 'tr', book=BOOK)
            engines.emotions['— Gel.'] = '[shouting]'
            self.assertNotEqual(audiobook.chapter_key(engines, chapter, 1.0, 'tr', book=BOOK), plain)
            self.assertEqual(audiobook.chapter_key(engines, chapter, 1.0, 'tr'), audiobook.chapter_key(
                FakeEngines(folder), chapter, 1.0, 'tr'))


if __name__ == '__main__':
    unittest.main()
