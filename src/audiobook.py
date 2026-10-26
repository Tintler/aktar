"""Sesli kitap disa aktarma (F141): okuyucudaki kitabi bolum bolum seslendirip tek dosyaya yazar.

Bicimler:
  - 'm4b': tek dosya, AAC; bolum isaretleri (ffmetadata) ve kapak resmi ile. Telefon ve sesli kitap
    uygulamalari bolumleri ayri gosterir.
  - 'mp3': secilen klasore bolum basina bir MP3 (ID3 etiketleri: baslik, albüm, yazar, parca no, kapak).
  - 'mp4' (F207): M4B'nin sesi + kitap gorselleri (book_art) goruntu olarak; her gorsel sahnesinin baslangic
    cumlesi okunurken gelir (tam ekran okuyucunun Gorselli arka plani gibi), bolum isaretleri de vardir.
    Gorsel 1920x1080 kareye sigdirilir, bos kalan yer ayni gorselin bulanik buyutulmus hali; ilk sahneye kadar
    kapak (yoksa siyah).

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
FORMATS = ('m4b', 'mp3', 'mp4')
AAC_BITRATE = '64k'
MP3_BITRATE = '96k'
VIDEO_SIZE = (1920, 1080)
VIDEO_FPS = 2          # duragan gorseller: saniyede iki kare gorsel degisimine yeter, dosya ve sure kucuk kalir
VIDEO_GOP = 240        # 2 dakikada bir anahtar kare (gorsel degisince x264 kendisi koyar): 10 sn'de birde 10 dakikalik
                       # video 9 kat buyuktu (26,7 MB / 3 MB); duragan karede ileri sarma yine aninda
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


class Stopped(RuntimeError):
    """Kullanici sesli kitap kaydini durdurdu."""


def safe_name(text, fallback='kitap', limit=100):
    name = ' '.join(_UNSAFE.sub(' ', str(text or '')).split()).strip(' .')
    return name[:limit].rstrip(' .') or fallback


def chapter_list(chapters):
    """Gelen bolumleri temizler: [{'title', 'sentences', 'gaps', 'breaks'}]; metni olmayanlar atlanir.
    F186 'breaks': paragraf sonu cumleler (okuyucunun gruplari); verilmediyse None (cumle cumle).
    F207 'images': [[cumle_no, gorsel_yolu], ...] (mp4); cumle numarasi temizlenmis listeye cevrilir, bos cumlede
    bir sonraki cumleye kayar."""
    result = []
    for number, chapter in enumerate(chapters or [], 1):
        sentences = [' '.join(str(s).split()) for s in (chapter or {}).get('sentences') or []]
        gaps = list((chapter or {}).get('gaps') or [])
        raw_breaks = (chapter or {}).get('breaks')
        pairs = [(text, gaps[i] if i < len(gaps) else None, i) for i, text in enumerate(sentences) if text]
        if not pairs:
            continue
        title = ' '.join(str((chapter or {}).get('title') or '').split()) or f'Bölüm {number}'
        breaks = None
        if raw_breaks is not None:
            ends = {int(b) for b in raw_breaks}
            breaks = [n for n, pair in enumerate(pairs) if pair[2] in ends]
        images = []
        for item in (chapter or {}).get('images') or []:
            try:
                index, path = int(item[0]), str(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            n = next((n for n, pair in enumerate(pairs) if pair[2] >= index), None)
            if n is not None and path:
                images.append((n, path))
        result.append({'title': title[:200], 'sentences': [p[0] for p in pairs], 'gaps': [p[1] for p in pairs],
                       'breaks': breaks, 'images': sorted(images, key=lambda item: item[0])})
    return result


def image_timeline(chapters, first=None):
    """[(bolum_baslangici_sn, bolum_suresi_sn, {cumle_no: sn}, [(cumle_no, gorsel)])] -> [(gorsel ya da None, sure)]
    ardisik; ayni gorsel tekrar edince birlesir. `first`: ilk sahneye kadar gosterilen (kapak), None siyah."""
    events, total = [(0.0, first)], 0.0
    for begin, seconds, starts, images in chapters:
        for index, path in images:
            at = begin + float(starts.get(index, starts.get(str(index), 0.0)))
            events.append((min(max(at, begin), begin + seconds), path))
        total = begin + seconds
    events.sort(key=lambda event: event[0])
    timeline = []
    for n, (at, path) in enumerate(events):
        end = events[n + 1][0] if n + 1 < len(events) else total
        if end - at <= 0.0005:
            continue
        if timeline and timeline[-1][0] == path:
            timeline[-1] = (path, timeline[-1][1] + end - at)
        else:
            timeline.append((path, end - at))
    return timeline or [(first, max(total, 0.001))]


def frame_command(source, target, size=VIDEO_SIZE):
    """Gorseli kareye sigdirir; bos kalan yer ayni gorselin bulanik, koyulastirilmis buyutulmus hali.
    source None: siyah kare."""
    width, height = size
    command = [media.ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'error', '-y']
    if source is None:
        return command + ['-f', 'lavfi', '-i', f'color=c=black:s={width}x{height}', '-frames:v', '1', str(target)]
    graph = (f'[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},'
             f'boxblur=40:2,eq=brightness=-0.18[bg];'
             f'[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];'
             f'[bg][fg]overlay=(W-w)/2:(H-h)/2,format=rgb24')
    return command + ['-i', str(source), '-filter_complex', graph, '-frames:v', '1', str(target)]


def slideshow_list(timeline):
    """[(kare_yolu, sure)] -> ffmpeg concat listesi (son kare tekrar yazilir: concat son sureyi yoksaymasin)."""
    lines = []
    for path, seconds in timeline:
        lines.append(concat_list([path]) + f'duration {max(seconds, 0.001):.3f}\n')
    return ''.join(lines) + concat_list([timeline[-1][0]])


def video_command(frames, listing, metadata, target, seconds):
    """Kare listesi + bolum m4a'lari (kopya) + bolum isaretleri -> MP4 (H.264 duragan gorsel)."""
    return [media.ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'error', '-y', '-progress', 'pipe:1', '-nostats',
            '-f', 'concat', '-safe', '0', '-i', str(frames),
            '-f', 'concat', '-safe', '0', '-i', str(listing), '-i', str(metadata),
            '-map', '0:v', '-map', '1:a', '-map_metadata', '2', '-map_chapters', '2',
            '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'stillimage', '-crf', '24', '-pix_fmt', 'yuv420p',
            '-vf', f'fps={VIDEO_FPS}', '-g', str(VIDEO_GOP), '-c:a', 'copy', '-t', f'{seconds:.3f}',
            '-movflags', '+faststart', '-f', 'mp4', str(target)]


