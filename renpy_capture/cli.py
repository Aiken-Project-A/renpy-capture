"""Command line: renpy-capture <command> …"""
import argparse
import os
import sys

from . import __version__

EPILOG = """\
The usual way, one command, everything in one work folder:
  renpy-capture capture ~/Games/MyGame work/      then open work/export/index.html
  run it again to go on after an interruption or after editing work/config.json

Step by step (what capture does): init, setup, explore, gaps, export.
Checking a capture: report, gaps, compare.  Finer work: run, prun, forget, sdk.
`renpy-capture <command> --help` describes a command."""

GAME = "the game: its folder (the one with game/ inside) or game/ itself"
CONFIG = 'the config file (JSON): the jobs and how to capture them; `init` writes a starter one'
RUNDIR = 'the launch folder made by `setup`: links to the game plus the capture script'
DISPLAY_HELP = ('where the engine draws. Linux: kwin (a virtual KDE compositor, GPU), xvfb (a virtual X server, '
                'software GL) or window (your desktop); default: the first one available. Windows: window (your '
                'desktop, the default), offscreen (your desktop, the window beyond the edge of the screen) or '
                'desktop (a desktop of its own, never on your screen)')
OUT = 'the capture folder: every picture (frames/) and the log of every line (log.jsonl)'


def main(argv=None):
    if os.name == 'nt':                             # a console or a file in the code page of Windows: a line of the
        for stream in (sys.stdout, sys.stderr):     # game it cannot spell must not stop the capture
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(errors='backslashreplace')
    ap = argparse.ArgumentParser(
        prog='renpy-capture', formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EPILOG,
        description="Screenshots of every line of a Ren'Py game, taken by the game's own engine "
                    '(the official SDK of the same version), with the script line of each one.')
    ap.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    sub = ap.add_subparsers(dest='cmd', required=True, metavar='command')

    def engine_opts(p):
        p.add_argument('--timewarp', type=float, default=4.0, help='game seconds per real second of animation '
                       '(default 4; the frame clock makes runs repeatable at any value)')
        p.add_argument('--display', choices=('kwin', 'xvfb', 'window', 'offscreen', 'desktop'),
                       help=DISPLAY_HELP)
        p.add_argument('--gpu', choices=('auto', 'nvidia', 'mesa'), help='OpenGL vendor for the engine (default auto)')
        p.add_argument('--screen', help='size of the virtual screen, WIDTHxHEIGHT (default 1920x1200)')
        p.add_argument('--fast', action='store_true',
                       help='skip the frames drawn while a scene settles: the same scenes, faster on animated '
                            'games, but animations may be caught in another phase than without it')
        p.add_argument('--language', help="capture a translation: the language as its folder game/tl/<language> is "
                                          "named (default: the game's own language)")
        p.add_argument('--text', action='store_true',
                       help="keep the game's dialogue window, speech bubbles and menus in the frames (to check how "
                            'the text fits); without it frames show the scene alone')

    p = sub.add_parser('capture', help='the usual way in one command: every branch of a game, captured into a work '
                                       'folder, and the pages to read it')
    p.add_argument('game', help=GAME)
    p.add_argument('workdir', help='a folder for everything: config.json, the launch folder run/, the capture out/ '
                                   'and the pages export/ (a translation or --text get out-…/export-… of their own)')
    p.add_argument('--workers', type=int, default=1,
                   help='engines at once (default 1; 4 on a machine with a GPU and memory to spare)')
    p.add_argument('--renpy-version', help="the Ren'Py version, when the game does not tell it")
    p.add_argument('--sdk', help="use this unpacked Ren'Py SDK instead of downloading one")
    p.add_argument('--exclude', help='regex of files in game/ to leave out (e.g. a machine-translation mod)')
    p.add_argument('--rounds', type=int, default=10, help='rounds of exploring new branches (default 10)')
    p.add_argument('--limit', type=int, default=600, help='at most this many jobs in the config (default 600)')
    engine_opts(p)

    p = sub.add_parser('init', help='write a starter config for a game')
    p.add_argument('game', help=GAME)
    p.add_argument('config', help='where to write it')

    p = sub.add_parser('sdk', help="download the Ren'Py SDK a game needs (done by setup/run when missing)")
    p.add_argument('game', nargs='?', help="the game (its Ren'Py version picks the SDK)")
    p.add_argument('--renpy-version', help="the Ren'Py version, instead of a game or when the game does not tell it")

    p = sub.add_parser('setup', help='make a launch folder: links to the game plus the capture script')
    p.add_argument('game', help=GAME)
    p.add_argument('rundir', help='the launch folder to make (the game itself is never changed)')
    p.add_argument('--renpy-version', help="the Ren'Py version, when the game does not tell it")
    p.add_argument('--sdk', help="use this unpacked Ren'Py SDK instead of downloading one")
    p.add_argument('--exclude', help='regex of files in game/ to leave out (e.g. a machine-translation mod)')

    p = sub.add_parser('run', help='run the jobs of a config in one engine')
    p.add_argument('rundir', help=RUNDIR)
    p.add_argument('config', help=CONFIG)
    p.add_argument('out', help=OUT)
    p.add_argument('--stall', type=float, default=180, help='seconds without progress before a job counts as hung')
    engine_opts(p)

    p = sub.add_parser('prun', help='run the jobs on several engines at once')
    p.add_argument('rundir', help=RUNDIR)
    p.add_argument('config', help=CONFIG)
    p.add_argument('out', help=OUT)
    p.add_argument('--workers', type=int, default=4, help='engines at once (default 4)')
    p.add_argument('--batch', type=int, default=8, help='jobs per engine launch')
    engine_opts(p)

    p = sub.add_parser('explore', help='run, then add a job for every menu option not taken yet, until none is left')
    p.add_argument('rundir', help=RUNDIR)
    p.add_argument('config', help=CONFIG + '; the new jobs are added to it')
    p.add_argument('out', help=OUT)
    p.add_argument('--rounds', type=int, default=10, help='rounds of exploring new branches (default 10)')
    p.add_argument('--limit', type=int, default=600, help='at most this many jobs in the config')
    p.add_argument('--workers', type=int, default=1, help='engines at once (default 1)')
    p.add_argument('--batch', type=int, default=8, help='jobs per engine launch, with --workers')
    engine_opts(p)

    p = sub.add_parser('report', help='summary of a capture: jobs, steps, frames, stops, errors')
    p.add_argument('out', help=OUT)

    p = sub.add_parser('gaps', help='scene/show lines of the scripts that no job has reached')
    p.add_argument('game', help=GAME)
    p.add_argument('config', help=CONFIG)
    p.add_argument('out', help=OUT)

    p = sub.add_parser('compare', help='check that two runs of the same jobs match (exit code 1 if not)')
    p.add_argument('reference', help='the capture folder to compare with')
    p.add_argument('out', help='the capture folder to check')
    p.add_argument('--states-only', action='store_true',
                   help='compare what is on screen at every line, not the pixels (runs on different GPUs)')

    p = sub.add_parser('forget', help='drop jobs from a capture before capturing them again')
    p.add_argument('out', help=OUT)
    p.add_argument('jobs', nargs='+', help='the ids of the jobs to drop')

    p = sub.add_parser('export', help='shots.tsv + index.html (every line with its frame), optionally CG pictures')
    p.add_argument('out', help=OUT)
    p.add_argument('game', help=GAME)
    p.add_argument('dest', help='the folder to write the pages and the table into')
    p.add_argument('--options', help='JSON file with export options (cg, crop, effects…; see docs/config.md)')
    p.add_argument('--no-page', action='store_true', help='do not write index.html')
    p.add_argument('--beside', help='another capture of the same jobs (a translation, captured with --language): its '
                                    'lines and frames next to these, step by step')

    a = ap.parse_args(argv)
    try:
        dispatch(a)
    except (ImportError, ValueError) as e:        # a game we cannot read, a missing optional tool
        if os.environ.get('RENPY_CAPTURE_DEBUG'):
            raise
        sys.exit(f'renpy-capture: {e}')


