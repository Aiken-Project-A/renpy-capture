"""A window for people who never open a terminal: pick the game, press Capture. ``controller`` holds what the window
decides and ``strings`` what it says (both work without a display, and are what the tests cover); ``app`` is the thin
Tk layer on top of them."""
import os
import sys


def _say(text):
    """Tell the person what is wrong where they will see it: a window of the system on Windows (the program has no
    console there), the standard error elsewhere."""
    if os.name == 'nt' and getattr(sys, 'stderr', None) is None:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, 'renpy-capture', 0x10)
            return
        except (OSError, AttributeError):
            pass
    print(text, file=sys.stderr)


def main():
    """Open the window; it returns when the window is closed."""
    try:
        from . import app
    except ImportError as e:                                # Python without Tk (some Linux packages leave it out)
        if getattr(e, 'name', None) not in ('tkinter', '_tkinter'):
            raise
        from . import strings
        _say(strings.NO_TK)
        sys.exit(1)
    app.run()
