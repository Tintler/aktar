"""Paylasilan cekirdek: yapilandirma, dosya G/C, kilit, glossary, LM Studio istemcisi.

Bu modul hem arayuz (gui.py) hem komut satiri (cevir.py) tarafindan kullanilir.
Ceviri/checkpoint/glossary mantigi burada tek yerde tutulur; arayuze veya CLI'a
kopyalanmaz.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import fonts
import subtitle

try:
    import msvcrt  # Windows OS bolgesi kilidi (FileLock)
except ImportError:  # Windows disi ortamlar (gelistirme/CI) icin
    msvcrt = None
try:
    import fcntl  # POSIX esdegeri
except ImportError:
    fcntl = None

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
APP_DIR = (Path(sys.executable).resolve().parent
           if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent)

DEFAULT_CONFIG = {
    'base_url': 'http://127.0.0.1:1234/v1',
    'model': 'gemma-4-26b-a4b-it-qat@q4_k_xl',
    'batch_cues': 10,
    'max_tokens': 8192,
    'temperature': 0.2,
    'timeout_seconds': 1800,
    'auto_retry_count': 2,
    'glossary_strict': False,
    'analysis_chunk_chars': 12000,
    # Reasoning/thinking ureten modellerde dusunmeyi kapatma denemesi
    # (LM Studio chat_template_kwargs desteklerse). Desteklenmezse yok sayilir;
    # o durumda LM Studio model preset'inden thinking kapatilmalidir.
    'disable_thinking': False,
}

# Model yanitindaki bu onekler gecici/dogrulama hatasi sayilir ve yeniden denenir.
TRANSLATION_RESPONSE_ERROR_PREFIXES = (
    'Yanıt ', 'Ön analiz ', 'Beklenmeyen API çıktısı', 'Boş veya kod bloğu',
    'Yanıt düşünce/tool işaretleri', 'Görünür newline kaçışları',
    'Yapısal altyazı işaretleri', 'Çeviri kimlikleri',
    # Eski checkpoint/test mesajlarıyla geriye uyumluluk.
    'Yanit ', 'On analiz ', 'Beklenmeyen API cikti', 'Bos veya kod blogu',
)


class GracefulStop(Exception):
    """Yalnizca mevcut yanit checkpoint'e yazildiktan sonra firlatilir."""


def retryable_translation_error(error):
    message = str(error)
    if isinstance(error, ValueError):
        return message.startswith(TRANSLATION_RESPONSE_ERROR_PREFIXES)
    if isinstance(error, RuntimeError):
        return (message.startswith(('LM Studio baglantisi kurulamadi',
                                    'LM Studio istegi zaman asimina ugradi'))
                or bool(re.match(r'HTTP (?:408|429|5\d\d):', message)))
    return False


def read(path):
    return Path(path).read_text(encoding='utf-8-sig')


