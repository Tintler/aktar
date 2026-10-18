"""Ceviri dil cifti testleri (F151)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import app_core
import book_core
import epub_import
import epub_output
import fonts
import languages
import media
import series
import subtitle
from test_book_core import make_epub


class AdaptTests(unittest.TestCase):
    def test_default_pair_keeps_prompts_byte_for_byte(self):
        for text in (app_core.read(app_core.prompt_path()), app_core.TERM_ANALYSIS_PROMPT,
                     book_core.read(book_core.prompt_path()), book_core.ANALYSIS_PROMPT, book_core.DECISIONS_PROMPT):
            self.assertIs(languages.adapt(text, {}), text)
            self.assertEqual(languages.adapt(text, {'source_language': 'en', 'target_language': 'tr'}), text)
        self.assertEqual(app_core.translation_prompt({}), app_core.read(app_core.prompt_path()))
        self.assertEqual(book_core.book_prompt({}), book_core.read(book_core.prompt_path()))

    def test_german_target_drops_turkish_only_rules(self):
        prompt = app_core.translation_prompt({'source_language': 'en', 'target_language': 'de'})
        self.assertIn('natural, fluent German', prompt)
        self.assertNotIn('Turkish', prompt)
        self.assertNotIn('sen/siz', prompt)
        self.assertIn('formal/informal', prompt)
        book = book_core.book_prompt({'source_language': 'ja', 'target_language': 'de'})
        self.assertIn('literary Japanese into natural, fluent German', book)
        self.assertNotIn('indefinite articles', book)
        self.assertNotIn('English', book)

    def test_auto_source_and_kept_turkish_reasons(self):
        prompt = languages.adapt(app_core.TERM_ANALYSIS_PROMPT, {'source_language': 'auto', 'target_language': 'fr'})
        self.assertIn('supplied subtitle text for durable French', prompt)
        self.assertIn('short Turkish reason', prompt)
        self.assertNotIn('English', prompt)
        # Turkce hedefte sen/siz kalir, yalnizca kaynak adi degisir.
        prompt = app_core.translation_prompt({'source_language': 'ja', 'target_language': 'tr'})
        self.assertIn('sen/siz', prompt)
        self.assertIn('Turkish suffixes', prompt)

    def test_validate(self):
        languages.validate({'source_language': 'auto', 'target_language': 'ja'})
        with self.assertRaises(ValueError):
            languages.validate({'source_language': 'de', 'target_language': 'de'})
        with self.assertRaises(ValueError):
            languages.validate({'target_language': 'xx'})
        cfg = dict(app_core.DEFAULT_CONFIG, target_language='auto')
        with self.assertRaises(ValueError):
            app_core.validate_config(cfg)


class GlossaryMatchTests(unittest.TestCase):
    def test_loose_search_allows_inflection(self):
        self.assertTrue(languages.loose_search('Schwert', 'Er zog die Schwertes Klinge.'))
        self.assertTrue(languages.loose_search('Drachenreiter', 'die Drachenreitern folgten'))
        self.assertTrue(languages.loose_search('Ледяной меч', 'Он поднял Ледяной меча.'))
        self.assertFalse(languages.loose_search('Schwert', 'Ein Messer.'))
        self.assertTrue(languages.loose_search('魔法', 'それは魔法だ'))

    def test_glossary_missing_uses_target_language(self):
        glossary = [{'source': 'Ash', 'target': 'Asche'}]
        self.assertEqual(app_core.glossary_missing('Ash fell.', 'Die Asche fiel.', glossary, 'de'), [])
        self.assertEqual(app_core.glossary_missing('Ash fell.', 'Der Staub fiel.', glossary, 'de'), glossary)
        # Turkce hedef eski kurali kullanir.
        self.assertEqual(app_core.glossary_missing('Ash fell.', 'Kül düştü.', [{'source': 'Ash', 'target': 'Kül'}]), [])

    def test_cjk_source_terms_match_without_word_boundaries(self):
        self.assertTrue(app_core.source_term_regex('魔法').search('それは魔法だ'))
        self.assertTrue(book_core.source_term_regex('魔法').search('それは魔法だ'))
        self.assertFalse(app_core.source_term_regex('Ash').search('ashamed'))


class OutputTests(unittest.TestCase):
    def test_output_tag_and_path(self):
        self.assertEqual(languages.output_tag({}), '_TR')
        self.assertEqual(languages.output_tag({'target_language': 'de'}), '_DE')
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / 'Movie.mkv'
            self.assertEqual(media.unique_output_path(video, 'srt', '_JA').name, 'Movie_JA.srt')

    def test_render_output_checks_target_language_glyphs(self):
        text = ('[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n'
                'Format: Name, Fontname, Fontsize\nStyle: Default,Gandhi Sans,20\n\n'
                '[Events]\nFormat: Layer, Start, End, Style, Text\n'
                'Dialogue: 0,0:00:01.00,0:00:02.00,Default,Hello\n')
        kind, payload = subtitle.parse_by_extension(text, '.ass')
        cues = subtitle.cues_of(kind, payload)
        with mock.patch.object(fonts, 'supports_chars', return_value=False) as check:
            _text, replacements = app_core.render_output(kind, payload, cues, language='ja')
        self.assertEqual(replacements, {'Gandhi Sans': 'Yu Gothic'})
        self.assertEqual(check.call_args[0][1], languages.FONT_SAMPLES['ja'][0])
        with mock.patch.object(fonts, 'supports_chars', return_value=False):
            _text, replacements = app_core.render_output(kind, payload, cues, language='en')
        self.assertEqual(replacements, {})


class SeriesLanguageTests(unittest.TestCase):
    def test_series_language(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict('os.environ', {'AKTAR_SERIES_DIR': temp}):
            series.create_series('Alpha')
            series.create_series('Beta', target_language='de')
            self.assertEqual(series.series_language('alpha'), 'tr')
            self.assertNotIn('target_language', series.load_series('alpha'))
            self.assertEqual(series.series_language('beta'), 'de')


class BookLanguageTests(unittest.TestCase):
    def test_prepare_records_pair_and_output_uses_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            epub = root / 'book.epub'
            make_epub(epub)
            book = epub_import.prepare(epub, root / 'work', 'auto', 'de')
            marker = json.loads((book / 'epub-import.json').read_text(encoding='utf-8'))
            self.assertEqual((marker['source_language'], marker['target_language']), ('auto', 'de'))
            self.assertEqual(languages.book_pair(book), ('auto', 'de'))
            context = (book / '00-CONTEXT.md').read_text(encoding='utf-8')
            self.assertIn('**Direction:** source language → German', context)
            self.assertIn('natural literary German', context)
            for name in marker['files']:
                (book / 'translation' / name).write_text((book / 'source' / name).read_text(encoding='utf-8'),
                                                         encoding='utf-8')
            output = epub_output.build_translated_epub(book, log=lambda *_: None)
            output = Path(output if not isinstance(output, (tuple, list)) else output[0])
            self.assertTrue(output.name.endswith(' DE.epub'), output.name)
            with zipfile.ZipFile(output) as archive:
                opf = archive.read('OEBPS/content.opf').decode('utf-8')
                nav = next(archive.read(n).decode('utf-8') for n in archive.namelist() if n.endswith('nav.xhtml'))
            self.assertIn('>de</dc:language>', opf)
            self.assertIn('Inhalt', nav)

    def test_default_project_has_no_language_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            epub = root / 'book.epub'
            make_epub(epub)
            book = epub_import.prepare(epub, root / 'work')
            marker = json.loads((book / 'epub-import.json').read_text(encoding='utf-8'))
            self.assertNotIn('target_language', marker)
            self.assertEqual(languages.book_pair(book), ('en', 'tr'))
            self.assertIn('English → Turkish', (book / '00-CONTEXT.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
