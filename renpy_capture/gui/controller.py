"""What the window decides, with no widget in sight: whether a folder is a game, where the work goes, which arguments
`renpy-capture capture` gets, how a run is going and how it ended, and what is kept for next time. The Tk layer
(app.py) shows it and passes the person's choices in; everything here can be tested without a display.

A capture runs as a child process of its own (``Run``): Cancel ends that process, and a capture that crashes does not
take the window down. Its progress is read as the JSON events of ``--progress-json`` (renpy_capture/events.py), its
text goes to a log file in the work folder."""
import collections
import dataclasses
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

from .. import sdk
from ..game import NoGame, SeveralGames, engine_major, engine_version, game_dir
from ..runner import RUN_INFO
from ..util import read_json
from ..workflow import paths as work_paths
from . import strings as S

WINDOWS = os.name == 'nt'
LOG = 'renpy-capture.log'               # the text of every run, in the work folder
LOOK = 3000                             # folders looked into for a game below the one chosen
KEPT_GAMES = 30                         # games whose choices are remembered
OWN = re.compile(r'(config\.json|run(-w\d+)?|out(-.*)?|export(-.*)?|renpy-capture\.log|\..*|desktop\.ini|thumbs\.db)$',
                 re.I)                  # what renpy-capture itself puts in a work folder (and what Windows adds)


# ---- the system: where things are, how to open them, how to run ourselves

def config_dir():
    """Where the window keeps what it remembers: %APPDATA%\\renpy-capture, ~/.config/renpy-capture elsewhere."""
    if WINDOWS:
        base = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'renpy-capture')


def _windows_documents():
    """The Documents folder where Windows says it is (it may have been moved, to OneDrive for one)."""
    import ctypes
    import uuid
    from ctypes import wintypes
    folder_id = uuid.UUID('FDD39AD0-238F-46AF-ADB4-6C85480369C7').bytes_le          # FOLDERID_Documents
    out = ctypes.c_wchar_p()
    shell, ole = ctypes.WinDLL('shell32'), ctypes.WinDLL('ole32')
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_char_p, wintypes.DWORD, wintypes.HANDLE,
                                           ctypes.POINTER(ctypes.c_wchar_p)]
    try:
        if shell.SHGetKnownFolderPath(folder_id, 0, None, ctypes.byref(out)) == 0:
            return out.value
    finally:
        ole.CoTaskMemFree(out)
    return None


def _xdg_documents():
    try:
        with open(os.path.join(os.path.expanduser('~'), '.config', 'user-dirs.dirs'), encoding='utf-8') as f:
            m = re.search(r'^XDG_DOCUMENTS_DIR="?([^"\n]+)"?', f.read(), re.M)
    except OSError:
        return None
    return os.path.expandvars(m.group(1).replace('$HOME', os.path.expanduser('~'))) if m else None


def synced(path):
    """Is the path inside a folder OneDrive keeps in sync? (Whatever is in one is uploaded, the game's files that are
    linked into a launch folder with it.)"""
    low = os.path.normcase(os.path.abspath(path))
    for var in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial'):
        root = os.environ.get(var)
        if root:
            root = os.path.normcase(os.path.abspath(root)).rstrip(os.sep)
            if low == root or low.startswith(root + os.sep):
                return True
    return False


def documents_folder():
    """The folder the work goes under by default: the person's Documents, or their home folder when Documents is
    kept in sync by OneDrive (the launch folder holds a link to every file of the game, and OneDrive would upload
    them all)."""
    home = os.path.expanduser('~')
    try:
        docs = _windows_documents() if WINDOWS else _xdg_documents()
    except (OSError, ImportError, AttributeError):
        docs = None
    docs = docs or os.path.join(home, 'Documents')
    if not os.path.isdir(docs) or synced(docs):
        return home
    return docs


