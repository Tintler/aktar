"""Gazete (F226): sayfayi modellerle okuma ve makalelere baglama.

Tesseract gazete sayfasinda konumu iyi, metni kotu okur (sutun kirintilari, Turkce harfler); serif buyuk
basliklari hic bulamayabilir. Burada is bolumu:
  - konum: Tesseract (tam sayfa satir/blok + yarim olcekte seyrek baslik taramasi, gazete.propose)
  - metin: OCR modeli (orn. glm-ocr) her blogu ve sonra her makale sutununu ayri kirpip okur
  - baglam: dil modeli (orn. gemma-4-26b) her govde blogunun hangi basliga ait oldugunu secer. Model yalnizca
    geometrinin izin verdigi adaylar arasindan secer (ustteki, yatayda ortusen basliklar); kutu koordinati
    uretmez -- gorsel modellere kutu cizdirmek denendi, koordinatlar uydurma cikti.
Model yaniti okunamazsa gazete.articles_of kurallarina donulur.
"""
from __future__ import annotations

import json
import re

import gazete

SCALE = 3.0            # govde yazisi OCR modeline ~3 kat buyutulup verilir (1x'te ı/i, ğ/g karisiyor)
TARGET_HEIGHT = 54     # buyutulmus satir yuksekligi (piksel)
MAX_SIDE = 2400        # kirpintinin buyutulmus uzun kenari en fazla
MIN_LETTERS = 20       # daha az harfli govde blogu (resim alti, ad) modele sorulmaz
CANDIDATES = 4
REACH = 0.15           # aday baslik yatayda sayfa genisliginin bu kadari uzakta olabilir
MAX_TOKENS = 8000
_FENCE = re.compile(r'^```\w*\s*|\s*```$')


# ---------------------------------------------------------------------- okuma
def clean(text):
    """OCR modeli ciktisi: markdown isaretleri ve donguler atilir."""
    import documents
    text = str(text or '').replace('\r\n', '\n')
    text = _FENCE.sub('', text.strip())
    text = re.sub(r'^\s{0,3}#{1,6}\s+', '', text, flags=re.M)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    return documents.trim_repetition(text)[0].strip()


def scale_for(size, crop):
    """Kirpintinin buyutme katsayisi: satir yuksekligi TARGET_HEIGHT'a, uzun kenar MAX_SIDE'i asmadan."""
    factor = min(SCALE, TARGET_HEIGHT / max(1.0, size)) if size else SCALE
    return max(1.0, min(factor, MAX_SIDE / max(1, max(crop))))


def reader(client, model, prompt='Text Recognition:'):
    """(png baytlari) -> metin; OCR modeliyle."""
    return lambda png: clean(client.vision(prompt, png, model=model, max_tokens=4096))


def read_blocks(image, blocks, read, cache=None):
    """Her blogu kirpip modele okutur; block['text'] modelin metni olur. cache: {kutu: metin} (sayfa onbellegi)."""
    from PIL import Image
    cache = cache if cache is not None else {}
    for block in blocks:
        key = ','.join(str(int(v)) for v in block['box'])
        if key not in cache:
            x1, y1, x2, y2 = block['box']
            margin = 8
            crop = image.crop((max(0, x1 - margin), max(0, y1 - margin), min(image.width, x2 + margin),
                               min(image.height, y2 + margin)))
            factor = scale_for(block.get('size'), crop.size)
            if factor > 1:
                crop = crop.resize((round(crop.width * factor), round(crop.height * factor)), Image.LANCZOS)
            cache[key] = read(gazete._png(crop))
        block['text'] = ' '.join(cache[key].split()) if block.get('head') else cache[key]
    return cache


# ---------------------------------------------------------------------- baglam
def letters(text):
    return sum(char.isalpha() for char in str(text))


def candidates(block, heads, body, width, seps=()):
    """Blogun olasi basliklari (yakindan uzaga): blogun ustunde baslayan, yatayda ortusen ya da yakin olanlar.
    Arada ayirici cizgi olan baslik sona kalir."""
    bx1, by1, bx2, _by2 = block['box']
    found = []
    for index, head in enumerate(heads):
        hx1, hy1, hx2, hy2 = head['box']
        if hy1 > by1 + body or min(hx2, bx2) + REACH * width < max(hx1, bx1):
            continue
        distance = max(0, by1 - hy2) + max(0, hx1 - bx2, bx1 - hx2)
        low, high = max(hx1, bx1), min(hx2, bx2)
        if high <= low:
            low, high = bx1, bx2
        if any(hy2 + 0.3 * body < y < by1 - 0.3 * body and min(x2, high) - max(x1, low) > 0.5 * (high - low)
               for y, x1, x2 in seps):
            distance += 10 * width
        found.append((distance, index))
    return [index for _distance, index in sorted(found)[:CANDIDATES]]


