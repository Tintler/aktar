import { call, on } from './api.js';
import { applyTheme } from './theme.js';
import { confirm, notice } from './confirm.svelte.js';

export const app = $state({
  view: 'library',            // 'chat' | 'library' | 'files' | 'translate' | 'console' | 'settings' | 'player' | 'document'
  sideCollapsed: false,       // sol menu daraltildi (yalnizca simgeler)
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
  translateView: { stream: null, analysis: false },
  // Komut satirindan ya da baska sayfadan acilmak uzere bekleyen video (Translate acilinca alir).
  pendingVideo: null,
  library: { collections: [], slug: '', title: '', folders: [], rows: [], meta: '', scanning: false, queue: null, kinds: {} },
  // Kutuphane gorunum durumu: secili satirlar (anahtar), tur filtresi, arama, sohbet paneli.
  // home: Kutuphane ana sayfasi (tum koleksiyonlar); bir koleksiyon acilinca false.
  libraryView: { selected: [], kind: '', query: '', search: null, chatOpen: true, scope: 'all', home: true },
  chat: null,                 // bridge_library.chat_state
  prepare: null,              // 'Hepsini hazirla' penceresi: plan bilgisi + sayimlar
  player: null,               // bridge_player._player_state (acik video)
  playerSeek: null,           // {time, play, n}: oynaticiya gidecegi an (atif, arama sonucu)
  playerPositions: {},        // video yolu -> son konum (sayfadan cikip donunce)
  document: null,             // bridge_document.doc_open (acik belge)
  docSeek: null,              // {page}: belge goruntuleyicinin gidecegi sayfa
  fileOrigin: 'library',      // acik video/belge nereden acildi: 'library' | 'files' (menude vurgu)
  files: [],                  // Dosya incele: son incelenen dosyalar
  assistant: null,            // genel sohbet: acik sohbetin durumu (bridge_assistant)
  conversations: [],          // genel sohbet listesi [{id, title, updated}]
});

const VIEWS = ['chat', 'library', 'files', 'translate', 'console'];

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

