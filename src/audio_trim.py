"""Ses kaydindan aralik kesme (F173): ses onayari olustururken klon kaydinin istenen parcasi.

Klonlama modelleri kaydin ilk ~20 sn'sini kullanir; uzun bir kaydin istenen parcasi burada secilir ve onayar
klasorune WAV olarak yazilir (voice_presets). Arayuz dalga bicimini (peaks) cizer, kaydi dinletir (listen_base64;
secim ayni ses icinde aranir, oynatma imleci gorunur) ve F174 kelime zamanli metni gosterir (transcript, Whisper).
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
LISTEN_LIMIT = 900.0   # dinletilen kayit en fazla (sn); daha uzun kaydin basi
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


def _cut_command(source, target, start, end):
    length = end - start
    fade = min(FADE, length / 4)
    command = [media.ffmpeg_path(), '-v', 'error', '-nostdin', '-y', '-ss', f'{start:.3f}', '-t', f'{length:.3f}',
               '-i', str(source), '-vn', '-ac', '1']
    return command + ['-af', f'afade=t=in:d={fade:.3f},afade=t=out:st={max(0.0, length - fade):.3f}:d={fade:.3f}',
                      '-c:a', 'pcm_s16le', str(target)]


def listen_base64(path):
    """Kaydin dinlenecek kopyasi {'audio': base64, 'mime'}: mono MP3 (en fazla LISTEN_LIMIT sn); MP3 kodlayicisi
    yoksa 16 kHz WAV. Zamanlar ozgun kayitla aynidir (arayuz secimi bu ses icinde arar)."""
    with tempfile.TemporaryDirectory(prefix='aktar-dinle-') as folder:
        for name, mime, codec in (('kayit.mp3', 'audio/mpeg', ['-c:a', 'libmp3lame', '-b:a', '96k']),
                                  ('kayit.wav', 'audio/wav', ['-ar', '16000', '-c:a', 'pcm_s16le'])):
            target = Path(folder) / name
            done = media._run([media.ffmpeg_path(), '-v', 'error', '-nostdin', '-y', '-t', f'{LISTEN_LIMIT:g}',
                               '-i', str(path), '-vn', '-ac', '1'] + codec + [str(target)])
            if done.returncode == 0 and target.exists():
                return {'audio': base64.b64encode(target.read_bytes()).decode('ascii'), 'mime': mime}
        raise ValueError('Ses kaydı dinletilemedi: ' + (done.stderr or '').strip()[-300:])


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


TRANSCRIPT_VERSION = 1


def transcript(path, transcribe, cache_dir, language='', model=''):
    """F174: kaydin kelime zamanli metni {'words': [[bas, son, kelime], ...]} (Whisper; onbellekli).
    `transcribe(wav16k, dil)` Whisper bolumlerini dondurur ([{'start', 'end', 'text', 'words'}])."""
    import hashlib
    import json
    source = Path(path)
    content = hashlib.sha1()   # icerige gore: onayar klasorune kopyalanan kayit da onbellekten gelir
    with open(source, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            content.update(block)
    key = hashlib.sha1(f'{TRANSCRIPT_VERSION}|{content.hexdigest()}|{language}|{model}'.encode('utf-8')).hexdigest()[:20]
    cached = Path(cache_dir) / f'{key}.json'
    try:
        return json.loads(cached.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    with tempfile.TemporaryDirectory(prefix='aktar-metin-') as folder:
        audio = Path(folder) / 'kayit.wav'
        done = media._run([media.ffmpeg_path(), '-v', 'error', '-nostdin', '-y', '-i', str(source), '-vn', '-ac', '1',
                           '-ar', '16000', '-c:a', 'pcm_s16le', str(audio)])
        if done.returncode != 0 or not audio.exists():
            raise ValueError('Ses kaydı okunamadı: ' + (done.stderr or '').strip()[-300:])
        segments = transcribe(audio, language) or []
    words = []
    for segment in segments:
        for start, end, word in segment.get('words') or [[segment['start'], segment['end'], segment.get('text', '')]]:
            word = ' '.join(str(word).split())
            if word:
                words.append([round(float(start), 2), round(float(end), 2), word])
    result = {'words': words}
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return result

