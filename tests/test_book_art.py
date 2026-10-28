import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))

import http.server
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

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
        self.prompts, self.calls, self.fail, self.uploads, self.loras = [], [], fail, [], []
        self.rtx = False   # F209 RTX Video Super Resolution dugumu kurulu mu
        self.image = PNG   # /view'in verdigi gorsel (F217 birlestirme gercek PNG ister)
        self.preview = False   # F213 is akisinda once gelen PreviewImage ciktisi
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
                    if owner.fail == 'run' or (owner.fail == 'first' and pid == 'p1'):
                        return self._send(200, {pid: {'status': {'status_str': 'error', 'completed': False, 'messages': [
                            ['execution_error', {'exception_message': 'CUDA out of memory'}]]}, 'outputs': {}}})
                    outputs = {'33': {'images': [{'filename': 'a.png', 'subfolder': 'Aktar', 'type': 'output'}]}}
                    if owner.preview:
                        outputs = {'40': {'images': [{'filename': 'onizleme.png', 'subfolder': '', 'type': 'temp'}]},
                                   **outputs}
                    return self._send(200, {pid: {'status': {'status_str': 'success', 'completed': True},
                                                  'outputs': outputs}})
                if self.path.startswith('/view?'):
                    return self._send(200, owner.image, raw=True)
                if self.path == '/object_info/RTXVideoSuperResolution':
                    return self._send(200, {'RTXVideoSuperResolution': {'input': {}}} if owner.rtx else {})
                if self.path == '/object_info/LoraLoaderModelOnly':
                    return self._send(200, {'LoraLoaderModelOnly': {'input': {'required': {
                        'model': ['MODEL'], 'lora_name': ['COMBO', {'options': owner.loras}]}}}})
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
        # F213: noktayla biten stil ve istem birlesirken nokta ikilenmez
        filled = comfy_client.fill(plain, 'A desk by a window.', 'Ink drawing, sepia.', 'no text')
        self.assertEqual(filled['6']['inputs']['text'], 'Ink drawing, sepia. A desk by a window. no text')

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


    def test_add_loras_after_model_loader(self):
        """F202: LoRA model yukleyicisinin arkasina eklenir; arada Power Lora Loader / kimlik LoRA'si varsa korunur."""
        main = dict(WORKFLOW, **{
            '57': {'inputs': {'model': ['106:1', 0], 'clip': ['106:13', 0]}, 'class_type': 'Power Lora Loader (rgthree)'},
            '106:1': {'inputs': {'unet_name': 'krea2.safetensors'}, 'class_type': 'UNETLoader'}})
        filled = comfy_client.add_loras(main, [('a.safetensors', 0.9), ('b.safetensors', 1)])
        self.assertEqual(filled['57']['inputs']['model'], ['aktar-lora-0-1', 0])
        self.assertEqual(filled['aktar-lora-0-1']['inputs']['model'], ['aktar-lora-0-0', 0])
        self.assertEqual(filled['aktar-lora-0-0']['inputs'], {'lora_name': 'a.safetensors', 'strength_model': 0.9,
                                                              'model': ['106:1', 0]})
        self.assertEqual(filled['57']['inputs']['clip'], ['106:13', 0])
        self.assertNotIn('aktar-lora-0-0', main)
        self.assertEqual(comfy_client.add_loras(main, []), main)

        identity = dict(IDENTITY, **{
            '1': {'inputs': {'unet_name': 'krea2.safetensors'}, 'class_type': 'UNETLoader'},
            '4': {'inputs': {'lora_name': 'identity.safetensors', 'model': ['1', 0]}, 'class_type': 'LoraLoaderModelOnly'},
            '8': {'inputs': {'model': ['4', 0]}, 'class_type': 'Krea2EditModelPatch'}})
        identity['11'] = dict(identity['11'], inputs=dict(identity['11']['inputs'], model=['8', 0]))
        filled = comfy_client.add_loras(identity, [('a.safetensors', 1)])
        self.assertEqual(filled['4']['inputs']['model'], ['aktar-lora-0-0', 0])
        self.assertEqual(filled['11']['inputs']['model'], ['8', 0])
        with self.assertRaisesRegex(comfy_client.ComfyError, 'model yükleyici'):
            comfy_client.add_loras(WORKFLOW, [('a.safetensors', 1)])

    def test_band_prompts_and_compose(self):
        """F217: "Top: ... Bottom: ..." iki seride ayrilir, orta cumlesi atilir; seritler gecisle birlestirilir."""
        from io import BytesIO
        from PIL import Image
        top, bottom = book_art.band_prompts(
            'Top: Rusted pipes hang from a low ceiling. Bottom: Four people argue on a metal deck. In the center of '
            'the deck a lamp burns. The middle is an empty smooth gradient fading to black.')
        self.assertEqual(top, 'Rusted pipes hang from a low ceiling.')
        self.assertEqual(bottom, 'Four people argue on a metal deck. In the center of the deck a lamp burns.')
        self.assertEqual(book_art.band_prompts('A mine shaft.'), ('A mine shaft.', 'A mine shaft.'))
        self.assertEqual(book_art.band_size((1344, 768)), (1344, 384))
        self.assertEqual(book_art.band_size((100, 1000)), (100, 432))

        def png(color):
            buffer = BytesIO()
            Image.new('RGB', (120, 40), color).save(buffer, 'PNG')
            return buffer.getvalue()
        image = Image.open(BytesIO(book_art.band_compose(png((255, 0, 0)), png((0, 0, 255)), (60, 100), 'white')))
        self.assertEqual(image.size, (60, 100))
        self.assertEqual(image.getpixel((30, 0)), (255, 0, 0))     # ust serit
        self.assertEqual(image.getpixel((30, 99)), (0, 0, 255))    # alt serit
        self.assertEqual(image.getpixel((30, 50)), book_art.BAND_TONES['white'])   # orta zemin
        red = [image.getpixel((30, y))[1] for y in range(0, 40)]
        self.assertEqual(red, sorted(red))   # ortaya dogru zemine solar
        self.assertTrue(0 < image.getpixel((30, 30))[1] < 236)
        self.assertEqual(book_art.band_tone({'modifiers': ['no-faces', 'band-light']}), 'white')
        self.assertIsNone(book_art.band_tone({'modifiers': ['no-faces']}))

    def test_resolve_lora(self):
        names = ['Krea2\\DarkFanKrea2_c1-st3000.safetensors', 'other.safetensors', 'YFG-Fwshn-Krea2_1.8k-v2 (1).safetensors']
        self.assertEqual(comfy_client.resolve_lora(names, 'other.safetensors'), 'other.safetensors')
        self.assertEqual(comfy_client.resolve_lora(names, 'DarkFanKrea2_c1-st3000.safetensors'), names[0])
        self.assertEqual(comfy_client.resolve_lora(['yfg_fwshn_krea2_1.8k_v2.safetensors'], 'YFG-Fwshn-Krea2_1.8k-v2.safetensors'),
                         'yfg_fwshn_krea2_1.8k_v2.safetensors')
        self.assertIsNone(comfy_client.resolve_lora(names, 'missing.safetensors'))


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

    def test_generate_prefers_saved_image(self):
        """F213: PreviewImage'in gecici ciktisi once gelse de SaveImage'inki alinir."""
        fake = FakeComfy()
        self.addCleanup(fake.close)
        fake.preview = True
        comfy_client.generate(fake.url, comfy_client.fill(WORKFLOW, 'scene'))
        view = [path for method, path in fake.calls if path.startswith('/view?')]
        self.assertEqual(len(view), 1)
        self.assertIn('filename=a.png', view[0])
        self.assertIn('type=output', view[0])

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
                return json.dumps({'style': 'muted watercolour', 'characters': [{'name': 'Ana', 'look': 'woman in a red coat'}]})
            first = int(user.split('the first scene starts at ')[1].split(')')[0])
            return json.dumps({'scenes': [{'start': first, 'title': 'T', 'prompt': f'scene {first}'}]})

        saved = []
        plan = book_art.new_plan('daha soyut ol', 'abstract', 'medium', options={'outfits': False})
        result = book_art.plan_book(sections, ask, plan, save=lambda p: saved.append(json.loads(json.dumps(p))))
        self.assertTrue(result['complete'])
        self.assertIn('daha soyut ol', prompts[0])
        self.assertIn('Ana: woman in a red coat', prompts[1])
        self.assertEqual([s['section'] for s in result['scenes']], [1])   # 3 cumlelik bolum sahne almaz
        self.assertEqual(result['scenes'][0]['anchor'], sections[1]['sentences'][0])
        # stil yazilmis, ilk parca bitmis yarim plandan devam: stil yeniden istenmez
        half = next(p for p in saved if p['style'] and p['next_chunk'] == 1)
        prompts.clear()
        book_art.plan_book(sections, ask, half)
        self.assertFalse(any('JSON shape: {"style"' in p for p in prompts))

    def test_age_in_looks(self):
        """F211: yassiz tarif ('Small, slight build') gorsel modelinde cocuk ciziliyordu; istemlerde yetiskin sayilir."""
        tate = {'name': 'Tate', 'look': 'Small, slight build, pale mannequin-like face'}
        self.assertFalse(book_art.has_age(tate['look']))
        for look in ('Middle-aged man, gaunt', 'Girl of about ten', 'woman in her 30s', 'a bulky robot', 'young, thin'):
            self.assertTrue(book_art.has_age(look), look)
        self.assertEqual(book_art.person_look(tate), 'Adult, small, slight build, pale mannequin-like face')
        self.assertEqual(book_art.person_look({'look': 'Boy of about ten'}), 'Boy of about ten')
        fox = {'name': 'Tilki', 'look': 'Slender red fox, bushy tail', 'kind': 'other'}
        self.assertEqual(book_art.person_look(fox), 'Slender red fox, bushy tail')   # insan degil: yetiskin denmez
        self.assertEqual(book_art.clean_characters([fox, {'name': 'A', 'look': 'x', 'kind': 'human'}]),
                         [fox, {'name': 'A', 'look': 'x'}])
        self.assertEqual(book_art.keep_portraits([{'name': 'tilki', 'look': 'fox'}], [fox])[0]['kind'], 'other')
        self.assertIn('Adult, small, slight build', book_art.portrait_prompt(tate))
        self.assertIn('Adult, small', book_art.identity_prompt({'prompt': 'p'}, [tate], 's'))
        self.assertIn('- Tate: Adult, small', book_art.character_lines([tate]))
        self.assertIn('- Maden: rusty shaft', book_art.character_lines([{'name': 'Maden', 'look': 'rusty shaft'}], False))

    def test_plan_book_rewrites_ageless_looks(self):
        sections = book(3, 60)
        prompts = []

        def ask(system, user):
            prompts.append(user)
            if 'JSON shape: {"style"' in user:
                return json.dumps({'style': 's', 'characters': [{'name': 'Tate', 'look': 'Small, slight build'},
                                                                {'name': 'Ana', 'look': 'woman in a red coat'},
                                                                {'name': 'Tilki', 'look': 'Slender, bushy tail'}]})
            if 'do not say the age and sex' in user and 'Tate' in user:
                return json.dumps({'characters': [{'name': 'Tate', 'look': 'Man in his fifties, small, slight build'},
                                                  {'name': 'Tilki', 'look': 'Other red fox, bushy tail', 'kind': 'other'}]})
            if 'do not say the age and sex' in user:
                return json.dumps({'characters': [{'name': 'Bo', 'look': 'tall, thin', 'kind': 'human'}]})
            first = int(user.split('the first scene starts at ')[1].split(')')[0])
            return json.dumps({'scenes': [{'start': first, 'title': 'T', 'prompt': 'p',
                                           'characters': [{'name': 'Bo', 'look': 'tall, thin'}]}]})

        plan = book_art.plan_book(sections, ask, book_art.new_plan(options={'outfits': False}))
        looks = {c['name']: c['look'] for c in plan['characters']}
        self.assertEqual(looks['Tate'], 'Man in his fifties, small, slight build')
        self.assertEqual(looks['Ana'], 'woman in a red coat')
        tilki = next(c for c in plan['characters'] if c['name'] == 'Tilki')
        self.assertEqual((tilki['look'], tilki['kind']), ('Red fox, bushy tail', 'other'))
        self.assertIn('- Tilki: Red fox, bushy tail', book_art.character_lines(plan['characters']))
        age = [p for p in prompts if 'do not say the age and sex' in p]
        self.assertIn('- Tate: Small, slight build', age[0])
        self.assertNotIn('Ana', age[0].split('Rewrite')[0])
        self.assertEqual(len(age), 2)   # stil adiminda Tate, parcada yeni tanitilan Bo
        self.assertEqual(looks['Bo'], 'tall, thin')   # yanit yas vermedi: tarif kalir, istemde yetiskin sayilir
        self.assertIn('- Bo: Adult, tall, thin', book_art.character_lines(plan['characters']))

    def test_same_new_character_in_two_scenes_kept_once(self):
        """F211: ayni parcadaki iki sahne ayni karakteri tanitinca plan iki kez yaziyordu (arayuz cokuyordu)."""
        merged = book_art.merge_characters([{'name': 'Ana', 'look': 'a'}],
                                           [{'name': 'Bo', 'look': '1'}, {'name': 'bo', 'look': '2'},
                                            {'name': 'ANA', 'look': 'x'}])
        self.assertEqual(merged, [{'name': 'Ana', 'look': 'a'}, {'name': 'Bo', 'look': '1'}])
        plan = {'characters': [{'name': 'Jerry', 'look': '1'}, {'name': 'Jerry', 'look': '1'}], 'places': []}
        self.assertTrue(book_art.dedupe_plan(plan))
        self.assertEqual(plan['characters'], [{'name': 'Jerry', 'look': '1'}])
        self.assertFalse(book_art.dedupe_plan(plan))

    def test_presets_and_modifiers(self):
        """F202: LoRA'li tarz plana kopyalanir; secenekler dil modeline kural, gorsel istemine olumlu son ek olur."""
        ids = [p['id'] for p in book_art.PRESETS]
        self.assertEqual(len(ids), len(set(ids)))
        # F224: gruplanmamis on LoRA'siz tarz hep gorunur; LoRA'li tarz gruplanmaz; hicbir not digerinin parcasi
        # degil (arayuz tarz degisince eski notu metinden ayiklar)
        plain = [p for p in book_art.PRESETS if not p.get('lora')]
        self.assertEqual(len([p for p in plain if not p.get('group')]), 10)
        self.assertFalse([p['id'] for p in book_art.PRESETS if p.get('lora') and p.get('group')])
        notes = [p['note'] for p in book_art.PRESETS]
        self.assertFalse([(a, b) for a in notes for b in notes if a != b and a in b])
        self.assertIsNone(book_art.preset_lora('watercolor'))
        self.assertIsNone(book_art.preset_lora('noir'))
        plan = book_art.new_plan('', 'dc-dark-fantasy', identity=True, modifiers=['landscape', 'bilinmeyen', 'no-people'])
        self.assertEqual(plan['modifiers'], ['no-people', 'landscape'])
        self.assertFalse(plan['identity'])   # karakter cizilmeyen secenekte kimlik kapali
        self.assertEqual(plan['lora']['trigger'], 'dcd@rkf@ntsy.')
        self.assertTrue(plan['lora']['lora'].endswith('.safetensors'))
        self.assertEqual(book_art.image_style(plan, 'Oil painting.'), 'dcd@rkf@ntsy. Oil painting.')
        self.assertTrue(book_art.image_suffix(plan).startswith('uninhabited, deserted scene, wide establishing shot'))
        self.assertTrue(book_art.image_suffix(plan).endswith(book_art.SUFFIX))
        self.assertEqual(book_art.image_suffix(plan, book_art.PORTRAIT_SUFFIX, False), book_art.PORTRAIT_SUFFIX)
        band = book_art.new_plan('', 'watercolor', modifiers=['band-light', 'band-dark', 'no-faces'])
        self.assertEqual(band['modifiers'], ['no-faces', 'band-dark'])   # gruptan yalnizca biri
        self.assertIn('wide panoramic strip', book_art.image_suffix(band))
        self.assertIn('stays plain white', book_art.note_text('', ['band-light']))
        plain = book_art.new_plan('', 'watercolor', identity=True, modifiers=['no-faces'])
        self.assertTrue(plain['identity'])
        self.assertEqual((plain['lora'], book_art.image_style(plain, 'Style.')), (None, 'Style.'))
        self.assertIn('Hard rule: Faces are never shown', book_art.refine_prompt('p', 'daha karanlık', ['no-faces'])[1])
        self.assertNotIn('Hard rule', book_art.refine_prompt('p', 'daha karanlık')[1])

        prompts = []

        def ask(system, user):
            prompts.append(user)
            if 'JSON shape: {"style"' in user:
                return json.dumps({'style': 's', 'characters': [{'name': 'Ana', 'look': 'woman in a red coat'}]})
            return json.dumps({'scenes': [{'start': 0, 'title': 'T', 'prompt': 'p',
                                           'characters': [{'name': 'Bo', 'look': 'tall man'}]}]})

        result = book_art.plan_book(book(60), ask, plan)
        self.assertTrue(all('Hard rule: No people' in p and 'Hard rule: Every image is a wide' in p for p in prompts))
        self.assertEqual(result['characters'], [])   # karakter olmasin: tarif tutulmaz

    def test_extra_loras(self):
        """F218: ek LoRA tarzdan bagimsiz plana kopyalanir; tetigi tarzinkinden sonra, son eki yalnizca insanli
        istemde, portrede (extras=False / modifiers=False) hic yok."""
        ids = [p['id'] for p in book_art.PRESETS] + [e['id'] for e in book_art.EXTRA_LORAS]
        self.assertEqual(len(ids), len(set(ids)))
        plan = book_art.new_plan('', 'retro-anime', options={'extras': ['dynamic-poses', 'yok']})
        self.assertEqual([e['id'] for e in plan['extras']], ['dynamic-poses'])
        self.assertEqual([lora['lora'] for lora in book_art.plan_loras(plan)],
                         [plan['lora']['lora'], plan['extras'][0]['lora']])
        self.assertEqual(book_art.image_style(plan, 'Anime.'),
                         'retro_scifi_90s, retro_artstyle, retro, cyberpunk, PoseDaal, Anime.')
        self.assertEqual(book_art.image_style(plan, 'Anime.', False), 'retro_scifi_90s, retro_artstyle, retro, cyberpunk, Anime.')
        self.assertIn('dynamic pose', book_art.image_suffix(plan, prompt='A woman runs through the rain.'))
        self.assertNotIn('dynamic pose', book_art.image_suffix(plan, prompt='An empty street at night.'))
        self.assertNotIn('dynamic pose', book_art.image_suffix(plan, book_art.PORTRAIT_SUFFIX, False))
        plan['extras'][0]['strength'] = 0.6
        self.assertEqual(book_art.extra_loras(['dynamic-poses'], plan['extras'])[0]['strength'], 0.6)
        self.assertEqual(book_art.new_plan('', 'neon-vhs')['extras'], [])
        self.assertEqual(book_art.image_style(book_art.new_plan('', 'neon-vhs'), 'Style.'), 'Style.')

    def test_no_faces_only_for_people(self):
        """F213: "Yuz gosterme" insansiz sahneye figur ekletmez: son ek yalnizca istemde insan varsa, kural dil
        modeline figur eklememesini soyler, yalin olumsuz cumle ("No faces are shown.") atilir."""
        plan = book_art.new_plan('', 'watercolor', modifiers=['no-faces'])
        face = 'back view, every face turned away'
        self.assertNotIn(face, book_art.image_suffix(plan, prompt='An empty study with a heavy oak desk.'))
        self.assertIn(face, book_art.image_suffix(plan, prompt='A man in a grey coat reads a letter.'))
        self.assertIn(face, book_art.image_suffix(plan, prompt='The crowd surges toward the barrier.'))
        self.assertIn(face, book_art.image_suffix(plan))   # istem verilmezse eskisi gibi
        self.assertIn('Never add a person', book_art.note_text('', ['no-faces']))
        self.assertEqual(book_art.strip_negations('A dark room. No faces are shown. Rain on the glass.'),
                         'A dark room. Rain on the glass.')
        kept = 'A void. No stars are visible, only blackness.'
        self.assertEqual(book_art.strip_negations(kept), kept)
        self.assertEqual(book_art.strip_negations('No people.'), 'No people.')   # istemin tamami atilmaz
        raw = json.dumps({'scenes': [{'start': 0, 'title': 't', 'prompt': 'A desk by a window. No faces are shown.'}]})
        self.assertEqual(book_art.parse_scenes(raw, 0, 2, ['a', 'b'])[0][0]['prompt'], 'A desk by a window.')
        character = {'name': 'A', 'look': 'Man in his forties, grey coat'}
        hidden = book_art.identity_prompt({'prompt': 'He walks away.'}, [character], 'Ink.', faces=False)
        self.assertIn('hair, build and clothing', hidden)
        self.assertNotIn('facial identity', hidden)
        self.assertIn('facial identity', book_art.identity_prompt({'prompt': 'He walks away.'}, [character], 'Ink.'))

    def test_no_faces_cleans_prompt(self):
        """F215: son ek kisi adi tasimaz (asagidan gorulen sahneye seyirci kalabaligi ekletiyordu); kurala ragmen
        yazilan kameraya bakis, yuz ifadesi ve gogusten yukari cekim uretimde ayiklanir, kayitli istem degismez."""
        suffix = book_art.image_suffix(book_art.new_plan('', 'watercolor', modifiers=['no-faces']), prompt='A man.')
        self.assertNotRegex(suffix.split(book_art.SUFFIX)[0], r'\b(?:people|figures?|persons?|crowd)\b')
        self.assertIn('chest up', book_art.note_text('', ['no-faces']))
        prompt = ('A woman of about twenty-five; slight build; wearing a cracked helmet stands on the Access Bridge, '
                  'looking toward the camera with an expression of apprehension. She is framed from the chest up, her '
                  'face partially obscured by the angle and shadows. The background shows dark iron railings.')
        self.assertEqual(book_art.hide_faces(prompt),
                         'A woman of about twenty-five; slight build; wearing a cracked helmet stands on the Access '
                         'Bridge, seen from behind. The background shows dark iron railings.')
        cases = {'A woman looks at the camera.': 'A woman turns away from the viewer.',
                 'They turn to face the viewer, silhouetted.': 'They turn away from the viewer, silhouetted.',
                 'Gazing straight into the lens, he waits.': 'Seen from behind, he waits.',
                 'He climbs the sheer rock face, his eyes fixed on the ledge.': 'He climbs the sheer rock face.',
                 'A dark room. Her face is lit by amber light.': 'A dark room.',
                 'She looks at the old map, her back to us.': 'She looks at the old map, her back to us.',
                 'He walks away, his face turned away from the lamp.':
                     'He walks away, his face turned away from the lamp.',
                 'Her eyes.': 'Her eyes.',   # istemin tamami atilmaz
                 # gercek model (gemma-4-26b) ciktisi: tarifteki yuz kalir, yuzun gorunusunu anlatan yan cumle gider
                 'Lincoln Powell, a man in his late thirties with a thin build and a weary face, is seen from behind.':
                     'Lincoln Powell, a man in his late thirties with a thin build and a weary face, is seen from '
                     'behind.',
                 'Ben Reich stands facing him, seen from a low angle that obscures his face, surrounded by teals.':
                     'Ben Reich stands facing him surrounded by teals.',
                 'Jerry Church, seen in profile with his face obscured by deep shadow, leans over the counter.':
                     'Jerry Church leans over the counter.'}
        for source, expected in cases.items():
            self.assertEqual(book_art.hide_faces(source), expected)
        scene = {'prompt': prompt, 'place': ''}
        self.assertEqual(book_art.scene_text({'modifiers': ['no-faces']}, scene), book_art.hide_faces(prompt))
        self.assertEqual(book_art.scene_text({'modifiers': []}, scene), prompt)
        self.assertEqual(scene['prompt'], prompt)

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


