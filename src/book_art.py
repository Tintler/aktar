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

Karakter kimligi (F201, kitap basina acilir, plan['identity']): kapaliyken yukaridaki akis hic degismez. Acikken
her karakterin duz fonlu bir portresi (portrait_prompt, stilin yalnizca ilk cumlesiyle: tam stil ortami portreye,
portre de sahnelere tasiyordu) ana is akisiyla uretilir ya da kullanici kendi gorselini koyar; karakterli sahne kimlik
is akisiyla (comfy_client.references) portre referans verilerek uretilir (identity_prompt). Sahnedeki karakterler
scene['cast'] (plan kimlik aciyken cikarildiysa dil modeli yazar, kullanici degistirebilir), yoksa cast_of karakterin
adini ya da gorunusunu istemde arar. Kayit: <kitap>/portre-<ad>-<surum>.png.

LoRA'li hazir tarzlar ve secenekler (F202): tarzin LoRA'si plana kopyalanir (plan['lora']: dosya, guc, tetik kelimesi,
son ek); uretimde iki is akisina da eklenir (comfy_client.add_loras), tetik kelimesi istemin en basina. Secenekler
(plan['modifiers']: karakter olmasin, yalnizca manzara, yuz gosterme) tarzdan bagimsizdir: dil modeline kesin kural,
gorsel istemine olumlu son ek olarak gider.

F209 secenekleri (hepsi kapaliyken istemler ve akis eskisi gibi):
  - Siklik: 'rare' / 'sparse' parcadan seyrek; dil modeli onem puanli adaylar verir, plan sonunda kitabin tamamindan
    en onemlileri secilir (select_moments). 'low' ve seyreklerde parca bolunmez, onemli anlar secilir (focused).
  - Bolum acilis gorseli (plan['openers']): siklik ne olursa olsun her bolumun ilk cumlesinde; ayri istekle ve
    yalnizca bolumun ilk sayfasindan yazilir (spoiler olmaz), hikaye disi sayfayi (kunye, ithaf) model atlar.
  - Mekan kimligi (plan['place_identity'], plan['places']): sahnenin mekaninin adi; kalici tarifi uretimde eklenir.
  - Gorunus degisimi (plan['look_changes']): karakterin 'changes' listesi; sahneler o yerdeki gorunusle.
  - RTX buyutme (plan['upscale'] katsayi): uretilen gorsel ComfyUI'de RTX Video Super Resolution ile buyutulur.
  - Toplu stil degisikligi (restyle): istemler kalir, stil kilavuzu ve LoRA degisir, gorseller yeniden uretilir.
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
IDENTITY_FILE = 'kimlik-is-akisi.json'   # karakter kimligi is akisi (F201)

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
) + (
    # LoRA'li tarzlar (F202, Krea 2; dosyalar ComfyUI'nin models/loras klasorunde). 'trigger' gorsel isteminin en basina
    # (stil kilavuzundan once), 'suffix' sona eklenir; tetik kelimeleri ve guc LoRA sayfalarindaki ornek istemlerden.
    # Notu dil modeli okur: stil kilavuzu LoRA'nin gorunusuyle catismasin.
    {'id': 'fever-dream', 'label': 'Fever Dream', 'lora': 'FeverDreamKrea2_c1-st4000.safetensors', 'strength': 1.0,
     'trigger': '', 'url': 'https://civitai.com/models/2675439',
     'note': 'Rüya gibi, hafif tekinsiz analog fotoğraf havası: parlak renk lekeleri, ışıltılı dokular, sinematik '
             'ışık, gerçeküstü ama gerçekçi ayrıntılar.'},
    {'id': 'yfg-fwshn', 'label': 'Pastel neon sis', 'lora': 'YFG-Fwshn-Krea2_1.8k-v2.safetensors', 'strength': 0.9,
     'trigger': 'YFG-Fwshn', 'suffix': 'dreamy, hazy, neon pastel, foggy, surreal, soft glow',
     'url': 'https://civitai.com/models/1123717',
     'note': 'Sisli, rüya gibi gerçeküstü dijital resim: soluk pastel neon pembe, kırmızı, turuncu ve sarı; '
             'yumuşak ışıma, belirsiz kenarlar, yer yer mimari yapılar.'},
    {'id': 'grimm', 'label': 'Grimm yağlıboya', 'lora': 'Grimm_s_realistic_painting_alternative_krea2_epoch_12.safetensors',
     'strength': 0.9, 'trigger': 'grimmspaintalt,', 'url': 'https://civitai.com/models/1980971',
     'note': 'Gerçekçi, izlenimci yağlıboya: belirgin fırça darbeleri, zengin doku, ışıltılı renk geçişleri, '
             'klasik resim zarafeti.'},
    {'id': 'dark-fantasy', 'label': 'Karanlık fantastik', 'lora': 'DarkFanKrea2_c1-st3000.safetensors', 'strength': 1.0,
     'trigger': 'Dark Fantasy Art Style,', 'suffix': 'eerie atmosphere, grainy, painterly texture',
     'url': 'https://civitai.com/models/1223108',
     'note': 'Karanlık fantastik resim: soluk renkler, gotik ve kasvetli hava, chiaroscuro ışık, grenli boyalı doku.'},
    {'id': 'krea-sketching', 'label': 'Eskiz', 'lora': 'KreaSketching_V2c.safetensors', 'strength': 1.0,
     'trigger': 'Bradhamel art style.', 'url': 'https://civitai.com/models/2817577',
     'note': 'Ayrıntılı kalem eskizi: ince tarama ve çapraz tarama gölgeleri, sade dokulu kâğıt, yer yer hafif renk.'},
    {'id': 'chaotic-shapes', 'label': 'Kaotik şekiller', 'lora': 'Chaotic_Shapes_krea2_3390106_epoch_10.safetensors',
     'strength': 1.0, 'trigger': 'Abstract composition. Cubism art style, ChaLOSTIC, The illustration has a stylized, '
                                 'geometric, and somewhat abstract art style, abstract,',
     'url': 'https://civitai.com/models/2990211',
     'note': 'Kübist, geometrik soyut çizim: keskin açılı biçimler, kıvrımlar, cesur ve zıt renkler; sahneyi '
             'biçimlerle ima et.'},
    {'id': 'dc-dark-fantasy', 'label': 'Fantastik illüstrasyon',
     'lora': 'DC_Dark_Fantasy_Style_7_[Krea2Raw][Gpt4.1Captioned][Trigger=dcd@rkf@ntsy.][Rank32]_v1.safetensors',
     'strength': 1.0, 'trigger': 'dcd@rkf@ntsy.', 'url': 'https://civitai.com/models/3012486',
     'note': 'Ayrıntılı karanlık fantastik illüstrasyon: işlemeli zırhlar, yaratıklar, sisli ve ışıltılı atmosferik '
             'mekânlar, dramatik ışık.'},
    {'id': 'dc-colossal-future', 'label': 'Devasa gelecek',
     'lora': 'DC_Colossal_Future_[Krea2Raw][Gpt4.1Captioned][Trigger=DCC0LFUT.][Rank32]_v1.safetensors',
     'strength': 1.0, 'trigger': 'DCC0LFUT.', 'url': 'https://civitai.com/models/3019065',
     'note': 'Bilimkurgu: devasa uzay gemileri, göğe uzanan megayapılar, ayrıntılı mekanik mimari, atmosferik '
             'derinlik ve olağanüstü ölçek; geniş ve alçak açılı çekimler.'},
)
LORA_KEYS = ('lora', 'strength', 'trigger', 'suffix', 'label')

