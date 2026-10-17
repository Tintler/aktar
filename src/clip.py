"""Videodan klip kaydetme (F118): secilen araligi altyazili ya da altyazisiz yeni dosyaya yazar.

Secenekler:
  - format: 'mp4' | 'mkv' | 'm4a' (yalniz ses) | 'gif'
  - mode: 'fast' (yeniden kodlamadan; baslangic onceki anahtar kareye yuvarlanabilir) |
          'precise' (H.264 ile yeniden kodlanir; kare hassasiyetinde)
  - quality: 'high' | 'medium' | 'small' (CRF 18 / 23 / 28)
  - height: 0 (ozgun) ya da 1080 / 720 / 480 ... (yalnizca kucultur)
  - audio: ses akisinin GLOBAL index'i (None: ilk ses akisi)
  - subtitles: 'none' | 'file' (klibin yanina ayri dosya) | 'embed' (kaba gomulu, acilip kapanir) |
               'burn' (goruntuye yakilir; karaoke renkleri de gorunur)

Altyazi dosyasi klibe gore (0'dan baslayan) zamanlarla hazir verilir. Yakma icin FFmpeg
gecici klasorde calistirilir ve altyazi goreli adla verilir; Windows yolunun filtre
icinde kacislanmasi gerekmez. Kaynak video SALT-OKUNUR.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import media
from app_core import GracefulStop

FORMATS = ('mp4', 'mkv', 'm4a', 'gif')
QUALITY = {'high': 18, 'medium': 23, 'small': 28}
SUBTITLE_MODES = ('none', 'file', 'embed', 'burn')
GIF_FPS = 12
_PROGRESS = re.compile(r'out_time_(?:us|ms)=(\d+)')


def options_of(values):
    """Arayuzden gelen secenekleri dogrular; tutarsiz birlesimler duzeltilir."""
    values = dict(values or {})
    fmt = values.get('format') if values.get('format') in FORMATS else 'mp4'
    mode = values.get('mode') if values.get('mode') in ('fast', 'precise') else 'precise'
    quality = values.get('quality') if values.get('quality') in QUALITY else 'high'
    try:
        height = max(0, int(values.get('height') or 0))
    except (TypeError, ValueError):
        height = 0
    subtitles = values.get('subtitles') if values.get('subtitles') in SUBTITLE_MODES else 'none'
    audio = values.get('audio')
    audio = int(audio) if isinstance(audio, (int, float)) or str(audio or '').isdigit() else None
    if fmt == 'm4a':
        subtitles = 'file' if subtitles in ('embed', 'burn') else subtitles
    if fmt == 'gif' and subtitles == 'embed':
        subtitles = 'burn'
    if fmt in ('gif', 'm4a') or subtitles == 'burn' or height:
        mode = 'precise'   # goruntu degisiyorsa kopyalanamaz
    try:
        font_size = max(16, min(200, int(values.get('font_size') or 0))) if values.get('font_size') else 0
    except (TypeError, ValueError):
        font_size = 0
    return {'format': fmt, 'mode': mode, 'quality': quality, 'height': height,
            'audio': audio, 'subtitles': subtitles, 'font_size': font_size}


def clock(seconds):
    """Dosya adi icin '1-02-03' / '02-03'."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours}-{minutes:02d}-{secs:02d}' if hours else f'{minutes:02d}-{secs:02d}'


def default_name(video, start, end, fmt):
    return f'{Path(video).stem} [{clock(start)} – {clock(end)}].{fmt}'


