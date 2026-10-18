"""Ceviri dil cifti (F151): kaynak ve hedef dil secimi.

Altyazi ve kitap istemleri Ingilizce -> Turkce yazilmistir. Baska bir cift secilince
adapt() istemdeki dil adlarini degistirir ve Turkceye ozgu yonergeleri (sen/siz, kesme
isaretiyle ek, "bir" fazlaligi) hedef Turkce degilse cikarir. Varsayilan cift (en -> tr)
icin istem bayt bayt aynidir; boylece eski kontrol noktalari ve imzalar gecerli kalir.

Kaynak dil 'auto' olabilir: model kaynak dili kendisi tanir, istemde "source-language" gecer.
"""
import re

AUTO = 'auto'
DEFAULT_SOURCE = 'en'
DEFAULT_TARGET = 'tr'

# kod: (istemlerde gecen Ingilizce ad, arayuzde Turkce ad, ISO 639-2/B (mkv/ffmpeg), Tesseract dili)
LANGUAGES = {
    'tr': ('Turkish', 'Türkçe', 'tur', 'tur'),
    'en': ('English', 'İngilizce', 'eng', 'eng'),
    'de': ('German', 'Almanca', 'ger', 'deu'),
    'fr': ('French', 'Fransızca', 'fre', 'fra'),
    'es': ('Spanish', 'İspanyolca', 'spa', 'spa'),
    'it': ('Italian', 'İtalyanca', 'ita', 'ita'),
    'pt': ('Portuguese', 'Portekizce', 'por', 'por'),
    'nl': ('Dutch', 'Felemenkçe', 'dut', 'nld'),
    'pl': ('Polish', 'Lehçe', 'pol', 'pol'),
    'ru': ('Russian', 'Rusça', 'rus', 'rus'),
    'uk': ('Ukrainian', 'Ukraynaca', 'ukr', 'ukr'),
    'el': ('Greek', 'Yunanca', 'gre', 'ell'),
    'ar': ('Arabic', 'Arapça', 'ara', 'ara'),
    'fa': ('Persian', 'Farsça', 'per', 'fas'),
    'hi': ('Hindi', 'Hintçe', 'hin', 'hin'),
    'ja': ('Japanese', 'Japonca', 'jpn', 'jpn'),
    'ko': ('Korean', 'Korece', 'kor', 'kor'),
    'zh': ('Chinese', 'Çince', 'chi', 'chi_sim'),
}

# ASS/SSA fontunun hedef dili cizip cizemedigini anlamak icin ornek harfler ve yedek font.
# Listede olmayan dillerde (ingilizce gibi) font denetimi yapilmaz.
FONT_SAMPLES = {
    'tr': ('çÇğĞıİöÖşŞüÜ', 'Calibri'),
    'de': ('äöüßÄÖÜ', 'Calibri'),
    'fr': ('éèêàçœÉÈÀÇ', 'Calibri'),
    'es': ('ñÑáéíóú¿¡', 'Calibri'),
    'pt': ('ãõçáéíóúÃÕÇ', 'Calibri'),
    'pl': ('ąćęłńóśźżĄĆĘŁŃŚŹŻ', 'Calibri'),
    'ru': ('абвгдежзийклмнопрстуфхцчшщъыьэюяё', 'Calibri'),
    'uk': ('абвгґдеєжзиіїйклмнопрстуфхцчшщьюя', 'Calibri'),
    'el': ('αβγδεζηθικλμνξοπρστυφχψω', 'Calibri'),
    'ar': ('ابتثجحخدذرزسشصضطظعغفقكلمنهوي', 'Arial'),
    'fa': ('ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی', 'Arial'),
    'hi': ('अआइईउऊएऐओऔकखगघ', 'Nirmala UI'),
    'ja': ('あいうえおアイウエオ日本語', 'Yu Gothic'),
    'ko': ('가나다라마바사한국어', 'Malgun Gothic'),
    'zh': ('的一是不了人我在有他这中', 'Microsoft YaHei'),
}

# Ceviri EPUB'unun icindekiler basligi (hedef dilde); listede yoksa 'Contents'.
TOC_TITLES = {
    'tr': 'İçindekiler', 'en': 'Contents', 'de': 'Inhalt', 'fr': 'Table des matières', 'es': 'Índice',
    'it': 'Indice', 'pt': 'Índice', 'nl': 'Inhoud', 'pl': 'Spis treści', 'ru': 'Содержание',
    'uk': 'Зміст', 'el': 'Περιεχόμενα', 'ar': 'المحتويات', 'fa': 'فهرست', 'hi': 'विषय सूची',
    'ja': '目次', 'ko': '목차', 'zh': '目录',
}

# Kelimeleri bosluksuz yazilan yazi sistemleri: terim aramasi kelime siniri yerine alt dizeyle yapilir.
_NO_SPACE_SCRIPT = re.compile(r'[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯฀-๿]')


def name(code):
    """Istemlerde gecen Ingilizce dil adi ('auto' icin 'source-language')."""
    if code == AUTO:
        return 'source-language'
    return LANGUAGES[code][0]


