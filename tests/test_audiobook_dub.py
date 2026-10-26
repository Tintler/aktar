"""Sesli kitap (audiobook.py) ve dublaj (dub.py) testleri: saf hesaplar ve gercek FFmpeg ile uctan uca
(ses motoru yerine sahte motor; FFmpeg yoksa uctan uca testler atlanir)."""
from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from array import array
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import audiobook  # noqa: E402
import book_video  # noqa: E402
import dub  # noqa: E402
import media  # noqa: E402
from app_core import GracefulStop  # noqa: E402
from tts import Cancelled  # noqa: E402

try:
    FFMPEG = media.ffmpeg_path()
    FFPROBE = media.ffprobe_path()
except RuntimeError:
    FFMPEG = FFPROBE = None

RATE = 16000


def tone(seconds, rate=RATE):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b'\x10\x08' * int(rate * seconds))
    return buffer.getvalue()


class FakeEngines:
    """tts.Engines yerine: her karakter 0,05 sn ses; hiz verilirse kisalir."""

    def __init__(self, app_dir):
        self.app_dir = Path(app_dir)
        self.calls = []
        self.emotions = {}    # F168: cumle -> duygu etiketi

    def choice(self, language, override=None):
        return ('sahte', (override or {}).get('voice', 'sahte/ses').split('/')[1])

    def _voice_options(self, engine_id, voice_id, override=None):
        return {}

    def emotion_tag(self, book, text, language='tr', override=None):
        return self.emotions.get(text, '') if book else ''

    def say(self, text, speed=1.0, book=None, language='tr', override=None):
        self.calls.append((text, speed))
        data = tone(len(text) * 0.05 / speed)
        return {'audio': base64.b64encode(data).decode('ascii'), 'duration': len(text) * 0.05 / speed}

    def export(self, sentences, speed, path, progress=None, book=None, language='tr', gaps=None,
               override=None, cancel=None, breaks=None, starts=None, chunks=None):
        self.overrides = getattr(self, 'overrides', []) + [override]
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(RATE)
            for index, text in enumerate(sentences):
                if cancel is not None and cancel.is_set():
                    raise Cancelled('Ses kaydı durduruldu.')
                if starts is not None:
                    starts[index] = out.getnframes() / RATE
                if chunks is not None:
                    chunks.append([index, index, out.getnframes() / RATE])
                with wave.open(io.BytesIO(base64.b64decode(self.say(text, speed)['audio']))) as clip:
                    out.writeframes(clip.readframes(clip.getnframes()))
                if progress:
                    progress(index + 1, len(sentences))
        return len(sentences)


def probe(path):
    result = subprocess.run([FFPROBE, '-v', 'error', '-show_streams', '-show_format', '-show_chapters', '-of', 'json',
                             str(path)], capture_output=True, text=True, encoding='utf-8')
    return json.loads(result.stdout)


