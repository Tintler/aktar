from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import library  # noqa: E402
import subscriptions  # noqa: E402


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(Path(self.temp.name) / 'store')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_clean_validates_and_normalises(self):
        item = subscriptions.clean({'id': '../x', 'name': '  Netflix  ', 'amount': '229,99', 'currency': 'XYZ',
                                    'cycle': 'daily', 'status': '?', 'renewal_date': '2026-13-01',
                                    'card_last4': '1234 5678 9012 3456', 'method': 'debit'})
        self.assertEqual(item['name'], 'Netflix')
        self.assertEqual(item['amount'], 229.99)
        self.assertEqual((item['currency'], item['cycle'], item['status']), ('TRY', 'monthly', 'active'))
        self.assertEqual(item['renewal_date'], '')
        self.assertEqual(item['card_last4'], '3456')
        self.assertEqual(item['method'], 'debit')
        self.assertNotEqual(item['id'], '../x')
        self.assertIsNone(subscriptions.clean({'name': '', 'amount': 5}))
        self.assertIsNone(subscriptions.clean({'name': 'A', 'amount': 'abc'}))
        self.assertIsNone(subscriptions.clean({'name': 'A', 'amount': -1}))

    def test_upsert_remove_and_not_a_collection(self):
        saved = subscriptions.upsert({'name': 'Spotify', 'amount': 99})
        subscriptions.upsert(dict(saved, amount=120))
        self.assertEqual([(i['name'], i['amount']) for i in subscriptions.load()], [('Spotify', 120)])
        self.assertEqual(library.list_collections(), {})
        self.assertTrue(subscriptions.remove(saved['id']))
        self.assertFalse(subscriptions.remove(saved['id']))
        self.assertEqual(subscriptions.load(), [])
        with self.assertRaises(ValueError):
            subscriptions.upsert({'name': ' '})

    def test_logo_resized_kept_and_removed(self):
        import base64
        import io
        from PIL import Image
        source = Image.new('RGBA', (600, 400), (0, 0, 0, 0))
        source.paste((229, 9, 20, 255), (100, 50, 500, 350))  # saydam kenar kirpilir
        buffer = io.BytesIO()
        source.save(buffer, 'PNG')
        url = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        saved = subscriptions.upsert({'name': 'Netflix', 'amount': 1, 'logo': url})
        with Image.open(subscriptions.logo_path(saved['id'])) as logo:
            self.assertEqual(logo.size, (128, 96))
        self.assertNotIn('logo', subscriptions.load()[0])
        subscriptions.upsert(dict(saved, amount=2))  # logo alani yok: dokunulmaz
        self.assertTrue(subscriptions.view()['items'][0]['logo'].startswith('data:image/png;base64,'))
        subscriptions.upsert(dict(saved, logo=''))
        self.assertEqual(subscriptions.view()['items'][0]['logo'], '')
        subscriptions.upsert(dict(saved, logo=url))
        subscriptions.remove(saved['id'])
        self.assertFalse(subscriptions.logo_path(saved['id']).exists())
        with self.assertRaises(ValueError):
            subscriptions.upsert({'name': 'A', 'amount': 1, 'logo': 'data:image/png;base64,AAAA'})
        with self.assertRaises(ValueError):
            subscriptions.upsert({'name': 'A', 'amount': 1, 'logo': 'http://example.com/a.png'})

    def test_next_due_rolls_from_anchor_without_drift(self):
        item = subscriptions.clean({'name': 'A', 'amount': 1, 'renewal_date': '2026-01-31'})
        self.assertEqual(subscriptions.next_due(item, date(2026, 2, 10)), date(2026, 2, 28))
        self.assertEqual(subscriptions.next_due(item, date(2026, 3, 1)), date(2026, 3, 31))
        yearly = dict(item, cycle='yearly', renewal_date='2024-02-29')
        self.assertEqual(subscriptions.next_due(yearly, date(2026, 10, 15)), date(2027, 2, 28))
        weekly = dict(item, cycle='weekly', renewal_date='2026-10-01')
        self.assertEqual(subscriptions.next_due(weekly, date(2026, 10, 15)), date(2026, 10, 15))
        self.assertIsNone(subscriptions.next_due(dict(item, status='cancelled'), date(2026, 2, 1)))
        self.assertIsNone(subscriptions.next_due(dict(item, end_date='2026-02-15'), date(2026, 2, 10)))
        once = dict(item, kind='once', renewal_date='2026-10-20')
        self.assertEqual(subscriptions.next_due(once, date(2026, 10, 15)), date(2026, 10, 20))
        self.assertIsNone(subscriptions.next_due(once, date(2026, 10, 21)))

    def test_view_summary(self):
        subscriptions.upsert({'name': 'Netflix', 'amount': 230, 'renewal_date': '2026-10-20', 'bank': 'Garanti'})
        subscriptions.upsert({'name': 'iCloud', 'amount': 120, 'currency': 'USD', 'cycle': 'yearly',
                              'renewal_date': '2027-01-01', 'method': 'debit', 'bank': 'Akbank'})
        subscriptions.upsert({'name': 'Elektrik', 'amount': 800, 'status': 'paused', 'renewal_date': '2026-10-18'})
        subscriptions.upsert({'name': 'Kurs', 'amount': 1500, 'kind': 'once', 'renewal_date': '2026-11-01'})
        result = subscriptions.view(date(2026, 10, 15))
        summary = result['summary']
        self.assertEqual(summary['monthly'], {'TRY': 230.0, 'USD': 10.0})
        self.assertEqual(summary['yearly'], {'TRY': 2760.0, 'USD': 120.0})
        self.assertEqual(summary['upcoming'], {'TRY': 1730.0})
        self.assertEqual(summary['active'], 3)
        self.assertEqual([row['name'] for row in result['items']], ['Netflix', 'Kurs', 'iCloud', 'Elektrik'])
        self.assertEqual(result['items'][3]['last_date'], '2026-10-18')
        self.assertEqual(result['items'][0]['days_left'], 5)
        self.assertEqual([(g['bank'], g['method']) for g in summary['by_payment']],
                         [('Garanti', 'credit'), ('Akbank', 'debit')])

    def test_inactive_rows_sorted_by_their_date_newest_first(self):
        subscriptions.upsert({'name': 'Tarihsiz', 'amount': 1, 'status': 'paused'})
        subscriptions.upsert({'name': 'Claude Ağustos', 'amount': 1, 'kind': 'once', 'renewal_date': '2026-08-14'})
        subscriptions.upsert({'name': 'Claude Eylül', 'amount': 1, 'kind': 'once', 'renewal_date': '2026-09-14'})
        subscriptions.upsert({'name': 'VPN', 'amount': 1, 'status': 'cancelled', 'renewal_date': '2026-05-01',
                              'end_date': '2026-09-01'})
        subscriptions.upsert({'name': 'Netflix', 'amount': 1, 'renewal_date': '2026-10-20'})
        result = subscriptions.view(date(2026, 10, 15))
        self.assertEqual([row['name'] for row in result['items']],
                         ['Netflix', 'Claude Eylül', 'VPN', 'Claude Ağustos', 'Tarihsiz'])
        self.assertEqual(result['items'][2]['last_date'], '2026-09-01')


