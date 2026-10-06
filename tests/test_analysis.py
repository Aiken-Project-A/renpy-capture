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


class GapsFlowTest(unittest.TestCase):
    """Which captures count for a scene line: the lines the game goes through after it."""

    def test_the_flow_goes_on_into_a_statement_at_the_top_level(self):
        """The Ren'Py Tutorial ends a label's body with a show and goes on into a statement of its own at the top
        level (`example nvl3 hide:`), whose block holds the next menu: the menu's capture counts for the show. A
        declaration at the top level (a screen, an image) is not run in the flow: a show before it is still a gap."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'game'))
            os.makedirs(os.path.join(tmp, 'out'))
            with open(os.path.join(tmp, 'game', 'script.rpy'), 'w') as f:
                f.write('label start:\n    "one"\n    show bg flow\n\nexample nvl3 hide:\n    menu:\n'
                        '        "Yes":\n            pass\n\nlabel other:\n    "two"\n    show bg decl\n\n'
                        'screen s():\n    text "x"\n    "three"\n')
            with open(os.path.join(tmp, 'out', 'log.jsonl'), 'w') as f:
                for line in (2, 6, 11, 16):
                    f.write(json.dumps(dict(shot(line, line), file='game/script.rpy')) + '\n')
            cfg = os.path.join(tmp, 'cfg.json')
            with open(cfg, 'w') as f:
                json.dump({}, f)
            found = analysis.gaps(os.path.join(tmp, 'game'), cfg, os.path.join(tmp, 'out'), show=False)
        self.assertEqual({spec for xs in found.values() for _, spec in xs}, {'bg decl'})


class CompareTest(unittest.TestCase):
    def out(self, recs):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        with open(os.path.join(d.name, 'log.jsonl'), 'w', encoding='utf-8') as f:
            for r in recs:
                f.write(json.dumps(r) + '\n')
        return d.name

    def compare(self, a, b, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return analysis.compare(a, b, **kw), buf.getvalue()

    def test_a_job_without_an_end_is_compared_too(self):
        """An engine that died mid-job leaves shots and no `end`: that is when two runs are compared most."""
        a = self.out([shot(1, 10)])
        ok, text = self.compare(a, self.out([shot(1, 10)]))
        self.assertTrue(ok, text)
        self.assertIn('job time: 0 s / 0 s', text)

    def test_the_same_run_matches_and_another_scene_does_not(self):
        a = self.out([shot(1, 10), shot(2, 12)])
        ok, text = self.compare(a, self.out([shot(1, 10), shot(2, 12)]))
        self.assertTrue(ok, text)
        ok, text = self.compare(a, self.out([shot(1, 10), shot(2, 14)]))
        self.assertFalse(ok)
        self.assertIn('scene state', text)

    def test_a_different_frame_of_a_scene_at_rest_counts_but_of_an_animation_does_not(self):
        def framed(frame, **kw):
            return [dict(shot(1, 10), frame=frame, **kw)]
        self.assertFalse(self.compare(self.out(framed('aa')), self.out(framed('bb')))[0])
        self.assertTrue(self.compare(self.out(framed('aa', anim=True)), self.out(framed('bb')))[0])
        self.assertTrue(self.compare(self.out(framed('aa')), self.out(framed('bb')), frames=False)[0])

    def test_two_captures_that_are_not_there_do_not_match(self):
        nowhere = os.path.join(tempfile.gettempdir(), 'renpy-capture-no-such-capture')
        ok, text = self.compare(nowhere, nowhere + '-either')
        self.assertFalse(ok)
        self.assertIn('nothing to compare', text)


class ForgetTest(unittest.TestCase):
    def test_jobs_leave_the_log_and_the_done_list_and_the_others_stay_as_written(self):
        with tempfile.TemporaryDirectory() as out:
            log = [{'ev': 'start', 'job': 'a', 'label': 'é'}, {'ev': 'end', 'job': 'a'},
                   {'ev': 'start', 'job': 'b'}, {'ev': 'end', 'job': 'b'}]
            with open(os.path.join(out, 'log.jsonl'), 'w', encoding='utf-8') as f:
                f.writelines(json.dumps(r, ensure_ascii=False) + '\n' for r in log)
            with open(os.path.join(out, 'done.txt'), 'w') as f:
                f.write('a\nb\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                analysis.forget(out, ['a', 'nothing'])
            with open(os.path.join(out, 'log.jsonl'), encoding='utf-8') as f:
                self.assertEqual(f.read(), ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in log[2:]))
            with open(os.path.join(out, 'done.txt')) as f:
                self.assertEqual(f.read(), 'b\n')
            self.assertEqual(buf.getvalue(), 'log.jsonl: 2 records removed\ndone.txt: 1 records removed\n')
            self.assertEqual(sorted(os.listdir(out)), ['done.txt', 'log.jsonl'])        # no .new left behind

    def test_a_capture_without_a_log_is_left_alone(self):
        with tempfile.TemporaryDirectory() as out, contextlib.redirect_stdout(io.StringIO()):
            analysis.forget(out, ['a'])
            self.assertEqual(os.listdir(out), [])


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

    def test_the_error_of_a_job_is_its_own_line_not_the_platform_tail(self):
        trace = ('Traceback (most recent call last):\n  File "game/script.rpy", line 3\nNameError: name \'x\' is not '
                 'defined\n\nWindows-10-10.0.19045 Ren\'Py 8.2.3\nMon Jan  1 00:00:00 2024\n')
        text = self.report([shot(1, 3), {'ev': 'error', 'job': 'j', 'error': trace},
                            {'ev': 'end', 'job': 'j', 'why': 'error', 'seconds': 1.0}])
        self.assertIn("error: NameError: name 'x' is not defined", text)
        self.assertNotIn('Windows', text)

    def test_a_bare_exception_is_the_error_line_too(self):
        """Ren'Py raises plain Exception for a missing file or font: that line, not the date at the end."""
        trace = ('  File "renpy/text/font.py", line 673, in load_face\n    raise Exception("Could not find font")\n'
                 "Exception: Could not find font 'Roboto-Light.ttf'.\n\nLinux-6.1 x86_64\nRen'Py 8.3.2\n"
                 'Tue Oct  6 09:35:40 2026\n')
        text = self.report([shot(1, 3), {'ev': 'error', 'job': 'j', 'error': trace},
                            {'ev': 'end', 'job': 'j', 'why': 'error', 'seconds': 1.0}])
        self.assertIn("error: Exception: Could not find font 'Roboto-Light.ttf'.", text)
        self.assertNotIn('2026', text)

    def test_an_ignored_error_is_marked_and_not_counted(self):
        recs = [shot(1, 3), {'ev': 'error', 'job': 'j', 'error': 'ValueError: x', 'ignored': True},
                {'ev': 'end', 'job': 'j', 'why': 'end', 'seconds': 1.0}]
        with tempfile.TemporaryDirectory() as out:
            with open(os.path.join(out, 'log.jsonl'), 'w') as f:
                f.writelines(json.dumps(r) + '\n' for r in recs)
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                totals = analysis.report(out)
                brief = analysis.report(out, brief=True)
        self.assertIn('error: ignored: ValueError: x', buf.getvalue())
        self.assertEqual((totals['errors'], totals['lines'], totals['pictures']), ([], 1, 0))
        self.assertEqual(brief['errors'], [])

    def test_a_missing_log_is_said_not_raised(self):
        with tempfile.TemporaryDirectory() as out, contextlib.redirect_stdout(io.StringIO()) as buf:
            totals = analysis.report(out)
        self.assertIn('no log', buf.getvalue())
        self.assertEqual(totals['jobs'], 0)

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

    def totals(self, recs):
        with tempfile.TemporaryDirectory() as out, contextlib.redirect_stdout(io.StringIO()):
            with open(os.path.join(out, 'log.jsonl'), 'w', encoding='utf-8') as f:
                f.writelines(json.dumps(r) + '\n' for r in recs)
            return analysis.report(out, brief=True)

    def test_the_warnings_come_as_data_for_a_program_that_words_them_itself(self):
        waited = {'n': 1, 'options': ['Quick, left', 'Quick, right'], 'wait': True}
        totals = self.totals([shot(1, 10), shot(2, 12, waited),
                              shot(3, 12, {'n': 1, 'options': ['Quick, left', 'Quick, right'], 'pick': 0}),
                              {'ev': 'end', 'job': 'j', 'why': 'end', 'seconds': 1.0}])
        self.assertEqual(totals['warnings'], [{'kind': 'late', 'menus': 1}])

    def test_an_overlay_that_never_stops_and_a_slow_engine_are_warnings_too(self):
        moving = [dict(shot(n, 3), anim=True) for n in range(1, 31)]
        totals = self.totals(moving + [{'ev': 'end', 'job': 'j', 'why': 'end', 'seconds': 90.0}])
        self.assertEqual(totals['warnings'], [{'kind': 'moving', 'moving': 30, 'steps': 30},
                                              {'kind': 'slow', 'seconds': 3.0}])
        self.assertEqual(self.totals([shot(1, 3), {'ev': 'end', 'job': 'j', 'why': 'end', 'seconds': 1.0}])['warnings'],
                         [])


if __name__ == '__main__':
    unittest.main()
