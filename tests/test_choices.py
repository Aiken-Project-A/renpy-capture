"""The tree of choices (choices.html) built from a log: a branch, a menu met again and again, a menu the game's
timer led on, one answered after wait_max, and how the jobs ended."""
import os
import tempfile
import unittest

from renpy_capture import export


def shot(job, seq, line, menu=None, what=None):
    r = {'ev': 'shot', 'job': job, 'seq': seq, 'label': 'start', 'file': 'game/script.rpy', 'line': line}
    if menu:
        r['menu'] = menu
    if what:
        r['what'] = what
    return r


def menu(n, pick=None, wait=False, caption=None):
    m = {'n': n, 'options': ['Left', 'Right']}
    if pick is not None:
        m['pick'] = pick
    if wait:
        m['wait'] = True
    if caption:
        m['caption'] = caption
    return m


class ChoicesTest(unittest.TestCase):
    def page(self, log):
        with tempfile.TemporaryDirectory() as d:
            made = export.write_choices(d, log, 'game')
            path = os.path.join(d, 'choices.html')
            text = open(path, encoding='utf-8').read() if os.path.exists(path) else None
        return made, text

    def test_no_menu_no_page(self):
        made, text = self.page([{'ev': 'start', 'job': 'a', 'label': 'start'}, shot('a', 1, 10, what='Hi.'),
                                {'ev': 'end', 'job': 'a', 'why': 'end'}])
        self.assertFalse(made)
        self.assertIsNone(text)

    def test_branches_repeats_timers_and_ends(self):
        log = [{'ev': 'start', 'job': 'a', 'label': 'start'},
               shot('a', 1, 10, what='Which way?'), shot('a', 2, 11, menu(0, 0)),
               shot('a', 3, 20, menu(1, 1)), shot('a', 4, 20, menu(2, 1)), shot('a', 5, 20, menu(3, 1)),
               shot('a', 6, 30, menu(4, wait=True, caption='Quick!')), shot('a', 7, 31, what='Too late.'),
               {'ev': 'end', 'job': 'a', 'why': 'end'},
               {'ev': 'start', 'job': 'a~1', 'label': 'start'},
               shot('a~1', 1, 10, what='Which way?'), shot('a~1', 2, 11, menu(0, 1)),
               shot('a~1', 3, 40, menu(1, wait=True)), shot('a~1', 4, 40, menu(1, 0)),
               {'ev': 'stop', 'job': 'a~1', 'why': 'label', 'label': 'hub'}, {'ev': 'end', 'job': 'a~1', 'why': 'stop'}]
        made, t = self.page(log)
        self.assertTrue(made)
        self.assertIn('2 jobs · 4 menus', t)
        self.assertIn('Which way?', t)                              # the line before a menu without a caption
        self.assertIn('href="index.html#s-a-2">Left</a>', t)        # both options of the branch, where taken
        self.assertIn('href="index.html#s-a~1-2">Right</a>', t)
        self.assertIn(' × 3', t)                                    # the same menu three times: one line
        self.assertIn('Quick!', t)
        self.assertEqual(t.count('own timer'), 1)                   # led on by the game's timer; the other waited
        self.assertIn('href="index.html#s-a~1-4">Left</a>', t)      # menu was answered after wait_max
        self.assertIn('stop (label hub)', t)
        self.assertEqual(t.count('class="end"'), 2)


if __name__ == '__main__':
    unittest.main()
