"""Export a capture: every interaction with the frame on screen at that moment (shots.tsv and a browsable
index.html), and optionally the game's event pictures (CG) cut out as separate images."""
import collections
import html
import os
import re
import shutil

from .game import Game
from .util import read_jsonl, script_path

SCENARIO_LABEL = re.compile(r'^\s*label\s+([A-Za-z_][\w.]*)')


class Labels:
    """The label of a scene by file and line: the nearest `label` above the line in the script (decompiled scripts
    keep the line numbers of the original, the same numbers the engine reports)."""

    def __init__(self, scripts):
        self.scripts, self.cache = scripts, {}

    def __call__(self, fn, line, skip=None):
        if not fn or not line:
            return None
        rel = script_path(fn)
        if rel not in self.cache:
            marks = []
            for i, ln in enumerate((self.scripts.get(rel) or '').split('\n'), 1):
                m = SCENARIO_LABEL.match(ln)
                if m:
                    marks.append((i, m.group(1)))
            self.cache[rel] = marks
        best = None
        for i, name in self.cache[rel]:             # skip: labels that do not name a scene (replay entry points in
            if i > line:                            # the middle of a scene): the story label above is taken
                break
            if skip is None or not skip.match(name):
                best = name
        return best


def coverage(data, area):
    """The share of the frame (``area`` pixels) covered by opaque pixels of an image, 0..1."""
    import io
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        a = im.getchannel('A') if 'A' in im.getbands() else None
        n = sum(a.histogram()[17:]) if a is not None else im.size[0] * im.size[1]
    return n / float(area)


def is_effect(path, crop=None, dark=3.5, bright=0.3, edges=2.5, flat=2.0):
    """A frame that is an effect rather than a picture: a blackout (mean brightness < dark), a flash (more than
    ``bright`` of it lighter than 200 with poor edges < edges: white glow without a drawing) or one flat colour
    (brightness spread < flat; a "black" is sometimes dark grey drawn over the scene)."""
    from PIL import Image, ImageFilter, ImageStat
    with Image.open(path) as im:
        g = (im.crop(crop) if crop else im).convert('L').resize((250, 188))
    mean = ImageStat.Stat(g).mean[0]
    light = sum(g.histogram()[200:]) / (250 * 188)
    edge = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]
    return mean < dark or (light > bright and edge < edges) or ImageStat.Stat(g).stddev[0] < flat


def _effect_job(args):
    return is_effect(*args)


def _save_job(args):
    from PIL import Image
    src, dst, crop = args
    with Image.open(src) as im:
        (im.crop(crop) if crop else im).save(dst)


FX_BLOCK = re.compile(r'^(\s*)(image|screen)\s+([A-Za-z_][\w ]*?)\s*(?:\([^)]*\))?\s*(:|=)')
FX_FILE = re.compile(r'"([^"]+\.(?:png|webp|jpg|jpeg))"', re.I)
FX_REF = re.compile(r'"([A-Za-z_][\w ]*)"')


def fx_defs(scripts, names, files=()):
    """Effects of lines: name -> kind (image, screen, file, caption), the files it draws (following images it refers
    to, e.g. `add "glow"`, and Ren'Py's automatic images named after files in images/) and its definition."""
    blocks = {}
    for text in scripts.values():
        lines = text.split('\n')
        for i, line in enumerate(lines):
            m = FX_BLOCK.match(line)
            if not m:
                continue
            name = ' '.join(m.group(3).split())
            if name in blocks:
                continue
            ind, body = len(m.group(1)), [line.strip()]
            if m.group(4) == ':':
                for nxt in lines[i + 1:]:
                    if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= ind:
                        break
                    if nxt.strip():
                        body.append(nxt.strip())
            blocks[name] = (m.group(2), body)
    auto = {}
    for f in files:
        if f.lower().startswith('images/') and re.search(r'\.(png|webp|jpe?g)$', f, re.I):
            auto.setdefault(os.path.splitext(os.path.basename(f))[0].lower(), f)

    def files_of(name, depth=0):
        if depth > 3:
            return []
        if name not in blocks:
            return [auto[name.lower()]] if name.lower() in auto else []
        _kind, body = blocks[name]
        text = ' '.join(body if len(body) == 1 else body[1:])
        rv = FX_FILE.findall(text)
        for ref in FX_REF.findall(text):
            if ref != name and not re.search(r'\.(png|webp|jpe?g)$', ref, re.I):
                rv += files_of(' '.join(ref.split()), depth + 1)
        return rv

    out = {}
    for n in sorted(names):
        key = ('text ' + n[5:]) if n.startswith('text:') else n
        if re.search(r'\.(png|webp|jpe?g)$', n, re.I):
            out[n] = ('file', [n], '')
        elif key in blocks:
            kind, body = blocks[key]
            out[n] = ('caption' if n.startswith('text:') else kind, sorted(set(files_of(key))), ' ⏎ '.join(body))
        else:
            out[n] = ('caption' if n.startswith('text:') else '?', files_of(key), n[5:] if n.startswith('text:') else '')
    return out


