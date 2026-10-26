<script>
  // F197 kitap gorselleri (kitapligin sag tik menusu): 1) kitap notu + hazir tarz + siklik ile dil modeli sahne
  // planini cikarir, 2) stil, karakterler ve sahneler gozden gecirilir, 3) ComfyUI gorselleri uretir. Sahne basina
  // kucuk duzeltme ("daha karanlik", "kisiyi cikar") istemi en az degisiklikle yeniden yazar, sahneyi bastan kurmaz.
  // Isler arka planda surer (sag ustteki is listesi); pencere kapansa da devam eder.
  // F201 Karakter kimligi (kitap basina acilir/kapanir, kapaliyken akis aynen eskisi): karakter portreleri uretilir
  // ya da kullanici kendi gorselini koyar; karakterli sahneler portre referansiyla kimlik is akisinda uretilir.
  import Modal from './Modal.svelte';
  import Toggle from './Toggle.svelte';
  import Icon from '../lib/Icon.svelte';
  import { app, act, go, toast, refreshArtBooks } from '../lib/state.svelte.js';
  import { call, on } from '../lib/api.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import { bookSections } from '../lib/emotions.js';

  let { book, title = '', onclose } = $props();

  const DENSITY = { low: 'Az', medium: 'Orta', high: 'Çok' };
  const DENSITY_HINT = { low: 'yaklaşık 4 sayfada bir', medium: 'sahne değişiminde, yaklaşık 1,5 sayfada bir', high: 'yarım–bir sayfada bir' };

  let options = $state(null);
  let plan = $state(null);
  let loaded = $state(false);
  let note = $state('');
  let preset = $state('');
  let density = $state('medium');
  let replanning = $state(false);   // tamamlanmis plan varken kurulum ekrani acik
  let style = $state('');
  let characters = $state('');
  let editing = $state({});         // sahne -> elle duzenlenen istem
  let fixes = $state({});           // sahne -> duzeltme notu
  let refining = $state('');        // duzeltilen sahne
  let identity = $state(false);     // yeni planda karakter kimligi

  const job = $derived(app.artJob?.book === book ? app.artJob : null);
  const otherJob = $derived(app.artJob && app.artJob.book !== book ? app.artJob : null);
  const planning = $derived(job?.stage === 'plan');
  const generating = $derived(job?.stage === 'generate');
  const scenes = $derived(plan?.scenes ?? []);
  const shown = $derived(scenes.filter((s) => !s.skip));
  const missing = $derived(shown.filter((s) => !s.url).length);
  const setup = $derived(!planning && (!plan || !plan.complete || replanning));
  const faces = $derived(plan?.identity ? plan.characters ?? [] : []);
  const identityReady = $derived(Boolean(options?.identity_workflow?.ok));

  async function load() {
    const [opts, result] = await Promise.all([call('art_options'), call('art_plan_get', book)]);
    options = opts?.error ? null : opts;
    applyPlan(result?.plan ?? null);
    loaded = true;
  }

  function applyPlan(value) {
    plan = value;
    if (!value) return;
    style = value.style ?? '';
    characters = (value.characters ?? []).map((c) => `${c.name}: ${c.look}`).join('\n');
    note = value.note ?? note;           // baştan planlarken önceki not ve seçimler hazır gelsin
    preset = value.preset ?? preset;
    density = value.density ?? density;
    identity = Boolean(value.identity);
  }

  load();
  const stop = on('art', (data) => {
    if (data.book !== book) return;
    if (data.scene && plan) {
      const index = plan.scenes.findIndex((s) => s.id === data.scene.id);
      if (index >= 0) plan.scenes[index] = data.scene;
    }
    if (data.character && plan) {
      const index = plan.characters.findIndex((c) => c.name === data.character.name);
      if (index >= 0) plan.characters[index] = data.character;
    }
    if (data.finished) call('art_plan_get', book).then((r) => { if (r?.plan !== undefined) applyPlan(r.plan); });
  });
  $effect(() => stop);

  // Hazir tarz notun basina yazilir; baska tarza gecince yalnizca onceki tarzin metni degisir, kullanicinin eki kalir.
  function pickPreset(entry) {
    let rest = note;
    for (const p of options.presets) rest = rest.replace(p.note, '');
    rest = rest.trim();
    if (preset === entry.id) { preset = ''; note = rest; return; }
    preset = entry.id;
    note = entry.note + (rest ? ' ' + rest : '');
  }

  async function startPlan(resume = false) {
    if (otherJob) { toast('Başka bir kitabın görselleri için iş sürüyor.'); return; }
    if (app.emotionJob) { toast('Duygu etiketleri oluşturulurken görsel planı çıkarılamaz.'); return; }
    if (!resume && plan?.complete) {
      const yes = await confirm({ title: 'Baştan planla', message: 'Mevcut plan ve üretilmiş görseller silinir. Devam edilsin mi?',
        ok: 'Baştan planla', cancel: 'Vazgeç', danger: true });
      if (!yes) return;
    }
    app.artJob = { book, title, stage: 'plan', done: 0, total: 0, reading: true };
    let sections;
    try {
      sections = await bookSections(book, app.ttsPrefs.split ?? {});
    } catch (error) {
      app.artJob = null;
      toast(String(error?.message ?? error), 'error');
      return;
    }
    const result = await act('art_plan_create', book, sections, note, preset, density, title, resume, identity);
    if (!result?.started) { app.artJob = null; return; }
    if (app.artJob?.reading) app.artJob = { book, title, stage: 'plan', done: 0, total: result.total };
    replanning = false;
    plan = null;
  }

  async function generate(ids = null, all = false, portraits = null) {
    if (otherJob) { toast('Başka bir kitabın görselleri için iş sürüyor.'); return; }
    const result = await act('art_generate', book, ids, title, all, portraits);
    if (result?.started) app.artJob = { book, title, stage: 'generate', done: 0, total: result.total, current: '' };
  }

  async function regenerateAll() {
    const yes = await confirm({ title: 'Hepsini yeniden üret', message: `${shown.length} görselin hepsi yeni stille yeniden üretilir.`,
      ok: 'Yeniden üret', cancel: 'Vazgeç' });
    if (yes) generate(null, true);
  }

  async function saveStyle() {
    if (!plan || style.trim() === plan.style) return;
    const result = await act('art_plan_save', book, { style });
    if (result) { applyPlan(result.plan); toast('Stil kaydedildi. Görsellere yansıması için "Hepsini yeniden üret" deyin.'); }
  }

  async function saveCharacters() {
    const list = characters.split('\n').map((line) => line.split(':')).filter((p) => p.length > 1 && p[0].trim())
      .map(([name, ...look]) => ({ name: name.trim(), look: look.join(':').trim() }));
    const result = await act('art_plan_save', book, { characters: list });
    if (result) applyPlan(result.plan);
  }

  async function updateScene(scene, values) {
    const result = await act('art_scene_update', book, scene.id, values);
    if (result) applyPlan(result.plan);
    return result;
  }

  async function retry(scene) {
    if (await updateScene(scene, { reseed: true })) generate([scene.id]);
  }

  async function savePrompt(scene) {
    if (await updateScene(scene, { prompt: editing[scene.id] })) {
      delete editing[scene.id];
      generate([scene.id]);
    }
  }

  async function refine(scene) {
    refining = scene.id;
    const result = await act('art_scene_refine', book, scene.id, fixes[scene.id] ?? '');
    refining = '';
    if (!result) return;
    applyPlan(result.plan);
    delete fixes[scene.id];
    generate([scene.id]);
  }

  async function setIdentity(value) {
    const result = await act('art_plan_save', book, { identity: value });
    if (result) applyPlan(result.plan);
  }

  async function ownPortrait(character) {
    const path = await call('choose_file', `${character.name} için portre`, ['Görsel (*.png;*.jpg;*.jpeg;*.webp)']);
    if (!path) return;
    const result = await act('art_portrait_set', book, character.name, path);
    if (result) applyPlan(result.plan);
  }

  async function clearPortrait(character) {
    const result = await act('art_portrait_clear', book, character.name);
    if (result) applyPlan(result.plan);
  }

  // Sahnedeki karakterler: dokunulan karakter eklenir/cikarilir (sahneye elle kadro yazilir).
  function toggleCast(scene, name) {
    const people = scene.people ?? [];
    updateScene(scene, { cast: people.includes(name) ? people.filter((n) => n !== name) : [...people, name] });
  }

  async function remove() {
    const yes = await confirm({ title: 'Görselleri sil', message: `"${title}" kitabının görsel planı ve tüm görselleri silinsin mi?`,
      ok: 'Sil', cancel: 'Vazgeç', danger: true });
    if (!yes) return;
    if (await act('art_clear', book)) { await refreshArtBooks(); plan = null; replanning = false; toast('Kitap görselleri silindi.'); }
  }

  function openSettings() {
    onclose();
    app.settingsTab = 'art';
    go('settings');
  }

  const pct = (done, total) => (total ? Math.min(100, Math.round((done * 100) / total)) : 0);
