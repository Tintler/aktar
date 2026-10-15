"""Abonelik ve odeme takibi (F106): Netflix, elektrik faturasi, tek seferlik odemeler.

Kayitlar kutuphane klasorunde `subscriptions.data.json` dosyasinda, logolar (F107)
`subscriptions.logos/<kimlik>.png` olarak durur (adlarindaki nokta yuzunden
library.list_collections bunlari koleksiyon saymaz). Saklanan `renewal_date` yinelenen
kayitlarda donemin capasidir; gecmiste kaldiysa bir sonraki odeme tarihi (`next_due`) her
okumada capadan donem eklenerek hesaplanir, dosya kendiliginden degismez.

F110: Elektrik, doğalgaz gibi tutari degisen faturalar (`variable`) ekstrelerden bulunan
odemelerle (`payments`) izlenir; tutar son odemelerin ortalamasidir. Kaydin `match` metni
(abone no ya da firma adi, virgulle birden fazla) ekstre satirlarini kayda baglar; hicbir
kayda uymayan duzenli odemeler oneri olarak listelenir. Satirlari statements.py cikarir.
"""
from __future__ import annotations

import base64
import calendar
import io
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
LOGO_SIZE = 128
LOGO_SOURCE_LIMIT = 15 * 1024 * 1024
LOGO_TYPES = ('*.png', '*.jpg', '*.jpeg', '*.webp', '*.gif', '*.bmp', '*.ico')
PAYMENT_LIMIT = 60          # kayit basina saklanan en fazla odeme
ESTIMATE_COUNT = 6          # degisken tutarin tahmini: son bu kadar odemenin ortalamasi
# Abonelik sayilmayan satirlar: kart borcu odemesi, kendi hesaplari arasi transfer.
SKIP_TYPES = ('card_payment', 'transfer')
SKIP_WORDS = ('kredi karti odemesi', 'kart borcu', 'cep subesi')
# F114: zam / yuksek fatura uyarilari
ALERT_DAYS = 45             # son odemesi bundan eski kayit uyarilmaz
RISE = 0.30                 # degisken fatura: onceki odemelerin ortalamasinin bu kadar ustu
DISMISS_LIMIT = 200


def path():
    return library.library_dir() / 'subscriptions.data.json'


def logo_path(ident):
    return library.library_dir() / 'subscriptions.logos' / f'{ident}.png'


