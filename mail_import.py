"""E-postadan iceri aktarma (F89): Gmail'den ekstre / fon raporu eklerini koleksiyona indirir.

Arayuzden bagimsizdir; bridge_mail.py ve testler ayni mantigi kullanir. Akis:
  1. IMAP (imap.gmail.com, uygulama sifresi) ile baglanilir; Gmail'de tum postalar
     ('\\All' isaretli kutu: arsivlenenler de) salt-okunur acilir, postalar okunmus
     isaretlenmez (BODY.PEEK).
  2. Kural: gonderen / konu icerir + su tarihten beri. Sunucuda tarih (ve ASCII ise
     gonderen) ile daraltilir, konu ve gonderen Turkce harf farki gozetmeden burada suzulur.
  3. Ayni postayi tekrar indirmemek icin postanin kimligi (Message-ID) kural basina
     kaydedilir; ayni ek baska postayla tekrar gelirse icerik ozeti (SHA-256) yakalar.
  4. Dosya adi postanin gelis tarihiyle baslar: '2026-10-03 World Gold Hesap Ozeti.pdf'.
     Ayni ad farkli icerikle varsa sonuna icerik ozetinin ilk harfleri eklenir.
  5. Sifreli PDF, kuralin PDF sifresiyle acilip sifresiz kopya olarak yazilir.

Kayit: `library/<slug>.mail.json` (adinda nokta var: koleksiyon sayilmaz).
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import imaplib
import io
import json
import re
import secrets
from datetime import date, datetime
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

import library
from app_core import read, save_json

VERSION = 1
GMAIL_HOST = 'imap.gmail.com'
GMAIL_PORT = 993
WHAT = {'pdf': 'PDF ekleri', 'html': 'E-posta gövdesi', 'both': 'PDF ekleri ve gövde'}
HEADER_BATCH = 200       # tek FETCH'te istenen en fazla posta basligi
DEFAULT_SINCE_DAYS = 365
_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
_LIST = re.compile(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')
_UID = re.compile(rb'UID (\d+)')
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


class MailError(RuntimeError):
    pass


def password_key(address):
    return 'mail/' + str(address).strip().lower()


def pdf_password_key(slug, rule_id):
    return f'pdf/{slug}/{rule_id}'


# --- kurallar -------------------------------------------------------------------
def new_rule_id():
    return secrets.token_hex(4)


def normalize_rule(value, existing_ids=()):
    """Arayuzden gelen kurali dogrular. Donen: temiz kural sozlugu (ValueError: hata)."""
    value = dict(value or {})
    rule = {'id': str(value.get('id') or '').strip() or new_rule_id(),
            'title': ' '.join(str(value.get('title', '')).split()),
            'sender': str(value.get('sender', '')).strip(),
            'subject': ' '.join(str(value.get('subject', '')).split()),
            'what': value.get('what') if value.get('what') in WHAT else 'pdf',
            'since': str(value.get('since', '')).strip(),
            'folder': str(value.get('folder', '')).strip(),
            'enabled': bool(value.get('enabled', True))}
    if not rule['sender'] and not rule['subject']:
        raise ValueError('Gönderen ya da konu alanından en az biri dolu olmalı.')
    if not rule['folder']:
        raise ValueError('İndirilecek klasörü seçin.')
    if rule['since']:
        try:
            rule['since'] = date.fromisoformat(rule['since']).isoformat()
        except ValueError as error:
            raise ValueError('Başlangıç tarihi geçersiz: ' + rule['since']) from error
    rule['title'] = rule['title'] or rule['subject'] or rule['sender']
    return rule


def rules_of(data):
    return [rule for rule in data.get('mail_rules') or [] if isinstance(rule, dict) and rule.get('id')]


# --- kayit ----------------------------------------------------------------------
def state_path(slug):
    return library.library_dir() / (slug + '.mail.json')


def load_state(slug):
    try:
        value = json.loads(read(state_path(slug)))
    except (OSError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    value.setdefault('messages', {})
    value.setdefault('hashes', {})
    value.setdefault('checked', '')
    return value


def save_state(slug, state):
    save_json(state_path(slug), dict(state, version=VERSION))


def delete_state(slug):
    state_path(slug).unlink(missing_ok=True)


def file_dates(state):
    """Indirilen dosyalarin postayla gelis tarihi {yol: 'YYYY-MM-DD'} (belge tarihi
    icerikten cikarilamazsa yedek olarak kullanilir)."""
    dates = {}
    for item in state.get('messages', {}).values():
        for path in item.get('files') or []:
            if item.get('date'):
                dates.setdefault(str(path), item['date'])  # ilk getiren posta
    return dates


# --- yardimcilar ----------------------------------------------------------------
def decode(value):
    """MIME kodlu basligi duz metne cevirir ('=?utf-8?q?Hesap_=C3=96zeti?=' -> 'Hesap Ozeti')."""
    if not value:
        return ''
    try:
        return ' '.join(str(make_header(decode_header(str(value)))).split())
    except (ValueError, LookupError, UnicodeError):
        return ' '.join(str(value).split())


def mail_date(value):
    """Date basligindan yerel gun ('YYYY-MM-DD'); okunamazsa ''."""
    try:
        moment = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, IndexError):
        return ''
    if moment is None:
        return ''
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.date().isoformat()


def safe_name(name, limit=120):
    """Windows ve Linux'ta gecerli dosya adi."""
    name = _UNSAFE.sub(' ', str(name))
    name = ' '.join(name.split()).strip(' .')
    if len(name) > limit:
        stem, dot, suffix = name.rpartition('.')
        name = (stem[:limit - len(suffix) - 1] + '.' + suffix) if dot and len(suffix) <= 8 else name[:limit]
    return name or 'ek'


