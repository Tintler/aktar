"""Sesli okuma onayarlari (F137): okuyucudan secilen, adli ve resimli ses kayitlari.

Bir onayar bir motor sesi ('<motor>/<ses>', orn. 'voxcpm/clone') ile o sesin seceneklerini
(motor.json "options": ses tarifi, klonlanacak kayit ve metni) tasir. Kayitlar APP_DIR/ses-presetleri/
altindadir: presets.json, resimler <kimlik>.png, klon kayitlari <kimlik>-kayit.<uzanti>. Klon kaydi
kopyalanir; kullanicinin dosyasi tasinsa ya da silinse de onayar calisir. F173: kaydin bir araligi secildiyse
('trim') yalnizca o parca kesilip <kimlik>-kayit.wav olarak yazilir (audio_trim).

Onayar secmek ui.json 'tts' tercihlerini (voices/options) gunceller; ses motoru (tts.Engines) ve
onbellek anahtarlari degismeden ayni tercihleri okur.
"""
from __future__ import annotations

import base64
import io
import json
import re
import secrets
import shutil
from pathlib import Path

FOLDER = 'ses-presetleri'
IMAGE_SIZE = 256
IMAGE_SOURCE_LIMIT = 15 * 1024 * 1024
IMAGE_TYPES = ('*.png', '*.jpg', '*.jpeg', '*.webp', '*.gif', '*.bmp')
AUDIO_TYPES = ('.wav', '.mp3', '.flac', '.ogg', '.m4a')
NAME_LIMIT = 60
TEXT_LIMIT = 2000


def folder(app_dir):
    return Path(app_dir) / FOLDER


def _index(app_dir):
    return folder(app_dir) / 'presets.json'


