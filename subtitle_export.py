"""Altyazi disa aktarma (F118): bicim donusumu ve Whisper kelime zamanli altyazilar.

Iki tur kaynak vardir:
  - Altyazi belgesi (`parse_by_extension` ciktisi: SRT/ASS/SSA/VTT). Kendi biciminde
    (stiller ve ASS etiketleri korunarak) ya da duz SRT/VTT/ASS olarak yazilir.
  - Whisper transkripti (speech.transcribe segmentleri). Satir zamanli bicimlerin yaninda
    kelime zamanlari varsa karaoke ASS (\\k / \\kf etiketleri: VLC, mpv, MPC-HC gibi
    oynaticilarda kelime kelime renk degisir), kelime vurgulu SRT, kelime zamanli WebVTT,
    tek kelimelik SRT ve JSON yazilabilir.

Zamanlama (subtitle_sync.Timing) ve klip penceresi (`length`) her iki turde de uygulanir.
"""
from __future__ import annotations

import json
import re

import qa
import speech
import subtitle
from subtitle_sync import Timing, ass_time, retime, srt_time, vtt_time

# bicim -> (etiket, uzanti, kelime zamani gerekir mi)
FORMATS = {
    'source': ('Kaynağın biçimi', '', False),
    'srt': ('SRT', 'srt', False),
    'ass': ('ASS', 'ass', False),
    'vtt': ('WebVTT', 'vtt', False),
    'karaoke': ('ASS karaoke (kelime kelime renk)', 'ass', True),
    'highlight': ('SRT kelime vurgulu', 'srt', True),
    'vtt_words': ('WebVTT kelime zamanlı', 'vtt', True),
    'words_srt': ('SRT tek kelime', 'srt', True),
    'json': ('JSON (kelime zamanları)', 'json', True),
}
WORD_FORMATS = tuple(name for name, (_, _, words) in FORMATS.items() if words)
DEFAULT_STYLE = {'font': 'Arial', 'size': 64, 'color': '#FFD400', 'base': '#FFFFFF', 'mode': 'kf'}
_HEX = re.compile(r'#?([0-9a-fA-F]{6})')
ASS_EVENT_FORMAT = ['Layer', 'Start', 'End', 'Style', 'Name', 'MarginL', 'MarginR', 'MarginV', 'Effect', 'Text']


def extension(fmt, kind=''):
    """Bicimin dosya uzantisi; 'source' icin kaynagin uzantisi."""
    if fmt not in FORMATS:
        raise ValueError('Bilinmeyen altyazı biçimi: ' + str(fmt))
    return FORMATS[fmt][1] or kind or 'srt'


def style_of(values):
    """Arayuzden gelen karaoke stili; eksik/bozuk alanlar varsayilana duser."""
    style = dict(DEFAULT_STYLE)
    for key, value in (values or {}).items():
        if key in ('color', 'base') and _HEX.fullmatch(str(value or '')):
            style[key] = '#' + _HEX.fullmatch(str(value)).group(1).upper()
        elif key == 'size':
            try:
                style['size'] = max(20, min(160, int(value)))
            except (TypeError, ValueError):
                pass
        elif key == 'mode' and value in ('k', 'kf'):
            style['mode'] = value
        elif key == 'font' and str(value or '').strip():
            style['font'] = re.sub(r'[,\r\n]', ' ', str(value)).strip()
    return style


def ass_colour(value):
    """'#RRGGBB' -> ASS '&H00BBGGRR'."""
    match = _HEX.fullmatch(str(value or ''))
    rgb = match.group(1) if match else 'FFFFFF'
    return '&H00' + (rgb[4:6] + rgb[2:4] + rgb[0:2]).upper()


def ass_header(style=None, title='Aktar'):
    style = style_of(style)
    return '\n'.join([
        '[Script Info]', f'Title: {title}', 'ScriptType: v4.00+', 'PlayResX: 1920', 'PlayResY: 1080',
        'WrapStyle: 0', 'ScaledBorderAndShadow: yes', '',
        '[V4+ Styles]',
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, '
        'Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
        'Alignment, MarginL, MarginR, MarginV, Encoding',
        # Karaokede PrimaryColour soylenen (vurgulu), SecondaryColour henuz soylenmeyen kelimedir.
        f'Style: Default,{style["font"]},{style["size"]},{ass_colour(style["color"])},'
        f'{ass_colour(style["base"])},&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,80,80,60,1',
    ]).split('\n')


def _ass_text(text):
    return str(text).replace('{', '(').replace('}', ')').replace('\\', '/')