class AudiobookPureTests(unittest.TestCase):
    def test_chapter_list_drops_empty_and_names_untitled(self):
        chapters = audiobook.chapter_list([
            {'title': '', 'sentences': ['Bir.', '  ', 'İki.'], 'gaps': [0.5, 0.1, 0.9], 'breaks': [2]},
            {'title': 'Boş', 'sentences': ['   ']},
            {'title': '  Son   bölüm ', 'sentences': ['Üç.']},
        ])
        self.assertEqual([c['title'] for c in chapters], ['Bölüm 1', 'Son bölüm'])
        self.assertEqual(chapters[0]['sentences'], ['Bir.', 'İki.'])
        self.assertEqual(chapters[0]['gaps'], [0.5, 0.9])
        self.assertEqual(chapters[1]['gaps'], [None])
        self.assertEqual((chapters[0]['breaks'], chapters[1]['breaks']), ([1], None))   # F186: bos cumle cikinca kayar

    def test_ffmetadata_chapters_are_contiguous_and_escaped(self):
        text = audiobook.ffmetadata('Kitap=1; #2', 'Yazar', [('A', 1.5), ('B\\C', 2.25)])
        self.assertIn('title=Kitap\\=1\\; \\#2', text)
        self.assertIn('START=0\nEND=1500\ntitle=A', text)
        self.assertIn('START=1500\nEND=3750\ntitle=B\\\\C', text)
        self.assertTrue(text.startswith(';FFMETADATA1\n'))

    def test_concat_list_escapes_quotes(self):
        line = audiobook.concat_list([Path("C:/a/it's.m4a")])
        self.assertIn("it'\\''s.m4a", line)

    def test_chapter_list_maps_images_past_empty_sentences(self):
        chapters = audiobook.chapter_list([{'sentences': ['A.', ' ', 'B.', 'C.'],
                                            'images': [[3, 'c.png'], [1, 'b.png'], ['x', 'y'], [9, 'z.png']]}])
        self.assertEqual(chapters[0]['images'], [(1, 'b.png'), (2, 'c.png')])

    def test_safe_name(self):
        self.assertEqual(audiobook.safe_name('Ana: Bir/İki?'), 'Ana Bir İki')
        self.assertEqual(audiobook.safe_name(' .. '), 'kitap')


class AudiobookImagesTests(unittest.TestCase):
    """F207: bridge_tts._audiobook_images kitap gorsellerinin sahnelerini sesli kitap bolumlerine baglar."""

    def test_scenes_follow_sections_and_anchor(self):
        import bridge_tts
        folder = Path(tempfile.mkdtemp(prefix='aktar-test-gorsel-'))
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        for name in ('a.png', 'b.png', 'c.png'):
            (folder / name).write_bytes(b'x')
        plan = {'scenes': [{'section': 1, 'start': 0, 'anchor': 'Önce.', 'image': 'a.png'},
                           {'section': 2, 'start': 0, 'anchor': 'Kaydı.', 'image': 'b.png'},     # bolme degismis
                           {'section': 3, 'start': 0, 'anchor': 'Son.', 'image': 'c.png', 'skip': True},
                           {'section': 3, 'start': 0, 'anchor': 'Yok.', 'image': 'yok.png'}]}
        store = mock.Mock(image_path=lambda book, scene: folder / scene['image'])
        host = mock.Mock(_art_store=lambda: store, _art_load=lambda book: plan)
        chapters = [{'sentences': ['Bir.', 'İki.', 'Kaydı.', 'Üç.'], 'sections': [[2, 0]]},
                    {'sentences': ['Son.'], 'sections': [[3, 0]]}]
        first = bridge_tts.TtsMixin._audiobook_images(host, 'kitap', chapters)
        self.assertEqual(first, str(folder / 'a.png'))                     # bolum 1 okunmadi: basta gosterilir
        self.assertEqual(chapters[0]['images'], [[2, str(folder / 'b.png')]])
        self.assertEqual(chapters[1]['images'], [])


