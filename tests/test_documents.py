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
        pages, segments, _read = documents.extract(notes)
        self.assertEqual(pages, 3)
        self.assertEqual(segments[-1]['start'], 3.0)
        scanned = self.root / 'tarama.pdf'
        write_pdf(scanned, [[], []])
        with self.assertRaises(documents.NoTextError):
            documents.extract(scanned)
        entry = self.entry(scanned)
        with self.assertRaises(documents.NoTextError):
            library.transcribe(entry, dict(DEFAULT_CONFIG), base=self.work, log=QUIET,
                               allow_vision=False)
        self.assertEqual(library.describe(entry, self.work, {'embedding_model': ''})['status'],
                         'no_text')
        result = library.plan([entry, self.entry(self.pdf)], self.work,
                              cfg={'embedding_model': ''})
        self.assertEqual([item['path'].name for item in result['document']], ['Kılavuz.pdf'])
        self.assertEqual(([item['path'].name for item in result['vision']],
                          result['vision_pages']), (['tarama.pdf'], 2))

    def test_scanned_pages_and_images_are_read_with_vision_model(self):
        """F69: metinsiz PDF sayfalari ve gorseller gorsel modelle okunur (sahte model)."""
        seen = []

        def reader(_cfg, _log=None):
            def read(png, prompt):
                seen.append((png[:8], prompt[:20]))
                return ('Taranmış sayfa: kombi basıncı 1,5 bar olmalı.' if 'belge sayfası'
                        in prompt else 'AÇIKLAMA: Kırmızı bir kombi.\n\nYAZI: 1,5 bar')
            return read

        mixed = self.root / 'karışık.pdf'
        write_pdf(mixed, [['Kombi kılavuzu, birinci sayfa metni burada.'], []])
        entry = self.entry(mixed)
        # Gorsel izni yok: metinli sayfa kullanilir, taranmis sayfa sonra okunacak diye isaretlenir.
        library.transcribe(entry, dict(DEFAULT_CONFIG), base=self.work, log=QUIET,
                           allow_vision=False)
        self.assertIn('1 sayfa okunmadı',
                      library.describe(entry, self.work, {'embedding_model': ''})['source'])
        plan = library.plan([entry], self.work, cfg={'embedding_model': ''})
        self.assertEqual(([item['path'].name for item in plan['vision']], plan['vision_pages']),
                         (['karışık.pdf'], 1))
        pages_seen = []
        with mock.patch('library.vision_reader', reader):
            library.transcribe(entry, dict(DEFAULT_CONFIG), base=self.work, log=QUIET,
                               vision_progress=lambda done, total: pages_seen.append((done, total)))
        session = search_index.primary_session(mixed, self.work)
        self.assertEqual(session['source'].get('vision_pages'), 1)
        self.assertNotIn('unread_pages', session['source'])
        self.assertEqual([(item['start'], item['text']) for item in session['segments']][-1],
                         (2.0, 'Taranmış sayfa: kombi basıncı 1,5 bar olmalı.'))
        self.assertEqual(pages_seen, [(1, 1)])
        self.assertEqual(seen[0][0], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(len(qa.cached_sessions(mixed, self.work)), 1)

        from PySide6.QtGui import QColor, QImage
        photo = self.root / 'kombi.jpg'
        image = QImage(64, 48, QImage.Format_RGB32)
        image.fill(QColor('red'))
        self.assertTrue(image.save(str(photo)))
        self.assertEqual(library.kind_of(photo), 'image')
        with mock.patch('library.vision_reader', reader):
            library.transcribe(self.entry(photo), dict(DEFAULT_CONFIG), base=self.work,
                               log=QUIET)
        info = library.describe(self.entry(photo), self.work, {'embedding_model': ''})
        self.assertEqual(info['source'], 'Görü modeli')
        # Model gorsel atfini '[V2 gorsel]' diye de yazabilir: baglantiya donmeli.
        chat = collection_qa.CollectionQA([mixed, photo], 'K', lambda: dict(DEFAULT_CONFIG),
                                          log=QUIET, base=self.work)
        parts = chat.split_citations('Kombi kırmızı [V2 Görsel]; sayfa [V1 görsel].',
                                     {'V1': mixed, 'V2': photo})
        cites = [cite['label'] for kind, value in parts if kind == 'cite' for cite in value]
        self.assertEqual(cites, ['V2 görsel'])
        self.assertIn('Kırmızı bir kombi', ' '.join(line['text'] for line in info['lines']))

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
        pages, segments, _read = documents.extract(path)
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

    def test_pptx_and_opendocument_formats(self):
        """F73: PowerPoint slaytlari, ODT/ODS/ODP ve HTML."""
        a_ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        p_ns = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        slide = (f'<p:sld {a_ns} {p_ns}><p:cSld><p:spTree><p:sp><p:txBody>'
                 '<a:p><a:r><a:t>{}</a:t></a:r></a:p><a:p><a:r><a:t>Madde </a:t></a:r>'
                 '<a:r><a:t>bir</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
        pptx = self.root / 'sunum.pptx'
        write_zip(pptx, {
            'ppt/presentation.xml': f'<p:presentation {p_ns} {R_NS}><p:sldIdLst>'
                                    '<p:sldId r:id="rId2"/><p:sldId r:id="rId1"/></p:sldIdLst>'
                                    '</p:presentation>',
            'ppt/_rels/presentation.xml.rels': (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="slides/slide1.xml"/>'
                '<Relationship Id="rId2" Target="slides/slide2.xml"/></Relationships>'),
            'ppt/slides/slide1.xml': slide.replace('{}', 'İkinci slayt'),
            'ppt/slides/slide2.xml': slide.replace('{}', 'Giriş')})
        self.assertEqual(documents.pages_of(pptx),
                         ['Giriş\n\nMadde bir', 'İkinci slayt\n\nMadde bir'])
        self.assertEqual(documents.kind_of(pptx), 'slides')
        office = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                  'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
                  'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
                  'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"')
        odt = self.root / 'not.odt'
        write_zip(odt, {'content.xml': (
            f'<office:document-content {office}><office:body><office:text>'
            '<text:h>Başlık</text:h><text:p>Bir<text:s text:c="2"/>iki<text:tab/>üç</text:p>'
            '</office:text></office:body></office:document-content>')})
        self.assertEqual(documents.pages_of(odt), ['Başlık\n\nBir  iki\tüç'])
        ods = self.root / 'tablo.ods'
        write_zip(ods, {'content.xml': (
            f'<office:document-content {office}><office:body><office:spreadsheet>'
            '<table:table table:name="Stok"><table:table-row>'
            '<table:table-cell><text:p>Ürün</text:p></table:table-cell>'
            '<table:table-cell><text:p>Adet</text:p></table:table-cell>'
            '<table:table-cell table:number-columns-repeated="16000"/></table:table-row>'
            '<table:table-row><table:table-cell><text:p>Çay</text:p></table:table-cell>'
            '<table:table-cell><text:p>7</text:p></table:table-cell></table:table-row>'
            '<table:table-row table:number-rows-repeated="1048000"><table:table-cell/>'
            '</table:table-row></table:table></office:spreadsheet></office:body>'
            '</office:document-content>')})
        pages = documents.pages_of(ods)
        self.assertIn('Stok · sütunlar: Ürün, Adet', pages[0])
        self.assertIn('Satır 2: Ürün: Çay; Adet: 7', pages[0])
        self.assertLess(len(pages[0]), 500, 'bos tekrar eden satir/sutunlar sisirmemeli')
        odp = self.root / 'sunu.odp'
        write_zip(odp, {'content.xml': (
            f'<office:document-content {office}><office:body><office:presentation>'
            '<draw:page><text:p>Slayt 1</text:p></draw:page>'
            '<draw:page><text:p>Slayt 2</text:p></draw:page>'
            '</office:presentation></office:body></office:document-content>')})
        self.assertEqual(documents.pages_of(odp), ['Slayt 1', 'Slayt 2'])
        page = self.root / 'sayfa.html'
        page.write_text('<html><head><title>x</title><script>var a;</script></head><body>'
                        '<h1>Duyuru</h1><p>Toplantı &amp; sunum yarın.</p></body></html>',
                        encoding='utf-8')
        self.assertEqual(documents.pages_of(page), ['Duyuru\n\nToplantı & sunum yarın.'])
        rtf = self.root / 'mektup.rtf'
        rtf.write_bytes(b"{\\rtf1\\ansi\\ansicpg1254{\\fonttbl{\\f0 Arial;}}\\f0 "
                        b"Say\\'fdn \\u305?lgili,\\par Te\\'feekk\\u252?rler.}")
        self.assertEqual(documents.pages_of(rtf), ['Sayın ılgili,\n\nTeşekkürler.'])

    def test_legacy_office_needs_libreoffice_and_reads_converted_copy(self):
        """F73: .doc/.xls/.ppt LibreOffice ile .docx/.xlsx/.pptx'e cevrilip okunur."""
        legacy = self.root / 'eski.doc'
        legacy.write_bytes(b'\xd0\xcf\x11\xe0 ole')
        with mock.patch('documents.office_converter', return_value=None):
            with self.assertRaises(ValueError) as caught:
                documents.pages_of(legacy)
        self.assertIn('LibreOffice', str(caught.exception))

        def fake_run(command, **_kwargs):
            outdir = Path(command[command.index('--outdir') + 1])
            write_zip(outdir / 'eski.docx', {'word/document.xml': (
                f'<w:document {W_NS}><w:body><w:p><w:r><w:t>Eski belge metni.</w:t></w:r>'
                '</w:p></w:body></w:document>')})
            return mock.Mock(returncode=0, stderr='', stdout='')

        with mock.patch('documents.office_converter', return_value='soffice'), \
                mock.patch('subprocess.run', side_effect=fake_run) as run, \
                mock.patch('qa.work_dir', return_value=self.root / 'work'):
            self.assertEqual(documents.pages_of(legacy), ['Eski belge metni.'])
            documents.pages_of(legacy)
            self.assertEqual(run.call_count, 1, 'donusturulmus kopya tekrar kullanilmali')
            self.assertIn('--headless', run.call_args.args[0])

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
