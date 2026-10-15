"""Sesle soru (F112): pywebview penceresinde mikrofon iznini uygulamanin kendi sayfasina verir.

pywebview izin isteklerini ele almaz: WebView2 (Windows) her acilista kendi izin kutusunu
gosterir (sayfa her seferinde rastgele portlu yerel sunucudan gelir), WebKitGTK (Linux)
ise ele alinmayan istegi reddeder. Burada yalnizca yerel adresten (127.0.0.1/localhost)
gelen MIKROFON istegine izin verilir; kamera, konum vb. varsayilan davranista kalir.
Kayit yerelde Whisper'a gider (bridge_voice.py); ses hicbir yere gonderilmez.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1')


def is_app_origin(uri):
    """Izin isteyen sayfa uygulamanin yerel sayfasi mi (pywebview sunucusu ya da Vite)?"""
    try:
        parts = urlsplit(str(uri or ''))
    except ValueError:
        return False
    return parts.scheme in ('http', 'https') and (parts.hostname or '') in LOCAL_HOSTS


def allow_microphone(window, log=None):
    """Pencere yuklendikten sonra bir kez cagrilir; basarisizlik yalnizca gunluge yazilir
    (o durumda tarayici motorunun varsayilan izin davranisi gecerli kalir)."""
    if getattr(window, '_aktar_mic', False):
        return
    backend = 'WebView2' if os.name == 'nt' else 'WebKitGTK'
    try:
        (_allow_webview2 if os.name == 'nt' else _allow_webkit)(window)
        window._aktar_mic = True
    except Exception as error:  # platform/pywebview surumu farkli olabilir
        if log:
            log(f'Mikrofon izni ayarlanamadı ({backend}): {error}')


def _allow_webview2(window):
    from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind, CoreWebView2PermissionState
    from System import Func, Type

    form = window.native

    def on_request(_sender, args):
        if args.PermissionKind == CoreWebView2PermissionKind.Microphone and is_app_origin(args.Uri):
            args.State = CoreWebView2PermissionState.Allow

    def attach():
        form.webview.CoreWebView2.PermissionRequested += on_request

    form._aktar_mic_handler = on_request   # temsilci cop toplayiciya gitmesin
    form.Invoke(Func[Type](attach))


def _allow_webkit(window):
    from gi.repository import GLib, WebKit2
    from webview.platforms.gtk import BrowserView

    view = BrowserView.instances[window.uid].webview

    def on_request(webview, request):
        if not isinstance(request, WebKit2.UserMediaPermissionRequest):
            return False
        audio_only = request.get_property('is-for-audio-device') and not request.get_property('is-for-video-device')
        if audio_only and is_app_origin(webview.get_uri()):
            request.allow()
            return True
        return False

    def attach():
        view.connect('permission-request', on_request)
        return False

    GLib.idle_add(attach)
