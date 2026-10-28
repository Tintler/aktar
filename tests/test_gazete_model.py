"""Gazete (F226): OCR modeliyle okuma ve dil modeliyle makale baglama (gazete_model) ile yarim olcek baslik taramasi."""
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
import gazete_model  # noqa: E402
from test_gazete import column, word  # noqa: E402

TSV_HEAD = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'


def tsv(rows):
    lines = [TSV_HEAD]
    for row in rows:
        lines.append('\t'.join(str(v) for v in (row['level'], 1, row['block_num'], row['par_num'], row['line_num'], 1,
                                                round(row['left']), round(row['top']), row['width'], row['height'],
                                                row['conf'], row['text'])))
    return '\n'.join(lines) + '\n'


def block(box, text, head=False, size=20):
    return {'box': list(box), 'text': text, 'head': head, 'size': size, 'lines': []}


class HeadScanTests(unittest.TestCase):
    def test_giant_headline_splits_from_body_column_on_same_line(self):
        rows = [word('Meme', 0, 0, 300, 140), word('kanserinde', 320, 0, 600, 140), word('Eralp', 940, 10, 60, 18),
                word('günümüzde', 1010, 10, 120, 18)]
        self.assertEqual([line['text'] for line in gazete.lines_of(rows)], ['Meme kanserinde', 'Eralp günümüzde'])

    def test_preferred_low_heads_replace_merged_head_and_skip_body(self):
        blocks = [block([0, 0, 1500, 300], 'Meme kanserinde Eralp de', head=True, size=80),
                  block([0, 400, 300, 600], 'gövde satırları')]
        lines = [{'box': [0, 0, 1200, 160], 'size': 140, 'text': 'Meme kanserinde'},
                 {'box': [0, 150, 1400, 300], 'size': 135, 'text': 'BİTKİSEL TEHLİKE'},     # ustteki ile hafif ortusur
                 {'box': [0, 420, 300, 560], 'size': 50, 'text': 'gövdeyi büyük sanan satır'},
                 {'box': [0, 700, 300, 740], 'size': 32, 'text': 'KORKMAYIN'}]               # 1.7 x 18 ustu
        gazete.add_low_heads(blocks, lines, 18, prefer=True)
        self.assertEqual([b['text'] for b in blocks if b['head']], ['Meme kanserinde', 'BİTKİSEL TEHLİKE', 'KORKMAYIN'])

    def test_without_prefer_existing_heads_win(self):
        blocks = [block([0, 0, 300, 60], 'Var', head=True, size=60)]
        gazete.add_low_heads(blocks, [{'box': [10, 10, 290, 50], 'size': 60, 'text': 'Var olan'}], 20)
        self.assertEqual([b['text'] for b in blocks], ['Var'])


class ParseTests(unittest.TestCase):
    def test_parse_json_ignores_fence_and_extra_brace(self):
        self.assertEqual(gazete_model.parse_json('```json\n{"blocks": {"B0": "H1"}}\n}\n```'), {'blocks': {'B0': 'H1'}})
        self.assertEqual(gazete_model.parse_json('{"a": {"b": {"c": 1}}\n```'), {'a': {'b': {'c': 1}}})
        with self.assertRaises(ValueError):
            gazete_model.parse_json('JSON yok')

    def test_assignment_keeps_candidates_and_falls_back_to_nearest_kept(self):
        heads = [{'box': [0, 0, 10, 10], 'text': f'H{i}'} for i in range(4)]
        bodies = [{}, {}, {}]
        options = [[1, 0], [2, 1], [1]]
        answer = json.dumps({'blocks': {'B0': 'H1', 'B1': 'H3', 'B2': 'none'},
                             'headlines': {'H0': {'text': 'Düzeltilmiş', 'skip': False}, 'H1': {'join': 'H0'},
                                           'H2': {'text': 'Sağlık', 'skip': True}}})
        owner, titles, skip, join = gazete_model.parse_assignment(answer, heads, bodies, options)
        self.assertEqual(owner, [1, 1, None])      # B1: H3 aday degil -> H2 atlandi -> H1
        self.assertEqual(titles, {0: 'Düzeltilmiş', 2: 'Sağlık'})
        self.assertEqual(skip, {2})
        self.assertEqual(join, {1: 0})

    def test_clean_strips_markdown(self):
        self.assertEqual(gazete_model.clean('```\n## Başlık\n**kalın** metin\n```'), 'Başlık\nkalın metin')


