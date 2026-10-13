"""Kutuphane indeksi (F57): transkript parcalari -> embedding vektorleri -> anlamsal arama.

Qt'den bagimsizdir. Her video icin transkript (qa onbellegindeki oturum)
~90 saniyelik parcalara bolunur, LM Studio'daki embedding modeliyle vektore
cevrilir ve `work_files/index/` altina yazilir. Video, transkript kaynagi veya
embedding modeli degisirse dosya adi (anahtar) degisir ve yeniden uretilir.

Vektorler birim uzunluga normalize edilir; benzerlik = ic carpim (cosine).
Arama saf Python'dur (numpy gerekmez): 100+ videoda birkac bin parca icin
yeterince hizlidir.
"""
from __future__ import annotations

import base64
import heapq
import json
import math
import re
import threading
from array import array
from operator import mul
from pathlib import Path

import qa
from app_core import Client, digest, read, save_json

VERSION = 1
CHUNK_SECONDS = 90.0
CHUNK_CHARS = 1000
EMBED_BATCH = 32
_MEMO = {}  # indeks dosyasi -> (meta, vektorler); ayni surecte bir kez okunur
_MEMO_LOCK = threading.Lock()


def index_dir(base=None):
    return Path(base or qa.work_dir()) / 'index'


def pick_session(sessions):
    """Indekslenecek transkript: altyazi oturumu (dusuk akis no) ya da Whisper."""
    if not sessions:
        return None
    return min(sessions, key=lambda data: (data['source'].get('kind') != 'subtitle',
                                           qa.source_key(data['source'])))


def primary_session(video, base=None):
    return pick_session(qa.cached_sessions(video, base))


def index_path(video, session, cfg, base=None):
    video = Path(video).resolve()
    stat = video.stat()
    key = digest('|'.join((str(VERSION), str(video), str(stat.st_size), str(int(stat.st_mtime)),
                           qa.source_key(session['source']), str(cfg['embedding_model']),
                           str(cfg['embedding_document_template']))))[:16]
    stem = re.sub(r'[^\w.-]+', '_', video.stem)[:40] or 'video'
    return index_dir(base) / f'{stem}.{key}.json'


def chunk_lines(segments, max_seconds=CHUNK_SECONDS, max_chars=CHUNK_CHARS):
    """Transkripti arama parcalarina boler; ardisik parcalar bir satir ortusur."""
    lines = qa.compact_lines(segments)
    chunks, current = [], []
    for line in lines:
        if current and (line['end'] - current[0]['start'] > max_seconds
                        or sum(len(item['text']) + 1 for item in current) + len(line['text'])
                        > max_chars):
            chunks.append(current)
            current = current[-1:]  # baglam kopmasin diye son satir tekrar
        current.append(line)
    if current:
        chunks.append(current)
    return [{'start': part[0]['start'], 'end': part[-1]['end'],
             'text': ' '.join(item['text'] for item in part)} for part in chunks]


def normalize(vector):
    length = math.sqrt(sum(value * value for value in vector)) or 1.0
    return array('f', (value / length for value in vector))


def _pack(vectors):
    data = array('f')
    for vector in vectors:
        data.extend(vector)
    return base64.b64encode(data.tobytes()).decode('ascii')


def _unpack(text, dims):
    data = array('f')
    data.frombytes(base64.b64decode(text))
    return [data[start:start + dims] for start in range(0, len(data), dims)]


def has_index(video, cfg, base=None):
    if not str(cfg.get('embedding_model', '')).strip():
        return False
    session = primary_session(video, base)
    try:
        return session is not None and index_path(video, session, cfg, base).exists()
    except OSError:
        return False


def build(video, cfg, client=None, base=None, log=print, cancelled=None):
    """Videonun indeksini (yoksa) uretir. Donen: indeks dosyasi ya da transkript yoksa None."""
    session = primary_session(video, base)
    if session is None:
        return None
    path = index_path(video, session, cfg, base)
    if path.exists():
        return path
    chunks = chunk_lines(session['segments'])
    if not chunks:
        raise ValueError('Transkript boş; indekslenecek metin yok.')
    client = client or Client(cfg, log=log)
    title = session.get('title') or Path(video).stem
    template = str(cfg['embedding_document_template'])
    vectors = []
    for start in range(0, len(chunks), EMBED_BATCH):
        if cancelled and cancelled():
            from app_core import GracefulStop
            raise GracefulStop('İndeksleme durduruldu.')
        batch = chunks[start:start + EMBED_BATCH]
        texts = [template.replace('{title}', title).replace('{text}', item['text'])
                 for item in batch]
        vectors.extend(normalize(vector) for vector in client.embed(texts))
    dims = len(vectors[0])
    if any(len(vector) != dims for vector in vectors):
        raise ValueError('Embedding boyutları tutarsız.')
    save_json(path, {'version': VERSION, 'video': str(video), 'title': title,
                     'model': cfg['embedding_model'], 'source': session['source'],
                     'dims': dims, 'chunks': chunks, 'vectors': _pack(vectors)})
    log(f'İndekslendi: {len(chunks)} parça.')
    return path


def load(path):
    """(meta, vektorler) - surec icinde onbellekli."""
    key = str(path)
    with _MEMO_LOCK:
        if key in _MEMO:
            return _MEMO[key]
    meta = json.loads(read(path))
    vectors = _unpack(meta.pop('vectors'), int(meta['dims']))
    if len(vectors) != len(meta['chunks']):
        raise ValueError('İndeks dosyası bozuk: ' + key)
    with _MEMO_LOCK:
        _MEMO[key] = (meta, vectors)
    return meta, vectors


def search(videos, query, cfg, client=None, limit=12, base=None, log=print):
    """Videolarin indekslerinde soruya en yakin parcalar.

    Donen: [{'video', 'title', 'start', 'end', 'text', 'score'}] (azalan skor).
    Indeksi olmayan videolar atlanir.
    """
    query = ' '.join(str(query).split())
    if not query:
        return []
    client = client or Client(cfg, log=log)
    probe = str(cfg['embedding_query_template']).replace('{query}', query)
    wanted = normalize(client.embed([probe])[0])
    scored = []
    for video in videos:
        session = primary_session(video, base)
        if session is None:
            continue
        try:
            path = index_path(video, session, cfg, base)
            if not path.exists():
                continue
            meta, vectors = load(path)
        except (OSError, ValueError, KeyError) as error:
            log(f'İndeks okunamadı ({Path(video).name}): {error}')
            continue
        if len(wanted) != int(meta['dims']):
            log(f'İndeks boyutu farklı, atlandı: {Path(video).name}')
            continue
        for chunk, vector in zip(meta['chunks'], vectors):
            scored.append((sum(map(mul, wanted, vector)), str(video), meta['title'], chunk))
    best = heapq.nlargest(limit, scored, key=lambda item: item[0])
    return [{'video': video, 'title': title, 'start': chunk['start'], 'end': chunk['end'],
             'text': chunk['text'], 'score': round(score, 4)}
            for score, video, title, chunk in best]
