"""Toplu hazirlik kuyrugunun dosya kayitlari (F140): is takibinde islenen ve siradaki dosyalar."""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))


import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bridge


class QueueItemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = mock.patch.object(bridge, 'APP_DIR', Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.events = []
        self.bridge = bridge.Bridge(emit=lambda event, data: self.events.append((event, data)))
        paths = [Path(self.temp.name) / name for name in ('a.mkv', 'b.mkv')]
        self.a, self.b = (str(path) for path in paths)
        self.bridge._queue = {'total': 2, 'done': 0, 'items': [
            {'name': 'a.mkv', 'path': self.a, 'state': 'waiting', 'detail': ''},
            {'name': 'b.mkv', 'path': self.b, 'state': 'waiting', 'detail': ''}]}

    def test_active_item_detail_follows_row_progress(self):
        self.bridge._queue_item(self.a, 'active', 'görüntüler okunuyor')
        self.bridge._set_row(self.a, 'Kare 11/57', 'accent')
        items = self.bridge._queue['items']
        self.assertEqual((items[0]['state'], items[0]['detail']), ('active', 'Kare 11/57'))
        self.assertEqual(self.events[-1][0], 'queue')
        count = len(self.events)
        self.bridge._set_row(self.b, 'Sırada', 'dim')            # siradaki dosya kuyruk olayi uretmez
        self.assertEqual((items[1]['detail'], len(self.events)), ('', count + 1))   # yalnizca row_status
        self.bridge._queue_item(self.a, 'done', '')
        self.assertEqual(items[0]['state'], 'done')
        self.assertIsNone(self.bridge._queue_item('yok.mkv'))


if __name__ == '__main__':
    unittest.main()
