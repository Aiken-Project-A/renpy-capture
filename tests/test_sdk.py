"""The SDK cache: one download however many workers ask at once; an SDK folder is either whole or absent."""
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
