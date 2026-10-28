"""F227: gazete sayfasinin yerlesimi (baslik, govde, resim, tablo bolgeleri) PP-DocLayoutV3 ile.

Tesseract'in kelime kutularindan kurallarla kurulan bloklar renkli zemindeki basliklari kaciriyor, buyuk basligin
ilk harfini kirpiyor, tablo ve TV listelerini makale saniyordu. Belge yerlesimi icin egitilmis model bolgeleri
siniflariyla verir (GLM-OCR'in resmi akisi da once bu modelle bolge bulur). Fotograf ustune basilmis basliklari
model resmin parcasi sayar: onlar yine yarim boyutlu Tesseract taramasindan eklenir.

Model ONNX (~134 MB, Apache 2.0), ilk kullanimda APP_DIR/models/layout altina iner; onnxruntime, OpenCV ve numpy
gerekir. Cikarim CPU'da sayfa basina ~1 sn.
"""

import os
import re
import statistics
import threading
import urllib.request

from app_core import APP_DIR, GracefulStop

URL = 'https://huggingface.co/phungpx/PP-DocLayoutV3-ONNX/resolve/main/pp_doclayoutv3.onnx'
FILE = 'pp_doclayoutv3.onnx'
SIZE = 133739324
INPUT = 800             # model kare 800x800 girdi ister (en-boy korunmaz)
THRESHOLD = 0.4
LABELS = ('abstract', 'algorithm', 'aside_text', 'chart', 'content', 'formula', 'doc_title', 'figure_title',
          'footer', 'footer', 'footnote', 'formula_number', 'header', 'header', 'image', 'formula', 'number',
          'paragraph_title', 'reference', 'reference_content', 'seal', 'table', 'text', 'text', 'vision_footnote')
TITLES = ('doc_title', 'paragraph_title')
BODY = ('text', 'abstract', 'content', 'aside_text', 'reference_content')
SUBHEAD_RATIO = 1.25    # govde boyuna bu kadar yakin paragraph_title makale ici ara baslik: govdeye katilir
LISTING = re.compile(r'\.{4,}|…{2,}|\b\d{1,2}[.:]\d{2}\b')   # program/fikstur satiri: saat ya da nokta doldurma
SAME_REGION = 0.7      # daha kucuk bolgenin bu kadari ortusuyorsa dusuk puanli olan atilir
_LOCK = threading.Lock()
_SESSION = None


def model_path():
    return APP_DIR / 'models' / 'layout' / FILE


