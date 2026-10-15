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
    chapter_glossary: [], analysis: '', running: false, paused: false, progress: { done: 80, total: 375 }, job: '', whisper_available: true,
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
  let templates = [{ id: 'finans', name: 'Finans analisti', text: 'Tutarları tabloyla ver.' }, { id: 'kisa', name: 'Kısa ve öz', text: 'Kısa yaz.' }];
  const chat = {
    template: '', template_note: '',
    slug: 'ml', busy: false, enabled: true, note: '5 hazır dosya · 3 dosya henüz hazır değil',
    overview: { summary: 'Bu koleksiyon denetimli öğrenmenin temellerini doğrusal regresyondan karar ağaçlarına kadar adım adım anlatıyor.', topics: ['Regresyon', 'Gradyan inişi', 'Aşırı öğrenme', 'Düzenlileştirme yöntemleri (L1/L2) ve model karmaşıklığının doğrulama hatasına etkisi'], questions: ['Gradyan inişi nasıl çalışır?', 'Aşırı öğrenme nasıl önlenir?'], videos: 5 },
    entries: [
      { kind: 'user', text: 'Öğrenme oranı çok büyük seçilirse ne olur?' },
      { kind: 'assistant', think: true, thinking: 'Kullanıcı öğrenme oranının büyük seçilmesinin etkisini soruyor. V3 videosunda 12:34 civarında salınım anlatılıyor; V1 ve ders notları küçük değerlerin yavaş yakınsamasını ekliyor.', parts: [
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
  const sub = (values) => ({ category: '', currency: 'TRY', kind: 'recurring', cycle: 'monthly', status: 'active', start_date: '2025-01-01',
    end_date: '', auto_renew: true, method: 'credit', bank: '', card: '', card_last4: '', notes: '', variable: false, match: '', payments: [], ...values });
  // F110: ekstre taramasi (sahte): oneriler ve okunan ekstreler
  let suggestions = [
    { key: 'no:1617', name: 'PALGAZ', match: '1617', category: 'Fatura', count: 3, months: 3, average: 241.67, last: 175, last_date: '2026-09-14', first_date: '2026-07-14',
      day: 14, variable: true, method: 'transfer', subscriber_no: '1617', description: 'Ödeme, PALGAZ - Gebze Tüketim faturası, abone no : 1617', payments: [] },
    { key: 'no:1130192198', name: 'Türksat Kablo TV', match: '1130192198', category: 'Fatura', count: 1, months: 1, average: 435.4, last: 435.4, last_date: '2026-09-21',
      first_date: '2026-09-21', day: 21, variable: false, method: 'transfer', subscriber_no: '1130192198', description: 'Ödeme, Türksat Kablo TV faturası', payments: [] },
    { key: 'm:deezer', name: 'Deezer', match: 'Deezer', category: '', count: 2, months: 2, average: 99.99, last: 99.99, last_date: '2026-09-07', first_date: '2026-08-07',
      day: 7, variable: false, method: 'credit', subscriber_no: '', description: 'DEEZER SA DEEZER', payments: [] },
  ];
  let ignoredList = [];
  let autoScan = true;
  let alerts = [
    { key: 's3|2026-09-02|504', id: 's3', name: 'Elektrik', kind: 'high', date: '2026-10-02', amount: 812.4, reference: 572.37, currency: 'TRY', ratio: 0.4194, stored: 840 },
    { key: 's1|2026-10-08|279.99', id: 's1', name: 'Netflix', kind: 'price_up', date: '2026-10-08', amount: 279.99, reference: 229.99, currency: 'TRY', ratio: 0.2174, stored: 229.99 },
  ];
  const scanInfo = { date: '2026-10-15T09:30:00', busy: null, sources: ['finans'], collections: [{ slug: 'finans', title: 'Finans' }, { slug: 'ml', title: 'Makine öğrenmesi' }],
    statements: [{ name: 'Enpara Kredi Kartı ekstreniz.pdf', path: 'a', account: 'credit_card', status: 'ok', problem: '', count: 7 },
      { name: '2026 Eylül ayı hesap özetiniz.pdf', path: 'b', account: 'bank_account', status: 'mismatch', problem: 'fark var', count: 6 }] };
  let subs = [
    sub({ id: 's1', name: 'Netflix', category: 'Dijital yayın', amount: 229.99, renewal_date: '2026-10-18', bank: 'Garanti BBVA', card: 'Bonus', card_last4: '4821' }),
    sub({ id: 's2', name: 'Amazon Prime', category: 'Dijital yayın', amount: 69.9, renewal_date: '2026-11-02', bank: 'Akbank', card: 'Axess', card_last4: '1290' }),
    sub({ id: 's3', name: 'Elektrik', category: 'Fatura', amount: 840, renewal_date: '2026-10-02', method: 'transfer', bank: 'Enpara', card: 'Abone no 100104418533',
      variable: true, match: '100104418533', payments: [['2026-05-04', 612.4], ['2026-06-02', 455.1], ['2026-07-03', 588], ['2026-08-02', 702.35], ['2026-09-02', 504]]
        .map(([date, amount]) => ({ date, amount, file: 'Hesap özeti.pdf' })) }),
    sub({ id: 's4', name: 'iCloud+', category: 'Bulut', amount: 99.99, currency: 'USD', cycle: 'yearly', renewal_date: '2027-03-12', method: 'debit', bank: 'Akbank', card_last4: '7730' }),
    sub({ id: 's5', name: 'Spor salonu', category: 'Spor', amount: 1500, status: 'paused', renewal_date: '2026-12-01', bank: 'Garanti BBVA' }),
  ];
  const subsView = () => {
    const rate = { weekly: 52 / 12, monthly: 1, quarterly: 1 / 3, semiannual: 1 / 6, yearly: 1 / 12 };
    const live = (s) => s.kind === 'recurring' && ['active', 'trial'].includes(s.status);
    const avg = (s) => s.variable && s.payments.length ? +(s.payments.slice(-6).reduce((a, p) => a + p.amount, 0) / Math.min(6, s.payments.length)).toFixed(2) : s.amount;
    const items = subs.map((s) => ({ ...s, estimate: avg(s), last_payment: s.payments.at(-1) ?? null,
      low: s.payments.length ? Math.min(...s.payments.map((p) => p.amount)) : null, high: s.payments.length ? Math.max(...s.payments.map((p) => p.amount)) : null, next_due: ['paused', 'cancelled'].includes(s.status) ? '' : s.renewal_date,
      days_left: ['paused', 'cancelled'].includes(s.status) ? null : Math.round((new Date(s.renewal_date) - new Date('2026-10-15')) / 864e5),
      monthly: live(s) ? +(avg(s) * rate[s.cycle]).toFixed(2) : 0 }));
    const sum = (list, f) => list.reduce((acc, s) => ({ ...acc, [s.currency]: +((acc[s.currency] ?? 0) + f(s)).toFixed(2) }), {});
    const monthly = sum(items.filter((s) => s.monthly), (s) => s.monthly);
    const groups = {};
    for (const s of items.filter((s) => s.monthly)) {
      const g = (groups[s.bank + s.method + s.currency] ??= { bank: s.bank || 'Banka belirtilmedi', method: s.method, currency: s.currency, monthly: 0, count: 0 });
      g.monthly = +(g.monthly + s.monthly).toFixed(2); g.count++;
    }
    return { items, categories: ['Dijital yayın', 'Müzik', 'Yazılım', 'Bulut', 'Fatura', 'Diğer'], summary: {
      monthly, yearly: Object.fromEntries(Object.entries(monthly).map(([k, v]) => [k, +(v * 12).toFixed(2)])),
      upcoming: sum(items.filter((s) => s.days_left !== null && s.days_left <= 30), (s) => s.amount), upcoming_days: 30,
      active: items.filter((s) => ['active', 'trial'].includes(s.status)).length,
      by_payment: Object.values(groups).sort((a, b) => b.monthly - a.monthly) },
      scan: { ...scanInfo, ignored: ignoredList.length, auto: autoScan }, suggestions, ignored: ignoredList, alerts };
  };
  const api = {
    library_open: async () => library,
    library_state: async () => library,
    library_overview: async () => library.collections.map((c) => ({ ...c, count: c.files, summary: chat.overview.summary, topics: chat.overview.topics })),
    chat_state: async () => ({ ...chat, entries: chat.entries.map((e) => ({ ...e })) }),
    // F106: abonelikler (tarih hesabi yok; gercek hesap subscriptions.py'de)
    subs_state: async () => subsView(),
    subs_save: async (item) => {
      const index = subs.findIndex((s) => s.id === item.id);
      if (index >= 0) subs[index] = item; else subs.push({ ...item, id: 'm' + Date.now() });
      return subsView();
    },
    subs_delete: async (id) => { subs = subs.filter((s) => s.id !== id); return subsView(); },
    subs_accept: async (key) => {
      const s = suggestions.find((x) => x.key === key);
      subs.push(sub({ id: 'm' + Date.now(), name: s.name, category: s.category, amount: s.average, renewal_date: s.last_date, method: s.method, variable: s.variable, match: s.match }));
      suggestions = suggestions.filter((x) => x.key !== key);
      return subsView();
    },
    subs_link: async (key) => { suggestions = suggestions.filter((x) => x.key !== key); return subsView(); },
    subs_ignore: async (key, undo) => {
      if (undo) { suggestions = [...suggestions, ...ignoredList.filter((x) => x.key === key)]; ignoredList = ignoredList.filter((x) => x.key !== key); }
      else { ignoredList = [...ignoredList, ...suggestions.filter((x) => x.key === key)]; suggestions = suggestions.filter((x) => x.key !== key); }
      return subsView();
    },
    subs_unignore_all: async () => { suggestions = [...suggestions, ...ignoredList]; ignoredList = []; return subsView(); },
    subs_scan_stop: async () => ({ ok: true }),
    subs_set_auto: async (on) => { autoScan = !!on; return subsView(); },
    subs_dismiss_alert: async (key) => { alerts = alerts.filter((a) => a.key !== key); return subsView(); },
    subs_apply_price: async (id) => {
      const a = alerts.find((x) => x.id === id);
      subs = subs.map((x) => (x.id === id ? { ...x, amount: a.amount } : x));
      alerts = alerts.filter((x) => x.id !== id);
      return subsView();
    },
    library_set_watch: async (on) => ({ ...library, watch: !!on }),
    // F111: harcama panosu (sabit ornek; gercek hesap expenses.py'de)
    subs_spending: async (month) => {
      const totals = [['2026-03', 8120.4, true], ['2026-04', 14250.9], ['2026-05', 12980.35], ['2026-06', 16840], ['2026-07', 13110.6],
        ['2026-08', 15420.75], ['2026-09', 17985.2], ['2026-10', 6240.5, true]];
      const months = totals.map(([m, total, partial]) => ({ month: m, total, count: Math.round(total / 380), partial: !!partial }));
      const keys = months.map((m) => m.month);
      if (month !== 'all' && !keys.includes(month)) month = keys.at(-1);
      const index = keys.indexOf(month);
      const total = month === 'all' ? +months.reduce((a, m) => a + m.total, 0).toFixed(2) : months[index].total;
      const split = (parts) => parts.map(([key, label, share]) => ({ key, label, share, total: +(total * share).toFixed(2), count: Math.max(1, Math.round(share * 40)) }));
      const full = months.filter((m) => !m.partial);
      return {
        month, months, options: [...keys].reverse(), total, count: Math.round(total / 380),
        previous: index > 0 && month !== 'all' ? { month: keys[index - 1], total: months[index - 1].total, change: +(total - months[index - 1].total).toFixed(2),
          ratio: +((total - months[index - 1].total) / months[index - 1].total).toFixed(4) } : null,
        partial: month !== 'all' && months[index].partial,
        average: +(full.reduce((a, m) => a + m.total, 0) / full.length).toFixed(2),
        categories: split([['purchase', 'Alışveriş', 0.52], ['bill', 'Fatura', 0.24], ['subscription', 'Abonelik', 0.11], ['other', 'Diğer', 0.09], ['fee', 'Masraf ve faiz', 0.04]]),
        merchants: [['Migros', 'Alışveriş', 0.16], ['Enerjisa', 'Fatura', 0.09], ['Trendyol', 'Alışveriş', 0.08], ['İGDAŞ', 'Fatura', 0.06], ['Shell', 'Alışveriş', 0.05],
          ['Turkcell', 'Fatura', 0.04], ['Netflix', 'Abonelik', 0.02], ['A101', 'Alışveriş', 0.02], ['Yemeksepeti', 'Alışveriş', 0.02], ['Deezer', 'Abonelik', 0.01]]
          .map(([name, category, share]) => ({ key: name, name, category, share, total: +(total * share).toFixed(2), count: Math.max(1, Math.round(share * 30)) })),
        merchant_count: 47, excluded: { count: 4, total: 48200,
          groups: [{ key: 'transfer', label: 'Hesaplar arası transfer', count: 2, total: 40000 }, { key: 'card_payment', label: 'Kart borcu ödemesi', count: 2, total: 8200 }],
          rows: [
            { date: '2026-09-21', description: 'Giden transfer, Cem Acar, Vadeli hesaba aktarım', merchant: '', amount: 25000, reason: 'transfer', account: 'bank_account', file: 'Eylül hesap özeti.pdf' },
            { date: '2026-09-12', description: 'Ödeme - Enpara.com Cep Şubesi', merchant: 'Enpara', amount: 3104.15, reason: 'card_payment', account: 'bank_account', file: 'Eylül hesap özeti.pdf' },
            { date: '2026-09-05', description: 'Giden transfer, Cem Acar, Döviz hesabı', merchant: '', amount: 15000, reason: 'transfer', account: 'bank_account', file: 'Eylül hesap özeti.pdf' },
            { date: '2026-08-12', description: 'Ödeme, Enpara.com kredi kartı ödemesi', merchant: 'Enpara', amount: 5095.85, reason: 'card_payment', account: 'bank_account', file: 'Ağustos hesap özeti.pdf' }] },
        period: { first: '2026-03-12', last: '2026-10-11' }, statements: 2, scan_date: scanInfo.date,
      };
    },
    subs_scan: async () => {
      let done = 0;
      const timer = setInterval(() => {
        if (done < 3) emit('subs_scan', { busy: { done: done++, total: 3, name: `Ekstre ${done}.pdf` } });
        else { clearInterval(timer); scanInfo.busy = null; emit('subs_scan', { busy: null, state: subsView(), message: '2 ekstre, 3 öneri' }); }
      }, 700);
      return { ...subsView(), scan: { ...scanInfo, ignored: ignoredList.length, busy: { done: 0, total: 3, name: '' } } };
    },
    // F104: sohbet sablonlari
    templates_list: async () => templates.map((t) => ({ ...t })),
    templates_save: async (items) => (templates = items.filter((t) => t.name.trim() && t.text.trim()).map((t, i) => ({ ...t, id: t.id || 'm' + Date.now() + i }))),
    chat_set_template: async (template, note) => {
      if (template != null) chat.template = template;
      if (note != null) chat.template_note = note.trim();
      return { ...chat, entries: chat.entries.map((e) => ({ ...e })) };
    },
    chat_ask: async (text, _selected, think) => {
      // F102: dusunme aciksa bekleyen kayitta dusunce canli akar, sonra cevaba donusur.
      const thought = think ? 'Soru öğrenme oranıyla ilgili. V3 videosunda salınım anlatılıyor, V1 yakınsama hızından bahsediyor. Ders notlarında da tipik değer aralığı var. Önce etkisini, sonra önerilen aralığı yazıp atıfları ekleyeceğim.' : '';
      const words = thought ? thought.split(' ') : [];
      const pending = { kind: 'pending', text: 'Dosyalarda aranıyor…', thinking: '' };
      chat.entries = [...chat.entries, { kind: 'user', text }, pending];
      Object.assign(chat, { busy: true, enabled: false });
      let i = 0;
      const timer = setInterval(() => {
        i += 1;
        if (i <= words.length) pending.thinking = words.slice(0, i).join(' ');
        else {
          clearInterval(timer);
          chat.entries = [...chat.entries.filter((e) => e !== pending), { kind: 'assistant', think, thinking: thought,
            parts: [{ type: 'text', text: 'Sahte arka uçtan örnek cevap ' }, { type: 'cite', items: [{ path: 'x', start: 754, label: 'V3 12:34', title: '03 Gradyan İnişi' }] }], sources: [] }];
          Object.assign(chat, { busy: false, enabled: true });
        }
        emit('chat', { slug: chat.slug });
      }, 150);
      return { ...chat, entries: [...chat.entries] };
    },
    library_search: async (q) => ({ query: q, keys: library.rows.slice(0, 3).map((r) => r.key), files: 2, limited: false, searched: q.length >= 3,
      hits: [{ path: 'x', name: '03 Gradyan İnişi', start: 754, where: '12:34', text: 'öğrenme oranını küçültünce adımlar da küçülüyor' }, { path: 'y', name: 'Ders notları', start: 12, where: 's.12', text: 'Öğrenme oranı (learning rate) seçimi' }] }),
    prepare_plan: async () => { setTimeout(() => emit('prepare', { counts: { ready: 4, summary: 1, index: 0, document: 0, subtitle: 1, vision: 1, whisper: 1, frames: 3 }, whisper_seconds: '22:10', vision_pages: 12, failed: [], frames_seconds: '2:41:10', frames_extra: 2 }), 700); return { files: 7, model: settings.model, whisper: true, whisper_model: 'large-v3-turbo', whisper_device: 'auto', vision_model: settings.model, ocr_engine: 'tesseract', warnings: [] }; },
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
    assistant_ask: async (text, think, template) => {
      // Dusunme aciksa once dusunce kelime kelime akar (F101 canli dusunce alani).
      let answer = 'Bu sahte arka uçtan gelen bir **örnek** cevaptır.\n\n- Madde bir\n- Madde iki';
      // F103: "grafik" iceren soruya her turden ornek grafik
      if (/grafik/i.test(text)) {
        answer = 'Örnek grafikler:\n\n' + [
          { type: 'bar', title: 'Çeyreklik net kâr', unit: 'mn TL', labels: ['Ç1', 'Ç2', 'Ç3', 'Ç4'], series: [{ name: '2025', values: [120, 140, 95, 160] }, { name: '2026', values: [150, 160, 130, 175] }] },
          { type: 'doughnut', title: 'Portföy dağılımı', unit: '%', labels: ['Altın', 'Döviz', 'Hisse', 'Fon'], series: [{ values: [42, 23, 20, 15] }] },
          { type: 'line', title: 'Kart borcu', unit: 'TL', labels: ['Haz', 'Tem', 'Ağu', 'Eyl'], series: [{ name: 'Borç', values: ['12.400,50', '9.850', '14.210', '11.030'] }] },
          { type: 'radar', title: 'Fon karşılaştırması', labels: ['Getiri', 'Risk', 'Likidite', 'Maliyet', 'Çeşitlilik'], series: [{ name: 'Fon A', values: [8, 5, 7, 6, 4] }, { name: 'Fon B', values: [6, 3, 9, 8, 7] }] },
          { type: 'hbar', title: 'Gider kalemleri', unit: 'TL', labels: ['Market alışverişi', 'Faturalar', 'Ulaşım', 'Eğlence'], series: [{ values: [5200, 3100, 1800, 950] }] },
        ].map((spec) => '```chart\n' + JSON.stringify(spec) + '\n```').join('\n\n') + '\n\n```chart\n{"type": "bar", bozuk\n```\n\nSon grafik bilerek bozuk.';
      }
      const thought = think ? 'Kullanıcı bir soru sordu. Önce kütüphanede ilgili notlar var mı bakmalıyım. Notlarda doğrudan bir kayıt yok, genel bilgiyle cevaplayacağım. Cevabı kısa tutup iki maddede özetlemek yeterli olur. Biçim olarak Markdown liste kullanacağım. Son olarak yazım hatalarını kontrol ediyorum ve gereksiz tekrarları çıkarıyorum.' : '';
      const words = thought ? thought.split(' ') : [];
      conversation = { ...conversation, busy: true, stream: '', thinking: '', entries: [...conversation.entries, { kind: 'user', text }] };
      let i = 0;
      const timer = setInterval(() => {
        i += 1;
        if (i <= words.length) emit('assistant_stream', { id: conversation.id, text: '', thinking: words.slice(0, i).join(' ') });
        else {
          clearInterval(timer);
          conversation = { ...conversation, busy: false, stream: null, thinking: null, entries: [...conversation.entries,
            { kind: 'assistant', think, thinking: thought, parts: [{ type: 'text', text: answer }], sources: [], template: templates.find((t) => t.id === template)?.name ?? '' }] };
          emit('assistant', { id: conversation.id });
        }
      }, 150);
      return conversation;
    },
    files_recent: async () => ({ items: [{ path: 'D:\\Belgeler\\rapor.pdf', name: 'rapor.pdf', folder: 'D:\\Belgeler', kind: 'document', opened: new Date().toISOString(), missing: false }] }),
    translate_state: async () => translate,
    set_series: async (slug) => ({ ...translate, series_slug: slug }),
    series_data: async () => ({ slug: 'one-step-beyond', title: 'One Step Beyond', glossary: [{ source: 'Bridge of the Ancients', target: 'Kadimlerin Köprüsü' }], decisions: ['Karakterler birbirine "sen" der.'] }),
    guess_series_title: async () => 'One Step Beyond',
    start_translation: async () => ({ ...translate, running: true, job: 'translate' }),
    generate_subtitle: async () => ({ ...translate, running: true, job: 'whisper', progress: { done: 312, total: 1440 } }),
    voice_status: async () => ({ available: true, hint: '', max_seconds: 120 }),
    voice_transcribe: async () => { await new Promise((r) => setTimeout(r, 900)); return { text: 'Bu videoda hangi konular anlatılıyor?', language: 'tr' }; },
  };
  // 'then' tanimsiz kalmali: yoksa Promise bu nesneyi "thenable" sanip hic cozulmez.
  return new Proxy(api, { get: (target, name) => (name === 'then' ? undefined : target[name] ?? (async () => null)) });
}
