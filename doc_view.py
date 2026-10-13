"""Belge goruntuleyici (F64): kutuphanede PDF/metin dosyasini acip atiftaki sayfaya gider.

PDF'ler QtPdf/QtPdfWidgets ile (PySide6 ile gelir) uygulama icinde gosterilir;
.txt/.md dosyalari duz metin olarak, documents.TEXT_PAGE_LINES satirlik
"sayfalarla" ayni numaralandirmada acilir. Kaynak dosya SALT-OKUNUR.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

import documents
from gui import THEME, HoverIconButton, card


class DocumentView(QWidget):
    """Tek belge: ust serit (sayfa, onceki/sonraki, varsayilan uygulamada ac) + icerik."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.kind = documents.kind_of(self.path)
        self._pages = 1
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 12, 16, 16)
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
        self._update()

    def current_page(self):
        if self.kind == 'pdf':
            return self.view.pageNavigator().currentPage() + 1
        line = self.view.cursorForPosition(self.view.viewport().rect().topLeft()).blockNumber()
        return line // documents.TEXT_PAGE_LINES + 1

    def go_to_page(self, page):
        """1'den baslayan sayfa numarasina gider (atiftaki s.N)."""
        page = max(1, min(int(page), self._pages))
        if self.kind == 'pdf':
            self.view.pageNavigator().jump(page - 1, QPointF(), self.view.pageNavigator().currentZoom())
        else:
            block = self.view.document().findBlockByNumber((page - 1) * documents.TEXT_PAGE_LINES)
            cursor = QTextCursor(block)
            self.view.setTextCursor(cursor)
            bar = self.view.verticalScrollBar()
            bar.setValue(int(self.view.document().documentLayout().blockBoundingRect(block).top()))
        self._update()

    def _update(self):
        page = self.current_page()
        self.page_label.setText(f's. {page} / {self._pages}')
        self.prev_button.setEnabled(page > 1)
        self.next_button.setEnabled(page < self._pages)

    def shutdown(self):
        if self.kind == 'pdf':
            self.document.close()
