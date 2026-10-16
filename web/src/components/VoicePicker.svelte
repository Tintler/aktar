<script>
  // Okuyucunun sag altindaki ses secici (F137): kayitli sesler resimleriyle listelenir, tiklayinca o ses
  // okumaya baslar; Ayarlar'a gitmeden yeni ses eklenir ya da duzenlenir.
  import Icon from '../lib/Icon.svelte';
  import VoicePresetModal from './VoicePresetModal.svelte';
  import { app, act } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';

  // onchange(): secili ses degisti (okuyucu motoru yeniden hazirlar, okuyorsa kaldigi cumleden surer).
  let { onchange } = $props();

  let presets = $state([]);
  let open = $state(false);
  let editing = $state(undefined);    // undefined: kapali, null: yeni ses, kayit: duzenle

  const PALETTE = ['#7c3aed', '#0ea5e9', '#22c55e', '#f97316', '#e11d48', '#14b8a6', '#eab308', '#a855f7'];
  const color = (id) => PALETTE[[...String(id)].reduce((sum, c) => sum + c.charCodeAt(0), 0) % PALETTE.length];
  const initial = (name) => (String(name).trim()[0] ?? '?').toLocaleUpperCase('tr');

  const active = $derived(presets.find((p) => p.id === app.ttsPrefs.active_preset) ?? null);
  // Ayarlar'daki ses (onayar secili degilken): tr icin secilen ya da varsayilan motor
  const fallbackLabel = $derived.by(() => {
    const saved = app.ttsPrefs.voices?.tr ?? '';
    const [engineId, voiceId] = saved.split('/');
    const engine = app.engines.find((e) => e.id === engineId && e.mode) ?? app.engines.find((e) => e.mode);
    const voice = engine?.voices.find((v) => v.id === voiceId) ?? engine?.voices[0];
    if (!engine) return 'Ses motoru yok';
    return engine.voices.length > 1 && voice ? `${engine.name} · ${voice.name}` : engine.name;
  });
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
  }
  load();
  $effect(() => {
    if (!app.engines.length) call('tts_engines').then((list) => { if (Array.isArray(list)) app.engines = list; });
  });

  async function choose(id) {
    open = false;
    if ((app.ttsPrefs.active_preset ?? '') === id) return;
    const result = await act('tts_preset_apply', id);
    if (!result) return;
    app.ttsPrefs = { ...app.ttsPrefs, ...result.tts };
    onchange?.();
  }

  function edit(preset, event) {
    event?.stopPropagation();
    open = false;
    editing = preset;
  }

  function saved(result) {
    const wasActive = editing && editing.id === app.ttsPrefs.active_preset;
    presets = result.presets;
    editing = undefined;
    if (wasActive) {
      // Secili ses duzenlendi: arka uc tercihleri guncelledi, okuyucu motoru yeniden hazirlar.
      call('ui_prefs').then((prefs) => { app.ttsPrefs = { ...app.ttsPrefs, ...(prefs?.tts ?? {}) }; onchange?.(); });
    } else {
      choose(result.saved.id);    // yeni ya da duzenlenen ses hemen secilir
    }
  }

  function deleted(result) {
    const wasActive = editing?.id === app.ttsPrefs.active_preset;
    presets = result.presets;
    editing = undefined;
    if (wasActive) { app.ttsPrefs = { ...app.ttsPrefs, active_preset: '' }; onchange?.(); }
  }
</script>

<svelte:window onclick={(e) => { if (open && !e.target.closest('.voice-picker')) open = false; }} />

