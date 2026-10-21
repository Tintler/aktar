"""Metinden ses (F178): yazilan metni secilen sesle okuyup secilen klasore WAV ya da MP3 olarak yazar.

Cumleleri arayuz boler (web/src/lib/sentences.js, okuyucuyla ayni) ve her cumleden sonraki sessizligi
(pauses.js) gonderir. Motor birlestirmeyi destekliyorsa (F177 group_chars) ayni paragraftaki ardisik
cumleler tek istekte okunur. Onbellek kullanilmaz (book=None). Is pencere icindeki bir is parcaciginda
calisir; pencere kapaninca durdurulur.
"""
from __future__ import annotations

import base64
import io
import os
import tempfile
import wave
from pathlib import Path

import audiobook
from tts import Cancelled

FORMATS = ('wav', 'mp3')
TEXT_LIMIT = 200_000          # tek seferde okunacak en uzun metin (karakter)
FILE_LIMIT = 2 * 1024 * 1024  # surukle-birak ile acilan metin dosyasinin en buyuk boyutu
TEXT_TYPES = ('.txt', '.md')


def clean(sentences, gaps=None):
    """[(cumle, sonraki sessizlik sn | None)]: bos cumleler atlanir."""
    gaps = list(gaps or ())
    result = []
    for index, text in enumerate(sentences or ()):
        text = ' '.join(str(text).split())
        if not text:
            continue
        gap = gaps[index] if index < len(gaps) else None
        try:
            gap = None if gap is None else max(0.0, min(10.0, float(gap)))
        except (TypeError, ValueError):
            gap = None
        result.append((text, gap))
    return result


def group(pairs, limit=0, breaks=()):
    """Ardisik cumleleri `limit` karaktere kadar birlestirir (0: cumle cumle). Paragraf sonu (`breaks`:
    pairs dizinleri) asilmaz. [(cumle listesi, son cumlenin sessizligi)]."""
    breaks = set(breaks or ())
    groups = []
    current, size = [], 0
    for index, (text, gap) in enumerate(pairs):
        if current and (not limit or size + 1 + len(text) > limit):
            groups.append((current, last_gap))
            current, size = [], 0
        current.append(text)
        size += len(text) + (1 if size else 0)
        last_gap = gap
        if index in breaks:
            groups.append((current, last_gap))
            current, size = [], 0
    if current:
        groups.append((current, last_gap))
    return groups


def output_path(folder, name, text, fmt):
    """Klasorde var olan dosyanin uzerine yazmayan ad: '<ad>.wav', '<ad> (2).wav' ..."""
    fmt = fmt if fmt in FORMATS else 'wav'
    fallback = ' '.join(str(text or '').split()[:6]) or 'ses'
    base = audiobook.safe_name(name, '', 100) or audiobook.safe_name(fallback, 'ses', 60)
    folder = Path(folder)
    path = folder / f'{base}.{fmt}'
    number = 2
    while path.exists():
        path = folder / f'{base} ({number}).{fmt}'
        number += 1
    return path


def read_text(path):
    """Surukle-birak ile acilan metin dosyasi (UTF-8, olmazsa Windows-1254)."""
    path = Path(path)
    if path.suffix.lower() not in TEXT_TYPES:
        raise ValueError('Yalnızca metin dosyası (.txt, .md) açılabilir.')
    if path.stat().st_size > FILE_LIMIT:
        raise ValueError('Metin dosyası çok büyük (en fazla 2 MB).')
    data = path.read_bytes()
    for encoding in ('utf-8-sig', 'cp1254'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', errors='replace')


def write(engines, groups, speed, path, language='tr', override=None, progress=None, cancel=None, gap=0.35):
    """Gruplari sirayla okutur, tek WAV'a yazar; fmt mp3 ise (yol uzantisi) FFmpeg ile kodlar.
    Durdurulursa Cancelled; yarim dosya silinir. Donen: ses suresi (sn)."""
    path = Path(path)
    mp3 = path.suffix.lower() == '.mp3'
    handle, temp = tempfile.mkstemp(suffix='.wav', prefix='.aktar-', dir=str(path.parent))
    os.close(handle)
    temp = Path(temp)
    stream = None
    frames = rate = 0
    total = sum(len(texts) for texts, _gap in groups)
    done = 0
    try:
        for texts, after in groups:
            if cancel is not None and cancel.is_set():
                raise Cancelled('Ses kaydı durduruldu.')
            result = engines.say(texts if len(texts) > 1 else texts[0], speed, None, language, override)
            if not result.get('audio'):
                continue
            with wave.open(io.BytesIO(base64.b64decode(result['audio']))) as clip:
                if stream is None:
                    rate = clip.getframerate()
                    stream = wave.open(str(temp), 'wb')
                    stream.setnchannels(1)
                    stream.setsampwidth(2)
                    stream.setframerate(rate)
                count = clip.getnframes()
                stream.writeframes(clip.readframes(count))
                silence = int(rate * (gap if after is None else after))
                stream.writeframes(b'\x00\x00' * silence)
                frames += count + silence
            done += len(texts)
            if progress:
                progress(done, total)
        if stream is None:
            raise RuntimeError('Ses motoru ses üretmedi.')
        stream.close()
        stream = None
        if mp3:
            audiobook._run(audiobook.encode_command(temp, path, 'mp3'))
        else:
            os.replace(temp, path)
        return frames / float(rate)
    finally:
        if stream is not None:
            stream.close()
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass
