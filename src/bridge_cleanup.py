"""Temizlik (F242): Ayarlar > Gelismis > Temizlik ve 'Kitapliktan kaldir'in kayitlariyla silme secenegi.

Listeleme (cleanup.find) hicbir seyi silmez; silme yalnizca kullanicinin sectigi kimliklerle ve arka planda kitapla
ilgili is yokken yapilir. Silinen kayitlarin bellekteki onbellekleri (duygu etiketleri, karakter sesleri, gorseller,
kitaplik) birakilir.
"""
from __future__ import annotations

import app_core
import cleanup


def _error(error):
    return {'error': str(error)}


class CleanupMixin:
    def _cleanup_busy(self):
        """Kayitlari kullanan arka plan isleri (etiket, karakter, ozet, gorsel, ses hazirlama, sesli kitap, yedek)."""
        busy = [job['label'] for job in self._llm_job_list()]
        for name, label in (('_prepare_job', 'Ses hazırlama'), ('_audiobook_job', 'Sesli kitap kaydı'),
                            ('_backup_job', 'Yedekleme'), ('_emotion_job', 'Duygu etiketleri'),
                            ('_art_job', 'Kitap görselleri')):
            if label in busy:
                continue
            job = getattr(self, name, None)
            if job is not None and job.is_alive():
                busy.append(label)
        return busy

    def _cleanup_forget(self):
        for name in ('_emotion_cache', '_cast_cache', '_art_cache', '_shelf_cache'):
            setattr(self, name, None)

    def cleanup_scan(self):
        """Temizlenebilecek kayitlar (cleanup.find); hicbir sey silinmez."""
        try:
            return cleanup.find(app_core.APP_DIR)
        except OSError as error:
            return _error(error)

    def cleanup_remove(self, ids):
        """Secilen kayitlari siler; dosyasi bulunamayan kitap kitapliktan da kaldirilir. Donen: sonuc + yeni liste."""
        busy = self._cleanup_busy()
        if busy:
            return _error('Önce şu işleri bitirin ya da durdurun: ' + ', '.join(busy) + '.')
        try:
            result = cleanup.remove(app_core.APP_DIR, list(ids or ()))
            for book in result['books']:
                self._shelf().remove(book)
        except (OSError, ValueError) as error:
            return _error(error)
        finally:
            self._cleanup_forget()
        self._log(f'Temizlik: {result["removed"]} kayıt silindi ({result["files"]} dosya, '
                  f'{result["bytes"] / 1e6:.1f} MB).')
        return dict(result, scan=self.cleanup_scan(), shelf=self.shelf_list())

    def shelf_book_data(self, book_id):
        """Kitabin diskteki kayitlari (Kitapliktan kaldir sorusu icin): [{'kind', 'label', 'files', 'bytes'}]."""
        try:
            return cleanup.book_parts(app_core.APP_DIR, book_id)
        except OSError:
            return []

    def shelf_remove_with_data(self, book_id):
        """Kitabi kitapliktan kaldirir ve kayitlarini (sesler, etiketler, karakterler, ozet, gorseller) siler."""
        busy = self._cleanup_busy()
        if busy:
            return _error('Önce şu işleri bitirin ya da durdurun: ' + ', '.join(busy) + '.')
        try:
            result = cleanup.remove_book_data(app_core.APP_DIR, book_id)
            self._shelf().remove(book_id)
        except (OSError, ValueError) as error:
            return _error(error)
        finally:
            self._cleanup_forget()
        self._log(f'Kitap kayıtlarıyla kaldırıldı ({result["files"]} dosya, {result["bytes"] / 1e6:.1f} MB).')
        return self.shelf_list()
