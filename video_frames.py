"""Videonun goruntusunu okuma (F114): sahne degisiminde alinan karelerin yazisi ve kisa betimi.

Akis:
  1. FFmpeg yalniz anahtar kareleri cozer (-skip_frame nokey, hizli) ve goruntu degisince
     (sahne puani > SCENE) ya da en gec MAX_GAP saniyede bir kare yazar.
  2. Birbirinin aynisi kareler (8x8 fark ozeti, en fazla HASH_DISTANCE bit fark) atilir;
     ders/sunum videolarinda bu genelde saatte birkac on kareye iner.
  3. Her kare: OCR motoru Tesseract ya da OCR modeliyse once yazisi okunur; yeterince yazi
     varsa (slayt, kod) betim o yazidir. Yoksa gorsel model kareyi kisaca betimler.
  4. Betimler qa.visual_path'e yazilir (her karede; yarida kalirsa kaldigi yerden devam eder).
     qa.cached_sessions bunlari oturuma ekler; soru-cevap, arama ve indeks '[Görüntü]'
     satirlari olarak gorur.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import documents
import media
import qa
from app_core import save_json

VERSION = 1
SCENE = 0.3            # ffmpeg sahne puani esigi (0-1)
MAX_GAP = 120          # degisim olmasa da en gec bu kadar saniyede bir kare
WIDTH = 1280           # kare genisligi (yazi okunabilsin)
HASH_DISTANCE = 6      # 64 bitlik ozette bu kadar ya da daha az fark: ayni kare
MIN_TEXT = 60          # OCR bu kadar karakterden azsa kare gorsel modelle betimlenir
TEXT_LIMIT = 1200      # kare basina saklanan en fazla metin
FRAME_PROMPT = ('Bu kare bir videodan alındı. Türkçe olarak 1-3 cümleyle ekranda ne olduğunu anlat '
                '(sahne, kişiler, nesneler, grafik ya da diyagram). Ekranda okunabilir yazı, slayt, '
                'kod ya da formül varsa onu da aynen yaz. Yalnız açıklamayı yaz.')
_TIME = re.compile(r'pts_time:\s*([0-9.]+)')


def extract(video, folder, cancelled=None):
    """Kareleri `folder`a JPEG olarak yazar; [(saniye, yol)] zaman sirasiyla."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    select = f"select='isnan(prev_selected_t)+gt(scene\\,{SCENE})+gte(t-prev_selected_t\\,{MAX_GAP})'"
    command = [media.ffmpeg_path(), '-hide_banner', '-nostdin', '-skip_frame', 'nokey', '-i', str(video),
               '-an', '-sn', '-dn', '-vf', f'{select},scale=\'min({WIDTH},iw)\':-2,showinfo',
               '-fps_mode', 'vfr', '-q:v', '3', str(folder / '%05d.jpg')]
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}  # konsol penceresi acilmasin
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                               encoding='utf-8', errors='replace', **kwargs)
    times, tail = [], []
    for line in process.stderr:
        if cancelled and cancelled():
            process.kill()
            break
        if 'showinfo' in line:
            match = _TIME.search(line)
            if match:
                times.append(float(match.group(1)))
        else:
            tail = (tail + [line.strip()])[-5:]
    process.stderr.close()
    code = process.wait()
    files = sorted(folder.glob('*.jpg'))
    if code != 0 and not (cancelled and cancelled()) and not files:
        raise RuntimeError('Kareler çıkarılamadı: ' + ' '.join(tail))
    return list(zip(times, files))


def fingerprint(image):
    """8x8 fark ozeti (dHash): komsu piksellerin parlaklik farki."""
    small = image.convert('L').resize((9, 8))
    pixels = small.tobytes()  # 'L' kipinde piksel basina bir bayt
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | (pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return value


def distinct(frames):
    """Bir oncekiyle neredeyse ayni kareleri atar: [(saniye, PNG baytlari)]."""
    from PIL import Image
    kept, last = [], None
    for seconds, path in frames:
        with Image.open(path) as image:
            image = image.convert('RGB')
            mark = fingerprint(image)
            if last is not None and bin(mark ^ last).count('1') <= HASH_DISTANCE:
                continue
            last = mark
            buffer = io.BytesIO()
            image.save(buffer, 'PNG')
        kept.append((seconds, buffer.getvalue()))
    return kept


def describe(png, reader, ocr=True):
    """Kare metni: once OCR (yeterince yazi varsa), yoksa gorsel modelin betimi."""
    if ocr:
        text = ' '.join(str(reader(png, documents.OCR_PROMPT) or '').split())
        if len(text) >= MIN_TEXT:
            return 'Ekrandaki yazı: ' + text[:TEXT_LIMIT]
    return ' '.join(str(reader(png, FRAME_PROMPT) or '').split())[:TEXT_LIMIT]


def read_video(video, cfg, reader, base=None, log=print, progress=None, cancelled=None):
    """Videonun karelerini okuyup betimleri kaydeder. Donen: betimlenen kare sayisi.

    `reader`: library.vision_reader(cfg) (png, istem) -> metin. Yarida kesilirse kaydedilen
    kareler korunur; bir sonraki calismada yalniz kalanlar okunur."""
    video = Path(video)
    target = qa.visual_path(video, base)
    done, complete = qa.load_visual(video, base)
    if complete:
        return len(done)
    known = {round(float(item['start']), 1) for item in done}
    ocr = documents.ocr_engine(cfg) in ('tesseract', 'model')
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='aktar-frames-'))
    try:
        log(f'Kareler çıkarılıyor: {video.name}')
        frames = distinct(extract(video, temp, cancelled))
        log(f'{video.name}: {len(frames)} farklı kare okunacak' + (' (yazı önce OCR ile)' if ocr else ''))
        results = list(done)
        for number, (seconds, png) in enumerate(frames, 1):
            if cancelled and cancelled():
                break
            if round(seconds, 1) not in known:
                text = describe(png, reader, ocr)
                if text:
                    results.append({'start': round(seconds, 2), 'text': text})
                    results.sort(key=lambda item: item['start'])
                    save_json(target, {'version': VERSION, 'video': str(video), 'frames': results, 'complete': False})
            if progress:
                progress(number, len(frames))
        finished = not (cancelled and cancelled())
        save_json(target, {'version': VERSION, 'video': str(video), 'frames': results, 'complete': finished})
        return len(results)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
