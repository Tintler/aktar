"""Klasor izleme (F114): 'izlenen' koleksiyonlara dusen yeni dosyalar kendiliginden hazirlanir.

Yalniz uygulama acikken calisir: ayri servis ya da zamanlanmis gorev yoktur; izleme uygulamanin
icindeki bir is parcacigidir ve pencere kapaninca durur. Uygulama acikken WATCH_SECONDS'de bir
izlenen koleksiyonlarin klasorleri taranir. Yeni bir dosya, boyutu iki tarama arasinda
degismeyince (kopyalama/indirme bitti) hazirlik kuyruguna girer; kuyruk doluysa sonraki turda
tekrar denenir. Uygulama kapaliyken klasore konan dosyalar, uygulama yeniden acildiginda ilk
turda yakalanir (koleksiyonun bilinen dosyalarinda 'known' yoklar). Izlenen koleksiyonlarin
e-posta kurallari da (F89), uygulama acikken, koleksiyon acik olmasa bile kontrol edilir.
"""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timedelta

import library
import mail_import
import speech
from bridge_mail import AUTO_MINUTES

WATCH_SECONDS = 30


class WatchMixin:
    _watch_thread = None

    def _start_watch(self):
        if self._watch_thread is not None:
            return
        self._watch_sizes = {}     # slug -> {dosya anahtari: boyut} (son tur)
        self._watch_pending = {}   # slug -> boyutu oturmasi beklenen yeni dosyalar
        self._watch_stop = threading.Event()
        self._watch_thread = threading.Thread(target=self._watch_loop, name='aktar-watch', daemon=True)
        self._watch_thread.start()

    def _stop_watch_for_close(self):
        """Pencere kapaninca izleme ve ekstre taramasi durur; uygulama kapaliyken hicbir sey calismaz."""
        if self._watch_thread is not None:
            self._watch_stop.set()
        self._subs_stop = True

    def _watch_loop(self):
        while not self._watch_stop.wait(WATCH_SECONDS):
            self._watch_tick()

    def _watch_tick(self):
        for slug, data in library.list_collections().items():
            if not data.get('watch'):
                self._watch_sizes.pop(slug, None)
                self._watch_pending.pop(slug, None)
                continue
            try:
                self._watch_mail(slug, data)
                self._watch_collection(slug)
            except Exception as error:  # bir koleksiyonun hatasi izlemeyi durdurmaz
                self._log(f'Klasör izleme ({data.get("title", slug)}): {error}')

    # ------------------------------------------------------------------ istek uzerine
    def library_set_watch(self, on):
        """Acik koleksiyonu izlemeye alir / birakir."""
        if self._lib_data is None:
            return {'error': 'Önce bir koleksiyon açın.'}
        self._lib_data['watch'] = bool(on)
        state = self._save_collection('Klasör izleme ' + ('açıldı: yeni dosyalar kendiliğinden hazırlanır.'
                                                           if on else 'kapatıldı.'))
        if on:
            self._start_watch()
        return state

    # ------------------------------------------------------------------ tur
    def _watch_mail(self, slug, data):
        rules = [rule for rule in mail_import.rules_of(data) if rule.get('enabled', True)]
        if not rules or self._mail_lock.locked() or not self._mail_password():
            return
        checked = mail_import.load_state(slug)['checked']
        try:
            if checked and datetime.now() - datetime.fromisoformat(checked) < timedelta(minutes=AUTO_MINUTES):
                return
        except ValueError:
            pass
        summary = self._mail_run(slug, rules)
        if summary.get('files'):
            self._emit('toast', {'message': f'{data["title"]}: {summary["message"]}', 'kind': 'ok'})

    def _watch_collection(self, slug):
        data = library.load_collection(slug)
        probe = copy.deepcopy(data)
        entries, _changed = library.scan(probe)
        sizes = {}
        for entry in entries:
            if entry['missing']:
                continue
            try:
                sizes[library._key(entry['path'])] = entry['path'].stat().st_size
            except OSError:
                continue
        previous = self._watch_sizes.get(slug)
        pending = self._watch_pending.setdefault(slug, set())
        if previous is None:  # ilk tur: uygulama kapaliyken gelenler
            known = {library._key(path) for path in data['known']}
            pending |= {key for key in sizes if key not in known}
        else:
            pending |= {key for key in sizes if key not in previous}
        pending &= set(sizes)  # silinenler
        self._watch_sizes[slug] = sizes
        stable = {key for key in pending if previous and previous.get(key) == sizes[key]}
        if not stable or self._queue_running():
            return
        targets = [entry for entry in entries if library._key(entry['path']) in stable]
        if slug == self._lib_slug:
            self._rescan()   # acik koleksiyon: listesi ve 'yeni' isaretleri guncellensin
        else:
            library.save_collection(probe, slug)
        pending -= stable
        self._watch_prepare(slug, data['title'], entries, targets, bool(data.get('frames')),
                            bool(data.get('speakers')))

    def _watch_prepare(self, slug, title, entries, targets, frames=False, speakers=False):
        """`frames`: koleksiyonda son 'Hepsini hazirla'da video goruntuleri secildiyse (F114);
        `speakers`: konusmacilar ayrilsin diye secildiyse (F146)."""
        plan = library.plan(targets)
        whisper = speech.available()[0]
        jobs = (list(plan['summary']) + list(plan['index']) + list(plan['document']) + list(plan['subtitle'])
                + list(plan['vision']) + (list(plan['whisper']) if whisper else []))
        for wanted, group in ((frames, 'frames'), (speakers, 'speakers')):
            if wanted:
                queued = {library._key(entry['path']) for entry in jobs}
                jobs += [entry for entry in plan[group] if library._key(entry['path']) not in queued]
        names = ', '.join(entry['path'].name for entry in targets[:3]) + (' …' if len(targets) > 3 else '')
        self._log(f'Klasör izleme · {title}: {len(targets)} yeni dosya ({names})')
        if jobs:
            videos = [entry['path'] for entry in entries if not entry['missing']]
            self._emit('toast', {'message': f'{title}: {len(targets)} yeni dosya bulundu, hazırlanıyor.', 'kind': 'info'})
            self._start_queue(jobs, whisper, True, (slug, title, videos), frames=frames, speakers=speakers)
        elif hasattr(self, '_subs_auto_scan'):
            self._subs_auto_scan(slug)  # hazirlik gerekmiyorsa ekstreler hemen okunur
