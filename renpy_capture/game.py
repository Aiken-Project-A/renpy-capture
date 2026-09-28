"""A Ren'Py game on disk: where its game/ directory is, its files as the engine sees them, and its scripts."""
import io
import os
import re
import sys

from . import rpa
from .util import read_bytes, read_text

SKIP_DIRS = ('cache/', 'saves/', 'tl/', '__pycache__/')
# Mods that players drop into game/ and that draw over the game: machine translation on the fly (Translator3000),
# the Universal Ren'Py Mod. They are not the game: a launch folder leaves them out, and so does reading the game.
MODS = re.compile(r'translator3000|0x52_urm', re.I)


def _has_scripts(d):
    try:
        return any(f.lower().endswith(('.rpa', '.rpy', '.rpyc')) for f in os.listdir(d))
    except OSError:
        return False


def game_dir(path):
    """The game/ directory of the game at ``path``: the game folder itself, its game/ directory, or a folder up to
    three levels above it (downloaded games often come wrapped in extra folders)."""
    path = os.path.abspath(path)
    if os.path.basename(path) == 'game' and _has_scripts(path):
        return path
    if _has_scripts(os.path.join(path, 'game')):
        return os.path.join(path, 'game')
    found = []
    for d, subs, _ in os.walk(path):
        if d.count(os.sep) - path.rstrip(os.sep).count(os.sep) >= 3:
            subs[:] = []
            continue
        if _has_scripts(os.path.join(d, 'game')):
            found.append(d)
            subs[:] = []
    if len(found) == 1:
        return os.path.join(found[0], 'game')
    if found:
        raise ValueError(f"{path}: several Ren'Py games inside, point to one of: " + '; '.join(found))
    raise ValueError(f"{path}: no Ren'Py game here (a folder whose game/ holds .rpy, .rpyc or .rpa files)")


def _engine_in(base):
    p = os.path.join(base, 'renpy', 'vc_version.py')
    if os.path.exists(p):
        m = re.search(r"^version\s*=\s*u?['\"](\d+(?:\.\d+)+)", read_text(p, errors='replace'), re.M)   # u'…': Py 2
        if m:
            return '.'.join(m.group(1).split('.')[:3])
    p = os.path.join(base, 'renpy', '__init__.py')           # Ren'Py 7 and older: version_tuple = (7, 4, 11, vc)
    if os.path.exists(p):
        m = re.search(r'^version_tuple\s*=\s*\((\d+),\s*(\d+),\s*(\d+)', read_text(p, errors='replace'), re.M)
        if m:
            return '.'.join(m.groups())
    return None


def engine_version(game):
    """The version of the engine bundled with the game, e.g. '8.2.3', or None when it cannot be told. A project
    without an engine of its own inside a Ren'Py SDK folder (the SDK's sample games, an author's projects) runs on
    that SDK: its version."""
    root = os.path.dirname(game_dir(game))
    return _engine_in(root) or _engine_in(os.path.dirname(root))


def engine_hint(game):
    """What the game's own cache tells of the engine that ran it last (bytecode-39.rpyb: Ren'Py 8 on Python 3.9), or
    ''. A hint for choosing --renpy-version, not a version."""
    cache = os.path.join(game_dir(game), 'cache')
    names = sorted(os.listdir(cache)) if os.path.isdir(cache) else []
    for n in names:
        m = re.fullmatch(r'bytecode-(\d)(\d+)\.rpyb', n)
        if m:
            major = '7' if m.group(1) == '2' else '8'
            return f"its cache was made by Ren'Py {major} (Python {m.group(1)}.{m.group(2)}, {n})"
    return ''


class Game:
    """``files`` maps a path inside game/ to a function returning its bytes, resolved the way the engine resolves
    them: loose files first, then the archives in reverse alphabetical order (``renpy/main.py`` sorts the archive
    list and reverses it); names match case-insensitively and the first file found wins. Translations (tl/), cache
    and saves are left out."""

    def __init__(self, path):
        self.base = game_dir(path)
        self.root = os.path.dirname(self.base)
        self.files, self.origin, low = {}, {}, {}

        def add(rel, fn, where):
            key = rel.lower()
            if key in low:
                return
            low[key] = rel
            self.files[rel] = fn
            self.origin[rel] = where

        for d, subs, fs in os.walk(self.base):
            subs.sort()
            for f in sorted(fs):
                p = os.path.join(d, f)
                rel = os.path.relpath(p, self.base).replace(os.sep, '/')
                if f.lower().endswith(('.rpa', '.rpi', '.rpyb')) or rel.lower().startswith(SKIP_DIRS) \
                        or MODS.search(rel):
                    continue
                add(rel, (lambda p=p: read_bytes(p)), 'disk')
        self.archives = sorted(f for f in os.listdir(self.base)
                               if f.lower().endswith('.rpa') and not MODS.search(f))[::-1]
        for f in self.archives:
            arc = rpa.Archive(os.path.join(self.base, f))
            for n in sorted(arc.index):
                rel = n.replace('\\', '/')
                if rel.lower().startswith('tl/'):
                    continue
                add(rel, (lambda arc=arc, n=n: arc.read(n)), f)
        self.decompiled, self.failed = set(), {}

    def scripts(self):
        """{path of a .rpy/.rpym: text}: the source where the game ships it; otherwise the compiled .rpyc/.rpymc
        decompiled with unrpyc (see ``decompile``). Files the decompiler could not read go to ``failed``."""
        out = {}
        have = {r.lower() for r in self.files}
        for rel in sorted(self.files):
            low = rel.lower()
            if low.endswith(('.rpy', '.rpym')):
                out[rel] = self.files[rel]().decode('utf-8-sig', 'replace').replace('\r\n', '\n')
            elif low.endswith(('.rpyc', '.rpymc')) and low[:-1] not in have:
                try:
                    out[rel[:-1]] = decompile(self.files[rel]())
                    self.decompiled.add(rel[:-1])
                except ImportError:
                    raise
                except Exception as e:
                    self.failed[rel] = f'{type(e).__name__}: {e}'
                    print(f'  not decompiled: {rel} ({self.failed[rel]})', file=sys.stderr)
        return out


_unrpyc = None


def decompile(raw):
    """A compiled script (.rpyc) as .rpy text, with the line numbers of the original, via unrpyc
    (https://github.com/CensoredUsername/unrpyc, MIT). Only games that ship no .rpy sources need it: the copy
    RENPY_CAPTURE_UNRPYC points to (the folder with unrpyc.py), an importable one, or else a pinned release that is
    downloaded once and checked (sdk.unrpyc)."""
    global _unrpyc
    if _unrpyc is None:
        where = os.environ.get('RENPY_CAPTURE_UNRPYC')
        if where:
            sys.path.insert(0, os.path.expanduser(where))
        try:
            import unrpyc
            import decompiler
        except ImportError as e:
            if where:
                raise ImportError(f'RENPY_CAPTURE_UNRPYC={where}: no unrpyc there ({e})') from e
            from .sdk import unrpyc as fetched
            sys.path.insert(0, fetched())
            import unrpyc
            import decompiler
        _unrpyc = (unrpyc, decompiler)
    unrpyc, decompiler = _unrpyc
    ctx = unrpyc.Context()
    ast = unrpyc.read_ast_from_file(io.BytesIO(raw), ctx)
    buf = io.StringIO()
    decompiler.pprint(buf, ast, decompiler.Options(log=ctx.log_contents, translator=None, init_offset=True,
                                                   sl_custom_names=None))
    return buf.getvalue()
