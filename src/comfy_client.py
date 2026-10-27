"""ComfyUI istemcisi (F197 kitap gorselleri): saf stdlib HTTP, Aktar ComfyUI'yi baslatmaz.

Kullanicinin ComfyUI'den "API formatinda" disa aktardigi is akisi sablondur; Aktar yalnizca su dugumleri doldurur
(kimlikle degil basliklarla bulunur: alt grafik kimlikleri is akisi duzenlenince degisir):
  - basligi 'Positive' olan metin dugumu: sahnenin istemi (yoksa basligi 'negative' icermeyen tek CLIPTextEncode)
  - 'PRE-PROMPT' / 'POST-PROMPT' (istege bagli): stil oneki ve sabit son ek; yoksa olumlu isteme eklenir
  - seed girdisi olan ornekleyici (KSampler, RandomNoise ...), width/height girdisi olan bos latent, SaveImage oneki
Uclar: POST /prompt kuyruga koyar, GET /history/<id> bitti mi, GET /view gorseli verir, POST /interrupt durdurur.

Karakter kimligi (F201, istege bagli ikinci is akisi, orn. Krea 2 Identity Edit): basligi 'REFERENCE' (ikinci kisi
icin istege bagli 'REFERENCE-B') olan LoadImage dugumune karakterin portresi konur; portre once POST /upload/image
ile ComfyUI'nin input klasorune yuklenir.

LoRA'li hazir tarzlar (F202): add_loras model yukleyicisinin arkasina LoraLoaderModelOnly dugumleri ekler (is akisi
degismez); dosya adi ComfyUI'nin LoRA listesinden (GET /object_info) resolve_lora ile bulunur.

RTX buyutme (F209, istege bagli): uretilen gorsel /upload/image ile geri yuklenir, Aktar'in kurdugu kucuk is akisi
(LoadImage -> RTXVideoSuperResolution -> SaveImage) buyutur; kullanicinin is akisina dokunulmaz.
"""
from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

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


def _request(url, path, body=None, timeout=30, content_type='application/json'):
    data = json.dumps(body).encode('utf-8') if body is not None and not isinstance(body, bytes) else body
    request = urllib.request.Request(url + path, data, {'Content-Type': content_type})
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


REFERENCE_TITLES = ('reference', 'reference-b')


def references(workflow):
    """Karakter portresinin konacagi LoadImage dugumleri, sirayla ('REFERENCE', 'REFERENCE-B')."""
    found = []
    for title in REFERENCE_TITLES:
        node = next((node for node in workflow.values() if _title(node) == title
                     and isinstance((node.get('inputs') or {}).get('image'), str)), None)
        if node is not None:
            found.append(node)
    return found


def describe_identity_workflow(workflow):
    """Kimlik is akisi: ana is akisinin dugumleri + 'REFERENCE' LoadImage."""
    info = describe_workflow(workflow)
    count = len(references(workflow))
    if not count:
        missing = info['missing'] + ['başlığı "REFERENCE" olan LoadImage düğümü']
        return {'ok': False, 'missing': missing, 'message': 'İş akışında eksik: ' + ', '.join(missing)}
    if info['ok']:
        info['message'] += ' · ' + ('iki kişilik referans' if count > 1 else 'tek kişilik referans')
    return info


def fill(workflow, prompt, style='', suffix='', seed=None, size=None, prefix='Aktar/kitap', images=()):
    """Sablonun doldurulmus kopyasi. PRE/POST dugumu yoksa stil ve son ek olumlu isteme eklenir. `images`: yuklenmis
    portre adlari, REFERENCE dugumlerine sirayla (fazlasi kullanilmaz)."""
    workflow = copy.deepcopy(workflow)
    found = slots(workflow)
    if found['positive'] is None or found['save'] is None:
        raise ComfyError(describe_workflow(workflow)['message'])
    if images:
        nodes = references(workflow)
        if not nodes:
            raise ComfyError(describe_identity_workflow(workflow)['message'])
        for node, name in zip(nodes, images):
            node['inputs']['image'] = name
    text = str(prompt or '').strip()
    for key, value, before in (('pre', style, True), ('post', suffix, False)):
        value = str(value or '').strip()
        node = found[key]
        if node is not None:
            node['inputs'][_text_key(node)] = value
        elif value:   # cumle sonu noktasi ikilenmesin ("stil.. sahne")
            text = (f'{value.rstrip(" .")}. {text}' if before else f'{text.rstrip(" .")}. {value}') if text else value
    found['positive']['inputs'][_text_key(found['positive'])] = text
    if seed is not None and found['sampler'] is not None:
        inputs = found['sampler']['inputs']
        inputs['seed' if isinstance(inputs.get('seed'), int) else 'noise_seed'] = int(seed) % (2 ** 63)
    if size and found['latent'] is not None:
        found['latent']['inputs']['width'], found['latent']['inputs']['height'] = int(size[0]), int(size[1])
    found['save']['inputs']['filename_prefix'] = prefix
    return workflow


