"""Ekstre satirlari (F110): banka hesap ozeti ve kredi karti ekstrelerinden islem cikarma.

Satirlari yerel model cikarir (bankalarin bicimleri farkli, satirlar PDF'te kayabiliyor);
sonuc ekstrenin kendi toplamlariyla kodda sinanir:
  - hesap ozeti: donem basi bakiyesi + gelenler - gidenler = donem sonu bakiyesi
  - kredi karti: onceki ekstre borcu - odemeler + harcamalar = ekstre borcu; varsa ekstredeki
    harcama/odeme toplamlari da satirlarin toplamina esit olmali
Tutmazsa model bir kez daha, farki da bilerek sorulur; yine tutmazsa ekstre 'mismatch'
isaretlenir ve arayuzde gosterilir. Sonuc dosya basina `statements.cache/` altinda saklanir
(klasor adindaki nokta yuzunden library.list_collections onu koleksiyon saymaz); ayni dosya
degismedikce model bir daha cagrilmaz.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import documents
import library
import qa
from app_core import read, save_json

VERSION = 1
TOLERANCE = 0.05
ACCOUNTS = ('credit_card', 'bank_account')
DIRECTIONS = ('out', 'in')
TYPES = ('bill', 'subscription', 'purchase', 'card_payment', 'transfer', 'fee', 'other')
# Ekstre olabilecek belgeler; digerleri (ders notu, sozlesme...) modele hic gonderilmez.
HINTS = ('ekstre', 'hesap ozeti', 'hesap hareket', 'hesap dokumu', 'iban', 'kart numarasi', 'bakiye',
         'statement', 'balance')
SYSTEM = '''You extract transactions from a bank account or credit card statement (the text may be one part of a longer statement). Reply with a JSON object only, no other text:
{"account": "credit_card" | "bank_account" | "none",
 "currency": "TRY",
 "opening_balance": <number or null>, "closing_balance": <number or null>,
 "spending_total": <number or null>, "payments_total": <number or null>,
 "transactions": [{"date": "YYYY-MM-DD", "description": "<the row's text>", "amount": 123.45, "direction": "out" | "in", "type": "bill" | "subscription" | "purchase" | "card_payment" | "transfer" | "fee" | "other", "merchant": "<short company name>", "subscriber_no": "<abone no / phone / customer number or empty>"}]}
Rules:
- "none" (with an empty list) when the text is not a statement with transaction rows.
- One entry per transaction row; skip summary lines (previous balance, totals, limits, interest tables).
- amount is always positive. direction "out" = money spent by the account holder, "in" = money received or a payment towards the card debt.
- Credit card: purchases are "out" even without a minus sign; a payment line like "Ödeme ... - 3.104,15 TL" is direction "in", type "card_payment".
- Bank account: a minus sign means "out". Paying a credit card from the account is type "card_payment", direction "out".
- Turkish numbers: 3.104,15 = 3104.15. Two-digit years like 02/09/26 are 2026.
- opening_balance / closing_balance: a bank account's balance at the start and end of the period (Dönem başı / Dönem sonu bakiyesi); on a credit card statement the previous statement's debt (Bir önceki ekstre borcu / bakiyeniz) and this statement's debt (Ekstre borcu / Dönem borcu).
- spending_total / payments_total: a credit card statement's own totals of purchases (Harcamalar) and payments (Ödemeler) for this period.
- Use null for a total that the text does not state. Never compute totals yourself.
- type "bill" = utilities, phone, internet, TV invoices; "subscription" = streaming, software or services billed periodically.
- merchant: short company name ("SEPAŞ", "Turkcell", "Deezer", "Amazon Prime"); keep it the same for the same company.'''
# Kucuk modeller satirlari cikarirken toplamlari atlayabiliyor; o zaman yalniz toplamlar sorulur.
TOTALS = '''You read the summary figures of a {account} statement. Reply with a JSON object only, no other text:
{{"opening_balance": <number or null>, "closing_balance": <number or null>}}
{rule}
Turkish numbers: 3.104,15 = 3104.15. Use null when the text does not state the figure; never compute it.'''
TOTAL_RULES = {
    'bank_account': 'opening_balance: the balance at the start of the period (Dönem başı bakiyesi); '
                    'closing_balance: the balance at the end of the period (Dönem sonu bakiyesi).',
    'credit_card': "opening_balance: the previous statement's debt (Bir önceki ekstre borcu / bakiyeniz); "
                   "closing_balance: this statement's total debt (Ekstre borcu / Dönem borcu).",
}
RETRY = '''Your previous answer does not reconcile with the statement's own totals: {problem}
Check every row again, especially the direction of each amount and rows you may have skipped, and reply with the corrected JSON object.'''


def cache_dir():
    return library.library_dir() / 'statements.cache'


def _digest(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def cache_path(path):
    path = Path(path).resolve()
    stat = path.stat()
    key = _digest('|'.join((str(VERSION), str(path).lower(), str(stat.st_size), str(int(stat.st_mtime)))))
    stem = re.sub(r'[^\w.-]+', '_', path.stem)[:40] or 'ekstre'
    return cache_dir() / f'{stem}.{key[:16]}.json'


def cached(path):
    """Dosyanin onbellekteki sonucu; yoksa ya da dosya degistiyse None."""
    try:
        value = json.loads(read(cache_path(path)))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get('version') == VERSION else None


def amount(value):
    """Model sayiyi bazen metin verir: '3.104,15' / '3104.15' / '-504,00 TL'."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return abs(float(value))
    text = re.sub(r'[^\d,.]', '', str(value))
    if not text:
        return None
    if ',' in text and '.' in text:
        text = text.replace('.', '').replace(',', '.') if text.rfind(',') > text.rfind('.') else text.replace(',', '')
    elif ',' in text:
        text = text.replace(',', '.')
    elif text.count('.') > 1 or re.fullmatch(r'\d{1,3}\.\d{3}', text):
        text = text.replace('.', '')
    try:
        return abs(float(text))
    except ValueError:
        return None


