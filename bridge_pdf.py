"""PDF'den kitap (F138): taranmis PDF'i okuyup EPUB yapar; sonuc Okuma'ya ya da Kitap Cevir'e gider.

Sayfalar Ayarlar'daki OCR motoruyla okunur (library.vision_reader: Tesseract, OCR modeli ya da gorsel
model). Tesseract secili ise kitabin dili once birkac sayfadan anlasilir ve kitabin tamami tek dille
('tur' ya da 'eng') okunur. Is pencere icindeki bir is parcaciginda calisir; pencere kapaninca durur,
okunan sayfalar <PDF>-pdf/ocr altinda kalir ve bir sonraki sefer kaldigi yerden surer.
"""
from __future__ import annotations

import threading
from pathlib import Path

import documents
import library
import pdf_book
from app_core import GracefulStop, load_config


class PdfMixin:
    _pdf_job = None
    _pdf_stop = None

    def _pdf_running(self):
        job = self._pdf_job
        return job is not None and job.is_alive()

    def pdf_info(self, path=None):
        """PDF secer (yol verilmezse pencere acilir) ve bilgisini dondurur: sayfa, tahmini baslik/yazar,
        daha once okunan sayfa sayisi."""
        path = path or self._dialog('open_file', 'Taranmış PDF seç', ('PDF (*.pdf)',))
        if not path:
            return None
        pdf = Path(str(path))
        if pdf.suffix.lower() != '.pdf' or not pdf.is_file():
            return {'error': 'PDF dosyası değil: ' + str(path)}
        try:
            count = pdf_book.page_count(pdf)
            title, author = pdf_book.guess_title_author(pdf)
        except Exception as error:   # bozuk/sifreli PDF
            return {'error': f'PDF açılamadı: {error}'}
        work = pdf_book.work_dir(pdf)
        read = len({path.name[:4] for path in (work / 'ocr').glob('*.txt')}) if (work / 'ocr').is_dir() else 0
        cfg = load_config()
        engine = documents.ocr_engine(cfg)
        return {'path': str(pdf), 'name': pdf.name, 'pages': count, 'read': read, 'title': title, 'author': author,
                'work': str(work), 'engine': documents.READER_NAMES.get(engine, engine),
                'running': self._pdf_running()}

    def pdf_convert(self, path, title='', author='', target='reading'):
        """Arka planda: sayfalari okur, EPUB yazar. Ilerleme 'pdf_progress', sonuc 'pdf_done' olayiyla gelir.
        target: 'reading' (Okuma'ya eklenir) ya da 'books' (Kitap Cevir'de acilir)."""
        if self._pdf_running():
            return {'error': 'Bir PDF zaten okunuyor.'}
        pdf = Path(str(path))
        if not pdf.is_file():
            return {'error': 'PDF bulunamadı: ' + str(path)}
        stop = threading.Event()
        self._pdf_stop = stop

        def emit(stage, done=0, total=0):
            self._emit('pdf_progress', {'path': str(pdf), 'stage': stage, 'done': done, 'total': total})

        def work():
            try:
                cfg = dict(load_config())
                if documents.ocr_engine(cfg) == 'tesseract':
                    emit('Kitabın dili belirleniyor…')
                    language = pdf_book.sample_language(pdf, library.vision_reader(cfg, self._log))
                    cfg['tesseract_lang'] = 'tur' if language == 'tr' else 'eng'
                    self._log(f'PDF: kitap dili {language}; Tesseract dili {cfg["tesseract_lang"]}.')
                read = library.vision_reader(cfg, self._log)
                folder = pdf_book.work_dir(pdf)
                texts = pdf_book.read_pages(pdf, folder, read,
                                            lambda done, total: emit('Sayfalar okunuyor', done, total),
                                            stop.is_set, self._log)
                emit('Kitap oluşturuluyor…')
                epub, info = pdf_book.build_epub(pdf, folder, texts, title.strip() or None,
                                                 author.strip() if author is not None else None, log=self._log)
                result = {'path': str(pdf), 'epub': str(epub), 'target': target, **info}
                if target == 'reading':
                    added = self.shelf_add([str(epub)])
                    if added and added.get('added'):
                        result['book_id'] = added['added'][0]
                self._emit('pdf_done', result)
            except GracefulStop as error:
                self._emit('pdf_done', {'path': str(pdf), 'cancelled': True, 'error': str(error)})
            except Exception as error:
                self._log(f'HATA: PDF okunamadı: {error}')
                self._emit('pdf_done', {'path': str(pdf), 'error': str(error)})

        self._pdf_job = threading.Thread(target=work, name='aktar-pdf-book', daemon=True)
        self._pdf_job.start()
        return {'started': True}

    def pdf_cancel(self):
        stop = self._pdf_stop
        if stop is not None:
            stop.set()
        return True

    def _stop_pdf_for_close(self):
        if self._pdf_running():
            self.pdf_cancel()
            self._pdf_job.join(5)
