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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import audiobook  # noqa: E402
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

    def choice(self, language, override=None):
        return ('sahte', (override or {}).get('voice', 'sahte/ses').split('/')[1])

    def _voice_options(self, engine_id, voice_id, override=None):
        return {}

    def say(self, text, speed=1.0, book=None, language='tr', override=None):
        self.calls.append((text, speed))
        data = tone(len(text) * 0.05 / speed)
        return {'audio': base64.b64encode(data).decode('ascii'), 'duration': len(text) * 0.05 / speed}

    def export(self, sentences, speed, path, progress=None, book=None, language='tr', gaps=None,
               override=None, cancel=None):
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(RATE)
            for index, text in enumerate(sentences):
                if cancel is not None and cancel.is_set():
                    raise Cancelled('Ses kaydı durduruldu.')
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
            {'title': '', 'sentences': ['Bir.', '  ', 'İki.'], 'gaps': [0.5, 0.1, 0.9]},
            {'title': 'Boş', 'sentences': ['   ']},
            {'title': '  Son   bölüm ', 'sentences': ['Üç.']},
        ])
        self.assertEqual([c['title'] for c in chapters], ['Bölüm 1', 'Son bölüm'])
        self.assertEqual(chapters[0]['sentences'], ['Bir.', 'İki.'])
        self.assertEqual(chapters[0]['gaps'], [0.5, 0.9])
        self.assertEqual(chapters[1]['gaps'], [None])

    def test_ffmetadata_chapters_are_contiguous_and_escaped(self):
        text = audiobook.ffmetadata('Kitap=1; #2', 'Yazar', [('A', 1.5), ('B\\C', 2.25)])
        self.assertIn('title=Kitap\\=1\\; \\#2', text)
        self.assertIn('START=0\nEND=1500\ntitle=A', text)
        self.assertIn('START=1500\nEND=3750\ntitle=B\\\\C', text)
        self.assertTrue(text.startswith(';FFMETADATA1\n'))

    def test_concat_list_escapes_quotes(self):
        line = audiobook.concat_list([Path("C:/a/it's.m4a")])
        self.assertIn("it'\\''s.m4a", line)

    def test_safe_name(self):
        self.assertEqual(audiobook.safe_name('Ana: Bir/İki?'), 'Ana Bir İki')
        self.assertEqual(audiobook.safe_name(' .. '), 'kitap')


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

    def test_mix_command_keeps_original_tracks_and_marks_dub_default(self):
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
