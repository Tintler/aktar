"""PySide6 masaustu arayuzu.

Duzen (mockup-2 "Ust Arac Cubugu" v2):
  - Üst özel başlık şeridi (frameless): [marka] [Video Seç] [Seri: dropdown / Terim / Süreklilik] [durum rozeti] [Ayarlar] [─ ▢ ✕]
  - Orta alan (kart yuzeyleri): bos durum birakma alani / dosya karti + akis tablosu
  - Islem karti: [Bolum terimleri...] [On analiz yap (anahtar)] [ilerleme] [Duraklat] [Cevir]
  - Alt panel (QSplitter + QTabWidget): [Konsol] [On Analiz]

Akış: video sürükle-bırak/Video Seç -> altyazı stream listesi -> akış işaretlenir ->
"Çevir" TEK eylem dugmesi once altyaziyi cikarir, sonra otomatik cevirir (cikarma
bitmeden ceviri baslamaz). Buton is boyunca PASIF olur. "On analiz yap" ticklenirse
ceviri oncesi aday terimler cikarilip "On Analiz" sekmesine yazilir.

Ceviri/checkpoint/glossary mantigi app_core'da tek yerde tutulur; buraya kopyalanmaz.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPointF,
                            QPropertyAnimation, QRectF, Qt, QThread, QTimer,
                            QVariantAnimation, Signal, Slot)
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath,
                           QPalette, QPixmap)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSizePolicy, QSpinBox, QSplitter, QStyle,
    QStyledItemDelegate, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from app_core import (APP_DIR, DEFAULT_CONFIG, ROOT, GracefulStop, PauseController,
                      TranslationEngine, _dedupe_glossary, load_config,
                      merge_glossaries, read, render_output, save_json, validate_config)
from media import (VIDEO_EXTENSIONS, extract_subtitle, subtitle_streams,
                   unique_output_path, unique_source_path)
import series
import subtitle

# ---------------------------------------------------------------------------
# Tema: renkler tek bir sozlukte tutulur, QSS sablonuna .format() ile enjekte edilir.
# Boylece tema degistirmek icin yalnizca THEME guncellenir (QSS tekrar tekrar yazilmaz).
# Kural: vurgu rengi (accent) yalnizca birincil eylemde (Cevir), secili sekme alt
# cizgisinde, tablodaki onay isaretinde ve progress bar dolgusunda kullanilir.
# ---------------------------------------------------------------------------
THEME = {
    'bg': '#03080a',            # pencere zemini
    'chrome': '#080d0f',        # baslik cubugu / sekme seridi
    'panel': '#0c1113',         # panel, buton, input, tablo zemini
    'border': '#1a2226',        # kenarlik
    'panel_alt': '#101719',     # tablo basligi / secili sekme zemini
    'text': '#e6edee',          # ana metin
    'secondary': '#9aabaf',     # ikincil metin
    'muted': '#6f8085',         # soluk/pasif metin
    'accent': '#c8ff00',        # vurgu
    'accent_text': '#0a1200',   # vurgu uzerindeki metin
    'accent_hover': '#d7ff3d',  # accent hover (turev renk)
    'accent_soft': 'rgba(200,255,0,0.12)',    # accent dolgusu (rozet/calisan buton)
    'accent_edge': 'rgba(200,255,0,0.28)',    # accent dolgusunun kenarligi
    'disabled': '#54666b',      # disabled metin
    'drop_border': '#243035',   # surukle-birak kesikli kenarlik
    'frame_border': '#33434a',  # frameless pencere dis cercevesi (bg'den acik)
    'grid': '#101719',          # tablo grid cizgisi (cok sonuk)
    'ui_font': 'IBM Plex Sans',
    'mono_font': 'IBM Plex Mono',
    'fallback_font': 'Segoe UI',
    'fallback_mono': 'Consolas',
    'body_size': 14,
    'label_size': 12,
    'mono_size': 13,
    'row_height': 40,
    'radius': 12,               # kart kosesi
    'radius_small': 9,          # buton/input kosesi
}

STYLE_TEMPLATE = """
QWidget {{ background:{bg}; color:{text}; }}
QMainWindow {{ background:{bg}; }}
QLabel {{ background:transparent; }}
QToolTip {{ background:{panel_alt}; color:{text}; border:1px solid {border}; padding:5px 7px; }}

/* Frameless pencerenin dis cercevesi: arkada koyu bir zemin olsa bile pencere
   siniri ayristirilsin diye bg'den daha acik bir kenarlik. (QWidget border
   boyamaz; bu yuzden kok widget QFrame'dir.) */
QFrame#appRoot {{ background:{bg}; border:1px solid {frame_border}; }}

QFrame#customTitleBar {{ background:{chrome}; border:0; border-bottom:1px solid {border};
                         padding-right:4px; }}
QFrame#customTitleBar QLabel#groupLabel {{ color:{muted}; font-size:11px; letter-spacing:0.7px; padding:0 2px; }}
QFrame#customTitleBar QPushButton {{ background:transparent; border:0; color:{secondary};
                                     padding:6px 11px; border-radius:{radius_small}px; }}
QFrame#customTitleBar QPushButton:hover {{ background:{panel_alt}; color:{accent}; }}
QFrame#customTitleBar QPushButton:pressed {{ background:{border}; color:{accent}; }}
QFrame#customTitleBar QComboBox {{ background:{panel}; border:1px solid {border}; color:{text}; padding:5px 9px; }}
/* Pencere dugmeleri. DIKKAT: Qt QSS ozgullugu CSS2 gibidir; "QFrame#customTitleBar
   QPushButton" (1 ID + 2 element) kurali "QPushButton#winButton" (1 ID + 1 element)
   kuralindan daha gucludur. Bu yuzden dugme kurallari da ata seciciyle yazilir;
   aksi halde padding uygulanip 46x32 siser ve ortalama bozulur. */
QFrame#customTitleBar QPushButton#winButton,
QFrame#customTitleBar QPushButton#winClose {{
    background:transparent; border:0; color:{secondary}; padding:0;
    min-width:46px; max-width:46px; min-height:32px; max-height:32px;
    border-radius:{radius_small}px;
}}
QFrame#customTitleBar QPushButton#winButton:hover,
QFrame#customTitleBar QPushButton#winClose:hover {{
    background:#1a2530; color:{accent};
}}
QFrame#customTitleBar QPushButton#winButton:pressed,
QFrame#customTitleBar QPushButton#winClose:pressed {{
    background:{border}; color:{accent};
}}
QLabel#statusPill {{ background:{panel}; border:1px solid {border}; border-radius:15px;
                     color:{secondary}; padding:6px 12px; font-size:12px; }}

QFrame#card {{ background:{panel}; border:1px solid {border}; border-radius:{radius}px; }}
QLabel#cardTitle {{ font-size:13px; font-weight:600; }}
QLabel#countPill {{ background:{panel_alt}; color:{secondary}; border-radius:10px;
                    padding:2px 8px; font-size:11px; }}
QLabel#hint {{ color:{muted}; font-size:12px; }}
QLabel#fileName {{ font-size:14px; font-weight:600; }}
QLabel#filePath {{ font-family:'{mono_font}'; font-size:{mono_size}px; color:{muted}; background:transparent; }}
QLabel#brandText {{ font-size:14px; font-weight:700; }}

QPlainTextEdit,QComboBox,QLineEdit,QSpinBox,QDoubleSpinBox {{
    background:{chrome}; border:1px solid {border}; border-radius:{radius_small}px;
    color:{text}; padding:6px 10px; selection-background-color:{panel_alt}; }}
QPlainTextEdit {{ border:0; background:transparent; font-family:'{mono_font}'; font-size:{mono_size}px;
                  color:{secondary}; padding:10px 14px; }}
QComboBox::drop-down {{ border:0; width:22px; }}
QComboBox QAbstractItemView {{ background:{panel}; border:1px solid {border}; color:{text};
                               selection-background-color:{panel_alt}; outline:none; }}
QLineEdit:read-only,QSpinBox:read-only,QDoubleSpinBox:read-only {{ background:{panel_alt}; color:{secondary}; }}
QComboBox:disabled,QCheckBox:disabled {{ color:{disabled}; background:{panel_alt}; }}

QPushButton {{ background:{panel}; border:1px solid {border}; color:{text};
               padding:8px 13px; border-radius:{radius_small}px; }}
QPushButton:hover {{ background:#1a2530; color:{accent}; }}
QPushButton:pressed {{ background:{chrome}; color:{accent}; }}
QPushButton:disabled {{ color:{disabled}; background:{panel}; border-color:{border}; }}
QPushButton#primary {{ background:{accent}; color:{accent_text}; border:1px solid {accent};
                       font-weight:600; padding:8px 20px; }}
QPushButton#primary:hover {{ background:{accent_hover}; border-color:{accent_hover}; color:{accent_text}; }}
QPushButton#primary:disabled {{ background:{accent_soft}; color:{accent}; border-color:{accent_edge}; }}
QPushButton#ghost {{ background:transparent; border:1px solid {border}; color:{secondary}; }}
QPushButton#ghost:hover {{ background:{panel_alt}; color:{accent}; }}
QPushButton#iconOnly {{ background:{panel}; border:1px solid {border}; padding:8px; }}
QPushButton#iconFlat {{ background:transparent; border:0; padding:6px; }}
QPushButton#iconFlat:hover {{ background:{panel_alt}; color:{accent}; }}
QPushButton#iconOnly:hover {{ background:#1a2530; color:{accent}; }}

QFrame#dropArea {{ background:{panel}; border:1.5px dashed {drop_border}; color:{secondary};
                   border-radius:14px; }}
QLabel#dropTitle {{ font-size:17px; font-weight:600; }}
QLabel#progressValue {{ color:{secondary}; font-family:'{mono_font}'; font-size:{mono_size}px; }}

QProgressBar {{ border:0; background:{panel_alt}; border-radius:4px; max-height:8px; min-height:8px; }}
QProgressBar::chunk {{ background:{accent}; border-radius:4px; }}

QHeaderView::section {{ background:{chrome}; color:{muted}; border:0;
                        padding:9px 6px; font-size:11px; }}
QTableWidget {{ background:{panel}; border:0; gridline-color:{grid}; outline:none; }}
QTableWidget::item {{ border-bottom:1px solid {grid}; padding-left:2px; }}
QTableWidget::item:hover {{ color:{accent}; }}
QTableWidget::indicator {{ width:18px; height:18px; border:1px solid {drop_border};
                           background:{panel}; border-radius:5px; }}
QTableWidget::indicator:disabled {{ border-color:{border}; }}
QTableWidget::indicator:checked {{ background:{accent}; border:1px solid {accent};{check_image} }}

