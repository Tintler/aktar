"""Kitap Cevir arka ucu (bridge_book); Cevirgec tests/test_bridge.py'den tasindi."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import bridge
from bridge_book import book_section, validate_glossary_rows
from epub_meta import book_info
from test_book_core import make_epub


class FakeClient:
    gate = None

    def __init__(self, cfg, log=print):
        self.cfg = cfg

    def context_length(self):
        return 32768, 'test'

    def generate(self, system, user, max_tokens, require_marker=True, allow_json_fence=False):
        if FakeClient.gate is not None:
            FakeClient.gate.wait(10)
        if 'SOURCE TO TRANSLATE' in user:
            # Kaynagi Turkce bir isaretle geri verir; EPUB yapi denetimleri gecer.
            source = user.split('SOURCE TO TRANSLATE', 1)[1].split(':\n', 1)[1]
            return source.replace('Hello world.', 'Merhaba dünya.')
        if 'Compress only' in system:
            return 'Kısa olay özeti.'
        return '- Bölüm özeti.'


class Recorder:
    def __init__(self):
        self.events = []
        self.cond = threading.Condition()

    def __call__(self, event, data):
        with self.cond:
            self.events.append((event, data))
            self.cond.notify_all()

    def wait_for(self, event, timeout=20):
        deadline = time.time() + timeout
        with self.cond:
            while True:
                found = [data for name, data in self.events if name == event]
                if found:
                    return found[-1]
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise AssertionError(f'{event} olayı gelmedi: {[name for name, _ in self.events]}')
                self.cond.wait(remaining)


class FakeDialogs:
    def __init__(self, file=None, folder=None):
        self.file, self.folder = file, folder

    def open_file(self, _title, _types):
        return self.file

    def open_folder(self, _title):
        return self.folder


class BookBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app_dir = self.root / 'app'
        self.app_dir.mkdir()
        for target in ('app_core.APP_DIR', 'book_core.APP_DIR', 'bridge.APP_DIR'):
            patcher = patch(target, self.app_dir)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.epub = self.root / 'book.epub'
        make_epub(self.epub)
        self.work = self.root / 'work'
        self.events = Recorder()
        self.bridge = bridge.Bridge(emit=self.events, dialogs=FakeDialogs(file=str(self.epub), folder=str(self.work)))
        FakeClient.gate = None

    def tearDown(self):
        FakeClient.gate = None
        thread = self.bridge._bk_thread
        if thread:
            thread.join(10)
        self.temp.cleanup()

    def prepare(self):
        snapshot = self.bridge.book_choose_epub()
        self.assertEqual(snapshot['book']['title'], 'Example')
        self.bridge.book_choose_folder()
        prepared = self.bridge.book_prepare()
        self.assertTrue(prepared['glossary_required'])
        result = self.bridge.book_confirm_glossary([{'source': 'Hello', 'target': 'Merhaba'}])
        self.assertNotIn('error', result)
        return result

    def test_glossary_rows_validation(self):
        self.assertEqual(validate_glossary_rows([{'source': ' A ', 'target': ' B '}, {'source': '', 'target': ''}]),
                         [{'source': 'A', 'target': 'B'}])
        with self.assertRaises(ValueError):
            validate_glossary_rows([{'source': 'A', 'target': ''}])
        with self.assertRaises(ValueError):
            validate_glossary_rows([{'source': 'A', 'target': 'B'}, {'source': 'a', 'target': 'C'}])

    def test_book_info_reads_title_author_and_cover(self):
        info = book_info(self.epub)
        self.assertEqual((info['title'], info['author']), ('Example', 'Author'))
        self.assertTrue(info['cover'].startswith('data:image/png;base64,'))
        self.assertEqual(book_info(self.root / 'missing.epub')['title'], 'missing')

    def test_start_requires_prepared_project(self):
        self.assertIn('error', self.bridge.book_prepare())
        self.assertIn('error', self.bridge.book_start(None))

    def test_full_translation_run_emits_progress_and_finishes(self):
        snapshot = self.prepare()
        self.assertEqual(len([c for c in snapshot['chapters'] if c['type'] == 'chapter']), 2)
        self.assertEqual(json.loads((Path(snapshot['book']['project']) / 'glossary.json').read_text(encoding='utf-8')),
                         [{'source': 'Hello', 'target': 'Merhaba'}])
        with patch('book_core.Client', FakeClient):
            status = self.bridge.book_start(None)
            self.assertEqual(status['runtime'], 'running')
            finished = self.events.wait_for('book_finished')
        self.assertEqual(finished['outcome'], 'done', finished['message'])
        chapters = [c for c in finished['snapshot']['chapters'] if c['type'] == 'chapter']
        self.assertTrue(all(c['kind'] == 'done' for c in chapters), chapters)
        self.assertEqual(finished['snapshot']['status']['progress']['percent'], 100)
        self.assertTrue(finished['snapshot']['book']['output'].endswith('book TR.epub'))
        self.assertTrue(any(name == 'book_status' for name, _ in self.events.events))
        self.assertTrue(any(name == 'book_log' for name, _ in self.events.events))
        preview = self.bridge.book_preview(chapters[0]['filename'])
        self.assertTrue(preview['translated'])
        self.assertIn('Merhaba', preview['translation'])
        self.assertTrue((Path(finished['snapshot']['book']['project']) / 'translation.log').exists())

    def test_pause_and_resume_while_running(self):
        self.prepare()
        FakeClient.gate = threading.Event()
        with patch('book_core.Client', FakeClient):
            self.bridge.book_start(None)
            self.assertEqual(self.bridge.book_control()['runtime'], 'pausing')
            self.assertIn('error', self.bridge.book_choose_epub())
            FakeClient.gate.set()
            deadline = time.time() + 10
            while self.bridge._bk_runtime != 'paused' and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(self.bridge._bk_runtime, 'paused')
            self.assertEqual(self.bridge.book_control()['runtime'], 'running')
            finished = self.events.wait_for('book_finished')
        self.assertEqual(finished['outcome'], 'done', finished['message'])

    def test_stop_ends_worker_after_current_request(self):
        self.prepare()
        FakeClient.gate = threading.Event()
        with patch('book_core.Client', FakeClient):
            self.bridge.book_start(None)
            self.assertEqual(self.bridge.book_stop()['runtime'], 'closing')
            FakeClient.gate.set()
            finished = self.events.wait_for('book_finished')
        self.assertEqual(finished['outcome'], 'stopped')
        self.assertEqual(finished['snapshot']['status']['runtime'], 'idle')

    def test_window_close_asks_then_stops_worker(self):
        self.prepare()
        FakeClient.gate = threading.Event()
        with patch('book_core.Client', FakeClient):
            self.bridge.book_start(None)
            self.assertFalse(self.bridge.request_close(lambda: None))
            self.assertIn('Kitap çevirisi', self.events.wait_for('confirm_close')['reason'])
            FakeClient.gate.set()
            self.bridge._stop_book_for_close()
        self.assertEqual(self.events.wait_for('book_finished')['outcome'], 'stopped')
        self.assertFalse(self.bridge._book_running())

    def test_review_round_trip(self):
        self.prepare()
        book = self.bridge._bk_book
        result = {}
        pending = [{'source': 'Hello', 'suggested_target': 'Selam'},
                   {'source': 'Mage', 'suggested_target': 'Büyücü', 'scope': 'book', 'reason': 'sık geçiyor'}]
        worker = threading.Thread(target=lambda: result.setdefault('values', self.bridge._book_ask_review(book, pending)))
        worker.start()
        review = self.events.wait_for('book_review')
        self.assertEqual([p['source'] for p in review['proposed']], ['Mage'])
        self.assertEqual(review['current'], [{'source': 'Hello', 'target': 'Merhaba'}])
        self.assertTrue(self.bridge.book_submit_review(review['current'] + [{'source': 'Mage', 'target': 'Büyücü'}]))
        worker.join(5)
        self.assertEqual(result['values'], [{'source': 'Hello', 'target': 'Merhaba'}, {'source': 'Mage', 'target': 'Büyücü'}])

    def test_glossary_edit_reports_changes(self):
        self.prepare()
        self.assertEqual(self.bridge.book_save_glossary([{'source': 'Hello', 'target': 'Merhaba'}]),
                         {'changed': False, 'affected': []})
        result = self.bridge.book_save_glossary([{'source': 'Hello', 'target': 'Selam'}])
        self.assertTrue(result['changed'])
        self.assertIn('error', self.bridge.book_save_glossary([{'source': 'Hello', 'target': ''}]))

    def test_book_settings_are_validated_and_merged(self):
        info = self.bridge.get_settings()
        self.assertEqual(info['config']['book']['chunk_chars'], info['book_defaults']['chunk_chars'])
        self.assertNotIn('model', info['book_defaults'])
        self.assertIn('glossary_strict', info['book_defaults'])        # altyazidan ayri kati sozluk
        with patch.object(self.bridge, 'refresh_models'):
            saved = self.bridge.save_settings({'glossary_strict': False, 'book': {'glossary_strict': True}})
        self.assertEqual((saved['config']['glossary_strict'], saved['config']['book']['glossary_strict']), (False, True))
        with patch.object(self.bridge, 'refresh_models'):
            self.assertIn('error', self.bridge.save_settings({'book': {'chunk_chars': 0}}))
            saved = self.bridge.save_settings({'book': {'chunk_chars': '3000', 'epubcheck_enabled': True}})
        self.assertEqual(saved['config']['book']['chunk_chars'], 3000)
        stored = json.loads((self.app_dir / 'config.json').read_text(encoding='utf-8'))
        self.assertEqual((stored['book']['chunk_chars'], stored['book']['epubcheck_enabled']), (3000, True))
        with patch.object(self.bridge, 'refresh_models'):
            saved = self.bridge.save_settings({'batch_cues': 12})   # sayfa "book" gondermese de korunur
        self.assertEqual(saved['config']['book']['chunk_chars'], 3000)
        self.assertEqual(book_section({'chunk_chars': 5}, {'chunk_chars': 9}, locked=('chunk_chars',))['chunk_chars'], 5)

    def test_model_check_uses_probed_model_list(self):
        self.bridge._models = {'state': 'failed', 'names': [], 'message': '', 'model': ''}
        self.assertEqual(set(self.bridge.book_model_check()), {'warn'})
        self.bridge._models = {'state': 'ok', 'names': ['other'], 'message': '', 'model': ''}
        self.assertEqual(set(self.bridge.book_model_check()), {'block'})
        model = __import__('book_core').load_config()['model']
        self.bridge._models = {'state': 'ok', 'names': [model], 'message': '', 'model': model}
        self.assertEqual(self.bridge.book_model_check(), {})

    def test_open_project_validates_folder(self):
        self.assertIn('error', self.bridge.book_open_project(str(self.root)))
        snapshot = self.prepare()
        other = bridge.Bridge(emit=lambda *_: None)
        reopened = other.book_open_project(snapshot['book']['project'])
        self.assertEqual(reopened['book']['epub'], str(self.epub.resolve()))
        self.assertEqual(reopened['status']['phase'], 'Mevcut proje hazır')
        self.assertEqual(other.book_prepare(), {'ok': True, 'glossary_required': False})


if __name__ == '__main__':
    unittest.main()
