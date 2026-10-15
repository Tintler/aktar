// Sesle soru (F112): mikrofon kaydi -> 16 kHz mono WAV -> Python'da yerel Whisper -> metin.
// MediaRecorder yerine ham PCM alinir: WebView2 ve WebKitGTK'de ayni calisir, ffmpeg gerekmez.
import { call } from './api.js';

export const CLIP_RATE = 16000;
let status;

/** {available, hint, max_seconds}: Whisper yoksa ya da tarayici mikrofon vermiyorsa aciklama. */
export function voiceStatus() {
  status ??= (async () => {
    if (!navigator.mediaDevices?.getUserMedia || !(window.AudioContext || window.webkitAudioContext)) {
      return { available: false, hint: 'Bu pencere mikrofona erişemiyor.', max_seconds: 120 };
    }
    try {
      return await call('voice_status');
    } catch {
      return { available: false, hint: 'Sesle soru kullanılamıyor.', max_seconds: 120 };
    }
  })();
  return status;
}

export function downsample(samples, fromRate, toRate = CLIP_RATE) {
  if (fromRate === toRate) return samples;
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    // Pencere ortalamasi: basit bir alcak geciren suzgec (cinlama olmasin).
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    out[i] = end > start ? sum / (end - start) : 0;
  }
  return out;
}

export function encodeWav(samples, rate = CLIP_RATE) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset, value) => [...value].forEach((ch, i) => view.setUint8(offset + i, ch.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE');
  text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buffer);
}

function toBase64(bytes) {
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** Kaydi baslatir; {stop(): Promise<base64 WAV>, cancel(), level()} dondurur. */
export async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  const source = ctx.createMediaStreamSource(stream);
  const node = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  let peak = 0;
  node.onaudioprocess = (event) => {
    const data = event.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(data));
    let max = 0;
    for (let i = 0; i < data.length; i++) max = Math.max(max, Math.abs(data[i]));
    peak = max;
  };
  source.connect(node);
  node.connect(ctx.destination); // ScriptProcessor ancak bir hedefe bagliyken calisir (cikis sessiz)
  const release = () => {
    node.onaudioprocess = null;
    try { source.disconnect(); node.disconnect(); } catch { /* zaten kopuk */ }
    stream.getTracks().forEach((track) => track.stop());
    ctx.close().catch(() => {});
  };
  return {
    level: () => peak,
    cancel: release,
    async stop() {
      const rate = ctx.sampleRate;
      release();
      const total = chunks.reduce((n, c) => n + c.length, 0);
      const all = new Float32Array(total);
      let offset = 0;
      for (const c of chunks) { all.set(c, offset); offset += c.length; }
      return toBase64(encodeWav(downsample(all, rate)));
    },
  };
}

/** Var olan metnin sonuna bosluklu ekler. */
export function appendText(current, addition) {
  const base = (current ?? '').trimEnd();
  return base ? `${base} ${addition}` : addition;
}
