"""The Ren'Py SDK a game needs: downloaded once from renpy.org and checked against the official checksums. And
unrpyc, which reads the compiled scripts of games that ship no sources: a pinned release, downloaded once.

The capture never runs the game's own executable: it runs the official SDK of the same version on a launch folder
that links to the game's files. SDKs are kept in ``$RENPY_CAPTURE_SDK`` (default ``~/.cache/renpy-capture/sdk``, on
Windows ``%LOCALAPPDATA%\\renpy-capture\\sdk``).

Every SDK package holds the engine for Linux, Windows and macOS alike (the .tar.bz2 and the .zip of 8.3.2 and 7.8.7
hold the same files); Windows takes the .zip, which unpacks without bzip2 and several times faster there.
"""
import hashlib
import os
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile

WINDOWS = os.name == 'nt'

DOWNLOADS = 'https://www.renpy.org/dl/'
# unrpyc (https://github.com/CensoredUsername/unrpyc, MIT): its release, and the sha256 of its Python files and license
# (content_hash), which stays the same however GitHub packs the archive
UNRPYC = ('2.0.4', '06d991966ec7e1f6470b0b02e2c4c9360c5fcb18be62b3b9ce049da9e03f0bbf')


def _cache_base():
    if os.environ.get('XDG_CACHE_HOME'):
        return os.environ['XDG_CACHE_HOME']
    if WINDOWS and os.environ.get('LOCALAPPDATA'):
        return os.environ['LOCALAPPDATA']
    return os.path.expanduser('~/.cache')


def cache_root():
    return os.environ.get('RENPY_CAPTURE_SDK') or os.path.join(_cache_base(), 'renpy-capture', 'sdk')


def _lock(f):
    """Wait for the lock of an open file; it is held until _unlock or until the process dies."""
    if os.name == 'nt':
        import msvcrt
        f.seek(0)
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)   # one byte: past the end of an empty file is fine
                return
            except OSError:                          # LK_LOCK gives up after ten tries a second apart: try again
                pass
    else:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX)


def _unlock(f):
    if os.name == 'nt':                             # Windows frees a lock some time after its file is closed:
        import msvcrt                               # free it now, for whoever waits
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def _once(root, lock_name, ready, make):
    """``make()`` unless ``ready()``, one process at a time: the others wait on the lock and find it ready."""
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, lock_name), 'a+') as lock:     # (not 'w': no truncating a file another one locks)
        _lock(lock)
        try:
            if not ready():
                make()
        finally:
            _unlock(lock)


def _unpack(archive, dest):
    if archive.endswith('.zip'):
        with zipfile.ZipFile(archive) as z:         # zipfile drops absolute paths and '..' by itself
            z.extractall(dest)
        return
    with tarfile.open(archive) as t:
        if hasattr(tarfile, 'tar_filter'):          # Python 3.12+ (and the security releases before it): refuse
            t.extractall(dest, filter='tar')        # absolute paths and paths outside dest
        else:
            t.extractall(dest)


def package(version):
    """The name of the SDK package to download: the .zip on Windows, the .tar.bz2 elsewhere."""
    return f'renpy-{version}-sdk.zip' if WINDOWS else f'renpy-{version}-sdk.tar.bz2'


def engine(sdk_dir):
    """The command that starts the engine of an SDK, before the launch folder: renpy.sh, or on Windows the engine
    renpy.sh would pick there, lib/py3-windows-x86_64/renpy.exe (py2-… for Ren'Py 7), which runs renpy.py with the
    SDK's own Python."""
    if not WINDOWS:
        return [os.path.join(sdk_dir, 'renpy.sh')]
    for py in ('py3', 'py2'):
        exe = os.path.join(sdk_dir, 'lib', f'{py}-windows-x86_64', 'renpy.exe')
        if os.path.isfile(exe):
            return [exe]
    raise SystemExit(f"{sdk_dir}: no lib/py3-windows-x86_64/renpy.exe (nor py2-…) in this Ren'Py SDK")


def ensure(version):
    """The folder of the SDK ``version`` (e.g. '8.2.3'), downloaded and unpacked if it is not there yet. Workers and
    runs may ask for it at once: one downloads, the others wait and take the same folder."""
    root = cache_root()
    d = os.path.join(root, f'renpy-{version}-sdk')
    if os.path.isfile(os.path.join(d, 'renpy.sh')):
        return d
    _once(root, f'.renpy-{version}-sdk.lock', lambda: os.path.isfile(os.path.join(d, 'renpy.sh')),
          lambda: fetch(version, root, d))
    return d


