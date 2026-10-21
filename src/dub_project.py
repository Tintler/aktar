"""Dublaj duzenleyicisi (F175): dublaji tek seferde yazmak yerine duzenlenebilir bir proje.

Proje videonun dublaj klasorunde tutulur (work_files/dublaj/<dub.cache_id>/proje.json) ve satirlarin
uretilmis sesleri yanindaki satirlar/ klasorundedir (<kimlik>-<deneme>.wav). Kullanici:
  - satiri boler, birlestirir, metnini ve Drama 3 ifade etiketini duzeltir, sesini (konusmaci) degistirir;
  - dublaj sesini istedigi yere tasir ('at'; None: satirin kendi zamani, onceki ses bitmediyse arkasi);
  - satirin ses duzeyini ('gain') ayarlar, istedigi satiri yeniden seslendirir (onbellege bakmadan yeni deneme);
  - ozgun sesin kisilacagi yerleri elle cizer ('ducks' [{start, end, level}]; None: otomatik, dub.duck_spans).
Metin/etiket/ses/hiz degisen satirin sesi 'eski' sayilir (imza 'sig'); eski ses yeniden uretilene kadar calar.

Alan sahipligi: duzenlenebilir alanlar (EDIT_KEYS) arayuzden gelir; ses alanlari (AUDIO_KEYS) yalnizca uretim
isinde yazilir. save() arayuzden gelen satirlara dosyadaki ses alanlarini kimlige gore geri koyar; boylece arka
plandaki uretim ve arayuzun kaydetmesi birbirinin yazdigini silmez (tek kilit: _LOCK).
Kaynak video SALT-OKUNUR.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import tempfile
import threading
import wave
from array import array
from pathlib import Path

import dub
import qa
from app_core import GracefulStop

VERSION = 1
LINES_DIR = 'satirlar'
EDIT_KEYS = ('start', 'end', 'text', 'tag', 'voice', 'speaker', 'at', 'gain', 'speed', 'fit')
AUDIO_KEYS = ('audio', 'duration', 'sig', 'take', 'tempo')
GAIN = (0.0, 4.0)
MIN_LINE = 0.05
_LOCK = threading.RLock()


def folder(video):
    return qa.work_dir() / 'dublaj' / dub.cache_id(video)


def project_path(video):
    return folder(video) / 'proje.json'


def load(video):
    """Kayitli proje ya da None."""
    path = project_path(video)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get('version') != VERSION:
        return None
    if data.get('ducks') is not None:
        data['ducks'] = clean_ducks(data['ducks'])   # eski kayitlarda bos liste kalmis olabilir
    return data


def _write(video, project):
    path = project_path(video)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix('.part')
    partial.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(partial, path)


def _number(value, default=None, low=None, high=None):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if value != value:   # NaN
        return default
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return round(value, 3)


def clean_line(item, ident):
    """Arayuzden gelen satir -> gecerli duzenlenebilir alanlar (gecersizse None)."""
    text = ' '.join(str(item.get('text') or '').split())
    start = _number(item.get('start'), None, 0.0)
    end = _number(item.get('end'), None, 0.0)
    if not text or start is None or end is None:
        return None
    speaker = item.get('speaker')
    return {'id': int(ident), 'start': start, 'end': max(start + MIN_LINE, end), 'text': text,
            'tag': str(item.get('tag') or '').strip(), 'voice': str(item.get('voice') or ''),
            'speaker': None if speaker in (None, '') else int(speaker),
            'at': _number(item.get('at'), None, 0.0), 'gain': _number(item.get('gain'), 1.0, *GAIN),
            'speed': _number(item.get('speed'), 1.0, 0.5, 2.0), 'fit': item.get('fit') is not False}


def clean_ducks(ducks):
    if ducks is None:
        return None
    result = []
    for item in ducks or []:
        start, end = _number(item.get('start'), None, 0.0), _number(item.get('end'), None, 0.0)
        if start is None or end is None or end - start < MIN_LINE:
            continue
        level = _number(item.get('level'), None, 0.0, 1.0)
        result.append({'start': start, 'end': end, 'level': level})
    result.sort(key=lambda item: item['start'])
    return result or None   # F179: elle tum araliklar silinince otomatik kismaya donulur


def signature(line, project):
    """Satirin sesini belirleyen alanlar: degisirse ses yeniden uretilmeli."""
    options = project.get('options') or {}
    parts = [line['text'], line.get('tag') or '', line.get('voice') or project.get('voice') or '',
             round(float(line.get('speed') or 1) * float(options.get('speed') or 1), 3), bool(line.get('fit', True)),
             bool(options.get('normalize')), bool(options.get('overlap'))]
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]


def create(video, source, label, lines, timing=None, voice='', options=None, voices=None, expressed=None):
    """Hazirlanmis satirlardan (dub.prepare + konusmaci sesleri) yeni proje; eski satir sesleri silinir.
    `voices`: her satirin ses anahtari (None: ana ses) -- dub.voice_plan."""
    voices = list(voices or [])
    items = []
    for index, line in enumerate(lines):
        items.append({'id': index + 1, 'start': round(line['start'], 3), 'end': round(line['end'], 3),
                      'text': line['text'], 'tag': line.get('tag') or '',
                      'voice': (voices[index] if index < len(voices) else None) or '',
                      'speaker': line.get('speaker'), 'at': None, 'gain': 1.0, 'speed': 1.0, 'fit': True})
    project = {'version': VERSION, 'video': str(video), 'source': source, 'label': label or '', 'timing': timing,
               'voice': voice or '', 'options': dub.options_of(options), 'lines': items, 'ducks': None,
               'next_id': len(items) + 1, 'expressed': expressed or {'tagged': 0, 'paused': 0}}
    with _LOCK:
        shutil.rmtree(folder(video) / LINES_DIR, ignore_errors=True)
        _write(video, project)
    return project


def save(video, incoming):
    """Arayuzun duzenledigi proje: satirlar, kisma araliklari, ana ses ve secenekler. Ses alanlari dosyadan korunur."""
    with _LOCK:
        project = load(video)
        if project is None:
            raise ValueError('Dublaj projesi bulunamadı; önce oluşturun.')
        known = {line['id']: line for line in project['lines']}
        next_id = int(project.get('next_id') or 1)
        lines, seen = [], set()
        for item in (incoming or {}).get('lines', project['lines']):
            ident = item.get('id')
            if not isinstance(ident, int) or ident in seen:
                ident = next_id
            next_id = max(next_id, ident + 1)
            line = clean_line(item, ident)
            if line is None:
                continue
            seen.add(ident)
            old = known.get(ident)
            if old:
                line.update({key: old[key] for key in AUDIO_KEYS if key in old})
            lines.append(line)
        lines.sort(key=lambda line: (line['start'], line['id']))
        project['lines'] = lines
        project['next_id'] = next_id
        if 'ducks' in (incoming or {}):
            project['ducks'] = clean_ducks(incoming['ducks'])
        if 'voice' in (incoming or {}):
            project['voice'] = str(incoming['voice'] or '')
        if 'options' in (incoming or {}):
            project['options'] = dub.options_of(dict(project['options'], **(incoming['options'] or {})))
        _write(video, project)
        _prune(video, project)
        return project


def _prune(video, project):
    """Projede kalmayan satir seslerini siler."""
    used = {line.get('audio') for line in project['lines'] if line.get('audio')}
    directory = folder(video) / LINES_DIR
    if not directory.is_dir():
        return
    for file in directory.glob('*.wav'):
        if file.name not in used:
            file.unlink(missing_ok=True)


def clip_path(video, line):
    return folder(video) / LINES_DIR / line['audio'] if line.get('audio') else None


def durations(video, project):
    return [float(line.get('duration') or 0) if clip_path(video, line) and clip_path(video, line).exists() else 0.0
            for line in project['lines']]


def placements(lines, lengths, overlap=False):
    """Seslerin calacagi zamanlar: elle tasinmis satir ('at') orada; digerleri kendi zamaninda ya da (ust uste
    binme kapaliyken) onceki ses bitmediyse onun bitisinde (dub.place)."""
    result, cursor = [], 0.0
    for line, length in zip(lines, lengths):
        if line.get('at') is not None:
            at = float(line['at'])
        elif overlap:
            at = float(line['start'])
        else:
            at = max(float(line['start']), cursor)
        result.append(round(at, 3))
        cursor = at + float(length)
    return result


def auto_ducks(project, placed, lengths):
    return [{'start': round(a, 3), 'end': round(b, 3), 'level': None}
            for a, b in dub.duck_spans(project['lines'], placed, lengths)]


def view(video, project, url_of=None):
    """Arayuz icin proje: satirlarda 'placed' (calacagi an), 'stale' (ses eski), 'url' (ses dosyasi);
    'auto_ducks' otomatik kisma araliklari."""
    lengths = durations(video, project)
    placed = placements(project['lines'], lengths, project['options'].get('overlap'))
    lines = []
    for line, length, at in zip(project['lines'], lengths, placed):
        item = dict(line, placed=at, duration=round(length, 3))
        path = clip_path(video, line)
        item['ready'] = bool(length)
        item['stale'] = bool(length) and line.get('sig') != signature(line, project)
        item['url'] = url_of(path) if url_of and length else ''
        lines.append(item)
    return dict(project, lines=lines, auto_ducks=auto_ducks(project, placed, lengths))


def pending(project, ids=None):
    """Uretilecek satir kimlikleri: verilenler ya da sesi olmayan/eski olanlar."""
    if ids:
        wanted = {int(item) for item in ids}
        return [line['id'] for line in project['lines'] if line['id'] in wanted]
    return [line['id'] for line in project['lines']
            if not line.get('audio') or line.get('sig') != signature(line, project)]


def _slots(lines):
    return dict(zip((line['id'] for line in lines), dub.slots(lines)))


def _store(video, ident, frames, rate, sig, tempo):
    """Uretilen sesi satira yazar (satir bu arada silindiyse atlanir); donen guncel satir ya da None."""
    with _LOCK:
        project = load(video)
        line = next((item for item in (project or {}).get('lines', []) if item['id'] == ident), None)
        if line is None:
            return None
        take = int(line.get('take') or 0) + 1
        name = f'{ident}-{take}.wav'
        target = folder(video) / LINES_DIR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(frames)
        old = clip_path(video, line)
        line.update(audio=name, duration=round(len(frames) / 2.0 / rate, 3), sig=sig, take=take, tempo=round(tempo, 3))
        _write(video, project)
        if old and old.name != name:
            old.unlink(missing_ok=True)
        return line


def generate(engines, video, ids=None, fresh=False, voice_spec=None, load_voice=None, progress=None, cancelled=None,
             on_line=None, log=None):
    """Satirlari seslendirir (bloklar). `ids` None: sesi olmayan ya da eski satirlar. `fresh`: ses motorunun
    onbellegine bakilmaz (ayni metin icin yeni deneme). `voice_spec(ref)` -> {'override', 'language', 'can_speed'}
    (ref '' ana ses); `load_voice(override, language)` motoru o sese hazirlar. `on_line(satir)` her satirda.
    Donen: {'done', 'faster'}."""
    log = log or (lambda _message: None)
    project = load(video)
    if project is None:
        raise ValueError('Dublaj projesi bulunamadı; önce oluşturun.')
    options = project['options']
    targets = pending(project, ids)
    if not targets:
        return {'done': 0, 'faster': 0}
    room = _slots(project['lines'])
    by_id = {line['id']: line for line in project['lines']}
    groups = {}
    for ident in targets:
        groups.setdefault(by_id[ident].get('voice') or project.get('voice') or '', []).append(ident)
    book = dub.cache_id(video)
    work = Path(tempfile.mkdtemp(prefix='aktar-dublaj-satir-'))
    done = faster = 0
    try:
        for ref, members in groups.items():
            spec = voice_spec(ref) if voice_spec else {'override': None, 'language': 'tr', 'can_speed': False}
            if load_voice:
                load_voice(spec['override'], spec['language'])
            for ident in members:
                if cancelled and cancelled():
                    raise GracefulStop('Dublaj durduruldu.')
                current = next((item for item in (load(video) or {}).get('lines', []) if item['id'] == ident), None)
                if current is None:   # bu arada silindi
                    continue
                line = current
                sig = signature(line, project)
                speed = round(float(options['speed']) * float(line.get('speed') or 1), 2)
                tag = {'tag': line['tag']} if line.get('tag') else {}
                result = engines.say(line['text'], speed, None if fresh else book, spec['language'], spec['override'],
                                     **tag)
                done += 1
                if progress:
                    progress(done, len(targets), 'voice')
                if not result.get('audio'):
                    log(f'Dublaj: {line["text"][:40]}… için ses üretilemedi.')
                    continue
                rate, channels, width, frames = dub._clip(base64.b64decode(result['audio']))
                if channels != 1 or width != 2:
                    raise RuntimeError('Ses motoru beklenmeyen biçimde ses döndürdü (16 bit mono değil).')
                tempo = 1.0
                need = dub._seconds(frames, rate) / room.get(ident, 1.0)
                if line.get('fit', True) and not options['overlap'] and need > 1.02 and options['max_tempo'] > 1:
                    tempo = min(options['max_tempo'], need)
                    if spec.get('can_speed'):
                        quick = engines.say(line['text'], round(speed * tempo, 2), None if fresh else book,
                                            spec['language'], spec['override'], **tag)
                        if quick.get('audio'):
                            rate, _channels, _width, frames = dub._clip(base64.b64decode(quick['audio']))
                    else:
                        frames = dub.atempo(frames, rate, tempo, work)
                    faster += 1
                if options['normalize']:
                    frames = dub.normalize(frames, rate)
                stored = _store(video, ident, frames, rate, sig, tempo)
                if stored is not None and on_line:
                    on_line(stored)
        return {'done': done, 'faster': faster}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _read(path):
    with wave.open(str(path)) as clip:
        return clip.getframerate(), clip.readframes(clip.getnframes())


def _gain(frames, gain):
    if abs(gain - 1) < 0.01:
        return frames
    samples = dub._samples(frames)
    return dub._pcm(array('h', [32767 if v > 32767 else -32768 if v < -32768 else v
                                for v in (int(value * gain) for value in samples)]))


def export(video, output, duration=0.0, has_audio=True, stems=None, progress=None, cancelled=None, log=None):
    """Projeyi videoya dublaj olarak yazar (bloklar): satir sesleri yerlerine, kisma araliklari (elle cizilmis ya da
    otomatik) ozgun sese. Sesi olmayan satirlar atlanir. Donen: {'output', 'lines', 'missing', 'stale', 'moved'}."""
    log = log or (lambda _message: None)
    project = load(video)
    if project is None:
        raise ValueError('Dublaj projesi bulunamadı; önce oluşturun.')
    options = project['options']
    lengths = durations(video, project)
    if not any(lengths):
        raise ValueError('Seslendirilmiş satır yok; önce satırları seslendirin.')
    placed = placements(project['lines'], lengths, options['overlap'])
    clips, rate = [], None
    work = Path(tempfile.mkdtemp(prefix='aktar-dublaj-'))
    try:
        for line, length in zip(project['lines'], lengths):
            if not length:
                clips.append(b'')
                continue
            if cancelled and cancelled():
                raise GracefulStop('Dublaj durduruldu.')
            clip_rate, frames = _read(clip_path(video, line))
            if rate is None:
                rate = clip_rate
            elif clip_rate != rate:
                frames = dub.resample(frames, clip_rate, rate, work)
            clips.append(_gain(frames, float(line.get('gain') or 1)))
        spans = None
        if has_audio and (options['duck'] or project.get('ducks') is not None):
            ducks = project['ducks'] if project.get('ducks') is not None else auto_ducks(project, placed, lengths)
            spans = [(item['start'], item['end'], item.get('level')) for item in ducks]
        missing = sum(1 for length in lengths if not length)
        stale = sum(1 for line, length in zip(project['lines'], lengths)
                    if length and line.get('sig') != signature(line, project))
        moved = sum(1 for line in project['lines'] if line.get('at') is not None)
        log(f'Dublaj (düzenleyici): {len(clips) - missing} satır, {moved} elle taşınmış, '
            f'{len(spans or [])} kısma aralığı; ses karıştırılıyor…')
        dub.render(video, work, placed, clips, rate, output, dict(options, duck=spans is not None), has_audio, spans,
                   stems, duration, progress, cancelled, log)
        return {'output': str(output), 'lines': len(clips) - missing, 'missing': missing, 'stale': stale,
                'moved': moved}
    finally:
        shutil.rmtree(work, ignore_errors=True)
