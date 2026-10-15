// Not ve vurgu (F113): acik videonun/belgenin notlari. Oynatici ve belge goruntuleyici paylasir;
// arka uc (bridge_document.notes_*) her degisiklikte guncel listeyi dondurur.
import { act } from './state.svelte.js';

// draft: {at, quote} yazilmakta olan yeni not (panelde yazma alani acilir)
export const notes = $state({ path: '', items: [], open: false, draft: null });

export function startNote(at, quote = '') {
  notes.draft = { at, quote, n: Date.now() };
  notes.open = true;
}

export async function loadNotes(path) {
  if (notes.path === path) return;
  notes.path = path;
  notes.items = [];
  notes.draft = null;
  const items = await act('notes_list', path);
  if (Array.isArray(items) && notes.path === path) notes.items = items;
}

function apply(path, items) {
  if (Array.isArray(items) && notes.path === path) notes.items = items;
  return Array.isArray(items);
}

export async function addNote(path, at, text, quote = '', color = null) {
  const ok = apply(path, await act('notes_add', path, at, text, quote, color));
  if (ok) notes.open = true;
  return ok;
}

export async function updateNote(path, id, text = null, color = null) {
  return apply(path, await act('notes_update', path, id, text, color));
}

export async function deleteNote(path, id) {
  return apply(path, await act('notes_delete', path, id));
}

export const NOTE_COLORS = { yellow: '#f5d84a', green: '#7ed67a', blue: '#6fb4f5', pink: '#f590c0' };
