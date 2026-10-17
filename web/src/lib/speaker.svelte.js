// Sohbet sesli modu (F141): model cevabini sesli okuma motoruyla cumle cumle okur. Okuyucunun oynaticisindan
// (player.svelte.js) ayridir; ses Ayarlar → Ses → "Sohbet sesi" (ui.json tts.chat_voice) ile secilir.
// Sesler onbellege yazilmaz (book: null). F142: streamSpeaker cevap uretilirken tamamlanan cumleleri okur.
import { call } from './api.js';
import { app } from './state.svelte.js';

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
    .replace(/\[[^\]\n]{1,40}\]/g, '')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/<[^>]+>/g, '')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s*>\s?/gm, '')
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/gm, '')
    .replace(/^\s*[-*_]{3,}\s*$/gm, '')
    .replace(/(\*\*|__|\*|_|~~|`)/g, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/ +([.,!?;:…])/g, '$1')
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
export function speak(text) {
  const stream = streamSpeaker();
  stream.finish(text);
  return stream.done;
}

/** F142: cevap uretilirken okur. update(akan ham metin) tamamlanan cumleleri sirasiyla kuyruga ekler (son,
 * yarim kalabilecek parca beklenir); finish(son duz metin) kalanini ekler. done: bitince true, durdurulunca false. */
export function streamSpeaker() {
  stopSpeaking();
  const token = generation;
  const voice = voiceRef(), rate = speed();
  const clips = [];
  let queued = 0, finished = false;
  speaker.message = '';

  const add = (sentences) => {
    for (const sentence of sentences.slice(queued)) {
      const clip = call('tts_say', sentence, rate, null, 'tr', voice).then((result) => {
        if (!result || result.error) throw new Error(result?.error ?? 'Ses üretilemedi.');
        return result.audio ? decode(result.audio) : null;
      });
      clip.catch(() => {});
      clips.push(clip);
    }
    queued = Math.max(queued, sentences.length);
    wake?.();
  };

  const done = (async () => {
    context ??= new AudioContext();
    if (context.state === 'suspended') await context.resume();
    let index = 0;
    try {
      while (token === generation) {
        if (index < clips.length) {
          const buffer = await clips[index++];
          if (token !== generation) return false;
          speaker.speaking = true;
          if (buffer) await playBuffer(buffer);
        } else if (finished) {
          return true;
        } else {
          await new Promise((resolve) => { wake = resolve; });
          wake = null;
        }
      }
      return false;
    } catch (error) {
      speaker.message = error.message;
      return false;
    } finally {
      if (token === generation) { speaker.speaking = false; source = null; }
    }
  })();

  return {
    done,
    update(raw) {
      if (finished || token !== generation) return;
      add(splitSentences(speechText(raw)).slice(0, -1));
    },
    finish(text) {
      if (finished || token !== generation) return;
      add(splitSentences(text));
      finished = true;
      wake?.();
    },
  };
}

function playBuffer(buffer) {
  return new Promise((resolve) => {
    source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    source.onended = resolve;
    stopWaiter = resolve;
    source.start();
  }).finally(() => { stopWaiter = null; });
}

let wake = null;
let stopWaiter = null;

export function stopSpeaking() {
  generation++;
  stopSource();
  stopWaiter?.();
  stopWaiter = null;
  wake?.();
  speaker.speaking = false;
}