def open_path(path):
    """Open a page or a folder with what the system opens it with: the browser, the file manager. True if it could."""
    try:
        if WINDOWS:
            os.startfile(path)
        else:
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def child_command():
    """How to start renpy-capture as a program of its own, before its arguments: in the Windows build, the console
    program that stands next to the window's (which opens no console of its own: the window starts it hidden), else
    this Python running the package."""
    if getattr(sys, 'frozen', False):
        console = os.path.join(os.path.dirname(sys.executable), 'renpy-capture' + ('.exe' if WINDOWS else ''))
        return [console if os.path.isfile(console) else sys.executable]
    exe = sys.executable
    if WINDOWS and os.path.basename(exe).lower() == 'pythonw.exe':      # the launcher of a pip-installed window
        console = os.path.join(os.path.dirname(exe), 'python.exe')
        exe = console if os.path.isfile(console) else exe
    return [exe, '-m', 'renpy_capture']


# ---- what is remembered

def _text_or_none(value):
    return value if isinstance(value, str) and value else None


class Settings:
    """The choices of the last runs: one small JSON file in the user's config folder. What is not there, or is not
    what it should be, is forgotten: a damaged file must never keep the window from opening."""

    def __init__(self, path=None):
        self.path = path or os.path.join(config_dir(), 'gui.json')
        self.data = {}
        try:
            data = read_json(self.path)
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            self.data = data

    @staticmethod
    def _key(root):
        return os.path.normcase(os.path.abspath(root))

    @staticmethod
    def _choices(d):
        """The choices of one game, as far as they are what they should be."""
        d = d if isinstance(d, dict) else {}
        out = {}
        for key in ('workdir', 'language', 'version'):
            if _text_or_none(d.get(key)):
                out[key] = d[key]
        if isinstance(d.get('text'), bool):
            out['text'] = d['text']
        return out

    def last(self):
        """The game of the last run (its folder as it was typed) and the choices that went with it."""
        d = self.data.get('last')
        game = _text_or_none(d.get('game')) if isinstance(d, dict) else None
        return (game, self._choices(d)) if game else (None, {})

    def game(self, root):
        return self._choices(self.data.get('games', {}).get(self._key(root)))

    def remember(self, game, root, workdir, language, text, version):
        choices = {'workdir': workdir, 'language': language, 'text': bool(text), 'version': version}
        self.data['last'] = dict(choices, game=game)
        games = self.data['games'] = {k: v for k, v in self.data.get('games', {}).items() if isinstance(v, dict)}
        games.pop(self._key(root), None)                    # the newest goes last, the oldest are forgotten
        games[self._key(root)] = choices
        while len(games) > KEPT_GAMES:
            games.pop(next(iter(games)))
        self.save()

    def window(self):
        """The (width, height) the window had when it was closed, if sensible."""
        d = self.data.get('window')
        if isinstance(d, dict) and all(isinstance(d.get(k), int) and 300 <= d[k] <= 4000 for k in ('width', 'height')):
            return d['width'], d['height']
        return None

    def remember_window(self, width, height):
        self.data['window'] = {'width': int(width), 'height': int(height)}
        self.save()

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.new'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:                                     # nothing remembered is no reason to complain
            pass


# ---- the folders

def clean_path(text):
    """What a person typed or pasted into a folder box, as a path: without the quotes Windows puts round a path it
    copies ("Copy as path"), the blanks around it, with %VARIABLES% and ~ expanded, and absolute. '' for nothing."""
    text = (text or '').strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in '"\'':
        text = text[1:-1].strip()
    if not text:
        return ''
    return os.path.normpath(os.path.abspath(os.path.expanduser(os.path.expandvars(text))))


@dataclasses.dataclass
class GameInfo:
    """What the window knows of the folder it was given. ``version`` is the Ren'Py the game was made with, None when it
    cannot be told (the person is then asked); ``major`` is '7' or '8' when the game's cache tells which ran it."""
    ok: bool
    message: str
    path: str = ''
    root: str = ''
    name: str = ''
    version: object = None
    major: object = None
    languages: tuple = ()


def _languages(game):
    tl = os.path.join(game, 'tl')
    try:
        names = os.listdir(tl)
    except OSError:
        return ()
    return tuple(sorted((n for n in names if os.path.isdir(os.path.join(tl, n)) and n != 'None'
                         and not n.startswith('.')), key=str.lower))


