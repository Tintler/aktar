<script>
  // Kayitli sesler (F179): Metinden ses sayfasinin sekmesi. Sesler burada eklenir, duzenlenir ve siralanir
  // (surukle-birak ya da oklar); sira presets.json'a yazilir, okuyucudaki ve diger ses secicileri ayni sirayla listeler.
  // F191: liste sayfayi kaplar; sagdaki panelde secili ses ornek metinle okutulur, begenilen okuma sesin onizlemesi
  // olarak saklanir (bridge tts_preset_preview_*). Satirdaki oynat dugmesi ve dublaj seciciler saklanan onizlemeyi calar.
  import Icon from '../lib/Icon.svelte';
  import VoicePresetModal from './VoicePresetModal.svelte';
  import { app, act, savePref, toast } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';
  import { splitText, QUOTE_DEFAULTS } from '../lib/sentences.js';
  import { resolvePauses, pauseAfter } from '../lib/pauses.js';

  // onchange(): sesler degisti (sayfanin ses secicisi listeyi yeniler)
  let { onchange } = $props();

  let presets = $state([]);
  let loaded = $state(false);
  let editing = $state(undefined);    // undefined: kapali, null: yeni ses, kayit: duzenle
  let dragging = $state(null);        // suruklenen sesin kimligi
  let moved = false;

  const SAMPLE = 'Merhaba! Bu benim sesim. Uzun bir kitabı da, kısa bir mesajı da sizin için böyle okuyacağım.';
  const SAMPLE_LIMIT = 1000;
  let selectedId = $state('');
  const selected = $derived(presets.find((p) => p.id === selectedId) ?? presets[0] ?? null);
  let sample = $state('');
  let sampleFor = '';
  let draft = $state(null);           // {id, url, duration, text}: okutulan ama saklanmayan onizleme
  let reading = $state('');           // okunan sesin kimligi
  let playing = $state('');           // satirdan calinan onizlemenin kimligi
  let player = null;

  $effect(() => {
    const id = selected?.id ?? '';
    if (id === sampleFor) return;
    sampleFor = id;
    sample = selected?.preview_text || app.prefs.speech?.sample_text || SAMPLE;
  });

  const PALETTE = ['#7c3aed', '#0ea5e9', '#22c55e', '#f97316', '#e11d48', '#14b8a6', '#eab308', '#a855f7'];
  const color = (id) => PALETTE[[...String(id)].reduce((sum, c) => sum + c.charCodeAt(0), 0) % PALETTE.length];
  const initial = (name) => (String(name).trim()[0] ?? '?').toLocaleUpperCase('tr');
  const voiceLabel = (value) => {
    const [engineId, voiceId] = String(value).split('/');
    const engine = app.engines.find((e) => e.id === engineId);
    const voice = engine?.voices.find((v) => v.id === voiceId);
    if (!engine) return 'Motor kurulu değil';
    return engine.voices.length > 1 && voice ? `${engine.name} · ${voice.name}` : engine.name;
  };
  const usable = (value) => app.engines.some((e) => e.mode && value.startsWith(e.id + '/'));

  async function load() {
    const result = await call('tts_presets');
    if (result?.presets) presets = result.presets;
    loaded = true;
  }
  load();
  $effect(() => {
    if (!app.engines.length) call('tts_engines').then((list) => { if (Array.isArray(list)) app.engines = list; });
  });

  async function commit() {
    const result = await act('tts_preset_order', presets.map((p) => p.id));
    if (result?.presets) presets = result.presets;
    onchange?.();
  }

  function move(from, to) {
    if (to < 0 || to >= presets.length || from === to) return false;
    const [item] = presets.splice(from, 1);
    presets.splice(to, 0, item);
    return true;
  }

  function step(index, delta) {
    if (move(index, index + delta)) commit();
  }

  function dragOver(event, index) {
    if (dragging == null) return;
    event.preventDefault();
    const from = presets.findIndex((p) => p.id === dragging);
    if (from !== index && move(from, index)) moved = true;
  }

  function dragEnd() {
    dragging = null;
    if (moved) commit();
    moved = false;
  }

  function saved(result) {
    presets = result.presets;
    editing = undefined;
    onchange?.();
  }

  function stopPlaying() {
    player?.pause();
    player = null;
    playing = '';
  }
  $effect(() => stopPlaying);

  function playPreview(preset) {
    const same = playing === preset.id;
    stopPlaying();
    if (same || !preset.preview) return;
    player = new Audio(preset.preview);
    player.onended = stopPlaying;
    playing = preset.id;
    player.play().catch(stopPlaying);
  }

  async function readSample() {
    const preset = selected;
    const text = sample.trim();
    if (!preset || !text || reading) return;
    const { sentences, breaks } = splitText(text, { ...QUOTE_DEFAULTS, ...(app.ttsPrefs.split ?? {}) });
    const pauses = resolvePauses(app.ttsPrefs.pauses);
    const gaps = sentences.map((t, i) => pauseAfter(t, breaks.has(i), pauses, 1));
    savePref({ speech: { ...(app.prefs.speech ?? {}), sample_text: text } });
    stopPlaying();
    draft = null;
    reading = preset.id;
    const result = await act('tts_preset_preview_create', preset.id, sentences, gaps);
    reading = '';
    if (result?.url) draft = { id: preset.id, url: result.url, duration: result.duration, text };
  }

  async function keepDraft() {
    if (!draft) return;
    const result = await act('tts_preset_preview_save', draft.id, draft.text);
    if (!result?.presets) return;
    presets = result.presets;
    draft = null;
    toast('Önizleme saklandı.', 'ok');
    onchange?.();
  }

  async function dropPreview(preset) {
    stopPlaying();
    const result = await act('tts_preset_preview_delete', preset.id);
    if (result?.presets) presets = result.presets;
  }

  const seconds = (value) => `${(value || 0).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} sn`;

  function deleted(result) {
    const wasActive = editing?.id === app.ttsPrefs.active_preset;
    presets = result.presets;
    editing = undefined;
    if (wasActive) app.ttsPrefs = { ...app.ttsPrefs, active_preset: '' };
    onchange?.();
  }
