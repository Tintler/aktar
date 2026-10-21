<script>
  // F179: acilir/kapanir ayar bolumunun basligi (Ayarlar > Ses). Arama surerken bolumler hep acik gorunur;
  // `open` cagiran tarafta isOpen(key) || searching ile hesaplanir. `children`: basligin sagindaki dugmeler.
  import Icon from '../lib/Icon.svelte';
  import { toggleOpen } from '../lib/folds.js';

  let { key, title, open, fallback = true, level = 2, note = '', children } = $props();
</script>

<div class="head fold">
  <button class="toggle" aria-expanded={open} onclick={() => toggleOpen(key, fallback)}>
    <span class="chev" class:open><Icon name="forward" size={16} /></span>
    {#if level === 2}<h2>{title}</h2>{:else}<b>{title}</b>{/if}
    {#if note}<span class="note">{note}</span>{/if}
  </button>
  {#if children && open}{@render children()}{/if}
</div>

<style>
  .fold { display: flex; align-items: center; gap: 10px; justify-content: space-between; }
  .toggle { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; text-align: left; padding: 4px 0; color: inherit; }
  .toggle h2 { font-size: 20px; font-weight: 700; letter-spacing: -.01em; }
  .toggle b { font-size: 14px; font-weight: 600; }
  .note { font-size: 12px; color: var(--dim); font-weight: 400; }
  .chev { display: inline-flex; color: var(--secondary); transition: transform .15s; }
  .chev.open { transform: rotate(90deg); }
</style>
