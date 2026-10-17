"""Taranmis PDF'den EPUB (F138): sayfa okuma (OCR), temizleme, bolumleme, EPUB yazma.

Uretilen EPUB ya Okuma'ya eklenir (Turkce kitaplar, sesli okuma) ya da Kitap Cevir'de acilir
(Ingilizce kitaplar). Ceviri motoruna (book_core) dokunulmaz; buradaki is yalnizca temiz bir kaynak
EPUB uretmektir.

Calisma klasoru: <cikti klasoru>/<PDF adi>-pdf/
  ocr/0012.txt      sayfa 12'nin metni (cift sayfa taramada 0012a.txt ve 0012b.txt)
  <PDF adi>.epub    uretilen kitap
OCR sonuclari sayfa sayfa saklanir; is yarida kalirsa kaldigi sayfadan surer.

- Cift sayfa: genisligi yuksekliginden belirgin buyuk sayfa (acik kitap taramasi) ortadan ikiye
  bolunup sol, sag sirasiyla okunur.
- Metin katmani olan sayfa (dijital PDF) OCR'siz okunur.
- Temizleme (kurallarla, model kullanmadan): tekrar eden ust/alt bilgiler ve sayfa numaralari,
  satir/sayfa sonunda bolunmus kelimeler, sayfalar arasinda yarim kalan paragraflar.
- Bolumleme: anlamli PDF icindekileri, yoksa baslik satirlari, yoksa sabit sayfa parcalari.
"""
from __future__ import annotations

import html
import re
import unicodedata
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import documents

WORK_SUFFIX = '-pdf'
SPREAD_RATIO = 1.2          # genislik/yukseklik bundan buyukse cift sayfa taramasi
RENDER_LONG_SIDE = 2000     # tek sayfanin uzun kenari (piksel)
TEXT_LAYER_CHARS = 200      # bu kadar metin katmani olan sayfa OCR'siz okunur
COVER_LONG_SIDE = 1400


# ---------------------------------------------------------------------- sayfa okuma
def work_dir(pdf, parent=None):
    pdf = Path(pdf)
    return Path(parent or pdf.parent) / (pdf.stem + WORK_SUFFIX)


def _png(image):
    import io
    buffer = io.BytesIO()
    image.save(buffer, 'PNG', compress_level=6)
    return buffer.getvalue()


def page_images(document, index, long_side=RENDER_LONG_SIDE):
    """Sayfanin okunacak goruntuleri (Pillow): tek sayfa [goruntu], cift sayfa taramasi [sol, sag]."""
    with documents._PDFIUM:
        page = document[index]
        try:
            width, height = page.get_size()
            spread = width > height * SPREAD_RATIO
            side = long_side * (2 if spread else 1)
            image = page.render(scale=side / max(width, height, 1.0), fill_color=(255, 255, 255, 255)).to_pil()
        finally:
            page.close()
    image = image.convert('RGB')
    if not spread:
        return [image]
    middle = image.width // 2
    return [image.crop((0, 0, middle, image.height)), image.crop((middle, 0, image.width, image.height))]


def _text_layer(document, index):
    with documents._PDFIUM:
        page = document[index]
        try:
            textpage = page.get_textpage()
            try:
                return textpage.get_text_range()
            finally:
                textpage.close()
        finally:
            page.close()


def page_count(pdf):
    document = documents.open_pdf(pdf)
    try:
        with documents._PDFIUM:
            return len(document)
    finally:
        with documents._PDFIUM:
            document.close()


def sample_language(pdf, read):
    """Kitabin dili ('tr'/'en'): ortadaki uc sayfa okunup bakilir. Tesseract'a kitabin tamami icin tek dil
    ('tur' ya da 'eng') verilsin diye; 'tur+eng' ile Turkce harfler bozulabiliyor."""
    count = page_count(pdf)
    document = documents.open_pdf(pdf)
    try:
        texts = [read(_png(image), documents.OCR_PROMPT)
                 for index in sorted({int(count * share) for share in (0.3, 0.5, 0.7)})
                 for image in page_images(document, index)]
    finally:
        with documents._PDFIUM:
            document.close()
    return detect_language('\n'.join(texts))


def _newlines(text):
    """Tesseract '\\r\\n', onceki surumun onbellegi '\\r\\r\\n' yazabilir: hepsi tek '\\n' olur."""
    return re.sub(r'\r+\n?', '\n', str(text))


def _cache_names(index, parts):
    base = f'{index + 1:04d}'
    return [base + '.txt'] if parts == 1 else [base + letter + '.txt' for letter in 'ab'[:parts]]


