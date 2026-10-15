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

    def subs_delete(self, ident):
        try:
            removed = subscriptions.remove(str(ident or ''))
        except OSError as error:
            return {'error': str(error)}
        if not removed:
            return {'error': 'Kayıt bulunamadı.'}
        return subscriptions.view()
