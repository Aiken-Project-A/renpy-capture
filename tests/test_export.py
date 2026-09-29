"""The pieces of `export` that need no capture: which label a line belongs to, and what the pages say."""
import contextlib
import io
import json
import os
import re
import tempfile
import unittest

from renpy_capture import export
from renpy_capture.util import read_text

SCRIPT = '\n'.join(['# a comment',                     # 1
                    'label start:',                    # 2
                    '    "one"',                       # 3
                    'label _replay_entry:',            # 4
                    '    "two"',                       # 5
                    'label second.part:',              # 6
                    '    "three"',                     # 7
                    '  label indented:',               # 8: a label may be indented
                    '    "four"'])                     # 9


class LabelsTest(unittest.TestCase):
    def setUp(self):
        self.labels = export.Labels({'script.rpy': SCRIPT})

    def test_the_nearest_label_above_the_line(self):
        self.assertIsNone(self.labels('game/script.rpy', 1))       # before the first label
        self.assertEqual(self.labels('game/script.rpy', 2), 'start')
        self.assertEqual(self.labels('game/script.rpy', 3), 'start')
        self.assertEqual(self.labels('game/script.rpy', 5), '_replay_entry')
        self.assertEqual(self.labels('game/script.rpy', 7), 'second.part')
        self.assertEqual(self.labels('game/script.rpy', 900), 'indented')

    def test_the_engine_may_name_a_script_by_its_compiled_file(self):
        self.assertEqual(self.labels('game/script.rpyc', 3), 'start')
        self.assertEqual(self.labels('script.rpy', 3), 'start')

    def test_skipped_labels_give_way_to_the_story_label_above(self):
        aside = re.compile('^_')
        self.assertEqual(self.labels('game/script.rpy', 5, skip=aside), 'start')
        self.assertEqual(self.labels('game/script.rpy', 5), '_replay_entry')     # the same line, asked without skip
        self.assertEqual(self.labels('game/script.rpy', 7, skip=aside), 'second.part')

    def test_no_file_no_line_no_script(self):
        self.assertIsNone(self.labels('', 3))
        self.assertIsNone(self.labels(None, 3))
        self.assertIsNone(self.labels('game/script.rpy', 0))
        self.assertIsNone(self.labels('game/script.rpy', None))
        self.assertIsNone(self.labels('game/other.rpy', 3))


FX_SCRIPT = """\
image glow = "fx/glow.png"
image flash:
    "white.jpg"
    linear 0.5 alpha 0.0
image both:
    add "glow"
    add "pic.WEBP"
screen hud():
    text "hp"
image loop:
    add "loop"
"""


class FxDefsTest(unittest.TestCase):
    """Effects of lines: what each is defined as and which picture files it draws."""

    def defs(self, names, files=()):
        return export.fx_defs({'script.rpy': FX_SCRIPT}, names, files)

    def test_kinds_files_and_definitions(self):
        got = self.defs(['glow', 'flash', 'hud', 'text:Chapter 1', 'unknown', 'fx/x.PNG'])
        self.assertEqual(got['glow'], ('image', ['fx/glow.png'], 'image glow = "fx/glow.png"'))
        self.assertEqual(got['flash'],
                         ('image', ['white.jpg'], 'image flash: ⏎ "white.jpg" ⏎ linear 0.5 alpha 0.0'))
        self.assertEqual(got['hud'][0:2], ('screen', []))
        self.assertEqual(got['text:Chapter 1'], ('caption', [], 'Chapter 1'))
        self.assertEqual(got['unknown'], ('?', [], ''))
        self.assertEqual(got['fx/x.PNG'], ('file', ['fx/x.PNG'], ''))

    def test_an_image_that_adds_another_draws_its_files(self):
        self.assertEqual(self.defs(['both'])['both'][1], ['fx/glow.png', 'pic.WEBP'])

    def test_an_image_that_adds_itself_does_not_loop(self):
        self.assertEqual(self.defs(['loop'])['loop'][1], [])

    def test_an_automatic_image_is_named_after_its_file(self):
        got = self.defs(['smoke'], files=['images/Smoke.jpeg', 'other/smoke.png', 'images/readme.txt'])
        self.assertEqual(got['smoke'], ('?', ['images/Smoke.jpeg'], ''))


