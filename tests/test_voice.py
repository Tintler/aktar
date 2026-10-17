"""Sesle soru sorma (F112) testleri: kayit dogrulama, Whisper'a verme, kopru ve mikrofon izni.
faster-whisper, mikrofon ya da pywebview gerektirmez."""
from __future__ import annotations

import base64
import io
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import bridge  # noqa: E402
import bridge_voice  # noqa: E402
import mic_permission  # noqa: E402
import qa  # noqa: E402
import speech  # noqa: E402


def wav_bytes(seconds=1.0, rate=16000, channels=1, width=2):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(width)
        stream.setframerate(rate)
        stream.writeframes(b'\x00' * width * channels * int(rate * seconds))
    return buffer.getvalue()


class ClipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'clip.wav'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, data):
        self.path.write_bytes(data)
        return self.path

    def test_check_clip_accepts_16k_mono_and_returns_seconds(self):
        self.assertAlmostEqual(speech.check_clip(self.write(wav_bytes(2.5))), 2.5)

    def test_check_clip_rejects_bad_recordings(self):
        for data, message in ((wav_bytes(1, rate=44100), '16 kHz'), (wav_bytes(1, channels=2), '16 kHz'),
                              (wav_bytes(0.1), 'kısa'), (b'not a wav file at all', 'okunamadı')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                speech.check_clip(self.write(data))
        with self.assertRaisesRegex(ValueError, 'en fazla 2 saniye'):
            speech.check_clip(self.write(wav_bytes(8)), max_seconds=2)

    def test_transcribe_clip_joins_segments_and_never_caches(self):
        segments = [{'start': 0, 'end': 1, 'text': ' Bu videoda '}, {'start': 1, 'end': 2, 'text': 'ne  anlatılıyor?'}]
        calls = []

        def runner(audio, model, device, language, **kwargs):
            calls.append((Path(audio), model, device, language, kwargs['cuda_dir']))
            return {'segments': segments, 'language': 'tr', 'duration': 2.0, 'device': 'cpu'}

        with mock.patch.object(speech, 'backend', return_value='inprocess'), \
                mock.patch.object(speech, 'run_whisper', side_effect=runner), \
                mock.patch.object(speech, 'save_json') as save:
            result = speech.transcribe_clip(self.write(wav_bytes()), 'small', 'cpu', cuda_dir='C:/cuda')
        self.assertEqual(result, {'text': 'Bu videoda ne anlatılıyor?', 'language': 'tr', 'device': 'cpu'})
        self.assertEqual(calls, [(self.path, 'small', 'cpu', '', 'C:/cuda')])
        save.assert_not_called()

    def test_transcribe_clip_uses_helper_package_when_frozen(self):
        with mock.patch.object(speech, 'backend', return_value='helper'), \
                mock.patch.object(speech, '_run_helper', return_value={'segments': [{'text': 'merhaba'}],
                                                                        'language': 'tr', 'device': 'cuda'}) as helper:
            self.assertEqual(speech.transcribe_clip(self.write(wav_bytes()))['text'], 'merhaba')
        helper.assert_called_once()

    def test_transcribe_clip_reports_silence_and_missing_whisper(self):
        with mock.patch.object(speech, 'backend', return_value='inprocess'), \
                mock.patch.object(speech, 'run_whisper', return_value={'segments': [], 'language': ''}), \
                self.assertRaisesRegex(ValueError, 'konuşma algılanmadı'):
            speech.transcribe_clip(self.write(wav_bytes()))
        with mock.patch.object(speech, 'backend', return_value=None), \
                self.assertRaisesRegex(RuntimeError, 'Whisper|faster-whisper'):
            speech.transcribe_clip(self.write(wav_bytes()))


class Voice(bridge_voice.VoiceMixin):
    def __init__(self):
        self.logs = []

    def _log(self, message):
        self.logs.append(message)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.voice = Voice()
        patcher = mock.patch.object(qa, 'work_dir', return_value=self.work)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_bridge_exposes_voice_methods(self):
        self.assertTrue(issubclass(bridge.Bridge, bridge_voice.VoiceMixin))

    def test_status_reports_whisper_hint(self):
        with mock.patch.object(speech, 'available', return_value=(False, 'Whisper paketi bulunamadı.')):
            self.assertEqual(self.voice.voice_status(),
                             {'available': False, 'hint': 'Whisper paketi bulunamadı.', 'max_seconds': 120})

    def test_transcribe_writes_temp_wav_and_deletes_it(self):
        seen = {}

        def fake(path, model, device, log=None, cuda_dir=''):
            seen.update(path=Path(path), exists=Path(path).exists(), model=model, device=device,
                        data=Path(path).read_bytes())
            return {'text': 'Özetle', 'language': 'tr', 'device': 'cpu'}

        data = wav_bytes()
        cfg = {'whisper_model': 'base', 'whisper_device': 'cpu', 'whisper_cuda_dir': '', 'whisper_language': 'en'}
        with mock.patch.object(speech, 'transcribe_clip', side_effect=fake), \
                mock.patch.object(bridge_voice, 'load_config', return_value=cfg):
            result = self.voice.voice_transcribe(base64.b64encode(data).decode())
        self.assertEqual(result, {'text': 'Özetle', 'language': 'tr'})
        self.assertTrue(seen['exists'])
        self.assertEqual(seen['data'], data)
        self.assertEqual((seen['model'], seen['device']), ('base', 'cpu'))
        self.assertEqual(seen['path'].parent, self.work / 'qa')
        self.assertFalse(seen['path'].exists())

    def test_errors_come_back_as_messages_and_file_is_removed(self):
        cfg = {'whisper_model': 'base', 'whisper_device': 'cpu'}
        with mock.patch.object(speech, 'transcribe_clip', side_effect=ValueError('Kayıtta konuşma algılanmadı.')), \
                mock.patch.object(bridge_voice, 'load_config', return_value=cfg):
            result = self.voice.voice_transcribe(base64.b64encode(wav_bytes()).decode())
        self.assertEqual(result, {'error': 'Kayıtta konuşma algılanmadı.'})
        self.assertEqual(list((self.work / 'qa').iterdir()), [])
        # kilit birakildi: sonraki kayit cozulebilir
        self.assertTrue(self.voice._voice_lock.acquire(blocking=False))
        self.voice._voice_lock.release()

    def test_bad_or_oversized_payload_is_rejected_before_whisper(self):
        with mock.patch.object(speech, 'transcribe_clip') as clip:
            self.assertIn('bozuk', self.voice.voice_transcribe('%%% not base64')['error'])
            self.assertIn('boş', self.voice.voice_transcribe('')['error'])
            with mock.patch.object(bridge_voice, 'MAX_CLIP_BYTES', 10):
                self.assertIn('uzun', self.voice.voice_transcribe(base64.b64encode(wav_bytes()).decode())['error'])
        clip.assert_not_called()

    def test_only_one_clip_at_a_time(self):
        self.voice._voice_lock.acquire()
        try:
            self.assertIn('hâlâ', self.voice.voice_transcribe(base64.b64encode(wav_bytes()).decode())['error'])
        finally:
            self.voice._voice_lock.release()


class PermissionTests(unittest.TestCase):
    def test_only_local_app_pages_get_the_microphone(self):
        for uri in ('http://127.0.0.1:52341/index.html', 'http://localhost:5173/', 'https://localhost/x'):
            self.assertTrue(mic_permission.is_app_origin(uri), uri)
        for uri in ('https://example.com/', 'http://127.0.0.1.evil.com/', 'file:///C:/x.html', '', None,
                    'http://localhost.example.com/'):
            self.assertFalse(mic_permission.is_app_origin(uri), uri)

    def test_failure_to_hook_permissions_is_only_logged(self):
        logs = []
        window = types.SimpleNamespace(native=None, uid='master')
        with mock.patch.object(mic_permission, '_allow_webview2', side_effect=RuntimeError('yok')), \
                mock.patch.object(mic_permission, '_allow_webkit', side_effect=RuntimeError('yok')):
            mic_permission.allow_microphone(window, log=logs.append)
        self.assertEqual(len(logs), 1)
        self.assertIn('Mikrofon izni ayarlanamadı', logs[0])
        self.assertFalse(getattr(window, '_aktar_mic', False))

    def test_hook_is_installed_once(self):
        window = types.SimpleNamespace(native=None, uid='master')
        name = '_allow_webview2' if mic_permission.os.name == 'nt' else '_allow_webkit'
        with mock.patch.object(mic_permission, name) as hook:
            mic_permission.allow_microphone(window)
            mic_permission.allow_microphone(window)
        hook.assert_called_once_with(window)


if __name__ == '__main__':
    unittest.main()