def _place(src, dst):
    if os.path.exists(dst):
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def _tsv(v):
    return '' if v is None else str(v).replace('\t', ' ').replace('\r', ' ').replace('\n', ' ⏎ ')


def export(out, game, dest, opts=None, page=True, beside=None):
    """``out`` is a capture output, ``game`` the game, ``dest`` the export folder. ``opts`` (all optional):
    cg — regex of image files that make an event picture (CG); with it, cg/<label>_<NN>.png and cg.tsv are written;
    cg_min — the share of the frame such a file must cover (0.08); crop — [x0, y0, x1, y1] of the picture area;
    scenario — regex of script files whose labels name scenes (all files); label_skip — regex of labels that do not
    name scenes ('^_'); min_pause — a frame shown for a shorter pause is an effect (0.25 s); flash — regex of
    flash images: a frame with one of them on screen is an effect; effects — regex of effect tags and screens: frames
    of the same scene without them are one CG, the cleanest one is kept; context — for chains of labels joined by
    jumps, take a CG from the run that reached it with the most scene behind it; fx_skip — regex of line effects not
    to list. ``beside`` is another capture of the same jobs (a translation, captured with --language): its lines,
    menus and frames go next to these, step by step, as long as it takes the game the same way."""
    opts = opts or {}
    g = Game(game)
    try:
        scripts = g.scripts()
    except ImportError as e:
        print(f'{e}\nscene names come from the log instead')
        scripts = {}
    labels = Labels(scripts)
    crop = tuple(opts['crop']) if opts.get('crop') else None
    cgrx = re.compile(opts['cg']) if opts.get('cg') else None
    fmin = float(opts.get('cg_min', 0.08))
    scen = re.compile(opts.get('scenario') or '.')
    aside = re.compile(opts.get('label_skip') or '^_')
    blink = float(opts.get('min_pause', 0.25))
    flash = re.compile(opts['flash']) if opts.get('flash') else None
    fx_skip = re.compile(opts['fx_skip']) if opts.get('fx_skip') else None
    fx = re.compile(opts['effects']) if opts.get('effects') else None
    log = read_jsonl(os.path.join(out, 'log.jsonl'))
    frame_path = lambda h: os.path.join(out, 'frames', h + '.png')
    low = {k.lower(): k for k in g.files}

    def read(rel):                                  # the engine searches case-insensitively and with prefixes
        for pre in ('', 'images/'):                 # (config.search_prefixes)
            if pre + rel.lower() in low:
                return g.files[low[pre + rel.lower()]]()
        raise KeyError(rel)

    effect = {}
    if cgrx:
        from concurrent.futures import ProcessPoolExecutor
        hashes = sorted({r['frame'] for r in log if r.get('ev') == 'shot' and r.get('frame')})
        with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as ex:
            for h, v in zip(hashes, ex.map(_effect_job, [(frame_path(h), crop) for h in hashes], chunksize=16)):
                effect[h] = v

    def at(fn, line):
        return labels(fn or '', line) if scen.search(fn or '') else None

    def places(r):                                  # the line itself, then the return points, nearest call first
        return [(r.get('file'), r.get('line'))] + [tuple(x) for x in reversed(r.get('stack') or [])]

    callers = collections.defaultdict(set)          # a shared procedure called from two or more scenes does not
    for r in log:                                   # give its name to a frame
        if r['ev'] == 'shot' and r.get('stack'):
            here = at(r.get('file'), r.get('line'))
            up = next((a for a in (at(f, ln) for f, ln in places(r)[1:]) if a), None)
            if here and up and up != here:
                callers[here].add(up)
    shared = {lab for lab, c in callers.items() if len(c) >= 2}
    # a procedure without a single line of dialogue (a picture change with a transition) does not name frames
    # either: its caller does
    talky = {at(r.get('file'), r.get('line')) for r in log if r['ev'] == 'shot' and 'Say' in (r.get('kind') or '')}
    mute = {lab for lab in callers if lab not in talky}

    def story(r):
        if not scripts:
            return r.get('label')
        for f, ln in places(r):
            lab = labels(f or '', ln, skip=aside) if scen.search(f or '') else None
            if lab and lab not in shared and lab not in mute:
                return lab
        return None

    ctx_first, ctx_depth = {}, {}
    if opts.get('context'):
        for r in log:
            if r['ev'] == 'shot':
                k = (r.get('file'), r.get('line'), tuple(tuple(x) for x in r.get('stack') or []))
                ctx_first.setdefault((k, r['job']), r['seq'])
        for (k, _), s in ctx_first.items():
            ctx_depth[k] = max(ctx_depth.get(k, -1), s)

    def in_context(r):
        if not ctx_depth:
            return True
        k = (r.get('file'), r.get('line'), tuple(tuple(x) for x in r.get('stack') or []))
        return ctx_first[(k, r['job'])] >= ctx_depth[k]

    def content(r):                                 # what the scene is made of without effects: images with
        keep = lambda x: x and not (fx and fx.match(x.split()[0]))     # attributes (as a set), screens, event files
        norm = lambda x: ' '.join(x.split()[:1] + sorted(x.split()[1:]))
        return (tuple(sorted(norm(x) for x in r.get('shown', []) if keep(x))),
                tuple(x for x in r.get('screens', []) if keep(x)),
                tuple(sorted(f for f in r.get('files', []) if cgrx.search(f))))

    def dirt(r):                                    # how far a frame is from clean: an effect over the scene, then
        cam = r.get('cam') or {}                    # the camera away from rest; the cleanest frame represents a CG
        rest = {'zoom': 1, 'xzoom': 1, 'yzoom': 1}
        fxd = bool(fx and any(fx.match(x.split()[0]) for x in r.get('shown', []) + r.get('screens', []) if x))
        return (fxd, round(sum(abs(v - rest.get(k, 0)) * (100 if k in rest else 1) for k, v in cam.items()), 1))

    first = {}
    for r in log:
        if r['ev'] == 'shot' and r['job'] not in first and story(r):
            first[r['job']] = story(r)
    os.makedirs(os.path.join(dest, 'frames'), exist_ok=True)
    area = (crop[2] - crop[0]) * (crop[3] - crop[1]) if crop else None
    names, counters, rows, shots = {}, collections.Counter(), [], []
    by_content, row_of, score, to_save, cur_label, cover = {}, {}, {}, {}, {}, {}
    for r in log:
        if r['ev'] == 'start':
            cur_label[r['job']] = first.get(r['job']) or r['label']
            continue
        if r['ev'] != 'shot':
            continue
        fn = script_path(r.get('file'))
        lab = cur_label[r['job']] = story(r) or cur_label.get(r['job'])
        h = r.get('frame')
        name = ''
        if h and cgrx:
            if area is None:
                from PIL import Image
                with Image.open(frame_path(h)) as im0:
                    area = im0.width * im0.height
            ev = [f for f in r.get('files', []) if cgrx.search(f)]
            for f in ev:
                if f not in cover:
                    try:
                        cover[f] = coverage(read(f), area)
                    except (OSError, KeyError):
                        cover[f] = 1.0
            is_cg = in_context(r) \
                and not (flash and any(flash.match(x.split()[0]) for x in r.get('shown', []) if x)) \
                and not (r.get('pause') is not None and 0 < r['pause'] < blink) \
                and any(cover[f] >= fmin for f in ev) \
                and not effect.get(h)
            c = content(r) if fx else None
            if h in names:
                name = names[h]
            elif is_cg and c is not None and c in by_content:   # the same scene: the same CG, cleanest frame kept
                name = names[h] = by_content[c]
                if dirt(r) < score[name]:
                    to_save[name] = h
                    rows[row_of[name]] = (name, h, r['job'], r['seq'], fn, r.get('line'), rows[row_of[name]][6],
                                          ' '.join(r.get('shown', [])), ' '.join(r.get('screens', [])))
                    score[name] = dirt(r)
            elif is_cg:
                counters[lab] += 1
                name = f'{lab}_{counters[lab]:02d}'
                names[h] = name
                if c is not None:
                    by_content[c], score[name] = name, dirt(r)
                to_save[name] = h
                row_of[name] = len(rows)
                rows.append((name, h, r['job'], r['seq'], fn, r.get('line'), lab, ' '.join(r.get('shown', [])),
                             ' '.join(r.get('screens', []))))
        effs = [e for e in r.get('fx', []) if not (fx_skip and fx_skip.search(e))]
        opts_txt = _menu_text(r)
        shots.append({'job': r['job'], 'step': r['seq'], 'file': fn, 'line': r.get('line'), 'label': lab,
                      'statement': r.get('kind') or '', 'who': r.get('who') or '', 'name': r.get('name') or '',
                      'what': r.get('what') or '', 'frame': h or '', 'cg': name, 'skip': 'skip' if r.get('skip') else '',
                      'effects': ' | '.join(effs), 'menu': opts_txt, 'tl': r.get('tl') or '',
                      'tl_file': script_path(r.get('tl_file')) or '', 'tl_line': r.get('tl_line') or '',
                      'caption': (r.get('menu') or {}).get('caption') or ''})
        if h:
            _place(frame_path(h), os.path.join(dest, 'frames', h + '.png'))
    cols = ['job', 'step', 'file', 'line', 'label', 'statement', 'who', 'name', 'what', 'frame', 'cg', 'skip',
            'effects', 'menu', 'tl', 'tl_file', 'tl_line', 'caption']
    apart, blang = {}, None
    if beside:
        apart, blang = _pair(shots, log, beside, dest)
        cols += ['beside_name', 'beside_what', 'beside_menu', 'beside_caption', 'beside_frame']
    with open(os.path.join(dest, 'shots.tsv'), 'w', encoding='utf-8') as f:
        f.write('\t'.join(cols) + '\n')
        for s in shots:
            f.write('\t'.join(_tsv(s[c]) for c in cols) + '\n')
    if cgrx:
        from concurrent.futures import ProcessPoolExecutor
        os.makedirs(os.path.join(dest, 'cg'), exist_ok=True)
        with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as ex:
            list(ex.map(_save_job, [(frame_path(h), os.path.join(dest, 'cg', n + '.png'), crop)
                                    for n, h in to_save.items()], chunksize=8))
        with open(os.path.join(dest, 'cg.tsv'), 'w', encoding='utf-8') as f:
            f.write('cg\tframe\tjob\tstep\tfile\tline\tlabel\timages\tscreens\n')
            for row in rows:
                f.write('\t'.join(_tsv(x) for x in row) + '\n')
    used = sorted({e for s in shots for e in s['effects'].split(' | ') if e})
    if used:
        with open(os.path.join(dest, 'effects.tsv'), 'w', encoding='utf-8') as f:
            f.write('effect\tkind\tfiles\tdefinition\n')
            for n, (kind, fl, d) in fx_defs(scripts, used, list(g.files)).items():
                f.write('\t'.join((_tsv(n), kind, ' '.join(fl), _tsv(d))) + '\n')
    if page:
        title = os.path.basename(os.path.abspath(game).rstrip(os.sep))
        tree = write_choices(dest, log, title)
        write_page(dest, shots, title, beside=(blang or 'the capture beside') if beside else None, apart=apart,
                   choices=tree)
    print(f'interactions: {len(shots)}, frames: {len({s["frame"] for s in shots if s["frame"]})}'
          + (f', CG: {len(rows)} (labels {len(counters)})' if cgrx else '') + f', effects: {len(used)}')
    for job, step in apart.items():
        print(f'{job}: the capture beside took another way at step {step}')