def matches(rule, sender, subject):
    """Gonderen/konu kurala uyuyor mu (buyuk/kucuk harf ve Turkce harf farki yok)."""
    if rule.get('sender') and library.fold(rule['sender']) not in library.fold(sender):
        return False
    if rule.get('subject') and library.fold(rule['subject']) not in library.fold(subject):
        return False
    return True


def _imap_date(text):
    day = date.fromisoformat(text)
    return f'{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}'


def _since(rule, today=None):
    if rule.get('since'):
        return rule['since']
    today = today or date.today()
    return date.fromordinal(today.toordinal() - DEFAULT_SINCE_DAYS).isoformat()


# --- IMAP -----------------------------------------------------------------------
def connect(address, password, factory=None):
    """Gmail'e baglanip giris yapar. Hata mesajlari Turkce ve ne yapilacagini soyler."""
    if not str(address).strip() or '@' not in str(address):
        raise MailError('E-posta adresi ayarlanmamış (Ayarlar → E-posta).')
    if not password:
        raise MailError('Uygulama şifresi kaydedilmemiş (Ayarlar → E-posta).')
    try:
        imap = (factory or imaplib.IMAP4_SSL)(GMAIL_HOST, GMAIL_PORT, timeout=30)
    except OSError as error:
        raise MailError('Gmail sunucusuna bağlanılamadı: ' + str(error)) from error
    try:
        imap.login(str(address).strip(), str(password).replace(' ', ''))
    except imaplib.IMAP4.error as error:
        raise MailError('Gmail girişi reddedildi. Normal Google şifreniz değil, 16 harflik '
                        '"uygulama şifresi" gerekir (Google hesabı → Güvenlik → 2 adımlı doğrulama '
                        '→ Uygulama şifreleri). Ayrıntı: ' + decode(error)) from error
    return imap


def all_mail_box(imap):
    """Gmail'in 'Tum Postalar' kutusu (dil ayarina gore adi degisir; '\\All' bayragindan
    bulunur). Bulunamazsa INBOX."""
    status, lines = imap.list()
    if status == 'OK':
        for line in lines or []:
            if not isinstance(line, bytes):
                continue
            match = _LIST.match(line)
            if match and b'\\All' in match.group('flags'):
                return match.group('name').decode('ascii', 'replace')
    return 'INBOX'


