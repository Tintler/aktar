<script>
  // Ceviri onayi: on analiz / ceviri sonu terim ve sureklilik onerileri (eski GlossaryReviewDialog).
  // data: bridge_translate.review_payload; onsubmit(null) = Atla.
  import Modal from './Modal.svelte';

  let { data, onsubmit } = $props();
  // Pencere ilk verinin kendi kopyasini duzenler.
  // svelte-ignore state_referenced_locally
  const defaultScope = data.has_series ? 'series' : 'chapter';
  // svelte-ignore state_referenced_locally
  let terms = $state(data.terms.map((t) => ({ ...t, checked: true, scope: defaultScope })));
  // svelte-ignore state_referenced_locally
  let decisions = $state(data.decisions.map((d) => ({ ...d, checked: true, scope: defaultScope })));
  let tab = $state('terms');

  function accept() {
    const pick = (rows) => rows.filter((r) => r.checked).map(({ checked, ...rest }) => rest);
    onsubmit({ terms: pick(terms), decisions: pick(decisions) });
  }

  const typeLabel = (type) => ({ term: 'terim', name: 'ad', place: 'yer', title: 'unvan', continuity: 'süreklilik' }[type] ?? type);
</script>

<Modal title={data.title} width={980}>
  <p class="hint">
    {#if data.existing}{data.existing} mevcut seri terimi korunacak. {/if}Kullanılacak önerileri işaretleyin, Türkçe
    karşılıkları düzeltin ve kapsamlarını seçin. Atlarsanız çeviri önerisiz devam eder.
  </p>
  <div class="tabs">
    <button class="chip" class:on={tab === 'terms'} onclick={() => (tab = 'terms')}>Terimler · {terms.length}</button>
    <button class="chip" class:on={tab === 'decisions'} onclick={() => (tab = 'decisions')}>Süreklilik · {decisions.length}</button>
  </div>
  <div class="wrap">
    {#if tab === 'terms'}
      <table class="table">
        <thead><tr><th></th><th>Kaynak</th><th>Türkçe önerisi</th><th>Tür</th><th>Gerekçe</th><th>Kullanım</th><th>Kapsam</th></tr></thead>
        <tbody>
          {#each terms as row}
            <tr class:off={!row.checked}>
              <td class="c"><input type="checkbox" bind:checked={row.checked} /></td>
              <td class="src selectable">{row.source}</td>
              <td><input class="field cell" bind:value={row.target} /></td>
              <td><span class="badge">{typeLabel(row.type ?? 'term')}</span></td>
              <td class="reason">{row.reason ?? ''}</td>
              <td class="dim">×{row.count ?? 1}</td>
              <td>
                <select class="field cell scope" bind:value={row.scope}>
                  {#if data.has_series}<option value="series">Seriye ekle</option>{/if}
                  <option value="chapter">Yalnız bu bölüm</option>
                </select>
              </td>
            </tr>
          {:else}
            <tr><td colspan="7" class="empty">Yeni terim önerisi yok.</td></tr>
          {/each}
        </tbody>
      </table>
    {:else}
      <table class="table">
        <thead><tr><th></th><th>Karar</th><th>Tür</th><th>Gerekçe</th><th>Kapsam</th></tr></thead>
        <tbody>
          {#each decisions as row}
            <tr class:off={!row.checked}>
              <td class="c"><input type="checkbox" bind:checked={row.checked} /></td>
              <td><input class="field cell" bind:value={row.value} /></td>
              <td><span class="badge">{typeLabel(row.type ?? 'continuity')}</span></td>
              <td class="reason">{row.reason ?? ''}</td>
              <td>
                <select class="field cell scope" bind:value={row.scope}>
                  {#if data.has_series}<option value="series">Seriye ekle</option>{/if}
                  <option value="chapter">Yalnız bu bölüm</option>
                </select>
              </td>
            </tr>
          {:else}
            <tr><td colspan="5" class="empty">Süreklilik önerisi yok.</td></tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
  {#snippet footer()}
    <button class="btn" onclick={() => onsubmit(null)}>Atla</button>
    <button class="btn primary" onclick={accept}>Seçilenleri uygula</button>
  {/snippet}
</Modal>

<style>
  .hint { color: var(--secondary); font-size: 13px; line-height: 1.55; }
  .tabs { display: flex; gap: 8px; }
  .wrap { max-height: 56vh; overflow: auto; border: 1px solid var(--outline); border-radius: 10px; padding: 0 4px 4px; }
  .table td { padding: 4px 8px; vertical-align: middle; }
  .c { width: 40px; text-align: center; }
  .src { font-weight: 600; }
  .cell { width: 100%; height: 32px; background: transparent; }
  .cell:hover { background: var(--surface); }
  .scope { width: 140px; }
  .reason { color: var(--secondary); font-size: 12px; max-width: 280px; }
  tr.off td { opacity: .45; }
  tr.off td.c { opacity: 1; }
</style>
