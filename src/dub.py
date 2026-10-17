"""Videoya dublaj (F141): secili (cevrilmis) altyaziyi sesli okuma motoruyla seslendirip videoya ses
parcasi olarak ekler.

Akis:
  1. Her altyazi satiri seslendirilir (tts.Engines.say; video basina onbellek, durdurulup yeniden
     baslatilinca hazir satirlar tekrar uretilmez).
  2. Satirin sesi kendi yerine (bir sonraki satira kadar) sigmazsa hizlandirilir: motor hiz
     destekliyorsa daha hizli yeniden okunur, yoksa FFmpeg atempo ile sikistirilir (en fazla
     `max_tempo`). Yine sigmazsa sonraki satirlar biraz kaydirilir; bosluklarda kayma sifirlanir.
  3. Satirlar tek bir dublaj izinde (WAV) zamanina yerlestirilir.
  4. FFmpeg ozgun sesi dublaj konusurken `background` duzeyine kisar (asendcmd ile yumusak gecis),
     iki sesi karistirir; sonuc videonun yanina yazilir:
       - 'mkv': goruntu ve ozgun parcalar kopyalanir, dublaj ilk (varsayilan) ses parcasi olur;
       - 'm4a': yalniz karisik ses.
Kaynak video SALT-OKUNUR. Is pencere icindeki is parcaciginda calisir; pencere kapaninca durur.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import media
from app_core import GracefulStop

FORMATS = ('mkv', 'm4a')
DEFAULTS = {'background': 0.25, 'duck': True, 'max_tempo': 1.35, 'format': 'mkv', 'speed': 1.0, 'audio': None}
FADE = 0.25            # ozgun sesin kisilip acilma suresi (sn)
FADE_STEPS = 5
MERGE_GAP = 0.8        # bu kadardan kisa sessizliklerde ozgun ses kisik kalir
SLOT_TAIL = 0.6        # satirin sesi, sonraki satira bosluk varsa bitisinden bu kadar tasabilir
MIX_RATE = 48000


def options_of(values):
    options = dict(DEFAULTS)
    for key, value in (values or {}).items():
        if key in DEFAULTS:
            options[key] = value
    options['background'] = min(1.0, max(0.0, float(options['background'] or 0)))
    options['duck'] = bool(options['duck'])
    options['max_tempo'] = min(2.0, max(1.0, float(options['max_tempo'] or 1)))
    options['speed'] = min(2.0, max(0.5, float(options['speed'] or 1)))
    options['format'] = options['format'] if options['format'] in FORMATS else 'mkv'
    options['audio'] = None if options['audio'] in (None, '') else int(options['audio'])
    return options


def cache_id(video):
    """Videonun dublaj onbellegi icin kimlik (tts onbellek klasoru adi)."""
    return hashlib.sha1(('dublaj:' + str(Path(video).resolve()).lower()).encode('utf-8')).hexdigest()[:20]


def lines_of(segments, timing=None):
    """[{start, end, text}] -> zamani duzeltilmis, sirali, bos olmayan satirlar."""
    scale, offset = 1.0, 0.0
    if timing:
        scale, offset = float(timing.get('scale', 1) or 1), float(timing.get('offset', 0) or 0)
    result = []
    for item in segments or []:
        text = ' '.join(str(item.get('text') or '').split())
        if not text:
            continue
        start = float(item['start']) * scale + offset
        end = float(item['end']) * scale + offset
        if end <= 0:
            continue
        result.append({'start': max(0.0, start), 'end': max(0.0, start, end), 'text': text})
    result.sort(key=lambda line: line['start'])
    return result


def slots(lines):
    """Her satirin sesi icin yer (sn): bir sonraki satirin baslangicina kadar; son satirda bitis + SLOT_TAIL."""
    result = []
    for index, line in enumerate(lines):
        limit = line['end'] + SLOT_TAIL
        if index + 1 < len(lines):
            limit = min(limit, lines[index + 1]['start'])
        result.append(max(0.3, limit - line['start'], line['end'] - line['start']))
    return result


def place(starts, durations):
    """Seslerin yerlesecegi zamanlar: kendi zamani ya da onceki ses bitmediyse onun bitisi."""
    result, cursor = [], 0.0
    for start, length in zip(starts, durations):
        at = max(float(start), cursor)
        result.append(at)
        cursor = at + float(length)
    return result


def regions(placed, durations, gap=MERGE_GAP):
    """Dublajin konustugu araliklar; aralarindaki kisa bosluklar birlestirilir."""
    merged = []
    for at, length in sorted(zip(placed, durations)):
        end = at + length
        if merged and at - merged[-1][1] < gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([at, end])
    return [(a, b) for a, b in merged]


def duck_commands(spans, level, fade=FADE, steps=FADE_STEPS):
    """asendcmd komut dosyasi: her konusma araliginda ozgun ses `level`e kisilir, sonra geri acilir."""
    lines = []

    def ramp(begin, frm, to):
        for step in range(1, steps + 1):
            value = frm + (to - frm) * step / steps
            lines.append(f'{max(0.0, begin + fade * (step - 1) / steps):.3f} volume@duck volume {value:.4f};')

    for begin, end in spans:
        ramp(begin - fade, 1.0, level)
        ramp(end, level, 1.0)
    return '\n'.join(lines) + ('\n' if lines else '')


def _clip(data):
    with wave.open(io.BytesIO(data)) as clip:
        return clip.getframerate(), clip.getnchannels(), clip.getsampwidth(), clip.readframes(clip.getnframes())


def _seconds(frames, rate):
    return len(frames) / 2.0 / rate


def _run(command, cwd=None):
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    done = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          text=True, encoding='utf-8', errors='replace', cwd=cwd, **kwargs)
    if done.returncode != 0:
        raise RuntimeError('FFmpeg dublajı yazamadı: ' + ((done.stderr or '').strip()[-500:] or f'çıkış kodu {done.returncode}'))


def atempo(frames, rate, tempo, folder):
    """16 bit mono PCM'i FFmpeg atempo ile `tempo` kat hizlandirir (perde degismez)."""
    source, target = Path(folder) / 'tempo-in.wav', Path(folder) / 'tempo-out.wav'
    with wave.open(str(source), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(frames)
    _run([media.ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'error', '-y', '-i', str(source),
          '-filter:a', f'atempo={tempo:.4f}', '-ac', '1', '-ar', str(rate), '-c:a', 'pcm_s16le', str(target)])
    with wave.open(str(target)) as clip:
        return clip.readframes(clip.getnframes())


def mix_command(video, track, output, options, has_audio, duck_file=None):
    """FFmpeg karistirma komutu. `track`: dublaj WAV'i; `duck_file`: calisma klasorundeki asendcmd dosyasi."""
    options = options_of(options)
    command = [media.ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'error', '-y', '-i', str(video), '-i', str(track)]
    dub = f'[1:a]aresample={MIX_RATE},aformat=channel_layouts=stereo[dub]'
    if has_audio:
        original = f'0:{options["audio"]}' if options['audio'] is not None else '0:a:0'
        level = options['background']
        if options['duck'] and duck_file:
            duck = f'asendcmd=f={duck_file},volume@duck=1'
        else:
            duck = f'volume={level:.4f}'
        graph = (f'[{original}]aresample={MIX_RATE},aformat=channel_layouts=stereo,{duck}[bg];{dub};'
                 '[bg][dub]amix=inputs=2:duration=longest:normalize=0[out]')
    else:
        graph = dub.replace('[dub]', '[out]')
    command += ['-filter_complex', graph]
    if options['format'] == 'm4a':
        return command + ['-map', '[out]', '-vn', '-c:a', 'aac', '-b:a', '192k', str(output)]
    command += ['-map', '0:v?', '-map', '[out]']
    if has_audio:
        command += ['-map', '0:a']
    command += ['-map', '0:s?', '-map', '0:t?', '-c', 'copy', '-c:a:0', 'aac', '-b:a:0', '192k',
                '-metadata:s:a:0', 'language=tur', '-metadata:s:a:0', 'title=Türkçe dublaj',
                '-disposition:a', '0', '-disposition:a:0', 'default',
                # Kopyalanan akislar karistirma filtresinden hizli akar; FFmpeg varsayilan olarak 10 sn'den fazla
                # bekletmez ve dublaj paketleri dosyanin sonuna yigilir (oynaticilar sesi bulamaz). Tam siralama:
                '-max_interleave_delta', '0', '-max_muxing_queue_size', '65536']
    return command + [str(output)]


def build(engines, video, segments, output, options=None, timing=None, language='tr', override=None,
          duration=0.0, has_audio=True, can_speed=False, progress=None, cancelled=None, log=None):
    """Dublaji yazar (bloklar). progress(done, total, stage): stage 'voice' (satir) ya da 'mix' (saniye).
    Donen: {'output', 'lines', 'faster', 'shifted'}."""
    import clip   # klip kaydinin FFmpeg ilerleme okuyucusu

    options = options_of(options)
    log = log or (lambda _message: None)
    lines = lines_of(segments, timing)
    if not lines:
        raise ValueError('Altyazıda seslendirilecek satır yok.')
    book = cache_id(video)
    room = slots(lines)
    folder = Path(tempfile.mkdtemp(prefix='aktar-dublaj-'))
    voices, faster = [], 0
    rate = None
    try:
        for index, line in enumerate(lines):
            if cancelled and cancelled():
                raise GracefulStop('Dublaj durduruldu.')
            result = engines.say(line['text'], options['speed'], book, language, override)
            if not result.get('audio'):
                voices.append(b'')
                continue
            clip_rate, channels, width, frames = _clip(base64.b64decode(result['audio']))
            if channels != 1 or width != 2:
                raise RuntimeError('Ses motoru beklenmeyen biçimde ses döndürdü (16 bit mono değil).')
            if rate is None:
                rate = clip_rate
            elif clip_rate != rate:
                raise RuntimeError('Ses motoru satırlarda farklı örnekleme hızları döndürdü.')
            length = _seconds(frames, rate)
            need = length / room[index]
            if need > 1.02:
                tempo = min(options['max_tempo'], need)
                if can_speed:
                    quick = engines.say(line['text'], round(options['speed'] * tempo, 2), book, language, override)
                    if quick.get('audio'):
                        frames = _clip(base64.b64decode(quick['audio']))[3]
                else:
                    frames = atempo(frames, rate, tempo, folder)
                faster += 1
            voices.append(frames)
            if progress:
                progress(index + 1, len(lines), 'voice')
        if rate is None:
            raise RuntimeError('Ses motoru hiçbir satır için ses üretmedi.')
        lengths = [_seconds(frames, rate) for frames in voices]
        placed = place([line['start'] for line in lines], lengths)
        shifted = sum(1 for at, line in zip(placed, lines) if at - line['start'] > 0.3)
        track = folder / 'dublaj.wav'
        with wave.open(str(track), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            written = 0
            for at, frames in zip(placed, voices):
                if not frames:
                    continue
                start = int(round(at * rate))
                while written < start:
                    count = min(start - written, rate * 30)
                    out.writeframes(b'\x00\x00' * count)
                    written += count
                out.writeframes(frames)
                written += len(frames) // 2
        duck = None
        if has_audio and options['duck']:
            spans = regions([at for at, n in zip(placed, lengths) if n > 0], [n for n in lengths if n > 0])
            (folder / 'duck.cmd').write_text(duck_commands(spans, options['background']), encoding='utf-8')
            duck = 'duck.cmd'
        log(f'Dublaj: {len(lines)} satır seslendirildi ({faster} satır hızlandırıldı, {shifted} satır kaydırıldı); '
            'ses karıştırılıyor…')
        output = Path(output)
        partial = output.with_name(output.stem + '.part' + output.suffix)
        command = mix_command(video, track.resolve(), partial.resolve(), options, has_audio, duck)
        total = float(duration or 0) or (written / rate)
        try:
            clip.run(command, total, cwd=str(folder), progress=lambda done, all_: progress and progress(done, all_, 'mix'),
                     cancelled=cancelled)
        except GracefulStop:
            partial.unlink(missing_ok=True)
            raise GracefulStop('Dublaj durduruldu.')
        except RuntimeError as error:
            partial.unlink(missing_ok=True)
            if options['format'] != 'mkv':
                raise RuntimeError(str(error).replace('Klip kaydedilemedi', 'Dublaj kaydedilemedi')) from error
            # Ornek: MP4'teki mov_text altyazisi MKV'ye kopyalanamaz; altyazi ve ekler olmadan yeniden denenir.
            log('Dublaj: altyazı akışları kopyalanamadı, altyazısız yazılıyor. (' + str(error)[-200:] + ')')
            command = _drop_map(_drop_map(command, '0:s?'), '0:t?')
            try:
                clip.run(command, total, cwd=str(folder), cancelled=cancelled)
            except GracefulStop:
                partial.unlink(missing_ok=True)
                raise GracefulStop('Dublaj durduruldu.')
            except RuntimeError as again:
                partial.unlink(missing_ok=True)
                raise RuntimeError(str(again).replace('Klip kaydedilemedi', 'Dublaj kaydedilemedi')) from again
        os.replace(partial, output)
        return {'output': str(output), 'lines': len(lines), 'faster': faster, 'shifted': shifted}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _drop_map(command, target):
    result, skip = [], False
    for index, part in enumerate(command):
        if skip:
            skip = False
            continue
        if part == '-map' and index + 1 < len(command) and command[index + 1] == target:
            skip = True
            continue
        result.append(part)
    return result