def _select(imap):
    box = all_mail_box(imap)
    status, data = imap.select(box if box.startswith('"') else f'"{box}"', readonly=True)
    if status != 'OK':
        raise MailError('Posta kutusu açılamadı: ' + box)
    return box


def _search(imap, rule):
    criteria = ['SINCE', _imap_date(_since(rule))]
    sender = rule.get('sender', '')
    if sender and sender.isascii() and '"' not in sender:
        criteria += ['FROM', f'"{sender}"']
    status, data = imap.uid('SEARCH', None, *criteria)
    if status != 'OK':
        raise MailError('Posta araması başarısız.')
    return [uid for uid in (data[0] or b'').split() if uid]


def _headers(imap, uids):
    """{uid: email.message.Message (yalnizca basliklar)}."""
    found = {}
    for start in range(0, len(uids), HEADER_BATCH):
        chunk = b','.join(uids[start:start + HEADER_BATCH])
        status, data = imap.uid('FETCH', chunk, '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT FROM DATE)])')
        if status != 'OK':
            raise MailError('Posta başlıkları okunamadı.')
        for item in data or []:
            if isinstance(item, tuple) and len(item) >= 2:
                match = _UID.search(item[0])
                if match:
                    found[match.group(1)] = email.message_from_bytes(item[1])
    return found


def _message(imap, uid):
    status, data = imap.uid('FETCH', uid, '(BODY.PEEK[])')
    if status != 'OK':
        raise MailError('Posta indirilemedi.')
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2:
            return email.message_from_bytes(item[1], policy=email.policy.default)
    raise MailError('Posta içeriği boş döndü.')


def find(imap, rule, state):
    """Kurala uyan postalar (yeniden eskiye): [{'uid','id','date','subject','sender','done'}]."""
    uids = _search(imap, rule)
    items = []
    done = state.get('messages', {})
    for uid, head in _headers(imap, uids).items():
        sender, subject = decode(head.get('From')), decode(head.get('Subject'))
        if not matches(rule, sender, subject):
            continue
        message_id = str(head.get('Message-ID') or '').strip() or f'uid:{uid.decode()}'
        items.append({'uid': uid, 'id': message_id, 'date': mail_date(head.get('Date')),
                      'subject': subject, 'sender': sender,
                      'done': f'{rule["id"]}|{message_id}' in done})
    items.sort(key=lambda item: (item['date'], int(item['uid'])), reverse=True)
    return items


# --- indirme --------------------------------------------------------------------
def unlock_pdf(data, password):
    """Sifreli PDF'i sifresiz kopyaya cevirir. Donen: (bayt, uyari)."""
    if not data.startswith(b'%PDF') and b'%PDF' not in data[:1024]:
        return data, ''
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_raw
    except ImportError:
        return data, ''
    try:
        pdfium.PdfDocument(data).close()
        return data, ''  # sifresiz
    except pdfium.PdfiumError:
        pass
    if not password:
        return data, 'PDF şifreli; kurala PDF şifresi girilmemiş, şifreli hâliyle kaydedildi.'
    try:
        document = pdfium.PdfDocument(data, password=password)
    except pdfium.PdfiumError:
        return data, 'PDF şifresi yanlış; dosya şifreli hâliyle kaydedildi.'
    try:
        buffer = io.BytesIO()
        document.save(buffer, flags=pdfium_raw.FPDF_REMOVE_SECURITY)
        return buffer.getvalue(), ''
    finally:
        document.close()


def attachments(message, what):
    """Postadan kaydedilecek parcalar: [(ad, bayt)]."""
    found = []
    if what in ('pdf', 'both'):
        for part in message.walk():
            if part.is_multipart():
                continue
            name = decode(part.get_filename() or '')
            if part.get_content_type() == 'application/pdf' or name.lower().endswith('.pdf'):
                payload = part.get_payload(decode=True)
                if payload:
                    found.append((name if name.lower().endswith('.pdf') else (name or 'ek') + '.pdf',
                                  payload))
    if what in ('html', 'both'):
        body = message.get_body(preferencelist=('html', 'plain'))
        if body is not None:
            text = body.get_content()
            subject = decode(message.get('Subject')) or 'e-posta'
            if body.get_content_type() == 'text/html':
                found.append((subject + '.html', text.encode('utf-8')))
            else:
                found.append((subject + '.txt', text.encode('utf-8')))
    return found


