"""Soru Sor sekmesi paneli (F45/F46): solda oynatici, sagda atifli sohbet.

Ana penceredeki "Soru Sor" sekmesinin icerigidir (F46'dan once ayri pencereydi).
Duzen:
  - Sol kart: QVideoWidget + bolum isaretli arama cubugu + [oynat] [ses] 0:03 / 20:29 [bolum]
  - Sag kart: baslik, transkript kaynagi, hazirlik durumu, sohbet (QTextBrowser),
    onerilen soru dugmeleri, soru alani.

Is mantigi qa.py'dedir (Qt'siz); burada yalnizca oynatici, sohbet gorunumu ve
arka plan worker'lari vardir. Cevaptaki zaman atiflari "t:<saniye>" baglantisidir;
tiklaninca oynatici o ana gider. QtMultimedia yalnizca Soru Sor sekmesi ilk kez
acilinca yuklenir (gui.MainWindow._ensure_qa_panel lazy import eder). Her video
icin yeni panel kurulur; video degisince eski panel `retire()` ile durdurulur.
"""
from __future__ import annotations

import html
import re
import threading
from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, QPoint, QPointF, QRectF, Qt, QThread, QTimer, QUrl,
                            Signal, Slot)
from PySide6.QtGui import QActionGroup, QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QProgressBar,
                               QSlider, QSplitter,
                               QTextBrowser, QToolTip, QVBoxLayout, QWidget)

import qa
import speech
from app_core import GracefulStop, load_config, save_json
from gui import (THEME, ClickableLabel, DropdownCombo, HoverIconButton, card, section_label,
                 tinted_icon)
from media import audio_label, audio_streams, sidecar_subtitles, subtitle_streams

GREETING = ('Merhaba! İzlediğiniz videoyla ilgili sorularınız mı var? '
            'Size yardımcı olmaktan memnuniyet duyarım.')
NO_SUBTITLE = ('Bu videoda metin tabanlı altyazı yok. Soru sormak için konuşmayı sesten '
               'metne çevirebilirsiniz (Whisper; ilk kullanımda model indirilir).')
WHISPER_KEY = 'whisper'  # transkript secicisi ve CC menusu icin kaynak anahtari
SEEK_STEP_MS = 5000
SUBTITLE_TICK_MS = 120  # oynarken altyazi metninin yenilenme araligi

QA_STYLE = """
QFrame#videoSurface {{ background:#000; border:0; border-top-left-radius:{radius}px;
                       border-top-right-radius:{radius}px; }}
QLabel#timeLabel {{ color:{secondary}; font-family:'{mono_font}'; font-size:{mono_size}px; }}
QLabel#chapterLabel {{ color:{secondary}; background:{panel_alt}; border-radius:12px;
                       padding:4px 11px; font-size:12px; }}
QTextBrowser#qaChat {{ background:transparent; border:0; color:{text}; padding:4px 14px; }}
QLabel#qaChip {{ background:transparent; border:1px solid {drop_border}; border-radius:15px;
                 color:{text}; padding:6px 14px; }}
QLabel#qaChip:hover {{ background:{panel_alt}; color:{accent}; border-color:{accent_edge}; }}
QWidget#qaChips, QWidget#qaSource {{ background:transparent; }}
QLabel#qaFoot {{ color:{muted}; font-size:11px; }}
QSlider::groove:horizontal {{ height:4px; background:{drop_border}; border-radius:2px; }}
QSlider::sub-page:horizontal {{ height:4px; background:{secondary}; border-radius:2px; }}
QSlider::handle:horizontal {{ width:12px; margin:-4px 0; background:{text}; border-radius:6px; }}
QMenu {{ background:{panel}; border:1px solid {drop_border}; padding:6px; }}
QMenu::item {{ padding:7px 26px 7px 26px; border-radius:6px; color:{text}; }}
QMenu::item:selected {{ background:{panel_alt}; color:{accent}; }}
QMenu::item:disabled {{ color:{muted}; background:transparent; }}
QMenu::separator {{ height:1px; background:{border}; margin:5px 8px; }}
"""


# --- sohbet gorunumu (HTML) -------------------------------------------------
def _inline_html(text):
    """Model metnini guvenli HTML'e cevirir: kacis, **kalin**, madde imleri, satir sonlari."""
    value = html.escape(text, quote=False)
    value = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', value)
    value = re.sub(r'(?m)^[ \t]*#{1,6}[ \t]+(.+)$', r'<b>\1</b>', value)
    value = re.sub(r'(?m)^([ \t]*)[-*][ \t]+', r'\1• ', value)
    return value.replace('\n', '<br>')


def citation_html(cite):
    return ('<a href="t:%.3f" style="color:%s; text-decoration:none; font-weight:600;">'
            '<span style="background-color:%s;">%s</span></a>'
            % (cite['start'], THEME['accent'], THEME['panel_alt'], html.escape(cite['label'])))


def answer_html(parts):
    """qa.split_citations ciktisi -> zaman baglantili HTML."""
    out = []
    for kind, value in parts:
        if kind == 'cite':
            out.append(', '.join(citation_html(item) for item in value))
        else:
            out.append(_inline_html(value))
    return ''.join(out)


def chat_html(entries):
    """Sohbet kayitlarini tek HTML belgesine cevirir (her degisiklikte yeniden cizilir)."""
    blocks = []
    for kind, value in entries:
        if kind == 'user':
            blocks.append(
                '<table width="100%" cellspacing="0" cellpadding="0" style="margin:10px 0 6px 0;">'
                '<tr><td align="right"><table cellspacing="0" cellpadding="9" bgcolor="{bg}">'
                '<tr><td>{text}</td></tr></table></td></tr></table>'.format(
                    bg=THEME['panel_alt'], text=html.escape(value)))
        elif kind == 'assistant':
            blocks.append('<p style="margin:6px 0 14px 0;">' + answer_html(value) + '</p>')
        elif kind == 'error':
            blocks.append('<p style="margin:6px 0 12px 0; color:%s;">%s</p>'
                          % (THEME['secondary'], html.escape(value)))
        else:  # note / pending
            blocks.append('<p style="margin:6px 0 12px 0; color:%s;"><i>%s</i></p>'
                          % (THEME['muted'], html.escape(value)))
    return ''.join(blocks)