QTabWidget::pane {{ border:0; }}
QTabBar::tab {{ background:transparent; color:{muted}; padding:10px 15px; border:0;
                border-bottom:2px solid transparent; }}
QTabBar::tab:selected {{ color:{text}; border-bottom:2px solid {accent}; }}
QTabBar::tab:hover {{ color:{secondary}; }}

QSplitter::handle:vertical {{ background:transparent; height:12px; }}

QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{drop_border}; border-radius:4px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:{muted}; }}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{ background:transparent; }}
QScrollBar:horizontal {{ background:transparent; height:10px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:{drop_border}; border-radius:4px; min-width:30px; }}
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal {{ width:0; }}

QFrame#toast {{ background:{panel_alt}; border:1px solid {drop_border}; border-radius:{radius}px; }}
QLabel#toastTitle {{ font-size:13px; font-weight:600; }}
QLabel#toastBody {{ font-size:12px; color:{secondary}; }}

QLabel#settingsSection {{ color:{secondary}; font-weight:600; padding-top:9px; padding-bottom:4px;
                          border-bottom:1px solid {border}; }}
QLabel#settingsWarning {{ background:{panel_alt}; color:{secondary}; border:1px solid {border};
                          padding:9px; border-radius:{radius_small}px; }}
QLabel#badgeOk {{ background:{accent_soft}; color:{accent}; border-radius:11px;
                  padding:3px 9px; font-size:11px; }}
QLabel#badgeMuted {{ background:{panel_alt}; color:{secondary}; border-radius:11px;
                     padding:3px 9px; font-size:11px; }}
QLabel#badgeOff {{ background:{panel_alt}; color:{muted}; border-radius:11px;
                   padding:3px 9px; font-size:11px; }}

QDialog {{ background:{bg}; }}
"""


def asset_path(name):
    """Varlik dosyasini bulur: once exe/uygulama dizinindeki assets/, sonra pakete
    gomulu assets/ (ROOT). Bulunamazsa None doner. Gecici klasorlere bakmaz."""
    for directory in (APP_DIR / 'assets', ROOT / 'assets'):
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def _first_font(candidates):
    """Verilen font ailelerinden sistemde kurulu olan ilkini dondurur."""
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return candidates[-1]


_MONO_FAMILY = THEME['fallback_mono']


def build_style():
    """THEME + QSS sablonundan stil uretir (font tespiti ve varlik yolu dahil)."""
    global _MONO_FAMILY
    theme = dict(THEME)
    theme['ui_font'] = _first_font([THEME['ui_font'], THEME['fallback_font']])
    theme['mono_font'] = _first_font([THEME['mono_font'], THEME['fallback_mono']])
    _MONO_FAMILY = theme['mono_font']
    check_icon = asset_path('check-lime.svg')
    theme['check_image'] = (' image:url(' + check_icon.as_posix() + ');'
                            if check_icon is not None else '')
    return theme, STYLE_TEMPLATE.format(**theme)


def _brand_pixmap(size):
    """Arac cubugu logosu: once PNG/ICO, yoksa SVG'yi QSvgRenderer ile cizer."""
    for name in ('aktar-icon-256.png', 'aktar-icon-512.png', 'aktar.ico'):
        path = asset_path(name)
        if path is None:
            continue
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    path = asset_path('aktar-icon.svg')
    if path is None:
        return QPixmap()
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return QIcon(str(path)).pixmap(size)
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return QPixmap()
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def window_icon():
    for name in ('aktar-icon-256.png', 'aktar.ico', 'aktar-icon-512.png', 'aktar-icon.svg'):
        path = asset_path(name)
        if path is not None:
            return QIcon(str(path))
    return QIcon()


def _settings_svg_icon(size=20, color='#8e9da1'):
    """Ayarlar butonu için inline SVG'den QIcon üretir.

    Hover varyanti icin color'a accent verilerek ikinci bir ikon uretilir
    (HoverIconButton.setHoverIcon ile baglanir)."""
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        b'fill="#8e9da1"><path d="M8.68637 4.00008L11.293 '
        b'1.39348C11.6835 1.00295 12.3167 1.00295 12.7072 1.39348L'
        b'15.3138 4.00008H19.0001C19.5524 4.00008 20.0001 4.4478 '
        b'20.0001 5.00008V8.68637L22.6067 11.293C22.9972 11.6835 '
        b'22.9972 12.3167 22.6067 12.7072L20.0001 15.3138V'
        b'19.0001C20.0001 19.5524 19.5524 20.0001 19.0001 20.0001H'
        b'15.3138L12.7072 22.6067C12.3167 22.9972 11.6835 22.9972 '
        b'11.293 22.6067L8.68637 20.0001H5.00008C4.4478 20.0001 '
        b'4.00008 19.5524 4.00008 19.0001V15.3138L1.39348 '
        b'12.7072C1.00295 12.3167 1.00295 11.6835 1.39348 '
        b'11.293L4.00008 8.68637V5.00008C4.00008 4.4478 4.4478 '
        b'4.00008 5.00008 4.00008H8.68637ZM6.00008 6.00008V'
        b'9.5148L3.5148 12.0001L6.00008 14.4854V18.0001H9.5148L'
        b'12.0001 20.4854L14.4854 18.0001H18.0001V14.4854L'
        b'20.4854 12.0001L18.0001 9.5148V6.00008H14.4854L'
        b'12.0001 3.5148L9.5148 6.00008H6.00008ZM12.0001 '
        b'16.0001C9.79094 16.0001 8.00008 14.2092 8.00008 '
        b'12.0001C8.00008 9.79094 9.79094 8.00008 12.0001 '
        b'8.00008C14.2092 8.00008 16.0001 9.79094 16.0001 '
        b'12.0001C16.0001 14.2092 14.2092 16.0001 12.0001 '
        b'16.0001ZM12.0001 14.0001C13.1047 14.0001 14.0001 '
        b'13.1047 14.0001 12.0001C10.8955 10.0001 10.0001 '
        b'10.8955 10.0001 12.0001 10.0001 13.1047 14.0001 '
        b'12.0001Z"></path></svg>'
    )
    svg = svg.replace(b'fill="#8e9da1"', b'fill="' + color.encode('ascii') + b'"')
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtCore import QByteArray
    renderer = QSvgRenderer(QByteArray(svg))
    if not renderer.isValid():
        return QIcon()
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def tinted_icon(name, color, size=16):
    """assets/icons/<name>.svg dosyasini verilen tema rengine boyayip QIcon dondurur.

    QSS ikon rengi degistiremedigi icin ikonlar burada CompositionMode_SourceIn ile
    boyanir; boylece tek SVG seti butun durumlarda (normal/soluk/accent) kullanilir."""
    path = asset_path('icons/' + name + '.svg')
    if path is None:
        return QIcon()
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return QIcon(str(path))
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return QIcon()
    ratio = 2  # HiDPI ekranlarda ikon bulaniklasmasin diye 2x cizilir
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return QIcon(pixmap)


def add_shadow(widget, blur=26, alpha=90, offset=6):
    """Karta yumusak golge verir (QSS'te box-shadow yok, efekt sinifi gerekir)."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setColor(QColor(0, 0, 0, alpha))
    effect.setOffset(0, offset)
    widget.setGraphicsEffect(effect)
    return widget


def card(spacing=0, margins=(0, 0, 0, 0), horizontal=False, shadow=True):
    """Kart yuzeyi: QFrame#card + hazir yerlesim. (frame, layout) dondurur."""
    frame = QFrame()
    frame.setObjectName('card')
    layout = QHBoxLayout(frame) if horizontal else QVBoxLayout(frame)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    if shadow:
        add_shadow(frame)
    return frame, layout


def section_label(text, object_name='cardTitle'):
    label = QLabel(text)
    label.setObjectName(object_name)
    return label


class HoverHighlightDelegate(QStyledItemDelegate):
    """Satir uzerine gelince o satirdaki tum metinleri accent (yesil) yapar.

    QSS `QTableWidget::item:hover` yalnizca fare altindaki TEK hucreyi
    renklendirebiliyor; istenen davranis butun satirin (butun sutunlarin)
    yesile donmesi oldugu icin hover satiri burada izlenir ve hucre metin
    renkleri initStyleOption icinde accent'e cevrilir. Isaretlenmis (checkbox)
    satirlar da kalici olarak accent renkte kalir."""

    def __init__(self, table):
        super().__init__(table)
        self._table = table
        self._hover_row = -1
        table.setMouseTracking(True)
        table.viewport().setMouseTracking(True)
        table.viewport().installEventFilter(self)

    def _accent_palette(self, option):
        option.palette.setColor(QPalette.Text, QColor(THEME['accent']))
        option.palette.setColor(QPalette.HighlightedText, QColor(THEME['accent']))

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        row = index.row()
        checked = False
        if 0 <= row < self._table.rowCount():
            cell = self._table.item(row, 0)
            checked = cell is not None and cell.checkState() == Qt.Checked
        if checked or row == self._hover_row:
            self._accent_palette(option)

    def eventFilter(self, obj, event):
        if obj is self._table.viewport():
            if event.type() == QEvent.MouseMove:
                index = self._table.indexAt(event.position().toPoint())
                row = index.row() if index.isValid() else -1
                if row != self._hover_row:
                    self._hover_row = row
                    self._table.viewport().update()
            elif event.type() == QEvent.Leave:
                if self._hover_row != -1:
                    self._hover_row = -1
                    self._table.viewport().update()
        return super().eventFilter(obj, event)


def highlight_rows(table):
    """Tabloya satir hover'inda yesil metin vurgusu baglar."""
    delegate = HoverHighlightDelegate(table)
    table.setItemDelegate(delegate)
    return delegate


class HoverIconButton(QPushButton):
    """Ikonu yalnizca fare uzerine gelince accent (yesil) varyanta donen dugme.

    Qt ikonun Active modunu State_HasFocus'ta da cizer: dugmeye tiklanip diyolog
    acilinca klavye focus'u dugmede kaldigindan ikon, mouse uzerden ciksa bile yesil
    kaliyordu. Bu yuzden yesil varyant Active modu yerine hover eventleriyle acikca
    set edilir; focus durumundan bagimsizdir."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hover_icon = QIcon()
        self._base_icon = QIcon()

    def setHoverIcon(self, icon):
        """Hover'da gosterilecek accent (yesil) ikonu atar."""
        self._hover_icon = QIcon(icon)

    def setTintedIcon(self, name, color, size=16):
        """Normal ikonu atar ve ayni ikonun accent kopyasini hover'a ayirir."""
        self.setIcon(tinted_icon(name, color, size))
        self.setHoverIcon(tinted_icon(name, THEME['accent'], size))

    def enterEvent(self, event):
        if self.isEnabled() and not self._hover_icon.isNull():
            self._base_icon = self.icon()
            self.setIcon(self._hover_icon)
        super().enterEvent(event)

    def leaveEvent(self, event):
        # Runtime'da ikon degisti ise (orn. duraklat->devam) eski ikonu geri
        # yazmamak icin yalnizca hover ikonu hala gorunuyorsa geri alinir.
        if (not self._base_icon.isNull()
                and self.icon().cacheKey() == self._hover_icon.cacheKey()):
            self.setIcon(self._base_icon)
        self._base_icon = QIcon()
        super().leaveEvent(event)


