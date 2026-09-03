# Testing Layer 0 — Metrics in run_conform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute `edge_distortion` and `looseness_preservation` on every real conform, surface them to the user (report + WARNING) and to tests, without ever blocking the bake.

**Architecture:** Add a pure `surface_standoffs` helper to `core/conform.py` and a pure `quality_warning` decision helper + threshold constants to `core/quality.py`. Change `run_conform` to return a `ConformReport` dataclass (info string + the two metrics); both operators read `.info` for their report and call `quality_warning` to emit a Blender WARNING when a gate is breached.

**Tech Stack:** Python 3.11 (Blender 5.2 bundled), `bpy`/`mathutils`, stdlib `unittest`. Tests run headless in Blender.

**Spec:** `docs/superpowers/specs/2026-09-03-testing-layers-design.md` (§1 Layer 0). Companion review: `TESTING_STRATEGY.md`.

## Global Constraints

- **Test runner (there is no pytest):** run the whole suite with
  `"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tests/run_tests.py`
  from the repo root. It discovers every `tests/test_*.py`, runs in ~14s
  with `verbosity=2` (each test named), and exits non-zero on any
  failure. "Verify it fails/passes" steps mean: run this, find the named
  test in the output.
- **`core/` stays Blender-free-testable where it already is:** `quality.py`
  imports no `bpy` — keep it that way (`quality_warning` is pure).
  `conform.surface_standoffs` may use `TargetContext.bvh` like its siblings.
- **No hard gate:** `run_conform` always completes the bake. Quality only
  ever produces a `{'WARNING'}`, never `{'CANCELLED'}`.
- **Commit message trailer** on every commit:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- Provisional thresholds (calibrated later in Layer 2):
  `MAX_DISTORTED_FRACTION = 0.05`, `MIN_LOOSENESS_RATIO = 0.4`.

## File Structure

- `sculpt_tool/core/conform.py` — **modify**: add `surface_standoffs(positions, target_ctx)`.
- `sculpt_tool/core/quality.py` — **modify**: add threshold constants + `quality_warning(edge_distortion, looseness)`.
- `sculpt_tool/operators/op_conform.py` — **modify**: add `ConformReport` dataclass; `run_conform` returns it; both operators read `.info` and emit WARNING via `quality_warning`.
- `tests/test_conform.py` — **modify**: add a `surface_standoffs` test.
- `tests/test_quality.py` — **modify**: add `quality_warning` tests.
- `tests/test_conform_quality.py` — **create**: end-to-end test that `run_conform` returns a populated `ConformReport`.

---

### Task 1: `surface_standoffs` pure helper

**Files:**
- Modify: `sculpt_tool/core/conform.py`
- Test: `tests/test_conform.py`

**Interfaces:**
- Consumes: `core.geometry.TargetContext` (has `.bvh`), `mathutils.Vector` (already imported in `conform.py`).
- Produces: `conform.surface_standoffs(positions, target_ctx) -> list[float]` — unsigned nearest-target-surface distance per input position, `0.0` for a vertex with no surface hit; index-aligned with `positions`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_conform.py`, inside `class ConformTubeTest` (it already has `_ctx`, and the module has `_mean`, `common.world_positions`):

```python
    def test_surface_standoffs_measures_distance_to_target(self):
        # Garment tube 0.2 outside a taller target tube -> every garment
        # vertex sits ~0.2 off the nearest target surface point.
        target = common.make_tube("Target", radius=1.0, height=4.0)
        garment = common.make_tube("Garment", radius=1.2, height=2.0)
        dists = conform.surface_standoffs(common.world_positions(garment), self._ctx(target))
        self.assertAlmostEqual(_mean(dists), 0.2, delta=0.02)
```

- [ ] **Step 2: Run the suite to verify it fails**

Run: `"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tests/run_tests.py`
Expected: `test_surface_standoffs_measures_distance_to_target` ERRORs with `AttributeError: module 'sculpt_tool.core.conform' has no attribute 'surface_standoffs'`.

- [ ] **Step 3: Write minimal implementation**

Add to `sculpt_tool/core/conform.py` (next to `placed_standoff`; `Vector` is already imported at module top):

