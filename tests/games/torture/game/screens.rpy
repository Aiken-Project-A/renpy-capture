# The window a line is said in, the buttons of a menu and the page of NVL mode, as a game made from the Ren'Py template
# defines them. A capture replaces them with invisible stand-ins, and draws them with `text`.

screen say(who, what):
    window:
        id "window"
        xfill True
        ysize 200
        yalign 1.0
        background Solid("#000000b0")
        padding (60, 24)
        if who is not None:
            text who id "who" color "#ffdd66" size 30
        text what id "what" ypos 44 size 28 color "#ffffff"

screen choice(items):
    vbox:
        xalign 0.5
        yalign 0.45
        spacing 12
        for i in items:
            textbutton i.caption action i.action

screen nvl(dialogue, items=None):
    window:
        xfill True
        yfill True
        background Solid("#000000c0")
        padding (40, 30)
        vbox:
            spacing 12
            for d in dialogue:
                window:
                    id d.window_id
                    background None
                    hbox:
                        spacing 16
                        if d.who is not None:
                            text d.who id d.who_id color "#ffdd66" size 24
                        text d.what id d.what_id size 24 color "#ffffff"
            if items:
                for i in items:
                    textbutton i.caption action i.action

# A screen of the scene whose text follows a variable: the same screen, shown once, is a new picture on every change.
screen tally_screen():
    text "Tally: [torture_tally]" xalign 0.5 yalign 0.3 size 48 color "#ffffff"

# A screen the script calls (`call screen`) and waits on, as a hub or a map is: its buttons that lead on are the options
# of a menu, worded as a screen reader says them (a button's text, or its `alt`). A button that leads nowhere and one
# that cannot be pressed are not options.
screen signpost():
    vbox:
        xalign 0.5
        yalign 0.5
        spacing 16
        textbutton "North road" action Return("north")
        textbutton "South road" action Return("south")
        button:
            action Jump("signpost_cellar")
            alt "The cellar door"
            add Solid("#665544", xsize=120, ysize=60)
        textbutton "Read the sign" action Notify("Both roads lead home.")
        textbutton "The locked gate" action [SensitiveIf(False), Return("gate")]
