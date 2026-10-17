"""Renk temalari (Deeverse ile ayni bicim).

Bir tema dosyasi JSON'dur: bir `base` (`dark` ya da `light`) ve degistirilecek renkler,
`#RRGGBB` veya `#RRGGBBAA` olarak; ornek `{"base": "dark", "colors": {"accent": "#a238ff"}}`.
Renk adlari PALETTE_KEYS'tir. Dosyalar uygulama dizinindeki `themes/` klasorunde durur;
Aktar'in hazir temalari ilk acilista oraya bir kez yazilir. Kullanici bir hazir temayi
silerse silinmis kalir (kayit: INSTALLED). Deeverse'in tema dosyalari aynen calisir.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app_core import APP_DIR, ROOT, read

PALETTE_KEYS = ('window', 'panel', 'surface', 'surface_hover', 'surface_active', 'outline', 'text',
                'secondary', 'dim', 'accent', 'accent_hover', 'on_accent', 'danger', 'warning',
                'overlay', 'shadow')

# Deeverse'in (Spotifast) koyu/acik grileri, vurgu rengi Aktar'in limon yesili.
BASES = {
    'dark': {
        'window': '#0f1114', 'panel': '#15181c', 'surface': '#1d2127', 'surface_hover': '#262b33',
        'surface_active': '#2f353f', 'outline': '#2a3038', 'text': '#f2f4f6', 'secondary': '#a9b1bc',
        'dim': '#6e7784', 'accent': '#c8ff00', 'accent_hover': '#d6ff3d', 'on_accent': '#0a1200',
        'danger': '#f5717f', 'warning': '#f2b85c', 'overlay': '#22272e', 'shadow': '#0000008c',
    },
    'light': {
        'window': '#f8f9fb', 'panel': '#ffffff', 'surface': '#eef0f3', 'surface_hover': '#e3e6eb',
        'surface_active': '#d7dbe1', 'outline': '#dde1e6', 'text': '#14171a', 'secondary': '#535b66',
        'dim': '#8b939e', 'accent': '#4d7c0f', 'accent_hover': '#3f6212', 'on_accent': '#ffffff',
        'danger': '#d63b4c', 'warning': '#b87a14', 'overlay': '#ffffff', 'shadow': '#0000002d',
    },
}
BUILT_IN = {'dark': 'Koyu', 'light': 'Açık'}
DEFAULT_THEME = 'dark'
INSTALLED = '.installed-aktar-palettes'
COLOR = re.compile(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?')


def themes_dir():
    return APP_DIR / 'themes'


def presets_dir():
    return ROOT / 'assets' / 'themes'


def install_presets(folder=None, source=None):
    """Bu surumun getirdigi ve daha once hic kurulmamis hazir temalari yazar.

    Var olan dosyanin uzerine yazmaz: kurulduktan sonra dosya kullanicinindir."""
    folder = Path(folder or themes_dir())
    source = Path(source or presets_dir())
    record = folder / INSTALLED
    try:
        installed = set(read(record).splitlines()) if record.exists() else set()
    except OSError:
        installed = set()
    changed = False
    for preset in sorted(source.glob('*.json')):
        if preset.name in installed:
            continue
        target = folder / preset.name
        try:
            if not target.exists():
                folder.mkdir(parents=True, exist_ok=True)
                target.write_bytes(preset.read_bytes())
        except OSError:
            continue
        installed.add(preset.name)
        changed = True
    if changed:
        try:
            record.write_text(''.join(name + '\n' for name in sorted(installed)), encoding='utf-8')
        except OSError:
            pass


def parse_palette(text):
    """Tema dosyasini tam palete cevirir; hatali dosyada ValueError (Turkce mesaj)."""
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ValueError(f'JSON okunamadı: {error}') from None
    if not isinstance(data, dict):
        raise ValueError('Tema bir JSON nesnesi olmalı.')
    base = str(data.get('base', 'dark')).lower()
    if base not in BASES:
        raise ValueError('base "dark" ya da "light" olmalı.')
    colors = data.get('colors', {})
    if not isinstance(colors, dict):
        raise ValueError('colors bir nesne olmalı.')
    palette = dict(BASES[base])
    for name, value in colors.items():
        if name not in PALETTE_KEYS:
            continue  # bilinmeyen adlar (baska programlarin renkleri) yok sayilir
        if not isinstance(value, str) or not COLOR.fullmatch(value.strip()):
            raise ValueError(f'{name}: renk #RRGGBB ya da #RRGGBBAA olmalı.')
        palette[name] = value.strip().lower()
    return base, palette


def display_name(filename):
    return Path(filename).stem


def list_themes(folder=None):
    """Yerlesik Koyu/Acik ve klasordeki tema dosyalari (bozuklar hata mesajiyla)."""
    result = [{'id': key, 'name': name, 'base': key, 'palette': dict(BASES[key]), 'file': ''}
              for key, name in BUILT_IN.items()]
    folder = Path(folder or themes_dir())
    if folder.is_dir():
        for path in sorted(folder.glob('*.json'), key=lambda item: item.name.casefold()):
            entry = {'id': 'file:' + path.name, 'name': display_name(path.name), 'file': path.name}
            try:
                entry['base'], entry['palette'] = parse_palette(read(path))
            except (OSError, ValueError) as error:
                entry['error'] = str(error)
            result.append(entry)
    return result


def resolve(theme_id, folder=None):
    """Secili temanin paleti; bulunamazsa ya da bozuksa yerlesik koyu tema."""
    theme_id = str(theme_id or DEFAULT_THEME)
    if theme_id in BASES:
        return theme_id, dict(BASES[theme_id])
    if theme_id.startswith('file:'):
        name = Path(theme_id[5:]).name
        path = Path(folder or themes_dir()) / name
        try:
            return parse_palette(read(path))
        except (OSError, ValueError):
            pass
    return DEFAULT_THEME, dict(BASES[DEFAULT_THEME])
