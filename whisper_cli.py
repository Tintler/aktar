"""aktar-whisper: Aktar.exe'nin cagirdigi ayri konusmadan metin paketi (F50).

DERLE_WHISPER.cmd bu betigi faster-whisper (ve kuruluysa NVIDIA CUDA kutuphaneleri)
ile birlikte `dist\\aktar-whisper\\` klasorune derler; klasor Aktar.exe'nin yanina
konur. Aktar sesi kendisi WAV'a cikarir ve bu pakete verir; paket stdout'a satir
basina bir JSON yazar (speech._run_helper protokolu). Kaynak koddan calisirken
gerekmez: faster-whisper kuruluysa Aktar onu dogrudan kullanir.

Kullanim: aktar-whisper.exe <ses.wav> --model large-v3-turbo --device auto
          [--language en] [--models-dir <klasor>] [--cuda-dir <cuBLAS/cuDNN klasoru>]
"""
from __future__ import annotations

import argparse
import json
import sys


def emit(**message):
    print(json.dumps(message, ensure_ascii=False), flush=True)


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(prog='aktar-whisper')
    parser.add_argument('audio')
    parser.add_argument('--model', default='large-v3-turbo')
    parser.add_argument('--device', default='auto', choices=('auto', 'cuda', 'cpu'))
    parser.add_argument('--language', default='')
    parser.add_argument('--models-dir', default=None)
    parser.add_argument('--cuda-dir', default='')
    args = parser.parse_args(argv)
    import speech
    try:
        result = speech.run_whisper(
            args.audio, args.model, args.device, args.language,
            progress=lambda done, total: emit(progress=[done, total]),
            log=lambda message: emit(log=message), download_root=args.models_dir,
            cuda_dir=args.cuda_dir)
    except Exception as error:  # her hata Aktar'a anlamli mesaj olarak donmeli
        emit(error=str(error))
        return 1
    emit(result=result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
