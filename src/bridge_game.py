"""Oyun Cevirisi sayfasi (F194): oyunun ekranindaki yaziyi okuyup Turkce cevirisini oyunun ustunde gosterir.

Akis (calisirken, game_ onekli metotlar; olay 'game'):
  1. Is parcacigi secili oyunun bolgelerini `interval_ms` araliginda yakalar (game_screen.grab, yalnizca bolge).
  2. Goruntu degismediyse okunmaz; degistiyse Windows OCR ile okunur (~10 ms, ekran kartina yuk yok).
  3. game_core.TextTracker daktilo gibi gelen yazinin yerlesmesini bekler; ayni yazi bir kez cevrilir.
     Onbellekteki cumle yazi daha gelirken bile hemen gosterilir; yeni cumle LM Studio'ya akisli istekle gider.
  4. Ceviri game_overlay.OverlayHost katmaninda (tiklama gecirgen, odak almaz, yakalamaya girmez) gosterilir.
Kisayollar (RegisterHotKey) sayfa ilk acildiginda ya da daha once kullanildiysa acilista kaydedilir; pencere
kapaninca katman, kisayollar ve is parcacigi durur (arka planda hicbir sey kalmaz).
"""
from __future__ import annotations

import base64
import io
import threading
import time
from collections import deque

import game_core
import game_screen
import languages
from app_core import WINDOWS, Client, keep_loaded, load_config, unload_models

RECENT = 30          # sayfada gosterilen son ceviriler
STREAM_REDRAW = 0.08  # akan ceviride katman en sik bu aralikla yeniden cizilir
ERROR_REPEAT = 15.0   # ayni hata Konsol'a en sik bu aralikla yazilir
PICK_TIMEOUT = 180    # bolge secimi bu kadar saniye beklenir
BLOCK_OCR_GAP = 0.35  # tarama kipinde goruntu degisse de OCR en sik bu aralikla
BLOCK_MISSES = 2      # tarama kipinde yazi bu kadar okumada gorulmezse cevirisi gizlenir
RETRY_GAP = 5.0       # toplu ceviri istegi basarisizsa yeniden denemeden once beklenir
SKIP_GAP = 30.0       # modelin atladigi yazi bu kadar saniye yeniden istenmez
QUICK_CHECKS = 8      # OCR'siz turlarda altindaki yazisi denetlenen en fazla ceviri kutusu


class _Pass:
    """Bir calisma boyunca bolgelerin durumu (parmak izi, yazi takibi, okuyucu)."""

    def __init__(self):
        self.fps = {}
        self.trackers = {}
        self.speakers = {}
        self.showing = {}       # bolge -> ekrandaki cevirinin kaynak metni (compact)
        self.vision_dirty = {}
        self.blocks = {}        # tarama bolgesi -> _Blocks
        self.reader = None
        self.reader_key = None


class _Blocks:
    """Tarama kipindeki bir bolgenin durumu: son okunan yazilar ve ceviriyi bekleyenler."""

    def __init__(self):
        self.items = None       # son OCR'deki yazilar (ekran koordinatlari)
        self.seen = {}          # compact metin -> (ilk gorulme ani, kac bakista goruldu)
        self.busy = set()       # ceviri istegindeki yazilar
        self.skip = {}          # modelin atladigi yazilar -> yeniden istenebilecegi an
        self.next_ocr = 0.0
        self.retry_after = 0.0


