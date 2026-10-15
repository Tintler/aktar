<script>
  // Sohbetlerde dusunme (reasoning) dugmesi (F99): secim tum sohbetlerde ortaktir ve hatirlanir.
  // Ayarlar'daki "Thinking kapat" yalnizca analiz/ceviri/ozet gibi arka plan islerine uygulanir.
  import Icon from '../lib/Icon.svelte';
  import { app, setThink } from '../lib/state.svelte.js';

  let { label = false } = $props();
</script>

<button type="button" class="think" class:on={app.think} class:label aria-pressed={app.think}
  title={app.think ? 'Düşünme açık: model cevaplamadan önce düşünür (daha yavaş). Kapatmak için tıklayın.' : 'Düşünme kapalı: model hemen cevaplar. Açmak için tıklayın.'}
  onclick={() => setThink(!app.think)}>
  <Icon name="brain" size={16} />{#if label}<span>Düşün</span>{/if}
</button>

<style>
  .think { flex: none; height: 30px; min-width: 30px; padding: 0 7px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    color: var(--dim); font-size: 12.5px; font-weight: 600; text-transform: none; letter-spacing: 0; border: 1px solid transparent; transition: color .15s, background .15s, border-color .15s; }
  .think:hover { color: var(--text); background: var(--surface-active); }
  .think.label { padding: 0 11px 0 9px; border-color: var(--outline); }
  .think.on { color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); border-color: color-mix(in srgb, var(--accent) 40%, transparent); }
</style>
