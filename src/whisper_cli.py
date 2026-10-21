"""aktar-whisper: derlenmis Aktar'in cagirdigi ayri konusmadan metin paketi (F50).

DERLE_WHISPER.cmd (Windows) / derle_whisper.sh (Linux) bu betigi faster-whisper (ve
kuruluysa NVIDIA CUDA kutuphaneleri) ile birlikte `dist/aktar-whisper/` klasorune
derler; klasor Aktar.exe'nin (Linux'ta Aktar'in) yanina konur. Aktar sesi kendisi WAV'a cikarir ve bu pakete verir; paket stdout'a satir
basina bir JSON yazar (speech._run_helper protokolu). Kaynak koddan calisirken
gerekmez: faster-whisper kuruluysa Aktar onu dogrudan kullanir.

Kullanim: aktar-whisper.exe <ses.wav> --model large-v3-turbo --device auto
          [--language en] [--models-dir <klasor>] [--cuda-dir <cuBLAS/cuDNN klasoru>]

F146: ayni paket ses ayirma ve konusmaci ayrimini da yapar (sherpa-onnx, voice_split.py):
          aktar-whisper.exe --task separate <44k-stereo.wav> --vocals <a.wav> --background <b.wav> --model <onnx>
          aktar-whisper.exe --task diarize <16k-mono.wav> --segmentation <onnx> --embedding <onnx> [--speakers N]
F172: aktar-whisper.exe --task expression <16k-mono.wav> --tagging <onnx> --labels <csv> --vad <onnx>
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
    parser.add_argument('--task', default='transcribe', choices=('transcribe', 'separate', 'diarize', 'expression'))
    parser.add_argument('audio')
    parser.add_argument('--model', default='large-v3-turbo')
    parser.add_argument('--device', default='auto', choices=('auto', 'cuda', 'cpu'))
    parser.add_argument('--language', default='')
    parser.add_argument('--models-dir', default=None)
    parser.add_argument('--cuda-dir', default='')
    parser.add_argument('--vocals', default='')
    parser.add_argument('--background', default='')
    parser.add_argument('--segmentation', default='')
    parser.add_argument('--embedding', default='')
    parser.add_argument('--speakers', type=int, default=0)
    parser.add_argument('--tagging', default='')
    parser.add_argument('--labels', default='')
    parser.add_argument('--vad', default='')
    args = parser.parse_args(argv)
    if args.task != 'transcribe':
        return run_task(args)
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


def run_task(args):
    import voice_split
    report = lambda done, total: emit(progress=[done, total])  # noqa: E731
    try:
        if args.task == 'separate':
            voice_split.run_separate(args.audio, args.vocals, args.background, args.model, progress=report)
            result = {'vocals': args.vocals, 'background': args.background}
        elif args.task == 'expression':
            result = voice_split.run_expression(args.audio, args.tagging, args.labels, args.vad, progress=report)
        else:
            result = voice_split.run_diarize(args.audio, args.segmentation, args.embedding, args.speakers,
                                             progress=report)
    except Exception as error:  # her hata Aktar'a anlamli mesaj olarak donmeli
        emit(error=str(error))
        return 1
    emit(result=result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