class OptionsTest(unittest.TestCase):
    """F209: seyrek siklik ve onemli anlar, bolum acilis gorseli, mekan kimligi, gorunus degisimi, tarz degisikligi."""

    @staticmethod
    def style_reply(user, **extra):
        return json.dumps(dict({'style': 'muted watercolour', 'characters': [{'name': 'Ana', 'look': 'woman in a red coat'}]},
                               **extra))

    def test_density_levels(self):
        self.assertEqual(list(book_art.DENSITY), ['sparse', 'rare', 'low', 'medium', 'high'])
        self.assertEqual([book_art.focused(d) for d in book_art.DENSITY], [True, True, True, False, False])
        self.assertEqual([book_art.selective(d) for d in book_art.DENSITY], [True, True, False, False, False])
        self.assertEqual(book_art.scene_count(14000, 'rare'), 3)     # adaylar: 14000 * 3 / 20000 yukari
        self.assertEqual(book_art.scene_count(14000, 'sparse'), 1)
        self.assertEqual(book_art.scene_count(200, 'sparse'), 0)
        system, user = book_art.scene_prompt('s', [], ['a', 'b', 'c'], 0, 3, 2, focus=True)
        self.assertIn('moments of it that matter most', user)
        self.assertIn('"importance"', user)
        self.assertNotIn('Split it at', user)

    def test_focused_scene_not_pulled_to_chunk_start(self):
        raw = json.dumps({'scenes': [{'start': 5, 'title': 'T', 'prompt': 'p', 'importance': '8.6'},
                                     {'start': 7, 'title': 'U', 'prompt': 'q', 'importance': 'çok'}]})
        sentences = [f's{i}' for i in range(10)]
        scenes = book_art.parse_scenes(raw, 2, 10, sentences, first=False)[0]
        self.assertEqual([(s['start'], s['importance']) for s in scenes], [(5, 9), (7, 5)])
        self.assertEqual(book_art.parse_scenes(raw, 2, 10, sentences)[0][0]['start'], 2)

    def test_select_moments(self):
        candidates = [{'pos': 0, 'importance': 3}, {'pos': 100, 'importance': 9}, {'pos': 120, 'importance': 8},
                      {'pos': 900, 'importance': 7}]
        self.assertEqual([c['pos'] for c in book_art.select_moments(candidates, 2, 300)], [100, 900])
        # aralik birakan aday kalmazsa aralik gozetilmeden, yine onem sirasiyla tamamlanir
        self.assertEqual([c['pos'] for c in book_art.select_moments(candidates, 3, 300)], [100, 120, 900])
        self.assertEqual(len(book_art.select_moments(candidates, 9, 300)), 4)
        # esit puanda secilmislere en uzak olan: gorseller kitabin basina yigilmaz
        flat = [{'pos': pos, 'importance': 9} for pos in range(0, 1100, 100)]
        self.assertEqual([c['pos'] for c in book_art.select_moments(flat, 3, 0)], [0, 500, 1000])

    def test_sparse_plan_picks_most_important(self):
        sections = book(400)   # ~40 bin karakter, 3 parca
        prompts = []

        def ask(system, user):
            prompts.append(user)
            if 'JSON shape: {"style"' in user:
                return self.style_reply(user)
            first = int(user.split('number of the sentence where the moment begins (')[1].split(' ')[0])
            # her parcada iki aday: ikinci parcanin ortasindaki an en onemlisi
            return json.dumps({'scenes': [{'start': first + 3, 'title': 'A', 'prompt': f'a{first}', 'importance': 4},
                                          {'start': first + 60, 'title': 'B', 'prompt': f'b{first}',
                                           'importance': 9 if first else 6}]})

        saved = []
        plan = book_art.new_plan(density='rare', options={'outfits': False})
        result = book_art.plan_book(sections, ask, plan, save=lambda p: saved.append(json.loads(json.dumps(p))))
        self.assertTrue(result['complete'])
        self.assertTrue(all('moments of it that matter most' in p for p in prompts[1:]))
        self.assertEqual(len(result['scenes']), 2)   # 40 bin / 20 bin
        self.assertTrue(all(s['importance'] == 9 for s in result['scenes']), result['scenes'])
        self.assertNotIn('candidates', result)
        self.assertTrue(all('pos' not in s and s['seed'] and s['start'] > 0 for s in result['scenes']))
        self.assertEqual([s['start'] for s in result['scenes']], sorted(s['start'] for s in result['scenes']))
        # yarim plan adaylari saklar, kaldigi yerden surer
        half = next(p for p in saved if p['next_chunk'] == 1)
        self.assertEqual(len(half['candidates']), 2)
        prompts.clear()
        again = book_art.plan_book(sections, ask, half)
        self.assertEqual(len(prompts), 2)
        self.assertEqual(len(again['scenes']), 2)

    def test_chapter_openers(self):
        sections = book(1, 60, 60, 60)
        prompts, openings = [], []

        def ask(system, user):
            prompts.append(user)
            if 'JSON shape: {"style"' in user:
                return self.style_reply(user)
            if 'first page of a chapter' in user:
                openings.append(user)
                if 'Bölüm 2 ' in user:
                    return json.dumps({'skip': True})   # hikaye disi sayfa
                return json.dumps({'title': 'Açılış', 'prompt': 'A wide valley at dawn.'})
            first = int((user.split('the first scene starts at ')[1:] or ['0)'])[0].split(')')[0])
            return json.dumps({'scenes': [{'start': first, 'title': 'T', 'prompt': f'scene {first}',
                                           'importance': 5}]})

        saved = []
        result = book_art.plan_book(sections, ask, book_art.new_plan(options={'openers': True}),
                                    save=lambda plan: saved.append(json.loads(json.dumps(plan))))
        # kisa bolum (0) sorulmaz; acilis istegi yalnizca ilk sayfayi gorur (spoiler yok)
        self.assertEqual(len(openings), 3)
        self.assertTrue(all('\n15: ' in p and '\n16: ' not in p and '"skip": true' in p for p in openings))
        scenes = [(s['id'], s['start'], bool(s.get('opening'))) for s in result['scenes']]
        self.assertEqual(scenes, [('1-open', 0, True), ('1-1', 1, False), ('2-0', 0, False),
                                  ('3-open', 0, True), ('3-1', 1, False)])
        self.assertEqual(result['opening_skipped'], [2])
        self.assertIn('sentence 1 or later', next(p for p in prompts if '\n0: Bölüm 1 cümle 0' in p
                                                  and 'first page of a chapter' not in p))
        here, _carry = book_art.section_images(
            {'scenes': [dict(s, image='x.png') for s in reversed(result['scenes'])]}, 1)
        self.assertTrue(here[0]['opening'])
        # yeniden baslatmada var olan ve atlanan acilislar bir daha sorulmaz
        openings.clear()
        half = next(p for p in saved if p['next_chunk'] == 3)
        book_art.plan_book(sections, ask, half)
        self.assertEqual(len(openings), 1)
        # cok seyrekte de her bolumun acilisi var
        sparse = book_art.plan_book(sections, ask, book_art.new_plan(density='sparse', options={'openers': True}))
        self.assertEqual([s['id'] for s in sparse['scenes'] if s.get('opening')], ['1-open', '3-open'])
        # sahne alamayacak kadar kisa bolum de acilir
        short = book_art.plan_book(book(4), ask, book_art.new_plan(options={'openers': True}))
        self.assertEqual([s['id'] for s in short['scenes']], ['0-open'])
        # kapaliyken istemde yok
        prompts.clear()
        book_art.plan_book(sections, ask, book_art.new_plan())
        self.assertFalse(any('first page' in p or 'own image' in p for p in prompts))

    def test_add_openers_to_existing_plan(self):
        sections = [dict(s, number=n + 2) for n, s in enumerate(book(1, 60, 60, 60))]
        asked = []

        def ask(system, user):
            if 'JSON shape: {"style"' in user:
                return self.style_reply(user)
            if 'first page of a chapter' in user:
                asked.append(user)
                return json.dumps({'title': 'Açılış', 'prompt': 'A quiet harbour.'})
            return json.dumps({'scenes': [{'start': 0 if '0: Bölüm 3 ' in user else 5, 'title': 'T', 'prompt': 'p'}]})

        plan = book_art.plan_book(sections, ask, book_art.new_plan(density='low'))
        self.assertFalse(any(s.get('opening') for s in plan['scenes']))
        book_art.add_openers(sections, ask, plan)
        # bolum 5'in (metinde 'Bölüm 3') ilk cumlesinde zaten sahne var: sorulmaz; kisa bolum (2) sorulmaz
        self.assertEqual(len(asked), 2)
        self.assertTrue(plan['openers'])
        self.assertEqual([(s['id'], s['section']) for s in plan['scenes']],
                         [('3-open', 3), ('3-5', 3), ('4-open', 4), ('4-5', 4), ('5-0', 5)])
        asked.clear()
        book_art.add_openers(sections, ask, plan)
        self.assertEqual(asked, [])

    def test_place_identity(self):
        prompts = []

        def ask(system, user):
            prompts.append(user)
            if 'JSON shape: {"style"' in user:
                return self.style_reply(user, places=[{'name': 'Maden', 'look': 'rusty steel shaft with hazard lamps'}])
            return json.dumps({'scenes': [{'start': 0, 'title': 'T', 'prompt': 'Two miners wait.', 'place': 'Maden',
                                           'places': [{'name': 'Köy', 'look': 'stone houses on a hill'}]}]})

        plan = book_art.plan_book(book(60), ask, book_art.new_plan(options={'places': True, 'outfits': False}))
        self.assertIn('3. "places"', prompts[0])
        self.assertIn('- Maden: rusty steel shaft', prompts[1])
        self.assertEqual([p['name'] for p in plan['places']], ['Maden', 'Köy'])
        scene = plan['scenes'][0]
        self.assertEqual(scene['place'], 'Maden')
        self.assertEqual(book_art.scene_text(plan, scene),
                         'Two miners wait. Setting: rusty steel shaft with hazard lamps.')
        self.assertEqual(book_art.scene_text(dict(plan, place_identity=False), scene), 'Two miners wait.')
        prompts.clear()
        book_art.plan_book(book(60), ask, book_art.new_plan(options={'outfits': False}))
        self.assertFalse(any('"place"' in p or '"places"' in p for p in prompts))

    def test_look_changes(self):
        sections = book(150, 150)
        prompts = []

        def ask(system, user):
            prompts.append(user)
            if 'JSON shape: {"style"' in user:
                return self.style_reply(user)
            first = int(user.split('the first scene starts at ')[1].split(')')[0])
            reply = {'scenes': [{'start': first, 'title': 'T', 'prompt': 'p'}]}
            if first == 0 and '- Ana: woman in a red coat' in user:
                reply['changes'] = [{'name': 'Ana', 'start': 2, 'look': 'grey-haired woman in a black uniform'},
                                    {'name': 'Yok', 'start': 2, 'look': 'x'}, {'name': 'Ana', 'start': 9999, 'look': 'y'}]
            return json.dumps(reply)

        plan = book_art.plan_book(sections, ask, book_art.new_plan(options={'changes': True, 'outfits': False}))
        self.assertIn('"changes"', prompts[1])
        ana = plan['characters'][0]
        self.assertEqual(ana['changes'], [{'section': 0, 'start': 2, 'look': 'grey-haired woman in a black uniform'}])
        self.assertIn('- Ana: grey-haired woman in a black uniform', prompts[-1])   # sonraki bolumde yeni gorunus
        self.assertEqual(book_art.look_at(ana, 0, 1), 'woman in a red coat')
        self.assertEqual(book_art.look_at(ana, 1, 0), 'grey-haired woman in a black uniform')
        scene = {'section': 1, 'start': 0, 'prompt': 'A grey-haired woman in a black uniform walks.'}
        self.assertEqual(book_art.scene_people(scene, plan['characters'])[0]['look'], ana['changes'][0]['look'])
        # kutudan duzenleme degisimleri korur, karakter olmasin secenegiyle kapali
        self.assertEqual(book_art.clean_characters([dict(ana)])[0]['changes'], ana['changes'])
        self.assertFalse(book_art.new_plan(modifiers=['no-people'], options={'changes': True})['look_changes'])

    def test_restyle_and_upscale_values(self):
        system, user = book_art.restyle_prompt('Oil painting, warm light.', 'kara kalem eskiz', ['no-faces'])
        self.assertIn('ignore its medium, technique, colour palette and lighting):\nOil painting, warm light.', user)
        # dunya cumlesi kodda eklenir (model eski teknigi karistirmasin); zaten varsa iki kez yazilmaz
        raw = json.dumps({'world': 'Near-future mining colony.', 'style': 'Pencil sketch on rough paper.'})
        self.assertEqual(book_art.parse_restyle(raw), 'Pencil sketch on rough paper. Near-future mining colony.')
        raw = json.dumps({'world': 'Mining colony', 'style': 'Pencil sketch of a mining colony.'})
        self.assertEqual(book_art.parse_restyle(raw), 'Pencil sketch of a mining colony.')
        self.assertRaises(ValueError, book_art.parse_restyle, '{"world": "x"}')
        self.assertIn('"kara kalem eskiz"', user)
        self.assertIn('Hard rule: Faces', user)
        plan = book_art.restyle(book_art.new_plan('eski', 'watercolor'), 'dark-fantasy', 'karanlık')
        self.assertEqual((plan['preset'], plan['note'], plan['lora']['trigger']),
                         ('dark-fantasy', 'karanlık', 'Dark Fantasy Art Style,'))
        self.assertEqual([book_art.clean_upscale(v) for v in (2, '3', 5, None, 'x')], [2.0, 3.0, 0, 0, 0])
        workflow = comfy_client.upscale_workflow('aktar-x.png', 2)
        self.assertEqual(workflow['2']['class_type'], 'RTXVideoSuperResolution')
        self.assertEqual(workflow['2']['inputs']['resize_type.scale'], 2.0)
        self.assertEqual(workflow['3']['inputs']['images'], ['2', 0])


