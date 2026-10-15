<script>
  // Abonelikler (F106): tekrarlayan ve tek seferlik odemeler; tutar, banka/kart, durum, yenileme.
  import Icon from '../lib/Icon.svelte';
  import SubscriptionModal from '../components/SubscriptionModal.svelte';
  import StatementScanModal from '../components/StatementScanModal.svelte';
  import SpendingPanel from '../components/SpendingPanel.svelte';
  import { onDestroy } from 'svelte';
  import { on } from '../lib/api.js';
  import { act, toast, onDrop } from '../lib/state.svelte.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import { CYCLES, STATUSES, METHODS, money, shortDate, daysText, logoDrop } from '../lib/subscriptions.js';

  let data = $state(null);
  let query = $state('');
  let status = $state('');
  let kind = $state('');
  let sort = $state('due');
  let editing = $state(null);   // null: kapali, {}: yeni kayit, kayit: duzenleme
  let scanOpen = $state(false);
  let showAll = $state(false);   // onerilerin hepsi (varsayilan ilk SUGGEST_LIMIT)
  let tab = $state('subs');      // F111: 'subs' | 'spending' (harcama panosu)
  let scanVersion = $state(0);   // tarama bitince harcama panosu yeniden yuklenir
  const SUGGEST_LIMIT = 5;

  async function load() {
    const result = await act('subs_state');
    if (result) data = result;
  }
  load();

  // F110: ekstre taramasi arka planda surer; ilerleme ve sonuc olayla gelir.
  const offScan = on('subs_scan', ({ busy, state, message, error }) => {
    if (state) { data = state; scanVersion++; }
    else if (data) data.scan = { ...data.scan, busy };
    if (message) toast('Ekstre taraması: ' + message, 'ok');
    if (error) toast(error, 'error');
  });
  onDestroy(offScan);

  const scan = $derived(data?.scan);
  const suggestions = $derived(data?.suggestions ?? []);
  const ignoredItems = $derived(data?.ignored ?? []);
  const alerts = $derived(data?.alerts ?? []);

  // F114: zam / yuksek fatura uyarilari
  function alertTitle(a) {
    const pct = a.ratio === null ? '' : ` (${a.ratio > 0 ? '+' : '−'}%${Math.abs(a.ratio * 100).toFixed(0)})`;
    if (a.kind === 'high') return `Son ödeme ortalamanın %${(a.ratio * 100).toFixed(0)} üstünde`;
    return `Tutar ${a.kind === 'price_up' ? 'arttı' : 'azaldı'}: ${money(a.reference, a.currency)} → ${money(a.amount, a.currency)}${pct}`;
  }
  let showIgnored = $state(false);

  async function startScan(slugs, force) {
    scanOpen = false;
    const result = await act('subs_scan', slugs, force);
    if (result) data = result;
  }

  async function suggestionAct(method, ...args) {
    const result = await act(method, ...args);
    if (result) data = result;
    return result;
  }

  async function accept(s) {
    if (await suggestionAct('subs_accept', s.key)) toast(`"${s.name}" eklendi; ödemeleri ekstrelerden bağlandı.`, 'ok');
  }

  async function linkTo(s, event) {
    const id = event.currentTarget.value;
    event.currentTarget.value = '';
    if (id && await suggestionAct('subs_link', s.key, id)) toast(`Ödemeler "${items.find((i) => i.id === id)?.name}" kaydına bağlandı.`, 'ok');
  }

  function suggestionInfo(s) {
    const parts = [s.subscriber_no ? `Abone no ${s.subscriber_no}` : '', `${s.count} ödeme`, `son ${shortDate(s.last_date)}`];
    if (s.months > 1) parts.push(`ayın ~${s.day}. günü`);
    return parts.filter(Boolean).join(' · ');
  }

  // Birakilan gorsel acik kaydin logosu olur (F107).
  onDrop('subscriptions', (paths) => {
    if (logoDrop.handler) logoDrop.handler(paths);
    else toast('Logo eklemek için bir kaydı açın ya da yeni kayıt ekleyin, sonra görseli bırakın.', 'info');
  });

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

  // Yaklasan odemesi olmayan kaydin tarihinin anlami (subscriptions.last_date).
  function pastLabel(item) {
    if (item.kind === 'once') return item.last_date < (data?.today ?? '') ? 'ödendi' : 'ödeme tarihi';
    if (item.status === 'paused') return 'durduruldu';
    if (item.status === 'cancelled' && !item.end_date) return 'iptal edildi';
    return 'bitti';
  }

  function payment(item) {
    const parts = [item.bank, item.card].filter(Boolean);
    return parts.join(' · ');
  }
