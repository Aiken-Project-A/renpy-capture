# The window a line is said in and the buttons of a menu, the least a game defines. A capture replaces them with
# invisible stand-ins, and draws them with `text`.

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
