"""The window itself, on a real display: it opens, shows what the controller says, answers the keyboard everywhere, and
a whole capture can be run through it and cancelled. Skipped where there is no Tk or no display (the Linux jobs of CI run
it under Xvfb).

The end-to-end class is opt-in like the other ones (RENPY_CAPTURE_IT=1; it downloads the SDK once): it runs The Question
through the window, with the real capture as its child process. RENPY_CAPTURE_GUI_SHOT=file.png saves a picture of the
window when the run is over (RENPY_CAPTURE_GUI_SHOT_BASE=folder puts the game and the work folders it shows into that
folder, to have short paths in it); RENPY_CAPTURE_IT_REFERENCE (a capture made on Linux) is compared with it like the
other end-to-end tests do."""
import contextlib
import gc
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

try:
    import tkinter as tk
except ImportError:                                         # a Python without Tk
    tk = None

from renpy_capture import analysis, sdk
from renpy_capture.gui import controller, strings as S
from renpy_capture.gui.controller import Controller, Settings
from renpy_capture.util import read_jsonl

from .test_gui import FakeRun, event, make_game

VERSION = os.environ.get('RENPY_CAPTURE_IT_VERSION', '8.3.2')
REFERENCE = os.environ.get('RENPY_CAPTURE_IT_REFERENCE')
SHOT = os.environ.get('RENPY_CAPTURE_GUI_SHOT')
BASE = os.environ.get('RENPY_CAPTURE_GUI_SHOT_BASE')                # where the game and the work folders are for the picture


def display_here():
    if tk is None:
        return False
    try:
        tk.Tk().destroy()
    except tk.TclError:
        return False
    return True


NEEDS_A_WINDOW = unittest.skipUnless(display_here(), 'no Tk, or no display to open a window on')


def said(words):
    return words.get('1.0', 'end-1c')


def settle(root, seconds=0.0):
    """Let the window do what is queued (draw, lay out, run its timers) for ``seconds`` at least."""
    end = time.monotonic() + seconds
    root.update()
    while time.monotonic() < end:
        time.sleep(0.01)
        root.update()


class Boxes:
    """The message boxes of the window, answered by the test instead of by a person."""

    def __init__(self, answer=True):
        self.answer, self.asked, self.shown = answer, [], []

    def askyesno(self, title, message, **kw):
        self.asked.append((title, message))
        return self.answer

    def showerror(self, title, message, **kw):
        self.shown.append(('error', message))

    def showwarning(self, title, message, **kw):
        self.shown.append(('warning', message))


