"""Komut satiri giris noktasi. Arayuz ve CLI ayni cekirdegi (app_core) kullanir."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app_core import TranslationEngine, load_config, read, render_output
from media import extract_subtitle, ffmpeg_path, ffprobe_path, subtitle_streams, unique_output_path
import subtitle
from series import series_decisions, series_glossary


def make_logger(prefix='Aktar'):
    def log(message):
        print(str(message))
    return log


def _resolve_binaries():
    ffprobe_path()
    ffmpeg_path()


def command_check(_args):
    """ffmpeg/ffprobe bulunabilirligini ve config gecerliligini dogrular."""
    _resolve_binaries()
    load_config()
    print('ffprobe: ' + ffprobe_path())
    print('ffmpeg:  ' + ffmpeg_path())
    print('Yapılandırma geçerli.')
    return 0


def command_streams(args):
    """Videodaki altyazi stream'lerini listeler."""
    streams = subtitle_streams(args.video)
    if not streams:
        print('Bu videoda altyazı akışı yok.')
        return 0
    for stream in streams:
        if stream['image']:
            status = 'Görüntü tabanlı altyazı şu anda desteklenmiyor.'
        elif stream['supported']:
            status = stream['extension'].upper()
        else:
            status = 'Desteklenmiyor'
        print(f'#{stream["index"]:<4} {stream["codec"]:<20} '
              f'{stream["language"]:<8} {stream["title"]:<24} {status}')
    return 0


def command_extract(args):
    """Secilen metin tabanli altyazi stream'ini videonun dizinine cikarir."""
    streams = {stream['index']: stream for stream in subtitle_streams(args.video)}
    stream = streams.get(args.stream)
    if stream is None:
        raise ValueError('Bu videoda boyle bir stream yok: ' + str(args.stream))
    if stream['image']:
        raise ValueError('Görüntü tabanlı altyazı şu anda desteklenmiyor.')
    if not stream['supported']:
        raise ValueError('Desteklenmeyen altyazı codec: ' + stream['codec'])
    video = Path(args.video)
    output = Path(args.output) if args.output else unique_output_path(video, stream['extension'])
    extract_subtitle(video, stream['index'], output, codec=stream['codec'])
    print('Altyazı çıkarıldı: ' + str(output))
    return 0


def command_translate(args):
    """Altyazi dosyasini LM Studio ile Turkceye cevirir.

    Cikti, altyazinin bulundugu dizine `<ad>_TR.<uzanti>` olarak yazilir;
    cakismada `_TR (2)` uretilir. `--series` verilirse seri sozlugu + kararlari
    temel alinir; `--glossary` ile bolume ozel terim eklenir.
    """
    source_path = Path(args.subtitle)
    if not source_path.exists():
        raise ValueError('Altyazı dosyası bulunamadı: ' + str(source_path))
    kind, payload = subtitle.parse_by_extension(read(source_path), source_path.suffix)
    cues = subtitle.cues_of(kind, payload)
    glossary = []
    decisions = []
    if args.series:
        glossary = series_glossary(args.series)
        decisions = series_decisions(args.series)
    if args.glossary:
        for entry in args.glossary:
            if '=' not in entry:
                raise ValueError('Sözlük biçimi "Kaynak=Karşılık" olmalı: ' + entry)
            source, target = entry.split('=', 1)
            glossary.append({'source': source.strip(), 'target': target.strip()})
    checkpoint = source_path.with_suffix(source_path.suffix + '.state.json')
    engine = TranslationEngine(load_config, log=make_logger())
    translated = engine.translate(cues, glossary=glossary, decisions=decisions, checkpoint=checkpoint)
    output = unique_output_path(source_path, kind)
    text, _ = render_output(kind, payload, translated, log=make_logger())
    output.write_text(text, encoding='utf-8', newline='\n')
    print('Çeviri yazıldı: ' + str(output))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='aktar', description='Video altyazısı çıkarma ve çevirme.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    check = subparsers.add_parser('check', help='ffmpeg/ffprobe ve yapilandirmayi dogrula.')
    check.set_defaults(func=command_check)

    streams = subparsers.add_parser('streams', help='Videodaki altyazı akışlarını listele.')
    streams.add_argument('video')
    streams.set_defaults(func=command_streams)

    extract = subparsers.add_parser('extract', help='Seçilen altyazı akışını çıkar.')
    extract.add_argument('video')
    extract.add_argument('--stream', type=int, required=True, help='ffprobe global stream index')
    extract.add_argument('--output', default='', help='Çıktı dosyası (varsayılan: videonun dizini)')
    extract.set_defaults(func=command_extract)

    translate = subparsers.add_parser('translate', help='Altyazı dosyasını Türkçeye çevir.')
    translate.add_argument('subtitle', help='Çıkarılmış altyazı dosyası (.srt/.ass/.ssa/.vtt)')
    translate.add_argument('--series', default='', help='Seri slug (seri sozlugu + kararlari)')
    translate.add_argument('--glossary', action='append', default=[],
                           help='Bölüme özel terim: "Kaynak=Karşılık" (çoklanabilir)')
    translate.set_defaults(func=command_translate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError) as error:
        print('HATA: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