def row(day, amount, description, merchant='', number='', kind='bill', direction='out', account='bank_account'):
    return {'date': day, 'amount': amount, 'description': description, 'merchant': merchant, 'subscriber_no': number,
            'type': kind, 'direction': direction, 'account': account, 'file': 'ekstre.pdf'}


ROWS = [
    row('2026-08-02', 612.4, 'Ödeme, Sakarya Elektrik (SEPAŞ) faturası, abone no : 100104418533', 'SEPAŞ', '100104418533'),
    row('2026-09-02', 504.0, 'Ödeme, Sakarya Elektrik (SEPAŞ) faturası, abone no : 100104418533', 'SEPAŞ', '100104418533'),
    row('2026-09-14', 175.0, 'Ödeme, PALGAZ - Gebze Tüketim faturası, abone no : 16170', 'PALGAZ', '16170'),
    row('2026-09-08', 3104.15, 'Ödeme, Enpara.com kredi kartı ödemesi, Cem Acar', 'Enpara.com', kind='other'),
    row('2026-09-08', 8851.0, 'Gelen Transfer', kind='transfer', direction='in'),
    row('2026-09-19', 316.05, 'Diğer, MIGROS-GEBZE MUTLUKENT', 'Migros', kind='purchase'),
    row('2026-08-07', 99.99, 'DEEZER SA DEEZER', 'Deezer', kind='purchase', account='credit_card'),
    row('2026-09-07', 99.99, 'DEEZER SA DEEZER', 'Deezer', kind='purchase', account='credit_card'),
]


