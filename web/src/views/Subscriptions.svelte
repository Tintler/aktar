<script>
  // Abonelikler (F106): tekrarlayan ve tek seferlik odemeler; tutar, banka/kart, durum, yenileme.
  import Icon from '../lib/Icon.svelte';
  import SubscriptionModal from '../components/SubscriptionModal.svelte';
  import { act, toast } from '../lib/state.svelte.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import { CYCLES, STATUSES, METHODS, money, shortDate, daysText } from '../lib/subscriptions.js';

  let data = $state(null);
  let query = $state('');
  let status = $state('');
  let kind = $state('');
  let sort = $state('due');
  let editing = $state(null);   // null: kapali, {}: yeni kayit, kayit: duzenleme

  async function load() {
    const result = await act('subs_state');
    if (result) data = result;
  }
  load();

  const items = $derived(data?.items ?? []);
  const summary = $derived(data?.summary);
  const banks = $derived([...new Set(items.map((item) => item.bank).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'tr')));
  const counts = $derived(Object.fromEntries(Object.keys(STATUSES).map((key) => [key, items.filter((item) => item.status === key).length])));

  const rows = $derived.by(() => {
    const needle = query.trim().toLocaleLowerCase('tr');
    const list = items.filter((item) => (!status || item.status === status) && (!kind || item.kind === kind)
      && (!needle || [item.name, item.category, item.bank, item.card, item.notes].join(' ').toLocaleLowerCase('tr').includes(needle)));
    if (sort === 'amount') list.sort((a, b) => (b.monthly || b.amount) - (a.monthly || a.amount));
    else if (sort === 'name') list.sort((a, b) => a.name.localeCompare(b.name, 'tr'));
    return list;
  });

  const totals = (map) => Object.entries(map ?? {});

  async function save(item) {
    const result = await act('subs_save', item);
    if (!result) return;
    data = result;
    editing = null;
    toast(`"${item.name.trim()}" kaydedildi.`, 'ok');
  }

  async function remove(item) {
    editing = null;  // onay penceresi duzenleme penceresinin altinda kalmasin
    const ok = await confirm({ title: 'Kaydı sil', message: `"${item.name}" silinsin mi? Bu işlem geri alınamaz.`, ok: 'Sil', danger: true });
    if (!ok) return;
    const result = await act('subs_delete', item.id);
    if (result) data = result;
  }

  function payment(item) {
    const parts = [item.bank, item.card].filter(Boolean);
    return parts.join(' · ');
  }
</script>