<div class="voice-picker">
  <button class="chip" title="Okuyan ses" onclick={() => (open = !open)}>
    {#if active}
      <span class="av sm" style:background={color(active.id)}>{#if active.image}<img src={active.image} alt="" />{:else}{initial(active.name)}{/if}</span>
      <span class="nm">{active.name}</span>
    {:else}
      <Icon name="mic" size={14} /><span class="nm">{fallbackLabel}</span>
    {/if}
    <Icon name="up" size={12} />
  </button>

  {#if open}
    <div class="pop" role="menu">
      <div class="head">Okuyan ses</div>
      <button class="item" class:on={!active} role="menuitemradio" aria-checked={!active} onclick={() => choose('')}>
        <span class="av gear"><Icon name="settings" size={16} /></span>
        <span class="tx"><b>Ayarlardaki ses</b><small>{fallbackLabel}</small></span>
        {#if !active}<Icon name="check" size={16} />{/if}
      </button>
      {#each presets as preset (preset.id)}
        <div class="item" class:on={active?.id === preset.id} class:off={!usable(preset.voice)} role="menuitemradio" tabindex="0"
          aria-checked={active?.id === preset.id} onclick={() => choose(preset.id)} onkeydown={(e) => { if (e.key === 'Enter') choose(preset.id); }}>
          <span class="av" style:background={color(preset.id)}>{#if preset.image}<img src={preset.image} alt="" />{:else}{initial(preset.name)}{/if}</span>
          <span class="tx"><b>{preset.name}</b><small>{voiceLabel(preset.voice)}</small></span>
          {#if active?.id === preset.id}<Icon name="check" size={16} />{/if}
          <button class="icon-btn sm ed" title="Düzenle" onclick={(e) => edit(preset, e)}><Icon name="pencil" size={14} /></button>
        </div>
      {/each}
      <button class="item add" onclick={() => edit(null)}>
        <span class="av gear"><Icon name="plus" size={16} /></span><span class="tx"><b>Yeni ses</b><small>Kayıttan ses, VoxCPM ya da EMA Lightning</small></span>
      </button>
    </div>
  {/if}
</div>

{#if editing !== undefined}
  <VoicePresetModal preset={editing} onsave={saved} ondelete={deleted} onclose={() => (editing = undefined)} />
{/if}

<style>
  .voice-picker { position: relative; }
  .chip { height: 30px; padding: 0 10px 0 4px; border-radius: 999px; background: var(--surface); font-size: 12px; font-weight: 600;
    display: inline-flex; align-items: center; gap: 6px; max-width: 180px; }
  .chip:hover { background: var(--surface-hover); }
  .chip > :global(svg:first-child) { margin-left: 6px; }
  .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .av { width: 36px; height: 36px; border-radius: 50%; flex: none; overflow: hidden; display: grid; place-items: center;
    color: #fff; font-weight: 700; font-size: 15px; }
  .av.sm { width: 22px; height: 22px; font-size: 11px; }
  .av img { width: 100%; height: 100%; object-fit: cover; }
  .av.gear { background: var(--surface-active); color: var(--secondary); }
  .pop { position: absolute; right: 0; bottom: 40px; width: 320px; max-height: 60vh; overflow: auto; z-index: 30; padding: 6px;
    background: var(--overlay); border: 1px solid var(--outline); border-radius: 14px; box-shadow: 0 8px 28px var(--shadow); }
  .head { font-size: 11px; font-weight: 700; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; padding: 8px 10px 6px; }
  .item { display: flex; align-items: center; gap: 12px; width: 100%; padding: 8px 10px; border-radius: 10px; text-align: left; cursor: pointer; }
  .item:hover { background: var(--surface-hover); }
  .item.on { background: var(--surface); }
  .item.on > :global(svg) { color: var(--accent); }
  .item.off { opacity: .55; }
  .tx { flex: 1; min-width: 0; }
  .tx b, .tx small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tx b { font-size: 13px; }
  .tx small { color: var(--dim); font-size: 12px; }
  .ed { opacity: 0; }
  .item:hover .ed, .ed:focus-visible { opacity: 1; }
  .add { border-top: 1px solid var(--outline); border-radius: 0 0 10px 10px; margin-top: 4px; }
</style>
