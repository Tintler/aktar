"""Pencere boyutunu hatirlama (F92): kayitli boyut/konum ekrana sigdirilir."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from window_frame import fit_geometry  # noqa: E402

SCREENS = [(0, 0, 1920, 1080), (1920, 0, 1280, 1024)]
DEFAULT, MINIMUM = (1360, 860), (1000, 640)


class FitGeometryTests(unittest.TestCase):
    def test_saved_window_on_a_connected_screen_is_kept(self):
        saved = {'x': 2000, 'y': 50, 'width': 1100, 'height': 700, 'maximized': True,
                 'bounds': [3000, 75, 1650, 1050]}
        self.assertEqual(fit_geometry(saved, SCREENS, DEFAULT, MINIMUM),
                         {'x': 2000, 'y': 50, 'width': 1100, 'height': 700, 'maximized': True,
                          'bounds': [3000, 75, 1650, 1050]})

    def test_unplugged_monitor_falls_back_to_centred_saved_size(self):
        saved = {'x': 4000, 'y': 50, 'width': 1100, 'height': 700, 'maximized': False}
        self.assertEqual(fit_geometry(saved, SCREENS, DEFAULT, MINIMUM),
                         {'x': None, 'y': None, 'width': 1100, 'height': 700, 'maximized': False,
                          'bounds': None})

    def test_too_large_or_too_small_and_bad_values(self):
        big = fit_geometry({'x': 1920, 'y': 0, 'width': 3000, 'height': 2000}, SCREENS, DEFAULT, MINIMUM)
        self.assertEqual((big['x'], big['y'], big['width'], big['height']), (1920, 0, 1280, 1024))
        small = fit_geometry({'x': 10, 'y': 10, 'width': 200, 'height': 100}, SCREENS, DEFAULT, MINIMUM)
        self.assertEqual((small['width'], small['height']), MINIMUM)
        moved = fit_geometry({'x': 1500, 'y': 900, 'width': 1200, 'height': 800,
                              'bounds': [1500, 900, 1200, 800]}, SCREENS, DEFAULT, MINIMUM)
        self.assertEqual((moved['x'], moved['y'], moved['bounds']), (720, 280, None))  # ekranin icine cekilir
        for bad in (None, 'x', {'width': 'genis'}, {}):
            self.assertEqual(fit_geometry(bad, SCREENS, DEFAULT, MINIMUM),
                             {'width': 1360, 'height': 860, 'x': None, 'y': None, 'maximized': False,
                              'bounds': None})


if __name__ == '__main__':
    unittest.main()
