"""The command line hands its options to the right function, by name: a reordered signature must not shift them."""
import contextlib
import inspect
import io
import json
import os
import signal
import time
import unittest
from unittest import mock

from renpy_capture import cli, events, runner

ENGINE = ['--timewarp', '2.5', '--display', 'xvfb', '--gpu', 'mesa', '--screen', '800x600', '--fast',
          '--language', 'russian', '--text']


class DispatchTest(unittest.TestCase):
    def call(self, func, argv):
        """The arguments ``func`` of runner got from the command line, every one by its name."""
        got, real = {}, inspect.signature(getattr(runner, func))

        def fake(*a, **kw):
            got.update(real.bind(*a, **kw).arguments)

        with mock.patch.object(runner, func, fake):
            cli.main(argv)
        return got

    def test_run(self):
        got = self.call('run', ['run', 'rd', 'cfg.json', 'out', '--stall', '9'] + ENGINE)
        self.assertEqual(got, dict(rundir='rd', cfg_path='cfg.json', out='out', timewarp=2.5, stall=9.0,
                                   display='xvfb', gpu='mesa', screen='800x600', fast=True, language='russian',
                                   text=True))

    def test_prun(self):
        got = self.call('prun', ['prun', 'rd', 'cfg.json', 'out', '--workers', '3', '--batch', '5'] + ENGINE)
        self.assertEqual(got, dict(rundir='rd', cfg_path='cfg.json', out='out', workers=3, timewarp=2.5, batch=5,
                                   display='xvfb', gpu='mesa', screen='800x600', fast=True, language='russian',
                                   text=True))

    def test_explore(self):
        argv = ['explore', 'rd', 'cfg.json', 'out', '--rounds', '4', '--limit', '77', '--workers', '2',
                '--batch', '6']
        got = self.call('explore', argv + ENGINE)
        self.assertEqual(got, dict(rundir='rd', cfg_path='cfg.json', out='out', rounds=4, timewarp=2.5, limit=77,
                                   workers=2, batch=6, display='xvfb', gpu='mesa', screen='800x600', fast=True,
                                   language='russian', text=True))

    def test_defaults(self):
        got = self.call('explore', ['explore', 'rd', 'cfg.json', 'out'])
        self.assertEqual(got, dict(rundir='rd', cfg_path='cfg.json', out='out', rounds=10, timewarp=4.0, limit=600,
                                   workers=1, batch=8, display=None, gpu=None, screen=None, fast=False,
                                   language=None, text=False))

    def test_explore_passes_the_options_on_to_the_engine(self):
        """explore is the only command that calls another command's function: by name, and the same in both modes."""
        seen = {}
        for workers, func in ((1, 'run'), (3, 'prun')):
            real = inspect.signature(getattr(runner, func))

            def fake(*a, _f=func, _real=real, **kw):
                seen[_f] = _real.bind(*a, **kw).arguments

            with mock.patch.object(runner, func, fake), \
                    mock.patch.object(runner, 'report', lambda out, brief=False: {'jobs': 0, 'lines': 0,
                                                                                   'pictures': 0}), \
                    mock.patch.object(runner, 'read_json', lambda p: {'jobs': []}), \
                    mock.patch.object(runner, 'read_jsonl', lambda p: []), \
                    contextlib.redirect_stdout(io.StringIO()):
                runner.explore('rd', 'cfg.json', 'out', rounds=1, timewarp=2.5, workers=workers, batch=6,
                               display='xvfb', gpu='mesa', screen='800x600', fast=True, language='russian', text=True)
        for func, got in seen.items():
            self.assertEqual((got['timewarp'], got['display'], got['gpu'], got['screen'], got['fast'],
                              got['language'], got['text'], got['quiet']),
                             (2.5, 'xvfb', 'mesa', '800x600', True, 'russian', True, True), func)
        self.assertEqual((seen['prun']['workers'], seen['prun']['batch']), (3, 6))


