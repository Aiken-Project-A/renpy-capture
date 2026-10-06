"""Running a capture: the launch folder, the engine under a display, jobs on several engines, menu exploration."""
import collections
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback

from . import events
from . import sdk as sdkmod
from .analysis import report
from .game import MODS, engine_hint, engine_version, game_dir
from .util import near, plural, read_bytes, read_done, read_json, read_jsonl, read_text

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURE_RPY = os.path.join(HERE, 'capture.rpy')
RPY_NAME = 'zz_renpy_capture.rpy'
RUN_INFO = 'renpy-capture.json'
LINKS = '.links.json'
NO_EDITOR = 'no-editor.edit.py'
WINDOWS = os.name == 'nt'
EGL = {'nvidia': '/usr/share/glvnd/egl_vendor.d/10_nvidia.json',
       'mesa': '/usr/share/glvnd/egl_vendor.d/50_mesa.json'}
DRM_SYSFS = '/sys/class/drm'
SCREEN = (1920, 1200)
DISPLAYS = ('kwin', 'xvfb', 'window', 'offscreen', 'desktop')
STARTER = {'jobs': [{'id': 'start', 'label': 'start'}], 'ui': '.*', 'settle': 0.3, 'settle_max': 1.2,
           'max_steps': 3000, 'loop_limit': 40}


def _info(rundir):
    p = os.path.join(rundir, RUN_INFO)
    if not os.path.exists(p):
        raise SystemExit(f'{rundir}: not a launch folder (run `renpy-capture setup` first)')
    return read_json(p)