class GameMixin:
    def _init_game(self):
        self._game_lock = threading.RLock()
        self._game_host = None
        self._game_thread = None
        self._game_stop = threading.Event()
        self._game_wake = threading.Event()
        self._game_force = False
        self._game_running = False
        self._game_visible = True
        self._game_recent = deque(maxlen=RECENT)
        self._game_history = deque(maxlen=10)
        self._game_cache = None          # (oyun kimligi, TranslationCache)
        self._game_generation = {}       # bolge -> son istek numarasi (yeni yazi eskisini iptal eder)
        self._game_displayed = {}        # bolge -> ekrandaki ceviri metni (kendi yazimizi okumamak icin)
        self._game_last = {}             # bolge -> {'text', 'time', 'fresh'}: devam eden yazi icin
        self._game_errors = {}
        self._game_error = ''
        self._game_hotkey_errors = {}
        self._game_hotkeys_paused = False
        self._game_status_timer = None
        self._game_info = {}             # son okuma: motor adi ve sure
        self._game_models = []           # ceviri icin LM Studio'ya yuklenen modeller (durunca bosaltilir)
        self._game_block_shown = {}      # tarama bolgesi -> {kaynak: {'key', 'translation', 'box', 'miss'}}
        self._game_block_free = {}       # tarama bolgesi -> bos katman anahtarlari (pencereler yeniden kullanilir)

    # ------------------------------------------------------------------ durum
    def _game_settings(self):
        return game_core.load_settings()

    def _game_current(self, settings=None):
        settings = settings or self._game_settings()
        return game_core.load_game(settings.get('game'))

    def _game_status(self):
        return {'running': self._game_running, 'overlay': self._game_visible, 'error': self._game_error,
                'recent': list(self._game_recent), 'info': dict(self._game_info),
                'capture_safe': self._game_host.capture_safe if self._game_host else True}

    def _game_push(self):
        self._emit('game', self._game_status())

    def _game_report(self, message):
        """Hata: sayfada gorunur, Konsol'a ayni ileti en sik ERROR_REPEAT saniyede bir yazilir."""
        self._game_error = str(message)
        now = time.monotonic()
        if now - self._game_errors.get(self._game_error, -ERROR_REPEAT) >= ERROR_REPEAT:
            self._game_errors[self._game_error] = now
            self._log(f'Ekran çevirisi: {message}')
        self._game_push()

    def game_snapshot(self):
        """Sayfa acilinca: ayarlar, oyunlar, secili oyun, durum ve okuyucu dilleri. Katman/kisayollar hazirlanir."""
        settings = self._game_settings()
        game = self._game_current(settings)
        if WINDOWS:
            self._game_boot(settings)
        cache = self._game_cache_for(game) if game else None
        return {'supported': WINDOWS, 'settings': settings, 'games': game_core.list_games(), 'game': game,
                'status': self._game_status(), 'cache': len(cache) if cache else 0,
                'ocr_languages': game_screen.windows_languages(),
                'languages': [item for item in languages.choices() if item['code'] != 'tr'],
                'hotkey_errors': dict(self._game_hotkey_errors)}

    def _game_boot(self, settings=None):
        """Katman is parcacigi ve kisayollar (bir kez). Hata olursa sayfada gorunur, uygulama etkilenmez."""
        if not WINDOWS or self._game_hotkeys_paused:
            return
        with self._game_lock:
            if self._game_host is None or not self._game_host.alive():
                try:
                    import game_overlay
                    self._game_host = game_overlay.OverlayHost(on_hotkey=self._game_hotkey, log=self._log).start()
                except Exception as error:  # katman acilamadi: ceviri sayfasi yine acilir
                    self._game_host = None
                    self._game_hotkey_errors = {'toggle': f'Katman başlatılamadı: {error}'}
                    return
                self._game_hotkey_errors = self._game_host.set_hotkeys((settings or self._game_settings())['hotkeys'])

    def _game_startup(self):
        """Uygulama acilisinda: ozellik daha once kullanildiysa kisayollar hemen calissin."""
        if WINDOWS and (game_core.folder() / 'ayarlar.json').exists():
            threading.Thread(target=self._game_boot, name='aktar-game-boot', daemon=True).start()

    # ------------------------------------------------------------------ ayarlar ve oyunlar
    def game_save_settings(self, values):
        try:
            before = self._game_settings()
            settings = game_core.save_settings(values)
        except OSError as error:
            return {'error': 'Ayarlar kaydedilemedi: ' + str(error)}
        if settings['hotkeys'] != before['hotkeys'] and self._game_host and not self._game_hotkeys_paused:
            self._game_hotkey_errors = self._game_host.set_hotkeys(settings['hotkeys'])
        if settings['game'] != before['game']:
            self._game_reset_display()
        return self.game_snapshot()

    def game_create(self, name):
        try:
            game = game_core.create_game(name)
        except (ValueError, OSError) as error:
            return {'error': str(error)}
        return self.game_save_settings({'game': game['id']})

    def game_select(self, game_id):
        if game_core.load_game(game_id) is None:
            return {'error': 'Oyun bulunamadı.'}
        return self.game_save_settings({'game': game_id})

    def game_delete(self, game_id):
        settings = self._game_settings()
        game_core.delete_game(game_id)
        if settings['game'] == game_id:
            if self._game_running:
                self.game_stop()
            games = game_core.list_games()
            return self.game_save_settings({'game': games[0]['id'] if games else ''})
        return self.game_snapshot()

    def game_update(self, values):
        """Secili oyunun adi, dili, bolgeleri ya da terimleri (gelen alanlar degisir)."""
        game = self._game_current()
        if game is None:
            return {'error': 'Önce bir oyun ekleyin.'}
        values = dict(values or {})
        for key in ('name', 'language', 'regions', 'terms'):
            if key in values:
                game[key] = values[key]
        try:
            game = game_core.save_game(game)
        except (ValueError, OSError) as error:
            return {'error': str(error)}
        if 'regions' in values:
            self._game_reset_display()
        return {'game': game}

    def game_clear_cache(self):
        game = self._game_current()
        cache = self._game_cache_for(game) if game else None
        if cache is not None:
            cache.clear()
            self._log(f'Ekran çevirisi: {game["name"]} önbelleği temizlendi.')
        return {'cache': 0}

    def _game_cache_for(self, game):
        with self._game_lock:
            if self._game_cache is None or self._game_cache[0] != game['id']:
                self._game_cache = (game['id'], game_core.TranslationCache(game_core.cache_path(game['id'])))
            return self._game_cache[1]

    # ------------------------------------------------------------------ bolge secimi ve deneme
    def _game_window(self, minimize):
        window = getattr(self._dialogs, 'window', None)
        if window is None:
            return
        try:
            if minimize:
                if self._frame is not None:
                    self._frame.minimize()
                else:
                    window.minimize()
            else:
                window.restore()
        except Exception:
            pass  # pencere yonetilemezse secim yine calisir

    def game_pick_region(self, hint=''):
        """Ekranda dikdortgen sectirir (Aktar penceresi bu surede kuculur). {'rect', 'preview'} | {'cancelled'}."""
        if not WINDOWS:
            return {'error': 'Ekranda bölge seçimi yalnızca Windows\'ta var.'}
        self._game_boot()
        if self._game_host is None:
            return {'error': self._game_hotkey_errors.get('toggle') or 'Katman başlatılamadı.'}
        done, box = threading.Event(), []

        def chosen(rect):
            box.append(rect)
            done.set()
        self._game_window(True)
        time.sleep(0.45)           # pencere kuculme animasyonu bitsin: donmus karede Aktar gorunmesin
        # Secim, o anki ekranin donmus karesi uzerinde yapilir; onizleme de ondan kesilir. (Secimden sonra
        # yakalamak Aktar penceresi geri acilirken onun goruntusunu aliyordu.)
        try:
            bounds = game_screen.virtual_screen()
            frozen = game_screen.grab(bounds)
        except OSError:
            bounds, frozen = None, None
        self._game_host.select(chosen, hint, frozen)
        done.wait(PICK_TIMEOUT)
        self._game_window(False)
        rect = box[0] if box else None
        if not rect:
            return {'cancelled': True}
        try:
            if frozen is not None:
                left, top = rect[0] - bounds[0], rect[1] - bounds[1]
                image = frozen.crop((left, top, left + rect[2], top + rect[3]))
            else:
                image = game_screen.grab(rect)
            preview = self._game_preview(image)
        except OSError:
            preview = ''
        return {'rect': rect, 'preview': preview}

    def game_screen_region(self):
        """'Tum ekrani tara' bolgesi icin birincil ekranin dikdortgeni (fiziksel piksel)."""
        if not WINDOWS:
            return {'error': 'Ekran çevirisi yalnızca Windows\'ta çalışır.'}
        width, height = game_screen.primary_size()
        return {'rect': [0, 0, width, height]}

    @staticmethod
    def _game_preview(image):
        from PIL import Image
        image = image.copy()
        image.thumbnail((520, 220), Image.LANCZOS)
        buffer = io.BytesIO()
        image.convert('RGB').save(buffer, 'JPEG', quality=72)
        return 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode()

    def game_test_region(self, region):
        """Bolgeyi simdi okur (cevirmez): {'lines', 'speaker', 'text', 'ms', 'engine', 'preview'}."""
        game = self._game_current()
        if game is None:
            return {'error': 'Önce bir oyun ekleyin.'}
        try:
            region = game_core.clean_region(region)
            game_screen.dpi_aware()
            image = game_screen.grab(region['rect'])
            state = _Pass()
            started = time.perf_counter()
            reader = self._game_reader(state, self._game_settings(), game)
            if region['placement'] == 'blocks':
                items = game_core.text_blocks(reader.boxes(image), game['language'], region['scan'] == 'prose')
                return {'lines': [item['text'] for item in items], 'speaker': '', 'blocks': len(items),
                        'text': '\n'.join(item['text'] for item in items),
                        'ms': round((time.perf_counter() - started) * 1000), 'engine': reader.label,
                        'preview': self._game_preview(image)}
            lines = reader(image)
        except (ValueError, OSError, RuntimeError) as error:
            return {'error': str(error)}
        speaker, text = game_core.split_speaker(lines, region['speaker'], game['terms'], game['language'])
        return {'lines': lines, 'speaker': speaker, 'text': text, 'ms': round((time.perf_counter() - started) * 1000),
                'engine': state.reader.label, 'preview': self._game_preview(image)}

    # ------------------------------------------------------------------ calistirma
    def game_start(self):
        settings = self._game_settings()
        game = self._game_current(settings)
        if not WINDOWS:
            return {'error': 'Ekran çevirisi yalnızca Windows\'ta çalışır.'}
        if game is None:
            return {'error': 'Önce bir oyun ekleyin.'}
        if not any(region['enabled'] and region['role'] == 'text' for region in game['regions']):
            return {'error': 'Önce okunacak bir bölge ekleyin (Bölgeler sekmesi).'}
        self._game_boot(settings)
        with self._game_lock:
            if self._game_running:
                return self._game_status()
            self._game_running = True
            self._game_error = ''
            self._game_stop.clear()
            self._game_thread = threading.Thread(target=self._game_loop, name='aktar-game-translate', daemon=True)
            self._game_thread.start()
        threading.Thread(target=self._game_keep_model, args=(settings,), name='aktar-game-model', daemon=True).start()
        self._log(f'Ekran çevirisi başladı: {game["name"]}')
        self._game_toast('Çeviri açık')
        self._game_push()
        return self._game_status()

    def game_stop(self):
        with self._game_lock:
            was = self._game_running
            self._game_running = False
            self._game_stop.set()
            self._game_wake.set()
            thread, self._game_thread = self._game_thread, None
        if thread and thread is not threading.current_thread():
            thread.join(2)
        for key in list(self._game_generation):
            self._game_generation[key] += 1      # suren istekler sonucunu gostermesin
        self._game_reset_display()
        if was:
            self._log('Ekran çevirisi durdu.')
            self._game_toast('Çeviri kapalı')
            threading.Thread(target=self._game_release_models, name='aktar-game-unload', daemon=True).start()
        self._game_push()
        return self._game_status()

    def game_toggle(self):
        return self.game_stop() if self._game_running else self.game_start()

    def game_overlay(self, visible=None):
        """Katmani gizler/gosterir (None: tersine cevirir). Ceviri surmeye devam eder."""
        self._game_visible = (not self._game_visible) if visible is None else bool(visible)
        if self._game_host:
            self._game_host.set_visible(self._game_visible)
        self._game_toast('Katman görünür' if self._game_visible else 'Katman gizli', force=True)
        self._game_push()
        return self._game_status()

    def game_translate_now(self):
        """Bolgeleri hemen okuyup cevirir (yazinin yerlesmesi beklenmez). Calismiyorsa tek seferlik."""
        if not WINDOWS:
            return {'error': 'Ekran çevirisi yalnızca Windows\'ta çalışır.'}
        if self._game_current() is None:
            return {'error': 'Önce bir oyun ekleyin.'}
        self._game_boot()
        if self._game_running:
            self._game_force = True
            self._game_wake.set()
        else:
            threading.Thread(target=self._game_once, name='aktar-game-once', daemon=True).start()
        return self._game_status()

    def game_hotkeys_pause(self, paused):
        """Kisayol kaydedilirken genel kisayollar birakilir (yoksa basilan tus sayfaya ulasmaz)."""
        self._game_hotkeys_paused = bool(paused)
        if self._game_host:
            self._game_hotkey_errors = self._game_host.set_hotkeys(
                {} if paused else self._game_settings()['hotkeys'])
        return {'hotkey_errors': dict(self._game_hotkey_errors)}

    def _game_hotkey(self, action):
        """Katman is parcaciginda: is baska is parcacigina birakilir (model istegi bekletmesin)."""
        target = {'toggle': self.game_toggle, 'overlay': self.game_overlay, 'now': self.game_translate_now}[action]
        threading.Thread(target=self._game_safe, args=(target,), name='aktar-game-hotkey', daemon=True).start()

    def _game_safe(self, fn):
        result = fn()
        if isinstance(result, dict) and result.get('error'):
            self._game_toast(result['error'], force=True)
            self._game_report(result['error'])

    def _game_keep_model(self, settings):
        """Model sunucusu LM Studio ise ceviri modeli acikca yuklenir (ilk cumlede yukleme beklenmesin)."""
        try:
            cfg = self._game_cfg(settings)
            loaded = keep_loaded(Client(cfg, self._log), [cfg['model']], self._log)
        except (RuntimeError, ValueError, OSError) as error:
            self._game_report(f'Model hazırlanamadı: {error}')
            return
        with self._lock:
            self._kept_models = list(dict.fromkeys(getattr(self, '_kept_models', []) + loaded))
            self._game_models = list(dict.fromkeys(self._game_models + loaded))

    def _game_release_models(self):
        """Ceviri durunca: yalnizca ceviri icin yuklenen model bosaltilir; ekran kartinin bellegi oyuna kalir."""
        with self._lock:
            models, self._game_models = self._game_models, []
        if not models:
            return
        try:
            unload_models(Client(dict(load_config(), timeout_seconds=15), self._log), models)
        except (RuntimeError, ValueError, OSError):
            return
        with self._lock:
            self._kept_models = [name for name in getattr(self, '_kept_models', []) if name not in models]
        self._log('Ekran çevirisi: çeviri modeli bellekten boşaltıldı.')

    def _stop_game_for_close(self):
        self._game_running = False
        self._game_stop.set()
        self._game_wake.set()
        for key in list(self._game_generation):
            self._game_generation[key] += 1
        host, self._game_host = self._game_host, None
        if host is not None:
            host.stop()

    # ------------------------------------------------------------------ katman
    def _game_reset_display(self):
        self._game_displayed.clear()
        self._game_last.clear()
        with self._game_lock:
            for key, shown in self._game_block_shown.items():
                self._game_generation[key] = self._game_generation.get(key, 0) + 1   # suren tarama istegi
                self._game_block_free.setdefault(key, []).extend(item['key'] for item in shown.values())
            self._game_block_shown.clear()
        if self._game_host:
            self._game_host.hide_all()

    def _game_style(self, settings):
        return {key: settings[key] for key in ('font_size', 'opacity', 'text_color', 'background', 'show_speaker')}

    def _game_show(self, region, text, speaker, settings):
        import game_overlay
        self._game_displayed[region['id']] = text
        if not self._game_host:
            return
        screen = game_screen.virtual_screen()
        placement, target = region['placement'], region.get('target')
        width = game_overlay.box_width(region['rect'], placement, target)
        fit = region['rect'][3] if placement == 'cover' else None
        image = game_overlay.render(text, width, self._game_style(settings), speaker=speaker, fit_height=fit)
        x, y = game_overlay.place(region['rect'], placement, image.size, screen, target)
        self._game_host.show(region['id'], image, x, y)

    def _game_hide(self, key):
        self._game_displayed.pop(key, None)
        if self._game_host:
            self._game_host.hide(key)

    def _game_toast(self, message, force=False):
        """Oyunun ustunde kisa durum yazisi (Aktar gorunmezken kisayolun ise yaradigi anlasilsin)."""
        if not self._game_host or not (force or self._game_visible):
            return
        import game_overlay
        settings = self._game_settings()
        style = dict(self._game_style(settings), font_size=max(14, int(settings['font_size'] * 0.8)), opacity=0.9)
        image = game_overlay.render(message, 360, style)
        left = (game_screen.primary_size()[0] - image.width) // 2
        self._game_host.call(lambda: self._game_host and self._game_host._show('_status', image, left, 40))
        if self._game_status_timer:
            self._game_status_timer.cancel()
        self._game_status_timer = threading.Timer(1.6, lambda: self._game_host and self._game_host.hide('_status'))
        self._game_status_timer.daemon = True
        self._game_status_timer.start()

    # ------------------------------------------------------------------ okuma dongusu
    def _game_loop(self):
        game_screen.dpi_aware()
        state = _Pass()
        try:
            while not self._game_stop.is_set():
                settings = self._game_settings()
                self._game_wake.wait(settings['interval_ms'] / 1000)
                self._game_wake.clear()
                if self._game_stop.is_set():
                    break
                force, self._game_force = self._game_force, False
                if not self._game_pass(state, settings, force):
                    break
        finally:
            if state.reader is not None:
                state.reader.close()

    def _game_once(self):
        game_screen.dpi_aware()
        state = _Pass()
        try:
            self._game_pass(state, self._game_settings(), True)
        finally:
            if state.reader is not None:
                state.reader.close()

    def _game_reader(self, state, settings, game):
        key = (settings['ocr_engine'], game['language'])
        if state.reader is None or state.reader_key != key:
            if state.reader is not None:
                state.reader.close()
            state.reader = game_screen.reader(settings['ocr_engine'], game['language'], load_config(), self._log)
            state.reader_key = key
        return state.reader

    def _game_pass(self, state, settings, force):
        """Bolgeleri bir kez yakalar ve gerekirse cevirir. Donen False: calisma durmali (kalici hata)."""
        game = self._game_current(settings)
        if game is None:
            return False
        regions = [region for region in game['regions'] if region['enabled']]
        if force and not any(region['role'] == 'text' for region in regions):
            self._game_screen_vision(settings, game)
            return True
        try:
            if any(region['mode'] == 'ocr' for region in regions):
                self._game_reader(state, settings, game)
        except (ValueError, OSError) as error:
            self._game_report(error)
            if self._game_running:
                threading.Thread(target=self.game_stop, daemon=True).start()
            return False
        now = time.monotonic()
        for region in regions:
            if region['role'] != 'text' or not (region['auto'] or force):
                continue
            try:
                self._game_region(state, settings, game, region, regions, force, now)
            except Exception as error:  # bir bolgenin hatasi digerlerini durdurmasin
                self._game_report(f'{region["name"]}: {error}')
        return True

    def _game_grab(self, rect):
        host = self._game_host
        if host is None or host.capture_safe:
            return game_screen.grab(rect)
        # Katman yakalamadan dislanamiyorsa: bolgenin ustundeki kutular yakalama aninda gizlenir.
        x, y, w, h = rect
        covering = [box for box in host.shown_rects()
                    if box[0] < x + w and x < box[0] + box[2] and box[1] < y + h and y < box[1] + box[3]]
        if not covering:
            return game_screen.grab(rect)
        host.call(lambda: [game_overlay_hide(host, key) for key in list(host._shown)], wait=True)
        time.sleep(0.03)
        try:
            return game_screen.grab(rect)
        finally:
            host.set_visible(self._game_visible)

    def _game_region(self, state, settings, game, region, regions, force, now):
        key = region['id']
        if region['placement'] == 'blocks':
            self._game_blocks(state, settings, game, region, force, now)
            return
        image = self._game_grab(region['rect'])
        fp = game_screen.fingerprint(image)
        same = not game_screen.changed(state.fps.get(key), fp)
        state.fps[key] = fp
        if region['mode'] == 'vision':
            # Gorsel model pahali: goruntu degistikten sonra bir aralik boyunca yerlesince bir kez gider.
            if force or (same and state.vision_dirty.get(key)):
                state.vision_dirty[key] = False
                self._game_vision(region, image, settings, game)
            elif not same:
                state.vision_dirty[key] = True
            return
        tracker = state.trackers.setdefault(key, game_core.TextTracker())
        tracker.settle = settings['settle_ms'] / 1000
        if same and not force:
            result = tracker.unchanged(now)
        else:
            started = time.perf_counter()
            lines = state.reader(image)
            self._game_info = {'engine': state.reader.label, 'ocr_ms': round((time.perf_counter() - started) * 1000)}
            speaker, text = game_core.split_speaker(lines, region['speaker'], game['terms'], game['language'])
            shown = self._game_displayed.get(key, '')
            if shown and game_core.similar(text, shown):
                return               # katmanin kendi yazisi okundu (yakalamadan dislanamadiysa)
            state.speakers[key] = speaker
            if force:
                result = tracker.force(text)
            else:
                result = tracker.observe(text, now)
                if result is None and text:
                    self._game_instant(state, region, text, speaker, settings, game)
        if result == 'gone':
            state.showing.pop(key, None)
            if settings['hide_when_gone']:
                self._game_hide(key)
            return
        if result:
            speaker = self._game_speaker(state, regions, game) or state.speakers.get(key, '')
            self._game_commit(state, region, result, speaker, settings, game)

    def _game_speaker(self, state, regions, game):
        """Ayri 'konusan adi' bolgesi varsa oradaki ad (listedeki ada oturtulur)."""
        for region in regions:
            if region['role'] != 'speaker':
                continue
            lines = state.reader(game_screen.grab(region['rect'])) if state.reader else []
            if lines:
                return game_core.snap_name(lines[0], game['terms'])
        return ''

    def _game_instant(self, state, region, text, speaker, settings, game):
        """Yazi daha gelirken onbellekte tam hali varsa ceviri hemen gosterilir."""
        cache = self._game_cache_for(game)
        entry = cache.get(text) or cache.complete(text)
        if entry is None or state.showing.get(region['id']) == game_core.compact(entry['source']):
            return
        state.showing[region['id']] = game_core.compact(entry['source'])
        self._game_generation[region['id']] = self._game_generation.get(region['id'], 0) + 1
        self._game_show(region, entry['translation'], speaker or entry.get('speaker', ''), settings)

    # ------------------------------------------------------------------ tarama kipi (yazilarin ustune)
    def _game_blocks(self, state, settings, game, region, force, now):
        """Bolgedeki (tum ekran olabilir) her yaziyi ayri bulur ve cevirisini o yazinin tam ustune koyar.
        Yerlesen yeni yazilar tek istekte toplu cevrilir; onbellektekiler hemen gosterilir."""
        import game_overlay
        key = region['id']
        blocks = state.blocks.setdefault(key, _Blocks())
        fresh = False
        if force or blocks.items is None or now >= blocks.next_ocr:
            image = self._game_grab(region['rect'])
            fp = game_screen.fingerprint(image)
            same = not game_screen.changed(state.fps.get(key), fp)
            state.fps[key] = fp
            # Her bakis (goruntu ayni kalsa da) kaybolan yazi icin bir 'gorulmedi' sayar: sahne degisip sabit
            # kalinca eski ekranin cevirileri ekranda kalmasin.
            fresh = True
            blocks.next_ocr = now + max(settings['interval_ms'] / 1000, BLOCK_OCR_GAP)
            if force or blocks.items is None or not same:
                started = time.perf_counter()
                lines = state.reader.boxes(image)
                self._game_info = {'engine': state.reader.label,
                                   'ocr_ms': round((time.perf_counter() - started) * 1000)}
                items = game_core.text_blocks(lines, game['language'], region['scan'] == 'prose')
                for item in items:
                    # Parmak izi: OCR'siz turlarda bu yazinin degisip degismedigi ucuzca denetlenir.
                    area = _around(item['box'], item['height'])
                    crop = image.crop((area[0], area[1], area[0] + area[2], area[1] + area[3]))
                    item['fp'] = game_screen.fingerprint(crop)
                    item['colors'] = game_overlay.area_colors(crop) if settings['game_colors'] else None
                    item['box'][0] += region['rect'][0]
                    item['box'][1] += region['rect'][1]
                blocks.items = items
                self._game_block_vanished(region, image, items)
                # Genis alanin OCR'i pahali: hareketli sahnede her aralikta degil, en sik BLOCK_OCR_GAP'te bir.
        elif blocks.items:
            self._game_block_changes(state, blocks, region, settings, now)
        cache = self._game_cache_for(game)
        seen, ready = {}, []
        for item in blocks.items:
            text = game_core.compact(item['text'])
            first, looks = blocks.seen.get(text, (now, 0))
            seen[text] = (first, looks + 1) if fresh else (first, looks)
            if text in blocks.busy or blocks.skip.get(text, 0) > now or cache.get(item['text']) is not None:
                continue
            # Daktilo bitti: ayni yazi en az iki ayri bakista (aradaki surede) gorulmeli; OCR'siz gecen
            # turlar yazinin yerlestigini kanitlamaz (yarim cumle cevrilmesin).
            if force or (seen[text][1] >= 2 and now - first >= settings['settle_ms'] / 1000):
                ready.append(item)
        blocks.seen = seen
        if ready and not blocks.busy and (force or now >= blocks.retry_after):
            batch, size = [], 0
            for item in ready:
                if batch and (len(batch) >= game_core.BATCH_MAX or size + len(item['text']) > game_core.BATCH_CHARS):
                    break
                batch.append(item)
                size += len(item['text'])
            blocks.busy = {game_core.compact(item['text']) for item in batch}
            threading.Thread(target=self._game_batch, name='aktar-game-batch', daemon=True,
                             args=(region, blocks, batch, settings, game, self._game_generation.get(key, 0))).start()
        self._game_show_blocks(region, blocks, settings, game, fresh)

    def _game_block_vanished(self, region, image, items):
        """Tam OCR'de bulunamayan kutu: alani da degistiyse yazi gercekten kalkmistir, hemen gizlenir. Alan
        ayniysa OCR o okumada kacirmis olabilir; BLOCK_MISSES kurali bekler (ceviri yanip sonmesin)."""
        host = self._game_host
        key = region['id']
        with self._game_lock:
            current = self._game_block_shown.get(key, {})
            for source, entry in list(current.items()):
                if entry.get('fp') is None or any(_overlaps(entry['box'], item['box']) for item in items):
                    continue
                area = _around(entry['box'], entry['height'])
                left, top = area[0] - region['rect'][0], area[1] - region['rect'][1]
                crop = image.crop((left, top, left + area[2], top + area[3]))
                if game_screen.changed(entry['fp'], game_screen.fingerprint(crop)):
                    del current[source]
                    if host:
                        host.hide(entry['key'])
                    self._game_block_free.setdefault(key, []).append(entry['key'])

    def _game_block_changes(self, state, blocks, region, settings, now):
        """OCR'siz turlarda ceviri kutularinin altindaki ozgun yazi degisti mi (diyalog gecti, pencere kapandi)?
        Tam OCR'i beklemeden: degisen kutunun alani kucuk bir OCR'le okunur; yazi kalktiysa kutu hemen gizlenir,
        yerine baska yazi geldiyse ozgun yine ortulur (bos kutu) ve tam OCR one alinir."""
        host = self._game_host
        if host is None or not host.capture_safe:
            return            # katman yakalamadan dislanamiyorsa her turda gizle-yakala titrer
        import game_overlay
        key = region['id']
        with self._game_lock:
            shown = list(self._game_block_shown.get(key, {}).items())[:QUICK_CHECKS]
        for source, entry in shown:
            if entry.get('fp') is None:
                continue
            area = _around(entry['box'], entry['height'])
            image = game_screen.grab(area)
            fp = game_screen.fingerprint(image)
            if not game_screen.changed(entry['fp'], fp):
                continue
            text = ' '.join(state.reader(image))
            change = game_core.reading_change(entry['text'], text)
            entry['fp'] = fp
            if change == 'same':
                continue          # yalnizca arkadaki sahne kipirdadi
            blocks.next_ocr = now
            if change == 'grew':
                continue
            blocks.items = [item for item in blocks.items or [] if not _overlaps(item['box'], entry['box'])]
            with self._game_lock:
                current = self._game_block_shown.get(key, {})
                if current.get(source) is not entry:
                    continue
                if change == 'gone':
                    del current[source]
                    host.hide(entry['key'])
                    self._game_block_free.setdefault(key, []).append(entry['key'])
                    continue
                # Yerine yeni yazi geldi: ceviri kalkar, ozgun Ingilizce bos kutuyla ortulu kalir.
                image, x, y = game_overlay.render_block('', entry['box'], entry['height'], self._game_style(settings),
                                                        game_screen.virtual_screen(), colors=entry.get('colors'),
                                                        placeholder=True)
                host.show(entry['key'], image, x, y)
                del current[source]
                current['…' + game_core.compact(text)] = dict(entry, translation=None, text=text, miss=0)

    def _game_batch(self, region, blocks, batch, settings, game, generation):
        key = region['id']
        current = lambda: self._game_generation.get(key, 0) == generation and self._game_host is not None  # noqa: E731
        cache = self._game_cache_for(game)
        started = time.perf_counter()
        stored = set()
        last_draw = [0.0]

        def store(found):
            for number, translation in found.items():
                if number in stored:
                    continue
                stored.add(number)
                item = batch[number - 1]
                cache.put(item['text'], translation, item['speaker'])
                if len(item['text'].split()) >= 4:        # menu ogeleri son cevirileri doldurmasin
                    self._game_record(region, item['text'], item['speaker'], translation, False, started)
            if found and current():
                self._game_show_blocks(region, blocks, settings, game, False)

        def partial(value):     # akarken biten ogeler hemen ekrana gelir
            if time.monotonic() - last_draw[0] >= STREAM_REDRAW:
                last_draw[0] = time.monotonic()
                store(game_core.parse_batch(value, len(batch), final=False))
        history = list(self._game_history)[-settings['context_lines']:] if settings['context_lines'] else []
        messages = game_core.batch_messages(batch, history, game['terms'], game['language'])
        try:
            client = Client(self._game_cfg(settings), lambda _message: None)
            result, finish = client.chat_stream(messages, on_delta=partial, temperature=0.2,
                                                max_tokens=game_core.batch_tokens(batch), cancelled=lambda: not current())
            if finish != 'cancelled' and current():
                store(game_core.parse_batch(result, len(batch)))
                missing = [item for number, item in enumerate(batch, 1) if number not in stored]
                for item in missing:      # model atladiysa ayni yazi hemen yeniden istenmesin
                    blocks.skip[game_core.compact(item['text'])] = time.monotonic() + SKIP_GAP
                if len(missing) == len(batch):
                    self._game_report('Model çeviri listesini beklenen biçimde döndürmedi.')
        except (RuntimeError, ValueError, OSError) as error:
            if current():
                self._game_report(error)
            blocks.retry_after = time.monotonic() + RETRY_GAP
        finally:
            blocks.busy = set()

    def _game_show_blocks(self, region, blocks, settings, game, fresh):
        """Cevirisi bilinen yazilarin ustune kutu; cevirisi beklenenlerin ustune bos kutu (ozgun Ingilizce
        ceviri gelene kadar ortulu kalir). Kaybolan yazinin kutusu BLOCK_MISSES okumadan sonra gizlenir
        (OCR bir okumada yaziyi kacirirsa ceviri yanip sonmesin)."""
        import game_overlay
        key = region['id']
        cache = self._game_cache_for(game)
        style = self._game_style(settings)
        screen = game_screen.virtual_screen()
        now = time.monotonic()
        with self._game_lock:
            shown = self._game_block_shown.get(key, {})
            free = self._game_block_free.setdefault(key, [])
            current = {}
            for item in blocks.items or []:
                text = game_core.compact(item['text'])
                entry = cache.get(item['text']) or cache.complete(item['text'])
                if entry is None:
                    # Ceviri bekleniyor: model atladiysa ya da istek basarisizsa ozgun acik kalir.
                    if blocks.skip.get(text, 0) > now or now < blocks.retry_after:
                        continue
                    source, translation = '…' + text, None
                else:
                    source, translation = game_core.compact(entry['source']), entry['translation']
                if source in current:
                    continue
                old = shown.pop(source, None) or shown.pop('…' + text, None)
                if old is None:     # daktilo ilerledi: ayni yerdeki bos kutu yeni yaziya gecer (titremesin)
                    near = next((name for name, value in shown.items()
                                 if value['translation'] is None and _overlaps(value['box'], item['box'])), None)
                    old = shown.pop(near) if near else None
                if old and old['translation'] == translation and not _moved(old['box'], item['box'], item['height']):
                    old.update(miss=0, fp=item.get('fp') or old.get('fp'))
                    current[source] = old
                    continue
                if old:
                    window = old['key']
                elif free:
                    window = free.pop()
                else:
                    self._game_block_seq = getattr(self, '_game_block_seq', 0) + 1
                    window = f'{key}#{self._game_block_seq}'
                if self._game_host:
                    box = list(item['box'])
                    if translation is None and len(item['lines']) == 1:
                        # Tek satir daktiloyla uzuyor olabilir: bos kutu saga genis tutulur, yeni harfler de ortulur.
                        box[2] = max(box[2], min(box[2] * 2, region['rect'][0] + region['rect'][2] - box[0]))
                    image, x, y = game_overlay.render_block(translation or '', box, item['height'], style, screen,
                                                            pitch=item.get('pitch'), colors=item.get('colors'),
                                                            placeholder=translation is None)
                    self._game_host.show(window, image, x, y)
                current[source] = {'key': window, 'translation': translation, 'box': list(item['box']), 'miss': 0,
                                   'height': item['height'], 'text': item['text'], 'fp': item.get('fp'),
                                   'colors': item.get('colors')}
            for source, old in shown.items():
                old['miss'] += 1 if fresh else 0
                covered = any(_overlaps(old['box'], other['box']) for other in current.values())
                if old['miss'] >= BLOCK_MISSES or covered:
                    if self._game_host:
                        self._game_host.hide(old['key'])
                    free.append(old['key'])
                else:
                    current[source] = old
            self._game_block_shown[key] = current

    # ------------------------------------------------------------------ ceviri
    def _game_cfg(self, settings, vision=False):
        cfg = dict(load_config())
        model = settings['model'] or cfg['model']
        if vision:
            model = settings['vision_model'] or str(cfg.get('vision_model') or '').strip() or model
        cfg.update(model=model, vision_model=model, disable_thinking=True, temperature=0.2,
                   timeout_seconds=min(90, int(cfg['timeout_seconds'])))
        cfg.pop('thinking', None)
        return cfg

    def _game_record(self, region, source, speaker, translation, cached, started):
        item = {'time': time.strftime('%H:%M:%S'), 'region': region['name'], 'speaker': speaker, 'source': source,
                'translation': translation, 'cached': cached, 'ms': round((time.perf_counter() - started) * 1000)}
        self._game_recent.appendleft(item)
        self._game_history.append({'speaker': speaker, 'source': source, 'translation': translation})
        self._game_error = ''
        self._game_push()

    def _game_commit(self, state, region, text, speaker, settings, game):
        key = region['id']
        started = time.perf_counter()
        cache = self._game_cache_for(game)
        now = time.monotonic()
        last = self._game_last.get(key)
        # Daktilo arasinda bir an duran yazi once yarim cevrilmis olabilir: tamami gelince yarim kayit silinir.
        if (last and last['fresh'] and now - last['time'] < 30
                and game_core.compact(text).startswith(game_core.compact(last['text']))):
            cache.forget(last['text'])
        # Yarim yazi (oyun cumlenin ortasinda durdu) onbellekteki bir cumlenin basiysa o cumle gosterilir.
        entry = cache.get(text) or cache.complete(text)
        self._game_last[key] = {'text': text, 'time': now, 'fresh': entry is None}
        state.showing[key] = game_core.compact(text)
        generation = self._game_generation.get(key, 0) + 1
        self._game_generation[key] = generation
        if entry is not None:
            speaker = speaker or entry.get('speaker', '')
            self._game_show(region, entry['translation'], speaker, settings)
            self._game_record(region, text, speaker, entry['translation'], True, started)
            return
        history = list(self._game_history)[-settings['context_lines']:] if settings['context_lines'] else []
        threading.Thread(target=self._game_translate, name='aktar-game-request', daemon=True,
                         args=(region, text, speaker, history, settings, game, generation, started)).start()

    def _game_translate(self, region, text, speaker, history, settings, game, generation, started):
        key = region['id']
        current = lambda: self._game_generation.get(key) == generation and self._game_host is not None  # noqa: E731
        messages = game_core.translation_messages(text, speaker, history, game['terms'], game['language'])
        last_draw = [0.0]

        def partial(value):
            value = game_core.clean_translation(value)
            if value and current() and time.monotonic() - last_draw[0] >= STREAM_REDRAW:
                last_draw[0] = time.monotonic()
                self._game_show(region, value + ' …', speaker, settings)
        try:
            client = Client(self._game_cfg(settings), lambda _message: None)
            result, finish = client.chat_stream(messages, on_delta=partial, temperature=0.2,
                                                max_tokens=game_core.max_tokens_for(text),
                                                cancelled=lambda: not current())
        except (RuntimeError, ValueError, OSError) as error:
            if current():
                self._game_report(error)
            return
        if finish == 'cancelled' or not current():
            return
        translation = game_core.clean_translation(result)
        if not translation:
            self._game_report('Model boş çeviri döndürdü.')
            return
        self._game_cache_for(game).put(text, translation, speaker)
        self._game_show(region, translation, speaker, settings)
        self._game_record(region, text, speaker, translation, False, started)

    def _game_vision(self, region, image, settings, game):
        key = region['id']
        generation = self._game_generation.get(key, 0) + 1
        self._game_generation[key] = generation
        threading.Thread(target=self._game_vision_request, name='aktar-game-vision', daemon=True,
                         args=(region, image, settings, game, generation)).start()

    def _game_vision_request(self, region, image, settings, game, generation):
        started = time.perf_counter()
        try:
            client = Client(self._game_cfg(settings, vision=True), lambda _message: None)
            prompt = game_core.vision_prompt(game['terms'], list(self._game_history)[-1:])
            answer = client.vision(prompt, game_screen.png_bytes(image, 1600), max_tokens=700)
        except (RuntimeError, ValueError, OSError) as error:
            self._game_report(f'Görsel model: {error}')
            return
        if self._game_generation.get(region['id']) != generation:
            return
        value = game_core.parse_vision(answer)
        if not value['translation']:
            self._game_hide(region['id'])
            return
        speaker = game_core.snap_name(value['speaker'], game['terms']) if value['speaker'] else ''
        if value['text']:
            self._game_cache_for(game).put(value['text'], value['translation'], speaker)
        self._game_show(region, value['translation'], speaker, settings)
        self._game_record(region, value['text'] or '(görüntü)', speaker, value['translation'], False, started)

    def _game_screen_vision(self, settings, game):
        """Bolge tanimli degilken 'Simdi cevir': birincil ekranin tamami gorsel modele gider, ceviri altta."""
        width, height = game_screen.primary_size()
        region = {'id': '_screen', 'name': 'Tüm ekran', 'rect': [width // 6, height - height // 4, width * 2 // 3, 1],
                  'placement': 'below', 'target': None}
        self._game_toast('Ekran görsel modelle okunuyor…', force=True)
        self._game_vision(region, game_screen.grab([0, 0, width, height]), settings, game)


def _around(box, height):
    """Yazinin kutusu ve cevresi (OCR kutusu ust uctan taban cizgisine: alt uzantilar ve zemin de girsin)."""
    margin = max(2, round(0.35 * height))
    return [round(box[0]) - margin, round(box[1]) - margin, round(box[2]) + 2 * margin, round(box[3]) + 2 * margin]


def _moved(before, after, height):
    return any(abs(a - b) > 0.5 * max(1, height) for a, b in zip(before, after))


def _overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def game_overlay_hide(host, key):
    """Katman is parcaciginda: kutuyu gecici gizler (icerigi silinmez, set_visible geri getirir)."""
    import game_overlay
    hwnd = host._windows.get(key)
    if hwnd:
        game_overlay.user32.ShowWindow(hwnd, game_overlay.SW_HIDE)
