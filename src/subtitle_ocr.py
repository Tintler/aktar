"""Goruntu tabanli altyazilari okuma (F118): PGS (Blu-ray), VobSub (DVD), DVB -> metin.

Akis:
  1. FFmpeg altyazi akisini kendi cozucusuyle seffaf kareler olarak cizer (sub2video) ve her
     karenin zamanini ve sagama toplamini `showinfo` ile yazar. Renk paleti, kirpma ve
     konum FFmpeg'de cozulur; bicime ozel ayristirma gerekmez.
  2. Ardisik ayni kareler tek olaya toplanir: olay, kare degisince biter. Bos (tamamen
     seffaf) kareler satir sonudur.
  3. Her farkli goruntu bir kez okunur: yazi kirpilir, siyah zemine konup tersine cevrilir
     (beyaz zemin, koyu yazi) ve kucukse buyutulur. Okuyucu Ayarlar'daki OCR motorudur:
     Tesseract (akisin diliyle), OCR modeli ya da gorsel model.
  4. Okunan metinler onbellege her goruntude yazilir; yarida kalirsa kaldigi yerden devam eder.

Kaynak video SALT-OKUNUR; kareler gecici klasorde tutulur ve is bitince silinir.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import documents
import media
import qa
from app_core import GracefulStop, read, save_json

VERSION = 1
EMPTY = '00000000'
MAX_EVENT_SECONDS = 10.0   # silme komutu olmayan (DVD) altyazi en fazla bu kadar gorunur
MIN_HEIGHT = 90            # OCR icin yazi bu yukseklikten kucukse buyutulur
SUBTITLE_PROMPT = ('Bu görüntü bir video altyazısı. Görüntüdeki yazıyı satır satır, olduğu gibi '
                   'yaz. Çevirme, açıklama ya da yorum ekleme. Yazı yoksa hiçbir şey yazma.')
# pts_time FFmpeg 6.x'te %g ile yazilir (4.29497e+06, 1234.57): zaman pts * time_base ile hesaplanir.
_INFO = re.compile(r'\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*(-?[0-9.]+(?:[eE][-+]?\d+)?)'
                   r'.*?\bchecksum:\s*([0-9A-Fa-f]+)')
_TIME_BASE = re.compile(r'\bconfig in time_base:\s*(\d+)/(\d+)')
# ffprobe dil etiketi (ISO 639-2/1) -> Tesseract dil verisi
TESSERACT_LANGS = {
    'eng': 'eng', 'en': 'eng', 'tur': 'tur', 'tr': 'tur', 'ger': 'deu', 'deu': 'deu', 'de': 'deu',
    'fre': 'fra', 'fra': 'fra', 'fr': 'fra', 'spa': 'spa', 'es': 'spa', 'ita': 'ita', 'it': 'ita',
    'por': 'por', 'pt': 'por', 'rus': 'rus', 'ru': 'rus', 'jpn': 'jpn', 'ja': 'jpn', 'kor': 'kor',
    'ko': 'kor', 'chi': 'chi_sim', 'zho': 'chi_sim', 'zh': 'chi_sim', 'dut': 'nld', 'nld': 'nld',
    'nl': 'nld', 'ara': 'ara', 'ar': 'ara', 'pol': 'pol', 'pl': 'pol', 'swe': 'swe', 'sv': 'swe',
    'dan': 'dan', 'da': 'dan', 'fin': 'fin', 'fi': 'fin', 'nor': 'nor', 'no': 'nor', 'gre': 'ell',
    'ell': 'ell', 'el': 'ell', 'heb': 'heb', 'he': 'heb', 'hun': 'hun', 'hu': 'hun', 'cze': 'ces',
    'ces': 'ces', 'cs': 'ces', 'rum': 'ron', 'ron': 'ron', 'ro': 'ron',
}


def tesseract_lang(language):
    """Akisin dil etiketine uygun Tesseract dili; bilinmiyorsa None (ayardaki dil)."""
    return TESSERACT_LANGS.get(str(language or '').strip().lower())


def cache_path(video, stream_index, base=None):
    return qa.cache_path(video, f'image-subtitle:{int(stream_index)}:v{VERSION}', base)


def load_cached(video, stream_index, base=None):
    """Tamamlanmis OCR sonucu: {'segments', 'language', 'engine'} ya da None."""
    try:
        value = json.loads(read(cache_path(video, stream_index, base)))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not value.get('complete') or not value.get('segments'):
        return None
    return value


_READY = {}   # onbellek dosyasi -> (degisme zamani, tamam mi): oynatici durumu sik sorar


def is_ready(video, stream_index, base=None):
    """Akis OCR ile okunmus mu (dosya degismedikce yeniden okunmaz)."""
    try:
        path = cache_path(video, stream_index, base)
        stamp = path.stat().st_mtime_ns
    except OSError:
        return False
    key = str(path)
    if _READY.get(key, (None,))[0] != stamp:
        _READY[key] = (stamp, load_cached(video, stream_index, base) is not None)
    return _READY[key][1]


def _partial(video, stream_index, base=None):
    try:
        value = json.loads(read(cache_path(video, stream_index, base)))
    except (OSError, ValueError):
        return {}
    texts = value.get('texts') if isinstance(value, dict) else None
    return dict(texts) if isinstance(texts, dict) else {}


# --- kareler ---------------------------------------------------------------------
def render_frames(video, stream_index, folder, duration=0.0, progress=None, cancelled=None):
    """Altyazi akisini PNG karelere cizer. Donen: [(saniye, sagama, dosya)] zaman sirasiyla."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    command = [media.ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'info', '-i', str(video),
               '-filter_complex', f'[0:{int(stream_index)}]showinfo[o]', '-map', '[o]',
               '-fps_mode', 'passthrough', '-f', 'image2', str(folder / '%06d.png')]
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                               encoding='utf-8', errors='replace', **kwargs)
    infos, tail, time_base = [], [], None
    try:
        for line in process.stderr:
            if cancelled and cancelled():
                process.kill()
                raise GracefulStop('Altyazı okuma durduruldu.')
            match = _INFO.search(line) if 'showinfo' in line else None
            base = _TIME_BASE.search(line) if 'showinfo' in line and not match else None
            if base and int(base.group(2)):
                time_base = (int(base.group(1)), int(base.group(2)))
            elif match:
                seconds = (int(match.group(2)) * time_base[0] / time_base[1] if time_base
                           else float(match.group(3)))
                infos.append((int(match.group(1)), seconds, match.group(4).upper()))
                if progress and duration:
                    progress(min(seconds, duration), duration)
            else:
                tail = (tail + [line.strip()])[-5:]
    finally:
        process.stderr.close()
        code = process.wait()
    if code != 0 and not infos:
        raise RuntimeError('Altyazı görüntüleri çıkarılamadı: ' + ' '.join(tail))
    frames = []
    for number, seconds, checksum in infos:
        path = folder / f'{number + 1:06d}.png'
        if path.exists():
            frames.append((max(0.0, seconds), checksum, path))
    frames.sort(key=lambda item: item[0])
    return frames


