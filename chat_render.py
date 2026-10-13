"""Sohbet gorunumu ortak parcalari: koleksiyon sohbeti (library_panel) ve tek belge
sohbeti (doc_view) ayni HTML cizimini ve soru isci sinifini kullanir."""
from __future__ import annotations

import html
import re

from PySide6.QtCore import QObject, Signal, Slot

from gui import THEME

CITE_BG = '#18210a'  # atif rozeti zemini (tasarim taslagindaki koyu lime)


def inline_html(text):
    """Model metnini guvenli HTML'e cevirir: kacis, **kalin**, basliklar, madde imleri."""
    value = html.escape(text, quote=False)
    value = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', value)
    value = re.sub(r'(?m)^[ \t]*#{1,6}[ \t]+(.+)$', r'<b>\1</b>', value)
    value = re.sub(r'(?m)^([ \t]*)[-*][ \t]+', r'\1• ', value)
    return value.replace('\n', '<br>')


def chat_html(entries, targets, single=False):
    """Sohbet HTML'i. Atiflar 'cite:<n>' baglantisidir; n -> targets[n] (dosya yolu,
    saniye/sayfa). `targets` her cizimde yeniden doldurulur. `single`: tek dosya
    sohbeti (etiketlerde 'V1 ' oneki ve 'Kaynaklar' satiri yok)."""
    targets.clear()

    def link(path, start, label):
        if single:
            label = label.split(' ', 1)[-1]
        targets.append((path, start))
        return ('<a href="cite:%d" style="color:%s; text-decoration:none; font-weight:600;">'
                '<span style="background-color:%s;">&nbsp;%s&nbsp;</span></a>'
                % (len(targets) - 1, THEME['accent'], CITE_BG, html.escape(label)))

    blocks = []
    for kind, value in entries:
        if kind == 'user':
            blocks.append(
                '<table width="100%" cellspacing="0" cellpadding="0" style="margin:10px 0 6px 0;">'
                '<tr><td align="right"><table cellspacing="0" cellpadding="9" bgcolor="{bg}">'
                '<tr><td>{text}</td></tr></table></td></tr></table>'.format(
                    bg=THEME['panel_alt'], text=html.escape(value)))
        elif kind == 'assistant':
            body = []
            for part_kind, part in value['parts']:
                if part_kind == 'cite':
                    body.append(' '.join(link(cite['video'], cite['start'], cite['label'])
                                         for cite in part))
                else:
                    body.append(inline_html(part))
            blocks.append('<p style="margin:6px 0 6px 0;">' + ''.join(body) + '</p>')
            if value['sources'] and not single:
                sources = ' &nbsp; '.join(
                    link(item['video'], item['start'], item['label'])
                    + ' %s <span style="color:%s;">(%d)</span>' % (
                        html.escape(item['title']), THEME['muted'], item['count'])
                    for item in value['sources'])
                blocks.append('<p style="margin:0 0 14px 0; color:%s; font-size:12px;">'
                              'Kaynaklar: %s</p>' % (THEME['secondary'], sources))
        elif kind == 'overview':
            topics = ' · '.join(html.escape(topic) for topic in value.get('topics') or [])
            questions = ''.join(
                '<a href="ask:%d" style="color:%s; text-decoration:none;">→ %s</a><br>'
                % (index, THEME['accent'], html.escape(question))
                for index, question in enumerate(value.get('questions') or []))
            blocks.append(
                '<table width="100%%" cellspacing="0" cellpadding="10" bgcolor="%s" '
                'style="margin:4px 0 10px 0;"><tr><td>'
                '<span style="color:%s; font-size:11px; font-weight:600;">KOLEKSİYON ÖZETİ · '
                '%d video</span><br>%s%s%s</td></tr></table>'
                % (THEME['panel'], THEME['muted'], len(value.get('videos') or []),
                   '<span style="color:%s;">%s</span>' % (THEME['secondary'],
                                                         html.escape(value['summary'])),
                   ('<br><br><span style="color:%s;">Konular: %s</span>' % (THEME['muted'], topics)
                    if topics else ''),
                   ('<br><br>' + questions) if questions else ''))
        elif kind == 'error':
            blocks.append('<p style="margin:6px 0 12px 0; color:%s;">%s</p>'
                          % (THEME['secondary'], html.escape(value)))
        else:  # note / pending
            blocks.append('<p style="margin:6px 0 12px 0; color:%s;"><i>%s</i></p>'
                          % (THEME['muted'], html.escape(value)))
    return ''.join(blocks)


class AskWorker(QObject):
    """Koleksiyon sorusu: arama + model cevabi arka planda."""

    finished = Signal(str, object, str)  # (koleksiyon slug, tur, hata)

    def __init__(self, slug, session, question):
        super().__init__()
        self.slug = slug
        self.session = session
        self.question = question

    @Slot()
    def run(self):
        try:
            turn = self.session.ask(self.question)
        except Exception as error:  # baglanti/model hatasi sohbete yazilir
            self.finished.emit(self.slug, None, str(error))
            return
        self.finished.emit(self.slug, turn, '')