def setup(game, rundir, version=None, sdk_dir=None, exclude=None, quiet=False):
    """The launch folder: game/ made of links to the game's files plus capture.rpy, its own saves, cache and HOME.
    The game itself is never changed."""
    g = game_dir(game)
    root = os.path.dirname(g)
    rundir = os.path.abspath(rundir)
    if os.path.exists(rundir) and (os.path.samefile(rundir, root) or os.path.samefile(rundir, g)):
        raise SystemExit('the launch folder must not be the game folder')
    if os.path.lexists(os.path.join(rundir, 'game')) and not os.path.exists(os.path.join(rundir, RUN_INFO)):
        raise SystemExit(f'{rundir} already has a game/ folder that renpy-capture did not make; '
                         'choose an empty launch folder')
    version = version or engine_version(game)
    if not version and not sdk_dir:
        hint = engine_hint(game)
        raise SystemExit("cannot tell the game's Ren'Py version: pass --renpy-version (or --sdk)"
                         + (f'; {hint}' if hint else ''))
    os.makedirs(os.path.join(rundir, 'home'), exist_ok=True)
    stub = os.path.join(rundir, 'bin')              # a crashing engine opens traceback.txt with xdg-open: no editor
    os.makedirs(stub, exist_ok=True)                # windows pop up on the user's desktop
    if WINDOWS:                                     # (os.startfile there: an editor of Ren'Py's own that opens nothing)
        with open(os.path.join(stub, NO_EDITOR), 'w') as f:
            f.write('import renpy.editor\n\n\nclass Editor(renpy.editor.Editor):\n'
                    '    def open(self, filename, line=None, **kwargs):\n        pass\n')
    else:
        with open(os.path.join(stub, 'xdg-open'), 'w') as f:
            f.write('#!/bin/sh\nexit 0\n')
        os.chmod(os.path.join(stub, 'xdg-open'), 0o755)
    info = {'game': os.path.abspath(game), 'version': version, 'sdk': sdk_dir and os.path.abspath(sdk_dir),
            'exclude': exclude}
    with open(os.path.join(rundir, RUN_INFO), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    link_game(info, rundir)
    if not quiet:
        print(f"launch folder: {near(rundir)} (Ren'Py {version or 'from ' + sdk_dir})")


# a compiled script and the sources the engine compiles it from: x.rpyc from x.rpy or from x_ren.py
COMPILED = {'.rpyc': ('.rpy', '_ren.py'), '.rpymc': ('.rpym',)}


def _sources(name):
    """The possible sources of a compiled script (x.rpy and x_ren.py for x.rpyc), or ()."""
    for ext, srcs in COMPILED.items():
        if name.endswith(ext):
            return tuple(name[:-len(ext)] + src for src in srcs)
    return ()


def _place(src, dst):
    """A file of the game in the launch folder. A symbolic link; on Windows, where those need an administrator or
    Developer Mode, a hard link (the same file under a second name, on the same volume), or else a copy. Returns how
    it was placed: 'link' or 'copy'."""
    if not WINDOWS:
        os.symlink(src, dst)
        return 'link'
    try:
        os.link(src, dst)
        return 'link'
    except OSError:                                 # another drive, FAT/exFAT, a network share
        shutil.copy2(src, dst)
        return 'copy'


def _read_links(rundir):
    """What link_game placed in game/ on Windows, {path inside game/: 'link' | 'copy'}: a hard link or a copy is a
    plain file there, unlike a symbolic link, so the launch folder keeps a list of them."""
    p = os.path.join(rundir, LINKS)
    try:
        return read_json(p) if os.path.exists(p) else {}
    except ValueError:
        return {}


def _write_links(rundir, made):
    tmp = os.path.join(rundir, LINKS + '.new')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(made, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, os.path.join(rundir, LINKS))


def _same_copy(src, dst):
    """A copy that is still the game's file: the same size and time of change (copy2 keeps the time, to the two
    seconds of FAT)."""
    try:
        a, b = os.stat(src), os.stat(dst)
    except OSError:
        return False
    return a.st_size == b.st_size and abs(a.st_mtime - b.st_mtime) <= 2


def _plan(g, rx):
    """What link_game puts in game/ of a launch folder: (the folders inside game/, [(a file of the game, its path
    inside game/)]). Not the game's saves and cache, overlay mods, ``exclude`` (the regex ``rx``) or executables at
    the top; not a compiled script whose source the game ships too (the engine compiles its own from the source)."""
    dirs, files = [], []
    for d, subs, names in os.walk(g, followlinks=WINDOWS):
        rel = os.path.relpath(d, g)
        if rel == '.':
            subs[:] = [s for s in subs if s not in ('saves', 'cache') and not MODS.search(s)
                       and not (rx and rx.search(s))]
            names = [f for f in names if not f.lower().endswith('.exe') and not MODS.search(f)
                     and not (rx and rx.search(f))]
        if not WINDOWS:                             # a link to a folder in the game is linked as it is (on
            names += [s for s in subs if os.path.islink(os.path.join(d, s))]       # Windows, walked into)
            subs[:] = [s for s in subs if not os.path.islink(os.path.join(d, s))]
        subs.sort()
        if rel != '.':
            dirs.append(rel)
        have = set(names)
        for f in sorted(names):
            if not any(s in have for s in _sources(f)):
                files.append((os.path.join(d, f), f if rel == '.' else os.path.join(rel, f)))
    return dirs, files


def link_game(info, rundir):
    """(Re)make game/ of a launch folder: the folders of the game's game/ as real folders, with a link to every file
    (not its saves and cache, not overlay mods, not ``exclude``), and capture.rpy. Whatever the engine writes lands in
    the launch folder, never in the game: its saves/ and cache/, and the scripts it compiles — a compiled script whose
    source the game ships too is not linked, the engine compiles its own from the source and keeps it for later runs.
    Called on every run, so the folder follows an updated game. On Windows a copy that is still the game's file stays
    (a game on another drive is copied once, not on every run)."""
    g = game_dir(info['game'])
    rg = os.path.join(rundir, 'game')
    rx = re.compile(info['exclude']) if info.get('exclude') else None
    os.makedirs(rg, exist_ok=True)
    dirs, files = _plan(g, rx)
    made = _read_links(rundir) if WINDOWS else {}
    keep = {rel for src, rel in files if made.get(rel) == 'copy' and _same_copy(src, os.path.join(rg, rel))}
    _unlink(g, rg, rg, made, keep)
    now = {rel: 'link' for _, rel in files}
    now.update((rel, 'copy') for rel in keep)
    if WINDOWS:                                     # listed before they are made: a cut-off run leaves none unknown
        _write_links(rundir, now)
    for rel in dirs:
        os.makedirs(os.path.join(rg, rel), exist_ok=True)
    copies = 0
    for src, rel in files:
        dst = os.path.join(rg, rel)
        if os.path.lexists(dst):                    # the engine's own compiled script, or a copy kept
            continue
        now[rel] = _place(src, dst)
        copies += now[rel] == 'copy'
    if WINDOWS:
        _write_links(rundir, now)
        if copies:
            print(f"{plural(copies, 'file')} of the game copied into the launch folder (a hard link needs the same "
                  'drive and NTFS); a launch folder on the drive of the game takes no room', flush=True)
    for sub in ('saves', 'cache'):
        os.makedirs(os.path.join(rg, sub), exist_ok=True)
    with open(CAPTURE_RPY, 'rb') as src, open(os.path.join(rg, RPY_NAME), 'wb') as dst:
        dst.write(src.read().replace(b'\r\n', b'\n'))   # LF, however it was checked out: a line continued with a
                                                            # backslash is one line for Ren'Py only before LF


def _unlink(g, rg, d, made=None, keep=()):
    """Take down what link_game made in the folder ``d`` of a launch folder's game/ ``rg``: links and capture.rpy go
    (on Windows the hard links and copies of ``made``, except the copies in ``keep``), folders go once empty. The
    engine's saves/ and cache/ stay, and so do the scripts it compiled while the game still has their source. Anything
    else was put there by hand: refuse rather than delete it."""
    made = made or {}
    rel = os.path.relpath(d, rg)
    for f in os.listdir(d):
        p = os.path.join(d, f)
        r = f if rel == '.' else os.path.join(rel, f)
        if d == rg and f in ('saves', 'cache'):
            continue
        if r in keep:
            continue
        if os.path.islink(p) or (d == rg and f.startswith(RPY_NAME[:-3])) or (r in made and os.path.isfile(p)):
            os.remove(p)                            # (removing a hard link leaves the game's own name of the file)
        elif os.path.isdir(p):
            _unlink(g, rg, p, made, keep)
            if not os.listdir(p):
                os.rmdir(p)
        elif _sources(f):
            if not any(os.path.exists(os.path.join(g, rel, s)) for s in _sources(f)):   # the game no longer has
                os.remove(p)                                                            # the source
        elif WINDOWS and _same_file(p, os.path.join(g, r)):   # a hard link whose list was lost
            os.remove(p)
        else:
            raise SystemExit(f'{p} is not a link made by renpy-capture; the launch folder was changed by hand')


def _same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def init_config(game, path):
    """A starter config: one job that plays the game from `start`, menus answered with the first option (explore
    then takes every other option)."""
    game_dir(game)
    if os.path.exists(path):
        raise SystemExit(f'{path} exists')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(STARTER, f, ensure_ascii=False, indent=1)
    print(f'config: {near(path)} (a starter one: yours to edit, see docs/config.md)')


def kill_group(p):
    """Stop a whole process group: the session bus, the nested compositor or X server and the engine."""
    if p is None:
        return
    for sig, wait in ((signal.SIGTERM, 15), (signal.SIGKILL, 10)):
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            return
        try:
            p.wait(wait)
            return
        except subprocess.TimeoutExpired:
            pass


class KWin:
    """A virtual KDE Plasma 6 compositor (kwin_wayland --virtual) with its own D-Bus session: nothing appears on the
    user's desktop, and the engine can render on the GPU."""
    name = 'kwin'
    env = {'SDL_VIDEODRIVER': 'wayland'}
    unset = ('DISPLAY',)

    def __init__(self, rundir, genv, size):
        self.rundir, self.genv, self.size, self.n, self.p, self.sock = rundir, genv, size, 0, None, None

    def start(self, inner, log):
        self.n += 1
        # a bus without activation of services: with the default one, Qt inside KWin registers with the desktop
        # portal and wakes it up, the secret service wakes up with it, and both outlive their bus
        bus = os.path.join(self.rundir, '.bus.conf')
        with open(bus, 'w') as f:
            f.write('<busconfig><type>session</type><keep_umask/><listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth>'
                    '<policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/>'
                    '<allow own="*"/></policy></busconfig>\n')
        self.sock = f'renpy-capture-{os.getpid()}-{threading.get_ident() % 100000}-{self.n}'
        cmd = ['dbus-run-session', f'--config-file={bus}', '--', 'kwin_wayland', '--virtual',
               '--width', str(self.size[0]), '--height', str(self.size[1]), '--socket', self.sock,
               '--no-lockscreen', '--exit-with-session', inner]
        env = dict(os.environ)
        env.update(self.genv)                       # without EGL of the engine's vendor KWin falls back to QPainter
        self.p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=env)
        return self.p

    def stop(self):
        kill_group(self.p)

    def cleanup(self):
        if not self.sock:                           # never started
            return
        rt = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
        for f in (self.sock, self.sock + '.lock'):
            try:
                os.remove(os.path.join(rt, f))
            except OSError:
                pass


