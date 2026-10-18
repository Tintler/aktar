"""Web arayuzunun (Svelte) arka ucu: pywebview `window.pywebview.api` olarak sayfaya verir.

Her public metot JavaScript'ten cagrilabilir ve JSON'a cevrilebilir deger dondurur;
kullaniciya gosterilecek hatalar istisna yerine {'error': mesaj} olarak doner. Arka
plandaki isler (gunluk, ilerleme, onay istekleri) enjekte edilen `emit` ile sayfaya itilir.

Is mantigi app_core / library / qa modullerinde kalir; burada yalnizca arayuz akisi var.
Bolumler: bu dosyada genel (ayarlar, tema, pencere), bridge_translate.py'de Altyazi Cevir,
bridge_library.py'de Kutuphane (bridge_mail.py'de e-postadan iceri aktarma), bridge_player.py'de oynatici ve videoya soru sor,
bridge_document.py'de belge goruntuleyici, bridge_assistant.py'de genel sohbet ve tekil dosyalar,
bridge_subscriptions.py'de abonelik takibi, bridge_book.py'de Kitap Cevir, bridge_reader.py'de Okuma (EPUB kitapligi), bridge_tts.py'de sesli okuma, bridge_pdf.py'de PDF'den kitap, bridge_voice.py'de sesle soru sorma, bridge_watch.py'de
klasor izleme, bridge_subtitles.py'de altyazi araclari (zamanlama, disa aktarma, OCR) ve klip.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import documents
import languages
import llm_provider
import media_server
import setup_check
from version import VERSION
import themes
from app_core import (APP_DIR, DEFAULT_CONFIG, WINDOWS, Client, keep_loaded, load_config, qa_config, read, save_json,
                      unload_models, validate_config)
from bridge_assistant import AssistantMixin, FilesMixin
from bridge_book import BookMixin
from bridge_reader import ReaderMixin
from bridge_tts import TtsMixin
from bridge_pdf import PdfMixin
from bridge_document import DocumentMixin
from bridge_library import LibraryMixin
from bridge_mail import MailMixin
from bridge_native import NativePlayerMixin
from bridge_player import PlayerMixin
from bridge_subscriptions import SubscriptionsMixin
from bridge_subtitles import SubtitleToolsMixin
from bridge_translate import TranslateMixin
from bridge_voice import VoiceMixin
from bridge_watch import WatchMixin

UI_FILE = 'ui.json'
WHISPER_MODELS = ('large-v3-turbo', 'large-v3', 'medium', 'small', 'base')
CUDA_MARKERS = (('cublas64_12.dll', 'cudnn64_9.dll') if os.name == 'nt'
                else ('libcublas.so.12', 'libcudnn.so.9'))
OCR_ENGINES = [('auto', 'Otomatik (Tesseract > OCR modeli > görü modeli)'),
               ('tesseract', 'Tesseract (yerel)'),
               ('model', 'OCR modeli (LM Studio)'),
               ('vision', 'Görü modeli')]
# Ceviri surerken degistirilemeyen ayarlar (calisan isin modeli/baglantisi).
LOCKED_WHILE_RUNNING = ('base_url', 'provider', 'model', 'batch_cues', 'max_tokens', 'temperature', 'timeout_seconds',
                        'auto_retry_count', 'glossary_strict', 'analysis_chunk_chars', 'disable_thinking',
                        'source_language', 'target_language')


def _error(error):
    return {'error': str(error)}


class Bridge(TranslateMixin, BookMixin, ReaderMixin, TtsMixin, PdfMixin, LibraryMixin, MailMixin, PlayerMixin, DocumentMixin, AssistantMixin, FilesMixin,
             SubscriptionsMixin, VoiceMixin, WatchMixin, SubtitleToolsMixin, NativePlayerMixin):
    def __init__(self, emit=None, dialogs=None):
        self._emit = emit or (lambda _event, _data: None)
        self._dialogs = dialogs          # desktop.Dialogs: open_file(), open_folder() ...
        # window_frame.WindowFrame; desktop.py atar. Ozel (alt cizgili): pywebview public
        # nitelikleri sayfaya verir ve iclerinde gezinir.
        self._frame = None
        self._lock = threading.RLock()
        self._models = {'state': 'probing', 'names': [], 'message': '', 'model': ''}
        self._startup_paths = []
        self._init_translate()
        self._init_book()
        self._init_library()
        self._init_mail()
        self._init_player()
        self._init_document()
        self._init_assistant()
        self._init_subtools()
        self._init_native()

    # ------------------------------------------------------------------ yardimcilar
    def _log(self, message):
        stamp = datetime.now().strftime('%H:%M:%S')
        for line in str(message).splitlines() or ['']:
            self._emit('log', {'line': f'[{stamp}] {line}'})

    def _dialog(self, name, *args):
        if self._dialogs is None:
            return None
        return getattr(self._dialogs, name)(*args)

    # ------------------------------------------------------------------ acilis
    def _video_encoders(self):
        """Ayarlar sayfasi icin GPU kodlayicilari; 'works' None ise deneme suruyor (sayfa beklemez)."""
        status = media_server.hw_status()
        if any(value is None for value in status.values()):
            media_server.detect_async(lambda: self._emit('video_encoders', self._video_encoders()))
        return [{'id': name, 'label': media_server.HW_ENCODERS[name][0], 'works': status[name]}
                for name in media_server.HW_ORDER]

    def startup(self):
        """Sayfa ilk acildiginda: arayuz tercihleri, temalar, durum ve komut satiri dosyasi."""
        themes.install_presets()
        media_server.detect_async()   # F120: GPU kodlayicilari arka planda bir kez denenir
        paths, self._startup_paths = self._startup_paths, []
        self._start_watch()  # F114: izlenen koleksiyonlar arka planda taranir
        return {'prefs': self.ui_prefs(), 'themes': themes.list_themes(),
                'translate': self.translate_state(), 'books': self.book_snapshot(),
                'library': self.library_open(), 'models': self._models,
                'platform': 'windows' if WINDOWS else sys.platform, 'open': paths, 'version': VERSION}

    def ui_prefs(self):
        path = APP_DIR / UI_FILE
        try:
            value = json.loads(read(path)) if path.exists() else {}
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def save_ui_prefs(self, values):
        prefs = self.ui_prefs()
        prefs.update(values or {})
        try:
            save_json(APP_DIR / UI_FILE, prefs)
        except OSError as error:
            return _error(error)
        return prefs

    # ------------------------------------------------------------------ LM Studio modelleri (F142)
    def _keep_chat_models(self):
        """Soru oncesi: sohbet (soru-cevap) ve embedding modelleri LM Studio'da acikca yuklenir; boylece her
        soruda biri bosaltilip digeri yeniden yuklenmez. Is parcaciginda cagrilir (yukleme surebilir)."""
        try:
            cfg = load_config()
            names = [qa_config(cfg)['model'], cfg.get('embedding_model', '')]
            loaded = keep_loaded(Client(cfg, self._log), names, self._log)
        except (RuntimeError, ValueError, OSError) as error:
            self._log(f'LM Studio modelleri hazırlanamadı: {error}')
            return
        with self._lock:
            self._kept_models = list(dict.fromkeys(getattr(self, '_kept_models', []) + loaded))

    def _release_models(self):
        """Kapanirken: yalnizca uygulamanin acikca yukledigi modeller bosaltilir (LM Studio bellegi bosalsin)."""
        kept, self._kept_models = getattr(self, '_kept_models', []), []
        if not kept:
            return
        try:
            cfg = dict(load_config(), timeout_seconds=5)
            unload_models(Client(cfg, self._log), kept)
        except (RuntimeError, ValueError, OSError):
            pass

    # ------------------------------------------------------------------ temalar
    def list_themes(self):
        themes.install_presets()
        return themes.list_themes()

    def open_themes_folder(self):
        folder = themes.themes_dir()
        folder.mkdir(parents=True, exist_ok=True)
        return self.reveal(str(folder))

    # ------------------------------------------------------------------ dosya sistemi
    def reveal(self, path):
        """Klasoru ya da dosyanin bulundugu klasoru dosya yoneticisinde acar."""
        path = Path(str(path))
        if not path.exists():
            return {'error': 'Bulunamadı: ' + str(path)}
        try:
            if WINDOWS:
                if path.is_file():
                    subprocess.Popen(['explorer', '/select,', str(path)])
                else:
                    os.startfile(str(path))  # noqa: S606 - kullanicinin kendi klasoru
            else:
                subprocess.Popen(['xdg-open', str(path if path.is_dir() else path.parent)])
        except OSError as error:
            return _error(error)
        return True

    def choose_file(self, title='Dosya seç', file_types=()):
        return self._dialog('open_file', title, tuple(file_types or ()))

    def choose_folder(self, title='Klasör seç'):
        return self._dialog('open_folder', title)

    # ------------------------------------------------------------------ LM Studio
    def refresh_models(self):
        """Yuklu modelleri arka planda sorgular; sonuc 'models' olayiyla gelir."""
        try:
            cfg = dict(load_config())
        except (OSError, ValueError) as error:
            self._models = {'state': 'failed', 'names': [], 'message': str(error), 'model': ''}
            self._emit('models', self._models)
            return False
        cfg['timeout_seconds'] = min(8, int(cfg['timeout_seconds']))
        self._models = dict(self._models, state='probing', model=cfg['model'])
        self._emit('models', self._models)

        def probe():
            try:
                names = Client(cfg, lambda _message: None).models()
            except (RuntimeError, ValueError) as error:
                self._models = {'state': 'failed', 'names': [], 'message': str(error), 'model': cfg['model']}
            else:
                self._models = {'state': 'ok', 'names': list(names), 'message': '', 'model': cfg['model']}
            self._emit('models', self._models)

        threading.Thread(target=probe, name='aktar-model-probe', daemon=True).start()
        return True

    # ------------------------------------------------------------------ ayarlar
    def get_settings(self):
        value = dict(DEFAULT_CONFIG)
        try:
            value.update(json.loads(read(APP_DIR / 'config.json')))
        except (OSError, ValueError):
            pass  # gecersiz config.json bu sayfadan duzeltilebilsin
        value['book'], book_defaults = self._book_settings(value.get('book'))
        return {'config': value, 'defaults': dict(DEFAULT_CONFIG), 'book_defaults': book_defaults,
                'book_locked': self._book_locked(),
                'locked': list(LOCKED_WHILE_RUNNING) if self._running() or self._book_running() else [],
                'whisper_models': list(dict.fromkeys(WHISPER_MODELS + (str(value.get('whisper_model', '')),))),
                'ocr_engines': [{'id': key, 'label': label} for key, label in OCR_ENGINES],
                'cuda_markers': list(CUDA_MARKERS),
                'video_encoders': self._video_encoders(), 'mpv': self._native is not None,
                'languages': languages.choices(),
                'llm': {'presets': list(llm_provider.PRESETS), 'api_key_set': bool(llm_provider.api_key())}}

    def setup_check(self):
        """Ilk acilis bilesen denetimi (F154): [{'id', 'label', 'required', 'state', 'detail', 'hint', ...}]."""
        try:
            engines = self._engines().engines()
        except Exception:  # motor listesi okunamadi: ses motoru 'yok' gorunur
            engines = []
        return setup_check.run(engines, self._native is not None)

    def llm_scope(self, url):
        """Sunucu adresi nerede: 'local' | 'lan' | 'internet' (Ayarlar'daki gizlilik uyarisi, F152)."""
        return {'scope': llm_provider.scope(url)}

    def llm_set_api_key(self, value):
        """Model sunucusu API anahtarini isletim sistemi deposuna yazar; bos deger siler."""
        try:
            llm_provider.set_api_key(value)
        except Exception as error:  # depo yok (Linux'ta secret-tool) ya da yazilamadi
            return {'error': 'API anahtarı kaydedilemedi: ' + str(error)}
        self.refresh_models()
        return {'api_key_set': bool(llm_provider.api_key())}

    def save_settings(self, values):
        try:
            value = dict(DEFAULT_CONFIG)
            try:
                value.update(json.loads(read(APP_DIR / 'config.json')))
            except (OSError, ValueError):
                pass
            current = dict(value)
            incoming = {key: item for key, item in dict(values or {}).items() if key in DEFAULT_CONFIG}
            if self._running() or self._book_running():
                for key in LOCKED_WHILE_RUNNING:
                    incoming.pop(key, None)
            value.update(incoming)
            for key, default in DEFAULT_CONFIG.items():
                # Sayfadaki sayi alanlari bos birakilirsa varsayilana doner.
                if isinstance(default, (int, float)) and not isinstance(default, bool):
                    try:
                        value[key] = type(default)(value[key])
                    except (TypeError, ValueError):
                        value[key] = default
                elif isinstance(default, str):
                    value[key] = str(value.get(key, '')).strip()
            validate_config(value)
            self._book_merge_settings(value, dict(values or {}).get('book'))
            save_json(APP_DIR / 'config.json', value)
        except (RuntimeError, ValueError, OSError) as error:
            return {'error': 'Ayarlar kaydedilemedi: ' + str(error)}
        self._log('Ayarlar kaydedildi.')
        if any(current.get(key) != value.get(key) for key in ('base_url', 'provider', 'model')):
            self.refresh_models()
        return {'config': value}

    def check_tesseract(self, path):
        found = documents.tesseract_path({'tesseract_path': str(path or '').strip()})
        return {'found': found or ''}

    def check_cuda_dir(self, path):
        text = str(path or '').strip()
        if not text:
            return {'message': ''}
        folder = Path(text)
        if not folder.is_dir():
            return {'message': 'Klasör bulunamadı.', 'ok': False}
        missing = [name for name in CUDA_MARKERS if not (folder / name).is_file()]
        if missing:
            return {'message': 'Eksik: ' + ', '.join(missing), 'ok': False}
        return {'message': 'cuBLAS 12 ve cuDNN 9 bulundu.', 'ok': True}

    # ------------------------------------------------------------------ pencere
    def window_state(self):
        return self._frame.state() if self._frame else {'custom': False, 'maximized': False}

    def window_fullscreen(self, on):
        """Video tam ekrani (F126): HTML ogesi tam ekrana gecince pencere de ekrani kaplar."""
        if getattr(self, '_native', None) is not None:
            self._native.watch_cursor(bool(on))   # mpv videosu fare hareketini iletmeyebilir
        if self._frame is not None:
            self._frame.set_fullscreen(bool(on))
        else:
            window = getattr(self._dialogs, 'window', None)
            if window is not None and bool(getattr(window.native, 'is_fullscreen', False)) != bool(on):
                window.toggle_fullscreen()
        return True

    def window_command(self, name, edge=None):
        """Kendi baslik cubugunun dugmeleri, pencereyi tasima ve boyutlandirma."""
        if self._frame is None:
            return False
        if name == 'resize':
            self._frame.resize(edge)
        elif name in ('minimize', 'toggle_maximize', 'close', 'drag'):
            getattr(self._frame, name)()
        else:
            return False
        return True

    def request_close(self, close):
        """Pencere kapanirken cagrilir. Hemen kapanabiliyorsa True."""
        reasons = (['Çeviri sürüyor.'] if self._running() else []) + (
            ['Kitap çevirisi sürüyor.'] if self._book_running() else []) + (
            ['PDF okunuyor.'] if self._pdf_running() else []) + (
            ['Toplu hazırlık sürüyor.'] if self._queue_running() else []) + (
            ['Altyazı/klip işi sürüyor.'] if self._tool_running() else [])
        if not reasons:
            return True
        self._pending_close = close
        self._emit('confirm_close', {'reason': ' '.join(reasons)})
        return False

    def confirm_close(self):
        """Arayuz kapatmayi onayladi: calisan isler durdurulur, pencere kapanir."""
        close = getattr(self, '_pending_close', None)
        self._pending_close = None
        self._stop_translation_for_close()
        self._stop_book_for_close()
        self._stop_tts_for_close()
        self._stop_pdf_for_close()
        self._stop_library_for_close()
        self._stop_document_for_close()
        self._stop_player_for_close()
        self._stop_subtools_for_close()
        self._stop_native_for_close()
        self._stop_assistant_for_close()
        self._stop_watch_for_close()
        self._release_models()
        if close:
            threading.Timer(0.1, close).start()
        return True

    def shutdown(self):
        """Pencere kapandi: arka plandaki isleri birak."""
        self._stop_translation_for_close()
        self._stop_book_for_close()
        self._stop_tts_for_close()
        self._stop_pdf_for_close()
        self._stop_library_for_close()
        self._stop_document_for_close()
        self._stop_player_for_close()
        self._stop_subtools_for_close()
        self._stop_native_for_close()
        self._stop_assistant_for_close()
        self._stop_watch_for_close()
        self._release_models()