def _run_progress(command, seconds, report):
    """FFmpeg'i -progress ciktisini okuyarak calistirir: report(0..1). cancel icin report Stopped atabilir."""
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
                                   text=True, encoding='utf-8', errors='replace', **kwargs)
        try:
            with process.stdout:
                for line in process.stdout:
                    key, _, value = line.strip().partition('=')
                    if key == 'out_time_us' and value.isdigit() and seconds > 0:
                        report(min(1.0, int(value) / 1e6 / seconds))
        except BaseException:
            process.kill()
            process.wait()
            raise
        code = process.wait()
        if code != 0:
            errors.seek(0)
            text = errors.read().decode('utf-8', 'replace').strip()
            raise RuntimeError('FFmpeg videoyu yazamadı: ' + (text[-500:] or f'çıkış kodu {code}'))


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


def _write_video(parts, listing, metadata, target, first, scratch, check, report=None, log=None):
    """F207: bolum parcalarinin sesi + sahne gorselleri -> MP4. Her farkli gorsel bir kez kareye cevrilir."""
    chapters, begin = [], 0.0
    for _path, _title, seconds, starts, images in parts:
        chapters.append((begin, seconds, starts, images))
        begin += seconds
    timeline = image_timeline(chapters, str(first) if first else None)
    frames = {}
    for path, _seconds in timeline:
        if path in frames:
            continue
        check()
        frame = scratch / f'kare-{len(frames):04d}.png'
        try:
            _run(frame_command(path, frame))
        except RuntimeError as error:
            if path is None:
                raise
            if log:
                log(f'Sesli kitap videosu: görsel okunamadı, siyah kare kullanılıyor ({Path(path).name}): {error}')
            _run(frame_command(None, frame))
        frames[path] = frame
    listing_frames = scratch / 'kareler.txt'
    listing_frames.write_text(slideshow_list([(frames[p], s) for p, s in timeline]), encoding='utf-8')
    if log:
        log(f'Sesli kitap videosu: {len(frames)} görsel, görüntü yazılıyor.')

    def step(fraction):
        check()
        if report:
            report(fraction)

    _run_progress(video_command(listing_frames, listing, metadata, target, begin), begin, step)


