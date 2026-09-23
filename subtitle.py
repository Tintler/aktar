"""Altyazi parse/yaz katmani: SRT, ASS, SSA, WebVTT.

Tasarim ilkesi: yapisal bilgi (timestamp, sira numarasi, ASS tag'leri, stil
bloklari) programa aittir; modele yalnizca cevrilecek GORUNUR METIN gonderilir.
Boylece timestamp bozulmasi, ASS tag bozulmasi ve blok kaybi engellenir veya
dogrulamayla tespit edilir (Cevirgec G42 deseni).

Bir cue'nun metni satirlara ayrilir. Her satir icin yalnizca BASINDA ve SONUNDA
duran ASS tag'leri saklanir; gorunur metin tag'lerden arindirilip modele
gonderilir. Ceviri donunce tag'ler program tarafinda geri konur. Boylece model
tag'leri kopyalamak zorunda kalmaz; yalnizca gorunur metni cevirir. Satir
sonlari da korunur, cunku cue tek ID olarak gonderilir ve model cumleyi butun
olarak gorur.

Model satir sayisini yine de bozarsa (satirlari birlestirir veya fazladan
bolerse) `rebuild` hata vermez: ceviri kaynak satir sayisina gore KELIME
SINIRINDA yeniden bolunur (`_reflow`) ve yapi korunur. Modelin kopyalamasi
gereken hicbir ozel isaret yoktur (F11).
"""
from __future__ import annotations

import re
from collections import Counter

_SRT_TIME = re.compile(r'(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})(.*)')
_VTT_TIME = re.compile(r'((?:\d{1,2}:)?\d{2}:\d{2}\.\d{1,3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}\.\d{1,3})(.*)')
_ASS_OVERRIDE = re.compile(r'\{[^}]*\}')
# Yakalama gruplu split: tag'leri KORUYARAK parcalara ayirir (re.split yakalama
# grubu olmadan eslesmeleri siler; o zaman even/odd indeksleme bozulur).
_ASS_SPLIT = re.compile(r'(\{[^}]*\})')
# ASS satir sonu belirtecleri (\N, \n, \h) ve gercek yeni satir.
_LINE_BREAK = re.compile(r'(\\[Nnh]|\n)')
# Model yaniti bicimleri (parse_translation_response).
_RESPONSE_ID = re.compile(r'^[ \t]*ID[ \t]*:[ \t]*(\d+)[ \t]*(.*)$')
_RESPONSE_TEXT_LABEL = re.compile(r'^[ \t]*TEXT[ \t]*:[ \t]*(.*)$')


class Cue:
    """Tek bir altyazi girdisi. `lines` her zaman METIN satirlaridir.

    `raw` doluysa girdi cevrilmez ve oldugu gibi geri yazilir (ASS `Comment`,
    `Picture` gibi metin disi Events satirlari).
    """

    def __init__(self, lines, start=None, end=None, index=None, extra=None, prefix=None, raw=None, ass_fields=None):
        self.lines = list(lines)
        self.start = start
        self.end = end
        self.index = index
        self.extra = extra if extra is not None else ''
        self.prefix = prefix
        self.raw = raw
        self.ass_fields = ass_fields

    @property
    def translatable(self):
        return self.raw is None

    @property
    def text(self):
        return '\n'.join(self.lines)


def _strip_bom(text):
    return text.lstrip('\ufeff')


def parse_srt(text):
    """SRT -> [Cue]. Bozuk bloklar anlamli ValueError uretir."""
    text = _strip_bom(text).replace('\r\n', '\n').replace('\r', '\n')
    cues, blocks = [], re.split(r'\n[ \t]*\n', text.strip())
    for block in blocks:
        lines = block.split('\n')
        if not lines or not lines[0].strip():
            continue
        index = None
        match = re.fullmatch(r'\s*(\d+)\s*', lines[0])
        if match:
            index = int(match.group(1))
            lines = lines[1:]
        if not lines:
            continue
        timing = _SRT_TIME.match(lines[0].strip())
        if not timing:
            raise ValueError('SRT blok biçimi geçersiz (zaman kodu yok).')
        body = lines[1:]
        if not body:
            raise ValueError('SRT bloğu boş metin içeriyor.')
        cues.append(Cue(body, start=timing.group(1), end=timing.group(2),
                        index=index, extra=timing.group(3).strip()))
    if not cues:
        raise ValueError('SRT dosyasında altyazı girdisi bulunamadı.')
    return cues


