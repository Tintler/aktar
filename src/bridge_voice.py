"""Sesle soru sorma (F112): sohbet kutularindaki mikrofon dugmesinin arka ucu.

Arayuz mikrofonu getUserMedia ile alir, kaydi 16 kHz mono WAV'a cevirip base64 olarak
gonderir. WAV work_files/qa altina yazilir, Whisper (speech.transcribe_clip; uygulama ici
faster-whisper ya da aktar-whisper paketi) ile metne cevrilir ve hemen silinir. Ses hicbir
yere gonderilmez; metin kutuya yazilir, kullanici kendisi gonderir.
"""
from __future__ import annotations

import base64
import binascii
import threading
import uuid
from pathlib import Path

import qa
import speech
from app_core import load_config

MAX_CLIP_BYTES = 16 * 1024 * 1024   # 120 sn 16 kHz mono 16 bit ~3.8 MB; fazlasi bozuk/kotu niyetli


class VoiceMixin:
    _voice_lock = threading.Lock()

    def voice_status(self):
        """{'available', 'hint'}: Whisper yoksa dugme aciklamali devre disi kalir."""
        ok, hint = speech.available()
        return {'available': ok, 'hint': hint, 'max_seconds': speech.CLIP_MAX_SECONDS}

    def voice_transcribe(self, data):
        """base64 WAV -> {'text', 'language'} ya da {'error'}. Ayni anda tek kayit cozulur."""
        try:
            raw = base64.b64decode(str(data or ''), validate=True)
        except (binascii.Error, ValueError):
            return {'error': 'Ses kaydı bozuk.'}
        if not raw:
            return {'error': 'Ses kaydı boş.'}
        if len(raw) > MAX_CLIP_BYTES:
            return {'error': 'Ses kaydı çok uzun.'}
        if not self._voice_lock.acquire(blocking=False):
            return {'error': 'Önceki kayıt hâlâ metne çevriliyor.'}
        folder = Path(qa.work_dir()) / 'qa'
        path = folder / f'voice-{uuid.uuid4().hex[:12]}.wav'
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            cfg = load_config()
            result = speech.transcribe_clip(path, cfg['whisper_model'], cfg['whisper_device'],
                                            log=self._log, cuda_dir=cfg.get('whisper_cuda_dir', ''))
        except (OSError, RuntimeError, ValueError) as error:
            return {'error': str(error)}
        finally:
            self._voice_lock.release()
            try:
                path.unlink()
            except OSError:
                pass
        return {'text': result['text'], 'language': result['language']}
