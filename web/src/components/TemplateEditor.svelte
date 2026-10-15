<script>
  // Ayarlar > Sohbet sablonlari (F104): ad + talimat metni; kendi Kaydet dugmesi vardir
  // (config.json'a degil kutuphane klasorundeki prompt.templates.json'a yazilir).
  import Icon from '../lib/Icon.svelte';
  import { toast } from '../lib/state.svelte.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import { templates, loadTemplates, saveTemplates } from '../lib/templates.svelte.js';

  let items = $state([]);
  let saved = $state('[]');
  let saving = $state(false);
  const dirty = $derived(JSON.stringify(items) !== saved);
  const invalid = $derived(items.some((item) => !item.name.trim() || !item.text.trim()));

  async function load() {
    await loadTemplates();
    items = templates.items.map((item) => ({ ...item }));
    saved = JSON.stringify(items);
  }
  load();

  function add() {
    items.push({ id: '', name: 'Yeni şablon', text: '' });
  }

  async function remove(index) {
    const ok = await confirm({ title: 'Şablonu sil', message: `"${items[index].name}" silinsin mi? Bu şablonu kullanan sohbetler şablonsuz devam eder.`, ok: 'Sil', danger: true });
    if (ok) items.splice(index, 1);
  }

  async function save() {
    saving = true;
    const result = await saveTemplates($state.snapshot(items));
    saving = false;
    if (Array.isArray(result)) {
      items = result.map((item) => ({ ...item }));
      saved = JSON.stringify(items);
      toast('Sohbet şablonları kaydedildi.', 'ok');
    }
  }
</script>

<section id="sohbet-sablonlari">
  <div class="head">
    <h2>Sohbet şablonları</h2>
    {#if dirty}<span class="unsaved">Kaydedilmedi</span>{/if}
    <span class="grow"></span>
    <button class="btn sm" onclick={add}><Icon name="plus" size={14} />Yeni şablon</button>
    <button class="btn sm primary" onclick={save} disabled={!dirty || invalid || saving}><Icon name="check" size={14} />Kaydet</button>
  </div>
  <p class="hint">Şablon, sohbetlerde modele giden ek talimattır: cevabın biçimi, odağı ve üslubu. Sohbet kutusundaki <Icon name="scroll" size={12} /> düğmesiyle seçilir; koleksiyonda seçim koleksiyona kaydedilir ve koleksiyona özel bir not eklenebilir. Şablonlar atıf ve "uydurma" kurallarını değiştiremez.</p>
  {#each items as item, index}
    <div class="tpl">
      <div class="top">
        <input class="field name" bind:value={item.name} maxlength="60" placeholder="Şablon adı" />
        <button class="icon-btn sm" title="Şablonu sil" onclick={() => remove(index)}><Icon name="trash" size={15} /></button>
      </div>
      <textarea class="field" rows="4" bind:value={item.text} maxlength="4000"
        placeholder="Örn. Tutarları tabloyla ver, her tutarda para birimini ve dönemi yaz…"></textarea>
    </div>
  {:else}
    <p class="empty">Şablon yok. "Yeni şablon" ile ekleyin.</p>
  {/each}
</section>

<style>
  .head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .head h2 { font-size: 20px; font-weight: 700; letter-spacing: -.01em; }
  .grow { flex: 1; }
  .unsaved { color: var(--accent); font-size: 12px; font-weight: 600; }
  .hint { color: var(--dim); font-size: 12px; margin-bottom: 10px; line-height: 1.5; }
  .hint :global(svg) { vertical-align: -2px; }
  .tpl { display: flex; flex-direction: column; gap: 8px; padding: 12px 0; border-bottom: 1px solid var(--outline); }
  .tpl:last-child { border-bottom: 0; }
  .top { display: flex; align-items: center; gap: 8px; }
  .name { width: 320px; font-weight: 600; }
  textarea.field { width: 100%; resize: vertical; min-height: 80px; font: inherit; font-size: 13px; line-height: 1.5; padding: 8px 10px; box-sizing: border-box; }
  .empty { color: var(--dim); font-size: 13px; padding: 8px 0; }
</style>
