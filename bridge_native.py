"""Gomulu mpv oynaticinin arka ucu (F122, deneme; Bridge'e karisan sinif).

Oynatici sayfasi `engine` 'mpv' ise <video> yerine bunlari cagirir: mpv_open / mpv_command /
mpv_place (video alaninin dikdortgeni) / mpv_subtitle (CC secimi, zamanlama duzeltmesiyle) /
mpv_hide. mpv durumu 'mpv' olayiyla gelir (native_player.NativePlayer).
"""
from __future__ import annotations

from pathlib import Path

import qa
import subtitle_sync
from app_core import load_config

KARAOKE_STYLE = {'color': '#FFD400', 'base': '#FFFFFF', 'size': 60, 'mode': 'kf'}


class NativePlayerMixin:
    def _init_native(self):
        self._native = None            # desktop.py atar: native_player.NativePlayer (Windows + libmpv)
        self._native_sources = {}      # (yol, anahtar) -> bridge_subtitles.Source (her duzeltmede yeniden cikarilmasin)
        self._native_sub = 0

    def _engine(self):
        if self._native is None:
            return 'web'
        try:
            return 'mpv' if load_config().get('player_engine', 'mpv') == 'mpv' else 'web'
        except (OSError, ValueError):
            return 'mpv'

    def _need_native(self):
        if self._native is None:
            raise RuntimeError('Gömülü oynatıcı (mpv) kullanılamıyor.')
        return self._native

    def mpv_open(self, path, start=0.0, play=False, volume=None, mute=None):
        try:
            return self._need_native().open(Path(str(path)), float(start or 0.0), bool(play), volume, mute)
        except (RuntimeError, OSError) as error:
            self._log('[mpv] ' + str(error))
            return {'error': 'Video açılamadı: ' + str(error)}

    def mpv_command(self, name, value=None):
        try:
            return self._need_native().command(str(name), value)
        except (RuntimeError, ValueError, TypeError) as error:
            return {'error': str(error)}

    def mpv_place(self, x, y, width, height, visible=True):
        if self._native is not None:
            self._native.place(float(x), float(y), float(width), float(height), bool(visible))
        return True

    def mpv_hide(self):
        if self._native is not None:
            self._native.hide()
        return True

    def mpv_osd(self, text):
        if self._native is not None:
            self._native.show_text(text)
        return True

    def mpv_subtitle(self, path, key=None, timing=None, karaoke=True):
        """CC secimi: kaynak altyazi (zamanlama duzeltmesiyle) gecici dosyaya yazilip mpv'ye verilir.
        Whisper'da kelime zamanlari varsa (ve `karaoke`) soylenen kelime renklenir (ASS \\kf)."""
        native = self._native
        if native is None:
            return {'error': 'Gömülü oynatıcı yok.'}
        if not key:
            native.subtitle(None)
            return True
        path = Path(str(path))
        try:
            cache_key = (str(path), str(key))
            source = self._native_sources.get(cache_key)
            if source is None:
                source = self._native_sources[cache_key] = self._source(path, key)
            fmt = 'karaoke' if karaoke and source.words else 'source'
            text = source.render(fmt, subtitle_sync.Timing.of(timing), style=KARAOKE_STYLE)
            # Dosya adi her seferinde degisir: mpv eskisini okurken uzerine yazilmasin.
            self._native_sub = (self._native_sub + 1) % 4
            target = qa.work_dir() / 'qa' / f'mpv-sub-{self._native_sub}.{source.extension(fmt)}'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8', newline='\n')
            native.subtitle(target)
        except (RuntimeError, ValueError, OSError) as error:
            return {'error': 'Altyazı yüklenemedi: ' + str(error)}
        return True

    def _forget_native_sources(self, path=None):
        if path is None:
            self._native_sources.clear()
        else:
            for key in [item for item in self._native_sources if item[0] == str(path)]:
                del self._native_sources[key]

    def _stop_native_for_close(self):
        if self._native is not None:
            self._native.close()