class ProgressJsonTest(unittest.TestCase):
    """--progress-json: the events on the standard output, the text for a person on the standard error."""

    def run_capture(self, fake, *extra):
        out, err = io.StringIO(), io.StringIO()
        error = None
        with mock.patch('renpy_capture.workflow.capture', fake), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            try:
                cli.main(['capture', 'game', 'work', *extra])
            except BaseException as e:               # SystemExit, or what the capture raised
                error = e
        return out.getvalue(), err.getvalue(), error

    def test_the_streams_are_kept_apart(self):
        def capture(*a, **kw):
            print('launch folder: work/run')
            events.emit('stage', stage='capture')
            print('round 1: 3 jobs')

        out, err, error = self.run_capture(capture, '--progress-json')
        self.assertIsNone(error)
        self.assertEqual([json.loads(line) for line in out.splitlines()], [{'event': 'stage', 'stage': 'capture'}])
        self.assertEqual(err, 'launch folder: work/run\nround 1: 3 jobs\n')
        self.assertFalse(events.active())

    def test_without_it_everything_is_text_on_the_standard_output(self):
        def capture(*a, **kw):
            print('launch folder: work/run')
            events.emit('stage', stage='capture')

        out, err, error = self.run_capture(capture)
        self.assertEqual((out, err, error), ('launch folder: work/run\n', '', None))

    def test_a_command_that_stops_says_why(self):
        def capture(*a, **kw):
            raise SystemExit("cannot tell the game's Ren'Py version")

        out, err, error = self.run_capture(capture, '--progress-json')
        self.assertEqual(error.code, "cannot tell the game's Ren'Py version")
        self.assertEqual([json.loads(line) for line in out.splitlines()],
                         [{'event': 'error', 'message': "cannot tell the game's Ren'Py version"}])

    def test_a_game_that_cannot_be_read_says_so_in_one_line(self):
        def capture(*a, **kw):
            raise ValueError('game: no Ren\'Py game here')

        out, _, error = self.run_capture(capture, '--progress-json')
        self.assertEqual(error.code, "renpy-capture: game: no Ren'Py game here")
        self.assertEqual(json.loads(out)['message'], "renpy-capture: game: no Ren'Py game here")

    def test_a_bug_is_told_and_still_raised(self):
        def capture(*a, **kw):
            raise RuntimeError('boom')

        out, _, error = self.run_capture(capture, '--progress-json')
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(json.loads(out), {'event': 'error', 'message': 'RuntimeError: boom'})

    def test_only_the_commands_that_run_an_engine_have_the_option(self):
        for cmd in ('capture', 'explore', 'run', 'prun'):
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()) as buf:
                cli.main([cmd, '--help'])
            self.assertIn('--progress-json', buf.getvalue(), cmd)
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()) as buf:
            cli.main(['report', '--help'])
        self.assertNotIn('--progress-json', buf.getvalue())


@unittest.skipIf(os.name == 'nt', 'there is no SIGTERM on Windows: the Job Object of the engine does it')
class StopTest(unittest.TestCase):
    def test_a_capture_told_to_stop_ends_through_its_finally_clauses(self):
        """The window's Cancel sends SIGTERM: the engine and the virtual screen are stopped by the `finally` of the
        run, as they are on Ctrl+C."""
        cleaned = []

        def capture(*a, **kw):
            try:
                os.kill(os.getpid(), signal.SIGTERM)
                for _ in range(500):                # the signal arrives long before this ends
                    time.sleep(0.01)
            finally:
                cleaned.append('engine stopped')

        before = signal.getsignal(signal.SIGTERM)
        with mock.patch('renpy_capture.workflow.capture', capture), self.assertRaises(SystemExit) as cm:
            cli.main(['capture', 'game', 'work'])
        self.assertEqual(cm.exception.code, 128 + signal.SIGTERM)
        self.assertEqual(cleaned, ['engine stopped'])
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)       # not left behind for the next command

    def test_a_command_that_runs_no_engine_leaves_the_signal_alone(self):
        before = signal.getsignal(signal.SIGTERM)
        seen = []
        with mock.patch('renpy_capture.analysis.report', lambda out: seen.append(signal.getsignal(signal.SIGTERM))):
            cli.main(['report', 'out'])
        self.assertEqual(seen, [before])


class WindowTest(unittest.TestCase):
    def test_the_window_command_opens_the_window(self):
        with mock.patch('renpy_capture.gui.main') as window:
            cli.main(['gui'])
        window.assert_called_once_with()

    def test_the_window_is_a_gui_script_of_the_package(self):
        """pip makes a launcher of it that opens no console on Windows; the package must hold the code it names."""
        import importlib
        import re
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'pyproject.toml'), encoding='utf-8') as f:
            toml = f.read()
        gui_scripts = toml.split('[project.gui-scripts]')[1].split('[')[0]
        self.assertEqual(re.findall(r'^(\S+) = "(\S+)"', gui_scripts, re.M), [('renpy-capture-gui', 'renpy_capture.gui:main')])
        self.assertTrue(callable(importlib.import_module('renpy_capture.gui').main))
        self.assertIn('"renpy_capture.gui"', toml.split('packages = ')[1].split('\n')[0])


class HelpTest(unittest.TestCase):
    def test_every_command_has_help(self):
        commands = ('capture', 'gui', 'init', 'sdk', 'setup', 'run', 'prun', 'explore', 'report', 'gaps', 'compare',
                    'forget', 'export')
        for cmd in commands:
            buf = io.StringIO()
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(buf):
                cli.main([cmd, '--help'])
            self.assertEqual(cm.exception.code, 0)
            self.assertIn(f'renpy-capture {cmd}', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