def chapter_key(engines, chapter, speed, language, override=None, book=None):
    """Bolumun sesini belirleyen her sey (ses, ayarlar, hiz, metin, duraklar): saklanan parca gecerli mi."""
    engine_id, voice_id = engines.choice(language, override)
    options = engines._voice_options(engine_id, voice_id, override) if engine_id else {}
    parts = [engine_id, voice_id, options, round(float(speed), 2), chapter['sentences'], chapter['gaps']]
    tags = [engines.emotion_tag(book, text, language, override) for text in chapter['sentences']] if book else []
    if any(tags):    # F168: Drama 3 duygu etiketleri
        parts.append(tags)
    if chapter.get('breaks') is not None and engines.group_chars(language, override):   # F186: cumle gruplari
        parts.append({'groups': [g[:2] for g in engines.plan(None, chapter['sentences'], speed, language,
                                                              chapter['breaks'], override)]})
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def build(engines, chapters, target, fmt='m4b', title='', author='', cover=None, speed=1.0, book=None,
          language='tr', progress=None, cancel=None, log=None, video_progress=None, carry=None):
    """Sesli kitabi yazar (bloklar). progress(done_sentences, total_sentences, chapter_no, chapter_count).
    m4b/mp4: `target` dosya yolu; mp3: `target` klasor (icine '<kitap>' klasoru acilir). Donen: {'output', 'chapters'}.
    F207 mp4: bolumlerin 'images' sahneleri goruntu olur; `carry` ilk sahneden onceki gorsel (yoksa kapak, o da
    yoksa siyah); ses bittikten sonra goruntu yazilirken video_progress(0..1)."""
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
            key = chapter_key(engines, chapter, speed, language, book=book)
            stored = work / f'{number:04d}-{key}.m4a'
            seconds_file = stored.with_suffix('.sure')
            times_file = stored.with_suffix('.zaman')    # F207: cumle baslangiclari (mp4 gorselleri icin)
            if (fmt != 'mp3' and stored.exists() and seconds_file.exists()
                    and (fmt == 'm4b' or times_file.exists())):
                starts = json.loads(times_file.read_text(encoding='utf-8')) if times_file.exists() else {}
                parts.append((stored, chapter['title'], float(seconds_file.read_text(encoding='utf-8')),
                              {int(k): v for k, v in starts.items()}, chapter['images']))
                done_before += count
                if progress:
                    progress(done_before, total, number, len(chapters))
                continue
            wav = scratch / f'{number:04d}.wav'

            def step(done, _total, base=done_before, no=number):
                if progress:
                    progress(base + done, total, no, len(chapters))

            starts = {}
            try:
                engines.export(chapter['sentences'], speed, wav, step, book, language, chapter['gaps'], cancel=cancel,
                               breaks=chapter.get('breaks'), starts=starts)
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
                times_file.write_text(json.dumps(starts), encoding='utf-8')
                parts.append((stored, chapter['title'], seconds, starts, chapter['images']))
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
        if fmt == 'mp4':
            _write_video(parts, listing, metadata, partial, carry or art, scratch, check, video_progress, log)
            os.replace(partial, target)
            shutil.rmtree(work, ignore_errors=True)
            return {'output': str(target), 'chapters': len(chapters)}
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
