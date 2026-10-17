"""F146: ses ayirma ve konusmaci ayrimi (voice_split.py), dublajda konusmaci basina ses ve ayrilmis
seslerle karistirma (dub.py), transkript/soru-cevap etiketleri (qa.py). Saf hesaplar her yerde; gercek
sherpa-onnx modelleri models/sherpa altinda varsa kisa bir sesle de denenir."""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import dub  # noqa: E402
import media  # noqa: E402
import qa  # noqa: E402
import search_index  # noqa: E402
import transcript_export  # noqa: E402
import voice_split  # noqa: E402

try:
    FFMPEG = media.ffmpeg_path()
    FFPROBE = media.ffprobe_path()
except RuntimeError:
    FFMPEG = FFPROBE = None

try:
    import sherpa_onnx  # noqa: F401
    SHERPA = all(voice_split.model_path(name).exists() for name in voice_split.MODELS)
except ImportError:
    SHERPA = False

TURNS = [{'start': 0.0, 'end': 4.0, 'speaker': 0}, {'start': 4.5, 'end': 8.0, 'speaker': 1},
         {'start': 9.0, 'end': 10.0, 'speaker': 0}]


def tone(seconds, rate=16000):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b'\x10\x08' * int(rate * seconds))
    return buffer.getvalue()


class PureTests(unittest.TestCase):
    def test_speaker_of_prefers_overlap_then_nearest(self):
        self.assertEqual(voice_split.speaker_of(3.5, 5.0, TURNS), 0)      # 0,5 sn ortusme 0; 0,5 sn 1 -> ilki
        self.assertEqual(voice_split.speaker_of(5.0, 7.0, TURNS), 1)
        self.assertEqual(voice_split.speaker_of(8.3, 8.6, TURNS), 1)      # ortusme yok, en yakin
        self.assertIsNone(voice_split.speaker_of(20, 21, TURNS))

    def test_renumber_by_first_appearance(self):
        turns, count = voice_split.renumber([{'start': 5, 'end': 6, 'speaker': 3}, {'start': 0, 'end': 1, 'speaker': 7},
                                             {'start': 2, 'end': 3, 'speaker': 3}])
        self.assertEqual(count, 2)
        self.assertEqual([t['speaker'] for t in turns], [0, 1, 1])

    def test_label_uses_names_and_skips_visual(self):
        data = {'turns': TURNS, 'count': 2, 'names': {'1': 'Ayşe'}}
        segments = [{'start': 0.5, 'end': 2, 'text': 'a'}, {'start': 5, 'end': 6, 'text': 'b'},
                    {'start': 5, 'end': 5, 'text': '[Görüntü] x', 'visual': True}]
        labelled = voice_split.label(segments, data)
        self.assertEqual([s.get('speaker') for s in labelled], ['K1', 'Ayşe', None])
        self.assertNotIn('speaker', segments[0])   # kopya
        self.assertIs(voice_split.label(segments, None), segments)

    def test_summary_orders_by_speaking_time(self):
        data = {'turns': TURNS, 'count': 2, 'names': {}}
        lines = [{'start': 1, 'end': 2, 'text': 'Merhaba'}, {'start': 5, 'end': 6, 'text': 'Selam'}]
        result = voice_split.summary(data, lines)
        self.assertEqual([(s['id'], s['name'], s['lines'], s['sample']) for s in result],
                         [(0, 'K1', 1, 'Merhaba'), (1, 'K2', 1, 'Selam')])
        self.assertEqual(result[0]['seconds'], 5.0)

    def test_signature_changes_with_names(self):
        data = {'turns': TURNS, 'count': 2, 'names': {}}
        self.assertNotEqual(voice_split.signature(data), voice_split.signature(dict(data, names={'0': 'Ali'})))
        self.assertEqual(voice_split.signature(None), '')


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='aktar-test-vs-'))
        self.video = self.folder / 'film.mkv'
        self.video.write_bytes(b'x' * 10)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def _store(self):
        path = voice_split.speakers_path(self.video, self.folder)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'turns': TURNS, 'count': 2, 'names': {}}), encoding='utf-8')

    def test_save_names_cleans_values(self):
        self._store()
        data = voice_split.save_names(self.video, {'0': '  Ali   Veli ', '1': '', '5': 'Yok', 'x': 'Y'}, self.folder)
        self.assertEqual(data['names'], {'0': 'Ali Veli'})
        self.assertEqual(voice_split.load_speakers(self.video, self.folder)['names'], {'0': 'Ali Veli'})

    def test_save_names_without_diarization_fails(self):
        with self.assertRaises(ValueError):
            voice_split.save_names(self.video, {'0': 'A'}, self.folder)

    def test_diarize_uses_cache_and_fresh_reruns(self):
        self._store()
        with mock.patch.object(voice_split, '_run') as run:
            self.assertEqual(voice_split.diarize(self.video, base=self.folder, log=lambda _m: None)['count'], 2)
            run.assert_not_called()
        voice_split.save_names(self.video, {'1': 'Ayşe'}, self.folder)
        with mock.patch.object(voice_split, 'ensure_models'), mock.patch.object(voice_split, '_extract'), \
                mock.patch.object(voice_split, '_run', return_value=[{'start': 0, 'end': 1, 'speaker': 4},
                                                                      {'start': 2, 'end': 3, 'speaker': 9}]):
            data = voice_split.diarize(self.video, base=self.folder, log=lambda _m: None, fresh=True)
        self.assertEqual([t['speaker'] for t in data['turns']], [0, 1])
        self.assertEqual(data['names'], {'1': 'Ayşe'})   # konusmaci sayisi ayni: adlar korunur

    def test_sessions_get_speakers_and_labelled_lines(self):
        self._store()
        session = qa.build_data(self.video, [{'start': 0.5, 'end': 1.5, 'text': 'Merhaba.'},
                                              {'start': 1.6, 'end': 2.5, 'text': 'Nasılsın?'},
                                              {'start': 5.0, 'end': 6.0, 'text': 'İyiyim.'}],
                                {'kind': 'subtitle', 'stream': 2, 'language': 'tr', 'title': ''},
                                {'duration': 10.0, 'chapters': []})
        path = qa.cache_path(self.video, qa.source_key(session['source']), self.folder)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(session), encoding='utf-8')
        loaded = qa.cached_sessions(self.video, self.folder)[0]
        self.assertEqual(loaded['speakers']['count'], 2)
        self.assertEqual([line['text'] for line in qa.lines_of(loaded)], ['K1: Merhaba. Nasılsın?', 'K2: İyiyim.'])
        self.assertIn('K2: İyiyim.', transcript_export.render(loaded, 'srt'))
        cfg = {'embedding_model': 'm', 'embedding_document_template': '{text}'}
        plain = dict(loaded)
        plain.pop('speakers')
        self.assertNotEqual(search_index.index_path(self.video, loaded, cfg, self.folder),
                            search_index.index_path(self.video, plain, cfg, self.folder))


