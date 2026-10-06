# -*- mode: python ; coding: utf-8 -*-
"""The Windows build of renpy-capture: a folder that needs nothing installed (no Python, no pipx, no console).

    pip install pyinstaller==6.22.3 .
    pyinstaller --noconfirm packaging/windows/renpy-capture.spec      ->  dist/renpy-capture/
    python packaging/windows/make_zip.py                               ->  renpy-capture-<version>-windows-x64.zip

One folder, not one file: it starts faster (nothing is unpacked into a temporary folder first) and antivirus programs
flag it less. Two programs share it: renpy-capture.exe is the command (a console; given no arguments it opens the
window), renpy-capture-gui.exe is the window (no console, what a double-click is meant to start). PyInstaller is a tool
of this build only, not a dependency of the package."""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))           # SPECPATH: the folder of this file
sys.path.insert(0, ROOT)
sys.path.insert(0, SPECPATH)

from PyInstaller.utils.hooks import collect_submodules                # noqa: E402

from renpy_capture import __version__, sdk                            # noqa: E402
from stdlib_imports import stdlib_imports                             # noqa: E402
import make_icon                                                      # noqa: E402

# what unrpyc needs if it cannot be looked at when this is built (it is, normally: see unrpyc_imports)
UNRPYC_FALLBACK = ['argparse', 'ast', 'codecs', 'collections', 'concurrent.futures', 'contextlib', 'copy', 'dis',
                   'enum', 'functools', 'glob', 'inspect', 'io', 'itertools', 'multiprocessing', 'operator',
                   'os', 'pathlib', 'pickle', 'pickletools', 're', 'struct', 'sys', 'textwrap', 'traceback', 'types',
                   'typing', 'zlib']


def unrpyc_imports():
    """The standard-library modules the pinned unrpyc imports. A game that ships only compiled scripts has them read by
    unrpyc, which is downloaded when it is needed and runs inside this program; a module that this program does not
    hold would stop it. The release is the one sdk.py checks the hash of, so what is found here is what will run."""
    try:
        folder = sdk.unrpyc()
    except ImportError as e:
        print(f'WARNING: unrpyc could not be looked at ({e}); the usual modules are included')
        return UNRPYC_FALLBACK
    mods = stdlib_imports(folder)
    print(f'unrpyc {sdk.UNRPYC[0]} imports from the standard library: {", ".join(mods)}')
    return mods


def version_info(description, original):
    """What the properties of the program say on Windows (and what an antivirus program reads about it)."""
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    numbers = (tuple(int(n) for n in re.findall(r'\d+', __version__)) + (0, 0, 0, 0))[:4]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                          subtype=0x0, date=(0, 0)),
        kids=[StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'renpy-capture'),
            StringStruct('FileDescription', description),
            StringStruct('FileVersion', __version__),
            StringStruct('InternalName', 'renpy-capture'),
            StringStruct('LegalCopyright', 'MIT License, https://github.com/Aiken-Project-A/renpy-capture'),
            StringStruct('OriginalFilename', original),
            StringStruct('ProductName', 'renpy-capture'),
            StringStruct('ProductVersion', __version__)])]),
            VarFileInfo([VarStruct('Translation', [1033, 1200])])])


a = Analysis(
    [os.path.join(SPECPATH, 'entry.py')],
    pathex=[ROOT],
    # what the package reads at run time: the script the engine runs (runner.py finds it next to itself)
    datas=[(os.path.join(ROOT, 'renpy_capture', 'capture.rpy'), 'renpy_capture')],
    hiddenimports=collect_submodules('renpy_capture') + unrpyc_imports(),
    excludes=['pydoc', 'pdb', 'doctest', 'unittest', 'test', 'lib2to3', 'distutils', 'setuptools', 'pkg_resources',
              'tkinter.test', 'idlelib', 'turtledemo', 'turtle'],
)
pyz = PYZ(a.pure)

windows = sys.platform == 'win32'
icon = os.path.join(workpath, 'renpy-capture.ico')                    # drawn now: no binary file in the repository
os.makedirs(workpath, exist_ok=True)
make_icon.ico(icon)
command = EXE(pyz, a.scripts, [], exclude_binaries=True, name='renpy-capture', console=True,
              icon=icon if windows else None,
              version=version_info('renpy-capture, the command line', 'renpy-capture.exe') if windows else None)
window = EXE(pyz, a.scripts, [], exclude_binaries=True, name='renpy-capture-gui', console=False,
             icon=icon if windows else None,
             version=version_info('renpy-capture, the window', 'renpy-capture-gui.exe') if windows else None)
COLLECT(command, window, a.binaries, a.datas, name='renpy-capture')