```python
def surface_standoffs(positions, target_ctx):
    """Unsigned nearest-target-surface distance per vertex.

    The abs-distance sibling of :func:`placed_standoff` with no min-clearance
    clamp: just how far each vertex sits from the target surface, used by the
    quality metrics (looseness preservation) rather than by conform itself.
    Returns one float per ``positions`` entry, in order; a vertex with no
    surface hit gets ``0.0``.
    """
    bvh = target_ctx.bvh
    out = []
    for position in positions:
        _location, _normal, index, distance = bvh.find_nearest(Vector(position))
        out.append(distance if index is not None else 0.0)
    return out
```

- [ ] **Step 4: Run the suite to verify it passes**

Run: `"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tests/run_tests.py`
Expected: `test_surface_standoffs_measures_distance_to_target ... ok`; all other tests still `ok`.

- [ ] **Step 5: Commit**

```bash
git add sculpt_tool/core/conform.py tests/test_conform.py
git commit -m "$(printf 'Add conform.surface_standoffs (unsigned nearest-surface distance)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

### Task 2: thresholds + `quality_warning` decision helper

**Files:**
- Modify: `sculpt_tool/core/quality.py`
- Test: `tests/test_quality.py`

**Interfaces:**
- Consumes: `quality.EdgeDistortion` (existing dataclass with `.distorted_fraction`).
- Produces:
  - `quality.MAX_DISTORTED_FRACTION = 0.05`, `quality.MIN_LOOSENESS_RATIO = 0.4`.
  - `quality.quality_warning(edge_distortion, looseness) -> str | None` —
    `edge_distortion` is an `EdgeDistortion`; `looseness` is a float or
    `None`. Returns a human-readable message when a gate is breached, else
    `None`. `looseness is None` (no loose region) never warns on looseness.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_quality.py` (it imports `quality` already; pure, no `bpy`):

```python
class QualityWarningTest(unittest.TestCase):
    def _ed(self, distorted_fraction):
        return quality.EdgeDistortion(
            median_ratio=1.0, distorted_fraction=distorted_fraction, max_normalized=1.0
        )

    def test_high_distortion_warns(self):
        self.assertIsNotNone(quality.quality_warning(self._ed(0.2), None))

    def test_collapsed_looseness_warns(self):
        self.assertIsNotNone(quality.quality_warning(self._ed(0.0), 0.2))

    def test_clean_fit_is_none(self):
        self.assertIsNone(quality.quality_warning(self._ed(0.0), 0.9))

    def test_absent_loose_region_never_warns_on_looseness(self):
        # looseness None = tight garment, must not produce a looseness warning.
        self.assertIsNone(quality.quality_warning(self._ed(0.0), None))
```

- [ ] **Step 2: Run the suite to verify it fails**

Run: `"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tests/run_tests.py`
Expected: the four `QualityWarningTest` tests ERROR with `AttributeError: module 'sculpt_tool.core.quality' has no attribute 'quality_warning'`.

- [ ] **Step 3: Write minimal implementation**

Add to `sculpt_tool/core/quality.py` (constants near the top after the docstring; helper below `edge_distortion`):

```python
MAX_DISTORTED_FRACTION = 0.05  # warn above; provisional, calibrate in Layer 2
MIN_LOOSENESS_RATIO = 0.4      # warn below (when a loose region exists)
```

```python
def quality_warning(edge_distortion, looseness):
    """Human-readable warning if a fit's metrics breach the provisional
    gates, else ``None``.

    ``edge_distortion`` is an :class:`EdgeDistortion`; ``looseness`` is the
    median loose-standoff ratio or ``None`` (no loose region -- never warned).
    Pure decision logic so both the single and batch operators share one
    tested threshold source (no ``bpy``).
    """
    problems = []
    if edge_distortion.distorted_fraction > MAX_DISTORTED_FRACTION:
        problems.append(
            f"{edge_distortion.distorted_fraction:.0%} of edges distorted "
            f"(max {MAX_DISTORTED_FRACTION:.0%})"
        )
    if looseness is not None and looseness < MIN_LOOSENESS_RATIO:
        problems.append(
            f"loose regions kept {looseness:.0%} of standoff "
            f"(min {MIN_LOOSENESS_RATIO:.0%})"
        )
    return "; ".join(problems) if problems else None
```

- [ ] **Step 4: Run the suite to verify it passes**

Run: `"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tests/run_tests.py`
Expected: the four `QualityWarningTest` tests `... ok`; all others still `ok`.

- [ ] **Step 5: Commit**

