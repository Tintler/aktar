<script>
  // Abonelik / odeme kaydi ekleme ve duzenleme penceresi (F106).
  import Icon from '../lib/Icon.svelte';
  import Modal from './Modal.svelte';
  import Toggle from './Toggle.svelte';
  import { act, toast } from '../lib/state.svelte.js';
  import { CYCLES, STATUSES, METHODS, CURRENCIES, logoDrop, money, shortDate } from '../lib/subscriptions.js';

  let { item = null, categories = [], banks = [], onsave, ondelete, onclose } = $props();

  // subscriptions.view'in hesapladigi alanlar kayda geri gonderilmez.
  const COMPUTED = ['next_due', 'days_left', 'monthly', 'last_date', 'estimate', 'last_payment', 'low', 'high'];
  const today = new Date().toLocaleDateString('sv-SE');  // yerel YYYY-AA-GG
  // Pencere her acilista yeniden kurulur; kaydin o anki kopyasi duzenlenir.
  const blank = () => ({
    id: '', name: '', category: '', amount: '', currency: 'TRY', kind: 'recurring', cycle: 'monthly', status: 'active',
    start_date: today, renewal_date: '', end_date: '', auto_renew: true, method: 'credit', bank: '', card: '', card_last4: '', notes: '', logo: '',
    variable: false, match: '', payments: [],
    ...(item ? Object.fromEntries(Object.entries(item).filter(([key]) => !COMPUTED.includes(key))) : {}),
  });
  let form = $state(blank());
  const amount = $derived(Number(String(form.amount).replace(',', '.')));
  const valid = $derived(form.name.trim() && String(form.amount).trim() !== '' && Number.isFinite(amount) && amount >= 0);
  const once = $derived(form.kind === 'once');
  const card = $derived(form.method === 'credit' || form.method === 'debit');
  // F110: ekstrelerden bulunan odemeler (son 12) ve degisken tutarin tahmini
  const history = $derived((form.payments ?? []).slice(-12));
  const peak = $derived(Math.max(...history.map((p) => p.amount), 1));
  const recent = $derived((form.payments ?? []).slice(-6));
  const average = $derived(recent.length ? recent.reduce((sum, p) => sum + p.amount, 0) / recent.length : null);
  let saving = $state(false);
  // Logo (F107): degismediyse arka uca gonderilmez; '' kaldirir, data URL yenisidir.
  let logoChanged = $state(false);
  const initial = $derived(form.name.trim().slice(0, 1).toLocaleUpperCase('tr'));

  function setLogo(value) {
    form.logo = value;
    logoChanged = true;
  }

  async function pickLogo(path = null) {
    const result = await act('subs_logo', path);
    if (result?.logo) setLogo(result.logo);
  }

  // Panodan yapistirilan gorsel (tarayicida logoya sag tik > Resmi kopyala, sonra Ctrl+V).
  function paste(event) {
    const file = [...(event.clipboardData?.items ?? [])].find((entry) => entry.type.startsWith('image/'))?.getAsFile();
    if (!file) return;
    // Metin kutusuna metin yapistiriliyorsa (panoda metin de varsa) ona dokunulmaz.
    const typing = event.target?.matches?.('input, textarea');
    if (typing && event.clipboardData.types.includes('text/plain')) return;
    event.preventDefault();
    if (file.size > 15 * 1024 * 1024) return toast('Görsel çok büyük (en fazla 15 MB).', 'error');
    const reader = new FileReader();
    reader.onload = () => setLogo(String(reader.result));
    reader.readAsDataURL(file);
  }

  $effect(() => {
    logoDrop.handler = (paths) => pickLogo(paths[0]);
    return () => { logoDrop.handler = null; };
  });

  async function save() {
    if (!valid || saving) return;
    saving = true;
    const values = { ...$state.snapshot(form), amount };
    if (!logoChanged) delete values.logo;
    await onsave(values);
    saving = false;
  }
</script>

<svelte:window onpaste={paste} />

