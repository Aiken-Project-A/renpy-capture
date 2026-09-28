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
from unittest import mock

from renpy_capture import sdk


def fake_sdk(version):
    """A tar.bz2 shaped like an SDK: renpy-<version>-sdk/renpy.sh and one more file."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:bz2') as t:
        for name, data in ((f'renpy-{version}-sdk/renpy.sh', b'#!/bin/sh\n'),
                           (f'renpy-{version}-sdk/renpy/__init__.py', b'')):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class SdkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tar = fake_sdk('9.9.9')
        self.downloads = []

        def urlretrieve(url, path):
            self.downloads.append(url)
            data = self.tar
            with open(path, 'wb') as f:             # slowly, the way a real download gives every other worker
                for i in range(0, len(data), 64):   # time to arrive meanwhile
                    f.write(data[i:i + 64])
                    f.flush()
                    time.sleep(0.002)

        sums = f'{hashlib.sha256(self.tar).hexdigest()}  renpy-9.9.9-sdk.tar.bz2\n'.encode()
        self.patches = [mock.patch.dict(os.environ, {'RENPY_CAPTURE_SDK': self.tmp.name}),
                        mock.patch.object(sdk.urllib.request, 'urlretrieve', urlretrieve),
                        mock.patch.object(sdk.urllib.request, 'urlopen', lambda url: io.BytesIO(sums))]
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
                         ['renpy-9.9.9-sdk', 'renpy-9.9.9-sdk.tar.bz2'])

    def test_a_folder_without_renpy_sh_is_unpacked_again(self):
        os.makedirs(os.path.join(self.d, 'lib'))    # what a cut-off unpack used to leave
        self.assertEqual(sdk.ensure('9.9.9'), self.d)
        self.assertTrue(os.path.isfile(os.path.join(self.d, 'renpy.sh')))
        self.assertFalse(os.path.exists(os.path.join(self.d, 'lib')))

    def test_a_download_that_does_not_match_is_removed(self):
        self.tar = self.tar[:-8] + b'\0' * 8        # the checksums still describe the good file
        with self.assertRaises(SystemExit):
            sdk.ensure('9.9.9')
        self.assertEqual([f for f in os.listdir(self.tmp.name) if not f.endswith('.lock')], [])

    def test_an_unpacked_sdk_is_not_downloaded_again(self):
        sdk.ensure('9.9.9')
        sdk.ensure('9.9.9')
        self.assertEqual(len(self.downloads), 1)


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

        def urlretrieve(url, path):
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