class StatementMatchTests(unittest.TestCase):
    """F110: ekstre satirlarinin kayitlara baglanmasi ve oneriler."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(Path(self.temp.name) / 'store')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_variable_bill_uses_average_of_recent_payments(self):
        payments = [{'date': f'2026-0{month}-02', 'amount': amount}
                    for month, amount in zip(range(1, 10), (900, 800, 700, 100, 200, 300, 400, 500, 600))]
        saved = subscriptions.upsert({'name': 'Elektrik', 'amount': 0, 'variable': True,
                                      'payments': payments + [payments[-1], {'date': 'x', 'amount': 5}]})
        self.assertEqual(len(saved['payments']), 9)  # tekrar eden ve tarihsiz odeme atilir
        self.assertEqual(subscriptions.estimate(saved), 350.0)  # son 6: 100..600
        self.assertEqual(subscriptions.monthly_cost(saved), 350.0)
        row_ = subscriptions.view(date(2026, 10, 15))['items'][0]
        self.assertEqual((row_['estimate'], row_['low'], row_['high']), (350.0, 100.0, 900.0))
        self.assertEqual(row_['last_payment']['amount'], 600.0)
        fixed = dict(saved, variable=False, amount=42)
        self.assertEqual(subscriptions.estimate(fixed), 42)

    def test_sync_links_payments_and_moves_anchor(self):
        elektrik = subscriptions.upsert({'name': 'Elektrik', 'amount': 500, 'variable': True, 'match': '100104418533',
                                         'renewal_date': '2026-07-01'})
        gaz = subscriptions.upsert({'name': 'Doğalgaz', 'amount': 200, 'match': '1617'})  # 16170'e uymaz
        self.assertEqual(subscriptions.sync(ROWS), 1)
        items = {item['id']: item for item in subscriptions.load()}
        self.assertEqual([p['amount'] for p in items[elektrik['id']]['payments']], [612.4, 504.0])
        self.assertEqual(items[elektrik['id']]['renewal_date'], '2026-09-02')
        self.assertEqual(items[gaz['id']]['payments'], [])
        self.assertEqual(subscriptions.sync(ROWS), 0)  # ayni satirlar ikinci kez eklenmez

    def test_suggestions_group_bills_and_repeated_payments(self):
        subscriptions.upsert({'name': 'Elektrik', 'amount': 500, 'match': 'SEPAŞ'})
        found = {item['key']: item for item in subscriptions.suggestions(ROWS)}
        # Elektrik kayda uyar; kart odemesi, transfer ve tek seferlik market onerilmez.
        self.assertEqual(set(found), {'no:16170', 'm:deezer'})
        deezer = found['m:deezer']
        self.assertEqual((deezer['count'], deezer['months'], deezer['average'], deezer['variable']), (2, 2, 99.99, False))
        self.assertEqual((deezer['method'], deezer['category'], deezer['day']), ('credit', '', 7))
        self.assertEqual((found['no:16170']['category'], found['no:16170']['match']), ('Fatura', '16170'))
        self.assertEqual([item['key'] for item in subscriptions.suggestions(ROWS, ignored=['m:deezer'])], ['no:16170'])

    def test_accept_link_and_ignore(self):
        suggestion = next(item for item in subscriptions.suggestions(ROWS) if item['key'] == 'no:100104418533')
        self.assertTrue(suggestion['variable'])
        saved = subscriptions.accept(suggestion)
        self.assertEqual((saved['name'], saved['match'], saved['method'], saved['amount']),
                         ('SEPAŞ', '100104418533', 'transfer', 558.2))
        self.assertEqual((saved['renewal_date'], saved['start_date'], saved['card']),
                         ('2026-09-02', '2026-08-02', 'Abone no 100104418533'))
        self.assertNotIn('no:100104418533', [item['key'] for item in subscriptions.suggestions(ROWS)])

        music = subscriptions.upsert({'name': 'Müzik', 'amount': 99.99, 'match': 'Spotify'})
        deezer = next(item for item in subscriptions.suggestions(ROWS) if item['key'] == 'm:deezer')
        linked = subscriptions.link(deezer, music['id'])
        self.assertEqual((linked['match'], len(linked['payments']), linked['renewal_date']),
                         ('Spotify, Deezer', 2, '2026-09-07'))

        subscriptions.ignore('no:16170')
        self.assertEqual(subscriptions.settings()['ignored'], ['no:16170'])
        subscriptions.upsert({'name': 'Yeni', 'amount': 1})  # kayit yazmak ayarlari silmez
        self.assertEqual(subscriptions.settings()['ignored'], ['no:16170'])
        subscriptions.ignore('no:16170', undo=True)
        self.assertEqual(subscriptions.settings()['ignored'], [])


class AlertTests(unittest.TestCase):
    """F114: zam ve yuksek fatura uyarilari."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(Path(self.temp.name) / 'store')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)
        self.today = date(2026, 10, 15)

    @staticmethod
    def pays(*values):
        return [{'date': day, 'amount': amount} for day, amount in values]

    def test_price_change_and_apply(self):
        netflix = subscriptions.upsert({'name': 'Netflix', 'amount': 229.99, 'payments': self.pays(
            ('2026-08-08', 229.99), ('2026-09-08', 229.99), ('2026-10-08', 279.99))})
        found = subscriptions.alerts(today=self.today)
        self.assertEqual([(a['kind'], a['reference'], a['amount'], a['ratio']) for a in found],
                         [('price_up', 229.99, 279.99, 0.2174)])
        self.assertIn('229,99 TL → 279,99 TL (+%22)', subscriptions.alert_text(found[0]))
        subscriptions.apply_price(netflix['id'])
        self.assertEqual(subscriptions.load()[0]['amount'], 279.99)
        self.assertEqual(subscriptions.alerts(today=self.today), [])  # tutar guncellenince uyari kalkar

    def test_high_variable_bill_dismiss_and_old_payments(self):
        gas = subscriptions.upsert({'name': 'Doğalgaz', 'amount': 0, 'variable': True, 'payments': self.pays(
            ('2026-07-14', 400), ('2026-08-14', 420), ('2026-09-14', 440), ('2026-10-14', 600))})
        subscriptions.upsert({'name': 'Su', 'amount': 0, 'variable': True, 'payments': self.pays(
            ('2026-08-10', 100), ('2026-09-10', 110), ('2026-10-10', 125))})  # %19: uyarilmaz
        subscriptions.upsert({'name': 'Eski', 'amount': 10, 'payments': self.pays(('2026-01-01', 10), ('2026-02-01', 20))})
        subscriptions.upsert({'name': 'Durdu', 'amount': 10, 'status': 'paused', 'payments': self.pays(
            ('2026-09-01', 10), ('2026-10-01', 20))})
        found = subscriptions.alerts(today=self.today)
        self.assertEqual([(a['id'], a['kind'], a['reference']) for a in found], [(gas['id'], 'high', 420.0)])
        self.assertIn('ortalamanın %43 üstünde', subscriptions.alert_text(found[0]))
        subscriptions.dismiss(found[0]['key'])
        self.assertEqual(subscriptions.alerts(today=self.today), [])
        self.assertEqual(subscriptions.view(self.today)['alerts'], [])
        # Yeni bir yuksek odeme gelince uyari yeniden cikar.
        items = subscriptions.load()
        gas = next(item for item in items if item['name'] == 'Doğalgaz')
        subscriptions.upsert(dict(gas, payments=gas['payments'] + [{'date': '2026-10-15', 'amount': 700}]))
        self.assertEqual(len(subscriptions.alerts(today=self.today)), 1)

    def test_auto_setting_defaults_on_and_persists(self):
        self.assertTrue(subscriptions.settings()['auto'])
        subscriptions.save_settings(auto=False)
        subscriptions.upsert({'name': 'X', 'amount': 1})
        self.assertFalse(subscriptions.settings()['auto'])


if __name__ == '__main__':
    unittest.main()