def render_srt(cues):
    parts = []
    for order, cue in enumerate(cues, 1):
        index = cue.index if cue.index is not None else order
        extra = (' ' + cue.extra) if cue.extra else ''
        parts.append(f'{index}\n{cue.start} --> {cue.end}{extra}\n' + '\n'.join(cue.lines))
    return '\n\n'.join(parts) + '\n'


def parse_vtt(text):
    """WebVTT -> [Cue]. NOTE/STYLE/REGION bloklari korunmaz (cevrilmez)."""
    text = _strip_bom(text).replace('\r\n', '\n').replace('\r', '\n')
    if not text.lstrip().startswith('WEBVTT'):
        raise ValueError('WebVTT dosyası "WEBVTT" başlığıyla başlamıyor.')
    cues = []
    blocks = re.split(r'\n[ \t]*\n', text.strip())
    for block in blocks[1:]:
        lines = block.split('\n')
        if lines[0].strip().startswith(('NOTE', 'STYLE', 'REGION')):
            continue
        index = None
        if not _VTT_TIME.match(lines[0].strip()) and len(lines) > 1:
            index = lines[0].strip()
            lines = lines[1:]
        timing = _VTT_TIME.match(lines[0].strip())
        if not timing:
            continue
        body = [line for line in lines[1:]]
        if not body:
            continue
        cues.append(Cue(body, start=timing.group(1), end=timing.group(2),
                        index=index, extra=timing.group(3).strip()))
    if not cues:
        raise ValueError('WebVTT dosyasında altyazı girdisi bulunamadı.')
    return cues


def render_vtt(cues):
    blocks = ['WEBVTT']
    for cue in cues:
        header = f'{cue.index}\n' if cue.index else ''
        extra = (' ' + cue.extra) if cue.extra else ''
        blocks.append(f'{header}{cue.start} --> {cue.end}{extra}\n' + '\n'.join(cue.lines))
    return '\n\n'.join(blocks) + '\n'


def parse_ass(text):
    """ASS/SSA -> (meta, events_format, [Cue]).

    `meta`, `[Events]` disindaki tum bolumleri (Script Info, Styles, Fonts...)
    oldugu gibi tasir. Yalnizca `Dialogue` satirlarinin METNI cevrilir;
    `Format:` alan sirasi ve `Comment`/`Picture` satirlari dokunulmaz.
    """
    text = _strip_bom(text).replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    meta, cues = [], []
    events_format = None
    in_events = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            in_events = stripped.lower() == '[events]'
            if not in_events:
                meta.append(line)
            continue
        if in_events:
            if stripped.lower().startswith('format:'):
                events_format = [item.strip() for item in stripped.split(':', 1)[1].split(',')]
                continue
            if stripped.lower().startswith('dialogue:'):
                if events_format is None:
                    raise ValueError('ASS [Events] bölümünde Format satırı yok.')
                fields = line.split(':', 1)[1].split(',', len(events_format) - 1)
                if len(fields) != len(events_format):
                    raise ValueError('ASS Dialogue satırı Format ile uyuşmuyor.')
                # Metin alani (son alan) oldugu gibi korunur; yalnizca onekler
                # kirpilir (Format alan sirasini bozmamak icin).
                text_field = fields[-1]
                prefix = [item.strip() for item in fields[:-1]]
                cues.append(Cue([text_field], prefix=prefix,
                                ass_fields=dict(zip((name.lower() for name in events_format[:-1]), prefix))))
                continue
            if stripped:
                # Comment/Picture/Movie/Sound/Command gibi metin disi Events
                # satirlari konumlarini korumak icin ham olarak saklanir.
                cues.append(Cue([], raw=line))
            continue
        meta.append(line)
    if not any(cue.translatable for cue in cues):
        raise ValueError('ASS dosyasında Dialogue satırı bulunamadı.')
    return meta, events_format, cues


