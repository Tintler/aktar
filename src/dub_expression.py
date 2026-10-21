"""Dublajda ifadeyi aktarma (F172): ozgun konusmadaki gulme, aglama, ic cekme, fisilti, bagirma ve duraklamalar.

Kaynaklar:
  - Altyazidaki ses notlari: '(laughs)', '[GÜLER]', '*sighs*', '(iç çeker)' ... Not okunmaz (her motorda metinden
    cikarilir); ifade olarak satira gecer. Yalnizca nottan olusan satir ('[Kahkahalar]') bir sonraki satira gecer.
  - Ozgun ses (voice_split.expression): AudioSet ses olaylari (CED modeli) satirin araliginda (biraz oncesi dahil)
    esigi asarsa satirin ifadesi olur; konusma araliklari (Silero VAD) satir icindeki duraklamalari verir.
Ifadeler Drama 3 etiketine cevrilir (drama3_tags; Ayarlar'da secilen etiketlerden ilk uyan); Drama 3 disindaki
motorlar etiketi almaz (tts.Engines.say). Duraklama her motorda gecerlidir: satir, ozgun konusmanin durdugu yere en
yakin noktalama isaretinden ikiye bolunur ve ikinci parca ozgun konusmanin yeniden basladigi anda calar.
Turkceye budanmis Drama 3'te nokta etiketleri yalnizca parcanin basinda calistigi icin her satir (ya da duraklamayla
bolunen parca) en fazla bir etiket alir.
"""
from __future__ import annotations

import re

import drama3_tags

# ifade -> Drama 3 etiketleri (oncelik sirasiyla; Ayarlar'da secili ilk etiket kullanilir)
TAGS = {
    'laugh': ('[laughs]', '[small laugh]'),
    'cry': ('[crying]', '[sad]'),
    'sigh': ('[sighs]',),
    'whisper': drama3_tags.WHISPER_TAGS,
    'shout': ('[shouting]',),
    'breath': ('[breathy]', '[shaky breath]'),
    'cough': ('[clear throat]',),
}
# ses olayi esikleri (CED olasiligi; Code Geass / Carbonaro denemeleriyle): ic cekme ve nefes konusmada sik ve
# dusuk olasilikla gorunur, yuksek esik ister
THRESHOLDS = {'laugh': 0.3, 'cry': 0.35, 'sigh': 0.55, 'whisper': 0.35, 'shout': 0.35, 'breath': 0.45, 'cough': 0.45}
ORDER = ('laugh', 'cry', 'shout', 'whisper', 'sigh', 'breath', 'cough')   # ayni olasilikta oncelik
LEAD = 1.0          # satirdan bu kadar onceki ses olayi da satirin (gulup konusmaya baslama); onceki satira tasmaz
PAUSE = 0.6         # satir icinde bu kadar sessizlik duraklamadir
PAUSE_SIDE = 0.3    # duraklamanin iki yaninda en az bu kadar konusma
SPLIT_TOLERANCE = 0.25   # bolme noktasi, metinde ozgun duraklamanin oranina bu kadar yakin olmali
NOTE_CARRY = 2.0    # yalnizca nottan olusan satirin ifadesi bu kadar sonraki satira gecer

NOTE_WORDS = (
    ('laugh', r'laugh\w*|chuckl\w*|giggl\w*|snicker\w*|güle?r|gül(?:üyor|üşme\w*|üş\w*|me|erek)|kahkaha\w*|kıkırda\w*'),
    ('cry', r'cr(?:y|ies|ying)|sob\w*|weep\w*|ağla\w*|hıçkır\w*'),
    ('sigh', r'sigh\w*|iç (?:çeker|çekiyor|çekme|çekerek|geçirir)'),
    ('whisper', r'whisper\w*|fısılda\w*|fısıltı\w*'),
    ('shout', r'shout\w*|yell\w*|scream\w*|bağır\w*|haykır\w*|çığlık\w*'),
    ('breath', r'gasp\w*|pant\w*|breath\w*|nefes\w*|soluk\w*'),
    ('cough', r'cough\w*|clears? throat|öksür\w*|boğaz\w*'),
)
_NOTE_WORDS = tuple((kind, re.compile(r'(?<!\w)(?:' + pattern + r')(?!\w)', re.I | re.U)) for kind, pattern in NOTE_WORDS)
# kisa notlar: [..], (..), *..*; ♪ isaretleri. En fazla 5 kelime (uzun parantezli cumle not degildir)
_NOTE = re.compile(r'\[([^\[\]]{1,50})\]|\(([^()]{1,50})\)|\*([^*]{1,50})\*')
_MUSIC = re.compile(r'[♪♫]+')
_SPLIT = re.compile(r'(?:\.\.\.|[,.;:…?!—–])(?=\s)')


def note_kind(note):
    """Ses notunun ifadesi ('' tanimadik)."""
    for kind, pattern in _NOTE_WORDS:
        if pattern.search(note):
            return kind
    return ''


def _is_note(content):
    content = content.strip()
    if not content or len(content.split()) > 5:
        return False
    letters = [c for c in content if c.isalpha()]
    return bool(note_kind(content)) or (bool(letters) and all(c.isupper() for c in letters))   # SDH: [MUSIC], (JOHN)


