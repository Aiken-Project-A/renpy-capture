"""End to end on the "Torture Test", an original sample game (tests/games/torture) written for this project. Unlike
"The Question" (the Ren'Py SDK's own sample, exercised by test_the_question.py), it is built to exercise features of
renpy-capture that The Question never touches: nested and flag-gated menus, a quiz that retries after a wrong
answer, renpy.pause/{w=}/{nw}, a timed choice that times out to a default, NVL mode with a named speaker, a
layeredimage whose attributes change between lines, one-shot and endless ATL, dissolve/fade transitions, a screen
that is part of the scene next to a HUD screen that is not, a shared procedure reached by call/return from two
scenes, renpy.random and a full restart.

Opt-in (it downloads the SDK once and needs a display backend): RENPY_CAPTURE_IT=1 python -m unittest
tests.test_torture. RENPY_CAPTURE_IT_VERSION picks the SDK (default 8.3.2), RENPY_CAPTURE_IT_DISPLAY and
RENPY_CAPTURE_IT_GPU the display and GPU.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from renpy_capture import analysis, export, runner, sdk
from renpy_capture.util import read_json, read_jsonl, read_text

VERSION = os.environ.get('RENPY_CAPTURE_IT_VERSION', '8.3.2')
DISPLAY = os.environ.get('RENPY_CAPTURE_IT_DISPLAY')
GPU = os.environ.get('RENPY_CAPTURE_IT_GPU')

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_SRC = os.path.join(HERE, 'games', 'torture')

# The game ships only .rpy sources (like a fresh project or a translator's working copy), not precompiled .rpyc (like
# The Question, or any built/distributed game). Compiling it once here, with the same SDK that will run it, works
# around a renpy-capture bug this game found: see UncompiledSourceLinkBug below and the PR description for the
# smallest reproduction.
CONFIG = {
    'jobs': [
        {'id': 'start', 'label': 'start'},
        # "Consult the veteran's logbook" is gated on a flag exploration can never set on its own (nothing in the
        # game ever does); an exact job with a scope override is what `gaps` is for.
        {'id': 'veteran', 'label': 'start', 'scope': {'veteran_mode': True}, 'choices': [0, 1, 0]},
        # demonstrates wait_menus/wait_max: the capture does not answer this menu itself but waits (game time) for
        # it to resolve on its own, exactly as it would while a real player deliberated.
        {'id': 'timeout_demo', 'label': 'start', 'choices': [1], 'wait_menus': '^Quick,', 'wait_max': 2},
    ],
    'ui': '^hud$',
    'settle': 0.3,
    'settle_max': 1.5,
    'max_steps': 3000,
    'loop_limit': 40,
    'transitions': True,
}

RANDOM_LINES = (
    'A merchant offers a strange trinket.',
    'A wandering cat crosses your path.',
    'A distant bell tolls three times.',
)

NVL_LINES = (
    'Let me tell you something in a different mode entirely.',
    'Here, every line stays on the page instead of replacing the one before it.',
)

SCENES = ('menus_scene', 'menus_quiz', 'timing_scene', 'nvl_scene', 'layered_scene', 'atl_scene',
          'transitions_scene', 'customscreen_scene', 'random_scene', 'ending_scene')


@unittest.skipUnless(os.environ.get('RENPY_CAPTURE_IT'), 'set RENPY_CAPTURE_IT=1 to run the end-to-end test')
class TortureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sdk = sdk.ensure(VERSION)
        cls.tmp = tempfile.mkdtemp(prefix='renpy-capture-torture-')
        cls.game = os.path.join(cls.tmp, 'torture')
        shutil.copytree(GAME_SRC, cls.game)
        subprocess.run([os.path.join(cls.sdk, 'renpy.sh'), cls.game, 'compile'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        cls.cfg = os.path.join(cls.tmp, 'config.json')
        with open(cls.cfg, 'w', encoding='utf-8') as f:
            json.dump(CONFIG, f)
        cls.rundir = os.path.join(cls.tmp, 'run')
        cls.out = os.path.join(cls.tmp, 'out')
        cls.again = os.path.join(cls.tmp, 'out-again')
        with contextlib.redirect_stdout(io.StringIO()):
            runner.setup(cls.game, cls.rundir, version=VERSION)
            runner.explore(cls.rundir, cls.cfg, cls.out, display=DISPLAY, gpu=GPU)
            runner.run(cls.rundir, cls.cfg, cls.again, display=DISPLAY, gpu=GPU)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def records(self, out=None):
        return read_jsonl(os.path.join(out or self.out, 'log.jsonl'))

    def test_no_errors_or_stops(self):
        recs = self.records()
        self.assertFalse([r for r in recs if r['ev'] == 'error'])
        self.assertFalse([r for r in recs if r['ev'] == 'stop'])

    def test_nothing_left_uncaptured(self):
        with contextlib.redirect_stdout(io.StringIO()):
            found = analysis.gaps(self.game, self.cfg, self.out)
        self.assertEqual(dict(found), {})

    def test_second_run_is_identical(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = analysis.compare(self.out, self.again)
        self.assertTrue(ok, buf.getvalue())

    def test_endless_animation_same_phase(self):
        """gentle_pulse (atl_scene) runs forever; the virtual clock must fix its phase so the two runs above land on
        the exact same frame, not merely "both mid-animation"."""
        def anim_frames(out):
            return [(r['job'], r['seq'], r['frame']) for r in self.records(out)
                    if r['ev'] == 'shot' and r.get('anim')]
        a, b = anim_frames(self.out), anim_frames(self.again)
        self.assertTrue(a)
        self.assertEqual(a, b)

    def test_timed_choice_times_out_to_default(self):
        menus = [r['menu'] for r in self.records() if r['job'] == 'timeout_demo' and r['ev'] == 'shot'
                 and r.get('menu')]
        self.assertTrue(any(m.get('wait') for m in menus), menus)
        self.assertTrue(any('pick' in m for m in menus), menus)

    def test_export_covers_every_scene(self):
        dest = os.path.join(self.tmp, 'export')
        with contextlib.redirect_stdout(io.StringIO()):
            export.export(self.out, self.game, dest)
        rows = read_text(os.path.join(dest, 'shots.tsv')).splitlines()
        header = rows[0].split('\t')
        cells = [dict(zip(header, r.split('\t'))) for r in rows[1:]]
        labels = {c['label'] for c in cells}
        for scene in SCENES:
            self.assertIn(scene, labels)
        for c in cells:
            if c['frame']:
                self.assertTrue(os.path.exists(os.path.join(dest, 'frames', c['frame'] + '.png')))
        whats = {c['what'] for c in cells}
        for line in NVL_LINES:
            self.assertIn(line, whats)
        self.assertIn('Ivy', {c['name'] for c in cells})
        self.assertTrue(whats & set(RANDOM_LINES), whats)
        page = read_text(os.path.join(dest, 'index.html'))
        self.assertIn('Ivy', page)


class UncompiledSourceLinkBug(unittest.TestCase):
    """Found while building the Torture Test, needs no engine or SDK download to reproduce: a game that ships bare
    .rpy sources (no precompiled .rpyc, unlike The Question or any built game) has its very first compile write real
    .rpyc files straight into the launch folder's game/, next to the symlinked .rpy of the same name. `link_game`'s
    "was this folder changed by hand?" check, run again at the top of every later `run()` (explore(), prun() and a
    plain second `run` all make one), cannot tell its own engine's output from tampering and refuses to proceed."""

    @unittest.expectedFailure           # renpy-capture bug: see the class docstring for the smallest reproduction
    def test_second_link_after_compile_is_refused(self):
        tmp = tempfile.mkdtemp(prefix='renpy-capture-linkbug-')
        try:
            project = os.path.join(tmp, 'project')
            os.makedirs(os.path.join(project, 'game'))
            with open(os.path.join(project, 'game', 'script.rpy'), 'w', encoding='utf-8') as f:
                f.write('label start:\n    "hi"\n    return\n')
            rundir = os.path.join(tmp, 'run')
            runner.setup(project, rundir, version='8.3.2')            # first link_game(): all symlinks, succeeds
            # what the engine's first launch does as a side effect of compiling script.rpy, simulated without
            # starting it: it writes script.rpyc as a real file next to the symlinked script.rpy in run/game/
            open(os.path.join(rundir, 'game', 'script.rpyc'), 'a').close()
            info = read_json(os.path.join(rundir, runner.RUN_INFO))
            try:
                runner.link_game(info, rundir)                        # every run() makes this call again
            except SystemExit as e:
                raise AssertionError(str(e))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