class BookVideoTests(unittest.TestCase):
    """F208: tam ekran okuyucu kareleri (book_video)."""

    def test_options_are_cleaned(self):
        opts = book_video.options({'background': 'x', 'size': 999, 'band': -1, 'height': 480, 'font': 'sans',
                                   'colors': {'bg': 'rgb(244, 236, 216)', 'ink': '#123'}, 'motion': 'fade'})
        self.assertEqual((opts['background'], opts['size'], opts['band'], opts['height'], opts['font'], opts['motion']),
                         ('art', 120, 0.0, 1080, 'sans', 'fade'))
        self.assertEqual(opts['colors'], {'bg': '#f4ecd8', 'ink': '#112233'})
        self.assertEqual(book_video.fps_for(book_video.options({'motion': 'none', 'art_motion': 'cut'})), book_video.FPS_STILL)
        self.assertEqual(book_video.fps_for(book_video.options({})), book_video.FPS_MOTION)

    def test_easings_match_svelte(self):
        self.assertAlmostEqual(book_video.cubic_out(0.5), 0.875)
        self.assertAlmostEqual(book_video.cubic_in_out(0.25), 0.0625)
        self.assertAlmostEqual(book_video.css_ease(0.5), 0.8024, places=3)
        self.assertEqual((book_video.css_ease(0), book_video.css_ease(1)), (0.0, 1.0))

    def test_long_text_shrinks_to_fit_and_is_centered(self):
        renderer = book_video.Renderer({'height': 720, 'size': 120})
        size, lines = renderer.layout('kelime ' * 400)
        self.assertLess(size, 120 * 720 / 1080)
        self.assertLessEqual(len(lines) * size * book_video.LEADING, renderer.stage_height)
        short, _lines = renderer.layout('Kısa.')
        self.assertEqual(short, 80)
        frame = renderer.frame('Kısa.')
        self.assertEqual(frame.size, (1280, 720))
        self.assertEqual(frame.getpixel((10, 10)), (0, 0, 0))                # sayfa rengi
        box = frame.convert('L').point(lambda v: 255 if v > 128 else 0).getbbox()
        self.assertTrue(box and abs((box[0] + box[2]) / 2 - 640) < 8, box)     # yazi ortada

    def test_states_merge_still_frames_and_animate_changes(self):
        renderer = book_video.Renderer({'height': 720, 'art_motion': 'cut'})
        fps = book_video.FPS_MOTION
        states = book_video.chapter_states([('Bir.', 0.0), ('İki.', 2.0)], [], None, 0.0, 0, 4 * fps, fps, renderer)
        self.assertEqual(sum(count for _state, count in states), 4 * fps)
        still = [s for s in states if s[0][2] is None]
        self.assertEqual([(s[0][0], s[1]) for s in still], [('Bir.', 2 * fps - 20), ('İki.', 2 * fps - 20)])
        moving = [s for s in states if s[0][2] is not None and s[0][0] == 'İki.']
        self.assertEqual(len(moving), 20)                               # 0,77 sn kayma 25 kare/sn
        self.assertEqual(moving[0][0][1], 'Bir.')                       # giden yazi
        carried = book_video.chapter_states([('Üç.', 0.0)], [], None, 4.0, 4 * fps, 5 * fps, fps, renderer, before='İki.')
        self.assertEqual(carried[0][0][1], 'İki.')                     # bolum basinda onceki bolumun yazisi gider
        none = book_video.Renderer({'motion': 'none', 'art_motion': 'cut'})
        self.assertEqual(len(book_video.chapter_states([('Bir.', 0.0), ('İki.', 2.0)], [], None, 0.0, 0, 8, 2, none)), 2)

    def test_art_crossfade_between_scenes(self):
        folder = Path(tempfile.mkdtemp(prefix='aktar-test-video-'))
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        from PIL import Image
        Image.new('RGB', (64, 36), (255, 0, 0)).save(folder / 'a.png')
        Image.new('RGB', (64, 36), (0, 0, 255)).save(folder / 'b.png')
        renderer = book_video.Renderer({'height': 720, 'text': False, 'band': 0})
        states = book_video.chapter_states([('x', 0.0)], [(1.0, str(folder / 'b.png'))], str(folder / 'a.png'),
                                           0.0, 0, 75, 25, renderer)
        middle = next(s for s in states if s[0][5] is not None and s[0][5] >= 0.2)[0]
        pixel = renderer.frame(*[middle[i] for i in (0, 3, 1, 2, 4, 5)]).getpixel((5, 5))
        self.assertTrue(pixel[0] > 60 and pixel[2] > 40, pixel)           # kirmizidan maviye gecerken ikisi de var
        self.assertEqual(renderer.frame(None, str(folder / 'b.png')).getpixel((5, 5)), (0, 0, 255))


