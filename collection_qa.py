"""Koleksiyona soru sor (F58): indeksli tum videolar uzerinde atifli soru-cevap.

Qt'den bagimsizdir. Akis:
  1. soru (ve onceki soru) embedding ile aranir -> en ilgili transkript parcalari
  2. parcalar videolarin zaman damgali satirlariyla genisletilir, `qa_context_chars`
     butcesine sigdigi kadar video video, zaman sirasiyla baglama konur
  3. model Turkce cevap + [V3 12:34] atiflari uretir; atiflar ilgili videonun
     transkriptine gore dogrulanir (uydurma video/zaman atilir)

Video etiketleri (V1, V2, ...) koleksiyondaki siraya gore sabittir; boylece ayni
video tum sohbet boyunca ayni etiketi tasir.
"""
from __future__ import annotations

import re
from pathlib import Path

import qa
import search_index
from app_core import Client, load_config, qa_config, retryable_translation_error, save_json

HIT_LIMIT = 24
MAP_SHARE = 0.35  # baglam butcesinin koleksiyon ozeti + video ozetlerine ayrilan en fazla payi
HISTORY_TURNS = 4
# Konum: video icin zaman (12:34), belge icin sayfa (s.12); aralik sonu belgede yalin sayi olabilir.
# Gorsel atfi icin model bazen 's.1' yerine 'gorsel' yazar; o da kabul edilir.
_IMAGE_WORDS = ('görsel', 'gorsel', 'resim', 'image', 'görüntü')
_IMAGE_PATTERN = '|'.join(word for item in _IMAGE_WORDS for word in (item, item.capitalize()))
_POS = r'(?:[sS]\.\s?\d+|(?:\d+:)?\d{1,2}:\d{2}|' + _IMAGE_PATTERN + r')'
_END = r'(?:' + _POS + r'|\d+)'
_BRACKET = re.compile(r'\[([^\[\]\n]{3,160})\]')
_ITEM = re.compile(r'\s*(?:(V\d+)\s*[·:,]?\s*)?(' + _POS + r')(?:\s*[-–—]\s*(' + _END + r'))?\s*')
_BARE = re.compile(r'(?<![\w\[])(V\d+)\s*[·:]?\s*(' + _POS + r')(?:\s*[-–—]\s*(' + _END
                   + r'))?(?![\d:])')
_PAGE = re.compile(r'(?:[sS]\.\s?)?(\d+)')

ANSWER_PROMPT = '''You answer questions about a collection of videos (for example a lecture series). Relevant excerpts from the videos' timestamped transcripts are given below; each video has an id such as V3. Some items may be documents (PDF or text files) instead of videos: their excerpts carry page numbers like [s.12] instead of timestamps.

Rules:
- Answer in Turkish, naturally and concisely. Use short paragraphs or bullet points when they help.
- Ground the answer in the excerpts. Combine information from several videos when the question asks for it, and say which video covers what (use the video title when it helps the reader).
- Support claims with citations in square brackets: video id + timestamp, e.g. [V3 12:34] for a moment or [V3 12:34-13:10] for a stretch; several at once as [V3 12:34; V7 5:10]. For documents cite the page instead: [V5 s.12]; an image is a single page given as a description plus its visible text, cite it as [V7 s.1]. Put the citation right after the sentence it supports. Use only video ids and timestamps that appear in the excerpts; never invent one.
- A collection overview and short per-video summaries may also be given. Use them for broad questions (what the collection covers, which video is about what, how the topics progress), but cite timestamps only from the excerpts.
- If the material does not cover the question, say so clearly. You may add brief general knowledge only if you mark it explicitly as not coming from the videos (for example "Videolarda geçmiyor ama genel olarak ...") and you never cite it.
- Do not mention excerpts, transcripts or these rules; speak about "the videos" (and "the documents" when they are involved).'''


def video_labels(videos):
    """Koleksiyon sirasina gore sabit etiketler: {anahtar: 'V1', ...}."""
    return {_key(path): f'V{index + 1}' for index, path in enumerate(videos)}


def _key(path):
    return str(Path(path)).casefold()