def _menu_text(r):
    menu = r.get('menu') or {}
    pick = menu.get('pick')
    return ' | '.join(('» ' if i == pick else '') + o for i, o in enumerate(menu.get('options', [])))


def _pair(shots, log, beside, dest):
    """Put the lines of another capture of the same jobs next to these, by job and step, until it takes another way
    (another line of the scripts, another translation id, or its job ends earlier): from there on a job has nothing
    beside it. Its frames are copied too. Returns {job: the step where it went apart} and its language."""
    blog = read_jsonl(os.path.join(beside, 'log.jsonl'))
    other = {(r['job'], r['seq']): r for r in blog if r['ev'] == 'shot'}
    apart = {}
    for s in shots:
        b = None if s['job'] in apart else other.get((s['job'], s['step']))
        if b is not None and ((script_path(b.get('file')), b.get('line')) != (s['file'], s['line'])
                              or (b.get('tl') and s['tl'] and b['tl'] != s['tl'])):   # (older captures have no ids)
            b = None
        if b is None:
            apart.setdefault(s['job'], s['step'])
            b = {}
        h = b.get('frame') or ''
        s.update(beside_name=b.get('name') or b.get('who') or '', beside_what=b.get('what') or '',
                 beside_menu=_menu_text(b), beside_caption=(b.get('menu') or {}).get('caption') or '',
                 beside_frame=h)
        if h:
            _place(os.path.join(beside, 'frames', h + '.png'), os.path.join(dest, 'frames', h + '.png'))
    return apart, next((r['language'] for r in blog if r['ev'] == 'start' and r.get('language')), None)


