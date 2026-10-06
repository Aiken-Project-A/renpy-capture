"""The downloads: the SDK cache (one download however many workers ask at once; an SDK folder is either whole or
absent), and unrpyc, kept only when its files are the pinned ones."""
import contextlib
import hashlib
import io
import os
import tarfile
import tempfile
import threading
import time
import unittest
import zipfile
from unittest import mock

from renpy_capture import sdk


def fake_sdk(version, kind='tar.bz2'):
    """A package shaped like an SDK (a .tar.bz2 or a .zip): renpy-<version>-sdk/renpy.sh and one more file."""
    files = ((f'renpy-{version}-sdk/renpy.sh', b'#!/bin/sh\n'), (f'renpy-{version}-sdk/renpy/__init__.py', b''))
    buf = io.BytesIO()
    if kind == 'zip':
        with zipfile.ZipFile(buf, 'w') as z:
            for name, data in files:
                z.writestr(name, data)
        return buf.getvalue()
    with tarfile.open(fileobj=buf, mode='w:bz2') as t:
        for name, data in files:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class SdkTest(unittest.TestCase):
    windows = sdk.WINDOWS                           # the package of this system; WindowsSdkTest: the .zip anywhere

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.name = 'renpy-9.9.9-sdk.zip' if self.windows else 'renpy-9.9.9-sdk.tar.bz2'
        self.tar = fake_sdk('9.9.9', 'zip' if self.windows else 'tar.bz2')
        self.downloads = []

        def urlretrieve(url, path, reporthook=None):
            self.downloads.append(url)
            data = self.tar
            if reporthook:
                reporthook(0, 64, len(data))
            with open(path, 'wb') as f:             # slowly, the way a real download gives every other worker
                for i in range(0, len(data), 64):   # time to arrive meanwhile
                    f.write(data[i:i + 64])
                    f.flush()
                    if reporthook:
                        reporthook(i // 64 + 1, 64, len(data))
                    time.sleep(0.002)

        def urlopen(url):                           # read when the download is done: the sum of what it holds
            return io.BytesIO(f'{hashlib.sha256(self.tar).hexdigest()}  {self.name}\n'.encode())

        self.patches = [mock.patch.dict(os.environ, {'RENPY_CAPTURE_SDK': self.tmp.name}),
                        mock.patch.object(sdk, 'WINDOWS', self.windows),
                        mock.patch.object(sdk.urllib.request, 'urlretrieve', urlretrieve),
                        mock.patch.object(sdk.urllib.request, 'urlopen', urlopen)]
        for p in self.patches:
            p.start()
        self.d = os.path.join(self.tmp.name, 'renpy-9.9.9-sdk')

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_one_download_for_many_workers(self):
        got, errors = [], []

        def ask():
            try:
                got.append(sdk.ensure('9.9.9'))
            except BaseException as e:              # SystemExit too: a thread would drop it silently
                errors.append(e)

        threads = [threading.Thread(target=ask) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual(got, [self.d] * 4)
        self.assertTrue(os.path.isfile(os.path.join(self.d, 'renpy.sh')))
        self.assertEqual(sorted(f for f in os.listdir(self.tmp.name) if not f.endswith('.lock')),
                         ['renpy-9.9.9-sdk', self.name])
        self.assertTrue(self.downloads[0].endswith('/9.9.9/' + self.name))

    def test_a_folder_without_renpy_sh_is_unpacked_again(self):
        os.makedirs(os.path.join(self.d, 'lib'))    # what a cut-off unpack used to leave
        self.assertEqual(sdk.ensure('9.9.9'), self.d)
        self.assertTrue(os.path.isfile(os.path.join(self.d, 'renpy.sh')))
        self.assertFalse(os.path.exists(os.path.join(self.d, 'lib')))

    def test_a_download_that_does_not_match_is_removed(self):
        good = self.tar
        self.tar = self.tar[:-8] + b'\0' * 8        # the checksums still describe the good file

        def urlopen(url):
            return io.BytesIO(f'{hashlib.sha256(good).hexdigest()}  {self.name}\n'.encode())

        with mock.patch.object(sdk.urllib.request, 'urlopen', urlopen), self.assertRaises(SystemExit):
            sdk.ensure('9.9.9')
        self.assertEqual([f for f in os.listdir(self.tmp.name) if not f.endswith('.lock')], [])

    def test_an_unpacked_sdk_is_not_downloaded_again(self):
        sdk.ensure('9.9.9')
        sdk.ensure('9.9.9')
        self.assertEqual(len(self.downloads), 1)

    def test_a_program_that_reads_the_progress_is_told_every_step(self):
        """The download with its size, the check, the unpack (file by file for a .zip), and that it is done."""
        got = []
        always = lambda seconds: (lambda force=False: True)             # no throttling: every update is told
        with mock.patch.object(sdk.events, 'emit', lambda event, **kw: got.append((event, kw))), \
                mock.patch.object(sdk.events, 'Every', always):
            sdk.ensure('9.9.9')
        self.assertEqual({event for event, _ in got}, {'fetch'})
        steps = [kw['step'] for _, kw in got]
        downloads = [kw for _, kw in got if kw['step'] == 'download']
        self.assertEqual((downloads[0]['done'], downloads[0]['total']), (0, len(self.tar)))
        self.assertEqual((downloads[-1]['done'], downloads[-1]['total']), (len(self.tar), len(self.tar)))
        self.assertTrue(all(kw['what'] == 'sdk' and kw['version'] == '9.9.9' for _, kw in got))
        unpacked = [(kw['done'], kw['total']) for _, kw in got if kw['step'] == 'unpack']
        self.assertEqual(unpacked, [(0, None), (1, 2), (2, 2)] if self.windows else [(0, None)])
        self.assertEqual(steps[len(downloads):len(downloads) + 2], ['verify', 'unpack'])
        self.assertEqual(steps[-1], 'done')

    def test_a_download_of_unknown_size_says_so(self):
        got = []

        def urlretrieve(url, path, reporthook=None):
            reporthook(0, 8192, -1)
            reporthook(5, 8192, -1)

        with mock.patch.object(sdk.events, 'emit', lambda event, **kw: got.append(kw)), \
                mock.patch.object(sdk.events, 'Every', lambda seconds: (lambda force=False: True)), \
                mock.patch.object(sdk.urllib.request, 'urlretrieve', urlretrieve):
            sdk._download('https://example.org/x', 'x', 'unrpyc', '1.0')
        self.assertEqual([(kw['done'], kw['total']) for kw in got], [(0, None), (40960, None)])


class WindowsSdkTest(SdkTest):
    """Windows takes the .zip: the same files as the .tar.bz2, unpacked without bzip2."""
    windows = True

    def test_the_cache_is_in_local_app_data(self):
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': self.tmp.name}), mock.patch.dict(os.environ):
            for k in ('RENPY_CAPTURE_SDK', 'XDG_CACHE_HOME'):
                os.environ.pop(k, None)
            self.assertEqual(sdk.cache_root(), os.path.join(self.tmp.name, 'renpy-capture', 'sdk'))
            self.assertEqual(sdk.tools_root(), os.path.join(self.tmp.name, 'renpy-capture', 'tools'))


class LockTest(unittest.TestCase):
    """The lock of _once is the system's own (flock, or msvcrt.locking on Windows): it holds across processes."""

    def test_one_process_at_a_time(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            script = ('import sys, time; from renpy_capture import sdk; '
                      'sdk._once(sys.argv[1], ".x.lock", lambda: False, '
                      'lambda: (open(sys.argv[2], "a").write("in "), time.sleep(0.3), open(sys.argv[2], "a").write("out ")))')
            trace = os.path.join(tmp, 'trace')
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ps = [subprocess.Popen([sys.executable, '-c', script, tmp, trace], cwd=here) for _ in range(3)]
            for p in ps:
                self.assertEqual(p.wait(30), 0)
            with open(trace) as f:
                self.assertEqual(f.read().split(), ['in', 'out'] * 3)


if __name__ == '__main__':
    unittest.main()


def fake_unrpyc(version, extra=b''):
    """A tar.gz shaped like an unrpyc release: unrpyc-<version>/unrpyc.py, decompiler/, LICENSE, a test file."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        for name, data in ((f'unrpyc-{version}/unrpyc.py', b'# unrpyc\n' + extra),
                           (f'unrpyc-{version}/decompiler/__init__.py', b''),
                           (f'unrpyc-{version}/LICENSE', b'MIT\n'),
                           (f'unrpyc-{version}/README.md', b'readme\n')):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class UnrpycTest(unittest.TestCase):
    """unrpyc for games without sources: downloaded once, kept only when its files are the pinned ones."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tar, self.downloads = fake_unrpyc('0.0.1'), []

        def urlretrieve(url, path, reporthook=None):
            self.downloads.append(url)
            with open(path, 'wb') as f:
                f.write(self.tar)

        ref = os.path.join(self.tmp.name, 'ref')
        with tarfile.open(fileobj=io.BytesIO(self.tar)) as t:
            t.extractall(ref)
        self.patches = [mock.patch.dict(os.environ, {'XDG_CACHE_HOME': self.tmp.name}),
                        mock.patch.object(sdk.urllib.request, 'urlretrieve', urlretrieve),
                        mock.patch.object(sdk, 'UNRPYC', ('0.0.1', sdk.content_hash(os.path.join(ref, 'unrpyc-0.0.1'))))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_downloaded_once_and_checked(self):
        with contextlib.redirect_stdout(io.StringIO()):
            d = sdk.unrpyc()
            self.assertEqual(sdk.unrpyc(), d)
        self.assertTrue(os.path.isfile(os.path.join(d, 'unrpyc.py')))
        self.assertEqual(len(self.downloads), 1)
        self.assertIn('/v0.0.1.tar.gz', self.downloads[0])

    def test_other_files_are_refused(self):
        self.tar = fake_unrpyc('0.0.1', extra=b'print("not the release")\n')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ImportError):
            sdk.unrpyc()
        self.assertEqual([n for n in os.listdir(sdk.tools_root()) if not n.startswith('.unrpyc')], [])

    def test_the_hash_does_not_depend_on_other_files(self):
        a = os.path.join(self.tmp.name, 'a')
        with tarfile.open(fileobj=io.BytesIO(self.tar)) as t:
            t.extractall(a)
        before = sdk.content_hash(os.path.join(a, 'unrpyc-0.0.1'))
        with open(os.path.join(a, 'unrpyc-0.0.1', 'README.md'), 'w') as f:      # not code: not in the hash
            f.write('changed')
        self.assertEqual(sdk.content_hash(os.path.join(a, 'unrpyc-0.0.1')), before)
        with open(os.path.join(a, 'unrpyc-0.0.1', 'decompiler', '__init__.py'), 'w') as f:
            f.write('x = 1\n')
        self.assertNotEqual(sdk.content_hash(os.path.join(a, 'unrpyc-0.0.1')), before)
