<script>
  // F224 kitap gorsellerinde LoRA'siz hazir tarzlar: 'group'suz tarzlar hep gorunur, gruplular "Daha fazla" ile
  // acilir (acik/kapali ui.json art_presets_open). Kapaliyken secili tarz gruplu olsa da gorunur kalir.
  // Acikken suzme kutusu ad ve notta arar. Plan kurulumu ve "Tarzı değiştir" paneli ayni bileseni kullanir.
  import Icon from '../lib/Icon.svelte';
  import { app, savePref } from '../lib/state.svelte.js';

  let { presets = [], selected = '', onpick } = $props();

  let query = $state('');

  const open = $derived(Boolean(app.prefs.art_presets_open));
  const top = $derived(presets.filter((p) => !p.group));
  const more = $derived(presets.filter((p) => p.group));
  const picked = $derived(more.find((p) => p.id === selected));
  const groups = $derived([...new Set(more.map((p) => p.group))].map((name) => [name, more.filter((p) => p.group === name)]));
  const fold = (text) => text.toLocaleLowerCase('tr');
  const found = $derived(query.trim()
    ? presets.filter((p) => fold(`${p.label} ${p.note}`).includes(fold(query.trim()))) : null);

  function toggle() {
    if (open) query = '';
    savePref({ art_presets_open: !open });
  }
</script>

{#snippet chip(entry)}
  <button class="chip" class:on={selected === entry.id} title={entry.note} onclick={() => onpick(entry)}>{entry.label}</button>
{/snippet}

<div class="row">
  <span class="dim lead">Hazır tarz</span>
  {#each top as entry (entry.id)}{@render chip(entry)}{/each}
  {#if !open && picked}{@render chip(picked)}{/if}
  {#if more.length}
    <button class="chip more" aria-expanded={open} onclick={toggle}>
      {open ? 'Daha az' : `Daha fazla (${more.length})`}<Icon name={open ? 'up' : 'down'} size={14} />
    </button>
  {/if}
</div>
{#if open}
  <div class="more-list">
    <input class="field filter" type="search" placeholder="Tarz ara: mürekkep, gotik, fotoğraf…" bind:value={query} />
    {#if found}
      <div class="row">
        {#each found as entry (entry.id)}{@render chip(entry)}{/each}
        {#if !found.length}<span class="dim">Eşleşen tarz yok.</span>{/if}
      </div>
    {:else}
      {#each groups as [name, entries] (name)}
        <div class="row">
          <span class="dim lead group">{name}</span>
          {#each entries as entry (entry.id)}{@render chip(entry)}{/each}
        </div>
      {/each}
    {/if}
  </div>
{/if}

<style>
  .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; }
  .row .lead { min-width: 78px; }
  .chip.more { display: inline-flex; align-items: center; gap: 4px; color: var(--secondary); }
  .more-list { display: flex; flex-direction: column; gap: 8px; padding-left: 86px; }
  .more-list .lead.group { flex-basis: 100%; font-size: 12px; margin-top: 2px; }
  .filter { max-width: 320px; }
</style>
