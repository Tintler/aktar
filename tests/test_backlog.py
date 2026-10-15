"""Backlog sitesi (backlog.py, F94) testleri: yerel sahte HTTP sunucusuyla, internet gerektirmez."""
from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import assistant  # noqa: E402
import backlog  # noqa: E402
from app_core import DEFAULT_CONFIG, validate_config  # noqa: E402

QUIET = (lambda _message: None)
TITLES = {'games': ['Cyberpunk 2077', 'Cyberpunk 2077: Phantom Liberty', 'Doom', 'Up', '1979', 'Inside'],
          'anime': ['Cyberpunk: Edgerunners'], 'screen': ['Spirited Away', 'Sen to Chihiro no Kamikakushi']}
RECORDS = {
    'cyberpunk 2077': [
        {'section': 'games', 'id': 'g1', 'Game name': 'Cyberpunk 2077', 'Platform': 'Windows PC',
         'Digital service': 'Steam', 'Playtime': '16050', 'Date added': '2025-05-06T09:34:03.000Z'},
        {'section': 'games', 'id': 'g2', 'Game name': 'Cyberpunk 2077', 'Platform': 'Windows PC',
         'Digital service': 'Epic Games', 'Playtime': '0'}],
    'spirited away': [{'section': 'screen', 'id': 's1', 'Title': 'Spirited Away', 'Status': 'Watched'}],
}


class Handler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        params = dict(urllib.parse.parse_qsl(url.query))
        Handler.requests.append(params)
        if url.path != '/api':
            body, status = {'ok': False, 'error': 'NOT_FOUND'}, 404
        elif params.get('view') == 'titles':
            body, status = {'ok': True, 'sections': TITLES}, 200
        elif params.get('view') == 'lookup':
            body, status = {'ok': True, 'results': RECORDS.get(backlog.fold(params.get('q')), [])}, 200
        else:
            body, status = {'ok': False, 'error': 'UNKNOWN_VIEW'}, 400
        data = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class BacklogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        backlog.forget()
        Handler.requests = []

    def test_url_rules(self):
        self.assertEqual(backlog.base_url('https://site.pages.dev/'), 'https://site.pages.dev')
        self.assertEqual(backlog.base_url('https://site.pages.dev/api'), 'https://site.pages.dev')
        self.assertEqual(backlog.base_url('http://localhost:8788'), 'http://localhost:8788')
        self.assertEqual(backlog.base_url('http://site.pages.dev'), '')
        self.assertEqual(backlog.base_url('site.pages.dev'), '')
        validate_config(dict(DEFAULT_CONFIG, backlog_url=''))
        validate_config(dict(DEFAULT_CONFIG, backlog_url='https://site.pages.dev'))
        with self.assertRaises(ValueError):
            validate_config(dict(DEFAULT_CONFIG, backlog_url='ftp://site'))

    def test_fold_matches_site(self):
        self.assertEqual(backlog.fold('Işık: Ağaç!'), 'isik agac')
        self.assertEqual(backlog.fold('Pokémon  Brilliant-Diamond'), 'pokemon brilliant diamond')

    def test_find_titles_prefers_longest_and_skips_short(self):
        known = backlog.titles(self.url)
        self.assertEqual(backlog.find_titles("Cyberpunk 2077'e Steam'de mi sahiptim?", known), ['Cyberpunk 2077'])
        self.assertEqual(backlog.find_titles('Cyberpunk 2077: Phantom Liberty bitti mi?', known),
                         ['Cyberpunk 2077: Phantom Liberty'])
        self.assertEqual(backlog.find_titles('doom ve spirited away', known), ['Spirited Away', 'Doom'])
        self.assertEqual(backlog.find_titles('up 1979 yılında', known), [])  # kisa ve sayisal basliklar atlanir
        self.assertEqual(backlog.find_titles('cyberpunk nedir', known), [])

    def test_titles_are_cached(self):
        backlog.titles(self.url)
        backlog.titles(self.url)
        self.assertEqual(sum(1 for item in Handler.requests if item.get('view') == 'titles'), 1)
        backlog.titles(self.url, force=True)
        self.assertEqual(sum(1 for item in Handler.requests if item.get('view') == 'titles'), 2)

    def test_notes_format_records(self):
        cfg = dict(DEFAULT_CONFIG, backlog_url=self.url)
        text = backlog.notes("Cyberpunk 2077'e Steam'de mi Epic'te mi sahiptim?", cfg, log=QUIET)
        self.assertIn('BACKLOG RECORDS', text)
        self.assertIn('- [game] Game name: Cyberpunk 2077 | Platform: Windows PC | Digital service: Steam | '
                      'Playtime: 267.5 h | Date added: 2025-05-06', text)
        self.assertIn('Digital service: Epic Games | Playtime: 0 h', text)
        self.assertEqual(backlog.notes('merhaba nasılsın', cfg, log=QUIET), '')
        self.assertEqual(backlog.notes('Cyberpunk 2077', dict(cfg, backlog_url=''), log=QUIET), '')

    def test_unreachable_site_is_quiet(self):
        logs = []
        cfg = dict(DEFAULT_CONFIG, backlog_url=self.url + '/missing')
        self.assertEqual(backlog.notes('Cyberpunk 2077', cfg, log=logs.append), '')
        self.assertTrue(logs and 'Backlog' in logs[0])
        self.assertFalse(backlog.check(self.url + '/missing')['ok'])
        self.assertEqual(backlog.check(self.url), {'ok': True, 'message': 'Bağlandı · 7 başlık'})

    def test_assistant_adds_backlog_records_with_previous_question(self):
        class Client:
            messages = None

            def chat_stream(self, messages, **_kwargs):
                Client.messages = messages
                return 'Steam ve Epic Games.', 'stop'

        cfg = dict(DEFAULT_CONFIG, backlog_url=self.url)
        bot = assistant.Assistant(config_provider=lambda: cfg, log=QUIET, snapshot=lambda: ([], ''))
        bot.ask('Cyberpunk 2077 hakkında konuşalım', client=Client())
        bot.ask("Steam'de mi vardı?", client=Client())
        system = Client.messages[0]['content']
        self.assertIn('BACKLOG RECORDS', system)
        self.assertIn('Digital service: Epic Games', system)


if __name__ == '__main__':
    unittest.main()