def parse_seek_link(url):
    """'t:754.000' -> 754000 ms; zaman baglantisi degilse None."""
    text = url.toString() if hasattr(url, 'toString') else str(url)
    if not text.startswith('t:'):
        return None
    try:
        return max(0, int(float(text[2:]) * 1000))
    except ValueError:
        return None


# --- arka plan isleri -------------------------------------------------------
class PrepareWorker(QObject):
    """Akis tespiti -> transkript (altyazi veya Whisper, onbellekli) -> video haritasi/ozet."""

    audio_ready = Signal(object)            # ses akislari (media.audio_streams)
    streams_ready = Signal(object, object)  # (akislar, secilen akis; Whisper ise None)
    whisper_progress = Signal(int, int)     # (islenen saniye, toplam saniye)
    whisper_ready = Signal(object)          # speech.transcribe sonucu
    loaded = Signal(object)                 # qa.VideoQA
    progress = Signal(int, int)
    log = Signal(str)
    finished = Signal(object, str)          # (genel ozet, hata)

    def __init__(self, video, stream=None, streams=None, session=None, whisper=False,
                 audio_track=None, audio=None):
        super().__init__()
        self.video = video
        self.stream = stream
        self.streams = streams
        self.session = session
        self.whisper = whisper
        self.audio_track = audio_track  # Whisper ses akisi (GLOBAL index; None: ilk akis)
        self.audio = audio
        self.cancel_event = threading.Event()

    @Slot()
    def run(self):
        try:
            if self.session is None:
                if self.audio is None:
                    try:
                        self.audio_ready.emit(audio_streams(self.video))
                    except (RuntimeError, ValueError):
                        self.audio_ready.emit([])
                streams = self.streams if self.streams is not None else subtitle_streams(self.video)
                stream = None if self.whisper else (self.stream or qa.pick_subtitle_stream(streams))
                cfg = load_config()
                if stream is None and not self.whisper:
                    # Altyazi yok: daha once cikarilmis Whisper transkripti varsa onu kullan.
                    self.whisper = speech.load_cached(self.video, cfg['whisper_model'],
                                                      cfg['whisper_language'],
                                                      audio_track=self.audio_track) is not None
                self.streams_ready.emit(streams, stream)
                if stream is None and not self.whisper:
                    self.finished.emit(None, NO_SUBTITLE)
                    return
                if self.whisper:
                    result = speech.transcribe(
                        self.video, cfg['whisper_model'], cfg['whisper_device'],
                        cfg['whisper_language'], progress=self.whisper_progress.emit,
                        cancelled=self.cancel_event.is_set, log=self.log.emit,
                        cuda_dir=cfg.get('whisper_cuda_dir', ''), audio_track=self.audio_track)
                    self.whisper_ready.emit(result)
                    data, path = qa.load_whisper_session(self.video, result, log=self.log.emit)
                else:
                    data, path = qa.load_subtitle_session(self.video, stream, log=self.log.emit)
                self.session = qa.VideoQA(data, config_provider=load_config, log=self.log.emit,
                                          save=lambda value: save_json(path, value))
                self.loaded.emit(self.session)
            overview = self.session.prepare(progress=self.progress.emit,
                                            cancelled=self.cancel_event.is_set)
        except GracefulStop as stop:
            self.finished.emit(None, str(stop))
            return
        except (RuntimeError, ValueError, OSError) as error:
            self.finished.emit(None, str(error))
            return
        self.finished.emit(overview, '')


class TranscribeWorker(QObject):
    """Yalnizca konusmadan metin (CC menusunden 'Sesten olustur')."""

    progress = Signal(int, int)
    log = Signal(str)
    finished = Signal(object, str)  # (speech.transcribe sonucu, hata)

    def __init__(self, video, audio_track=None):
        super().__init__()
        self.video = video
        self.audio_track = audio_track
        self.cancel_event = threading.Event()

    @Slot()
    def run(self):
        try:
            cfg = load_config()
            result = speech.transcribe(self.video, cfg['whisper_model'], cfg['whisper_device'],
                                       cfg['whisper_language'], progress=self.progress.emit,
                                       cancelled=self.cancel_event.is_set, log=self.log.emit,
                                       cuda_dir=cfg.get('whisper_cuda_dir', ''),
                                       audio_track=self.audio_track)
        except (GracefulStop, RuntimeError, ValueError, OSError) as error:
            self.finished.emit(None, str(error))
            return
        self.finished.emit(result, '')


class AskWorker(QObject):
    finished = Signal(object, str)  # (tur, hata)

    def __init__(self, session, question):
        super().__init__()
        self.session = session
        self.question = question

    @Slot()
    def run(self):
        try:
            turn = self.session.ask(self.question)
        except (GracefulStop, RuntimeError, ValueError, OSError) as error:
            self.finished.emit(None, str(error))
            return
        self.finished.emit(turn, '')


