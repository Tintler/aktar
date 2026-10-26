import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))

import http.server
import json
from pathlib import Path
import tempfile
import threading
import unittest

import book_art
import comfy_client

# Kullanicinin Krea2 is akisinin ozu (API formati, alt grafik kimlikleri dahil).
WORKFLOW = {
    '2': {'inputs': {'seed': 1, 'steps': 10, 'cfg': 1, 'model': ['57', 0], 'positive': ['104', 0],
                     'negative': ['17', 0], 'latent_image': ['106:10', 0]}, 'class_type': 'KSampler',
          '_meta': {'title': 'KSampler'}},
    '17': {'inputs': {'text': '', 'clip': ['57', 1]}, 'class_type': 'CLIPTextEncode', '_meta': {'title': 'Negative Prompt'}},
    '33': {'inputs': {'filename_prefix': 'Krea2/x', 'images': ['3', 0]}, 'class_type': 'SaveImage',
           '_meta': {'title': 'Save Image'}},
    '96': {'inputs': {'positive': ''}, 'class_type': 'easy positive', '_meta': {'title': 'PRE-PROMPT'}},
    '97': {'inputs': {'positive': 'web page mockup'}, 'class_type': 'easy positive', '_meta': {'title': 'Positive'}},
    '98': {'inputs': {'positive': ''}, 'class_type': 'easy positive', '_meta': {'title': 'POST-PROMPT'}},
    '104': {'inputs': {'text': ['99', 0], 'clip': ['57', 1]}, 'class_type': 'CLIPTextEncode',
            '_meta': {'title': 'COMBINED PROMPT'}},
    '106:10': {'inputs': {'width': 1024, 'height': 1024, 'batch_size': 1}, 'class_type': 'EmptyLatentImage',
               '_meta': {'title': 'Empty Latent Image'}},
}
PNG = b'\x89PNG\r\n\x1a\nfake'
# Karakter kimligi is akisi (F201, Krea 2 Identity Edit ozu): REFERENCE LoadImage + grounded encode'da istem.
IDENTITY = {
    '5': {'inputs': {'image': 'portre.png', 'upload': 'image'}, 'class_type': 'LoadImage', '_meta': {'title': 'REFERENCE'}},
    '7': {'inputs': {'width': 1344, 'height': 768, 'batch_size': 1}, 'class_type': 'EmptySD3LatentImage',
          '_meta': {'title': 'Empty Latent Image'}},
    '9': {'inputs': {'clip': ['2', 0], 'prompt': '', 'image': ['5', 0], 'grounding_px': 768, 'system_prompt': ''},
          'class_type': 'Krea2EditGroundedEncode', '_meta': {'title': 'Positive'}},
    '10': {'inputs': {'clip': ['2', 0], 'prompt': '', 'image': ['5', 0], 'grounding_px': 768, 'system_prompt': ''},
           'class_type': 'Krea2EditGroundedEncode', '_meta': {'title': 'Negative'}},
    '11': {'inputs': {'seed': 1, 'steps': 10, 'cfg': 1, 'positive': ['9', 0], 'negative': ['10', 0],
                      'latent_image': ['7', 0]}, 'class_type': 'KSampler', '_meta': {'title': 'KSampler'}},
    '13': {'inputs': {'filename_prefix': 'Aktar/kimlik', 'images': ['12', 0]}, 'class_type': 'SaveImage',
           '_meta': {'title': 'Save Image'}},
}


