<script>
  // Kaynak -> karsilik tablosu (bolum ve seri sozlugu icin ortak). onsave(rows) / onclose().
  import Modal from './Modal.svelte';
  import Icon from '../lib/Icon.svelte';

  let { title, items = [], onsave, onclose } = $props();
  // svelte-ignore state_referenced_locally
  let rows = $state([...items.map((r) => ({ source: r.source, target: r.target })), { source: '', target: '' }]);

  // Son satira yazilinca altina yeni bos satir eklenir.
  $effect(() => {
    const last = rows[rows.length - 1];
    if (last.source || last.target) rows.push({ source: '', target: '' });
  });

  const filled = $derived(rows.filter((r) => r.source.trim() && r.target.trim()).length);
  const incomplete = $derived(rows.some((r) => !!r.source.trim() !== !!r.target.trim()));
</script>

<Modal {title} width={680} {onclose}>
  <div class="wrap">
    <table class="table">
      <thead><tr><th>Kaynak terim</th><th>Karşılık</th><th></th></tr></thead>
      <tbody>
        {#each rows as row, i}
          <tr>
            <td><input class="field cell" bind:value={row.source} placeholder={i === rows.length - 1 ? 'Yeni terim…' : ''} /></td>
            <td><input class="field cell" bind:value={row.target} /></td>
            <td class="x">
              {#if i < rows.length - 1}
                <button class="icon-btn sm" title="Satırı sil" onclick={() => rows.splice(i, 1)}><Icon name="trash" size={14} /></button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  {#snippet footer()}
    <span class="count">{incomplete ? 'Yarım satırlar kaydedilmez.' : filled + ' terim'}</span>
    <button class="btn" onclick={onclose}>İptal</button>
    <button class="btn primary" onclick={() => onsave(rows.filter((r) => r.source.trim() && r.target.trim()))}>Kaydet</button>
  {/snippet}
</Modal>

<style>
  .wrap { max-height: 56vh; overflow: auto; border: 1px solid var(--outline); border-radius: 10px; padding: 0 4px 4px; }
  .table td { padding: 3px 6px; }
  .cell { width: 100%; height: 32px; background: transparent; }
  .cell:hover { background: var(--surface); }
  .x { width: 40px; }
  .count { margin-right: auto; color: var(--dim); font-size: 12px; }
</style>
