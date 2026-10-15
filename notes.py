"""Not ve vurgu (F113): oynaticida videonun bir anina, belgede bir sayfaya (ya da secili metne)
kullanicinin yazdigi notlar.

Dosya basina kutuphane klasorunde `note-<ozet>.notes.json` olarak saklanir; adinda nokta
oldugu icin library.list_collections onu koleksiyon saymaz. Kaynak dosyaya dokunulmaz.
Notun konumu `at`: video icin saniye, belge icin sayfa numarasi (1'den baslar). `quote`
belgede vurgulanan metindir (bos olabilir). Koleksiyon sohbeti notlari baglama koyar.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import library
from app_core import FileLock, digest, read, save_json

VERSION = 1
COLORS = ('yellow', 'green', 'blue', 'pink')
TEXT_LIMIT = 4000
QUOTE_LIMIT = 1000


def notes_path(path):
    return library.library_dir() / ('note-' + digest(library._key(path))[:16] + '.notes.json')


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _clean(note):
    """Diskten okunan notu dogrular; bozuksa None."""
    if not isinstance(note, dict) or not note.get('id'):
        return None
    try:
        at = max(0.0, float(note.get('at') or 0))
    except (TypeError, ValueError):
        return None
    color = note.get('color') if note.get('color') in COLORS else COLORS[0]
    return {'id': str(note['id']), 'at': at, 'text': str(note.get('text') or ''),
            'quote': str(note.get('quote') or ''), 'color': color,
            'created': str(note.get('created') or ''), 'updated': str(note.get('updated') or '')}


def load(path):
    """Dosyanin notlari, konuma gore sirali (okunamazsa bos liste)."""
    try:
        value = json.loads(read(notes_path(path)))
    except (OSError, ValueError):
        return []
    items = value.get('notes', []) if isinstance(value, dict) else []
    notes = [note for note in map(_clean, items) if note is not None]
    return sorted(notes, key=lambda note: (note['at'], note['created']))


def _save(path, notes):
    target = notes_path(path)
    if not notes:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    save_json(target, {'version': VERSION, 'path': str(path), 'notes': notes})


def _edit(path, change):
    """Notlari kilit altinda okuyup `change(notes)` ile degistirir ve yazar."""
    directory = library.library_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(directory / 'notes.lock'):
        notes = load(path)
        result = change(notes)
        _save(path, notes)
    return result


def _text(value, limit):
    return str(value or '').strip()[:limit]


def add(path, at, text='', quote='', color=None):
    """Yeni not ekler; eklenen notu dondurur. Metin ve alinti ikisi birden bos olamaz."""
    text, quote = _text(text, TEXT_LIMIT), ' '.join(str(quote or '').split())[:QUOTE_LIMIT]
    if not text and not quote:
        raise ValueError('Not boş olamaz.')
    note = {'id': uuid.uuid4().hex[:12], 'at': max(0.0, float(at or 0)), 'text': text,
            'quote': quote, 'color': color if color in COLORS else COLORS[0],
            'created': _now(), 'updated': ''}
    _edit(path, lambda notes: notes.append(note))
    return note


def update(path, note_id, text=None, color=None):
    """Notun metnini/rengini degistirir; metni ve alintisi bosalan not silinir."""
    def change(notes):
        for index, note in enumerate(notes):
            if note['id'] != note_id:
                continue
            if text is not None:
                note['text'] = _text(text, TEXT_LIMIT)
            if color in COLORS:
                note['color'] = color
            note['updated'] = _now()
            if not note['text'] and not note['quote']:
                del notes[index]
            return True
        return False
    return _edit(path, change)


def delete(path, note_id):
    def change(notes):
        before = len(notes)
        notes[:] = [note for note in notes if note['id'] != note_id]
        return len(notes) != before
    return _edit(path, change)


def collect(paths):
    """{yol: notlar} (notu olmayan dosyalar atlanir); koleksiyon sohbeti icin."""
    found = {}
    for path in paths:
        notes = load(Path(path))
        if notes:
            found[str(path)] = notes
    return found