def render_ass(meta, events_format, cues):
    output = list(meta)
    if output and output[-1].strip():
        output.append('')
    output.append('[Events]')
    output.append('Format: ' + ', '.join(events_format))
    for cue in cues:
        if cue.raw is not None:
            output.append(cue.raw)
        else:
            output.append('Dialogue: ' + ','.join(cue.prefix + cue.lines))
    return '\n'.join(output) + '\n'


# --- ASS fontlari (Türkçe karakter uyumu) ---------------------------------
# Kaynak font Türkçe karakterleri çizemiyorsa çıktıda Calibri ile değiştirilir.
# Tespit `fonts` modülünde; burada yalnızca metin dönüşümü yapılır.

_ASS_FN = re.compile(r'\\fn([^\\}]*)(?=[\\}]|$)')


def ass_font_families(text):
    """ASS/SSA metninde kullanılan font ailelerini toplar.

    `[V4+ Styles]`/`[V4 Styles]` `Format` satirindaki `Fontname` sutunu ve
    gorunur metindeki `\\fn<ad>` etiketleri taranir. Bos adlar atlanir.
    """
    families, in_styles, columns = set(), False, None
    for line in str(text).split('\n'):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            in_styles = stripped.lower() in ('[v4+ styles]', '[v4 styles]')
            columns = None
            continue
        if not in_styles:
            continue
        if stripped.lower().startswith('format:'):
            columns = [item.strip().lower() for item in stripped.split(':', 1)[1].split(',')]
            continue
        if stripped.lower().startswith('style:') and columns and 'fontname' in columns:
            index = columns.index('fontname')
            fields = line.split(':', 1)[1].split(',', len(columns) - 1)
            if index < len(fields) and fields[index].strip():
                families.add(fields[index].strip())
    for match in _ASS_FN.finditer(str(text)):
        name = match.group(1).strip()
        if name:
            families.add(name)
    return families


def apply_ass_font_fallback(text, replacements):
    """Turko olmayan fontlari `replacements` eslemesine gore degistirir.

    Hem `[V4+ Styles]` Fontname sutunu hem de gorunur metindeki `\\fn<ad>`
    etiketleri donusturulur. Donen: (yeni_metin, degistirilen_adet).
    """
    replacements = {str(source): str(target) for source, target in (replacements or {}).items()
                    if source and target and source != target}
    if not replacements:
        return text, 0
    changed = 0
    output = []
    in_styles, columns = False, None
    for line in str(text).split('\n'):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            in_styles = stripped.lower() in ('[v4+ styles]', '[v4 styles]')
            columns = None
            output.append(line)
            continue
        if in_styles and stripped.lower().startswith('format:'):
            columns = [item.strip().lower() for item in stripped.split(':', 1)[1].split(',')]
            output.append(line)
            continue
        if in_styles and columns and 'fontname' in columns and stripped.lower().startswith('style:'):
            index = columns.index('fontname')
            head, _, body = line.partition(':')
            fields = body.split(',', len(columns) - 1)
            if index < len(fields) and fields[index].strip() in replacements:
                fields[index] = replacements[fields[index].strip()]
                changed += 1
                line = head + ':' + ','.join(fields)
            output.append(line)
            continue
        if '\\fn' in line:
            def replace(match):
                nonlocal changed
                name = match.group(1).strip()
                if name in replacements:
                    changed += 1
                    return '\\fn' + replacements[name]
                return match.group(0)
            line = _ASS_FN.sub(replace, line)
        output.append(line)
    return '\n'.join(output), changed


def override_tags(text):
    """ASS override tag'lerini ({\\...}) sayar; ceviri sonrasi degismemeli."""
    return Counter(_ASS_OVERRIDE.findall(text))


# --- yapi analizi (tag'ler modele gitmez) ---------------------------------

def _split_lines(text):
    """Metni satirlara ve satir sonu belirteclerine ayirir."""
    pieces = _LINE_BREAK.split(text)
    lines, breaks = [], []
    for index, piece in enumerate(pieces):
        if index % 2:
            breaks.append(piece)
        else:
            lines.append(piece)
    return lines, breaks


