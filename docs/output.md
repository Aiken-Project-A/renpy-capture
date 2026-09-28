# The output folder

| file | what it is |
|---|---|
| `frames/<sha1>.png` | Every distinct frame, once, named after the sha1 of its PNG. |
| `log.jsonl` | One JSON record per line: every interaction and every job event, in order. |
| `done.txt` | Jobs that are finished. `run` skips them, so an interrupted capture continues where it stopped. |
| `renpy.log`, `display.log` | What the engine and the display printed. |
| `traceback.txt`, `fatal.txt` | Present when the engine failed outside a job. |
| `pulse.json` | What the engine was doing a moment ago (to diagnose a hang); `pulse-stall-<job>.json` is kept when the watchdog restarted the engine. |
| `work/` | Batches of `prun` workers; failed batches are kept in `work/failed/`. |

`renpy-capture forget out JOB…` removes jobs from `log.jsonl` and `done.txt` before capturing them again.

## Records

Every record has `ev` (the kind) and `job`.

**`start`** — a job began: `label`.

**`shot`** — an interaction was captured:

| field | meaning |
|---|---|
| `seq` | The step within the job, from 1. |
| `kind` | The statement: `Say`, `TranslateSay`, `Menu`, `UserStatement`, `Pause`… (the class of the Ren'Py node). |
| `file`, `line` | Where the statement is in the scripts (`game/script.rpy`, 120). |
| `label`, `at` | The label the statement belongs to in the script, as Ren'Py names lines for translation: the last story label above it in its file (not starting with `_`) and the last label of any kind. After a `call` returns, the lines are the caller's again; a line of a translation (`tl/`) has the label of the line it translates. |
| `who`, `name`, `what` | For lines of dialogue: the speaker as written in the script, the name the player sees, and the text as written (with its text tags and `[variables]`). |
| `menu` | For menus: `n` (the menu's number in the job), `options` (the captions) and `pick` (the option taken), or `wait: true` when the capture waited on it. |
| `pause` | The length of the pause, for pauses. |
| `stack` | Return points of the calls in progress (`[file, line]`, innermost last). |
| `shown` | Images on the master layer: tag and attributes, e.g. `"sylvie green smile"`. |
| `screens` | Screens that are part of the scene (not matched by `ui`). |
| `files` | Image files the scene is drawn from. |
| `cam` | The camera, when it is not at rest. |
| `fx` | Effects running on this line but kept out of the frame (see `null_images`, `hide_tags`, `fx_screens`, `fx_files`). |
| `frame` | The sha1 of the frame (`frames/<sha1>.png`); missing when `skip` is set. |
| `same` | The scene has not changed since the previous capture; `frame` is the previous one. |
| `anim` | Captured while an endless animation was running (its phase is fixed by the frame clock). |
| `peak` | Captured as a layer began to fade out. |
| `skip` | The image files that made the frame skipped. |

**`wait`** — still waiting on a timed menu: `t`, seconds of game time so far.

**`stop`** — the job was ended early: `why` is `max_steps`, `loop` (with `file`, `line`), `label` (with `label`, and
`file` for `stop_files`) or `stall` (the watchdog).

**`error`** — a script error: `error` (the traceback), `seq`, `label`; `ignored: true` when `ignore_errors` stepped
over it.

**`end`** — a job finished: `steps`, `why` (`end`; `restart` when the game went back to its main menu;
`exception: …`; `stall`), `seconds` (wall-clock time), and `prof`, where that time went: `frames` drawn while scenes
settled and `draw` (seconds spent drawing them), `shots` screenshots and `shot` (seconds), `known` screenshots whose
pixels this engine had already saved (no PNG needed), `encoded` pictures compressed to PNG and `png` (seconds), `dup`
of them already saved by an earlier launch, and `save` (seconds hashing and writing). `report` sums them up.
