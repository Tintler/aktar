"""Altyazi zamanlamasi (F118): kaydirma, hiz duzeltme ve Whisper'a gore otomatik hizalama.

Zamanlama tek bir dogrusal donusumdur: yeni = eski * scale + offset. Kaydirma yalnizca
`offset`; kare hizi farki (23.976 <-> 25 gibi) `scale` ile duzeltilir. Iki noktadan esitleme
ve otomatik hizalama da ayni iki sayiyi uretir; oynatici, disa aktarma ve klip ayni
donusumu kullanir.

Otomatik hizalama dilden bagimsizdir (ceviri altyazi da hizalanabilir): Whisper'in
konusma araliklari ile altyazi satirlarinin araliklari zaman eksenine bit dizisi olarak
yazilir ve her kaydirma icin ortusme sayilir (ffsubsync yaklasimi). Altyazi genellikle konusma
bittikten sonra da ekranda kaldigi icin satir baslangiclarinin konusma baslangiclarina denk
gelmesi ayrica puanlanir. Python'un buyuk tamsayilari bit dizisi olarak kullanilir; numpy
gerekmez.
"""
from __future__ import annotations

import copy
import math

import qa
import subtitle

# Yaygin kare hizi uyusmazliklari (altyazi zamani * oran).
FRAME_RATIOS = (1.0, 25 / 23.976, 23.976 / 25, 24 / 23.976, 23.976 / 24, 25 / 24, 24 / 25)
COARSE_HZ = 10          # kaba arama cozunurlugu (0.1 sn)
FINE_HZ = 100           # ince ayar cozunurlugu (0.01 sn)
MAX_OFFSET = 120.0      # en fazla bu kadar saniye kaydirma aranir
RATIO_PREFERENCE = 1.04  # 1.0 disindaki oran ancak bu kadar daha iyi uyarsa secilir
ONSET_WEIGHT = 0.6       # satir baslangici konusma baslangicina denk gelirse eklenen agirlik


# --- zaman bicimleri --------------------------------------------------------
def _parts(seconds, unit):
    total = max(0, int(round(float(seconds) * unit)))
    hours, rest = divmod(total, 3600 * unit)
    minutes, rest = divmod(rest, 60 * unit)
    secs, fraction = divmod(rest, unit)
    return hours, minutes, secs, fraction


def srt_time(seconds):
    hours, minutes, secs, millis = _parts(seconds, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}'


def vtt_time(seconds):
    hours, minutes, secs, millis = _parts(seconds, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}'


def ass_time(seconds):
    hours, minutes, secs, centis = _parts(seconds, 100)
    return f'{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}'


TIME_FORMATS = {'srt': srt_time, 'vtt': vtt_time, 'ass': ass_time, 'ssa': ass_time}


# --- donusum ----------------------------------------------------------------
class Timing:
    """yeni = eski * scale + offset."""

    def __init__(self, scale=1.0, offset=0.0):
        self.scale = float(scale or 1.0)
        self.offset = float(offset or 0.0)

    @classmethod
    def of(cls, value):
        """Arayuzden gelen {'scale', 'offset'} (ya da None) -> Timing."""
        if isinstance(value, Timing):
            return value
        value = value or {}
        scale = float(value.get('scale') or 1.0)
        if not 0.5 <= scale <= 2.0:
            raise ValueError('Zamanlama hızı 0,5 ile 2 arasında olmalı.')
        return cls(scale, float(value.get('offset') or 0.0))

    @property
    def identity(self):
        return abs(self.scale - 1.0) < 1e-9 and abs(self.offset) < 1e-9

    def __call__(self, seconds):
        return float(seconds) * self.scale + self.offset

    def to_dict(self):
        return {'scale': self.scale, 'offset': self.offset}


