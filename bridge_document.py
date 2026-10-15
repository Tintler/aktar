"""Belge goruntuleyici + tek belgeye soru sor arka ucu (Bridge'e karisan sinif; eski doc_view).

PDF sayfalari media_server'dan PNG olarak gelir (pdfium cizer); diger belgeler (metin, Word,
tablo, e-kitap) documents.pages_of ile ayni sayfa numaralandirmasinda duz metin olarak
gonderilir; gorseller dosya olarak. Belge acilinca metni cikarilir (embedding modeli
seciliyse indekslenir); kisa belgede metnin tamami, uzun belgede ilgili parcalar modele gider.
Cevaptaki s.N atiflari belgeyi o sayfaya goturur. Kaynak dosya SALT-OKUNUR.
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

import chat_templates
import collection_qa
import documents
import library
from app_core import WINDOWS, load_config
from bridge_library import chat_entries, reasoning_feed

VISION_PAGES_ON_OPEN = 20  # acilista gorsel modelle okunacak en fazla taranmis sayfa
GREETING = ('Bu belgeye soru sorun; cevaplar hangi sayfada geçtiğini gösterir. '
            'Sayfa atfına tıklayınca belge o sayfaya gider.')


class DocumentSession:
    def __init__(self, path):
        self.path = Path(path)
        self.kind = documents.kind_of(self.path)
        self.key = library.file_chat_key(self.path)
        saved = library.load_chat(self.key)   # onceki acilistan kalan sohbet
        self.entries = [('note', GREETING)] + saved['entries']
        self.history = saved['history']
        self.session = None
        self.ready = False
        self.asking = False
        self.note = 'Belge hazırlanıyor…'
        self.cancelled = threading.Event()


class DocumentMixin:
    def _init_document(self):
        self._doc = None

    def _doc_chat(self, doc):
        return {'entries': chat_entries(doc.entries), 'ready': doc.ready, 'asking': doc.asking,
                'note': 'Cevap hazırlanıyor…' if doc.asking else doc.note,
                'enabled': doc.ready and not doc.asking and doc.session is not None}

    def _push_doc(self, doc):
        if doc is self._doc:
            self._emit('document', {'path': str(doc.path), 'chat': self._doc_chat(doc)})

    def doc_open(self, path):
        """Belgeyi acar: {'kind', 'pages', ...} + sohbet; ayni belge aciksa sohbet korunur."""
        path = Path(str(path))
        if not path.is_file():
            return {'error': 'Dosya bulunamadı: ' + str(path)}
        if self._doc is None or self._doc.path != path:
            if self._doc is not None:
                self._doc.cancelled.set()
            self._doc = DocumentSession(path)
            self._start_doc_prepare(self._doc)
        doc = self._doc
        result = {'path': str(path), 'name': path.name, 'kind': doc.kind, 'chat': self._doc_chat(doc)}
        try:
            if doc.kind == 'image':
                result.update(pages=1, image=self._media.file_url(path))
            elif doc.kind == 'pdf':
                renderer = documents.PdfRenderer(path)
                try:
                    sizes = [renderer_size(renderer, index) for index in range(renderer.page_count())]
                finally:
                    renderer.close()
                result.update(pages=len(sizes), sizes=sizes,
                              page_url=self._media.page_url(path, 1).rsplit('/', 1)[0])
            else:
                texts = documents.pages_of(path)
                result.update(pages=max(1, len(texts)), texts=texts or [''])
        except (ValueError, RuntimeError, OSError) as error:
            return {'error': 'Belge açılamadı: ' + str(error)}
        return result

    def _start_doc_prepare(self, doc):
        """Metni cikarir (gerekirse gorsel modelle); embedding modeli varsa indeksler.

        Uzun taranmis PDF'ler (VISION_PAGES_ON_OPEN sayfadan fazla) acilista okunmaz;
        'Hepsini hazirla'ya birakilir."""
        log = lambda message: self._log('[Belge] ' + str(message))  # noqa: E731

        reader = ['görü modeli']  # F91: secili OCR motorunun adi (cfg okununca)

        def progress(done, total):
            if not doc.ready:
                doc.note = f'{reader[0][0].upper() + reader[0][1:]} ile okunuyor… {done}/{total}'
                self._push_doc(doc)

        def work():
            entry = {'path': doc.path, 'kind': 'image' if doc.kind == 'image' else 'document',
                     'root': None, 'missing': False, 'new': False}
            try:
                cfg = load_config()
                reader[0] = documents.reader_name(cfg, doc.kind == 'image')
                scanned = len(documents.scanned_pages(doc.path)) if doc.kind == 'pdf' else 0
                allow = scanned <= VISION_PAGES_ON_OPEN
                if doc.kind == 'image' or (scanned and allow):
                    progress(0, max(1, scanned))
                try:
                    library.transcribe(entry, cfg, log=log, allow_vision=allow, vision_progress=progress,
                                       cancelled=doc.cancelled.is_set)
                except documents.NoTextError:
                    if allow:
                        raise
                    raise documents.NoTextError(
                        f'taranmış belge ({scanned} sayfa); kütüphanede "Hepsini hazırla" ile '
                        'okutun.') from None
                if str(cfg.get('embedding_model', '')).strip():
                    try:
                        library.index(entry, cfg, log=log)
                    except (RuntimeError, ValueError, OSError) as error:
                        log('Belge indekslenemedi (kısa belgede gerekmez): ' + str(error))
                session = collection_qa.CollectionQA([doc.path], doc.path.stem, log=log)
                fits = session.whole_hits(cfg) is not None
                model = str(cfg.get('embedding_model', '')).strip()
                if fits or model:
                    session.history = list(doc.history)
                    doc.session = session
                    doc.ready = True
                    doc.note = '' if fits else 'Uzun belge: soruyla ilgili bölümler aranarak cevaplanır.'
                else:
                    doc.note = ('Belge tek seferde modele sığmayacak kadar uzun; soru sormak için '
                                'Ayarlar → Kütüphane indeksi\'nden embedding modeli seçin.')
            except Exception as error:  # metin yoksa / okunamazsa sohbet kapali kalir
                doc.note = 'Bu belgeye soru sorulamıyor: ' + str(error)
            self._push_doc(doc)

        threading.Thread(target=work, name='aktar-doc-prepare', daemon=True).start()

    def doc_ask(self, question, think=None, template=None):
        doc = self._doc
        text = ' '.join(str(question or '').split())
        if doc is None or not text or not doc.ready or doc.asking or doc.session is None:
            return self._doc_chat(doc) if doc else None
        doc.asking = True
        doc.entries += [('user', text), ('pending', 'Cevap hazırlanıyor…')]
        instructions, name = chat_templates.instruction(template)

        def work():
            turn, error = None, ''
            try:
                turn = doc.session.ask(text, think=think, on_reasoning=reasoning_feed(
                    lambda: doc.entries, lambda: self._push_doc(doc)),
                    instructions=instructions, template=name)
            except Exception as failure:  # baglanti/model hatasi sohbete yazilir
                error = str(failure)
            doc.entries = [item for item in doc.entries if item[0] != 'pending']
            doc.entries.append(('assistant', turn) if turn is not None else ('error', 'Cevap alınamadı: ' + error))
            doc.history = doc.session.history
            library.save_chat(doc.key, doc.entries, doc.history)
            if error:
                self._log('[Belge] Cevap alınamadı: ' + error)
            doc.asking = False
            self._push_doc(doc)

        threading.Thread(target=work, name='aktar-doc-ask', daemon=True).start()
        return self._doc_chat(doc)

    def doc_clear_chat(self):
        """Acik belgenin sohbetini ve kayitli gecmisini siler."""
        doc = self._doc
        if doc is None or doc.asking:
            return self._doc_chat(doc) if doc else None
        library.clear_chat(doc.key)
        doc.entries = [('note', GREETING)]
        doc.history = []
        if doc.session is not None:
            doc.session.history = []
        return self._doc_chat(doc)

    def open_external(self, path):
        """Dosyayi isletim sisteminin varsayilan uygulamasinda acar."""
        path = Path(str(path))
        if not path.exists():
            return {'error': 'Bulunamadı: ' + str(path)}
        try:
            if WINDOWS:
                os.startfile(str(path))  # noqa: S606 - kullanicinin kendi dosyasi
            else:
                subprocess.Popen(['xdg-open', str(path)])
        except OSError as error:
            return {'error': str(error)}
        return True

    def _stop_document_for_close(self):
        if self._doc is not None:
            self._doc.cancelled.set()


def renderer_size(renderer, index):
    """PDF sayfasinin en/boy orani (goruntuleyicide yer tutucu yuksekligi icin)."""
    with documents._PDFIUM:
        page = renderer.document[index]
        try:
            width, height = page.get_size()
        finally:
            page.close()
    return round(height / max(width, 1.0), 4)
