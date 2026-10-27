"""E-kitap donusturme (F153): FB2 ve MOBI'den EPUB."""
from __future__ import annotations

import base64
import re
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import ebook_convert
import epub_import

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


def make_mobi(path, text, encryption=0, compression=1, exth=None, images=(PNG,)):
    """En kucuk MOBI: rec0 (PalmDOC + MOBI + EXTH), tek metin kaydi, gorsel kayitlari."""
    body = text.encode('utf-8')
    exth = exth or {}
    exth_records = b''.join(struct.pack('>II', kind, 8 + len(value)) + value for kind, value in exth.items())
    exth_block = b'EXTH' + struct.pack('>II', 12 + len(exth_records), len(exth)) + exth_records
    header_length = 0xE8
    rec0 = bytearray(16 + header_length)
    struct.pack_into('>HHIHHH', rec0, 0, compression, 0, len(body), 1, 4096, encryption)
    rec0[16:20] = b'MOBI'
    struct.pack_into('>IIII', rec0, 20, header_length, 2, 65001, 1)
    struct.pack_into('>I', rec0, 36, 6)
    struct.pack_into('>I', rec0, 108, 2 if images else 0xFFFFFFFF)   # ilk gorsel kaydi
    struct.pack_into('>I', rec0, 128, 0x40 if exth else 0)
    struct.pack_into('>H', rec0, 16 + 0xE2, 0)
    rec0 += exth_block if exth else b''
    name = b'Synthetic Book'
    struct.pack_into('>II', rec0, 84, len(rec0), len(name))
    rec0 += name + b'\x00\x00'
    records = [bytes(rec0), body, *images]
    header = bytearray(78)
    header[:len(b'synthetic')] = b'synthetic'
    header[60:68] = b'BOOKMOBI'
    struct.pack_into('>H', header, 76, len(records))
    offset = 78 + 8 * len(records) + 2
    table = b''
    for index, record in enumerate(records):
        table += struct.pack('>II', offset, index)
        offset += len(record)
    Path(path).write_bytes(bytes(header) + table + b'\x00\x00' + b''.join(records))


FB2 = '''<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
 <description><title-info>
  <author><first-name>Anton</first-name><last-name>Chekhov</last-name></author>
  <book-title>Short Stories</book-title><lang>ru</lang>
  <coverpage><image l:href="#cover.png"/></coverpage>
 </title-info></description>
 <body>
  <title><p>Short Stories</p></title>
  <section><title><p>Part One</p></title>
   <section><title><p>The Bet</p></title><p>It was a dark <emphasis>autumn</emphasis> night.<a l:href="#n1" type="note">1</a></p>
    <poem><stanza><v>Line one</v><v>Line two</v></stanza></poem></section>
   <section><title><p>The Lady</p></title><p>She walked <strong>alone</strong>.</p><empty-line/><p>End.</p></section>
  </section>
 </body>
 <body name="notes"><section id="n1"><title><p>1</p></title><p>A footnote.</p></section></body>
 <binary id="cover.png" content-type="image/png">''' + base64.b64encode(PNG).decode() + '''</binary>
</FictionBook>'''


class DialogFilterTests(unittest.TestCase):
    def test_filter_is_valid_for_pywebview(self):
        # webview.util.parse_file_type ile ayni kalip
        pattern = r'^([\w ]+)\((\*(?:\.(?:\w+|\*))*(?:;\*(?:\.(?:\w+|\*))*)*)\)$'
        self.assertRegex(ebook_convert.DIALOG_FILTER, pattern)


class PalmDocTests(unittest.TestCase):
    def test_decompress(self):
        data = b'ab' + b'\x80\x10' + b'\xe1' + b'\x02\xff\xfe' + b'z'
        self.assertEqual(ebook_convert.palmdoc_decompress(data), b'ababa a\xff\xfez')

    def test_trailing_entries(self):
        record = b'hello' + b'\x83'  # bit 1: sonda 3 baytlik ek veri (deger 3, son bayt 0x83)
        self.assertEqual(ebook_convert._trailing_size(b'hel' + b'xx' + b'\x83', 0b10), 3)
        self.assertEqual(ebook_convert._trailing_size(record + b'\x01', 0b1), 2)


