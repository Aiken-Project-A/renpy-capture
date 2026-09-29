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


class GapsScopeTest(unittest.TestCase):
    """`gaps` closes the branches that gaps_scope decides. The conditions are the game's text: it must never run
    them as code."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = os.path.join(self.tmp.name, 'game')
        os.makedirs(self.game)
        os.makedirs(os.path.join(self.tmp.name, 'out'))

    def gaps(self, conditions, scope):
        """{condition: (its branch is a gap, its else branch is a gap)} for a script with one label per condition."""
        lines = []
        for i, c in enumerate(conditions):
            lines += [f'label l{i}:', f'    if {c}:', f'        scene bg then{i}', '        "x"', '    else:',
                      f'        scene bg else{i}', '        "y"', '    return']
        with open(os.path.join(self.game, 'script.rpy'), 'w') as f:
            f.write('\n'.join(lines) + '\n')
        cfg = os.path.join(self.tmp.name, 'cfg.json')
        with open(cfg, 'w') as f:
            json.dump({'gaps_scope': scope}, f)
        found = analysis.gaps(self.game, cfg, os.path.join(self.tmp.name, 'out'), show=False)
        seen = {spec for xs in found.values() for _, spec in xs}
        return {c: (f'bg then{i}' in seen, f'bg else{i}' in seen) for i, c in enumerate(conditions)}

    def test_a_branch_the_scope_closes_is_not_a_gap(self):
        scope = {'a': True, 'b': False, 'n': 3, 's': 'hi', 'd': {'k': 2}}
        want = {'a': (True, False), 'not a': (False, True), 'b': (False, True), 'a and b': (False, True),
                'a or x': (True, False), 'b and x': (False, True), 'x or b': (True, True),
                'n == 3': (True, False), 'n in (1, 2, 3)': (True, False), '1 < n < 3': (False, True),
                's != "hi"': (False, True), 'n + 1 == 4': (True, False), 'n * 2 == 6': (True, False),
                'd["k"] == 2': (True, False), 'a if b else b': (False, True),
                'unrelated': (True, True)}                      # no name of the scope in it: both stay open
        self.assertEqual(self.gaps(list(want), scope), want)

    def test_a_condition_is_not_executed(self):
        marker = os.path.join(self.tmp.name, 'pwned')
        # the classic way out of eval(..., {'__builtins__': {}}): through the classes every object knows
        evil = ('a and [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == "_wrap_close"][0]'
                f'.__init__.__globals__["system"]("touch {marker}")')
        self.gaps([evil], {'a': True})
        self.assertFalse(os.path.exists(marker))


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
