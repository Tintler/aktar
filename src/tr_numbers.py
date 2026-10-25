"""Turkce sira sayilari ve Romen rakamlari sesli okuma icin yaziya (F198).

OpenRouter'daki orijinal Fish Audio Drama 3 '44. bolum'u 'kirk dort bolum', 'IV. Murad'i harf harf okuyor (yerel
Turkce konusmaci kendisi dogru okuyordu). spoken() yalnizca modele giden metni degistirir:
- '44. bolum' -> 'kirk dorduncu bolum': rakamdan sonra nokta ve kucuk harfle baslayan kelime (buyuk harfle
  baslayan kelime cumle sonu olabilir: 'Yasi 44. Sonra'), '44'uncu' -> 'kirk dorduncu'.
- 'IV. Murad' -> 'Dorduncu Murad', 'XV. yuzyil' -> 'on besinci yuzyil': gecerli Romen rakami + nokta + kelime.
Duz sayilari (44, 1990'da) model zaten Turkce okuyor; onlara dokunulmaz.
"""
from __future__ import annotations

import re

VERSION = 1     # okunus kurali degisince artir: sayili cumlelerin ses onbellegi yenilenir (tts._cache_path)

ONES = ['', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz']
TENS = ['', 'on', 'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan']
SCALES = [(10 ** 9, 'milyar'), (10 ** 6, 'milyon'), (1000, 'bin')]
ORDINAL = {'sıfır': 'sıfırıncı', 'bir': 'birinci', 'iki': 'ikinci', 'üç': 'üçüncü', 'dört': 'dördüncü',
           'beş': 'beşinci', 'altı': 'altıncı', 'yedi': 'yedinci', 'sekiz': 'sekizinci', 'dokuz': 'dokuzuncu',
           'on': 'onuncu', 'yirmi': 'yirminci', 'otuz': 'otuzuncu', 'kırk': 'kırkıncı', 'elli': 'ellinci',
           'altmış': 'altmışıncı', 'yetmiş': 'yetmişinci', 'seksen': 'sekseninci', 'doksan': 'doksanıncı',
           'yüz': 'yüzüncü', 'bin': 'bininci', 'milyon': 'milyonuncu', 'milyar': 'milyarıncı'}
ROMAN = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
INITIALS = {'L', 'C', 'D', 'M'}    # tek harfte ad kisaltmasi ('M. Kemal', 'John D. Rockefeller'), Romen sayilmaz

_LETTER = r'[^\W\d_]'
_ROMAN_FORM = re.compile(r'M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})')
_ARABIC = re.compile(r'(?<![\w.,])(\d{1,12})\.(?=\s+[a-zçğıöşü])')
_SUFFIXED = re.compile(r"(?<![\w.,])(\d{1,12})['’](?:i|ı|u|ü)?nc(?:i|ı|u|ü)\b")
_ROMAN = re.compile(rf'(?<![\w.,])([IVXLCDM]+)\.(?=\s+{_LETTER})')
_SENTENCE_START = re.compile(r'(^|[.!?…:]\s*)["“«\'‘(\-–—\s]*$')


def _below_thousand(number):
    hundreds, rest = divmod(number, 100)
    words = []
    if hundreds:
        words += ([ONES[hundreds]] if hundreds > 1 else []) + ['yüz']
    words += [word for word in (TENS[rest // 10], ONES[rest % 10]) if word]
    return words


def cardinal(number):
    """44 -> 'kırk dört', 1000 -> 'bin', 2000000 -> 'iki milyon'."""
    number = int(number)
    if number == 0:
        return 'sıfır'
    words = []
    for size, name in SCALES:
        count, number = divmod(number, size)
        if count:
            words += ([] if count == 1 and size == 1000 else _below_thousand(count) if count < 1000
                      else cardinal(count).split()) + [name]
    return ' '.join(words + _below_thousand(number))


def ordinal(number):
    """44 -> 'kırk dördüncü'."""
    words = cardinal(number).split()
    words[-1] = ORDINAL[words[-1]]
    return ' '.join(words)


def roman_value(text):
    """'IV' -> 4; gecerli Romen rakami degilse None."""
    if not text or not _ROMAN_FORM.fullmatch(text):
        return None
    if text in INITIALS:
        return None
    total = 0
    for index, char in enumerate(text):
        value = ROMAN[char]
        total += -value if index + 1 < len(text) and ROMAN[text[index + 1]] > value else value
    return total


def _capital(text, start):
    return bool(_SENTENCE_START.search(text[:start]))


def _case(words, upper):
    return words[:1].replace('i', 'İ').upper() + words[1:] if upper else words


def spoken(text):
    """Modele giden metin: sira sayilari ve Romen rakamlari yaziyla (bkz. modul belgesi)."""
    if not text or not re.search(r'\d|[IVXLCDM]\.', text):
        return text

    def arabic(match):
        return _case(ordinal(match.group(1)), _capital(match.string, match.start()))

    def roman(match):
        value = roman_value(match.group(1))
        if value is None:
            return match.group(0)
        following = match.string[match.end():].lstrip()[:1]
        return _case(ordinal(value), following.isupper() or _capital(match.string, match.start()))

    text = _SUFFIXED.sub(arabic, text)
    text = _ARABIC.sub(arabic, text)
    return _ROMAN.sub(roman, text)
