// Temalar (Deeverse bicimi): paleti CSS degiskenlerine yazar. "system" secimi isletim
// sisteminin acik/koyu tercihini izler.

const media = window.matchMedia('(prefers-color-scheme: light)');

export const SYSTEM = { id: 'system', name: 'Sistem' };

// Paletteki her renk --ad olarak (alt cizgi tire olur); ek olarak base'e gore "ok" (yesil).
export function applyPalette(base, palette) {
  const root = document.documentElement;
  for (const [name, value] of Object.entries(palette)) root.style.setProperty('--' + name.replace(/_/g, '-'), value);
  root.style.setProperty('--ok', base === 'light' ? '#15803d' : '#4ade80');
  root.style.colorScheme = base;
  root.dataset.base = base;
}

// themes: bridge.list_themes() listesi; id: 'system' | 'dark' | 'light' | 'file:<ad>.json'
export function resolveTheme(id, themes) {
  if (id === 'system' || !id) id = media.matches ? 'light' : 'dark';
  const found = themes.find((t) => t.id === id && !t.error);
  return found ?? themes.find((t) => t.id === 'dark');
}

let current = { id: 'system', themes: [] };

export function applyTheme(id, themes) {
  current = { id, themes };
  const theme = resolveTheme(id, themes);
  if (theme) applyPalette(theme.base, theme.palette);
}

media.addEventListener('change', () => {
  if (current.id === 'system') applyTheme(current.id, current.themes);
});
