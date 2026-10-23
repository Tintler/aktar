// Read-aloud player: asks the back end (EMA Lightning) for one sentence at a time, plays it with
// the Web Audio API and prefetches the next sentences so speech flows without gaps.
// F177: an engine with a fixed cost per request (Drama 3 TR) reads consecutive sentences of a paragraph in one
// request (tts_group_chars); the highlight moves through the group in proportion to its characters.
import { call } from './api.js';
import { PAUSE_DEFAULTS, pauseAfter } from './pauses.js';

const PREFETCH = 2;

export const player = $state({
  active: false,     // a reading session exists (playing or paused)
  playing: false,
  waiting: false,    // the current sentence is still being synthesised
  index: -1,
  total: 0,
  speed: 1,
});

let sentences = [];
let breaks = new Set();   // indices of sentences that end a paragraph
let pauses = { ...PAUSE_DEFAULTS };
let scope = { book: null, language: 'tr' };   // where rendered sentences are cached
let groupChars = 0;       // F177: 0 = one sentence per request
let prepared = [];        // F185: sentences already in the cache on their own (tts_cached_flags)
let context = null;
let source = null;
let follow = null;        // interval moving the highlight through a group
let currentEnd = -1;      // last sentence of the group being played
let generation = 0;
const cache = new Map();
const hooks = { onsentence: () => {}, onend: () => {}, onerror: () => {} };

export function setHooks(next) {
  Object.assign(hooks, next);
}

export function setSentences(list, where = {}) {
  sentences = list;
  breaks = where.breaks ?? new Set();
  scope = { book: where.book ?? null, language: where.language || 'tr' };
  player.total = list.length;
  prepared = [];
  cache.clear();
}

// Silence after each sentence; read when a sentence starts, so changes apply from the next one.
export function setPauses(next) {
  pauses = next;
}

// Last sentence read together with `index`: following sentences of the same paragraph while they fit.
// F185: a sentence prepared ("Hazırla" renders one at a time) is read alone from the cache, never in a group.
function groupEnd(index) {
  let end = index;
  if (groupChars <= 0 || prepared[index]) return end;
  let chars = sentences[index].length;
  while (end + 1 < sentences.length && !breaks.has(end) && !prepared[end + 1]
         && chars + 1 + sentences[end + 1].length <= groupChars) {
    end++;
    chars += 1 + sentences[end].length;
  }
  return end;
}

// The sentence followed by its pause: the next one starts when this buffer ends, so pausing and
// resuming inside the silence works like anywhere else.
function withPause(buffer, index) {
  const extra = Math.round(pauseAfter(sentences[index], breaks.has(index), pauses, player.speed) * buffer.sampleRate);
  if (extra <= 0) return buffer;
  const padded = context.createBuffer(buffer.numberOfChannels, buffer.length + extra, buffer.sampleRate);
  for (let channel = 0; channel < buffer.numberOfChannels; channel++) padded.copyToChannel(buffer.getChannelData(channel), channel);
  return padded;
}

function base64Buffer(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function fetchSentence(index) {
  const end = groupEnd(index);
  const key = `${index}-${end}@${player.speed}`;
  if (!cache.has(key)) {
    const text = end > index ? sentences.slice(index, end + 1) : sentences[index];
    const promise = call('tts_say', text, player.speed, scope.book, scope.language).then(async (result) => {
      if (!result || result.error) throw new Error(result?.error ?? 'Ses üretilemedi.');
      if (!result.audio) return null;
      return context.decodeAudioData(base64Buffer(result.audio));
    });
    promise.catch(() => cache.delete(key));
    cache.set(key, promise);
  }
  return cache.get(key);
}

function prefetchAfter(end) {
  for (let next = end + 1, count = 0; next < sentences.length && count < PREFETCH; count++) {
    fetchSentence(next);
    next = groupEnd(next) + 1;
  }
}

function stopSource() {
  clearInterval(follow);
  follow = null;
  if (source) {
    source.onended = null;
    try { source.stop(); } catch { /* already stopped */ }
    source.disconnect();
    source = null;
  }
}

// Highlight inside a group: each sentence starts at its share of the characters (AudioContext time stops
// while paused, so the highlight pauses too).
function followGroup(index, end, duration, token) {
  if (end <= index) return;
  const lengths = sentences.slice(index, end + 1).map((s) => s.length);
  const total = lengths.reduce((a, b) => a + b, 0) || 1;
  const starts = [];
  let sum = 0;
  for (const length of lengths) { starts.push((sum / total) * duration); sum += length; }
  const begin = context.currentTime;
  follow = setInterval(() => {
    if (token !== generation) return;
    const elapsed = context.currentTime - begin;
    let current = index;
    for (let i = 0; i < starts.length; i++) if (elapsed >= starts[i]) current = index + i;
    if (current !== player.index) {
      player.index = current;
      hooks.onsentence(current);
    }
  }, 100);
}

async function playIndex(index) {
  const token = ++generation;
  stopSource();
  if (index < 0) index = 0;
  if (index >= sentences.length) {
    player.playing = false;
    hooks.onend();
    return;
  }
  player.index = index;
  player.waiting = true;
  hooks.onsentence(index);
  const end = groupEnd(index);
  currentEnd = end;
  let buffer;
  try {
    buffer = await fetchSentence(index);
  } catch (error) {
    if (token !== generation) return;
    player.waiting = false;
    pause();
    hooks.onerror(error.message);
    return;
  }
  if (token !== generation) return;
  player.waiting = false;
  prefetchAfter(end);
  if (!buffer) { playIndex(end + 1); return; }
  source = context.createBufferSource();
  source.buffer = withPause(buffer, end);
  source.connect(context.destination);
  source.onended = () => { if (token === generation && player.playing) playIndex(end + 1); };
  source.start();
  followGroup(index, end, buffer.duration, token);
}

export async function play(index = player.index) {
  context ??= new AudioContext();
  if (context.state === 'suspended') await context.resume();
  const chars = await call('tts_group_chars', scope.language);
  const next = typeof chars === 'number' ? chars : 0;
  const flags = next > 0 && scope.book
    ? await call('tts_cached_flags', scope.book, sentences, player.speed, scope.language).catch(() => null) : null;
  const ready = Array.isArray(flags) ? flags : [];
  if (next !== groupChars || ready.some((flag, i) => flag !== Boolean(prepared[i]))) cache.clear();
  groupChars = next;
  prepared = ready;
  player.active = true;
  player.playing = true;
  await playIndex(index < 0 ? 0 : index);
}

export function pause() {
  player.playing = false;
  context?.suspend();
}

export async function resume() {
  if (!player.active) return play(0);
  player.playing = true;
  await context.resume();
  if (!source && !player.waiting) playIndex(player.index);
}

export function stop() {
  generation++;
  stopSource();
  context?.suspend();
  player.active = player.playing = player.waiting = false;
  player.index = -1;
  cache.clear();
}

export function step(delta) {
  if (!player.active) return;
  player.playing = true;
  context.resume();
  playIndex(Math.max(0, Math.min(sentences.length - 1, player.index + delta)));
}

export function setSpeed(speed) {
  player.speed = speed;
  // Already prefetched sentences used the old speed; the current one finishes as it is.
  for (const key of [...cache.keys()]) if (!key.endsWith(`@${speed}`)) cache.delete(key);
  if (player.active && player.index >= 0) prefetchAfter(Math.max(currentEnd, player.index));
}
