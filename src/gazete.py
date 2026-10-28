"""Gazete (F225): gunluk e-gazete sayisini sayfa sayfa makalelere ayirir, makaleleri okur ve seslendirir.

Gozu az goren biri basili gazeteyi telefonun kamerasiyla gosterir; telefon (ayri bir Android uygulamasi)
kareyi yerel agdaki Aktar'a gonderir, Aktar karenin hangi sayfanin hangi makalesi oldugunu bulur
(gazete_match) ve o makalenin onceden uretilmis sesini verir (gazete_server). Bu modulde sayi kaydi,
otomatik makale onerisi ve kutu kutu OCR var.

Calisma klasoru: APP_DIR/gazete/<sayi>/
  sayi.json         ad, sayfalar ve makaleler (kutular sayfa goruntusunun piksel koordinatlarinda)
  sayfalar/0001.jpg sayfa goruntuleri (PDF'den ya da goruntu klasorunden)
  ocr/0001.tsv      tam sayfa Tesseract kelime konumlari (onbellek; makale onerisi icin)
  ocr/0001.half.tsv 1/2 boyutta seyrek tarama (buyuk ve serif basliklar; tam taramada kaciyor)
  ocr/0001.<model>.json OCR modelinin blok okumalari (F226, gazete_model)
  ses/<makale>-<anahtar>.mp3

Tam sayfa OCR gazete sayfasinda sutunlari ve fotograf ici yazilari karistirir; makale metni bu yuzden
her kutu ayri kirpilip okunarak cikarilir (bir kutu birden cok sutun kapsayabilir). Otomatik oneri yalnizca baslangictir:
kutular Gazete sayfasinda elle duzeltilir (birlestir, bol, ciz, sil).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import statistics
import threading
from datetime import date
from pathlib import Path

import app_core
import documents

FOLDER = 'gazete'
ISSUE_FILE = 'sayi.json'
IMAGE_TYPES = ('.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff')
PAGE_LONG_SIDE = 3400        # PDF sayfasi bu boyda cizilir; daha buyuk goruntuler kucultulur
MAX_LONG_SIDE = 4200
LOW_FACTOR = 2               # buyuk baslik taramasi icin kucultme (1/4'te serif basliklar kaciyordu)
HEAD_RATIO = 1.7             # govde yazisinin bu katindan buyuk satir baslik sayilir
LOW_HEAD_RATIO = 1.9
MIN_CONF = 30
TSV = ('-c', 'tessedit_create_tsv=1')   # ozel --tessdata-dir ile 'tsv' yapilandirma dosyasi bulunmaz
_LOCK = threading.Lock()


# ---------------------------------------------------------------------- sayi kaydi
def root():
    return app_core.APP_DIR / FOLDER


def slug(name):
    text = re.sub(r'[^\w.-]+', '-', str(name or '').strip(), flags=re.UNICODE).strip('-.')
    return text[:60] or date.today().isoformat()


def issue_dir(name):
    folder = root() / slug(name)
    if folder.parent != root():
        raise ValueError('Geçersiz sayı adı.')
    return folder


def list_issues():
    """[{name, title, pages, articles, reviewed, voiced}] yeniden eskiye."""
    result = []
    base = root()
    if not base.is_dir():
        return result
    for folder in sorted(base.iterdir(), reverse=True):
        try:
            data = load(folder.name)
        except (OSError, ValueError):
            continue
        articles = data.get('articles', [])
        result.append({'name': folder.name, 'title': data.get('title') or folder.name, 'pages': len(data.get('pages', [])),
                       'articles': len(articles), 'reviewed': sum(1 for a in articles if a.get('reviewed')),
                       'voiced': sum(1 for a in articles if a.get('audio'))})
    return result


def load(name):
    path = issue_dir(name) / ISSUE_FILE
    if not path.is_file():
        raise ValueError('Sayı bulunamadı: ' + str(name))
    return json.loads(path.read_text(encoding='utf-8'))


def save(name, data):
    folder = issue_dir(name)
    with _LOCK:
        app_core.save_json(folder / ISSUE_FILE, data)


def page_path(name, page):
    return issue_dir(name) / 'sayfalar' / f'{int(page):04d}.jpg'


def page_number(path):
    """Dosya adindaki sayfa sirasi: e-gazete goruntulerinde ad '11709<sayfa-1>jpg-...' bicimindedir;
    adin basindaki rakamlar sayi olarak siralanir (117099 < 1170910)."""
    match = re.match(r'\d+', Path(path).name)
    return (int(match.group()) if match else float('inf'), Path(path).name.casefold())


def source_pages(source):
    """Kaynaktaki sayfalar: PDF ise ('pdf', yol, sayfa sayisi), klasor ise ('images', [goruntuler])."""
    source = Path(source)
    if source.is_file() and source.suffix.lower() == '.pdf':
        import pdf_book
        return 'pdf', source, pdf_book.page_count(source)
    if source.is_dir():
        images = sorted((p for p in source.iterdir() if p.suffix.lower() in IMAGE_TYPES), key=page_number)
        if not images:
            raise ValueError('Klasörde sayfa görüntüsü yok: ' + str(source))
        return 'images', images, len(images)
    raise ValueError('Gazete PDF dosyası ya da sayfa görüntüleri klasörü seçin.')


def _fit(image, long_side):
    from PIL import Image
    scale = long_side / max(image.size)
    if scale < 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    return image


def create(source, name=None, title=None, progress=None, cancelled=None):
    """Sayiyi kaydeder: sayfa goruntuleri sayfalar/ altina yazilir. Ayni adli sayi varsa sayfalari
    yenilenir, makaleleri korunur. Donen: sayi adi."""
    from PIL import Image
    kind, pages, count = source_pages(source)
    source = Path(source)
    name = slug(name or (source.stem if kind == 'pdf' else source.name))
    folder = issue_dir(name)
    (folder / 'sayfalar').mkdir(parents=True, exist_ok=True)
    try:
        data = load(name)
    except ValueError:
        data = {'name': name, 'title': title or name, 'created': date.today().isoformat(), 'language': 'tr',
                'articles': []}
    data['source'] = str(source)
    data['pages'] = []
    document = None
    if kind == 'pdf':
        import pdf_book
        document = documents.open_pdf(source)
    try:
        for index in range(count):
            if cancelled and cancelled():
                raise app_core.GracefulStop('Durduruldu.')
            if kind == 'pdf':
                image = pdf_book.page_images(document, index, PAGE_LONG_SIDE)[0]
            else:
                with Image.open(pages[index]) as opened:
                    image = opened.convert('RGB')
            image = _fit(image, MAX_LONG_SIDE)
            target = page_path(name, index + 1)
            image.save(target, 'JPEG', quality=92)
            data['pages'].append({'page': index + 1, 'width': image.width, 'height': image.height})
            if progress:
                progress(index + 1, count)
    finally:
        if document is not None:
            with documents._PDFIUM:
                document.close()
    if title:
        data['title'] = title
    save(name, data)
    return name


def delete(name):
    folder = issue_dir(name)
    if folder.is_dir():
        shutil.rmtree(folder)


# ---------------------------------------------------------------------- Tesseract
def ocr_reader(cfg=None, log=print, psm='3', tsv=True):
    """(png baytlari) -> metin ya da TSV; gazete Turkce okunur."""
    cfg = dict(cfg or app_core.load_config())
    return documents.tesseract_reader(cfg, log, lang='tur', psm=psm, configs=TSV if tsv else ())


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


def parse_tsv(text, factor=1.0):
    """Tesseract TSV -> kelime satirlari (sozluk). factor: kucultulmus goruntu koordinatlarini buyutur."""
    rows = []
    for row in csv.DictReader(io.StringIO(text), delimiter='\t', quoting=csv.QUOTE_NONE):
        try:
            row = dict(row, **{key: round(int(row[key]) * factor) for key in ('left', 'top', 'width', 'height')})
            row['conf'] = float(row['conf'])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append(row)
    return rows


def _cached(path, produce):
    path = Path(path)
    if path.is_file():
        return path.read_text(encoding='utf-8')
    text = produce()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return text


# ---------------------------------------------------------------------- makale onerisi
def lines_of(rows, split=True, min_conf=MIN_CONF):
    """Kelimelerden satirlar: [{box, size, text}]. split: satirda genis bosluk varsa (Tesseract komsu
    sutunlari tek satir okuyabilir) satir ikiye ayrilir. size: uc harften uzun kelimelerin yuksekligi."""
    groups = {}
    for row in rows:
        if str(row.get('level')) != '5':
            continue
        text = (row.get('text') or '').strip()
        if not text or row['conf'] < min_conf:
            continue
        key = (row['block_num'], row['par_num'], row['line_num'])
        groups.setdefault(key, []).append((row['left'], row['top'], row['width'], row['height'], text))
    parts = []
    for words in groups.values():
        words.sort()
        height = statistics.median(word[3] for word in words)
        part = [words[0]]
        for word in words[1:]:
            last = part[-1]
            # dev baslik ile yanindaki govde sutunu tek satir okunabilir: yukseklik iki kattan cok degisirse bolunur
            jump = len(word[4]) > 2 and len(last[4]) > 2 and max(word[3], last[3]) > 2 * min(word[3], last[3])
            if split and (word[0] - (last[0] + last[2]) > 1.6 * height or jump):
                parts.append(part)
                part = []
            part.append(word)
        parts.append(part)
    lines = []
    for words in parts:
        if sum(sum(char.isalpha() for char in word[4]) for word in words) < 3:
            continue
        heights = [word[3] for word in words if len(word[4]) > 2] or [word[3] for word in words]
        lines.append({'box': [min(w[0] for w in words), min(w[1] for w in words),
                              max(w[0] + w[2] for w in words), max(w[1] + w[3] for w in words)],
                      'size': statistics.median(heights), 'text': ' '.join(word[4] for word in words)})
    return lines


def body_size(lines):
    """Govde yazisinin boyu: uzun satirlarin ortanca yuksekligi."""
    sizes = [line['size'] for line in lines if len(line['text']) > 15]
    return statistics.median(sizes) if sizes else 20.0


def blocks_of(lines, body):
    """Alt alta, ayni sutunda, ayni boydaki satirlar tek blok. Blok: {box, size, head, lines, text}."""
    blocks = []
    for line in sorted(lines, key=lambda item: (item['box'][1], item['box'][0])):
        x1, y1, x2, y2 = line['box']
        target = None
        for block in blocks:
            bx1, _by1, bx2, _by2 = block['box']
            last = block['lines'][-1]
            same = abs(line['size'] - block['size']) < 0.25 * max(line['size'], block['size'])
            gap = y1 - last['box'][3]
            overlap = min(x2, bx2) - max(x1, bx1)
            if same and -0.5 * line['size'] < gap < 1.2 * line['size'] and overlap > 0.6 * min(x2 - x1, bx2 - bx1):
                target = block
                break
        if target is None:
            blocks.append({'box': list(line['box']), 'size': line['size'], 'lines': [line]})
            continue
        target['lines'].append(line)
        box = target['box']
        target['box'] = [min(box[0], x1), min(box[1], y1), max(box[2], x2), max(box[3], y2)]
        target['size'] = statistics.median(item['size'] for item in target['lines'])
    for block in blocks:
        block['head'] = block['size'] > HEAD_RATIO * body
        block['text'] = ' '.join(line['text'] for line in block['lines'])
    return blocks


def _overlaps(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _common(a, b):
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def add_low_heads(blocks, lines, body, prefer=False):
    """Kucuk taramada bulunan buyuk satirlardan, tam taramadaki bir basligin ustune binmeyenler baslik olur.
    Seyrek tarama alt alta govde satirlarini tek buyuk satir sanabilir: alaninin ucte birinden fazlasi govde
    bloguyla ortusen satir baslik sayilmaz."""
    ratio = HEAD_RATIO if prefer else LOW_HEAD_RATIO   # modelle okunurken yanlis baslik dil modelinde elenir
    for line in lines:
        if line['size'] <= ratio * body or len(line['text']) < 4:
            continue
        covered = sum(_common(block['box'], line['box']) for block in blocks if not block['head'])
        if covered > _area(line['box']) / 3:
            continue
        clash = [block for block in blocks if block['head'] and _overlaps(block['box'], line['box'])]
        if clash and not prefer:
            continue
        # prefer: tam taramanin baslik blogu dev basligi yanindaki sutunlarla birlestirebiliyor; seyrek taramanin
        # satiri yerine gecer (seyrek taramanin alt alta iki satiri birbirine hafifce binebilir, ikisi de kalir)
        for block in clash:
            if not block.get('low'):
                blocks.remove(block)
        blocks.append({'box': list(line['box']), 'size': line['size'], 'lines': [line], 'head': True,
                       'text': line['text'], 'low': True})
    return blocks


def separators(image, body):
    """Uzun yatay kenarlar (cizgi, cerceve, renkli kutu siniri): [(y, x1, x2)]. OpenCV yoksa bos."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []
    gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
    edges = cv2.dilate(cv2.Canny(gray, 60, 160), np.ones((3, 1), np.uint8))
    length = max(30, int(12 * body))
    horizontal = cv2.morphologyEx(edges, cv2.MORPH_OPEN, np.ones((1, length), np.uint8))
    count, _labels, stats, _centers = cv2.connectedComponentsWithStats(horizontal)
    return [(float(y + height / 2), int(x), int(x + width)) for x, y, width, height, _area in stats[1:count]
            if height < 3 * body]


