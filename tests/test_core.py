"""Aktar cekirdek testleri (unittest). PySide6 gerektirmez.

Calistirma:
    cd /d Z:\\LLM-Files\\Projects\\Aktar
    py -3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_core
import fonts
import media
import series
import subtitle
from app_core import (FileLock, PauseController, TranslationEngine, _dedupe_glossary,
                      _target_search, candidate_terms, clean_response, glossary_missing,
                      load_config, merge_glossaries, parse_term_analysis,
                      retryable_translation_error, source_term_regex, validate_config,
                      visible_cue_text)


class ConfigTests(unittest.TestCase):
    def test_default_config_is_valid(self):
        validate_config(dict(app_core.DEFAULT_CONFIG))

    def test_non_local_base_url_is_rejected(self):
        cfg = dict(app_core.DEFAULT_CONFIG, base_url='http://example.com/v1')
        with self.assertRaises(ValueError):
            validate_config(cfg)

    def test_retry_count_bounds(self):
        cfg = dict(app_core.DEFAULT_CONFIG, auto_retry_count=0)
        with self.assertRaises(ValueError):
            validate_config(cfg)

    def test_retryable_error_classification(self):
        self.assertTrue(retryable_translation_error(ValueError('Yanit eksik.')))
        self.assertTrue(retryable_translation_error(RuntimeError('HTTP 429: x')))
        self.assertFalse(retryable_translation_error(RuntimeError('HTTP 403: x')))
        self.assertFalse(retryable_translation_error(ValueError('Glossary zorunlulugu saglanamadi')))


class GlossaryTests(unittest.TestCase):
    def test_dedupe_keeps_first_entry(self):
        items = [{'source': 'Ash', 'target': 'Kul'},
                 {'source': 'ash', 'target': 'Kül'},
                 {'source': '', 'target': 'x'}]
        self.assertEqual(_dedupe_glossary(items), [{'source': 'Ash', 'target': 'Kul'}])

    def test_merge_glossaries_later_layer_wins(self):
        base = [{'source': 'White Walker', 'target': 'Ak Gezen'},
                {'source': 'Wight', 'target': 'Olu'}]
        override = [{'source': 'Wight', 'target': 'Hayalet'}]
        merged = merge_glossaries(base, override)
        self.assertEqual(merged, [{'source': 'White Walker', 'target': 'Ak Gezen'},
                                  {'source': 'Wight', 'target': 'Hayalet'}])

    def test_source_term_regex_whole_word_only(self):
        self.assertTrue(source_term_regex('Ash').search('Ash kapida'))
        self.assertFalse(source_term_regex('Ash').search('He was ashamed.'))

    def test_target_search_accepts_turkish_inflections(self):
        self.assertTrue(_target_search('Yapi', 'yapilar'))
        self.assertTrue(_target_search('Yapi', 'yapisinin'))
        self.assertTrue(_target_search('Yapi', 'yapida'))
        self.assertFalse(_target_search('kul', 'kulot'))


class CandidateTermTests(unittest.TestCase):
    """On analiz aday terim tarayicisi (app_core.candidate_terms)."""

    def _cues(self, *texts):
        return [subtitle.Cue([text]) for text in texts]

    def test_multiword_proper_noun_is_candidate(self):
        cues = self._cues('White Walker geldi.', 'White Walker gitti.')
        sources = [item['source'] for item in candidate_terms(cues)]
        self.assertIn('White Walker', sources)

    def test_sentence_initial_single_word_is_not_candidate(self):
        cues = self._cues('Hello there.', 'Hello again.')
        sources = [item['source'] for item in candidate_terms(cues)]
        self.assertNotIn('Hello', sources)

    def test_single_word_needs_min_count(self):
        # Tek kelimeli aday >=4 harf olmali ve en az min_count kez gecmeli.
        # (Ardisik iki buyuk harfli kelime cok-kelimeli obek sayilir; bu yuzden
        #  tek kelimelik adi kucuk harfli kelimelerle saralim.)
        cues = self._cues('We saw Owen here.', 'and Owen left.')
        sources = [item['source'] for item in candidate_terms(cues)]
        self.assertIn('Owen', sources)
        single = self._cues('We saw Owen here.')
        self.assertEqual([item['source'] for item in candidate_terms(single)], [])

    def test_untranslatable_cues_are_skipped(self):
        cues = [subtitle.Cue([], raw='Comment: ...'),
                subtitle.Cue(['White Walker geldi.', 'White Walker gitti.'])]
        sources = [item['source'] for item in candidate_terms(cues)]
        self.assertEqual(sources, ['White Walker'])

    def test_ass_line_break_is_removed_before_candidate_scan(self):
        cues = self._cues(r'Now, is there anything \Nthe three of you want?',
                          r'Land, a title... \NAnything I can do.')
        sources = [item['source'] for item in candidate_terms(cues)]
        self.assertNotIn('Nthe', sources)
        self.assertNotIn('NAnything', sources)


class TermAnalysisTests(unittest.TestCase):
    def test_pre_analysis_accepts_lowercase_fictional_term_and_target(self):
        raw = json.dumps({'terms': [{'source': 'forestkin', 'target': 'orman halki',
                                    'type': 'race', 'reason': 'kurgu halki'}],
                          'decisions': [{'type': 'proper_name',
                                         'value': 'Dias adi degistirilmeden korunur',
                                         'reason': 'ozel ad'}]})
        result = parse_term_analysis(raw, 'The forestkin protect the forest.')
        self.assertEqual(result['terms'][0]['target'], 'orman halki')
        self.assertEqual(result['terms'][0]['count'], 1)
        self.assertEqual(len(result['decisions']), 1)

    def test_post_analysis_rejects_target_not_used_in_translation(self):
        raw = json.dumps({'terms': [{'source': 'miasma', 'target': 'zehirli sis',
                                    'type': 'term', 'reason': ''}], 'decisions': []})
        result = parse_term_analysis(raw, 'disease and miasma', 'hastalik ve miazma')
        self.assertEqual(result['terms'], [])

    def test_engine_analysis_is_checkpointed_and_resumed(self):
        cfg = dict(app_core.DEFAULT_CONFIG, analysis_chunk_chars=1000)
        answer = json.dumps({'terms': [{'source': 'forestkin', 'target': 'orman halki',
                                       'type': 'race', 'reason': 'kalici'}],
                             'decisions': []})

        class FakeClient:
            calls = 0
            def __init__(self, _cfg, log=None): pass
            def generate(self, *_args, **_kwargs):
                FakeClient.calls += 1
                return answer

        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(app_core, 'Client', FakeClient):
            checkpoint = Path(folder) / 'analysis.json'
            engine = TranslationEngine(lambda: cfg, log=lambda _message: None)
            result = engine.analyze_terms([subtitle.Cue(['The forestkin arrived.'])],
                                          checkpoint=checkpoint)
            again = engine.analyze_terms([subtitle.Cue(['The forestkin arrived.'])],
                                         checkpoint=checkpoint)
        self.assertEqual(result, again)
        self.assertEqual(FakeClient.calls, 1)

    def test_post_approved_term_is_enforced_in_current_episode(self):
        cfg = dict(app_core.DEFAULT_CONFIG)

        class FixClient:
            def __init__(self, _cfg, log=None): pass
            def generate(self, *_args, **_kwargs):
                return 'ID: 1\nTEXT: Orman halki burada.'

        source = [subtitle.Cue(['The forestkin are here.'])]
        translated = [subtitle.Cue(['Ormanlilar burada.'])]
        with mock.patch.object(app_core, 'Client', FixClient):
            fixed = TranslationEngine(lambda: cfg, log=lambda _message: None).enforce_episode_terms(
                source, translated, [{'source': 'forestkin', 'target': 'Orman halki'}])
        self.assertEqual(fixed[0].text, 'Orman halki burada.')


class RealAssRegressionTests(unittest.TestCase):
    """Kullanici tarafindan verilen iki ASS dosyasindan turetilen regresyonlar."""

    FIXTURES = Path(__file__).parent / 'fixtures'

    def _paths(self):
        paths = sorted(self.FIXTURES.glob('*-regression.ass'))
        external = os.environ.get('AKTAR_REAL_ASS_DIR')
        if external:
            paths.extend(sorted(Path(external).glob('*.ass')))
        return paths

    def test_two_real_ass_families_parse_normalize_and_round_trip(self):
        paths = self._paths()
        self.assertGreaterEqual(len(paths), 2)
        for path in paths:
            with self.subTest(path=path.name):
                text = path.read_text(encoding='utf-8-sig')
                kind, payload = subtitle.parse_by_extension(text, '.ass')
                cues = subtitle.cues_of(kind, payload)
                self.assertTrue(cues)
                visible = '\n'.join(visible_cue_text(cue) for cue in cues)
                self.assertNotRegex(visible, r'\\[Nnh]')
                rendered = subtitle.render_by_kind(kind, payload, cues)
                reparsed_kind, reparsed = subtitle.parse_by_extension(rendered, '.ass')
                self.assertEqual(reparsed_kind, 'ass')
                self.assertEqual(len(subtitle.cues_of(kind, payload)),
                                 len(subtitle.cues_of(reparsed_kind, reparsed)))

    def test_real_ass_candidate_scan_has_no_linebreak_artifacts(self):
        for path in self._paths():
            with self.subTest(path=path.name):
                kind, payload = subtitle.parse_by_extension(
                    path.read_text(encoding='utf-8-sig'), '.ass')
                sources = [item['source'] for item in candidate_terms(subtitle.cues_of(kind, payload))]
                self.assertFalse(any(re.fullmatch(r'N(?:and|the|for|are|they|named).*', item, re.I)
                                     for item in sources), sources)

    def test_real_ass_files_pass_translation_assembly(self):
        cfg = dict(app_core.DEFAULT_CONFIG, batch_cues=1000)

        class EchoClient:
            def __init__(self, _cfg, log=None): pass
            def generate(self, _system, user, **_kwargs):
                return user.split('SOURCE TO TRANSLATE:\n', 1)[1]

        with mock.patch.object(app_core, 'Client', EchoClient):
            for path in self._paths():
                with self.subTest(path=path.name):
                    text = path.read_text(encoding='utf-8-sig')
                    kind, payload = subtitle.parse_by_extension(text, '.ass')
                    cues = subtitle.cues_of(kind, payload)
                    translated = TranslationEngine(
                        lambda: cfg, log=lambda _message: None).translate(cues)
                    subtitle.validate_structure(cues, translated)
                    rendered = subtitle.render_by_kind(kind, payload, translated)
                    self.assertIn('[Events]', rendered)


class FileLockTests(unittest.TestCase):
    def test_lock_is_exclusive_and_releasable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'x.lock'
            first = FileLock(path).acquire()
            with self.assertRaises(RuntimeError):
                FileLock(path).acquire()
            first.release()
            second = FileLock(path).acquire()
            second.release()


class SeriesTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._old = os.environ.get('AKTAR_SERIES_DIR')
        os.environ['AKTAR_SERIES_DIR'] = self._temp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop('AKTAR_SERIES_DIR', None)
        else:
            os.environ['AKTAR_SERIES_DIR'] = self._old
        self._temp.cleanup()

    def test_slugify_ascii(self):
        self.assertEqual(series.slugify('Game of Thrones'), 'game-of-thrones')
        self.assertEqual(series.slugify('Sehrazat Çölü'), 'sehrazat-colu')

    def test_create_and_list_series(self):
        data = series.create_series('Game of Thrones', ['Game of Thrones', 'GoT'])
        self.assertEqual(data['title'], 'Game of Thrones')
        self.assertIn('game-of-thrones', series.list_series())
        with self.assertRaises(ValueError):
            series.create_series('Game of Thrones')

    def test_suggest_series_from_folder_name(self):
        series.create_series('Game of Thrones', ['Game of Thrones'])
        video = Path(self._temp.name) / 'Game of Thrones' / 'S01E01.mkv'
        self.assertEqual(series.suggest_series(video), 'game-of-thrones')
        other = Path(self._temp.name) / 'Breaking Bad' / 'S01E01.mkv'
        self.assertIsNone(series.suggest_series(other))

    def test_ambiguous_series_match_is_not_silently_selected(self):
        series.create_series('First', ['Shared Folder'])
        series.create_series('Second', ['Shared Folder'])
        video = Path(self._temp.name) / 'Shared Folder' / 'S01E01.mkv'
        self.assertEqual(len(series.matching_series(video)), 2)
        self.assertIsNone(series.suggest_series(video))

    def test_guess_series_title_removes_fansub_episode_and_quality(self):
        path = '[SubsPlease] Ryoumin 0-nin Start - 06 (1080p) [ABC123].mkv'
        self.assertEqual(series.guess_series_title(path), 'Ryoumin 0-nin Start')

    def test_generic_download_folder_is_not_saved_as_hint(self):
        data = series.create_series('Ryoumin', ['qbit', 'Season 1', 'Ryoumin'])
        self.assertEqual(data['folder_hints'], ['Ryoumin'])

    def test_add_knowledge_preserves_existing_and_metadata(self):
        series.create_series('Test')
        series.add_knowledge('test', [
            {'source': 'forestkin', 'target': 'orman halki', 'type': 'race',
             'origin': 'pre_analysis', 'locked': True},
        ], ['Dias adi korunur'], 'E01.mkv')
        series.add_knowledge('test', [
            {'source': 'forestkin', 'target': 'ormanlilar'},
            {'source': 'miasma', 'target': 'miazma', 'type': 'term'},
        ], ['Dias adi korunur'], 'E02.mkv')
        data = series.load_series('test')
        self.assertEqual(data['glossary'][0]['target'], 'orman halki')
        self.assertEqual(data['glossary'][0]['type'], 'race')
        self.assertEqual(data['glossary'][1]['first_seen'], 'E02.mkv')
        self.assertEqual(data['decisions'], ['Dias adi korunur'])

    def test_add_episode_is_idempotent(self):
        series.create_series('Breaking Bad')
        series.add_episode('breaking-bad', 'S01E01.mkv')
        data = series.add_episode('breaking-bad', 'S01E01.mkv')
        self.assertEqual(len(data['episodes']), 1)

    def test_series_glossary_and_decisions(self):
        series.create_series('Test')
        data = series.load_series('test')
        data['glossary'] = [{'source': 'A', 'target': 'B'}]
        data['decisions'] = ['sen/siz kurali']
        series.save_series(data, slug='test')
        self.assertEqual(series.series_glossary('test'), [{'source': 'A', 'target': 'B'}])
        self.assertEqual(series.series_decisions('test'), ['sen/siz kurali'])

    def test_missing_series_raises(self):
        with self.assertRaises(ValueError):
            series.load_series('yok-boyle-bir-sey')


class SubtitleSrtTests(unittest.TestCase):
    SAMPLE = ('1\n00:00:01,000 --> 00:00:03,000\nHello there.\n\n'
              '2\n00:00:04,000 --> 00:00:06,500\nHow are you?\nSecond line.\n')

    def test_srt_round_trip_preserves_structure(self):
        cues = subtitle.parse_srt(self.SAMPLE)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start, '00:00:01,000')
        self.assertEqual(cues[1].lines, ['How are you?', 'Second line.'])
        rendered = subtitle.render_srt(cues)
        self.assertEqual(subtitle.render_srt(subtitle.parse_srt(rendered)), rendered)

    def test_srt_multiline_text_keeps_lines(self):
        cues = subtitle.parse_srt(self.SAMPLE)
        self.assertEqual(cues[1].text, 'How are you?\nSecond line.')

    def test_validate_structure_detects_line_count_change(self):
        cues = subtitle.parse_srt(self.SAMPLE)
        broken = [subtitle.Cue(['Only one']), subtitle.Cue(['Only one line'])]
        with self.assertRaises(ValueError):
            subtitle.validate_structure(cues, broken)

    def test_translation_request_and_response_round_trip(self):
        cues = subtitle.parse_srt(self.SAMPLE)
        request = subtitle.build_translation_request([cue.text for cue in cues], 1)
        self.assertIn('ID: 1', request)
        self.assertIn('ID: 2', request)
        response = 'ID: 1\nTEXT: Merhaba.\n\nID: 2\nTEXT: Nasilsin?\nIkinci satir.'
        found = subtitle.parse_translation_response(response, [1, 2])
        self.assertEqual(found[2], 'Nasilsin?\nIkinci satir.')

    def test_translation_response_missing_id_is_rejected(self):
        with self.assertRaises(ValueError):
            subtitle.parse_translation_response('ID: 1\nTEXT: x', [1, 2])

    def test_translation_response_allows_dropped_text_label(self):
        # Gercek calismada (Sakamoto Days 12) model bazi girdilerde "TEXT:"
        # etiketini dusurdu; ID kumesi tam oldugu halde ayristirma eksik
        # sayip ceviriyi kalici olarak durduruyordu.
        response = ('ID: 1\nTEXT: Birinci.\n\n'
                    'ID: 2\nIkinci etiketsiz.\n\n'
                    'ID: 3\nTEXT: Ucuncu.')
        found = subtitle.parse_translation_response(response, [1, 2, 3])
        self.assertEqual(found[1], 'Birinci.')
        self.assertEqual(found[2], 'Ikinci etiketsiz.')
        self.assertEqual(found[3], 'Ucuncu.')

    def test_translation_response_dropped_label_multiline_value(self):
        response = 'ID: 1\nTEXT: Birinci.\n\nID: 2\nIkinci.\nIkinci devam.'
        found = subtitle.parse_translation_response(response, [1, 2])
        self.assertEqual(found[2], 'Ikinci.\nIkinci devam.')

    def test_ambiguous_batch_responses_are_rejected(self):
        # F28/F29's positional fallback silently discarded native list numbers.
        for response, ids in [
            ('1. First\n2. Second', [1, 2]),
            ('2. Second\n1. First', [1, 2]),
            ('1) First\n2- Second', [1, 2]),
            ('1. First\n2. Second\n1. First', [1, 2, 3]),
            ('First\n\nSecond', [1, 2]),
            ('1. First', [1, 2]),
        ]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                subtitle.parse_translation_response(response, ids)

    def test_singleton_preserves_native_numbering_and_paragraphs(self):
        text = '1. First\n2. Second\n\nLast paragraph'
        self.assertEqual(subtitle.parse_translation_response(text, [1]), {1: text})

    def test_duplicate_ids_and_text_labels_rejected(self):
        for text in ['ID: 1\nTEXT: A\nID: 1\nTEXT: B\nID: 2\nTEXT: C',
                     'ID: 1\nTEXT: A\nTEXT: B',
                     'ID: 1\nA\nTEXT: B']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                subtitle.parse_translation_response(text, [1])

    def test_invalid_singleton_protocol_rejected(self):
        for text in ['ID: nope\nTEXT: A', 'TEXT: A', 'ID: 1\nTEXT:',
                     'Explanation\nID: 1\nTEXT: A',
                     'ID: 1\nTEXT: A\nID: nope\nB']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                subtitle.parse_translation_response(text, [1])

    def test_translation_response_labeled_with_inline_text(self):
        # Model `ID: 1 TEXT: ...` bicimini tek satirda da uretebiliyor.
        response = 'ID: 1 TEXT: Merhaba.\n\nID: 2 TEXT: Hosca kal.\nIkinci satir.'
        found = subtitle.parse_translation_response(response, [1, 2])
        self.assertEqual(found[1], 'Merhaba.')
        self.assertEqual(found[2], 'Hosca kal.\nIkinci satir.')

    def test_translation_response_does_not_mix_labeled_and_numbered(self):
        # Etiketli bicim kismi geldiyse numarali bicime DUSULMEZ; eksik ID
        # yine anlamli hata uretir.
        with self.assertRaises(ValueError):
            subtitle.parse_translation_response('ID: 1\nTEXT: Birinci.', [1, 2])

    def test_analyze_preserves_leading_and_trailing_tags(self):
        text = '{\\i1}Hello world{\\i0}'
        analysis = subtitle.analyze(text)
        self.assertEqual(subtitle.send_text(analysis), 'Hello world')
        self.assertEqual(subtitle.rebuild(analysis, 'Merhaba dünya'), '{\\i1}Merhaba dünya{\\i0}')
        self.assertEqual(subtitle.dropped_tags(analysis), 0)

    def test_analyze_keeps_line_breaks_and_tags(self):
        text = '{\\an7}Reigning Sword Saint\\N{\\fs24}Owen Koath'
        analysis = subtitle.analyze(text)
        self.assertEqual(subtitle.send_text(analysis), 'Reigning Sword Saint\nOwen Koath')
        self.assertEqual(subtitle.rebuild(analysis, 'Hüküm Süren Kılıç Azizi\nOwen Koath'),
                         '{\\an7}Hüküm Süren Kılıç Azizi\\N{\\fs24}Owen Koath')

    def test_rebuild_reflows_merged_multiline_translation(self):
        # Model iki satiri birlestirdiginde ceviri kaynak satir sayisina gore
        # (kelime sinirinda) yeniden bolunur; yapi korunur (F11).
        analysis = subtitle.analyze('{\\an7}Reigning Sword Saint\\N{\\fs24}Owen Koath')
        self.assertEqual(
            subtitle.rebuild(analysis, 'Hüküm Süren Kılıç Azizi Owen Koath'),
            '{\\an7}Hüküm Süren Kılıç Azizi\\N{\\fs24}Owen Koath')

    def test_rebuild_collapses_extra_lines_to_source_count(self):
        analysis = subtitle.analyze('{\\an7}One\\NTwo')
        self.assertEqual(subtitle.rebuild(analysis, 'Bir\nIki\nUc'), '{\\an7}Bir Iki\\NUc')

    def test_rebuild_reports_line_count_change(self):
        analysis = subtitle.analyze('A\\NB')
        notes = []
        subtitle.rebuild(analysis, 'tek satir', note=lambda expected, found: notes.append((expected, found)))
        self.assertEqual(notes, [(2, 1)])

    def test_rebuild_collapses_extra_lines_for_single_line_cue(self):
        analysis = subtitle.analyze('Hello')
        notes = []
        result = subtitle.rebuild(analysis, 'Merhaba\nDunya', note=lambda e, f: notes.append((e, f)))
        self.assertEqual(result, 'Merhaba Dunya')
        self.assertEqual(notes, [(1, 2)])

    def test_rebuild_keeps_exact_line_count_untouched(self):
        analysis = subtitle.analyze('{\\i1}A\\NB{\\i0}')
        notes = []
        result = subtitle.rebuild(analysis, 'Bir\nIki', note=lambda e, f: notes.append((e, f)))
        self.assertEqual(result, '{\\i1}Bir\\NIki{\\i0}')
        self.assertEqual(notes, [])

    def test_analyze_preserves_mid_line_tags(self):
        analysis = subtitle.analyze('C{\\fs38}L{\\fs36}E')
        self.assertEqual(subtitle.dropped_tags(analysis), 0)
        self.assertEqual(subtitle.rebuild(analysis, 'KLM'), 'K{\\fs38}L{\\fs36}M')

    def test_analyze_without_markup_is_plain(self):
        analysis = subtitle.analyze('plain text')
        self.assertEqual(subtitle.send_text(analysis), 'plain text')
        self.assertEqual(subtitle.dropped_tags(analysis), 0)


class SubtitleVttTests(unittest.TestCase):
    SAMPLE = ('WEBVTT\n\nNOTE bu bir not\n\n'
              '00:00:01.000 --> 00:00:03.000\nHello.\n\n'
              'cue-2\n00:00:04.000 --> 00:00:06.000\nWorld.\n')

    def test_vtt_parse_skips_notes(self):
        cues = subtitle.parse_vtt(self.SAMPLE)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].lines, ['Hello.'])
        self.assertEqual(cues[1].index, 'cue-2')

    def test_vtt_render_round_trip(self):
        cues = subtitle.parse_vtt(self.SAMPLE)
        rendered = subtitle.render_vtt(cues)
        self.assertTrue(rendered.startswith('WEBVTT'))
        self.assertEqual(subtitle.render_vtt(subtitle.parse_vtt(rendered)), rendered)


class SubtitleAssTests(unittest.TestCase):
    SAMPLE = ('[Script Info]\nTitle: Test\n\n[V4+ Styles]\n'
              'Format: Name, Fontname\nStyle: Default,Arial\n\n'
              '[Events]\nFormat: Layer, Start, End, Style, Text\n'
              'Dialogue: 0,0:00:01.00,0:00:03.00,Default,{\\i1}Hello{\\i0}\n'
              'Comment: 0,0:00:00.00,0:00:01.00,Default,Not translated\n')

    def test_ass_parse_keeps_meta_and_only_dialogue(self):
        meta, events_format, cues = subtitle.parse_ass(self.SAMPLE)
        self.assertEqual(len(subtitle.translatable(cues)), 1)
        self.assertEqual(len(cues), 2)  # Dialogue + Comment
        self.assertIn('[Script Info]', '\n'.join(meta))
        self.assertIn('[V4+ Styles]', '\n'.join(meta))
        self.assertEqual(events_format[:4], ['Layer', 'Start', 'End', 'Style'])
        self.assertEqual(cues[0].prefix, ['0', '0:00:01.00', '0:00:03.00', 'Default'])
        self.assertFalse(cues[1].translatable)

    def test_ass_render_round_trip(self):
        meta, events_format, cues = subtitle.parse_ass(self.SAMPLE)
        rendered = subtitle.render_ass(meta, events_format, cues)
        self.assertIn('Comment:', rendered)
        meta2, fmt2, cues2 = subtitle.parse_ass(rendered)
        self.assertEqual(len(subtitle.translatable(cues2)), 1)
        self.assertEqual(cues2[0].lines, cues[0].lines)

    def test_ass_override_tag_change_is_detected(self):
        meta, events_format, cues = subtitle.parse_ass(self.SAMPLE)
        broken = [subtitle.Cue(['Hello'])]
        with self.assertRaises(ValueError):
            subtitle.validate_structure(cues, broken)


class FontFallbackTests(unittest.TestCase):
    """Türkçe karakter desteklemeyen kaynak fontlar çıktıda Calibri olur."""

    ASS = ('[Script Info]\nTitle: Test\n\n[V4+ Styles]\n'
           'Format: Name, Fontname, Fontsize\n'
           'Style: Default,Gandhi Sans,72\n'
           'Style: Signs,Arial,80\n\n'
           '[Events]\nFormat: Layer, Start, End, Style, Text\n'
           'Dialogue: 0,0:00:01.00,0:00:02.00,Default,{\\fnBolton}Hello\n')

    def test_ass_font_families_reads_styles_and_inline_tags(self):
        families = subtitle.ass_font_families(self.ASS)
        self.assertEqual(families, {'Gandhi Sans', 'Arial', 'Bolton'})

    def test_apply_ass_font_fallback_rewrites_style_and_tag(self):
        text, changed = subtitle.apply_ass_font_fallback(
            self.ASS, {'Gandhi Sans': 'Calibri', 'Bolton': 'Calibri'})
        self.assertEqual(changed, 2)
        self.assertIn('Style: Default,Calibri,72', text)
        self.assertIn('Style: Signs,Arial,80', text)
        self.assertIn('{\\fnCalibri}Hello', text)

    def test_apply_ass_font_fallback_is_noop_without_replacements(self):
        text, changed = subtitle.apply_ass_font_fallback(self.ASS, {})
        self.assertEqual(changed, 0)
        self.assertEqual(text, self.ASS)

    def test_turkish_replacements_uses_capability(self):
        with mock.patch.object(fonts, 'supports_turkish',
                               side_effect=lambda name: name != 'Gandhi Sans'):
            replacements = fonts.turkish_replacements(['Gandhi Sans', 'Arial', 'Calibri'])
        self.assertEqual(replacements, {'Gandhi Sans': fonts.FALLBACK_FONT})

    def test_render_output_replaces_unsupported_ass_font(self):
        kind, payload = subtitle.parse_by_extension(self.ASS, '.ass')
        cues = subtitle.cues_of(kind, payload)
        messages = []
        with mock.patch.object(fonts, 'supports_turkish',
                               side_effect=lambda name: name != 'Gandhi Sans'):
            text, replacements = app_core.render_output(
                kind, payload, cues, log=messages.append)
        self.assertEqual(replacements, {'Gandhi Sans': fonts.FALLBACK_FONT})
        self.assertIn('Style: Default,Calibri,72', text)
        self.assertTrue(any('Calibri' in message for message in messages))

    def test_render_output_keeps_supported_ass_font(self):
        kind, payload = subtitle.parse_by_extension(self.ASS, '.ass')
        cues = subtitle.cues_of(kind, payload)
        with mock.patch.object(fonts, 'supports_turkish', return_value=True):
            text, replacements = app_core.render_output(kind, payload, cues)
        self.assertEqual(replacements, {})
        self.assertIn('Style: Default,Gandhi Sans,72', text)

    def test_render_output_ignores_srt(self):
        kind, payload = subtitle.parse_by_extension(
            '1\n00:00:01,000 --> 00:00:02,000\nHello.\n', '.srt')
        with mock.patch.object(fonts, 'supports_turkish', return_value=False):
            text, replacements = app_core.render_output(kind, payload, payload)
        self.assertEqual(replacements, {})
        self.assertEqual(text, '1\n00:00:01,000 --> 00:00:02,000\nHello.\n')


class EngineTests(unittest.TestCase):
    """TranslationEngine: ID/TEXT kontrollu ceviri, glossary zorunlulugu, checkpoint."""

    class FakeClient:
        def __init__(self, responses):
            self.responses = list(responses)
            self.calls = []

        def generate(self, system, user):
            self.calls.append((system, user))
            if not self.responses:
                raise AssertionError('Beklenmeyen ek model istegi.')
            return self.responses.pop(0)

    def setUp(self):
        self.config = dict(app_core.DEFAULT_CONFIG, batch_cues=40)

    def _engine(self):
        return TranslationEngine(lambda: dict(self.config), log=lambda _message: None)

    def _run(self, responses, cues, **kwargs):
        fake = self.FakeClient(responses)
        with mock.patch.object(app_core, 'Client', return_value=fake):
            result = self._engine().translate(cues, **kwargs)
        return result, fake

    def test_translate_reflows_merged_multiline_cue(self):
        # Model cok satirli cue'yu tek satira indirse bile cikti kaynak satir
        # sayisini korur ve yapisal dogrulama gecer (F11 kok neden).
        cues = subtitle.parse_srt('1\n00:00:01,000 --> 00:00:02,000\n'
                                  'Hello there.\nSecond line.\n')
        response = 'ID: 1\nTEXT: Merhaba, orada. Ikinci satir.'
        result, _fake = self._run([response], cues)
        self.assertEqual(result[0].lines, ['Merhaba, orada.', 'Ikinci satir.'])
        self.assertEqual(result[0].start, '00:00:01,000')

    def test_translate_srt_keeps_timestamps(self):
        cues = subtitle.parse_srt('1\n00:00:01,000 --> 00:00:03,000\nHello.\n\n'
                                  '2\n00:00:04,000 --> 00:00:06,000\nBye.\n')
        response = 'ID: 1\nTEXT: Merhaba.\n\nID: 2\nTEXT: Hosca kal.'
        result, _fake = self._run([response], cues)
        self.assertEqual([cue.text for cue in result], ['Merhaba.', 'Hosca kal.'])
        self.assertEqual(result[0].start, '00:00:01,000')
        self.assertEqual(subtitle.render_srt(result).splitlines()[1], '00:00:01,000 --> 00:00:03,000')

    def test_translate_sends_ids_and_glossary(self):
        cues = subtitle.parse_srt('1\n00:00:01,000 --> 00:00:02,000\nAsh is here.\n')
        response = 'ID: 1\nTEXT: Kul burada.'
        _result, fake = self._run([response], cues,
                                  glossary=[{'source': 'Ash', 'target': 'Kul'}])
        self.assertIn('MANDATORY USER GLOSSARY', fake.calls[0][1])
        self.assertIn('ID: 1', fake.calls[0][1])
        self.assertIn('TEXT: Ash is here.', fake.calls[0][1])

    def test_glossary_fix_is_requested_once(self):
        cues = subtitle.parse_srt('1\n00:00:01,000 --> 00:00:02,000\nAsh is here.\n')
        first = 'ID: 1\nTEXT: Dumanlar burada.'
        fixed = 'ID: 1\nTEXT: Kul burada.'
        result, fake = self._run([first, fixed], cues,
                                 glossary=[{'source': 'Ash', 'target': 'Kul'}])
        self.assertEqual(result[0].text, 'Kul burada.')
        self.assertEqual(len(fake.calls), 2)

    def test_glossary_still_missing_raises_when_strict(self):
        # Kati sozluk acikken eksik terim kalici hatadir.
        self.config['glossary_strict'] = True
        cues = subtitle.parse_srt('1\n00:00:01,000 --> 00:00:02,000\nAsh is here.\n')
        bad = 'ID: 1\nTEXT: Dumanlar burada.'
        with mock.patch.object(app_core, 'Client', return_value=self.FakeClient([bad, bad])):
            with self.assertRaises(ValueError):
                self._engine().translate(cues, glossary=[{'source': 'Ash', 'target': 'Kul'}])

    def test_glossary_missing_continues_when_not_strict(self):
        # Kati sozluk kapaliyken (varsayilan) eksik terim UYARI loglanir,
        # ceviri devam eder ve sonuc uretilir.
        logs = []
        cues = subtitle.parse_srt('1\n00:00:01,000 --> 00:00:02,000\nAsh is here.\n')
        bad = 'ID: 1\nTEXT: Dumanlar burada.'
        engine = TranslationEngine(lambda: dict(self.config), log=logs.append)
        with mock.patch.object(app_core, 'Client', return_value=self.FakeClient([bad, bad])):
            result = engine.translate(cues, glossary=[{'source': 'Ash', 'target': 'Kul'}])
        self.assertEqual(result[0].text, 'Dumanlar burada.')
        self.assertTrue(any('katı sözlük kapalı' in line for line in logs))

    def test_checkpoint_skips_completed_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder) / 'x.state.json'
            self.config['batch_cues'] = 1
            cues = subtitle.parse_srt('1\n00:00:01,000 --> 00:00:02,000\nHello.\n\n'
                                      '2\n00:00:03,000 --> 00:00:04,000\nBye.\n')
            responses = ['ID: 1\nTEXT: Merhaba.', 'ID: 1\nTEXT: Hosca kal.']
            first, fake = self._run(responses, cues, checkpoint=checkpoint)
            self.assertEqual(len(fake.calls), 2)
            self.assertTrue(checkpoint.exists())
            second, fake2 = self._run([], cues, checkpoint=checkpoint)
            self.assertEqual(len(fake2.calls), 0)
            self.assertEqual([cue.text for cue in second], ['Merhaba.', 'Hosca kal.'])

    def test_checkpoint_signature_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder) / 'x.state.json'
            checkpoint.write_text(json.dumps({'signature': 'baska', 'translations': {}}),
                                  encoding='utf-8')
            cues = subtitle.parse_srt('1\n00:00:01,000 --> 00:00:02,000\nHello.\n')
            with mock.patch.object(app_core, 'Client', return_value=self.FakeClient([])):
                with self.assertRaises(ValueError):
                    self._engine().translate(cues, checkpoint=checkpoint)

    def test_pause_controller_checkpoint_blocks_until_resume(self):
        controller = PauseController()
        controller.request_pause()
        self.assertTrue(controller.pause_requested)
        controller.resume()
        controller.checkpoint()  # bloklamadan doner
        controller.request_close()
        with self.assertRaises(app_core.GracefulStop):
            controller.checkpoint()

    def test_clean_response_rejects_markers_and_code(self):
        with self.assertRaises(ValueError):
            clean_response('')
        with self.assertRaises(ValueError):
            clean_response('```json\n{}\n```')
        with self.assertRaises(ValueError):
            clean_response('\n<tool_call>')
        self.assertEqual(clean_response('  Merhaba.  '), 'Merhaba.')

    def test_glossary_missing_checks_source_occurrence(self):
        glossary = [{'source': 'Ash', 'target': 'Kul'}, {'source': 'Wight', 'target': 'Olu'}]
        # 'Wight' kaynakta hic gecmiyor -> denetlenmez.
        self.assertEqual(glossary_missing('Ash burada.', 'Dumanlar burada.', glossary),
                         [{'source': 'Ash', 'target': 'Kul'}])
        # Kaynaginda gecen ve karsiligi (cekimli de olsa) bulunan terim eksik sayilmaz.
        self.assertEqual(glossary_missing('Ash burada.', 'Kul burada.', glossary), [])

    def test_empty_response_retries_then_raises(self):
        # auto_retry_count=2 -> toplam 3 deneme; ucuncude hata dogrudan yukselir.
        self.config['auto_retry_count'] = 2
        cues = subtitle.parse_srt('1\n00:00:01,000 --> 00:00:02,000\nHello.\n')
        fake = self.FakeClient(['', '', ''])
        with mock.patch.object(app_core, 'Client', return_value=fake):
            with self.assertRaises(ValueError):
                self._engine().translate(cues)
        self.assertEqual(len(fake.calls), 3)

    def test_client_reports_empty_content_with_finish_reason(self):
        client = app_core.Client(dict(app_core.DEFAULT_CONFIG), log=lambda _m: None)
        client.request = lambda route, payload=None: {
            'choices': [{'message': {'content': '', 'reasoning_content': 'xxxx'},
                         'finish_reason': 'length'}]}
        with self.assertRaises(ValueError) as context:
            client.generate('sys', 'user')
        message = str(context.exception)
        self.assertIn('finish_reason=length', message)
        self.assertIn('düşünce_uzunluğu=4', message)

    def test_client_returns_content_when_present(self):
        client = app_core.Client(dict(app_core.DEFAULT_CONFIG), log=lambda _m: None)
        client.request = lambda route, payload=None: {
            'choices': [{'message': {'content': 'Merhaba.'}, 'finish_reason': 'stop'}]}
        self.assertEqual(client.generate('sys', 'user'), 'Merhaba.')

    def test_disable_thinking_adds_chat_template_kwargs(self):
        cfg = dict(app_core.DEFAULT_CONFIG, disable_thinking=True)
        client = app_core.Client(cfg, log=lambda _m: None)
        captured = {}

        def fake_request(route, payload=None):
            captured['payload'] = payload
            return {'choices': [{'message': {'content': 'x'}, 'finish_reason': 'stop'}]}

        client.request = fake_request
        client.generate('sys', 'user')
        self.assertEqual(captured['payload'].get('chat_template_kwargs'), {'enable_thinking': False})

    def test_thinking_disabled_by_default(self):
        client = app_core.Client(dict(app_core.DEFAULT_CONFIG), log=lambda _m: None)
        captured = {}

        def fake_request(route, payload=None):
            captured['payload'] = payload
            return {'choices': [{'message': {'content': 'x'}, 'finish_reason': 'stop'}]}

        client.request = fake_request
        client.generate('sys', 'user')
        self.assertNotIn('chat_template_kwargs', captured['payload'])


class SubtitleFormatTests(unittest.TestCase):
    """parse_by_extension / render_by_kind: uzantiya gore parse + ayni formatta yaz."""

    SRT = '1\n00:00:01,000 --> 00:00:02,000\nHello.\n'
    VTT = 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello.\n'
    ASS = ('[Script Info]\nTitle: T\n\n[Events]\n'
           'Format: Layer, Start, End, Style, Text\n'
           'Dialogue: 0,0:00:01.00,0:00:02.00,Default,Hello\n')

    def test_parse_and_render_srt(self):
        kind, payload = subtitle.parse_by_extension(self.SRT, '.srt')
        self.assertEqual(kind, 'srt')
        self.assertEqual(subtitle.cues_of(kind, payload)[0].text, 'Hello.')
        self.assertEqual(subtitle.render_by_kind(kind, payload, payload).splitlines()[0], '1')

    def test_parse_and_render_vtt(self):
        kind, payload = subtitle.parse_by_extension(self.VTT, 'vtt')
        self.assertEqual(kind, 'vtt')
        self.assertTrue(subtitle.render_by_kind(kind, payload, payload).startswith('WEBVTT'))

    def test_parse_and_render_ass_keeps_meta(self):
        kind, payload = subtitle.parse_by_extension(self.ASS, '.ass')
        self.assertEqual(kind, 'ass')
        rendered = subtitle.render_by_kind(kind, payload, subtitle.cues_of(kind, payload))
        self.assertIn('[Script Info]', rendered)
        self.assertIn('Dialogue: 0,0:00:01.00,0:00:02.00,Default,Hello', rendered)

    def test_unknown_extension_raises(self):
        with self.assertRaises(ValueError):
            subtitle.parse_by_extension('x', '.sub')


class MediaProbeTests(unittest.TestCase):
    PROBE = json.dumps({'streams': [
        {'index': 2, 'codec_type': 'subtitle', 'codec_name': 'subrip',
         'tags': {'language': 'eng', 'title': 'English'}},
        {'index': 3, 'codec_type': 'subtitle', 'codec_name': 'ass',
         'tags': {'language': 'tur', 'title': 'Turkish'}},
        {'index': 4, 'codec_type': 'subtitle', 'codec_name': 'hdmv_pgs_subtitle',
         'tags': {'language': 'eng', 'title': 'English PGS'}},
        {'index': 0, 'codec_type': 'video', 'codec_name': 'h264'},
    ]})

    def _video(self, folder):
        video = Path(folder) / 'Movie.mkv'
        video.write_text('x', encoding='utf-8')
        return video

    def test_subtitle_streams_parses_probe_output(self):
        with tempfile.TemporaryDirectory() as folder:
            video = self._video(folder)
            result = mock.Mock(returncode=0, stdout=self.PROBE, stderr='')
            with mock.patch.object(media, 'ffprobe_path', return_value='ffprobe'), \
                 mock.patch.object(media, '_run', return_value=result):
                streams = media.subtitle_streams(video)
        self.assertEqual([item['index'] for item in streams], [2, 3, 4])
        self.assertTrue(streams[0]['supported'])
        self.assertEqual(streams[0]['extension'], 'srt')
        self.assertTrue(streams[1]['supported'])
        self.assertEqual(streams[1]['extension'], 'ass')
        self.assertFalse(streams[2]['supported'])
        self.assertTrue(streams[2]['image'])

    def test_subtitle_streams_reports_probe_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            video = self._video(folder)
            result = mock.Mock(returncode=1, stdout='', stderr='bad file')
            with mock.patch.object(media, 'ffprobe_path', return_value='ffprobe'), \
                 mock.patch.object(media, '_run', return_value=result):
                with self.assertRaises(RuntimeError):
                    media.subtitle_streams(video)

    def test_extract_subtitle_uses_global_index_and_copies(self):
        with tempfile.TemporaryDirectory() as folder:
            video = self._video(folder)
            output = Path(folder) / 'Movie_TR.srt'

            def fake_run(command):
                Path(command[-1]).write_text('subtitle', encoding='utf-8')
                return mock.Mock(returncode=0, stderr='')

            with mock.patch.object(media, 'ffmpeg_path', return_value='ffmpeg'), \
                 mock.patch.object(media, '_run', side_effect=fake_run) as run:
                media.extract_subtitle(video, 2, output, codec='subrip')
            command = run.call_args[0][0]
            self.assertEqual(command[command.index('-map') + 1], '0:2')
            self.assertIn('copy', command)
            self.assertTrue(output.exists())

    def test_extract_subtitle_converts_mov_text(self):
        with tempfile.TemporaryDirectory() as folder:
            video = self._video(folder)
            output = Path(folder) / 'Movie_TR.srt'

            def fake_run(command):
                Path(command[-1]).write_text('subtitle', encoding='utf-8')
                return mock.Mock(returncode=0, stderr='')

            with mock.patch.object(media, 'ffmpeg_path', return_value='ffmpeg'), \
                 mock.patch.object(media, '_run', side_effect=fake_run) as run:
                media.extract_subtitle(video, 3, output, codec='mov_text')
            command = run.call_args[0][0]
            self.assertIn('srt', command)

    def test_extract_subtitle_rejects_image_codec(self):
        with tempfile.TemporaryDirectory() as folder:
            video = self._video(folder)
            output = Path(folder) / 'Movie_TR.srt'
            with self.assertRaises(ValueError):
                media.extract_subtitle(video, 4, output, codec='hdmv_pgs_subtitle')


class MediaPathTests(unittest.TestCase):
    def test_unique_output_path_adds_counter(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'Movie.mkv'
            video.write_text('x', encoding='utf-8')
            first = media.unique_output_path(video, 'srt')
            self.assertEqual(first.name, 'Movie_TR.srt')
            first.write_text('y', encoding='utf-8')
            second = media.unique_output_path(video, 'srt')
            self.assertEqual(second.name, 'Movie_TR (2).srt')

    def test_unique_output_path_keeps_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'Movie.mkv'
            video.write_text('x', encoding='utf-8')
            self.assertEqual(media.unique_output_path(video, 'ass').name, 'Movie_TR.ass')

    def test_unique_source_path_adds_counter(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'Movie.mkv'
            video.write_text('x', encoding='utf-8')
            first = media.unique_source_path(video, 'ass')
            self.assertEqual(first.name, 'Movie.ass')
            first.write_text('y', encoding='utf-8')
            self.assertEqual(media.unique_source_path(video, 'ass').name, 'Movie (2).ass')

    def test_find_videos_filters_by_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'a.mkv').write_text('x', encoding='utf-8')
            (Path(folder) / 'b.txt').write_text('x', encoding='utf-8')
            (Path(folder) / 'c.mp4').write_text('x', encoding='utf-8')
            names = [item.name for item in media.find_videos(folder)]
            self.assertEqual(names, ['a.mkv', 'c.mp4'])


if __name__ == '__main__':
    unittest.main()
