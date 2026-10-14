// Model metnini guvenli HTML'e cevirir (chat_render.inline_html ile ayni kurallar):
// kacis, **kalin**, # basliklar, madde imleri, satir sonlari.
const ESCAPE = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ESCAPE[c]);
}

export function inlineHtml(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/^[ \t]*#{1,6}[ \t]+(.+)$/gm, '<b>$1</b>')
    .replace(/^([ \t]*)[-*][ \t]+/gm, '$1• ')
    .replace(/\n/g, '<br>');
}

// Genel sohbet icin blok Markdown: kod bloklari, basliklar, listeler, tablolar, alintilar.
// Baglantilar tiklanamaz metin olarak kalir (pencere baska sayfaya gitmesin).
// `tokens`: metne gomulu \u0001N\u0001 yer tutuculari -> HTML (atif dugmeleri).
function inline(text) {
  const codes = [];
  let html = escapeHtml(text).replace(/`([^`\n]+)`/g, (_m, code) => `\u0002${codes.push(code) - 1}\u0002`);
  html = html
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/__(.+?)__/g, '<b>$1</b>')
    .replace(/(^|[^\w*])\*(?!\s)([^*\n]+?)\*(?!\w)/g, '$1<i>$2</i>')
    .replace(/(^|[^\w])_(?!\s)([^_\n]+?)_(?!\w)/g, '$1<i>$2</i>')
    .replace(/~~(.+?)~~/g, '<s>$1</s>')
    .replace(/\[([^\]\n]+)\]\((https?:[^)\s]+)\)/g, '<span class="link" title="$2">$1</span>')
    .replace(/\[(V\d+[^\]\n]{0,150})\]/g, '<span class="cite raw">$1</span>');
  return html.replace(/\u0002(\d+)\u0002/g, (_m, i) => `<code>${codes[i]}</code>`);
}

const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const cells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());

function blocks(text) {
  const lines = text.split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    let m;
    if ((m = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/))) {
      const level = Math.min(6, m[1].length + 2);
      out.push(`<h${level}>${inline(m[2])}</h${level}>`);
      i++;
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      out.push('<hr>');
      i++;
    } else if (line.includes('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push('<div class="table-wrap"><table><thead><tr>' + head.map((c) => `<th>${inline(c)}</th>`).join('')
        + '</tr></thead><tbody>' + rows.map((r) => '<tr>' + r.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('')
        + '</tbody></table></div>');
    } else if (/^\s*>/.test(line)) {
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ''));
      out.push(`<blockquote>${blocks(quote.join('\n'))}</blockquote>`);
    } else if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      // Liste: girintiye gore ic ice; maddenin devam satirlari maddeye eklenir.
      const items = [];
      while (i < lines.length && lines[i].trim()) {
        const item = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
        if (item) items.push({ indent: item[1].replace(/\t/g, '    ').length, ordered: /\d/.test(item[2]), text: item[3] });
        else if (items.length) items[items.length - 1].text += '\n' + lines[i].trim();
        i++;
        if (i < lines.length && !lines[i].trim() && i + 1 < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i + 1])) i++;
      }
      out.push(list(items, 0, items.length));
    } else {
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^\s*(#{1,6}\s|>|([-*+]|\d+[.)])\s+)/.test(lines[i])
        && !(lines[i].includes('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]))) para.push(lines[i++]);
      if (!para.length) para.push(lines[i++]);
      out.push(`<p>${para.map(inline).join('<br>')}</p>`);
    }
  }
  return out.join('');
}

function list(items, from, to) {
  const base = items[from].indent;
  const tag = items[from].ordered ? 'ol' : 'ul';
  let html = `<${tag}>`;
  let i = from;
  while (i < to) {
    let j = i + 1;
    while (j < to && items[j].indent > base) j++;
    html += `<li>${items[i].text.split('\n').map(inline).join('<br>')}${j > i + 1 ? list(items, i + 1, j) : ''}</li>`;
    i = j;
  }
  return html + `</${tag}>`;
}

export function richHtml(text, tokens = []) {
  const parts = String(text ?? '').replace(/\r\n/g, '\n').split(/^```[^\n]*\n?/m);
  let html = '';
  // Cift indeksler duz metin, tek indeksler kod blogu (kapanmamis son blok da kod sayilir).
  parts.forEach((part, index) => {
    if (index % 2) html += `<pre><code>${escapeHtml(part.replace(/\n$/, ''))}</code></pre>`;
    else html += blocks(part);
  });
  return html.replace(/\u0001(\d+)\u0001/g, (_m, i) => tokens[i] ?? '');
}
