"""Taranmis PDF'den EPUB (F138): pdf_book."""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))


import tempfile
import unittest
import zipfile
from pathlib import Path

import pdf_book
from book_reader import EpubBook
from epub_import import prepare


def scanned_pdf(path, sizes):
    """Metin katmani olmayan (taranmis gibi) PDF; sizes: sayfa boyutlari (genis = cift sayfa)."""
    from PIL import Image
    pages = [Image.new('RGB', size, 'white') for size in sizes]
    pages[0].save(path, 'PDF', save_all=True, append_images=pages[1:])
    return path


class CleaningTests(unittest.TestCase):
    def test_running_headers_page_numbers_and_hyphens(self):
        bodies = ['Yaşlı adam yolda yürüyordu ve kasabaya var-\nmak istiyordu.', 'Çöl sıcaktı, rüzgâr esmiyordu.',
                  'Rahip bir taş buldu ve onu kaldırdı.', 'Gece olunca ateş yaktılar.', 'Sabah erkenden yola çıktılar.',
                  'Kasabada kimse onları beklemiyordu.']
        texts = [f'T.me/Cinciva\n\n{body}\n\nLA (L\'s Affair) {number:03d}\n\n{number + 10}'
                 for number, body in enumerate(bodies, 1)]
        paragraphs, language, _warnings = pdf_book.clean_pages(texts)
        self.assertEqual(language, 'tr')
        joined = [p['text'] for p in paragraphs]
        self.assertNotIn('T.me/Cinciva', ' '.join(joined))
        self.assertFalse(any('Affair' in text or text.isdigit() for text in joined))
        self.assertEqual(joined[0], 'Yaşlı adam yolda yürüyordu ve kasabaya varmak istiyordu.')
        self.assertEqual(len(joined), 6)

    def test_paragraph_continues_across_pages(self):
        texts = ['Francis Kardeş orada, yıkıntıların doğu sınırının yakının-',
                 'da, kazma yerine bir çapa kullanarak siper kazmıştı. Gece oldu',
                 've rüzgâr esti.\n\nYeni paragraf.']
        paragraphs, _language, _warnings = pdf_book.clean_pages(texts, 'tr')
        self.assertEqual([p['text'] for p in paragraphs], [
            'Francis Kardeş orada, yıkıntıların doğu sınırının yakınında, kazma yerine bir çapa kullanarak '
            'siper kazmıştı. Gece oldu ve rüzgâr esti.', 'Yeni paragraf.'])
        self.assertEqual(paragraphs[0]['page'], 1)

    def test_short_lines_ending_a_sentence_split_paragraphs(self):
        # Tesseract diyaloglari bos satirsiz verebilir: kisa ve noktalamayla biten satir paragraf sonudur.
        text = ('“...ve ondan sonra, Peder, ekmekle peyniri az daha alacak-\ntım.”\n“Ama almadın mı?”\n'
                'Francis başını salladı ve uzun uzun düşündükten sonra yavaşça\nkonuştu.')
        paragraphs, _language, _warnings = pdf_book.clean_pages([text], 'tr')
        self.assertEqual([p['text'] for p in paragraphs], [
            '“...ve ondan sonra, Peder, ekmekle peyniri az daha alacaktım.”', '“Ama almadın mı?”',
            'Francis başını salladı ve uzun uzun düşündükten sonra yavaşça konuştu.'])

    def test_english_keeps_real_compounds(self):
        texts = ['The well-known professor was minimiz-ing the damage. It was well known and he was a professor of '
                 'the old school. The damage was done.']
        paragraphs, language, _warnings = pdf_book.clean_pages(texts)
        self.assertEqual(language, 'en')
        self.assertIn('well-known', paragraphs[0]['text'])
        self.assertIn('minimizing', paragraphs[0]['text'])

    def test_warnings_for_empty_and_foreign_script_pages(self):
        _paragraphs, _language, warnings = pdf_book.clean_pages(['Hello there.', '', '“他’s listed,” he said.'], 'en')
        self.assertEqual([w['page'] for w in warnings], [2, 3])