def day(value):
    """'2026-09-02', '02/09/2026', '02.09.26' -> '2026-09-02'; okunamazsa ''."""
    text = str(value or '').strip()
    match = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', text[:10])
    if match:
        year, month, number = map(int, match.groups())
    else:
        match = re.match(r'(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})', text)
        if not match:
            return ''
        number, month, year = map(int, match.groups())
        year += 2000 if year < 100 else 0
    try:
        return date(year, month, number).isoformat()
    except ValueError:
        return ''


def _text(value, limit=200):
    return ' '.join(str(value or '').split())[:limit]


def clean_transaction(row):
    if not isinstance(row, dict):
        return None
    value, when = amount(row.get('amount')), day(row.get('date'))
    if not value or not when:
        return None
    kind = str(row.get('type') or 'other')
    return {
        'date': when,
        'description': _text(row.get('description')),
        'amount': round(value, 2),
        'direction': row.get('direction') if row.get('direction') in DIRECTIONS else 'out',
        'type': kind if kind in TYPES else 'other',
        'merchant': _text(row.get('merchant'), 60),
        'subscriber_no': re.sub(r'[^\w-]', '', str(row.get('subscriber_no') or ''))[:30],
    }


def merge(parts):
    """Parca parca cikarilan sonuclari birlestirir: ust bilgiler ilk dolu degerden."""
    result = {'account': 'none', 'currency': 'TRY', 'opening_balance': None, 'closing_balance': None,
              'spending_total': None, 'payments_total': None, 'transactions': []}
    for part in parts:
        if not isinstance(part, dict):
            continue
        if result['account'] == 'none' and part.get('account') in ACCOUNTS:
            result['account'] = part['account']
        currency = str(part.get('currency') or '').upper()
        if re.fullmatch(r'[A-Z]{3}', currency) and result['currency'] == 'TRY':
            result['currency'] = currency
        for key in ('opening_balance', 'closing_balance', 'spending_total', 'payments_total'):
            if result[key] is None:
                result[key] = amount(part.get(key))
        rows = part.get('transactions')
        result['transactions'] += [row for row in map(clean_transaction, rows if isinstance(rows, list) else []) if row]
    if result['account'] == 'none' and result['transactions']:
        result['account'] = 'bank_account' if result['opening_balance'] is not None else 'credit_card'
    return result


def check(result):
    """Ekstrenin kendi toplamlariyla sinama: ('ok' | 'mismatch' | 'unchecked', aciklama)."""
    rows = result['transactions']
    out = round(sum(row['amount'] for row in rows if row['direction'] == 'out'), 2)
    came = round(sum(row['amount'] for row in rows if row['direction'] == 'in'), 2)
    problems, checked = [], False
    start, end = result['opening_balance'], result['closing_balance']
    if start is not None and end is not None and result['account'] in ACCOUNTS:
        checked = True
        if result['account'] == 'bank_account':
            computed = round(start + came - out, 2)
            formula = f'opening balance {start:.2f} + incoming {came:.2f} - outgoing {out:.2f}'
        else:  # kartta borc: odemeler duser, harcamalar ekler
            computed = round(start - came + out, 2)
            formula = f'previous debt {start:.2f} - incoming (payments) {came:.2f} + outgoing {out:.2f}'
        if abs(computed - end) > TOLERANCE:
            problems.append(f'{formula} = {computed:.2f}, but the statement says the closing balance is {end:.2f}.')
    if result['account'] == 'credit_card':
        for total, got, label in ((result['spending_total'], out, 'outgoing (spending)'),
                                  (result['payments_total'], came, 'incoming (payments)')):
            if total is None:
                continue
            checked = True
            if abs(total - got) > TOLERANCE:
                problems.append(f'the {label} rows add up to {got:.2f}, but the statement total is {total:.2f}.')
    if problems:
        return 'mismatch', ' '.join(problems)
    return ('ok' if checked else 'unchecked'), ''


