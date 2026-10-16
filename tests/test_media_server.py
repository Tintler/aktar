"""Oynatici video sunucusu (media_server) testleri; ffmpeg gerektirmez."""
from __future__ import annotations

import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bridge  # noqa: E402
import bridge_document  # noqa: E402
import bridge_library  # noqa: E402
import bridge_player  # noqa: E402
import bridge_translate  # noqa: E402
import media_server  # noqa: E402


def info(video='h264', audio=('aac',), profile='High', level=31, pix_fmt='yuv420p'):
    return {'duration': 100.0, 'chapters': [],
            'video': {'index': 0, 'codec': video, 'height': 720, 'profile': profile, 'level': level, 'pix_fmt': pix_fmt}
            if video else None,
            'audio': [{'index': index + 1, 'codec': codec} for index, codec in enumerate(audio)]}


class PlanTests(unittest.TestCase):
    def test_browser_friendly_mp4_plays_directly(self):
        self.assertEqual(media_server.plan('a.mp4', info())['mode'], 'direct')
        self.assertEqual(media_server.plan('a.webm', info('vp9', ('opus',)))['mode'], 'direct')

    def test_mkv_or_other_codecs_are_streamed(self):
        self.assertEqual(media_server.plan('a.mkv', info()), {'mode': 'stream', 'video': 'copy', 'audio': 1})
        self.assertEqual(media_server.plan('a.mp4', info(audio=('ac3',)))['mode'], 'stream')
        self.assertEqual(media_server.plan('a.avi', info('mpeg4'))['video'], 'x264')
        self.assertEqual(media_server.plan('a.mkv', info('hevc'))['video'], 'x264')

    def test_hevc_is_copied_when_webview_can_decode_it(self):
        self.assertEqual(media_server.plan('a.mp4', info('hevc'), extra=['hevc'])['mode'], 'direct')
        self.assertEqual(media_server.plan('a.mkv', info('hevc'), extra=['hevc'])['video'], 'copy')
        ten = info('hevc', pix_fmt='yuv420p10le', level=120)
        self.assertEqual(media_server.plan('a.mp4', ten, extra=['hevc'])['video'], 'x264')
        self.assertEqual(media_server.plan('a.mp4', ten, extra=['hevc10'])['mode'], 'direct')
        chosen = media_server.plan('a.mkv', ten, extra=['hevc10'])
        self.assertIn('hvc1.2.4.L120.B0', media_server.stream_mime(ten, chosen))
        self.assertEqual(media_server.plan('a.mkv', ten, extra=['hevc10'], transcode=True)['video'], 'x264')

    def test_second_audio_track_forces_stream_and_transcode_flag(self):
        value = media_server.plan('a.mp4', info(audio=('aac', 'aac')), audio_index=2)
        self.assertEqual((value['mode'], value['audio']), ('stream', 2))
        self.assertEqual(media_server.plan('a.mkv', info(), transcode=True)['video'], 'x264')

    def test_audio_only_and_unknown_track(self):
        self.assertEqual(media_server.plan('a.mkv', info(video=None))['video'], None)
        self.assertEqual(media_server.plan('a.mkv', info(audio=()))['audio'], None)

    def test_mime_strings_for_media_source(self):
        self.assertEqual(media_server.stream_mime(info(), media_server.plan('a.mkv', info())),
                         'video/mp4; codecs="avc1.64001F, mp4a.40.2"')
        exotic = info(profile='High 4:4:4 Predictive', level=12)
        self.assertIn('avc1.640028', media_server.stream_mime(exotic, media_server.plan('a.mkv', exotic)))
        self.assertIn('avc1.640028', media_server.stream_mime(info('mpeg4'), media_server.plan('a.avi', info('mpeg4'))))

    @mock.patch.object(media_server.media, 'ffmpeg_path', return_value='ffmpeg')
    def test_stream_command_maps_tracks_and_seeks(self, _ffmpeg):
        command = media_server.stream_command('a.mkv', 12.5, 0, 'copy', 3)
        joined = ' '.join(command)
        self.assertIn('-ss 12.500 -i a.mkv', joined)
        self.assertIn('-map 0:0 -map 0:3', joined)
        self.assertIn('-c:v copy', joined)
        self.assertIn('-c:a aac', joined)
        self.assertTrue(command[-1] == 'pipe:1')
        scaled = ' '.join(media_server.stream_command('a.mkv', 0, 0, 'x264', 1, height=2160))
        self.assertIn('libx264', scaled)
        self.assertIn('scale=-2:1080', scaled)
        self.assertNotIn('-ss', scaled)
        self.assertIn('-tag:v hvc1', ' '.join(media_server.stream_command('a.mkv', 0, 0, 'copy', 1, codec='hevc')))
        self.assertNotIn('-tag:v', joined)
        self.assertIn('-frag_duration 1000000', joined)   # veri kucuk parcalarla akar
        self.assertIn('-g 60', scaled)

    @mock.patch.object(media_server.media, 'ffmpeg_path', return_value='ffmpeg')
    def test_gpu_encoder_in_stream_command(self, _ffmpeg):
        gpu = ' '.join(media_server.stream_command('a.mkv', 5, 0, 'x264', 1, encoder='nvenc'))
        self.assertTrue(gpu.startswith('ffmpeg -hide_banner -loglevel error -nostdin -hwaccel auto -ss 5.000 -i a.mkv'))
        self.assertIn('-c:v h264_nvenc', gpu)
        self.assertNotIn('libx264', gpu)
        # Kopyalanan goruntude ve bilinmeyen kodlayicida GPU kullanilmaz.
        self.assertNotIn('-hwaccel', ' '.join(media_server.stream_command('a.mkv', 0, 0, 'copy', 1, encoder='nvenc')))
        self.assertIn('libx264', ' '.join(media_server.stream_command('a.mkv', 0, 0, 'x264', 1, encoder='bogus')))

    def test_hw_encoder_choice(self):
        works = {'nvenc': False, 'qsv': True, 'amf': True, 'mf': True}
        with mock.patch.object(media_server, 'hw_works', side_effect=lambda name: works.get(name, False)):
            self.assertEqual(media_server.hw_encoder('auto'), 'qsv')
            self.assertIsNone(media_server.hw_encoder('off'))
            self.assertIsNone(media_server.hw_encoder('nvenc'))
            self.assertEqual(media_server.hw_encoder('amf'), 'amf')
        self.assertEqual(media_server.encoder_label(None), 'işlemci (x264)')

    def test_stream_url_carries_encoder(self):
        server = media_server.MediaServer()
        server.start()
        try:
            plan_value = dict(media_server.plan('a.mkv', info('hevc')), encoder='qsv')
            self.assertIn('&e=qsv', server.stream_url(Path('a.mkv'), 0, plan_value, info('hevc')))
        finally:
            server.shutdown()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.file = Path(self.temp.name) / 'a.mp4'
        self.file.write_bytes(bytes(range(256)) * 4)
        self.server = media_server.MediaServer().start()

    def tearDown(self):
        self.server.shutdown()
        self.temp.cleanup()

    def test_range_requests_and_unknown_tokens(self):
        url = self.server.file_url(self.file)
        self.assertEqual(url, self.server.file_url(self.file))  # ayni dosya ayni anahtar
        request = urllib.request.Request(url, headers={'Range': 'bytes=10-19'})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers['Content-Range'], 'bytes 10-19/1024')
            self.assertEqual(response.headers['Access-Control-Allow-Origin'], '*')
            self.assertEqual(response.read(), bytes(range(10, 20)))
        with urllib.request.urlopen(url) as response:
            self.assertEqual(len(response.read()), 1024)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.server.start().base + '/f/unknown')
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(urllib.request.Request(url, headers={'Range': 'bytes=5000-'}))
        self.assertEqual(caught.exception.code, 416)
        caught.exception.close()


class MixinTests(unittest.TestCase):
    def test_mixins_do_not_share_state_names(self):
        # Ayni ozel alan adi iki bolumde kullanilirsa birbirinin durumunu ezer (ornek: _video).
        names = {}
        for module, init in ((bridge_translate.TranslateMixin, '_init_translate'),
                             (bridge_library.LibraryMixin, '_init_library'),
                             (bridge_player.PlayerMixin, '_init_player'),
                             (bridge_document.DocumentMixin, '_init_document')):
            fake = type('Fake', (), {})()
            getattr(module, init)(fake)
            names[init] = set(vars(fake))
        sets = list(names.values())
        for index, first in enumerate(sets):
            for second in sets[index + 1:]:
                self.assertFalse(first & second, first & second)
        self.assertTrue(issubclass(bridge.Bridge, bridge_player.PlayerMixin))


if __name__ == '__main__':
    unittest.main()