class SubtitleLoadWorker(QObject):
    """Secilen altyazi kaynagini (video akisi veya dosya) gosterim icin yukler."""

    finished = Signal(str, object, str)  # (kaynak anahtari, qa.SubtitleTimeline, hata)

    def __init__(self, video, source):
        super().__init__()
        self.video = video
        self.source = source

    @Slot()
    def run(self):
        try:
            if self.source['kind'] == 'stream':
                segments = qa.subtitle_segments(self.video, self.source['stream'], keep_lines=True)
            else:
                segments = qa.file_segments(self.source['path'])
        except (RuntimeError, ValueError, OSError) as error:
            self.finished.emit(self.source['key'], None, str(error))
            return
        self.finished.emit(self.source['key'], qa.SubtitleTimeline(segments), '')


def subtitle_sources(video, streams):
    """CC menusu kaynaklari: videodaki metin akislari + videonun yanindaki dosyalar."""
    sources = []
    for item in streams or []:
        if not item.get('supported'):
            continue
        label = ' · '.join(part for part in (item.get('language') or '', item.get('title') or '',
                                             (item.get('extension') or '').upper()) if part)
        sources.append({'key': f'stream:{item["index"]}', 'kind': 'stream', 'stream': item,
                        'label': label or ('Akış ' + str(item['index']))})
    for path in sidecar_subtitles(video):
        sources.append({'key': 'file:' + str(path), 'kind': 'file', 'path': path,
                        'label': path.name})
    return sources


# --- oynatici parcalari -----------------------------------------------------
class SeekBar(QWidget):
    """Bolum (chapter) araliklari isaretli arama cubugu; tikla/surukle ile atlar."""

    seek_requested = Signal(int)  # ms
    MARGIN = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(22)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._duration = 0
        self._position = 0
        self._marks = []  # [(saniye, baslik)]
        self._dragging = False
        self._hover = None

    def set_duration(self, ms):
        self._duration = max(0, int(ms))
        self.update()

    def set_position(self, ms):
        if not self._dragging:
            self._position = max(0, int(ms))
            self.update()

    def set_marks(self, marks):
        self._marks = sorted((float(start), str(title)) for start, title in marks)
        self.update()

    def chapter_at(self, seconds):
        title = ''
        for start, name in self._marks:
            if start <= seconds + 0.25:
                title = name
        return title

    def _track(self):
        return QRectF(self.MARGIN, self.height() / 2 - 2, max(1, self.width() - 2 * self.MARGIN), 4)

    def _x_to_ms(self, x):
        track = self._track()
        ratio = min(1.0, max(0.0, (x - track.left()) / track.width()))
        return int(ratio * self._duration)

    def _ms_to_x(self, ms):
        track = self._track()
        return track.left() + (ms / self._duration * track.width() if self._duration else 0)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        track = self._track()
        if self._hover is not None or self._dragging:
            track.adjust(0, -1, 0, 1)
        cuts = [self._ms_to_x(start * 1000) for start, _title in self._marks
                if 0 < start * 1000 < self._duration]
        edges = [track.left()] + cuts + [track.right()]
        played = self._ms_to_x(self._position)
        hover = self._hover
        for left, right in zip(edges, edges[1:]):
            segment = QRectF(left + (1.5 if left > track.left() else 0), track.top(),
                             max(0.0, right - left - (1.5 if left > track.left() else 0)
                                 - (1.5 if right < track.right() else 0)), track.height())
            painter.fillRect(segment, QColor(THEME['drop_border']))
            if hover is not None and hover > segment.left():
                painter.fillRect(QRectF(segment.left(), segment.top(),
                                        min(segment.width(), hover - segment.left()),
                                        segment.height()), QColor(THEME['muted']))
            if played > segment.left():
                painter.fillRect(QRectF(segment.left(), segment.top(),
                                        min(segment.width(), played - segment.left()),
                                        segment.height()), QColor(THEME['accent']))
        radius = 6.5 if (self._hover is not None or self._dragging) else 5.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(THEME['accent']))
        painter.drawEllipse(QPointF(played, track.center().y()), radius, radius)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._duration:
            self._dragging = True
            self._position = self._x_to_ms(event.position().x())
            self.seek_requested.emit(self._position)
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        x = event.position().x()
        self._hover = x
        if self._dragging:
            self._position = self._x_to_ms(x)
            self.seek_requested.emit(self._position)
        if self._duration:
            seconds = self._x_to_ms(x) / 1000
            title = self.chapter_at(seconds)
            QToolTip.showText(event.globalPosition().toPoint(),
                              qa.format_time(seconds) + (' · ' + title if title else ''), self)
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.update()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        super().leaveEvent(event)


