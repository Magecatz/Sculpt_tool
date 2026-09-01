# Showcase renders (dev tooling)

Headless-Blender scripts that render the retarget pipeline on the real
`Test_Items` assets, so each stage can be seen. **Dev tooling, not part of
the add-on** and not run by the test suite — opt-in, like `tests/perf.py` /
`tests/corpus_repro.py` (they need the local, gitignored asset corpus).

## Run

    blender --background --factory-startup --python renders/render_r8.py

Output PNGs land in `renders/out/` (gitignored). Each script imports
`renderlib` for shared helpers and path/config, so nothing hard-codes a
machine path:

- `renderlib.REPO_ROOT` / `renderlib.TEST_ITEMS` — auto-located (the latter
  honors `$SCULPT_TOOL_TEST_ITEMS`, then `<repo>/Test_Items`, then the main
  worktree's `Test_Items`).
- `renderlib.SMOOTHING_ITERATIONS` — smoothing passes the showcase fits use
  (edit to taste; scripts read it via `s.smoothing_iterations`).

## What each renders

| Script | Shows |
|---|---|
| `render_r1.py` | Base retargeting — source vs target base (rig awareness) |
| `render_r2.py` | Canonical bone map — matched bones colored across two rigs |
| `render_r3.py` | Pose transfer — sleeves follow an arms-down base |
| `render_r4.py` | Alignment guard — accepted vs refused |
| `render_r5.py` | End-to-end pipeline — one garment onto three bases |
| `render_r6.py` | Full Tech Set retarget across three bases |
| `render_r7.py` | Position + scale placement (before/after) |
| `render_r8.py` | Fit consumes the placed garment (before/after) |
| `render_r9.py` | Corrected capstone — full Tech Set, placed + scaled |
| `render_variants.py` | Assorted garments × assorted bases |