def atomic(path, text):
    """Gecici dosyaya yazip atomik olarak hedefe tasir."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def save_json(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class FileLock:
    """Isletim sistemi seviyesinde dosya bolgesi kilidi.

    Duz 'kilit dosyasi var mi' yaklasimi cokme sonrasi bayat dosya birakir ve
    sonraki tum calismalari bloklar. Burada kilit isletim sistemine aittir ve
    kilidi tutan surec olunce otomatik birakilir.
    """

    def __init__(self, path):
        self.path = Path(path)
        self._handle = None

    def acquire(self):
        if msvcrt is None and fcntl is None:  # pragma: no cover
            raise RuntimeError('Proje kilidi bu işletim sisteminde desteklenmiyor.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_BINARY', 0))
        try:
            if msvcrt is not None:
                if os.fstat(handle).st_size < 1:
                    os.write(handle, b'\x00')
                os.lseek(handle, 0, os.SEEK_SET)
                msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(handle)
            raise RuntimeError(
                'Bu seri/sözlük dosyası başka bir Aktar örneği tarafından '
                'kullanılıyor. Diğer örnekleri kapatıp yeniden deneyin.'
            ) from None
        self._handle = handle
        return self

    def release(self):
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if msvcrt is not None:
                os.lseek(handle, 0, os.SEEK_SET)
                msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            os.close(handle)
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback_):
        self.release()
        return False


def load_config(path=None):
    path = Path(path or APP_DIR / 'config.json')
    value = dict(DEFAULT_CONFIG)
    if path.exists():
        value.update(json.loads(read(path)))
    validate_config(value)
    return value


def validate_config(cfg):
    from urllib.parse import urlparse
    parsed = urlparse(str(cfg['base_url']))
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('base_url yalnızca yerel HTTP adresi olabilir.')
    if not str(cfg['model']).strip():
        raise ValueError('Model adı boş olamaz.')
    for key in ('batch_cues', 'max_tokens', 'timeout_seconds', 'analysis_chunk_chars'):
        if int(cfg[key]) <= 0:
            raise ValueError(f'{key} sıfırdan büyük olmalı.')
    if not 1 <= int(cfg['auto_retry_count']) <= 100:
        raise ValueError('auto_retry_count 1 ile 100 arasında olmalı.')
    if not 0 <= float(cfg['temperature']) <= 2:
        raise ValueError('temperature 0 ile 2 arasında olmalı.')
    if not isinstance(cfg.get('disable_thinking', False), bool):
        raise ValueError('disable_thinking true veya false olmalı.')


def tr_lower(text):
    """Turkce kucuk harf: I -> ı, İ -> i (str.lower/casefold bunu yanlis yapar)."""
    return str(text).replace('I', 'ı').replace('İ', 'i').lower()


def _harmony(*templates):
    result = set()
    for template in templates:
        if 'I' in template:
            result.update(template.replace('I', vowel) for vowel in 'ıiuü')
        elif 'A' in template:
            result.update(template.replace('A', vowel) for vowel in 'ae')
        else:
            result.add(template)
    return result


def _expand_consonants(values):
    result = set()
    for value in values:
        if 'D' in value:
            result.update(value.replace('D', letter) for letter in 'dt')
        elif 'C' in value:
            result.update(value.replace('C', letter) for letter in 'cç')
        else:
            result.add(value)
    return result


# Turkce isim cekim ekleri ve ek-fiiller. Yapim ekleri (-lı, -cı, -lık) kasitli
# olarak YOK: "yapılı", "külot" glossary karsiligi sayilmaz.
_TURKISH_SUFFIX_TOKENS = frozenset(_expand_consonants(
    _harmony('lAr', 'I', 'sI', 'yI', 'nI', 'A', 'yA', 'nA', 'DA', 'nDA', 'DAn', 'nDAn',
             'In', 'nIn', 'lA', 'ylA', 'Im', 'm', 'n', 'ImIz', 'mIz', 'InIz', 'nIz',
             'CA', 'ki', 'ken', 'yken', 'DIr', 'DI', 'yDI', 'sA', 'ysA', 'mIş', 'ymIş')
    | {'nDAki', 'DAki'}
))

_SOFTEN = {'p': 'b', 'ç': 'c', 't': 'd', 'k': 'ğ'}
_VOWELS = set('aeıioöuüâîû')


def _is_suffix_chain(rest, _cache={}):
    if rest in _cache:
        return _cache[rest]
    if not rest:
        return True
    if len(rest) > 18:
        return False
    found = any(rest.startswith(token) and _is_suffix_chain(rest[len(token):])
                for token in _TURKISH_SUFFIX_TOKENS)
    _cache[rest] = found
    return found


def _stem_variants(word):
    """Cekim sirasinda alinabilecek govde bicimleri:
    kitap -> kitab, ağaç -> ağac, renk -> reng, burun -> burn, Yapılar -> yapı."""
    variants = {word}
    last = word[-1:]
    if last in _SOFTEN and len(word) >= 3:
        variants.add(word[:-1] + _SOFTEN[last])
        if last == 'k' and word[-2:-1] == 'n':
            variants.add(word[:-1] + 'g')
    if (len(word) >= 4 and word[-1] not in _VOWELS and word[-2] in _VOWELS
            and word[-3] not in _VOWELS):
        variants.add(word[:-2] + word[-1])
    for plural in ('lar', 'ler'):
        index = word.find(plural)
        if index >= 2 and _is_suffix_chain(word[index:]):
            variants.add(word[:index])
    return variants


def _target_search(target, text):
    """Glossary karsiligi ceviride Turkce cekimli olarak geciyor mu?

    Metindeki kelime, hedefin govde bicimlerinden biriyle baslamali ve geriye
    kalan kisim yalnizca bilinen cekim eklerinden olusmali. Cok kelimeli
    hedeflerde onceki kelimeler aynen ve ardisik gecmeli; ek yalnizca son
    kelimeye gelir.
    """
    target_words = re.findall(r'[^\W\d_]+', tr_lower(target))
    if not target_words:
        return False
    words = re.findall(r'[^\W\d_]+', tr_lower(text))
    head, last = target_words[:-1], target_words[-1]
    variants = sorted(_stem_variants(last), key=len, reverse=True)
    for index in range(len(head), len(words)):
        if words[index - len(head):index] != head:
            continue
        word = words[index]
        if any(word.startswith(variant) and _is_suffix_chain(word[len(variant):])
               for variant in variants):
            return True
    return False


def source_term_regex(term):
    """Ingilizce kaynak terimi tam kelime olarak arar; yalnizca -s/-es ve iyelik
    's eklerine izin verir: "Ash" -> "Ash's" evet, "ashamed" hayir."""
    return re.compile(r'(?<!\w)' + re.escape(term) + r"(?:s|es|'s|’s)?(?!\w)", re.I)


# On analiz icin aday terim deseni: cok kelimeli buyuk harfli obekler veya tek
# kelimeli buyuk harfli sozcukler (>=4 harf).
_TERM_CANDIDATE = re.compile(
    r"(?<![A-Za-z'’])([A-Z][A-Za-z'’]+(?:[ \t]+[A-Z][A-Za-z'’]+)+|[A-Z][A-Za-z'’]{3,})(?![A-Za-z'’])"
)


