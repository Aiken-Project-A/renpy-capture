"""The pieces of the Windows build that can be tried anywhere: what the program does with and without arguments, which
standard-library modules unrpyc needs, and the zip of a release."""
import importlib.util
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

from renpy_capture import __version__

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGING = os.path.join(HERE, 'packaging', 'windows')


def load(name):
    """A module of packaging/windows (it is not part of the package: a script and its helpers)."""
    spec = importlib.util.spec_from_file_location(f'packaging_{name}', os.path.join(PACKAGING, f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(os.path.isdir(PACKAGING), 'the source tree (an sdist leaves packaging out)')
class EntryTest(unittest.TestCase):
    """renpy-capture.exe with arguments is the command; without any (a double-click) it opens the window."""

    def setUp(self):
        self.entry = load('entry')

    def run_with(self, *argv):
        with mock.patch.object(sys, 'argv', ['renpy-capture.exe', *argv]), \
                mock.patch('renpy_capture.cli.main') as command, mock.patch('renpy_capture.gui.main') as window, \
                mock.patch.object(self.entry.multiprocessing, 'freeze_support') as freeze:
            self.entry.main()
        return command, window, freeze

    def test_arguments_make_it_the_command(self):
        command, window, freeze = self.run_with('capture', 'game', 'work')
        command.assert_called_once_with()
        window.assert_not_called()
        freeze.assert_called_once_with()

    def test_a_double_click_makes_it_the_window(self):
        command, window, freeze = self.run_with()
        window.assert_called_once_with()
        command.assert_not_called()
        freeze.assert_called_once_with()                        # first of all: a process of the pool is not a person

    def test_a_console_that_is_not_ours_is_left_alone(self):
        """Only the console a double-click made is let go of; one a terminal lent (another process is on it) stays."""
        if sys.platform != 'win32':
            self.assertIsNone(self.entry.let_go_of_the_console())               # nothing to do, nothing to fail
            return
        kernel = mock.Mock()
        kernel.GetConsoleWindow.return_value = 1
        for others, freed in ((1, True), (2, False)):
            kernel.GetConsoleProcessList.return_value = others
            kernel.FreeConsole.reset_mock()
            with mock.patch('ctypes.windll', mock.Mock(kernel32=kernel), create=True):
                self.entry.let_go_of_the_console()
            self.assertEqual(kernel.FreeConsole.called, freed)


@unittest.skipUnless(os.path.isdir(PACKAGING), 'the source tree (an sdist leaves packaging out)')
class IconTest(unittest.TestCase):
    def test_the_icon_of_the_window_is_the_one_the_programs_have(self):
        """renpy_capture/gui/icon.py is made by make_icon.py: when the drawing changes, it is made again. (Compared by
        what it shows, within a little: two versions of Pillow need not write the same bytes for one picture.)"""
        import base64
        import io
        from PIL import Image, ImageChops
        from renpy_capture.gui import icon
        drawn = load('make_icon').draw(64).convert('RGBA')
        kept = Image.open(io.BytesIO(base64.b64decode(icon.PNG64))).convert('RGBA')
        self.assertEqual(kept.size, (64, 64))
        self.assertLessEqual(max(hi for _, hi in ImageChops.difference(drawn, kept).getextrema()), 12)

    def test_the_icon_of_the_programs_has_every_size_windows_asks_for(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'renpy-capture.ico')
            load('make_icon').ico(path)
            self.assertEqual(sorted(Image.open(path).info['sizes']), [(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])


@unittest.skipUnless(os.path.isdir(PACKAGING) and hasattr(sys, 'stdlib_module_names'),
                     'the source tree, and a Python that names its standard library (3.10 and later)')
class ImportsTest(unittest.TestCase):
    def test_what_unrpyc_needs_from_the_standard_library(self):
        scan = load('stdlib_imports').stdlib_imports
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'decompiler'))
            files = {'unrpyc.py': 'import argparse, glob\nfrom concurrent.futures import ProcessPoolExecutor\n'
                                  'import decompiler\nfrom decompiler import astdump\n',
                     'decompiler/util.py': 'from . import magic\nfrom .x import y\n\ndef f():\n    import zlib, pickle\n',
                     'decompiler/broken.py': 'def (\n',
                     'decompiler/notes.txt': 'import socket\n'}
            for name, text in files.items():
                with open(os.path.join(tmp, name), 'w', encoding='utf-8') as f:
                    f.write(text)
            self.assertEqual(scan(tmp), ['argparse', 'concurrent.futures', 'glob', 'pickle', 'zlib'])
            self.assertEqual(scan(tmp, stdlib={'zlib'}), ['zlib'])


@unittest.skipUnless(os.path.isdir(PACKAGING), 'the source tree (an sdist leaves packaging out)')
class ZipTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dist = os.path.join(self._tmp.name, 'dist', 'renpy-capture')
        os.makedirs(os.path.join(self.dist, '_internal', 'renpy_capture'))
        for name in ('renpy-capture.exe', 'renpy-capture-gui.exe', '_internal/python312.dll',
                     '_internal/renpy_capture/capture.rpy'):
            with open(os.path.join(self.dist, *name.split('/')), 'wb') as f:
                f.write(b'x' * 100)
        self.make = load('make_zip')

    def test_the_zip_of_a_release(self):
        out = self.make.main(self.dist)
        self.assertEqual(os.path.basename(out), f'renpy-capture-{__version__}-windows-x64.zip')
        self.assertEqual(os.path.dirname(out), os.path.dirname(self.dist))
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            self.assertEqual(z.testzip(), None)
            readme = z.read('renpy-capture/README.txt').decode('utf-8')
        self.assertEqual(sorted(names), sorted(f'renpy-capture/{n}' for n in (
            'README.txt', 'LICENSE', 'THIRD-PARTY.txt', 'renpy-capture.exe', 'renpy-capture-gui.exe',
            '_internal/python312.dll', '_internal/renpy_capture/capture.rpy')))
        self.assertNotIn('\\', ''.join(names))                          # paths with / in them, whoever unzips
        self.assertIn(f'renpy-capture {__version__}, for Windows', readme)
        self.assertNotIn('{version}', readme)
        for must in ('renpy-capture-gui.exe', 'Extract All', 'More info', 'Run anyway'):
            self.assertIn(must, readme)                                 # what a person needs the first time

    def test_a_folder_that_is_not_the_build_is_refused(self):
        os.remove(os.path.join(self.dist, 'renpy-capture-gui.exe'))
        with self.assertRaises(SystemExit) as cm:
            self.make.main(self.dist)
        self.assertIn('renpy-capture-gui.exe', str(cm.exception.code))

    def test_the_licenses_of_what_is_carried_along_are_there_or_named_as_missing(self):
        text = self.make.third_party()
        for name in ('Python', 'Tcl/Tk', 'Pillow'):
            self.assertIn(name, text)


if __name__ == '__main__':
    unittest.main()