</script>

<div class="wrap">
<div class="presets card">
  <div class="top">
    <div>
      <b>Kayıtlı sesler</b>
      <small>Sıralamak için sürükleyin ya da oklarla taşıyın. Okuyucudaki, dublajdaki ve bu sayfadaki ses seçicileri bu sırayla gösterir.</small>
    </div>
    <button class="btn primary" onclick={() => (editing = null)}><Icon name="plus" size={15} />Yeni ses</button>
  </div>

  {#if loaded && !presets.length}
    <div class="empty">
      <Icon name="mic" size={26} />
      <b>Henüz kayıtlı ses yok</b>
      <span>Kayıttan ses (klon), VoxCPM ses tarifi ya da EMA Lightning ile ad ve resim vererek ses ekleyin.</span>
    </div>
  {:else}
    <ul role="list">
      {#each presets as preset, index (preset.id)}
        <li class="item" class:off={!usable(preset.voice)} class:drag={dragging === preset.id} class:sel={selected?.id === preset.id}
          draggable="true"
          ondragstart={(e) => { dragging = preset.id; e.dataTransfer.effectAllowed = 'move'; }}
          ondragover={(e) => dragOver(e, index)} ondrop={(e) => e.preventDefault()} ondragend={dragEnd}>
          <span class="grip" title="Sürükleyerek sırala"><Icon name="list" size={16} /></span>
          <span class="no">{index + 1}</span>
          <button class="pick" title="Örnek metinle dinle" onclick={() => (selectedId = preset.id)}>
            <span class="av" style:background={color(preset.id)}>{#if preset.image}<img src={preset.image} alt="" />{:else}{initial(preset.name)}{/if}</span>
            <span class="tx"><b>{preset.name}</b><small>{voiceLabel(preset.voice)}{usable(preset.voice) ? '' : ' (kurulu değil)'}</small></span>
          </button>
          {#if preset.id === app.ttsPrefs.active_preset}<span class="chip-on">Okuyucuda seçili</span>{/if}
          {#if preset.preview}
            <button class="icon-btn sm" class:on={playing === preset.id} title={playing === preset.id ? 'Durdur' : 'Önizlemeyi dinle'}
              onclick={() => playPreview(preset)}><Icon name={playing === preset.id ? 'stop' : 'play'} size={14} /></button>
          {/if}
          <button class="icon-btn sm" title="Yukarı taşı" disabled={index === 0} onclick={() => step(index, -1)}><Icon name="up" size={15} /></button>
          <button class="icon-btn sm" title="Aşağı taşı" disabled={index === presets.length - 1} onclick={() => step(index, 1)}><Icon name="down" size={15} /></button>
          <button class="icon-btn sm" title="Düzenle" onclick={() => (editing = preset)}><Icon name="pencil" size={15} /></button>
        </li>
      {/each}
    </ul>
  {/if}
</div>

{#if selected}
  <aside class="sample card">
    <div class="who">
      <span class="av" style:background={color(selected.id)}>{#if selected.image}<img src={selected.image} alt="" />{:else}{initial(selected.name)}{/if}</span>
      <span class="tx"><b>{selected.name}</b><small>{voiceLabel(selected.voice)}</small></span>
    </div>

    <label class="row">
      <span class="label">Örnek metin</span>
      <textarea class="field selectable" rows="5" maxlength={SAMPLE_LIMIT} bind:value={sample} disabled={!!reading}></textarea>
      <small>Sesi bu metinle okutup dinleyin; beğendiğiniz okumayı önizleme olarak saklayın.</small>
    </label>

    {#if reading === selected.id}
      <div class="busy"><span class="spin"></span>Okunuyor… (ses motoru ilk seferde yüklenir)</div>
      <button class="btn" onclick={() => call('tts_preset_preview_cancel')}><Icon name="stop" size={15} />Durdur</button>
    {:else}
      <button class="btn primary" disabled={!sample.trim() || !!reading || !usable(selected.voice)} onclick={readSample}
        title={usable(selected.voice) ? '' : 'Bu sesin motoru kurulu değil'}><Icon name="waveform" size={16} />Okut</button>
    {/if}

    {#if draft?.id === selected.id}
      <div class="clip">
        <span class="head">Yeni okuma · {seconds(draft.duration)}</span>
        <audio controls src={draft.url}></audio>
        <div class="acts">
          <button class="btn sm primary" onclick={keepDraft}><Icon name="check" size={14} />Önizleme olarak sakla</button>
          <button class="btn sm" onclick={() => (draft = null)}>Vazgeç</button>
        </div>
      </div>
    {/if}

    <div class="clip">
      <span class="head">Saklanan önizleme</span>
      {#if selected.preview}
        <audio controls src={selected.preview}></audio>
        {#if selected.preview_text}<p class="said selectable">“{selected.preview_text}”</p>{/if}
        <div class="acts">
          <button class="btn sm" onclick={() => (sample = selected.preview_text || sample)}>Metni kutuya al</button>
          <button class="btn sm" onclick={() => dropPreview(selected)}><Icon name="trash" size={14} />Sil</button>
        </div>
      {:else}
        <small>Henüz yok. Saklanınca listede ve dublajdaki ses seçicilerinde bu okuma çalınır.</small>
      {/if}
    </div>
  </aside>
{/if}
</div>

{#if editing !== undefined}
  <VoicePresetModal preset={editing} onsave={saved} ondelete={deleted} onclose={() => (editing = undefined)} />
{/if}

<style>
  .wrap { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; align-items: start; }
  .presets { display: flex; flex-direction: column; min-height: 0; max-height: 100%; overflow: auto; }
  .top { display: flex; align-items: center; gap: 16px; padding: 16px; border-bottom: 1px solid var(--outline); }
  .top > div { flex: 1; min-width: 0; }
  .top b { display: block; font-size: 15px; }
  .top small { display: block; color: var(--dim); font-size: 12px; margin-top: 2px; }
  ul { list-style: none; margin: 0; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
  .item { display: flex; align-items: center; gap: 12px; padding: 8px 10px; border-radius: 10px; border: 1px solid transparent; }
  .pick { flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; text-align: left; color: inherit; padding: 0;
    background: none; border: 0; cursor: pointer; }
  .item:hover { background: var(--surface-hover); }
  .item.sel { background: var(--surface-active); }
  .icon-btn.on { color: var(--accent); }
  .item.drag { opacity: .5; border-color: var(--accent); }
  .item.off .tx, .item.off .av { opacity: .55; }
  .grip { color: var(--dim); cursor: grab; display: inline-flex; }
  .no { width: 18px; text-align: right; font-size: 12px; color: var(--dim); font-variant-numeric: tabular-nums; }
  .av { width: 36px; height: 36px; border-radius: 50%; flex: none; overflow: hidden; display: grid; place-items: center;
    color: #fff; font-weight: 700; font-size: 15px; }
  .av img { width: 100%; height: 100%; object-fit: cover; }
  .tx { flex: 1; min-width: 0; }
  .tx b, .tx small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tx b { font-size: 13px; }
  .tx small { color: var(--dim); font-size: 12px; }
  .chip-on { font-size: 11px; font-weight: 600; color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent);
    padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
  .empty { display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center; padding: 48px 24px; color: var(--secondary); }
  .empty span { color: var(--dim); font-size: 13px; max-width: 420px; }
  .sample { display: flex; flex-direction: column; gap: 14px; padding: 16px; max-height: 100%; overflow: auto; }
  .who { display: flex; align-items: center; gap: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--outline); }
  .who .av { width: 44px; height: 44px; }
  .row { display: flex; flex-direction: column; gap: 6px; }
  .row small, .clip small { font-size: 11px; color: var(--dim); }
  .row textarea { resize: vertical; min-height: 96px; font: 14px/1.6 inherit; }
  .busy { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--secondary); }
  .spin { width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--outline); border-top-color: var(--accent);
    animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .clip { display: flex; flex-direction: column; gap: 8px; padding-top: 12px; border-top: 1px solid var(--outline); }
  .clip .head { font-size: 12px; font-weight: 600; color: var(--secondary); }
  .clip audio { width: 100%; height: 36px; }
  .said { margin: 0; font-size: 12px; color: var(--dim); line-height: 1.5; }
  .acts { display: flex; flex-wrap: wrap; gap: 6px; }
  @media (max-width: 1000px) { .wrap { grid-template-columns: 1fr; } }
</style>