def read_pages(pdf, work, read, progress=None, cancelled=None, log=print):
    """Sayfa metinleri (liste, sayfa basina bir metin). `read(png, istem) -> metin` (library.vision_reader).
    Okunan her sayfa work/ocr altina yazilir; tekrar calistirmada okunmus sayfalar atlanir."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    folder = Path(work) / 'ocr'
    folder.mkdir(parents=True, exist_ok=True)
    workers = max(1, int(getattr(read, 'workers', 1)))   # Tesseract: cekirdek sayisi kadar paralel
    document = documents.open_pdf(pdf)
    pool = ThreadPoolExecutor(workers)
    try:
        with documents._PDFIUM:
            count = len(document)
        texts = [None] * count
        running = {}
        done = 0

        def finish(index, parts):
            nonlocal done
            parts = [_newlines(text) for text in parts]
            for name, text in zip(_cache_names(index, len(parts)), parts):
                (folder / name).write_bytes(text.encode('utf-8'))   # satir sonu olduğu gibi (\r eklenmez)
            texts[index] = '\n\n'.join(parts)
            done += 1
            if progress:
                progress(done, count)

        def collect(block):
            completed, _pending = wait(running, return_when=FIRST_COMPLETED) if block else (
                [future for future in running if future.done()], None)
            for future in completed:
                index, total = running.pop(future)
                parts = future.result()
                finish(index, parts)

        def read_parts(images):
            return [read(_png(image), documents.OCR_PROMPT) for image in images]

        for index in range(count):
            if cancelled and cancelled():
                for future in running:
                    future.cancel()
                from app_core import GracefulStop
                raise GracefulStop('PDF okuma durduruldu; okunan sayfalar kaydedildi.')
            cached = sorted(folder.glob(f'{index + 1:04d}*.txt'))
            if cached:
                texts[index] = '\n\n'.join(path.read_bytes().decode('utf-8') for path in cached)
                done += 1
                if progress:
                    progress(done, count)
                continue
            layer = _text_layer(document, index)
            if len(' '.join(layer.split())) >= TEXT_LAYER_CHARS:
                finish(index, [layer])
                continue
            # Sayfalar bu is parcaciginda cizilir (pdfium tek is parcacikli); okuma havuzda paralel.
            running[pool.submit(read_parts, page_images(document, index))] = (index, None)
            while len(running) >= workers * 2:
                collect(True)
            collect(False)
        while running:
            collect(True)
        return texts
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        with documents._PDFIUM:
            document.close()


# ---------------------------------------------------------------------- temizleme
TERMINAL = tuple('.!?…:;"”»)\'’')
LOWER_START = re.compile(r'^[a-zçğıöşüâîûéèàäëïô]')
PAGE_NUMBER = re.compile(r'^[\s\-–—.]*(?:\d{1,4}|[ivxlc]{1,7})[\s\-–—.]*$', re.I)
SOFT_HYPHEN = re.compile(r'(?<![\w-])([^\W\d_]+)-([^\W\d_]+)(?![\w-])')
WORD = re.compile(r'[^\W\d_]+')
NON_LATIN = re.compile(r'[Ͱ-ϿЀ-ӿ֐-ۿ぀-ヿ㐀-鿿가-힯]')
HEADER_LIMIT = 80           # ust/alt bilgi sayilacak paragrafin en fazla uzunlugu
FOOTNOTE = re.compile(r'^(?:[*°†‡]+|[¹²³⁴⁵⁶⁷⁸⁹]+)\s*[^\W\d_]')   # sayfa sonu dipnotu


def detect_language(text):
    """'tr' ya da 'en': Turkceye ozgu harfler ve sik kelimelerle."""
    sample = text[:200000].lower()
    letters = sum(sample.count(ch) for ch in 'ğışİ')
    words = Counter(WORD.findall(sample))
    turkish = letters / max(1, len(sample)) * 1000 + sum(words[w] for w in ('ve', 'bir', 'bu', 'da', 'de', 'için'))
    english = sum(words[w] for w in ('the', 'and', 'of', 'to', 'was', 'he'))
    return 'tr' if turkish > english else 'en'


def _blocks(text):
    """Sayfa metni -> paragraflar. Bos satir paragraf ayirir; paragraf icindeki satirlar birlesir
    (satir sonundaki tire kelime bolmesiyse kaldirilir, karar sonra dehyphenate'te verilir)."""
    text = unicodedata.normalize('NFC', _newlines(text)).replace('­', '')
    result = []
    for block in re.split(r'\n\s*\n', text):
        # OCR modeli bazen metni kod blogu isaretleriyle (```markdown) sarar
        lines = [line.strip() for line in block.split('\n') if line.strip() and not re.fullmatch(r'\s*```\w*\s*', line)]
        if not lines:
            continue
        # Tesseract paragraflari (ozellikle diyaloglari) bos satirsiz verebilir. Calibre'nin yontemi: tipik satirdan
        # belirgin kisa olup cumle sonu noktalamasiyla biten satir paragraf sonudur.
        lengths = sorted(len(line) for line in lines)
        typical = lengths[len(lengths) * 3 // 4] if len(lines) >= 3 else 0
        paragraph = lines[0]
        for previous, line in zip(lines, lines[1:]):
            if typical and len(previous) < typical * 0.8 and previous.endswith(TERMINAL):
                result.append(re.sub(r'\s+', ' ', paragraph))
                paragraph = line
            elif paragraph.endswith('-') and LOWER_START.match(line):
                paragraph = paragraph + line       # 'gel-' + 'di' -> 'gel-di' (sonra birlesir)
            else:
                paragraph = paragraph + ' ' + line
        result.append(re.sub(r'\s+', ' ', paragraph))
    return _trim_edges(result)


EDGE_SCAN = 6               # sayfa basinda/sonunda kirinti aranan paragraf sayisi


def _is_debris(paragraph):
    """Sayfa kenarindaki tarama kirintisi: 'TIi', 'a', '‘so' gibi; tek basina bolum numarasi degil."""
    letters = len(re.findall(r'[^\W\d_]', paragraph))
    return len(paragraph) <= 5 and letters <= 3 and not NUMBER_WORDS.match(paragraph)


def _trim_edges(paragraphs):
    """Sayfanin basindaki ve sonundaki kirintilari atar (Tesseract kenar suslerini, dikey seritleri harf sanar)."""
    start, end = 0, len(paragraphs)
    while start < min(end, EDGE_SCAN) and _is_debris(paragraphs[start]):
        start += 1
    while end > start and len(paragraphs) - end < EDGE_SCAN and _is_debris(paragraphs[end - 1]):
        end -= 1
    return paragraphs[start:end]


def _header_key(text):
    return re.sub(r'[\W_]+', ' ', re.sub(r'\d+', ' ', text.casefold())).strip()   # rakamlar yok sayilir


def strip_running(pages):
    """Tekrar eden ust/alt bilgileri ve sayfa numaralarini atar. pages: paragraf listelerinin listesi.
    Sayfa kenarinda (ilk/son 3 paragraf) kisa olup bir cok sayfada (rakamlar yok sayilarak) ayni gorunen
    satirlar ust/alt bilgidir ve sayfanin her yerinden atilir (Tesseract kenar satirlarini metnin ortasina
    koyabiliyor). Tek basina sayi ancak sayfa sirasiyla tutarliysa (sayi - sayfa farki kitabin cogunda ayni)
    sayfa numarasidir; sayfa basindaki '1', '2' gibi bolum numaralari kalir."""
    edges = Counter()
    offsets = Counter()
    for index, paragraphs in enumerate(pages):
        for paragraph in {*paragraphs[:3], *paragraphs[-3:]}:
            if len(paragraph) <= HEADER_LIMIT:
                edges[_header_key(paragraph)] += 1
        for paragraph in set(paragraphs):
            number = re.fullmatch(r'\D{0,3}(\d{1,4})\D{0,3}', paragraph)
            if number:
                offsets[int(number.group(1)) - index] += 1
    threshold = max(3, len(pages) // 5)
    running = {key for key, count in edges.items() if key and count >= threshold and re.search(r'[^\W\d_]', key)}
    offset = next((value for value, count in offsets.most_common(1) if count >= 3), None)

    def is_running(index, position, paragraph):
        if len(paragraph) > HEADER_LIMIT:
            return False
        if _header_key(paragraph) in running:
            return True
        number = re.fullmatch(r'\D{0,3}(\d{1,4})\D{0,3}', paragraph)
        if number:
            return offset is not None and abs(int(number.group(1)) - index - offset) <= 1
        edge = position < 2 or position >= len(pages[index]) - 2
        return edge and bool(PAGE_NUMBER.match(paragraph)) and index < 30   # on sayfalardaki Roma rakamlari
    return [[paragraph for position, paragraph in enumerate(paragraphs) if not is_running(index, position, paragraph)]
            for index, paragraphs in enumerate(pages)]


# OCR'in Latin metne karistirdigi Kiril benzerleri ('İlsе'deki е) Latin harfe cevrilir; kalan yabanci
# alfabe karakterleri ('bölme勒den', '啊, olur') atilir. Sayfa yine de gozden gecirmeye isaretlenir.
LOOKALIKES = str.maketrans('аеорсухіАЕОРСУХІТНКМВ', 'aeopcyxiAEOPCYXITHKMB')


def fix_script(text):
    """(duzeltilmis metin, degisti mi)."""
    fixed = NON_LATIN.sub('', text.translate(LOOKALIKES))
    fixed = re.sub(r'(^|[\s“"‘(])[,.;:]\s*', r'\1', fixed) if fixed != text else fixed
    return re.sub(r'  +', ' ', fixed).strip(), fixed != text


def _vocabulary(pages):
    words = Counter()
    for paragraphs in pages:
        for paragraph in paragraphs:
            for word in WORD.findall(SOFT_HYPHEN.sub(' ', paragraph)):
                words[word.casefold()] += 1
    return words


def _join_hyphen(left, right, language, vocabulary):
    """'gel-di' tire satir sonu bolmesi mi? Turkcede kucuk harfli iki parca birlesir; Ingilizcede
    birlesik kelime kitapta geciyorsa ya da parcalardan biri kelime degilse ('minimiz-ing')."""
    if not right[:1].islower() or not left[-1:].islower():
        return False
    joined = (left + right).casefold()
    if vocabulary[joined]:
        return True
    if language == 'tr':
        return True
    return not (vocabulary[left.casefold()] and vocabulary[right.casefold()])


def dehyphenate(paragraph, language, vocabulary):
    return SOFT_HYPHEN.sub(lambda m: m.group(1) + m.group(2) if _join_hyphen(m.group(1), m.group(2), language, vocabulary)
                           else m.group(0), paragraph)


DUPLICATE_RATIO = 0.9


def drop_duplicate_pages(texts):
    """Taramada ayni sayfa art arda iki kez olabiliyor: ikincisi bosaltilir. (metinler, tekrar sayfa numaralari)."""
    from difflib import SequenceMatcher
    result, duplicates = list(texts), set()
    for index in range(1, len(texts)):
        previous, current = (' '.join(str(texts[i]).split())[:1500] for i in (index - 1, index))
        if len(current) <= 200:
            continue
        # Hizli on eleme: kelime kumeleri cok ortusmuyorsa tekrar degildir (ayni dilde harf dagilimi hep benzer).
        before, after = set(previous.casefold().split()), set(current.casefold().split())
        if len(before & after) < DUPLICATE_RATIO * max(len(before), len(after)):
            continue
        if SequenceMatcher(None, previous, current, autojunk=False).ratio() >= DUPLICATE_RATIO:
            result[index] = ''
            duplicates.add(index + 1)
    return result, duplicates


def clean_pages(texts, language=None):
    """Sayfa metinleri -> (paragraflar, dil, uyarilar). paragraf: {'text', 'page'} (page 1'den baslar).
    Sayfalar arasinda yarim kalan paragraf (tireyle biten ya da noktalamasiz bitip kucuk harfle
    suren) birlestirilir. uyarilar: [{'page', 'reason'}] gozden gecirme icin."""
    texts, duplicates = drop_duplicate_pages(texts)
    pages = strip_running([_blocks(text) for text in texts])
    language = language or detect_language('\n'.join(p for page in pages for p in page))
    paragraphs, warnings = [], []
    for number, page in enumerate(pages, 1):
        if number in duplicates:
            warnings.append({'page': number, 'reason': f'Taramada {number - 1}. sayfanın tekrarı; atlandı.'})
        elif not page:
            warnings.append({'page': number, 'reason': 'Metin çıkmadı (boş ya da resimli sayfa).'})
        fixed = [fix_script(text) for text in page]
        if any(changed for _text, changed in fixed):
            warnings.append({'page': number, 'reason': 'OCR alfabe dışı karakter üretti; düzeltildi, sayfayı kontrol edin.'})
        pages[number - 1] = page = [text for text, _changed in fixed if text]
    vocabulary = _vocabulary(pages)
    notes = []
    for number, page in enumerate(pages, 1):
        # Sayfa sonundaki dipnotlar ('* Hristiyanlarin ... -çn') akistan ayrilir; bolum sonunda toplanir.
        while page and FOOTNOTE.match(page[-1]) and len(page) > 1:
            notes.append({'text': page.pop(), 'page': number, 'note': True})
        for index, text in enumerate(page):
            previous = next((p for p in reversed(paragraphs) if not p.get('note')), None)
            if index == 0 and previous and previous['page'] < number:
                tail = previous['text']
                if tail.endswith('-') and LOWER_START.match(text):
                    left = (WORD.findall(tail[:-1].rsplit(' ', 1)[-1]) or [''])[-1]
                    right = (WORD.findall(text.split(' ', 1)[0]) or [''])[0]
                    glue = '' if left and right and _join_hyphen(left, right, language, vocabulary) else '-'
                    previous['text'] = tail[:-1] + glue + text
                    continue
                if not tail.endswith(TERMINAL) and LOWER_START.match(text):
                    previous['text'] = tail + ' ' + text
                    continue
            paragraphs.append({'text': text, 'page': number})
        paragraphs.extend(reversed([note for note in notes if note['page'] == number]))
    for paragraph in paragraphs:
        paragraph['text'] = dehyphenate(paragraph['text'], language, vocabulary)
    return paragraphs, language, warnings


# ---------------------------------------------------------------------- bolumleme
HEADING_WORDS = (r'chapter|part|book|prologue|epilogue|interlude|afterword|foreword|introduction|preface|'
                 r'bolum|kisim|kitap|onsoz|sonsoz|son soz|giris|ara bolum|baslangic|sonuc')
STRONG_HEADING = re.compile(rf'^#*\s*(?:{HEADING_WORDS})\b[^.!?]{{0,60}}$', re.I)
PART_HEADING = re.compile(r'^#*\s*(?:part|book|kisim|kitap)\b', re.I)
# OCR Turkce harfleri karistirabiliyor ('Kisim Üç'): basliklar harf farklarina duyarsiz eslesir.
FOLD = str.maketrans('ıİIöÖüÜşŞçÇğĞâÂîÎûÛ’‘', "iiioouussccggaaiiuu''")


def _fold(text):
    return text.translate(FOLD).casefold()


def is_strong(text):
    return bool(STRONG_HEADING.match(_fold(text)))


def is_part(text):
    return bool(PART_HEADING.match(_fold(text)))


NUMBER_WORDS =re.compile(r'^(?:\d{1,3}|[IVXLC]{1,6})\.?$')
TITLE_LIMIT = 70
CHUNK_PAGES = 15
GENERIC_TITLES = {'tr': ('Bölüm', 'Ön sayfalar'), 'en': ('Part', 'Front matter')}


def _is_title_like(text):
    return len(text) <= TITLE_LIMIT and not text.rstrip().endswith(('.', ',', ';', '?', '!', '…', '"', '”'))


def outline_chapters(pdf):
    """PDF icindekileri [(sayfa, baslik)]; yalnizca anlamliysa: basliklarin cogu sayi ya da 'blank',
    'cover' gibi sayfa etiketi degilse ve sayfalar artiyorsa."""
    document = documents.open_pdf(pdf)
    entries = []
    try:
        with documents._PDFIUM:
            for item in document.get_toc():
                dest = item.get_dest()
                index = dest.get_index() if dest else None
                if index is not None and item.level == 0:
                    entries.append((index + 1, ' '.join(item.get_title().split())))
    finally:
        with documents._PDFIUM:
            document.close()
    noise = sum(1 for _page, title in entries if not title or NUMBER_WORDS.match(title)
                or re.fullmatch(r'\d*\s*(blank|cover|page|sayfa|bos|boş)\s*\d*', title, re.I))
    pages = [page for page, _title in entries]
    if len(entries) < 2 or noise > len(entries) / 3 or pages != sorted(pages) or len(set(pages)) < len(pages):
        return []
    return entries


def _increasing_numbers(paragraphs, indices):
    """Sayi basliklarindan duzenli artan en uzun diziyi (her adim 1-3) secer; sayfa ortasina dusmus ya da
    yanlis okunmus sayfa numaralari ('66', '316') bu diziye girmez. Sayi olmayan basliklar ([...]) kalir."""
    numbers = [(i, int(paragraphs[i]['text'].rstrip('.'))) for i in indices if paragraphs[i]['text'].rstrip('.').isdigit()]
    others = [i for i in indices if not paragraphs[i]['text'].rstrip('.').isdigit()]
    best = []
    chains = []   # her sayi icin: o sayiyla biten en uzun dizi
    for position, (index, value) in enumerate(numbers):
        chain = [(index, value)]
        for earlier in range(position):
            previous = chains[earlier]
            if 1 <= value - previous[-1][1] <= 3 and len(previous) + 1 > len(chain):
                chain = previous + [(index, value)]
        chains.append(chain)
        if len(chain) > len(best):
            best = chain
    if len(best) < 2:
        best = []
    return sorted(others + [index for index, _value in best])


def heading_indices(paragraphs):
    """Bolum basligi sayilan paragraflarin sirasi: guclu kaliplar ('Chapter 3', 'Kısım Bir', 'Önsöz',
    markdown '#') ile sayfa basinda tek basina duran sayi/Roma rakami ya da [koseli] basliklar.
    Sayfa basi basliklari kitabin ucte birinden fazla sayfasinda goruluyorsa (sayfa numarasi olabilir)
    kullanilmaz."""
    first_on_page = [i for i, p in enumerate(paragraphs) if i == 0 or paragraphs[i - 1]['page'] != p['page']]
    strong = [i for i, p in enumerate(paragraphs)
              if (is_strong(p['text']) or p['text'].startswith('#')) and _is_title_like(p['text'].lstrip('# '))]
    weak = [i for i in first_on_page
            if NUMBER_WORDS.match(paragraphs[i]['text']) or re.fullmatch(r'\[[^\]]{2,60}\]', paragraphs[i]['text'])]
    weak = _increasing_numbers(paragraphs, weak)
    if len(weak) > max(2, len({p['page'] for p in paragraphs}) // 3):
        weak = []
    indices = sorted(set(strong) | set(weak))
    return indices if len(indices) >= 2 else []


def top_gap(document, index):
    """Sayfanin ust kismindan (ilk %20 icinde) baslayan en uzun bos yatay seridin sayfa yuksekligine orani.
    Bolum basi sayfalarinda baslik oncesi/sonrasi buyuk bosluk olur (~0,2+); siradan sayfada cok kucuktur.
    Metnin ustte bitip alti bos kalan bolum sonu sayfalari sayilmaz (bosluklari asagida baslar)."""
    with documents._PDFIUM:
        page = document[index]
        try:
            width, height = page.get_size()
            image = page.render(scale=300 / max(width, height, 1.0), grayscale=True,
                                fill_color=(255, 255, 255, 255)).to_pil().convert('L')
        finally:
            page.close()
    if image.width > image.height * SPREAD_RATIO:
        return 0.0
    pixels = image.load()
    rows, start_limit = int(image.height * 0.6), int(image.height * 0.2)
    longest = run = 0
    # Kenar bosluklarindaki sayfa numaralari sayilmasin: yalnizca orta bant (%20-%80) taranir.
    columns = range(int(image.width * 0.2), int(image.width * 0.8), 2)
    for y in range(rows):
        dark = sum(1 for x in columns if pixels[x, y] < 128)
        if dark <= 1:
            run += 1
        else:
            # yalnizca altinda yeniden yazi baslayan bosluk sayilir (sayfanin alti bos bolum sonu degil)
            if run and y - run < start_limit:
                longest = max(longest, run)
            run = 0
    return longest / image.height


CHAPTER_GAP = 0.15          # top_gap bundan buyukse sayfa bolum basi sayilir
NUMBER_AGREEMENT = 0.7      # OCR numaralarinin bu kadari sirayla uyusuyorsa bolumler yeniden numaralanir


def number_chapters(paragraphs, pdf, log=print):
    """Numarali bolumleri (sayfa basinda '1', '2' ...) sayfa goruntusuyle denetler. OCR modeli suslu yazilmis
    bolum numaralarini bazen hic okumaz ('7' yok) ya da yanlis okur (15 -> 16). Bolum basi sayfalari ustlerindeki
    buyuk bosluktan bulunur; OCR'in okudugu numaralarin cogu bu sirayla uyusuyorsa bolumler sirayla yeniden
    numaralanir, eksik basliklar eklenir. Uyusmuyorsa hicbir sey degismez."""
    indices = heading_indices(paragraphs)
    numbered = [(i, int(paragraphs[i]['text'].rstrip('.'))) for i in indices if paragraphs[i]['text'].rstrip('.').isdigit()]
    if len(numbered) < 3:
        return paragraphs
    headings = {paragraphs[i]['page']: i for i, _value in numbered}
    # Ilk okunan numaradan oncesine de bakilir (Tesseract '1'-'9'u okumamis olabilir); on sayfalarin
    # bosluklu sayfalari (kapak, ithaf) asagida numara 1'in altina dusup elenir.
    first_page, last_page = paragraphs[0]['page'], paragraphs[-1]['page']
    # Kitap kisimlara ayriliyorsa ('Kısım Bir') bolumler ilk kisimdan once baslamaz (on sayfalar).
    first_part = next((p['page'] for p in paragraphs if is_part(p['text']) and _is_title_like(p['text'])), 0)
    starts = dict(headings)
    document = documents.open_pdf(pdf)
    try:
        for page in range(first_page + 1, last_page + 1):
            if page in starts:
                continue
            index = next((i for i, p in enumerate(paragraphs) if p['page'] == page and not p.get('note')), None)
            if index is None or not index:
                continue
            previous = next((p['text'] for p in reversed(paragraphs[:index]) if not p.get('note')), '')
            text = paragraphs[index]['text']
            if not previous.endswith(TERMINAL) and not is_part(previous):
                continue
            if LOWER_START.match(text) or is_strong(text) or page < first_part:
                continue
            if top_gap(document, page - 1) >= CHAPTER_GAP:
                starts[page] = index
    finally:
        with documents._PDFIUM:
            document.close()
    ordered = sorted(starts)
    order = {page: position for position, page in enumerate(ordered)}
    # Okunan numaralarin cogunun uydugu baslangic (numara - sira farki)
    base = Counter(value - order[paragraphs[i]['page']] for i, value in numbered).most_common(1)[0][0]
    expected = {page: base + order[page] for page in ordered}
    for page in [page for page in ordered if expected[page] < 1]:   # numara 1'den once: on sayfalar
        starts.pop(page)
    agree = sum(1 for i, value in numbered if expected[paragraphs[i]['page']] == value)
    if agree < NUMBER_AGREEMENT * len(numbered):
        log(f"UYARI: Bölüm numaraları sayfa düzeniyle uyuşmadı ({agree}/{len(numbered)}); OCR'daki numaralar kullanıldı.")
        return paragraphs
    result = [dict(p) for p in paragraphs]
    inserts = []
    for page, index in starts.items():
        value = str(expected[page])
        if page in headings:
            if result[index]['text'].rstrip('.') != value:
                log(f'Bölüm {value}: OCR "{result[index]["text"]}" okumuştu ({page}. sayfa), düzeltildi.')
                result[index]['text'] = value
        else:
            inserts.append((index, {'text': value, 'page': page, 'inserted': True}))
            log(f"Bölüm {value} başlığı OCR'da yoktu; {page}. sayfaya eklendi.")
    for index, paragraph in sorted(inserts, key=lambda item: item[0], reverse=True):
        result.insert(index, paragraph)
    return result


CONTENTS_LINE = re.compile(r'^\s*(.*?[^\W\d_].*?)[\s.·…_-]*\s(\d{1,3})\s*$')
CONTENTS_PAGES = 15         # kitap ici icindekiler ilk bu kadar sayfada aranir


def contents_entries(texts):
    """Kitabin kendi icindekiler sayfasi: 'Baslik ...... 123' satirlari. ([(basili sayfa, baslik)], sayfalar).
    Ilk CONTENTS_PAGES sayfada en az 3 boyle satiri olan sayfalar icindekiler sayilir."""
    entries, pages = [], set()
    for number, text in enumerate(texts[:CONTENTS_PAGES], 1):
        found = []
        for line in str(text).replace('\r', '').split('\n'):
            match = CONTENTS_LINE.match(line)
            if match and len(match.group(1)) <= TITLE_LIMIT:
                title = re.sub(r'^[#*\s]*-?\d+\s+(?=[^\W\d_])', '', match.group(1)).strip(' .·…-')
                if WORD.search(title):
                    found.append((int(match.group(2)), title))
        if len(found) >= 3:
            entries.extend(found)
            pages.add(number)
    entries = sorted(set(entries))
    return entries, pages


def contents_starts(paragraphs, entries, toc_pages):
    """Icindekiler basliklarini govdede sirayla bulur; bulunamayanlar basili sayfa + (PDF sayfasi - basili
    sayfa) farkiyla yerlestirilir. [(sira, baslik, basliktan mi)] ya da yeterince eslesme yoksa []."""
    after = max(toc_pages) if toc_pages else 0
    entries = [(printed, title) for printed, title in entries if printed > 2]   # '... 1' kitap adi satiridir
    matched, position = {}, 0
    for printed, title in entries:
        key = _fold(title)
        for index in range(position, len(paragraphs)):
            paragraph = paragraphs[index]
            raw = paragraph['text'].lstrip('# ').strip()
            text = _fold(raw)
            if paragraph['page'] <= after or paragraph.get('note') or not _is_title_like(raw):
                continue
            # Basligin onunde kitap adi ya da 'L19' gibi kod olabilir; baslik satirin sonunda buyuk harfle baslar.
            tail = raw[len(raw) - len(title):] if len(raw) >= len(title) else ''
            if text == key or (len(text) <= len(key) + 45 and tail[:1].isupper()
                               and (text.endswith(' ' + key) or text.endswith('-' + key))):
                matched[printed, title] = index
                position = index + 1
                break
    if len(matched) < 2:
        return []
    anchors = sorted((printed, paragraphs[index]['page']) for (printed, _title), index in matched.items())

    def page_of(printed):
        """Basili sayfa -> PDF sayfasi: komsu eslesmeler arasinda orantili (cift sayfa taramada oran ~1/2)."""
        before = [a for a in anchors if a[0] <= printed]
        later = [a for a in anchors if a[0] >= printed]
        (p1, q1), (p2, q2) = (before[-1] if before else anchors[0]), (later[0] if later else anchors[-1])
        if p1 == p2:
            (p1, q1), (p2, q2) = anchors[0], anchors[-1]
        return round(q1 + (printed - p1) * (q2 - q1) / max(1, p2 - p1))
    starts = []
    for printed, title in entries:
        if (printed, title) in matched:
            index = matched[printed, title]
            raw = paragraphs[index]['text'].lstrip('# ').strip()
            prefix = raw[:len(raw) - len(title)].strip(' -')
            start = (index, raw if len(prefix) <= 8 else title, True)
        else:
            page = page_of(printed)
            index = next((i for i, p in enumerate(paragraphs) if p['page'] >= page and not p.get('note')), None)
            if index is None or paragraphs[index]['page'] != page:
                continue
            start = (index, title, False)
        if not starts or start[0] > starts[-1][0]:
            starts.append(start)
    return starts if len(starts) >= max(2, len(entries) * 0.6) else []


def layout_pages(paragraphs, pdf):
    """Bolum basi gibi gorunen sayfalar (ustte buyuk bosluk, onceki sayfa cumleyle bitmis, sayfa yeni
    paragrafla basliyor). Baslik okunamayan kitaplarda (suslu yazi, Tesseract) bolum sinirlari icin."""
    first = {}
    for index, paragraph in enumerate(paragraphs):
        if not paragraph.get('note'):
            first.setdefault(paragraph['page'], index)
    pages = []
    document = documents.open_pdf(pdf)
    try:
        for page, index in sorted(first.items()):
            previous = next((p['text'] for p in reversed(paragraphs[:index]) if not p.get('note')), '')
            if (index and previous.endswith(TERMINAL) and not LOWER_START.match(paragraphs[index]['text'])
                    and top_gap(document, page - 1) >= CHAPTER_GAP):
                pages.append(page)
    finally:
        with documents._PDFIUM:
            document.close()
    return pages


def _ordinal(paragraphs, index):
    """index'teki paragrafin sayfasindaki sirasi: ayni sayfada ondan once gelen gercek (not ya da eklenmis
    baslik olmayan) paragraf sayisi. Sinirlar (sayfa, sira) olarak saklanir; metin duzeltilse de anlamli kalir."""
    page = paragraphs[index]['page']
    return sum(1 for p in paragraphs[:index] if p['page'] == page and not p.get('note') and not p.get('inserted'))


def auto_boundaries(paragraphs, language, outline=(), contents=None, layout=None):
    """Otomatik bolum sinirlari: [{'title', 'page', 'ordinal', 'skip', 'level'}]. skip: bolum basinda atlanan
    (baslik olarak kullanilan) gercek paragraf sayisi. Sirasiyla: anlamli PDF icindekileri, kitabin kendi
    icindekiler sayfasi (contents: contents_entries sonucu), baslik satirlari, sayfa duzeni (layout: bolum basi
    sayfalarini donduren islev), CHUNK_PAGES sayfalik parcalar. Baslik satirindan sonraki kisa satir alt baslik
    sayilip birlestirilir ('Chapter 1' + 'The Storm' -> 'Chapter 1: The Storm'). Ilk sinirdan onceki metin
    'Ön sayfalar' bolumu olur."""
    generic, front = GENERIC_TITLES.get(language, GENERIC_TITLES['en'])
    if not paragraphs:
        return []
    starts, subtitles = [], False
    if outline:
        for page, title in outline:
            index = next((i for i, p in enumerate(paragraphs) if p['page'] >= page), None)
            if index is not None and (not starts or index > starts[-1][0]):
                starts.append((index, title, False))
    if not starts and contents and contents[0]:
        starts = contents_starts(paragraphs, *contents)
    if not starts:
        toc_pages = contents[1] if contents else set()
        starts = [(index, paragraphs[index]['text'].lstrip('# ').strip(), True)
                  for index in heading_indices(paragraphs) if paragraphs[index]['page'] not in toc_pages]
        subtitles = True
    if not starts and layout is not None:
        chapter_word = 'Bölüm' if language == 'tr' else 'Chapter'
        for number, page in enumerate(layout(), 1):
            index = next((i for i, p in enumerate(paragraphs) if p['page'] == page and not p.get('note')), None)
            if index is not None and (not starts or index > starts[-1][0]):
                starts.append((index, f'{chapter_word} {number}', False))
        if len(starts) < 2:
            starts = []
    if not starts:
        pages = sorted({p['page'] for p in paragraphs})
        for number, page in enumerate(range(pages[0], pages[-1] + 1, CHUNK_PAGES), 1):
            index = next((i for i, p in enumerate(paragraphs) if p['page'] >= page), None)
            if index is not None and (not starts or index > starts[-1][0]):
                starts.append((index, f'{generic} {number}', False))
    boundaries = []
    for position, (index, title, from_text) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(paragraphs)
        skip = 1 if from_text and not paragraphs[index].get('inserted') else 0
        following = [p for p in paragraphs[index + (1 if from_text else 0):end] if not p.get('note')]
        if (subtitles and from_text and len(following) > 1 and _is_title_like(following[0]['text'])
                and not is_strong(following[0]['text']) and not following[0].get('inserted')):
            title = f'{title}: {following[0]["text"]}'
            skip += 1
        boundaries.append({'title': title, 'page': paragraphs[index]['page'], 'ordinal': _ordinal(paragraphs, index),
                           'skip': skip, 'level': 0})
    # 'Kısım Bir' / 'Part One' ile numarali bolumler birlikteyse kisimlar ust duzey, bolumler altinda.
    parts = [b for b in boundaries if is_part(b['title'])]
    if parts and len(parts) < len(boundaries):
        inside = False
        for boundary in boundaries:
            if boundary in parts:
                inside = True
            elif inside:
                boundary['level'] = 1
    if any(not p.get('note') and not p.get('inserted') for p in paragraphs[:starts[0][0]]):
        boundaries.insert(0, {'title': front, 'page': paragraphs[0]['page'], 'ordinal': 0, 'skip': 0, 'level': 0})
    return boundaries


def chapters_from(paragraphs, boundaries):
    """Sinirlardan bolumler: [{'title', 'paragraphs', 'notes', 'level', 'page', 'ordinal', 'skip'}].
    paragraphs: clean_pages ciktisi (eklenmis baslik yok). Sinirin sayfasi/sirasi artik yoksa (metin
    duzeltildi) o sayfanin sonuna ya da sonraki sayfaya kayar."""
    positions = {}
    for index, paragraph in enumerate(paragraphs):
        if not paragraph.get('note'):
            positions.setdefault(paragraph['page'], []).append(index)

    def locate(page, ordinal):
        indices = positions.get(page, [])
        if ordinal < len(indices):
            return indices[ordinal]
        return next((i for i, p in enumerate(paragraphs) if p['page'] > page and not p.get('note')), len(paragraphs))
    located = sorted(((locate(b['page'], b.get('ordinal', 0)), position, b) for position, b in enumerate(boundaries)),
                     key=lambda item: (item[0], item[1]))
    chapters = []
    for position, (index, _order, boundary) in enumerate(located):
        end = located[position + 1][0] if position + 1 < len(located) else len(paragraphs)
        part = paragraphs[index:end]
        body = [p['text'] for p in part if not p.get('note')][int(boundary.get('skip', 0)):]
        notes = [p['text'] for p in part if p.get('note')]
        chapters.append({'title': boundary['title'], 'paragraphs': body, 'notes': notes,
                         'level': int(boundary.get('level', 0)), 'page': boundary['page'],
                         'ordinal': boundary.get('ordinal', 0), 'skip': int(boundary.get('skip', 0))})
    return chapters


def split_chapters(paragraphs, language, outline=(), contents=None, layout=None):
    """Otomatik bolumleme: auto_boundaries + chapters_from (eklenmis basliklar metne girmez)."""
    boundaries = auto_boundaries(paragraphs, language, outline, contents, layout)
    return chapters_from([p for p in paragraphs if not p.get('inserted')], boundaries)


# ---------------------------------------------------------------------- EPUB
# Tarama uygulamalarinin yazdigi ust veri ('CamScanner 06.07.2024 10.42') kitap adi/yazari degildir.
SCANNER_META = re.compile(r'camscanner|adobe scan|microsoft lens|office lens|genius ?scan|tiny ?scanner|clear ?scan|'
                          r'scanned|\bscan\b|\d{1,4}[./-]\d{1,2}[./-]\d{1,4}', re.I)


def guess_title_author(pdf):
    """PDF ust verisinden, yoksa dosya adindan ('Baslik - Yazar'); koseli parantezli etiketler atilir."""
    document = documents.open_pdf(pdf)
    try:
        with documents._PDFIUM:
            meta = document.get_metadata_dict()
    finally:
        with documents._PDFIUM:
            document.close()
    name = re.sub(r'\s*\[[^\]]*\]', '', Path(pdf).stem).replace('_', ' ').strip()
    title, author = name, ''
    parts = [part.strip() for part in name.split(' - ')]
    if len(parts) == 2:
        title, author = parts
    meta_title = ' '.join(str(meta.get('Title') or '').split())
    meta_author = ' '.join(str(meta.get('Author') or '').split())
    key = lambda text: re.sub(r'\W+', '', text).casefold()  # noqa: E731
    if (meta_title and key(meta_title) not in (key(name), key(Path(pdf).stem))
            and not re.search(r'\.(pdf|docx?|indd)$|^untitled|^microsoft', meta_title, re.I)
            and not SCANNER_META.search(meta_title)):
        title = meta_title
    if meta_author and not re.search(r'^(admin|user|owner)', meta_author, re.I) and not SCANNER_META.search(meta_author):
        author = meta_author
    return title, author


def _xhtml(title, body, language):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{language}" '
            f'xml:lang="{language}"><head><title>{html.escape(title)}</title></head><body>{body}</body></html>')


def cover_jpeg(pdf):
    """Ilk sayfanin goruntusu (cift sayfa taramasinda tamami)."""
    import io
    document = documents.open_pdf(pdf)
    try:
        with documents._PDFIUM:
            page = document[0]
            try:
                width, height = page.get_size()
                image = page.render(scale=COVER_LONG_SIDE / max(width, height, 1.0),
                                    fill_color=(255, 255, 255, 255)).to_pil().convert('RGB')
            finally:
                page.close()
    finally:
        with documents._PDFIUM:
            document.close()
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=85)
    return buffer.getvalue()


def write_epub(path, chapters, title, author, language, cover=None):
    """EPUB 3 (nav + toc.ncx) yazar; her bolum ayri XHTML, baslik h1, paragraflar p."""
    path = Path(path)
    ident = 'urn:uuid:' + str(uuid.uuid4())
    modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    files, manifest, spine, entries = [], [], [], []
    for number, chapter in enumerate(chapters, 1):
        name = f'text/bolum{number:03d}.xhtml'
        label = html.escape(chapter['title'])
        body = f'<h1>{label}</h1>' + ''.join(f'<p>{html.escape(text)}</p>' for text in chapter['paragraphs'])
        if chapter.get('notes'):
            body += (f'<section class="notes"><h2>{"Notlar" if language == "tr" else "Notes"}</h2>'
                     + ''.join(f'<p>{html.escape(text)}</p>' for text in chapter['notes']) + '</section>')
        files.append((f'OEBPS/{name}', _xhtml(chapter['title'], body, language)))
        manifest.append(f'<item id="c{number}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{number}"/>')
        entries.append((chapter.get('level', 0) if entries else 0, number, name, label))
    # level 1 (kisim icindeki bolum) bir onceki level 0 ogesinin altina girer.
    nav, ncx, index = [], [], 0
    while index < len(entries):
        _level, number, name, label = entries[index]
        children = []
        index += 1
        while index < len(entries) and entries[index][0] == 1:
            children.append(entries[index])
            index += 1
        sub_nav = ''.join(f'<li><a href="{n}">{l}</a></li>' for _lv, _no, n, l in children)
        sub_ncx = ''.join(f'<navPoint id="n{no}" playOrder="{no}"><navLabel><text>{l}</text></navLabel>'
                          f'<content src="{n}"/></navPoint>' for _lv, no, n, l in children)
        nav.append(f'<li><a href="{name}">{label}</a>' + (f'<ol>{sub_nav}</ol>' if children else '') + '</li>')
        ncx.append(f'<navPoint id="n{number}" playOrder="{number}"><navLabel><text>{label}</text></navLabel>'
                   f'<content src="{name}"/>{sub_ncx}</navPoint>')
    cover_meta = ''
    if cover:
        manifest.append('<item id="cover" href="images/kapak.jpg" media-type="image/jpeg" properties="cover-image"/>')
        cover_meta = '<meta name="cover" content="cover"/>'
    heading = 'İçindekiler' if language == 'tr' else 'Contents'
    nav_doc = _xhtml(title, f'<nav epub:type="toc" id="toc"><h1>{heading}</h1><ol>' + ''.join(nav) + '</ol></nav>', language)
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="bookid">{ident}</dc:identifier><dc:title>{html.escape(title)}</dc:title>'
           + (f'<dc:creator>{html.escape(author)}</dc:creator>' if author else '')
           + f'<dc:language>{language}</dc:language><meta property="dcterms:modified">{modified}</meta>{cover_meta}'
           '</metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
           '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>' + ''.join(manifest)
           + '</manifest><spine toc="ncx">' + ''.join(spine) + '</spine></package>')
    toc = ('<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="{ident}"/></head><docTitle><text>{html.escape(title)}</text></docTitle>'
           '<navMap>' + ''.join(ncx) + '</navMap></ncx>')
    container = ('<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                 '</rootfiles></container>')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        archive.writestr('META-INF/container.xml', container)
        archive.writestr('OEBPS/content.opf', opf)
        archive.writestr('OEBPS/nav.xhtml', nav_doc)
        archive.writestr('OEBPS/toc.ncx', toc)
        for name, content in files:
            archive.writestr(name, content)
        if cover:
            archive.writestr('OEBPS/images/kapak.jpg', cover)
    temp.replace(path)
    return path


# ---------------------------------------------------------------------- gozden gecirme
EDITS_DIR = 'duzeltme'      # elle duzeltilen sayfa metinleri (OCR ciktisi bozulmaz)
BOOK_FILE = 'kitap.json'    # kitap adi, yazar, dil ve bolum sinirlari
REVIEW_LONG_SIDE = 1600


def _page_files(work, page):
    return sorted((Path(work) / 'ocr').glob(f'{page:04d}*.txt'))


def ocr_text(work, page):
    """Sayfanin OCR metni (cift sayfa taramada iki yarisi birlikte); okunmamissa ''."""
    return '\n\n'.join(_newlines(path.read_bytes().decode('utf-8')) for path in _page_files(work, page))


def edit_path(work, page):
    return Path(work) / EDITS_DIR / f'{page:04d}.txt'


def page_text(work, page):
    """Sayfanin gecerli metni: elle duzeltilmisse o, degilse OCR."""
    path = edit_path(work, page)
    return _newlines(path.read_bytes().decode('utf-8')) if path.exists() else ocr_text(work, page)


def load_texts(pdf, work):
    return [page_text(work, page) for page in range(1, page_count(pdf) + 1)]


def save_page(work, page, text):
    path = edit_path(work, page)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_newlines(text).encode('utf-8'))


def revert_page(work, page):
    edit_path(work, page).unlink(missing_ok=True)


def edited_pages(work):
    folder = Path(work) / EDITS_DIR
    return sorted(int(path.stem) for path in folder.glob('*.txt')) if folder.is_dir() else []


def load_book(work):
    import json
    try:
        data = json.loads((Path(work) / BOOK_FILE).read_bytes().decode('utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_book(work, data):
    """kitap.json: {'title', 'author', 'language', 'chapters': [sinir], 'auto': otomatik mi}."""
    import json
    chapters = []
    for item in data.get('chapters') or []:
        title = ' '.join(str(item.get('title', '')).split())
        if not title:
            raise ValueError('Bölüm adı boş olamaz.')
        chapters.append({'title': title, 'page': int(item['page']), 'ordinal': max(0, int(item.get('ordinal', 0))),
                         'skip': max(0, int(item.get('skip', 0))), 'level': 1 if int(item.get('level', 0)) else 0})
    if not chapters:
        raise ValueError('En az bir bölüm olmalı.')
    chapters.sort(key=lambda item: (item['page'], item['ordinal']))
    value = {'title': ' '.join(str(data.get('title', '')).split()), 'author': ' '.join(str(data.get('author', '')).split()),
             'language': 'en' if data.get('language') == 'en' else 'tr', 'chapters': chapters, 'auto': bool(data.get('auto'))}
    path = Path(work) / BOOK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))
    temp.replace(path)
    return value


_CLEAN_CACHE = {}


def clean_cached(texts, language=None):
    """clean_pages, ayni metin icin bellekten: gozden gecirmede her sayfa gecisinde yuzlerce sayfa yeniden
    temizlenmesin. Sayfa duzeltilince metin degisir, sonuc yeniden hesaplanir. Son birkac kitap tutulur."""
    import hashlib
    key = hashlib.sha1(('\x00'.join(texts) + '\x01' + str(language)).encode('utf-8')).hexdigest()
    if key not in _CLEAN_CACHE:
        if len(_CLEAN_CACHE) >= 4:
            _CLEAN_CACHE.pop(next(iter(_CLEAN_CACHE)))
        _CLEAN_CACHE[key] = clean_pages(texts, language)
    paragraphs, detected, warnings = _CLEAN_CACHE[key]
    return [dict(p) for p in paragraphs], detected, list(warnings)


def detect_structure(pdf, texts, paragraphs, language, log=print):
    """Otomatik bolum sinirlari (yer imleri, icindekiler, basliklar, sayfa duzeni)."""
    outline = outline_chapters(pdf)
    augmented = paragraphs if outline else number_chapters(paragraphs, pdf, log)
    return auto_boundaries(augmented, language, outline, contents_entries(texts),
                           lambda: layout_pages(augmented, pdf))


def analyze(pdf, work, log=print, redetect=False):
    """Gozden gecirme ve EPUB icin kitabin hali: duzeltmeler uygulanmis metin, kayitli (yoksa otomatik) bolumler.
    {'texts', 'paragraphs', 'language', 'warnings', 'book'}; otomatik bolumler kitap.json'a yazilir."""
    texts = load_texts(pdf, work)
    book = load_book(work)
    paragraphs, language, warnings = clean_cached(texts, book.get('language'))
    if not paragraphs:
        raise ValueError("PDF'den metin çıkmadı; OCR ayarlarını (Ayarlar → Kütüphane ve belgeler) kontrol edin.")
    if redetect or not book.get('chapters'):
        guessed_title, guessed_author = guess_title_author(pdf)
        book = save_book(work, {'title': book.get('title') or guessed_title,
                                'author': book.get('author', guessed_author) if book else guessed_author,
                                'language': language, 'auto': True,
                                'chapters': detect_structure(pdf, texts, paragraphs, language, log)})
    return {'texts': texts, 'paragraphs': paragraphs, 'language': book['language'], 'warnings': warnings, 'book': book}


def review(pdf, work, log=print, redetect=False):
    """Gozden gecirme ekraninin ozeti: kitap bilgisi, bolumler (ilk satir ve paragraf sayisiyla), uyarilar."""
    state = analyze(pdf, work, log, redetect)
    chapters = chapters_from(state['paragraphs'], state['book']['chapters'])
    return {'title': state['book']['title'], 'author': state['book']['author'], 'language': state['language'],
            'auto': state['book'].get('auto', False), 'pages': len(state['texts']), 'warnings': state['warnings'],
            'edited': edited_pages(work),
            'chapters': [{'title': c['title'], 'page': c['page'], 'ordinal': c['ordinal'], 'skip': c['skip'],
                          'level': c['level'], 'count': len(c['paragraphs']),
                          'first': (c['paragraphs'][0] if c['paragraphs'] else '')[:120]} for c in chapters]}


def page_image(pdf, page, long_side=REVIEW_LONG_SIDE):
    """Sayfanin JPEG goruntusu (data URL; cift sayfa taramada tamami)."""
    import base64
    import io
    document = documents.open_pdf(pdf)
    try:
        with documents._PDFIUM:
            item = document[page - 1]
            try:
                width, height = item.get_size()
                image = item.render(scale=long_side / max(width, height, 1.0),
                                    fill_color=(255, 255, 255, 255)).to_pil().convert('RGB')
            finally:
                item.close()
    finally:
        with documents._PDFIUM:
            document.close()
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=82)
    return 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def page_view(pdf, work, page):
    """Bir sayfanin gozden gecirmesi: goruntu, gecerli ve OCR metni, temizlenmis paragraflari (bolum baslatmak
    icin sayfadaki siralariyla)."""
    texts = load_texts(pdf, work)
    if not 1 <= page <= len(texts):
        raise ValueError('Sayfa bulunamadı.')
    book = load_book(work)
    paragraphs, _language, _warnings = clean_cached(texts, book.get('language'))
    on_page = [p['text'] for p in paragraphs if p['page'] == page and not p.get('note')]
    return {'page': page, 'pages': len(texts), 'image': page_image(pdf, page), 'text': texts[page - 1],
            'ocr': ocr_text(work, page), 'edited': edit_path(work, page).exists(),
            'paragraphs': [{'ordinal': ordinal, 'text': text[:200]} for ordinal, text in enumerate(on_page)]}


