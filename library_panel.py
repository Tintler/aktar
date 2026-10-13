"""Kutuphane sayfasi (F55): koleksiyonlar, dosya tablosu, oynatici + soru sor.

Ana penceredeki "Kutuphane" sekmesinin icerigidir. Duzen:
  - Bos durum: koleksiyon yokken "Klasor veya dosya birak" + [Klasor sec] [Dosya sec]
  - Liste: sol koleksiyonlar + kaynak klasorler | orta dosya tablosu | sag
    koleksiyon sohbeti (F58'e kadar pasif)
  - Ayrinti: dosyaya cift tiklaninca geri dugmesi + qa_panel.VideoQAPanel

Koleksiyon mantigi library.py'dedir (Qt'siz). Tarama ve durum okuma arka plan
thread'inde yapilir (buyuk klasorlerde arayuz donmasin). Kaynak dosyalar
SALT-OKUNUR: "Koleksiyondan cikar" yalnizca kaydi degistirir.
"""
from __future__ import annotations

import copy
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

import library
import qa
import speech
from app_core import Client, GracefulStop, load_config
from gui import (THEME, HoverIconButton, ToggleSwitch, _alive, card, highlight_rows,
                 tinted_icon, window_icon)

PAGE_EMPTY, PAGE_LIST, PAGE_DETAIL = 0, 1, 2
REPEATED_ERROR_LIMIT = 3  # ust uste ayni hata: kuyruk durur
WARN = '#f0b44c'  # onay bekleyen (Whisper) durumlar; tasarim taslagindaki amber
KIND_LABELS = {'video': 'Video'}
KIND_ICONS = {'video': 'video'}
STATUS_TEXT = {'ready': 'Hazır', 'transcript': 'Metin hazır', 'pending': 'Bekliyor',
               'no_subtitle': 'Altyazı yok · Whisper bekliyor', 'missing': 'Bulunamadı'}
META_TEXT = {'ready': 'hazır', 'transcript': 'metin hazır', 'pending': 'bekliyor',
             'no_subtitle': 'Whisper bekliyor', 'missing': 'bulunamadı'}
STATUS_COLOR = {'ready': THEME['text'], 'transcript': THEME['secondary'],
                'pending': THEME['muted'], 'no_subtitle': WARN, 'missing': THEME['disabled']}

LIBRARY_STYLE = """
QFrame#libSide {{ background:{chrome}; border:0; border-right:1px solid {border}; }}
QFrame#libChat {{ background:{chrome}; border:0; border-left:1px solid {border}; }}
QLabel#libSection {{ color:{muted}; font-size:11px; font-weight:600; letter-spacing:0.7px; }}
QLabel#libTitle {{ font-size:20px; font-weight:600; }}
QLabel#libDropTitle {{ font-size:20px; font-weight:600; }}
QLabel#libChatTitle {{ font-size:14px; font-weight:600; }}
QLabel#libChatNote {{ color:{secondary}; font-size:12px; }}
QListWidget#libList {{ background:transparent; border:0; outline:none; }}
QListWidget#libList::item {{ color:{secondary}; padding:8px 10px; border-radius:8px; }}
QListWidget#libList::item:hover {{ background:{panel}; color:{accent}; }}
QListWidget#libList::item:selected {{ background:{panel_alt}; color:{text}; }}
QListWidget#libFolders {{ background:transparent; border:0; outline:none; }}
QListWidget#libFolders::item {{ color:{secondary}; padding:7px 9px; margin-bottom:6px;
    border:1px solid {border}; border-radius:8px; font-family:'{mono_font}'; font-size:11px; }}
QListWidget#libFolders::item:hover {{ color:{accent}; }}
QPushButton#libChip {{ background:{panel}; border:1px solid {border}; color:{secondary};
    border-radius:14px; padding:5px 12px; font-size:12px; }}
QPushButton#libChip:hover {{ color:{accent}; }}
QPushButton#libChip:checked {{ background:{panel_alt}; border-color:{accent}; color:{text}; }}
QPushButton#libNew {{ background:transparent; border:0; color:{muted}; text-align:left;
    padding:8px 10px; }}
QPushButton#libNew:hover {{ background:{panel}; color:{accent}; }}
QPushButton#libBack {{ background:transparent; border:0; color:{secondary}; padding:6px 10px; }}
QPushButton#libBack:hover {{ background:{panel_alt}; color:{accent}; }}
QFrame#libDrop {{ background:{panel}; border:1.5px dashed {drop_border}; border-radius:16px; }}
"""


def format_duration(seconds):
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'


def format_size(path):
    try:
        size = Path(path).stat().st_size
    except OSError:
        return '—'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit in ('B', 'KB') else f'{size:.1f} {unit}'
        size /= 1024
    return '—'


def file_filter():
    patterns = ' '.join('*' + suffix for suffix in library.supported_suffixes())
    return f'Desteklenen dosyalar ({patterns})'


def _dropped_paths(event):
    return [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]


class DropFrame(QFrame):
    """Klasor/dosya birakilabilen cerceve; birakilan yollari tek sinyalle verir."""

    dropped = Signal(list)

    def __init__(self, object_name='', parent=None):
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = _dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self.dropped.emit(paths)


