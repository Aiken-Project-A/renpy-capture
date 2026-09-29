# Changelog

## Unreleased

### Easier to use
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

## 0.1.0 — 2026-09-28

First public version.