def build_epub(pdf, work, texts=None, title=None, author=None, language=None, log=print):
    """Kitabi EPUB olarak yazar: duzeltilmis metin + kitap.json'daki (yoksa otomatik bulunan) bolumler.
    title/author verilirse kitap.json'a da yazilir. (epub yolu, bilgi); bilgi: dil, bolum basliklari, uyarilar."""
    state = analyze(pdf, work, log)
    book = state['book']
    if title or author is not None or language:
        book = save_book(work, dict(book, title=title or book['title'],
                                    author=book['author'] if author is None else author,
                                    language=language or book['language']))
    chapters = chapters_from(state['paragraphs'], book['chapters'])
    try:
        cover = cover_jpeg(pdf)
    except Exception as error:  # kapak olmadan da kitap uretilir
        log(f'UYARI: Kapak görüntüsü alınamadı: {error}')
        cover = None
    target = Path(work) / (Path(pdf).stem + '.epub')
    write_epub(target, chapters, book['title'], book['author'], book['language'], cover)
    log(f'EPUB oluşturuldu: {target.name} ({len(chapters)} bölüm, dil: {book["language"]})')
    return target, {'language': book['language'], 'chapters': [c['title'] for c in chapters],
                    'warnings': state['warnings'], 'title': book['title'], 'author': book['author']}