class GroupTests(unittest.TestCase):
    def test_heads_merge_stacked_lines_but_not_neighbours(self):
        blocks = [block([0, 0, 400, 44], 'KADINLARDA', True, 44), block([0, 50, 460, 120], 'EN SIK GÖRÜLEN', True, 70),
                  block([0, 122, 340, 166], 'KANSER TÜRÜ', True, 44),
                  block([600, 0, 1000, 60], 'Başka haber', True, 60), block([0, 400, 300, 600], 'gövde')]
        heads = gazete_model.heads_of(blocks)
        self.assertEqual([h['text'] for h in heads], ['KADINLARDA EN SIK GÖRÜLEN KANSER TÜRÜ', 'Başka haber'])

    def test_column_boxes_merge_unless_other_block_between(self):
        members = [[0, 100, 300, 200], [0, 220, 300, 400], [320, 100, 620, 300]]
        self.assertEqual(gazete_model.column_boxes(members, [], 20), [[0, 100, 300, 400], [320, 100, 620, 300]])
        boxes = gazete_model.column_boxes(members, [[0, 205, 300, 215]], 20)
        self.assertEqual(boxes, [[0, 100, 300, 200], [0, 220, 300, 400], [320, 100, 620, 300]])

    def test_candidates_prefer_head_above_and_skip_far_ones(self):
        heads = [{'box': [0, 0, 600, 60]}, {'box': [400, 0, 1000, 60]}, {'box': [0, 900, 600, 960]}, {'box': [700, 0, 1000, 60]}]
        found = gazete_model.candidates(block([0, 100, 300, 400], 'x'), heads, 20, 1000)
        self.assertEqual(found, [0, 1])

    def test_articles_join_kicker_and_drop_captions(self):
        blocks = [block([0, 0, 600, 30], 'TÜRK TIBBİ ONKOLOJİ DERNEĞİ UYARDI', True, 30),
                  block([0, 60, 600, 160], 'Meme kanserinde BİTKİSEL TEHLİKE', True, 100),
                  block([0, 200, 280, 600], 'TÜRK Tıbbi Onkoloji Derneği üyesi hekimlerin katılımıyla toplantı yapıldı.'),
                  block([300, 200, 600, 600], 'devamında uzmanlar bitkisel ürünlerin tehlikeli olduğunu söyledi.'),
                  block([0, 620, 280, 640], 'Prof. Dr. Ad Soyadı fotoğraf altı yazısı')]
        prompts = []

        def ask(prompt, png=None):
            prompts.append((prompt, png))
            return json.dumps({'blocks': {'B0': 'H1', 'B1': 'H1', 'B2': 'none'},
                               'headlines': {'H0': {'join': 'H1'},
                                             'H1': {'text': 'Meme kanserinde BİTKİSEL TEHLİKE', 'skip': False}}})
        found = gazete_model.articles(blocks, 20, (1000, 1000), ask)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['title'], 'TÜRK TIBBİ ONKOLOJİ DERNEĞİ UYARDI: Meme kanserinde BİTKİSEL TEHLİKE')
        self.assertEqual(found[0]['head'], [0, 0, 600, 160])
        self.assertEqual(found[0]['boxes'], [[0, 200, 280, 600], [300, 200, 600, 600]])
        self.assertTrue(found[0]['titled'])
        self.assertIn('B2 (0,620,280,640)', prompts[0][0])
        self.assertIsNone(prompts[0][1])


