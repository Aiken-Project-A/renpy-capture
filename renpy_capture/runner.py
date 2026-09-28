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

from . import sdk as sdkmod
from .analysis import report
from .game import MODS, engine_version, game_dir
from .util import read_bytes, read_json, read_jsonl, read_text

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURE_RPY = os.path.join(HERE, 'capture.rpy')
RPY_NAME = 'zz_renpy_capture.rpy'
RUN_INFO = 'renpy-capture.json'
EGL = {'nvidia': '/usr/share/glvnd/egl_vendor.d/10_nvidia.json',
       'mesa': '/usr/share/glvnd/egl_vendor.d/50_mesa.json'}
SCREEN = (1920, 1200)
DISPLAYS = ('kwin', 'xvfb', 'window')
STARTER = {'jobs': [{'id': 'start', 'label': 'start'}], 'ui': '.*', 'settle': 0.3, 'settle_max': 1.2,
           'max_steps': 3000, 'loop_limit': 40}


def _info(rundir):
    p = os.path.join(rundir, RUN_INFO)
    if not os.path.exists(p):
        raise SystemExit(f'{rundir}: not a launch folder (run `renpy-capture setup` first)')
    return read_json(p)


def setup(game, rundir, version=None, sdk_dir=None, exclude=None):
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
        raise SystemExit("cannot tell the game's Ren'Py version: pass --renpy-version (or --sdk)")
    os.makedirs(os.path.join(rundir, 'home'), exist_ok=True)
    stub = os.path.join(rundir, 'bin')              # a crashing engine opens traceback.txt with xdg-open: no editor
    os.makedirs(stub, exist_ok=True)                # windows pop up on the user's desktop
    with open(os.path.join(stub, 'xdg-open'), 'w') as f:
        f.write('#!/bin/sh\nexit 0\n')
    os.chmod(os.path.join(stub, 'xdg-open'), 0o755)
    info = {'game': os.path.abspath(game), 'version': version, 'sdk': sdk_dir and os.path.abspath(sdk_dir),
            'exclude': exclude}
    with open(os.path.join(rundir, RUN_INFO), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    link_game(info, rundir)
    print(f"launch folder: {rundir} (Ren'Py {version or 'from ' + sdk_dir})")


def link_game(info, rundir):
    """(Re)make game/ of a launch folder: a link to every file and folder of the game's game/ (not its saves and
    cache, not overlay mods, not ``exclude``) and capture.rpy. The engine's own saves/ and cache/ (compiled bytecode)
    are kept. Called on every run, so the folder follows an updated game."""
    g = game_dir(info['game'])
    rg = os.path.join(rundir, 'game')
    rx = re.compile(info['exclude']) if info.get('exclude') else None
    os.makedirs(rg, exist_ok=True)
    for f in os.listdir(rg):
        p = os.path.join(rg, f)
        if f in ('saves', 'cache'):
            continue
        if not (os.path.islink(p) or f.startswith(RPY_NAME[:-3])):     # capture.rpy and its .rpyc
            raise SystemExit(f'{p} is not a link made by renpy-capture; the launch folder was changed by hand')
        os.remove(p)
    for f in sorted(os.listdir(g)):
        if f in ('saves', 'cache') or f.lower().endswith('.exe') or MODS.search(f) or (rx and rx.search(f)):
            continue
        os.symlink(os.path.join(g, f), os.path.join(rg, f))
    for sub in ('saves', 'cache'):
        os.makedirs(os.path.join(rg, sub), exist_ok=True)
    shutil.copy(CAPTURE_RPY, os.path.join(rg, RPY_NAME))


def init_config(game, path):
    """A starter config: one job that plays the game from `start`, menus answered with the first option (explore
    then takes every other option)."""
    game_dir(game)
    if os.path.exists(path):
        raise SystemExit(f'{path} exists')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(STARTER, f, ensure_ascii=False, indent=1)
    print(f'config: {path}')


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

    def __init__(self, rundir, egl, size):
        self.rundir, self.egl, self.size, self.n, self.p, self.sock = rundir, egl, size, 0, None, None

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
        if self.egl:                                # without EGL of the same vendor KWin falls back to QPainter
            env['__EGL_VENDOR_LIBRARY_FILENAMES'] = self.egl
        self.p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=env)
        return self.p

    def stop(self):
        kill_group(self.p)

    def cleanup(self):
        rt = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
        for f in (self.sock, (self.sock or '') + '.lock'):
            try:
                os.remove(os.path.join(rt, f))
            except (OSError, TypeError):
                pass


