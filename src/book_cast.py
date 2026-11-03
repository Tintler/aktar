"""Cok sesli sesli kitap (F239, deneysel): kitaptaki konusmalari karakterlere atar, her karaktere ayri ses.

Atama kitapliktan butun kitap icin bir kez yapilir (duygu etiketleri gibi, F170): okuyucunun cumleleri (sentences.js
bolmesi + paragraf sonlari) parcalar halinde dil modeline gider; konusma cumleleri (emotion_tags.speech_mask) icin
konusanin adi istenir. Model kimin konustugunu her zaman bilemez: bilinmeyen ya da sesi atanmamis konusma anlaticinin
sesiyle okunur. Okuyucudaki metin degismez.

Kayit APP_DIR/karakter-sesleri/<kitap>.json:
    {"version": 1, "created", "sentences", "speech", "assigned",
     "speakers": {cumle metni: ad}, "characters": [{"name", "gender", "lines"}],
     "voices": {ad: ses secimi ('preset:<kimlik>' ya da '<motor>/<ses>')}, "enabled": bool}
Ayni metinli cumle (orn. "Evet.") farkli kisilerce soylenebilir; en sik atanan ad kalir.
Yarim kalan is APP_DIR/karakter-sesleri/yarim/<kitap>.json'dan surer.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

import emotion_tags

STORE_DIR = 'karakter-sesleri'
PARTIAL_DIR = 'yarim'
VERSION = 1
BATCH = 50          # modele bir istekte giden cumle
CONTEXT = 8         # onceki parcadan baglam icin tekrar giden cumle
MAX_CHARACTERS = 60
UNKNOWN = '?'
GENDERS = ('female', 'male', 'unknown')

PROMPT = '''You read part of a book and decide who speaks each line of dialogue.
Lines are numbered. Lines starting with » are spoken words (dialogue); the others are narration.
For every » line numbered from {start} to {stop}, give the name of the person who says it, as the book calls them.
- Use the same name for the same person every time; prefer a name from KNOWN CHARACTERS when it is that person.
- Use the narration around the line ("dedi Ali", "diye sordu annesi") and the turn-taking of the conversation.
- If you cannot tell who speaks, use "?". Never answer for narration lines.
- In "new", list the speakers you named that are not in KNOWN CHARACTERS, with their gender if the text shows it.
Return only JSON: {{"speakers": {{"<line number>": "<name>"}}, "new": [{{"name": "<name>", "gender": "female|male|unknown"}}]}}

KNOWN CHARACTERS: {known}

TEXT:
'''


class Cancelled(RuntimeError):
    """Kullanici atamayi durdurdu."""


def _key(text):
    return ' '.join(str(text).split())


def fold(name):
    return emotion_tags.tr_lower(' '.join(str(name).split())).strip(' .,:;"\'')


def lines_text(sentences, mask, breaks, begin, stop):
    ends = {int(b) for b in breaks or ()}
    lines = []
    for i in range(begin, stop):
        lines.append(f'{i}: {"» " if mask[i] else ""}{sentences[i]}')
        if i in ends:
            lines.append('')
    return '\n'.join(lines).strip()


def parse(raw, start, stop, mask, known):
    """Yanit -> ({cumle numarasi: ad}, yeni karakterler [{name, gender}]). Adlar `known` ({katlanmis: ad}) ile
    birlestirilir; araligin disi, anlatici cumlesi ve '?' atilir."""
    match = re.search(r'\{.*\}', str(raw or ''), re.S)
    if not match:
        return {}, []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}, []
    if not isinstance(data, dict):
        return {}, []
    new = []
    for item in data.get('new') or ():
        if isinstance(item, dict) and _key(item.get('name') or '') and _key(item['name']) != UNKNOWN:
            gender = str(item.get('gender') or 'unknown').lower()
            new.append({'name': _key(item['name'])[:60], 'gender': gender if gender in GENDERS else 'unknown'})
    names = dict(known)
    for item in new:
        names.setdefault(fold(item['name']), item['name'])
    found = {}
    speakers = data.get('speakers')
    for key, value in (speakers.items() if isinstance(speakers, dict) else ()):
        try:
            index = int(str(key).strip())
        except ValueError:
            continue
        name = _key(value or '')[:60]
        if not (start <= index < stop and mask[index]) or not name or name == UNKNOWN:
            continue
        found[index] = names.setdefault(fold(name), name)
    return found, new


def attribute_section(sentences, breaks, ask, characters, cancel=None, progress=None):
    """Bir bolumun konusmalari: [ad ya da ''] (cumle basina). `characters` {katlanmis: {'name','gender'}} bilinen
    kisiler; yeni adlar eklenir. `ask(istem) -> yanit`."""
    sentences = [_key(s) for s in sentences]
    mask = emotion_tags.speech_mask(sentences, breaks)
    result = [''] * len(sentences)
    for start in range(0, len(sentences), BATCH):
        if cancel is not None and cancel.is_set():
            raise Cancelled('Karakter ataması durduruldu.')
        stop = min(len(sentences), start + BATCH)
        if any(mask[start:stop]):
            known = ', '.join(item['name'] for item in list(characters.values())[:MAX_CHARACTERS]) or '(none yet)'
            prompt = PROMPT.format(start=start, stop=stop - 1, known=known) + lines_text(
                sentences, mask, breaks, max(0, start - CONTEXT), stop)
            found, new = parse(ask(prompt), start, stop, mask,
                               {key: item['name'] for key, item in characters.items()})
            for item in new:
                current = characters.setdefault(fold(item['name']), dict(item))
                if current.get('gender', 'unknown') == 'unknown':
                    current['gender'] = item['gender']
            for index, name in found.items():
                result[index] = name
                characters.setdefault(fold(name), {'name': name, 'gender': 'unknown'})
        if progress:
            progress(stop)
    return result


def attribute_book(sections, ask, cancel=None, progress=None, partial=None, checkpoint=None):
    """Butun kitap: ({'sections': [[ad]], 'characters': {katlanmis: {...}}}). `sections` [{'sentences','breaks'}].
    `partial` ara kayit (ayni bicim) verilirse biten bolumler atlanir; `checkpoint(durum)` her bolumden sonra."""
    total = sum(len(section['sentences']) for section in sections)
    partial = partial or {}
    result = [list(names) for names in partial.get('sections') or ()][:len(sections)]
    characters = {key: dict(value) for key, value in (partial.get('characters') or {}).items()}
    done = sum(len(section['sentences']) for section in sections[:len(result)])
    if progress:
        progress(done, total)
    for number in range(len(result), len(sections)):
        section = sections[number]
        step = (lambda count, base=done: progress(base + count, total)) if progress else None
        result.append(attribute_section(section['sentences'], section.get('breaks') or (), ask, characters, cancel,
                                        step))
        done += len(section['sentences'])
        if checkpoint:
            checkpoint({'sections': result, 'characters': characters})
    return {'sections': result, 'characters': characters}


def summarize(sections, attributed):
    """Kayit icin: (konusanlar {cumle: ad}, karakterler [{'name','gender','lines'}], konusma sayisi)."""
    votes, lines = {}, Counter()
    speech = 0
    for section, names in zip(sections, attributed['sections']):
        mask = emotion_tags.speech_mask(section['sentences'], section.get('breaks') or ())
        speech += sum(mask)
        for sentence, name in zip(section['sentences'], names):
            if name:
                votes.setdefault(_key(sentence), Counter())[name] += 1
                lines[name] += 1
    speakers = {text: counter.most_common(1)[0][0] for text, counter in votes.items()}
    genders = {item['name']: item.get('gender', 'unknown') for item in attributed['characters'].values()}
    characters = [{'name': name, 'gender': genders.get(name, 'unknown'), 'lines': count}
                  for name, count in lines.most_common()]
    return speakers, characters, speech


def resume_key(sections):
    digest = hashlib.sha1()
    for section in sections:
        digest.update(json.dumps([section['sentences'], section.get('breaks') or []], ensure_ascii=False).encode('utf-8'))
    return f'{VERSION}:{digest.hexdigest()}'


class Store:
    """APP_DIR/karakter-sesleri/<kitap>.json (bellekte, degistirilme zamaniyla onbellekli)."""

    def __init__(self, app_dir):
        self.directory = Path(app_dir) / STORE_DIR
        self._lock = threading.RLock()
        self._cache = {}

    def _path(self, book):
        if not re.fullmatch(r'[0-9a-f]{8,40}', str(book or '')):
            raise ValueError('Geçersiz kitap kimliği.')
        return self.directory / f'{book}.json'

    def load(self, book):
        path = self._path(book)
        with self._lock:
            try:
                stamp = path.stat().st_mtime_ns
            except OSError:
                self._cache.pop(book, None)
                return None
            cached = self._cache.get(book)
            if cached and cached[0] == stamp:
                return cached[1]
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return None
            if not isinstance(data, dict) or data.get('version') != VERSION:
                return None
            self._cache[book] = (stamp, data)
            return data

    def _write(self, book, data):
        path = self._path(book)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temp, path)
        self._cache.pop(book, None)

    def save(self, book, sections, attributed):
        """Yeni atama; onceki kayittaki ses secimleri ayni adli karakterlerde kalir."""
        speakers, characters, speech = summarize(sections, attributed)
        with self._lock:
            old = self.load(book) or {}
            names = {item['name'] for item in characters}
            data = {'version': VERSION, 'created': datetime.now().isoformat(timespec='seconds'),
                    'sentences': sum(len(section['sentences']) for section in sections), 'speech': speech,
                    'assigned': sum(item['lines'] for item in characters), 'speakers': speakers,
                    'characters': characters,
                    'voices': {name: ref for name, ref in (old.get('voices') or {}).items() if name in names},
                    'enabled': bool(old.get('enabled'))}
            self._write(book, data)
        return self.info(book)

    def update(self, book, voices=None, enabled=None, rename=None):
        """Ses secimleri ({ad: ses ya da ''}), acik/kapali; `rename` {eski: yeni} (ayni adla birlestirir)."""
        with self._lock:
            data = self.load(book)
            if data is None:
                raise ValueError('Bu kitap için karakter ataması yok.')
            data = json.loads(json.dumps(data))
            for old, new in (rename or {}).items():
                new = _key(new)[:60]
                if not new or old == new:
                    continue
                data['speakers'] = {text: (new if name == old else name) for text, name in data['speakers'].items()}
                merged = {}
                for item in data['characters']:
                    name = new if item['name'] == old else item['name']
                    current = merged.setdefault(name, dict(item, name=name, lines=0))
                    current['lines'] += item['lines']
                data['characters'] = sorted(merged.values(), key=lambda item: -item['lines'])
                if old in data['voices'] and new not in data['voices']:
                    data['voices'][new] = data['voices'][old]
                data['voices'].pop(old, None)
            names = {item['name'] for item in data['characters']}
            for name, ref in (voices or {}).items():
                if name not in names:
                    continue
                if ref:
                    data['voices'][name] = str(ref)
                else:
                    data['voices'].pop(name, None)
            if enabled is not None:
                data['enabled'] = bool(enabled)
            self._write(book, data)
        return self.info(book)

    def info(self, book):
        data = self.load(book)
        if data is None:
            return None
        return {key: data.get(key) for key in ('created', 'sentences', 'speech', 'assigned', 'characters', 'voices',
                                                'enabled')}

    def speaker(self, book, text):
        """Cumlenin konusani ('' bilinmiyor)."""
        data = self.load(book)
        return (data or {}).get('speakers', {}).get(_key(text), '')

    def books(self):
        if not self.directory.exists():
            return []
        return sorted(path.stem for path in self.directory.glob('*.json') if re.fullmatch(r'[0-9a-f]{8,40}', path.stem))

    def clear(self, book):
        with self._lock:
            for path in (self._path(book), self._partial_path(book)):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            self._cache.pop(book, None)

    def _partial_path(self, book):
        return self.directory / PARTIAL_DIR / self._path(book).name

    def save_partial(self, book, key, state, total):
        path = self._partial_path(book)
        path.parent.mkdir(parents=True, exist_ok=True)
        done = sum(len(names) for names in state.get('sections') or ())
        value = dict(state, key=key, total=total, done=done, updated=datetime.now().isoformat(timespec='seconds'))
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, path)

    def load_partial(self, book, key=None):
        try:
            value = json.loads(self._partial_path(book).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        if not isinstance(value, dict) or (key is not None and value.get('key') != key):
            return None
        return value

    def clear_partial(self, book):
        try:
            self._partial_path(book).unlink()
        except FileNotFoundError:
            pass

    def partials(self):
        folder = self.directory / PARTIAL_DIR
        result = {}
        for path in folder.glob('*.json') if folder.exists() else ():
            value = self.load_partial(path.stem)
            if value:
                result[path.stem] = {'done': value.get('done', 0), 'total': value.get('total', 0),
                                     'updated': value.get('updated', '')}
        return result
