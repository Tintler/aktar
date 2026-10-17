"""Font yetenek tespiti ve Turkce guvenli font yedegi.

Bir ASS/SSA kaynagindaki font, Turkce'ye ozgu harfleri (g, i, s ve buyuk
harfleri) cizebiliyorsa dokunulmaz. Cizemiyorsa (font kurulu degil veya
glifler yok) Turkce ciktida o fontun yerine Calibri kullanilir (Calibri bu
harfleri destekler).

Tespit Windows GDI (GetGlyphIndicesW) uzerinden yapilir; font kurulu
degilse GDI zaten yedek fonta dusemez ve glif "yok" (0xFFFF) doner, bu da
dogru sekilde "Türkçe desteklemiyor" anlamina gelir. Basarisizlik durumunda
yanlis font degisikligi yapmamak icin font "destekliyor" varsayilir.

Linux'ta (ve fontconfig olan diger sistemlerde) ayni tespit `fc-list` ile
yapilir: ailenin kurulu yuzlerinin karakter kumesi okunur. Windows'taki gibi
font kurulu degilse "Türkçe desteklemiyor" sayilir. fc-list yoksa veya hata
verirse font "destekliyor" varsayilir ve cikti degistirilmez.
"""
from __future__ import annotations

import os
import shutil
import subprocess

# Turkce alfabeye ozgu harfler. Yalnizca Latin-1'de bulunmayanlar ayirt edici
# olsa da tamami denetlenir; herhangi biri eksikse font Turkce'yi desteklemiyor
# sayilir.
TURKISH_CHARS = 'çÇğĞıİöÖşŞüÜ'
FALLBACK_FONT = 'Calibri'

_support_cache = {}


def _gdi_missing(family):
    """Kurulu bir font ailesinde eksik Turkce glifleri dondurur (Windows GDI).

    Donen: eksik karakter listesi. Font kurulu degilse GDI yine de bir yedek
    aile uretir; Turkce glifleri yoksa liste dolu doner.
    """
    import ctypes
    from ctypes import wintypes

    class LOGFONTW(ctypes.Structure):
        _fields_ = [
            ('lfHeight', ctypes.c_long),
            ('lfWidth', ctypes.c_long),
            ('lfEscapement', ctypes.c_long),
            ('lfOrientation', ctypes.c_long),
            ('lfWeight', ctypes.c_long),
            ('lfItalic', ctypes.c_byte),
            ('lfUnderline', ctypes.c_byte),
            ('lfStrikeOut', ctypes.c_byte),
            ('lfCharSet', ctypes.c_byte),
            ('lfOutPrecision', ctypes.c_byte),
            ('lfClipPrecision', ctypes.c_byte),
            ('lfQuality', ctypes.c_byte),
            ('lfPitchAndFamily', ctypes.c_byte),
            ('lfFaceName', ctypes.c_wchar * 32),
        ]

    handle = ctypes.c_void_p
    gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
    gdi32.CreateFontIndirectW.restype = handle
    gdi32.CreateFontIndirectW.argtypes = [ctypes.POINTER(LOGFONTW)]
    gdi32.CreateCompatibleDC.restype = handle
    gdi32.CreateCompatibleDC.argtypes = [handle]
    gdi32.SelectObject.restype = handle
    gdi32.SelectObject.argtypes = [handle, handle]
    gdi32.DeleteObject.argtypes = [handle]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [handle]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.GetGlyphIndicesW.restype = ctypes.c_uint
    gdi32.GetGlyphIndicesW.argtypes = [handle, ctypes.c_wchar_p, ctypes.c_int,
                                       ctypes.POINTER(ctypes.c_ushort), ctypes.c_uint]

    logfont = LOGFONTW()
    logfont.lfHeight = -20
    logfont.lfCharSet = 1  # DEFAULT_CHARSET
    logfont.lfFaceName = family
    font = gdi32.CreateFontIndirectW(ctypes.byref(logfont))
    dc = gdi32.CreateCompatibleDC(None)
    previous = gdi32.SelectObject(dc, font)
    try:
        buffer = ctypes.create_unicode_buffer(TURKISH_CHARS)
        indices = (ctypes.c_ushort * len(TURKISH_CHARS))()
        # GGI_MARK_NONEXISTING_GLYPHS = 1
        gdi32.GetGlyphIndicesW(dc, buffer, len(TURKISH_CHARS), indices, 1)
        # 0xFFFF = glif yok, 0 = .notdef; ikisi de "cizilemez" demektir.
        return [char for position, char in enumerate(TURKISH_CHARS)
                if indices[position] in (0xFFFF, 0)]
    finally:
        gdi32.SelectObject(dc, previous)
        gdi32.DeleteDC(dc)
        gdi32.DeleteObject(font)


def _fontconfig_escape(family):
    """fontconfig desen sozdizimindeki ozel karakterleri kacirir."""
    return ''.join('\\' + char if char in '\\-:,=' else char for char in family)


def _parse_charset(text):
    """fc-list %{charset} ciktisini ('20-7e a0-17f ...') kod noktasi araliklarina cevirir."""
    ranges = []
    for item in text.split():
        start, _, end = item.partition('-')
        try:
            ranges.append((int(start, 16), int(end or start, 16)))
        except ValueError:
            continue
    return ranges


def _fontconfig_missing(family):
    """Kurulu bir font ailesinde eksik Turkce glifleri dondurur (fontconfig / fc-list).

    Ailenin herhangi bir yuzu tum harfleri iceriyorsa liste bos doner. Aile kurulu
    degilse tum harfler eksik sayilir (Windows GDI davranisiyla ayni). fc-list
    yoksa veya hata verirse istisna firlatir (cagiran "destekliyor" varsayar).
    """
    command = shutil.which('fc-list')
    if not command:
        raise RuntimeError('fc-list bulunamadi')
    result = subprocess.run([command, '--format', '%{charset}\\n',
                             ':family=' + _fontconfig_escape(family)],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=15)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or 'fc-list basarisiz')
    best = list(TURKISH_CHARS)
    for line in result.stdout.splitlines():
        ranges = _parse_charset(line)
        if not ranges:
            continue
        missing = [char for char in TURKISH_CHARS
                   if not any(start <= ord(char) <= end for start, end in ranges)]
        if len(missing) < len(best):
            best = missing
    return best


def supports_turkish(family):
    """Font Turkce karakterleri cizebiliyor mu? Bilinemiyorsa True doner."""
    name = str(family or '').strip()
    if not name:
        return True
    if name in _support_cache:
        return _support_cache[name]
    try:
        supported = not (_gdi_missing(name) if os.name == 'nt' else _fontconfig_missing(name))
    except Exception:
        supported = True
    _support_cache[name] = supported
    return supported


def turkish_replacements(families, fallback=FALLBACK_FONT):
    """Türkçe desteklemeyen fontlari `fallback`e esler.

    Donen: {kaynak_font: hedef_font}. Bos veya zaten hedef olan adlar atlanir.
    """
    replacements = {}
    for family in families or []:
        name = str(family or '').strip()
        if name and name != fallback and not supports_turkish(name):
            replacements[name] = fallback
    return replacements