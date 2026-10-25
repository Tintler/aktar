"""Kitap gorselleri (F197): dil modeli kitabi okuyup sahne plani cikarir, ComfyUI gorselleri uretir; tam ekran
okuyucunun "Gorselli" arka planinda sahnenin cumlesi okunurken gosterilir.

Iki asama (kitapligin sag tik menusunden):
  1. Plan: once kitaptan bir ozet ornegiyle (digest) tek bir stil kilavuzu ve tekrar eden karakterlerin sabit
     tarifleri yazilir (style_prompt); sonra kitap parca parca (chunks) okunur ve her parcada anlamli sahne
     degisimleri secilir (scene_prompt). Kullanicinin kitap notu ("daha soyut ol, yuz gosterme") her iki istemde.
  2. Uretim: her sahnenin istemi ComfyUI is akisina konur (comfy_client.fill): stil PRE-PROMPT'a, sahne Positive'e,
     SUFFIX POST-PROMPT'a. Stil degisince plan yeniden yapilmaz, yalnizca gorseller yeniden uretilir.
Sahne basina kucuk duzeltme (refine_prompt) sahneyi bastan kurmaz: istemi en az degisiklikle yeniden yazar.
Turbo modellerde CFG 1 oldugu icin olumsuz istem calismaz; "kisiyi cikar" istemden silinerek yapilir.

Cumleler okuyucunun bolmesiyle (web/src/lib/sentences.js) gelir; sahne {section, start, anchor} ile baglanir,
anchor (baslangic cumlesinin metni) bolme degisirse yeniden bulmak icin. Kayit: APP_DIR/kitap-gorselleri/<kitap>/
plan.json + <sahne>-<surum>.png. Ses onbellegine dokunulmaz.
"""
from __future__ import annotations

import json
import random
import re
import threading
from datetime import datetime
from pathlib import Path

STORE_DIR = 'kitap-gorselleri'
VERSION = 1
WORKFLOW_FILE = 'is-akisi.json'   # Ayarlar'da secilen is akisinin kopyasi (STORE_DIR altinda)

# Kitap notuna yazilan hazir tarzlar (kullanici duzenleyebilir; dil modeli Turkce notu anlar).
PRESETS = (
    {'id': 'cinematic', 'label': 'Sinematik', 'note': 'Sinematik dijital resim, dramatik ışık, zengin ayrıntı.'},
    {'id': 'watercolor', 'label': 'Suluboya', 'note': 'Dokulu kâğıt üstüne yumuşak suluboya: hafif renk geçişleri, '
                                                         'soluk renkler, serbest fırça darbeleri.'},
    {'id': 'engraving', 'label': 'Gravür', 'note': 'Eski kitap gravürü: ince tarama çizgileri, tek renk mürekkep, '
                                                     'hafif sepya ton.'},
    {'id': 'abstract', 'label': 'Soyut', 'note': 'Sahneyi birebir değil sembolik anlat: biçim, ışık, renk ve havayı '
                                                   'veren nesneler; insan figürü az ya da hiç, yüz gösterme.'},
    {'id': 'minimal', 'label': 'Sade', 'note': 'Sade ve sakin kompozisyonlar: geniş boşluk, tek bir konu, '
                                                 'az renk.'},
)
# sahne basina hedef karakter (Turkce sayfa ~2000): az ~4 sayfa, orta ~1,5 sayfa, cok ~yarim-bir sayfa
DENSITY = {'low': 8000, 'medium': 3000, 'high': 1500}
SIZES = {'1344x768': (1344, 768), '1536x864': (1536, 864), '1920x1088': (1920, 1088)}
DEFAULT_SIZE = '1344x768'
SUFFIX = ('wide cinematic illustration, full-bleed, no text, no letters, no captions, no signs, no watermark, '
          'no logo, no user interface, no frame, no border')
CHUNK_CHARS = 14000    # bir sahne isteginin en fazla metni
DIGEST_CHARS = 24000   # stil kilavuzu icin kitaptan alinan ornek
MIN_SCENE_CHARS = 600  # daha kisa bolum (kunye, ithaf) kendi sahnesini almaz
MAX_TOKENS = 6000


