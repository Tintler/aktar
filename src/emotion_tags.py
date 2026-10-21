"""Drama 3 duygu etiketleri (F168, deneysel): kitap diyaloglarina [laughs], [sighs] ... atanir.

Turkceye budanmis Drama 3'te yalnizca parcanin EN BASINDAKI su etiketler calisiyor (kullanicinin dinleme seti):
[laughs], [sighs], [fısıldar], [shouting], [angry]. Sonda ya da tirnak icindeki [laughs], <whisper>, [iç çeker],
[crying] calismiyor; [güler] yalnizca bazen.

Etiketleme okuyucunun kendi cumleleri uzerinde yapilir (web/src/lib/sentences.js bolmesi + paragraf sonlari):
anlaticidaki ipucu ('gulerek', 'fisildadi', 'bagirdi' ...) ayni paragraftaki konusma cumlesine (tirnakli ya da
cizgili) atanir; anlatici cumlesi etiket almaz. Istege bagli olarak model sunucusu (llm_provider) baglamdan
cikarir. Okuyucuda gorunen metin degismez: etiket yalnizca sunucuya giden metne eklenir (drama3.tagged).

F170: etiketleme okurken yapilmaz (ses motoru ile dil modeli ayni anda bellegi dolduruyordu); kitapligin sag tik
menusunden butun kitap icin bir kez calisir (tag_book) ve kitabin etiketli surumu APP_DIR/duygu-etiketleri altina
yazilir: <kitap>.json cumle metnine gore etiketler, <kitap>.txt okunabilir etiketli metin:
    {"version": 2, "method": "llm"|"words", "created", "sentences", "tagged", "tags": {cumle: etiket}}
Okuyucu Drama 3 ile okurken etiketli surumu (Ayarlar'da ya da okuyucuda kapatilmadiysa) kullanir.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path

from drama3 import EMOTION_TAGS as TAGS, tagged   # [laughs], [sighs], [fısıldar], [shouting], [angry]

METHODS = ('words', 'llm')
STORE_DIR = 'duygu-etiketleri'
VERSION = 2

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


def tag_with_llm(sentences, breaks, ask, cancel=None, progress=None):
    """Model sunucusuyla etiketleme: `ask(istem) -> yanit metni`. Donen: her cumle icin etiket ('' yok). Konusmalarin
    yarisindan fazlasini etiketleyen yanit (kucuk model istemi anlamamis: her seye [laughs]) yok sayilir.
    `progress(islenen_cumle)` her parcadan sonra cagrilir."""
    sentences = [str(s) for s in sentences]
    tags = [''] * len(sentences)
    for start in range(0, len(sentences), LLM_BATCH):
        if cancel is not None and cancel.is_set():
            break
        stop = min(len(sentences), start + LLM_BATCH)
        speech = sum(is_speech(sentences[i]) for i in range(start, stop))
        if speech:
            found = parse_llm(ask(LLM_PROMPT + llm_lines(sentences, breaks, start, stop)), sentences, start, stop)
            if len(found) <= max(LLM_MAX_TAGGED, speech // 2):
                for index, tag in found.items():
                    tags[index] = tag
        if progress:
            progress(stop)
    return tags


class Cancelled(RuntimeError):
    """Kullanici etiketlemeyi durdurdu."""


def tag_book(sections, ask=None, cancel=None, progress=None):
    """Butun kitabi etiketler (F170). `sections`: [{'sentences', 'breaks'}] okuyucunun bolmesiyle. `ask` verilirse
    model sunucusu da sorulur; modelin etiket vermedigi konusmada kelime listesininki kalir (anlaticidaki acik
    ipucu modelden daha guvenilir). Donen: bolum basina etiket listeleri. `progress(islenen, toplam)`;
    durdurulursa Cancelled."""
    total = sum(len(section['sentences']) for section in sections)
    result, done = [], 0
    for section in sections:
        if cancel is not None and cancel.is_set():
            raise Cancelled('Duygu etiketleme durduruldu.')
        sentences, breaks = section['sentences'], section.get('breaks') or ()
        tags = tag_sentences(sentences, breaks)
        if ask is not None:
            step = (lambda count, base=done: progress(base + count, total)) if progress else None
            found = tag_with_llm(sentences, breaks, ask, cancel, step)
            tags = [llm or words for llm, words in zip(found, tags)]
        result.append(tags)
        done += len(sentences)
        if progress:
            progress(done, total)
    if cancel is not None and cancel.is_set():
        raise Cancelled('Duygu etiketleme durduruldu.')
    return result


# ---------------------------------------------------------------- kitabin etiketli surumu
def _key(text):
    return ' '.join(str(text).split())


def tagged_text(sections, tags):
    """Okunabilir etiketli metin (<kitap>.txt): bolumler arasi bos satir, paragraf basina bir satir."""
    blocks = []
    for section, section_tags in zip(sections, tags):
        ends = {int(b) for b in section.get('breaks') or ()}
        lines, line = [], []
        for i, (text, tag) in enumerate(zip(section['sentences'], section_tags)):
            line.append(tagged(text, tag) if tag else _key(text))
            if i in ends:
                lines.append(' '.join(line))
                line = []
        if line:
            lines.append(' '.join(line))
        if lines:
            blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks) + '\n'


class Store:
    """APP_DIR/duygu-etiketleri/<kitap>.json + .txt (bellekte onbellekli)."""

    def __init__(self, app_dir):
        self.directory = Path(app_dir) / STORE_DIR
        self._lock = threading.RLock()
        self._cache = {}

    def _path(self, book):
        if not re.fullmatch(r'[0-9a-f]{8,40}', str(book or '')):
            raise ValueError('Geçersiz kitap kimliği.')
        return self.directory / f'{book}.json'

    def load(self, book):
        """Kitabin etiketli surumu (yoksa None)."""
        with self._lock:
            if book not in self._cache:
                try:
                    data = json.loads(self._path(book).read_text(encoding='utf-8'))
                    if data.get('version') != VERSION or not isinstance(data.get('tags'), dict):
                        raise ValueError
                except (OSError, ValueError, AttributeError):
                    data = None
                self._cache[book] = data
            return self._cache[book]

    def save(self, book, method, sections, tags):
        """Butun kitabin etiketlerini yazar (oncekinin yerine). Donen: info()."""
        table = {}
        for section, section_tags in zip(sections, tags):
            for text, tag in zip(section['sentences'], section_tags):
                if tag and _key(text):
                    table[_key(text)] = tag
        data = {'version': VERSION, 'method': method if method in METHODS else 'words',
                'created': datetime.now().isoformat(timespec='seconds'),
                'sentences': sum(len(section['sentences']) for section in sections), 'tagged': len(table),
                'tags': table}
        with self._lock:
            path = self._path(book)
            path.parent.mkdir(parents=True, exist_ok=True)
            for target, content in ((path, json.dumps(data, ensure_ascii=False, indent=1)),
                                    (path.with_suffix('.txt'), tagged_text(sections, tags))):
                partial = target.with_name(target.name + '.part')
                partial.write_text(content, encoding='utf-8')
                partial.replace(target)
            self._cache[book] = data
        return self.info(book)

    def info(self, book):
        """{'method', 'created', 'sentences', 'tagged', 'text'} ya da None."""
        data = self.load(book)
        if not data:
            return None
        return {key: data.get(key) for key in ('method', 'created', 'sentences', 'tagged')} | {
            'text': str(self._path(book).with_suffix('.txt'))}

    def books(self):
        """Etiketli surumu olan kitaplar."""
        return sorted(path.stem for path in self.directory.glob('*.json') if self.load(path.stem))

    def tag(self, book, text):
        """Bir cumlenin etiketi ('' yok)."""
        if not re.fullmatch(r'[0-9a-f]{8,40}', str(book or '')):
            return ''
        data = self.load(book)
        return data['tags'].get(_key(text), '') if data else ''

    def clear(self, book=None):
        with self._lock:
            self._cache.clear()
            targets = [self._path(book)] if book else list(self.directory.glob('*.json'))
            for path in targets:
                path.unlink(missing_ok=True)
                path.with_suffix('.txt').unlink(missing_ok=True)