class OutfitTest(unittest.TestCase):
    """F219: kiyafet tariften ayri; uretimde kodla eklenir, kalici ve o ana ait degisimler algilanir."""

    def plan(self, **values):
        plan = book_art.new_plan()
        plan.update(style='s', characters=[
            {'name': 'Ana', 'look': 'Woman of about thirty, red hair, freckles', 'outfit': 'green wool coat',
             'outfits': [{'section': 2, 'start': 5, 'outfit': 'grey prison uniform'}]},
            {'name': 'Bo', 'look': 'Man in his fifties, bald', 'outfit': 'black suit'}], **values)
        return plan

    def test_old_prompts_unchanged_when_off(self):
        system, user = book_art.style_prompt('ornek')
        self.assertIn('(15-35 words: age, build, face, hair, clothing) so they', user)
        self.assertIn('[{"name": "...", "look": "..."}]}', user)
        self.assertNotIn('outfit', user)
        user = book_art.scene_prompt('s', [{'name': 'Ana', 'look': 'woman', 'outfit': 'coat'}], ['a', 'b'], 0, 2, 1,
                                     changes=True)[1]
        self.assertIn('copy its look into the prompt word for word):', user)
        self.assertIn('new clothes or uniform', user)
        self.assertNotIn('Clothing now', user)
        self.assertNotIn('"cast"', user)
        self.assertNotIn('outfit', user)
        self.assertNotIn('outfit', book_art.opening_prompt('s', [], ['a'])[1])

    def test_prompts_ask_for_outfits(self):
        user = book_art.style_prompt('ornek', outfits=True)[1]
        self.assertIn('hair) so they', user)
        self.assertIn('"outfit": the ONE set of clothing they usually wear', user)
        self.assertIn('"look": "...", "outfit": "..."}]}', user)
        people = book_art.characters_at(self.plan()['characters'], 2, 7)
        user = book_art.scene_prompt('s', people, ['a', 'b'], 0, 2, 1, changes=True, outfits=True)[1]
        self.assertIn('never describe the clothing of a recurring character', user)
        self.assertIn('- Ana: Woman of about thirty, red hair, freckles. Clothing now: grey prison uniform', user)
        self.assertNotIn('"outfits"', user)   # kiyafet degisimi ayri soruda
        self.assertIn('new characters in "characters" also get "outfit"', user)
        self.assertIn('- "cast": names of the recurring characters visible', user)
        self.assertNotIn('new clothes or uniform', user)   # kiyafet gorunus degisimi sayilmaz
        self.assertIn('"characters": [], "cast": [], "changes": []}]}', user)
        user = book_art.opening_prompt('s', people, ['a'], outfits=True)[1]
        self.assertIn('never describe the clothing of a recurring character', user)
        self.assertNotIn('new characters in', user)
        self.assertIn('"prompt": "...", "cast": []}', user)

    def test_outfit_change_question(self):
        """Kiyafet degisimi parca basina ayri soruda: kalici olan karakterin, o ana ait olan sahnenin kiyafeti."""
        plan = self.plan()
        ana = plan['characters'][0]
        prompts = []

        def ask(system, user):
            prompts.append(user)
            return json.dumps({'changes': [
                {'name': 'ana', 'from': 12, 'wear': 'white nightgown', 'keep': False, 'until': 14},
                {'name': 'Bo', 'from': 15, 'wear': 'diving suit', 'keep': 'false', 'until': 99},
                {'name': 'Ana', 'from': 16, 'wear': 'green wool coat again', 'keep': True},
                {'name': 'Kim', 'from': 12, 'wear': 'x', 'keep': True},
                {'name': 'Ana', 'from': 3, 'wear': 'outside the part', 'keep': True}]})

        changes = book_art.outfit_changes(plan, ask, [f's{i}' for i in range(30)], 2, 10, 20)
        self.assertIn('- Ana: grey prison uniform (earlier in the book: green wool coat)\n- Bo: black suit\n',
                      prompts[0])
        self.assertIn('10: s10\n', prompts[0])
        self.assertNotIn('9: s9', prompts[0])
        self.assertEqual(changes, [
            {'name': 'Ana', 'from': 12, 'wear': 'white nightgown', 'keep': False, 'until': 14},
            {'name': 'Bo', 'from': 15, 'wear': 'diving suit', 'keep': False, 'until': 19},   # parcanin sonu
            {'name': 'Ana', 'from': 16, 'wear': 'green wool coat again', 'keep': True, 'until': None}])
        scenes = [{'section': 2, 'start': at, 'prompt': 'p'} for at in (10, 13, 15, 17)]
        scenes[1]['outfits'] = {'Ana': 'elle yazilan'}
        book_art.apply_outfit_changes(plan, changes, 2, scenes, 20)
        self.assertEqual([s.get('outfits') for s in scenes],
                         [None, {'Ana': 'elle yazilan'}, {'Bo': 'diving suit'}, {'Bo': 'diving suit'}])
        # 16. cumledeki degisim 15-16 sahnesinin ilk yarisinda: o sahneden sayilir; 12 ise 10-12'nin ikinci yarisinda
        self.assertEqual(book_art.outfit_at(ana, 2, 15), 'green wool coat again')
        self.assertEqual(book_art.outfit_at(ana, 2, 14), 'grey prison uniform')
        night = [{'section': 0, 'start': at, 'prompt': 'p'} for at in (0, 17, 23)]
        book_art.apply_outfit_changes(plan, [{'name': 'Ana', 'from': 18, 'wear': 'nightgown', 'keep': False,
                                              'until': 22}], 0, night, 30)
        self.assertEqual([s.get('outfits') for s in night], [None, {'Ana': 'nightgown'}, None])
        self.assertEqual(book_art.outfit_changes(plan, lambda s, u: 'bozuk', ['a'], 0, 0, 1), [])
        self.assertEqual(book_art.clean_scene_outfits({'bo': ' x ', 'Kim': 'y'}, plan['characters']), {'Bo': 'x'})

    def test_outfit_at_and_scene_people(self):
        ana = self.plan()['characters'][0]
        self.assertEqual(book_art.outfit_at(ana, 2, 4), 'green wool coat')
        self.assertEqual(book_art.outfit_at(ana, 2, 5), 'grey prison uniform')
        self.assertEqual(book_art.outfit_at({'name': 'X', 'look': 'y'}, 0), '')
        self.assertNotIn('outfit', book_art.characters_at([{'name': 'X', 'look': 'y'}], 0)[0])
        scene = {'section': 3, 'start': 0, 'prompt': 'p', 'cast': ['Ana', 'Bo'], 'outfits': {'bo': 'pyjamas'}}
        people = book_art.scene_people(scene, self.plan()['characters'])
        self.assertEqual([c['outfit'] for c in people], ['grey prison uniform', 'pyjamas'])
        self.assertEqual(book_art.clean_scene_outfits({'bo': ' pyjamas ', 'Kim': 'x', 'Ana': ''},
                                                      self.plan()['characters']), {'Bo': 'pyjamas'})

    def test_clothing_added_to_prompt(self):
        plan = self.plan()
        scene = {'section': 1, 'start': 0, 'prompt': 'A woman of about thirty argues with a bald man.',
                 'cast': ['Ana', 'Bo'], 'outfits': {'Bo': 'striped pyjamas'}}
        self.assertEqual(book_art.scene_text(plan, scene),
                         'A woman of about thirty argues with a bald man. Clothing: the woman of about thirty wears '
                         'green wool coat; the man in his fifties wears striped pyjamas.')
        self.assertEqual(book_art.scene_text(plan, scene, ['ana']),
                         'A woman of about thirty argues with a bald man. Clothing: the man in his fifties wears '
                         'striped pyjamas.')
        old = dict(plan)
        old.pop('outfits')
        self.assertEqual(book_art.scene_text(old, scene), scene['prompt'])   # eski plan: istem birebir
        # orta bos seridi: yalnizca bu parcada gecen karakterin kiyafeti (ust seride insan cizilmesin)
        top = dict(scene, prompt='Rusted pipes and a grey sky overhead.')
        bottom = dict(scene, prompt='A woman of about thirty, red hair, freckles kneels on the floor.')
        self.assertEqual(book_art.scene_text(plan, top, part=True), top['prompt'])
        self.assertTrue(book_art.scene_text(plan, bottom, part=True).endswith(
            'Clothing: the woman of about thirty wears green wool coat.'))
        lonely = {'section': 1, 'start': 0, 'prompt': 'An empty hall.', 'cast': []}
        self.assertEqual(book_art.scene_text(plan, lonely), 'An empty hall.')
        self.assertEqual(book_art._who({'look': 'Small, slight build, pale face'}), 'the adult, small, slight build')
        self.assertEqual((book_art._lower('A navy coat'), book_art._lower('RAF uniform')), ('a navy coat', 'RAF uniform'))
        self.assertEqual(book_art._lower('Fully dressed in business attire'), 'business attire')   # fiil atilir
        self.assertEqual(book_art._lower('Wearing a dress'), 'a dress')
        twins = dict(plan, characters=[{'name': 'Ben', 'look': 'Man in his fifties, bald, sharp nose', 'outfit': 'robe'},
                                       {'name': 'Tate', 'look': 'Man in his fifties, small build', 'outfit': 'suit'}])
        self.assertEqual(book_art.clothing_text(twins, dict(lonely, cast=['Ben', 'Tate'])),
                         'Clothing: the man in his fifties, bald, sharp nose wears robe; '
                         'the man in his fifties, small build wears suit.')   # ayni kisa tarif uzar

    def test_portrait_and_identity_use_outfit(self):
        ana, bo = self.plan()['characters']
        self.assertIn('freckles, wearing green wool coat. Plain', book_art.portrait_prompt(ana))
        self.assertIn('Woman of about thirty. Plain', book_art.portrait_prompt({'name': 'A', 'look': 'Woman of about thirty'}))
        text = book_art.identity_prompt({'prompt': 'p'}, [dict(bo, outfit='pyjamas')], 's', False, True)
        self.assertIn('bald, wearing pyjamas', text)
        self.assertIn('Preserve the hair and build of the reference portrait', text)
        worn = book_art.identity_prompt({'prompt': 'p'}, [bo], 's', False, True, True)   # F220 tam boy referans
        self.assertIn('Preserve the hair, build and clothing of the reference image', worn)
        self.assertNotIn('clothing follows the description', worn)
        self.assertIn('Each person from the references appears only once.', worn)   # F221
        self.assertIn('facial expression follow the scene, not the reference.',
                      book_art.identity_prompt({'prompt': 'p'}, [bo], 's', True, True, True))
        self.assertIn('Bare head: no helmet', book_art.body_prompt(bo, 's'))
        key = book_art.body_key(bo)
        with mock.patch.object(book_art, 'BODY_VERSION', book_art.BODY_VERSION + 1):
            self.assertNotEqual(book_art.body_key(bo), key)   # istem degisince eski referans yenilenir
        self.assertNotEqual(book_art.body_key(bo), book_art.body_key(dict(bo, outfit='pyjamas')))
        self.assertIn('The clothing follows the description above, not the reference.', text)
        old = book_art.identity_prompt({'prompt': 'p'}, [bo], 's', False)
        self.assertIn('hair, build and clothing', old)
        self.assertNotIn('wearing', old)

    def test_characters_keep_outfits(self):
        ana = self.plan()['characters'][0]
        self.assertEqual(book_art.clean_characters([ana]), [ana])
        self.assertEqual(book_art.keep_portraits(book_art.clean_characters([ana]), [dict(ana, portrait='p.png')])[0]
                         ['outfits'], ana['outfits'])

    def test_plan_book_detects_outfit_changes(self):
        sections = book(3, 300)
        prompts = []

        def ask(system, user):
            prompts.append(user)
            if 'JSON shape: {"style"' in user:
                return json.dumps({'style': 's', 'characters': [
                    {'name': 'Ana', 'look': 'Woman of about thirty, red hair', 'outfit': 'green wool coat'}]})
            if 'do not say the age and sex' in user:
                return '{"characters": []}'
            if 'have no clothing description yet' in user:
                return json.dumps({'characters': [{'name': 'Bo', 'outfit': 'blue overalls'}]})
            if 'puts on different clothing' in user:   # parcanin kiyafet degisimleri
                if '\n0: ' not in user:
                    return '{"changes": []}'
                self.assertIn('- Bo: blue overalls\n', user)   # eksik kiyafet degisim sorusundan once yazildi
                return json.dumps({'changes': [
                    {'name': 'Ana', 'from': 0, 'wear': 'white nightgown', 'keep': False, 'until': 5},
                    {'name': 'Ana', 'from': 40, 'wear': 'grey prison uniform', 'keep': True}]})
            first = int(user.split('the first scene starts at ')[1].split(')')[0])
            if first:
                return json.dumps({'scenes': [{'start': first, 'title': 'T', 'prompt': 'later', 'cast': ['Ana']}]})
            return json.dumps({'scenes': [
                {'start': 0, 'title': 'Gece', 'prompt': 'night', 'cast': ['Ana']},
                {'start': 20, 'title': 'Sabah', 'prompt': 'morning', 'cast': ['Ana']},
                {'start': 40, 'title': 'Hapis', 'prompt': 'cell', 'cast': ['Ana'],
                 'characters': [{'name': 'Gardiyan', 'look': 'Man in his forties', 'outfit': 'blue uniform'},
                                {'name': 'Bo', 'look': 'Man in his twenties'}]}]})

        plan = book_art.plan_book(sections, ask, book_art.new_plan())
        self.assertTrue(plan['outfits'])
        ana = plan['characters'][0]
        self.assertEqual(ana['outfits'], [{'section': 1, 'start': 40, 'outfit': 'grey prison uniform'}])
        self.assertEqual(plan['characters'][1]['outfit'], 'blue uniform')
        self.assertEqual(plan['characters'][2]['outfit'], 'blue overalls')   # kiyafetsiz yeni karakter soruldu
        self.assertEqual(sum('have no clothing description yet' in p for p in prompts), 1)
        scenes = {scene['title']: scene for scene in plan['scenes']}
        self.assertEqual(scenes['Gece']['outfits'], {'Ana': 'white nightgown'})
        for title, outfit in (('Gece', 'white nightgown'), ('Sabah', 'green wool coat'),
                              ('Hapis', 'grey prison uniform')):
            self.assertEqual(book_art.clothing_text(plan, scenes[title]),
                             f'Clothing: the woman of about thirty wears {outfit}.', title)
        later = [p for p in prompts if 'the first scene starts at' in p and 'starts at 0)' not in p]
        self.assertIn('Clothing now: grey prison uniform', later[0])   # sonraki parca yeni kiyafeti bilir
        self.assertEqual(sum('puts on different clothing' in p for p in prompts), 3)   # parca basina bir soru


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
                                                  'created': plan['created'], 'failed': 0, 'errors': 0})
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

    def test_lora_preset_generation(self):
        """F202: LoRA ComfyUI'de yoksa uretim baslamaz; varsa is akisina eklenir, tetik kelimesi istemin basinda."""
        main = dict(WORKFLOW, **{'2': dict(WORKFLOW['2'], inputs=dict(WORKFLOW['2']['inputs'], model=['1', 0])),
                                 '1': {'inputs': {'unet_name': 'krea2.safetensors'}, 'class_type': 'UNETLoader'}})
        source = Path(self.tmp.name) / 'akis-lora.json'
        source.write_text(json.dumps(main), encoding='utf-8')
        self.assertTrue(self.bridge.art_set_workflow(str(source))['ok'])
        store = self.bridge._art_store()
        plan = book_art.new_plan('', 'dc-colossal-future', modifiers=['no-faces'])
        plan.update(complete=True, style='Matte painting.')
        plan['scenes'] = [{'id': '1-0', 'section': 1, 'start': 0, 'anchor': 'a', 'title': 'Şehir', 'seed': 5,
                           'prompt': 'A vast city.', 'image': '', 'skip': False}]
        store.save('ab12cd34ef', plan)
        file = plan['lora']['lora']

        self.assertIn('models/loras', self.bridge.art_generate('ab12cd34ef')['error'])
        self.assertFalse(self.bridge.art_lora_check('dc-colossal-future')['ok'])
        self.assertTrue(self.bridge.art_lora_check('watercolor')['ok'])
        self.fake.loras = ['other.safetensors', 'Krea2/' + file]
        self.assertTrue(self.bridge.art_lora_check('dc-colossal-future')['ok'])
        self.assertEqual(self.bridge.art_plan_save('ab12cd34ef', {'lora_strength': 0.75})['plan']['lora']['strength'], 0.75)
        self.assertTrue(self.bridge.art_generate('ab12cd34ef')['started'])
        self.assertEqual(self.finish()['done'], 1)
        sent = self.fake.prompts[0]
        self.assertEqual(sent['2']['inputs']['model'], ['aktar-lora-0-0', 0])
        self.assertEqual(sent['aktar-lora-0-0']['inputs']['lora_name'], 'Krea2/' + file)
        self.assertEqual(sent['aktar-lora-0-0']['inputs']['strength_model'], 0.75)
        self.assertEqual(sent['96']['inputs']['positive'], 'DCC0LFUT. Matte painting.')
        # F213: insansiz sahneye "arkadan gorulen kisiler" son eki gitmez (gorsel modeli siluet ekliyordu)
        self.assertEqual(sent['98']['inputs']['positive'], book_art.SUFFIX)

    def test_extra_lora_generation(self):
        """F218: ek LoRA tarzin LoRA'sinin arkasina eklenir; dosyasi yoksa uretim baslamaz; plan kaydinda acilir,
        kapanir, gucu degisir."""
        main = dict(WORKFLOW, **{'2': dict(WORKFLOW['2'], inputs=dict(WORKFLOW['2']['inputs'], model=['1', 0])),
                                 '1': {'inputs': {'unet_name': 'krea2.safetensors'}, 'class_type': 'UNETLoader'}})
        source = Path(self.tmp.name) / 'akis-lora.json'
        source.write_text(json.dumps(main), encoding='utf-8')
        self.assertTrue(self.bridge.art_set_workflow(str(source))['ok'])
        store = self.bridge._art_store()
        plan = book_art.new_plan('', '80s-fantasy', options={'extras': ['dynamic-poses']})
        plan.update(complete=True, style='Film still.')
        plan['scenes'] = [{'id': '1-0', 'section': 1, 'start': 0, 'anchor': 'a', 'title': 'Dövüş', 'seed': 5,
                           'prompt': 'A knight swings his sword.', 'image': '', 'skip': False}]
        store.save('ab12cd34ef', plan)
        style_file, extra_file = plan['lora']['lora'], plan['extras'][0]['lora']
        self.fake.loras = [style_file]
        error = self.bridge.art_generate('ab12cd34ef')['error']
        self.assertIn('Dinamik pozlar', error)
        self.assertFalse(self.bridge.art_lora_check('dynamic-poses')['ok'])
        self.fake.loras = [style_file, extra_file]
        self.assertTrue(self.bridge.art_lora_check('dynamic-poses')['ok'])
        saved = self.bridge.art_plan_save('ab12cd34ef', {'extra_strength': ['dynamic-poses', 0.6]})['plan']
        self.assertEqual(saved['extras'][0]['strength'], 0.6)
        self.assertTrue(self.bridge.art_generate('ab12cd34ef')['started'])
        self.assertEqual(self.finish()['done'], 1)
        sent = self.fake.prompts[0]
        self.assertEqual(sent['2']['inputs']['model'], ['aktar-lora-0-1', 0])
        self.assertEqual(sent['aktar-lora-0-0']['inputs']['lora_name'], style_file)
        self.assertEqual(sent['aktar-lora-0-1']['inputs']['lora_name'], extra_file)
        self.assertEqual(sent['aktar-lora-0-1']['inputs']['strength_model'], 0.6)
        self.assertEqual(sent['96']['inputs']['positive'], 'ArsMovieStill, 80s Fantasy Movie Still, PoseDaal, Film still.')
        self.assertTrue(sent['98']['inputs']['positive'].startswith('dynamic pose'))
        self.assertEqual(self.bridge.art_plan_save('ab12cd34ef', {'extras': []})['plan']['extras'], [])

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

    def test_duplicate_characters_repaired_on_read(self):
        store = self.bridge._art_store()
        plan = book_art.new_plan()
        plan['complete'] = True
        plan['characters'] = [{'name': 'Chooka', 'look': 'Man, 1'}, {'name': 'Chooka', 'look': 'Man, 2'}]
        store.save('ab12cd34ef', plan)
        shown = self.bridge.art_plan_get('ab12cd34ef')['plan']
        self.assertEqual([c['look'] for c in shown['characters']], ['Man, 1'])
        self.assertEqual(len(store.load('ab12cd34ef')['characters']), 1)

    def test_scene_carries_book_chapter_title(self):
        """F211: kartta okuyucunun sira numarasi yerine kitabin icindekilerdeki bolum adi."""
        store = self.bridge._art_store()
        plan = book_art.new_plan()
        plan['complete'] = True
        plan['scenes'] = [{'id': f'{n}-open', 'section': n, 'start': 0, 'anchor': 'a', 'opening': True, 'image': '',
                           'skip': False} for n in (6, 7, 8)]
        store.save('ab12cd34ef', plan)

        class Epub:
            toc = [{'section': 6, 'title': 'Sunuş'}, {'section': 8, 'title': '1'}, {'section': 8, 'title': 'Alt'}]

        class Shelf:
            def _book(self, book_id):
                return {}, Epub()

        self.bridge._shelf = lambda: Shelf()
        scenes = self.bridge.art_plan_get('ab12cd34ef')['plan']['scenes']
        self.assertEqual([s.get('chapter') for s in scenes], ['Sunuş', None, '1'])

    def test_restyle_keeps_prompts(self):
        """F209: tarz degisince istemler ve seed'ler kalir; stil kilavuzu dil modeliyle yeniden yazilir, LoRA plana."""
        from unittest.mock import patch
        store = self.identity_plan(identity=False)
        asked = []

        class FakeClient:
            def __init__(self, cfg, log=None):
                self.cfg = {'model': 'sohbet'}

            def chat(self, messages, temperature=None, max_tokens=None):
                asked.append(messages[1]['content'])
                return '{"style": "Pencil sketch, cross-hatching, sepia paper."}'

        before = store.load('ab12cd34ef')
        self.assertIn('error', self.bridge.art_restyle('ab12cd34ef', '', ''))
        with patch('app_core.Client', FakeClient), patch('app_core.load_config', return_value={}), \
                patch('app_core.keep_loaded', return_value=['sohbet:1']), patch('app_core.unload_models'):
            plan = self.bridge.art_restyle('ab12cd34ef', 'krea-sketching', 'kara kalem')['plan']
            self.assertIn('Rusty mine, fog', asked[0])   # eski stil kilavuzu dil modeline gider
            self.assertEqual(plan['style'], 'Pencil sketch, cross-hatching, sepia paper.')
            self.assertEqual(plan['lora']['trigger'], 'Bradhamel art style.')
            self.assertEqual([(s['prompt'], s['seed']) for s in plan['scenes']],
                             [(s['prompt'], s['seed']) for s in before['scenes']])
            # yeniden yazmadan: stil aynen kalir, yalnizca tarz degisir
            plain = self.bridge.art_restyle('ab12cd34ef', 'watercolor', 'suluboya', False)['plan']
        self.assertEqual(len(asked), 1)
        self.assertEqual((plain['style'], plain['preset'], plain['lora']), (plan['style'], 'watercolor', None))

    def test_upscale_after_generation(self):
        """F209: buyutme aciksa uretilen gorsel geri yuklenip RTX is akisiyla buyutulur; dugum yoksa baslamaz."""
        store = self.identity_plan(identity=False)
        self.assertEqual(self.bridge.art_plan_save('ab12cd34ef', {'upscale': 2})['plan']['upscale'], 2.0)
        self.assertIn('Nvidia RTX Nodes', self.bridge.art_generate('ab12cd34ef')['error'])
        self.assertFalse(self.bridge.art_upscale_check()['ok'])
        self.fake.rtx = True
        self.assertTrue(self.bridge.art_upscale_check()['ok'])
        self.assertTrue(self.bridge.art_generate('ab12cd34ef')['started'])
        self.assertEqual(self.finish()['done'], 2)
        kinds = [next(iter({n['class_type'] for n in sent.values()} & {'KSampler', 'RTXVideoSuperResolution'}))
                 for sent in self.fake.prompts]
        self.assertEqual(kinds, ['KSampler', 'RTXVideoSuperResolution'] * 2)
        self.assertEqual(self.fake.prompts[1]['2']['inputs']['resize_type.scale'], 2.0)
        self.assertEqual(len(self.fake.uploads), 2)
        self.assertTrue(all(s['upscaled'] == 2.0 for s in store.load('ab12cd34ef')['scenes']))
        self.assertEqual(book_art.not_upscaled(store.load('ab12cd34ef')), [])
        # katsayi degisince var olanlar yeniden uretilmeden aradaki fark kadar buyur
        self.bridge.art_plan_save('ab12cd34ef', {'upscale': 3})
        self.fake.prompts.clear()
        self.assertTrue(self.bridge.art_generate('ab12cd34ef', upscale_only=True)['started'])
        self.assertEqual(self.finish()['done'], 2)
        self.assertEqual([sent['2']['inputs']['resize_type.scale'] for sent in self.fake.prompts], [1.5, 1.5])
        self.assertTrue(all(s['upscaled'] == 3.0 for s in store.load('ab12cd34ef')['scenes']))
        self.bridge.art_plan_save('ab12cd34ef', {'upscale': 0})
        self.assertIn('kapalı', self.bridge.art_generate('ab12cd34ef', upscale_only=True)['error'])

    def test_place_text_sent_to_comfy(self):
        store = self.identity_plan(identity=False)
        store.update('ab12cd34ef', lambda p: p.update(place_identity=True,
                                                      places=[{'name': 'Maden', 'look': 'rusty shaft'}]))
        self.bridge.art_scene_update('ab12cd34ef', '1-9', {'place': 'Maden'})
        self.assertTrue(self.bridge.art_generate('ab12cd34ef', ['1-9'])['started'])
        self.finish()
        self.assertEqual(self.fake.prompts[0]['97']['inputs']['positive'], 'An empty mine shaft. Setting: rusty shaft.')
        cleared = self.bridge.art_scene_update('ab12cd34ef', '1-9', {'place': ''})['plan']['scenes'][1]
        self.assertNotIn('place', cleared)

    def test_outfit_sent_to_comfy(self):
        """F219: sahnedeki karakterin kiyafeti isteme eklenir; sahneye ozel kiyafet arayuzden degistirilir."""
        store = self.identity_plan(identity=False)
        store.update('ab12cd34ef', lambda p: p['characters'][0].update(
            look='Young woman, short black hair', outfit='scuffed white jumpsuit'))
        updated = self.bridge.art_scene_update('ab12cd34ef', '1-0', {'outfits': {'sekai': 'orange spacesuit'},
                                                                      'cast': ['Sekai']})
        self.assertEqual(updated['plan']['scenes'][0]['clothing'],
                         [{'name': 'Sekai', 'outfit': 'orange spacesuit', 'own': True}])
        self.assertTrue(self.bridge.art_generate('ab12cd34ef', ['1-0'])['started'])
        self.finish()
        self.assertTrue(self.fake.prompts[0]['97']['inputs']['positive'].endswith(
            'ledge. Clothing: the young woman, short black hair wears orange spacesuit.'))
        cleared = self.bridge.art_scene_update('ab12cd34ef', '1-0', {'outfits': {}})['plan']['scenes'][0]
        self.assertNotIn('outfits', cleared)
        self.assertEqual(cleared['clothing'], [{'name': 'Sekai', 'outfit': 'scuffed white jumpsuit', 'own': False}])

    def test_body_reference_per_outfit(self):
        """F220: kiyafet basina tam boy referans portreden uretilir, sahne portre yerine onunla cizilir; kiyafet
        degisince yeni referans, portre yenilenince hepsi yenilenir."""
        store = self.identity_plan()
        source = Path(self.tmp.name) / 'kimlik.json'
        source.write_text(json.dumps(IDENTITY), encoding='utf-8')
        self.bridge.art_set_workflow(str(source), 'identity')
        store.update('ab12cd34ef', lambda p: (p.update(bodies=True), p['scenes'][0].update(cast=['Sekai']),
                                              p['characters'][0].update(look='Young woman, short black hair',
                                                                        outfit='scuffed white jumpsuit')))
        self.assertEqual(self.bridge.art_generate('ab12cd34ef', ['1-0'])['total'], 3)   # portre + tam boy + sahne
        self.assertEqual(self.finish()['done'], 3)
        portrait, body, scene = self.fake.prompts
        self.assertIn('97', portrait)
        self.assertTrue(body['9']['inputs']['prompt'].startswith(
            'Create a full-body character reference of this person: Young woman, short black hair, wearing scuffed '
            'white jumpsuit.'))
        self.assertEqual((body['7']['inputs']['width'], body['7']['inputs']['height']), book_art.BODY_SIZE)
        plan = store.load('ab12cd34ef')
        sekai = plan['characters'][0]
        self.assertEqual(body['5']['inputs']['image'], f'aktar-ab12cd34ef-{sekai["portrait"]}')
        [entry] = sekai['bodies']
        self.assertEqual(entry['from'], sekai['portrait'])
        self.assertEqual(scene['5']['inputs']['image'], f'aktar-ab12cd34ef-{entry["file"]}')
        self.assertIn('Preserve the exact facial identity, hair, build and clothing of the reference image',
                      scene['9']['inputs']['prompt'])
        self.assertNotIn('clothing follows the description', scene['9']['inputs']['prompt'])
        view = self.bridge.art_plan_get('ab12cd34ef')['plan']
        self.assertEqual(len(view['characters'][0]['body_urls']), 1)

        # var olan referans yeniden uretilmez; sahneye ozel kiyafet ikinci referans ister, ilki kalir
        self.assertEqual(self.bridge.art_generate('ab12cd34ef', ['1-0'])['total'], 1)
        self.finish()
        self.bridge.art_scene_update('ab12cd34ef', '1-0', {'outfits': {'Sekai': 'orange spacesuit'}})
        self.assertEqual(self.bridge.art_generate('ab12cd34ef', ['1-0'])['total'], 2)
        self.finish()
        self.assertIn('wearing orange spacesuit', self.fake.prompts[-2]['9']['inputs']['prompt'])
        files = [e['file'] for e in store.load('ab12cd34ef')['characters'][0]['bodies']]
        self.assertEqual(len(files), 1)   # planda artik gerekmeyen jumpsuit referansi silindi
        self.assertFalse((store.folder('ab12cd34ef') / entry['file']).exists())

        # yalnizca tam boy referansi yeni seed ile: sahne uretilmez
        old = store.load('ab12cd34ef')['characters'][0]['bodies'][0]
        self.assertEqual(self.bridge.art_generate('ab12cd34ef', bodies=['sekai'])['total'], 1)
        self.finish()
        new = store.load('ab12cd34ef')['characters'][0]['bodies'][0]
        self.assertNotEqual((new['file'], new['seed']), (old['file'], old['seed']))
        self.assertFalse((store.folder('ab12cd34ef') / old['file']).exists())

        # portre yenilenince tam boy da yenilenir; kapatilinca sahne portreyle
        self.assertEqual(self.bridge.art_generate('ab12cd34ef', ['1-0'], portraits=['Sekai'])['total'], 3)
        self.finish()
        sekai = store.load('ab12cd34ef')['characters'][0]
        self.assertEqual(sekai['bodies'][0]['from'], sekai['portrait'])
        self.bridge.art_plan_save('ab12cd34ef', {'bodies': False})
        self.bridge.art_generate('ab12cd34ef', ['1-0'])
        self.finish()
        self.assertEqual(self.fake.prompts[-1]['5']['inputs']['image'], f'aktar-ab12cd34ef-{sekai["portrait"]}')
        self.assertNotIn('body_urls', self.bridge.art_plan_get('ab12cd34ef')['plan']['characters'][0])
        self.bridge.art_portrait_clear('ab12cd34ef', 'Sekai')
        self.assertFalse(list(store.folder('ab12cd34ef').glob('boy-*')))

    def test_place_image_reference(self):
        """F222: mekan gorseli once ana is akisiyla uretilir; tek kisilik sahnede ilk yuvaya mekan, ikinciye kisi
        (tek referansli Krea2Edit is akisina ikinci yuva eklenir), kisisiz sahnede yalnizca mekan; tarif degisince
        yenilenir; mekan kimligi tarifi istemde kalir."""
        store = self.identity_plan()
        edit = dict(IDENTITY)
        edit['6'] = {'inputs': {'pixels': ['5', 0], 'vae': ['3', 0]}, 'class_type': 'VAEEncode', '_meta': {'title': 'E'}}
        edit['8'] = {'inputs': {'model': ['4', 0], 'source_latent': ['6', 0], 'vae': ['3', 0], 'source_image': ['5', 0],
                                'ref_position_a': 'aligned (trained)'}, 'class_type': 'Krea2EditModelPatch',
                     '_meta': {'title': 'Patch'}}
        source = Path(self.tmp.name) / 'kimlik.json'
        source.write_text(json.dumps(edit), encoding='utf-8')
        self.bridge.art_set_workflow(str(source), 'identity')
        store.update('ab12cd34ef', lambda p: (
            p.update(place_identity=True, place_images=True,
                     places=[{'name': 'Maden', 'look': 'Rusty steel catwalks over a dark shaft'}]),
            p['scenes'][0].update(place='Maden', cast=['Sekai']), p['scenes'][1].update(place='maden')))
        self.assertEqual(self.bridge.art_generate('ab12cd34ef')['total'], 4)   # mekan + portre + iki sahne
        self.assertEqual(self.finish()['done'], 4)
        place, portrait, scene, empty = self.fake.prompts
        self.assertTrue(place['97']['inputs']['positive'].startswith(
            'Establishing wide shot of a location: Rusty steel catwalks over a dark shaft.'))
        plan = store.load('ab12cd34ef')
        spot = plan['places'][0]
        self.assertTrue((store.folder('ab12cd34ef') / spot['image']).is_file())
        sekai = plan['characters'][0]
        self.assertEqual(scene['5']['inputs']['image'], f'aktar-ab12cd34ef-{spot["image"]}')   # ilk yuva mekan
        self.assertEqual(scene['aktar_ref_b']['inputs']['image'], f'aktar-ab12cd34ef-{sekai["portrait"]}')
        self.assertEqual(scene['8']['inputs']['source_latent_b'], ['aktar_ref_b_latent', 0])
        self.assertEqual(scene['8']['inputs']['source_image_b'], ['aktar_ref_b', 0])
        self.assertEqual(scene['9']['inputs']['image_b'], ['aktar_ref_b', 0])
        self.assertTrue(scene['9']['inputs']['prompt'].startswith('Create an illustration of the person from '
                                                                  'reference 2 (a young woman'))
        self.assertIn('Setting: Rusty steel catwalks', scene['9']['inputs']['prompt'])   # tarif de kalir
        self.assertNotIn('aktar_ref_b', empty)
        self.assertEqual(empty['5']['inputs']['image'], f'aktar-ab12cd34ef-{spot["image"]}')
        self.assertTrue(empty['9']['inputs']['prompt'].startswith('Create an illustration set in the place'))
        self.assertTrue(self.bridge.art_plan_get('ab12cd34ef')['plan']['places'][0]['image_url'])

        # tarif elle degisince gorsel kalir ama gecersiz: sonraki uretim yeniler; places=[ad] yeni seed
        saved = self.bridge.art_plan_save('ab12cd34ef', {'places': [{'name': 'Maden', 'look': 'Flooded mine hall'}]})
        self.assertEqual(saved['plan']['places'][0]['image_url'], '')
        self.assertEqual(self.bridge.art_generate('ab12cd34ef', ['1-9'])['total'], 2)
        self.finish()
        old = store.load('ab12cd34ef')['places'][0]
        self.assertFalse((store.folder('ab12cd34ef') / spot['image']).exists())
        self.assertEqual(self.bridge.art_generate('ab12cd34ef', places=['maden'])['total'], 1)
        self.finish()
        new = store.load('ab12cd34ef')['places'][0]
        self.assertNotEqual((new['image'], new['image_seed']), (old['image'], old['image_seed']))

        # kapaliyken eski akis: mekan yalnizca tarifle, kisi tek referansla
        self.bridge.art_plan_save('ab12cd34ef', {'place_images': False})
        self.bridge.art_generate('ab12cd34ef', ['1-0'])
        self.finish()
        self.assertNotIn('aktar_ref_b', self.fake.prompts[-1])
        self.assertEqual(self.fake.prompts[-1]['5']['inputs']['image'], f'aktar-ab12cd34ef-{sekai["portrait"]}')
        self.assertNotIn('image_url', self.bridge.art_plan_get('ab12cd34ef')['plan']['places'][0])

    def test_second_reference_needs_krea2edit(self):
        self.assertIsNone(comfy_client.with_second_reference(IDENTITY))   # Krea2Edit dugumu yok
        two = dict(IDENTITY, b={'inputs': {'image': 'x.png'}, 'class_type': 'LoadImage', '_meta': {'title': 'REFERENCE-B'}})
        self.assertIs(comfy_client.with_second_reference(two), two)

    def test_body_reference_follows_slots(self):
        """F220: tek referansli is akisinda yalnizca ilk kisi kimlikle cizilir, ikinciye tam boy uretilmez;
        kiyafeti olmayan (giysisi tarifinde) portresiyle kalir."""
        store = self.identity_plan()
        source = Path(self.tmp.name) / 'kimlik.json'
        source.write_text(json.dumps(IDENTITY), encoding='utf-8')
        self.bridge.art_set_workflow(str(source), 'identity')
        store.update('ab12cd34ef', lambda p: (p.update(bodies=True), p['scenes'][0].update(cast=['Bot', 'Sekai']),
                                              p['characters'][0].update(outfit='scuffed white jumpsuit'),
                                              p['characters'].append({'name': 'Bot', 'look': 'Security robot, '
                                                                      'matte black armour'})))
        self.assertEqual(self.bridge.art_generate('ab12cd34ef', ['1-0'])['total'], 3)   # iki portre + sahne
        self.finish()
        self.assertFalse(store.load('ab12cd34ef')['characters'][0].get('bodies'))
        scene = self.fake.prompts[-1]
        self.assertTrue(scene['5']['inputs']['image'].endswith(store.load('ab12cd34ef')['characters'][1]['portrait']))
        self.assertIn('Preserve the exact facial identity of the reference portrait', scene['9']['inputs']['prompt'])

    def test_band_two_strips(self):
        """F217: orta bos secenegi her sahneyi iki seritte (ust, alt) uretir, gecisle tek gorselde birlestirir."""
        from io import BytesIO
        from PIL import Image
        buffer = BytesIO()
        Image.new('RGB', (1344, 384), (200, 30, 30)).save(buffer, 'PNG')
        self.fake.image = buffer.getvalue()
        store = self.identity_plan(identity=False)
        store.update('ab12cd34ef', lambda p: p.update(modifiers=['band-dark']))
        self.bridge.art_scene_update('ab12cd34ef', '1-9', {
            'prompt': 'Top: Rusted pipes overhead. Bottom: A flooded mine floor. The middle is an empty gradient.'})
        self.assertTrue(self.bridge.art_generate('ab12cd34ef', ['1-9'])['started'])
        self.finish()
        top, bottom = self.fake.prompts
        self.assertEqual((top['97']['inputs']['positive'], bottom['97']['inputs']['positive']),
                         ('Rusted pipes overhead.', 'A flooded mine floor.'))
        self.assertTrue(top['98']['inputs']['positive'].startswith(book_art.BAND_TOP + ', wide panoramic strip'))
        self.assertTrue(bottom['98']['inputs']['positive'].startswith(book_art.BAND_BOTTOM))
        self.assertEqual((top['106:10']['inputs']['width'], top['106:10']['inputs']['height']), (1344, 384))
        self.assertEqual((top['2']['inputs']['seed'], bottom['2']['inputs']['seed']), (6, 7))
        self.assertTrue(top['33']['inputs']['filename_prefix'].endswith('1-9-ust'))
        scene = store.scene(store.load('ab12cd34ef'), '1-9')
        image = Image.open(store.image_path('ab12cd34ef', scene))
        self.assertEqual(image.size, (1344, 768))
        self.assertEqual(image.getpixel((600, 5)), (200, 30, 30))
        self.assertEqual(image.getpixel((600, 384)), book_art.BAND_TONES['black'])

    def test_one_failed_image_does_not_stop_queue(self):
        """F214: tek gorselin hatasi kalanlari durdurmaz; hata sahnede kalir, yeniden uretilince silinir."""
        self.identity_plan(identity=False)
        self.fake.fail = 'first'
        self.assertTrue(self.bridge.art_generate('ab12cd34ef')['started'])
        done = self.finish()
        self.assertEqual((done['done'], done['failed']), (1, 1), done)
        scenes = self.bridge.art_plan_get('ab12cd34ef')['plan']['scenes']
        self.assertIn('out of memory', scenes[0]['error'])
        self.assertTrue(scenes[1]['url'])
        self.fake.fail = None
        self.assertTrue(self.bridge.art_generate('ab12cd34ef')['started'])
        self.assertEqual(self.finish()['done'], 1)
        self.assertNotIn('error', self.bridge.art_plan_get('ab12cd34ef')['plan']['scenes'][0])
        # art arda hatalar ComfyUI'nin kendisidir: is durur
        from unittest.mock import patch
        import bridge_art
        self.fake.fail = 'run'
        with patch.object(bridge_art, 'STOP_AFTER', 2):
            self.assertTrue(self.bridge.art_generate('ab12cd34ef', all_scenes=True)['started'])
            self.assertIn('out of memory', self.finish()['error'])

    def test_failed_replan_keeps_old_images(self):
        from unittest.mock import patch
        self.identity_plan(identity=False)
        self.assertTrue(self.bridge.art_generate('ab12cd34ef', ['1-0'])['started'])
        self.finish()

        class DeadClient:
            def __init__(self, cfg, log=None):
                self.cfg = {'model': 'sohbet'}

            def chat(self, messages, temperature=None, max_tokens=None):
                raise RuntimeError('Model sunucusuna bağlanılamadı')

        with patch('app_core.Client', DeadClient), patch('app_core.load_config', return_value={}), \
                patch('app_core.keep_loaded', return_value=[]), patch('app_core.unload_models'):
            self.assertTrue(self.bridge.art_plan_create('ab12cd34ef', book(2, 50), title='Kitap')['started'])
            self.assertIn('bağlanılamadı', self.finish()['error'])
        plan = self.bridge.art_plan_get('ab12cd34ef')['plan']
        self.assertEqual(plan['scenes'][0]['title'], 'Kurtarma')
        self.assertTrue(plan['scenes'][0]['url'])

    def test_no_edits_while_planning(self):
        from unittest.mock import patch
        self.identity_plan(identity=False)
        with patch.object(type(self.bridge), '_art_planning', return_value=True):
            self.assertIn('error', self.bridge.art_plan_save('ab12cd34ef', {'style': 'New.'}))
            self.assertIn('error', self.bridge.art_scene_update('ab12cd34ef', '1-0', {'title': 'X'}))
        self.assertEqual(self.bridge.art_plan_save('ab12cd34ef', {'style': 'New.'})['plan']['style'], 'New.')