class Cancelled(RuntimeError):
    """Kullanici plani durdurdu."""


def _clean(text):
    return ' '.join(str(text or '').split())


def _json_object(raw):
    """Model yanitindaki ilk JSON nesnesi (dusunme etiketleri ve kod citlari yok sayilir)."""
    text = re.sub(r'<think>.*?</think>', ' ', str(raw or ''), flags=re.S)
    match = re.search(r'\{.*\}', text, re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------- 1. stil kilavuzu
def digest(sections, limit=DIGEST_CHARS):
    """Stil kilavuzu icin kitaptan ornek: her bolumun basindan, uzunluguyla orantili pay (kitap baglama sigmaz)."""
    sizes = [sum(len(s) for s in section['sentences']) for section in sections]
    total = sum(sizes) or 1
    parts = []
    for section, size in zip(sections, sizes):
        share = max(300, limit * size // total)
        taken, text = 0, []
        for sentence in section['sentences']:
            if taken >= share:
                break
            text.append(_clean(sentence))
            taken += len(sentence) + 1
        if text:
            parts.append(' '.join(text) + (' …' if taken < size else ''))
    return '\n\n'.join(parts)[:limit + 2000]


STYLE_SYSTEM = (
    'You are the art director of an illustrated edition of a book. The illustrations are shown full-screen behind '
    'the text while the book is read aloud; all of them must look like ONE consistent illustrated edition. '
    'Answer with JSON only.')
STYLE_TASK = (
    'Write:\n'
    '1. "style": one English style guide, 60-120 words, used as the prefix of EVERY image prompt: medium and '
    'technique, colour palette, lighting, mood, era / technology look of the world. Do not name real artists. '
    'Do not describe a specific scene.\n'
    '2. "characters": the recurring characters (at most 8) with a fixed English visual description each '
    '(15-35 words: age, build, face, hair, clothing) so they look the same in every image. Only permanent features, '
    'never emotions or momentary states (no "crying", "holding a rod"). Leave out characters '
    'that are never described or barely appear.\n'
    '{note}'
    'JSON shape: {{"style": "...", "characters": [{{"name": "...", "look": "..."}}]}}\n\n'
    'Book excerpts (beginning of each chapter):\n\n')


def note_text(note):
    note = _clean(note)
    return (f'The reader asked for this direction; it overrides your own taste: "{note}"\n') if note else ''


def style_prompt(sample, note=''):
    return STYLE_SYSTEM, STYLE_TASK.format(note=note_text(note)) + sample


def parse_style(raw):
    """(stil, karakterler); stil yoksa ValueError."""
    data = _json_object(raw) or {}
    style = _clean(data.get('style'))
    if not style:
        raise ValueError('Dil modeli stil kılavuzu yazmadı.')
    return style, clean_characters(data.get('characters'))


def clean_characters(value, limit=12):
    result, seen = [], set()
    for item in value if isinstance(value, list) else ():
        if not isinstance(item, dict):
            continue
        name, look = _clean(item.get('name'))[:60], _clean(item.get('look'))[:400]
        if name and look and name.lower() not in seen:
            seen.add(name.lower())
            result.append({'name': name, 'look': look})
    return result[:limit]


# ---------------------------------------------------------------- 2. sahneler
def chunks(sections, limit=CHUNK_CHARS):
    """[(bolum, bas, son)]: bolumler, uzunsa cumle sinirinda `limit` karakterlik parcalara bolunur."""
    result = []
    for number, section in enumerate(sections):
        sentences = section['sentences']
        start, size = 0, 0
        for i, sentence in enumerate(sentences):
            if size and size + len(sentence) > limit:
                result.append((number, start, i))
                start, size = i, 0
            size += len(sentence) + 1
        if start < len(sentences):
            result.append((number, start, len(sentences)))
    return result


def scene_count(chars, density='medium'):
    """Parcadaki hedef sahne sayisi (kisa parca 0)."""
    if chars < MIN_SCENE_CHARS:
        return 0
    return max(1, round(chars / DENSITY.get(density, DENSITY['medium'])))


SCENE_SYSTEM = STYLE_SYSTEM
SCENE_TASK = (
    'Style guide of the edition (it is added to every prompt automatically, do not repeat it):\n{style}\n\n'
    'Recurring characters (when one appears, copy its look into the prompt word for word):\n{characters}\n\n'
    '{note}'
    '{previous}'
    'Below is the next part of the book as numbered sentences. Split it at meaningful scene, location or mood '
    'changes into about {count} scenes (between {low} and {high}). For each scene give:\n'
    '- "start": number of the first sentence the image belongs to (the first scene starts at {first})\n'
    '- "title": short title in the language of the book\n'
    '- "prompt": English image prompt, 40-90 words, describing only what is visible: setting, subjects, action, '
    'framing. Start directly with the scene; never restate the medium, art style or palette (the style guide is '
    'already added). Describe characters by their look (the image model does not know names). Every character appears at '
    'most once in the image; say how many people are visible. Describe what IS '
    'there; never write "no ...", never ask for text, letters, signs or screens with writing. For non-fiction or '
    'reflective passages prefer places, objects, period details or symbolic imagery.\n'
    '- "characters": optional, new recurring characters introduced here with a fixed look '
    '[{{"name": "...", "look": "..."}}]\n'
    'JSON shape: {{"scenes": [{{"start": {first}, "title": "...", "prompt": "...", "characters": []}}]}}\n\n')


def character_lines(characters):
    return '\n'.join(f'- {c["name"]}: {c["look"]}' for c in characters) or '- (none yet)'


def scene_prompt(style, characters, sentences, start, stop, count, note='', previous=None):
    lines = '\n'.join(f'{i}: {_clean(sentences[i])}' for i in range(start, stop))
    before = (f'The previous image showed: {previous}\n\n') if previous else ''
    task = SCENE_TASK.format(style=style, characters=character_lines(characters), note=note_text(note),
                             previous=before, count=count, low=max(1, count - 1), high=count + 1, first=start)
    return SCENE_SYSTEM, task + lines


def strip_style(prompt, style):
    """Model talimata ragmen istemin basina stil kilavuzunu yazdiysa (gorsel modeline iki kez gider) o cumleler
    atilir: stilin ilk 5 kelimesiyle baslayan cumleler istemin basindan silinir."""
    head = ' '.join(re.findall(r'[\w-]+', str(style or '').lower())[:5])
    if not head:
        return prompt
    sentences = re.split(r'(?<=[.!?])\s+', prompt)
    while len(sentences) > 1 and ' '.join(re.findall(r'[\w-]+', sentences[0].lower())[:5]) == head:
        sentences.pop(0)
    return ' '.join(sentences)


def parse_scenes(raw, start, stop, sentences, style=''):
    """[{start, title, prompt}] ve yeni karakterler: aralik disi, tekrarlanan ya da istemsiz sahne atilir; ilk sahne
    parcanin basina cekilir (parcanin basi baska bir sahnenin devami olmasin). Basa yazilan stil cumlesi atilir."""
    data = _json_object(raw) or {}
    found, characters = {}, []
    for item in data.get('scenes') if isinstance(data.get('scenes'), list) else ():
        if not isinstance(item, dict):
            continue
        try:
            index = int(str(item.get('start')).strip())
        except (TypeError, ValueError):
            continue
        prompt = strip_style(_clean(item.get('prompt')), style)
        if not (start <= index < stop) or not prompt or index in found:
            continue
        found[index] = {'start': index, 'title': _clean(item.get('title'))[:80] or _clean(sentences[index])[:40],
                        'prompt': prompt[:1200]}
        characters += clean_characters(item.get('characters'))
    scenes = [found[key] for key in sorted(found)]
    if scenes and scenes[0]['start'] != start:
        scenes[0]['start'] = start
    return scenes, characters


def merge_characters(characters, extra, limit=12):
    names = {c['name'].lower() for c in characters}
    return (characters + [c for c in extra if c['name'].lower() not in names])[:limit]


def new_plan(note='', preset='', density='medium', size=DEFAULT_SIZE, title=''):
    return {'version': VERSION, 'created': datetime.now().isoformat(timespec='seconds'), 'title': title,
            'note': _clean(note), 'preset': preset, 'density': density if density in DENSITY else 'medium',
            'size': size if size in SIZES else DEFAULT_SIZE, 'seed': random.randrange(1, 2 ** 31),
            'style': '', 'characters': [], 'scenes': [], 'complete': False, 'next_chunk': 0}


def plan_book(sections, ask, plan, cancel=None, progress=None, save=None):
    """Plani doldurur (kaldigi parcadan devam eder). `ask(system, user) -> yanit`; `progress(islenen, toplam)` cumle
    sayisiyla; `save(plan)` her parcadan sonra (durdurulup yeniden baslatilinca devam icin). Donen: plan."""
    parts = chunks(sections)
    total = sum(len(section['sentences']) for section in sections)
    done = sum(stop - start for _section, start, stop in parts[:plan.get('next_chunk', 0)])
    if progress:
        progress(done, total)
    if not plan.get('style'):
        plan['style'], plan['characters'] = parse_style(ask(*style_prompt(digest(sections), plan.get('note'))))
        if save:
            save(plan)
    for number in range(plan.get('next_chunk', 0), len(parts)):
        if cancel is not None and cancel.is_set():
            raise Cancelled('Görsel planı durduruldu.')
        section, start, stop = parts[number]
        sentences = sections[section]['sentences']
        count = scene_count(sum(len(s) + 1 for s in sentences[start:stop]), plan.get('density'))
        if count:
            previous = plan['scenes'][-1]['prompt'] if plan['scenes'] else None
            scenes, extra = parse_scenes(ask(*scene_prompt(plan['style'], plan['characters'], sentences, start, stop,
                                                            count, plan.get('note'), previous)), start, stop, sentences,
                                         plan['style'])
            plan['characters'] = merge_characters(plan['characters'], extra)
            for scene in scenes:
                order = len(plan['scenes'])
                plan['scenes'].append({'id': f'{section}-{scene["start"]}', 'section': section, 'start': scene['start'],
                                       'anchor': _clean(sentences[scene['start']]), 'title': scene['title'],
                                       'prompt': scene['prompt'], 'seed': plan['seed'] + order, 'image': '',
                                       'skip': False})
        plan['next_chunk'] = number + 1
        done += stop - start
        if save:
            save(plan)
        if progress:
            progress(done, total)
    plan['complete'] = True
    return plan


# ---------------------------------------------------------------- sahne basina kucuk duzeltme
REFINE_SYSTEM = ('You edit image prompts. Apply the requested change with the smallest possible edit and keep '
                 'everything else word for word. Answer with the new prompt only, no explanation.')
REFINE_TASK = (
    'Prompt:\n{prompt}\n\nRequested change (may be in Turkish): {instruction}\n\n'
    'Rules: to remove something, delete it from the description instead of writing "no ..." (negative words do '
    'not work with this model). Keep it English, 40-100 words. Do not mention text or letters.')


def refine_prompt(prompt, instruction):
    return REFINE_SYSTEM, REFINE_TASK.format(prompt=_clean(prompt), instruction=_clean(instruction))


def parse_refined(raw, fallback):
    text = re.sub(r'<think>.*?</think>', ' ', str(raw or ''), flags=re.S).strip().strip('`').strip()
    text = re.sub(r'^(?:new\s+)?prompt\s*:\s*', '', text, flags=re.I).strip().strip('"').strip()
    return _clean(text)[:1200] or fallback


# ---------------------------------------------------------------- kayit
class Store:
    """APP_DIR/kitap-gorselleri/<kitap>/plan.json + gorseller (bellekte onbellekli)."""

    def __init__(self, app_dir):
        self.directory = Path(app_dir) / STORE_DIR
        self._lock = threading.RLock()
        self._cache = {}

    def folder(self, book):
        if not re.fullmatch(r'[0-9a-f]{8,40}', str(book or '')):
            raise ValueError('Geçersiz kitap kimliği.')
        return self.directory / book

    def load(self, book):
        with self._lock:
            if book not in self._cache:
                try:
                    data = json.loads((self.folder(book) / 'plan.json').read_text(encoding='utf-8'))
                    if data.get('version') != VERSION or not isinstance(data.get('scenes'), list):
                        raise ValueError
                except (OSError, ValueError, AttributeError):
                    data = None
                self._cache[book] = data
            return self._cache[book]

    def save(self, book, plan):
        with self._lock:
            folder = self.folder(book)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / 'plan.json'
            partial = target.with_name('plan.json.part')
            partial.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding='utf-8')
            partial.replace(target)
            self._cache[book] = plan
        return plan

    def update(self, book, change):
        """plan.json'u kilit altinda degistirir: `change(plan)`; plan yoksa ValueError."""
        with self._lock:
            plan = self.load(book)
            if not plan:
                raise ValueError('Bu kitabın görsel planı yok.')
            plan = json.loads(json.dumps(plan))
            change(plan)
            return self.save(book, plan)

    def scene(self, plan, scene_id):
        found = next((scene for scene in plan['scenes'] if scene['id'] == scene_id), None)
        if found is None:
            raise ValueError('Sahne bulunamadı.')
        return found

    def image_path(self, book, scene):
        return self.folder(book) / scene['image'] if scene.get('image') else None

    def write_image(self, book, scene_id, data):
        """Yeni gorseli <sahne>-<surum>.png olarak yazar (surum: tarayici onbellegi eskisini gostermesin), eskisini
        siler. Donen: guncel plan."""
        folder = self.folder(book)
        folder.mkdir(parents=True, exist_ok=True)
        holder = {}

        def change(plan):
            scene = self.scene(plan, scene_id)
            version = int(scene.get('version', 0)) + 1
            name = f'{re.sub(r"[^0-9a-z-]", "", scene_id)}-{version}.png'
            partial = folder / (name + '.part')
            partial.write_bytes(data)
            partial.replace(folder / name)
            holder['old'] = scene.get('image')
            scene.update(image=name, version=version)

        plan = self.update(book, change)
        old = holder.get('old')
        if old and old != next(s for s in plan['scenes'] if s['id'] == scene_id)['image']:
            (folder / old).unlink(missing_ok=True)
        return plan

    def books(self):
        """Plani olan kitaplar."""
        if not self.directory.is_dir():
            return []
        return sorted(path.name for path in self.directory.iterdir() if path.is_dir() and self.load(path.name))

    def clear(self, book):
        with self._lock:
            self._cache.pop(book, None)
            folder = self.folder(book)
            for path in folder.glob('*') if folder.is_dir() else ():
                path.unlink(missing_ok=True)
            try:
                folder.rmdir()
            except OSError:
                pass


def summary(plan):
    """Kitaplik ve okuyucu icin kisa durum."""
    if not plan:
        return None
    scenes = [scene for scene in plan['scenes'] if not scene.get('skip')]
    return {'complete': bool(plan.get('complete')), 'scenes': len(scenes),
            'images': sum(1 for scene in scenes if scene.get('image')), 'created': plan.get('created')}


def pending(plan):
    """Uretilecek sahneler (okuma sirasiyla)."""
    return [scene for scene in sorted(plan['scenes'], key=lambda s: (s['section'], s['start']))
            if not scene.get('skip') and not scene.get('image')]


def section_images(plan, section):
    """Okuyucu: bolumun sahneleri [{start, anchor, image}] ve bolumden onceki son gorsel (bolum basindan ilk sahneye
    kadar o kalir)."""
    shown = [scene for scene in plan['scenes'] if scene.get('image') and not scene.get('skip')]
    here = sorted((scene for scene in shown if scene['section'] == section), key=lambda s: s['start'])
    before = [scene for scene in shown if scene['section'] < section]
    carry = max(before, key=lambda s: (s['section'], s['start'])) if before else None
    return here, carry
