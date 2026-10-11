"""Soru Sor sekmesi paneli (F45/F46): solda oynatici, sagda atifli sohbet.

Ana penceredeki "Soru Sor" sekmesinin icerigidir (F46'dan once ayri pencereydi).
Duzen (YouTube "Bu video hakkinda soru sorun" paneli):
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

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QSlider, QSplitter,
                               QTextBrowser, QToolTip, QVBoxLayout, QWidget)

import qa
from app_core import GracefulStop, load_config, save_json
from gui import (THEME, ClickableLabel, DropdownCombo, HoverIconButton, card, section_label,
                 tinted_icon)
from media import subtitle_streams

GREETING = ('Merhaba! İzlediğiniz videoyla ilgili sorularınız mı var? '
            'Size yardımcı olmaktan memnuniyet duyarım.')
NO_SUBTITLE = ('Bu videoda metin tabanlı altyazı yok; soru-cevap için transkript '
               'çıkarılamadı. Video yine de oynatılabilir.')
SEEK_STEP_MS = 5000

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
QWidget#qaChips {{ background:transparent; }}
QLabel#qaFoot {{ color:{muted}; font-size:11px; }}
QSlider::groove:horizontal {{ height:4px; background:{drop_border}; border-radius:2px; }}
QSlider::sub-page:horizontal {{ height:4px; background:{secondary}; border-radius:2px; }}
QSlider::handle:horizontal {{ width:12px; margin:-4px 0; background:{text}; border-radius:6px; }}
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
    """Akis tespiti -> transkript (onbellekli) -> video haritasi/ozet."""

    streams_ready = Signal(object, object)  # (akislar, secilen akis)
    loaded = Signal(object)                 # qa.VideoQA
    progress = Signal(int, int)
    log = Signal(str)
    finished = Signal(object, str)          # (genel ozet, hata)

    def __init__(self, video, stream=None, streams=None, session=None):
        super().__init__()
        self.video = video
        self.stream = stream
        self.streams = streams
        self.session = session
        self.cancel_event = threading.Event()

    @Slot()
    def run(self):
        try:
            if self.session is None:
                streams = self.streams if self.streams is not None else subtitle_streams(self.video)
                stream = self.stream or qa.pick_subtitle_stream(streams)
                self.streams_ready.emit(streams, stream)
                if stream is None:
                    self.finished.emit(None, NO_SUBTITLE)
                    return
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

    def hideEvent(self, event):
        """Ceviri sekmesine gecilince video duraklar (YouTube'da sekme degisimi gibi)."""
        self.player.pause()
        super().hideEvent(event)

    def retire(self):
        """Video degisince: oynatici durur, hazirlik bir sonraki adimda durur; is
        bitince panel kendini siler (calisan thread'in alicisi silinmesin diye)."""
        self._retired = True
        self.player.stop()
        if self._prepare_worker is not None:
            self._prepare_worker.cancel_event.set()
        self.hide()
        if not self._jobs:
            self.deleteLater()

    def shutdown(self, wait_ms=3000):
        """Uygulama kapanirken: isleri durdur ve thread'leri kisa sure bekle."""
        self.player.stop()
        if self._prepare_worker is not None:
            self._prepare_worker.cancel_event.set()
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
    def start_prepare(self, stream=None):
        if self.busy():
            return
        self._ready = False
        self._set_input_enabled(False)
        self.chips.hide()
        self.prepare_progress.setRange(0, 0)
        self.prepare_progress.show()
        self.status_label.setText('Transkript hazırlanıyor...' if self.session is None
                                  else 'Video hazırlanıyor...')
        worker = PrepareWorker(self.video, stream=stream or self._initial_stream,
                               streams=self._streams, session=self.session)
        worker.streams_ready.connect(self.on_streams)
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
        if chosen is not None:
            index = self.source_combo.findData(chosen['index'])
            self.source_combo.setCurrentIndex(max(0, index))
        self.source_combo.blockSignals(False)
        self.source_row.setVisible(len(usable) > 1)

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
            self.status_label.setText('Hazırlık tamamlanamadı.')
            self._note('error', error)
            if self.session is not None:
                self._show_chips([], retry=True)
            return
        data = self.session.data
        mode = 'tüm transkript' if data.get('mode') == 'full' else f'{len(data["sections"])} bölüm'
        self.status_label.setText(f'Hazır · {qa.format_time(data.get("duration", 0))} · {mode}')
        self._ready = True
        self._set_input_enabled(True)
        if not self.session.history:
            self._show_chips(self.session.questions())

    def on_source_changed(self, _index):
        index = self.source_combo.currentData()
        if index is None or self.busy():
            return
        if self.session is not None and self.session.data['source'].get('stream') == index:
            return
        stream = next((item for item in self._streams or [] if item['index'] == index), None)
        if stream is None:
            return
        self.session = None
        self._entries = [('note', GREETING)]
        self._render_chat()
        self.start_prepare(stream)

    # --- sohbet -------------------------------------------------------------
    def _set_input_enabled(self, enabled):
        self.input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        self.input.setPlaceholderText('Soru sorun...' if enabled else
                                      ('Yanıt hazırlanıyor...' if self._asking
                                       else 'Video hazırlanıyor...'))
        if enabled:
            self.input.setFocus()

    def _show_chips(self, questions, retry=False):
        while self.chips_box.count():
            item = self.chips_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if retry:
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
