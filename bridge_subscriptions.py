"""Abonelikler sayfasinin (F106) arka ucu; is mantigi subscriptions.py'de.

F110: "Ekstrelerden tara" secilen koleksiyonlardaki belgeleri arka planda statements.py ile
okur ('subs_scan' olaylariyla ilerleme), sonra satirlari kayitlara baglar ve onerileri cikarir.
Okunan ekstreler onbellekte kalir; sayfa her acildiginda oneriler onbellekten hesaplanir.
"""
from __future__ import annotations

import threading
from datetime import datetime

import expenses
import library
import statements
import subscriptions
from app_core import Client, load_config, qa_config


class SubscriptionsMixin:
    _subs_busy = None      # tarama suruyorsa {'done', 'total', 'name'}
    _subs_stop = False

    # ------------------------------------------------------------------ gorunum
    def _subs_records(self, files):
        records = []
        for path in files:
            try:
                record = statements.cached(path)
            except OSError:   # dosya silinmis/tasinmis
                record = None
            if record and record.get('account') != 'none':
                records.append(record)
        return records

    def _subs_view(self):
        view = subscriptions.view()
        options = subscriptions.settings()
        records = self._subs_records(options['scan']['files'])
        rows = statements.transactions(records)
        collections = library.list_collections()
        view['scan'] = {
            'date': options['scan']['date'], 'busy': self._subs_busy,
            'sources': [slug for slug in options['sources'] if slug in collections],
            'collections': [{'slug': slug, 'title': data['title']} for slug, data in collections.items()],
            'statements': [{'name': record['name'], 'path': record['path'], 'account': record['account'],
                            'status': record['status'], 'problem': record.get('problem', ''),
                            'count': len(record['transactions'])} for record in records],
            'ignored': len(options['ignored']),
        }
        view['suggestions'] = subscriptions.suggestions(rows, ignored=options['ignored'])
        return view

    def _subs_suggestion(self, key):
        options = subscriptions.settings()
        rows = statements.transactions(self._subs_records(options['scan']['files']))
        found = next((item for item in subscriptions.suggestions(rows) if item['key'] == key), None)
        if found is None:
            raise ValueError('Öneri artık yok; sayfayı yenileyin.')
        return found

    def subs_state(self):
        return self._subs_view()

    def subs_spending(self, month=None):
        """F111: Harcamalar sekmesi; taranmis ekstrelerin satirlarindan pano (expenses.py)."""
        options = subscriptions.settings()
        records = self._subs_records(options['scan']['files'])
        board = expenses.dashboard(statements.transactions(records), subscriptions.load(),
                                   str(month) if month else None)
        board['statements'] = len(records)
        board['scan_date'] = options['scan']['date']
        return board

    def subs_save(self, item):
        try:
            saved = subscriptions.upsert(item)
            if saved['match']:  # arama metni degistiyse odemeler hemen baglansin
                options = subscriptions.settings()
                subscriptions.sync(statements.transactions(self._subs_records(options['scan']['files'])))
        except (ValueError, OSError) as error:
            return {'error': str(error)}
        self._log(f'Abonelik kaydedildi: {saved["name"]}')
        return self._subs_view()

    def subs_logo(self, path=None):
        """Logo gorseli: yol verilmezse dosya penceresi acilir. {'logo': data URL}; vazgecilirse None."""
        path = path or self._dialog('open_file', 'Logo seç', ('Görseller (' + ';'.join(subscriptions.LOGO_TYPES) + ')',))
        if not path:
            return None
        try:
            return {'logo': subscriptions.logo_from_file(path)}
        except ValueError as error:
            return {'error': str(error)}
        except OSError as error:
            return {'error': f'Görsel açılamadı: {path} ({error.strerror or error})'}

    def subs_delete(self, ident):
        try:
            removed = subscriptions.remove(str(ident or ''))
        except OSError as error:
            return {'error': str(error)}
        if not removed:
            return {'error': 'Kayıt bulunamadı.'}
        return self._subs_view()

    # ------------------------------------------------------------------ oneriler
    def subs_accept(self, key, overrides=None):
        try:
            saved = subscriptions.accept(self._subs_suggestion(str(key or '')), overrides)
        except (ValueError, OSError) as error:
            return {'error': str(error)}
        self._log(f'Ekstreden abonelik eklendi: {saved["name"]} ({len(saved["payments"])} ödeme)')
        return self._subs_view()

    def subs_link(self, key, ident):
        try:
            item = subscriptions.link(self._subs_suggestion(str(key or '')), str(ident or ''))
        except (ValueError, OSError) as error:
            return {'error': str(error)}
        self._log(f'Ekstre ödemeleri kayda bağlandı: {item["name"]}')
        return self._subs_view()

    def subs_ignore(self, key, undo=False):
        try:
            subscriptions.ignore(str(key or ''), bool(undo))
        except OSError as error:
            return {'error': str(error)}
        return self._subs_view()

    def subs_unignore_all(self):
        try:
            subscriptions.save_settings(ignored=[])
        except OSError as error:
            return {'error': str(error)}
        return self._subs_view()

    # ------------------------------------------------------------------ tarama
    def subs_scan(self, slugs=None, force=False):
        """Secilen koleksiyonlardaki ekstreleri arka planda okur. `slugs` None: kayitli secim."""
        if self._subs_busy:
            return {'error': 'Tarama zaten sürüyor.'}
        collections = library.list_collections()
        if slugs is not None:
            slugs = [str(slug) for slug in slugs if str(slug) in collections]
            subscriptions.save_settings(sources=slugs)
        else:
            slugs = [slug for slug in subscriptions.settings()['sources'] if slug in collections]
        if not slugs:
            return {'error': 'Taranacak koleksiyon seçin.'}
        paths, seen = [], set()
        for slug in slugs:
            entries, _changed = library.scan(library.load_collection(slug))
            for path in statements.candidates(entries):
                key = str(path).lower()
                if key not in seen:
                    seen.add(key)
                    paths.append(path)
        if not paths:
            return {'error': 'Seçilen koleksiyonlarda belge yok.'}
        try:
            client = Client(qa_config(load_config()), log=self._log)  # F72: soru-cevap modeli
        except (ValueError, RuntimeError) as error:
            return {'error': str(error)}
        self._subs_busy = {'done': 0, 'total': len(paths), 'name': ''}
        self._subs_stop = False

        def work():
            cfg, failed, read = client.cfg, [], 0
            for number, path in enumerate(paths):
                if self._subs_stop:
                    break
                self._subs_busy = {'done': number, 'total': len(paths), 'name': path.name}
                self._emit('subs_scan', {'busy': self._subs_busy})
                try:
                    fresh = force or statements.cached(path) is None
                    record = statements.extract(path, client, cfg, log=self._log, force=force)
                    read += fresh and record['account'] != 'none'
                    if record['status'] == 'mismatch':
                        self._log(f'Ekstre toplamı tutmadı: {path.name} — {record["problem"]}')
                except Exception as error:  # bir dosyanin hatasi taramayi durdurmaz
                    failed.append(path.name)
                    self._log(f'Ekstre okunamadı: {path.name} ({error})')
            stopped = self._subs_stop
            self._subs_busy = None
            try:
                # Durdurulsa da daha once okunmus ekstreler listede kalir.
                done = [str(path) for path in paths if statements.cached(path) is not None]
                subscriptions.save_settings(scan={'date': datetime.now().isoformat(timespec='seconds'), 'files': done})
                options = subscriptions.settings()
                records = self._subs_records(options['scan']['files'])
                changed = subscriptions.sync(statements.transactions(records))
                state = self._subs_view()
            except (OSError, ValueError) as error:
                self._emit('subs_scan', {'busy': None, 'error': str(error)})
                return
            message = (f'{len(records)} ekstre, {len(state["suggestions"])} öneri'
                       + (f', {changed} kayıt güncellendi' if changed else '')
                       + (f' · {read} ekstre yeni okundu' if read else '')
                       + (f' · {len(failed)} dosya okunamadı' if failed else '')
                       + (' · durduruldu' if stopped else ''))
            self._log('Ekstre taraması: ' + message)
            self._emit('subs_scan', {'busy': None, 'state': state, 'message': message})

        threading.Thread(target=work, name='aktar-statement-scan', daemon=True).start()
        return self._subs_view()

    def subs_scan_stop(self):
        self._subs_stop = True
        return {'ok': True}
