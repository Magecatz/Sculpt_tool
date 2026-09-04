# Testing Layer 2 — Real-Corpus Acceptance Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A checked-in, opt-in acceptance module that runs the real Tech Set garments through `op_conform` onto the real Venus/Egirl bases and asserts the fitted result keeps its authored identity (`edge_distortion.distorted_fraction < τ`, `looseness ≈ 1`) — the "balloon gate" that would have gone red on the original failure, and the run that calibrates Layer 0's provisional thresholds.

**Architecture:** `tests/acceptance_corpus.py` — NOT discovered by `run_tests.py` (no `test_` prefix), run via its own `blender --background --python` entry, gated on the presence of the gitignored `Test_Items/` corpus (skips cleanly when absent). It reuses `renders/renderlib.py`'s corpus locator and FBX import helpers, imports each Tech Set piece + its ZinPia source base + a target base, calls `op_conform.run_conform`, and asserts on the Layer 0 `ConformReport`.

**Tech Stack:** Python 3.11 (Blender 5.2 bundled), `bpy`/`mathutils`, stdlib `unittest`, `renders/renderlib.py`, headless Blender.

**Spec:** `docs/superpowers/specs/2026-09-03-testing-layers-design.md` (§3 Layer 2, §4 process rule). Depends on Layer 0 (`ConformReport`, thresholds) — merged in PR #46.

## Global Constraints

