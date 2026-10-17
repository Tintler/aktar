"""Videoya Soru Sor cekirdegi: zaman damgali transkript, video haritasi, atifli cevap.

Video icerigi hakkinda yerel modelle soru-cevap. Qt'den
bagimsizdir; gui.py ve testler ayni mantigi kullanir. Kaynak video SALT-OKUNUR:
yalnizca secilen altyazi stream'i work_files altina cikarilir.

Akis:
  1. transkript: altyazi cue'lari -> [{'start', 'end', 'text'}] (saniye)
  2. bolumler: gomulu chapter'lar veya ~4 dakikalik zaman parcalari
  3. hazirlik: transkript baglama sigiyorsa tek istekte genel ozet + onerilen
     sorular ('full'); sigmiyorsa once bolum ozetleri, sonra genel ozet ('map')
  4. soru: baglam kurulur (tam transkript ya da harita + ilgili bolumlerin
     ayrintisi), model Turkce cevap + [m:ss] atif uretir; atiflar transkripte
     gore dogrulanir, uydurma zaman damgalari ayiklanir.
"""
from __future__ import annotations

import json
import re
from bisect import bisect_right
from pathlib import Path

import media
import subtitle
from app_core import (APP_DIR, Client, GracefulStop, digest, load_config, qa_config, read,
                      retryable_translation_error, save_json, visible_cue_text)

CACHE_VERSION = 1
DEFAULT_QUESTIONS = ('Videoyu özetle', 'Ana konular neler?')
HISTORY_TURNS = 4
LINE_SECONDS = 15.0       # bir transkript satirinda birlestirilecek en uzun sure
LINE_CHARS = 280
SECTION_SECONDS = 240.0   # chapter yoksa bolum uzunlugu
SECTION_CHARS = 6000
CITATION_TOLERANCE = 15.0  # atif ile en yakin transkript satiri arasindaki en buyuk fark
ROUTE_LIMIT = 6
_NOISY_TRACK = re.compile(r'\b(?:signs?|songs?|forced|karaoke)\b', re.IGNORECASE)

_TIME = re.compile(r'(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?')
_STAMP = r'(?:\d+:)?\d{1,2}:\d{2}'
_BRACKET = re.compile(r'\[([^\[\]\n]{3,80})\]')
_CITE_ITEM = re.compile(r'\s*(' + _STAMP + r')(?:\s*[-–—]\s*(' + _STAMP + r'))?\s*')
_BARE = re.compile(r'(?<![\d:.,\[])(' + _STAMP + r')(?:\s*[-–—]\s*(' + _STAMP + r'))?(?![\d:])')
_THINK = re.compile(r'(?is)<think>.*?</think>')
# SRT/mov_text bicim etiketleri (<font size="54">, <i>, </b>...): gosterimde ve transkriptte atilir.
_MARKUP_TAG = re.compile(r'</?[A-Za-z][\w-]*(?:\s[^<>]*)?/?>')


# --- zaman ----------------------------------------------------------------
def parse_time(value):
    """'00:01:02,345' (SRT), '0:01:02.34' (ASS), '01:02.345' (VTT), '12:34' -> saniye."""
    match = _TIME.fullmatch(str(value).strip())
    if not match:
        raise ValueError('Zaman damgası geçersiz: ' + str(value))
    hours, minutes, seconds, fraction = match.groups()
    total = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
    if fraction:
        total += int(fraction) / (10 ** len(fraction))
    return float(total)


