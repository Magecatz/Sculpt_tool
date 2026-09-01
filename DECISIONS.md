# Sculpt Tool — Decisions & Fix History

This is the fix-narrative counterpart to `ARCHITECTURE.md`. That
document's section 7 is a compact, current-state risk table; this file
holds the measurements, rejected approaches, and full write-ups behind
each row — appended to by the Architect after each future card, in
roughly chronological order. Nothing here is deleted once a residual is
further reduced or a rejected approach is superseded; corrections are
appended, not overwritten, the same way section 7 itself used to grow.

This file was created by restructuring card `816e075c` (2026-08-31),
which moved section 7's narrative content here essentially unchanged and
replaced section 7 itself with a status table. See that table for
current status; this file is the "why" and "how measured" behind it.

---

## 1. Collision resolution: tunneling and concave push-out direction

**Card `c9ff95a5-6269-4c82-8789-08113a9dc9d3`** — "Collision resolution's
nearest-point inside/outside test has blind spots on deep tunneling and
concave regions." Split into a prioritized half (tunneling, shipped
first) and a deferred half (concave push-out direction, its own card
below). Both closed; Deployed.

### 1a. Tunneling fix (PR #7, `fix/collision-tunneling`)

A vertex that tunnels all the way through thin geometry (e.g.
wrist/ankle) was left in place pre-fix. The fix does not make the
inside/outside test on the vertex's own final position smarter — a
vertex sitting well past the far wall of a thin slab is genuinely,
correctly outside the solid by any point-containment test (nearest-point
sign, ray-parity, winding number alike), so no such test can flag it
without being wrong. Instead, `core/solver.py`'s `project_mode_a`/
`project_mode_b` return the per-vertex anchor point (and its normal) on
the target body's surface that the binding offset was actually measured
from — the surface the vertex is meant to be hugging, independent of how
far the offset then carried it — via a `ProjectionResult` dataclass,
instead of discarding it after computing the offset.
`resolve_collisions(fitted_positions, anchor_positions, anchor_normals,
target_body_obj, collision_margin)` uses that anchor for a second,
bounded `BVHTree.ray_cast` per vertex — only when the existing
nearest-point test didn't already flag it — checking whether the
straight segment from anchor to fitted position crosses the target
body's own surface at all. That can only happen if the offset carried
the vertex through solid material, which is exactly what "tunneled"
means; a vertex caught this way is pushed back to `anchor_position +
anchor_normal * collision_margin` (the near surface) rather than
whatever the nearest-point query would find on the far side. One extra
bounded ray-cast per vertex, same single BVH build per call as before —
no meaningful perf regression at the scales this pipeline targets
(verified: ~30k vertices against a ~65k-triangle body in ~0.25s).

Known limitation, accepted as out of scope: on sufficiently
convoluted/bumpy geometry the anchor-to-fitted segment can graze an
unrelated nearby fold of the body and produce a false-positive tunneling
detection — the same class of blind spot as the concave push-out-
direction issue below, not a new one.

Side effect worth flagging for smoothing work (not a defect): because
the corrected vertex is snapped to `anchor_position + anchor_normal *
collision_margin`, a pure normal-offset point, its tangential/bitangent
offset collapses to zero — the correct, intentional trade-off for
collision safety, but it makes a tunnel-corrected vertex a categorically
different kind of displacement (larger, differently shaped) than the
ordinary sub-margin jitter the rest of the pipeline produces. Re-verified
clean against the smoothing pass's internal-loop change (below): a
thin-geometry tunneling-correction scenario stays finite with bounded
edge lengths through smoothing, no blow-up.

### 1b. Concave push-out direction (PR #15, `fix/concave-collision-residual`, card `1e252575`)

A full-corpus run against real garments (22 meshes across 9 FBX files)
measured the residual this caused: 9 of 22 ended with 50+ vertices still
penetrating the body after fit, concentrated in concave/self-occluding
regions (straps, hoods, layered pieces, armpit/crotch folds); the other
13 (simple, mostly-convex garments) were the ones that measurement did
not put on that failing-9 list — **not** uniformly zero, as an earlier,
unverified version of this document claimed. Most of the 13 sit at or
near 0, but a few sit well above it, including above the 50-vertex mark
itself. Exact pre-fix residuals for all 13 are reproducible via
`tests/corpus_repro.py`'s `CLEAN_GARMENTS` table rather than restated
here as fixed numbers, since they can drift if the corpus changes.

Root cause: `resolve_collisions()` decided a push-out *direction* from
the locally-nearest triangle's own face normal, which in a concave
pocket can belong to a different fold of the surface than the one the
vertex is actually meant to clear, and so can point sideways or back
into the body. Fixed three ways together (Architect consult):

- **Push-out normal source** — pushes along `anchor_normal`
  (`ProjectionResult.anchor_normals`, the same anchor the tunneling fix
  uses) instead of the locally-nearest triangle's face normal.
  `hit_location` (the nearest surface point) is still the position the
  push originates from — only the direction source changed.
- **Bounded re-query loop** — `_push_out_locally()` re-runs the
  inside/outside test after each push, up to 3 attempts, falling back to
  `anchor_position + anchor_normal * collision_margin` if still inside
  after that many. Every flagged vertex now resolves to a definite,
  correct-side answer in bounded time. The bound is small deliberately:
  collision resolution is the cheap side of the pipeline relative to
  smoothing (~0.25s vs. ~4.73s at comparable scale — see section 2
  below), and only vertices actually flagged pay for extra attempts.
- **Post-smoothing collision re-pass** — smoothing has no notion of the
  target body and can drag an already-cleared vertex back into it;
  `operators/op_fit.py` now runs `resolve_collisions()` a second time on
  smoothing's output, reusing the original projection's anchors, when
  both collision resolution and smoothing are enabled.

