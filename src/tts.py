"""Voice engines for read-aloud: discovery, installation and the worker processes.

An engine (EMA Lightning, Piper, …) is a separate program speaking the JSON-lines protocol in
engines/protocol.py. The user builds engine packages (DERLE_SES.cmd) and installs them from the
settings page ("Dosyadan kur"); they live next to Aktar in `ses-motorlari/<id>/` (worker.exe,
its runtime, motor.json and a data/ folder for the models and voices it fetches). When Aktar runs
from source, an engine whose Python packages are installed is started from engines/<name>/ instead,
so development needs no packaging. Which engine and voice read a book is chosen per language.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import itertools
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import threading
import time
import wave
import zipfile

ENGINES_DIR = 'ses-motorlari'
PROTOCOL = 1
SNAPSHOT_SECONDS = 2.0        # F188: how long the motor.json files read are reused (Engines._manifests)
AUDIO_RATE = 48000     # requested from engines (those that cannot choose return their own rate)
CACHE_DIR = 'ses-onbellegi'   # rendered sentences per book: ses-onbellegi/<book id>/<key>.wav
PREVIOUS_SUFFIX = '.onceki.wav'   # F205: the take a re-render replaced (<key>.onceki.wav)
SENTENCE_GAP = 0.35    # seconds of silence between sentences in an exported file
DEFAULT_ENGINE = {'tr': 'ema-lightning'}
MAX_PATH = 259
DATA_PATH_BUDGET = 70   # room for downloaded models/voices under <engine>/data
FROZEN = bool(getattr(sys, 'frozen', False))


class Cancelled(RuntimeError):
    """A long rendering (export) was stopped by its cancel event."""


def language_key(language):
    return str(language or 'tr').split('-')[0].split('_')[0].lower() or 'tr'


def _gap(gaps, index):
    """Seconds of silence after sentence `index`: the given one (clamped to 0–5 s) or SENTENCE_GAP."""
    try:
        return min(5.0, max(0.0, float(gaps[index])))
    except (IndexError, TypeError, ValueError):
        return SENTENCE_GAP


class Worker:
    """One engine process: request/response over stdin/stdout, events forwarded to `on_event`."""

    def __init__(self, engine, data, log_path, on_event):
        self.engine, self.data, self.log_path, self.on_event = engine, Path(data), Path(log_path), on_event
        self._ids = itertools.count(1)
        self._pending = {}
        self._lock = threading.Lock()
        self._write = threading.Lock()
        self._ready = threading.Event()
        self.process = None

    def start(self, timeout=60):
        self.data.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log_path, 'w', encoding='utf-8', errors='replace')
        if self.engine['mode'] == 'package':
            command, cwd = [str(Path(self.engine['dir']) / self.engine.get('entry', 'worker.exe'))], self.engine['dir']
        else:
            command, cwd = [sys.executable, '-u', '-m', self.engine['module']], self.engine['root']
        env = dict(os.environ, CEVIRGEC_ENGINE_DATA=str(self.data), PYTHONIOENCODING='utf-8')
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=log, creationflags=flags)
        finally:
            log.close()
        threading.Thread(target=self._read, name=f'engine-{self.engine["id"]}', daemon=True).start()
        if not self._ready.wait(timeout):
            self.stop()
            raise RuntimeError('Ses motoru başlatılamadı. ' + self.log_tail())

    def _read(self):
        for raw in self.process.stdout:
            try:
                message = json.loads(raw.decode('utf-8'))
            except ValueError:
                continue
            if message.get('event') == 'ready':
                if message.get('protocol') == PROTOCOL:
                    self._ready.set()
            elif 'event' in message:
                self.on_event(message)
            elif 'id' in message:
                with self._lock:
                    slot = self._pending.pop(message['id'], None)
                if slot:
                    slot['message'] = message
                    slot['done'].set()
        # The process ended: fail everything still waiting.
        with self._lock:
            pending, self._pending = self._pending, {}
        for slot in pending.values():
            slot['message'] = {'ok': False, 'error': 'Ses motoru beklenmedik biçimde kapandı. ' + self.log_tail()}
            slot['done'].set()

    def request(self, command, timeout=None, **payload):
        if not self.alive:
            raise RuntimeError('Ses motoru çalışmıyor. ' + self.log_tail())
        number = next(self._ids)
        slot = {'done': threading.Event(), 'message': None}
        with self._lock:
            self._pending[number] = slot
        line = json.dumps({'id': number, 'cmd': command, **payload}, ensure_ascii=False) + '\n'
        try:
            with self._write:
                self.process.stdin.write(line.encode('utf-8'))
                self.process.stdin.flush()
        except OSError as error:
            raise RuntimeError('Ses motoruna ulaşılamadı. ' + self.log_tail()) from error
        if not slot['done'].wait(timeout):
            with self._lock:
                self._pending.pop(number, None)
            raise RuntimeError('Ses motoru yanıt vermedi.')
        message = slot['message']
        if not message.get('ok'):
            raise RuntimeError(message.get('error') or 'Ses motoru hatası.')
        return message.get('result') or {}

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None

    def log_tail(self, lines=6):
        try:
            text = self.log_path.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            return ''
        tail = [line.strip() for line in text if line.strip()][-lines:]
        return ('Ayrıntı: ' + ' | '.join(tail))[:900] if tail else ''

    def stop(self):
        if not self.process:
            return
        if self.alive:
            try:
                with self._write:
                    self.process.stdin.write(b'{"id": 0, "cmd": "shutdown"}\n')
                    self.process.stdin.flush()
                self.process.wait(3)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if self.alive:
            self.process.kill()
            try:
                self.process.wait(3)
            except subprocess.TimeoutExpired:
                pass
        for pipe in (self.process.stdin, self.process.stdout):
            try:
                pipe.close()
            except OSError:
                pass


class InlineWorker:
    """An engine running inside Aktar (motor.json "builtin": a module under src/, e.g. drama3, a client of a
    server the user runs, or drama3_tr, which starts its own server from a model folder). Same interface as Worker; requests are plain calls, serialized like a worker's."""

    def __init__(self, engine, data, on_event, prefs=None, transcribe=None, log=None):
        self.engine, self.data = engine, Path(data)
        extra = {}
        if engine['builtin'] == 'drama3':
            import drama3 as module
        elif engine['builtin'] == 'drama3_tr':
            # F173: Aktar starts this engine's server from the model folder; the script ships in engines/<id>/
            import drama3_tr as module
            extra['script'] = Path(engine.get('root') or '.') / 'engines' / engine['id'] / module.SERVER_SCRIPT
        else:
            raise RuntimeError(f'Bilinmeyen yerleşik ses motoru: {engine["builtin"]}')
        self.impl = module.Engine(self.data, prefs=prefs, transcribe=transcribe, log=log,
                                  stage=lambda message: on_event({'event': 'stage', 'message': message}), **extra)
        self._lock = threading.Lock()
        self._stopped = False

    def start(self, timeout=60):
        self.data.mkdir(parents=True, exist_ok=True)

    def request(self, command, timeout=None, **payload):
        if self._stopped:
            raise RuntimeError('Ses motoru çalışmıyor.')
        with self._lock:
            if command == 'load':
                return self.impl.load(payload.get('voice') or '', payload.get('options') or {}) or {}
            if command == 'say':
                data, duration = self.impl.say(payload.get('text', ''), float(payload.get('speed') or 1.0),
                                               payload.get('tag') or '')
                return {'audio': base64.b64encode(data).decode('ascii'), 'duration': duration}
            if command == 'ping':
                return {}
        raise ValueError(f'Bilinmeyen komut: {command}')

    @property
    def alive(self):
        return not self._stopped

    def log_tail(self, lines=6):
        return ''

    def stop(self):
        self._stopped = True
        stop = getattr(self.impl, 'stop', None)    # F173: a server process Aktar started
        if stop:
            stop()