class FakeComfy:
    """ComfyUI'nin yerine: /prompt kuyruga alir, /history ilk sorguda bitmis gosterir, /view gorseli verir."""

    def __init__(self, fail=None):
        self.prompts, self.calls, self.fail, self.uploads = [], [], fail, []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _send(self, code, value, raw=False):
                body = value if raw else json.dumps(value).encode()
                self.send_response(code)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                owner.calls.append(('GET', self.path))
                if self.path == '/system_stats':
                    return self._send(200, {'system': {'comfyui_version': '0.9'}, 'devices': [{'name': 'RTX 5080'}]})
                if self.path.startswith('/history/'):
                    pid = self.path.rsplit('/', 1)[1]
                    if owner.fail == 'run':
                        return self._send(200, {pid: {'status': {'status_str': 'error', 'completed': False, 'messages': [
                            ['execution_error', {'exception_message': 'CUDA out of memory'}]]}, 'outputs': {}}})
                    return self._send(200, {pid: {'status': {'status_str': 'success', 'completed': True},
                                                  'outputs': {'33': {'images': [{'filename': 'a.png', 'subfolder': 'Aktar',
                                                                                 'type': 'output'}]}}}})
                if self.path.startswith('/view?'):
                    return self._send(200, PNG, raw=True)
                self._send(404, {})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get('Content-Length') or 0)
                raw = self.rfile.read(length)
                owner.calls.append(('POST', self.path))
                if self.path == '/upload/image':
                    name = raw.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
                    owner.uploads.append((name, PNG in raw, b'name="overwrite"' in raw))
                    return self._send(200, {'name': name, 'subfolder': '', 'type': 'input'})
                body = json.loads(raw or b'{}')
                if self.path == '/prompt':
                    if owner.fail == 'queue':
                        return self._send(400, {'error': {'message': 'Prompt outputs failed validation'},
                                                'node_errors': {'1': {'class_type': 'UNETLoader', 'errors': [
                                                    {'message': 'Value not in list', 'details': 'krea2.safetensors'}]}}})
                    owner.prompts.append(body['prompt'])
                    return self._send(200, {'prompt_id': f'p{len(owner.prompts)}'})
                self._send(200, {})

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class WorkflowTest(unittest.TestCase):
    def test_slots_found_by_title(self):
        found = comfy_client.slots(WORKFLOW)
        self.assertIs(found['positive'], WORKFLOW['97'])
        self.assertIs(found['pre'], WORKFLOW['96'])
        self.assertIs(found['latent'], WORKFLOW['106:10'])
        self.assertTrue(comfy_client.describe_workflow(WORKFLOW)['ok'])

    def test_fill_does_not_touch_template(self):
        filled = comfy_client.fill(WORKFLOW, 'a mine shaft', 'gritty painting', 'no text', 42, (1344, 768), 'Aktar/b/1')
        self.assertEqual(filled['97']['inputs']['positive'], 'a mine shaft')
        self.assertEqual(filled['96']['inputs']['positive'], 'gritty painting')
        self.assertEqual(filled['98']['inputs']['positive'], 'no text')
        self.assertEqual(filled['2']['inputs']['seed'], 42)
        self.assertEqual((filled['106:10']['inputs']['width'], filled['106:10']['inputs']['height']), (1344, 768))
        self.assertEqual(filled['33']['inputs']['filename_prefix'], 'Aktar/b/1')
        self.assertEqual(WORKFLOW['97']['inputs']['positive'], 'web page mockup')

    def test_plain_workflow_gets_style_in_prompt(self):
        plain = {'6': {'inputs': {'text': 'x'}, 'class_type': 'CLIPTextEncode', '_meta': {'title': 'CLIP Text Encode'}},
                 '7': {'inputs': {'text': ''}, 'class_type': 'CLIPTextEncode', '_meta': {'title': 'Negative'}},
                 '9': {'inputs': {'filename_prefix': 'x'}, 'class_type': 'SaveImage'}}
        filled = comfy_client.fill(plain, 'scene', 'style', 'suffix')
        self.assertEqual(filled['6']['inputs']['text'], 'style. scene. suffix')

    def test_ui_format_rejected(self):
        with self.assertRaisesRegex(comfy_client.ComfyError, 'API'):
            comfy_client.load_workflow(json.dumps({'nodes': [], 'links': []}))
        missing = dict(WORKFLOW)
        del missing['33']
        self.assertIn('SaveImage', comfy_client.describe_workflow(missing)['message'])


    def test_identity_workflow(self):
        self.assertFalse(comfy_client.describe_identity_workflow(WORKFLOW)['ok'])
        self.assertIn('REFERENCE', comfy_client.describe_identity_workflow(WORKFLOW)['message'])
        info = comfy_client.describe_identity_workflow(IDENTITY)
        self.assertTrue(info['ok'], info)
        self.assertIn('tek kişilik', info['message'])
        filled = comfy_client.fill(IDENTITY, 'Create an illustration of this person', '', 'no text', 7, (1344, 768),
                                   'Aktar/b/1', images=['aktar-portre.png', 'fazla.png'])
        self.assertEqual(filled['5']['inputs']['image'], 'aktar-portre.png')
        self.assertEqual(filled['9']['inputs']['prompt'], 'Create an illustration of this person. no text')
        self.assertEqual(filled['10']['inputs']['prompt'], '')   # olumsuz grounded encode bos kalir
        self.assertEqual(IDENTITY['5']['inputs']['image'], 'portre.png')
        with self.assertRaisesRegex(comfy_client.ComfyError, 'REFERENCE'):
            comfy_client.fill(WORKFLOW, 'x', images=['a.png'])


