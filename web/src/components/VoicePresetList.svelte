<script>
  // Kayitli sesler (F179): Metinden ses sayfasinin sekmesi. Sesler burada eklenir, duzenlenir ve siralanir
  // (surukle-birak ya da oklar); sira presets.json'a yazilir, okuyucudaki ve diger ses secicileri ayni sirayla listeler.
  import Icon from '../lib/Icon.svelte';
  import VoicePresetModal from './VoicePresetModal.svelte';
  import { app, act } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';

  // onchange(): sesler degisti (sayfanin ses secicisi listeyi yeniler)
  let { onchange } = $props();

  let presets = $state([]);
  let loaded = $state(false);
  let editing = $state(undefined);    // undefined: kapali, null: yeni ses, kayit: duzenle
  let dragging = $state(null);        // suruklenen sesin kimligi
  let moved = false;

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

  function deleted(result) {
    const wasActive = editing?.id === app.ttsPrefs.active_preset;
    presets = result.presets;
    editing = undefined;
    if (wasActive) app.ttsPrefs = { ...app.ttsPrefs, active_preset: '' };
    onchange?.();
  }
</script>

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
        <li class="item" class:off={!usable(preset.voice)} class:drag={dragging === preset.id} draggable="true"
          ondragstart={(e) => { dragging = preset.id; e.dataTransfer.effectAllowed = 'move'; }}
          ondragover={(e) => dragOver(e, index)} ondrop={(e) => e.preventDefault()} ondragend={dragEnd}>
          <span class="grip" title="Sürükleyerek sırala"><Icon name="list" size={16} /></span>
          <span class="no">{index + 1}</span>
          <span class="av" style:background={color(preset.id)}>{#if preset.image}<img src={preset.image} alt="" />{:else}{initial(preset.name)}{/if}</span>
          <span class="tx"><b>{preset.name}</b><small>{voiceLabel(preset.voice)}{usable(preset.voice) ? '' : ' (kurulu değil)'}</small></span>
          {#if preset.id === app.ttsPrefs.active_preset}<span class="chip-on">Okuyucuda seçili</span>{/if}
          <button class="icon-btn sm" title="Yukarı taşı" disabled={index === 0} onclick={() => step(index, -1)}><Icon name="up" size={15} /></button>
          <button class="icon-btn sm" title="Aşağı taşı" disabled={index === presets.length - 1} onclick={() => step(index, 1)}><Icon name="down" size={15} /></button>
          <button class="icon-btn sm" title="Düzenle" onclick={() => (editing = preset)}><Icon name="pencil" size={15} /></button>
        </li>
      {/each}
    </ul>
  {/if}
</div>

{#if editing !== undefined}
  <VoicePresetModal preset={editing} onsave={saved} ondelete={deleted} onclose={() => (editing = undefined)} />
{/if}

<style>
  .presets { display: flex; flex-direction: column; min-height: 0; overflow: auto; }
  .top { display: flex; align-items: center; gap: 16px; padding: 16px; border-bottom: 1px solid var(--outline); }
  .top > div { flex: 1; min-width: 0; }
  .top b { display: block; font-size: 15px; }
  .top small { display: block; color: var(--dim); font-size: 12px; margin-top: 2px; }
  ul { list-style: none; margin: 0; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
  .item { display: flex; align-items: center; gap: 12px; padding: 8px 10px; border-radius: 10px; border: 1px solid transparent; }
  .item:hover { background: var(--surface-hover); }
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
</style>
