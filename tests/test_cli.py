"""The command line hands its options to the right function, by name: a reordered signature must not shift them."""
import contextlib
import inspect
import io
import unittest
from unittest import mock

from renpy_capture import cli, runner

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


class HelpTest(unittest.TestCase):
    def test_every_command_has_help(self):
        commands = ('capture', 'init', 'sdk', 'setup', 'run', 'prun', 'explore', 'report', 'gaps', 'compare',
                    'forget', 'export')
        for cmd in commands:
            buf = io.StringIO()
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(buf):
                cli.main([cmd, '--help'])
            self.assertEqual(cm.exception.code, 0)
            self.assertIn(f'renpy-capture {cmd}', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