- **The corpus is not in every checkout.** `Test_Items/` is gitignored third-party art; it exists in the main working copy but NOT in linked worktrees. Every corpus access goes through `renderlib._find_test_items()` (env `SCULPT_TOOL_TEST_ITEMS` → `<repo>/Test_Items` → `Test_Items` beside the main git-common-dir). **If the corpus is absent, the module SKIPS with a clear message and exits 0 — never fails.**
- **Not in the fast suite.** The module must NOT be named `test_*.py` (so `run_tests.py`'s discovery ignores it) and is run explicitly:
  `"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tests/acceptance_corpus.py`
- **Real asset constants (from `renders/render.py`, verified):**
  - `TECH_SET = "FBX-Tech Set by Vinuzhka.fbx"` under `Test_Items/Clothing/`.
  - Source base (Tech Set was authored for it): `("ZinPia_Fit Base HEELED Foot High Poly.fbx", "ZIN_FIT BASE")` under `Test_Items/Body/`.
  - Targets: Egirl `("vrbase_Egirl_Heeled Foot.fbx", "BODY")`, Venus `("Project Venus_v2.02.fbx", "Body")` under `Test_Items/Body/` (Venus = cross-creator).
  - Tech Set piece mesh names are only partially known (`render.py` defaults to `"Sweater by Vinuzhka"`, `"pants by Vinuzhka"`); the full set incl. the balloon-prone `Top`/`pasties` is **discovered by Task 1**, not guessed.
- **Layer 0 interfaces:** `op_conform.run_conform(context, garment) -> ConformReport(info, edge_distortion, looseness)`; `quality.MAX_DISTORTED_FRACTION`, `quality.MIN_LOOSENESS_RATIO`.
- **Conform setup (from `render.py:_conform`):** per garment mesh set `s = gm.sculpt_tool; s.source_body = zin_mesh; s.target_body = base_mesh; s.target_base_armature = base_rig` (base rig via `sculpt_tool.core.rig.deforming_armature(base_mesh)`), then `run_conform`.
- **Thresholds are EMPIRICAL.** Task 1's calibration run produces the real baseline `distorted_fraction`/`looseness` per piece; Task 2's gate constants (`τ`) are set from those numbers and fed back into `quality.py` (per spec §3 calibration loop). Do NOT invent τ — measure it.
- **Commit trailer:** `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

- `tests/acceptance_corpus.py` — **create**: the corpus harness (locator/skip + import helpers wrapper), the calibration entry (Task 1), and the assertion gate (Task 2). One file — the calibration and the gate share the same import/conform scaffolding.
- `sculpt_tool/core/quality.py` — **modify** (Task 2, after calibration): update `MAX_DISTORTED_FRACTION`/`MIN_LOOSENESS_RATIO` to the calibrated values if the measured baselines justify it, with a comment citing the calibration.

---

### Task 1: Corpus harness + calibration run (produces the numbers Task 2 needs)

**Files:**
- Create: `tests/acceptance_corpus.py`

**Interfaces:**
- Produces (for Task 2, same file): `_corpus_or_skip()` (returns the corpus `Path` or prints SKIP and `sys.exit(0)`); `_import_piece_and_bases(...)` scaffolding; and — as printed run output — the per-piece `(mesh_name, vertex_count, distorted_fraction, looseness)` for Tech Set → {ZinPia source} → {Egirl, Venus}.

- [ ] **Step 1: Write the harness + a discovery/calibration `main()`**

Reuse `renderlib` rather than re-implementing FBX import. The calibration `main()` imports the whole Tech Set, lists every mesh (name + vert count), then conforms each onto Egirl and Venus (ZinPia as source) and prints the metrics.

```python
"""Real-corpus acceptance gate for op_conform (Layer 2). OPT-IN.

NOT named test_*.py, so tests/run_tests.py never discovers it. Run explicitly:

    blender --background --factory-startup --python tests/acceptance_corpus.py

Skips cleanly (exit 0) when the gitignored Test_Items corpus is absent, so it
is safe to invoke anywhere. With the corpus present it runs the real Tech Set
garments through the real op_conform onto real bases and gates on the fitted
result keeping its authored identity -- the failure the fast synthetic suite
structurally cannot see (TESTING_STRATEGY.md).
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDERS = REPO_ROOT / "renders"
for p in (str(REPO_ROOT), str(RENDERS), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import bpy  # noqa: E402
import renderlib as R  # noqa: E402  (provides _find_test_items, import_group, TEST_ITEMS)
import sculpt_tool  # noqa: E402
from sculpt_tool.core import rig  # noqa: E402
from sculpt_tool.operators import op_conform  # noqa: E402

TECH_SET = "FBX-Tech Set by Vinuzhka.fbx"
SOURCE_ZIN = ("ZinPia_Fit Base HEELED Foot High Poly.fbx", "ZIN_FIT BASE")
TARGETS = {
    "Egirl": ("vrbase_Egirl_Heeled Foot.fbx", "BODY"),
    "Venus": ("Project Venus_v2.02.fbx", "Body"),
}


def _corpus_or_skip():
    corpus = R.TEST_ITEMS
    if not ((corpus / "Body").is_dir() and (corpus / "Clothing").is_dir()):
        print(f"SKIP: Test_Items corpus not found at {corpus} "
              f"(set SCULPT_TOOL_TEST_ITEMS or run from the main checkout).")
        sys.exit(0)
    return corpus


def _clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def _import_base(corpus, fbx, obj_name):
    group = R.import_group(corpus / "Body" / fbx, {obj_name})
    mesh = next(o for o in group if o.type == 'MESH')
    return mesh, rig.deforming_armature(mesh)


def _conform_piece(corpus, mesh_name, target_key):
    """Import one Tech Set piece + ZinPia source + one target, conform, and
    return the ConformReport (plus the piece's vertex count)."""
    _clear()
    if not hasattr(bpy.types.Object, "sculpt_tool"):
        sculpt_tool.register()
    zin_mesh, _ = _import_base(corpus, *SOURCE_ZIN)
    base_fbx, base_obj = TARGETS[target_key]
    base_mesh, base_rig = _import_base(corpus, base_fbx, base_obj)
    piece_group = R.import_group(corpus / "Clothing" / TECH_SET, {mesh_name})
    garment = next(o for o in piece_group if o.type == 'MESH')
    s = garment.sculpt_tool
    s.source_body = zin_mesh
    s.target_body = base_mesh
    s.target_base_armature = base_rig
    bpy.context.view_layer.objects.active = garment
    report = op_conform.run_conform(bpy.context, garment)
    return report, len(garment.data.vertices)


def calibrate():
    """DISCOVERY: list every Tech Set mesh and print conform metrics onto each
    target. Its printed output supplies Task 2's exact mesh names and the
    empirical baseline that sets the gate thresholds."""
    corpus = _corpus_or_skip()
    _clear()
    all_objs = R.import_group(corpus / "Clothing" / TECH_SET,
                              set())  # empty keep-set: import then list below
    # import_group with an empty keep-set removes everything; instead list from
    # a raw import:
    _clear()
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(filepath=str(corpus / "Clothing" / TECH_SET))
    meshes = [o for o in bpy.data.objects
              if o.name not in before and o.type == 'MESH']
    print("=== Tech Set meshes ===")
    for m in sorted(meshes, key=lambda o: o.name):
        print(f"  {m.name!r}: {len(m.data.vertices)} verts")
    names = [m.name for m in meshes]

    print("=== conform metrics (source=ZinPia) ===")
    for name in names:
        for target_key in TARGETS:
            report, vcount = _conform_piece(corpus, name, target_key)
            loose = "None" if report.looseness is None else f"{report.looseness:.3f}"
            print(f"  {name!r} -> {target_key}: verts={vcount} "
                  f"distorted_fraction={report.edge_distortion.distorted_fraction:.4f} "
                  f"looseness={loose}")


if __name__ == "__main__":
    calibrate()
```

- [ ] **Step 2: Run the calibration (needs the corpus)**

Run from the main checkout (or set `SCULPT_TOOL_TEST_ITEMS`):
`"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tests/acceptance_corpus.py`
Expected without corpus: prints `SKIP:` and exits 0. With corpus: prints the mesh list and a `distorted_fraction`/`looseness` line per (piece, target).

- [ ] **Step 3: Record the calibration output** in the task report — the exact Tech Set mesh names (especially the balloon-prone `Top`/`pasties` equivalents and `pants`), their vertex counts, and the per-piece baseline metrics. **These numbers are the deliverable of Task 1**; Task 2's thresholds and asserted piece list come from them.

- [ ] **Step 4: Commit the harness** (calibration entry only — no gate yet)

```bash
git add tests/acceptance_corpus.py
git commit -m "$(printf 'Add opt-in real-corpus conform calibration harness (Layer 2 pt 1)\n\nImports the real Tech Set through renderlib, conforms each piece onto\nEgirl/Venus (ZinPia source), and prints per-piece edge-distortion and\nlooseness baselines. Skips cleanly when the gitignored corpus is absent.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

> **Executor note:** if `calibrate()`'s empty-keep-set `import_group` call is awkward, replace it with the raw-import listing shown below it (the code already does this) and delete the dead first call. Reviewer should flag the dead call if left in.

---

### Task 2: The acceptance gate (uses Task 1's measured numbers)

**Files:**
- Modify: `tests/acceptance_corpus.py` (add a `unittest.TestCase` gate + a runner that skips cleanly)
- Modify: `sculpt_tool/core/quality.py` (only if calibration shows the provisional `0.05`/`0.4` need adjusting)

**Interfaces:**
- Consumes: Task 1's `_corpus_or_skip`, `_conform_piece`, and its recorded mesh names + baselines.

- [ ] **Step 1: Encode the gate from the measured baselines**

Using the mesh names and metrics recorded in Task 1, add a gate. Pick `τ` as a margin above the measured clean baseline (e.g. if a healthy Top fits at `distorted_fraction ≈ 0.01`, gate at `< 0.03`, comfortably below the value a balloon produces). Assert `looseness` above the measured collapse boundary. Example shape (fill `PIECES` and thresholds from Task 1's run):

```python
# From Task 1 calibration (fill in the real discovered names + chosen margins):
PIECES = ["<Top mesh name>", "<pasties mesh name>", "pants by Vinuzhka"]
GATE_DISTORTED_FRACTION = 0.03   # set from calibration: margin above clean baseline
GATE_LOOSENESS = 0.5             # set from calibration: above measured collapse

class CorpusAcceptanceTest(unittest.TestCase):
    def _assert_piece(self, mesh_name, target_key):
        report, _ = _conform_piece(_CORPUS, mesh_name, target_key)
        self.assertLess(report.edge_distortion.distorted_fraction, GATE_DISTORTED_FRACTION,
                        f"{mesh_name} -> {target_key} ballooned/scattered")
        if report.looseness is not None:
            self.assertGreater(report.looseness, GATE_LOOSENESS,
                               f"{mesh_name} -> {target_key} loose region collapsed")

    def test_tech_set_onto_venus(self):
        for name in PIECES:
            with self.subTest(piece=name):
                self._assert_piece(name, "Venus")

    def test_tech_set_onto_egirl(self):
        for name in PIECES:
            with self.subTest(piece=name):
                self._assert_piece(name, "Egirl")
```

- [ ] **Step 2: Wire the runner to skip cleanly and gate**

Replace the `__main__` block so the corpus check happens first, then unittest runs and the process exits on its result:

```python
if __name__ == "__main__":
    _CORPUS = _corpus_or_skip()   # prints SKIP + exit 0 when absent
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true")
    args, _ = parser.parse_known_args()
    if args.calibrate:
        calibrate()
    else:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(CorpusAcceptanceTest))
        sys.exit(0 if result.wasSuccessful() else 1)
```

(`_CORPUS` is module-global for the test case; `calibrate()` keeps its own `_corpus_or_skip()` call so `--calibrate` still works standalone.)

- [ ] **Step 3: Run the gate (needs corpus); calibrate `quality.py` if warranted**

Run: `blender --background --factory-startup --python tests/acceptance_corpus.py`. Expected with corpus: the gate passes on healthy fits (or FAILS red on a real balloon — which is a genuine finding, file a card). Expected without corpus: `SKIP`, exit 0. If the measured clean baselines show the Layer 0 provisional `MAX_DISTORTED_FRACTION=0.05` / `MIN_LOOSENESS_RATIO=0.4` are miscalibrated, update them in `sculpt_tool/core/quality.py` with a comment citing the calibration numbers, and re-run the fast suite to confirm the Layer 0 unit tests still hold.

- [ ] **Step 4: Commit**

```bash
git add tests/acceptance_corpus.py sculpt_tool/core/quality.py
git commit -m "$(printf 'Add real-corpus balloon gate + calibrate thresholds (Layer 2 pt 2)\n\nGates the real Tech Set onto Venus/Egirl on fitted-identity metrics; the\ntest that would have gone red on the original Top balloon. Thresholds set\nfrom the Task 1 calibration baselines.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

- [ ] **Step 5: Document the pre-merge step**

Add a line to `TESTING_STRATEGY.md` §4.2 / the Builder checklist noting the required command (`blender --background --python tests/acceptance_corpus.py`) so the gate is actually run before merge (per spec §4 process rule). Commit with the same trailer.

---

## Self-Review

- **Spec coverage (§3):** opt-in non-`test_` module → `acceptance_corpus.py`; real Tech Set → Venus/Egirl gate → Task 2; skip-if-absent → `_corpus_or_skip`; threshold calibration loop feeding `quality.py` → Task 1 output + Task 2 Step 3; required pre-merge step → Task 2 Step 5.
- **Placeholder scan:** the only intentionally-deferred values are the discovered mesh names and calibrated τ, explicitly produced by Task 1's calibration run (spec §3 mandates measuring them) — not guessable placeholders. Everything mechanical (locator, import, conform setup, runner, skip) is concrete.
- **Type consistency:** `run_conform -> ConformReport`, `.edge_distortion.distorted_fraction`, `.looseness`, `rig.deforming_armature`, `renderlib.import_group/TEST_ITEMS` all match the real code read during planning.
- **Known wrinkle for the executor:** `calibrate()`'s first `import_group(..., set())` call is dead (the raw-import listing below it does the real work); drop it during implementation. Flagged so it isn't shipped.
- **Honesty note:** like Layer 1, this gate encodes the hypothesis that Direction-B keeps identity on the real corpus. A red result is the gate doing its job — a finding and a card, never a threshold loosened to force green.