PAGE_CSS = """
:root { --bg: #f6f5f2; --card: #fff; --ink: #222; --muted: #6b6b6b; --line: #e3e0da; --pick: #1f6feb;
        --beside: #8a5a00; --warn: #b3261e; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #16171a; --card: #1f2125; --ink: #e8e6e3; --muted: #9a9a9a; --line: #2e3035; --pick: #6ea8ff;
          --beside: #e0b050; --warn: #ff8a80; }
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, sans-serif; }
header { padding: 20px 16px 8px; max-width: 1400px; margin: auto; }
header h1 { margin: 0 0 4px; font-size: 22px; }
header p { margin: 0; color: var(--muted); }
main { max-width: 1400px; margin: auto; padding: 8px 16px 40px; }
details { margin: 12px 0; border: 1px solid var(--line); border-radius: 8px; background: var(--card); }
summary { cursor: pointer; padding: 10px 14px; font-weight: 600; }
summary small { color: var(--muted); font-weight: 400; }
.shot { display: grid; grid-template-columns: minmax(0, 480px) minmax(0, 1fr); gap: 14px; padding: 12px 14px;
        border-top: 1px solid var(--line); }
.shot img { width: 100%; height: auto; border-radius: 4px; background: #000; display: block; }
.noimg { color: var(--muted); font-style: italic; }
.lines p { margin: 0 0 8px; }
.who { font-weight: 600; margin-right: 6px; }
.meta { color: var(--muted); font-size: 12px; margin-left: 6px; font-family: ui-monospace, monospace; }
.menu { list-style: none; padding: 0; margin: 0 0 8px; }
.menu li { padding: 2px 8px; border-left: 3px solid var(--line); margin: 2px 0; }
.menu li.pick { border-color: var(--pick); color: var(--pick); }
.shot.two { grid-template-columns: minmax(0, 420px) minmax(0, 420px) minmax(0, 1fr); }
.beside { border-left: 3px solid var(--beside); padding-left: 8px; }
.beside .who { color: var(--beside); }
.apart { color: var(--warn); font-style: italic; }
header a, .tree a { color: var(--pick); }
.tree { padding: 6px 14px 12px; }
.tree ul { list-style: none; margin: 0; padding-left: 18px; border-left: 1px solid var(--line); }
.tree > ul { padding-left: 0; border: 0; }
.tree li { margin: 4px 0; }
.ask { font-style: italic; }
.search { margin-top: 10px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.search input { width: 100%; max-width: 420px; padding: 6px 10px; font: inherit; color: var(--ink);
                background: var(--card); border: 1px solid var(--line); border-radius: 6px; }
.search span { color: var(--muted); font-size: 14px; }
.tree .untaken { color: var(--muted); }
.tree .end { color: var(--muted); }
@media (max-width: 760px) { .shot, .shot.two { grid-template-columns: 1fr; } }
"""