def candidate_terms(cues, min_count=2):
    """On analiz (ON HAZIRLIK): kaynak altyazida tekrar eden aday terimler.

    Yalnizca ONERI listesidir; seri sozlugune YAZILMAZ (onay akisi F14 kapsaminda).
    Cumle basindaki tek kelimeli buyuk harfler aday sayilmaz (gurultuyu azaltir);
    cok kelimeli obekler her zaman aday sayilir. Donen: [{'source', 'count'}].
    """
    counter = Counter()
    for cue in cues:
        if not cue.translatable:
            continue
        visible = subtitle.send_text(subtitle.analyze(cue.text))
        for line in (visible or '').splitlines():
            stripped = line.strip()
            for match in _TERM_CANDIDATE.finditer(stripped):
                term = ' '.join(match.group(1).split())
                if match.start() == 0 and len(term.split()) == 1:
                    continue  # cumle basi tek kelime: aday degil
                counter[term] += 1
    return [{'source': term, 'count': count}
            for term, count in counter.most_common()
            if count >= min_count or len(term.split()) >= 2]


TERM_ANALYSIS_PROMPT = '''Analyze the supplied English subtitle text for durable Turkish translation terminology.
Return only valid JSON without Markdown or commentary, using exactly this shape:
{"terms":[{"source":"exact source expression","target":"Turkish translation suggestion","type":"term|title|place|race|item|ability|phrase|name","reason":"short Turkish reason"}],"decisions":[{"type":"proper_name|address|voice|recurring_phrase|style","value":"concise durable Turkish decision","reason":"short Turkish reason"}]}
Suggest only expressions that are useful for consistency in later episodes. Include lowercase fictional terminology, titles, places, races/species, items, abilities and recurring fixed phrases. Do not suggest ordinary vocabulary. A proper name that stays unchanged belongs in decisions, not terms. Do not repeat an existing glossary item. Do not invent source expressions. Every source must occur verbatim in the supplied source text. Every term target must be non-empty.'''

POST_ANALYSIS_PROMPT = '''Inspect aligned English source and Turkish subtitle translation pairs.
Return only valid JSON without Markdown or commentary, using exactly this shape:
{"terms":[{"source":"exact English expression","target":"Turkish rendering actually used","type":"term|title|place|race|item|ability|phrase|name","reason":"short Turkish reason"}],"decisions":[{"type":"proper_name|address|voice|recurring_phrase|style","value":"concise durable Turkish decision","reason":"short Turkish reason"}]}
Extract only durable terminology and continuity decisions useful in later episodes. Do not invent or improve a translation: each source must occur in SOURCE and each target must already occur in TRANSLATION. Do not include ordinary vocabulary or an existing glossary item.'''


def visible_cue_text(cue):
    """ASS/SRT/VTT yapisini atip yalnizca modele giden gorunur metni dondurur."""
    if not cue.translatable:
        return ''
    return subtitle.send_text(subtitle.analyze(cue.text)) or ''


def _clean_analysis_json(text):
    value = str(text).strip()
    if value.startswith('```') and value.endswith('```'):
        lines = value.splitlines()
        value = '\n'.join(lines[1:-1]).strip()
    try:
        value = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError('Ön analiz yanıtı geçerli JSON değil.') from error
    if not isinstance(value, dict) or not isinstance(value.get('terms', []), list) \
            or not isinstance(value.get('decisions', []), list):
        raise ValueError('Ön analiz JSON şeması geçersiz.')
    return value


def parse_term_analysis(text, source_text, translated_text=None, existing=None):
    """LLM terim JSON'unu kaynaga dayali olarak dogrular ve normalize eder."""
    value = _clean_analysis_json(text)
    existing_keys = {str(item.get('source', '')).strip().casefold() for item in (existing or [])}
    terms, seen = [], set()
    for item in value.get('terms', []):
        if not isinstance(item, dict):
            continue
        source = str(item.get('source', '')).strip()
        target = str(item.get('target', item.get('suggested_target', ''))).strip()
        key = source.casefold()
        if not source or not target or key in seen or key in existing_keys:
            continue
        matches = list(source_term_regex(source).finditer(source_text))
        if not matches:
            continue
        if translated_text is not None and not _target_search(target, translated_text):
            continue
        seen.add(key)
        kind = str(item.get('type', 'term')).strip().lower()
        if kind not in {'term', 'title', 'place', 'race', 'item', 'ability', 'phrase', 'name'}:
            kind = 'term'
        terms.append({
            'source': source,
            'target': target,
            'type': kind,
            'reason': str(item.get('reason', '')).strip(),
            'count': len(matches),
        })
    decisions, decision_seen = [], set()
    for item in value.get('decisions', []):
        if isinstance(item, str):
            item = {'value': item}
        if not isinstance(item, dict):
            continue
        decision = str(item.get('value', '')).strip()
        key = decision.casefold()
        if not decision or key in decision_seen:
            continue
        decision_seen.add(key)
        decisions.append({
            'type': str(item.get('type', 'style')).strip().lower() or 'style',
            'value': decision,
            'reason': str(item.get('reason', '')).strip(),
        })
    return {'terms': terms, 'decisions': decisions}


def _analysis_chunks(source_cues, translated_cues=None, limit=12000):
    """Cue sinirlarini bozmadan analiz istekleri olusturur."""
    rows = []
    translated_cues = translated_cues or []
    for index, cue in enumerate(source_cues):
        source = visible_cue_text(cue).strip()
        if not source:
            continue
        if translated_cues:
            target = visible_cue_text(translated_cues[index]).strip()
            row = f'ID: {index + 1}\nSOURCE: {source}\nTRANSLATION: {target}'
        else:
            row = f'ID: {index + 1}\nSOURCE: {source}'
        rows.append(row)
    chunks, current, length = [], [], 0
    for row in rows:
        if current and length + len(row) + 2 > limit:
            chunks.append('\n\n'.join(current)); current, length = [], 0
        current.append(row); length += len(row) + 2
    if current:
        chunks.append('\n\n'.join(current))
    return chunks


