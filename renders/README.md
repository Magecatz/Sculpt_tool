# Showcase renders (dev tooling)

Headless-Blender rendering of the retarget pipeline on the real
`Test_Items` assets, so the result can be seen. **Dev tooling, not part of
the add-on** and not run by the test suite — opt-in, like `tests/perf.py` /
`tests/corpus_repro.py` (it needs the local, gitignored asset corpus).

A single parametric script, `render.py`, drives everything (it replaced the
old pile of one-off `render_r*.py` / `render_*_fix.py` / `render_variants`
scripts). It retargets garments onto bases through the deployed operators
(bind + placement + conform) and renders a solid Workbench image.

## Run

    # multi-view of one outfit (default: full Tech Set -> Egirl, 4 angles)
    blender --background --factory-startup --python renders/render.py -- views

    # grid of assorted garment x base pairings
    blender --background --factory-startup --python renders/render.py -- combos

`views` takes optional overrides after the mode — a comma-separated mesh
list from `FBX-Tech Set by Vinuzhka.fbx` and a base key (`Egirl` / `Fantasy`
/ `Venus`):

    ... -- views "Sweater by Vinuzhka,pants by Vinuzhka" Fantasy

Output PNGs land in `renders/out/` (gitignored). `render.py` imports
`renderlib` for shared helpers and path/config, so nothing hard-codes a
machine path:

- `renderlib.REPO_ROOT` / `renderlib.TEST_ITEMS` — auto-located (the latter
  honors `$SCULPT_TOOL_TEST_ITEMS`, then `<repo>/Test_Items`, then the main
  worktree's `Test_Items`).
- `renderlib.SMOOTHING_ITERATIONS` — smoothing passes the showcase fits use
  (edit to taste; `render.py` reads it via `s.smoothing_iterations`).

## Outputs

| Mode | Produces |
|---|---|
| `views` | `out/view_{front,three-quarter,side,back}.png` — one outfit, four angles |
| `combos` | `out/combos_3q.png` — a row of assorted garment × base pairings |