def fetch(version, root, d):
    """Download, check and unpack the SDK into ``d``. The archive is unpacked aside and moved in whole, so a cut-off
    unpack never looks like a ready SDK."""
    name = package(version)
    base = f'{DOWNLOADS}{version}/'
    tb = os.path.join(root, name)
    try:
        if not os.path.exists(tb):
            print(f'downloading {base}{name}', flush=True)
            urllib.request.urlretrieve(base + name, tb + '.part')
            os.replace(tb + '.part', tb)
        with urllib.request.urlopen(base + 'checksums.txt') as r:
            sums = r.read().decode()
    except OSError as e:
        raise SystemExit(f"cannot download the Ren'Py {version} SDK from {base}: {e}")
    want = next((line.split()[0] for line in sums.splitlines()
                 if line.endswith(' ' + name) and len(line.split()[0]) == 64), None)
    if want is None:
        raise SystemExit(f'{base}checksums.txt has no sha256 for {name}')
    h = hashlib.sha256()
    with open(tb, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    if h.hexdigest() != want:
        os.remove(tb)
        raise SystemExit(f'sha256 of {name} does not match the official one ({h.hexdigest()} != {want}); '
                         'the download was removed, try again')
    print(f'unpacking {name}', flush=True)
    tmp = tempfile.mkdtemp(prefix=f'.renpy-{version}-sdk-', dir=root)
    try:
        _unpack(tb, tmp)
        got = os.path.join(tmp, os.path.basename(d))
        if not os.path.isfile(os.path.join(got, 'renpy.sh')):
            raise SystemExit(f'{name} unpacked, but {os.path.basename(d)}/renpy.sh is missing in it')
        if os.path.isdir(d):                        # a cut-off unpack of an earlier version of this tool
            shutil.rmtree(d)
        os.rename(got, d)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def tools_root():
    return os.path.join(_cache_base(), 'renpy-capture', 'tools')


def unrpyc():
    """The folder of unrpyc, downloaded once from its GitHub release and checked against the pinned content hash.
    Raises ImportError when it cannot be had, as a missing module would."""
    version, want = UNRPYC
    root = tools_root()
    d = os.path.join(root, f'unrpyc-{version}')
    if os.path.isfile(os.path.join(d, 'unrpyc.py')):
        return d
    _once(root, f'.unrpyc-{version}.lock', lambda: os.path.isfile(os.path.join(d, 'unrpyc.py')),
          lambda: fetch_unrpyc(version, want, root, d))
    return d


def content_hash(folder):
    """sha256 over the Python files and the license of a folder, with their paths: the same for any archive that
    holds the same files."""
    h = hashlib.sha256()
    for base, dirs, files in os.walk(folder):
        dirs.sort()
        for f in sorted(files):
            if f.endswith('.py') or f == 'LICENSE':
                p = os.path.join(base, f)
                h.update(os.path.relpath(p, folder).replace(os.sep, '/').encode() + b'\0')
                with open(p, 'rb') as fh:
                    h.update(fh.read())
                h.update(b'\0')
    return h.hexdigest()


def fetch_unrpyc(version, want, root, d):
    """Download the release, check it and move it into ``d`` whole (as fetch does with an SDK)."""
    url = f'https://github.com/CensoredUsername/unrpyc/archive/refs/tags/v{version}.tar.gz'
    tmp = tempfile.mkdtemp(prefix=f'.unrpyc-{version}-', dir=root)
    try:
        tb = os.path.join(tmp, 'unrpyc.tar.gz')
        print(f'downloading unrpyc {version} (reads compiled scripts): {url}', flush=True)
        try:
            urllib.request.urlretrieve(url, tb)
        except OSError as e:
            raise ImportError(f'cannot download unrpyc from {url}: {e}; or point RENPY_CAPTURE_UNRPYC to a copy of '
                              'it (https://github.com/CensoredUsername/unrpyc)') from e
        _unpack(tb, tmp)
        got = os.path.join(tmp, f'unrpyc-{version}')
        have = content_hash(got) if os.path.isdir(got) else None
        if have != want:
            raise ImportError(f'unrpyc {version} from {url} is not the release this tool was checked with '
                              f'(content {have} != {want})')
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.rename(got, d)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
