// pywebview olmadan (duz tarayicida `npm run dev`) arayuzu gelistirmek icin sahte arka uc.
const BASE = {
  dark: { window: '#0f1114', panel: '#15181c', surface: '#1d2127', surface_hover: '#262b33', surface_active: '#2f353f', outline: '#2a3038', text: '#f2f4f6', secondary: '#a9b1bc', dim: '#6e7784', accent: '#c8ff00', accent_hover: '#d6ff3d', on_accent: '#0a1200', danger: '#f5717f', warning: '#f2b85c', overlay: '#22272e', shadow: '#0000008c' },
  light: { window: '#f8f9fb', panel: '#ffffff', surface: '#eef0f3', surface_hover: '#e3e6eb', surface_active: '#d7dbe1', outline: '#dde1e6', text: '#14171a', secondary: '#535b66', dim: '#8b939e', accent: '#4d7c0f', accent_hover: '#3f6212', on_accent: '#ffffff', danger: '#d63b4c', warning: '#b87a14', overlay: '#ffffff', shadow: '#0000002d' },
};
const PRESETS = import.meta.glob('../../../assets/themes/*.json', { eager: true, import: 'default' });

function themes() {
  const list = [
    { id: 'dark', name: 'Koyu', base: 'dark', palette: BASE.dark, file: '' },
    { id: 'light', name: 'Açık', base: 'light', palette: BASE.light, file: '' },
  ];
  for (const [path, data] of Object.entries(PRESETS)) {
    const file = path.split('/').pop();
    list.push({ id: 'file:' + file, name: file.replace(/\.json$/, ''), base: data.base, palette: { ...BASE[data.base], ...data.colors }, file });
  }
  return list;
}

