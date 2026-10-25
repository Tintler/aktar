"""Oyun ekran cevirisi (F194) cekirdegi: oyun kayitlari, terim listesi, ceviri onbellegi, yazi takibi
(daktilo gibi yavas yavas gelen diyalog) ve model istemleri. Platformdan bagimsizdir; ekran yakalama ve
OCR game_screen.py'de, katman pencereleri ve kisayollar game_overlay.py'de, akis bridge_game.py'de.

Kayitlar APP_DIR/oyun-ceviri altinda:
  ayarlar.json            genel ayarlar (model, gorunum, kisayollar, secili oyun)
  oyunlar/<kimlik>.json   oyun: ad, kaynak dil, okunacak bolgeler, isim/terim listesi
  onbellek/<kimlik>.json  daha once cevrilen cumleler (sikistirilmis metin -> ceviri)

Oyunun dosyalarina, bellegine ya da kurulumuna dokunulmaz: yalnizca ekranda gorunen okunur.
"""
from __future__ import annotations

import difflib
import json
import re
import threading
import time
import unicodedata
from pathlib import Path

import languages
from app_core import APP_DIR, read, save_json
from book_core import is_acronym, is_proper, source_term_regex

FOLDER = 'oyun-ceviri'
PLACEMENTS = ('below', 'above', 'cover', 'custom', 'blocks')   # blocks: her yazinin kendi ustune
MODES = ('ocr', 'vision')
ROLES = ('text', 'speaker')
SPEAKER_MODES = ('auto', 'first_line', 'none')
SCAN_MODES = ('prose', 'all')    # tarama: yalnizca cumleler (diyalog, hikaye, aciklama) ya da menuler dahil
OCR_ENGINES = ('auto', 'windows', 'tesseract')
HOTKEY_ACTIONS = ('toggle', 'overlay', 'now')

DEFAULT_SETTINGS = {
    'game': '',               # secili oyunun kimligi
    'model': '',              # bos: Ayarlar'daki analiz modeli
    'vision_model': '',       # bos: Ayarlar'daki gorsel model (o da bossa analiz modeli)
    'ocr_engine': 'auto',     # auto: Windows OCR (dil paketi varsa), yoksa Tesseract
    'interval_ms': 250,       # bolgeler bu aralikla yakalanir; yalnizca degisince okunur
    'settle_ms': 350,         # yazi bu sure degismeden kalinca cevrilir (daktilo efekti biter)
    'font_size': 26,
    'opacity': 0.85,          # ceviri kutusunun zemini: 0 saydam, 1 opak
    'text_color': '#ffffff',
    'background': '#101418',
    'show_speaker': True,     # konusanin adi cevirinin ustunde
    'hide_when_gone': True,   # oyundaki yazi kaybolunca ceviri de gizlenir
    'context_lines': 3,       # modele baglam olarak verilen onceki satir sayisi
    # Ctrl+Alt kullanilmaz: Turkce klavyede AltGr (Ctrl+Alt) ile yazilan karakterleri (@, ₺ ...) engellerdi.
    'hotkeys': {'toggle': 'Ctrl+F9', 'overlay': 'Ctrl+F10', 'now': 'Ctrl+F11'},
}
LIMITS = {'interval_ms': (100, 2000), 'settle_ms': (100, 3000), 'font_size': (10, 72),
          'opacity': (0.0, 1.0), 'context_lines': (0, 10)}
_COLOR = re.compile(r'#[0-9a-fA-F]{6}')

# Ekrandan okunan yazinin karsilastirma anahtari: harf/rakam disi her sey ve buyuk/kucuk harf farki atilir.
# Bosluklar da atilir: OCR'in kelime araligi okumalari arasinda degisebilir; Japonca zaten bosluksuz.
_PUNCT = str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"', '—': '-', '–': '-', '…': '...'})
_NON_WORD = re.compile(r'[\W_]+')
COMPLETE_MIN = 12          # yarim yazidan onbellekteki tam cumleyi bulmak icin en az bu kadar harf
FUZZY_CUTOFF = 0.92        # OCR gurultusu: bu benzerlikteki onbellek kaydi ayni cumle sayilir
NAME_CUTOFF = 0.75         # konusan adi listedeki ada bu benzerlikle oturtulur ("LasswelC" -> Lasswell)


