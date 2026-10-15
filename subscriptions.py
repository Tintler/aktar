"""Abonelik ve odeme takibi (F106): Netflix, elektrik faturasi, tek seferlik odemeler.

Kayitlar kutuphane klasorunde `subscriptions.data.json` dosyasinda durur (adindaki nokta
yuzunden library.list_collections onu koleksiyon saymaz). Saklanan `renewal_date` yinelenen
kayitlarda donemin capasidir; gecmiste kaldiysa bir sonraki odeme tarihi (`next_due`) her
okumada capadan donem eklenerek hesaplanir, dosya kendiliginden degismez.
"""
from __future__ import annotations

import calendar
import json
import re
import secrets
from datetime import date

import library
from app_core import read, save_json

NAME_LIMIT = 80
TEXT_LIMIT = 120
NOTE_LIMIT = 2000
CURRENCIES = ('TRY', 'USD', 'EUR', 'GBP')
KINDS = ('recurring', 'once')
CYCLES = {'weekly': 52 / 12, 'monthly': 1, 'quarterly': 1 / 3, 'semiannual': 1 / 6, 'yearly': 1 / 12}
CYCLE_MONTHS = {'monthly': 1, 'quarterly': 3, 'semiannual': 6, 'yearly': 12}
STATUSES = ('active', 'trial', 'paused', 'cancelled')
METHODS = ('credit', 'debit', 'transfer', 'cash', 'other')
CATEGORIES = ['Dijital yayın', 'Müzik', 'Yazılım', 'Bulut', 'Fatura', 'İletişim', 'Sigorta', 'Spor', 'Eğitim', 'Diğer']
UPCOMING_DAYS = 30


def path():
    return library.library_dir() / 'subscriptions.data.json'


def _date(value):
    value = str(value or '').strip()[:10]
    try:
        return date.fromisoformat(value).isoformat() if value else ''
    except ValueError:
        return ''


def _text(value, limit=TEXT_LIMIT):
    return ' '.join(str(value or '').split())[:limit]


def _choice(value, options, default):
    value = str(value or '')
    return value if value in options else default


def clean(item):
    """Gelen kaydi dogrular; adi bos ya da tutari gecersizse None."""
    if not isinstance(item, dict):
        return None
    name = _text(item.get('name'), NAME_LIMIT)
    try:
        amount = round(float(str(item.get('amount', 0)).replace(',', '.')), 2)
    except (TypeError, ValueError):
        return None
    if not name or not (0 <= amount < 1e9):
        return None
    ident = str(item.get('id') or '')
    if not re.fullmatch(r'[\w-]{1,40}', ident):
        ident = 's' + secrets.token_hex(4)
    last4 = re.sub(r'\D', '', str(item.get('card_last4') or ''))[-4:]
    return {
        'id': ident,
        'name': name,
        'category': _text(item.get('category'), 40),
        'amount': amount,
        'currency': _choice(item.get('currency'), CURRENCIES, 'TRY'),
        'kind': _choice(item.get('kind'), KINDS, 'recurring'),
        'cycle': _choice(item.get('cycle'), CYCLES, 'monthly'),
        'status': _choice(item.get('status'), STATUSES, 'active'),
        'start_date': _date(item.get('start_date')),
        'renewal_date': _date(item.get('renewal_date')),
        'end_date': _date(item.get('end_date')),
        'auto_renew': bool(item.get('auto_renew', True)),
        'method': _choice(item.get('method'), METHODS, 'credit'),
        'bank': _text(item.get('bank'), 60),
        'card': _text(item.get('card'), 60),
        'card_last4': last4 if len(last4) == 4 else '',
        'notes': str(item.get('notes') or '').strip()[:NOTE_LIMIT],
    }


def load():
    try:
        value = json.loads(read(path()))
    except (OSError, ValueError):
        return []
    items = value.get('items') if isinstance(value, dict) else None
    return [item for item in map(clean, items) if item] if isinstance(items, list) else []


