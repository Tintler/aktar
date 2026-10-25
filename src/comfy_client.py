"""ComfyUI istemcisi (F197 kitap gorselleri): saf stdlib HTTP, Aktar ComfyUI'yi baslatmaz.

Kullanicinin ComfyUI'den "API formatinda" disa aktardigi is akisi sablondur; Aktar yalnizca su dugumleri doldurur
(kimlikle degil basliklarla bulunur: alt grafik kimlikleri is akisi duzenlenince degisir):
  - basligi 'Positive' olan metin dugumu: sahnenin istemi (yoksa basligi 'negative' icermeyen tek CLIPTextEncode)
  - 'PRE-PROMPT' / 'POST-PROMPT' (istege bagli): stil oneki ve sabit son ek; yoksa olumlu isteme eklenir
  - seed girdisi olan ornekleyici (KSampler, RandomNoise ...), width/height girdisi olan bos latent, SaveImage oneki
Uclar: POST /prompt kuyruga koyar, GET /history/<id> bitti mi, GET /view gorseli verir, POST /interrupt durdurur.
"""
from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = 'http://127.0.0.1:8188'
TEXT_INPUTS = ('positive', 'text', 'prompt', 'string', 'value')
POLL = 1.0
TIMEOUT = 600   # tek gorselin en uzun suresi (sn); ilk istekte model yuklenir


class ComfyError(RuntimeError):
    """ComfyUI'ye ulasilamadi ya da is akisi uygun degil."""


class Cancelled(RuntimeError):
    """Kullanici uretimi durdurdu."""


def normalize_url(url):
    url = str(url or '').strip().rstrip('/') or DEFAULT_URL
    if '://' not in url:
        url = 'http://' + url
    return url


def _request(url, path, body=None, timeout=30):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    request = urllib.request.Request(url + path, data, {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode('utf-8', 'replace'))
        except ValueError:
            detail = {}
        finally:
            error.close()
        raise ComfyError(_describe(detail) or f'ComfyUI hata verdi (HTTP {error.code}).') from None
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, 'reason', error)
        raise ComfyError(f'ComfyUI\'ye bağlanılamadı ({url}): {reason}. ComfyUI açık mı?') from None


def _json(url, path, body=None, timeout=30):
    try:
        return json.loads(_request(url, path, body, timeout).decode('utf-8'))
    except ValueError:
        raise ComfyError('ComfyUI anlaşılmayan bir yanıt verdi.') from None


def _describe(detail):
    """/prompt hata yanitindan okunur mesaj (eksik dugum, model dosyasi ...)."""
    if not isinstance(detail, dict):
        return ''
    error = detail.get('error')
    parts = []
    if isinstance(error, dict):
        parts.append(str(error.get('message') or '').strip())
        if error.get('details'):
            parts.append(str(error['details']).strip())
    for node in (detail.get('node_errors') or {}).values():
        for item in (node or {}).get('errors') or ():
            text = ' '.join(str(item.get(key) or '') for key in ('message', 'details')).strip()
            if text:
                parts.append(f'{node.get("class_type", "")}: {text}')
    return ' · '.join(dict.fromkeys(part for part in parts if part))


# ---------------------------------------------------------------- is akisi
def load_workflow(text):
    """API formatindaki is akisi (dict). Arayuz formati (nodes/links) reddedilir."""
    try:
        data = json.loads(text) if isinstance(text, (str, bytes)) else text
    except ValueError:
        raise ComfyError('İş akışı dosyası JSON değil.') from None
    if not isinstance(data, dict) or 'nodes' in data or not data:
        raise ComfyError('İş akışı API formatında değil: ComfyUI\'de "Export (API)" ile dışa aktarın.')
    if not all(isinstance(node, dict) and 'class_type' in node for node in data.values()):
        raise ComfyError('İş akışı API formatında değil: ComfyUI\'de "Export (API)" ile dışa aktarın.')
    return data


def _title(node):
    return str((node.get('_meta') or {}).get('title') or '').strip().lower()


def _text_key(node):
    inputs = node.get('inputs') or {}
    return next((key for key in TEXT_INPUTS if isinstance(inputs.get(key), str)), None)


def _titled(workflow, *titles):
    for node in workflow.values():
        if _title(node) in titles and _text_key(node):
            return node
    return None


def slots(workflow):
    """Doldurulacak dugumler: {'positive', 'pre', 'post', 'sampler', 'latent', 'save'} (bulunamayan None)."""
    positive = _titled(workflow, 'positive', 'positive prompt', 'prompt')
    if positive is None:
        plain = [node for node in workflow.values() if node.get('class_type') == 'CLIPTextEncode'
                 and isinstance((node.get('inputs') or {}).get('text'), str) and 'negative' not in _title(node)]
        positive = plain[0] if len(plain) == 1 else None
    sampler = next((node for node in workflow.values()
                    if any(isinstance((node.get('inputs') or {}).get(key), int) for key in ('seed', 'noise_seed'))), None)
    latent = next((node for node in workflow.values() if 'latent' in node.get('class_type', '').lower()
                   and isinstance((node.get('inputs') or {}).get('width'), int)), None)
    save = next((node for node in workflow.values() if node.get('class_type') == 'SaveImage'), None)
    return {'positive': positive, 'pre': _titled(workflow, 'pre-prompt', 'pre prompt'),
            'post': _titled(workflow, 'post-prompt', 'post prompt'), 'sampler': sampler, 'latent': latent, 'save': save}


