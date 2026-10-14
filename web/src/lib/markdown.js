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
