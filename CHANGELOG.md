# Changelog

## Unreleased

### Windows
- renpy-capture runs on Windows 10 and 11 with Python 3.9 or newer (`pipx install renpy-capture`), proven on every
  pull request by the tests on windows-latest: the unit tests, the Torture Test, and The Question on Ren'Py 8.3.2 and
  7.8.7, whose capture has the same scene at every line as the capture made on Linux.
- The SDK comes as the official `.zip` there (the same files as the `.tar.bz2`, checked against the same official
  sha256 list), kept in `%LOCALAPPDATA%\renpy-capture\sdk`; the engine is `lib\py3-windows-x86_64\renpy.exe` of the
  SDK (`py2-…` for Ren'Py 7).
- The launch folder is made of hard links on Windows (symbolic links need an administrator or Developer Mode there),
  or of copies when the game is on another drive; `.links.json` lists them. The game is still never written to.
- The engine runs in a Job Object: it and anything it starts die with the capture, on Ctrl+C or when the console is
  closed too. Saves and persistent data stay in the launch folder, an error opens no editor, and the game window does
  not take the keyboard.
- Displays of Windows: `desktop` (the default: a desktop of its own, nothing on the user's screen), `offscreen` (the
  window beyond the edge of the screen) and `window`. On the tests' machine the three give the same frames, to the
  byte. See the guide, "On Windows".
- `capture.rpy` reaches the engine with LF line ends however git checked it out (with CRLF the engine stopped on
  "Indentation mismatch"), and a path on another drive is printed as it is instead of stopping `setup`.

### Fixed
- A game that ships `x_ren.py` with its compiled `x.rpyc`: `x.rpyc` was linked into the launch folder, and the
  engine, compiling `x_ren.py`, wrote it in place, through the link, into the game. It is no longer linked.

## 0.2.1 — 2026-10-03

- renpy-capture is on PyPI: `pipx install renpy-capture`. A release on GitHub is published there by itself (trusted
  publishing, no token stored anywhere).
- The README reads the same on PyPI (its pictures and links are absolute); the license is an SPDX expression and the
  LICENSE file is in the package.

## 0.2.0 — 2026-10-03

### Easier to use
- The README is one page for people, in eight languages (`docs/readme/`); everything technical is in `docs/guide.md`.
- `renpy-capture capture GAME WORKDIR` does the usual way in one command: a starter config, the launch folder, every
  branch, the check for unreached lines and the pages, all in one work folder, ending with what to open. Run it again
  to go on. With `--language` the translation's page shows the original beside it.
- A line tells how far a capture is while it runs (jobs done, lines captured, the job under way).
- Between rounds of `explore` one line sums the round up; warnings and failed jobs still show, the whole table is left
  to `report`. `prun` no longer prints a report for every batch of every engine.
- `--help` explains every argument, and the main help starts with the usual way.
- `explore` says when branches were left out because the config reached `--limit` jobs.
- Games that ship only compiled scripts need no setup by hand any more: unrpyc, which reads them for `gaps` and
  `export`, is downloaded once from its GitHub release and its files are checked (`RENPY_CAPTURE_UNRPYC` still points
  to a copy of your own).

### For translators
- `--language NAME` (config `language`) captures a translation: the engine starts in `game/tl/NAME`. A translated
  line keeps the file and line of the line it translates (`tl_file`, `tl_line` say where its text is), so `compare`
  and `gaps` work across languages, and `compare` with the original shows the translation takes the game the same way.
- Every line of dialogue has its translation id (`tl`) in the log, in `shots.tsv` and on the page.
- `--text` (config `text`) keeps the game's own dialogue window, speech bubbles, NVL page and menus in the frames:
  how the text fits the window, whether the font has the glyphs. A game without a dialogue window of its own gets the
  engine's built-in one.
- `export --beside OTHER_OUT` puts a second capture of the same jobs (a translation) next to the first, step by step:
  its lines under these, its frame next to this one; the pairs of a job end where it takes another way.

### New
- `choices.html`: the tree of choices of every family of jobs, each option a link to its step on the page, down to
  how each job ended; a menu met again and again is one line.
- The export page has a search box (text, speaker, script line, translation id; `index.html?q=…`) and an anchor for
  every step.
- A menu's record has its `caption`, the line shown with it; the page shows it above the options.
- `--fast` draws only the frames where the capture decides: the same scenes, faster on animated games.
- `report` shows where the time of the jobs went, and warns when `wait_max` had to answer a timed menu.
- A picture already saved by the engine is recognised before it is compressed again.

### Fixed
- A line could keep the picture of the line before it although the scene had changed: the same show line run with
  other arguments (`show sq at Position(xpos=x)` in a loop), a screen of the scene whose text follows a variable, an
  image on a layer of its own, an effect that had moved on. At rest a frame is now reused only when nothing was shown,
  hidden or put on a layer and the engine drew nothing anew since the last capture; otherwise the pixels decide. In
  the middle of an endless animation the scene's key decides, as before (its phases are not new frames), and the key
  now knows the arguments of a show.
- Without `--text` the NVL page is no longer drawn, as the documentation always said: like the dialogue window, it
  is replaced by an invisible one. A menu on the NVL page (`menu (nvl=True)`, `nvl_menu`) is answered like any other.
- `hide_tags` hides an image shown by `renpy.show` as well as by the show statement.
- A job whose id has a space is no longer captured again on every resume (`done.txt` is read line by line).
- A job that ends with an error while a screen is being built no longer breaks the jobs after it in the same engine.
- `shown` lists an image's attributes in a fixed order (Ren'Py 8 keeps them in a set, the order changed from run to
  run), and the engine runs with a fixed `PYTHONHASHSEED`, so a game's own sets keep their order too.
