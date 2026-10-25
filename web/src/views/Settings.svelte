<script>
  import Icon from '../lib/Icon.svelte';
  import Toggle from '../components/Toggle.svelte';
  import TemplateEditor from '../components/TemplateEditor.svelte';
  import VoiceSettings from '../components/VoiceSettings.svelte';
  import FoldHead from '../components/FoldHead.svelte';
  import { isOpen } from '../lib/folds.js';
  import { app, act, savePref, setTheme, reloadThemes, toast } from '../lib/state.svelte.js';
  import { resolveTheme } from '../lib/theme.js';
  import { call, on } from '../lib/api.js';
  import { onDestroy, tick } from 'svelte';

  let info = $state(null);       // get_settings sonucu (varsayilanlar, kilitler, secenekler)
  let cfg = $state(null);
  let saved = $state('');
  let saving = $state(false);
  let tesseract = $state('');
  let cuda = $state({ message: '' });
  const dirty = $derived(cfg !== null && JSON.stringify(cfg) !== saved);

  async function load() {
    info = await call('get_settings');
    cfg = info.config;
    saved = JSON.stringify(cfg);
  }
  load();
  // GPU kodlayici denemesi arka planda biter (F120); sayfa beklemeden acilir.
  const offEncoders = on('video_encoders', (list) => { if (info) info.video_encoders = list; });
  onDestroy(offEncoders);

  const locked = (key) => info?.locked.includes(key);
  const bookLocked = (key) => info?.book_locked?.includes(key);
  const names = $derived(app.models.names ?? []);
  const chatNames = $derived(names.filter((n) => !n.toLowerCase().includes('embed')));
  // Secili deger listede yoksa (LM Studio kapali) yine de gorunsun.
  const withCurrent = (list, current) => (current && !list.includes(current) ? [current, ...list] : list);
  const embedNames = $derived(withCurrent([...names.filter((n) => n.toLowerCase().includes('embed')),
    ...names.filter((n) => !n.toLowerCase().includes('embed'))], cfg?.embedding_model));
  const visionNames = $derived(withCurrent([...chatNames.filter((n) => n.toLowerCase().includes('ocr')),
    ...chatNames.filter((n) => !n.toLowerCase().includes('ocr'))], cfg?.vision_model));

  $effect(() => {
    if (!cfg) return;
    const path = cfg.tesseract_path;
    call('check_tesseract', path).then((r) => (tesseract = r?.found ?? ''));
  });
  $effect(() => {
    if (!cfg) return;
    const path = cfg.whisper_cuda_dir;
    call('check_cuda_dir', path).then((r) => (cuda = r ?? { message: '' }));
  });

  // F152: model sunucusu; API anahtari isletim sistemi deposunda, adresin yeri gizlilik uyarisi icin.
  let apiKey = $state('');
  let serverScope = $state('local');
  $effect(() => {
    if (!cfg) return;
    const url = cfg.base_url;
    call('llm_scope', url).then((r) => (serverScope = r?.scope ?? 'local'));
  });
  function applyPreset(id) {
    const preset = info.llm.presets.find((p) => p.id === id);
    if (preset) { cfg.base_url = preset.base_url; cfg.provider = preset.provider; }
  }
  async function saveApiKey(value) {
    const r = await act('llm_set_api_key', value);
    if (r) { info.llm.api_key_set = r.api_key_set; apiKey = ''; toast(value ? 'API anahtarı kaydedildi.' : 'API anahtarı silindi.', 'ok'); }
  }

  // F89: Gmail uygulama sifresi config.json'a degil isletim sistemi deposuna yazilir.
  let mail = $state({ address: '', has_password: false });
  let mailPassword = $state('');
  let mailStatus = $state(null);
  call('mail_account').then((r) => r && (mail = r));
  async function saveMailPassword(value) {
    const r = await act('mail_set_password', value);
    if (r) { mail = r; mailPassword = ''; mailStatus = null; toast(value ? 'Uygulama şifresi kaydedildi.' : 'Uygulama şifresi silindi.', 'ok'); }
  }
  async function testMail() {
    mailStatus = { busy: true, message: 'Bağlanıyor…' };
    mailStatus = (await call('mail_test')) ?? null;
  }

  // F94: Backlog sitesi; genel sohbette soruda gecen oyun/anime/film/kitap basliklari aranir.
  let backlogStatus = $state(null);
  async function testBacklog() {
    backlogStatus = { busy: true, message: 'Bağlanıyor…' };
    backlogStatus = (await call('backlog_test', cfg.backlog_url)) ?? null;
  }

  // F197 kitap gorselleri: ComfyUI adresi, is akisi (API formati, Aktar kopyasini saklar), gorsel boyutu (ui.json 'art').
  let art = $state(null);            // art_options
  let artCheck = $state(null);       // {ok, message} | {error}
  let artBusy = $state(false);
  call('art_options').then((r) => { if (r && !r.error) art = r; });
  function setArt(values) {
    art = { ...art, ...values };
    artCheck = null;
    savePref({ art: { ...(app.prefs.art ?? {}), ...values } });
  }
  async function pickWorkflow() {
    const path = await call('choose_file', 'ComfyUI iş akışı (API formatı)', ['JSON (*.json)']);
    if (!path) return;
    const result = await act('art_set_workflow', path);
    if (result) { art = { ...art, workflow: result }; toast('İş akışı kaydedildi.', 'ok'); }
  }
  async function testArt() {
    artBusy = true;
    artCheck = await call('art_check', art.url);
    artBusy = false;
  }

  async function save() {
    saving = true;
    const result = await act('save_settings', $state.snapshot(cfg));
    saving = false;
    if (result) {
      cfg = result.config;
      saved = JSON.stringify(cfg);
      toast('Ayarlar kaydedildi.', 'ok');
      call('mail_account').then((r) => r && (mail = r));
    }
  }

  function reset() {
    for (const key of Object.keys(info.defaults)) if (!locked(key)) cfg[key] = info.defaults[key];
    for (const key of Object.keys(info.book_defaults ?? {})) if (!bookLocked(key)) cfg.book[key] = info.book_defaults[key];
  }

  async function browse(key, folder) {
    const path = folder ? await call('choose_folder', 'Klasör seç') : await call('choose_file', 'Program seç', []);
    if (path) cfg[key] = path;
  }

  // Kategoriler: solda liste, sagda yalnizca secili kategori. Son secim ui.json'da (settings_tab);
  // baska sayfa app.settingsTab'i ayarlayip buraya gelerek ilgili kategoriyi acabilir.
  // keys: kategori basina "kaydedilmemis degisiklik" noktasi icin config anahtarlari ('book.' = "book" bolumu).
  const CATS = [
    { id: 'models', label: 'Modeller', icon: 'cpu', keys: ['base_url', 'provider', 'model', 'qa_model', 'disable_thinking'] },
    { id: 'appearance', label: 'Görünüm', icon: 'palette', keys: [] },
    { id: 'subtitles', label: 'Altyazı çevirisi', icon: 'languages', keys: ['source_language', 'target_language', 'glossary_strict', 'auto_retry_count', 'batch_cues', 'analysis_chunk_chars'] },
    { id: 'books', label: 'Kitap çevirisi', icon: 'bookA', keys: ['auto_retry_count', 'book.'] },
    { id: 'art', label: 'Kitap görselleri', icon: 'image', keys: [] },
    { id: 'library', label: 'Kütüphane ve belgeler', icon: 'library', keys: ['embedding_model', 'vision_model', 'ocr_engine', 'ocr_model', 'tesseract_path', 'tesseract_lang'] },
    { id: 'chat', label: 'Sohbet', icon: 'message', keys: ['qa_context_chars'] },
    { id: 'voice', label: 'Ses', icon: 'mic', keys: ['whisper_model', 'whisper_device', 'whisper_language', 'whisper_cuda_dir'] },
    { id: 'video', label: 'Video', icon: 'film', keys: ['player_engine', 'mpv_output', 'mpv_hwdec', 'video_hw', 'video_direct_hevc'] },
    { id: 'connections', label: 'Bağlantılar', icon: 'mail', keys: ['mail_address', 'backlog_url'] },
    { id: 'advanced', label: 'Gelişmiş', icon: 'settings', keys: ['max_tokens', 'timeout_seconds', 'temperature'] },
  ];
  if (!CATS.some((c) => c.id === app.settingsTab)) app.settingsTab = 'models';
  const tab = $derived(app.settingsTab);

  function pick(id) {
    query = '';
    app.settingsTab = id;
    savePref({ settings_tab: id });
    content?.closest('.page-body')?.scrollTo({ top: 0 });
  }

  const changed = $derived.by(() => {
    if (!cfg || !dirty) return {};
    const before = JSON.parse(saved);
    const differs = (key) => key.endsWith('.')
      ? JSON.stringify(cfg[key.slice(0, -1)]) !== JSON.stringify(before[key.slice(0, -1)])
      : JSON.stringify(cfg[key]) !== JSON.stringify(before[key]);
    return Object.fromEntries(CATS.map((c) => [c.id, c.keys.some(differs)]));
  });

  // Arama: tum kategoriler gosterilir; eslesmeyen satirlar ve bolumler gizlenir. Bolum basligi eslesirse
  // bolumun tamami gorunur. Satirlarin cogu alt bilesenlerde (VoiceSettings, TemplateEditor) oldugu icin
  // suzme cizilen sayfa uzerinde yapilir.
  let query = $state('');
  let content = $state();
  let hits = $state(1);
  const searching = $derived(query.trim().length > 0);

  $effect(() => {
    const needle = query.trim().toLocaleLowerCase('tr');
    if (!content) return;
    tick().then(() => {
      let found = 0;
      for (const body of content.querySelectorAll('.cat-body')) {
        let visible = 0;
        for (const section of body.querySelectorAll(':scope > section, :scope > * > section')) {
          const head = section.querySelector(':scope > h2, :scope > .head');
          const whole = !needle || (head?.textContent ?? '').toLocaleLowerCase('tr').includes(needle);
          let shown = 0;
          for (const item of section.children) {
            if (item === head) continue;
            const match = whole || item.textContent.toLocaleLowerCase('tr').includes(needle);
            item.hidden = !match;
            if (match && item.matches('.fr, .tpl, .themes')) shown++;
          }
          section.hidden = !whole && !shown;
          if (!section.hidden) visible++;
        }
        body.classList.toggle('empty-cat', !!needle && !visible);
        found += visible;
      }
      hits = found;
    });
  });

  // Tema onizlemesi: paletin birkac rengiyle kucuk bir pencere cizimi.
  const choices = $derived([{ id: 'system', name: 'Sistem', system: true }, ...app.themes]);
  const preview = (theme) => (theme.system ? resolveTheme('system', app.themes) : theme)?.palette ?? {};

  // Kitap Cevir'e ozel (config.json "book" bolumu; Cevirgec ayarlari).
  const bookNumbers = [
    ['chunk_chars', 'Parça boyutu (karakter)', 'Bölümler bu uzunlukta parçalara bölünerek çevrilir.', 1, 1000000],
    ['max_tokens', 'Çıktı token payı', 'Bir çeviri yanıtı için ayrılan en fazla token.', 1, 262144],
    ['notes_max_tokens', 'Not çıktı tokenı', 'Bölüm notları yanıtı için en fazla token.', 1, 32768],
    ['fallback_context_length', 'Yedek context', 'Sunucu context bilgisini veremezse (LM Studio dışı sunucularda her zaman) kullanılır.', 1, 1048576],
    ['context_safety_tokens', 'Güvenlik payı', 'Context hesabında boş bırakılan token.', 1, 65536],
  ];

  const advanced = [
    ['max_tokens', 'Çıktı token payı', 'Bir model yanıtı için ayrılan en fazla token.', 1, 262144, 1],
    ['timeout_seconds', 'Zaman aşımı (sn)', 'Tek bir model sunucusu isteği için beklenecek en uzun süre.', 1, 86400, 1],
    ['temperature', 'Temperature', 'Düşük değer daha tutarlı çeviri verir.', 0, 2, 0.05],
  ];