def _say(s, pre, cls=''):
    esc = html.escape
    who = s[pre + 'name'] or s.get(pre + 'who', '')
    return f'<p{cls}>{f"<span class=who>{esc(who)}</span>" if who else ""}{esc(s[pre + "what"])}'


def _menu(text, cls=''):
    esc = html.escape
    lis = ''.join(f'<li class="pick">{esc(o[2:])}</li>' if o.startswith('» ') else f'<li>{esc(o)}</li>'
                  for o in text.split(' | '))
    return f'<ul class="menu{cls}">{lis}</ul>'


def _anchor(job, step):
    return f's-{job}-{step}'


OPEN_TARGET = """<script>
function openTarget() {
  var t = document.getElementById(decodeURIComponent(location.hash.slice(1)));
  if (!t) return;
  for (var d = t.closest('details'); d; d = d.parentElement && d.parentElement.closest('details')) d.open = true;
  t.scrollIntoView();
}
addEventListener('hashchange', openTarget);
addEventListener('DOMContentLoaded', openTarget);
addEventListener('DOMContentLoaded', function () {
  var q = document.getElementById('q'), found = document.getElementById('found'), timer;
  if (!q) return;
  var shots = Array.prototype.slice.call(document.querySelectorAll('.shot'));
  var texts = shots.map(function (s) { return s.querySelector('.lines').textContent.toLowerCase(); });
  var jobs = Array.prototype.slice.call(document.querySelectorAll('main > details'));
  function search() {
    var v = q.value.trim().toLowerCase(), hits = 0, per = new Map();
    shots.forEach(function (s, i) {
      var ok = !v || texts[i].indexOf(v) >= 0;
      s.hidden = !ok;
      if (ok && v) { hits++; var d = s.closest('details'); per.set(d, (per.get(d) || 0) + 1); }
    });
    jobs.forEach(function (d) {
      d.hidden = !!v && !per.get(d);
      if (v && per.get(d)) d.open = true;
    });
    found.textContent = v ? hits + ' found' : '';
  }
  q.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(search, 150); });
  var p = new URLSearchParams(location.search).get('q');
  if (p) { q.value = p; search(); }
});
</script>"""


