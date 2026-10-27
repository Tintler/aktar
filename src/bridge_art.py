"""Kitap gorselleri (F197) arka ucu (Bridge'e karisan sinif): `art_` onekli metotlar, olay 'art'.

Akis (kitapligin sag tik menusu -> BookArt.svelte): art_plan_create dil modeliyle plani cikarir (arka plan isi),
kullanici stili ve sahneleri gozden gecirir, art_generate ComfyUI ile gorselleri uretir. Ayni anda tek is; ikisi de
pencere kapaninca durur. Dil modeli ile gorsel modeli ayni GPU'yu paylasir: plan basinda ComfyUI'den modelleri
bosaltmasi istenir (comfy_client.free), plan sonunda dil modeli bosaltilir; ses motoru plan surerken durur.
Ayarlar ui.json 'art' altinda: comfy_url, size. Is akisi APP_DIR/kitap-gorselleri/is-akisi.json kopyasidir.
Karakter kimligi (F201, plan['identity'] acikken): ikinci is akisi kimlik-is-akisi.json; art_generate once eksik ya da
istenen portreleri ana is akisiyla uretir, sonra karakterli sahneyi portre(ler) yuklenerek kimlik is akisiyla.
LoRA'li tarz (F202, plan['lora']): uretim basinda dosya ComfyUI'nin LoRA listesinde aranir, iki is akisina eklenir.
F209: art_restyle tarzi degistirir (istemler kalir), plan['upscale'] aciksa her gorsel RTX ile buyutulur.
"""
from __future__ import annotations

import random
import threading
from pathlib import Path

import book_art
import comfy_client
from app_core import APP_DIR


def _error(error):
    return {'error': str(error)}