Re-measured on the real corpus via `tests/corpus_repro.py` (opt-in,
`Test_Items/`-dependent, matching `perf.py`'s pattern; also runs a real
in-process A/B against the pre-fix algorithm and an independent
ray-parity inside/outside test rather than `collision.py`'s own test).
`tests/test_collision.py`'s synthetic concave-pocket regression is the
fast-suite coverage (the real `Test_Items/` assets are gitignored
third-party meshes and cannot be checked in, so `corpus_repro.py` stays
opt-in rather than part of the gate).

**Corrected claim, replacing this card's original unqualified "all nine
dropped substantially"** (sent back on review for being asserted with no
regenerable numbers): **seven of the nine measurably dropped
substantially** (old-algorithm-after → new-algorithm-after residual
count: Bunny Suit 251→63, Socks & Harness 423→204, cybercroptop Body
336→162, Straps by Vinuzhka 190→38, Sweater 156→45, Zip Up 193→136, Hood
Crop 92→42 — roughly −30% to −80% each). The remaining two behave
differently, investigated directly:

- **pants by Vinuzhka: 233→225, a real but small improvement (~−3%).**
  Confirmed every one of the 225 residual vertices *was* pushed by
  `resolve_collisions()` — the bounded re-query/fallback ran, just didn't
  clear the independent parity test's stricter global standard on this
  mesh's denser concave folds. This is the "not a complete fix for every
  conceivable concave topology" limit (below) actually showing up on a
  real asset, not a new defect.
- **Cube.012 (Lingerie): 332→332, exactly unchanged.** Confirmed all 332
  residual vertices were *never* flagged as interpenetrating by
  `resolve_collisions()`'s own local nearest-point/normal-sign test under
  EITHER algorithm version — this fix only changes push-out behavior for
  a vertex already flagged as inside, so it is structurally unable to
  affect a vertex neither version's local test ever flags. Root-caused to
  part of this asset's raw fitted geometry (before any collision pass)
  landing implausibly far from the body — a Mode A binding/drape artifact
  on this mesh's decorative geometry, not a collision-resolution issue —
  orthogonal to this fix and out of its scope. **Not currently tracked by
  its own card** — flagged here for whoever picks up collision resolution
  next.

This card's own review cycle produced two independent real-corpus
measurements of these same two garments that *disagreed with each
other* (one found both improved, the other found pants roughly unchanged
and Cube.012 got worse); `tests/corpus_repro.py`'s numbers above are a
third, checked-in-and-regenerable measurement, and confirm Cube.012 is
bit-for-bit identical before and after this fix, not worse.

**Not claimed as a complete fix for every conceivable concave topology:**
the bounded re-query/fallback guarantees a correct-side answer against
`resolve_collisions()`'s own local test on the first local push, not a
minimum-margin-satisfying one against every possible independent
measurement — extremely convoluted geometry (self-intersecting folds
nested several layers deep, or a global test disagreeing with the local
one) could still need more than the fallback's single anchor-snap.

---

## 2. Smoothing: curvature-driven shrinkage fix (internal sub-sweeps)