def write_page(dest, shots, title, beside=None, apart=None, choices=False):
    """index.html: jobs as sections; consecutive lines on the same frame share one picture. With ``beside`` (the
    name of the other capture: its language), its lines follow these, its frame follows when it differs. Every step
    has an anchor (#s-<job>-<step>) that opens its section."""
    jobs = collections.OrderedDict()
    for s in shots:
        jobs.setdefault(s['job'], []).append(s)
    esc = html.escape
    parts = [f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
             f'<meta name="viewport" content="width=device-width, initial-scale=1">'
             f'<title>{esc(title)} · renpy-capture</title><style>{PAGE_CSS}</style>{OPEN_TARGET}</head><body>',
             f'<header><h1>{esc(title)}</h1><p>{len(shots)} interactions in {len(jobs)} jobs, '
             f'{len({s["frame"] for s in shots if s["frame"]})} distinct frames'
             + (f'; beside them: {esc(beside)}' if beside else '')
             + ('; <a href="choices.html">the tree of choices</a>' if choices else '') + '</p>'
             '<div class="search"><input id="q" type="search" placeholder="Search: text, speaker, script line, '
             'translation id" aria-label="Search the lines"><span id="found"></span></div></header><main>']
    for job, items in jobs.items():
        label = next((s['label'] for s in items if s['label']), '')
        parts.append(f'<details{" open" if len(jobs) == 1 else ""}><summary>{esc(job)} '
                     f'<small>{esc(label)} · {len(items)} interactions</small></summary>')
        groups, prev, bprev = [], '', ''
        for s in items:
            pair = (s['frame'], s.get('beside_frame', ''))
            if groups and groups[-1][0] == pair and s['frame']:
                groups[-1][1].append(s)
            else:
                groups.append((pair, [s]))
        for (frame, bframe), lines in groups:
            img = (f'<img loading="lazy" src="frames/{frame}.png" alt="">' if frame
                   else '<div class="noimg">no frame (skipped)</div>')
            two = bool(bframe and bframe != frame)          # its own frame (with --text): side by side
            if two:
                img += f'</div><div><img loading="lazy" src="frames/{bframe}.png" alt="">'
            body = []
            for s in lines:
                body.append(f'<a id="{esc(_anchor(job, s["step"]))}"></a>')
                if s['caption'] and s['caption'] != prev:    # the line shown with a menu, unless it was just said
                    body.append(f'<p class="ask">{esc(s["caption"])}</p>')
                if s.get('beside_caption') and s['beside_caption'] != bprev:
                    body.append(f'<p class="ask beside">{esc(s["beside_caption"])}</p>')
                prev, bprev = s['what'] or prev, s.get('beside_what') or bprev
                if apart and apart.get(job) == s['step']:
                    body.append(f'<p class="apart">From here on {esc(beside)} took another way.</p>')
                tl = (f' · {esc(s["tl_file"])}:{s["tl_line"]}' if s['tl_file'] else '') + \
                     (f' · {esc(s["tl"])}' if s['tl'] else '')        # a translator finds the line by its id
                meta = f'<span class="meta">{esc(s["file"])}:{s["line"]} · {esc(s["statement"])}{tl}</span>'
                if s['menu']:
                    body.append(_menu(s['menu']))
                elif s['what'] or s['who']:
                    body.append(_say(s, '') + meta + '</p>')
                else:
                    body.append(f'<p>{meta}</p>')
                if s.get('beside_menu'):
                    body.append(_menu(s['beside_menu'], ' beside'))
                elif s.get('beside_what'):
                    body.append(_say(s, 'beside_', ' class="beside"') + '</p>')
            parts.append(f'<div class="shot{" two" if two else ""}"><div>{img}</div>'
                         f'<div class="lines">{"".join(body)}</div></div>')
        parts.append('</details>')
    parts.append('</main></body></html>')
    with open(os.path.join(dest, 'index.html'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))


