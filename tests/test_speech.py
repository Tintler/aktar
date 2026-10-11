"""Konusmadan metin (F48) testleri. faster-whisper/GPU gerektirmez (sahte model)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_core
import media
import qa
import speech


class FakeWord:
    def __init__(self, start, end, word):
        self.start, self.end, self.word = start, end, word


class FakeSegment:
    def __init__(self, start, end, text, words):
        self.start, self.end, self.text, self.words = start, end, text, words


def fake_whisper_module(fail_devices=(), calls=None):
    """faster_whisper yerine: cihaz listesinde olan cihazda calisma aninda hata verir."""
    calls = calls if calls is not None else []

    class WhisperModel:
        def __init__(self, name, device, compute_type, download_root):
            calls.append((name, device, compute_type, download_root))
            self.device = device

        def transcribe(self, audio, **kwargs):
            calls.append(('transcribe', len(audio), kwargs.get('language'),
                          kwargs.get('word_timestamps')))
            if self.device in fail_devices:
                raise RuntimeError('Library cublas64_12.dll is not found')
            segments = [
                FakeSegment(0.0, 2.3, ' Welcome to the review.',
                            [FakeWord(0.0, 0.5, ' Welcome'), FakeWord(0.5, 0.8, ' to'),
                             FakeWord(0.8, 1.2, ' the'), FakeWord(1.2, 2.3, ' review.')]),
                FakeSegment(3.0, 5.5, ' The card is fast.', []),
            ]
            return iter(segments), types.SimpleNamespace(duration=27.0, language='en')

    return types.SimpleNamespace(WhisperModel=WhisperModel), calls


def write_wav(path, seconds=1):
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\x00\x10' * 16000 * seconds)


class HelperTests(unittest.TestCase):
    def test_regroup_words_splits_on_sentence_and_limits(self):
        words = [(0.0, 0.4, ' Hello'), (0.4, 0.8, ' there,'), (0.8, 1.5, ' this is a test.'),
                 (2.0, 2.4, ' Next'), (2.4, 9.5, ' part')]
        cues = speech.regroup_words(words)
        self.assertEqual([cue['text'] for cue in cues],
                         ['Hello there, this is a test.', 'Next', 'part'])
        self.assertEqual((cues[0]['start'], cues[0]['end']), (0.0, 1.5))
        long_words = [(index * 0.3, index * 0.3 + 0.2, 'word') for index in range(40)]
        for cue in speech.regroup_words(long_words):
            self.assertLessEqual(len(cue['text']), speech.CUE_CHARS)
            self.assertLessEqual(cue['end'] - cue['start'], speech.CUE_SECONDS)

    def test_sentence_final_word_is_not_orphaned(self):
        words = [(18.88, 19.5, 'Our recommendation, if you play at 1440p,'),
                 (19.5, 24.8, 'this is the best value card right'), (24.8, 25.08, 'now.')]
        self.assertEqual([cue['text'] for cue in speech.regroup_words(words)],
                         ['Our recommendation, if you play at 1440p, this is the best value '
                          'card right now.'])

    def test_short_sentence_end_does_not_split(self):
        cues = speech.regroup_words([(0, 0.5, 'Mr.'), (0.5, 1.0, 'Smith'), (1.0, 2.0, 'arrived.')])
        self.assertEqual([cue['text'] for cue in cues], ['Mr. Smith arrived.'])

    def test_wrap_lines_balances_two_lines(self):
        self.assertEqual(speech.wrap_lines('kısa metin'), 'kısa metin')
        text = 'Our recommendation, if you play at 1440p, this is the best value card.'
        top, bottom = speech.wrap_lines(text).split('\n')
        self.assertLess(abs(len(top) - len(bottom)), 12)
        shown = speech.display_segments([{'start': 0, 'end': 1, 'text': text}])
        self.assertIn('\n', shown[0]['text'])

    def test_device_plan(self):
        self.assertEqual(speech._device_plan('cpu'), [('cpu', 'int8')])
        self.assertEqual(speech._device_plan('cuda'), [('cuda', 'float16')])
        fake = types.SimpleNamespace(get_cuda_device_count=lambda: 1)
        with mock.patch.dict(sys.modules, {'ctranslate2': fake}):
            self.assertEqual(speech._device_plan('auto'), [('cuda', 'float16'), ('cpu', 'int8')])
        fake = types.SimpleNamespace(get_cuda_device_count=lambda: 0)
        with mock.patch.dict(sys.modules, {'ctranslate2': fake}):
            self.assertEqual(speech._device_plan('auto'), [('cpu', 'int8')])

    def test_cuda_dirs_found_inside_frozen_helper(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('cublas', 'cudnn'):
                (Path(folder) / 'nvidia' / name / 'bin').mkdir(parents=True)
            with mock.patch.object(sys, '_MEIPASS', folder, create=True),                     mock.patch.dict(sys.modules, {'nvidia.cublas': None, 'nvidia.cudnn': None}):
                found = speech._cuda_dll_dirs()
        self.assertEqual([item.parent.name for item in found], ['cublas', 'cudnn'])

    def test_available_reports_install_hint(self):
        with mock.patch.dict(sys.modules, {'faster_whisper': None}):
            ok, message = speech.available()
        self.assertFalse(ok)
        self.assertIn('requirements-whisper.txt', message)

    def test_frozen_exe_uses_helper_package_or_explains_it(self):
        with mock.patch.object(sys, 'frozen', True, create=True), \
                mock.patch.object(speech, 'helper_command', return_value=None):
            self.assertIsNone(speech.backend())
            ok, message = speech.available()
        self.assertFalse(ok)
        self.assertIn('aktar-whisper', message)
        self.assertIn('DERLE_WHISPER.cmd', message)
        with mock.patch.object(sys, 'frozen', True, create=True), \
                mock.patch.object(speech, 'helper_command', return_value=['x.exe']):
            self.assertEqual(speech.backend(), 'helper')
            self.assertEqual(speech.available(), (True, ''))
        derle = (Path(__file__).resolve().parent.parent / 'DERLE.cmd').read_text(encoding='utf-8')
        self.assertIn('--exclude-module faster_whisper', derle)

    def test_helper_is_looked_up_next_to_the_app(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(speech, 'APP_DIR', Path(folder)):
                self.assertIsNone(speech.helper_command())
                exe = Path(folder) / 'aktar-whisper' / 'aktar-whisper.exe'
                exe.parent.mkdir()
                exe.write_bytes(b'')
                self.assertEqual(speech.helper_command(), [str(exe)])

    def test_read_wav(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.wav'
            write_wav(path, 2)
            samples = speech.read_wav(path)
        self.assertEqual(len(samples), 32000)
        self.assertEqual(str(samples.dtype), 'float32')


class TranscribeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.base = Path(self.folder.name)
        self.video = self.base / 'speech.mkv'
        self.video.write_bytes(b'video')

    def tearDown(self):
        self.folder.cleanup()

    def extract(self, _video, output):
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        write_wav(output)
        return Path(output)

    def run_transcribe(self, module, device='auto', cuda=True, **kwargs):
        ctranslate2 = types.SimpleNamespace(get_cuda_device_count=lambda: 1 if cuda else 0)
        logs = []
        with mock.patch.dict(sys.modules, {'faster_whisper': module, 'ctranslate2': ctranslate2}), \
                mock.patch.object(speech, 'extract_audio', side_effect=self.extract):
            result = speech.transcribe(self.video, device=device, base=self.base,
                                       log=logs.append, **kwargs)
        return result, logs

    def test_gpu_failure_falls_back_to_cpu_and_caches(self):
        module, calls = fake_whisper_module(fail_devices=('cuda',))
        progress = []
        result, logs = self.run_transcribe(module, progress=lambda d, n: progress.append((d, n)))
        self.assertEqual(result['device'], 'cpu')
        self.assertEqual(result['language'], 'en')
        self.assertEqual([seg['text'] for seg in result['segments']],
                         ['Welcome to the review.', 'The card is fast.'])
        devices = [call[1] for call in calls if call[0] != 'transcribe']
        self.assertEqual(devices, ['cuda', 'cpu'])
        self.assertTrue(all(call[3] for call in calls if call[0] == 'transcribe'))
        self.assertTrue(any('cuda ile çalışamadı' in line for line in logs))
        self.assertEqual(progress[-1], (5, 27))
        self.assertFalse(list((self.base / 'qa').glob('*.wav')), 'gecici WAV silinmeli')
        # Ikinci cagri onbellekten: model hic yuklenmez.
        module2, calls2 = fake_whisper_module()
        again, logs = self.run_transcribe(module2)
        self.assertEqual(again['segments'], result['segments'])
        self.assertEqual(calls2, [])
        self.assertIsNotNone(speech.load_cached(self.video, base=self.base))

    def test_all_devices_failing_raises_meaningful_error(self):
        module, _calls = fake_whisper_module(fail_devices=('cuda', 'cpu'))
        with self.assertRaises(RuntimeError) as context:
            self.run_transcribe(module)
        self.assertIn('Konuşmadan metin başarısız', str(context.exception))

    def test_cancel_stops_transcription(self):
        module, _calls = fake_whisper_module()
        with self.assertRaises(app_core.GracefulStop):
            self.run_transcribe(module, device='cpu', cancelled=lambda: True)
        self.assertIsNone(speech.load_cached(self.video, base=self.base))

    def test_missing_dependency_raises_install_hint(self):
        with mock.patch.dict(sys.modules, {'faster_whisper': None}):
            with self.assertRaises(RuntimeError) as context:
                speech.transcribe(self.video, base=self.base, log=lambda _m: None)
        self.assertIn('faster-whisper kurulu değil', str(context.exception))

    def test_extract_audio_reports_missing_audio_stream(self):
        result = subprocess.CompletedProcess([], 1, stdout='',
                                             stderr='Stream map 0:a:0 matches no streams.')
        with mock.patch.object(media, '_run', return_value=result), \
                mock.patch.object(media, 'ffmpeg_path', return_value='ffmpeg'):
            with self.assertRaises(ValueError) as context:
                speech.extract_audio(self.video, self.base / 'a.wav')
        self.assertIn('ses akışı yok', str(context.exception))

    def test_whisper_session_uses_segments_as_transcript(self):
        result = {'segments': [{'start': 0.0, 'end': 2.0, 'text': 'Welcome.'},
                               {'start': 3.0, 'end': 5.0, 'text': 'Bye.'}],
                  'language': 'en', 'model': 'large-v3-turbo'}
        with mock.patch.object(media, 'video_info', return_value={'duration': 27.0, 'chapters': []}):
            data, path = qa.load_whisper_session(self.video, result, self.base, log=lambda _m: None)
            again, _ = qa.load_whisper_session(self.video, result, self.base, log=lambda _m: None)
        self.assertEqual(data['source'], {'kind': 'whisper', 'model': 'large-v3-turbo',
                                          'language': 'en'})
        self.assertEqual(again['segments'], data['segments'])
        self.assertTrue(path.exists())
        self.assertEqual(data['duration'], 27.0)


FAKE_HELPER = """
import json, sys, time
sys.stdout.reconfigure(encoding='utf-8')
args = sys.argv[1:]
mode = args[args.index('--model') + 1]
sys.stderr.write('indirme cubugu 100%\\n'); sys.stderr.flush()
def emit(**m):
    print(json.dumps(m, ensure_ascii=False), flush=True)
