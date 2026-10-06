"""Several engines at once: the SDK is fetched before the workers start; a worker that stops is reported, and the
jobs the others finished are kept."""
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
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


class ExploreTest(unittest.TestCase):
    """Rounds of exploring: which jobs a finished capture makes new."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = os.path.join(self.tmp.name, 'cfg.json')
        self.out = os.path.join(self.tmp.name, 'out')
        os.makedirs(self.out)
        self.rounds = 0
        self.patches = [mock.patch.object(runner, 'run', self.fake_run),
                        mock.patch.object(runner, 'report', lambda out, brief=False: {'jobs': 0, 'lines': 0,
                                                                                       'pictures': 0})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def config(self):
        with open(self.cfg, 'w') as f:
            json.dump({'jobs': [{'id': 'start', 'label': 'start'}]}, f)

    def fake_run(self, rundir, cfg, out, *a, **kw):
        """A game with one menu of three options that leads nowhere: a job takes the option its `choices` name."""
        self.rounds += 1
        done = set(runner.read_text(os.path.join(out, 'done.txt')).split()) if \
            os.path.exists(os.path.join(out, 'done.txt')) else set()
        with open(os.path.join(out, 'log.jsonl'), 'a') as f, open(os.path.join(out, 'done.txt'), 'a') as d:
            for job in runner.read_json(cfg)['jobs']:
                if job['id'] in done:
                    continue
                pick = (job.get('choices') or [0])[0]
                f.write(json.dumps({'ev': 'shot', 'job': job['id'], 'seq': 1, 'file': 'game/script.rpy', 'line': 10,
                                    'menu': {'options': ['a', 'b', 'c'], 'pick': pick}}) + '\n')
                d.write(job['id'] + '\n')

    def explore(self, **kw):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            complete = runner.explore(self.tmp.name, self.cfg, self.out, **kw)
        return complete, err.getvalue()

    def test_every_option_of_a_menu_becomes_a_job(self):
        self.config()
        complete, _ = self.explore()
        self.assertTrue(complete)
        self.assertEqual([j['id'] for j in runner.read_json(self.cfg)['jobs']], ['start', 'start~1', 'start~2'])
        self.assertEqual(self.rounds, 2)                # one round to find the menu, one to take its options

    def test_branches_over_the_limit_are_counted_once(self):
        """The branch that did not fit is met again in every round; it is still one branch left out."""
        self.config()
        complete, err = self.explore(limit=2)
        self.assertFalse(complete)
        self.assertIn('1 branches left out', err)
        self.assertEqual([j['id'] for j in runner.read_json(self.cfg)['jobs']], ['start', 'start~1'])


class BatchTest(unittest.TestCase):
    """What a worker's batch brings into the common capture."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src, self.out = os.path.join(self.tmp.name, 'w0'), os.path.join(self.tmp.name, 'out')
        os.makedirs(os.path.join(self.src, 'frames'))
        os.makedirs(os.path.join(self.out, 'frames'))

    def frame(self, folder, name, data):
        with open(os.path.join(folder, 'frames', name + '.png'), 'wb') as f:
            f.write(data)

    def test_records_of_the_finished_jobs_only_and_all_frames(self):
        recs = [{'ev': 'start', 'job': 'a'}, {'ev': 'shot', 'job': 'a', 'frame': 'f1'}, {'ev': 'end', 'job': 'a'},
                {'ev': 'start', 'job': 'b'}, {'ev': 'shot', 'job': 'b', 'frame': 'f2'}]     # b never ended
        self.frame(self.src, 'f1', b'1')
        self.frame(self.src, 'f2', b'2')
        self.frame(self.out, 'f1', b'old')                       # the same picture is already there
        runner.merge_jobs(self.src, self.out, {'a'}, recs)
        self.assertEqual([r['ev'] for r in runner.read_jsonl(os.path.join(self.out, 'log.jsonl'))],
                         ['start', 'shot', 'end'])
        self.assertEqual(runner.read_text(os.path.join(self.out, 'done.txt')).split(), ['a'])
        self.assertEqual(sorted(os.listdir(os.path.join(self.out, 'frames'))), ['f1.png', 'f2.png'])
        self.assertEqual(runner.read_bytes(os.path.join(self.out, 'frames', 'f1.png')), b'old')
        self.assertEqual(os.listdir(os.path.join(self.src, 'frames')), [])       # moved, not copied

    def test_a_second_batch_is_appended(self):
        for job in ('a', 'b'):
            runner.merge_jobs(self.src, self.out, {job}, [{'ev': 'end', 'job': job}])
        self.assertEqual(runner.read_text(os.path.join(self.out, 'done.txt')).split(), ['a', 'b'])
        self.assertEqual(len(runner.read_jsonl(os.path.join(self.out, 'log.jsonl'))), 2)

    def test_an_engine_that_painted_one_flat_colour_is_not_healthy(self):
        def shots(distinct_scenes, distinct_frames):
            return [{'ev': 'shot', 'job': 'a', 'shown': [f'bg {i}'], 'frame': f'f{i % distinct_frames}'}
                    for i in range(distinct_scenes)]
        self.assertTrue(runner.healthy(shots(10, 1)))            # too few scenes to tell
        self.assertTrue(runner.healthy(shots(30, 30)))
        self.assertTrue(runner.healthy(shots(30, 12)))           # 0.4 frames per scene is the least
        self.assertFalse(runner.healthy(shots(30, 11)))
        self.assertFalse(runner.healthy(shots(30, 1)))
        same = [dict(r, same=True) for r in shots(30, 1)]        # a scene that did not change is not a new one
        self.assertTrue(runner.healthy(same))


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = self.tmp.name

    def log(self, path, *recs, mode='a'):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f:
            for r in recs:
                f.write((r if isinstance(r, str) else json.dumps(r)) + '\n')

    def line(self, bar):
        with mock.patch.object(runner.sys.stdout, 'isatty', lambda: False):
            return bar.line()

    def test_jobs_done_lines_and_the_job_under_way(self):
        bar = runner.Progress(self.out, 3)
        main = os.path.join(self.out, 'log.jsonl')
        self.assertEqual(self.line(bar), '  0 of 3 jobs done, 0 lines, starting')
        self.log(main, {'ev': 'start', 'job': 'a'}, {'ev': 'shot', 'job': 'a'}, {'ev': 'shot', 'job': 'a'})
        self.assertEqual(self.line(bar), '  0 of 3 jobs done, 2 lines, now a')
        self.log(main, {'ev': 'end', 'job': 'a'}, {'ev': 'start', 'job': 'b'})
        self.log(os.path.join(self.out, 'done.txt'), 'a')
        self.assertEqual(self.line(bar), '  1 of 3 jobs done, 2 lines, now b')

    def test_a_record_still_being_written_waits_for_the_next_look(self):
        bar = runner.Progress(self.out, 1)
        main = os.path.join(self.out, 'log.jsonl')
        self.log(main, {'ev': 'shot', 'job': 'a'})
        with open(main, 'a') as f:
            f.write('{"ev": "sho')
        self.assertIn('1 line,', self.line(bar))
        with open(main, 'a') as f:
            f.write('t", "job": "a"}\n')
        self.assertIn('2 lines,', self.line(bar))

    def test_engines_at_work_and_a_batch_already_merged_is_not_counted_twice(self):
        bar = runner.Progress(self.out, 4)
        for k in (0, 1):
            self.log(os.path.join(self.out, 'work', f'w{k}', 'log.jsonl'), {'ev': 'start', 'job': f'j{k}'},
                     {'ev': 'shot', 'job': f'j{k}'})
        self.assertEqual(self.line(bar), '  0 of 4 jobs done, 2 lines, 2 engines at work')
        self.log(os.path.join(self.out, 'log.jsonl'), {'ev': 'shot', 'job': 'j0'}, {'ev': 'end', 'job': 'j0'})
        self.log(os.path.join(self.out, 'done.txt'), 'j0')
        self.assertEqual(self.line(bar), '  1 of 4 jobs done, 2 lines, now j1')


