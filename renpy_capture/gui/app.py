"""The window: a thin layer of Tk over the controller. It shows what the controller says and passes the person's choices
to it; what is decided is in controller.py, what is said in strings.py."""
import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from . import strings as S
from .controller import Controller, Problem, Settings, clock_text, config_dir

POLL = 200                      # milliseconds between looks at what a running capture has said
LOG_LINES = 2000                # lines of the text of a run kept in the window (the log file has them all)
SIZE = (720, 680)               # the size of the window the first time, at 96 dpi
BAD, QUIET, NOTE = '#b3261e', '#5f6368', '#8a5300'          # colours of an error, of a help, of a warning


def make_sharp():
    """On Windows a program that does not say it can draw at the screen's own resolution is blown up by the system,
    and looks blurry at 125% and more."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except (ImportError, AttributeError, OSError):
        pass


def _go(event, backwards):
    """Tab and Shift+Tab leave a text that is only read (Tk's text keeps them for itself)."""
    (event.widget.tk_focusPrev() if backwards else event.widget.tk_focusNext()).focus_set()
    return 'break'


def selectable(text):
    """Make a text that nobody changes a text that anybody can select and copy: a click gives it the keyboard,
    Ctrl+A selects all, Ctrl+C copies, the right button offers both."""
    text.bind('<Button-1>', lambda e: e.widget.focus_set(), add='+')
    text.bind('<Control-a>', lambda e: (e.widget.tag_add('sel', '1.0', 'end-1c'), 'break')[1])
    text.bind('<Tab>', lambda e: _go(e, False))
    for shift in ('<Shift-Tab>', '<ISO_Left_Tab>'):
        try:
            text.bind(shift, lambda e: _go(e, True))
        except tk.TclError:                                 # Windows has no such key
            pass
    menu = tk.Menu(text, tearoff=False)
    menu.add_command(label=S.COPY, command=lambda: text.event_generate('<<Copy>>'))
    menu.add_command(label=S.SELECT_ALL, command=lambda: text.tag_add('sel', '1.0', 'end-1c'))

    def popup(event):
        event.widget.focus_set()
        menu.tk_popup(event.x_root, event.y_root)
        return 'break'

    text.bind('<Button-3>', popup)


class Words(tk.Text):
    """A few words to read, select and copy, which nobody can change: as high as what they say, up to ``lines``."""

    def __init__(self, parent, lines=1, font=None, tag=None):
        look = ttk.Style(parent).lookup('TFrame', 'background') or parent.winfo_toplevel().cget('background')
        font = font or tkfont.nametofont('TkDefaultFont')
        super().__init__(parent, width=10, height=1, wrap='word', relief='flat', borderwidth=0, highlightthickness=0,
                         padx=0, pady=0, state='disabled', takefocus=False, cursor='xterm', background=look, font=font)
        self.measure = font.measure
        self.most, self.said, self.tag, self.fitting, self.again, self.later = lines, None, tag, False, False, None
        for name, colour in (('bad', BAD), ('quiet', QUIET), ('note', NOTE)):
            self.tag_configure(name, foreground=colour)
        selectable(self)
        self.bind('<Configure>', lambda e: self.fit_later())

    def say(self, text, tag=None):
        """Say ``text``; nothing at all takes no room."""
        tag = tag or self.tag
        if (text, tag) == self.said:
            return
        self.said = (text, tag)
        self.configure(state='normal')
        self.delete('1.0', 'end')
        self.insert('1.0', text, (tag,) if tag else ())
        self.configure(state='disabled')
        self.grid() if text else self.grid_remove()
        self.fit_later()

    def fit_later(self):
        if self.later is None:
            self.later = self.after_idle(self.fit_now)

    def fit_now(self):
        self.later = None
        self.fit()

    def destroy(self):
        if self.later is not None:
            self.after_cancel(self.later)
        super().destroy()

    def wrapped(self):
        """How many lines the words take at the width the box has, by the measure of the font: whole words go to the
        next line, a word longer than a line (a path) is cut where the line ends, as Tk does."""
        width = self.winfo_width()
        if width <= 20 or not self.said:
            return 1
        measure = self.measure
        space, total = measure(' '), 0
        for paragraph in self.said[0].split('\n'):
            lines, used = 1, 0
            for word in paragraph.split(' '):
                length = measure(word)
                if used and used + space + length > width:
                    lines, used = lines + 1, 0
                used += (space if used else 0) + length
                while used > width:                         # a word that does not fit a line of its own
                    lines, used = lines + 1, used - width
            total += lines
        return total

    def fit(self):
        """Take the height of the text laid out at the width the window gives it: what the font measures, or what Tk
        counts when it is more (Tk lays a text out when it is idle, so it is made to before it is asked)."""
        if self.fitting:
            self.again = True
            return
        self.fitting, self.again = True, False
        try:
            self.update_idletasks()
            counted = self.count('1.0', 'end-1c', 'displaylines')
            shown = max((counted[0] if isinstance(counted, tuple) else counted) or 1, self.wrapped())
            height = max(1, min(shown, self.most))
            if int(self.cget('height')) != height:
                self.configure(height=height)
        except tk.TclError:                                 # gone with its window
            return
        finally:
            self.fitting = False
        if self.again:                                      # the width changed while it was being measured
            self.fit_later()


class LogView(ttk.Frame):
    """The text of a run, as it comes: scrolls by itself while the person is at the end of it, and not when they are
    reading further up."""

    def __init__(self, parent):
        super().__init__(parent)
        self.text = tk.Text(self, width=10, height=6, wrap='word', state='disabled', relief='solid', borderwidth=1,
                            font=tkfont.nametofont('TkFixedFont'), takefocus=True, padx=6, pady=4)
        bar = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        self.text.grid(row=0, column=0, sticky='nsew')
        bar.grid(row=0, column=1, sticky='ns')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        selectable(self.text)

    def add(self, lines):
        if not lines:
            return
        at_end = self.text.yview()[1] >= 0.999
        self.text.configure(state='normal')
        self.text.insert('end', ''.join(line + '\n' for line in lines))
        extra = int(self.text.index('end-1c').split('.')[0]) - 1 - LOG_LINES        # (a last line with nothing in it)
        if extra > 0:
            self.text.delete('1.0', f'{extra + 1}.0')
        self.text.configure(state='disabled')
        if at_end:
            self.text.see('end')

    def clear(self):
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.configure(state='disabled')


class App:
    def __init__(self, root, controller):
        self.root, self.ctl = root, controller
        self.told_of_bug = False
        root.title(S.TITLE)
        try:                                                # its own icon in the title bar and the taskbar, not Tk's
            from .icon import PNG64
            self.icon = tk.PhotoImage(data=PNG64)           # (held: Tk drops a picture that nothing holds)
            root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        self.style = ttk.Style(root)
        if sys.platform not in ('win32', 'darwin') and 'clam' in self.style.theme_names():
            self.style.theme_use('clam')                    # the plain theme of Tk on Linux is not a pleasure to look at
        self._fonts()
        self._build()
        self._bind()
        size = self.ctl.settings.window()
        width, height = size or (self.px(SIZE[0]), self.px(SIZE[1]))
        root.geometry(f'{width}x{height}')
        root.minsize(self.px(560), self.px(560))
        self.load_form()
        self.render_run()
        (self.capture if self.ctl.info.ok else self.game_entry).focus_set()
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.report_callback_exception = self.on_bug
        self.timer = root.after(POLL, self.tick)
        root.bind('<Destroy>', self.on_destroy)

    # -- building

    def px(self, n):
        """``n`` pixels at 96 dpi, as many as the screen's own resolution makes of them."""
        return round(n * self.root.winfo_fpixels('1i') / 96)

    def _fonts(self):
        base = tkfont.nametofont('TkDefaultFont')
        self.bold, self.big = base.copy(), base.copy()
        self.bold.configure(weight='bold')
        size = base.cget('size')
        self.big.configure(weight='bold', size=size + 3 if size > 0 else size - 4)
        self.style.configure('Capture.TButton', font=self.big, padding=(self.px(12), self.px(8)))
        if self.style.theme_use() == 'clam':                # the fill of its bar is paler than its trough
            accent = '#2f6fcf'
            self.style.configure('Horizontal.TProgressbar', background=accent, lightcolor=accent, darkcolor=accent,
                                 troughcolor='#c9c7c1', bordercolor='#a8a69f')

    def _build(self):
        px, root = self.px, self.root
        outer = ttk.Frame(root, padding=px(14))
        outer.grid(row=0, column=0, sticky='nsew')
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        self.game_var, self.work_var = tk.StringVar(), tk.StringVar()
        self.language_var, self.version_var, self.text_var = tk.StringVar(), tk.StringVar(), tk.BooleanVar()
        row = iter(range(100))
        wide = dict(column=0, columnspan=2, sticky='ew')

        ttk.Label(outer, text=S.GAME_LABEL, font=self.bold).grid(row=next(row), column=0, columnspan=2, sticky='w')
        r = next(row)
        self.game_entry = ttk.Entry(outer, textvariable=self.game_var)
        self.game_entry.grid(row=r, column=0, sticky='ew')
        self.game_browse = ttk.Button(outer, text=S.BROWSE, command=self.browse_game)
        self.game_browse.grid(row=r, column=1, padx=(px(8), 0))
        self.game_words = Words(outer, lines=3)
        self.game_words.grid(row=next(row), pady=(px(3), 0), **wide)

        ttk.Label(outer, text=S.WORK_LABEL, font=self.bold).grid(row=next(row), column=0, columnspan=2, sticky='w',
                                                                  pady=(px(10), 0))
        r = next(row)
        self.work_entry = ttk.Entry(outer, textvariable=self.work_var)
        self.work_entry.grid(row=r, column=0, sticky='ew')
        self.work_browse = ttk.Button(outer, text=S.BROWSE, command=self.browse_work)
        self.work_browse.grid(row=r, column=1, padx=(px(8), 0))
        self.work_words = Words(outer, lines=4)
        self.work_words.grid(row=next(row), pady=(px(3), 0), **wide)

        ttk.Label(outer, text=S.LANGUAGE_LABEL, font=self.bold).grid(row=next(row), column=0, columnspan=2,
                                                                      sticky='w', pady=(px(10), 0))
        self.language_box = ttk.Combobox(outer, textvariable=self.language_var, state='readonly')
        self.language_box.grid(row=next(row), pady=(px(2), 0), **wide)

        self.text_check = ttk.Checkbutton(outer, text=S.TEXT_LABEL, variable=self.text_var, command=self.on_text)
        self.text_check.grid(row=next(row), column=0, columnspan=2, sticky='w', pady=(px(10), 0))
        self.text_words = Words(outer, lines=3)
        self.text_words.grid(row=next(row), column=0, columnspan=2, sticky='ew', padx=(px(22), 0))
        self.text_words.say(S.TEXT_HELP, 'quiet')

        self.version_row = ttk.Frame(outer)                  # only for a game that does not tell its own version
        self.version_row.grid(row=next(row), pady=(px(10), 0), **wide)
        self.version_row.columnconfigure(1, weight=1)
        ttk.Label(self.version_row, text=S.VERSION_LABEL, font=self.bold).grid(row=0, column=0, sticky='w')
        self.version_box = ttk.Combobox(self.version_row, textvariable=self.version_var, state='readonly', width=12)
        self.version_box.grid(row=0, column=1, sticky='w', padx=(px(10), 0))
        self.version_words = Words(self.version_row, lines=3)
        self.version_words.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(px(2), 0))

        self.capture = ttk.Button(outer, text=S.CAPTURE, style='Capture.TButton', command=self.on_capture,
                                  default='active')
        self.capture.grid(row=next(row), pady=(px(14), px(10)), **wide)
        ttk.Separator(outer).grid(row=next(row), **wide)

        top = ttk.Frame(outer)
        top.grid(row=next(row), pady=(px(10), 0), **wide)
        top.columnconfigure(0, weight=1)
        self.status = Words(top, lines=3, font=self.bold)
        self.status.grid(row=0, column=0, sticky='ew')
        self.elapsed = ttk.Label(top, text='')
        self.elapsed.grid(row=0, column=1, sticky='ne', padx=(px(10), 0))
        self.bar = ttk.Progressbar(outer, mode='determinate', maximum=100)
        self.bar.grid(row=next(row), pady=(px(6), px(4)), **wide)
        self.bar_mode = 'determinate'
        self.detail = Words(outer, lines=2)
        self.detail.grid(row=next(row), **wide)
        self.notes = Words(outer, lines=12)
        self.notes.grid(row=next(row), pady=(px(4), 0), **wide)

        ttk.Label(outer, text=S.LOG_LABEL, style='TLabel').grid(row=next(row), column=0, columnspan=2, sticky='w',
                                                                  pady=(px(8), px(2)))
        self.log = LogView(outer)
        r = next(row)
        self.log.grid(row=r, column=0, columnspan=2, sticky='nsew')
        outer.rowconfigure(r, weight=1)

        self.buttons = ttk.Frame(outer)
        self.buttons.grid(row=next(row), pady=(px(10), 0), **wide)
        self.cancel = ttk.Button(self.buttons, text=S.CANCEL, command=self.on_cancel)
        self.open_page = ttk.Button(self.buttons, text=S.OPEN_PAGE, command=lambda: self.opened(self.ctl.open_page()))
        self.open_folder = ttk.Button(self.buttons, text=S.OPEN_FOLDER,
                                      command=lambda: self.opened(self.ctl.open_folder()))
        self.open_log = ttk.Button(self.buttons, text=S.OPEN_LOG, command=lambda: self.opened(self.ctl.open_log()))
        for n, button in enumerate((self.cancel, self.open_page, self.open_folder, self.open_log)):
            button.grid(row=0, column=n, padx=(0, px(8)))

    def _bind(self):
        for entry, apply in ((self.game_entry, self.apply_game), (self.work_entry, self.apply_work)):
            for key in ('<Return>', '<KP_Enter>'):
                entry.bind(key, self._committed(apply))
            entry.bind('<FocusOut>', lambda e, a=apply: a())
        self.language_box.bind('<<ComboboxSelected>>', lambda e: self.on_language())
        self.version_box.bind('<<ComboboxSelected>>', lambda e: self.ctl.set_version(self.version_var.get()))
        for key in ('<Return>', '<KP_Enter>'):
            self.root.bind(key, self.on_return)
        self.root.bind('<Escape>', lambda e: self.on_cancel() if self.ctl.phase == 'running' else None)

    def _committed(self, apply):
        """Enter in a box takes what was typed and goes on to the next one, as Tab does."""
        def handler(event):
            apply()
            event.widget.tk_focusNext().focus_set()
            return 'break'
        return handler

    # -- what is on the form

    def load_form(self):
        """Everything the controller knows about the choices, into the widgets."""
        c = self.ctl
        self.game_var.set(c.game_text)
        self.work_var.set(c.workdir_text)
        for entry in (self.game_entry, self.work_entry):    # a long path shows its end: the name of the folder
            entry.xview_moveto(1.0)
        self.language_box.configure(values=c.language_labels())
        self.language_box.current(c.language_index())
        self.text_var.set(c.text)
        if c.needs_version():
            self.version_box.configure(values=c.version_choices())
            self.version_var.set(c.version)
            self.version_words.say(S.VERSION_HELP + (' ' + S.VERSION_HINT_MAJOR.format(major=c.info.major)
                                                     if c.info.major else ''), 'quiet')
            self.version_row.grid()
        else:
            self.version_row.grid_remove()
        self.render_form()

    def render_form(self):
        c = self.ctl
        self.game_words.say(c.info.message, None if c.info.ok else 'bad')
        w = c.work
        lines = [w.message] if w.message else [S.WORK_HELP]
        self.work_words.say('\n'.join(lines + list(w.notes)), 'bad' if not w.ok else None if w.message else 'quiet')
        self.render_buttons()

    def render_buttons(self):
        c = self.ctl
        running = c.phase == 'running'
        self.capture.state(['!disabled'] if c.can_start() else ['disabled'])
        for widget in (self.game_entry, self.game_browse, self.work_entry, self.work_browse, self.text_check):
            widget.state(['disabled'] if running else ['!disabled'])
        for widget in (self.language_box, self.version_box):
            widget.state(['disabled'] if running else ['!disabled', 'readonly'])

    def apply_game(self):
        if self.ctl.phase == 'running' or self.game_var.get() == self.ctl.game_text:
            return
        self.ctl.set_game(self.game_var.get())
        self.load_form()

    def apply_work(self):
        if self.ctl.phase == 'running' or self.work_var.get() == self.ctl.workdir_text:
            return
        self.ctl.set_workdir(self.work_var.get())
        self.render_form()

    def browse_game(self):
        start = self.ctl.info.root or self.ctl.info.path or None
        chosen = filedialog.askdirectory(parent=self.root, title=S.BROWSE_GAME_TITLE, initialdir=start, mustexist=True)
        if chosen:
            self.game_var.set(chosen)
            self.apply_game()
            if self.ctl.can_start():
                self.capture.focus_set()

    def browse_work(self):
        start = self.ctl.work.path or self.ctl.workdir_text or None
        chosen = filedialog.askdirectory(parent=self.root, title=S.BROWSE_WORK_TITLE, initialdir=start)
        if chosen:
            self.work_var.set(chosen)
            self.apply_work()

    def on_language(self):
        index = self.language_box.current()
        self.ctl.set_language(self.ctl.info.languages[index - 1] if index > 0 else None)
        self.render_form()

    def on_text(self):
        self.ctl.set_text(self.text_var.get())
        self.render_form()

    # -- the run

    def on_capture(self):
        self.apply_game()
        self.apply_work()
        if not self.ctl.can_start():
            return
        question = self.ctl.question()
        if question and not messagebox.askyesno(S.WORK_OTHER_FILES_TITLE, question, parent=self.root):
            return
        try:
            self.ctl.start()
        except Problem as e:
            messagebox.showerror(S.TITLE, str(e), parent=self.root)
            return
        self.log.clear()
        self.render_form()
        self.render_run()
        self.log.text.focus_set()

    def on_cancel(self):
        if self.ctl.phase == 'running' and not self.ctl.stopping and \
                messagebox.askyesno(S.CANCEL_TITLE, S.CANCEL_ASK, parent=self.root, default='no'):
            self.ctl.cancel()
            self.render_run()

    def on_return(self, event):
        w = self.root.focus_get()
        if w is self.capture:
            self.on_capture()
        elif isinstance(w, ttk.Button):
            w.invoke()

    def opened(self, ok):
        if not ok:
            messagebox.showwarning(S.TITLE, S.OPEN_FAILED.format(path=self.ctl.log or self.ctl.work.path),
                                   parent=self.root)

    def tick(self):
        try:
            self.ctl.pump()
            self.log.add(self.ctl.take_text())
            self.render_run()
        finally:
            if self.timer is not None:
                self.root.after_cancel(self.timer)          # (a look that was not the timer's: only one is pending)
                self.timer = self.root.after(POLL, self.tick)

    def on_destroy(self, event):
        """The window is going: its timers go with it (the bar's too), so that none runs into nothing."""
        if event.widget is self.root and self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
            try:
                self.bar.stop()                             # (its widget may be gone already)
            except tk.TclError:
                pass

    def render_run(self):
        c = self.ctl
        running, finished = c.phase == 'running', c.phase == 'finished'
        self.render_buttons()
        if c.phase == 'idle':
            self.status.say('')
            self.detail.say('')
            self.notes.say('')
            self.elapsed.configure(text='')
        else:
            tag = 'bad' if finished and c.summary.kind == 'failed' else None
            self.status.say(c.headline(), tag)
            self.detail.say(c.detail(), 'quiet')
            self.notes.say('\n'.join(c.summary.lines) if finished else '',
                           'bad' if tag else None)
            self.elapsed.configure(text=S.ELAPSED.format(time=clock_text(c.elapsed())))
        self.render_bar()
        shown = {self.cancel: running, self.open_page: finished and bool(c.summary.index),
                 self.open_folder: finished, self.open_log: running or finished}
        for button, show in shown.items():
            button.grid() if show else button.grid_remove()
        self.cancel.state(['disabled'] if c.stopping else ['!disabled'])

    def render_bar(self):
        c = self.ctl
        fraction = c.fraction()
        if c.phase == 'running' and fraction is None:
            if self.bar_mode != 'indeterminate':
                self.bar.configure(mode='indeterminate')
                self.bar.start(15)
                self.bar_mode = 'indeterminate'
            return
        if self.bar_mode != 'determinate':
            self.bar.stop()
            self.bar.configure(mode='determinate')
            self.bar_mode = 'determinate'
        done = c.phase == 'finished' and c.summary.kind == 'done'
        self.bar.configure(value=100 if done else 100 * (fraction or 0))

    def on_bug(self, kind, error, trace):
        """A mistake of this program in what a click or a timer ran: the window has no console to say it in, so it is
        written down and the person told once, and the window goes on."""
        import traceback
        text = ''.join(traceback.format_exception(kind, error, trace))
        path = os.path.join(config_dir(), 'window-errors.log')
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f'=== {time.strftime("%Y-%m-%d %H:%M:%S")}\n{text}\n')
        except OSError:
            path = None
        print(text, file=sys.stderr)
        if not self.told_of_bug:
            self.told_of_bug = True
            messagebox.showerror(S.TITLE, S.BUG.format(error=f'{kind.__name__}: {error}', path=path or ''),
                                 parent=self.root)

    def on_close(self):
        if self.ctl.phase == 'running' and not messagebox.askyesno(S.CANCEL_TITLE, S.CANCEL_ASK, parent=self.root,
                                                                   default='no'):
            return
        self.ctl.settings.remember_window(self.root.winfo_width(), self.root.winfo_height())
        self.ctl.close()
        self.bar.stop()
        self.root.destroy()


def run(settings_path=None):
    """Open the window and stay until it is closed."""
    make_sharp()
    try:
        root = tk.Tk()
    except tk.TclError as e:                                # no screen to open a window on
        sys.exit(f'renpy-capture gui: cannot open a window: {e}')
    App(root, Controller(Settings(settings_path)))
    root.mainloop()