def build_command(video, start, end, output, options, info=None, subtitle_name=None, subtitle_codec=''):
    """FFmpeg komutu (liste). `subtitle_name`: calisma klasorundeki altyazi dosyasinin adi."""
    options = options_of(options)
    duration = max(0.05, float(end) - float(start))
    fmt, mode = options['format'], options['mode']
    video_stream = (info or {}).get('video')
    command = [media.ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'error', '-y',
               '-ss', f'{float(start):.3f}', '-i', str(video)]
    embed = options['subtitles'] == 'embed' and subtitle_name and fmt in ('mp4', 'mkv')
    if embed:
        command += ['-i', subtitle_name]
    command += ['-t', f'{duration:.3f}']
    audio_map = f'0:{options["audio"]}' if options['audio'] is not None else '0:a:0?'
    filters = []
    if options['subtitles'] == 'burn' and subtitle_name and fmt != 'm4a':
        burn = f'subtitles={subtitle_name}'
        if options['font_size'] and subtitle_codec not in ('ass', 'ssa'):
            # SRT'yi libass 288 satirlik tuvale cizer; boyut 1080p olcegindeki pikselden cevrilir.
            burn += f":force_style='Fontsize={max(6, round(options['font_size'] * 288 / 1080))}'"
        filters.append(burn)
    if fmt == 'gif':
        height = options['height'] or 360
        filters.append(f'fps={GIF_FPS},scale=-2:{height}:flags=lanczos')
        chain = ','.join(filters) + ',split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer'
        return command + ['-map', '0:v:0', '-vf', chain, '-loop', '0', '-an', str(output)]
    if fmt == 'm4a':
        return command + ['-map', audio_map, '-vn', '-c:a', 'aac', '-b:a', '192k', str(output)]
    if options['height'] and (not video_stream or not video_stream.get('height')
                              or options['height'] < video_stream['height']):
        filters.append(f'scale=-2:{options["height"]}')
    command += ['-map', '0:v:0', '-map', audio_map]
    if mode == 'fast':
        command += ['-c:v', 'copy', '-c:a', 'copy', '-avoid_negative_ts', 'make_zero']
        if fmt == 'mp4' and video_stream and video_stream.get('codec') == 'hevc':
            command += ['-tag:v', 'hvc1']
    else:
        if filters:
            command += ['-vf', ','.join(filters)]
        command += ['-c:v', 'libx264', '-preset', 'medium', '-crf', str(QUALITY[options['quality']]),
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k']
    if embed:
        codec = 'mov_text' if fmt == 'mp4' else ('ass' if subtitle_codec in ('ass', 'ssa') else 'srt')
        command += ['-map', '1:0', '-c:s', codec, '-disposition:s:0', 'default']
    if fmt == 'mp4':
        command += ['-movflags', '+faststart']
    return command + [str(output)]


def run(command, duration, cwd=None, progress=None, cancelled=None):
    """FFmpeg'i calistirir; `progress(saniye, toplam)`. Iptalde GracefulStop."""
    command = command[:-1] + ['-progress', 'pipe:1', '-nostats', command[-1]]
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    errors = tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace')
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, stdin=subprocess.DEVNULL,
                               text=True, encoding='utf-8', errors='replace', cwd=cwd, **kwargs)
    try:
        for line in process.stdout:
            if cancelled and cancelled():
                process.kill()
                raise GracefulStop('Klip kaydı durduruldu.')
            match = _PROGRESS.match(line.strip())
            if match and progress:
                progress(min(duration, int(match.group(1)) / 1_000_000), duration)
    finally:
        if process.poll() is None:
            process.kill()
        process.stdout.close()
        code = process.wait()
        errors.seek(0)
        detail = errors.read().strip()
        errors.close()
    if code != 0:
        raise RuntimeError('Klip kaydedilemedi: ' + (detail[-500:] or f'çıkış kodu {code}'))


def save(video, start, end, output, options, info=None, subtitle_text=None, subtitle_ext='srt',
         progress=None, cancelled=None):
    """Klibi `output`a yazar. `subtitle_text`: klibe gore zamanlanmis altyazi (yoksa None).

    Donen: {'output', 'subtitle'} (ayri altyazi dosyasi yazildiysa yolu).
    """
    options = options_of(options)
    start, end = float(start), float(end)
    if end - start < 0.1:
        raise ValueError('Klip en az 0,1 saniye olmalı.')
    output = Path(output)
    if output.resolve() == Path(video).resolve():
        raise ValueError('Klip kaynak videonun üzerine yazılamaz.')
    output.parent.mkdir(parents=True, exist_ok=True)
    sidecar = None
    folder = Path(tempfile.mkdtemp(prefix='aktar-clip-'))
    try:
        name = None
        if subtitle_text and options['subtitles'] in ('embed', 'burn'):
            name = 'clip.' + subtitle_ext
            (folder / name).write_text(subtitle_text, encoding='utf-8', newline='\n')
        command = build_command(video, start, end, output.resolve(), options, info, name, subtitle_ext)
        try:
            run(command, end - start, cwd=str(folder), progress=progress, cancelled=cancelled)
        except (GracefulStop, RuntimeError):
            try:
                output.unlink()
            except OSError:
                pass
            raise
        if subtitle_text and options['subtitles'] == 'file':
            sidecar = output.with_suffix('.' + subtitle_ext)
            sidecar.write_text(subtitle_text, encoding='utf-8', newline='\n')
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return {'output': str(output), 'subtitle': str(sidecar) if sidecar else ''}