# ---------------------------------------------------------------- LoRA (F202)
def _link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)


def _model_roots(workflow):
    """Modeli yukleyen dugumler: her 'model' baglantisi yukari dogru izlenir, 'model' girdisi olmayan dugumde durur
    (UNETLoader, CheckpointLoaderSimple ...). Aradaki LoRA, kimlik yamasi gibi dugumler atlanir."""
    roots = []
    for node in workflow.values():
        value = (node.get('inputs') or {}).get('model')
        seen = set()
        while _link(value) and value[0] in workflow and value[0] not in seen:
            seen.add(value[0])
            upstream = (workflow[value[0]].get('inputs') or {}).get('model')
            if not _link(upstream):
                break
            value = upstream
        if _link(value) and value[0] in workflow and value not in roots:
            roots.append(list(value))
    return roots


def add_loras(workflow, loras):
    """Is akisinin kopyasi: `loras` [(dosya, guc)] model yukleyicisinin hemen arkasina LoraLoaderModelOnly zinciri
    olarak eklenir; yukleyicinin modelini kullanan her dugum zincirin sonuna baglanir. Kullanicinin is akisinda
    degisiklik gerekmez (Power Lora Loader, kimlik LoRA'si oldugu gibi kalir)."""
    workflow = copy.deepcopy(workflow)
    if not loras:
        return workflow
    roots = _model_roots(workflow)
    if not roots:
        raise ComfyError('İş akışında model yükleyici bulunamadı; LoRA eklenemedi.')
    for number, root in enumerate(roots):
        last = root
        for index, (name, strength) in enumerate(loras):
            node_id = f'aktar-lora-{number}-{index}'
            workflow[node_id] = {'inputs': {'lora_name': name, 'strength_model': float(strength), 'model': last},
                                 'class_type': 'LoraLoaderModelOnly', '_meta': {'title': f'Aktar LoRA {index + 1}'}}
            last = [node_id, 0]
        for node_id, node in workflow.items():
            if node_id.startswith(f'aktar-lora-{number}-'):
                continue
            inputs = node.get('inputs') or {}
            for key, value in inputs.items():
                if value == root:
                    inputs[key] = list(last)
    return workflow


def lora_names(url):
    """ComfyUI'nin gordugu LoRA dosyalari (GET /object_info/LoraLoaderModelOnly)."""
    data = _json(normalize_url(url), '/object_info/LoraLoaderModelOnly', timeout=10)
    spec = (((data.get('LoraLoaderModelOnly') or {}).get('input') or {}).get('required') or {}).get('lora_name')
    if isinstance(spec, list) and spec and isinstance(spec[0], list):
        return [str(name) for name in spec[0]]
    if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict):   # yeni bicim: ["COMBO", {options}]
        return [str(name) for name in spec[1].get('options') or ()]
    raise ComfyError('ComfyUI LoRA listesini vermedi.')


def _lora_key(name):
    stem = str(name).replace('\\', '/').rsplit('/', 1)[-1]
    stem = stem[:-len('.safetensors')] if stem.lower().endswith('.safetensors') else stem
    return ''.join(ch for ch in stem.lower() if ch.isalnum())


