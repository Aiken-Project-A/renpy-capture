"""The pieces of `export` that need no capture: which label a line belongs to, and what the pages say."""
import re
import unittest

from renpy_capture import export

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
        self.assertEqual(got['flash'], ('image', ['white.jpg'], 'image flash: ⏎ "white.jpg" ⏎ linear 0.5 alpha 0.0'))
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


if __name__ == '__main__':
    unittest.main()