**Card `afefc553` (PR #9, `feature/smoothing-pass`)**, corrected by
**PR #10/#12 (doc-only)**. Deployed.

`core/smoothing.py`'s `relax()` runs one damped Laplacian step followed
by `_EDGE_CORRECTION_SUBSTEPS` (16) internal Gauss-Seidel sub-sweeps over
all edges, pulling each back toward its original (base-mesh) length, per
`smoothing_iterations`. A single sweep per iteration (found during this
card's own Tester/Architect review, before merge) left enough residual
edge-length error that the next iteration's Laplacian step compounded a
fresh contraction on top of it: on a completely clean, unperturbed,
unpinned cylindrical/tube-shaped garment (zero noise, zero pins — the
textbook case section 1 of ARCHITECTURE.md's anti-shrinkwrap goal exists
to protect) this produced ~9% radius shrinkage after 10
`smoothing_iterations`, a straightforward regression against that goal.

Looping the edge-length correction internally fixed this: on a synthetic
tube repro (32-segment, 20-ring cylinder, zero noise, zero pins), radius
shrinkage at 10 iterations dropped from ~9% to ~0.58%, and at 40
iterations it was ~0.575% — confirming the residual plateaus rather than
continuing to compound as `smoothing_iterations` grows. (A separate
tuning pass on a different synthetic mesh measured ~0.2% at the same
sub-sweep count — the exact residual is mesh-dependent, but the
qualitative behavior — low-single-digit-percent or better,
non-compounding — matches.) `relax(iterations=...)`'s public signature
and semantics are unchanged: it still counts outer Laplacian+constraint
iterations exactly as before, and a fully-pinned vertex
(`pin_weight == 1.0`) is still exactly untouched. Regression coverage:
`tests/test_smoothing.py`'s tube-shrinkage test (also the harness card's
seed test guarding the `16` constant).

**Perf claim correction (PR #10/#12, doc-only, card `4da4de1a`):** this
document originally claimed the ~16x increase in inner-loop work was
"cheap relative to the pipeline's per-vertex BVH collision work." That
was measured wrong. Actual numbers on a ~33k-vertex synthetic tube at
`smoothing_iterations=10`: ~4.73s with this fix, versus ~0.50s before
it. Measured against the collision pass's own documented figure at
comparable scale (~30k vertices against a ~65k-triangle body in ~0.25s),
the fixed smoothing pass is roughly **19x more expensive than
collision**, not cheap relative to it — now the pipeline's dominant
per-target cost. This cost is linear in batch collection size (scales
directly with target-body count in a real Batch run) and had not been
measured at that scale as of this writing.

Gauss-Seidel sub-sweeps (each edge's correction applied immediately, so
later edges in the same sweep see earlier ones) are the reason a naive
`foreach_get`/`foreach_set` NumPy rewrite cannot vectorize this step —
the sequential dependency is what the curvature-shrink fix's convergence
behavior depends on. Mitigation candidates, none yet validated:

- the adaptive/early-exit sub-sweep variant, Backlog card `5b232224`
  (stop once residual edge-length error falls under some threshold
  instead of always running all 16);
- exposing sub-sweep count as a batch-mode quality/speed trade-off;
- **graph/edge-colored Gauss-Seidel** — partitioning edges into colors
  where no two edges in a color share a vertex, then vectorizing within
  each color. The standard way to parallelize PBD distance constraints,
  and it *would* let NumPy attack the dominant cost. Changes sweep
  ordering, so it needs the tube-shrinkage validation above re-run before
  adoption — "needs re-validation" is not the same as "impossible," and
  this option should not be dismissed on the strength of the sequential-
  dependency argument alone (which only rules out the naive rewrite).

This was fully re-verified clean against the collision pass's
anchor-based tunneling correction: a vertex snapped by `anchor_position +
anchor_normal * collision_margin` next to neighbors that keep their full
authored offset is a genuinely larger, differently-shaped discontinuity
than ordinary projection/collision jitter, and the harder-converging
edge-length constraint still keeps a thin-geometry tunneling-correction
scenario finite with bounded edge lengths through smoothing, no blow-up.
A garment/body pairing that triggers tunneling correction on many
neighboring vertices at once may still show a locally tauter or
slower-to-relax patch near the correction compared to ordinary noise
elsewhere — not a bug, not solved further.

---

## 3. Smoothing: pin-weight blend linearization + graded-boundary residual

**Card `1638a2d4` (PR #11, `fix/pin-weight-linear-blend`)** — closed,
Deployed. Follow-on residual tracked by **card `8432ee45`** (partial fix
landed, PR #16, Deployed) and **Backlog card `e893bfdd`** (further
structural redesign, still open — see section 7 in ARCHITECTURE.md).

### 3a. The bug (`1638a2d4`)

ARCHITECTURE.md section 6 describes pin weight as blending a vertex
between "fully solved" and "rigid, unchanged." That was accurate for the
damped Laplacian step alone (which scales each vertex's own displacement
directly by `(1 - pin_weight)`) but not for the combination with the
edge-length correction sub-sweeps: `_edge_length_step()` distributed each
edge's correction between its two endpoints by free-weight-sharing
(`free_a / (free_a + free_b)`, `free_x = 1 - pin_weight_x`) rather than
applying `(1 - pin_weight)` to each vertex's own share independently. In
aggregate this pulled a partially-pinned vertex much closer to unpinned
behavior than its weight alone suggested — a vertex at
`pin_weight = 0.5` moved roughly 0.76x-0.96x of an unpinned vertex's
displacement, not the ~0.5x the section 6 description implied. Only
`pin_weight == 0.0` and `pin_weight == 1.0` behaved as documented.

**Fix:** pin weighting moved out of the per-edge/per-vertex math
entirely and into `relax()`'s outer loop. Each outer iteration computes
an entirely unpinned "fully solved" candidate (the same
`_laplacian_step` + `_edge_length_step` internals, called with every pin
weight forced to `0.0`), then blends every vertex between its own
pre-iteration position and that candidate by its own `(1 - pin_weight)`
— `new = old * pin + candidate * (1 - pin)`. This is a direct
implementation of the section 6 language rather than an approximation of
it. `_laplacian_step`/`_edge_length_step` themselves are unchanged (still
pin-aware, still correct standalone building blocks); `relax()` simply no
longer calls them with the real per-vertex pin array (until the partial
fix in 3c below, which reintroduces it in one specific place).

**Rejected intermediate approach:** scaling `_edge_length_step`'s
per-edge weight-sharing by each vertex's own `(1 - pin_weight)` directly
(splitting each edge's correction pool 50/50 between endpoints, then
damping each endpoint's own half by its own free weight) —
Architect-recommended as the natural mirror of the Laplacian step's
self-referential scaling. Correct for a single isolated step given fixed
neighbor positions, but empirically produced a non-linear and even
non-monotonic aggregate blend across multiple outer iterations: on a
disconnected-chain test isolating a single pinned vertex from cross-talk,
10 outer iterations measured `pin_weight=0.25` moving *more* than
`pin_weight=0.5` (ratios 1.16 and 1.17 respectively against an unpinned
baseline — both **above** the unpinned vertex's own displacement),
because a free neighbor's correction share was capped independent of the
pinned vertex's own resistance, letting the neighbor "wind up" against
the slower-moving pinned vertex over repeated iterations faster than the
reduced per-step correction could cancel. The outer-iteration blend
adopted instead avoids this because pin weighting never participates in
the per-edge/per-neighbor math at all.

**Measured on the fix** (disconnected-chain and 2D-grid test meshes,
`smoothing_iterations` 1-10):

- **Isolated pinned vertex:** `pin_weight` 0.25/0.5/0.75 moved
  ~0.70-0.91x / ~0.44-0.80x / ~0.21-0.60x of an otherwise-identical
  unpinned vertex's displacement across 1-10 outer iterations — exactly
  linear at 1 iteration (0.75/0.50/0.25 to 4 decimal places), drifting
  somewhat further from exact as iterations and neighbor feedback
  accumulate, but always monotonic in pin weight, and bounded by the
  unpinned baseline in every isolated-vertex configuration tested (see
  3b below for a configuration where this bound does not hold).
- **Continuous pinned band** (a realistic `Pin_Hem`-style selection where
  every pinned vertex's neighbors are also pinned): `pin_weight`
  0.25/0.5/0.75 measured ~0.84x/~0.68x/~0.47x at 10 outer iterations —
  still monotonic and bounded (again, see 3b), but a visibly softer blend
  than an isolated pin, since neighboring pinned vertices' unpinned
  candidates reinforce each other's advancement iteration over iteration.
  Still a large improvement over the pre-fix 0.76x-0.96x near-binary
  plateau.
- **Boundaries preserved exactly:** `pin_weight == 1.0` still bit-for-bit
  zero movement (including through overlapping-`Pin_*`-group
  sum-and-clamp to exactly 1.0); `pin_weight == 0.0` bit-for-bit
  identical to pre-fix behavior.
- **Curvature-shrink fix unaffected:** zero-pin tube/cylinder shrinkage
  re-test measured ~0.56% at 10 iterations and ~0.56% at 40 (matching
  section 2 above within measurement noise) — expected, since with all
  pins at `0.0` the candidate computation is exactly the pre-fix code
  path.

### 3b. Known residual found on this same card: graded-boundary overshoot

**A graded pin-weight region near a mesh boundary, combined with input
position noise, can exceed the unpinned baseline.** The isolated-pin and
continuous-band bounds above hold in every configuration tested, but
neither covers a *graded* pin region (neighboring vertices at different
pin weights) sitting near the mesh's own free boundary with some
vertex-position jitter present. Not a contrived corner case — a weight
feathering out toward zero at a garment's free edge, combined with the
ordinary positional noise a real post-collision-resolution mesh already
has, is close to the literal definition of a real `Pin_Hem`/`Pin_Cuff`
selection.

Tester found one counterexample (7x7 grid, radial graded band, one seed,
15 outer iterations): a `pin_weight = 0.25` vertex moved ~6% more than
the most-displaced `pin_weight = 0.0` vertex in the same run. Reviewer
independently reproduced this on a broader sweep (flat-panel and
cylindrical hem-ring topologies, varying grid size/grading
width/jitter amplitude/seed/iteration count): the overshoot appears in
roughly 3-4% of graded-boundary-plus-jitter configurations tried (0/24
with zero jitter — noise is necessary to trigger it; it also vanishes on
interior, non-boundary-adjacent graded regions), and can be considerably
larger than the Tester's single data point — up to ~46% on a flat panel
and ~32% on a cylindrical hem-ring. It does not grow monotonically with
iteration count (e.g. 26%/46%/11% overshoot at 10/15/20 iterations on the
same seed).

Likely cause: each outer iteration's "fully unpinned candidate" is
computed from every vertex's own *current*, already partially-blended
position (and its neighbors' likewise partially-blended positions), not
from a truly independent, fully-relaxed simulation — at a pin-weight
gradient the edge-length correction can assume more elasticity in a
lagging neighbor than that neighbor will actually exhibit once its own
blend is applied, producing a genuine (not measurement-noise) transient
overshoot.

For context: the identical adversarial sweep run against the pre-fix
code fails far more often (48% of configurations vs. 3.9% here) and far
more severely (worst-case 218% overshoot vs. 46% here) — so despite this
residual, the fix is a substantial improvement over prior behavior even
in the specific scenario that exposes it. Tightening this further looks
like it needs a different candidate-computation strategy (one that
doesn't let an un-relaxed neighbor's lag leak into the correction math at
a pin gradient), not a small tweak to the current approach. Tracked as
bug card `8432ee45`.

### 3c. Partial fix (same card `8432ee45`, PR #16, `fix/pin-boundary-overshoot`)

Per an Architect-directed cheap experiment (try this before any
structural redesign, since every structural fix candidate costs roughly
2x smoothing time or loses pin anchoring, for a residual that only
affected 3-4% of an adversarial sweep and defaults off), `relax()` now
passes the REAL per-vertex pin array to `_edge_length_step` for the
outer-iteration candidate computation, instead of an all-`0.0` array
(`_laplacian_step` still gets an all-`0.0` array — only the edge-length
correction's mass-weighted split changed). This directly targets the
likely cause above: `_edge_length_step` already splits each edge's
length correction between its two endpoints by
`free_a / (free_a + free_b)`; feeding it the real pin weights means a
neighbor's own resistance to movement is visible to that split, instead
of every neighbor being treated as fully free regardless of how pinned
it actually is. No per-call cost change; `pin_weight == 0.0`/`== 1.0`
boundaries unaffected (verified:
`tests/test_smoothing.py::PinWeightBoundaryTest` stays green).

**Measured on a fresh, wider sweep** (needed widening because the fix
reduced the overshoot enough that the original grid stopped finding a
representative worst case) — **before** this fix, the wider grid's
worst-case ratio was ~1.61x (partially-pinned vertex moving 61% more than
the most-displaced unpinned one), ~52% of swept configurations showing
at least some overshoot; **after**, worst case was ~1.19x, well under
half as many configurations affected on that one topology.

**This 7x7-grid-only figure did not generalize (Reviewer rejection,
first re-review pass).** A broader Reviewer sweep (larger flat grids, a
cylindrical hem-ring) found this fix reduced worst-case overshoot
MAGNITUDE (1.81x → 1.28x in that sweep) but not INCIDENCE — incidence
rose roughly 20-35x on wider topologies even as individual-occurrence
magnitude improved, and a plain 12x12 grid alone exceeded the
7x7-tuned 1.22 test ceiling with no exotic topology needed. Verdict
(Architect-concurred): a topology-specific lever-tweak that redistributed
the problem rather than converging on it.

**Re-verified honestly, on three topologies**
(`tests/test_smoothing.py::GradedBoundaryAdversarialSweepTest`, widened
to sweep a 7x7 flat grid, a 12x12 flat grid, and a cylindrical hem-ring —
each with its own ceiling since the three do not converge to the same
worst case): worst-case ratio / incidence is **1.19x / 25.0%** on the
7x7 grid, **1.30x / 25.5%** on the 12x12 grid, and **1.43x / 52.1%** on
the cylindrical hem-ring. Real, substantial improvement over the pre-fix
baseline on every topology (pre-fix was ~1.61x/52% even on the easiest,
7x7 case), but incidence is clearly topology-dependent and highest on
curved geometry — a `Pin_Hem` selection on a sleeve/cuff is exactly the
shape most exposed to this residual.

**The 7x7 ceiling needed one more honesty bump (Reviewer pass 3,
Architect-confirmed non-blocking).** The 1.19x/25.0% figure above (test
ceiling 1.22x/30.0%) came from sweeping `seeds=range(16)` only. An
independent Reviewer re-check found seed 203 on the identical 7x7
topology (values already inside the checked-in sweep's own sets, just a
seed outside `range(16)`) reproducibly measures **1.2350x**, exceeding
that ceiling. Not a new failure mode or a topology the fix doesn't
generalize to — the same topology, same fix, one additional seed grazing
a ceiling that was only ever "the worst of 16 seeds we happened to
check." Folding seed 203 into the checked-in sweep
(`seeds=list(range(16)) + [203]`) and re-measuring gives worst=1.2350x,
incidence=27.7% (113/408); the 7x7 test's ceiling is now **1.26x /
33.0%**, still comfortably below both rejected dual-trajectory
prototypes' numbers below (1.39x-6.75x, 32-94% incidence), so it remains
a meaningful regression guard.

**Separately, incidence roughly doubled overall on an independent
Reviewer sweep, even though worst-case magnitude improved** — using its
own methodology (distinct from the checked-in test's per-topology grid
above), incidence went from ~16.67% pre-fix to ~31.11% post-fix, while
worst-case magnitude dropped from ~1.6441x to ~1.4364x over the same
comparison. Same finding as the first-rejection pass: magnitude and
incidence are two different axes, and this fix trades one for the other
rather than eliminating either — a known, accepted tradeoff of the
shipped single-trajectory design, not a discrepancy between figures.

**Two "dual-trajectory" structural redesigns were prototyped on this
card and rejected**, per an Architect consult, since tightening the fix
further looked like it needed a different candidate-computation strategy
rather than another tweak to the same lever. Both maintained a second
`free` position trajectory that, unlike the shipped fix's `candidate`
(re-derived from `current` every outer iteration), was never blended
back toward the pin-weighted `current` trajectory — on the theory that a
truly independent, never-lagging reference would remove the coupling
mechanism instead of damping its effect. Measured on the same
three-topology sweep:

- **Fully pin-independent** (`_laplacian_step` and `_edge_length_step`
  both always called with an all-`0.0` pin array for `free`): worst ratio
  1.39x / 1.32x / 1.55x, incidence 65.6% / 32.3% / 72.2% on the 7x7 grid
  / 12x12 grid / hem-ring respectively — worse than the shipped fix on
  every topology.
- **Hybrid** (`free`'s `_laplacian_step` call left at all-`0.0`, but its
  `_edge_length_step` call given the real pin array): worst ratio 6.75x /
  5.94x / 3.67x, incidence 93.0% / 93.8% / 85.4% — far worse still, and
  this variant also broke `PinBlendMonotonicityTest` outright (an
  isolated `pin_weight = 0.5` vertex displacing more than both
  `pin_weight = 0.25` and the unpinned baseline, a guarantee that had
  held under every prior design).

**Root cause of both failures (Architect-confirmed, architectural, not a
tuning miss):** neither variant ever resets the persistent `free`
trajectory back toward the pin anchor each outer iteration, the way the
shipped single-trajectory design resets `current` every iteration.
Without that reset, a highly-pinned vertex's `free` position still gets
dragged toward its neighbors' average every iteration by the
always-unpinned `_laplacian_step` call, with nothing bounding the drift —
it compounds across `iterations` instead of plateauing. Any
dual-trajectory variant lacking a per-iteration reset toward the pin
anchor will fail this way regardless of how its edge-length split is
tuned; it is the per-iteration reset itself, not the internal correction
math, that bounds drift in the shipped design.

**Decision (Architect-approved close-out):** no clear win across all
three topologies on either prototype, and one broke a correctness
invariant outright, so no third structural redesign was attempted. The
shipped fix (real pin array into `_edge_length_step`, single trajectory)
remains as landed; both dual-trajectory prototypes are reverted and
documented here (and in `core/smoothing.py`'s docstrings) so a future
attempt does not re-derive the same dead end. The residual is accepted
as a documented limitation, topology-dependent and worst on curved/
hem-adjacent geometry, tracked under `8432ee45` plus Backlog card
`e893bfdd` for any future genuine structural redesign beyond
dual-trajectory.

---

## 4. Binding: bind-time reference geometry frozen (schema v2)

**Card `756f27f5` (PR #18, `claude/highest-priority-card-02c907`)** —
umbrella card, closed and Deployed. Supersedes and closes `089ab86f`
(Mode B stale source-body correspondence) and `1f8e8594` (re-bind reads
its own `Fitted` shape key), and absorbs a third, previously-uncarded
defect in the same family (Part C below). All three shared `storage.py`,
one schema version bump, and the same ARCHITECTURE.md section 2/7
surface.

**The unifying defect:** reference geometry the design assumes is frozen
at bind time was actually read live, with no detection. `project_mode_a`
never touches the source body at fit time — it applies frozen per-vertex
offsets against the target — so Mode A was always correct here; Mode B
and the auto-detect heuristic were the outliers, brought in line with
Mode A's existing design rather than inventing a new principle.

### Part A — Mode B's anchor frozen at bind time (closes `089ab86f`)

Previously, `project_mode_b` in `core/solver.py` reconstructed the
bind-time correspondence point from the source body's *current* mesh via
the stored `triangle_index`/barycentric weights on every fit — a
different situation from the source body being missing/renamed (which
already raised a clear error): if the source body was edited or reshaped
after bind, the fit silently reprojected onto the altered geometry with
no warning that the binding was stale.

Fixed by storing the bind-time anchor directly, in the **source body's
own local object space** (`storage.ATTR_SOURCE_ANCHOR_LOCAL`, a
`FLOAT_VECTOR`/`POINT` mesh attribute), plus the source body's
`matrix_world` at that same bind-time moment
(`storage.PROP_SOURCE_BIND_MATRIX`, an object-level property).
`project_mode_b` now computes `world_anchor = source_bind_matrix @
source_anchor_local[i]` and finds the nearest point to that on the
TARGET body's BVH — no source-mesh read, no source-body object lookup,
at fit time at all. This deletes structure rather than adding it:
`_resolve_source_body` and its "source body missing" error path are gone
from `core/solver.py` entirely (a renamed or deleted source body stops
being a failure mode too, not just an edited one), Mode B fitting no
longer does an extra `to_mesh()` + triangulation of the source body per
fit (i.e. per target in a batch run), and `project_mode_b` is measurably
smaller than before. `triangle_index`/`barycentric` are still computed
and stored at bind time, but are diagnostics only from here on.

### Part B — no output of this add-on may ever be an input to it (closes `1f8e8594`)

Verified empirically under Blender 5.2.1 on real assets (23,153-vert
avatar body, 2,087-vert bodysuit): bind → fit → bind again silently
changed 1,862 of 2,087 stored `sculpt_tool_bind_normal_offset` values,
max delta 0.0332, mean 0.0032 — against a legitimate fit displacement of
max 0.0357 in the same run, so one accidental re-bind injected error of
the same order as the effect being modeled, compounding per cycle, with
the operator reporting `FINISHED` and no warning.

Root cause: binding reads the garment's (Mode A and B alike) and, for
Mode B, the source body's evaluated mesh, and that evaluated mesh
includes the `Fitted` shape key's current contribution whenever one is
present and active — so re-binding after fitting quietly took this
add-on's own prior output as its "original, authored" input.

Fixed in `operators/op_bind.py` (not `core/`, since it needs
`context.view_layer.update()` to make the depsgraph catch up with a
mid-`execute()` mute/unmute, a Blender-context concern `core/`
deliberately stays free of): `_bind_time_evaluation` temporarily mutes
the `Fitted` key block — by name, `storage.FITTED_SHAPE_KEY_NAME` — on
the garment (and the source body, for the same reason, less commonly
triggered) around the bind-time evaluated-mesh read, restoring it after
even if the read raises. Garment-side *modifiers*, and every other shape
key, are left untouched.

Of three directions considered, this is the middle one: "refuse with an
error" would punish the expected iterate-on-fit workflow (re-binding
after fit is a normal thing to want to do — e.g. to update Mode B's
diagnostic triangle/barycentric fields against a since-changed *source*
mesh), and "warn only" would leave a silent wrong result reachable.
Regression coverage: bind → fit → bind now produces bit-identical stored
bind attributes to the first bind (`tests/test_binding_freeze.py`).

**Coverage gap found and closed (Tester pass, same card).** Every Part B
case above bakes the contaminating `Fitted` key onto the *garment* being
re-bound; `_bind_time_evaluation` also mutes it on the *source body*, but
no test exercised that branch — every source body in the suite was a
plain, never-fitted grid, so deleting `source_body_obj` from the
`_bind_time_evaluation` call entirely would still have passed all 41
cases. `tests/test_binding_freeze_source_body_mute.py` closes this: it
manually bakes a `Fitted` key onto a would-be source body (bypassing Fit
entirely, so it guards the general "any pre-existing `Fitted` key block"
case, not just Fit's own output shape), binds a garment against it, and
confirms the stored anchor reflects the source body's Basis geometry.
Suite is 42/42 with this test included. An Architect read of
`operators/op_bind.py` independently confirmed `_bind_time_evaluation` is
the sole bind-time evaluated-mesh read path, so this was a real
test-coverage gap on already-correct code, not a latent bug the test
happened to catch.

### Part C — the Mode A no-Target-Body-set trap (a third member of the same family, not previously carded)

`detect_bind_mode` returned Mode A whenever `target_body_obj is None`
(nothing to compare topology against), and `project_mode_a` only guarded
individual `body_index >= target_vertex_count` — an out-of-range check
that stays silent whenever the eventual target body has the SAME OR MORE
vertices than the source body did, which is exactly the common case.

Verified under 5.2.1: binding with Target Body unset chose Mode A, and
fitting that binding against a 91,691-vert cross-topology target (source
was 23,153) returned `FINISHED` with no error or warning, diverging from
the correct Mode B answer by max 0.0415 / mean 0.0052 — LARGER than the
entire body deformation being modeled (max 0.0288). The panel layout
actively teaches this order: Source Body sits under "Binding," Target
Body under "Fit," below it.

Fixed two ways together: `bind_mode_a` now records the source body's
evaluated vertex count at bind time (`storage.PROP_SOURCE_VERTEX_COUNT`),
and `project_mode_a` refuses outright, before touching any per-vertex
index, if the target body's vertex count doesn't match it (the old
per-index guard remains as defense in depth); and `detect_bind_mode` now
raises rather than defaulting to Mode A when no Target Body is declared,
caught by `operators/op_bind.py` and reported as a normal bind error. A
forced Mode A/B override still bypasses `detect_bind_mode` entirely, per
its own escape hatch, and is unaffected.

### Schema bump and tests

`SCHEMA_VERSION` is now 2. A v1 binding is refused at fit time with a
clear message (`storage.BindingVersionError`, a `ValueError` subclass)
rather than silently misread or falling back to pre-fix v1 behavior.
`tests/test_binding_freeze.py` covers all four acceptance criteria
directly (editing/deleting/renaming source body after bind has no
effect; bind → fit → bind bit-identical; no-Target-Body refuses; a
vertex-count-mismatched Mode A fit refuses) plus the v1-schema-refusal
case. `tests/test_pipeline.py`'s existing Mode B coverage
(`ModeBFitOnceTest`) continues to pass unchanged against the new storage
layout.

---

## 5. Mode A faceless-target regression — fixed, PR #19 merged

**Card `e6763cc5`**, found by Tester while reviewing card `cd0d1569`
(the `core/geometry.py`/`core/pipeline.py::fit_once` extraction).
Regression, not covered by that card's own test suite.

Before that refactor, `core.solver.project_mode_a` only required the
target body to have vertices — Mode A does a direct per-vertex index
lookup and has no notion of faces. `core.solver.project_mode_b`, by
contrast, always required triangulatable faces (BVH-based nearest-
surface projection), and that check is unaffected. After the refactor,
`core.pipeline.fit_once` unconditionally builds a
`core.geometry.TargetContext` up front, before dispatching to either
mode; `TargetContext.build` raises whenever the target has zero faces,
regardless of which mode is about to run — so a Mode A fit against a
target body that has vertices but no faces (e.g. a loose-vertex mesh, or
any object whose faces got stripped) now fails where it used to succeed.
Confirmed with a real repro, git-bisected across the refactor commit.

Fix (`4e05f6b`, PR #19, `fix/mode-a-faceless-target`): lazy
triangles/BVH construction on `TargetContext` — only built when Mode B
or collision resolution actually needs them. Full suite green (48/48)
per the Developer/Tester agents on the card, and independently re-verified
by the Reviewer (48/48) before merge. PR #19 has since merged to `master`
and card `e6763cc5` is Deployed. See ARCHITECTURE.md section 7 (row 3)
for current status.

A follow-on gap was found while verifying this fix and is separately
backlogged: Backlog card `9aeffb26` — `smoothing_iterations > 0` combined
with a faceless target and collision resolution off is not covered by
the new regression tests. This gap is now live on `master` since PR #19
has landed (it was previously moot, pre-merge); still open on the board
as of this writing.

---

## 6. Armature / initial posing: the pipeline has no skeletal stage

**Card `9df4bc00` (To-Do)** — "Tool is not using armature and bones for
initial posing of the article of clothing and as such the tool is
actively doing nothing productive." Filed by the user after a live
run-the-tool-on-real-assets session ("Tool results on clothing/body
combinations," 2026-09-01). This section is the Architect writeup behind
ARCHITECTURE.md section 7 row 18, and an honest calibration of how far
the complaint actually reaches — because part of it is real and part of
it is the frustration of a session that spent a lot of effort chasing
the wrong thing.

### 6a. The finding, grounded in the code

There is **no skeletal logic anywhere in the addon.** `grep -rni
"armature\|bone\|pose\|skin\|deform" sculpt_tool/` returns only Pin-group
vertex-group handling and unrelated prose in docstrings — zero references
to armatures, bones, pose, or skin weights as a deformation input. The
whole pipeline (bind → project → collision → smooth → bake) operates on
**static geometry**: `core/binding.py` records, per garment vertex, a
correspondence + offset against the source body's *evaluated, world-space*
mesh; `core/solver.py` re-projects each garment vertex onto the target
body's *evaluated* surface (Mode A nearest-vertex / Mode B nearest-surface
BVH); collision pushes out of the body; smoothing relaxes. Nothing in that
chain knows a skeleton exists.

Crucially, the tool does not *ignore* pose at the mesh level — it reads
the **evaluated** mesh, so whatever pose an Armature modifier currently
produces is baked into the positions it captures. What it lacks is any
step that *establishes*, *transfers*, or *matches* a pose. It assumes the
garment is already posed to sit on its body (the same unenforced-input-
precondition family as section 7 row 2's overlap gap) and, at fit time,
drapes onto the target body's *current* surface by nearest-surface
correspondence alone.

### 6b. Why nearest-surface projection can't stand in for skinning

Real clothing assets are authored **skinned to an armature**, and the
garment-on-body pose is produced by the armature deform (matched bone
transforms + skin weights), *then* refined by cloth-level fitting. The
reference file the user supplied mid-session (`Example1.blend`) was
exactly this: a single combined `Tech Outfit` mesh plus **two properly
posed armatures** — `Armature` driving the body, `Armature.001` driving
the outfit — with real non-identity bone rotations (Hips/Chest/Shoulder/
Arm/Elbow/Wrist), arms in a relaxed stance rather than a T-pose.

When the garment and target body are in *different* poses (or the tool is
fed rest-pose meshes while the intended result is posed), nearest-surface
projection is asked to do a job skinning is supposed to do first. On a
T-pose body with an arm blown out sideways, the surface nearest a sleeve
vertex is frequently the *torso*, not the arm — so the sleeve collapses
onto the chest and the cuff is left floating. The fit pipeline **cannot
recover this**: `project_*` only *repositions* the garment's existing
vertices and adds no geometry; collision only pushes out of the body;
smoothing only relaxes noise. None of them can carry fabric along a limb
the way an armature deform does. So across a pose gap the tool produces a
visibly broken drape *and reports `FINISHED` with no warning* — the same
silent-success failure mode as the row 2 overlap gap.

### 6c. Honest calibration — what the complaint gets right, and what it doesn't

- **"Doing nothing productive" is overstated as literal truth.** In the
  same session, the E-girl Tech Set (Tech top + Tech Pants) batch-fit
  **cleanly** across all three real bodies (Egirl / Fantasy / Venus) in
  one Bind + one Batch Fit call, torso and legs staying covered and the
  silhouette adapting per body. The tool *is* productive when its
  initial-pose-alignment precondition is already met. The defensible
  version of the complaint is narrower and real: the tool offers **no
  armature-driven way to reach that aligned state**, and for the common
  real-world case (garment and body each skinned to a rig, in different
  poses, or rest-vs-posed) it silently emits garbage.
- **The specific floating-cuff render was NOT caused by missing pose —
  do not attribute it to this card.** That thread's cuff gap was chased
  through several wrong theories (import scale, an Armature-modifier
  evaluation gap, needing to pose the rig) and each was ruled out: the
  raw `Sweater by Vinuzhka` piece reproduces the gap under a verified
  real T-pose, on its own source body, with an identity fit — and the
  user ultimately confirmed the separated cuff/sleeve is the garment's
  **intentional design**, not a fit failure. The armature/pose gap in
  this section is the *general structural* finding the investigation
  surfaced (a fully-rigged, fully-posed reference asset the tool has no
  concept of), not the root cause of that one render.
- **The "tool discarded the armature" symptom in that session was in the
  test-harness import helper, not the addon.** The helper dropped the
  Armature object on import and ran against the bare rest-pose mesh. That
  is a harness bug, but it points at the same real addon-level gap: the
  addon has no notion of a rig to preserve or use in the first place, so
  nothing downstream would have used the armature even had the helper
  kept it.

### 6d. The tool's actual purpose (clarified by the user, 2026-09-01)

The framing this gap sits inside, stated plainly so it isn't lost: every
garment is authored for one specific rigged body — its **base**. The
tool's whole purpose is to retarget a garment from its source base onto a
*different* target base automatically — the thing the user did by hand in
`Test_Items/Example1.blend` (Vinuzhka Tech Set, authored for `RP Female
Base_Heeled Foot.fbx`, hand-fitted onto `vrbase_Egirl_Heeled Foot.fbx`).
The intended pipeline is therefore two stages — **pose, then sculpt** —
and only the sculpt stage exists today. See ARCHITECTURE.md's intro.

### 6e. Bone-structure evidence (measured, `Test_Items/Body`)

The four bodies were imported headless (Blender 5.2.1, `--factory-startup`)
and their armatures dumped. The user's summary — "all body bone
structures will be relatively the same except for maybe naming
conventions" — holds, with the naming differences being the substantive
part:

| Rig family | Bones | Separator | Arm chain | Leg chain | Finger example |
|---|---|---|---|---|---|
| RP Female Base (+ Tech Set clothing rig, 89) | 84 | `.L`/`.R` | Arm / Elbow / Wrist | Leg / Knee / Foot | `Index Finger.L` |
| vrbase Egirl / Fantasy (+ bodysuit rig, 91) | 66 | `_L`/`_R` | Arm_L / Elbow_L / Wrist_L | Leg_L / Knee_L / Foot_L | `Index Finger_L` |
| Project Venus | 98 | `.L`/`.R` | Upper_Arm / Lower_Arm / Hand | Upper_Leg / Lower_Leg / Foot | `IndexFinger1.L` |

All three share the same humanoid hierarchy (Hips → Spine → Chest →
Shoulders→Arms→Hands + Neck/Head; Hips → Legs → Feet → Toes) plus
differing helper bones (twist/jiggle/breast/butt), which is why bone
counts diverge. The clothing rigs carry the same naming as their source
base — Tech Set uses the dot/`Arm`/`Leg` convention of RP Female Base;
`bodysuit` uses the underscore/`Arm_L` convention of the vrbase family.
**Consequence for the fix:** matching bones between a garment rig and a
target base rig cannot be naive string equality — it needs a canonical
humanoid map that normalizes the separator, joint-name, and finger-name
differences above. That mapping layer is roadmap card R2.

### 6f. The decided fix and roadmap

The direction is settled (user-directed): an **armature-driven Stage 1**
that matches the two rigs' bones (normalizing naming) and transfers the
target base's pose onto the garment via its own skin weights, before the
existing sculpt stage refines the surface. Scoped across six board cards:

- **R1** `062cfedd` (To-Do) — model source/target base rigs + target-base
  picker (foundation).
- **R2** `1b7b56eb` (To-Do) — canonical humanoid bone mapping across the
  naming families in §6e.
- **R4** `812a0a6a` (To-Do) — interim: refuse clearly on a gross
  pose/position mismatch instead of reporting success (subsumes row 2).
- **R3** `cfa7e4aa` (Backlog, needs R1+R2) — the pose-transfer stage
  itself; the concrete fix for anchor card `9df4bc00`.
- **R5** `450bdee9` (Backlog, needs R3) — wire pose→sculpt into
  Fit/Batch as the end-to-end flow.
- **R6** `c342ccc2` (Backlog, needs R3/R5) — real-asset retarget
  regression (Tech Set → Egirl/Fantasy/Venus vs `Example1.blend`).

Per section 9's standing rule this section stays qualitative: it records a
design/usability finding and a plan, not measured numbers. Any
quantitative claim a fix makes (e.g. "pose transfer reduces residual
penetration by X on the rigged corpus") must arrive with its own
reproducible test — that is precisely what R6 exists to provide.
