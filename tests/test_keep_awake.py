import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import keep_awake


class KeepAwakeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows')
    def test_windows_request_is_held_by_its_own_thread_and_released(self):
        calls = []
        held = threading.Event()

        def state(flags):
            calls.append(flags)
            if flags != keep_awake.ES_CONTINUOUS:
                held.set()
            return 1

        with mock.patch('ctypes.windll.kernel32.SetThreadExecutionState', side_effect=state):
            awake = keep_awake.KeepAwake()
            self.assertTrue(awake.set(True))
            self.assertTrue(held.wait(2))
            self.assertTrue(awake.set(True))   # ikinci istek yeni is parcacigi acmaz
            self.assertFalse(awake.set(False))
            for _ in range(100):
                if len(calls) == 2:
                    break
                threading.Event().wait(0.02)
        self.assertEqual(calls, [keep_awake.ES_CONTINUOUS | keep_awake.ES_SYSTEM_REQUIRED | keep_awake.ES_DISPLAY_REQUIRED,
                                 keep_awake.ES_CONTINUOUS])

    @unittest.skipIf(os.name == 'nt', 'Linux')
    def test_linux_without_systemd_inhibit_does_nothing(self):
        with mock.patch('shutil.which', return_value=None):
            self.assertFalse(keep_awake.KeepAwake().set(True))


if __name__ == '__main__':
    unittest.main()
