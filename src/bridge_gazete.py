"""Gazete (F225): gunluk sayiyi makalelere ayirma, duzeltme, seslendirme ve telefon sunucusu.

Is mantigi gazete.py (sayi, makale onerisi, kutu OCR), gazete_match.py (kamera karesi eslestirme) ve
gazete_server.py'de (yerel ag sunucusu). Arka plan isi (iceri aktarma + oneri + OCR ya da seslendirme)
tek seferde biri calisir; ilerleme ve sonuc 'gazete' olayiyla gelir. Pencere kapaninca is ve sunucu durur.
Tercihler ui.json 'gazete': {current: telefonun gordugu sayi, voice, port}.
"""
from __future__ import annotations

import threading

import gazete
import gazete_server
import text_speech
from app_core import GracefulStop
from tts import Cancelled
from version import VERSION

DEFAULT_VOICE = 'ema-lightning/default'
ARTICLE_KEYS = ('title', 'edited', 'reviewed')


def _error(error):
    return {'error': str(error)}


class GazeteMixin:
    _gazete_job = None
    _gazete_stop = None
    _gazete_server = None
    _gazete_index = None     # (sayi adi, sayfa surumu, PageIndex)
    _gazete_lock = None

    # ------------------------------------------------------------------ yardimcilar
    def _gazete_prefs(self):
        value = self.ui_prefs().get('gazete')
        return value if isinstance(value, dict) else {}

    def _gazete_set_prefs(self, **values):
        self.save_ui_prefs({'gazete': {**self._gazete_prefs(), **values}})

    def _gazete_running(self):
        job = self._gazete_job
        return job is not None and job.is_alive()

    def _gazete_call(self, action):
        try:
            return action()
        except (ValueError, OSError, KeyError) as error:
            return _error(error)

    def _gazete_view(self, name, data=None):
        """Arayuz icin sayi: sayfa goruntusu adresleri ve makaleler."""
        data = data or gazete.load(name)
        pages = []
        for info in data.get('pages', []):
            path = gazete.page_path(name, info['page'])
            try:
                url = self._media.file_url(path)
            except Exception:
                url = ''
            pages.append(dict(info, url=url))
        return {'name': name, 'title': data.get('title', name), 'pages': pages, 'articles': data.get('articles', []),
                'current': self._gazete_current() == name, 'running': self._gazete_running()}

    def _gazete_current(self):
        """Telefonun gordugu sayi: secilen, yoksa en yenisi."""
        chosen = self._gazete_prefs().get('current')
        names = [item['name'] for item in gazete.list_issues()]
        if chosen in names:
            return chosen
        return names[0] if names else None

    def _gazete_article(self, data, article_id):
        article = next((a for a in data.get('articles', []) if a['id'] == article_id), None)
        if article is None:
            raise ValueError('Makale bulunamadı.')
        return article

    # ------------------------------------------------------------------ sayilar
    def gazete_list(self):
        return {'issues': gazete.list_issues(), 'current': self._gazete_current(), 'running': self._gazete_running(),
                'server': self._gazete_server_state()}

    def gazete_open(self, name):
        return self._gazete_call(lambda: self._gazete_view(name))

    def gazete_choose(self, kind='folder'):
        """Kaynak secer: 'folder' (sayfa goruntuleri klasoru) ya da 'pdf'."""
        if kind == 'pdf':
            path = self._dialog('open_file', 'E-gazete PDF dosyasını seç', ('PDF (*.pdf)',))
        else:
            path = self._dialog('open_folder', 'Gazete sayfalarının bulunduğu klasörü seç')
        if isinstance(path, (list, tuple)):
            path = path[0] if path else None
        return {'path': str(path)} if path else None

    def gazete_import(self, path, name='', title=''):
        """Arka planda: sayfalar kaydedilir, makalesi olmayan her sayfa icin makale onerilir ve okunur."""
        if self._gazete_running():
            return {'error': 'Gazete için başka bir iş sürüyor.'}
        try:
            gazete.source_pages(path)
        except ValueError as error:
            return _error(error)
        stop = threading.Event()
        self._gazete_stop = stop

        def emit(**values):
            self._emit('gazete', values)

        def work():
            issue = None
            try:
                emit(stage='Sayfalar kaydediliyor', done=0, total=0)
                issue = gazete.create(path, name or None, title or None,
                                      lambda done, total: emit(stage='Sayfalar kaydediliyor', done=done, total=total),
                                      stop.is_set)
                self._gazete_index = None
                self._propose_pages(issue, None, stop, emit)
                emit(finished=True, name=issue)
                self._log(f'Gazete: {issue} hazırlandı.')
            except GracefulStop:
                emit(finished=True, name=issue, cancelled=True)
            except Exception as error:
                self._log(f'HATA: Gazete hazırlanamadı: {error}')
                emit(finished=True, name=issue, error=str(error))

        self._gazete_job = threading.Thread(target=work, name='aktar-gazete', daemon=True)
        self._gazete_job.start()
        return {'started': True}

    # ------------------------------------------------------------------ okuma modelleri (F226)
    def _gazete_model_names(self, cfg):
        """(OCR modeli, dil modeli): ui.json gazete.ocr_model / layout_model; yoksa Ayarlar'daki OCR modeli ve
        sohbet modeli. Bos metin: o adim modelsiz (Tesseract / kurallar)."""
        prefs = self._gazete_prefs()
        ocr = prefs.get('ocr_model')
        layout = prefs.get('layout_model')
        ocr = str(cfg.get('ocr_model') or '' if ocr is None else ocr).strip()
        layout = str(cfg.get('model') or '' if layout is None else layout).strip()
        return ocr, layout

    def _gazete_models(self, keep=False):
        """Sunucuda bulunan modellerle okuyucular: {read, read_name, ask, client, loaded}. Sunucuya
        ulasilamazsa ya da model yoksa o adim Tesseract'a / kurallara kalir (gunluge yazilir).
        keep: modeller LM Studio'da yuklu degilse bir kez yuklenir (sayfalar arasinda bosaltilip yeniden
        yuklenmesin); loaded yalnizca bu cagrinin yukledikleri, is bitince bunlar bosaltilir."""
        import gazete_model
        from app_core import Client, keep_loaded, load_config
        result = {'read': None, 'read_name': '', 'ask': None, 'client': None, 'loaded': []}
        try:
            cfg = load_config()
            ocr, layout = self._gazete_model_names(cfg)
            if not ocr and not layout:
                return result
            client = Client(dict(cfg, disable_thinking=True), log=self._log)
            available = set(client.models())
        except (RuntimeError, ValueError, OSError) as error:
            self._log(f'Gazete: model sunucusuna ulaşılamadı, Tesseract ile okunuyor ({error}).')
            return result
        for model, what in ((ocr, 'OCR modeli'), (layout, 'Dil modeli')):
            if model and model not in available:
                self._log(f'Gazete: {what} sunucuda yok ({model}); bu adım modelsiz yapılıyor.')
        ocr = ocr if ocr in available else ''
        layout = layout if layout in available else ''
        result['client'] = client
        if keep:
            result['loaded'] = keep_loaded(client, [ocr, layout], self._log)
        if ocr:
            result['read'] = gazete_model.reader(client, ocr, str(cfg.get('ocr_model_prompt') or 'Text Recognition:'))
            result['read_name'] = ocr

        if layout:
            def ask(prompt, png=None):
                if png:
                    return client.vision(prompt, png, model=layout, max_tokens=gazete_model.MAX_TOKENS)
                return client.chat([{'role': 'user', 'content': prompt}], temperature=0,
                                   max_tokens=gazete_model.MAX_TOKENS)
            if layout != client.cfg.get('model'):
                client.cfg = dict(client.cfg, model=layout)   # chat() cfg['model'] ile ister
            result['ask'] = ask
        return result

    def gazete_reading(self):
        """Okuma modelleri: {ocr_model, layout_model, page_layout, layout_available}; bos metin = modelsiz
        (Tesseract / kurallar). page_layout (F227): 'model' (PP-DocLayoutV3, varsayilan) | 'tesseract'."""
        import gazete_layout
        from app_core import load_config
        try:
            ocr, layout = self._gazete_model_names(load_config())
        except (ValueError, OSError) as error:
            return _error(error)
        return {'ocr_model': ocr, 'layout_model': layout, 'page_layout': self._gazete_page_layout(),
                'layout_available': gazete_layout.available()}

    def gazete_set_reading(self, ocr_model=None, layout_model=None, page_layout=None):
        values = {key: ' '.join(str(value).split()) for key, value in
                  (('ocr_model', ocr_model), ('layout_model', layout_model)) if value is not None}
        if page_layout in ('model', 'tesseract'):
            values['page_layout'] = page_layout
        self._gazete_set_prefs(**values)
        return self.gazete_reading()

    def _gazete_page_layout(self):
        return 'tesseract' if self._gazete_prefs().get('page_layout') == 'tesseract' else 'model'

    def _gazete_layout(self, stop, emit):
        """F227: sayfa yerlesim modeli (gazete_layout.regions) ya da None (Tesseract bloklari). Model ilk
        kullanimda iner; inemezse ya da onnxruntime yoksa Tesseract'a donulur."""
        import gazete_layout
        if self._gazete_page_layout() != 'model':
            return None
        if not gazete_layout.available():
            self._log('Gazete: sayfa yerleşim modeli için onnxruntime gerekir; sayfa Tesseract ile bölünüyor.')
            return None
        try:
            gazete_layout.ensure_model(self._log, lambda done, total: emit(
                stage='Sayfa yerleşim modeli indiriliyor (MB)', done=done >> 20, total=total >> 20), stop.is_set)
        except RuntimeError as error:
            self._log(f'UYARI: {error} Sayfa Tesseract ile bölünüyor.')
            return None
        return gazete_layout.regions

    def _gazete_read(self, name, article):
        """Elle duzeltmeden sonra makaleyi okur: OCR modeli varsa onunla, yoksa Tesseract."""
        models = self._gazete_models()
        if models['read']:
            return gazete.read_article(name, article, models['read'], self._log, model=True)
        return gazete.read_article(name, article, log=self._log)

    def _propose_pages(self, name, pages, stop, emit):
        """Verilen sayfalar (None: makalesi olmayan tum sayfalar) icin oneri + OCR. Gozden gecirilmis
        (reviewed) makalelere dokunulmaz; o sayfadaki diger otomatik makaleler yenilenir."""
        import gazete_layout
        from app_core import unload_models
        data = gazete.load(name)
        if pages is None:
            taken = {a['page'] for a in data.get('articles', [])}
            pages = [p['page'] for p in data.get('pages', []) if p['page'] not in taken]
        if not pages:
            return
        reader = gazete.ocr_reader(log=self._log)
        low = gazete.ocr_reader(log=self._log, psm='11')
        layout = self._gazete_layout(stop, emit)
        emit(stage='Okuma modelleri hazırlanıyor', done=0, total=len(pages))
        models = self._gazete_models(keep=True)
        read = models['read']
        boxes = read or gazete.ocr_reader(log=self._log, psm='3', tsv=False)
        try:
            for done, page in enumerate(pages):
                if stop.is_set():
                    raise GracefulStop('Durduruldu.')
                emit(stage='Makaleler bulunup okunuyor', done=done, total=len(pages), page=page)
                found = gazete.propose(name, page, reader, low, self._log, read, models['read_name'], models['ask'],
                                       layout)
                articles = []
                for item in found:
                    if stop.is_set():
                        raise GracefulStop('Durduruldu.')
                    article = {'page': page, 'head': item['head'], 'boxes': item['boxes'], 'title': item['title'],
                               'auto': True}
                    gazete.read_article(name, article, boxes, self._log, model=bool(read), title=not item.get('titled'))
                    articles.append(article)
                data = gazete.load(name)   # arayuzde bu arada yapilan duzeltmeler kaybolmasin
                data['articles'] = [a for a in data.get('articles', []) if a['page'] != page or a.get('reviewed')]
                keep = [a for a in data['articles'] if a['page'] == page]
                for article in articles:
                    if any(gazete._overlaps(article['head'] or article['boxes'][0], a.get('head') or a['boxes'][0])
                           for a in keep):
                        continue
                    article['id'] = gazete.new_id(data)
                    data['articles'].append(article)
                gazete.save(name, data)
                emit(page_done=page, name=name)
        finally:
            gazete_layout.unload()
            if models['loaded']:
                unload_models(models['client'], models['loaded'])
        emit(stage='Makaleler bulunup okunuyor', done=len(pages), total=len(pages))

    def gazete_propose(self, name, page):
        """Bir sayfanin makalelerini yeniden onerir (gozden gecirilmisler kalir). Arka planda."""
        if self._gazete_running():
            return {'error': 'Gazete için başka bir iş sürüyor.'}
        stop = threading.Event()
        self._gazete_stop = stop

        def emit(**values):
            self._emit('gazete', values)

        def work():
            try:
                self._propose_pages(name, [int(page)], stop, emit)
                emit(finished=True, name=name)
            except GracefulStop:
                emit(finished=True, name=name, cancelled=True)
            except Exception as error:
                self._log(f'HATA: Sayfa yeniden bölünemedi: {error}')
                emit(finished=True, name=name, error=str(error))

        self._gazete_job = threading.Thread(target=work, name='aktar-gazete', daemon=True)
        self._gazete_job.start()
        return {'started': True}

    def gazete_rename(self, name, title):
        def run():
            data = gazete.load(name)
            data['title'] = str(title or '').strip() or name
            gazete.save(name, data)
            return self._gazete_view(name, data)
        return self._gazete_call(run)

    def gazete_delete(self, name):
        if self._gazete_running():
            return {'error': 'Gazete için bir iş sürüyor.'}
        def run():
            gazete.delete(name)
            self._gazete_index = None
            return self.gazete_list()
        return self._gazete_call(run)

    def gazete_set_current(self, name):
        def run():
            gazete.load(name)
            self._gazete_set_prefs(current=name)
            self._gazete_index = None
            return self.gazete_list()
        return self._gazete_call(run)

    # ------------------------------------------------------------------ makale duzeltme
    def _gazete_edit(self, name, change):
        """change(data) makaleyi degistirir ve donen makaleyi (ya da None) verir; sayi kaydedilir."""
        def run():
            data = gazete.load(name)
            change(data)
            gazete.save(name, data)
            return self._gazete_view(name, data)
        return self._gazete_call(run)

    def _page_info(self, data, page):
        info = next((p for p in data.get('pages', []) if p['page'] == int(page)), None)
        if info is None:
            raise ValueError('Sayfa bulunamadı.')
        return info

    def gazete_save_article(self, name, article_id, values):
        """Baslik, duzeltilmis metin (None: OCR'a don) ve 'gozden gecirildi' isareti."""
        def change(data):
            article = self._gazete_article(data, article_id)
            values_ = dict(values or {})
            if 'title' in values_:
                title = ' '.join(str(values_['title'] or '').split())
                if title != article.get('title'):
                    article['title'] = title
                    article['title_edited'] = True
            if 'edited' in values_:
                edited = values_['edited']
                article['edited'] = None if edited is None or str(edited).strip() == article.get('text', '').strip() \
                    else str(edited).strip()
                if article['edited'] is None:
                    article.pop('edited')
            if 'reviewed' in values_:
                article['reviewed'] = bool(values_['reviewed'])
                article.pop('auto', None)
            if article.get('audio') and article['audio'] != gazete.audio_path(name, article, self._gazete_voice()).name:
                article.pop('audio')   # metin degisti: ses yeniden uretilmeli
        return self._gazete_edit(name, change)

    def gazete_set_boxes(self, name, article_id, head, boxes):
        """Baslik kutusu ve govde kutulari (okuma sirasinda); kutular degisince makale yeniden okunur."""
        def change(data):
            article = self._gazete_article(data, article_id)
            info = self._page_info(data, article['page'])
            article['head'] = gazete.clean_box(head, info) if head else None
            article['boxes'] = [gazete.clean_box(box, info) for box in boxes or ()]
            if not article['boxes'] and not article['head']:
                raise ValueError('Makalede en az bir kutu olmalı.')
            article.pop('auto', None)
            self._gazete_read(name, article)
        return self._gazete_edit(name, change)

    def gazete_add_article(self, name, page, box):
        """Cizilen kutudan yeni makale (kutu govde olur; baslik metnin ilk satirindan)."""
        def change(data):
            info = self._page_info(data, page)
            article = {'id': gazete.new_id(data), 'page': int(page), 'head': None,
                       'boxes': [gazete.clean_box(box, info)], 'title': ''}
            self._gazete_read(name, article)
            first, _sep, rest = article['text'].partition('\n\n')
            if len(first) <= 90 and rest:
                article['title'], article['text'] = first, rest
            data['articles'].append(article)
        return self._gazete_edit(name, change)

    def gazete_merge(self, name, article_id, into_id):
        """article_id'nin kutulari into_id'ye eklenir (devam eden makale, bolunmus oneri)."""
        def change(data):
            source = self._gazete_article(data, article_id)
            target = self._gazete_article(data, into_id)
            if source is target:
                raise ValueError('Makale kendisiyle birleştirilemez.')
            if source['page'] != target['page']:
                raise ValueError('Yalnızca aynı sayfadaki makaleler birleştirilir.')
            target['boxes'] = target['boxes'] + ([source['head']] if source.get('head') else []) + source['boxes']
            target.pop('auto', None)
            data['articles'].remove(source)
            self._gazete_read(name, target)
        return self._gazete_edit(name, change)

    def gazete_delete_article(self, name, article_id):
        def change(data):
            data['articles'].remove(self._gazete_article(data, article_id))
            gazete.prune_audio(name, data)
        return self._gazete_edit(name, change)

    def gazete_reread(self, name, article_id):
        def change(data):
            self._gazete_read(name, self._gazete_article(data, article_id))
        return self._gazete_edit(name, change)

    # ------------------------------------------------------------------ ses
    def _gazete_voice(self):
        return str(self._gazete_prefs().get('voice') or DEFAULT_VOICE)

    def gazete_set_voice(self, voice):
        self._gazete_set_prefs(voice=str(voice or ''))
        return {'voice': self._gazete_voice()}

    def gazete_voice(self, name, reviewed_only=False):
        """Arka planda: sesi olmayan (ya da metni degismis) makaleler seslendirilir (MP3)."""
        if self._gazete_running():
            return {'error': 'Gazete için başka bir iş sürüyor.'}
        running = getattr(self, '_tool_running', None)
        if (running is not None and running() and self._tool['kind'] in ('dub', 'dubgen')) \
                or self._audiobook_running() or self._speech_running():
            return {'error': 'Ses motoru şu an başka bir iş için kullanılıyor.'}
        voice = self._gazete_voice()
        override = self._voice_override(voice)
        if override is None:
            return {'error': 'Gazete sesi bulunamadı: ' + voice}
        language = self._override_language(override, 'tr')
        cancel = threading.Event()
        self._gazete_stop = cancel

        def emit(**values):
            self._emit('gazete', values)

        def work():
            try:
                data = gazete.load(name)
                todo = [a for a in data.get('articles', []) if (a.get('reviewed') or not reviewed_only)
                        and gazete.spoken(a) and not (gazete.audio_file(name, a)
                                                      and a.get('audio') == gazete.audio_path(name, a, voice).name)]
                emit(stage='Ses motoru yükleniyor', done=0, total=len(todo))
                if todo:
                    error = self._load_and_wait(language, override, cancel)
                    if cancel.is_set():
                        raise Cancelled('Durduruldu.')
                    if error:
                        raise RuntimeError(error)
                engines = self._engines()
                limit = engines.group_chars(language, override)
                for done, article in enumerate(todo):
                    if cancel.is_set():
                        raise Cancelled('Durduruldu.')
                    emit(stage='Makaleler seslendiriliyor', done=done, total=len(todo), article=article['id'])
                    parts, breaks = gazete.sentences(gazete.spoken(article))
                    groups = text_speech.group(text_speech.clean(parts), limit, breaks)
                    target = gazete.audio_path(name, article, voice)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    text_speech.write(engines, groups, 1.0, target, language, override, cancel=cancel)
                    data = gazete.load(name)
                    for item in data['articles']:
                        if item['id'] == article['id'] and gazete.audio_key(item, voice) == gazete.audio_key(article, voice):
                            item['audio'] = target.name
                    gazete.save(name, data)
                    emit(article_done=article['id'], name=name)
                gazete.prune_audio(name, gazete.load(name))
                emit(finished=True, name=name, voiced=len(todo))
                self._log(f'Gazete: {len(todo)} makale seslendirildi.')
            except Cancelled:
                emit(finished=True, name=name, cancelled=True)
            except Exception as error:
                self._log(f'HATA: Gazete seslendirilemedi: {error}')
                emit(finished=True, name=name, error=str(error))

        self._gazete_job = threading.Thread(target=work, name='aktar-gazete-voice', daemon=True)
        self._gazete_job.start()
        return {'started': True, 'total': None}

    def gazete_audio_url(self, name, article_id):
        """Arayuzde dinlemek icin makalenin sesi."""
        def run():
            article = self._gazete_article(gazete.load(name), article_id)
            path = gazete.audio_file(name, article)
            return {'url': self._media.file_url(path) if path else ''}
        return self._gazete_call(run)

    def gazete_cancel(self):
        stop = self._gazete_stop
        if stop is not None:
            stop.set()
        return True

    # ------------------------------------------------------------------ telefon sunucusu
    def _gazete_server_state(self):
        server = self._gazete_server
        info = server.info() if server else {'running': False, 'port': None, 'code': '', 'addresses': []}
        info['phones'] = gazete_server.Phones(gazete.root() / 'telefonlar.json').listing()
        info['default_port'] = int(self._gazete_prefs().get('port') or gazete_server.DEFAULT_PORT)
        return info

    def _gazete_page_index(self, name):
        """Sayinin eslestirme dizini; bir kez kurulur (20 sayfada birkac saniye), sayfalar degisince yenilenir."""
        import gazete_match
        if self._gazete_lock is None:
            self._gazete_lock = threading.Lock()
        with self._gazete_lock:
            data = gazete.load(name)
            version = tuple((p['page'], p['width'], p['height']) for p in data.get('pages', []))
            cached = self._gazete_index
            if cached is None or cached[0] != name or cached[1] != version:
                self._log(f'Gazete: {name} sayfaları eşleştirme için hazırlanıyor…')
                cached = (name, version, gazete_match.load_index(name))
                self._gazete_index = cached
        return cached[2]

    def _gazete_locate(self, name, frame, point):
        import gazete_match
        return self._gazete_page_index(name).locate(gazete_match.decode(frame), point)

    def gazete_server_start(self, port=None):
        try:
            import gazete_match
            gazete_match._cv()
        except ImportError as error:
            return _error(error)
        if self._gazete_server is None:
            mixin = self

            class Backend:
                def current(self):
                    name = mixin._gazete_current()
                    return (name, gazete.load(name)) if name else (None, None)

                def locate(self, name, frame, point):
                    return mixin._gazete_locate(name, frame, point)

                def audio(self, name, article):
                    return gazete.audio_file(name, article)

                def article_at(self, data, page, x, y):
                    return gazete.article_at(data, page, x, y)

                def text(self, article):
                    return gazete.spoken(article)

            self._gazete_server = gazete_server.GazeteServer(
                Backend(), gazete_server.Phones(gazete.root() / 'telefonlar.json'), VERSION, self._log)
        port = int(port or self._gazete_prefs().get('port') or gazete_server.DEFAULT_PORT)
        try:
            self._gazete_server.start(port)
        except OSError as error:
            return {'error': f'Sunucu {port} kapısında açılamadı: {error}'}
        self._gazete_set_prefs(port=port)
        self._log(f'Gazete: telefon sunucusu açıldı (kapı {port}).')
        name = self._gazete_current()
        if name:   # ilk karede beklenmesin
            threading.Thread(target=lambda: self._gazete_call(lambda: self._gazete_page_index(name)),
                             name='aktar-gazete-index', daemon=True).start()
        return self._gazete_server_state()

    def gazete_server_stop(self):
        if self._gazete_server is not None:
            self._gazete_server.stop()
            self._log('Gazete: telefon sunucusu kapatıldı.')
        self._gazete_index = None   # ~120 MB
        return self._gazete_server_state()

    def gazete_phone_remove(self, phone_id):
        gazete_server.Phones(gazete.root() / 'telefonlar.json').remove(str(phone_id))
        return self._gazete_server_state()

    def _stop_gazete_for_close(self):
        if self._gazete_running():
            self.gazete_cancel()
            self._gazete_job.join(5)
        if self._gazete_server is not None:
            self._gazete_server.stop()
