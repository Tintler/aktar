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
        # F67: belge ozeti (kisa belge: tek istek; uzun belge: once parca ozetleri).
        replies = []

        def chat(_self, messages):
            replies.append(messages)
            return ('{"summary": "Parça özeti."}' if 'one part' in messages[0]['content'] else
                    '{"summary": "Süpürge kılavuzu.", "topics": ["bakım"], "questions": ["q?"]}')

        with mock.patch('app_core.Client.chat', chat):
            overview = collection_qa.summarize_video(self.pdf, lambda: dict(cfg), QUIET,
                                                     base=self.work)
            self.assertEqual(overview['summary'], 'Süpürge kılavuzu.')
            self.assertEqual(len(replies), 1)
            self.assertIn('[s.2] Bakım', replies[0][1]['content'])
            self.assertEqual(collection_qa.video_summaries([self.pdf], self.work)[0]['summary'],
                             'Süpürge kılavuzu.')
            session = search_index.primary_session(self.pdf, self.work)
            session['overview'] = None
            session['segments'] += [{'start': 3.0, 'end': 3.0, 'text': 'Uzun metin. ' * 22}
                                    for _ in range(30)]  # ~8 bin karakter: tek istege sigmaz
            replies.clear()
            with mock.patch('qa.SECTION_CHARS', 40):
                collection_qa.summarize_document(session, self.root / 'uzun.json',
                                                 lambda: dict(cfg, qa_context_chars=1000), QUIET)
            self.assertGreater(len(replies), 1)
            self.assertIn('[s.1-1] Parça özeti.', replies[-1][1]['content'])

    def test_single_short_document_is_answered_without_index(self):
        """F66: tek belgeye soru; metin baglama sigiyorsa embedding/indeks gerekmez."""
        cfg = dict(DEFAULT_CONFIG, embedding_model='', auto_retry_count=1)
        library.transcribe(self.entry(self.pdf), cfg, base=self.work, log=QUIET)

        class NoEmbed(FakeClient):
            def embed(self, texts):
                raise AssertionError('kisa belgede arama yapilmamali')

        chat = collection_qa.CollectionQA([self.pdf], 'Kılavuz', lambda: dict(cfg), log=QUIET,
                                          base=self.work)
        self.assertIsNotNone(chat.whole_hits(cfg))
        client = NoEmbed()
        turn = chat.ask('filtre', client)
        self.assertIn('[s.1] Kullanım Kılavuzu', client.messages[0]['content'])
        self.assertEqual([cite['label'] for kind, value in turn['parts'] if kind == 'cite'
                          for cite in value], ['V1 s.2'])
        tiny = dict(cfg, qa_context_chars=1000)
        long_doc = collection_qa.CollectionQA([self.pdf], 'K', lambda: tiny, log=QUIET,
                                              base=self.work)
        long_doc._video_lines(self.pdf)[1].extend([{'start': 2.0, 'end': 2.0, 'text': 'x' * 900}])
        self.assertIsNone(long_doc.whole_hits(tiny))

    def test_paragraphs_split_long_blocks_at_sentences(self):
        text = ('Bir cümle burada. ' * 60).strip() + '\n\nİkinci paragraf.'
        parts = documents.paragraphs(text)
        self.assertTrue(all(len(part) <= documents.PARAGRAPH_CHARS for part in parts))
        self.assertTrue(parts[0].endswith('.'))
        self.assertEqual(parts[-1], 'İkinci paragraf.')


W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def write_zip(path, files):
    import zipfile
    with zipfile.ZipFile(path, 'w') as archive:
        for name, text in files.items():
            archive.writestr(name, text)


class OfficeAndEbookTests(unittest.TestCase):
    """F68: Word, Excel/CSV ve EPUB zip/XML'den ek kutuphanesiz okunur."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_docx_keeps_word_page_breaks(self):
        path = self.root / 'rapor.docx'
        write_zip(path, {'word/document.xml': (
            f'<w:document {W_NS}><w:body>'
            '<w:p><w:r><w:t>Giriş bölümü.</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">İkinci </w:t></w:r><w:r><w:t>paragraf.</w:t></w:r></w:p>'
            '<w:p><w:r><w:br w:type="page"/><w:t>Sonuç: bütçe aşıldı.</w:t></w:r></w:p>'
            '</w:body></w:document>')})
        pages, segments = documents.extract(path)
        self.assertEqual(pages, 2)
        self.assertEqual([(item['start'], item['text']) for item in segments],
                         [(1.0, 'Giriş bölümü.'), (1.0, 'İkinci paragraf.'),
                          (2.0, 'Sonuç: bütçe aşıldı.')])

    def test_xlsx_rows_use_headers_and_csv_delimiter(self):
        path = self.root / 'satis.xlsx'
        write_zip(path, {
            'xl/workbook.xml': f'<workbook {S_NS} {R_NS}><sheets><sheet name="Ocak" r:id="rId1"/>'
                               '</sheets></workbook>',
            'xl/_rels/workbook.xml.rels': (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'),
            'xl/sharedStrings.xml': f'<sst {S_NS}><si><t>Ürün</t></si><si><t>Adet</t></si>'
                                    '<si><t>Çay</t></si></sst>',
            'xl/worksheets/sheet1.xml': (
                f'<worksheet {S_NS}><sheetData>'
                '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>42</v></c></row>'
                '</sheetData></worksheet>')})
        pages = documents.pages_of(path)
        self.assertEqual(len(pages), 1)
        self.assertIn('Ocak · sütunlar: Ürün, Adet', pages[0])
        self.assertIn('Satır 2: Ürün: Çay; Adet: 42', pages[0])
        csv_path = self.root / 'liste.csv'
        csv_path.write_text('Ad;Şehir\nAyşe;İzmir\n', encoding='utf-8')
        self.assertIn('Satır 2: Ad: Ayşe; Şehir: İzmir', documents.pages_of(csv_path)[0])

    def test_epub_chapters_in_spine_order(self):
        path = self.root / 'kitap.epub'
        write_zip(path, {
            'META-INF/container.xml': (
                '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>'),
            'OEBPS/content.opf': (
                '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
                '<item id="b" href="text/b.xhtml"/><item id="a" href="text/a.xhtml"/></manifest>'
                '<spine><itemref idref="a"/><itemref idref="b"/></spine></package>'),
            'OEBPS/text/a.xhtml': '<html><head><style>p{}</style></head><body><h1>Bölüm 1</h1>'
                                  '<p>Yolculuk başlar.</p></body></html>',
            'OEBPS/text/b.xhtml': '<html><body><p>Son &amp; dönüş.</p></body></html>'})
        pages = documents.pages_of(path)
        self.assertEqual(pages, ['Bölüm 1\n\nYolculuk başlar.', 'Son & dönüş.'])
        self.assertEqual(library.kind_of(path), 'document')
        broken = self.root / 'bozuk.epub'
        broken.write_bytes(b'zip degil')
        with self.assertRaises(ValueError):
            documents.pages_of(broken)


if __name__ == '__main__':
    unittest.main()
