<script>
  // Sohbet sablonu secici (F104): dusunme dugmesinin yaninda. kind: 'collection' | 'assistant' | 'doc' | 'video'.
  // Koleksiyonda secim ve not koleksiyona yazilir; digerlerinde tarayici deposunda hatirlanir.
  import Icon from '../lib/Icon.svelte';
  import { app, act, go } from '../lib/state.svelte.js';
  import { openMenu } from '../lib/menu.svelte.js';
  import { prompt } from '../lib/confirm.svelte.js';
  import { templates, loadTemplates, templateFor, setTemplateFor, templateName } from '../lib/templates.svelte.js';

  let { kind, label = false, disabled = false } = $props();

  if (!templates.loaded) loadTemplates();

  const collection = $derived(kind === 'collection');
  const current = $derived(collection ? (templateName(app.chat?.template) ? app.chat.template : '') : templateFor(kind));
  const name = $derived(templateName(current));
  const note = $derived(collection ? app.chat?.template_note ?? '' : '');

  async function pick(id) {
    if (!collection) return setTemplateFor(kind, id);
    const state = await act('chat_set_template', id, null);
    if (state) app.chat = state;
  }

  async function editNote() {
    const value = await prompt({
      title: 'Koleksiyon notu',
      message: 'Bu koleksiyonun her sorusunda modele iletilir (ör. "Tutarlar TL; aylık kart ekstreleri ve fon raporları"). Boş bırakılırsa not kalkar.',
      value: note, multiline: true, ok: 'Kaydet',
    });
    if (value === null) return;
    const state = await act('chat_set_template', null, value);
    if (state) app.chat = state;
  }

  function editTemplates() {
    go('settings');
    setTimeout(() => document.getElementById('sohbet-sablonlari')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80);
  }

  async function open(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!templates.loaded) await loadTemplates();
    const items = [
      { label: 'Şablon yok', icon: current ? null : 'check', action: () => pick('') },
      ...templates.items.map((item) => ({ label: item.name, icon: item.id === current ? 'check' : null, action: () => pick(item.id) })),
      'sep',
    ];
    if (collection) items.push({ label: note ? 'Koleksiyon notunu düzenle…' : 'Koleksiyon notu ekle…', icon: 'pencil', action: editNote });
    items.push({ label: 'Şablonları düzenle…', icon: 'settings', action: editTemplates });
    openMenu({ preventDefault() {}, stopPropagation() {}, clientX: rect.left, clientY: rect.top - 8 }, items);
  }

  const title = $derived((name ? `Sohbet şablonu: ${name}` : 'Sohbet şablonu seçilmedi')
    + (note ? `\nKoleksiyon notu: ${note}` : '') + '\nŞablon, modelin cevap biçimini ve odağını belirler.');
</script>

<button type="button" class="tpl" class:on={!!name || !!note} class:label {disabled} {title} onclick={open}>
  <!-- dar sohbet kutularinda yalnizca simge (secili sablon yesil yanar; adi ipucunda) -->
  <Icon name="scroll" size={16} />{#if label}<span class="ellipsis">{name || (note ? 'Not' : 'Şablon')}</span>{/if}
</button>

<style>
  .tpl { flex: 0 1 auto; min-width: 30px; max-width: 150px; height: 30px; padding: 0 7px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    color: var(--dim); font-size: 12.5px; font-weight: 600; border: 1px solid transparent; transition: color .15s, background .15s, border-color .15s; }
  .tpl:not(:disabled):hover { color: var(--text); background: var(--surface-active); }
  .tpl.label { padding: 0 11px 0 9px; border-color: var(--outline); }
  .tpl :global(svg) { flex: none; }
  .tpl.on { color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); border-color: color-mix(in srgb, var(--accent) 40%, transparent); }
  .ellipsis { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