def _pos(box, size):
    width, height = size
    return '({},{},{},{})'.format(round(box[0] * 1000 / width), round(box[1] * 1000 / height),
                                  round(box[2] * 1000 / width), round(box[3] * 1000 / height))


def _short(text, limit=220):
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:140] + ' … ' + text[-70:]


TASK = (
    'The attached image is a newspaper page. It was split into headlines (H) and text blocks (B). Positions are '
    'x1,y1,x2,y2 in 0-1000 page coordinates; the text comes from OCR and may contain errors (long blocks are '
    'shortened with "…"). Look at the image to see which columns, frames and colored boxes belong together.\n\n'
    'For every text block decide which headline\'s article it belongs to. Choose only from the block\'s candidates '
    '(listed nearest first), or "none" for photo captions, names under portrait photos, bylines, pull quotes, ads, '
    'tables, weather, page furniture and text printed inside photos. Use the meaning: a block often continues the '
    'sentence where another block of the same article stopped, and an article\'s body is about its headline. The first '
    'word(s) of an article\'s body are often printed in capitals (e.g. "TÜRK Tıbbi", "PROF. Dr.").\n\n'
    'For every headline give "text": only the headline words with OCR errors corrected (keep the wording, do not '
    'translate, never add body text even if the OCR text of the headline contains some), and '
    '"skip": true when it is not an article headline (section name, logo, date, text inside a photo or an ad, pull '
    'quote, photo caption, a stray line of body text). A headline printed over several lines may have been split into '
    'several H entries, and a kicker or deck belongs to the headline below it: for each such part give "join": "H<n>" '
    'naming the main part, so that every article has exactly one main headline. Assign body blocks to the main part.\n\n'
    'Answer only with JSON: {"blocks": {"B0": "H3", "B1": "none", ...}, '
    '"headlines": {"H0": {"text": "...", "skip": false}, "H1": {"join": "H0"}, ...}}')


def assign_prompt(heads, bodies, options, size):
    lines = [TASK, '', 'HEADLINES:']
    lines += [f'H{i} {_pos(head["box"], size)} {_short(head["text"], 160)}' for i, head in enumerate(heads)]
    lines += ['', 'TEXT BLOCKS:']
    for j, block in enumerate(bodies):
        names = ', '.join(f'H{i}' for i in options[j]) or '-'
        lines.append(f'B{j} {_pos(block["box"], size)} candidates: {names} | {_short(block["text"])}')
    return '\n'.join(lines)


def parse_json(text):
    """Yanittaki ilk JSON nesnesi; arkasindaki fazlaliklar (gemma bazen bir '}' fazla yaziyor) yok sayilir, eksik
    kalan son kapanis ayraclari (bazen de bir eksik yaziyor) tamamlanir."""
    text = _FENCE.sub('', str(text or '').strip())
    start = text.find('{')
    if start < 0:
        raise ValueError('Modelin yanıtında JSON yok.')
    text = text[start:]
    for extra in ('', '}', '}}'):
        try:
            value, _end = json.JSONDecoder().raw_decode(text + extra)
            break
        except json.JSONDecodeError as error:
            failure = error
    else:
        raise failure
    if not isinstance(value, dict):
        raise ValueError('Modelin yanıtı beklenen biçimde değil.')
    return value


def _ref(value, prefix, count):
    match = re.fullmatch(prefix + r'(\d+)', str(value or '').strip(), flags=re.I)
    if match and int(match.group(1)) < count:
        return int(match.group(1))
    return None


def parse_assignment(text, heads, bodies, options):
    """Yanit -> (owner, titles, skip, join): owner[j] baslik dizini ya da None (yalnizca adaylardan),
    titles {i: metin}, skip {i}, join {i: hedef i}."""
    data = parse_json(text)
    marks = data.get('blocks') if isinstance(data.get('blocks'), dict) else {}
    titles, skip, join = {}, set(), {}
    info = data.get('headlines') if isinstance(data.get('headlines'), dict) else {}
    for i in range(len(heads)):
        item = info.get(f'H{i}')
        if not isinstance(item, dict):
            continue
        target = _ref(item.get('join'), 'H', len(heads))
        if target is not None and target != i:
            join[i] = target
        elif item.get('skip') is True:
            skip.add(i)
        text = ' '.join(str(item.get('text') or '').split())
        if text:
            titles[i] = text
    owner = []
    for j in range(len(bodies)):
        head = _ref(marks.get(f'B{j}'), 'H', len(heads))
        if head is not None and head not in options[j]:
            # aday disi secim (metinde gecen ama uzaktaki bir basliga kayma): atlanmamis en yakin aday
            head = next((i for i in options[j] if i not in skip and _root(i, join) not in skip), None)
        owner.append(head)
    return owner, titles, skip, join


