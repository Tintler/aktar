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


if __name__ == '__main__':
    unittest.main()
