<script>
  // F89: koleksiyonun e-posta kurallari: Gmail'den ekstre / rapor eklerini secilen klasore indirir.
  import Modal from './Modal.svelte';
  import Toggle from './Toggle.svelte';
  import Icon from '../lib/Icon.svelte';
  import { act, go, toast } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';
  import { confirm } from '../lib/confirm.svelte.js';

  let { onclose } = $props();
  let info = $state(null);
  let edit = $state(null);          // duzenlenen kural (yeni kuralda id bos)
  let pdfPassword = $state('');
  let pdfChanged = $state(false);
  let preview = $state(null);       // {items} | {loading}
  let fetching = $state(false);

  const blank = () => ({ id: '', title: '', sender: '', subject: '', what: 'pdf', since: '', folder: '', enabled: true });

  async function load() {
    info = await act('mail_rules');
    if (!info) onclose();
  }
  load();

  function startEdit(rule) {
    edit = { ...blank(), ...(rule ?? {}) };
    pdfPassword = '';
    pdfChanged = false;
    preview = null;
  }

  async function browse() {
    const folder = await call('choose_folder', 'E-posta eklerinin indirileceği klasör');
    if (folder) edit.folder = folder;
  }

  async function runPreview(rule) {
    preview = { loading: true, items: [] };
    const result = await act('mail_preview', $state.snapshot(rule));
    preview = result ? { items: result.items } : null;
  }

  async function saveRule() {
    const result = await act('mail_save_rule', $state.snapshot(edit), pdfChanged ? pdfPassword : null);
    if (!result) return;
    info = result;
    edit = null;
    preview = null;
    toast('Kural kaydedildi. Klasör koleksiyona eklendi.', 'ok');
  }

  async function toggle(rule) {
    const result = await act('mail_save_rule', { ...$state.snapshot(rule), enabled: !rule.enabled }, null);
    if (result) info = result;
  }

  async function remove(rule) {
    const ok = await confirm({ title: 'Kuralı sil', message: `"${rule.title}" kuralı silinsin mi? İndirilmiş dosyalar klasörde kalır.`, ok: 'Sil', danger: true });
    if (!ok) return;
    const result = await act('mail_delete_rule', rule.id);
    if (result) info = result;
  }

  async function fetchNow(ruleId = null) {
    fetching = true;
    const result = await act('mail_fetch', ruleId);
    fetching = false;
    if (!result) return;
    info = result;
    toast(result.message, 'ok');
  }

  const checked = $derived(info?.checked ? new Date(info.checked).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' }) : '');
  const whatLabel = (id) => info?.what.find((w) => w.id === id)?.label ?? id;
  const fmt = (iso) => (iso ? iso.split('-').reverse().join('.') : '');
</script>

<Modal title="E-postadan al" width={720} onclose={onclose}>
  {#if !info}
    <p class="dim"><Icon name="loader" size={14} spin /> Yükleniyor…</p>
  {:else}
    {#if !info.account}
      <div class="note warn">
        <Icon name="alert" size={16} />
        <span>Önce Gmail adresinizi ve uygulama şifrenizi girin.</span>
        <button class="btn sm" onclick={() => { onclose(); go('settings'); }}>Ayarlar → E-posta</button>
      </div>
    {:else}
      <p class="dim small">{info.address} · kurala uyan postaların ekleri seçtiğiniz klasöre "gün ad" biçiminde indirilir (ör. 2026-10-03 Hesap Ozeti.pdf). Aynı posta ve aynı içerik iki kez indirilmez; yeni dosyalar listede "yeni" görünür.</p>
    {/if}

    {#if edit}
      <div class="editor">
        <div class="grid">
          <label>Kural adı<input class="field" bind:value={edit.title} placeholder="World Gold ekstreleri" /></label>
          <label>Ne alınsın
            <select class="field" bind:value={edit.what}>{#each info.what as w}<option value={w.id}>{w.label}</option>{/each}</select></label>
          <label>Gönderen içerir<input class="field" bind:value={edit.sender} placeholder="@worldcard.com.tr" /></label>
          <label>Konu içerir<input class="field" bind:value={edit.subject} placeholder="Hesap Özeti" /></label>
          <label>Şu tarihten beri<input class="field" type="date" bind:value={edit.since} /><small>Boş: son 1 yıl</small></label>
          <label>PDF şifresi
            <input class="field" type="password" bind:value={pdfPassword} oninput={() => (pdfChanged = true)} autocomplete="off"
              placeholder={edit.has_password && !pdfChanged ? 'kayıtlı' : 'şifreli değilse boş'} />
            <small>Şifreli PDF'ler şifresiz kopya olarak kaydedilir.{#if edit.has_password && !pdfChanged} <button class="link" onclick={() => { pdfPassword = ''; pdfChanged = true; }}>Şifreyi sil</button>{/if}</small></label>
        </div>
        <label class="wide">İndirilecek klasör
          <span class="pick"><input class="field" bind:value={edit.folder} placeholder="D:\Finans\Ekstreler" /><button class="btn sm" onclick={browse}>Gözat…</button></span>
          <small>Klasör koleksiyona eklenir.</small></label>
        <div class="row">
          <button class="btn sm" disabled={!info.account || (!edit.sender.trim() && !edit.subject.trim()) || preview?.loading} onclick={() => runPreview(edit)}>
            <Icon name="eye" size={14} />Önizle</button>
          <span class="grow"></span>
          <button class="btn sm ghost" onclick={() => { edit = null; preview = null; }}>Vazgeç</button>
          <button class="btn sm primary" onclick={saveRule}><Icon name="check" size={14} />Kuralı kaydet</button>
        </div>
      </div>
    {:else}
      <div class="rules">
        {#each info.rules as rule (rule.id)}
          <div class="rule">
            <Toggle checked={rule.enabled} onchange={() => toggle(rule)} />
            <div class="rtext">
              <b class="ellipsis">{rule.title}</b>
              <span class="dim ellipsis">{[rule.sender, rule.subject && `"${rule.subject}"`].filter(Boolean).join(' · ')} · {whatLabel(rule.what)}{rule.since ? ` · ${fmt(rule.since)}'den beri` : ''}</span>
              <span class="dim ellipsis" title={rule.folder}><Icon name="folder" size={12} /> {rule.folder} · {rule.fetched} posta alındı</span>
            </div>
            <button class="icon-btn" title="Önizle" disabled={!info.account} onclick={() => { startEdit(rule); runPreview(rule); }}><Icon name="eye" size={16} /></button>
            <button class="icon-btn" title="Bu kuralı şimdi indir" disabled={!info.account || fetching} onclick={() => fetchNow(rule.id)}><Icon name="download" size={16} /></button>
            <button class="icon-btn" title="Düzenle" onclick={() => startEdit(rule)}><Icon name="pencil" size={16} /></button>
            <button class="icon-btn" title="Sil" onclick={() => remove(rule)}><Icon name="trash" size={16} /></button>
          </div>
        {:else}
          <div class="empty dim">Henüz kural yok. Örneğin gönderen "@worldcard.com.tr" ve konu "Hesap Özeti" olan postaların eklerini (PDF, Excel…) bir klasöre indiren bir kural ekleyin.</div>
        {/each}
      </div>
      <div><button class="btn sm" onclick={() => startEdit(null)}><Icon name="plus" size={14} />Kural ekle</button></div>
    {/if}

    {#if preview}
      <div class="preview">
        {#if preview.loading}
          <p class="dim small"><Icon name="loader" size={14} spin /> Gmail'de aranıyor…</p>
        {:else}
          <p class="dim small">{preview.items.length} posta eşleşti{preview.items.some((i) => i.done) ? `, ${preview.items.filter((i) => i.done).length} tanesi zaten alınmış` : ''}. Hiçbir şey indirilmedi.</p>
          {#each preview.items as item}
            <div class="mail">
              <span class="mono dim">{fmt(item.date)}</span>
              <span class="ellipsis" title={item.sender}>{item.subject}</span>
              <span class={item.done ? 'badge' : 'badge accent'}>{item.done ? 'alınmış' : 'yeni'}</span>
            </div>
          {/each}
        {/if}
      </div>
    {/if}
  {/if}
  {#snippet footer()}
    <span class="dim small grow">{checked ? `Son kontrol: ${checked}` : 'Henüz kontrol edilmedi'} · koleksiyon her açıldığında da kontrol edilir</span>
    <button class="btn" onclick={onclose}>Kapat</button>
    <button class="btn primary" disabled={!info?.account || !info?.rules.some((r) => r.enabled) || fetching || !!edit} onclick={() => fetchNow()}>
      <Icon name={fetching ? 'loader' : 'download'} size={16} spin={fetching} />{fetching ? 'İndiriliyor…' : 'Şimdi indir'}</button>
  {/snippet}
</Modal>

<style>
  .small { font-size: 12px; line-height: 1.5; }
  .grow { flex: 1; }
  .note { display: flex; align-items: center; gap: 10px; font-size: 13px; padding: 10px 12px; border-radius: 10px; }
  .note span { flex: 1; }
  .note.warn { color: var(--warning); background: color-mix(in srgb, var(--warning) 10%, transparent); }
  .rules { border: 1px solid var(--outline); border-radius: 10px; overflow: hidden; }
  .rule { display: flex; align-items: center; gap: 12px; padding: 10px 12px; }
  .rule + .rule { border-top: 1px solid var(--outline); }
  .rtext { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
  .rtext b { font-size: 14px; font-weight: 600; }
  .rtext :global(svg) { vertical-align: -2px; }
  .empty { padding: 16px; font-size: 13px; line-height: 1.5; }
  .editor { display: flex; flex-direction: column; gap: 12px; padding: 14px; border: 1px solid var(--outline); border-radius: 10px; }
  .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--secondary); font-weight: 500; }
  label small { color: var(--dim); font-weight: 400; }
  .pick { display: flex; gap: 6px; }
  .pick .field { flex: 1; min-width: 0; }
  .row { display: flex; align-items: center; gap: 8px; }
  .link { color: var(--accent); font-size: 12px; padding: 0; text-decoration: underline; }
  .preview { border-top: 1px solid var(--outline); padding-top: 10px; display: flex; flex-direction: column; }
  .mail { display: grid; grid-template-columns: 86px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 6px 0; font-size: 13px; border-top: 1px solid var(--outline); }
</style>
