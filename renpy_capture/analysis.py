"""Reading a capture: a summary, a comparison of two runs, forgetting jobs, and the lines no job has reached."""
import ast
import collections
import json
import operator
import os
import re

from .game import Game
from .util import read_json, read_jsonl, script_path


def _records(out):
    p = os.path.join(out, 'log.jsonl')
    if not os.path.exists(p):
        return None
    return read_jsonl(p)


def report(out, brief=False):
    """Per job: interactions captured, distinct frames, skipped frames, menus, why it stopped, errors, duration; then
    warnings and where the time went. ``brief`` (between rounds of explore) keeps the warnings and the jobs that
    stopped on an error only. Returns the totals: jobs, lines, pictures, jobs with errors."""
    recs = _records(out)
    if recs is None:
        print('no log: the engine did not record a single event')
        return {'jobs': 0, 'lines': 0, 'pictures': 0, 'errors': []}
    jobs = collections.OrderedDict()
    frames = set()
    stops = collections.Counter()
    late = []                                       # wait_menus menus answered after wait_max
    for r in recs:
        j = jobs.setdefault(r['job'], {'shots': 0, 'frames': set(), 'skip': 0, 'menus': 0, 'stop': None,
                                       'errors': 0, 'end': None, 'prev': None})
        if r['ev'] == 'shot':
            j['shots'] += 1
            if r.get('frame'):
                j['frames'].add(r['frame'])
                frames.add(r['frame'])
            if r.get('skip'):
                j['skip'] += 1
            if r.get('menu'):
                j['menus'] += 1
                p = j['prev']                       # the same menu captured again, now answered: its timer never came
                if 'pick' in r['menu'] and p and (p.get('menu') or {}).get('wait') \
                        and (p.get('file'), p.get('line')) == (r.get('file'), r.get('line')):
                    late.append(f"{r['job']}: \"{((r['menu'].get('options') or ['?'])[0])[:40]}\"")
            j['prev'] = r
        elif r['ev'] == 'stop':
            where = f"{r.get('file') or ''}{':' + str(r['line']) if r.get('line') else ''}"
            j['stop'] = f"{r['why']} {r.get('label') or ''} {where}".strip()
            stops[r['why']] += 1
        elif r['ev'] == 'error':                    # the tail of a Ren'Py traceback is platform, version and date:
            j['errors'] += 1                        # take the line of the error itself
            tb = r['error'].strip().splitlines()
            msg = next((x for x in reversed(tb) if re.match(r'[\w.]+(Error|Exception|Exit)\b', x)), tb[-1])
            j['error'] = ('ignored: ' if r.get('ignored') else '') + msg[:200]
        elif r['ev'] == 'end':
            j['end'] = f"{r['why']} {r.get('seconds')} s"
    for k, j in jobs.items():
        if brief and not (j['errors'] and not j['error'].startswith('ignored')):
            continue
        print(f"{k:40} steps {j['shots']:5}  frames {len(j['frames']):4}  skip {j['skip']:3}  menus {j['menus']:3}  "
              f"{j['stop'] or ''}  {('error: ' + j['error']) if j['errors'] else ''}  [{j['end']}]")
    if not brief:
        print(f'jobs {len(jobs)}, distinct frames {len(frames)}, stops: {dict(stops)}')
    steps = sum(j['shots'] for j in jobs.values())
    secs = sum(r.get('seconds') or 0 for r in recs if r['ev'] == 'end')
    moving = sum(1 for r in recs if r['ev'] == 'shot' and r.get('anim'))
    if steps >= 20 and moving > 0.9 * steps:        # nearly every capture waited for a scene that never settled
        print(f'warning: {moving} of {steps} captures were taken while something was still moving. An overlay '
              '(a mod, a HUD screen with an animation) may never stop; list its screens in `ui` or its files in '
              '`drop`, or leave it out with setup --exclude')
    if late:
        print(f"warning: {len(late)} menu(s) of wait_menus were answered after wait_max, the game's timer never led "
              f"on ({'; '.join(late[:5])}{'; …' if len(late) > 5 else ''}). A timer on an interface screen runs only "
              'with ui_timers; a longer timer needs a larger wait_max')
    if steps >= 20 and secs / steps > 2:            # a healthy engine takes a fraction of a second per interaction
        print(f'warning: {secs / steps:.1f} s per interaction is very slow; the GPU driver may be in a bad state '
              '(try --gpu mesa or --display xvfb)')
    prof = collections.Counter()                    # where the time of the jobs went (captures since this field)
    for r in recs:
        if r['ev'] == 'end' and r.get('prof'):
            prof.update(r['prof'])
    if prof['frames'] and not brief:
        rest = secs - prof['draw'] - prof['shot'] - prof['png'] - prof['save']
        print(f"time in jobs {secs:.0f} s: drawing {prof['frames']:.0f} frames {prof['draw']:.0f} s, "
              f"{prof['shots']:.0f} screenshots {prof['shot']:.0f} s ({prof['known']:.0f} of them pictures this "
              f"engine had saved, no PNG), PNG {prof['png']:.0f} s for {prof['encoded']:.0f} pictures, "
              f"writing {prof['save']:.0f} s, the rest {rest:.0f} s")
    return {'jobs': len(jobs), 'lines': steps, 'pictures': len(frames),
            'errors': [k for k, j in jobs.items() if j['errors'] and not j['error'].startswith('ignored')]}