def folder(base=None):
    return Path(base or APP_DIR) / FOLDER


def compact(text):
    text = unicodedata.normalize('NFKC', str(text or '')).translate(_PUNCT).casefold()
    return _NON_WORD.sub('', text)


def similar(a, b):
    """Iki okuma ayni yazi mi (OCR'in tek tuk harf hatalari tolere edilir)."""
    a, b = compact(a), compact(b)
    if a == b:
        return True
    # biri digerinin basi: yazi buyuyor (daktilo), ayni yazi degil
    if not a or not b or a.startswith(b) or b.startswith(a):
        return False
    longest = max(len(a), len(b))
    allowed = max(1, longest // 25)
    if abs(len(a) - len(b)) > allowed:
        return False
    same = sum(block.size for block in difflib.SequenceMatcher(None, a, b).get_matching_blocks())
    return longest - same <= allowed


def slugify(name):
    text = unicodedata.normalize('NFKD', str(name or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')[:48] or 'oyun'


# ------------------------------------------------------------------ ayarlar
def _clamp(key, value):
    low, high = LIMITS[key]
    default = DEFAULT_SETTINGS[key]
    try:
        value = type(default)(value)
    except (TypeError, ValueError):
        value = default
    return min(high, max(low, value))


def clean_settings(values, current=None):
    """Arayuzden gelen ayarlari dogrular; bilinmeyen anahtarlar atilir, sayilar sinira cekilir."""
    result = json.loads(json.dumps(DEFAULT_SETTINGS))
    for source in (current or {}), (values or {}):
        for key, value in dict(source).items():
            if key not in DEFAULT_SETTINGS:
                continue
            if key in LIMITS:
                result[key] = _clamp(key, value)
            elif key in ('text_color', 'background'):
                result[key] = value if isinstance(value, str) and _COLOR.fullmatch(value) else result[key]
            elif key == 'ocr_engine':
                result[key] = value if value in OCR_ENGINES else result[key]
            elif key in ('show_speaker', 'hide_when_gone'):
                result[key] = bool(value)
            elif key == 'hotkeys':
                keys = dict(result['hotkeys'])
                for action, combo in dict(value or {}).items():
                    if action in HOTKEY_ACTIONS:
                        keys[action] = str(combo or '').strip()
                result[key] = keys
            else:
                result[key] = str(value or '').strip()
    return result


def load_settings(base=None):
    try:
        value = json.loads(read(folder(base) / 'ayarlar.json'))
    except (OSError, ValueError):
        value = {}
    return clean_settings(value if isinstance(value, dict) else {})


def save_settings(values, base=None):
    value = clean_settings(values, load_settings(base))
    save_json(folder(base) / 'ayarlar.json', value)
    return value


# ------------------------------------------------------------------ oyunlar
def _rect(value):
    try:
        x, y, width, height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    return [x, y, width, height] if width >= 4 and height >= 4 else None


def clean_region(value, index=0):
    value = dict(value or {})
    rect = _rect(value.get('rect'))
    if rect is None:
        raise ValueError('Bölgenin ekran konumu eksik.')
    pick = lambda key, options: value.get(key) if value.get(key) in options else options[0]  # noqa: E731
    region = {
        'id': re.sub(r'[^a-z0-9]', '', str(value.get('id') or '').lower())[:16] or f'r{int(time.time() * 1000) % 10**9}{index}',
        'name': str(value.get('name') or '').strip()[:60] or f'Bölge {index + 1}',
        'rect': rect,
        'role': pick('role', ROLES),
        'enabled': bool(value.get('enabled', True)),
        'mode': pick('mode', MODES),
        # Gorsel model bolgeleri varsayilan olarak yalnizca kisayolla okunur (her degisimde istek gitmesin).
        'auto': bool(value.get('auto', value.get('mode') != 'vision')),
        'speaker': pick('speaker', SPEAKER_MODES),
        'placement': pick('placement', PLACEMENTS),
        'scan': pick('scan', SCAN_MODES),
        'target': _rect(value.get('target')),
        # sayfadaki kucuk onizleme (secim anindaki goruntu)
        'preview': value['preview'] if isinstance(value.get('preview'), str)
        and value['preview'].startswith('data:image/') and len(value['preview']) < 300_000 else '',
    }
    if region['placement'] == 'custom' and region['target'] is None:
        region['placement'] = 'below'
    if region['placement'] == 'blocks':
        region['mode'] = 'ocr'          # tarama kelime konumlarini ister: gorsel model konum vermez
    return region


def clean_terms(values):
    """[{source, target, note}]: bos kaynak atilir; ayni kaynak (harfe duyarli anahtar) bir kez."""
    result, seen = [], set()
    for item in values or []:
        if not isinstance(item, dict):
            continue
        source = ' '.join(str(item.get('source') or '').split())[:80]
        if not source:
            continue
        key = source if is_proper(source) else source.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({'source': source, 'target': ' '.join(str(item.get('target') or '').split())[:80],
                       'note': ' '.join(str(item.get('note') or '').split())[:160]})
    return result


def clean_game(value):
    value = dict(value or {})
    language = str(value.get('language') or 'en').strip().lower()
    if language not in languages.LANGUAGES or language == 'tr':
        language = 'en'
    regions = [clean_region(item, index) for index, item in enumerate(value.get('regions') or [])]
    seen = set()
    for region in regions:          # kimlikler benzersiz kalsin
        while region['id'] in seen:
            region['id'] += 'x'
        seen.add(region['id'])
    return {'id': slugify(value.get('id') or value.get('name')), 'name': str(value.get('name') or '').strip()[:80] or 'Oyun',
            'language': language, 'regions': regions, 'terms': clean_terms(value.get('terms'))}


def game_path(game_id, base=None):
    return folder(base) / 'oyunlar' / f'{slugify(game_id)}.json'


def list_games(base=None):
    result = []
    for path in sorted((folder(base) / 'oyunlar').glob('*.json')):
        try:
            game = clean_game(dict(json.loads(read(path)), id=path.stem))
        except (OSError, ValueError, TypeError):
            continue
        result.append({'id': game['id'], 'name': game['name']})
    return sorted(result, key=lambda item: item['name'].casefold())


def load_game(game_id, base=None):
    if not game_id:
        return None
    try:
        return clean_game(dict(json.loads(read(game_path(game_id, base))), id=slugify(game_id)))
    except (OSError, ValueError, TypeError):
        return None


def save_game(game, base=None):
    game = clean_game(game)
    save_json(game_path(game['id'], base), game)
    return game


def create_game(name, base=None):
    name = ' '.join(str(name or '').split())
    if not name:
        raise ValueError('Oyunun adını yazın.')
    slug, number = slugify(name), 2
    game_id = slug
    while game_path(game_id, base).exists():
        game_id, number = f'{slug}-{number}', number + 1
    return save_game({'id': game_id, 'name': name, 'language': 'en', 'regions': [], 'terms': []}, base)


def delete_game(game_id, base=None):
    for path in (game_path(game_id, base), cache_path(game_id, base)):
        try:
            path.unlink()
        except OSError:
            pass


# ------------------------------------------------------------------ onbellek
def cache_path(game_id, base=None):
    return folder(base) / 'onbellek' / f'{slugify(game_id)}.json'


class TranslationCache:
    """Daha once cevrilen cumleler: ayni cumle tekrar gelince model beklenmez. Anahtar compact() metindir;
    OCR'in kucuk okuma farklari FUZZY_CUTOFF benzerlikle ayni kayda duser."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        try:
            value = json.loads(read(self.path))
            items = value.get('items') if isinstance(value, dict) else None
        except (OSError, ValueError):
            items = None
        self.items = {key: item for key, item in (items or {}).items()
                      if isinstance(item, dict) and item.get('translation')}

    def __len__(self):
        return len(self.items)

    def get(self, text):
        key = compact(text)
        if not key:
            return None
        with self._lock:
            item = self.items.get(key)
            if item is not None or len(key) < 8:
                return item
            near = [other for other in self.items if abs(len(other) - len(key)) <= max(2, len(key) // 12)]
            match = difflib.get_close_matches(key, near, n=1, cutoff=FUZZY_CUTOFF)
            return self.items[match[0]] if match else None

    def complete(self, partial):
        """Yazi daha ekrana gelirken (daktilo efekti) onbellekteki tam cumle: yalnizca tek bir ceviriye
        isaret ediyorsa. Yoksa None."""
        key = compact(partial)
        if len(key) < COMPLETE_MIN:
            return None
        with self._lock:
            found = [item for other, item in self.items.items() if other.startswith(key) and other != key]
        if not found or len({item['translation'] for item in found}) != 1:
            return None
        return found[0]

    def put(self, source, translation, speaker=''):
        key = compact(source)
        if not key or not str(translation or '').strip():
            return
        with self._lock:
            self.items[key] = {'source': str(source), 'translation': str(translation).strip(),
                               'speaker': str(speaker or ''), 'time': int(time.time())}
            self._save()

    def forget(self, source):
        with self._lock:
            if self.items.pop(compact(source), None) is not None:
                self._save()

    def clear(self):
        with self._lock:
            self.items = {}
            self._save()

    def _save(self):
        try:
            save_json(self.path, {'version': 1, 'items': self.items})
        except OSError:
            pass  # onbellek yazilamazsa ceviri yine gosterilir


# ------------------------------------------------------------------ yazi takibi
class TextTracker:
    """Bir bolgenin yazisini izler ve ceviriye ne zaman gonderilecegine karar verir.

    Diyalog harf harf gelirken (daktilo efekti) goruntu her yakalamada degisir: yazi yerlesmeden
    cevrilmez. Goruntu bir yakalama araligi boyunca hic degismediyse yazi yerlesmis sayilir; arka plan
    oynadigi icin goruntu degisse de ayni yazi `settle` saniye boyunca okunduysa yine yerlesmistir.
    Ayni yazi ikinci kez gonderilmez; yazi kaybolunca 'gone' doner (katman gizlenebilir)."""

    def __init__(self, settle=0.35):
        self.settle = settle
        self.pending = ''
        self.since = 0.0
        self.committed = ''
        self.empty_since = None

    def observe(self, text, now):
        """Goruntu degisti ve yeniden okundu. Donen: gonderilecek metin, 'gone' ya da None."""
        if not compact(text):
            self.pending = ''
            if not self.committed:
                return None
            if self.empty_since is None:
                self.empty_since = now
            if now - self.empty_since >= self.settle:
                self.committed, self.empty_since = '', None
                return 'gone'
            return None
        self.empty_since = None
        if not similar(text, self.pending):
            self.pending, self.since = text, now
            return None
        if len(compact(text)) > len(compact(self.pending)):
            self.pending = text     # ayni yazinin daha iyi okumasi
        return self._ready(now, self.settle)

    def unchanged(self, now):
        """Goruntu son yakalamadan beri ayni: bekleyen yazi yerlesmistir."""
        if self.empty_since is not None and self.committed and now - self.empty_since >= self.settle:
            self.committed, self.empty_since = '', None
            return 'gone'
        return self._ready(now, 0.0) if self.pending else None

    def _ready(self, now, wait):
        if now - self.since < wait or similar(self.pending, self.committed):
            return None
        self.committed = self.pending
        return self.pending

    def force(self, text):
        """'Simdi cevir': yazi ne olursa olsun gonderilir."""
        self.pending = self.committed = text
        self.empty_since = None
        return text if compact(text) else None


# ------------------------------------------------------------------ okunan yazi
def _looks_like_name(line):
    line = line.strip()
    if not line or len(line) > 28 or len(line.split()) > 3 or line[-1] in '.!?,;:…"\'”’)-—':
        return False
    first = next((char for char in line if char.isalpha()), '')
    return bool(first) and (first.isupper() or not first.islower())


def snap_name(name, terms):
    """OCR'in bozdugu adi listedeki ada oturtur ("LasswelC" -> "Lasswell"); bulamazsa aynen."""
    name = name.strip().strip(':').strip()
    names = [item['source'] for item in terms or [] if is_proper(item['source'])]
    if not name or not names:
        return name
    lowered = {item.casefold(): item for item in names}
    if name.casefold() in lowered:
        return lowered[name.casefold()]
    match = difflib.get_close_matches(name.casefold(), list(lowered), n=1, cutoff=NAME_CUTOFF)
    return lowered[match[0]] if match else name


def join_lines(lines, language='en'):
    """Bolgedeki satirlar tek metne: diyalog kutusundaki satir kaydirmalari bosluk olur."""
    lines = [' '.join(str(line).split()) for line in lines if str(line).strip()]
    if languages.no_space(''.join(lines)) and language in ('ja', 'zh', 'ko', 'th'):
        return ''.join(line.replace(' ', '') if language != 'ko' else line for line in lines)
    text = ' '.join(lines)
    return re.sub(r'(\w)- (\w)', r'\1\2', text)   # satir sonunda bolunmus kelime


def split_speaker(lines, mode='auto', terms=(), language='en'):
    """(konusan, metin). 'first_line': ilk satir her zaman ad; 'auto': ilk satir ada benziyorsa (kisa,
    noktalamasiz, buyuk harfle). Tek satirlik ad (metin henuz gelmedi) metin sayilmaz."""
    lines = [str(line).strip() for line in lines if str(line).strip()]
    if not lines or mode == 'none':
        return '', join_lines(lines, language)
    first = lines[0]
    # Ikinci satir kucuk harfle basliyorsa ilk satir kaymis cumlenin basidir ("Come with" / "me now.").
    continued = len(lines) > 1 and lines[1][:1].islower()
    if mode == 'first_line' or (_looks_like_name(first) and not continued
                                and (len(lines) > 1 or len(first.split()) <= 2)):
        return snap_name(first, terms), join_lines(lines[1:], language)
    return '', join_lines(lines, language)


# ------------------------------------------------------------------ ekran taramasi (yazilarin ustune)
SEGMENT_GAP = 1.5     # satirdaki kelimeler arasi bosluk satir yuksekliginin bu katindan buyukse ayri yazi
BLOCK_GAP = 0.8       # alt alta iki satir arasi bosluk satir yuksekliginin bu katina kadarsa ayni paragraf
WRAPPED = 8           # genisligi yuksekliginin bu katindan fazla satir kaymis (devami alttaki satirda) sayilir
_WORD = re.compile(r'[^\W\d_]{3,}')
_CJK_LANGS = ('ja', 'zh', 'ko', 'th')


def _median(values):
    values = sorted(values)
    return values[len(values) // 2] if values else 0


def _union(boxes):
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return [round(left), round(top), round(right - left), round(bottom - top)]


def segments(lines):
    """OCR satirlari [[(kelime, x, y, w, h), ...]] -> yazi parcalari {'text', 'box', 'height'}.
    OCR yan yana duran ayri yazilari (ör. 'Lv.1' ve 'Holy Ray') tek satir okuyabilir: genis bosluk boler."""
    result = []
    for words in lines:
        words = sorted((word for word in words if str(word[0]).strip()), key=lambda word: word[1])
        if not words:
            continue
        height = _median([word[4] for word in words]) or 1
        group = [words[0]]
        for word in words[1:] + [None]:
            if word is not None and word[1] - (group[-1][1] + group[-1][3]) <= SEGMENT_GAP * height:
                group.append(word)
                continue
            # Dikeyde ortanca: tek bir kelimenin tasan kutusu (simge, alt cizgi) satiri buyutmesin.
            box = _union([item[1:] for item in group])
            top, tall = _median([item[2] for item in group]), _median([item[4] for item in group]) or height
            result.append({'text': ' '.join(str(item[0]) for item in group),
                           'box': [box[0], round(top), box[2], round(tall)], 'height': tall})
            group = [word]
    return result


def _joins(block, segment):
    """Parca blogun son satirinin devami mi (ayni paragrafin alt satiri)."""
    last = block['parts'][-1]
    height = max(last['height'], segment['height'])
    gap = segment['box'][1] - (last['box'][1] + last['box'][3])
    if not -0.3 * height <= gap <= BLOCK_GAP * height:
        return False
    if not 0.7 <= segment['height'] / max(1, last['height']) <= 1.4:
        return False
    if last['box'][2] < WRAPPED * last['height']:
        return False        # kisa satir (menu ogesi, baslik, ad) kendi basina bir yazidir
    left = abs(segment['box'][0] - last['box'][0])
    center = abs(segment['box'][0] + segment['box'][2] / 2 - (last['box'][0] + last['box'][2] / 2))
    return min(left, center) <= 1.5 * height


def worth_translating(text, language='en'):
    """Yalnizca rakam, simge ya da kisaltmadan (HP, Lv.1, 98 > 101) olusan yazilar cevrilmez."""
    if language in _CJK_LANGS:
        return sum(char.isalpha() for char in str(text)) >= 2
    return bool(_WORD.search(str(text)))


_SENTENCE_END = re.compile(r'[.!?…。！？」』"”)]\s*$')


def is_prose(text, language='en'):
    """Cumle mi (diyalog, hikaye, gorev ya da aciklama metni)? Beceri, silah, menu adlari ve nitelik
    etiketleri (Holy Ray, Phys. Atk., Radiant Restoration, Hide Tips) cumle sayilmaz: oyunda aynen kalir."""
    text = ' '.join(str(text).split())
    if language in _CJK_LANGS:
        letters = sum(char.isalpha() for char in text)
        return letters >= 8 or (letters >= 4 and bool(_SENTENCE_END.search(text)))
    words = [word for word in text.split() if sum(char.isalpha() for char in word) >= 2]
    return len(words) >= 5 or (len(words) >= 3 and bool(_SENTENCE_END.search(text)))


def text_blocks(lines, language='en', prose_only=False):
    """Tum ekran/bolge taramasi: OCR satirlarindan ayri ayri cevrilecek yazilar.
    Donen: [{'text', 'lines', 'box': [x, y, w, h], 'height', 'speaker'}] okuma sirasiyla. Uzun bir yazinin
    hemen ustundeki kisa, ada benzeyen tek satir (ör. 'Innkeeper') konusan olarak baglama verilir."""
    blocks = []
    for segment in sorted(segments(lines), key=lambda item: (item['box'][1], item['box'][0])):
        target = next((block for block in blocks if _joins(block, segment)), None)
        if target is None:
            blocks.append({'parts': [segment]})
        else:
            target['parts'].append(segment)
    result = []
    for block in blocks:
        parts = block['parts']
        texts = [part['text'] for part in parts]
        result.append({'text': join_lines(texts, language), 'lines': texts, 'box': _union([part['box'] for part in parts]),
                       'height': _median([part['height'] for part in parts]), 'speaker': ''})
    for item in result:
        if len(item['text'].split()) < 4:
            continue
        x, y = item['box'][0], item['box'][1]
        for other in result:
            ox, oy, ow, oh = other['box']
            if (other is not item and len(other['lines']) == 1 and _looks_like_name(other['text'])
                    and 0 <= y - (oy + oh) <= 1.2 * item['height'] and abs(ox - x) <= 1.5 * item['height']):
                item['speaker'] = other['text']
                break
    return [item for item in result if worth_translating(item['text'], language)
            and (not prose_only or is_prose(item['text'], language))]


# ------------------------------------------------------------------ istem
_SENTENCE_LEAD = ' \t\r\n"\'“‘«(*_-—–['


def _at_sentence_start(text, index):
    before = text[:index].rstrip(_SENTENCE_LEAD)
    return not before or before[-1] in '.!?…:'


def matched_terms(text, terms):
    """Metinde gecen terimler: (aynen kalacaklar, karsiligi olanlar, belirsizler).

    Buyuk harfle yazilan terimler (Rain) yalnizca buyuk harfle gecince eslesir; kucuk harfli 'rain'
    siradan kelime olarak cevrilir (book_core F192/F193 kurali). Tek kelimelik bir ozel ad yalnizca
    cumle basinda geciyorsa belirsizdir: modele baglama gore karar vermesi soylenir."""
    keep, mapped, ambiguous = [], [], []
    for item in terms or []:
        source = item['source']
        matches = list(source_term_regex(source).finditer(text))
        if not matches:
            continue
        if (is_proper(source) and not is_acronym(source) and len(source.split()) == 1
                and all(_at_sentence_start(text, match.start()) for match in matches)):
            ambiguous.append(item)
        elif item.get('target'):
            mapped.append(item)
        else:
            keep.append(item)
    return keep, mapped, ambiguous


SYSTEM_PROMPT = (
    'Sen bir oyun çevirmenisin. Oyunun ekranından okunan {language} metni doğal, akıcı ve oyunun tonuna '
    'uygun Türkçeye çevir. Yalnızca Türkçe çeviriyi yaz: açıklama, not, tırnak, özgün metin ya da '
    '"Çeviri:" gibi bir başlık ekleme. Metin ekrandan okunduğu için küçük harf hataları olabilir; '
    'anlamdan düzelt. Karakter, yer ve eşya adlarını çevirme, olduğu gibi bırak. Konuşanın kim olduğuna ve '
    'önceki satırlara göre hitabı (sen/siz) ve tonu tutarlı seç.')

VISION_PROMPT = (
    'Bu görüntü bir oyunun ekranından alındı. Görüntüdeki oyun yazısını oku ve Türkçeye çevir. Süslü ya da '
    'dekoratif yazıları da oku. Karakter, yer ve eşya adlarını çevirme. Yanıtı yalnızca şu JSON biçiminde '
    'ver: {"speaker": "konuşanın adı (yoksa boş)", "text": "okunan özgün metin", '
    '"translation": "Türkçe çeviri"}. Yazı yoksa üç alanı da boş bırak.')


def _term_lines(text, terms):
    keep, mapped, ambiguous = matched_terms(text, terms)
    lines = []
    if keep:
        lines.append('Özel adlar (çevirme, aynen yaz): ' + ', '.join(item['source'] for item in keep))
    if mapped:
        lines.append('Terimler (bu karşılıkları kullan): ' + '; '.join(
            f'{item["source"]} → {item["target"]}' for item in mapped))
    for item in ambiguous:
        lines.append(f'"{item["source"]}" bir özel ad ama burada cümle başında; özel ad olarak mı yoksa sıradan '
                     'kelime olarak mı geçtiğine bağlama göre karar ver (özel adsa çevirme).')
    notes = [item for item in keep + mapped + ambiguous if item.get('note')]
    if notes:
        lines.append('Notlar: ' + '; '.join(f'{item["source"]}: {item["note"]}' for item in notes))
    return lines


def translation_messages(text, speaker='', history=(), terms=(), language='en'):
    """Tek istekte cevrilecek metin: konusan, eslesen terimler ve onceki satirlar baglam olarak."""
    system = SYSTEM_PROMPT.format(language=languages.label(language))
    parts = []
    speaker_terms = [item for item in terms or [] if speaker and item['source'].casefold() == speaker.casefold()]
    if speaker:
        parts.append(f'Konuşan: {speaker}')
    parts.extend(_term_lines(text, [item for item in terms or [] if item not in speaker_terms]))
    if history:
        parts.append('Önceki satırlar (yalnızca bağlam, bunları çevirme):')
        for item in history:
            who = f'{item["speaker"]}: ' if item.get('speaker') else ''
            parts.append(f'- {who}{item["source"]} => {item["translation"]}')
    parts.append('Çevrilecek metin:')
    parts.append(text)
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': '\n'.join(parts)}]


BATCH_RULES = (
    ' Ekrandaki birbirinden ayrı yazılar (menü, başlık, açıklama, diyalog) numaralı olarak verilir. Her birini '
    'ayrı çevir ve her çeviriyi kendi numarasıyla tek satıra yaz: [1] çeviri. Numara atlama, yazıları '
    'birleştirme; menü ve başlık gibi kısa yazıları kısa tut.')
BATCH_MAX = 40          # bir istekte en fazla bu kadar yazi
BATCH_CHARS = 3000      # ... ya da bu kadar harf


def batch_messages(items, history=(), terms=(), language='en'):
    """Tarama kipinde ekrandaki yeni yazilar tek istekte: items [{'text', 'speaker'}]."""
    system = SYSTEM_PROMPT.format(language=languages.label(language)) + BATCH_RULES
    parts = _term_lines('\n'.join(item['text'] for item in items), terms)
    speakers = [f'[{number}] {item["speaker"]}' for number, item in enumerate(items, 1) if item.get('speaker')]
    if speakers:
        parts.append('Konuşanlar (yalnızca bağlam): ' + '; '.join(speakers))
    if history:
        parts.append('Önceki satırlar (yalnızca bağlam, bunları çevirme):')
        for item in history:
            who = f'{item["speaker"]}: ' if item.get('speaker') else ''
            parts.append(f'- {who}{item["source"]} => {item["translation"]}')
    parts.append('Çevrilecek yazılar:')
    parts.extend(f'[{number}] {" ".join(item["text"].split())}' for number, item in enumerate(items, 1))
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': '\n'.join(parts)}]


_ITEM = re.compile(r'^\s*\[(\d+)\]\s*', re.M)


def parse_batch(text, count, final=True):
    """'[1] ...\n[2] ...' -> {numara: ceviri}. final=False (akarken): son oge henuz bitmemis olabilir, atlanir."""
    import qa
    text = qa.strip_thinking(str(text or ''))
    marks = list(_ITEM.finditer(text))
    result = {}
    for index, mark in enumerate(marks):
        if not final and index == len(marks) - 1:
            break
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        number = int(mark.group(1))
        value = clean_translation(text[mark.end():end])
        if 1 <= number <= count and value and number not in result:
            result[number] = value
    if not marks and final and count == 1:      # tek yazida model numarayi yazmayabiliyor
        value = clean_translation(text)
        if value:
            result[1] = value
    return result


def batch_tokens(items):
    return min(4096, 64 + sum(len(item['text']) * 2 + 8 for item in items))


def vision_prompt(terms=(), history=()):
    prompt = VISION_PROMPT
    names = [item['source'] if not item.get('target') else f'{item["source"]} → {item["target"]}'
             for item in terms or []]
    if names:
        prompt += '\nAd ve terim listesi: ' + '; '.join(names[:60])
    if history:
        last = history[-1]
        prompt += f'\nÖnceki satır: {last["source"]} => {last["translation"]}'
    return prompt


_LABEL = re.compile(r'^\s*(?:türkçe\s+)?(?:çeviri|translation)\s*:\s*', re.I)


def clean_translation(text):
    import qa
    text = qa.strip_thinking(str(text or '')).strip()
    text = _LABEL.sub('', text)
    if len(text) >= 2 and text[0] in '"“«' and text[-1] in '"”»' and text.count(text[0]) <= 2:
        text = text[1:-1].strip()
    return '\n'.join(line.rstrip() for line in text.splitlines()).strip()


def parse_vision(text):
    """Gorsel modelin JSON yaniti -> {'speaker', 'text', 'translation'}; JSON yoksa tum yanit ceviri."""
    import qa
    raw = qa.strip_thinking(str(text or '')).strip()
    match = re.search(r'\{.*\}', raw, re.S)
    if match:
        try:
            value = json.loads(match.group(0))
        except ValueError:
            value = None
        if isinstance(value, dict):
            return {key: str(value.get(key) or '').strip() for key in ('speaker', 'text', 'translation')}
    return {'speaker': '', 'text': '', 'translation': clean_translation(raw)}


def max_tokens_for(text):
    """Kisa diyaloglar icin kucuk butce: model uzun yanitla zaman kaybetmesin."""
    return min(1024, 96 + len(str(text)) * 2)
