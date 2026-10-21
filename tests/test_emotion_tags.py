import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import json
from pathlib import Path
import tempfile
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


class StoreTests(unittest.TestCase):
    def test_round_trip_and_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            store = emotion_tags.Store(folder)
            store.update(BOOK, 'words', ['— Bir.', '— İki.'], ['[laughs]', ''])
            store.update(BOOK, 'llm', ['— Bir.', '— İki.'], ['', '[angry]'])
            fresh = emotion_tags.Store(folder)
            self.assertEqual(fresh.tag(BOOK, '— Bir.', 'words'), '[laughs]')
            self.assertEqual(fresh.tag(BOOK, '— Bir.', 'llm'), '[laughs]')   # model vermedi: kelime listesi
            self.assertEqual(fresh.tag(BOOK, '— İki.', 'llm'), '[angry]')
            self.assertEqual(fresh.tag(BOOK, '— Bir.', 'off'), '')
            self.assertTrue(fresh.has_llm(BOOK, ['— Bir.']))
            self.assertFalse(fresh.has_llm(BOOK, ['— Üç.']))
            fresh.clear(BOOK)
            self.assertEqual(emotion_tags.Store(folder).tag(BOOK, '— Bir.', 'words'), '')

    def test_bad_book_id(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                emotion_tags.Store(folder).update('../x', 'words', ['a'], ['[laughs]'])


class Drama3TextTests(unittest.TestCase):
    def test_tag_goes_before_the_quote(self):
        self.assertEqual(drama3.tagged('O fısıldayarak: “Sessiz ol,” dedi.', '[fısıldar]'),
                         'O fısıldayarak: [fısıldar] “Sessiz ol,” dedi.')
        self.assertEqual(drama3.tagged('"Gel!" diye bağırdı.', '[shouting]'), '[shouting] "Gel!" diye bağırdı.')
        self.assertEqual(drama3.tagged('— Ne yapalım.', '[sighs]'), '[sighs] — Ne yapalım.')
        self.assertEqual(drama3.tagged('Metin.', '[crying]'), 'Metin.')

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
