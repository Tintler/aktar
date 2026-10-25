"""Kitap gorselleri (F197) arka ucu (Bridge'e karisan sinif): `art_` onekli metotlar, olay 'art'.

Akis (kitapligin sag tik menusu -> BookArt.svelte): art_plan_create dil modeliyle plani cikarir (arka plan isi),
kullanici stili ve sahneleri gozden gecirir, art_generate ComfyUI ile gorselleri uretir. Ayni anda tek is; ikisi de
pencere kapaninca durur. Dil modeli ile gorsel modeli ayni GPU'yu paylasir: plan basinda ComfyUI'den modelleri
bosaltmasi istenir (comfy_client.free), plan sonunda dil modeli bosaltilir; ses motoru plan surerken durur.
Ayarlar ui.json 'art' altinda: comfy_url, size. Is akisi APP_DIR/kitap-gorselleri/is-akisi.json kopyasidir.
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

    def _art_running(self):
        job = getattr(self, '_art_job', None)
        return job is not None and job.is_alive()

    def _art_planning(self):
        """Dil modeli plan cikariyor mu (ses motoru bu sirada yuklenmez)."""
        return self._art_running() and getattr(self, '_art_stage', '') == 'plan'

    def _art_view(self, book, plan):
        """Arayuze giden plan: her sahnenin gorsel adresi (media_server)."""
        if not plan:
            return None
        view = dict(plan)
        scenes = []
        for scene in plan['scenes']:
            path = self._art_store().image_path(book, scene)
            scenes.append(dict(scene, url=self._media.file_url(path) if path and path.is_file() else ''))
        view['scenes'] = scenes
        view['summary'] = book_art.summary(plan)
        return view

    # ------------------------------------------------------------------ ayarlar
    def art_options(self):
        """Hazir tarzlar, siklik, boyutlar ve kayitli ayarlar (pencere ve Ayarlar icin)."""
        prefs = self._art_prefs()
        return {'presets': list(book_art.PRESETS), 'densities': list(book_art.DENSITY), 'sizes': list(book_art.SIZES),
                'url': self._art_url(), 'size': prefs.get('size') if prefs.get('size') in book_art.SIZES
                else book_art.DEFAULT_SIZE, 'workflow': self.art_workflow_info()}

    def art_workflow_info(self):
        try:
            return comfy_client.describe_workflow(self._art_workflow())
        except comfy_client.ComfyError as error:
            return {'ok': False, 'missing': [], 'message': str(error), 'none': True}

    def art_set_workflow(self, path):
        """Secilen API formatindaki is akisini denetler ve APP_DIR altina kopyalar."""
        try:
            text = Path(path).read_text(encoding='utf-8')
            info = comfy_client.describe_workflow(comfy_client.load_workflow(text))
        except (OSError, UnicodeDecodeError) as error:
            return _error(f'İş akışı okunamadı: {error}')
        except comfy_client.ComfyError as error:
            return _error(error)
        if not info['ok']:
            return _error(info['message'])
        target = self._art_workflow_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        self._log(f'Kitap görselleri: iş akışı kaydedildi ({Path(path).name}).')
        return info

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
            return {'plan': self._art_view(book, self._art_store().load(book))}
        except (OSError, ValueError) as error:
            return _error(error)

    def art_plan_create(self, book, sections, note='', preset='', density='medium', title='', resume=False):
        """Dil modeliyle sahne planini arka planda cikarir. `sections`: [{'sentences', 'breaks'}] okuyucunun
        bolmesiyle. `resume`: yarim kalan plan kaldigi yerden (not ve siklik onunki). Olay 'art' (stage 'plan')."""
        try:
            store = self._art_store()
            store.folder(book)
        except ValueError as error:
            return _error(error)
        sections = [{'sentences': [' '.join(str(s).split()) for s in (part or {}).get('sentences') or ()],
                     'breaks': [int(b) for b in (part or {}).get('breaks') or ()]} for part in sections or ()]
        total = sum(len(part['sentences']) for part in sections)
        if not total:
            return _error('Kitapta metin bulunamadı.')
        old = store.load(book)
        if resume and old and not old.get('complete'):
            plan = old
        else:
            size = self._art_prefs().get('size') or book_art.DEFAULT_SIZE
            plan = book_art.new_plan(note, preset, density, size, title)
        if not hasattr(self, '_art_lock'):
            self._art_lock = threading.Lock()
        with self._art_lock:
            if self._art_running():
                return _error('Kitap görselleri için bir iş zaten sürüyor.')
            emotion = getattr(self, '_emotion_job', None)
            if emotion is not None and emotion.is_alive():
                return _error('Duygu etiketleri oluşturulurken görsel planı çıkarılamaz (ikisi de dil modelini kullanır).')
            if not resume and old:
                store.clear(book)
            cancel = threading.Event()
            self._art_cancel_event, self._art_stage = cancel, 'plan'

            def progress(done, count):
                self._emit('art', {'book': book, 'title': title, 'stage': 'plan', 'done': done, 'total': count})

            def work():
                from app_core import Client, keep_loaded, load_config, unload_models
                client, loaded = None, []
                try:
                    engines = getattr(self, '_engines_cache', None)
                    if engines is not None and engines.state != 'idle' and not engines._exporting:
                        engines.stop_worker()   # ses motoru bellegi bosalsin
                        engines._set('idle', '')
                    comfy_client.free(self._art_url())   # ComfyUI ayni GPU'daki modelini birakir
                    client = Client(load_config(), log=self._log)
                    loaded = keep_loaded(client, [client.cfg.get('model')], self._log)
                    ask = lambda system, user: client.chat([{'role': 'system', 'content': system},
                                                            {'role': 'user', 'content': user}],
                                                           temperature=0.4, max_tokens=book_art.MAX_TOKENS)
                    result = book_art.plan_book(sections, ask, plan, cancel, progress, lambda p: store.save(book, p))
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
        """Gozden gecirmede degisen stil ve karakterler (gorseller kendiliginden yeniden uretilmez)."""
        values = values or {}

        def change(plan):
            if 'style' in values:
                style = ' '.join(str(values['style'] or '').split())
                if not style:
                    raise ValueError('Stil boş olamaz.')
                plan['style'] = style
            if 'characters' in values:
                plan['characters'] = book_art.clean_characters(values['characters'])

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
        from app_core import Client, keep_loaded, load_config, unload_models
        client, loaded = None, []
        try:
            store = self._art_store()
            plan = store.load(book)
            if not plan:
                return _error('Bu kitabın görsel planı yok.')
            scene = store.scene(plan, scene_id)
            comfy_client.free(self._art_url())
            client = Client(load_config(), log=self._log)
            loaded = keep_loaded(client, [client.cfg.get('model')], self._log)
            system, user = book_art.refine_prompt(scene['prompt'], instruction)
            raw = client.chat([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                              temperature=0.2, max_tokens=book_art.MAX_TOKENS)
            prompt = book_art.parse_refined(raw, scene['prompt'])
        except (OSError, ValueError, RuntimeError) as error:
            return _error(error)
        finally:
            if loaded:
                unload_models(client, loaded)
        return self.art_scene_update(book, scene_id, {'prompt': prompt})

    # ------------------------------------------------------------------ uretim
    def art_generate(self, book, scene_ids=None, title='', all_scenes=False):
        """Gorselleri ComfyUI ile arka planda uretir: `scene_ids` verilirse yalnizca onlar (varsa gorseli yenilenir),
        `all_scenes` butun sahneler (stil degisince), yoksa gorseli olmayanlar. Olay 'art' (stage 'generate')."""
        try:
            store = self._art_store()
            plan = store.load(book)
            if not plan:
                return _error('Bu kitabın görsel planı yok; önce planlayın.')
            workflow = self._art_workflow()
        except (OSError, ValueError, comfy_client.ComfyError) as error:
            return _error(error)
        ordered = sorted(plan['scenes'], key=lambda s: (s['section'], s['start']))
        if scene_ids:
            wanted = set(scene_ids)
            targets = [scene['id'] for scene in ordered if scene['id'] in wanted]
        elif all_scenes:
            targets = [scene['id'] for scene in ordered if not scene.get('skip')]
        else:
            targets = [scene['id'] for scene in book_art.pending(plan)]
        if not targets:
            return _error('Üretilecek görsel yok.')
        url = self._art_url()
        try:
            comfy_client.health(url)
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

            def work():
                done = 0
                try:
                    for scene_id in targets:
                        if cancel.is_set():
                            raise comfy_client.Cancelled('durduruldu')
                        current = store.load(book)
                        scene = store.scene(current, scene_id)
                        self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'done': done,
                                           'total': len(targets), 'current': scene['title']})
                        filled = comfy_client.fill(workflow, scene['prompt'], current['style'], book_art.SUFFIX,
                                                   scene['seed'], size, f'Aktar/{book[:12]}/{scene_id}')
                        data = comfy_client.generate(url, filled, cancel)
                        updated = store.write_image(book, scene_id, data)
                        done += 1
                        shown = next(s for s in self._art_view(book, updated)['scenes'] if s['id'] == scene_id)
                        self._emit('art', {'book': book, 'title': title, 'stage': 'generate', 'done': done,
                                           'total': len(targets), 'scene': shown})
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
        return {'started': True, 'total': len(targets)}

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
            plan = store.load(book)
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