def _dedupe_glossary(items):
    """Ayni kaynak terimi (casefold) yalnizca ilk kaydiyla korur; boslari atlar."""
    result, seen = [], set()
    for item in items or []:
        source = str(item.get('source', '')).strip()
        target = str(item.get('target', '')).strip()
        if not source or not target:
            continue
        key = source.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({'source': source, 'target': target})
    return result


def merge_glossaries(*layers):
    """Glossary katmanlarini sirayla birlestirir.

    SONRAKI katman ayni kaynak terimde kazanir: seri sozlugu taban, bolume ozel
    sozluk ustundur. Cikti sirasi ilk gorulme sirasidir.
    """
    merged, order = {}, []
    for layer in layers:
        for item in _dedupe_glossary(layer or []):
            key = item['source'].casefold()
            if key not in merged:
                order.append(key)
            merged[key] = item
    return [merged[key] for key in order]


def glossary_text(items):
    if not items:
        return '(Kullanici tarafindan tanimlanmis ozel terim yok.)'
    return '\n'.join(f'- {item["source"]} -> {item["target"]}' for item in items)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('HTTP yonlendirmesi kabul edilmiyor.')


class Client:
    """LM Studio yerel sunucu istemcisi (yalnizca yerel HTTP, proxy yok)."""

    def __init__(self, cfg, log=print):
        validate_config(cfg)
        self.cfg = cfg
        self.log = log
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _url(self, route):
        from urllib.parse import urlsplit
        base = self.cfg['base_url'].rstrip('/')
        parsed = urlsplit(base)
        if route.startswith('/api/'):
            return f'{parsed.scheme}://{parsed.netloc}{route}'
        return base + route

    def request(self, route, payload=None):
        headers = {'Content-Type': 'application/json'}
        token = os.environ.get('LM_STUDIO_API_KEY')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(
            self._url(route),
            data=None if payload is None else json.dumps(payload).encode('utf-8'),
            headers=headers,
        )
        try:
            with self.opener.open(request, timeout=self.cfg['timeout_seconds']) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'HTTP {error.code}: LM Studio istegi reddedildi.') from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise RuntimeError('LM Studio istegi zaman asimina ugradi.') from None
            raise RuntimeError('LM Studio baglantisi kurulamadi: ' + str(self.cfg['base_url'])) from None
        except TimeoutError:
            raise RuntimeError('LM Studio istegi zaman asimina ugradi.') from None

    def models(self):
        value = self.request('/models')
        return [item['id'] for item in value.get('data', []) if item.get('id')]

    def generate(self, system, user, temperature=None, max_tokens=None):
        payload = {
            'model': self.cfg['model'],
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            'temperature': self.cfg['temperature'] if temperature is None else temperature,
            'max_tokens': self.cfg['max_tokens'] if max_tokens is None else max_tokens,
            'stream': False,
        }
        # Reasoning/thinking modellerinde dusunmeyi kapatma denemesi. LM Studio
        # bu alani desteklemezse yok sayar; kalici cozum model preset'idir.
        if self.cfg.get('disable_thinking'):
            payload['chat_template_kwargs'] = {'enable_thinking': False}
        value = self.request('/chat/completions', payload)
        try:
            choice = value['choices'][0]
            message = choice['message']
        except (KeyError, IndexError, TypeError):
            raise ValueError('Beklenmeyen API çıktısı biçimi.') from None
        text = message.get('content') or ''
        if not str(text).strip():
            # Teshis: model neden metin dondurmedi? finish_reason=length + yuksek
            # reasoning_tokens ise model dusunmeye tum token butcesini harcadi.
            finish = choice.get('finish_reason') or 'yok'
            reasoning = message.get('reasoning_content') or message.get('reasoning') or ''
            details = (value.get('usage') or {}).get('completion_tokens_details') or {}
            reasoning_tokens = details.get('reasoning_tokens')
            extra = f', düşünce_token={reasoning_tokens}' if reasoning_tokens else ''
            raise ValueError(
                'Boş veya kod bloğu içeren yanıt alındı: model metin döndürmedi '
                f'(finish_reason={finish}, düşünce_uzunluğu={len(str(reasoning))}{extra}). '
                'Model düşünme (reasoning) üretiyor olabilir: LM Studio model preset\'inde '
                'thinking/reasoning kapatın, config.json içindeki disable_thinking değerini '
                'deneyin veya max_tokens değerini artırın.'
            )
        if choice.get('finish_reason') == 'length':
            raise ValueError('Yanıt token sınırında kesildi; eksik çeviri kabul edilmedi.')
        if choice.get('finish_reason') not in (None, 'stop'):
            raise ValueError('Yanıt tamamlanmadı: ' + str(choice.get('finish_reason')))
        return text


def prompt_path():
    external = APP_DIR / 'translation_prompt.txt'
    return external if external.exists() else ROOT / 'translation_prompt.txt'