if mode == 'ok':
    emit(log='Whisper cpu yüklendi')
    emit(progress=[3, 27])
    emit(progress=[27, 27])
    emit(result={'segments': [{'start': 0.0, 'end': 2.0, 'text': 'Merhaba.'}],
                 'language': 'tr', 'duration': 27.0, 'device': 'cuda'})
elif mode == 'error':
    emit(error='CUDA hatası')
    sys.exit(1)
elif mode == 'crash':
    sys.stderr.write('Traceback: ImportError onnxruntime\\n'); sys.exit(3)
elif mode == 'slow':
    for index in range(1000):
        emit(progress=[index, 1000]); time.sleep(0.05)
"""


class HelperProtocolTests(unittest.TestCase):
    """F50: Aktar.exe -> ayri aktar-whisper paketi (alt surec, JSON satirlari)."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.base = Path(self.folder.name)
        self.video = self.base / 'film.mkv'
        self.video.write_bytes(b'video')
        self.script = self.base / 'fake_helper.py'
        self.script.write_text(FAKE_HELPER, encoding='utf-8')

    def tearDown(self):
        self.folder.cleanup()

    def extract(self, _video, output):
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        write_wav(output)
        return Path(output)

    def run_helper(self, model, **kwargs):
        logs, progress = [], []
        with mock.patch.object(speech, 'backend', return_value='helper'), \
                mock.patch.object(speech, 'helper_command',
                                  return_value=[sys.executable, str(self.script)]), \
                mock.patch.object(speech, 'extract_audio', side_effect=self.extract):
            result = speech.transcribe(self.video, model_name=model, base=self.base,
                                       log=logs.append,
                                       progress=lambda d, n: progress.append((d, n)), **kwargs)
        return result, logs, progress

    def test_helper_result_progress_and_logs(self):
        result, logs, progress = self.run_helper('ok')
        self.assertEqual(result['segments'], [{'start': 0.0, 'end': 2.0, 'text': 'Merhaba.'}])
        self.assertEqual((result['device'], result['model'], result['language']),
                         ('cuda', 'ok', 'tr'))
        self.assertEqual(progress, [(3, 27), (27, 27)])
        self.assertIn('Whisper cpu yüklendi', logs)
        self.assertFalse(list((self.base / 'qa').glob('*.wav')))
        self.assertFalse(list((self.base / 'qa').glob('*.log')))

    def test_helper_error_message_is_reported(self):
        with self.assertRaises(RuntimeError) as context:
            self.run_helper('error')
        self.assertIn('CUDA hatası', str(context.exception))

    def test_helper_crash_reports_stderr_tail(self):
        with self.assertRaises(RuntimeError) as context:
            self.run_helper('crash')
        self.assertIn('ImportError onnxruntime', str(context.exception))

    def test_cancel_kills_helper(self):
        calls = []

        def cancelled():
            calls.append(1)
            return len(calls) > 3

        with self.assertRaises(app_core.GracefulStop):
            self.run_helper('slow', cancelled=cancelled)
        self.assertLess(len(calls), 10)

    def test_cli_emits_json_lines(self):
        import io
        import json
        import whisper_cli
        out = io.StringIO()

        def fake_run(audio, model, device, language, progress, log, download_root):
            progress(5, 10)
            log('günlük')
            return {'segments': [], 'language': 'en', 'duration': 10.0, 'device': 'cpu'}

        with mock.patch.object(speech, 'run_whisper', side_effect=fake_run), \
                mock.patch.object(sys, 'stdout', out):
            code = whisper_cli.main(['a.wav', '--model', 'base', '--device', 'cpu'])
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual(lines, [{'progress': [5, 10]}, {'log': 'günlük'},
                                 {'result': {'segments': [], 'language': 'en',
                                             'duration': 10.0, 'device': 'cpu'}}])
        out = io.StringIO()
        with mock.patch.object(speech, 'run_whisper', side_effect=RuntimeError('bozuk')), \
                mock.patch.object(sys, 'stdout', out):
            self.assertEqual(whisper_cli.main(['a.wav']), 1)
        self.assertEqual(json.loads(out.getvalue()), {'error': 'bozuk'})


class ConfigTests(unittest.TestCase):
    def test_whisper_config_is_validated(self):
        cfg = dict(app_core.DEFAULT_CONFIG)
        self.assertEqual(cfg['whisper_model'], speech.DEFAULT_MODEL)
        app_core.validate_config(cfg)
        for key, value in (('whisper_device', 'gpu'), ('whisper_language', 'english'),
                           ('whisper_model', ' ')):
            with self.assertRaises(ValueError):
                app_core.validate_config(dict(cfg, **{key: value}))
        app_core.validate_config(dict(cfg, whisper_language='ja', whisper_device='cpu'))


if __name__ == '__main__':
    unittest.main()