class ServerTest(unittest.TestCase):
    def test_upload_image(self):
        fake = FakeComfy()
        self.addCleanup(fake.close)
        self.assertEqual(comfy_client.upload_image(fake.url, PNG, 'aktar-ab/portre sekai-1.png'),
                         'aktar-abportresekai-1.png')
        self.assertEqual(fake.uploads, [('aktar-abportresekai-1.png', True, True)])

    def test_generate_returns_image(self):
        fake = FakeComfy()
        self.addCleanup(fake.close)
        self.assertIn('RTX 5080', comfy_client.health(fake.url)['message'])
        filled = comfy_client.fill(WORKFLOW, 'scene', 'style')
        self.assertEqual(comfy_client.generate(fake.url, filled), PNG)
        self.assertEqual(fake.prompts[0]['97']['inputs']['positive'], 'scene')

    def test_errors_are_readable(self):
        fake = FakeComfy(fail='queue')
        self.addCleanup(fake.close)
        with self.assertRaisesRegex(comfy_client.ComfyError, 'krea2.safetensors'):
            comfy_client.generate(fake.url, WORKFLOW)
        fake.fail = 'run'
        with self.assertRaisesRegex(comfy_client.ComfyError, 'out of memory'):
            comfy_client.generate(fake.url, WORKFLOW)

    def test_unreachable(self):
        with self.assertRaisesRegex(comfy_client.ComfyError, 'bağlanılamadı'):
            comfy_client.health('http://127.0.0.1:9')


def book(*lengths):
    return [{'sentences': [f'Bölüm {n} cümle {i} ' + 'x' * 80 + '.' for i in range(count)], 'breaks': []}
            for n, count in enumerate(lengths)]


