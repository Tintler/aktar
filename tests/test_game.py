"""Oyun ekran cevirisi (F194): game_core, game_overlay'in saf fonksiyonlari ve bridge_game akisi.
Ekran yakalama, Windows OCR ve katman pencereleri burada denenmez (Windows masaustu ister)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import bridge  # noqa: E402
import game_core  # noqa: E402
import game_overlay  # noqa: E402


class TextTests(unittest.TestCase):
    def test_compact_ignores_case_punctuation_and_spacing(self):
        self.assertEqual(game_core.compact("That’s right—but"), game_core.compact("thats right - but"))
        self.assertTrue(game_core.similar('impossible to outrun nightfall', 'imoossible to outrun nightfall'))
        self.assertFalse(game_core.similar("That's right", "That's right—but we'll be doing so"))

    def test_split_speaker_takes_name_line_and_snaps_ocr_noise(self):
        terms = [{'source': 'Lasswell', 'target': '', 'note': ''}]
        self.assertEqual(game_core.split_speaker(['LasswelC', "That's right—bu"], 'auto', terms),
                         ('Lasswell', "That's right—bu"))
        # yalnizca ad gorunuyor, yazi henuz gelmedi: cevrilecek metin yok
        self.assertEqual(game_core.split_speaker(['Lasswell'], 'auto', terms), ('Lasswell', ''))
        # kaymis cumlenin basi ad sayilmaz
        self.assertEqual(game_core.split_speaker(['Come with', 'me now.'], 'auto'), ('', 'Come with me now.'))
        self.assertEqual(game_core.split_speaker(['Hello there.', 'How are you?'], 'auto'),
                         ('', 'Hello there. How are you?'))
        self.assertEqual(game_core.split_speaker(['Lasswell', 'Go.'], 'none'), ('', 'Lasswell Go.'))
        self.assertEqual(game_core.split_speaker(['Narrator voice here', 'Go.'], 'first_line'),
                         ('Narrator voice here', 'Go.'))

    def test_japanese_lines_join_without_spaces(self):
        self.assertEqual(game_core.join_lines(['こんにちは', '世界'], 'ja'), 'こんにちは世界')
        self.assertEqual(game_core.join_lines(['a hyphen-', 'ated word'], 'en'), 'a hyphenated word')


class TrackerTests(unittest.TestCase):
    def test_typewriter_text_is_sent_once_after_it_settles(self):
        tracker = game_core.TextTracker(settle=0.35)
        # harfler geliyor: her yakalamada goruntu ve yazi degisiyor
        self.assertIsNone(tracker.observe("That's right—bu", 0.0))
        self.assertIsNone(tracker.observe("That's right—but we'll", 0.25))
        self.assertIsNone(tracker.observe("That's right—but we'll be doing so after", 0.5))
        # goruntu bir aralik degismedi: yazi yerlesti
        self.assertEqual(tracker.unchanged(0.75), "That's right—but we'll be doing so after")
        self.assertIsNone(tracker.unchanged(1.0))           # ayni yazi ikinci kez gonderilmez
        # arka plan oynuyor (goruntu degisiyor) ama yazi ayni
        self.assertIsNone(tracker.observe("That's right—but we'll be doing so after", 1.25))

    def test_same_text_with_animated_background_settles_by_time(self):
        tracker = game_core.TextTracker(settle=0.35)
        self.assertIsNone(tracker.observe('Hello there.', 0.0))
        self.assertIsNone(tracker.observe('Hello there.', 0.2))
        self.assertEqual(tracker.observe('Hel1o there.', 0.4), 'Hello there.')   # OCR gurultusu ayni yazi

    def test_text_gone_after_settle(self):
        tracker = game_core.TextTracker(settle=0.3)
        tracker.observe('Hello there.', 0.0)
        self.assertEqual(tracker.unchanged(0.25), 'Hello there.')
        self.assertIsNone(tracker.observe('', 0.5))
        self.assertEqual(tracker.unchanged(0.9), 'gone')
        # ayni satir yeniden gelirse yine gonderilir
        tracker.observe('Hello there.', 1.0)
        self.assertEqual(tracker.unchanged(1.25), 'Hello there.')

    def test_force_sends_even_if_already_sent(self):
        tracker = game_core.TextTracker()
        tracker.observe('Hi.', 0)
        tracker.unchanged(0.3)
        self.assertEqual(tracker.force('Hi.'), 'Hi.')
        self.assertIsNone(tracker.force(''))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'onbellek.json'

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_fuzzy_and_persisted(self):
        cache = game_core.TranslationCache(self.path)
        cache.put("At this point, it would be impossible to outrun nightfall.", 'Bu saatte karanlığı geçmek imkânsız.')
        self.assertEqual(cache.get('at this point it would be impossible to outrun nightfall')['translation'],
                         'Bu saatte karanlığı geçmek imkânsız.')
        self.assertIsNotNone(cache.get('At this point, it would be imoossible to outrun niahtfall.'))
        self.assertIsNone(cache.get('Something else entirely.'))
        self.assertEqual(len(game_core.TranslationCache(self.path)), 1)

    def test_complete_finds_full_sentence_while_typing(self):
        cache = game_core.TranslationCache(self.path)
        cache.put("That's right—but we'll be doing so after a night at the inn.", 'Doğru, ama handa bir gece kalınca.')
        self.assertEqual(cache.complete("That's right—bu")['translation'], 'Doğru, ama handa bir gece kalınca.')
        self.assertIsNone(cache.complete("That's"))            # cok kisa: belirsiz
        cache.put("That's right—but not today.", 'Doğru ama bugün değil.')
        self.assertIsNone(cache.complete("That's right—bu"))   # iki farkli cumle: gosterilmez
        cache.forget("That's right—but not today.")
        self.assertIsNotNone(cache.complete("That's right—bu"))
        cache.clear()
        self.assertEqual(len(cache), 0)


class TermTests(unittest.TestCase):
    TERMS = [{'source': 'Rain', 'target': '', 'note': ''}, {'source': 'Lasswell', 'target': '', 'note': 'erkek'},
             {'source': 'chocobo', 'target': 'çokobo', 'note': ''}]

    def test_capitalized_name_does_not_match_common_word(self):
        keep, mapped, ambiguous = game_core.matched_terms('The rain will not stop, said Lasswell.', self.TERMS)
        self.assertEqual([item['source'] for item in keep], ['Lasswell'])
        self.assertEqual((mapped, ambiguous), ([], []))

    def test_name_inside_sentence_is_kept_and_at_start_is_ambiguous(self):
        keep, _, ambiguous = game_core.matched_terms('Where did Rain go?', self.TERMS)
        self.assertEqual([item['source'] for item in keep], ['Rain'])
        self.assertEqual(ambiguous, [])
        keep, _, ambiguous = game_core.matched_terms('Rain is falling again.', self.TERMS)
        self.assertEqual((keep, [item['source'] for item in ambiguous]), ([], ['Rain']))

    def test_lowercase_term_matches_any_case_and_maps(self):
        _, mapped, _ = game_core.matched_terms('Two Chocobos ran off.', self.TERMS)
        self.assertEqual([item['target'] for item in mapped], ['çokobo'])

    def test_messages_carry_speaker_terms_and_history(self):
        messages = game_core.translation_messages(
            'Where did Rain go?', speaker='Lasswell', terms=self.TERMS,
            history=[{'speaker': 'Fina', 'source': 'Hello.', 'translation': 'Merhaba.'}])
        user = messages[1]['content']
        self.assertIn('Konuşan: Lasswell', user)
        self.assertIn('Özel adlar (çevirme, aynen yaz): Rain', user)
        self.assertNotIn('Lasswell: erkek', user.split('Konuşan')[0])
        self.assertIn('- Fina: Hello. => Merhaba.', user)
        self.assertTrue(user.endswith('Where did Rain go?'))
        self.assertIn('İngilizce', messages[0]['content'])

    def test_clean_terms_dedupes_with_case_rule(self):
        terms = game_core.clean_terms([{'source': ' Rain '}, {'source': 'Rain'}, {'source': 'rain'},
                                       {'source': 'Chocobo'}, {'source': ''}, 'x'])
        self.assertEqual([item['source'] for item in terms], ['Rain', 'rain', 'Chocobo'])


class ResponseTests(unittest.TestCase):
    def test_clean_translation_strips_labels_quotes_and_thinking(self):
        self.assertEqual(game_core.clean_translation('<think>x</think>Çeviri: "Merhaba dünya."'), 'Merhaba dünya.')
        self.assertEqual(game_core.clean_translation('“Doğru.”'), 'Doğru.')

    def test_parse_vision_json_and_plain(self):
        value = game_core.parse_vision('```json\n{"speaker": "Lasswell", "text": "Hi.", "translation": "Selam."}\n```')
        self.assertEqual(value, {'speaker': 'Lasswell', 'text': 'Hi.', 'translation': 'Selam.'})
        self.assertEqual(game_core.parse_vision('Selam.')['translation'], 'Selam.')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_settings_are_clamped_and_unknown_keys_dropped(self):
        value = game_core.save_settings({'font_size': 500, 'opacity': '0.5', 'text_color': 'red', 'evil': 1,
                                         'hotkeys': {'now': 'Ctrl+F12', 'other': 'x'}, 'ocr_engine': 'magic'},
                                        self.base)
        self.assertEqual(value['font_size'], 72)
        self.assertEqual(value['opacity'], 0.5)
        self.assertEqual(value['text_color'], '#ffffff')
        self.assertEqual(value['ocr_engine'], 'auto')
        self.assertEqual(value['hotkeys'], {'toggle': 'Ctrl+F9', 'overlay': 'Ctrl+F10', 'now': 'Ctrl+F12'})
        self.assertNotIn('evil', game_core.load_settings(self.base))

    def test_games_regions_and_delete(self):
        game = game_core.create_game('Final Fantasy: Brave Exvius', self.base)
        again = game_core.create_game('Final Fantasy: Brave Exvius', self.base)
        self.assertNotEqual(game['id'], again['id'])
        game['regions'] = [{'name': 'Diyalog', 'rect': [10, 20, 300, 80], 'placement': 'custom'},
                           {'rect': [0, 0, 50, 50], 'mode': 'vision', 'role': 'speaker'}]
        saved = game_core.save_game(game, self.base)
        first, second = saved['regions']
        self.assertEqual(first['placement'], 'below')            # ozel konum secilmeden 'custom' olmaz
        self.assertTrue(first['auto'])
        self.assertFalse(second['auto'])                          # gorsel model varsayilan olarak kisayolla
        self.assertEqual(second['role'], 'speaker')
        self.assertNotEqual(first['id'], second['id'])
        with self.assertRaises(ValueError):
            game_core.clean_region({'rect': [0, 0, 2, 2]})
        self.assertEqual(len(game_core.list_games(self.base)), 2)
        game_core.TranslationCache(game_core.cache_path(game['id'], self.base)).put('Hi.', 'Selam.')
        game_core.delete_game(game['id'], self.base)
        self.assertIsNone(game_core.load_game(game['id'], self.base))
        self.assertFalse(game_core.cache_path(game['id'], self.base).exists())


class OverlayTests(unittest.TestCase):
    def test_parse_hotkey(self):
        self.assertEqual(game_overlay.parse_hotkey('Ctrl+F9'), (0x2, 0x78))
        self.assertEqual(game_overlay.parse_hotkey('Ctrl+Shift+T'), (0x6, ord('T')))
        self.assertEqual(game_overlay.parse_hotkey('F10'), (0, 0x79))
        self.assertEqual(game_overlay.parse_hotkey('Alt+Numpad5'), (0x1, 0x65))
        for bad in ('T', '', 'Ctrl+', 'Hyper+T', 'Ctrl+Nope'):
            with self.assertRaises(ValueError):
                game_overlay.parse_hotkey(bad)

    def test_place_flips_at_screen_edges(self):
        screen = [0, 0, 1920, 1080]
        self.assertEqual(game_overlay.place([100, 800, 600, 150], 'below', (600, 120), screen), (100, 956))
        self.assertEqual(game_overlay.place([100, 900, 600, 150], 'below', (600, 120), screen), (100, 774))
        self.assertEqual(game_overlay.place([100, 10, 600, 150], 'above', (600, 120), screen), (100, 166))
        self.assertEqual(game_overlay.place([100, 500, 600, 150], 'cover', (600, 150), screen), (100, 500))
        self.assertEqual(game_overlay.place([100, 500, 600, 150], 'custom', (400, 90), screen, [1700, 50, 400, 90]),
                         (1520, 50))

    def test_render_wraps_and_fits_cover_height(self):
        style = {'font_size': 30, 'opacity': 0.5, 'text_color': '#ffffff', 'background': '#000000'}
        text = 'Doğru, ama bunu handa bir gece geçirdikten sonra yapacağız. Şu saatte karanlığı geçmek imkânsız.'
        image = game_overlay.render(text, 400, style, speaker='Lasswell')
        self.assertEqual(image.width, 400)
        self.assertEqual(image.mode, 'RGBA')
        self.assertEqual(image.getpixel((200, 2))[3], round(255 * 0.5))
        fitted = game_overlay.render(text, 400, style, fit_height=120)
        self.assertEqual(fitted.height, 120)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(game_core, 'APP_DIR', Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.events = []
        self.bridge = bridge.Bridge(emit=lambda event, data: self.events.append((event, data)))

    def tearDown(self):
        self.bridge._stop_game_for_close()
        self.temp.cleanup()

    def test_create_update_and_snapshot(self):
        with mock.patch('bridge_game.WINDOWS', False):
            snap = self.bridge.game_create('Test Oyunu')
            self.assertEqual(snap['game']['name'], 'Test Oyunu')
            self.assertFalse(snap['supported'])
            result = self.bridge.game_update({'regions': [{'rect': [0, 0, 100, 40]}], 'terms': [{'source': 'Rain'}]})
            self.assertEqual(len(result['game']['regions']), 1)
            self.assertIn('error', self.bridge.game_update({'regions': [{'rect': [0, 0, 1, 1]}]}))
            self.assertIn('error', self.bridge.game_start())

    def test_partial_text_of_cached_sentence_shows_cache_without_model(self):
        game = game_core.create_game('Test')
        region = game_core.clean_region({'rect': [0, 0, 100, 40], 'id': 'r1'})
        self.bridge._game_cache_for(game).put("That's right—but we'll be doing so after a night at the inn.",
                                              'Doğru, ama handa bir gece kalınca.', 'Lasswell')
        shown = []
        with mock.patch.object(self.bridge, '_game_show', lambda region, text, speaker, settings: shown.append(text)), \
                mock.patch('bridge_game.threading.Thread') as thread:
            from bridge_game import _Pass
            self.bridge._game_commit(_Pass(), region, "That's right—bu", '', game_core.load_settings(), game)
        thread.assert_not_called()
        self.assertEqual(shown, ['Doğru, ama handa bir gece kalınca.'])
        self.assertTrue(self.bridge._game_recent[0]['cached'])

    def test_completed_text_forgets_fresh_partial_translation(self):
        game = game_core.create_game('Test')
        region = game_core.clean_region({'rect': [0, 0, 100, 40], 'id': 'r1'})
        cache = self.bridge._game_cache_for(game)
        with mock.patch('bridge_game.threading.Thread'):
            from bridge_game import _Pass
            self.bridge._game_commit(_Pass(), region, 'At this point, it would', '', game_core.load_settings(), game)
            cache.put('At this point, it would', 'Bu noktada, bu')        # yarim yazinin cevirisi geldi
            self.bridge._game_commit(_Pass(), region, 'At this point, it would be impossible.', '',
                                     game_core.load_settings(), game)
        self.assertIsNone(cache.get('At this point, it would'))

    def test_blocks_show_cached_at_place_and_batch_new_text_once_settled(self):
        game = game_core.create_game('Test')
        region = game_core.clean_region({'rect': [100, 50, 1000, 600], 'id': 'scr', 'placement': 'blocks', 'scan': 'all'})
        settings = game_core.load_settings()
        self.bridge._game_cache_for(game).put('Attack', 'Saldır')

        class Reader:
            label = 'deneme'

            def boxes(self, image):
                return [[('Attack', 10, 10, 80, 20)], [('Perform', 10, 60, 100, 20), ('a', 115, 60, 10, 20),
                                                       ('physical', 130, 60, 120, 20)]]
        from PIL import Image
        from bridge_game import _Pass
        state = _Pass()
        state.reader = Reader()
        self.bridge._game_host = mock.Mock()
        with mock.patch('bridge_game.game_screen.grab', return_value=Image.new('RGB', (1000, 600))), \
                mock.patch('bridge_game.game_screen.virtual_screen', return_value=[0, 0, 1920, 1080]), \
                mock.patch('bridge_game.threading.Thread') as thread:
            self.bridge._game_blocks(state, settings, game, region, False, 100.0)
            thread.assert_not_called()                     # yeni yazi daha yerlesmedi
            (key, image, x, y), (pending, _image, _x, py) = [call[0] for call in self.bridge._game_host.show.call_args_list]
            self.assertTrue(key.startswith('scr#'))
            self.assertLess(abs(x - 110), 10)              # cevirinin kutusu yazinin ustunde
            self.assertLess(abs(y - 60), 10)
            self.assertLess(abs(py - 110), 10)             # cevirisi beklenen yazi bos kutuyla ortulur
            self.bridge._game_blocks(state, settings, game, region, False, 101.0)
            thread.assert_called_once()
            batch = thread.call_args.kwargs['args'][2]
            self.assertEqual([item['text'] for item in batch], ['Perform a physical'])
            self.assertEqual(self.bridge._game_host.show.call_count, 2)   # ayni kutular yeniden cizilmez
            self.bridge._game_cache_for(game).put('Perform a physical', 'Fiziksel bir')
            self.bridge._game_show_blocks(region, state.blocks['scr'], settings, game, False)
        self.assertEqual(self.bridge._game_host.show.call_args[0][0], pending)   # ceviri bos kutunun yerine
        self.bridge._game_host.hide.assert_not_called()

    def test_blocks_hide_at_once_when_text_under_translation_changes(self):
        game = game_core.create_game('Test')
        region = game_core.clean_region({'rect': [0, 0, 1000, 600], 'id': 'scr', 'placement': 'blocks', 'scan': 'all'})
        settings = game_core.load_settings()
        self.bridge._game_cache_for(game).put('Welcome to the inn', 'Hana hoş geldin')
        reading = ['Welcome to the inn']

        class Reader:
            label = 'deneme'

            def boxes(self, image):
                return [[('Welcome', 10, 10, 120, 20), ('to', 135, 10, 30, 20), ('the', 170, 10, 40, 20),
                         ('inn', 215, 10, 40, 20)]]

            def __call__(self, image):
                return list(reading)
        from PIL import Image
        from bridge_game import _Pass
        state = _Pass()
        state.reader = Reader()
        self.bridge._game_host = mock.Mock(capture_safe=True)
        screens = [Image.new('RGB', (1000, 600)), Image.new('RGB', (40, 40), 'white')]
        with mock.patch('bridge_game.game_screen.grab', side_effect=lambda rect: screens[0] if rect[2] == 1000 else screens[1]), \
                mock.patch('bridge_game.game_screen.virtual_screen', return_value=[0, 0, 1920, 1080]):
            self.bridge._game_blocks(state, settings, game, region, False, 100.0)
            window = self.bridge._game_host.show.call_args[0][0]
            self.bridge._game_blocks(state, settings, game, region, False, 100.1)     # OCR'siz tur: ayni yazi
            self.bridge._game_host.hide.assert_not_called()
            reading[:] = []                                                          # diyalog kapandi
            screens[1] = Image.new('RGB', (40, 40), 'gray')
            self.bridge._game_blocks(state, settings, game, region, False, 100.2)
        self.bridge._game_host.hide.assert_called_once_with(window)
        self.assertEqual(state.blocks['scr'].next_ocr, 100.2)                        # tam OCR one alinir

    def test_blocks_hide_at_once_when_full_ocr_misses_changed_text(self):
        game = game_core.create_game('Test')
        region = game_core.clean_region({'rect': [0, 0, 1000, 600], 'id': 'scr', 'placement': 'blocks', 'scan': 'all'})
        self.bridge._game_cache_for(game).put('Attack', 'Saldır')
        found = [[('Attack', 10, 10, 80, 20)]]

        class Reader:
            label = 'deneme'

            def boxes(self, image):
                return list(found)
        from PIL import Image
        from bridge_game import _Pass
        state = _Pass()
        state.reader = Reader()
        self.bridge._game_host = mock.Mock(capture_safe=True)
        screens = [Image.new('RGB', (1000, 600))]
        with mock.patch('bridge_game.game_screen.grab', side_effect=lambda rect: screens[0]), \
                mock.patch('bridge_game.game_screen.virtual_screen', return_value=[0, 0, 1920, 1080]):
            settings = game_core.load_settings()
            self.bridge._game_blocks(state, settings, game, region, False, 100.0)
            found[:] = []
            self.bridge._game_blocks(state, settings, game, region, False, 101.0)   # OCR kacirdi, alan ayni
            self.bridge._game_host.hide.assert_not_called()
            screens[0] = Image.new('RGB', (1000, 600), 'white')
            self.bridge._game_blocks(state, settings, game, region, False, 102.0)   # alan da degisti
        self.bridge._game_host.hide.assert_called_once()

    def test_reading_change(self):
        self.assertEqual(game_core.reading_change('Welcome to the inn', 'Welcome to the lnn'), 'same')
        self.assertEqual(game_core.reading_change('Welcome to', 'Welcome to the inn'), 'grew')
        self.assertEqual(game_core.reading_change('Welcome to the inn', ''), 'gone')
        self.assertEqual(game_core.reading_change('Welcome to the inn', 'Are you ready?'), 'other')


class BlockTests(unittest.TestCase):
    @staticmethod
    def line(text, x, y, height=20, gap=6):
        words = []
        for word in text.split():
            width = len(word) * height // 2
            words.append((word, x, y, width, height))
            x += width + gap
        return words

    def test_paragraph_lines_join_and_list_items_stay_apart(self):
        lines = [self.line('In the Kolobos Ruins, Rain’s subordinates who had been cut down', 1000, 100),
                 self.line('at the Earth Shrine return as wraith soldiers.', 1000, 130),
                 self.line('Though Lazarov manages to elude Rain and Lasswell, they help', 1000, 200),
                 self.line('Phys. Atk.', 100, 100), self.line('Phys. Def.', 100, 128),
                 self.line('Lv.1', 600, 300) + self.line('Holy Ray', 700, 300)]
        texts = [item['text'] for item in game_core.text_blocks(lines)]
        self.assertIn('In the Kolobos Ruins, Rain’s subordinates who had been cut down at the Earth Shrine '
                      'return as wraith soldiers.', texts)
        self.assertIn('Though Lazarov manages to elude Rain and Lasswell, they help', texts)
        self.assertIn('Phys. Atk.', texts)
        self.assertIn('Phys. Def.', texts)
        self.assertIn('Holy Ray', texts)
        self.assertNotIn('Lv.1', texts)                    # yalnizca kisaltma ve rakam: cevrilmez

    def test_name_line_above_dialog_becomes_speaker_context(self):
        lines = [self.line('Innkeeper', 500, 880, 32),
                 self.line('Welcome. How about a rest in our beds, lulled by the gentle sound of', 510, 940, 30),
                 self.line('the waves?', 510, 980, 30)]
        blocks = game_core.text_blocks(lines)
        dialog = next(item for item in blocks if item['text'].startswith('Welcome'))
        self.assertTrue(dialog['text'].endswith('the waves?'))
        self.assertEqual(dialog['speaker'], 'Innkeeper')

    def test_prose_only_skips_skill_stat_and_menu_labels(self):
        for label in ('Holy Ray', 'Radiant Restoration', 'Phys. Atk.', 'Hide Tips', 'Next Rank:', 'Lasswell',
                      '@ Skill Details (b Hide Tips O Back', 'Longsword Bronze Chestplate Earrings of Health'):
            self.assertFalse(game_core.is_prose(label), label)
        for sentence in ('Perform a physical attack with equipped weapon.', 'Ride the ship out of Grandport',
                         'Welcome to Grandport!', 'Welcome. How about a rest in our beds?'):
            self.assertTrue(game_core.is_prose(sentence), sentence)
        lines = [self.line('Holy Ray', 100, 100), self.line('Perform a physical attack with equipped weapon.', 100, 300)]
        self.assertEqual([item['text'] for item in game_core.text_blocks(lines, prose_only=True)],
                         ['Perform a physical attack with equipped weapon.'])

    def test_worth_translating(self):
        self.assertFalse(game_core.worth_translating('HP 1300'))
        self.assertFalse(game_core.worth_translating('98 > 101'))
        self.assertTrue(game_core.worth_translating('Next'))
        self.assertTrue(game_core.worth_translating('次へ', 'ja'))

    def test_batch_prompt_and_streamed_parse(self):
        items = [{'text': 'Attack', 'speaker': ''}, {'text': 'Welcome, Rain.', 'speaker': 'Innkeeper'}]
        terms = [{'source': 'Rain', 'target': '', 'note': ''}]
        messages = game_core.batch_messages(items, terms=terms)
        user = messages[1]['content']
        self.assertIn('[1] Attack', user)
        self.assertIn('[2] Welcome, Rain.', user)
        self.assertIn('[2] Innkeeper', user)
        self.assertIn('Rain', user.split('Çevrilecek')[0])
        self.assertEqual(game_core.parse_batch('[1] Saldır\n[2] Hoş gel', 2, final=False), {1: 'Saldır'})
        self.assertEqual(game_core.parse_batch('[1] Saldır\n[2] Hoş geldin, Rain.\n[7] fazla', 2),
                         {1: 'Saldır', 2: 'Hoş geldin, Rain.'})
        self.assertEqual(game_core.parse_batch('Saldır', 1), {1: 'Saldır'})
        self.assertEqual(game_core.parse_batch('Saldır', 2), {})

    def test_blocks_region_is_always_ocr(self):
        region = game_core.clean_region({'rect': [0, 0, 1920, 1080], 'placement': 'blocks', 'mode': 'vision'})
        self.assertEqual((region['placement'], region['mode']), ('blocks', 'ocr'))

    def test_tesseract_tsv_lines(self):
        import game_screen
        tsv = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
               '5\t1\t1\t1\t1\t1\t20\t10\t40\t16\t91\tHoly\n'
               '5\t1\t1\t1\t1\t2\t66\t10\t30\t16\t90\tRay\n'
               '5\t1\t2\t1\t1\t1\t20\t60\t40\t16\t12\tgarbage\n')
        self.assertEqual(game_screen.tsv_lines(tsv, 2.0), [[('Holy', 10, 5, 20, 8), ('Ray', 33, 5, 15, 8)]])

    def test_render_block_covers_text_and_shrinks_long_translation(self):
        style = {'font_size': 26, 'opacity': 0.5, 'text_color': '#ffffff', 'background': '#101418'}
        image, x, y = game_overlay.render_block('Saldırı', [200, 100, 80, 24], 24, style)
        self.assertLessEqual(x, 200)
        self.assertLessEqual(y, 100)
        self.assertGreaterEqual(image.height, 24)
        self.assertEqual(image.getpixel((1, image.height // 2))[3], round(255 * 0.96))   # ozgun yaziyi orter
        long, _x, _y = game_overlay.render_block('Donanımlı silahla fiziksel bir saldırı yap ve düşmanı yere ser.',
                                                 [0, 0, 300, 50], 24, style)
        self.assertLessEqual(long.height, 50 + 2 * (24 // 3) + 1)
        colored, _x, _y = game_overlay.render_block('Saldırı', [200, 100, 80, 24], 24, style,
                                                    colors=((20, 40, 60), (250, 250, 250)))
        self.assertEqual(colored.getpixel((2, colored.height // 2)), (20, 40, 60, 255))   # oyunun zemini, opak
        blank, _x, _y = game_overlay.render_block('', [200, 100, 80, 24], 24, style, placeholder=True)
        self.assertGreaterEqual(blank.width, 80)

    def test_area_colors(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (200, 40), (10, 30, 70))
        ImageDraw.Draw(image).rectangle((20, 12, 60, 28), fill=(240, 240, 240))
        background, text = game_overlay.area_colors(image)
        self.assertEqual(background, (10, 30, 70))
        self.assertGreater(sum(text), 600)


if __name__ == '__main__':
    unittest.main()
