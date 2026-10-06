"""Windows: the engine and whatever it starts die with the capture (a Job Object), its output goes to the end of its
log, and a desktop of its own runs it. Only on Windows."""
import os
import subprocess
import sys
import tempfile
import time
import unittest

from renpy_capture import runner

if os.name == 'nt':
    import ctypes

    from renpy_capture import winproc

SLEEPER = 'import time; time.sleep(120)'
# a child that starts a grandchild and tells its pid, as an engine could start a program of its own
PARENT = ('import subprocess, sys, time; '
          f'p = subprocess.Popen([sys.executable, "-c", {SLEEPER!r}]); '
          'print(p.pid, flush=True); time.sleep(120)')


def gone(pid, timeout=10):
    """Whether the process ``pid`` has ended (or never was), waiting up to ``timeout`` seconds."""
    SYNCHRONIZE = 0x00100000
    h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not h:
        return True
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(h, int(timeout * 1000)) == 0
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


@unittest.skipUnless(os.name == 'nt', 'Windows')
class JobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, 'out.log')

    def start(self, code, job, desktop=None):
        with open(self.log, 'ab') as out:
            return winproc.start([sys.executable, '-c', code], dict(os.environ), out, job, desktop)

    def grandchild(self):
        for _ in range(200):
            with open(self.log) as f:
                text = f.read().strip()
            if text:
                return int(text)
            time.sleep(0.05)
        self.fail('the child never told its child')

    def test_killing_the_job_kills_what_the_engine_started(self):
        job = winproc.Job()
        p = self.start(PARENT, job)
        kid = self.grandchild()
        job.kill()
        self.assertEqual(p.wait(10), 1)
        self.assertTrue(gone(kid))
        job.close()

    def test_the_job_dies_with_its_last_handle(self):
        """Ctrl+C, a closed console or the task manager end the capture without its finally: the job goes with it."""
        job = winproc.Job()
        p = self.start(PARENT, job)
        kid = self.grandchild()
        job.close()
        self.assertTrue(gone(p.pid) and gone(kid))

    def test_a_desktop_of_its_own(self):
        desk = winproc.Desktop(f'renpy-capture-test-{os.getpid()}')
        job = winproc.Job()
        try:
            p = self.start('import sys; print("on its own desktop"); sys.exit(3)', job, desk.name)
            self.assertEqual(p.wait(30), 3)
            with open(self.log) as f:
                self.assertEqual(f.read().strip(), 'on its own desktop')
            q = self.start(SLEEPER, job, desk.name)
            with self.assertRaises(subprocess.TimeoutExpired):
                q.wait(0.2)
            self.assertIsNone(q.poll())
            job.kill()
            self.assertEqual(q.wait(10), 1)
        finally:
            job.close()
            desk.close()

    def test_the_engine_writes_after_what_its_log_holds(self):
        """The engine gets an OS handle, which knows nothing of Python's append mode: it is put at the end first."""
        with open(self.log, 'w') as f:
            f.write('the first launch\n')
        launch = runner.Launch([sys.executable, '-c', 'print("the second")'], dict(os.environ), self.log)
        disp = runner.WinWindow(self.tmp.name, {}, (640, 480))
        p = disp.start(launch, None)
        p.wait(30)
        disp.stop()
        with open(self.log) as f:
            self.assertEqual(f.read().split('\n')[:2], ['the first launch', 'the second'])


@unittest.skipUnless(os.name == 'nt', 'Windows')
class EnvBlockTest(unittest.TestCase):
    def test_sorted_without_case_and_ended_twice(self):
        self.assertEqual(winproc._env_block({'b': '2', 'A': '1', 'C': 'x y'}), 'A=1\0b=2\0C=x y\0\0')


if __name__ == '__main__':
    unittest.main()
