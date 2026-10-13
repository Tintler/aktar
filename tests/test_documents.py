"""Belge destegi (F64): PDF/metin cikarma, plan, sayfa atiflari, disa aktarma."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import collection_qa  # noqa: E402
import documents  # noqa: E402
import library  # noqa: E402
import qa  # noqa: E402
import search_index  # noqa: E402
import transcript_export  # noqa: E402
from app_core import DEFAULT_CONFIG  # noqa: E402

try:
    from PySide6.QtGui import QFont, QGuiApplication, QPageSize, QPainter, QPdfWriter
    from PySide6.QtPdf import QPdfDocument  # noqa: F401
except ImportError:  # pragma: no cover - PySide6'siz ortam
    QGuiApplication = None

QUIET = (lambda _message: None)


def write_pdf(path, pages):
    """Her sayfaya verilen satirlari yazan PDF (bos liste = metinsiz sayfa)."""
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    painter = QPainter(writer)
    painter.setFont(QFont('Arial', 12))
    for index, lines in enumerate(pages):
        if index:
            writer.newPage()
        for row, line in enumerate(lines):
            painter.drawText(300, 300 + row * 300, line)
    painter.end()


class FakeClient:
    def embed(self, texts):
        words = ('filtre', 'şarj', 'garanti')
        return [[float(text.lower().count(word)) + 0.01 for word in words] for text in texts]

    def chat(self, messages):
        self.messages = messages
        return 'Filtre ayda bir yıkanır [V1 s.2]. Yanlış sayfa [V1 s.9], yanlış biçim [V1 0:30].'


@unittest.skipIf(QGuiApplication is None, 'PySide6 (QtPdf) gerekli')
class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication(sys.argv)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.work = self.root / 'work'
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(self.root / 'store')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pdf = self.root / 'Kılavuz.pdf'
        write_pdf(self.pdf, [['Kullanım Kılavuzu', 'Şarj ışığı yeşil yanınca pil doludur.'],
                             ['Bakım', 'Filtreyi ayda bir kez ılık suyla yıkayın.']])

    def entry(self, path):
        return {'path': path, 'kind': library.kind_of(path), 'root': None, 'missing': False,
                'new': False}

    def test_pdf_pages_become_page_numbered_session(self):
        data, _cache = documents.load_session(self.pdf, self.work, QUIET)
        self.assertEqual(data['source'], {'kind': 'pdf', 'pages': 2})
        self.assertEqual(data['duration'], 2.0)
        pages = {segment['start']: segment['text'] for segment in data['segments']}
        self.assertIn('Filtreyi ayda bir kez ılık suyla yıkayın.', pages[2.0])
        self.assertEqual(qa.format_lines(qa.lines_of(data), True).splitlines()[0][:5], '[s.1]')
        again, _cache = documents.load_session(self.pdf, self.work, QUIET)
        self.assertEqual(again, data)
        self.assertEqual(len(qa.cached_sessions(self.pdf, self.work)), 1)

    def test_text_file_pages_and_scanned_pdf(self):
        notes = self.root / 'notlar.md'
        notes.write_text('\n'.join(f'satır {index}' for index in range(1, 131)),
                         encoding='utf-8')
        pages, segments = documents.extract(notes)
        self.assertEqual(pages, 3)
        self.assertEqual(segments[-1]['start'], 3.0)
        scanned = self.root / 'tarama.pdf'
        write_pdf(scanned, [[], []])
        with self.assertRaises(documents.NoTextError):
            documents.extract(scanned)
        entry = self.entry(scanned)
        with self.assertRaises(documents.NoTextError):
            library.transcribe(entry, dict(DEFAULT_CONFIG), base=self.work, log=QUIET)
        self.assertEqual(library.describe(entry, self.work, {'embedding_model': ''})['status'],
                         'no_text')
        result = library.plan([entry, self.entry(self.pdf)], self.work,
                              cfg={'embedding_model': ''})
        self.assertEqual([item['path'].name for item in result['document']], ['Kılavuz.pdf'])
        self.assertEqual(len(result['failed']), 1)

    def test_document_is_indexed_cited_by_page_and_exported(self):
        cfg = dict(DEFAULT_CONFIG, embedding_model='emb', auto_retry_count=1)
        entry = self.entry(self.pdf)
        self.assertEqual(library.transcribe(entry, cfg, base=self.work, log=QUIET), 'document')
        search_index.build(self.pdf, cfg, FakeClient(), self.work, log=QUIET)
        info = library.describe(entry, self.work, cfg)
        self.assertEqual((info['status'], info['source'], info['duration']),
                         ('ready', 'PDF metni', 2.0))
        hits, _matched = library.transcript_hits([entry], [info], 'filtre')
        self.assertEqual(hits[0]['start'], 2.0)
        chat = collection_qa.CollectionQA([self.pdf], 'Kılavuzlar', lambda: dict(cfg), log=QUIET,
                                          base=self.work)
        client = FakeClient()
        turn = chat.ask('filtre nasıl temizlenir', client)
        self.assertIn('### V1 · Kılavuz (belge, 2 sayfa)', client.messages[0]['content'])
        self.assertIn('[s.2] Bakım', client.messages[0]['content'])
        cites = [cite for kind, value in turn['parts'] if kind == 'cite' for cite in value]
        self.assertEqual([(cite['label'], cite['start'], cite['document']) for cite in cites],
                         [('V1 s.2', 2.0, True)])
        session = search_index.primary_session(self.pdf, self.work)
        self.assertIn('**[s.2]** Bakım', transcript_export.render(session, 'md'))
        with self.assertRaises(ValueError):
            transcript_export.render(session, 'srt')
        self.assertIsNone(collection_qa.summarize_video(self.pdf, lambda: dict(cfg), QUIET,
                                                        base=self.work))

    def test_paragraphs_split_long_blocks_at_sentences(self):
        text = ('Bir cümle burada. ' * 60).strip() + '\n\nİkinci paragraf.'
        parts = documents.paragraphs(text)
        self.assertTrue(all(len(part) <= documents.PARAGRAPH_CHARS for part in parts))
        self.assertTrue(parts[0].endswith('.'))
        self.assertEqual(parts[-1], 'İkinci paragraf.')


if __name__ == '__main__':
    unittest.main()
