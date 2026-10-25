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


if __name__ == '__main__':
    unittest.main()