class CollectionQA:
    """Bir koleksiyonun indeksli videolari uzerinde cok turlu soru-cevap."""

    def __init__(self, videos, title='', config_provider=load_config, log=print, base=None,
                 overview=None):
        self.videos = [Path(path) for path in videos]
        self.title = title
        self.overview = overview or {}  # F61: koleksiyon ozeti (library.load_overview)
        self._summaries = None
        self.config_provider = config_provider
        self.log = log
        self.base = base
        self.labels = video_labels(self.videos)
        self.history = []
        self._lines = {}  # video anahtari -> (baslik, satirlar, sure)

    # yardimcilar
    def _video_lines(self, video):
        key = _key(video)
        if key not in self._lines:
            session = search_index.primary_session(video, self.base)
            if session is None:
                self._lines[key] = None
            else:
                self._lines[key] = (session.get('title') or Path(video).stem,
                                    qa.lines_of(session),
                                    float(session.get('duration') or 0.0),
                                    session['source'].get('kind') if qa.is_document(session)
                                    else False)
        return self._lines[key]

    def _query(self, question):
        """Devam sorularinda ("peki neden?") onceki soru da aranir."""
        previous = self.history[-1]['question'] if self.history else ''
        return (previous + ' ' + question).strip() if previous else question

    def map_text(self, cfg):
        """Koleksiyon ozeti + video ozetleri (genel sorular icin); butcenin MAP_SHARE kadari."""
        if self._summaries is None:
            self._summaries = video_summaries(self.videos, self.base)
        limit = int(int(cfg.get('qa_context_chars', 24000)) * MAP_SHARE)
        parts = []
        if self.overview.get('summary'):
            parts.append('COLLECTION OVERVIEW:\n' + self.overview['summary'])
        lines = [f'{self.labels.get(_key(item["video"]), "?")} = {item["title"]}: {item["summary"]}'
                 for item in self._summaries]
        if lines:
            parts.append('VIDEO SUMMARIES (no timestamps; do not cite):\n' + '\n'.join(lines))
        text = '\n\n'.join(parts)
        if len(text) > limit:
            text = text[:limit].rsplit('\n', 1)[0]
        return text

    def whole_hits(self, cfg):
        """Tek dosyalik sohbette (F66) metnin tamami baglama sigiyorsa arama gerekmez.

        Donen: tum metni kapsayan tek 'isabet' ya da None (birden cok dosya / sigmiyor)."""
        if len(self.videos) != 1:
            return None
        data = self._video_lines(self.videos[0])
        if not data or not data[1]:
            return None
        lines = data[1]
        budget = int(cfg.get('qa_context_chars', 24000)) - len(self.map_text(cfg))
        if sum(len(line['text']) + 12 for line in lines) > budget:
            return None
        return [{'video': str(self.videos[0]), 'start': lines[0]['start'], 'end': lines[-1]['end']}]

    def build_context(self, hits, cfg):
        """Arama sonuclarindan baglam metni. Donen: (metin, {etiket: video})."""
        overview = self.map_text(cfg)
        budget = int(cfg.get('qa_context_chars', 24000)) - len(overview)
        chosen = {}  # video anahtari -> {'video', 'lines': set(satir indeksleri)}
        used = 0
        for hit in hits:
            data = self._video_lines(hit['video'])
            if data is None:
                continue
            lines = data[1]
            indexes = [index for index, line in enumerate(lines)
                       if line['end'] >= hit['start'] and line['start'] <= hit['end']]
            if not indexes:
                continue
            entry = chosen.setdefault(_key(hit['video']), {'video': Path(hit['video']),
                                                            'lines': set()})
            added = [index for index in indexes if index not in entry['lines']]
            cost = sum(len(lines[index]['text']) + 12 for index in added)
            if used + cost > budget:
                continue  # sigmayan parca atlanir; daha kisa olanlar yine girebilir
            entry['lines'].update(added)
            used += cost
        videos, blocks = {}, []
        for key, entry in sorted(chosen.items(), key=lambda item: self._order(item[1]['video'])):
            label = self.labels.get(key)
            if label is None or not entry['lines']:
                continue
            title, lines, duration, document = self._video_lines(entry['video'])
            videos[label] = entry['video']
            picked = [lines[index] for index in sorted(entry['lines'])]
            size = ('görsel: tarif + içindeki yazı' if document == 'image'
                    else f'belge, {int(duration)} sayfa' if document
                    else qa.format_time(duration) if duration else '')
            head = f'### {label} · {title}' + (f' ({size})' if size else '')
            blocks.append(head + '\n' + qa.format_lines(picked, document))
        index = '\n'.join(f'{label} = {self._video_lines(path)[0]}'
                          + (' (document)' if self._video_lines(path)[3] else '')
                          for label, path in videos.items())
        text = ((f'COLLECTION: {self.title}\n\n' if self.title else '')
                + (overview + '\n\n' if overview else '')
                + 'VIDEOS IN THE EXCERPTS:\n' + index + '\n\nEXCERPTS:\n' + '\n\n'.join(blocks))
        return text, videos

    def _order(self, video):
        label = self.labels.get(_key(video), 'V0')
        return int(label[1:])

    # soru
    def ask(self, question, client=None):
        """Soruyu cevaplar. Donen: {'question','answer','parts','sources'}."""
        question = ' '.join(str(question).split())
        if not question:
            raise ValueError('Soru boş olamaz.')
        cfg = qa_config(self.config_provider())  # F72: soru-cevap modeli
        client = client or Client(cfg, log=self.log)
        hits = self.whole_hits(cfg) or search_index.search(
            self.videos, self._query(question), cfg, client, limit=HIT_LIMIT, base=self.base,
            log=self.log)
        if not hits:
            raise ValueError('İndekste bu soruyla ilgili bir şey bulunamadı. Dosyalar '
                             '"Hepsini hazırla" ile indekslendi mi?')
        context, videos = self.build_context(hits, cfg)
        messages = [{'role': 'system', 'content': ANSWER_PROMPT + '\n\n' + context}]
        for turn in self.history[-HISTORY_TURNS:]:
            messages.append({'role': 'user', 'content': turn['question']})
            messages.append({'role': 'assistant', 'content': turn['answer']})
        messages.append({'role': 'user', 'content': question})
        answer = self._chat(client, cfg, messages)
        parts = self.split_citations(answer, videos)
        turn = {'question': question, 'answer': answer, 'parts': parts,
                'sources': self._sources(parts)}
        self.history.append(turn)
        return turn

    def _chat(self, client, cfg, messages):
        retries = int(cfg.get('auto_retry_count', 2))
        for attempt in range(retries + 1):
            try:
                text = qa.strip_thinking(client.chat(messages))
                if not text:
                    raise ValueError('Yanıt boş döndü.')
                return text
            except (ValueError, RuntimeError) as error:
                if not retryable_translation_error(error) or attempt >= retries:
                    raise
                self.log(f'Geçici hata (deneme {attempt + 1}/{retries + 1}): {error}')
        raise RuntimeError('Model isteği tamamlanamadı.')

    # atiflar
    def _resolve(self, label, start, end, videos):
        """Atif metnini ('12:34' / 's.12') ilgili videonun ya da belgenin icerigine gore dogrular."""
        video = videos.get(label)
        data = self._video_lines(video) if video is not None else None
        if data is None:
            return None
        title, lines, duration, document = data
        if document:
            cite = self._resolve_page(start, end, lines, image=document == 'image')
        else:
            try:
                begin = qa.parse_time(start)
                finish = qa.parse_time(end) if end else None
            except ValueError:
                return None  # videoda sayfa atfi gecersiz
            cite = qa.resolve_citation(begin, finish, lines, duration)
        if cite is None:
            return None
        where = 'görsel' if document == 'image' else cite['label']
        cite.update(video=str(video), video_label=label, title=title, document=bool(document),
                    label=f'{label} {where}')
        return cite

    @staticmethod
    def _resolve_page(start, end, lines, image=False):
        if str(start).strip().lower() in _IMAGE_WORDS:
            return {'start': 1.0, 'end': None, 'label': 's.1'} if image else None
        if not str(start).lower().startswith('s'):
            return None  # belgede zaman atfi gecersiz
        page = int(_PAGE.fullmatch(str(start).strip()).group(1))
        if page not in {int(line['start']) for line in lines}:
            return None
        match = _PAGE.fullmatch(str(end).strip()) if end else None
        last = int(match.group(1)) if match else None
        last = last if last and last > page else None
        return {'start': float(page), 'end': float(last) if last else None,
                'label': f's.{page}' + (f'-{last}' if last else '')}

    def split_citations(self, text, videos):
        """Cevabi metin ve atif parcalarina ayirir (qa.split_citations'in coklu video hali).

        Donen: [('text', str) | ('cite', [{'video','video_label','title','start','end','label'}])].
        Etiketsiz zaman ([12:34]) yalnizca baglamda tek video varsa kabul edilir.
        """
        parts = []
        single = next(iter(videos)) if len(videos) == 1 else None

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
                cite = self._resolve(match.group(1), match.group(2), match.group(3), videos)
                if cite is None:
                    continue
                add_text(value[position:match.start()])
                parts.append(('cite', [cite]))
                position = match.end()
            add_text(value[position:])

        position = 0
        for match in _BRACKET.finditer(text):
            items = [_ITEM.fullmatch(item) for item in re.split(r'[;,]', match.group(1))]
            if not all(items):
                continue
            bare(text[position:match.start()])
            cites, label = [], single
            for item in items:
                label = item.group(1) or label
                if label is None:
                    continue
                cite = self._resolve(label, item.group(2), item.group(3), videos)
                if cite is not None:
                    cites.append(cite)
            if cites:
                parts.append(('cite', cites))
            elif parts and parts[-1][0] == 'text':  # uydurma atif: metinden atilir
                parts[-1] = ('text', parts[-1][1].rstrip(' '))
            position = match.end()
        bare(text[position:])
        return parts

    @staticmethod
    def _sources(parts):
        """Cevapta atif yapilan videolar, atif sayisiyla (ilk gorulme sirasiyla)."""
        sources = {}
        for kind, value in parts:
            if kind != 'cite':
                continue
            for cite in value:
                item = sources.setdefault(cite['video'], {
                    'video': cite['video'], 'label': cite['video_label'],
                    'title': cite['title'], 'count': 0, 'start': cite['start']})
                item['count'] += 1
        return list(sources.values())


