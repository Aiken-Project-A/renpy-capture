"""End to end on "The Question", the sample game every Ren'Py SDK ships: capture it loose and packed into an
archive, check that nothing is left uncaptured, that a second run is identical to the byte, that fast mode draws
fewer frames for the same pictures, and that the export holds every line.

Opt-in (it downloads the SDK once and needs a display backend): RENPY_CAPTURE_IT=1 python -m unittest
tests.test_the_question. RENPY_CAPTURE_IT_VERSION picks the SDK (default 8.3.2), RENPY_CAPTURE_IT_DISPLAY and
RENPY_CAPTURE_IT_GPU the display and GPU.
"""
import contextlib
import io
import os
import shutil
import tempfile
import unittest

from renpy_capture import analysis, export, runner, sdk
from renpy_capture.util import read_jsonl, read_text

from .rpatool import pack_game_dir

VERSION = os.environ.get('RENPY_CAPTURE_IT_VERSION', '8.3.2')
DISPLAY = os.environ.get('RENPY_CAPTURE_IT_DISPLAY')
GPU = os.environ.get('RENPY_CAPTURE_IT_GPU')


@unittest.skipUnless(os.environ.get('RENPY_CAPTURE_IT'), 'set RENPY_CAPTURE_IT=1 to run the end-to-end test')
class TheQuestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sdk = sdk.ensure(VERSION)
        cls.tmp = tempfile.mkdtemp(prefix='renpy-capture-it-')
        cls.out = {}
        for kind in ('loose', 'packed'):
            game = os.path.join(cls.tmp, kind, 'the_question')
            shutil.copytree(os.path.join(cls.sdk, 'the_question'), game,
                            ignore=shutil.ignore_patterns('saves', 'cache'))
            if kind == 'packed':
                pack_game_dir(os.path.join(game, 'game'))
            cfg = os.path.join(cls.tmp, kind, 'config.json')
            runner.init_config(game, cfg)
            rundir = os.path.join(cls.tmp, kind, 'run')
            out = os.path.join(cls.tmp, kind, 'out')
            with contextlib.redirect_stdout(io.StringIO()):
                runner.setup(game, rundir, version=VERSION)
                runner.explore(rundir, cfg, out, display=DISPLAY, gpu=GPU)
            cls.out[kind] = (game, cfg, rundir, out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def records(self, kind):
        return read_jsonl(os.path.join(self.out[kind][3], 'log.jsonl'))

    def test_every_branch_is_taken(self):
        recs = self.records('loose')
        jobs = {r['job'] for r in recs if r['ev'] == 'end'}
        self.assertGreaterEqual(len(jobs), 3)                       # start + one job per other menu option
        self.assertFalse([r for r in recs if r['ev'] == 'error'])
        menus = [r['menu'] for r in recs if r['ev'] == 'shot' and r.get('menu')]
        picks = {(tuple(m['options']), m['pick']) for m in menus}
        for m in menus:                                             # every option of every menu was chosen once
            for k in range(len(m['options'])):
                self.assertIn((tuple(m['options']), k), picks)

    def test_nothing_left_uncaptured(self):
        for kind in ('loose', 'packed'):
            game, cfg, _rundir, out = self.out[kind]
            with contextlib.redirect_stdout(io.StringIO()):
                found = analysis.gaps(game, cfg, out)
            self.assertEqual(dict(found), {}, kind)

    def test_speakers_have_names(self):
        names = {r.get('name') for r in self.records('loose') if r['ev'] == 'shot' and r.get('who')}
        self.assertIn('Sylvie', names)

    def compare(self, a, b):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = analysis.compare(a, b)
        self.assertTrue(ok, buf.getvalue())

    def test_archive_changes_nothing(self):
        self.compare(self.out['loose'][3], self.out['packed'][3])

    def test_second_run_is_identical(self):
        game, cfg, rundir, out = self.out['loose']
        again = out + '-again'
        with contextlib.redirect_stdout(io.StringIO()):
            runner.run(rundir, cfg, again, display=DISPLAY, gpu=GPU)
        self.compare(out, again)

    def test_fast_mode_gives_the_same_frames(self):
        game, cfg, rundir, out = self.out['loose']              # no endless animation here: skipping the frames
        fast = out + '-fast'                                    # of a settling scene must change nothing
        with contextlib.redirect_stdout(io.StringIO()):
            runner.run(rundir, cfg, fast, display=DISPLAY, gpu=GPU, fast=True)
        self.compare(out, fast)
        drawn = [sum(r['prof']['frames'] for r in read_jsonl(os.path.join(o, 'log.jsonl')) if r['ev'] == 'end')
                 for o in (out, fast)]
        self.assertLess(drawn[1], drawn[0])

    def test_export(self):
        game, cfg, _rundir, out = self.out['packed']
        dest = os.path.join(self.tmp, 'export')
        with contextlib.redirect_stdout(io.StringIO()):
            export.export(out, game, dest)
        rows = read_text(os.path.join(dest, 'shots.tsv')).splitlines()
        shots = [r for r in self.records('packed') if r['ev'] == 'shot']
        self.assertEqual(len(rows) - 1, len(shots))
        header = rows[0].split('\t')
        for row in rows[1:]:
            cells = dict(zip(header, row.split('\t')))
            self.assertTrue(os.path.exists(os.path.join(dest, 'frames', cells['frame'] + '.png')))
        page = read_text(os.path.join(dest, 'index.html'))
        self.assertIn('Sylvie', page)


if __name__ == '__main__':
    unittest.main()
