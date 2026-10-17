"""Sesli okuma onayarlari (F137): voice_presets ve bridge_tts.tts_preset_* metotlari."""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))


import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bridge
import voice_presets

VOICES = {
    'ema-lightning/default': {'id': 'default', 'name': 'EMA', 'language': 'tr', 'options': []},
    'voxcpm/design': {'id': 'design', 'name': 'Tarif', 'language': 'tr',
                      'options': [{'key': 'description', 'label': 'Ses tarifi', 'type': 'text'}]},
    'voxcpm/clone': {'id': 'clone', 'name': 'Klon', 'language': 'tr',
                     'options': [{'key': 'reference', 'label': 'Ses kaydı', 'type': 'file'},
                                 {'key': 'reference_text', 'label': 'Kaydın metni', 'type': 'text'}]},
}


def png_data_url(size=(40, 20)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', size, (200, 30, 30)).save(buffer, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


class VoicePresetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Path(self.temp.name) / 'app'
        self.recording = Path(self.temp.name) / 'kayit.wav'
        self.recording.write_bytes(b'RIFF....WAVE')

    def test_save_list_edit_and_remove(self):
        saved = voice_presets.save(self.app, {'name': '  Sakin   anlatıcı ', 'voice': 'voxcpm/design',
                                              'options': {'description': 'A calm narrator', 'stray': 'x'},
                                              'image': png_data_url()}, VOICES)
        self.assertEqual(saved['name'], 'Sakin anlatıcı')
        self.assertEqual(saved['options'], {'description': 'A calm narrator'})   # bilinmeyen secenek atilir
        self.assertTrue(saved['image'].startswith('data:image/png;base64,'))
        from PIL import Image
        with Image.open(voice_presets.folder(self.app) / f'{saved["id"]}.png') as image:
            self.assertEqual(image.size, (voice_presets.IMAGE_SIZE, voice_presets.IMAGE_SIZE))   # kare kirpildi
        edited = voice_presets.save(self.app, {'id': saved['id'], 'name': 'Ece', 'voice': 'ema-lightning/default'}, VOICES)
        self.assertEqual((edited['name'], edited['options']), ('Ece', {}))
        self.assertTrue(edited['image'])                     # resim verilmezse korunur
        voice_presets.save(self.app, {'id': saved['id'], 'name': 'Ece', 'voice': 'ema-lightning/default', 'image': ''}, VOICES)
        self.assertEqual(voice_presets.list_presets(self.app)[0]['image'], '')
        voice_presets.remove(self.app, saved['id'])
        self.assertEqual(voice_presets.list_presets(self.app), [])
        with self.assertRaises(ValueError):
            voice_presets.remove(self.app, saved['id'])

    def test_validation(self):
        for values, part in (({'name': '', 'voice': 'voxcpm/design'}, 'ad'),
                             ({'name': 'X', 'voice': 'yok/ses'}, 'bulunamadı'),
                             ({'name': 'X', 'voice': 'voxcpm/clone'}, 'Ses kaydı'),
                             ({'name': 'X', 'voice': 'voxcpm/clone', 'options': {'reference': 'C:/yok.wav'}}, 'bulunamadı'),
                             ({'name': 'X', 'voice': 'voxcpm/design', 'image': 'data:image/png;base64,AAAA'}, 'Görsel'),
                             ({'id': 'abcdefabcdef', 'name': 'X', 'voice': 'voxcpm/design'}, 'bulunamadı')):
            with self.assertRaises(ValueError) as caught:
                voice_presets.save(self.app, values, VOICES)
            self.assertIn(part, str(caught.exception))

    def test_clone_recording_is_copied_and_cleaned_up(self):
        saved = voice_presets.save(self.app, {'name': 'Klon', 'voice': 'voxcpm/clone',
                                              'options': {'reference': str(self.recording), 'reference_text': 'Merhaba.'}}, VOICES)
        copy = Path(saved['options']['reference'])
        self.assertEqual(copy.parent, voice_presets.folder(self.app))
        self.assertEqual(copy.read_bytes(), self.recording.read_bytes())
        self.recording.unlink()                             # kullanicinin dosyasi silinse de onayar calisir
        again = voice_presets.save(self.app, dict(saved, image=None), VOICES)
        self.assertEqual(again['options']['reference'], str(copy))
        voice_presets.save(self.app, {'id': saved['id'], 'name': 'Klon', 'voice': 'ema-lightning/default'}, VOICES)
        self.assertFalse(copy.exists())                     # ses degisince kopya kayit silinir


class BridgePresetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for target in ('bridge.APP_DIR', 'bridge_tts.APP_DIR'):
            patcher = mock.patch(target, self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.bridge = bridge.Bridge(emit=lambda *_: None)
        patcher = mock.patch.object(self.bridge, '_voice_specs', return_value=VOICES)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_apply_updates_tts_prefs_and_delete_clears_it(self):
        self.bridge.save_ui_prefs({'tts': {'speed': 1.25, 'voices': {'tr': 'ema-lightning/default'}}})
        result = self.bridge.tts_preset_save({'name': 'Tarif', 'voice': 'voxcpm/design', 'options': {'description': 'Warm'}})
        ident = result['saved']['id']
        self.assertEqual([p['name'] for p in result['presets']], ['Tarif'])
        tts = self.bridge.tts_preset_apply(ident)['tts']
        stored = json.loads((self.root / 'ui.json').read_text(encoding='utf-8'))['tts']
        self.assertEqual(stored, tts)
        self.assertEqual((tts['voices']['tr'], tts['options']['voxcpm/design'], tts['active_preset'], tts['speed']),
                         ('voxcpm/design', {'description': 'Warm'}, ident, 1.25))
        self.assertEqual(self.bridge.tts_presets()['active'], ident)
        # Secili ses duzenlenince tercihler de guncellenir.
        self.bridge.tts_preset_save({'id': ident, 'name': 'Tarif', 'voice': 'voxcpm/design', 'options': {'description': 'Calm'}})
        self.assertEqual(self.bridge.ui_prefs()['tts']['options']['voxcpm/design'], {'description': 'Calm'})
        self.assertEqual(self.bridge.tts_preset_apply('')['tts']['active_preset'], '')
        self.bridge.tts_preset_apply(ident)
        self.assertEqual(self.bridge.tts_preset_delete(ident)['active'], '')
        self.assertIn('error', self.bridge.tts_preset_apply(ident))

    def test_preset_of_missing_engine_cannot_be_applied(self):
        ident = self.bridge.tts_preset_save({'name': 'EMA', 'voice': 'ema-lightning/default'})['saved']['id']
        with mock.patch.object(self.bridge, '_voice_specs', return_value={}):
            self.assertIn('kurulu değil', self.bridge.tts_preset_apply(ident)['error'])


if __name__ == '__main__':
    unittest.main()