# Hazir tarzdan bagimsiz secenekler (F202, birlikte secilebilir): 'rule' her iki dil modeli istemine kesin kural
# olarak girer, 'suffix' gorsel isteminin sonuna (turbo modelde olumsuz istem yok: olumlu ifade).
MODIFIERS = (
    {'id': 'no-people', 'label': 'Karakter olmasın',
     'rule': 'No people or creatures are visible in any image: show the places, objects, traces and atmosphere of the '
             'scene instead. Leave "characters" empty.',
     'suffix': 'uninhabited, deserted scene'},
    {'id': 'landscape', 'label': 'Yalnızca manzara',
     'rule': 'Every image is a wide landscape or environment shot: the setting fills the frame; people, if any, are '
             'tiny distant figures.',
     'suffix': 'wide establishing shot, expansive landscape'},
    {'id': 'no-faces', 'label': 'Yüz gösterme',
     'rule': 'Faces are never shown: people are seen from behind, in silhouette, from far away or cropped.',
     'suffix': 'figures seen from behind or in silhouette'},
)
NO_CAST = ('no-people', 'landscape')   # bu seceneklerle karakter kimligi anlamsiz
# sahne basina hedef karakter (Turkce sayfa ~2000): cok seyrek ~25 sayfa, seyrek ~10, az ~4, orta ~1,5, cok ~yarim-bir
# sayfa. Az ve daha seyrekte dil modeli sahne degisimlerini degil onemli anlari secer (focused); bir parcadan seyrek
# olanlarda (selective, F209) her parcadan onem puanli adaylar istenir, plan bitince kitabin tamamindan en onemlileri.
DENSITY = {'sparse': 50000, 'rare': 20000, 'low': 8000, 'medium': 3000, 'high': 1500}
CANDIDATES = 3       # selective: gereken sahnenin kac kati aday istenir
MAX_CANDIDATES = 4   # selective: parca basina en fazla aday
SPACING = 0.4        # selective: secilen iki an arasi en az bu kadar sahne araligi (yer kalmazsa gevsetilir)
SIZES = {'1344x768': (1344, 768), '1536x864': (1536, 864), '1920x1088': (1920, 1088)}
DEFAULT_SIZE = '1344x768'
SUFFIX = ('wide cinematic illustration, full-bleed, no text, no letters, no captions, no signs, no watermark, '
          'no logo, no user interface, no frame, no border')
CHUNK_CHARS = 14000    # bir sahne isteginin en fazla metni
DIGEST_CHARS = 24000   # stil kilavuzu icin kitaptan alinan ornek
MIN_SCENE_CHARS = 600  # daha kisa bolum (kunye, ithaf) kendi sahnesini almaz
MAX_TOKENS = 6000
UPSCALES = (1.5, 2.0, 3.0, 4.0)   # RTX buyutme katsayilari (F209; 0 kapali)
PORTRAIT_SIZE = (1024, 1024)
PORTRAIT_SUFFIX = 'no text, no letters, no watermark, no logo, no frame, no border'
MAX_CAST = 2   # kimlik is akisinin en fazla referansi (REFERENCE, REFERENCE-B)


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


# Yas ve cinsiyet (F211): "small, slight build" gibi yassiz tarif gorsel modelinde cocuk (iri kafali) ciziliyordu
AGE_RULE = ('Every look starts with the explicit age and sex, e.g. "Man in his fifties", "Woman of about thirty", '
            '"Boy of about ten"; a short, small or slight adult is still a man or woman. An animal, robot, creature or '
            'spirit starts with what it is (e.g. "Old red fox") and gets "kind": "other".')
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
    '(15-35 words: age, build, face, hair, clothing) so they look the same in every image. ' + AGE_RULE + ' '
    'Only permanent features, never emotions or momentary states (no "crying", "holding a rod"). Leave out characters '
    'that are never described or barely appear.\n'
    '{places}'
    '{note}'
    'JSON shape: {{"style": "...", "characters": [{{"name": "...", "look": "..."}}]{places_shape}}}\n\n'
    'Book excerpts (beginning of each chapter):\n\n')
# mekan kimligi (F209): tekrar eden mekanlarin sabit tarifi; gorsel istemine uretimde eklenir (scene_text)
PLACES_TASK = (
    '3. "places": the recurring locations (at most 8) with a fixed English visual description each (20-40 words: '
    'architecture, materials, layout, colours, landmarks) so they look the same in every image. Only permanent '
    'features, never light, weather, time of day or people. Leave out places that appear only once.\n')
PLACES_SHAPE = ', "places": [{"name": "...", "look": "..."}]'


def note_text(note, modifiers=()):
    note = _clean(note)
    text = (f'The reader asked for this direction; it overrides your own taste: "{note}"\n') if note else ''
    rules = [m['rule'] for m in MODIFIERS if m['id'] in (modifiers or ())]
    return text + ''.join(f'Hard rule: {rule}\n' for rule in rules)


def clean_modifiers(value):
    known = [m['id'] for m in MODIFIERS]
    return [key for key in known if key in (value if isinstance(value, (list, tuple)) else ())]


def preset_lora(preset):
    """Hazir tarzin LoRA'si (plana kopyalanir: tarz listesi sonradan degisse de plan ayni kalir) ya da None."""
    entry = next((p for p in PRESETS if p['id'] == preset), None)
    return {key: entry.get(key, '') for key in LORA_KEYS} if entry and entry.get('lora') else None


def image_style(plan, style):
    """Gorsel isteminin oneki: LoRA'nin tetik kelimesi en basta, sonra stil."""
    trigger = _clean((plan.get('lora') or {}).get('trigger'))
    return ' '.join(part for part in (trigger, _clean(style)) if part)


def image_suffix(plan, base=SUFFIX, modifiers=True):
    """Gorsel isteminin son eki: LoRA ve seceneklerin olumlu ifadeleri + sabit son ek (portrede secenekler yok)."""
    parts = [_clean((plan.get('lora') or {}).get('suffix'))]
    parts += [m['suffix'] for m in MODIFIERS if modifiers and m['id'] in (plan.get('modifiers') or ())]
    return ', '.join(part for part in parts + [base] if part)