```bash
git add sculpt_tool/core/quality.py tests/test_quality.py
git commit -m "$(printf 'Add quality gate thresholds + quality_warning decision helper\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

### Task 3: `ConformReport` + wire metrics into `run_conform` and both operators

**Files:**
- Modify: `sculpt_tool/operators/op_conform.py`
- Test: `tests/test_conform_quality.py` (create)

**Interfaces:**
- Consumes: `conform.surface_standoffs` (Task 1), `conform._bbox_diagonal`,
  `quality.edge_distortion`, `quality.looseness_preservation`,
  `quality.quality_warning`, `quality.EdgeDistortion` (Task 2).
- Produces: `op_conform.ConformReport(info: str, edge_distortion: EdgeDistortion, looseness: float | None)`; `run_conform(context, garment_obj) -> ConformReport`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_conform_quality.py`:

```python
"""run_conform returns a populated ConformReport, and a clean flat-grid
conform stays under the distortion gate (Layer 0 wiring)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import quality  # noqa: E402
from sculpt_tool.operators import op_conform  # noqa: E402


class ConformReportTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def test_run_conform_returns_populated_report(self):
        target = common.make_grid("Target", x_segments=6, y_segments=6, size=2.0)
        garment = common.make_grid("Garment", x_segments=4, y_segments=4,
                                   size=1.0, location=(0.0, 0.0, 0.1))
        garment.sculpt_tool.target_body = target
        bpy.context.view_layer.objects.active = garment

        report = op_conform.run_conform(bpy.context, garment)

        self.assertIsInstance(report, op_conform.ConformReport)
        self.assertIn("vertices", report.info)
        self.assertIsInstance(report.edge_distortion, quality.EdgeDistortion)
        # A regular grid projected onto a flat grid stays uniform.
        self.assertLess(report.edge_distortion.distorted_fraction,
                        quality.MAX_DISTORTED_FRACTION)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the suite to verify it fails**

Run: `"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tests/run_tests.py`
Expected: `test_run_conform_returns_populated_report` fails — `run_conform` still returns a `str`, so `assertIsInstance(report, op_conform.ConformReport)` fails with `AttributeError`/`AssertionError` (`ConformReport` does not exist yet).

- [ ] **Step 3: Write minimal implementation**

In `sculpt_tool/operators/op_conform.py`:

(a) Add imports near the top:

```python
from dataclasses import dataclass
```

and extend the existing core import to include `quality`:

```python
from ..core import conform, geometry, quality, storage
```

(b) Add the dataclass below `SHAPE_KEY_NAME`:

```python
@dataclass
class ConformReport:
    """What one conform produced: the human-readable summary plus the
    surface-quality metrics measured on the fitted result (Layer 0)."""
    info: str
    edge_distortion: quality.EdgeDistortion
    looseness: object  # float | None


def _measure_quality(rest_world, fitted_world, standoff, edge_pairs, target_ctx):
    """Compute the two Layer-0 metrics on a fitted result. ``standoff`` is the
    signed authored/placed standoff used by the conform; looseness is measured
    on its magnitude vs the fitted distance to the target surface."""
    distortion = quality.edge_distortion(rest_world, fitted_world, edge_pairs)
    authored_abs = [abs(s) for s in standoff]
    fitted_abs = conform.surface_standoffs(fitted_world, target_ctx)
    diag = conform._bbox_diagonal(target_ctx.positions)
    looseness = quality.looseness_preservation(authored_abs, fitted_abs, loose_fraction_of=diag)
    return distortion, looseness
```

(c) In `run_conform`, build the edge list once and reuse it for both
`neighbors` and the metric. Replace the Stage-3 `neighbors = ...` line's
inline comprehension with a named `edge_pairs`:

```python
    edge_pairs = [(e.vertices[0], e.vertices[1]) for e in mesh.edges]
    neighbors = conform.build_vertex_neighbors(edge_pairs, vertex_count)
    fitted_world = conform.project_to_target(
        placed_world, standoff, target_ctx, neighbors=neighbors
    )
```

(d) Replace the final `return (...)` string with the report. The existing
info string stays verbatim as `info`; compute metrics from data already in
scope (`rest_world`, `fitted_world`, `standoff`, `edge_pairs`, `target_ctx`):

```python
    info = (
        f"{vertex_count} vertices, "
        f"{'source-measured' if used_source else 'source-free'} standoff"
        f"{', placed via armature' if placed_via_armature else ''}"
    )
    distortion, looseness = _measure_quality(
        rest_world, fitted_world, standoff, edge_pairs, target_ctx
    )
    return ConformReport(info=info, edge_distortion=distortion, looseness=looseness)
```

