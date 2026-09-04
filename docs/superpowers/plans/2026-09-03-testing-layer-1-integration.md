# Testing Layer 1 — Adversarial-Synthetic Integration Band Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive the whole `run_conform` end-to-end on synthetic geometry chosen to *provoke* the known failure regimes (rims, layering, asymmetry, girth-up balloon), asserting on the Layer 0 `ConformReport` metrics — so a regression that the current concentric-tube unit tests are built to avoid goes red in the fast suite.

**Architecture:** New operator-level tests in `tests/test_conform_integration.py` that build adversarial synthetic scenes with `common.py` builders (existing `make_tube` + one new elliptical builder), set `obj.sculpt_tool.target_body`, call `op_conform.run_conform`, and assert on `report.edge_distortion.distorted_fraction` / `report.looseness`. All checked-in-safe, no real corpus, runs in the ~14s fast suite.

**Tech Stack:** Python 3.11 (Blender 5.2 bundled), `bpy`/`mathutils`, stdlib `unittest`, headless Blender.

**Spec:** `docs/superpowers/specs/2026-09-03-testing-layers-design.md` (§2 Layer 1). Depends on Layer 0 (`ConformReport`, `quality.MAX_DISTORTED_FRACTION`) — merged in PR #46.

## Global Constraints

- **Test runner (no pytest):** `"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tests/run_tests.py` from the repo root. Discovers every `tests/test_*.py`, verbosity=2, exits non-zero on failure. Find your named tests in the output.
- **Layer 0 interfaces (already merged, use them):** `op_conform.run_conform(context, garment) -> ConformReport(info, edge_distortion, looseness)`; `quality.MAX_DISTORTED_FRACTION = 0.05`; `quality.EdgeDistortion.distorted_fraction`.
- **Operator setup pattern:** register with `sculpt_tool.register()` in `setUp` guarded by `if not hasattr(bpy.types.Object, "sculpt_tool")`, `unregister()` in `tearDown`; set `garment.sculpt_tool.target_body = target`; call `op_conform.run_conform(bpy.context, garment)` (import `from sculpt_tool.operators import op_conform`). This mirrors `tests/test_conform_quality.py`.
- **These tests encode hypotheses, not guaranteed passes.** Each adversarial case asserts the *intended-good* outcome (the new pipeline keeps identity). **If a case exceeds the gate, that is a real finding about the conform, not a test to weaken** — report it (DONE_WITH_CONCERNS or BLOCKED), file a Backlog card, and do NOT loosen the assertion to force green. The whole point of Layer 1 is to make such a gap visible.
- **Commit trailer:** `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

- `tests/common.py` — **modify**: add `make_elliptical_tube(...)` (an off-round target for the asymmetry case). Existing `make_tube` covers the rest.
- `tests/test_conform_integration.py` — **create**: the four adversarial operator-level tests.

---

### Task 1: `make_elliptical_tube` builder

**Files:**
- Modify: `tests/common.py`
- Test: covered indirectly by Task 2's asymmetry case; add a direct sanity test in `tests/test_conform_integration.py` (Task 2) rather than a separate file.

**Interfaces:**
- Produces: `common.make_elliptical_tube(name, segments=32, rings=20, radius_x=1.5, radius_y=1.0, height=4.0, location=(0,0,0)) -> object` — an open-ended tube like `make_tube` but with distinct X/Y radii, so a round garment tube conformed onto it meets a non-axisymmetric surface (nearest-point correspondence varies around the ring).

- [ ] **Step 1: Write the builder** (adapt `make_tube`'s body — the only change is `x = radius_x * cos`, `y = radius_y * sin`):

```python
def make_elliptical_tube(name, segments=32, rings=20, radius_x=1.5, radius_y=1.0,
                         height=4.0, location=(0.0, 0.0, 0.0)):
    """An open-ended quad tube with distinct X/Y radii (elliptical cross
    section) -- a non-axisymmetric target body, so a round garment tube
    conformed onto it must resolve correspondence that varies around the
    ring rather than the trivial radial case make_tube gives."""
    bm = bmesh.new()
    ring_verts = []
    for r in range(rings):
        z = -height / 2.0 + height * r / (rings - 1)
        row = []
        for s in range(segments):
            angle = 2.0 * math.pi * s / segments
            row.append(bm.verts.new((radius_x * math.cos(angle),
                                     radius_y * math.sin(angle), z)))
        ring_verts.append(row)
    bm.verts.ensure_lookup_table()
    for r in range(rings - 1):
        for s in range(segments):
            s2 = (s + 1) % segments
            bm.faces.new((ring_verts[r][s], ring_verts[r][s2],
                          ring_verts[r + 1][s2], ring_verts[r + 1][s]))
    obj = link_object(name, bm)
    obj.location = location
    update_scene()
    return obj