def two_point(first, second):
    """Iki esleme [(altyazi_zamani, dogru_zaman)] -> Timing. Tek nokta: yalnizca kaydirma."""
    (source_a, target_a) = first
    if second is None:
        return Timing(1.0, target_a - source_a)
    (source_b, target_b) = second
    if abs(source_b - source_a) < 1.0:
        raise ValueError('İki nokta arasında en az 1 saniye olmalı.')
    scale = (target_b - target_a) / (source_b - source_a)
    return Timing.of({'scale': scale, 'offset': target_a - source_a * scale})


def retime(kind, payload, mapper, length=None):
    """Altyazi belgesinin (parse_by_extension ciktisi) zamanlarini `mapper` ile degistirir.

    Kaynak payload degismez; kopya doner. Bitisi 0'dan once kalan satirlar atilir.
    `length` verilirse (klip) bu sureden sonra baslayan satirlar atilir, tasanlar kirpilir.
    ASS'de Comment gibi metin disi satirlar oldugu gibi kalir.
    """
    payload = copy.deepcopy(payload)
    cues = subtitle.cues_of(kind, payload)
    fmt = TIME_FORMATS[kind]
    kept = []
    for cue in cues:
        if not cue.translatable:
            kept.append(cue)
            continue
        start, end = (cue.ass_fields.get('start'), cue.ass_fields.get('end')) if cue.ass_fields \
            else (cue.start, cue.end)
        try:
            start, end = mapper(qa.parse_time(start)), mapper(qa.parse_time(end))
        except (TypeError, ValueError):
            kept.append(cue)
            continue
        if end <= 0 or (length is not None and start >= length):
            continue
        start, end = max(0.0, start), end if length is None else min(end, float(length))
        if cue.ass_fields:
            _set_ass_times(payload[1], cue, fmt(start), fmt(end))
        else:
            cue.start, cue.end = fmt(start), fmt(end)
        kept.append(cue)
    if kind in ('ass', 'ssa'):
        return kind, (payload[0], payload[1], kept)
    return kind, kept


def _set_ass_times(events_format, cue, start, end):
    names = [name.lower() for name in events_format[:-1]]
    for name, value in (('start', start), ('end', end)):
        if name in names:
            cue.prefix[names.index(name)] = value
        cue.ass_fields[name] = value


# --- otomatik hizalama -------------------------------------------------------
def speech_intervals(segments):
    """Whisper sonucundan konusma araliklari: kelime zamanlari varsa onlar, yoksa satirlar."""
    intervals = []
    for item in segments or []:
        words = item.get('words') or []
        if words:
            intervals += [(float(word[0]), float(word[1])) for word in words]
        else:
            intervals.append((float(item['start']), float(item['end'])))
    return [(start, end) for start, end in intervals if end > start]


def cue_intervals(kind, payload):
    """Altyazi satirlarinin araliklari (ayni metnin tekrarlari birlesik)."""
    return [(item['start'], item['end']) for item in
            qa.transcript_from_cues(subtitle.cues_of(kind, payload)) if item['end'] > item['start']]


def _mask(intervals, hz, mapper=None, pad=0, widen=0.0):
    """Araliklari bit dizisine (int) yazar; `pad` ornek kadar saga kaydirilir (negatif kaydirma icin).
    `widen`: her araligi iki yana bu kadar saniye genisletir (baslangic toleransi)."""
    mask = 0
    for start, end in intervals:
        if mapper is not None:
            start, end = mapper(start), mapper(end)
        first = max(0, int(round((start - widen) * hz)) + pad)
        last = max(first + 1, int(round((end + widen) * hz)) + pad)
        mask |= ((1 << (last - first)) - 1) << first
    return mask


def _onsets(intervals, gap=0.3):
    """Konusma baslangiclari: en az `gap` saniyelik sessizlikten sonra baslayan araliklar."""
    starts, until = [], None
    for start, end in sorted(intervals):
        if until is None or start - until >= gap:
            starts.append(start)
        until = end if until is None else max(until, end)
    return starts


def _scores(sub, target, low, high):
    """[low, high] ornek kaydirmalarinin her biri icin ortusen bit sayisi."""
    return [((sub << shift if shift >= 0 else sub >> -shift) & target).bit_count()
            for shift in range(low, high + 1)]


