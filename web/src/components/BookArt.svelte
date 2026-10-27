<script>
  // F197 kitap gorselleri (kitapligin sag tik menusu): 1) kitap notu + hazir tarz + siklik ile dil modeli sahne
  // planini cikarir, 2) stil, karakterler ve sahneler gozden gecirilir, 3) ComfyUI gorselleri uretir. Sahne basina
  // kucuk duzeltme ("daha karanlik", "kisiyi cikar") istemi en az degisiklikle yeniden yazar, sahneyi bastan kurmaz.
  // Isler arka planda surer (sag ustteki is listesi); pencere kapansa da devam eder.
  // F201 Karakter kimligi (kitap basina acilir/kapanir, kapaliyken akis aynen eskisi): karakter portreleri uretilir
  // ya da kullanici kendi gorselini koyar; karakterli sahneler portre referansiyla kimlik is akisinda uretilir.
  // F209: daha seyrek siklik (onemli anlar), bolum acilis gorseli, mekan kimligi, gorunus degisimi, RTX buyutme ve
  // "Tarzi degistir" (istemler kalir, stil kilavuzu + LoRA degisir, hepsi yeniden uretilir; Bastan planla'dan ayri).
  import Modal from './Modal.svelte';
  import Toggle from './Toggle.svelte';
  import Icon from '../lib/Icon.svelte';
  import { app, act, go, toast, refreshArtBooks } from '../lib/state.svelte.js';
  import { call, on } from '../lib/api.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import { bookSections } from '../lib/emotions.js';

  let { book, title = '', onclose } = $props();

  // F209: seyrekleştikçe dil modeli sahne değişimlerini değil önemli anları seçer; Seyrek ve Çok seyrekte kitabın
  // tamamından en önemlileri (önem puanıyla) seçilir.
  const DENSITY = { sparse: 'Çok seyrek', rare: 'Seyrek', low: 'Az', medium: 'Orta', high: 'Çok' };
  const DENSITY_HINT = { sparse: 'yaklaşık 25 sayfada bir: kitabın tamamından en önemli anlar',
    rare: 'yaklaşık 10 sayfada bir: kitabın tamamından en önemli anlar', low: 'yaklaşık 4 sayfada bir: önemli anlar',
    medium: 'sahne değişiminde, yaklaşık 1,5 sayfada bir', high: 'yarım–bir sayfada bir' };
  const UPSCALE_LABEL = (value) => (value ? `${String(value).replace('.', ',')}×` : 'Kapalı');
  // F211: kitabin icindekilerdeki bolum adi ("1" -> "1. bölüm"); girdisi olmayan bolumde okuyucunun numarasi
  const CHAPTER = (scene) => (!scene.chapter ? `Bölüm ${scene.section + 1}`
    : /^\d+$/.test(scene.chapter) ? `${scene.chapter}. bölüm` : scene.chapter);

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
  let outfitEdits = $state({});     // F219 sahne -> elle duzenlenen sahneye ozel kiyafetler ("Ad: giysi")
  let fixes = $state({});           // sahne -> duzeltme notu
  let refining = $state('');        // duzeltilen sahne
  let identity = $state(false);     // yeni planda karakter kimligi
  let modifiers = $state([]);       // F202 tarzdan bagimsiz secenekler (karakter olmasin, yalnizca manzara ...)
  let loraCheck = $state(null);     // secilen LoRA'li tarzin dosyasi ComfyUI'de var mi
  let loraStrength = $state(1);
  let extras = $state([]);          // F218 tarza eklenen LoRA'lar (dinamik pozlar ...), kimlikler
  let extraCheck = $state(null);    // son secilen ek LoRA'nin dosyasi ComfyUI'de var mi
  // F209 plan secenekleri: bolum acilis gorseli, mekan kimligi, gorunus degisimi, RTX buyutme
  let openers = $state(false);
  let placeIdentity = $state(false);
  let lookChanges = $state(false);
  let outfits = $state(true);        // F219 kıyafet kilidi (yeni planlarda varsayılan açık)
  let upscale = $state(0);
  let upscaleCheck = $state(null);  // RTX dugumu ComfyUI'de var mi
  let places = $state('');
  // F209 toplu stil degisikligi: istemler kalir, stil kilavuzu ve LoRA degisir, gorseller yeniden uretilir
  let restyling = $state(false);    // panel acik
  let restyleBusy = $state(false);
  let restyleNote = $state('');
  let restylePreset = $state('');
  let restyleRewrite = $state(true);
  let restyleCheck = $state(null);

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
  const plainPresets = $derived((options?.presets ?? []).filter((p) => !p.lora));
  const loraPresets = $derived((options?.presets ?? []).filter((p) => p.lora));
  const noCast = $derived(modifiers.some((m) => options?.no_cast?.includes(m)));
  const modifierLabels = $derived((plan?.modifiers ?? []).map((id) => options?.modifiers?.find((m) => m.id === id)?.label ?? id));
  const noPeople = $derived(modifiers.includes('no-people'));
  const unscaled = $derived(plan?.upscale ? shown.filter((s) => s.url && s.upscaled !== plan.upscale).length : 0);
  const planExtras = $derived((plan?.extras ?? []).map((e) => e.id));
  const placeNames = $derived((plan?.places ?? []).map((p) => p.name));

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
    characters = characterText(value.characters ?? []);
    places = (value.places ?? []).map((p) => `${p.name}: ${p.look}`).join('\n');
    note = value.note ?? note;           // baştan planlarken önceki not ve seçimler hazır gelsin
    preset = value.preset ?? preset;
    density = value.density ?? density;
    identity = Boolean(value.identity);
    modifiers = value.modifiers ?? modifiers;
    loraStrength = value.lora?.strength ?? 1;
    extras = (value.extras ?? []).map((e) => e.id);
    openers = Boolean(value.openers);
    placeIdentity = Boolean(value.place_identity);
    lookChanges = Boolean(value.look_changes);
    outfits = value.outfits !== false;
    upscale = value.upscale ?? 0;
  }

  // Karakterler kutusu: "Ad: görünüş"; F209 görünüm değişimi "Ad [5. bölüm]: yeni görünüş" (o bölümden sonra).
  // F219 kıyafet "Ad (kıyafet): giysi", kalıcı kıyafet değişimi "Ad (kıyafet) [5. bölüm]: yeni giysi".
  const PHASE = /^(.+?)\s*\[\s*(\d+)\.?\s*bölüm\s*\]$/i;
  const OUTFIT = /^(.+?)\s*\(\s*kıyafet\s*\)$/i;
  function characterText(list) {
    return list.flatMap((c) => [`${c.name}: ${c.look}`,
      ...(c.outfit ? [`${c.name} (kıyafet): ${c.outfit}`] : []),
      ...(c.changes ?? []).map((change) => `${c.name} [${change.section + 1}. bölüm]: ${change.look}`),
      ...(c.outfits ?? []).map((change) => `${c.name} (kıyafet) [${change.section + 1}. bölüm]: ${change.outfit}`)]).join('\n');
  }
  function parseCharacters(text) {
    const old = Object.fromEntries((plan?.characters ?? []).map((c) => [c.name.toLowerCase(), c]));
    const list = [];
    const phases = [];
    for (const line of text.split('\n')) {
      const [head, ...rest] = line.split(':');
      const look = rest.join(':').trim();
      if (!head.trim() || !look) continue;
      let name = head.trim();
      const phase = name.match(PHASE);
      if (phase) name = phase[1].trim();
      const outfit = name.match(OUTFIT);
      if (outfit) name = outfit[1].trim();
      if (phase) phases.push({ name, section: Number(phase[2]) - 1, look, key: outfit ? 'outfit' : 'look' });
      else if (outfit) phases.push({ name, look, key: 'outfit' });
      else list.push({ name, look, changes: [], outfits: [] });
    }
    for (const phase of phases) {
      const character = list.find((c) => c.name.toLowerCase() === phase.name.toLowerCase());
      if (!character) continue;
      if (phase.section === undefined) { character.outfit = phase.look; continue; }
      const field = phase.key === 'outfit' ? 'outfits' : 'changes';
      // ayni bolumdeki eski degisimin cumlesi korunur (kutuda yalnizca bolum yazar)
      const before = (old[character.name.toLowerCase()]?.[field] ?? []).find((c) => c.section === phase.section);
      character[field].push({ section: phase.section, start: before?.start ?? 0, [phase.key]: phase.look });
    }
    return list;
  }
  // F219 sahneye özel kıyafet kutusu: "Ad: giysi" satırları
  function outfitText(scene) {
    return Object.entries(scene.outfits ?? {}).map(([name, outfit]) => `${name}: ${outfit}`).join('\n');
  }
  function parseOutfits(text) {
    const result = {};
    for (const line of text.split('\n')) {
      const [name, ...rest] = line.split(':');
      if (name.trim() && rest.join(':').trim()) result[name.trim()] = rest.join(':').trim();
    }
    return result;
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
  // `restyle`: toplu stil degisikligi panelinin kendi notu ve tarzi.
  async function pickPreset(entry, restyle = false) {
    let rest = restyle ? restyleNote : note;
    for (const p of options.presets) rest = rest.replace(p.note, '');
    rest = rest.trim();
    const current = restyle ? restylePreset : preset;
    const [id, text] = current === entry.id ? ['', rest] : [entry.id, entry.note + (rest ? ' ' + rest : '')];
    if (restyle) { restylePreset = id; restyleNote = text; restyleCheck = null; }
    else { preset = id; note = text; loraCheck = null; }
    if (!id || !entry.lora) return;
    const pending = { pending: true, message: 'LoRA dosyası ComfyUI\'de aranıyor…' };
    if (restyle) restyleCheck = pending; else loraCheck = pending;
    const result = await call('art_lora_check', entry.id);
    if (restyle && restylePreset === entry.id) restyleCheck = result;
    if (!restyle && preset === entry.id) loraCheck = result;
  }

  // F209 RTX buyutme: secilince dugum ComfyUI'de aranir; inceleme ekraninda plana kaydedilir.
  async function pickUpscale(value, save = false) {
    upscale = value;
    upscaleCheck = null;
    if (save) {
      const result = await act('art_plan_save', book, { upscale: value });
      if (result) applyPlan(result.plan);
    }
    if (!value) return;
    upscaleCheck = { pending: true, message: 'RTX Video Super Resolution düğümü ComfyUI\'de aranıyor…' };
    const result = await call('art_upscale_check');
    if (upscale === value) upscaleCheck = result;
  }

  async function upscaleExisting() {
    if (otherJob) { toast('Başka bir kitabın görselleri için iş sürüyor.'); return; }
    const result = await act('art_generate', book, null, title, false, null, true);
    if (result?.started) app.artJob = { book, title, stage: 'generate', done: 0, total: result.total, current: '' };
  }

  async function savePlaces() {
    const list = places.split('\n').map((line) => line.split(':')).filter((p) => p.length > 1 && p[0].trim())
      .map(([name, ...look]) => ({ name: name.trim(), look: look.join(':').trim() }));
    const result = await act('art_plan_save', book, { places: list });
    if (result) applyPlan(result.plan);
  }

  async function setPlaceIdentity(value) {
    const result = await act('art_plan_save', book, { place_identity: value });
    if (result) applyPlan(result.plan);
  }

  function openRestyle() {
    restyleNote = plan?.note ?? '';
    restylePreset = plan?.preset ?? '';
    restyleRewrite = true;
    restyleCheck = null;
    restyling = true;
  }

  // Tarzi uygular (stil kilavuzunu dil modeli yeni yone gore yazar) ve butun gorselleri ayni seed'lerle yeniden
  // uretir; kimlik aciksa kullanicinin kendi koymadigi portreler de yeni tarzla yenilenir.
  async function applyRestyle() {
    if (otherJob) { toast('Başka bir kitabın görselleri için iş sürüyor.'); return; }
    const yes = await confirm({ title: 'Tarzı değiştir', message: `Sahneler aynı kalır; ${shown.length} görselin hepsi yeni tarzla yeniden üretilir.`,
      ok: 'Uygula ve yeniden üret', cancel: 'Vazgeç' });
    if (!yes) return;
    restyleBusy = true;
    const result = await act('art_restyle', book, restylePreset, restyleNote, restyleRewrite);
    restyleBusy = false;
    if (!result) return;
    applyPlan(result.plan);
    restyling = false;
    const portraits = plan.identity ? plan.characters.filter((c) => c.portrait_url && !c.portrait_own).map((c) => c.name) : null;
    generate(null, true, portraits?.length ? portraits : null);
  }

  function toggleModifier(id) {
    if (modifiers.includes(id)) { modifiers = modifiers.filter((m) => m !== id); return; }
    // ayni gruptan (orta bos koyu/acik) yalnizca biri
    const group = options?.modifiers?.find((m) => m.id === id)?.group;
    const rivals = group ? options.modifiers.filter((m) => m.group === group).map((m) => m.id) : [];
    modifiers = [...modifiers.filter((m) => !rivals.includes(m)), id];
  }

  // F218 ek LoRA: secilince dosyasi ComfyUI'de aranir; `save` inceleme ekraninda plana kaydeder (yeniden uretince yansir)
  async function toggleExtra(entry, save = false) {
    const current = save ? planExtras : extras;   // inceleme ekrani plani gosterir (kurulumdaki secim degil)
    const on = !current.includes(entry.id);
    const list = on ? [...current, entry.id] : current.filter((id) => id !== entry.id);
    extraCheck = null;
    if (save) {
      const result = await act('art_plan_save', book, { extras: list });
      if (!result) return;
      applyPlan(result.plan);
      toast('Kaydedildi. Görsellere yansıması için yeniden üretin.');
    } else extras = list;
    if (!on) return;
    extraCheck = { pending: true, message: 'LoRA dosyası ComfyUI\'de aranıyor…' };
    const result = await call('art_lora_check', entry.id);
    if ((save ? planExtras : extras).includes(entry.id)) extraCheck = result;
  }

  async function saveExtraStrength(entry, value) {
    value = Number(value);
    if (!Number.isFinite(value) || value === entry.strength) return;
    const result = await act('art_plan_save', book, { extra_strength: [entry.id, value] });
    if (result) { applyPlan(result.plan); toast('LoRA gücü kaydedildi. Görsellere yansıması için yeniden üretin.'); }
  }

  async function saveLoraStrength() {
    const value = Number(loraStrength);
    if (!plan?.lora || !Number.isFinite(value) || value === plan.lora.strength) return;
    const result = await act('art_plan_save', book, { lora_strength: value });
    if (result) { applyPlan(result.plan); toast('LoRA gücü kaydedildi. Görsellere yansıması için yeniden üretin.'); }
  }

  let readingRun = 0;
  async function startPlan(resume = false, openersOnly = false) {
    if (otherJob) { toast('Başka bir kitabın görselleri için iş sürüyor.'); return; }
    if (app.emotionJob) { toast('Duygu etiketleri oluşturulurken görsel planı çıkarılamaz.'); return; }
    if (!resume && !openersOnly && plan?.complete) {
      const yes = await confirm({ title: 'Baştan planla', message: 'Mevcut plan ve üretilmiş görseller silinir. Devam edilsin mi?',
        ok: 'Baştan planla', cancel: 'Vazgeç', danger: true });
      if (!yes) return;
    }
    // app.artJob $state vekiline sarilir (=== tutmaz): baslatma kendi numarasiyla taninir
    const reading = ++readingRun;
    app.artJob = { book, title, stage: 'plan', done: 0, total: 0, reading };
    let sections;
    try {
      sections = await bookSections(book, app.ttsPrefs.split ?? {});
    } catch (error) {
      if (app.artJob?.reading === reading) app.artJob = null;
      toast(String(error?.message ?? error), 'error');
      return;
    }
    if (app.artJob?.reading !== reading) return;   // bolumler okunurken durduruldu
    const result = await act('art_plan_create', book, sections, note, preset, density, title, resume, identity && !noCast, modifiers,
      { openers, places: placeIdentity, changes: lookChanges && !noPeople, outfits: outfits && !noPeople, upscale, extras }, openersOnly);
    if (!result?.started) { if (app.artJob?.reading === reading) app.artJob = null; return; }
    if (app.artJob?.reading === reading) app.artJob = { book, title, stage: 'plan', done: 0, total: result.total };
    replanning = false;
    if (!openersOnly) plan = null;
  }

  // Bolumler okunurken is henuz arka uca gitmedi: durdurmak yalnizca bekleyen baslatmayi birakir.
  function stopPlan() {
    if (job?.reading) { app.artJob = null; return; }
    act('art_cancel');
  }

  async function generate(ids = null, all = false, portraits = null, bodies = null) {
    if (otherJob) { toast('Başka bir kitabın görselleri için iş sürüyor.'); return; }
    const result = await act('art_generate', book, ids, title, all, portraits, false, bodies);
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
    const result = await act('art_plan_save', book, { characters: parseCharacters(characters) });
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
    const values = { prompt: editing[scene.id] };
    if (plan.outfits) values.outfits = parseOutfits(outfitEdits[scene.id] ?? '');
    if (await updateScene(scene, values)) {
      delete editing[scene.id];
      delete outfitEdits[scene.id];
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

  async function setBodies(value) {
    const result = await act('art_plan_save', book, { bodies: value });
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
        <div><button class="btn" onclick={stopPlan}><Icon name="stop" size={15} />Durdur</button></div>
      </div>
    {:else if setup}
      <div class="setup">
        <p class="dim">Dil modeli kitabı okur, sahne değişimlerini seçer ve her sahne için bir görsel istemi yazar. Bütün görseller
          aynı stil kılavuzuyla üretilir. Plan bitince stili ve sahneleri gözden geçirip üretimi siz başlatırsınız.</p>
        <label class="l" for="art-note">Kitap notu <small>Dil modeline verilen yönerge: tarz, ton, neyin gösterilip gösterilmeyeceği.</small></label>
        <textarea id="art-note" class="field" rows="3" bind:value={note}
          placeholder="Örn. daha soyut ol, insan yüzü gösterme, suluboya tarzında, dönemin mimarisini öne çıkar"></textarea>
        <div class="row">
          <span class="dim lead">Hazır tarz</span>
          {#each plainPresets as entry (entry.id)}
            <button class="chip" class:on={preset === entry.id} title={entry.note} onclick={() => pickPreset(entry)}>{entry.label}</button>
          {/each}
        </div>
        {#if loraPresets.length}
          <div class="row">
            <span class="dim lead">LoRA tarzı</span>
            {#each loraPresets as entry (entry.id)}
              <button class="chip" class:on={preset === entry.id} title={`${entry.note}\nLoRA: ${entry.lora}${entry.trigger ? `\nTetik: ${entry.trigger}` : ''}`}
                onclick={() => pickPreset(entry)}>{entry.label}</button>
            {/each}
          </div>
          {#if loraCheck}
            <div class="lora-note" class:bad={loraCheck.ok === false}>
              <Icon name={loraCheck.ok === false ? 'alert' : 'check'} size={14} /><span>{loraCheck.message}</span>
            </div>
          {/if}
        {/if}
        {#if options?.extras?.length}
          <div class="row">
            <span class="dim lead">Ek LoRA</span>
            {#each options.extras as entry (entry.id)}
              <button class="chip" class:on={extras.includes(entry.id)} title={`${entry.note}\nLoRA: ${entry.lora}\nTetik: ${entry.trigger}`}
                onclick={() => toggleExtra(entry)}>{entry.label}</button>
            {/each}
            <span class="dim">Herhangi bir tarzla birlikte kullanılır. Yalnızca sahnelere eklenir, karakter portrelerine eklenmez.</span>
          </div>
          {#if extraCheck}
            <div class="lora-note" class:bad={extraCheck.ok === false}>
              <Icon name={extraCheck.ok === false ? 'alert' : 'check'} size={14} /><span>{extraCheck.message}</span>
            </div>
          {/if}
        {/if}
        <div class="row">
          <span class="dim lead">Seçenekler</span>
          {#each options?.modifiers ?? [] as entry (entry.id)}
            <button class="chip" class:on={modifiers.includes(entry.id)} title={entry.rule} onclick={() => toggleModifier(entry.id)}>{entry.label}</button>
          {/each}
          <span class="dim">Tarzdan bağımsız, birlikte seçilebilir (orta boş koyu ya da açık, biri). Orta boş: üst ve alt kenar iki ayrı görsel olarak üretilir (sahne başına iki görsel), ortası yazı için düz geçiş.</span>
        </div>
        <div class="row">
          <span class="dim">Sıklık</span>
          <div class="seg">
            {#each Object.entries(DENSITY) as [key, label] (key)}
              <button class:on={density === key} onclick={() => (density = key)}>{label}</button>
            {/each}
          </div>
          <Toggle bind:checked={openers} label="Her bölüm başında görsel" />
          <span class="dim">{DENSITY_HINT[density]}{openers
            ? ' Sıklıktan bağımsız olarak her bölüm, o anki sayfadan çizilen bir görselle açılır (bölümün devamını göstermez).'
            : ''}</span>
        </div>
        <div class="row">
          <Toggle bind:checked={placeIdentity} label="Mekân kimliği" />
          <span class="dim">Sık geçen mekânlara sabit bir tarif yazılır; o mekândaki her görsel aynı tarifle çizilir.</span>
        </div>
        <div class="row">
          {#if noPeople}<Toggle checked={false} disabled label="Görünüm değişimi" />
          {:else}<Toggle bind:checked={lookChanges} label="Görünüm değişimi" />{/if}
          <span class="dim">{noPeople ? 'Karakter çizilmediği için kapalı.'
            : outfits ? 'Karakter yaşlanır ya da saçı değişirse sonraki görseller yeni görünüşle çizilir.'
            : 'Karakter yaşlanır, kıyafeti ya da saçı değişirse sonraki görseller yeni görünüşle çizilir.'}</span>
        </div>
        <div class="row">
          {#if noPeople}<Toggle checked={false} disabled label="Kıyafet kilidi" />
          {:else}<Toggle bind:checked={outfits} label="Kıyafet kilidi" />{/if}
          <span class="dim">{noPeople ? 'Karakter çizilmediği için kapalı.'
            : 'Karakterin kıyafeti ayrı yazılır ve her görsele aynen eklenir; metin kıyafetin değiştiğini söylerse (üniforma, gecelik, zırh) o sahnelerde yenisi kullanılır.'}</span>
        </div>
        <div class="row">
          <span class="dim lead">RTX büyütme</span>
          <div class="seg">
            {#each [0, ...(options?.upscales ?? [])] as value (value)}
              <button class:on={upscale === value} onclick={() => pickUpscale(value)}>{UPSCALE_LABEL(value)}</button>
            {/each}
          </div>
          <span class="dim">Üretilen görsel ComfyUI'de RTX Video Super Resolution ile büyütülür (NVIDIA RTX).</span>
        </div>
        {#if upscaleCheck}
          <div class="lora-note" class:bad={upscaleCheck.ok === false}>
            <Icon name={upscaleCheck.ok === false ? 'alert' : 'check'} size={14} /><span>{upscaleCheck.message}</span>
          </div>
        {/if}
        <div class="row">
          {#if noCast}<Toggle checked={false} disabled label="Karakter kimliği" />
          {:else}<Toggle bind:checked={identity} label="Karakter kimliği" />{/if}
          <span class="dim">{noCast ? 'Seçilen seçenekle karakter çizilmediği için kapalı.'
            : 'Karakterler her görselde aynı yüzle çıkar: her karaktere bir portre üretilir, karakterli sahneler bu portreyle çizilir. Ayarlar\'da kimlik iş akışı gerekir.'}</span>
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
          <button class="btn" disabled={Boolean(app.artJob) || !shown.length} title="Sahneler aynı kalır, görseller yeni tarzla yeniden üretilir"
            onclick={() => (restyling ? (restyling = false) : openRestyle())}><Icon name="sparkles" size={15} />Tarzı değiştir</button>
          <button class="btn" disabled={Boolean(app.artJob) || !shown.length} onclick={regenerateAll}><Icon name="refresh" size={15} />Hepsini yeniden üret</button>
          <button class="btn primary" disabled={Boolean(app.artJob) || !missing || !options?.workflow.ok} onclick={() => generate()}>
            <Icon name="image" size={15} />{!missing ? 'Hepsi üretildi' : missing === shown.length ? 'Görselleri üret' : `Eksikleri üret (${missing})`}</button>
        {/if}
      </div>
      {#if generating}<div class="track"><i style:width="{pct(job.done, job.total)}%"></i></div>{/if}
      {#if plan.failed?.length && !app.artJob}
        <div class="lora-note bad">
          <Icon name="alert" size={14} /><span>Kitabın {plan.failed.length} parçası dil modelinden okunamadı; bu parçalardan sahne çıkmadı.</span>
          <button class="btn ghost" onclick={() => startPlan(true)}><Icon name="refresh" size={15} />Yeniden dene</button>
        </div>
      {/if}

      {#if restyling}
        <div class="look restyle">
          <b>Tarzı değiştir</b>
          <p class="dim">Plan ve sahne istemleri aynen kalır; yalnızca her görselin başına eklenen stil kılavuzu ve tarzın LoRA'sı değişir.
            Görseller aynı seed'lerle yeni tarzda yeniden üretilir (karakter kimliği açıksa portreler de).</p>
          <div class="row">
            <span class="dim lead">Hazır tarz</span>
            {#each plainPresets as entry (entry.id)}
              <button class="chip" class:on={restylePreset === entry.id} title={entry.note} onclick={() => pickPreset(entry, true)}>{entry.label}</button>
            {/each}
          </div>
          {#if loraPresets.length}
            <div class="row">
              <span class="dim lead">LoRA tarzı</span>
              {#each loraPresets as entry (entry.id)}
                <button class="chip" class:on={restylePreset === entry.id} title={`${entry.note}\nLoRA: ${entry.lora}`}
                  onclick={() => pickPreset(entry, true)}>{entry.label}</button>
              {/each}
            </div>
            {#if restyleCheck}
              <div class="lora-note" class:bad={restyleCheck.ok === false}>
                <Icon name={restyleCheck.ok === false ? 'alert' : 'check'} size={14} /><span>{restyleCheck.message}</span>
              </div>
            {/if}
          {/if}
          <label class="l" for="art-restyle-note">Yeni tarz <small>Dil modeli stil kılavuzunu bu yöne göre yeniden yazar.</small></label>
          <textarea id="art-restyle-note" class="field" rows="2" bind:value={restyleNote}
            placeholder="Örn. kara kalem eskiz, soluk renkler, daha karanlık ışık"></textarea>
          <div class="row">
            <Toggle bind:checked={restyleRewrite} label="Stil kılavuzunu dil modeli yeniden yazsın" />
            <span class="dim">{restyleRewrite ? '' : 'Kapalıyken stil kılavuzu olduğu gibi kalır; yalnızca tarz ve LoRA değişir.'}</span>
          </div>
          <div class="row end">
            <button class="btn ghost" onclick={() => (restyling = false)}>Vazgeç</button>
            <button class="btn primary" disabled={restyleBusy || Boolean(app.artJob) || !options?.workflow.ok || (!restyleNote.trim() && !restylePreset)}
              onclick={applyRestyle}><Icon name="refresh" size={15} />{restyleBusy ? 'Stil yazılıyor…' : 'Uygula ve hepsini yeniden üret'}</button>
          </div>
        </div>
      {/if}

      <details class="look" open={!scenes.some((s) => s.url)}>
        <summary>Stil ve karakterler</summary>
        <label class="l" for="art-style">Stil kılavuzu <small>Her görselin başına aynen eklenir. Değiştirmek planı yeniden yaptırmaz; kaydedip "Hepsini yeniden üret" deyin.</small></label>
        <textarea id="art-style" class="field" rows="4" bind:value={style} onchange={saveStyle}></textarea>
        <label class="l" for="art-chars">Karakterler <small>Satır başına "Ad: görünüş"; görünüm değişimi "Ad [5. bölüm]: yeni görünüş". Sahne istemlerine dil modeli kopyalar; yeni sahnelere yansır, var olan istemler değişmez.{#if plan.outfits} Kıyafet "Ad (kıyafet): giysi", kalıcı değişimi "Ad (kıyafet) [5. bölüm]: yeni giysi"; görsel üretilirken isteme eklenir.{/if}</small></label>
        <textarea id="art-chars" class="field" rows="3" bind:value={characters} onchange={saveCharacters}></textarea>
        <div class="row">
          <Toggle checked={Boolean(plan.place_identity)} disabled={Boolean(app.artJob)} label="Mekân kimliği" onchange={setPlaceIdentity} />
          <span class="dim">Sahnenin mekânının tarifi her görselin istemine eklenir.</span>
        </div>
        {#if plan.place_identity}
          <label class="l" for="art-places">Mekânlar <small>Satır başına "Ad: kalıcı görünüş". Tarifi değiştirmek o mekândaki görsellere yeniden üretince yansır.</small></label>
          <textarea id="art-places" class="field" rows="3" bind:value={places} onchange={savePlaces}></textarea>
        {/if}
        <div class="row">
          <span class="dim">RTX büyütme</span>
          <div class="seg">
            {#each [0, ...(options?.upscales ?? [])] as value (value)}
              <button class:on={(plan.upscale ?? 0) === value} disabled={Boolean(app.artJob)} onclick={() => pickUpscale(value, true)}>{UPSCALE_LABEL(value)}</button>
            {/each}
          </div>
          {#if unscaled}
            <button class="btn sm" disabled={Boolean(app.artJob)} onclick={upscaleExisting}><Icon name="image" size={13} />Var olanları büyüt ({unscaled})</button>
          {/if}
        </div>
        {#if upscaleCheck}
          <div class="lora-note left" class:bad={upscaleCheck.ok === false}>
            <Icon name={upscaleCheck.ok === false ? 'alert' : 'check'} size={14} /><span>{upscaleCheck.message}</span>
          </div>
        {/if}
        {#if plan.openers || plan.look_changes || plan.outfits}
          <div class="dim">{[plan.openers && 'Her bölüm başında görsel', plan.look_changes && 'görünüm değişimi', plan.outfits && 'kıyafet kilidi'].filter(Boolean).join(' · ')} açık</div>
        {/if}
        <div class="row">
          <button class="btn sm" disabled={Boolean(app.artJob)} onclick={() => startPlan(false, true)}
            title="Yeniden planlamadan, açılış görseli olmayan her bölüme o anki sayfadan bir görsel planlanır."><Icon name="image" size={13} />{plan.openers ? 'Eksik bölüm açılışlarını tamamla' : 'Her bölüm başına görsel ekle'}</button>
        </div>
        {#if plan.lora}
          <div class="row lora">
            <span><b>LoRA:</b> {plan.lora.label}{#if plan.lora.trigger} · tetik <code>{plan.lora.trigger}</code>{/if}</span>
            <label class="dim">Güç <input class="field num" type="number" min="0" max="2" step="0.05" bind:value={loraStrength} onchange={saveLoraStrength} /></label>
          </div>
        {/if}
        {#if options?.extras?.length}
          <div class="row">
            <span class="dim">Ek LoRA</span>
            {#each options.extras as entry (entry.id)}
              <button class="chip" class:on={planExtras.includes(entry.id)} disabled={Boolean(app.artJob)} title={entry.note}
                onclick={() => toggleExtra(entry, true)}>{entry.label}</button>
            {/each}
          </div>
          {#each plan.extras ?? [] as entry (entry.id)}
            <div class="row lora">
              <span><b>{entry.label}</b>{#if entry.trigger} · tetik <code>{entry.trigger}</code>{/if}</span>
              <label class="dim">Güç <input class="field num" type="number" min="0" max="2" step="0.05" value={entry.strength}
                onchange={(e) => saveExtraStrength(entry, e.currentTarget.value)} /></label>
            </div>
          {/each}
          {#if extraCheck}
            <div class="lora-note left" class:bad={extraCheck.ok === false}>
              <Icon name={extraCheck.ok === false ? 'alert' : 'check'} size={14} /><span>{extraCheck.message}</span>
            </div>
          {/if}
        {/if}
        {#if modifierLabels.length}<div class="dim">Seçenekler: {modifierLabels.join(', ')}</div>{/if}
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
        {#if plan.identity && plan.outfits}
          <div class="row">
            <Toggle checked={Boolean(plan.bodies)} disabled={Boolean(app.artJob)} label="Tam boy kıyafet referansı" onchange={setBodies} />
          </div>
          <p class="dim">Açıkken her karakterin giydiği her kıyafet için portreden tam boy bir referans görseli üretilir; sahneler portre yerine o anki
            kıyafetin tam boy görseliyle çizilir, böylece kıyafet görselden de korunur. Kıyafet ya da portre değişince referans kendiliğinden yenilenir.</p>
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
                {#if plan.bodies && character.body_urls?.length}
                  <div class="bodies" title="Tam boy kıyafet referansları">
                    {#each character.body_urls as url (url)}<img src={url} alt={`${character.name} tam boy`} loading="lazy" />{/each}
                    <button class="btn sm ghost" disabled={Boolean(app.artJob) || !options?.workflow.ok} title="Tam boy referansları yeni seed ile üret"
                      onclick={() => generate(null, false, null, [character.name])}><Icon name="refresh" size={13} /></button>
                  </div>
                {:else if generating && job.current === `Tam boy: ${character.name}`}<span class="dim">Tam boy üretiliyor…</span>{/if}
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
              {:else if scene.error && !scene.skip && !(generating && job.current === scene.title)}<span class="dim" title={scene.error}>Üretilemedi: {scene.error}</span>
              {:else}<span class="dim">{scene.skip ? 'Atlandı' : generating && job.current === scene.title ? 'Üretiliyor…' : 'Henüz üretilmedi'}</span>{/if}
            </div>
            <div class="meta">
              <b class="ellipsis" title={scene.title}>{scene.title}</b>
              <span class="dim" title={`Okuyucuda ${scene.section + 1}. bölüm`}>{[scene.opening ? `${CHAPTER(scene)} · açılış` : `${CHAPTER(scene)} · cümle ${scene.start + 1}`,
                scene.importance && `önem ${scene.importance}/10`, scene.upscaled && `${UPSCALE_LABEL(scene.upscaled)} büyük`].filter(Boolean).join(' · ')}</span>
            </div>
            {#if plan.place_identity && placeNames.length}
              <select class="field place" value={scene.place ?? ''} disabled={Boolean(app.artJob)} title="Sahnenin mekânı: kalıcı tarifi isteme eklenir"
                onchange={(e) => updateScene(scene, { place: e.currentTarget.value })}>
                <option value="">Mekân: yok</option>
                {#each placeNames as name (name)}<option value={name}>Mekân: {name}</option>{/each}
                {#if scene.place && !placeNames.includes(scene.place)}<option value={scene.place}>Mekân: {scene.place} (listede yok)</option>{/if}
              </select>
            {/if}
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
              {#if plan.outfits}
                <label class="l" for={`art-outfit-${scene.id}`}>Bu sahneye özel kıyafet <small>Satır başına "Ad: giysi"; boş bırakılan karakter o anki kıyafetiyle çizilir.</small></label>
                <textarea id={`art-outfit-${scene.id}`} class="field" rows="2" bind:value={outfitEdits[scene.id]}></textarea>
              {/if}
              <div class="acts">
                <button class="btn sm ghost" onclick={() => { delete editing[scene.id]; delete outfitEdits[scene.id]; }}>Vazgeç</button>
                <button class="btn sm primary" disabled={Boolean(app.artJob)} onclick={() => savePrompt(scene)}>Kaydet ve üret</button>
              </div>
            {:else}
              <p class="prompt dim" title={scene.prompt}>{scene.prompt}</p>
              {#if scene.clothing?.some((c) => c.outfit)}
                <p class="clothing dim">{#each scene.clothing.filter((c) => c.outfit) as c (c.name)}<span title={c.own ? 'Yalnızca bu sahneye ait kıyafet' : 'O anki kıyafeti'}><b>{c.name}{c.own ? ' (bu sahnede)' : ''}:</b> {c.outfit}</span>{/each}</p>
              {/if}
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
                  <button class="btn sm ghost" onclick={() => { editing[scene.id] = scene.prompt; outfitEdits[scene.id] = outfitText(scene); }}><Icon name="pencil" size={13} />İstemi düzenle</button>
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
  .row .lead { min-width: 78px; }
  .lora-note { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--secondary); padding-left: 86px; }
  .lora-note.bad { color: var(--warning); }
  .lora-note.left { padding-left: 0; }
  .restyle { gap: 10px; padding: 12px; }
  .restyle p { margin: 0; font-size: 12px; line-height: 1.5; }
  .place { height: 28px; font-size: 12px; padding: 0 8px; }
  .row.lora { margin-top: 6px; justify-content: space-between; }
  .row.lora code { font-size: 12px; }
  .num { width: 70px; height: 28px; font-size: 12px; margin-left: 6px; }
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
  .bodies { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
  .bodies img { width: 30px; aspect-ratio: 832 / 1216; object-fit: cover; border-radius: 4px; background: var(--surface); }
  .cast { display: flex; gap: 4px; flex-wrap: wrap; }
  .clothing { margin: 0; font-size: 11.5px; line-height: 1.4; display: flex; flex-direction: column; gap: 2px; }
  .cast .chip { font-size: 11.5px; padding: 2px 8px; }
  .fix { display: flex; gap: 6px; }
  .fix .field { flex: 1; min-width: 0; height: 30px; font-size: 12px; }
  .acts { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
  textarea.field { font-size: 13px; line-height: 1.45; width: 100%; box-sizing: border-box; }
</style>