def _analyze_line(raw):
    """Tek bir satiri (bas/son tag'leri + gorunur metin) ayristirir.

    Satirin BASINDAKI ve SONUNDAKI tag'ler saklanir; ortadaki tag'ler (orn.
    `C{\\fs38}L...` gibi karakter bazli efektler) sayilir ve dusurulur. Bu
    tag'ler modele gitmedigi icin model tarafindan bozulamaz; dusurulen varsa
    cagiran taraf uyarilir. Donen sozluk: leading, trailing, text, dropped.
    """
    pieces = _ASS_SPLIT.split(raw)
    visible, tags = pieces[0::2], pieces[1::2]
    count = len(visible)
    first = 0
    while first < count and not visible[first].strip():
        first += 1
    last = count - 1
    while last >= 0 and not visible[last].strip():
        last -= 1
    if first > last:
        return {'leading': ''.join(tags), 'trailing': '', 'text': '',
                'mid_tags': [], 'dropped': 0}
    selected = visible[first:last + 1]
    joined = ''.join(selected)
    total = max(1, len(joined))
    position = 0
    mid_tags = []
    for offset, segment in enumerate(selected[:-1]):
        position += len(segment)
        tag_index = first + offset
        if tag_index < len(tags):
            mid_tags.append((position / total, tags[tag_index]))
    return {
        'leading': ''.join(tags[:first]),
        'trailing': ''.join(tags[last:count - 1]),
        'text': joined.strip(),
        'mid_tags': mid_tags,
        'dropped': 0,
    }


def analyze(text):
    """Cue metnini satirlara ve yapiya ayirir.

    Donen: {'lines': [satir sozlukleri], 'breaks': [satir sonu belirtecleri]}.
    """
    raw_lines, breaks = _split_lines(text)
    return {'lines': [_analyze_line(line) for line in raw_lines], 'breaks': breaks}


def send_text(analysis):
    """Cue icin modele gonderilecek TEK metin.

    Gorunur satirlar gercek yeni satirla birlestirilir; boylece model cumleyi
    butun olarak gorur ve satir sonu sayisini dogal bicimde korur. Tag'ler
    metinden cikarilmistir. Cevrilecek gorunur metin yoksa None doner.
    """
    texts = [line['text'] for line in analysis['lines']]
    if not any(text.strip() for text in texts):
        return None
    return '\n'.join(texts)


def dropped_tags(analysis):
    """Geriye uyumluluk: yeni analiz tum ASS tag'lerini korur."""
    return sum(line['dropped'] for line in analysis['lines'])


def _restore_mid_tags(text, mid_tags):
    if not mid_tags:
        return text
    buckets = {}
    for ratio, tag in mid_tags:
        position = max(0, min(len(text), round(float(ratio) * len(text))))
        buckets.setdefault(position, []).append(tag)
    output = []
    for index, char in enumerate(text):
        output.extend(buckets.get(index, []))
        output.append(char)
    output.extend(buckets.get(len(text), []))
    return ''.join(output)


def _reflow(text, weights):
    """Ceviri metnini kaynak satir sayisina gore yeniden boler.

    `weights` kaynak satirlarin gorunur metin uzunluklaridir (bos satir 0).
    Kelimeler satir oranlarina gore dagitilir; bolme her zaman kelime sinirinda
    yapilir, kelime bozulmaz. Ceviri kelime sayisi dolu satir sayisindan azsa
    kelimeler sirayla doldurulur, kalan satirlar bos kalir.
    """
    lines = len(weights)
    if lines <= 1:
        return [' '.join(text.split())]
    words = text.split()
    result = [''] * lines
    targets = [index for index, weight in enumerate(weights) if weight > 0]
    if not targets:
        return result
    if len(words) <= len(targets):
        for word, index in zip(words, targets):
            result[index] = word
        return result
    total = sum(weights[index] for index in targets)
    start = 0
    for position, index in enumerate(targets):
        remaining = len(targets) - position - 1
        if remaining == 0:
            end = len(words)
        else:
            boundary = sum(weights[targets[k]] for k in range(position + 1)) / total
            end = max(start + 1, min(round(boundary * len(words)), len(words) - remaining))
        result[index] = ' '.join(words[start:end])
        start = end
    return result