def check_game(text):
    """Is this folder a Ren'Py game, and which? The folder with game/ inside, game/ itself, or a folder around one
    (what `capture` accepts); anything else is said plainly."""
    path = clean_path(text)
    if not path:
        return GameInfo(False, S.GAME_EMPTY)
    if not os.path.exists(path):
        return GameInfo(False, S.GAME_MISSING, path)
    if not os.path.isdir(path):
        return GameInfo(False, S.GAME_IS_FILE, path)
    try:
        game = game_dir(path, LOOK)
    except SeveralGames as e:
        names = sorted(os.path.basename(f) for f in e.found)
        return GameInfo(False, S.GAME_SEVERAL.format(names=', '.join(names[:6]) + (', …' if len(names) > 6 else '')),
                        path)
    except NoGame:
        return GameInfo(False, S.GAME_NONE, path)
    root = os.path.dirname(game)
    name = os.path.basename(root) or root
    try:
        version, major = engine_version(root), engine_major(root)
    except OSError:
        version = major = None
    message = (S.GAME_FOUND_VERSION.format(name=name, version=version) if version
               else S.GAME_FOUND_NO_VERSION.format(name=name))
    return GameInfo(True, message, path, root, name, version, major, _languages(game))


def default_version(major, kept=None):
    """The Ren'Py to offer for a game that does not tell its own: the one kept from last time, else the newest of the
    major version its cache points to (8 when there is no hint: most games of these years)."""
    if kept in sdk.VERSIONS:
        return kept
    return next((v for v in sdk.VERSIONS if v.startswith(f'{major or 8}.')), sdk.VERSIONS[0])


def _inside(path, folder):
    a, b = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:                                      # another drive
        return False


def _drive(path):
    return os.path.splitdrive(os.path.abspath(path))[0].lower()


def _root_of(game):
    """The folder of a game given as it was to an earlier capture, None when it cannot be found any more."""
    try:
        return os.path.dirname(game_dir(game, LOOK))
    except (ValueError, OSError):
        return None