class RobustnessTest(unittest.TestCase):
    """F214: dil modeli ve ComfyUI hatalarinda plan ve gorseller kaybolmaz."""

    @staticmethod
    def style_reply(_user=''):
        return json.dumps({'style': 'Ink drawing.', 'characters': []})

    def test_json_object_tolerates_chatter(self):
        good = {'scenes': [{'start': 0, 'title': 'a', 'prompt': 'A man.'}]}
        text = json.dumps(good)
        self.assertEqual(book_art._json_object(text + '\nNote: I used {start} numbering.'), good)
        self.assertEqual(book_art._json_object('Here {x}: ' + text), good)
        self.assertEqual(book_art._json_object(text + ' {"x": 1}'), good)
        self.assertEqual(book_art._json_object('{"scenes": [{"start": 0, "prompt": "A man."},]}')['scenes'][0]['start'], 0)
        # kapanmamis dusunme blogundaki ornek nesne sayilmaz; kapanisi olan dusunmeden sonraki yanit alinir
        self.assertIsNone(book_art._json_object('<think>plan: {"start": 3}'))
        self.assertEqual(book_art._json_object('thinking {"start": 9} ...</think>' + text), good)

    def test_ask_json_retries(self):
        replies = iter(['Sorry, here it is', ValueError('Yanıt token sınırında kesildi'), '{"style": "x"}'])
        asked = []

        def ask(system, user):
            asked.append(user)
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

        self.assertEqual(book_art.ask_json(ask, 's', 'u'), '{"style": "x"}')
        self.assertEqual(asked[0], 'u')
        self.assertTrue(asked[1].endswith(book_art.JSON_REMINDER))
        with self.assertRaises(ValueError):
            book_art.ask_json(lambda s, u: 'no json', 's', 'u')
        with self.assertRaises(RuntimeError):   # baglanti hatasi yeniden denenmez
            book_art.ask_json(lambda s, u: (_ for _ in ()).throw(RuntimeError('down')), 's', 'u')

    def test_unreadable_opening_not_skipped_forever(self):
        sections = book(1, 60)
        broken = {'on': True}

        def ask(system, user):
            if 'JSON shape: {"style"' in user:
                return self.style_reply()
            if 'first page of a chapter' in user:
                return 'I cannot decide.' if broken['on'] else json.dumps({'title': 'A', 'prompt': 'A quiet harbour.'})
            first = int(user.split('number of the sentence where the moment begins (')[1].split(' ')[0])
            return json.dumps({'scenes': [{'start': first + 5, 'title': 'T', 'prompt': 'p'}]})

        plan = book_art.plan_book(sections, ask, book_art.new_plan(density='low', options={'openers': True}))
        self.assertNotIn(1, plan.get('opening_skipped') or [])
        self.assertFalse(any(s.get('opening') for s in plan['scenes']))
        broken['on'] = False
        book_art.add_openers(sections, ask, plan)   # sonra yeniden sorulur
        self.assertEqual([s['id'] for s in plan['scenes'] if s.get('opening')], ['1-open'])

    def test_unreadable_chunk_reported_and_retried(self):
        sections = book(60, 60)
        broken = {'on': True}

        def ask(system, user):
            if 'JSON shape: {"style"' in user:
                return self.style_reply()
            first = int(user.split('the first scene starts at ')[1].split(')')[0])
            if broken['on'] and 'Bölüm 1 ' in user:
                raise ValueError('Yanıt token sınırında kesildi; eksik çeviri kabul edilmedi.')
            return json.dumps({'scenes': [{'start': first, 'title': 'T', 'prompt': f'scene {first}'}]})

        plan = book_art.plan_book(sections, ask, book_art.new_plan())
        self.assertTrue(plan['complete'])   # bir parca plani durdurmaz
        self.assertEqual([(f['section'], f['start']) for f in plan['failed']], [(1, 0)])
        self.assertEqual(book_art.summary(plan)['failed'], 1)
        self.assertEqual({s['section'] for s in plan['scenes']}, {0})
        broken['on'] = False
        plan = book_art.plan_book(sections, ask, plan)   # yeniden dene: yalnizca okunamayan parca sorulur
        self.assertNotIn('failed', plan)
        self.assertEqual(sorted({s['section'] for s in plan['scenes']}), [0, 1])

    def test_digest_covers_every_section(self):
        sections = [{'sentences': [f'Bölüm {i} cümlesi. ' + 'x' * 400]} for i in range(200)]
        sample = book_art.digest(sections)
        self.assertLessEqual(len(sample), book_art.DIGEST_CHARS + 5 * 200)   # ayraclar
        self.assertIn('Bölüm 0 ', sample)
        self.assertIn('Bölüm 199 ', sample)
        short = book_art.digest(book(3, 4))   # kisa kitap tamamen girer
        self.assertIn('Bölüm 1 cümle 3', short)

    def test_replan_failure_restores_old_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            store = book_art.Store(folder)
            plan = book_art.new_plan()
            plan.update(complete=True, scenes=[{'id': '0-0', 'section': 0, 'start': 0, 'anchor': 'a', 'title': 'T',
                                                'prompt': 'p', 'seed': 1, 'image': '', 'skip': False}])
            store.save('ab12cd34', plan)
            store.write_image('ab12cd34', '0-0', PNG)
            store.stash('ab12cd34')
            self.assertIsNone(store.load('ab12cd34'))
            self.assertEqual(store.books(), [])   # yedek klasoru kitap sayilmaz
            self.assertTrue(store.restore('ab12cd34'))   # yeni plan kaydedilmeden basarisiz oldu
            restored = store.load('ab12cd34')
            self.assertTrue(store.image_path('ab12cd34', restored['scenes'][0]).is_file())
            # yeni plan kaydedildiyse eskisi geri gelmez, tamamlaninca yedek silinir
            store.stash('ab12cd34')
            store.save('ab12cd34', book_art.new_plan())
            self.assertFalse(store.restore('ab12cd34'))
            store.drop_backup('ab12cd34')
            self.assertFalse(store.backup_folder('ab12cd34').exists())

    def test_cache_not_shared_with_saved_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            store = book_art.Store(folder)
            plan = book_art.new_plan()
            store.save('ab12cd34', plan)
            plan['scenes'].append({'id': 'x'})   # plan isi kendi nesnesini degistirmeye devam eder
            self.assertEqual(store.load('ab12cd34')['scenes'], [])


