"""Kutuphane (koleksiyon deposu + klasor taramasi) testleri; Qt gerektirmez."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import library  # noqa: E402
import qa  # noqa: E402
import search_index  # noqa: E402
from app_core import save_json  # noqa: E402


def touch(path, data=b'x'):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = self.root / 'store'
        patcher = mock.patch.dict(os.environ, {'AKTAR_LIBRARY_DIR': str(self.store)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)
        self.media = self.root / 'media'
        touch(self.media / 'Ders 10.mkv')
        touch(self.media / 'Ders 2.mp4')
        touch(self.media / 'notlar.bin')
        touch(self.media / 'alt' / 'Ders 3.webm')
        touch(self.media / '.gizli' / 'x.mkv')

    def paths(self, entries):
        return [os.path.relpath(item['path'], self.media) for item in entries]

    def test_create_list_rename_delete(self):
        slug, data = library.create_collection('Makine Öğrenmesi', folders=[self.media])
        self.assertEqual(slug, 'makine-ogrenmesi')
        again, _ = library.create_collection('Makine Öğrenmesi')
        self.assertEqual(again, 'makine-ogrenmesi-2')
        self.assertEqual(list(library.list_collections()), [slug, again])
        library.rename_collection(again, 'Belgeseller')
        self.assertEqual(library.load_collection(again)['title'], 'Belgeseller')
        library.delete_collection(again)
        self.assertEqual(list(library.list_collections()), [slug])
        self.assertTrue((self.media / 'Ders 2.mp4').exists(), 'kaynak dosyalara dokunulmaz')

    def test_scan_walks_subfolders_in_natural_order_and_skips_hidden(self):
        _slug, data = library.create_collection('ML', folders=[self.media])
        entries, changed = library.scan(data)
        self.assertTrue(changed)
        self.assertEqual(self.paths(entries),
                         [os.path.join('alt', 'Ders 3.webm'), 'Ders 2.mp4', 'Ders 10.mkv'])
        self.assertTrue(all(item['kind'] == 'video' and not item['new'] for item in entries))

    def test_rescan_marks_new_and_missing_files(self):
        _slug, data = library.create_collection('ML', folders=[self.media])
        library.scan(data)
        touch(self.media / 'Ders 11.mkv')
        (self.media / 'Ders 2.mp4').unlink()
        entries, changed = library.scan(data)
        self.assertTrue(changed)
        state = {os.path.basename(item['path']): item for item in entries}
        self.assertTrue(state['Ders 11.mkv']['new'])
        self.assertTrue(state['Ders 2.mp4']['missing'])
        self.assertFalse(state['Ders 10.mkv']['new'])
        _entries, changed = library.scan(data)
        self.assertFalse(changed)

    def test_exclude_and_add_back(self):
        _slug, data = library.create_collection('ML', folders=[self.media])
        library.scan(data)
        target = self.media / 'Ders 10.mkv'
        library.exclude(data, [target])
        entries, _ = library.scan(data)
        self.assertNotIn('Ders 10.mkv', self.paths(entries))
        self.assertEqual(library.add_files(data, [target]), 1)
        entries, _ = library.scan(data)
        self.assertIn('Ders 10.mkv', self.paths(entries))

    def test_folders_merge_and_single_files(self):
        data = {'folders': [], 'files': [], 'excluded': [], 'known': []}
        self.assertTrue(library.add_folder(data, self.media / 'alt'))
        self.assertTrue(library.add_folder(data, self.media))
        self.assertEqual(data['folders'], [str(self.media)])
        self.assertFalse(library.add_folder(data, self.media / 'alt'))
        outside = touch(self.root / 'tek.mkv')
        self.assertEqual(library.add_files(data, [outside, self.media / 'Ders 2.mp4',
                                                  self.media / 'notlar.bin']), 1)
        self.assertEqual(data['files'], [str(outside)])
        outside.unlink()
        entries, _ = library.scan(data)
        self.assertTrue(next(item for item in entries if item['root'] is None)['missing'])

    def test_remove_folder_drops_its_files(self):
        _slug, data = library.create_collection('ML', folders=[self.media])
        library.scan(data)
        self.assertTrue(library.remove_folder(data, self.media))
        entries, _ = library.scan(data)
        self.assertEqual(entries, [])

    def test_describe_reads_qa_cache(self):
        video = self.media / 'Ders 2.mp4'
        entry = {'path': video, 'kind': 'video', 'root': None, 'missing': False, 'new': False}
        work = self.root / 'work'
        self.assertEqual(library.describe(entry, work)['status'], 'pending')
        source = {'kind': 'subtitle', 'stream': 2, 'language': 'eng', 'title': ''}
        data = qa.build_data(video, [{'start': 0.0, 'end': 2.0, 'text': 'merhaba'}], source,
                             {'duration': 95.0, 'chapters': []})
        save_json(qa.cache_path(video, qa.source_key(source), work), data)
        cfg = {'embedding_model': 'emb', 'embedding_document_template': 'title: {title} | text: {text}'}
        info = library.describe(entry, work, cfg=cfg)
        self.assertEqual((info['status'], info['source'], info['duration']),
                         ('transcript', 'Altyazı · eng', 95.0))
        # F57: 'Hazir' = transkript + embedding indeksi.
        save_json(search_index.index_path(video, data, cfg, work), {})
        self.assertEqual(library.describe(entry, work, cfg=cfg)['status'], 'ready')
        self.assertEqual(library.describe(entry, work, cfg={'embedding_model': ''})['status'],
                         'transcript')
        missing = dict(entry, missing=True)
        self.assertEqual(library.describe(missing, work)['status'], 'missing')

    def _entry(self, name):
        return {'path': self.media / name, 'kind': 'video', 'root': None,
                'missing': False, 'new': False}

    SUB = {'index': 2, 'codec': 'subrip', 'language': 'eng', 'title': '', 'supported': True,
           'image': False, 'extension': 'srt'}

    def test_probe_is_cached_until_file_changes(self):
        work = self.root / 'work'
        target = self.media / 'Ders 2.mp4'
        summary = {'duration': 61.0, 'subtitles': [self.SUB]}
        with mock.patch('media.probe_summary', return_value=summary) as probed:
            self.assertIsNone(library.cached_probe(target, work))
            self.assertEqual(library.probe(target, work)['duration'], 61.0)
            library.probe(target, work)
            self.assertEqual(probed.call_count, 1)
            os.utime(target, (1_000_000, 1_000_000))
            library.probe(target, work)
            self.assertEqual(probed.call_count, 2)
        info = library.describe(self._entry('Ders 2.mp4'), work)
        self.assertEqual((info['status'], info['duration']), ('pending', 61.0))

    def test_plan_groups_by_transcript_source(self):
        work = self.root / 'work'
        source = {'kind': 'subtitle', 'stream': 2, 'language': 'eng', 'title': ''}
        ready = self.media / 'Ders 10.mkv'
        save_json(qa.cache_path(ready, qa.source_key(source), work),
                  qa.build_data(ready, [], source, {'duration': 1.0, 'chapters': []}))
        summaries = {'Ders 2.mp4': {'duration': 10.0, 'subtitles': [self.SUB]},
                     'Ders 3.webm': {'duration': 90.0, 'subtitles': []}}
        entries = [self._entry('Ders 10.mkv'), self._entry('Ders 2.mp4'),
                   self._entry(os.path.join('alt', 'Ders 3.webm')),
                   dict(self._entry('yok.mkv'), missing=True)]
        with mock.patch('media.probe_summary', side_effect=lambda path: summaries[path.name]):
            result = library.plan(entries, work, cfg={'embedding_model': ''})
            indexed = library.plan(entries, work, cfg={
                'embedding_model': 'emb', 'embedding_document_template': '{text}'})
        names = {key: [item['path'].name for item in result[key]]
                 for key in ('ready', 'summary', 'index', 'subtitle', 'whisper')}
        # F61: transkripti (ve gerekirse indeksi) olan ama video ozeti olmayan -> 'summary'.
        self.assertEqual(names, {'ready': [], 'summary': ['Ders 10.mkv'], 'index': [],
                                 'subtitle': ['Ders 2.mp4'], 'whisper': ['Ders 3.webm']})
        self.assertEqual(result['whisper_seconds'], 90.0)
        # Embedding modeli seciliyse transkripti olup indeksi olmayan video indekslenecek.
        self.assertEqual([item['path'].name for item in indexed['index']], ['Ders 10.mkv'])
        self.assertEqual(indexed['ready'], [])
        whisper = library.describe(entries[2], work, cfg={'embedding_model': ''})
        self.assertEqual(whisper['status'], 'no_subtitle')

    def test_transcribe_uses_subtitle_then_whisper_only_when_allowed(self):
        work = self.root / 'work'
        cfg = {'whisper_model': 'small', 'whisper_language': '', 'whisper_device': 'cpu'}
        entry = self._entry('Ders 2.mp4')
        with mock.patch('media.probe_summary',
                        return_value={'duration': 5.0, 'subtitles': [self.SUB]}), \
                mock.patch('qa.load_subtitle_session') as load:
            self.assertEqual(library.transcribe(entry, cfg, base=work), 'subtitle')
            self.assertEqual(load.call_args.args[1]['index'], 2)
        silent = self._entry('Ders 10.mkv')
        result = {'segments': [{'start': 0.0, 'end': 1.0, 'text': 'x'}], 'model': 'small'}
        with mock.patch('media.probe_summary', return_value={'duration': 5.0, 'subtitles': []}), \
                mock.patch('speech.transcribe', return_value=result) as run, \
                mock.patch('qa.load_whisper_session') as load:
            self.assertEqual(library.transcribe(silent, cfg, allow_whisper=False, base=work),
                             'skipped')
            run.assert_not_called()
            self.assertEqual(library.transcribe(silent, cfg, base=work), 'whisper')
            run.assert_called_once()
            self.assertIs(load.call_args.args[1], result)

    def test_transcript_search_ignores_case_and_turkish_letters(self):
        """F59: model kullanmadan transkript aramasi; tum kelimeler ayni satirda."""
        work = self.root / 'work'
        video = self.media / 'Ders 2.mp4'
        source = {'kind': 'subtitle', 'stream': 2, 'language': 'tr', 'title': ''}
        segments = [{'start': 5.0, 'end': 8.0, 'text': 'AŞIRI öğrenme ezberdir.'},
                    {'start': 60.0, 'end': 64.0, 'text': 'Budama ağacı küçültür.'}]
        save_json(qa.cache_path(video, qa.source_key(source), work),
                  qa.build_data(video, segments, source, {'duration': 70.0, 'chapters': []}))
        entry = self._entry('Ders 2.mp4')
        info = library.describe(entry, work, cfg={'embedding_model': ''})
        self.assertEqual(library.fold('AŞIRI Öğrenme'), 'asiri ogrenme')
        hits, matched = library.transcript_hits([entry], [info], 'asiri ogren')
        self.assertEqual([(hit['start'], hit['text']) for hit in hits],
                         [(5.0, 'AŞIRI öğrenme ezberdir.')])
        self.assertEqual(matched, {library._key(entry['path'])})
        self.assertEqual(library.transcript_hits([entry], [info], 'budama ezber')[0], [])
        missing = library.describe(dict(entry, missing=True), work)
        self.assertEqual(missing['lines'], [])

    def test_chat_is_saved_trimmed_and_deleted_with_collection(self):
        """F60: sohbet koleksiyon basina diske yazilir; koleksiyon silinince gider."""
        slug, _data = library.create_collection('ML')
        self.assertEqual(library.load_chat(slug), {'entries': [], 'history': []})
        turn = {'question': 'q', 'answer': 'a [V1 0:05]',
                'parts': [('text', 'a '), ('cite', [{'video': 'x.mkv', 'start': 5.0,
                                                    'label': 'V1 0:05'}])],
                'sources': []}
        entries = [('note', 'merhaba'), ('user', 'q'), ('assistant', turn), ('pending', '...')]
        library.save_chat(slug, entries, [turn])
        saved = library.load_chat(slug)
        self.assertEqual([kind for kind, _item in saved['entries']], ['user', 'assistant'])
        self.assertEqual(saved['entries'][1][1]['parts'][1][1][0]['start'], 5.0)
        self.assertEqual(saved['history'], [{'question': 'q', 'answer': 'a [V1 0:05]'}])
        many = [item for index in range(library.CHAT_TURNS + 5)
                for item in (('user', f'q{index}'), ('error', 'x'))]
        library.save_chat(slug, many, [])
        entries = library.load_chat(slug)['entries']
        self.assertEqual(len(entries), 2 * library.CHAT_TURNS)
        self.assertEqual(entries[0], ('user', 'q5'))
        # Sohbet/ozet kayitlari ayni klasorde durur ama koleksiyon sayilmaz (bos 'hayalet'
        # koleksiyon olarak listelenmemeli).
        library.save_overview(slug, {'summary': 'x', 'topics': [], 'questions': [],
                                     'title': 'ML', 'videos': []})
        self.assertEqual(list(library.list_collections()), [slug])
        library.delete_collection(slug)
        self.assertFalse(library.chat_path(slug).exists())
        self.assertFalse(library.overview_path(slug).exists())

    def test_default_title(self):
        self.assertEqual(library.default_title([self.media]), 'media')
        self.assertEqual(library.default_title([self.media / 'Ders 2.mp4']), 'media')


if __name__ == '__main__':
    unittest.main()
