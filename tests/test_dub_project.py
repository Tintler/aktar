"""Dublaj duzenleyicisi (dub_project.py, F175): proje kaydi, satir sesleri, elle tasima ve kisma, disa aktarma
(ses motoru yerine sahte motor; disa aktarma gercek FFmpeg ister, yoksa atlanir)."""
from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import dub  # noqa: E402
import dub_project  # noqa: E402
import media  # noqa: E402
from app_core import GracefulStop  # noqa: E402

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
    """Her karakter 0,02 sn ses; cagrilar (metin, hiz, onbellek kitabi, etiket) olarak kaydedilir."""

    def __init__(self):
        self.calls = []

    def say(self, text, speed=1.0, book=None, language='tr', override=None, tag=None):
        self.calls.append((text, speed, book, tag))
        data = tone(len(text) * 0.02 / speed)
        return {'audio': base64.b64encode(data).decode('ascii'), 'duration': len(text) * 0.02 / speed}


LINES = [{'start': 1.0, 'end': 3.0, 'text': 'Merhaba.', 'tag': '[laughs]'},
         {'start': 3.5, 'end': 5.0, 'text': 'Nasılsın?'},
         {'start': 8.0, 'end': 9.0, 'text': 'İyiyim.'}]


class DubProjectTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='aktar-dub-project-test-'))
        patcher = mock.patch('qa.work_dir', return_value=self.folder / 'work')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.video = self.folder / 'film.mkv'
        self.engines = FakeEngines()

    def _create(self, **options):
        return dub_project.create(self.video, 'whisper', 'Whisper', [dict(line) for line in LINES],
                                  options=dict({'max_tempo': 1}, **options), voices=[None, 'preset:b', None])

    def test_create_and_load(self):
        project = self._create()
        self.assertEqual([line['id'] for line in project['lines']], [1, 2, 3])
        self.assertEqual(project['lines'][1]['voice'], 'preset:b')
        self.assertEqual(project['lines'][0]['tag'], '[laughs]')
        self.assertIsNone(project['ducks'])
        self.assertEqual(dub_project.load(self.video)['next_id'], 4)

    def test_generate_writes_clips_and_save_keeps_them(self):
        self._create()
        seen = []
        result = dub_project.generate(self.engines, self.video, on_line=seen.append)
        self.assertEqual(result['done'], 3)
        self.assertEqual([line['id'] for line in seen], [1, 3, 2])   # ses basina bir motor yuklemesi
        # etiket iletilir, ilk uretim motor onbellegini kullanir
        self.assertEqual(self.engines.calls[0][3], '[laughs]')
        self.assertEqual(self.engines.calls[0][2], dub.cache_id(self.video))
        view = dub_project.view(self.video, dub_project.load(self.video))
        self.assertTrue(all(line['ready'] and not line['stale'] for line in view['lines']))
        # arayuz ses alanlari olmadan kaydeder: sesler korunur; metni degisen satir eski sayilir
        edited = [{k: v for k, v in line.items() if k not in dub_project.AUDIO_KEYS} for line in view['lines']]
        edited[1]['text'] = 'Nasılsın bakalım?'
        saved = dub_project.view(self.video, dub_project.save(self.video, {'lines': edited}))
        self.assertEqual([line['stale'] for line in saved['lines']], [False, True, False])
        self.assertEqual(dub_project.pending(dub_project.load(self.video)), [2])

    def test_regenerate_makes_new_take_without_cache(self):
        self._create()
        dub_project.generate(self.engines, self.video)
        before = dub_project.load(self.video)['lines'][0]['audio']
        dub_project.generate(self.engines, self.video, ids=[1], fresh=True)
        line = dub_project.load(self.video)['lines'][0]
        self.assertNotEqual(line['audio'], before)
        self.assertIsNone(self.engines.calls[-1][2])   # onbellek kullanilmadi
        files = sorted(p.name for p in (dub_project.folder(self.video) / dub_project.LINES_DIR).glob('*.wav'))
        self.assertEqual(len(files), 3)   # eski deneme silindi

    def test_split_and_delete_lines(self):
        project = self._create()
        dub_project.generate(self.engines, self.video)
        lines = [dict(line) for line in dub_project.load(self.video)['lines']]
        first = lines[0]
        # bolme: ilk parca kimligini korur (sesi eski olur), ikinci parca yeni kimlik alir; ucuncu satir silinir
        halves = [dict(first, end=2.0, text='Mer-'), {'start': 2.0, 'end': 3.0, 'text': 'haba.'}]
        saved = dub_project.save(self.video, {'lines': halves + [lines[1]]})
        self.assertEqual([line['id'] for line in saved['lines']], [1, 4, 2])
        self.assertEqual(saved['next_id'], 5)
        self.assertIsNone(saved['lines'][1].get('audio'))
        self.assertEqual(dub_project.pending(saved), [1, 4])
        left = list((dub_project.folder(self.video) / dub_project.LINES_DIR).glob('3-*.wav'))
        self.assertEqual(left, [])
        self.assertTrue(project)

    def test_placements_respect_manual_position_and_chain(self):
        lines = [{'start': 0.0, 'at': None}, {'start': 1.0, 'at': None}, {'start': 2.0, 'at': 10.0},
                 {'start': 3.0, 'at': None}]
        self.assertEqual(dub_project.placements(lines, [1.5, 1.0, 1.0, 1.0]), [0.0, 1.5, 10.0, 11.0])
        self.assertEqual(dub_project.placements(lines, [1.5, 1.0, 1.0, 1.0], overlap=True), [0.0, 1.0, 10.0, 3.0])

    def test_clean_values(self):
        line = dub_project.clean_line({'start': '2', 'end': 1, 'text': '  a  b ', 'gain': 9, 'at': 'x'}, 7)
        self.assertEqual((line['id'], line['end'], line['text'], line['gain'], line['at']), (7, 2.05, 'a b', 4.0, None))
        self.assertIsNone(dub_project.clean_line({'start': 1, 'end': 2, 'text': ' '}, 1))
        ducks = dub_project.clean_ducks([{'start': 5, 'end': 6, 'level': 2}, {'start': 1, 'end': 1.01}])
        self.assertEqual(ducks, [{'start': 5.0, 'end': 6.0, 'level': 1.0}])

    def test_duck_commands_use_span_level(self):
        text = dub.duck_commands([(2.0, 4.0, 0.0), (6.0, 7.0)], 0.5, fade=0.5, steps=1)
        self.assertIn('1.500 volume@duck volume 0.0000;', text)
        self.assertIn('5.500 volume@duck volume 0.5000;', text)

    def test_generate_cancel(self):
        self._create()
        with self.assertRaises(GracefulStop):
            dub_project.generate(self.engines, self.video, cancelled=lambda: True)

    @unittest.skipUnless(FFMPEG, 'FFmpeg yok')
    def test_export_writes_dub_with_manual_ducks(self):
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=160x90:d=10',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=10', '-shortest',
                        '-c:v', 'libx264', '-c:a', 'aac', str(self.video)], check=True)
        self._create()
        dub_project.generate(self.engines, self.video, ids=[1, 2])
        lines = dub_project.load(self.video)['lines']
        lines[1]['at'] = 6.0
        lines[0]['gain'] = 0.5
        dub_project.save(self.video, {'lines': lines, 'ducks': [{'start': 0.5, 'end': 7.5, 'level': 0.1}]})
        output = self.folder / 'film.dublaj.mkv'
        result = dub_project.export(self.video, output, 10, True)
        self.assertEqual((result['lines'], result['missing'], result['moved']), (2, 1, 1))
        streams = json.loads(subprocess.run([FFPROBE, '-v', 'error', '-show_streams', '-of', 'json', str(output)],
                                            capture_output=True, text=True, encoding='utf-8').stdout)['streams']
        audio = [s for s in streams if s['codec_type'] == 'audio']
        self.assertEqual(len(audio), 2)
        self.assertEqual(audio[0]['disposition']['default'], 1)


if __name__ == '__main__':
    unittest.main()
