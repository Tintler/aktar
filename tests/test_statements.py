from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import statements  # noqa: E402

BANK_TEXT = '''Enpara hesap özeti
Dönem başı bakiyesi 6.852,30 TL Dönem sonu bakiyesi 11.168,70 TL IBAN TR55
02/09/26 Ödeme, Sakarya Elektrik (SEPAŞ) faturası, abone no : 100104418533 - 504,00 TL 6.348,30 TL
08/09/26 Gelen Transfer 8.851,00 TL 15.199,30 TL
08/09/26 Ödeme, Enpara.com kredi kartı ödemesi - 3.104,15 TL 12.095,15 TL
14/09/26 Ödeme, PALGAZ faturası, abone no : 1617 - 175,00 TL 11.920,15 TL
19/09/26 Diğer, MIGROS-GEBZE - 316,05 TL 11.604,10 TL
21/09/26 Ödeme, Türksat Kablo TV faturası, abone no : 1130192198 - 435,40 TL 11.168,70 TL
'''


def tx(day, amount, direction='out', kind='bill', description='x', merchant='', number=''):
    return {'date': day, 'amount': amount, 'direction': direction, 'type': kind, 'description': description,
            'merchant': merchant, 'subscriber_no': number}


GOOD = {'account': 'bank_account', 'currency': 'TRY', 'opening_balance': '6.852,30', 'closing_balance': 11168.70,
        'spending_total': None, 'payments_total': None, 'transactions': [
            tx('02/09/26', '504,00', merchant='SEPAŞ', number='100104418533'),
            tx('2026-09-08', 8851, 'in', 'transfer'),
            tx('2026-09-08', 3104.15, 'out', 'card_payment'),
            tx('2026-09-14', 175, merchant='PALGAZ', number='1617'),
            tx('2026-09-19', 316.05, kind='purchase'),
            tx('2026-09-21', 435.40, merchant='Türksat', number='1130192198')]}


class FakeClient:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        self.cfg = {'model': 'fake'}

    def chat(self, messages, temperature=None, max_tokens=None):
        self.calls.append(messages)
        return json.dumps(self.answers.pop(0), ensure_ascii=False)


class StatementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(Path(self.temp.name) / 'store')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.file = Path(self.temp.name) / 'Eylül hesap özeti.txt'
        self.file.write_text(BANK_TEXT, encoding='utf-8')
        self.cfg = {'qa_context_chars': 24000}

    def test_amount_and_day_parsing(self):
        self.assertEqual(statements.amount('3.104,15'), 3104.15)
        self.assertEqual(statements.amount('- 504,00 TL'), 504.0)
        self.assertEqual(statements.amount('1,234.50'), 1234.5)
        self.assertEqual(statements.amount('8.851'), 8851.0)
        self.assertEqual(statements.amount(-12.5), 12.5)
        self.assertIsNone(statements.amount('yok'))
        self.assertIsNone(statements.amount(True))
        self.assertEqual(statements.day('02/09/26'), '2026-09-02')
        self.assertEqual(statements.day('02.09.2026'), '2026-09-02')
        self.assertEqual(statements.day('2026-09-02'), '2026-09-02')
        self.assertEqual(statements.day('31/02/2026'), '')

    def test_check_bank_and_card_totals(self):
        result = statements.merge([GOOD])
        self.assertEqual(statements.check(result), ('ok', ''))
        wrong = statements.merge([dict(GOOD, transactions=GOOD['transactions'][:2]
                                       + [tx('2026-09-08', 3104.15, 'in', 'card_payment')] + GOOD['transactions'][3:])])
        status, problem = statements.check(wrong)
        self.assertEqual(status, 'mismatch')
        self.assertIn('closing balance is 11168.70', problem)
        card = statements.merge([{'account': 'credit_card', 'opening_balance': 3104.15, 'closing_balance': 2160.10,
                                  'spending_total': 2160.10, 'transactions': [
                                      tx('2026-09-08', 3104.15, 'in', 'card_payment'),
                                      tx('2026-09-04', 840, merchant='Turkcell'), tx('2026-09-07', 1320.10)]}])
        self.assertEqual(statements.check(card), ('ok', ''))
        bare = statements.merge([{'account': 'credit_card', 'transactions': [tx('2026-09-04', 840)]}])
        self.assertEqual(statements.check(bare)[0], 'unchecked')

    def test_extract_retries_mismatch_and_caches(self):
        wrong = dict(GOOD, transactions=[dict(row, direction='in') if row['type'] == 'card_payment' else row
                                         for row in GOOD['transactions']])
        client = FakeClient(wrong, GOOD)
        record = statements.extract(self.file, client, self.cfg, log=lambda _m: None)
        self.assertEqual((record['account'], record['status'], len(record['transactions'])), ('bank_account', 'ok', 6))
        self.assertEqual(len(client.calls), 2)
        self.assertIn('does not reconcile', client.calls[1][-1]['content'])
        self.assertEqual(record['transactions'][0], {
            'date': '2026-09-02', 'description': 'x', 'amount': 504.0, 'direction': 'out', 'type': 'bill',
            'merchant': 'SEPAŞ', 'subscriber_no': '100104418533'})
        again = statements.extract(self.file, FakeClient(), self.cfg)  # onbellekten, model cagrilmaz
        self.assertEqual(again['transactions'], record['transactions'])
        self.assertFalse(statements.cache_dir().name.isidentifier())  # adinda nokta: koleksiyon sayilmaz

    def test_missing_totals_are_asked_separately(self):
        client = FakeClient(dict(GOOD, opening_balance=None, closing_balance=None),
                            {'opening_balance': '6.852,30', 'closing_balance': '11.168,70'})
        record = statements.extract(self.file, client, self.cfg)
        self.assertEqual(record['status'], 'ok')
        self.assertIn('summary figures', client.calls[1][0]['content'])

    def test_non_statement_is_not_sent_to_model(self):
        other = Path(self.temp.name) / 'ders notu.txt'
        other.write_text('Gradyan inişi ve öğrenme oranı üzerine notlar.', encoding='utf-8')
        record = statements.extract(other, FakeClient(), self.cfg)
        self.assertEqual((record['account'], record['status'], record['transactions']), ('none', 'none', []))

    def test_transactions_deduplicate_overlapping_statements(self):
        first = statements.merge([GOOD])
        records = [dict(first, name='a.pdf'), dict(first, name='b.pdf')]
        rows = statements.transactions(records)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]['file'], 'a.pdf')
        self.assertEqual([row['date'] for row in rows], sorted(row['date'] for row in rows))


if __name__ == '__main__':
    unittest.main()