export function clearLog() {
  app.log.splice(0);
}

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
  on('analysis', ({ text }) => (app.translate.analysis = text));
  on('review', (data) => (app.review = data));
  on('finished', ({ output, name, error, cancelled }) => {
    app.review = null;
    if (error) {
      if (!cancelled) notice('Çeviri durdu', error);
      return;
    }
    notice('Çeviri tamamlandı', 'Çeviri başarıyla tamamlandı.\nÇıktı: ' + name);
  });
  on('library', (state) => setLibrary(state));
  on('row', ({ row, meta }) => {
    const index = app.library.rows.findIndex((r) => r.key === row.key);
    if (index >= 0) app.library.rows[index] = row;
    app.library.meta = meta;
  });
  on('row_status', ({ key, text, tone }) => {
    const row = app.library.rows.find((r) => r.key === key);
    if (row) { row.busy_text = text; row.busy_tone = tone; }
  });
  on('queue', ({ queue, message, failed }) => {
    app.library.queue = queue;
    if (!queue) {
      for (const row of app.library.rows) delete row.busy_text;
      if (message) {
        if (failed) notice('Toplu hazırlık', message + ' Ayrıntılar Konsol sayfasında.');
        else toast(message, 'ok');
      }
    }
  });
  on('prepare', (data) => {
    if (app.prepare) Object.assign(app.prepare, data);
  });
  on('chat', ({ slug }) => {
    if (slug === app.library.slug) refreshChat();
  });
  on('document', ({ path, chat }) => {
    if (app.document?.path === path) app.document.chat = chat;
  });
  on('player', (state) => {
    if (state && app.player?.path === state.path) app.player = state;
  });
  on('dropped', ({ paths }) => {
    const handler = dropHandlers[app.view] ?? dropHandlers.library;
    handler?.(paths);
  });
  on('assistant_stream', ({ id, text }) => {
    if (app.assistant?.id === id) app.assistant.stream = text;
  });
  on('assistant', async ({ id }) => {
    if (app.assistant?.id === id) app.assistant = await call('assistant_state');
    else if (app.assistant) app.assistant.locked = false;
    refreshConversations();
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
  if (start.prefs?.view && VIEWS.includes(start.prefs.view)) app.view = start.prefs.view;
  app.sideCollapsed = !!start.prefs?.sidebar_collapsed;
  app.models = { names: [], message: '', ...start.models };
  setTranslate(start.translate);
  setLibrary(start.library);
  call('refresh_models');
  // Komut satirindan ("Birlikte ac") gelen video Altyazi Cevir'de acilir.
  if (start.open?.length) openInTranslate(start.open[0]);
}

export function setLibrary(state) {
  if (!state) return;
  const changed = state.slug !== app.library.slug;
  Object.assign(app.library, state);
  const view = app.libraryView;
  if (changed) {
    view.selected = [];
    view.query = '';
    view.search = null;
    view.kind = '';
  } else {
    const keys = new Set(state.rows.map((r) => r.key));
    view.selected = view.selected.filter((k) => keys.has(k));
    if (view.query) runSearch();
  }
  refreshChat();
}

let searchSeq = 0;
export async function runSearch() {
  const seq = ++searchSeq;
  const query = app.libraryView.query.trim();
  const result = query ? await call('library_search', query) : null;
  if (seq === searchSeq) app.libraryView.search = result;
}

export async function refreshChat() {
  if (!app.library.slug) { app.chat = null; return; }
  const view = app.libraryView;
  const selected = view.scope === 'selected' ? selectedPaths() : null;
  app.chat = await call('chat_state', selected);
}

export function selectedPaths() {
  const keys = new Set(app.libraryView.selected);
  return app.library.rows.filter((r) => keys.has(r.key)).map((r) => r.path);
}

const VIDEO_EXT = /\.(mkv|mp4|m4v|avi|mov|webm|ts|wmv|flv)$/i;
let seekId = 0;

export function seekPlayer(time, play = true) {
  app.playerSeek = { time: Number(time) || 0, play, n: ++seekId };
}

// Dosyayi acar: video oynatici + soru sor, belge goruntuleyici. `at`: saniye ya da sayfa.
// `origin`: 'files' ise Dosya incele sayfasindan acildi (menude o vurgulanir).
export async function openFile(row, at = null, origin = 'library') {
  if (row.missing) return toast('Dosya bulunamadı: ' + row.path, 'error');
  app.fileOrigin = origin;
  if (!VIDEO_EXT.test(row.path)) {
    if (app.document?.path !== row.path) {
      const state = await act('doc_open', row.path);
      if (!state) return;
      app.document = state;
    }
    app.view = 'document';
    if (at !== null && at !== undefined) app.docSeek = { page: Math.round(Number(at)) || 1 };
    return;
  }
  if (app.player?.path !== row.path) {
    const state = await act('player_open', row.path);
    if (!state) return;
    app.player = state;
  }
  app.view = 'player';
  if (at !== null && at !== undefined) seekPlayer(at, true);
}

export function openInTranslate(path) {
  app.pendingVideo = path;
  app.view = 'translate';
}

export function go(view) {
  app.view = view;
  if (VIEWS.includes(view)) call('save_ui_prefs', { view });
}

export function toggleSidebar() {
  app.sideCollapsed = !app.sideCollapsed;
  call('save_ui_prefs', { sidebar_collapsed: app.sideCollapsed });
}

// --- genel sohbet ---
export async function refreshConversations() {
  const result = await call('assistant_list');
  if (result?.items) app.conversations = result.items;
}

export async function loadAssistant() {
  app.assistant = await call('assistant_state');
  refreshConversations();
}

// --- dosya incele ---
export async function refreshFiles() {
  const result = await call('files_recent');
  if (result?.items) app.files = result.items;
}

// Dosyayi listeye ekler ve acar (video: oynatici, belge: goruntuleyici; ikisi de soru sor).
export async function inspectFile(path, at = null) {
  const result = await act('files_touch', path);
  if (!result) return;
  app.files = result.items;
  await openFile({ path }, at, 'files');
}
