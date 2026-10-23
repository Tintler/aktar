// F186: where each sentence of a group starts in the group's audio, for the reading highlight. The character share
// of a sentence gives a first guess; each boundary then moves to the nearest pause in the audio (the reader speeds up
// and slows down, so in a 400-character group the share alone drifts by seconds). Plain functions, no Svelte.

const FRAME = 0.02;          // seconds per energy frame
const MIN_PAUSE = 0.12;      // shorter silences are not sentence ends
const SEARCH = 0.35;         // a boundary looks this share of its sentence's length around the guess (at least 1.2 s)

// Silent stretches of the audio as [{start, end}] in seconds (channel data of an AudioBuffer).
export function pauses(samples, rate) {
  const size = Math.max(1, Math.round(rate * FRAME));
  const levels = [];
  for (let i = 0; i < samples.length; i += size) {
    let sum = 0;
    const stop = Math.min(samples.length, i + size);
    for (let j = i; j < stop; j++) sum += samples[j] * samples[j];
    levels.push(Math.sqrt(sum / (stop - i)));
  }
  if (!levels.length) return [];
  // Silence is measured against the speech level (the loud tenth), so quiet and loud voices work alike.
  const sorted = [...levels].sort((a, b) => a - b);
  const loud = sorted[Math.floor(sorted.length * 0.9)] || 0;
  const threshold = Math.max(loud * 0.08, sorted[Math.floor(sorted.length * 0.1)] * 1.5, 1e-4);
  const found = [];
  let from = -1;
  for (let i = 0; i <= levels.length; i++) {
    const quiet = i < levels.length && levels[i] < threshold;
    if (quiet && from < 0) from = i;
    if (!quiet && from >= 0) {
      if ((i - from) * FRAME >= MIN_PAUSE && from > 0 && i < levels.length) found.push({ start: from * FRAME, end: i * FRAME });
      from = -1;
    }
  }
  return found;
}

// Start time of each sentence (first is 0) from the sentence lengths, the audio length and its pauses.
export function sentenceStarts(lengths, duration, silences = []) {
  const total = lengths.reduce((a, b) => a + b, 0) || 1;
  const starts = [0];
  let sum = 0, previous = 0;
  for (let k = 1; k < lengths.length; k++) {
    sum += lengths[k - 1];
    const guess = (sum / total) * duration;
    const reach = Math.max(1.2, SEARCH * (lengths[k - 1] / total) * duration);
    let best = null, bestCost = Infinity;
    for (const pause of silences) {
      const middle = (pause.start + pause.end) / 2;
      if (pause.end <= previous || Math.abs(middle - guess) > reach) continue;
      // Near the guess and long (a sentence end pauses longer than a comma).
      const cost = Math.abs(middle - guess) - 1.5 * Math.min(pause.end - pause.start, 0.6);
      if (cost < bestCost) { bestCost = cost; best = pause; }
    }
    const start = best ? best.end - 0.05 : Math.max(guess, previous);
    starts.push(start);
    previous = start;
  }
  return starts;
}