class DropdownCombo(QComboBox):
    """Popup'unu combo'nun ALTINA acan, icerigi sigdiran combo.

    Qt 6.10 combo popup'unu, secili ogemi combo ile ayni cizgiye gelecek sekilde
    ustten aciyor (currentIndex kac ise popup o kadar yukari kayiyor): seri
    listesi combo'nun ustune biniyor ve MainWindow icinde son ogem kesiliyordu.
    Popup burada super().showPopup() sonrasi acikca combo'nun altina tasinir;
    yukseklik tum ogemleri sigdirir (MAX_VISIBLE_ROWS'tan fazlaysa kaydirma
    cubugu acilir), genislik en uzun ogem metnine gore genisler."""

    MAX_VISIBLE_ROWS = 10
    # Popup genislik hesabinda item metin marjlari + kaydirma cubugu payi;
    # Qt'nun kendi popup genisligi (contentsSize) ile olculerek sabitlendi.
    TEXT_WIDTH_PAD = 44

    def showPopup(self):
        super().showPopup()
        view = self.view()
        container = view.window()
        model = view.model()
        if container is None or model is None or self.count() == 0:
            return
        # Qt 6.10 popup container'i (QComboBoxPrivateContainer) view'in etrafina
        # koseli maskeleme widget'lari ekler; bunlarin yuksekligi kaydirma
        # cubugunun gorunurlugune gore degistigi icin Qt kendi yukseklik
        # hesabinda son ogem kesiliyordu. Maskeler cikarilir, view container'i
        # tamamen doldurur ve icerik yukseklik hesabi dogrudan uygulanir.
        layout = container.layout()
        if layout is not None:
            for i in reversed(range(layout.count())):
                widget = layout.itemAt(i).widget()
                if widget is not None and widget is not view:
                    layout.removeWidget(widget)  # koseli maske widget'lari
            layout.setSpacing(0)
            layout.setContentsMargins(0, 0, 0, 0)
        item_height = view.sizeHintForRow(0)
        if item_height <= 0:
            rect = view.visualRect(model.index(0, 0))
            item_height = rect.height() or 24
        frame = 2 * view.frameWidth()
        rows = min(self.count(), self.MAX_VISIBLE_ROWS)
        target = rows * item_height + frame  # view'in icerigi tam sigdiracagi boy
        metrics = view.fontMetrics()
        max_text = 0
        for row in range(model.rowCount()):
            text = model.data(model.index(row, 0), Qt.ItemDataRole.DisplayRole) or ''
            max_text = max(max_text, metrics.horizontalAdvance(str(text)))
        width = max(self.width(), max_text + self.TEXT_WIDTH_PAD + frame)
        bottom_left = self.mapToGlobal(QPoint(0, self.height()))
        combo_top = self.mapToGlobal(QPoint(0, 0)).y()
        x, y = bottom_left.x(), bottom_left.y()
        open_above = False
        screen = self.screen().availableGeometry()
        if x + width > screen.right() + 1:
            x = max(screen.left(), screen.right() + 1 - width)
        if y + target > screen.bottom() + 1:
            above = combo_top - target
            if above >= screen.top():  # altta yer yok: popup alt kenari combo ustune
                y = above
                open_above = True
            else:
                target = max(2 * item_height + frame, screen.bottom() + 1 - y)
        # Icerik yuksegini tam oturana kadar (en fazla 3 tur) duzelt; layout
        # defer edebildigi icin her turda activate() ile senkron okunur.
        chrome = container.height() - view.height()
        height = target + chrome
        for _ in range(3):
            container.setGeometry(x, y, width, height)
            if container.layout() is not None:
                container.layout().activate()  # bayat boyut okumamak icin senkron
            mismatch = target - view.height()
            if mismatch == 0:
                break
            height += mismatch  # hedefe kalan/bolan payi tamamen kapat
        if open_above:
            # Yukseklik duzeltmesi popup'i asagi dogru buyutmesin: alt kenar
            # combo'nun ustunde kalsin (ekranin ustune tasmazsa).
            y = combo_top - container.height()
            new_height = container.height()
            if y < screen.top():
                y = screen.top()
                new_height = combo_top - y
            container.setGeometry(x, y, width, new_height)
        if view.currentIndex().isValid():
            view.scrollTo(view.currentIndex(), QAbstractItemView.EnsureVisible)


class ToggleSwitch(QCheckBox):
    """QCheckBox davranisi, elle cizilmis anahtar gorunumu.

    QSS bir checkbox'i anahtara donusturemedigi icin gosterim paintEvent'te cizilir;
    isChecked()/setChecked() ve sinyaller degismez, cagiran taraf farki gormez."""

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._offset = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(self._animate)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._set_offset)

    def _set_offset(self, value):
        self._offset = float(value)
        self.update()

    def _animate(self, checked):
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(hint.width() + 22)
        hint.setHeight(max(hint.height(), 26))
        return hint

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width, height, radius = 38.0, 20.0, 10.0
        top = (self.height() - height) / 2.0
        track = QRectF(0.0, top, width, height)
        enabled = self.isEnabled()
        if self.isChecked() and enabled:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(THEME['accent']))
            knob = QColor(THEME['accent_text'])
        else:
            painter.setPen(QColor(THEME['border']))
            painter.setBrush(QColor('#1e2a30'))
            knob = QColor(THEME['drop_border'] if enabled else THEME['border'])
        painter.drawRoundedRect(track, radius, radius)
        travel = width - height
        painter.setPen(Qt.NoPen)
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(3.0 + travel * self._offset, top + 3.0,
                                   height - 6.0, height - 6.0))
        painter.setPen(QColor(THEME['text'] if enabled else THEME['disabled']))
        painter.drawText(QRectF(width + 10.0, 0.0, self.width() - width - 10.0,
                                float(self.height())),
                         Qt.AlignVCenter | Qt.AlignLeft, self.text())
        painter.end()


class Toast(QFrame):
    """Pencere icinde belirip kendiliginden kaybolan bildirim.

    Basarili islem sonucu artik modal kutu acmaz; modal yalnizca uyari/hata icin."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('toast')
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 13, 16, 13)
        row.setSpacing(11)
        self.mark = QLabel()
        self.mark.setFixedSize(26, 26)
        self.mark.setAlignment(Qt.AlignCenter)
        self.mark.setStyleSheet('background:%s; border-radius:8px;' % THEME['accent_soft'])
        self.mark.setPixmap(tinted_icon('check', THEME['accent'], 13).pixmap(13, 13))
        row.addWidget(self.mark, 0, Qt.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(3)
        self.title = QLabel('')
        self.title.setObjectName('toastTitle')
        self.body = QLabel('')
        self.body.setObjectName('toastBody')
        self.body.setWordWrap(True)
        column.addWidget(self.title)
        column.addWidget(self.body)
        row.addLayout(column, 1)
        self.setFixedWidth(320)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b'opacity', self)
        self._fade.setDuration(220)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self.hide()

    def show_message(self, title, body, seconds=6):
        self.title.setText(str(title))
        self.body.setText(str(body))
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(int(seconds * 1000))

    def dismiss(self):
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        try:
            self._fade.finished.disconnect()
        except RuntimeError:
            pass
        self._fade.finished.connect(self.hide)
        self._fade.start()

    def _place(self):
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(parent.width() - self.width() - 24, parent.height() - self.height() - 24)


VIDEO_FILTER = 'Video (' + ' '.join('*' + item for item in VIDEO_EXTENSIONS) + ')'
NONE_SERIES = '(Seri yok)'
NEW_SERIES = '+ Yeni seri...'


class ClickableLabel(QLabel):
    """Sol tiklaninca clicked sinyalini yayan etiket (drop alanindaki ikon icin)."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class DropArea(QFrame):
    """Video dosyasi suruklenip birakilabilen bos durum alani.

    Ikon + basliktan olusan sade bir bos durum ekrani. Ikon tiklaninca
    'Video Sec' islemi tetiklenir (select_requested)."""

    dropped = Signal(str)
    select_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('dropArea')
        self.setAcceptDrops(True)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        column = QVBoxLayout(self)
        column.setContentsMargins(24, 24, 24, 24)
        column.setSpacing(16)
        column.addStretch(1)

        self.mark = ClickableLabel()
        self.mark.setFixedSize(68, 68)
        self.mark.setAlignment(Qt.AlignCenter)
        self.mark.setStyleSheet('background:%s; border:1px solid %s; border-radius:20px;'
                                % (THEME['panel'], THEME['border']))
        self.mark.setPixmap(tinted_icon('upload', THEME['accent'], 28).pixmap(28, 28))
        self.mark.setCursor(Qt.PointingHandCursor)
        self.mark.setToolTip('Video Seç')
        self.mark.clicked.connect(self.select_requested)
        column.addWidget(self.mark, 0, Qt.AlignHCenter)

        title = QLabel('Videoyu buraya bırakın')
        title.setObjectName('dropTitle')
        column.addWidget(title, 0, Qt.AlignHCenter)
        column.addStretch(1)

    def _highlight(self, active):
        color = THEME['accent'] if active else THEME['drop_border']
        self.setStyleSheet('QFrame#dropArea {{ border:1.5px dashed {0}; }}'.format(color))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self._highlight(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event):
        self._highlight(False)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self._highlight(False)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        for path in paths:
            if Path(path).suffix.lower() in VIDEO_EXTENSIONS:
                self.dropped.emit(path)
                return
        if paths:
            self.dropped.emit(paths[0])


class ProbeWorker(QObject):
    finished = Signal(object, str)

    def __init__(self, video):
        super().__init__()
        self.video = video

    @Slot()
    def run(self):
        try:
            streams = subtitle_streams(self.video)
        except (RuntimeError, ValueError) as error:
            self.finished.emit(None, str(error))
            return
        self.finished.emit(streams, '')


