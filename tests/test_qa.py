"""Videoya Soru Sor cekirdek testleri (unittest). PySide6 ve LM Studio gerektirmez.

Calistirma:
    py -3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_core
import media
import qa
import subtitle

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def synthetic_segments(minutes=20, step=5.0):
    segments = []
    for index in range(int(minutes * 60 / step)):
        start = index * step
        segments.append({'start': start, 'end': start + step - 0.5,
                         'text': f'Line {index} talks about topic {index // 48} in detail.'})
    return segments


class FakeClient:
    """Sirali yanitlar dondurur; gelen mesajlari kaydeder."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, cfg, log=print):
        return self

    def chat(self, messages, temperature=None, max_tokens=None):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def config(**overrides):
    return lambda: dict(app_core.DEFAULT_CONFIG, **overrides)


OVERVIEW = json.dumps({'summary': 'Video yeni sürümün performansını inceliyor.',
                       'topics': ['Performans', 'Ayarlar'],
                       'questions': ['En iyi ayarlar neler?', 'Hangi GPU yeterli?']})


class TimeTests(unittest.TestCase):
    def test_parse_time_accepts_subtitle_and_citation_formats(self):
        self.assertAlmostEqual(qa.parse_time('00:01:02,345'), 62.345)
        self.assertAlmostEqual(qa.parse_time('0:01:02.34'), 62.34)
        self.assertAlmostEqual(qa.parse_time('01:02.345'), 62.345)
        self.assertEqual(qa.parse_time('12:34'), 754.0)
        self.assertEqual(qa.parse_time('1:02:03'), 3723.0)
        with self.assertRaises(ValueError):
            qa.parse_time('abc')

    def test_format_time_style(self):
        self.assertEqual(qa.format_time(3), '0:03')
        self.assertEqual(qa.format_time(754.9), '12:34')
        self.assertEqual(qa.format_time(3723), '1:02:03')
        self.assertEqual(qa.format_range(190, 465), '3:10-7:45')
        self.assertEqual(qa.format_range(190, 190.4), '3:10')


class TranscriptTests(unittest.TestCase):
    def test_srt_fixture_becomes_sorted_plain_segments(self):
        cues = subtitle.parse_srt(app_core.read(FIXTURES / 'sakamoto-12.srt'))
        segments = qa.transcript_from_cues(cues)
        self.assertTrue(segments)
        starts = [item['start'] for item in segments]
        self.assertEqual(starts, sorted(starts))
        for item in segments:
            self.assertLessEqual(item['start'], item['end'])
            self.assertNotIn('\n', item['text'])

    def test_ass_fixture_drops_tags_and_merges_animation_repeats(self):
        meta, fmt, cues = subtitle.parse_ass(app_core.read(FIXTURES / 'turning-point-3.ass'))
        segments = qa.transcript_from_cues(cues)
        self.assertTrue(segments)
        self.assertFalse(any('{' in item['text'] or '\\N' in item['text'] for item in segments))
        for previous, current in zip(segments, segments[1:]):
            self.assertFalse(previous['text'] == current['text']
                             and current['start'] <= previous['end'] + 1.0)

    def test_empty_subtitle_raises_meaningful_error(self):
        cue = subtitle.Cue([''], start='00:00:01,000', end='00:00:02,000')
        with self.assertRaises(ValueError):
            qa.transcript_from_cues([cue])

    def test_compact_lines_merges_short_neighbours_only(self):
        segments = [{'start': 0, 'end': 2, 'text': 'a'}, {'start': 3, 'end': 5, 'text': 'b'},
                    {'start': 30, 'end': 32, 'text': 'c'}]
        lines = qa.compact_lines(segments)
        self.assertEqual([line['text'] for line in lines], ['a b', 'c'])
        self.assertEqual(lines[0]['end'], 5)
        self.assertEqual(qa.format_lines(lines), '[0:00] a b\n[0:30] c')