export function createMock(emit) {
  const settings = {
    base_url: 'http://127.0.0.1:1234/v1', model: 'gemma-4-26b-a4b-it-qat@q4_k_xl', batch_cues: 10, max_tokens: 8192,
    temperature: 0.2, timeout_seconds: 1800, auto_retry_count: 2, glossary_strict: false, analysis_chunk_chars: 12000,
    qa_context_chars: 24000, whisper_model: 'large-v3-turbo', whisper_device: 'auto', whisper_language: '', whisper_cuda_dir: '',
    embedding_model: 'text-embedding-embeddinggemma-2', vision_model: '', qa_model: '', ocr_engine: 'auto', ocr_model: '',
    tesseract_path: '', tesseract_lang: 'tur+eng', disable_thinking: true, mail_address: 'ornek@gmail.com', backlog_url: 'https://ornek.pages.dev',
  };
  let prefs = { theme: 'system' };
  let conversation = { id: 'c1', title: '', entries: [], busy: false, stream: null, locked: false, saved: false };
  let translate = {
    video: { path: 'D:\Diziler\One Step Beyond - S00E01 - Extended Pilot.mkv', name: 'One Step Beyond - S00E01 - Extended Pilot.mkv', folder: 'D:\Diziler' },
    streams: [
      { index: 2, codec: 'ass', language: 'eng', title: 'English subs', supported: true, image: false, extension: 'ass' },
      { index: 3, codec: 'subrip', language: 'jpn', title: 'Signs', supported: true, image: false, extension: 'srt' },
      { index: 4, codec: 'hdmv_pgs_subtitle', language: 'eng', title: 'Blu-ray', supported: false, image: true, extension: '' },
    ],
    probing: false, series: [{ slug: 'one-step-beyond', title: 'One Step Beyond' }], series_slug: 'one-step-beyond',
    chapter_glossary: [], analysis: '', running: false, paused: false, progress: { done: 80, total: 375 },
  };
  const row = (name, kind, where, length, source, status, extra = {}) => ({
    key: name, path: 'D:/Dersler/' + name, name, kind, where, folder: 'D:/Dersler/' + where, length, measured: length !== '—',
    source, status, status_text: { ready: 'Hazır', transcript: 'Metin hazır', pending: 'Bekliyor', no_subtitle: 'Altyazı yok · Whisper bekliyor', missing: 'Bulunamadı' }[status],
    new: false, missing: status === 'missing', length_sort: lengthSort(length, kind), ...extra });
  function lengthSort(length, kind) {
    if (length === '—') return null;
    if (length.includes(':')) return [0, length.split(':').reduce((a, b) => a * 60 + Number(b), 0)];
    if (length.endsWith('sayfa')) return [1, parseInt(length)];
    return [2, parseFloat(length) * (length.endsWith('MB') ? 1e6 : 1e3)];
  }
  const library = {
    collections: [{ slug: 'ml', title: 'Makine Öğrenmesi', folders: 2, files: 0 }, { slug: 'kilavuz', title: 'Kullanım Kılavuzları', folders: 1, files: 3 }],
    slug: 'ml', title: 'Makine Öğrenmesi', scanning: false, kinds: {},
    folders: [{ path: 'D:/Dersler/ML', name: 'ML', count: 6 }, { path: 'D:/Dersler/Notlar', name: 'Notlar', count: 2 }],
    meta: '8 dosya · 5 hazır · 1 bekliyor · 1 Whisper bekliyor · 1 bulunamadı',
    queue: null,
    rows: [
      row('01 Doğrusal Regresyon.mkv', 'video', 'ML', '24:13', 'Altyazı · tur', 'ready'),
      row('02 Lojistik Regresyon.mkv', 'video', 'ML', '31:02', 'Altyazı · eng', 'ready'),
      row('03 Gradyan İnişi.mp4', 'video', 'ML', '18:40', 'Whisper · large-v3-turbo', 'ready'),
      row('04 Aşırı Öğrenme.mkv', 'video', 'ML', '27:55', '', 'pending', { new: true }),
      row('05 Düzenlileştirme.mp4', 'video', 'ML', '22:10', '', 'no_subtitle'),
      row('06 Karar Ağaçları.mkv', 'video', 'ML', '—', '', 'missing'),
      row('Ders notları.pdf', 'document', 'Notlar', '42 sayfa', 'PDF metni', 'ready'),
      row('Tahta.jpg', 'image', 'Notlar', '1.2 MB', 'Görsel', 'transcript'),
      row('Hesap Özeti.pdf', 'document', 'Ekstreler', '4 sayfa', 'PDF metni', 'ready', { key: 'e1', date: '2026-09-15', date_text: '15.09.2026' }),
      row('Hesap Özeti (1).pdf', 'document', 'Ekstreler', '3 sayfa', 'PDF metni', 'ready', { key: 'e2', date: '2026-08', date_text: 'Ağu 2026', date_manual: true }),
    ],
  };
  const chat = {
    slug: 'ml', busy: false, enabled: true, note: '5 hazır dosya · 3 dosya henüz hazır değil',
    overview: { summary: 'Bu koleksiyon denetimli öğrenmenin temellerini doğrusal regresyondan karar ağaçlarına kadar adım adım anlatıyor.', topics: ['Regresyon', 'Gradyan inişi', 'Aşırı öğrenme', 'Düzenlileştirme yöntemleri (L1/L2) ve model karmaşıklığının doğrulama hatasına etkisi'], questions: ['Gradyan inişi nasıl çalışır?', 'Aşırı öğrenme nasıl önlenir?'], videos: 5 },
    entries: [
      { kind: 'user', text: 'Öğrenme oranı çok büyük seçilirse ne olur?' },
      { kind: 'assistant', parts: [
        { type: 'text', text: 'Öğrenme oranı çok büyükse gradyan inişi minimumun etrafında **salınır** ve hatta ıraksayabilir ' },
        { type: 'cite', items: [{ path: 'x', start: 754, label: 'V3 12:34', title: '03 Gradyan İnişi' }] },
        { type: 'text', text: '. Küçük değerlerde ise yakınsama yavaşlar ' },
        { type: 'cite', items: [{ path: 'x', start: 70, label: 'V1 1:10', title: '01 Doğrusal Regresyon' }, { path: 'y', start: 12, label: 'V7 s.12', title: 'Ders notları' }] },
        { type: 'text', text: '.' }],
        sources: [{ path: 'x', start: 754, label: 'V3', title: '03 Gradyan İnişi', count: 1 }, { path: 'x', start: 70, label: 'V1', title: '01 Doğrusal Regresyon', count: 1 }, { path: 'y', start: 12, label: 'V7', title: 'Ders notları', count: 1 }] },
      { kind: 'user', text: 'Güncel varlıklarımın TL karşılığı?' },
      { kind: 'assistant', parts: [
        { type: 'text', text: '**Envanter (Fiziksel Varlıklar)** ' },
        { type: 'cite', items: [{ path: 'y', start: 1, label: 'V7 s.1', title: 'Inventory', document: true }] },
        { type: 'text', text: '\n\n| Kalem | Miktar | Hesap |\n|---|---|---|\n| Altın | 420,06 g × 6.569 TL/gr = **2.759.374,14 TL** ' },
        { type: 'cite', items: [{ path: 'y', start: 1, label: 'V7 s.1', title: 'Inventory', document: true }] },
        { type: 'text', text: ' |\n| Euro (fiziksel) | 2.145 € × 55,52 TL/€ | **119.090,40 TL** |\n\n**Toplam:** ≈ 2.878.464,54 TL' }],
        sources: [{ path: 'y', start: 1, label: 'V7', title: 'Inventory', count: 2 }] },
    ],
  };
  setTimeout(() => {
    for (const line of ['Video açıldı: D:\Diziler\One Step Beyond - S00E01 - Extended Pilot.mkv', 'Çeviri partisi 6/38 (10 çeviri birimi)', 'BİLGİ: model satır sayısını değiştirdi (beklenen 2, bulunan 1).', 'Çeviri partisi 7/38 (10 çeviri birimi)'])
      emit('log', { line: '[10:42:0' + Math.floor(Math.random() * 9) + '] ' + line });
  }, 300);
  let mailRules = [{ id: 'r1', title: 'World Gold ekstreleri', sender: '@worldcard.com.tr', subject: 'Hesap Özeti', what: 'pdf', since: '2025-01-01', folder: 'D:\Finans\Ekstreler', enabled: true, has_password: false, fetched: 9 }];
  const mailState = () => ({ rules: mailRules, account: true, address: settings.mail_address, checked: '2026-10-15T09:12:00', busy: false,
    what: [{ id: 'pdf', label: 'Ekler (PDF, Excel, Word…)' }, { id: 'html', label: 'E-posta gövdesi' }, { id: 'both', label: 'Ekler ve gövde' }] });
  const api = {
    library_open: async () => library,
    library_state: async () => library,
    chat_state: async () => chat,
    library_search: async (q) => ({ query: q, keys: library.rows.slice(0, 3).map((r) => r.key), files: 2, limited: false, searched: q.length >= 3,
      hits: [{ path: 'x', name: '03 Gradyan İnişi', start: 754, where: '12:34', text: 'öğrenme oranını küçültünce adımlar da küçülüyor' }, { path: 'y', name: 'Ders notları', start: 12, where: 's.12', text: 'Öğrenme oranı (learning rate) seçimi' }] }),
    prepare_plan: async () => { setTimeout(() => emit('prepare', { counts: { ready: 4, summary: 1, index: 0, document: 0, subtitle: 1, vision: 1, whisper: 1 }, whisper_seconds: '22:10', vision_pages: 12, failed: [] }), 700); return { files: 7, model: settings.model, whisper: true, whisper_model: 'large-v3-turbo', whisper_device: 'auto', vision_model: settings.model, ocr_engine: 'tesseract', warnings: [] }; },
    // F85: yeniden isleme -> kayitlari silinen dosyalar 'Bekliyor' olur
    library_reset: async (paths) => {
      for (const r of library.rows) if (paths.includes(r.path)) Object.assign(r, { status: 'pending', status_text: 'Bekliyor', source: '' });
      return { ...library };
    },
    // F89: e-postadan al
    mail_account: async () => ({ address: settings.mail_address, has_password: true }),
    mail_set_password: async () => ({ address: settings.mail_address, has_password: true }),
    mail_test: async () => ({ ok: true, message: 'Bağlandı · postalar "[Gmail]/Tüm Postalar" kutusunda aranacak' }),
    backlog_test: async () => ({ ok: true, message: 'Bağlandı · 3120 başlık' }),
    mail_rules: async () => mailState(),
    mail_save_rule: async (rule) => {
      const clean = { ...rule, id: rule.id || 'r' + (mailRules.length + 1), title: rule.title || rule.subject || rule.sender };
      const i = mailRules.findIndex((r) => r.id === clean.id);
      if (i < 0) mailRules.push(clean); else mailRules[i] = clean;
      return mailState();
    },
    mail_delete_rule: async (id) => { mailRules = mailRules.filter((r) => r.id !== id); return mailState(); },
    mail_preview: async () => new Promise((resolve) => setTimeout(() => resolve({ items: [
      { date: '2026-10-03', subject: 'Hesap Özetiniz', sender: 'World <ekstre@worldcard.com.tr>', done: false },
      { date: '2026-09-04', subject: 'Hesap Özetiniz', sender: 'World <ekstre@worldcard.com.tr>', done: true },
      { date: '2026-08-05', subject: 'Hesap Özetiniz', sender: 'World <ekstre@worldcard.com.tr>', done: true }] }), 600)),
    mail_fetch: async () => new Promise((resolve) => setTimeout(() => resolve({ ...mailState(), message: "E-postadan 1 yeni dosya indirildi." }), 800)),
    library_set_date: async (paths, value) => {
      for (const r of library.rows) if (paths.includes(r.path)) Object.assign(r, { date: value, date_text: value, date_manual: !!value });
      return { ...library };
    },
    library_reset_collection: async () => {
      for (const r of library.rows) if (!r.missing) Object.assign(r, { status: 'pending', status_text: 'Bekliyor', source: '' });
      chat.overview = null;
      return { ...library };
    },
    startup: async () => ({ prefs, themes: themes(), translate, library, models: { state: 'ok', names: ['gemma-4-26b-a4b-it-qat@q4_k_xl', 'qwen3-8b', 'text-embedding-embeddinggemma-2', 'glm-ocr'], model: settings.model, message: '' }, platform: 'windows', open: [] }),
    ui_prefs: async () => prefs,
    save_ui_prefs: async (values) => (prefs = { ...prefs, ...values }),
    list_themes: async () => themes(),
    refresh_models: async () => true,
    get_settings: async () => ({ config: { ...settings }, defaults: { ...settings }, locked: [], whisper_models: ['large-v3-turbo', 'large-v3', 'medium', 'small', 'base'], ocr_engines: [{ id: 'auto', label: 'Otomatik (Tesseract > OCR modeli > görü modeli)' }, { id: 'tesseract', label: 'Tesseract (yerel)' }, { id: 'model', label: 'OCR modeli (LM Studio)' }, { id: 'vision', label: 'Görü modeli' }], cuda_markers: [] }),
    save_settings: async (values) => ({ config: Object.assign(settings, values) }),
    check_tesseract: async () => ({ found: 'C:\Program Files\Tesseract-OCR\tesseract.exe' }),
    check_cuda_dir: async () => ({ message: '' }),
    window_state: async () => ({ custom: true, maximized: false }),
    window_command: async () => true,
    assistant_state: async () => conversation,
    assistant_new: async () => (conversation = { ...conversation, id: 'yeni', title: '', entries: [] }),
    assistant_list: async () => ({ items: [{ id: 'c1', title: 'Regresyon notları', updated: new Date().toISOString() }], current: conversation.id }),
    assistant_ask: async (text) => {
      conversation.entries = [...conversation.entries, { kind: 'user', text },
        { kind: 'assistant', parts: [{ type: 'text', text: 'Bu sahte arka uçtan gelen bir **örnek** cevaptır.\n\n- Madde bir\n- Madde iki' }], sources: [] }];
      return conversation;
    },
    files_recent: async () => ({ items: [{ path: 'D:\\Belgeler\\rapor.pdf', name: 'rapor.pdf', folder: 'D:\\Belgeler', kind: 'document', opened: new Date().toISOString(), missing: false }] }),
    translate_state: async () => translate,
    set_series: async (slug) => ({ ...translate, series_slug: slug }),
    series_data: async () => ({ slug: 'one-step-beyond', title: 'One Step Beyond', glossary: [{ source: 'Bridge of the Ancients', target: 'Kadimlerin Köprüsü' }], decisions: ['Karakterler birbirine "sen" der.'] }),
    guess_series_title: async () => 'One Step Beyond',
    start_translation: async () => ({ ...translate, running: true }),
  };
  // 'then' tanimsiz kalmali: yoksa Promise bu nesneyi "thenable" sanip hic cozulmez.
  return new Proxy(api, { get: (target, name) => (name === 'then' ? undefined : target[name] ?? (async () => null)) });
}
