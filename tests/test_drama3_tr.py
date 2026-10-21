import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))

import json
import os
from pathlib import Path
import py_compile
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

import drama3_tr
from tts import Engines

REPO = Path(__file__).resolve().parents[1]

# Sahte sunucu: gercek server.py ile ayni satirlari yazar ve ayni API'yi sunar; istekleri requests.jsonl'e kaydeder.
FAKE_SERVER = textwrap.dedent('''
    import argparse, array, io, json, os, sys, wave
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    p = argparse.ArgumentParser()
    p.add_argument('--folder'); p.add_argument('--port', type=int); p.add_argument('--speaker')
    a = p.parse_args()
    if os.path.exists(os.path.join(a.folder, 'crash')):
        print('Traceback: CUDA out of memory', flush=True)
        sys.exit(1)
    print('AKTAR STAGE Drama 3 TR: model yukleniyor', flush=True)

    def clip(seconds):
        rate = 44100
        samples = array.array('h', ((8000 if (i // 110) % 2 else -8000) for i in range(int(rate * seconds))))
        samples += array.array('h', bytes(2 * int(rate * 0.1)))
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate); out.writeframes(samples.tobytes())
        return buffer.getvalue()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x): pass
        def _send(self, code, body):
            self.send_response(code); self.send_header('Content-Length', str(len(body))); self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            self._send(200, json.dumps({'status': 'healthy', 'pid': os.getpid()}).encode())
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            body['pid'] = os.getpid()
            with open(os.path.join(a.folder, 'requests.jsonl'), 'a', encoding='utf-8') as log:
                log.write(json.dumps(body, ensure_ascii=False) + '\\n')
            self._send(200, clip(1.0))

    server = ThreadingHTTPServer(('127.0.0.1', a.port), H)
    print('AKTAR READY', a.port, flush=True)
    server.serve_forever()
''')


def make_folder(root):
    """drama-3-tr klasoru duzeni (dosyalar bos)."""
    root = Path(root)
    for name in drama3_tr.REQUIRED:
        path = root / name
        if '.' in path.name:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'')
        else:
            path.mkdir(parents=True, exist_ok=True)
    python = root / drama3_tr.PYTHONS[0]
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b'')
    return root