def _root(index, join):
    seen = set()
    while index in join and index not in seen:
        seen.add(index)
        index = join[index]
    return index


def column_boxes(members, others, body):
    """Makalenin bloklari sutun sutun birlesir (Tesseract'in atladigi satirlar da kutuya girer); birlesik kutu
    baska bir blogun ustune binerse parca ayri kalir. Okuma sirasi: soldan saga sutunlar, sutunda yukaridan asagi."""
    columns = []
    for box in sorted(members, key=lambda b: (b[1], b[0])):
        for column in columns:
            span = gazete._union(column)
            overlap = min(span[2], box[2]) - max(span[0], box[0])
            whole = gazete._union(column + [box])
            if overlap > 0.5 * min(box[2] - box[0], span[2] - span[0]) \
                    and not any(gazete._overlaps(whole, other) for other in others):
                column.append(box)
                break
        else:
            columns.append([box])
    boxes = sorted((gazete._union(column) for column in columns), key=lambda b: (round(b[0] / (3 * body)), b[1]))
    # ust uste binen kutular ayni satirlari iki kez okutuyordu: sonraki kutunun ust kenari oncekinin altina iner
    for index, box in enumerate(boxes):
        for earlier in boxes[:index]:
            if gazete._overlaps(earlier, box) and earlier[1] < box[1] < earlier[3] < box[3]:
                box[1] = earlier[3]
    return boxes


def heads_of(blocks):
    """Baslik parcalari yalnizca kesin durumda birlesir: ayni boyda ve ayni satirda yan yana ya da hemen alt satirda.
    gazete._heads birlesik kutuyu buyuterek komsu basliklari da zincirleme yutuyordu; gerisini dil modeli 'join'
    ile birlestirir."""
    merged = []
    for block in sorted((b for b in blocks if b['head']), key=lambda b: (b['box'][1], b['box'][0])):
        box, size = block['box'], block['size']
        for head in merged:
            # olculen boy satirdan satira cok oynuyor (buyuk harf, kuyruklu harfler): alt satirda iki kat serbest
            last, last_size = head['last'], head['size']
            small, ratio = min(size, last_size), max(size, last_size) / max(1, min(size, last_size))
            below = (ratio < 2 and -0.3 * small < box[1] - last[3] < 0.5 * small
                     and min(box[2], last[2]) - max(box[0], last[0]) > 0.5 * min(box[2] - box[0], last[2] - last[0]))
            beside = (ratio < 1.25
                      and min(box[3], last[3]) - max(box[1], last[1]) > 0.5 * min(box[3] - box[1], last[3] - last[1])
                      and -0.3 * small < box[0] - last[2] < small)
            if below or beside:
                head['box'] = gazete._union([head['box'], box])
                head['text'] += ' ' + block['text']
                head['last'] = box
                break
        else:
            merged.append({'box': list(box), 'size': size, 'text': block['text'], 'last': box})
    return [{'box': head['box'], 'size': head['size'], 'text': head['text']} for head in merged]


def title_of(members, root, heads, titles):
    """Baslik parcalari (ust bilgi + baslik) yukaridan asagi '<ust>: <baslik>'; model kok basliga parcayi zaten
    yazdiysa tekrar eklenmez."""
    main = titles.get(root) or heads[root]['text']
    parts = []
    for index in sorted(members, key=lambda i: (heads[i]['box'][1], heads[i]['box'][0])):
        text = main if index == root else titles.get(index) or heads[index]['text']
        key = ' '.join(text.casefold().split())
        if index != root and (key in ' '.join(main.casefold().split())
                              or any(key == ' '.join(p.casefold().split()) for p in parts)):
            continue
        parts.append(text)
    return ': '.join(part.rstrip(':') for part in parts)


PAGE_SIDE = 1536       # dil modeline giden sayfa goruntusunun uzun kenari


def page_png(image):
    small = image.copy()
    small.thumbnail((PAGE_SIDE, PAGE_SIDE))
    return gazete._png(small)


