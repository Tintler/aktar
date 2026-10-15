<script>
  // Abonelik / odeme kaydi ekleme ve duzenleme penceresi (F106).
  import Icon from '../lib/Icon.svelte';
  import Modal from './Modal.svelte';
  import Toggle from './Toggle.svelte';
  import { CYCLES, STATUSES, METHODS, CURRENCIES } from '../lib/subscriptions.js';

  let { item = null, categories = [], banks = [], onsave, ondelete, onclose } = $props();

  const today = new Date().toLocaleDateString('sv-SE');  // yerel YYYY-AA-GG
  // Pencere her acilista yeniden kurulur; kaydin o anki kopyasi duzenlenir.
  const blank = () => ({
    id: '', name: '', category: '', amount: '', currency: 'TRY', kind: 'recurring', cycle: 'monthly', status: 'active',
    start_date: today, renewal_date: '', end_date: '', auto_renew: true, method: 'credit', bank: '', card: '', card_last4: '', notes: '',
    ...(item ? Object.fromEntries(Object.entries(item).filter(([key]) => !['next_due', 'days_left', 'monthly'].includes(key))) : {}),
  });
  let form = $state(blank());
  const amount = $derived(Number(String(form.amount).replace(',', '.')));
  const valid = $derived(form.name.trim() && String(form.amount).trim() !== '' && Number.isFinite(amount) && amount >= 0);
  const once = $derived(form.kind === 'once');
  const card = $derived(form.method === 'credit' || form.method === 'debit');
  let saving = $state(false);

  async function save() {
    if (!valid || saving) return;
    saving = true;
    await onsave({ ...$state.snapshot(form), amount });
    saving = false;
  }
</script>

<Modal title={item ? 'Kaydı düzenle' : 'Yeni abonelik / ödeme'} width={660} {onclose}>
  <div class="seg" role="radiogroup" aria-label="Tür">
    <button class:on={!once} role="radio" aria-checked={!once} onclick={() => (form.kind = 'recurring')}><Icon name="repeat" size={15} />Tekrarlayan</button>
    <button class:on={once} role="radio" aria-checked={once} onclick={() => (form.kind = 'once')}><Icon name="calendar" size={15} />Tek seferlik</button>
  </div>
  <div class="grid">
    <label class="wide2">Ad<input class="field" bind:value={form.name} maxlength="80" placeholder="Netflix, Elektrik, Amazon Prime…" /></label>
    <label>Kategori<input class="field" bind:value={form.category} maxlength="40" list="sub-categories" placeholder="Seçin ya da yazın" /></label>

    <label>Tutar
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
    <label class="wide">Notlar<textarea class="field" rows="2" bind:value={form.notes} maxlength="2000" placeholder="Paket, hesap, iptal yolu…"></textarea></label>
  </div>

  <datalist id="sub-categories">{#each categories as c}<option value={c}></option>{/each}</datalist>
  <datalist id="sub-banks">{#each banks as b}<option value={b}></option>{/each}</datalist>

  {#snippet footer()}
    {#if item}<button class="btn ghost danger left" onclick={() => ondelete(item)}><Icon name="trash" size={15} />Sil</button>{/if}
    <button class="btn" onclick={onclose}>Vazgeç</button>
    <button class="btn primary" disabled={!valid || saving} onclick={save}><Icon name="check" size={16} />Kaydet</button>
  {/snippet}
</Modal>

<style>
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
  .section { display: flex; align-items: center; gap: 8px; margin-top: 6px; padding-top: 14px; border-top: 1px solid var(--outline);
    font-size: 13px; font-weight: 700; color: var(--text); }
  .section :global(svg) { color: var(--accent); }
  textarea.field { font: inherit; font-size: 13px; line-height: 1.5; }
  input[type='date'] { color-scheme: light dark; }
  .left { margin-right: auto; }
  @media (max-width: 700px) { .grid, .grid.pay { grid-template-columns: 1fr 1fr; } .wide2 { grid-column: 1 / -1; } }
</style>