def rebuild(analysis, translated, note=None):
    """Analiz iskeletini cevrilmis metinle geri birlestirir.

    Model satirlari birlestirir veya fazladan bolerse, ceviri kaynak satir
    sayisina gore yeniden bolunur; yapi (tag'ler, satir sonlari) her durumda
    korunur. `note`, yeniden bolme yapildiginda `(beklenen, bulunan)` ile
    cagrilir (teshis/log icin).
    """
    lines = analysis['lines']
    parts = [part.strip() for part in translated.split('\n')]
    if len(parts) != len(lines):
        if note is not None:
            note(len(lines), len(parts))
        weights = [len(line['text']) if line['text'].strip() else 0 for line in lines]
        parts = _reflow(translated, weights)
    output = []
    for index, line in enumerate(lines):
        if index:
            output.append(analysis['breaks'][index - 1])
        visible = _restore_mid_tags(parts[index].strip(), line.get('mid_tags', []))
        output.append(line['leading'] + visible + line['trailing'])
    return ''.join(output)


def strip_spurious_braces(text):
    """Modelin gorunur metne ekledigi yapisal olmayan suslu parantezleri temizler.

    Gercek tag'ler metinden cikarilmistir; modele ait `{...}` bloklari ASS
    ciktisini bozar. Donen: (temiz_metin, temizlenen_adet).
    """
    removed = 0

    def replace(_match):
        nonlocal removed
        removed += 1
        return ''

    text = _ASS_OVERRIDE.sub(replace, text)
    lone = text.count('{') + text.count('}')
    if lone:
        removed += lone
        text = text.replace('{', '').replace('}', '')
    return text, removed


def translatable(cues):
    """Cevrilecek (ham olmayan) girdiler."""
    return [cue for cue in cues if cue.translatable]


def validate_structure(source_cues, translated_cues):
    """Yapisal bozulmayi tespit eder: girdi sayisi, satir sayisi, tag sayisi.

    Ham (cevrilmeyen) girdiler karsilastirmaya girmez. Yapi program tarafinda
    kuruldugu icin bu kontrol bir guvenlik agidir.
    """
    source_cues = translatable(source_cues)
    translated_cues = translatable(translated_cues)
    if len(source_cues) != len(translated_cues):
        raise ValueError('Yapısal altyazı işaretleri korunmadı: girdi sayısı değişti '
                         f'({len(source_cues)} -> {len(translated_cues)}).')
    for position, (source, translated) in enumerate(zip(source_cues, translated_cues)):
        if len(source.lines) != len(translated.lines):
            raise ValueError('Yapısal altyazı işaretleri korunmadı: '
                             f'girdi {position + 1} satır sayısı değişti.')
        if override_tags(source.text) != override_tags(translated.text):
            raise ValueError('Yapısal altyazı işaretleri korunmadı: '
                             f'girdi {position + 1} ASS etiket sayısı değişti.')


def batch_cues(cues, size):
    """Cevrilecek girdileri modele gonderilecek partilere boler (ham girdiler atlanir)."""
    size = max(1, int(size))
    items = translatable(cues)
    return [items[index:index + size] for index in range(0, len(items), size)]


def build_translation_request(texts, start_id):
    """Modele gonderilecek ID/TEXT metnini uretir. `texts` bir metin listesidir.

    Her eleman AYRI bir ID olarak gonderilir; ID'ler `start_id`den baslar.
    """
    lines = []
    for offset, text in enumerate(texts):
        lines.append(f'ID: {start_id + offset}')
        lines.append('TEXT: ' + str(text))
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def parse_by_extension(text, suffix):
    """Dosya uzantisina gore parse eder. Donen: (kind, payload).

    kind: 'srt' | 'ass' | 'ssa' | 'vtt'. payload: SRT/VTT icin [Cue];
    ASS/SSA icin (meta, events_format, [Cue]).
    """
    suffix = str(suffix).lower().lstrip('.')
    if suffix == 'srt':
        return 'srt', parse_srt(text)
    if suffix in ('ass', 'ssa'):
        meta, events_format, cues = parse_ass(text)
        return suffix, (meta, events_format, cues)
    if suffix == 'vtt':
        return 'vtt', parse_vtt(text)
    raise ValueError('Desteklenmeyen altyazı uzantısı: .' + suffix)


def render_by_kind(kind, payload, cues):
    """`parse_by_extension` ciktisini ayni formatta metne cevirir."""
    if kind == 'srt':
        return render_srt(cues)
    if kind in ('ass', 'ssa'):
        return render_ass(payload[0], payload[1], cues)
    return render_vtt(cues)