class DubVoicesTests(unittest.TestCase):
    def test_voice_plan_maps_speakers(self):
        lines = [{'start': 1, 'end': 2, 'text': 'a'}, {'start': 5, 'end': 6, 'text': 'b'}, {'start': 30, 'end': 31, 'text': 'c'}]
        plan = dub.voice_plan(lines, {'turns': TURNS}, {'1': 'preset:kadin'})
        self.assertEqual(plan, [None, 'preset:kadin', None])
        self.assertEqual(dub.voice_plan(lines, None, {'1': 'x'}), [None, None, None])

    def test_mix_with_stems_ducks_only_speech(self):
        command = dub.mix_command('v.mkv', 'd.wav', 'o.mkv', {'audio': 3}, True, 'duck.cmd', ('voc.m4a', 'bg.m4a'))
        graph = command[command.index('-filter_complex') + 1]
        self.assertIn('voc.m4a', command)
        self.assertIn('bg.m4a', command)
        self.assertIn('[2:a]', graph)
        self.assertIn('volume@duck', graph.split('[voice]')[0])
        self.assertIn('amix=inputs=3', graph)
        self.assertNotIn('[0:3]', graph)     # ozgun ses karistirilmaz, yalnizca parca olarak kopyalanir
        self.assertIn('0:a', command)