class Xvfb:
    """A virtual X server (Xvfb). It has no GPU: the engine renders with Mesa's software OpenGL (llvmpipe)."""
    name = 'xvfb'
    env = {'SDL_VIDEODRIVER': 'x11', '__GLX_VENDOR_LIBRARY_NAME': 'mesa'}
    unset = ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS')

    def __init__(self, rundir, egl, size):
        self.size, self.p, self.x = size, None, None

    def start(self, inner, log):
        r, w = os.pipe()
        self.x = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0', f'{self.size[0]}x{self.size[1]}x24',
                                   '-nolisten', 'tcp', '-noreset'], pass_fds=(w,), stdout=log,
                                  stderr=subprocess.STDOUT, start_new_session=True)
        os.close(w)
        with os.fdopen(r) as f:
            num = f.readline().strip()
        if not num:
            kill_group(self.x)
            raise SystemExit('Xvfb did not start (see kwin.log / display log in the output folder)')
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

    def __init__(self, rundir, egl, size):
        self.p = None

    def start(self, inner, log):
        self.p = subprocess.Popen([inner], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return self.p

    def stop(self):
        kill_group(self.p)

    def cleanup(self):
        pass


def default_display():
    if shutil.which('kwin_wayland') and shutil.which('dbus-run-session'):
        return 'kwin'
    if shutil.which('Xvfb'):
        return 'xvfb'
    return 'window'


def make_display(name, rundir, egl, size):
    name = name or default_display()
    cls = {'kwin': KWin, 'xvfb': Xvfb, 'window': Window}.get(name)
    if cls is None:
        raise SystemExit(f'unknown display {name!r}: one of {", ".join(DISPLAYS)}')
    need = {'kwin': ('kwin_wayland', 'dbus-run-session'), 'xvfb': ('Xvfb',)}.get(name, ())
    missing = [c for c in need if not shutil.which(c)]
    if missing:
        raise SystemExit(f'display {name!r} needs {", ".join(missing)}, which is not installed')
    return cls(rundir, egl, size)


def sweep(sdk_dir, rundir):
    """Kill an engine of this launch folder that outlived its process group (its command line runs the SDK's
    Python on exactly this folder; a worker folder <rundir>-w0 is another folder)."""
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


def _parse_size(v):
    if not v:
        return SCREEN
    if isinstance(v, str):
        m = re.fullmatch(r'(\d+)x(\d+)', v)
        if not m:
            raise SystemExit(f'screen size {v!r}: expected WIDTHxHEIGHT')
        return int(m.group(1)), int(m.group(2))
    return int(v[0]), int(v[1])


def run(rundir, cfg_path, out, timewarp=4.0, stall=180, display=None, gpu=None, screen=None, fast=False):
    """Run the jobs of a config in one engine. A watchdog restarts the engine when the log has not grown for
    ``stall`` seconds (a hung job is recorded and skipped); an interrupted run continues from the first job that
    is not done."""
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
    egl = EGL.get(gpu)
    if gpu != 'auto' and (egl is None or not os.path.exists(egl)):
        print(f'gpu {gpu!r}: no {egl or "known EGL vendor file"} here, leaving the GPU choice to the system')
        egl = None
    disp = make_display(display, rundir, egl, _parse_size(screen or cfg.get('screen')))
    env = {'HOME': os.path.join(rundir, 'home'), 'SDL_AUDIODRIVER': 'dummy', 'RENPY_TIMEWARP': str(timewarp),
           'RENPY_CAPTURE_FAST': '1' if fast else '0',
           'RENPY_SKIP_MAIN_MENU': '1', 'RENPY_SKIP_SPLASHSCREEN': '1',
           'RENPY_GL_VSYNC': '0',      # Ren'Py only slows itself down with vsync; a 60 Hz screen does not matter here
           'RENPY_CAPTURE_CONFIG': os.path.abspath(cfg_path), 'RENPY_CAPTURE_OUT': os.path.abspath(out),
           'PATH': os.path.join(rundir, 'bin') + os.pathsep + os.environ.get('PATH', '/usr/bin:/bin'),
           'BROWSER': 'true'}
    if egl:
        env['__EGL_VENDOR_LIBRARY_FILENAMES'] = egl
        env['__GLX_VENDOR_LIBRARY_NAME'] = 'nvidia' if gpu == 'nvidia' else 'mesa'
    env.update(disp.env)
    # Live2D: the SDK from renpy.org has no Cubism Core (Live2D licenses it), a game with Live2D ships it in its own
    # lib/, and the engine looks for it next to itself, then by name: a folder with one link to the game's core
    core = os.path.join(os.path.dirname(game_dir(info['game'])), 'lib', 'py3-linux-x86_64',
                        'libLive2DCubismCore.so')
    if os.path.exists(core):
        l2d = os.path.join(os.path.abspath(rundir), 'live2d')
        os.makedirs(l2d, exist_ok=True)
        if not os.path.lexists(os.path.join(l2d, 'libLive2DCubismCore.so')):
            os.symlink(core, os.path.join(l2d, 'libLive2DCubismCore.so'))
        env['LD_LIBRARY_PATH'] = l2d
    inner = os.path.join(rundir, '.inner.sh')
    with open(inner, 'w') as f:
        f.write('#!/bin/sh\nexec env ' + ' '.join(f'-u {u}' for u in disp.unset) + ' '
                + ' '.join(f'{k}={shlex.quote(v)}' for k, v in env.items())
                + f' {shlex.quote(os.path.join(sdk_dir, "renpy.sh"))} {shlex.quote(os.path.abspath(rundir))}'
                + f' >> {shlex.quote(os.path.abspath(rlog))} 2>&1\n')
    os.chmod(inner, 0o755)
    for f in ('traceback.txt', 'errors.txt'):
        p = os.path.join(rundir, f)
        if os.path.exists(p):
            os.remove(p)
    # every launch starts with default persistent data (plus the config's values): earlier launches in this folder
    # leave no "seen" marks behind
    stale = [os.path.join(rundir, 'game', 'saves', 'persistent'),
             os.path.join(rundir, 'game', 'saves', 'sync', 'persistent')]
    home = os.path.join(rundir, 'home', '.renpy')
    if os.path.isdir(home):
        stale += [os.path.join(home, d, 'persistent') for d in os.listdir(home)]
    for p in stale:
        if os.path.isfile(p):
            os.remove(p)
    log, done = os.path.join(out, 'log.jsonl'), os.path.join(out, 'done.txt')
    ids = [j['id'] for j in cfg['jobs']]
    rc = None
    while True:
        hung = None
        with open(os.path.join(out, 'display.log'), 'a') as dl:
            p = disp.start(inner, dl)
            try:
                size, since = -1, time.time()
                while p.poll() is None:
                    time.sleep(2)
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
        finished = set(read_text(done).split())
        if all(i in finished for i in ids):
            break
    tb = os.path.join(rundir, 'traceback.txt')
    if os.path.exists(tb):
        shutil.copy(tb, os.path.join(out, 'traceback.txt'))
        print(read_text(tb, errors='replace')[-3000:])
    fatal = os.path.join(out, 'fatal.txt')
    if os.path.exists(fatal):
        print('engine: ' + read_text(fatal, errors='replace')[-2000:])
    print(f'engine exit code: {rc}')
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


def prun(rundir, cfg_path, out, workers=4, timewarp=4.0, batch=8, display=None, gpu=None, screen=None, fast=False):
    """Jobs on several engines at once. A worker has its own launch folder (<rundir>-wN: links to the same game,
    its own saves and HOME) and its own display. It takes a batch of jobs from the common queue (up to ``batch``; the
    tail of the queue is shared evenly) and runs it in one engine, so the display and the game do not start again
    for every job. A job without an end (the engine died, no window) or with broken GL goes back to the end of the
    queue for another launch; after three failures it is given up."""
    cfg = read_json(cfg_path)
    os.makedirs(os.path.join(out, 'frames'), exist_ok=True)
    dpath = os.path.join(out, 'done.txt')
    done = set(read_text(dpath).split()) if os.path.exists(dpath) else set()
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
            setup(info['game'], rd, info.get('version'), info.get('sdk'), info.get('exclude'))
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
            run(rd, wcfg, wout, timewarp, display=display, gpu=gpu, screen=screen, fast=fast)
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
    for t in threads:
        t.join()
    if os.path.exists(os.path.join(out, 'log.jsonl')):
        report(out)
    if failed:                                      # the other workers went on; the stopped one's batch is not done
        k, e = failed[0]
        why = e.code if isinstance(e, SystemExit) else f'{type(e).__name__}: {e}'
        raise SystemExit(f'worker w{k} stopped: {why}\nfinished jobs are kept; run the same command again to go on')


def explore(rundir, cfg_path, out, rounds=10, timewarp=4.0, limit=600, workers=1, batch=8, display=None, gpu=None,
            screen=None, fast=False):
    """Rounds until the branches run out: every option of every menu met (file:line) is taken at least once. A new
    job repeats the choices made before that menu in a finished job, takes an option not taken yet, and then the
    first options. New jobs are added to the config (id "<job>~<choices>")."""
    cfg = read_json(cfg_path)
    for rnd in range(rounds):
        if workers > 1:
            prun(rundir, cfg_path, out, workers, timewarp, batch, display, gpu, screen, fast)
        else:
            run(rundir, cfg_path, out, timewarp, display=display, gpu=gpu, screen=screen, fast=fast)
        seen, menus = set(), collections.defaultdict(list)
        looped = set()                              # stopped as a loop: a mini-game gauge moved by screen timers,
        for r in read_jsonl(os.path.join(out, 'log.jsonl')):           # retried with the timers running
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
                    if nid not in ids and len(cfg['jobs']) + len(new) < limit:
                        new.append(dict(job, id=nid, choices=path + [j]))
                        ids.add(nid)
                path.append(k)
        print(f'round {rnd + 1}: new branches {len(new)}')
        if not new:
            break
        cfg['jobs'] += new
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    else:
        print(f'stopped after {rounds} rounds; run explore again to go on', file=sys.stderr)
