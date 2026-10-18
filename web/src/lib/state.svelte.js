import { call, on } from './api.js';
import { applyTheme } from './theme.js';
import { confirm, notice } from './confirm.svelte.js';

export const app = $state({
  view: 'library',            // 'chat' | 'library' | 'files' | 'translate' | 'books' | 'console' | 'settings' | 'player' | 'document'
  sideCollapsed: false,       // sol menu daraltildi (yalnizca simgeler)
  platform: 'windows',
  themeId: 'system',
  themes: [],
  models: { state: 'probing', names: [], message: '', model: '' },
  log: [],
  review: null,               // ceviri onay penceresi verisi (bridge_translate.review_payload)
  translate: {
    video: null, streams: [], probing: false, series: [], series_slug: '', chapter_glossary: [],
    analysis: '', running: false, paused: false, progress: { done: 0, total: 0 }, job: '', whisper_available: false,
  },
  // Altyazi Cevir sayfasinin gorunum durumu (sekme degisince korunur).
  translateView: { stream: null, analysis: false },
  // Kitap Cevir (bridge_book): acik proje, bolumler, durum ve sayfa gorunumu (sekme degisince korunur).
  books: {
    book: { epub: '', folder: '', project: '', title: '', author: '', cover: null, chars: 0, output: '' },
    chapters: [], analysis: '', log: [], review: null,
    status: { runtime: 'idle', phase: 'Başlatılmadı', current: '', last_saved: '', progress: { done: 0, total: 0, percent: 0 } },
    tab: 'preview', selected: null, preAnalysis: false,
  },
  // Okuma (bridge_reader): kitaplik, acik kitap ve okuyucu gorunumu (ui.json 'reader').
  shelf: [],
  reading: { book: null, section: 0, offset: 0, percent: 0 },
  reader: { size: 19, font: 'serif', leading: 1.75, width: 680, paper: 'theme' },
  bookChat: null,             // F146: okuyucudaki kitap sohbeti {book, chat} (bridge_reader.reader_chat_open)
  // PDF'den kitap (bridge_pdf): acik pencere ve calisan is (pencere kapansa da is surer).
  pdfImport: null,            // {open, info, title, author, target, running, progress, result}
  setup: false,               // F154: bilesen denetimi penceresi acik
  version: '',                // F155: uygulama surumu (src/version.py)
  pdfReview: null,            // gozden gecirme: {path, target, summary} (bridge_pdf.pdf_review)
  settingsTab: 'models',      // Ayarlar sayfasinin acik kategorisi (ui.json 'settings_tab')
  // Sesli okuma (bridge_tts): motor durumu, kurulu motorlar, hazirlama/kayit ilerlemesi, tercihler (ui.json 'tts').
  tts: { state: 'idle', message: '', device: null, exporting: false },
  engines: [],
  ttsPrepare: null,           // {book, done, total}: cumleler hazirlanirken
  ttsExport: null,
  ttsAudiobook: null,         // F141: {book, title, done, total, chapter, chapters}: sesli kitap kaydedilirken
  ttsPrefs: { device: 'auto', speed: 1, voices: {}, options: {} },
  // Komut satirindan ya da baska sayfadan acilmak uzere bekleyen video (Translate acilinca alir).
  pendingVideo: null,
  library: { collections: [], slug: '', title: '', folders: [], rows: [], meta: '', scanning: false, queue: null, kinds: {} },
  // Kutuphane gorunum durumu: secili satirlar (anahtar), tur filtresi, arama, sohbet paneli.
  // home: Kutuphane ana sayfasi (tum koleksiyonlar); bir koleksiyon acilinca false.
  libraryView: { selected: [], kind: '', query: '', search: null, sort: '', chatOpen: true, chatWide: false, scope: 'all', home: true, preparing: false },
  chat: null,                 // bridge_library.chat_state
  prepare: null,              // 'Hepsini hazirla' penceresi: plan bilgisi + sayimlar
  player: null,               // bridge_player._player_state (acik video)
  playerSeek: null,           // {time, play, n}: oynaticiya gidecegi an (atif, arama sonucu)
  playerPositions: {},        // video yolu -> son konum (sayfadan cikip donunce)
  document: null,             // bridge_document.doc_open (acik belge)
  docSeek: null,              // {page}: belge goruntuleyicinin gidecegi sayfa
  fileOrigin: 'library',      // acik video/belge nereden acildi: 'library' | 'files' (menude vurgu)
  files: [],                  // Dosya incele: son incelenen dosyalar
  prefs: {},                  // ui.json (arayuz tercihleri; ses duzeyi gibi kalici degerler)
  busy: '',                   // dolu iken tum pencereyi kaplayan bekleme katmani (video/belge aciliyor)
  assistant: null,            // genel sohbet: acik sohbetin durumu (bridge_assistant)
  conversations: [],          // genel sohbet listesi [{id, title, updated}]
  think: false,               // sohbetlerde dusunme (reasoning) acik mi (F99; ui.json'da kalir)
});