def available():
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def ensure_model(log=print, progress=None, cancelled=None):
    """Model yoksa indirir (bir kez). progress(indirilen_bayt, toplam_bayt)."""
    target = model_path()
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix('.part')
    log('Sayfa yerleşim modeli indiriliyor (bir kez, 134 MB).')
    request = urllib.request.Request(URL, headers={'User-Agent': 'Aktar'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(part, 'wb') as out:
            total = int(response.headers.get('Content-Length') or SIZE)
            done = 0
            while True:
                if cancelled and cancelled():
                    raise GracefulStop('İndirme durduruldu.')
                block = response.read(1 << 20)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if progress:
                    progress(done, total)
    except GracefulStop:
        part.unlink(missing_ok=True)
        raise
    except OSError as error:
        part.unlink(missing_ok=True)
        raise RuntimeError(f'Sayfa yerleşim modeli indirilemedi: {error}') from None
    if part.stat().st_size != SIZE:
        part.unlink(missing_ok=True)
        raise RuntimeError('Sayfa yerleşim modeli eksik indi; yeniden deneyin.')
    os.replace(part, target)
    return target


def _session():
    global _SESSION
    with _LOCK:
        if _SESSION is None:
            import onnxruntime
            _SESSION = onnxruntime.InferenceSession(str(model_path()), providers=['CPUExecutionProvider'])
        return _SESSION


def unload():
    """Oturumu birakir (is bitince bellek geri verilir)."""
    global _SESSION
    with _LOCK:
        _SESSION = None


def _sigmoid(values):
    import numpy as np
    return 1.0 / (1.0 + np.exp(-np.clip(values.astype(np.float64), -60, 60)))


def decode(logits, boxes, order, width, height, threshold=THRESHOLD):
    """Model ciktisi -> [{label, score, box, order}] okuma sirasinda. logits (Q, C), boxes (Q, 4) cxcywh 0..1,
    order (Q, Q) okuma sirasi isaretcisi (transformers PPDocLayoutV3ImageProcessor ile ayni)."""
    import numpy as np
    scores = _sigmoid(order)
    votes = np.triu(scores, 1).sum(axis=0) + np.tril(1.0 - scores.T, -1).sum(axis=0)
    rank = np.empty(len(votes), dtype=np.int64)
    rank[np.argsort(votes, kind='stable')] = np.arange(len(votes))
    queries, classes = logits.shape
    flat = _sigmoid(logits).reshape(-1)
    found = []
    for index in np.argsort(-flat, kind='stable')[:queries]:
        if flat[index] < threshold:
            break
        query, label = divmod(int(index), classes)
        cx, cy, w, h = (float(value) for value in boxes[query])
        found.append({'label': LABELS[label] if label < len(LABELS) else str(label), 'score': round(float(flat[index]), 3),
                      'order': int(rank[query]),
                      'box': [round((cx - w / 2) * width), round((cy - h / 2) * height),
                              round((cx + w / 2) * width), round((cy + h / 2) * height)]})
    found.sort(key=lambda item: item['order'])
    return found


def regions(image, threshold=THRESHOLD):
    """PIL goruntusunun bolgeleri: [{label, score, box, order}]."""
    import cv2
    import numpy as np
    pixels = cv2.resize(np.asarray(image.convert('RGB')), (INPUT, INPUT), interpolation=cv2.INTER_CUBIC)
    batch = pixels.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
    session = _session()
    names = [output.name for output in session.get_outputs() if output.name != 'out_masks']
    out = dict(zip(names, session.run(names, {session.get_inputs()[0].name: batch})))
    return decode(out['logits'][0], out['pred_boxes'][0], out['order_logits'][0], image.width, image.height, threshold)


def _area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _common(a, b):
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def _inside(line, box):
    x1, y1, x2, y2 = line['box']
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _size(lines, weighted=False):
    """Satirlarin yazi boyu ortancasi. weighted: alana gore agirlikli (baslik kutusu yandaki sutunun birkac
    kucuk satirini da icine alabiliyor; dev baslik satiri alani kaplar)."""
    lines = [line for line in lines if len(line['text']) > 2] or list(lines)
    if not lines:
        return 0
    if not weighted:
        return statistics.median(line['size'] for line in lines)
    ranked = sorted(lines, key=lambda line: line['size'])
    half, total = sum(_area(line['box']) for line in ranked) / 2, 0
    for line in ranked:
        total += _area(line['box'])
        if total >= half:
            return line['size']
    return ranked[-1]['size']


def listing(lines):
    """TV programi, fikstur, sonuc listesi: satirlarin yarisindan cogu saat ya da nokta doldurma tasiyor.
    Yerlesim modeli bunlari duz metin sayiyor (cogu kez tek satirlik bloklar), makaleye karisiyordu."""
    return bool(lines) and sum(bool(LISTING.search(line['text'])) for line in lines) > len(lines) / 2


def listing_text(text):
    """Okunmus blok metni liste mi: saat ya da nokta doldurma sik (her ~40 harfte bir). Tesseract liste
    satirlarini dusuk guvenle atabildigi icin satir denetimi bos kalabiliyor; OCR modelinin metniyle yeniden."""
    hits = len(LISTING.findall(text or ''))
    return hits >= 2 and hits * 40 >= len(text)


def blocks_of(found, lines, body, low_lines=()):
    """Bolgelerden gazete bloklari ({box, size, head, lines, text}; gazete.blocks_of ile ayni bicim). Yazi boyu
    bolgedeki Tesseract satirlarindan olculur; basliklarda alana gore agirlikli ve tam boyutlu tarama dev basligi
    kucuk parcalar halinde okuyabildigi icin yarim boyutlu taramanin olcusu buyukse o alinir. Resim, tablo, ust/alt bilgi ve fotograf
    altlari blok olmaz."""
    kept = []
    for region in sorted(found, key=lambda item: -item['score']):
        if region['label'] not in TITLES + BODY:
            continue
        box = region['box']
        if any(_common(box, other['box']) > SAME_REGION * min(_area(box), _area(other['box'])) for other in kept):
            continue
        kept.append(region)
    kept.sort(key=lambda item: item['order'])
    blocks = []
    for region in kept:
        box = region['box']
        inner = sorted((line for line in lines if _inside(line, box)), key=lambda line: (line['box'][1], line['box'][0]))
        title = region['label'] in TITLES
        size = _size(inner, weighted=title)
        if title:
            low = [line for line in low_lines if _inside(line, box)]
            size = max(size, _size(low, weighted=True)) or 0.7 * (box[3] - box[1])
        size = size or body
        head = title and size > SUBHEAD_RATIO * body
        if not head and listing(inner):
            continue
        blocks.append({'box': list(box), 'size': size, 'head': head, 'lines': inner, 'label': region['label'],
                       'text': ' '.join(line['text'] for line in inner)})
    return blocks


def add_photo_heads(blocks, low_lines, body, head_ratio):
    """Fotograf ustune basilmis buyuk basliklar (model onlari resmin parcasi sayar) yarim boyutlu taramadan:
    hicbir bloga binmeyen, govdeden belirgin buyuk satirlar baslik olur."""
    for line in low_lines:
        if line['size'] <= head_ratio * body or len(line['text']) < 4:
            continue
        if any(_common(block['box'], line['box']) > 0.2 * _area(line['box']) for block in blocks):
            continue
        blocks.append({'box': list(line['box']), 'size': line['size'], 'head': True, 'lines': [line],
                       'text': line['text'], 'low': True, 'label': 'photo_title'})
    return blocks
