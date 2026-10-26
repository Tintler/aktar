// Read-aloud player: asks the back end (EMA Lightning) for one sentence at a time, plays it with
// the Web Audio API and prefetches the next sentences so speech flows without gaps.
// F177: an engine with a fixed cost per request (Drama 3 TR) reads consecutive sentences of a paragraph in one
// request; the highlight moves through the group in proportion to its characters.
// F186: the groups come from the back end (tts_plan), the same ones "Hazırla" renders, so prepared audio is found.
import { call } from './api.js';
import { PAUSE_DEFAULTS, pauseAfter } from './pauses.js';
import { pauses as silences, sentenceStarts } from './grouptiming.js';

const PREFETCH = 2;

export const player = $state({
  active: false,     // a reading session exists (playing or paused)
  playing: false,
  waiting: false,    // the current sentence is still being synthesised
  index: -1,
  from: -1,          // F189: group being played (first and last sentence), for the full-screen view
  to: -1,
  total: 0,
  speed: 1,
});

// F189: Web Audio, Windows'a etkinlik sayilmaz; okuma surdukce ekran kararmasin, bilgisayar uyumasin.
$effect.root(() => {
  $effect(() => {
    call('tts_keep_awake', player.playing).catch(() => {});
  });
});

let sentences = [];
let breaks = new Set();   // indices of sentences that end a paragraph
let pauses = { ...PAUSE_DEFAULTS };
let scope = { book: null, language: 'tr' };   // where rendered sentences are cached
let plan = { start: [], end: [], ready: [] };   // F186: per sentence, its group's first/last sentence, cached
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
  player.from = player.to = -1;
  plan ={ start: [], end: [], ready: [] };
  cache.clear();
}

// Silence after each sentence; read when a sentence starts, so changes apply from the next one.
export function setPauses(next) {
  pauses = next;
}

// Last sentence read together with `index` (without a plan: one sentence per request).
function groupEnd(index) {
  return plan.end[index] ?? index;
}

// Asks the back end how this chapter is grouped; a changed plan drops prefetched audio.
async function loadPlan() {
  const result = await call('tts_plan', scope.book, sentences, player.speed, scope.language, [...breaks]).catch(() => null);
  const next = { start: [], end: [], ready: [] };
  for (const [start, end, ready] of Array.isArray(result?.groups) ? result.groups : []) {
    for (let i = start; i <= end; i++) { next.start[i] = start; next.end[i] = end; next.ready[i] = ready; }
  }
  if (JSON.stringify(next) !== JSON.stringify(plan)) cache.clear();
  plan = next;
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

// Highlight inside a group: each sentence starts at the pause nearest its share of the characters (F186,
// grouptiming.js; AudioContext time stops while paused, so the highlight pauses too).
function followGroup(index, end, buffer, token) {
  if (end <= index) return;
  const lengths = sentences.slice(index, end + 1).map((s) => s.length);
  const starts = sentenceStarts(lengths, buffer.duration, silences(buffer.getChannelData(0), buffer.sampleRate));
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
  // A prepared group is read whole: starting inside it begins at its first sentence instead of rendering again.
  if (plan.ready[index] && plan.start[index] < index) index = plan.start[index];
  player.index = index;
  player.waiting = true;
  hooks.onsentence(index);
  const end = groupEnd(index);
  currentEnd = end;
  player.from = index;
  player.to = end;
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
  followGroup(index, end, buffer, token);
}

export async function play(index = player.index) {
  context ??= new AudioContext();
  if (context.state === 'suspended') await context.resume();
  await loadPlan();
  player.active = true;
  player.playing = true;
  await playIndex(index < 0 ? 0 : index);
}

// F205: a group was rendered again: prefetched audio is old, reading starts at that group.
export async function replay(index) {
  generation++;
  stopSource();
  cache.clear();
  return play(index);
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
  player.index = player.from = player.to = -1;
  cache.clear();
}

export function step(delta) {
  if (!player.active) return;
  player.playing = true;
  context.resume();
  let target = player.index + delta;
  if (plan.ready[player.index]) target = delta > 0 ? groupEnd(player.index) + 1 : plan.start[player.index] - 1;   // whole prepared groups
  playIndex(Math.max(0, Math.min(sentences.length - 1, target)));
}

export function setSpeed(speed) {
  player.speed = speed;
  // Already prefetched sentences used the old speed; the current one finishes as it is.
  for (const key of [...cache.keys()]) if (!key.endsWith(`@${speed}`)) cache.delete(key);
  if (player.active && player.index >= 0) prefetchAfter(Math.max(currentEnd, player.index));
}