def _same_folder(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


@dataclasses.dataclass
class WorkInfo:
    """What the window knows of the work folder: ``ok`` unless it cannot be used (``message`` says why, or tells that
    a capture will go on there), ``notes`` that do not stop it, ``other_files`` when the folder holds files that are
    not renpy-capture's own (the person is asked)."""
    ok: bool
    message: str = ''
    path: str = ''
    notes: tuple = ()
    other_files: bool = False
    resume: bool = False


def check_work(text, game=None, language=None, text_box=False):
    """Can the work go in this folder, for the game ``game`` (a GameInfo)? Not inside the game's own folder, not over
    the capture of another game."""
    path = clean_path(text)
    if not path:
        return WorkInfo(False, S.WORK_EMPTY)
    if os.path.exists(path) and not os.path.isdir(path):
        return WorkInfo(False, S.WORK_IS_FILE, path)
    root = game.root if game is not None and game.ok else None
    if root and (_inside(path, root) or _inside(root, path)):
        return WorkInfo(False, S.WORK_INSIDE_GAME, path)
    notes, other, resume = [], False, False
    if os.path.isdir(path):
        info = os.path.join(path, 'run', RUN_INFO)
        earlier = None
        try:
            earlier = read_json(info).get('game') if os.path.isfile(info) else None
        except (OSError, ValueError, AttributeError):
            pass
        if isinstance(earlier, str) and root:
            there = _root_of(earlier)
            if there and not _same_folder(there, root):
                return WorkInfo(False, S.WORK_OTHER_GAME.format(game=earlier), path)
        ours = os.path.isfile(os.path.join(path, 'config.json')) or earlier is not None
        try:
            other = not ours and any(not OWN.match(n) for n in os.listdir(path))
        except OSError:
            pass
        done = os.path.join(work_paths(path, language, text_box)['out'], 'done.txt')
        resume = os.path.isfile(done)
    if root and WINDOWS and _drive(path) != _drive(root):
        notes.append(S.WORK_OTHER_DRIVE)
    if synced(path):
        notes.append(S.WORK_SYNCED)
    return WorkInfo(True, S.WORK_RESUME if resume else '', path, tuple(notes), other, resume)


def default_workdir(game):
    """A folder named after the game, under renpy-capture in Documents; with a number after it when a folder of that
    name already holds the capture of another game."""
    base = os.path.join(documents_folder(), 'renpy-capture')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', game.name).strip(' .') or 'game'
    candidate = os.path.join(base, name)
    for n in range(2, 100):
        if check_work(candidate, game).ok:
            break
        candidate = os.path.join(base, f'{name} ({n})')
    return candidate


# ---- the run

def capture_arguments(game, workdir, language=None, text=False, version=None):
    """The arguments of `renpy-capture` for what the person chose. The version goes only when the game does not tell
    its own: `capture` reads it from the game, and from the earlier run in the same work folder."""
    args = ['capture', game.path, workdir, '--progress-json']
    if language:
        args += ['--language', language]
    if text:
        args.append('--text')
    if version and not game.version:
        args += ['--renpy-version', version]
    return args


def clock_text(seconds):
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    return f'{h}:{rest // 60:02d}:{rest % 60:02d}' if h else f'{rest // 60}:{rest % 60:02d}'


class Run:
    """One `renpy-capture capture` as a program of its own. Its events (the JSON lines of its standard output) and its
    text (the standard error, which goes to the log file as well) come to ``poll``; it runs in ``cwd`` (the work folder:
    the paths it says are then relative to it). ``cancel`` stops it and everything
    it started: on Windows by the Job Object of the window (the engines are in the capture's own, which is inside it),
    elsewhere by SIGTERM, which the capture turns into a clean stop, and after a while by SIGKILL."""

    GRACE = 20                                              # seconds a capture has to stop on SIGTERM

    def __init__(self, argv, log, env=None, cwd=None):
        self.argv, self.log, self.env, self.cwd = argv, log, env, cwd
        self.proc = self.job = None
        self.cancelled = False
        self.tail = collections.deque(maxlen=30)            # the last lines it said: what a failure is explained by
        self._items, self._eof, self._ended = queue.Queue(), 0, None
        self._lock = threading.Lock()
        self._file = None
        self._threads = []

    def start(self):
        self._file = open(self.log, 'a', encoding='utf-8', errors='replace')
        self.write_log(f'=== {time.strftime("%Y-%m-%d %H:%M:%S")}  {subprocess.list2cmdline(self.argv)}')
        env = dict(os.environ if self.env is None else self.env)
        env['PYTHONUNBUFFERED'] = '1'
        extra = ({'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS
                 else {'start_new_session': True})
        try:
            self.proc = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                                         bufsize=1, env=env, cwd=self.cwd, **extra)
        except OSError:
            self._file.close()
            raise
        if WINDOWS:
            try:
                from .. import winproc
                self.job = winproc.Job()
                self.job.add(int(self.proc._handle))
            except (ImportError, OSError):                  # then Cancel ends the capture itself, whose Job Object
                if self.job:                                # ends the engines
                    self.job.close()
                self.job = None
        for stream, kind in ((self.proc.stdout, 'event'), (self.proc.stderr, 'text')):
            t = threading.Thread(target=self._read, args=(stream, kind), daemon=True)
            t.start()
            self._threads.append(t)

    def write_log(self, line):
        with self._lock:
            if self._file and not self._file.closed:
                self._file.write(line + '\n')
                self._file.flush()

    def _read(self, stream, kind):
        try:
            for line in stream:
                line = line.rstrip('\r\n')
                if kind == 'event':
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            self._items.put(('event', event))
                            continue
                    except ValueError:
                        pass
                self.write_log(line)                        # text, or what claimed to be an event and is not one
                self.tail.append(line)
                self._items.put(('text', line))
        except (OSError, ValueError):                       # the pipe closed under us
            pass
        finally:
            self._items.put(('eof', None))

    def poll(self):
        """What came since the last look, in order: ('event', {…}) and ('text', 'a line')."""
        got = []
        while True:
            try:
                kind, payload = self._items.get_nowait()
            except queue.Empty:
                return got
            if kind == 'eof':
                self._eof += 1
            else:
                got.append((kind, payload))

    @property
    def finished(self):
        """The capture has ended and everything it said has been read (a pipe that a grandchild holds open is not
        waited for longer than a moment)."""
        if self.proc is None or self.proc.poll() is None:
            return False
        if self._ended is None:
            self._ended = time.monotonic()
        return self._eof >= 2 or time.monotonic() - self._ended > 3

    @property
    def returncode(self):
        return self.proc.returncode if self.proc is not None else None

    def cancel(self):
        self.cancelled = True
        if self.proc is None or self.proc.poll() is not None:
            return
        if self.job is not None:
            self.job.kill()                                 # the capture, the engines, whatever they started
            return
        self.proc.terminate()
        if not WINDOWS:
            threading.Thread(target=self._escalate, daemon=True).start()

    def _escalate(self):
        try:
            self.proc.wait(self.GRACE)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.proc.pid, 9)
            except OSError:
                pass

    def wait(self, seconds):
        """True when the capture has ended within ``seconds``."""
        try:
            self.proc.wait(seconds)
            return True
        except subprocess.TimeoutExpired:
            return False

    def close(self):
        for t in self._threads:
            t.join(2)
        if self.job is not None:
            self.job.close()
            self.job = None
        with self._lock:
            if self._file:
                self._file.close()


