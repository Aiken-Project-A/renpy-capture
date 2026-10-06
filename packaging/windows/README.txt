renpy-capture {version}, for Windows
=====================================

Every line of a Ren'Py game, in its scene, in every branch, without playing it.
It plays the game with the game's own engine on a screen of its own, answers every
menu every way, and keeps the picture the player sees at every line. What comes out
is a small website to read in your browser.


HOW TO START
------------

1. Unpack this zip first: right-click it, "Extract All". It does not run from inside
   the zip.
2. Open the folder you unpacked and double-click   renpy-capture-gui.exe
3. Choose the folder of the game, and press Capture.

That is all. Nothing else has to be installed.


THE FIRST TIME: "WINDOWS PROTECTED YOUR PC"
-------------------------------------------

This program is not signed (a certificate costs money every year), so Windows
SmartScreen may show a blue window. Click "More info", then "Run anyway". You do
this once. The whole source code is public, at
https://github.com/Aiken-Project-A/renpy-capture , and it is built there by GitHub
from that source.

The first capture also downloads the Ren'Py engine of your game's version from
renpy.org (150 to 165 MB, once): the program needs the internet then, and never
again for that version.


WHAT IS HERE
------------

  renpy-capture-gui.exe   the window
  renpy-capture.exe       the same as a command line, for a terminal:
                            renpy-capture.exe capture "D:\Games\SomeGame" work
                          (renpy-capture.exe --help lists everything)
  _internal\              what they run on: do not move or delete it

Your game is never changed. What a capture makes (the pictures, the pages, a log)
goes into the work folder you choose; the window remembers your choices in
%APPDATA%\renpy-capture .


MORE
----

  Guide:   https://github.com/Aiken-Project-A/renpy-capture/blob/main/docs/guide.md
  Issues:  https://github.com/Aiken-Project-A/renpy-capture/issues

Capture games you own. The pictures and the words are their authors' work: do not
publish them without permission.

renpy-capture is MIT licensed (LICENSE). THIRD-PARTY.txt has the licenses of what it
carries along (Python, Tcl/Tk, Pillow).