@NEEDS_A_WINDOW
class WindowTest(unittest.TestCase):
    def setUp(self):
        from renpy_capture.gui import app
        self.app_module = app
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = os.path.realpath(self._tmp.name)
        self.docs = os.path.join(self.tmp, 'docs')
        for patch in (mock.patch.object(controller, 'documents_folder', lambda: self.docs),
                      mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': self.tmp, 'APPDATA': self.tmp})):
            patch.start()
            self.addCleanup(patch.stop)
        self.boxes = Boxes()
        for name in ('askyesno', 'showerror', 'showwarning'):
            patch = mock.patch.object(app.messagebox, name, getattr(self.boxes, name))
            patch.start()
            self.addCleanup(patch.stop)
        FakeRun.made, self.opened = [], []
        self.game = make_game(self.tmp, 'The Question', version='8.3.2.1', tl=('russian',), around=('games',))
        self.open()

    def open(self):
        """A window, as the last one left the settings."""
        self.root = tk.Tk()
        self.addCleanup(self.destroy)
        self.ctl = Controller(Settings(os.path.join(self.tmp, 'gui.json')), spawn=FakeRun,
                              opener=lambda p: self.opened.append(p) or True, command=['renpy-capture'])
        self.app = self.app_module.App(self.root, self.ctl)
        settle(self.root)

    def destroy(self):
        if self.root is None:                                   # (once for each window the test opened)
            return
        with contextlib.suppress(tk.TclError):
            self.app.bar.stop()                                 # (the bar's own timer would run into nothing)
            self.root.destroy()
        self.app = self.ctl = self.root = None
        gc.collect()                                            # here, in the main thread: Tk objects must not be
                                                                # freed by a thread that the next test starts

    def choose(self, game=None):
        self.app.game_var.set(game or self.game)
        self.app.apply_game()
        settle(self.root)

    def test_it_opens_and_says_what_to_do(self):
        a = self.app
        self.assertEqual(self.root.title(), S.TITLE)
        self.assertEqual((a.icon.width(), a.icon.height()), (64, 64))             # its own icon, not Tk's feather
        self.assertEqual(said(a.game_words), S.GAME_EMPTY)
        self.assertIn('disabled', a.capture.state())
        self.assertEqual(said(a.status), '')                                   # nothing has run yet
        self.assertEqual(a.cancel.winfo_manager(), '')
        self.assertEqual(a.open_page.winfo_manager(), '')
        self.assertEqual(a.version_row.winfo_manager(), '')                    # no game, no version to ask for

    def test_a_game_is_recognised_and_its_translations_are_listed(self):
        self.choose()
        a = self.app
        self.assertIn('The Question', said(a.game_words))
        self.assertIn('8.3.2', said(a.game_words))
        self.assertEqual(list(a.language_box.cget('values')), [S.LANGUAGE_ORIGINAL, 'russian'])
        self.assertEqual(a.language_var.get(), S.LANGUAGE_ORIGINAL)
        self.assertNotIn('disabled', a.capture.state())
        self.assertEqual(a.work_var.get(), os.path.join(self.docs, 'renpy-capture', 'The Question'))
        self.assertEqual(a.version_row.winfo_manager(), '')

    def test_a_game_that_is_not_one_says_so_and_the_button_stays_off(self):
        empty = os.path.join(self.tmp, 'nothing')
        os.makedirs(empty)
        self.choose(empty)
        self.assertEqual(said(self.app.game_words), S.GAME_NONE)
        self.assertIn('disabled', self.app.capture.state())

    def test_a_game_that_does_not_tell_its_version_asks_for_it(self):
        self.choose(make_game(self.tmp, 'Old', cache=True, around=('old',)))
        a = self.app
        self.assertEqual(a.version_row.winfo_manager(), 'grid')
        self.assertEqual((a.version_var.get(), list(a.version_box.cget('values'))), ('7.8.7', self.ctl.version_choices()))
        a.version_var.set('8.2.3')
        a.version_box.event_generate('<<ComboboxSelected>>')
        a.capture.invoke()
        self.assertEqual(FakeRun.made[-1].argv[-2:], ['--renpy-version', '8.2.3'])

    def test_the_choices_reach_the_command(self):
        self.choose()
        a = self.app
        a.language_box.current(1)
        a.language_box.event_generate('<<ComboboxSelected>>')
        a.text_check.invoke()
        a.capture.invoke()
        argv = FakeRun.made[-1].argv
        self.assertEqual(argv[:3], ['renpy-capture', 'capture', self.game])
        self.assertEqual(argv[-3:], ['--language', 'russian', '--text'])

    def test_a_work_folder_inside_the_game_stops_the_button(self):
        self.choose()
        a = self.app
        a.work_var.set(os.path.join(self.game, 'work'))
        a.apply_work()
        self.assertEqual(said(a.work_words), S.WORK_INSIDE_GAME)
        self.assertIn('disabled', a.capture.state())

    def test_a_folder_with_other_files_is_asked_about_first(self):
        self.choose()
        work = os.path.join(self.tmp, 'full')
        os.makedirs(work)
        open(os.path.join(work, 'holiday.jpg'), 'w').close()
        self.app.work_var.set(work)
        self.boxes.answer = False
        self.app.capture.invoke()
        self.assertEqual(self.boxes.asked[-1], (S.WORK_OTHER_FILES_TITLE, S.WORK_OTHER_FILES))
        self.assertEqual(FakeRun.made, [])
        self.boxes.answer = True
        self.app.capture.invoke()
        self.assertEqual(len(FakeRun.made), 1)

    def run_something(self):
        self.choose()
        self.app.capture.invoke()
        settle(self.root)
        return FakeRun.made[-1]

    def test_a_run_is_shown_while_it_goes_and_ends_with_the_buttons(self):
        run, a = self.run_something(), self.app
        self.assertEqual(self.ctl.phase, 'running')
        self.assertEqual((a.cancel.winfo_manager(), a.open_log.winfo_manager(), a.open_page.winfo_manager()),
                         ('grid', 'grid', ''))
        for widget in (a.game_entry, a.work_entry, a.game_browse, a.text_check, a.capture):
            self.assertIn('disabled', widget.state())                           # nothing to change during a run
        run.say(event('stage', stage='capture'), ('text', 'launch folder: work/run'),
                event('progress', jobs_done=1, jobs_total=4, lines=57, now='start~1', engines=1))
        a.tick()
        settle(self.root)
        self.assertEqual(said(a.status), S.CAPTURING)
        self.assertIn('Branches done: 1 of 4', said(a.detail))
        self.assertIn('now: start~1', said(a.detail))
        self.assertEqual(float(a.bar.cget('value')), 25.0)
        self.assertEqual(said(a.log.text), 'launch folder: work/run\n')
        self.assertRegex(a.elapsed.cget('text'), r'^Time: \d+:\d\d$')
        index = os.path.join(self.tmp, 'index.html')
        open(index, 'w').close()
        run.say(event('done', lines=128, jobs=3, pictures=14, complete=True, errors=[], missed=0, warnings=[],
                      language=None, beside=False, index=index), code=0)
        a.tick()
        settle(self.root)
        self.assertEqual(said(a.status), 'Done: 128 lines in 3 branches, 14 pictures.')
        self.assertIn(S.DONE_COMPLETE, said(a.notes))
        self.assertEqual((a.open_page.winfo_manager(), a.open_folder.winfo_manager(), a.open_log.winfo_manager(),
                          a.cancel.winfo_manager()), ('grid', 'grid', 'grid', ''))
        self.assertEqual(float(a.bar.cget('value')), 100.0)
        for widget in (a.game_entry, a.work_entry, a.capture):
            self.assertNotIn('disabled', widget.state())
        a.open_page.invoke()
        a.open_folder.invoke()
        self.assertEqual(self.opened, [index, self.ctl.work.path])

    def test_a_failure_is_in_red_and_says_why(self):
        run = self.run_something()
        run.say(event('error', message='cannot download the Ren\'Py 8.3.2 SDK'), code=1)
        self.app.tick()
        settle(self.root)
        self.assertEqual(said(self.app.status), S.FAILED)
        self.assertIn("cannot download the Ren'Py 8.3.2 SDK", said(self.app.notes))
        self.assertEqual(self.app.status.tag_ranges('bad')[0].string, '1.0')
        self.assertEqual(self.app.open_page.winfo_manager(), '')                # there is no page to open

    def test_cancel_asks_first_and_then_stops_everything(self):
        run = self.run_something()
        self.boxes.answer = False
        self.app.cancel.invoke()
        self.assertEqual((run.cancelled, self.boxes.asked[-1]), (False, (S.CANCEL_TITLE, S.CANCEL_ASK)))
        self.boxes.answer = True
        self.app.cancel.invoke()
        settle(self.root)
        self.assertTrue(run.cancelled)
        self.assertEqual(said(self.app.status), S.STOPPING)
        self.assertIn('disabled', self.app.cancel.state())
        self.app.tick()
        settle(self.root)
        self.assertEqual(said(self.app.status), S.STOPPED)
        self.assertIn(S.STOPPED_GO_ON, said(self.app.notes))

    def test_escape_cancels_a_run_and_does_nothing_otherwise(self):
        self.root.focus_force()                                 # a key goes to the window that has the keyboard
        settle(self.root)
        self.root.event_generate('<Escape>')
        self.assertEqual(self.boxes.asked, [])
        self.run_something()
        self.root.focus_force()
        settle(self.root)
        self.root.event_generate('<Escape>')
        self.assertEqual(self.boxes.asked[-1], (S.CANCEL_TITLE, S.CANCEL_ASK))

    def test_closing_the_window_in_the_middle_of_a_run_stops_it(self):
        run = self.run_something()
        self.boxes.answer = False
        self.app.on_close()
        self.assertFalse(run.cancelled)
        self.assertTrue(self.root.winfo_exists())
        self.boxes.answer = True
        self.app.on_close()
        self.assertTrue(run.cancelled and run.closed)
        with self.assertRaises(tk.TclError):                                    # the window is gone
            self.root.title()

    def test_enter_on_the_big_button_starts_and_elsewhere_does_not(self):
        self.choose()
        a = self.app
        self.root.focus_force()
        a.game_browse.focus_force()
        settle(self.root)
        with mock.patch.object(a.game_browse, 'invoke') as invoked:
            a.on_return(None)
        invoked.assert_called_once_with()
        self.assertEqual(FakeRun.made, [])
        a.language_box.focus_force()
        settle(self.root)
        a.on_return(None)
        self.assertEqual(FakeRun.made, [])                                      # Enter in a list is not "go"
        a.capture.focus_force()
        settle(self.root)
        a.on_return(None)
        self.assertEqual(len(FakeRun.made), 1)

    def test_tab_goes_through_everything_in_the_order_of_the_page(self):
        self.choose(make_game(self.tmp, 'Old', cache=True, around=('old',)))        # a version box too
        a, order = self.app, []
        w = a.game_entry
        for _ in range(30):
            order.append(w)
            w = w.tk_focusNext()
            if w is a.game_entry:
                break
        self.assertEqual(order, [a.game_entry, a.game_browse, a.work_entry, a.work_browse, a.language_box,
                                 a.text_check, a.version_box, a.capture, a.log.text])   # (no buttons before a run)
        self.assertIs(a.log.text.tk_focusPrev(), a.capture)
        self.assertIs(a.game_entry.tk_focusPrev(), a.log.text)

    def test_the_text_can_be_selected_and_copied(self):
        self.choose()
        a = self.app
        for words in (a.game_words, a.work_words, a.text_words, a.log.text):
            if words is a.log.text:
                a.log.add(['a line of what renpy-capture says', 'and another'])
            settle(self.root)
            words.focus_force()
            words.event_generate('<Control-a>')
            self.assertTrue(words.tag_ranges('sel'), words)
            self.root.clipboard_clear()
            words.event_generate('<<Copy>>')
            self.assertEqual(self.root.clipboard_get().strip(), said(words).strip(), words)
        words = a.game_words                                                    # and nobody can change it
        words.insert('1.0', 'typed')
        words.event_generate('<Key-x>')
        self.assertNotIn('typed', said(words))

    def test_the_log_keeps_the_last_lines_and_follows_the_end(self):
        log = self.app.log
        log.add([f'line {n}' for n in range(self.app_module.LOG_LINES + 50)])
        settle(self.root)
        lines = said(log.text).splitlines()
        self.assertEqual((len(lines), lines[0], lines[-1]),
                         (self.app_module.LOG_LINES, 'line 50', f'line {self.app_module.LOG_LINES + 49}'))
        self.assertGreater(log.text.yview()[1], 0.99)
        log.text.yview_moveto(0)
        log.add(['one more'])
        self.assertLess(log.text.yview()[1], 0.5)                               # reading further up: left alone

    def test_the_log_pane_is_a_whole_number_of_lines_tall(self):
        """At its end a log must not show its first line cut in half, whatever the size of the window."""
        log = self.app.log
        log.add([f'line {n}' for n in range(80)])
        for height in (600, 637, 661, 700, 733):
            self.root.geometry(f'{self.root.winfo_width()}x{height}')
            settle(self.root, 0.2)
            t, line = log.text, log.font.metrics('linespace')
            t.yview_moveto(1.0)
            settle(self.root, 0.1)
            area = t.winfo_height() - 2 * (int(t.cget('borderwidth')) + int(t.cget('highlightthickness'))) \
                - 2 * int(t.cget('pady'))
            self.assertIn(area % line, (0, line - 1), (height, t.winfo_height(), area, line))   # (a pixel of margin)
            self.assertGreater(t.yview()[1], 0.99)                              # at its end

    def test_the_window_can_be_made_smaller_and_larger(self):
        self.choose(make_game(self.tmp, 'Old', cache=True, around=('old',)))
        a = self.app
        heights = {}
        for width in (1000, 600):
            self.root.geometry(f'{width}x720')
            settle(self.root, 0.3)
            actual = self.root.winfo_width()
            heights[width] = int(a.version_words.cget('height'))
            self.assertLessEqual(a.capture.winfo_rooty() + a.capture.winfo_height(), self.root.winfo_rooty() + 720)
            self.assertLessEqual(a.game_browse.winfo_rootx() + a.game_browse.winfo_width(),
                                 self.root.winfo_rootx() + actual)               # nothing is pushed out at the side
            self.assertGreater(a.log.winfo_height(), 20)                          # the log is what gives room
        self.assertGreaterEqual(heights[600], heights[1000])                      # a narrow window wraps its help more

    def test_a_script_can_have_the_window_capture_and_close_with_an_exit_code(self):
        """RENPY_CAPTURE_GUI_AUTORUN: how the build is tried where nobody can press Capture."""
        self.choose()
        a = self.app
        a.autorun(delay=10)
        settle(self.root, 0.3)
        run = FakeRun.made[-1]
        self.assertEqual(self.ctl.phase, 'running')
        run.say(event('done', lines=1, jobs=1, pictures=1, complete=True, errors=[], missed=0, warnings=[]), code=0)
        for _ in range(20):
            with contextlib.suppress(tk.TclError):
                a.tick()
                settle(self.root, 0.1)
        self.assertEqual(a.exit_code, 0)
        self.assertTrue(run.closed)
        with self.assertRaises(tk.TclError):                                    # it closed by itself
            self.root.title()

    def test_a_script_that_cannot_capture_leaves_with_another_code(self):
        a = self.app                                                            # no game chosen
        a.autorun(delay=10)
        settle(self.root, 0.6)
        self.assertEqual((a.exit_code, FakeRun.made), (2, []))

    def test_a_capture_that_fails_leaves_with_a_failing_code(self):
        self.choose()
        a = self.app
        a.autorun(delay=10)
        settle(self.root, 0.3)
        FakeRun.made[-1].say(event('error', message='no'), code=1)
        for _ in range(20):
            with contextlib.suppress(tk.TclError):
                a.tick()
                settle(self.root, 0.1)
        self.assertEqual(a.exit_code, 1)

    def test_a_mistake_inside_the_window_is_written_down_and_told_once(self):
        try:
            raise ValueError('boom')
        except ValueError as e:
            args = (ValueError, e, e.__traceback__)
        with contextlib.redirect_stderr(io.StringIO()) as err:                  # (it prints the traceback too)
            self.app.on_bug(*args)
            self.app.on_bug(*args)
        self.assertIn('ValueError: boom', err.getvalue())
        self.assertEqual(len(self.boxes.shown), 1)
        self.assertIn('ValueError: boom', self.boxes.shown[0][1])
        path = os.path.join(controller.config_dir(), 'window-errors.log')
        with open(path, encoding='utf-8') as f:
            self.assertEqual(f.read().count('ValueError: boom'), 2)
        self.assertIn(path, self.boxes.shown[0][1])

    def test_the_choices_and_the_size_of_the_window_come_back(self):
        self.choose()
        a = self.app
        a.language_box.current(1)
        a.language_box.event_generate('<<ComboboxSelected>>')
        a.text_check.invoke()
        a.work_var.set(os.path.join(self.tmp, 'my work'))
        a.capture.invoke()
        FakeRun.made[-1].say(code=0)
        self.root.geometry('810x640')
        settle(self.root, 0.2)
        self.boxes.answer = True
        a.on_close()
        self.open()
        b = self.app
        self.assertEqual((b.game_var.get(), b.work_var.get(), b.text_var.get()),
                         (self.game, os.path.join(self.tmp, 'my work'), True))
        self.assertEqual(b.language_var.get(), 'russian')
        self.assertNotIn('disabled', b.capture.state())
        self.assertEqual(self.ctl.settings.window(), (810, 640))

    def test_the_entries_take_what_was_typed_when_the_person_leaves_them(self):
        a = self.app
        a.game_entry.focus_force()
        a.game_entry.delete(0, 'end')
        a.game_entry.insert(0, f'  "{self.game}"  ')                               # pasted with quotes, as Windows copies
        a.work_entry.focus_force()                                               # leaving the box is enough
        settle(self.root, 0.2)
        self.assertTrue(self.ctl.info.ok)
        self.assertIn('The Question', said(a.game_words))


class Elsewhere(unittest.TestCase):
    def test_the_window_asks_for_tk_when_python_has_none(self):
        """On a Python without Tk the command says what to install instead of failing with a traceback."""
        import renpy_capture.gui as gui
        real_import = __import__

        def no_tk(name, *a, **kw):
            if name == 'tkinter' or name.startswith('tkinter.'):
                raise ImportError('no tkinter', name='tkinter')
            return real_import(name, *a, **kw)

        err = io.StringIO()
        loaded = gui.__dict__.pop('app', None)                                    # so that it is imported anew
        try:
            with mock.patch.dict(sys.modules), mock.patch('builtins.__import__', no_tk), \
                    contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                sys.modules.pop('renpy_capture.gui.app', None)
                gui.main()
        finally:
            if loaded is not None:
                gui.app = loaded
        self.assertEqual(cm.exception.code, 1)
        self.assertIn('python3-tk', err.getvalue())


def engines_of(folder):
    """The processes whose command line names ``folder`` ("pid command line"): the capture, its engine, and what they
    started. On Windows the question is asked by a program whose own command line names the folder: it leaves itself
    out ($PID), or it would always find one."""
    if os.name == 'nt':
        script = ("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like '*"
                  + folder.replace("'", "''") + "*' } | ForEach-Object { $_.ProcessId.ToString() + ' ' + "
                  "$_.CommandLine }")
        out = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, text=True).stdout
    else:
        out = subprocess.run(['pgrep', '-af', folder], capture_output=True, text=True).stdout
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return [line for line in lines if line.split()[0].isdigit() and int(line.split()[0]) != os.getpid()]