<Modal title={item ? 'Kaydı düzenle' : 'Yeni abonelik / ödeme'} width={660} {onclose}>
  <div class="head">
    <button class="logo" class:has={form.logo} title="Logo seç" onclick={() => pickLogo()}>
      {#if form.logo}<img src={form.logo} alt="" />{:else if initial}<span>{initial}</span>{:else}<Icon name="image" size={22} />{/if}
      <i><Icon name="pencil" size={13} /></i>
    </button>
    <div class="head-side">
      <div class="seg" role="radiogroup" aria-label="Tür">
        <button class:on={!once} role="radio" aria-checked={!once} onclick={() => (form.kind = 'recurring')}><Icon name="repeat" size={15} />Tekrarlayan</button>
        <button class:on={once} role="radio" aria-checked={once} onclick={() => (form.kind = 'once')}><Icon name="calendar" size={15} />Tek seferlik</button>
      </div>
      <div class="logo-hint">
        <button class="link" onclick={() => pickLogo()}>Logo seç</button>{#if form.logo}<span>·</span><button class="link" onclick={() => setLogo('')}>Kaldır</button>{/if}
        <span class="dim">ya da görseli yapıştırın (Ctrl+V) veya pencereye sürükleyin</span>
      </div>
    </div>
  </div>
  <div class="grid">
    <label class="wide2">Ad<input class="field" bind:value={form.name} maxlength="80" placeholder="Netflix, Elektrik, Amazon Prime…" /></label>
    <label>Kategori<input class="field" bind:value={form.category} maxlength="40" list="sub-categories" placeholder="Seçin ya da yazın" /></label>

    <label title={form.variable && average !== null ? 'Ekstrelerde ödeme bulunduğu için son ödemelerin ortalaması kullanılır.' : ''}>
      {#if form.variable && average !== null}<span>Tutar <span class="dim">· ortalama {money(average, form.currency)} kullanılır</span></span>{:else}{form.variable ? 'Tahmini tutar' : 'Tutar'}{/if}
      <span class="money">
        <input class="field" bind:value={form.amount} inputmode="decimal" placeholder="0,00" />
        <select class="field" bind:value={form.currency}>{#each CURRENCIES as c}<option value={c}>{c}</option>{/each}</select>
      </span>
    </label>
    {#if !once}
      <label>Dönem<select class="field" bind:value={form.cycle}>{#each Object.entries(CYCLES) as [key, text]}<option value={key}>{text}</option>{/each}</select></label>
    {/if}
    <label>Durum<select class="field" bind:value={form.status}>{#each Object.entries(STATUSES) as [key, s]}<option value={key}>{s.label}</option>{/each}</select></label>

    <label>Başlangıç tarihi<input class="field" type="date" bind:value={form.start_date} /></label>
    <label>{once ? 'Ödeme tarihi' : 'Yenileme tarihi'}<input class="field" type="date" bind:value={form.renewal_date} /></label>
    <label>{form.status === 'trial' ? 'Deneme bitişi' : 'Bitiş / iptal tarihi'}<input class="field" type="date" bind:value={form.end_date} /></label>
    {#if !once}
      <div class="wide toggle-row"><Toggle bind:checked={form.auto_renew} label="Otomatik yenileniyor" />
        <span class="dim">Yenileme tarihi geçince bir sonraki dönem kendiliğinden hesaplanır.</span></div>
      <div class="wide toggle-row"><Toggle bind:checked={form.variable} label="Tutar değişken" />
        <span class="dim">Elektrik, doğalgaz, su gibi faturalar: tutar ekstrelerdeki son ödemelerin ortalamasıdır.</span></div>
    {/if}
  </div>

  <div class="section"><Icon name="wallet" size={15} />Ödeme</div>
  <div class="grid pay">
    <label>Ödeme yöntemi<select class="field" bind:value={form.method}>{#each Object.entries(METHODS) as [key, m]}<option value={key}>{m.label}</option>{/each}</select></label>
    <label>Banka<input class="field" bind:value={form.bank} maxlength="60" list="sub-banks" placeholder="Garanti BBVA, Akbank…" /></label>
    {#if card}
      <label>Kart<input class="field" bind:value={form.card} maxlength="60" placeholder="Bonus, Axess, Maximum…" /></label>
      <label>Son 4 hane<input class="field mono" bind:value={form.card_last4} maxlength="4" inputmode="numeric" placeholder="1234" /></label>
    {:else}
      <label class="wide2">Açıklama<input class="field" bind:value={form.card} maxlength="60" placeholder="Otomatik ödeme talimatı, abone no…" /></label>
    {/if}
    <label class="wide">Ekstrede arama metni<input class="field" bind:value={form.match} maxlength="120" placeholder="Abone no ya da firma adı (birden fazlaysa virgülle); ekstre taramasında ödemeler bu kayda bağlanır" /></label>
    <label class="wide">Notlar<textarea class="field" rows="2" bind:value={form.notes} maxlength="2000" placeholder="Paket, hesap, iptal yolu…"></textarea></label>
  </div>

  {#if history.length}
    <div class="section"><Icon name="fileText" size={15} />Ekstrelerdeki ödemeler<span class="dim count">{form.payments.length} ödeme</span></div>
    <div class="bars" role="list">
      {#each history as p (p.date + p.amount)}
        <div class="bar" role="listitem" title={`${shortDate(p.date)} · ${money(p.amount, form.currency)}${p.file ? ' · ' + p.file : ''}`}>
          <span class="amt">{money(p.amount, form.currency)}</span>
          <i style:height={`${Math.max(6, (p.amount / peak) * 64)}px`}></i>
          <small>{new Date(p.date).toLocaleDateString('tr-TR', { month: 'short', year: '2-digit' })}</small>
        </div>
      {/each}
    </div>
  {/if}

  <datalist id="sub-categories">{#each categories as c}<option value={c}></option>{/each}</datalist>
  <datalist id="sub-banks">{#each banks as b}<option value={b}></option>{/each}</datalist>

  {#snippet footer()}
    {#if item}<button class="btn ghost danger left" onclick={() => ondelete(item)}><Icon name="trash" size={15} />Sil</button>{/if}
    <button class="btn" onclick={onclose}>Vazgeç</button>
    <button class="btn primary" disabled={!valid || saving} onclick={save}><Icon name="check" size={16} />Kaydet</button>
  {/snippet}
</Modal>

<style>
  .head { display: flex; align-items: center; gap: 16px; }
  .head-side { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; min-width: 0; }
  .logo { position: relative; width: 64px; height: 64px; flex: none; border-radius: 16px; display: grid; place-items: center;
    background: color-mix(in srgb, var(--accent) 16%, var(--surface)); color: var(--accent); font-size: 26px; font-weight: 700;
    border: 1px dashed var(--outline); box-sizing: border-box; }
  .logo.has { background: #fff; border: 1px solid var(--outline); padding: 6px; }
  .logo img { width: 100%; height: 100%; object-fit: contain; }
  .logo i { position: absolute; right: -6px; bottom: -6px; width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center;
    background: var(--overlay); color: var(--secondary); border: 1px solid var(--outline); opacity: 0; transition: opacity .15s; }
  .logo:hover i, .logo:focus-visible i { opacity: 1; }
  .logo-hint { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 12px; }
  .link { color: var(--accent); font-weight: 600; font-size: 12px; }
  .link:hover { text-decoration: underline; }
  .seg { display: inline-flex; align-self: flex-start; padding: 3px; border-radius: 999px; background: var(--surface); gap: 2px; }
  .seg button { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 14px; border-radius: 999px; font-size: 13px; font-weight: 600; color: var(--secondary); }
  .seg button.on { background: var(--text); color: var(--window); }
  .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 14px; }
  label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; font-weight: 600; color: var(--secondary); min-width: 0; }
  .grid.pay { grid-template-columns: 1.25fr 1.25fr 1fr .6fr; }
  .wide { grid-column: 1 / -1; }
  .wide2 { grid-column: span 2; }
  .money { display: flex; gap: 6px; }
  .money input { flex: 1; min-width: 0; }
  .money select { width: 76px; flex: none; }
  .toggle-row { display: flex; align-items: center; gap: 14px; font-size: 12px; }
  .toggle-row > :global(:first-child) { flex: none; white-space: nowrap; }
  .section { display: flex; align-items: center; gap: 8px; margin-top: 6px; padding-top: 14px; border-top: 1px solid var(--outline);
    font-size: 13px; font-weight: 700; color: var(--text); }
  .section :global(svg) { color: var(--accent); }
  textarea.field { font: inherit; font-size: 13px; line-height: 1.5; }
  input[type='date'] { color-scheme: light dark; }
  .left { margin-right: auto; }
  .count { margin-left: auto; font-weight: 500; font-size: 12px; }
  .bars { display: flex; align-items: flex-end; gap: 8px; overflow-x: auto; padding: 4px 2px 2px; }
  .bar { flex: 1; min-width: 52px; display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .bar i { width: 100%; max-width: 34px; border-radius: 6px 6px 2px 2px; background: color-mix(in srgb, var(--accent) 70%, transparent); }
  .bar:last-child i { background: var(--accent); }
  .bar .amt { font-size: 10.5px; font-variant-numeric: tabular-nums; color: var(--secondary); white-space: nowrap; }
  .bar small { font-size: 11px; color: var(--dim); white-space: nowrap; }
  @media (max-width: 700px) { .grid, .grid.pay { grid-template-columns: 1fr 1fr; } .wide2 { grid-column: 1 / -1; } }
</style>