class FolderTests(unittest.TestCase):
    def test_empty_and_missing(self):
        self.assertFalse(drama3_tr.check_folder('')['ok'])
        self.assertIn('bulunamadı', drama3_tr.check_folder('Z:/yok/drama-3-tr')['message'])
        with tempfile.TemporaryDirectory() as temp:
            state = drama3_tr.check_folder(temp)
            self.assertFalse(state['ok'])
            self.assertIn('models/drama-3/codec.pth', state['missing'])
            self.assertIn('.venv (Python ortamı)', state['missing'])

    def test_complete_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            make_folder(temp)
            state = drama3_tr.check_folder(temp)
            self.assertTrue(state['ok'], state)
            self.assertEqual(Path(state['python']), Path(temp) / drama3_tr.PYTHONS[0])

    def test_settings(self):
        manifest = json.loads((REPO / 'engines' / 'drama3-tr' / 'motor.json').read_text(encoding='utf-8'))
        shown = {item['key']: (item['default'], item['min'], item['max']) for item in manifest['settings']}
        self.assertEqual(shown, drama3_tr.SETTINGS)
        prefs = {'engine_settings': {'drama3-tr': {'max_chars': '90', 'cfg': 9, 'temperature': 'x'}}}
        engine = drama3_tr.Engine(tempfile.gettempdir(), prefs=lambda: prefs)
        self.assertEqual(engine.settings(), {'max_chars': 90, 'cfg': 6.0, 'temperature': 1.0})

    def test_server_script_compiles(self):
        py_compile.compile(str(REPO / 'engines' / 'drama3-tr' / 'server.py'), doraise=True,
                           cfile=os.path.join(tempfile.gettempdir(), 'drama3_tr_server.pyc'))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = make_folder(Path(self.temp.name) / 'model')
        self.script = Path(self.temp.name) / 'fake_server.py'
        self.script.write_text(FAKE_SERVER, encoding='utf-8')

    def test_start_speak_stop(self):
        server = drama3_tr.Server(self.folder, sys.executable, self.script)
        self.addCleanup(server.stop)
        stages = []
        server.start()
        server.wait_ready(timeout=30, on_stage=stages.append)
        if os.name == 'nt':
            self.assertIsNotNone(server._job)    # Aktar cokse de surec is nesnesiyle kapanir
            self.assertIsNone(server.process.stdin)   # stdin borusu yok: okuyan is parcacigi torch'u kilitliyordu
        data = drama3_tr.speech(server.url, 'Merhaba.', {'key': 'k', 'path': 'p.wav', 'text': 'Selam.'},
                                {'cfg': 4.0, 'temperature': 1.0})
        self.assertTrue(data.startswith(b'RIFF'))
        sent = json.loads((self.folder / 'requests.jsonl').read_text(encoding='utf-8').splitlines()[0])
        self.assertEqual((sent['text'], sent['reference']['key'], sent['cfg'], sent['top_p']),
                         ('Merhaba.', 'k', 4.0, drama3_tr.TOP_P))
        process = server.process
        server.stop()
        self.assertIsNotNone(process.poll())
        self.assertFalse(server.alive)

    @unittest.skipIf(os.name == 'nt', 'Windows: is nesnesi; stdin okuyan is parcacigi torch import unu kilitliyordu')
    def test_server_script_exits_when_aktar_pipe_closes(self):
        # gercek sunucu betigi: Aktar kapanir ya da cokerse stdin borusu kapanir, sunucu kendini kapatir
        import subprocess
        code = ('import runpy, sys, time; sys.argv = ["server.py"]; '
                f'ns = runpy.run_path({str(REPO / "engines" / "drama3-tr" / "server.py")!r}, run_name="aktar_test"); '
                'ns["exit_with_aktar"](); time.sleep(30)')
        process = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        time.sleep(0.5)
        self.assertIsNone(process.poll())
        process.stdin.close()
        self.assertEqual(process.wait(10), 0)

    def test_child_env_drops_aktar_paths(self):
        # F176: Whisper'in CUDA 12 klasorleri ve Aktar'in kendi klasorleri sunucunun PATH'inde kalmaz
        import types
        cuda = os.path.abspath(os.path.join(self.temp.name, 'cuda12'))
        own = str(REPO / 'bin')
        other = os.path.abspath(os.path.join(self.temp.name, 'diger'))
        path = os.pathsep.join([cuda, own, other])
        with patch.dict(os.environ, {'PATH': path, 'PYTHONHOME': 'x', '_PYI_APPLICATION_HOME_DIR': 'y'}), \
                patch.dict(sys.modules, {'speech': types.SimpleNamespace(_cuda_dirs_added=[Path(cuda)])}):
            env = drama3_tr.child_env()
        path_key = next(key for key in env if key.upper() == 'PATH')
        self.assertEqual(env[path_key].split(os.pathsep), [other])
        self.assertNotIn('PYTHONHOME', env)
        self.assertNotIn('_PYI_APPLICATION_HOME_DIR', env)
        self.assertEqual(env['PYTHONUNBUFFERED'], '1')

    def test_crash_before_ready_shows_output(self):
        (self.folder / 'crash').write_text('', encoding='utf-8')
        server = drama3_tr.Server(self.folder, sys.executable, self.script)
        self.addCleanup(server.stop)
        server.start()
        with self.assertRaises(drama3_tr.ServerError) as caught:
            server.wait_ready(timeout=30)
        self.assertIn('CUDA out of memory', str(caught.exception))


