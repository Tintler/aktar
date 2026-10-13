"""Transkript disa aktarma (TXT/SRT/Markdown) testleri."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import qa  # noqa: E402
import subtitle  # noqa: E402
import transcript_export  # noqa: E402
from app_core import save_json  # noqa: E402


class ExportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.work = self.root / 'work'
        self.video = self.root / 'Ders 1.mkv'
        self.video.write_bytes(b'x')
        source = {'kind': 'subtitle', 'stream': 2, 'language': 'tr', 'title': ''}
        segments = [{'start': 1.5, 'end': 4.0, 'text': 'Merhaba, başlıyoruz.'},
                    {'start': 65.25, 'end': 70.0, 'text': 'Regresyon anlatılıyor.'}]
        data = qa.build_data(self.video, segments, source, {'duration': 80.0, 'chapters': []})
        data['overview'] = {'summary': 'Giriş dersi.', 'topics': [], 'questions': []}
        save_json(qa.cache_path(self.video, qa.source_key(source), self.work), data)
        self.session = data

    def test_formats(self):
        srt = transcript_export.render(self.session, 'srt')
        self.assertIn('1\n00:00:01,500 --> 00:00:04,000\nMerhaba, başlıyoruz.\n', srt)
        self.assertIn('2\n00:01:05,250 --> 00:01:10,000\n', srt)
        kind, cues = subtitle.parse_by_extension(srt, '.srt')
        self.assertEqual(len(subtitle.cues_of(kind, cues)), 2, 'SRT geri okunabilmeli')
        txt = transcript_export.render(self.session, 'txt')
        self.assertTrue(txt.startswith('Ders 1\n\n[0:01] Merhaba'))
        self.assertIn('[1:05] Regresyon', txt)
        md = transcript_export.render(self.session, 'md')
        self.assertIn('# Ders 1\n\n> Giriş dersi.\n\n## Transkript', md)
        self.assertIn('**[1:05]** Regresyon anlatılıyor.', md)

    def test_export_many_never_overwrites_and_reports_missing(self):
        out = self.root / 'out'
        (out).mkdir()
        (out / 'Ders 1.txt').write_text('eski', encoding='utf-8')
        other = self.root / 'Ders 2.mkv'
        other.write_bytes(b'x')
        written, missing = transcript_export.export_many([self.video, other], out, 'txt',
                                                         self.work)
        self.assertEqual([path.name for path in written], ['Ders 1 (2).txt'])
        self.assertEqual(missing, ['Ders 2.mkv'])
        self.assertEqual((out / 'Ders 1.txt').read_text(encoding='utf-8'), 'eski')

    def test_collection_markdown(self):
        text = transcript_export.render_collection(
            'ML', [self.video], {'summary': 'Seri özeti.', 'topics': ['regresyon']}, self.work)
        self.assertTrue(text.startswith('# ML\n\nSeri özeti.\n'))
        self.assertIn('**Konular:** regresyon', text)
        self.assertIn('## Ders 1\n\n> Giriş dersi.', text)
        with self.assertRaises(ValueError):
            transcript_export.render_collection('ML', [self.root / 'yok.mkv'], None, self.work)


if __name__ == '__main__':
    unittest.main()