def events(frames, duration=0.0):
    """Ardisik ayni kareleri olaylara toplar: [(baslangic, bitis, sagama, dosya)] (bos kareler disinda)."""
    result = []
    current = None
    for seconds, checksum, path in frames:
        if current and checksum == current[1]:
            continue
        if current and current[1] != EMPTY:
            result.append((current[0], seconds, current[1], current[2]))
        current = (seconds, checksum, path)
    if current and current[1] != EMPTY:
        end = current[0] + MAX_EVENT_SECONDS
        result.append((current[0], min(end, duration) if duration > current[0] else end, current[1], current[2]))
    limit = lambda start: duration if duration > start else float('inf')  # noqa: E731
    result = [(start, min(end, start + MAX_EVENT_SECONDS, limit(start)), checksum, path)
              for start, end, checksum, path in result]
    return [item for item in result if item[1] - item[0] >= 0.05]


def prepare_image(path):
    """Altyazi karesini OCR'a hazirlar: yazi kirpilir, beyaz zemine koyu yazi. Bossa None."""
    from PIL import Image, ImageOps
    with Image.open(path) as source:
        image = source.convert('RGBA')
    alpha = image.getchannel('A').point(lambda value: 255 if value > 24 else 0)
    box = alpha.getbbox()
    if not box:
        return None
    pad = 12
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(image.width, box[2] + pad), min(image.height, box[3] + pad))
    crop = image.crop(box)
    flat = Image.new('RGB', crop.size, (0, 0, 0))
    flat.paste(crop, mask=crop.getchannel('A'))
    gray = ImageOps.invert(flat.convert('L'))
    if gray.height < MIN_HEIGHT:
        factor = min(4.0, MIN_HEIGHT / max(1, gray.height))
        gray = gray.resize((int(gray.width * factor), int(gray.height * factor)), Image.LANCZOS)
    gray = ImageOps.expand(gray, border=16, fill=255)
    buffer = io.BytesIO()
    gray.save(buffer, 'PNG')
    return buffer.getvalue()


