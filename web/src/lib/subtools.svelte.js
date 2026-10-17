// Altyazi araclari ve klip (F118): arka uctaki tek is yuvasinin durumu (bridge_subtitles 'subtool' olayi).
// job: {kind: 'align'|'ocr'|'whisper'|'clip'|'dub'|'diarize', path, state, stage, progress: {done, total}, message, result}
import { on } from './api.js';
import { act, toast } from './state.svelte.js';
import { confirm, notice } from './confirm.svelte.js';

export const subtool = $state({ job: null });

export const KIND_NAMES = { align: 'Otomatik hizalama', ocr: 'Altyazı OCR', whisper: 'Kelime zamanları', clip: 'Klip kaydı', dub: 'Dublaj', diarize: 'Konuşmacı ayrımı' };
const STAGE_NAMES = { whisper: 'Konuşmadan metin', frames: 'Altyazı görüntüleri', ocr: 'OCR', align: 'Hizalanıyor', clip: 'Klip kodlanıyor',
  engine: 'Ses motoru hazırlanıyor', voice: 'Seslendiriliyor', mix: 'Ses karıştırılıyor',
  download: 'Model indiriliyor', separate: 'Konuşma ve müzik ayrılıyor', diarize: 'Konuşmacılar ayrılıyor' };
const listeners = new Set();

// Is bitince (done/error/cancelled) cagrilir: fn(job). Donen fonksiyon dinlemeyi birakir.
export function onSubtool(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

on('subtool', async (data) => {
  if (data.state === 'running') {
    subtool.job = { ...(subtool.job?.kind === data.kind ? subtool.job : {}), ...data };
    return;
  }
  subtool.job = null;
  for (const fn of listeners) fn(data);
  const name = KIND_NAMES[data.kind] ?? 'İş';
  if (data.state === 'cancelled') return toast(name + ' durduruldu.', 'info');
  if (data.state === 'error') return notice(name + ' tamamlanamadı', data.message);
  const result = data.result ?? {};
  if (data.kind === 'clip') {
    const extra = result.subtitle ? '\nAltyazı: ' + result.subtitle.split(/[\\/]/).pop() : '';
    if (await confirm({ title: 'Klip kaydedildi', message: result.name + extra, ok: 'Konumu aç', cancel: 'Kapat' })) act('reveal', result.output);
  } else if (data.kind === 'dub') {
    const notes = [result.faster ? `${result.faster} satır sığması için hızlandırıldı` : '', result.shifted ? `${result.shifted} satır biraz kaydırıldı` : '']
      .filter(Boolean).join(', ');
    if (await confirm({ title: 'Dublaj hazır', message: `${result.name} · ${result.lines} satır${notes ? '\n' + notes + '.' : ''}`, ok: 'Konumu aç', cancel: 'Kapat' })) {
      act('reveal', result.output);
    }
  } else if (data.kind === 'ocr') {
    toast(`Altyazı okundu (${result.lines} satır): ${result.name}`, 'ok');
  } else if (data.kind === 'whisper') {
    toast('Kelime zamanları hazır.', 'ok');
  } else if (data.kind === 'diarize') {
    toast(`Konuşmacılar ayrıldı: ${result.speakers} konuşmacı.`, 'ok');
  }
});

export function jobText(job) {
  if (!job) return '';
  const stage = STAGE_NAMES[job.stage] ?? KIND_NAMES[job.kind] ?? '';
  const { done = 0, total = 0 } = job.progress ?? {};
  if (!total) return stage + '…';
  if (job.stage === 'ocr' || job.stage === 'voice') return `${stage}: ${Math.round(done)} / ${Math.round(total)}`;
  return `${stage}: %${Math.min(100, Math.round((done * 100) / total))}`;
}

export function jobPercent(job) {
  const { done = 0, total = 0 } = job?.progress ?? {};
  return total ? Math.min(100, Math.round((done * 100) / total)) : 0;
}

export const cancelJob = () => act('subtool_cancel');

// --- zamanlama -------------------------------------------------------------------
export const IDENTITY = { scale: 1, offset: 0 };
export const isIdentity = (t) => !t || (Math.abs(t.scale - 1) < 1e-9 && Math.abs(t.offset) < 1e-9);

// Kare hizi uyusmazliklari: altyazi zamani * oran (subtitle_sync.FRAME_RATIOS ile ayni).
export const RATIOS = [
  [1, 'Normal (×1)'],
  [25 / 23.976, '23,976 → 25 fps'], [23.976 / 25, '25 → 23,976 fps'],
  [24 / 23.976, '23,976 → 24 fps'], [23.976 / 24, '24 → 23,976 fps'],
  [25 / 24, '24 → 25 fps'], [24 / 25, '25 → 24 fps'],
];

export function signed(seconds, digits = 2) {
  const value = Number(seconds || 0);
  return (value >= 0 ? '+' : '−') + Math.abs(value).toFixed(digits).replace('.', ',') + ' sn';
}

export function timingText(t) {
  if (isIdentity(t)) return 'Düzeltme yok';
  const parts = [];
  if (Math.abs(t.offset) >= 1e-9) parts.push(signed(t.offset));
  if (Math.abs(t.scale - 1) >= 1e-9) parts.push('hız ×' + t.scale.toFixed(5).replace('.', ','));
  return parts.join(' · ');
}

// Iki esleme [(altyazi zamani, dogru zaman)] -> {scale, offset} (subtitle_sync.two_point ile ayni).
export function twoPoint(a, b) {
  if (!b) return { scale: 1, offset: a[1] - a[0] };
  if (Math.abs(b[0] - a[0]) < 1) return null;
  const scale = (b[1] - a[1]) / (b[0] - a[0]);
  if (!(scale >= 0.5 && scale <= 2)) return null;
  return { scale, offset: a[1] - a[0] * scale };
}

// h:mm:ss.s <-> saniye (klip araliklari)
export function clockTenths(seconds) {
  const tenths = Math.round(Math.max(0, Number(seconds) || 0) * 10);
  const h = Math.floor(tenths / 36000), m = Math.floor((tenths % 36000) / 600);
  const rest = ((tenths % 600) / 10).toFixed(1).padStart(4, '0').replace('.', ',');
  return h ? `${h}:${String(m).padStart(2, '0')}:${rest}` : `${m}:${rest}`;
}

export function parseClock(text) {
  const parts = String(text).trim().replace(',', '.').split(':').map(Number);
  if (!parts.length || parts.some((p) => Number.isNaN(p))) return null;
  return parts.reduce((total, part) => total * 60 + part, 0);
}