def near(part, main):
    """Baslik parcasi ana basliga bitisik mi: aradaki bosluk iki basliktan buyugunun boyunun iki katini gecmez.
    Model spor sayfasinda sayfanin obur ucundaki basliklari manset birlestiriyordu."""
    a, b = part['box'], main['box']
    gap = max(0, max(a[0], b[0]) - min(a[2], b[2])) + max(0, max(a[1], b[1]) - min(a[3], b[3]))
    return gap <= 2 * max(part['size'], main['size'])


def merge_decks(groups, members_of, heads, roots, skip=()):
    """Basligin hemen altindaki daha kucuk, yatayda onun altinda kalan 'baslik' spot cumlesidir: dil modeli onu
    ayri makale yapip govdeyi ona veriyordu. Spotun govdesi ana makaleye katilir, spot ana makalenin ilk govde
    kutusu olur. roots: baska basliga 'join' edilmemis basliklar (atlananlar haric). groups ve members_of
    yerinde degisir; donen {ana kok: [spot basliklari]}."""
    roots = [i for i in roots if i not in skip]
    merged = set()
    decks = {}
    for root in sorted(roots, key=lambda i: heads[i]['box'][1]):
        if root in merged:
            continue
        top = gazete._union([heads[i]['box'] for i in members_of.get(root, [root])])
        size = heads[root]['size']
        for other in sorted(groups, key=lambda i: heads[i]['box'][1]):
            if other == root or len(members_of[other]) > 1:
                continue
            box, small = heads[other]['box'], heads[other]['size']
            overlap = min(box[2], top[2]) - max(box[0], top[0])
            if small < 0.8 * size and -0.3 * small < box[1] - top[3] < 1.5 * small \
                    and overlap > 0.6 * (box[2] - box[0]):
                # ana basliga govde verilmemis olabilir: model govdeyi hep spota veriyordu
                groups[root] = groups.get(root, []) + groups.pop(other)
                members_of.setdefault(root, [root])
                members_of.pop(other)
                merged.add(other)
                decks.setdefault(root, []).append(other)
    return decks


def articles(blocks, body, size, ask, seps=(), log=print, image=None):
    """Bloklar (block['text'] OCR modelinden) -> [{head, title, boxes, chars}] dil modelinin baglamasiyla.
    ask(istem, png) -> yanit; png sayfanin kucuk goruntusu (gorsel model duzeni gorur). Yanit okunamazsa ValueError."""
    heads = heads_of(blocks)
    bodies = [b for b in blocks if not b['head'] and letters(b['text']) >= MIN_LETTERS]
    options = [candidates(b, heads, body, size[0], seps) for b in bodies]
    if not heads or not bodies:
        return []
    prompt = assign_prompt(heads, bodies, options, size)
    png = page_png(image) if image is not None else None
    try:
        answer = parse_assignment(ask(prompt, png), heads, bodies, options)
    except ValueError as error:    # bozuk JSON (virgul eksik vb.): bir kez daha sorulur
        log(f'Gazete: dil modelinin yanıtı okunamadı, yeniden soruluyor ({error}).')
        answer = parse_assignment(ask(prompt, png), heads, bodies, options)
    owner, titles, skip, join = answer
    join = {part: main for part, main in join.items() if near(heads[part], heads[main])}
    groups = {}
    for j, head in enumerate(owner):
        if head is None:
            continue
        # govde verilen baslik 'skip' dense de makaledir (model yarim okunan basligi atlayabiliyor)
        groups.setdefault(_root(head, join), []).append(bodies[j])
    members_of = {i: [i] + [k for k in join if _root(k, join) == i] for i in groups}
    decks = merge_decks(groups, members_of, heads, [i for i in range(len(heads)) if _root(i, join) == i], skip)
    result = []
    for root, members in groups.items():
        parts = sorted((heads[i] for i in members_of[root]), key=lambda h: (h['box'][1], h['box'][0]))
        own = {id(b) for b in members}
        others = [b['box'] for b in blocks if id(b) not in own and (b['head'] or letters(b['text']) >= 3)
                  and not any(gazete._overlaps(b['box'], h['box']) for h in parts)]
        result.append({'head': gazete._union([h['box'] for h in parts]),
                       'title': title_of(members_of[root], root, heads, titles),
                       'boxes': [heads[i]['box'] for i in decks.get(root, ())]
                       + column_boxes([b['box'] for b in members], others, body),
                       'chars': sum(len(b['text']) for b in members), 'titled': True})
    return result