def clean_response(text):
    """Model yanitini dogrular: bos/kod blogu, dusunce-tool isareti, kacis newline.

    Hata mesajina yanitin baslangici eklenir; boylece "neden bos" sorusu
    tahmine kalmaz.
    """
    value = str(text).strip()
    preview = value[:180].replace('\n', ' / ')
    if not value:
        raise ValueError('Boş veya kod bloğu içeren yanıt alındı: yanıt tamamen boş.')
    if '```' in value:
        raise ValueError('Boş veya kod bloğu içeren yanıt alındı: kod bloğu. Başlangıç: ' + preview)
    if (re.search(r'<\|channel>|<tool_call|<\|tool_call', value)
            or re.search(r'(?m)^[ \t]*(?:thinking|response)\b', value)):
        raise ValueError('Yanıt düşünce/tool işaretleri içeriyor. Başlangıç: ' + preview)
    if '\\n' in value and '\n' not in value:
        raise ValueError('Görünür newline kaçışları içeriyor. Başlangıç: ' + preview)
    return value


def glossary_missing(source_text, translated_text, glossary):
    """Kaynaginda gecen ama ceviride karsiligi bulunmayan glossary girdileri.

    Denetim yalnizca kaynagi bu parcada GECEN terimler icin yapilir; kaynakta
    gecmeyen bir terimin karsiligi aranmaz.
    """
    missing = []
    for item in glossary:
        if source_term_regex(item['source']).search(source_text):
            if not _target_search(item['target'], translated_text):
                missing.append(item)
    return missing


GLOSSARY_FIX_PROMPT = (
    'The previous translation missed mandatory glossary renderings. '
    'Return the corrected entries for ALL supplied IDs, in the same ID/TEXT format, '
    'using the required Turkish target for each listed term. '
    'Change only what is needed; keep every other entry as it was. No commentary.'
)


class PauseController:
    """Duraklatma/kapatma denetimi. checkpoint() guvenli noktalarda cagrilir."""

    def __init__(self, state_callback=None):
        self._condition = threading.Condition()
        self._pause_requested = False
        self._close_requested = False
        self._state_callback = state_callback or (lambda _state: None)

    def set_state_callback(self, callback):
        self._state_callback = callback

    @property
    def pause_requested(self):
        with self._condition:
            return self._pause_requested

    def request_pause(self):
        with self._condition:
            self._pause_requested = True
        self._state_callback('pausing')

    def resume(self):
        with self._condition:
            self._pause_requested = False
            self._condition.notify_all()
        self._state_callback('running')

    def request_close(self):
        with self._condition:
            self._close_requested = True
            self._pause_requested = False
            self._condition.notify_all()
        self._state_callback('closing')

    def checkpoint(self):
        with self._condition:
            if self._close_requested:
                raise GracefulStop('Mevcut istek kaydedildi; program kapatılıyor.')
            if not self._pause_requested:
                return
            self._state_callback('paused')
            while self._pause_requested and not self._close_requested:
                self._condition.wait()
            if self._close_requested:
                raise GracefulStop('Mevcut istek kaydedildi; program kapatılıyor.')
            self._state_callback('running')


