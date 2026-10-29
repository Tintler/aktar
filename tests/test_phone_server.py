import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import phone_server  # noqa: E402


class PhoneServerTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.spoken = []
        self.busy = None

        def speak(text, speed):
            if self.busy:
                raise phone_server.Busy(self.busy)
            self.spoken.append((text, speed))
            return b'RIFF-fake-wav'

        self.server = phone_server.PhoneServer(speak, phone_server.Phones(Path(self.folder.name) / 'telefonlar.json'),
                                               '9.9.9', log=lambda _line: None)
        self.server.start(0, '127.0.0.1')
        self.base = f'http://127.0.0.1:{self.server.info()["port"]}'

    def tearDown(self):
        self.server.stop()
        self.folder.cleanup()

    def request(self, path, body=None, token=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        request = urllib.request.Request(self.base + path, data=data, method='GET' if body is None else 'POST')
        if token:
            request.add_header('X-Anahtar', token)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers.get('Content-Type'), response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.headers.get('Content-Type'), error.read()

    def pair(self):
        status, _kind, body = self.request('/api/eslestir', {'kod': self.server.code, 'ad': 'Babamın telefonu'})
        self.assertEqual(status, 200)
        return json.loads(body)['anahtar']

    def test_status_without_key(self):
        status, _kind, body = self.request('/api/durum')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'uygulama': 'Aktar', 'surum': '9.9.9', 'eslesmis': False})

    def test_pair_and_read(self):
        token = self.pair()
        self.assertTrue(json.loads(self.request('/api/durum', token=token)[2])['eslesmis'])
        status, kind, body = self.request('/api/oku', {'metin': '  Merhaba\n dünya. ', 'hiz': 1.2}, token)
        self.assertEqual((status, kind, body), (200, 'audio/wav', b'RIFF-fake-wav'))
        self.assertEqual(self.spoken, [('Merhaba dünya.', 1.2)])
        self.assertEqual(self.server.phones.listing()[0]['ad'], 'Babamın telefonu')

    def test_read_needs_key(self):
        status, _kind, body = self.request('/api/oku', {'metin': 'Merhaba'})
        self.assertEqual(status, 401)
        self.assertIn('hata', json.loads(body))
        self.assertEqual(self.request('/api/oku', {'metin': 'Merhaba'}, 'yanlis')[0], 401)
        self.assertEqual(self.spoken, [])

    def test_wrong_code_locks_after_limit(self):
        wrong = '000000' if self.server.code != '000000' else '111111'
        for _ in range(phone_server.PAIR_TRIES):
            self.assertEqual(self.request('/api/eslestir', {'kod': wrong})[0], 403)
        self.assertEqual(self.request('/api/eslestir', {'kod': self.server.code})[0], 403)

    def test_busy_engine_is_503(self):
        token = self.pair()
        self.busy = 'Aktar sesli kitap kaydediyor.'
        status, _kind, body = self.request('/api/oku', {'metin': 'Merhaba'}, token)
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)['hata'], 'Aktar sesli kitap kaydediyor.')

    def test_empty_text_is_400(self):
        token = self.pair()
        self.assertEqual(self.request('/api/oku', {'metin': '   '}, token)[0], 400)

    def test_removed_phone_is_rejected(self):
        token = self.pair()
        self.assertTrue(self.server.phones.remove(token[:8]))
        self.assertEqual(self.request('/api/oku', {'metin': 'Merhaba'}, token)[0], 401)

    def test_outside_lan_is_rejected(self):
        with mock.patch.object(phone_server, 'allowed_client', return_value=False):
            self.assertEqual(self.request('/api/durum')[0], 403)

    def test_clamp_and_clean(self):
        self.assertEqual(phone_server.clamp_speed('x'), 1.0)
        self.assertEqual(phone_server.clamp_speed(9), 2.0)
        self.assertEqual(phone_server.clamp_speed(0.1), 0.5)
        self.assertEqual(phone_server.clamp_speed(float('nan')), 1.0)
        self.assertEqual(len(phone_server.clean_text('a ' * 2000)), phone_server.TEXT_LIMIT)

    def test_allowed_client(self):
        self.assertTrue(phone_server.allowed_client('192.168.1.20'))
        self.assertTrue(phone_server.allowed_client('127.0.0.1'))
        self.assertTrue(phone_server.allowed_client('::ffff:10.0.0.5'))
        self.assertFalse(phone_server.allowed_client('8.8.8.8'))
        self.assertFalse(phone_server.allowed_client('bozuk'))


if __name__ == '__main__':
    unittest.main()
