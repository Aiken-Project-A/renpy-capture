"""The work folder of `capture`: where each capture and its pages go, and what a capture tells at its end, to a
person and to a program that reads its progress."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from renpy_capture import workflow
from renpy_capture.util import plural
from renpy_capture.workflow import paths

from .test_events import machine_mode


class WorkFolderTest(unittest.TestCase):
    def test_every_kind_of_capture_has_its_own_folders(self):
        seen = set()
        for language in (None, 'russian'):
            for text in (False, True):
                p = paths('work', language, text)
                self.assertEqual(p['config'], os.path.join('work', 'config.json'))    # one config and launch folder
                self.assertEqual(p['run'], os.path.join('work', 'run'))
                seen.add((p['out'], p['export']))
        self.assertEqual(len(seen), 4)
        self.assertEqual(paths('work')['out'], os.path.join('work', 'out'))
        self.assertEqual(paths('work', 'russian', True)['export'], os.path.join('work', 'export-text-russian'))

    def test_plural(self):
        self.assertEqual(plural(1, 'job'), '1 job')
        self.assertEqual(plural(0, 'line'), '0 lines')
        self.assertEqual(plural(2, 'new branch', 'new branches'), '2 new branches')


LOG = [{'ev': 'start', 'job': 'start'},
       {'ev': 'shot', 'job': 'start', 'seq': 1, 'frame': 'f1'}, {'ev': 'shot', 'job': 'start', 'seq': 2, 'frame': 'f1'},
       {'ev': 'shot', 'job': 'start', 'seq': 3, 'frame': 'f2'},
       {'ev': 'end', 'job': 'start', 'why': 'end', 'seconds': 1.0}]


class CaptureTest(unittest.TestCase):
    """`capture` with the engine, the check for unreached lines and the pages replaced by fakes: what is left is what
    it adds itself, the summary and its two ways of telling it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game, self.work = os.path.join(self.tmp.name, 'game'), os.path.join(self.tmp.name, 'work')
        self.log, self.found, self.complete, self.calls = LOG, {}, True, []
        self.patches = [mock.patch.object(workflow.runner, 'init_config', self.init_config),
                        mock.patch.object(workflow.runner, 'setup', lambda *a, **kw: self.calls.append('setup')),
                        mock.patch.object(workflow.runner, 'explore', self.explore),
                        mock.patch.object(workflow.analysis, 'gaps', lambda *a, **kw: self.found),
                        mock.patch.object(workflow.export, 'export', self.export)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def init_config(self, game, path):
        with open(path, 'w') as f:
            f.write('{}')

    def explore(self, rundir, cfg, out, **kw):
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, 'log.jsonl'), 'w') as f:
            f.writelines(json.dumps(r) + '\n' for r in self.log)
        return self.complete

    def export(self, out, game, dest, opts=None, page=True, beside=None):
        self.calls.append(('export', os.path.basename(out), os.path.basename(dest), beside and os.path.basename(beside)))
        os.makedirs(dest, exist_ok=True)
        for name in ('index.html', 'choices.html', 'shots.tsv'):
            open(os.path.join(dest, name), 'w').close()

    def capture(self, **kw):
        """(what a person is told, the events a program is told) of one `capture`."""
        with machine_mode() as (out, err):
            workflow.capture(self.game, self.work, **kw)
        text = err.getvalue().decode('utf-8')
        return text, [json.loads(line) for line in out.getvalue().decode('ascii').splitlines()]

    def test_a_program_is_told_every_step_and_then_the_summary(self):
        _, told = self.capture()
        self.assertEqual([e['stage'] for e in told if e['event'] == 'stage'], ['setup', 'capture', 'check', 'export'])
        self.assertEqual([e['event'] for e in told][-1], 'done')
        done = told[-1]
        self.assertEqual((done['lines'], done['jobs'], done['pictures']), (3, 1, 2))
        self.assertEqual((done['complete'], done['errors'], done['missed'], done['unchecked'], done['warnings']),
                         (True, [], 0, None, []))
        for key in ('workdir', 'config', 'out', 'export', 'index', 'table', 'choices'):
            self.assertTrue(os.path.isabs(done[key]), key)
        self.assertEqual(done['index'], os.path.join(os.path.abspath(self.work), 'export', 'index.html'))
        self.assertTrue(os.path.exists(done['index']))

    def test_a_person_reads_the_same_numbers(self):
        text, _ = self.capture()
        self.assertIn('Done: 3 lines in 1 job, 2 pictures, every menu option taken.', text)
        self.assertIn('Every scene line was reached.', text)
        self.assertIn(os.path.join('export', 'index.html'), text)

    def test_without_the_option_the_text_is_on_the_standard_output_as_before(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            workflow.capture(self.game, self.work)
        self.assertIn('Done: 3 lines in 1 job, 2 pictures, every menu option taken.', out.getvalue())

    def test_jobs_that_stopped_on_an_error_and_lines_no_branch_reached(self):
        self.log = LOG + [{'ev': 'error', 'job': 'start~1', 'error': 'NameError: x'},
                          {'ev': 'error', 'job': 'start~2', 'error': 'x', 'ignored': True}]
        self.found, self.complete = {'script.rpy': [(3, 'scene bg'), (9, 'scene bg2')]}, False
        text, told = self.capture()
        done = told[-1]
        self.assertEqual((done['errors'], done['missed'], done['complete']), (['start~1'], 2, False))
        self.assertIn('some branches are still to take: run it again.', text)
        self.assertIn('1 job stopped on a script error', text)
        self.assertIn('2 scene lines never reached', text)

    def test_unreached_lines_that_could_not_be_checked(self):
        def gaps(*a, **kw):
            raise ImportError('cannot download unrpyc')

        with mock.patch.object(workflow.analysis, 'gaps', gaps):
            text, told = self.capture()
        self.assertEqual((told[-1]['missed'], told[-1]['unchecked']), (None, 'cannot download unrpyc'))
        self.assertIn('Lines left unreached: not checked, cannot download unrpyc.', text)

    def test_a_translation_is_shown_beside_the_original_when_it_has_been_captured(self):
        text, told = self.capture(language='russian')
        self.assertFalse(told[-1]['beside'])
        self.assertIn('Capture the original too', text)
        self.assertEqual(self.calls[-1], ('export', 'out-russian', 'export-russian', None))
        self.capture()                                          # the original
        text, told = self.capture(language='russian')
        self.assertTrue(told[-1]['beside'])
        self.assertEqual(self.calls[-1], ('export', 'out', 'export-russian', 'out-russian'))
        self.assertNotIn('Capture the original too', text)
        self.assertEqual((told[-1]['language'], told[-1]['text']), ('russian', False))

if __name__ == '__main__':
    unittest.main()
