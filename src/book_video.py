"""Sesli kitap videosu (F208): tam ekran okuyucunun (web/src/components/FocusReader.svelte) gorunumu kare kare.

Okunan parca (motorun tek istekte okudugu cumle grubu; Drama 3 TR disinda tek cumle) ekranin ortasinda; arka plan
duz sayfa rengi ya da kitap gorseli (F197): gorsel ustte ve altta acik, ortaya dogru sayfa rengine koyulasan yazi
bandiyla, yazinin cevresinde sayfa renginde parilti. Gecisler okuyucudakiyle ayni egrilerle: yazi Kayma (eskisi
yukari, yenisi asagidan) / Belirme / yok; gorsel 1,2 sn capraz gecis ya da kesme. Olculer okuyucunun 1920x1080
tam ekranina gore (ust satir ve dugmeler fare durunca gizlenir ama yer kaplar), 720p'de oranlanir.

Kareler Pillow ile cizilir: duragan kare bir kez yazilir ve ffmpeg concat listesinde suresiyle durur, yalnizca gecis
kareleri tek tek cizilir. Bolum basina bir H.264 parcasi (sessiz) uretilir; audiobook.build saklar ve birlestirir.
"""
from __future__ import annotations

import io
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import media
from app_core import ROOT

FONT_DIR = ROOT / 'assets' / 'fonts'   # exe'de PyInstaller'in acildigi klasor (DERLE.cmd assets'i ekler)
FONTS = {'serif': 'literata.ttf', 'sans': 'inter.ttf'}   # okuyucunun Literata / Inter'i, latin + latin-ext
VERSION = 1             # cizim degisince artir: saklanan bolum parcalari yeniden cizilir
HEIGHTS = (1080, 720)
DEFAULTS = {'background': 'art', 'text': True, 'motion': 'slide', 'art_motion': 'fade', 'size': 44,
            'colors': {'bg': '#000000', 'ink': '#f2f2f2'}, 'band': 0.85, 'font': 'serif', 'height': 1080}
SIZES = (24, 120)
FPS_MOTION = 25        # gecisli: okuyucudaki gibi akici
FPS_STILL = 2          # gecissiz: kare yalnizca parca degisince degisir
GOP_SECONDS = 60       # dakikada bir anahtar kare (gecislerde x264 kendisi de koyar)
JPEG_QUALITY = 90

# 1080 yuksek ekranda okuyucu: ust satir 62, dugmeler 76 + ilerleme cubugu 3 piksel; sahne yanlarda 6vw bosluk,
# yazi en fazla 1400 piksel genis, satir yuksekligi 1.45; sigmayan grupta yazi 2'ser kuculur (en az 16).
TOP, BOTTOM, SIDE, MAX_WIDTH, LEADING = 62, 79, 0.06, 1400, 1.45
SLIDE = {'leave': 0.55, 'delay': 0.12, 'enter': 0.65, 'shift': 60}
FADE = {'leave': 0.55, 'delay': 0.25, 'enter': 0.9, 'out_scale': 0.96, 'in_scale': 1.03}
ART_FADE = 1.2
BAND_STOPS = ((0.0, 0.0), (0.16, 0.55), (0.36, 1.0), (0.64, 1.0), (0.84, 0.55), (1.0, 0.0))


def cubic_out(t):
    return (t - 1) ** 3 + 1


def cubic_in_out(t):
    return 4 * t ** 3 if t < 0.5 else 0.5 * (2 * t - 2) ** 3 + 1


def css_ease(t, p1=(0.25, 0.1), p2=(0.25, 1.0)):
    """CSS 'ease' = cubic-bezier(.25, .1, .25, 1): x(s) = t cozulur, y(s) doner."""
    if t <= 0 or t >= 1:
        return min(max(t, 0.0), 1.0)
    lo, hi = 0.0, 1.0
    for _ in range(30):
        s = (lo + hi) / 2
        x = 3 * (1 - s) ** 2 * s * p1[0] + 3 * (1 - s) * s ** 2 * p2[0] + s ** 3
        lo, hi = (s, hi) if x < t else (lo, s)
    s = (lo + hi) / 2
    return 3 * (1 - s) ** 2 * s * p1[1] + 3 * (1 - s) * s ** 2 * p2[1] + s ** 3


