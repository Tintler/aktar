"""F114 klasor izleme ve F114 kendiliginden ekstre taramasi (bridge_watch, bridge_subscriptions)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import bridge_subscriptions  # noqa: E402
import bridge_watch  # noqa: E402
import library  # noqa: E402
import subscriptions  # noqa: E402


class FakeBridge(bridge_watch.WatchMixin, bridge_subscriptions.SubscriptionsMixin):
    def __init__(self):
        self.events, self.queued, self.logs, self.scans = [], [], [], []
        self._lib_slug = ''
        self._watch_sizes, self._watch_pending = {}, {}
        self._mail_lock = mock.Mock(locked=lambda: False)
        self.running = False

    def _emit(self, name, data):
        self.events.append((name, data))

    def _log(self, message):
        self.logs.append(message)

    def _queue_running(self):
        return self.running

    def _start_queue(self, entries, whisper, summaries, collection, vision=True, ocr_engine='', frames=False,
                     speakers=False):
        self.queued.append(([entry['path'].name for entry in entries], collection[0]))

    def _rescan(self):
        pass

    def _mail_password(self, address=None):
        return ''


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(Path(self.temp.name) / 'store')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = Path(self.temp.name) / 'izlenen'
        self.folder.mkdir()
        (self.folder / 'eski.txt').write_text('eski dosya', encoding='utf-8')
        self.slug, data = library.create_collection('Finans', folders=[str(self.folder)])
        library.scan(data)
        data['watch'] = True
        library.save_collection(data, self.slug)
        self.bridge = FakeBridge()
        plan = {key: [] for key in ('summary', 'index', 'document', 'subtitle', 'vision', 'whisper')}

        def fake_plan(entries, **_kwargs):
            return dict(plan, document=list(entries))

        for target, value in ((library, 'plan'), (bridge_watch.speech, 'available')):
            patcher = mock.patch.object(target, value, fake_plan if value == 'plan' else lambda: (False, ''))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_new_file_is_prepared_once_its_size_settles(self):
        self.bridge._watch_tick()          # ilk tur: bilinen dosyalar
        self.assertEqual(self.bridge.queued, [])
        new = self.folder / 'ekstre.txt'
        new.write_text('yari', encoding='utf-8')
        self.bridge._watch_tick()          # yeni dosya goruldu, boyutu bekleniyor
        self.assertEqual(self.bridge.queued, [])
        new.write_text('yarim kalan kopyalama bitti', encoding='utf-8')
        self.bridge._watch_tick()          # boyut degisti: hala bekleniyor
        self.assertEqual(self.bridge.queued, [])
        self.bridge.running = True
        self.bridge._watch_tick()          # boyut oturdu ama kuyruk dolu: sonraki tura kalir
        self.assertEqual(self.bridge.queued, [])
        self.bridge.running = False
        self.bridge._watch_tick()
        self.assertEqual(self.bridge.queued, [(['ekstre.txt'], self.slug)])
        self.bridge._watch_tick()          # bir kez hazirlanir
        self.assertEqual(len(self.bridge.queued), 1)
        self.assertIn(str(new), library.load_collection(self.slug)['known'])

    def test_files_added_while_closed_and_unwatched_collections(self):
        (self.folder / 'kapaliyken.txt').write_text('uygulama kapaliyken geldi', encoding='utf-8')
        self.bridge._watch_tick()
        self.bridge._watch_tick()
        self.assertEqual(self.bridge.queued, [(['kapaliyken.txt'], self.slug)])
        data = library.load_collection(self.slug)
        data['watch'] = False
        library.save_collection(data, self.slug)
        (self.folder / 'izlenmiyor.txt').write_text('x', encoding='utf-8')
        self.bridge._watch_tick()
        self.bridge._watch_tick()
        self.assertEqual(len(self.bridge.queued), 1)

    def test_auto_scan_only_for_selected_sources_when_enabled(self):
        with mock.patch.object(FakeBridge, 'subs_scan', autospec=True, return_value={}) as scan:
            self.bridge._subs_auto_scan(self.slug)
            scan.assert_not_called()                     # hic tarama yapilmamis: kaynak yok
            subscriptions.save_settings(sources=[self.slug])
            self.bridge._subs_auto_scan('baska')
            scan.assert_not_called()
            self.bridge._subs_auto_scan(self.slug)
            scan.assert_called_once_with(self.bridge, None, auto=True)
            subscriptions.save_settings(auto=False)
            self.bridge._subs_auto_scan(self.slug)
            self.assertEqual(scan.call_count, 1)


if __name__ == '__main__':
    unittest.main()