class Xvfb:
    """A virtual X server (Xvfb). It has no GPU: the engine renders with Mesa's software OpenGL (llvmpipe)."""
    name = 'xvfb'
    env = {'SDL_VIDEODRIVER': 'x11', '__GLX_VENDOR_LIBRARY_NAME': 'mesa'}
    unset = ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS')

    def __init__(self, rundir, genv, size):
        self.size, self.genv, self.p, self.x = size, genv, None, None

    def start(self, inner, log):
        r, w = os.pipe()
        xenv = dict(os.environ)                     # the X server too loads the drivers it finds (see vendor_env)
        xenv.update(self.genv)
        self.x = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0', f'{self.size[0]}x{self.size[1]}x24',
                                   '-nolisten', 'tcp', '-noreset'], pass_fds=(w,), stdout=log,
                                  stderr=subprocess.STDOUT, start_new_session=True, env=xenv)
        os.close(w)
        with os.fdopen(r) as f:
            num = f.readline().strip()
        if not num:
            kill_group(self.x)
            raise SystemExit('Xvfb did not start (see display.log in the output folder)')
        env = dict(os.environ, DISPLAY=':' + num)
        self.p = subprocess.Popen([inner], stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=env)
        return self.p

    def stop(self):
        kill_group(self.p)
        kill_group(self.x)

    def cleanup(self):
        kill_group(self.x)