class DeckTests(unittest.TestCase):
    def test_deck_below_headline_joins_its_article(self):
        blocks = [block([0, 0, 1000, 150], 'Başkanın babası gözaltına alındı', True, 130),
                  block([0, 160, 950, 200], 'Başkan arama yapıldı derken babası emniyete götürüldü', True, 35),
                  block([0, 220, 300, 600], 'BAKIRKÖY Cumhuriyet Başsavcılığı tarafından soruşturma başlatıldı.'),
                  block([320, 220, 620, 600], 'Ayşegül Ovalıoğlu babasının gözaltına alındığını söyledi ve tepki gösterdi.')]

        def ask(prompt, png=None):
            return json.dumps({'blocks': {'B0': 'H1', 'B1': 'H1'},
                               'headlines': {'H0': {'text': 'Başkanın babası gözaltına alındı'},
                                             'H1': {'text': 'Başkan arama yapıldı derken'}}})
        found = gazete_model.articles(blocks, 20, (1000, 1000), ask)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['title'], 'Başkanın babası gözaltına alındı')
        self.assertEqual(found[0]['boxes'][0], [0, 160, 950, 200])      # spot ilk okunur
        self.assertEqual(len(found[0]['boxes']), 3)


class JoinTests(unittest.TestCase):
    def test_far_join_is_ignored_and_broken_json_asked_again(self):
        blocks = [block([0, 0, 600, 100], 'ALNI AK BAŞI DİK', True, 90),
                  block([0, 900, 300, 940], 'Muslera yere yığıldı', True, 40),
                  block([0, 120, 300, 500], 'Okan Buruk derbilerdeki başarılı performansına yenisini ekledi.'),
                  block([0, 950, 300, 1200], 'Muslera tedavisinin ardından sahadan çıktı ve hastaneye kaldırıldı.')]
        answers = ['{"blocks": {"B0": "H0" "B1": "H1"}}',
                   json.dumps({'blocks': {'B0': 'H0', 'B1': 'H1'}, 'headlines': {'H1': {'join': 'H0'}}})]
        messages = []
        found = gazete_model.articles(blocks, 20, (1000, 2000), lambda prompt, png=None: answers.pop(0),
                                      log=messages.append)
        self.assertEqual(sorted(item['title'] for item in found), ['ALNI AK BAŞI DİK', 'Muslera yere yığıldı'])
        self.assertTrue(any('yeniden' in message for message in messages))


class ProposeTests(unittest.TestCase):
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

    def run_propose(self, answer, log):
        reads = []

        def read(png):
            reads.append(png)
            return 'Modelin okuduğu gövde metni, yeterince uzun bir paragraf olarak burada sürüyor ve bitiyor.'
        found = gazete.propose(self.name, 1, lambda png: self.full, lambda png: TSV_HEAD + '\n', log,
                               read, 'glm-ocr', lambda prompt, png=None: answer)
        return found, reads

    def test_model_reading_is_cached_and_used(self):
        answer = json.dumps({'blocks': {'B0': 'H0', 'B1': 'H0'}, 'headlines': {'H0': {'text': 'Büyük Başlık'}}})
        found, reads = self.run_propose(answer, print)
        self.assertEqual([item['title'] for item in found], ['Büyük Başlık'])
        self.assertEqual(len(reads), 3)                       # baslik + iki sutun
        self.assertTrue((gazete.issue_dir(self.name) / 'ocr' / '0001.glm-ocr.json').is_file())
        _again, reads = self.run_propose(answer, print)
        self.assertEqual(reads, [])                          # onbellekten

    def test_unusable_answer_falls_back_to_rules(self):
        messages = []
        found, _reads = self.run_propose('anlamadım', messages.append)
        self.assertEqual(len(found), 1)
        self.assertNotIn('titled', found[0])
        self.assertTrue(any('kurallarla' in message for message in messages))


if __name__ == '__main__':
    unittest.main()
