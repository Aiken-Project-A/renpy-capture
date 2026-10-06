"""The usual way in one command: a work folder that holds the config, the launch folder, the capture and the pages
made from it. Running the same command again goes on where it stopped."""
import contextlib
import io
import os

from . import analysis, events, export, runner
from .util import near, plural, read_json, read_jsonl


def paths(workdir, language=None, text=False):
    """Where everything of a work folder lives. A capture with text and a translation get folders of their own next
    to the plain one (out-text, out-russian, out-text-russian), so all of them can share one work folder."""
    tag = ('-text' if text else '') + (f'-{language}' if language else '')
    return {'config': os.path.join(workdir, 'config.json'), 'run': os.path.join(workdir, 'run'),
            'out': os.path.join(workdir, 'out' + tag), 'export': os.path.join(workdir, 'export' + tag)}


def capture(game, workdir, workers=1, version=None, sdk_dir=None, exclude=None, rounds=10, limit=600,
            language=None, text=False, fast=False, timewarp=4.0, display=None, gpu=None, screen=None):
    """A starter config (unless the work folder has one: it is the user's to edit), the launch folder, every branch
    captured, what was left unreached, and the pages. A translation captured next to the original gets its page beside
    the original's. Ends with what to open. Returns the paths of the work folder."""
    p = paths(workdir, language, text)
    os.makedirs(workdir, exist_ok=True)
    events.emit('stage', stage='setup')
    if not os.path.exists(p['config']):
        runner.init_config(game, p['config'])
    info = os.path.join(p['run'], runner.RUN_INFO)
    if not version and not sdk_dir and os.path.exists(info):   # the version an earlier run was given or told
        old = read_json(info)
        version, sdk_dir = old.get('version'), old.get('sdk')
    runner.setup(game, p['run'], version, sdk_dir, exclude)
    events.emit('stage', stage='capture')
    complete = runner.explore(p['run'], p['config'], p['out'], rounds=rounds, timewarp=timewarp, limit=limit,
                              workers=workers, display=display, gpu=gpu, screen=screen, fast=fast,
                              language=language, text=text)
    events.emit('stage', stage='check')
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            found = analysis.gaps(game, p['config'], p['out'])
        missed, why = sum(len(v) for v in found.values()), None
    except ImportError as e:
        missed, why = None, str(e)
    original = paths(workdir, None, text)['out']
    beside = bool(language) and os.path.exists(os.path.join(original, 'log.jsonl'))
    events.emit('stage', stage='export')
    with contextlib.redirect_stdout(io.StringIO()):
        if beside:
            export.export(original, game, p['export'], beside=p['out'])
        else:
            export.export(p['out'], game, p['export'])
    s = summary(p, workdir, complete, missed, why, language, text, beside)
    _summary(game, p, s)
    events.emit('done', **s)
    return p


def summary(p, workdir, complete, missed, why, language, text, beside):
    """What a capture came to: lines, jobs and pictures, whether every menu option was taken, the jobs that stopped on
    a script error, the scene lines no branch reached (``missed``; None when they could not be checked, ``why``), the
    warnings of `report`, and where the pages are (absolute paths). The same numbers are told to a person by
    `_summary` and to a program by the `done` event."""
    recs = read_jsonl(os.path.join(p['out'], 'log.jsonl'))
    shots = [r for r in recs if r['ev'] == 'shot']
    jobs = {r['job'] for r in recs if r['ev'] == 'end'}
    frames = {r['frame'] for r in shots if r.get('frame')}
    errors = {r['job'] for r in recs if r['ev'] == 'error' and not r.get('ignored')}
    with contextlib.redirect_stdout(io.StringIO()):         # said already, between the rounds
        warned = analysis.report(p['out'], brief=True)['warnings']
    page = os.path.abspath(p['export'])
    choices = os.path.join(page, 'choices.html')
    return {'lines': len(shots), 'jobs': len(jobs), 'pictures': len(frames), 'complete': bool(complete),
            'errors': sorted(errors), 'missed': missed, 'unchecked': why, 'warnings': warned,
            'language': language, 'text': bool(text), 'beside': bool(beside),
            'workdir': os.path.abspath(workdir), 'config': os.path.abspath(p['config']),
            'out': os.path.abspath(p['out']), 'export': page, 'index': os.path.join(page, 'index.html'),
            'choices': choices if os.path.exists(choices) else None, 'table': os.path.join(page, 'shots.tsv')}


def _summary(game, p, s):
    print()
    print(f"Done: {plural(s['lines'], 'line')} in {plural(s['jobs'], 'job')}, {plural(s['pictures'], 'picture')}"
          + (', every menu option taken.' if s['complete'] else '; some branches are still to take: run it again.'))
    if s['errors']:
        print(f"{plural(len(s['errors']), 'job')} stopped on a script error: renpy-capture report {near(p['out'])}")
    if s['unchecked']:
        print(f"Lines left unreached: not checked, {s['unchecked']}.")
    elif s['missed']:
        print(f"{plural(s['missed'], 'scene line')} never reached (a branch behind a flag set earlier?): "
              f"renpy-capture gaps {near(game)} {near(p['config'])} {near(p['out'])}")
    else:
        print('Every scene line was reached.')
    if s['language'] and not s['beside']:
        print('Capture the original too (the same command without --language) to see the translation beside it.')
    print('Open:')
    print(f"  {near(os.path.join(p['export'], 'index.html'))}    every line with its picture"
          + (', the translation beside the original' if s['beside'] else ''))
    if s['choices']:
        print(f"  {near(os.path.join(p['export'], 'choices.html'))}  the tree of choices")
    print(f"  {near(os.path.join(p['export'], 'shots.tsv'))}     the same as a table")
    print(f"Run the same command again to go on after an interruption or after editing {near(p['config'])}.")
