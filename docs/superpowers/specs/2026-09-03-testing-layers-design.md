# Testing Layers — Design Spec

Date: 2026-09-03
Status: Approved for planning
Companion: `TESTING_STRATEGY.md` (the Tech Lead review this implements)

## Problem

The suite is green (91 unit tests, ~14s, all synthetic) while the tool
produces broken sculpts. `TESTING_STRATEGY.md` diagnoses why: the pass/fail
gate and the quality bar are disjoint. The two `core/quality.py` metrics
that would catch the real failures (`edge_distortion`,
`looseness_preservation`) are computed nowhere in the product, and no test
ever runs the real corpus.

This spec designs the three missing layers. **Only §1 (Layer 0) is built
now**; §2 and §3 are designed here and implemented as follow-on Bear cards.

## Goals / Non-goals

**Goals**
- Compute the quality metrics on every real conform, surfaced to the user
  and available to tests (Layer 0).
- Add an operator-level integration band that provokes the known failure
  regimes and asserts on the metrics (Layer 1).
- Add a real-corpus acceptance gate that would have gone red on the balloon
  (Layer 2), and use it to calibrate the Layer 0 thresholds.

**Non-goals**
- No change to the conform math itself (`project_to_target` et al. untouched).
- No hard-refuse / cancel path in `run_conform` — it always completes the
  bake; the gate lives in tests, the user gets a WARNING only.
- No wiring of the orphaned rim-relax (that is a separate Backlog card, see
  `TESTING_STRATEGY.md` §6).

---

## 1. Layer 0 — metrics in `run_conform` (BUILD NOW)

### 1.1 Return shape

`run_conform` currently returns an info **string**, consumed by
`OT_conform` and `OT_batch_conform`. Replace it with a small dataclass:

```python
@dataclass
class ConformReport:
    info: str                      # the existing human-readable summary
    edge_distortion: EdgeDistortion  # from core.quality
    looseness: float | None        # median loose-standoff ratio, or None
```

Both operators read `.info` for their report line and inspect the metric
fields for the WARNING. This is the only signature change, contained to the
two call sites.

### 1.2 New pure helper — `core/conform.py`

```python
def surface_standoffs(positions, target_ctx):
    """Unsigned nearest-target-surface distance per vertex."""
```

The abs-distance sibling of `placed_standoff`, with no min-clearance
clamping. Pure (positions + `TargetContext` in, floats out), unit-testable
without a full conform, matching `core/`'s Blender-free convention.

### 1.3 Thresholds — `core/quality.py`

Add module-level constants as the single source of truth, marked provisional
pending §3 calibration:

```python
MAX_DISTORTED_FRACTION = 0.05  # warn above; calibrate in acceptance layer
MIN_LOOSENESS_RATIO = 0.4      # warn below (when a loose region exists)
```

### 1.4 Metric computation in `run_conform`

After the Stage-4 bake, with data already in scope:

- `edge_distortion(rest_world, fitted_world, edges)` where
  `edges = [(e.vertices[0], e.vertices[1]) for e in mesh.edges]` (already
  built for `neighbors`).
- `looseness_preservation(authored_abs, fitted_abs, loose_fraction_of=diag)`
  where `authored_abs = [abs(s) for s in standoff]`,
  `fitted_abs = surface_standoffs(fitted_world, target_ctx)`, and `diag` is
  the target bbox diagonal (`conform._bbox_diagonal(target_ctx.positions)`).

Return `ConformReport(info, edge_distortion_result, looseness_result)`.

### 1.5 Operator surfacing

- `OT_conform.execute`: report `.info` as today (INFO). If
  `report.edge_distortion.distorted_fraction > MAX_DISTORTED_FRACTION`
  **or** (`report.looseness is not None` and
  `report.looseness < MIN_LOOSENESS_RATIO`), also emit a `{'WARNING'}`
  naming the blown metric and its value. Never `CANCELLED` on quality.
- `OT_batch_conform.execute`: count garments that tripped a warning and fold
  `"N with quality warnings"` into the summary line.

### 1.6 Tests (TDD, fast synthetic suite)

- `test_conform.py`: `surface_standoffs` on a tube returns ~radius-distance.
- New `test_conform_quality.py` (or extend `test_batch_conform.py`):
  - a clean concentric-tube conform → `distorted_fraction ≈ 0`,
    `looseness` preserved, no warning path triggered;
  - a deliberately-distorted target → `distorted_fraction` over ceiling.
- Assertions read the `ConformReport` fields directly (the payoff of §1.1).

### 1.7 Error handling / edges

- `looseness` is `None` for a tight garment (no loose region) — the WARNING
  condition guards on `is not None`, so a tight fit is never falsely warned.
- Metric computation must not break a successful bake: it runs after the
  shape key is written, on data already validated for length.

---

## 2. Layer 1 — adversarial-synthetic integration (FOLLOW-ON CARD)

Operator-level: drives the whole `run_conform` on synthetic geometry chosen
to provoke failures, asserting on the §1 `ConformReport`. Stays in the fast
suite (seconds, checked-in-safe). Tests set `obj.sculpt_tool.target_body`
etc. directly (the `test_batch_conform` pattern).

New builders in `tests/common.py`:
- **Rim tube** — garment taller than target so vertices project off the open
  rim → assert `distorted_fraction` under ceiling (attacks §2.2 of the
  review: the case the current tubes are built to avoid).
- **Layered** — two concentric garment tubes over one target (`Top`/
  `pasties`) → neither collapses onto the other or the body.
- **Asymmetric target** — off-center / elliptical body (correspondence
  ambiguity) → no local scatter spike.
- **Anti-balloon regression** — a case that ballooned under the old
  collision+smoothing loop → asserts it stays clean now (regression lock on
  the restart's central claim).

## 3. Layer 2 — real-corpus acceptance gate (FOLLOW-ON CARD)

New `tests/acceptance_corpus.py`, **not** discovered by `run_tests.py`
(named outside `test_*.py`, or explicitly excluded), with its own
`blender --background --factory-startup --python tests/acceptance_corpus.py`
entry — gated the way the removed `perf.py` was.

- Loads the real Tech Set pieces (`Top`, `pasties`, `pants`) and the Venus /
  Egirl bases from `Test_Items/` (gitignored third-party art).
- Runs `op_conform` (or `run_conform`) per piece; asserts
  `distorted_fraction < τ` and `looseness ≈ 1` on the loose pieces.
- If the corpus is absent, skips with a clear message rather than failing.
- Becomes a **required** step in the Builder's pre-merge checklist.

**Threshold calibration loop.** The §1.3 constants (`0.05`, `0.4`) are
provisional. Layer 2's first run yields baseline numbers on real pieces; set
τ from those and feed the real values back into the `quality.py` constants,
so Layer 0's WARNING and Layer 2's gate share one calibrated source.

---

## 4. Process rule (Bear PR Process)

Extend the standing "every quantitative claim ships with a reproducing
script" rule: **every acceptance claim — authored identity preserved on the
real corpus — ships with an asserted corpus test in the merge gate, not an
eyeballed render.** Renders stay a *seeing* tool, not a merge gate.

## 5. Sequencing

1. **Layer 0** (this plan) — prerequisite; gives everything above unit
   something real to assert on.
2. **Layer 1** card — depends on Layer 0's `ConformReport`.
3. **Layer 2** card — depends on Layer 0; calibrates its thresholds.

`TESTING_STRATEGY.md` §6 gaps (orphaned rim-relax, fictional e2e docstring,
stale harness references to deleted `test_solver`/`test_collision`/`perf`)
are tracked as separate Backlog cards, out of scope here.