def dispatch(a):
    if a.cmd == 'capture':
        from .workflow import capture
        capture(a.game, a.workdir, workers=a.workers, version=a.renpy_version, sdk_dir=a.sdk, exclude=a.exclude,
                rounds=a.rounds, limit=a.limit, language=a.language, text=a.text, fast=a.fast, timewarp=a.timewarp,
                display=a.display, gpu=a.gpu, screen=a.screen)
    elif a.cmd == 'init':
        from .runner import init_config
        init_config(a.game, a.config)
    elif a.cmd == 'sdk':
        from . import sdk
        from .game import engine_version
        v = a.renpy_version or (engine_version(a.game) if a.game else None)
        if not v:
            sys.exit("give a game whose Ren'Py version can be told, or --renpy-version")
        print(sdk.ensure(v))
    elif a.cmd == 'setup':
        from .runner import setup
        setup(a.game, a.rundir, a.renpy_version, a.sdk, a.exclude)
    elif a.cmd in ('run', 'prun', 'explore'):
        from . import runner
        engine = dict(timewarp=a.timewarp, display=a.display, gpu=a.gpu, screen=a.screen, fast=a.fast,
                      language=a.language, text=a.text)
        if a.cmd == 'run':
            runner.run(a.rundir, a.config, a.out, stall=a.stall, **engine)
        elif a.cmd == 'prun':
            runner.prun(a.rundir, a.config, a.out, workers=a.workers, batch=a.batch, **engine)
        else:
            runner.explore(a.rundir, a.config, a.out, rounds=a.rounds, limit=a.limit, workers=a.workers,
                           batch=a.batch, **engine)
    elif a.cmd == 'report':
        from .analysis import report
        report(a.out)
    elif a.cmd == 'gaps':
        from .analysis import gaps
        gaps(a.game, a.config, a.out)
    elif a.cmd == 'compare':
        from .analysis import compare
        sys.exit(0 if compare(a.reference, a.out, frames=not a.states_only) else 1)
    elif a.cmd == 'forget':
        from .analysis import forget
        forget(a.out, a.jobs)
    elif a.cmd == 'export':
        from .export import export
        from .util import read_json
        opts = read_json(a.options) if a.options else None
        export(a.out, a.game, a.dest, opts, page=not a.no_page, beside=a.beside)


if __name__ == '__main__':
    main()
