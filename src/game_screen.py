"""Oyun cevirisi (F194): ekrandan bolge yakalama, degisim denetimi ve yazi okuma (OCR).

Yakalama Windows'ta GDI BitBlt ile yalnizca bolgenin pikselleri alinir (tam ekran degil; ~1 ms). Oyun
pencereli tam ekranda (borderless) calismalidir: ozel tam ekran kipinde masaustu bileskesi yoktur.
Okuma once Windows'un kendi OCR'i (Windows.Media.Ocr, winrt paketleri; islemcide ~10 ms, ekran kartina
yuk bindirmez), o dilde yoksa ya da Windows disinda Tesseract (documents.tesseract_reader).
Yakalanan goruntu diske yazilmaz.
"""
from __future__ import annotations

import io
import os
import re
import threading

WINDOWS = os.name == 'nt'
THUMB_WIDTH = 160          # degisim denetimi icin kucultulmus goruntu genisligi
CHANGE_LEVEL = 40          # bu kadar parlaklik farki olan piksel "degisti" sayilir
MIN_TEXT_HEIGHT = 120      # bolge bundan alcaksa OCR oncesi buyutulur

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
    _user32.GetDC.restype = wintypes.HDC
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.BitBlt.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    _gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                 ctypes.c_void_p, wintypes.UINT]
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    SRCCOPY = 0x00CC0020

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
                    ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                    ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)]


def dpi_aware():
    """Bu is parcaciginda koordinatlar fiziksel piksel olsun (olcekli ekranlarda bolge kaymasin)."""
    if WINDOWS:
        try:
            _user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # PER_MONITOR_AWARE_V2
        except (AttributeError, OSError):
            pass


def virtual_screen():
    """Tum ekranlari kapsayan dikdortgen [x, y, genislik, yukseklik] (fiziksel piksel)."""
    if WINDOWS:
        dpi_aware()
        metric = _user32.GetSystemMetrics
        return [metric(76), metric(77), metric(78), metric(79)]
    from PIL import ImageGrab
    image = ImageGrab.grab()
    return [0, 0, image.width, image.height]


def primary_size():
    """Birincil ekranin (genislik, yukseklik), fiziksel piksel; sol ustu (0, 0)."""
    if WINDOWS:
        dpi_aware()
        return _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)
    return tuple(virtual_screen()[2:])


def grab(rect):
    """Ekranin [x, y, w, h] bolgesi -> PIL RGB goruntu."""
    x, y, width, height = (int(value) for value in rect)
    from PIL import Image
    if not WINDOWS:
        from PIL import ImageGrab
        return ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True).convert('RGB')
    dpi_aware()
    screen = _user32.GetDC(None)
    memory = _gdi32.CreateCompatibleDC(screen)
    bitmap = _gdi32.CreateCompatibleBitmap(screen, width, height)
    old = _gdi32.SelectObject(memory, bitmap)
    try:
        # CAPTUREBLT yok: Aktar'in katman pencereleri (layered) yakalamaya girmez.
        if not _gdi32.BitBlt(memory, 0, 0, width, height, screen, x, y, SRCCOPY):
            raise OSError('Ekran yakalanamadı.')
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        _gdi32.SelectObject(memory, old)
        if not _gdi32.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header), 0):
            raise OSError('Ekran görüntüsü okunamadı.')
        old = None
    finally:
        if old is not None:
            _gdi32.SelectObject(memory, old)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(memory)
        _user32.ReleaseDC(None, screen)
    return Image.frombuffer('RGB', (width, height), buffer.raw, 'raw', 'BGRX', 0, 1)


def fingerprint(image):
    """Degisim denetimi icin kucuk gri goruntu."""
    from PIL import Image
    width = min(THUMB_WIDTH, image.width)
    height = max(1, round(image.height * width / max(1, image.width)))
    return image.convert('L').resize((width, height), Image.BILINEAR)


def changed(before, after):
    """Iki parmak izi arasinda gozle gorulur fark var mi (yeni harf, kutunun acilip kapanmasi)."""
    if before is None or after is None or before.size != after.size:
        return True
    from PIL import ImageChops
    difference = ImageChops.difference(before, after)
    return difference.point(lambda value: 255 if value > CHANGE_LEVEL else 0).getbbox() is not None


