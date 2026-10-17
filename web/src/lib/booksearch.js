// Okuyucuda kitap ici arama (F147): book_search.py ile ayni katlama (I/ı/İ/i ayni, buyuk/kucuk harf yok, sorgudaki
// bosluk her bosluk dizisine uyar). Arka uc tum bolumlerde eslesmeleri bulur; burada acik bolumun DOM'unda ayni
// eslesmeler bulunup CSS Custom Highlight API ile vurgulanir (desteklenmiyorsa secimle).
const FOLD = { 'İ': 'i', I: 'i', 'ı': 'i' };

export function fold(text) {
  let out = '';
  for (const char of text) {
    let folded = FOLD[char];
    if (folded === undefined) {
      const lower = char.toLowerCase();
      folded = lower.length === char.length ? lower : char;   // uzunluk degismez: konumlar ozgun metinle ayni
    }
    out += folded;
  }
  return out;
}

export function pattern(query) {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  return new RegExp(words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+'), 'g');
}

// Kok altindaki metindeki eslesmeler -> Range listesi (dugmeler ve .no-tts disarida).
export function findRanges(root, query) {
  const found = pattern(query);
  if (!root || !found) return [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (node.parentElement?.closest('button, .no-tts') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  const nodes = [];
  let text = '';
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    nodes.push({ node, start: text.length });
    text += node.data;
  }
  const locate = (index) => {
    let low = 0, high = nodes.length - 1;
    while (low < high) {
      const mid = (low + high + 1) >> 1;
      if (nodes[mid].start <= index) low = mid; else high = mid - 1;
    }
    return { node: nodes[low].node, offset: index - nodes[low].start };
  };
  const ranges = [];
  for (const match of fold(text).matchAll(found)) {
    if (!match[0].length) continue;
    const a = locate(match.index), b = locate(match.index + match[0].length - 1);
    const range = document.createRange();
    range.setStart(a.node, a.offset);
    range.setEnd(b.node, b.offset + 1);
    ranges.push(range);
  }
  return ranges;
}

// Tum eslesmeleri hafif, `current`i belirgin vurgular ve ona kaydirir (current < 0: yalnizca vurgu).
export function highlight(ranges, current = -1) {
  const supported = typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight !== 'undefined';
  if (supported) {
    CSS.highlights.set('book-search', new Highlight(...ranges));
    if (ranges[current]) CSS.highlights.set('book-search-now', new Highlight(ranges[current]));
    else CSS.highlights.delete('book-search-now');
  }
  const target = ranges[current];
  if (!target) return;
  if (!supported) {
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(target);
  }
  target.startContainer.parentElement?.scrollIntoView({ block: 'center' });
}

export function clearHighlight() {
  if (typeof CSS !== 'undefined' && CSS.highlights) {
    CSS.highlights.delete('book-search');
    CSS.highlights.delete('book-search-now');
  }
}