class SizeTest(unittest.TestCase):
    def test_screen_sizes(self):
        self.assertEqual(runner._parse_size(None), runner.SCREEN)
        self.assertEqual(runner._parse_size('1280x720'), (1280, 720))
        self.assertEqual(runner._parse_size([800, '600']), (800, 600))
        with self.assertRaises(SystemExit):
            runner._parse_size('big')


LINUX_ONLY = unittest.skipIf(os.name == 'nt', 'Linux displays and drivers')


@LINUX_ONLY
class DisplayTest(unittest.TestCase):
    def test_an_x_server_that_does_not_start_points_to_the_log_that_exists(self):
        """Xvfb closes the descriptor without a display number when it dies at once; its words are in display.log."""
        popen = mock.Mock(return_value=mock.Mock())
        with mock.patch.object(runner.subprocess, 'Popen', popen), \
                mock.patch.object(runner, 'kill_group') as killed:
            with self.assertRaises(SystemExit) as cm:
                runner.Xvfb('rundir', {}, (640, 480)).start('inner', None)
        self.assertIn('display.log', str(cm.exception.code))
        self.assertNotIn('kwin.log', str(cm.exception.code))
        killed.assert_called_once()

    def test_cleaning_up_a_compositor_that_never_started_is_quiet(self):
        with tempfile.TemporaryDirectory() as rt, mock.patch.dict(os.environ, {'XDG_RUNTIME_DIR': rt}):
            k = runner.KWin('rundir', {}, (640, 480))
            k.cleanup()                                     # no socket yet: nothing to remove, nothing to hide
            k.sock = 'renpy-capture-test'
            for name in (k.sock, k.sock + '.lock'):
                open(os.path.join(rt, name), 'w').close()
            k.cleanup()
            self.assertEqual(os.listdir(rt), [])
            k.cleanup()                                     # already gone