@unittest.skipUnless(os.environ.get('RENPY_CAPTURE_IT'), 'set RENPY_CAPTURE_IT=1 to run the end-to-end test')
@NEEDS_A_WINDOW
class WindowEndToEnd(unittest.TestCase):
    """The Question through the window, with the real capture as its child process."""

    @classmethod
    def setUpClass(cls):
        cls.sdk = sdk.ensure(VERSION)
        cls._tmp = tempfile.TemporaryDirectory(prefix='rc-gui-')
        cls.tmp = os.path.realpath(cls._tmp.name)
        cls.folders = [os.path.join(cls.tmp, 'Games'), os.path.join(cls.tmp, 'renpy-capture')]
        if BASE:                                                    # the picture shows these folders: short ones, of
            cls.folders = [os.path.join(BASE, 'Games'), os.path.join(BASE, 'renpy-capture')]      # nobody's machine
            if any(os.path.exists(f) for f in cls.folders):
                raise unittest.SkipTest(f'{BASE}: Games or renpy-capture is there already, and is not ours to remove')
        cls.game = os.path.join(cls.folders[0], 'The Question')
        shutil.copytree(os.path.join(cls.sdk, 'the_question'), cls.game, ignore=shutil.ignore_patterns('saves', 'cache'))
        os.makedirs(os.path.join(cls.game, 'renpy'))              # a game of Windows has its engine beside game/, and the
        shutil.copy(os.path.join(cls.sdk, 'renpy', 'vc_version.py'),                   # engine tells its version
                    os.path.join(cls.game, 'renpy', 'vc_version.py'))

    @classmethod
    def tearDownClass(cls):
        for folder in cls.folders + [cls.tmp]:
            shutil.rmtree(folder, ignore_errors=True)
        try:
            cls._tmp.cleanup()                              # (done already: this keeps the finalizer of the folder quiet)
        except OSError:
            pass

    def setUp(self):
        from renpy_capture.gui import app
        self.boxes = Boxes()
        for name in ('askyesno', 'showerror', 'showwarning'):
            patch = mock.patch.object(app.messagebox, name, getattr(self.boxes, name))
            patch.start()
            self.addCleanup(patch.stop)
        name = 'The Question' if 'whole' in self.id() else 'cancelled'            # (the picture shows this one)
        self.work = os.path.join(self.folders[1], name)
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.ctl = Controller(Settings(os.path.join(self.tmp, 'gui.json')),
                              opener=lambda p: True)               # the real child process, the real capture
        self.app = app.App(self.root, self.ctl)
        self.app.game_var.set(self.game)
        self.app.apply_game()
        self.app.work_var.set(self.work)
        self.app.apply_work()
        self.assertFalse(self.ctl.needs_version())                 # the engine beside the game tells its version
        self.assertIn(VERSION, self.ctl.info.message)
        self.addCleanup(self.ctl.close)

    def wait(self, until, seconds=900):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.tick()
            settle(self.root, 0.1)
            if until():
                return
        self.fail(f'not after {seconds} s: {self.ctl.headline()} | {self.ctl.detail()}')

    def test_a_whole_capture_through_the_window(self):
        self.app.capture.invoke()
        self.assertEqual(self.ctl.phase, 'running')
        seen = set()

        def over():
            seen.add(self.ctl.headline())
            return self.ctl.phase == 'finished'

        self.wait(over)
        s = self.ctl.summary
        self.assertEqual(s.kind, 'done', s)
        self.assertRegex(s.headline, r'^Done: 128 lines in 3 branches, \d+ pictures\.$')
        self.assertIn(S.DONE_COMPLETE, s.lines)
        self.assertIn(S.NOTHING_MISSED, s.lines)
        self.assertTrue(os.path.isfile(s.index), s.index)
        self.assertTrue(any(h == S.CAPTURING for h in seen), seen)              # it was shown going, not only done
        with open(self.ctl.log, encoding='utf-8') as f:
            log = f.read()
        self.assertRegex(log, r'Done: 128 lines in 3 jobs, \d+ pictures')
        self.assertIn('=== ended with exit code 0', log)
        self.assertEqual([self.ctl.open_page(), self.ctl.open_folder(), self.ctl.open_log()], [True] * 3)
        if REFERENCE:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                same = analysis.compare(REFERENCE, os.path.join(self.work, 'out'), frames=False)
            self.assertTrue(same, buf.getvalue())
        if SHOT:
            self.picture(SHOT)

    def picture(self, path):
        """The window as it is now, in a file (what the README shows): with its title bar and frame where the system
        draws them (Windows), else what is inside."""
        from PIL import ImageGrab
        settle(self.root, 0.5)
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.focus_force()                                     # (a window that has the focus has a title that shows it)
        settle(self.root, 0.5)
        x, y, w, h = self.root.winfo_rootx(), self.root.winfo_rooty(), self.root.winfo_width(), self.root.winfo_height()
        box = (x, y, x + w, y + h)
        if os.name == 'nt':
            try:
                import ctypes
                from ctypes import wintypes
                frame = wintypes.RECT()                         # DWMWA_EXTENDED_FRAME_BOUNDS: the frame as it is seen
                top = ctypes.windll.user32.GetParent(self.root.winfo_id())      # (Tk's own window, around the one it shows)
                if ctypes.windll.dwmapi.DwmGetWindowAttribute(top, 9, ctypes.byref(frame), ctypes.sizeof(frame)) == 0:
                    box = (frame.left, frame.top, frame.right, frame.bottom)
            except (OSError, AttributeError):
                pass
        try:
            picture = ImageGrab.grab(bbox=box)
        except (OSError, ValueError):                               # a frame the screen cannot give: what is inside
            picture = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        picture.convert('RGB').save(path, optimize=True)

    def test_cancel_stops_the_capture_and_what_it_started_and_capture_goes_on(self):
        self.app.capture.invoke()
        self.wait(lambda: (self.ctl.tracker.numbers or {}).get('lines', 0) >= 5)
        self.assertTrue(engines_of(self.work), 'no engine of this capture is running')
        self.app.cancel.invoke()
        self.assertEqual(said(self.app.status), S.STOPPING)
        self.wait(lambda: self.ctl.phase == 'finished', 120)
        self.assertEqual((self.ctl.summary.kind, self.ctl.summary.headline), ('stopped', S.STOPPED))
        deadline = time.monotonic() + 30
        while engines_of(self.work) and time.monotonic() < deadline:
            time.sleep(0.5)
        self.assertEqual(engines_of(self.work), [], 'something the capture started is still running')
        self.app.capture.invoke()                                               # and again: it goes on
        self.wait(lambda: self.ctl.phase == 'finished')
        self.assertRegex(self.ctl.summary.headline, r'^Done: 128 lines in 3 branches, \d+ pictures\.$')
        lines = [r for r in read_jsonl(os.path.join(self.work, 'out', 'log.jsonl')) if r['ev'] == 'shot']
        self.assertEqual(len(lines), 128)                                       # nothing twice, nothing lost


if __name__ == '__main__':
    unittest.main()
