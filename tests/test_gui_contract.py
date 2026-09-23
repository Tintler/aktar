"""PySide6 kurulu olmayan CI ortaminda GUI baglanti sozlesmesi regresyonlari."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


GUI_PATH = Path(__file__).resolve().parent.parent / 'gui.py'


def _class(tree, name):
    return next(node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == name)


def _method(class_node, name):
    return next(node for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


class GuiReviewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(GUI_PATH.read_text(encoding='utf-8'))

    def test_review_dialog_accepts_every_keyword_used_by_handler(self):
        dialog = _class(self.tree, 'GlossaryReviewDialog')
        init = _method(dialog, '__init__')
        parameters = {item.arg for item in init.args.args + init.args.kwonlyargs}
        self.assertTrue({'proposed', 'decisions', 'current', 'title', 'has_series'} <= parameters)

        window = _class(self.tree, 'MainWindow')
        handler = _method(window, 'handle_review')
        calls = [node for node in ast.walk(handler)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == 'GlossaryReviewDialog']
        self.assertEqual(len(calls), 1)
        keywords = {item.arg for item in calls[0].keywords}
        self.assertTrue(keywords <= parameters)

    def test_review_handler_always_releases_waiting_worker(self):
        handler = _method(_class(self.tree, 'MainWindow'), 'handle_review')
        guarded = [node for node in ast.walk(handler)
                   if isinstance(node, ast.Try) and node.finalbody]
        self.assertTrue(guarded)
        releases = [node for node in ast.walk(guarded[0].finalbody[0])
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'set']
        self.assertTrue(releases, 'worker review event must be released in finally')

    def test_folder_selection_is_removed(self):
        window = _class(self.tree, 'MainWindow')
        methods = {node.name for node in window.body if isinstance(node, ast.FunctionDef)}
        self.assertNotIn('choose_folder', methods)
        source = GUI_PATH.read_text(encoding='utf-8')
        self.assertNotIn('folder_button', source)
        self.assertNotIn('find_videos', source)

    def test_successful_run_shows_themed_completion_message(self):
        window = _class(self.tree, 'MainWindow')
        self.assertIsNotNone(_method(window, 'complete'))
        finished = _method(window, 'run_finished')
        calls = [node for node in ast.walk(finished)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == 'complete']
        self.assertEqual(len(calls), 1)
        source = GUI_PATH.read_text(encoding='utf-8')
        self.assertIn("button.setObjectName('primary')", source)
        self.assertIn('Çeviri başarıyla tamamlandı.', source)

    def test_settings_are_read_only_during_translation(self):
        init = _method(_class(self.tree, 'SettingsDialog'), '__init__')
        source = ast.get_source_segment(GUI_PATH.read_text(encoding='utf-8'), init)
        self.assertIn('for field in self.fields.values()', source)
        self.assertIn('field.setReadOnly(True)', source)
        self.assertIn('buttons.button(QDialogButtonBox.Save).setEnabled(False)', source)

    def test_settings_save_refreshes_status_pill(self):
        """Ayarlar kaydedilince durum rozeti yeni modele gore guncellenir.

        Eski durum: show_settings yalnizca 'Ayarlar kaydedildi.' yazip rozeti
        hic tazelemiyordu; model ismi ancak uygulama acilista guncelleniyordu."""
        source = GUI_PATH.read_text(encoding='utf-8')
        window = _class(self.tree, 'MainWindow')
        methods = {node.name for node in window.body if isinstance(node, ast.FunctionDef)}
        self.assertIn('_status_text', methods)
        show = ast.get_source_segment(source, _method(window, 'show_settings'))
        self.assertIn('_set_status', show)
        self.assertIn('refresh_loaded_models', show)
        probe = ast.get_source_segment(source, _method(window, 'refresh_loaded_models'))
        self.assertIn('_status_text(cfg)', probe)
        status_text = ast.get_source_segment(source, _method(window, '_status_text'))
        self.assertIn("' · '", status_text)

    def test_primary_ui_labels_use_turkish_characters(self):
        source = GUI_PATH.read_text(encoding='utf-8')
        for label in ('Video Seç', 'Altyazı Akışları', 'Bölüm terimleri...',
                      'Ön analiz yap', 'Çevir', 'Süreklilik', 'Türkçe önerisi'):
            self.assertIn(label, source)
        for obsolete in ("QPushButton('Video Sec...')", "QLabel('Altyazi Akislari')",
                         "QCheckBox('On analiz yap')", "QPushButton('Cevir')",
                         "HoverIconButton('Video Seç...')"):
            self.assertNotIn(obsolete, source)

    def test_theme_palette_is_unchanged(self):
        """F24 arayuz tazelemesi paleti degistirmez; yalnizca turev tonlar eklenir."""
        source = GUI_PATH.read_text(encoding='utf-8')
        for token in ("'bg': '#03080a'", "'chrome': '#080d0f'", "'panel': '#0c1113'",
                      "'border': '#1a2226'", "'panel_alt': '#101719'", "'text': '#e6edee'",
                      "'secondary': '#9aabaf'", "'muted': '#6f8085'", "'accent': '#c8ff00'",
                      "'accent_text': '#0a1200'", "'disabled': '#54666b'",
                      "'drop_border': '#243035'"):
            self.assertIn(token, source)

    def test_fusion_style_is_forced_before_stylesheet(self):
        """Windows yerel stili QSS'in bir kismini yok sayar; Fusion zorunlu."""
        source = GUI_PATH.read_text(encoding='utf-8')
        self.assertIn("app.setStyle('Fusion')", source)
        self.assertLess(source.index("app.setStyle('Fusion')"),
                        source.index('app.setStyleSheet(style)'))

    def test_dock_is_replaced_by_splitter(self):
        source = GUI_PATH.read_text(encoding='utf-8')
        self.assertNotIn('QDockWidget', source)
        self.assertIn('QSplitter(Qt.Vertical)', source)

    def test_completion_uses_modal_and_warnings_stay_modal(self):
        """F37: Basarili sonuc toast degil, 'Tamam' ile kapatilan modal bildirimdir."""
        window = _class(self.tree, 'MainWindow')
        complete = ast.get_source_segment(GUI_PATH.read_text(encoding='utf-8'),
                                          _method(window, 'complete'))
        self.assertNotIn('self.toast.show_message', complete)
        self.assertIn('self._message_box', complete)
        self.assertIn('Çeviri tamamlandı', complete)
        warn = ast.get_source_segment(GUI_PATH.read_text(encoding='utf-8'),
                                      _method(window, 'warn'))
        self.assertIn('_message_box', warn)

    def test_window_is_frameless_with_custom_title_bar(self):
        source = GUI_PATH.read_text(encoding='utf-8')
        init = ast.get_source_segment(source, _method(_class(self.tree, 'MainWindow'), '__init__'))
        self.assertIn('Qt.FramelessWindowHint', init)
        window = _class(self.tree, 'MainWindow')
        bar = _method(window, '_build_title_bar')
        bar_source = ast.get_source_segment(source, bar)
        self.assertIn('startSystemMove', ast.get_source_segment(
            source, _class(self.tree, 'TitleBar')))
        self.assertIn('self._window_button', bar_source)

    def test_title_bar_drag_and_double_click_are_wired(self):
        bar = ast.get_source_segment(
            GUI_PATH.read_text(encoding='utf-8'), _class(self.tree, 'TitleBar'))
        self.assertIn('def mousePressEvent', bar)
        self.assertIn('def mouseDoubleClickEvent', bar)
        self.assertIn('toggle_maximize', bar)

    def test_title_bar_does_not_resize_from_its_bottom_edge(self):
        """Ust barin alt kenarinda istenmeyen 'genisletme' imleci/boyutlandirmasi olmamali.

        Fare seridin alt kenarina geldiginde eski kod startSystemResize(BottomEdge)
        cagirip pencereyi yanlis kenardan buyutuyordu. Artik serit yalnizca ust/sol/sag
        kenardan boyutlandirir; alt kenarda suruklemeye duser."""
        bar = ast.get_source_segment(
            GUI_PATH.read_text(encoding='utf-8'), _class(self.tree, 'TitleBar'))
        self.assertIn('RESIZE_EDGES', bar)
        self.assertIn('Qt.TopEdge | Qt.LeftEdge | Qt.RightEdge', bar)
        self.assertNotIn('Qt.BottomEdge', bar)

    def test_edges_allow_resizing_and_use_system_resize(self):
        source = GUI_PATH.read_text(encoding='utf-8')
        edges = ast.get_source_segment(source, _class(self.tree, 'ResizeEdges'))
        self.assertIn('startSystemResize', edges)
        self.assertIn('def reposition', edges)
        init = ast.get_source_segment(source, _method(_class(self.tree, 'MainWindow'),
                                                      '__init__'))
        self.assertIn('Qt.FramelessWindowHint', init)
        resize = ast.get_source_segment(source, _method(_class(self.tree, 'MainWindow'),
                                                        'resizeEvent'))
        self.assertIn('_edges.reposition()', resize)

    def test_caption_buttons_keep_fixed_size(self):
        """Qt QSS ozgullugu CSS2 gibidir: 'QFrame#customTitleBar QPushButton'
        (1 ID + 2 element) kurali 'QPushButton#winButton'dan gucludur. Dugme
        kurallari da ata seciciyle yazilmazsa padding uygulanip 46x32 siser ve
        ortalama bozulur."""
        source = GUI_PATH.read_text(encoding='utf-8')
        block = source.split('QFrame#customTitleBar QPushButton#winButton,')[1].split('}}')[0]
        for token in ('max-width:46px', 'max-height:32px', 'padding:0'):
            self.assertIn(token, block)
        button = ast.get_source_segment(source, _class(self.tree, 'CaptionButton'))
        self.assertIn('setFixedSize(46, 32)', button)

    def test_caption_buttons_are_painted_and_use_accent_glyph(self):
        source = GUI_PATH.read_text(encoding='utf-8')
        button = ast.get_source_segment(source, _class(self.tree, 'CaptionButton'))
        self.assertIn('def paintEvent', button)
        self.assertIn("THEME['accent']", button)
        # Pencere dugmelerinin hover zemini digerleriyle ayni olmali; arkadaki
        # yesil dolgu kaldirildi, yalnizca simge yesile doner.
        self.assertIn('QPushButton#winButton:hover', source)
        self.assertIn('QPushButton#winClose:hover', source)
        block = source.split('QFrame#customTitleBar QPushButton#winButton:hover,')[1].split('}}')[0]
        self.assertIn('background:#1a2530', block)
        self.assertNotIn('background:{accent}', block)
        self.assertNotIn('#c42b1c', source)

    def test_clickable_items_highlight_in_accent_on_hover(self):
        """Tiklanabilir ogeler ve tablo kayitlari hover'da yesil (accent) metin."""
        source = GUI_PATH.read_text(encoding='utf-8')
        self.assertIn('QTableWidget::item:hover {{ color:{accent}; }}', source)
        self.assertIn('QPushButton:hover {{ background:#1a2530; color:{accent}; }}', source)
        self.assertIn('def highlight_rows', source)
        self.assertIn('HoverHighlightDelegate', source)
        # Hover satiri delegate ile butun sutunlarda accent'e doner.
        delegate = ast.get_source_segment(source, _class(self.tree, 'HoverHighlightDelegate'))
        self.assertIn('QPalette.Text', delegate)
        self.assertIn("THEME['accent']", delegate)
        # Ikon tabanli dugmelerin ikonlari yalnizca hover'da yesile doner. Eski
        # QIcon.Active yontemi kaldirildi: Qt Active modu State_HasFocus'ta da
        # cizdigi icin tiklamadan sonra ikon yesil kaliyordu (focus dugmede
        # kaldigi surece). Yesil varyant HoverIconButton ile hover eventlerinde
        # acikca set edilir.
        self.assertIn('class HoverIconButton', source)
        self.assertIn('def setTintedIcon', source)
        self.assertIn('def setHoverIcon', source)
        self.assertNotIn('QIcon.Active', source)
        self.assertNotIn('addPixmap', source)
        self.assertNotIn('_icon_with_accent_hover', source)

    def test_dropdown_combo_places_popup_below_the_field(self):
        """Seri/dropdown popup'u combo'nun altina acilmali ve icerigi sigdirmali.

        Qt 6.10 popup'u secili ogemi combo ile ayni cizgiye hizalayip ustten
        aciyordu; seri menu combo'nun ustune biniyor ve son ogem kesiliyordu
        ('kisik' acilma sikayeti). DropdownCombo popup'u acikca alttadir."""
        source = GUI_PATH.read_text(encoding='utf-8')
        self.assertIn('class DropdownCombo(QComboBox)', source)
        popup = ast.get_source_segment(source,
                                       _method(_class(self.tree, 'DropdownCombo'),
                                               'showPopup'))
        self.assertIn('super().showPopup()', popup)
        self.assertIn('mapToGlobal', popup)
        self.assertIn('container.setGeometry', popup)
        self.assertIn('MAX_VISIBLE_ROWS', popup)
        # Uygulamadaki tum combolar bu siniftan turetilmelidir.
        for fragment in ('self.series_combo = DropdownCombo()',
                         'model = DropdownCombo()',
                         'scope = DropdownCombo()'):
            self.assertIn(fragment, source)
        self.assertNotIn('= QComboBox()', source)

    def test_tables_use_hover_highlight_rows(self):
        source = GUI_PATH.read_text(encoding='utf-8')
        self.assertGreaterEqual(source.count('highlight_rows('), 5)  # tanim + 4 cagri

    def test_root_frame_border_is_applied(self):
        source = GUI_PATH.read_text(encoding='utf-8')
        self.assertIn("setObjectName('appRoot')", source)
        self.assertIn('QFrame#appRoot {{ background:{bg}; border:1px solid {frame_border}; }}',
                      source)
        self.assertIn("'frame_border'", source)

    def test_empty_state_toggles_file_and_stream_cards(self):
        window = _class(self.tree, 'MainWindow')
        source = ast.get_source_segment(GUI_PATH.read_text(encoding='utf-8'),
                                        _method(window, '_show_empty_state'))
        for call in ('self.drop.setVisible', 'self.file_card.setVisible',
                     'self.stream_card.setVisible'):
            self.assertIn(call, source)

    def test_drop_area_is_minimal_and_icon_opens_video_pick(self):
        """F41: Surukle-birak alaninda yalnizca ikon + 'Videoyu buraya birakin'
        kalir (ipucu/uzanti rozetleri/not kaldirildi); ikon tiklaninca 'Video Sec'
        akisi (choose_video) tetiklenir ve el imleci gosterilir."""
        source = GUI_PATH.read_text(encoding='utf-8')
        area = ast.get_source_segment(source, _class(self.tree, 'DropArea'))
        self.assertIn('Videoyu buraya bırakın', area)
        self.assertIn('select_requested = Signal()', area)
        self.assertIn('self.mark.clicked.connect(self.select_requested)', area)
        self.assertIn('class ClickableLabel', source)
        for gone in ('veya araç çubuğundan', 'Kaynak dosya salt-okunur',
                     'extBadge', 'dropHint', 'dropNote'):
            self.assertNotIn(gone, source)
        build = ast.get_source_segment(source, _method(_class(self.tree, 'MainWindow'), '_build'))
        self.assertIn('self.drop.select_requested.connect(self.choose_video)', build)

    def test_icon_assets_exist_for_every_tinted_icon(self):
        source = GUI_PATH.read_text(encoding='utf-8')
        tree = ast.parse(source)
        icons = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args
                    and isinstance(node.args[0], ast.Constant)):
                continue
            # tinted_icon('name', ...) ve button.setTintedIcon('name', ...)
            if (isinstance(node.func, ast.Name) and node.func.id == 'tinted_icon') or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'setTintedIcon'):
                icons.add(node.args[0].value)
        folder = GUI_PATH.parent / 'assets' / 'icons'
        for name in icons:
            self.assertTrue((folder / (name + '.svg')).exists(),
                            'eksik ikon varligi: ' + name)


if __name__ == '__main__':
    unittest.main()
