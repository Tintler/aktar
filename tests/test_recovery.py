"""Adversarial model responses and complete user-file regressions (no live LLM)."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app_core
import subtitle


class Model:
    def __init__(self, collapse=False, fail=None):
        self.collapse = collapse
        self.fail = fail
        self.requests = []

    @staticmethod
    def translated(text):
        # Keep native numbering to make its loss observable, with distinct output.
        return re.sub(r'^(\d+\. )?(.*)',
                      lambda m: (m[1] or '') + 'TR ' + m[2], text)

    def generate(self, system, user):
        source = user.split('SOURCE TO TRANSLATE:\n', 1)[1].split('\nSINGLE ENTRY:', 1)[0]
        ids = [int(x) for x in re.findall(r'^ID: (\d+)', source, re.M)]
        entries = subtitle.parse_translation_response(source, ids)
        self.requests.append(list(entries.values()))
        if self.fail and any(self.fail == text for text in entries.values()):
            if len(entries) == 1:
                raise RuntimeError('HTTP 401: denied')
        if self.collapse and len(entries) > 1:
            # Same count but reversed answers. Old F29 silently accepts this.
            return '\n\n'.join(f'{i}. {self.translated(text)}'
                               for i, text in reversed(list(entries.items())))
        if self.collapse:
            return self.translated(next(iter(entries.values())))
        return '\n\n'.join(f'ID: {i}\nTEXT: {self.translated(text)}'
                           for i, text in reversed(list(entries.items())))


class RecoveryTests(unittest.TestCase):
    def engine(self, **overrides):
        config = dict(app_core.DEFAULT_CONFIG, auto_retry_count=1, batch_cues=10)
        config.update(overrides)
        return app_core.TranslationEngine(lambda: config, log=lambda _: None)

    def test_complete_user_files_normal_and_adversarial(self):
        for filename, count, groups in [('turning-point-3.ass', 1242, 385),
                                        ('afar.ass', 471, 363),
                                        ('sakamoto-12.srt', 320, 320)]:
            path = Path(__file__).parent / 'fixtures' / filename
            kind, payload = subtitle.parse_by_extension(path.read_text(encoding='utf-8-sig'), path.suffix)
            cues = subtitle.cues_of(kind, payload)
            originals = subtitle.translatable(cues)
            analyses = [subtitle.analyze(c.text) for c in originals]
            self.assertEqual(len(originals), count)
            self.assertEqual(len(subtitle.translation_groups(originals, analyses)), groups)
            for collapse in [False, True]:
                with self.subTest(filename=filename, collapse=collapse):
                    model = Model(collapse)
                    with mock.patch.object(app_core, 'Client', return_value=model):
                        result = self.engine().translate(cues)
                    output = subtitle.render_by_kind(kind, payload, result)
                    kind2, payload2 = subtitle.parse_by_extension(output, path.suffix)
                    parsed = subtitle.cues_of(kind2, payload2)
                    self.assertEqual(len(parsed), len(cues))
                    subtitle.validate_structure(cues, parsed)
                    if kind == 'ass':
                        self.assertEqual(payload[1], payload2[1])
                        # Existing renderer moves [Events] after metadata; compare content.
                        self.assertEqual([x for x in payload[0] if x.strip()],
                                         [x for x in payload2[0] if x.strip()])
                    for before, after in zip(cues, parsed):
                        self.assertEqual(before.prefix, after.prefix)
                        self.assertEqual((before.start, before.end, before.index, before.extra, before.raw),
                                         (after.start, after.end, after.index, after.extra, after.raw))
                        if not before.translatable:
                            continue
                        analysis = subtitle.analyze(before.text)
                        visible = subtitle.send_text(analysis)
                        expected = before.text if visible is None else subtitle.rebuild(analysis, Model.translated(visible))
                        self.assertEqual(after.text, expected)
                    if filename == 'turning-point-3.ass' and not collapse:
                        submitted = [text for request in model.requests for text in request]
                        self.assertEqual(submitted.count('1. Summon inorganic matter'), 1)
                        self.assertEqual(submitted.count('2. Summon organic matter'), 1)

    def test_split_success_checkpoint_survives_later_failure(self):
        cues = [subtitle.Cue([x]) for x in ['A', 'B', 'C', 'D']]
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder) / 'state.json'
            first = Model(collapse=True, fail='B')
            with mock.patch.object(app_core, 'Client', return_value=first):
                with self.assertRaisesRegex(RuntimeError, '401'):
                    self.engine().translate(cues, checkpoint=checkpoint)
            saved = json.loads(checkpoint.read_text())['translations']
            self.assertEqual(saved, {'0': 'TR A'})
            second = Model(collapse=True)
            with mock.patch.object(app_core, 'Client', return_value=second):
                result = self.engine().translate(cues, checkpoint=checkpoint)
            self.assertEqual([c.text for c in result], ['TR A', 'TR B', 'TR C', 'TR D'])
            self.assertNotIn('A', [text for request in second.requests for text in request])

    def test_pause_stop_after_successful_subbatch_is_saved(self):
        cues = [subtitle.Cue(['A']), subtitle.Cue(['B'])]
        controller = app_core.PauseController()
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder) / 'state.json'
            def progress(done, total):
                if done == 1:
                    controller.request_close()
            with mock.patch.object(app_core, 'Client', return_value=Model(collapse=True)):
                with self.assertRaises(app_core.GracefulStop):
                    self.engine().translate(cues, checkpoint=checkpoint, pause=controller,
                                            progress=progress)
            self.assertEqual(json.loads(checkpoint.read_text())['translations'], {'0': 'TR A'})

    def test_network_failure_does_not_split(self):
        client = mock.Mock()
        client.generate.side_effect = RuntimeError('HTTP 503: unavailable')
        with mock.patch.object(app_core, 'Client', return_value=client):
            with self.assertRaises(RuntimeError):
                self.engine(auto_retry_count=1).translate([subtitle.Cue(['A']), subtitle.Cue(['B'])])
        self.assertEqual(client.generate.call_count, 2)

    def test_unrecoverable_singleton_does_not_commit(self):
        client = mock.Mock()
        client.generate.return_value = 'ID: 2\nTEXT: wrong'
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder) / 'state.json'
            with mock.patch.object(app_core, 'Client', return_value=client):
                with self.assertRaises(ValueError):
                    self.engine(auto_retry_count=1).translate([subtitle.Cue(['A'])], checkpoint=checkpoint)
            self.assertFalse(checkpoint.exists())
            self.assertEqual(client.generate.call_count, 2)

    def test_glossary_fix_receives_translation(self):
        client = mock.Mock()
        client.generate.side_effect = ['ID: 1\nTEXT: Duman burada.', 'ID: 1\nTEXT: Kul burada.']
        with mock.patch.object(app_core, 'Client', return_value=client):
            self.engine().translate([subtitle.Cue(['Ash is here.'])],
                                    glossary=[{'source': 'Ash', 'target': 'Kul'}])
        correction = client.generate.call_args_list[1].args[1]
        self.assertIn('TEXT: Duman burada.', correction)
        self.assertNotIn('TEXT: Ash is here.', correction)

    def test_truncated_response_rejected_even_with_all_ids(self):
        client = app_core.Client(dict(app_core.DEFAULT_CONFIG), log=lambda _: None)
        for finish in ['length', 'content_filter', 'tool_calls']:
            with self.subTest(finish=finish), mock.patch.object(client, 'request', return_value={
                'choices': [{'message': {'content': 'ID: 1\nTEXT: Unfinished'}, 'finish_reason': finish}]
            }):
                with self.assertRaises(ValueError):
                    client.generate('system', 'user')

    def test_time_scoped_groups_do_not_merge_dialogue_or_distant_occurrences(self):
        def cue(start, end, style='Signs', name='', text='{\\pos(1,2)}Same'):
            return subtitle.Cue([text], ass_fields={'start': start, 'end': end,
                                                    'style': style, 'name': name})
        cues = [cue('0:00:01.00', '0:00:01.04'), cue('0:00:01.04', '0:00:01.08'),
                cue('0:00:02.00', '0:00:02.04'), cue('0:00:01.00', '0:00:01.04', name='Other'),
                cue('0:00:01.00', '0:00:01.04', style='Other'),
                cue('0:00:01.00', '0:00:01.04', text='Same'),
                cue('0:00:01.04', '0:00:01.08', text='Same'), subtitle.Cue(['Same'])]
        groups = subtitle.translation_groups(cues, [subtitle.analyze(c.text) for c in cues])
        self.assertEqual(groups, [[0, 1], [2], [3], [4], [5], [6], [7]])

    def test_grouping_handles_out_of_order_events(self):
        cues = [subtitle.Cue(['{\\pos(1,2)}Same'], ass_fields={'start': start, 'end': end})
                for start, end in [('0:00:01.08', '0:00:01.12'), ('0:00:01.00', '0:00:01.04'),
                                   ('0:00:01.04', '0:00:01.08')]]
        self.assertEqual(subtitle.translation_groups(cues, [subtitle.analyze(c.text) for c in cues]),
                         [[0, 1, 2]])

    def test_old_protocol_checkpoint_is_rejected_without_overwrite(self):
        cues = [subtitle.Cue(['A'])]
        old_signature = app_core.digest(json.dumps({
            'sources': ['A'], 'glossary': [], 'decisions': [], 'prompt': '',
            'model': app_core.DEFAULT_CONFIG['model'], 'batch_cues': 10,
        }, ensure_ascii=False, sort_keys=True))
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder) / 'state.json'
            old = json.dumps({'signature': old_signature, 'translations': {'0': 'BAD'}})
            checkpoint.write_text(old)
            with self.assertRaisesRegex(ValueError, 'protokol'):
                self.engine().translate(cues, checkpoint=checkpoint, prompt='')
            self.assertEqual(checkpoint.read_text(), old)

    def test_truncation_recovery_splits_batch(self):
        class LimitedModel(Model):
            def generate(self, system, user):
                if user.count('\nID: ') > 1:
                    raise ValueError('Yanıt token sınırında kesildi; eksik çeviri kabul edilmedi.')
                return super().generate(system, user)
        with mock.patch.object(app_core, 'Client', return_value=LimitedModel()):
            result = self.engine().translate([subtitle.Cue(['A']), subtitle.Cue(['B'])])
        self.assertEqual([c.text for c in result], ['TR A', 'TR B'])