def _clamp(value, low, high):
    return max(low, min(high, value))


def parse_color(value, fallback=(0, 0, 0)):
    """'#rgb', '#rrggbb', 'rgb(r, g, b)' ya da 'rgba(...)' -> (r, g, b)."""
    text = str(value or '').strip().lower()
    match = re.fullmatch(r'#([0-9a-f]{3}|[0-9a-f]{6})', text)
    if match:
        raw = match.group(1)
        raw = ''.join(c * 2 for c in raw) if len(raw) == 3 else raw
        return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))
    match = re.fullmatch(r'rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+).*\)', text)
    if match:
        return tuple(_clamp(int(round(float(match.group(i)))), 0, 255) for i in (1, 2, 3))
    return tuple(fallback)


def options(raw=None):
    """Arayuzden gelen secenekler -> temiz sozluk (bilinmeyen deger varsayilana doner)."""
    raw = dict(raw or {})
    result = dict(DEFAULTS)
    result['background'] = raw.get('background') if raw.get('background') in ('art', 'plain') else DEFAULTS['background']
    result['text'] = bool(raw.get('text', DEFAULTS['text']))
    result['motion'] = raw.get('motion') if raw.get('motion') in ('slide', 'fade', 'none') else DEFAULTS['motion']
    result['art_motion'] = raw.get('art_motion') if raw.get('art_motion') in ('fade', 'cut') else DEFAULTS['art_motion']
    try:
        result['size'] = int(_clamp(int(float(raw.get('size', DEFAULTS['size']))), *SIZES))
    except (TypeError, ValueError):
        pass
    try:
        result['band'] = round(_clamp(float(raw.get('band', DEFAULTS['band'])), 0.0, 1.0), 3)
    except (TypeError, ValueError):
        pass
    colors = raw.get('colors') if isinstance(raw.get('colors'), dict) else {}
    result['colors'] = {'bg': '#%02x%02x%02x' % parse_color(colors.get('bg'), parse_color(DEFAULTS['colors']['bg'])),
                        'ink': '#%02x%02x%02x' % parse_color(colors.get('ink'), parse_color(DEFAULTS['colors']['ink']))}
    result['font'] = raw.get('font') if raw.get('font') in FONTS else DEFAULTS['font']
    try:
        height = int(raw.get('height', DEFAULTS['height']))
    except (TypeError, ValueError):
        height = DEFAULTS['height']
    result['height'] = height if height in HEIGHTS else DEFAULTS['height']
    return result


def fps_for(opts):
    moving = (opts['text'] and opts['motion'] != 'none') or (opts['background'] == 'art' and opts['art_motion'] == 'fade')
    return FPS_MOTION if moving else FPS_STILL


