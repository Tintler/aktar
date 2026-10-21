"""Drama 3 duygu etiketleri (F168, deneysel): kitap diyaloglarina [laughs], [sighs] ... atanir.

Turkceye budanmis Drama 3'te yalnizca parcanin EN BASINDAKI su etiketler calisiyor (kullanicinin dinleme seti):
[laughs], [sighs], [fısıldar], [shouting], [angry]. Sonda ya da tirnak icindeki [laughs], <whisper>, [iç çeker],
[crying] calismiyor; [güler] yalnizca bazen.

Etiketleme okuyucunun kendi cumleleri uzerinde yapilir (web/src/lib/sentences.js bolmesi + paragraf sonlari):
anlaticidaki ipucu ('gulerek', 'fisildadi', 'bagirdi' ...) ayni paragraftaki konusma cumlesine (tirnakli ya da
cizgili) atanir; anlatici cumlesi etiket almaz. Istege bagli olarak model sunucusu (llm_provider) baglamdan
cikarir. Okuyucuda gorunen metin degismez: etiket yalnizca sunucuya giden metne eklenir (drama3.tagged).

Sonuc kitap basina APP_DIR/duygu-etiketleri/<kitap>.json'da cumle metnine gore saklanir:
    {"version": 1, "words": {cumle: etiket}, "llm": {cumle: etiket ya da ""}}
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from drama3 import EMOTION_TAGS as TAGS   # [laughs], [sighs], [fısıldar], [shouting], [angry]

MODES = ('off', 'words', 'llm')
STORE_DIR = 'duygu-etiketleri'
VERSION = 1

# Anlatici ipuclari (Turkce kucuk harfle). Yalnizca ucuncu kisi/zarf bicimleri: konusmanin icindeki
# 'Neden bagirdin?' eslesmesin (ikinci kisi eki -n/-niz dislanir). Sira oncelik sirasidir (fisilti ve
# bagirma ayni cumlede ofkeden baskin).
CUES = (
    ('[fısıldar]', r'fısılda(?:dı|yarak|yordu|mış|şarak|ştı)|fısıltıyla|fısıltı (?:halinde|ile)|alçak sesle'),
    ('[shouting]', r'bağır(?:dı|arak|ıyordu|ıp|mış|ınca)|haykır(?:dı|arak|ıyordu|ıp|mış)|çığlık (?:attı|atarak)'
                   r'|avaz avaz|gürledi|gürleyerek'),
    ('[angry]', r'öfkeyle|öfkeli bir|öfkelen(?:di|erek|miş)|sinirle|sinirli bir|sinirlen(?:di|erek|miş)'
                r'|kızgın(?:lıkla)?|kızarak|kızdı(?!\w)|hiddetle|hiddetlen(?:di|erek)|köpürdü|tersledi|çıkıştı'),
    ('[laughs]', r'gül(?:erek|dü|üyordu|üştü|üşerek|üşüyorlardı|mekten|meye başladı)'
                 r'|kahkaha|kıkırda(?:dı|yarak)|katıla katıla'),
    ('[sighs]', r'iç(?:ini)? çek(?:ti|erek|iyordu|ip|miş)|iç geçir(?:di|erek|iyordu)'),
)
_CUES = tuple((tag, re.compile(r'(?<!\w)(?:' + pattern + r')(?!n(?:ız)?\b)', re.U)) for tag, pattern in CUES)
_OPEN_QUOTE = '“«"'
_QUOTED = re.compile(r'[“«"][^”»"]*(?:[”»"]|$)')
_DASH = re.compile(r'^[—–-]\s*')
_UNMARKED = re.compile(r'[?!,…]\s+(?:diye|dedi|der|sordu)(?!\w)')    # isaretsiz konusma: 'Gelir misin? diye sordu'
_CONTINUES = re.compile(r'^(?:diye|dedi|deyip|diyerek|demişti)(?!\w)')  # onceki konusmanin devami: 'Diye guldu.'


def tr_lower(text):
    return str(text).replace('I', 'ı').replace('İ', 'i').lower()


def is_speech(sentence):
    """Konusma cumlesi mi: cizgiyle baslar, tirnak icinde soz var (tek-iki kelimelik 'lutr' gibi alinti degil) ya da
    isaretsiz konusma ('Begenemiyor musun? diye guldu')."""
    sentence = str(sentence).lstrip()
    if _DASH.match(sentence) or _UNMARKED.search(tr_lower(sentence)):
        return True
    return any(len(quoted.split()) >= 3 or re.search(r'[.!?,…]', quoted) for quoted in _QUOTED.findall(sentence))


def narration(sentence):
    """Cumlenin anlatici kismi: tirnak icleri cikarilir (cizgili diyalogda butunu, ipuclari ucuncu kisi oldugu icin)."""
    return _QUOTED.sub(' ', str(sentence))


def cue(sentence):
    """Cumlenin anlatici kismindaki ilk ipucunun etiketi ('' yoksa)."""
    text = tr_lower(narration(sentence))
    for tag, pattern in _CUES:
        if pattern.search(text):
            return tag
    return ''


def paragraphs(count, breaks):
    """Paragraflar: [(bas, son)] (son dahil degil); `breaks` paragraf sonu olan cumle numaralari."""
    ends = sorted({int(b) for b in breaks or () if 0 <= int(b) < count} | ({count - 1} if count else set()))
    result, start = [], 0
    for end in ends:
        if end >= start:
            result.append((start, end + 1))
            start = end + 1
    return result


def tag_sentences(sentences, breaks=()):
    """Kelime listesiyle etiketleme: her cumle icin etiket ('' yok). Ipucu konusma cumlesindeyse ('"Gel!" diye
    bagirdi.') o cumleye; 'Diye guldu.' gibi devam cumlesindeyse onceki konusmaya; anlatici cumlesindeyse ayni
    paragrafta hemen sonraki, yoksa hemen onceki konusmaya; iki nokta ya da virgulle biten paragraf sonundaysa
    ('Sinirle sordu:') sonraki paragrafin ilk cumlesine. Uzaktaki konusma etiket almaz (baska bir ana ait olabilir)."""
    sentences = [str(s) for s in sentences]
    tags = [''] * len(sentences)
    speech = [is_speech(s) for s in sentences]
    paragraph = [0] * len(sentences)
    for number, (start, end) in enumerate(paragraphs(len(sentences), breaks)):
        paragraph[start:end] = [number] * (end - start)
    for i, sentence in enumerate(sentences):
        found = cue(sentence)
        if not found:
            continue
        target, after, before = None, i + 1, i - 1
        if speech[i]:
            target = i
        elif _CONTINUES.match(tr_lower(sentence.lstrip())):
            target = before if before >= 0 and speech[before] else None
        elif after < len(sentences) and speech[after] and (paragraph[after] == paragraph[i]
                                                            or sentence.rstrip()[-1:] in (':', ',')):
            target = after
        elif before >= 0 and speech[before] and paragraph[before] == paragraph[i]:
            target = before
        if target is not None and not tags[target]:
            tags[target] = found
    return tags


# ---------------------------------------------------------------- model sunucusuyla (istege bagli)
LLM_BATCH = 60   # bir istekteki cumle sayisi
LLM_MAX_TAGGED = 3   # bundan cok ve konusmalarin yarisindan fazlasi etiketlenmisse yanit gecersiz
LLM_PROMPT = (
    'Aşağıda bir romandan numaralı cümleler var (boş satır paragraf sonudur). Konuşma cümlelerinden (tırnaklı ya da '
    'çizgiyle başlayan) anlatıcının ya da bağlamın açıkça belli ettiği duyguyla söylenenlere şu etiketlerden birini '
    'ver: [laughs] (gülerek), [sighs] (iç çekerek), [fısıldar] (fısıldayarak), [shouting] (bağırarak), [angry] '
    '(öfkeyle). Emin olmadığın, nötr ya da anlatıcı cümlelerine etiket verme. Yalnızca JSON nesnesi döndür; '
    'anahtar cümle numarası, değer etiket. Örnek: {"12": "[laughs]", "15": "[angry]"}. Hiçbiri yoksa {}.\n\n')


def llm_lines(sentences, breaks, start, stop):
    ends = {int(b) for b in breaks or ()}
    lines = []
    for i in range(start, stop):
        lines.append(f'{i}: {sentences[i]}')
        if i in ends:
            lines.append('')
    return '\n'.join(lines).strip()


def parse_llm(raw, sentences, start, stop):
    """Model yanitindan {numara: etiket}: yalnizca araliktaki konusma cumleleri ve bilinen etiketler."""
    match = re.search(r'\{.*\}', str(raw or ''), re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    result = {}
    for key, value in (data.items() if isinstance(data, dict) else ()):
        try:
            index = int(str(key).strip())
        except ValueError:
            continue
        tag = str(value or '').strip()
        tag = tag if tag.startswith('[') else f'[{tag}]'
        if start <= index < stop and tag in TAGS and is_speech(sentences[index]):
            result[index] = tag
    return result


def tag_with_llm(sentences, breaks, ask, cancel=None):
    """Model sunucusuyla etiketleme: `ask(istem) -> yanit metni`. Donen: her cumle icin etiket ('' yok). Konusmalarin
    yarisindan fazlasini etiketleyen yanit (kucuk model istemi anlamamis: her seye [laughs]) yok sayilir."""
    sentences = [str(s) for s in sentences]
    tags = [''] * len(sentences)
    for start in range(0, len(sentences), LLM_BATCH):
        if cancel is not None and cancel.is_set():
            break
        stop = min(len(sentences), start + LLM_BATCH)
        speech = sum(is_speech(sentences[i]) for i in range(start, stop))
        if not speech:
            continue
        found = parse_llm(ask(LLM_PROMPT + llm_lines(sentences, breaks, start, stop)), sentences, start, stop)
        if len(found) > max(LLM_MAX_TAGGED, speech // 2):
            continue
        for index, tag in found.items():
            tags[index] = tag
    return tags


# ---------------------------------------------------------------- kitap basina saklama
def _key(text):
    return ' '.join(str(text).split())


class Store:
    """APP_DIR/duygu-etiketleri/<kitap>.json (bellekte onbellekli)."""

    def __init__(self, app_dir):
        self.directory = Path(app_dir) / STORE_DIR
        self._lock = threading.RLock()
        self._cache = {}

    def _path(self, book):
        if not re.fullmatch(r'[0-9a-f]{8,40}', str(book or '')):
            raise ValueError('Geçersiz kitap kimliği.')
        return self.directory / f'{book}.json'

    def load(self, book):
        with self._lock:
            if book not in self._cache:
                try:
                    data = json.loads(self._path(book).read_text(encoding='utf-8'))
                    if data.get('version') != VERSION:
                        raise ValueError
                except (OSError, ValueError, AttributeError):
                    data = {}
                self._cache[book] = {'version': VERSION, 'words': dict(data.get('words') or {}),
                                     'llm': dict(data.get('llm') or {})}
            return self._cache[book]

    def update(self, book, kind, sentences, tags):
        """`kind` ('words'/'llm') haritasina bu cumlelerin etiketlerini yazar; degistiyse kaydeder. 'words'
        yalnizca etiketlileri tutar, 'llm' etiketsizleri de ('') tutar (bolum modelle islendi)."""
        with self._lock:
            data = self.load(book)
            table, changed = data[kind], False
            for text, tag in zip(sentences, tags):
                key = _key(text)
                if not key:
                    continue
                if tag or kind == 'llm':
                    if table.get(key) != tag:
                        table[key], changed = tag, True
                elif key in table:
                    del table[key]
                    changed = True
            if changed:
                path = self._path(book)
                path.parent.mkdir(parents=True, exist_ok=True)
                partial = path.with_suffix('.part')
                partial.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
                partial.replace(path)
            return changed

    def has_llm(self, book, sentences):
        table = self.load(book)['llm']
        return all(_key(s) in table for s in sentences if _key(s))

    def tag(self, book, text, mode):
        """Bir cumlenin etiketi: 'words' kipinde kelime listesi; 'llm' kipinde modelin etiketi, model etiket vermediyse
        kelime listesininki (anlaticidaki acik ipucu modelden daha guvenilir)."""
        if mode not in ('words', 'llm') or not re.fullmatch(r'[0-9a-f]{8,40}', str(book or '')):
            return ''
        data, key = self.load(book), _key(text)
        if mode == 'llm' and data['llm'].get(key):
            return data['llm'][key]
        return data['words'].get(key, '')

    def clear(self, book=None):
        with self._lock:
            self._cache.clear()
            targets = [self._path(book)] if book else list(self.directory.glob('*.json'))
            for path in targets:
                path.unlink(missing_ok=True)