class Tracker:
    """What the events of a run add up to: the sentence for what is going on now, how far it is, and at the end the
    summary the capture sent."""

    def __init__(self):
        self.stage = self.fetch = self.numbers = self.done = self.error = None

    def feed(self, e):
        kind = e.get('event')
        if kind == 'stage':
            self.stage, self.fetch = e.get('stage'), None
        elif kind == 'fetch':
            self.fetch = None if e.get('step') == 'done' else e
        elif kind == 'progress':
            self.numbers, self.fetch = e, None
        elif kind == 'done':
            self.done = e
        elif kind == 'error':
            self.error = e.get('message')

    def headline(self):
        f = self.fetch
        if f:
            if f.get('what') == 'unrpyc':
                return S.FETCH_UNRPYC
            step = f.get('step')
            if step == 'download':
                return S.FETCH_DOWNLOAD.format(version=f.get('version'))
            return S.FETCH_VERIFY if step == 'verify' else S.FETCH_UNPACK.format(version=f.get('version'))
        if self.stage == 'check':
            return S.STAGE_CHECK
        if self.stage == 'export':
            return S.STAGE_EXPORT
        if self.stage == 'capture':
            return S.CAPTURING if self.numbers else S.STAGE_ENGINE
        return S.STAGE_SETUP if self.stage == 'setup' else S.STARTING

    def detail(self):
        f = self.fetch
        if f:
            if f.get('step') == 'download' and f.get('what') != 'unrpyc':
                done, total = f.get('done') or 0, f.get('total')
                return (S.FETCH_BYTES.format(done=S.size(done), total=S.size(total)) if total
                        else S.FETCH_BYTES_UNKNOWN.format(done=S.size(done)))
            if f.get('step') == 'unpack' and f.get('total'):
                return S.FETCH_FILES.format(done=f.get('done') or 0, total=f['total'])
            return ''
        n = self.numbers
        if not n or self.stage != 'capture':
            return ''
        done, total = n.get('jobs_done') or 0, n.get('jobs_total') or 0
        parts = [S.PROGRESS_BRANCHES.format(done=done, total=total), S.count(S.LINES, n.get('lines') or 0)]
        if (n.get('engines') or 0) > 1:
            parts.append(S.PROGRESS_ENGINES.format(n=n['engines']))
        elif n.get('now'):
            parts.append(S.PROGRESS_NOW.format(job=n['now']))
        else:
            parts.append(S.PROGRESS_FINISHING if done >= total else S.PROGRESS_STARTING)
        return S.DETAIL_SEPARATOR.join(parts)

    def fraction(self):
        """How far along, 0 to 1; None while it cannot be told (the bar then just moves)."""
        f, n = self.fetch, self.numbers
        if f:
            total = f.get('total')
            return min((f.get('done') or 0) / total, 1.0) if total and f.get('step') in ('download', 'unpack') \
                else None
        if self.stage == 'capture' and n and n.get('jobs_total'):
            return min((n.get('jobs_done') or 0) / n['jobs_total'], 1.0)
        return None


@dataclasses.dataclass
class Summary:
    """How a run ended. ``kind`` is 'done', 'stopped' (by the person) or 'failed'; ``lines`` are the sentences under the
    headline; ``index`` is the page to open, if there is one."""
    kind: str
    headline: str
    lines: tuple = ()
    index: object = None


