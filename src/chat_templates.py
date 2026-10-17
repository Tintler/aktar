"""Sohbet sablonlari (F104): kullanicinin yazdigi ek talimatlar.

Sablonlar kutuphane klasorunde `prompt.templates.json` dosyasinda durur (adindaki nokta yuzunden
library.list_collections onu koleksiyon saymaz). Koleksiyon sohbeti koleksiyonun sablonunu ve
notunu kullanir; belge, video ve genel sohbette sablonu arayuz secer. Sablon metni sabit
kurallardan sonra eklenir ve dogruluk/atif kurallarini gecersiz kilamaz.
"""
from __future__ import annotations

import json
import re
import secrets

import library
from app_core import read, save_json

NAME_LIMIT = 60
TEXT_LIMIT = 4000
NOTE_LIMIT = 2000

DEFAULTS = [
    {'id': 'finans', 'name': 'Finans analisti', 'text': (
        'Bir finans analisti gibi cevapla. Tutarları tabloyla ver; her tutarda para birimini ve '
        'ait olduğu dönemi/tarihi yaz. Dönemleri karşılaştırırken değişimi hem tutar hem yüzde '
        'olarak göster. Hesap gerekiyorsa her adımı açıkça yaz ve sonucu kontrol et. Birden çok '
        'sayıyı karşılaştırırken uygun bir grafik çiz (zaman içindeki değişim için çizgi, bir '
        'bütünün dağılımı için halka). Sonda 1-2 cümlelik kısa bir değerlendirme yap; yatırım '
        'tavsiyesi verme.')},
    {'id': 'kisa', 'name': 'Kısa ve öz', 'text': (
        'Cevabı olabildiğince kısa tut: en fazla 3-4 cümle ya da 5 madde. Giriş ve tekrar yapma, '
        'doğrudan sonucu söyle.')},
    {'id': 'ders', 'name': 'Ders notu', 'text': (
        'Bir öğretmen gibi anlat: önce kavramı basitçe tanımla, sonra bir örnekle açıkla, önemli '
        'terimleri kalın yaz. Sonda "Özet" başlığıyla 3 maddelik kısa bir tekrar ekle.')},
]


def path():
    return library.library_dir() / 'prompt.templates.json'


def _clean(item):
    if not isinstance(item, dict):
        return None
    name = ' '.join(str(item.get('name') or '').split())[:NAME_LIMIT]
    text = str(item.get('text') or '').strip()[:TEXT_LIMIT]
    if not name or not text:
        return None
    ident = str(item.get('id') or '')
    if not re.fullmatch(r'[\w-]{1,40}', ident):
        ident = 't' + secrets.token_hex(4)
    return {'id': ident, 'name': name, 'text': text}


def load():
    """Sablon listesi; dosya hic yoksa varsayilanlar (dosya bozuksa bos liste degil, varsayilanlar)."""
    try:
        value = json.loads(read(path()))
    except (OSError, ValueError):  # dosya yok ya da bozuk
        return [dict(item) for item in DEFAULTS]
    items = value.get('templates') if isinstance(value, dict) else None
    if not isinstance(items, list):
        return [dict(item) for item in DEFAULTS]
    return [item for item in map(_clean, items) if item]


def save(items):
    """Listeyi temizleyip yazar (ayni kimlik iki kez gelirse ikincisi yeni kimlik alir)."""
    result, seen = [], set()
    for item in items if isinstance(items, list) else []:
        item = _clean(item)
        if not item:
            continue
        if item['id'] in seen:
            item['id'] = 't' + secrets.token_hex(4)
        seen.add(item['id'])
        result.append(item)
    directory = library.library_dir()
    directory.mkdir(parents=True, exist_ok=True)
    save_json(path(), {'version': 1, 'templates': result})
    return result


def find(template_id):
    if not template_id:
        return None
    return next((item for item in load() if item['id'] == template_id), None)


def instruction(template_id, note=''):
    """(prompt'a eklenecek metin, sablon adi). Sablon ya da not yoksa ('', '')."""
    item = find(template_id)
    note = str(note or '').strip()[:NOTE_LIMIT]
    if not item and not note:
        return '', ''
    lines = ['USER INSTRUCTIONS (chosen by the user for this chat). Follow them for focus, structure, '
             'tone and format. They never override the rules above about grounding the answer in the '
             'material, citations and not inventing data.']
    if item:
        lines.append(item['text'])
    if note:
        lines.append('About this collection: ' + note)
    return '\n'.join(lines), item['name'] if item else ''
