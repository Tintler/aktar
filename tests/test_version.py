"""Surum takibi (F155): src/version.py, web/package.json ve CHANGELOG.md ayni surumu gostermeli."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

import version
import version_info


class VersionTests(unittest.TestCase):
    def test_semver(self):
        self.assertRegex(version.VERSION, r'^\d+\.\d+\.\d+$')
        self.assertEqual(len(version.version_tuple()), 3)

    def test_package_json_matches(self):
        package = json.loads((ROOT / 'web' / 'package.json').read_text(encoding='utf-8'))
        self.assertEqual(package['version'], version.VERSION)

    def test_changelog_top_entry_matches(self):
        text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        first = re.search(r'^## (\d+\.\d+\.\d+)', text, re.M)
        self.assertIsNotNone(first)
        self.assertEqual(first.group(1), version.VERSION)

    def test_windows_version_file(self):
        text = version_info.render()
        numbers = version.version_tuple() + (0,)
        self.assertIn(f'filevers={numbers}', text)
        self.assertIn(f"StringStruct('ProductVersion', '{version.VERSION}')", text)

    def test_startup_reports_version(self):
        import bridge
        self.assertIn("'version': VERSION", (ROOT / 'src' / 'bridge.py').read_text(encoding='utf-8'))
        self.assertEqual(bridge.VERSION, version.VERSION)


if __name__ == '__main__':
    unittest.main()