class GenerateRobustnessTest(unittest.TestCase):
    def test_poll_miss_and_queue_wait(self):
        from unittest.mock import patch
        calls = {'history': 0, 'queue': 0}

        def fake_json(url, path, body=None, timeout=30):
            if path == '/prompt':
                return {'prompt_id': 'p1'}
            if path == '/queue':
                calls['queue'] += 1
                return {'queue_pending': [[1, 'p1', {}]]} if calls['queue'] < 3 else {'queue_pending': []}
            calls['history'] += 1
            if calls['history'] == 1:
                raise comfy_client.ComfyError('zaman aşımı')
            return {'p1': {'status': {'status_str': 'success', 'completed': True},
                           'outputs': {'9': {'images': [{'filename': 'a.png', 'type': 'output'}]}}}}

        with patch.object(comfy_client, '_json', fake_json), patch.object(comfy_client, '_request', return_value=PNG), \
                patch.object(comfy_client, 'POLL', 0.01):
            self.assertEqual(comfy_client.generate('http://x', WORKFLOW, threading.Event(), timeout=0.001), PNG)
        self.assertEqual(calls['queue'], 2)

        def dead(url, path, body=None, timeout=30):
            if path == '/prompt':
                return {'prompt_id': 'p1'}
            raise comfy_client.ComfyError('bağlanılamadı')

        with patch.object(comfy_client, '_json', dead), patch.object(comfy_client, 'POLL', 0.01), \
                patch.object(comfy_client, 'interrupt'):
            with self.assertRaisesRegex(comfy_client.ComfyError, 'bağlanılamadı'):
                comfy_client.generate('http://x', WORKFLOW, threading.Event())


if __name__ == '__main__':
    unittest.main()