def format_time(seconds):
    """Saniye -> 'm:ss' veya 'h:mm:ss'."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'


def format_range(start, end=None):
    if end is None or int(end) <= int(start):
        return format_time(start)
    return format_time(start) + '-' + format_time(end)


# --- transkript -----------------------------------------------------------
def _cue_times(cue):
    if cue.ass_fields:
        return cue.ass_fields.get('start'), cue.ass_fields.get('end')
    return cue.start, cue.end


def transcript_from_cues(cues, keep_lines=False):
    """Altyazi cue'larini zamana gore sirali gorunur metin segmentlerine cevirir.

    ASS etiketleri atilir; ayni metnin birbirine degen tekrarlari (ASS
    animasyon kareleri) tek segmentte birlestirilir. `keep_lines` oynaticida
    gosterim icindir: cue'nun satir yapisi korunur (transkriptte tek satir).
    """
    segments = []
    for cue in cues:
        visible = _MARKUP_TAG.sub('', visible_cue_text(cue))
        if keep_lines:
            text = '\n'.join(' '.join(line.split()) for line in visible.split('\n') if line.strip())
        else:
            text = ' '.join(visible.split())
        if not text:
            continue
        start, end = _cue_times(cue)
        try:
            start, end = parse_time(start), parse_time(end)
        except (TypeError, ValueError):
            continue
        segments.append({'start': start, 'end': max(start, end), 'text': text})
    segments.sort(key=lambda item: item['start'])
    merged = []
    for segment in segments:
        previous = merged[-1] if merged else None
        if previous and previous['text'] == segment['text'] \
                and segment['start'] <= previous['end'] + 1.0:
            previous['end'] = max(previous['end'], segment['end'])
            continue
        merged.append(dict(segment))
    if not merged:
        raise ValueError('Altyazıda okunabilir metin bulunamadı.')
    return merged


def compact_lines(segments, max_seconds=LINE_SECONDS, max_chars=LINE_CHARS):
    """Ardisik kisa segmentleri satirlarda birlestirir (zaman damgasi yukunu azaltir).
    F146: konusmacisi belli segmentler ('speaker') yalnizca ayni konusmaciyla birlesir; satir 'Ad: ' ile baslar."""
    lines = []
    for segment in segments:
        current = lines[-1] if lines else None
        # Kare betimleri (F114) konusmayla birlesmez; '[Görüntü]' satiri ayri kalir.
        if (current and not current.get('visual') and not segment.get('visual')
                and current.get('speaker') == segment.get('speaker')
                and segment['start'] - current['start'] <= max_seconds
                and segment['start'] - current['end'] <= 3.0
                and len(current['text']) + 1 + len(segment['text']) <= max_chars):
            current['text'] += ' ' + segment['text']
            current['end'] = max(current['end'], segment['end'])
        else:
            line = dict(segment)
            if segment.get('speaker'):
                line['text'] = f'{segment["speaker"]}: {segment["text"]}'
            lines.append(line)
    return lines


def format_lines(lines, document=False):
    return '\n'.join(f'[{format_position(line["start"], document)}] {line["text"]}'
                     for line in lines)


# --- belgeler (F64): konum zaman yerine sayfa numarasidir --------------------
DOCUMENT_KINDS = ('pdf', 'text', 'word', 'sheet', 'slides', 'epub', 'html', 'image')


def is_document(data):
    return (data.get('source') or {}).get('kind') in DOCUMENT_KINDS


def format_position(value, document=False):
    """Video icin 'm:ss', belge icin 's.<sayfa>'."""
    return f's.{int(value)}' if document else format_time(value)


VISUAL_LABEL = '[Görüntü]'


def with_visual(data):
    """F114: videonun segmentleri + kare betimleri ('[Görüntü] ...' satirlari) zaman sirasiyla.
    Betimler cached_sessions'ta oturuma 'visual' olarak eklenir (video_frames.py uretir).
    F146: konusmacilar ayrildiysa ('speakers') segmentlere konusmaci adi eklenir."""
    visual = data.get('visual') or []
    segments = data['segments']
    if data.get('speakers'):
        import voice_split
        segments = voice_split.label(segments, data['speakers'])
    if not visual:
        return segments
    extra = [{'start': float(item['start']), 'end': float(item['start']), 'text': f'{VISUAL_LABEL} {item["text"]}',
              'visual': True} for item in visual]
    return sorted(list(segments) + extra, key=lambda item: item['start'])


def visual_path(video, base=None):
    """Kare betimlerinin onbellegi; video degisirse yenilenir."""
    video = Path(video).resolve()
    stat = video.stat()
    key = digest(f'visual|{video}|{stat.st_size}|{int(stat.st_mtime)}')[:16]
    stem = re.sub(r'[^\w.-]+', '_', video.stem)[:40] or 'video'
    return Path(base or work_dir()) / 'visual' / f'{stem}.{key}.json'


def load_visual(video, base=None):
    """Kaydedilmis kare betimleri [{'start', 'text'}] (yarim kalmis olsa da) ve tamamlandi mi."""
    try:
        value = json.loads(read(visual_path(video, base)))
    except (OSError, ValueError):
        return [], False
    frames = value.get('frames') if isinstance(value, dict) else None
    if not isinstance(frames, list):
        return [], False
    return ([item for item in frames if isinstance(item, dict) and str(item.get('text', '')).strip()],
            bool(value.get('complete')))


def lines_of(data):
    """Oturumun satirlari: video icin compact_lines; belgede yalnizca ayni sayfadaki
    paragraflar birlesir (sayfa numarasi atif icin korunur)."""
    if not is_document(data):
        return compact_lines(with_visual(data))
    lines = []
    for segment in data['segments']:
        current = lines[-1] if lines else None
        if (current and current['start'] == segment['start']
                and len(current['text']) + 1 + len(segment['text']) <= LINE_CHARS):
            current['text'] += ' ' + segment['text']
        else:
            lines.append(dict(segment))
    return lines


# --- bolumler -------------------------------------------------------------
def build_sections(lines, chapters=None, max_seconds=SECTION_SECONDS, max_chars=SECTION_CHARS):
    """Satirlari bolumlere ayirir. Donen: [{'start','end','title','first','last'}].

    En az iki gomulu chapter varsa sinirlar onlardan gelir (baslik korunur);
    yoksa ~`max_seconds` uzunlugunda parcalar olusur. Cok uzun bir chapter
    `max_chars` asilinca ayni baslikla bolunur. first/last: `lines` indisleri.
    """
    chapters = [item for item in (chapters or []) if item.get('end', 0) > item.get('start', 0)]
    use_chapters = len(chapters) >= 2

    def chapter_of(time):
        found = 0
        for index, chapter in enumerate(chapters):
            if chapter['start'] <= time + 0.5:
                found = index
        return found

    def chapter_at(index):
        return chapter_of(lines[index]['start']) if use_chapters else None

    sections = []
    first, size = 0, 0
    for index, line in enumerate(lines):
        if index > first:
            boundary = (chapter_at(index) != chapter_at(first) if use_chapters
                        else line['start'] - lines[first]['start'] >= max_seconds)
            if boundary or size + len(line['text']) > max_chars:
                sections.append(_section(lines, first, index - 1, chapter_at(first), chapters))
                first, size = index, 0
        size += len(line['text']) + 10
    if lines:
        sections.append(_section(lines, first, len(lines) - 1, chapter_at(first), chapters))
    return sections


def _section(lines, first, last, chapter, chapters):
    title = chapters[chapter].get('title', '') if chapter is not None else ''
    return {'start': lines[first]['start'], 'end': lines[last]['end'],
            'title': title, 'first': first, 'last': last}


def section_label(section):
    return section.get('title') or section.get('heading') or ''


# --- onbellek + transkript kaynagi ----------------------------------------
def work_dir():
    return APP_DIR / 'work_files'


def cache_path(video, source_key, base=None):
    """Video + kaynak (stream) icin degismeyen onbellek yolu; video degisirse yenilenir."""
    video = Path(video).resolve()
    stat = video.stat()
    key = digest(f'{CACHE_VERSION}|{video}|{stat.st_size}|{int(stat.st_mtime)}|{source_key}')[:16]
    stem = re.sub(r'[^\w.-]+', '_', video.stem)[:40] or 'video'
    return Path(base or work_dir()) / 'qa' / f'{stem}.{key}.json'


def load_cache(path):
    try:
        value = json.loads(read(path))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('version') != CACHE_VERSION:
        return None
    return value


def pick_subtitle_stream(streams):
    """Soru-cevap icin en uygun metin altyaziyi secer (yazi/sarki izlerinden kacinir)."""
    usable = [item for item in streams if item.get('supported')]
    if not usable:
        return None
    clean = [item for item in usable if not _NOISY_TRACK.search(item.get('title', ''))]
    return (clean or usable)[0]


def subtitle_segments(video, stream, base=None, keep_lines=False):
    """Secilen altyazi stream'ini work_files/qa altina cikarip segmentlere cevirir.

    Gosterim (`keep_lines`) ayri dosyaya cikarilir; soru-cevap hazirligi ayni
    anda ayni akisi cikarirken dosya yarismasi olmasin.
    """
    folder = Path(base or work_dir()) / 'qa'
    stem = re.sub(r'[^\w.-]+', '_', Path(video).stem)[:40] or 'video'
    view = '.view' if keep_lines else ''
    output = folder / f'{stem}.s{int(stream["index"])}{view}.{stream["extension"]}'
    media.extract_subtitle(video, stream['index'], output, codec=stream.get('codec', ''))
    return file_segments(output, keep_lines=keep_lines)


def file_segments(path, keep_lines=True):
    """Diskteki .srt/.ass/.ssa/.vtt dosyasini zaman segmentlerine cevirir."""
    path = Path(path)
    kind, payload = subtitle.parse_by_extension(read(path), path.suffix)
    return transcript_from_cues(subtitle.cues_of(kind, payload), keep_lines=keep_lines)


class SubtitleTimeline:
    """Oynaticida gosterilecek altyazi: verilen andaki metin (cakisan cue'lar birlikte)."""

    LOOKBACK = 60.0  # bu kadar once baslayip hala suren cue'lar da aranir

    def __init__(self, segments):
        self.segments = sorted(segments, key=lambda item: item['start'])
        self.starts = [item['start'] for item in self.segments]

    def text_at(self, seconds):
        index = bisect_right(self.starts, seconds)
        active = []
        for segment in reversed(self.segments[:index]):
            if segment['start'] < seconds - self.LOOKBACK:
                break
            if seconds < segment['end']:
                active.append(segment['text'])
        return '\n'.join(dict.fromkeys(reversed(active)))


def build_data(video, segments, source, info=None):
    """Transkript + bolumlerden onbellege yazilacak oturum verisini kurar."""
    info = info or {'duration': 0.0, 'chapters': []}
    lines = compact_lines(segments)
    duration = float(info.get('duration') or 0.0) or (lines[-1]['end'] if lines else 0.0)
    return {
        'version': CACHE_VERSION,
        'video': str(video),
        'title': Path(video).stem,
        'source': source,
        'duration': duration,
        'chapters': info.get('chapters', []),
        'segments': segments,
        'sections': build_sections(lines, info.get('chapters')),
        'mode': '',
        'overview': None,
    }


def source_key(source):
    """Oturum kaynagindan onbellek anahtari: 'subtitle:2' / 'whisper:<model>:<dil>[:a<iz>]' /
    'document:pdf'."""
    if source.get('kind') == 'sheet':
        return 'document:sheet:2'  # F96: tarih + toplam satirli yeni metin; eski onbellek gecersiz
    if source.get('kind') == 'epub':
        return 'document:epub:2'   # F146: sayfalar okuyucunun bolum numaralariyla; eski onbellek gecersiz
    if source.get('kind') in DOCUMENT_KINDS:
        return f'document:{source["kind"]}'
    if source.get('kind') == 'subtitle':
        return f'subtitle:{int(source["stream"])}'
    track = source.get('audio_track')
    suffix = '' if track is None else f':a{int(track)}'
    return f'whisper:{source.get("model", "")}:{source.get("language", "")}{suffix}'


def cached_sessions(video, base=None):
    """Video icin onbellekte duran (video degismediyse gecerli) tum oturumlar."""
    video = Path(video)
    try:
        resolved = video.resolve()
        stem = re.sub(r'[^\w.-]+', '_', video.stem)[:40] or 'video'
        candidates = sorted((Path(base or work_dir()) / 'qa').glob(stem + '.*.json'))
    except OSError:
        return []
    sessions = []
    for path in candidates:
        data = load_cache(path)
        if not data or not isinstance(data.get('source'), dict):
            continue
        try:
            if (Path(data.get('video', '')).resolve() != resolved
                    or cache_path(video, source_key(data['source']), base) != path):
                continue
        except (OSError, KeyError, TypeError, ValueError):
            continue
        sessions.append(data)
    if sessions and not is_document(sessions[0]):
        import voice_split
        visual, _complete = load_visual(video, base)
        try:
            speakers = voice_split.load_speakers(video, base)
        except OSError:
            speakers = None
        for data in sessions:
            data['visual'] = visual
            if speakers:
                data['speakers'] = speakers
    return sessions


def load_subtitle_session(video, stream, base=None, log=print):
    """Altyazi stream'inden oturum verisi: onbellekte varsa oradan, yoksa cikarir."""
    source = {'kind': 'subtitle', 'stream': int(stream['index']),
              'language': stream.get('language', ''), 'title': stream.get('title', '')}
    return _load_session(video, source,
                         lambda: subtitle_segments(video, stream, base), base, log)


def load_whisper_session(video, result, base=None, log=print):
    """speech.transcribe sonucundan (konusmadan metin) oturum verisi."""
    source = {'kind': 'whisper', 'model': result.get('model', ''),
              'language': result.get('language', ''), 'audio_track': result.get('audio_track')}
    return _load_session(video, source,
                         lambda: [{key: value for key, value in item.items() if key != 'words'}
                                  for item in result['segments']], base, log)


def _load_session(video, source, make_segments, base, log):
    path = cache_path(video, source_key(source), base)
    cached = load_cache(path)
    if cached:
        log('Transkript önbellekten yüklendi.')
        return cached, path
    segments = make_segments()
    try:
        info = media.video_info(video)
    except (RuntimeError, ValueError) as error:
        log('Video bölümleri okunamadı: ' + str(error))
        info = None
    data = build_data(video, segments, source, info)
    save_json(path, data)
    log(f'Transkript hazır: {len(segments)} satır, {len(data["sections"])} bölüm.')
    return data, path


# --- model istemleri ------------------------------------------------------
OVERVIEW_FROM_TRANSCRIPT_PROMPT = '''You receive the complete timestamped transcript of a video. Reply with a JSON object only, no other text:
{"summary": "<Turkish, 3-6 sentences: what the video is about, its main points and its conclusion>",
 "topics": ["<Turkish short topic>", ...],
 "questions": ["<Turkish question a viewer might ask about this video>", ...]}
Give 3-6 topics and exactly 4 questions. Questions must be specific to this video and answerable from it. Use only the transcript.'''

SECTION_PROMPT = '''You receive one section of a video's timestamped transcript. Reply with a JSON object only, no other text:
{"heading": "<Turkish, at most 6 words>", "summary": "<Turkish, 2-5 sentences with the concrete facts, numbers, names, recommendations and conclusions of this section>"}
Use only the transcript.'''

OVERVIEW_FROM_SECTIONS_PROMPT = '''You receive the section-by-section summary of a video with time ranges. Reply with a JSON object only, no other text:
{"summary": "<Turkish, 3-6 sentences: what the video is about, its main points and its conclusion>",
 "topics": ["<Turkish short topic>", ...],
 "questions": ["<Turkish question a viewer might ask about this video>", ...]}
Give 3-6 topics and exactly 4 questions. Questions must be specific to this video and answerable from it. Use only the summaries.'''

ROUTE_PROMPT = '''Choose the video sections whose detailed transcript is needed to answer the viewer's latest question. The question may be in a different language than the video. Reply with a JSON object only: {{"sections": [section numbers, most relevant first]}}. Choose at most {limit}. For broad questions about the whole video (summary, main message, verdict) choose the sections that carry its key points and conclusion. Return an empty list only if no section relates to the question.'''

# F103: sohbet cevaplarinda grafik; arayuz ```chart blogunu Chart.js ile cizer (web/src/lib/chart.js).
CHART_RULE = '''- Charts: when the user asks for a chart or graph, or when the answer compares several numbers (shares of a whole, change over time, categories side by side) and a chart clearly helps, add one fenced code block tagged chart that contains only JSON, for example:
```chart
{"type": "bar", "title": "Yıllık gelir", "unit": "TL", "labels": ["2024", "2025"], "series": [{"name": "Gelir", "values": [120.5, 140]}]}
```
  "type" is one of bar, hbar, stacked, line, area, pie, doughnut, radar, scatter (scatter values are [x, y] pairs; labels are not needed). Values are plain JSON numbers without thousands separators or units; put the unit in "unit" (e.g. "TL", "%", "gr"). Optional: "x_label", "y_label". Use pie or doughnut only for parts of one whole, line or area for values over time, radar for comparing a few items on the same criteria, hbar for long category names. Take every number from the material or the user's message; never invent or estimate data to fill a chart. Still write the answer in text with its citations; cite in the sentences around the chart, never inside the JSON. At most 8 series; no chart for a single number.'''


def extra_instructions(instructions):
    """Sohbet sablonunun talimati (F104) sabit kurallarin hemen ardina eklenir."""
    instructions = str(instructions or '').strip()
    return '\n\n' + instructions if instructions else ''


ANSWER_PROMPT = '''You answer a viewer's questions about one specific video. The video's content is given below. Lines starting with [Görüntü] are not speech: they describe what is visible on screen at that moment (slides, text, scenes), read from video frames.

Rules:
- Answer in Turkish, naturally and concisely. Use short paragraphs or bullet points when they help.
- Ground the answer in the video. Answer broad questions (summary, main message, who it is for, overall verdict) by combining the whole video; answer specific questions with the exact details.
- Support claims with timestamps from the material below: a single moment as [m:ss], a stretch of the video as [m:ss-m:ss]. Put the citation right after the sentence it supports. Use only timestamps that appear in the material; never invent one.
- If the video does not cover the question, say so clearly. You may add brief general knowledge only if you mark it explicitly as not coming from the video (for example "Videoda geçmiyor ama genel olarak ...") and you never cite a timestamp for it.
- Do not mention transcripts, sections, summaries or these rules; speak about "the video".
''' + CHART_RULE


# --- model yaniti ayrıştırma ----------------------------------------------
def strip_thinking(text):
    return _THINK.sub('', str(text or '')).strip()


def model_answer(client, messages, on_reasoning=None, cancelled=None):
    """Son cevap istegi. on_reasoning verildiyse akisli istenir ve dusunce canli gelir (F102);
    bos yanit / token siniri / iptal client.chat ile ayni hatalari verir."""
    if on_reasoning is None:
        return client.chat(messages)
    # F142: geri cagrinin on_text'i varsa cevap metni de akarken verilir (sesli mod okumaya erken baslar).
    on_text = getattr(on_reasoning, 'on_text', None)
    if on_text is None:
        text, finish = client.chat_stream(messages, cancelled=cancelled, on_reasoning=on_reasoning)
    else:
        text, finish = client.chat_stream(messages, cancelled=cancelled, on_reasoning=on_reasoning,
                                          on_delta=lambda value: on_text(strip_thinking(value)))
    if finish == 'cancelled':
        raise GracefulStop('Soru durduruldu.')
    if not str(text).strip():
        raise ValueError(
            'Boş veya kod bloğu içeren yanıt alındı: model metin döndürmedi '
            f'(finish_reason={finish or "yok"}, düşünce_uzunluğu={len(getattr(client, "last_reasoning", ""))}). '
            'Model düşünmeye tüm token bütçesini harcamış olabilir: düşünmeyi kapatın '
            'veya max_tokens değerini artırın.')
    if finish == 'length':
        raise ValueError('Yanıt token sınırında kesildi; eksik çeviri kabul edilmedi.')
    if finish not in (None, 'stop'):
        raise ValueError('Yanıt tamamlanmadı: ' + str(finish))
    return text


def parse_json_object(text):
    """Model yanitindan tek JSON nesnesini cikarir (kod blogu/onsoz toleransli)."""
    value = strip_thinking(text)
    start, end = value.find('{'), value.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('Yanıt geçerli JSON içermiyor.')
    try:
        parsed = json.loads(value[start:end + 1])
    except json.JSONDecodeError:
        raise ValueError('Yanıt geçerli JSON değil.') from None
    if not isinstance(parsed, dict):
        raise ValueError('Yanıt JSON nesnesi değil.')
    return parsed


def _text_list(value, limit):
    if not isinstance(value, list):
        return []
    items = [' '.join(str(item).split()) for item in value if str(item).strip()]
    return list(dict.fromkeys(items))[:limit]


def normalize_overview(value):
    summary = ' '.join(str(value.get('summary', '')).split())
    if not summary:
        raise ValueError('Yanıt genel özet içermiyor.')
    return {'summary': summary, 'topics': _text_list(value.get('topics'), 8),
            'questions': _text_list(value.get('questions'), 4)}


# --- atiflar --------------------------------------------------------------
def resolve_citation(start, end, lines, duration=0.0, tolerance=CITATION_TOLERANCE):
    """Atif zamanini transkriptle dogrular. Gecersizse None.

    Atif bir satirin icindeyse aynen kalir; yakinindaysa (tolerans) satirin
    basina oturtulur; hicbir satira yakin degilse uydurma sayilir.
    """
    if not lines:
        return None
    limit = max(float(duration or 0.0), lines[-1]['end'])
    if start > limit + tolerance:
        return None
    best, best_distance = None, None
    for line in lines:
        if line['start'] <= start <= line['end']:
            best, best_distance = line, 0.0
            break
        distance = min(abs(start - line['start']), abs(start - line['end']))
        if best_distance is None or distance < best_distance:
            best, best_distance = line, distance
    if best_distance > tolerance:
        return None
    target = start if best['start'] <= start <= best['end'] else best['start']
    if end is not None:
        end = min(end, limit)
        if end <= target:
            end = None
    return {'start': float(target), 'end': None if end is None else float(end),
            'label': format_range(start, end)}


def split_citations(text, lines, duration=0.0):
    """Cevabi metin ve atif parcalarina ayirir.

    Donen: [('text', str) | ('cite', [{'start','end','label'}])]. Koseli
    parantezli atiflar ([12:34], [3:10-7:45], [1:02, 3:45]) gecersizse
    metinden atilir; parantezsiz zamanlar (12:34'te) yalnizca gecerliyse
    baglantiya donusur, degilse metin olarak kalir.
    """
    parts = []

    def add_text(value):
        if not value:
            return
        if parts and parts[-1][0] == 'text':
            parts[-1] = ('text', parts[-1][1] + value)
        else:
            parts.append(('text', value))

    def bare(value):
        position = 0
        for match in _BARE.finditer(value):
            start = parse_time(match.group(1))
            end = parse_time(match.group(2)) if match.group(2) else None
            cite = resolve_citation(start, end, lines, duration)
            if cite is None:
                continue
            add_text(value[position:match.start()])
            cite['label'] = match.group(0)
            parts.append(('cite', [cite]))
            position = match.end()
        add_text(value[position:])

    position = 0
    for match in _BRACKET.finditer(text):
        items = re.split(r'[,;]', match.group(1))
        parsed = [_CITE_ITEM.fullmatch(item) for item in items]
        if not all(parsed):
            continue
        bare(text[position:match.start()])
        cites = []
        for item in parsed:
            start = parse_time(item.group(1))
            end = parse_time(item.group(2)) if item.group(2) else None
            cite = resolve_citation(start, end, lines, duration)
            if cite is not None:
                cites.append(cite)
        if cites:
            parts.append(('cite', cites))
        else:
            # Uydurma atif: metinden atilir, onceki bosluk da temizlenir.
            if parts and parts[-1][0] == 'text':
                parts[-1] = ('text', parts[-1][1].rstrip(' '))
        position = match.end()
    bare(text[position:])
    return parts


# --- oturum ---------------------------------------------------------------
class VideoQA:
    """Tek video icin hazirlik (ozet/harita) ve cok turlu soru-cevap."""

    def __init__(self, data, config_provider=load_config, log=print, save=None):
        self.data = data
        self.config_provider = config_provider
        self.log = log
        self.save = save or (lambda _data: None)
        self.lines = compact_lines(with_visual(data))
        self.history = []

    # yardimcilar
    @property
    def overview(self):
        return self.data.get('overview') or {}

    @property
    def sections(self):
        return self.data.get('sections') or []

    def questions(self):
        specific = list(self.overview.get('questions') or [])
        return list(dict.fromkeys([DEFAULT_QUESTIONS[0]] + specific
                                  + list(DEFAULT_QUESTIONS[1:])))[:5]

    def _budget(self, cfg):
        return int(cfg.get('qa_context_chars', 24000))

    def _fits(self, cfg):
        return len(format_lines(self.lines)) + 1500 <= self._budget(cfg)

    def _section_lines(self, section):
        return self.lines[section['first']:section['last'] + 1]

    def _section_header(self, number, section):
        label = section_label(section)
        head = f'{number}. [{format_range(section["start"], section["end"])}]'
        return head + (' ' + label if label else '')

    def _call(self, client, cfg, messages, parse, on_reasoning=None, cancelled=None):
        retries = int(cfg['auto_retry_count'])
        for attempt in range(retries + 1):
            try:
                return parse(model_answer(client, messages, on_reasoning, cancelled))
            except (ValueError, RuntimeError) as error:
                if not retryable_translation_error(error) or attempt >= retries:
                    raise
                self.log(f'Geçici hata (deneme {attempt + 1}/{retries + 1}): {error}')
        raise RuntimeError('Model isteği tamamlanamadı.')

    @staticmethod
    def _check(cancelled):
        if cancelled and cancelled():
            raise GracefulStop('Hazırlık durduruldu; tamamlanan adımlar kaydedildi.')

    # hazirlik
    def prepare(self, progress=None, cancelled=None):
        """Genel ozet + onerilen sorular (ve gerekirse bolum ozetleri) uretir.

        Her adimdan sonra `save` cagrilir; kesilirse kaldigi yerden devam eder.
        """
        cfg = self.config_provider()
        client = Client(cfg, log=self.log)
        mode = 'full' if self._fits(cfg) else 'map'
        if self.data.get('mode') != mode:
            self.data['mode'] = mode
            self.data['overview'] = None
        pending = ([] if mode == 'full'
                   else [index for index, item in enumerate(self.sections) if not item.get('summary')])
        total = len(pending) + 1
        done = 0
        if progress:
            progress(done, total)
        for index in pending:
            self._check(cancelled)
            section = self.sections[index]
            label = section_label(section)
            user = (f'VIDEO: {self.data.get("title", "")}\n'
                    f'SECTION {format_range(section["start"], section["end"])}'
                    + (f' ({label})' if label else '') + '\n\n'
                    + format_lines(self._section_lines(section)))
            value = self._call(client, cfg, [{'role': 'system', 'content': SECTION_PROMPT},
                                              {'role': 'user', 'content': user}], parse_json_object)
            summary = ' '.join(str(value.get('summary', '')).split())
            if not summary:
                raise ValueError('Yanıt bölüm özeti içermiyor.')
            section['summary'] = summary
            section['heading'] = ' '.join(str(value.get('heading', '')).split())[:80]
            self.save(self.data)
            done += 1
            if progress:
                progress(done, total)
            self.log(f'Bölüm özeti {done}/{len(pending)}: {self._section_header(index + 1, section)}')
        if not self.data.get('overview'):
            self._check(cancelled)
            if mode == 'full':
                system = OVERVIEW_FROM_TRANSCRIPT_PROMPT
                user = (f'VIDEO: {self.data.get("title", "")}\n'
                        f'DURATION: {format_time(self.data.get("duration", 0))}\n\n'
                        + format_lines(self.lines))
            else:
                system = OVERVIEW_FROM_SECTIONS_PROMPT
                user = f'VIDEO: {self.data.get("title", "")}\n\n' + self._map_text()
            self.data['overview'] = self._call(
                client, cfg, [{'role': 'system', 'content': system},
                              {'role': 'user', 'content': user}],
                lambda text: normalize_overview(parse_json_object(text)))
            self.save(self.data)
        if progress:
            progress(total, total)
        return self.data['overview']

    def _map_text(self):
        return '\n'.join(self._section_header(index + 1, section) + ': ' + section.get('summary', '')
                         for index, section in enumerate(self.sections))

    # baglam
    def _route(self, client, cfg, question):
        recent = '\n'.join('Q: ' + turn['question'] for turn in self.history[-2:])
        user = ('SECTIONS:\n' + self._map_text()
                + ('\n\nRECENT QUESTIONS:\n' + recent if recent else '')
                + '\n\nLATEST QUESTION: ' + question)

        def parse(text):
            value = parse_json_object(text).get('sections')
            if not isinstance(value, list):
                raise ValueError('Yanıt bölüm listesi içermiyor.')
            picked = []
            for item in value:
                try:
                    number = int(item)
                except (TypeError, ValueError):
                    continue
                if 1 <= number <= len(self.sections) and number - 1 not in picked:
                    picked.append(number - 1)
            return picked

        try:
            return self._call(client, cfg, [
                {'role': 'system', 'content': ROUTE_PROMPT.format(limit=ROUTE_LIMIT)},
                {'role': 'user', 'content': user}], parse)
        except (ValueError, RuntimeError) as error:
            self.log('Bölüm seçimi yapılamadı, kelime eşleşmesine düşülüyor: ' + str(error))
            return lexical_rank(self.sections, self.lines, question)

    def build_context(self, cfg, ranked=None):
        """Modele gidecek video icerigi. 'full': tum transkript; 'map': harita + ayrinti."""
        head = (f'VIDEO TITLE: {self.data.get("title", "")}\n'
                f'DURATION: {format_time(self.data.get("duration", 0))}\n')
        if self.data.get('mode') != 'map' or not self.sections:
            return head + '\nTRANSCRIPT:\n' + format_lines(self.lines), []
        overview = self.overview.get('summary', '')
        text = (head + ('\nOVERVIEW:\n' + overview + '\n' if overview else '')
                + '\nSECTIONS:\n' + self._map_text()
                + '\n\nDETAILED TRANSCRIPT OF THE MOST RELEVANT SECTIONS:\n')
        room = self._budget(cfg) - len(text)
        chosen = {}
        # Once modelin sectigi bolumler; butce kalirsa videoya yayilmis digerleri
        # (genel sorularda tek bolum secilse bile cevap tum videoyu gorur).
        ranked = list(ranked or [])
        order = ranked + [index for index in spread(len(self.sections), ROUTE_LIMIT)
                          if index not in ranked]
        for index in order:
            block = format_lines(self._section_lines(self.sections[index]))
            if len(block) > room:
                if chosen:
                    continue
                block = block[:max(0, room)].rsplit('\n', 1)[0]
            chosen[index] = block
            room -= len(block) + 80
            if room <= 200:
                break
        parts = [f'### {self._section_header(index + 1, self.sections[index])}\n{chosen[index]}'
                 for index in sorted(chosen)]
        return text + '\n\n'.join(parts), sorted(chosen)

    # soru
    def ask(self, question, cancelled=None, think=None, on_reasoning=None, instructions='', template=''):
        """Soruyu cevaplar. Donen: {'question','answer','parts','sections'}.

        on_reasoning(simdiye kadarki dusunce) verildiyse cevap akisli istenir (F102).
        instructions: sohbet sablonunun talimati (F104); template: kayda yazilan sablon adi."""
        question = ' '.join(str(question).split())
        if not question:
            raise ValueError('Soru boş olamaz.')
        cfg = qa_config(self.config_provider(), think)  # F72: soru-cevap modeli
        client = Client(cfg, log=self.log)
        ranked = None
        if self.data.get('mode') == 'map' and self.sections:
            ranked = self._route(client, cfg, question)
            self._check(cancelled)
        context, used = self.build_context(cfg, ranked)
        messages = [{'role': 'system', 'content': ANSWER_PROMPT + extra_instructions(instructions) + '\n\n' + context}]
        for turn in self.history[-HISTORY_TURNS:]:
            messages.append({'role': 'user', 'content': turn['question']})
            messages.append({'role': 'assistant', 'content': turn['answer']})
        messages.append({'role': 'user', 'content': question})

        def parse(text):
            value = strip_thinking(text)
            if not value:
                raise ValueError('Yanıt boş döndü.')
            return value

        answer = self._call(client, cfg, messages, parse, on_reasoning, cancelled)
        turn = {'question': question, 'answer': answer, 'sections': used,
                'parts': split_citations(answer, self.lines, self.data.get('duration', 0)),
                'thinking': getattr(client, 'last_reasoning', ''), 'think': think, 'template': template}
        self.history.append(turn)
        return turn


def spread(count, limit):
    """Ayrinti icin baska ipucu yoksa videoya esit yayilmis bolum indisleri."""
    if count <= limit:
        return list(range(count))
    step = (count - 1) / (limit - 1)
    return sorted({round(step * index) for index in range(limit)})


def _words(text):
    return {word for word in re.findall(r'\w{3,}', str(text).lower())}


def lexical_rank(sections, lines, question):
    """Model secimi basarisizsa: soru kelimelerinin bolum metniyle ortusmesine gore sira."""
    wanted = _words(question)
    scored = []
    for index, section in enumerate(sections):
        body = ' '.join(line['text'] for line in lines[section['first']:section['last'] + 1])
        words = _words(body + ' ' + section.get('summary', '') + ' ' + section_label(section))
        scored.append((len(wanted & words), index))
    hits = [index for score, index in sorted(scored, key=lambda item: (-item[0], item[1])) if score]
    return hits[:ROUTE_LIMIT] or spread(len(sections), ROUTE_LIMIT)
