"""Yedekleme ve tasima (F239): Ayarlar > Gelismis > Yedekleme (Bridge'e karisan sinif). Olay 'backup'.

Yedek arka planda yazilir; geri yukleme baska is yokken yapilir ve sonrasinda Aktar yeniden baslatilmalidir (acik
sayfalar ve onbellekler eski veriyi tutar). Bulunamayan kitap/klasor yollari secilen klasorde aranip duzeltilir.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import app_core
import backup
from version import VERSION


def _error(error):
    return {'error': str(error)}


class BackupMixin:
    def _backup_running(self):
        job = getattr(self, '_backup_job', None)
        return job is not None and job.is_alive()

    def backup_info(self):
        """Yedege girecek gruplarin boyutu ve bu bilgisayarda bulunamayan yollar."""
        try:
            missing = backup.missing(app_core.APP_DIR)
            return {'groups': backup.sizes(app_core.APP_DIR), 'missing': {key: len(items) for key, items in missing.items()},
                    'running': self._backup_running(), 'folder': str(Path(app_core.APP_DIR) / backup.BACKUP_DIR)}
        except OSError as error:
            return _error(error)

    def backup_create(self, groups=()):
        """Kayit penceresi acilir; yedek arka planda yazilir (olay 'backup')."""
        if self._backup_running():
            return _error('Yedekleme zaten sürüyor.')
        name = f'aktar-yedek-{datetime.now().strftime("%Y-%m-%d")}.zip'
        target = self._dialog('save_file', 'Yedeği kaydet', name, ('Aktar yedeği (*.zip)',))
        if not target:
            return None
        target = Path(target) if str(target).lower().endswith('.zip') else Path(str(target) + '.zip')
        if Path(app_core.APP_DIR).resolve() in target.resolve().parents and target.parent.name != backup.BACKUP_DIR:
            return _error('Yedeği Aktar klasörünün içine değil, başka bir yere (ör. harici disk) kaydedin.')
        cancel = threading.Event()
        self._backup_cancel = cancel

        def progress(done, total):
            self._emit('backup', {'stage': 'create', 'done': done, 'total': total})

        def work():
            try:
                result = backup.create(app_core.APP_DIR, target, list(groups or ()), progress, cancel.is_set, VERSION)
                self._log(f'Yedek yazıldı: {result["path"]} ({result["files"]} dosya)')
                self._emit('backup', dict(result, stage='create', finished=True))
            except InterruptedError:
                self._emit('backup', {'stage': 'create', 'finished': True, 'cancelled': True})
            except Exception as error:
                self._log(f'UYARI: Yedek yazılamadı: {error}')
                self._emit('backup', {'stage': 'create', 'finished': True, 'error': str(error)})

        self._backup_job = threading.Thread(target=work, name='aktar-backup', daemon=True)
        self._backup_job.start()
        return {'started': True, 'path': str(target)}

    def backup_cancel(self):
        cancel = getattr(self, '_backup_cancel', None)
        if cancel is not None:
            cancel.set()
        return True

    def backup_choose(self):
        """Geri yuklenecek yedegi sectirir; bilgisini dondurur (henuz bir sey yazilmaz)."""
        path = self._dialog('open_file', 'Aktar yedeğini seç', ('Aktar yedeği (*.zip)',))
        if not path:
            return None
        try:
            return dict(backup.inspect(path), path=str(path))
        except ValueError as error:
            return _error(error)

    def backup_restore(self, path):
        """Yedegi geri yukler (bloklar; once mevcut veri yedeklenir). Arka planda is varken yapilmaz."""
        busy = [job['label'] for job in self._llm_job_list()]
        for name, label in (('_prepare_job', 'Ses hazırlama'), ('_audiobook_job', 'Sesli kitap kaydı'),
                            ('_backup_job', 'Yedekleme')):
            job = getattr(self, name, None)
            if job is not None and job.is_alive():
                busy.append(label)
        if busy:
            return _error('Önce şu işleri bitirin ya da durdurun: ' + ', '.join(busy) + '.')
        try:
            result = backup.restore(app_core.APP_DIR, path, VERSION)
        except (ValueError, OSError) as error:
            return _error(error)
        self._shelf_cache = None
        self._ui_text = None
        self._log(f'Yedek geri yüklendi: {path} ({result["files"]} dosya). Önceki veri: {result["before"]}')
        missing = backup.missing(app_core.APP_DIR)
        return dict(result, missing={key: len(items) for key, items in missing.items()})

    def backup_relink(self):
        """Bulunamayan kitap ve koleksiyon yollarini secilen klasorde arar."""
        folder = self._dialog('open_folder', 'Kitapların ve videoların bulunduğu klasörü seç')
        if not folder:
            return None
        try:
            result = backup.relink(app_core.APP_DIR, folder)
        except OSError as error:
            return _error(error)
        self._shelf_cache = None
        return result

    def backup_open_folder(self):
        folder = Path(app_core.APP_DIR) / backup.BACKUP_DIR
        folder.mkdir(parents=True, exist_ok=True)
        return self.reveal(str(folder))
