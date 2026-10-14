"""Gelistirme koprusu: Bridge'i HTTP uzerinden acar; web arayuzu tarayicida gercek arka uca baglanir.

    py -3 tools/dev_rpc.py [--app-dir KLASOR] [--port 8765] [--allow-lan]
    (web klasorunde) npm run dev  ->  http://localhost:5173/?rpc=http://127.0.0.1:8765

--app-dir: config.json, library/ ve work_files/ icin baska klasor (gercek verilere dokunmadan
deneme). --allow-lan: LM Studio adresinde yerel ag adresine izin verir (yalnizca deneme).
Yalnizca 127.0.0.1'i dinler. Dosya pencereleri bu kipte acilmaz (None doner).
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description='Aktar gelistirme koprusu')
    parser.add_argument('--app-dir', type=Path)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--allow-lan', action='store_true')
    args = parser.parse_args()

    import app_core
    if args.allow_lan:
        app_core.validate_config = lambda cfg: None
    import bridge
    if args.app_dir:
        import library, qa, search_index, series, speech, themes  # noqa: E401
        for module in (app_core, bridge, library, qa, search_index, speech, series, themes):
            if hasattr(module, 'APP_DIR'):
                module.APP_DIR = args.app_dir.resolve()

    clients = []

    def emit(event, data):
        payload = json.dumps({'event': event, 'data': data}, ensure_ascii=False, default=str)
        for client in list(clients):
            client.put(payload)

    class Dialogs:
        def __getattr__(self, _name):
            return lambda *_args: None

    api = bridge.Bridge(emit=emit, dialogs=Dialogs())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def cors(self):
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')

        def do_OPTIONS(self):  # noqa: N802
            self.send_response(204)
            self.cors()
            self.end_headers()

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            method = str(body.get('method', ''))
            try:
                if method.startswith('_'):
                    raise AttributeError(method)
                result = getattr(api, method)(*body.get('args', []))
            except Exception as error:
                traceback.print_exc()
                result = {'error': 'RPC: ' + repr(error)}
            data = json.dumps(result, ensure_ascii=False, default=str).encode()
            self.send_response(200)
            self.cors()
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 - olay akisi (Server-Sent Events)
            client = queue.Queue()
            clients.append(client)
            self.send_response(200)
            self.cors()
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            try:
                while True:
                    try:
                        payload = client.get(timeout=15)
                    except queue.Empty:
                        payload = None
                    self.wfile.write((('data: ' + payload) if payload else ':').encode() + b'\n\n')
                    self.wfile.flush()
            except OSError:
                clients.remove(client)

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    print(f'Aktar RPC: http://127.0.0.1:{args.port}  (arayuz: http://localhost:5173/?rpc=http://127.0.0.1:{args.port})',
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        api.shutdown()


if __name__ == '__main__':
    main()