def forget(out, ids):
    """Treat jobs as never captured: their records leave the log and the "done" list (frames stay, the log no longer
    mentions them). Needed before capturing a job again: the log is appended to, old records would double lines."""
    ids = set(ids)
    for name in ('log.jsonl', 'done.txt'):
        p = os.path.join(out, name)
        if not os.path.exists(p):
            continue
        keep, gone = [], 0
        with open(p, encoding='utf-8') as f:
            lines = f.readlines()
        for line in lines:
            job = json.loads(line).get('job') if name == 'log.jsonl' else line.strip()
            if job in ids:
                gone += 1
            else:
                keep.append(line)
        with open(p + '.new', 'w', encoding='utf-8') as f:
            f.writelines(keep)
        os.replace(p + '.new', p)
        print(f'{name}: {gone} records removed')


def compare(a, b, frames=True):
    """Two runs of the same jobs (a reference and a candidate): the same order of captures, the same scene state on
    every line (image attributes as a set: Ren'Py returns them from a set) and the same frame. Frames are compared by
    the sha1 of the PNG, which only makes sense when both runs used the same GL; ``frames=False`` compares scene
    states only (runs on different GPUs or drivers). A capture in the middle of an endless animation (anim) may
    differ in phase and is counted apart; only a frame of a scene at rest counts as a mismatch."""
    def norm(shown):
        return sorted(' '.join([s.split()[0]] + sorted(s.split()[1:])) for s in (shown or []) if s)

    def load(out):
        shots, secs = collections.defaultdict(list), {}
        for r in _records(out) or []:
            if r['ev'] == 'shot':
                shots[r['job']].append(r)
            elif r['ev'] == 'end':
                secs[r['job']] = r.get('seconds') or 0
        return shots, secs

    def state(p):
        return (script_path(p.get('file')), p.get('line'), norm(p.get('shown')), p.get('screens'), p.get('files'), p.get('cam'),
                (p.get('menu') or {}).get('pick'))

    sa, ta = load(a)
    sb, tb = load(b)
    common = sorted(set(sa) & set(sb))
    bad, anim, same, total = 0, 0, 0, 0
    for j in common:
        x, y = sa[j], sb[j]
        if len(x) != len(y):
            bad += 1
            print(f'{j}: captures {len(x)} / {len(y)}')
        for p, q in zip(x, y):
            total += 1
            if state(p) != state(q):
                bad += 1
                print(f'{j} #{p.get("seq")}: scene state\n   {state(p)}\n   {state(q)}')
                break
            if not frames or p.get('frame') == q.get('frame'):
                same += 1
            elif p.get('anim') or q.get('anim') or p.get('peak') or q.get('peak'):
                anim += 1
            else:
                bad += 1
                print(f'{j} #{p.get("seq")} {p.get("kind")} {p.get("file")}:{p.get("line")}: '
                      'a different frame of a scene at rest')
    only = sorted(set(sa) ^ set(sb))
    print(f'jobs {len(common)}, captures {total}: ' + (f'same frame {same}, another animation phase {anim}, '
                                                          if frames else f'same scene state {same}, ')
          + f'mismatches {bad}' + (f'; only in one run: {", ".join(only)}' if only else ''))
    secs = [sum(t.get(j, 0) for j in common) for t in (ta, tb)]      # a job the engine died in has no end
    print(f'job time: {secs[0]:.0f} s / {secs[1]:.0f} s')
    return bad == 0 and not only