def _heads(blocks):
    """Ust uste ya da yan yana baslik parcalari tek baslik: [{box, size, text}]."""
    merged = []
    for block in sorted((b for b in blocks if b['head']), key=lambda b: (b['box'][1], b['box'][0])):
        box = block['box']
        for head in merged:
            other = head['box']
            below = (box[1] - other[3] < head['size']
                     and min(box[2], other[2]) - max(box[0], other[0]) > 0.3 * (box[2] - box[0]))
            beside = (min(box[3], other[3]) - max(box[1], other[1]) > 0.5 * (box[3] - box[1])
                      and -head['size'] < box[0] - other[2] < 2.5 * head['size'])
            if below or beside:
                head['box'] = [min(other[0], box[0]), min(other[1], box[1]), max(other[2], box[2]), max(other[3], box[3])]
                head['text'] += ' ' + block['text']
                break
        else:
            merged.append({'box': list(box), 'size': block['size'], 'text': block['text']})
    return merged


def articles_of(blocks, body, seps=()):
    """Govde bloklari en yakin ustteki basliga baglanir: blogun ortasi basligin yatay araliginda olmali ve
    aralarinda ayirici kenar bulunmamali. Basliksiz bloklar dusurulur. [{head, title, boxes}]"""
    heads = _heads(blocks)
    owned = [[] for _ in heads]
    for block in blocks:
        if block['head']:
            continue
        bx1, by1, bx2, _by2 = block['box']
        middle = (bx1 + bx2) / 2
        best = None
        for index, head in enumerate(heads):
            hx1, hy1, hx2, hy2 = head['box']
            if hy1 > by1 + body or not (hx1 - 2 * body <= middle <= hx2 + 2 * body):
                continue
            low, high = max(hx1, bx1), min(hx2, bx2)
            if high <= low:
                low, high = bx1, bx2
            if any(hy2 + 0.3 * body < y < by1 - 0.3 * body and min(x2, high) - max(x1, low) > 0.5 * (high - low)
                   for y, x1, x2 in seps):
                continue
            distance = by1 - hy2
            if best is None or distance < best[0]:
                best = (distance, index)
        if best is not None:
            owned[best[1]].append(block)
    articles = []
    for index, (head, members) in enumerate(zip(heads, owned)):
        # okuma sirasi: sutun sutun (soldan saga), sutun icinde yukaridan asagi
        members.sort(key=lambda b: (round(b['box'][0] / (3 * body)), b['box'][1]))
        boxes = [b['box'] for b in members]
        others = [b['box'] for other, group in enumerate(owned) if other != index for b in group]
        whole = _union(boxes)
        # Govde tek cerceveye sigiyorsa (baska makalenin bloguna binmeden) tek kutu: Tesseract cercevedeki
        # sutunlari kendisi ayirir; parca bloklar satir kacirir.
        if whole and not any(_overlaps(whole, box) for box in others):
            boxes = [whole]
        articles.append({'head': head['box'], 'title': head['text'], 'boxes': boxes,
                         'chars': sum(len(b['text']) for b in members)})
    return articles


