# Torture Test — an original sample game for renpy-capture's end-to-end tests, covering features "The Question"
# (the Ren'Py SDK's own sample game) does not exercise: nested and gated menus, a quiz that retries, timed events,
# NVL mode with a menu on its page, a layered sprite, ATL (one-shot and endless), transitions, screens, a shared procedure, randomness, a
# full restart, and scenes that change without a new statement on the line. Every line is original English text;
# every picture is made in code (see art.rpy).

define narrator_ivy = Character("Ivy", kind=nvl)
define pip = Character("Pip", color="#ffdd66")
define quinn = Character("Quinn", color="#88ddff", ctc="quinn_ctc", ctc_position="nestled")   # a blinking click-to-continue

default found_key = False
default veteran_mode = False
default timeout_choice = None

label start:
    show screen hud
    "Welcome to the Torture Test, a small game made only to be captured."
    menu:
        "Menus":
            call menus_scene
        "Timing":
            call timing_scene
        "NVL dialogue":
            call nvl_scene
        "Layered sprite":
            call layered_scene
        "ATL animation":
            call atl_scene
        "Transitions":
            call transitions_scene
        "Custom screen":
            call customscreen_scene
        "Random event":
            call random_scene
        "Same line, new picture":
            call changes_scene
        "The ending":
            call ending_scene
    hide screen hud
    return


label menus_scene:
    "You step into a small chamber with three doors."
    menu:
        "Search the room for a hidden key":
            $ found_key = True
            "Your fingers close around a small brass key."
        "Ignore the room and move on":
            "You decide not to waste time searching."
    menu:
        "Use the brass key on the locked chest" if found_key:
            show flourish_mark at truecenter
            "The chest creaks open, revealing a dusty note inside."
            hide flourish_mark
        "Consult the veteran's logbook" if veteran_mode:
            show veteran_relic at truecenter
            "The logbook lists every trap in this dungeon, held down by a small brass relic."
            hide veteran_relic
        "Try the middle door":
            menu:
                "Push it open":
                    "Beyond it, a narrow stairway spirals down into the dark."
                "Knock first":
                    "No one answers, so you push the door open yourself."
        "Try the left door":
            "It is bricked shut; there is nothing more to see here."
    label menus_quiz:
        "A riddle is carved into the wall: what has keys but cannot open a single lock?"
        menu:
            "A piano":
                "The wall rumbles in approval. You solved the riddle."
            "A treasure chest":
                "Nothing happens. That answer is wrong."
                jump menus_quiz
    return


label timing_scene:
    "Time moves strangely in this place."
    $ renpy.pause(1.0)
    "The room was silent for exactly one second."
    pip "Give me a moment{w=0.5} to think it over{nw}"
    extend " ...there, I have decided."
    call shared_flourish
    "A soft chime plays as the flourish settles."
    show screen countdown_timeout
    menu:
        "A gate begins to close. Choose fast!"
        "Quick, pull the left lever":
            $ timeout_choice = "left"
        "Quick, pull the right lever":
            $ timeout_choice = "right"
    hide screen countdown_timeout
    if timeout_choice == "left":
        "The left lever grinds and the gate slides open."
    else:
        "The right lever was the one that mattered all along."
    return


label nvl_scene:
    nvl clear
    narrator_ivy "Let me tell you something in a different mode entirely."
    narrator_ivy "Here, every line stays on the page instead of replacing the one before it."
    "This particular line has no speaker at all, only the page itself."
    menu (nvl=True):
        "Turn the page":
            narrator_ivy "The next page is blank, waiting for ink."
        "Close the book":
            narrator_ivy "The cover shuts with a soft thump."
    nvl clear
    return


label layered_scene:
    show hero calm grin at truecenter
    quinn "Here I am, feeling perfectly calm."
    show hero alert frown
    quinn "Wait — did you hear that?"
    show hero calm grin
    quinn "Never mind. All clear again."
    hide hero
    return


label atl_scene:
    show box_marker at slide_and_settle
    "A marker slides into place and comes to rest."
    show glow_orb at gentle_pulse
    "Nearby, a soft light pulses without end."
    call shared_flourish
    "The flourish returns here, shared with the transitions scene."
    hide box_marker
    hide glow_orb
    return


label transitions_scene:
    scene bg_indigo
    with dissolve
    "The room dissolves into a deep indigo glow."
    scene bg_amber
    with fade
    "Everything fades to black, then rises again in warm amber light."
    call shared_flourish
    "The flourish appears here too, shared with the ATL scene."
    scene black
    return


label customscreen_scene:
    show screen banner_screen("A banner appears on screen.")
    "This banner is part of the scene, not the interface."
    hide screen banner_screen
    return


label random_scene:
    $ torture_pick = renpy.random.randint(0, 2)
    if torture_pick == 0:
        "A merchant offers a strange trinket."
    elif torture_pick == 1:
        "A wandering cat crosses your path."
    else:
        "A distant bell tolls three times."
    return


label ending_scene:
    "The story loops back on itself, as every good torture test should."
    $ renpy.full_restart()


label shared_flourish:
    show flourish_mark at truecenter
    "A shimmering flourish briefly lights the air."
    hide flourish_mark
    return


# A scene can change while the statements that make it stay the same: one show line run with other arguments, a
# screen whose text follows a variable, a caption the config hides whether a statement or Python code shows it.
label changes_scene:
    $ torture_step = 0
    while torture_step < 3:
        show box_marker at Position(xpos=120 + torture_step * 260, ypos=330)
        "The marker hops to its next spot."
        $ torture_step += 1
    hide box_marker
    $ torture_tally = 1
    show screen tally_screen
    "The tally on the wall reads one."
    $ torture_tally = 2
    "The tally on the wall now reads two."
    "Nothing changes; the tally stays at two."
    hide screen tally_screen
    "The wall is bare again."
    show caption_card
    "A caption hangs here, but the config hides it."
    hide caption_card
    $ renpy.show("caption_card")
    "The same caption, shown from Python this time."
    $ renpy.hide("caption_card")
    return