class _Unknown(Exception):
    """A name that gaps_scope does not set."""


_COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
            ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Is: operator.is_, ast.IsNot: operator.is_not,
            ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}


def _evaluate(expr, scope):
    """The value of a condition of a script, from the names of ``scope`` alone. The text is the game's, not ours: it
    is never handed to eval (a crafted condition would run on the machine of whoever runs `gaps`); only names,
    constants, comparisons, and/or/not, arithmetic and subscripts are computed, anything else raises ValueError
    (undecided). A name that is not in ``scope`` raises _Unknown."""
    def go(n):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in scope:
                raise _Unknown(n.id)
            return scope[n.id]
        if isinstance(n, ast.BoolOp):
            for v in n.values:
                r = go(v)
                if bool(r) == isinstance(n.op, ast.Or):
                    break
            return r
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.Not, ast.USub, ast.UAdd)):
            r = go(n.operand)
            return not r if isinstance(n.op, ast.Not) else -r if isinstance(n.op, ast.USub) else +r
        if isinstance(n, ast.Compare) and all(type(o) in _COMPARE for o in n.ops):
            left = go(n.left)
            for op, right in zip(n.ops, n.comparators):
                right = go(right)
                if not _COMPARE[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult)):
            a, b = go(n.left), go(n.right)
            if isinstance(n.op, ast.Mult):          # "x" * 10**9 would eat the memory: numbers only
                if not all(isinstance(v, (int, float)) for v in (a, b)):
                    raise ValueError('a product of things that are not numbers')
                return a * b
            return a + b if isinstance(n.op, ast.Add) else a - b
        if isinstance(n, ast.IfExp):
            return go(n.body) if go(n.test) else go(n.orelse)
        if isinstance(n, ast.Subscript):
            return go(n.value)[go(n.slice)]
        if isinstance(n, (ast.Tuple, ast.List, ast.Set)):
            return [go(e) for e in n.elts] if isinstance(n, ast.List) else \
                tuple(go(e) for e in n.elts) if isinstance(n, ast.Tuple) else {go(e) for e in n.elts}
        raise ValueError(f'not a condition gaps_scope can decide: {type(n).__name__}')
    return go(ast.parse(expr.strip(), mode='eval').body)


GAP_LABEL = re.compile(r'^(\s*)label\s+([A-Za-z_][\w.]*)')
GAP_SAY = re.compile(r'^\s*(?:[A-Za-z_]\w*\s+)*"[^"]')
GAP_STMT = re.compile(r'^\s*(play|queue|stop|voice|sound|music|show|scene|hide|with|window|pause|jump|call|return|'
                      r'image|define|default|init|python|label|if|elif|else|while|for)\b')     # not lines of dialogue
GAP_SHOW = re.compile(r'^\s*(scene|show)\s+(?!screen\b|layer\b)(\S.*?)\s*:?\s*$')
GAP_COND = re.compile(r'^\s*(if|elif)\s+(.+?)\s*:\s*$')
GAP_ELSE = re.compile(r'^\s*else\s*:\s*$')