class ArtMixin:
    def _art_store(self):
        directory = Path(APP_DIR)
        store = getattr(self, '_art_cache', None)
        if store is None or store.directory != directory / book_art.STORE_DIR:
            self._art_cache = store = book_art.Store(directory)
        return store

    def _art_prefs(self):
        return self.ui_prefs().get('art', {}) or {}

    def _art_url(self):
        return comfy_client.normalize_url(self._art_prefs().get('comfy_url'))

    def _art_workflow_path(self):
        return Path(APP_DIR) / book_art.STORE_DIR / book_art.WORKFLOW_FILE

    def _art_workflow(self):
        path = self._art_workflow_path()
        if not path.is_file():
            raise comfy_client.ComfyError('Ayarlar → Kitap görselleri\'nde ComfyUI iş akışını (API formatında) seçin.')
        return comfy_client.load_workflow(path.read_text(encoding='utf-8'))

    def _art_identity_path(self):
        return Path(APP_DIR) / book_art.STORE_DIR / book_art.IDENTITY_FILE

    def _art_identity_workflow(self):
        path = self._art_identity_path()
        if not path.is_file():
            raise comfy_client.ComfyError('Karakter kimliği için Ayarlar → Kitap görselleri\'nde kimlik iş akışını '
                                          '(API formatında, "REFERENCE" düğümlü) seçin.')
        return comfy_client.load_workflow(path.read_text(encoding='utf-8'))

    def _art_running(self):
        job = getattr(self, '_art_job', None)
        return job is not None and job.is_alive()

    def _art_planning(self):
        """Dil modeli plan cikariyor mu (ses motoru bu sirada yuklenmez)."""
        return self._art_running() and getattr(self, '_art_stage', '') == 'plan'

    def _art_load(self, book):
        """Plan; eski (bolumleri bos bolumler atlanarak numaralanmis) plan kitabin metniyle bir kez onarilir."""
        store = self._art_store()
        plan = store.load(book)
        if plan and book_art.dedupe_plan(dict(plan)):   # tekrar eden karakter arayuzu cokertiyordu (F211)
            plan = store.update(book, book_art.dedupe_plan)
            self._log('Kitap görselleri: plandaki tekrar eden karakterler ayıklandı.')
        tried = self.__dict__.setdefault('_art_renumber_tried', set())
        if not plan or plan.get('numbered') or book in tried:
            return plan
        tried.add(book)
        import book_search
        try:
            _entry, epub = self._shelf()._book(book)
            texts = list(book_search.section_texts(epub))
        except Exception as error:   # kitap kitapliktan kalkmis ya da okunamiyor: plan oldugu gibi kalir
            self._log(f'UYARI: Görsel planının bölümleri onarılamadı: {error}')
            return plan
        fixed = []
        plan = store.update(book, lambda p: fixed.append(book_art.renumber(p, texts)))
        self._log('Kitap görselleri: eski planın bölüm numaraları düzeltildi.' if fixed[0]
                  else 'UYARI: Görsel planının bölümleri kitapla eşleşmedi; planı yeniden oluşturun.')
        return plan

    def _art_chapters(self, book):
        """Okuyucu bolum numarasi -> kitabin icindekilerdeki adi (F211; yalnizca kendi girdisi olan bolumler: kapak,
        ithaf gibi girdisiz bolume bir oncekinin adi verilmez)."""
        try:
            toc = self._shelf()._book(book)[1].toc
        except Exception:   # kitap kitapliktan kalkmis: kartlar okuyucu numarasini gosterir
            return {}
        chapters = {}
        for entry in toc:
            chapters.setdefault(entry['section'], entry['title'])
        return chapters

    def _art_view(self, book, plan):
        """Arayuze giden plan: her sahnenin gorsel adresi (media_server)."""
        if not plan:
            return None
        view = dict(plan)
        store = self._art_store()
        chapters = self._art_chapters(book)
        scenes = []
        for scene in plan['scenes']:
            path = store.image_path(book, scene)
            shown = dict(scene, url=self._media.file_url(path) if path and path.is_file() else '')
            if chapters.get(scene['section']):
                shown['chapter'] = chapters[scene['section']]
            if plan.get('identity'):
                shown['people'] = [c['name'] for c in book_art.cast_of(scene, plan['characters'])]
            scenes.append(shown)
        view['scenes'] = scenes
        characters = []
        for character in plan.get('characters') or ():
            path = store.portrait_path(book, character)
            characters.append(dict(character, portrait_url=self._media.file_url(path) if path and path.is_file() else ''))
        view['characters'] = characters
        view['summary'] = book_art.summary(plan)
        return view

    # ------------------------------------------------------------------ ayarlar
    def art_options(self):
        """Hazir tarzlar, siklik, boyutlar ve kayitli ayarlar (pencere ve Ayarlar icin)."""
        prefs = self._art_prefs()
        return {'presets': list(book_art.PRESETS), 'modifiers': list(book_art.MODIFIERS),
                'no_cast': list(book_art.NO_CAST), 'densities': list(book_art.DENSITY), 'sizes': list(book_art.SIZES),
                'upscales': list(book_art.UPSCALES),
                'url': self._art_url(), 'size': prefs.get('size') if prefs.get('size') in book_art.SIZES
                else book_art.DEFAULT_SIZE, 'workflow': self.art_workflow_info(),
                'identity_workflow': self.art_identity_workflow_info()}

    def art_workflow_info(self):
        try:
            return comfy_client.describe_workflow(self._art_workflow())
        except comfy_client.ComfyError as error:
            return {'ok': False, 'missing': [], 'message': str(error), 'none': True}

    def art_identity_workflow_info(self):
        try:
            return comfy_client.describe_identity_workflow(self._art_identity_workflow())
        except comfy_client.ComfyError as error:
            return {'ok': False, 'missing': [], 'message': str(error), 'none': True}

    def art_set_workflow(self, path, kind='main'):
        """Secilen API formatindaki is akisini denetler ve APP_DIR altina kopyalar. `kind` 'identity': karakter
        kimligi is akisi (REFERENCE dugumu gerekir)."""
        identity = kind == 'identity'
        try:
            text = Path(path).read_text(encoding='utf-8')
            workflow = comfy_client.load_workflow(text)
            info = (comfy_client.describe_identity_workflow if identity else comfy_client.describe_workflow)(workflow)
        except (OSError, UnicodeDecodeError) as error:
            return _error(f'İş akışı okunamadı: {error}')
        except comfy_client.ComfyError as error:
            return _error(error)
        if not info['ok']:
            return _error(info['message'])
        target = self._art_identity_path() if identity else self._art_workflow_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        self._log(f'Kitap görselleri: {"kimlik " if identity else ""}iş akışı kaydedildi ({Path(path).name}).')
        return info

    def art_clear_identity_workflow(self):
        self._art_identity_path().unlink(missing_ok=True)
        return self.art_identity_workflow_info()

    def _art_loras(self, url, lora):
        """Planin LoRA'si [(ComfyUI'deki adi, guc)]; dosya ComfyUI'de yoksa ComfyError."""
        if not lora or not lora.get('lora'):
            return []
        try:
            available = comfy_client.lora_names(url)
        except comfy_client.ComfyError as error:
            raise comfy_client.ComfyError(f'ComfyUI\'nin LoRA listesi alınamadı: {error}') from None
        found = comfy_client.resolve_lora(available, lora['lora'])
        if not found:
            raise comfy_client.ComfyError(f'"{lora.get("label") or lora["lora"]}" tarzının LoRA dosyası ComfyUI\'de yok: '
                                          f'{lora["lora"]} dosyasını ComfyUI\'nin models/loras klasörüne koyun ve '
                                          f'ComfyUI\'yi yenileyin.')
        return [(found, float(lora.get('strength') or 1.0))]

    def art_lora_check(self, preset):
        """Hazir tarzin LoRA dosyasi ComfyUI'de var mi: {'ok', 'message'} (LoRA'siz tarzda ok)."""
        lora = book_art.preset_lora(preset)
        if not lora:
            return {'ok': True, 'message': ''}
        try:
            name = self._art_loras(self._art_url(), lora)[0][0]
        except comfy_client.ComfyError as error:
            return {'ok': False, 'message': str(error)}
        return {'ok': True, 'message': f'LoRA hazır: {name}'}

    def art_upscale_check(self):
        """F209: RTX buyutme dugumu ComfyUI'de var mi: {'ok', 'message'}."""
        try:
            found = comfy_client.has_node(self._art_url(), comfy_client.UPSCALE_NODE)
        except comfy_client.ComfyError as error:
            return {'ok': False, 'message': str(error)}
        return {'ok': found, 'message': 'RTX Video Super Resolution hazır.' if found else comfy_client.UPSCALE_MISSING}

    def art_check(self, url=None):
        """ComfyUI'nin saglik denetimi ve is akisi (Ayarlar'daki "Bağlantıyı dene")."""
        try:
            result = comfy_client.health(url or self._art_url())
        except comfy_client.ComfyError as error:
            return _error(error)
        workflow = self.art_workflow_info()
        if not workflow['ok']:
            return _error(result['message'] + ' · ' + workflow['message'])
        return result

    # ------------------------------------------------------------------ plan
    def art_books(self):
        """Plani olan kitaplar: {kitap: ozet}."""
        try:
            store = self._art_store()
            return {book: book_art.summary(store.load(book)) for book in store.books()}
        except OSError:
            return {}

    def art_plan_get(self, book):
        try:
            return {'plan': self._art_view(book, self._art_load(book))}
        except (OSError, ValueError) as error:
            return _error(error)

    def art_plan_create(self, book, sections, note='', preset='', density='medium', title='', resume=False,
                        identity=False, modifiers=None, options=None, openers_only=False):
        """Dil modeliyle sahne planini arka planda cikarir. `sections`: [{'sentences', 'breaks'}] okuyucunun
        bolmesiyle. `resume`: yarim kalan plan kaldigi yerden (not ve siklik onunki). `identity`: karakter kimligi
        (sahnelere gorunen karakterler yazilir). `modifiers`: tarzdan bagimsiz secenekler (book_art.MODIFIERS).
        `options` (F209): openers, places, changes, upscale (book_art.new_plan). `openers_only`: tamamlanmis plana
        yalnizca eksik bolum acilis gorselleri eklenir (book_art.add_openers). Olay 'art' (stage 'plan')."""
        try:
            store = self._art_store()
            store.folder(book)
        except ValueError as error:
            return _error(error)
        sections = [{'number': int((part or {}).get('number', index)),
                     'sentences': [' '.join(str(s).split()) for s in (part or {}).get('sentences') or ()],
                     'breaks': [int(b) for b in (part or {}).get('breaks') or ()]}
                    for index, part in enumerate(sections or ())]
        total = sum(len(part['sentences']) for part in sections)
        if not total:
            return _error('Kitapta metin bulunamadı.')
        old = self._art_load(book)
        if openers_only and not (old and old.get('complete')):
            return _error('Önce kitabın görsel planını çıkarın.')
        if openers_only or (resume and old and not old.get('complete')):
            plan = old
        else:
            size = self._art_prefs().get('size') or book_art.DEFAULT_SIZE
            plan = book_art.new_plan(note, preset, density, size, title, identity, modifiers or (), options)
        if not hasattr(self, '_art_lock'):
            self._art_lock = threading.Lock()
        with self._art_lock:
            if self._art_running():
                return _error('Kitap görselleri için bir iş zaten sürüyor.')
            emotion = getattr(self, '_emotion_job', None)
            if emotion is not None and emotion.is_alive():
                return _error('Duygu etiketleri oluşturulurken görsel planı çıkarılamaz (ikisi de dil modelini kullanır).')
            if not resume and not openers_only and old:
                store.clear(book)
            cancel = threading.Event()
            self._art_cancel_event, self._art_stage = cancel, 'plan'

            def progress(done, count):
                self._emit('art', {'book': book, 'title': title, 'stage': 'plan', 'done': done, 'total': count})

            def work():
                from app_core import Client, keep_loaded, load_config, unload_models
                client, loaded = None, []
                try:
                    self._log(f'Kitap görselleri: plan başlıyor ({total} cümle, {title or book}).')
                    engines = getattr(self, '_engines_cache', None)
                    if engines is not None and engines.state != 'idle' and not engines._exporting:
                        self._log('Kitap görselleri: ses motoru durduruluyor…')
                        engines.stop_worker()   # ses motoru bellegi bosalsin
                        engines._set('idle', '')
                    self._log('Kitap görselleri: ComfyUI belleği boşaltılıyor…')
                    comfy_client.free(self._art_url())   # ComfyUI ayni GPU'daki modelini birakir
                    client = Client(load_config(), log=self._log)
                    loaded = keep_loaded(client, [client.cfg.get('model')], self._log)
                    self._log(f'Kitap görselleri: dil modeline ilk istek gönderiliyor ({client.cfg.get("model") or "seçili model"}).')
                    ask = lambda system, user: client.chat([{'role': 'system', 'content': system},
                                                            {'role': 'user', 'content': user}],
                                                           temperature=0.4, max_tokens=book_art.MAX_TOKENS)
                    run = book_art.add_openers if openers_only else book_art.plan_book
                    result = run(sections, ask, plan, cancel, progress, lambda p: store.save(book, p))
                    store.save(book, result)
                    self._log(f'Kitap görselleri: {len(result["scenes"])} sahne planlandı ({title or book}).')
                    self._emit('art', {'book': book, 'title': title, 'stage': 'plan', 'finished': True,
                                       'summary': book_art.summary(result)})
                except book_art.Cancelled:
                    self._emit('art', {'book': book, 'title': title, 'stage': 'plan', 'finished': True, 'cancelled': True})
                except Exception as error:
                    self._log(f'UYARI: Görsel planı çıkarılamadı: {error}')
                    self._emit('art', {'book': book, 'title': title, 'stage': 'plan', 'finished': True,
                                       'error': str(error)})
                finally:
                    if loaded:
                        unload_models(client, loaded)

            self._art_job = threading.Thread(target=work, name='aktar-art-plan', daemon=True)
            self._art_job.start()
        return {'started': True, 'total': total}

    def art_plan_save(self, book, values):
        """Gozden gecirmede degisen stil, karakterler (portreler ada gore korunur), karakter kimligi anahtari; F209
        mekanlar, mekan kimligi ve buyutme katsayisi (gorseller kendiliginden yeniden uretilmez)."""
        values = values or {}

        def change(plan):
            if 'style' in values:
                style = ' '.join(str(values['style'] or '').split())
                if not style:
                    raise ValueError('Stil boş olamaz.')
                plan['style'] = style
            if 'characters' in values:
                plan['characters'] = book_art.keep_portraits(book_art.clean_characters(values['characters']),
                                                             plan.get('characters'))
            if 'identity' in values:
                plan['identity'] = bool(values['identity'])
            if 'lora_strength' in values and plan.get('lora'):   # LoRA'nin gucu (0-2)
                plan['lora']['strength'] = round(min(2.0, max(0.0, float(values['lora_strength']))), 2)
            if 'places' in values:
                plan['places'] = book_art.clean_places(values['places'])
            if 'place_identity' in values:
                plan['place_identity'] = bool(values['place_identity'])
            if 'upscale' in values:
                plan['upscale'] = book_art.clean_upscale(values['upscale'])

        try:
            return {'plan': self._art_view(book, self._art_store().update(book, change))}
        except (OSError, ValueError) as error:
            return _error(error)

    def art_scene_update(self, book, scene_id, values):
        """Sahnenin istemi, basligi ya da atlanmasi; `reseed` yeni seed (Yeniden dene)."""
        values = values or {}

        def change(plan):
            scene = self._art_store().scene(plan, scene_id)
            if 'prompt' in values:
                prompt = ' '.join(str(values['prompt'] or '').split())
                if not prompt:
                    raise ValueError('İstem boş olamaz.')
                scene['prompt'] = prompt[:1200]
            if 'title' in values:
                scene['title'] = ' '.join(str(values['title'] or '').split())[:80] or scene['title']
            if 'skip' in values:
                scene['skip'] = bool(values['skip'])
            if 'cast' in values:   # karakter kimligi: sahnedeki karakterler elle (None: kendiliginden bul)
                if values['cast'] is None:
                    scene.pop('cast', None)
                else:
                    scene['cast'] = book_art.clean_cast(values['cast'])
            if 'place' in values:   # F209 mekan kimligi: sahnenin mekani ('' yok)
                place = ' '.join(str(values['place'] or '').split())[:60]
                if place:
                    scene['place'] = place
                else:
                    scene.pop('place', None)
            if values.get('reseed'):
                scene['seed'] = random.randrange(1, 2 ** 31)

        try:
            return {'plan': self._art_view(book, self._art_store().update(book, change))}
        except (OSError, ValueError) as error:
            return _error(error)

    def art_scene_refine(self, book, scene_id, instruction):
        """Sahne basina kucuk duzeltme: dil modeli istemi en az degisiklikle yeniden yazar (sahneyi bastan kurmaz).
        Bloklar (kisa istek); ComfyUI modeli once bosaltilir, dil modeli sonra. Donen: guncel plan."""
        instruction = ' '.join(str(instruction or '').split())
        if not instruction:
            return _error('Ne değişsin? Kısa bir not yazın: "daha karanlık", "kişiyi çıkar" gibi.')
        if self._art_running():
            return _error('Görseller üretilirken düzeltme yapılamaz; önce durdurun.')
        try:
            store = self._art_store()
            plan = store.load(book)
            if not plan:
                return _error('Bu kitabın görsel planı yok.')
            scene = store.scene(plan, scene_id)
            raw = self._art_ask(*book_art.refine_prompt(scene['prompt'], instruction, plan.get('modifiers')),
                                temperature=0.2)
            prompt = book_art.parse_refined(raw, scene['prompt'])
        except (OSError, ValueError, RuntimeError) as error:
            return _error(error)
        return self.art_scene_update(book, scene_id, {'prompt': prompt})

    def _art_ask(self, system, user, temperature=0.4):
        """Tek dil modeli istegi (bloklar): ComfyUI modeli once bosaltilir, dil modeli sonra."""
        from app_core import Client, keep_loaded, load_config, unload_models
        client, loaded = None, []
        try:
            comfy_client.free(self._art_url())
            client = Client(load_config(), log=self._log)
            loaded = keep_loaded(client, [client.cfg.get('model')], self._log)
            return client.chat([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                               temperature=temperature, max_tokens=book_art.MAX_TOKENS)
        finally:
            if loaded:
                unload_models(client, loaded)

    def art_restyle(self, book, preset='', note='', rewrite=True):
        """F209 toplu stil degisikligi: sahne istemleri ve plan aynen kalir; not, hazir tarz ve LoRA'si degisir, stil
        kilavuzu (`rewrite`) dil modeliyle yeni yone gore yeniden yazilir. Gorselleri arayuz sonra yeniden uretir
        (art_generate all_scenes). Bloklar. Donen: guncel plan."""
        note = ' '.join(str(note or '').split())
        if not note and not preset:
            return _error('Yeni tarzı seçin ya da kitap notuna yazın.')
        if self._art_running():
            return _error('Kitap görselleri için bir iş sürüyor; önce durdurun.')
        try:
            store = self._art_store()
            plan = store.load(book)
            if not plan:
                return _error('Bu kitabın görsel planı yok.')
            style = plan['style']
            if rewrite:
                raw = self._art_ask(*book_art.restyle_prompt(style, note, plan.get('modifiers')))
                style = book_art.parse_restyle(raw)

            def change(current):
                book_art.restyle(current, preset, note)
                current['style'] = style

            plan = store.update(book, change)
        except (OSError, ValueError, RuntimeError) as error:
            return _error(error)
        self._log(f'Kitap görselleri: tarz değişti ({preset or "not"}).')
        return {'plan': self._art_view(book, plan)}

    # ------------------------------------------------------------------ uretim
    def art_generate(self, book, scene_ids=None, title='', all_scenes=False, portraits=None, upscale_only=False):
        """Gorselleri ComfyUI ile arka planda uretir: `scene_ids` verilirse yalnizca onlar (varsa gorseli yenilenir),
        `all_scenes` butun sahneler (stil degisince), yoksa gorseli olmayanlar. `portraits`: yeniden uretilecek karakter
        portreleri (yeni seed; yalnizca portre istenirse sahne uretilmez). Karakter kimligi aciksa sahnelerdeki portresi
        olmayan karakterlerin portresi once uretilir. F209: planda buyutme aciksa her gorsel uretimden sonra RTX ile
        buyutulur; `upscale_only` var olan gorselleri yeniden uretmeden buyutur (`scene_ids` yoksa buyutulmemis
        olanlar). Olay 'art' (stage 'generate')."""
        try:
            store = self._art_store()
            plan = store.load(book)
            if not plan:
                return _error('Bu kitabın görsel planı yok; önce planlayın.')
            workflow = None if upscale_only else self._art_workflow()
        except (OSError, ValueError, comfy_client.ComfyError) as error:
            return _error(error)
        factor = plan.get('upscale') or 0
        ordered = sorted(plan['scenes'], key=lambda s: (s['section'], s['start']))
        if upscale_only:
            if not factor:
                return _error('Bu kitapta büyütme kapalı.')
            wanted = set(scene_ids or [s['id'] for s in book_art.not_upscaled(plan)])
            targets = [s['id'] for s in ordered if s['id'] in wanted and s.get('image') and not s.get('skip')]
            portraits = []
        elif scene_ids:
            wanted = set(scene_ids)
            targets = [scene['id'] for scene in ordered if scene['id'] in wanted]
        elif portraits is not None and not all_scenes:
            targets = []
        elif all_scenes:
            targets = [scene['id'] for scene in ordered if not scene.get('skip')]
        else:
            targets = [scene['id'] for scene in book_art.pending(plan)]
        identity = bool(plan.get('identity')) and not upscale_only
        known = {c['name'].lower(): c['name'] for c in plan['characters']}
        faces = [known[name.lower()] for name in portraits or () if name.lower() in known] if identity else []
        renew = set(faces)
        identity_workflow = None
        if identity:
            cast = [c for scene in ordered if scene['id'] in set(targets)
                    for c in book_art.cast_of(scene, plan['characters'])[:book_art.MAX_CAST]]
            for character in cast:
                if character['name'] not in faces and not (store.portrait_path(book, character) or Path()).is_file():
                    faces.append(character['name'])
            if cast:
                try:
                    identity_workflow = self._art_identity_workflow()
                except comfy_client.ComfyError as error:
                    return _error(error)
        if not targets and not faces:
            return _error('Üretilecek görsel yok.')
        url = self._art_url()
        try:
            comfy_client.health(url)
            if factor and targets and not comfy_client.has_node(url, comfy_client.UPSCALE_NODE):
                raise comfy_client.ComfyError(comfy_client.UPSCALE_MISSING)
            if workflow is not None:
                loras = self._art_loras(url, plan.get('lora'))   # tarzin LoRA'si iki is akisina da
                workflow = comfy_client.add_loras(workflow, loras)
                if identity_workflow is not None:
                    identity_workflow = comfy_client.add_loras(identity_workflow, loras)
        except comfy_client.ComfyError as error:
            return _error(error)
        if not hasattr(self, '_art_lock'):
            self._art_lock = threading.Lock()
        with self._art_lock:
            if self._art_running():
                return _error('Kitap görselleri için bir iş zaten sürüyor.')
            cancel = threading.Event()
            self._art_cancel_event, self._art_stage = cancel, 'generate'
            size = book_art.SIZES.get(plan.get('size'), book_art.SIZES[book_art.DEFAULT_SIZE])
            title = title or plan.get('title') or ''

            total = len(faces) + len(targets)
            uploaded = {}   # portre dosyasi -> ComfyUI'deki adi (is boyunca bir kez yuklenir)

            def upload(character):
                path = store.portrait_path(book, character)
                if path.name not in uploaded:
                    uploaded[path.name] = comfy_client.upload_image(url, path.read_bytes(),
                                                                    f'aktar-{book[:12]}-{path.name}')
                return uploaded[path.name]

            def enlarge(scene_id, data, before):
                """F209: gorseli planin buyutme katsayisina getirir (`before`: simdiki katsayisi, 0 ozgun boyut);
                buyutulmus gorselde katsayi farki kadar, kuculecekse Pillow ile."""
                scale = factor / (before or 1)
                if abs(scale - 1) < 0.01:
                    return data
                if scale < 1:
                    from io import BytesIO
                    from PIL import Image
                    with Image.open(BytesIO(data)) as image:
                        buffer = BytesIO()
                        image.resize((round(image.width * scale), round(image.height * scale)),
                                     Image.LANCZOS).save(buffer, 'PNG')
                    return buffer.getvalue()
                name = comfy_client.upload_image(url, data, f'aktar-{book[:12]}-{scene_id}-kaynak.png')
                return comfy_client.generate(url, comfy_client.upscale_workflow(
                    name, scale, f'Aktar/{book[:12]}/{scene_id}-buyuk'), cancel)

            def work():
                done = 0
                try:
                    for name in faces:
                        if cancel.is_set():
                            raise comfy_client.Cancelled('durduruldu')
                        current = store.load(book)
                        character = store.character(current, name)
                        self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'done': done,
                                           'total': total, 'current': f'Portre: {name}'})
                        seed = (random.randrange(1, 2 ** 31) if name in renew or not character.get('portrait_seed')
                                else character['portrait_seed'])
                        filled = comfy_client.fill(workflow, book_art.portrait_prompt(character),
                                                   book_art.image_style(current, book_art.medium(current['style'])),
                                                   book_art.image_suffix(current, book_art.PORTRAIT_SUFFIX, False), seed,
                                                   book_art.PORTRAIT_SIZE,
                                                   f'Aktar/{book[:12]}/portre-{book_art.portrait_slug(name)}')
                        updated = store.write_portrait(book, name, comfy_client.generate(url, filled, cancel), seed=seed)
                        done += 1
                        shown = next(c for c in self._art_view(book, updated)['characters'] if c['name'] == name)
                        self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'done': done,
                                           'total': total, 'character': shown})
                    for scene_id in targets:
                        if cancel.is_set():
                            raise comfy_client.Cancelled('durduruldu')
                        current = store.load(book)
                        scene = store.scene(current, scene_id)
                        self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'done': done,
                                           'total': total, 'current': scene['title']})
                        if upscale_only:
                            data = store.image_path(book, scene).read_bytes()
                            updated = store.write_image(book, scene_id, enlarge(scene_id, data, scene.get('upscaled')),
                                                        upscaled=factor)
                            done += 1
                            shown = next(s for s in self._art_view(book, updated)['scenes'] if s['id'] == scene_id)
                            self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'done': done,
                                               'total': total, 'scene': shown})
                            continue
                        prefix = f'Aktar/{book[:12]}/{scene_id}'
                        people = []
                        if identity_workflow is not None and current.get('identity'):
                            people = [c for c in book_art.scene_people(scene, current['characters'])
                                      if (store.portrait_path(book, c) or Path()).is_file()]
                            people = people[:len(comfy_client.references(identity_workflow))]
                        text = dict(scene, prompt=book_art.scene_text(current, scene))   # F209 mekanin tarifiyle
                        if people:
                            filled = comfy_client.fill(identity_workflow, book_art.image_style(
                                                           current, book_art.identity_prompt(text, people, current['style'])),
                                                       '', book_art.image_suffix(current), scene['seed'], size, prefix,
                                                       images=[upload(c) for c in people])
                        else:
                            filled = comfy_client.fill(workflow, text['prompt'], book_art.image_style(current, current['style']),
                                                       book_art.image_suffix(current), scene['seed'], size, prefix)
                        data = comfy_client.generate(url, filled, cancel)
                        if factor:
                            self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'done': done,
                                               'total': total, 'current': f'{scene["title"]} · büyütülüyor'})
                            data = enlarge(scene_id, data, 0)
                        updated = store.write_image(book, scene_id, data, upscaled=factor)
                        done += 1
                        shown = next(s for s in self._art_view(book, updated)['scenes'] if s['id'] == scene_id)
                        self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'done': done,
                                           'total': total, 'scene': shown})
                    self._log(f'Kitap görselleri: {done} görsel üretildi ({title or book}).')
                    self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'finished': True,
                                       'done': done, 'summary': book_art.summary(store.load(book))})
                except comfy_client.Cancelled:
                    self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'finished': True,
                                       'cancelled': True, 'done': done})
                except Exception as error:
                    self._log(f'UYARI: Görsel üretilemedi: {error}')
                    self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'finished': True,
                                       'error': str(error), 'done': done})

            self._art_job = threading.Thread(target=work, name='aktar-art-generate', daemon=True)
            self._art_job.start()
        return {'started': True, 'total': total}

    def art_portrait_set(self, book, name, path):
        """Kullanicinin kendi portre gorseli (PNG'ye cevrilip kaydedilir)."""
        if self._art_running():
            return _error('Kitap görselleri için bir iş sürüyor; önce durdurun.')
        try:
            from io import BytesIO
            from PIL import Image
            with Image.open(path) as image:
                buffer = BytesIO()
                image.convert('RGB').save(buffer, 'PNG')
            plan = self._art_store().write_portrait(book, name, buffer.getvalue(), own=True)
        except (OSError, ValueError) as error:
            return _error(f'Görsel okunamadı: {error}' if isinstance(error, OSError) else error)
        return {'plan': self._art_view(book, plan)}

    def art_portrait_clear(self, book, name):
        if self._art_running():
            return _error('Kitap görselleri için bir iş sürüyor; önce durdurun.')
        try:
            return {'plan': self._art_view(book, self._art_store().clear_portrait(book, name))}
        except (OSError, ValueError) as error:
            return _error(error)

    def art_cancel(self):
        cancel = getattr(self, '_art_cancel_event', None)
        if cancel is not None:
            cancel.set()
        return True

    def art_clear(self, book):
        """Kitabin plani ve gorselleri silinir."""
        if self._art_running():
            return _error('Kitap görselleri için bir iş sürüyor; önce durdurun.')
        try:
            self._art_store().clear(book)
        except (OSError, ValueError) as error:
            return _error(error)
        return True

    # ------------------------------------------------------------------ okuyucu
    def art_section(self, book, section):
        """Tam ekran okuyucunun Gorselli arka plani: bolumun sahneleri [{start, anchor, url}] ve bolum basindan ilk
        sahneye kadar gosterilecek onceki gorsel (carry)."""
        try:
            store = self._art_store()
            plan = self._art_load(book)
        except (OSError, ValueError):
            return {'scenes': [], 'carry': ''}
        if not plan:
            return {'scenes': [], 'carry': ''}
        here, carry = book_art.section_images(plan, int(section))

        def url(scene):
            path = store.image_path(book, scene)
            return self._media.file_url(path) if path and path.is_file() else ''

        return {'scenes': [{'start': s['start'], 'anchor': s['anchor'], 'url': url(s)} for s in here if url(s)],
                'carry': url(carry) if carry else ''}

    def _stop_art_for_close(self):
        """Pencere kapaninca: plan ya da uretim durur (ComfyUI'deki is de kesilir)."""
        self.art_cancel()
        job = getattr(self, '_art_job', None)
        if job is not None and job.is_alive():
            job.join(5)
