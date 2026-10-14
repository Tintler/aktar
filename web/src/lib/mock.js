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
    tesseract_path: '', tesseract_lang: 'tur+eng', disable_thinking: true,
  };
  let prefs = { theme: 'system' };
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
  setTimeout(() => {
    for (const line of ['Video açıldı: D:\Diziler\One Step Beyond - S00E01 - Extended Pilot.mkv', 'Çeviri partisi 6/38 (10 çeviri birimi)', 'BİLGİ: model satır sayısını değiştirdi (beklenen 2, bulunan 1).', 'Çeviri partisi 7/38 (10 çeviri birimi)'])
      emit('log', { line: '[10:42:0' + Math.floor(Math.random() * 9) + '] ' + line });
  }, 300);
  const api = {
    startup: async () => ({ prefs, themes: themes(), translate, models: { state: 'ok', names: ['gemma-4-26b-a4b-it-qat@q4_k_xl', 'qwen3-8b', 'text-embedding-embeddinggemma-2', 'glm-ocr'], model: settings.model, message: '' }, platform: 'windows', open: [] }),
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
    translate_state: async () => translate,
    set_series: async (slug) => ({ ...translate, series_slug: slug }),
    series_data: async () => ({ slug: 'one-step-beyond', title: 'One Step Beyond', glossary: [{ source: 'Bridge of the Ancients', target: 'Kadimlerin Köprüsü' }], decisions: ['Karakterler birbirine "sen" der.'] }),
    guess_series_title: async () => 'One Step Beyond',
    start_translation: async () => ({ ...translate, running: true }),
  };
  // 'then' tanimsiz kalmali: yoksa Promise bu nesneyi "thenable" sanip hic cozulmez.
  return new Proxy(api, { get: (target, name) => (name === 'then' ? undefined : target[name] ?? (async () => null)) });
}
