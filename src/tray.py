"""Sistem tepsisi ve oturum acilisinda baslatma (F233).

Tepsi: ui.json 'tray' aciksa pencere simge durumuna kucultulunce gizlenir ve saat yanindaki bildirim alaninda
simge olarak durur (tikla = ac, sag tik menusu Ac / Cikis). Pencere kapatilinca uygulama yine tamamen kapanir.
Baslangic: Windows'ta HKCU\\...\\Run degeri, Linux'ta ~/.config/autostart/aktar.desktop; komut '--tray' ile
calisir, Aktar pencere gostermeden tepside acilir. Yalnizca kullanici acarsa yazilir, kapatinca silinir.
"""
from __future__ import annotations

import os
import shlex
import sys
import threading
from pathlib import Path

from app_core import ROOT

NAME = 'Aktar'
TRAY_ARG = '--tray'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
FROZEN = bool(getattr(sys, 'frozen', False))


def icon_path():
    return ROOT / 'assets' / ('aktar.ico' if os.name == 'nt' else 'aktar-icon-256.png')


def available():
    try:
        import pystray  # noqa: F401
    except Exception:
        return False
    return True


def launch_command():
    """Aktar'i tepside baslatan komut (arguman listesi)."""
    if FROZEN:
        return [sys.executable, TRAY_ARG]
    python = Path(sys.executable)
    windowed = python.with_name('pythonw.exe')   # Windows'ta konsol penceresi acilmasin
    if os.name == 'nt' and windowed.is_file():
        python = windowed
    return [str(python), str(ROOT / 'desktop.py'), TRAY_ARG]


def _windows_command(args):
    return ' '.join(f'"{arg}"' for arg in args)


def _desktop_file():
    base = os.environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')
    return Path(base) / 'autostart' / 'aktar.desktop'


def autostart_enabled():
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _kind = winreg.QueryValueEx(key, NAME)
        except OSError:
            return False
        return bool(value)
    return _desktop_file().is_file()


def set_autostart(on):
    """Oturum acilisinda baslatmayi acar/kapatir; acarken komut her seferinde guncellenir (exe tasinmis olabilir)."""
    args = launch_command()
    if os.name == 'nt':
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if on:
                winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, _windows_command(args))
            else:
                try:
                    winreg.DeleteValue(key, NAME)
                except FileNotFoundError:
                    pass
        return
    path = _desktop_file()
    if not on:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[Desktop Entry]\nType=Application\nName=Aktar\n'
                    f'Exec={shlex.join(args)}\nIcon={ROOT / "assets" / "aktar-icon-256.png"}\n'
                    'X-GNOME-Autostart-enabled=true\n', encoding='utf-8')


class Tray:
    """Bildirim alanindaki simge; kendi is parcaciginda calisir, pencere kapaninca durdurulur."""

    def __init__(self, on_open, on_quit, log=None):
        self._on_open, self._on_quit, self._log = on_open, on_quit, log or (lambda _message: None)
        self._icon = None
        self._lock = threading.Lock()

    @property
    def running(self):
        return self._icon is not None

    def start(self):
        with self._lock:
            if self._icon is not None:
                return True
            try:
                import pystray
                from PIL import Image
                image = Image.open(icon_path())
                menu = pystray.Menu(pystray.MenuItem('Aktar\'ı aç', lambda: self._on_open(), default=True),
                                    pystray.MenuItem('Çıkış', lambda: self._on_quit()))
                icon = pystray.Icon('aktar', image, NAME, menu)
                icon.run_detached()
            except Exception as error:
                self._log(f'Tepsi simgesi açılamadı: {error}')
                return False
            self._icon = icon
            return True

    def stop(self):
        with self._lock:
            icon, self._icon = self._icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