<section class="page">
  <div class="page-head">
    <h1>Abonelikler</h1>
    <button class="btn primary" onclick={() => (editing = {})}><Icon name="plus" size={16} />Yeni kayıt</button>
  </div>
  <div class="page-body">
    {#if summary}
      <div class="stats">
        <div class="stat card">
          <span class="label">Aylık toplam</span>
          {#each totals(summary.monthly) as [currency, value]}<b>{money(value, currency)}</b>{:else}<b class="dim">—</b>{/each}
          <span class="dim">aktif tekrarlayan ödemeler</span>
        </div>
        <div class="stat card">
          <span class="label">Yıllık toplam</span>
          {#each totals(summary.yearly) as [currency, value]}<b>{money(value, currency)}</b>{:else}<b class="dim">—</b>{/each}
          <span class="dim">aylık toplamın 12 katı</span>
        </div>
        <div class="stat card">
          <span class="label">Önümüzdeki {summary.upcoming_days} gün</span>
          {#each totals(summary.upcoming) as [currency, value]}<b>{money(value, currency)}</b>{:else}<b class="dim">—</b>{/each}
          <span class="dim">{items.filter((item) => item.days_left !== null && item.days_left <= summary.upcoming_days).length} ödeme bekleniyor</span>
        </div>
        <div class="stat card">
          <span class="label">Aktif kayıt</span>
          <b>{summary.active}</b>
          <span class="dim">{items.length} kayıttan</span>
        </div>
      </div>
    {/if}

    <div class="layout">
      <div class="main">
        <div class="filters">
          <label class="search">
            <Icon name="search" size={16} />
            <input bind:value={query} placeholder="Ad, kategori, banka…" />
            {#if query}<button class="icon-btn sm" title="Temizle" onclick={() => (query = '')}><Icon name="x" size={14} /></button>{/if}
          </label>
          <button class="chip" class:on={!status} onclick={() => (status = '')}>Tümü</button>
          {#each Object.entries(STATUSES) as [key, s]}
            {#if counts[key]}<button class="chip" class:on={status === key} onclick={() => (status = status === key ? '' : key)}>{s.label} <span class="n">{counts[key]}</span></button>{/if}
          {/each}
          <span class="grow"></span>
          <select class="field sm" bind:value={kind} title="Tür">
            <option value="">Tüm türler</option><option value="recurring">Tekrarlayan</option><option value="once">Tek seferlik</option>
          </select>
          <select class="field sm" bind:value={sort} title="Sırala">
            <option value="due">Sonraki ödeme</option><option value="amount">Tutar (aylık)</option><option value="name">Ad</option>
          </select>
        </div>

        {#if !data}
          <p class="empty">Yükleniyor…</p>
        {:else if !items.length}
          <div class="blank card">
            <Icon name="creditCard" size={34} />
            <b>Henüz kayıt yok</b>
            <span>Netflix, Amazon Prime, elektrik faturası gibi düzenli ödemelerinizi ya da tek seferlik ödemeleri ekleyin; aylık toplamı, yaklaşan yenilemeleri ve hangi karttan ödendiğini burada görün.</span>
            <button class="btn primary" onclick={() => (editing = {})}><Icon name="plus" size={16} />İlk kaydı ekle</button>
          </div>
        {:else}
          <div class="card list">
            <table class="table">
              <thead><tr><th>Ad</th><th class="num">Tutar</th><th>Ödeme</th><th>Durum</th><th>Sonraki ödeme</th><th></th></tr></thead>
              <tbody>
                {#each rows as item (item.id)}
                  <tr class:off={item.status === 'cancelled' || item.status === 'paused'} onclick={() => (editing = item)}>
                    <td>
                      <div class="name"><span class="mark">{item.name.slice(0, 1).toLocaleUpperCase('tr')}</span>
                        <div class="ellipsis"><b>{item.name}</b><small class="dim">{[item.category, item.kind === 'once' ? 'Tek seferlik' : CYCLES[item.cycle]].filter(Boolean).join(' · ')}</small></div></div>
                    </td>
                    <td class="num">
                      <b>{money(item.amount, item.currency)}</b>
                      {#if item.kind === 'recurring' && item.cycle !== 'monthly' && item.monthly}<small class="dim">aylık {money(item.monthly, item.currency)}</small>{/if}
                    </td>
                    <td>
                      <div class="pay"><Icon name={METHODS[item.method].icon} size={16} />
                        <div class="ellipsis"><span>{METHODS[item.method].label}{#if item.card_last4}<span class="mono dim last4">•••• {item.card_last4}</span>{/if}</span>
                          {#if payment(item)}<small class="dim">{payment(item)}</small>{/if}</div></div>
                    </td>
                    <td><span class="badge {STATUSES[item.status].tone}">{STATUSES[item.status].label}</span>
                      {#if item.kind === 'recurring' && !item.auto_renew && item.status !== 'cancelled'}<small class="dim">elle yenileniyor</small>{/if}</td>
                    <td>
                      {#if item.next_due}
                        <span>{shortDate(item.next_due)}</span>
                        <small class:soon={item.days_left <= 3} class="dim">{daysText(item.days_left)}</small>
                      {:else if item.status === 'cancelled' && item.end_date}
                        <small class="dim">{shortDate(item.end_date)} tarihinde bitti</small>
                      {:else}
                        <small class="dim">—</small>
                      {/if}
                    </td>
                    <td class="act"><button class="icon-btn sm" title="Düzenle" onclick={(e) => { e.stopPropagation(); editing = item; }}><Icon name="pencil" size={15} /></button></td>
                  </tr>
                {:else}
                  <tr class="none"><td colspan="6"><p class="empty">Filtreyle eşleşen kayıt yok.</p></td></tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>

      {#if summary?.by_payment.length}
        <aside class="card side">
          <div class="side-title"><Icon name="wallet" size={16} />Ödeme araçlarına göre</div>
          <span class="dim hint">Aktif tekrarlayan ödemelerin aylık yükü</span>
          {#each summary.by_payment as group}
            <div class="group">
              <Icon name={METHODS[group.method].icon} size={16} />
              <div class="ellipsis"><b>{group.bank}</b><small class="dim">{METHODS[group.method].label} · {group.count} kayıt</small></div>
              <b class="amt">{money(group.monthly, group.currency)}</b>
            </div>
          {/each}
        </aside>
      {/if}
    </div>
  </div>
</section>

{#if editing}
  <SubscriptionModal item={editing.id ? editing : null} categories={data?.categories ?? []} {banks}
    onsave={save} ondelete={remove} onclose={() => (editing = null)} />
{/if}

<style>
  .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 20px; }
  .stat { display: flex; flex-direction: column; gap: 4px; padding: 16px 18px; }
  .stat b { font-size: 22px; font-weight: 700; letter-spacing: -.01em; font-variant-numeric: tabular-nums; }
  .stat .label { margin-bottom: 4px; }
  .stat .dim { font-size: 12px; }
  @media (max-width: 1100px) { .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

  .layout { display: flex; gap: 16px; align-items: flex-start; }
  .main { flex: 1; min-width: 0; }
  .filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
  .grow { flex: 1; }
  .search { width: 220px; height: 34px; display: flex; align-items: center; gap: 8px; padding: 0 4px 0 12px; border-radius: 999px;
    background: var(--surface); color: var(--secondary); border: 1px solid var(--field-border); transition: border-color .15s, box-shadow .15s; }
  .search:focus-within { border-color: var(--accent); box-shadow: var(--focus-ring); }
  .search input { flex: 1; min-width: 0; height: 100%; background: none; border: 0; outline: none; font-size: 13px; color: var(--text); }
  .search input::placeholder { color: var(--dim); }
  .chip .n { margin-left: 4px; opacity: .6; font-size: 12px; }
  .field.sm { height: 32px; font-size: 12.5px; }

  .list { padding: 6px; overflow: auto; }
  .table td { vertical-align: middle; }
  .table tbody tr { cursor: pointer; }
  .table tbody tr.none { cursor: default; }
  .table tbody tr.none:hover td { background: none; }
  .table small { display: block; font-size: 11.5px; margin-top: 2px; }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  tr.off td:not(.act) { opacity: .55; }
  .name { display: flex; align-items: center; gap: 12px; min-width: 0; max-width: 300px; }
  .mark { width: 34px; height: 34px; border-radius: 10px; flex: none; display: grid; place-items: center; font-weight: 700; font-size: 15px;
    background: color-mix(in srgb, var(--accent) 16%, var(--surface)); color: var(--accent); }
  .pay { display: flex; align-items: center; gap: 10px; color: var(--secondary); min-width: 0; max-width: 260px; }
  .pay span { color: var(--text); }
  .pay .last4 { color: var(--dim); margin-left: 6px; font-size: 12px; }
  .soon { color: var(--warning) !important; font-weight: 600; }
  .act { width: 40px; }
  .act .icon-btn { opacity: 0; }
  tr:hover .act .icon-btn, .act .icon-btn:focus-visible { opacity: 1; }

  .blank { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 48px 32px; text-align: center; color: var(--secondary); }
  .blank :global(svg) { color: var(--accent); }
  .blank b { color: var(--text); font-size: 16px; }
  .blank span { max-width: 520px; font-size: 13px; line-height: 1.55; margin-bottom: 8px; }

  .side { width: 300px; flex: none; padding: 16px; display: flex; flex-direction: column; gap: 4px; position: sticky; top: 0; }
  .side-title { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 14px; }
  .side-title :global(svg) { color: var(--accent); }
  .hint { font-size: 12px; margin-bottom: 8px; }
  .group { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--outline); color: var(--secondary); }
  .group > div { flex: 1; display: flex; flex-direction: column; }
  .group b { color: var(--text); font-size: 13px; }
  .group small { font-size: 11.5px; }
  .amt { font-variant-numeric: tabular-nums; white-space: nowrap; }
  @media (max-width: 1250px) { .layout { flex-direction: column-reverse; align-items: stretch; } .side { width: auto; position: static; } }
</style>
