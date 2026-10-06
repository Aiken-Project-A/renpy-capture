"""Machine-readable progress, for a program that runs renpy-capture (the window, a script). With ``--progress-json`` the
standard output carries one JSON object per line, one for each update, and everything meant for a person (what the
command line says) goes to the standard error instead. Without it ``emit`` does nothing.

Every event has an "event" and, besides it:

  stage     "stage": setup, capture, check or export: the step the capture is at
  fetch     "what": sdk or unrpyc, "version", "step": download, verify, unpack or done, and for a download its "done" and
            "total" (bytes), for an unpack its "done" and "total" (files); "total" is null when it is not known
  progress  "jobs_done", "jobs_total", "lines", "now" (the job under way, null when none or several), "engines": how far
            a capture is, every second or two
  done      the capture is over: its summary (docs/guide.md, "The progress a program can read")
  error     "message": the command is stopping, and why

The lines are ASCII, whatever the system's code page; the text on the standard error is UTF-8.
"""
import json
import sys
import threading
import time

_out = None             # the real standard output while machine mode is on
_lock = threading.Lock()


def active():
    return _out is not None


def enable():
    """Machine mode: events go to the standard output of now, and ``print`` to the standard error."""
    global _out
    if _out is not None:
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    _out = sys.stdout
    sys.stdout = sys.stderr


def disable():
    global _out
    if _out is None:
        return
    sys.stdout, _out = _out, None


def emit(event, **fields):
    """One event as a line of JSON. A reader that went away is no reason to stop a capture."""
    if _out is None:
        return
    line = json.dumps(dict(event=event, **fields), separators=(',', ':')) + '\n'
    with _lock:
        try:
            _out.write(line)
            _out.flush()
        except (OSError, ValueError):
            pass


class Every:
    """``Every(0.25)()`` is True at most four times a second; ``force`` is for the last update, which must not be
    held back (the end of a download)."""

    def __init__(self, seconds):
        self.seconds, self.last = seconds, None

    def __call__(self, force=False):
        now = time.monotonic()
        if force or self.last is None or now - self.last >= self.seconds:
            self.last = now
            return True
        return False
