"""E-postadan iceri aktarma (F89) testleri: sahte IMAP sunucusuyla, ag gerekmez."""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import library  # noqa: E402
import mail_import  # noqa: E402

QUIET = (lambda _message: None)


def mail(uid, subject, sender, day, attachments=(), html='', message_id=None):
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = sender
    message['Date'] = f'{day} 09:00:00 +0300'
    message['Message-ID'] = message_id or f'<m{uid}@banka.test>'
    message.set_content('Ekte hesap özetiniz var.')
    if html:
        message.add_alternative(html, subtype='html')
    for item in attachments:
        name, data = item[:2]
        maintype, subtype = (item[2] if len(item) > 2 else 'application/pdf').split('/')
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return str(uid).encode(), message.as_bytes()


class FakeIMAP:
    """imaplib.IMAP4_SSL'in kullandigimiz kadari."""

    def __init__(self, messages, password='dogru'):
        self.messages = dict(messages)
        self.password = password
        self.selected = None
        self.fetched = []

    def __call__(self, host, port, timeout=None):
        self.host = host
        return self

    def login(self, user, password):
        import imaplib
        if password != self.password:
            raise imaplib.IMAP4.error(b'[AUTHENTICATIONFAILED] Invalid credentials')
        return 'OK', [b'ok']

    def list(self):
        return 'OK', [b'(\\HasNoChildren) "/" "INBOX"',
                      b'(\\All \\HasNoChildren) "/" "[Gmail]/T&APw-m Postalar"']

    def select(self, box, readonly=False):
        self.selected = (box, readonly)
        return 'OK', [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        if command == 'SEARCH':
            self.search = args
            return 'OK', [b' '.join(self.messages)]
        uids, part = args
        data = []
        for uid in uids.split(b','):
            raw = self.messages[uid]
            if b'HEADER.FIELDS' in part.encode():
                head = raw.split(b'\n\n', 1)[0] + b'\n\n'
                data += [(b'%s (UID %s BODY[HEADER.FIELDS] {%d}' % (uid, uid, len(head)), head), b')']
            else:
                self.fetched.append(uid)
                data += [(b'%s (UID %s BODY[] {%d}' % (uid, uid, len(raw)), raw), b')']
        return 'OK', data

    def logout(self):
        return 'BYE', [b'']


class MailImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(self.root / 'store')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = self.root / 'Ekstreler'
        self.rule = mail_import.normalize_rule({'sender': '@worldcard.com.tr', 'subject': 'hesap ozeti',
                                                'since': '2026-01-01', 'folder': str(self.folder)})
        self.state = mail_import.load_state('finans')

    def run_rules(self, server, fetch=True, rules=None):
        return mail_import.run('ben@gmail.com', 'dogru', rules or [self.rule], self.state, fetch=fetch,
                               log=QUIET, factory=server)[self.rule['id']]

    def test_same_name_different_months_and_no_redownload(self):
        sender = 'World <ekstre@worldcard.com.tr>'
        server = FakeIMAP([
            mail(1, 'Hesap Özetiniz', sender, 'Thu, 04 Sep 2026', [('World Gold Hesap Ozeti.pdf', b'%PDF eylul')]),
            mail(2, '=?utf-8?q?HESAP_=C3=96ZET=C4=B0N=C4=B0Z?=', sender, 'Sat, 03 Oct 2026',
                 [('World Gold Hesap Ozeti.pdf', b'%PDF ekim')]),
            mail(3, 'Kampanya', sender, 'Sun, 04 Oct 2026', [('afis.pdf', b'%PDF reklam')]),
            mail(4, 'Hesap Özetiniz (tekrar)', sender, 'Mon, 05 Oct 2026',
                 [('World Gold Hesap Ozeti.pdf', b'%PDF ekim')]),
        ])
        preview = self.run_rules(server, fetch=False)
        self.assertEqual([item['date'] for item in preview['items']], ['2026-10-05', '2026-10-03', '2026-09-04'])
        self.assertEqual(server.fetched, [])  # onizleme hicbir postayi indirmez
        self.assertEqual(server.selected, ('"[Gmail]/T&APw-m Postalar"', True))
        self.assertIn('SINCE', server.search)
        self.assertIn('01-Jan-2026', server.search)

        outcome = self.run_rules(server)
        names = sorted(path.name for path in self.folder.iterdir())
        self.assertEqual(names, ['2026-09-04 World Gold Hesap Ozeti.pdf', '2026-10-03 World Gold Hesap Ozeti.pdf'])
        self.assertEqual((len(outcome['files']), outcome['duplicates']), (2, 1))
        self.assertEqual((self.folder / '2026-10-03 World Gold Hesap Ozeti.pdf').read_bytes(), b'%PDF ekim')
        dates = mail_import.file_dates(self.state)
        self.assertEqual(dates[str(self.folder / '2026-09-04 World Gold Hesap Ozeti.pdf')], '2026-09-04')

        server.fetched.clear()
        again = self.run_rules(server)
        self.assertEqual((again['files'], server.fetched), ([], []))
        self.assertTrue(all(item['done'] for item in again['items']))
        # dosya silinse de ayni posta tekrar indirilmez
        (self.folder / '2026-09-04 World Gold Hesap Ozeti.pdf').unlink()
        self.assertEqual(self.run_rules(server)['files'], [])

    def test_same_day_same_name_other_content_gets_hash_suffix(self):
        sender = 'ekstre@worldcard.com.tr'
        server = FakeIMAP([
            mail(1, 'Hesap Özeti', sender, 'Thu, 04 Sep 2026', [('Ozet.pdf', b'%PDF kart 1')]),
            mail(2, 'Hesap Özeti', sender, 'Thu, 04 Sep 2026', [('Ozet.pdf', b'%PDF kart 2')]),
        ])
        self.run_rules(server)
        digest = hashlib.sha256(b'%PDF kart 2').hexdigest()[:6]
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()),
                         sorted(['2026-09-04 Ozet.pdf', f'2026-09-04 Ozet {digest}.pdf']))

    def test_html_body_and_unsafe_names(self):
        rule = mail_import.normalize_rule({'subject': 'Fon Bülteni', 'what': 'html', 'folder': str(self.folder)})
        server = FakeIMAP([mail(1, 'Fon Bülteni: Ağustos/2026', 'fon@portfoy.test', 'Mon, 01 Sep 2026',
                                html='<p>Getiri %3,2</p>')])
        outcome = mail_import.run('ben@gmail.com', 'dogru', [rule], self.state, log=QUIET,
                                  factory=server)[rule['id']]
        self.assertEqual([Path(path).name for path in outcome['files']],
                         ['2026-09-01 Fon Bülteni Ağustos 2026.html'])
        self.assertIn('Getiri %3,2', Path(outcome['files'][0]).read_text(encoding='utf-8'))
        self.assertEqual(library.kind_of(outcome['files'][0]), 'document')

    def test_excel_and_office_attachments_are_taken_images_are_not(self):
        """F90: Excel/CSV/Word ekleri de alinir; logo/imza gorselleri alinmaz."""
        xlsx = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        server = FakeIMAP([mail(1, 'Hesap Özeti', 'ekstre@worldcard.com.tr', 'Thu, 04 Sep 2026', [
            ('Hareketler.xlsx', b'PK xlsx', xlsx), ('Hareketler.csv', b'tarih;tutar', 'text/csv'),
            ('Eski.xls', b'xls', 'application/octet-stream'), ('logo.png', b'png', 'image/png'),
            ('sozlesme.zip', b'zip', 'application/zip'), ('Ozet.pdf', b'%PDF ozet')])])
        outcome = self.run_rules(server)
        self.assertEqual(sorted(Path(path).name for path in outcome['files']),
                         ['2026-09-04 Eski.xls', '2026-09-04 Hareketler.csv', '2026-09-04 Hareketler.xlsx',
                          '2026-09-04 Ozet.pdf'])
        self.assertTrue(all(library.kind_of(path) == 'document' for path in outcome['files']))
        # F89 ile yalnizca PDF'i alinmis eski kayit: bir kez yeniden islenir, PDF tekrar yazilmaz
        key = next(iter(self.state['messages']))
        for path in outcome['files']:
            if not path.endswith('.pdf'):
                Path(path).unlink()
                del self.state['hashes'][next(h for h, p in self.state['hashes'].items() if p == path)]
        self.state['messages'][key] = {'rule': self.rule['id'], 'date': '2026-09-04', 'subject': 'Hesap Özeti',
                                       'files': [p for p in outcome['files'] if p.endswith('.pdf')]}
        again = self.run_rules(server)
        self.assertEqual((len(again['files']), again['duplicates']), (3, 0))
        self.assertEqual(self.run_rules(server)['files'], [])
        nameless = EmailMessage()
        nameless.add_attachment(b'PK', maintype='application', subtype=xlsx.split('/')[1])
        part = next(item for item in nameless.walk() if not item.is_multipart())
        del part['Content-Disposition']
        self.assertEqual(mail_import.attachments(nameless, 'pdf'), [('ek.xlsx', b'PK')])

    def test_wrong_password_and_rule_validation(self):
        with self.assertRaises(mail_import.MailError) as caught:
            mail_import.run('ben@gmail.com', 'yanlis', [self.rule], self.state, log=QUIET,
                            factory=FakeIMAP([]))
        self.assertIn('uygulama şifresi', str(caught.exception))
        with self.assertRaises(mail_import.MailError):
            mail_import.connect('', 'x', FakeIMAP([]))
        with self.assertRaises(ValueError):
            mail_import.normalize_rule({'folder': 'x'})
        with self.assertRaises(ValueError):
            mail_import.normalize_rule({'sender': 'a'})
        with self.assertRaises(ValueError):
            mail_import.normalize_rule({'sender': 'a', 'folder': 'x', 'since': '31.12.2025'})
        self.assertEqual(mail_import.safe_name('a:b*c?.pdf'), 'a b c .pdf')

    def test_state_lives_beside_collection_and_is_not_a_collection(self):
        slug, _data = library.create_collection('Finans', folders=[self.root])
        mail_import.save_state(slug, self.state)
        self.assertEqual(list(library.list_collections()), [slug])
        library.delete_collection(slug)
        self.assertFalse(mail_import.state_path(slug).exists())


@unittest.skipIf(os.name != 'nt', 'Windows Kimlik Bilgileri yalnizca Windows\'ta')
class SecretStoreTests(unittest.TestCase):
    def test_round_trip(self):
        import secret_store
        key = 'test/aktar-unittest'
        self.addCleanup(secret_store.delete_secret, key)
        secret_store.set_secret(key, 'abcd efgh ğüş')
        self.assertEqual(secret_store.get_secret(key), 'abcd efgh ğüş')
        secret_store.set_secret(key, '')
        self.assertEqual(secret_store.get_secret(key), '')


if __name__ == '__main__':
    unittest.main()
