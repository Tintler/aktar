"""Soru Sor sekmesi (qa_panel) ve ana penceredeki sekme sozlesme testleri (F45/F46).

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
WINDOW_PATH = ROOT / 'qa_panel.py'


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

    def test_title_bar_switches_between_translate_and_ask_tabs(self):
        main = _class(self.gui, 'MainWindow')
        bar = ast.get_source_segment(self.gui_source, _method(main, '_build_title_bar'))
        self.assertIn("('Çeviri', 'translate'", bar)
        self.assertIn("('Soru Sor', 'ask'", bar)
        self.assertIn("setObjectName('modeSwitch')", bar)
        self.assertIn('self.mode_group.idClicked.connect(self.set_mode)', bar)
        self.assertIn('self.series_group', bar)
        mode = ast.get_source_segment(self.gui_source, _method(main, 'set_mode'))
        self.assertIn('self.series_group.setVisible(mode == MODE_TRANSLATE)', mode)
        self.assertIn('self.pages.setCurrentIndex(mode)', mode)
        build = ast.get_source_segment(self.gui_source, _method(main, '_build'))
        self.assertIn('QStackedWidget()', build)
        self.assertIn('self.qa_drop.select_requested.connect(self.choose_video)', build)
        self.assertIn('QFrame#modeSwitch QPushButton#modeTab:checked', self.gui_source)

    def test_separate_qa_window_and_file_card_button_are_gone(self):
        self.assertFalse((ROOT / 'qa_window.py').exists())
        self.assertNotIn('qa_button', self.gui_source)
        self.assertNotIn('def open_qa', self.gui_source)
        self.assertNotIn('QMainWindow', self.window_source)
        self.assertNotIn('FramelessWindowHint', self.window_source)

    def test_qa_panel_is_imported_lazily(self):
        main = _class(self.gui, 'MainWindow')
        ensure = _method(main, '_ensure_qa_panel')
        imports = [node for node in ast.walk(ensure) if isinstance(node, ast.ImportFrom)]
        self.assertEqual([node.module for node in imports], ['qa_panel'])
        top_level = {node.module for node in self.gui.body if isinstance(node, ast.ImportFrom)}
        self.assertNotIn('qa_panel', top_level, 'QtMultimedia yalnizca gerektiginde yuklenmeli')

    def test_video_change_retires_old_panel_and_close_shuts_down(self):
        main = _class(self.gui, 'MainWindow')
        opened = ast.get_source_segment(self.gui_source, _method(main, 'open_video'))
        self.assertIn('self._retire_qa_panel()', opened)
        retire = ast.get_source_segment(self.gui_source, _method(main, '_retire_qa_panel'))
        self.assertIn('panel.retire()', retire)
        close = ast.get_source_segment(self.gui_source, _method(main, 'closeEvent'))
        self.assertIn('panel.shutdown()', close)
        panel = _class(self.window, 'VideoQAPanel')
        retire = ast.get_source_segment(self.window_source, _method(panel, 'retire'))
        self.assertIn('cancel_event.set()', retire)
        done = ast.get_source_segment(self.window_source, _method(panel, '_job_done'))
        self.assertIn('self.deleteLater()', done)
        hide = ast.get_source_segment(self.window_source, _method(panel, 'hideEvent'))
        self.assertIn('self.player.pause()', hide)

    def test_gui_registers_itself_when_run_as_script(self):
        self.assertIn("sys.modules.setdefault('gui', sys.modules[__name__])", self.gui_source)

    def test_citation_links_seek_the_player(self):
        window = _class(self.window, 'VideoQAPanel')
        chat = ast.get_source_segment(self.window_source, _method(window, '_build_chat'))
        self.assertIn('setOpenLinks(False)', chat)
        self.assertIn('anchorClicked.connect(self.on_anchor)', chat)
        self.assertTrue(_attr_calls(_method(window, 'on_anchor'), 'seek_to'))
        self.assertTrue(_attr_calls(_method(window, 'seek_to'), 'setPosition'))

    def test_model_work_runs_in_threads(self):
        window = _class(self.window, 'VideoQAPanel')
        start = ast.get_source_segment(self.window_source, _method(window, '_start_job'))
        self.assertIn('moveToThread(thread)', start)
        for name in ('PrepareWorker', 'AskWorker'):
            run = ast.get_source_segment(self.window_source, _method(_class(self.window, name), 'run'))
            self.assertIn('self.finished.emit', run)

    def test_chip_lambdas_ignore_clicked_argument(self):
        chips = _method(_class(self.window, 'VideoQAPanel'), '_show_chips')
        lambdas = [node for node in ast.walk(chips) if isinstance(node, ast.Lambda)]
        self.assertTrue(lambdas)
        for node in lambdas:
            self.assertEqual(node.args.args[0].arg, '_checked')

    def test_cc_menu_lists_streams_and_sidecar_files_and_renders_text(self):
        panel = _class(self.window, 'VideoQAPanel')
        player = ast.get_source_segment(self.window_source, _method(panel, '_build_player'))
        self.assertIn('self.cc_button.clicked.connect(self.show_subtitle_menu)', player)
        menu = ast.get_source_segment(self.window_source, _method(panel, 'show_subtitle_menu'))
        for text in ("'Kapalı'", "'Videodaki altyazılar'", "'Video klasöründeki dosyalar'",
                     'subtitle_sources(self.video, self._streams)'):
            self.assertIn(text, menu)
        sources = ast.get_source_segment(
            self.window_source, next(node for node in self.window.body
                                     if isinstance(node, ast.FunctionDef)
                                     and node.name == 'subtitle_sources'))
        self.assertIn("item.get('supported')", sources)
        self.assertIn('sidecar_subtitles(video)', sources)
        refresh = ast.get_source_segment(self.window_source, _method(panel, '_refresh_subtitle'))
        self.assertIn('videoSink().setSubtitleText(text)', refresh)
        select = ast.get_source_segment(self.window_source, _method(panel, 'select_subtitle'))
        self.assertIn('self._start_job(SubtitleLoadWorker(', select)
        setup = ast.get_source_segment(self.window_source, _method(panel, '_setup_player'))
        self.assertIn('setActiveSubtitleTrack(-1)', setup)

    def test_window_icons_exist(self):
        for name in ('ask', 'send', 'volume', 'mute', 'play', 'pause', 'subtitles', 'translate'):
            self.assertTrue((ROOT / 'assets' / 'icons' / f'{name}.svg').exists(), name)


try:
    import qa_panel as qa_window
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
