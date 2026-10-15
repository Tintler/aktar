// Sohbet sablonlari (F104): Ayarlar'da duzenlenen ek talimatlar (chat_templates.py).
// Koleksiyon sohbeti koleksiyonun sablonunu kullanir (koleksiyon dosyasinda); genel, belge ve
// video sohbetinde secim tarayici deposunda hatirlanir.
import { call } from './api.js';
import { act } from './state.svelte.js';

const KEY = 'aktar.templates';

export const templates = $state({ items: [], loaded: false, choice: readChoice() });

function readChoice() {
  try { return JSON.parse(localStorage.getItem(KEY) ?? '{}') || {}; } catch { return {}; }
}

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
  const id = templates.choice[kind] ?? '';
  return templateName(id) ? id : '';
}

export function setTemplateFor(kind, id) {
  templates.choice = { ...templates.choice, [kind]: id || '' };
  try { localStorage.setItem(KEY, JSON.stringify(templates.choice)); } catch { /* depo yok */ }
}
