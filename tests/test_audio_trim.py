"""F173: ses onayarinda klon kaydindan aralik kesme (audio_trim.py + voice_presets.save 'trim')."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))

import base64
import io
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import audio_trim
import media
import voice_presets

try:
    FFMPEG = media.ffmpeg_path()
except RuntimeError:
    FFMPEG = None

VOICES = {'motor/clone': {'id': 'clone', 'options': [{'key': 'reference', 'type': 'file', 'label': 'Ses kaydı'},
                                                     {'key': 'reference_text', 'type': 'text'}]}}


def seconds_of(path):
    with wave.open(str(path)) as clip:
        return clip.getnframes() / clip.getframerate(), clip.getnchannels()


class SpanTests(unittest.TestCase):
    def test_span(self):
        self.assertEqual(audio_trim.span(-1, 5), (0.0, 5.0))
        self.assertEqual(audio_trim.span(2, 50, duration=30), (2.0, 30.0))
        with self.assertRaises(ValueError):
            audio_trim.span(3, 3.2)


@unittest.skipUnless(FFMPEG, 'FFmpeg yok')
class TrimTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='aktar-test-kes-'))
        self.addCleanup(shutil.rmtree, self.folder, True)
        patcher = patch.object(media, 'ffmpeg_path', return_value=FFMPEG)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = self.folder / 'uzun kayit.mp3'
        # 2 sn sessizlik + 6 sn ton: dalga bicimi basta bos, sonra dolu
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo:d=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=330:duration=6:sample_rate=44100',
                        '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1', str(self.source)], check=True)

    def test_peaks(self):
        info = audio_trim.peaks(self.source, 80)
        self.assertAlmostEqual(info['duration'], 8.0, delta=0.15)
        self.assertEqual(len(info['peaks']), 80)
        self.assertLess(max(info['peaks'][:15]), 0.05)
        self.assertGreater(min(info['peaks'][30:75]), 0.5)

    def test_clip_and_cut(self):
        with wave.open(io.BytesIO(base64.b64decode(audio_trim.clip_base64(self.source, 1.0, 4.0)))) as clip:
            self.assertEqual(clip.getframerate(), audio_trim.PREVIEW_RATE)
            self.assertAlmostEqual(clip.getnframes() / clip.getframerate(), 3.0, delta=0.05)
        target = audio_trim.cut(self.source, self.folder / 'kesik.wav', 2.5, 7.0)
        length, channels = seconds_of(target)
        self.assertAlmostEqual(length, 4.5, delta=0.05)
        self.assertEqual(channels, 1)
        audio_trim.cut(target, target, 0, 2.0)     # ayni dosyanin uzerine
        self.assertAlmostEqual(seconds_of(target)[0], 2.0, delta=0.05)
        self.assertFalse(list(self.folder.glob('*.part.wav')))

    def test_preset_saves_the_trimmed_wav(self):
        app = self.folder / 'app'
        saved = voice_presets.save(app, {'name': 'Ece', 'voice': 'motor/clone',
                                         'options': {'reference': str(self.source), 'reference_text': 'Merhaba.'},
                                         'trim': {'reference': {'start': 2.0, 'end': 5.0}}}, VOICES)
        recording = Path(saved['options']['reference'])
        self.assertEqual(recording.parent, voice_presets.folder(app))
        self.assertEqual(recording.name, f'{saved["id"]}-kayit.wav')
        self.assertAlmostEqual(seconds_of(recording)[0], 3.0, delta=0.05)
        self.assertTrue(self.source.exists())                  # ozgun dosyaya dokunulmaz
        # duzenlerken kayitli kaydi yeniden kesmek
        again = voice_presets.save(app, {'id': saved['id'], 'name': 'Ece', 'voice': 'motor/clone',
                                         'options': {'reference': str(recording)},
                                         'trim': {'reference': {'start': 0.5, 'end': 2.0}}}, VOICES)
        self.assertEqual(again['options']['reference'], str(recording))
        self.assertAlmostEqual(seconds_of(recording)[0], 1.5, delta=0.05)
        self.assertEqual([path.name for path in voice_presets.folder(app).glob('*-kayit.*')], [recording.name])

    def test_untrimmed_recording_is_copied_as_before(self):
        app = self.folder / 'app'
        saved = voice_presets.save(app, {'name': 'Ali', 'voice': 'motor/clone',
                                         'options': {'reference': str(self.source)}}, VOICES)
        self.assertTrue(saved['options']['reference'].endswith('-kayit.mp3'))


if __name__ == '__main__':
    unittest.main()
