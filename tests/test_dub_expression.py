"""F172: dublajda ifadeyi aktarma (dub_expression.py): ses notlari, ses olaylari -> Drama 3 etiketleri,
duraklamada satir bolme; tts.Engines'e cagiranin verdigi etiket; dub.build etiketi motora iletir."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import base64
import io
import shutil
import subprocess
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import dub
import dub_expression as de
import media
import voice_split
from tts import Engines
from test_drama3 import REPO, FakeServer

try:
    FFMPEG = media.ffmpeg_path()
except RuntimeError:
    FFMPEG = None

try:
    import sherpa_onnx  # noqa: F401
    SHERPA = all(voice_split.model_path(name).exists() for name in ('tagging', 'vad'))
except ImportError:
    SHERPA = False

ALL = ('[laughs]', '[sighs]', '[fısıldar]', '[shouting]', '[angry]', '[crying]', '[breathy]', '[clear throat]')


def analysis(seconds=20, speech=(), **peaks):
    """Sahte ifade cozumlemesi: peaks={'laugh': [(zaman, olasilik)]}; pencere ortasi zaman + 1 sn."""
    count = int(seconds / 0.5)
    sounds = {kind: [0.0] * count for kind in voice_split.SOUNDS}
    for kind, items in peaks.items():
        for at, value in items:
            sounds[kind][int((at - 1.0) / 0.5)] = value
    return {'hop': 0.5, 'window': 2.0, 'sounds': sounds, 'speech': [list(item) for item in speech]}


class NoteTests(unittest.TestCase):
    def test_notes_are_removed_and_give_the_expression(self):
        self.assertEqual(de.clean('(laughs) Gerçekten mi?'), ('Gerçekten mi?', 'laugh'))
        self.assertEqual(de.clean('[GÜLER] Tamam.'), ('Tamam.', 'laugh'))
        self.assertEqual(de.clean('*iç çeker* Peki.'), ('Peki.', 'sigh'))
        self.assertEqual(de.clean('[Fısıldayarak] Sus!'), ('Sus!', 'whisper'))
        self.assertEqual(de.clean('(sobbing) Neden?'), ('Neden?', 'cry'))

    def test_sdh_labels_and_music_are_not_read(self):
        self.assertEqual(de.clean('[MUSIC] ♪ La la ♪'), ('La la', ''))
        self.assertEqual(de.clean('(JOHN) - Gel.'), ('Gel.', ''))

    def test_ordinary_parentheses_stay(self):
        self.assertEqual(de.clean('Ona (yani kardeşine) söyle.'), ('Ona (yani kardeşine) söyle.', ''))
        long = 'Bu (çok uzun bir açıklama cümlesi burada duruyor) kalır.'
        self.assertEqual(de.clean(long)[0], long)

    def test_tag_follows_the_choice(self):
        self.assertEqual(de.tag_of('laugh'), '[laughs]')
        self.assertEqual(de.tag_of('laugh', ['[small laugh]']), '[small laugh]')
        self.assertEqual(de.tag_of('cry'), '')               # varsayilan secimde aglama yok (calismiyor)
        self.assertEqual(de.tag_of('whisper', ['[whisper]']), '[whisper]')


class SoundTests(unittest.TestCase):
    def test_sound_inside_or_just_before_the_line(self):
        data = analysis(laugh=[(4.6, 0.5)])
        self.assertEqual(de.sound_at(data, 5.0, 7.0), 'laugh')     # konusmadan hemen once gulmus
        self.assertEqual(de.sound_at(data, 8.0, 10.0), '')
        self.assertEqual(de.sound_at(data, 2.0, 3.0), '')
        self.assertEqual(de.sound_at(data, 5.0, 7.0, after=4.9), '')   # onceki satirin gulmesi bu satira tasmaz

    def test_thresholds_and_choice(self):
        self.assertEqual(de.sound_at(analysis(sigh=[(5.0, 0.4)]), 4.0, 6.0), '')        # ic cekme esigi 0.5
        self.assertEqual(de.sound_at(analysis(sigh=[(5.0, 0.6)]), 4.0, 6.0), 'sigh')
        self.assertEqual(de.sound_at(analysis(cry=[(5.0, 0.9)]), 4.0, 6.0), '')         # etiketi secili degil
        self.assertEqual(de.sound_at(analysis(cry=[(5.0, 0.9)]), 4.0, 6.0, ALL), 'cry')

    def test_strongest_relative_to_threshold_wins(self):
        data = analysis(laugh=[(5.0, 0.35)], shout=[(5.5, 0.7)])
        self.assertEqual(de.sound_at(data, 4.0, 6.0), 'shout')


class PauseTests(unittest.TestCase):
    def test_pause_inside_the_line(self):
        found = de.pauses([[1.0, 2.0], [3.0, 5.0]], 0.8, 5.2)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][:2], (2.0, 3.0))
        self.assertAlmostEqual(found[0][2], 1 / 3)
        self.assertEqual(de.pauses([[1.0, 2.0], [2.3, 5.0]], 0.8, 5.2), [])      # kisa sessizlik
        self.assertEqual(de.pauses([[1.0, 1.1], [2.5, 5.0]], 0.8, 5.2), [])      # oncesinde konusma yok denecek kadar

    def test_split_at_the_nearest_punctuation(self):
        self.assertEqual(de.split_at('Bilmiyorum... belki yarın gelirim.', 0.35), ('Bilmiyorum...', 'belki yarın gelirim.'))
        self.assertEqual(de.split_at('Evet, hayır, belki de olur bir gün.', 0.4), ('Evet, hayır,', 'belki de olur bir gün.'))
        self.assertIsNone(de.split_at('Noktalamasız uzun bir cümle burada', 0.5))
        self.assertIsNone(de.split_at('Evet, bu çok uzun bir cümlenin devamı olarak duruyor.', 0.8))


class ApplyTests(unittest.TestCase):
    def test_line_is_split_at_the_pause_and_parts_are_tagged(self):
        lines = [{'start': 1.0, 'end': 6.0, 'text': 'Bilmiyorum... belki yarın gelirim.'}]
        data = analysis(speech=[[1.0, 2.2], [3.4, 6.0]], laugh=[(4.5, 0.6)])
        result, stats = de.apply(lines, data, tags=True)
        self.assertEqual([(item['start'], item['end'], item['text']) for item in result],
                         [(1.0, 2.2, 'Bilmiyorum...'), (3.4, 6.0, 'belki yarın gelirim.')])
        self.assertNotIn('tag', result[0])
        self.assertEqual(result[1]['tag'], '[laughs]')
        self.assertEqual(stats, {'tagged': 1, 'paused': 1})

    def test_note_only_line_moves_to_the_next_line(self):
        lines = [{'start': 1.0, 'end': 2.0, 'text': '[Kahkahalar]'}, {'start': 2.5, 'end': 4.0, 'text': 'Çok komik.'},
                 {'start': 9.0, 'end': 9.5, 'text': '(sighs)'}, {'start': 14.0, 'end': 15.0, 'text': 'Sonra.'}]
        result, stats = de.apply(lines, None, tags=True)
        self.assertEqual([(item['text'], item.get('tag')) for item in result],
                         [('Çok komik.', '[laughs]'), ('Sonra.', None)])   # uzaktaki satira gecmez
        self.assertEqual(stats, {'tagged': 1, 'paused': 0})

    def test_without_tags_notes_are_still_removed(self):
        result, stats = de.apply([{'start': 0, 'end': 1, 'text': '(laughs) Evet.'}], analysis(laugh=[(1.0, 0.9)]),
                                 tags=False)
        self.assertEqual(result, [{'start': 0, 'end': 1, 'text': 'Evet.'}])
        self.assertEqual(stats['tagged'], 0)

    def test_dub_prepare(self):
        segments = [{'start': 0.0, 'end': 1.0, 'text': '[MUSIC]'}, {'start': 1.0, 'end': 2.0, 'text': '(laughs) Selam.'}]
        lines, stats = dub.prepare(segments)
        self.assertEqual([line['text'] for line in lines], ['Selam.'])
        self.assertNotIn('tag', lines[0])
        lines, stats = dub.prepare(segments, expression={'analysis': analysis(), 'tags': True})
        self.assertEqual(lines[0]['tag'], '[laughs]')
        self.assertTrue(dub.options_of({'expression': 1})['expression'])
        self.assertFalse(dub.options_of({})['expression'])


class EngineTagTests(unittest.TestCase):
    """Cagiranin verdigi etiket (dublaj) herhangi bir Drama 3 sesine gider ve onbellek anahtarina katilir."""

    def setUp(self):
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prefs = {'drama3_url': self.server.url, 'voices': {'tr': 'drama3/clone'},
                      'options': {'drama3/clone': {'reference': 'C:/ses/kayit.wav', 'reference_text': 'Merhaba.'}}}
        self.engines = Engines(Path(self.temp.name), REPO / 'engines', prefs=lambda: self.prefs,
                               emotion=lambda book, text: '[angry]')
        self.addCleanup(self.engines.shutdown)

    def test_given_tag(self):
        book, override = 'abcdef0123456789', {'voice': 'drama3/clone'}
        self.assertEqual(self.engines._tag_for(book, 'Selam.', 'tr', override, '[laughs]'), '[laughs]')
        self.assertEqual(self.engines._tag_for(book, 'Selam.', 'tr', None, ''), '')      # kitap etiketine bakilmaz
        self.assertEqual(self.engines._tag_for(book, 'Selam.', 'tr', None, None), '[angry]')
        self.assertNotEqual(self.engines._cache_path(book, 'Selam.', 1.0, 'tr', override, '[laughs]'),
                            self.engines._cache_path(book, 'Selam.', 1.0, 'tr', override, ''))
        with patch.object(self.engines, '_manifests', return_value={'drama3': {}}):
            self.assertEqual(self.engines._tag_for(book, 'Selam.', 'tr', override, '[laughs]'), '')
        prepared = {'text': 'Merhaba.', 'data': 'QUJD', 'seconds': 4.0}
        with patch('drama3.prepare_reference', return_value=prepared):
            self.engines.load('tr')
            end = time.time() + 20
            while self.engines.state == 'loading' and time.time() < end:
                time.sleep(0.05)
        self.assertEqual(self.engines.state, 'ready', self.engines.message)
        self.engines.say('Selam.', 1.0, book, 'tr', None, tag='[laughs]')
        self.assertEqual(self.server.requests[-1][1]['input'], '[laughs] Selam.')


def tone(seconds, rate=16000):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b'\x10\x00' * int(seconds * rate))
    return buffer.getvalue()


class TagEngines:
    def __init__(self):
        self.calls = []

    def say(self, text, speed=1.0, book=None, language='tr', override=None, **extra):
        self.calls.append((text, extra.get('tag')))
        return {'audio': base64.b64encode(tone(0.3)).decode('ascii'), 'duration': 0.3}


@unittest.skipUnless(FFMPEG, 'FFmpeg yok')
class DubBuildTests(unittest.TestCase):
    def test_tags_and_split_lines_reach_the_engine(self):
        folder = Path(tempfile.mkdtemp(prefix='aktar-test-de-'))
        self.addCleanup(shutil.rmtree, folder, True)
        video = folder / 'film.mkv'
        with patch.object(media, 'ffmpeg_path', return_value=FFMPEG):
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=8',
                            '-c:a', 'aac', str(video)], check=True)
            segments = [{'start': 0.5, 'end': 6.0, 'text': 'Bilmiyorum... belki yarın gelirim.'},
                        {'start': 6.5, 'end': 7.5, 'text': '(laughs) Tamam.'}]
            engines = TagEngines()
            data = analysis(seconds=8, speech=[[0.5, 1.7], [3.0, 6.0], [6.5, 7.5]], laugh=[(3.5, 0.8)])
            result = dub.build(engines, video, segments, folder / 'o.m4a', {'format': 'm4a', 'expression': True},
                               expression={'analysis': data, 'tags': True})
        self.assertEqual(engines.calls, [('Bilmiyorum...', None), ('belki yarın gelirim.', '[laughs]'),
                                         ('Tamam.', '[laughs]')])
        self.assertEqual((result['lines'], result['tagged'], result['paused']), (3, 2, 1))


@unittest.skipUnless(SHERPA and FFMPEG, 'sherpa-onnx ya da ifade modelleri yok')
class SherpaExpressionTests(unittest.TestCase):
    def test_run_expression_on_a_short_sound(self):
        folder = Path(tempfile.mkdtemp(prefix='aktar-test-de-'))
        self.addCleanup(shutil.rmtree, folder, True)
        source = folder / 'in.wav'
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
                        '-ac', '1', '-ar', '16000', str(source)], check=True)
        labels = voice_split.model_dir() / voice_split.TAGGING_LABELS
        data = voice_split.run_expression(source, voice_split.model_path('tagging'), labels,
                                          voice_split.model_path('vad'), threads=2)
        self.assertEqual(set(data['sounds']), set(voice_split.SOUNDS))
        self.assertEqual(len(data['sounds']['laugh']), 5)
        self.assertTrue(all(0 <= value <= 1 for values in data['sounds'].values() for value in values))


if __name__ == '__main__':
    unittest.main()