def style_prompt(sample, note='', modifiers=(), places=False):
    return STYLE_SYSTEM, STYLE_TASK.format(note=note_text(note, modifiers), places=PLACES_TASK if places else '',
                                           places_shape=PLACES_SHAPE if places else '') + sample


def parse_style(raw):
    """(stil, karakterler); stil yoksa ValueError."""
    data = _json_object(raw) or {}
    style = _clean(data.get('style'))
    if not style:
        raise ValueError('Dil modeli stil kılavuzu yazmadı.')
    return style, clean_characters(data.get('characters'))


def parse_places(raw):
    """Stil yanitindaki mekanlar (F209)."""
    return clean_places((_json_object(raw) or {}).get('places'))


def clean_characters(value, limit=12):
    result, seen = [], set()
    for item in value if isinstance(value, list) else ():
        if not isinstance(item, dict):
            continue
        name, look = _clean(item.get('name'))[:60], _clean(item.get('look'))[:400]
        if name and look and name.lower() not in seen:
            seen.add(name.lower())
            entry = {'name': name, 'look': look}
            changes = clean_changes(item.get('changes'))
            if changes:
                entry['changes'] = changes
            if item.get('kind') == 'other':   # insan degil (F211): tarif yetiskin sayilmaz
                entry['kind'] = 'other'
            result.append(entry)
    return result[:limit]


def clean_places(value, limit=12):
    """[{name, look}] (karakterlerle ayni kural; gorunus degisimi yok)."""
    return [{'name': c['name'], 'look': c['look']} for c in clean_characters(value, limit)]


# ---------------------------------------------------------------- gorunus degisimi (F209)
def clean_changes(value):
    """Karakterin kalici gorunus degisimleri [{section, start, look}] okuma sirasiyla (ayni yerde sonuncusu)."""
    found = {}
    for item in value if isinstance(value, list) else ():
        if not isinstance(item, dict):
            continue
        look = _clean(item.get('look'))[:400]
        try:
            where = (max(0, int(item.get('section'))), max(0, int(item.get('start') or 0)))
        except (TypeError, ValueError):
            continue
        if look:
            found[where] = {'section': where[0], 'start': where[1], 'look': look}
    return [found[key] for key in sorted(found)][:12]


def look_at(character, section, start=0):
    """Karakterin (bolum, cumle) yerindeki gorunusu: o yere kadarki son degisim, yoksa ilk tarifi."""
    look = character['look']
    for change in character.get('changes') or ():
        if (change['section'], change['start']) <= (int(section), int(start)):
            look = change['look']
    return look


def characters_at(characters, section, start=0):
    """Karakterler, gorunusleri o yerdeki haliyle (dil modeline giden liste)."""
    return [dict(c, look=look_at(c, section, start)) for c in characters]


def apply_changes(characters, changes, section):
    """Dil modelinin bildirdigi degisimler ([{name, start, look}]) adi bilinen karakterlere eklenir."""
    by_name = {c['name'].lower(): c for c in characters}
    for item in changes if isinstance(changes, list) else ():
        if not isinstance(item, dict):
            continue
        character = by_name.get(_clean(item.get('name')).lower())
        look = _clean(item.get('look'))[:400]
        try:
            start = int(str(item.get('start')).strip())
        except (TypeError, ValueError):
            continue
        if character is None or not look or look == look_at(character, section, start):
            continue
        character['changes'] = clean_changes((character.get('changes') or [])
                                             + [{'section': section, 'start': start, 'look': look}])
    return characters


# ---------------------------------------------------------------- yas ve cinsiyet (F211)
AGE_WORDS = re.compile(
    r'\b(?:man|men|woman|women|boy|boys|girl|girls|child|children|kid|baby|infant|toddler|teen\w*|adolescent|youth|'
    r'lady|gentleman|adult|elderly|elder|old|aged|middle-aged|young|\w+ties|\d+s|years?|grand\w+|'
    r'robot|android|cyborg|automaton|golem|creature|animal|beast|monster|alien|fairy|dog|cat|horse|bird|dragon|wolf|'
    r'machine|ghost|spirit|entity)\b', re.I)
AGE_SYSTEM = ('You fix character descriptions for an illustrated book. Answer with JSON only.')
AGE_TASK = (
    'These character looks do not say the age and sex, so the image model may draw an adult as a child:\n'
    '{characters}\n\n'
    'Judged from the book text below, rewrite each look so it starts with the explicit age and sex (e.g. "Man in '
    'his fifties", "Woman of about thirty", "Boy of about ten"); keep the rest of the look word for word. A short, '
    'small or slight person who works, marries or leads others is an adult. An animal, robot, creature or spirit '
    'gets "kind": "other" and its look starts with what it is, e.g. {{"name": "Fox", "look": "Old red fox, bushy '
    'tail", "kind": "other"}}.\n'
    'JSON shape: {{"characters": [{{"name": "...", "look": "...", "kind": "human"}}]}}\n\nBook text:\n\n')


def has_age(look):
    """Tarif yas ya da cinsiyet (ya da bilinen bir insan disi tur) soyluyor mu."""
    return bool(AGE_WORDS.search(str(look or '')))


def person_look(character):
    """Gorsel modeline giden tarif: yassiz insan tarifi yetiskin sayilir (yoksa ufak tefek kisi cocuk ciziliyordu);
    insan olmayan (kind 'other') oldugu gibi."""
    look = _clean(character.get('look'))
    if not look or character.get('kind') == 'other' or has_age(look):
        return look
    return f'Adult, {look[0].lower()}{look[1:]}'


def age_prompt(characters, sample):
    return AGE_SYSTEM, AGE_TASK.format(characters=character_lines(characters, False)) + sample


def fix_ages(characters, ask, sample, asked):
    """Yassiz tarifleri dil modeline bir kez yeniden yazdirir (`asked`: bu planlamada sorulan adlar). Insan olmayan
    'kind': 'other' alir; yanit yas vermezse tarif kalir, isteme giderken person_look yetiskin sayar."""
    todo = [c for c in characters if c.get('kind') != 'other' and not has_age(c['look'])
            and c['name'].lower() not in asked]
    if not todo:
        return characters
    asked.update(c['name'].lower() for c in todo)
    try:
        fixed = {c['name'].lower(): c for c in
                 clean_characters((_json_object(ask(*age_prompt(todo, sample))) or {}).get('characters'))}
    except ValueError:
        return characters
    for character in todo:
        found = fixed.get(character['name'].lower())
        if found and found.get('kind') == 'other':
            character['kind'] = 'other'   # model bazen tur yerine "Other red fox" yaziyor
            look = re.sub(r'^other\b[\s,:]*', '', found['look'], flags=re.I) or found['look']
            character['look'] = look[0].upper() + look[1:]
        elif found and has_age(found['look']):
            character['look'] = found['look']
    return characters


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