def describe_workflow(workflow):
    """Ayarlar'daki denetim icin: {'ok', 'missing': [...], 'message'}."""
    found = slots(workflow)
    missing = []
    if found['positive'] is None:
        missing.append('başlığı "Positive" olan istem düğümü')
    if found['save'] is None:
        missing.append('SaveImage düğümü')
    extras = [label for key, label in (('pre', 'PRE-PROMPT'), ('post', 'POST-PROMPT'), ('sampler', 'seed'),
                                       ('latent', 'boyut')) if found[key] is not None]
    message = ('İş akışı uygun' + (f' · doldurulacak: istem, {", ".join(extras)}' if extras else '')
               if not missing else 'İş akışında eksik: ' + ', '.join(missing))
    return {'ok': not missing, 'missing': missing, 'message': message}


def fill(workflow, prompt, style='', suffix='', seed=None, size=None, prefix='Aktar/kitap'):
    """Sablonun doldurulmus kopyasi. PRE/POST dugumu yoksa stil ve son ek olumlu isteme eklenir."""
    workflow = copy.deepcopy(workflow)
    found = slots(workflow)
    if found['positive'] is None or found['save'] is None:
        raise ComfyError(describe_workflow(workflow)['message'])
    text = str(prompt or '').strip()
    for key, value, before in (('pre', style, True), ('post', suffix, False)):
        value = str(value or '').strip()
        node = found[key]
        if node is not None:
            node['inputs'][_text_key(node)] = value
        elif value:
            text = f'{value}. {text}' if before else f'{text}. {value}'
    found['positive']['inputs'][_text_key(found['positive'])] = text
    if seed is not None and found['sampler'] is not None:
        inputs = found['sampler']['inputs']
        inputs['seed' if isinstance(inputs.get('seed'), int) else 'noise_seed'] = int(seed) % (2 ** 63)
    if size and found['latent'] is not None:
        found['latent']['inputs']['width'], found['latent']['inputs']['height'] = int(size[0]), int(size[1])
    found['save']['inputs']['filename_prefix'] = prefix
    return workflow


# ---------------------------------------------------------------- sunucu
def health(url):
    """GET /system_stats: {'ok', 'url', 'message'}; ulasilamazsa ComfyError."""
    url = normalize_url(url)
    data = _json(url, '/system_stats', timeout=5)
    devices = [device.get('name', '') for device in data.get('devices') or () if isinstance(device, dict)]
    version = (data.get('system') or {}).get('comfyui_version') or ''
    detail = ' · '.join(part for part in (f'ComfyUI {version}' if version else 'ComfyUI', devices[0] if devices else '') if part)
    return {'ok': True, 'url': url, 'message': f'{detail} çalışıyor ({url})'}


def generate(url, workflow, cancel=None, timeout=TIMEOUT):
    """Doldurulmus is akisini calistirir, ilk gorselin baytlarini dondurur. `cancel` (threading.Event) kurulursa
    ComfyUI'deki is durdurulur ve Cancelled."""
    url = normalize_url(url)
    queued = _json(url, '/prompt', {'prompt': workflow})
    prompt_id = queued.get('prompt_id')
    if not prompt_id:
        raise ComfyError(_describe(queued) or 'ComfyUI işi kuyruğa almadı.')
    deadline = time.monotonic() + timeout
    while True:
        if cancel is not None and cancel.wait(POLL):
            interrupt(url, prompt_id)
            raise Cancelled('Görsel üretimi durduruldu.')
        if cancel is None:
            time.sleep(POLL)
        entry = _json(url, '/history/' + urllib.parse.quote(prompt_id)).get(prompt_id)
        status = (entry or {}).get('status') or {}
        if status.get('status_str') == 'error':
            messages = [item[1].get('exception_message', '') for item in status.get('messages') or ()
                        if isinstance(item, list) and len(item) > 1 and item[0] == 'execution_error']
            raise ComfyError('ComfyUI görseli üretemedi: ' + (' · '.join(m for m in messages if m) or 'bilinmeyen hata'))
        if entry and status.get('completed', True) and entry.get('outputs'):
            images = [image for output in entry['outputs'].values() for image in (output or {}).get('images') or ()]
            if not images:
                raise ComfyError('ComfyUI görsel çıktısı vermedi (SaveImage düğümü bağlı mı?).')
            image = images[0]
            query = urllib.parse.urlencode({key: image.get(key, '') for key in ('filename', 'subfolder', 'type')})
            return _request(url, '/view?' + query, timeout=60)
        if time.monotonic() > deadline:
            interrupt(url, prompt_id)
            raise ComfyError(f'ComfyUI {timeout} saniyede görseli bitirmedi.')


def free(url):
    """POST /free: ComfyUI modelleri bellekten bosaltir (dil modeli ayni GPU'ya yuklenmeden once); hata yutulur."""
    try:
        _request(normalize_url(url), '/free', {'unload_models': True, 'free_memory': True}, timeout=10)
        return True
    except ComfyError:
        return False


def interrupt(url, prompt_id=None):
    """Calisan isi durdurur, kuyruktaysa siler (hata yutulur)."""
    url = normalize_url(url)
    for path, body in (('/interrupt', {'prompt_id': prompt_id} if prompt_id else {}),
                       ('/queue', {'delete': [prompt_id]} if prompt_id else None)):
        if body is None:
            continue
        try:
            _request(url, path, body, timeout=5)
        except ComfyError:
            pass
