"""Several engines at once: the SDK is fetched before the workers start; a worker that stops is reported, and the
jobs the others finished are kept."""
import json
import os
import tempfile
import unittest
from unittest import mock

from renpy_capture import runner


class PrunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rundir = os.path.join(self.tmp.name, 'run')
        os.makedirs(self.rundir)
        with open(os.path.join(self.rundir, runner.RUN_INFO), 'w') as f:
            json.dump({'game': self.tmp.name, 'version': '8.2.3', 'sdk': None, 'exclude': None}, f)
        self.cfg = os.path.join(self.tmp.name, 'cfg.json')
        with open(self.cfg, 'w') as f:
            json.dump({'jobs': [{'id': f'j{i}', 'label': 'start'} for i in range(4)]}, f)
        self.out = os.path.join(self.tmp.name, 'out')
        self.calls = []
        self.patches = [mock.patch.object(runner, 'setup', lambda *a: self.calls.append('setup')),
                        mock.patch.object(runner.sdkmod, 'ensure', lambda v: self.calls.append('ensure')),
                        mock.patch.object(runner, 'report', lambda out: None),
                        mock.patch.object(runner.time, 'sleep', lambda s: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def fake_run(self, stop_at=None):
        def run(rd, wcfg, wout, *a, **kw):
            jobs = [j['id'] for j in runner.read_json(wcfg)['jobs']]
            if stop_at in jobs:
                raise SystemExit('no display')
            with open(os.path.join(wout, 'log.jsonl'), 'w') as f:
                for j in jobs:
                    f.write(json.dumps({'job': j, 'ev': 'end'}) + '\n')
        return run

    def test_the_sdk_is_fetched_once_before_the_workers(self):
        with mock.patch.object(runner, 'run', self.fake_run()):
            runner.prun(self.rundir, self.cfg, self.out, workers=2)
        self.assertEqual(self.calls, ['ensure', 'setup', 'setup'])

    def test_a_stopped_worker_is_reported_and_the_rest_is_kept(self):
        with mock.patch.object(runner, 'run', self.fake_run(stop_at='j3')):
            with self.assertRaises(SystemExit) as cm:
                runner.prun(self.rundir, self.cfg, self.out, workers=2)
        self.assertIn('no display', str(cm.exception.code))
        done = runner.read_text(os.path.join(self.out, 'done.txt')).split()
        self.assertEqual(sorted(done), ['j0', 'j1', 'j2'])   # batches j0+j1, j2, j3: only the last one stopped


if __name__ == '__main__':
    unittest.main()
