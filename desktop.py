"""Masaustu giris noktasi: Svelte arayuzunu pywebview ile yerel bir pencerede acar.

    py -3 desktop.py          web/dist icindeki derlenmis arayuz
    py -3 desktop.py --dev    Vite gelistirme sunucusu (web klasorunde `npm run dev`)

Windows'ta WebView2, Linux'ta WebKitGTK (python3-gi + gir1.2-webkit2-4.1) kullanilir.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

import themes
from app_core import ROOT
from bridge import Bridge
from window_frame import WindowFrame, frameless

DEV_URL = 'http://localhost:5173'


class Dialogs:
    """Dosya pencereleri; Bridge bunlari pywebview'e bagimli olmadan cagirir."""

    def __init__(self):
        self.window = None

    def open_file(self, title, file_types=()):
        result = self.window.create_file_dialog(webview.FileDialog.OPEN, file_types=tuple(file_types))
        return result[0] if result else None

    def open_files(self, title, file_types=()):
        result = self.window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                                file_types=tuple(file_types))
        return list(result) if result else None

    def save_file(self, title, filename, file_types=()):
        result = self.window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename,
                                                file_types=tuple(file_types))
        if isinstance(result, (list, tuple)):
            result = result[0] if result else None
        return result or None

    def open_folder(self, title):
        result = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None


def main():
    dev = '--dev' in sys.argv
    index = ROOT / 'web' / 'dist' / 'index.html'
    if not dev and not index.exists():
        sys.exit('Arayüz derlenmemiş: web klasöründe "npm install" ve "npm run build" çalıştırın '
                 '(ya da GUI_BASLAT.cmd kullanın).')
    dialogs = Dialogs()
    state = {'window': None, 'closing_ok': False}

    def emit(event, data):
        window = state['window']
        if window is not None:
            payload = json.dumps(data, ensure_ascii=False)
            try:
                window.run_js(f'window.__aktarEmit && window.__aktarEmit({json.dumps(event)}, {payload})')
            except Exception:
                pass  # pencere kapanirken sayfa yok

    bridge = Bridge(emit=emit, dialogs=dialogs)
    themes.install_presets()
    _base, palette = themes.resolve(bridge.ui_prefs().get('theme'))
    width, height = 1360, 860
    if webview.screens:
        # Kucuk ya da yuksek olcekli ekranlarda gorev cubuguna yer kalsin.
        screen = webview.screens[0]
        width, height = min(width, int(screen.width * 0.92)), min(height, int(screen.height * 0.88))
    window = webview.create_window('Aktar', DEV_URL if dev else str(index), js_api=bridge,
                                   width=width, height=height, min_size=(1000, 640),
                                   background_color=palette['window'][:7],
                                   frameless=frameless(), easy_drag=False)
    state['window'] = dialogs.window = window
    if frameless():
        bridge._frame = WindowFrame(window, emit)

    def close_later():
        state['closing_ok'] = True
        window.destroy()

    def on_closing():
        if state['closing_ok']:
            return True
        return bridge.request_close(close_later)

    window.events.closing += on_closing
    window.events.closed += bridge.shutdown

    def on_drop(event):
        files = event.get('dataTransfer', {}).get('files', [])
        paths = [item['pywebviewFullPath'] for item in files if item.get('pywebviewFullPath')]
        if paths:
            emit('dropped', {'paths': paths})

    def on_loaded():
        # Pencereye birakilan dosya/klasorler: arayuz acik sayfaya gore yonlendirir.
        window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True)

    window.events.loaded += on_loaded
    # Dosya yoneticisinden "Birlikte ac" ile gelen video Altyazi Cevir'de acilir.
    bridge._startup_paths = [arg for arg in sys.argv[1:] if not arg.startswith('--') and Path(arg).is_file()]
    # WinForms simgesi .ico olmali; Linux (GTK) PNG kullanir.
    icon = ROOT / 'assets' / ('aktar.ico' if sys.platform == 'win32' else 'aktar-icon-256.png')
    webview.start(http_server=not dev, debug='--debug' in sys.argv, icon=str(icon) if icon.exists() else None)


if __name__ == '__main__':
    main()