```

- [ ] **Step 2: Commit** (builder lands with Task 2's tests that use it; if executing task-by-task, commit builder + a placeholder import-check together, or fold this task into Task 2's first commit). Prefer folding into Task 2 — a builder with no caller is not independently reviewable.

> **Right-sizing note:** Task 1 has no standalone deliverable worth a review gate. An executor should implement `make_elliptical_tube` as the first edit of Task 2 and commit it alongside the asymmetry test that first uses it.

---

### Task 2: Adversarial integration tests

**Files:**
- Modify: `tests/common.py` (the Task 1 builder, if not already landed)
- Create: `tests/test_conform_integration.py`

**Interfaces:**
- Consumes: `op_conform.run_conform`, `quality.MAX_DISTORTED_FRACTION`, `common.make_tube`, `common.make_elliptical_tube`, `common.clear_scene`, `sculpt_tool.register/unregister`.

- [ ] **Step 1: Write the failing test file**

```python
"""Operator-level adversarial-synthetic integration tests (Layer 1).

Drives the whole op_conform.run_conform on synthetic scenes chosen to PROVOKE
the failure regimes the concentric-tube unit tests deliberately avoid, and
asserts the fitted result keeps its identity (low edge distortion). A case
that trips the gate is a real conform finding -- see the plan's Global
Constraints -- not a test to weaken.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import quality  # noqa: E402
from sculpt_tool.operators import op_conform  # noqa: E402


class ConformIntegrationTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def _conform(self, garment, target):
        garment.sculpt_tool.target_body = target
        bpy.context.view_layer.objects.active = garment
        return op_conform.run_conform(bpy.context, garment)

    def test_girth_up_does_not_balloon(self):
        # The Top-balloon regime in miniature: a tight garment onto a much
        # fatter target. The new pipeline must keep edges uniform.
        target = common.make_tube("Target", radius=2.0, height=4.0)
        garment = common.make_tube("Garment", radius=1.0, height=2.0)
        report = self._conform(garment, target)
        self.assertLess(report.edge_distortion.distorted_fraction,
                        quality.MAX_DISTORTED_FRACTION)

    def test_rim_projection_stays_uniform(self):
        # Garment TALLER than the target so its top/bottom rings project off
        # the open rim (the case test_conform.py is built to avoid).
        target = common.make_tube("Target", radius=1.5, height=2.0)
        garment = common.make_tube("Garment", radius=1.2, height=4.0)
        report = self._conform(garment, target)
        self.assertLess(report.edge_distortion.distorted_fraction,
                        quality.MAX_DISTORTED_FRACTION)

    def test_layered_garments_neither_collapses(self):
        # Two concentric garment tubes (inner ~ pasties, outer ~ Top) over one
        # target: conform each; neither should collapse into a distorted mass.
        target = common.make_tube("Target", radius=1.0, height=4.0)
        inner = common.make_tube("Inner", radius=1.1, height=2.0)
        outer = common.make_tube("Outer", radius=1.4, height=2.0)
        r_inner = self._conform(inner, target)
        r_outer = self._conform(outer, target)
        self.assertLess(r_inner.edge_distortion.distorted_fraction,
                        quality.MAX_DISTORTED_FRACTION)
        self.assertLess(r_outer.edge_distortion.distorted_fraction,
                        quality.MAX_DISTORTED_FRACTION)

    def test_asymmetric_target_no_scatter(self):
        # Round garment onto an elliptical target: correspondence varies around
        # the ring, but a single clean projection should not scatter edges.
        target = common.make_elliptical_tube("Target", radius_x=1.8, radius_y=1.0, height=4.0)
        garment = common.make_tube("Garment", radius=1.0, height=2.0)
        report = self._conform(garment, target)
        self.assertLess(report.edge_distortion.distorted_fraction,
                        quality.MAX_DISTORTED_FRACTION)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the suite; observe results honestly.**

Run the suite. Expected ideal: all four pass (the new pipeline handles these regimes). **If any case FAILS**, do not weaken it. Record which case, the actual `distorted_fraction`, and stop to report it as DONE_WITH_CONCERNS with the finding — it means the single-projection conform has a real gap in that regime (exactly what Layer 1 exists to surface), which becomes a Backlog card and possibly justifies the Layer 2 §4 optional-polish path.

- [ ] **Step 3: Commit**

```bash
git add tests/common.py tests/test_conform_integration.py
git commit -m "$(printf 'Add Layer 1 adversarial-synthetic conform integration tests\n\nDrives run_conform end-to-end over rim/layering/asymmetry/girth-up\nregimes the unit tests avoid, asserting fitted identity via the Layer 0\nedge-distortion metric.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Self-Review

- **Spec coverage (§2):** rim → `test_rim_projection_stays_uniform`; layering → `test_layered_garments_neither_collapses`; asymmetry → `test_asymmetric_target_no_scatter` + `make_elliptical_tube`; anti-balloon → `test_girth_up_does_not_balloon`. All four §2 cases covered.
- **Placeholder scan:** none — full builder and test code inline.
- **Type consistency:** `run_conform -> ConformReport`, `.edge_distortion.distorted_fraction`, `quality.MAX_DISTORTED_FRACTION` all match Layer 0 as merged.
- **Honesty note:** the assertions encode the hypothesis that the Direction-B pipeline handles these regimes. This plan is partly exploratory by design; a failing case is a finding, not a plan defect.