</script>

<section class="page">
  <div class="page-head">
    <h1>{tab === 'spending' ? 'Harcamalar' : 'Abonelikler'}</h1>
    <span class="seg" role="tablist">
      <button role="tab" aria-selected={tab === 'subs'} class:on={tab === 'subs'} onclick={() => (tab = 'subs')}><Icon name="repeat" size={15} />Abonelikler</button>
      <button role="tab" aria-selected={tab === 'spending'} class:on={tab === 'spending'} onclick={() => (tab = 'spending')}><Icon name="wallet" size={15} />Harcamalar</button>
    </span>
    <span class="head-actions">
      {#if scan?.busy}
        <button class="btn" onclick={() => act('subs_scan_stop')}><Icon name="stop" size={16} />Taramayı durdur</button>
      {:else}
        <button class="btn" onclick={() => (scanOpen = true)} title="Banka ve kredi kartı ekstrelerindeki ödemeleri kayıtlara bağlar, yeni faturaları önerir"><Icon name="fileSearch" size={16} />Ekstrelerden tara</button>
      {/if}
      {#if tab === 'subs'}<button class="btn primary" onclick={() => (editing = {})}><Icon name="plus" size={16} />Yeni kayıt</button>{/if}
    </span>
  </div>
  <div class="page-body">
    {#if scan?.busy}
      <div class="card scanning">
        <Icon name="loader" size={16} spin />
        <span class="ellipsis">Ekstreler okunuyor · {scan.busy.done + 1}/{scan.busy.total}{#if scan.busy.name}<span class="dim"> · {scan.busy.name}</span>{/if}</span>
        <span class="progress"><i style:width={`${(scan.busy.done / Math.max(1, scan.busy.total)) * 100}%`}></i></span>
      </div>
    {/if}

    {#if tab === 'spending'}
      <SpendingPanel version={scanVersion} onscan={() => (scanOpen = true)} />
    {:else}
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

    {#if alerts.length}
      <div class="card alerts">
        {#each alerts as a (a.key)}
          <div class="alert-row">
            <Icon name="alert" size={16} />
            <div class="info">
              <span class="title"><b class="ellipsis">{a.name}</b><span class="dim">{alertTitle(a)}</span></span>
              <small class="dim">{a.kind === 'high' ? `Son ödeme ${money(a.amount, a.currency)} · önceki ortalama ${money(a.reference, a.currency)} · ` : ''}{shortDate(a.date)}</small>
            </div>
            <div class="sug-actions">
              {#if a.kind !== 'high' && Math.abs(a.stored - a.amount) > 0.005}
                <button class="btn sm" onclick={() => suggestionAct('subs_apply_price', a.id)}>Tutarı {money(a.amount, a.currency)} yap</button>
              {/if}
              <button class="btn sm ghost" onclick={() => (editing = items.find((i) => i.id === a.id))}>Kaydı aç</button>
              <button class="icon-btn sm" title="Tamam, gizle" onclick={() => suggestionAct('subs_dismiss_alert', a.key)}><Icon name="x" size={15} /></button>
            </div>
          </div>
        {/each}
      </div>
    {/if}

    {#if suggestions.length || ignoredItems.length}
      <div class="card suggest">
        <div class="side-title"><Icon name="sparkles" size={16} />Ekstrelerden öneriler<span class="badge accent">{suggestions.length}</span>
          <span class="grow"></span>
          {#if ignoredItems.length}<button class="link" onclick={() => (showIgnored = !showIgnored)}>{showIgnored ? 'Yoksayılanları gizle' : `Yoksayılanlar (${ignoredItems.length})`}</button>{/if}
        </div>
        {#if !suggestions.length}<p class="dim none-left">Yeni öneri yok.</p>{/if}
        {#each showAll ? suggestions : suggestions.slice(0, SUGGEST_LIMIT) as s (s.key)}
          <div class="sug">
            <span class="mark">{s.name.slice(0, 1).toLocaleUpperCase('tr')}</span>
            <div class="info">
              <span class="title"><b class="ellipsis">{s.name}</b>{#if s.category}<span class="badge">{s.category}</span>{/if}</span>
              <small class="dim ellipsis" title={s.description}>{suggestionInfo(s)}</small>
            </div>
            <div class="num"><b>{money(s.count > 1 ? s.average : s.last)}</b><small class="dim">{s.count > 1 ? (s.variable ? 'ortalama · değişken' : 'her ödeme') : 'tek ödeme'}</small></div>
            <div class="sug-actions">
              <button class="btn sm primary" onclick={() => accept(s)}><Icon name="plus" size={14} />Ekle</button>
              {#if items.length}
                <select class="field sm" title="Ödemeleri var olan bir kayda bağla" onchange={(e) => linkTo(s, e)}>
                  <option value="">Kayda bağla…</option>
                  {#each items as item (item.id)}<option value={item.id}>{item.name}</option>{/each}
                </select>
              {/if}
              <button class="icon-btn sm" title="Yoksay (bir daha önerilmez)" onclick={() => suggestionAct('subs_ignore', s.key)}><Icon name="x" size={15} /></button>
            </div>
          </div>
        {/each}
        {#if suggestions.length > SUGGEST_LIMIT}
          <button class="link more" onclick={() => (showAll = !showAll)}>{showAll ? 'Daha az göster' : `${suggestions.length - SUGGEST_LIMIT} öneri daha`}</button>
        {/if}
        {#if showIgnored && ignoredItems.length}
          <div class="ignored">
            <div class="ignored-head"><span class="dim">Yoksayılan öneriler</span>
              {#if ignoredItems.length > 1}<button class="link" onclick={() => suggestionAct('subs_unignore_all')}>Hepsini geri getir</button>{/if}</div>
            {#each ignoredItems as s (s.key)}
              <div class="sug off">
                <span class="mark">{s.name.slice(0, 1).toLocaleUpperCase('tr')}</span>
                <div class="info"><b class="ellipsis">{s.name}</b><small class="dim">{s.count} ödeme · son {shortDate(s.last_date)}</small></div>
                <div class="num"><b>{money(s.average)}</b></div>
                <button class="btn sm" onclick={() => suggestionAct('subs_ignore', s.key, true)}><Icon name="restore" size={14} />Geri getir</button>
              </div>
            {/each}
          </div>
        {/if}
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
                      <div class="name">{#if item.logo}<span class="mark img"><img src={item.logo} alt="" /></span>{:else}<span class="mark">{item.name.slice(0, 1).toLocaleUpperCase('tr')}</span>{/if}
                        <div class="ellipsis"><b>{item.name}</b><small class="dim">{[item.category, item.kind === 'once' ? 'Tek seferlik' : CYCLES[item.cycle]].filter(Boolean).join(' · ')}</small></div></div>
                    </td>
                    <td class="num">
                      <b>{money(item.estimate ?? item.amount, item.currency)}</b>
                      {#if item.variable && item.last_payment}<small class="dim" title={`En düşük ${money(item.low, item.currency)} · en yüksek ${money(item.high, item.currency)}`}>ort. · son {money(item.last_payment.amount, item.currency)}</small>
                      {:else if item.variable}<small class="dim">değişken</small>
                      {:else if item.kind === 'recurring' && item.cycle !== 'monthly' && item.monthly}<small class="dim">aylık {money(item.monthly, item.currency)}</small>{/if}
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
                      {:else if item.last_date}
                        <span class="dim">{shortDate(item.last_date)}</span>
                        <small class="dim">{pastLabel(item)}</small>
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
    {/if}
  </div>
</section>

{#if scanOpen}
  <StatementScanModal {scan} onstart={startScan} onauto={(on) => suggestionAct('subs_set_auto', on)} onclose={() => (scanOpen = false)} />
{/if}

{#if editing}
  <SubscriptionModal item={editing.id ? editing : null} categories={data?.categories ?? []} {banks}
    onsave={save} ondelete={remove} onclose={() => (editing = null)} />
{/if}

<style>
  .head-actions { display: flex; gap: 8px; }
  .seg { display: inline-flex; padding: 3px; border-radius: 999px; background: var(--surface); gap: 2px; margin-right: 8px; }
  .seg button { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 14px; border-radius: 999px; font-size: 13px; font-weight: 600; color: var(--secondary); }
  .seg button:hover:not(.on) { color: var(--text); }
  .seg button.on { background: var(--text); color: var(--window); }
  .scanning { display: flex; align-items: center; gap: 12px; padding: 12px 16px; margin-bottom: 16px; font-size: 13px; color: var(--text); }
  .scanning :global(svg) { color: var(--accent); flex: none; }
  .scanning .ellipsis { flex: 1; min-width: 0; }
  .progress { width: 180px; height: 6px; border-radius: 999px; background: var(--surface-active); overflow: hidden; flex: none; }
  .progress i { display: block; height: 100%; background: var(--accent); transition: width .3s; }
  .suggest { padding: 14px 16px 8px; margin-bottom: 16px; display: flex; flex-direction: column; }
  .suggest .side-title { margin-bottom: 6px; }
  .sug { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-top: 1px solid var(--outline); min-width: 0; }
  .sug .info { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .sug .title { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .sug small { font-size: 11.5px; margin-top: 2px; }
  .sug .num { display: flex; flex-direction: column; }
  .sug-actions { display: flex; align-items: center; gap: 6px; flex: none; }
  .sug-actions select { width: 140px; }
  .link { color: var(--accent); font-weight: 600; font-size: 12px; }
  .link:hover { text-decoration: underline; }
  .more { align-self: flex-start; padding: 8px 0 6px; }
  .alerts { padding: 4px 16px; margin-bottom: 16px; border-color: color-mix(in srgb, var(--warning) 40%, var(--outline)); }
  .alert-row { display: flex; align-items: center; gap: 12px; padding: 10px 0; min-width: 0; }
  .alert-row + .alert-row { border-top: 1px solid var(--outline); }
  .alert-row > :global(svg) { color: var(--warning); flex: none; }
  .alert-row .info { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .alert-row .title { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
  .alert-row .title .dim { font-size: 12.5px; white-space: nowrap; }
  .alert-row small { font-size: 11.5px; margin-top: 2px; }
  .none-left { font-size: 12.5px; margin: 4px 0 8px; }
  .ignored { margin-top: 6px; padding-top: 8px; border-top: 1px dashed var(--outline); }
  .ignored-head { display: flex; justify-content: space-between; align-items: center; font-size: 12px; padding-bottom: 4px; }
  .sug.off .mark, .sug.off .info, .sug.off .num { opacity: .6; }
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
  .mark.img { background: #fff; padding: 4px; box-sizing: border-box; }
  .mark img { width: 100%; height: 100%; object-fit: contain; }
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
