# renpy-capture

**Every line of a Ren'Py visual novel, in every branch, with a screenshot taken by the game's own engine.**

[![Tests](https://github.com/Aiken-Project-A/renpy-capture/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Aiken-Project-A/renpy-capture/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-2b6cb0)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-2b6cb0)
![Linux](https://img.shields.io/badge/platform-Linux-2b6cb0)
![Ren'Py 7.8 | 8.2 | 8.3](https://img.shields.io/badge/Ren%27Py-7.8%20%7C%208.2%20%7C%208.3-2b6cb0)

renpy-capture plays a Ren'Py game on its own, with the official Ren'Py SDK of the game's version, on a virtual
screen. At every line of dialogue, pause and menu it saves a picture of the scene, with the speaker, the text and the
script file and line. Then it comes back for every menu option it has not taken yet, until no branch is left. You get
a table of every line with its picture, and a page to read the whole game on like a book:

![The export page: the pictures of a scene with the lines spoken over them](docs/images/export-page.jpg)

<sub>The Question, the sample game that ships with the Ren'Py SDK; its artwork is released under the MIT license.</sub>

See the whole result for The Question: https://aiken-project-a.github.io/renpy-capture/ — and its Russian
translation beside the original, with the game's own dialogue window:
https://aiken-project-a.github.io/renpy-capture/the-question-ru/

## Who it helps

- **Translators.** A line in a spreadsheet does not tell who speaks, to whom, or what is on screen; here every line
  comes with its scene and its translation id. Capture the translation too (`--language russian`): every translated
  line of every branch in its scene, and `compare` with the original shows that the translation takes the game the
  same way. With `--text` the frames keep the game's own dialogue window and menus: text that does not fit the
  window, a font without the glyphs — in minutes instead of hours of clicking.
- **Authors and testers.** Capture the game before and after a change: `compare` names the first line where a scene
  differs. `gaps` lists the scene and show lines that no path through the game reaches — a branch behind a flag that
  is never set.
- **Proofreaders and editors.** The whole game on one scrollable page, every branch included.
- **Wikis, archives and researchers.** Every scene of a game and its whole tree of choices (`choices.html`); event
  pictures (CG) can be cut out and named after the labels that show them.
- **Content review.** Every scene of every branch without playing the game — before an age rating, for example.

## Why it works this way

- **The game's own engine.** The pictures are what a player sees — its fonts, transitions, screens and layered
  images — not a guess made from the script.
- **The game stays untouched.** The launch folder only links to the game's files, the SDK comes from renpy.org and is
  checked against the official sha256, and the game's own executable is never run.
- **Every branch.** Menus met on the way become new jobs until no option is left untaken; `gaps` names what is still
  out of reach.
- **Repeatable to the byte.** Game time follows a frame counter instead of the wall clock, randomness is seeded from
  the job's name, and timers fire only when the capture lets them: the same config gives the same pictures every
  time, on one engine or on eight (`compare` checks it).
- **Unattended.** A virtual screen, several engines at once (`explore --workers`), a watchdog that restarts an engine
  whose job hangs, and an interrupted capture goes on where it stopped.

## How it works

```mermaid
flowchart LR
    G["Your copy of the game"] -->|setup| L["Launch folder<br/>links to the game + capture.rpy"]
    S["Official Ren'Py SDK<br/>from renpy.org, sha256 checked"] --> L
    L -->|explore| O["out/<br/>every picture + log.jsonl"]
    O -->|export| E["shots.tsv, index.html,<br/>CG pictures"]
    O -->|gaps| X["scene lines<br/>no path reached"]
    O -->|compare| C["first line where<br/>two captures differ"]
```

- Inside the engine, `capture.rpy` takes the picture once the scene has **settled**: one-shot animations have
  finished, transitions are over, and nothing asks for a redraw any more (endless animations are captured at a fixed
  phase). The dialogue window and the game's interface screens are not drawn, so the picture is the scene itself
  (`--text` keeps the window and menus).
- A **job** plays a label as a replay (a fresh game state from `default`, plus the job's own variables) and answers
  menus with the options it was given, the first one otherwise. **`explore`** reads the menus met in the log and adds
  a job for every option not taken yet, until there are none.
- Mods that players drop into `game/` and that draw over the game (Translator3000, the Universal Ren'Py Mod) are left
  out of the launch folder; `setup --exclude REGEX` leaves out anything else.

## Tested on

| | |
|---|---|
| **System** | Gentoo Linux, kernel 7.2 · KDE Plasma 6.7 (KWin 6.7.5) · Python 3.14 |
| **Graphics** | NVIDIA GeForce RTX 2060 (driver 615.71) · AMD Radeon Vega (Mesa 26.2, radeonsi) · software rendering (Xvfb 21.1, Mesa llvmpipe) |
| **Ren'Py** | 7.8.7, 8.2.3, 8.3.2 |
| **The sample game** | The Question: 3 jobs, 128 lines in seconds. The same pictures, byte for byte, on Ren'Py 7.8 and 8.3; the same scene at every line on all three graphics stacks. |
| **A large commercial game** | 44 jobs, 21,945 lines in about 8 minutes on four engines (RTX 2060). The same pictures, byte for byte, as a reference capture, and the same 591 event pictures. |

## Install and run

You need Linux, Python 3.9 or newer, and a screen for the engine. The first one available is used; `--display` picks
one:

- `kwin` — a virtual KDE Plasma 6 compositor (`kwin_wayland --virtual`) with its own D-Bus session: nothing appears
  on your desktop, the engine renders on the GPU;
- `xvfb` — a virtual X server (`Xvfb`): nothing appears on your desktop, the engine renders in software (Mesa);
- `window` — your own desktop: the game window is visible while the capture runs; leave it alone.

```sh
pipx install git+https://github.com/Aiken-Project-A/renpy-capture
# or, inside a virtual environment: pip install git+https://github.com/Aiken-Project-A/renpy-capture

renpy-capture capture ~/Games/MyGame work/
xdg-open work/export/index.html
```

`capture` does the whole job in one work folder: a starter config (`work/config.json`, yours to edit), the launch
folder (it downloads the game's Ren'Py SDK once), every option of every menu, a check for scene lines that no branch
reached, and the pages. A line shows how far it is while it runs; at the end it says what to open. Run the same
command again to go on after an interruption, or after editing the config to guide the capture.

Worth knowing: `--workers 4` runs four engines at once (with a GPU and memory to spare); `--fast` draws only the
frames where the capture decides, up to twice as fast on animated games, with animations maybe caught in another
phase; `--renpy-version` when the game does not tell its version. `renpy-capture capture --help` lists every option.
SDKs are kept in `~/.cache/renpy-capture/sdk` (`RENPY_CAPTURE_SDK` puts them elsewhere).

For games that ship only compiled scripts (`.rpyc`), the check for unreached lines and the scene names of the page
need [unrpyc](https://github.com/CensoredUsername/unrpyc): set `RENPY_CAPTURE_UNRPYC` to its folder. The capture
itself does not need it.

### A translation

```sh
renpy-capture capture ~/Games/MyGame work/ --text                      # the original, with its dialogue window
renpy-capture capture ~/Games/MyGame work/ --text --language russian   # the translation, from game/tl/russian
xdg-open work/export-text-russian/index.html
```

The second page shows every line of the original with its translation under it and both frames side by side: text
that does not fit the window, a font without the glyphs. Without `--text` the frames show the scenes alone, the same
to the byte in both languages, and `renpy-capture compare work/out work/out-russian` checks that the translation
takes the game the same way.

### Step by step

What `capture` does, command by command, for finer control:

```sh
renpy-capture init    ~/Games/MyGame config.json          # a starter config: one job from `start`
renpy-capture setup   ~/Games/MyGame run/                 # the launch folder (downloads the SDK once)
renpy-capture explore run/ config.json out/               # capture, taking every menu option
renpy-capture gaps    ~/Games/MyGame config.json out/     # scene/show lines no job has reached
renpy-capture export  out/ ~/Games/MyGame export/         # the pages and the table
```

`report` sums a capture up, `compare` checks two captures against each other, `run` and `prun` capture the jobs of a
config as they are (on one engine or several), `forget` drops jobs to capture them again; `--help` after any command
describes it.

## What you get

- `out/frames/<sha1>.png` — every distinct picture, once.
- `out/log.jsonl` — one record per interaction and per job event (see [docs/output.md](docs/output.md)).
- `export/shots.tsv` — every interaction in order: job, step, script file and line, label, statement, speaker
  (variable and name), text, picture, menu options with the one taken, translation id; with `--beside`, the line,
  menu and picture of the other capture too.
- `export/index.html` — the same as a page: jobs as sections, each picture with the lines spoken over it; with
  `--beside`, the other capture's lines under these and its picture next to this one when it differs. A search box
  filters the lines by text, speaker, script line or translation id (`index.html?q=Sylvie` opens with a search).
- `export/choices.html` — the tree of choices: every menu met, the line shown with it and the options taken, each
  one a link to its step on the page, down to where every job ended (a mini-game's menu met again and again is one
  line).
- `export/cg/` and `cg.tsv` — event pictures, when `export --options` names the image files that make one
  ([docs/config.md](docs/config.md#export-options)).

## Games that need help

Most visual novels need nothing but the starter config. Games with more machinery can be guided by the config
([docs/config.md](docs/config.md)): mini-games can be skipped with a menu option (`prefer`) or a stub screen
(`stub_screens`), timed mini-games can be left to time out (`ui_timers`, `wait_menus`), map screens can end a scene
(`stop_labels`), effects can be kept out of the picture (`null_images`, `still_transforms`, `hide_tags`), and branches
chosen by flags set much earlier can be captured with exact jobs (`gaps` tells which ones).

## When something is off

- **The capture is very slow.** `report` warns about it. If nearly every capture was taken "while something was
  still moving", an overlay never stops animating: a mod or a HUD screen; list its screens in `ui`, its files in
  `drop`, or leave it out with `setup --exclude`. If every interaction takes seconds, the GPU driver may be in a bad
  state (it happens after a laptop's discrete GPU wakes from sleep): `--gpu mesa` or `--display xvfb` still work, a
  reboot brings the GPU back.
- **Two runs differ.** `compare` shows the first line where the scene differs. Runs on different GPUs or drivers
  differ in pixels only: `compare --states-only`.
- **A job stops early.** `report` tells why: a script error (`ignore_errors` steps over an author's typo), a hub label
  (`stop_labels`), a loop (`loop_limit`), or the watchdog (`--stall`).
- **A timed menu was answered instead of timing out.** `report` warns when `wait_max` had to answer a menu of
  `wait_menus`: the game's timer lives on an interface screen (let it run with `ui_timers`) or needs longer
  (`wait_max`).
- **Something is on screen that should not be, or missing.** `export`'s `index.html` shows every picture; the log
  record of a line lists the images, screens and files that make it (`shown`, `screens`, `files`).

## Limits

- Linux only for now.
- The official SDK must be able to run the game: games that ship a modified engine may not start.
- `gaps` and `export` read `.rpy` sources, `.rpyc` through unrpyc, and archives in the formats Ren'Py itself writes
  (RPA-2.0 and RPA-3.0). The index of an archive is read without running code from it; custom and obfuscated
  archive formats are not supported.

## Tests

```sh
python -m unittest discover -s tests -t .                        # unit tests: no engine, no network
RENPY_CAPTURE_IT=1 python -m unittest tests.test_the_question    # end to end on The Question (downloads the SDK once)
RENPY_CAPTURE_IT=1 python -m unittest tests.test_torture         # end to end on the Torture Test (tests/games)
```

## Be kind to the authors

Capture games you own. The pictures are the authors' work: do not publish them without their permission.

## License

MIT, see [LICENSE](LICENSE).
