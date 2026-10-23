"""F189: sesli okuma surerken ekran kararmaz, bilgisayar uykuya girmez.

Web Audio ile calinan ses Windows'a "etkinlik" sayilmiyor (video oynatmanin aksine), bu yuzden
okuma surdukce istek acikca tutulur ve duraklatinca birakilir.
Windows: SetThreadExecutionState istegi, onu cagiran is parcacigi yasadikca gecerlidir; bu yuzden
istek kendi is parcacigindan tutulur. Linux: systemd-inhibit (KDE/GNOME logind kilitlerine uyar);
kilidi tutan `tail --pid` Aktar kapaninca ya da cokunce kendiliginden biter.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


class KeepAwake:
    def __init__(self):
        self._lock = threading.Lock()
        self._release = None    # Windows: istegi tutan is parcacigini birakan olay
        self._process = None    # Linux: systemd-inhibit sureci

    @property
    def active(self):
        return self._release is not None or self._process is not None

    def set(self, on):
        with self._lock:
            if bool(on) == self.active:
                return self.active
            if on:
                self._start()
            else:
                self._stop()
            return self.active

    def _start(self):
        if os.name == 'nt':
            release = threading.Event()
            threading.Thread(target=_hold_windows, args=(release,), daemon=True, name='keep-awake').start()
            self._release = release
            return
        inhibit, tail = shutil.which('systemd-inhibit'), shutil.which('tail')
        if not inhibit or not tail:
            return
        try:
            self._process = subprocess.Popen(
                [inhibit, '--what=idle:sleep', '--who=Aktar', '--why=Sesli okuma', '--mode=block',
                 tail, f'--pid={os.getpid()}', '-f', '/dev/null'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)   # durdururken tail de birlikte biter
        except OSError:
            self._process = None

    def _stop(self):
        if self._release is not None:
            self._release.set()
            self._release = None
        if self._process is not None:
            try:
                os.killpg(self._process.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                self._process.wait(2)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None


def _hold_windows(release):
    import ctypes
    state = ctypes.windll.kernel32.SetThreadExecutionState
    state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
    try:
        release.wait()
    finally:
        state(ES_CONTINUOUS)
