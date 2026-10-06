"""End to end on the "Torture Test", an original sample game (tests/games/torture) written for this project. Unlike
"The Question" (the Ren'Py SDK's own sample, exercised by test_the_question.py), it is built to exercise features of
renpy-capture that The Question never touches: nested and flag-gated menus, a quiz that retries after a wrong
answer, renpy.pause/{w=}/{nw}, a timed choice that times out to a default, NVL mode with a named speaker, a
layeredimage whose attributes change between lines, one-shot and endless ATL, dissolve/fade transitions, a screen
that is part of the scene next to a HUD screen that is not, a shared procedure reached by call/return from two
scenes, renpy.random and a full restart; its own say and choice screens, drawn with text, and a click-to-continue
indicator that blinks for ever; and a scene that changes while its statements stay the same (one show line run with
other arguments, a screen whose text follows a variable, a caption the config hides however it is shown);
a file found on a search path the game gives relative to its own folder; a screen the script calls and waits on, whose
buttons are the options of a menu.

Opt-in (it downloads the SDK once and needs a display backend): RENPY_CAPTURE_IT=1 python -m unittest
tests.test_torture. RENPY_CAPTURE_IT_VERSION picks the SDK (default 8.3.2), RENPY_CAPTURE_IT_DISPLAY and
RENPY_CAPTURE_IT_GPU the display and GPU.
"""
import collections
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
        {'id': 'veteran mode', 'label': 'start', 'scope': {'veteran_mode': True}, 'choices': [0, 1, 0]},   # (an id
        # with a space: a second run must still know it is done)
        # demonstrates wait_menus: the capture does not answer this menu itself but waits (game time) for the game's
        # own timer to resolve it, exactly as it would while a real player deliberated. wait_max only answers a menu
        # whose timer never comes; it is large here, so the test sees the game lead on by itself.
        {'id': 'timeout_demo', 'label': 'start', 'choices': [1], 'wait_menus': '^Quick,', 'wait_max': 30},
    ],
    'ui': '^hud$',
    'hide_tags': '^caption_card$',
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
          'transitions_scene', 'customscreen_scene', 'random_scene', 'changes_scene', 'ending_scene')