</script>

<section class="page">
  <div class="page-head">
    <h1>Ayarlar</h1>
    <label class="search">
      <Icon name="search" size={15} />
      <input bind:value={query} placeholder="Ayarlarda ara" aria-label="Ayarlarda ara"
        onkeydown={(e) => { if (e.key === 'Escape') query = ''; }} />
      {#if query}<button class="icon-btn sm" title="Aramayı temizle" onclick={() => (query = '')}><Icon name="x" size={14} /></button>{/if}
    </label>
    <span class="grow"></span>
    {#if dirty}<span class="unsaved">Kaydedilmemiş değişiklik var</span>{/if}
    <button class="btn" onclick={reset} disabled={!cfg}><Icon name="rotate" size={16} />Varsayılanlar</button>
    <button class="btn primary" onclick={save} disabled={!cfg || saving || !dirty}><Icon name="check" size={16} />Kaydet</button>
  </div>

  {#if cfg}
    <div class="page-body layout">
      <nav class="cats" aria-label="Ayar kategorileri">
        {#each CATS as c (c.id)}
          <button class="cat" class:on={!searching && tab === c.id} onclick={() => pick(c.id)}>
            <Icon name={c.icon} size={18} /><span>{c.label}</span>{#if changed[c.id]}<i class="dot" title="Kaydedilmemiş değişiklik"></i>{/if}
          </button>
        {/each}
      </nav>
      <div class="col" bind:this={content}>
      <div class="cat-body" data-cat="models" hidden={!searching && tab !== 'models'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'models').label}</div>{/if}
          <section>
            <h2>Model sunucusu</h2>
            {#if info.locked.length}<div class="warn"><Icon name="alert" size={16} />Çeviri sürerken model ve bağlantı ayarları değiştirilemez.</div>{/if}
            <div class="fr">
              <div class="l">Hazır ayar<small>Adresi ve sunucu türünü doldurur; sonra değiştirebilirsiniz.</small></div>
              <select class="field w" value="" disabled={locked('base_url')} onchange={(e) => { applyPreset(e.currentTarget.value); e.currentTarget.value = ''; }}>
                <option value="">Seçin…</option>
                {#each info.llm?.presets ?? [] as p}<option value={p.id}>{p.label} · {p.base_url}</option>{/each}
              </select>
            </div>
            <div class="fr">
              <div class="l">Sunucu türü<small>LM Studio'da modeller kalıcı yüklenir ve gerçek bağlam uzunluğu okunur. OpenAI uyumlu türde (Ollama, llama.cpp, vLLM, OpenAI, OpenRouter…) yalnızca standart istekler gönderilir; kitap çevirisinde bağlam uzunluğu Kitap çevirisi ayarlarındaki yedek değerdir.</small></div>
              <select class="field w" bind:value={cfg.provider} disabled={locked('provider')}>
                <option value="lmstudio">LM Studio</option>
                <option value="openai">OpenAI uyumlu</option>
              </select>
            </div>
            <div class="fr">
              <div class="l">Sunucu adresi<small>Bu bilgisayar ve yerel ağ için http, internetteki sunucular için https.</small></div>
              <input class="field w" bind:value={cfg.base_url} disabled={locked('base_url')} placeholder="http://127.0.0.1:1234/v1" />
            </div>
            {#if serverScope === 'internet'}
              <div class="warn"><Icon name="alert" size={16} />Çevrilen, sorulan ve özetlenen metinler bu bilgisayardan çıkıp internetteki bu sunucuya gönderilir. "Hiçbir veri internete gönderilmez" güvencesi bu sunucu için geçerli değildir.</div>
            {:else if serverScope === 'lan'}
              <div class="note-row"><Icon name="info" size={16} />Metinler yerel ağdaki bu sunucuya gönderilir; internete çıkmaz.</div>
            {/if}
            <div class="fr">
              <div class="l">API anahtarı<small>Gerekiyorsa (OpenAI, OpenRouter ya da anahtar isteyen yerel sunucu). İşletim sisteminin şifre deposunda saklanır, config.json'a yazılmaz.</small>
                {#if info.llm?.api_key_set}<small class="okc">Kayıtlı</small>{/if}</div>
              <div class="pick">
                <input class="field w2" type="password" bind:value={apiKey} placeholder={info.llm?.api_key_set ? '••••••••••••' : 'sk-…'} autocomplete="off" />
                <button class="btn sm" disabled={!apiKey.trim()} onclick={() => saveApiKey(apiKey.trim())}>Kaydet</button>
                {#if info.llm?.api_key_set}<button class="btn sm ghost" onclick={() => saveApiKey('')} title="Anahtarı sil">Sil</button>{/if}
              </div>
            </div>
            <div class="fr">
              <div class="l">Analiz modeli<small>Çeviri, dosya özetleri, ekstre okuma ve analiz için kullanılan model.</small></div>
              <div class="pick">
                <select class="field w" bind:value={cfg.model} disabled={locked('model')}>
                  {#each withCurrent(chatNames, cfg.model) as m}<option value={m}>{m}</option>{/each}
                </select>
                <button class="icon-btn" title="Modelleri sunucudan yeniden getir" disabled={app.models.state === 'probing'}
                  onclick={() => call('refresh_models')}><Icon name="refresh" size={16} spin={app.models.state === 'probing'} /></button>
              </div>
            </div>
            <div class="fr">
              <div class="l">Soru-cevap modeli<small>Koleksiyon, belge ve video sohbetini cevaplayan model. Ayrı (ör. daha küçük) bir model seçilebilir.</small></div>
              <select class="field w" bind:value={cfg.qa_model}>
                <option value="">(analiz modeliyle aynı)</option>
                {#each withCurrent(chatNames, cfg.qa_model) as m}<option value={m}>{m}</option>{/each}
              </select>
            </div>
            {#if app.models.state === 'failed'}<p class="err small selectable">{app.models.message}</p>{/if}
            <div class="fr">
              <div class="l">Thinking kapat<small>Analiz, çeviri, özet ve indeksleme gibi arka plan işlerinde düşünme (reasoning) kapatılır. Sohbetlerde soru kutusundaki beyin düğmesi geçerlidir.</small></div>
              <Toggle bind:checked={cfg.disable_thinking} disabled={locked('disable_thinking')} />
            </div>
          </section>
      </div>

      <div class="cat-body" data-cat="appearance" hidden={!searching && tab !== 'appearance'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'appearance').label}</div>{/if}
          <section>
            <h2>Görünüm</h2>
            <div class="themes">
              {#each choices as theme (theme.id)}
                {@const p = preview(theme)}
                <button class="theme" class:on={app.themeId === theme.id} disabled={!!theme.error} title={theme.error ?? ''}
                  onclick={() => setTheme(theme.id)}>
                  <span class="mini" style:background={p.window} style:border-color={p.outline}>
                    <span class="mini-side" style:background={p.panel}><i style:background={p.accent}></i><i style:background={p.dim}></i><i style:background={p.dim}></i></span>
                    <span class="mini-main"><i style:background={p.text}></i><i style:background={p.secondary}></i><b style:background={p.accent}></b></span>
                  </span>
                  <span class="tname">
                    {#if theme.system}<Icon name="monitor" size={14} />{/if}{theme.name}
                  </span>
                  {#if theme.error}<span class="terr">Bozuk dosya</span>{/if}
                </button>
              {/each}
            </div>
            <div class="row-actions">
              <button class="btn sm" onclick={() => act('open_themes_folder')}><Icon name="folderOpen" size={14} />Temalar klasörünü aç</button>
              <button class="btn sm" onclick={reloadThemes}><Icon name="refresh" size={14} />Yeniden yükle</button>
            </div>
          </section>
      </div>

      <div class="cat-body" data-cat="subtitles" hidden={!searching && tab !== 'subtitles'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'subtitles').label}</div>{/if}
          <section>
            <h2>Altyazı çevirisi</h2>
            <div class="fr">
              <div class="l">Kaynak dil<small>Altyazının ve yeni kitap projelerinin dili. Otomatik seçilirse dili model tanır. Açık kitap projeleri oluşturuldukları dil çiftini korur.</small></div>
              <select class="field" bind:value={cfg.source_language} disabled={locked('source_language')}>
                <option value="auto">Otomatik</option>
                {#each info.languages ?? [] as l}<option value={l.code}>{l.label}</option>{/each}
              </select>
            </div>
            <div class="fr">
              <div class="l">Hedef dil<small>Çeviri dili. Çıktı dosyası bu dilin kodunu ek olarak alır (_TR, _DE, _JA…). Seri sözlükleri tek hedef dile aittir.</small></div>
              <select class="field" bind:value={cfg.target_language} disabled={locked('target_language')}>
                {#each info.languages ?? [] as l}<option value={l.code}>{l.label}</option>{/each}
              </select>
            </div>
            <div class="fr">
              <div class="l">Katı sözlük<small>Açıkken uygulanamayan terimde çeviri durur; kapalıyken uyarı günlüğe yazılır ve çeviri sürer. Yalnızca altyazı çevirisi için.</small></div>
              <Toggle bind:checked={cfg.glossary_strict} disabled={locked('glossary_strict')} />
            </div>
            <div class="fr">
              <div class="l">Otomatik tekrar sayısı<small>İlk istek hariç ek deneme: 2 seçilirse en fazla 3 istek yapılır. Kitap çevirisiyle ortaktır.</small></div>
              <input class="field n" type="number" min="1" max="100" bind:value={cfg.auto_retry_count} disabled={locked('auto_retry_count')} />
            </div>
            <div class="fr">
              <div class="l">Parti boyutu<small>Tek istekte modele gönderilen altyazı girdisi sayısı.</small></div>
              <input class="field n" type="number" min="1" max="200" bind:value={cfg.batch_cues} disabled={locked('batch_cues')} />
            </div>
            <div class="fr">
              <div class="l">Analiz parça karakteri<small>Ön analizde modele tek seferde giden en fazla altyazı metni.</small></div>
              <input class="field n" type="number" min="1" max="200000" bind:value={cfg.analysis_chunk_chars} disabled={locked('analysis_chunk_chars')} />
            </div>
          </section>
      </div>

      <div class="cat-body" data-cat="books" hidden={!searching && tab !== 'books'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'books').label}</div>{/if}
          {#if cfg.book}
          <section>
            <h2>Kitap çevirisi</h2>
            <p class="hint-line">Sunucu ve model Modeller'den, temperature ve zaman aşımı Gelişmiş'ten gelir.</p>
            {#if info.book_locked?.length}<div class="warn"><Icon name="alert" size={16} />Kitap çevirisi sürerken parça ve token ayarları değiştirilemez.</div>{/if}
            <div class="fr">
              <div class="l">Katı sözlük<small>Açıkken uygulanamayan terimde çeviri durur; kapalıyken uygulanamayan terim kitap klasöründeki glossary_fixes.log dosyasına yazılır ve çeviri sürer. Yalnızca kitap çevirisi için.</small></div>
              <Toggle bind:checked={cfg.book.glossary_strict} />
            </div>
            <div class="fr">
              <div class="l">Otomatik tekrar sayısı<small>İlk istek hariç ek deneme: 2 seçilirse en fazla 3 istek yapılır. Altyazı çevirisiyle ortaktır.</small></div>
              <input class="field n" type="number" min="1" max="100" bind:value={cfg.auto_retry_count} disabled={locked('auto_retry_count')} />
            </div>
            <div class="fr">
              <div class="l">Bitiş işareti denetimi<small>Uzun yanıtlarda modelin bitiş işaretini üretmesi gerekir; eksik sonuçlar kaydedilmez.</small></div>
              <Toggle bind:checked={cfg.book.completion_marker_enabled} />
            </div>
            <div class="fr">
              <div class="l">İşaretsiz sınır (karakter)<small>Bu uzunluk ve altındaki parçalarda bitiş işareti aranmaz.</small></div>
              <input class="field n" type="number" min="0" max="1000000" bind:value={cfg.book.completion_marker_exempt_chars} disabled={!cfg.book.completion_marker_enabled} />
            </div>
            {#each bookNumbers as [key, title, hint, min, max]}
              <div class="fr">
                <div class="l">{title}<small>{hint}</small></div>
                <input class="field n" type="number" {min} {max} bind:value={cfg.book[key]} disabled={bookLocked(key)} />
              </div>
            {/each}
            <div class="fr">
              <div class="l">Token tahmini<small>İstek göndermeden önce context sınırı tahmin edilerek denetlenir.</small></div>
              <Toggle bind:checked={cfg.book.token_estimation_enabled} disabled={bookLocked('token_estimation_enabled')} />
            </div>
            <div class="fr">
              <div class="l">EPUBCheck ile doğrula<small>EPUB oluşturulduktan sonra harici EPUBCheck çalıştırılır. JAR için Java gerekir.</small></div>
              <Toggle bind:checked={cfg.book.epubcheck_enabled} />
            </div>
            <div class="fr">
              <div class="l">EPUBCheck yolu<small>Boşsa PATH içindeki epubcheck kullanılır; .jar veya .exe olabilir.</small></div>
              <input class="field w" bind:value={cfg.book.epubcheck_path} placeholder="epubcheck" />
            </div>
          </section>
          {/if}
      </div>

      <div class="cat-body" data-cat="library" hidden={!searching && tab !== 'library'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'library').label}</div>{/if}
          <section>
            <h2>Kütüphane indeksi ve görsel okuma</h2>
            <div class="fr">
              <div class="l">Embedding modeli<small>Transkriptleri aranabilir yapan model (ör. text-embedding-embeddinggemma-2). Kapalıysa yalnızca transkript çıkarılır.</small></div>
              <select class="field w" bind:value={cfg.embedding_model}>
                <option value="">(kapalı)</option>
                {#each embedNames as m}<option value={m}>{m}</option>{/each}
              </select>
            </div>
            <div class="fr">
              <div class="l">Görü modeli<small>Görselleri tarif edip içindeki yazıları okuyan model; görsel destekli olmalı.</small></div>
              <select class="field w" bind:value={cfg.vision_model}>
                <option value="">(analiz modeliyle aynı)</option>
                {#each visionNames as m}<option value={m}>{m}</option>{/each}
              </select>
            </div>
            <div class="fr">
              <div class="l">OCR motoru<small>Taranmış PDF sayfalarını okuyan motor. Görseller her zaman görü modeliyle okunur.</small></div>
              <select class="field w" bind:value={cfg.ocr_engine}>
                {#each info.ocr_engines as engine}<option value={engine.id}>{engine.label}</option>{/each}
              </select>
            </div>
            <div class="fr">
              <div class="l">OCR modeli<small>Taranmış sayfalar için OCR'a özel küçük model (ör. glm-ocr); hızlıdır ve metin uydurmaz.</small></div>
              <select class="field w" bind:value={cfg.ocr_model}>
                <option value="">(seçilmedi)</option>
                {#each withCurrent(chatNames, cfg.ocr_model) as m}<option value={m}>{m}</option>{/each}
              </select>
            </div>
            <div class="fr">
              <div class="l">Tesseract<small class:okc={tesseract}>{tesseract ? 'Bulundu: ' + tesseract : 'Bulunamadı (OCR motoru Tesseract seçilirse gerekir).'}</small></div>
              <div class="pick">
                <input class="field w2" bind:value={cfg.tesseract_path} placeholder="Boş: otomatik bul" />
                <button class="btn sm" onclick={() => browse('tesseract_path', false)}>Gözat…</button>
              </div>
            </div>
            <div class="fr">
              <div class="l">Tesseract dili<small>Dil kodları, ör. tur+eng.</small></div>
              <input class="field n" bind:value={cfg.tesseract_lang} placeholder="tur+eng" />
            </div>
          </section>
      </div>

      <div class="cat-body" data-cat="chat" hidden={!searching && tab !== 'chat'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'chat').label}</div>{/if}
          <TemplateEditor />

          <section>
            <h2>Soru-cevap</h2>
            <div class="fr">
              <div class="l">Bağlam karakteri<small>Genel sohbet, koleksiyon, belge ve video sorularında modele tek istekte giden en fazla metin (karakter, token değil; Türkçede ~3 karakter = 1 token). Aşılırsa yalnızca ilgili parçalar gider. LM Studio bağlam uzunluğunu aşmayın: 122k token için ~300000.</small></div>
              <input class="field n" type="number" min="1000" max="1000000" step="1000" bind:value={cfg.qa_context_chars} />
            </div>
          </section>
      </div>

      <div class="cat-body" data-cat="voice" hidden={!searching && tab !== 'voice'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'voice').label}</div>{/if}
          <section>
            <FoldHead key="whisper" title="Konuşmadan metin (Whisper)" open={isOpen('whisper') || searching} />
            {#if isOpen('whisper') || searching}
            <div class="fr">
              <div class="l">Whisper modeli<small>İlk kullanımda models/whisper altına indirilir (large-v3-turbo ~1,6 GB).</small></div>
              <select class="field n" bind:value={cfg.whisper_model}>
                {#each info.whisper_models as m}<option value={m}>{m}</option>{/each}
              </select>
            </div>
            <div class="fr">
              <div class="l">Cihaz<small>auto: NVIDIA GPU (CUDA) varsa onu, yoksa işlemciyi kullanır.</small></div>
              <select class="field n" bind:value={cfg.whisper_device}>
                <option value="auto">auto</option><option value="cuda">cuda</option><option value="cpu">cpu</option>
              </select>
            </div>
            <div class="fr">
              <div class="l">Konuşma dili<small>Boş: otomatik algıla (ör. en, ja, tr).</small></div>
              <input class="field n" bind:value={cfg.whisper_language} placeholder="otomatik" />
            </div>
            <div class="fr">
              <div class="l">Sohbetlerde mikrofon düğmesi<small>Kapalıyken sohbet kutularındaki mikrofon (konuşmayı yazıya dökme) düğmesi gösterilmez. Sesli mod bundan etkilenmez.</small></div>
              <Toggle checked={app.prefs.mic_button !== false} onchange={(value) => savePref({ mic_button: value })} />
            </div>
            <div class="fr">
              <div class="l">GPU kütüphane klasörü<small class:okc={cuda.ok} class:errc={cuda.ok === false}>{cuda.message || 'Boş: pip ile kurulan ya da pakete gömülü cuBLAS 12 / cuDNN 9.'}</small></div>
              <div class="pick">
                <input class="field w2" bind:value={cfg.whisper_cuda_dir} placeholder="Boş: otomatik" />
                <button class="btn sm" onclick={() => browse('whisper_cuda_dir', true)}>Gözat…</button>
              </div>
            </div>
            {/if}
          </section>

          <VoiceSettings {searching} />
      </div>

      <div class="cat-body" data-cat="video" hidden={!searching && tab !== 'video'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'video').label}</div>{/if}
          <section>
            <h2>Video oynatma</h2>
            {#if info.mpv}
              <div class="fr">
                <div class="l">Oynatıcı motoru<small>mpv: her biçim (HEVC, 10 bit, MKV, AC3/DTS) dönüştürmeden, ekran kartıyla çözülerek oynatılır; ASS ve karaoke altyazılar gerçek haliyle görünür. WebView: uygulama içi tarayıcı; çözemediği videolar ffmpeg ile dönüştürülür.</small></div>
                <select class="field w" bind:value={cfg.player_engine}>
                  <option value="mpv">mpv (gömülü, önerilen)</option>
                  <option value="web">WebView</option>
                </select>
              </div>
              {#if cfg.player_engine === 'mpv'}
                <div class="fr">
                  <div class="l">mpv görüntü çıkışı<small>Ses gelip görüntü siyah kalıyorsa diğer seçenekleri deneyin. Seçim bir sonraki videoda uygulanır; Konsol'daki "[mpv] Çıkış:" satırı kullanılan çıkışı gösterir.</small></div>
                  <select class="field w" bind:value={cfg.mpv_output}>
                    <option value="next">gpu-next (Direct3D 11, önerilen)</option>
                    <option value="safe">Uyumlu (Direct3D 11, eski sunum)</option>
                  </select>
                </div>
                <div class="fr">
                  <div class="l">mpv donanım çözme<small>Kapalıyken video işlemcide çözülür (daha çok işlemci kullanır ama ekran kartı sürücüsü sorunlarından etkilenmez).</small></div>
                  <Toggle bind:checked={cfg.mpv_hwdec} />
                </div>
              {/if}
            {/if}
            {#if !info.mpv || cfg.player_engine !== 'mpv'}
            <div class="fr">
              <div class="l">Dönüştürmede donanım hızlandırma<small>Oynatıcı bir videoyu çözemezse (örn. HEVC/x265) anında H.264'e dönüştürür. GPU kodlayıcısı işlemciyi rahatlatır ve takılmayı azaltır; çalışmazsa oynatıcı kendiliğinden işlemciye geçer.
                {#if info.video_encoders?.length}<br />Bu bilgisayarda: {info.video_encoders.some((e) => e.works === null) ? 'denetleniyor…'
                  : info.video_encoders.filter((e) => e.works).map((e) => e.label).join(', ') || 'çalışan GPU kodlayıcısı bulunamadı'}{/if}</small></div>
              <select class="field w" bind:value={cfg.video_hw}>
                <option value="auto">Otomatik (GPU varsa)</option>
                {#each info.video_encoders ?? [] as e}<option value={e.id}>{e.label}{e.works === false ? ' (çalışmıyor)' : ''}</option>{/each}
                <option value="off">Yalnız işlemci</option>
              </select>
            </div>
            <div class="fr">
              <div class="l">HEVC'yi WebView ile doğrudan oynat<small>Açıkken HEVC/x265 videoyu WebView kendisi çözer (bilgisayarda HEVC çözücüsü varsa). Bu videolar takılıyorsa kapatın: HEVC her zaman yukarıdaki kodlayıcıyla H.264'e dönüştürülür.</small></div>
              <Toggle bind:checked={cfg.video_direct_hevc} />
            </div>
            {/if}
          </section>
      </div>

      <div class="cat-body" data-cat="art" hidden={!searching && tab !== 'art'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'art').label}</div>{/if}
          <section>
            <h2>Kitap görselleri (ComfyUI)</h2>
            <div class="fr">
              <div class="l">ComfyUI adresi<small>Kitaplıkta kitaba sağ tıklayıp "Kitap görselleri" deyince görseller bu ComfyUI'de üretilir. ComfyUI'yi siz açarsınız (Aktar başlatmaz); aynı bilgisayarda varsayılan adres çalışır.</small></div>
              <input class="field w" value={art?.url ?? ''} placeholder="http://127.0.0.1:8188" spellcheck="false" disabled={!art}
                onchange={(e) => setArt({ comfy_url: e.currentTarget.value.trim(), url: e.currentTarget.value.trim() })} />
            </div>
            <div class="fr">
              <div class="l">İş akışı<small>ComfyUI'de iş akışını "Export (API)" ile dışa aktarıp seçin. Aktar düğümleri başlıklarından bulur: "Positive" (sahne istemi), varsa "PRE-PROMPT" (kitabın stili) ve "POST-PROMPT" (yazı istememe), seed, boyut ve SaveImage. Negatif istem CFG 1'de çalışmaz, kullanılmaz.</small>
                {#if art}<small class:okc={art.workflow.ok} class:errc={!art.workflow.ok}>{art.workflow.message}</small>{/if}</div>
              <button class="btn sm" disabled={!art} onclick={pickWorkflow}><Icon name="folderOpen" size={14} />Seç…</button>
            </div>
            <div class="fr">
              <div class="l">Görsel boyutu<small>Tam ekran okuyucu için 16:9. Büyük boyut daha yavaş üretilir; yeni planlarda geçerli olur.</small></div>
              <select class="field" value={art?.size ?? '1344x768'} disabled={!art} onchange={(e) => setArt({ size: e.currentTarget.value })}>
                {#each art?.sizes ?? [] as size (size)}<option value={size}>{size.replace('x', ' × ')}</option>{/each}
              </select>
            </div>
            <div class="fr">
              <div class="l">Bağlantı<small class:okc={artCheck?.ok} class:errc={artCheck?.error}>{artCheck ? (artCheck.error ?? artCheck.message) : 'ComfyUI açık mı ve iş akışı uygun mu, dener.'}</small></div>
              <button class="btn sm" disabled={!art || artBusy} onclick={testArt}><Icon name="refresh" size={14} />{artBusy ? 'Deneniyor…' : 'Bağlantıyı dene'}</button>
            </div>
          </section>
      </div>

      <div class="cat-body" data-cat="connections" hidden={!searching && tab !== 'connections'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'connections').label}</div>{/if}
          <section>
            <h2>E-posta (Gmail)</h2>
            <div class="fr">
              <div class="l">Gmail adresi<small>Koleksiyonlardaki "E-postadan al" kuralları bu hesaptaki postalara bakar. Değiştirdikten sonra Kaydet'e basın.</small></div>
              <input class="field w" type="email" bind:value={cfg.mail_address} placeholder="ad@gmail.com" />
            </div>
            <div class="fr">
              <div class="l">Uygulama şifresi
                <small>Normal Google şifreniz değil: Google hesabı → Güvenlik → 2 adımlı doğrulama → Uygulama şifreleri'nden alınan 16 harflik şifre. Windows Kimlik Bilgileri'nde saklanır, config.json'a yazılmaz.</small>
                {#if mail.has_password}<small class="okc">Kayıtlı ({mail.address})</small>{/if}</div>
              <div class="pick">
                <input class="field w2" type="password" bind:value={mailPassword} placeholder={mail.has_password ? '•••• •••• •••• ••••' : 'abcd efgh ijkl mnop'} autocomplete="off"
                  disabled={!mail.address || dirty} />
                <button class="btn sm" disabled={!mailPassword.trim()} onclick={() => saveMailPassword(mailPassword.trim())}>Kaydet</button>
                {#if mail.has_password}<button class="btn sm ghost" onclick={() => saveMailPassword('')} title="Şifreyi sil">Sil</button>{/if}
              </div>
            </div>
            <div class="fr">
              <div class="l">Bağlantı<small class:okc={mailStatus?.ok} class:errc={mailStatus?.ok === false}>{mailStatus?.message ?? (mail.address && !mail.has_password ? 'Uygulama şifresini kaydedin.' : "Gmail'e giriş yapıp tüm postalar kutusunu bulur.")}</small></div>
              <button class="btn sm" disabled={!mail.has_password || mailStatus?.busy || dirty} onclick={testMail}><Icon name="mail" size={14} />Bağlantıyı dene</button>
            </div>
          </section>

          <section>
            <h2>Backlog sitesi</h2>
            <div class="fr">
              <div class="l">Site adresi<small>Genel sohbette sorudaki oyun, anime, manga, film ve kitap adları bu sitede aranır ("Cyberpunk 2077'ye Steam'de mi sahiptim?"). Boş: kapalı.</small></div>
              <input class="field w" type="url" bind:value={cfg.backlog_url} placeholder="https://site.pages.dev" />
            </div>
            <div class="fr">
              <div class="l">Bağlantı<small class:okc={backlogStatus?.ok} class:errc={backlogStatus?.ok === false}>{backlogStatus?.message ?? 'Başlık listesini çekmeyi dener.'}</small></div>
              <button class="btn sm" disabled={!cfg.backlog_url?.trim() || backlogStatus?.busy} onclick={testBacklog}>Bağlantıyı dene</button>
            </div>
          </section>
      </div>

      <div class="cat-body" data-cat="advanced" hidden={!searching && tab !== 'advanced'}>
        {#if searching}<div class="cat-label">{CATS.find((c) => c.id === 'advanced').label}</div>{/if}
          <section>
            <h2>Gelişmiş</h2>
            <div class="fr">
              <div class="l">Sürüm<small>Değişiklikler depodaki CHANGELOG.md dosyasındadır.</small></div>
              <span class="mono selectable">Aktar {app.version || '?'}</span>
            </div>
            <div class="fr">
              <div class="l">Bileşen denetimi<small>Model sunucusu, FFmpeg, Whisper, ses motorları, Tesseract, libmpv ve Calibre kurulu mu; eksikse nasıl kurulur.</small></div>
              <button class="btn sm" onclick={() => (app.setup = true)}><Icon name="check" size={14} />Denetle</button>
            </div>
            <div class="warn"><Icon name="alert" size={16} />Bu ayarlar deneyseldir; ne yaptığınızdan emin değilseniz değiştirmeyin.</div>
            {#each advanced as [key, title, hint, min, max, step]}
              <div class="fr">
                <div class="l">{title}<small>{hint}</small></div>
                <input class="field n" type="number" {min} {max} {step} bind:value={cfg[key]} disabled={locked(key)} />
              </div>
            {/each}
          </section>
      </div>
        {#if searching && !hits}<p class="none">"{query}" ile eşleşen ayar yok.</p>{/if}
      </div>
    </div>
  {/if}
</section>

<style>
  .search { display: flex; align-items: center; gap: 6px; width: 280px; height: 36px; padding: 0 6px 0 12px; margin-left: 12px;
    border-radius: 999px; background: var(--surface); color: var(--dim); }
  .search input { flex: 1; min-width: 0; height: 100%; background: transparent; border: 0; outline: 0; color: var(--text); font: inherit; }
  .search:focus-within { box-shadow: 0 0 0 2px var(--accent); }
  .page-head .grow { flex: 1; }
  .page-head h1 { margin-right: 0; }
  .layout { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 32px; align-items: start; }
  .cats { position: sticky; top: 0; display: flex; flex-direction: column; gap: 2px; }
  .cat { display: flex; align-items: center; gap: 12px; padding: 9px 12px; border-radius: 8px; color: var(--secondary); font-weight: 600; text-align: left; }
  .cat:hover { color: var(--text); background: var(--surface-hover); }
  .cat.on { color: var(--text); background: var(--surface); }
  .cat.on :global(svg) { color: var(--accent); }
  .cat span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); flex: none; }
  .cat-body { display: flex; flex-direction: column; gap: 28px; }
  /* Arama ve kategori secimi [hidden] ile gizler; display: flex olan satirlar da gizlensin. */
  .col :global([hidden]) { display: none !important; }
  /* Dar pencerede kategori listesi icerigin ustunde, satir satir dugmeler olur. */
  @media (max-width: 1200px) {
    .layout { grid-template-columns: minmax(0, 1fr); gap: 18px; }
    .cats { position: static; flex-direction: row; flex-wrap: wrap; gap: 6px; }
    .cat { padding: 6px 12px; border-radius: 999px; background: var(--surface); font-size: 13px; gap: 8px; }
    .cat.on { background: var(--surface-active); }
    .search { width: 220px; }
  }
  .cat-body:global(.empty-cat) { display: none; }
  .cat-label { font-size: 12px; font-weight: 700; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; margin-bottom: -16px; }
  .none { color: var(--dim); }
  .unsaved { color: var(--accent); font-size: 12px; font-weight: 600; }
  .col { max-width: 900px; display: flex; flex-direction: column; gap: 28px; }
  h2 { font-size: 20px; font-weight: 700; letter-spacing: -.01em; margin-bottom: 6px; }
  .fr { display: flex; align-items: center; gap: 20px; padding: 12px 0; border-bottom: 1px solid var(--outline); }
  .fr:last-child { border-bottom: 0; }
  .l { flex: 1; min-width: 0; font-weight: 500; }
  .l small { display: block; color: var(--dim); font-size: 12px; font-weight: 400; margin-top: 2px; }
  small.okc { color: var(--ok); }
  small.errc { color: var(--danger); }
  .field.w { width: 340px; }
  .field.w2 { width: 260px; }
  .field.n { width: 160px; }
  .pick { display: flex; align-items: center; gap: 6px; }
  .pick .field.w { width: 296px; }
  .hint-line { color: var(--dim); font-size: 12px; margin: 2px 0 4px; }
  .note-row { display: flex; gap: 8px; align-items: center; color: var(--dim); font-size: 12px; padding: 4px 0; margin: 6px 0; }
  .warn { display: flex; gap: 8px; align-items: center; color: var(--warning); font-size: 12px; background: color-mix(in srgb, var(--warning) 10%, transparent); padding: 8px 12px; border-radius: 8px; margin: 6px 0; }
  .err { color: var(--danger); }
  .small { font-size: 12px; }

  .themes { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; margin: 8px 0 12px; }
  .theme { display: flex; flex-direction: column; gap: 8px; padding: 8px; border-radius: 10px; text-align: left; }
  .theme:not(:disabled):hover { background: var(--surface-hover); }
  .theme.on { background: var(--surface); box-shadow: inset 0 0 0 2px var(--accent); }
  .mini { display: flex; height: 76px; border-radius: 6px; overflow: hidden; border: 1px solid; }
  .mini-side { width: 34%; display: flex; flex-direction: column; gap: 5px; padding: 8px 6px; }
  .mini-side i, .mini-main i { display: block; height: 5px; border-radius: 3px; }
  .mini-side i:nth-child(2) { width: 80%; } .mini-side i:nth-child(3) { width: 60%; }
  .mini-main { flex: 1; display: flex; flex-direction: column; gap: 6px; padding: 10px 8px; }
  .mini-main i:first-child { width: 70%; height: 7px; }
  .mini-main i:nth-child(2) { width: 50%; opacity: .7; }
  .mini-main b { margin-top: auto; width: 42%; height: 12px; border-radius: 999px; }
  .tname { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; padding: 0 2px; }
  .terr { color: var(--danger); font-size: 11px; padding: 0 2px; }
  .row-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
