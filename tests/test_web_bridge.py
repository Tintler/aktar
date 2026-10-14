"""Web arayuzunun arka ucu (themes, bridge, bridge_translate) testleri; pywebview gerektirmez."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bridge  # noqa: E402
import bridge_library  # noqa: E402
import library  # noqa: E402
import bridge_translate  # noqa: E402
import themes  # noqa: E402


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_palette_file_overrides_base_and_ignores_unknown_names(self):
        base, palette = themes.parse_palette(json.dumps(
            {'base': 'light', 'colors': {'accent': '#A238FF', 'shadow': '#00000040', 'button_glow': '#123456'}}))
        self.assertEqual(base, 'light')
        self.assertEqual(palette['accent'], '#a238ff')
        self.assertEqual(palette['shadow'], '#00000040')
        self.assertEqual(palette['window'], themes.BASES['light']['window'])
        self.assertEqual(set(palette), set(themes.PALETTE_KEYS))

    def test_bad_palette_files_raise_turkish_errors(self):
        for text, part in (('{', 'JSON'), ('[]', 'nesne'), ('{"base": "blue"}', 'base'),
                           ('{"colors": {"accent": "red"}}', 'accent')):
            with self.assertRaises(ValueError) as caught:
                themes.parse_palette(text)
            self.assertIn(part, str(caught.exception))

    def test_every_shipped_preset_parses(self):
        presets = sorted((ROOT / 'assets' / 'themes').glob('*.json'))
        self.assertGreaterEqual(len(presets), 9)
        for path in presets:
            themes.parse_palette(path.read_text(encoding='utf-8'))

    def test_presets_install_once_and_deleted_ones_stay_deleted(self):
        source, folder = self.root / 'presets', self.root / 'themes'
        source.mkdir()
        (source / 'One.json').write_text('{"base": "dark"}', encoding='utf-8')
        themes.install_presets(folder, source)
        self.assertTrue((folder / 'One.json').exists())
        (folder / 'One.json').write_text('{"base": "light"}', encoding='utf-8')
        themes.install_presets(folder, source)  # kullanicinin degisikligi korunur
        self.assertIn('light', (folder / 'One.json').read_text(encoding='utf-8'))
        (folder / 'One.json').unlink()
        themes.install_presets(folder, source)
        self.assertFalse((folder / 'One.json').exists())
        (source / 'Two.json').write_text('{"base": "dark"}', encoding='utf-8')
        themes.install_presets(folder, source)  # yeni surumun yeni temasi gelir
        self.assertTrue((folder / 'Two.json').exists())

    def test_list_and_resolve_fall_back_to_dark(self):
        (self.root / 'Good.json').write_text('{"base": "light", "colors": {"accent": "#112233"}}', encoding='utf-8')
        (self.root / 'Broken.json').write_text('{', encoding='utf-8')
        listed = {item['id']: item for item in themes.list_themes(self.root)}
        self.assertEqual(listed['dark']['name'], 'Koyu')
        self.assertEqual(listed['file:Good.json']['palette']['accent'], '#112233')
        self.assertIn('error', listed['file:Broken.json'])
        self.assertEqual(themes.resolve('file:Good.json', self.root)[0], 'light')
        self.assertEqual(themes.resolve('file:Broken.json', self.root)[0], 'dark')
        self.assertEqual(themes.resolve('file:../../etc.json', self.root)[0], 'dark')
        self.assertEqual(themes.resolve('system', self.root)[0], 'dark')


class TranslateHelperTests(unittest.TestCase):
    def test_review_payload_hides_terms_already_in_series(self):
        payload = bridge_translate.review_payload(
            'pre', {'terms': [{'source': 'Keeper', 'target': 'Bekçi'}, {'source': 'Lamp', 'target': 'Lamba'}],
                    'decisions': ['sen diye hitap']},
            [{'source': 'keeper', 'target': 'Bekçi'}], 'Seri')
        self.assertEqual([item['source'] for item in payload['terms']], ['Lamp'])
        self.assertEqual(payload['decisions'], [{'value': 'sen diye hitap'}])
        self.assertTrue(payload['has_series'])
        self.assertEqual(payload['existing'], 1)
        self.assertIn('Seri', payload['title'])

    def test_review_values_split_by_scope_and_drop_empty_rows(self):
        values = bridge_translate.review_values({
            'terms': [{'source': 'A', 'target': 'a', 'scope': 'series', 'count': 3},
                      {'source': 'B', 'target': ' ', 'scope': 'series'},
                      {'source': 'C', 'target': 'c', 'scope': 'chapter'}],
            'decisions': [{'value': 'karar', 'scope': 'series'}, {'value': '', 'scope': 'chapter'}]}, True)
        self.assertEqual(values['series_terms'], [{'source': 'A', 'target': 'a', 'count': 3}])
        self.assertEqual(values['chapter_terms'], [{'source': 'C', 'target': 'c'}])
        self.assertEqual(values['series_decisions'], ['karar'])
        self.assertEqual(values['chapter_decisions'], [])

    def test_without_series_everything_is_chapter_scoped(self):
        values = bridge_translate.review_values(
            {'terms': [{'source': 'A', 'target': 'a', 'scope': 'series'}],
             'decisions': [{'value': 'k', 'scope': 'series'}]}, False)
        self.assertEqual(values['series_terms'], [])
        self.assertEqual(len(values['chapter_terms']), 1)
        self.assertEqual(values['chapter_decisions'], ['k'])

    def test_clean_glossary_keeps_complete_unique_rows(self):
        rows = bridge_translate.clean_glossary([{'source': ' A ', 'target': 'a'}, {'source': 'a', 'target': 'x'},
                                                {'source': 'B', 'target': ''}, None])
        self.assertEqual(rows, [{'source': 'A', 'target': 'a'}])


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.events = []
        self.patch = mock.patch.object(bridge, 'APP_DIR', self.root)
        self.patch.start()
        self.bridge = bridge.Bridge(emit=lambda event, data: self.events.append((event, data)))

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_public_attributes_are_methods_only(self):
        # pywebview public nitelikleri sayfaya verir ve icinde gezinir: veri alanlari ozel olmali.
        for name in dir(self.bridge):
            if not name.startswith('_'):
                self.assertTrue(callable(getattr(self.bridge, name)), name)

    def test_ui_prefs_merge_and_survive_bad_file(self):
        self.bridge.save_ui_prefs({'theme': 'file:Acid.json'})
        self.bridge.save_ui_prefs({'view': 'translate'})
        self.assertEqual(self.bridge.ui_prefs(), {'theme': 'file:Acid.json', 'view': 'translate'})
        (self.root / 'ui.json').write_text('{', encoding='utf-8')
        self.assertEqual(self.bridge.ui_prefs(), {})

    def test_save_settings_validates_and_keeps_unknown_keys(self):
        (self.root / 'config.json').write_text(json.dumps({'embedding_query_template': 'q: {query}'}), encoding='utf-8')
        result = self.bridge.save_settings({'base_url': 'http://192.168.1.5:1234/v1'})
        self.assertIn('error', result)
        result = self.bridge.save_settings({'batch_cues': '12', 'whisper_language': ' EN ', 'not_a_setting': 1})
        self.assertNotIn('error', result)
        saved = json.loads((self.root / 'config.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['batch_cues'], 12)
        self.assertEqual(saved['embedding_query_template'], 'q: {query}')
        self.assertNotIn('not_a_setting', saved)

    def test_open_video_rejects_non_videos(self):
        self.assertIn('error', self.bridge.open_video(str(self.root / 'notes.txt')))
        self.assertIn('error', self.bridge.open_video(str(self.root / 'missing.mkv')))

    def test_start_translation_needs_a_supported_stream(self):
        self.assertIn('error', self.bridge.start_translation(1))
        self.bridge._video = self.root / 'a.mkv'
        self.bridge._streams = [{'index': 3, 'codec': 'hdmv_pgs_subtitle', 'image': True, 'supported': False}]
        self.assertIn('Görüntü', self.bridge.start_translation(3)['error'])
        self.assertIn('error', self.bridge.start_translation(9))

    def test_close_is_allowed_when_idle(self):
        self.assertTrue(self.bridge.request_close(lambda: None))


class LibraryBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [mock.patch.object(bridge, 'APP_DIR', self.root),
                        mock.patch.object(library, 'APP_DIR', self.root)]
        for patch in self.patches:
            patch.start()
        self.events = []
        self.bridge = bridge.Bridge(emit=lambda event, data: self.events.append((event, data)))

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def wait_scan(self):
        import time
        for _ in range(200):
            if not self.bridge._lib_scanning:
                return
            time.sleep(0.02)

    def test_row_shows_relative_folder_and_length(self):
        root = self.root / 'Dersler'
        entry = {'path': root / 'Hafta-1' / 'a.mkv', 'root': str(root), 'kind': 'video', 'new': True, 'missing': False}
        row = bridge_library.row_of(entry, {'status': 'ready', 'source': 'Altyazı · tur', 'duration': 3725.0})
        self.assertEqual(row['where'], 'Hafta-1')
        self.assertEqual(row['length'], '1:02:05')
        self.assertEqual(row['status_text'], 'Hazır')
        self.assertTrue(row['new'])
        doc = dict(entry, path=root / 'b.pdf', kind='document')
        self.assertEqual(bridge_library.row_of(doc, {'status': 'transcript', 'source': '', 'duration': 12})['length'], '12 sayfa')
        self.assertEqual(bridge_library.where(dict(entry, path=root / 'c.mkv')), 'Dersler')

    def test_chat_entries_turn_citations_into_json(self):
        cite = {'video': self.root / 'a.mkv', 'start': 12.0, 'label': 'V1 0:12', 'title': 'a', 'document': False}
        turn = {'parts': [('text', 'Cevap '), ('cite', [cite])],
                'sources': [{'video': self.root / 'a.mkv', 'start': 12.0, 'label': 'V1', 'title': 'a', 'count': 1}]}
        entries = bridge_library.chat_entries([('user', 'Soru?'), ('assistant', turn), ('note', 'not')])
        json.dumps(entries)  # arayuze gidebilmeli
        self.assertEqual(entries[0], {'kind': 'user', 'text': 'Soru?'})
        self.assertEqual(entries[1]['parts'][1]['items'][0]['label'], 'V1 0:12')
        self.assertEqual(entries[1]['sources'][0]['count'], 1)
        self.assertEqual(entries[2]['kind'], 'note')

    def test_dropping_a_folder_creates_a_collection_and_scans_it(self):
        folder = self.root / 'Dersler'
        (folder / 'Hafta-1').mkdir(parents=True)
        (folder / 'Hafta-1' / '01 Giris.mkv').write_bytes(b'x')
        (folder / 'notlar.txt').write_text('Aşırı öğrenme', encoding='utf-8')
        (folder / 'resim.xyz').write_bytes(b'x')
        state = self.bridge.library_add_paths([str(folder)])
        self.assertEqual(state['title'], 'Dersler')
        self.assertEqual([item['title'] for item in state['collections']], ['Dersler'])
        self.wait_scan()
        state = self.bridge.library_state()
        self.assertEqual(sorted(row['name'] for row in state['rows']), ['01 Giris.mkv', 'notlar.txt'])
        self.assertEqual(state['folders'][0]['count'], 2)
        found = self.bridge.library_search('giris')
        self.assertEqual(len(found['keys']), 1)
        self.assertFalse(self.bridge.library_add_paths([str(folder / 'resim.xyz')]).get('rows'))

    def test_exclude_and_delete_keep_files_on_disk(self):
        folder = self.root / 'Seri'
        folder.mkdir()
        video = folder / 'a.mkv'
        video.write_bytes(b'x')
        state = self.bridge.library_add_paths([str(folder)])
        self.wait_scan()
        state = self.bridge.library_exclude([str(video)])
        self.wait_scan()
        self.assertEqual(self.bridge.library_state()['rows'], [])
        self.assertTrue(video.exists())
        state = self.bridge.delete_collection(state['slug'])
        self.assertEqual(state['collections'], [])
        self.assertEqual(state['slug'], '')
        self.assertTrue(video.exists())

    def test_chat_needs_indexed_files(self):
        folder = self.root / 'Bos'
        folder.mkdir()
        (folder / 'a.mkv').write_bytes(b'x')
        self.bridge.library_add_paths([str(folder)])
        self.wait_scan()
        chat = self.bridge.chat_state()
        self.assertFalse(chat['enabled'])
        self.assertEqual(chat['entries'][0]['kind'], 'note')
        self.assertEqual(self.bridge.chat_ask('Soru?')['entries'], chat['entries'])


if __name__ == '__main__':
    unittest.main()