class RunWorker(QObject):
    """Cikarma + (istege bagli on analiz) + ceviri zincirini tek thread'de yurutur.

    Tek eylem: once altyaziyi cikarir, sonra otomatik cevirir. Boylece ceviri,
    cikarma bitmeden baslamaz. Duraklat/iptal PauseController ile desteklenir.
    """

    progress = Signal(int, int)
    log = Signal(str)
    analysis = Signal(object)
    review_requested = Signal(str, object)  # (pre|post, oneriler)
    finished = Signal(str, str)  # (output_path, error)

    def __init__(self, video, stream, glossary, decisions, do_analysis):
        super().__init__()
        self.video = video
        self.stream = stream
        self.glossary = glossary
        self.decisions = decisions
        self.do_analysis = do_analysis
        self.pause = PauseController()
        self._cancelled = False
        self._review_event = threading.Event()
        self._review_values = None
        # work_files dizini (kalabalığı önlemek için)
        self.work_dir = APP_DIR / 'work_files'
        self.work_dir.mkdir(parents=True, exist_ok=True)


    @Slot()
    def run(self):
        try:
            video_name = Path(self.video).stem
            source_ext = self.stream['extension']  # 'srt', 'ass' vb.
            source = self.work_dir / f'{video_name}.{source_ext}'
            extract_subtitle(self.video, self.stream['index'], source, codec=self.stream['codec'])
            self.log.emit('Kaynak altyazı çıkarıldı: ' + str(source))
            kind, payload = subtitle.parse_by_extension(read(source), source.suffix)
            cues = subtitle.cues_of(kind, payload)
            engine = TranslationEngine(load_config, log=self.log.emit)
            if self.do_analysis:
                candidates = engine.analyze_terms(
                    cues, glossary=self.glossary,
                    checkpoint=self.work_dir / f'{video_name}.pre-analysis.state.json',
                    pause=self.pause)
                self.analysis.emit(candidates)
                self.log.emit('Ön analiz: ' + str(len(candidates['terms'])) + ' terim, '
                              + str(len(candidates['decisions'])) + ' süreklilik adayı bulundu.')
                accepted = self._review('pre', candidates)
                if accepted is not None:
                    terms = accepted.get('series_terms', []) + accepted.get('chapter_terms', [])
                    self.glossary = merge_glossaries(self.glossary, terms)
                    decisions = accepted.get('series_decisions', []) + accepted.get('chapter_decisions', [])
                    self.decisions = list(dict.fromkeys(self.decisions + decisions))
                    self.log.emit('Ön analiz önerileri bu çeviriye uygulandı.')
            checkpoint = self.work_dir / f'{video_name}.state.json'
            translated = engine.translate(cues, glossary=self.glossary, decisions=self.decisions,
                                          checkpoint=checkpoint, pause=self.pause,
                                          progress=lambda done, total: self.progress.emit(done, total))
            post = engine.analyze_terms(
                cues, glossary=self.glossary, translated_cues=translated,
                checkpoint=self.work_dir / f'{video_name}.post-analysis.state.json',
                pause=self.pause)
            self.log.emit('Çeviri sonu analizi: ' + str(len(post['terms'])) + ' terim, '
                          + str(len(post['decisions'])) + ' süreklilik adayı bulundu.')
            accepted_post = self._review('post', post)
            if accepted_post is not None:
                learned = (accepted_post.get('series_terms', [])
                           + accepted_post.get('chapter_terms', []))
                translated = engine.enforce_episode_terms(
                    cues, translated, learned, pause=self.pause)
        except GracefulStop as stop:
            self.finished.emit('', str(stop))
            return
        except (RuntimeError, ValueError) as error:
            self.finished.emit('', str(error))
            return
        if self._cancelled:
            self.finished.emit('', 'Çeviri iptal edildi.')
            return
        output = unique_output_path(self.video, kind)
        text, _ = render_output(kind, payload, translated, log=self.log.emit)
        output.write_text(text, encoding='utf-8', newline='\n')
        self.finished.emit(str(output), '')

    def _review(self, phase, candidates):
        if not candidates.get('terms') and not candidates.get('decisions'):
            return None
        self._review_values = None
        self._review_event.clear()
        self.review_requested.emit(phase, candidates)
        self._review_event.wait()
        if self._cancelled:
            raise GracefulStop('Çeviri iptal edildi.')
        return self._review_values

    def request_pause(self):
        self.pause.request_pause()

    def request_resume(self):
        self.pause.resume()

    def request_cancel(self):
        self._cancelled = True
        self._review_event.set()  # onay bekleniyorsa worker'i serbest birak
        self.pause.request_close()


class GlossaryDialog(QDialog):
    """Kaynak -> karsilik tablosu duzenleyici (bolum ve seri sozlugu icin ortak)."""

    def __init__(self, parent=None, items=None, title='Terim Sözlüğü'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 420)
        items = items or []
        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(items) + 1, 2)
        self.table.setHorizontalHeaderLabels(['Kaynak terim', 'Karşılık'])
        highlight_rows(self.table)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        for row, item in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(str(item.get('source', ''))))
            self.table.setItem(row, 1, QTableWidgetItem(str(item.get('target', ''))))
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Tamam')
        buttons.button(QDialogButtonBox.Cancel).setText('İptal')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        result = []
        for row in range(self.table.rowCount()):
            source = self.table.item(row, 0)
            target = self.table.item(row, 1)
            source = source.text().strip() if source else ''
            target = target.text().strip() if target else ''
            if source and target:
                result.append({'source': source, 'target': target})
        return result