class DisplaySubtitleTests(unittest.TestCase):
    """F47: oynaticida altyazi gosterimi (satir yapisi korunur, cakisanlar birlikte)."""

    def test_keep_lines_preserves_cue_line_breaks(self):
        cue = subtitle.Cue(['{\\an8}Birinci  satır\\Nikinci satır'],
                           ass_fields={'start': '0:00:01.00', 'end': '0:00:03.00'})
        self.assertEqual(qa.transcript_from_cues([cue], keep_lines=True)[0]['text'],
                         'Birinci satır\nikinci satır')
        self.assertEqual(qa.transcript_from_cues([cue])[0]['text'], 'Birinci satır ikinci satır')

    def test_timeline_returns_active_and_overlapping_text(self):
        timeline = qa.SubtitleTimeline([
            {'start': 10.0, 'end': 14.0, 'text': 'b'},
            {'start': 1.0, 'end': 4.0, 'text': 'a'},
            {'start': 12.0, 'end': 13.0, 'text': 'üst yazı'},
            {'start': 12.5, 'end': 13.0, 'text': 'b'},
        ])
        self.assertEqual(timeline.text_at(0.5), '')
        self.assertEqual(timeline.text_at(2.0), 'a')
        self.assertEqual(timeline.text_at(4.0), '')
        self.assertEqual(timeline.text_at(12.7), 'b\nüst yazı')
        self.assertEqual(timeline.text_at(100.0), '')

    def test_file_segments_reads_fixture_with_lines(self):
        segments = qa.file_segments(FIXTURES / 'turning-point-3.ass')
        self.assertTrue(segments)
        self.assertFalse(any('{' in item['text'] for item in segments))

    def test_sidecar_subtitles_match_video_name(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            video = folder / 'Film.mkv'
            for name in ('Film.mkv', 'Film_TR.srt', 'film.en.ASS', 'Film.txt',
                         'Başka.srt', 'Film.vtt'):
                (folder / name).write_text('x', encoding='utf-8')
            names = [item.name for item in media.sidecar_subtitles(video)]
        self.assertEqual(names, ['film.en.ASS', 'Film.vtt', 'Film_TR.srt'])

    def test_display_extraction_uses_separate_file(self):
        with tempfile.TemporaryDirectory() as folder:
            outputs = []

            def extract(_video, _index, output, codec=''):
                outputs.append(Path(output).name)
                Path(output).parent.mkdir(parents=True, exist_ok=True)
                Path(output).write_text(app_core.read(FIXTURES / 'sakamoto-12.srt'), encoding='utf-8')

            stream = {'index': 3, 'extension': 'srt', 'codec': 'subrip'}
            with mock.patch.object(media, 'extract_subtitle', side_effect=extract):
                qa.subtitle_segments('Ep.mkv', stream, folder)
                shown = qa.subtitle_segments('Ep.mkv', stream, folder, keep_lines=True)
        self.assertEqual(outputs, ['Ep.s3.srt', 'Ep.s3.view.srt'])
        self.assertTrue(any('\n' in item['text'] for item in shown))


class SectionTests(unittest.TestCase):
    def test_time_based_sections_cover_every_line_once(self):
        lines = qa.compact_lines(synthetic_segments(20))
        sections = qa.build_sections(lines)
        self.assertGreaterEqual(len(sections), 5)
        covered = [index for item in sections for index in range(item['first'], item['last'] + 1)]
        self.assertEqual(covered, list(range(len(lines))))
        for item in sections:
            self.assertLessEqual(item['end'] - item['start'], qa.SECTION_SECONDS + qa.LINE_SECONDS + 5)

    def test_embedded_chapters_define_sections_and_titles(self):
        lines = qa.compact_lines(synthetic_segments(10))
        chapters = [{'start': 0.0, 'end': 60.0, 'title': 'Introduction'},
                    {'start': 60.0, 'end': 400.0, 'title': 'Benchmarks'},
                    {'start': 400.0, 'end': 600.0, 'title': 'Settings'}]
        sections = qa.build_sections(lines, chapters, max_chars=100000)
        self.assertEqual([item['title'] for item in sections],
                         ['Introduction', 'Benchmarks', 'Settings'])
        self.assertLess(sections[1]['start'], 61)

    def test_long_chapter_is_split_by_size_keeping_title(self):
        lines = qa.compact_lines(synthetic_segments(10))
        chapters = [{'start': 0.0, 'end': 10.0, 'title': 'Intro'},
                    {'start': 10.0, 'end': 600.0, 'title': 'Main'}]
        sections = qa.build_sections(lines, chapters, max_chars=1500)
        self.assertGreater(len(sections), 2)
        self.assertTrue(all(item['title'] in ('Intro', 'Main') for item in sections))


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.lines = [{'start': 10.0, 'end': 20.0, 'text': 'a'},
                      {'start': 190.0, 'end': 200.0, 'text': 'b'},
                      {'start': 754.0, 'end': 760.0, 'text': 'c'}]

    def cites(self, text):
        return [part[1] for part in qa.split_citations(text, self.lines, 900) if part[0] == 'cite']

    def test_bracket_single_range_and_multiple(self):
        parts = qa.split_citations('Sonuç iyi [12:34]. Ayrıca [3:10-7:45] ve [0:10, 3:10].',
                                   self.lines, 900)
        cites = [part[1] for part in parts if part[0] == 'cite']
        self.assertEqual(cites[0][0]['start'], 754.0)
        self.assertEqual((cites[1][0]['start'], cites[1][0]['end']), (190.0, 465.0))
        self.assertEqual([item['start'] for item in cites[2]], [10.0, 190.0])
        text = ''.join(part[1] for part in parts if part[0] == 'text')
        self.assertEqual(text, 'Sonuç iyi . Ayrıca  ve .')

    def test_invented_citation_is_removed(self):
        parts = qa.split_citations('Uydurma bilgi [45:00].', self.lines, 900)
        self.assertEqual(parts, [('text', 'Uydurma bilgi.')])

    def test_near_citation_snaps_to_line_start(self):
        self.assertEqual(self.cites('Yakın [3:05].')[0][0]['start'], 190.0)
        self.assertEqual(self.cites('İçinde [0:15].')[0][0]['start'], 15.0)

    def test_bare_timestamp_is_linked_only_when_valid(self):
        parts = qa.split_citations("12:34'te şöyle deniyor; saat 21:00 değil, oran 16:9.",
                                   self.lines, 900)
        self.assertEqual(parts[0][0], 'cite')
        self.assertEqual(parts[0][1][0]['label'], '12:34')
        rest = ''.join(part[1] for part in parts[1:] if part[0] == 'text')
        self.assertIn('21:00', rest)
        self.assertIn('16:9', rest)

    def test_non_timestamp_brackets_stay_text(self):
        parts = qa.split_citations('Bkz. [kaynak] ve [not 3].', self.lines, 900)
        self.assertEqual(parts, [('text', 'Bkz. [kaynak] ve [not 3].')])


class ParseTests(unittest.TestCase):
    def test_json_object_tolerates_fences_and_thinking(self):
        text = '<think>hmm</think>```json\n{"summary": "x"}\n```'
        self.assertEqual(qa.parse_json_object(text), {'summary': 'x'})

    def test_invalid_json_is_retryable(self):
        with self.assertRaises(ValueError) as context:
            qa.parse_json_object('özet yok')
        self.assertTrue(app_core.retryable_translation_error(context.exception))

    def test_overview_normalization(self):
        value = qa.normalize_overview({'summary': ' a  b ', 'topics': ['x', 'x', ''],
                                       'questions': ['1', '2', '3', '4', '5']})
        self.assertEqual(value, {'summary': 'a b', 'topics': ['x'], 'questions': ['1', '2', '3', '4']})
        with self.assertRaises(ValueError):
            qa.normalize_overview({'summary': ''})


class SessionTests(unittest.TestCase):
    def short_data(self):
        segments = [{'start': 3.0, 'end': 8.0, 'text': 'Welcome to the review.'},
                    {'start': 754.0, 'end': 760.0, 'text': 'Use high textures on 8GB cards.'}]
        return qa.build_data('Witcher.mkv', segments, {'kind': 'subtitle'},
                             {'duration': 1229.0, 'chapters': []})

    def test_full_mode_prepares_overview_and_answers_with_history(self):
        fake = FakeClient([OVERVIEW, 'Yüksek doku öneriliyor [12:34].', 'Evet [0:03].'])
        saved = []
        session = qa.VideoQA(self.short_data(), config_provider=config(), log=lambda _m: None,
                             save=saved.append)
        with mock.patch.object(qa, 'Client', fake):
            overview = session.prepare()
            self.assertEqual(session.data['mode'], 'full')
            self.assertEqual(overview['summary'], 'Video yeni sürümün performansını inceliyor.')
            self.assertEqual(session.questions()[0], 'Videoyu özetle')
            self.assertIn('En iyi ayarlar neler?', session.questions())
            turn = session.ask('Hangi doku ayarı?')
            session.ask('Emin misin?')
        self.assertTrue(saved)
        self.assertEqual([part[0] for part in turn['parts']], ['text', 'cite', 'text'])
        system = fake.calls[1][0]['content']
        self.assertIn('[12:34] Use high textures on 8GB cards.', system)
        self.assertIn('Answer in Turkish', system)
        last = fake.calls[2]
        self.assertEqual([item['role'] for item in last], ['system', 'user', 'assistant', 'user'])
        self.assertEqual(last[2]['content'], 'Yüksek doku öneriliyor [12:34].')

    def test_map_mode_summarizes_sections_resumes_and_routes(self):
        data = qa.build_data('Long.mkv', synthetic_segments(20), {'kind': 'subtitle'},
                             {'duration': 1200.0, 'chapters': []})
        count = len(data['sections'])
        replies = [json.dumps({'heading': f'Bölüm {n}', 'summary': f'Konu {n} anlatılıyor.'})
                   for n in range(count)]
        fake = FakeClient(replies[:2] + [RuntimeError('LM Studio istegi reddedildi.')])
        session = qa.VideoQA(data, config_provider=config(qa_context_chars=3000),
                             log=lambda _m: None)
        with mock.patch.object(qa, 'Client', fake):
            with self.assertRaises(RuntimeError):
                session.prepare()
        self.assertEqual(sum(1 for item in data['sections'] if item.get('summary')), 2)
        # Kaldigi yerden devam: yalnizca eksik bolumler + genel ozet istenir.
        fake = FakeClient(replies[2:] + [OVERVIEW, json.dumps({'sections': [2]}),
                                         'İkinci bölümde anlatılıyor [4:00].'])
        progress = []
        with mock.patch.object(qa, 'Client', fake):
            session.prepare(progress=lambda done, total: progress.append((done, total)))
            self.assertEqual(data['mode'], 'map')
            self.assertEqual(len(fake.calls), count - 2 + 1)
            self.assertEqual(progress[-1], (count - 1, count - 1))
            turn = session.ask('İkinci konu ne?')
        self.assertEqual(turn['sections'], [1])
        system = fake.calls[-1][0]['content']
        self.assertIn('OVERVIEW:', system)
        self.assertIn('2. [4:00-', system)
        self.assertIn('Line 48 talks', system)
        self.assertNotIn('Line 0 talks', system)
        self.assertLessEqual(len(system), 3000 + len(qa.ANSWER_PROMPT) + 400)
        self.assertEqual(turn['parts'][1][1][0]['start'], 240.0)

    def test_broad_question_fills_remaining_budget_with_spread_sections(self):
        data = qa.build_data('Long.mkv', synthetic_segments(20), {'kind': 'subtitle'},
                             {'duration': 1200.0, 'chapters': []})
        for index, item in enumerate(data['sections']):
            item['summary'] = f'Summary {index}'
        data['mode'] = 'map'
        session = qa.VideoQA(data, config_provider=config(qa_context_chars=9000),
                             log=lambda _m: None)
        context, used = session.build_context(session.config_provider(), ranked=[3])
        self.assertIn(3, used)
        self.assertIn(0, used)
        self.assertLessEqual(len(context), 9000)

    def test_route_failure_falls_back_to_word_overlap(self):
        data = qa.build_data('Long.mkv', synthetic_segments(20), {'kind': 'subtitle'},
                             {'duration': 1200.0, 'chapters': []})
        for index, item in enumerate(data['sections']):
            item['summary'] = f'Summary {index}'
        data['mode'], data['overview'] = 'map', {'summary': 'x', 'topics': [], 'questions': []}
        fake = FakeClient(['bozuk', 'bozuk', 'bozuk', 'Cevap.'])
        session = qa.VideoQA(data, config_provider=config(qa_context_chars=3000),
                             log=lambda _m: None)
        with mock.patch.object(qa, 'Client', fake):
            turn = session.ask('Line 100 ne diyor?')
        self.assertIn(2, turn['sections'])

    def test_cancel_raises_graceful_stop(self):
        data = qa.build_data('Long.mkv', synthetic_segments(20), {'kind': 'subtitle'},
                             {'duration': 1200.0, 'chapters': []})
        session = qa.VideoQA(data, config_provider=config(qa_context_chars=3000),
                             log=lambda _m: None)
        with mock.patch.object(qa, 'Client', FakeClient([])):
            with self.assertRaises(app_core.GracefulStop):
                session.prepare(cancelled=lambda: True)

    def test_empty_question_is_rejected(self):
        session = qa.VideoQA(self.short_data(), config_provider=config(), log=lambda _m: None)
        with self.assertRaises(ValueError):
            session.ask('   ')

    def test_spread_and_lexical_rank(self):
        self.assertEqual(qa.spread(3, 6), [0, 1, 2])
        self.assertEqual(qa.spread(11, 6), [0, 2, 4, 6, 8, 10])
        sections = [{'first': 0, 'last': 0, 'title': ''}, {'first': 1, 'last': 1, 'title': ''}]
        lines = [{'start': 0, 'end': 1, 'text': 'graphics settings'},
                 {'start': 2, 'end': 3, 'text': 'raytracing performance'}]
        self.assertEqual(qa.lexical_rank(sections, lines, 'raytracing nasıl?')[0], 1)


class SourceTests(unittest.TestCase):
    def test_pick_subtitle_stream_avoids_signs_tracks(self):
        streams = [{'index': 2, 'supported': False, 'title': ''},
                   {'index': 3, 'supported': True, 'title': 'Signs & Songs'},
                   {'index': 4, 'supported': True, 'title': 'Full Dialogue'}]
        self.assertEqual(qa.pick_subtitle_stream(streams)['index'], 4)
        self.assertEqual(qa.pick_subtitle_stream(streams[:2])['index'], 3)
        self.assertIsNone(qa.pick_subtitle_stream(streams[:1]))

    def test_cache_path_depends_on_source_and_rejects_old_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'My Video.mkv'
            video.write_bytes(b'x')
            first = qa.cache_path(video, 'subtitle:2', folder)
            self.assertNotEqual(first, qa.cache_path(video, 'subtitle:3', folder))
            self.assertEqual(first.parent, Path(folder) / 'qa')
            app_core.save_json(first, {'version': 0})
            self.assertIsNone(qa.load_cache(first))
            app_core.save_json(first, {'version': qa.CACHE_VERSION, 'segments': []})
            self.assertEqual(qa.load_cache(first)['segments'], [])
            self.assertIsNone(qa.load_cache(Path(folder) / 'missing.json'))

    def test_load_subtitle_session_extracts_once_then_uses_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'ep.mkv'
            video.write_bytes(b'x')
            stream = {'index': 2, 'codec': 'subrip', 'extension': 'srt', 'supported': True}
            source = app_core.read(FIXTURES / 'sakamoto-12.srt')

            def extract(_video, _index, output, codec=''):
                Path(output).parent.mkdir(parents=True, exist_ok=True)
                Path(output).write_text(source, encoding='utf-8')
                return output

            info = {'duration': 1400.0, 'chapters': []}
            with mock.patch.object(media, 'extract_subtitle', side_effect=extract) as extractor, \
                    mock.patch.object(media, 'video_info', return_value=info):
                data, path = qa.load_subtitle_session(video, stream, folder, log=lambda _m: None)
                again, _ = qa.load_subtitle_session(video, stream, folder, log=lambda _m: None)
            self.assertEqual(extractor.call_count, 1)
            self.assertTrue(path.exists())
            self.assertEqual(data['duration'], 1400.0)
            self.assertEqual(again['segments'], data['segments'])


class CoreChangeTests(unittest.TestCase):
    def test_qa_context_chars_is_validated(self):
        app_core.validate_config(dict(app_core.DEFAULT_CONFIG))
        with self.assertRaises(ValueError):
            app_core.validate_config(dict(app_core.DEFAULT_CONFIG, qa_context_chars=10))
        legacy = dict(app_core.DEFAULT_CONFIG)
        legacy.pop('qa_context_chars')
        app_core.validate_config(legacy)

    def test_generate_delegates_to_chat_messages(self):
        client = app_core.Client(dict(app_core.DEFAULT_CONFIG), log=lambda _m: None)
        reply = {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}
        with mock.patch.object(client, 'request', return_value=reply) as request:
            self.assertEqual(client.generate('sys', 'usr'), 'ok')
            self.assertEqual(client.chat([{'role': 'user', 'content': 'q'}]), 'ok')
        first = request.call_args_list[0].args[1]['messages']
        self.assertEqual(first, [{'role': 'system', 'content': 'sys'},
                                 {'role': 'user', 'content': 'usr'}])
        self.assertEqual(request.call_args_list[1].args[1]['messages'],
                         [{'role': 'user', 'content': 'q'}])

    def test_video_info_reads_duration_and_chapters(self):
        output = json.dumps({'format': {'duration': '1229.5'}, 'chapters': [
            {'start_time': '60.0', 'end_time': '120.0', 'tags': {'title': 'Benchmarks'}},
            {'start_time': '0.0', 'end_time': '60.0', 'tags': {'title': 'Introduction'}},
            {'start_time': '5', 'end_time': '5'}]})
        result = subprocess.CompletedProcess([], 0, stdout=output, stderr='')
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'v.mkv'
            video.write_bytes(b'x')
            with mock.patch.object(media, '_run', return_value=result), \
                    mock.patch.object(media, 'ffprobe_path', return_value='ffprobe'):
                info = media.video_info(video)
        self.assertEqual(info['duration'], 1229.5)
        self.assertEqual([item['title'] for item in info['chapters']], ['Introduction', 'Benchmarks'])


class StreamClient:
    """chat_stream sahtesi: dusunceyi parca parca bildirir, (metin, finish_reason) dondurur."""

    def __init__(self, *results):
        self.results = list(results)
        self.last_reasoning = ''

    def chat_stream(self, messages, cancelled=None, on_reasoning=None, **_kwargs):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        for piece in ('Düşün', 'Düşün biraz'):
            on_reasoning(piece)
        self.last_reasoning = 'Düşün biraz'
        if cancelled and cancelled():
            return '', 'cancelled'
        return result


class ModelAnswerTests(unittest.TestCase):
    def test_streams_reasoning_and_returns_text(self):
        seen = []
        self.assertEqual(qa.model_answer(StreamClient(('Cevap', 'stop')), [], seen.append), 'Cevap')
        self.assertEqual(seen, ['Düşün', 'Düşün biraz'])

    def test_without_callback_uses_plain_chat(self):
        self.assertEqual(qa.model_answer(FakeClient(['Düz']), []), 'Düz')

    def test_errors_match_plain_chat(self):
        for result, prefix in ((('', 'stop'), 'Boş veya kod bloğu'), (('Yarım', 'length'), 'Yanıt token'),
                               (('x', 'tool_calls'), 'Yanıt tamamlanmadı')):
            with self.assertRaises(ValueError) as caught:
                qa.model_answer(StreamClient(result), [], lambda _text: None)
            self.assertTrue(str(caught.exception).startswith(prefix))
            self.assertTrue(app_core.retryable_translation_error(caught.exception))

    def test_cancel_stops_gracefully(self):
        with self.assertRaises(app_core.GracefulStop):
            qa.model_answer(StreamClient(('x', 'stop')), [], lambda _text: None, cancelled=lambda: True)

    def test_video_ask_streams_and_retries(self):
        # bos yanit gecici hata sayilir: ikinci akisli denemede cevap gelir
        client = StreamClient(('', 'stop'), ('Cevap [0:10].', 'stop'))
        session = qa.VideoQA.__new__(qa.VideoQA)
        session.log = lambda _message: None
        seen = []
        answer = session._call(client, {'auto_retry_count': 1}, [], qa.strip_thinking, seen.append)
        self.assertEqual(answer, 'Cevap [0:10].')
        self.assertEqual(seen.count('Düşün biraz'), 2)


if __name__ == '__main__':
    unittest.main()
