"""Genel sohbet (F83): Claude benzeri serbest sohbet + tum kutuphanede arka plan aramasi.

Arayuzden bagimsizdir. Her mesajda soru (ve onceki soru) tum koleksiyonlarin ve son
incelenen dosyalarin indekslerinde embedding ile aranir; yeterince yakin parcalar
varsa "kutuphane notlari" olarak baglama eklenir. Model notlari yalnizca soru
kullanicinin dosyalariyla ilgiliyse kullanir ve o zaman [V2 12:34] / [V3 s.5]
atiflari yapar; degilse normal bir asistan gibi konusur.

Sohbetler `library/conversations/<id>.json` dosyalarindadir.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

import backlog
import collection_qa
import library
import qa
import search_index
from app_core import Client, load_config, qa_config, read, save_json

HIT_LIMIT = 16
# Notlar ancak en iyi parca MIN_SCORE'u gecerse eklenir; o zaman en iyiden en fazla
# KEEP_MARGIN asagidakiler (ve KEEP_FLOOR ustundekiler) girer. EmbeddingGemma'da ilgisiz
# sorular (selamlasma, genel bilgi) ~0.52-0.61, ilgili parcalar ~0.70+ cikiyor.
# Esik kacirsa da model notlari yok saymasi icin uyarilir.
MIN_SCORE = 0.66
KEEP_MARGIN = 0.12
KEEP_FLOOR = 0.6
CONTEXT_SHARE = 0.5      # qa_context_chars'in notlara ayrilan payi
HISTORY_TURNS = 8
TEMPERATURE = 0.7
FILES_TTL = 60.0         # kutuphane dosya listesi bu kadar saniye onbellekte kalir
OVERVIEW_CHARS = 320     # koleksiyon basina ozetten alinan en fazla karakter
TITLE_CHARS = 60
CONVERSATION_LIMIT = 200  # diskte tutulan en fazla sohbet

SYSTEM_PROMPT = '''You are the assistant inside Aktar, a desktop app for the user's personal library of videos and documents. Behave like a capable general-purpose AI assistant: chat naturally, answer from your own knowledge, help with writing, explanations, reasoning, planning and code.

- Reply in the language the user writes in (usually Turkish). Be natural and to the point; use Markdown (short paragraphs, lists, tables, code blocks) when it helps. Do not use LaTeX; write formulas with plain text and Unicode (R², x₁, ≤).
- Below you may find LIBRARY NOTES: excerpts that an automatic search pulled from the user's own videos and documents for the latest message. They can be irrelevant. Use them only when the user asks about their files or the content clearly helps answer; otherwise ignore them completely and do not mention the library, the search or the notes.
- When you do use the notes, cite them in square brackets right after the sentence they support: file id + timestamp for videos, e.g. [V2 12:34] or [V2 12:34-13:10], file id + page for documents, e.g. [V3 s.12]. Use only ids and positions that appear in the notes; never invent a citation. Do not cite your own general knowledge.
- LIBRARY OVERVIEW lists the user's collections; use it when they ask what is in their library.
- BACKLOG RECORDS, when present, are entries from the user's own game/anime/manga/film/book tracker for titles mentioned in the conversation. Use them to answer questions about what the user owns, played, watched or read (platform, store/digital service, status, playtime, score, dates). Several lines with the same title mean several copies or entries; mention all relevant ones. If a title the user asks about is not in the records, say it is not in their backlog. Do not cite backlog records with brackets.'''

_CITE = re.compile(r'\s?\[(?:V\d+[^\[\]\n]{0,150})\]')
_OPEN_THINK = re.compile(r'(?is)<think>.*$')


def conversations_dir():
    return library.library_dir() / 'conversations'


def _path(conversation_id):
    if not re.fullmatch(r'[\w-]{1,64}', str(conversation_id)):
        raise ValueError('Geçersiz sohbet kimliği.')
    return conversations_dir() / f'{conversation_id}.json'


def _now():
    return datetime.now().isoformat(timespec='seconds')


def new_conversation():
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    return {'id': f'{stamp}-{secrets.token_hex(3)}', 'title': '', 'created': _now(), 'updated': _now(),
            'entries': [], 'history': []}


def load_conversation(conversation_id):
    """Kayitli sohbet; yoksa ya da okunamazsa ValueError."""
    try:
        value = json.loads(read(_path(conversation_id)))
    except (OSError, ValueError):
        raise ValueError('Sohbet bulunamadı.') from None
    if not isinstance(value, dict):
        raise ValueError('Sohbet dosyası geçersiz.')
    value['entries'] = [(str(kind), item) for kind, item in value.get('entries', [])
                        if kind in ('user', 'assistant', 'error')]
    value['history'] = [{'question': str(turn.get('question', '')), 'answer': str(turn.get('answer', ''))}
                        for turn in value.get('history', []) if isinstance(turn, dict)]
    value['id'] = str(conversation_id)
    value.setdefault('title', '')
    return value


def save_conversation(data):
    data['updated'] = _now()
    save_json(_path(data['id']), {
        'version': 1, 'id': data['id'], 'title': data.get('title', ''), 'created': data.get('created', _now()),
        'updated': data['updated'],
        'entries': [[kind, item] for kind, item in data['entries'] if kind in ('user', 'assistant', 'error')],
        'history': [{'question': turn['question'], 'answer': turn['answer']} for turn in data['history']]})
    _prune()


def _prune():
    items = list_conversations()
    for item in items[CONVERSATION_LIMIT:]:
        delete_conversation(item['id'])


def delete_conversation(conversation_id):
    try:
        _path(conversation_id).unlink()
    except FileNotFoundError:
        pass


def rename_conversation(conversation_id, title):
    data = load_conversation(conversation_id)
    data['title'] = ' '.join(str(title).split())[:120]
    save_conversation(data)
    return data


def list_conversations():
    """[{'id', 'title', 'updated'}] (yeniden eskiye)."""
    folder = conversations_dir()
    items = []
    if folder.is_dir():
        for path in folder.glob('*.json'):
            try:
                value = json.loads(read(path))
            except (OSError, ValueError):
                continue
            if isinstance(value, dict):
                items.append({'id': path.stem, 'title': str(value.get('title') or 'Yeni sohbet'),
                              'updated': str(value.get('updated', ''))})
    return sorted(items, key=lambda item: item['updated'], reverse=True)


def make_title(question):
    text = ' '.join(str(question).split())
    if len(text) <= TITLE_CHARS:
        return text
    return text[:TITLE_CHARS].rsplit(' ', 1)[0].rstrip(',.;:') + '…'


def visible_text(text):
    """Akis sirasinda gosterilecek metin: dusunce bloklari (kapanmamis olani dahil) gizlenir."""
    return _OPEN_THINK.sub('', qa.strip_thinking(text)).strip()


def strip_citations(text):
    """Gecmise giden cevaplardan atiflar silinir: etiketler her soruda yeniden verilir."""
    return _CITE.sub('', str(text))


# --- kutuphane -----------------------------------------------------------------
_FILES = {'time': 0.0, 'files': [], 'overview': ''}
_FILES_LOCK = threading.Lock()


def library_snapshot(force=False):
    """(dosyalar, koleksiyon ozeti metni): tum koleksiyonlarin mevcut dosyalari + son
    incelenen dosyalar. Klasor taramasi pahali oldugu icin FILES_TTL boyunca onbellekte."""
    with _FILES_LOCK:
        if not force and time.monotonic() - _FILES['time'] < FILES_TTL:
            return list(_FILES['files']), _FILES['overview']
    files, seen, lines = [], set(), []

    def add(path):
        key = library._key(path)
        if key not in seen:
            seen.add(key)
            files.append(Path(path))

    for slug, data in library.list_collections().items():
        try:
            entries, _changed = library.scan(data)
        except (OSError, ValueError):
            continue
        present = [entry['path'] for entry in entries if not entry['missing']]
        for path in present:
            add(path)
        line = f'- {data["title"]} ({len(present)} dosya)'
        overview = library.load_overview(slug)
        if overview and overview.get('summary'):
            summary = ' '.join(str(overview['summary']).split())
            line += ': ' + (summary[:OVERVIEW_CHARS].rsplit(' ', 1)[0] + '…'
                            if len(summary) > OVERVIEW_CHARS else summary)
        lines.append(line)
    recent = [item['path'] for item in library.load_recent() if Path(item['path']).is_file()]
    for path in recent:
        add(path)
    if recent:
        lines.append(f'- Tek tek incelenen dosyalar ({len(recent)} dosya)')
    text = 'LIBRARY OVERVIEW (collections):\n' + '\n'.join(lines) if lines else ''
    with _FILES_LOCK:
        _FILES.update(time=time.monotonic(), files=files, overview=text)
    return list(files), text


def forget_snapshot():
    with _FILES_LOCK:
        _FILES['time'] = 0.0


# --- soru ----------------------------------------------------------------------
class Assistant:
    """Bir sohbetin cevaplayicisi. history: [{'question', 'answer'}]."""

    def __init__(self, history=None, config_provider=load_config, log=print, snapshot=library_snapshot,
                 backlog_notes=backlog.notes):
        self.history = list(history or [])
        self.config_provider = config_provider
        self.log = log
        self.snapshot = snapshot
        self.backlog = backlog_notes

    def _query(self, question):
        previous = self.history[-1]['question'] if self.history else ''
        return (previous + ' ' + question).strip() if previous else question

    def notes(self, question, cfg, client):
        """(not metni, {etiket: dosya}, CollectionQA ya da None) - ilgili parca yoksa bos."""
        files, overview = self.snapshot()
        if not files or not str(cfg.get('embedding_model', '')).strip():
            return overview, {}, None
        try:
            hits = search_index.search(files, self._query(question), cfg, client, limit=HIT_LIMIT,
                                       log=self.log)
        except (RuntimeError, ValueError, OSError) as error:
            self.log('Kütüphane araması yapılamadı: ' + str(error))
            return overview, {}, None
        if not hits or hits[0]['score'] < MIN_SCORE:
            return overview, {}, None
        floor = max(KEEP_FLOOR, hits[0]['score'] - KEEP_MARGIN)
        hits = [hit for hit in hits if hit['score'] >= floor]
        order = list(dict.fromkeys(hit['video'] for hit in hits))  # en iyi eslesen dosya V1
        notes_cfg = dict(cfg, qa_context_chars=int(int(cfg.get('qa_context_chars', 24000)) * CONTEXT_SHARE))
        session = collection_qa.CollectionQA(order, log=self.log)
        context, videos = session.build_context(hits, notes_cfg)
        self.log(f'Kütüphane notları: {len(hits)} parça, {len(videos)} dosya '
                 f'(en iyi benzerlik {hits[0]["score"]:.2f}).')
        text = (overview + '\n\n' if overview else '') + 'LIBRARY NOTES (automatic search; may be irrelevant):\n' \
            + context.replace('VIDEOS IN THE EXCERPTS:', 'FILES IN THE NOTES:', 1)
        return text, videos, session

    def ask(self, question, on_delta=None, cancelled=None, client=None, think=None):
        """Cevaplar. Donen: {'question', 'answer', 'parts', 'sources', 'stopped'}."""
        question = ' '.join(str(question).split()) if '\n' not in str(question) else str(question).strip()
        if not question:
            raise ValueError('Mesaj boş olamaz.')
        cfg = qa_config(self.config_provider(), think)
        client = client or Client(cfg, log=self.log)
        notes, videos, session = self.notes(question, cfg, client)
        records = self.backlog(self._query(question), cfg, log=self.log)
        system = SYSTEM_PROMPT + ''.join('\n\n' + part for part in (notes, records) if part)
        messages = [{'role': 'system', 'content': system}]
        for turn in self.history[-HISTORY_TURNS:]:
            messages.append({'role': 'user', 'content': turn['question']})
            messages.append({'role': 'assistant', 'content': strip_citations(turn['answer'])})
        messages.append({'role': 'user', 'content': question})
        text, finish = client.chat_stream(
            messages, on_delta=(lambda value: on_delta(visible_text(value))) if on_delta else None,
            temperature=TEMPERATURE, cancelled=cancelled)
        answer = qa.strip_thinking(text)
        stopped = finish == 'cancelled'
        if not answer and not stopped:
            raise ValueError('Yanıt boş döndü. Model düşünme (reasoning) üretiyor olabilir; '
                             'LM Studio\'da thinking\'i kapatın ya da max_tokens\'ı artırın.')
        if finish == 'length':
            answer += '\n\n*(Yanıt token sınırında kesildi.)*'
        parts = session.split_citations(answer, videos) if session is not None else [('text', answer)]
        turn = {'question': question, 'answer': answer, 'parts': parts,
                'sources': collection_qa.CollectionQA._sources(parts), 'stopped': stopped}
        if answer:
            self.history.append({'question': question, 'answer': answer})
        return turn
