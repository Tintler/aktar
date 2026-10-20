import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))

import array
import base64
import http.server
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

import drama3
from tts import Engines

REPO = Path(__file__).resolve().parents[1]

try:
    import media
    FFMPEG = media.ffmpeg_path()
except Exception:   # ffmpeg yok
    FFMPEG = None

RATE = 44100


def tone(seconds, level=8000, rate=RATE):
    """Kare dalga (sessizlik esiginin cok ustunde)."""
    period = max(2, rate // 200)
    return array.array('h', (level if (i // (period // 2)) % 2 else -level for i in range(int(rate * seconds))))


def silence(seconds, rate=RATE):
    return array.array('h', bytes(2 * int(rate * seconds)))


class FakeServer:
    """Drama 3 sunucusunun yerine gecen yerel HTTP sunucusu: istekleri kaydeder, `replies` sirasiyla yanitlar."""

    def __init__(self):
        self.requests = []
        self.replies = []        # [(kod, govde bayt)]; bossa her metin icin 0,5 sn ses
        self.healthy = True
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _send(self, code, body, kind='application/json'):
                self.send_response(code)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == '/health':
                    status = 'healthy' if owner.healthy else 'starting'
                    self._send(200, json.dumps({'status': status, 'pending_completions': 0}).encode())
                else:
                    self._send(404, b'{}')

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8'))
                owner.requests.append((self.path, body))
                if owner.replies:
                    code, data = owner.replies.pop(0)
                    self._send(code, data, 'audio/wav' if code == 200 else 'application/json')
                else:
                    self._send(200, drama3.wav_bytes(tone(0.5), RATE), 'audio/wav')

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def free_url():
    import socket
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return f'http://127.0.0.1:{probe.getsockname()[1]}'


class SplitTests(unittest.TestCase):
    def test_sentences_go_separately(self):
        pieces = drama3.split_text('Merhaba dünya. Nasılsın? İyiyim!')
        self.assertEqual([p for p, _ in pieces], ['Merhaba dünya.', 'Nasılsın?', 'İyiyim!'])
        self.assertEqual({g for _, g in pieces}, {drama3.SENTENCE_GAP})

    def test_long_sentence_splits_at_commas(self):
        clause = 'bu cümlenin bir parçası oldukça uzun yazılmış bir yan cümledir'
        text = ', '.join([clause] * 6) + '.'
        pieces = drama3.split_text(text, limit=150)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(p) <= 150 for p, _ in pieces))
        self.assertEqual(' '.join(p for p, _ in pieces), text)
        self.assertEqual([g for _, g in pieces][-1], drama3.SENTENCE_GAP)
        self.assertEqual({g for _, g in pieces[:-1]}, {drama3.CLAUSE_GAP})

    def test_sentence_without_commas_splits_at_words(self):
        text = ' '.join(['kelime'] * 80) + '.'
        pieces = drama3.split_text(text, limit=100)
        self.assertTrue(all(len(p) <= 100 for p, _ in pieces))
        self.assertEqual(' '.join(p for p, _ in pieces), text)

    def test_tags_pass_unchanged_and_are_not_split(self):
        whisper = '<whisper>sessizce, çok sessizce, kimse duymasın, söylüyorum</whisper>'
        text = '[laughs] Bak, ' + whisper + ', anladın mı, tamam mı, gerçekten mi?'
        pieces = [p for p, _ in drama3.split_text(text, limit=40)]
        self.assertIn(whisper, ' '.join(pieces))
        self.assertTrue(any(whisper in p for p in pieces))
        self.assertTrue(pieces[0].startswith('[laughs]'))

    def test_speaker_tag_carries_to_following_pieces(self):
        pieces = [p for p, _ in drama3.split_text('<|speaker:1|>Selam. Nasılsın? <|speaker:0|>İyiyim. Sen?')]
        self.assertEqual(pieces, ['<|speaker:1|>Selam.', '<|speaker:1|>Nasılsın?', '<|speaker:0|>İyiyim.',
                                  '<|speaker:0|>Sen?'])

    def test_lower_case_continuation_does_not_end_sentence(self):
        text = "Çöküşü'nün 44. bölümünü izliyordum. \"Gelir misin?\" diye sordu. Sonra gitti."
        self.assertEqual([p for p, _ in drama3.split_text(text)],
                         ["Çöküşü'nün 44. bölümünü izliyordum.", '"Gelir misin?" diye sordu.', 'Sonra gitti.'])

    def test_empty_text(self):
        self.assertEqual(drama3.split_text('   '), [])


class SilenceTests(unittest.TestCase):
    def test_long_silence_is_shortened(self):
        samples = tone(1.0) + silence(6.0) + tone(1.0)
        result = drama3.shorten_silences(samples, RATE)
        self.assertAlmostEqual(len(result) / RATE, 2.0 + drama3.SILENCE_KEEP, delta=0.03)
        self.assertEqual(result[:RATE], tone(1.0))
        self.assertEqual(result[-RATE:], tone(1.0))

    def test_short_silence_is_kept(self):
        samples = tone(0.5) + silence(0.8) + tone(0.5)
        self.assertEqual(drama3.shorten_silences(samples, RATE), samples)

    def test_edges_are_shortened_too(self):
        samples = silence(3.0) + tone(1.0) + silence(2.5)
        result = drama3.shorten_silences(samples, RATE)
        self.assertAlmostEqual(len(result) / RATE, 1.0 + 2 * drama3.SILENCE_KEEP, delta=0.03)

    def test_join_adds_gaps_between_clips(self):
        joined = drama3.join_clips([(tone(0.5), 0.25), (tone(0.5), 0.12), (tone(0.5), 0.25)], RATE)
        self.assertEqual(len(joined), int(RATE * 0.5) * 3 + int(RATE * 0.25) + int(RATE * 0.12))

    def test_wav_round_trip(self):
        samples, rate = drama3.read_pcm(drama3.wav_bytes(tone(0.2), 22050))
        self.assertEqual((len(samples), rate), (int(RATE * 0.2), 22050))


class CutPointTests(unittest.TestCase):
    def words(self, items):
        return [{'start': items[0][0], 'end': items[-1][1], 'text': '',
                 'words': [[a, b, w] for a, b, w in items]}]

    def test_prefers_sentence_end_inside_limit(self):
        segments = self.words([(0, 3, 'Bir'), (3, 9, 'cümle.'), (9.5, 15, 'İkinci'), (15, 19, 'devam'),
                               (19.2, 22, 'ediyor.')])
        end, text = drama3._cut_point(segments, 20)
        self.assertEqual(text, 'Bir cümle.')
        self.assertAlmostEqual(end, 9.15)

    def test_falls_back_to_last_word(self):
        segments = self.words([(0, 2, 'Kısa.'), (2.5, 10, 'uzun'), (10, 19.5, 'konuşma'), (19.6, 25, 'sürüyor')])
        end, text = drama3._cut_point(segments, 20)
        self.assertEqual(text, 'Kısa. uzun konuşma')
        self.assertLessEqual(end, 20)

    def test_no_speech(self):
        self.assertEqual(drama3._cut_point([], 20), (0.0, ''))


class SilentPieceTests(unittest.TestCase):
    LONG = 'Kısmen insan, kısmen bot yapısıyız; şirketin güvenlik teminatının bir parçası olarak kiralanıyoruz.'

    def test_detects_model_falling_silent(self):
        self.assertTrue(drama3.fell_silent(self.LONG, tone(1.0) + silence(6.0), RATE))
        self.assertFalse(drama3.fell_silent(self.LONG, tone(6.0) + silence(0.5), RATE))
        self.assertFalse(drama3.fell_silent('Ya da başka bir şey...', tone(0.3), RATE))   # kisa parca denetlenmez

    def test_letters_ignore_tags_and_punctuation(self):
        self.assertEqual(drama3.letters('[laughs] <whisper>Bak, şu!</whisper> 44.'), 7)

    def test_silent_piece_is_requested_again_with_server_defaults(self):
        server = FakeServer()
        self.addCleanup(server.close)
        server.replies = [(200, drama3.wav_bytes(tone(1.0) + silence(6.0), RATE)),
                          (200, drama3.wav_bytes(tone(6.0), RATE))]
        engine = drama3.Engine(tempfile.gettempdir(), prefs=lambda: {'drama3_url': server.url})
        engine.reference = {'text': 'Kayıt.', 'data': 'QUJD', 'seconds': 3}
        _data, duration = engine.say(self.LONG)
        self.assertAlmostEqual(duration, 6.0, delta=0.05)
        self.assertEqual(len(server.requests), 2)
        self.assertEqual(server.requests[0][1]['temperature'], drama3.TEMPERATURE)
        self.assertNotIn('temperature', server.requests[1][1])

    def test_keeps_the_most_complete_attempt(self):
        server = FakeServer()
        self.addCleanup(server.close)
        server.replies = [(200, drama3.wav_bytes(tone(1.0), RATE)), (200, drama3.wav_bytes(tone(2.0), RATE)),
                          (200, drama3.wav_bytes(tone(0.5), RATE))]
        logs = []
        engine = drama3.Engine(tempfile.gettempdir(), prefs=lambda: {'drama3_url': server.url}, log=logs.append)
        engine.reference = {'text': 'Kayıt.', 'data': 'QUJD', 'seconds': 3}
        _data, duration = engine.say(self.LONG)
        self.assertEqual(len(server.requests), 1 + len(drama3.SILENT_RETRY_TEMPERATURES))
        self.assertAlmostEqual(duration, 2.0, delta=0.05)
        self.assertTrue(any('tam okuyamadı' in line for line in logs))


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.addCleanup(self.server.close)

    def test_request_format(self):
        references = [{'text': 'Kayıt metni.', 'data': 'QUJD'}]
        data = drama3.speech(self.server.url, 'Merhaba [laughs] <whisper>dünya</whisper>', references)
        self.assertEqual(drama3.read_pcm(data)[1], RATE)
        path, body = self.server.requests[0]
        self.assertEqual(path, '/v1/audio/speech')
        self.assertEqual(body, {'model': 'drama-3', 'input': 'Merhaba [laughs] <whisper>dünya</whisper>',
                                'references': [{'text': 'Kayıt metni.', 'data': 'QUJD'}], 'response_format': 'wav',
                                'temperature': drama3.TEMPERATURE})
        self.assertIsNone(drama3.TOP_P)   # top_p kisitlamasi modeli susturuyordu (F160)
        drama3.speech(self.server.url, 'Bir.', temperature=None)
        self.assertNotIn('temperature', self.server.requests[-1][1])

    def test_retries_once_on_server_error(self):
        self.server.replies = [(500, b'{"detail": "generated no audio frames"}')]
        drama3.speech(self.server.url, 'Bir.')
        self.assertEqual(len(self.server.requests), 2)

    def test_second_failure_is_reported(self):
        self.server.replies = [(500, b'{"detail": "generated no audio frames"}')] * 2
        with self.assertRaisesRegex(drama3.ServerError, 'generated no audio frames'):
            drama3.speech(self.server.url, 'Bir.')
        self.assertEqual(len(self.server.requests), 2)

    def test_client_error_is_not_retried(self):
        self.server.replies = [(400, b'{"detail": "references.0.data required"}')]
        with self.assertRaisesRegex(drama3.ServerError, 'HTTP 400'):
            drama3.speech(self.server.url, 'Bir.')
        self.assertEqual(len(self.server.requests), 1)

    def test_health(self):
        self.assertEqual(drama3.health(self.server.url + '/')['status'], 'healthy')
        self.server.healthy = False
        with self.assertRaisesRegex(drama3.ServerError, 'hazır değil'):
            drama3.health(self.server.url)

    def test_unreachable_server_has_clear_message(self):
        url = free_url()
        with self.assertRaisesRegex(drama3.ServerError, 'bağlanılamadı'):
            drama3.health(url, timeout=2)
        with self.assertRaisesRegex(drama3.ServerError, 'bağlanılamadı'):
            drama3.speech(url, 'Bir.', timeout=2)

    def test_normalize_url(self):
        self.assertEqual(drama3.normalize_url(''), drama3.DEFAULT_URL)
        self.assertEqual(drama3.normalize_url(' localhost:7861/ '), 'http://localhost:7861')

    def test_engine_say_joins_pieces_and_shortens_silence(self):
        self.server.replies = [(200, drama3.wav_bytes(tone(0.5) + silence(5.0) + tone(0.5), RATE)),
                               (500, b'{"detail": "generated no audio frames"}'),
                               (200, drama3.wav_bytes(tone(1.0), RATE))]
        engine = drama3.Engine(tempfile.gettempdir(), prefs=lambda: {'drama3_url': self.server.url})
        engine.reference = {'text': 'Kayıt.', 'data': 'QUJD', 'seconds': 3}
        data, duration = engine.say('Birinci cümle. İkinci cümle.')
        expected = 1.0 + drama3.SILENCE_KEEP + drama3.SENTENCE_GAP + 1.0
        self.assertAlmostEqual(duration, expected, delta=0.05)
        self.assertEqual(len(self.server.requests), 3)
        self.assertEqual([body['input'] for _, body in self.server.requests],
                         ['Birinci cümle.', 'İkinci cümle.', 'İkinci cümle.'])
        self.assertTrue(all(body['references'] == [{'text': 'Kayıt.', 'data': 'QUJD'}] for _, body in self.server.requests))


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def recording(self, seconds, name='kayit.wav'):
        path = self.dir / name
        path.write_bytes(drama3.wav_bytes(tone(seconds, rate=22050), 22050))
        return path

    def test_missing_recording(self):
        with self.assertRaisesRegex(ValueError, 'ses kaydı seçin'):
            drama3.prepare_reference('', 'metin', self.dir / 'c')

    @unittest.skipUnless(FFMPEG, 'ffmpeg yok')
    def test_short_recording_with_text(self):
        path = self.recording(5.0)
        result = drama3.prepare_reference(path, '  Merhaba   dünya. ', self.dir / 'c')
        self.assertEqual(result['text'], 'Merhaba dünya.')
        samples, rate = drama3.read_pcm(base64.b64decode(result['data']))
        self.assertEqual(rate, 44100)
        self.assertAlmostEqual(len(samples) / rate, 5.0, delta=0.05)
        # ikinci cagri onbellekten (ffmpeg calismaz)
        with patch('drama3._ffmpeg', side_effect=AssertionError('onbellek kullanilmadi')):
            self.assertEqual(drama3.prepare_reference(path, 'Merhaba dünya.', self.dir / 'c'), result)

    @unittest.skipUnless(FFMPEG, 'ffmpeg yok')
    def test_long_recording_is_cut_and_transcribed(self):
        path = self.recording(26.0)
        calls = []

        def transcribe(audio, language):
            calls.append(language)
            with wave.open(str(audio)) as stream:
                self.assertEqual((stream.getframerate(), stream.getnchannels()), (16000, 1))
            return [{'start': 0, 'end': 26, 'text': '',
                     'words': [[0, 6, 'Birinci'], [6, 12.5, 'cümle.'], [13, 17.8, 'İkinci'], [17.8, 18.6, 'biter.'],
                               [19, 26, 'Üçüncü']]}]

        result = drama3.prepare_reference(path, 'Kullanıcının yazdığı metin', self.dir / 'c', transcribe, 'tr')
        self.assertEqual(calls, ['tr'])
        self.assertEqual(result['text'], 'Birinci cümle. İkinci biter.')
        self.assertLessEqual(result['seconds'], drama3.REFERENCE_SECONDS)
        self.assertAlmostEqual(result['seconds'], 18.75, delta=0.05)

    @unittest.skipUnless(FFMPEG, 'ffmpeg yok')
    def test_text_required_without_whisper(self):
        with self.assertRaisesRegex(ValueError, 'metnini yazın'):
            drama3.prepare_reference(self.recording(5.0), '', self.dir / 'c')

    @unittest.skipUnless(FFMPEG, 'ffmpeg yok')
    def test_missing_text_is_transcribed(self):
        result = drama3.prepare_reference(self.recording(5.0), '', self.dir / 'c',
                                          lambda audio, language: [{'start': 0, 'end': 4, 'text': 'Selam millet.'}])
        self.assertEqual(result['text'], 'Selam millet.')
        self.assertAlmostEqual(result['seconds'], 5.0, delta=0.05)


class BuiltinEngineTests(unittest.TestCase):
    """tts.Engines engines/drama3/motor.json'i yerlesik motor olarak calistirir (ayri surec yok)."""

    def setUp(self):
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prefs = {'drama3_url': self.server.url, 'voices': {'tr': 'drama3/clone'},
                      'options': {'drama3/clone': {'reference': 'C:/ses/kayit.wav', 'reference_text': 'Merhaba.'}}}
        self.engines = Engines(Path(self.temp.name), REPO / 'engines', prefs=lambda: self.prefs)
        self.addCleanup(self.engines.shutdown)

    def wait(self):
        end = time.time() + 20
        while self.engines.state == 'loading' and time.time() < end:
            time.sleep(0.05)
        return self.engines.status()

    def test_listed_as_builtin_with_attribution(self):
        engine = next(e for e in self.engines.engines() if e['id'] == 'drama3')
        self.assertEqual(engine['mode'], 'builtin')
        self.assertFalse(engine['removable'])
        self.assertTrue(engine['server'])
        self.assertEqual(engine['attribution'], 'Built with Fish Audio')
        self.assertIn('Rızası olmadan', engine['notice'])
        self.assertEqual(engine['languages'], ['en', 'tr'])

    def test_cache_tag_separates_sentence_cache(self):
        path = self.engines._cache_path('0123456789abcdef', 'Bir.', 1.0, 'tr')
        with patch.object(self.engines, '_manifests', return_value={'drama3': {'id': 'drama3', 'builtin': 'drama3',
                                                                              'voices': [{'id': 'clone', 'language': 'tr'}]}}):
            self.assertNotEqual(self.engines._cache_path('0123456789abcdef', 'Bir.', 1.0, 'tr'), path)

    def test_never_chosen_by_itself(self):
        self.prefs.pop('voices')
        self.assertEqual(self.engines.choice('en'), (None, None))
        self.assertNotEqual(self.engines.choice('tr')[0], 'drama3')
        self.prefs['voices'] = {'en': 'drama3/clone-en'}
        self.assertEqual(self.engines.choice('en'), ('drama3', 'clone-en'))

    def test_load_and_say(self):
        prepared = {'text': 'Merhaba.', 'data': 'QUJD', 'seconds': 4.0}
        with patch('drama3.prepare_reference', return_value=prepared) as prepare:
            status = self.engines.load('tr')
            status = self.wait()
        self.assertEqual((status['state'], status['engine'], status['voice'], status['device']),
                         ('ready', 'drama3', 'clone', 'sunucu'), status)
        self.assertEqual(prepare.call_args.args[:2], ('C:/ses/kayit.wav', 'Merhaba.'))
        result = self.engines.say('Bir cümle.')
        self.assertAlmostEqual(result['duration'], 0.5, delta=0.02)
        with wave.open(io.BytesIO(base64.b64decode(result['audio']))) as clip:
            self.assertEqual(clip.getframerate(), RATE)
        self.assertEqual(self.server.requests[-1][1]['references'], [{'text': 'Merhaba.', 'data': 'QUJD'}])

    def test_server_down_gives_clear_error(self):
        self.prefs['drama3_url'] = free_url()
        self.engines.load('tr')
        status = self.wait()
        self.assertEqual(status['state'], 'error')
        self.assertIn('Drama 3 sunucusuna bağlanılamadı', status['message'])


if __name__ == '__main__':
    unittest.main()
