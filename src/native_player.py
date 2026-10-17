"""Gomulu mpv oynatici (deneme, F122): video WebView yerine libmpv ile oynatilir.

Neden: WebView'in <video> ogesi yalnizca birkac kodu cozer; HEVC/10 bit/MKV/AC3 icin ffmpeg ile anlik
donusturme + Media Source zinciri gerekiyordu ve takiliyordu. mpv her bicimi dogrudan, donanim
cozmeyle (d3d11va/nvdec) oynatir ve yerel dosya gibi aninda sarar.

Nasil: Pencereye (WinForms) yerel bir Panel eklenir; mpv o panelin penceresine (`wid`) cizer.
Arayuz video alaninin dikdortgenini (CSS pikseli * devicePixelRatio) bildirir, panel oraya tasinir.
Kontroller HTML'de kalir: oynat/duraklat/sarma komutlari buraya gelir; mpv zamani ve durumu
'mpv' olayiyla geri bildirir. Videonun ustune HTML cizilemez (yerel pencere ustte kalir).

Yalnizca Windows (WinForms); libmpv-2.dll uygulama klasorundeki bin\\ icinde aranir.
Uygulama kapaninca mpv sonlandirilir; arka planda hicbir sey kalmaz.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from app_core import APP_DIR, ROOT, WINDOWS

DLL_NAME = 'libmpv-2.dll'
# mpv tuslari -> arayuzde ayni kisayol (Player.svelte keydown ile ayni anlam)
# Goruntu cikisi (Ayarlar 'mpv_output'). 'next' (gpu-next) gercek ekran kartinda gomulu pencerede
# gorunur; vo=gpu bazi ekran kartlarinda WebView2 altinda siyah kalabiliyor (ses var, goruntu yok).
# 'safe' yedek olarak kalir (eski blit sunumu).
OUTPUTS = {
    'safe': {'vo': 'gpu', 'gpu_api': 'd3d11', 'd3d11_flip': 'no'},
    'next': {'vo': 'gpu-next', 'gpu_api': 'd3d11'},
}
# Fare hareketi tam ekranda imlec konumundan izlenir (watch_cursor); video penceresi her bilgisayarda
# fare olaylarini iletmiyor. Cift tiklamayla tam ekran yok (guvenilir calismadi, F129).
FORWARD_KEYS = ('MOUSE_MOVE', 'MBTN_LEFT', 'SPACE', 'LEFT', 'RIGHT', 'f', 'n', 'g', 'h', 'G', 'H', 'i', 'o', 'ESC')
_mpv_module = []


def dll_folder():
    for folder in (APP_DIR / 'bin', ROOT / 'bin', APP_DIR):
        if (folder / DLL_NAME).is_file():
            return folder
    return None


def load_mpv():
    """python-mpv modulu (libmpv yuklenmis) ya da None."""
    if _mpv_module:
        return _mpv_module[0]
    if not WINDOWS:
        return None
    folder = dll_folder()
    if folder is None:
        return None
    try:
        os.add_dll_directory(str(folder))
    except (AttributeError, OSError):
        pass
    os.environ['PATH'] = str(folder) + os.pathsep + os.environ.get('PATH', '')
    try:
        import mpv  # noqa: PLC0415 - libmpv yolu ayarlandiktan sonra yuklenmeli
    except (ImportError, OSError):
        return None
    _mpv_module.append(mpv)
    return mpv


def available():
    """libmpv ve python-mpv var mi (DLL yuklenmeden; ilk videoda yuklenir)."""
    import importlib.util
    return WINDOWS and dll_folder() is not None and importlib.util.find_spec('mpv') is not None


class NativePlayer:
    """Pencereye gomulu tek mpv ornegi. Tum WinForms islemleri pencerenin UI is parcaciginda."""

    TICK = 0.25   # zaman bildirimi en fazla bu siklikta

    def __init__(self, window, emit, log=print):
        self.window = window
        self.emit = emit
        self.log = log
        self.panel = None
        # Son bildirilen dikdortgen (x, y, genislik, yukseklik, gorunur). Panel henuz yokken gelen
        # konum da saklanir: panel ilk acilista dogrudan burada ve gorunur olusturulur (yoksa mpv
        # gizli 200x100 bir pencereye cizer ve ilk acilista goruntu siyah kalir).
        self._rect = None
        self.player = None
        self.path = None
        self._last = 0.0
        self._lock = threading.Lock()
        self._options = None      # mpv'nin acildigi (cikis, donanim cozme) ayari
        self._reported = None     # tani satiri yazilan dosya
        self._moved = 0.0
        self._watching = None     # tam ekranda imlec izleyen is parcacigi (threading.Event)

    # ------------------------------------------------------------------ UI is parcacigi
    def _ui(self, fn, wait=True):
        from System import Action, Func, Object
        form = self.window.native
        if not wait:
            form.BeginInvoke(Action(fn))
            return None
        box = []
        form.Invoke(Func[Object](lambda: box.append(fn())))
        return box[0] if box else None

    def _settings(self):
        from app_core import load_config
        try:
            cfg = load_config()
        except (OSError, ValueError):
            cfg = {}
        output = cfg.get('mpv_output', 'next')
        return (output if output in OUTPUTS else 'next', 'auto-safe' if cfg.get('mpv_hwdec', True) else 'no')

    def _ensure(self):
        options = self._settings()
        if self.player is not None and options != self._options:
            # Ayar degisti: mpv yeni secenekle yeniden acilir (panel kalir).
            self.log(f'[mpv] Görüntü ayarı değişti ({options[0]}, donanım çözme: {options[1]}); oynatıcı yeniden başlatılıyor.')
            self.close()
        if self.player is not None:
            return
        mpv = load_mpv()
        if mpv is None:
            raise RuntimeError('libmpv bulunamadı (bin\\libmpv-2.dll).')

        def make_panel():
            from System.Drawing import Color
            from System.Windows.Forms import Panel
            panel = Panel()
            panel.BackColor = Color.Black
            self._apply(panel)
            self.window.native.Controls.Add(panel)
            panel.BringToFront()
            return int(panel.Handle.ToInt64()), panel
        if self.panel is None:
            self._handle, self.panel = self._ui(make_panel)
        output, hwdec = self._options = options
        self.player = mpv.MPV(
            wid=str(self._handle), hwdec=hwdec, keep_open='yes', idle='yes', osc=False, **OUTPUTS[output],
            input_default_bindings=False, input_vo_keyboard=True, input_cursor=True,
            cursor_autohide='no', sub_auto='no', log_handler=self._mpv_log, loglevel='warn')
        # Video penceresi tiklamayi ve klavyeyi alir: arayuzun kisayollarina iletilir (bosluk, oklar...).
        for key in FORWARD_KEYS:
            self.player.register_key_binding(key, lambda state, _name, _char, key=key: self._key(state, key))
        for name in ('time-pos', 'pause', 'duration', 'eof-reached', 'hwdec-current', 'paused-for-cache',
                     'video-codec'):
            self.player.observe_property(name, self._changed)
        self.player.observe_property('video-params', self._report)

    def _report(self, _name, params):
        """Ilk karede bir kez Konsol'a tani: cikis, cozucu, boyut ve panelin yeri (siyah ekran icin)."""
        player = self.player
        if not params or player is None or self._reported == self.path:
            return
        self._reported = self.path

        def panel_info():
            panel = self.panel
            form = self.window.native
            return (f'panel {panel.Left},{panel.Top} {panel.Width}x{panel.Height} '
                    f'{"görünür" if panel.Visible else "gizli"}, sıra {form.Controls.GetChildIndex(panel)}/'
                    f'{form.Controls.Count}')
        try:
            where = self._ui(panel_info)
        except Exception as error:  # tani satiri oynatmayi bozmasin
            where = 'panel okunamadı: ' + str(error)
        try:
            self.log(f'[mpv] Çıkış: {player.current_vo} ({self._options[0]}), çözücü: '
                     f'{player.hwdec_current if player.hwdec_current not in (None, "no") else "işlemci"}, görüntü {params.get("w")}x{params.get("h")} '
                     f'{params.get("pixelformat", "")}; {where}')
        except Exception:
            pass

    def _key(self, state, key):
        if key == 'MOUSE_MOVE':   # tam ekranda kontrolleri gostermek icin; seyrek bildirilir
            now = time.monotonic()
            if now - self._moved >= 0.3:
                self._moved = now
                self.emit('mpv_key', {'key': key})
            return
        if not state or state[0] not in ('d', 'p'):   # yalnizca basma (birakma degil)
            return
        self.emit('mpv_key', {'key': key})

    def watch_cursor(self, on):
        """Tam ekranda imlec konumunu izler; kipirdayinca 'MOUSE_MOVE' bildirir (kontroller geri gelsin).
        Video penceresi fare hareketini her bilgisayarda iletmiyor; konum Windows'tan okunur."""
        if self._watching is not None:
            self._watching.set()
            self._watching = None
        if not on or not WINDOWS:
            return
        import ctypes
        from ctypes import wintypes
        stop = self._watching = threading.Event()

        def run():
            point, last = wintypes.POINT(), None
            while not stop.wait(0.15):
                if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                    continue
                now = (point.x, point.y)
                if last is not None and now != last:
                    self.emit('mpv_key', {'key': 'MOUSE_MOVE'})
                last = now
        threading.Thread(target=run, name='aktar-cursor', daemon=True).start()

    def _mpv_log(self, level, prefix, text):
        if level in ('error', 'fatal'):
            self.log(f'[mpv] {prefix}: {text.strip()}')

    def _changed(self, name, value):
        if name == 'time-pos':
            now = time.monotonic()
            if now - self._last < self.TICK:
                return
            self._last = now
        self.emit('mpv', self.state())

    def state(self):
        player = self.player
        if player is None:
            return {'ready': False}
        try:
            duration = player.duration or 0.0
            # loaded: dosya acildi, parca listesi hazir (sure ancak o zaman bilinir); arayuz menuleri acar
            return {'ready': True, 'loaded': duration > 0, 'path': self.path, 'time': player.time_pos or 0.0,
                    'duration': duration, 'paused': bool(player.pause),
                    'eof': bool(player.eof_reached), 'hwdec': player.hwdec_current or 'no',
                    'codec': player.video_codec or '', 'buffering': bool(player.paused_for_cache)}
        except Exception:  # mpv kapanirken
            return {'ready': False}

    # ------------------------------------------------------------------ komutlar
    def open(self, path, start=0.0, play=False, volume=None, mute=None):
        with self._lock:
            self._ensure()
            self.path = str(path)
            # Ses duzeyi her acilista verilir: arayuzun onceden gonderdigi komut mpv yokken bosa gidiyordu.
            if volume is not None:
                self.player.volume = max(0.0, min(100.0, float(volume) * 100))
            if mute is not None:
                self.player.mute = bool(mute)
            self.player.pause = not play
            self.player.sid = 'no'   # gomulu altyazi kendiliginden acilmaz; CC menusu secer
            self.player.loadfile(self.path, start=f'{max(0.0, float(start)):.3f}', sid='no')
        return self.state()

    def command(self, name, value=None):
        player = self.player
        if player is None:
            return {'ready': False}
        if name == 'toggle':
            player.pause = not player.pause
        elif name == 'play':
            player.pause = False
        elif name == 'pause':
            player.pause = True
        elif name == 'seek':
            player.seek(max(0.0, float(value)), reference='absolute', precision='exact')
        elif name == 'audio':   # ffprobe GLOBAL index -> mpv ses parcasi
            track = next((item for item in player.track_list or [] if item.get('type') == 'audio'
                          and item.get('ff-index') == int(value)), None)
            if track is not None:
                player.aid = track['id']
        elif name == 'volume':
            player.volume = max(0.0, min(100.0, float(value) * 100))
        elif name == 'mute':
            player.mute = bool(value)
        elif name == 'cursor':   # tam ekranda imlec bir sure sonra gizlenir (ms) ya da 'no'
            player.cursor_autohide = value if value == 'no' else int(value)
        return self.state()

    def _apply(self, panel):
        """Saklanan dikdortgeni panele uygular (UI is parcaciginda)."""
        if self._rect is None:
            panel.Visible = False
            return
        x, y, width, height, visible = self._rect
        panel.SetBounds(int(x), int(y), max(1, int(width)), max(1, int(height)))
        panel.Visible = bool(visible) and width > 2 and height > 2
        if panel.Visible:
            panel.BringToFront()

    def place(self, x, y, width, height, visible=True):
        """Paneli pencere istemci alanindaki fiziksel piksel dikdortgenine tasir. Panel henuz
        yoksa dikdortgen saklanir ve panel olusturulurken uygulanir."""
        self._rect = (x, y, width, height, visible)
        if self.panel is None:
            return
        self._ui(lambda: self._apply(self.panel), wait=False)

    def subtitle(self, path):
        """Gosterilen altyaziyi degistirir: `path` (dosya) ya da None (kapali). Oncekiler kaldirilir."""
        player = self.player
        if player is None:
            return
        for track in list(player.track_list or []):
            if track.get('type') == 'sub' and track.get('external'):
                try:
                    player.command('sub-remove', track['id'])
                except Exception:
                    pass
        if path:
            player.command('sub-add', str(path), 'select')
        else:
            player.sid = 'no'

    def show_text(self, text, ms=1500):
        if self.player is not None:
            self.player.show_text(str(text), ms)

    def hide(self):
        if self.panel is not None:
            self._ui(lambda: setattr(self.panel, 'Visible', False), wait=False)
        if self.player is not None:
            self.player.pause = True

    def close(self):
        self.watch_cursor(False)
        player, self.player = self.player, None
        self._reported = None
        if player is not None:
            try:
                player.terminate()
            except Exception:
                pass
