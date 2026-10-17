"""F114: videonun goruntusunu okuma (video_frames) ve betimlerin soru-cevap/aramaya girmesi."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import documents  # noqa: E402
import media  # noqa: E402
import qa  # noqa: E402
import search_index  # noqa: E402
import transcript_export  # noqa: E402
import video_frames  # noqa: E402

SESSION = {'source': {'kind': 'subtitle', 'stream': 1}, 'title': 'Ders', 'segments': [
    {'start': 1.0, 'end': 5.0, 'text': 'Bugün gradyan inişini konuşacağız.'},
    {'start': 6.0, 'end': 9.0, 'text': 'Önce öğrenme oranına bakalım.'},
    {'start': 21.0, 'end': 25.0, 'text': 'Şimdi aşırı öğrenmeye geçelim.'}]}
VISUAL = [{'start': 0.0, 'text': 'Slayt: Gradyan inişi'}, {'start': 20.0, 'text': 'Slayt: Aşırı öğrenme'}]


def ffmpeg_available():
    try:
        media.ffmpeg_path()
        return True
    except RuntimeError:
        return False


class VisualLinesTests(unittest.TestCase):
    def test_visual_lines_stay_separate_from_speech(self):
        lines = qa.lines_of(dict(SESSION, visual=VISUAL))
        self.assertEqual([(line['start'], line['text']) for line in lines], [
            (0.0, '[Görüntü] Slayt: Gradyan inişi'),
            (1.0, 'Bugün gradyan inişini konuşacağız. Önce öğrenme oranına bakalım.'),
            (20.0, '[Görüntü] Slayt: Aşırı öğrenme'),
            (21.0, 'Şimdi aşırı öğrenmeye geçelim.')])
        self.assertEqual(len(qa.lines_of(SESSION)), 2)  # betimsiz video eskisi gibi

    def test_search_chunks_and_export(self):
        chunks = search_index.chunk_session(dict(SESSION, visual=VISUAL))
        self.assertIn('[Görüntü] Slayt: Aşırı öğrenme', ' '.join(chunk['text'] for chunk in chunks))
        text = transcript_export.render(dict(SESSION, visual=VISUAL), 'txt')
        self.assertIn('gradyan inişini', text)
        self.assertNotIn('[Görüntü]', text)  # disa aktarilan transkript yalniz konusma

    def test_index_key_changes_only_when_frames_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / 'ders.mp4'
            video.write_bytes(b'x')
            cfg = {'embedding_model': 'e', 'embedding_document_template': '{text}'}
            plain = search_index.index_path(video, SESSION, cfg, Path(temp))
            self.assertEqual(plain, search_index.index_path(video, dict(SESSION, visual=[]), cfg, Path(temp)))
            self.assertNotEqual(plain, search_index.index_path(video, dict(SESSION, visual=VISUAL), cfg, Path(temp)))


class FrameReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / 'ders.mp4'
        self.video.write_bytes(b'video')

    def frames(self, *colors):
        from PIL import Image, ImageDraw
        result = []
        for number, (seconds, color, text) in enumerate(colors):
            image = Image.new('RGB', (320, 180), color)
            if text:
                ImageDraw.Draw(image).rectangle((40, 40, 200, 120), fill=(255, 255, 255))
            path = self.root / f'{number:05d}.jpg'
            image.save(path)
            result.append((seconds, path))
        return result

    def test_distinct_drops_near_duplicates(self):
        frames = self.frames((0, (20, 40, 90), True), (10, (20, 40, 91), True), (30, (240, 240, 240), False))
        self.assertEqual([seconds for seconds, _png in video_frames.distinct(frames)], [0, 30])

    def test_describe_prefers_ocr_text(self):
        calls = []

        def reader(png, prompt):
            calls.append(prompt)
            return 'Gradyan inişi öğrenme oranı 0,01 adım büyüklüğü ve yakınsama hızı' if prompt == documents.OCR_PROMPT \
                else 'Bir kişi tahtanın önünde konuşuyor.'

        self.assertTrue(video_frames.describe(b'png', reader).startswith('Ekrandaki yazı: Gradyan'))
        self.assertEqual(calls, [documents.OCR_PROMPT])
        short = lambda png, prompt: 'yazı' if prompt == documents.OCR_PROMPT else 'Bir kişi konuşuyor.'
        self.assertEqual(video_frames.describe(b'png', short), 'Bir kişi konuşuyor.')
        self.assertEqual(video_frames.describe(b'png', short, ocr=False), 'Bir kişi konuşuyor.')

    def test_read_video_saves_resumes_and_completes(self):
        frames = self.frames((0, (20, 40, 90), True), (20, (240, 240, 240), False), (40, (90, 20, 20), True))
        prompts = []

        def reader(png, prompt):
            prompts.append(prompt)
            return f'kare {len(prompts)}'

        cfg = {'ocr_engine': 'vision'}
        stop = {'after': 1}
        cancelled = lambda: len(prompts) >= stop['after']
        with mock.patch.object(video_frames, 'extract', return_value=frames):
            video_frames.read_video(self.video, cfg, reader, base=self.root, log=lambda _m: None, cancelled=cancelled)
            saved, complete = qa.load_visual(self.video, self.root)
            self.assertEqual(([item['start'] for item in saved], complete), ([0], False))
            stop['after'] = 99
            count = video_frames.read_video(self.video, cfg, reader, base=self.root, log=lambda _m: None)
        self.assertEqual(count, 3)
        saved, complete = qa.load_visual(self.video, self.root)
        self.assertTrue(complete)
        self.assertEqual([item['start'] for item in saved], [0, 20, 40])
        self.assertEqual(len(prompts), 3)  # ilk kare yeniden okunmadi
        self.assertEqual(set(prompts), {video_frames.FRAME_PROMPT})  # OCR motoru gorsel model: dogrudan betim
        with mock.patch.object(video_frames, 'extract') as extract:
            video_frames.read_video(self.video, cfg, reader, base=self.root)
            extract.assert_not_called()  # tamamlanmis video bir daha islenmez

    @unittest.skipUnless(ffmpeg_available(), 'ffmpeg yok')
    def test_extract_takes_a_frame_per_scene(self):
        video = self.root / 'renkler.mp4'
        command = [media.ffmpeg_path(), '-v', 'error', '-y',
                   '-f', 'lavfi', '-i', 'color=c=red:s=320x240:d=4:r=10',
                   '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=4:r=10',
                   '-filter_complex', '[0:v][1:v]concat=n=2:v=1', '-g', '10', '-pix_fmt', 'yuv420p', str(video)]
        subprocess.run(command, check=True, capture_output=True)
        frames = video_frames.extract(video, self.root / 'kareler')
        self.assertEqual(len(frames), 2)
        self.assertAlmostEqual(frames[0][0], 0.0, delta=0.2)
        self.assertAlmostEqual(frames[1][0], 4.0, delta=1.1)


if __name__ == '__main__':
    unittest.main()