def _paths(log):
    """Per job: its family (the id before "~": explore names the jobs it adds after the job they come from), its
    menus in order as (menu shot, the option taken or "timer" when the game's own timer led on, the line before it),
    and how it ended."""
    jobs = collections.OrderedDict()
    for r in log:
        j = r.get('job')
        if j is None:
            continue
        d = jobs.setdefault(j, {'shots': [], 'end': None, 'stop': None})
        if r['ev'] == 'shot':
            d['shots'].append(r)
        elif r['ev'] in ('end', 'stop'):
            d[r['ev']] = r
    for j, d in jobs.items():
        menus, shots = [], d['shots']
        for k, r in enumerate(shots):
            m = r.get('menu')
            if not m:
                continue
            nxt = shots[k + 1] if k + 1 < len(shots) else None
            if m.get('wait'):
                if nxt and (nxt.get('menu') or {}).get('pick') is not None \
                        and (nxt.get('file'), nxt.get('line')) == (r.get('file'), r.get('line')):
                    continue                        # answered after wait_max: the next record is the answer
                pick = 'timer'
            else:
                pick = m.get('pick')
            ask = m.get('caption') or next((p.get('what') for p in reversed(shots[:k]) if p.get('what')), '')
            menus.append((r, pick, ask))
        d['menus'] = menus
        d['family'] = j.split('~')[0]
    return jobs