# --- ozetler (F61) ----------------------------------------------------------------
OVERVIEW_PROMPT = '''You receive short summaries of the videos and documents in a collection (for example a lecture series or a set of manuals), in collection order. Reply with a JSON object only, no other text:
{"summary": "<Turkish, 4-8 sentences: what the collection covers overall, how it progresses and its main takeaways>",
 "topics": ["<Turkish short topic>", ...],
 "questions": ["<Turkish question a viewer might ask about the whole collection>", ...]}
Give 4-8 topics and exactly 4 questions that the collection can answer. Use only the summaries.'''


def summarize_video(video, config_provider=load_config, log=print, progress=None, cancelled=None,
                    base=None):
    """Videonun genel ozetini (Soru Sor panelindeki ile ayni) uretir ya da onbellekten verir.

    Uzun videolarda once bolum ozetleri cikarilir (qa.VideoQA 'map' modu); her adim
    onbellege yazilir, kesilirse kaldigi yerden devam eder. Transkript yoksa None."""
    session = search_index.primary_session(video, base)
    if session is None:
        return None
    if session.get('overview'):
        return session['overview']
    path = qa.cache_path(video, qa.source_key(session['source']), base)
    if qa.is_document(session):
        return summarize_document(session, path, config_provider, log, progress, cancelled)
    worker = qa.VideoQA(session, config_provider=config_provider, log=log,
                        save=lambda data: save_json(path, data))
    return worker.prepare(progress=progress, cancelled=cancelled)