class GlossaryReviewDialog(QDialog):
    """Terim ve sureklilik onerilerini secip kapsam atamaya yarayan diyalog."""

    def __init__(self, parent=None, proposed=None, decisions=None, current=None,
                 title='Terim Önerileri', has_series=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1040, 620)
        self.has_series = bool(has_series)
        current = _dedupe_glossary(current or [])
        existing = {item['source'].casefold() for item in current}
        self.proposed = [dict(item) for item in (proposed or [])
                         if str(item.get('source', '')).strip().casefold() not in existing]
        self.decisions = [dict(item) if isinstance(item, dict) else {'value': str(item)}
                          for item in (decisions or [])]

        layout = QVBoxLayout(self)
        note = QLabel(
            f'{len(current)} mevcut seri terimi korunacak. Kullanılacak önerileri '
            'işaretleyin, Türkçe karşılıkları düzeltin ve kapsamlarını seçin.')
        note.setWordWrap(True)
        layout.addWidget(note)

        self.tabs = QTabWidget()
        self.term_table = self._build_term_table()
        self.decision_table = self._build_decision_table()
        self.tabs.addTab(self.term_table, f'Terimler ({len(self.proposed)})')
        self.tabs.addTab(self.decision_table, f'Süreklilik ({len(self.decisions)})')
        layout.addWidget(self.tabs, 1)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText('Seçilenleri uygula')
        box.button(QDialogButtonBox.Cancel).setText('Atla')
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    @staticmethod
    def _check_item():
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        return item

    def _scope_box(self):
        scope = DropdownCombo()
        if self.has_series:
            scope.addItem('Seriye ekle', 'series')
        scope.addItem('Yalnız bu bölüm', 'chapter')
        return scope

    def _build_term_table(self):
        columns = ['Ekle', 'Kaynak', 'Türkçe önerisi', 'Tür', 'Gerekçe', 'Kullanım', 'Kapsam']
        table = QTableWidget(len(self.proposed), len(columns))
        table.setHorizontalHeaderLabels(columns)
        highlight_rows(table)
        header = table.horizontalHeader()
        for column in (0, 3, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        for column in (1, 2, 4):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        for row, item in enumerate(self.proposed):
            table.setItem(row, 0, self._check_item())
            source = QTableWidgetItem(str(item.get('source', '')))
            source.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            table.setItem(row, 1, source)
            table.setItem(row, 2, QTableWidgetItem(str(item.get('target', ''))))
            table.setItem(row, 3, QTableWidgetItem(str(item.get('type', 'term'))))
            table.setItem(row, 4, QTableWidgetItem(str(item.get('reason', ''))))
            count = QTableWidgetItem('x' + str(item.get('count', 1)))
            count.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            table.setItem(row, 5, count)
            table.setCellWidget(row, 6, self._scope_box())
        return table

    def _build_decision_table(self):
        columns = ['Ekle', 'Karar', 'Tür', 'Gerekçe', 'Kapsam']
        table = QTableWidget(len(self.decisions), len(columns))
        table.setHorizontalHeaderLabels(columns)
        highlight_rows(table)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        for row, item in enumerate(self.decisions):
            table.setItem(row, 0, self._check_item())
            table.setItem(row, 1, QTableWidgetItem(str(item.get('value', ''))))
            table.setItem(row, 2, QTableWidgetItem(str(item.get('type', 'continuity'))))
            table.setItem(row, 3, QTableWidgetItem(str(item.get('reason', ''))))
            table.setCellWidget(row, 4, self._scope_box())
        return table

    def values(self):
        result = {'series_terms': [], 'chapter_terms': [],
                  'series_decisions': [], 'chapter_decisions': []}
        for row, original in enumerate(self.proposed):
            check = self.term_table.item(row, 0)
            if not check or check.checkState() != Qt.Checked:
                continue
            source_item = self.term_table.item(row, 1)
            target_item = self.term_table.item(row, 2)
            source = source_item.text().strip() if source_item else ''
            target = target_item.text().strip() if target_item else ''
            if not source or not target:
                continue
            term = dict(original)
            term.update(source=source, target=target)
            scope = self.term_table.cellWidget(row, 6).currentData()
            result[scope + '_terms'].append(term)
        for row, _original in enumerate(self.decisions):
            check = self.decision_table.item(row, 0)
            if not check or check.checkState() != Qt.Checked:
                continue
            value_item = self.decision_table.item(row, 1)
            value = value_item.text().strip() if value_item else ''
            if not value:
                continue
            scope = self.decision_table.cellWidget(row, 4).currentData()
            result[scope + '_decisions'].append(value)
        return result

    def exec_and_values(self):
        if self.exec() != QDialog.Accepted:
            return None, False
        return self.values(), True


class SettingsDialog(QDialog):
    """Ayarlar penceresi (Cevirgec SettingsDialog deseni).

    LM Studio (Base URL / Model) + ceviri davranisi (Kati sozluk, Otomatik tekrar,
    batch, max_tokens, temperature, timeout, thinking). Ceviri surerken model ve
    baglanti alanlari kilitlenir.
    """

    models_loaded = Signal(object, str)  # (names, error)

    def __init__(self, config, loaded_models=None, parent=None, locked=False):
        super().__init__(parent)
        self.setWindowTitle('Ayarlar')
        self.resize(560, 0)
        self.models_loaded.connect(self._on_models)
        outer = QVBoxLayout(self)
        layout = QFormLayout()
        outer.addLayout(layout)
        self.fields = {}

        model_section = QLabel('LM Studio ve model')
        model_section.setObjectName('settingsSection')
        layout.addRow(model_section)
        base_url = QLineEdit(str(config['base_url']))
        base_url.setPlaceholderText('http://127.0.0.1:1234/v1')
        self.fields['base_url'] = base_url
        layout.addRow('Base URL', base_url)
        self.loaded_models = list(dict.fromkeys(str(model).strip()
                                                for model in (loaded_models or []) if str(model).strip()))
        choices = self.loaded_models or list(dict.fromkeys((str(config['model']).strip(),
                                                           str(DEFAULT_CONFIG['model']))))
        model = DropdownCombo()
        model.setEditable(False)
        model.addItems(choices)
        configured_index = model.findText(str(config['model']))
        model.setCurrentIndex(configured_index if configured_index >= 0 else 0)
        model.setToolTip('LM Studio tarafından yüklü bildirilen modeller arasından seçim yapılır.')
        self.fields['model'] = model
        layout.addRow('Model', model)
        refresh = HoverIconButton('Yüklü modelleri sorgula')
        refresh.setTintedIcon('refresh', THEME['secondary'])
        refresh.clicked.connect(self.refresh_models)
        self.model_hint = QLabel('LM Studio açıkken sorgulayın.')
        self.model_hint.setObjectName('hint')
        model_row = QHBoxLayout()
        model_row.addWidget(refresh)
        model_row.addWidget(self.model_hint, 1)
        layout.addRow('', model_row)

        engine_section = QLabel('Çeviri davranışı')
        engine_section.setObjectName('settingsSection')
        layout.addRow(engine_section)
        strict = QCheckBox('Uygulanamayan terimde çeviriyi durdur')
        strict.setChecked(bool(config.get('glossary_strict', False)))
        strict.setToolTip('Kapalıyken eksik terim UYARI olarak günlüğe yazılır ve çeviri devam eder.')
        self.fields['glossary_strict'] = strict
        layout.addRow('Katı sözlük', strict)
        retry_count = QSpinBox()
        retry_count.setRange(1, 100)
        retry_count.setValue(int(config.get('auto_retry_count', 2)))
        retry_count.setToolTip('Geçici/geçersiz yanıttan sonra yapılacak ek deneme sayısı '
                               '(ilk istek dahil değil: 2 seçilirse en fazla 3 istek).')
        self.fields['auto_retry_count'] = retry_count
        layout.addRow('Otomatik tekrar sayısı', retry_count)
        batch = QSpinBox()
        batch.setRange(1, 200)
        batch.setValue(int(config['batch_cues']))
        batch.setToolTip('Tek istekte modele gönderilecek altyazı girdisi sayısı.')
        self.fields['batch_cues'] = batch
        layout.addRow('Parti boyutu (girdi)', batch)
        thinking = QCheckBox('Düşünme (reasoning) modunu kapatmayı dene')
        thinking.setChecked(bool(config.get('disable_thinking', False)))
        thinking.setToolTip('LM Studio chat_template_kwargs desteklerse thinking kapatılır; '
                            'kalıcı çözüm model preset ayarıdır.')
        self.fields['disable_thinking'] = thinking
        layout.addRow('Thinking kapat', thinking)

        advanced_section = QLabel('Gelişmiş (deneysel)')
        advanced_section.setObjectName('settingsSection')
        layout.addRow(advanced_section)
        warning = QLabel('Bu ayarlar deneyseldir; ne yaptığınızdan emin değilseniz değiştirmeyin.')
        warning.setObjectName('settingsWarning')
        warning.setWordWrap(True)
        layout.addRow(warning)
        for key, title, maximum in (('analysis_chunk_chars', 'Analiz parça karakteri', 200000),
                                    ('max_tokens', 'Çıktı token payı', 262144),
                                    ('timeout_seconds', 'Timeout (s)', 86400)):
            field = QSpinBox()
            field.setRange(1, maximum)
            field.setValue(int(config[key]))
            self.fields[key] = field
            layout.addRow(title, field)
        temperature = QDoubleSpinBox()
        temperature.setRange(0, 2)
        temperature.setSingleStep(0.05)
        temperature.setValue(float(config['temperature']))
        self.fields['temperature'] = temperature
        layout.addRow('Temperature', temperature)

        restore = QPushButton('Varsayılan ayarlara dön')
        restore.clicked.connect(self.reset_defaults)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('Kaydet')
        buttons.button(QDialogButtonBox.Cancel).setText('İptal')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(restore)
        bottom.addStretch()
        bottom.addWidget(buttons)
        outer.addLayout(bottom)
        if locked:
            lock_note = QLabel('Çeviri sürerken ayarlar salt okunurdur.')
            lock_note.setObjectName('settingsWarning')
            outer.insertWidget(0, lock_note)
            for field in self.fields.values():
                if isinstance(field, (QLineEdit, QSpinBox, QDoubleSpinBox)):
                    field.setReadOnly(True)
                else:
                    field.setEnabled(False)
            refresh.setEnabled(False)
            restore.setEnabled(False)
            buttons.button(QDialogButtonBox.Save).setEnabled(False)

    def refresh_models(self):
        self.model_hint.setText('Sorgulanıyor...')
        cfg = dict(load_config())
        cfg['timeout_seconds'] = min(8, int(cfg['timeout_seconds']))

        def probe():
            from app_core import Client
            try:
                names = Client(cfg, lambda _message: None).models()
            except (RuntimeError, ValueError) as error:
                self.models_loaded.emit([], str(error))
                return
            self.models_loaded.emit(names, '')

        threading.Thread(target=probe, name='lmstudio-model-probe', daemon=True).start()

    def _on_models(self, names, error):
        if error:
            self.model_hint.setText('Bağlantı kurulamadı: ' + error)
            return
        if not names:
            self.model_hint.setText('Yüklü model bulunamadı.')
            return
        current = self.fields['model'].currentText().strip()
        self.fields['model'].clear()
        self.fields['model'].addItems(names)
        index = self.fields['model'].findText(current)
        if index >= 0:
            self.fields['model'].setCurrentIndex(index)
        self.model_hint.setText(f'{len(names)} model bulundu.')

    def reset_defaults(self):
        for key, field in self.fields.items():
            value = DEFAULT_CONFIG[key]
            if isinstance(field, QLineEdit):
                field.setText(str(value))
            elif isinstance(field, QComboBox):
                index = field.findText(str(value))
                field.setCurrentIndex(index if index >= 0 else 0)
            elif isinstance(field, QCheckBox):
                field.setChecked(bool(value))
            elif isinstance(field, QDoubleSpinBox):
                field.setValue(float(value))
            else:
                field.setValue(int(value))

    def value(self):
        result = {}
        for key, field in self.fields.items():
            if isinstance(field, QLineEdit):
                result[key] = field.text().strip()
            elif isinstance(field, QComboBox):
                result[key] = field.currentText().strip()
            elif isinstance(field, QCheckBox):
                result[key] = field.isChecked()
            elif isinstance(field, QDoubleSpinBox):
                result[key] = float(field.value())
            else:
                result[key] = int(field.value())
        return result


def edges_at(point, left, top, right, bottom):
    """Nokta verilen dikdortgenin kenarina yakinsa Qt.Edge(ler)ini dondurur.

    Koseye yakinsa iki kenar OR'lanir (orn. TopEdge|LeftEdge). Kenarda degilse
    None doner. Kenardan boyutlandirmada kullanilir."""
    edges = None
    if point.x() <= left:
        edges = Qt.LeftEdge
    elif point.x() >= right:
        edges = Qt.RightEdge
    if point.y() <= top:
        edges = Qt.TopEdge if edges is None else edges | Qt.TopEdge
    elif point.y() >= bottom:
        edges = Qt.BottomEdge if edges is None else edges | Qt.BottomEdge
    return edges


def resize_cursor(edges):
    """Kenar tutamaci icin uygun imleci secer."""
    if edges is None:
        return Qt.ArrowCursor
    left = bool(edges & Qt.LeftEdge)
    right = bool(edges & Qt.RightEdge)
    top = bool(edges & Qt.TopEdge)
    bottom = bool(edges & Qt.BottomEdge)
    if (left and top) or (right and bottom):
        return Qt.SizeFDiagCursor
    if (right and top) or (left and bottom):
        return Qt.SizeBDiagCursor
    if left or right:
        return Qt.SizeHorCursor
    return Qt.SizeVerCursor


class TitleBar(QFrame):
    """Ozel baslik seridi (frameless pencere icin).

    Surukleme ve ekran kenarina yapistirma (Aero Snap) isletim sistemine devredilir:
    sol tusa basinca QWindow.startSystemMove() cagrilir; boylece snap/geri tepme
    davranisi elle yazilmaz. Cift tik buyut/kucult yapar. Pencere dugmeleri
    (kucult / buyut / kapat) sag ucta durur.

    Kenardan boyutlandirma: seridin ust kenari pencere ust kenari oldugu icin
    seritte de kenar tutamaci vardir; ust kenara basinca startSystemResize cagrilir.
    Seridin ALT kenari boyutlandirmaya kapalidir (RESIZE_EDGES): aksi halde ust barin
    hemen altinda istenmeyen "genisletme" imleci cikiyor ve basildiginda pencere
    yanlis kenardan boyutlandiriliyordu."""

    HEIGHT = 44
    RESIZE_MARGIN = 6
    # Seritte boyutlandirmaya izin verilen kenarlar. Alt kenar bilerek disaridadir:
    # orasi icerige bakar ve yalnizca surukleme (startSystemMove) yapar.
    RESIZE_EDGES = Qt.TopEdge | Qt.LeftEdge | Qt.RightEdge

    def __init__(self, window):
        super().__init__(window)
        self.setObjectName('customTitleBar')
        self._window = window
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 0, 0)
        row.setSpacing(9)
        self.row = row

    def _edge_at(self, point):
        """Noktayi pencere kenarina esler; kenara yakinsa Qt.Edge doner, degilse None.

        Seridin alt kenari RESIZE_EDGES disinda oldugu icin orada None doner ve
        mousePressEvent suruklemeye (startSystemMove) duser."""
        edge = edges_at(point, self.RESIZE_MARGIN, self.RESIZE_MARGIN,
                        self.width() - self.RESIZE_MARGIN,
                        self.height() - self.RESIZE_MARGIN)
        if edge is None:
            return None
        edge &= self.RESIZE_EDGES
        return edge or None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            edge = self._edge_at(event.position())
            if handle is not None and edge is not None and handle.startSystemResize(edge):
                event.accept()
                return
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        edge = self._edge_at(event.position())
        self.setCursor(resize_cursor(edge) if edge is not None else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.unsetCursor()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._window.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class CaptionButton(QPushButton):
    """Pencere dugmesi (kucult / buyut / geri yukle / kapat).

    Glifler isletim sistemi fontuna bagli kalmadan QPainter ile tam ortalanarak
    cizilir (font fallback'i farkli taban cizgilerine dusup kayma yapiyordu).
    Hover zemini QSS'teki QPushButton#winButton kuralindan gelir."""

    GLYPH = 10

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setObjectName('winButton')
        self.setFixedSize(46, 32)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)

    def set_kind(self, kind):
        self._kind = kind
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # QSS zemini/kenarlik
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        hovered = self.underMouse()
        color = THEME['accent'] if hovered else THEME['secondary']
        painter.setPen(QColor(color))
        size = self.GLYPH
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        half = size / 2.0
        if self._kind == 'min':
            painter.drawLine(QPointF(cx - half, cy), QPointF(cx + half, cy))
        elif self._kind == 'max':
            painter.drawRect(QRectF(cx - half, cy - half, size, size))
        elif self._kind == 'restore':
            painter.drawRect(QRectF(cx - half, cy - half + 3, size - 3, size - 3))
            painter.drawRect(QRectF(cx - half + 3, cy - half, size - 3, size - 3))
        else:  # kapat
            painter.drawLine(QPointF(cx - half, cy - half), QPointF(cx + half, cy + half))
            painter.drawLine(QPointF(cx + half, cy - half), QPointF(cx - half, cy + half))
        painter.end()


