import base64
import io
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import text_speech  # noqa: E402
from tts import Cancelled  # noqa: E402

RATE = 1000


def clip(frames):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b'\x01\x00' * frames)
    return base64.b64encode(buffer.getvalue()).decode('ascii')


class FakeEngines:
    def __init__(self, cancel=None):
        self.calls = []
        self.cancel = cancel

    def say(self, text, speed=1.0, book=None, language='tr', override=None, tag=None):
        self.calls.append((text, speed, book, override))
        if self.cancel is not None:
            self.cancel.set()
        return {'audio': clip(100), 'duration': 0.1}


class TextSpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_clean_skips_empty_and_clamps_gaps(self):
        pairs = text_speech.clean(['  Bir.  ', '', 'İki  cümle.', 'Üç.'], [0.4, 9, 'x', 50])
        self.assertEqual(pairs, [('Bir.', 0.4), ('İki cümle.', None), ('Üç.', 10.0)])

    def test_group_joins_within_limit_and_respects_breaks(self):
        pairs = [('Bir.', 0.1), ('İki.', 0.2), ('Üç.', 0.8), ('Dört.', 0.3)]
        self.assertEqual(text_speech.group(pairs, 0), [(['Bir.'], 0.1), (['İki.'], 0.2), (['Üç.'], 0.8), (['Dört.'], 0.3)])
        self.assertEqual(text_speech.group(pairs, 100, breaks=[2]), [(['Bir.', 'İki.', 'Üç.'], 0.8), (['Dört.'], 0.3)])
        self.assertEqual(text_speech.group(pairs, 9), [(['Bir.', 'İki.'], 0.2), (['Üç.', 'Dört.'], 0.3)])

    def test_output_path_does_not_overwrite(self):
        first = text_speech.output_path(self.folder, 'Ses: deneme?', '', 'mp3')
        self.assertEqual(first.name, 'Ses deneme.mp3')
        first.write_bytes(b'')
        self.assertEqual(text_speech.output_path(self.folder, 'Ses: deneme?', '', 'mp3').name, 'Ses deneme (2).mp3')
        self.assertEqual(text_speech.output_path(self.folder, '', 'Merhaba dünya, nasılsın?', 'ogg').name,
                         'Merhaba dünya, nasılsın.wav')

    def test_write_wav_with_gaps(self):
        engines = FakeEngines()
        target = self.folder / 'cikti.wav'
        seen = []
        seconds = text_speech.write(engines, [(['Bir.', 'İki.'], 0.5), (['Üç.'], None)], 1.25, target,
                                    override={'voice': 'a/b'}, progress=lambda d, t: seen.append((d, t)), gap=0.2)
        self.assertEqual(engines.calls, [(['Bir.', 'İki.'], 1.25, None, {'voice': 'a/b'}), ('Üç.', 1.25, None, {'voice': 'a/b'})])
        self.assertEqual(seen, [(2, 3), (3, 3)])
        with wave.open(str(target)) as result:
            self.assertEqual(result.getnframes(), 100 + 500 + 100 + 200)
        self.assertAlmostEqual(seconds, 0.9)
        self.assertEqual([p.name for p in self.folder.iterdir()], ['cikti.wav'])

    def test_write_mp3_encodes_with_ffmpeg(self):
        target = self.folder / 'cikti.mp3'
        with mock.patch.object(text_speech.audiobook, '_run') as run, \
                mock.patch.object(text_speech.audiobook.media, 'ffmpeg_path', return_value='ffmpeg'):
            text_speech.write(FakeEngines(), [(['Bir.'], 0.1)], 1.0, target)
        command = run.call_args[0][0]
        self.assertIn('libmp3lame', command)
        self.assertEqual(command[-1], str(target))
        self.assertEqual(list(self.folder.iterdir()), [])   # gecici WAV silinir

    def test_cancel_removes_partial(self):
        cancel = threading.Event()
        with self.assertRaises(Cancelled):
            text_speech.write(FakeEngines(cancel), [(['Bir.'], 0.1), (['İki.'], 0.1)], 1.0, self.folder / 'x.wav',
                              cancel=cancel)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_read_text(self):
        path = self.folder / 'metin.txt'
        path.write_bytes('Çağrı geldi.'.encode('cp1254'))
        self.assertEqual(text_speech.read_text(path), 'Çağrı geldi.')
        path.write_bytes('﻿Şimdi.'.encode('utf-8'))
        self.assertEqual(text_speech.read_text(path), 'Şimdi.')
        with self.assertRaises(ValueError):
            text_speech.read_text(self.folder / 'resim.png')



class BridgeSpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for target in ('bridge.APP_DIR', 'bridge_tts.APP_DIR'):
            patcher = mock.patch(target, self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        import bridge
        self.events = []
        self.bridge = bridge.Bridge(emit=lambda name, data: self.events.append((name, data)))
        self.out = self.root / 'cikti'
        self.out.mkdir()

    def test_rejects_missing_folder_and_text(self):
        self.assertIn('klasör', self.bridge.tts_speech_create(['Bir.'], folder=str(self.root / 'yok'))['error'])
        self.assertIn('metin', self.bridge.tts_speech_create(['  '], folder=str(self.out))['error'])
        self.assertIn('bulunamadı', self.bridge.tts_speech_create(['Bir.'], voice='preset:yok', folder=str(self.out))['error'])

    def test_writes_file_with_chosen_voice(self):
        engines = FakeEngines()
        engines.group_chars = lambda language, override=None: 0
        with mock.patch.object(self.bridge, '_engines', return_value=engines),                 mock.patch.object(self.bridge, '_load_and_wait', return_value=None) as load,                 mock.patch.object(self.bridge, '_voice_specs', return_value={'ema/def': {'language': 'tr'}}):
            result = self.bridge.tts_speech_create(['Bir.', '', 'İki.'], [0.1, 0, 0.2], [2], 'ema/def', str(self.out),
                                                   'Deneme', 1.1, 'wav')
            self.assertTrue(result['started'], result)
            self.bridge._speech_job.join(5)
        self.assertEqual(load.call_args[0][:2], ('tr', {'voice': 'ema/def', 'options': None}))
        self.assertEqual([c[0] for c in engines.calls], ['Bir.', 'İki.'])
        finished = [data for name, data in self.events if name == 'tts_speech' and data.get('finished')]
        self.assertEqual(finished[0]['path'], str(self.out / 'Deneme.wav'), finished)
        self.assertTrue((self.out / 'Deneme.wav').is_file())

if __name__ == '__main__':
    unittest.main()