# --- altyazi belgesi ---------------------------------------------------------
def segments_document(segments):
    """Whisper segmentleri -> ('srt', [Cue]) (satirlar 42 karakterde bolunur)."""
    cues = []
    for item in segments:
        text = str(item.get('text', '')).strip()
        if not text:
            continue
        start = float(item['start'])
        end = max(float(item['end']), start + 0.5)
        cues.append(subtitle.Cue(speech.wrap_lines(text).split('\n'), start=srt_time(start), end=srt_time(end)))
    if not cues:
        raise ValueError('Transkriptte altyazı satırı yok.')
    return 'srt', cues


def render_document(kind, payload, fmt='source', timing=None, length=None, style=None):
    """Altyazi belgesini istenen bicimde metne cevirir (zamanlama ve klip penceresi uygulanir)."""
    if fmt in WORD_FORMATS:
        raise ValueError('Bu biçim yalnızca Whisper kelime zamanlarıyla yazılabilir.')
    timing = Timing.of(timing)
    if not timing.identity or length is not None:
        kind, payload = retime(kind, payload, timing, length)
    cues = subtitle.cues_of(kind, payload)
    if fmt == 'source' or fmt == kind or (fmt == 'ass' and kind == 'ssa'):
        if not subtitle.translatable(cues):
            raise ValueError('Seçilen aralıkta altyazı satırı yok.')
        return subtitle.render_by_kind(kind, payload, cues)
    items = qa.transcript_from_cues(cues, keep_lines=True)
    if not items:
        raise ValueError('Seçilen aralıkta altyazı satırı yok.')
    if fmt == 'srt':
        return subtitle.render_srt([subtitle.Cue(item['text'].split('\n'), start=srt_time(item['start']),
                                                 end=srt_time(item['end'])) for item in items])
    if fmt == 'vtt':
        return subtitle.render_vtt([subtitle.Cue(item['text'].split('\n'), start=vtt_time(item['start']),
                                                 end=vtt_time(item['end'])) for item in items])
    if fmt == 'ass':
        plain = style_of(style)
        plain['color'] = plain['base']   # duz altyazida yazi rengi; vurgu rengi yalniz karaokede
        lines = ass_header(plain) + ['']
        cues = [subtitle.Cue([r'\N'.join(_ass_text(line) for line in item['text'].split('\n'))],
                             prefix=['0', ass_time(item['start']), ass_time(item['end']), 'Default', '', '0', '0', '0', ''])
                for item in items]
        return subtitle.render_ass(lines, ASS_EVENT_FORMAT, cues)
    raise ValueError('Bilinmeyen altyazı biçimi: ' + str(fmt))


# --- Whisper kelime zamanlari --------------------------------------------------
def retime_segments(segments, timing=None, length=None):
    """Segment ve kelime zamanlarina donusumu uygular; klip disinda kalanlar atilir."""
    timing = Timing.of(timing)
    result = []
    for item in segments:
        words = []
        for word in item.get('words') or []:
            start, end = timing(word[0]), timing(word[1])
            if end <= 0 or (length is not None and start >= length):
                continue
            words.append([max(0.0, start), end if length is None else min(end, float(length)), str(word[2])])
        start, end = timing(item['start']), timing(item['end'])
        if item.get('words') and not words:
            continue
        if not item.get('words') and (end <= 0 or (length is not None and start >= length)):
            continue
        if words:
            start, end = words[0][0], max(word[1] for word in words)
        result.append({'start': max(0.0, start), 'end': end if length is None else min(end, float(length)),
                       'text': ' '.join(word[2] for word in words) if words else str(item['text']),
                       'words': words})
    return result


def _lines_of(words):
    """Kelimeleri gosterim satirlarina boler: ikinci satirin ilk kelimesinin sirasi (yoksa None)."""
    texts = [' '.join(str(word[2]).split()) for word in words]
    wrapped = speech.wrap_lines(' '.join(texts))
    if '\n' not in wrapped:
        return None
    first, position = len(wrapped.split('\n')[0]), 0
    for index, text in enumerate(texts):
        if position >= first:
            return index or None
        position += len(text) + 1
    return None


def _need_words(segments):
    if not segments or not all(item.get('words') for item in segments):
        raise ValueError('Transkriptte kelime zamanları yok; Whisper ile yeniden çıkarın.')