class MobiTests(unittest.TestCase):
    TEXT = ('<html><body><h1>Chapter One</h1><p>Hello <b>world</b> &amp; friends.</p><img recindex="00001"/>'
            '<mbp:pagebreak/><h1>Chapter Two</h1><p>Goodbye.</p></body></html>')

    def test_mobi_to_epub(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'book.mobi'
            make_mobi(source, self.TEXT, exth={100: b'Jane Doe', 503: b'Real Title', 524: b'de-DE',
                                               201: struct.pack('>I', 0)})
            target = ebook_convert.ensure_epub(source, log=lambda _m: None, folder=Path(temp) / 'out')
            with zipfile.ZipFile(target) as archive:
                opf = archive.read('OEBPS/content.opf').decode('utf-8')
                nav = archive.read('OEBPS/nav.xhtml').decode('utf-8')
                pages = [archive.read(n).decode('utf-8') for n in sorted(archive.namelist()) if n.startswith('OEBPS/text/')]
                self.assertIn('OEBPS/images/0001.png', archive.namelist())
            self.assertIn('<dc:title>Real Title</dc:title>', opf)
            self.assertIn('<dc:creator>Jane Doe</dc:creator>', opf)
            self.assertIn('<dc:language>de</dc:language>', opf)
            self.assertIn('properties="cover-image"', opf)
            self.assertEqual(re.findall(r'<a href="[^"]+">([^<]+)</a>', nav), ['Chapter One', 'Chapter Two'])
            self.assertIn('<strong>world</strong> &amp; friends.', pages[1])
            # Ikinci acilista yeniden uretilmez; kaynak dosya degismez.
            self.assertEqual(ebook_convert.ensure_epub(source, log=lambda _m: None, folder=Path(temp) / 'out'), target)
            book = epub_import.prepare(target, Path(temp) / 'work')
            self.assertEqual(len(list((book / 'source').glob('*.md'))), 3)   # kapak + iki bolum

    def test_palmdoc_compressed_text(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'book.azw3'
            make_mobi(source, '<p>Plain text body.</p>', compression=2, images=())
            book = ebook_convert.MobiBook(source.read_bytes())
            self.assertEqual(book.text(), '<p>Plain text body.</p>')

    def test_drm_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'locked.azw'
            make_mobi(source, '<p>x</p>', encryption=2)
            with self.assertRaisesRegex(ValueError, 'DRM'):
                ebook_convert.ensure_epub(source, log=lambda _m: None, folder=Path(temp) / 'out')

    def test_not_a_mobi(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'fake.mobi'
            source.write_bytes(b'not a mobi file' * 10)
            with mock.patch.object(ebook_convert, 'calibre_converter', return_value=None), \
                    self.assertRaisesRegex(ValueError, 'MOBI'):
                ebook_convert.ensure_epub(source, log=lambda _m: None, folder=Path(temp) / 'out')

    def test_calibre_is_preferred_when_installed(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'book.mobi'
            make_mobi(source, self.TEXT)

            def fake_run(command, **_kwargs):
                Path(command[2]).write_bytes(b'calibre-epub')
                return mock.Mock(returncode=0, stdout='', stderr='')

            with mock.patch.object(ebook_convert, 'calibre_converter', return_value='ebook-convert'), \
                    mock.patch.object(ebook_convert.subprocess, 'run', side_effect=fake_run) as run:
                target = ebook_convert.ensure_epub(source, log=lambda _m: None, folder=Path(temp) / 'out')
            self.assertEqual(run.call_args[0][0][:2], ['ebook-convert', str(source)])
            self.assertEqual(target.read_bytes(), b'calibre-epub')


class Fb2Tests(unittest.TestCase):
    def test_fb2_to_epub(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'stories.fb2'
            source.write_text(FB2, encoding='utf-8')
            target = ebook_convert.ensure_epub(source, log=lambda _m: None, folder=Path(temp) / 'out')
            with zipfile.ZipFile(target) as archive:
                opf = archive.read('OEBPS/content.opf').decode('utf-8')
                nav = archive.read('OEBPS/nav.xhtml').decode('utf-8')
                names = archive.namelist()
                pages = {n: archive.read(n).decode('utf-8') for n in names if n.startswith('OEBPS/text/')}
            self.assertIn('<dc:title>Short Stories</dc:title>', opf)
            self.assertIn('<dc:creator>Anton Chekhov</dc:creator>', opf)
            self.assertIn('<dc:language>ru</dc:language>', opf)
            self.assertIn('OEBPS/images/0001.png', names)
            self.assertEqual(re.findall(r'<a href="[^"]+">([^<]+)</a>', nav), ['Short Stories', 'The Bet', 'The Lady', 'Notes'])
            bet = next(text for text in pages.values() if 'The Bet' in text and 'autumn' in text)
            self.assertIn('<h1>Part One</h1>', bet)
            self.assertIn('<em>autumn</em>', bet)
            self.assertIn('href="../text/notes.xhtml#n1"', bet)
            self.assertIn('Line one<br/>Line two', bet)
            self.assertIn('A footnote.', pages['OEBPS/text/notes.xhtml'])

    def test_zipped_fb2(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'stories.fb2.zip'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('stories.fb2', FB2)
            self.assertTrue(ebook_convert.supported(source))
            target = ebook_convert.ensure_epub(source, log=lambda _m: None, folder=Path(temp) / 'out')
            self.assertTrue(target.name.startswith('stories-'))
            book = epub_import.prepare(target, Path(temp) / 'work')
            self.assertGreaterEqual(len(list((book / 'source').glob('*.md'))), 3)

    def test_unsupported(self):
        self.assertFalse(ebook_convert.supported('book.kfx'))
        with self.assertRaises(ValueError):
            ebook_convert.ensure_epub(Path('book.kfx'))


if __name__ == '__main__':
    unittest.main()
