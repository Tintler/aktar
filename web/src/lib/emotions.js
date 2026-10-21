// F170: Drama 3 duygu etiketleri kitapliktan, butun kitap icin bir kez olusturulur (okurken degil: ses motoru ile
// dil modeli ayni anda bellegi dolduruyordu). Cumleler okuyucunun bolmesiyle (sentences.js + ayarlardaki tirnak
// secenekleri) cikarilir; boylece okurken her cumlenin etiketi metnine gore bulunur.
import { call } from './api.js';
import { segment, QUOTE_DEFAULTS } from './sentences.js';

export async function bookSections(bookId, split = {}) {
  const count = await call('shelf_section_count', bookId);
  if (typeof count !== 'number') throw new Error(count?.error ?? 'Kitap açılamadı.');
  const sections = [];
  for (let number = 0; number < count; number++) {
    const result = await call('reader_section', bookId, number);
    if (!result || result.error) continue;
    const holder = document.createElement('div');
    holder.innerHTML = result.html;
    const cut = segment(holder, { ...QUOTE_DEFAULTS, ...split });
    if (cut.sentences.length) sections.push({ sentences: cut.sentences, breaks: [...cut.breaks] });
  }
  return sections;
}