DOCUMENT_OVERVIEW_PROMPT = '''You receive the text of a document (page markers like [s.3]; for spreadsheets a page is a sheet, for e-books a chapter) or the page-by-page summaries of a long document. Reply with a JSON object only, no other text:
{"summary": "<Turkish, 3-6 sentences: what the document is about, its main points and conclusions>",
 "topics": ["<Turkish short topic>", ...],
 "questions": ["<Turkish question a reader might ask about this document>", ...]}
Give 3-6 topics and exactly 4 questions answerable from the document. Use only the given text.'''

DOCUMENT_PART_PROMPT = '''You receive one part of a document's text (page markers like [s.3]). Reply with a JSON object only, no other text:
{"summary": "<Turkish, 2-5 sentences with the concrete facts, numbers, names, instructions and conclusions of this part>"}
Use only the text.'''


def summarize_document(session, path, config_provider=load_config, log=print, progress=None,
                       cancelled=None):
    """Belge ozeti (F67): sigarsa tum metinden tek istek; sigmazsa once parca ozetleri.

    Parca ozetleri oturuma ('part_summaries') yazilir; kesilirse kaldigi yerden devam eder."""
    cfg = config_provider()
    client = Client(cfg, log=log)
    lines = qa.lines_of(session)
    budget = max(4000, int(cfg.get('qa_context_chars', 24000)) - 1500)
    text = qa.format_lines(lines, True)
    title = session.get('title') or Path(path).stem
    if len(text) > budget:
        parts, current = [], []
        for line in lines:
            if current and sum(len(item['text']) + 12 for item in current) + len(line['text']) \
                    > qa.SECTION_CHARS:
                parts.append(current)
                current = []
            current.append(line)
        if current:
            parts.append(current)
        done = session.setdefault('part_summaries', {})
        for number, part in enumerate(parts, 1):
            if cancelled and cancelled():
                from app_core import GracefulStop
                raise GracefulStop('Özet durduruldu; tamamlanan bölümler kaydedildi.')
            span = f'{int(part[0]["start"])}-{int(part[-1]["start"])}'
            if span not in done:
                value = _ask_json(client, cfg, DOCUMENT_PART_PROMPT,
                                  f'DOCUMENT: {title}\nPAGES {span}\n\n'
                                  + qa.format_lines(part, True), log)
                done[span] = ' '.join(str(value.get('summary', '')).split())
                save_json(path, session)
            if progress:
                progress(number, len(parts) + 1)
        text = '\n'.join(f'[s.{span}] {summary}' for span, summary in done.items())
    overview = qa.normalize_overview(_ask_json(client, cfg, DOCUMENT_OVERVIEW_PROMPT,
                                               f'DOCUMENT: {title}\n\n{text}', log))
    session['overview'] = overview
    save_json(path, session)
    if progress:
        progress(1, 1)
    return overview


