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


if __name__ == '__main__':
    unittest.main()
