"""Drama 3 (Turkce) ses motoru (F158): kullanicinin kendi baslattigi SGLang-Omni sunucusuna HTTP istemcisi.

Fish Audio Drama 3'un Turkceye gore budanmis surumu ayri bir makinede (orn. WSL'de `serve_tr.sh`) calisir;
Aktar sunucuyu baslatmaz, yalnizca baglanir. Motor ayri bir surec degil, Aktar'in icinde calisir
(motor.json "builtin": "drama3", tts.InlineWorker); yalnizca standart kutuphane ve ffmpeg kullanir.

Sunucu API'si:
    GET  {url}/health            -> 200 {"status": "healthy", ...}
    POST {url}/v1/audio/speech   {"model": "drama-3", "input": metin, "references": [{"text", "data"}],
                                  "response_format": "wav"}  -> 44.1 kHz mono 16 bit WAV

Istek basina en fazla ~14 sn konusma uretilir: metin cumlelere, uzun cumle virgullerden, gerekirse
kelimelerden bolunur; parcalar birlestirilir. [laughs], <whisper>...</whisper>, <|speaker:N|> etiketleri
aynen gider (etiket icinden bolunmez). Model bazen uzun sessizlik biraktigi icin 1 sn'den uzun
sessizlikler 0,4 sn'ye kisaltilir. Klon kaydi en fazla 20 sn olabilir; dogru transkript gerekir:
verilmezse (ya da kayit kirpilirsa) Aktar'in Whisper altyapisiyla cikarilir.
"""
from __future__ import annotations

import array
import base64
import hashlib
import io
import json
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import wave
from pathlib import Path

DEFAULT_URL = 'http://127.0.0.1:7861'
MODEL = 'drama-3'
MAX_CHARS = 150            # bir istekte en fazla karakter (Ayarlar'dan 60-250); kisa parca daha az atlar ama
                           # cumle ortasinda ton degisir (F160: 122 karakterde 1/10 erken bitme, bolunce 0/20)
CAP_SECONDS = 14.3         # serve_tr.sh MAXNEW=320 kare = 14,86 sn; buna ulasan ses kesilmis sayilir ve parca bolunur.
                           # Kesilme bir duraklamaya denk gelirse ses sessiz biter (F162: 7 kelime boyle kayboldu),
                           # o yuzden sonun sesli olmasi aranmaz. MAXNEW buyutulurse yalnizca gereksiz bir bolme olur.