class PrepareDialog(QDialog):
    """'Hepsini hazirla' onayi: videolari yoklar, kaynaga gore sayar, Whisper iznini sorar.

    Yoklama (ffprobe) arka plan thread'indedir ve onbellege yazilir; pencere
    kapatilirsa durur. Whisper bu pencerede acikca onaylanmadikca calismaz."""

    planned = Signal(object)        # library.plan sonucu
    plan_progress = Signal(int, int)

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Aktar - Toplu hazırlık')
        self.setWindowIcon(window_icon())
        self.setMinimumWidth(560)
        self.result_plan = None
        self._cancel = threading.Event()
        self.whisper_ready, whisper_hint = speech.available()
        cfg = load_config()

        column = QVBoxLayout(self)
        column.setContentsMargins(24, 22, 24, 20)
        column.setSpacing(14)
        videos = sum(1 for entry in entries if not entry['missing'] and entry['kind'] == 'video')
        title = QLabel(f'{videos} videoyu hazırla')
        title.setObjectName('libDropTitle')
        column.addWidget(title)
        intro = QLabel('Her videonun transkripti çıkarılır ve aranabilir indekse eklenir; sonra '
                       'soru-cevapta beklemeden kullanılır. İstediğin an durdurabilirsin, kaldığı '
                       'yerden devam eder.')
        intro.setObjectName('libChatNote')
        intro.setWordWrap(True)
        column.addWidget(intro)

        self.counts_card, counts = card(spacing=0, margins=(0, 0, 0, 0), shadow=False)
        self.count_labels = {}
        for key, icon, color, text, hint in (
                ('ready', 'check', THEME['accent'], 'Zaten hazır', 'Önbellekten gelir, tekrar işlenmez'),
                ('index', 'terms', THEME['secondary'], 'Yalnızca indekslenecek',
                 'Transkript hazır; embedding ile aranabilir yapılır'),
                ('subtitle', 'subtitles', THEME['secondary'], 'Gömülü altyazıdan',
                 'Hızlı · şarkı/yazı izleri atlanır, en uygun akış seçilir'),
                ('whisper', 'audio', WARN, 'Altyazı yok → Whisper', '')):
            row = QHBoxLayout()
            row.setContentsMargins(14, 11, 14, 11)
            row.setSpacing(12)
            mark = QLabel()
            mark.setPixmap(tinted_icon(icon, color, 16).pixmap(16, 16))
            row.addWidget(mark)
            texts = QVBoxLayout()
            texts.setSpacing(2)
            name = QLabel(text)
            texts.addWidget(name)
            detail = QLabel(hint)
            detail.setObjectName('hint')
            texts.addWidget(detail)
            row.addLayout(texts, 1)
            value = QLabel('…')
            value.setObjectName('progressValue')
            row.addWidget(value)
            self.count_labels[key] = (value, detail)
            counts.addLayout(row)
        column.addWidget(self.counts_card)

        self.plan_bar = QProgressBar()
        self.plan_bar.setTextVisible(False)
        column.addWidget(self.plan_bar)
        self.plan_label = QLabel('Videolar yoklanıyor…')
        self.plan_label.setObjectName('hint')
        column.addWidget(self.plan_label)

        self.whisper_check = ToggleSwitch('Altyazısız videolarda Whisper kullan')
        self.whisper_check.setChecked(self.whisper_ready)
        self.whisper_check.setEnabled(self.whisper_ready)
        self.whisper_check.toggled.connect(self._update_start)
        column.addWidget(self.whisper_check)
        embedding = str(cfg.get('embedding_model', '')).strip()
        self.index_label = QLabel(
            f'İndeks: {embedding} (LM Studio). Transkriptler parçalara bölünüp aranabilir yapılır.'
            if embedding else 'Embedding modeli seçilmedi: yalnızca transkript çıkarılır, '
                              'koleksiyona soru sormak için indeks gerekir (Ayarlar → Kütüphane indeksi).')
        self.index_label.setObjectName('hint')
        self.index_label.setWordWrap(True)
        if not embedding:
            self.index_label.setStyleSheet('color:%s;' % WARN)
        column.addWidget(self.index_label)
        model = QLabel(f'Whisper: {cfg["whisper_model"]} · cihaz: {cfg["whisper_device"]} '
                       '(Ayarlar\'dan değiştirilir). Kapalıysa bu videolar atlanır.'
                       if self.whisper_ready else whisper_hint)
        model.setObjectName('hint')
        model.setWordWrap(True)
        column.addWidget(model)
        order = QLabel('Sıra: önce altyazılı videolar, sonra Whisper. Whisper bir videoyu '
                       'bitirmeden duraklamaz; durdurunca yarım kalan video baştan yapılır.')
        order.setObjectName('hint')
        order.setWordWrap(True)
        column.addWidget(order)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton('İptal')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.start_button = QPushButton('Hazırlamayı başlat')
        self.start_button.setObjectName('primary')
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.accept)
        buttons.addWidget(self.start_button)
        column.addLayout(buttons)

        self.planned.connect(self._on_planned)
        self.plan_progress.connect(self._on_progress)
        threading.Thread(target=self._plan, args=(list(entries),),
                         name='aktar-library-plan', daemon=True).start()

    def _plan(self, entries):
        try:
            result = library.plan(entries, progress=self.plan_progress.emit,
                                  cancelled=self._cancel.is_set)
        except Exception as error:  # yoklama hatasi pencereyi kilitlemesin
            result = {'ready': [], 'index': [], 'subtitle': [], 'whisper': [],
                      'whisper_seconds': 0.0,
                      'failed': [(None, str(error))]}
        if not self._cancel.is_set():
            self.planned.emit(result)

    def _on_progress(self, done, total):
        self.plan_bar.setMaximum(max(1, total))
        self.plan_bar.setValue(done)
        self.plan_label.setText(f'Videolar yoklanıyor {done}/{total}…')

    def _on_planned(self, result):
        self.result_plan = result
        self.plan_bar.hide()
        failed = result['failed']
        self.plan_label.setText(f'{len(failed)} video okunamadı ve atlanacak: '
                                + ', '.join(entry['path'].name for entry, _error in failed[:3]
                                            if entry is not None)
                                if failed else '')
        self.plan_label.setVisible(bool(failed))
        for key in ('ready', 'index', 'subtitle', 'whisper'):
            self.count_labels[key][0].setText(str(len(result[key])))
        seconds = result['whisper_seconds']
        self.count_labels['whisper'][1].setText(
            f'Toplam {format_duration(seconds)} ses · süre GPU\'ya bağlı' if seconds
            else 'Konuşma sesten metne çevrilir')
        self._update_start()

    def _update_start(self):
        if self.result_plan is None:
            return
        count = len(self.queue())
        self.start_button.setText(f'Hazırlamayı başlat ({count} video)')
        self.start_button.setEnabled(count > 0)

    def allow_whisper(self):
        return self.whisper_ready and self.whisper_check.isChecked()

    def queue(self):
        """Islenecek sira: once yalnizca indeks ve altyazilar (hizli), sonra Whisper."""
        if self.result_plan is None:
            return []
        return (list(self.result_plan['index']) + list(self.result_plan['subtitle'])
                + (list(self.result_plan['whisper']) if self.allow_whisper() else []))

    def done(self, code):
        self._cancel.set()
        super().done(code)


