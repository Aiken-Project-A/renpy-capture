"""Command line: renpy-capture <command> …"""
import argparse
import os
import sys

from . import __version__


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='renpy-capture',
        description="Screenshots of every line of a Ren'Py game, taken by the game's own engine "
                    '(the official SDK of the same version), with the script line of each one.')
    ap.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    sub = ap.add_subparsers(dest='cmd', required=True, metavar='command')

    def engine_opts(p):
        p.add_argument('--timewarp', type=float, default=4.0, help='game seconds per real second of animation '
                       '(default 4; the frame clock makes runs repeatable at any value)')
        p.add_argument('--display', choices=('kwin', 'xvfb', 'window'),
                       help='where the engine draws: kwin (a virtual KDE compositor, GPU), xvfb (a virtual X server, '
                            'software GL) or window (your desktop; default: the first one available)')
        p.add_argument('--gpu', choices=('auto', 'nvidia', 'mesa'), help='OpenGL vendor for the engine (default auto)')
        p.add_argument('--screen', help='size of the virtual screen, WIDTHxHEIGHT (default 1920x1200)')

    p = sub.add_parser('init', help='write a starter config for a game')
    p.add_argument('game')
    p.add_argument('config')

    p = sub.add_parser('sdk', help="download the Ren'Py SDK a game needs (done by setup/run when missing)")
    p.add_argument('game', nargs='?', help='the game (its Ren\'Py version picks the SDK)')
    p.add_argument('--renpy-version', help="the Ren'Py version, instead of a game or when the game does not tell it")

    p = sub.add_parser('setup', help='make a launch folder: links to the game plus the capture script')
    p.add_argument('game')
    p.add_argument('rundir')
    p.add_argument('--renpy-version', help="the Ren'Py version, when the game does not tell it")
    p.add_argument('--sdk', help="use this unpacked Ren'Py SDK instead of downloading one")
    p.add_argument('--exclude', help='regex of files in game/ to leave out (e.g. a machine-translation mod)')

    p = sub.add_parser('run', help='run the jobs of a config in one engine')
    p.add_argument('rundir')
    p.add_argument('config')
    p.add_argument('out')
    p.add_argument('--stall', type=float, default=180, help='seconds without progress before a job counts as hung')
    engine_opts(p)

    p = sub.add_parser('prun', help='run the jobs on several engines at once')
    p.add_argument('rundir')
    p.add_argument('config')
    p.add_argument('out')
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--batch', type=int, default=8, help='jobs per engine launch')
    engine_opts(p)

    p = sub.add_parser('explore', help='run, then add a job for every menu option not taken yet, until none is left')
    p.add_argument('rundir')
    p.add_argument('config')
    p.add_argument('out')
    p.add_argument('--rounds', type=int, default=10)
    p.add_argument('--limit', type=int, default=600, help='at most this many jobs in the config')
    p.add_argument('--workers', type=int, default=1)
    p.add_argument('--batch', type=int, default=8)
    engine_opts(p)

    p = sub.add_parser('report', help='summary of a capture: jobs, steps, frames, stops, errors')
    p.add_argument('out')

    p = sub.add_parser('gaps', help='scene/show lines of the scripts that no job has reached')
    p.add_argument('game')
    p.add_argument('config')
    p.add_argument('out')

    p = sub.add_parser('compare', help='check that two runs of the same jobs match (exit code 1 if not)')
    p.add_argument('reference')
    p.add_argument('out')
    p.add_argument('--states-only', action='store_true',
                   help='compare what is on screen at every line, not the pixels (runs on different GPUs)')

    p = sub.add_parser('forget', help='drop jobs from a capture before capturing them again')
    p.add_argument('out')
    p.add_argument('jobs', nargs='+')

    p = sub.add_parser('export', help='shots.tsv + index.html (every line with its frame), optionally CG pictures')
    p.add_argument('out')
    p.add_argument('game')
    p.add_argument('dest')
    p.add_argument('--options', help='JSON file with export options (cg, crop, effects…; see docs/config.md)')
    p.add_argument('--no-page', action='store_true', help='do not write index.html')

    a = ap.parse_args(argv)
    try:
        dispatch(a)
    except (ImportError, ValueError) as e:        # a game we cannot read, a missing optional tool
        if os.environ.get('RENPY_CAPTURE_DEBUG'):
            raise
        sys.exit(f'renpy-capture: {e}')


def dispatch(a):
    if a.cmd == 'init':
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
    elif a.cmd == 'run':
        from .runner import run
        run(a.rundir, a.config, a.out, a.timewarp, a.stall, a.display, a.gpu, a.screen)
    elif a.cmd == 'prun':
        from .runner import prun
        prun(a.rundir, a.config, a.out, a.workers, a.timewarp, a.batch, a.display, a.gpu, a.screen)
    elif a.cmd == 'explore':
        from .runner import explore
        explore(a.rundir, a.config, a.out, a.rounds, a.timewarp, a.limit, a.workers, a.batch, a.display, a.gpu,
                a.screen)
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
        export(a.out, a.game, a.dest, opts, page=not a.no_page)


if __name__ == '__main__':
    main()