class DubPureTests(unittest.TestCase):
    def test_lines_apply_timing_and_sort(self):
        lines = dub.lines_of([{'start': 10, 'end': 12, 'text': ' B '}, {'start': 2, 'end': 3, 'text': 'A'},
                              {'start': 4, 'end': 5, 'text': '  '}], {'scale': 2, 'offset': -1})
        self.assertEqual([(l['start'], l['end'], l['text']) for l in lines], [(3, 5, 'A'), (19, 23, 'B')])

    def test_slots_stop_at_next_line(self):
        lines = [{'start': 0, 'end': 1, 'text': 'a'}, {'start': 1.2, 'end': 2, 'text': 'b'},
                 {'start': 5, 'end': 6, 'text': 'c'}]
        self.assertEqual([round(s, 2) for s in dub.slots(lines)], [1.2, round(2 + dub.SLOT_TAIL - 1.2, 2), 1 + dub.SLOT_TAIL])

    def test_place_pushes_overlaps_and_resets_on_gaps(self):
        self.assertEqual(dub.place([0, 1, 10], [1.5, 1, 1]), [0, 1.5, 10])

    def test_regions_merge_short_gaps(self):
        self.assertEqual(dub.regions([0, 1.2, 5], [1, 1, 1]), [(0, 2.2), (5, 6)])

    def test_duck_commands_ramp_down_and_up(self):
        text = dub.duck_commands([(2.0, 4.0)], 0.2, fade=0.5, steps=2)
        rows = [line.split()[0] + ' ' + line.split()[-1] for line in text.strip().splitlines()]
        self.assertEqual(rows, ['1.500 0.6000;', '1.750 0.2000;', '4.000 0.6000;', '4.250 1.0000;'])

    def test_duck_spans_cover_original_lines(self):
        # dublaj sesi (0,5 sn) satirdan (3 sn) kisa kalsa da ozgun konusma satir boyunca kisilir
        lines = [{'start': 1.0, 'end': 4.0, 'text': 'a'}, {'start': 10.0, 'end': 11.0, 'text': 'b'}]
        spans = dub.duck_spans(lines, [1.0, 10.0], [0.5, 0.0], pad=0.2)
        self.assertEqual([(round(a, 2), round(b, 2)) for a, b in spans], [(1.0, 4.2), (10.0, 11.2)])

    def test_normalize_levels_quiet_and_loud_clips(self):
        def pcm(amplitude, count=4800):
            return array('h', [amplitude if i % 2 else -amplitude for i in range(count)]).tobytes()
        quiet = dub.normalize(pcm(800) + bytes(9600), 24000)
        loud = dub.normalize(pcm(12000), 24000)
        level = lambda data: max(array('h', data))
        self.assertAlmostEqual(level(quiet), level(loud), delta=60)
        self.assertAlmostEqual(level(loud), dub.NORM_RMS, delta=60)
        self.assertEqual(dub.normalize(bytes(4800), 24000), bytes(4800))   # sessizlik oldugu gibi

    def test_layers_mix_overlapping_clips(self):
        a, b = array('h', [100] * 10).tobytes(), array('h', [50] * 10).tobytes()
        result = dub.layers([0.0, 0.5, 3.0], [a, b, a], 10)
        self.assertEqual([start for start, _ in result], [0, 30])
        self.assertEqual(list(array('h', result[0][1])), [100] * 5 + [150] * 5 + [50] * 5)
        self.assertEqual(dub.overlaps([0.0, 0.5, 3.0], [1.0, 1.0, 1.0]), 1)

    def test_options_are_clamped(self):
        options = dub.options_of({'background': 3, 'max_tempo': 0.2, 'format': 'avi', 'audio': '2', 'x': 1})
        self.assertEqual((options['background'], options['max_tempo'], options['format'], options['audio']), (1.0, 1.0, 'mkv', 2))
        self.assertNotIn('x', options)

    @mock.patch.object(media, 'ffmpeg_path', return_value='ffmpeg')
    def test_mix_command_keeps_original_tracks_and_marks_dub_default(self, _ffmpeg):
        command = dub.mix_command('v.mkv', 'd.wav', 'o.mkv', {'audio': 3}, True, 'duck.cmd')
        graph = command[command.index('-filter_complex') + 1]
        self.assertIn('[0:3]', graph)
        self.assertIn('asendcmd=f=duck.cmd,volume@duck=1', graph)
        self.assertIn('-disposition:a:0', command)
        self.assertEqual(command[command.index('-c:a:0') + 1], 'aac')
        self.assertIn('0:a', command)
        # Gercek ornekte (HEVC kopya + Opus) dublaj paketleri 16. sn'den sonra dosya sonuna yigiliyordu.
        self.assertEqual(command[command.index('-max_interleave_delta') + 1], '0')
        self.assertIn('-max_muxing_queue_size', command)
        m4a = dub.mix_command('v.mkv', 'd.wav', 'o.m4a', {'format': 'm4a', 'duck': False, 'background': 0.5}, True)
        self.assertIn('volume=0.5000', m4a[m4a.index('-filter_complex') + 1])
        self.assertNotIn('0:v?', m4a)
        silent = dub.mix_command('v.mkv', 'd.wav', 'o.mkv', {}, False)
        self.assertNotIn('amix', silent[silent.index('-filter_complex') + 1])