class ChapterTests(unittest.TestCase):
    def paragraphs(self, pages):
        return [{'text': text, 'page': page} for page, texts in enumerate(pages, 1) for text in texts]

    def test_strong_headings_with_subtitle_and_front_matter(self):
        paragraphs = self.paragraphs([['Copyright 2009.'], ['Chapter 1', 'The Storm', 'It rained.'],
                                      ['More rain.'], ['CHAPTER 2', 'It stopped.']])
        chapters = pdf_book.split_chapters(paragraphs, 'en')
        self.assertEqual([c['title'] for c in chapters], ['Front matter', 'Chapter 1: The Storm', 'CHAPTER 2'])
        self.assertEqual(chapters[0]['paragraphs'], ['Copyright 2009.'])
        self.assertEqual(chapters[1]['paragraphs'], ['It rained.', 'More rain.'])
        self.assertEqual((chapters[1]['page'], chapters[1]['ordinal'], chapters[1]['skip']), (2, 0, 2))

    def test_saved_boundaries_survive_text_edits_and_skip_inserted_headings(self):
        paragraphs = self.paragraphs([['Intro.'], ['It rained.', 'More rain.'], ['It stopped.']])
        boundaries = [{'title': 'Giriş', 'page': 1, 'ordinal': 0, 'skip': 0, 'level': 0},
                      {'title': '7', 'page': 2, 'ordinal': 1, 'skip': 0, 'level': 1},
                      {'title': 'Son', 'page': 3, 'ordinal': 5, 'skip': 0, 'level': 0}]   # sayfada 5. paragraf yok
        chapters = pdf_book.chapters_from(paragraphs, boundaries)
        self.assertEqual([(c['title'], c['paragraphs']) for c in chapters],
                         [('Giriş', ['Intro.', 'It rained.']), ('7', ['More rain.', 'It stopped.']), ('Son', [])])
        auto = pdf_book.auto_boundaries([{'text': 'Intro.', 'page': 1}, {'text': '1', 'page': 2, 'inserted': True},
                                         {'text': 'It rained.', 'page': 2}, {'text': '2', 'page': 3},
                                         {'text': 'It stopped.', 'page': 3}], 'en')
        self.assertEqual([(b['title'], b['page'], b['ordinal'], b['skip']) for b in auto],
                         [('Front matter', 1, 0, 0), ('1', 2, 0, 0), ('2', 3, 0, 1)])

    def test_bracketed_headings_and_fallback_chunks(self):
        paragraphs = self.paragraphs([['[Holy Empire]', 'A nation.'], ['Text.'], ['Text.'], ['[September 2009]', 'Go.'],
                                      ['Text.'], ['Text.']])
        self.assertEqual([c['title'] for c in pdf_book.split_chapters(paragraphs, 'en')],
                         ['[Holy Empire]', '[September 2009]'])
        plain = self.paragraphs([['Bir.']] * 40)
        self.assertEqual([c['title'] for c in pdf_book.split_chapters(plain, 'tr')], ['Bölüm 1', 'Bölüm 2', 'Bölüm 3'])

    def test_outline_is_used_and_page_labels_are_ignored(self):
        paragraphs = self.paragraphs([['a.'], ['b.'], ['c.'], ['d.']])
        chapters = pdf_book.split_chapters(paragraphs, 'en', [(1, 'Prologue'), (3, 'The Case')])
        self.assertEqual([(c['title'], c['paragraphs']) for c in chapters], [('Prologue', ['a.', 'b.']), ('The Case', ['c.', 'd.'])])


class PdfToEpubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_spread_pages_are_split_and_reading_resumes_from_cache(self):
        pdf = scanned_pdf(self.root / 'Kitap Adı - Yazar Adı.pdf', [(600, 850), (1300, 850), (600, 850)])
        calls = []

        def read(png, prompt):
            calls.append(len(png))
            return f'Sayfa metni {len(calls)}.'
        work = pdf_book.work_dir(pdf, self.root / 'cikti')
        texts = pdf_book.read_pages(pdf, work, read)
        self.assertEqual(len(calls), 4)                                    # 2. sayfa sol + sag
        self.assertEqual(texts[1], 'Sayfa metni 2.\n\nSayfa metni 3.')
        self.assertEqual(sorted(p.name for p in (work / 'ocr').iterdir()), ['0001.txt', '0002a.txt', '0002b.txt', '0003.txt'])
        (work / 'ocr' / '0003.txt').unlink()
        self.assertEqual(pdf_book.read_pages(pdf, work, read)[2], 'Sayfa metni 5.')   # yalnizca eksik sayfa
        self.assertEqual(len(calls), 5)

    def test_epub_opens_in_reader_and_book_import(self):
        pdf = scanned_pdf(self.root / 'Leibowitz Icin Bir Ilahi - Walter M Miller JR.pdf', [(600, 850)] * 4)
        texts = ['BÖLÜM 1\n\nIssız çöl\n\nGenç rahip yürüdü ve bir taş buldu.', 'Taşı kaldırdı ve bir yazı gördü.',
                 'BÖLÜM 2\n\nYaşlı adam güldü.', 'Sonra gitti.']
        pages = iter(texts)
        work = self.root / 'is'
        pdf_book.read_pages(pdf, work, lambda png, prompt: next(pages))
        epub, info = pdf_book.build_epub(pdf, work, log=lambda *_: None)
        self.assertEqual((info['title'], info['author'], info['language']),
                         ('Leibowitz Icin Bir Ilahi', 'Walter M Miller JR', 'tr'))
        self.assertEqual(info['chapters'], ['BÖLÜM 1: Issız çöl', 'BÖLÜM 2'])
        with zipfile.ZipFile(epub) as archive:
            self.assertEqual(archive.namelist()[0], 'mimetype')
            self.assertIn('OEBPS/images/kapak.jpg', archive.namelist())
        book = EpubBook(epub)
        self.assertEqual((book.language, [entry['title'] for entry in book.toc]), ('tr', ['BÖLÜM 1: Issız çöl', 'BÖLÜM 2']))
        self.assertIn('Taşı kaldırdı', book.section_html(0))
        project = prepare(epub, self.root / 'ceviri')
        sources = sorted((project / 'source').glob('*.md'))
        self.assertEqual(len(sources), 2)
        self.assertIn('Genç rahip yürüdü', sources[0].read_text(encoding='utf-8'))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = scanned_pdf(self.root / 'Kitap - Yazar.pdf', [(600, 850)] * 4)
        self.work = pdf_book.work_dir(self.pdf)
        pages = iter(['BÖLÜM 1\n\nGenç rahip yürüdü.', 'Taşı kaldırdı.\n\nBir yazı gördü.', 'BÖLÜM 2\n\nYaşlı adam güldü.',
                      'Sonra gitti.'])
        pdf_book.read_pages(self.pdf, self.work, lambda png, prompt: next(pages))

    def test_review_page_edits_and_saved_structure(self):
        summary = pdf_book.review(self.pdf, self.work, log=lambda *_: None)
        self.assertEqual(([c['title'] for c in summary['chapters']], summary['auto'], summary['pages']),
                         (['BÖLÜM 1', 'BÖLÜM 2'], True, 4))
        self.assertEqual(summary['chapters'][0]['first'], 'Genç rahip yürüdü.')
        view = pdf_book.page_view(self.pdf, self.work, 2)
        self.assertTrue(view['image'].startswith('data:image/jpeg;base64,'))
        self.assertEqual([p['text'] for p in view['paragraphs']], ['Taşı kaldırdı.', 'Bir yazı gördü.'])
        pdf_book.save_page(self.work, 2, 'Taşı kaldırdı ve baktı.\r\n\r\nBir yazı gördü.')
        self.assertTrue(pdf_book.page_view(self.pdf, self.work, 2)['edited'])
        self.assertEqual(pdf_book.ocr_text(self.work, 2), 'Taşı kaldırdı.\n\nBir yazı gördü.')   # OCR bozulmadi
        # Kullanici 2. sayfanin ikinci paragrafinda yeni bolum baslatir ve ilk bolumun adini degistirir.
        chapters = summary['chapters'] + [{'title': 'Yazı', 'page': 2, 'ordinal': 1, 'skip': 0, 'level': 0}]
        chapters[0] = dict(chapters[0], title='Çöl')
        pdf_book.save_book(self.work, {'title': 'Kitap', 'author': 'Yazar', 'language': 'tr', 'chapters': chapters})
        epub, info = pdf_book.build_epub(self.pdf, self.work, log=lambda *_: None)
        self.assertEqual(info['chapters'], ['Çöl', 'Yazı', 'BÖLÜM 2'])
        self.assertIn('Taşı kaldırdı ve baktı.', EpubBook(epub).section_html(0))
        self.assertFalse(pdf_book.review(self.pdf, self.work)['auto'])
        pdf_book.revert_page(self.work, 2)
        self.assertEqual(pdf_book.edited_pages(self.work), [])
        with self.assertRaises(ValueError):
            pdf_book.save_book(self.work, {'chapters': [{'title': ' ', 'page': 1}]})
        redetected = pdf_book.review(self.pdf, self.work, log=lambda *_: None, redetect=True)
        self.assertEqual(([c['title'] for c in redetected['chapters']], redetected['auto']), (['BÖLÜM 1', 'BÖLÜM 2'], True))