class Window:
    """The user's own desktop: the game window is visible while the capture runs (do not touch it)."""
    name = 'window'
    env, unset = {}, ()

    def __init__(self, rundir, genv, size):
        self.p = None

    def start(self, inner, log):
        self.p = subprocess.Popen([inner], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return self.p

    def stop(self):
        kill_group(self.p)

    def cleanup(self):
        pass


class WinWindow:
    """Windows, the user's desktop: the game window is visible while the capture runs (do not touch it). The engine
    and whatever it starts run in a Job Object: they die with the capture, also on Ctrl+C."""
    name = 'window'
    env, unset = {}, ()

    def __init__(self, rundir, genv, size):
        self.rundir, self.p, self.job = rundir, None, None

    def start(self, launch, log):
        from . import winproc
        self.job = winproc.Job()
        with open(launch.log, 'ab') as out:
            out.seek(0, os.SEEK_END)                # the engine gets the handle, not Python's append mode: it writes
            self.p = winproc.start(launch.cmd, launch.env, out, self.job, self.desktop())   # where this one points
        return self.p

    def desktop(self):
        return None

    def stop(self):
        if self.job is None:
            return
        self.job.kill()
        try:
            self.p.wait(10)
        except subprocess.TimeoutExpired:
            pass
        self.job.close()
        self.job = None

    def cleanup(self):
        pass


class WinOffscreen(WinWindow):
    """Windows, the user's desktop, with the game window kept beyond the edge of the screen: it is still drawn, but
    not seen (it shows for a moment at each start of the engine, and in the taskbar)."""
    name = 'offscreen'

    def start(self, launch, log):
        from . import winproc
        p = super().start(launch, log)
        self.mover = winproc.Mover(p.pid)
        self.mover.start()
        return p

    def stop(self):
        mover = getattr(self, 'mover', None)
        if mover:
            mover.stop()
        super().stop()


class WinDesktop(WinWindow):
    """Windows, a desktop of its own (CreateDesktop): the game window is never on the user's screen, and the user's
    mouse and keyboard never reach it."""
    name = 'desktop'
    count = 0

    def desktop(self):
        from . import winproc
        WinDesktop.count += 1
        self.desk = winproc.Desktop(f'renpy-capture-{os.getpid()}-{threading.get_ident() % 100000}-'
                                    f'{WinDesktop.count}')
        return self.desk.name

    def stop(self):
        super().stop()
        desk = getattr(self, 'desk', None)
        if desk:
            desk.close()


def default_display():
    if WINDOWS:                                     # measured on windows-latest: the same frames, to the byte, as
        return 'desktop'                            # window and offscreen, and nothing on the user's screen
    if shutil.which('kwin_wayland') and shutil.which('dbus-run-session'):
        return 'kwin'
    if shutil.which('Xvfb'):
        return 'xvfb'
    return 'window'


def render_nodes(gpu):
    """Render nodes (/dev/dri/renderD*) of one vendor's GPUs, by the kernel driver behind each: 'nvidia' — NVIDIA's
    own driver, 'mesa' — every other one (amdgpu, i915, xe, nouveau…, the ones Mesa drives)."""
    nodes = []
    for d in sorted(os.listdir(DRM_SYSFS)) if os.path.isdir(DRM_SYSFS) else ():
        if d.startswith('renderD'):
            driver = os.path.basename(os.path.realpath(os.path.join(DRM_SYSFS, d, 'device', 'driver')))
            if (driver == 'nvidia') == (gpu == 'nvidia'):
                nodes.append('/dev/dri/' + d)
    return nodes


def vendor_env(gpu):
    """The environment that keeps a program on one vendor's drivers: 'nvidia' or 'mesa' ({} for 'auto'). Each graphics
    API picks drivers from its own list, EGL and GLX through glvnd, Vulkan through its loader, and a program that only
    looks at a driver still loads it. NVIDIA's opens the card as it loads, which wakes a sleeping NVIDIA GPU: Xvfb
    does it through EGL just by starting, KWin through Vulkan once a client connects and through its renderer on every
    GPU it finds (KWin 6 keeps to KWIN_RENDER_NODES when it is set). VK_LOADER_DRIVERS_DISABLE needs Vulkan loader
    1.3.234 or newer; older ones ignore it."""
    if gpu == 'auto':
        return {}
    if WINDOWS:
        print(f'gpu {gpu!r}: on Windows the system chooses the GPU (Windows settings, Graphics), not renpy-capture')
        return {}
    egl = EGL.get(gpu)
    if egl is None or not os.path.exists(egl):
        print(f'gpu {gpu!r}: no {egl or "known EGL vendor file"} here, leaving the GPU choice to the system')
        return {}
    env = {'__EGL_VENDOR_LIBRARY_FILENAMES': egl, '__GLX_VENDOR_LIBRARY_NAME': gpu}
    if gpu == 'mesa':
        env['VK_LOADER_DRIVERS_DISABLE'] = '*nvidia*'
        # KWin often runs with file capabilities (cap_sys_nice), and in such a program the Vulkan loader ignores
        # its environment: KWin's own switch is the only way to keep it off NVIDIA's Vulkan driver
        env['KWIN_DISABLE_VULKAN'] = '1'
    nodes = render_nodes(gpu)
    if nodes:
        env['KWIN_RENDER_NODES'] = ':'.join(nodes)
    return env


def make_display(name, rundir, genv, size):
    name = name or default_display()
    native = ('window', 'offscreen', 'desktop') if WINDOWS else ('kwin', 'xvfb', 'window')
    if name not in DISPLAYS:
        raise SystemExit(f'unknown display {name!r}: one of {", ".join(native)}')
    if name not in native:
        raise SystemExit(f'display {name!r} is not there on {"Windows" if WINDOWS else "this system"}: '
                         f'one of {", ".join(native)}')
    if WINDOWS:
        return {'window': WinWindow, 'offscreen': WinOffscreen, 'desktop': WinDesktop}[name](rundir, genv, size)
    need = {'kwin': ('kwin_wayland', 'dbus-run-session'), 'xvfb': ('Xvfb',)}.get(name, ())
    missing = [c for c in need if not shutil.which(c)]
    if missing:
        raise SystemExit(f'display {name!r} needs {", ".join(missing)}, which is not installed')
    return {'kwin': KWin, 'xvfb': Xvfb, 'window': Window}[name](rundir, genv, size)


def sweep(sdk_dir, rundir):
    """Kill an engine of this launch folder that outlived its process group (its command line runs the SDK's
    Python on exactly this folder; a worker folder <rundir>-w0 is another folder). On Windows its Job Object has
    killed it already."""
    if not os.path.isdir('/proc'):
        return
    lib, rd = os.path.join(sdk_dir, 'lib') + os.sep, os.path.abspath(rundir)
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            args = read_bytes(f'/proc/{pid}/cmdline').decode(errors='replace').split('\0')
        except OSError:
            continue
        if any(a.startswith(lib) for a in args) and any(a.rstrip(os.sep) == rd for a in args):
            try:
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass


def current_job(out):
    """The job that is running now: the last "start" without an "end" in the log; '?' when none has started."""
    cur = '?'
    p = os.path.join(out, 'log.jsonl')
    if os.path.exists(p):
        for r in read_jsonl(p):
            if r['ev'] == 'start':
                cur = r['job']
            elif r['ev'] == 'end' and r['job'] == cur:
                cur = None
    return cur or '?'


class Progress:
    """How far a capture is, in one line: jobs done out of all, lines captured, the job under way. On a terminal the
    line is rewritten in place every few seconds; elsewhere (a log file, CI) it is printed every half minute. Reads
    the logs as they grow: the capture's own and, with several engines, those of the batches under way (a batch's
    records also reach the capture's log when it ends, so a job already marked done there is not counted twice)."""

    def __init__(self, out, total):
        self.out, self.total = out, total
        self.tty = sys.stdout.isatty()
        self.pos, self.jobs, self.cur = {}, {}, {}      # per log: bytes read, lines per job, the job under way
        self.width, self.last = 0, time.time()

    def _scan(self, path):
        try:
            size = os.path.getsize(path)
        except OSError:                             # a batch folder removed: its jobs are in the capture's log now
            for d in (self.pos, self.jobs, self.cur):
                d.pop(path, None)
            return
        if size < self.pos.get(path, 0):            # a new batch in the same folder: start over
            self.pos[path], self.jobs[path] = 0, {}
        with open(path, 'rb') as f:
            f.seek(self.pos.get(path, 0))
            data = f.read()
        end = data.rfind(b'\n') + 1                 # a record still being written waits for the next look
        self.pos[path] = self.pos.get(path, 0) + end
        counts = self.jobs.setdefault(path, {})
        for line in data[:end].splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get('ev') == 'shot':
                counts[r.get('job')] = counts.get(r.get('job'), 0) + 1
            elif r.get('ev') == 'start':
                self.cur[path] = r.get('job')
            elif r.get('ev') == 'end':
                self.cur[path] = None

    def numbers(self):
        """How far the capture is: jobs done out of all, lines captured, the job under way (``now``, None when none or
        several; ``engines`` counts those at work)."""
        main = os.path.join(self.out, 'log.jsonl')
        work = os.path.join(self.out, 'work')
        logs = [main] + sorted(os.path.join(work, d, 'log.jsonl') for d in
                               (os.listdir(work) if os.path.isdir(work) else ()) if d.startswith('w'))
        for p in logs + [p for p in list(self.pos) if p not in logs]:
            self._scan(p)
        dp = os.path.join(self.out, 'done.txt')
        done = read_done(dp)
        lines = sum(self.jobs.get(main, {}).values())
        lines += sum(n for p, c in self.jobs.items() if p != main for j, n in c.items() if j not in done)
        now = [j for p, j in self.cur.items() if j and j not in done]
        return {'jobs_done': min(len(done), self.total), 'jobs_total': self.total, 'lines': lines,
                'now': now[0] if len(now) == 1 else None, 'engines': len(now)}

    @staticmethod
    def text(n):
        what = (f"now {n['now']}" if n['engines'] == 1 else f"{n['engines']} engines at work" if n['engines'] else
                'finishing' if n['jobs_done'] >= n['jobs_total'] else 'starting')
        return (f'  {n["jobs_done"]} of {plural(n["jobs_total"], "job")} done, {plural(n["lines"], "line")}, {what}')

    def line(self):
        return self.text(self.numbers())

    def update(self):
        """Called every second or two. A program that reads the output (``--progress-json``) gets the numbers every
        time; a person gets a line every half minute, or in place every time on a terminal."""
        due = self.tty or time.time() - self.last >= 30
        if not due and not events.active():
            return
        n = self.numbers()
        events.emit('progress', **n)
        if not due:
            return
        self.last = time.time()
        text = self.text(n)
        if self.tty:
            sys.stdout.write('\r' + text.ljust(self.width))
            self.width = len(text)
        else:
            sys.stdout.write(text + '\n')
        sys.stdout.flush()

    def clear(self):
        if self.tty and self.width:
            sys.stdout.write('\r' + ' ' * self.width + '\r')
            sys.stdout.flush()
            self.width = 0


def _parse_size(v):
    if not v:
        return SCREEN
    if isinstance(v, str):
        m = re.fullmatch(r'(\d+)x(\d+)', v)
        if not m:
            raise SystemExit(f'screen size {v!r}: expected WIDTHxHEIGHT')
        return int(m.group(1)), int(m.group(2))
    return int(v[0]), int(v[1])


def _engine_env(info, rundir, cfg_path, out, disp, genv, timewarp, fast, text, language):
    """The environment of the engine: the capture's own switches, the display's and the GPU vendor's."""
    env = {'HOME': os.path.join(rundir, 'home'), 'SDL_AUDIODRIVER': 'dummy', 'RENPY_TIMEWARP': str(timewarp),
           'RENPY_CAPTURE_FAST': '1' if fast else '0', 'RENPY_CAPTURE_TEXT': '1' if text else '0',
           'RENPY_SKIP_MAIN_MENU': '1', 'RENPY_SKIP_SPLASHSCREEN': '1',
           'RENPY_GL_VSYNC': '0',      # Ren'Py only slows itself down with vsync; a 60 Hz screen does not matter here
           'PYTHONHASHSEED': '0',      # the order of sets (image attributes, a game's own sets) is the same every run
           'RENPY_CAPTURE_CONFIG': os.path.abspath(cfg_path), 'RENPY_CAPTURE_OUT': os.path.abspath(out),
           'RENPY_CAPTURE_BASE': os.path.dirname(game_dir(info['game'])),   # the game's own folder: its relative
                                                                              # search paths start there
           'PATH': os.path.join(rundir, 'bin') + os.pathsep + os.environ.get('PATH', '/usr/bin:/bin'),
           'BROWSER': 'true'}
    env.update(genv)
    if language:                                    # the engine starts in this language (a folder game/tl/<name>)
        tl = os.path.join(game_dir(info['game']), 'tl', language)
        if not os.path.isdir(tl):
            raise SystemExit(f"language {language!r}: the game has no {tl}")
        env['RENPY_LANGUAGE'] = language
    env.update(disp.env)
    if WINDOWS:
        home = os.path.join(os.path.abspath(rundir), 'home')
        env.update({'APPDATA': home,                                    # saves and persistent data, the game's
                    'RENPY_PATH_TO_SAVES': os.path.join(home, '.renpy'),   # and those games share, stay in the launch
                                                                           # folder, as HOME keeps them on Linux
                    'RENPY_EDIT_PY': os.path.join(os.path.abspath(rundir), 'bin', NO_EDITOR),   # an error opens no editor
                    'SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN': '1'})             # the window leaves the keyboard alone
    # Live2D: the SDK from renpy.org has no Cubism Core (Live2D licenses it), a game with Live2D ships it in its own
    # lib/, and the engine looks for it next to itself, then by name: a folder with one link to the game's core
    lib = os.path.join(os.path.dirname(game_dir(info['game'])), 'lib')
    if WINDOWS:
        cores = [os.path.join(lib, d, 'Live2DCubismCore.dll') for d in ('py3-windows-x86_64', 'py2-windows-x86_64')]
    else:
        cores = [os.path.join(lib, 'py3-linux-x86_64', 'libLive2DCubismCore.so')]
    core = next((c for c in cores if os.path.exists(c)), None)
    if core:
        l2d = os.path.join(os.path.abspath(rundir), 'live2d')
        os.makedirs(l2d, exist_ok=True)
        name = os.path.basename(core)
        if not os.path.lexists(os.path.join(l2d, name)):
            _place(core, os.path.join(l2d, name))
        if WINDOWS:                                 # a DLL by name is looked for on PATH too
            env['PATH'] = l2d + os.pathsep + env['PATH']
        else:
            env['LD_LIBRARY_PATH'] = l2d
    return env


def _write_launcher(rundir, sdk_dir, disp, env, rlog):
    """The script the display runs: the engine under ``env``, minus what the display wants unset, its output to
    renpy.log. Returns its path. The engine gets the niceness of the capture back: KWin, which runs with a real-time
    priority of its own, starts it at niceness 0, and `nice renpy-capture …` would slow down only the host side."""
    inner = os.path.join(rundir, '.inner.sh')
    n = os.getpriority(os.PRIO_PROCESS, 0) if hasattr(os, 'getpriority') else 0
    nice = f'nice -n $(( {n} - $(nice) )) ' if n > 0 else ''
    with open(inner, 'w') as f:
        f.write('#!/bin/sh\nexec ' + nice + 'env ' + ' '.join(f'-u {u}' for u in disp.unset) + ' '
                + ' '.join(f'{k}={shlex.quote(v)}' for k, v in env.items())
                + f' {shlex.quote(os.path.join(sdk_dir, "renpy.sh"))} {shlex.quote(os.path.abspath(rundir))}'
                + f' >> {shlex.quote(os.path.abspath(rlog))} 2>&1\n')
    os.chmod(inner, 0o755)
    return inner


Launch = collections.namedtuple('Launch', 'cmd env log')


def _launcher(rundir, sdk_dir, disp, env, rlog):
    """What the display starts: on Linux the script of _write_launcher; on Windows, which has no shell to put between,
    the engine's command, its whole environment and the file for its output (a Launch)."""
    if not WINDOWS:
        return _write_launcher(rundir, sdk_dir, disp, env, rlog)
    full = dict(os.environ)
    for u in disp.unset:
        full.pop(u, None)
    full.update(env)
    return Launch(sdkmod.engine(sdk_dir) + [os.path.abspath(rundir)], full, os.path.abspath(rlog))


def _fresh_start(rundir, sdk_dir):
    """Every launch starts with default persistent data (plus the config's values): earlier launches in this folder
    leave no "seen" marks behind. And no traceback of an earlier launch is taken for this one's, and no engine of a
    capture that was killed outright (its engine outlived it) goes on writing into this one's output."""
    sweep(sdk_dir, rundir)
    for f in ('traceback.txt', 'errors.txt'):
        p = os.path.join(rundir, f)
        if os.path.exists(p):
            os.remove(p)
    stale = [os.path.join(rundir, 'game', 'saves', 'persistent'),
             os.path.join(rundir, 'game', 'saves', 'sync', 'persistent')]
    home = os.path.join(rundir, 'home', '.renpy')
    if os.path.isdir(home):
        stale += [os.path.join(home, d, 'persistent') for d in os.listdir(home)]
    for p in stale:
        if os.path.isfile(p):
            os.remove(p)


def forget_unfinished(out):
    """The engine skips the jobs of done.txt and captures every other one from its first line, so what a job recorded
    before it was interrupted would be in the log twice, and each of its lines twice in the pages. A capture that was
    killed outright (Cancel is that on Windows, and so is a crash or a power cut) leaves such a job, and the half of a
    record that the kill cut off: both are dropped from the log here, before the engine goes on. Returns how many
    records it dropped."""
    log = os.path.join(out, 'log.jsonl')
    if not os.path.exists(log):
        return 0
    done = read_done(os.path.join(out, 'done.txt'))
    kept, dropped = [], 0
    with open(log, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:                      # half a record: the kill came in the middle of its write
                dropped += 1
                continue
            if isinstance(r, dict) and 'job' in r and r['job'] not in done:
                dropped += 1
            else:
                kept.append(line)
    if dropped or (kept and not kept[-1].endswith('\n')):
        tmp = log + '.new'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.writelines(line if line.endswith('\n') else line + '\n' for line in kept)
        os.replace(tmp, log)
    return dropped


def run(rundir, cfg_path, out, timewarp=4.0, stall=180, display=None, gpu=None, screen=None, fast=False,
        language=None, text=False, quiet=False, progress=True):
    """Run the jobs of a config in one engine. A watchdog restarts the engine when the log has not grown for
    ``stall`` seconds (a hung job is recorded and skipped); an interrupted run continues from the first job that
    is not done. A line tells how far it is while it runs (``progress``); ``quiet`` leaves the report at the end to
    the caller."""
    info = _info(rundir)
    link_game(info, rundir)
    cfg = read_json(cfg_path)
    sdk_dir = info.get('sdk') or sdkmod.ensure(info['version'])
    os.makedirs(out, exist_ok=True)
    rlog = os.path.join(out, 'renpy.log')
    gpu = gpu or cfg.get('gpu') or 'auto'
    display = display or cfg.get('display') or default_display()
    if display == 'xvfb':                           # Xvfb has no GPU: Mesa renders in software
        gpu = 'mesa'
    genv = vendor_env(gpu)
    disp = make_display(display, rundir, genv, _parse_size(screen or cfg.get('screen')))
    env = _engine_env(info, rundir, cfg_path, out, disp, genv, timewarp, fast, text, language or cfg.get('language'))
    inner = _launcher(rundir, sdk_dir, disp, env, rlog)
    _fresh_start(rundir, sdk_dir)
    forget_unfinished(out)                          # (after the sweep: an engine that outlived its capture is gone)
    log, done = os.path.join(out, 'log.jsonl'), os.path.join(out, 'done.txt')
    ids = [j['id'] for j in cfg['jobs']]
    bar = Progress(out, len(ids)) if progress else None
    rc = None
    while True:
        hung = None
        with open(os.path.join(out, 'display.log'), 'a') as dl:
            p = disp.start(inner, dl)
            try:
                size, since = -1, time.time()
                while p.poll() is None:
                    time.sleep(1)                   # a window that watches the progress wants it every second
                    if bar:
                        bar.update()
                    cur = os.path.getsize(log) if os.path.exists(log) else 0
                    if cur != size:
                        size, since = cur, time.time()
                    elif time.time() - since > stall:
                        hung = current_job(out)
                        pulse = os.path.join(out, 'pulse.json')
                        if os.path.exists(pulse):
                            shutil.copy(pulse, os.path.join(out, f'pulse-stall-{hung}.json'))
                        break
            finally:
                disp.stop()
                disp.cleanup()
                sweep(sdk_dir, rundir)
            rc = p.returncode
        if bar:
            bar.clear()
        if hung is None:
            break
        if hung == '?':
            print(f'the engine did not start a single job, see {rlog}')
            break
        with open(log, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ev': 'stop', 'job': hung, 'why': 'stall'}, ensure_ascii=False) + '\n')
            f.write(json.dumps({'ev': 'end', 'job': hung, 'why': 'stall'}, ensure_ascii=False) + '\n')
        with open(done, 'a', encoding='utf-8') as f:
            f.write(hung + '\n')
        print(f'job {hung} hung, going on with the next one')
        finished = read_done(done)
        if all(i in finished for i in ids):
            break
    tb = os.path.join(rundir, 'traceback.txt')
    if os.path.exists(tb):
        shutil.copy(tb, os.path.join(out, 'traceback.txt'))
        print(read_text(tb, errors='replace')[-3000:])
    fatal = os.path.join(out, 'fatal.txt')
    if os.path.exists(fatal):
        print('engine: ' + read_text(fatal, errors='replace')[-2000:])
    if rc:
        print(f'engine exit code: {rc}')
    if not quiet:
        report(out)


def merge_jobs(src, out, ids, recs):
    """The output of a batch of a worker goes into the common output: records of the successful jobs only (in a row,
    as in the batch), their "done" marks, and all frames (an extra frame of a failed job is never mentioned by the
    log, so it does no harm)."""
    os.makedirs(os.path.join(out, 'frames'), exist_ok=True)
    with open(os.path.join(out, 'log.jsonl'), 'a', encoding='utf-8') as f:
        for r in recs:
            if r.get('job') in ids:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    with open(os.path.join(out, 'done.txt'), 'a', encoding='utf-8') as f:
        for i in ids:
            f.write(i + '\n')
    fd = os.path.join(src, 'frames')
    for f in os.listdir(fd) if os.path.isdir(fd) else []:
        dst = os.path.join(out, 'frames', f)
        if os.path.exists(dst):
            os.remove(os.path.join(fd, f))
        else:
            os.replace(os.path.join(fd, f), dst)


def healthy(recs):
    """An engine whose GL broke in the middle of a job (out of video memory) paints one flat colour: different
    scene states give one and the same frame. Healthy jobs have at least 0.4 distinct frames per distinct state."""
    contents, frames = set(), set()
    for r in recs:
        if r.get('ev') == 'shot' and r.get('frame') and not r.get('same'):
            contents.add(json.dumps([r.get('shown'), r.get('screens'), r.get('cam')], ensure_ascii=False))
            frames.add(r['frame'])
    return len(contents) < 20 or len(frames) >= 0.4 * len(contents)


def prun(rundir, cfg_path, out, workers=4, timewarp=4.0, batch=8, display=None, gpu=None, screen=None, fast=False,
         language=None, text=False, quiet=False):
    """Jobs on several engines at once. A worker has its own launch folder (<rundir>-wN: links to the same game,
    its own saves and HOME) and its own display. It takes a batch of jobs from the common queue (up to ``batch``; the
    tail of the queue is shared evenly) and runs it in one engine, so the display and the game do not start again
    for every job. A job without an end (the engine died, no window) or with broken GL goes back to the end of the
    queue for another launch; after three failures it is given up."""
    cfg = read_json(cfg_path)
    os.makedirs(os.path.join(out, 'frames'), exist_ok=True)
    forget_unfinished(out)                          # (a batch is merged before its jobs are marked done)
    dpath = os.path.join(out, 'done.txt')
    done = read_done(dpath)
    queue = [j for j in cfg['jobs'] if j['id'] not in done]
    info = _info(rundir)
    if not info.get('sdk'):                         # once, before the workers: together they would all download it
        sdkmod.ensure(info['version'])
    lock = threading.Lock()
    tries = collections.Counter()
    nworkers = max(1, min(workers, len(queue)))
    failed = []

    def worker(k):
        try:
            work(k)
        except BaseException as e:                  # a thread drops SystemExit silently: keep it for the end
            if not isinstance(e, SystemExit):
                traceback.print_exc()
            with lock:
                failed.append((k, e))

    def work(k):
        rd = f'{os.path.abspath(rundir).rstrip(os.sep)}-w{k}'
        with lock:                                  # workers follow the main folder (game, version, exclude)
            setup(info['game'], rd, info.get('version'), info.get('sdk'), info.get('exclude'), quiet=True)
        time.sleep(4 * k)                           # launches spread out: a dozen displays and GL contexts at once
        launch = 0                                  # leave some engine without a window ("Invalid window")
        while True:
            with lock:
                if not queue:
                    return
                n = max(1, min(batch, -(-len(queue) // nworkers)))
                jobs = [queue.pop(0) for _ in range(min(n, len(queue)))]
            launch += 1
            wout = os.path.join(out, 'work', f'w{k}')
            if os.path.isdir(wout):
                shutil.rmtree(wout)
            os.makedirs(wout)
            wcfg = os.path.join(wout, 'cfg.json')
            with open(wcfg, 'w', encoding='utf-8') as f:
                json.dump(dict(cfg, jobs=jobs), f, ensure_ascii=False)
            run(rd, wcfg, wout, timewarp, display=display, gpu=gpu, screen=screen, fast=fast, language=language,
                text=text, quiet=True, progress=False)
            lp = os.path.join(wout, 'log.jsonl')
            recs = read_jsonl(lp) if os.path.exists(lp) else []
            by = collections.defaultdict(list)
            for r in recs:
                by[r.get('job')].append(r)
            good, bad = [], []
            for job in jobs:
                jr = by.get(job['id'], [])
                ok = any(r.get('ev') == 'end' for r in jr) and not any(
                    r.get('ev') == 'error' and 'Invalid window' in r.get('error', '') for r in jr) and healthy(jr)
                (good if ok else bad).append(job)
            with lock:
                merge_jobs(wout, out, {j['id'] for j in good}, recs)
                for job in bad:
                    tries[job['id']] += 1
                    if tries[job['id']] < 3:
                        queue.append(job)
                    else:
                        print(f"job {job['id']}: three launches without an end, given up")
            if bad:
                fail = os.path.join(out, 'work', 'failed', f'w{k}-{launch}')
                shutil.rmtree(fail, ignore_errors=True)
                os.makedirs(os.path.dirname(fail), exist_ok=True)
                os.replace(wout, fail)
                print(f"batch w{k}-{launch}: no end for {', '.join(j['id'] for j in bad)}, queued again")
                time.sleep(20)                      # let a storm of launches pass before retrying

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(nworkers)]
    for t in threads:
        t.start()
    bar = Progress(out, len(cfg['jobs']))
    while any(t.is_alive() for t in threads):
        time.sleep(1)
        bar.update()
    bar.clear()
    for t in threads:
        t.join()
    if os.path.exists(os.path.join(out, 'log.jsonl')) and not quiet:
        report(out)
    if failed:                                      # the other workers went on; the stopped one's batch is not done
        k, e = failed[0]
        why = e.code if isinstance(e, SystemExit) else f'{type(e).__name__}: {e}'
        raise SystemExit(f'worker w{k} stopped: {why}\nfinished jobs are kept; run the same command again to go on')


def explore(rundir, cfg_path, out, rounds=10, timewarp=4.0, limit=600, workers=1, batch=8, display=None, gpu=None,
            screen=None, fast=False, language=None, text=False):
    """Rounds until the branches run out: every option of every menu met (file:line) is taken at least once. A new
    job repeats the choices made before that menu in a finished job, takes an option not taken yet, and then the
    first options. New jobs are added to the config (id "<job>~<choices>"). Returns whether every branch was taken
    (not when the rounds ran out, or when branches were left out because the config reached ``limit`` jobs)."""
    cfg = read_json(cfg_path)
    dropped = set()                                 # the branches over the limit; the next round meets them again
    for rnd in range(rounds):
        engine = dict(timewarp=timewarp, display=display, gpu=gpu, screen=screen, fast=fast, language=language,
                      text=text, quiet=True)
        if workers > 1:
            prun(rundir, cfg_path, out, workers=workers, batch=batch, **engine)
        else:
            run(rundir, cfg_path, out, **engine)
        stats = report(out, brief=True)             # warnings and failed jobs only; `report` has the whole table
        try:
            recs = read_jsonl(os.path.join(out, 'log.jsonl'))
        except FileNotFoundError:                   # the engine never got as far as its first line
            raise SystemExit(f"nothing was captured: the engine did not record a single line (what it and the "
                             f"screen said: {near(os.path.join(out, 'renpy.log'))}, "
                             f"{near(os.path.join(out, 'display.log'))})") from None
        seen, menus = set(), collections.defaultdict(list)
        looped = set()                              # stopped as a loop: a mini-game gauge moved by screen timers,
        for r in recs:                              # retried with the timers running
            if r['ev'] == 'shot' and r.get('menu') and 'pick' in r['menu']:   # waiting on a menu is not a choice
                m = r['menu']
                menus[r['job']].append((r['file'], r['line'], len(m['options']), m['pick']))
                seen.add((r['file'], r['line'], m['pick']))
            elif r['ev'] == 'stop' and r.get('why') == 'loop':
                looped.add(r['job'])
        new, ids = [], {j['id'] for j in cfg['jobs']}
        for job in cfg['jobs']:
            vid = job['id'] + '~timers'
            if job['id'] in looped and not job.get('ui_timers') and vid not in ids:
                new.append(dict(job, id=vid, ui_timers=True, loop_limit=400))
                ids.add(vid)
        for job in cfg['jobs']:
            path = []
            for f, ln, n, k in menus.get(job['id'], []):
                for j in range(n):
                    if (f, ln, j) in seen:
                        continue
                    seen.add((f, ln, j))
                    nid = f"{job['id'].split('~')[0]}~{'.'.join(map(str, path + [j]))}"
                    if nid in ids:
                        continue
                    if len(cfg['jobs']) + len(new) < limit:
                        new.append(dict(job, id=nid, choices=path + [j]))
                        ids.add(nid)
                    else:
                        dropped.add(nid)
                path.append(k)
        print(f"round {rnd + 1}: {plural(stats['jobs'], 'job')}, {plural(stats['lines'], 'line')}, "
              f"{plural(stats['pictures'], 'picture')}; "
              + (f"{plural(len(new), 'new branch', 'new branches')} to take" if new else 'no branch left to take'))
        if not new:
            break
        cfg['jobs'] += new
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    else:
        print(f'stopped after {rounds} rounds; run explore again to go on', file=sys.stderr)
        return False
    if dropped:
        print(f'{len(dropped)} branches left out: the config reached {limit} jobs (raise it with --limit)',
              file=sys.stderr)
    return not dropped