def _ask_json(client, cfg, system, user, log):
    retries = int(cfg.get('auto_retry_count', 2))
    for attempt in range(retries + 1):
        try:
            return qa.parse_json_object(client.chat([{'role': 'system', 'content': system},
                                                     {'role': 'user', 'content': user}]))
        except (ValueError, RuntimeError) as error:
            if not retryable_translation_error(error) or attempt >= retries:
                raise
            log(f'Geçici hata (deneme {attempt + 1}/{retries + 1}): {error}')
    raise RuntimeError('Model isteği tamamlanamadı.')


def video_summaries(videos, base=None):
    """Ozeti cikarilmis videolar: [{'video', 'title', 'summary', 'topics'}] (koleksiyon sirasi)."""
    items = []
    for video in videos:
        session = search_index.primary_session(video, base)
        overview = (session or {}).get('overview') or {}
        if overview.get('summary'):
            items.append({'video': str(video), 'title': session.get('title') or Path(video).stem,
                          'summary': overview['summary'], 'topics': overview.get('topics', [])})
    return items


def build_overview(title, videos, cfg, client=None, log=print, base=None):
    """Video ozetlerinden koleksiyon ozeti. Ozetli video yoksa None.

    Donen: {'summary', 'topics', 'questions', 'videos': [ozetli yollar], 'title'}."""
    items = video_summaries(videos, base)
    if not items:
        return None
    labels = video_labels(videos)
    budget = int(cfg.get('qa_context_chars', 24000))
    share = max(200, budget // len(items) - 40)  # cok video: her ozet esit kisaltilir
    text = '\n'.join(f'{labels[_key(item["video"])]} {item["title"]}: {item["summary"][:share]}'
                      for item in items)
    client = client or Client(cfg, log=log)
    messages = [{'role': 'system', 'content': OVERVIEW_PROMPT},
                {'role': 'user', 'content': f'COLLECTION: {title}\n\n{text}'}]
    retries = int(cfg.get('auto_retry_count', 2))
    for attempt in range(retries + 1):
        try:
            value = qa.normalize_overview(qa.parse_json_object(client.chat(messages)))
            break
        except (ValueError, RuntimeError) as error:
            if not retryable_translation_error(error) or attempt >= retries:
                raise
            log(f'Geçici hata (deneme {attempt + 1}/{retries + 1}): {error}')
    value.update(title=title, videos=[item['video'] for item in items])
    return value