def _target(folder, day, name, digest_text):
    """'<gun> <ad>'; ayni ad baska icerikle varsa sonuna ozetin ilk harfleri eklenir."""
    name = safe_name(name)
    base = Path(folder) / safe_name(f'{day} {name}' if day else name)
    if not base.exists():
        return base
    if hashlib.sha256(base.read_bytes()).hexdigest() == digest_text:
        return base  # ayni dosya zaten orada
    return base.with_name(f'{base.stem} {digest_text[:6]}{base.suffix}')


def download(imap, rule, item, state, pdf_password='', log=print):
    """Tek postanin eklerini kuralin klasorune yazar ve kayda isler.

    Donen: {'files': [yeni yollar], 'duplicates': n, 'warnings': [..]}."""
    folder = Path(rule['folder'])
    folder.mkdir(parents=True, exist_ok=True)
    message = _message(imap, item['uid'])
    result = {'files': [], 'duplicates': 0, 'warnings': []}
    recorded = []
    for name, data in attachments(message, rule.get('what', 'pdf')):
        digest_text = hashlib.sha256(data).hexdigest()
        known = state['hashes'].get(digest_text)
        if known:
            result['duplicates'] += 1
            recorded.append(known)
            continue
        if name.lower().endswith('.pdf'):
            data, warning = unlock_pdf(data, pdf_password)
            if warning:
                result['warnings'].append(f'{name}: {warning}')
        path = _target(folder, item['date'], name, digest_text)
        if not path.exists():
            path.write_bytes(data)
            result['files'].append(str(path))
            log(f'E-postadan indirildi: {path.name}')
        state['hashes'][digest_text] = str(path)
        recorded.append(str(path))
    if not recorded and not result['warnings']:
        result['warnings'].append(f'"{item["subject"]}" postasında kaydedilecek ek bulunamadı.')
    state['messages'][f'{rule["id"]}|{item["id"]}'] = {
        'rule': rule['id'], 'date': item['date'], 'subject': item['subject'], 'files': recorded,
        'fetched': datetime.now().isoformat(timespec='seconds')}
    return result


def run(address, password, rules, state, fetch=True, pdf_password=lambda _rule: '', log=print,
        factory=None, cancelled=None):
    """Kurallari isler. `fetch` False ise yalnizca onizleme (hicbir sey indirilmez).

    Donen: {kural_id: {'items': [...], 'files': [...], 'duplicates': n, 'warnings': [...],
    'error': ''}}. Kayit (`state`) yerinde guncellenir; cagiran kaydeder."""
    results = {}
    imap = connect(address, password, factory)
    try:
        _select(imap)
        for rule in rules:
            outcome = {'items': [], 'files': [], 'duplicates': 0, 'warnings': [], 'error': ''}
            results[rule['id']] = outcome
            try:
                outcome['items'] = find(imap, rule, state)
                if not fetch:
                    continue
                for item in reversed(outcome['items']):  # eskiden yeniye
                    if cancelled and cancelled():
                        break
                    if item['done']:
                        continue
                    done = download(imap, rule, item, state, pdf_password(rule), log)
                    item['done'] = True
                    outcome['files'] += done['files']
                    outcome['duplicates'] += done['duplicates']
                    outcome['warnings'] += done['warnings']
            except (MailError, imaplib.IMAP4.error, OSError) as error:
                outcome['error'] = decode(error)
                log(f'E-posta kuralı "{rule.get("title", rule["id"])}": {outcome["error"]}')
        if fetch:
            state['checked'] = datetime.now().isoformat(timespec='seconds')
    finally:
        try:
            imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
    return results


def test_login(address, password, factory=None):
    """Baglanti denemesi: Tum Postalar kutusunun adi."""
    imap = connect(address, password, factory)
    try:
        return all_mail_box(imap)
    finally:
        try:
            imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
