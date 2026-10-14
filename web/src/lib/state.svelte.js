import { call, on } from './api.js';
import { applyTheme } from './theme.js';
import { confirm, notice } from './confirm.svelte.js';

export const app = $state({
  view: 'library',            // 'library' | 'translate' | 'settings'
  platform: 'windows',
  themeId: 'system',
  themes: [],
  models: { state: 'probing', names: [], message: '', model: '' },
  log: [],
  review: null,               // ceviri onay penceresi verisi (bridge_translate.review_payload)
  translate: {
    video: null, streams: [], probing: false, series: [], series_slug: '', chapter_glossary: [],
    analysis: '', running: false, paused: false, progress: { done: 0, total: 0 },
  },
  // Altyazi Cevir sayfasinin gorunum durumu (sekme degisince korunur).
  translateView: { stream: null, analysis: false, tab: 'console' },
  // Komut satirindan ya da baska sayfadan acilmak uzere bekleyen video (Translate acilinca alir).
  pendingVideo: null,
});

export const toasts = $state([]);

let toastId = 0;

export function toast(message, kind = 'info') {
  const id = ++toastId;
  toasts.push({ id, message, kind });
  setTimeout(() => dismissToast(id), kind === 'error' ? 8000 : 4500);
}

// Svelte vekilleri yuzunden indexOf calismaz; kimlikle bulunur.
export function dismissToast(id) {
  const index = toasts.findIndex((t) => t.id === id);
  if (index >= 0) toasts.splice(index, 1);
}

const LOG_LIMIT = 5000;

export function log(line) {
  app.log.push(line);
  if (app.log.length > LOG_LIMIT) app.log.splice(0, app.log.length - LOG_LIMIT);
}

// Arka uc metodunu cagirir; {error} sonucunu bildirime cevirir ve null dondurur.
export async function act(method, ...args) {
  try {
    const result = await call(method, ...args);
    if (result && typeof result === 'object' && !Array.isArray(result) && 'error' in result) {
      toast(result.error, 'error');
      return null;
    }
    return result;
  } catch (error) {
    toast(String(error?.message ?? error), 'error');
    return null;
  }
}

export function setTranslate(state) {
  if (!state) return;
  Object.assign(app.translate, state);
  const selected = app.translateView.stream;
  if (selected !== null && !app.translate.streams.some((s) => s.index === selected)) app.translateView.stream = null;
  if (app.translateView.stream === null) {
    // Tek desteklenen akis varsa onu isaretle.
    const supported = app.translate.streams.filter((s) => s.supported);
    if (supported.length === 1) app.translateView.stream = supported[0].index;
  }
}

export function setTheme(id, save = true) {
  app.themeId = id;
  applyTheme(id, app.themes);
  if (save) call('save_ui_prefs', { theme: id });
}

export async function reloadThemes() {
  const list = await call('list_themes');
  if (Array.isArray(list)) app.themes = list;
  applyTheme(app.themeId, app.themes);
}

// Pencereye birakilan dosyalari acik sayfaya gore yonlendiren isleyiciler.
const dropHandlers = {};
export function onDrop(view, fn) {
  dropHandlers[view] = fn;
}

export async function init() {
  on('log', ({ line }) => log(line));
  on('toast', ({ message, kind }) => toast(message, kind));
  on('models', (data) => (app.models = { names: [], message: '', ...data }));
  on('translate', (state) => setTranslate(state));
  on('progress', (progress) => (app.translate.progress = progress));
  on('analysis', ({ text }) => {
    app.translate.analysis = text;
    app.translateView.tab = 'analysis';
  });
  on('review', (data) => (app.review = data));
  on('finished', ({ output, name, error, cancelled }) => {
    app.review = null;
    if (error) {
      if (!cancelled) notice('Çeviri durdu', error);
      return;
    }
    notice('Çeviri tamamlandı', 'Çeviri başarıyla tamamlandı.\nÇıktı: ' + name);
  });
  on('dropped', ({ paths }) => {
    const handler = dropHandlers[app.view] ?? dropHandlers.library;
    handler?.(paths);
  });
  on('confirm_close', async ({ reason }) => {
    const ok = await confirm({
      title: 'Aktar kapatılsın mı?',
      message: reason + ' Kapatırsanız iş durdurulur; kaydedilen kısım bir sonraki sefere kalır.',
      ok: 'Kapat', danger: true,
    });
    if (ok) call('confirm_close');
  });

  const start = await call('startup');
  app.platform = start.platform;
  app.themes = start.themes;
  setTheme(start.prefs?.theme ?? 'system', false);
  if (start.prefs?.view && ['library', 'translate'].includes(start.prefs.view)) app.view = start.prefs.view;
  app.models = { names: [], message: '', ...start.models };
  setTranslate(start.translate);
  call('refresh_models');
  // Komut satirindan ("Birlikte ac") gelen video Altyazi Cevir'de acilir.
  if (start.open?.length) openInTranslate(start.open[0]);
}

export function openInTranslate(path) {
  app.pendingVideo = path;
  app.view = 'translate';
}

export function go(view) {
  app.view = view;
  if (view !== 'settings') call('save_ui_prefs', { view });
}