def looks_like_statement(text):
    folded = library.fold(text[:20000])
    return any(hint in folded for hint in HINTS)


def statement_text(path, base=None):
    """Belgenin sayfalari; metin katmani yoksa (taranmis) hazirlanmis oturumun OCR metni."""
    try:
        pages = [str(page or '') for page in documents.pages_of(path)]
    except (OSError, ValueError, RuntimeError):
        pages = []
    if sum(len(page.strip()) for page in pages) >= 40:
        return pages
    import search_index
    session = search_index.primary_session(path, base)
    if not session or not qa.is_document(session):
        return pages
    grouped = {}
    for line in qa.lines_of(session):
        grouped.setdefault(int(line['start']), []).append(line['text'])
    return ['\n'.join(lines) for _page, lines in sorted(grouped.items())]


def chunks(pages, budget):
    """Sayfalari modele sigacak parcalara boler (sayfa bolunmez, cok uzun sayfa kesilir)."""
    parts, current = [], ''
    for page in pages:
        page = page[:budget]
        if current and len(current) + len(page) + 1 > budget:
            parts.append(current)
            current = ''
        current = f'{current}\n{page}' if current else page
    if current.strip():
        parts.append(current)
    return parts


def _ask(client, user, previous=None, problem=''):
    """Model cevabi (JSON nesnesi). `previous` + `problem`: tutmayan ilk cevap ve farki."""
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]
    if previous is not None:
        messages += [{'role': 'assistant', 'content': json.dumps(previous, ensure_ascii=False)},
                     {'role': 'user', 'content': RETRY.format(problem=problem)}]
    return qa.parse_json_object(client.chat(messages, temperature=0))


def _totals(client, account, text):
    system = TOTALS.format(account=account.replace('_', ' '), rule=TOTAL_RULES[account])
    try:
        return qa.parse_json_object(client.chat([{'role': 'system', 'content': system},
                                                 {'role': 'user', 'content': text}], temperature=0))
    except ValueError:
        return {}


def extract(path, client, cfg, log=print, base=None, force=False):
    """Ekstreyi okur, sinar ve onbellege yazar; onbellekte varsa dogrudan dondurur.

    Donen: {'path', 'name', 'account', 'currency', 'status', 'problem', 'transactions', ...}.
    Ekstre olmayan belgeler {'account': 'none'} olarak (modele sorulmadan) kaydedilir."""
    path = Path(path)
    if not force:
        value = cached(path)
        if value is not None:
            return value
    pages = statement_text(path, base)
    text = '\n'.join(pages)
    record = {'version': VERSION, 'path': str(path), 'name': path.name, 'model': ''}
    if not text.strip() or not looks_like_statement(text):
        record.update(merge([]), status='none', problem='')
    else:
        budget = max(4000, int(cfg.get('qa_context_chars', 24000)) - 2000)
        parts = chunks(pages, budget)
        title = f'STATEMENT FILE: {path.name}\n\n'
        answers = []
        for number, part in enumerate(parts, 1):
            if len(parts) > 1:
                log(f'Ekstre okunuyor: {path.name} ({number}/{len(parts)})')
            answers.append(_ask(client, title + part))
        result = merge(answers)
        if result['account'] in ACCOUNTS and None in (result['opening_balance'], result['closing_balance']):
            text = title + parts[0] + ('\n' + parts[-1] if len(parts) > 1 else '')
            figures = _totals(client, result['account'], text)
            for key in ('opening_balance', 'closing_balance'):
                if result[key] is None:
                    result[key] = amount(figures.get(key))
        status, problem = check(result)
        if status == 'mismatch' and len(parts) == 1:
            log(f'Ekstre toplamı tutmadı, yeniden okunuyor: {path.name}')
            retried = merge([_ask(client, title + parts[0], answers[0], problem)])
            again, again_problem = check(retried)
            if again != 'mismatch' or len(retried['transactions']) >= len(result['transactions']):
                result, status, problem = retried, again, again_problem
        record.update(result, status=status if result['account'] in ACCOUNTS else 'none', problem=problem,
                      model=str(client.cfg.get('model', '')))
    save_json(cache_path(path), record)
    return record


def candidates(entries):
    """Koleksiyon taramasindaki belgeler (video ve gorseller ekstre sayilmaz)."""
    return [entry['path'] for entry in entries if not entry.get('missing') and entry.get('kind') == 'document']


def transactions(records):
    """Ekstrelerin satirlari tek listede; ust uste binen donemlerde ayni islem bir kez sayilir."""
    seen, rows = set(), []
    for record in records:
        for row in record.get('transactions') or []:
            key = (row['date'], row['amount'], row['direction'], library.fold(row['description']))
            if key in seen:
                continue
            seen.add(key)
            rows.append(dict(row, file=record.get('name', ''), account=record.get('account', '')))
    rows.sort(key=lambda row: row['date'])
    return rows
