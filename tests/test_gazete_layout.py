"""Gazete (F227): yerlesim modeli bolgelerinden bloklar (gazete_layout)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))

import app_core  # noqa: E402
import gazete  # noqa: E402
import gazete_layout  # noqa: E402
from test_gazete import column, word  # noqa: E402
from test_gazete_model import TSV_HEAD, fake_read, tsv  # noqa: E402

try:
    import numpy as np
except ImportError:
    np = None


def line(box, text, size=None):
    return {'box': box, 'size': size or box[3] - box[1], 'text': text}


def region(label, box, score=0.9, order=0):
    return {'label': label, 'box': box, 'score': score, 'order': order}


@unittest.skipIf(np is None, 'numpy yok')
class DecodeTests(unittest.TestCase):
    def test_boxes_labels_and_threshold(self):
        logits = np.full((3, 25), -10.0, dtype=np.float32)
        logits[0, 6] = 5          # doc_title
        logits[1, 22] = 3         # text
        logits[2, 14] = -1        # image, esigin altinda
        boxes = np.array([[0.5, 0.1, 0.8, 0.1], [0.25, 0.5, 0.3, 0.6], [0.5, 0.5, 0.2, 0.2]], dtype=np.float32)
        found = gazete_layout.decode(logits, boxes, np.zeros((3, 3), dtype=np.float32), 1000, 2000)
        self.assertEqual([item['label'] for item in found], ['doc_title', 'text'])
        self.assertEqual(found[0]['box'], [100, 100, 900, 300])
        self.assertEqual(found[1]['box'], [100, 400, 400, 1600])
        self.assertEqual([item['order'] for item in found], [0, 1])


class BlockTests(unittest.TestCase):
    def test_title_size_follows_the_big_line_not_side_column(self):
        lines = [line([0, 0, 900, 150], 'Meme kanserinde'), line([0, 160, 900, 300], 'BİTKİSEL TEHLİKE')]
        lines += [line([920, y, 1100, y + 18], 'yandaki sütun satırı') for y in range(0, 300, 25)]
        lines += [line([0, 400 + 25 * i, 400, 418 + 25 * i], 'gövde yazısı satırı burada') for i in range(10)]
        found = [region('doc_title', [0, 0, 1100, 300]), region('text', [0, 400, 400, 650], order=1)]
        blocks = gazete_layout.blocks_of(found, lines, 18)
        self.assertEqual([b['head'] for b in blocks], [True, False])
        self.assertGreater(blocks[0]['size'], 100)

    def test_half_scan_size_used_when_full_scan_splits_headline(self):
        lines = [line([0, 0, 200, 20], 'parça'), line([0, 30, 200, 50], 'parça')]
        low = [line([0, 0, 900, 140], 'DEV BAŞLIK')]
        blocks = gazete_layout.blocks_of([region('doc_title', [0, 0, 900, 150])], lines, 18, low)
        self.assertTrue(blocks[0]['head'])

    def test_subheads_listings_images_and_duplicates(self):
        lines = [line([0, 0, 300, 20], 'EN SKORER SEZONA ULAŞTI'),
                 line([0, 100, 300, 118], '13.00 A Spor ........ Kars-Antalyaspor'),
                 line([0, 120, 300, 138], '18.00 A Spor ........ Sakaryaspor-Yıldırım'),
                 line([0, 200, 300, 218], 'Maçtan sonra 20.30\'da açıklama yaptı ve'),
                 line([0, 220, 300, 238], 'taraftarlara teşekkür etti, sonra ayrıldı.')]
        found = [region('paragraph_title', [0, 0, 300, 22]), region('text', [0, 95, 300, 140]),
                 region('text', [0, 195, 300, 240], 0.9), region('text', [0, 198, 300, 238], 0.5),
                 region('image', [400, 0, 900, 500]), region('header', [0, 900, 900, 950])]
        blocks = gazete_layout.blocks_of(found, lines, 18)
        self.assertEqual([(b['label'], b['head']) for b in blocks], [('paragraph_title', False), ('text', False)])
        self.assertIn('20.30', blocks[1]['text'])

    def test_listing_text(self):
        self.assertTrue(gazete_layout.listing_text('20.30...S Sport +.....Milan-Bologna 22.45...S Sport +.....Genoa'))
        self.assertFalse(gazete_layout.listing_text(
            'Maç saat 20.30\'da başladı ve 22.15\'te bitti. Teknik direktör maçtan sonra yaptığı açıklamada '
            'oyuncularına teşekkür etti, taraftarların desteğinin çok önemli olduğunu söyledi.'))

    def test_photo_heads_only_where_no_block(self):
        blocks = [{'box': [0, 0, 300, 300], 'head': False, 'size': 18}]
        low = [line([400, 0, 900, 120], 'DİL YARASI'), line([0, 100, 300, 200], 'GÖVDE ÜSTÜ'),
               line([400, 300, 900, 330], 'küçük yazı')]
        gazete_layout.add_photo_heads(blocks, low, 18, gazete.HEAD_RATIO)
        self.assertEqual([b['text'] for b in blocks[1:]], ['DİL YARASI'])
        self.assertTrue(blocks[1]['head'] and blocks[1]['low'])


class ProposeLayoutTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.temp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(app_core, 'APP_DIR', Path(self.temp.name))
        self.patch.start()
        folder = Path(self.temp.name) / 'kaynak'
        folder.mkdir()
        Image.new('RGB', (1000, 1400), 'white').save(folder / '117090jpg-a.jpg')
        self.name = gazete.create(folder, 'sayi')
        rows = [word('BÜYÜK', 0, 0, 300, 60, block=1), word('BAŞLIK', 320, 0, 300, 60, block=1)]
        rows += column(0, 100, 8, block=2) + column(320, 100, 8, block=3)
        self.full = tsv(rows)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_blocks_come_from_layout_regions_and_are_cached(self):
        calls = []

        def layout(image):
            calls.append(image.size)
            return [region('doc_title', [0, 0, 620, 60]), region('text', [0, 95, 300, 400], order=1),
                    region('text', [320, 95, 620, 400], order=2), region('table', [0, 500, 620, 900], order=3)]
        answer = json.dumps({'blocks': {'B0': 'H0', 'B1': 'H0'}, 'headlines': {'H0': {'text': 'Büyük Başlık'}}})
        prompts = []

        def ask(prompt, png=None):
            prompts.append(prompt)
            return answer
        read = fake_read
        for _ in range(2):
            found = gazete.propose(self.name, 1, lambda png: self.full, lambda png: TSV_HEAD + '\n', print,
                                   read, 'glm-ocr', ask, layout)
        self.assertEqual(calls, [(1000, 1400)])             # ikinci kez onbellekten
        self.assertTrue((gazete.issue_dir(self.name) / 'ocr' / '0001.layout.json').is_file())
        self.assertEqual([item['title'] for item in found], ['Büyük Başlık'])
        self.assertEqual(len(found[0]['boxes']), 2)
        self.assertIn('B1 (320,68,620,286)', prompts[0])


if __name__ == '__main__':
    unittest.main()