def _load(app_dir):
    try:
        data = json.loads(_index(app_dir).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [item for item in data if isinstance(item, dict) and item.get('id')] if isinstance(data, list) else []


def _save(app_dir, items):
    path = _index(app_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def _valid_id(ident):
    return bool(re.fullmatch(r'[0-9a-f]{12}', str(ident or '')))


def make_image(data):
    """Gorseli ortadan kare kirpip IMAGE_SIZE piksellik PNG'ye cevirir (ses resmi yuvarlak gosterilir)."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if len(data) > IMAGE_SOURCE_LIMIT:
        raise ValueError('Görsel çok büyük (en fazla 15 MB).')
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert('RGBA')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('Görsel okunamadı; PNG, JPG, WebP, GIF ya da BMP seçin.') from error
    image = ImageOps.fit(image, (IMAGE_SIZE, IMAGE_SIZE), Image.LANCZOS)
    output = io.BytesIO()
    image.save(output, 'PNG', optimize=True)
    return output.getvalue()


def data_url(png):
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')


def image_from_file(path):
    with open(path, 'rb') as stream:
        return data_url(make_image(stream.read(IMAGE_SOURCE_LIMIT + 1)))


def _image_bytes(value):
    match = re.fullmatch(r'data:image/[\w.+-]+;base64,([A-Za-z0-9+/=\s]+)', str(value or ''))
    if not match:
        raise ValueError('Görsel verisi geçersiz.')
    return make_image(base64.b64decode(match.group(1)))


def _public(app_dir, item):
    result = dict(item)
    path = folder(app_dir) / f'{item["id"]}.png'
    try:
        result['image'] = data_url(path.read_bytes()) if item.get('has_image') else ''
    except OSError:
        result['image'] = ''
    result.pop('has_image', None)
    return result


def list_presets(app_dir):
    return [_public(app_dir, item) for item in _load(app_dir)]


def get(app_dir, ident):
    return next((item for item in _load(app_dir) if item['id'] == ident), None)


def save(app_dir, values, voices):
    """values: {id?, name, voice, options, image?, trim?}. trim: {secenek: {start, end}} klon kaydinin kesilecek
    araligi (F173). voices: '<motor>/<ses>' -> motor.json ses kaydi.
    image: None dokunma, '' sil, data URL kaydet. Kaydedilen onayari (resmiyle) dondurur."""
    values = dict(values or {})
    name = ' '.join(str(values.get('name', '')).split())[:NAME_LIMIT]
    if not name:
        raise ValueError('Ses için bir ad yazın.')
    voice = str(values.get('voice', ''))
    spec = voices.get(voice)
    if spec is None:
        raise ValueError('Ses motoru ya da ses bulunamadı; Ayarlar → Sesli okuma bölümünden kurun.')
    items = _load(app_dir)
    ident = str(values.get('id') or '')
    existing = next((item for item in items if item['id'] == ident), None) if ident else None
    if ident and existing is None:
        raise ValueError('Ses kaydı bulunamadı.')
    if existing is None:
        ident = secrets.token_hex(6)
    base = folder(app_dir)
    base.mkdir(parents=True, exist_ok=True)
    options = {}
    given = values.get('options') or {}
    for option in spec.get('options', []):
        key = option['key']
        text = str(given.get(key, '') or '').strip()[:TEXT_LIMIT]
        if option.get('type') == 'file':
            cut = (values.get('trim') or {}).get(key)
            text = _trim_recording(base, ident, text, cut) if cut and text else _keep_recording(base, ident, text)
        if text:
            options[key] = text
    for option in spec.get('options', []):
        if option.get('type') == 'file' and not options.get(option['key']):
            raise ValueError(f'{option.get("label", "Ses kaydı")} seçin.')
    if existing is None or existing.get('voice') != voice:
        _drop_recordings(base, ident, keep=options.values())
    record = {'id': ident, 'name': name, 'voice': voice, 'options': options,
              'has_image': bool(existing and existing.get('has_image'))}
    image = values.get('image')
    if image is not None:
        target = base / f'{ident}.png'
        if image:
            png = _image_bytes(image)
            temp = target.with_suffix('.tmp')
            temp.write_bytes(png)
            temp.replace(target)
            record['has_image'] = True
        else:
            target.unlink(missing_ok=True)
            record['has_image'] = False
    if existing is None:
        items.append(record)
    else:
        items[items.index(existing)] = record
    _save(app_dir, items)
    return _public(app_dir, record)


def _keep_recording(base, ident, path):
    """Klon kaydini onayar klasorune kopyalar (zaten oradaysa dokunmaz); yeni yolu dondurur."""
    if not path:
        return ''
    source = Path(path)
    if source.parent.resolve() == base.resolve() and source.name.startswith(ident + '-kayit'):
        return str(source) if source.exists() else ''
    if not source.is_file():
        raise ValueError('Ses kaydı bulunamadı: ' + path)
    suffix = source.suffix.lower()
    if suffix not in AUDIO_TYPES:
        raise ValueError('Ses kaydı WAV, MP3, FLAC, OGG ya da M4A olmalı.')
    _drop_recordings(base, ident)
    target = base / f'{ident}-kayit{suffix}'
    shutil.copyfile(source, target)
    return str(target)


def _trim_recording(base, ident, path, cut):
    """F173: kaydin [start, end] araligini onayar klasorune <kimlik>-kayit.wav olarak keser; yeni yolu dondurur."""
    import audio_trim
    source = Path(path)
    if not source.is_file():
        raise ValueError('Ses kaydı bulunamadı: ' + path)
    if source.suffix.lower() not in AUDIO_TYPES:
        raise ValueError('Ses kaydı WAV, MP3, FLAC, OGG ya da M4A olmalı.')
    target = base / f'{ident}-kayit.wav'
    try:
        start, end = float(cut['start']), float(cut['end'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('Kesilecek aralık geçersiz.') from None
    audio_trim.cut(source, target, start, end)
    _drop_recordings(base, ident, keep=[str(target)])
    return str(target)


def _drop_recordings(base, ident, keep=()):
    keep = {str(Path(value)) for value in keep}
    for path in base.glob(f'{ident}-kayit.*'):
        if str(path) not in keep:
            path.unlink(missing_ok=True)


def remove(app_dir, ident):
    if not _valid_id(ident):
        raise ValueError('Ses kaydı bulunamadı.')
    items = _load(app_dir)
    remaining = [item for item in items if item['id'] != ident]
    if len(remaining) == len(items):
        raise ValueError('Ses kaydı bulunamadı.')
    base = folder(app_dir)
    (base / f'{ident}.png').unlink(missing_ok=True)
    _drop_recordings(base, ident)
    _save(app_dir, remaining)


def reorder(app_dir, ids):
    """F179: sesleri `ids` sirasina dizer (secicilerde bu sirayla gorunur); listede olmayanlar sonda kalir."""
    items = _load(app_dir)
    rank = {str(ident): index for index, ident in enumerate(ids or [])}
    items.sort(key=lambda item: rank.get(item['id'], len(rank)))   # sort kararli: bilinmeyenler eski sirasinda
    _save(app_dir, items)
