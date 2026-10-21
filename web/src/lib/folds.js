// F179: Ayarlar'daki acilir/kapanir bolumler. Son durum ui.json'da (settings_open: {anahtar: acik}) saklanir.
import { app, savePref } from './state.svelte.js';

export const isOpen = (key, fallback = true) => app.prefs.settings_open?.[key] ?? fallback;

export function toggleOpen(key, fallback = true) {
  savePref({ settings_open: { ...(app.prefs.settings_open ?? {}), [key]: !isOpen(key, fallback) } });
}