class PlanTest(unittest.TestCase):
    def test_chunks_split_long_sections(self):
        parts = book_art.chunks(book(3, 400), limit=14000)
        self.assertEqual(parts[0], (0, 0, 3))
        self.assertGreater(len(parts), 2)
        self.assertEqual(sum(stop - start for _s, start, stop in parts), 403)

    def test_short_section_gets_no_scene(self):
        self.assertEqual(book_art.scene_count(200), 0)
        self.assertEqual(book_art.scene_count(9000, 'medium'), 3)
        self.assertEqual(book_art.scene_count(9000, 'high'), 6)
        self.assertEqual(book_art.scene_count(9000, 'low'), 1)

    def test_parse_scenes_cleans_reply(self):
        sentences = [f's{i}' for i in range(20)]
        raw = ('<think>hmm {"x": 1}</think>```json\n{"scenes": [{"start": 13, "title": "B", "prompt": "two"},'
               '{"start": 12, "title": "A", "prompt": "one", "characters": [{"name": "Sekai", "look": "white suit"}]},'
               '{"start": 99, "prompt": "out"}, {"start": 13, "prompt": "dup"}, {"start": 14, "prompt": ""}]}\n```')
        scenes, characters = book_art.parse_scenes(raw, 10, 20, sentences)
        self.assertEqual([(s['start'], s['prompt']) for s in scenes], [(10, 'one'), (13, 'two')])
        self.assertEqual(characters, [{'name': 'Sekai', 'look': 'white suit'}])

    def test_style_not_repeated_in_scene(self):
        style = 'Cinematic digital illustration with dramatic chiaroscuro lighting. Rust and cyan palette.'
        prompt = 'Cinematic digital illustration with dramatic lighting and rich textures. Wide shot of a shaft.'
        self.assertEqual(book_art.strip_style(prompt, style), 'Wide shot of a shaft.')
        self.assertEqual(book_art.strip_style('Wide shot of a shaft.', style), 'Wide shot of a shaft.')
        raw = json.dumps({'scenes': [{'start': 0, 'title': 'A', 'prompt': prompt}]})
        self.assertEqual(book_art.parse_scenes(raw, 0, 3, ['a', 'b', 'c'], style)[0][0]['prompt'], 'Wide shot of a shaft.')

    def test_plan_book_uses_note_and_resumes(self):
        sections = book(3, 60)
        prompts = []

        def ask(system, user):
            prompts.append(user)
            if '"style"' in user and 'JSON shape: {"style"' in user:
                return json.dumps({'style': 'muted watercolour', 'characters': [{'name': 'Ana', 'look': 'red coat'}]})
            first = int(user.split('the first scene starts at ')[1].split(')')[0])
            return json.dumps({'scenes': [{'start': first, 'title': 'T', 'prompt': f'scene {first}'}]})

        saved = []
        plan = book_art.new_plan('daha soyut ol', 'abstract', 'medium')
        result = book_art.plan_book(sections, ask, plan, save=lambda p: saved.append(json.loads(json.dumps(p))))
        self.assertTrue(result['complete'])
        self.assertIn('daha soyut ol', prompts[0])
        self.assertIn('Ana: red coat', prompts[1])
        self.assertEqual([s['section'] for s in result['scenes']], [1])   # 3 cumlelik bolum sahne almaz
        self.assertEqual(result['scenes'][0]['anchor'], sections[1]['sentences'][0])
        # stil yazilmis, ilk parca bitmis yarim plandan devam: stil yeniden istenmez
        half = next(p for p in saved if p['style'] and p['next_chunk'] == 1)
        prompts.clear()
        book_art.plan_book(sections, ask, half)
        self.assertFalse(any('JSON shape: {"style"' in p for p in prompts))

    def test_scene_keeps_reader_section_number(self):
        # bos bolumler (kapak, gorsel sayfasi) okuyucuda sayilir ama plana gelmez: sahne okuyucunun numarasini almali
        sections = book(60)
        sections[0]['number'] = 4
        ask = lambda system, user: (json.dumps({'style': 's', 'characters': []}) if 'JSON shape: {"style"' in user
                                    else json.dumps({'scenes': [{'start': 0, 'title': 'T', 'prompt': 'p'}]}))
        result = book_art.plan_book(sections, ask, book_art.new_plan())
        self.assertEqual((result['scenes'][0]['section'], result['scenes'][0]['id']), (4, '4-0'))
        self.assertTrue(result['numbered'])

    def test_renumber_old_plan(self):
        plan = book_art.new_plan()
        del plan['numbered']
        plan['scenes'] = [{'id': '0-0', 'section': 0, 'start': 0, 'anchor': 'Önsöz başlar.'},
                          {'id': '1-5', 'section': 1, 'start': 5, 'anchor': 'Ben  o gece, uyumadım.'}]
        texts = ['', 'Önsöz\nbaşlar. Devam.', '   ', 'Bölüm\nBen o gece,\nuyumadım. Sonra...']
        self.assertTrue(book_art.renumber(plan, texts))
        self.assertEqual([s['section'] for s in plan['scenes']], [1, 3])
        self.assertFalse(book_art.renumber(plan, texts))   # bir kez
        # baska kitabin metni: dokunulmaz
        other = book_art.new_plan()
        del other['numbered']
        other['scenes'] = [{'id': '0-0', 'section': 0, 'start': 0, 'anchor': 'Yok böyle cümle.'}]
        self.assertFalse(book_art.renumber(other, texts))
        self.assertEqual(other['scenes'][0]['section'], 0)

    def test_cancel(self):
        import threading as _t
        cancel = _t.Event()
        cancel.set()
        plan = book_art.new_plan()
        plan['style'] = 'x'
        with self.assertRaises(book_art.Cancelled):
            book_art.plan_book(book(60), lambda *_a: '{}', plan, cancel)

    def test_identity_asks_for_cast(self):
        sentences = ['a', 'b', 'c']
        plain = book_art.scene_prompt('s', [], sentences, 0, 3, 1)[1]
        asked = book_art.scene_prompt('s', [], sentences, 0, 3, 1, identity=True)[1]
        self.assertNotIn('cast', plain)   # kimlik kapaliyken istem eskisiyle ayni
        self.assertIn('"cast": []', asked)
        self.assertIn('not posing or looking at the camera', asked)
        raw = json.dumps({'scenes': [{'start': 0, 'title': 'A', 'prompt': 'p', 'cast': ['Sekai', ' sekai ', '', 'Asa']}]})
        self.assertEqual(book_art.parse_scenes(raw, 0, 3, sentences)[0][0]['cast'], ['Sekai', 'Asa'])

        def ask(system, user):
            if 'JSON shape: {"style"' in user:
                return json.dumps({'style': 'Oil painting. Rusty mine.', 'characters': [{'name': 'Sekai', 'look': 'w'}]})
            return json.dumps({'scenes': [{'start': 0, 'title': 'T', 'prompt': 'p', 'cast': ['Sekai']}]})

        plan = book_art.plan_book(book(60), ask, book_art.new_plan(identity=True))
        self.assertEqual(plan['scenes'][0]['cast'], ['Sekai'])
        self.assertTrue(plan['identity'])
        self.assertFalse(book_art.new_plan()['identity'])

    def test_cast_of(self):
        characters = [{'name': 'Sekai', 'look': 'a young woman in a scuffed white jumpsuit and cracked helmet'},
                      {'name': 'Murderbot', 'look': 'a bulky matte-black security exosuit with an opaque visor'}]
        scene = {'prompt': 'A bulky matte-black security exosuit with an opaque visor lifts a young woman in a scuffed '
                           'white jumpsuit and cracked helmet.'}
        self.assertEqual([c['name'] for c in book_art.cast_of(scene, characters)], ['Murderbot', 'Sekai'])
        self.assertEqual(book_art.cast_of({'prompt': 'Sekai sits alone.'}, characters)[0]['name'], 'Sekai')
        self.assertEqual(book_art.cast_of({'prompt': 'An empty shaft.'}, characters), [])
        scene['cast'] = ['sekai', 'Yok']
        self.assertEqual([c['name'] for c in book_art.cast_of(scene, characters)], ['Sekai'])
        scene['cast'] = []
        self.assertEqual(book_art.cast_of(scene, characters), [])

    def test_identity_prompts(self):
        self.assertEqual(book_art.medium('Cinematic digital painting, matte. Rust palette and fog.'),
                         'Cinematic digital painting, matte.')
        character = {'name': 'Sekai', 'look': 'a young woman with short black hair'}
        self.assertIn('Plain flat mid-grey studio backdrop', book_art.portrait_prompt(character))
        text = book_art.identity_prompt({'prompt': 'She clings to a ledge.'}, [character], 'Oil painting.')
        self.assertTrue(text.startswith('Create an illustration of this person: a young woman with short black hair.'))
        self.assertIn('She clings to a ledge.', text)
        self.assertTrue(text.endswith('Style: Oil painting'))   # son eki fill '. ' ile ekler
        self.assertNotIn('..', text + book_art.portrait_prompt({'name': 'A', 'look': 'a robot.'}))
        two = book_art.identity_prompt({'prompt': 'p'}, [character, {'name': 'B', 'look': 'a robot'}], 's')
        self.assertIn('reference 2 (a robot)', two)
        self.assertEqual(book_art.portrait_slug('Şükrü Çağ'), 'sukru-cag')
        kept = book_art.keep_portraits([{'name': 'sekai', 'look': 'new'}],
                                       [{'name': 'Sekai', 'look': 'old', 'portrait': 'portre-sekai-2.png',
                                         'portrait_version': 2}])
        self.assertEqual(kept, [{'name': 'sekai', 'look': 'new', 'portrait': 'portre-sekai-2.png', 'portrait_version': 2}])

    def test_refined_prompt(self):
        self.assertEqual(book_art.parse_refined('Prompt: "a dark hall"', 'old'), 'a dark hall')
        self.assertEqual(book_art.parse_refined('', 'old'), 'old')
        self.assertIn('kişiyi çıkar', book_art.refine_prompt('a man in a hall', 'kişiyi çıkar')[1])


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = book_art.Store(self.tmp.name)
        self.book = 'ab12cd34ef'
        plan = book_art.new_plan()
        plan['scenes'] = [{'id': '0-0', 'section': 0, 'start': 0, 'anchor': 'a', 'title': 't', 'prompt': 'p',
                           'seed': 1, 'image': '', 'skip': False},
                          {'id': '2-5', 'section': 2, 'start': 5, 'anchor': 'b', 'title': 't', 'prompt': 'p',
                           'seed': 2, 'image': '', 'skip': False}]
        self.store.save(self.book, plan)

    def test_images_versioned_and_old_removed(self):
        plan = self.store.write_image(self.book, '0-0', PNG)
        first = plan['scenes'][0]['image']
        plan = self.store.write_image(self.book, '0-0', PNG + b'2')
        second = plan['scenes'][0]['image']
        self.assertNotEqual(first, second)
        folder = Path(self.tmp.name) / book_art.STORE_DIR / self.book
        self.assertFalse((folder / first).exists())
        self.assertEqual((folder / second).read_bytes(), PNG + b'2')
        self.assertEqual([s['id'] for s in book_art.pending(plan)], ['2-5'])

    def test_section_images_carry_previous(self):
        self.store.write_image(self.book, '0-0', PNG)
        plan = self.store.load(self.book)
        here, carry = book_art.section_images(plan, 1)
        self.assertEqual((here, carry['id']), ([], '0-0'))
        self.assertEqual(book_art.summary(plan), {'complete': False, 'scenes': 2, 'images': 1,
                                                  'created': plan['created']})
        self.assertEqual(self.store.books(), [self.book])
        self.store.clear(self.book)
        self.assertEqual(self.store.books(), [])

    def test_bad_book_id(self):
        with self.assertRaises(ValueError):
            self.store.folder('../x')


