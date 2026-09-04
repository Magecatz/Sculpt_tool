# Testing Strategy — Why Green ≠ Working, and How to Fix It

Status: **Tech Lead review (2026-09-03).** Reviews the suite as it stands
after the Direction-B restart (`op_conform` / `core.conform` in place) and
proposes the missing layers. Grounded in a full run of the suite and a
read of every `tests/test_*.py`, `sculpt_tool/operators/op_conform.py`, and
`sculpt_tool/core/quality.py`.

---

## 0. TL;DR

We are "feature complete" with a **green** suite — verified, not assumed:

```
blender --background --factory-startup --python tests/run_tests.py
Ran 91 tests in 14.102s
OK
```

…and the tool still produces broken sculpts. That is not a contradiction.
**The pass/fail gate and the actual quality bar are two disjoint things that
never touch.** The suite proves the conform math is correct on idealized
shapes that never fail; the product breaks on real shapes the suite never
runs. Making CI green again would not have caught a single one of the
failures in `RESTART_SCOPE.md`.

The fix is not "more unit tests." It is adding the two missing pyramid
layers (integration and real-corpus acceptance) and **closing the loop so
the acceptance criteria live in the product, not only in a test file.**

---

## 1. What the suite is today

91 tests, all unit tests, all on small synthetic meshes built in
`tests/common.py` (grids, tubes, valleys, toy armatures). By file:

| File | Tests | Covers |
|---|---:|---|
| `test_rig_map.py` | 17 | Canonical bone map across naming conventions |
| `test_rig.py` | 16 | Rig / deforming-armature detection |
| `test_conform.py` | 12 | Direction-B conform math on concentric tubes |
| `test_quality.py` | 8 | `edge_distortion` / `looseness_preservation` metrics |
| `test_smoothing.py` | 8 | Pin blend, boundary graded sweep, tube shrinkage |
| `test_placement.py` | 7 | Placement spine (position + rotation + scale) |
| `test_geometry.py` | 5 | BVH / evaluated-mesh / triangle-frame helpers |
| `test_pose.py` | 5 | `compute_bone_placements` |
| `test_alignment.py` | 4 | Alignment guard thresholds |
| `test_boundary.py` | 4 | Open-edge detection + rim relax (unit only) |
| `test_registration.py` | 3 | Add-on class registration |
| `test_batch_conform.py` | 2 | Batch orchestration over `run_conform` |

The base of the pyramid is genuinely good. The rig / rig-map / placement
coverage (45 tests) is thorough and the conform-math tests are clean. **The
problem is not test quality. It is test scope.**

---

## 2. Why green cannot catch what is breaking

Four independent structural reasons, each verified against the tree.

### 2.1 No test ever runs a real garment

`tests/common.py` states it outright: every builder makes "small, synthetic,
checked-in-safe meshes … none of this touches `Test_Items/`." A search for
`.fbx` / `import_scene` across `tests/` finds only a bone-name string and
that disclaimer. Every failure that drove the restart — the `Top` ballooning
over the chest, the cross-creator girth errors — was found in `renders/`
experiments on the real corpus, which are **eyeballed images, not asserted
tests** (`renders/` contains zero `assert` and computes zero quality
metrics). The corpus never reaches the gate.

### 2.2 The tests are built to avoid the regimes that fail

This is the sharpest point. `tests/test_conform.py` makes the source/target
tubes deliberately *taller* than the garment

> "so every garment vertex projects radially (**never off a rim**)"

Open rims (necklines, hems, cuffs) are the **#1 failure risk** called out in
`RESTART_SCOPE.md` §7 for a bare projection. The suite's synthetic geometry
is chosen precisely so the hard case cannot occur. Concentric tubes also
give an analytically exact answer, so correspondence is never ambiguous —
but unstable nearest-target correspondence on a real body is the documented
root cause of the balloon (`RESTART_SCOPE.md` §1). The tests exercise the
one geometry where the mechanism cannot misbehave.

### 2.3 The metrics that would catch the failure are wired into nothing

`sculpt_tool/core/quality.py` defines exactly the right acceptance signals:

- `edge_distortion` → local stretch / shrink / scatter (the blob and the
  shrink-wrap-flat collapse).
- `looseness_preservation` → whether a loose panel kept its standoff or got
  sucked onto the body.

A search for these symbols across `sculpt_tool/` returns **`quality.py` and
its unit test, and nothing else.** They are computed nowhere in the product.
`op_conform.run_conform` places → measures standoff → projects → bakes →
reports *vertex count and standoff mode*. It never evaluates its own output.

> **A ballooned garment bakes into the `Fitted` shape key and the operator
> reports success.** There is no quality gate anywhere in the runtime path.

The one asset most able to catch the failure is dead code outside its own
unit test.

### 2.4 The rim fix is orphaned, and its e2e test is fictional

`core.smoothing.relax_boundary_positions` (straighten a spiky rim) is
unit-tested, but **no operator calls it** — `run_conform` has no boundary
pass at all. And `tests/test_boundary.py`'s docstring advertises

> "an end-to-end check that a garment fit onto a bumpy target comes out with
> a smoother open edge"

…which **does not exist in the file.** All four tests are synthetic
detection / relax units. So the flagged rim risk is unhandled in the product
*and* has no end-to-end coverage, while the suite's own documentation claims
otherwise.

### 2.5 Consequence

