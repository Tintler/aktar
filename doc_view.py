"""Belge goruntuleyici (F64) + tek belgeye soru sor (F66).

Solda belge: PDF'ler QtPdf/QtPdfWidgets ile (PySide6 ile gelir) uygulama icinde
gosterilir; .txt/.md dosyalari duz metin olarak, documents.TEXT_PAGE_LINES
satirlik "sayfalarla" ayni numaralandirmada acilir. Sagda sohbet: belge
acilinca metni cikarilir (embedding modeli seciliyse indekslenir); kisa belgede
metnin tamami, uzun belgede ilgili parcalar modele gider. Cevaptaki s.N atiflari
tiklaninca belge o sayfaya gider. Kaynak dosya SALT-OKUNUR.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter,
                               QTextBrowser, QVBoxLayout, QWidget)

import collection_qa
import documents
import library
from app_core import load_config
from chat_render import AskWorker, chat_html
from gui import THEME, HoverIconButton, card, section_label

GREETING = ('Bu belge hakkında soru sorun; cevaplar hangi sayfada geçtiğini gösterir. '
            'Sayfa atfına tıklayınca belge o sayfaya gider.')


class DocumentView(QWidget):
    """Tek belge: solda goruntuleyici (sayfa gezinme), sagda belgeye soru sor."""

    prepared = Signal(str)  # hazirlik bitti: hata metni ('' = basarili)

    def __init__(self, path, parent=None, log=None):
        super().__init__(parent)
        self.path = Path(path)
        self.kind = documents.kind_of(self.path)
        self._log = log or (lambda _message: None)
        self._pages = 1
        self._entries = [('note', GREETING)]
        self._targets = []
        self._session = None
        self._ask_job = None
        self._ready = False
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 16)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        outer.addWidget(splitter)
        splitter.addWidget(self._build_viewer())
        splitter.addWidget(self._build_chat())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([860, 460])
        self.prepared.connect(self._on_prepared)
        self._render_chat()
        self._set_chat_enabled(False, 'Belge hazırlanıyor…')
        threading.Thread(target=self._prepare, name='aktar-doc-prepare', daemon=True).start()
        self._update()

    # --- kurulum -------------------------------------------------------------
    def _build_viewer(self):
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.page_label = QLabel('')
        self.page_label.setObjectName('progressValue')
        bar.addStretch(1)
        self.prev_button = HoverIconButton('')
        self.prev_button.setObjectName('iconOnly')
        self.prev_button.setTintedIcon('back', THEME['text'])
        self.prev_button.setToolTip('Önceki sayfa')
        self.prev_button.clicked.connect(lambda: self.go_to_page(self.current_page() - 1))
        bar.addWidget(self.prev_button)
        bar.addWidget(self.page_label)
        self.next_button = HoverIconButton('')
        self.next_button.setObjectName('iconOnly')
        self.next_button.setTintedIcon('forward', THEME['text'])
        self.next_button.setToolTip('Sonraki sayfa')
        self.next_button.clicked.connect(lambda: self.go_to_page(self.current_page() + 1))
        bar.addWidget(self.next_button)
        external = QPushButton('Varsayılan uygulamada aç')
        external.setObjectName('ghost')
        external.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path))))
        bar.addWidget(external)
        column.addLayout(bar)

        frame, inner = card(spacing=0, margins=(0, 0, 0, 0), shadow=False)
        if self.kind == 'pdf':
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView
            self.document = QPdfDocument(self)
            self.document.load(str(self.path))
            self.view = QPdfView(self)
            self.view.setDocument(self.document)
            self.view.setPageMode(QPdfView.PageMode.MultiPage)
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.view.pageNavigator().currentPageChanged.connect(lambda _page: self._update())
            self._pages = max(1, self.document.pageCount())
        else:
            self.view = QTextBrowser(self)
            self.view.setPlainText(documents.read_text(self.path))
            self.view.setStyleSheet('QTextBrowser { background:transparent; border:0; '
                                    'padding:14px; color:%s; }' % THEME['text'])
            self.view.verticalScrollBar().valueChanged.connect(lambda _value: self._update())
            self._pages = max(1, len(documents.text_pages(self.path)))
        inner.addWidget(self.view, 1)
        column.addWidget(frame, 1)
        return holder

    def _build_chat(self):
        frame, column = card(spacing=10, margins=(16, 14, 16, 14), shadow=False)
        column.addWidget(section_label('Bu belgeye sor'))
        self.chat_view = QTextBrowser()
        self.chat_view.setOpenLinks(False)
        self.chat_view.setStyleSheet('QTextBrowser { background:transparent; border:0; '
                                     'color:%s; }' % THEME['text'])
        self.chat_view.anchorClicked.connect(self._on_link)
        column.addWidget(self.chat_view, 1)
        self.chat_note = QLabel('')
        self.chat_note.setObjectName('hint')
        self.chat_note.setWordWrap(True)
        column.addWidget(self.chat_note)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.ask_input = QLineEdit()
        self.ask_input.setPlaceholderText('Belgeye sor…')
        self.ask_input.returnPressed.connect(self.ask)
        row.addWidget(self.ask_input, 1)
        self.ask_button = HoverIconButton('')
        self.ask_button.setObjectName('iconOnly')
        self.ask_button.setTintedIcon('send', THEME['text'])
        self.ask_button.setToolTip('Gönder')
        self.ask_button.clicked.connect(self.ask)
        row.addWidget(self.ask_button)
        column.addLayout(row)
        return frame

    # --- hazirlik --------------------------------------------------------------
    def _prepare(self):
        """Metni cikarir; embedding modeli varsa indeksler (uzun belgede arama icin)."""
        entry = {'path': self.path, 'kind': 'document', 'root': None, 'missing': False,
                 'new': False}
        try:
            cfg = load_config()
            library.transcribe(entry, cfg, log=self._log)
            if str(cfg.get('embedding_model', '')).strip():
                try:
                    library.index(entry, cfg, log=self._log)
                except (RuntimeError, ValueError, OSError) as error:
                    self._log('Belge indekslenemedi (kısa belgede gerekmez): ' + str(error))
        except Exception as error:  # metin yoksa / okunamazsa sohbet kapali kalir
            self._emit_prepared(str(error))
            return
        self._emit_prepared('')

    def _emit_prepared(self, error):
        try:
            self.prepared.emit(error)
        except RuntimeError:
            pass  # gorunum bu arada kapatildi

    def _on_prepared(self, error):
        if error:
            self._set_chat_enabled(False, 'Bu belgeye soru sorulamıyor: ' + error)
            return
        self._ready = True
        self._session = collection_qa.CollectionQA([self.path], self.path.stem, log=self._log)
        cfg = load_config()
        fits = self._session.whole_hits(cfg) is not None
        model = str(cfg.get('embedding_model', '')).strip()
        if fits or model:
            self._set_chat_enabled(True, '' if fits else 'Uzun belge: soruyla ilgili bölümler '
                                                         'aranarak cevaplanır.')
        else:
            self._set_chat_enabled(False, 'Belge tek seferde modele sığmayacak kadar uzun; soru '
                                          'sormak için Ayarlar → Kütüphane indeksi\'nden '
                                          'embedding modeli seçin.')

    def _set_chat_enabled(self, enabled, note):
        self.ask_input.setEnabled(enabled)
        self.ask_button.setEnabled(enabled)
        self.chat_note.setText(note)
        self.chat_note.setVisible(bool(note))

    # --- sohbet ------------------------------------------------------------------
    def _render_chat(self):
        self.chat_view.setHtml(chat_html(self._entries, self._targets, single=True))
        bar = self.chat_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def ask(self):
        question = ' '.join(self.ask_input.text().split())
        if not question or not self._ready or self._ask_job is not None:
            return
        self._entries += [('user', question), ('pending', 'Cevap hazırlanıyor…')]
        self.ask_input.clear()
        worker = AskWorker('', self._session, question)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._ask_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._ask_job = (thread, worker)
        self._set_chat_enabled(False, 'Cevap hazırlanıyor…')
        self._render_chat()
        thread.start()

    def _ask_finished(self, _slug, turn, error):
        self._ask_job = None
        self._entries = [item for item in self._entries if item[0] != 'pending']
        self._entries.append(('assistant', turn) if turn is not None
                             else ('error', 'Cevap alınamadı: ' + error))
        self._set_chat_enabled(True, '')
        self._render_chat()

    def _on_link(self, url):
        text = url.toString()
        if not text.startswith('cite:'):
            return
        try:
            _path, page = self._targets[int(text[5:])]
        except (ValueError, IndexError):
            return
        self.go_to_page(int(page))

    # --- gezinme -----------------------------------------------------------------
    def current_page(self):
        if self.kind == 'pdf':
            return self.view.pageNavigator().currentPage() + 1
        line = self.view.cursorForPosition(self.view.viewport().rect().topLeft()).blockNumber()
        return line // documents.TEXT_PAGE_LINES + 1

    def go_to_page(self, page):
        """1'den baslayan sayfa numarasina gider (atiftaki s.N)."""
        page = max(1, min(int(page), self._pages))
        if self.kind == 'pdf':
            navigator = self.view.pageNavigator()
            navigator.jump(page - 1, QPointF(), navigator.currentZoom())
        else:
            block = self.view.document().findBlockByNumber((page - 1) * documents.TEXT_PAGE_LINES)
            self.view.setTextCursor(QTextCursor(block))
            layout = self.view.document().documentLayout()
            self.view.verticalScrollBar().setValue(int(layout.blockBoundingRect(block).top()))
        self._update()

    def _update(self):
        page = self.current_page()
        self.page_label.setText(f's. {page} / {self._pages}')
        self.prev_button.setEnabled(page > 1)
        self.next_button.setEnabled(page < self._pages)

    def shutdown(self):
        if self._ask_job is not None:
            self._ask_job[0].quit()
            self._ask_job[0].wait(3000)
        if self.kind == 'pdf':
            self.document.close()