def _peak(values):
    """En yuksek degerin sirasi; esit degerli duzlukte ortadaki (altyazi konusmadan uzun kalinca
    ortusme genis bir aralikta ayni kalir)."""
    best = max(values)
    first = values.index(best)
    last = first
    while last + 1 < len(values) and values[last + 1] >= best - 1e-9:
        last += 1
    return (first + last) // 2


def _combined(cues, speech, hz, mapper, low, high, pad, tolerance):
    """Her kaydirma icin skor: araliklarin benzerligi (kosinus) + satir baslangiclarinin konusma
    baslangiclarina denk gelme orani (ONSET_WEIGHT agirlikli). Donen: (skorlar, benzerlikler)."""
    sub = _mask(cues, hz, mapper=mapper, pad=pad)
    speech_mask = _mask(speech, hz, pad=pad)
    norm = math.sqrt(max(1, sub.bit_count()) * max(1, speech_mask.bit_count()))
    overlap = [value / norm for value in _scores(sub, speech_mask, low, high)]
    starts = _mask([(start, start) for start, _ in cues], hz, mapper=mapper, pad=pad)
    onsets = _mask([(start, start) for start in _onsets(speech)], hz, pad=pad, widen=tolerance)
    hits = [value / max(1, len(cues)) for value in _scores(starts, onsets, low, high)]
    return [a + ONSET_WEIGHT * b for a, b in zip(overlap, hits)], overlap


def auto_align(cues, speech, max_offset=MAX_OFFSET, ratios=FRAME_RATIOS):
    """Altyazi araliklarini konusma araliklarina en iyi oturtan Timing ve guven bilgisi.

    Donen: {'scale', 'offset', 'score' (0-1 benzerlik), 'confidence' ('high'|'medium'|'low'),
    'before' (dokunulmamis benzerlik)}.
    """
    cues = sorted(item for item in cues if item[1] > item[0])
    speech = sorted(item for item in speech if item[1] > item[0])
    if len(cues) < 3 or len(speech) < 3:
        raise ValueError('Hizalamak için yeterli altyazı ya da konuşma yok.')
    pad = int(max_offset * COARSE_HZ)
    candidates = []
    for ratio in ratios:
        scores, overlap = _combined(cues, speech, COARSE_HZ, lambda t, ratio=ratio: t * ratio,
                                    -pad, pad, pad, 0.25)
        index = _peak(scores)
        candidates.append({'ratio': ratio, 'index': index, 'value': scores[index], 'scores': scores,
                           'score': overlap[index], 'before': overlap[pad]})
    plain = candidates[0]
    best = max(candidates, key=lambda item: item['value'])
    if best is not plain and best['value'] < plain['value'] * RATIO_PREFERENCE:
        best = plain
    # Ince ayar: kaba sonucun +-0.3 sn cevresinde 0.01 sn adimla.
    ratio = best['ratio']
    fine_pad = int((max_offset + 1) * FINE_HZ)
    centre = (best['index'] - pad) * (FINE_HZ // COARSE_HZ)
    fine, _ = _combined(cues, speech, FINE_HZ, lambda t: t * ratio, centre - 30, centre + 30, fine_pad, 0.08)
    offset = (centre - 30 + _peak(fine)) / FINE_HZ
    # Guven: en iyi tepe, ondan en az 2 sn uzaktaki en iyi ikinci tepeye gore ne kadar belirgin.
    scores = best['scores']
    others = [value for index, value in enumerate(scores) if abs(index - best['index']) > 2 * COARSE_HZ]
    margin = best['value'] / max(1e-9, max(others) if others else 0.0)
    confidence = 'high' if margin >= 1.3 and best['score'] >= 0.45 else         'medium' if margin >= 1.12 and best['score'] >= 0.3 else 'low'
    return {'scale': ratio, 'offset': round(offset, 3), 'score': round(best['score'], 3),
            'before': round(plain['before'], 3), 'confidence': confidence}
