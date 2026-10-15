<script>
  // Harcamalar > Sayilmayan (F114): harcama sayilmayan giden satirlar; nedene gore suzulur, aranir.
  import Icon from '../lib/Icon.svelte';
  import Modal from './Modal.svelte';
  import { money, shortDate } from '../lib/subscriptions.js';

  let { excluded, period = '', onclose } = $props();

  let reason = $state('');
  let query = $state('');
  let sort = $state('date');   // 'date' | 'amount'

  const rows = $derived.by(() => {
    const needle = query.trim().toLocaleLowerCase('tr');
    const list = excluded.rows.filter((r) => (!reason || r.reason === reason)
      && (!needle || [r.description, r.merchant, r.file].join(' ').toLocaleLowerCase('tr').includes(needle)));
    return sort === 'amount' ? [...list].sort((a, b) => b.amount - a.amount) : list;
  });
  const shown = $derived(rows.reduce((sum, r) => sum + r.amount, 0));
  const label = (key) => excluded.groups.find((g) => g.key === key)?.label ?? key;
</script>

<Modal title="Harcama sayılmayan çıkışlar" width={860} {onclose}>
  <p class="dim intro">Bu satırlar hesaptan ya da karttan çıkan ama harcama sayılmayan paralardır: kredi kartı borcu ödemeleri ve kendi hesaplarınız arasındaki transferler. Kart ekstresindeki alışverişler zaten harcama sayıldığı için, karta yapılan ödeme ikinci kez sayılmaz. Para hesaplar arasında gidip geldikçe her hareket ayrıca listelenir; bu yüzden toplam, gerçekten harcanan paradan çok büyük görünebilir.{#if period} Dönem: <b>{period}</b>.{/if}</p>

  <div class="chips">
    <button class="chip" class:on={!reason} onclick={() => (reason = '')}>Tümü <span class="n">{excluded.count} · {money(excluded.total)}</span></button>
    {#each excluded.groups as g (g.key)}
      <button class="chip" class:on={reason === g.key} onclick={() => (reason = reason === g.key ? '' : g.key)}>{g.label} <span class="n">{g.count} · {money(g.total)}</span></button>
    {/each}
  </div>
  <div class="tools">
    <label class="search"><Icon name="search" size={15} /><input bind:value={query} placeholder="Açıklama, firma, dosya…" /></label>
    <span class="grow"></span>
    <span class="dim small">{rows.length} satır · {money(shown)}</span>
    <select class="field sm" bind:value={sort}><option value="date">Tarihe göre</option><option value="amount">Tutara göre</option></select>
  </div>

  <div class="list">
    <table class="table">
      <thead><tr><th>Tarih</th><th>Açıklama</th><th>Neden</th><th>Kaynak</th><th class="num">Tutar</th></tr></thead>
      <tbody>
        {#each rows as r, i (r.date + r.amount + r.description + i)}
          <tr>
            <td class="nowrap">{shortDate(r.date)}</td>
            <td><span class="desc" title={r.description}>{r.description || r.merchant}</span></td>
            <td class="nowrap dim">{label(r.reason)}</td>
            <td><span class="src" title={r.file}><Icon name={r.account === 'credit_card' ? 'creditCard' : 'landmark'} size={14} /><span class="ellipsis">{r.file}</span></span></td>
            <td class="num">{money(r.amount)}</td>
          </tr>
        {:else}
          <tr><td colspan="5"><p class="empty">Eşleşen satır yok.</p></td></tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#snippet footer()}
    <button class="btn" onclick={onclose}>Kapat</button>
  {/snippet}
</Modal>

<style>
  .intro { font-size: 12.5px; line-height: 1.55; margin: 0 0 12px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .chip .n { margin-left: 6px; opacity: .65; font-size: 12px; font-variant-numeric: tabular-nums; }
  .tools { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .grow { flex: 1; }
  .small { font-size: 12px; font-variant-numeric: tabular-nums; }
  .search { width: 240px; height: 32px; display: flex; align-items: center; gap: 8px; padding: 0 12px; border-radius: 999px;
    background: var(--surface); color: var(--secondary); border: 1px solid var(--field-border); }
  .search:focus-within { border-color: var(--accent); box-shadow: var(--focus-ring); }
  .search input { flex: 1; min-width: 0; background: none; border: 0; outline: none; font-size: 13px; color: var(--text); }
  .field.sm { height: 32px; font-size: 12.5px; }
  .list { max-height: 52vh; overflow: auto; border: 1px solid var(--outline); border-radius: 10px; }
  .table td { vertical-align: middle; font-size: 12.5px; }
  .nowrap { white-space: nowrap; }
  .desc { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; max-width: 360px; }
  .src { display: flex; align-items: center; gap: 6px; max-width: 200px; color: var(--secondary); }
  .src :global(svg) { flex: none; }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
