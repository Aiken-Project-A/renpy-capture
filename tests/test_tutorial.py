"""End to end on the Ren'Py Tutorial, the larger of the two games every Ren'Py SDK ships: a hub of topics the player
picks from a called screen, many screens, ATL and transforms, NVL mode, an imagemap whose hotspots jump, interactive
examples and a pong minigame. It is captured the way a user would, with `capture` and the config a user can write
from reading the script (TUTORIAL_CONFIG); the test checks that the hub and every menu are taken all the way, that no
job stops on an error or hangs, that `gaps` finds nothing left unreached, and that a second run gives the same
pictures.

Opt-in and slow (minutes; it downloads the SDK once and needs a display backend): RENPY_CAPTURE_IT_TUTORIAL=1 python
-m unittest tests.test_tutorial. RENPY_CAPTURE_IT_VERSION picks the SDK (default 8.3.2), RENPY_CAPTURE_IT_DISPLAY and
RENPY_CAPTURE_IT_GPU the display and GPU. Nothing of the capture is kept: the Tutorial's art is not under the terms of
this repository.
"""
import collections
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from renpy_capture import analysis, runner, sdk, workflow
from renpy_capture.util import read_jsonl

VERSION = os.environ.get('RENPY_CAPTURE_IT_VERSION', '8.3.2')
DISPLAY = os.environ.get('RENPY_CAPTURE_IT_DISPLAY')
GPU = os.environ.get('RENPY_CAPTURE_IT_GPU')

# The starter config, plus what a user learns from the Tutorial's script: its pong minigame says "I win!" when the
# screen returns "eileen" (indepth_minigame.rpy), and "You won!" otherwise, which is what a capture gets on its own.
TUTORIAL_CONFIG = {
    'jobs': [{'id': 'start', 'label': 'start'},
             {'id': 'pong lost', 'label': 'demo_minigame', 'stub_screens': {'pong': 'eileen'}}],
    'ui': '.*',
    'settle': 0.3,
    'settle_max': 1.2,
    'max_steps': 3000,
    'loop_limit': 40,
}

# The topics of the hub, as its buttons say them (script.rpy), and the line each one starts with.
TOPICS = ('Player Experience', 'Creating a New Game', 'Writing Dialogue', 'Adding Images', 'Positioning Images',
          'Transitions', 'Music and Sound Effects', 'Choices and Python', 'Input and Interpolation', 'Video Playback',
          'NVL Mode', 'Tools and the Interactive Director', 'Building Distributions',
          'Text Tags, Escapes, and Interpolation', 'Character Objects', 'Simple Displayables', 'Transition Gallery',
          'Position Properties', 'Transforms and Animation', 'Transform Properties', 'GUI Customization',
          'Styles and Style Properties', 'Screen Basics', 'Screen Displayables', 'Minigames and CDDs',
          'Translations', "That's enough for now.")


@unittest.skipUnless(os.environ.get('RENPY_CAPTURE_IT_TUTORIAL'),
                     'set RENPY_CAPTURE_IT_TUTORIAL=1 to run the end-to-end test on the Tutorial')
class Tutorial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sdk = sdk.ensure(VERSION)
        cls.game = os.path.join(cls.sdk, 'tutorial')   # in place: it takes fonts from ../launcher (never written to)
        cls.tmp = tempfile.mkdtemp(prefix='renpy-capture-tutorial-')
        cls.work = os.path.join(cls.tmp, 'work')
        os.makedirs(cls.work)
        with open(os.path.join(cls.work, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump(TUTORIAL_CONFIG, f)
        cls.said = io.StringIO()
        with contextlib.redirect_stdout(cls.said):
            cls.paths = workflow.capture(cls.game, cls.work, display=DISPLAY, gpu=GPU)
        cls.recs = read_jsonl(os.path.join(cls.paths['out'], 'log.jsonl'))
        cls.shots = [r for r in cls.recs if r['ev'] == 'shot']

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_no_errors_stalls_or_warnings(self):
        """Every job ends at the end of the game, of its own label, or back at the hub; `report` warns of nothing."""
        self.assertFalse([r for r in self.recs if r['ev'] == 'error'], self.said.getvalue()[-3000:])
        self.assertEqual({r['why'] for r in self.recs if r['ev'] == 'stop'}, {'hub'})
        self.assertIn('every menu option taken', self.said.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            analysis.report(self.paths['out'])
        self.assertNotIn('warning', buf.getvalue())

    def test_both_ends_of_pong(self):
        said = collections.defaultdict(set)
        for r in self.shots:
            if r.get('what') in ('I win!', 'You won! Congratulations.'):
                said[r['what']].add(r['job'])
        self.assertIn('pong lost', said['I win!'])
        self.assertTrue(said['You won! Congratulations.'] - {'pong lost'})

    def test_the_hub_is_a_menu_and_every_topic_is_taken(self):
        hub = [r['menu'] for r in self.shots if (r.get('menu') or {}).get('screen') == 'tutorials']
        self.assertTrue(hub)
        self.assertEqual({tuple(m['options']) for m in hub}, {TOPICS})
        self.assertEqual({m['pick'] for m in hub if 'pick' in m}, set(range(len(TOPICS))))

    def test_every_option_of_every_menu_is_taken(self):
        picks = collections.defaultdict(set)
        sizes = {}
        for r in self.shots:
            m = r.get('menu')
            if m and 'pick' in m:
                picks[r['file'], r['line']].add(m['pick'])
                sizes[r['file'], r['line']] = len(m['options'])
        self.assertGreater(len(picks), 10)
        for k, n in sizes.items():
            self.assertEqual(picks[k], set(range(n)), k)

    def test_the_imagemap_hotspots_jump(self):
        whats = {r.get('what') for r in self.shots}
        for line in ('You chose swimming.', 'You chose science.', 'You chose art.', 'You chose to go home.'):
            self.assertIn(line, whats)

    def test_nvl_lines_are_captured(self):
        self.assertTrue([r for r in self.shots if r.get('who') == 'nvle'])

    def test_second_run_is_identical(self):
        """The same jobs again, on a fresh engine: the same pictures to the byte (a movie playing may be caught in
        another frame)."""
        again = os.path.join(self.tmp, 'again')
        with contextlib.redirect_stdout(io.StringIO()):
            runner.run(self.paths['run'], self.paths['config'], again, display=DISPLAY, gpu=GPU)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = analysis.compare(self.paths['out'], again)
        self.assertTrue(ok, buf.getvalue())

    def test_nothing_left_unreached(self):
        with contextlib.redirect_stdout(io.StringIO()):
            found = analysis.gaps(self.game, self.paths['config'], self.paths['out'])
        self.assertEqual(dict(found), {})


if __name__ == '__main__':
    unittest.main()