def label(code):
    """Arayuzde gosterilen Turkce ad."""
    if code == AUTO:
        return 'Otomatik'
    return LANGUAGES.get(code, (code, code))[1]


def iso639_2(code):
    return LANGUAGES.get(code, ('', '', 'und'))[2]


def tesseract(code):
    return LANGUAGES.get(code, ('', '', '', 'eng'))[3]


def choices():
    """Arayuzdeki dil secicileri icin [{code, label}] (kaynak listesine 'auto' ayrica eklenir)."""
    return [{'code': code, 'label': value[1]} for code, value in LANGUAGES.items()]


def pair(cfg=None):
    """(kaynak, hedef) dil kodlari; ayar yoksa ('en', 'tr')."""
    cfg = cfg or {}
    source = str(cfg.get('source_language') or DEFAULT_SOURCE).strip().lower()
    target = str(cfg.get('target_language') or DEFAULT_TARGET).strip().lower()
    return source, target


def validate(cfg):
    source, target = pair(cfg)
    if source != AUTO and source not in LANGUAGES:
        raise ValueError('source_language desteklenmiyor: ' + source)
    if target not in LANGUAGES:
        raise ValueError('target_language desteklenmiyor: ' + target)
    if source == target:
        raise ValueError('Kaynak ve hedef dil aynı olamaz.')


def is_default(cfg=None):
    return pair(cfg) == (DEFAULT_SOURCE, DEFAULT_TARGET)


def target(cfg=None):
    return pair(cfg)[1]


def output_tag(cfg=None):
    """Ceviri dosyasi eki: '_TR', '_DE' ..."""
    return '_' + target(cfg).upper()


# Hedef Turkce degilse istemden cikarilan Turkceye ozgu yonergeler.
_TURKISH_ONLY = (
    (' Attach Turkish suffixes to foreign proper nouns with an apostrophe where appropriate.', ''),
    (' Avoid mechanical indefinite articles.', ''),
    ('(sen/siz)', '(formal/informal)'),
    ('sen/siz', 'formal/informal address'),
)
# Kaynak dil 'auto' iken Ingilizceye ozgu ifadelerin dogal karsiliklari.
_AUTO_SOURCE = (
    ('literary English into', 'literary text into'),
    ('rather than English syntax', 'rather than source syntax'),
    ('exact English expression', 'exact source expression'),
    ('aligned English source', 'aligned source'),
    ('"English term"', '"source term"'),
    ('supplied English subtitle text', 'supplied subtitle text'),
)
# Kullaniciya gosterilen gerekce ve ozetler arayuz dili (Turkce) olarak kalir.
_KEEP_TURKISH = ('short Turkish reason', 'short Turkish summary')


def adapt(text, cfg=None):
    """Ingilizce -> Turkce yazilmis istemi secili dil ciftine uyarlar."""
    source, target_code = pair(cfg)
    if (source, target_code) == (DEFAULT_SOURCE, DEFAULT_TARGET) or not text:
        return text
    value = str(text)
    if target_code != 'tr':
        for old, new in _TURKISH_ONLY:
            value = value.replace(old, new)
    if source == AUTO:
        for old, new in _AUTO_SOURCE:
            value = value.replace(old, new)
    if source != DEFAULT_SOURCE:
        value = re.sub(r'\bEnglish\b', name(source), value)
    if target_code != DEFAULT_TARGET:
        held = {}
        for index, phrase in enumerate(_KEEP_TURKISH):
            marker = f'\x00{index}\x00'
            held[marker] = phrase
            value = value.replace(phrase, marker)
        value = re.sub(r'\bTurkish\b', name(target_code), value)
        for marker, phrase in held.items():
            value = value.replace(marker, phrase)
    return value


def book_pair(book):
    """Kitap projesinin dil cifti (epub-import.json; eski projeler en -> tr)."""
    import json
    from pathlib import Path
    marker = Path(book) / 'epub-import.json'
    try:
        data = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    return pair(data)


def no_space(text):
    """Metin kelimeleri bosluksuz yazilan bir yazi sistemi iceriyor mu (Japonca, Cince, Korece, Tayca)?"""
    return bool(_NO_SPACE_SCRIPT.search(str(text or '')))


def loose_search(target_text, text):
    """Turkce disi hedef dillerde sozluk karsiligi ceviride geciyor mu?

    Cekim eklerine (Almanca -en, Rusca hal ekleri ...) izin vermek icin son kelimenin
    govdesiyle baslayan ve en fazla 4 harf uzun bir kelime yeterlidir. Bosluksuz yazilan
    dillerde alt dize aranir.
    """
    wanted = str(target_text or '').casefold().strip()
    if not wanted:
        return False
    haystack = str(text or '').casefold()
    if no_space(wanted):
        return wanted in haystack
    target_words = re.findall(r'[^\W\d_]+', wanted)
    if not target_words:
        return wanted in haystack
    words = re.findall(r'[^\W\d_]+', haystack)
    head, last = target_words[:-1], target_words[-1]
    stem = last[:len(last) - 2] if len(last) > 5 else last
    for index in range(len(head), len(words)):
        if words[index - len(head):index] != head:
            continue
        word = words[index]
        if word.startswith(stem) and len(word) <= len(last) + 4:
            return True
    return False