// Kalici arayuz tercihi: ui.json'a yazilir. pywebview'in tarayici deposu (localStorage) uygulama
// kapaninca silindigi icin hatirlanmasi gereken her secim buradan kaydedilir (F130).
export function savePref(values) {
  Object.assign(app.prefs, values);
  call('save_ui_prefs', $state.snapshot(values));
}

export function setThink(value) {
  app.think = !!value;
  savePref({ think: app.think });
}

const VIEWS = ['chat', 'library', 'files', 'translate', 'books', 'reading', 'subscriptions', 'console'];

export const READER_DEFAULTS = { size: 19, font: 'serif', leading: 1.75, width: 680, paper: 'theme' };

// EPUB'u kitapliga ekleyip Okuma sayfasinda acar (Kitap Cevir'in urettigi Turkce EPUB icin).
export async function openInReader(path) {
  const result = await act('shelf_add', [path]);
  if (!result?.added?.length) return;
  app.shelf = result.books;
  const data = await act('reader_open', result.added[0]);
  if (!data) return;
  app.reading = { book: data, section: data.position.section, offset: data.position.offset, percent: data.percent };
  go('reading');
}

export function saveReaderPrefs() {
  savePref({ reader: $state.snapshot(app.reader) });
}

export function saveTtsPrefs() {
  savePref({ tts: $state.snapshot(app.ttsPrefs) });
}

export const toasts = $state([]);

let toastId = 0;

