<script>
  // Ekstrelerden tara (F110): hangi koleksiyonlarin belgeleri okunacak; okunan ekstrelerin durumu.
  import Icon from '../lib/Icon.svelte';
  import Modal from './Modal.svelte';
  import Toggle from './Toggle.svelte';
  import { shortDate } from '../lib/subscriptions.js';

  let { scan, onstart, onclose, onauto } = $props();

  let selected = $state([...(scan?.sources ?? [])]);
  let force = $state(false);
  const STATUS = {
    ok: { label: 'Toplam tuttu', tone: 'ok' },
    unchecked: { label: 'Toplam bulunamadı', tone: '' },
    mismatch: { label: 'Toplam tutmadı', tone: 'warning' },
  };

  function toggle(slug) {
    selected = selected.includes(slug) ? selected.filter((s) => s !== slug) : [...selected, slug];
  }
</script>

<Modal title="Ekstrelerden tara" width={560} {onclose}>
  <p class="dim intro">Seçilen koleksiyonlardaki banka hesap özetleri ve kredi kartı ekstreleri Ayarlar'daki analiz modeliyle okunur. Ödemeler, arama metni uyan kayıtlara bağlanır; hiçbir kayda uymayan faturalar ve düzenli ödemeler öneri olarak listelenir. Okunan ekstreler saklanır, aynı dosya bir daha okunmaz.</p>

  <div class="label">Koleksiyonlar</div>
  <div class="list">
    {#each scan?.collections ?? [] as c (c.slug)}
      <label class="row"><input type="checkbox" checked={selected.includes(c.slug)} onchange={() => toggle(c.slug)} /><span class="ellipsis">{c.title}</span></label>
    {:else}
      <p class="dim">Henüz koleksiyon yok. Ekstrelerin bulunduğu klasörü Kütüphane'de koleksiyon olarak ekleyin.</p>
    {/each}
  </div>
  <div class="toggle-row"><Toggle bind:checked={force} label="Okunmuş ekstreleri yeniden oku" />
    <span class="dim">Model değiştiyse ya da bir ekstrenin toplamı tutmadıysa.</span></div>
  <div class="toggle-row"><Toggle checked={scan?.auto ?? true} onchange={(on) => onauto?.(on)} label="Yeni ekstreleri kendiliğinden tara" />
    <span class="dim">E-postadan ya da izlenen klasörden yeni dosya gelince seçili koleksiyonlar arka planda taranır; zam ve yüksek fatura uyarı verir.</span></div>

  {#if scan?.statements?.length}
    <div class="label">Okunan ekstreler{#if scan.date}<span class="dim"> · son tarama {shortDate(scan.date.slice(0, 10))} {scan.date.slice(11, 16)}</span>{/if}</div>
    <div class="list statements">
      {#each scan.statements as s (s.path)}
        <div class="row" title={s.problem || s.path}>
          <Icon name={s.account === 'credit_card' ? 'creditCard' : 'landmark'} size={15} />
          <span class="ellipsis">{s.name}</span>
          <small class="dim">{s.count} işlem</small>
          <span class="badge {STATUS[s.status]?.tone ?? ''}">{STATUS[s.status]?.label ?? s.status}</span>
        </div>
      {/each}
    </div>
  {/if}

  {#snippet footer()}
    <button class="btn" onclick={onclose}>Vazgeç</button>
    <button class="btn primary" disabled={!selected.length} onclick={() => onstart(selected, force)}><Icon name="fileSearch" size={16} />Taramayı başlat</button>
  {/snippet}
</Modal>

<style>
  .intro { font-size: 12.5px; line-height: 1.55; margin: 0 0 14px; }
  .label { font-size: 12px; font-weight: 700; color: var(--secondary); margin: 12px 0 6px; }
  .list { display: flex; flex-direction: column; max-height: 220px; overflow: auto; border: 1px solid var(--outline); border-radius: 10px; }
  .row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; font-size: 13px; min-width: 0; }
  .row + .row { border-top: 1px solid var(--outline); }
  label.row { cursor: pointer; }
  label.row:hover { background: var(--surface-hover); }
  .row .ellipsis { flex: 1; min-width: 0; }
  .row small { white-space: nowrap; font-size: 11.5px; }
  .statements :global(svg) { color: var(--secondary); flex: none; }
  .list > p { padding: 10px 12px; margin: 0; font-size: 12.5px; }
  .toggle-row { display: flex; align-items: center; gap: 14px; font-size: 12px; margin-top: 12px; }
  .toggle-row > :global(:first-child) { flex: none; white-space: nowrap; }
</style>