class Engines:
    """Sahte motor: ses adina gore farkli ornekleme hizi; yuklenen sesleri kaydeder."""

    def __init__(self):
        self.calls = []

    def say(self, text, speed=1.0, book=None, language='tr', override=None):
        voice = (override or {}).get('voice', 'ana')
        self.calls.append((voice, text))
        data = tone(0.3, 22050 if voice == 'ikinci' else 16000)
        return {'audio': base64.b64encode(data).decode('ascii'), 'duration': 0.3}


@unittest.skipUnless(FFMPEG and FFPROBE, 'FFmpeg yok')
class DubEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='aktar-test-vs-'))

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def _audio(self, name, frequency, seconds=4):
        path = self.folder / name
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'sine=frequency={frequency}:duration={seconds}',
                        '-ac', '2', '-c:a', 'aac', str(path)], check=True)
        return path

    def test_grouped_voices_resample_and_stems(self):
        video = self.folder / 'film.mkv'
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=160x90:d=4',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-shortest', '-c:v', 'libx264',
                        '-c:a', 'aac', str(video)], check=True)
        stems = (self._audio('voc.m4a', 300), self._audio('bg.m4a', 900))
        segments = [{'start': 0.2, 'end': 0.8, 'text': 'bir'}, {'start': 1.0, 'end': 1.6, 'text': 'iki'},
                    {'start': 2.0, 'end': 2.6, 'text': 'üç'}]
        engines, loaded = Engines(), []
        specs = {'ikinci': {'override': {'voice': 'ikinci'}, 'language': 'tr', 'can_speed': False}}
        result = dub.build(engines, video, segments, self.folder / 'o.mkv', {'separate': True}, duration=4,
                           plan=[None, 'ikinci', None], voices=specs, stems=stems,
                           load_voice=lambda override, language: loaded.append((override or {}).get('voice')))
        self.assertEqual(result['voices'], 2)
        self.assertEqual(loaded, [None, 'ikinci'])                  # her ses icin bir kez
        self.assertEqual([v for v, _ in engines.calls], ['ana', 'ana', 'ikinci'])
        info = json.loads(subprocess.run([FFPROBE, '-v', 'error', '-show_streams', '-of', 'json', str(self.folder / 'o.mkv')],
                                         capture_output=True, text=True, check=True).stdout)
        audio = [s for s in info['streams'] if s['codec_type'] == 'audio']
        self.assertEqual(len(audio), 2)
        self.assertEqual(audio[0]['disposition']['default'], 1)

    def test_single_speaker_voice_is_loaded_even_without_main_lines(self):
        # Hata: tum satirlar konusmacilara atanip tek grup kalinca motor ana seste kaliyordu ("Ses motoru hazir degil").
        video = self.folder / 'film.mkv'
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
                        '-c:a', 'aac', str(video)], check=True)
        loaded = []
        specs = {'klon': {'override': {'voice': 'klon'}, 'language': 'tr', 'can_speed': False}}
        dub.build(Engines(), video, [{'start': 0.2, 'end': 0.8, 'text': 'bir'}], self.folder / 'o.m4a', {'format': 'm4a'},
                  plan=['klon'], voices=specs, load_voice=lambda override, language: loaded.append(override['voice']))
        self.assertEqual(loaded, ['klon'])


@unittest.skipUnless(SHERPA and FFMPEG, 'sherpa-onnx ya da modelleri yok')
class SherpaTests(unittest.TestCase):
    """Gercek modellerle kisa deneme: iki farkli sesli konusma yerine iki farkli ton."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='aktar-test-vs-'))

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_separate_writes_two_stereo_tracks_in_chunks(self):
        source = self.folder / 'in.wav'
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
                        '-ac', '2', '-ar', '44100', str(source)], check=True)
        vocals, background = self.folder / 'v.wav', self.folder / 'b.wav'
        seen = []
        with mock.patch.object(voice_split, 'CHUNK_SECONDS', 1):
            voice_split.run_separate(source, vocals, background, voice_split.model_path('separation'),
                                     progress=lambda done, total: seen.append((done, total)), threads=2)
        for path in (vocals, background):
            with wave.open(str(path)) as stream:
                self.assertEqual(stream.getnchannels(), 2)
                self.assertAlmostEqual(stream.getnframes() / stream.getframerate(), 3.0, delta=0.05)
        self.assertEqual(seen[-1], (3, 3))


if __name__ == '__main__':
    unittest.main()
