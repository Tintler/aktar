from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        self.assertEqual(result['items'][0]['days_left'], 5)
        self.assertEqual([(g['bank'], g['method']) for g in summary['by_payment']],
                         [('Garanti', 'credit'), ('Akbank', 'debit')])


if __name__ == '__main__':
    unittest.main()
