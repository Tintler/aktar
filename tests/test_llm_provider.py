"""Model sunucusu (F152) testleri: adres kurali, sunucu turu, OpenAI uyumlu kitap istegi."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import app_core
import book_core
import llm_provider


class ScopeTests(unittest.TestCase):
    def test_scope(self):
        for url, expected in (
            ('http://127.0.0.1:1234/v1', 'local'), ('http://localhost:11434/v1', 'local'), ('http://[::1]:8080/v1', 'local'),
            ('http://192.168.1.5:1234/v1', 'lan'), ('http://10.70.238.67:5000/v1', 'lan'), ('http://172.20.0.2/v1', 'lan'),
            ('http://100.101.1.2:8080/v1', 'lan'), ('http://gpu-box:8000/v1', 'lan'), ('http://nas.local/v1', 'lan'),
            ('https://api.openai.com/v1', 'internet'), ('http://8.8.8.8/v1', 'internet'), ('', 'internet'),
        ):
            self.assertEqual(llm_provider.scope(url), expected, url)

    def test_validate(self):
        ok = ('http://127.0.0.1:1234/v1', 'http://192.168.1.5:1234/v1', 'https://api.openai.com/v1', 'https://openrouter.ai/api/v1')
        for url in ok:
            llm_provider.validate({'base_url': url, 'provider': 'openai'})
        for url in ('http://example.com/v1', 'ftp://127.0.0.1/v1', 'http:///v1', 'https://user:pw@api.openai.com/v1'):
            with self.assertRaises(ValueError, msg=url):
                llm_provider.validate({'base_url': url})
        with self.assertRaises(ValueError):
            llm_provider.validate({'base_url': 'http://127.0.0.1:1234/v1', 'provider': 'gemini'})
        # Uygulama ve kitap ayarlari ayni kurali kullanir.
        app_core.validate_config(dict(app_core.DEFAULT_CONFIG, base_url='https://api.openai.com/v1', provider='openai'))
        book_core.validate_config(dict(book_core.DEFAULT_CONFIG, base_url='http://192.168.1.5:1234/v1'))

    def test_extensions_only_for_lmstudio_or_local(self):
        self.assertTrue(llm_provider.sends_extensions({'base_url': 'https://api.openai.com/v1', 'provider': 'lmstudio'}))
        self.assertTrue(llm_provider.sends_extensions({'base_url': 'http://127.0.0.1:8080/v1', 'provider': 'openai'}))
        self.assertFalse(llm_provider.sends_extensions({'base_url': 'https://api.openai.com/v1', 'provider': 'openai'}))
        cfg = dict(app_core.DEFAULT_CONFIG, base_url='https://api.openai.com/v1', provider='openai', disable_thinking=True)
        payload = {}
        app_core.Client(cfg)._thinking(payload)
        self.assertEqual(payload, {})

    def test_api_key_header(self):
        with mock.patch.dict('os.environ', {'AKTAR_API_KEY': 'sk-test'}, clear=False):
            self.assertEqual(llm_provider.headers()['Authorization'], 'Bearer sk-test')


class LmStudioOnlyTests(unittest.TestCase):
    def test_keep_loaded_skips_openai_servers(self):
        client = mock.Mock(cfg={'provider': 'openai', 'base_url': 'http://127.0.0.1:11434/v1'})
        self.assertEqual(app_core.keep_loaded(client, ['a', 'b']), [])
        app_core.unload_models(client, ['x'])
        client.request.assert_not_called()

    def test_bridge_unload_ejects_and_forgets_kept_model(self):
        # F183: sol alttaki panelden eject; Aktar'in yukledigi model kapanista yeniden bosaltilmaz.
        import bridge
        calls = []

        class Fake:
            def __init__(self, cfg, _log=None):
                self.cfg = cfg

            def request(self, route, payload=None):
                calls.append((route, payload))
                return {'models': []} if route == '/api/v1/models' else {}

        cfg = dict(app_core.DEFAULT_CONFIG)
        with mock.patch('bridge.load_config', return_value=cfg), mock.patch('bridge.Client', Fake):
            api = bridge.Bridge()
            api._kept_models = ['gomme', 'sohbet']
            result = api.llm_unload('gomme')
            self.assertEqual(result, {'models': [], 'kept': ['sohbet']})
            self.assertEqual(calls[0], ('/api/v1/models/unload', {'instance_id': 'gomme'}))
            self.assertIn('error', api.llm_unload(''))
            # Art arda sorgu (arayuz dongusu) sunucuya gitmez: saniyede en fazla bir istek.
            listed = len(calls)
            for _ in range(50):
                api.llm_loaded()
            self.assertEqual(len(calls), listed)
            api._loaded_last = (0.0, None)
            cfg.update(provider='openai')
            self.assertEqual(api.llm_loaded(), {'models': None, 'kept': ['sohbet']})
            self.assertIn('error', api.llm_unload('sohbet'))

    def test_rest_routes_refused_for_openai(self):
        cfg = dict(app_core.DEFAULT_CONFIG, base_url='http://127.0.0.1:11434/v1', provider='openai')
        with self.assertRaises(RuntimeError):
            app_core.Client(cfg).request('/api/v1/models')


class BookOpenAITests(unittest.TestCase):
    def client(self):
        cfg = dict(book_core.DEFAULT_CONFIG, base_url='http://127.0.0.1:8080/v1', provider='openai', model='m')
        return book_core.Client(cfg, log=lambda _message: None)

    def test_generate_uses_chat_completions_and_marker(self):
        client = self.client()
        sent = {}

        def request(route, payload=None):
            sent['route'], sent['payload'] = route, payload
            marker = payload['messages'][1]['content'].rsplit(' ', 1)[-1]
            return {'choices': [{'message': {'content': 'Merhaba dünya.\n' + marker}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}

        client.request = request
        self.assertEqual(client.generate('SYSTEM', 'USER', 100), 'Merhaba dünya.')
        self.assertEqual(sent['route'], '/chat/completions')
        self.assertEqual(sent['payload']['max_tokens'], 100)
        self.assertTrue(sent['payload']['messages'][0]['content'].startswith('SYSTEM'))
        self.assertIn('completion marker', sent['payload']['messages'][1]['content'])
        self.assertEqual(client.context_length(), (int(book_core.DEFAULT_CONFIG['fallback_context_length']), 'config fallback'))

    def test_generate_rejects_truncated_answer(self):
        client = self.client()
        client.request = lambda route, payload=None: {
            'choices': [{'message': {'content': 'Yarım'}, 'finish_reason': 'length'}], 'usage': {}}
        with self.assertRaisesRegex(ValueError, 'token sinirina'):
            client.generate('S', 'U', 100, require_marker=False)

    def test_connection_errors_stay_retryable(self):
        self.assertTrue(book_core.retryable_translation_error(RuntimeError('Model sunucusuna baglanilamadi: x')))
        self.assertTrue(app_core.retryable_translation_error(RuntimeError('Model sunucusu istegi zaman asimina ugradi.')))


class ProfileTests(unittest.TestCase):
    """F236: baglanti profilleri; gecis yerel baglantiyi bozmaz, anahtar profil basina saklanir."""

    def setUp(self):
        import json
        import tempfile
        import bridge
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.secrets = {}
        self.json = json
        (self.root / 'config.json').write_text(json.dumps(dict(
            app_core.DEFAULT_CONFIG, base_url='http://127.0.0.1:5000/v1', model='gemma', qa_model='kucuk')), encoding='utf-8')
        llm_provider._key_cache.clear()
        self.patches = [
            mock.patch.object(bridge, 'APP_DIR', self.root),
            mock.patch('secret_store.set_secret', side_effect=lambda k, v: self.secrets.__setitem__(k, v)),
            mock.patch('secret_store.get_secret', side_effect=lambda k: self.secrets.get(k)),
            mock.patch('secret_store.delete_secret', side_effect=lambda k: self.secrets.pop(k, None)),
            mock.patch.dict('os.environ', {'AKTAR_API_KEY': '', 'LM_STUDIO_API_KEY': ''}),
            mock.patch.object(bridge.Bridge, 'refresh_models', lambda self: True),
        ]
        for patch in self.patches:
            patch.start()
        self.secrets['llm-api-key'] = 'yerel-anahtar'
        self.secrets['llm-api-key@openai'] = 'eski'   # silinememis eski kayit yeni profile gecmemeli
        self.api = bridge.Bridge()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        llm_provider._key_cache.clear()
        self.temp.cleanup()

    def config(self):
        return self.json.loads((self.root / 'config.json').read_text(encoding='utf-8'))

    def test_create_keeps_current_connection_and_switch_back(self):
        result = self.api.llm_profile_create('OpenAI')
        self.assertNotIn('error', result)
        cfg = self.config()
        self.assertEqual([p['name'] for p in cfg['llm_profiles']], ['LM Studio', 'OpenAI'])
        self.assertEqual([p['id'] for p in cfg['llm_profiles']], ['lm-studio', 'openai'])
        self.assertEqual(cfg['llm_profile'], 'openai')
        self.assertEqual(self.secrets['llm-api-key@lm-studio'], 'yerel-anahtar')
        self.assertNotIn('llm-api-key', self.secrets)   # yeni baglanti anahtarsiz
        self.assertNotIn('llm-api-key@openai', self.secrets)

        # Yeni baglanti Ayarlar'dan duzenlenir: kaydetme etkin profili gunceller, profil listesine dokunulmaz.
        values = dict(cfg, base_url='https://api.openai.com/v1', provider='openai', model='gpt-5', qa_model='',
                      llm_profiles=[], llm_profile='')
        self.assertNotIn('error', self.api.save_settings(values))
        self.assertNotIn('error', self.api.llm_set_api_key('sk-openai'))
        cfg = self.config()
        self.assertEqual(cfg['llm_profile'], 'openai')
        self.assertEqual(cfg['llm_profiles'][1]['base_url'], 'https://api.openai.com/v1')
        self.assertEqual(cfg['llm_profiles'][0]['base_url'], 'http://127.0.0.1:5000/v1')
        self.assertEqual(self.secrets['llm-api-key@openai'], 'sk-openai')

        self.assertNotIn('error', self.api.llm_profile_use('lm-studio'))
        cfg = self.config()
        self.assertEqual((cfg['base_url'], cfg['provider'], cfg['model'], cfg['qa_model']),
                         ('http://127.0.0.1:5000/v1', 'lmstudio', 'gemma', 'kucuk'))
        self.assertEqual(llm_provider.headers()['Authorization'], 'Bearer yerel-anahtar')
        self.api.llm_profile_use('openai')
        self.assertEqual(self.config()['model'], 'gpt-5')
        self.assertEqual(llm_provider.headers()['Authorization'], 'Bearer sk-openai')

    def test_rename_and_delete(self):
        self.api.llm_profile_create('Uzak')
        self.assertNotIn('error', self.api.llm_profile_rename('lm-studio', 'Masaüstü'))
        self.assertEqual(self.config()['llm_profiles'][0]['name'], 'Masaüstü')
        # Kullanilan baglanti silinince kalan ilk baglantiya (anahtariyla) gecilir.
        self.assertNotIn('error', self.api.llm_profile_delete('uzak'))
        self.assertEqual(self.config()['llm_profile'], 'lm-studio')
        self.assertEqual(llm_provider.api_key(), 'yerel-anahtar')
        self.assertNotIn('error', self.api.llm_profile_delete('lm-studio'))
        self.assertNotIn('llm-api-key@lm-studio', self.secrets)
        self.assertEqual(self.config()['base_url'], 'http://127.0.0.1:5000/v1')
        cfg = self.config()
        self.assertEqual((cfg['llm_profiles'], cfg['llm_profile']), ([], ''))
        self.assertIn('error', self.api.llm_profile_use('yok'))
        self.assertIn('error', self.api.llm_profile_create('  '))

    def test_validate_profiles(self):
        base = dict(app_core.DEFAULT_CONFIG)
        with self.assertRaises(ValueError):
            app_core.validate_config(dict(base, llm_profile='yok'))
        with self.assertRaises(ValueError):
            app_core.validate_config(dict(base, llm_profiles=[{'id': 'a', 'name': 'A', 'base_url': 'http://example.com/v1'}]))
        app_core.validate_config(dict(base, llm_profile='a', llm_profiles=[{'id': 'a', 'name': 'A', **llm_provider.snapshot(base)}]))

if __name__ == '__main__':
    unittest.main()
