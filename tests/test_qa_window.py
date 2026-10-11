"""Videoya Soru Sor penceresi sozlesme testleri (F45).

AST testleri PySide6 olmadan calisir; HTML/baglanti yardimcilarinin davranis
testleri PySide6 (QtMultimedia) kuruluysa calisir.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
GUI_PATH = ROOT / 'gui.py'
WINDOW_PATH = ROOT / 'qa_window.py'


def _class(tree, name):
    return next(node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == name)


def _method(class_node, name):
    return next(node for node in class_node.body
                if isinstance(node, ast.FunctionDef) and node.name == name)


def _attr_calls(node, attr):
    return [item for item in ast.walk(node)
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
            and item.func.attr == attr]


class QaWindowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui_source = GUI_PATH.read_text(encoding='utf-8')
        cls.window_source = WINDOW_PATH.read_text(encoding='utf-8')
        cls.gui = ast.parse(cls.gui_source)
        cls.window = ast.parse(cls.window_source)

    def test_main_window_opens_qa_lazily_from_file_card(self):
        main = _class(self.gui, 'MainWindow')
        open_qa = _method(main, 'open_qa')
        imports = [node for node in ast.walk(open_qa) if isinstance(node, ast.ImportFrom)]
        self.assertEqual([node.module for node in imports], ['qa_window'])
        top_level = {node.module for node in self.gui.body if isinstance(node, ast.ImportFrom)}
        self.assertNotIn('qa_window', top_level, 'QtMultimedia yalnizca gerektiginde yuklenmeli')
        card = ast.get_source_segment(self.gui_source, _method(main, '_build_file_card'))
        self.assertIn("HoverIconButton('Videoya Soru Sor')", card)
        self.assertIn('clicked.connect(self.open_qa)', card)

    def test_main_window_close_shuts_down_qa_windows(self):
        close = ast.get_source_segment(self.gui_source,
                                       _method(_class(self.gui, 'MainWindow'), 'closeEvent'))
        self.assertIn('window.shutdown()', close)

    def test_gui_registers_itself_when_run_as_script(self):
        self.assertIn("sys.modules.setdefault('gui', sys.modules[__name__])", self.gui_source)

    def test_window_is_frameless_and_reuses_title_bar(self):
        window = _class(self.window, 'VideoQAWindow')
        init = ast.get_source_segment(self.window_source, _method(window, '__init__'))
        self.assertIn('Qt.FramelessWindowHint', init)
        build = ast.get_source_segment(self.window_source, _method(window, '_build'))
        self.assertIn('TitleBar(self)', build)
        self.assertIn('ResizeEdges(self)', build)
        self.assertIn("setObjectName('appRoot')", build)

    def test_citation_links_seek_the_player(self):
        window = _class(self.window, 'VideoQAWindow')
        chat = ast.get_source_segment(self.window_source, _method(window, '_build_chat'))
        self.assertIn('setOpenLinks(False)', chat)
        self.assertIn('anchorClicked.connect(self.on_anchor)', chat)
        self.assertTrue(_attr_calls(_method(window, 'on_anchor'), 'seek_to'))
        self.assertTrue(_attr_calls(_method(window, 'seek_to'), 'setPosition'))

    def test_model_work_runs_in_threads(self):
        window = _class(self.window, 'VideoQAWindow')
        start = ast.get_source_segment(self.window_source, _method(window, '_start_job'))
        self.assertIn('moveToThread(thread)', start)
        for name in ('PrepareWorker', 'AskWorker'):
            run = ast.get_source_segment(self.window_source, _method(_class(self.window, name), 'run'))
            self.assertIn('self.finished.emit', run)

    def test_chip_lambdas_ignore_clicked_argument(self):
        chips = _method(_class(self.window, 'VideoQAWindow'), '_show_chips')
        lambdas = [node for node in ast.walk(chips) if isinstance(node, ast.Lambda)]
        self.assertTrue(lambdas)
        for node in lambdas:
            self.assertEqual(node.args.args[0].arg, '_checked')

    def test_window_icons_exist(self):
        for name in ('ask', 'send', 'volume', 'mute', 'play', 'pause'):
            self.assertTrue((ROOT / 'assets' / 'icons' / f'{name}.svg').exists(), name)


try:
    import qa_window
except ImportError:  # PySide6/QtMultimedia yok (CI)
    qa_window = None


@unittest.skipIf(qa_window is None, 'PySide6 QtMultimedia kurulu degil')
class QaWindowHelperTests(unittest.TestCase):
    def test_answer_html_escapes_text_and_links_citations(self):
        parts = [('text', '<b>x</b> **kalın**\n- madde '),
                 ('cite', [{'start': 754.0, 'end': None, 'label': '12:34'},
                           {'start': 190.0, 'end': 465.0, 'label': '3:10-7:45'}])]
        value = qa_window.answer_html(parts)
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', value)
        self.assertIn('<b>kalın</b>', value)
        self.assertIn('<br>• madde', value)
        self.assertIn('href="t:754.000"', value)
        self.assertIn('href="t:190.000"', value)
        self.assertIn('3:10-7:45', value)

    def test_chat_html_escapes_user_text(self):
        value = qa_window.chat_html([('user', '<script>'), ('error', 'a & b')])
        self.assertNotIn('<script>', value)
        self.assertIn('a &amp; b', value)

    def test_parse_seek_link(self):
        self.assertEqual(qa_window.parse_seek_link('t:754.500'), 754500)
        self.assertIsNone(qa_window.parse_seek_link('https://example.com'))
        self.assertIsNone(qa_window.parse_seek_link('t:abc'))


if __name__ == '__main__':
    unittest.main()
