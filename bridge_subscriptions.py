"""Abonelikler sayfasinin (F106) arka ucu; is mantigi subscriptions.py'de."""
from __future__ import annotations

import subscriptions


class SubscriptionsMixin:
    def subs_state(self):
        return subscriptions.view()

    def subs_save(self, item):
        try:
            saved = subscriptions.upsert(item)
        except (ValueError, OSError) as error:
            return {'error': str(error)}
        self._log(f'Abonelik kaydedildi: {saved["name"]}')
        return subscriptions.view()

    def subs_logo(self, path=None):
        """Logo gorseli: yol verilmezse dosya penceresi acilir. {'logo': data URL}; vazgecilirse None."""
        path = path or self._dialog('open_file', 'Logo seç', ('Görseller (' + ';'.join(subscriptions.LOGO_TYPES) + ')',))
        if not path:
            return None
        try:
            return {'logo': subscriptions.logo_from_file(path)}
        except ValueError as error:
            return {'error': str(error)}
        except OSError as error:
            return {'error': f'Görsel açılamadı: {path} ({error.strerror or error})'}

    def subs_delete(self, ident):
        try:
            removed = subscriptions.remove(str(ident or ''))
        except OSError as error:
            return {'error': str(error)}
        if not removed:
            return {'error': 'Kayıt bulunamadı.'}
        return subscriptions.view()