REFERENCE_SECONDS = 20.0   # sunucunun kabul ettigi en uzun klon kaydi
TRANSCRIBE_SECONDS = 30.0  # kirpma noktasini bulmak icin Whisper'a giden en uzun bolum
REQUEST_TIMEOUT = 180      # yeni bir sesle ilk istek ~8 sn; uzun cumle + yogun sunucu icin pay
HEALTH_TIMEOUT = 5
# Ornekleme (F159/F160): sunucu varsayilani (temperature 1.0, top_p 0.9) her cumleyi farkli tonlar. Daha dar
# ornekleme tonu sabitler ama model bazen ilk ifadeden sonra susar ve cumlenin kalanini atlar (0.7/0.7 ile
# uzun parcalarin ~%4'u). 0.8 + varsayilan top_p bu olcumde susmadi; yine de susan parca yeniden istenir.
TEMPERATURE = 0.8
TOP_P = 0.9                # sunucu varsayilani; daha dari modeli susturabilir
# Ayarlar -> Ses'te degistirilebilenler (ui.json tts.engine_settings.drama3; engines/drama3/motor.json "settings")
SETTINGS = {'max_chars': (MAX_CHARS, 60, 250), 'temperature': (TEMPERATURE, 0.3, 1.5), 'top_p': (TOP_P, 0.5, 1.0)}
SILENT_RETRY_TEMPERATURES = (None, None)   # susan parca icin yeniden denemeler (None: sunucu varsayilani)
MAX_LETTERS_PER_SECOND = 24   # konusulan sureye gore bundan hizli parca "susmus" sayilir (normal 10-17)
CHECK_MIN_LETTERS = 25        # bundan kisa parcada harf orani yerine en az konusma suresi aranir:
SHORT_MIN_VOICED, SHORT_LETTERS_PER_SECOND = 0.3, 18.0   # max(0,3 sn, harf/18)
OVERLONG_BASE, OVERLONG_LETTERS_PER_SECOND = 2.0, 5.0   # ses bundan uzunsa (2 sn + harf/5) model takilmis sayilir
VOICED_LEVEL = 1500           # 100 ms pencerede bu tepeyi asan bolum konusma sayilir
ABRUPT_LEVEL = 1000           # son 50 ms'de bu tepeyi asan ses 'erken bitmis' sayilir (873 parcada ~%11)
SENTENCE_GAP = 0.25        # cumle parcalari arasina konan sessizlik (sn)
CLAUSE_GAP = 0.12          # virgulden bolunen parcalar arasina
SILENCE_LIMIT = 1.0        # bundan uzun sessizlik...
SILENCE_KEEP = 0.4         # ...bu kadara kisaltilir
SILENCE_LEVEL = 300        # 16 bit orneklerde sessizlik esigi (~-40 dBFS)
SILENCE_WINDOW = 0.01      # sessizlik penceresi (sn)
REFERENCE_VERSION = 2      # hazirlanan klon kaydi onbellegi bicimi (2: duraklamada kesme + sonda ses azaltma)
FADE_SECONDS = 0.04        # kirpilan referansin sonundaki ses azaltma
CONSENT_NOTE = ('Rızası olmadan tanınabilir kişilerin sesini klonlamak yasaktır (Fish Audio Community License). '
                'Yalnızca hakkına sahip olduğunuz kayıtları kullanın.')
RECORDING_HINT = ('En iyi sonuç: 8-15 saniyelik, sakin, gürültüsüz ve tam bir cümleyle biten kayıt. '
                  '20 saniyeden uzun kayıtlar kırpılır.')

_SENTENCE_END = re.compile(r'(?<=[.!?…])["\'»”’)\]]*\s+')
_CLAUSE_END = re.compile(r'(?<=[,;:])\s+')
_SPEAKER = re.compile(r'<\|speaker:\d+\|>')


class ServerError(RuntimeError):
    """Sunucuya ulasilamadi ya da sunucu hata dondurdu."""


def normalize_url(url):
    url = str(url or '').strip().rstrip('/') or DEFAULT_URL
    if not re.match(r'https?://', url, re.I):
        url = 'http://' + url
    return url


def _unreachable(url, error):
    return ServerError(f'Drama 3 sunucusuna bağlanılamadı ({url}). Sunucuyu başlatın (ör. WSL\'de '
                       f'"bash ~/drama3/serve_tr.sh") ve adresi Ayarlar → Ses bölümünden denetleyin. '
                       f'Ayrıntı: {getattr(error, "reason", None) or error}')


