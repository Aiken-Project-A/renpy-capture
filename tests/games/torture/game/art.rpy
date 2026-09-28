# Torture Test — art made entirely in code: Solid, Composite, Text and Transform. No image, font or audio file
# from anywhere else ships with this game.

image bg_indigo = Solid("#241b45")
image bg_amber = Solid("#4a3410")

image box_marker = Solid("#dddddd", xsize=140, ysize=140)
image glow_orb = Composite((160, 160), (0, 0), Solid("#332200", xsize=160, ysize=160),
                            (10, 10), Solid("#ffcc55", xsize=140, ysize=140))
image flourish_mark = Text("*", size=90, color="#ffffff")
image veteran_relic = Solid("#886633", xsize=120, ysize=120)

layeredimage hero:
    attribute calm default:
        Solid("#4a6fa5", xsize=220, ysize=320)
    attribute alert:
        Solid("#a54a4a", xsize=220, ysize=320)
    attribute grin default:
        Text("^_^", size=54, xalign=0.5, yalign=0.15, color="#ffffff")
    attribute frown:
        Text(">_<", size=54, xalign=0.5, yalign=0.15, color="#ffffff")

# A one-shot move: slides in from off-screen and settles; the capture must wait for it to finish.
transform slide_and_settle:
    xalign 0.5 yalign 0.5
    xoffset -500
    ease 0.6 xoffset 0

# An endless animation: pulses forever, so the capture takes it at a fixed phase of the loop.
transform gentle_pulse:
    alpha 1.0
    linear 0.4 alpha 0.55
    linear 0.4 alpha 1.0
    repeat

# The HUD: listed in the config's "ui" so renpy-capture does not draw it or count it as part of the scene.
screen hud():
    text "HP 100 / MP 100" xalign 1.0 yalign 0.02 size 22 color "#ffffff"

# A banner screen that IS part of the scene (not listed in "ui"): it is drawn and counted like any other picture.
screen banner_screen(message):
    frame:
        xalign 0.5 yalign 0.05
        background Solid("#222222cc")
        text message color "#ffffff" size 28

# No visible widgets: only a timer that, in a real playthrough, hands control back to the blocked menu once the
# default has "timed out", by invoking the first option's own action — the same thing choosing it by hand would do.
# renpy-capture always replaces the "choice" screen with an empty one, so a real timeout has to live on a screen of
# its own. Under a capture this timer never actually fires — pygame_sdl2.time.set_timer is stubbed to a no-op under
# the virtual clock (capture.rpy), so "wait_menus" always resolves through its own wait_max fallback instead; the
# scene still settles deterministically, just not through this screen. See the PR description for the repro.
screen countdown_timeout():
    timer 1.0 action Function(_torture_timeout_default)

init python:
    def _torture_timeout_default():
        choice = renpy.get_screen("choice")
        if choice is not None:
            items = [i for i in choice.scope.get("items", []) if getattr(i, "action", None) is not None]
            if items:
                items[0].action()