class Engines:
    """Lists, installs and runs voice engines; keeps at most one worker process running."""

    def __init__(self, app_dir, source_dir, emit=None, prefs=None, transcribe=None, log=None, emotion=None):
        self.app_dir, self.source_dir = Path(app_dir), Path(source_dir)
        self._emotion = emotion           # F168: (book, sentence) -> emotion tag ('' none), engines with "emotion_tags"
        self._emit = emit or (lambda _event, _data: None)
        self._prefs = prefs or (lambda: {})
        self._transcribe = transcribe     # builtin engines: (wav path, language) -> Whisper segments
        self._log = log
        self._lock = threading.RLock()
        self._worker = None
        self._loading = None
        self.state, self.message = 'idle', ''
        self.current = {'engine': None, 'voice': None, 'device': None, 'language': None}
        self._exporting = False
        self._busy = {}               # engine id -> installation progress text
        self._snapshot = None         # (time, manifests, engines list): see _manifests

    # ------------------------------------------------------------- discovery
    @property
    def install_root(self):
        return self.app_dir / ENGINES_DIR

    def _manifests(self):
        """Known engines: bundled descriptions (engines/*/motor.json) merged with installed packages.
        F188: kept for SNAPSHOT_SECONDS (read-only for callers). A chapter's plan asks for every sentence group and
        rereading the motor.json files each time took minutes for an 800-sentence chapter ("Hazirla" at 0)."""
        snapshot = self._snapshot
        if snapshot and time.monotonic() - snapshot[0] < SNAPSHOT_SECONDS:
            return snapshot[1]
        known = self._read_manifests()
        self._snapshot = (time.monotonic(), known, None)
        return known

    def _forget_manifests(self):
        self._snapshot = None

    def _read_manifests(self):
        known = {}
        for path in sorted(self.source_dir.glob('*/motor.json')):
            try:
                manifest = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            manifest['root'] = str(self.source_dir.parent)
            known[manifest['id']] = manifest
        if self.install_root.exists():
            for path in sorted(self.install_root.glob('*/motor.json')):
                try:
                    manifest = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if manifest.get('protocol') == PROTOCOL and (path.parent / manifest.get('entry', 'worker.exe')).exists():
                    merged = dict(known.get(manifest['id'], {}), **manifest)
                    merged['dir'] = str(path.parent)
                    merged['installed_version'] = manifest.get('version')
                    known[manifest['id']] = merged
        return known

    def _mode(self, manifest):
        if manifest.get('builtin'):
            return 'builtin'
        if (not FROZEN and manifest.get('module') and manifest.get('root')
                and all(importlib.util.find_spec(name) for name in manifest.get('python_modules', []))):
            return 'source'
        return 'package' if manifest.get('dir') else None

    def _data_dir(self, engine_id):
        return self.install_root / engine_id / 'data'

    def engines(self):
        manifests = self._manifests()
        snapshot = self._snapshot
        if snapshot and snapshot[1] is manifests and snapshot[2] is not None:
            return [dict(item, busy=self._busy.get(item['id'])) for item in snapshot[2]]
        result = self._list_engines(manifests)
        if snapshot and snapshot[1] is manifests:
            self._snapshot = (snapshot[0], manifests, result)
        return [dict(item) for item in result]

    def _list_engines(self, manifests):
        result = []
        for engine_id, manifest in manifests.items():
            data = self._data_dir(engine_id)
            voices = [dict(voice, downloaded=all((data / name).exists() for name in voice.get('files', [])))
                      for voice in manifest.get('voices', [])]
            result.append({
                'id': engine_id, 'name': manifest.get('name', engine_id), 'version': manifest.get('version', ''),
                'installed_version': manifest.get('installed_version'), 'description': manifest.get('description', ''),
                'license': manifest.get('license', ''), 'homepage': manifest.get('homepage', ''),
                'mode': self._mode(manifest), 'removable': bool(manifest.get('dir')), 'speed': bool(manifest.get('speed')),
                'devices': manifest.get('devices', ['cpu']), 'voices': voices,
                'languages': sorted({voice['language'] for voice in voices}),
                'busy': self._busy.get(engine_id),
                'attribution': manifest.get('attribution', ''), 'notice': manifest.get('notice', ''),
                'server': bool(manifest.get('server')), 'folder': bool(manifest.get('folder')),
                'cloud': manifest.get('cloud', ''),     # F188: motor.json cloud backend ('openrouter')
                'settings': manifest.get('settings', []),
                'emotion_tags': bool(manifest.get('emotion_tags')),
                'emotion_rich': manifest.get('emotion_tags') == 'rich',
            })
        return result

    def choice(self, language, override=None):
        """(engine, voice) for a book language: the user's choice when usable, otherwise a default.
        `override` ({'voice': '<engine>/<voice>', 'options'}) is another page's own voice (chat, dubbing);
        it wins when usable for that language."""
        key = language_key(language)
        usable = {item['id']: item for item in self.engines() if item['mode']}
        chosen = (override or {}).get('voice') or (self._prefs().get('voices') or {}).get(key) or ''
        engine_id, _, voice_id = chosen.partition('/')
        if override and not (engine_id in usable and any(v['id'] == voice_id and v['language'] == key
                                                          for v in usable[engine_id]['voices'])):
            engine_id, _, voice_id = ((self._prefs().get('voices') or {}).get(key) or '').partition('/')
        if engine_id in usable and any(v['id'] == voice_id and v['language'] == key for v in usable[engine_id]['voices']):
            return engine_id, voice_id
        # A server engine (Drama 3) is never picked by itself: it needs a server and a recording the user chose.
        for candidate in [DEFAULT_ENGINE.get(key)] + sorted(i for i in usable if not usable[i].get('server')):
            voice = next((v for v in usable.get(candidate, {}).get('voices', []) if v['language'] == key), None)
            if voice:
                return candidate, voice['id']
        return None, None

    def _voice_options(self, engine_id, voice_id, override=None):
        """The voice's settings: the override's when it names this voice, else the saved ones."""
        if override and override.get('voice') == f'{engine_id}/{voice_id}' and override.get('options') is not None:
            return dict(override['options'])
        return dict((self._prefs().get('options') or {}).get(f'{engine_id}/{voice_id}') or {})

    # ------------------------------------------------------------- status
    def status(self):
        return {'state': self.state, 'message': self.message, 'exporting': self._exporting, **self.current}

    def _set(self, state, message=''):
        self.state, self.message = state, message
        self._emit('tts', self.status())

    def _on_event(self, message):
        if message.get('event') == 'stage' and self.state == 'loading':
            self._set('loading', message.get('message', ''))

    # ------------------------------------------------------------- loading and speech
    def load(self, language, device='auto', override=None):
        """Starts (or reuses) the worker for a book language in the background; returns the status."""
        engine_id, voice_id = self.choice(language, override)
        with self._lock:
            key = language_key(language)
            if engine_id is None:
                self.current = {'engine': None, 'voice': None, 'device': None, 'language': key}
                self._set('missing', 'Bu dil için kullanılabilir bir ses motoru yok. Ayarlar → Sesli okuma bölümünden kurun.')
                return self.status()
            target = {'engine': engine_id, 'voice': voice_id, 'device': device or 'auto', 'language': key}
            options = self._voice_options(engine_id, voice_id, override)
            if self._loading and self._loading.is_alive():
                return self.status()
            same = (self._worker and self._worker.alive and self.state == 'ready'
                    and (self.current['engine'], self.current['voice']) == (engine_id, voice_id)
                    and self._requested_device == target['device'] and self._options == options
                    and self._pref_state == self._pref_tags(engine_id))
            if same:
                self.current['language'] = key
                return self.status()
            self.current = target
            self._requested_device = target['device']
            self._set('loading', 'Ses motoru başlatılıyor…')
            self._options = options
            self._pref_state = self._pref_tags(engine_id)
            self._loading = threading.Thread(target=self._load, args=(target, options), name='tts-load', daemon=True)
            self._loading.start()
        return self.status()

    _requested_device = None
    _options = None
    _pref_state = None

    def _pref_tags(self, engine_id):
        """F188: motor.json "cache_prefs" {pref: default}: prefs that differ from their default (Drama 3 TR's
        backend). They join the sentence cache key (old keys stay valid at the default) and reload the engine."""
        defaults = self._manifests().get(engine_id, {}).get('cache_prefs') or {}
        prefs = self._prefs()
        return {key: prefs[key] for key, default in defaults.items() if prefs.get(key, default) != default}

    def _load(self, target, options=None):
        try:
            manifest = self._manifests()[target['engine']]
            mode = self._mode(manifest)
            if not mode:
                raise RuntimeError('Ses motoru kurulu değil.')
            worker = self._worker
            if not (worker and worker.alive and worker.engine['id'] == target['engine']
                    and self._requested_device == target['device']):
                self.stop_worker()
                if mode == 'builtin':
                    worker = InlineWorker(dict(manifest, mode=mode), self._data_dir(target['engine']), self._on_event,
                                          self._prefs, self._transcribe, self._log)
                else:
                    worker = Worker(dict(manifest, mode=mode), self._data_dir(target['engine']),
                                    self.install_root / target['engine'] / 'worker.log', self._on_event)
                worker.start()
                self._worker = worker
            result = worker.request('load', voice=target['voice'], device=target['device'], options=options or {})
            self.current = dict(target, device=result.get('device', target['device']))
            self._set('ready', 'Hazır')
        except Exception as error:
            self._set('error', f'Ses motoru yüklenemedi: {error}')

    def _ready_worker(self):
        if self.state != 'ready' or not self._worker or not self._worker.alive:
            raise RuntimeError('Ses motoru hazır değil.')
        return self._worker

    # ------------------------------------------------------------- sentence cache
    def emotion_tag(self, book, text, language='tr', override=None):
        """F168: a book sentence's emotion tag ('' none), only for an engine whose motor.json has "emotion_tags"
        (Drama 3) and only for reading a book with its own voice (not chat or dubbing voices)."""
        if not book or override or self._emotion is None:
            return ''
        engine_id, _voice = self.choice(language)
        if not engine_id or not self._manifests().get(engine_id, {}).get('emotion_tags'):
            return ''
        return self._emotion(book, ' '.join(str(text).split())) or ''

    def _tag_for(self, book, text, language='tr', override=None, tag=None):
        """The emotion tag sent with a sentence: `tag` given by the caller (F172 dubbing, any voice of an engine with
        "emotion_tags"), else the book's tag (emotion_tag)."""
        engine_id, _voice = self.choice(language, override)
        if tag is None:
            found = self.emotion_tag(book, text, language, override)
        else:
            found = str(tag or '') if engine_id and self._manifests().get(engine_id, {}).get('emotion_tags') else ''
        return self._for_engine(engine_id, found)

    def _rich_tags(self, engine_id):
        """F187: motor.json "emotion_tags": "rich" (Drama 3 TR): etiketli cumle ve serbest yonerge oldugu gibi gider."""
        return bool(engine_id) and self._manifests().get(engine_id, {}).get('emotion_tags') == 'rich'

    def _for_engine(self, engine_id, found):
        """F187: etiketli cumle (serbest yonerge) budanmis Drama 3'e tek katalog etiketi olarak gider."""
        import drama3_tags
        if found and drama3_tags.is_markup(found) and not self._rich_tags(engine_id):
            return drama3_tags.legacy_tag(found, drama3_tags.ALL_TAGS)
        return found

    def _cache_path(self, book, text, speed, language, override=None, tag=None):
        """Where a sentence rendered with the voice chosen for `language` is kept (None: no caching)."""
        if not book or not re.fullmatch(r'[0-9a-f]{8,40}', str(book)):
            return None
        engine_id, voice_id = self.choice(language, override)
        if engine_id is None:
            return None
        emotion = self._tag_for(book, text, language, override, tag)
        options = self._voice_options(engine_id, voice_id, override)
        parts = [engine_id, voice_id, options, round(float(speed), 2), text]
        tag = self._manifests().get(engine_id, {}).get('cache_tag')   # motor.json: bump to re-render old sentences
        if tag:
            parts.append(tag)
        settings = (self._prefs().get('engine_settings') or {}).get(engine_id)   # motor.json "settings" (Drama 3)
        if settings:
            parts.append(settings)
        pref_tags = self._pref_tags(engine_id)
        if pref_tags:
            parts.append({'prefs': pref_tags})
        numbers = None
        if self._manifests().get(engine_id, {}).get('spoken_numbers'):   # F198: only sentences it rewrites re-render
            import tr_numbers
            joined = ' '.join(text) if isinstance(text, (list, tuple)) else str(text)
            if tr_numbers.spoken(joined) != joined:
                numbers = {'numbers': tr_numbers.VERSION}
        if emotion:   # motor.json "emotion_cache_tags": bump to re-render only sentences with that tag (F169)
            renew = (self._manifests().get(engine_id, {}).get('emotion_cache_tags') or {}).get(emotion)
            parts.append({'emotion': emotion, 'tag': renew} if renew else {'emotion': emotion})

        def path(parts):
            key = json.dumps(parts, sort_keys=True, ensure_ascii=False)
            return self.app_dir / CACHE_DIR / book / (hashlib.sha1(key.encode('utf-8')).hexdigest() + '.wav')

        if numbers is None:
            return path(parts)
        # F200: a sentence recorded before F198 keeps its audio (paid cloud renders are not thrown away); only a
        # sentence never recorded is read with the spoken numbers
        new, old = path(parts[:-1] + [numbers] + parts[-1:] if emotion else parts + [numbers]), path(parts)
        return old if not self._cached_file(new) and self._cached_file(old) else new

    def _request_text(self, text, book, language='tr', override=None, tag=None):
        """(text, tag) sent to the engine for one sentence or a list of consecutive sentences (F177): in a list
        each sentence carries its own book emotion tag inside the joined text. F187: in one request a style prefix
        ([öfkeyle] ...) carries over to the next sentences, so an untagged sentence after one gets a calm prefix."""
        if isinstance(text, (list, tuple)):
            parts = [' '.join(str(part).split()) for part in text]
            parts = [part for part in parts if part]
            if tag is None:
                import drama3
                import drama3_tags
                import emotion_tags
                rich = self._rich_tags(self.choice(language, override)[0])
                tagged, styled = [], False
                for part in parts:
                    found = self._tag_for(book, part, language, override, None)
                    if found:
                        part = drama3.tagged(part, found)
                        styled = rich and drama3_tags.starts_with_style(part)
                    elif styled:
                        reset = (drama3_tags.RESET_SPEECH if emotion_tags.is_speech(part)
                                 else drama3_tags.RESET_NARRATION)
                        part, styled = f'{reset} {part}', False
                    tagged.append(part)
                parts, tag = tagged, ''
            text = ' '.join(parts)
        return ' '.join(str(text).split()), tag

    @staticmethod
    def _clip(data):
        with wave.open(io.BytesIO(data)) as clip:
            duration = clip.getnframes() / clip.getframerate()
        return {'audio': base64.b64encode(data).decode('ascii'), 'duration': duration}

    def say(self, text, speed=1.0, book=None, language='tr', override=None, tag=None):
        """One sentence as base64 WAV: from the book's cache when it was rendered before, else from the engine.
        `tag`: emotion tag chosen by the caller (F172); None reads the book's own (F168).
        F177: `text` may be a list of consecutive sentences (group_chars) read in one request; each sentence keeps
        its own book emotion tag inside the joined text."""
        text, tag = self._request_text(text, book, language, override, tag)
        if not text:
            return {'audio': '', 'duration': 0.0}
        path = self._cache_path(book, text, speed, language, override, tag)
        if path is not None and path.exists():
            return dict(self._clip(path.read_bytes()), cached=True)
        worker = self._ready_worker()
        engine_id, voice_id = self.choice(language, override)
        if (self.current.get('engine'), self.current.get('voice')) != (engine_id, voice_id):
            raise RuntimeError('Ses motoru hazır değil.')
        tag = self._tag_for(book, text, language, override, tag)
        extra = {'tag': tag} if tag else {}
        result = worker.request('say', text=text, speed=float(speed), rate=AUDIO_RATE, timeout=600, **extra)
        if path is not None and result.get('audio'):
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_suffix('.part')
            partial.write_bytes(base64.b64decode(result['audio']))
            os.replace(partial, path)
        return {'audio': result.get('audio', ''), 'duration': result.get('duration', 0.0), 'cached': False}

    def group_chars(self, language='tr', override=None):
        """F177: how many characters of consecutive sentences the reader may send in one request (0: one sentence
        at a time). Only for an engine whose motor.json has "group_sentences" (Drama 3 TR: every request costs
        ~4 s however short it is); the limit is the engine's "max_chars" setting."""
        engine_id, _voice = self.choice(language, override)
        manifest = self._manifests().get(engine_id or '', {})
        if not manifest.get('group_sentences'):
            return 0
        default = next((item.get('default') for item in manifest.get('settings', []) if item.get('key') == 'max_chars'), 0)
        value = ((self._prefs().get('engine_settings') or {}).get(engine_id) or {}).get('max_chars', default)
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return int(default or 0)

    def plan(self, book, sentences, speed, language='tr', breaks=None, override=None):
        """F186: how a chapter is read, shared by "Hazirla" and the reader so both use the same cache entries:
        [[start, end, cached], ...] covering every sentence. A group already in the cache is kept (longest first,
        also a single sentence of an older sentence-by-sentence preparation); the rest
        are joined greedily up to group_chars without crossing a paragraph end (`breaks`: indices of sentences
        that end one; None: unknown, every sentence alone) or swallowing a sentence a cached group starts with."""
        texts = [' '.join(str(s).split()) for s in sentences]
        limit = self.group_chars(language, override) if breaks is not None else 0
        ends_paragraph = {int(b) for b in breaks or ()}
        known = {}

        def reach(start, chars):
            """Sentences that may follow `start` in one group of at most `chars` characters."""
            end, total = start, len(texts[start])
            while (chars > 0 and end + 1 < len(texts) and end not in ends_paragraph and texts[end + 1]
                   and total + 1 + len(texts[end + 1]) <= chars):
                end += 1
                total += 1 + len(texts[end])
            return end

        def cached_end(start):
            """Last sentence of the longest cached group starting at `start` (None: none)."""
            if start not in known:
                known[start] = None
                if texts[start]:
                    for end in range(reach(start, limit), start - 1, -1):
                        text, tag = self._request_text(texts[start] if end == start else texts[start:end + 1],
                                                       book, language, override)
                        path = self._cache_path(book, text, speed, language, override, tag)
                        if path is not None and self._cached_file(path):
                            known[start] = end
                            break
            return known[start]

        groups, start = [], 0
        while start < len(texts):
            end = cached_end(start)
            if end is not None:
                groups.append([start, end, True])
            else:
                end = start
                for following in range(start + 1, reach(start, limit) + 1):
                    if cached_end(following) is not None:
                        break
                    end = following
                groups.append([start, end, False])
            start = end + 1
        return groups

    def cached(self, book, sentences, speed, language='tr', override=None, breaks=None):
        """How many of the sentences are already rendered for this book and voice (alone or in a group)."""
        return sum(sum(1 for text in sentences[start:end + 1] if str(text).strip())
                   for start, end, ready in self.plan(book, sentences, speed, language, breaks, override) if ready)

    def with_prefs(self, prefs, shared=None):
        """F190: a read-only view of the cache as if ui.json 'tts' were `prefs` (another voice or backend), for
        counting what was prepared with it (cached/plan). It shares the worker: never load or say through it.
        `shared` ({}), passed to every view of one count, remembers the book's emotion tags and cache files."""
        import copy
        view = copy.copy(self)
        view._prefs = lambda: prefs
        if shared is not None:
            tags = shared.setdefault('tags', {})
            emotion = self._emotion

            def remembered(book, text):
                if (book, text) not in tags:
                    tags[book, text] = emotion(book, text) if emotion else ''
                return tags[book, text]

            view._emotion = remembered
            view._files = shared.setdefault('files', {})
            choices = {}
            plain_choice = view.choice

            def choice(language, override=None):   # engines() is rebuilt on every call; prefs are fixed here
                if override is not None:
                    return plain_choice(language, override)
                if language not in choices:
                    choices[language] = plain_choice(language)
                return choices[language]

            view.choice = choice
        return view

    _files = None   # F190: {book: set of cached file names} while counting other voices (with_prefs)

    def _cached_file(self, path):
        if self._files is None:
            return path.exists()
        book = path.parent.name
        if book not in self._files:
            try:
                self._files[book] = set(os.listdir(path.parent))
            except OSError:
                self._files[book] = set()
        return path.name in self._files[book]

    def voice_signature(self, language):
        """F190: what makes the cache of a language's voice differ (engine, voice, options, cache prefs)."""
        engine_id, voice_id = self.choice(language)
        if engine_id is None:
            return None
        return json.dumps([engine_id, voice_id, self._voice_options(engine_id, voice_id), self._pref_tags(engine_id)],
                          sort_keys=True, ensure_ascii=False)

    def prepare(self, book, sentences, speed, language='tr', progress=None, cancel=None, breaks=None):
        """Renders sentences into the book's cache (blocking) in the groups the reader will ask for (plan);
        already rendered ones are skipped. Progress and the result count sentences."""
        sentences = list(sentences)
        total = sum(1 for s in sentences if str(s).strip())
        done = 0
        for start, end, ready in self.plan(book, sentences, speed, language, breaks):
            if cancel is not None and cancel.is_set():
                return done
            if not ready:
                self.say(sentences[start] if end == start else sentences[start:end + 1], speed, book, language)
            count = sum(1 for s in sentences[start:end + 1] if str(s).strip())
            if count:
                done += count
                if progress:
                    progress(done, total)
        return done

    def _group_at(self, book, sentences, index, speed, language='tr', breaks=None):
        """F205: the reader's group holding sentence `index` (plan): (start, end, text, cache path)."""
        index = int(index)
        if not 0 <= index < len(sentences):
            raise ValueError('Cümle bulunamadı.')
        start, end, _ready = next(g for g in self.plan(book, sentences, speed, language, breaks) if g[0] <= index <= g[1])
        text = sentences[start] if end == start else list(sentences[start:end + 1])
        request, tag = self._request_text(text, book, language)
        return start, end, text, self._cache_path(book, request, speed, language, None, tag)

    @staticmethod
    def _previous(path):
        """F205: the take a re-render replaced, kept next to the cache entry (paid cloud audio is not thrown away)."""
        return path.with_name(path.stem + PREVIOUS_SUFFIX)

    def redo(self, book, sentences, index, speed, language='tr', breaks=None):
        """F205: renders the group holding sentence `index` again (blocking) without touching the rest of the book;
        the replaced take is kept as <key>.onceki.wav for undo_redo. Returns say()'s result with 'start'/'end'."""
        start, end, text, path = self._group_at(book, sentences, index, speed, language, breaks)
        if path is None:
            raise ValueError('Bu kitabın sesi saklanmıyor.')
        self._ready_worker()
        kept = None
        if path.exists():
            kept = path.with_suffix('.redo')
            os.replace(path, kept)
        try:
            result = self.say(text, speed, book, language)
        except BaseException:
            if kept is not None and not path.exists():
                os.replace(kept, path)
            raise
        if kept is not None:   # F200: say() may have written under the newer key; the old take sits beside it
            now = self._group_at(book, sentences, start, speed, language, breaks)[3]
            os.replace(kept, self._previous(now))
        return dict(result, start=start, end=end, previous=kept is not None)

    def has_previous(self, book, sentences, index, speed, language='tr', breaks=None):
        """F205: whether the group holding sentence `index` has a take to go back to."""
        path = self._group_at(book, sentences, index, speed, language, breaks)[3]
        return bool(path is not None and path.exists() and self._previous(path).exists())

    def undo_redo(self, book, sentences, index, speed, language='tr', breaks=None):
        """F205: swaps the group's take with the one redo replaced (calling it again swaps back)."""
        start, end, _text, path = self._group_at(book, sentences, index, speed, language, breaks)
        previous = self._previous(path) if path is not None else None
        if previous is None or not previous.exists() or not path.exists():
            raise ValueError('Bu cümle öbeğinin önceki sesi yok.')
        swap = path.with_suffix('.swap')
        os.replace(path, swap)
        os.replace(previous, path)
        os.replace(swap, previous)
        return dict(self._clip(path.read_bytes()), start=start, end=end, cached=True)

    def cache_info(self):
        root = self.app_dir / CACHE_DIR
        files = list(root.rglob('*.wav')) if root.exists() else []
        return {'files': len(files), 'bytes': sum(f.stat().st_size for f in files)}

    def clear_cache(self, book=None):
        root = self.app_dir / CACHE_DIR
        target = root / book if book and re.fullmatch(r'[0-9a-f]{8,40}', str(book)) else root
        shutil.rmtree(target, ignore_errors=True)
        return self.cache_info()

    def export(self, sentences, speed, path, progress=None, book=None, language='tr', gaps=None,
               override=None, cancel=None, breaks=None, starts=None):
        """Writes all sentences into one WAV file, reusing (and filling) the book's cache; blocking.
        `gaps` gives the seconds of silence after each sentence (default SENTENCE_GAP).
        F186: with `breaks` (paragraph ends) sentences are read in the reader's groups (plan), so prepared
        audio is used; a group is followed by its last sentence's gap.
        F207: a `starts` dict is filled with {sentence index: second it starts in the file}; inside a group the
        time is shared by character count, like the reader's highlight.
        A set `cancel` event stops it with Cancelled (the partial file is left to the caller)."""
        gaps = list(gaps or ())
        kept = [i for i, s in enumerate(sentences) if str(s).strip()]
        texts = [' '.join(str(sentences[i]).split()) for i in kept]
        if not texts:
            raise ValueError('Kaydedilecek metin yok.')
        ends = None if breaks is None else {int(b) for b in breaks}
        ends = None if ends is None else [n for n, i in enumerate(kept) if i in ends]
        self._exporting = True
        stream = None
        try:
            for start, end, _ready in self.plan(book, texts, speed, language, ends, override):
                if cancel is not None and cancel.is_set():
                    raise Cancelled('Ses kaydı durduruldu.')
                gap = _gap(gaps, kept[end])
                result = self.say(texts[start] if end == start else texts[start:end + 1], speed, book, language, override)
                with wave.open(io.BytesIO(base64.b64decode(result['audio']))) as clip:
                    if stream is None:
                        rate = clip.getframerate()
                        stream = wave.open(str(path), 'wb')
                        stream.setnchannels(1)
                        stream.setsampwidth(2)
                        stream.setframerate(rate)
                    if starts is not None:
                        begin = stream.getnframes() / float(rate)
                        length = clip.getnframes() / float(clip.getframerate())
                        sizes = [max(1, len(texts[n])) for n in range(start, end + 1)]
                        done = 0
                        for n, size in zip(range(start, end + 1), sizes):
                            starts[kept[n]] = round(begin + length * done / sum(sizes), 3)
                            done += size
                    stream.writeframes(clip.readframes(clip.getnframes()))
                    stream.writeframes(b'\x00\x00' * int(rate * gap))
                if progress:
                    progress(end + 1, len(texts))
        finally:
            if stream is not None:
                stream.close()
            self._exporting = False
        return len(texts)

    def stop_worker(self):
        worker, self._worker = self._worker, None
        if worker:
            worker.stop()

    def shutdown(self):
        self.stop_worker()

    # ------------------------------------------------------------- warm engine (F183, sidebar panel)
    def runtime(self):
        """The engine kept in memory: {'engine', 'name', 'voice', 'device', 'state', 'message', 'kind', 'pid',
        'busy'} or None. kind: 'process' (engine worker), 'server' (a model server Aktar started) or 'remote'
        (a client of the user's server: nothing of it runs here). Reads only in-memory state."""
        worker, state = self._worker, self.state
        if not (worker and worker.alive) and state != 'loading':
            return None
        engine_id, voice_id = self.current.get('engine'), self.current.get('voice')
        manifest = worker.engine if worker and worker.engine.get('id') == engine_id else self._manifests().get(engine_id, {})
        voice = next((v for v in manifest.get('voices', []) if v.get('id') == voice_id), {})
        process = getattr(worker, 'process', None)
        server = getattr(getattr(getattr(worker, 'impl', None), 'server', None), 'process', None)
        cloud = getattr(getattr(worker, 'impl', None), 'cloud', False)    # F188: Drama 3 TR on OpenRouter
        kind = 'process' if process else 'server' if server or (manifest.get('folder') and not cloud) else 'remote'
        pid = (process or server).pid if (process or server) else None
        return {'engine': engine_id, 'name': manifest.get('name', engine_id), 'voice': voice.get('name') or voice_id,
                'device': self.current.get('device'), 'state': state, 'message': self.message if state != 'ready' else '',
                'kind': kind, 'pid': pid, 'busy': self._exporting}

    def unload(self):
        """Frees the warm engine on request; the next read loads it again."""
        with self._lock:
            if self._exporting:
                raise RuntimeError('Ses kaydedilirken ses motoru boşaltılamaz.')
            if self._loading and self._loading.is_alive():
                raise RuntimeError('Ses motoru yükleniyor; yüklenince boşaltabilirsiniz.')
            self.stop_worker()
            self._set('idle', '')

    # ------------------------------------------------------------- install / remove
    def _writable_root(self):
        try:
            self.install_root.mkdir(parents=True, exist_ok=True)
            probe = self.install_root / '.yazma-denemesi'
            probe.write_text('', encoding='utf-8')
            probe.unlink()
        except OSError as error:
            raise RuntimeError(f"Program klasörüne yazılamıyor ({self.install_root}). Aktar'ı yazılabilir bir "
                               'klasöre (örneğin Belgeler) taşıyın ya da yönetici olarak çalıştırın.') from error

    def _progress(self, engine_id, message):
        if message:
            self._busy[engine_id] = message
        else:
            self._busy.pop(engine_id, None)
            self._forget_manifests()      # installed or removed: read the packages again
        self._emit('tts_engines', {'engines': self.engines()})

    def install_zip(self, path):
        """Installs an engine package: a zip with motor.json at its root or inside one top folder."""
        self._writable_root()
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if not name.endswith('/')]
            manifest_name = min((name for name in names if PurePosixPath(name).name == 'motor.json'
                                 and len(PurePosixPath(name).parts) <= 2), key=len, default=None)
            if not manifest_name:
                raise ValueError('Bu dosya bir ses motoru paketi değil (motor.json yok).')
            manifest = json.loads(archive.read(manifest_name).decode('utf-8'))
            engine_id = str(manifest.get('id', ''))
            if not engine_id or not all(c.isalnum() or c in '-_' for c in engine_id):
                raise ValueError('Paketteki motor kimliği geçersiz.')
            if manifest.get('protocol') != PROTOCOL:
                raise ValueError('Bu ses motoru paketi bu Aktar sürümüyle uyumlu değil.')
            prefix = str(PurePosixPath(manifest_name).parent)
            prefix = '' if prefix == '.' else prefix + '/'
            if prefix + manifest.get('entry', 'worker.exe') not in names:
                raise ValueError('Pakette motor programı eksik.')
            members = [name for name in names if name.startswith(prefix)]
            final = self.install_root / engine_id
            longest = max(len(str(final / name[len(prefix):])) for name in members)
            longest = max(longest, len(str(final / 'data')) + DATA_PATH_BUDGET)
            if longest > MAX_PATH:
                raise RuntimeError(f'Program klasörünün yolu bu motor için çok uzun ({len(str(self.app_dir))} karakter). '
                                   "Windows'un dosya yolu sınırı nedeniyle kurulamaz; Aktar'ı daha kısa yollu bir "
                                   'klasöre (örneğin C:\\Aktar) taşıyın.')
            staging = self.install_root / f'.{engine_id}.kur'
            shutil.rmtree(staging, ignore_errors=True)
            try:
                staging.mkdir(parents=True)
                base = staging.resolve()
                for index, name in enumerate(members):
                    target = (staging / name[len(prefix):]).resolve()
                    if base not in target.parents:
                        raise ValueError('Paket güvenli olmayan bir dosya yolu içeriyor.')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as source, open(target, 'wb') as out:
                        shutil.copyfileobj(source, out)
                    if index % 200 == 0:
                        self._progress(engine_id, f'Açılıyor… %{index * 100 // max(1, len(members))}')
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                self._progress(engine_id, None)
                raise
        with self._lock:
            if self._worker and self._worker.engine['id'] == engine_id:
                self.stop_worker()
                self._set('idle', '')
            if final.exists():
                if (final / 'data').exists():            # keep downloaded models and voices
                    shutil.move(str(final / 'data'), str(staging / 'data'))
                shutil.rmtree(final)
            staging.rename(final)
        self._progress(engine_id, None)
        return engine_id

    def remove(self, engine_id):
        folder = self.install_root / engine_id
        if not (folder / 'motor.json').exists():
            raise ValueError('Bu ses motoru paket olarak kurulu değil.')
        with self._lock:
            if self._worker and self._worker.engine['id'] == engine_id:
                self.stop_worker()
                self._set('idle', '')
            shutil.rmtree(folder)
        return self.engines()
