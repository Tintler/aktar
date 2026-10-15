<script>
  // Harcama panosu (F111): taranmis ekstre satirlarindan aylik toplam, tur dagilimi, firmalar.
  // Hesap expenses.py'de; kart odemeleri ve kendi transferleri sayilmaz.
  import Icon from '../lib/Icon.svelte';
  import ExcludedModal from './ExcludedModal.svelte';
  import { untrack } from 'svelte';
  import { act } from '../lib/state.svelte.js';
  import { plot, seriesColor } from '../lib/chart.js';
  import { money, shortDate } from '../lib/subscriptions.js';

  let { onscan, version = 0 } = $props();   // version: tarama bitince pano yenilensin

  let board = $state(null);
  let month = $state(null);   // null: en son ay
  let showExcluded = $state(false);

  async function load() {
    const result = await act('subs_spending', month);
    if (result) { board = result; month = result.month; }
  }
  $effect(() => { version; untrack(load); });

  function pick(value) { month = value; load(); }

  let color = $state(seriesColor());   // HTML cubuklar grafikle ayni renk; tema degisince guncellenir
  $effect(() => {
    const retheme = () => (color = seriesColor());
    window.addEventListener('aktar-theme', retheme);
    return () => window.removeEventListener('aktar-theme', retheme);
  });

  const monthName = (key, long = false) => {
    if (!key) return '';
    if (key === 'all') return 'Tüm dönem';
    const [y, m] = key.split('-').map(Number);
    return new Date(y, m - 1, 1).toLocaleDateString('tr-TR', long ? { month: 'long', year: 'numeric' } : { month: 'short' });
  };
  const percent = (value) => `%${(value * 100).toLocaleString('tr-TR', { maximumFractionDigits: value < 0.1 ? 1 : 0 })}`;

  const months = $derived(board?.months ?? []);
  const change = $derived(board?.previous);
  const maxCategory = $derived(Math.max(1, ...(board?.categories ?? []).map((c) => c.total)));
  const maxMerchant = $derived(Math.max(1, ...(board?.merchants ?? []).map((m) => m.total)));

  // Aylik cubuklar: secili ay tam renk, digerleri soluk; tiklanan ay secilir. Eksik (kismi) aylar '*'.
  const monthly = $derived({
    spec: {
      type: 'bar', unit: 'TL',
      // Yil, ilk cubukta ve Ocak'ta yazilir.
      labels: months.map((m, i) => monthName(m.month) + (i === 0 || m.month.endsWith('-01') ? ` '${m.month.slice(2, 4)}` : '') + (m.partial ? '*' : '')),
      series: [{ name: 'Giden harcama', values: months.map((m) => m.total) }],
    },
    tune(cfg, colors) {
      const set = cfg.data.datasets[0];
      set.backgroundColor = months.map((m) => (month === 'all' || m.month === month ? colors[0] : colors[0] + '55'));
      set.hoverBackgroundColor = colors[0];
      cfg.options.plugins.legend.display = false;
      cfg.options.plugins.tooltip.callbacks.title = (list) => monthName(months[list[0].dataIndex].month, true);
      cfg.options.plugins.tooltip.callbacks.footer = (list) => {
        const m = months[list[0].dataIndex];
        return `${m.count} işlem${m.partial ? ' · kısmi ay' : ''}`;
      };
      cfg.options.onClick = (_event, elements) => { if (elements.length) pick(months[elements[0].index].month); };
      cfg.options.onHover = (event, elements) => { event.native.target.style.cursor = elements.length ? 'pointer' : 'default'; };
    },
  });
</script>