class TranslationEngine:
    """Altyazi ceviri cekirdegi. Arayuz ve CLI ayni motoru kullanir.

    Modele yalnizca ID/TEXT gonderilir; timestamp/sira/ASS tag'leri program
    tarafinda korunur. Her parti sonrasi kontrol noktasi yazilir; kesilirse
    kaldigi partiden devam edilir.
    """

    def __init__(self, config_provider, log=print):
        self.config_provider = config_provider
        self.log = log
        self.failed_fixes = []

    def analyze_terms(self, cues, glossary=None, translated_cues=None, checkpoint=None,
                      pause=None, progress=None):
        """On analiz veya ceviri-sonu kalici terim/continuity onerileri uretir.

        `translated_cues` yoksa on analiz, varsa hizali kaynak/ceviri analizi
        yapilir. Her LLM parcasi checkpoint'e yazilir; yalnizca kaynaga dayali
        ve mevcut glossary'de bulunmayan oneriler dondurulur.
        """
        cfg = dict(self.config_provider())
        validate_config(cfg)
        glossary = _dedupe_glossary(glossary or [])
        translated_cues = list(translated_cues or [])
        if translated_cues and len(translated_cues) != len(cues):
            raise ValueError('Çeviri sonu analizinde kaynak/çeviri girdi sayısı uyuşmuyor.')
        chunks = _analysis_chunks(cues, translated_cues or None,
                                  max(1000, int(cfg['analysis_chunk_chars'])))
        if not chunks:
            return {'terms': [], 'decisions': []}
        mode = 'post' if translated_cues else 'pre'
        system = POST_ANALYSIS_PROMPT if translated_cues else TERM_ANALYSIS_PROMPT
        source_text = '\n'.join(visible_cue_text(cue) for cue in cues)
        translated_text = ('\n'.join(visible_cue_text(cue) for cue in translated_cues)
                           if translated_cues else None)
        signature = digest(json.dumps({
            'mode': mode, 'chunks': chunks, 'glossary': glossary,
            'model': cfg['model'], 'prompt': system,
        }, ensure_ascii=False, sort_keys=True))
        state = {'signature': signature, 'parts': []}
        if checkpoint and Path(checkpoint).exists():
            loaded = json.loads(read(checkpoint))
            if loaded.get('signature') != signature:
                raise ValueError('Ön analiz kontrol noktası bu altyazı/ayarlarla uyuşmuyor; '
                                 'önceki analizle devam edilemez.')
            state = loaded
        client = Client(cfg, log=self.log)
        total = len(chunks)
        if progress:
            progress(len(state.get('parts', [])), total)
        for index in range(len(state.get('parts', [])), total):
            if pause:
                pause.checkpoint()
            self.log(f'{"Çeviri sonu analizi" if translated_cues else "Ön analiz"} '
                     f'{index + 1}/{total} — yanıt bekleniyor...')
            glossary_note = glossary_text(glossary)
            user = 'EXISTING GLOSSARY:\n' + glossary_note + '\n\n' + chunks[index]
            def request_and_parse():
                raw = client.generate(system, user, temperature=0.1,
                                      max_tokens=min(int(cfg['max_tokens']), 4096))
                return parse_term_analysis(raw, source_text, translated_text, glossary)
            # JSON/sema hatasi da configured retry politikasina tabidir.
            parsed = self._retry(cfg, request_and_parse)
            state.setdefault('parts', []).append(parsed)
            if checkpoint:
                save_json(checkpoint, state)
            if progress:
                progress(index + 1, total)
            if pause:
                pause.checkpoint()
        terms, term_seen, decisions, decision_seen = [], set(), [], set()
        for part in state.get('parts', []):
            for item in part.get('terms', []):
                key = item['source'].casefold()
                if key in term_seen:
                    continue
                term_seen.add(key); terms.append(item)
            for item in part.get('decisions', []):
                key = item['value'].casefold()
                if key in decision_seen:
                    continue
                decision_seen.add(key); decisions.append(item)
        return {'terms': terms, 'decisions': decisions}

    def enforce_episode_terms(self, source_cues, translated_cues, glossary, pause=None):
        """Ceviri sonu onaylanan terimleri mevcut bolumdeki tum gecislere uygular.

        Yalnizca kaynaginda terim gecen ve cevirisinde onayli hedef bulunmayan
        cue'lar duzeltilir. Boylece son analizden ogrenilen karar yalniz sonraki
        bolume degil, tamamlanmakta olan bolume de tutarli bicimde yansir.
        """
        glossary = _dedupe_glossary(glossary or [])
        if not glossary:
            return list(translated_cues)
        cfg = dict(self.config_provider()); validate_config(cfg)
        client = Client(cfg, log=self.log)
        result = list(translated_cues)
        changed = 0
        for index, (source, translated) in enumerate(zip(source_cues, result)):
            if not source.translatable:
                continue
            missing = glossary_missing(visible_cue_text(source),
                                       visible_cue_text(translated), glossary)
            if not missing:
                continue
            if pause:
                pause.checkpoint()
            analysis = subtitle.analyze(translated.text)
            visible = subtitle.send_text(analysis)
            if visible is None:
                continue
            fixed = self._retry(cfg, lambda: self._fix_texts(
                client, [visible], missing, read(prompt_path())))[0]
            rebuilt = subtitle.Cue(
                subtitle.rebuild(analysis, fixed, note=self._note_reflow).split('\n'),
                start=translated.start, end=translated.end, index=translated.index,
                extra=translated.extra, prefix=translated.prefix)
            still = glossary_missing(visible_cue_text(source), visible_cue_text(rebuilt), missing)
            if still:
                names = ', '.join(item['source'] for item in still)
                if cfg.get('glossary_strict'):
                    raise ValueError('Bölüm içi terim tutarlılığı sağlanamadı: ' + names)
                self.log('UYARI: bölüm içi terim tutarlılığı sağlanamadı; '
                         'ilk çeviri korundu: ' + names)
                continue
            result[index] = rebuilt; changed += 1
        if changed:
            self.log(f'Bölüm içi terim tutarlılığı: {changed} altyazı girdisi düzeltildi.')
        return result

    # --- genel akis -------------------------------------------------------
    def translate(self, cues, glossary=None, decisions=None, prompt=None,
                  checkpoint=None, pause=None, progress=None):
        cfg = self.config_provider()
        validate_config(cfg)
        self.log(f'Model: {cfg["model"]} @ {cfg["base_url"]} (batch_cues={cfg["batch_cues"]})')
        glossary = _dedupe_glossary(glossary or [])
        decisions = [str(item).strip() for item in (decisions or []) if str(item).strip()]
        prompt = prompt if prompt is not None else read(prompt_path())
        items = subtitle.translatable(cues)
        if not items:
            return list(cues)
        signature = digest(json.dumps({
            'translation_protocol': 2,
            'sources': [(cue.text, cue.ass_fields) for cue in items],
            'glossary': glossary,
            'decisions': decisions,
            'prompt': prompt,
            'model': cfg['model'],
            'batch_cues': cfg['batch_cues'],
        }, ensure_ascii=False, sort_keys=True))
        translations = self._load_state(checkpoint, signature)
        client = Client(cfg, log=self.log)
        size = max(1, int(cfg['batch_cues']))
        total = len(items)
        if progress is not None:
            progress(len(translations), total)
        analyses = [subtitle.analyze(cue.text) for cue in items]
        groups = subtitle.translation_groups(items, analyses)
        if len(groups) < total:
            self.log(f'ASS animasyon tekrarları: {total} girdi, {len(groups)} çeviri birimi; '
                     'özgün zamanlama ve efektler korunacak.')
        pending = [group for group in groups if not all(i in translations for i in group)]

        def commit_batch(selected):
            if pause is not None:
                pause.checkpoint()
            try:
                visible = self._translate_batch(client, [items[g[0]] for g in selected],
                                                glossary, decisions, prompt, cfg,
                                                visible_only=True)
            except ValueError as error:
                if not retryable_translation_error(error) or len(selected) <= 1:
                    raise
                middle = len(selected) // 2
                self.log(f'Yanıt doğrulanamadı; {len(selected)} girdilik parti '
                         f'{middle}+{len(selected) - middle} olarak bölünüyor: {error}')
                commit_batch(selected[:middle])
                commit_batch(selected[middle:])
                return
            for group, text in zip(selected, visible):
                for index in group:
                    translations[index] = (items[index].text if text is None else
                        subtitle.rebuild(analyses[index], text, note=self._note_reflow))
            if checkpoint:
                save_json(checkpoint, {'signature': signature, 'translations': translations})
            if progress is not None:
                progress(len(translations), total)
            if pause is not None:
                pause.checkpoint()

        for start in range(0, len(pending), size):
            selected = pending[start:start + size]
            self.log(f'Çeviri partisi {start // size + 1}/{(len(pending) + size - 1) // size} '
                     f'({len(selected)} çeviri birimi)')
            commit_batch(selected)
        return self._rebuild(cues, translations)

    def _load_state(self, checkpoint, signature):
        if not checkpoint or not Path(checkpoint).exists():
            return {}
        state = json.loads(read(checkpoint))
        if state.get('signature') != signature:
            raise ValueError('Kontrol noktası bu altyazı/ayarlarla uyuşmuyor; önceki '
                             'çeviriyle devam edilemez (çeviri protokolü de değişmiş olabilir). '
                             'Kontrol noktası dosyasını yedekleyip yeniden adlandırın; baştan başlayın.')
        # JSON sozluk anahtarlarini string'e cevirir; burada tekrar int'e donusturulur
        # ki "bu parti tamamlandi mi" kontrolu (int index) dogru calissin.
        return {int(key): value for key, value in state.get('translations', {}).items()}

    def _rebuild(self, cues, translations):
        result, counter = [], 0
        for cue in cues:
            if not cue.translatable:
                result.append(cue)
                continue
            if counter not in translations:
                raise ValueError('Çeviri eksik kaldı: girdi ' + str(counter + 1) + '.')
            result.append(subtitle.Cue(translations[counter].split('\n'), start=cue.start,
                                       end=cue.end, index=cue.index, extra=cue.extra,
                                       prefix=cue.prefix, ass_fields=cue.ass_fields))
            counter += 1
        return result

    # --- parti cevirisi ---------------------------------------------------
    def _clean(self, text):
        """Modelin dondurdugu metni temizler; bos metin kabul edilmez."""
        value, removed = subtitle.strip_spurious_braces(str(text).strip())
        if removed:
            self.log(f'UYARI: model {removed} adet yapısal olmayan süslü parantez '
                     'üretti; temizlendi.')
        if not value:
            raise ValueError('Çeviri kimlikleri: boş metin döndü.')
        return value

    def _retry(self, cfg, action):
        """Gecici hatalarda `action`i yeniden dener; kalici hatayi dogrudan yukseltir."""
        retries = int(cfg['auto_retry_count'])
        for attempt in range(retries + 1):
            try:
                return action()
            except (ValueError, RuntimeError) as error:
                if not retryable_translation_error(error) or attempt >= retries:
                    raise
                self.log(f'Geçici hata (deneme {attempt + 1}/{retries + 1}): {error}')
        raise RuntimeError('Çeviri isteği tamamlanamadı.')

    def _request_texts(self, client, texts, glossary, decisions, prompt):
        """Gorunur metinleri modele AYRI ID'ler olarak gonderir; cevirileri doner.

        Modelin kopyalamasi gereken ozel bir isaret yoktur; yalnizca ID/TEXT
        bicimini korur. Donen liste `texts` ile ayni uzunluktadir.
        """
        if not texts:
            return []
        user = self._request_text(texts, glossary, decisions)
        if len(texts) == 1:
            user += ('\nSINGLE ENTRY: translate the entire TEXT as one entry. '
                     'Keep its own list numbers and punctuation. Return ID: 1 and TEXT: '
                     'or only the complete translated text. Do not merge or summarize lines.\n')
        text = clean_response(client.generate(prompt, user))
        expected = list(range(1, len(texts) + 1))
        found = subtitle.parse_translation_response(text, expected)
        return [self._clean(found[index]) for index in expected]

    def _fix_texts(self, client, texts, missing, prompt):
        """Eksik glossary terimleri icin duzeltme turu."""
        self.log('Sözlük denetimi: eksik terimler düzeltiliyor: '
                 + ', '.join(item['source'] for item in missing))
        lines = ['MANDATORY GLOSSARY TERMS THAT MUST APPEAR:',
                 glossary_text(missing), '', 'PREVIOUS TRANSLATION TO CORRECT:']
        for offset, text in enumerate(texts, 1):
            lines.append(f'ID: {offset}')
            lines.append('TEXT: ' + text)
        user = '\n'.join(lines)
        text = clean_response(client.generate(GLOSSARY_FIX_PROMPT, user))
        expected = list(range(1, len(texts) + 1))
        found = subtitle.parse_translation_response(text, expected)
        return [self._clean(found[index]) for index in expected]

    def _translate_batch(self, client, batch, glossary, decisions, prompt, cfg,
                         visible_only=False):
        analyses = [subtitle.analyze(cue.text) for cue in batch]
        for analysis in analyses:
            dropped = subtitle.dropped_tags(analysis)
            if dropped:
                self.log(f'UYARI: satır ortasında {dropped} ASS etiketi çıkarıldı '
                         '(karakter bazlı efekt); bunlar çeviriye girmez.')
        texts = [subtitle.send_text(analysis) for analysis in analyses]
        translated = self._retry(cfg, lambda: self._request_texts(
            client, [text for text in texts if text is not None], glossary, decisions, prompt))
        restored = self._assemble(analyses, texts, translated)
        missing = glossary_missing(self._join(batch), self._join(restored), glossary)
        if missing:
            fixed = self._retry(cfg, lambda: self._fix_texts(
                client, translated, missing, prompt))
            translated = fixed
            restored = self._assemble(analyses, texts, fixed)
            still = glossary_missing(self._join(batch), self._join(restored), glossary)
            if still:
                names = ', '.join(item['source'] for item in still)
                self.failed_fixes.append({'missing': [item['source'] for item in still]})
                # "Kati sozluk" (glossary_strict): acikken eksik terim kalici hata;
                # kapaliyken uyari loglanir ve ceviri devam eder (Cevirgec deseni).
                if cfg.get('glossary_strict'):
                    raise ValueError('Sözlük zorunluluğu sağlanamadı: ' + names)
                self.log('UYARI: sözlük zorunluluğu sağlanamadı (katı sözlük '
                         'kapalı); çeviri devam ediyor: ' + names)
        if visible_only:
            values = iter(translated)
            return [next(values) if text is not None else None for text in texts]
        return [cue.text for cue in restored]

    def _assemble(self, analyses, texts, translated):
        """Cevirileri kaynak yapi iskeletiyle geri birlestirir.

        Model satir sayisini bozduysa `subtitle.rebuild` ceviriyi kaynak satir
        sayisina gore yeniden boler (kelime sinirinda) ve yapi korunur; durum
        loglanir.
        """
        iterator = iter(translated)
        restored = []
        for analysis, text in zip(analyses, texts):
            if text is None:
                # Gorunur metin yok (yalnizca tag/efekt); yapi aynen korunur.
                restored.append(subtitle.Cue(subtitle.rebuild(
                    analysis, '\n'.join([''] * len(analysis['lines']))).split('\n')))
            else:
                restored.append(subtitle.Cue(subtitle.rebuild(
                    analysis, next(iterator), note=self._note_reflow).split('\n')))
        return restored

    def _note_reflow(self, expected, found):
        """Model satir sayisini bozdugunda bilgilendirir (yeniden bolme yapildi)."""
        self.log(f'BİLGİ: model satır sayısını değiştirdi (beklenen {expected}, '
                 f'bulunan {found}); çeviri kaynak satır sayısına göre yeniden bölündü.')

    def _request_text(self, texts, glossary, decisions):
        parts = []
        if glossary:
            parts.append('MANDATORY USER GLOSSARY (source -> target):\n' + glossary_text(glossary))
        if decisions:
            parts.append('SERIES CONTINUITY DECISIONS:\n'
                         + '\n'.join('- ' + item for item in decisions))
        parts.append('SOURCE TO TRANSLATE:\n' + subtitle.build_translation_request(texts, 1))
        return '\n\n'.join(parts)

    @staticmethod
    def _join(cues):
        return '\n'.join(cue.text for cue in cues)


def render_output(kind, payload, cues, log=None):
    """Ceviri ciktisini uretir; ASS/SSA'da Turkce desteklemeyen fontu Calibri yapar.

    Kaynak font Turkce karakterleri cizemiyorsa (kurulu degil veya glifleri
    yok) ciktidaki Fontname ve `\\fn` etiketleri `fonts.FALLBACK_FONT` ile
    degistirilir. SRT/VTT font tasimadigi icin dokunulmaz. `log` verilirse
    degistirilen fontlar bildirilir. Donen: (metin, {kaynak: hedef}).
    """
    text = subtitle.render_by_kind(kind, payload, cues)
    if kind not in ('ass', 'ssa'):
        return text, {}
    replacements = fonts.turkish_replacements(subtitle.ass_font_families(text))
    if not replacements:
        return text, {}
    text, changed = subtitle.apply_ass_font_fallback(text, replacements)
    if log and changed:
        pairs = ', '.join(f'{source} -> {target}'
                          for source, target in sorted(replacements.items()))
        log(f'Font uyarısı: kaynak font Türkçe karakterleri desteklemiyor; '
            f'{changed} yerde Calibri kullanıldı ({pairs}).')
    return text, replacements