def clean_text(text):
    """OCR ciktisi: satir basina bosluklar sadelesir, bos satirlar ve tek basina '|' atilir."""
    lines = []
    for line in qa.strip_thinking(str(text or '')).replace('\r', '').split('\n'):
        line = ' '.join(line.replace('|', 'I').split())
        line = line.strip('`').strip()
        if line:
            lines.append(line)
    return '\n'.join(lines)


# --- okuyucu ---------------------------------------------------------------------
def reader_for(cfg, language='', log=print):
    """(png) -> metin. Ayarlardaki OCR motoru; Tesseract akisin diliyle okur."""
    engine = documents.ocr_engine(cfg)
    if engine == 'tesseract':
        lang = tesseract_lang(language)
        read_png = documents.tesseract_reader(cfg, log, lang=(lang + '+eng' if lang and lang != 'eng' else lang),
                                              psm='6')
        read_png.workers = documents.tesseract_workers()
        read_png.label = 'Tesseract'
        return read_png
    from app_core import Client
    client = Client(cfg, log=log)
    model = str(cfg.get('ocr_model', '')).strip() if engine == 'model' else ''
    prompt = str(cfg.get('ocr_model_prompt') or 'Text Recognition:') if model else SUBTITLE_PROMPT

    def read_png(png):
        return client.vision(prompt, png, model=model or None, max_tokens=512)
    read_png.workers = 1
    read_png.label = 'OCR modeli' if model else 'görü modeli'
    return read_png


def recognize(video, stream, cfg, base=None, log=print, progress=None, cancelled=None, reader=None):
    """Goruntu tabanli altyazi akisini okur (onbellekli). Donen: {'segments', 'language', 'engine'}.

    `progress(asama, islenen, toplam)`: asama 'frames' (saniye) ya da 'ocr' (goruntu).
    """
    index = int(stream['index'])
    cached = load_cached(video, index, base)
    if cached:
        log('Altyazı OCR sonucu önbellekten yüklendi.')
        return cached
    language = str(stream.get('language') or '')
    try:
        duration = float(media.probe_summary(video).get('duration') or 0.0)
    except (RuntimeError, ValueError):
        duration = 0.0
    temp = Path(tempfile.mkdtemp(prefix='aktar-subocr-'))
    try:
        log(f'Altyazı görüntüleri çıkarılıyor ({stream.get("codec", "")}, akış {index})…')
        frames = render_frames(video, index, temp, duration,
                               progress=(lambda done, total: progress('frames', done, total)) if progress else None,
                               cancelled=cancelled)
        found = events(frames, duration)
        if not found:
            raise ValueError('Altyazı akışında görüntü bulunamadı.')
        reader = reader or reader_for(cfg, language, log)
        texts = _partial(video, index, base)
        pending = list(dict.fromkeys(checksum for _, _, checksum, _ in found if checksum not in texts))
        paths = {checksum: path for _, _, checksum, path in found}
        unique = len({checksum for _, _, checksum, _ in found})
        log(f'{len(found)} altyazı satırı, {unique} farklı görüntü; {len(pending)} tanesi '
            f'{getattr(reader, "label", "OCR")} ile okunacak.')
        target = cache_path(video, index, base)
        target.parent.mkdir(parents=True, exist_ok=True)
        lock = threading.Lock()
        done = [unique - len(pending)]

        def work(checksum):
            if cancelled and cancelled():
                return
            png = prepare_image(paths[checksum])
            text = clean_text(reader(png)) if png else ''
            with lock:
                texts[checksum] = text
                done[0] += 1
                save_json(target, {'version': VERSION, 'complete': False, 'texts': texts})
                if progress:
                    progress('ocr', done[0], unique)

        workers = max(1, int(getattr(reader, 'workers', 1)))
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(work, pending))
        else:
            for checksum in pending:
                work(checksum)
        if cancelled and cancelled():
            raise GracefulStop('Altyazı okuma durduruldu.')
        segments = []
        for start, end, checksum, _ in found:
            text = texts.get(checksum, '')
            if not text:
                continue
            previous = segments[-1] if segments else None
            if previous and previous['text'] == text and start - previous['end'] < 0.15:
                previous['end'] = round(end, 3)
                continue
            segments.append({'start': round(start, 3), 'end': round(end, 3), 'text': text})
        if not segments:
            raise ValueError('Altyazı görüntülerinde okunabilir yazı bulunamadı.')
        result = {'version': VERSION, 'complete': True, 'segments': segments, 'language': language,
                  'engine': getattr(reader, 'label', ''), 'texts': texts}
        save_json(target, result)
        log(f'Altyazı okundu: {len(segments)} satır ({result["engine"]}).')
        return result
    finally:
        shutil.rmtree(temp, ignore_errors=True)