class QueueWorker(QObject):
    """Toplu transkript isi: siradaki videolari library.transcribe ile isler."""

    started = Signal(int, str, str)    # (sira, yol, adim)
    progress = Signal(int, int)        # Whisper: (islenen saniye, toplam saniye)
    item_done = Signal(str, str, str)  # (yol, sonuc, hata)
    log = Signal(str)
    finished = Signal(int, int, bool)  # (tamamlanan, hatali, durduruldu)

    def __init__(self, entries, allow_whisper):
        super().__init__()
        self.entries = entries
        self.allow_whisper = allow_whisper
        self.cancel_event = threading.Event()
        self.resume_event = threading.Event()
        self.resume_event.set()

    def _wait_if_paused(self):
        while not self.resume_event.wait(0.2):
            if self.cancel_event.is_set():
                return

    @Slot()
    def run(self):
        done = failed = 0
        last_error, repeats = '', 0
        cfg = load_config()
        client = Client(cfg, log=self.log.emit)  # indeksleme icin tek istemci
        for index, entry in enumerate(self.entries):
            self._wait_if_paused()
            if self.cancel_event.is_set():
                break
            path = str(entry['path'])
            log = (lambda message, name=entry['path'].name: self.log.emit(f'[{name}] {message}'))
            probed = library.cached_probe(entry['path'])
            whisper = probed is not None and not qa.pick_subtitle_stream(probed['subtitles'])
            has_text = bool(qa.cached_sessions(entry['path']))
            self.started.emit(index, path, 'indeksleniyor' if has_text
                              else 'Whisper ile transkript' if whisper else 'altyazıdan metin')
            try:
                outcome = library.transcribe(entry, cfg, self.allow_whisper, log=log,
                                             progress=self.progress.emit,
                                             cancelled=self.cancel_event.is_set)
                if outcome != 'skipped' and str(cfg.get('embedding_model', '')).strip():
                    if not has_text:
                        self.started.emit(index, path, 'indeksleniyor')
                    library.index(entry, cfg, log=log, cancelled=self.cancel_event.is_set,
                                  client=client)
            except GracefulStop:
                break
            except Exception as error:  # tek videonun hatasi kuyrugu durdurmasin
                failed += 1
                self.item_done.emit(path, 'failed', str(error))
                # Ayni hata ust uste tekrarlaniyorsa (LM Studio kapali vb.) bosuna surdurme.
                repeats = repeats + 1 if str(error) == last_error else 1
                last_error = str(error)
                if repeats >= REPEATED_ERROR_LIMIT:
                    self.log.emit(f'Aynı hata {repeats} kez üst üste: kuyruk durduruldu. {error}')
                    break
                continue
            repeats = 0
            done += 1
            self.item_done.emit(path, outcome, '')
        self.finished.emit(done, failed, self.cancel_event.is_set())


