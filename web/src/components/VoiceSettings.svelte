<script>
  import Icon from '../lib/Icon.svelte';
  import { app, act, toast, saveTtsPrefs } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import Toggle from './Toggle.svelte';
  import FoldHead from './FoldHead.svelte';
  import { isOpen, toggleOpen } from '../lib/folds.js';
  import { PAUSE_KEYS, PAUSE_PRESETS, PAUSE_DEFAULTS, resolvePauses } from '../lib/pauses.js';
  import { QUOTE_DEFAULTS } from '../lib/sentences.js';

  // F179: Ayarlar aramasi surerken butun bolumler acik (eslesen satirlar gizli bolumde kalmasin)
  let { searching = false } = $props();
  const shown = (key, fallback = true) => searching || isOpen(key, fallback);

  const LANGUAGES = { tr: 'Ses', en: 'İngilizce ses' };
  const DEFAULT_ENGINE = { tr: 'ema-lightning' };
  const DRAMA3_URL = 'http://127.0.0.1:7861';

  const usable = $derived(app.engines.filter((e) => e.mode));
  // Turkce her zaman; baska diller ancak o dilde ses veren bir motor varsa (F158: Drama 3 Ingilizce)
  const languages = $derived(['tr', ...new Set(usable.flatMap((e) => e.voices.map((v) => v.language)).filter((l) => l !== 'tr'))]);

  function options(language) {
    return usable.flatMap((engine) => engine.voices.filter((v) => v.language === language).map((voice) => ({
      value: `${engine.id}/${voice.id}`,
      label: engine.voices.length > 1 ? `${engine.name} · ${voice.name}` : engine.name,
      note: voice.downloaded || !voice.files?.length ? '' : ` — ilk kullanımda indirilir (${voice.size_mb} MB)`,
      engine: engine.id,
    })));
  }

  // Mirrors Engines.choice(): the saved choice when still usable, otherwise the default.
  function selected(language) {
    const list = options(language);
    const saved = app.ttsPrefs.voices?.[language];
    if (list.some((o) => o.value === saved)) return saved;
    // sunucu isteyen motor (Drama 3) kendiliginden secilmez
    const server = (id) => usable.find((e) => e.id === id)?.server;
    return (list.find((o) => o.engine === DEFAULT_ENGINE[language]) ?? list.find((o) => !server(o.engine)))?.value ?? '';
  }

  function choose(language, value) {
    app.ttsPrefs.voices = { ...(app.ttsPrefs.voices ?? {}), [language]: value };
    app.ttsPrefs.active_preset = '';   // F137: elle secilen ses okuyucudaki kayitli sesin yerine gecer
    saveTtsPrefs();
  }

  // Settings of the chosen voice (motor.json "options"): voice description, reference recording…
  function voiceOf(value) {
    const [engineId, voiceId] = value.split('/');
    return usable.find((e) => e.id === engineId)?.voices.find((v) => v.id === voiceId) ?? null;
  }

  function optionValue(value, option) {
    return app.ttsPrefs.options?.[value]?.[option.key] ?? option.default ?? '';
  }

  function setOption(value, key, text) {
    const all = { ...(app.ttsPrefs.options ?? {}) };
    all[value] = { ...(all[value] ?? {}), [key]: text };
    app.ttsPrefs.options = all;
    app.ttsPrefs.active_preset = '';
    saveTtsPrefs();
  }

  async function pickReference(value, key) {
    const path = await call('tts_choose_reference');
    if (path) setOption(value, key, path);
  }

  // F171: Drama 3 etiket katalogu (drama3_tags): hangi etiketlerin kullanilacagi burada secilir (ui.json
  // tts.emotion_allowed). Yeni secilen etiket icin kitap kitapliktan yeniden etiketlenmeli; kaldirilan hemen uygulanmaz.
  const STATUS = { works: 'Çalıştı', fails: 'Çalışmadı', untested: 'Denenmedi' };
  let catalog = $state(null);
  $effect(() => {
    if (app.engines.some((e) => e.emotion_tags) && !catalog) call('tts_emotion_catalog').then((c) => { if (c?.tags) catalog = c; });
  });
  const tagGroups = $derived(catalog ? [...new Set(catalog.tags.map((t) => t.group))] : []);
  const allowedTags = $derived(app.ttsPrefs.emotion_allowed ?? catalog?.tags.filter((t) => t.default).map((t) => t.tag) ?? []);
  function toggleTag(tag, on) {
    const chosen = new Set(allowedTags);
    if (on) chosen.add(tag); else chosen.delete(tag);
    app.ttsPrefs.emotion_allowed = catalog.tags.map((t) => t.tag).filter((t) => chosen.has(t));
    saveTtsPrefs();
  }
  function defaultTags() {
    delete app.ttsPrefs.emotion_allowed;
    app.ttsPrefs = { ...app.ttsPrefs };
    saveTtsPrefs();
  }

  let cache = $state(null);
  const refreshCache = async () => { cache = await call('tts_cache_info'); };
  $effect(() => { app.ttsPrepare; refreshCache(); });

  async function clearCache() {
    const yes = await confirm({
      title: 'Hazırlanan sesleri sil',
      message: 'Önceden üretilip saklanan bütün sesler silinecek; bu kitaplar yeniden okunurken ses yeniden üretilir. Devam edilsin mi?',
      ok: 'Sil', cancel: 'Vazgeç',
    });
    if (!yes) return;
    cache = await act('tts_cache_clear');
    if (cache) toast('Hazırlanan sesler silindi.');
  }

  const megabytes = (bytes) => (bytes / 1e6).toLocaleString('tr-TR', { maximumFractionDigits: bytes > 1e9 ? 0 : 1 });

  // Silence between sentences: a preset, or custom values from the details.
  const pausePrefs = $derived({ ...PAUSE_DEFAULTS, ...(app.ttsPrefs.pauses ?? {}) });
  const pauses = $derived(resolvePauses(app.ttsPrefs.pauses));
  let pauseDetails = $state(false);

  function setPauses(change, save = true) {
    app.ttsPrefs.pauses = { ...pausePrefs, ...change };
    if (save) saveTtsPrefs();
  }

  // Moving a slider turns the shown values (a preset's, perhaps) into custom ones.
  function setPause(key, value, save) {
    setPauses({ ...(PAUSE_PRESETS[pausePrefs.preset] ? pauses : {}), preset: 'custom', [key]: value }, save);
  }

  // How chapters are cut into sentences; applies when a chapter is (re)opened in the reader.
  const split = $derived({ ...QUOTE_DEFAULTS, ...(app.ttsPrefs.split ?? {}) });

  function setSplit(change, save = true) {
    app.ttsPrefs.split = { ...split, ...change };
    if (save) saveTtsPrefs();
  }

  const seconds = (value) => `${value.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} sn`;

  function setDevice(value) {
    app.ttsPrefs.device = value;
    saveTtsPrefs();
  }

  async function installFile() {
    await act('tts_install_file');
  }

  async function remove(engine) {
    const yes = await confirm({
      title: 'Ses motorunu kaldır',
      message: `${engine.name} ve indirdiği model/ses dosyaları program klasöründen silinecek. Devam edilsin mi?`,
      ok: 'Kaldır', cancel: 'Vazgeç',
    });
    if (!yes) return;
    const engines = await act('tts_remove', engine.id);
    if (engines) { app.engines = engines; toast(`${engine.name} kaldırıldı.`); }
  }

  // F158: sunucuya baglanan motor (Drama 3): adres ve saglik denetimi
  let serverCheck = $state(null);    // {ok, message} | {error}
  let checking = $state(false);

  function setServerUrl(value) {
    app.ttsPrefs.drama3_url = value.trim();
    serverCheck = null;
    saveTtsPrefs();
  }

  async function checkServer() {
    checking = true;
    serverCheck = await call('tts_server_check', app.ttsPrefs.drama3_url || DRAMA3_URL);
    checking = false;
  }

  // F173: modeli secilen klasorden calistiran motor (Drama 3 TR): klasor ve denetim
  let folderCheck = $state(null);    // {ok, message, missing} | {error}

  async function setModelFolder(value) {
    app.ttsPrefs.drama3_tr_dir = value.trim();
    saveTtsPrefs();
    folderCheck = app.ttsPrefs.drama3_tr_dir ? await call('tts_folder_check', app.ttsPrefs.drama3_tr_dir) : null;
  }

  $effect(() => {
    if (folderCheck === null && app.ttsPrefs.drama3_tr_dir && app.engines.some((e) => e.folder)) {
      call('tts_folder_check', app.ttsPrefs.drama3_tr_dir).then((result) => { folderCheck = result ?? false; });
    }
  });

  async function chooseModelFolder() {
    const folder = await call('choose_folder', 'Drama 3 TR klasörü (drama-3-tr reposu; models, speaker.safetensors ve .venv içinde)');
    if (typeof folder === 'string' && folder) await setModelFolder(folder);
  }

  // F188: Drama 3 TR'yi yerel klasor yerine OpenRouter'dan calistirma; anahtar isletim sistemi deposunda
  const cloudOn = (engine) => engine.cloud && app.ttsPrefs.drama3_tr_backend === engine.cloud;
  let cloudKey = $state('');
  let cloudCheck = $state(null);     // {ok, key_set, message} | {error}
  let cloudBusy = $state(false);

  function setBackend(value) {
    app.ttsPrefs.drama3_tr_backend = value;
    saveTtsPrefs();
    if (value !== 'local' && cloudCheck === null) testCloud();
  }

  async function saveCloudKey(value) {
    cloudBusy = true;
    const result = await act('tts_cloud_set_key', value);
    cloudBusy = false;
    if (result) { cloudCheck = result; cloudKey = ''; toast(value ? 'API anahtarı kaydedildi.' : 'API anahtarı silindi.', 'ok'); }
  }

  async function testCloud() {
    cloudBusy = true;
    cloudCheck = (await call('tts_cloud_check')) ?? false;
    cloudBusy = false;
  }

  $effect(() => {
    if (cloudCheck === null && !cloudBusy && app.engines.some(cloudOn)) testCloud();
  });

  // F161: motorun kendi ayarlari (motor.json "settings"; Drama 3: parca uzunlugu, temperature, top_p)
  const engineValue = (engine, s) => app.ttsPrefs.engine_settings?.[engine.id]?.[s.key] ?? s.default;

  function setEngineValue(engine, key, value, save = true) {
    const all = { ...(app.ttsPrefs.engine_settings ?? {}) };
    all[engine.id] = { ...(all[engine.id] ?? {}), [key]: value };
    app.ttsPrefs.engine_settings = all;
    if (save) saveTtsPrefs();
  }

  function resetEngine(engine) {
    const all = { ...(app.ttsPrefs.engine_settings ?? {}) };
    delete all[engine.id];
    app.ttsPrefs.engine_settings = all;
    saveTtsPrefs();
  }

  const settingText = (s, value) => `${Number(value).toLocaleString('tr-TR', { maximumFractionDigits: 2 })}${s.unit ? ' ' + s.unit : ''}`;

  const modeBadge = (engine) => engine.busy ? [engine.busy, 'active']
    : engine.mode === 'builtin' && cloudOn(engine) ? ['OpenRouter üzerinden', 'done']
    : engine.mode === 'builtin' && engine.folder ? ['Klasörden çalışır', 'done']
    : engine.mode === 'builtin' ? ['Sunucuya bağlanır', 'done']
    : engine.mode === 'package' ? [`Kurulu · ${engine.installed_version ?? engine.version}`, 'done']
    : engine.mode === 'source' ? ['Python paketiyle', 'done'] : ['Kurulu değil', ''];

  const stateText = $derived({
    idle: 'Henüz yüklenmedi; okumaya başladığınızda yüklenir.',
    loading: app.tts.message,
    ready: `Hazır · ${app.engines.find((e) => e.id === app.tts.engine)?.name ?? app.tts.engine} · ${app.tts.device === 'sunucu' ? 'Sunucu' : app.tts.device === 'bulut' ? 'Bulut (OpenRouter)' : String(app.tts.device ?? '').startsWith('cuda') ? 'GPU' : 'CPU'}`,
    error: app.tts.message,
    missing: app.tts.message,
  }[app.tts.state] ?? '');

  $effect(() => { call('tts_engines').then((list) => { if (Array.isArray(list)) app.engines = list; }); });

  // F141: sohbetlerdeki sesli modun sesi (okuyucudan ayri secilebilir); bos: okuma sesi.
  let chatVoices = $state([]);
  $effect(() => {
    app.engines;
    call('tts_voices').then((list) => { if (Array.isArray(list)) chatVoices = list; });
  });
  const chatGroups = $derived([...new Set(chatVoices.map((v) => v.group))]);
  const CHAT_SPEEDS = [0.9, 1, 1.1, 1.2, 1.35, 1.5];

  function setChat(change) {
    Object.assign(app.ttsPrefs, change);
    saveTtsPrefs();
  }