def png_bytes(image, long_side=None):
    from PIL import Image
    if long_side and max(image.size) > long_side:
        factor = long_side / max(image.size)
        image = image.resize((max(1, int(image.width * factor)), max(1, int(image.height * factor))), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


def _prepared(image):
    """Kucuk yazilar OCR icin buyutulur."""
    from PIL import Image
    if image.height < MIN_TEXT_HEIGHT:
        factor = min(3.0, MIN_TEXT_HEIGHT / max(1, image.height))
        image = image.resize((int(image.width * factor), int(image.height * factor)), Image.LANCZOS)
    return image


# ------------------------------------------------------------------ Windows OCR
_WINDOWS_TAGS = {'zh': ('zh-Hans', 'zh-Hant', 'zh'), 'en': ('en-US', 'en-GB', 'en')}
_CJK_GAP = re.compile(r'(?<=[　-鿿豈-﫿＀-￯]) (?=[　-鿿豈-﫿＀-￯])')


def windows_languages():
    """Windows OCR'in kurulu dilleri (dil etiketleri); winrt paketi yoksa bos liste."""
    if not WINDOWS:
        return []
    try:
        from winrt.windows.media.ocr import OcrEngine
        return [item.language_tag for item in OcrEngine.available_recognizer_languages]
    except Exception:  # paket yok ya da Windows surumu desteklemiyor
        return []


def windows_tag(language, installed=None):
    """Oyunun dili icin kurulu Windows OCR dil etiketi ya da None."""
    installed = windows_languages() if installed is None else installed
    lowered = {tag.lower(): tag for tag in installed}
    for wanted in _WINDOWS_TAGS.get(language, ()) + (language,):
        if wanted.lower() in lowered:
            return lowered[wanted.lower()]
    return next((tag for tag in installed if tag.lower().split('-')[0] == language), None)


class WindowsOcr:
    label = 'Windows OCR'

    def __init__(self, tag):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        self.engine = OcrEngine.try_create_from_language(Language(tag))
        if self.engine is None:
            raise ValueError(f'Windows OCR {tag} dilini açamadı.')
        self.cjk = tag.lower().split('-')[0] in ('ja', 'zh', 'ko')
        self._loop = None
        self._lock = threading.Lock()

    def __call__(self, image):
        lines = [line.text for line in self._recognize(_prepared(image.convert('RGB'))).lines]
        return [_CJK_GAP.sub('', line) for line in lines] if self.cjk else lines

    def boxes(self, image):
        """Ekran taramasi: [[(kelime, x, y, w, h), ...] satir basina], koordinatlar verilen goruntude.
        Gri tonlamayla okunur: hareketli renkli oyun sahnesinde Windows OCR renkli goruntude hic satir
        bulamayabiliyor (savas ekrani denemesi), gri tonlamada buluyor."""
        prepared = _prepared(image.convert('L'))
        factor = prepared.height / max(1, image.height)
        result = []
        for line in self._recognize(prepared).lines:
            words = []
            for word in line.words:
                box = word.bounding_rect
                words.append((word.text, box.x / factor, box.y / factor, box.width / factor, box.height / factor))
            if words:
                result.append(words)
        return result

    def _recognize(self, image):
        import asyncio
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import Buffer
        data = image.convert('RGBA').tobytes('raw', 'BGRA')
        buffer = Buffer(len(data))
        buffer.length = len(data)
        memoryview(buffer).cast('B')[:len(data)] = data
        bitmap = SoftwareBitmap.create_copy_from_buffer(buffer, BitmapPixelFormat.BGRA8, image.width, image.height,
                                                        BitmapAlphaMode.PREMULTIPLIED)

        async def recognize():
            return await self.engine.recognize_async(bitmap)
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
            return self._loop.run_until_complete(recognize())

    def close(self):
        if self._loop is not None:
            self._loop.close()
            self._loop = None


class TesseractOcr:
    label = 'Tesseract'

    def __init__(self, cfg, language, log=print):
        import documents
        import languages
        lang = languages.tesseract(language)
        lang = lang if lang == 'eng' else lang + '+eng'
        self._read = documents.tesseract_reader(cfg, log, lang=lang, psm='6')
        # ekran taramasi: daginik yazi kipi (11) ve kelime konumlari (tsv)
        self._read_boxes = documents.tesseract_reader(cfg, log, lang=lang, psm='11', configs=('tsv',))

    @staticmethod
    def _gray(image):
        from PIL import ImageOps, ImageStat
        gray = _prepared(image.convert('L'))
        if ImageStat.Stat(gray).mean[0] < 110:     # oyunlarda genelde koyu zemine acik yazi
            gray = ImageOps.invert(gray)
        return gray

    def __call__(self, image):
        text = self._read(png_bytes(self._gray(image)))
        return [' '.join(line.replace('|', 'I').split()) for line in text.splitlines() if line.strip()]

    def boxes(self, image):
        gray = self._gray(image)
        return tsv_lines(self._read_boxes(png_bytes(gray)), gray.height / max(1, image.height))

    def close(self):
        pass


def tsv_lines(text, factor=1.0):
    """Tesseract tsv ciktisi -> [[(kelime, x, y, w, h), ...] satir basina] (guveni dusuk kelimeler atilir)."""
    lines = {}
    for row in str(text or '').splitlines()[1:]:
        cells = row.split('\t')
        if len(cells) < 12 or cells[0] != '5' or not cells[11].strip():
            continue
        try:
            if float(cells[10]) < 30:
                continue
            left, top, width, height = (int(value) / factor for value in cells[6:10])
        except ValueError:
            continue
        lines.setdefault(tuple(cells[1:5]), []).append((cells[11].strip(), left, top, width, height))
    return list(lines.values())


def reader(engine, language, cfg, log=print):
    """(PIL goruntu) -> [satir]. engine: 'auto' | 'windows' | 'tesseract'."""
    if engine in ('auto', 'windows'):
        tag = windows_tag(language)
        if tag:
            return WindowsOcr(tag)
        if engine == 'windows':
            raise ValueError('Windows OCR bu dili okuyamıyor: Windows Ayarlar > Zaman ve dil > Dil bölümünden '
                             'oyunun dilini (OCR / optik karakter tanıma özelliğiyle) ekleyin ya da Tesseract seçin.')
    return TesseractOcr(cfg, language, log)