{#if !board}
  <p class="empty">Yükleniyor…</p>
{:else if !board.statements || !board.period}
  <div class="blank card">
    <Icon name="fileSearch" size={34} />
    <b>Henüz okunmuş ekstre yok</b>
    <span>Harcama panosu banka hesap özetleri ve kredi kartı ekstrelerindeki işlemlerden hazırlanır. Ekstrelerin bulunduğu koleksiyonları tarayın; aylık harcamanız, türlere göre dağılım ve en çok harcadığınız firmalar burada görünür.</span>
    <button class="btn primary" onclick={onscan}><Icon name="fileSearch" size={16} />Ekstrelerden tara</button>
  </div>
{:else}
  <div class="bar">
    <select class="field sm" value={month} onchange={(e) => pick(e.currentTarget.value)} title="Dönem">
      {#each board.options as key}<option value={key}>{monthName(key, true)}</option>{/each}
      <option value="all">Tüm dönem</option>
    </select>
    <span class="dim note">{board.statements} ekstre · {shortDate(board.period.first)} – {shortDate(board.period.last)}</span>
  </div>

  <div class="stats">
    <div class="stat card">
      <span class="label">{month === 'all' ? 'Toplam harcama' : monthName(month, true)}</span>
      <b>{money(board.total)}</b>
      <span class="dim">{board.count} işlem{board.partial ? ' · ay eksik (ekstre ay ortasında)' : ''}</span>
    </div>
    <div class="stat card">
      <span class="label">Önceki aya göre</span>
      {#if change}
        <b class="delta" class:up={change.change > 0} class:down={change.change < 0}>
          <Icon name={change.change > 0 ? 'arrowUp' : 'down'} size={18} />{money(Math.abs(change.change))}
        </b>
        <span class="dim">{change.ratio !== null ? percent(Math.abs(change.ratio)) + (change.change > 0 ? ' fazla' : ' az') + ' · ' : ''}{monthName(change.month, true)}: {money(change.total)}</span>
        {#if board.partial}<span class="warn"><Icon name="alert" size={13} />Bu ay eksik; karşılaştırma yanıltıcı olabilir</span>{/if}
      {:else}
        <b class="dim">—</b><span class="dim">{month === 'all' ? 'tüm dönem seçili' : 'önceki ay verisi yok'}</span>
      {/if}
    </div>
    <div class="stat card">
      <span class="label">Aylık ortalama</span>
      {#if board.average !== null}<b>{money(board.average)}</b><span class="dim">tam aylar ({months.filter((m) => !m.partial).length})</span>
      {:else}<b class="dim">—</b><span class="dim">tam ay verisi yok</span>{/if}
    </div>
    <button class="stat card clickable" onclick={() => (showExcluded = true)} disabled={!board.excluded.count}
      title="Kart borcu ödemeleri ve kendi hesaplarınız arasındaki transferler harcama sayılmaz; aynı para iki kez toplanmasın. Ayrıntı için tıklayın.">
      <span class="label">Sayılmayan<Icon name="external" size={12} /></span>
      <b>{money(board.excluded.total)}</b>
      <span class="dim">{board.excluded.count} kart ödemesi / transfer · {month === 'all' ? 'tüm dönem' : monthName(month, true)}</span>
    </button>
  </div>

  <div class="card chart-card">
    <div class="side-title"><Icon name="calendar" size={16} />Aylara göre giden harcama</div>
    <span class="dim hint">Bir aya tıklayarak seçin{months.some((m) => m.partial) ? ' · * ekstre ayın tamamını kapsamıyor' : ''}</span>
    <div class="plot" use:plot={monthly}></div>
  </div>

  <div class="grid" style:--series={color}>
    <div class="card block">
      <div class="side-title"><Icon name="list" size={16} />Türlere göre</div>
      <span class="dim hint">Takip ettiğiniz aboneliklere uyan ödemeler kaydın türüyle sayılır</span>
      {#each board.categories as c (c.key)}
        <div class="row">
          <span class="name">{c.label}<small class="dim">{c.count} işlem</small></span>
          <span class="meter"><i style:width={`${(c.total / maxCategory) * 100}%`}></i></span>
          <span class="amt">{money(c.total)}<small class="dim">{percent(c.share)}</small></span>
        </div>
      {:else}
        <p class="empty">Bu dönemde harcama yok.</p>
      {/each}
    </div>

    <div class="card block">
      <div class="side-title"><Icon name="wallet" size={16} />En çok harcanan yerler</div>
      <span class="dim hint">{board.merchant_count > board.merchants.length ? `${board.merchant_count} firmadan ilk ${board.merchants.length}` : `${board.merchant_count} firma`}</span>
      {#each board.merchants as m (m.key)}
        <div class="row">
          <span class="name"><span class="ellipsis" title={m.name}>{m.name}</span><small class="dim">{m.category} · {m.count} işlem</small></span>
          <span class="meter"><i style:width={`${(m.total / maxMerchant) * 100}%`}></i></span>
          <span class="amt">{money(m.total)}<small class="dim">{percent(m.share)}</small></span>
        </div>
      {:else}
        <p class="empty">Bu dönemde harcama yok.</p>
      {/each}
    </div>
  </div>
{/if}

{#if showExcluded && board?.excluded}
  <ExcludedModal excluded={board.excluded} period={month === 'all' ? 'Tüm dönem' : monthName(month, true)} onclose={() => (showExcluded = false)} />
{/if}

<style>
  .bar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
  .bar select { width: 180px; }
  .note { font-size: 12px; }
  .field.sm { height: 32px; font-size: 12.5px; }
  .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 16px; }
  .stat { display: flex; flex-direction: column; gap: 4px; padding: 16px 18px; min-width: 0; }
  .stat b { font-size: 22px; font-weight: 700; letter-spacing: -.01em; font-variant-numeric: tabular-nums; display: flex; align-items: center; gap: 4px; }
  .stat .label { margin-bottom: 4px; display: flex; align-items: center; gap: 6px; }
  .stat.clickable { text-align: left; font: inherit; color: inherit; cursor: pointer; transition: border-color .15s, background .15s; }
  .stat.clickable:hover:not(:disabled) { border-color: var(--accent); }
  .stat.clickable:disabled { cursor: default; }
  .stat.clickable :global(svg) { opacity: .6; }
  .stat .dim { font-size: 12px; }
  .warn { display: flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--warning); }
  .delta.up :global(svg) { color: var(--danger); }
  .delta.down :global(svg) { color: var(--ok); }
  @media (max-width: 1100px) { .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

  .side-title { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 14px; }
  .side-title :global(svg) { color: var(--accent); }
  .hint { font-size: 12px; margin: 2px 0 8px; display: block; }
  .chart-card { padding: 16px; margin-bottom: 16px; }
  .plot { position: relative; height: 240px; }

  .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: start; }
  @media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }
  .block { padding: 16px; display: flex; flex-direction: column; min-width: 0; }
  .row { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(60px, 1fr) auto; align-items: center; gap: 12px;
    padding: 9px 0; border-top: 1px solid var(--outline); font-size: 13px; }
  .name { display: flex; flex-direction: column; min-width: 0; color: var(--text); font-weight: 600; }
  .name small, .amt small { font-size: 11.5px; font-weight: 400; margin-top: 2px; }
  .meter { height: 8px; border-radius: 4px; background: var(--surface); overflow: hidden; }
  .meter i { display: block; height: 100%; border-radius: 4px; background: var(--series); }
  .amt { display: flex; flex-direction: column; align-items: flex-end; font-variant-numeric: tabular-nums; white-space: nowrap; font-weight: 600; }

  .blank { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 48px 32px; text-align: center; color: var(--secondary); }
  .blank :global(svg) { color: var(--accent); }
  .blank b { color: var(--text); font-size: 16px; }
  .blank span { max-width: 520px; font-size: 13px; line-height: 1.55; margin-bottom: 8px; }
</style>