def gaps(game, cfg_path, out, show=True):
    """What the capture missed: scene/show lines of the scripts that no job went past. Exploration branches every menu
    option once for the whole game, but a flag set earlier can choose a branch later on; such a branch stays
    uncaptured until an exact job (label, scope with the flag, choices) is added. A line counts as passed when the log
    has a capture on it or before the next line of dialogue after it (lines with `multiple=` are shown together, the
    capture is on the last one).
    Not counted: hub labels (stop_labels), branches closed by the values in gaps_scope (a condition decided by those
    values alone, e.g. `if outfit_b` when outfit_a is set), labels matching gaps_skip (whole alternative scenes), and
    lines whose picture was captured elsewhere (a show right before a jump is captured on the first line of the next
    label)."""
    cfg = read_json(cfg_path)
    hubs = re.compile(cfg['stop_labels']) if cfg.get('stop_labels') else None
    skip = re.compile(cfg['gaps_skip']) if cfg.get('gaps_skip') else None
    scope = dict(cfg.get('gaps_scope') or {})

    names = re.compile(r'\b(' + '|'.join(map(re.escape, scope)) + r')\b') if scope else None

    def value(cond):                                # True/False if gaps_scope alone decides it, otherwise None
        if names is None or not names.search(cond):
            return None
        try:
            return bool(_evaluate(cond, scope))
        except _Unknown:                            # "b and x" is false for any x, "a or x" is true
            rest = re.sub(r'\b(?!(?:' + '|'.join(map(re.escape, scope)) + r')\b)[A-Za-z_]\w*(?:\.\w+)*\b(?!\s*\()',
                          'None', cond)
            try:
                return bool(_evaluate(rest, scope))
            except Exception:
                return None
        except Exception:
            return None

    def closed(lines, i):                           # the line sits in a branch gaps_scope makes unreachable
        ind = len(lines[i - 1]) - len(lines[i - 1].lstrip())
        n = i - 1
        while n > 0 and ind > 0:
            ln = lines[n - 1]
            d = len(ln) - len(ln.lstrip())
            if ln.strip() and not ln.lstrip().startswith('#') and d < ind:
                m, e = GAP_COND.match(ln), GAP_ELSE.match(ln)
                if m and value(m.group(2)) is False:
                    return True
                if (m and m.group(1) == 'elif') or e:
                    k = n - 1                       # a true if/elif above in the same chain closes this branch
                    while k > 0:
                        lk = lines[k - 1]
                        dk = len(lk) - len(lk.lstrip())
                        if lk.strip() and not lk.lstrip().startswith('#'):
                            if dk < d:
                                break
                            if dk == d:
                                mk = GAP_COND.match(lk)
                                if not mk:
                                    break
                                if value(mk.group(2)) is True:
                                    return True
                                if mk.group(1) == 'if':
                                    break
                        k -= 1
                ind = d
            n -= 1
        return False

    seen = collections.defaultdict(set)
    pics = collections.defaultdict(list)            # tag -> attribute sets that were on screen in some capture
    for r in _records(out) or []:
        if r['ev'] == 'shot' and r.get('file'):
            seen[script_path(r['file'])].add(r.get('line'))
            for s in r.get('shown') or ():
                t = s.split()
                if t and set(t[1:]) not in pics[t[0]]:
                    pics[t[0]].append(set(t[1:]))

    def on_screen(spec):
        name = re.split(r'\s+(?:with|at|onlayer|as|behind|zorder)\b', spec)[0].strip().rstrip(':').split()
        return bool(name) and any(set(name[1:]) <= a for a in pics.get(name[0], ()))

    found, closed_n, elsewhere = collections.defaultdict(list), 0, 0
    for f, text in sorted(Game(game).scripts().items()):
        f = re.sub(r'^game/', '', f)
        if os.path.basename(f).startswith('zz_renpy_capture'):
            continue
        lines = text.split('\n')
        cur = None
        for i, ln in enumerate(lines, 1):
            m = GAP_LABEL.match(ln)
            if m:
                cur = m.group(2)
                continue
            if ln.strip() and not ln[0].isspace() and not ln.lstrip().startswith('#'):
                cur = None                          # a top-level statement that is not a label (image, screen, init)
            s = GAP_SHOW.match(ln)
            if not s or cur is None or (hubs and hubs.search(cur)):
                continue
            end, ind = i, len(ln) - len(ln.lstrip())
            for k in range(i + 1, min(len(lines), i + 400) + 1):
                lk = lines[k - 1]
                if GAP_LABEL.match(lk) or (lk.strip() and not lk.lstrip().startswith('#')
                                           and len(lk) - len(lk.lstrip()) < ind):
                    break                           # the block of the line ended (an if/menu branch): a capture below
                end = k                             # belongs to the code shared by all branches
                if GAP_SAY.match(lines[k - 1]) and not GAP_STMT.match(lines[k - 1]) and '(multiple=' not in lines[k - 1]:
                    break
            if any(n in seen.get(f, ()) for n in range(i, end + 1)):
                continue
            if (skip and skip.match(cur)) or closed(lines, i):
                closed_n += 1
                continue
            if on_screen(s.group(2)):
                elsewhere += 1
                continue
            found[(f, cur)].append((i, s.group(2)[:60]))
    total = sum(len(v) for v in found.values())
    if show:
        print(f'scene/show lines not reached: {total} in {len(found)} labels (not counted: hubs, alternatives and '
              f'branches closed by gaps_scope — {closed_n}; picture captured elsewhere — {elsewhere})')
        for (f, lab), xs in sorted(found.items(), key=lambda x: (-len(x[1]), x[0])):
            print(f'{len(xs):5}  {lab:28} {f}:{xs[0][0]}  {xs[0][1]}' + (f'  (+{len(xs) - 1})' if len(xs) > 1 else ''))
    return found
