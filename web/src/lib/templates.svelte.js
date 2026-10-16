// Sohbet sablonlari (F104): Ayarlar'da duzenlenen ek talimatlar (chat_templates.py).
// Koleksiyon sohbeti koleksiyonun sablonunu kullanir (koleksiyon dosyasinda); genel, belge ve
// video sohbetinde secim ui.json'da hatirlanir (app.prefs.template_choice).
import { call } from './api.js';
import { act, app, savePref } from './state.svelte.js';

export const templates = $state({ items: [], loaded: false });

export async function loadTemplates() {
  const result = await call('templates_list');
  if (Array.isArray(result)) templates.items = result;
  templates.loaded = true;
}

export async function saveTemplates(items) {
  const result = await act('templates_save', items);
  if (Array.isArray(result)) templates.items = result;
  return result;
}

export const templateName = (id) => templates.items.find((item) => item.id === id)?.name ?? '';

// kind: 'assistant' | 'doc' | 'video'. Silinmis sablon secili kaldiysa '' doner.
export function templateFor(kind) {
  const id = app.prefs.template_choice?.[kind] ?? '';
  return templateName(id) ? id : '';
}

export function setTemplateFor(kind, id) {
  savePref({ template_choice: { ...(app.prefs.template_choice ?? {}), [kind]: id || '' } });
}
