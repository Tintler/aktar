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

        self.described = []

        def speak(text, speed):
            if self.busy:
                raise phone_server.Busy(self.busy)
            self.spoken.append((text, speed))
            return b'RIFF-fake-wav'

        def describe(image, mime):
            if self.busy:
                raise phone_server.Busy(self.busy)
            self.described.append((image, mime))
            return '  Bir köy meydanı.\n Kalabalık var. '

        self.server = phone_server.PhoneServer(speak, phone_server.Phones(Path(self.folder.name) / 'telefonlar.json'),
                                               '9.9.9', log=lambda _line: None, describe=describe,
                                               diagnostics=phone_server.Diagnostics(Path(self.folder.name) / 'teshis'))
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

    def send_image(self, data, kind, token):
        request = urllib.request.Request(self.base + '/api/betimle', data=data, method='POST')
        request.add_header('Content-Type', kind)
        if token:
            request.add_header('X-Anahtar', token)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_describe_image(self):
        token = self.pair()
        status, body = self.send_image(b'\xff\xd8fake-jpeg', 'image/jpeg', token)
        self.assertEqual((status, body), (200, {'metin': 'Bir köy meydanı. Kalabalık var.'}))
        self.assertEqual(self.described, [(b'\xff\xd8fake-jpeg', 'image/jpeg')])

    def test_describe_needs_key_and_image(self):
        self.assertEqual(self.send_image(b'x', 'image/jpeg', None)[0], 401)
        token = self.pair()
        self.assertEqual(self.send_image(b'metin', 'text/plain', token)[0], 400)
        with mock.patch.object(phone_server, 'MAX_IMAGE', 4):
            self.assertEqual(self.send_image(b'12345', 'image/png', token)[0], 400)
        self.assertEqual(self.described, [])
        # bozuk istekten sonra ayni sunucu calismaya devam eder
        self.assertEqual(self.send_image(b'ok', 'image/png', token)[0], 200)

    def test_describe_busy_or_missing_is_503(self):
        token = self.pair()
        self.busy = 'Resim betimleme Aktar\'da kapalı.'
        status, body = self.send_image(b'x', 'image/jpeg', token)
        self.assertEqual((status, body['hata']), (503, 'Resim betimleme Aktar\'da kapalı.'))
        self.server.describe = None
        self.busy = None
        self.assertEqual(self.send_image(b'x', 'image/jpeg', token)[0], 503)

    def test_diagnostics_saved_with_screenshot(self):
        import base64
        token = self.pair()
        record = {'paket': 'com.facebook/katana', 'dokunus': [10, 20], 'agac': {'b': [0, 0, 1, 1]},
                  'ekran_goruntusu': base64.b64encode(b'\xff\xd8jpeg').decode()}
        status, _kind, body = self.request('/api/teshis', record, token)
        self.assertEqual(status, 200)
        name = json.loads(body)['kayit']
        self.assertTrue(name.endswith('-com.facebook_katana'))
        folder = Path(self.folder.name) / 'teshis'
        saved = json.loads((folder / (name + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(saved['ekran_goruntusu'], name + '.jpg')
        self.assertEqual((folder / (name + '.jpg')).read_bytes(), b'\xff\xd8jpeg')
        self.assertEqual(self.server.diagnostics.count(), 1)
        # ayni saniyede ikinci kayit ustune yazmaz
        self.request('/api/teshis', {'paket': 'com.facebook/katana'}, token)
        self.assertEqual(self.server.diagnostics.count(), 2)

    def test_diagnostics_need_key_and_are_pruned(self):
        self.assertEqual(self.request('/api/teshis', {'paket': 'x'})[0], 401)
        token = self.pair()
        with mock.patch.object(phone_server, 'DIAG_KEEP', 2):
            for _ in range(4):
                self.assertEqual(self.request('/api/teshis', {'paket': 'x'}, token)[0], 200)
        self.assertEqual(self.server.diagnostics.count(), 2)

    def test_plain_text(self):
        import bridge_phone
        self.assertEqual(bridge_phone.plain_text('<think>hmm</think>**Resimde** bir kedi var.\n- Yazı: `Merhaba`'),
                         'Resimde bir kedi var. Yazı: Merhaba')

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