</script>

<section>
  <FoldHead key="tts-engines" title="Ses motorları" open={shown('tts-engines')}>
    <button class="btn sm primary" onclick={installFile} title="DERLE_SES.cmd ile oluşturduğunuz ses motoru paketini (.zip) kurun"><Icon name="download" size={14} />Dosyadan kur</button>
  </FoldHead>
  {#if shown('tts-engines')}
  {#if !app.engines.some((e) => e.mode)}
    <div class="info"><span>Kurulu ses motoru yok. Kaynak koddan çalışırken <code>requirements-tts.txt</code> paketleri kuruluysa motorlar doğrudan çalışır. Paketleri proje klasöründe <b>DERLE_SES.cmd</b> ile oluşturun
      (<code>dist-engines</code> klasörüne yazılır), sonra <b>Dosyadan kur</b> ile seçin.</span></div>
  {/if}

  {#each app.engines as engine (engine.id)}
    {@const badge = modeBadge(engine)}
    {@const open = shown('engine:' + engine.id)}
    <div class="fr engine" class:open>
      <button class="icon-btn sm chev" class:open aria-expanded={open} title={open ? 'Ayrıntıları gizle' : 'Ayrıntıları göster'}
        onclick={() => toggleOpen('engine:' + engine.id)}><Icon name="forward" size={16} /></button>
      <div class="l">
        {engine.name} <span class="ver">{engine.version}</span>{#if engine.attribution}<span class="attr">{engine.attribution}</span>{/if}
        <small>{engine.description}</small>
        {#if engine.notice}<small class="notice">{engine.notice}</small>{/if}
        <small class="dim">Diller: {engine.languages.map((l) => ({ tr: 'Türkçe', en: 'İngilizce' })[l] ?? l).join(', ')} · {engine.license}</small>
      </div>
      <span class="badge {badge[1]}">{badge[0]}</span>
      {#if engine.removable && !engine.busy}
        <button class="icon-btn" title="Kaldır" onclick={() => remove(engine)}><Icon name="trash" size={16} /></button>
      {/if}
    </div>
    {#if open}
    <!-- F179: motor kapali: alt satirlar gizli; acikken motorun icinde girintili kutuda -->
    <div class="engine-body">
    {#if engine.cloud}
      <div class="fr sub">
        <div class="l">Çalışma yeri<small>Kayıtlı sesleriniz iki yerde de aynen çalışır. OpenRouter'da bulutta orijinal Fish Audio
          Drama 3 çalışır (yerel klasördeki 32 uzmanlı Türkçe konuşmacı değil); ücret okunan karakter başınadır (~2 $ / 1 milyon karakter).
          Okunan metin ve klon kaydı her istekte OpenRouter'a ve Fish Audio'ya gider.</small></div>
        <select class="field w" value={cloudOn(engine) ? engine.cloud : 'local'} aria-label="Çalışma yeri"
          onchange={(e) => setBackend(e.currentTarget.value)}>
          <option value="local">Yerel klasör (GPU)</option>
          <option value={engine.cloud}>OpenRouter (bulut, ücretli)</option>
        </select>
      </div>
    {/if}
    {#if cloudOn(engine)}
      <div class="fr sub">
        <div class="l">OpenRouter API anahtarı{#if cloudCheck?.key_set}<small class="okc">Kayıtlı</small>{/if}<small>openrouter.ai → Keys.
          Anahtara düşük bir harcama sınırı koymanız önerilir. Anahtar ui.json'a yazılmaz, işletim sisteminin şifre deposunda durur.</small></div>
        <input class="field" type="password" bind:value={cloudKey} placeholder={cloudCheck?.key_set ? '••••••••••••' : 'sk-or-…'} autocomplete="off" />
        <button class="btn sm" disabled={!cloudKey.trim() || cloudBusy} onclick={() => saveCloudKey(cloudKey.trim())}>Kaydet</button>
        <button class="btn sm" disabled={cloudBusy} onclick={testCloud}><Icon name="refresh" size={14} />{cloudBusy ? 'Deneniyor…' : 'Anahtarı dene'}</button>
        {#if cloudCheck?.key_set}<button class="btn sm ghost" disabled={cloudBusy} onclick={() => saveCloudKey('')} title="Anahtarı sil">Sil</button>{/if}
      </div>
      {#if cloudCheck}
        <div class={cloudCheck.ok ? 'info' : 'warn'}>
          <Icon name={cloudCheck.ok ? 'check' : 'alert'} size={16} /><span class="selectable">{cloudCheck.error ?? cloudCheck.message}</span>
        </div>
      {/if}
    {:else if engine.folder}
      <div class="fr sub">
        <div class="l">Model klasörü<small>Model Aktar klasörüne kopyalanmaz; seçtiğiniz klasörden (hızlı bir SSD önerilir) çalışır.
          Aktar sunucuyu bu klasördeki .venv Python'uyla kendisi başlatır ve kapanınca durdurur.</small></div>
        <input class="field" value={app.ttsPrefs.drama3_tr_dir ?? ''} placeholder="ör. Z:\Ai Models\drama-3-tr-speaker" spellcheck="false"
          onchange={(e) => setModelFolder(e.currentTarget.value)} />
        <button class="btn sm" onclick={chooseModelFolder}><Icon name="folder" size={14} />Seç…</button>
      </div>
      {#if folderCheck}
        <div class={folderCheck.ok ? 'info' : 'warn'}>
          <Icon name={folderCheck.ok ? 'check' : 'alert'} size={16} /><span class="selectable">{folderCheck.error ?? folderCheck.message}</span>
        </div>
      {/if}
    {:else if engine.server}
      <div class="fr sub">
        <div class="l">Sunucu adresi<small>{engine.name} sunucusunu siz başlatırsınız (Aktar başlatmaz). Windows'ta WSL "mirrored" ağ kipindeyse
          localhost çalışır; değilse WSL'in IP adresini yazın.</small></div>
        <input class="field" value={app.ttsPrefs.drama3_url ?? ''} placeholder={DRAMA3_URL} spellcheck="false"
          onchange={(e) => setServerUrl(e.currentTarget.value)} />
        <button class="btn sm" disabled={checking} onclick={checkServer}><Icon name="refresh" size={14} />{checking ? 'Deneniyor…' : 'Bağlantıyı dene'}</button>
      </div>
      {#if serverCheck}
        <div class={serverCheck.error ? 'warn' : 'info'}>
          <Icon name={serverCheck.error ? 'alert' : 'check'} size={16} /><span class="selectable">{serverCheck.error ?? serverCheck.message}</span>
        </div>
      {/if}
    {/if}
    {#each open ? (engine.settings ?? []).filter((s) => !(s.local_only && cloudOn(engine))) : [] as s (engine.id + s.key)}
      <div class="fr sub">
        <div class="l">{s.label}{#if s.hint}<small>{s.hint}</small>{/if}</div>
        <input class="range" type="range" min={s.min} max={s.max} step={s.step} value={engineValue(engine, s)} aria-label={s.label}
          oninput={(e) => setEngineValue(engine, s.key, Number(e.currentTarget.value), false)}
          onchange={(e) => setEngineValue(engine, s.key, Number(e.currentTarget.value))} />
        <span class="dim-text num wide">{settingText(s, engineValue(engine, s))}</span>
      </div>
    {/each}
    {#if engine.emotion_tags && open}
      <div class="fr sub">
        <div class="l">Duygu etiketleri (deneysel)<small>Kitaplıkta kitaba sağ tıklayıp "Duygu etiketleri oluştur" deyince kitabın
          diyaloglarına duygu, ses ve duraklama yönergeleri bir kez eklenir (anlatıcı ipuçlarından ya da model sunucusuyla
          bağlamdan). Okurken model çalışmaz. Okuyucudaki metin değişmez; etiketli sürüm yalnızca {engine.name}'e
          giden metne eklenir. Okuyucudaki "Duygulu" düğmesiyle de açılıp kapanır.</small></div>
        <select class="field w" value={app.ttsPrefs.emotion_tags === 'off' ? 'off' : 'on'} aria-label="Duygu etiketleri"
          onchange={(e) => { app.ttsPrefs.emotion_tags = e.currentTarget.value; saveTtsPrefs(); }}>
          <option value="on">Etiketli sürüm varsa kullan</option>
          <option value="off">Kapalı</option>
        </select>
      </div>
      {#if app.ttsPrefs.emotion_tags !== 'off'}
        <div class="fr sub">
          <div class="l">Model ile etiketleme biçimi<small>Serbest yönerge: model aşağıdaki listeyle sınırlı kalmaz, konuşmaya
            Türkçe ön ek ([titrek bir sesle, ağlamamak için kendini zorlayarak]), cümle ortasında ses ya da duraklama
            ([derin bir nefes alır]) ve birkaç kelimeyi saran çift etiket (&lt;whisper&gt;…&lt;/whisper&gt;) yazar; aşağıdaki
            etiket listesi modele verilmez. Model cümlenin kelimelerini değiştirirse o cümle etiketsiz kalır.
            {#if !engine.emotion_rich}{engine.name} yalnızca baştaki tek etikete uyduğu için yönergeden en yakın etiket seçilir.{/if}
            Yalnızca katalog: model yalnızca seçtiğiniz etiketlerden birini konuşmanın başına koyar. Değişiklik için kitabı
            yeniden etiketleyin.</small></div>
          <select class="field w" value={app.ttsPrefs.emotion_style === 'catalog' ? 'catalog' : 'free'} aria-label="Etiketleme biçimi"
            onchange={(e) => { app.ttsPrefs.emotion_style = e.currentTarget.value; saveTtsPrefs(); }}>
            <option value="free">Serbest yönerge</option>
            <option value="catalog">Yalnızca katalog</option>
          </select>
        </div>
      {/if}
      {#if catalog && app.ttsPrefs.emotion_tags !== 'off'}
        <div class="fr sub tags-head">
          <div class="l">Kullanılacak etiketler · {allowedTags.length} / {catalog.tags.length}<small>Drama 3'te sabit bir etiket
            listesi yok; bunlar Fish Audio belgelerinde ve örneklerinde geçenler. Durum sizin dinleme setinize göre. Kelime
            listesi ve "Yalnızca katalog" kipi bunları kullanır: [köşeli] etiketler konuşmanın başına eklenir, &lt;çift&gt;
            etiketler konuşmayı sarar; serbest yönerge bu listeyi kullanmaz. Yeni seçtiğiniz etiket için kitabı
            kitaplıktan yeniden etiketleyin; kaldırdığınız etiket hemen uygulanmaz.</small></div>
          <button class="btn sm" onclick={defaultTags} disabled={!app.ttsPrefs.emotion_allowed}><Icon name="refresh" size={14} />Varsayılana dön</button>
          <button class="btn sm" aria-expanded={shown('tags:' + engine.id, false)} onclick={() => toggleOpen('tags:' + engine.id, false)}>
            <Icon name={shown('tags:' + engine.id, false) ? 'up' : 'down'} size={14} />{shown('tags:' + engine.id, false) ? 'Gizle' : 'Etiketleri göster'}</button>
        </div>
        {#if shown('tags:' + engine.id, false)}
          {#each tagGroups as group (group)}
            {@const items = catalog.tags.filter((t) => t.group === group)}
            <div class="tags">
              <div class="group">{group} <span>· {items.filter((t) => allowedTags.includes(t.tag)).length} / {items.length}</span></div>
              {#each items as item (item.tag)}
                <label class="tag" class:on={allowedTags.includes(item.tag)}>
                  <input type="checkbox" checked={allowedTags.includes(item.tag)} onchange={(e) => toggleTag(item.tag, e.currentTarget.checked)} />
                  <span class="tb"><code>{item.kind === 'paired' ? `${item.tag}…</${item.tag.slice(1)}` : item.tag}</code>
                    <b>{item.label}</b><i class="st {item.status}">{STATUS[item.status]}</i>
                    <small>{item.examples}</small></span>
                </label>
              {/each}
            </div>
          {/each}
        {/if}
      {/if}
    {/if}
    {#if open && engine.settings?.length && app.ttsPrefs.engine_settings?.[engine.id]}
      <div class="fr sub">
        <div class="l"><small>Değiştirilen ayarlarla hazırlanan cümleler yeniden üretilir.</small></div>
        <button class="btn sm" onclick={() => resetEngine(engine)}><Icon name="refresh" size={14} />Varsayılana dön</button>
      </div>
    {/if}
    </div>
    {/if}
  {/each}

  {#if app.tts.state === 'loading' || app.tts.state === 'error' || app.tts.state === 'ready'}
    <div class={app.tts.state === 'error' ? 'warn' : 'info'}>
      {#if app.tts.state === 'error'}<Icon name="alert" size={16} />{/if}
      <span class="selectable">{stateText}</span>
    </div>
  {/if}
  {/if}
</section>

<section>
  <FoldHead key="tts-voices" title="Okuma sesi" open={shown('tts-voices')} />
  {#if shown('tts-voices')}
  {#each languages as language}
    {@const list = options(language)}
    <div class="fr">
      <div class="l">{LANGUAGES[language] ?? `Dil: ${language}`}<small>{list.length ? 'Bu dildeki kitapları okuyacak ses' : 'Bu dil için kurulu ses motoru yok'}</small></div>
      {#if list.length}
        <select class="field w" value={selected(language)} onchange={(e) => choose(language, e.currentTarget.value)}>
          {#if !selected(language)}<option value="">Seçilmedi</option>{/if}
          {#each list as option}<option value={option.value}>{option.label}{option.note}</option>{/each}
        </select>
      {/if}
    </div>
    {@const value = selected(language)}
    {#each voiceOf(value)?.options ?? [] as option (value + option.key)}
      <div class="fr sub">
        <div class="l">{option.label}{#if option.hint}<small>{option.hint}</small>{/if}</div>
        {#if option.type === 'file'}
          <span class="path selectable" title={optionValue(value, option)}>{optionValue(value, option) || 'Seçilmedi'}</span>
          <button class="btn sm" onclick={() => pickReference(value, option.key)}>Seç…</button>
        {:else}
          <input class="field w" value={optionValue(value, option)} placeholder={option.default ?? ''}
            onchange={(e) => setOption(value, option.key, e.currentTarget.value.trim())} />
        {/if}
      </div>
    {/each}
  {/each}

  <div class="fr">
    <div class="l">Sohbet sesi<small>Sohbetlerdeki sesli modda cevapları okuyan ses. Okuma sesinden farklı bir motor seçilirse
      sesli moda geçerken o motor yüklenir.</small></div>
    <select class="field w" value={app.ttsPrefs.chat_voice ?? ''} onchange={(e) => setChat({ chat_voice: e.currentTarget.value })}>
      <option value="">Okuma sesiyle aynı</option>
      {#each chatGroups as group}
        <optgroup label={group}>
          {#each chatVoices.filter((v) => v.group === group) as v}<option value={v.value}>{v.label}</option>{/each}
        </optgroup>
      {/each}
    </select>
    <select class="field" title="Sohbet sesinin hızı" value={String(app.ttsPrefs.chat_speed ?? 1)}
      onchange={(e) => setChat({ chat_speed: Number(e.currentTarget.value) })}>
      {#each CHAT_SPEEDS as s}<option value={String(s)}>{s.toLocaleString('tr-TR')}×</option>{/each}
    </select>
  </div>
  {/if}
</section>

<section>
  <FoldHead key="tts-reading" title="Okuma ayarları" open={shown('tts-reading')} />
  {#if shown('tts-reading')}
  <div class="fr">
    <div class="l">Hazırlanan sesler<small>Okuyucudaki "Hazırla" ile önceden üretilen sesler; motor yüklenmeden anında okunur.
      Kitap başına program klasöründeki ses-onbellegi altında tutulur.</small></div>
    <span class="dim-text">{cache ? `${cache.files.toLocaleString('tr-TR')} cümle · ${megabytes(cache.bytes)} MB` : '…'}</span>
    <button class="btn sm" disabled={!cache?.files} onclick={clearCache}><Icon name="trash" size={14} />Temizle</button>
  </div>
  <div class="fr">
    <div class="l">İşlemci<small>EMA Lightning için. Otomatik: NVIDIA ekran kartı varsa onu, yoksa CPU'yu kullanır.</small></div>
    <div class="seg">
      {#each [['auto', 'Otomatik'], ['cuda', 'GPU'], ['cpu', 'CPU']] as [value, label]}
        <button class:on={app.ttsPrefs.device === value} onclick={() => setDevice(value)}>{label}</button>
      {/each}
    </div>
  </div>
  <div class="fr">
    <div class="l">Varsayılan hız</div>
    <div class="seg">
      {#each [0.8, 1, 1.25, 1.5, 2] as value}
        <button class:on={app.ttsPrefs.speed === value} onclick={() => { app.ttsPrefs.speed = value; saveTtsPrefs(); }}>{value.toLocaleString('tr-TR')}×</button>
      {/each}
    </div>
  </div>
  <div class="fr">
    <div class="l">Duraklamalar<small>Cümle ve paragraf sonlarında bırakılan sessizlik. Okurken değiştirilebilir; hazırlanan sesleri etkilemez.</small></div>
    <div class="seg">
      {#each Object.entries(PAUSE_PRESETS) as [value, preset]}
        <button class:on={pausePrefs.preset === value} onclick={() => setPauses({ preset: value })}>{preset.label}</button>
      {/each}
      <button class:on={!PAUSE_PRESETS[pausePrefs.preset]} onclick={() => setPauses({ preset: 'custom' })}>Özel</button>
    </div>
    <button class="btn sm" aria-expanded={pauseDetails} onclick={() => (pauseDetails = !pauseDetails)}>{pauseDetails ? 'Gizle' : 'Ayrıntılar'}</button>
  </div>
  {#if pauseDetails}
    {#each PAUSE_KEYS as [key, label]}
      <div class="fr sub">
        <div class="l">{label}</div>
        <input class="range" type="range" min="0" max="2" step="0.05" value={pauses[key]} aria-label={label}
          oninput={(e) => setPause(key, Number(e.currentTarget.value), false)}
          onchange={(e) => setPause(key, Number(e.currentTarget.value), true)} />
        <span class="dim-text num">{seconds(pauses[key])}</span>
      </div>
    {/each}
    <div class="fr sub">
      <div class="l">Hızla birlikte kısalt<small>Hızlı okurken duraklamalar da aynı oranda kısalır.</small></div>
      <Toggle bind:checked={() => pauses.scale, (scale) => setPauses({ scale })} />
    </div>
  {/if}
  <div class="fr">
    <div class="l">Tırnak içini bölme<small>Tırnak içindeki konuşma (ör. "Bekle! Hemen geliyorum!") tek parça okunur; vurgulama da
      tek parça olur. Okuyucuya dönünce geçerli olur; değişen paragrafların hazırlanan sesleri yeniden üretilir.</small></div>
    <Toggle bind:checked={() => split.quotes, (quotes) => setSplit({ quotes })} />
  </div>
  {#if split.quotes}
    <div class="fr sub">
      <div class="l">En uzun alıntı<small>Daha uzun alıntılar her zamanki gibi cümle cümle bölünür; kapanmayan bir tırnak en fazla paragraf sonuna kadar etkiler.</small></div>
      <input class="range" type="range" min="2" max="8" step="1" value={split.maxQuoted} aria-label="En uzun alıntı"
        oninput={(e) => setSplit({ maxQuoted: Number(e.currentTarget.value) }, false)}
        onchange={(e) => setSplit({ maxQuoted: Number(e.currentTarget.value) })} />
      <span class="dim-text num">{split.maxQuoted} cümle</span>
    </div>
  {/if}
  {/if}
</section>

<style>
  section > :global(.fold) { margin-bottom: 6px; }
  .chev { color: var(--secondary); transition: transform .15s; }
  .chev.open { transform: rotate(90deg); }
  .engine { gap: 12px; }
  .engine.open { border-bottom: 0; padding-bottom: 8px; }
  /* acik motorun ayarlari: basligin altinda girintili, sol cizgili kutu (hangi motora ait oldugu belli olsun) */
  .engine-body { margin: 0 0 14px 40px; padding: 2px 16px; border-left: 2px solid color-mix(in srgb, var(--accent) 55%, var(--outline));
    background: color-mix(in srgb, var(--surface) 60%, transparent); border-radius: 0 12px 12px 0; }
  :global(.engine-body) + .engine { border-top: 1px solid var(--outline); }
  .engine-body .sub { padding-left: 0; }
  .engine-body .tags { padding-left: 0; }
  .engine-body > .fr:last-child, .engine-body > .tags:last-child { border-bottom: 0; }
  .fr { display: flex; align-items: center; gap: 20px; padding: 12px 0; border-bottom: 1px solid var(--outline); }
  .fr:last-child { border-bottom: 0; }
  .l { flex: 1; min-width: 0; font-weight: 500; }
  .l small { display: block; color: var(--dim); font-size: 12px; font-weight: 400; margin-top: 2px; }
  .l small.dim { color: var(--dim); }
  .info code { font-family: var(--mono); }
  small.okc { color: var(--ok); }
  .dim-text { font-size: 12px; color: var(--secondary); white-space: nowrap; }
  .sub { padding-left: 16px; border-bottom-style: dashed; }
  .path { max-width: 260px; font-size: 12px; color: var(--secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; direction: rtl; }
  .ver { color: var(--dim); font-size: 12px; margin-left: 4px; }
  .attr { margin-left: 8px; font-size: 11px; font-weight: 600; color: var(--secondary); border: 1px solid var(--outline); border-radius: 999px; padding: 1px 8px; }
  .l small.notice { color: var(--warning); }
  .field.w { width: 340px; }
  .info, .warn { display: flex; gap: 8px; align-items: center; font-size: 12px; padding: 8px 12px; border-radius: 8px; margin: 4px 0 8px; }
  .info { color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); }
  .warn { color: var(--warning); background: color-mix(in srgb, var(--warning) 10%, transparent); }
  .seg { display: flex; background: var(--surface); border-radius: 999px; padding: 3px; }
  .seg button { display: inline-flex; gap: 6px; align-items: center; padding: 5px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; color: var(--secondary); }
  .range { width: 220px; accent-color: var(--accent); }
  .num { width: 56px; text-align: right; font-variant-numeric: tabular-nums; }
  .num.wide { width: 96px; }
  .seg button.on { background: var(--surface-active); color: var(--text); }
  .tags-head { border-bottom: 0; }
  .tags { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 6px; padding: 0 0 12px 16px; border-bottom: 1px dashed var(--outline); }
  .group { grid-column: 1 / -1; font-size: 12px; font-weight: 700; color: var(--secondary); text-transform: uppercase; letter-spacing: .04em; padding-top: 8px; }
  .group span { font-weight: 500; color: var(--dim); text-transform: none; letter-spacing: 0; }
  .tag { display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--outline); cursor: pointer; }
  .tag.on { border-color: color-mix(in srgb, var(--accent) 60%, var(--outline)); background: color-mix(in srgb, var(--accent) 7%, transparent); }
  .tag input { margin-top: 3px; accent-color: var(--accent); }
  .tb { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; min-width: 0; font-size: 13px; }
  .tb code { font-family: var(--mono); font-size: 12px; color: var(--accent); }
  .tb small { flex-basis: 100%; color: var(--dim); font-size: 11px; }
  .st { font-style: normal; font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 999px; color: var(--secondary); background: var(--surface); }
  .st.works { color: var(--success, #22c55e); background: color-mix(in srgb, var(--success, #22c55e) 12%, transparent); }
  .st.fails { color: var(--danger); background: color-mix(in srgb, var(--danger) 12%, transparent); }
</style>
