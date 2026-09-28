"""The Ren'Py SDK a game needs: downloaded once from renpy.org and checked against the official checksums. And
unrpyc, which reads the compiled scripts of games that ship no sources: a pinned release, downloaded once.

The capture never runs the game's own executable: it runs the official SDK of the same version on a launch folder
that links to the game's files. SDKs are kept in ``$RENPY_CAPTURE_SDK`` (default ``~/.cache/renpy-capture/sdk``).
"""
import fcntl
import hashlib
import os
import shutil
import tarfile
import tempfile
import urllib.request

DOWNLOADS = 'https://www.renpy.org/dl/'
# unrpyc (https://github.com/CensoredUsername/unrpyc, MIT): its release, and the sha256 of its Python files and license
# (content_hash), which stays the same however GitHub packs the archive
UNRPYC = ('2.0.4', '06d991966ec7e1f6470b0b02e2c4c9360c5fcb18be62b3b9ce049da9e03f0bbf')


def cache_root():
    return os.environ.get('RENPY_CAPTURE_SDK') or os.path.join(
        os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'renpy-capture', 'sdk')


def ensure(version):
    """The folder of the SDK ``version`` (e.g. '8.2.3'), downloaded and unpacked if it is not there yet. Workers and
    runs may ask for it at once: one downloads, the others wait and take the same folder."""
    root = cache_root()
    d = os.path.join(root, f'renpy-{version}-sdk')
    if os.path.isfile(os.path.join(d, 'renpy.sh')):
        return d
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, f'.renpy-{version}-sdk.lock'), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)            # held until the file is closed or the process dies
        if not os.path.isfile(os.path.join(d, 'renpy.sh')):
            fetch(version, root, d)
    return d


def fetch(version, root, d):
    """Download, check and unpack the SDK into ``d``. The archive is unpacked aside and moved in whole, so a cut-off
    unpack never looks like a ready SDK."""
    name = f'renpy-{version}-sdk.tar.bz2'
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
        with tarfile.open(tb) as t:
            if hasattr(tarfile, 'tar_filter'):      # Python 3.12+: refuse absolute paths and paths outside tmp
                t.extractall(tmp, filter='tar')
            else:
                t.extractall(tmp)
        got = os.path.join(tmp, os.path.basename(d))
        if not os.path.isfile(os.path.join(got, 'renpy.sh')):
            raise SystemExit(f'{name} unpacked, but {os.path.basename(d)}/renpy.sh is missing in it')
        if os.path.isdir(d):                        # a cut-off unpack of an earlier version of this tool
            shutil.rmtree(d)
        os.rename(got, d)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def tools_root():
    return os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'renpy-capture', 'tools')


def unrpyc():
    """The folder of unrpyc, downloaded once from its GitHub release and checked against the pinned content hash.
    Raises ImportError when it cannot be had, as a missing module would."""
    version, want = UNRPYC
    root = tools_root()
    d = os.path.join(root, f'unrpyc-{version}')
    if os.path.isfile(os.path.join(d, 'unrpyc.py')):
        return d
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, f'.unrpyc-{version}.lock'), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not os.path.isfile(os.path.join(d, 'unrpyc.py')):
            fetch_unrpyc(version, want, root, d)
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
        with tarfile.open(tb) as t:
            if hasattr(tarfile, 'tar_filter'):
                t.extractall(tmp, filter='tar')
            else:
                t.extractall(tmp)
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
