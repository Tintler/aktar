"""Gazete (F225): sayi kaydi, makale onerisi, OCR metni temizleme, eslestirme ve telefon sunucusu."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import app_core  # noqa: E402
import gazete  # noqa: E402
import gazete_server  # noqa: E402

try:
    import cv2  # noqa: F401
    HAVE_CV = True
except ImportError:
    HAVE_CV = False


def word(text, left, top, width, height, block=1, par=1, line=1, conf=90.0):
    return {'level': '5', 'block_num': str(block), 'par_num': str(par), 'line_num': str(line), 'text': text,
            'left': left, 'top': top, 'width': width, 'height': height, 'conf': conf}


def column(x, y, lines, block, size=20, text='satır metni burada devam ediyor'):
    """Bir govde sutunu: alt alta `lines` satir."""
    return [word(text, x, y + index * size * 1.4, 280, size, block=block, line=index + 1) for index in range(lines)]


class TempApp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(app_core, 'APP_DIR', Path(self.temp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()


class TextTests(unittest.TestCase):
    def test_page_order_is_numeric(self):
        names = ['1170910jpg-a.jpg', '117090jpg-b.jpg', '117099jpg-c.jpg', '117091jpg-d.jpg']
        self.assertEqual([n[:7] for n in sorted(names, key=gazete.page_number)],
                         ['117090j', '117091j', '117099j', '1170910'])

    def test_tidy_joins_hyphenation_and_lines(self):
        text = 'TÜİK, eylül ayı işgücü\nistatistiklerini açıkladı. İş-\nsizlik oranı yüz-\nde 8.4\'e çıktı.\n\n| Yeni paragraf.'
        self.assertEqual(gazete.tidy(text),
                         "TÜİK, eylül ayı işgücü istatistiklerini açıkladı. İşsizlik oranı yüzde 8.4'e çıktı.\n\n"
                         'Yeni paragraf.')

    def test_tidy_keeps_hyphen_before_capital_and_merges_unfinished_paragraph(self):
        self.assertEqual(gazete.tidy('Ankara-\nİstanbul hattı\n\nyarım kalan cümle sürüyor.'),
                         'Ankara-İstanbul hattı yarım kalan cümle sürüyor.')

    def test_tidy_drops_debris(self):
        self.assertEqual(gazete.tidy('ğ |\n\nGerçek metin.'), 'Gerçek metin.')

    def test_sentences_and_paragraph_breaks(self):
        parts, breaks = gazete.sentences('Birinci cümle. İkinci cümle!\n\n“Alıntı bitti.” Son 3 madde.')
        self.assertEqual(parts, ['Birinci cümle.', 'İkinci cümle!', '“Alıntı bitti.”', 'Son 3 madde.'])
        self.assertEqual(breaks, [1, 3])

    def test_spoken_prefers_edited_text(self):
        article = {'title': 'Başlık', 'text': 'OCR metni.', 'edited': 'Düzeltilmiş metin.'}
        self.assertEqual(gazete.spoken(article), 'Başlık.\n\nDüzeltilmiş metin.')
        self.assertEqual(gazete.spoken({'title': '', 'text': 'Yalnız metin.'}), 'Yalnız metin.')

    def test_audio_key_follows_text_and_voice(self):
        article = {'id': 'm1', 'title': 'A', 'text': 'B.'}
        key = gazete.audio_key(article, 'ema-lightning/default')
        self.assertNotEqual(key, gazete.audio_key(dict(article, edited='C.'), 'ema-lightning/default'))
        self.assertNotEqual(key, gazete.audio_key(article, 'voxcpm/default'))


class LayoutTests(unittest.TestCase):
    def test_lines_split_wide_gaps_and_drop_low_confidence(self):
        rows = [word('sol', 0, 0, 60, 20), word('sütun', 70, 0, 80, 20), word('sağ', 400, 0, 60, 20),
                word('kelime', 470, 0, 90, 20), word('gürültü', 600, 0, 90, 20, conf=10)]
        lines = gazete.lines_of(rows)
        self.assertEqual([line['text'] for line in lines], ['sol sütun', 'sağ kelime'])

    def test_headline_owns_columns_below_and_union_box(self):
        rows = [word('BÜYÜK', 0, 0, 300, 60, block=1), word('BAŞLIK', 320, 0, 300, 60, block=1)]
        rows += column(0, 100, 8, block=2) + column(320, 100, 8, block=3)
        lines = gazete.lines_of(rows)
        body = gazete.body_size(lines)
        blocks = gazete.blocks_of(lines, body)
        self.assertEqual(sum(b['head'] for b in blocks), 1)
        found = gazete.articles_of(blocks, body)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['title'], 'BÜYÜK BAŞLIK')
        self.assertEqual(len(found[0]['boxes']), 1)            # iki sutun tek cercevede
        self.assertEqual(found[0]['boxes'][0][0], 0)
        self.assertEqual(found[0]['boxes'][0][2], 600)

    def test_separator_stops_column_from_joining_headline(self):
        rows = [word('BAŞLIK', 0, 0, 300, 60, block=1)] + column(0, 100, 5, block=2) + column(0, 400, 5, block=3)
        lines = gazete.lines_of(rows)
        body = gazete.body_size(lines)
        blocks = gazete.blocks_of(lines, body)
        self.assertEqual(len(blocks), 3)
        found = gazete.articles_of(blocks, body, seps=[(380.0, 0, 300)])
        self.assertEqual(len(found[0]['boxes']), 1)
        self.assertLess(found[0]['boxes'][0][3], 380)

    def test_side_by_side_headline_parts_merge(self):
        rows = [word("'Derhal", 0, 0, 200, 50, block=1), word('istifa', 210, 0, 150, 50, block=1),
                word('etmeniz', 420, 0, 200, 50, block=2), word("lazım'", 630, 0, 150, 50, block=2)]
        rows += column(0, 80, 6, block=3)
        lines = gazete.lines_of(rows)
        body = gazete.body_size(lines)
        found = gazete.articles_of(gazete.blocks_of(lines, body), body)
        self.assertEqual(len(found), 1)
        self.assertIn('lazım', found[0]['title'])

    def test_low_resolution_heads_fill_missing_headlines(self):
        blocks = [{'box': [0, 0, 300, 60], 'size': 60, 'head': True, 'lines': [], 'text': 'Var'}]
        lines = [{'box': [10, 10, 290, 50], 'size': 60, 'text': 'Var olan'},
                 {'box': [0, 500, 400, 580], 'size': 80, 'text': 'Genç işsizler'},
                 {'box': [0, 700, 60, 720], 'size': 20, 'text': 'küçük'}]
        gazete.add_low_heads(blocks, lines, 20)
        self.assertEqual([b['text'] for b in blocks if b['head']], ['Var', 'Genç işsizler'])


class ArticleTests(unittest.TestCase):
    def test_clean_box_orders_and_clamps(self):
        page = {'width': 1000, 'height': 2000}
        self.assertEqual(gazete.clean_box([900, 50, -20, 10.6], page), [0, 11, 900, 50])
        with self.assertRaises(ValueError):
            gazete.clean_box([10, 10, 12, 500], page)

    def test_article_at_inside_nearest_and_none(self):
        data = {'articles': [{'id': 'a', 'page': 1, 'head': [0, 0, 100, 50], 'boxes': [[0, 60, 100, 300]]},
                             {'id': 'b', 'page': 1, 'head': None, 'boxes': [[200, 0, 400, 300]]},
                             {'id': 'c', 'page': 2, 'head': None, 'boxes': [[0, 0, 400, 300]]}]}
        self.assertEqual(gazete.article_at(data, 1, 50, 100)['id'], 'a')
        self.assertEqual(gazete.article_at(data, 1, 150, 100, reach=60)['id'], 'a')   # 50 px uzakta
        self.assertEqual(gazete.article_at(data, 1, 190, 100, reach=60)['id'], 'b')
        self.assertIsNone(gazete.article_at(data, 1, 150, 900))
        self.assertEqual(gazete.article_at(data, 2, 10, 10)['id'], 'c')


class IssueTests(TempApp):
    def make_pages(self):
        from PIL import Image
        folder = Path(self.temp.name) / 'kaynak'
        folder.mkdir()
        for number, size in ((10, (300, 500)), (2, (300, 500)), (1, (5000, 8000))):
            Image.new('RGB', size, 'white').save(folder / f'11709{number}jpg-x.jpg')
        (folder / 'not.txt').write_text('x', encoding='utf-8')
        return folder

    def test_create_orders_pages_and_limits_size(self):
        name = gazete.create(self.make_pages(), '2026-10-28', 'Sözcü')
        data = gazete.load(name)
        self.assertEqual([p['page'] for p in data['pages']], [1, 2, 3])
        self.assertEqual(max(data['pages'][0]['width'], data['pages'][0]['height']), gazete.MAX_LONG_SIDE)
        self.assertEqual(data['pages'][1]['width'], 300)
        self.assertTrue(gazete.page_path(name, 3).is_file())
        self.assertEqual(gazete.list_issues()[0]['title'], 'Sözcü')

    def test_recreate_keeps_articles(self):
        folder = self.make_pages()
        name = gazete.create(folder, 'sayi')
        data = gazete.load(name)
        data['articles'].append({'id': 'm1', 'page': 1, 'head': None, 'boxes': [[0, 0, 50, 50]], 'title': 'X'})
        gazete.save(name, data)
        gazete.create(folder, 'sayi')
        self.assertEqual(len(gazete.load(name)['articles']), 1)

    def test_bad_source_and_names(self):
        with self.assertRaises(ValueError):
            gazete.source_pages(Path(self.temp.name))      # goruntu yok
        self.assertEqual(gazete.slug('../../x y'), 'x-y')
        with self.assertRaises(ValueError):
            gazete.load('yok')

    def test_prune_audio_keeps_used_files(self):
        name = gazete.create(self.make_pages(), 'ses')
        folder = gazete.issue_dir(name) / 'ses'
        folder.mkdir()
        (folder / 'm1-aaa.mp3').write_bytes(b'1')
        (folder / 'm1-old.mp3').write_bytes(b'2')
        gazete.prune_audio(name, {'articles': [{'id': 'm1', 'audio': 'm1-aaa.mp3'}]})
        self.assertEqual([p.name for p in folder.iterdir()], ['m1-aaa.mp3'])

    def test_read_article_uses_boxes_and_head(self):
        name = gazete.create(self.make_pages(), 'oku')
        seen = []

        def reader(png):
            seen.append(png[:8])
            return 'BAŞLIK' if len(seen) == 1 else 'göv-\nde metni.'
        article = {'id': 'm1', 'page': 2, 'head': [0, 0, 100, 40], 'boxes': [[0, 50, 200, 300]], 'audio': 'x.mp3'}
        gazete.read_article(name, article, reader)
        self.assertEqual(article['title'], 'BAŞLIK')
        self.assertEqual(article['text'], 'gövde metni.')
        self.assertNotIn('audio', article)
        self.assertTrue(all(item == b'\x89PNG\r\n\x1a\n' for item in seen))


class FakeBackend:
    def __init__(self, audio=None):
        self.data = {'title': 'Sözcü', 'pages': [{'page': 1}],
                     'articles': [{'id': 'm1', 'page': 1, 'head': [0, 0, 10, 10], 'boxes': [], 'title': 'Haber',
                                   'text': 'Metin.', 'audio': 'm1.mp3'}]}
        self.audio_path = audio
        self.frames = []

    def current(self):
        return 'sayi', self.data

    def locate(self, name, frame, point):
        self.frames.append((frame, point))
        return {'page': 1, 'x': 5.0, 'y': 5.0} if frame == b'bulunur' else None

    def audio(self, name, article):
        return self.audio_path

    def article_at(self, data, page, x, y):
        return gazete.article_at(data, page, x, y)

    def text(self, article):
        return gazete.spoken(article)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        audio = Path(self.temp.name) / 'm1.mp3'
        audio.write_bytes(bytes(range(256)) * 4)
        self.backend = FakeBackend(audio)
        self.server = gazete_server.GazeteServer(self.backend, gazete_server.Phones(Path(self.temp.name) / 't.json'),
                                                 '9.9.9', log=lambda _m: None)
        info = self.server.start(0, '127.0.0.1')
        self.base = f'http://127.0.0.1:{info["port"]}'

    def tearDown(self):
        self.server.stop()
        self.temp.cleanup()

    def request(self, method, path, body=None, token=None, headers=None):
        values = dict(headers or {})
        if token:
            values['X-Anahtar'] = token
        req = urllib.request.Request(self.base + path, body, values, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = response.read()
                kind = response.headers.get('Content-Type', '')
                return response.status, json.loads(data) if kind.startswith('application/json') else data, response.headers
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read() or b'{}'), error.headers

    def pair(self):
        status, value, _ = self.request('POST', '/api/eslestir', json.dumps({'kod': self.server.code, 'ad': 'T'}).encode())
        self.assertEqual(status, 200)
        return value['anahtar']

    def test_pairing_required_and_wrong_code_rejected(self):
        self.assertEqual(self.request('GET', '/api/durum')[1]['eslesmis'], False)
        self.assertEqual(self.request('GET', '/api/sayi')[0], 401)
        self.assertEqual(self.request('POST', '/api/eslestir', b'{"kod": "x"}')[0], 403)
        token = self.pair()
        self.assertTrue(self.request('GET', '/api/durum', token=token)[1]['eslesmis'])
        status, value, _ = self.request('GET', '/api/sayi', token=token)
        self.assertEqual((status, value['baslik'], value['makaleler'][0]['id']), (200, 'Sözcü', 'm1'))

    def test_too_many_wrong_codes_lock_pairing(self):
        for _ in range(gazete_server.PAIR_TRIES):
            self.request('POST', '/api/eslestir', b'{"kod": "000000"}')
        status, _value, _ = self.request('POST', '/api/eslestir', json.dumps({'kod': self.server.code}).encode())
        self.assertEqual(status, 403)

    def test_locate_returns_article(self):
        token = self.pair()
        status, value, _ = self.request('POST', '/api/bul?x=0.3&y=2', b'bulunur', token, {'Content-Type': 'image/jpeg'})
        self.assertEqual((status, value['bulundu'], value['makale']['id']), (200, True, 'm1'))
        self.assertEqual(self.backend.frames[-1][1], (0.3, 1.0))
        self.assertFalse(self.request('POST', '/api/bul', b'yok', token)[1]['bulundu'])
        self.assertEqual(self.request('POST', '/api/bul', b'', token)[0], 400)

    def test_article_text_and_audio_range(self):
        token = self.pair()
        self.assertEqual(self.request('GET', '/api/makale/m1', token=token)[1]['metin'], 'Haber.\n\nMetin.')
        self.assertEqual(self.request('GET', '/api/makale/yok', token=token)[0], 404)
        status, data, headers = self.request('GET', '/api/ses/m1', token=token, headers={'Range': 'bytes=10-19'})
        self.assertEqual((status, data, headers['Content-Range']), (206, bytes(range(10, 20)), 'bytes 10-19/1024'))
        status, data, _ = self.request('GET', '/api/ses/m1', token=token)
        self.assertEqual((status, len(data)), (200, 1024))
        self.backend.audio_path = None
        self.assertEqual(self.request('GET', '/api/ses/m1', token=token)[0], 404)

    def test_paired_phone_survives_restart_and_can_be_removed(self):
        token = self.pair()
        self.server.stop()
        info = self.server.start(0, '127.0.0.1')
        self.base = f'http://127.0.0.1:{info["port"]}'
        self.assertEqual(self.request('GET', '/api/sayi', token=token)[0], 200)
        phones = self.server.phones
        self.assertTrue(phones.remove(phones.listing()[0]['id']))
        self.assertEqual(self.request('GET', '/api/sayi', token=token)[0], 401)

    def test_only_local_clients_allowed(self):
        for address, allowed in (('192.168.1.20', True), ('10.0.0.5', True), ('127.0.0.1', True),
                                 ('::ffff:192.168.1.2', True), ('8.8.8.8', False), ('2001:4860::1', False), ('x', False)):
            self.assertEqual(gazete_server.allowed_client(address), allowed, address)


@unittest.skipUnless(HAVE_CV, 'OpenCV yok')
class MatchTests(unittest.TestCase):
    def test_locates_warped_crop_on_right_page(self):
        import numpy as np
        import gazete_match
        from PIL import Image
        rng = np.random.default_rng(3)
        pages = []
        for number in (1, 2):
            canvas = np.full((1400, 1000, 3), 255, np.uint8)
            for _ in range(160):     # rastgele kutular ve cizgiler: gazete benzeri ayrinti
                x, y = int(rng.integers(0, 950)), int(rng.integers(0, 1350))
                color = tuple(int(c) for c in rng.integers(0, 200, 3))
                cv2.rectangle(canvas, (x, y), (x + int(rng.integers(8, 120)), y + int(rng.integers(4, 60))), color, -1)
                cv2.putText(canvas, 'GAZETE', (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)
            pages.append((number, Image.fromarray(canvas)))
        index = gazete_match.PageIndex(pages)
        page2 = np.asarray(pages[1][1])
        source = np.float32([[300, 400], [700, 420], [720, 900], [280, 880]])
        warp = cv2.getPerspectiveTransform(source, np.float32([[0, 0], [600, 0], [600, 800], [0, 800]]))
        frame = cv2.GaussianBlur(cv2.warpPerspective(page2, warp, (600, 800)), (0, 0), 1.0)
        found = index.locate(frame)
        self.assertIsNotNone(found)
        self.assertEqual(found['page'], 2)
        center = cv2.perspectiveTransform(np.float32([[[300, 400]]]), np.linalg.inv(warp))[0, 0]
        self.assertLess(abs(found['x'] - center[0]) + abs(found['y'] - center[1]), 20)
        self.assertIsNone(index.locate(np.full((800, 600, 3), 128, np.uint8)))
        with self.assertRaises(ValueError):
            gazete_match.decode(b'jpeg degil')


if __name__ == '__main__':
    unittest.main()
