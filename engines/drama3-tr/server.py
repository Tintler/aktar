"""Aktar'in Drama 3 TR sunucusu (F176): kasparovabi/drama-3-tr motorunu istek basina klon kaydiyla calistirir.

Aktar bu dosyayi kullanicinin sectigi drama-3-tr klasorundeki Python ortamiyla baslatir ve pencere kapaninca
durdurur; Aktar disinda calistirilmasi gerekmez. Reponun kendi server.py'si klon kaydini acilista sabitler;
burada her istek kendi kaydini getirir (dublajda konusmaci basina ses). Model bir kez yuklenir; kayit
degisince yalnizca yeni kaydin on okumasi yapilir (PrefixCache tek kaydi tutar: dikkat KV'si model
onbelleginde kaldigi icin eski kaydin durumuna geri donulmez, her degisimde yeniden okunur).

    python server.py --folder <drama-3-tr> --port <port> --speaker <speaker.safetensors>

    GET  /health -> {"status": "healthy", "reference": <etkin kayit anahtari>}
    POST /tts    {"text", "reference": {"key", "path", "text"}, "cfg", "temperature", "top_p"}
                 -> 44.1 kHz mono 16 bit WAV

Standart ciktiya giden "AKTAR STAGE <metin>" satirlari Aktar'da yukleme asamasi olarak, "AKTAR READY" de
hazir isareti olarak okunur.
"""
import argparse
from collections import OrderedDict
import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CODES_KEPT = 8      # kodlanmis klon kayitlari (codec ciktisi, kucuk)


def stage(text):
    print(f'AKTAR STAGE {text}', flush=True)


def exit_with_aktar():
    """Aktar stdin borusunu acik tutar; Aktar kapanir ya da cokerse boru kapanir ve sunucu da kapanir
    (uygulama kapaliyken arka planda hicbir sey calismaz)."""
    def watch():
        try:
            while sys.stdin.buffer.read(1):
                pass
        except (OSError, ValueError, AttributeError):
            pass
        os._exit(0)
    if sys.stdin is not None:
        threading.Thread(target=watch, name='aktar-watch', daemon=True).start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--speaker', required=True)
    parser.add_argument('--slots', type=int, default=300)
    parser.add_argument('--ram', action='store_true', help='uzmanlari diskten okumak yerine bellekte tut (40 GB+)')
    args = parser.parse_args()
    exit_with_aktar()

    folder = os.path.abspath(args.folder)
    os.chdir(folder)
    sys.path.insert(0, folder)
    os.environ['FISH_DRAMA3_CUDA_GRAPH'] = '1'

    stage('Drama 3 TR: kütüphaneler yükleniyor…')
    import soundfile as sf
    import torch
    from engine import OnDemandExperts, PrefixCache, attach_speaker, build_model, synthesize
    from prepare_data import encode, load_codec

    stage('Drama 3 TR: model yükleniyor (ilk açılış birkaç dakika sürebilir)…')
    model, _store = build_model(args.slots, disk=not args.ram)
    attach_speaker(model, args.speaker)
    OnDemandExperts.batch = 2       # yonerge yonlendirmesi (cfg) iki satirla calisir
    codec = load_codec()
    lock = threading.Lock()
    codes = OrderedDict()           # anahtar -> (ref_codes, ref_text)
    active = {'key': None, 'prefix': None}

    def use_reference(reference):
        key = str(reference.get('key') or reference.get('path'))
        if key not in codes:
            audio, rate = sf.read(str(reference['path']), dtype='float32')
            ref_codes = encode(codec, audio if audio.ndim == 1 else audio.mean(1), rate).long()
            codes[key] = (ref_codes, ' '.join(str(reference.get('text') or '').split()))
            while len(codes) > CODES_KEPT:
                codes.popitem(last=False)
        codes.move_to_end(key)
        ref_codes, ref_text = codes[key]
        if active['key'] != key:
            active.update(key=key, prefix=PrefixCache(model, ref_text, ref_codes))
        return active['prefix'], ref_codes, ref_text

    def speak(request):
        text = str(request.get('text') or '')
        with lock:
            prefix, ref_codes, ref_text = use_reference(request['reference'])
            wave, info = synthesize(model, prefix, codec, text, ref_codes, ref_text,
                                    temperature=float(request.get('temperature', 1.0)),
                                    top_p=float(request.get('top_p', 0.9)), strength=float(request.get('cfg', 4.0)))
        print(f'[tts] {info} {text[:60]}', flush=True)
        buffer = io.BytesIO()
        sf.write(buffer, wave, codec.sample_rate, format='WAV', subtype='PCM_16')
        return buffer.getvalue()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _send(self, code, body, kind):
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/health':
                self._send(200, json.dumps({'status': 'healthy', 'reference': active['key']}).encode(), 'application/json')
            else:
                self._send(404, b'{}', 'application/json')

        def do_POST(self):
            try:
                request = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
                self._send(200, speak(request), 'audio/wav')
            except Exception as error:
                print(f'[tts] hata {error!r}', flush=True)
                self._send(500, json.dumps({'error': repr(error)}).encode(), 'application/json')

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'AKTAR READY {args.port} GPU {torch.cuda.max_memory_allocated() / 2**30:.1f} GiB', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