def summarize(tracker, returncode, cancelled, tail=()):
    """The end of a run in words: what was captured, what to look at (warnings, plainly), or why it stopped."""
    n = tracker.numbers
    if cancelled:
        lines = [S.STOPPED_AT.format(done=n.get('jobs_done') or 0, total=n.get('jobs_total') or 0,
                                     lines=S.count(S.LINES, n.get('lines') or 0))] if n else []
        return Summary('stopped', S.STOPPED, tuple(lines + [S.STOPPED_GO_ON]))
    d = tracker.done
    if returncode == 0 and d:
        return _done(d)
    reason = tracker.error or next((line for line in reversed(list(tail)) if line.strip()), None)
    return Summary('failed', S.FAILED, (reason or S.FAILED_NO_REASON.format(code=returncode), S.FAILED_LOG,
                                        S.FAILED_GO_ON))


def _done(d):
    lines = [S.DONE_COMPLETE if d.get('complete') else S.DONE_PARTIAL]
    if not d.get('lines'):
        lines = [S.NOTHING_CAPTURED]
    if d.get('errors'):
        lines.append(S.count(S.WARN_ERRORS, len(d['errors'])))
    if d.get('unchecked'):
        lines.append(S.WARN_UNCHECKED.format(why=d['unchecked']))
    elif d.get('missed'):
        lines.append(S.count(S.WARN_MISSED, d['missed']))
    elif d.get('lines'):
        lines.append(S.NOTHING_MISSED)
    for w in d.get('warnings') or ():
        if w.get('kind') == 'moving':
            lines.append(S.WARN_MOVING)
        elif w.get('kind') == 'late':
            lines.append(S.count(S.WARN_LATE, w.get('menus', 0)))
        elif w.get('kind') == 'slow':
            lines.append(S.WARN_SLOW.format(seconds=w.get('seconds')))
    if d.get('language') and not d.get('beside'):
        lines.append(S.HINT_ORIGINAL)
    headline = S.DONE.format(lines=S.count(S.LINES, d.get('lines', 0)), branches=S.count(S.BRANCHES, d.get('jobs', 0)),
                             pictures=S.count(S.PICTURES, d.get('pictures', 0)))
    index = d.get('index')
    return Summary('done', headline, tuple(lines), index if index and os.path.isfile(index) else None)


# ---- the window's brain

class Problem(Exception):
    """Capture cannot start: the message is the sentence to show."""