class ExportTest(unittest.TestCase):
    """A whole export over a made-up capture: the table, the page, the frames and a translation beside."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        os.makedirs(os.path.join(t, 'MyGame', 'game'))
        with open(os.path.join(t, 'MyGame', 'game', 'script.rpy'), 'w') as f:
            f.write(SCRIPT)
        self.game, self.dest = os.path.join(t, 'MyGame'), os.path.join(t, 'export')

    def capture(self, name, recs):
        out = os.path.join(self.tmp.name, name)
        os.makedirs(os.path.join(out, 'frames'))
        with open(os.path.join(out, 'log.jsonl'), 'w', encoding='utf-8') as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
                if r.get('frame'):
                    with open(os.path.join(out, 'frames', r['frame'] + '.png'), 'wb') as p:
                        p.write(r['frame'].encode())
        return out

    def shot(self, seq, line, what, frame='aa', **kw):
        return dict({'ev': 'shot', 'job': 'start', 'seq': seq, 'file': 'game/script.rpy', 'line': line,
                     'kind': 'Say', 'who': 'e', 'name': 'Eileen', 'what': what, 'frame': frame}, **kw)

    def base(self):
        return self.capture('out', [
            {'ev': 'start', 'job': 'start', 'label': 'start'},
            self.shot(1, 3, 'Hello <b>&</b>'),
            self.shot(2, 5, 'Second', frame='bb', skip=True),
            self.shot(3, 7, None, frame='bb', kind='Menu', who=None, name=None,
                      menu={'options': ['Yes', 'No'], 'pick': 1, 'caption': 'Sure?'}),
            {'ev': 'end', 'job': 'start', 'why': 'end', 'seconds': 1.0}])

    def export(self, out, **kw):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            export.export(out, self.game, self.dest, **kw)
        return buf.getvalue()

    def rows(self):
        with open(os.path.join(self.dest, 'shots.tsv'), encoding='utf-8') as f:
            head, *rows = [line.rstrip('\n').split('\t') for line in f]
        return [dict(zip(head, r)) for r in rows]

    def test_the_table_has_a_row_per_interaction(self):
        text = self.export(self.base())
        self.assertEqual(text.splitlines()[0], 'interactions: 3, frames: 2, effects: 0')
        first, second, menu = self.rows()
        self.assertEqual((first['job'], first['step'], first['file'], first['line'], first['label']),
                         ('start', '1', 'script.rpy', '3', 'start'))
        self.assertEqual((first['who'], first['name'], first['what'], first['frame']),
                         ('e', 'Eileen', 'Hello <b>&</b>', 'aa'))
        self.assertEqual(second['skip'], 'skip')
        self.assertEqual((menu['menu'], menu['caption']), ('Yes | » No', 'Sure?'))

    def test_the_frames_are_placed_once_and_the_page_shows_them(self):
        self.export(self.base())
        self.assertEqual(sorted(os.listdir(os.path.join(self.dest, 'frames'))), ['aa.png', 'bb.png'])
        page = read_text(os.path.join(self.dest, 'index.html'))
        self.assertIn('Hello &lt;b&gt;&amp;&lt;/b&gt;', page)                # the game's text is escaped
        self.assertIn('id="s-start-1"', page)
        self.assertEqual(page.count('<img '), 2)                            # lines 2 and 3 share the frame bb
        self.assertIn('<li class="pick">No</li>', page)
        self.assertTrue(os.path.exists(os.path.join(self.dest, 'choices.html')))

    def test_no_page_leaves_the_table_and_frames_only(self):
        self.export(self.base(), page=False)
        self.assertEqual(sorted(os.listdir(self.dest)), ['frames', 'shots.tsv'])

    def test_a_second_export_over_the_first_is_the_same(self):
        out = self.base()
        self.export(out)
        first = {n: read_text(os.path.join(self.dest, n)) for n in ('shots.tsv', 'index.html', 'choices.html')}
        self.export(out)
        self.assertEqual(first, {n: read_text(os.path.join(self.dest, n)) for n in first})

    def test_a_capture_beside_is_paired_by_job_and_step_until_it_takes_another_way(self):
        out = self.base()
        beside = self.capture('out-ru', [
            {'ev': 'start', 'job': 'start', 'label': 'start', 'language': 'russian'},
            self.shot(1, 3, 'Привет', frame='cc', name='Эйлин'),
            self.shot(2, 6, 'Другая строка', frame='dd')])            # line 6, not 5: another way
        text = self.export(out, beside=beside)
        self.assertIn('start: the capture beside took another way at step 2', text)
        first, second, menu = self.rows()
        self.assertEqual((first['beside_name'], first['beside_what'], first['beside_frame']),
                         ('Эйлин', 'Привет', 'cc'))
        self.assertEqual((second['beside_what'], second['beside_frame'], menu['beside_what']), ('', '', ''))
        self.assertEqual(sorted(os.listdir(os.path.join(self.dest, 'frames'))), ['aa.png', 'bb.png', 'cc.png'])
        page = read_text(os.path.join(self.dest, 'index.html'))
        self.assertIn('beside them: russian', page)
        self.assertIn('From here on russian took another way.', page)


if __name__ == '__main__':
    unittest.main()
