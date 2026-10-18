"""Ilk acilis bilesen denetimi (F154)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import app_core
import setup_check


class SetupCheckTests(unittest.TestCase):
    def run_check(self, models=('m',), error=None, ffmpeg=True, embedding='', engines=()):
        cfg = dict(app_core.DEFAULT_CONFIG, model='m', embedding_model=embedding)

        def listing(_self):
            if error:
                raise RuntimeError(error)
            return list(models)

        with mock.patch.object(setup_check, 'load_config', return_value=cfg), \
                mock.patch.object(app_core.Client, 'models', listing), \
                mock.patch.object(setup_check.media, 'ffmpeg_path', return_value='ffmpeg' if ffmpeg else None), \
                mock.patch.object(setup_check.media, 'ffprobe_path', return_value='ffprobe' if ffmpeg else None), \
                mock.patch.object(setup_check.speech, 'available', return_value=(False, 'pip install ...')), \
                mock.patch.object(setup_check.documents, 'tesseract_path', return_value=None), \
                mock.patch.object(setup_check.ebook_convert, 'calibre_converter', return_value=None):
            return {item['id']: item for item in setup_check.run(engines, mpv_available=True)}

    def test_all_good_required(self):
        items = self.run_check(embedding='m', engines=[{'name': 'EMA', 'mode': 'package'}])
        self.assertEqual(items['model_server']['state'], 'ok')
        self.assertEqual(items['ffmpeg']['state'], 'ok')
        self.assertEqual(items['embedding']['state'], 'ok')
        self.assertEqual(items['tts']['state'], 'ok')
        self.assertEqual(items['mpv']['state'], 'ok')
        self.assertEqual(items['whisper']['state'], 'missing')
        self.assertEqual(items['whisper']['hint'], 'pip install ...')
        self.assertTrue(items['model_server']['required'])
        self.assertFalse(items['calibre']['required'])

    def test_missing_and_mismatched(self):
        items = self.run_check(error='Model sunucusuna baglanilamadi', ffmpeg=False)
        self.assertEqual(items['model_server']['state'], 'missing')
        self.assertEqual(items['model_server']['settings'], 'models')
        self.assertEqual(items['ffmpeg']['state'], 'missing')
        self.assertEqual(items['tts']['state'], 'missing')
        items = self.run_check(models=('other',), embedding='embed')
        self.assertEqual(items['model_server']['state'], 'warn')
        self.assertEqual(items['embedding']['state'], 'warn')


if __name__ == '__main__':
    unittest.main()