class ResizeEdges(QObject):
    """Frameless pencerede kenardan boyutlandirma tutamaclarini yonetir.

    Pencere kenarlarina yerlestirilen saydam tutamaclar basildiginda
    QWindow.startSystemResize(edges) cagrilir; boylece boyutlandirma ve imlec
    isletim sistemine devredilir. Tutamaclar 6px kalinliginda oldugu icin
    icerik etkilesimini engellemez. Pencere buyutuldugunde gizlenir."""

    MARGIN = 6
    CORNER = 12

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._handles = []
        specs = (
            ('left', Qt.LeftEdge),
            ('right', Qt.RightEdge),
            ('top', Qt.TopEdge),
            ('bottom', Qt.BottomEdge),
            ('top_left', Qt.TopEdge | Qt.LeftEdge),
            ('top_right', Qt.TopEdge | Qt.RightEdge),
            ('bottom_left', Qt.BottomEdge | Qt.LeftEdge),
            ('bottom_right', Qt.BottomEdge | Qt.RightEdge),
        )
        for name, edge in specs:
            handle = QWidget(window)
            handle.setObjectName('resizeHandle')
            handle.setCursor(resize_cursor(edge))
            handle.setMouseTracking(True)
            handle.setAttribute(Qt.WA_NoSystemBackground, True)
            handle.setAttribute(Qt.WA_TranslucentBackground, True)
            handle.installEventFilter(self)
            handle._edge = edge
            self._handles.append((name, handle))
        self.reposition()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemResize(obj._edge):
                return True
        return super().eventFilter(obj, event)

    def reposition(self):
        """Tutamaclari pencere kenarlarina yerlestirir; buyutulmusse gizler."""
        if self._window.isMaximized() or self._window.isFullScreen():
            for _name, handle in self._handles:
                handle.hide()
            return
        width = self._window.width()
        height = self._window.height()
        m, c = self.MARGIN, self.CORNER
        boxes = {
            'left': (0, 0, m, height),
            'right': (width - m, 0, m, height),
            'top': (0, 0, width, m),
            'bottom': (0, height - m, width, m),
            'top_left': (0, 0, c, c),
            'top_right': (width - c, 0, c, c),
            'bottom_left': (0, height - c, c, c),
            'bottom_right': (width - c, height - c, c, c),
        }
        for name, handle in self._handles:
            handle.setGeometry(*boxes[name])
            handle.show()
            handle.raise_()


