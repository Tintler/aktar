"""Sesli kitap disa aktarma (F141): okuyucudaki kitabi bolum bolum seslendirip tek dosyaya yazar.

Bicimler:
  - 'm4b': tek dosya, AAC; bolum isaretleri (ffmetadata) ve kapak resmi ile. Telefon ve sesli kitap
    uygulamalari bolumleri ayri gosterir.
  - 'mp3': secilen klasore bolum basina bir MP3 (ID3 etiketleri: baslik, albüm, yazar, parca no, kapak).

Cumleler tts.Engines.export ile uretilir: kitabin ses onbellegi (Hazirla) kullanilir ve doldurulur.
M4B'de her bolum once APP_DIR/sesli-kitap/<kitap>/ altinda .m4a olarak saklanir; is durdurulur ya da
pencere kapanirsa bir sonraki sefer biten bolumler atlanir. Is pencere icindeki bir is parcaciginda
calisir (uygulama kapaliyken hicbir sey calismaz).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import media
from tts import Cancelled

WORK_DIR = 'sesli-kitap'
FORMATS = ('m4b', 'mp3')
AAC_BITRATE = '64k'
MP3_BITRATE = '96k'
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


class Stopped(RuntimeError):
    """Kullanici sesli kitap kaydini durdurdu."""


def safe_name(text, fallback='kitap', limit=100):
    name = ' '.join(_UNSAFE.sub(' ', str(text or '')).split()).strip(' .')
    return name[:limit].rstrip(' .') or fallback


def chapter_list(chapters):
    """Gelen bolumleri temizler: [{'title', 'sentences', 'gaps'}]; metni olmayanlar atlanir."""
    result = []
    for number, chapter in enumerate(chapters or [], 1):
        sentences = [' '.join(str(s).split()) for s in (chapter or {}).get('sentences') or []]
        gaps = list((chapter or {}).get('gaps') or [])
        pairs = [(text, gaps[i] if i < len(gaps) else None) for i, text in enumerate(sentences) if text]
        if not pairs:
            continue
        title = ' '.join(str((chapter or {}).get('title') or '').split()) or f'Bölüm {number}'
        result.append({'title': title[:200], 'sentences': [p[0] for p in pairs], 'gaps': [p[1] for p in pairs]})
    return result


def _escape_meta(value):
    """ffmetadata degeri: = ; # \\ ve satir sonu ters bolu ile kacirilir."""
    return re.sub(r'([=;#\\\n])', r'\\\1', str(value))


def ffmetadata(title, author, chapters):
    """[(baslik, sure_saniye)] -> FFMETADATA1 metni (bolum baslangic/bitisleri milisaniye)."""
    lines = [';FFMETADATA1', f'title={_escape_meta(title)}', f'album={_escape_meta(title)}', 'genre=Audiobook']
    if author:
        lines += [f'artist={_escape_meta(author)}', f'album_artist={_escape_meta(author)}']
    start = 0
    for name, seconds in chapters:
        end = start + max(1, int(round(float(seconds) * 1000)))
        lines += ['', '[CHAPTER]', 'TIMEBASE=1/1000', f'START={start}', f'END={end}', f'title={_escape_meta(name)}']
        start = end
    return '\n'.join(lines) + '\n'


def concat_list(paths):
    """ffmpeg concat demuxer listesi (tek tirnaklar kacirilir)."""
    return ''.join("file '" + str(Path(p).resolve()).replace("'", "'\\''") + "'\n" for p in paths)


def cover_file(data_url, folder):
    """Kapak data URL'ini dosyaya yazar; yoksa ya da bozuksa None."""
    match = re.match(r'data:image/(png|jpe?g);base64,(.+)', str(data_url or ''), re.S)
    if not match:
        return None
    try:
        raw = base64.b64decode(match.group(2), validate=False)
    except ValueError:
        return None
    if not raw:
        return None
    path = Path(folder) / ('cover.png' if match.group(1) == 'png' else 'cover.jpg')
    path.write_bytes(raw)
    return path


def wav_seconds(path):
    with wave.open(str(path)) as clip:
        return clip.getnframes() / float(clip.getframerate())


def encode_command(source, target, fmt, tags=None, cover=None):
    """WAV -> m4a (AAC, M4B parcasi) ya da mp3 (ID3 etiketli, kapakli)."""
    command = [media.ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'error', '-y', '-i', str(source)]
    if fmt == 'mp3':
        if cover:
            command += ['-i', str(cover), '-map', '0:a', '-map', '1:v', '-c:v', 'copy',
                        '-metadata:s:v', 'title=Album cover', '-metadata:s:v', 'comment=Cover (front)']
        command += ['-c:a', 'libmp3lame', '-b:a', MP3_BITRATE, '-ac', '1', '-id3v2_version', '3']
        for key, value in (tags or {}).items():
            if value:
                command += ['-metadata', f'{key}={value}']
    else:
        command += ['-vn', '-c:a', 'aac', '-b:a', AAC_BITRATE, '-ac', '1', '-f', 'mp4']
    return command + [str(target)]