- `stack` lists only the game's return points: every record named the capture's own call of the job.
- `skip` names each file once, however many patterns match it.
- The label of a line is the label it belongs to in the script; after a `call` returned, lines were named after the
  procedure called.
- A game shipped as `.rpy` sources could not be captured twice (the engine's compiled scripts were taken for changes
  made by hand), and a script in a subfolder was compiled through the link into the game itself.
- The Ren'Py version of games made with Ren'Py 7.5 and later (`version = u'…'`) is read; a project inside an SDK
  folder takes that SDK's version.
- A click-to-continue indicator that blinks for ever no longer keeps a line from settling (each such line was
  captured only at `settle_max`, as if the scene were moving).
- `--display xvfb` and `--gpu mesa` no longer wake a laptop's sleeping NVIDIA GPU. Xvfb loaded NVIDIA's EGL driver just
  by starting; KWin opened a Vulkan instance on the NVIDIA GPU once the engine connected (KWin usually runs with file
  capabilities, and then the Vulkan loader ignores the environment). The GPU chosen now keeps the X server, the
  compositor and the engine on its vendor's EGL, GLX and Vulkan drivers, and KWin on that vendor's render nodes.
- `gaps` no longer runs the conditions of the game's scripts with `eval`: a crafted `if` naming a `gaps_scope` variable
  could run code on your machine. Conditions are computed from names, constants, comparisons, `and`/`or`/`not`,
  arithmetic and subscripts; anything else (a call, an attribute, `**`) is undecided and its branches stay open.
- `compare` no longer stops on a job the engine died in (no `end` record), and two captures that hold nothing (a
  misspelt path) no longer "match": it says so and exits 1.
- `explore` counts a branch left out over `--limit` once, not once per round.
- A damaged archive or an index that asks for code is reported in one line, not a traceback; a log with a broken line
  names the file and the line.
- `export` of a long capture is much faster (24 000 lines of a game with 3 000 labels: 8 s, now 1.4 s): the label of a
  line is looked up by bisection.

## 0.1.0 — 2026-09-28

First public version.