class Controller:
    """Everything the window decides. The person's choices come in through the ``set_`` methods, ``pump`` takes what a
    running capture has said, and the attributes tell what to show: the form (``info``, ``work``, ``language``…) and
    the run (``phase``: idle, running or finished; ``headline``, ``detail``, ``fraction``, ``summary``)."""

    def __init__(self, settings=None, spawn=Run, opener=open_path, clock=time.monotonic, command=None):
        self.settings = settings if settings is not None else Settings()
        self.spawn, self.opener, self.clock = spawn, opener, clock
        self.command = command if command is not None else child_command()
        self.game_text = self.workdir_text = ''
        self.workdir_edited = False
        self.last_root = None                               # the last folder that was a game
        self.language = self.version = None
        self.text = False
        self.info, self.work = check_game(''), WorkInfo(False, S.WORK_EMPTY)
        self.phase, self.run, self.tracker, self.summary = 'idle', None, Tracker(), None
        self.stopping = False                               # Cancel was pressed, the capture has not ended yet
        self.started = self.ended = self.log = None
        self.new_text = []
        last, choices = self.settings.last()
        if last:
            self.text = choices.get('text', False)
            self.set_game(last, remembered=choices)

    # -- the form

    def set_game(self, text, remembered=None):
        """The folder of the game was chosen or typed. What was chosen for this game before comes back; the work folder
        is the default one (named after the game) unless an earlier run or the person chose another."""
        self.game_text = text
        self.info = check_game(text)
        if self.info.ok:
            saved = remembered if remembered is not None else self.settings.game(self.info.root)
            if self.last_root is None or not _same_folder(self.info.root, self.last_root) or remembered is not None:
                self.language = saved.get('language') if saved.get('language') in self.info.languages else None
                self.text = saved.get('text', self.text)
                self.workdir_edited = 'workdir' in saved
                self.workdir_text = saved.get('workdir') or default_workdir(self.info)
                self.version = default_version(self.info.major, saved.get('version'))
            elif self.language not in (None, *self.info.languages):
                self.language = None
            self.last_root = self.info.root                 # (a mistyped path in between is not another game)
        self._look_at_work()

    def set_workdir(self, text):
        self.workdir_text, self.workdir_edited = text, True
        self._look_at_work()

    def set_language(self, name):
        self.language = name if name in self.info.languages else None
        self._look_at_work()

    def set_text(self, on):
        self.text = bool(on)
        self._look_at_work()

    def set_version(self, version):
        self.version = version

    def _look_at_work(self):
        self.work = check_work(self.workdir_text, self.info, self.language, self.text)

    def language_labels(self):
        return [S.LANGUAGE_ORIGINAL, *self.info.languages]

    def language_index(self):
        return 1 + self.info.languages.index(self.language) if self.language in self.info.languages else 0

    def version_choices(self):
        return list(sdk.VERSIONS)

    def needs_version(self):
        return self.info.ok and not self.info.version

    def problem(self):
        """Why Capture cannot start now, as a sentence; None when it can."""
        if not self.info.ok:
            return self.info.message
        if not self.work.ok:
            return self.work.message
        return None

    def can_start(self):
        return self.phase != 'running' and self.problem() is None

    def question(self):
        """Something to ask before starting, as a sentence (a work folder with other files in it); None when nothing."""
        return S.WORK_OTHER_FILES if self.work.other_files else None

    # -- the run

    def start(self):
        """Begin the capture. Raises Problem (with the sentence to show) when it cannot."""
        problem = self.problem()
        if problem:
            raise Problem(problem)
        workdir = self.work.path
        try:
            os.makedirs(workdir, exist_ok=True)
        except OSError as e:
            raise Problem(S.WORK_CANNOT.format(error=e)) from e
        argv = self.command + capture_arguments(self.info, workdir, self.language, self.text,
                                                self.version if self.needs_version() else None)
        self.log = os.path.join(workdir, LOG)
        run = self.spawn(argv, self.log, cwd=workdir)   # there: the paths the capture says are short ones
        try:
            run.start()
        except OSError as e:
            raise Problem(S.CANNOT_START.format(error=e)) from e
        self.run, self.tracker, self.summary, self.stopping = run, Tracker(), None, False
        self.phase, self.started, self.ended, self.new_text = 'running', self.clock(), None, []
        self.settings.remember(self.info.path, self.info.root, self.work.path, self.language, self.text, self.version)

    def cancel(self):
        if self.run is not None:
            self.stopping = True
            self.run.cancel()

    def pump(self):
        """Take what a running capture has said; True when anything changed (the window shows it again)."""
        if self.run is None:
            return False
        changed = False
        for kind, payload in self.run.poll():
            changed = True
            if kind == 'event':
                self.tracker.feed(payload)
            else:
                self.new_text.append(payload)
        if self.run.finished:
            self._end()
            changed = True
        return changed

    def _end(self):
        run, self.run = self.run, None
        code = run.returncode
        self.summary = summarize(self.tracker, code, run.cancelled, run.tail)
        run.write_log(f'=== ended with exit code {code}' + (' (cancelled)' if run.cancelled else ''))
        run.close()
        self.phase, self.ended = 'finished', self.clock()

    def take_text(self):
        """The lines the capture said since the last call."""
        lines, self.new_text = self.new_text, []
        return lines

    def elapsed(self):
        if self.started is None:
            return 0
        return (self.ended if self.ended is not None else self.clock()) - self.started

    def headline(self):
        if self.summary:
            return self.summary.headline
        return S.STOPPING if self.stopping else self.tracker.headline()

    def detail(self):
        return '' if self.summary else self.tracker.detail()

    def fraction(self):
        return None if self.summary else self.tracker.fraction()

    def close(self):
        """The window is closing: a capture still running is stopped, with everything it started."""
        if self.run is not None:
            self.run.cancel()
            self.run.wait(10)
            self.run.close()
            self.run = None

    # -- after it

    def _open(self, path):
        return bool(path) and self.opener(path)

    def open_page(self):
        return self._open(self.summary.index if self.summary else None)

    def open_folder(self):
        return self._open(self.work.path)

    def open_log(self):
        return self._open(self.log if self.log and os.path.isfile(self.log) else None)