class BridgePdfTests(unittest.TestCase):
    def setUp(self):
        import bridge
        from unittest import mock
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for target in ('bridge.APP_DIR', 'book_core.APP_DIR', 'app_core.APP_DIR'):
            patcher = mock.patch(target, self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.events = []
        self.done = __import__('threading').Event()

        def emit(event, data):
            self.events.append((event, data))
            if event == 'pdf_done':
                self.done.set()
        self.bridge = bridge.Bridge(emit=emit)
        pages = iter(['BÖLÜM 1\n\nGenç rahip yürüdü.', 'Taşı kaldırdı ve bir yazı gördü.', 'BÖLÜM 2\n\nYaşlı adam güldü.'])

        def reader(cfg, log=print):
            def read(png, prompt):
                return next(pages, 'Son.')
            return read
        for target, value in (('library.vision_reader', reader), ('documents.ocr_engine', lambda cfg: 'model')):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_convert_to_reading_adds_book_to_shelf(self):
        pdf = scanned_pdf(self.root / 'Kitap - Yazar.pdf', [(600, 850)] * 3)
        info = self.bridge.pdf_info(str(pdf))
        self.assertEqual((info['pages'], info['title'], info['author'], info['read']), (3, 'Kitap', 'Yazar', 0))
        self.assertIn('error', self.bridge.pdf_info(str(self.root / 'yok.txt')))
        self.assertTrue(self.bridge.pdf_convert(str(pdf), 'Benim Kitabım', 'Yazar', 'reading')['started'])
        self.assertTrue(self.done.wait(20))
        done = [data for event, data in self.events if event == 'pdf_done'][0]
        self.assertNotIn('error', done)
        self.assertEqual((done['title'], done['chapters']), ('Benim Kitabım', ['BÖLÜM 1', 'BÖLÜM 2']))
        self.assertTrue(Path(done['epub']).is_file())
        self.assertEqual([book['title'] for book in self.bridge.shelf_list()], ['Benim Kitabım'])
        self.assertTrue(any(event == 'pdf_progress' for event, _data in self.events))
        self.assertEqual(self.bridge.pdf_info(str(pdf))['read'], 3)           # okunan sayfalar saklandi
        # Gozden gecirme: 2. bolumun adi duzeltilir, sayfa metni duzeltilir, kitap yeniden yazilir.
        summary = self.bridge.pdf_review(str(pdf))
        self.assertEqual([c['title'] for c in summary['chapters']], ['BÖLÜM 1', 'BÖLÜM 2'])
        chapters = [dict(summary['chapters'][0]), dict(summary['chapters'][1], title='İkinci')]
        saved = self.bridge.pdf_save_structure(str(pdf), {'title': 'Benim Kitabım', 'author': 'Yazar', 'language': 'tr',
                                                          'chapters': chapters})
        self.assertEqual(([c['title'] for c in saved['chapters']], saved['auto']), (['BÖLÜM 1', 'İkinci'], False))
        page = self.bridge.pdf_save_page(str(pdf), 2, 'Taşı kaldırdı, sonra baktı.')
        self.assertTrue(page['edited'])
        self.assertFalse(self.bridge.pdf_save_page(str(pdf), 2, page['ocr'])['edited'])   # OCR'in aynisi
        self.bridge.pdf_save_page(str(pdf), 2, 'Taşı kaldırdı, sonra baktı.')
        book_id = done['book_id']
        self.bridge.reader_open(book_id)                                       # okuyucu onbellege alir
        rebuilt = self.bridge.pdf_rebuild(str(pdf), 'reading')
        self.assertEqual((rebuilt['chapters'], rebuilt['book_id']), (['BÖLÜM 1', 'İkinci'], book_id))
        self.assertIn('sonra baktı', self.bridge.reader_section(book_id, 0)['html'])
        self.assertIn('error', self.bridge.pdf_page(str(pdf), 99))


if __name__ == '__main__':
    unittest.main()
