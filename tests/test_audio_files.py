"""Ses dosyalari (F181): oynatici, altyazi cevirisi, kutuphane ve dublaj videoyla ayni yoldan acar.
FFmpeg gerektirmez (probe mock'lanir)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import bridge_player  # noqa: E402
import clip  # noqa: E402
import dub  # noqa: E402
import library  # noqa: E402
import media  # noqa: E402
import media_server  # noqa: E402


def audio_info(codec='mp3'):
    return {'duration': 30.0, 'chapters': [], 'video': None, 'audio': [{'index': 0, 'codec': codec}]}


class FakePlayer(bridge_player.PlayerMixin):
    def __init__(self):
        self._init_player()
        self.events = []

    def _emit(self, name, value):
        self.events.append(name)

    def _log(self, _message):
        pass

    def _engine(self):
        return 'mpv'

    def _start_prepare(self, video, **_kwargs):
        pass


class AudioFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_audio_extensions_are_media_but_not_video(self):
        self.assertTrue(media.is_audio('Bölüm 1.MP3'))
        self.assertFalse(media.is_audio('film.mkv'))
        self.assertIn('.flac', media.MEDIA_EXTENSIONS)
        self.assertNotIn('.mp3', media.VIDEO_EXTENSIONS)
        self.assertEqual(library.kind_of('ders.m4a'), 'video')   # transkript yolu videoyla ortak

    def test_dub_of_audio_is_always_m4a(self):
        self.assertEqual(dub.options_for('a.wav', {'format': 'mkv'})['format'], 'm4a')
        self.assertEqual(dub.options_for('a.mkv', {'format': 'mkv'})['format'], 'mkv')

    def test_browser_plays_common_audio_directly_and_streams_the_rest(self):
        self.assertEqual(media_server.plan('a.mp3', audio_info())['mode'], 'direct')
        self.assertEqual(media_server.plan('a.m4a', audio_info('aac'))['mode'], 'direct')
        wav = media_server.plan('a.wav', audio_info('pcm_s16le'))
        self.assertEqual((wav['mode'], wav['video'], wav['audio']), ('stream', None, 0))
        self.assertEqual(media_server.stream_mime(audio_info('pcm_s16le'), wav), 'video/mp4; codecs="mp4a.40.2"')

    def test_player_uses_html_player_for_audio(self):
        player = FakePlayer()
        self.addCleanup(player._media.shutdown)
        path = self.root / 'kayit.mp3'
        path.write_bytes(b'x')
        with mock.patch('media_server.probe', return_value=audio_info()), \
                mock.patch('speech.load_cached', return_value=None), \
                mock.patch('library.load_chat', return_value={'entries': [], 'history': []}), \
                mock.patch('bridge_player.load_config', return_value={'whisper_model': 's', 'whisper_language': ''}):
            state = player.player_open(str(path))
        self.assertEqual((state['engine'], state['audio_only']), ('web', True))

    def test_clip_of_audio_moves_subtitles_beside_the_file(self):
        options = clip.options_of(dict(clip.options_of({'format': 'mp4', 'subtitles': 'burn'}), format='m4a'))
        self.assertEqual((options['format'], options['subtitles']), ('m4a', 'file'))

    def test_library_plan_skips_frames_for_audio(self):
        song = self.root / 'ders.mp3'
        song.write_bytes(b'x')
        entry = {'path': song, 'kind': 'video', 'root': str(self.root), 'missing': False, 'new': False}
        with mock.patch('media.probe_summary', return_value={'duration': 12.0, 'subtitles': []}):
            result = library.plan([entry], self.root / 'work', cfg={'embedding_model': ''})
        self.assertEqual([item['path'].name for item in result['whisper']], ['ders.mp3'])
        self.assertEqual(result['frames'], [])


if __name__ == '__main__':
    unittest.main()