class BridgeTest(unittest.TestCase):
    """Kitapliktan plan (sahte dil modeli) -> uretim (sahte ComfyUI) -> okuyucunun bolum gorselleri."""

    def setUp(self):
        from unittest.mock import patch
        import bridge_art
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(bridge_art, 'APP_DIR', Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = FakeComfy()
        self.addCleanup(self.fake.close)
        fake_url = self.fake.url

        class Media:
            def file_url(self, path):
                return 'http://media/f/' + Path(path).name

        class FakeBridge(bridge_art.ArtMixin):
            def __init__(self):
                self.events, self.logs, self._media = [], [], Media()

            def ui_prefs(self):
                return {'art': {'comfy_url': fake_url}}

            def _emit(self, name, data):
                self.events.append((name, data))

            def _log(self, message):
                self.logs.append(message)

        self.bridge = FakeBridge()
        source = Path(self.tmp.name) / 'akis.json'
        source.write_text(json.dumps(WORKFLOW), encoding='utf-8')
        self.assertTrue(self.bridge.art_set_workflow(str(source))['ok'])

    def finish(self):
        self.bridge._art_job.join(15)
        return self.bridge.events[-1][1]

    def test_plan_generate_and_read(self):
        from unittest.mock import patch

        class FakeClient:
            def __init__(self, cfg, log=None):
                self.cfg = {'model': 'sohbet'}

            def chat(self, messages, temperature=None, max_tokens=None):
                user = messages[1]['content']
                if 'JSON shape: {"style"' in user:
                    return '{"style": "engraving", "characters": []}'
                first = int(user.split('the first scene starts at ')[1].split(')')[0])
                return json.dumps({'scenes': [{'start': first, 'title': 'Maden', 'prompt': 'a mine shaft'}]})

        sections = book(2, 50)
        with patch('app_core.Client', FakeClient), patch('app_core.load_config', return_value={}), \
                patch('app_core.keep_loaded', return_value=['sohbet:1']), patch('app_core.unload_models') as unload:
            self.assertTrue(self.bridge.art_plan_create('ab12cd34ef', sections, 'gravür gibi', 'engraving',
                                                         'medium', 'Kitap')['started'])
            done = self.finish()
        self.assertEqual(done['summary']['scenes'], 1, done)
        self.assertEqual(unload.call_args[0][1], ['sohbet:1'])
        self.assertIn(('POST', '/free'), self.fake.calls)   # ComfyUI dil modelinden once bellegi birakti
        self.assertEqual(self.bridge.art_section('ab12cd34ef', 1), {'scenes': [], 'carry': ''})

        self.assertTrue(self.bridge.art_generate('ab12cd34ef')['started'])
        done = self.finish()
        self.assertEqual(done['done'], 1, done)
        sent = self.fake.prompts[0]
        self.assertEqual(sent['96']['inputs']['positive'], 'engraving')
        self.assertEqual(sent['97']['inputs']['positive'], 'a mine shaft')
        self.assertEqual(sent['98']['inputs']['positive'], book_art.SUFFIX)
        shown = self.bridge.art_section('ab12cd34ef', 1)
        self.assertEqual(shown['scenes'][0]['start'], 0)
        self.assertTrue(shown['scenes'][0]['url'].endswith('.png'))
        self.assertEqual(self.bridge.art_books()['ab12cd34ef']['images'], 1)
        self.assertIn('error', self.bridge.art_generate('ab12cd34ef'))   # uretilecek gorsel kalmadi

        scene = self.bridge.art_plan_get('ab12cd34ef')['plan']['scenes'][0]
        updated = self.bridge.art_scene_update('ab12cd34ef', scene['id'], {'reseed': True, 'skip': True})
        self.assertTrue(updated['plan']['scenes'][0]['skip'])
        self.assertEqual(self.bridge.art_section('ab12cd34ef', 1)['scenes'], [])

    def identity_plan(self, identity=True):
        store = self.bridge._art_store()
        plan = book_art.new_plan(identity=identity)
        plan.update(complete=True, style='Oil painting with heavy brushwork. Rusty mine, fog and hazard lamps.',
                    characters=[{'name': 'Sekai', 'look': 'a young woman in a scuffed white jumpsuit'}])
        plan['scenes'] = [{'id': '1-0', 'section': 1, 'start': 0, 'anchor': 'a', 'title': 'Kurtarma', 'seed': 5,
                           'prompt': 'A young woman in a scuffed white jumpsuit clings to a ledge.', 'image': '',
                           'skip': False},
                          {'id': '1-9', 'section': 1, 'start': 9, 'anchor': 'b', 'title': 'Boş', 'seed': 6,
                           'prompt': 'An empty mine shaft.', 'image': '', 'skip': False}]
        store.save('ab12cd34ef', plan)
        return store

    def test_identity_off_keeps_old_flow(self):
        self.identity_plan(identity=False)
        self.assertTrue(self.bridge.art_generate('ab12cd34ef')['started'])   # kimlik is akisi olmadan da
        self.assertEqual(self.finish()['done'], 2)
        self.assertEqual(self.fake.uploads, [])
        self.assertTrue(all('97' in sent for sent in self.fake.prompts))
        self.assertNotIn('people', self.bridge.art_plan_get('ab12cd34ef')['plan']['scenes'][0])

    def test_identity_portrait_then_scene(self):
        store = self.identity_plan()
        self.assertIn('kimlik iş akışını', self.bridge.art_generate('ab12cd34ef')['error'])
        source = Path(self.tmp.name) / 'kimlik.json'
        source.write_text(json.dumps(IDENTITY), encoding='utf-8')
        self.assertIn('error', self.bridge.art_set_workflow(str(Path(self.tmp.name) / 'akis.json'), 'identity'))
        self.assertTrue(self.bridge.art_set_workflow(str(source), 'identity')['ok'])
        self.assertTrue(self.bridge.art_options()['identity_workflow']['ok'])

        started = self.bridge.art_generate('ab12cd34ef')
        self.assertEqual(started['total'], 3)   # Sekai'nin portresi + iki sahne
        done = self.finish()
        self.assertEqual(done['done'], 3, done)
        portrait, scene, empty = self.fake.prompts
        self.assertEqual(portrait['96']['inputs']['positive'], 'Oil painting with heavy brushwork.')   # yalnizca teknik
        self.assertIn('studio backdrop', portrait['97']['inputs']['positive'])
        self.assertEqual((portrait['106:10']['inputs']['width'], portrait['106:10']['inputs']['height']), (1024, 1024))
        plan = store.load('ab12cd34ef')
        name = plan['characters'][0]['portrait']
        self.assertTrue((store.folder('ab12cd34ef') / name).is_file())
        self.assertEqual(self.fake.uploads[0][0], f'aktar-ab12cd34ef-{name}')
        self.assertEqual(scene['5']['inputs']['image'], f'aktar-ab12cd34ef-{name}')
        self.assertTrue(scene['9']['inputs']['prompt'].startswith('Create an illustration of this person'))
        self.assertEqual(scene['11']['inputs']['seed'], 5)
        self.assertIn('97', empty)   # karaktersiz sahne ana is akisiyla
        view = self.bridge.art_plan_get('ab12cd34ef')['plan']
        self.assertEqual((view['scenes'][0]['people'], view['scenes'][1]['people']), (['Sekai'], []))
        self.assertTrue(view['characters'][0]['portrait_url'].endswith('.png'))

        # yalnizca portreyi yeniden uret: yeni seed, sahne uretilmez; karakter duzenlenince portre kalir
        seed = plan['characters'][0]['portrait_seed']
        self.assertEqual(self.bridge.art_generate('ab12cd34ef', portraits=['sekai'])['total'], 1)
        self.finish()
        plan = store.load('ab12cd34ef')
        self.assertEqual(len(self.fake.prompts), 4)
        self.assertNotEqual(plan['characters'][0]['portrait_seed'], seed)
        self.assertFalse((store.folder('ab12cd34ef') / name).exists())
        saved = self.bridge.art_plan_save('ab12cd34ef', {'characters': [{'name': 'Sekai', 'look': 'short hair'}]})
        self.assertTrue(saved['plan']['characters'][0]['portrait_url'])

        # sahnenin kadrosu elle bosaltilinca referans kullanilmaz; None ile kendiliginden bulmaya doner
        self.bridge.art_scene_update('ab12cd34ef', '1-0', {'cast': []})
        self.assertEqual(self.bridge.art_plan_get('ab12cd34ef')['plan']['scenes'][0]['people'], [])
        self.bridge.art_scene_update('ab12cd34ef', '1-0', {'cast': None})
        self.assertNotIn('cast', store.load('ab12cd34ef')['scenes'][0])

        # kendi gorseli PNG'ye cevrilir; portre silinebilir
        from PIL import Image
        own = Path(self.tmp.name) / 'own.jpg'
        Image.new('RGB', (8, 8), 'red').save(own)
        shown = self.bridge.art_portrait_set('ab12cd34ef', 'Sekai', str(own))['plan']['characters'][0]
        self.assertTrue(shown['portrait_own'])
        self.assertEqual((store.folder('ab12cd34ef') / shown['portrait']).read_bytes()[:4], b'\x89PNG')
        cleared = self.bridge.art_portrait_clear('ab12cd34ef', 'Sekai')['plan']['characters'][0]
        self.assertEqual(cleared['portrait_url'], '')
        self.assertIn('error', self.bridge.art_portrait_clear('ab12cd34ef', 'Yok'))

    def test_old_plan_renumbered_on_read(self):
        from unittest.mock import patch
        store = self.bridge._art_store()
        plan = book_art.new_plan()
        del plan['numbered']
        plan['complete'] = True
        plan['scenes'] = [{'id': '1-0', 'section': 1, 'start': 0, 'anchor': 'Gece başladı.', 'image': '1-0-1.png',
                           'skip': False, 'version': 1}]
        store.save('ab12cd34ef', plan)
        (store.folder('ab12cd34ef') / '1-0-1.png').write_bytes(b'png')

        class Shelf:
            def _book(self, book_id):
                return {}, object()

        self.bridge._shelf = lambda: Shelf()
        texts = ['', 'Kapak', '', 'Gece başladı. Sonra...']   # eski sira 1 -> okuyucunun 3. bolumu
        with patch('book_search.section_texts', return_value=iter(texts)) as read:
            shown = self.bridge.art_section('ab12cd34ef', 2)
            self.assertEqual(self.bridge.art_section('ab12cd34ef', 3)['scenes'][0]['start'], 0)
        self.assertEqual(shown['scenes'], [])
        self.assertEqual(read.call_count, 1)
        self.assertTrue(json.loads((store.folder('ab12cd34ef') / 'plan.json').read_text(encoding='utf-8'))['numbered'])


if __name__ == '__main__':
    unittest.main()
