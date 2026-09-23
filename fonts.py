"""Font yetenek tespiti ve Turkce guvenli font yedegi.

Bir ASS/SSA kaynagindaki font, Turkce'ye ozgu harfleri (g, i, s ve buyuk
harfleri) cizebiliyorsa dokunulmaz. Cizemiyorsa (font kurulu degil veya
glifler yok) Turkce ciktida o fontun yerine Calibri kullanilir (Calibri bu
harfleri destekler).

Tespit Windows GDI (GetGlyphIndicesW) uzerinden yapilir; font kurulu
degilse GDI zaten yedek fonta dusemez ve glif "yok" (0xFFFF) doner, bu da
dogru sekilde "Türkçe desteklemiyor" anlamina gelir. Basarisizlik durumunda
yanlis font degisikligi yapmamak icin font "destekliyor" varsayilir.

Windows disinda tespit yapilamaz; ayni sekilde font "destekliyor" varsayilir
ve cikti degistirilmez. Boylece cekirdek platformdan bagimsiz kalir.
"""
from __future__ import annotations

import os

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


def supports_turkish(family):
    """Font Turkce karakterleri cizebiliyor mu? Bilinemiyorsa True doner."""
    name = str(family or '').strip()
    if not name:
        return True
    if name in _support_cache:
        return _support_cache[name]
    if os.name != 'nt':
        _support_cache[name] = True
        return True
    try:
        supported = not _gdi_missing(name)
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