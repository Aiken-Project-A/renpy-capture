# Changelog

## Unreleased

### For translators
- `--language NAME` (config `language`) captures a translation: the engine starts in `game/tl/NAME`. A translated
  line keeps the file and line of the line it translates (`tl_file`, `tl_line` say where its text is), so `compare`
  and `gaps` work across languages, and `compare` with the original shows the translation takes the game the same way.
- Every line of dialogue has its translation id (`tl`) in the log, in `shots.tsv` and on the page.
- `--text` (config `text`) keeps the game's own dialogue window, speech bubbles, NVL page and menus in the frames:
  how the text fits the window, whether the font has the glyphs.
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
- The Ren'Py version of games made with Ren'Py 7.5 and later (`version = u'…'`) is read again; a project inside an
  SDK folder takes that SDK's version.

## 0.1.0 — 2026-09-28

First public version.
