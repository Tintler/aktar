"""Ses kaydindan aralik kesme (F173): ses onayari olustururken klon kaydinin istenen parcasi.

Klonlama modelleri kaydin ilk ~20 sn'sini kullanir; uzun bir kaydin istenen parcasi burada secilir ve onayar
klasorune WAV olarak yazilir (voice_presets). Arayuz dalga bicimini (peaks) cizer, secimi dinletir (clip_base64).
Kaynak dosya SALT-OKUNUR. FFmpeg ile; numpy gerekmez.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path

import media

PEAK_RATE = 8000       # dalga bicimi icin cozme hizi
PEAKS = 600            # dalga bicimi sutun sayisi
PREVIEW_RATE = 22050
PREVIEW_LIMIT = 60.0   # dinletilen secim en fazla (sn)
FADE = 0.02            # kesilen uclarda tik sesi olmasin
MIN_LENGTH = 0.5


def _kwargs():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def peaks(path, count=PEAKS):
    """{'duration': sn, 'peaks': [0..1] x count} (her sutunun en yuksek mutlak degeri)."""
    done = subprocess.run([media.ffmpeg_path(), '-v', 'error', '-nostdin', '-i', str(path), '-vn', '-ac', '1',
                           '-ar', str(PEAK_RATE), '-f', 's16le', '-'], stdin=subprocess.DEVNULL,
                          capture_output=True, **_kwargs())
    if done.returncode != 0:
        detail = done.stderr.decode('utf-8', 'replace').strip()[-300:]
        raise ValueError('Ses kaydı okunamadı: ' + (detail or Path(path).name))
    samples = array('h')
    samples.frombytes(done.stdout[:len(done.stdout) // 2 * 2])
    if sys.byteorder == 'big':
        samples.byteswap()
    if not samples:
        raise ValueError('Ses kaydı boş.')
    count = max(1, min(int(count), len(samples)))
    step = len(samples) / count
    result = []
    for index in range(count):
        chunk = samples[int(index * step):max(int(index * step) + 1, int((index + 1) * step))]
        result.append(round(max(max(chunk), -min(chunk)) / 32768, 3))
    top = max(result) or 1.0
    return {'duration': round(len(samples) / PEAK_RATE, 3), 'peaks': [round(value / top, 3) for value in result]}


def span(start, end, duration=None):
    """Gecerli (bas, son) araligi; gecersizse ValueError."""
    start, end = max(0.0, float(start)), float(end)
    if duration:
        end = min(end, float(duration))
    if end - start < MIN_LENGTH:
        raise ValueError(f'Seçilen parça çok kısa (en az {MIN_LENGTH:g} sn).')
    return start, end


def _cut_command(source, target, start, end, rate=None):
    length = end - start
    fade = min(FADE, length / 4)
    command = [media.ffmpeg_path(), '-v', 'error', '-nostdin', '-y', '-ss', f'{start:.3f}', '-t', f'{length:.3f}',
               '-i', str(source), '-vn', '-ac', '1']
    if rate:
        command += ['-ar', str(rate)]
    return command + ['-af', f'afade=t=in:d={fade:.3f},afade=t=out:st={max(0.0, length - fade):.3f}:d={fade:.3f}',
                      '-c:a', 'pcm_s16le', str(target)]


def clip_base64(path, start, end):
    """Secimin dinlenecek kopyasi: 22 kHz mono WAV, base64 (en fazla PREVIEW_LIMIT sn)."""
    start, end = span(start, end)
    end = min(end, start + PREVIEW_LIMIT)
    with tempfile.TemporaryDirectory(prefix='aktar-kes-') as folder:
        target = Path(folder) / 'secim.wav'
        done = media._run(_cut_command(path, target, start, end, PREVIEW_RATE))
        if done.returncode != 0 or not target.exists():
            raise ValueError('Seçim dinletilemedi: ' + (done.stderr or '').strip()[-300:])
        return base64.b64encode(target.read_bytes()).decode('ascii')


def cut(source, target, start, end):
    """[start, end] araligini `target`a 16 bit mono WAV olarak yazar (ozgun ornekleme hizi). `source` ile
    `target` ayni dosya olabilir (once gecici dosyaya yazilir)."""
    start, end = span(start, end)
    target = Path(target)
    partial = target.with_name(target.stem + '.part.wav')
    done = media._run(_cut_command(source, partial, start, end))
    if done.returncode != 0 or not partial.exists():
        partial.unlink(missing_ok=True)
        raise ValueError('Ses kaydı kesilemedi: ' + (done.stderr or '').strip()[-300:])
    os.replace(partial, target)
    return target
