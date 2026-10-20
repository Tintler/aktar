"""Ilk acilis bilesen denetimi (F154): eksik bilesenleri ve nasil kurulacaklarini listeler.

Her oge: {'id', 'label', 'required', 'state': 'ok'|'warn'|'missing', 'detail', 'hint', 'settings', 'url'}.
'required' ogeler uygulamanin temel isleri (ceviri, sohbet, video) icin gerekir; digerleri yalnizca ilgili
ozellik kullanilinca. Denetim hizlidir: model sunucusu kisa zaman asimiyla sorgulanir, baska bir sey
indirilmez ya da kurulmaz.
"""
from __future__ import annotations

import os

import documents
import ebook_convert
import llm_provider
import media
import speech
from app_core import Client, load_config

WINDOWS = os.name == 'nt'


def _item(item_id, label, required, state, detail, hint='', settings=None, url=None):
    return {'id': item_id, 'label': label, 'required': required, 'state': state, 'detail': detail,
            'hint': hint, 'settings': settings, 'url': url}


def model_server(cfg):
    """(oge, sunucudaki model adlari ya da None)."""
    base = cfg.get('base_url', '')
    where = {'local': 'bu bilgisayarda', 'lan': 'yerel ağda', 'internet': 'internette'}[llm_provider.scope(base)]
    probe = dict(cfg, timeout_seconds=4)
    try:
        names = Client(probe, lambda _message: None).models()
    except (RuntimeError, ValueError) as error:
        return None, _item('model_server', 'Model sunucusu', True, 'missing', f'{base} yanıt vermiyor ({error}).',
                     'LM Studio, Ollama ya da llama.cpp sunucusunu başlatın; adresi ve türü Ayarlar → Modeller\'den '
                     'seçin. OpenAI uyumlu bir internet sunucusu da (API anahtarıyla) kullanılabilir.',
                     'models', 'https://lmstudio.ai')
    if not names:
        return names, _item('model_server', 'Model sunucusu', True, 'warn', f'{base} açık ama hiç model sunmuyor.',
                     'Sunucuda bir sohbet modeli yükleyin ya da indirin.', 'models')
    if cfg.get('model') not in names:
        return names, _item('model_server', 'Model sunucusu', True, 'warn',
                     f'Sunucu {where} ({len(names)} model), ama seçili model ({cfg.get("model")}) listede yok.',
                     'Ayarlar → Modeller\'den sunucudaki modellerden birini seçin.', 'models')
    return names, _item('model_server', 'Model sunucusu', True, 'ok', f'{cfg.get("model")} · {where} ({len(names)} model)',
                 settings='models')


def ffmpeg():
    found = media.ffmpeg_path(), media.ffprobe_path()
    if all(found):
        return _item('ffmpeg', 'FFmpeg', True, 'ok', 'ffmpeg ve ffprobe bulundu.')
    missing = ' ve '.join(name for name, path in zip(('ffmpeg', 'ffprobe'), found) if not path)
    hint = ("Windows: FFmpeg'i indirip ffmpeg.exe ile ffprobe.exe'yi uygulamanın bin\\ klasörüne koyun."
            if WINDOWS else 'Linux: sudo apt install ffmpeg (ya da dağıtımınızın paket yöneticisi).')
    return _item('ffmpeg', 'FFmpeg', True, 'missing', f'{missing} bulunamadı: video açma, altyazı çıkarma ve '
                 'dublaj çalışmaz.', hint, url='https://ffmpeg.org/download.html')


def embedding(cfg, names):
    model = str(cfg.get('embedding_model') or '').strip()
    if not model:
        return _item('embedding', 'Kütüphane indeksi (embedding)', False, 'warn', 'Embedding modeli seçilmedi; '
                     'koleksiyonlarda anlam araması kapalı, yalnızca kelime araması var.',
                     'Sunucuda bir embedding modeli (ör. EmbeddingGemma) yükleyip Ayarlar → Kütüphane\'den seçin.', 'library')
    if names is not None and model not in names:
        return _item('embedding', 'Kütüphane indeksi (embedding)', False, 'warn', f'{model} sunucuda listelenmiyor.',
                     'Modeli sunucuda yükleyin ya da başka bir embedding modeli seçin.', 'library')
    return _item('embedding', 'Kütüphane indeksi (embedding)', False, 'ok', model, settings='library')


def whisper():
    ok, message = speech.available()
    if ok:
        return _item('whisper', 'Konuşmadan metin (Whisper)', False, 'ok', 'Kurulu; model ilk kullanımda iner.',
                     settings='voice')
    return _item('whisper', 'Konuşmadan metin (Whisper)', False, 'missing',
                 'Altyazısız videolar, sesli soru ve konuşmacı ayrımı kullanılamaz.', message, 'voice')


def tts(engines):
    usable = [item['name'] for item in engines if item.get('mode') and not item.get('server')]   # F158: Drama 3 ayri sunucu ister
    if usable:
        return _item('tts', 'Sesli okuma motoru', False, 'ok', ', '.join(usable), settings='voice')
    return _item('tts', 'Sesli okuma motoru', False, 'missing', 'Sesli okuma, sesli kitap ve dublaj kullanılamaz.',
                 'Ayarlar → Ses → Sesli okuma bölümünden bir motor kurun.', 'voice')


def tesseract(cfg):
    path = documents.tesseract_path(cfg)
    if path:
        return _item('tesseract', 'Tesseract OCR', False, 'ok', str(path), settings='library')
    hint = ('Windows: UB Mannheim Tesseract kurulumunu dil paketleriyle kurun ya da yolunu Ayarlar\'da gösterin.'
            if WINDOWS else 'Linux: sudo apt install tesseract-ocr tesseract-ocr-tur')
    return _item('tesseract', 'Tesseract OCR', False, 'missing', 'Taranmış PDF\'ler yalnızca görü modeliyle okunabilir.',
                 hint, 'library', 'https://github.com/UB-Mannheim/tesseract/wiki' if WINDOWS else None)


def mpv(available):
    if available:
        return _item('mpv', 'Gömülü oynatıcı (libmpv)', False, 'ok', 'MKV, HEVC, AC3/DTS dönüştürmeden oynatılır.',
                     settings='video')
    hint = ("libmpv-2.dll'i uygulamanın bin\\ klasörüne koyun (bin/README.txt)." if WINDOWS
            else 'Linux: sudo apt install libmpv2')
    return _item('mpv', 'Gömülü oynatıcı (libmpv)', False, 'warn', 'Yok: videolar WebView ve FFmpeg dönüştürmesiyle '
                 'oynatılır (daha yavaş başlar).', hint, 'video')


def calibre():
    path = ebook_convert.calibre_converter()
    if path:
        return _item('calibre', 'Calibre (MOBI/AZW3)', False, 'ok', path)
    return _item('calibre', 'Calibre (MOBI/AZW3)', False, 'warn', 'Yok: MOBI/AZW3 yerleşik okuyucuyla açılır '
                 '(biçimlendirme yaklaşık).', 'En iyi sonuç için Calibre\'yi kurun; Aktar ebook-convert\'i kendisi bulur.',
                 url='https://calibre-ebook.com/download')


def run(engines=(), mpv_available=False):
    try:
        cfg = load_config()
    except (OSError, ValueError) as error:
        return [_item('config', 'Ayarlar (config.json)', True, 'missing', str(error),
                      'Ayarlar sayfasından geçerli değerleri kaydedin.', 'models')]
    names, server = model_server(cfg)
    return [server, ffmpeg(), embedding(cfg, names), whisper(), tts(list(engines)), tesseract(cfg),
            mpv(mpv_available), calibre()]