def per_scene(density):
    return DENSITY.get(density, DENSITY['medium'])


def focused(density):
    """Az ve daha seyrek: dil modeli parcayi bolmez, onemli anlari secer."""
    return per_scene(density) >= DENSITY['low']


def selective(density):
    """Parcadan seyrek: onem puanli adaylar, plan sonunda kitabin tamamindan secim (select_moments)."""
    return per_scene(density) > CHUNK_CHARS


def scene_count(chars, density='medium'):
    """Parcadaki hedef sahne sayisi (kisa parca 0); selective siklikta parcadan istenen aday sayisi."""
    if chars < MIN_SCENE_CHARS:
        return 0
    if selective(density):
        return min(MAX_CANDIDATES, max(1, -(-chars * CANDIDATES // per_scene(density))))
    return max(1, round(chars / per_scene(density)))


SCENE_SYSTEM = STYLE_SYSTEM
PROMPT_RULE = (
    'English image prompt, 40-90 words, describing only what is visible: setting, subjects, action, '
    'framing. Start directly with the scene; never restate the medium, art style or palette (the style guide is '
    'already added). Describe characters by their look (the image model does not know names). Every character appears at '
    'most once in the image; say how many people are visible. Describe what IS '
    'there; never write "no ...", never ask for text, letters, signs or screens with writing. For non-fiction or '
    'reflective passages prefer places, objects, period details or symbolic imagery.')
SCENE_TASK = (
    'Style guide of the edition (it is added to every prompt automatically, do not repeat it):\n{style}\n\n'
    'Recurring characters (when one appears, copy its look into the prompt word for word):\n{characters}\n\n'
    '{places}'
    '{note}'
    '{previous}'
    'Below is the next part of the book as numbered sentences. {choose} For each scene give:\n'
    '- "start": {start_rule}\n'
    '- "title": short title in the language of the book\n'
    '- "prompt": ' + PROMPT_RULE + '\n'
    '{importance}'
    '- "characters": optional, new recurring characters introduced here with a fixed look '
    '[{{"name": "...", "look": "..."}}]. ' + AGE_RULE + '\n'
    '{extra}'
    '{cast}'
    '{opening}'
    'JSON shape: {{"scenes": [{{"start": {first}, "title": "...", "prompt": "...", "characters": []{cast_shape}}}]}}\n\n')
SPLIT_TASK = ('Split it at meaningful scene, location or mood changes into about {count} scenes (between {low} and '
              '{high}).')
SPLIT_START = 'number of the first sentence the image belongs to (the first scene starts at {first})'
# az ve daha seyrek siklik (F209): bolme degil, onemli anlar; gorsel bir sonrakine kadar ekranda kalir
FOCUS_TASK = ('Pick the {count} moments of it that matter most for the book (between {low} and {high}): turning '
              'points, dramatic peaks, emotionally strong or visually striking moments, the first appearance of a '
              'major character or place. Skip routine and transitional passages: an image stays on screen until the '
              'next one, so the moments do not have to cover the whole part.')
FOCUS_START = 'number of the sentence where the moment begins ({first} to {last})'
IMPORTANCE_TASK = ('- "importance": 1-10, how central and memorable this moment is for the whole book (10: a key '
                   'turning point, 1: a minor detail)\n')
# mekan kimligi (F209): mekanin kalici gorunusu uretimde eklenir, dil modeli yalnizca adini verir
PLACES_LIST = ('Recurring places (when a scene happens in one, give its name in "place"; its permanent look is added '
               'to the prompt automatically, so describe only the visible part of it, the light, weather and what '
               'happens there):\n{places}\n\n')
PLACE_TASK = ('- "place": name of the recurring place where the scene happens (exact name from the list above or from '
              '"places"), "" if none\n'
              '- "places": optional, new recurring places introduced here with a fixed look (20-40 words: '
              'architecture, materials, layout, colours) [{{"name": "...", "look": "..."}}]\n')
# gorunus degisimi (F209): karakterin kalici gorunusu degisirse sonraki gorseller yeni tarifle
CHANGES_TASK = ('- "changes": optional, only when a recurring character\'s lasting appearance changes in this part '
                '(grows older, new clothes or uniform, a scar, new hair): [{{"name": "...", "start": sentence number, '
                '"look": "the full new look, 15-35 words"}}]; later images use the new look. ' + AGE_RULE + '\n')
# bolum acilis gorseli (F209): bolumun ilk sayfasi kendi gorselini aldiysa sahneler sonrasindan baslar
OPENED_TASK = ('The first page of this chapter already has its own image, so the scenes start at sentence {second} '
               'or later.\n')
# Acilis gorseli ayri istekle ve yalnizca bolumun ilk sayfasindan yazilir: model bolumun devamini gormez, okurun
# henuz okumadigi bir seyi (spoiler) gosteremez. Hikaye disi sayfada (kunye, ithaf, yazarin hayati) {"skip": true}.
OPENING_PAGE = 1500   # ilk sayfa: bu kadar karakter (en az bir cumle)
MIN_OPENING_CHARS = 200   # kisa bolum de acilis alir (sahne sinirindan kucuk); yalnizca baslik gibi bolumler almaz
OPENING_TASK = (
    'Style guide of the edition (it is added to every prompt automatically, do not repeat it):\n{style}\n\n'
    'Recurring characters (when one appears, copy its look into the prompt word for word):\n{characters}\n\n'
    '{places}'
    '{note}'
    'Below is the first page of a chapter as numbered sentences. Write the image shown while this page is read, at '
    'the very start of the chapter. Show only what this page itself tells or implies (place, people, situation, '
    'mood): the reader has not read any further, so never show anything that may happen later in the chapter. '
    'If the page is not part of the story (author biography, title or copyright page, dedication, contents, notes '
    'about the edition, foreword or preface by someone else), answer {{"skip": true}}. Otherwise give:\n'
    '- "title": short title in the language of the book\n'
    '- "prompt": ' + PROMPT_RULE + '\n'
    '{extra}'
    '{cast}'
    'JSON shape: {{"title": "...", "prompt": "..."{shape}}}\n\n')
# karakter kimligi acikken (F201): her sahneye gorunen karakterlerin adlari; poz ve bakis portreden kopyalanmasin
CAST_TASK = (
    '- "cast": names of the recurring characters visible in the image (exact names from the list above or from '
    '"characters"), the most important first, at most {limit}; [] if none. Each of them is drawn from a reference '
    'portrait, so for them describe pose, action, gaze direction and expression clearly (people are caught in the '
    'middle of the action, not posing or looking at the camera unless the text says so).\n')


def character_lines(characters, people=True):
    """Dil modeline giden liste; `people` kapali (mekanlar, yas istegi) tarif oldugu gibi."""
    return '\n'.join(f'- {c["name"]}: {person_look(c) if people else c["look"]}'
                     for c in characters) or '- (none yet)'


def scene_prompt(style, characters, sentences, start, stop, count, note='', previous=None, identity=False,
                 modifiers=(), focus=False, places=None, changes=False, opening=False):
    """Parcanin sahne istegi. `focus`: onemli anlari sec (az ve seyrek siklik, onem puaniyla); `places`: mekan kimligi
    acikken bilinen mekanlar (None kapali); `changes`: gorunus degisimlerini sor; `opening`: bolumun ilk sayfasinin
    kendi gorseli var (sahneler sonrasindan baslar)."""
    lines = '\n'.join(f'{i}: {_clean(sentences[i])}' for i in range(start, stop))
    before = (f'The previous image showed: {previous}\n\n') if previous else ''
    numbers = {'count': count, 'low': max(1, count - 1), 'high': count + 1, 'first': start, 'last': stop - 1}
    shape = ', "cast": []' if identity else ''
    if places is not None:
        shape += ', "place": "", "places": []'
    if changes:
        shape += ', "changes": []'
    task = SCENE_TASK.format(
        style=style, characters=character_lines(characters), note=note_text(note, modifiers), previous=before,
        places=PLACES_LIST.format(places=character_lines(places, False)) if places is not None else '',
        choose=(FOCUS_TASK if focus else SPLIT_TASK).format(**numbers),
        start_rule=(FOCUS_START if focus else SPLIT_START).format(**numbers),
        importance=IMPORTANCE_TASK if focus else '',
        extra=(PLACE_TASK.format() if places is not None else '') + (CHANGES_TASK.format() if changes else ''),
        cast=CAST_TASK.format(limit=MAX_CAST) if identity else '', first=start,
        opening=OPENED_TASK.format(second=start + 1) if opening else '', cast_shape=shape)
    return SCENE_SYSTEM, task + lines


def first_page(sentences, limit=OPENING_PAGE):
    """Bolumun ilk sayfasinin cumle sayisi (en az bir)."""
    size = 0
    for index, sentence in enumerate(sentences):
        size += len(sentence) + 1
        if size >= limit:
            return index + 1
    return len(sentences)


def opening_prompt(style, characters, sentences, note='', identity=False, modifiers=(), places=None):
    """Bolum acilis gorseli istegi: yalnizca bolumun ilk sayfasi gider (spoiler olmasin)."""
    lines = '\n'.join(f'{i}: {_clean(sentences[i])}' for i in range(first_page(sentences)))
    shape = (', "cast": []' if identity else '') + (', "place": ""' if places is not None else '')
    task = OPENING_TASK.format(
        style=style, characters=character_lines(characters), note=note_text(note, modifiers),
        places=PLACES_LIST.format(places=character_lines(places, False)) if places is not None else '',
        extra=PLACE_TASK.format().split('\n')[0] + '\n' if places is not None else '',
        cast=CAST_TASK.format(limit=MAX_CAST) if identity else '', shape=shape)
    return SCENE_SYSTEM, task + lines


def parse_opening(raw, style=''):
    """Acilis gorseli {title, prompt[, cast, place]}; hikaye disi sayfa ya da istemsiz yanit None."""
    data = _json_object(raw) or {}
    prompt = strip_style(_clean(data.get('prompt')), style)
    if data.get('skip') is True or not prompt:
        return None
    entry = {'title': _clean(data.get('title'))[:80], 'prompt': prompt[:1200]}
    if isinstance(data.get('cast'), list):
        entry['cast'] = clean_cast(data['cast'])
    if _clean(data.get('place')):
        entry['place'] = _clean(data['place'])[:60]
    return entry


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


def parse_scenes(raw, start, stop, sentences, style='', first=True):
    """[{start, title, prompt}] ve yeni karakterler: aralik disi, tekrarlanan ya da istemsiz sahne atilir; `first`
    iken ilk sahne parcanin basina cekilir (parcanin basi baska bir sahnenin devami olmasin; onemli anlar secilirken
    cekilmez). Basa yazilan stil cumlesi atilir. Varsa 'importance' (1-10) ve 'place' de alinir."""
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
        if isinstance(item.get('cast'), list):
            found[index]['cast'] = clean_cast(item['cast'])
        if 'importance' in item:
            try:
                found[index]['importance'] = min(10, max(1, int(round(float(item['importance'])))))
            except (TypeError, ValueError):
                found[index]['importance'] = 5
        if _clean(item.get('place')):
            found[index]['place'] = _clean(item['place'])[:60]
        characters += clean_characters(item.get('characters'))
    scenes = [found[key] for key in sorted(found)]
    if first and scenes and scenes[0]['start'] != start:
        scenes[0]['start'] = start
    return scenes, characters


def parse_extras(raw, style=''):
    """Sahne yanitinin secenekli alanlari (F209): {'places': [...], 'changes': [{name, start, look}]} (sahnelerdeki
    'places' / 'changes' listeleri birlestirilir)."""
    data = _json_object(raw) or {}
    places, changes = [], []
    items = [data] + [item for item in data.get('scenes') or () if isinstance(item, dict)] \
        if isinstance(data.get('scenes'), list) else [data]
    for item in items:
        places += clean_places(item.get('places'))
        changes += [c for c in item.get('changes') or () if isinstance(c, dict)] \
            if isinstance(item.get('changes'), list) else []
    return {'places': places, 'changes': changes}


def select_moments(candidates, target, spacing):
    """Kitabin tamamindan en onemli `target` an (selective siklik): her adimda onem puani en buyuk aday, esitlikte
    secilmis anlara en uzak olan (dil modeli bircok ana ayni puani verir; kitapta once gelen kazanirsa gorseller
    basa yigiliyordu). Secilen iki an arasi en az `spacing` karakter ('pos'), yer kalmazsa aralik gozetilmeden
    tamamlanir. Donen: okuma sirasiyla."""
    pos = lambda c: c.get('pos', 0)
    chosen = []
    for gap in (spacing, 0):
        while len(chosen) < target:
            distance = lambda c: min((abs(pos(c) - pos(o)) for o in chosen), default=0)
            pool = [c for c in candidates if not any(c is o for o in chosen) and (not chosen or distance(c) >= gap)]
            if not pool:
                break
            chosen.append(max(pool, key=lambda c: (int(c.get('importance', 5)), distance(c), -pos(c))))
    return sorted(chosen, key=pos)


def merge_characters(characters, extra, limit=12):
    names = {c['name'].lower() for c in characters}
    return (characters + [c for c in extra if c['name'].lower() not in names])[:limit]


def keep_portraits(characters, old):
    """Karakterler elle duzenlenince portreler ada gore korunur (clean_characters yalnizca ad ve gorunus tutar)."""
    by_name = {c['name'].lower(): c for c in old or ()}
    for character in characters:
        before = by_name.get(character['name'].lower(), {})
        character.update({key: before[key] for key in ('portrait', 'portrait_version', 'portrait_seed', 'portrait_own',
                                                        'kind')
                          if key in before})
    return characters


# ---------------------------------------------------------------- karakter kimligi (F201)
def clean_cast(value):
    names = []
    for item in value if isinstance(value, list) else ():
        name = _clean(item)[:60]
        if name and name.lower() not in (n.lower() for n in names):
            names.append(name)
    return names[:6]


def _words(text):
    return re.findall(r'\w+', str(text or '').lower())


def cast_of(scene, characters):
    """Sahnede gorunen karakterler (sirayla). scene['cast'] varsa o; yoksa adi ya da gorunusunun ilk alti kelimesi
    istemde geciyor mu (sahne istemine dil modeli gorunusu aynen kopyalar)."""
    by_name = {c['name'].lower(): c for c in characters}
    if isinstance(scene.get('cast'), list):
        return [by_name[name.lower()] for name in scene['cast'] if name.lower() in by_name]
    prompt = f' {" ".join(_words(scene.get("prompt")))} '
    found = []
    for character in characters:
        looks = [character['look']] + [change['look'] for change in character.get('changes') or ()]
        parts = [' '.join(_words(look)[:6]) for look in looks] + [' '.join(_words(character['name']))]
        hits = [prompt.find(f' {part} ') for part in parts if part and f' {part} ' in prompt]
        if hits:
            found.append((min(hits), character))
    return [character for _at, character in sorted(found, key=lambda item: item[0])]


def medium(style):
    """Portre icin stilin yalnizca ilk cumlesi (teknik ve malzeme); ortam, isik ve renk portreye girmesin."""
    first = re.split(r'(?<=[.!?])\s+', _clean(style), maxsplit=1)[0]
    return first[:240]


def _sentence(text):
    """Sonundaki noktalama atilmis metin (istemler birlestirilirken '..' olmasin)."""
    return _clean(text).rstrip(' .')


def portrait_prompt(character):
    return (f'Character reference portrait, head and shoulders, three-quarter view with the head turned slightly, '
            f'relaxed natural expression, face clearly visible. {_sentence(person_look(character))}. '
            f'Plain flat mid-grey studio backdrop with nothing else behind, soft even studio light.')


def identity_prompt(scene, people, style):
    """Kimlik is akisinin istemi (talimat bicimi: LoRA "bu kisiyi ... ciz" diye egitildi). Stil sona eklenir;
    kimlik is akisinda PRE/POST dugumu yoktur (son ek comfy_client.fill'de '. ' ile eklenir)."""
    who = ('this person' if len(people) == 1 else 'these people')
    looks = [_sentence(person_look(c)) for c in people]
    names = ' and '.join(f'the person from reference {n + 1} ({look})' for n, look in enumerate(looks)) \
        if len(people) > 1 else looks[0]
    return (f'Create an illustration of {who}: {names}. {_sentence(scene["prompt"])}. Preserve the exact facial '
            f'identity of the reference portrait, but not its pose, framing or background: the pose, gaze and '
            f'expression follow the scene. Style: {_sentence(style)}')


def scene_people(scene, characters):
    """Sahnedeki karakterler, gorunusleri sahnenin yerindeki haliyle (F209 gorunus degisimi)."""
    return characters_at(cast_of(scene, characters), scene['section'], scene['start'])


def scene_text(plan, scene):
    """Gorsel modeline giden sahne istemi: mekan kimligi aciksa sahnenin mekaninin kalici tarifi sona eklenir
    (dil modeli mekani tarif etmez, yalnizca adini verir; mekan tarifi duzenlenince yeni gorsellere yansir)."""
    prompt = scene['prompt']
    if plan.get('place_identity') and scene.get('place'):
        place = next((p for p in plan.get('places') or () if p['name'].lower() == scene['place'].lower()), None)
        if place:
            prompt = f'{_sentence(prompt)}. Setting: {_sentence(place["look"])}.'
    return prompt


def portrait_slug(name):
    table = str.maketrans('çğıöşüÇĞİÖŞÜâîû', 'cgiosuCGIOSUaiu')
    slug = re.sub(r'[^0-9a-z]+', '-', str(name).translate(table).lower()).strip('-')
    return slug[:40] or 'karakter'


def clean_upscale(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return value if value in UPSCALES else 0


def new_plan(note='', preset='', density='medium', size=DEFAULT_SIZE, title='', identity=False, modifiers=(),
             options=None):
    """Yeni plan. `options` (F209): openers (bolum acilis gorseli), places (mekan kimligi), changes (gorunus
    degisimi), upscale (RTX buyutme katsayisi, 0 kapali)."""
    modifiers, options = clean_modifiers(modifiers), options or {}
    people = 'no-people' not in modifiers
    return {'version': VERSION, 'created': datetime.now().isoformat(timespec='seconds'), 'title': title,
            'note': _clean(note), 'preset': preset, 'density': density if density in DENSITY else 'medium',
            'size': size if size in SIZES else DEFAULT_SIZE, 'seed': random.randrange(1, 2 ** 31),
            'style': '', 'characters': [], 'scenes': [], 'complete': False, 'next_chunk': 0, 'numbered': True,
            'identity': bool(identity) and not set(modifiers) & set(NO_CAST), 'modifiers': modifiers,
            'lora': preset_lora(preset), 'openers': bool(options.get('openers')),
            'place_identity': bool(options.get('places')), 'places': [],
            'look_changes': bool(options.get('changes')) and people, 'upscale': clean_upscale(options.get('upscale'))}


def renumber(plan, texts):
    """Eski plan onarimi: 'numbered' olmayan planda sahnenin bolumu metni olan bolumler arasindaki siraydi (bos
    bolumler atlaniyordu), okuyucu ise kitabin bolum numarasini sorar. `texts`: kitabin bolumlerinin duz metni.
    Her sahnenin baslangic cumlesi (anchor) yeni bolumunde bulunursa plan duzeltilir; donen: duzeltildi mi."""
    if plan.get('numbered'):
        return False
    squash = lambda text: ''.join(str(text or '').split())
    texts = [squash(text) for text in texts]
    mapping = [number for number, text in enumerate(texts) if text]
    moved = []
    for scene in plan['scenes']:
        index = int(scene['section'])
        if not 0 <= index < len(mapping) or squash(scene.get('anchor')) not in texts[mapping[index]]:
            return False
        moved.append(mapping[index])
    for scene, number in zip(plan['scenes'], moved):
        scene['section'] = number
    plan['numbered'] = True
    return True


def opening_scene(plan, real, sentences, ask, add):
    """Bolum acilis gorseli (F209): ilk sayfadan ayri istek, sahne plan['scenes']'e eklenir. Hikaye disi sayfa
    plan['opening_skipped']'e yazilir, bir daha sorulmaz. Donen: bolumun acilis gorseli var mi."""
    key = f'{real}-open'
    if any(scene['id'] == key for scene in plan['scenes']):
        return True
    if real in (plan.get('opening_skipped') or ()):
        return False
    people = 'no-people' not in (plan.get('modifiers') or ())
    found = parse_opening(ask(*opening_prompt(
        plan['style'], characters_at(plan['characters'], real, 0) if people else [], sentences, plan.get('note'),
        plan.get('identity'), plan.get('modifiers'), plan.get('places') if plan.get('place_identity') else None)),
        plan['style'])
    if not found:
        plan.setdefault('opening_skipped', []).append(real)
        return False
    entry = {'id': key, 'section': real, 'start': 0, 'anchor': _clean(sentences[0]),
             'title': found['title'] or 'Bölüm açılışı', 'prompt': found['prompt'], 'opening': True}
    for name in ('cast', 'place'):
        if name in found:
            entry[name] = found[name]
    add(entry, plan['scenes'])
    return True


def add_openers(sections, ask, plan, cancel=None, progress=None, save=None):
    """Var olan plana eksik bolum acilis gorsellerini ekler (yeniden planlamadan, F209). Ilk cumlesinde zaten
    sahnesi olan bolum ve daha once atlanan hikaye disi sayfa sorulmaz; `progress(islenen, toplam)` bolum sayisiyla."""
    plan['openers'] = True
    todo = [section for index, section in enumerate(sections)
            if len(section['sentences']) > 1 and sum(len(s) + 1 for s in section['sentences']) >= MIN_OPENING_CHARS
            and not any(scene['section'] == section.get('number', index) and scene['start'] == 0
                        and not scene.get('opening') for scene in plan['scenes'])]

    def add(entry, where):
        entry.update(seed=random.randrange(1, 2 ** 31), image='', skip=False)
        where.append(entry)

    for done, section in enumerate(todo):
        if cancel is not None and cancel.is_set():
            raise Cancelled('Görsel planı durduruldu.')
        if progress:
            progress(done, len(todo))
        opening_scene(plan, section.get('number', sections.index(section)), section['sentences'], ask, add)
        plan['scenes'].sort(key=lambda s: (s['section'], s['start'], not s.get('opening')))
        if save:
            save(plan)
    if progress:
        progress(len(todo), len(todo))
    return plan


def plan_book(sections, ask, plan, cancel=None, progress=None, save=None):
    """Plani doldurur (kaldigi parcadan devam eder). `ask(system, user) -> yanit`; `progress(islenen, toplam)` cumle
    sayisiyla; `save(plan)` her parcadan sonra (durdurulup yeniden baslatilinca devam icin). Donen: plan."""
    parts = chunks(sections)
    total = sum(len(section['sentences']) for section in sections)
    done = sum(stop - start for _section, start, stop in parts[:plan.get('next_chunk', 0)])
    density = plan.get('density')
    focus, choose = focused(density), selective(density)
    people = 'no-people' not in (plan.get('modifiers') or ())
    places = plan.get('place_identity')
    # selective: her cumlenin kitaptaki karakter konumu (secilen anlarin arasi buna gore acilir)
    offsets, at = [], 0
    for section in sections:
        offsets.append(at)
        at += sum(len(s) + 1 for s in section['sentences'])
    if progress:
        progress(done, total)
    asked = set()   # yasi yeniden sorulan karakterler (F211)
    if not plan.get('style'):
        sample = digest(sections)
        raw = ask(*style_prompt(sample, plan.get('note'), plan.get('modifiers'), places))
        plan['style'], plan['characters'] = parse_style(raw)
        if people:
            fix_ages(plan['characters'], ask, sample, asked)
        if places:
            plan['places'] = parse_places(raw)
        if not people:
            plan['characters'] = []
        if save:
            save(plan)

    def add(entry, where):
        entry.update(seed=plan['seed'] + len(plan['scenes']) + len(plan.get('candidates') or ()), image='', skip=False)
        where.append(entry)

    for number in range(plan.get('next_chunk', 0), len(parts)):
        if cancel is not None and cancel.is_set():
            raise Cancelled('Görsel planı durduruldu.')
        section, start, stop = parts[number]
        sentences = sections[section]['sentences']
        count = scene_count(sum(len(s) + 1 for s in sentences[start:stop]), density)
        real = sections[section].get('number', section)   # okuyucunun bolum numarasi
        opening = (bool(plan.get('openers')) and start == 0 and stop > 1
                   and sum(len(s) + 1 for s in sentences) >= MIN_OPENING_CHARS
                   and opening_scene(plan, real, sentences, ask, add))
        if count:
            earlier = (plan.get('candidates') or []) + plan['scenes']
            previous = max(earlier, key=lambda s: (s['section'], s['start']))['prompt'] if earlier else None
            raw = ask(*scene_prompt(plan['style'], characters_at(plan['characters'], real, start), sentences, start,
                                    stop, count, plan.get('note'), previous, plan.get('identity'),
                                    plan.get('modifiers'), focus, plan.get('places') if places else None,
                                    bool(plan.get('look_changes')) and people, opening))
            scenes, extra = parse_scenes(raw, start, stop, sentences, plan['style'], first=not focus)
            extras = parse_extras(raw, plan['style'])
            if people:
                plan['characters'] = merge_characters(plan['characters'], extra)
                new = {c['name'].lower() for c in extra}   # yalnizca bu parcada tanitilanlar (metin onlari anlatir)
                fix_ages([c for c in plan['characters'] if c['name'].lower() in new], ask,
                         ' '.join(_clean(s) for s in sentences[start:stop]), asked)
                if plan.get('look_changes'):
                    apply_changes(plan['characters'], [c for c in extras['changes']
                                                       if str(c.get('start', '')).strip().isdigit()
                                                       and start <= int(c['start']) < stop], real)
            if places:
                plan['places'] = merge_characters(plan.get('places') or [], extras['places'])
            if opening:
                # acilis gorseli bolumun ilk cumlesinde; ayni cumleye dusen sahne bir sonrakine kayar
                taken = {scene['start'] for scene in scenes}
                for scene in scenes:
                    if scene['start'] == start:
                        if start + 1 in taken:
                            scenes.remove(scene)
                        else:
                            scene['start'] = start + 1
                        break
            for scene in scenes:
                entry = {'id': f'{real}-{scene["start"]}', 'section': real, 'start': scene['start'],
                         'anchor': _clean(sentences[scene['start']]), 'title': scene['title'],
                         'prompt': scene['prompt']}
                for key in ('cast', 'importance', 'place'):
                    if key in scene:
                        entry[key] = scene[key]
                if choose:
                    entry['pos'] = offsets[section] + sum(len(s) + 1 for s in sentences[:scene['start']])
                    add(entry, plan.setdefault('candidates', []))
                else:
                    add(entry, plan['scenes'])
        plan['next_chunk'] = number + 1
        done += stop - start
        if save:
            save(plan)
        if progress:
            progress(done, total)
    if choose:
        target = max(1, round(at / per_scene(density)))
        picked = select_moments(plan.pop('candidates', None) or [], target, per_scene(density) * SPACING)
        for entry in picked:
            entry.pop('pos', None)
            entry['seed'] = plan['seed'] + len(plan['scenes'])
            plan['scenes'].append(entry)
        plan['scenes'].sort(key=lambda s: (s['section'], s['start']))
    plan['complete'] = True
    return plan


# ---------------------------------------------------------------- sahne basina kucuk duzeltme
REFINE_SYSTEM = ('You edit image prompts. Apply the requested change with the smallest possible edit and keep '
                 'everything else word for word. Answer with the new prompt only, no explanation.')
REFINE_TASK = (
    'Prompt:\n{prompt}\n\nRequested change (may be in Turkish): {instruction}\n\n'
    'Rules: to remove something, delete it from the description instead of writing "no ..." (negative words do '
    'not work with this model). Keep it English, 40-100 words. Do not mention text or letters.')


def refine_prompt(prompt, instruction, modifiers=()):
    rules = note_text('', modifiers)
    return REFINE_SYSTEM, REFINE_TASK.format(prompt=_clean(prompt), instruction=_clean(instruction)) + (
        f'\n{rules}' if rules else '')


def parse_refined(raw, fallback):
    text = re.sub(r'<think>.*?</think>', ' ', str(raw or ''), flags=re.S).strip().strip('`').strip()
    text = re.sub(r'^(?:new\s+)?prompt\s*:\s*', '', text, flags=re.I).strip().strip('"').strip()
    return _clean(text)[:1200] or fallback


# ---------------------------------------------------------------- toplu stil degisikligi (F209)
# Sahne istemleri yeniden yazilmaz: yalnizca stil kilavuzu (her istemin oneki) yeni yone gore yeniden yazilir, tarzin
# LoRA'si plana kopyalanir, sonra butun gorseller ayni seed'lerle yeniden uretilir.
RESTYLE_TASK = (
    'Old style guide of the edition (use it ONLY for the era and technology look of the world; ignore its medium, '
    'technique, colour palette and lighting):\n{style}\n\n'
    '{note}'
    'Write:\n'
    '1. "world": one sentence with only the era, technology and setting look taken from the old guide (no medium, '
    'technique, colours or light).\n'
    '2. "style": the new style guide, 60-120 words, used as the prefix of EVERY image prompt: medium, technique, colour '
    'palette, lighting and mood from the reader\'s direction alone. Write it entirely in '
    'English: translate the reader\'s words, never copy a non-English word. Describe what IS there, never "no ..." '
    'or "instead of". Do not name real artists. Do not describe a specific scene.\n'
    'JSON shape: {{"world": "...", "style": "..."}}')


def restyle_prompt(style, note, modifiers=()):
    return STYLE_SYSTEM, RESTYLE_TASK.format(style=_clean(style), note=note_text(note, modifiers))


def parse_restyle(raw):
    """Yeni stil kilavuzu: tarz kismi + eski kilavuzdan alinan dunya cumlesi (model eski teknigi karistirmasin diye
    ikisi ayri istenir, burada birlesir). Stil yoksa ValueError."""
    data = _json_object(raw) or {}
    style, world = parse_style(raw)[0], _clean(data.get('world'))
    if world and world.lower()[:40] not in style.lower():
        style = f'{_sentence(style)}. {_sentence(world)}.'
    return style


def restyle(plan, preset='', note=''):
    """Planin tarzini degistirir (stil kilavuzu ayrica yazilir): not, hazir tarz ve LoRA'si."""
    plan.update(note=_clean(note), preset=preset or '', lora=preset_lora(preset))
    return plan


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

    def write_image(self, book, scene_id, data, upscaled=0):
        """Yeni gorseli <sahne>-<surum>.png olarak yazar (surum: tarayici onbellegi eskisini gostermesin), eskisini
        siler. `upscaled`: RTX ile buyutulduyse katsayi (yeni uretilen gorselde 0). Donen: guncel plan."""
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
            scene.update(image=name, version=version, upscaled=upscaled)

        plan = self.update(book, change)
        old = holder.get('old')
        if old and old != next(s for s in plan['scenes'] if s['id'] == scene_id)['image']:
            (folder / old).unlink(missing_ok=True)
        return plan

    def portrait_path(self, book, character):
        return self.folder(book) / character['portrait'] if character.get('portrait') else None

    def character(self, plan, name):
        found = next((c for c in plan['characters'] if c['name'].lower() == str(name or '').lower()), None)
        if found is None:
            raise ValueError('Karakter bulunamadı.')
        return found

    def write_portrait(self, book, name, data, own=False, seed=None):
        """Karakterin portresi portre-<ad>-<surum>.png (eskisi silinir); `own` kullanicinin kendi gorseli."""
        folder = self.folder(book)
        folder.mkdir(parents=True, exist_ok=True)
        holder = {}

        def change(plan):
            character = self.character(plan, name)
            version = int(character.get('portrait_version', 0)) + 1
            file = f'portre-{portrait_slug(character["name"])}-{version}.png'
            partial = folder / (file + '.part')
            partial.write_bytes(data)
            partial.replace(folder / file)
            holder['old'] = character.get('portrait')
            character.update(portrait=file, portrait_version=version, portrait_own=bool(own))
            if seed is not None:
                character['portrait_seed'] = int(seed)

        plan = self.update(book, change)
        if holder.get('old') and holder['old'] != self.character(plan, name)['portrait']:
            (folder / holder['old']).unlink(missing_ok=True)
        return plan

    def clear_portrait(self, book, name):
        holder = {}

        def change(plan):
            character = self.character(plan, name)
            holder['old'] = character.pop('portrait', None)
            character.pop('portrait_own', None)

        plan = self.update(book, change)
        if holder.get('old'):
            (self.folder(book) / holder['old']).unlink(missing_ok=True)
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


def not_upscaled(plan):
    """Planin buyutme katsayisiyla buyutulmemis gorseller (okuma sirasiyla; buyutme kapaliysa bos)."""
    factor = plan.get('upscale') or 0
    return [scene for scene in sorted(plan['scenes'], key=lambda s: (s['section'], s['start']))
            if factor and scene.get('image') and not scene.get('skip') and scene.get('upscaled') != factor]


def section_images(plan, section):
    """Okuyucu: bolumun sahneleri [{start, anchor, image}] ve bolumden onceki son gorsel (bolum basindan ilk sahneye
    kadar o kalir)."""
    shown = [scene for scene in plan['scenes'] if scene.get('image') and not scene.get('skip')]
    here = sorted((scene for scene in shown if scene['section'] == section),
                  key=lambda s: (s['start'], not s.get('opening')))
    before = [scene for scene in shown if scene['section'] < section]
    carry = max(before, key=lambda s: (s['section'], s['start'])) if before else None
    return here, carry