class MainWindow(QMainWindow):
    status_ready = Signal(str, bool)  # arka plan model sorgusundan durum rozetine

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Aktar')
        self.resize(1280, 820)
        # Frameless pencere: Windows'un native baslik cubugu yerine kendi seridimiz
        # cizilir (sürükleme/snap isletim sistemine devredilir).
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMouseTracking(True)
        self._maximized = False
        self.video = None
        self.streams = []
        self.source_subtitle = None
        self.series_slug = ''
        self._chapter_glossary = []
        self._candidates = []
        self._thread = None
        self._worker = None
        self._run_worker = None
        self._running = False
        self.loaded_models = []
        self._progress_animation = QVariantAnimation(self)
        self._progress_animation.setDuration(280)
        self._progress_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._progress_animation.valueChanged.connect(
            lambda value: self.progress.setValue(int(value)))
        self._build()
        self.status_ready.connect(self._set_status)
        self.reload_series()
        self.refresh_loaded_models()

    # --- arayuz kurulumu --------------------------------------------------
    def _build(self):
        central = QFrame()  # QWidget QSS border cizmez; dis cerceve icin QFrame sart
        central.setObjectName('appRoot')
        self.setCentralWidget(central)
        central.setMouseTracking(True)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._outer = outer

        self._build_title_bar()

        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        outer.addWidget(self.splitter, 1)

        top = QWidget()
        layout = QVBoxLayout(top)
        layout.setContentsMargins(16, 16, 16, 4)
        layout.setSpacing(14)

        self.drop = DropArea()
        self.drop.dropped.connect(self.open_video)
        self.drop.select_requested.connect(self.choose_video)
        layout.addWidget(self.drop, 1)

        layout.addWidget(self._build_file_card())
        layout.addWidget(self._build_stream_card(), 1)
        layout.addWidget(self._build_action_card())

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 4, 16, 16)
        bottom_layout.setSpacing(0)
        bottom_layout.addWidget(self._build_console())

        self.splitter.addWidget(top)
        self.splitter.addWidget(bottom)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([520, 220])

        self.toast = Toast(central)
        self._show_empty_state(True)

        # Frameless pencerede icerik ile pencere sinirini ayristiran dis cerceve:
        # gorunmez kenar tutamaclarindan olusur, en son kurulur ve en uste kaldirilir.
        self._edges = ResizeEdges(self)

    def _build_file_card(self):
        self.file_card, row = card(spacing=14, margins=(16, 14, 16, 14), horizontal=True)
        mark = QLabel()
        mark.setFixedSize(42, 42)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet('background:%s; border-radius:10px;' % THEME['panel_alt'])
        mark.setPixmap(tinted_icon('film', THEME['accent'], 18).pixmap(18, 18))
        row.addWidget(mark)

        column = QVBoxLayout()
        column.setSpacing(3)
        self.file_name = QLabel('')
        self.file_name.setObjectName('fileName')
        self.drop_path = QLabel('')
        self.drop_path.setObjectName('filePath')
        column.addWidget(self.file_name)
        column.addWidget(self.drop_path)
        row.addLayout(column, 1)

        change = QPushButton('Değiştir')
        change.setObjectName('ghost')
        change.clicked.connect(self.choose_video)
        row.addWidget(change)
        return self.file_card

    def _build_stream_card(self):
        self.stream_card, column = card(spacing=0, margins=(0, 0, 0, 0))
        head = QHBoxLayout()
        head.setContentsMargins(16, 0, 16, 0)
        head.setSpacing(10)
        head.addWidget(section_label('Altyazı Akışları'))
        self.stream_count = QLabel('')
        self.stream_count.setObjectName('countPill')
        head.addWidget(self.stream_count)
        head.addStretch(1)
        self.stream_info = QLabel('')
        self.stream_info.setObjectName('hint')
        head.addWidget(self.stream_info)
        header_row = QWidget()
        header_row.setFixedHeight(46)
        header_row.setLayout(head)
        column.addWidget(header_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['', 'Codec', 'Dil', 'Başlık', 'Durum'])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 46)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setHighlightSections(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(THEME['row_height'])
        self.table.setShowGrid(False)
        highlight_rows(self.table)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.itemChanged.connect(self.on_item_changed)
        column.addWidget(self.table, 1)
        return self.stream_card

    def _build_action_card(self):
        frame, row = card(spacing=14, margins=(14, 12, 14, 12), horizontal=True)
        self.chapter_button = HoverIconButton('Bölüm terimleri...')
        self.chapter_button.setTintedIcon('terms', THEME['secondary'])
        self.chapter_button.clicked.connect(self.edit_chapter_glossary)
        row.addWidget(self.chapter_button)

        self.analysis_check = ToggleSwitch('Ön analiz yap')
        self.analysis_check.setToolTip('Çeviriden önce yapay zekâyla Türkçe terim ve '
                                       'süreklilik önerileri üretir.')
        row.addWidget(self.analysis_check)
        row.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(300)
        row.addWidget(self.progress, 1)

        self.progress_value = QLabel('0 / 0')
        self.progress_value.setObjectName('progressValue')
        self.progress_value.setMinimumWidth(86)
        self.progress_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.progress_value)

        self.pause_button = HoverIconButton('')
        self.pause_button.setObjectName('iconOnly')
        self.pause_button.setTintedIcon('pause', THEME['text'])
        self.pause_button.setToolTip('Duraklat')
        self.pause_button.clicked.connect(self.toggle_pause)
        self.pause_button.setEnabled(False)
        row.addWidget(self.pause_button)

        self.translate_button = QPushButton('Çevir')
        self.translate_button.setObjectName('primary')
        self.translate_button.clicked.connect(self.toggle_translate)
        row.addWidget(self.translate_button)
        return frame

    def _build_console(self):
        frame, column = card(spacing=0, margins=(0, 0, 0, 0))
        frame.setMinimumHeight(150)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.tabs.addTab(self.log, 'Konsol')

        analysis_page = QWidget()
        analysis_layout = QVBoxLayout(analysis_page)
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        self.analysis_view = QPlainTextEdit()
        self.analysis_view.setReadOnly(True)
        self.analysis_view.setPlaceholderText('Ön analiz sonuçları burada görünür.')
        analysis_layout.addWidget(self.analysis_view, 1)
        self.tabs.addTab(analysis_page, 'Ön Analiz')

        clear = HoverIconButton('')
        clear.setObjectName('iconFlat')
        clear.setTintedIcon('trash', THEME['muted'], 14)
        clear.setToolTip('Günlüğü temizle')
        clear.setFixedSize(30, 30)
        clear.clicked.connect(self.log.clear)
        corner = QWidget()
        corner_row = QHBoxLayout(corner)
        corner_row.setContentsMargins(0, 0, 10, 0)
        corner_row.addWidget(clear)
        self.tabs.setCornerWidget(corner, Qt.TopRightCorner)

        column.addWidget(self.tabs, 1)
        return frame

    def _build_title_bar(self):
        """Frameless pencerenin ozel baslik seridi: marka + gruplar + pencere dugmeleri.

        Surukleme ve Aero Snap TitleBar.mousePressEvent -> startSystemMove ile
        isletim sistemine devredilir. Dikey sohbet: prototip kapsaminda yalnizca
        serit; kenardan boyutlandirma sonraki adimda eklenecek."""
        self.title_bar = TitleBar(self)
        self._outer.addWidget(self.title_bar)
        row = self.title_bar.row

        brand = QWidget()
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(2, 0, 10, 0)
        brand_row.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(_brand_pixmap(24))
        brand_row.addWidget(logo)
        brand_text = QLabel(
            'aktar<span style="color:%s; font-size:16px;">.</span>' % THEME['accent'])
        brand_text.setTextFormat(Qt.RichText)
        brand_text.setObjectName('brandText')
        brand_row.addWidget(brand_text)
        row.addWidget(brand)

        self.open_button = HoverIconButton('Video Seç')
        self.open_button.setTintedIcon('upload', THEME['secondary'], 18)
        self.open_button.clicked.connect(self.choose_video)
        row.addWidget(self.open_button)

        label = QLabel('SERİ')
        label.setObjectName('groupLabel')
        row.addWidget(label)
        self.series_combo = DropdownCombo()
        self.series_combo.setMinimumWidth(210)
        self.series_combo.setMaximumWidth(260)
        self.series_combo.currentIndexChanged.connect(self.on_series_changed)
        row.addWidget(self.series_combo)
        self.term_button = HoverIconButton('Terim')
        self.term_button.setTintedIcon('terms', THEME['secondary'])
        self.term_button.setToolTip('Seri terim sözlüğünü düzenle')
        self.term_button.clicked.connect(self.edit_series_glossary)
        row.addWidget(self.term_button)
        self.continuity_button = HoverIconButton('Süreklilik')
        self.continuity_button.setTintedIcon('continuity', THEME['secondary'])
        self.continuity_button.setToolTip('Seri süreklilik kararlarını düzenle')
        self.continuity_button.clicked.connect(self.edit_series_decisions)
        row.addWidget(self.continuity_button)

        spacer = QWidget()
        spacer.setStyleSheet('background:transparent;')
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(spacer)

        self.status_pill = QLabel('LM Studio sorgulanıyor...')
        self.status_pill.setObjectName('statusPill')
        self.status_pill.setToolTip('Bağlantı ve yüklü model durumu')
        row.addWidget(self.status_pill)

        self.settings_button = HoverIconButton('')
        self.settings_button.setObjectName('iconOnly')
        self.settings_button.setIcon(_settings_svg_icon())
        self.settings_button.setHoverIcon(_settings_svg_icon(color=THEME['accent']))
        self.settings_button.setToolTip('LM Studio, model ve çeviri ayarları')
        self.settings_button.clicked.connect(self.show_settings)
        row.addWidget(self.settings_button)

        controls = QWidget()
        controls_row = QHBoxLayout(controls)
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(0)
        self.min_button = self._window_button('min', 'Küçült', self.showMinimized)
        controls_row.addWidget(self.min_button)
        self.max_button = self._window_button('max', 'Büyüt', self.toggle_maximize)
        controls_row.addWidget(self.max_button)
        self.close_button = self._window_button('close', 'Kapat', self.close,
                                                object_name='winClose')
        controls_row.addWidget(self.close_button)
        row.addWidget(controls)

    def _window_button(self, kind, tooltip, slot, object_name='winButton'):
        button = CaptionButton(kind)
        button.setObjectName(object_name)
        button.setToolTip(tooltip)
        button.clicked.connect(slot)
        return button

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._sync_window_state()

    def _sync_window_state(self):
        """Buyut/kucult dugmesinin simgesini ve arac ipucunu pencere durumuna esitler."""
        maximized = self.isMaximized()
        self._maximized = maximized
        if hasattr(self, 'max_button'):
            self.max_button.set_kind('restore' if maximized else 'max')
            self.max_button.setToolTip('Geri Yükle' if maximized else 'Büyüt')
        if getattr(self, '_edges', None) is not None:
            self._edges.reposition()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self._sync_window_state()

    # --- durum gecisleri --------------------------------------------------
    def _show_empty_state(self, empty):
        """Video yokken buyuk birakma alani, varken dosya karti + akis tablosu."""
        self.drop.setVisible(bool(empty))
        self.file_card.setVisible(not empty)
        self.stream_card.setVisible(not empty)

    def _set_status(self, text, connected=None):
        """Arac cubugunun sagindaki durum rozeti (model + baglanti)."""
        self.status_pill.setText(str(text))
        if connected is None:
            return
        self.status_pill.setStyleSheet(
            'QLabel#statusPill { color:%s; border-color:%s; }'
            % ((THEME['secondary'], THEME['drop_border']) if connected
               else (THEME['muted'], THEME['border'])))
        self.status_pill.setToolTip(
            ('Bağlı - ' if connected else '') + str(text))

    @staticmethod
    def _status_text(cfg):
        """Durum rozeti metni: '<model> · <host>' (config'ten)."""
        host = str(cfg['base_url']).split('//')[-1].rstrip('/')
        if host.endswith('/v1'):
            host = host[:-3]
        return str(cfg['model']) + ' · ' + host

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_window_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, '_edges', None) is not None:
            self._edges.reposition()
        if getattr(self, 'toast', None) is not None and self.toast.isVisible():
            self.toast._place()

    # --- seri -------------------------------------------------------------
    def reload_series(self):
        current = self.series_slug
        self.series_combo.blockSignals(True)
        self.series_combo.clear()
        self.series_combo.addItem(NONE_SERIES)
        for slug, data in series.list_series().items():
            self.series_combo.addItem(data['title'], slug)
        self.series_combo.addItem(NEW_SERIES)
        self.series_combo.blockSignals(False)
        self.series_slug = current
        self._select_series(current)

    def _select_series(self, slug):
        index = self.series_combo.findData(slug)
        self.series_combo.setCurrentIndex(index if index >= 0 else 0)
        self.series_slug = self.series_combo.currentData() or ''

    def on_series_changed(self, _index):
        data = self.series_combo.currentData()
        if data == NEW_SERIES or self.series_combo.currentText() == NEW_SERIES:
            self.create_series()
            return
        self.series_slug = data or ''
        if self.series_slug:
            self.append('Seri seçildi: ' + self.series_combo.currentText())

    def create_series(self):
        suggested = series.guess_series_title(self.video) if self.video is not None else ''
        title, ok = QInputDialog.getText(self, 'Yeni seri', 'Seri başlığı:', text=suggested)
        if not ok or not title.strip():
            self._select_series(self.series_slug)
            return
        hints = []
        if self.video is not None:
            hints.append(self.video.parent.name)
        try:
            data = series.create_series(title.strip(), hints)
        except (ValueError, RuntimeError) as error:
            self.warn(str(error))
            self._select_series(self.series_slug)
            return
        self.series_slug = series.slugify(title.strip())
        self.reload_series()
        self._select_series(self.series_slug)
        self.append('Seri oluşturuldu: ' + data['title'])

    def edit_series_glossary(self):
        if not self.series_slug:
            self.warn('Önce bir seri seçin veya yeni seri oluşturun.')
            return
        data = series.load_series(self.series_slug)
        dialog = GlossaryDialog(self, data.get('glossary', []),
                                title='Seri Terimleri - ' + data['title'])
        if dialog.exec() != QDialog.Accepted:
            return
        old = {str(item.get('source', '')).casefold(): item
               for item in data.get('glossary', []) if isinstance(item, dict)}
        updated = []
        for item in dialog.values():
            saved = dict(old.get(item['source'].casefold(), {}))
            saved.update(item); updated.append(saved)
        data['glossary'] = updated
        try:
            series.save_series(data, slug=self.series_slug)
        except RuntimeError as error:
            self.warn(str(error))
            return
        self.append('Seri terimleri güncellendi.')

    def edit_series_decisions(self):
        if not self.series_slug:
            self.warn('Önce bir seri seçin veya yeni seri oluşturun.')
            return
        data = series.load_series(self.series_slug)
        current = '\n'.join(str(item) for item in data.get('decisions', []) if str(item).strip())
        value, ok = QInputDialog.getMultiLineText(
            self, 'Seri Süreklilik Kararları - ' + data['title'],
            'Her satıra bir kalıcı karar yazın (sen/siz, isim yazımı, ses, tekrar eden kalıp):',
            current)
        if not ok:
            return
        data['decisions'] = list(dict.fromkeys(
            line.strip() for line in value.splitlines() if line.strip()))
        try:
            series.save_series(data, slug=self.series_slug)
        except RuntimeError as error:
            self.warn(str(error)); return
        self.append('Seri süreklilik kararları güncellendi.')

    # --- video ------------------------------------------------------------
    def choose_video(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Video Seç', '', VIDEO_FILTER)
        if path:
            self.open_video(path)

    def open_video(self, path):
        if not path:
            return
        path = Path(path)
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            self.warn('Bu dosya bir video değil: ' + path.name)
            return
        self.video = path
        self.file_name.setText(path.name)
        self.drop_path.setText(str(path.parent))
        self._show_empty_state(False)
        self.table.setRowCount(0)
        self.streams = []
        self.source_subtitle = None
        self.stream_info.setText('')
        self.stream_count.setText('')
        self.progress.setValue(0)
        self.progress_value.setText('0 / 0')
        self.append('Video açıldı: ' + str(path))
        if not self.series_slug:
            matches = series.matching_series(path)
            if len(matches) == 1:
                self._select_series(matches[0])
                self.append('Seri önerisi: ' + self.series_combo.currentText())
            elif len(matches) > 1:
                labels = [series.load_series(slug)['title'] for slug in matches]
                choice, ok = QInputDialog.getItem(
                    self, 'Seri Seç', 'Birden fazla seri eşleşti:', labels, 0, False)
                if ok and choice:
                    self._select_series(matches[labels.index(choice)])
        self.start_probe(path)

    def start_probe(self, path):
        self._start_worker(ProbeWorker(path), self.probe_finished)

    @Slot(object, str)
    def probe_finished(self, streams, error):
        if error:
            self.warn(error)
            return
        self.streams = streams or []
        self.populate(self.streams)
        if not self.streams:
            self.append('Bu videoda altyazı akışı yok.')

    def populate(self, streams):
        self.table.blockSignals(True)
        self.table.setRowCount(len(streams))
        for row, stream in enumerate(streams):
            if stream['image']:
                status = 'Görüntü tabanlı - desteklenmiyor'
            elif stream['supported']:
                status = stream['extension'].upper()
            else:
                status = 'Desteklenmiyor'
            pick = QTableWidgetItem('')
            if stream['supported']:
                pick.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                pick.setCheckState(Qt.Unchecked)
            else:
                pick.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 0, pick)
            values = [stream['codec'], stream['language'] or '-',
                      stream['title'] or '-', status]
            tone = THEME['text'] if stream['supported'] else THEME['disabled']
            for offset, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled)
                item.setForeground(QColor(tone))
                if offset == 1:
                    item.setFont(QFont(_MONO_FAMILY, THEME['mono_size'] - 1))
                if offset == 4 and stream['supported']:
                    item.setForeground(QColor(THEME['accent']))
                self.table.setItem(row, offset, item)
        self.table.blockSignals(False)
        supported = sum(1 for stream in streams if stream['supported'])
        self.stream_count.setText(f'{len(streams)} akış')
        self.stream_info.setText(f'{supported} metin tabanlı - tek akış işaretlenebilir')

    def on_item_changed(self, item):
        """Secim sutununda TEK akis isaretlenebilir; digerleri otomatik kalkar."""
        if item.column() != 0 or item.checkState() != Qt.Checked:
            return
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            if cell is not None and row != item.row():
                cell.setCheckState(Qt.Unchecked)
        self.table.blockSignals(False)

    def selected_stream(self):
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            if cell is not None and cell.checkState() == Qt.Checked and row < len(self.streams):
                return self.streams[row]
        return None

    # --- ceviri -----------------------------------------------------------
    def edit_chapter_glossary(self):
        dialog = GlossaryDialog(self, self._chapter_glossary, title='Bölüme Özel Terimler')
        if dialog.exec() != QDialog.Accepted:
            return
        self._chapter_glossary = dialog.values()
        self.append(f'Bölüm terimleri: {len(self._chapter_glossary)} giriş')

    def toggle_translate(self):
        if self._running:
            if self._run_worker is not None:
                self._run_worker.request_cancel()
                self.append('İptal isteniyor...')
            return
        stream = self.selected_stream()
        if stream is None:
            self.warn('Önce bir altyazı akışı işaretleyin.')
            return
        if stream['image']:
            self.warn('Görüntü tabanlı altyazı şu anda desteklenmiyor.')
            return
        if not stream['supported']:
            self.warn('Desteklenmeyen altyazı codec: ' + stream['codec'])
            return
        self.start_run(stream)

    def start_run(self, stream):
        glossary = list(self._chapter_glossary)
        decisions = []
        if self.series_slug:
            # Bolum terimleri seri terimlerini EZER (sonraki katman kazanir).
            glossary = merge_glossaries(series.series_glossary(self.series_slug), glossary)
            decisions = series.series_decisions(self.series_slug)
        worker = RunWorker(self.video, stream, glossary, decisions, self.analysis_check.isChecked())
        worker.progress.connect(self.update_progress)
        worker.log.connect(self.append)
        worker.analysis.connect(self.show_analysis)
        worker.review_requested.connect(self.handle_review)
        worker.finished.connect(self.run_finished)
        self._run_worker = worker
        self._running = True
        self.translate_button.setEnabled(False)
        self.translate_button.setText('Çevriliyor')
        self.pause_button.setEnabled(True)
        self.chapter_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress_value.setText('0 / 0')
        self._start_worker(worker, None)

    @Slot(int, int)
    def update_progress(self, done, total):
        """Ilerleme cubugu deger atlamak yerine yumusak gecer (QSS transition yok)."""
        self.progress.setMaximum(max(1, total))
        self._progress_animation.stop()
        self._progress_animation.setStartValue(self.progress.value())
        self._progress_animation.setEndValue(int(done))
        self._progress_animation.start()
        self.progress_value.setText(f'{done} / {total}')

    @Slot(object)
    def show_analysis(self, candidates):
        self._candidates = dict(candidates or {})
        lines = ['Ön analiz - yapay zekâ önerileri:', '']
        for item in self._candidates.get('terms', []):
            lines.append(f"- {item['source']} -> {item['target']} "
                         f"[{item.get('type', 'term')}, x{item.get('count', 1)}]")
        if self._candidates.get('decisions'):
            lines.extend(['', 'Süreklilik:'])
            lines.extend('- ' + item['value'] for item in self._candidates['decisions'])
        if not self._candidates.get('terms') and not self._candidates.get('decisions'):
            lines.append('Aday terim bulunamadı.')
        self.analysis_view.setPlainText('\n'.join(lines))
        self.tabs.setCurrentIndex(1)

    @Slot(str, object)
    def handle_review(self, phase, candidates):
        """On/son analiz onerilerini onaya sunar; worker diyalogu bekler."""
        worker = self._run_worker
        if worker is None:
            return
        try:
            current = []
            title = 'Ön Analiz Önerileri' if phase == 'pre' else 'Çeviri Sonu Önerileri'
            if self.series_slug:
                data = series.load_series(self.series_slug)
                current = data.get('glossary', [])
                title += ' - ' + data['title']
            dialog = GlossaryReviewDialog(
                self, proposed=candidates.get('terms', []),
                decisions=candidates.get('decisions', []), current=current,
                title=title, has_series=bool(self.series_slug))
            values, accepted = dialog.exec_and_values()
            worker._review_values = values if accepted else None
            if accepted and self.series_slug:
                terms = [dict(item,
                              origin=('pre_analysis' if phase == 'pre' else 'post_analysis'),
                              first_seen=(self.video.name if self.video else ''), locked=True)
                         for item in (values or {}).get('series_terms', [])]
                decisions = (values or {}).get('series_decisions', [])
                series.add_knowledge(self.series_slug, terms, decisions,
                                     self.video.name if self.video else '')
                self.append('Seri terimleri/süreklilik kararları güncellendi.')
        except Exception as error:
            # Bir arayuz hatasi ceviri thread'ini sonsuza kadar bekletmemeli.
            worker._review_values = None
            self.append('Öneri penceresi açılamadı: ' + str(error))
            self.warn('Öneri penceresi açılamadı: ' + str(error))
        finally:
            worker._review_event.set()

    # --- ayarlar ----------------------------------------------------------
    def show_settings(self):
        dialog = SettingsDialog(load_config(), self.loaded_models, self, locked=self._running)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            value = dialog.value()
            validate_config(value)
            save_json(APP_DIR / 'config.json', value)
        except (RuntimeError, ValueError, OSError) as error:
            self.warn('Ayarlar kaydedilemedi: ' + str(error))
            return
        self.append('Ayarlar kaydedildi.')
        # Durum rozeti yeni modele gore aninda guncellenir; baglanti durumu
        # arka plan sorgusuyla (refresh_loaded_models -> status_ready) duzeltilir.
        self._set_status(self._status_text(dict(load_config())), None)
        self.refresh_loaded_models()

    def refresh_loaded_models(self):
        """Arka planda LM Studio'daki yuklu modelleri sorgular (Ayarlar icin)."""
        cfg = dict(load_config())
        cfg['timeout_seconds'] = min(8, int(cfg['timeout_seconds']))

        def probe():
            from app_core import Client
            try:
                names = Client(cfg, lambda _message: None).models()
            except (RuntimeError, ValueError):
                names = []
            self.loaded_models = list(names)
            self.status_ready.emit(self._status_text(cfg), bool(names))

        threading.Thread(target=probe, name='aktar-model-probe', daemon=True).start()

    @Slot(str, str)
    def run_finished(self, output, error):
        self._run_worker = None
        self._running = False
        self.translate_button.setEnabled(True)
        self.translate_button.setText('Çevir')
        self.pause_button.setEnabled(False)
        self._set_pause_button(paused=False)
        self.chapter_button.setEnabled(True)
        if error:
            self.append(error)
            if not any(marker in error.casefold() for marker in ('ptal', 'kapatıl')):
                self.warn(error)
            return
        self.append('Çeviri yazıldı: ' + output)
        if self.series_slug and self.video is not None:
            try:
                series.add_episode(self.series_slug, self.video.name)
            except (RuntimeError, ValueError) as series_error:
                self.append('UYARI: bölüm kaydedilemedi: ' + str(series_error))
        self.complete(output)

    def toggle_pause(self):
        if self._run_worker is None:
            return
        if self._run_worker.pause.pause_requested:
            self._run_worker.request_resume()
            self._set_pause_button(paused=False)
            self.append('Devam ediliyor.')
        else:
            self._run_worker.request_pause()
            self._set_pause_button(paused=True)
            self.append('Duraklatıldı.')

    def _set_pause_button(self, paused):
        """Ikon tabanli duraklat/devam dugmesi (metin yerine ikon + arac ipucu)."""
        name = 'play' if paused else 'pause'
        self.pause_button.setIcon(tinted_icon(name, THEME['text']))
        self.pause_button.setHoverIcon(tinted_icon(name, THEME['accent']))
        self.pause_button.setToolTip('Devam' if paused else 'Duraklat')

    # --- worker altyapisi -------------------------------------------------
    def _start_worker(self, worker, finished_slot):
        self._thread = QThread(self)
        self._worker = worker
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        if finished_slot is not None:
            worker.finished.connect(finished_slot)
        worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def closeEvent(self, event):
        if self._run_worker is not None:
            self._run_worker.request_cancel()
            self._thread.quit()
            self._thread.wait(5000)
        event.accept()

    def warn(self, message):
        self._message_box('Uyarı', str(message))

    def complete(self, output):
        """Basarili sonucta kullanicinin 'Tamam' ile kapattigi modal bildirim."""
        self._message_box('Çeviri tamamlandı',
                          'Çeviri başarıyla tamamlandı. Çıktı: '
                          + Path(str(output)).name)

    def _message_box(self, title, message, detail=''):
        box = QMessageBox(self)
        box.setWindowTitle('Aktar - ' + title)
        box.setWindowIcon(window_icon())
        box.setIconPixmap(_brand_pixmap(48))
        box.setText(str(message))
        if detail:
            box.setInformativeText(str(detail))
        button = box.addButton('Tamam', QMessageBox.ButtonRole.AcceptRole)
        button.setObjectName('primary')
        box.exec()

    def append(self, message):
        self.log.appendPlainText(str(message))


def main():
    app = QApplication(sys.argv)
    # Windows'un yerel stili QSS'in bir kismini (spinbox, combobox oku, checkbox
    # gostergesi, progress kosesi) yok sayar; Fusion her platformda ayni sonucu verir.
    app.setStyle('Fusion')
    _theme, style = build_style()
    app.setStyleSheet(style)
    app.setWindowIcon(window_icon())
    font = QFont(_theme['ui_font'])
    font.setPixelSize(THEME['body_size'])
    app.setFont(font)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