def join_command(listing, metadata, target, cover=None):
    """Bolum m4a'larini kopyalayarak (yeniden kodlamadan) tek M4B'de birlestirir."""
    command = [media.ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'error', '-y',
               '-f', 'concat', '-safe', '0', '-i', str(listing), '-i', str(metadata)]
    if cover:
        command += ['-i', str(cover)]
    command += ['-map', '0:a', '-map_metadata', '1', '-map_chapters', '1']
    if cover:
        command += ['-map', '2:v', '-c:v', 'copy', '-disposition:v:0', 'attached_pic']
    return command + ['-c:a', 'copy', '-movflags', '+faststart', '-f', 'mp4', str(target)]


def _run(command):
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    done = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          text=True, encoding='utf-8', errors='replace', **kwargs)
    if done.returncode != 0:
        raise RuntimeError('FFmpeg sesi yazamadı: ' + ((done.stderr or '').strip()[-500:] or f'çıkış kodu {done.returncode}'))


def chapter_key(engines, chapter, speed, language, override=None):
    """Bolumun sesini belirleyen her sey (ses, ayarlar, hiz, metin, duraklar): saklanan parca gecerli mi."""
    engine_id, voice_id = engines.choice(language, override)
    options = engines._voice_options(engine_id, voice_id, override) if engine_id else {}
    raw = json.dumps([engine_id, voice_id, options, round(float(speed), 2), chapter['sentences'], chapter['gaps']],
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def build(engines, chapters, target, fmt='m4b', title='', author='', cover=None, speed=1.0, book=None,
          language='tr', progress=None, cancel=None, log=None):
    """Sesli kitabi yazar (bloklar). progress(done_sentences, total_sentences, chapter_no, chapter_count).
    m4b: `target` dosya yolu; mp3: `target` klasor (icine '<kitap>' klasoru acilir). Donen: {'output', 'chapters'}."""
    fmt = fmt if fmt in FORMATS else 'm4b'
    chapters = chapter_list(chapters)
    if not chapters:
        raise ValueError('Kitapta seslendirilecek metin yok.')
    log = log or (lambda _message: None)
    total = sum(len(c['sentences']) for c in chapters)
    title = ' '.join(str(title or '').split()) or 'Sesli kitap'
    work = Path(engines.app_dir) / WORK_DIR / safe_name(book or hashlib.sha1(title.encode('utf-8')).hexdigest()[:16], 'kitap', 40)
    work.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='aktar-sesli-kitap-'))
    done_before = 0

    def check():
        if cancel is not None and cancel.is_set():
            raise Stopped('Sesli kitap kaydı durduruldu.')

    try:
        art = cover_file(cover, scratch)
        if fmt == 'mp3':
            folder = Path(target) / safe_name(title)
            folder.mkdir(parents=True, exist_ok=True)
        parts = []
        width = max(2, len(str(len(chapters))))
        for number, chapter in enumerate(chapters, 1):
            check()
            count = len(chapter['sentences'])
            key = chapter_key(engines, chapter, speed, language)
            stored = work / f'{number:04d}-{key}.m4a'
            seconds_file = stored.with_suffix('.sure')
            if fmt == 'm4b' and stored.exists() and seconds_file.exists():
                parts.append((stored, chapter['title'], float(seconds_file.read_text(encoding='utf-8'))))
                done_before += count
                if progress:
                    progress(done_before, total, number, len(chapters))
                continue
            wav = scratch / f'{number:04d}.wav'

            def step(done, _total, base=done_before, no=number):
                if progress:
                    progress(base + done, total, no, len(chapters))

            try:
                engines.export(chapter['sentences'], speed, wav, step, book, language, chapter['gaps'], cancel=cancel)
            except Cancelled as error:
                raise Stopped(str(error)) from error
            check()
            seconds = wav_seconds(wav)
            if fmt == 'mp3':
                name = f'{number:0{width}d} - {safe_name(chapter["title"], f"Bölüm {number}", 80)}.mp3'
                tags = {'title': chapter['title'], 'album': title, 'artist': author, 'album_artist': author,
                        'track': f'{number}/{len(chapters)}', 'genre': 'Audiobook'}
                _run(encode_command(wav, folder / name, 'mp3', tags, art))
            else:
                for old in work.glob(f'{number:04d}-*'):
                    old.unlink()
                partial = stored.with_suffix('.part')
                _run(encode_command(wav, partial, 'm4a'))
                os.replace(partial, stored)
                seconds_file.write_text(f'{seconds:.3f}', encoding='utf-8')
                parts.append((stored, chapter['title'], seconds))
            wav.unlink()
            done_before += count
            log(f'Sesli kitap: {number}/{len(chapters)} bölüm hazır ({chapter["title"]}).')
        check()
        if fmt == 'mp3':
            return {'output': str(folder), 'chapters': len(chapters)}
        listing = scratch / 'liste.txt'
        listing.write_text(concat_list([p[0] for p in parts]), encoding='utf-8')
        metadata = scratch / 'meta.txt'
        metadata.write_text(ffmetadata(title, author, [(p[1], p[2]) for p in parts]), encoding='utf-8')
        target = Path(target)
        partial = target.with_name(target.name + '.part')
        try:
            _run(join_command(listing, metadata, partial, art))
        except RuntimeError:
            if not art:
                raise
            log('Sesli kitap: kapak eklenemedi, kapaksız yazılıyor.')
            _run(join_command(listing, metadata, partial))
        os.replace(partial, target)
        shutil.rmtree(work, ignore_errors=True)   # bitti: saklanan bolum parcalari artik gerekmez
        return {'output': str(target), 'chapters': len(chapters)}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
