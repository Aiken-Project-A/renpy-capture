# The config

A capture is driven by one JSON file. `renpy-capture init` writes a starter one:

```json
{
 "jobs": [{"id": "start", "label": "start"}],
 "ui": ".*",
 "settle": 0.3,
 "settle_max": 1.2,
 "max_steps": 3000,
 "loop_limit": 40
}
```

`explore` adds jobs to this file as it finds menu options that were not taken yet. Regexes are Python regular
expressions and match anywhere in the string (`re.search`) unless stated otherwise.

## Jobs

| key | meaning |
|---|---|
| `id` | A unique name. It also seeds the game's randomness, so a job always plays out the same. |
| `label` | The label to play. |
| `scope` | `{variable: value}` set in the store before the label, on top of the game's `default`s. |
| `choices` | The option to take in the 1st, 2nd, … menu met (0 is the first option). Menus beyond the list take the option matching `prefer`, or the first one; a menu met again (a quiz after a wrong answer) takes the next option. |
| `allow` | Labels that do not end the job even when they match `stop_labels` or live in `stop_files`. |
| `scene` | An image to show as the background before the label: for scenes that normally play over a hub or a map. |
| `replay` | `true` for a label that is a gallery replay and ends itself with `renpy.end_replay()`. |
| `prelude`, `camera` | Override the config keys of the same name for this job. |
| `loop_limit` | Overrides the config key. |
| `ui_timers` | `true`: interface screens receive events, so their timers run (to capture the "too late" outcome of a timed mini-game). A regex: only the matching screens. |
| `wait_menus` | A regex on menu captions: on such a menu, do not answer and wait until the game's timer leads on by itself. |
| `wait_max` | Seconds of game time to wait on such a menu (default 600). A menu still waiting then is answered as usual, and `report` warns about it. |
| `trans_max` | See below. |

## What is drawn

| key | default | meaning |
|---|---|---|
| `ui` | none | Screens whose names match are interface: they are not drawn and get no events. Everything else on the `screens` layer counts as part of the scene. `.*` treats every screen as interface. The say, choice, quick menu, notify and skip-indicator screens are always replaced by invisible ones (with `text`, the game's own dialogue window, speech bubbles, NVL page and menus are drawn). |
| `null_screens` | none | Screens replaced by empty ones (map screens whose logic fails without the state of earlier scenes). |
| `skip` | `[]` | Regexes on image files: a frame showing a matching file is not written (the record gets `skip`). |
| `drop` | none | A regex on image files that are drawn fully transparent. |
| `null_images` | `[]` | Image names replaced by an empty image: fades, flashes, noise, vignettes over the scene. `"text"` makes `show text "…"` invisible. |
| `still_transforms` | `[]` | Transforms of endless animation (shaking, pulsing) that are kept at rest: their instant first lines apply, the animation does not run. |
| `neutral_matrices` | `[]` | Names of colour-matrix functions in the store (e.g. `InvertMatrix`) replaced by the identity. |
| `hide_tags` | none | A regex on image tags that are never shown (captions over the scene); their text is logged as an effect of the line (`text:…`). |
| `fx_screens`, `fx_files` | none | Regexes on screens and image files to log as effects of the line (`fx`), to overlay them separately later. |
| `camera` | none | The camera of the master layer at the start of every job: the name of a transform in the store, or a dict of `Transform` properties (e.g. `{"perspective": true}`), as the game sets it before its scenes. |
| `prelude` | `[]` | Labels to call before the job's label: what the game does at start that is not a `default`. |

## When a frame is taken

| key | default | meaning |
|---|---|---|
| `settle` | 1.0 | Seconds of game time an interaction waits before its capture. |
| `settle_max` | `settle` | The longest wait while something on screen still moves (endless animation). |
| `early` | `true` | When the scene is made of the same things as at the last capture and nothing moves, capture at once. |
| `peak` | `true` | When a layer starts to fade out while the scene waits, capture at that moment, so the layer is in the frame. |
| `transitions` | `false` | Play transitions (`with dissolve`…) and capture after each one ends. Off: transitions are instant. |
| `trans_max` | 8 | The longest wait for a transition, in seconds. |
| `instant_camera` | `true` | Camera moves (`camera:` with ATL) jump to their final position. |
| `virtual_clock` | `true` | Game time advances by `timewarp/60` s per drawn frame instead of following the wall clock: runs are repeatable to the byte. |
| `text` | `false` | Keep the game's own dialogue window, speech bubbles, NVL page and menus in the frames (the same as `--text`): every line and menu gets a frame of its own, to check how a translation fits the window and whether the font has its glyphs. Without it a frame shows the scene alone. |
| `fast` | `false` | Skip the frames a scene draws while it settles; only the frames where the capture decides are drawn (the same as `--fast`). The same scenes and course of the game, but a motion that stops between two drawn frames is seen later, so later animations can be caught in another phase than without it. Jobs that let screen timers run (`ui_timers`, `wait_menus`) keep every frame. Repeatable to the byte among runs with `fast`. |

## When a job ends

| key | default | meaning |
|---|---|---|
| `stop_files` | none | A regex on script files: entering a label defined in a matching file ends the job. |
| `stop_labels` | none | A regex on label names: entering a matching label (a hub, a map) ends the job. |
| `max_steps` | 3000 | Interactions per job. |
| `loop_limit` | 40 | Captures of the same line from the same call site. `explore` retries a job stopped this way with `ui_timers`. |
| `ignore_errors` | none | A regex on the text of script errors to step over, as a player pressing "Ignore" would (an author's typo). Other errors end the job. |

## Mini-games and saved state

| key | meaning |
|---|---|
| `prefer` | A regex on menu captions: without a planned choice, take the first option that matches (e.g. "Skip the mini-game"). |
| `stub_screens` | `{screen: value}`: the screen returns `value` at once, as if the mini-game was won. |
| `persistent` | `{field: value}` set in the persistent data at start (tutorials seen, options unlocked). Every launch starts from the default persistent data otherwise. |
| `language` | Capture a translation: the language as its folder `game/tl/<language>` is named (`"russian"`). The engine starts in that language; a translated line keeps the `file` and `line` of the line it translates, so `compare` and `gaps` work across languages. The `--language` option overrides it. |

## Machine

| key | meaning |
|---|---|
| `gpu` | `auto` (default), `nvidia` or `mesa`: the OpenGL vendor for the engine (and for KWin). The `--gpu` option overrides it. |
| `display` | `kwin`, `xvfb` or `window`; the `--display` option overrides it. |
| `screen` | The size of the virtual screen, `"1920x1200"` by default; the game window keeps its own size inside it. |

## `gaps`

| key | meaning |
|---|---|
| `gaps_scope` | `{variable: value}`: branches decided by these values alone are not counted (`if outfit_b:` when the jobs set `outfit_a`). |
| `gaps_skip` | A regex on label names (matched from the start) that are not counted: whole alternative scenes. |

Hub labels (`stop_labels`) are not counted either.

## Export options

`renpy-capture export out game dest --options export.json`:

| key | default | meaning |
|---|---|---|
| `cg` | none | A regex on image files that make an event picture. With it, `cg/<label>_<NN>.png` and `cg.tsv` are written: a new state of the scene showing such a file, covering at least `cg_min` of the frame, that is not a blackout or a flash. |
| `cg_min` | 0.08 | The share of the frame a CG file must cover (opaque pixels). |
| `crop` | none | `[x0, y0, x1, y1]`: the picture area of the frame, for games that draw a frame around it. |
| `scenario` | all files | A regex on script files whose labels name scenes. |
| `label_skip` | `^_` | A regex on labels that do not name scenes (replay entry points…): the story label above them is used. |
| `min_pause` | 0.25 | A frame shown for a shorter pause is an effect, not a CG. |
| `flash` | none | A regex on image tags (matched from the start): a frame with one of them on screen is an effect. |
| `effects` | none | A regex on image tags and screen names (matched from the start) that are effects: frames of the same scene with and without them are one CG, and the cleanest is kept. |
| `context` | `false` | For chains of labels joined by jumps: take a CG from the run that reached it with the most of the scene behind it. |
| `fx_skip` | none | A regex on line effects not to list in `shots.tsv` and `effects.tsv`. |