def _write(items):
    library.library_dir().mkdir(parents=True, exist_ok=True)
    save_json(path(), {'version': 1, 'items': items})


def upsert(item):
    """Kaydi ekler ya da ayni kimliklisini degistirir; temizlenmis kaydi dondurur."""
    item = clean(item)
    if not item:
        raise ValueError('Ad ve geçerli bir tutar gerekli.')
    items = load()
    index = next((i for i, old in enumerate(items) if old['id'] == item['id']), None)
    if index is None:
        items.append(item)
    else:
        items[index] = item
    _write(items)
    return item


def remove(ident):
    items = load()
    kept = [item for item in items if item['id'] != ident]
    if len(kept) == len(items):
        return False
    _write(kept)
    return True


def add_months(day, months):
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def next_due(item, today=None):
    """Bir sonraki odeme tarihi (date) ya da yoksa None.

    Tek seferlikte kayitli tarih; yinelenende capadan itibaren bugune ya da sonrasina dusen ilk
    donem. Iptal/durdurulmus kayitlarin ya da bitis tarihini gecen donemlerin odemesi yoktur.
    """
    today = today or date.today()
    anchor = item.get('renewal_date') or item.get('start_date')
    if not anchor or item.get('status') in ('paused', 'cancelled'):
        return None
    anchor = date.fromisoformat(anchor)
    if item.get('kind') == 'once':
        return anchor if anchor >= today else None
    due, step = anchor, 0
    while due < today:
        step += 1
        if item['cycle'] == 'weekly':
            due = date.fromordinal(anchor.toordinal() + 7 * step)
        else:
            due = add_months(anchor, CYCLE_MONTHS[item['cycle']] * step)
    end = item.get('end_date')
    if end and due > date.fromisoformat(end):
        return None
    return due


def monthly_cost(item):
    """Aylik esdeger tutar; tek seferlik ve iptal/durdurulmus kayitlarda 0."""
    if item.get('kind') == 'once' or item.get('status') in ('paused', 'cancelled'):
        return 0.0
    return item['amount'] * CYCLES[item['cycle']]


def view(today=None):
    """Arayuz icin kayitlar (+ next_due, days_left, monthly) ve para birimine gore ozet."""
    today = today or date.today()
    rows, monthly, upcoming, by_payment = [], {}, {}, {}
    for item in load():
        due = next_due(item, today)
        cost = monthly_cost(item)
        row = dict(item, next_due=due.isoformat() if due else '',
                   days_left=(due - today).days if due else None, monthly=round(cost, 2))
        rows.append(row)
        currency = item['currency']
        if cost:
            monthly[currency] = monthly.get(currency, 0) + cost
            key = (item['bank'] or 'Banka belirtilmedi', item['method'])
            group = by_payment.setdefault(key + (currency,), {'bank': key[0], 'method': key[1], 'currency': currency,
                                                             'monthly': 0.0, 'count': 0})
            group['monthly'] += cost
            group['count'] += 1
        if due and (due - today).days <= UPCOMING_DAYS:
            upcoming[currency] = upcoming.get(currency, 0) + item['amount']
    rows.sort(key=lambda row: (row['next_due'] == '', row['next_due'], row['name'].lower()))
    rounded = lambda totals: {key: round(value, 2) for key, value in sorted(totals.items())}
    payments = sorted(by_payment.values(), key=lambda group: -group['monthly'])
    for group in payments:
        group['monthly'] = round(group['monthly'], 2)
    return {
        'items': rows,
        'summary': {
            'monthly': rounded(monthly),
            'yearly': rounded({key: value * 12 for key, value in monthly.items()}),
            'upcoming': rounded(upcoming),
            'upcoming_days': UPCOMING_DAYS,
            'active': sum(1 for row in rows if row['status'] in ('active', 'trial')),
            'by_payment': payments,
        },
        'categories': CATEGORIES,
        'today': today.isoformat(),
    }