class Renderer:
    """Bir secenek takimi icin kareleri cizer; arka planlar ve yazi katmanlari onbellekte tutulur."""

    def __init__(self, opts):
        self.opts = options(opts)
        self.height = self.opts['height']
        self.width = self.height * 16 // 9
        self.scale = self.height / 1080
        self.paper = parse_color(self.opts['colors']['bg'])
        self.ink = parse_color(self.opts['colors']['ink'])
        self.art = self.opts['background'] == 'art'
        self._fonts = {}
        self._raw = {}
        self._backgrounds = {}
        self._layers = {}
        stage_top, stage_bottom = TOP * self.scale, self.height - BOTTOM * self.scale
        self.stage_height = stage_bottom - stage_top
        self.center_y = (stage_top + stage_bottom) / 2
        self.max_width = min(MAX_WIDTH * self.scale, self.width * (1 - 2 * SIDE))
        self._veil = self._band_mask()

    # ---------------------------------------------------------------- arka plan
    def _band_mask(self):
        band = self.opts['band']
        column = []
        for y in range(self.height):
            at = (y + 0.5) / self.height
            for (x0, a0), (x1, a1) in zip(BAND_STOPS, BAND_STOPS[1:]):
                if x0 <= at <= x1:
                    column.append(int(round(255 * band * (a0 + (a1 - a0) * (at - x0) / (x1 - x0)))))
                    break
        mask = Image.new('L', (1, self.height))
        mask.putdata(column)
        return mask.resize((self.width, self.height))

    def _cover(self, path):
        """Gorsel ekrani kaplar (CSS 'center / cover'); okunamazsa None."""
        if path not in self._raw:
            if len(self._raw) > 3:
                self._raw.pop(next(iter(self._raw)))
            try:
                with Image.open(path) as image:
                    self._raw[path] = ImageOps.fit(image.convert('RGB'), (self.width, self.height), Image.LANCZOS)
            except (OSError, ValueError):
                self._raw[path] = None
        return self._raw[path]

    def _plain(self):
        return Image.new('RGB', (self.width, self.height), self.paper)

    def background(self, path=None, previous=None, phase=None):
        """Yazinin arkasi: duz sayfa rengi ya da gorsel + bant. `previous`/`phase`: capraz gecisin ortasi
        (okuyucuda iki katman sayfa renginin ustunde birinin opakligi artarken digerininki azalir)."""
        if not self.art:
            key = ('plain',)
        elif phase is None:
            key = ('art', path)
        else:
            key = None
        if key is not None and key in self._backgrounds:
            return self._backgrounds[key]
        if not self.art:
            image = self._plain()
        else:
            plain = self._plain()
            new = self._cover(path) if path else None
            if phase is None:
                image = new if new is not None else plain
            else:
                e = css_ease(phase)
                old = self._cover(previous) if previous else None
                fading = Image.blend(old if old is not None else plain, plain, e)
                image = Image.blend(fading, new if new is not None else plain, e)
            image = Image.composite(plain, image, self._veil) if image is not plain else image
        if key is not None:
            if len(self._backgrounds) > 4:
                self._backgrounds.pop(next(iter(self._backgrounds)))
            self._backgrounds[key] = image
        return image

    # ---------------------------------------------------------------- yazi
    def _font(self, size):
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(str(FONT_DIR / FONTS[self.opts['font']]), size)
        return self._fonts[size]

    def _lines(self, words, font):
        lines, line = [], ''
        for word in words:
            trial = f'{line} {word}' if line else word
            if line and font.getlength(trial) > self.max_width:
                lines.append(line)
                line = word
            else:
                line = trial
        return lines + ([line] if line else [])

    def layout(self, text):
        """(yazi boyu, satirlar): secilen boyut ust sinir, sahneye sigmayan parca 2'ser kuculur (okuyucunun fit'i)."""
        words = str(text or '').split()
        size = max(1, int(round(self.opts['size'] * self.scale)))
        least = max(1, int(round(16 * self.scale)))
        step = max(1, int(round(2 * self.scale)))
        while True:
            lines = self._lines(words, self._font(size))
            if size <= least or len(lines) * size * LEADING <= self.stage_height - 16 * self.scale:
                return size, lines
            size -= step

    def text_layer(self, text):
        """Parcanin RGBA katmani ve sol ust kosesi (ekranda ortali); gorselli arka planda sayfa renginde parilti."""
        if text in self._layers:
            return self._layers[text]
        size, lines = self.layout(text)
        font = self._font(size)
        line_height = size * LEADING
        ascent, descent = font.getmetrics()
        pad = int(round(40 * self.scale))
        width = int(self.max_width) + 2 * pad
        height = int(round(len(lines) * line_height)) + 2 * pad
        mask = Image.new('L', (width, height), 0)
        draw = ImageDraw.Draw(mask)
        for n, line in enumerate(lines):
            baseline = pad + n * line_height + (line_height - ascent - descent) / 2 + ascent
            draw.text((width / 2, baseline), line, font=font, fill=255, anchor='ms')
        layer = Image.new('RGBA', (width, height), self.ink + (0,))
        if self.art:   # text-shadow: 0 0 18px sayfa %90, 0 1px 2px sayfa %80
            glow = Image.new('RGBA', (width, height), self.paper + (0,))
            glow.putalpha(mask.filter(ImageFilter.GaussianBlur(9 * self.scale)).point(lambda v: int(v * 0.9)))
            near = Image.new('RGBA', (width, height), self.paper + (0,))
            shifted = Image.new('L', (width, height), 0)
            shifted.paste(mask, (0, max(1, int(round(self.scale)))))
            near.putalpha(shifted.filter(ImageFilter.GaussianBlur(max(1, self.scale))).point(lambda v: int(v * 0.8)))
            layer = Image.alpha_composite(glow, near)
        ink = Image.new('RGBA', (width, height), self.ink + (0,))
        ink.putalpha(mask)
        layer = Image.alpha_composite(layer, ink)
        position = (int((self.width - width) / 2), int(round(self.center_y - height / 2)))
        if len(self._layers) > 8:
            self._layers.pop(next(iter(self._layers)))
        self._layers[text] = (layer, position)
        return self._layers[text]

    def _paste(self, base, text, opacity=1.0, dy=0.0, scale=1.0):
        if not text or opacity <= 0.002:
            return
        layer, (x, y) = self.text_layer(text)
        if abs(scale - 1) > 0.0005:
            w, h = layer.size
            size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
            x, y = int(round(x + (w - size[0]) / 2)), int(round(y + (h - size[1]) / 2))
            layer = layer.resize(size, Image.BICUBIC)
        if opacity < 0.998:
            layer = layer.copy()
            layer.putalpha(layer.getchannel('A').point(lambda v: int(v * opacity)))
        base.paste(layer, (x, int(round(y + dy))), layer)

    def frame(self, text=None, path=None, old_text=None, text_phase=None, previous=None, art_phase=None):
        """Tek kare (RGB). text_phase: parca degisiminden beri gecen saniye (None: duragan); art_phase: 0..1 gorsel
        gecisinin neresi (None: duragan)."""
        base = self.background(path, previous, art_phase).copy()
        if not self.opts['text']:
            return base
        motion = self.opts['motion']
        if text_phase is None or motion == 'none':
            self._paste(base, text)
            return base
        s = self.scale
        if motion == 'slide':
            out = _clamp(text_phase / SLIDE['leave'], 0, 1)
            t_out = 1 - cubic_in_out(out)
            self._paste(base, old_text, t_out, -SLIDE['shift'] * s * (1 - t_out))
            t_in = cubic_out(_clamp((text_phase - SLIDE['delay']) / SLIDE['enter'], 0, 1))
            self._paste(base, text, t_in, SLIDE['shift'] * s * (1 - t_in))
        else:
            t_out = cubic_out(1 - _clamp(text_phase / FADE['leave'], 0, 1))
            self._paste(base, old_text, t_out, 0, FADE['out_scale'] + (1 - FADE['out_scale']) * t_out)
            t_in = cubic_out(_clamp((text_phase - FADE['delay']) / FADE['enter'], 0, 1))
            self._paste(base, text, t_in, 0, FADE['in_scale'] + (1 - FADE['in_scale']) * t_in)
        return base

    def text_seconds(self):
        motion = self.opts['motion']
        if not self.opts['text'] or motion == 'none':
            return 0.0
        spec = SLIDE if motion == 'slide' else FADE
        return max(spec['leave'], spec['delay'] + spec['enter'])

    def preview(self, text, path=None, width=960):
        """Ayar penceresi icin duragan kare: JPEG baytlari."""
        image = self.frame(text, path)
        if width and image.width > width:
            image = image.resize((width, width * image.height // image.width), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, 'JPEG', quality=85)
        return buffer.getvalue()


def chapter_states(chunks, images, carry, begin, first, last, fps, renderer, before=None):
    """Bolumun kareleri [(durum, kare sayisi)]: ayni duragan durum birlesir. chunks: [(metin, baslangic_sn)],
    images: [(baslangic_sn, yol)] bolum basina gore; first/last: kuresel kare numaralari [first, last).
    before: onceki bolumun son parcasi (bolum basinda okuyucudaki gibi gecisle gider)."""
    text_span = renderer.text_seconds()
    art_span = ART_FADE if renderer.art and renderer.opts['art_motion'] == 'fade' else 0.0
    events = [(float('-inf'), carry)] + sorted(images, key=lambda item: item[0])
    states = []
    k = j = 0
    for frame in range(first, last):
        t = max(0.0, frame / fps - begin)
        while k + 1 < len(chunks) and chunks[k + 1][1] <= t + 1e-6:
            k += 1
        while j + 1 < len(events) and events[j + 1][0] <= t + 1e-6:
            j += 1
        text = chunks[k][0] if chunks else None
        since = t - chunks[k][1] if chunks else 0.0
        text_phase = round(since, 4) if chunks and since < text_span else None
        old_text = chunks[k - 1][0] if chunks and k > 0 else before
        path = events[j][1]
        art_phase = None
        if art_span and j > 0 and t - events[j][0] < art_span and events[j - 1][1] != path:
            art_phase = round((t - events[j][0]) / art_span, 4)
        state = (text, old_text if text_phase is not None else None, text_phase, path,
                 events[j - 1][1] if art_phase is not None else None, art_phase)
        if states and states[-1][0] == state and text_phase is None and art_phase is None:
            states[-1][1] += 1
        else:
            states.append([state, 1])
    return states


def render_chapter(renderer, states, folder, fps, check=None, report=None):
    """Kareleri JPEG olarak yazar ve ffmpeg concat listesini dondurur (durumlar chapter_states'ten)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    total = sum(count for _state, count in states) or 1
    done = 0
    for n, ((text, old_text, text_phase, path, previous, art_phase), count) in enumerate(states):
        if check:
            check()
        target = folder / f'{n:06d}.jpg'
        renderer.frame(text, path, old_text, text_phase, previous, art_phase).save(target, 'JPEG', quality=JPEG_QUALITY)
        lines.append("file '" + str(target.resolve()).replace("'", "'\\''") + f"'\nduration {count / fps:.6f}\n")
        done += count
        if report:
            report(done / total)
    if lines:
        lines.append(lines[-1].split('\n')[0] + '\n')
    listing = folder / 'kareler.txt'
    listing.write_text(''.join(lines), encoding='utf-8')
    return listing, total


def segment_command(listing, target, fps, frames):
    """Kare listesi -> sessiz H.264 parca (tam `frames` kare: bolum sinirlari kare izgarasina oturur)."""
    return [media.ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'error', '-y', '-progress', 'pipe:1', '-nostats',
            '-f', 'concat', '-safe', '0', '-i', str(listing), '-vf', f'fps={fps},format=yuv420p',
            '-frames:v', str(frames), '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
            '-g', str(fps * GOP_SECONDS), '-movflags', '+faststart', '-f', 'mp4', str(target)]


def mux_command(segments, audio, metadata, target):
    """Bolum parcalari (goruntu) + bolum m4a'lari (ses) + bolum isaretleri -> MP4, yeniden kodlamadan."""
    return [media.ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'error', '-y',
            '-f', 'concat', '-safe', '0', '-i', str(segments), '-f', 'concat', '-safe', '0', '-i', str(audio),
            '-i', str(metadata), '-map', '0:v', '-map', '1:a', '-map_metadata', '2', '-map_chapters', '2',
            '-c', 'copy', '-movflags', '+faststart', '-f', 'mp4', str(target)]


def image_stamp(path):
    """Gorsel degisince bolum parcasi yeniden uretilsin: yol + boyut + degisme zamani."""
    try:
        info = os.stat(path)
        return [str(path), info.st_size, int(info.st_mtime)]
    except (OSError, TypeError):
        return [str(path), 0, 0]