def make_logo(data):
    """Gorsel baytlarini en fazla LOGO_SIZE piksellik, saydamligi korunan PNG'ye cevirir."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if len(data) > LOGO_SOURCE_LIMIT:
        raise ValueError('Görsel çok büyük (en fazla 15 MB).')
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert('RGBA')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('Görsel okunamadı; PNG, JPG, WebP, GIF, BMP ya da ICO seçin.') from error
    box = image.getbbox()  # ikonlarin cevresindeki saydam bosluk kirpilir
    if box:
        image = image.crop(box)
    image.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
    output = io.BytesIO()
    image.save(output, 'PNG', optimize=True)
    return output.getvalue()


def data_url(png):
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')


def logo_from_file(path):
    with open(path, 'rb') as stream:
        return data_url(make_logo(stream.read(LOGO_SOURCE_LIMIT + 1)))


def logo_from_data_url(value):
    match = re.fullmatch(r'data:image/[\w.+-]+;base64,([A-Za-z0-9+/=\s]+)', str(value or ''))
    if not match:
        raise ValueError('Logo verisi geçersiz.')
    return make_logo(base64.b64decode(match.group(1)))


def _set_logo(ident, logo):
    """logo: None dokunma, '' sil, data URL kaydet."""
    if logo is None:
        return
    target = logo_path(ident)
    if not logo:
        target.unlink(missing_ok=True)
        return
    png = logo_from_data_url(logo)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.tmp')
    temp.write_bytes(png)
    temp.replace(target)


def _read_logo(ident):
    try:
        return data_url(logo_path(ident).read_bytes())
    except OSError:
        return ''


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
        'variable': bool(item.get('variable', False)),
        'match': _text(item.get('match'), TEXT_LIMIT),
        'payments': clean_payments(item.get('payments')),
    }


def clean_payments(values):
    """[{date, amount, file}] tarih sirasinda, ayni gun + tutar bir kez; en yeni PAYMENT_LIMIT."""
    found = {}
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict):
            continue
        when = _date(value.get('date'))
        try:
            amount = round(float(value.get('amount')), 2)
        except (TypeError, ValueError):
            continue
        if when and 0 < amount < 1e9:
            found.setdefault((when, amount), {'date': when, 'amount': amount, 'file': _text(value.get('file'), 160)})
    return [found[key] for key in sorted(found)][-PAYMENT_LIMIT:]


def _read_file():
    try:
        value = json.loads(read(path()))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def load():
    items = _read_file().get('items')
    return [item for item in map(clean, items) if item] if isinstance(items, list) else []


def settings():
    """Ekstre taramasi ayarlari: taranan koleksiyonlar, yoksayilan oneriler, son tarama,
    yeni ekstrelerin kendiliginden taranmasi (F114) ve kapatilan uyarilar."""
    value = _read_file()
    sources = value.get('sources')
    ignored = value.get('ignored')
    dismissed = value.get('dismissed')
    scan = value.get('scan') if isinstance(value.get('scan'), dict) else {}
    return {'sources': [str(slug) for slug in sources] if isinstance(sources, list) else [],
            'ignored': [str(key) for key in ignored] if isinstance(ignored, list) else [],
            'auto': bool(value.get('auto', True)),
            'dismissed': [str(key) for key in dismissed][-DISMISS_LIMIT:] if isinstance(dismissed, list) else [],
            'scan': {'date': str(scan.get('date') or ''),
                     'files': [str(item) for item in scan.get('files') or [] if isinstance(item, str)]}}


def save_settings(**values):
    current = settings()
    current.update({key: value for key, value in values.items() if key in current})
    _write(load(), current)
    return current


def _write(items, extra=None):
    library.library_dir().mkdir(parents=True, exist_ok=True)
    save_json(path(), {'version': 1, 'items': items, **(extra if extra is not None else settings())})


def upsert(item):
    """Kaydi ekler ya da ayni kimliklisini degistirir; temizlenmis kaydi dondurur.

    `logo` alani: yoksa/None logoya dokunulmaz, '' logoyu siler, data URL yeni logodur.
    """
    logo = item.get('logo') if isinstance(item, dict) else None
    item = clean(item)
    if not item:
        raise ValueError('Ad ve geçerli bir tutar gerekli.')
    _set_logo(item['id'], logo)
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
    logo_path(ident).unlink(missing_ok=True)
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


def last_date(item):
    """Yaklasan odemesi olmayan kaydin tarihi: bitis/iptal, yoksa son odeme ya da baslangic."""
    if item.get('kind') == 'once':
        return item.get('renewal_date') or item.get('start_date') or ''
    return item.get('end_date') or item.get('renewal_date') or item.get('start_date') or ''


def _negate(iso):
    """Tarihi azalan siralamak icin: 2026-10-15 -> sirasi tersine donen sayi."""
    return -date.fromisoformat(iso).toordinal()


def estimate(item):
    """Odeme basina tutar: degisken faturada son odemelerin ortalamasi, yoksa kayitli tutar."""
    payments = item.get('payments') or []
    if item.get('variable') and payments:
        recent = [payment['amount'] for payment in payments[-ESTIMATE_COUNT:]]
        return round(sum(recent) / len(recent), 2)
    return item['amount']


def monthly_cost(item):
    """Aylik esdeger tutar; tek seferlik ve iptal/durdurulmus kayitlarda 0."""
    if item.get('kind') == 'once' or item.get('status') in ('paused', 'cancelled'):
        return 0.0
    return estimate(item) * CYCLES[item['cycle']]


def view(today=None):
    """Arayuz icin kayitlar (+ next_due, days_left, monthly) ve para birimine gore ozet."""
    today = today or date.today()
    rows, monthly, upcoming, by_payment = [], {}, {}, {}
    for item in load():
        due = next_due(item, today)
        cost = monthly_cost(item)
        amounts = [payment['amount'] for payment in item['payments']]
        row = dict(item, logo=_read_logo(item['id']), next_due=due.isoformat() if due else '',
                   last_date='' if due else last_date(item),
                   days_left=(due - today).days if due else None, monthly=round(cost, 2),
                   estimate=estimate(item), last_payment=item['payments'][-1] if amounts else None,
                   low=min(amounts) if amounts else None, high=max(amounts) if amounts else None)
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
            upcoming[currency] = upcoming.get(currency, 0) + estimate(item)
    # Once odemesi yaklasanlar (en yakin basta), sonra odemesi olmayanlar (durdurulmus, iptal,
    # odenmis tek seferlik) kendi tarihlerine gore en yenisi basta, en sonda tarihsizler.
    rows.sort(key=lambda row: (0, row['next_due'], row['name'].lower()) if row['next_due']
              else (1, _negate(row['last_date']), row['name'].lower()) if row['last_date']
              else (2, '', row['name'].lower()))
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
        'alerts': alerts(today=today),
    }


def alerts(items=None, today=None, dismissed=None):
    """Son odemesi yeni olan aktif kayitlarda: sabit tutarli kaydin tutari degistiyse (zam ya da
    indirim) ya da degisken faturanin son odemesi onceki ortalamanin RISE kadar ustundeyse uyari.
    Kimlik kayit + son odemedir; kapatilan uyari yeni odeme gelince yeniden cikabilir."""
    today = today or date.today()
    items = load() if items is None else items
    dismissed = set(settings()['dismissed'] if dismissed is None else dismissed)
    result = []
    for item in items:
        payments = item['payments']
        if len(payments) < 2 or item['status'] not in ('active', 'trial') or item['kind'] != 'recurring':
            continue
        last = payments[-1]
        if (today - date.fromisoformat(last['date'])).days > ALERT_DAYS:
            continue
        key = f'{item["id"]}|{last["date"]}|{last["amount"]}'
        if key in dismissed:
            continue
        if item['variable']:
            before = [payment['amount'] for payment in payments[-1 - ESTIMATE_COUNT:-1]]
            reference = round(sum(before) / len(before), 2)
            if last['amount'] < reference * (1 + RISE):
                continue
            kind = 'high'
        else:
            reference = payments[-2]['amount']
            tolerance = max(0.01 * reference, 0.5)
            # Tutar kayitta zaten yeni fiyata cekildiyse (Tutari guncelle) uyari kalkar.
            if abs(last['amount'] - reference) <= tolerance or abs(item['amount'] - last['amount']) <= tolerance:
                continue
            kind = 'price_up' if last['amount'] > reference else 'price_down'
        result.append({'key': key, 'id': item['id'], 'name': item['name'], 'kind': kind, 'date': last['date'],
                       'amount': last['amount'], 'reference': reference, 'currency': item['currency'],
                       'ratio': round((last['amount'] - reference) / reference, 4) if reference else None,
                       'stored': item['amount']})
    result.sort(key=lambda alert: alert['date'], reverse=True)
    return result


def _money(value, currency):
    text = f'{value:,.2f}'.replace(',', ' ').replace('.', ',').replace(' ', '.')
    return f'{text} {"TL" if currency == "TRY" else currency}'


def alert_text(alert):
    """Bildirim metni: 'Netflix tutarı 229,99 TL → 279,99 TL (+%21,7)'."""
    ratio = f'{abs(alert["ratio"]) * 100:.0f}'.replace('.', ',') if alert['ratio'] is not None else '?'
    amount, reference = _money(alert['amount'], alert['currency']), _money(alert['reference'], alert['currency'])
    if alert['kind'] == 'high':
        return f'{alert["name"]}: son ödeme {amount}, önceki ortalamanın %{ratio} üstünde ({reference}).'
    sign = '+' if alert['kind'] == 'price_up' else '-'
    return f'{alert["name"]} tutarı değişti: {reference} → {amount} ({sign}%{ratio}).'


def dismiss(key):
    dismissed = [value for value in settings()['dismissed'] if value != key] + [str(key)]
    return save_settings(dismissed=dismissed[-DISMISS_LIMIT:])


def apply_price(ident):
    """Zam uyarisinda kaydin tutarini son odemeye esitler."""
    items = load()
    item = next((item for item in items if item['id'] == ident), None)
    if item is None or not item['payments']:
        raise ValueError('Kayıt bulunamadı.')
    item['amount'] = item['payments'][-1]['amount']
    _write(items)
    return item


# ---------------------------------------------------------------- ekstre eslestirme (F110)
def _terms(item):
    return [library.fold(term) for term in str(item.get('match') or '').split(',') if term.strip()]


def _row_text(row):
    return library.fold(' '.join((row.get('description', ''), row.get('merchant', ''), row.get('subscriber_no', ''))))


def spending(row):
    """Abonelige donusebilecek satir mi: giden para; kart odemesi ve transfer degil."""
    if row.get('direction') != 'out' or row.get('type') in SKIP_TYPES:
        return False
    text = _row_text(row)
    return not any(word in text for word in SKIP_WORDS)


def matches(item, row):
    """Arama metinlerinden biri satirda tam kelime olarak geciyor mu ('1617' '16170'e uymaz)."""
    text = _row_text(row)
    return any(re.search(r'(?<![0-9a-z])' + re.escape(term) + r'(?![0-9a-z])', text) for term in _terms(item))


def row_key(row):
    """Oneri gruplamasi: abone no varsa o (iki Turkcell hatti ayri kalir), yoksa firma adi."""
    number = library.fold(row.get('subscriber_no', ''))
    if number:
        return 'no:' + number
    name = re.sub(r'[^0-9a-z]+', '', library.fold(row.get('merchant') or row.get('description', '')[:30]))
    return 'm:' + name if name else ''


def _payment(row):
    return {'date': row['date'], 'amount': row['amount'], 'file': row.get('file', '')}


def sync(rows):
    """Arama metni olan kayitlara eslesen ekstre odemelerini ekler; yinelenen aktif kaydin
    capasi en son odeme tarihine tasinir (sonraki odeme oradan hesaplanir). Degisen kayit sayisi."""
    items, changed = load(), 0
    rows = [row for row in rows if spending(row)]
    for item in items:
        if not _terms(item):
            continue
        found = [_payment(row) for row in rows if matches(item, row)]
        payments = clean_payments(item['payments'] + found)
        anchor = item['renewal_date']
        if payments and item['kind'] == 'recurring' and item['status'] in ('active', 'trial') \
                and payments[-1]['date'] > (anchor or ''):
            anchor = payments[-1]['date']
        if payments != item['payments'] or anchor != item['renewal_date']:
            item['payments'], item['renewal_date'] = payments, anchor
            changed += 1
    if changed:
        _write(items)
    return changed


def suggestions(rows, items=None, ignored=()):
    """Hicbir kayda uymayan duzenli odemeler: fatura/abonelik turundekiler ya da en az iki ayri
    ayda gorulen ayni firma. En yeni odemesi olan basta."""
    items = load() if items is None else items
    ignored = set(ignored)
    groups = {}
    for row in rows:
        if not spending(row) or any(matches(item, row) for item in items):
            continue
        key = row_key(row)
        if key and key not in ignored:
            groups.setdefault(key, []).append(row)
    result = []
    for key, group in groups.items():
        months = {row['date'][:7] for row in group}
        if len(months) < 2 and not any(row['type'] in ('bill', 'subscription') for row in group):
            continue
        amounts = [row['amount'] for row in group]
        names = [row['merchant'] for row in group if row.get('merchant')]
        name = max(reversed(names), key=names.count) if names else group[-1]['description'][:40]  # esitse en yenisi
        number = group[-1].get('subscriber_no', '')
        days = sorted(int(row['date'][8:]) for row in group)
        bill = any(row['type'] == 'bill' for row in group)
        result.append({
            'key': key, 'name': name[:NAME_LIMIT], 'match': number or name,
            'category': 'Fatura' if bill else '',
            'count': len(group), 'months': len(months),
            'average': round(sum(amounts) / len(amounts), 2), 'last': group[-1]['amount'],
            'last_date': group[-1]['date'], 'first_date': group[0]['date'], 'day': days[len(days) // 2],
            # Faturalar (elektrik, su...) tek odemede de degisken sayilir.
            'variable': bill or max(amounts) - min(amounts) > 0.01 * max(amounts),
            'method': 'credit' if group[-1].get('account') == 'credit_card' else 'transfer',
            'subscriber_no': number, 'description': group[-1]['description'],
            'payments': [_payment(row) for row in group],
        })
    result.sort(key=lambda item: item['last_date'], reverse=True)
    return result


def accept(suggestion, overrides=None):
    """Oneriyi kayda cevirir: yinelenen, aylik; tutar ortalama, capa son odeme."""
    values = {
        'name': suggestion['name'], 'category': suggestion['category'], 'amount': suggestion['average'],
        'kind': 'recurring', 'cycle': 'monthly', 'status': 'active', 'variable': suggestion['variable'],
        'start_date': suggestion['first_date'], 'renewal_date': suggestion['last_date'],
        'method': suggestion['method'], 'match': suggestion['match'], 'payments': suggestion['payments'],
        'card': f'Abone no {suggestion["subscriber_no"]}' if suggestion['subscriber_no']
        and suggestion['method'] != 'credit' else '',
    }
    values.update({key: value for key, value in (overrides or {}).items() if key not in ('id', 'payments')})
    return upsert(values)


def link(suggestion, ident):
    """Oneriyi var olan kayda baglar: arama metni eklenir, odemeleri kayda gecer."""
    items = load()
    item = next((item for item in items if item['id'] == ident), None)
    if item is None:
        raise ValueError('Kayıt bulunamadı.')
    terms = [term.strip() for term in item['match'].split(',') if term.strip()]
    if library.fold(suggestion['match']) not in map(library.fold, terms):
        terms.append(suggestion['match'])
    item['match'] = _text(', '.join(terms), TEXT_LIMIT)
    item['payments'] = clean_payments(item['payments'] + suggestion['payments'])
    if item['kind'] == 'recurring' and item['payments'][-1]['date'] > (item['renewal_date'] or ''):
        item['renewal_date'] = item['payments'][-1]['date']
    _write(items)
    return item


def ignore(key, undo=False):
    ignored = [value for value in settings()['ignored'] if value != key]
    if not undo:
        ignored.append(key)
    return save_settings(ignored=ignored)
