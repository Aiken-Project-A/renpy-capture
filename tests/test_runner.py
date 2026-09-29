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
        self.patches = [mock.patch.object(runner, 'setup', lambda *a, **k: self.calls.append('setup')),
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


class VendorTest(unittest.TestCase):
    """Choosing a GPU vendor keeps every graphics API on it: loading NVIDIA's driver alone wakes a sleeping NVIDIA
    GPU (found on a laptop with runtime D3: Xvfb woke it through EGL, KWin through Vulkan)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        files = {k: os.path.join(self.tmp.name, os.path.basename(v)) for k, v in runner.EGL.items()}
        for f in files.values():
            open(f, 'w').close()
        self.drm = os.path.join(self.tmp.name, 'drm')         # a laptop: AMD graphics and an NVIDIA card
        self.gpu('renderD128', 'amdgpu')
        self.gpu('renderD129', 'nvidia')
        self.patches = [mock.patch.dict(runner.EGL, files), mock.patch.object(runner, 'DRM_SYSFS', self.drm)]
        for p in self.patches:
            p.start()

    def gpu(self, node, driver):
        drivers = os.path.join(self.tmp.name, 'drivers', driver)
        os.makedirs(drivers, exist_ok=True)
        os.makedirs(os.path.join(self.drm, node, 'device'))
        os.symlink(drivers, os.path.join(self.drm, node, 'device', 'driver'))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_mesa_hides_nvidia_from_egl_glx_vulkan_and_kwin(self):
        env = runner.vendor_env('mesa')
        self.assertEqual(env['__EGL_VENDOR_LIBRARY_FILENAMES'], runner.EGL['mesa'])
        self.assertEqual(env['__GLX_VENDOR_LIBRARY_NAME'], 'mesa')
        self.assertEqual(env['VK_LOADER_DRIVERS_DISABLE'], '*nvidia*')
        self.assertEqual(env['KWIN_DISABLE_VULKAN'], '1')        # KWin with capabilities: the loader ignores the above
        self.assertEqual(env['KWIN_RENDER_NODES'], '/dev/dri/renderD128')

    def test_nvidia_and_auto(self):
        env = runner.vendor_env('nvidia')
        self.assertEqual(env['__GLX_VENDOR_LIBRARY_NAME'], 'nvidia')
        self.assertNotIn('VK_LOADER_DRIVERS_DISABLE', env)
        self.assertNotIn('KWIN_DISABLE_VULKAN', env)
        self.assertEqual(env['KWIN_RENDER_NODES'], '/dev/dri/renderD129')
        self.assertEqual(runner.vendor_env('auto'), {})

    def test_no_gpu_of_the_vendor_leaves_kwin_to_choose(self):
        self.assertEqual(runner.render_nodes('nvidia'), ['/dev/dri/renderD129'])
        os.remove(os.path.join(self.drm, 'renderD129', 'device', 'driver'))
        os.rmdir(os.path.join(self.drm, 'renderD129', 'device'))
        os.rmdir(os.path.join(self.drm, 'renderD129'))
        self.assertNotIn('KWIN_RENDER_NODES', runner.vendor_env('nvidia'))

    def test_no_vendor_file_leaves_the_choice_to_the_system(self):
        os.remove(runner.EGL['mesa'])
        with mock.patch('builtins.print'):
            self.assertEqual(runner.vendor_env('mesa'), {})

    def test_the_x_server_gets_the_vendor_too(self):
        calls = []

        def popen(cmd, **kw):
            calls.append(kw.get('env'))
            if '-displayfd' in cmd:                        # Xvfb tells its display number through this descriptor
                os.write(int(cmd[cmd.index('-displayfd') + 1]), b'7\n')
            return mock.Mock()

        genv = runner.vendor_env('mesa')
        with mock.patch.object(runner.subprocess, 'Popen', popen):
            runner.Xvfb(self.tmp.name, genv, (640, 480)).start('inner', None)
        server, engine = calls
        for k, v in genv.items():
            self.assertEqual(server[k], v)
        self.assertEqual(engine['DISPLAY'], ':7')


if __name__ == '__main__':
    unittest.main()
