"""ffprobe / ffmpeg sarmalayicisi: stream tespiti ve altyazi cikarma.

Kaynak video SALT-OKUNUR kabul edilir. Bu modul yalnizca okur ve secilen
metin tabanli altyazi stream'ini cikarir; video uzerine yazmaz, yeni video
uretmez, yeniden encode etmez.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from app_core import APP_DIR, ROOT

# ffprobe codec adi -> (destekleniyor mu, cikti uzantisi, metin mi)
TEXT_SUBTITLE_CODECS = {
    'subrip': ('srt', True),
    'srt': ('srt', True),
    'ass': ('ass', True),
    'ssa': ('ssa', True),
    'webvtt': ('vtt', True),
    'mov_text': ('srt', True),   # MP4 tx3g; uygun metin formatina cevrilir
    'text': ('srt', True),
}
IMAGE_SUBTITLE_CODECS = {
    'hdmv_pgs_subtitle', 'dvd_subtitle', 'dvb_subtitle', 'xsub',
    'pgssub', 'vobsub',
}

VIDEO_EXTENSIONS = ('.mkv', '.mp4', '.m4v', '.avi', '.mov', '.webm', '.ts', '.wmv', '.flv')


def _find_binary(name):
    """Once uygulama dizini, sonra PyInstaller _MEIPASS, sonra PATH."""
    for directory in (APP_DIR / 'bin', ROOT / 'bin'):
        for candidate in (directory / f'{name}.exe', directory / name):
            if candidate.exists():
                return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(
        f'{name} bulunamadı. Uygulama klasöründeki "bin" dizinine '
        f'{name}.exe dosyasını koyun.'
    )


def ffprobe_path():
    return _find_binary('ffprobe')


def ffmpeg_path():
    return _find_binary('ffmpeg')


def _run(command):
    kwargs = {}
    if os.name == 'nt':
        # Windows'ta konsol penceresi acilmasini engelle.
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', **kwargs)
    except OSError as error:
        raise RuntimeError('Komut çalıştırılamadı: ' + str(command[0])) from error
    return result


def _no_window():
    # Geriye uyumluluk icin tutuldu; _run artik os.name kontrolu yapar.
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0


def subtitle_streams(video):
    """Videodaki altyazi stream'lerini listeler.

    Donen her kayit: index (GLOBAL stream index), codec, language, title,
    supported (metin tabanli mi), extension (cikti uzantisi), image (goruntu
    tabanli mi). `-map 0:s:N` subtitle SIRASINA gore indeksledigi icin cikarma
    isleminde GLOBAL index kullanilir.
    """
    video = Path(video)
    if not video.exists():
        raise ValueError('Video bulunamadı: ' + str(video))
    command = [ffprobe_path(), '-v', 'error', '-show_streams', '-show_format',
               '-of', 'json', str(video)]
    result = _run(command)
    if result.returncode != 0:
        raise RuntimeError('ffprobe videoyu okuyamadı: ' + (result.stderr or '').strip())
    try:
        value = json.loads(result.stdout or '{}')
    except json.JSONDecodeError as error:
        raise RuntimeError('ffprobe çıktısı okunamadı.') from error
    streams = []
    for stream in value.get('streams', []):
        if stream.get('codec_type') != 'subtitle':
            continue
        codec = str(stream.get('codec_name', '')).lower()
        tags = stream.get('tags', {}) or {}
        extension, supported = TEXT_SUBTITLE_CODECS.get(codec, ('', False))
        streams.append({
            'index': stream.get('index'),
            'codec': codec,
            'language': str(tags.get('language', '')).strip(),
            'title': str(tags.get('title', '')).strip(),
            'supported': supported,
            'image': codec in IMAGE_SUBTITLE_CODECS,
            'extension': extension,
        })
    return streams


def extract_subtitle(video, stream_index, output, codec=''):
    """Secilen metin tabanli altyazi stream'ini `output` dosyasina cikarir.

    Video uzerinde hicbir degisiklik yapilmaz. Metin tabanli codec'ler oldugu
    gibi kopyalanir; `mov_text` (MP4 tx3g) uygun metin formatina (SRT) cevrilir.
    """
    video, output = Path(video), Path(output)
    if not video.exists():
        raise ValueError('Video bulunamadı: ' + str(video))
    codec = str(codec).lower()
    if codec in IMAGE_SUBTITLE_CODECS:
        raise ValueError('Görüntü tabanlı altyazı şu anda desteklenmiyor.')
    if codec and codec not in TEXT_SUBTITLE_CODECS:
        raise ValueError('Desteklenmeyen altyazı codec: ' + codec)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg_path(), '-v', 'error', '-y', '-i', str(video),
               '-map', f'0:{int(stream_index)}']
    command += ['-c:s', 'srt'] if codec == 'mov_text' else ['-c:s', 'copy']
    command.append(str(output))
    result = _run(command)
    if result.returncode != 0:
        raise RuntimeError('Altyazı çıkarılamadı: ' + (result.stderr or '').strip())
    if not output.exists():
        raise RuntimeError('Altyazı çıkarılamadı; çıktı dosyası oluşmadı.')
    return output


def unique_output_path(video, extension):
    """Videonun dizininde cakismasiz CEVIRI cikti yolu uretir.

    `<video>_TR.<uzanti>`; varsa `<video>_TR (2).<uzanti>`, `<video>_TR (3)...`.
    Var olan dosyanin uzerine sessizce YAZILMAZ.
    """
    return _unique_path(Path(video), f'{Path(video).stem}_TR', extension)


def unique_source_path(video, extension):
    """Videonun dizininde cakismasiz KAYNAK altyazi cikarma yolu uretir.

    `<video>.<uzanti>`; varsa `<video> (2).<uzanti>`, `<video> (3)...`.
    """
    return _unique_path(Path(video), Path(video).stem, extension)


def _unique_path(video, stem, extension):
    directory = Path(video).parent
    extension = str(extension).lstrip('.').lower()
    candidate = directory / f'{stem}.{extension}'
    index = 2
    while candidate.exists():
        candidate = directory / f'{stem} ({index}).{extension}'
        index += 1
    return candidate


def find_videos(folder):
    """Klasordeki video dosyalarini (uzantiya gore, ASCII-buyuk/kucuk duyarsiz) dondurur."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError('Klasör bulunamadı: ' + str(folder))
    return sorted((item for item in folder.iterdir()
                   if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS),
                  key=lambda item: item.name.lower())
