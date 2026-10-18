"""F118: altyazi zamanlamasi, disa aktarma (karaoke), goruntu tabanli altyazi OCR ve klip testleri."""
from __future__ import annotations

import io
import json
import random
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import bridge_subtitles  # noqa: E402
import clip  # noqa: E402
import media  # noqa: E402
import speech  # noqa: E402
import subtitle  # noqa: E402
import subtitle_export  # noqa: E402
import subtitle_ocr  # noqa: E402
import subtitle_sync  # noqa: E402
from subtitle_sync import Timing  # noqa: E402

SRT = """1
00:00:01,000 --> 00:00:03,500
<i>Hello</i> there.

2
00:00:05,000 --> 00:00:08,000
Second line
on two rows.
"""

ASS = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default,Arial,40

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,{\\i1}Hello{\\i0} there.
Comment: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,note
Dialogue: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,Second line\\Non two rows.
"""

WORDS = [(1.0, 1.4, ' Hello'), (1.5, 1.9, ' there,'), (2.0, 2.6, ' my'), (2.7, 3.2, ' dear'),
         (3.3, 3.9, ' friend,'), (4.0, 4.4, ' how'), (4.5, 4.9, ' are'), (5.0, 5.5, ' you'),
         (5.6, 6.0, ' doing'), (6.1, 6.6, ' today?'), (8.0, 8.5, ' Fine.'), (9.0, 9.4, ' Thanks'),
         (9.5, 10.0, ' a'), (10.1, 10.6, ' lot.')]


def ffmpeg_available():
    try:
        media.ffmpeg_path()
        return True
    except RuntimeError:
        return False


def whisper_result():
    return {'segments': speech.regroup_words(WORDS), 'language': 'en'}


class WordTimeTests(unittest.TestCase):
    def test_regroup_keeps_word_times(self):
        cues = speech.regroup_words(WORDS)
        self.assertEqual(cues[0]['words'][0], [1.0, 1.4, 'Hello'])
        self.assertEqual(' '.join(word[2] for word in cues[0]['words']), cues[0]['text'])
        self.assertTrue(speech.has_words({'segments': cues}))
        self.assertFalse(speech.has_words({'segments': [{'start': 0, 'end': 1, 'text': 'x'}]}))
        self.assertFalse(speech.has_words({'segments': []}))

    def test_continuation_pieces_are_glued(self):
        cues = speech.regroup_words([(0, 0.3, ' Image'), (0.3, 0.6, '-based'), (0.6, 1.0, ' tests'),
                                     (1.0, 1.2, ' don'), (1.2, 1.4, "'t"), (1.4, 1.8, ' fail.')])
        self.assertEqual(cues[0]['text'], "Image-based tests don't fail.")
        self.assertEqual([word[2] for word in cues[0]['words']], ['Image-based', 'tests', "don't", 'fail.'])
        self.assertEqual(cues[0]['words'][0][:2], [0.0, 0.6])

    def test_cached_result_without_words_is_redone_when_needed(self):
        old = {'segments': [{'start': 0.0, 'end': 1.0, 'text': 'hi'}], 'language': 'en'}
        with mock.patch.object(speech, 'load_cached', return_value=old), \
                mock.patch.object(speech, 'backend', return_value=None):
            quiet = lambda *_: None  # noqa: E731
            self.assertIs(speech.transcribe('v.mkv', log=quiet), old)
            with self.assertRaises(RuntimeError):   # yeniden cikarmaya calisir (burada paket yok)
                speech.transcribe('v.mkv', need_words=True, log=quiet)


class TimingTests(unittest.TestCase):
    def test_retime_srt_offset_scale_and_window(self):
        kind, payload = subtitle.parse_by_extension(SRT, '.srt')
        _, cues = subtitle_sync.retime(kind, payload, Timing(1.0, 1.25))
        self.assertEqual((cues[0].start, cues[0].end), ('00:00:02,250', '00:00:04,750'))
        self.assertEqual(payload[0].start, '00:00:01,000')   # kaynak degismez
        _, cues = subtitle_sync.retime(kind, payload, Timing(2.0, 0.0))
        self.assertEqual(cues[1].start, '00:00:10,000')
        # Klip: 4. saniyeden baslayan 2 sn'lik pencere
        _, cues = subtitle_sync.retime(kind, payload, Timing(1.0, -4.0), length=2.0)
        self.assertEqual(len(cues), 1)
        self.assertEqual((cues[0].start, cues[0].end), ('00:00:01,000', '00:00:02,000'))

    def test_retime_ass_keeps_comments_and_fields(self):
        kind, payload = subtitle.parse_by_extension(ASS, '.ass')
        kind, payload = subtitle_sync.retime(kind, payload, Timing(1.0, -2.0))
        text = subtitle.render_by_kind(kind, payload, subtitle.cues_of(kind, payload))
        self.assertIn('Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,{\\i1}Hello{\\i0} there.', text)
        self.assertIn('Comment: 0,0:00:02.00,0:00:04.00', text)
        self.assertIn('0:00:03.00,0:00:06.00', text)

    def test_two_point(self):
        timing = subtitle_sync.two_point((10.0, 12.0), (110.0, 116.0))
        self.assertAlmostEqual(timing.scale, 1.04)
        self.assertAlmostEqual(timing(10.0), 12.0)
        self.assertAlmostEqual(subtitle_sync.two_point((10.0, 9.0), None).offset, -1.0)
        with self.assertRaises(ValueError):
            subtitle_sync.two_point((10.0, 9.0), (10.5, 11.0))

    def test_timing_validation(self):
        self.assertTrue(Timing.of(None).identity)
        with self.assertRaises(ValueError):
            Timing.of({'scale': 3})

    def test_auto_align_finds_offset_and_frame_rate(self):
        rng = random.Random(7)
        speech_spans, t = [], 4.0
        while t < 1800:
            length = rng.uniform(0.8, 4)
            speech_spans.append((t, t + length))
            t += length + rng.uniform(0.3, 6)
        for scale, offset in ((1.0, 2.3), (1.0, -31.4), (23.976 / 25, 1.2)):
            # Altyazi konusmadan biraz uzun kalir (gercek altyazilar gibi).
            cues = [((a - offset) / scale + rng.uniform(-0.08, 0.08), (b - offset) / scale + rng.uniform(0.3, 1.2))
                    for a, b in speech_spans if rng.random() < 0.85]
            found = subtitle_sync.auto_align(cues, speech_spans)
            self.assertAlmostEqual(found['scale'], scale, places=4)
            self.assertAlmostEqual(found['offset'], offset, delta=0.12)
            self.assertEqual(found['confidence'], 'high')
            self.assertGreater(found['score'], found['before'])

    def test_auto_align_unrelated_subtitle_is_low_confidence(self):
        rng = random.Random(1)
        speech_spans = [(t, t + 2) for t in range(0, 1800, 7)]
        cues = [(s, s + 2) for s in (rng.uniform(0, 1800) for _ in range(200))]
        self.assertEqual(subtitle_sync.auto_align(cues, speech_spans)['confidence'], 'low')

    def test_auto_align_needs_data(self):
        with self.assertRaises(ValueError):
            subtitle_sync.auto_align([(1, 2)], [(1, 2), (3, 4), (5, 6)])


class ExportTests(unittest.TestCase):
    def test_document_conversions(self):
        kind, payload = subtitle.parse_by_extension(ASS, '.ass')
        srt = subtitle_export.render_document(kind, payload, 'srt', {'offset': 1})
        self.assertIn('00:00:02,000 --> 00:00:04,500\nHello there.', srt)
        self.assertIn('Second line\non two rows.', srt)
        self.assertNotIn('note', srt)
        same = subtitle_export.render_document(kind, payload, 'source')
        self.assertIn('{\\i1}Hello{\\i0}', same)
        kind, payload = subtitle.parse_by_extension(SRT, '.srt')
        vtt = subtitle_export.render_document(kind, payload, 'vtt')
        self.assertTrue(vtt.startswith('WEBVTT'))
        self.assertIn('00:00:01.000 --> 00:00:03.500', vtt)
        ass = subtitle_export.render_document(kind, payload, 'ass')
        self.assertIn('Dialogue: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,Second line\\Non two rows.', ass)
        with self.assertRaises(ValueError):
            subtitle_export.render_document(kind, payload, 'karaoke')
        with self.assertRaises(ValueError):   # pencerede satir yok
            subtitle_export.render_document(kind, payload, 'srt', {'offset': -100}, length=5)

    def test_karaoke_ass(self):
        text = subtitle_export.render_whisper(whisper_result(), 'karaoke', style={'color': '#ff0000', 'mode': 'k'})
        self.assertIn('Style: Default,Arial,64,&H000000FF,&H00FFFFFF', text)
        line = next(item for item in text.splitlines() if item.startswith('Dialogue') and 'Hello' in item)
        self.assertTrue(line.startswith('Dialogue: 0,0:00:01.00,0:00:06.60,'))
        self.assertIn('{\\k50}Hello {\\k50}there,', line)
        self.assertIn('\\N', line)
        # Sureler satir suresine esit (kayma birikmez)
        durations = [int(value) for value in __import__('re').findall(r'\\k(\d+)', line)]
        self.assertEqual(sum(durations), 560)

    def test_word_formats(self):
        result = whisper_result()
        highlight = subtitle_export.render_whisper(result, 'highlight')
        self.assertEqual(highlight.count('<font color="#FFD400">'), len(WORDS))
        vtt = subtitle_export.render_whisper(result, 'vtt_words')
        self.assertIn('<00:00:01.500><c>there,</c>', vtt)
        single = subtitle_export.render_whisper(result, 'words_srt')
        self.assertEqual(len(subtitle.parse_srt(single)), len(WORDS))
        data = json.loads(subtitle_export.render_whisper(result, 'json'))
        self.assertEqual(data['segments'][0]['words'][0], {'start': 1.0, 'end': 1.4, 'word': 'Hello'})
        plain = subtitle_export.render_whisper(result, 'srt', {'offset': 0.5})
        self.assertIn('00:00:01,500 -->', plain)

    def test_clip_window_on_words(self):
        segments = subtitle_export.retime_segments(whisper_result()['segments'], Timing(1.0, -4.0), length=3.0)
        self.assertEqual([word[2] for word in segments[0]['words']], ['how', 'are', 'you', 'doing', 'today?'])
        self.assertEqual(segments[0]['start'], 0.0)
        self.assertLessEqual(max(word[1] for word in segments[0]['words']), 3.0)

    def test_word_formats_need_words(self):
        result = {'segments': [{'start': 0.0, 'end': 1.0, 'text': 'hi'}]}
        with self.assertRaises(ValueError):
            subtitle_export.render_whisper(result, 'karaoke')
        self.assertIn('hi', subtitle_export.render_whisper(result, 'srt'))

    def test_mov_text_font_size_is_dropped(self):
        text = '1\n00:00:01,000 --> 00:00:02,000\n<font size="54">>> HEY</font> <font color="#ff0" size=54>a</font>\n'
        kind, payload = subtitle.parse_by_extension(text, '.srt')
        out = subtitle_export.render_document(kind, payload, 'source')
        self.assertIn('>> HEY <font color="#ff0">a</font>', out)
        self.assertNotIn('size', out)

    def test_native_subtitle_written_for_mpv(self):
        import bridge_native

        class Host(bridge_native.NativePlayerMixin, bridge_subtitles.SubtitleToolsMixin):
            def _log(self, message):
                pass
        host = Host()
        host._init_native()
        host._native = mock.Mock()
        result = {'segments': speech.regroup_words(WORDS), 'language': 'en'}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(bridge_subtitles.qa, 'work_dir', return_value=Path(folder)), \
                mock.patch.object(bridge_native.qa, 'work_dir', return_value=Path(folder)), \
                mock.patch.object(host, '_whisper_for', return_value=result):
            self.assertTrue(host.mpv_subtitle('v.mkv', 'whisper', {'offset': 1}))
            target = host._native.subtitle.call_args.args[0]
            self.assertEqual(target.suffix, '.ass')
            self.assertIn('{\\kf', target.read_text(encoding='utf-8'))
            self.assertIn('0:00:02.00', target.read_text(encoding='utf-8'))
            host.mpv_subtitle('v.mkv', None)
            host._native.subtitle.assert_called_with(None)

    def test_native_panel_keeps_rect_before_creation(self):
        import native_player
        player = native_player.NativePlayer(window=None, emit=lambda *_: None)
        player.place(10, 20, 640, 360, True)   # panel henuz yok: konum saklanmali (F125)
        self.assertEqual(player._rect, (10, 20, 640, 360, True))
        panel = mock.Mock()
        player._apply(panel)
        panel.SetBounds.assert_called_once_with(10, 20, 640, 360)
        self.assertTrue(panel.Visible)

    def test_native_clicks_are_forwarded_once(self):
        import native_player
        events = []
        player = native_player.NativePlayer(window=None, emit=lambda name, data: events.append(data['key']))
        player._key('d-', 'MBTN_LEFT')
        player._key('u-', 'MBTN_LEFT')     # birakma sayilmaz
        player._key('d-', 'MBTN_LEFT')
        self.assertEqual(events, ['MBTN_LEFT', 'MBTN_LEFT'])   # cift tiklamayla tam ekran yok (F129)

    def test_native_open_applies_volume(self):
        import native_player
        player = native_player.NativePlayer(window=None, emit=lambda *_: None)
        player.player = mock.Mock(track_list=[])
        player._options = player._settings()
        with mock.patch.object(player, '_ensure'):
            player.open('v.mkv', 0, False, 0.3, True)
        self.assertAlmostEqual(player.player.volume, 30.0)
        self.assertTrue(player.player.mute)

    def test_style_sanitised(self):
        style = subtitle_export.style_of({'color': 'red', 'size': 999, 'mode': 'x', 'font': 'A,B'})
        self.assertEqual((style['color'], style['size'], style['mode'], style['font']), ('#FFD400', 160, 'kf', 'A B'))


# --- goruntu tabanli altyazi --------------------------------------------------------
def _seg(kind, data, pts):
    return b'PG' + struct.pack('>IIBH', pts, 0, kind, len(data)) + data


def _rle(image):
    width, height = image.size
    pixels = image.load()
    out = bytearray()
    for y in range(height):
        x = 0
        while x < width:
            color, run = pixels[x, y], 1
            while x + run < width and pixels[x + run, y] == color and run < 16383:
                run += 1
            if color == 0:
                out += bytes([0, run]) if run < 64 else bytes([0, 0x40 | (run >> 8), run & 0xFF])
            elif run < 3:
                out += bytes([color]) * run
            elif run < 64:
                out += bytes([0, 0x80 | run, color])
            else:
                out += bytes([0, 0xC0 | (run >> 8), run & 0xFF, color])
            x += run
        out += b'\x00\x00'
    return bytes(out)


def make_sup(items, width=640, height=360):
    """Kucuk bir PGS (.sup) dosyasi: [(yazi, baslangic, bitis)]."""
    from PIL import Image, ImageDraw
    data = b''
    for number, (text, start, end) in enumerate(items):
        image = Image.new('P', (220, 30), 0)
        ImageDraw.Draw(image).text((6, 8), text, fill=1)
        x, y = (width - 220) // 2, height - 60
        pts, stop = int(start * 90000), int(end * 90000)
        pcs = struct.pack('>HHBHBBBB', width, height, 0x10, number * 2, 0x80, 0, 0, 1) + struct.pack('>HBBHH', 0, 0, 0, x, y)
        wds = struct.pack('>BBHHHH', 1, 0, x, y, 220, 30)
        palette = bytes([0, 0, 0, 16, 128, 128, 0, 1, 235, 128, 128, 255])
        rle = _rle(image)
        ods = struct.pack('>HBB', 0, 0, 0xC0) + (len(rle) + 4).to_bytes(3, 'big') + struct.pack('>HH', 220, 30) + rle
        clear = struct.pack('>HHBHBBBB', width, height, 0x10, number * 2 + 1, 0, 0, 0, 0)
        data += _seg(0x16, pcs, pts) + _seg(0x17, wds, pts) + _seg(0x14, palette, pts) + _seg(0x15, ods, pts) + _seg(0x80, b'', pts)
        data += _seg(0x16, clear, stop) + _seg(0x17, wds, stop) + _seg(0x80, b'', stop)
    return data


class OcrTests(unittest.TestCase):
    def test_events_group_frames(self):
        frames = [(0.0, 'AAAA0001', 'a'), (0.5, 'AAAA0001', 'b'), (1.0, subtitle_ocr.EMPTY, 'c'),
                  (2.0, 'BBBB0002', 'd'), (3.0, 'CCCC0003', 'e'), (30.0, subtitle_ocr.EMPTY, 'f')]
        events = subtitle_ocr.events(frames, duration=40.0)
        self.assertEqual([(start, end, key) for start, end, key, _ in events],
                         [(0.0, 1.0, 'AAAA0001'), (2.0, 3.0, 'BBBB0002'), (3.0, 13.0, 'CCCC0003')])

    def test_clean_text_and_languages(self):
        self.assertEqual(subtitle_ocr.clean_text('  Hello |\n\n  world  \n'), 'Hello I\nworld')
        self.assertEqual(subtitle_ocr.tesseract_lang('ger'), 'deu')
        self.assertIsNone(subtitle_ocr.tesseract_lang('xx'))

    def test_prepare_image_crops_and_inverts(self):
        from PIL import Image
        image = Image.new('RGBA', (400, 200), (0, 0, 0, 0))
        for x in range(150, 250):
            for y in range(150, 170):
                image.putpixel((x, y), (255, 255, 255, 255))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'f.png'
            image.save(path)
            png = subtitle_ocr.prepare_image(path)
            Image.new('RGBA', (10, 10), (0, 0, 0, 0)).save(path)
            self.assertIsNone(subtitle_ocr.prepare_image(path))
        result = Image.open(io.BytesIO(png))
        self.assertEqual(result.mode, 'L')
        self.assertLess(result.width, 400)
        self.assertEqual(result.getpixel((0, 0)), 255)          # beyaz zemin
        self.assertEqual(result.getpixel((result.width // 2, result.height // 2)), 0)   # koyu yazi

    def test_render_frames_reads_ffmpeg6_times(self):
        # FFmpeg 6.x pts_time'i %g ile yazar: 4.29497e+06 ve 1234.57; zaman pts * time_base'den gelir.
        lines = ['[Parsed_showinfo_0 @ 0] config in time_base: 1/1000, frame_rate: 0/1\n',
                 '[Parsed_showinfo_0 @ 0] config out time_base: 0/0, frame_rate: 0/0\n',
                 '[Parsed_showinfo_0 @ 0] n:   0 pts:   4000 pts_time:4       duration:      0 checksum:CFD66AA3 mean:[0]\n',
                 '[Parsed_showinfo_0 @ 0] n:   1 pts:1234567 pts_time:1234.57 duration:      0 checksum:00000000 mean:[0]\n',
                 '[Parsed_showinfo_0 @ 0] n:   2 pts:4294972295 pts_time:4.29497e+06 duration:      0 checksum:00000000\n']
        process = mock.Mock(stderr=mock.MagicMock(), wait=mock.Mock(return_value=0))
        process.stderr.__iter__.return_value = iter(lines)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(media, 'ffmpeg_path', return_value='ffmpeg'), \
                mock.patch.object(subtitle_ocr.subprocess, 'Popen', return_value=process):
            for number in range(3):
                (Path(folder) / f'{number + 1:06d}.png').write_bytes(b'')
            frames = subtitle_ocr.render_frames('v.mkv', 1, folder)
        self.assertEqual([(seconds, checksum) for seconds, checksum, _ in frames],
                         [(4.0, 'CFD66AA3'), (1234.567, '00000000'), (4294972.295, '00000000')])

    @unittest.skipUnless(ffmpeg_available(), 'ffmpeg yok')
    def test_recognize_pgs_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 's.sup').write_bytes(make_sup([('First', 1.0, 2.5), ('Second', 4.0, 5.0)]))
            video = folder / 'v.mkv'
            subprocess.run([media.ffmpeg_path(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=640x360:d=7',
                            '-itsoffset', '1', '-i', str(folder / 's.sup'), '-map', '0', '-map', '1',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-c:s', 'copy', str(video)], check=True)
            stream = next(item for item in media.subtitle_streams(video) if item['image'])
            texts = iter(['First', 'Second'])
            reader = lambda png: next(texts)  # noqa: E731
            reader.workers = 1
            result = subtitle_ocr.recognize(video, stream, {}, base=folder, log=lambda *_: None, reader=reader)
            self.assertEqual([(item['text'], item['start'], item['end']) for item in result['segments']],
                             [('First', 1.0, 2.5), ('Second', 4.0, 5.0)])
            self.assertIsNotNone(subtitle_ocr.load_cached(video, stream['index'], base=folder))


class ClipTests(unittest.TestCase):
    def test_options_force_reencode(self):
        self.assertEqual(clip.options_of({'mode': 'fast', 'subtitles': 'burn'})['mode'], 'precise')
        self.assertEqual(clip.options_of({'mode': 'fast', 'height': 720})['mode'], 'precise')
        self.assertEqual(clip.options_of({'mode': 'fast'})['mode'], 'fast')
        self.assertEqual(clip.options_of({'format': 'gif', 'subtitles': 'embed'})['subtitles'], 'burn')
        self.assertEqual(clip.options_of({'format': 'm4a', 'subtitles': 'burn'})['subtitles'], 'file')
        self.assertEqual(clip.options_of({'format': 'avi'})['format'], 'mp4')

    def test_commands(self):
        info = {'video': {'index': 0, 'codec': 'hevc', 'height': 1080}}
        with mock.patch.object(media, 'ffmpeg_path', return_value='ffmpeg'):
            fast = clip.build_command('in.mkv', 10, 20, 'out.mp4', {'mode': 'fast'}, info)
            self.assertEqual(fast[fast.index('-ss') + 1], '10.000')
            self.assertEqual(fast[fast.index('-t') + 1], '10.000')
            self.assertIn('copy', fast)
            self.assertIn('hvc1', fast)
            burn = clip.build_command('in.mkv', 10, 20, 'out.mp4', {'subtitles': 'burn', 'height': 720}, info, 'clip.ass', 'ass')
            self.assertEqual(burn[burn.index('-vf') + 1], 'subtitles=clip.ass,scale=-2:720')
            self.assertIn('libx264', burn)
            embed = clip.build_command('in.mkv', 0, 5, 'out.mkv', {'format': 'mkv', 'subtitles': 'embed', 'audio': 3}, info,
                                       'clip.ass', 'ass')
            self.assertEqual(embed[embed.index('-c:s') + 1], 'ass')
            self.assertIn('0:3', embed)
            sized = clip.build_command('in.mkv', 0, 5, 'out.mp4', {'subtitles': 'burn', 'font_size': 108}, info,
                                       'clip.srt', 'srt')
            self.assertEqual(sized[sized.index('-vf') + 1], "subtitles=clip.srt:force_style='Fontsize=29'")
            styled = clip.build_command('in.mkv', 0, 5, 'out.mp4', {'subtitles': 'burn', 'font_size': 108}, info,
                                        'clip.ass', 'ass')
            self.assertEqual(styled[styled.index('-vf') + 1], 'subtitles=clip.ass')
            gif = clip.build_command('in.mkv', 0, 5, 'out.gif', {'format': 'gif'}, info)
            self.assertIn('palettegen', gif[gif.index('-vf') + 1])
            audio = clip.build_command('in.mkv', 0, 5, 'out.m4a', {'format': 'm4a'}, info)
            self.assertIn('-vn', audio)

    def test_default_name(self):
        self.assertEqual(clip.default_name('C:/x/Film.mkv', 75, 3725, 'mp4'), 'Film [01-15 – 1-02-05].mp4')

    @unittest.skipUnless(ffmpeg_available(), 'ffmpeg yok')
    def test_save_with_burned_karaoke_and_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            video = folder / 'v.mp4'
            subprocess.run([media.ffmpeg_path(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=8',
                            '-f', 'lavfi', '-i', 'sine=d=8', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
                            str(video)], check=True)
            text = subtitle_export.render_whisper(whisper_result(), 'karaoke', Timing(1.0, -1.0), 5.0)
            seen = []
            result = clip.save(video, 1.0, 6.0, folder / 'c.mp4', {'subtitles': 'burn'}, None, text, 'ass',
                               progress=lambda done, total: seen.append(done))
            self.assertTrue(Path(result['output']).stat().st_size > 0)
            self.assertTrue(seen)
            result = clip.save(video, 1.0, 3.0, folder / 'd.mkv', {'mode': 'fast', 'subtitles': 'file'}, None,
                               'x', 'srt')
            self.assertEqual(Path(result['subtitle']).name, 'd.srt')
            with self.assertRaises(ValueError):
                clip.save(video, 1.0, 1.05, folder / 'e.mp4', {}, None)
            with self.assertRaises(ValueError):
                clip.save(video, 1.0, 3.0, video, {}, None)


class BridgeToolTests(unittest.TestCase):
    class Host(bridge_subtitles.SubtitleToolsMixin):
        def __init__(self, target):
            self.events, self.logs, self.target = [], [], target
            self._init_subtools()

        def _emit(self, event, data):
            self.events.append((event, data))

        def _log(self, message):
            self.logs.append(message)

        def _dialog(self, name, *args):
            return str(self.target) if name == 'save_file' else None

    def test_export_file_source_with_timing(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            video, sub = folder / 'Film.mkv', folder / 'Film.srt'
            video.write_bytes(b'')
            sub.write_text(SRT, encoding='utf-8')
            host = self.Host(folder / 'out')
            info = host.subtitle_info(str(video), 'file:' + str(sub))
            self.assertEqual(info['kind'], 'srt')
            self.assertNotIn('karaoke', [item['id'] for item in info['formats']])
            result = host.subtitle_export(str(video), 'file:' + str(sub), 'vtt', {'offset': -0.5})
            self.assertEqual(result['name'], 'out.vtt')
            self.assertIn('00:00:00.500 --> 00:00:03.000', (folder / 'out.vtt').read_text(encoding='utf-8'))

    def test_whisper_word_format_requires_words(self):
        host = self.Host('x')
        old = {'segments': [{'start': 0.0, 'end': 1.0, 'text': 'hi'}], 'language': 'en'}
        with mock.patch.object(host, '_whisper_for', return_value=old):
            result = host.subtitle_export('v.mkv', 'whisper', 'karaoke')
            self.assertTrue(result.get('need_words'))
            info = host.subtitle_info('v.mkv', 'whisper')
            self.assertFalse(info['words'])
            self.assertIn('karaoke', [item['id'] for item in info['formats']])

    def test_word_extraction_reports_old_helper(self):
        host = self.Host('x')
        old = {'segments': [{'start': 0.0, 'end': 1.0, 'text': 'hi'}], 'language': 'en'}
        with mock.patch.object(speech, 'available', return_value=(True, '')), \
                mock.patch.object(host, '_transcribe', return_value=old):
            host.whisper_words('v.mkv')
            host._tool['thread'].join(5)
        final = host.events[-1][1]
        self.assertEqual(final['state'], 'error')
        self.assertIn('aktar-whisper', final['message'])

    def test_save_dialog_opens_in_video_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            video, sub = folder / 'Film.mkv', folder / 'Film.srt'
            video.write_bytes(b'')
            sub.write_text(SRT, encoding='utf-8')
            host = self.Host(folder / 'out')
            with mock.patch.object(host, '_dialog', wraps=host._dialog) as dialog:
                host.subtitle_export(str(video), 'file:' + str(sub), 'srt')
            self.assertEqual(dialog.call_args.args[-1], str(folder))

    def test_burned_plain_subtitle_uses_chosen_size_and_colour(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            video, sub = folder / 'Film.mkv', folder / 'Film.srt'
            video.write_bytes(b'')
            sub.write_text(SRT, encoding='utf-8')
            host = self.Host(folder / 'clip.mp4')
            with mock.patch.object(clip, 'save', return_value={'output': 'x', 'subtitle': ''}) as save, \
                    mock.patch.object(bridge_subtitles.media_server, 'probe', return_value={}):
                host.clip_save(str(video), 0.5, 6, {'subtitles': 'burn', 'font_size': 90}, 'file:' + str(sub),
                               None, 'srt', {'base': '#00FF00'})
                host._tool['thread'].join(5)
            text, ext = save.call_args.args[6], save.call_args.args[7]
            self.assertEqual(ext, 'ass')
            self.assertIn('Style: Default,Arial,90,&H0000FF00', text)
            self.assertIn('Dialogue: 0,0:00:00.50,0:00:03.00', text)

    def test_clip_requires_subtitle_choice(self):
        host = self.Host('x')
        self.assertIn('error', host.clip_save('v.mkv', 0, 5, {'subtitles': 'burn'}, None))
        self.assertIn('error', host.clip_save('v.mkv', 5, 5))


if __name__ == '__main__':
    unittest.main()