export function toast(message, kind = 'info') {
  const id = ++toastId;
  toasts.push({ id, message, kind });
  setTimeout(() => dismissToast(id), kind === 'error' || kind === 'warning' ? 8000 : 4500);
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

export function applyBookSnapshot(snapshot) {
  if (!snapshot) return;
  const b = app.books;
  b.book = snapshot.book;
  b.chapters = snapshot.chapters;
  b.status = snapshot.status;
  b.analysis = snapshot.analysis;
}

function bookLog(line) {
  const lines = app.books.log;
  lines.push(line);
  if (lines.length > LOG_LIMIT) lines.splice(0, lines.length - LOG_LIMIT);
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
  on('subtitle_ready', ({ name, error, cancelled }) => {
    if (error) {
      if (!cancelled) notice('Altyazı oluşturulamadı', error);
      return;
    }
    app.translateView.stream = 'whisper';
    toast('Altyazı oluşturuldu: ' + name + ' · Çevirmek için Çevir\'e basın.', 'ok');
  });
  // Kitap Cevir (bridge_book): gunluk hem sayfanin kendi sekmesine hem Konsol'a gider.
  on('book_log', ({ line, last_saved }) => {
    bookLog(line);
    log(line);
    app.books.status.last_saved = last_saved;
  });
  on('book_status', (status) => (app.books.status = status));
  on('book_chapters', ({ chapters }) => (app.books.chapters = chapters));
  on('book_analysis', ({ text }) => (app.books.analysis = text));
  on('book_review', (data) => (app.books.review = data));
  on('book_finished', ({ outcome, message, snapshot }) => {
    applyBookSnapshot(snapshot);
    app.books.review = null;
    if (outcome === 'failed') {
      notice('Kitap çevirisi durdu', message + '\nAyrıntılar Kitap Çevir sayfasının Günlük sekmesinde.');
      app.books.tab = 'console';
    } else toast(message, outcome === 'done' ? 'ok' : 'info');
  });
  on('shelf', ({ books, added, errors }) => {
    app.shelf = books;
    if (added?.length) toast(added.length === 1 ? 'Kitap kitaplığa eklendi.' : `${added.length} kitap kitaplığa eklendi.`, 'ok');
    for (const message of errors ?? []) toast(message, 'error');
  });
  on('tts', (status) => {
    app.tts = status;
    // Yuklenirken bir ses inmis olabilir: "indirildi" isaretleri yenilenir.
    if (status.state === 'ready') call('tts_engines').then((list) => { if (Array.isArray(list)) app.engines = list; });
  });
  on('tts_prepare', (data) => {
    if (!data.finished) { app.ttsPrepare = { book: data.book, done: data.done, total: data.total }; return; }
    app.ttsPrepare = null;
    if (data.error) toast('Hazırlama durdu: ' + data.error, 'error');
    else if (data.cancelled) toast(`Hazırlama durduruldu (${data.done} cümle hazır).`);
    else toast(`Ses hazırlandı (${data.done} cümle).`, 'ok');
  });
  on('tts_export', (data) => {
    if (!data.finished) { app.ttsExport = data; return; }
    app.ttsExport = null;
    if (data.error) toast('Ses kaydedilemedi: ' + data.error, 'error');
    else toast(`Ses kaydedildi (${data.count} cümle): ${data.path}`, 'ok');
  });
  // F141: sesli kitap kaydi (okuyucu); bitince dosya/klasor gosterilir.
  on('tts_audiobook', async (data) => {
    if (!data.finished) { app.ttsAudiobook = { ...data, chapters: data.chapters, chapter: data.chapter }; return; }
    app.ttsAudiobook = null;
    if (data.cancelled) { toast('Sesli kitap kaydı durduruldu; biten bölümler saklandı, yeniden başlatınca kaldığı yerden sürer.'); return; }
    if (data.error) { toast('Sesli kitap kaydedilemedi: ' + data.error, 'error'); return; }
    const where = data.format === 'mp3' ? 'Klasör' : 'Dosya';
    if (await confirm({ title: 'Sesli kitap hazır', message: `${data.title} · ${data.chapters} bölüm\n${where}: ${data.output}`, ok: 'Konumu aç', cancel: 'Kapat' })) {
      act('reveal', data.output);
    }
  });
  on('tts_engines', ({ engines, done, error }) => {
    app.engines = engines;
    if (done) toast(done, 'ok');
    if (error) toast(error, 'error');
  });
  on('pdf_progress', (data) => {
    if (app.pdfImport && app.pdfImport.info.path === data.path) { app.pdfImport.running = true; app.pdfImport.progress = data; }
  });
  on('pdf_done', (data) => {
    const job = app.pdfImport;
    if (!job || job.info.path !== data.path) return;
    job.running = false;
    if (data.cancelled) { app.pdfImport = null; toast('PDF okuma durduruldu; okunan sayfalar saklandı.'); return; }
    job.result = { target: job.target, ...data };
    job.open = true;          // pencere kapatilmissa sonucla yeniden acilir
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
  on('reader_chat', ({ book, chat }) => {
    // Kitap, reader_chat_open cevabi gelmeden hazirlanmis olabilir: olay o zaman da saklanir (at: ne zaman geldi).
    if (!app.bookChat || app.bookChat.book === book) app.bookChat = { book, chat, at: Date.now() };
  });
  on('player', (state) => {
    if (state && app.player?.path === state.path) app.player = state;
  });
  on('dropped', ({ paths }) => {
    const handler = dropHandlers[app.view] ?? dropHandlers.library;
    handler?.(paths);
  });
  on('assistant_stream', ({ id, text, thinking }) => {
    if (app.assistant?.id === id) { app.assistant.stream = text; app.assistant.thinking = thinking; }
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
  app.version = start.version ?? '';
  app.themes = start.themes;
  setTheme(start.prefs?.theme ?? 'system', false);
  if (start.prefs?.view && VIEWS.includes(start.prefs.view)) app.view = start.prefs.view;
  app.sideCollapsed = !!start.prefs?.sidebar_collapsed;
  app.prefs = start.prefs ?? {};
  app.think = !!app.prefs.think;
  app.books.preAnalysis = !!app.prefs.book_pre_analysis;
  app.reader = { ...READER_DEFAULTS, ...(app.prefs.reader ?? {}) };
  if (app.prefs.settings_tab) app.settingsTab = app.prefs.settings_tab;
  app.ttsPrefs = { device: 'auto', speed: 1, voices: {}, options: {}, ...(app.prefs.tts ?? {}) };
  app.models = { names: [], message: '', ...start.models };
  setTranslate(start.translate);
  setLibrary(start.library);
  applyBookSnapshot(start.books);
  call('shelf_list').then((books) => { if (Array.isArray(books)) app.shelf = books; });
  call('tts_status').then((status) => { if (status?.state) app.tts = status; });
  call('refresh_models');
  if (!app.prefs.setup_seen) app.setup = true;   // F154: ilk acilista bilesen denetimi
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
  if (app.busy) return;   // acilis surerken ikinci tiklama yok sayilir
  app.fileOrigin = origin;
  if (!VIDEO_EXT.test(row.path)) {
    if (app.document?.path !== row.path) {
      app.busy = 'Belge açılıyor…';
      const state = await act('doc_open', row.path).finally(() => (app.busy = ''));
      if (!state) return;
      app.document = state;
    }
    app.view = 'document';
    if (at !== null && at !== undefined) app.docSeek = { page: Math.round(Number(at)) || 1 };
    return;
  }
  if (app.player?.path !== row.path) {
    app.busy = 'Video açılıyor…';
    const state = await act('player_open', row.path).finally(() => (app.busy = ''));
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

// PDF'den kitap penceresini acar (target: 'reading' | 'books').
export async function openPdfImport(path = null, target = 'reading') {
  if (app.pdfImport?.running) { app.pdfImport.open = true; return; }
  const info = await act('pdf_info', path);
  if (!info) return;
  app.pdfImport = { open: true, info, title: info.title, author: info.author, target, running: false, progress: null, result: null };
}

export function closePdfImport() {
  if (!app.pdfImport) return;
  if (app.pdfImport.running) app.pdfImport.open = false;
  else app.pdfImport = null;
}

// Bitmis isin kitabini acar: Okuma'da okuyucu ya da Kitap Cevir'de proje.
export async function finishPdfImport() {
  const result = app.pdfImport?.result;
  app.pdfImport = null;
  await openPdfResult(result);
}

// PDF'nin gozden gecirme ekranini acar (sayfalar okunmus olmali).
export async function openPdfReview(path, target = 'reading') {
  app.busy = 'Kitap hazırlanıyor…';
  const summary = await act('pdf_review', path).finally(() => (app.busy = ''));
  if (!summary) return;
  app.pdfImport = null;
  app.pdfReview = { path, target, summary };
  app.view = 'pdfreview';
}

export async function finishPdfReview(result) {
  app.pdfReview = null;
  toast(`Kitap yeniden oluşturuldu (${result.chapters.length} bölüm).`, 'ok');
  await openPdfResult(result);
}

async function openPdfResult(result) {
  if (!result || result.error) return;
  if (result.target === 'books') {
    const snapshot = await act('book_choose_epub', result.epub);
    if (snapshot) { applyBookSnapshot(snapshot); go('books'); }
    return;
  }
  const books = await call('shelf_list');
  if (Array.isArray(books)) app.shelf = books;
  const data = result.book_id ? await act('reader_open', result.book_id) : null;
  if (data) app.reading = { book: data, section: data.position.section, offset: data.position.offset, percent: data.percent };
  go('reading');
}

// Ayarlar'i belirli bir kategoride acar (orn. sesli okumada motor yoksa 'voice').
export function openSettings(tab) {
  app.settingsTab = tab;
  go('settings');
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
