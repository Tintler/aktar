// Sohbet sesli modu (F141): model cevabini sesli okuma motoruyla cumle cumle okur. Okuyucunun oynaticisindan
// (player.svelte.js) ayridir; ses Ayarlar → Ses → "Sohbet sesi" (ui.json tts.chat_voice) ile secilir.
// Sesler onbellege yazilmaz (book: null).
import { call } from './api.js';
import { app } from './state.svelte.js';

const PREFETCH = 2;
const MAX_SENTENCE = 280;

export const speaker = $state({ speaking: false, loading: false, message: '' });

let context = null;
let source = null;
let generation = 0;

const voiceRef = () => app.ttsPrefs.chat_voice ?? '';
const speed = () => Number(app.ttsPrefs.chat_speed ?? 1) || 1;

/** Markdown cevaptan okunacak duz metin: kod/grafik bloklari, tablolar, baglanti adresleri ve isaretler atilir. */
export function speechText(markdown) {
  return String(markdown ?? '')
    .replace(/```[\s\S]*?(```|$)/g, '\n')
    .replace(/^\s*\|.*\|\s*$/gm, '')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/<[^>]+>/g, '')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s*>\s?/gm, '')
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/gm, '')
    .replace(/^\s*[-*_]{3,}\s*$/gm, '')
    .replace(/(\*\*|__|\*|_|~~|`)/g, '')
    .replace(/[ \t]+/g, ' ')
    .trim();
}

/** Satir ve cumle sonlarindan boler; cok uzun cumleler virgullerden bolunur. */
export function splitSentences(text) {
  const result = [];
  for (const line of String(text).split(/\n+/)) {
    for (const sentence of line.split(/(?<=[.!?…:;])\s+(?=\S)/)) {
      let rest = sentence.trim();
      while (rest.length > MAX_SENTENCE) {
        const cut = Math.max(rest.lastIndexOf(', ', MAX_SENTENCE), rest.lastIndexOf(' ', MAX_SENTENCE));
        const at = cut > 40 ? cut + 1 : MAX_SENTENCE;
        result.push(rest.slice(0, at).trim());
        rest = rest.slice(at).trim();
      }
      if (/[\p{L}\p{N}]/u.test(rest)) result.push(rest);
    }
  }
  return result;
}

/** Cevap kaydindaki duz metin (atiflar atlanir). */
export function entryText(entry) {
  if (!entry) return '';
  if (entry.kind === 'error') return entry.text ?? '';
  return speechText((entry.parts ?? []).filter((p) => p.type !== 'cite').map((p) => p.text ?? '').join(''));
}

/** Sohbet sesinin motorunu hazirlar; hazir degilse aciklamayla false. */
export async function ensureVoice() {
  speaker.loading = true;
  try {
    let status = await call('tts_load', null, voiceRef());
    while (status?.state === 'loading') {
      speaker.message = status.message || 'Ses motoru hazırlanıyor…';
      await new Promise((r) => setTimeout(r, 250));
      status = await call('tts_status');
    }
    if (status) app.tts = status;
    speaker.message = status?.state === 'ready' ? '' : (status?.message || 'Ses motoru yüklenemedi.');
    return status?.state === 'ready';
  } finally {
    speaker.loading = false;
  }
}

function decode(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return context.decodeAudioData(bytes.buffer);
}

function stopSource() {
  if (source) {
    source.onended = null;
    try { source.stop(); } catch { /* bitmis */ }
    source.disconnect();
    source = null;
  }
}

/** Metni okur; bitince (ya da durdurulunca) cozulur. Donen: true tamamlandi, false durduruldu/hata. */
export async function speak(text) {
  const sentences = splitSentences(text);
  const token = ++generation;
  stopSource();
  if (!sentences.length) return true;
  context ??= new AudioContext();
  if (context.state === 'suspended') await context.resume();
  speaker.speaking = true;
  const voice = voiceRef(), rate = speed();
  const pending = new Map();
  const fetch = (i) => {
    if (i >= sentences.length) return null;
    if (!pending.has(i)) {
      pending.set(i, call('tts_say', sentences[i], rate, null, 'tr', voice).then((result) => {
        if (!result || result.error) throw new Error(result?.error ?? 'Ses üretilemedi.');
        return result.audio ? decode(result.audio) : null;
      }));
      pending.get(i).catch(() => {});
    }
    return pending.get(i);
  };
  try {
    for (let i = 0; i < sentences.length; i++) {
      const buffer = await fetch(i);
      for (let j = i + 1; j <= i + PREFETCH; j++) fetch(j);
      if (token !== generation) return false;
      if (!buffer) continue;
      await new Promise((resolve) => {
        source = context.createBufferSource();
        source.buffer = buffer;
        source.connect(context.destination);
        source.onended = resolve;
        source.start();
        stopWaiter = resolve;
      });
      stopWaiter = null;
      if (token !== generation) return false;
    }
    return true;
  } catch (error) {
    speaker.message = error.message;
    return false;
  } finally {
    if (token === generation) { speaker.speaking = false; source = null; }
  }
}

let stopWaiter = null;

export function stopSpeaking() {
  generation++;
  stopSource();
  stopWaiter?.();
  stopWaiter = null;
  speaker.speaking = false;
}
