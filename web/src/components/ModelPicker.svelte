<script>
  // F237: aranabilir model secici. OpenRouter gibi yuzlerce model donduren sunucularda <select> listesinde
  // aranan model bulunamiyordu. Yazilan kelimelerin hepsi (sirasiz) gecen modeller kalir ("gpt 6 luna" ->
  // openai/gpt-6-luna); listede olmayan ad da "Kullan" ile secilebilir (sunucu listelemese de calisan modeller).
  import { tick } from 'svelte';
  import Icon from '../lib/Icon.svelte';

  let { value = $bindable(''), options = [], empty = null, disabled = false, placeholder = 'Model ara…' } = $props();

  let open = $state(false);
  let query = $state('');
  let active = $state(0);
  let trigger = $state(null);
  let input = $state(null);
  let list = $state(null);
  let place = $state({ left: 0, top: 0, width: 300, up: false });

  const LIMIT = 300;   // cok uzun listede yalnizca ilk eslesmeler cizilir; arama hepsine bakar
  const terms = $derived(query.toLowerCase().split(/\s+/).filter(Boolean));
  const matches = $derived(options.filter((name) => { const text = name.toLowerCase(); return terms.every((t) => text.includes(t)); }));
  const typed = $derived(query.trim());
  // Elle ad: hicbir model eslesmezse ya da tam kimlik yazilmissa (saglayici/model); "qwen" gibi parcada gosterilmez.
  const custom = $derived(typed && !options.includes(typed) && !/\s/.test(typed)
    && (!matches.length || typed.includes('/')) ? typed : '');
  // Secilebilir satirlar: bos secenek (arama yokken), eslesen modeller, elle yazilan ad.
  const rows = $derived([
    ...(empty !== null && !terms.length ? [{ value: '', label: empty }] : []),
    ...matches.slice(0, LIMIT).map((name) => ({ value: name, label: name })),
    ...(custom ? [{ value: custom, label: custom, custom: true }] : []),
  ]);

  async function show() {
    if (disabled) return;
    const rect = trigger.getBoundingClientRect();
    const below = window.innerHeight - rect.bottom;
    const up = below < 320 && rect.top > below;
    place = { left: rect.left, width: Math.max(rect.width, 340), up,
      top: up ? window.innerHeight - rect.top + 4 : rect.bottom + 4 };
    query = '';
    open = true;
    await tick();
    active = Math.max(0, rows.findIndex((row) => row.value === value));
    input?.focus();
    list?.querySelector('.on')?.scrollIntoView({ block: 'center' });
  }
  function choose(row) {
    value = row.value;
    open = false;
    trigger?.focus();
  }
  function key(event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = Math.min(rows.length - 1, Math.max(0, active + (event.key === 'ArrowDown' ? 1 : -1)));
      tick().then(() => list?.querySelector('.on')?.scrollIntoView({ block: 'nearest' }));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (rows[active]) choose(rows[active]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      open = false;
      trigger?.focus();
    }
  }
  function outside(event) {
    if (open && !event.target.closest('.model-pop') && !trigger?.contains(event.target)) open = false;
  }
  const label = $derived(value === '' && empty !== null ? empty : value);
</script>

<svelte:window onmousedown={outside} onresize={() => (open = false)} />

<button bind:this={trigger} type="button" class="field picker" class:open {disabled} title={value || null}
  aria-haspopup="listbox" aria-expanded={open} onclick={() => (open ? (open = false) : show())}
  onkeydown={(e) => { if (!open && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); show(); } }}>
  <span class="val" class:dim={value === ''}>{label}</span>
  <Icon name="down" size={14} />
</button>

{#if open}
  <div class="model-pop" style:left="{place.left}px" style:width="{place.width}px"
    style:top={place.up ? null : `${place.top}px`} style:bottom={place.up ? `${place.top}px` : null}>
    <div class="search">
      <Icon name="search" size={14} />
      <input bind:this={input} bind:value={query} {placeholder} spellcheck="false" autocomplete="off"
        oninput={() => (active = 0)} onkeydown={key} aria-label="Model ara" />
      <small>{matches.length}/{options.length}</small>
    </div>
    <div class="rows" role="listbox" bind:this={list}>
      {#each rows as row, index (row.custom ? '\u0000' + row.value : row.value)}
        <button type="button" class="row" class:on={index === active} class:sel={row.value === value} role="option"
          aria-selected={row.value === value} onmousemove={() => (active = index)} onclick={() => choose(row)}>
          {#if row.custom}<Icon name="plus" size={13} /><span>Kullan: <b>{row.label}</b></span>
          {:else}<span class:dim={row.value === ''}>{row.label}</span>{#if row.value === value}<Icon name="check" size={13} />{/if}{/if}
        </button>
      {:else}
        <div class="none">Eşleşen model yok.</div>
      {/each}
      {#if matches.length > LIMIT}<div class="none">İlk {LIMIT} sonuç gösteriliyor; aramayı daraltın.</div>{/if}
    </div>
  </div>
{/if}

<style>
  .picker { width: 100%; display: flex; align-items: center; gap: 8px; text-align: left; cursor: pointer; padding-right: 10px; }
  .picker.open { border-color: var(--accent); }
  .val { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dim { color: var(--dim); }
  .model-pop { position: fixed; z-index: 60; max-width: calc(100vw - 24px); display: flex; flex-direction: column;
    background: var(--overlay); border: 1px solid var(--outline); border-radius: 12px; box-shadow: 0 8px 28px var(--shadow); overflow: hidden; }
  .search { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--outline); color: var(--dim); }
  .search input { flex: 1; min-width: 0; background: none; border: none; outline: none; color: var(--text); font: inherit; font-size: 13px; }
  .search small { font-size: 11px; white-space: nowrap; }
  .rows { max-height: 300px; overflow: auto; padding: 4px; }
  .row { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 10px; border-radius: 8px; border: none; background: none;
    color: var(--text); font: inherit; font-size: 13px; text-align: left; cursor: pointer; }
  .row span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row.on { background: var(--surface-hover); }
  .row.sel { color: var(--accent); }
  .none { padding: 8px 10px; color: var(--dim); font-size: 12px; }
</style>