(e) Update `SCULPTTOOL_OT_conform.execute` to read `.info` and warn:

```python
    def execute(self, context):
        garment_obj = context.object
        try:
            report = run_conform(context, garment_obj)
        except (ConformError, ValueError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Conformed '{garment_obj.name}' to "
            f"'{garment_obj.sculpt_tool.target_body.name}' ({report.info}).",
        )
        warning = quality.quality_warning(report.edge_distortion, report.looseness)
        if warning:
            self.report({'WARNING'}, f"'{garment_obj.name}' fit quality: {warning}.")
        return {'FINISHED'}
```

(f) Update `SCULPTTOOL_OT_batch_conform.execute` to capture the report and
count quality warnings:

```python
    def execute(self, context):
        garments = [o for o in context.selected_objects if o.type == 'MESH'
                    and getattr(o, "sculpt_tool", None)]
        done, warned, skipped = 0, 0, []
        for garment_obj in garments:
            try:
                report = run_conform(context, garment_obj)
                done += 1
                if quality.quality_warning(report.edge_distortion, report.looseness):
                    warned += 1
            except (ConformError, ValueError) as exc:
                skipped.append(f"{garment_obj.name} ({exc})")
        if done == 0 and skipped:
            self.report({'ERROR'}, "Batch Conform: nothing conformed. " + "; ".join(skipped))
            return {'CANCELLED'}
        msg = f"Batch Conform: {done} garment(s) conformed"
        if warned:
            msg += f" ({warned} with quality warnings)"
        if skipped:
            msg += f"; {len(skipped)} skipped -- " + "; ".join(skipped)
        self.report({'WARNING'} if skipped else {'INFO'}, msg + ".")
        return {'FINISHED'}
```

- [ ] **Step 4: Run the suite to verify it passes**

Run: `"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tests/run_tests.py`
Expected: `test_run_conform_returns_populated_report ... ok`, and the existing
`test_batch_conform` tests still `ok` (they call the operators, which now
return the report internally but still yield `{'FINISHED'}`/`RuntimeError`).
Full suite green.

- [ ] **Step 5: Commit**

```bash
git add sculpt_tool/operators/op_conform.py tests/test_conform_quality.py
git commit -m "$(printf 'Wire quality metrics into run_conform (ConformReport + WARNING)\n\nrun_conform now returns a ConformReport carrying edge_distortion and\nlooseness measured on the fitted result; both operators report the info\nline as before and emit a WARNING when a provisional gate is breached.\nThe bake is never blocked. Implements TESTING_STRATEGY.md Layer 0.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Self-Review

**Spec coverage (§1 Layer 0):**
- §1.1 `ConformReport` return shape → Task 3 (b), (d).
- §1.2 `surface_standoffs` → Task 1.
- §1.3 threshold constants → Task 2.
- §1.4 metric computation in `run_conform` → Task 3 (b) `_measure_quality`, (c)/(d).
- §1.5 operator surfacing (INFO + WARNING, batch count, never cancel) → Task 3 (e), (f).
- §1.6 tests → Task 1 (surface_standoffs), Task 2 (warning logic), Task 3 (report populated + clean-case gate).
- §1.7 edge handling (`looseness is None` never warns; metrics after bake) → Task 2 `test_absent_loose_region_never_warns_on_looseness`; metrics computed from `fitted_world` after the Stage-3/4 flow in Task 3.

Note: §1.6's "deliberately-distorted target trips the ceiling" case is
realised as the deterministic `quality_warning` unit tests in Task 2
(constructed `EdgeDistortion` values), rather than by forcing the real
conform to misbehave — same coverage of the threshold decision, without a
flaky geometric assertion. The real end-to-end path is covered by Task 3's
clean-case assertion; provoking real distortion end-to-end is Layer 1's job.

**Placeholder scan:** none — every step has concrete code and an exact run command.

**Type consistency:** `ConformReport(info, edge_distortion, looseness)` and
`run_conform -> ConformReport` used identically in Tasks 3(d), 3(e), 3(f) and
the Task 3 test. `quality_warning(edge_distortion, looseness)` signature
matches its Task 2 definition and all three call sites. `surface_standoffs(positions, target_ctx)` matches Task 1 and its Task 3 use.

**Note for the executor:** `_bbox_diagonal` and `_measure_quality` are
underscore-prefixed module-internal helpers reused within their own module —
consistent with `conform.py`'s existing `_bbox_diagonal`/`_MIN_CLEARANCE_FRAC`
convention.
