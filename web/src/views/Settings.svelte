<script>
  import Icon from '../lib/Icon.svelte';
  import Toggle from '../components/Toggle.svelte';
  import { app, act, setTheme, reloadThemes, toast } from '../lib/state.svelte.js';
  import { resolveTheme } from '../lib/theme.js';
  import { call } from '../lib/api.js';

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

  const locked = (key) => info?.locked.includes(key);
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
  }

  async function browse(key, folder) {
    const path = folder ? await call('choose_folder', 'Klasör seç') : await call('choose_file', 'Program seç', []);
    if (path) cfg[key] = path;
  }

  // Tema onizlemesi: paletin birkac rengiyle kucuk bir pencere cizimi.
  const choices = $derived([{ id: 'system', name: 'Sistem', system: true }, ...app.themes]);
  const preview = (theme) => (theme.system ? resolveTheme('system', app.themes) : theme)?.palette ?? {};

  const advanced = [
    ['analysis_chunk_chars', 'Analiz parça karakteri', 'Ön analizde modele tek seferde giden en fazla altyazı metni.', 1, 200000, 1],
    ['max_tokens', 'Çıktı token payı', 'Bir model yanıtı için ayrılan en fazla token.', 1, 262144, 1],
    ['timeout_seconds', 'Zaman aşımı (sn)', 'Tek bir LM Studio isteği için beklenecek en uzun süre.', 1, 86400, 1],
    ['temperature', 'Temperature', 'Düşük değer daha tutarlı çeviri verir.', 0, 2, 0.05],
    ['qa_context_chars', 'Soru-cevap bağlam karakteri', 'Video sohbetinde modele tek istekte giden en fazla transkript; aşılırsa video haritası kullanılır.', 1000, 1000000, 1000],
  ];
</script>

<section class="page">
  <div class="page-head">
    <h1>Ayarlar</h1>
    {#if dirty}<span class="unsaved">Kaydedilmemiş değişiklik var</span>{/if}
    <button class="btn" onclick={reset} disabled={!cfg}><Icon name="rotate" size={16} />Varsayılanlar</button>
    <button class="btn primary" onclick={save} disabled={!cfg || saving || !dirty}><Icon name="check" size={16} />Kaydet</button>
  </div>

  {#if cfg}
    <div class="page-body">
      <div class="col">
        <section>
          <h2>LM Studio ve model</h2>
          {#if info.locked.length}<div class="warn"><Icon name="alert" size={16} />Çeviri sürerken model ve bağlantı ayarları değiştirilemez.</div>{/if}
          <div class="fr">
            <div class="l">Sunucu adresi<small>Yalnızca yerel HTTP adresi (localhost / 127.0.0.1).</small></div>
            <input class="field w" bind:value={cfg.base_url} disabled={locked('base_url')} placeholder="http://127.0.0.1:1234/v1" />
          </div>
          <div class="fr">
            <div class="l">Analiz modeli<small>Çeviri, dosya özetleri ve analiz için kullanılan model.</small></div>
            <div class="pick">
              <select class="field w" bind:value={cfg.model} disabled={locked('model')}>
                {#each withCurrent(chatNames, cfg.model) as m}<option value={m}>{m}</option>{/each}
              </select>
              <button class="icon-btn" title="Modelleri LM Studio'dan yeniden getir" disabled={app.models.state === 'probing'}
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

        <section>
          <h2>Çeviri davranışı</h2>
          <div class="fr">
            <div class="l">Katı sözlük<small>Açıkken uygulanamayan terimde çeviri durur; kapalıyken uyarı günlüğe yazılır ve çeviri sürer.</small></div>
            <Toggle bind:checked={cfg.glossary_strict} disabled={locked('glossary_strict')} />
          </div>
          <div class="fr">
            <div class="l">Otomatik tekrar sayısı<small>İlk istek hariç ek deneme: 2 seçilirse en fazla 3 istek yapılır.</small></div>
            <input class="field n" type="number" min="1" max="100" bind:value={cfg.auto_retry_count} disabled={locked('auto_retry_count')} />
          </div>
          <div class="fr">
            <div class="l">Parti boyutu<small>Tek istekte modele gönderilen altyazı girdisi sayısı.</small></div>
            <input class="field n" type="number" min="1" max="200" bind:value={cfg.batch_cues} disabled={locked('batch_cues')} />
          </div>
        </section>

        <section>
          <h2>Konuşmadan metin (Whisper)</h2>
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
            <div class="l">GPU kütüphane klasörü<small class:okc={cuda.ok} class:errc={cuda.ok === false}>{cuda.message || 'Boş: pip ile kurulan ya da pakete gömülü cuBLAS 12 / cuDNN 9.'}</small></div>
            <div class="pick">
              <input class="field w2" bind:value={cfg.whisper_cuda_dir} placeholder="Boş: otomatik" />
              <button class="btn sm" onclick={() => browse('whisper_cuda_dir', true)}>Gözat…</button>
            </div>
          </div>
        </section>

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

        <section>
          <h2>Gelişmiş</h2>
          <div class="warn"><Icon name="alert" size={16} />Bu ayarlar deneyseldir; ne yaptığınızdan emin değilseniz değiştirmeyin.</div>
          {#each advanced as [key, title, hint, min, max, step]}
            <div class="fr">
              <div class="l">{title}<small>{hint}</small></div>
              <input class="field n" type="number" {min} {max} {step} bind:value={cfg[key]} disabled={locked(key)} />
            </div>
          {/each}
        </section>

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
    </div>
  {/if}
</section>

<style>
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