@unittest.skipUnless(FFMPEG and FFPROBE, 'FFmpeg yok')
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='aktar-test-sk-'))
        self.engines = FakeEngines(self.folder)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_m4b_has_chapters_and_resumes(self):
        chapters = [{'title': 'Giriş', 'sentences': ['Merhaba dünya.', 'İkinci cümle.']},
                    {'title': 'Son', 'sentences': ['Bitti.']}]
        target = self.folder / 'kitap.m4b'
        seen = []
        result = audiobook.build(self.engines, chapters, target, 'm4b', 'Kitap', 'Yazar', None, 1.0, 'abcdef12',
                                 progress=lambda *args: seen.append(args))
        self.assertEqual(result['chapters'], 2)
        info = probe(target)
        self.assertEqual([c['tags']['title'] for c in info['chapters']], ['Giriş', 'Son'])
        self.assertEqual(info['format']['tags']['artist'], 'Yazar')
        self.assertEqual(seen[-1], (3, 3, 2, 2))
        self.assertFalse((self.folder / audiobook.WORK_DIR / 'abcdef12').exists())

        # Durdurulan is: biten bolum saklanir, ikinci sefer yeniden uretilmez.
        cancel = threading.Event()
        calls = []

        def stop_after_first(done, total, chapter, count):
            calls.append(chapter)
            if chapter == 2:
                cancel.set()
        with self.assertRaises(audiobook.Stopped):
            audiobook.build(self.engines, chapters, target, 'm4b', 'Kitap', '', None, 1.0, 'abcdef12',
                            progress=stop_after_first, cancel=cancel)
        self.assertEqual(len(list((self.folder / audiobook.WORK_DIR / 'abcdef12').glob('*.m4a'))), 1)
        self.engines.calls.clear()
        audiobook.build(self.engines, chapters, target, 'm4b', 'Kitap', '', None, 1.0, 'abcdef12')
        self.assertEqual([text for text, _ in self.engines.calls], ['Bitti.'])

    def test_mp3_folder_one_file_per_chapter(self):
        chapters = [{'title': 'Bir: başlangıç', 'sentences': ['A.']}, {'title': 'İki', 'sentences': ['B.']}]
        result = audiobook.build(self.engines, chapters, self.folder, 'mp3', 'Kitap/Adı', 'Yazar', None, 1.0, 'abcdef12')
        names = sorted(p.name for p in Path(result['output']).iterdir())
        self.assertEqual(names, ['01 - Bir başlangıç.mp3', '02 - İki.mp3'])
        tags = probe(Path(result['output']) / names[1])['format']['tags']
        self.assertEqual((tags.get('track'), tags.get('album')), ('2/2', 'Kitap/Adı'))

    def _picture(self, name, color, size='320x240'):
        path = self.folder / name
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s={size}', '-frames:v', '1',
                        str(path)], check=True)
        return path

    def test_mp4_shows_scene_images_with_chapters(self):
        red, blue = self._picture('k.png', 'red'), self._picture('m.png', 'blue', '200x400')
        chapters = [{'title': 'Giriş', 'sentences': ['Merhaba dünya, uzun bir cümle.', 'İkinci cümle burada.'],
                     'images': [[1, str(red)]]},
                    {'title': 'Son', 'sentences': ['Bitti artık, hepsi bu.'], 'images': [[0, str(blue)]]}]
        target = self.folder / 'kitap.mp4'
        seen = []
        video = {'text': False, 'band': 0, 'art_motion': 'cut', 'height': 720}     # yalnizca gorseller: 2 kare/sn
        audiobook.build(self.engines, chapters, target, 'mp4', 'Kitap', 'Yazar', None, 1.0, 'abcdef12',
                        video_progress=seen.append, video=video)
        info = probe(target)
        kinds = sorted(s['codec_type'] for s in info['streams'] if s['codec_type'] != 'data')   # data: bolum izi
        self.assertEqual(kinds, ['audio', 'video'])
        stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
        self.assertEqual((stream['width'], stream['height']), (1280, 720))
        self.assertEqual([c['tags']['title'] for c in info['chapters']], ['Giriş', 'Son'])
        self.assertTrue(seen and seen[-1] <= 1.0)
        self.assertAlmostEqual(float(stream['duration']), float(info['format']['duration']), delta=0.6)

        raw = subprocess.run([FFMPEG, '-v', 'error', '-i', str(target), '-vf', 'crop=2:2:639:359', '-f', 'rawvideo',
                              '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout

        def color_at(second):    # ortadaki piksel; kareler FPS_STILL aralikla (2x2 kare = 12 bayt)
            at = int(second * book_video.FPS_STILL) * 12
            return raw[at], raw[at + 1], raw[at + 2]

        first = len('Merhaba dünya, uzun bir cümle.') * 0.05
        self.assertLess(max(color_at(first / 2)), 30)                    # sahne yok: sayfa rengi (siyah)
        r, g, b = color_at(first + 0.6)
        self.assertTrue(r > 150 and b < 80, (r, g, b))                    # ikinci cumlede kirmizi
        r, g, b = color_at(float(info['format']['duration']) - 0.3)
        self.assertTrue(b > 150 and r < 80, (r, g, b))                    # son bolumde mavi

    def test_mp4_keeps_chapter_video_and_uses_chosen_voice(self):
        chapters = [{'title': 'Bir', 'sentences': ['Merhaba.', 'Nasılsın?']}, {'title': 'İki', 'sentences': ['Son.']}]
        target = self.folder / 'kitap.mp4'
        voice = {'voice': 'sahte/baska', 'options': None}
        video = {'background': 'plain', 'height': 720, 'motion': 'fade'}
        audiobook.build(self.engines, chapters, target, 'mp4', 'Kitap', '', None, 1.0, 'abcdef12', video=video,
                        override=voice)
        self.assertEqual(self.engines.overrides, [voice, voice])
        self.assertEqual(round(float(probe(target)['format']['duration'])), 1)
        # Durdurulup yeniden baslatilan is: biten bolumun goruntu parcasi yeniden cizilmez.
        cancel = threading.Event()
        work = self.folder / audiobook.WORK_DIR / 'abcdef12'
        with mock.patch.object(book_video, 'render_chapter', wraps=book_video.render_chapter) as drawn:
            def stop(_fraction):
                if drawn.call_count >= 2:     # ikinci bolum cizilirken durur
                    cancel.set()
            with self.assertRaises(audiobook.Stopped):
                audiobook.build(self.engines, chapters, target, 'mp4', 'Kitap', '', None, 1.0, 'abcdef12', video=video,
                                override=voice, cancel=cancel, video_progress=stop)
            self.assertEqual(len(list(work.glob('*-v*.mp4'))), 1)
            drawn.reset_mock()
            audiobook.build(self.engines, chapters, target, 'mp4', 'Kitap', '', None, 1.0, 'abcdef12', video=video,
                            override=voice)
            self.assertEqual(drawn.call_count, 1)

    def _video(self, seconds=6):
        video = self.folder / 'film.mkv'
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=black:s=160x90:d={seconds}',
                        '-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}', '-shortest',
                        '-c:v', 'libx264', '-c:a', 'aac', str(video)], check=True)
        return video

    def test_dub_adds_default_turkish_track(self):
        video = self._video()
        segments = [{'start': 0.5, 'end': 1.5, 'text': 'Kısa.'},
                    {'start': 1.6, 'end': 2.0, 'text': 'Bu satır yerine sığmayacak kadar uzun.'},
                    {'start': 4.0, 'end': 5.0, 'text': 'Son.'}]
        output = self.folder / 'film.dublaj.mkv'
        result = dub.build(self.engines, video, segments, output, {'max_tempo': 1.5}, duration=6, has_audio=True)
        self.assertEqual(result['lines'], 3)
        self.assertEqual(result['faster'], 1)
        audio = [s for s in probe(output)['streams'] if s['codec_type'] == 'audio']
        self.assertEqual(len(audio), 2)
        self.assertEqual(audio[0]['tags'].get('language'), 'tur')
        self.assertEqual(audio[0]['disposition']['default'], 1)
        self.assertEqual(audio[1]['disposition']['default'], 0)
        self.assertTrue(video.exists())

    def test_dub_of_audio_file_writes_m4a_even_if_mkv_asked(self):
        source = self.folder / 'podcast.mp3'
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
                        '-c:a', 'libmp3lame', str(source)], check=True)
        output = self.folder / 'podcast.dublaj.m4a'
        dub.build(self.engines, source, [{'start': 0.5, 'end': 1.5, 'text': 'Merhaba.'}], output,
                  {'format': 'mkv'}, duration=3, has_audio=True)
        streams = probe(output)['streams']
        self.assertEqual([s['codec_type'] for s in streams], ['audio'])
        self.assertEqual(streams[0]['codec_name'], 'aac')

    def test_dub_with_speed_capable_engine_rerenders_faster(self):
        video = self._video(3)
        segments = [{'start': 0.2, 'end': 0.6, 'text': 'Oldukça uzun bir cümle burada.'}]
        dub.build(self.engines, video, segments, self.folder / 'o.m4a', {'format': 'm4a', 'max_tempo': 1.3},
                  has_audio=True, can_speed=True)
        self.assertEqual([speed for _, speed in self.engines.calls], [1.0, 1.3])

    def test_dub_overlap_keeps_timestamps_without_speeding(self):
        video = self._video(4)
        segments = [{'start': 0.2, 'end': 0.6, 'text': 'Oldukça uzun bir cümle burada.'},
                    {'start': 0.8, 'end': 1.2, 'text': 'İkinci.'}]
        result = dub.build(self.engines, video, segments, self.folder / 'u.m4a',
                           {'format': 'm4a', 'overlap': True, 'normalize': True}, has_audio=True, can_speed=True)
        self.assertEqual((result['faster'], result['shifted'], result['overlapped']), (0, 0, 1))
        self.assertEqual([speed for _, speed in self.engines.calls], [1.0, 1.0])

    def test_dub_cancel(self):
        video = self._video(2)
        with self.assertRaises(GracefulStop):
            dub.build(self.engines, video, [{'start': 0, 'end': 1, 'text': 'a'}], self.folder / 'x.mkv',
                      cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