class LibraryPanel(QWidget):
    """Kutuphane sekmesi: koleksiyon secimi, dosya tablosu ve oynatici ayrintisi."""

    translate_requested = Signal(str)
    scanned = Signal(int, str, object, object, object, bool)  # tarama thread'inden

    def __init__(self, log=None, warn=None, parent=None):
        super().__init__(parent)
        self._log = log or (lambda _message: None)
        self._warn = warn or (lambda _message: None)
        self.slug = ''
        self.data = None
        self.entries = []
        self.infos = []
        self._generation = 0
        self.qa_panel = None
        self._qa_retired = []  # geri donulunce/baska video acilinca isi suren eski paneller
        self._rows = {}        # dosya anahtari -> tablo satiri
        self._queue = None     # (thread, worker): toplu transkript isi
        self._queue_total = 0
        self._queue_name = ''
        self.setStyleSheet(LIBRARY_STYLE.format(**THEME))
        self.scanned.connect(self._scan_finished)
        self._build()
        self.reload()

    # --- kurulum -------------------------------------------------------------
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        self.pages.addWidget(self._build_empty())
        self.pages.addWidget(self._build_list())
        self.pages.addWidget(self._build_detail())

    def _build_empty(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.addStretch(1)
        self.empty_drop = DropFrame('libDrop')
        self.empty_drop.setFixedSize(720, 400)
        self.empty_drop.dropped.connect(self.add_paths)
        column = QVBoxLayout(self.empty_drop)
        column.setSpacing(22)
        column.addStretch(1)
        mark = QLabel()
        mark.setFixedSize(64, 64)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet('background:%s; border-radius:16px;' % THEME['panel_alt'])
        mark.setPixmap(tinted_icon('folder-plus', THEME['accent'], 30).pixmap(30, 30))
        column.addWidget(mark, 0, Qt.AlignHCenter)
        title = QLabel('Klasör veya dosya bırak')
        title.setObjectName('libDropTitle')
        column.addWidget(title, 0, Qt.AlignHCenter)
        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.addStretch(1)
        folder = QPushButton('Klasör seç')
        folder.setObjectName('primary')
        folder.clicked.connect(self.choose_folder)
        buttons.addWidget(folder)
        files = QPushButton('Dosya seç')
        files.clicked.connect(self.choose_files)
        buttons.addWidget(files)
        buttons.addStretch(1)
        column.addLayout(buttons)
        kinds = QLabel(' · '.join(KIND_LABELS.values()))
        kinds.setObjectName('hint')
        column.addWidget(kinds, 0, Qt.AlignHCenter)
        column.addStretch(1)
        outer.addWidget(self.empty_drop, 0, Qt.AlignHCenter)
        outer.addStretch(1)
        return page

    def _build_list(self):
        page = DropFrame()
        page.dropped.connect(self.add_paths)
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_sidebar())
        row.addWidget(self._build_center(), 1)
        row.addWidget(self._build_chat())
        return page

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName('libSide')
        side.setFixedWidth(236)
        column = QVBoxLayout(side)
        column.setContentsMargins(12, 18, 12, 14)
        column.setSpacing(6)
        label = QLabel('KOLEKSİYONLAR')
        label.setObjectName('libSection')
        label.setContentsMargins(10, 0, 0, 4)
        column.addWidget(label)
        self.collection_list = QListWidget()
        self.collection_list.setObjectName('libList')
        self.collection_list.setIconSize(QSize(16, 16))
        self.collection_list.currentItemChanged.connect(self._on_collection_changed)
        self.collection_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.collection_list.customContextMenuRequested.connect(self._collection_menu)
        column.addWidget(self.collection_list, 1)
        new = HoverIconButton('Yeni koleksiyon')
        new.setObjectName('libNew')
        new.setTintedIcon('plus', THEME['muted'])
        new.clicked.connect(self.new_collection)
        column.addWidget(new)
        label = QLabel('KAYNAK KLASÖRLER')
        label.setObjectName('libSection')
        label.setContentsMargins(10, 12, 0, 4)
        column.addWidget(label)
        self.folder_list = QListWidget()
        self.folder_list.setObjectName('libFolders')
        self.folder_list.setFixedHeight(150)
        self.folder_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.folder_list.setTextElideMode(Qt.ElideMiddle)
        self.folder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self._folder_menu)
        column.addWidget(self.folder_list)
        return side

    def _build_center(self):
        center = QWidget()
        column = QVBoxLayout(center)
        column.setContentsMargins(20, 20, 20, 16)
        column.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.title_label = QLabel('')
        self.title_label.setObjectName('libTitle')
        titles.addWidget(self.title_label)
        self.meta_label = QLabel('')
        self.meta_label.setObjectName('hint')
        titles.addWidget(self.meta_label)
        head.addLayout(titles, 1)
        add_folder = HoverIconButton('Klasör ekle')
        add_folder.setTintedIcon('folder-plus', THEME['secondary'])
        add_folder.clicked.connect(self.choose_folder)
        head.addWidget(add_folder, 0, Qt.AlignBottom)
        add_files = HoverIconButton('Dosya ekle')
        add_files.setTintedIcon('plus', THEME['secondary'])
        add_files.clicked.connect(self.choose_files)
        head.addWidget(add_files, 0, Qt.AlignBottom)
        self.prepare_button = QPushButton('Hepsini hazırla')
        self.prepare_button.setObjectName('primary')
        self.prepare_button.setToolTip('Koleksiyondaki tüm videoların transkriptini çıkarır '
                                       '(altyazıdan; altyazısızlarda onayla Whisper).')
        self.prepare_button.clicked.connect(self.prepare_all)
        head.addWidget(self.prepare_button, 0, Qt.AlignBottom)
        column.addLayout(head)
        column.addWidget(self._build_queue_strip())

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Dosya adında ara…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        tools.addWidget(self.search, 1)
        self.chip_row = QHBoxLayout()
        self.chip_row.setSpacing(6)
        tools.addLayout(self.chip_row)
        self.chips = QButtonGroup(self)
        self.chips.setExclusive(True)
        self.chips.idClicked.connect(lambda _id: self._apply_filter())
        column.addLayout(tools)

        frame, inner = card(spacing=0, margins=(0, 0, 0, 0), shadow=False)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['', 'Dosya', 'Klasör', 'Uzunluk',
                                              'Metin kaynağı', 'Durum'])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 44)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 170)
        for index in (3, 4, 5):
            header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(THEME['row_height'])
        self.table.setShowGrid(False)
        highlight_rows(self.table)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setIconSize(QSize(16, 16))
        self.table.cellDoubleClicked.connect(lambda row, _column: self.open_row(row))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        inner.addWidget(self.table, 1)
        foot = QLabel('Çift tıkla: oynatıcı ve soru sor · Sağ tık: altyazı çevir, '
                      'konumu aç, koleksiyondan çıkar')
        foot.setObjectName('hint')
        foot.setContentsMargins(14, 8, 14, 9)
        inner.addWidget(foot)
        column.addWidget(frame, 1)
        return center

    def _build_queue_strip(self):
        """Toplu hazirlik seridi: '<n>/<toplam> · dosya — adim', ilerleme, duraklat/durdur."""
        self.queue_strip, row = card(spacing=14, margins=(14, 10, 14, 10), horizontal=True,
                                     shadow=False)
        texts = QVBoxLayout()
        texts.setSpacing(7)
        self.queue_label = QLabel('')
        texts.addWidget(self.queue_label)
        bar_row = QHBoxLayout()
        bar_row.setSpacing(10)
        self.queue_bar = QProgressBar()
        self.queue_bar.setTextVisible(False)
        bar_row.addWidget(self.queue_bar, 1)
        self.queue_value = QLabel('')
        self.queue_value.setObjectName('progressValue')
        bar_row.addWidget(self.queue_value)
        texts.addLayout(bar_row)
        row.addLayout(texts, 1)
        self.queue_pause = HoverIconButton('')
        self.queue_pause.setObjectName('iconOnly')
        self.queue_pause.setTintedIcon('pause', THEME['text'])
        self.queue_pause.setToolTip('Duraklat (sıradaki dosyadan önce)')
        self.queue_pause.clicked.connect(self.toggle_queue_pause)
        row.addWidget(self.queue_pause)
        self.queue_stop = HoverIconButton('')
        self.queue_stop.setObjectName('iconOnly')
        self.queue_stop.setTintedIcon('stop', THEME['text'])
        self.queue_stop.setToolTip('Durdur')
        self.queue_stop.clicked.connect(self.stop_queue)
        row.addWidget(self.queue_stop)
        self.queue_strip.hide()
        return self.queue_strip

    def _build_chat(self):
        chat = QFrame()
        chat.setObjectName('libChat')
        chat.setFixedWidth(400)
        column = QVBoxLayout(chat)
        column.setContentsMargins(18, 16, 18, 16)
        column.setSpacing(12)
        title = QLabel('Koleksiyona sor')
        title.setObjectName('libChatTitle')
        column.addWidget(title)
        note = QLabel('Tüm dosyalara birden soru sorma, dosyalar toplu hazırlandıktan sonra '
                      'burada açılacak.\n\nŞimdilik bir videoya çift tıklayıp o video '
                      'hakkında soru sorabilirsiniz.')
        note.setObjectName('libChatNote')
        note.setWordWrap(True)
        column.addWidget(note)
        column.addStretch(1)
        ask = QLineEdit()
        ask.setPlaceholderText('Tüm dosyalara sor…')
        ask.setEnabled(False)
        column.addWidget(ask)
        return chat

    def _build_detail(self):
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 8, 0, 0)
        column.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 0, 16, 0)
        self.back_button = HoverIconButton('')
        self.back_button.setObjectName('libBack')
        self.back_button.setTintedIcon('back', THEME['secondary'])
        self.back_button.clicked.connect(self.close_detail)
        bar.addWidget(self.back_button)
        self.detail_title = QLabel('')
        self.detail_title.setObjectName('cardTitle')
        bar.addWidget(self.detail_title, 1)
        column.addLayout(bar)
        self.detail_host = QVBoxLayout()
        self.detail_host.setContentsMargins(0, 0, 0, 0)
        column.addLayout(self.detail_host, 1)
        return page

    # --- koleksiyonlar -------------------------------------------------------
    def reload(self, select=None):
        """Koleksiyon listesini depodan yeniler; bos ise bos duruma gecer."""
        collections = library.list_collections()
        select = select or self.slug
        self.collection_list.blockSignals(True)
        self.collection_list.clear()
        for slug, data in collections.items():
            item = QListWidgetItem(tinted_icon('folder', THEME['secondary'], 16), data['title'])
            item.setData(Qt.UserRole, slug)
            self.collection_list.addItem(item)
        self.collection_list.blockSignals(False)
        if not collections:
            self.slug, self.data = '', None
            if self.pages.currentIndex() != PAGE_DETAIL:
                self.pages.setCurrentIndex(PAGE_EMPTY)
            return
        if self.pages.currentIndex() == PAGE_EMPTY:
            self.pages.setCurrentIndex(PAGE_LIST)
        slugs = list(collections)
        self.collection_list.setCurrentRow(slugs.index(select) if select in slugs else 0)

    def _on_collection_changed(self, current, _previous):
        if current is not None:
            self.show_collection(current.data(Qt.UserRole))

    def show_collection(self, slug):
        try:
            self.data = library.load_collection(slug)
        except (OSError, ValueError) as error:
            self._warn('Koleksiyon açılamadı: ' + str(error))
            return
        self.slug = slug
        self.title_label.setText(self.data['title'])
        self._fill_folders()
        self.rescan()

    def _fill_folders(self):
        """Kaynak klasorler: klasor adi + dosya sayisi (tam yol arac ipucunda)."""
        self.folder_list.clear()
        counts = {}
        for entry in self.entries:
            if entry['root']:
                counts[entry['root']] = counts.get(entry['root'], 0) + 1
        for folder in self.data['folders']:
            name = Path(folder).name or folder
            item = QListWidgetItem(f'{name}\n{counts[folder]} dosya' if folder in counts else name)
            item.setToolTip(folder)
            item.setData(Qt.UserRole, folder)
            self.folder_list.addItem(item)
        if not self.data['folders']:
            item = QListWidgetItem('Klasör eklenmedi')
            item.setFlags(Qt.NoItemFlags)
            self.folder_list.addItem(item)

    def rescan(self):
        """Klasorleri arka planda tarar; sonuc gelene kadar mevcut tablo kalir."""
        if self.data is None:
            return
        self._generation += 1
        generation, slug, data = self._generation, self.slug, copy.deepcopy(self.data)
        self.meta_label.setText('Taranıyor…')

        def work():
            try:
                entries, changed = library.scan(data)
                cfg = library._embedding_cfg(None)
                infos = [library.describe(entry, cfg=cfg) for entry in entries]
            except Exception as error:  # tarama hatasi arayuzu dusurmesin
                self.scanned.emit(generation, slug, None, [], str(error), False)
                return
            self.scanned.emit(generation, slug, data, entries, infos, changed)

        threading.Thread(target=work, name='aktar-library-scan', daemon=True).start()

    def _scan_finished(self, generation, slug, data, entries, infos, changed):
        if generation != self._generation or slug != self.slug:
            return  # bu arada baska koleksiyon secildi / icerik degisti
        if data is None:
            self.meta_label.setText('')
            self._warn('Koleksiyon taranamadı: ' + str(infos))
            return
        self.data = data
        if changed:
            try:
                library.save_collection(data, slug)
            except RuntimeError as error:
                self._log('UYARI: ' + str(error))
        self.entries, self.infos = entries, infos
        self._fill_folders()
        self._fill_chips()
        self._fill_table()

    def _save_and_refresh(self, message=''):
        try:
            library.save_collection(self.data, self.slug)
        except RuntimeError as error:
            self._warn(str(error))
            return
        if message:
            self._log(message)
        self._fill_folders()
        self.rescan()

    def new_collection(self):
        title, ok = QInputDialog.getText(self, 'Yeni koleksiyon', 'Koleksiyon adı:')
        if not ok or not title.strip():
            return
        try:
            slug, _data = library.create_collection(title)
        except (ValueError, RuntimeError) as error:
            self._warn(str(error))
            return
        self._log('Koleksiyon oluşturuldu: ' + title.strip())
        self.reload(select=slug)

    def rename_collection(self, slug):
        current = library.load_collection(slug)['title']
        title, ok = QInputDialog.getText(self, 'Yeniden adlandır', 'Koleksiyon adı:', text=current)
        if not ok or not title.strip() or title.strip() == current:
            return
        try:
            library.rename_collection(slug, title)
        except (ValueError, RuntimeError) as error:
            self._warn(str(error))
            return
        self.reload(select=slug)

    def delete_collection(self, slug):
        title = library.load_collection(slug)['title']
        if not self._confirm('Koleksiyonu sil',
                             f'"{title}" koleksiyonu silinsin mi?',
                             'Yalnızca koleksiyon kaydı silinir; dosyalarınız diskte kalır.'):
            return
        library.delete_collection(slug)
        self._log('Koleksiyon silindi: ' + title)
        if slug == self.slug:
            self.slug, self.data = '', None
        self.reload()

    def _collection_menu(self, point):
        item = self.collection_list.itemAt(point)
        if item is None:
            return
        slug = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction('Yeniden adlandır', lambda: self.rename_collection(slug))
        menu.addAction('Yeniden tara', lambda: self.show_collection(slug))
        menu.addSeparator()
        menu.addAction('Koleksiyonu sil', lambda: self.delete_collection(slug))
        menu.exec(self.collection_list.mapToGlobal(point))

    def _folder_menu(self, point):
        item = self.folder_list.itemAt(point)
        folder = item.data(Qt.UserRole) if item is not None else None
        if not folder:
            return
        menu = QMenu(self)
        menu.addAction('Klasörü aç',
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
        menu.addAction('Koleksiyondan kaldır', lambda: self.remove_folder(folder))
        menu.exec(self.folder_list.mapToGlobal(point))

    def remove_folder(self, folder):
        if self.data is not None and library.remove_folder(self.data, folder):
            self._save_and_refresh('Klasör koleksiyondan kaldırıldı: ' + folder)

    # --- ekleme --------------------------------------------------------------
    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Klasör Seç')
        if folder:
            self.add_paths([folder])

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Dosya Seç', '', file_filter())
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        """Birakilan/secilen klasor ve dosyalari acik koleksiyona ekler.

        Koleksiyon yoksa klasorun (ya da dosyanin klasorunun) adiyla yenisi kurulur."""
        folders = [path for path in paths if Path(path).is_dir()]
        files = [path for path in paths if Path(path).is_file()]
        skipped = [Path(path).name for path in files if library.kind_of(path) is None]
        files = [path for path in files if library.kind_of(path) is not None]
        if not folders and not files:
            self._warn('Desteklenen dosya bulunamadı.'
                       + (' Atlananlar: ' + ', '.join(skipped[:5]) if skipped else ''))
            return
        if self.data is None:
            try:
                slug, _data = library.create_collection(library.default_title(folders + files),
                                                        folders=folders, files=files)
            except (ValueError, RuntimeError) as error:
                self._warn(str(error))
                return
            self._log('Koleksiyon oluşturuldu: ' + library.load_collection(slug)['title'])
            self.reload(select=slug)
            return
        changed = sum(1 for folder in folders if library.add_folder(self.data, folder))
        changed += library.add_files(self.data, files)
        if not changed:
            self._log('Eklenenler zaten koleksiyonda.')
            return
        self._save_and_refresh(f'Koleksiyona eklendi: {len(folders)} klasör, {len(files)} dosya.')

    def exclude_rows(self, rows):
        paths = [self.entries[row]['path'] for row in rows if row < len(self.entries)]
        if not paths or self.data is None:
            return
        library.exclude(self.data, paths)
        self._save_and_refresh(f'{len(paths)} dosya koleksiyondan çıkarıldı (diskte duruyor).')

    # --- tablo ---------------------------------------------------------------
    def _fill_chips(self):
        checked = self.chips.checkedButton()
        wanted = checked.property('kind') if checked is not None else ''
        for button in self.chips.buttons():
            self.chips.removeButton(button)
            button.deleteLater()
        counts = {}
        for entry in self.entries:
            counts[entry['kind']] = counts.get(entry['kind'], 0) + 1
        options = [('', 'Tümü', len(self.entries))]
        options += [(kind, KIND_LABELS.get(kind, kind), count) for kind, count in counts.items()]
        for index, (kind, label, count) in enumerate(options):
            button = QPushButton(f'{label}  {count}')
            button.setObjectName('libChip')
            button.setCheckable(True)
            button.setProperty('kind', kind)
            button.setChecked(kind == wanted)
            self.chips.addButton(button, index)
            self.chip_row.addWidget(button)
        if self.chips.checkedButton() is None:
            self.chips.button(0).setChecked(True)

    def _fill_table(self):
        self._update_meta()
        self.table.setRowCount(len(self.entries))
        self._rows = {library._key(entry['path']): row for row, entry in enumerate(self.entries)}
        for row in range(len(self.entries)):
            self._fill_row(row)
        self._apply_filter()

    def _update_meta(self):
        counts = {}
        for info in self.infos:
            counts[info['status']] = counts.get(info['status'], 0) + 1
        parts = [f'{len(self.entries)} dosya']
        parts += [f'{counts[key]} {META_TEXT[key]}'
                  for key in ('ready', 'transcript', 'pending', 'no_subtitle', 'missing')
                  if counts.get(key)]
        self.meta_label.setText(' · '.join(parts))

    def _fill_row(self, row):
        entry, info = self.entries[row], self.infos[row]
        kind = QTableWidgetItem(tinted_icon(KIND_ICONS.get(entry['kind'], 'film'),
                                            THEME['secondary'], 16), '')
        kind.setToolTip(KIND_LABELS.get(entry['kind'], entry['kind']))
        name = QTableWidgetItem(entry['path'].name + ('  · yeni' if entry['new'] else ''))
        name.setToolTip(str(entry['path']))
        folder = QTableWidgetItem(self._where(entry))
        folder.setToolTip(str(Path(entry['path']).parent))
        folder.setForeground(QColor(THEME['muted']))
        length = QTableWidgetItem(format_duration(info['duration']) if info['duration']
                                  else ('—' if entry['missing'] else format_size(entry['path'])))
        length.setForeground(QColor(THEME['secondary'] if info['duration'] else THEME['muted']))
        source = QTableWidgetItem(info['source'] or '—')
        source.setForeground(QColor(THEME['secondary'] if info['source'] else THEME['muted']))
        status = QTableWidgetItem(STATUS_TEXT[info['status']])
        status.setForeground(QColor(STATUS_COLOR[info['status']]))
        if entry['missing']:
            name.setForeground(QColor(THEME['disabled']))
        elif entry['new']:
            name.setForeground(QColor(THEME['accent']))
        for column, item in enumerate((kind, name, folder, length, source, status)):
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, column, item)

    def _set_status_cell(self, path, text, color):
        """Kuyruk calisirken tek satirin durum hucresi (acik koleksiyonda varsa)."""
        row = self._rows.get(library._key(path))
        item = self.table.item(row, 5) if row is not None else None
        if item is not None:
            item.setText(text)
            item.setForeground(QColor(color))

    def _refresh_entry(self, path):
        """Islenen dosyanin durumunu onbellekten yeniden okuyup satiri gunceller."""
        row = self._rows.get(library._key(path))
        if row is None or row >= len(self.entries):
            return
        self.infos[row] = library.describe(self.entries[row])
        self._fill_row(row)
        self._update_meta()

    @staticmethod
    def _where(entry):
        """Klasor sutunu: kaynak klasore gore goreli alt klasor (kokteyse klasor adi)."""
        parent = entry['path'].parent
        if entry['root']:
            try:
                relative = parent.relative_to(entry['root'])
            except ValueError:
                return parent.name
            return Path(entry['root']).name if str(relative) == '.' else str(relative)
        return parent.name

    def _apply_filter(self):
        text = self.search.text().strip().casefold()
        checked = self.chips.checkedButton()
        kind = checked.property('kind') if checked is not None else ''
        for row, entry in enumerate(self.entries):
            hidden = ((kind and entry['kind'] != kind)
                      or (text and text not in entry['path'].name.casefold()))
            self.table.setRowHidden(row, bool(hidden))

    def _selected_rows(self):
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def _table_menu(self, point):
        row = self.table.rowAt(point.y())
        if row < 0 or row >= len(self.entries):
            return
        if row not in self._selected_rows():
            self.table.selectRow(row)
        rows = self._selected_rows()
        entry = self.entries[row]
        menu = QMenu(self)
        single = len(rows) == 1 and not entry['missing']
        action = menu.addAction('Oynat ve soru sor', lambda: self.open_row(row))
        action.setEnabled(single)
        action = menu.addAction('Altyazıyı çevir…',
                                lambda: self.translate_requested.emit(str(entry['path'])))
        action.setEnabled(single and entry['kind'] == 'video')
        action = menu.addAction('Dosya konumunu aç', lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(entry['path'].parent))))
        action.setEnabled(entry['path'].parent.is_dir())
        menu.addSeparator()
        label = 'Koleksiyondan çıkar' + (f' ({len(rows)} dosya)' if len(rows) > 1 else '')
        menu.addAction(label, lambda: self.exclude_rows(rows))
        menu.exec(self.table.viewport().mapToGlobal(point))

    # --- ayrinti (oynatici + soru sor) ---------------------------------------
    def open_row(self, row):
        if 0 <= row < len(self.entries):
            self.open_detail(self.entries[row])

    def open_detail(self, entry):
        if entry['missing'] or not entry['path'].is_file():
            self._warn('Dosya bulunamadı: ' + str(entry['path']))
            return
        if entry['kind'] != 'video':
            return
        if self.qa_panel is None or self.qa_panel.video != entry['path']:
            try:
                # Lazy import: QtMultimedia yalnizca bir video acilinca yuklenir.
                from qa_panel import VideoQAPanel
            except ImportError as error:
                self._warn('Video oynatıcı bileşeni yüklenemedi (QtMultimedia): ' + str(error))
                return
            self._retire_qa_panel()
            self.qa_panel = VideoQAPanel(entry['path'], log=self._log)
            self.detail_host.addWidget(self.qa_panel, 1)
            self._log('Soru Sor hazırlanıyor: ' + entry['path'].name)
        self.back_button.setText(self.data['title'] if self.data else 'Kütüphane')
        self.detail_title.setText(entry['path'].name)
        self.pages.setCurrentIndex(PAGE_DETAIL)

    def close_detail(self):
        """Listeye doner; panel (ve hazirligi) kalir, video gizlenince duraklar."""
        self.pages.setCurrentIndex(PAGE_LIST if self.data is not None else PAGE_EMPTY)
        self.rescan()  # hazirlik durumu degismis olabilir

    def _retire_qa_panel(self):
        panel = self.qa_panel
        if panel is None:
            return
        self.qa_panel = None
        self.detail_host.removeWidget(panel)
        self._qa_retired = [item for item in self._qa_retired if _alive(item) and item.busy()]
        if panel.busy():
            self._qa_retired.append(panel)
        panel.retire()

    # --- toplu hazirlik (F56) ------------------------------------------------
    def prepare_all(self):
        if self._queue is not None:
            return
        entries = [entry for entry in self.entries if not entry['missing']]
        if not entries:
            self._warn('Koleksiyonda hazırlanacak video yok.')
            return
        dialog = PrepareDialog(entries, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.start_queue(dialog.queue(), dialog.allow_whisper())

    def start_queue(self, entries, allow_whisper):
        if not entries:
            return
        worker = QueueWorker(entries, allow_whisper)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.started.connect(self._queue_started)
        worker.progress.connect(self._queue_progress)
        worker.item_done.connect(self._queue_item_done)
        worker.log.connect(self._log)
        worker.finished.connect(self._queue_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._queue = (thread, worker)
        self._queue_total = len(entries)
        self._queue_index = 0
        self._queue_failed = []
        self.queue_bar.setMaximum(len(entries))
        self.queue_bar.setValue(0)
        self.queue_value.setText(f'0 / {len(entries)}')
        self._set_queue_paused(False)
        self.queue_strip.show()
        self.prepare_button.setEnabled(False)
        for entry in entries:
            self._set_status_cell(entry['path'], 'Sırada', THEME['muted'])
        self._log(f'Toplu hazırlık başladı: {len(entries)} video'
                  + (' (Whisper açık).' if allow_whisper else '.'))
        thread.start()

    def _queue_started(self, index, path, step):
        self._queue_name = Path(path).name
        self._queue_index = index
        self.queue_label.setText(f'Hazırlanıyor {index + 1}/{self._queue_total} · '
                                 f'{self._queue_name} — {step}')
        self._set_status_cell(path, 'İşleniyor…', THEME['accent'])

    def _queue_progress(self, done, total):
        """Whisper ilerlemesi (saniye): satirda ve seritte yuzde."""
        if total <= 0 or self._queue is None:
            return
        percent = int(100 * done / total)
        worker = self._queue[1]
        path = worker.entries[self._queue_index]['path']
        self._set_status_cell(path, f'Whisper %{percent}', THEME['accent'])
        self.queue_value.setText(f'{self._queue_index} / {self._queue_total} · %{percent}')

    def _queue_item_done(self, path, outcome, error):
        done = self.queue_bar.value() + 1
        self.queue_bar.setValue(done)
        self.queue_value.setText(f'{done} / {self._queue_total}')
        if outcome == 'failed':
            self._queue_failed.append(Path(path).name)
            self._log(f'HATA [{Path(path).name}]: {error}')
            self._set_status_cell(path, 'Hata', THEME['disabled'])
            return
        self._refresh_entry(path)

    def _queue_finished(self, done, failed, stopped):
        self._queue = None
        self.queue_strip.hide()
        self.prepare_button.setEnabled(True)
        message = (f'Toplu hazırlık {"durduruldu" if stopped else "bitti"}: {done} video hazır'
                   + (f', {failed} hata ({", ".join(self._queue_failed[:5])}).' if failed else '.'))
        self._log(message)
        self.rescan()
        if failed:
            self._warn(message + ' Ayrıntılar Altyazı Çevir sekmesindeki konsolda.')

    def toggle_queue_pause(self):
        if self._queue is None:
            return
        worker = self._queue[1]
        paused = worker.resume_event.is_set()
        if paused:
            worker.resume_event.clear()
        else:
            worker.resume_event.set()
        self._set_queue_paused(paused)

    def _set_queue_paused(self, paused):
        name = 'play' if paused else 'pause'
        self.queue_pause.setIcon(tinted_icon(name, THEME['text']))
        self.queue_pause.setHoverIcon(tinted_icon(name, THEME['accent']))
        self.queue_pause.setToolTip('Devam' if paused else 'Duraklat (sıradaki dosyadan önce)')
        if paused:
            self.queue_label.setText(f'Duraklatıldı · {self._queue_name} bitince bekler')
        elif self._queue is not None and self._queue_name:
            self.queue_label.setText('Devam ediliyor…')

    def stop_queue(self):
        if self._queue is None:
            return
        worker = self._queue[1]
        worker.cancel_event.set()
        worker.resume_event.set()
        self.queue_label.setText('Durduruluyor…')

    def shutdown(self):
        if self._queue is not None:
            thread, worker = self._queue
            worker.cancel_event.set()
            worker.resume_event.set()
            thread.quit()
            thread.wait(5000)
        for panel in [self.qa_panel] + self._qa_retired:
            if panel is not None and _alive(panel):
                panel.shutdown()

    # --- yardimcilar ---------------------------------------------------------
    def _confirm(self, title, text, detail=''):
        box = QMessageBox(self)
        box.setWindowTitle('Aktar - ' + title)
        box.setWindowIcon(window_icon())
        box.setText(text)
        if detail:
            box.setInformativeText(detail)
        yes = box.addButton('Sil', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton('Vazgeç', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes
