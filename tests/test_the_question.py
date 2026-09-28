"""End to end on "The Question", the sample game every Ren'Py SDK ships: capture it loose and packed into an
archive, check that nothing is left uncaptured, that a second run is identical to the byte, that fast mode draws
fewer frames for the same pictures, and that the export holds every line.

Opt-in (it downloads the SDK once and needs a display backend): RENPY_CAPTURE_IT=1 python -m unittest
tests.test_the_question. RENPY_CAPTURE_IT_VERSION picks the SDK (default 8.3.2), RENPY_CAPTURE_IT_DISPLAY and
RENPY_CAPTURE_IT_GPU the display and GPU.
"""
import contextlib
import html
import io
import os
import re
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

    @classmethod
    def russian(cls):
        """The loose game captured in its Russian translation, once for the tests that need it."""
        game, cfg, rundir, out = cls.out['loose']
        ru = out + '-russian'
        if not os.path.exists(os.path.join(ru, 'done.txt')):
            with contextlib.redirect_stdout(io.StringIO()):
                runner.run(rundir, cfg, ru, display=DISPLAY, gpu=GPU, language='russian')
        return ru

    def test_a_translation_takes_the_same_course(self):
        """The Question ships a Russian translation. Captured in it, every line keeps the script place, label and
        translation id of the original, its text and the place of the text come from game/tl/russian, and the scenes
        are the same to the byte (the text is not part of the frame)."""
        ru = self.russian()
        self.compare(self.out['loose'][3], ru)
        recs = read_jsonl(os.path.join(ru, 'log.jsonl'))
        self.assertEqual({r.get('language') for r in recs if r['ev'] == 'start'}, {'russian'})
        en = [r for r in self.records('loose') if r['ev'] == 'shot']
        tr = {(r['job'], r['seq']): r for r in recs if r['ev'] == 'shot'}
        says = 0
        for a in en:
            b = tr[a['job'], a['seq']]
            self.assertEqual([b.get(k) for k in ('file', 'line', 'label', 'tl')],
                             [a.get(k) for k in ('file', 'line', 'label', 'tl')])
            if a.get('tl'):
                says += 1
                self.assertIsNone(a.get('tl_file'))
                self.assertTrue(b['tl_file'].startswith('game/tl/russian/'), b)
                self.assertRegex(b['what'], '[А-Яа-я]')
        self.assertGreater(says, 50)

    def test_text_keeps_the_dialogue_window_and_menus(self):
        """With text the game's own window and menus are in the frames: every line and every menu gets a frame of its
        own, different from the frame of the scene alone, and a second run is identical to the byte."""
        game, cfg, rundir, out = self.out['loose']
        text, again = out + '-text', out + '-text-again'
        with contextlib.redirect_stdout(io.StringIO()):
            runner.run(rundir, cfg, text, display=DISPLAY, gpu=GPU, text=True)
            runner.run(rundir, cfg, again, display=DISPLAY, gpu=GPU, text=True)
        self.compare(text, again)
        plain = {(r['job'], r['seq']): r for r in self.records('loose') if r['ev'] == 'shot'}
        shots = [r for r in read_jsonl(os.path.join(text, 'log.jsonl')) if r['ev'] == 'shot']
        worded = [r for r in shots if r.get('what') or r.get('menu')]
        self.assertGreater(len(worded), 50)
        for r in worded:
            self.assertNotIn('same', r)
            self.assertNotEqual(r['frame'], plain[r['job'], r['seq']]['frame'], r)
        lines = {(r.get('who'), r['what']) for r in shots if r.get('what')}
        self.assertGreaterEqual(len({r['frame'] for r in shots}), len(lines))

    def test_export_beside_a_translation(self):
        """export --beside: every line of the original with the Russian line of the same step next to it."""
        game, cfg, _rundir, out = self.out['loose']
        dest = os.path.join(self.tmp, 'export-beside')
        with contextlib.redirect_stdout(io.StringIO()):
            export.export(out, game, dest, beside=self.russian())
        rows = read_text(os.path.join(dest, 'shots.tsv')).splitlines()
        header = rows[0].split('\t')
        cells = [dict(zip(header, r.split('\t'))) for r in rows[1:]]
        says = [c for c in cells if c['tl']]
        self.assertGreater(len(says), 50)
        for c in says:
            self.assertRegex(c['beside_what'], '[А-Яа-я]', c)
        self.assertTrue(all(c['beside_menu'] for c in cells if c['menu']))
        page = read_text(os.path.join(dest, 'index.html'))
        self.assertIn('beside them: russian', page)
        self.assertIn(html.escape(says[0]['beside_what']), page)
        self.assertNotIn('took another way', page)

    def test_a_language_the_game_does_not_have(self):
        game, cfg, rundir, out = self.out['loose']
        with self.assertRaises(SystemExit):
            runner.run(rundir, cfg, out + '-klingon', display=DISPLAY, gpu=GPU, language='klingon')

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
        self.assertIn('href="choices.html"', page)
        tree = read_text(os.path.join(dest, 'choices.html'))        # the tree of choices: every option of every menu,
        links = re.findall(r'href="index.html#([^"]+)"', tree)        # each one a link to a step of the page
        self.assertTrue(links)
        for a in links:
            self.assertIn(f'id="{a}"', page)
        for m in (r['menu'] for r in shots if r.get('menu')):
            for o in m['options']:
                self.assertIn(html.escape(o), tree)


if __name__ == '__main__':
    unittest.main()