def resolve_lora(available, wanted):
    """`wanted` dosyasinin ComfyUI'deki adi (alt klasor dahil); bulunamazsa None. Once birebir, sonra alt klasorsuz,
    en son buyuk/kucuk harf ve isaretler yok sayilarak (indirirken adi degisen dosya)."""
    if wanted in available:
        return wanted
    key = _lora_key(wanted)
    for match in (lambda name: name.replace('\\', '/').rsplit('/', 1)[-1] == wanted,
                  lambda name: _lora_key(name) == key):
        found = [name for name in available if match(name)]
        if found:
            return found[0]
    return None


# ---------------------------------------------------------------- RTX buyutme (F209)
UPSCALE_NODE = 'RTXVideoSuperResolution'   # Comfy-Org/Nvidia_RTX_Nodes_ComfyUI (yalnizca NVIDIA RTX)
UPSCALE_MISSING = ('ComfyUI\'de "RTX Video Super Resolution" düğümü yok: ComfyUI Manager\'dan "Nvidia RTX Nodes" '
                   '(Comfy-Org/Nvidia_RTX_Nodes_ComfyUI) eklentisini kurup ComfyUI\'yi yeniden başlatın. '
                   'Yalnızca NVIDIA RTX ekran kartlarında çalışır.')


def has_node(url, class_type):
    """ComfyUI'de bu dugum turu var mi (GET /object_info/<tur>; yoksa bos nesne ya da 404)."""
    try:
        data = _json(normalize_url(url), '/object_info/' + urllib.parse.quote(class_type), timeout=10)
    except ComfyError as error:
        if 'HTTP 404' in str(error):
            return False
        raise
    return isinstance(data, dict) and class_type in data


def upscale_workflow(image, scale, prefix='Aktar/buyutme'):
    """Yuklenmis gorseli RTX Video Super Resolution ile `scale` kat buyuten is akisi (kullanicinin is akisindan
    bagimsiz; DynamicCombo alt girdisi API'de 'resize_type.scale')."""
    return {
        '1': {'inputs': {'image': image}, 'class_type': 'LoadImage', '_meta': {'title': 'Aktar buyutme kaynagi'}},
        '2': {'inputs': {'images': ['1', 0], 'resize_type': 'scale by multiplier',
                         'resize_type.scale': round(min(4.0, max(1.0, float(scale))), 2), 'quality': 'ULTRA',
                         'strength': 1.0, 'image_encoding': '8-bit RGB'},
              'class_type': UPSCALE_NODE, '_meta': {'title': 'RTX Video Super Resolution'}},
        '3': {'inputs': {'filename_prefix': prefix, 'images': ['2', 0]}, 'class_type': 'SaveImage',
              '_meta': {'title': 'Save Image'}},
    }


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
            # is akisinda PreviewImage varsa onun gecici ('temp') ciktisi once gelebilir: SaveImage'inki ('output') alinir
            image = next((item for item in images if item.get('type') == 'output'), images[0])
            query = urllib.parse.urlencode({key: image.get(key, '') for key in ('filename', 'subfolder', 'type')})
            return _request(url, '/view?' + query, timeout=60)
        if time.monotonic() > deadline:
            interrupt(url, prompt_id)
            raise ComfyError(f'ComfyUI {timeout} saniyede görseli bitirmedi.')


def upload_image(url, data, name):
    """POST /upload/image (ayni adli dosyanin ustune yazar); LoadImage'in bekledigi adi doner."""
    boundary = uuid.uuid4().hex
    safe = ''.join(ch for ch in str(name) if ch.isalnum() or ch in '-_.') or 'aktar.png'
    body = b''.join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{safe}"\r\n'
        f'Content-Type: image/png\r\n\r\n'.encode(), data,
        f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'
        f'--{boundary}--\r\n'.encode()])
    try:
        info = json.loads(_request(normalize_url(url), '/upload/image', body, timeout=60,
                                   content_type=f'multipart/form-data; boundary={boundary}').decode('utf-8'))
    except ValueError:
        raise ComfyError('ComfyUI portreyi yüklemedi.') from None
    if not isinstance(info, dict) or not info.get('name'):
        raise ComfyError('ComfyUI portreyi yüklemedi.')
    return f'{info["subfolder"]}/{info["name"]}' if info.get('subfolder') else info['name']


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
