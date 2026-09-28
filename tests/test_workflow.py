"""The work folder of `capture`: where each capture and its pages go."""
import os
import unittest

from renpy_capture.util import plural
from renpy_capture.workflow import paths


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


if __name__ == '__main__':
    unittest.main()
