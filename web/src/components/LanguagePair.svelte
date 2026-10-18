<script>
  // Ceviri dil cifti secici (F151): kaynak (Otomatik dahil) -> hedef. Degisiklik config.json'a yazilir.
  import Icon from '../lib/Icon.svelte';
  import { act } from '../lib/state.svelte.js';

  let { value, disabled = false, onchange } = $props();   // value: {source, target, choices}

  async function change(source, target) {
    if (source === target) return;
    const result = await act('set_translation_languages', source, target);
    if (result) onchange?.(result);
  }
</script>

{#if value}
  <div class="pair" title="Çeviri dili: altyazılar ve yeni kitap projeleri için">
    <select class="field" value={value.source} {disabled} aria-label="Kaynak dil"
      onchange={(e) => change(e.currentTarget.value, value.target)}>
      <option value="auto">Otomatik</option>
      {#each value.choices as c}<option value={c.code} disabled={c.code === value.target}>{c.label}</option>{/each}
    </select>
    <Icon name="arrowRight" size={14} />
    <select class="field" value={value.target} {disabled} aria-label="Hedef dil"
      onchange={(e) => change(value.source, e.currentTarget.value)}>
      {#each value.choices as c}<option value={c.code} disabled={c.code === value.source}>{c.label}</option>{/each}
    </select>
  </div>
{/if}

<style>
  .pair { display: flex; align-items: center; gap: 6px; color: var(--dim); }
  .pair select { width: 128px; border-radius: 999px; color: var(--text); }
</style>