def karaoke_ass(segments, style=None):
    """Kelime zamanli ASS: her kelime `\\k`/`\\kf` suresince renk degistirir."""
    _need_words(segments)
    style = style_of(style)
    tag = style['mode']
    cues = []
    for item in segments:
        words = item['words']
        start = min(item['start'], words[0][0])
        bounds = [int(round((word[0] - start) * 100)) for word in words] + \
                 [int(round((words[-1][1] - start) * 100))]
        parts = [f'{{\\{tag}{bounds[0]}}}'] if bounds[0] > 0 else []
        cut = _lines_of(words)
        for index, word in enumerate(words):
            if index and index == cut:
                parts[-1] = parts[-1].rstrip() + r'\N'
            duration = max(1, bounds[index + 1] - bounds[index])
            parts.append(f'{{\\{tag}{duration}}}{_ass_text(word[2])} ')
        text = ''.join(parts).rstrip()
        cues.append(subtitle.Cue([text], prefix=['0', ass_time(start), ass_time(max(item['end'], words[-1][1])),
                                                 'Default', '', '0', '0', '0', '']))
    if not cues:
        raise ValueError('Seçilen aralıkta altyazı satırı yok.')
    return subtitle.render_ass(ass_header(style, 'Aktar karaoke') + [''], ASS_EVENT_FORMAT, cues)


def highlight_srt(segments, style=None):
    """Her kelime icin bir SRT girdisi: satirin tamami, o anki kelime renkli (<font color>)."""
    _need_words(segments)
    color = style_of(style)['color']
    cues = []
    for item in segments:
        words = item['words']
        cut = _lines_of(words)
        for index, word in enumerate(words):
            start = item['start'] if index == 0 else word[0]
            end = words[index + 1][0] if index + 1 < len(words) else max(word[1], item['end'])
            if end <= start:
                continue
            tokens = [f'<font color="{color}">{other[2]}</font>' if position == index else other[2]
                      for position, other in enumerate(words)]
            lines = [' '.join(tokens[:cut]), ' '.join(tokens[cut:])] if cut else [' '.join(tokens)]
            cues.append(subtitle.Cue(lines, start=srt_time(start), end=srt_time(end)))
    if not cues:
        raise ValueError('Seçilen aralıkta altyazı satırı yok.')
    return subtitle.render_srt(cues)


def word_vtt(segments):
    """WebVTT, satir icinde kelime zaman damgalariyla (<00:00:01.400><c>kelime</c>)."""
    _need_words(segments)
    cues = []
    for item in segments:
        words = item['words']
        cut = _lines_of(words)
        tokens = [(f'<{vtt_time(word[0])}>' if index else '') + f'<c>{word[2]}</c>'
                  for index, word in enumerate(words)]
        lines = [' '.join(tokens[:cut]), ' '.join(tokens[cut:])] if cut else [' '.join(tokens)]
        cues.append(subtitle.Cue(lines, start=vtt_time(item['start']), end=vtt_time(item['end'])))
    if not cues:
        raise ValueError('Seçilen aralıkta altyazı satırı yok.')
    return subtitle.render_vtt(cues)


def single_word_srt(segments):
    """Her kelime ayri SRT girdisi (kisa video/dikey kurgu icin)."""
    _need_words(segments)
    words = [word for item in segments for word in item['words']]
    cues = []
    for index, word in enumerate(words):
        end = max(word[1], word[0] + 0.25)
        if index + 1 < len(words):
            end = min(end, words[index + 1][0]) if words[index + 1][0] > word[0] else end
        cues.append(subtitle.Cue([word[2]], start=srt_time(word[0]), end=srt_time(end)))
    if not cues:
        raise ValueError('Seçilen aralıkta altyazı satırı yok.')
    return subtitle.render_srt(cues)


def words_json(segments, language=''):
    _need_words(segments)
    return json.dumps({'language': language, 'segments': [
        {'start': round(item['start'], 3), 'end': round(item['end'], 3), 'text': item['text'],
         'words': [{'start': round(word[0], 3), 'end': round(word[1], 3), 'word': word[2]}
                   for word in item['words']]} for item in segments]}, ensure_ascii=False, indent=1) + '\n'


def render_whisper(result, fmt='srt', timing=None, length=None, style=None):
    """Whisper transkriptini istenen bicimde metne cevirir."""
    segments = retime_segments(result.get('segments') or [], timing, length)
    if not segments:
        raise ValueError('Seçilen aralıkta altyazı satırı yok.')
    if fmt == 'karaoke':
        return karaoke_ass(segments, style)
    if fmt == 'highlight':
        return highlight_srt(segments, style)
    if fmt == 'vtt_words':
        return word_vtt(segments)
    if fmt == 'words_srt':
        return single_word_srt(segments)
    if fmt == 'json':
        return words_json(segments, result.get('language', ''))
    kind, payload = segments_document(segments)
    return render_document(kind, payload, 'srt' if fmt == 'source' else fmt, style=style)