class BuiltinEngineTests(unittest.TestCase):
    """tts.Engines engines/drama3-tr/motor.json'i yerlesik motor olarak calistirir; sunucu sahte betikle baslar."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.folder = make_folder(root / 'model')
        script = root / 'fake_server.py'
        script.write_text(FAKE_SERVER, encoding='utf-8')
        self.prefs = {drama3_tr.PREF_DIR: str(self.folder), 'voices': {'tr': 'drama3-tr/clone'},
                      'options': {'drama3-tr/clone': {'reference': 'C:/ses/a.wav', 'reference_text': 'Bir.'}}}
        self.engines = Engines(root / 'app', REPO / 'engines', prefs=lambda: self.prefs)
        self.addCleanup(self.engines.shutdown)
        for target, value in (('drama3_tr.python_path', lambda _folder: Path(sys.executable)),
                              ('drama3_tr.Engine._server_script', lambda _self: script),
                              ('drama3.prepare_reference', self.prepared)):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def prepared(path, text, *_args, **_kwargs):
        return {'text': text, 'data': 'UklGRg==' if 'a.wav' in str(path) else 'UklGRk==', 'seconds': 5.0}

    def wait(self):
        end = time.time() + 30
        while self.engines.state == 'loading' and time.time() < end:
            time.sleep(0.05)
        return self.engines.status()

    def requests(self):
        return [json.loads(line) for line in (self.folder / 'requests.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_listed(self):
        engine = next(e for e in self.engines.engines() if e['id'] == 'drama3-tr')
        self.assertEqual((engine['mode'], engine['server'], engine['folder'], engine['languages']),
                         ('builtin', True, True, ['tr']))
        self.assertTrue(engine['emotion_tags'])
        self.prefs.pop('voices')
        self.assertNotEqual(self.engines.choice('tr')[0], 'drama3-tr')   # kendiliginden secilmez

    def test_voice_change_keeps_server(self):
        self.engines.load('tr')
        status = self.wait()
        self.assertEqual((status['state'], status['engine'], status['device']), ('ready', 'drama3-tr', 'sunucu'), status)
        self.engines.say('Bir cümle.')
        # dublajdaki gibi baska bir ses: ayni sunucu, istekte baska kayit
        other = {'voice': 'drama3-tr/clone', 'options': {'reference': 'C:/ses/b.wav', 'reference_text': 'İki.'}}
        self.engines.load('tr', override=other)
        status = self.wait()
        self.assertEqual(status['state'], 'ready', status)
        self.engines.say('Başka cümle.', override=other)
        # F176: her yeni kayitta yuklemede bir isitma istegi, sonra cumle
        warm_a, first, warm_b, second = self.requests()
        self.assertEqual([warm_a['text'], warm_b['text']], [drama3_tr.WARMUP_TEXT] * 2)
        self.assertEqual((warm_a['reference'], warm_b['reference']), (first['reference'], second['reference']))
        self.assertEqual(first['pid'], second['pid'])
        self.assertNotEqual(first['reference']['key'], second['reference']['key'])
        self.assertEqual((first['reference']['text'], second['reference']['text']), ('Bir.', 'İki.'))
        self.assertTrue(Path(second['reference']['path']).is_file())
        process = self.engines._worker.impl.server.process
        self.engines.shutdown()
        self.assertIsNotNone(process.poll())

    def test_warmup_once_and_single_whisper_take(self):
        self.engines.load('tr')
        self.assertEqual(self.wait()['state'], 'ready')
        self.engines.load('tr')        # ayni ses: yeniden isitilmaz
        self.wait()
        self.engines.say('[fısıldar] Sessiz ol.')
        texts = [request['text'] for request in self.requests()]
        self.assertEqual(texts, [drama3_tr.WARMUP_TEXT, '[fısıldar] Sessiz ol.'])

    def test_missing_folder_gives_clear_error(self):
        self.prefs[drama3_tr.PREF_DIR] = ''
        self.engines.load('tr')
        status = self.wait()
        self.assertEqual(status['state'], 'error')
        self.assertIn('Drama 3 TR klasörü seçilmedi', status['message'])


if __name__ == '__main__':
    unittest.main()
