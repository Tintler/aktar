import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import tray  # noqa: E402


class LaunchCommandTest(unittest.TestCase):
    def test_source_run_starts_desktop_in_tray(self):
        with mock.patch.object(tray, 'FROZEN', False):
            args = tray.launch_command()
        self.assertEqual(args[1:], [str(ROOT / 'desktop.py'), tray.TRAY_ARG])

    def test_frozen_run_starts_exe_in_tray(self):
        with mock.patch.object(tray, 'FROZEN', True), mock.patch.object(tray.sys, 'executable', r'C:\A b\Aktar.exe'):
            args = tray.launch_command()
            self.assertEqual(args, [r'C:\A b\Aktar.exe', '--tray'])
            self.assertEqual(tray._windows_command(args), r'"C:\A b\Aktar.exe" "--tray"')


@unittest.skipIf(os.name == 'nt', 'Linux autostart dosyasi')
class DesktopFileTest(unittest.TestCase):
    def test_write_and_remove(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': folder}):
            tray.set_autostart(True)
            path = Path(folder) / 'autostart' / 'aktar.desktop'
            self.assertIn('--tray', path.read_text(encoding='utf-8'))
            self.assertTrue(tray.autostart_enabled())
            tray.set_autostart(False)
            self.assertFalse(tray.autostart_enabled())


class BridgeTrayTest(unittest.TestCase):
    def test_state_and_set(self):
        from bridge import Bridge
        bridge = Bridge.__new__(Bridge)
        prefs = {}
        bridge.ui_prefs = lambda: dict(prefs)
        bridge.save_ui_prefs = prefs.update
        synced = []
        bridge._tray_sync = lambda: synced.append(prefs.get('tray'))
        written = []
        with mock.patch.object(tray, 'autostart_enabled', return_value=False), \
                mock.patch.object(tray, 'set_autostart', side_effect=written.append):
            state = bridge.tray_set(enabled=True, autostart=True)
        self.assertEqual(synced, [True])
        self.assertEqual(written, [True])
        self.assertTrue(state['tray'])


if __name__ == '__main__':
    unittest.main()
