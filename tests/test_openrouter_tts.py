import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))

import array
import base64
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import patch
import wave

import drama3
import drama3_tr
import openrouter_tts
from tts import Engines

REPO = Path(__file__).resolve().parents[1]
KEY = 'sk-or-deneme'


def pcm(seconds, rate=openrouter_tts.PCM_RATE):
    samples = array.array('h', ((8000 if (i // 110) % 2 else -8000) for i in range(int(rate * seconds))))
    return samples.tobytes()


class Response:
    def __init__(self, body, kind='audio/pcm'):
        self.stream, self.headers = io.BytesIO(body), {'Content-Type': kind}

    def read(self, amount=-1):
        return self.stream.read(amount)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def http_error(code, message='hata'):
    body = json.dumps({'error': {'code': code, 'message': message}}).encode('utf-8')
    return urllib.error.HTTPError('https://openrouter.ai', code, message, {}, io.BytesIO(body))


REFERENCE = {'audio': b'ID3mp3', 'format': 'mp3', 'text': 'Kaydın metni.'}


class SpeechTests(unittest.TestCase):
    def test_request_carries_reference_and_returns_wav(self):
        seen = []

        def fake(request, timeout):
            seen.append(request)
            return Response(pcm(1.0))

        with patch('urllib.request.urlopen', fake):
            data = openrouter_tts.speech('Merhaba dünya.', REFERENCE, {'temperature': 0.9, 'top_p': 0.9}, key=KEY)
        samples, rate = drama3.read_pcm(data)
        self.assertEqual((rate, len(samples)), (openrouter_tts.PCM_RATE, openrouter_tts.PCM_RATE))
        request = seen[0]
        self.assertEqual(request.full_url, openrouter_tts.API_URL + '/audio/speech')
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + KEY)
        body = json.loads(request.data.decode('utf-8'))
        self.assertEqual((body['model'], body['input'], body['response_format']),
                         ('fish-audio/drama-3', 'Merhaba dünya.', 'pcm'))
        audio, text = body['input_references']
        self.assertEqual(audio['type'], 'input_audio')
        self.assertEqual(audio['input_audio']['data'], 'data:audio/mpeg;base64,' + base64.b64encode(b'ID3mp3').decode())
        self.assertEqual(text, {'type': 'text', 'text': 'Kaydın metni.'})
        self.assertEqual(body['provider'], {'options': {'fish-audio': {'temperature': 0.9, 'top_p': 0.9}}})

    def test_rate_limit_is_retried(self):
        calls, waits = [], []

        def fake(request, timeout):
            calls.append(1)
            if len(calls) < 3:
                raise http_error(429 if len(calls) == 1 else 502)
            return Response(pcm(0.5))

        with patch('urllib.request.urlopen', fake):
            openrouter_tts.speech('Bir.', REFERENCE, key=KEY, sleep=waits.append)
        self.assertEqual((len(calls), waits), (3, list(openrouter_tts.RETRY_WAITS[:2])))

    def test_timeout_is_retried_and_logged(self):
        calls, lines = [], []

        def fake(request, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise TimeoutError('The read operation timed out')
            return Response(pcm(0.5))

        with patch('urllib.request.urlopen', fake):
            openrouter_tts.speech('Bir.', REFERENCE, key=KEY, sleep=lambda _s: None, log=lines.append)
        self.assertEqual(calls, [openrouter_tts.REQUEST_TIMEOUT] * 2)
        self.assertIn('yarım kaldı', lines[0])
        self.assertIn('4 karakter', lines[1])
        with patch('urllib.request.urlopen', side_effect=TimeoutError('zaman asimi')):
            with self.assertRaises(openrouter_tts.CloudError) as caught:
                openrouter_tts.speech('Bir.', REFERENCE, key=KEY, sleep=lambda _s: None)
        self.assertIn('denemede ses üretemedi', str(caught.exception))

    def test_endless_audio_is_cut_and_retried(self):
        # Drama 3 metni bitirince susmayabilir: ses akarak geldigi icin soket zaman asimi dolmaz
        calls, lines = [], []
        long = pcm(openrouter_tts.max_seconds('Bir.') + 5)

        def fake(request, timeout):
            calls.append(1)
            return Response(long if len(calls) == 1 else pcm(0.5))

        with patch('urllib.request.urlopen', fake):
            data = openrouter_tts.speech('Bir.', REFERENCE, key=KEY, sleep=lambda _s: None, log=lines.append)
        self.assertEqual(len(calls), 2)
        self.assertIn('uzun ses üretti', lines[0])
        self.assertLess(drama3.read_pcm(data)[0].__len__(), openrouter_tts.PCM_RATE)

    def test_slow_stream_is_cut(self):
        # 20. saniyede 1 sn ses: Fish'in yavas akisi, yeniden istemek beklemekten hizli
        second = openrouter_tts.PCM_RATE * 2
        chunks = iter([b'a' * second, b'b' * 10])
        response = Response(b'')
        response.read = lambda amount=-1: next(chunks, b'')
        ticks = iter([2, 20])
        with self.assertRaises(openrouter_tts.CloudError) as caught:
            openrouter_tts._read(response, 'Bir cümle.', 0, 90, lambda _m: None, clock=lambda: next(ticks))
        self.assertIn('yavaş geliyor', str(caught.exception))

    def test_slow_note_and_total_limit(self):
        ticks = iter([0, 5, 40, 95])
        lines = []
        response = Response(b'')
        size = openrouter_tts.PCM_RATE * 2 * 30         # akis gercek zamandan hizli: yavaslik kesmesi devreye girmez
        response.read = lambda amount=-1, chunks=iter([b'a' * size] * 4): next(chunks, b'')
        with self.assertRaises(openrouter_tts.CloudError) as caught:
            openrouter_tts._read(response, 'Bir ' * 200, 0, 90, lines.append, clock=lambda: next(ticks))
        self.assertIn('90 sn', str(caught.exception))
        self.assertEqual(len(lines), 1)
        self.assertIn('sürüyor', lines[0])

    def test_errors_are_explained(self):
        for code, words in ((401, 'anahtarı geçersiz'), (402, 'bakiyesi'), (400, 'HTTP 400')):
            with patch('urllib.request.urlopen', side_effect=http_error(code, 'ayrinti')):
                with self.assertRaises(drama3.ServerError) as caught:
                    openrouter_tts.speech('Bir.', REFERENCE, key=KEY, sleep=lambda _s: None)
            self.assertIn(words, str(caught.exception))
        with self.assertRaises(openrouter_tts.CloudError):
            with patch.object(openrouter_tts, 'api_key', return_value=''):
                openrouter_tts.speech('Bir.', REFERENCE)

    def test_json_body_instead_of_audio(self):
        body = json.dumps({'error': {'message': 'olmadi'}}).encode()
        with patch('urllib.request.urlopen', return_value=Response(body, 'application/json')):
            with self.assertRaises(openrouter_tts.CloudError) as caught:
                openrouter_tts.speech('Bir.', REFERENCE, key=KEY)
        self.assertIn('olmadi', str(caught.exception))

    def test_key_info(self):
        info = {'data': {'usage': 0.0123, 'limit': 1, 'limit_remaining': 0.9877}}
        with patch('urllib.request.urlopen', return_value=Response(json.dumps(info).encode(), 'application/json')):
            result = openrouter_tts.key_info(KEY)
        self.assertTrue(result['ok'])
        self.assertIn('kalan sınır $0.9877', result['message'])
        with patch('urllib.request.urlopen', side_effect=http_error(401)):
            self.assertFalse(openrouter_tts.key_info(KEY)['ok'])
        self.assertFalse(openrouter_tts.key_info('')['ok'])

    def test_environment_key_wins(self):
        with patch.dict(os.environ, {'AKTAR_OPENROUTER_API_KEY': ' anahtar '}):
            self.assertEqual(openrouter_tts.api_key(), 'anahtar')


class CloudEngineTests(unittest.TestCase):
    """F188: Drama 3 TR, ui.json drama3_tr_backend='openrouter' iken ayni onayarla OpenRouter'dan okur."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.prefs = {drama3_tr.PREF_DIR: '', drama3_tr.PREF_BACKEND: 'openrouter', 'voices': {'tr': 'drama3-tr/clone'},
                      'options': {'drama3-tr/clone': {'reference': 'C:/ses/a.wav', 'reference_text': 'Bir.'}}}
        self.engines = Engines(root / 'app', REPO / 'engines', prefs=lambda: self.prefs)
        self.addCleanup(self.engines.shutdown)
        self.sent = []

        def fake_speech(text, reference, settings=None, **_kwargs):
            self.sent.append((text, reference, settings))
            return drama3.wav_bytes(array.array('h', pcm(0.08 * len(text))), openrouter_tts.PCM_RATE)

        for target, value in (('drama3.prepare_reference', lambda path, text, *_a, **_k:
                               {'text': text, 'data': 'UklGRg==', 'seconds': 5.0}),
                              ('openrouter_tts.reference_audio', lambda wav: (b'mp3:' + wav, 'mp3')),
                              ('openrouter_tts.api_key', lambda: KEY),
                              ('openrouter_tts.speech', fake_speech)):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def wait(self):
        end = time.time() + 30
        while self.engines.state == 'loading' and time.time() < end:
            time.sleep(0.05)
        return self.engines.status()

    def test_reads_without_model_folder(self):
        self.engines.load('tr')
        status = self.wait()
        self.assertEqual((status['state'], status['device']), ('ready', 'bulut'), status)
        self.assertIsNone(self.engines._worker.impl.server)            # yerel sunucu baslamaz
        self.assertEqual(self.engines.runtime()['kind'], 'remote')
        result = self.engines.say('Bir cümle.')
        self.assertGreater(result['duration'], 0)
        self.assertEqual(len(self.sent), 1)                              # isitma istegi yok
        text, reference, settings = self.sent[0]
        self.assertEqual(text, 'Bir cümle.')
        self.assertEqual((reference['audio'], reference['format'], reference['text']), (b'mp3:RIFF', 'mp3', 'Bir.'))
        self.assertEqual(settings, {'temperature': 1.0, 'top_p': drama3_tr.TOP_P})

    def test_cache_key_separates_backends(self):
        book = '0123456789abcdef'
        cloud = self.engines._cache_path(book, 'Bir.', 1.0, 'tr')
        self.prefs[drama3_tr.PREF_BACKEND] = 'local'
        local = self.engines._cache_path(book, 'Bir.', 1.0, 'tr')
        self.prefs.pop(drama3_tr.PREF_BACKEND)
        self.assertEqual(self.engines._cache_path(book, 'Bir.', 1.0, 'tr'), local)   # eski anahtarlar gecerli
        self.assertNotEqual(cloud, local)

    def test_switching_backend_reloads(self):
        self.engines.load('tr')
        self.assertEqual(self.wait()['state'], 'ready')
        self.prefs[drama3_tr.PREF_DIR] = ''
        self.prefs[drama3_tr.PREF_BACKEND] = 'local'
        self.engines.load('tr')
        status = self.wait()
        self.assertEqual(status['state'], 'error')                       # yerel kip klasor ister
        self.assertIn('Drama 3 TR klasörü seçilmedi', status['message'])

    def test_missing_key(self):
        with patch('openrouter_tts.api_key', lambda: ''):
            self.engines.load('tr')
            status = self.wait()
        self.assertEqual(status['state'], 'error')
        self.assertIn('OpenRouter API anahtarı', status['message'])

    def test_cfg_is_local_only(self):
        engine = next(e for e in self.engines.engines() if e['id'] == 'drama3-tr')
        self.assertEqual(engine['cloud'], 'openrouter')
        self.assertEqual([s['key'] for s in engine['settings'] if s.get('local_only')], ['cfg'])


class PrepareWatchTests(unittest.TestCase):
    """F188: Hazirla uzun sure ilerlemezse beklenen yer Konsol'a yazilir."""

    def test_stuck_prepare_is_logged_once(self):
        import threading
        import bridge_tts
        release = threading.Event()

        class FakeEngines:
            def prepare(self, book, sentences, speed, language, progress, cancel, breaks):
                progress(1, 2)
                release.wait(10)
                return 1

        class Host(bridge_tts.TtsMixin):
            def __init__(self):
                self.lines, self.events = [], []

            def _engines(self):
                return FakeEngines()

            def _log(self, message):
                self.lines.append(message)

            def _emit(self, name, data):
                self.events.append((name, data))

        host = Host()
        with patch.object(bridge_tts, 'PREPARE_STUCK', 0.2), patch.object(bridge_tts, 'PREPARE_POLL', 0.05):
            host.tts_prepare('0123456789abcdef', ['Bir.', 'Iki.'])
            end = time.time() + 5
            while not host.lines and time.time() < end:
                time.sleep(0.05)
            time.sleep(0.4)
            release.set()
            host._prepare_job.join(5)
        self.assertEqual(len(host.lines), 1)
        self.assertIn('ilerlemiyor', host.lines[0])
        self.assertIn('prepare', host.lines[0])


@unittest.skipUnless(os.environ.get('AKTAR_OPENROUTER_API_KEY'), 'gercek OpenRouter denemesi: anahtar yok')
class LiveTests(unittest.TestCase):
    def test_key(self):
        self.assertTrue(openrouter_tts.key_info()['ok'])


if __name__ == '__main__':
    unittest.main()