def _union(boxes):
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def propose(name, page, reader=None, low_reader=None, log=print, read=None, read_name='', ask=None, layout=None):
    """Sayfanin otomatik makale onerisi (OCR onbellekli). Govde metni 120 harften kisa olan oneriler
    (fotograf ici yazilar, reklam) atilir.

    F226: read (png -> metin, OCR modeli; read_name onbellek adi) verilirse bloklar modelle okunur; ask (istem ->
    yanit, dil modeli) verilirse bloklar basliklara modelle baglanir (gazete_model). Model yaniti
    kullanilamazsa kurallara donulur. Modelle bulunan onerilerde 'titled': baslik modelden, yeniden okunmaz.

    F227: layout (PIL goruntu -> bolgeler, gazete_layout.regions) verilirse bloklar yerlesim modelinin
    bolgelerinden kurulur (onbellek ocr/<sayfa>.layout.json); Tesseract yalnizca yazi boyunu ve fotograf ustu
    basliklari verir."""
    from PIL import Image
    import gazete_model
    folder = issue_dir(name)
    with Image.open(page_path(name, page)) as opened:
        image = opened.convert('RGB')
    reader = reader or ocr_reader(log=log)
    low_reader = low_reader or ocr_reader(log=log, psm='11')
    text = _cached(folder / 'ocr' / f'{page:04d}.tsv', lambda: reader(_png(image)))
    lines = lines_of(parse_tsv(text))
    body = body_size(lines)
    small = image.resize((image.width // LOW_FACTOR, image.height // LOW_FACTOR), Image.LANCZOS)
    low = _cached(folder / 'ocr' / f'{page:04d}.half.tsv', lambda: low_reader(_png(small)))
    low_lines = lines_of(parse_tsv(low, LOW_FACTOR), split=False, min_conf=10)
    if layout:
        import gazete_layout
        found = json.loads(_cached(folder / 'ocr' / f'{page:04d}.layout.json',
                                   lambda: json.dumps(layout(image), ensure_ascii=False)))
        blocks = gazete_layout.add_photo_heads(gazete_layout.blocks_of(found, lines, body, low_lines), low_lines, body, HEAD_RATIO)
    else:
        blocks = blocks_of(lines, body)
        add_low_heads(blocks, low_lines, body, prefer=bool(read))
    seps = separators(image, body)
    if read:
        path = folder / 'ocr' / f'{page:04d}.{slug(read_name or "model")}.json'
        try:
            cache = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cache = {}
        try:
            gazete_model.read_blocks(image, blocks, read, cache)
        finally:
            app_core.save_json(path, cache)
    if layout:
        import gazete_layout
        blocks = [block for block in blocks if block['head'] or not gazete_layout.listing_text(block['text'])]
    found = None
    if ask:
        try:
            found = gazete_model.articles(blocks, body, image.size, ask, seps, log, image)
        except (ValueError, RuntimeError, KeyError, TypeError) as error:
            log(f'UYARI: Gazete {page}. sayfa: dil modelinin bağlaması kullanılamadı, kurallarla bölünüyor ({error}).')
    if found is None:
        found = articles_of(blocks, body, seps)
    return [item for item in found if item['chars'] >= 120]


# ---------------------------------------------------------------------- makaleler
def new_id(data):
    used = {article['id'] for article in data.get('articles', [])}
    number = len(used) + 1
    while f'm{number}' in used:
        number += 1
    return f'm{number}'


def clean_box(box, page):
    """Kutuyu sayfa sinirlarina sigdirir; [x1, y1, x2, y2] tam sayi."""
    x1, y1, x2, y2 = (int(round(float(value))) for value in box)
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    width, height = page['width'], page['height']
    x1, x2 = max(0, min(width, x1)), max(0, min(width, x2))
    y1, y2 = max(0, min(height, y1)), max(0, min(height, y2))
    if x2 - x1 < 8 or y2 - y1 < 8:
        raise ValueError('Kutu çok küçük.')
    return [x1, y1, x2, y2]


def article_text(article):
    """Okunacak metin: elle duzeltilmis metin, yoksa OCR."""
    edited = article.get('edited')
    return edited if edited is not None else article.get('text', '')


def spoken(article):
    """Seslendirilecek metin: baslik, bos satir, govde."""
    title = ' '.join(str(article.get('title') or '').split())
    body = article_text(article).strip()
    return f'{title}.\n\n{body}' if title and body else title or body


HYPHEN_BREAK = re.compile(r'(\w)[-‐­]\s*\n\s*([a-zçğıöşü])')
STRAY = re.compile(r'^[^\wÇĞİÖŞÜçğıöşü“"‘(]+|[|_~]+')


def tidy(text):
    """Kutu OCR'inin satirlari: satir sonu tirelemesi birlesir ('yüz-\\nde' -> 'yüzde'), satirlar paragrafa
    katilir, bos satir paragraf sonudur; satir basindaki kirintilar silinir."""
    text = re.sub(r'\r\n?', '\n', str(text))
    text = HYPHEN_BREAK.sub(r'\1\2', text)
    text = re.sub(r'(\w-)[ \t]*\n[ \t]*(?=\w)', r'\1', text)   # 'Ankara-\nİstanbul': tire kalir, bosluk girmez
    paragraphs = []
    for chunk in re.split(r'\n\s*\n', text):
        lines = [STRAY.sub('', line).strip() for line in chunk.split('\n')]
        joined = ' '.join(line for line in lines if line)
        if sum(char.isalpha() for char in joined) >= 3:
            paragraphs.append(re.sub(r'\s+', ' ', joined))
    # Tesseract bloklar arasina her satirda bos satir koyabilir: noktalama ile bitmeyen paragraf sonrakine katilir
    merged = []
    for paragraph in paragraphs:
        if merged and not re.search(r'[.!?…:”"’)]$', merged[-1]):
            merged[-1] += ' ' + paragraph
        else:
            merged.append(paragraph)
    return '\n\n'.join(merged)


def read_box(image, box, reader, model=False):
    """Kutuyu kirpip okur. Kutu birden cok sutun kapsayabilir: Tesseract (psm 3) sutunlari kendisi ayirir;
    kenar payi, satir kutusunun kestigi harfleri geri getirir. model: OCR modeli (kirpinti uc kata kadar buyutulur)."""
    from PIL import Image
    x1, y1, x2, y2 = box
    margin = 12
    crop = image.crop((max(0, x1 - margin), max(0, y1 - margin), min(image.width, x2 + margin),
                       min(image.height, y2 + margin)))
    if model:
        import gazete_model
        factor = gazete_model.scale_for(None, crop.size)
        crop = crop.resize((round(crop.width * factor), round(crop.height * factor)), Image.LANCZOS)
    elif crop.height < 60:     # tek satirlik kucuk kutu: Tesseract buyutulunce daha iyi okur
        crop = crop.resize((crop.width * 2, crop.height * 2))
    return reader(_png(crop))


def read_article(name, article, reader=None, log=print, model=False, title=True):
    """Makalenin basligini ve kutularini ayri ayri okur; article['title'] (elle verilmediyse) ve
    article['text'] guncellenir. model: reader OCR modelidir. title=False: baslik okunmaz (modelin duzelttigi
    baslik kalir)."""
    from PIL import Image
    reader = reader or ocr_reader(log=log, psm='3', tsv=False)
    with Image.open(page_path(name, article['page'])) as opened:
        image = opened.convert('RGB')
    if title and article.get('head') and not article.get('title_edited'):
        heading = ' '.join(read_box(image, article['head'], reader, model).split())
        article['title'] = re.sub(r'^[^\wÇĞİÖŞÜçğıöşü“"‘\']+', '', heading)
    article['text'] = '\n\n'.join(part for part in (tidy(read_box(image, box, reader, model))
                                                    for box in article['boxes']) if part)
    article.pop('audio', None)
    return article


def article_at(data, page, x, y, reach=60):
    """(x, y) noktasindaki makale: kutularindan birinin icindeyse o, degilse `reach` piksel icindeki en yakin."""
    best = None
    for article in data.get('articles', []):
        if article.get('page') != page:
            continue
        for box in [article['head']] * bool(article.get('head')) + list(article.get('boxes', [])):
            dx = max(box[0] - x, 0, x - box[2])
            dy = max(box[1] - y, 0, y - box[3])
            distance = (dx * dx + dy * dy) ** 0.5
            if distance <= reach and (best is None or distance < best[0]):
                best = (distance, article)
    return best[1] if best else None


# ---------------------------------------------------------------------- ses
_NEXT = r'(?=["“‘(]?[A-ZÇĞİÖŞÜ0-9])'
SENTENCE_END = re.compile(r'(?<=[.!?…])\s+' + _NEXT + r'|(?<=[.!?…]["”’)])\s+' + _NEXT)


def sentences(text):
    """Metni cumlelere boler; paragraf sonlari (cumle dizinleri) ayrica doner."""
    result, breaks = [], []
    for paragraph in re.split(r'\n\s*\n', str(text)):
        paragraph = ' '.join(paragraph.split())
        if not paragraph:
            continue
        result.extend(part for part in SENTENCE_END.split(paragraph) if part.strip())
        breaks.append(len(result) - 1)
    return result, breaks


def audio_key(article, voice):
    return hashlib.sha1(f'{voice}\n{spoken(article)}'.encode('utf-8')).hexdigest()[:12]


def audio_path(name, article, voice):
    return issue_dir(name) / 'ses' / f'{article["id"]}-{audio_key(article, voice)}.mp3'


def audio_file(name, article):
    """Makalenin kayitli sesi (metni ya da ses degistiyse None)."""
    audio = article.get('audio')
    if not audio:
        return None
    path = issue_dir(name) / 'ses' / audio
    return path if path.is_file() else None


def prune_audio(name, data):
    """Hicbir makalenin kullanmadigi eski ses dosyalarini siler."""
    folder = issue_dir(name) / 'ses'
    if not folder.is_dir():
        return
    used = {article.get('audio') for article in data.get('articles', [])}
    for path in folder.glob('*.mp3'):
        if path.name not in used:
            try:
                path.unlink()
            except OSError:
                pass
