## renpy-capture: screenshots of a Ren'Py game taken by the game's own engine. MIT License.
##
## renpy-capture copies this file into the launch folder of a game (never into the game itself). With
## RENPY_CAPTURE_CONFIG set, the engine runs the jobs of that config instead of the main menu.
##
## Every interaction (a line of dialogue, a pause, a menu, a screen) is captured once the scene has settled: at least
## `settle` seconds of game time have passed and nothing asks for a redraw any more (one-shot ATL has finished), but
## no later than `settle_max` (endless animation). Screens whose names match `ui` are not drawn, the dialogue window
## is invisible. The interaction then ends at once: a line moves on, a menu takes the option planned by the job (the
## first one otherwise), a pause counts as expired.
## A job calls a label as a replay (renpy.call_replay: a fresh store from `default` plus the job's variables, its own
## context). A job ends when the label returns, on a jump into a label from `stop_files` or matching `stop_labels`,
## on a script error, after `max_steps` interactions, or when the same line has been captured `loop_limit` times
## (mini-games that go round in circles).
## Output (RENPY_CAPTURE_OUT): frames/<sha1>.png — unique frames; log.jsonl — one record per interaction and per job
## event.
init offset = 999

screen say(who, what):
    text what id "what" size 1 color "#0000" outlines [] xpos -50

screen bubble(who, what):
    text what id "what" size 1 color "#0000" outlines [] xpos -50

screen choice(items):
    null

screen quick_menu():
    null

screen notify(message):
    null

screen skip_indicator():
    null

# "At rest" for still_transforms: an empty ATL transform rather than Transform(). Used as a line inside an ATL block
# (`image x:`, `show x:`) a transform is included, while a displayable becomes a new child: an empty Transform() there
# erased the picture. With `at x` both behave the same.
transform _rc_still:
    pass