def write_choices(dest, log, title):
    """choices.html: for every family of jobs, the tree of the menus met and the options taken, each option linked to
    the step of index.html where it was taken, down to where the jobs ended. A run of menus without a branch is one
    line after another; only a branch opens a new level. Returns False when no job met a menu."""
    esc = html.escape
    jobs = _paths(log)
    if not any(d['menus'] for d in jobs.values()):
        return False

    def node():
        return {'edges': collections.OrderedDict(), 'menus': {}, 'first': {}, 'ends': []}

    roots = collections.OrderedDict()
    for j, d in jobs.items():
        n = roots.setdefault(d['family'], node())
        for r, pick, ask in d['menus']:
            place = (script_path(r.get('file')), r.get('line'))
            n['menus'].setdefault(place, (r['menu'].get('options', []), ask))
            key = (place, pick)
            if key not in n['edges']:
                n['edges'][key], n['first'][key] = node(), (j, r['seq'])
            n = n['edges'][key]
        last = d['shots'][-1] if d['shots'] else {}
        why = (d['end'] or {}).get('why') or 'no end'
        if d['stop']:
            why = f"stop ({d['stop'].get('why')}{' ' + d['stop']['label'] if d['stop'].get('label') else ''})"
        n['ends'].append((j, last, why, len(d['shots'])))

    def option(opts, pick):
        return "the game's own timer" if pick == 'timer' else (opts[pick] if isinstance(pick, int) and
                                                               pick < len(opts) else f'option {pick}')

    def menu_head(place, n):
        opts, ask = n['menus'][place]
        return (f'<span class="ask">{esc(ask)}</span> ' if ask else '') + \
            f'<span class="meta">{esc(place[0])}:{place[1]}</span>'

    def link(key, n, text):
        j, seq = n['first'][key]
        return f'<a href="index.html#{esc(_anchor(j, seq))}">{esc(text)}</a>'

    def others(place, n, taken):
        opts = n['menus'][place][0]
        rest = [o for k, o in enumerate(opts) if k not in taken]
        return f' <span class="untaken">(not taken: {esc(" · ".join(rest))})</span>' if rest else ''

    def render(n, out):
        while len(n['edges']) == 1 and not n['ends']:          # no branch: one line, the same level
            (place, pick), child = next(iter(n['edges'].items()))
            opts, times = n['menus'][place][0], 1
            while len(child['edges']) == 1 and not child['ends'] and next(iter(child['edges'])) == (place, pick):
                child, times = next(iter(child['edges'].values())), times + 1    # the same menu again (a mini-game)
            out.append(f'<li>{menu_head(place, n)} → {link((place, pick), n, option(opts, pick))}'
                       f'{f" × {times}" if times > 1 else ""}{others(place, n, {pick})}</li>')
            n = child
        by_place = collections.OrderedDict()
        for (place, pick), child in n['edges'].items():
            by_place.setdefault(place, []).append((pick, child))
        for place, picks in by_place.items():
            opts = n['menus'][place][0]
            out.append(f'<li>{menu_head(place, n)}{others(place, n, {p for p, _ in picks})}<ul>')
            for pick, child in picks:
                out.append(f'<li>→ {link((place, pick), n, option(opts, pick))}<ul>')
                render(child, out)
                out.append('</ul></li>')
            out.append('</ul></li>')
        for j, last, why, steps in n['ends']:
            where = f"{script_path(last.get('file'))}:{last.get('line')}" if last else ''
            out.append(f'<li class="end">■ {esc(why)} · <a href="index.html#{esc(_anchor(j, last.get("seq")))}">'
                       f'{esc(j)}</a> · {steps} steps · {esc(last.get("label") or "")} · {esc(where)}</li>')

    parts = [f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
             f'<meta name="viewport" content="width=device-width, initial-scale=1">'
             f'<title>{esc(title)} · choices · renpy-capture</title><style>{PAGE_CSS}</style></head><body>',
             f'<header><h1>{esc(title)}: the tree of choices</h1><p>Every menu the capture met and the options it '
             f'took; each option opens the step in <a href="index.html">the whole capture</a>.</p></header><main>']
    for fam, root in roots.items():
        members = [j for j, d in jobs.items() if d['family'] == fam]
        places = {(script_path(r.get('file')), r.get('line')) for j in members for r, _p, _a in jobs[j]['menus']}
        parts.append(f'<details{" open" if len(roots) == 1 else ""}><summary>{esc(fam)} <small>{len(members)} jobs · '
                     f'{len(places)} menus</small></summary><div class="tree"><ul>')
        out = []
        render(root, out)
        parts.extend(out)
        parts.append('</ul></div></details>')
    parts.append('</main></body></html>')
    with open(os.path.join(dest, 'choices.html'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))
    return True
