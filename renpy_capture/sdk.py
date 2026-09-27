"""The Ren'Py SDK a game needs: downloaded once from renpy.org and checked against the official checksums.

The capture never runs the game's own executable: it runs the official SDK of the same version on a launch folder
that links to the game's files. SDKs are kept in ``$RENPY_CAPTURE_SDK`` (default ``~/.cache/renpy-capture/sdk``).
"""
import hashlib
import os
import tarfile
import urllib.request

DOWNLOADS = 'https://www.renpy.org/dl/'


def cache_root():
    return os.environ.get('RENPY_CAPTURE_SDK') or os.path.join(
        os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'renpy-capture', 'sdk')


def ensure(version):
    """The folder of the SDK ``version`` (e.g. '8.2.3'), downloaded and unpacked if it is not there yet."""
    root = cache_root()
    d = os.path.join(root, f'renpy-{version}-sdk')
    if os.path.isfile(os.path.join(d, 'renpy.sh')):
        return d
    os.makedirs(root, exist_ok=True)
    name = f'renpy-{version}-sdk.tar.bz2'
    base = f'{DOWNLOADS}{version}/'
    tb = os.path.join(root, name)
    try:
        if not os.path.exists(tb):
            print(f'downloading {base}{name}')
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
    print(f'unpacking {name}')
    with tarfile.open(tb) as t:
        if hasattr(tarfile, 'tar_filter'):          # Python 3.12+: refuse absolute paths and paths outside root
            t.extractall(root, filter='tar')
        else:
            t.extractall(root)
    if not os.path.isfile(os.path.join(d, 'renpy.sh')):
        raise SystemExit(f'{name} unpacked, but {d}/renpy.sh is missing')
    return d
