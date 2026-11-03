"""Okuyucuda "Simdiye kadar ne oldu?" ve "Kim kimdir?" (F239): okunan yere kadarki kisimdan, surpriz bozmadan.

Her bolum bir kez dil modeliyle ozetlenir (kisa ozet + gecen kisiler) ve onbellege yazilir:
APP_DIR/kitap-ozetleri/<kitap>.json. Okuma ilerledikce yalnizca yeni bolumler ozetlenir; acik bolumun okunan
kismi (fraction) her seferinde ayrica ozetlenir (onbellekte okunan karakter sayisiyla). Son adimda bolum
ozetlerinden tek bir "simdiye kadar" metni ve kisi listesi yazilir. Modele okunan yerden sonrasi hic gitmez.

Bolum numaralari okuyucununkiyle aynidir (book.sections sirasi, 0'dan); metinde s.N = N. bolum (1'den).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import qa
from app_core import APP_DIR, digest, read, save_json, retryable_translation_error

VERSION = 1
MIN_CHARS = 200          # bundan kisa bolum (kunye, bos sayfa) ozetlenmez
CHUNK_CHARS = 16000      # uzun bolum parcalara bolunur
DIGEST_CHARS = 14000     # son adimda modele giden bolum ozetleri; asarsa once gruplar ozetlenir
MAX_PEOPLE = 40

SECTION_TASK = '''You summarize one part of a book for a reader who has just read it.
Return only JSON: {"story": true|false, "summary": "...", "people": [{"name": "...", "note": "..."}]}
- Write "summary" and every "note" in Turkish.
- "story": false for front or back matter (copyright page, dedication, acknowledgements, table of contents,
  author biography, index); then leave summary empty and people [].
- "summary": 2-6 sentences: the key events, decisions, revelations or arguments of this part, in order.
- "people": the named people (characters, or for non-fiction the historical figures) who matter in this part,
  at most 12; "note" is one short sentence on who they are and what they do here.
- Use only this text. Do not guess what happens next.'''

RECAP_TASK = '''You write "the story so far" for a reader of a book. The reader has read up to the point where the
notes below end. Write in Turkish, 2-5 short paragraphs, plain prose (no headings, no lists).
- Cover the whole read part, giving more detail to the most recent parts.
- After the sentence it supports, cite the part as (s.N), for example (s.3).
- Use only the notes. Never mention or hint at anything beyond them.'''

PEOPLE_TASK = '''From the notes about the parts of a book the reader has read so far, build a "who is who" list.
Return only JSON: {"people": [{"name": "...", "about": "...", "first": N}]}
- Write "about" in Turkish: 1-2 sentences on who the person is and their role or situation as of the last notes.
- "first": the part number (s.N) where the person first appears.
- Merge spellings of the same person. Most important people first; at most 25.
- Use only the notes. Never mention anything beyond them.'''

GROUP_TASK = '''Condense these consecutive part summaries of a book into one Turkish summary of 4-8 sentences.
Keep the order of events and keep a (s.N) citation after the sentence it supports. Use only the text given.'''


class Store:
    """APP_DIR/kitap-ozetleri/<kitap>.json: {'version', 'sections': {n: {...}}, 'recap': {...}}"""

    def __init__(self, book_id, base=None):
        self.path = Path(base or APP_DIR) / 'kitap-ozetleri' / f'{book_id}.json'
        self.lock = threading.Lock()

    def load(self):
        try:
            value = json.loads(read(self.path))
        except (OSError, ValueError):
            return {'version': VERSION, 'sections': {}, 'recap': None}
        if not isinstance(value, dict) or value.get('version') != VERSION:
            return {'version': VERSION, 'sections': {}, 'recap': None}
        value.setdefault('sections', {})
        value.setdefault('recap', None)
        return value

    def save(self, value):
        with self.lock:
            save_json(self.path, value)


def cut(text, fraction):
    """Bolumun okunan kismi: ilk `fraction` kadari (karakterce), kelime sinirinda."""
    fraction = min(1.0, max(0.0, float(fraction)))
    if fraction >= 1.0:
        return text
    limit = int(len(text) * fraction)
    head = text[:limit]
    space = head.rfind(' ')
    return head[:space] if space > limit * 0.8 else head


def chunks(text, size=CHUNK_CHARS):
    """Uzun metni paragraf sinirinda ~size parcalara boler."""
    parts, current = [], ''
    for paragraph in text.split('\n'):
        if current and len(current) + len(paragraph) > size:
            parts.append(current)
            current = ''
        while len(paragraph) > size:   # paragrafsiz dev metin
            parts.append(paragraph[:size])
            paragraph = paragraph[size:]
        current = (current + '\n' + paragraph) if current else paragraph
    if current.strip():
        parts.append(current)
    return parts


def _clean_people(items, key='note', limit=MAX_PEOPLE):
    people, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = ' '.join(str(item.get('name') or '').split())[:80]
        text = ' '.join(str(item.get(key) or '').split())[:400]
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        entry = {'name': name, key: text}
        if key == 'about':
            try:
                entry['first'] = max(1, int(item.get('first')))
            except (TypeError, ValueError):
                pass
        people.append(entry)
    return people[:limit]


def _ask(client, system, user, retries=2, log=print):
    for attempt in range(retries + 1):
        try:
            return client.chat([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}])
        except (ValueError, RuntimeError) as error:
            if not retryable_translation_error(error) or attempt >= retries:
                raise
            log(f'Geçici hata (deneme {attempt + 1}/{retries + 1}): {error}')
            time.sleep(1)
    raise RuntimeError('Model isteği tamamlanamadı.')


def _ask_json(client, system, user, log=print):
    retries = 2
    for attempt in range(retries + 1):
        text = _ask(client, system, user, log=log)
        try:
            return qa.parse_json_object(text)
        except ValueError:
            if attempt >= retries:
                raise
            log('Model geçerli JSON döndürmedi; yeniden isteniyor.')
    return {}


def summarize_section(client, title, text, log=print):
    """Bir bolumun (ya da okunan kisminin) notu: {'story', 'summary', 'people'}."""
    summaries, people, story = [], [], False
    parts = chunks(text)
    for index, part in enumerate(parts):
        head = f'PART TITLE: {title}\n' if title else ''
        if len(parts) > 1:
            head += f'(piece {index + 1} of {len(parts)} of this part)\n'
        value = _ask_json(client, SECTION_TASK, head + 'TEXT:\n' + part, log)
        if value.get('story') is False and not str(value.get('summary') or '').strip():
            continue
        story = True
        summaries.append(' '.join(str(value.get('summary') or '').split()))
        people += _clean_people(value.get('people'))
    merged = {}
    for person in people:   # ayni kisi parcalarda tekrar edebilir: son not kalir
        merged[person['name'].casefold()] = person
    return {'story': story, 'summary': ' '.join(item for item in summaries if item), 'people': list(merged.values())}


def section_key(text, model):
    return digest(f'{VERSION}|{model}|{text}')


def notes_text(notes):
    """Bolum notlari -> modele giden metin."""
    lines = []
    for item in notes:
        title = f' ({item["title"]})' if item.get('title') else ''
        partial = ' [read partly]' if item.get('partial') else ''
        lines.append(f's.{item["section"] + 1}{title}{partial}: {item["summary"]}')
        for person in item.get('people') or []:
            lines.append(f'  - {person["name"]}: {person["note"]}')
    return '\n'.join(lines)


def condense(client, notes, limit=DIGEST_CHARS, log=print, rounds=3):
    """Notlar cok uzunsa eski ardisik gruplar birer ozete indirilir; en son grup ayrintili kalir. Kisiler burada
    yoktur (kisi listesi ayri yazilir)."""
    lines = [f's.{item["section"] + 1}: {item["summary"]}' for item in notes]
    for _round in range(rounds):
        if len('\n'.join(lines)) <= limit:
            break
        groups, current, size = [], [], 0
        for line in lines:
            if current and size + len(line) > limit // 3:
                groups.append(current)
                current, size = [], 0
            current.append(line)
            size += len(line) + 1
        groups.append(current)
        if len(groups) < 2:
            break
        lines = [' '.join(qa.strip_thinking(_ask(client, GROUP_TASK, '\n'.join(group), log=log)).split())
                 for group in groups[:-1]] + groups[-1]
    text = '\n'.join(lines)
    return text if len(text) <= limit else text[-limit:].split('\n', 1)[-1]


def people_text(notes, limit=DIGEST_CHARS):
    """Kisi notlari (sonrakiler once kesilmesin diye en yeniden geriye, sonra sirali)."""
    lines, used = [], 0
    for item in reversed(notes):
        block = [f'  s.{item["section"] + 1} - {person["name"]}: {person["note"]}' for person in item.get('people') or []]
        cost = sum(len(line) + 1 for line in block)
        if used + cost > limit:
            break
        lines[:0] = block
        used += cost
    return '\n'.join(lines)


def build(book, until, fraction, client, model, store, log=print, progress=None, cancelled=None):
    """Okunan yere kadar ozet + kisi listesi. `book`: book_reader.EpubBook; `until` acik bolum (0'dan);
    `fraction`: acik bolumun okunan orani. Donen kayit {'until','fraction','text','people','at','model'}."""
    import book_search
    data = store.load()
    titles = {}
    for item in book.toc:
        titles.setdefault(item['section'], ' '.join(str(item['title']).split()))
    texts = []
    for number, text in enumerate(book_search.section_texts(book)):
        if number > until:
            break
        texts.append(text)
    work = []
    for number, text in enumerate(texts):
        partial = number == until and fraction < 0.999
        if partial:
            text = cut(text, fraction)
        if len(' '.join(text.split())) >= MIN_CHARS:
            work.append((number, text, partial))
    if not work:
        raise ValueError('Okunan kısımda özetlenecek metin yok.')
    notes = []
    for done, (number, text, partial) in enumerate(work):
        if cancelled and cancelled():
            from app_core import GracefulStop
            raise GracefulStop('Özet durduruldu; bitmiş bölümler kaydedildi.')
        if progress:
            progress(done, len(work))
        key = section_key(text, model)
        cached = data['sections'].get(str(number))
        if not cached or cached.get('key') != key:
            log(f'Bölüm özetleniyor: s.{number + 1}' + (' (okunan kısım)' if partial else ''))
            note = summarize_section(client, titles.get(number, ''), text, log)
            cached = dict(note, key=key, partial=partial)
            if not partial:   # yarim bolumun notu kalici degil (okuma ilerleyince degisir)
                data['sections'][str(number)] = cached
                store.save(data)
        if cached.get('story') and cached.get('summary'):
            notes.append({'section': number, 'title': titles.get(number, ''), 'partial': partial,
                          'summary': cached['summary'], 'people': cached.get('people') or []})
    if progress:
        progress(len(work), len(work))
    if not notes:
        raise ValueError('Okunan kısımda hikâye metni bulunamadı (yalnızca künye, önsöz vb.).')
    log('Özet yazılıyor…')
    story = condense(client, notes, log=log)
    text = qa.strip_thinking(_ask(client, RECAP_TASK, 'NOTES (in reading order):\n' + story, log=log)).strip()
    people = []
    if any(item.get('people') for item in notes):
        value = _ask_json(client, PEOPLE_TASK, 'NOTES ABOUT PEOPLE (s.N = part):\n' + people_text(notes), log)
        people = _clean_people(value.get('people'), 'about', 25)
    recap = {'until': until, 'fraction': round(float(fraction), 3), 'text': text, 'people': people,
             'model': model, 'at': int(time.time())}
    data['recap'] = recap
    store.save(data)
    return recap