def clean(text):
    """Satirdan ses notlarini cikarir: (okunacak metin, notlardaki ifade ya da '')."""
    kind = ''

    def drop(match):
        nonlocal kind
        content = next(group for group in match.groups() if group is not None)
        if not _is_note(content):
            return match.group(0)
        kind = kind or note_kind(content)
        return ' '
    text = _MUSIC.sub(' ', _NOTE.sub(drop, str(text)))
    text = ' '.join(text.split())
    text = re.sub(r'^[\s,.;:–—-]+(?=\w)', '', text)   # '(laughs) - Evet' -> 'Evet'
    return text, kind


def tag_of(kind, allowed=None):
    """Ifadenin Drama 3 etiketi: secili etiketlerden ilk uyan ('' yok)."""
    chosen = drama3_tags.allowed(allowed)
    return next((tag for tag in TAGS.get(kind, ()) if tag in chosen), '')


def sound_at(analysis, start, end, allowed=None, after=None):
    """[start - LEAD (ama `after`dan once degil), end] araligindaki en guclu ses olayi ('' yoksa); yalnizca etiketi secili olanlar."""
    if not analysis:
        return ''
    hop = float(analysis.get('hop') or 0.5)
    window = float(analysis.get('window') or 2.0)
    best, score = '', 0.0
    for kind in ORDER:
        values = (analysis.get('sounds') or {}).get(kind) or []
        if not values or not tag_of(kind, allowed):
            continue
        begin = start - LEAD if after is None else max(start - LEAD, min(after, start))
        first = max(0, int((begin - window / 2) / hop + 0.999))   # pencere ortasi araliga dusmeli
        last = min(len(values) - 1, int((end - window / 2) / hop))
        peak = max(values[first:last + 1], default=0.0) if last >= first else 0.0
        if peak >= THRESHOLDS[kind] and peak / THRESHOLDS[kind] > score:
            best, score = kind, peak / THRESHOLDS[kind]
    return best


def pauses(speech, start, end):
    """Satir icindeki duraklamalar: [(sessizlik_basi, sessizlik_sonu, onceki_konusma_orani)]."""
    parts = [(max(a, start), min(b, end)) for a, b in speech or () if min(b, end) - max(a, start) > 0.05]
    total = sum(b - a for a, b in parts)
    if len(parts) < 2 or total <= 0:
        return []
    result, before = [], 0.0
    for (a, b), (c, d) in zip(parts, parts[1:]):
        before += b - a
        after = total - before
        if c - b >= PAUSE and before >= PAUSE_SIDE and after >= PAUSE_SIDE:
            result.append((b, c, before / total))
    return result


def split_at(text, fraction, tolerance=SPLIT_TOLERANCE):
    """Metni `fraction` oranina en yakin noktalama isaretinden ikiye boler: (bas, son) ya da None."""
    best = None
    for match in _SPLIT.finditer(text):
        cut = match.end()
        head, tail = text[:cut].strip(), text[cut:].strip()
        if not head or not re.search(r'\w', tail):
            continue
        distance = abs(cut / len(text) - fraction)
        if distance <= tolerance and (best is None or distance < best[0]):
            best = (distance, head, tail)
    return best[1:] if best else None


def apply(lines, analysis=None, allowed=None, tags=True):
    """Satirlara ifade ekler: notlar cikarilir, duraklamada bolunur, 'tag' anahtari eklenir (Drama 3 etiketi).
    `tags` False ise yalnizca notlar cikarilir ve duraklamalar uygulanir. Donen: (satirlar, {'tagged', 'paused'})."""
    speech = (analysis or {}).get('speech') or []
    result, carry, tagged, paused, previous = [], None, 0, 0, None
    for line in lines:
        text, note = clean(line['text'])
        if carry and line['start'] - carry[1] > NOTE_CARRY:
            carry = None
        if not text:   # yalnizca not: ifadesi sonraki satira
            if note:
                carry = (note, line['end'])
            continue
        note = note or (carry[0] if carry else '')
        carry = None
        pieces = [(line['start'], line['end'], text)]
        for silent_start, silent_end, fraction in pauses(speech, line['start'], line['end']):
            first_start, _first_end, rest = pieces[-1]
            done = sum(len(piece[2]) for piece in pieces[:-1])
            share = (len(text) * fraction - done) / max(1, len(rest))
            cut = split_at(rest, share)
            if cut:
                pieces[-1] = (first_start, silent_start, cut[0])
                pieces.append((silent_end, line['end'], cut[1]))
                paused += 1
        for number, (start, end, piece) in enumerate(pieces):
            item = dict(line, start=start, end=max(start, end), text=piece)
            item.pop('tag', None)
            if tags:
                kind = (note if number == 0 else '') or sound_at(analysis, start, end, allowed, previous)
                tag = tag_of(kind, allowed)
                if tag:
                    item['tag'] = tag
                    tagged += 1
            result.append(item)
            previous = item['end']
    return result, {'tagged': tagged, 'paused': paused}