</script>

<Modal title={`Kitap görselleri · ${title}`} width={1040} {onclose}>
  {#if !loaded}
    <div class="empty">Yükleniyor…</div>
  {:else}
    {#if options && !options.workflow.ok}
      <div class="warn"><Icon name="alert" size={16} /><span>{options.workflow.message}</span>
        <button class="btn sm" onclick={openSettings}><Icon name="settings" size={14} />Ayarlar</button></div>
    {/if}

    {#if planning}
      <div class="stage">
        <b>Dil modeli kitabı okuyor ve sahneleri seçiyor…</b>
        <span class="dim">{job.reading || !job.total ? 'bölümler okunuyor' : `${job.done} / ${job.total} cümle`}</span>
        <div class="track"><i style:width="{pct(job.done, job.total)}%"></i></div>
        <p class="dim">Önce bütün kitap için tek bir stil kılavuzu ve karakter tarifleri yazılır, sonra kitap parça parça okunur.
          Bu sırada ses motoru durur; bitince dil modeli bellekten boşaltılır. Pencereyi kapatabilirsiniz, iş sürer.</p>
        <div><button class="btn" onclick={() => act('art_cancel')}><Icon name="stop" size={15} />Durdur</button></div>
      </div>
    {:else if setup}
      <div class="setup">
        <p class="dim">Dil modeli kitabı okur, sahne değişimlerini seçer ve her sahne için bir görsel istemi yazar. Bütün görseller
          aynı stil kılavuzuyla üretilir. Plan bitince stili ve sahneleri gözden geçirip üretimi siz başlatırsınız.</p>
        <label class="l" for="art-note">Kitap notu <small>Dil modeline verilen yönerge: tarz, ton, neyin gösterilip gösterilmeyeceği.</small></label>
        <textarea id="art-note" class="field" rows="3" bind:value={note}
          placeholder="Örn. daha soyut ol, insan yüzü gösterme, suluboya tarzında, dönemin mimarisini öne çıkar"></textarea>
        <div class="row">
          <span class="dim">Hazır tarz</span>
          {#each options?.presets ?? [] as entry (entry.id)}
            <button class="chip" class:on={preset === entry.id} title={entry.note} onclick={() => pickPreset(entry)}>{entry.label}</button>
          {/each}
        </div>
        <div class="row">
          <span class="dim">Sıklık</span>
          <div class="seg">
            {#each Object.entries(DENSITY) as [key, label] (key)}
              <button class:on={density === key} onclick={() => (density = key)}>{label}</button>
            {/each}
          </div>
          <span class="dim">{DENSITY_HINT[density]}</span>
        </div>
        <div class="row">
          <Toggle bind:checked={identity} label="Karakter kimliği" />
          <span class="dim">Karakterler her görselde aynı yüzle çıkar: her karaktere bir portre üretilir, karakterli sahneler bu portreyle çizilir. Ayarlar'da kimlik iş akışı gerekir.</span>
        </div>
        <div class="row end">
          {#if replanning}<button class="btn ghost" onclick={() => (replanning = false)}>Vazgeç</button>{/if}
          {#if plan && !plan.complete}
            <button class="btn" disabled={Boolean(app.artJob)} onclick={() => startPlan(true)}><Icon name="play" size={15} />Kaldığı yerden sürdür</button>
          {/if}
          <button class="btn primary" disabled={Boolean(app.artJob)} onclick={() => startPlan(false)}>
            <Icon name="sparkles" size={15} />{plan ? 'Baştan planla' : 'Planla'}</button>
        </div>
      </div>
    {:else}
      <div class="bar">
        <span><b>{shown.length}</b> sahne · <b>{shown.length - missing}</b> görsel{#if scenes.length > shown.length} · {scenes.length - shown.length} atlandı{/if}</span>
        <span class="grow"></span>
        {#if generating}
          <span class="dim ellipsis">{job.current ? `Üretiliyor: ${job.current}` : 'Üretiliyor'} · {job.done} / {job.total}</span>
          <button class="btn" onclick={() => act('art_cancel')}><Icon name="stop" size={15} />Durdur</button>
        {:else}
          <button class="btn ghost" disabled={Boolean(app.artJob)} onclick={() => (replanning = true)}>Baştan planla</button>
          <button class="btn ghost" onclick={remove}><Icon name="trash" size={15} />Sil</button>
          <button class="btn" disabled={Boolean(app.artJob) || !shown.length} onclick={regenerateAll}><Icon name="refresh" size={15} />Hepsini yeniden üret</button>
          <button class="btn primary" disabled={Boolean(app.artJob) || !missing || !options?.workflow.ok} onclick={() => generate()}>
            <Icon name="image" size={15} />{!missing ? 'Hepsi üretildi' : missing === shown.length ? 'Görselleri üret' : `Eksikleri üret (${missing})`}</button>
        {/if}
      </div>
      {#if generating}<div class="track"><i style:width="{pct(job.done, job.total)}%"></i></div>{/if}

      <details class="look" open={!scenes.some((s) => s.url)}>
        <summary>Stil ve karakterler</summary>
        <label class="l" for="art-style">Stil kılavuzu <small>Her görselin başına aynen eklenir. Değiştirmek planı yeniden yaptırmaz; kaydedip "Hepsini yeniden üret" deyin.</small></label>
        <textarea id="art-style" class="field" rows="4" bind:value={style} onchange={saveStyle}></textarea>
        <label class="l" for="art-chars">Karakterler <small>Satır başına "Ad: görünüş". Sahne istemlerine dil modeli kopyalar; yeni sahnelere yansır, var olan istemler değişmez.</small></label>
        <textarea id="art-chars" class="field" rows="3" bind:value={characters} onchange={saveCharacters}></textarea>
        {#if plan.note}<div class="dim">Kitap notu: {plan.note}</div>{/if}
      </details>

      <details class="look" open={plan.identity && faces.some((c) => !c.portrait_url)}>
        <summary>Karakter kimliği {plan.identity ? '· açık' : '· kapalı'}</summary>
        <div class="row">
          <Toggle checked={Boolean(plan.identity)} disabled={Boolean(app.artJob)} label="Karakterler her görselde aynı yüzle" onchange={setIdentity} />
        </div>
        <p class="dim">Açıkken her karakterin düz fonlu bir portresi üretilir (ya da kendi görselinizi seçersiniz); karakterli sahneler bu portre referans verilerek
          kimlik iş akışıyla çizilir. Kapalıyken görseller yalnızca metin tarifinden üretilir. Var olan görseller kendiliğinden değişmez.</p>
        {#if plan.identity && !identityReady}
          <div class="warn"><Icon name="alert" size={16} /><span>{options?.identity_workflow?.message ?? 'Kimlik iş akışı seçilmedi.'}</span>
            <button class="btn sm" onclick={openSettings}><Icon name="settings" size={14} />Ayarlar</button></div>
        {/if}
        {#if plan.identity}
          {#if !faces.length}<p class="dim">Planda tekrar eden karakter yok; yukarıdaki "Karakterler" kutusuna ekleyebilirsiniz.</p>{/if}
          <div class="faces">
            {#each faces as character (character.name)}
              <div class="face card">
                <div class="portrait">
                  {#if character.portrait_url}<img src={character.portrait_url} alt={character.name} />
                  {:else}<span class="dim">{generating && job.current === `Portre: ${character.name}` ? 'Üretiliyor…' : 'Portre yok'}</span>{/if}
                </div>
                <b class="ellipsis" title={character.look}>{character.name}</b>
                <div class="acts">
                  <button class="btn sm ghost" disabled={Boolean(app.artJob) || !options?.workflow.ok} title="Yeni seed ile portre"
                    onclick={() => generate(null, false, [character.name])}><Icon name="refresh" size={13} />{character.portrait_url ? '' : 'Üret'}</button>
                  <button class="btn sm ghost" disabled={Boolean(app.artJob)} title="Kendi görselinizi portre yapın" onclick={() => ownPortrait(character)}><Icon name="folderOpen" size={13} /></button>
                  {#if character.portrait_url}<button class="btn sm ghost" disabled={Boolean(app.artJob)} title="Portreyi sil" onclick={() => clearPortrait(character)}><Icon name="trash" size={13} /></button>{/if}
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </details>

      <div class="grid">
        {#each scenes as scene (scene.id)}
          <div class="scene card" class:skip={scene.skip}>
            <div class="img">
              {#if scene.url}<img src={scene.url} alt={scene.title} loading="lazy" />
              {:else}<span class="dim">{scene.skip ? 'Atlandı' : generating && job.current === scene.title ? 'Üretiliyor…' : 'Henüz üretilmedi'}</span>{/if}
            </div>
            <div class="meta">
              <b class="ellipsis" title={scene.title}>{scene.title}</b>
              <span class="dim">Bölüm {scene.section + 1} · cümle {scene.start + 1}</span>
            </div>
            {#if plan.identity && faces.length}
              <div class="cast" title="Görselde kimliği korunacak karakterler (en fazla iki referans kullanılır)">
                {#each faces as character (character.name)}
                  <button class="chip" class:on={scene.people?.includes(character.name)} disabled={Boolean(app.artJob)}
                    onclick={() => toggleCast(scene, character.name)}>{character.name}</button>
                {/each}
              </div>
            {/if}
            {#if editing[scene.id] !== undefined}
              <textarea class="field" rows="5" bind:value={editing[scene.id]}></textarea>
              <div class="acts">
                <button class="btn sm ghost" onclick={() => delete editing[scene.id]}>Vazgeç</button>
                <button class="btn sm primary" disabled={Boolean(app.artJob)} onclick={() => savePrompt(scene)}>Kaydet ve üret</button>
              </div>
            {:else}
              <p class="prompt dim" title={scene.prompt}>{scene.prompt}</p>
              {#if !scene.skip}
                <div class="fix">
                  <input class="field" placeholder="Ne değişsin? (daha karanlık, kişiyi çıkar…)" bind:value={fixes[scene.id]}
                    onkeydown={(e) => { if (e.key === 'Enter' && fixes[scene.id]?.trim()) refine(scene); }} />
                  <button class="btn sm" disabled={Boolean(app.artJob) || refining !== '' || !fixes[scene.id]?.trim()} onclick={() => refine(scene)}>
                    {refining === scene.id ? 'Düzeltiliyor…' : 'Düzelt'}</button>
                </div>
              {/if}
              <div class="acts">
                {#if !scene.skip}
                  <button class="btn sm ghost" disabled={Boolean(app.artJob)} title="Aynı istem, yeni seed" onclick={() => retry(scene)}><Icon name="refresh" size={13} />Yeniden dene</button>
                  <button class="btn sm ghost" onclick={() => (editing[scene.id] = scene.prompt)}><Icon name="pencil" size={13} />İstemi düzenle</button>
                {/if}
                <button class="btn sm ghost" onclick={() => updateScene(scene, { skip: !scene.skip })}>{scene.skip ? 'Geri al' : 'Görsel olmasın'}</button>
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</Modal>

<style>
  .warn { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 10px; font-size: 13px;
    background: color-mix(in srgb, var(--warning) 14%, transparent); color: var(--text); }
  .warn span { flex: 1; }
  .stage, .setup { display: flex; flex-direction: column; gap: 10px; }
  .stage p, .setup p { margin: 0; font-size: 13px; line-height: 1.5; }
  .stage .track { flex: none; }
  .l { font-size: 13px; font-weight: 600; display: flex; flex-direction: column; gap: 2px; }
  .l small { font-weight: 400; color: var(--dim); font-size: 12px; }
  .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; }
  .row.end { justify-content: flex-end; margin-top: 6px; }
  .seg { display: flex; align-items: center; background: var(--surface); border-radius: 999px; padding: 3px; }
  .seg button { padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; color: var(--secondary); }
  .seg button.on { background: var(--surface-active); color: var(--text); }
  .bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; }
  .bar .grow { flex: 1; }
  .bar > .track { flex: none; }
  .look { border: 1px solid var(--outline); border-radius: 10px; padding: 8px 12px; display: flex; flex-direction: column; gap: 8px; }
  .look[open] { padding-bottom: 12px; }
  .look summary { cursor: pointer; font-weight: 600; font-size: 13px; }
  .look .l { margin-top: 8px; }
  .look .dim { font-size: 12px; margin-top: 6px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
  .scene { display: flex; flex-direction: column; gap: 8px; padding: 10px; min-width: 0; }
  .scene.skip { opacity: .55; }
  .img { aspect-ratio: 16 / 9; border-radius: 8px; overflow: hidden; background: var(--surface); display: grid; place-items: center; font-size: 12px; }
  .img img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .meta { display: flex; flex-direction: column; gap: 1px; font-size: 13px; min-width: 0; }
  .meta .dim { font-size: 11.5px; }
  .prompt { margin: 0; font-size: 12px; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .look p { margin: 0; font-size: 12px; line-height: 1.5; }
  .faces { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
  .face { display: flex; flex-direction: column; gap: 6px; padding: 8px; min-width: 0; font-size: 13px; }
  .portrait { aspect-ratio: 1; border-radius: 8px; overflow: hidden; background: var(--surface); display: grid; place-items: center; font-size: 12px; }
  .portrait img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .face .acts { flex-wrap: nowrap; }
  .cast { display: flex; gap: 4px; flex-wrap: wrap; }
  .cast .chip { font-size: 11.5px; padding: 2px 8px; }
  .fix { display: flex; gap: 6px; }
  .fix .field { flex: 1; min-width: 0; height: 30px; font-size: 12px; }
  .acts { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
  textarea.field { font-size: 13px; line-height: 1.45; width: 100%; box-sizing: border-box; }
</style>