class LaunchTest(unittest.TestCase):
    """What the engine is started with, and what is cleared before it starts."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rundir = os.path.join(self.tmp.name, 'run')
        os.makedirs(os.path.join(self.rundir, 'game', 'saves'))
        self.game = os.path.join(self.tmp.name, 'MyGame')
        os.makedirs(os.path.join(self.game, 'game'))
        self.info = {'game': self.game, 'version': '8.2.3', 'sdk': None, 'exclude': None}
        self.disp = runner.Xvfb(self.rundir, {}, (640, 480))
        if runner.WINDOWS:
            self.disp = runner.WinWindow(self.rundir, {}, (640, 480))

    def env(self, **kw):
        args = dict(timewarp=4.0, fast=False, text=False, language=None)
        args.update(kw)
        with mock.patch.object(runner, 'game_dir', lambda g: os.path.join(self.game, 'game')):
            return runner._engine_env(self.info, self.rundir, 'cfg.json', 'out', self.disp, {'VENDOR': 'mesa'},
                                      **args)

    def test_the_switches_of_the_capture(self):
        env = self.env(timewarp=2.5, fast=True, text=True)
        self.assertEqual(env['RENPY_TIMEWARP'], '2.5')
        self.assertEqual((env['RENPY_CAPTURE_FAST'], env['RENPY_CAPTURE_TEXT']), ('1', '1'))
        self.assertEqual(env['RENPY_CAPTURE_CONFIG'], os.path.abspath('cfg.json'))
        self.assertEqual(env['RENPY_CAPTURE_OUT'], os.path.abspath('out'))
        self.assertEqual(env['HOME'], os.path.join(self.rundir, 'home'))
        self.assertEqual(env['RENPY_CAPTURE_BASE'], self.game)     # the game's folder, not the launch folder
        self.assertTrue(env['PATH'].startswith(os.path.join(self.rundir, 'bin') + os.pathsep))
        self.assertEqual(env['VENDOR'], 'mesa')                     # the GPU vendor's
        if not runner.WINDOWS:
            self.assertEqual(env['SDL_VIDEODRIVER'], 'x11')         # the display's
        self.assertEqual((self.env()['RENPY_CAPTURE_FAST'], self.env()['RENPY_CAPTURE_TEXT']), ('0', '0'))
        self.assertNotIn('RENPY_LANGUAGE', env)
        self.assertNotIn('LD_LIBRARY_PATH', env)

    def test_a_language_the_game_does_not_have_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            self.env(language='russian')
        self.assertIn('russian', str(cm.exception.code))
        os.makedirs(os.path.join(self.game, 'game', 'tl', 'russian'))
        self.assertEqual(self.env(language='russian')['RENPY_LANGUAGE'], 'russian')

    def test_live2d_core_of_the_game_is_linked_for_the_engine(self):
        if runner.WINDOWS:
            self.skipTest('Linux: the shared library; see WindowsLaunchTest')
        lib = os.path.join(self.game, 'lib', 'py3-linux-x86_64')
        os.makedirs(lib)
        open(os.path.join(lib, 'libLive2DCubismCore.so'), 'w').close()
        env = self.env()
        self.assertEqual(env['LD_LIBRARY_PATH'], os.path.join(os.path.abspath(self.rundir), 'live2d'))
        self.assertTrue(os.path.islink(os.path.join(env['LD_LIBRARY_PATH'], 'libLive2DCubismCore.so')))
        self.env()                                                  # again: the link is there already

    def test_the_launcher_runs_the_sdk_on_the_launch_folder_under_that_environment(self):
        if runner.WINDOWS:
            self.skipTest('Linux: a shell script; see WindowsLaunchTest')
        with mock.patch.object(runner.os, 'getpriority', lambda *a: 0):
            inner = runner._write_launcher(self.rundir, '/sdk dir', self.disp, {'A': 'x y', 'B': '1'}, 'out/renpy.log')
        self.assertTrue(os.access(inner, os.X_OK))
        text = runner.read_text(inner)
        self.assertEqual(text.splitlines()[0], '#!/bin/sh')
        self.assertIn("exec env -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS A='x y' B=1 '/sdk dir/renpy.sh' ", text)
        self.assertTrue(text.rstrip().endswith(f">> {os.path.abspath('out/renpy.log')} 2>&1"))

    def test_the_engine_gets_the_niceness_of_the_capture_back(self):
        if runner.WINDOWS:
            self.skipTest('Linux: a shell script; see WindowsLaunchTest')
        sdk, seen = os.path.join(self.tmp.name, 'sdk'), os.path.join(self.tmp.name, 'nice.txt')
        os.makedirs(sdk)
        with open(os.path.join(sdk, 'renpy.sh'), 'w') as f:      # an engine that tells its niceness
            f.write(f'#!/bin/sh\nnice > {seen}\n')
        os.chmod(os.path.join(sdk, 'renpy.sh'), 0o755)
        want = min(max(os.getpriority(os.PRIO_PROCESS, 0), 0) + 7, 19)     # (the tests may run at a negative one)
        with mock.patch.object(runner.os, 'getpriority', lambda *a: want):     # the capture was started with nice
            inner = runner._write_launcher(self.rundir, sdk, self.disp, {}, os.path.join(self.tmp.name, 'r.log'))
        subprocess.run([inner], check=True)         # started at another niceness, as KWin starts it at its own
        self.assertEqual(runner.read_text(seen).strip(), str(want))

    def test_a_launch_starts_from_default_persistent_data_and_no_old_traceback(self):
        saves = os.path.join(self.rundir, 'game', 'saves')
        home = os.path.join(self.rundir, 'home', '.renpy', 'MyGame-1')
        os.makedirs(home)
        keep = os.path.join(saves, '1-1-LT1.save')
        gone = [os.path.join(saves, 'persistent'), os.path.join(home, 'persistent'),
                os.path.join(self.rundir, 'traceback.txt'), os.path.join(self.rundir, 'errors.txt')]
        for p in gone + [keep]:
            open(p, 'w').close()
        runner._fresh_start(self.rundir, '/no/sdk')
        self.assertEqual([p for p in gone if os.path.exists(p)], [])
        self.assertTrue(os.path.exists(keep))

    @LINUX_ONLY                     # (on Windows the engine's Job Object dies with the capture)
    def test_an_engine_left_by_a_killed_capture_is_stopped_first(self):
        """A capture killed outright (SIGTERM, a closed terminal) leaves its engine running on the launch folder,
        writing into the same output as the next capture: a launch stops it first, and only it."""
        sdk = os.path.join(self.tmp.name, 'sdk')
        sleep = [sys.executable, '-c', 'import time; time.sleep(60)', os.path.join(sdk, 'lib', 'py3', 'renpy')]
        left = subprocess.Popen(sleep + [self.rundir])
        other = subprocess.Popen(sleep + [self.rundir + '-w0'])        # a worker's folder is another one
        self.addCleanup(other.kill)
        self.addCleanup(left.kill)
        runner._fresh_start(self.rundir, sdk)
        self.assertEqual(left.wait(10), -signal.SIGKILL)
        self.assertIsNone(other.poll())


class WindowsLaunchTest(LaunchTest):
    """What the engine is started with on Windows, on any system: no shell between, saves and persistent data in the
    launch folder, no editor, the window does not take the keyboard."""

    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(runner, 'WINDOWS', True), mock.patch.object(runner.sdkmod, 'WINDOWS', True)):
            p.start()
            self.addCleanup(p.stop)
        self.disp = runner.WinWindow(self.rundir, {}, (640, 480))

    def test_saves_and_persistent_data_stay_in_the_launch_folder(self):
        env = self.env()
        home = os.path.join(os.path.abspath(self.rundir), 'home')
        self.assertEqual(env['APPDATA'], home)
        self.assertEqual(env['RENPY_PATH_TO_SAVES'], os.path.join(home, '.renpy'))
        self.assertEqual(env['RENPY_EDIT_PY'], os.path.join(os.path.abspath(self.rundir), 'bin', runner.NO_EDITOR))
        self.assertEqual(env['SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN'], '1')
        self.assertNotIn('SDL_VIDEODRIVER', env)

    def test_live2d_core_of_the_game_is_on_the_path(self):
        lib = os.path.join(self.game, 'lib', 'py3-windows-x86_64')
        os.makedirs(lib)
        with open(os.path.join(lib, 'Live2DCubismCore.dll'), 'wb') as f:
            f.write(b'MZ')
        env = self.env()
        l2d = os.path.join(os.path.abspath(self.rundir), 'live2d')
        self.assertTrue(env['PATH'].startswith(l2d + os.pathsep))
        self.assertTrue(os.path.samefile(os.path.join(l2d, 'Live2DCubismCore.dll'),
                                         os.path.join(lib, 'Live2DCubismCore.dll')))
        self.assertNotIn('LD_LIBRARY_PATH', env)
        self.env()                                                  # again: the link is there already

    def test_the_engine_is_started_without_a_shell(self):
        sdk = os.path.join(self.tmp.name, 'sdk')
        exe = os.path.join(sdk, 'lib', 'py3-windows-x86_64', 'renpy.exe')
        os.makedirs(os.path.dirname(exe))
        open(exe, 'wb').close()
        with mock.patch.dict(os.environ, {'KEEP': 'me', 'DROP': 'me'}):
            self.disp.unset = ('DROP',)
            launch = runner._launcher(self.rundir, sdk, self.disp, {'A': 'x y'}, 'out/renpy.log')
        self.assertEqual(launch.cmd, [exe, os.path.abspath(self.rundir)])
        self.assertEqual((launch.env['A'], launch.env['KEEP']), ('x y', 'me'))  # the whole environment: Windows
        self.assertNotIn('DROP', launch.env)                                   # needs SYSTEMROOT and the like
        self.assertEqual(launch.log, os.path.abspath('out/renpy.log'))
        self.assertFalse(os.path.exists(os.path.join(self.rundir, '.inner.sh')))

    def test_ren_py_7_has_its_engine_under_py2(self):
        sdk = os.path.join(self.tmp.name, 'sdk7')
        exe = os.path.join(sdk, 'lib', 'py2-windows-x86_64', 'renpy.exe')
        os.makedirs(os.path.dirname(exe))
        open(exe, 'wb').close()
        self.assertEqual(runner.sdkmod.engine(sdk), [exe])
        with self.assertRaises(SystemExit):
            runner.sdkmod.engine(self.tmp.name)

    def test_the_displays_of_windows(self):
        self.assertEqual(runner.default_display(), 'desktop')
        for name, cls in (('window', runner.WinWindow), ('offscreen', runner.WinOffscreen),
                          ('desktop', runner.WinDesktop)):
            self.assertIsInstance(runner.make_display(name, self.rundir, {}, (640, 480)), cls)
        for name in ('kwin', 'xvfb'):
            with self.assertRaises(SystemExit) as cm:
                runner.make_display(name, self.rundir, {}, (640, 480))
            self.assertIn('Windows', str(cm.exception.code))
        with mock.patch('builtins.print'):
            self.assertEqual(runner.vendor_env('nvidia'), {})        # the system chooses the GPU there


@LINUX_ONLY
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
