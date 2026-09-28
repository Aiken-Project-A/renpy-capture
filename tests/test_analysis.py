"""Reading a capture's log: the report warns about timed menus the capture had to answer itself."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from renpy_capture import analysis


def shot(seq, line, menu=None):
    r = {'ev': 'shot', 'job': 'j', 'seq': seq, 'label': 'start', 'file': 'game/script.rpy', 'line': line}
    if menu:
        r['menu'] = menu
    return r


class ReportTest(unittest.TestCase):
    def report(self, recs):
        with tempfile.TemporaryDirectory() as out:
            with open(os.path.join(out, 'log.jsonl'), 'w', encoding='utf-8') as f:
                for r in recs:
                    f.write(json.dumps(r) + '\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                analysis.report(out)
            return buf.getvalue()

    def test_a_timed_menu_answered_after_wait_max_is_reported(self):
        waited = {'n': 1, 'options': ['Quick, left', 'Quick, right'], 'wait': True}
        text = self.report([shot(1, 10), shot(2, 12, waited),
                            shot(3, 12, {'n': 1, 'options': ['Quick, left', 'Quick, right'], 'pick': 0}),
                            shot(4, 14), {'ev': 'end', 'job': 'j', 'why': 'end', 'seconds': 1.0}])
        self.assertIn('answered after wait_max', text)
        self.assertIn('j: "Quick, left"', text)

    def test_a_timer_that_led_on_is_not_reported(self):
        waited = {'n': 1, 'options': ['Quick, left', 'Quick, right'], 'wait': True}
        text = self.report([shot(1, 12, waited), shot(2, 14),     # the game's timer ended the menu; the next menu
                            shot(3, 20, {'n': 1, 'options': ['Go on', 'Stay'], 'pick': 0}),   # has the same number
                            {'ev': 'end', 'job': 'j', 'why': 'end', 'seconds': 1.0}])
        self.assertNotIn('wait_max', text)


if __name__ == '__main__':
    unittest.main()