@unittest.skipUnless(os.environ.get('RENPY_CAPTURE_IT'), 'set RENPY_CAPTURE_IT=1 to run the end-to-end test')
class TortureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sdk = sdk.ensure(VERSION)
        cls.tmp = tempfile.mkdtemp(prefix='renpy-capture-torture-')
        cls.game = os.path.join(cls.tmp, 'torture')
        shutil.copytree(GAME_SRC, cls.game)
        subprocess.run(sdk.engine(cls.sdk) + [cls.game, 'compile'], check=True,
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
        self.assertEqual([r['why'] for r in recs if r['ev'] == 'stop'], ['hub'])     # the signpost met again

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
        """The timed menu is left unanswered; the game's own timer (1 s) picks its first option, long before
        wait_max would answer it."""
        shots = [r for r in self.records() if r['job'] == 'timeout_demo' and r['ev'] == 'shot']
        waited = [k for k, r in enumerate(shots) if (r.get('menu') or {}).get('wait')]
        self.assertEqual(len(waited), 1, shots)
        after = shots[waited[0] + 1]
        self.assertNotIn('menu', after)                     # not answered by the capture after wait_max
        self.assertEqual(after.get('what'), 'The left lever grinds and the gate slides open.')

    def test_a_line_after_a_call_returns_has_the_callers_label(self):
        """shared_flourish is called from three scenes: its own line has its label, and the line after each call has
        the label of the scene that called it, not of the last label entered."""
        want = {'A shimmering flourish briefly lights the air.': 'shared_flourish',
                'A soft chime plays as the flourish settles.': 'timing_scene',
                'The flourish returns here, shared with the transitions scene.': 'atl_scene',
                'The flourish appears here too, shared with the ATL scene.': 'transitions_scene'}
        got = collections.defaultdict(set)
        for r in self.records():
            if r['ev'] == 'shot' and r.get('what') in want:
                got[r['what']].add(r['label'])
        self.assertEqual({w: {lab} for w, lab in want.items()}, dict(got))

    QUINN = ('Here I am, feeling perfectly calm.', 'Wait — did you hear that?', 'Never mind. All clear again.')

    def test_a_blinking_indicator_is_not_motion(self):
        """Quinn's lines come with a click-to-continue indicator that blinks for ever, in a scene that does not move:
        they are captured at rest, without text (the indicator is in the invisible stand-in) and with it (drawn)."""
        text = os.path.join(self.tmp, 'out-text')
        with contextlib.redirect_stdout(io.StringIO()):
            runner.run(self.rundir, self.cfg, text, display=DISPLAY, gpu=GPU, text=True)
        for out in (self.out, text):
            quinn = [r for r in self.records(out) if r['ev'] == 'shot' and r.get('what') in self.QUINN]
            self.assertTrue(quinn, out)
            self.assertFalse([r for r in quinn if r.get('anim')], out)
        plain = {(r['job'], r['seq']): r['frame'] for r in self.records(self.again) if r['ev'] == 'shot'}
        for r in self.records(text):
            if r['ev'] == 'shot' and r.get('what') in self.QUINN:
                self.assertNotEqual(r['frame'], plain[r['job'], r['seq']])     # the window is in the frame
        first, second = self.shots_of(*NVL_LINES, out=text)                     # with text the NVL page is drawn,
        self.assertNotEqual(first['frame'], second['frame'])                    # a line more on each frame

    def shots_of(self, *whats, out=None):
        """The captures of these lines, in the order of the log, from the first job that says them all."""
        by_job = collections.defaultdict(list)
        for r in self.records(out):
            if r['ev'] == 'shot' and r.get('what') in whats:
                by_job[r['job']].append(r)
        return next(v for v in by_job.values() if {r['what'] for r in v} == set(whats))

    def test_the_same_show_with_other_arguments_is_a_new_frame(self):
        """One show line run three times with other arguments: the key of the scene is the same each time (tag,
        attributes, the line of the show), the picture is not."""
        hops = self.shots_of('The marker hops to its next spot.')
        self.assertEqual(len(hops), 3)
        self.assertEqual(len({r['frame'] for r in hops}), 3, hops)

    def test_a_screen_that_follows_a_variable_is_a_new_frame(self):
        """A screen of the scene shown once, its text changed by a variable: a new picture, then the same one again
        while nothing changes."""
        one, two, stays = self.shots_of('The tally on the wall reads one.', 'The tally on the wall now reads two.',
                                        'Nothing changes; the tally stays at two.')
        self.assertNotEqual(one['frame'], two['frame'])
        self.assertEqual(two['frame'], stays['frame'])

    def test_hide_tags_hide_python_shows_too(self):
        """hide_tags keeps the caption out of the picture whether the show statement or renpy.show shows it: both
        lines keep the frame of the bare wall before them and log the caption as an effect."""
        bare, stmt, py = self.shots_of('The wall is bare again.', 'A caption hangs here, but the config hides it.',
                                       'The same caption, shown from Python this time.')
        self.assertEqual({stmt['frame'], py['frame']}, {bare['frame']})
        for r in (stmt, py):
            self.assertFalse([s for s in r['shown'] if s.split()[0] == 'caption_card'], r)
            self.assertTrue([f for f in r.get('fx', []) if f.startswith('text:')], r)

    def test_the_nvl_page_is_drawn_with_text_only(self):
        """Without text the NVL page is not drawn, like the dialogue window: Ivy's two lines show the scene alone.
        (Its menu is answered all the same: test_nothing_left_uncaptured finds both pages after it.)"""
        first, second = self.shots_of(*NVL_LINES)
        self.assertEqual(first['frame'], second['frame'])

    SIGNPOST = ('You take the north road, up into the hills.', 'You take the south road, down to the river.',
                'You climb down into the cellar instead.')

    def test_a_called_screen_is_a_menu(self):
        """`call screen signpost`: its buttons that lead on (Return, and Jump on a button known by its alt) are the
        options, every one is taken; a button that leads nowhere and one that cannot be pressed are not options."""
        shots = [r for r in self.records() if r['ev'] == 'shot']
        menus = [r['menu'] for r in shots if (r.get('menu') or {}).get('screen') == 'signpost']
        self.assertTrue(menus)
        self.assertEqual({tuple(m['options']) for m in menus}, {('North road', 'South road', 'The cellar door')})
        self.assertEqual({m['pick'] for m in menus if 'pick' in m}, {0, 1, 2})
        whats = {r.get('what') for r in shots}
        for line in self.SIGNPOST:
            self.assertIn(line, whats)

    def test_a_called_screen_met_again_ends_the_job(self):
        """Back at the signpost from the cellar, as at a hub: nothing is planned for it, so the job ends there rather
        than taking the next road (each road is a job of its own already)."""
        recs = self.records()
        stop = next(r for r in recs if r['ev'] == 'stop')
        self.assertEqual((stop['why'], stop['line']), ('hub', self.signpost_line()))
        shots = [r for r in recs if r['ev'] == 'shot' and r['job'] == stop['job']]
        self.assertEqual(shots[-2]['what'], 'A ladder leads back up to the fork.')
        self.assertEqual(shots[-1]['menu']['screen'], 'signpost')
        self.assertNotIn('pick', shots[-1]['menu'])

    def signpost_line(self):
        lines = read_text(os.path.join(GAME_SRC, 'game', 'script.rpy')).splitlines()
        return lines.index('    call screen signpost') + 1

    def test_a_search_path_beside_the_game(self):
        """The game puts notes/, a folder next to game/, on its search path: the engine runs on the launch folder and
        still reads the note from there."""
        notes = [r for r in self.records() if r['ev'] == 'shot' and r.get('what') == '[torture_note]']
        self.assertTrue(notes)

    def test_records_name_the_games_calls_only(self):
        """The return points in a record are the game's: the call of the job itself (in the capture's own script)
        is not one."""
        recs = [r for r in self.records() if r['ev'] == 'shot']
        self.assertFalse([r for r in recs for f, _ln in r['stack'] if 'renpy_capture' in f])
        self.assertTrue([r for r in recs if r['stack']])           # the shared procedure is still named by its callers

    def test_attributes_in_a_fixed_order(self):
        for r in self.records():
            for s in r.get('shown', []):
                self.assertEqual(s.split()[1:], sorted(s.split()[1:]), r)

    def test_a_second_run_finds_every_job_done(self):
        """Running a finished capture again captures nothing: done.txt is read line by line, an id with a space
        included."""
        again = os.path.join(self.tmp, 'out-resume')
        shutil.copytree(self.out, again)
        with contextlib.redirect_stdout(io.StringIO()):
            runner.run(self.rundir, self.cfg, again, display=DISPLAY, gpu=GPU)
        starts = collections.Counter(r['job'] for r in self.records(again) if r['ev'] == 'start')
        self.assertIn('veteran mode', starts)
        self.assertEqual(set(starts.values()), {1}, starts)

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
    .rpyc files straight into the launch folder's game/, next to the symlinked .rpy of the same name. `link_game`,
    run again at the top of every later `run()` (explore(), prun() and a plain second `run` all make one), used to
    take its own engine's output for a change made by hand and refuse to go on; now it keeps the compiled script."""

    def test_second_link_after_compile_is_refused(self):
        tmp = tempfile.mkdtemp(prefix='renpy-capture-linkbug-')
        try:
            project = os.path.join(tmp, 'project')
            os.makedirs(os.path.join(project, 'game'))
            with open(os.path.join(project, 'game', 'script.rpy'), 'w', encoding='utf-8') as f:
                f.write('label start:\n    "hi"\n    return\n')
            rundir = os.path.join(tmp, 'run')
            with contextlib.redirect_stdout(io.StringIO()):          # first link_game(): all symlinks, succeeds
                runner.setup(project, rundir, version='8.3.2')
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
