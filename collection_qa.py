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
from app_core import Client, load_config, retryable_translation_error

HIT_LIMIT = 24
HISTORY_TURNS = 4
_STAMP = r'(?:\d+:)?\d{1,2}:\d{2}'
_BRACKET = re.compile(r'\[([^\[\]\n]{3,160})\]')
_ITEM = re.compile(r'\s*(?:(V\d+)\s*[·:,]?\s*)?(' + _STAMP + r')(?:\s*[-–—]\s*(' + _STAMP + r'))?\s*')
_BARE = re.compile(r'(?<![\w\[])(V\d+)\s*[·:]?\s*(' + _STAMP + r')(?:\s*[-–—]\s*(' + _STAMP
                   + r'))?(?![\d:])')

ANSWER_PROMPT = '''You answer questions about a collection of videos (for example a lecture series). Relevant excerpts from the videos' timestamped transcripts are given below; each video has an id such as V3.

Rules:
- Answer in Turkish, naturally and concisely. Use short paragraphs or bullet points when they help.
- Ground the answer in the excerpts. Combine information from several videos when the question asks for it, and say which video covers what (use the video title when it helps the reader).
- Support claims with citations in square brackets: video id + timestamp, e.g. [V3 12:34] for a moment or [V3 12:34-13:10] for a stretch; several at once as [V3 12:34; V7 5:10]. Put the citation right after the sentence it supports. Use only video ids and timestamps that appear in the excerpts; never invent one.
- If the excerpts do not cover the question, say so clearly. You may add brief general knowledge only if you mark it explicitly as not coming from the videos (for example "Videolarda geçmiyor ama genel olarak ...") and you never cite it.
- Do not mention excerpts, transcripts or these rules; speak about "the videos".'''


def video_labels(videos):
    """Koleksiyon sirasina gore sabit etiketler: {anahtar: 'V1', ...}."""
    return {_key(path): f'V{index + 1}' for index, path in enumerate(videos)}


def _key(path):
    return str(Path(path)).casefold()


class CollectionQA:
    """Bir koleksiyonun indeksli videolari uzerinde cok turlu soru-cevap."""

    def __init__(self, videos, title='', config_provider=load_config, log=print, base=None):
        self.videos = [Path(path) for path in videos]
        self.title = title
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
                                    qa.compact_lines(session['segments']),
                                    float(session.get('duration') or 0.0))
        return self._lines[key]

    def _query(self, question):
        """Devam sorularinda ("peki neden?") onceki soru da aranir."""
        previous = self.history[-1]['question'] if self.history else ''
        return (previous + ' ' + question).strip() if previous else question

    def build_context(self, hits, cfg):
        """Arama sonuclarindan baglam metni. Donen: (metin, {etiket: video})."""
        budget = int(cfg.get('qa_context_chars', 24000))
        chosen = {}  # video anahtari -> {'video', 'lines': set(satir indeksleri)}
        used = 0
        for hit in hits:
            data = self._video_lines(hit['video'])
            if data is None:
                continue
            _title, lines, _duration = data
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
            title, lines, duration = self._video_lines(entry['video'])
            videos[label] = entry['video']
            picked = [lines[index] for index in sorted(entry['lines'])]
            head = f'### {label} · {title}' + (f' ({qa.format_time(duration)})' if duration else '')
            blocks.append(head + '\n' + qa.format_lines(picked))
        index = '\n'.join(f'{label} = {self._video_lines(path)[0]}' for label, path in videos.items())
        text = ((f'COLLECTION: {self.title}\n' if self.title else '')
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
        cfg = self.config_provider()
        client = client or Client(cfg, log=self.log)
        hits = search_index.search(self.videos, self._query(question), cfg, client,
                                   limit=HIT_LIMIT, base=self.base, log=self.log)
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
        video = videos.get(label)
        data = self._video_lines(video) if video is not None else None
        if data is None:
            return None
        title, lines, duration = data
        cite = qa.resolve_citation(start, end, lines, duration)
        if cite is None:
            return None
        cite.update(video=str(video), video_label=label, title=title,
                    label=f'{label} {cite["label"]}')
        return cite

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
                cite = self._resolve(match.group(1), qa.parse_time(match.group(2)),
                                     qa.parse_time(match.group(3)) if match.group(3) else None,
                                     videos)
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
                cite = self._resolve(label, qa.parse_time(item.group(2)),
                                     qa.parse_time(item.group(3)) if item.group(3) else None,
                                     videos)
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
