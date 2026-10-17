"""F146 kitapla sohbet: EPUB sayfalari okuyucunun bolum numaralariyla (documents.epub_pages), sorudaki bolum
adinin/numarasinin bulunmasi (bridge_reader.focus_sections), "okudugum yere kadar" sayfa siniri, odak sayfalari
ve tek sayfasi cok uzun belgede baglamin isabet parcasina daralmasi (collection_qa)."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import book_reader  # noqa: E402
import collection_qa  # noqa: E402
import documents  # noqa: E402
import qa  # noqa: E402
from bridge_reader import focus_sections  # noqa: E402

TOC = [{'section': 0, 'title': 'Contents', 'depth': 0}, {'section': 1, 'title': 'Chapter I. The Start', 'depth': 0},
       {'section': 2, 'title': 'Chapter II', 'depth': 0}, {'section': 3, 'title': 'Chapter III. The Storm', 'depth': 0},
       {'section': 4, 'title': 'Hercules and the Carter', 'depth': 1}]


def make_epub(path, chapters):
    """Kapak (yalniz resim) + baslikli bolumler; icindekiler nav ile."""
    items = ['<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>',
             '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>']
    spine = ['<itemref idref="cover"/>']
    links = []
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('META-INF/container.xml', '<?xml version="1.0"?><container version="1.0" '
                         'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile '
                         'full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        archive.writestr('OEBPS/cover.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"><body><img src="c.png"/></body></html>')
        for number, (title, text) in enumerate(chapters, 1):
            name = f'c{number}.xhtml'
            items.append(f'<item id="c{number}" href="{name}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="c{number}"/>')
            links.append(f'<li><a href="{name}">{title}</a></li>')
            archive.writestr('OEBPS/' + name, f'<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{text}</p></body></html>')
        archive.writestr('OEBPS/nav.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
                         '<body><nav epub:type="toc"><ol>' + ''.join(links) + '</ol></nav></body></html>')
        archive.writestr('OEBPS/content.opf', '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                         '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>T</dc:title><dc:language>en</dc:language>'
                         '</metadata><manifest>' + ''.join(items) + '</manifest><spine>' + ''.join(spine) + '</spine></package>')


class FocusTests(unittest.TestCase):
    def test_numbers_titles_and_roman(self):
        self.assertEqual(focus_sections('3. bölümde ne oldu?', TOC), [3])
        self.assertEqual(focus_sections("3'üncü bölümü özetle", TOC), [3])
        self.assertEqual(focus_sections('Bölüm 2 kısaca', TOC), [2])
        self.assertEqual(focus_sections('What happens in chapter 1?', TOC), [1])
        self.assertEqual(focus_sections('HERCULES AND THE CARTER masalı', TOC), [4])

    def test_no_chapter_named(self):
        self.assertEqual(focus_sections('Ana karakter kim?', TOC), [])
        self.assertEqual(focus_sections('1952 yılında ne oldu?', TOC), [])

    def test_falls_back_to_nth_top_level_entry(self):
        toc = [{'section': 1, 'title': 'Giriş', 'depth': 0}, {'section': 2, 'title': 'Yolculuk', 'depth': 0}]
        self.assertEqual(focus_sections('2. bölümde ne oldu?', toc), [2])
        self.assertEqual(focus_sections('9. bölüm', toc), [])


class EpubPagesTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='aktar-test-bc-'))
        self.epub = self.folder / 'kitap.epub'
        make_epub(self.epub, [('Birinci', 'Ali yola çıktı.'), ('İkinci', 'Fırtına koptu.')])

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_pages_follow_reader_sections_and_start_with_title(self):
        book = book_reader.EpubBook(self.epub)
        pages = documents.epub_pages(self.epub)
        self.assertEqual(len(pages), len(book.sections))
        self.assertEqual(pages[0], '')                      # kapak bos sayfa olarak sirada kalir
        self.assertTrue(pages[2].startswith('İkinci\n\nFırtına koptu.'))

    def test_search_finds_words_across_sections_ignoring_case(self):
        import book_search
        book = book_reader.EpubBook(self.epub)
        result = book_search.search(book, 'fırtına  KOPTU')
        self.assertEqual(result['total'], 1)
        self.assertEqual((result['results'][0]['section'], result['results'][0]['index']), (2, 0))
        self.assertEqual(result['results'][0]['match'], 'Fırtına koptu')
        self.assertEqual(book_search.search(book, 'ALİ')['total'], 1)       # İ/i farki yok
        self.assertEqual(book_search.search(book, '   ')['total'], 0)
        self.assertEqual(len(book_search.fold('İIıi')), 4)

    def test_epub_cache_key_changed(self):
        self.assertEqual(qa.source_key({'kind': 'epub'}), 'document:epub:2')


class Fake(collection_qa.CollectionQA):
    """Diskten okumadan: tek belgenin satirlari verilir."""

    def __init__(self, lines):
        super().__init__(['kitap.epub'], 'Kitap', config_provider=lambda: {})
        self.raw = lines
        self._summaries = []

    def _video_lines(self, video):
        lines = self.raw if self.page_limit is None else collection_qa.read_lines(self.raw, self.page_limit, self.page_fraction)
        return ('Kitap', lines, 3.0, 'epub')

    def notes_text(self, cfg):
        return '', {}


class ContextTests(unittest.TestCase):
    def setUp(self):
        long_page = [{'start': 2, 'end': 2, 'text': f'Satır {index} ' + 'x' * 300} for index in range(200)]
        self.lines = [{'start': 1, 'end': 1, 'text': 'Giriş metni.'}] + long_page + [{'start': 3, 'end': 3, 'text': 'Son bölüm sırrı.'}]
        self.cfg = {'qa_context_chars': 24000}

    def test_long_page_narrows_to_hit_text(self):
        session = Fake(self.lines)
        hit = {'video': 'kitap.epub', 'start': 2, 'end': 2, 'text': self.lines[51]['text'] + ' ' + self.lines[52]['text']}
        text, videos = session.build_context([hit], self.cfg)
        self.assertIn('Satır 50 ', text)
        self.assertIn('Satır 51 ', text)
        self.assertNotIn('Satır 120 ', text)
        self.assertEqual(list(videos), ['V1'])

    def test_page_limit_hides_later_pages(self):
        session = Fake(self.lines)
        session.page_limit = 2
        text, _videos = session.build_context([{'video': 'kitap.epub', 'start': 3, 'end': 3, 'text': 'Son bölüm sırrı.'}], self.cfg)
        self.assertNotIn('sırrı', text)

    def test_fraction_keeps_only_read_part_of_last_page(self):
        lines = [{'start': 1, 'end': 1, 'text': 'a' * 10}] + [{'start': 2, 'end': 2, 'text': str(i) * 10} for i in range(10)] \
            + [{'start': 3, 'end': 3, 'text': 'sır'}]
        kept = collection_qa.read_lines(lines, 2, 0.3)
        self.assertEqual([line['text'][0] for line in kept], ['a', '0', '1', '2'])
        self.assertEqual(len(collection_qa.read_lines(lines, 2, 1.0)), 11)
        self.assertEqual(len(collection_qa.read_lines(lines, 2, 0.0)), 1)

    def test_focus_hits_take_the_start_of_named_pages(self):
        session = Fake(self.lines)
        session.focus_pages = [2, 3]
        session.page_limit = 2
        hits = session.focus_hits(self.cfg)
        self.assertEqual([(hit['start'], hit['chars']) for hit in hits], [(2, int(24000 * collection_qa.FOCUS_SHARE))])
        text, _videos = session.build_context(hits, self.cfg)
        self.assertIn('Satır 0 ', text)


if __name__ == '__main__':
    unittest.main()