def cues_of(kind, payload):
    """payload icinden cevrilecek Cue listesini dondurur."""
    return payload[2] if kind in ('ass', 'ssa') else payload


def _parse_labeled_response(text):
    """Accept explicit IDs; never overwrite duplicate entries or body text."""
    found = {}
    current = None
    body = []
    label_seen = False
    preamble = []
    for line in str(text).splitlines():
        match = _RESPONSE_ID.match(line)
        if match:
            if current is not None:
                found[current] = '\n'.join(body).strip()
            current = int(match.group(1))
            if current in found:
                raise ValueError('Çeviri kimlikleri: tekrarlanan ID=' + str(current))
            value = match.group(2)
            label = _RESPONSE_TEXT_LABEL.match(value)
            label_seen = bool(label)
            body = [label.group(1) if label else value] if value else []
        elif current is None:
            if line.strip():
                preamble.append(line)
        else:
            label = _RESPONSE_TEXT_LABEL.match(line)
            if label:
                if label_seen or any(part.strip() for part in body):
                    raise ValueError('Çeviri kimlikleri: yinelenen TEXT etiketi.')
                label_seen = True
                body.append(label.group(1))
            else:
                if re.match(r'^\s*(?:ID|TEXT)\s*:', line, re.I):
                    raise ValueError('Çeviri kimlikleri: bozuk ID/TEXT satırı.')
                body.append(line)
    if current is not None:
        found[current] = '\n'.join(body).strip()
        if preamble:
            raise ValueError('Çeviri kimlikleri: ilk ID öncesinde beklenmeyen metin.')
    return found


def parse_translation_response(text, expected_ids):
    """Multiple entries require explicit IDs. A singleton may be plain text.

    Native numbering is subtitle content, never an implicit transport ID.
    Ambiguous batch replies are retried in smaller requests by the engine.
    """
    expected_ids = [int(identifier) for identifier in expected_ids]
    text = str(text).strip()
    found = _parse_labeled_response(text)
    if not found and len(expected_ids) == 1:
        if re.search(r'(?mi)^\s*(?:ID|TEXT)\s*:', text):
            raise ValueError('Çeviri kimlikleri: bozuk ID/TEXT biçimi.')
        found = {expected_ids[0]: text}
    missing = [identifier for identifier in expected_ids if identifier not in found]
    extra = [identifier for identifier in found if identifier not in expected_ids]
    if missing or extra:
        raise ValueError('Çeviri kimlikleri: eksik=' + str(missing) + ' fazla=' + str(extra))
    if any(not value.strip() for value in found.values()):
        raise ValueError('Çeviri kimlikleri: boş metin döndü.')
    return found


def translation_groups(cues, analyses):
    """Share only identical, touching/overlapping positioned ASS events.

    Sorting is only for finding temporal components, never for output order.
    Each component keeps every original cue and its own formatting skeleton.
    Plain dialogue and SRT/VTT entries remain independent.
    """
    candidates = {}
    groups = []
    def centiseconds(value):
        match = re.fullmatch(r'(\d+):(\d{2}):(\d{2})\.(\d{2})', value)
        if not match:
            raise ValueError(value)
        h, m, sec, cs = map(int, match.groups())
        return ((h * 60 + m) * 60 + sec) * 100 + cs
    for index, (cue, analysis) in enumerate(zip(cues, analyses)):
        fields = cue.ass_fields
        visible = send_text(analysis)
        if not fields or not visible or not re.search(r'\\(?:pos|move)\s*\(', cue.text):
            groups.append([index])
            continue
        try:
            start, end = centiseconds(fields['start']), centiseconds(fields['end'])
            if end <= start:
                raise ValueError('duration')
        except (KeyError, ValueError):
            groups.append([index])
            continue
        key = (visible, tuple(sorted((k, v) for k, v in fields.items()
                                     if k not in ('start', 'end'))))
        candidates.setdefault(key, []).append((start, end, index))
    for events in candidates.values():
        current = []
        until = -1
        for start, end, index in sorted(events):
            if current and start > until:
                groups.append(sorted(current))
                current = []
            current.append(index)
            until = max(until, end) if len(current) > 1 else end
        if current:
            groups.append(sorted(current))
    return sorted(groups, key=lambda group: group[0])
