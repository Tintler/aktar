// Tam ekran okuyucunun (FocusReader) renk ciftleri; sesli kitap videosu (F208) da ayni listeyi kullanir.
// paper: okuyucunun sayfa rengi; digerleri uzaktan okumaya uygun sabit ciftler.
export const FOCUS_COLORS = {
  paper: null,
  night: { bg: '#000000', ink: '#f2f2f2', label: 'Gece' },
  amber: { bg: '#000000', ink: '#ffd34d', label: 'Siyah üstüne sarı' },
  warm: { bg: '#1b1612', ink: '#f1d9b0', label: 'Sıcak koyu' },
  navy: { bg: '#0f1b2d', ink: '#e4ecf7', label: 'Lacivert' },
  green: { bg: '#0d1f17', ink: '#cfeedd', label: 'Yeşil' },
  sepia: { bg: '#f4ecd8', ink: '#3b2f1e', label: 'Sepya' },
  light: { bg: '#ffffff', ink: '#111111', label: 'Beyaz' },
  contrast: { bg: '#ffff00', ink: '#000000', label: 'Sarı üstüne siyah' },
};

// paper null ise (tema rengi) temanin panel ve yazi renkleri okunur.
export function resolvePaper(paper) {
  if (paper) return { bg: paper.bg, ink: paper.ink };
  const style = getComputedStyle(document.documentElement);
  return { bg: style.getPropertyValue('--panel').trim() || '#111114', ink: style.getPropertyValue('--text').trim() || '#e8e8ea' };
}