Layer the four together: the gate runs the mechanism only on shapes where
the mechanism is provably correct, with no assertion on the metrics that
define "good," on none of the real assets, avoiding the one geometry most
likely to break. Green is an accurate statement about a space that excludes
every known failure. That is the whole of "feature complete but broken."

---

## 3. Keep list (do not throw this out)

- **Placement-spine coverage** — `test_rig`, `test_rig_map`, `test_placement`
  (45 tests). This layer works and the tests prove it. Untouched.
- **Conform-math unit tests** — correct and valuable *as a base layer*. Keep
  them; they just are not the whole pyramid.
- **The `quality.py` metrics themselves** — the right acceptance signals.
  They are not wrong, they are unplugged. Plugging them in is §4.0.

The restart's instinct to build pure-logic core modules testable outside
Blender is sound and should continue. The gap is the layers *above* unit.

---

## 4. Proposed testing plan

Ordered by leverage. **§4.0 + §4.2 are the highest-value pair** — they
convert `quality.py` from dead code into the gate we are missing and add the
one test that would have gone red on the balloon.

### 4.0 Wire the metrics into `run_conform` (product change — prerequisite)

Have `run_conform` compute `edge_distortion` and `looseness_preservation`
on its own fitted output and (a) include them in the returned info / operator
report, and (b) optionally emit a `WARNING` (or refuse, behind a setting)
when a gate threshold is blown. This makes the acceptance criteria real at
runtime and gives every test above unit something concrete to assert on.
Everything else in the plan depends on this existing.

### 4.1 Integration layer — operator-level, adversarial-synthetic (fast, default gate)

Run the *whole* `run_conform` end to end on synthetic geometry chosen to
**provoke** the failures, asserting on the §4.0 metrics rather than on vertex
count. Still Blender-headless, still checked-in-safe, still seconds to run.

- **Rim tube** — garment taller than the target so vertices project off the
  open rim → assert `distorted_fraction` stays under ceiling (guards §2.2).
- **Layered garments** — two concentric garment tubes over one target (the
  `Top` / `pasties` case) → neither collapses onto the other or onto the body.
- **Asymmetric / off-center target** — introduces correspondence ambiguity →
  assert no local scatter spike.
- **Anti-balloon baseline** — a case that ballooned under the old
  collision+smoothing loop → assert it no longer does (regression lock on the
  restart's central claim).

### 4.2 Acceptance layer — real corpus "balloon gate" (opt-in module, pre-merge)

A checked-in test that loads the real Tech Set pieces (`Top`, `pasties`,
`pants`) from `Test_Items/`, runs `op_conform` onto Venus / Egirl, and
asserts:

- `edge_distortion.distorted_fraction < τ` (identity preserved), and
- `looseness_preservation ≈ 1` on the loose pieces.

**This is the single test that would have gone red on the balloon.** The
corpus is gitignored third-party art, so this cannot live in the fast suite —
gate it the way `perf.py` is gated (its own `blender --background --python`
entry, skipped by `run_tests.py`), but make running it a **required** step in
the Builder's pre-merge checklist, not an optional afterthought. If the
corpus is absent the module skips with a clear message rather than failing.

### 4.3 Golden / characterization snapshots

Once §4.2 exists, snapshot the metric tuple per `(garment, target)` pair and
fail on regression beyond tolerance. Cheap early warning against silent
quality drift as the optional-polish stages (`RESTART_SCOPE.md` P4) come and
go.

---

## 5. Coverage targets

| Layer | Today | Target |
|---|---:|---|
| Unit — mechanism / math | ~91, strong | keep as-is |
| Integration — operator + metric asserts, adversarial-synthetic | **0** | rim, layering, asymmetry, anti-balloon (§4.1) |
| Acceptance — real corpus, metric-gated | **0** | Tech Set 5-piece → Venus / Egirl (§4.2) |
| Product self-check — metrics computed in `run_conform` | **0** | every conform reports its own quality (§4.0) |

The shape to aim for is unchanged at the base and grown at the top: keep the
fast unit suite as the inner-loop gate, add a small adversarial integration
band, and cap it with a real-corpus acceptance gate that runs before merge.

---

## 6. Gaps that are also bugs

Surfaced during this review; each is worth its own Backlog card.

- **Orphaned rim relax** — `relax_boundary_positions` is unwired into any
  operator (§2.4). Either wire it into `run_conform` behind the acceptance
  gate, or delete it; right now it is untested-in-context dead weight.
- **Fictional e2e docstring** — `test_boundary.py` documents an end-to-end
  check it does not contain (§2.4). Fix the doc or add the test.
- **Stale harness scaffolding** — `run_tests.py` and `common.py` reference
  `test_solver.py`, `test_collision.py`, and `perf.py`, all removed in the
  restart. Dead references in the test harness erode trust in "green."

None of these fail CI. That is the point.

---

## 7. Process rule (Bear PR Process)

The standing rule in `ARCHITECTURE.md` — *every quantitative claim added to
the docs ships with a checked-in script that reproduces it* — is good, but it
was applied to **synthetic** claims and stops at the fast suite. Extend it:

> **Every acceptance claim — "the garment keeps its authored identity on the
> real corpus" — ships with an asserted corpus test in the merge gate, not an
> eyeballed render.**

Renders stay useful for *seeing* what happened. They do not get to be the
thing that decides whether a change is allowed to merge. That one change is
what stops "feature complete but broken" from recurring.
