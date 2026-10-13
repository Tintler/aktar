"""Transkriptleri disa aktarma (F62): TXT, SRT, Markdown; koleksiyon icin tek Markdown.

Qt'den bagimsizdir. Kaynak her videonun indekslenen transkripti
(search_index.primary_session). Kaynak videolar SALT-OKUNUR: cikti yalnizca
kullanicinin sectigi yola yazilir, var olan dosyanin uzerine sessizce yazilmaz.
"""
from __future__ import annotations

from pathlib import Path

import qa
import search_index

FORMATS = {'txt': 'Metin', 'srt': 'Altyazı (SRT)', 'md': 'Markdown'}


def srt_time(seconds):
    total = max(0, int(round(float(seconds) * 1000)))
    hours, rest = divmod(total, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, millis = divmod(rest, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}'


def render(session, fmt):
    """Tek videonun transkripti istenen bicimde (metin)."""
    title = session.get('title') or 'Transkript'
    if fmt == 'srt':
        cues = []
        for number, segment in enumerate(session['segments'], 1):
            end = max(float(segment['end']), float(segment['start']) + 0.5)
            cues.append(f'{number}\n{srt_time(segment["start"])} --> {srt_time(end)}\n'
                        f'{segment["text"]}\n')
        return '\n'.join(cues)
    lines = qa.compact_lines(session['segments'])
    if fmt == 'md':
        overview = (session.get('overview') or {}).get('summary', '')
        body = '\n'.join(f'**[{qa.format_time(line["start"])}]** {line["text"]}  ' for line in lines)
        return (f'# {title}\n\n' + (f'> {overview}\n\n' if overview else '')
                + '## Transkript\n\n' + body + '\n')
    if fmt == 'txt':
        return f'{title}\n\n{qa.format_lines(lines)}\n'
    raise ValueError('Bilinmeyen biçim: ' + str(fmt))


def render_collection(title, videos, overview=None, base=None):
    """Koleksiyonun tum transkriptleri tek Markdown'da (ozetler varsa basta)."""
    parts = [f'# {title}\n']
    if overview and overview.get('summary'):
        parts.append(overview['summary'] + '\n')
        if overview.get('topics'):
            parts.append('**Konular:** ' + ' · '.join(overview['topics']) + '\n')
    count = 0
    for video in videos:
        session = search_index.primary_session(video, base)
        if session is None:
            continue
        count += 1
        text = render(session, 'md').replace('\n## Transkript\n\n', '\n')
        parts.append('#' + text)  # video basligi bir alt seviye: '## <video>'
    if not count:
        raise ValueError('Dışa aktarılacak transkript yok: önce "Hepsini hazırla".')
    return '\n'.join(parts)


def write(path, text):
    """Yeni dosyaya yazar; var olan dosyanin uzerine yazilmaz (cagiran onay almadiysa)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    return path


def unique_path(folder, stem, extension):
    """Klasorde cakismasiz '<stem>.<uzanti>' ('<stem> (2).<uzanti>' ...)."""
    folder = Path(folder)
    candidate = folder / f'{stem}.{extension}'
    index = 2
    while candidate.exists():
        candidate = folder / f'{stem} ({index}).{extension}'
        index += 1
    return candidate


def export_many(videos, folder, fmt, base=None):
    """Birden cok videonun transkriptini klasore yazar. Donen: (yazilanlar, transkripti yok)."""
    written, missing = [], []
    for video in videos:
        session = search_index.primary_session(video, base)
        if session is None:
            missing.append(Path(video).name)
            continue
        written.append(write(unique_path(folder, Path(video).stem, fmt), render(session, fmt)))
    return written, missing
