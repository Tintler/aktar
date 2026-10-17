"""Harcama panosu (F111): ekstre satirlarindan aylik toplam, tur dagilimi ve firmalar.

Saf hesap; satirlar statements.transactions'tan gelir. Kart odemeleri ve kendi transferleri
subscriptions.spending kuraliyla disarida kalir (ayni para iki kez sayilmasin). Bir abonelik
kaydina uyan satir, ekstrede 'alisveris' diye gecse de kaydin turuyle (fatura/abonelik) sayilir.
"""
from __future__ import annotations

import calendar

import subscriptions

CATEGORIES = {
    'bill': 'Fatura', 'subscription': 'Abonelik', 'purchase': 'Alışveriş', 'fee': 'Masraf ve faiz', 'other': 'Diğer',
}
# Sayilmayan satirlarin nedeni (F114: Sayilmayan kartina tiklayinca ayrinti)
EXCLUDED = {'card_payment': 'Kart borcu ödemesi', 'transfer': 'Hesaplar arası transfer',
            'words': 'Kart ödemesi (açıklamadan)'}
MERCHANT_LIMIT = 10
MONTH_LIMIT = 12
EDGE_DAYS = 3   # verinin ilk/son ayi bu kadar gunden fazla eksikse 'kismi' sayilir


def category(row, items=()):
    """Satirin pano kategorisi: abonelik kaydina uyuyorsa kaydin turu, yoksa ekstredeki tur."""
    for item in items:
        if subscriptions.matches(item, row):
            return 'bill' if item.get('category') == 'Fatura' or item.get('variable') else 'subscription'
    return row.get('type') if row.get('type') in CATEGORIES else 'other'


def _name(group):
    names = [row['merchant'] for row in group if row.get('merchant')]
    if names:
        return max(reversed(names), key=names.count)  # esitse en yenisi
    return group[-1].get('description', '')[:40] or '?'


def _months(rows):
    """Verinin kapsadigi her ay (bos aylar dahil): {'YYYY-MM': [satirlar]}."""
    if not rows:
        return {}
    first, last = rows[0]['date'][:7], rows[-1]['date'][:7]
    year, month = int(first[:4]), int(first[5:])
    result = {}
    while True:
        key = f'{year:04d}-{month:02d}'
        result[key] = []
        if key >= last:
            break
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    for row in rows:
        result[row['date'][:7]].append(row)
    return result


def _partial(month, rows):
    """Verinin basindaki ya da sonundaki ay eksik mi (ekstre ayin ortasinda basliyor/bitiyor)."""
    if not rows:
        return False
    year, number = int(month[:4]), int(month[5:])
    days = calendar.monthrange(year, number)[1]
    first, last = rows[0]['date'], rows[-1]['date']
    return (first[:7] == month and int(first[8:]) > 1 + EDGE_DAYS) \
        or (last[:7] == month and int(last[8:]) < days - EDGE_DAYS)


def reason(row):
    """Harcama sayilmayan giden satirin nedeni (subscriptions.spending'in tersi)."""
    return row.get('type') if row.get('type') in ('card_payment', 'transfer') else 'words'


def excluded(rows):
    """Sayilmayan satirlar: nedene gore toplamlar ve satirlar (en yenisi basta)."""
    groups = {}
    for row in rows:
        groups.setdefault(reason(row), []).append(row)
    return {
        'count': len(rows), 'total': _total(rows),
        'groups': sorted(({'key': key, 'label': EXCLUDED[key], 'count': len(group), 'total': _total(group)}
                          for key, group in groups.items()), key=lambda group: -group['total']),
        'rows': [{'date': row['date'], 'description': row.get('description', ''), 'merchant': row.get('merchant', ''),
                  'amount': row['amount'], 'reason': reason(row), 'account': row.get('account', ''),
                  'file': row.get('file', '')} for row in sorted(rows, key=lambda row: row['date'], reverse=True)],
    }


def _total(rows):
    return round(sum(row['amount'] for row in rows), 2)


def dashboard(rows, items=(), month=None):
    """Pano verisi. `month` ('YYYY-MM') secili ay; yoksa en son ay. Kategori ve firma listeleri
    secili ayin; `month='all'` tum donemi verir."""
    rows = sorted(rows, key=lambda row: row['date'])
    spent = [row for row in rows if subscriptions.spending(row)]
    skipped = [row for row in rows if row.get('direction') == 'out' and not subscriptions.spending(row)]
    by_month = _months(spent)
    keys = list(by_month)
    months = [{'month': key, 'total': _total(group), 'count': len(group), 'partial': _partial(key, spent)}
              for key, group in by_month.items()][-MONTH_LIMIT:]
    full = [entry for entry in months if not entry['partial']]   # ortalama eksik aylari saymaz
    if month != 'all' and month not in by_month:
        month = keys[-1] if keys else None
    if month == 'all':
        chosen, previous = spent, None
    else:
        chosen = by_month.get(month, [])
        index = keys.index(month) if month in by_month else -1
        previous = keys[index - 1] if index > 0 else None
    total = _total(chosen)
    before = _total(by_month[previous]) if previous else None

    groups = {}
    for row in chosen:
        groups.setdefault(category(row, items), []).append(row)
    categories = [{'key': key, 'label': CATEGORIES[key], 'total': _total(group), 'count': len(group),
                   'share': round(_total(group) / total, 4) if total else 0}
                  for key, group in groups.items()]
    categories.sort(key=lambda entry: entry['total'], reverse=True)

    firms = {}
    for row in chosen:
        key = subscriptions.row_key(row) or 'd:' + row.get('description', '')[:30]
        firms.setdefault(key, []).append(row)
    merchants = [{'key': key, 'name': _name(group), 'total': _total(group), 'count': len(group),
                  'category': CATEGORIES[category(group[-1], items)],
                  'share': round(_total(group) / total, 4) if total else 0}
                 for key, group in firms.items()]
    merchants.sort(key=lambda entry: entry['total'], reverse=True)

    return {
        'month': month, 'months': months, 'options': keys[::-1],
        'total': total, 'count': len(chosen),
        'previous': {'month': previous, 'total': before,
                     'change': round(total - before, 2) if before is not None else None,
                     'ratio': round((total - before) / before, 4) if before else None} if previous else None,
        'partial': month != 'all' and month is not None and _partial(month, spent),
        'average': round(sum(entry['total'] for entry in full) / len(full), 2) if full else None,
        'categories': categories,
        'merchants': merchants[:MERCHANT_LIMIT], 'merchant_count': len(merchants),
        # Secili donemin sayilmayanlari (ay ya da tum donem)
        'excluded': excluded(skipped if month == 'all' else [row for row in skipped if row['date'][:7] == month]),
        'period': {'first': rows[0]['date'], 'last': rows[-1]['date']} if rows else None,
    }