# --- panel ------------------------------------------------------------------
class VideoQAPanel(QWidget):
    """Tek video icin oynatici + atifli sohbet (Soru Sor sekmesi icerigi)."""

    def __init__(self, video, stream=None, streams=None, log=None, parent=None):
        super().__init__(parent)
        self.video = Path(video)
        self._initial_stream = stream
        self._streams = list(streams) if streams else None
        self._external_log = log or (lambda _message: None)
        self.session = None
        self._entries = [('note', GREETING)]
        self._jobs = []  # [(thread, worker)] calisan isler
        self._prepare_worker = None
        self._asking = False
        self._ready = False
        self._muted_volume = None
        self._retired = False
        self._subtitle_key = None   # None: altyazi kapali
        self._timelines = {}        # kaynak anahtari -> qa.SubtitleTimeline
        self._subtitle_text = ''
        self._transcribe_worker = None
        self._audio = None          # media.audio_streams (hazirlikta okunur)
        try:
            cfg = load_config()
            self._whisper = speech.load_cached(self.video, cfg['whisper_model'],
                                               cfg['whisper_language'])
        except (OSError, ValueError):
            self._whisper = None
        theme = dict(THEME)
        try:
            from gui import _MONO_FAMILY
            theme['mono_font'] = _MONO_FAMILY
        except ImportError:
            pass
        self.setStyleSheet(QA_STYLE.format(**theme))
        self._build()
        self._setup_player()
        self._render_chat()
        self.start_prepare()

    # --- kurulum -----------------------------------------------------------
    def _build(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        body_layout = QHBoxLayout(self)
        body_layout.setContentsMargins(16, 16, 16, 16)
        body_layout.addWidget(splitter)

        splitter.addWidget(self._build_player())
        splitter.addWidget(self._build_chat())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([860, 460])

    def _build_player(self):
        frame, column = card(spacing=0, margins=(0, 0, 0, 0))
        self.player_panel = frame
        surface = QFrame()
        surface.setObjectName('videoSurface')
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(480, 270)
        self.video_widget.installEventFilter(self)
        surface_layout.addWidget(self.video_widget)
        column.addWidget(surface, 1)

        controls = QVBoxLayout()
        controls.setContentsMargins(12, 6, 12, 10)
        controls.setSpacing(4)
        self.seek_bar = SeekBar()
        controls.addWidget(self.seek_bar)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.play_button = HoverIconButton('')
        self.play_button.setObjectName('iconFlat')
        self.play_button.setTintedIcon('play', THEME['text'], 18)
        self.play_button.setToolTip('Oynat (Boşluk)')
        self.play_button.clicked.connect(self.toggle_play)
        row.addWidget(self.play_button)
        self.mute_button = HoverIconButton('')
        self.mute_button.setObjectName('iconFlat')
        self.mute_button.setTintedIcon('volume', THEME['text'], 18)
        self.mute_button.setToolTip('Sesi kapat')
        self.mute_button.clicked.connect(self.toggle_mute)
        row.addWidget(self.mute_button)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(90)
        self.volume.setToolTip('Ses düzeyi')
        row.addWidget(self.volume)
        self.time_label = QLabel('0:00 / 0:00')
        self.time_label.setObjectName('timeLabel')
        row.addWidget(self.time_label)
        self.chapter_label = QLabel('')
        self.chapter_label.setObjectName('chapterLabel')
        self.chapter_label.hide()
        row.addWidget(self.chapter_label)
        row.addStretch(1)
        self.audio_button = HoverIconButton('')
        self.audio_button.setObjectName('iconFlat')
        self.audio_button.setTintedIcon('audio', THEME['text'], 18)
        self.audio_button.setToolTip('Ses parçası')
        self.audio_button.clicked.connect(self.show_audio_menu)
        self.audio_button.hide()  # birden fazla ses parcasi varsa gorunur
        row.addWidget(self.audio_button)
        self.cc_button = HoverIconButton('')
        self.cc_button.setObjectName('iconFlat')
        self.cc_button.setTintedIcon('subtitles', THEME['text'], 18)
        self.cc_button.setToolTip('Altyazılar')
        self.cc_button.clicked.connect(self.show_subtitle_menu)
        row.addWidget(self.cc_button)
        controls.addLayout(row)
        column.addLayout(controls)

        for key, slot in ((Qt.Key_Space, self.toggle_play),
                          (Qt.Key_Left, lambda: self.seek_relative(-SEEK_STEP_MS)),
                          (Qt.Key_Right, lambda: self.seek_relative(SEEK_STEP_MS))):
            shortcut = QShortcut(QKeySequence(key), frame)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        frame.setFocusPolicy(Qt.ClickFocus)
        return frame

    def _build_chat(self):
        frame, column = card(spacing=8, margins=(14, 14, 14, 12))
        frame.setMinimumWidth(360)
        head = QHBoxLayout()
        head.addWidget(section_label('Bu video hakkında soru sorun'))
        head.addStretch(1)
        column.addLayout(head)

        source = QHBoxLayout()
        source.setSpacing(8)
        self.source_label = QLabel('Transkript')
        self.source_label.setObjectName('hint')
        source.addWidget(self.source_label)
        self.source_combo = DropdownCombo()
        self.source_combo.setToolTip('Soru-cevapta kullanılacak altyazı akışı')
        self.source_combo.currentIndexChanged.connect(self.on_source_changed)
        source.addWidget(self.source_combo, 1)
        self.source_row = QWidget()
        self.source_row.setObjectName('qaSource')
        self.source_row.setLayout(source)
        self.source_row.hide()
        column.addWidget(self.source_row)

        status = QHBoxLayout()
        status.setSpacing(10)
        self.status_label = QLabel('Hazırlanıyor...')
        self.status_label.setObjectName('hint')
        self.status_label.setWordWrap(True)
        status.addWidget(self.status_label, 1)
        self.prepare_progress = QProgressBar()
        self.prepare_progress.setTextVisible(False)
        self.prepare_progress.setMaximumWidth(140)
        self.prepare_progress.setRange(0, 0)
        status.addWidget(self.prepare_progress)
        column.addLayout(status)

        self.chat = QTextBrowser()
        self.chat.setObjectName('qaChat')
        self.chat.setOpenLinks(False)
        self.chat.setOpenExternalLinks(False)
        self.chat.anchorClicked.connect(self.on_anchor)
        column.addWidget(self.chat, 1)

        self.chips = QWidget()
        self.chips.setObjectName('qaChips')
        chips_layout = QVBoxLayout(self.chips)
        chips_layout.setContentsMargins(0, 0, 0, 4)
        chips_layout.setSpacing(6)
        self.chips_title = QLabel('Ne soracağınızı bilmiyor musunuz? Birini seçin:')
        self.chips_title.setObjectName('hint')
        chips_layout.addWidget(self.chips_title)
        self.chips_box = QVBoxLayout()
        self.chips_box.setSpacing(6)
        chips_layout.addLayout(self.chips_box)
        self.chips.hide()
        column.addWidget(self.chips)

        ask_row = QHBoxLayout()
        ask_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText('Video hazırlanıyor...')
        self.input.returnPressed.connect(self.ask)
        ask_row.addWidget(self.input, 1)
        self.send_button = HoverIconButton('')
        self.send_button.setObjectName('iconOnly')
        self.send_button.setTintedIcon('send', THEME['text'], 16)
        self.send_button.setToolTip('Sor')
        self.send_button.clicked.connect(self.ask)
        ask_row.addWidget(self.send_button)
        column.addLayout(ask_row)

        foot = QLabel('Yapay zekâ yanlış bilgi verebilir; zaman atıflarına tıklayıp videoda doğrulayın.')
        foot.setObjectName('qaFoot')
        foot.setWordWrap(True)
        column.addWidget(foot)
        self._set_input_enabled(False)
        return frame

    def _setup_player(self):
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(self.volume.value() / 100)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)
        self.player.durationChanged.connect(self.on_duration)
        self.player.positionChanged.connect(self.on_position)
        self.player.playbackStateChanged.connect(self.on_playback_state)
        self.player.errorOccurred.connect(self.on_player_error)
        # Altyazi metnini Aktar cizer (tum kaynaklar ayni yoldan); Qt'nin kendi
        # gomulu altyazi secimi kapali tutulur.
        self.player.tracksChanged.connect(lambda: self.player.setActiveSubtitleTrack(-1))
        self.player.tracksChanged.connect(self._update_audio_button)
        self._subtitle_timer = QTimer(self)
        self._subtitle_timer.setInterval(SUBTITLE_TICK_MS)
        self._subtitle_timer.timeout.connect(self._refresh_subtitle)
        self.seek_bar.seek_requested.connect(self.player.setPosition)
        self.volume.valueChanged.connect(self.on_volume)
        self.player.setSource(QUrl.fromLocalFile(str(self.video)))

    def eventFilter(self, obj, event):
        if obj is self.video_widget and event.type() == QEvent.MouseButtonPress \
                and event.button() == Qt.LeftButton:
            self.toggle_play()
            return True
        return super().eventFilter(obj, event)

    def busy(self):
        return bool(self._jobs)

    def _cancel_jobs(self):
        for worker in (self._prepare_worker, self._transcribe_worker):
            if worker is not None:
                worker.cancel_event.set()

    def hideEvent(self, event):
        """Ceviri sekmesine gecilince video duraklar."""
        self.player.pause()
        super().hideEvent(event)

    def retire(self):
        """Video degisince: oynatici durur, hazirlik bir sonraki adimda durur; is
        bitince panel kendini siler (calisan thread'in alicisi silinmesin diye)."""
        self._retired = True
        self.player.stop()
        self._cancel_jobs()
        self.hide()
        if not self._jobs:
            self.deleteLater()

    def shutdown(self, wait_ms=3000):
        """Uygulama kapanirken: isleri durdur ve thread'leri kisa sure bekle."""
        self.player.stop()
        self._cancel_jobs()
        for thread, _worker in list(self._jobs):
            thread.quit()
            thread.wait(wait_ms)

    # --- oynatici ----------------------------------------------------------
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek_relative(self, delta_ms):
        self.seek_to(self.player.position() + delta_ms)

    def seek_to(self, ms, play=False):
        duration = self.player.duration()
        ms = max(0, int(ms))
        if duration > 0:
            ms = min(ms, duration)
        self.player.setPosition(ms)
        self.seek_bar.set_position(ms)
        if play:
            self.player.play()

    def toggle_mute(self):
        if self._muted_volume is None:
            self._muted_volume = self.volume.value() or 80
            self.volume.setValue(0)
        else:
            self.volume.setValue(self._muted_volume)
            self._muted_volume = None

    @Slot(int)
    def on_volume(self, value):
        self.audio.setVolume(value / 100)
        if value and self._muted_volume is not None:
            self._muted_volume = None
        name = 'mute' if value == 0 else 'volume'
        self.mute_button.setIcon(tinted_icon(name, THEME['text'], 18))
        self.mute_button.setHoverIcon(tinted_icon(name, THEME['accent'], 18))
        self.mute_button.setToolTip('Sesi aç' if value == 0 else 'Sesi kapat')

    @Slot(int)
    def on_duration(self, ms):
        self.seek_bar.set_duration(ms)
        self._update_time(self.player.position())

    @Slot(int)
    def on_position(self, ms):
        self.seek_bar.set_position(ms)
        self._update_time(ms)
        self._refresh_subtitle()

    def _update_time(self, ms):
        self.time_label.setText(qa.format_time(ms / 1000) + ' / '
                                + qa.format_time(max(0, self.player.duration()) / 1000))
        title = self.seek_bar.chapter_at(ms / 1000)
        self.chapter_label.setText(title + '  ›' if title else '')
        self.chapter_label.setVisible(bool(title))

    @Slot(object)
    def on_playback_state(self, state):
        playing = state == QMediaPlayer.PlayingState
        name = 'pause' if playing else 'play'
        self.play_button.setIcon(tinted_icon(name, THEME['text'], 18))
        self.play_button.setHoverIcon(tinted_icon(name, THEME['accent'], 18))
        self.play_button.setToolTip(('Duraklat' if playing else 'Oynat') + ' (Boşluk)')
        if playing and self._subtitle_key is not None:
            self._subtitle_timer.start()
        else:
            self._subtitle_timer.stop()

    # --- altyazi (CC) ---------------------------------------------------------
    def show_subtitle_menu(self):
        """Altyazi menusu: Kapali / videodaki akislar / yan dosyalar."""
        menu = QMenu(self)
        group = QActionGroup(menu)
        group.setExclusive(True)

        def add(label, source, checked):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(checked)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, value=source: self.select_subtitle(value))

        add('Kapalı', None, self._subtitle_key is None)
        sources = subtitle_sources(self.video, self._streams)
        streams = [item for item in sources if item['kind'] == 'stream']
        files = [item for item in sources if item['kind'] == 'file']
        for title, items in (('Videodaki altyazılar', streams), ('Video klasöründeki dosyalar', files)):
            if not items:
                continue
            menu.addSeparator()
            menu.addAction(title).setEnabled(False)
            for item in items:
                add(item['label'], item, item['key'] == self._subtitle_key)
        menu.addSeparator()
        menu.addAction('Sesten (Whisper)').setEnabled(False)
        tracks = self._audio or []
        if self._whisper:
            label = self._whisper_label(self._whisper)
            add(label, {'key': WHISPER_KEY, 'kind': WHISPER_KEY, 'label': label},
                self._subtitle_key == WHISPER_KEY)
        if self._transcribe_worker is not None:
            menu.addAction('Konuşmadan metin çıkarılıyor...').setEnabled(False)
        elif len(tracks) > 1:
            # Birden fazla ses parcasi: Whisper'a gidecek parca secilir.
            submenu = menu.addMenu('Sesten oluştur')
            for item in tracks:
                submenu.addAction(audio_label(item)).triggered.connect(
                    lambda _checked=False, value=item: self.generate_whisper(value))
        elif not self._whisper:
            menu.addAction('Sesten oluştur...').triggered.connect(
                lambda _checked=False: self.generate_whisper())
        if self._streams is None:
            menu.addSeparator()
            menu.addAction('Altyazı akışları okunuyor...').setEnabled(False)
        point = self.cc_button.mapToGlobal(QPoint(0, 0))
        menu.exec(QPoint(point.x() + self.cc_button.width() - menu.sizeHint().width(),
                         point.y() - menu.sizeHint().height() - 4))

    def select_subtitle(self, source):
        """Gosterilecek altyaziyi secer; ilk secimde arka planda yuklenir."""
        self._subtitle_key = None if source is None else source['key']
        self.cc_button.setTintedIcon('subtitles', THEME['text'] if source is None
                                     else THEME['accent'], 18)
        if source is not None and source['key'] == WHISPER_KEY and self._whisper:
            self._timelines.setdefault(WHISPER_KEY, qa.SubtitleTimeline(
                speech.display_segments(self._whisper['segments'])))
        if source is not None and source['key'] not in self._timelines:
            self._log('Altyazı yükleniyor: ' + source['label'])
            self._start_job(SubtitleLoadWorker(self.video, source), self.subtitle_loaded)
        if self._subtitle_key is not None and \
                self.player.playbackState() == QMediaPlayer.PlayingState:
            self._subtitle_timer.start()
        else:
            self._subtitle_timer.stop()
        self._refresh_subtitle()

    # --- ses parcasi ----------------------------------------------------------
    def _audio_track_arg(self, stream):
        """Whisper icin ses akisi: ilk akis None (eski onbellekler gecerli kalsin)."""
        if stream is None or not self._audio or stream['index'] == self._audio[0]['index']:
            return None
        return stream['index']

    def _whisper_label(self, result):
        label = 'Whisper · ' + speech.language_label(result.get('language'))
        if self._audio and len(self._audio) > 1:
            track = result.get('audio_track')
            stream = next((item for item in self._audio if item['index'] == track),
                          self._audio[0] if track is None else None)
            if stream is not None:
                label += ' (' + audio_label(stream) + ')'
        return label

    def _audio_track_labels(self):
        """Oynaticinin ses parcalari icin etiketler (ffprobe bilgisi varsa ondan)."""
        labels = []
        for order, meta in enumerate(self.player.audioTracks()):
            if self._audio and order < len(self._audio):
                labels.append(audio_label(self._audio[order]))
                continue
            language = meta.stringValue(QMediaMetaData.Language)
            title = meta.stringValue(QMediaMetaData.Title)
            labels.append(' · '.join(part for part in (language, title) if part)
                          or f'Ses {order + 1}')
        return labels

    def _update_audio_button(self):
        self.audio_button.setVisible(len(self.player.audioTracks()) > 1)

    def show_audio_menu(self):
        """Oynatilan ses parcasini secer (altyazi menusu gibi)."""
        menu = QMenu(self)
        group = QActionGroup(menu)
        group.setExclusive(True)
        menu.addAction('Ses parçası').setEnabled(False)
        active = self.player.activeAudioTrack()
        for order, label in enumerate(self._audio_track_labels()):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(order == active)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, value=order: self.select_audio(value))
        point = self.audio_button.mapToGlobal(QPoint(0, 0))
        menu.exec(QPoint(point.x() + self.audio_button.width() - menu.sizeHint().width(),
                         point.y() - menu.sizeHint().height() - 4))

    def select_audio(self, order):
        position = self.player.position()
        self.player.setActiveAudioTrack(order)
        # Bazi arka uclar parca degisince basa sarar; konum korunur.
        if abs(self.player.position() - position) > 1000:
            self.player.setPosition(position)

    @Slot(object)
    def on_audio(self, streams):
        self._audio = list(streams or [])

    def generate_whisper(self, stream=None):
        """CC menusunden: konusmadan metin cikar, bitince altyazi olarak goster.

        `stream`: Whisper'a gidecek ses akisi (media.audio_streams kaydi; None: ilk akis)."""
        ok, message = speech.available()
        if not ok:
            self._note('error', message)
            return
        if self._transcribe_worker is not None or self._prepare_worker is not None:
            self._note('note', 'Önceki iş bitince tekrar deneyin.')
            return
        worker = TranscribeWorker(self.video, self._audio_track_arg(stream))
        worker.progress.connect(self.on_whisper_progress)
        worker.log.connect(self._log)
        self._transcribe_worker = worker
        self.prepare_progress.setRange(0, 0)
        self.prepare_progress.show()
        self.status_label.setText('Konuşmadan metin çıkarılıyor...')
        self._start_job(worker, self.transcribe_finished)

    @Slot(object, str)
    def transcribe_finished(self, result, error):
        self._transcribe_worker = None
        self.prepare_progress.hide()
        self.status_label.setText('Hazır' if self._ready else self.status_label.text())
        if error:
            self._note('error', 'Konuşmadan metin çıkarılamadı: ' + error)
            return
        self.on_whisper_ready(result)
        label = self._whisper_label(result)
        self.select_subtitle({'key': WHISPER_KEY, 'kind': WHISPER_KEY, 'label': label})

    @Slot(str, object, str)
    def subtitle_loaded(self, key, timeline, error):
        if error:
            self._note('error', 'Altyazı yüklenemedi: ' + error)
            if key == self._subtitle_key:
                self.select_subtitle(None)
            return
        self._timelines[key] = timeline
        self._refresh_subtitle()

    def _refresh_subtitle(self):
        timeline = self._timelines.get(self._subtitle_key)
        text = timeline.text_at(self.player.position() / 1000) if timeline is not None else ''
        if text != self._subtitle_text:
            self._subtitle_text = text
            self.video_widget.videoSink().setSubtitleText(text)

    @Slot(object, str)
    def on_player_error(self, _error, message):
        if message:
            self._note('error', 'Video oynatılamadı: ' + message)

    @Slot(QUrl)
    def on_anchor(self, url):
        ms = parse_seek_link(url)
        if ms is not None:
            self.seek_to(ms, play=True)

    def _update_marks(self):
        if self.session is None:
            return
        data = self.session.data
        marks = [(item['start'], item.get('title', '')) for item in data.get('chapters') or []]
        if len(marks) < 2:
            marks = [(item['start'], qa.section_label(item)) for item in data.get('sections') or []
                     if qa.section_label(item)]
        self.seek_bar.set_marks(marks)
        self._update_time(self.player.position())

    # --- is altyapisi -------------------------------------------------------
    def _start_job(self, worker, finished_slot):
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(finished_slot)
        worker.finished.connect(thread.quit)
        entry = (thread, worker)
        self._jobs.append(entry)
        self.source_combo.setEnabled(False)
        thread.finished.connect(lambda: self._job_done(entry))
        thread.start()

    def _job_done(self, entry):
        if entry in self._jobs:
            self._jobs.remove(entry)
        entry[0].deleteLater()
        self.source_combo.setEnabled(not self._jobs)
        if self._retired and not self._jobs:
            self.deleteLater()

    def _log(self, message):
        self._external_log('[Soru] ' + str(message))

    # --- hazirlik -----------------------------------------------------------
    def start_prepare(self, stream=None, whisper=False, audio_track=None):
        if self.busy():
            return
        if whisper:
            ok, message = speech.available()
            if not ok:
                self._note('error', message)
                return
        self._ready = False
        self._set_input_enabled(False)
        self.chips.hide()
        self.prepare_progress.setRange(0, 0)
        self.prepare_progress.show()
        self.status_label.setText(('Konuşmadan metin çıkarılıyor...' if whisper
                                   else 'Transkript hazırlanıyor...') if self.session is None
                                  else 'Video hazırlanıyor...')
        worker = PrepareWorker(self.video, stream=stream or self._initial_stream,
                               streams=self._streams, session=self.session, whisper=whisper,
                               audio_track=audio_track, audio=self._audio)
        worker.audio_ready.connect(self.on_audio)
        worker.streams_ready.connect(self.on_streams)
        worker.whisper_progress.connect(self.on_whisper_progress)
        worker.whisper_ready.connect(self.on_whisper_ready)
        worker.loaded.connect(self.on_loaded)
        worker.progress.connect(self.on_prepare_progress)
        worker.log.connect(self._log)
        self._prepare_worker = worker
        self._start_job(worker, self.prepare_finished)

    @Slot(object, object)
    def on_streams(self, streams, chosen):
        self._streams = list(streams or [])
        usable = [item for item in self._streams if item.get('supported')]
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        for item in usable:
            label = ' · '.join(part for part in (item.get('language') or '', item.get('title') or '',
                                                 item.get('codec', '')) if part)
            self.source_combo.addItem(label or ('Akış ' + str(item['index'])), item['index'])
        tracks = self._audio or []
        if len(tracks) > 1:
            # Her ses parcasi ayri secenek: 'whisper:<global index>'.
            for item in tracks:
                self.source_combo.addItem('Sesten (Whisper) · ' + audio_label(item),
                                          f'{WHISPER_KEY}:{item["index"]}')
        else:
            self.source_combo.addItem('Sesten (Whisper)', WHISPER_KEY)
        if chosen is not None:
            index = self.source_combo.findData(chosen['index'])
        elif len(tracks) > 1:
            index = self.source_combo.findData(f'{WHISPER_KEY}:{self._whisper_stream_index()}')
        else:
            index = self.source_combo.findData(WHISPER_KEY)
        self.source_combo.setCurrentIndex(max(0, index))
        self.source_combo.blockSignals(False)
        self.source_row.show()

    @Slot(int, int)
    def on_whisper_progress(self, done, total):
        self.prepare_progress.setRange(0, max(1, total))
        self.prepare_progress.setValue(done)
        self.status_label.setText(f'Konuşmadan metin: {qa.format_time(done)} / '
                                  f'{qa.format_time(total)}')

    @Slot(object)
    def on_whisper_ready(self, result):
        self._whisper = result
        self._timelines.pop(WHISPER_KEY, None)

    @Slot(object)
    def on_loaded(self, session):
        self.session = session
        self._update_marks()
        data = session.data
        self.status_label.setText(f'Transkript hazır ({len(data["segments"])} satır). '
                                  'Video özetleniyor...')

    @Slot(int, int)
    def on_prepare_progress(self, done, total):
        self.prepare_progress.setRange(0, max(1, total))
        self.prepare_progress.setValue(done)
        if total > 1:
            self.status_label.setText(f'Video haritası çıkarılıyor: {done} / {total}')

    @Slot(object, str)
    def prepare_finished(self, overview, error):
        self._prepare_worker = None
        self.prepare_progress.hide()
        if self.session is not None:
            self._update_marks()
        if error:
            self._log(error)
            self.status_label.setText('Altyazı yok · video oynatılabilir' if error == NO_SUBTITLE
                                      else 'Hazırlık tamamlanamadı.')
            self._note('error', error)
            if error == NO_SUBTITLE:
                self._show_chips([], whisper=True)
            elif self.session is not None:
                self._show_chips([], retry=True)
            return
        data = self.session.data
        mode = 'tüm transkript' if data.get('mode') == 'full' else f'{len(data["sections"])} bölüm'
        self.status_label.setText(f'Hazır · {qa.format_time(data.get("duration", 0))} · {mode}')
        self._ready = True
        self._set_input_enabled(True)
        if not self.session.history:
            self._show_chips(self.session.questions())

    def _whisper_stream_index(self):
        """Hazirlanan Whisper oturumunun ses akisi (GLOBAL index); ilk akis varsayilan."""
        worker = self._prepare_worker
        track = worker.audio_track if worker is not None else None
        if track is None and self.session is not None:
            track = self.session.data['source'].get('audio_track')
        if track is None and self._audio:
            track = self._audio[0]['index']
        return track

    def on_source_changed(self, _index):
        index = self.source_combo.currentData()
        if index is None or self.busy():
            return
        source = self.session.data['source'] if self.session is not None else {}
        stream, track = None, None
        if isinstance(index, str) and index.startswith(WHISPER_KEY):
            if index != WHISPER_KEY:  # 'whisper:<global index>': birden fazla ses parcasi
                wanted = int(index.split(':', 1)[1])
                track = self._audio_track_arg(next(
                    (item for item in self._audio or [] if item['index'] == wanted), None))
            if source.get('kind') == 'whisper' and source.get('audio_track') == track:
                return
        else:
            if source.get('stream') == index:
                return
            stream = next((item for item in self._streams or [] if item['index'] == index), None)
            if stream is None:
                return
        self.session = None
        self._entries = [('note', GREETING)]
        self._render_chat()
        self.start_prepare(stream, whisper=stream is None, audio_track=track)

    # --- sohbet -------------------------------------------------------------
    def _set_input_enabled(self, enabled):
        self.input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        self.input.setPlaceholderText('Soru sorun...' if enabled else
                                      ('Yanıt hazırlanıyor...' if self._asking
                                       else 'Video hazırlanıyor...'))
        if enabled:
            self.input.setFocus()

    def _show_chips(self, questions, retry=False, whisper=False):
        # Her oneri bir satir layout'u icinde; layout kaldirilinca icindeki etiket
        # silinmez ve eski oneri yenilerin ustunde kaliyordu.
        while self.chips_box.count():
            line = self.chips_box.takeAt(0).layout()
            while line is not None and line.count():
                widget = line.takeAt(0).widget()
                if widget is not None:
                    widget.deleteLater()
        if whisper:
            self.chips_title.setText('Altyazı olmadan da soru sorabilirsiniz:')
            labels = [('Sesten transkript çıkar (Whisper)',
                       lambda _checked=False: self.start_prepare(whisper=True))]
        elif retry:
            self.chips_title.setText('LM Studio açık ve model yüklü olduğunda tekrar deneyin:')
            labels = [('Tekrar dene', lambda _checked=False: self.start_prepare())]
        else:
            self.chips_title.setText('Ne soracağınızı bilmiyor musunuz? Birini seçin:')
            labels = [(text, (lambda _checked=False, value=text: self.ask(value)))
                      for text in questions]
        for text, slot in labels:
            # QPushButton metni kaydirmaz; uzun sorular iki yandan kesiliyordu.
            button = ClickableLabel(text)
            button.setObjectName('qaChip')
            # Kisa sorular tek satirda kalsin; yalnizca sigmayacak kadar uzunlar kaydirilir.
            button.setWordWrap(button.fontMetrics().horizontalAdvance(text) > 380)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            line = QHBoxLayout()
            line.addStretch(1)
            line.addWidget(button)
            self.chips_box.addLayout(line)
        self.chips.setVisible(bool(labels))

    def ask(self, question=None):
        text = question if isinstance(question, str) else self.input.text()
        text = ' '.join(text.split())
        if not text or self.session is None or not self._ready or self._asking:
            return
        self.input.clear()
        self.chips.hide()
        self._asking = True
        self._set_input_enabled(False)
        self._entries.append(('user', text))
        self._entries.append(('pending', 'Yanıt hazırlanıyor...'))
        self._render_chat()
        self._start_job(AskWorker(self.session, text), self.ask_finished)

    @Slot(object, str)
    def ask_finished(self, turn, error):
        self._asking = False
        self._entries = [entry for entry in self._entries if entry[0] != 'pending']
        if error:
            self._log(error)
            self._entries.append(('error', 'Yanıt alınamadı: ' + error))
        else:
            self._entries.append(('assistant', turn['parts']))
        self._render_chat()
        self._set_input_enabled(True)

    def _note(self, kind, text):
        self._entries.append((kind, text))
        self._render_chat()

    def _render_chat(self):
        self.chat.setHtml(chat_html(self._entries))
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())
