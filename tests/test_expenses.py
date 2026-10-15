from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import expenses  # noqa: E402


def row(date, amount, type='purchase', merchant='', description='', direction='out', **extra):
    return dict(date=date, amount=amount, type=type, merchant=merchant, description=description or merchant,
                direction=direction, subscriber_no='', account='credit_card', file='e.pdf', **extra)


ROWS = [
    row('2026-08-01', 100, merchant='Migros'),
    row('2026-08-15', 400, 'bill', 'Enerjisa'),
    row('2026-08-20', 5000, 'card_payment', description='Kredi karti odemesi'),
    row('2026-08-21', 2000, 'transfer', description='Kendi hesabima'),
    row('2026-08-22', 9000, 'other', description='Maas', direction='in'),
    row('2026-08-25', 50, 'other', description='CEP SUBESI EFT'),
    row('2026-09-01', 150, merchant='Migros'),
    row('2026-09-03', 60, merchant='Migros'),
    row('2026-09-07', 99.99, merchant='DEEZER'),
    row('2026-09-14', 300, 'bill', 'Enerjisa'),
    row('2026-09-30', 12.5, 'fee', description='BSMV'),
]


class ExpensesTests(unittest.TestCase):
    def test_excludes_card_payments_transfers_and_income(self):
        board = expenses.dashboard(ROWS, month='2026-08')
        self.assertEqual(board['total'], 500)
        self.assertEqual(board['count'], 2)
        # kart odemesi, transfer ve 'cep subesi' satiri sayilmaz
        self.assertEqual(board['excluded'], {'count': 3, 'total': 7050})

    def test_defaults_to_latest_month_and_compares_with_previous(self):
        board = expenses.dashboard(ROWS)
        self.assertEqual(board['month'], '2026-09')
        self.assertEqual(board['total'], 622.49)
        self.assertEqual(board['previous']['month'], '2026-08')
        self.assertEqual(board['previous']['change'], 122.49)
        self.assertAlmostEqual(board['previous']['ratio'], 0.245, places=3)
        self.assertEqual(board['options'], ['2026-09', '2026-08'])

    def test_unknown_month_falls_back_and_all_has_no_previous(self):
        self.assertEqual(expenses.dashboard(ROWS, month='1999-01')['month'], '2026-09')
        board = expenses.dashboard(ROWS, month='all')
        self.assertEqual(board['total'], 1122.49)
        self.assertIsNone(board['previous'])
        self.assertFalse(board['partial'])

    def test_categories_sorted_with_shares(self):
        board = expenses.dashboard(ROWS, month='2026-09')
        self.assertEqual([c['key'] for c in board['categories']], ['purchase', 'bill', 'fee'])
        purchase = board['categories'][0]
        self.assertEqual((purchase['label'], purchase['total'], purchase['count']), ('Alışveriş', 309.99, 3))
        self.assertAlmostEqual(sum(c['share'] for c in board['categories']), 1, places=3)

    def test_tracked_subscription_overrides_statement_type(self):
        items = [{'match': 'deezer', 'category': 'Müzik', 'variable': False},
                 {'match': 'migros', 'category': 'Fatura', 'variable': False}]
        board = expenses.dashboard(ROWS, items=items, month='2026-09')
        keys = {c['key']: c['total'] for c in board['categories']}
        self.assertEqual(keys, {'bill': 510, 'subscription': 99.99, 'fee': 12.5})

    def test_merchants_grouped_and_named(self):
        board = expenses.dashboard(ROWS, month='2026-09')
        top = board['merchants'][0]
        self.assertEqual((top['name'], top['total'], top['count'], top['category']), ('Enerjisa', 300, 1, 'Fatura'))
        migros = next(m for m in board['merchants'] if m['name'] == 'Migros')
        self.assertEqual((migros['total'], migros['count']), (210, 2))
        self.assertEqual(board['merchant_count'], 4)

    def test_months_include_gaps_and_flag_partial_edges(self):
        rows = [row('2026-05-20', 10, merchant='A'), row('2026-07-10', 20, merchant='B')]
        board = expenses.dashboard(rows)
        self.assertEqual([(m['month'], m['total'], m['partial']) for m in board['months']],
                         [('2026-05', 10, True), ('2026-06', 0, False), ('2026-07', 20, True)])
        self.assertTrue(board['partial'])
        self.assertEqual(board['average'], 0)   # yalnizca tam ay (Haziran) ortalamaya girer

    def test_month_limit_and_empty_input(self):
        rows = [row(f'{2025 + (m // 12)}-{m % 12 + 1:02d}-15', 1, merchant='X') for m in range(15)]
        self.assertEqual(len(expenses.dashboard(rows)['months']), expenses.MONTH_LIMIT)
        board = expenses.dashboard([])
        self.assertIsNone(board['month'])
        self.assertEqual((board['total'], board['months'], board['categories'], board['period']), (0, [], [], None))


if __name__ == '__main__':
    unittest.main()
