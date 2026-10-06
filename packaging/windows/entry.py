"""The program the Windows build starts (see renpy-capture.spec): given arguments it is the `renpy-capture` command,
started without any (a double-click) it opens the window."""
import multiprocessing
import sys


def let_go_of_the_console():
    """A double-click on renpy-capture.exe, the program for the command line, opens a console that the window does not
    need: let go of it when nobody else is using it (a console that a terminal lent is left alone). The window's own
    program, renpy-capture-gui.exe, never has one."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        if kernel.GetConsoleWindow() and kernel.GetConsoleProcessList((ctypes.c_uint * 2)(), 2) <= 1:
            kernel.FreeConsole()
    except (OSError, AttributeError):
        pass


def main():
    multiprocessing.freeze_support()            # the pool of processes that export uses starts this program again
    if len(sys.argv) > 1:
        from renpy_capture.cli import main as command
        command()
    else:
        let_go_of_the_console()
        from renpy_capture.gui import main as window
        window()


if __name__ == '__main__':
    main()
