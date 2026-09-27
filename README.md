# renpy-capture

**A screenshot of every line of a Ren'Py game, taken by the game's own engine.**

renpy-capture plays a Ren'Py game with the official Ren'Py SDK of the same version and records every interaction —
each line of dialogue, pause and menu — with a screenshot of the scene at that moment, the script file and line, the
speaker and what is on screen. Then it takes every menu option it has not taken yet, and again, until no branch is
left. The result is a table of every line with its picture and a page you can read the game on like a book.

It is made for:

- **translators** — context for every line: who speaks, where, and what the scene looks like;
- **proofreaders and editors** — the whole game on one scrollable page, every branch included;
- **wikis and archives** — every scene of a game, and optionally its event pictures (CG) cut out and named after the
  labels that show them;
- **authors** — a visual walkthrough of every branch of their own game, and `gaps`: the scene and show lines that no
  path through the game reaches.

## How it works

- **The game is never modified or run by its own executable.** renpy-capture downloads the official SDK of the
  game's Ren'Py version from renpy.org (checked against the official sha256), makes a *launch folder* whose `game/`
  is made of links to the game's files, and adds one script, `capture.rpy`.
- Inside the engine, that script captures a frame once the scene has **settled**: one-shot animations have finished,
  transitions are over, and nothing asks for a redraw any more (endless animations are captured at a fixed phase). The
  dialogue window and the game's interface screens are not drawn, so the picture is the scene itself.
- A **job** plays a label as a replay (a fresh game state from `default`, plus the job's own variables) and answers
  menus with the options it was given, the first one otherwise. **`explore`** reads the menus met in the log and adds a
  job for every option not taken yet, until there are none.
- **Runs are repeatable to the byte.** Game time is driven by a frame counter instead of the wall clock, randomness is
  seeded from the job's name, and timers only fire when the capture lets them, so the same config gives the same PNGs
  every time, on one engine or on eight (`compare` checks it).
- Jobs can run on **several engines at once** (`prun`, `explore --workers`), and a watchdog restarts an engine whose
  job hangs.

## Requirements

- **Linux** and **Python 3.9+** (`Pillow` is installed with the package; it is used by `export`).
- A screen for the engine, one of:
  - `kwin` — a virtual KDE Plasma 6 compositor (`kwin_wayland --virtual`) with its own D-Bus session: nothing appears
    on your desktop, the engine renders on the GPU;
  - `xvfb` — a virtual X server (`Xvfb`): nothing appears on your desktop, the engine renders in software (Mesa);
  - `window` — your own desktop: the game window is visible while the capture runs; leave it alone.

  The first one available is used by default; `--display` picks one.
- For `gaps` and `export` on games that ship only compiled scripts (`.rpyc`):
  [unrpyc](https://github.com/CensoredUsername/unrpyc) — set `RENPY_CAPTURE_UNRPYC` to its folder. The capture itself
  does not need it.

Tested with Ren'Py 8.2 and 8.3.

## Quick start

```sh
pip install .                     # from a clone of this repository

renpy-capture init    ~/Games/MyGame config.json          # a starter config: one job from `start`
renpy-capture setup   ~/Games/MyGame run/                 # the launch folder (downloads the SDK once)
renpy-capture explore run/ config.json out/               # capture, taking every menu option
renpy-capture gaps    ~/Games/MyGame config.json out/     # scene/show lines no job has reached
renpy-capture export  out/ ~/Games/MyGame export/         # shots.tsv + index.html
xdg-open export/index.html
```

With a GPU and enough memory, `explore --workers 4` runs four engines at once. `renpy-capture <command> --help`
describes every option.

## What you get

- `out/frames/<sha1>.png` — every distinct frame, once.
- `out/log.jsonl` — one record per interaction and per job event (see [docs/output.md](docs/output.md)).
- `export/shots.tsv` — every interaction in order: job, step, script file and line, label, statement, speaker
  (variable and name), text, frame, menu options with the one taken.
- `export/index.html` — the same as a page: jobs as sections, each frame with the lines spoken over it.
- `export/cg/` and `cg.tsv` — event pictures, when `export --options` names the image files that make one
  ([docs/config.md](docs/config.md#export-options)).

## Games that need help

Most visual novels need nothing but the starter config. Games with more machinery can be guided by the config
([docs/config.md](docs/config.md)): mini-games can be skipped with a menu option (`prefer`) or a stub screen
(`stub_screens`), timed mini-games can be left to time out (`ui_timers`, `wait_menus`), map screens can end a scene
(`stop_labels`), effects can be kept out of the frame (`null_images`, `still_transforms`, `hide_tags`), and branches
chosen by flags set much earlier can be captured with exact jobs (`gaps` tells which ones).

## Limits

- Linux only for now.
- The official SDK must be able to run the game: games that ship a modified engine may not start.
- `gaps` and `export` read `.rpy` sources, `.rpyc` through unrpyc, and archives in the formats Ren'Py itself writes
  (RPA-2.0 and RPA-3.0). The index of an archive is read without running code from it; custom and obfuscated
  archive formats are not supported.

## Be kind to the authors

Capture games you own. The frames are the authors' work: do not publish them without their permission.

## License

MIT, see [LICENSE](LICENSE).