init python:
    import os as _rc_os, io as _rc_io, re as _rc_re, json as _rc_json, time as _rc_time
    import hashlib as _rc_hashlib, traceback as _rc_tb
    try:
        import ctypes as _rc_ctypes
    except Exception:
        _rc_ctypes = None

    class _RcState(python_object):
        """The capture's state: a plain object (python_object), outside rollback and saves; works on the Python 2
        of Ren'Py 7 as well, which has no types.SimpleNamespace."""

        def __init__(self, **kw):
            self.__dict__.update(kw)

    def _rc_makedirs(path):
        if not _rc_os.path.isdir(path):
            _rc_os.makedirs(path)

    _rc_P = _RcState(active=False, cfg=None, out=None, log=None, job=None, seq=0, menu_i=0, label=None,
                     pause_delay=None, lines={}, seen=set(), ui=None, skip=[], drop=None, stop=None, settle=1.0,
                     settle_max=1.0, max_steps=3000, loop_limit=40, t0=0.0, where={}, last_key=None,
                     last_frame=None, scene=None, prefer=None, menus_seen={}, cur_node=None, node_t0=0.0,
                     stubs=set(), timers=None, wait=None, wait_node=None, wait_t0=0.0, nulls=set(),
                     stop_labels=None, trans=False, fx_screens=None, fx_files=None, hidden_text={}, dt=0.0,
                     vclock=0.0, cap_anim=False, cap_peak=False, vis_prev=None, hidden_ids=set(), persist0=None,
                     prof=None, raw_seen={}, fast=False)

    def _rc_rx(v):
        return _rc_re.compile(v) if v else None

    def _rc_emit(rec):
        P = _rc_P
        P.log.write(_rc_json.dumps(rec, ensure_ascii=False) + "\n")
        P.log.flush()

    def _rc_is_ui(name):
        return _rc_P.ui is not None and _rc_P.ui.search(name) is not None

    def _rc_screen_name(d):
        n = getattr(d, "screen_name", None)
        return n[0] if n else None

    def _rc_files(ctx):
        """Image files the scene is made of right now: every displayable (visit_all) of the master layer and of the
        shown screens that are not part of the interface."""
        seen = set()

        def cb(d):
            fn = getattr(d, "filename", None)
            if isinstance(fn, str) and isinstance(d, renpy.display.im.Image):
                seen.add(fn)

        for layer in ("master", "screens"):
            for e in ctx.scene_lists.layers.get(layer, []):
                d = e.displayable
                n = _rc_screen_name(d)
                if n is not None and _rc_is_ui(n):
                    continue
                try:
                    d.visit_all(cb)
                except Exception:
                    pass
        return sorted(seen)

    def _rc_shown(ctx):
        rv = []
        hidden = {e.tag for e in ctx.scene_lists.layers.get("master", []) if e.name and e.name[0] in _rc_P.nulls}
        for tag in renpy.get_showing_tags("master", sort=True):
            if tag in hidden:                      # an effect image replaced by an empty one (null_images)
                continue
            try:
                attrs = renpy.get_attributes(tag, "master") or ()
            except Exception:
                attrs = ()
            rv.append(" ".join((tag,) + tuple(attrs)))
        scr = []
        for e in ctx.scene_lists.layers.get("screens", []):
            n = _rc_screen_name(e.displayable)
            if n is not None and not _rc_is_ui(n):
                scr.append(n)
        return rv, scr

    def _rc_node():
        ctx = renpy.game.context()
        try:
            return renpy.game.script.lookup(ctx.current)
        except Exception:
            return None

    def _rc_camstate(ctx):
        """Position of the master layer camera when it is not at rest (a zoom-in, a shift), otherwise None."""
        t = ctx.scene_lists.camera_transform.get("master")
        if t is None:
            return None
        rv = {}
        for k, rest in (("xpos", 0), ("ypos", 0), ("zpos", 0), ("xoffset", 0), ("yoffset", 0), ("zoom", 1),
                        ("xzoom", 1), ("yzoom", 1), ("rotate", 0)):
            try:
                v = getattr(t, k)
            except Exception:
                continue
            if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            if abs(v - rest) > 0.5 if k in ("xpos", "ypos", "zpos", "xoffset", "yoffset", "rotate") else abs(v - rest) > 0.001:
                rv[k] = round(v, 2)
        return rv or None

    def _rc_key(ctx, files):
        """State of the scene without the phase of animations: images of the master layer (tag, name with attributes,
        zorder, where it was shown — file and line of the show), scene screens, image files, camera. The same key
        means the same frame, so an animation does not multiply frames."""
        ents = []
        for e in ctx.scene_lists.layers.get("master", []):
            if e.name and e.name[0] in _rc_P.nulls:
                continue
            ents.append((e.tag, tuple(e.name) if e.name else None, e.zorder, _rc_P.where.get(e.tag)))
        scr = []
        for e in ctx.scene_lists.layers.get("screens", []):
            n = _rc_screen_name(e.displayable)
            if n is not None and not _rc_is_ui(n):
                scr.append((n, _rc_P.where.get(("screen", n))))
        return repr((ents, scr, tuple(files), _rc_camstate(ctx)))

    def _rc_vis(ctx):
        """Visibility of the scene: the sum of the opacities of the shown master-layer images (empty effects
        excluded), down the chain of transforms (the default transform, then the image's ATL). A drop means that
        some layer is fading out."""
        v = 0.0
        for e in ctx.scene_lists.layers.get("master", []):
            if e.name and e.name[0] in _rc_P.nulls:
                continue
            a, d = 1.0, e.displayable
            for _i in range(6):
                if not isinstance(d, renpy.display.transform.Transform):
                    break
                try:
                    x = d.alpha
                    a *= 1.0 if x is None else float(x)
                except Exception:
                    pass
                d = getattr(d, "child", None)
            v += a
        return v

    def _rc_fx(ctx, files):
        """Effects hidden from the frame but running on this line (to overlay them separately later): effect images
        (null_images), effect screens (fx_screens), effect files (fx_files), captions (hide_tags)."""
        P = _rc_P
        rv = [e.name[0] for e in ctx.scene_lists.layers.get("master", []) if e.name and e.name[0] in P.nulls]
        if P.fx_screens is not None:
            for layer in ("screens", "master"):
                for e in ctx.scene_lists.layers.get(layer, []):
                    n = _rc_screen_name(e.displayable)
                    if n is not None and P.fx_screens.search(n):
                        rv.append(n)
        if P.fx_files is not None:
            rv.extend(f for f in files if P.fx_files.search(f))
        rv.extend("text:" + t for t in P.hidden_text.values())
        return sorted(set(rv))

    def _rc_raw_digest(surf):
        """sha1 of a screenshot's pixels, read where pygame_sdl2 keeps them: a picture this engine has already saved
        is recognised before PNG compression, which costs several times more. The same pixels always compress to the
        same PNG, so the frame file stays the same. None when the pixels cannot be read this way: then every picture
        is compressed, as before."""
        if _rc_ctypes is None:
            return None
        try:
            size = surf.get_pitch() * surf.get_height()
            h = _rc_hashlib.sha1((_rc_ctypes.c_char * size).from_address(surf._pixels_address))
            h.update(repr((surf.get_size(), surf.get_pitch(), surf.get_bytesize())).encode("ascii"))
            return h.digest()
        except Exception:
            return None

    def _rc_capture(iface, files=None):
        P = _rc_P
        ctx = renpy.game.context()
        node = _rc_node()
        P.seq += 1
        rec = {"ev": "shot", "job": P.job["id"], "seq": P.seq, "label": P.scene, "at": P.label,
               "kind": type(node).__name__ if node is not None else None,
               "file": getattr(node, "filename", None), "line": getattr(node, "linenumber", None)}
        if isinstance(node, renpy.ast.Say):
            rec["who"] = node.who
            rec["what"] = node.what
            try:                                   # the speaker's name as the player sees it ("Sylvie", not "s")
                ch = renpy.ast.eval_who(node.who, getattr(node, "who_fast", None))
                n = ch if isinstance(ch, str) else getattr(ch, "name", None)    # (str is unicode in Ren'Py 7)
                if n is not None:
                    rec["name"] = renpy.substitute(n) if isinstance(n, str) else str(n)
            except Exception:
                pass
        if P.pause_delay is not None:
            rec["pause"] = P.pause_delay
        stack = []                                 # return points of the calls (lines in the calling labels): a frame
        for name in ctx.return_stack[-6:]:         # shown by a shared procedure can be named after its caller
            try:
                rn = renpy.game.script.lookup(name)
                stack.append([rn.filename, rn.linenumber])
            except Exception:
                pass
        rec["stack"] = stack
        rec["shown"], rec["screens"] = _rc_shown(ctx)
        if files is None:
            files = _rc_files(ctx)
        rec["files"] = files
        fx = _rc_fx(ctx, files)
        if fx:
            rec["fx"] = fx
        if P.cap_anim:
            rec["anim"] = True
        if P.cap_peak:
            rec["peak"] = True
        cam = _rc_camstate(ctx)
        if cam:
            rec["cam"] = cam
        hit = [f for f in files for r in P.skip if r.search(f)]
        key = _rc_key(ctx, files)
        if hit:
            rec["skip"] = hit
            P.last_key = P.last_frame = None
        elif key == P.last_key and P.last_frame:
            rec["frame"] = P.last_frame
            rec["same"] = True
        else:
            pr = P.prof
            t0 = _rc_time.time()
            surf = renpy.display.draw.screenshot(iface.surftree)
            raw = _rc_raw_digest(surf)
            t1 = _rc_time.time()
            h = P.raw_seen.get(raw) if raw is not None else None
            if h is not None:
                pr["known"] += 1                       # these pixels were saved by this engine already: no PNG
            else:
                with _rc_io.BytesIO() as sio:
                    renpy.display.module.save_png(surf, sio, 3)
                    png = sio.getvalue()
                t2 = _rc_time.time()
                h = _rc_hashlib.sha1(png).hexdigest()
                if h not in P.seen:
                    with open(_rc_os.path.join(P.out, "frames", h + ".png"), "wb") as f:
                        f.write(png)
                    P.seen.add(h)
                else:
                    pr["dup"] += 1                     # saved before this engine started (an earlier launch)
                if raw is not None:
                    P.raw_seen[raw] = h
                pr["encoded"] += 1
                pr["png"] += t2 - t1
                pr["save"] += _rc_time.time() - t2
            pr["shots"] += 1
            pr["shot"] += t1 - t0
            rec["frame"] = h
            P.last_key, P.last_frame = key, h

        # How to end the interaction.
        value = True
        choice = renpy.get_screen("choice")
        if choice is not None:
            items = [i for i in choice.scope.get("items", []) if getattr(i, "action", None) is not None]
            plan = P.job.get("choices", [])
            caps = [renpy.substitute(i.caption) for i in items]
            if P.wait is not None and P.wait_node is None and any(P.wait.search(c) for c in caps):
                rec["menu"] = {"n": P.menu_i, "options": caps, "wait": True}   # a timed mini-game menu: no answer,
                P.wait_node, P.wait_t0, P.wait_beat = ctx.current, iface.frame_time, -999   # its timer leads to
                _rc_emit(rec)                                                    # the "too late" outcome by itself
                return
            mkey = (getattr(node, "filename", None), getattr(node, "linenumber", None))
            again = P.menus_seen.get(mkey, 0)
            P.menus_seen[mkey] = again + 1
            if P.menu_i < len(plan):
                k = plan[P.menu_i]
            elif again:                            # the same menu again (a quiz asks again after a wrong answer):
                k = again % max(len(items), 1)     # the next option
            else:                                  # no plan: the option matching `prefer` (skip a mini-game),
                k = next((n for n, c in enumerate(caps) if P.prefer is not None and P.prefer.search(c)), 0)
            k = min(k, len(items) - 1) if items else 0
            rec["menu"] = {"n": P.menu_i, "options": caps, "pick": k}
            P.menu_i += 1
            value = items[k].action() if items else True
        elif renpy.get_screen("input") is not None:
            value = ""
        elif P.pause_delay is not None:
            value = False

        try:                                           # a repeat is the same line from the same call site
            calls = tuple(str(x) for x in ctx.return_stack[-4:])
        except Exception:
            calls = ()
        key = (rec["file"], rec["line"], calls)
        P.lines[key] = P.lines.get(key, 0) + 1
        _rc_emit(rec)
        if P.seq >= P.max_steps:
            _rc_emit({"ev": "stop", "job": P.job["id"], "why": "max_steps"})
            raise renpy.game.EndReplay()
        if P.lines[key] > P.job.get("loop_limit", P.loop_limit):
            _rc_emit({"ev": "stop", "job": P.job["id"], "why": "loop", "file": key[0], "line": key[1]})
            raise renpy.game.EndReplay()
        raise renpy.display.core.EndInteraction(value)

    # The capture happens right after a frame has been drawn (Interface.draw_screen), once the scene has settled.
    _rc_orig_draw = renpy.display.core.Interface.draw_screen

    def _rc_animating():
        """The scene is still moving: something that was drawn asked for a redraw (ATL, animation, movie).
        Requests from hidden screens (interface, effect screens) do not count, they are not visible; neither does
        the camera: we keep it at its final position, and a camera function (parallax following the mouse) asks for
        a frame on every frame."""
        rc = renpy.display.render.render_cache
        hid = set(_rc_P.hidden_ids)
        for t in renpy.game.context().scene_lists.camera_transform.values():
            for _i in range(8):
                if not isinstance(t, renpy.display.transform.Transform):
                    break
                hid.add(id(t))
                t = getattr(t, "child", None)
        return any(id(d) in rc and id(d) not in hid for _when, d in renpy.display.render.redraw_queue)

    def _rc_skip(waiting):
        """Fast mode: the frames a wait would draw are skipped, the clock goes on step by step (the same values as
        drawing them) to the first one that would end the wait; only the frames where a decision is taken are drawn.
        A motion that stops between two such frames is seen later, so the capture is taken later and later animations
        run in another phase than in the exact mode; the scenes are the same."""
        P = _rc_P
        if P.timers or P.wait is not None:            # screen timers tick once per drawn frame: a job that lets them
            return                                    # run (a mini-game, a timed menu) keeps every frame
        for _i in range(100000):
            if not waiting(P.vclock):
                break
            P.vclock += P.dt

    def _rc_draw_screen(self, root_widget, fullscreen_video, draw):
        _rc_P.hidden_ids = set()                      # collected again while hidden screens render
        t = _rc_time.time()
        _rc_orig_draw(self, root_widget, fullscreen_video, draw)
        P = _rc_P
        if P.active:                                  # where the time goes (report prints it): frames drawn while
            P.prof["frames"] += 1                     # a scene settles, and the time drawing them took
            P.prof["draw"] += _rc_time.time() - t
        if P.dt:                                      # frame clock: a frame was drawn, game time moves one step on,
            P.vclock += P.dt                          # plus one PERIODIC event (normally sent by a real timer)
            try:
                import pygame_sdl2 as _rc_pg2
                _rc_pg2.event.post(_rc_pg2.event.Event(renpy.display.core.PERIODIC))
            except Exception:
                pass
        if P.cfg is not None and not getattr(P, "gl_checked", False):   # first frame: no GL (out of video memory,
            P.gl_checked = True                       # too many engines starting at once) — software rendering is
            if (getattr(renpy.display.draw, "info", None) or {}).get("renderer") == "sw":   # not captured; quit,
                with open(_rc_os.path.join(P.out, "fatal.txt"), "w", encoding="utf-8") as f:   # the job is retried
                    f.write("no GL: software renderer\n")
                raise renpy.game.QuitException()
        if not P.active:
            return
        cur = renpy.game.context().current            # time is counted from the start of the statement, not of the
        if P.wait_node is not None:                   # interaction: waiting on a menu (wait_menus) until its timer
            if cur == P.wait_node:                    # leads the game on
                el = self.frame_time - P.wait_t0      # a screen timer ticks once per frame and restarts the
                if el - getattr(P, "wait_beat", -999) >= 60:   # interaction each time; a long wait writes a pulse to
                    P.wait_beat = el                  # the log, otherwise the stall watchdog would end the job
                    _rc_emit({"ev": "wait", "job": P.job["id"], "t": round(el, 1)})
                if el < P.job.get("wait_max", 600):
                    self.force_redraw = True
                    return
                P.wait = None                         # the timer never came: answer menus as usual from now on
            P.wait_node = None
        if cur != P.cur_node:                         # screen timers (SetVariable) restart the interaction every
            P.cur_node, P.node_t0 = cur, self.frame_time   # 0.05 s
            P.vis_prev = None
        start = P.node_t0
        if P.trans:                                   # transitions (with dissolve…): capture once the transition
            tt = [v for v in (self.transition_time or {}).values() if v is not None]   # is over; phases an author
            delay = max([getattr(v, "delay", 0) or 0 for v in (getattr(self, "instantiated_transition", None)
                                                              or {}).values()]      # shows through a chain of
                        + [v or 0 for v in (getattr(self, "transition_delay", None) or {}).values()] + [0])   # show …
            tmax = P.job.get("trans_max", P.cfg.get("trans_max", 8))
            if tt and delay and self.frame_time - min(tt) < delay and \
                    self.frame_time - start < tmax:                                              # with become
                self.force_redraw = True                                                         # frames, not a
                if P.fast:                                                                       # blend of two
                    t0 = min(tt)
                    _rc_skip(lambda t: t - t0 < delay and t - start < tmax)
                return
        if P.cfg.get("early", True) and P.last_frame and not _rc_animating():
            ctx = renpy.game.context()                # the scene is made of the same things as at the last capture
            files = _rc_files(ctx)                    # and nothing moves: the frame is the same, capture at once
            if _rc_key(ctx, files) == P.last_key:     # without waiting for `settle` (most lines do not change the
                P.cur_node = None                     # picture)
                P.cap_anim = P.cap_peak = False
                _rc_capture(self, files)
                return
        need, most = P.settle, P.settle_max
        if P.pause_delay is not None and P.pause_delay > 0:
            need, most = min(need, P.pause_delay * 0.8), min(most, P.pause_delay * 0.8)
        elapsed = self.frame_time - start
        moving = _rc_animating()
        if moving and P.cfg.get("peak", True):        # a layer began to fade out (a spark, smoke): capture now, at
            vis = _rc_vis(renpy.game.context())       # its peak, otherwise the settled frame would not show it
            if P.vis_prev is not None and vis < P.vis_prev - 0.02:
                P.cur_node, P.vis_prev = None, None
                P.cap_anim = P.cap_peak = True
                _rc_capture(self)
                return
            P.vis_prev = vis
        if elapsed < need or (elapsed < most and moving):
            self.force_redraw = True                 # a one-shot ATL effect (a two-second fade) is still running —
            if P.fast:                               # wait; an endless one (shaking, blinking) — until settle_max
                wait = need if elapsed < need else most
                _rc_skip(lambda t: t - start < wait)
            return
        P.cur_node = None
        P.cap_anim = moving                          # captured in the middle of an endless animation (the phase is
        P.cap_peak = False                           # fixed by the frame clock)
        _rc_capture(self)

    renpy.display.core.Interface.draw_screen = _rc_draw_screen

    # Interface screens are not drawn (their logic stays alive: scope, widgets, actions).
    _rc_orig_screen_render = renpy.display.screen.ScreenDisplayable.render

    def _rc_screen_render(self, w, h, st, at):
        rv = _rc_orig_screen_render(self, w, h, st, at)
        if _rc_P.active and _rc_is_ui(self.screen_name[0]):
            ids = _rc_P.hidden_ids
            try:
                self.visit_all(lambda d: ids.add(id(d)))
            except Exception:
                pass
            return renpy.display.render.Render(w, h)
        return rv

    renpy.display.screen.ScreenDisplayable.render = _rc_screen_render

    # …and they get no events, so their timers stand still (mini-game gauges do not drain, timeouts do not fire).
    # A job with ui_timers lets time run (to capture the "too late" outcome of a mini-game): True for every interface
    # screen, a regex for the matching ones. Stub screens always work.
    _rc_orig_screen_event = renpy.display.screen.ScreenDisplayable.event

    def _rc_screen_event(self, ev, x, y, st):
        P = _rc_P
        n = self.screen_name[0]
        if P.active and _rc_is_ui(n) and n not in P.stubs and not (P.timers is True or (P.timers and P.timers.search(n))):
            return None
        return _rc_orig_screen_event(self, ev, x, y, st)

    renpy.display.screen.ScreenDisplayable.event = _rc_screen_event

    # Layers left out (drop): the image file is drawn fully transparent at the same size.
    _rc_orig_im_load = renpy.display.im.Image.load

    def _rc_im_load(self, unscaled=False):
        surf = _rc_orig_im_load(self, unscaled)
        if _rc_P.drop is not None and _rc_P.drop.search(self.filename):
            return renpy.display.pgrender.surface(surf.get_size(), True)
        return surf

    renpy.display.im.Image.load = _rc_im_load

    # The length of a pause, to capture it before it ends by itself.
    _rc_orig_pause = renpy.exports.pause

    def _rc_pause(delay=None, *args, **kwargs):
        _rc_P.pause_delay = delay
        try:
            if _rc_P.active and isinstance(delay, (int, float)) and not isinstance(delay, bool) and delay > 0:
                # the pause does not end by itself, the capture ends it (EndInteraction): under load frames are
                # drawn less often, and a short pause used to expire between two frames — the picture shown only
                # during that pause was lost
                return _rc_orig_pause(None, *args, **kwargs)
            return _rc_orig_pause(delay, *args, **kwargs)
        finally:
            _rc_P.pause_delay = None

    renpy.exports.pause = _rc_pause

    # Camera moves (the camera statement with an ATL block) jump to their final position: that is what the reader
    # sees once the move is over, and an unfinished move of the previous scene (the capture is faster than a player)
    # does not leak into the next one ("ease 2 xoffset 250 … ease 1 xoffset 0" used to leave a shift and a black
    # band). The camera ATL is run to its end once, from the state of the previous camera (Ren'Py inherits it the
    # same way), and replaced by a still Transform with all the final properties (the transform's arguments are
    # applied over the inherited state on every frame). Images are not fast-forwarded like this: the end of a splash
    # or a tongue is off-screen or transparent.
    _rc_orig_camera_execute = renpy.ast.Camera.execute

    _rc_rep = {}

    def _rc_repeats(raw):
        """Whether an ATL block has a repeat (such a block cannot be fast-forwarded: a loop has no end)."""
        k = id(raw)
        if k not in _rc_rep:
            rv, stack = False, [raw]
            while stack and not rv:
                x = stack.pop()
                if isinstance(x, renpy.atl.RawRepeat):
                    rv = True
                stack.extend(getattr(x, "statements", None) or [])
                stack.extend(getattr(x, "blocks", None) or [])
                stack.extend(getattr(x, "children", None) or [])
                stack.extend(b for _c, b in (getattr(x, "choices", None) or []))
                stack.extend((getattr(x, "handlers", None) or {}).values())
            _rc_rep[k] = rv
        return _rc_rep[k]

    def _rc_camera_execute(self):
        P = _rc_P
        if not (P.active and self.atl is not None and P.cfg is not None and P.cfg.get("instant_camera", True)
                and not _rc_repeats(self.atl)):
            return _rc_orig_camera_execute(self)
        renpy.ast.next_node(self.next)
        renpy.ast.statement_name("show layer")
        at_list = [renpy.python.py_eval(i) for i in self.at_list]
        atl = renpy.display.motion.ATLTransform(self.atl)
        old = renpy.game.context().scene_lists.camera_transform.get(self.layer)
        if old is not None:
            atl.take_state(old)
        atl.atl_st_offset = 0
        atl.execute(atl, 100000.0, 100000.0)
        props = {k: getattr(atl.state, k) for k in renpy.display.transform.all_properties if hasattr(atl.state, k)}
        at_list.append(renpy.display.motion.Transform(**props))
        renpy.exports.layer_at_list(at_list, layer=self.layer, camera=True)

    renpy.ast.Camera.execute = _rc_camera_execute

    # The same for the pause timer inside a line ({nw=0.3}) and the pause of an interaction: time does not end it,
    # the capture does. A zero delay ({nw} without a number, pause 0) behaves as the author wrote it: on at once.
    _rc_orig_pause_event = renpy.display.behavior.PauseBehavior.event

    def _rc_pause_event(self, ev, x, y, st):
        if _rc_P.active and ev.type == renpy.display.core.TIMEEVENT and (self.delay or 0) > 0:
            return None
        return _rc_orig_pause_event(self, ev, x, y, st)

    renpy.display.behavior.PauseBehavior.event = _rc_pause_event

    def _rc_here():
        n = _rc_node()
        return (getattr(n, "filename", None), getattr(n, "linenumber", None))

    _rc_orig_show = renpy.exports.show

    def _rc_show(name, *args, **kwargs):
        if _rc_P.active:
            nm = tuple(name.split()) if isinstance(name, str) else tuple(name)
            _rc_P.where[kwargs.get("tag") or nm[0]] = _rc_here()
        return _rc_orig_show(name, *args, **kwargs)

    renpy.exports.show = _rc_show
    _rc_orig_cfg_show = config.show                     # the show statement calls config.show (a reference to the
                                                        # original function)
    def _rc_cfg_show(name, *args, **kwargs):
        if _rc_P.active:
            nm = tuple(name.split()) if isinstance(name, str) else tuple(name)
            _rc_P.where[kwargs.get("tag") or nm[0]] = _rc_here()
        return _rc_orig_cfg_show(name, *args, **kwargs)

    config.show = _rc_cfg_show

    _rc_orig_scene = renpy.exports.scene

    def _rc_scene(layer="master"):
        if _rc_P.active and layer == "master":
            _rc_P.where = {k: v for k, v in _rc_P.where.items() if isinstance(k, tuple)}
            _rc_P.hidden_text.clear()
        return _rc_orig_scene(layer)

    renpy.exports.scene = _rc_scene
    _rc_orig_cfg_scene = config.scene

    def _rc_cfg_scene(layer="master"):
        if _rc_P.active and layer == "master":
            _rc_P.where = {k: v for k, v in _rc_P.where.items() if isinstance(k, tuple)}
            _rc_P.hidden_text.clear()
        return _rc_orig_cfg_scene(layer)

    config.scene = _rc_cfg_scene

    _rc_orig_show_screen = renpy.exports.show_screen

    def _rc_show_screen(_screen_name, *args, **kwargs):
        if _rc_P.active:
            _rc_P.where[("screen", _screen_name)] = _rc_here()
        return _rc_orig_show_screen(_screen_name, *args, **kwargs)

    renpy.exports.show_screen = _rc_show_screen

    def _rc_pulse():
        """A pulse every 2 s with what is running right now (to diagnose hangs): pulse.json in the output."""
        P = _rc_P
        now = _rc_time.time()
        if P.out is None or now - getattr(P, "pulse_t", 0) < 2.0:
            return
        P.pulse_t = now
        n = _rc_node()
        iface = renpy.game.interface
        info = {"t": round(now, 1), "active": P.active, "job": (P.job or {}).get("id"), "seq": P.seq,
                "label": P.label, "node": [getattr(n, "filename", None), getattr(n, "linenumber", None),
                                           type(n).__name__ if n is not None else None],
                "pause": P.pause_delay, "interact_time": iface.interact_time, "frame_time": iface.frame_time,
                "screens": [_rc_screen_name(e.displayable) for e in
                            renpy.game.context().scene_lists.layers.get("screens", [])]}
        try:
            with open(_rc_os.path.join(P.out, "pulse.json"), "w", encoding="utf-8") as f:
                f.write(_rc_json.dumps(info, ensure_ascii=False, default=str))
        except Exception:
            pass

    config.periodic_callbacks.append(_rc_pulse)

    def _rc_label_cb(name, abnormal):
        P = _rc_P
        P.label = name
        if not name.startswith("_"):
            P.scene = name
        if not P.active:
            return
        if P.stop_labels is not None and name != P.job.get("label") and name not in P.job.get("allow", ()) \
                and P.stop_labels.search(name):            # a hub label (a map, a corridor): the scene is over
            _rc_emit({"ev": "stop", "job": P.job["id"], "why": "label", "label": name})
            raise renpy.game.EndReplay()
        if P.stop is None:
            return
        node = renpy.game.script.namemap.get(name)
        fn = getattr(node, "filename", "") or ""
        if P.stop.search(fn) and name not in P.job.get("allow", ()):
            _rc_emit({"ev": "stop", "job": P.job["id"], "why": "label", "label": name, "file": fn})
            raise renpy.game.EndReplay()

    config.label_callbacks.append(_rc_label_cb)

    def _rc_exception(short, full, traceback_fn):
        P = _rc_P
        if P.cfg is None:
            return False
        if not P.active:                               # outside a job the error screen would wait forever — quit
            with open(_rc_os.path.join(P.out, "fatal.txt"), "w", encoding="utf-8") as f:
                f.write(full)
            raise renpy.game.QuitException()
        # A typo of the author (`with disslove`): a player presses "Ignore" and the game goes on; so does the capture,
        # but only for errors matching ignore_errors (a regex on the text). True: the engine takes the next statement
        # (next_node was set before the error).
        if P.cfg.get("ignore_errors") and _rc_re.search(P.cfg["ignore_errors"], full):
            _rc_emit({"ev": "error", "job": P.job["id"], "seq": P.seq, "label": P.label, "ignored": True,
                      "error": full[-4000:]})
            return True
        _rc_emit({"ev": "error", "job": P.job["id"], "seq": P.seq, "label": P.label, "error": full[-4000:]})
        raise renpy.game.EndReplay()

    config.exception_handler = _rc_exception

    def _rc_stub(value):
        def screen(**kwargs):
            renpy.ui.timer(0.05, action=Return(value))
        return screen

    def _rc_run_all():
        P = _rc_P
        cfg = P.cfg
        _rc_makedirs(_rc_os.path.join(P.out, "frames"))
        for f in _rc_os.listdir(_rc_os.path.join(P.out, "frames")):
            P.seen.add(f[:-4])
        P.log = open(_rc_os.path.join(P.out, "log.jsonl"), "a", encoding="utf-8")
        P.ui = _rc_rx(cfg.get("ui"))
        P.skip = [_rc_re.compile(r) for r in cfg.get("skip", [])]
        P.drop = _rc_rx(cfg.get("drop"))
        P.stop = _rc_rx(cfg.get("stop_files"))
        P.stop_labels = _rc_rx(cfg.get("stop_labels"))
        P.fast = bool(cfg.get("fast") or _rc_os.environ.get("RENPY_CAPTURE_FAST") == "1") and bool(P.dt)   # (--fast)
        P.settle = cfg.get("settle", 1.0)
        P.settle_max = max(P.settle, cfg.get("settle_max", P.settle))
        P.max_steps = cfg.get("max_steps", 3000)
        P.loop_limit = cfg.get("loop_limit", 40)
        P.prefer = _rc_rx(cfg.get("prefer"))
        P.fx_screens = _rc_rx(cfg.get("fx_screens"))   # what of the hidden things to log as the line's effects
        P.fx_files = _rc_rx(cfg.get("fx_files"))
        for name, value in cfg.get("stub_screens", {}).items():   # mini-games: the screen returns "success" at once
            renpy.display.screen.define_screen(name, _rc_stub(value), modal="True")
            P.stubs.add(name)
        import copy as _rc_copy                         # jobs of one launch see no traces of each other:
        if getattr(P, "set_timer", None) is not None:   # timers created before our replacement (PERIODIC, when the
            for _rc_ev in (renpy.display.core.PERIODIC, renpy.display.core.REDRAW, renpy.display.core.TIMEEVENT):
                P.set_timer(_rc_ev, 0)                  # interface was created) are switched off with the real one
        P.persist0 = _rc_copy.deepcopy(vars(persistent))   # persistent data (seen flags, gallery) as at the start
        P.old_scene0 = dict(renpy.game.interface.old_scene)   # the old screen for the first transition, as at start
        done = set()
        dpath = _rc_os.path.join(P.out, "done.txt")
        if _rc_os.path.exists(dpath):
            done = set(open(dpath, encoding="utf-8").read().split())
        for job in cfg["jobs"]:
            if job["id"] in done:
                continue
            P.job, P.seq, P.menu_i, P.lines, P.label, P.scene = job, 0, 0, {}, None, None
            P.where, P.last_key, P.last_frame, P.menus_seen = {}, None, None, {}
            P.hidden_text = {}
            _rc_pd = vars(persistent)
            _rc_pd.clear()
            _rc_pd.update(_rc_copy.deepcopy(P.persist0))
            import random as _rc_random, zlib as _rc_zlib   # the game's randomness (mini-game targets, random
            _rc_seed = _rc_zlib.crc32(job["id"].encode("utf-8"))   # choices) is the same in every run: seeded
            renpy.random.seed(_rc_seed)                 # from the job's id
            _rc_random.seed(_rc_seed)
            renpy.game.interface.old_scene = dict(P.old_scene0)   # as in a fresh engine: enter_context does not
                                                        # reset it, and the frame of the previous job leaked (an empty
                                                        # one loses the first transition: Ren'Py skips it)
            t = job.get("ui_timers")                   # True: every interface screen; a string: the matching ones
            P.timers = _rc_re.compile(t) if isinstance(t, str) else bool(t)
            P.wait, P.wait_node = _rc_rx(job.get("wait_menus")), None
            P.prof = {"frames": 0, "draw": 0.0, "shots": 0, "shot": 0.0, "known": 0, "encoded": 0, "dup": 0,
                      "png": 0.0, "save": 0.0}
            P.t0 = _rc_time.time()
            _rc_emit({"ev": "start", "job": job["id"], "label": job["label"]})
            P.active = True
            try:
                renpy.call_replay("_rc_job", scope=dict(job.get("scope", {})))
                why = "end"
            except renpy.game.QuitException:
                raise                                  # no GL (first-frame check): no "end", the job is retried
            except renpy.game.FullRestartException:
                why = "restart"                        # the game went back to its main menu: the story is over
            except Exception as e:
                tb = _rc_tb.format_exc()
                if "Invalid window" in tb:             # the window was not created (video memory): the same
                    with open(_rc_os.path.join(P.out, "fatal.txt"), "w", encoding="utf-8") as f:
                        f.write(tb)
                    raise renpy.game.QuitException()
                why = "exception: " + repr(e)
                _rc_emit({"ev": "error", "job": job["id"], "error": tb[-4000:]})
            finally:
                P.active = False
            _rc_emit({"ev": "end", "job": job["id"], "steps": P.seq, "why": why,
                      "seconds": round(_rc_time.time() - P.t0, 1),
                      "prof": dict((k, round(v, 3)) for k, v in P.prof.items())})
            with open(dpath, "a", encoding="utf-8") as f:
                f.write(job["id"] + "\n")
        P.log.close()

    if _rc_os.environ.get("RENPY_CAPTURE_CONFIG"):
        _rc_P.cfg = _rc_json.load(open(_rc_os.environ["RENPY_CAPTURE_CONFIG"], encoding="utf-8"))
        _rc_P.out = _rc_os.environ["RENPY_CAPTURE_OUT"]
        config.label_overrides["start"] = "_rc_driver"
        renpy.game.preferences.physical_size = None
        renpy.game.preferences.fullscreen = False
        _rc_P.trans = bool(_rc_P.cfg.get("transitions"))   # transitions: capture after the end of every `with`
        renpy.game.preferences.transitions = 2 if _rc_P.trans else 0
        renpy.game.preferences.text_cps = 0
        renpy.game.preferences.afm_enable = False
        # Frame clock (virtual_clock): game time is a frame counter, every drawn frame moves it by dt = timewarp/60 s.
        # The engine does not wait for real time (without power saving the loop does not block and draws one frame
        # after another, vsync is off), and an endless animation is always in the same phase when captured, so runs
        # are identical.
        if _rc_P.cfg.get("virtual_clock", True):
            _rc_P.dt = float(_rc_os.environ.get("RENPY_TIMEWARP") or 1) / 60.0
            _rc_P.vclock = renpy.display.core.get_time()
            renpy.display.core.get_time = lambda: _rc_P.vclock
            renpy.game.preferences.gl_powersave = False
            # real pygame timers (TIMEEVENT and REDRAW in real milliseconds, PERIODIC every 50 ms) are silenced: their
            # events arrived in a random frame and moved the tick of a mini-game's screen timer, so runs differed.
            # Ren'Py sends TIMEEVENT itself when the game clock reaches the deadline; PERIODIC is posted once per frame
            import pygame_sdl2 as _rc_pg
            _rc_P.set_timer = _rc_pg.time.set_timer
            _rc_pg.time.set_timer = lambda *a, **k: None
        config.performance_test = False            # no "performance" screen: without GL we quit by ourselves
        for _k, _v in _rc_P.cfg.get("persistent", {}).items():
            setattr(persistent, _k, _v)
        # A clean frame: effect images (fades, flashes, noise, spirals) become empty; transforms of endless
        # animation (shaking, pulsing, swaying) rest, the layer stands as drawn. Done here, at init offset 999, after
        # the game's own definitions, including images and transforms defined inside labels.
        for _k in _rc_P.cfg.get("null_images", []):
            if _k == "text":                         # `show text "…"` is an image with a parameter: invisible text
                renpy.image(_k, ParameterizedText(style="default", color="#0000", outlines=[], drop_shadow=None))
            else:
                renpy.image(_k, Null())
        _rc_P.nulls = set(_rc_P.cfg.get("null_images", []))
        # Tags that are not shown at all (hide_tags): captions over the scene — `show text …`,
        # `show expression Text(…) as text`, flying words on the screens layer; the show statement goes through
        # config.show
        _rc_P.hide_tags = _rc_rx(_rc_P.cfg.get("hide_tags"))
        if _rc_P.hide_tags is not None:
            _rc_orig_show = config.show

            def _rc_text_of(name, what):
                """The words of a caption: the image parameter of `show text "…"`, the text of `show expression
                Text(…)`."""
                try:
                    if what is not None and hasattr(what, "text"):
                        return "".join(x for x in what.text if isinstance(x, str))
                    if isinstance(name, tuple) and len(name) > 1:
                        return " ".join(str(x) for x in name[1:]).strip('"')
                except Exception:
                    pass
                return str(name)

            def _rc_show(name, *args, **kwargs):
                tag = kwargs.get("tag") or (name[0] if isinstance(name, tuple) and name else str(name).split()[0])
                if _rc_P.hide_tags.search(str(tag)):
                    if _rc_P.active:                   # not drawn, but logged as an effect of the line (fx)
                        _rc_P.hidden_text[str(tag)] = _rc_text_of(name, kwargs.get("what"))
                    return
                return _rc_orig_show(name, *args, **kwargs)

            config.show = _rc_show
            _rc_orig_hide = config.hide

            def _rc_hide(name, *args, **kwargs):
                tag = name[0] if isinstance(name, tuple) and name else str(name).split()[0]
                _rc_P.hidden_text.pop(str(tag), None)
                return _rc_orig_hide(name, *args, **kwargs)

            config.hide = _rc_hide
        # At rest means the first frame of the animation: the leading instant lines of its ATL (up to the first one
        # that takes time). For a typical shake that is "xoffset 0 yoffset 0" — the game puts the sprite back in
        # place, while an empty rest froze the middle of the previous shake. Without such lines (the shake starts
        # with ease) or without ATL (a transform class) it is the empty _rc_still.
        def _rc_still_of(t):
            atl = getattr(t, "atl", None)
            if not isinstance(atl, renpy.atl.RawBlock):
                return _rc_still
            pre = []
            for st in atl.statements:
                if not (isinstance(st, renpy.atl.RawMultipurpose) and st.warper is None and st.properties
                        and not st.expressions and not st.splines and st.revolution is None):
                    break
                pre.append(st)
            if not pre:
                return _rc_still
            ctx = getattr(t, "context", None)            # a ready transform keeps an atl.Context around a dict
            ctx = dict(getattr(ctx, "context", None) or {})
            return renpy.display.motion.ATLTransform(renpy.atl.RawBlock(atl.loc, pre, False), context=ctx,
                                                     parameters=getattr(t, "parameters", None))

        for _k in _rc_P.cfg.get("still_transforms", []):
            if hasattr(store, _k):
                setattr(store, _k, _rc_still_of(getattr(store, _k)))
        # map and navigation screens (null_screens): they are not drawn anyway, and their logic fails without the
        # state of earlier scenes (scrolling driven by map variables) — they become empty
        _rc_ns = _rc_rx(_rc_P.cfg.get("null_screens"))
        if _rc_ns is not None:
            for _rc_sn, _rc_sv in list(renpy.display.screen.screens):
                if _rc_ns.search(_rc_sn):
                    renpy.display.screen.define_screen(_rc_sn, lambda **kw: None, variant=_rc_sv)
        # colour-matrix glitches (InvertMatrix: a negative for half a second) become the identity: the layer keeps
        # its colours
        for _k in _rc_P.cfg.get("neutral_matrices", []):
            if hasattr(store, _k):
                setattr(store, _k, lambda *a, **kw: IdentityMatrix())

