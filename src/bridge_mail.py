"""E-postadan iceri aktarma (F89) arka ucu: Gmail hesabi, koleksiyon kurallari, onizleme ve indirme.

Is mantigi mail_import.py'dedir. Kurallar koleksiyon kaydinda ('mail_rules'), indirilen
postalarin kaydi `library/<slug>.mail.json`'da, sifreler secret_store'da durur. Koleksiyon
acildiginda kurallar arka planda kontrol edilir (en sik AUTO_MINUTES dakikada bir);
indirilen dosyalar kuralin klasorune yazilir, klasor koleksiyona eklenir ve tarama onlari
'yeni' isaretler. Hazirlik kullaniciya birakilir.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

import library
import mail_import
import secret_store
from app_core import load_config

AUTO_MINUTES = 10


def _address():
    try:
        return str(load_config().get('mail_address', '')).strip()
    except (OSError, ValueError, RuntimeError):
        return ''


class MailMixin:
    def _init_mail(self):
        self._mail_lock = threading.Lock()
        self._mail_dates = {}   # indirilen dosya -> postanin gelis tarihi (belge tarihi yedegi)

    # ------------------------------------------------------------------ hesap
    def _mail_password(self, address=None):
        address = address or _address()
        if not address:
            return ''
        try:
            return secret_store.get_secret(mail_import.password_key(address))
        except secret_store.SecretStoreError:
            return ''

    def mail_account(self):
        address = _address()
        return {'address': address, 'has_password': bool(self._mail_password(address))}

    def mail_set_password(self, password):
        """Uygulama sifresini isletim sistemi deposuna yazar (bos: siler)."""
        address = _address()
        if not address:
            return {'error': 'Önce e-posta adresini girip ayarları kaydedin.'}
        try:
            secret_store.set_secret(mail_import.password_key(address), str(password or '').replace(' ', ''))
        except secret_store.SecretStoreError as error:
            return {'error': str(error)}
        self._log('E-posta uygulama şifresi ' + ('kaydedildi.' if password else 'silindi.'))
        return self.mail_account()

    def mail_test(self):
        address = _address()
        try:
            box = mail_import.test_login(address, self._mail_password(address))
        except mail_import.MailError as error:
            return {'ok': False, 'message': str(error)}
        return {'ok': True, 'message': f'Bağlandı · postalar "{box}" kutusunda aranacak'}

    # ------------------------------------------------------------------ kurallar
    def _rule_view(self, rule):
        try:
            has = bool(secret_store.get_secret(mail_import.pdf_password_key(self._lib_slug, rule['id'])))
        except secret_store.SecretStoreError:
            has = False
        return dict(rule, has_password=has)

    def mail_rules(self):
        if self._lib_data is None:
            return {'error': 'Önce bir koleksiyon açın.'}
        state = mail_import.load_state(self._lib_slug)
        counts = {}
        for item in state['messages'].values():
            counts[item.get('rule')] = counts.get(item.get('rule'), 0) + 1
        account = self.mail_account()
        return {'rules': [dict(self._rule_view(rule), fetched=counts.get(rule['id'], 0))
                          for rule in mail_import.rules_of(self._lib_data)],
                'account': bool(account['address'] and account['has_password']),
                'address': account['address'], 'checked': state['checked'],
                'busy': self._mail_lock.locked(),
                'what': [{'id': key, 'label': label} for key, label in mail_import.WHAT.items()]}

    def mail_save_rule(self, rule, pdf_password=None):
        """Kurali kaydeder; klasoru koleksiyona ekler. `pdf_password` None: degismez, '': siler."""
        if self._lib_data is None:
            return {'error': 'Önce bir koleksiyon açın.'}
        rules = mail_import.rules_of(self._lib_data)
        try:
            clean = mail_import.normalize_rule(rule)
        except ValueError as error:
            return {'error': str(error)}
        if pdf_password is not None:
            try:
                secret_store.set_secret(mail_import.pdf_password_key(self._lib_slug, clean['id']),
                                        str(pdf_password))
            except secret_store.SecretStoreError as error:
                return {'error': str(error)}
        index = next((i for i, item in enumerate(rules) if item['id'] == clean['id']), None)
        if index is None:
            rules.append(clean)
        else:
            rules[index] = clean
        self._lib_data['mail_rules'] = rules
        Path(clean['folder']).mkdir(parents=True, exist_ok=True)
        library.add_folder(self._lib_data, clean['folder'])
        state = self._save_collection(f'E-posta kuralı kaydedildi: {clean["title"]}')
        if 'error' in state:
            return state
        return self.mail_rules()

    def mail_delete_rule(self, rule_id):
        if self._lib_data is None:
            return {'error': 'Önce bir koleksiyon açın.'}
        self._lib_data['mail_rules'] = [rule for rule in mail_import.rules_of(self._lib_data)
                                        if rule['id'] != rule_id]
        try:
            secret_store.delete_secret(mail_import.pdf_password_key(self._lib_slug, rule_id))
        except secret_store.SecretStoreError:
            pass
        state = self._save_collection('E-posta kuralı silindi (indirilen dosyalar duruyor).')
        return state if 'error' in state else self.mail_rules()

    # ------------------------------------------------------------------ onizleme / indirme
    def mail_preview(self, rule):
        """Kurala uyan postalari listeler; hicbir sey indirilmez (kaydedilmemis kural da olur)."""
        if self._lib_data is None:
            return {'error': 'Önce bir koleksiyon açın.'}
        try:
            clean = mail_import.normalize_rule(dict(rule or {}, folder=(rule or {}).get('folder') or '.'))
        except ValueError as error:
            return {'error': str(error)}
        address = _address()
        state = mail_import.load_state(self._lib_slug)
        try:
            results = mail_import.run(address, self._mail_password(address), [clean], state, fetch=False,
                                      log=self._log)
        except mail_import.MailError as error:
            return {'error': str(error)}
        outcome = results[clean['id']]
        if outcome['error']:
            return {'error': outcome['error']}
        return {'items': [{key: item[key] for key in ('date', 'subject', 'sender', 'done')}
                          for item in outcome['items']]}

    def mail_fetch(self, rule_id=None):
        """Acik kurallarin (ya da tek kuralin) yeni postalarini indirir."""
        if self._lib_data is None:
            return {'error': 'Önce bir koleksiyon açın.'}
        rules = [rule for rule in mail_import.rules_of(self._lib_data)
                 if (rule['id'] == rule_id if rule_id else rule.get('enabled', True))]
        if not rules:
            return {'error': 'İndirilecek açık kural yok.'}
        summary = self._mail_run(self._lib_slug, rules)
        if 'error' in summary:
            return summary
        return dict(self.mail_rules(), message=summary['message'])

    def _mail_run(self, slug, rules):
        if not self._mail_lock.acquire(blocking=False):
            return {'error': 'E-posta kontrolü zaten sürüyor.'}
        try:
            address = _address()
            state = mail_import.load_state(slug)

            def pdf_password(rule):
                try:
                    return secret_store.get_secret(mail_import.pdf_password_key(slug, rule['id']))
                except secret_store.SecretStoreError:
                    return ''

            try:
                results = mail_import.run(address, self._mail_password(address), rules, state,
                                          pdf_password=pdf_password, log=self._log)
            except mail_import.MailError as error:
                return {'error': str(error)}
            finally:
                mail_import.save_state(slug, state)
        finally:
            self._mail_lock.release()
        files = sum(len(item['files']) for item in results.values())
        duplicates = sum(item['duplicates'] for item in results.values())
        for item in results.values():
            for warning in item['warnings']:
                self._log('E-posta: ' + warning)
        errors = [item['error'] for item in results.values() if item['error']]
        message = (f'E-postadan {files} yeni dosya indirildi' if files else 'E-postada yeni dosya yok') + (
            f' · {duplicates} tekrar gelen atlandı' if duplicates else '') + (
            f' · {len(errors)} kural hata verdi' if errors else '') + '.'
        self._log(message)
        if slug == self._lib_slug:
            self._mail_dates = mail_import.file_dates(state)
            if files:
                self._rescan()
        if files and hasattr(self, '_subs_auto_scan'):
            self._subs_auto_scan(slug)  # F114: inen ekstreler hemen okunur
        return {'message': message, 'files': files}

    def _mail_auto(self):
        """Koleksiyon acilinca: hesap ve acik kural varsa, son kontrolden AUTO_MINUTES gectiyse
        arka planda yeni postalari indirir."""
        slug, data = self._lib_slug, self._lib_data
        self._mail_dates = mail_import.file_dates(mail_import.load_state(slug)) if slug else {}
        rules = [rule for rule in mail_import.rules_of(data or {}) if rule.get('enabled', True)]
        if not rules or self._mail_lock.locked():
            return
        checked = mail_import.load_state(slug)['checked']
        try:
            if checked and datetime.now() - datetime.fromisoformat(checked) < timedelta(minutes=AUTO_MINUTES):
                return
        except ValueError:
            pass
        if not self._mail_password():
            return

        def work():
            summary = self._mail_run(slug, rules)
            if summary.get('files'):
                self._emit('toast', {'message': summary['message'], 'kind': 'ok'})
            elif 'error' in summary:
                self._log('E-posta kontrolü: ' + summary['error'])

        threading.Thread(target=work, name='aktar-mail-check', daemon=True).start()