def health(url, timeout=HEALTH_TIMEOUT):
    """Sunucunun saglik yaniti (dict); calismiyorsa ServerError."""
    url = normalize_url(url)
    try:
        with urllib.request.urlopen(url + '/health', timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as error:
        raise ServerError(f'Drama 3 sunucusu sağlık denetiminde hata verdi (HTTP {error.code}).') from error
    except (urllib.error.URLError, OSError) as error:
        raise _unreachable(url, error) from error
    except ValueError as error:
        raise ServerError(f'{url} bir Drama 3 sunucusu gibi görünmüyor (sağlık yanıtı JSON değil).') from error
    if not isinstance(data, dict) or str(data.get('status', '')).lower() != 'healthy':
        raise ServerError(f'Drama 3 sunucusu hazır değil (durum: {data.get("status") if isinstance(data, dict) else data}).')
    return data


def speech(url, text, references=(), timeout=REQUEST_TIMEOUT, retries=1, temperature=TEMPERATURE, top_p=TOP_P):
    """Bir metin parcasini WAV bayt olarak uretir (temperature/top_p None ise sunucu varsayilani). Sunucu 500 dondururse (ara sira 'generated no audio
    frames') `retries` kez yeniden dener."""
    url = normalize_url(url)
    payload = {'model': MODEL, 'input': text, 'references': list(references), 'response_format': 'wav'}
    if temperature is not None:
        payload['temperature'] = temperature
    if top_p is not None:
        payload['top_p'] = top_p
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    for attempt in range(retries + 1):
        request = urllib.request.Request(url + '/v1/audio/speech', data=body, method='POST',
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            detail = _detail(error)
            if error.code >= 500 and attempt < retries:
                continue
            raise ServerError(f'Drama 3 sunucusu ses üretemedi (HTTP {error.code}): {detail}') from error
        except (urllib.error.URLError, OSError) as error:
            raise _unreachable(url, error) from error
    raise ServerError('Drama 3 sunucusu ses üretemedi.')   # pragma: no cover


def _detail(error):
    try:
        raw = error.read().decode('utf-8', 'replace')
    except OSError:
        return str(error.reason)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            inner = data.get('detail') or data.get('error') or data.get('message') or raw
            if isinstance(inner, dict):
                inner = inner.get('message') or json.dumps(inner, ensure_ascii=False)
            raw = str(inner)
    except ValueError:
        pass
    return ' '.join(raw.split())[:300]


# ---------------------------------------------------------------- metni parcalara bolme
def _protected(text):
    """Bolunmemesi gereken araliklar: <whisper>...</whisper> gibi acik etiketlerin ici ve <|...|>."""
    spans, stack = [], []
    for match in re.finditer(r'<\|[^|>]*\|>|<(/?)([A-Za-z][\w-]*)>', text):
        if match.group(0).startswith('<|'):
            spans.append((match.start(), match.end()))
        elif not match.group(1):
            stack.append((match.group(2), match.start()))
        elif stack and stack[-1][0] == match.group(2):
            spans.append((stack.pop()[1], match.end()))
    if stack:   # kapanmayan etiket: sonuna kadar
        spans.append((stack[0][1], len(text)))
    return spans


def _lower_follows(text, end):
    """Bolme noktasindan sonra kucuk harf mi geliyor ('44. bolumunu', 'Gelir misin? diye'): cumle bitmemistir
    (okuyucunun sentences.js kurali)."""
    following = text[end:end + 1]
    return following.isalpha() and following != following.upper()


def _cuts(text, pattern):
    """`pattern` eslesmelerindeki bolme noktalari (korunan araliklarin icindekiler haric): [(bas, son)]."""
    spans = _protected(text)
    return [(m.start(), m.end()) for m in pattern.finditer(text)
            if not any(a < m.start() < b for a, b in spans)
            and not (pattern is _SENTENCE_END and _lower_follows(text, m.end()))]


def _split(text, pattern):
    pieces, last = [], 0
    for start, end in _cuts(text, pattern):
        pieces.append(text[last:start])
        last = end
    pieces.append(text[last:])
    return [piece.strip() for piece in pieces if piece.strip()]


_SPACE = re.compile(r'\s+')


def halve(text):
    """Metni ortaya en yakin yerden ikiye boler: once ortanin +-%25'indeki virgul/noktali virgul, yoksa ortaya en
    yakin bosluk. Bolunemiyorsa [metin]."""
    middle = len(text) / 2
    pool = [c for c in _cuts(text, _CLAUSE_END) if abs(c[0] - middle) <= len(text) / 4] or _cuts(text, _SPACE)
    if not pool:
        return [text]
    start, end = min(pool, key=lambda cut: abs(cut[0] - middle))
    return [text[:start].strip(), text[end:].strip()]


def bisect(text, limit):
    """Sinirdan uzun metni ortadan ikiye bolerek parcalar (ozyinelemeli); greedy paketlemenin aksine sonda tek
    kalan kisa kirintilar olmaz."""
    if len(text) <= limit:
        return [text]
    halves = halve(text)
    if len(halves) == 1:
        return halves
    return [piece for half in halves for piece in bisect(half, limit)]


_SHORT_TAIL = re.compile(r'[?!]+(["”’»)]*)\s+(?=[^\W\d_]{1,10}[.…!?]*$)')


def model_text(piece):
    """Sunucuya giden metin: soru/unlem isaretinden sonra tek kisa kelimeyle biten parcada ('degil mi? iste…') isaret
    virgule cevrilir (F166: model soruda bitirip son kelimeyi atliyordu, 24 denemede 16 -> virgulle 22; Whisper soru
    tonlamasini yine duyuyor). Kelime kucuk harfle baslamali (devam eden cumle); okuyucuda gorunen metin degismez."""
    match = _SHORT_TAIL.search(piece)
    if not match or not piece[match.end()].islower():
        return piece
    return piece[:match.start()] + ',' + match.group(1) + ' ' + piece[match.end():]


def split_text(text, limit=MAX_CHARS):
    """Metni sunucuya gidecek parcalara boler: [(parca, sonraki_sessizlik_sn)]. Ardisik cumleler sinira kadar
    tek parcada gider (F163: tek basina kalan 'dedi.', 'iste...' gibi kisa parcalari model susarak ya da
    mirildanarak okuyordu; az parca ayni zamanda az ton degisimi). Sinirdan uzun cumle ortadan, once virgul/
    noktali virgulden, o da yetmezse kelimelerden bolunur. <|speaker:N|> etiketi sonraki parcalara da tasinir."""
    text = ' '.join(str(text or '').split())
    result = []
    for sentence in _split(text, _SENTENCE_END):
        if len(sentence) > limit:
            packed = bisect(sentence, limit)
            result.extend((piece, CLAUSE_GAP) for piece in packed[:-1])
            result.append((packed[-1], SENTENCE_GAP))
        elif (result and result[-1][1] == SENTENCE_GAP and len(result[-1][0]) + 1 + len(sentence) <= limit
              and not _SPEAKER.match(sentence)):
            result[-1] = (result[-1][0] + ' ' + sentence, SENTENCE_GAP)
        else:
            result.append((sentence, SENTENCE_GAP))
    speaker = ''
    tagged = []
    for piece, gap in result:
        found = _SPEAKER.findall(piece)
        if speaker and not _SPEAKER.match(piece):
            piece = speaker + piece
        if found:
            speaker = found[-1]
        tagged.append((piece, gap))
    return tagged


# ---------------------------------------------------------------- WAV islemleri (numpy yok)
def read_pcm(data):
    """WAV bayt -> (array('h') mono ornekler, ornekleme hizi). 16 bit olmayan ya da cok kanalli WAV reddedilir."""
    with wave.open(io.BytesIO(data)) as stream:
        if stream.getsampwidth() != 2:
            raise ServerError('Drama 3 sunucusu beklenmeyen bir ses biçimi döndürdü (16 bit değil).')
        channels, rate = stream.getnchannels(), stream.getframerate()
        samples = array.array('h', stream.readframes(stream.getnframes()))
    if sys.byteorder == 'big':
        samples.byteswap()
    if channels > 1:
        samples = array.array('h', samples[::channels])
    return samples, rate


def wav_bytes(samples, rate):
    data = array.array('h', samples)
    if sys.byteorder == 'big':
        data.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(int(rate))
        stream.writeframes(data.tobytes())
    return buffer.getvalue()


def shorten_silences(samples, rate, limit=SILENCE_LIMIT, keep=SILENCE_KEEP, level=SILENCE_LEVEL):
    """`limit` saniyeden uzun sessizlikleri `keep` saniyeye indirir (yarisi basta, yarisi sonda kalir)."""
    window = max(1, int(rate * SILENCE_WINDOW))
    count = (len(samples) + window - 1) // window
    quiet = [max(map(abs, samples[i * window:(i + 1) * window]), default=0) < level for i in range(count)]
    output = array.array('h')
    head = int(rate * keep / 2)
    tail = int(rate * keep) - head
    position = index = 0
    while index < count:
        if not quiet[index]:
            index += 1
            continue
        end = index
        while end < count and quiet[end]:
            end += 1
        start, stop = index * window, min(len(samples), end * window)
        if stop - start > rate * limit:
            output.extend(samples[position:start + head])
            position = stop - tail
        index = end
    output.extend(samples[position:])
    return output


def voiced_seconds(samples, rate, level=VOICED_LEVEL):
    """Konusma suresi: tepesi `level`i asan 100 ms'lik pencerelerin toplami."""
    window = max(1, int(rate * 0.1))
    return sum(max(map(abs, samples[i:i + window])) > level for i in range(0, len(samples), window)) * window / rate


def noise_floor(samples, rate):
    """Gurultu tabani: 50 ms'lik pencere tepelerinin en sessiz %10'u (yankili/gurultulu klon seste yuksek olur)."""
    window = max(1, int(rate * 0.05))
    peaks = sorted(max(map(abs, samples[i:i + window])) for i in range(0, max(0, len(samples) - window), window))
    return peaks[len(peaks) // 10] if peaks else 0


def ends_abruptly(samples, rate, level=ABRUPT_LEVEL, floor=None):
    """Ses sessizlige inmeden mi bitiyor (son 50 ms'de konusma): model parcayi erken bitirmis, son kelime ya da hece
    eksik (F162: 'ifadeler icin [tariyorum]'). Esik sesin gurultu tabaninin 3 kati (F164: gurultulu klon seste
    parcalar bosuna yeniden isteniyordu). `floor`: klon kaydinin gurultu tabani (F167: parcanin kendisinden olculunce
    kisa ve kesintisiz konusan parcada taban konusmanin kendisi oluyor, hicbir kesilme yakalanmiyordu)."""
    tail = samples[-max(1, int(rate * 0.05)):]
    floor = noise_floor(samples, rate) if floor is None else floor
    return max(map(abs, tail), default=0) > max(level, 3 * floor)


def letters(text):
    """Okunacak harf sayisi ([laughs], <whisper> gibi etiketler ve noktalama haric)."""
    return len(re.sub(r'\[[^\]]*\]|<[^>]*>|[\W_]', '', text))


def fell_silent(text, samples, rate):
    """Model parcanin bir kismini soylemeden sustu mu: konusulan sure metne gore cok kisa, ya da ses metne gore
    cok uzun (F163: 'dedi.' icin 1,2 sn konusma + 6 sn sessizlik; kisa parcada harf orani anlamsiz)."""
    count = letters(text)
    if len(samples) / rate > OVERLONG_BASE + count / OVERLONG_LETTERS_PER_SECOND:
        return True
    voiced = voiced_seconds(samples, rate)
    if count < CHECK_MIN_LETTERS:
        # F165: kisa parcada model bazen hic konusmuyor ('Dedi.' 0,2 sn, 'Gevezeligi birak.' 0,4 sn)
        return count >= 2 and voiced < max(SHORT_MIN_VOICED, count / SHORT_LETTERS_PER_SECOND)
    return count / max(voiced, 0.05) > MAX_LETTERS_PER_SECOND


def join_clips(clips, rate):
    """[(ornekler, sonraki_sessizlik)] -> tek ornek dizisi; son parcadan sonra sessizlik eklenmez."""
    output = array.array('h')
    for number, (samples, gap) in enumerate(clips):
        output.extend(samples)
        if number < len(clips) - 1:
            output.extend(array.array('h', bytes(2 * int(rate * gap))))
    return output


def _ffmpeg(arguments, data=None):
    import media
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    result = subprocess.run([media.ffmpeg_path(), '-v', 'error', '-y', *arguments], input=data,
                            capture_output=True, creationflags=flags)
    if result.returncode != 0:
        raise RuntimeError('ffmpeg: ' + result.stderr.decode('utf-8', 'replace').strip()[-400:])
    return result.stdout


def change_speed(data, speed):
    """WAV'i perdesini degistirmeden hizlandirir/yavaslatir (ffmpeg atempo, 0.5-2.0)."""
    speed = min(2.0, max(0.5, float(speed or 1.0)))
    if abs(speed - 1.0) < 0.01:
        return data
    rate = read_pcm(data)[1]
    # boruya yazilan WAV'in basliginda uzunluk yok; ham PCM alinip yeniden sarilir
    raw = _ffmpeg(['-f', 'wav', '-i', 'pipe:0', '-filter:a', f'atempo={speed:.3f}', '-ac', '1', '-ar', str(rate),
                   '-f', 's16le', '-c:a', 'pcm_s16le', 'pipe:1'], data)
    samples = array.array('h', raw[:len(raw) // 2 * 2])
    if sys.byteorder == 'big':
        samples.byteswap()
    return wav_bytes(samples, rate)


# ---------------------------------------------------------------- klon kaydi
def fade_out(samples, rate, seconds=FADE_SECONDS):
    """Son `seconds` saniyeyi dogrusal olarak sessizlige indirir (kirpilan kayit tik sesiyle bitmesin)."""
    count = min(len(samples), int(rate * seconds))
    out = array.array('h', samples)
    for i in range(count):
        index = len(out) - count + i
        out[index] = int(out[index] * (count - 1 - i) / count)
    return out


def _cut_point(segments, limit=REFERENCE_SECONDS):
    """Whisper kelimelerinden kirpma noktasi ve o noktaya kadarki metin: tercihen `limit` icinde biten son
    cumle sonu, yoksa son kelime. Donen (saniye, metin); konusma yoksa (0, '')."""
    words = [(float(w[0]), float(w[1]), str(w[2]).strip()) for segment in segments
             for w in (segment.get('words') or [[segment.get('start', 0), segment.get('end', 0), segment.get('text', '')]])]
    words = [w for w in words if w[2]]
    inside = [i for i, w in enumerate(words) if w[1] <= limit]
    if not inside:
        return 0.0, ''
    sentence = [i for i in inside if re.search(r'[.!?…]["\'»”’)]*$', words[i][2])]
    # F164: cumle sonu yoksa kelimeler arasindaki bir duraklamada kes (son 1/3'teki en uzun bosluk): konusmanin
    # ortasinda biten referans modele de sesi birden bitirmeyi ogretiyordu
    gaps = [i for i in inside
            if i + 1 < len(words) and words[i + 1][0] - words[i][1] >= 0.2 and words[i][1] >= limit * 2 / 3]
    if sentence and words[sentence[-1]][1] >= limit / 3:
        last = sentence[-1]
    elif gaps:
        last = max(gaps, key=lambda i: words[i + 1][0] - words[i][1])
    else:
        last = inside[-1]
    end = min(limit, words[last][1] + 0.15)
    if last + 1 < len(words):
        end = min(end, max(words[last][1], words[last + 1][0]))
    return end, ' '.join(w[2] for w in words[:last + 1])


def prepare_reference(path, text, cache_dir, transcribe=None, language='tr', log=None):
    """Klon kaydini sunucuya gidecek bicime getirir: {'text', 'data' (base64 WAV), 'seconds'}.
    Kayit 44.1 kHz mono WAV'a donusturulur, en fazla REFERENCE_SECONDS. Metin verilmediyse ya da kayit
    kirpilmasi gerekiyorsa `transcribe(wav_yolu, dil)` (Whisper bolumleri) ile metin cikarilir.
    Sonuc kaydin icerigi ve metne gore onbellege alinir."""
    log = log or (lambda _message: None)
    source = Path(str(path or ''))
    if not str(path or '').strip():
        raise ValueError('Drama 3 için bir ses kaydı seçin (Ses ayarları ya da kayıtlı ses).')
    if not source.is_file():
        raise ValueError(f'Ses kaydı bulunamadı: {source}')
    text = ' '.join(str(text or '').split())
    digest = hashlib.sha1(source.read_bytes()).hexdigest()
    key = hashlib.sha1(json.dumps([REFERENCE_VERSION, digest, text, language]).encode('utf-8')).hexdigest()[:20]
    cache_dir = Path(cache_dir)
    cached_json, cached_wav = cache_dir / f'{key}.json', cache_dir / f'{key}.wav'
    try:
        meta = json.loads(cached_json.read_text(encoding='utf-8'))
        return {'text': meta['text'], 'data': base64.b64encode(cached_wav.read_bytes()).decode('ascii'),
                'seconds': meta['seconds']}
    except (OSError, ValueError, KeyError):
        pass
    cache_dir.mkdir(parents=True, exist_ok=True)
    raw = _ffmpeg(['-i', str(source), '-t', str(TRANSCRIBE_SECONDS), '-vn', '-ac', '1', '-ar', '44100',
                   '-c:a', 'pcm_s16le', '-f', 's16le', 'pipe:1'])
    samples, rate = array.array('h', raw[:len(raw) // 2 * 2]), 44100
    if sys.byteorder == 'big':
        samples.byteswap()
    full = wav_bytes(samples, rate)
    seconds = len(samples) / rate
    if seconds < 1.0:
        raise ValueError('Ses kaydı çok kısa; 8-15 saniyelik bir kayıt seçin.')
    long = seconds > REFERENCE_SECONDS + 0.05
    if text and not long:
        cut = seconds
    else:
        if transcribe is None:
            raise ValueError('Kaydın metnini yazın: Drama 3 klon kaydının tam metnini ister.' if not long else
                             'Ses kaydı 20 saniyeden uzun ve Whisper kurulu değil; kırpılan kaydın metni çıkarılamıyor. '
                             '20 saniyeden kısa bir kayıt seçip metnini yazın.')
        log('Drama 3: klon kaydının metni Whisper ile çıkarılıyor…')
        temp = cache_dir / f'{key}.16k.wav'
        try:
            _ffmpeg(['-f', 'wav', '-i', 'pipe:0', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(temp)], full)
            segments = transcribe(temp, language) or []
        finally:
            temp.unlink(missing_ok=True)
        cut, heard = _cut_point(segments, REFERENCE_SECONDS if long else seconds + 1)
        if not heard:
            raise ValueError('Ses kaydında konuşma algılanamadı.')
        if long and text:
            log('Drama 3: kayıt 20 saniyeden uzun; kırpılan bölümün metni Whisper ile çıkarıldı.')
        if not long:
            cut = seconds
        text = heard
    samples = fade_out(samples[:int(rate * min(cut, REFERENCE_SECONDS))], rate)
    data = wav_bytes(samples, rate)
    partial = cached_wav.with_suffix('.part')
    partial.write_bytes(data)
    partial.replace(cached_wav)
    cached_json.write_text(json.dumps({'text': text, 'seconds': round(len(samples) / rate, 2),
                                       'source': str(source)}, ensure_ascii=False), encoding='utf-8')
    return {'text': text, 'data': base64.b64encode(data).decode('ascii'), 'seconds': round(len(samples) / rate, 2)}


# ---------------------------------------------------------------- motor (tts.InlineWorker)
class Engine:
    """tts.InlineWorker'in cagirdigi motor: load() sesi hazirlar, say() bir metni WAV bayt olarak dondurur."""

    def __init__(self, data_dir, prefs=None, stage=None, transcribe=None, log=None):
        self.data_dir = Path(data_dir)
        self._prefs = prefs or (lambda: {})
        self._stage = stage or (lambda _message: None)
        self._transcribe = transcribe
        self._log = log or (lambda _message: None)
        self._lock = threading.Lock()
        self.reference = None
        self.floor = None      # klon kaydinin gurultu tabani (ends_abruptly esigi)
        self.voice = None

    @property
    def url(self):
        return normalize_url(self._prefs().get('drama3_url'))

    def load(self, voice, options):
        self._stage('Drama 3 sunucusu denetleniyor…')
        health(self.url)
        language = 'en' if voice.endswith('-en') else 'tr'
        reference = (options or {}).get('reference')
        if not reference:
            raise ValueError('Drama 3 için bir ses kaydı seçin (Ayarlar → Ses ya da okuyucudaki ses seçici).')
        self._stage('Klon kaydı hazırlanıyor…')
        self.reference = prepare_reference(reference, (options or {}).get('reference_text'),
                                           self.data_dir / 'kayitlar', self._transcribe, language, self._log)
        try:
            self.floor = noise_floor(*read_pcm(base64.b64decode(self.reference['data'])))
        except (ValueError, EOFError, wave.Error, ServerError):
            self.floor = None    # okunamazsa her parcanin kendi tabani
        self.voice = voice
        return {'device': 'sunucu', 'reference_text': self.reference['text'], 'reference_seconds': self.reference['seconds']}

    def settings(self):
        """Ayarlar'daki parca uzunlugu, temperature, top_p (gecersiz ya da eksikse varsayilan, sinirlara kirpilir)."""
        given = (self._prefs().get('engine_settings') or {}).get('drama3') or {}
        result = {}
        for key, (default, low, high) in SETTINGS.items():
            try:
                value = float(given[key])
            except (KeyError, TypeError, ValueError):
                value = default
            result[key] = min(high, max(low, value))
        result['max_chars'] = int(result['max_chars'])
        return result

    def _piece(self, piece, references, settings, depth=0):
        """Bir parcayi uretir: [(ornekler, hiz)]. Model cumlenin ortasinda susarsa (F160) sunucu varsayilanlariyla
        yeniden ister, hepsi susarsa en cok konusani kullanir. Ses sunucunun istek sinirina dayanmissa (kesilmis)
        parca ikiye bolunup yeniden istenir."""
        best = None
        attempts = ((settings['temperature'], settings['top_p']),) + tuple((t, None) for t in SILENT_RETRY_TEMPERATURES)
        for attempt, (temperature, top_p) in enumerate(attempts):
            samples, rate = read_pcm(speech(self.url, model_text(piece), references, temperature=temperature,
                                            top_p=top_p))
            if len(samples) / rate >= CAP_SECONDS and depth < 3:
                halves = halve(piece)
                if len(halves) > 1:
                    self._log(f'Drama 3: parça sunucunun süre sınırına takıldı, bölünüyor: {piece[:60]}')
                    return [clip for half in halves for clip in self._piece(half, references, settings, depth + 1)]
            silent, abrupt = fell_silent(piece, samples, rate), ends_abruptly(samples, rate, floor=self.floor)
            if not silent and not abrupt:
                return [(samples, rate)]
            reason = 'cümlenin bir kısmını atladı' if silent else 'parçayı erken bitirdi'
            self._log(f'Drama 3: model {reason}, yeniden deneniyor ({attempt + 1}): {piece[:60]}')
            # tercih: susmayan, sonra en cok konusan deneme
            score = (not silent, voiced_seconds(samples, rate))
            if best is None or score > best[0]:
                best = (score, (samples, rate))
        self._log(f'UYARI: Drama 3 bu parçayı tam okuyamadı: {piece[:80]}')
        return [best[1]]

    def say(self, text, speed=1.0):
        """Metni parcalara bolup sunucuda seslendirir; WAV bayt ve sure (sn) dondurur."""
        if self.reference is None:
            raise RuntimeError('Ses motoru hazır değil.')
        references = [{'text': self.reference['text'], 'data': self.reference['data']}]
        clips, rate = [], None
        settings = self.settings()
        with self._lock:     # sunucuya ayni anda tek istek (motor sureclerindeki gibi sirali)
            for piece, gap in split_text(text, settings['max_chars']):
                parts = self._piece(piece, references, settings)
                for number, (samples, piece_rate) in enumerate(parts):
                    if rate is not None and piece_rate != rate:
                        raise ServerError('Drama 3 sunucusu parçalar için farklı örnekleme hızları döndürdü.')
                    rate = piece_rate
                    clips.append((shorten_silences(samples, rate), gap if number == len(parts) - 1 else CLAUSE_GAP))
        if not clips:
            return wav_bytes(array.array('h'), 44100), 0.0
        data = change_speed(wav_bytes(join_clips(clips, rate), rate), speed)
        with wave.open(io.BytesIO(data)) as stream:
            duration = stream.getnframes() / stream.getframerate()
        return data, duration