label _rc_job:
    if not _rc_P.job.get("replay"):             # an event as in a normal game; a replay from the gallery ends
        $ _in_replay = None                     # by itself with renpy.end_replay()
    python:
        for _k, _v in _rc_P.job.get("scope", {}).items():
            setattr(store, _k, _v)
        # the camera as the game itself sets it before the scene (cfg camera: the name of a transform, or its
        # properties, e.g. perspective True): without perspective, layers with a 3D rotation (xrotate/yrotate)
        # move beyond |z| > 1 and get clipped
        _rc_cam = _rc_P.job.get("camera", _rc_P.cfg.get("camera"))
        if _rc_cam and isinstance(_rc_cam, str):    # the name of a transform of the game
            renpy.show_layer_at([getattr(store, _rc_cam)], camera=True)
        elif _rc_cam:                               # properties (`camera: perspective True` in start); a dict in
            renpy.show_layer_at([Transform(**_rc_cam)], camera=True)   # the store is a RevertableDict
        # the background of a hub (the job's scene): a scene on a map (a Call from a map button) goes over the
        # background the hub has set; the job starts past the hub, and without this the sprites would stand on
        # nothing
        if _rc_P.job.get("scene"):
            renpy.scene()
            renpy.show(_rc_P.job["scene"])
        # prelude labels: what the game does at start before the scene — variables not set by `default`
        _rc_pre = list(_rc_P.job.get("prelude", _rc_P.cfg.get("prelude", [])))
    while _rc_pre:
        $ _rc_pl = _rc_pre.pop(0)
        call expression _rc_pl
    call expression _rc_P.job["label"]
    return

label _rc_driver:
    $ config.label_overrides.pop("start", None)    # the override was only needed to get in; jobs call the real start
    $ _rc_run_all()
    $ renpy.quit()
