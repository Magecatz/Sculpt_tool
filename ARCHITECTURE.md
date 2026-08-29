# Sculpt Tool — Architecture

Blender add-on that automatically fits a clothing/garment mesh onto a
target body mesh: pushes the garment out of interpenetration, follows the
target body's surface contours, and preserves the garment's own volume
and silhouette (sleeves, collars, hems stay garment-shaped rather than
collapsing flat onto the body). Designed to also support batch/automated
use — fitting one garment across many body variants without a manual
sculpt pass per pair.

This is the project's first architecture document. It is a design
artifact, not implementation — no add-on code exists yet. Each numbered
module below becomes one or more Bear PR Process cards on the shared
board (project `Sculpt_tool`).

## 1. Chosen approach

**A custom BVH-based bind/solve pipeline, built from first principles on
top of Blender's own Python primitives (`bmesh`, `mathutils.bvhtree`,
mesh custom attributes), not a single built-in modifier.**

The pipeline runs in two phases:

1. **Bind** (once per garment + source body pair): record, for every
   garment vertex, where it sits relative to the body it was authored on
   — its correspondence point on the body surface plus its offset from
   that surface. This binding is persisted data, not a live link.
2. **Fit** (once per target body, repeatable/batchable): given a target
   body mesh, re-evaluate each garment vertex's stored correspondence
   against the target's surface and reapply the same offset, then run a
   collision-resolution pass and a pin-aware smoothing/relaxation pass to
   clean up the result. Output is written to a new Shape Key on the
   garment ("non-destructive bake"), never overwriting base mesh data.

### Alternatives considered and rejected for v1

- **Shrinkwrap modifier alone.** Cheapest option, but it collapses every
  garment vertex onto (or at a single uniform offset from) the body
  surface. It has no notion of the garment's original looseness varying
  by region (a loose sleeve vs. a tight cuff), so sleeves/collars/hems
  shrink-wrap flat instead of retaining their authored silhouette — this
  directly violates the volume/silhouette-preservation requirement. It's
  still useful as a *building block* inside our collision-resolution
  pass (Blender's own project-to-surface math), just not as the whole
  solution.
- **Surface Deform modifier alone.** Binds via a cage-like correspondence
  to a target mesh and then *tracks* that target's deformation — good for
  reposing/animating a garment that's already correctly fitted, but it
  assumes garment and target already overlap correctly at bind time. It
  doesn't solve the initial-fit problem (different body shape/proportions
  than the garment was authored on), which is the actual ask here.
- **Cloth simulation as the primary solver.** Physically the most
  realistic drape, but nondeterministic, sensitive to substep/margin
  tuning, and a poor fit for unattended batch use (hundreds of body
  variants). Kept as an optional *opt-in refinement pass* on top of the
  deterministic solve, not the default pipeline — see Risks.
- **Cage/lattice-based deformation.** Would need a hand-authored cage per
  garment, adding manual setup per garment that defeats the "batch across
  many bodies" goal without also automating cage generation, which is a
  harder problem than the projection-based approach below. Not pursued
  for v1.

The chosen approach reuses Blender's low-level geometry primitives
(`BVHTree` nearest-surface queries, barycentric coordinates,
`mathutils` vector/normal math) rather than any one high-level modifier,
because no single built-in modifier captures "preserve per-region
garment offset while following a different body's contours."

## 2. Binding modes (the data-model core)

A garment is bound to a **source body** (the body it was authored on),
producing a per-vertex correspondence record. Two modes, auto-selected
by the bind operator based on topology match, are supported:

- **Mode A — same-topology.** Source and target body share vertex count
  and order (e.g. the target is a shape key / sculpted morph of the same
  base mesh — the common case for a body-shape library). Correspondence
  is a direct `body_vertex_index`, and the offset is stored as a
  normal-aligned local delta (normal/tangent/bitangent components at that
  body vertex) so it reapplies correctly as the body's shape changes.
  Cheap and exact.
- **Mode B — cross-topology.** Source and target bodies are different
  meshes entirely (a genuinely different/customized character). Built via
  `BVHTree.FromObject` nearest-surface projection: each garment vertex
  stores the source body's `triangle_index`, barycentric weights
  (u, v, w), a signed `normal_offset` (distance off the surface), and a
  `tangent_offset` (2D, in-plane component) to reduce misassignment near
  seams and thin geometry. Re-evaluated against the target body's BVH at
  fit time.

Binding data is persisted as **custom attributes on the garment mesh**
(`bpy.types.Mesh.attributes`), plus object-level custom properties
recording the source body's name, binding mode, and a schema version.
This means a bound garment stays bound across file save/reload with no
external cache file, and undo works normally. No dependency is taken on
UV-space correspondence for v1 (see Risks — noted as a possible future
Mode C).

## 3. Fit pipeline (applied per target body)

1. **Project** — re-evaluate each garment vertex's stored binding against
   the target body's current BVH/vertex positions → raw fitted position.
2. **Collision resolution** — BVH-based penetration test against the
   target body; any garment vertex found inside the body is pushed out
   along the binding's own anchor normal (not the locally-nearest
   triangle's face normal — see §7) by at least the user's
   collision-margin parameter, re-querying up to a small bounded number of
   times and falling back to the anchor point itself if still inside.
   Thin-geometry tunneling is fixed via a second, anchor-based
   `BVHTree.ray_cast` check (see §7).
3. **Smoothing / relaxation** — Laplacian-style relaxation pass, weighted
   by `(1 - pin_weight)` per vertex so pinned regions don't move, and
   constrained against the garment's own original edge lengths so the
   pass smooths noise from steps 1–2 without shrink-wrapping the garment
   flat. Because this step has no notion of the target body and can push
   an already-cleared vertex back into it, step 2 (collision resolution)
   runs a second time on step 3's output when both are enabled — see §7.
4. **Bake** — result is written to a Shape Key named `Fitted` on the
   garment object (created fresh or overwritten), never mutating base
   mesh data. This sidesteps a hard platform limitation: Blender's Python
   API cannot author a new entry in the traditional C-level modifier
   stack, so "live modifier" is not achievable in pure `bpy`. A Shape Key
   is the idiomatic non-destructive equivalent — it's undoable, can be
   blended with existing shape keys/animation, and requires no custom
   modifier plumbing.

Steps 2 and 3 are independently toggleable per the parameters below (the
post-smoothing re-run of step 2 follows step 2's own toggle — it never
runs if collision resolution is disabled, and never runs if smoothing
didn't, since there is then nothing new for it to re-check).

## 4. Blender integration surface

- **Target platform:** Blender 4.x, baseline 4.2 LTS. Uses `bmesh`,
  `mathutils.bvhtree.BVHTree`, `mathutils.kdtree` (fallback nearest-vertex
  queries), and the mesh generic-attribute API. Batch mode uses NumPy
  (bundled with Blender) with `foreach_get`/`foreach_set` bulk vertex
  access rather than per-vertex Python loops — see Risks on performance.
- **Operators** (`bpy.types.Operator`):
  - `OT_bind_garment` — computes and stores the binding (Mode A or B,
    auto-detected) between the active garment and a chosen source body.
  - `OT_fit_garment` — runs the fit pipeline (project → collision →
    smooth → bake) against a chosen target body.
  - `OT_batch_fit` — runs `OT_fit_garment`'s pipeline once per object in
    a target Collection, producing one fitted output per target body.
  - Small helper operators for pin vertex-group management (create/
    assign/remove a pin group from the active selection).
- **UI:** a single N-sidebar panel (3D Viewport, "Sculpt Tool" tab) with
  sections for Binding (source body + garment pickers, Bind button),
  Fit (target body picker, Fit button), Parameters (offset/thickness,
  collision margin, smoothing iterations), Pin Regions (vertex-group
  list, standard Blender weight-painting workflow), and Batch (target
  Collection picker, Run Batch button, progress reporting).
- **Settings:** a `PropertyGroup` holding source/target object pointers,
  numeric parameters, and pin vertex-group references, attached to the
  garment `Object` so settings travel with the object, not just the
  scene.

## 5. Module breakdown

```
sculpt_tool/
  __init__.py            add-on registration (bl_info, register/unregister)
  properties.py           PropertyGroup: source/target refs, parameters, pin groups
  ui_panel.py             N-sidebar panel: Binding / Fit / Parameters / Pin Regions / Batch
  operators/
    op_bind.py            OT_bind_garment
    op_fit.py              OT_fit_garment
    op_batch.py             OT_batch_fit
    op_pin_groups.py        pin vertex-group helper operators
  core/
    binding.py             Mode A + Mode B bind computation
    solver.py               project step: apply binding to a target body
    collision.py            BVH-based penetration test + push-out
    smoothing.py            pin-weighted relaxation pass
    storage.py               read/write binding data as mesh custom attributes
```

Each `core/` module is pure logic operating on mesh data (testable
outside the UI); `operators/` and `ui_panel.py` are the thin Blender-
facing layer that wires user input to `core/`.

## 6. Parameters exposed to the user

- **Offset / thickness scale** — global multiplier on the stored binding
  offset (lets a user tighten/loosen the fit without re-binding).
- **Collision margin** — minimum garment-to-body clearance enforced by
  the collision pass.
- **Smoothing iterations** — relaxation pass iteration count.
- **Pin regions** — one or more vertex groups (e.g. `Pin_Collar`,
  `Pin_Cuff_L`, `Pin_Cuff_R`, `Pin_Hem`) whose weight blends a vertex
  between "fully solved" and "rigid, unchanged" — keeps collars/cuffs/
  hems garment-shaped even under aggressive fitting elsewhere. `relax()`
  in `core/smoothing.py` implements this literally: each outer iteration
  computes an entirely unpinned "fully solved" candidate position (the
  same Laplacian + edge-length-correction math with no vertex treated as
  pinned), then blends every vertex between its own pre-iteration
  position and that candidate by its own `(1 - pin_weight)`. A vertex at
  `pin_weight == 1.0` is therefore exactly unchanged every iteration; a
  vertex at `pin_weight == 0.0` gets the candidate exactly. Partial
  weights now blend roughly linearly in aggregate (measured ~0.70-0.91x/
  ~0.44-0.80x/~0.21-0.60x of an unpinned vertex's displacement at
  `pin_weight` 0.25/0.5/0.75, depending on iteration count and whether
  the pin is an isolated vertex or part of a continuous pinned band). An
  earlier version scaled the edge-length correction's per-edge weight-
  sharing directly instead of blending at the outer-iteration level,
  which did not produce a linear blend (see section 7).

  **Caveat a user of this parameter needs, not just an implementation
  footnote:** the monotonic, bounded-by-unpinned behavior above holds in
  every isolated-pin and uniform-band configuration tested, but *not*
  universally. A **graded** pin weight (neighbors at different weights)
  near the garment's own **free boundary**, combined with the ordinary
  position noise a post-collision mesh already carries, can still let a
  partially-pinned vertex move *more* than a fully unpinned one —
  measured up to ~46% past the unpinned baseline, in roughly 3-4% of such
  configurations. That combination is not exotic: a weight feathered
  toward zero along a hem or cuff edge is close to the literal definition
  of the `Pin_Hem`/`Pin_Cuff` selections this bullet names as the
  motivating use case. So partial pin weights are now a large, real
  improvement over the previous near-binary behavior — but they are a
  strong tendency, not a guarantee, and a feathered hem is exactly where
  the exception lives. Section 7 has the full measurement, the
  comparison against pre-fix behavior on the same adversarial scenario,
  and the tracking card (`8432ee45-20a9-47da-be6a-53e3beee39e6`).
- **Bind mode override** — force Mode A/B instead of auto-detect, for
  edge cases where topology matches by coincidence but shouldn't be
  treated as correspondence.

## 7. Known risks / limitations (up front)

- **Mode B accuracy on extreme shape changes.** Barycentric/normal-offset
  correspondence degrades on large body-shape deltas (thin → heavy body):
  local triangle geometry distorts enough that normal direction and
  in-plane offset assumptions can diverge or flip, especially at concave
  regions (armpits, crotch) and thin extremities (fingers, where a nearby
  garment vertex can misassign to the wrong local surface entirely). Not
  solved in v1 — flagged for future correspondence-quality validation.
- **No garment/source-body overlap validation.** If a garment mesh isn't
  reasonably positioned relative to its declared source body at bind
  time, Mode B will silently produce a garbage binding. v1 does not
  detect or warn about this (e.g. via an average-nearest-distance sanity
  check) — future UX improvement.
- **No garment-vs-garment layering.** The collision pass only resolves
  garment-vs-single-body interpenetration. Multiple garment layers (e.g.
  jacket over shirt) are out of scope for v1.
- **Performance on dense meshes / large batch runs.** This bullet
  originally named per-vertex BVH queries as the dominant cost. As of the
  smoothing pass landing, **that is no longer true**: measured at
  comparable scale, collision's per-vertex BVH work runs ~0.25s (~30k
  vertices vs. a ~65k-triangle body) while the smoothing pass runs ~4.73s
  (~33k vertices, `smoothing_iterations=10`) — smoothing is roughly **19x
  collision**, and is now the pipeline's dominant per-target cost. See the
  smoothing entry below for the full measurement. Both are fine at
  moderate (tens-of-thousands vertex) counts for interactive
  single-target use, but a batch job fitting one garment across hundreds
  of target bodies multiplies the *whole* per-target cost, smoothing
  included, and has not been measured at that scale.

  Two distinct mitigations, and it matters that they are not the same
  one: the batch operator must use NumPy-vectorized bulk vertex access
  (`foreach_get`/`foreach_set`) rather than per-vertex Python loops for
  mesh I/O and the projection/collision steps — called out explicitly on
  that card. **That mitigation does not touch smoothing's cost.**
  `_edge_length_step`'s 16 sub-sweeps are Gauss-Seidel (each edge's
  correction applied immediately, so later edges in the same sweep see
  earlier ones), so a naive `foreach_get`/`foreach_set` rewrite cannot
  vectorize them: the sequential dependency is what the curvature-shrink
  fix's convergence behavior depends on. Reducing smoothing's batch cost
  therefore needs a different lever than bulk vertex access. Three
  candidates, none yet validated:

  - the adaptive/early-exit sub-sweep variant tracked as Backlog card
    `5b232224-901f-4c7a-a991-42cb29b5627d`;
  - exposing sub-sweep count as a batch-mode quality/speed trade-off;
  - **graph/edge-colored Gauss-Seidel** — partitioning edges into colors
    where no two edges in a color share a vertex, then vectorizing within
    each color. This is the standard way to parallelize PBD distance
    constraints, and it *would* let NumPy attack the dominant cost. It
    changes sweep ordering, so it is not free: it requires re-running the
    tube shrinkage validation described in the smoothing entry below
    before adoption. "Needs re-validation" is not the same as
    "impossible", and this option should not be dismissed on the
    strength of the sequential-dependency argument above, which only
    rules out the naive rewrite.

  Anyone scoping the Batch card should plan against this explicitly
  rather than assuming bulk vertex access covers it.
- **Cloth-sim refinement is opt-in only.** A physically-simulated
  drape pass is valuable for realism but nondeterministic and
  substep/margin-sensitive; it must never be part of the default
  unattended batch pipeline. If added later, it is a separate, clearly
  optional stage.
- **No UV-space binding mode (Mode C) in v1.** Garments authored fully
  off-body (flat pattern pieces matched to the body via UV
  parameterization rather than 3D proximity) are not supported by either
  Mode A or B. Noted as a plausible future mode, not scoped now.
- **Topology-mismatch misdetection.** Auto-detection of Mode A vs. B
  relies on vertex count/order matching; two unrelated meshes that
  happen to share a vertex count could be misclassified as Mode A. The
  bind-mode override parameter exists specifically as the escape hatch,
  but the default heuristic itself is a known soft spot.
- **Mode B re-derives its anchor from the source body's live mesh, not a
  bind-time snapshot.** `project_mode_b` in `core/solver.py` reconstructs
  the bind-time correspondence point from the source body's *current*
  mesh via the stored `triangle_index`/barycentric weights, rather than
  from a cached bind-time position. If the source body is edited or
  reshaped after bind — a different situation from the source body being
  missing/renamed, which already raises a clear error — the fit silently
  reprojects onto the altered geometry with no warning that the binding
  is stale. This is a separate failure mode from the correspondence-math
  degradation described above: the geometry query itself stays valid,
  but it's answering a question the user no longer thinks they're
  asking. It doesn't block Smoothing or the Pin-UI work, but it should be
  fixed before Batch fitting is trusted for real production use — Batch
  runs unattended at scale and is the workflow least likely to have
  someone around to notice a quietly-wrong fit. Tracked as Backlog card
  `089ab86f-4247-42c4-9652-9d30de33fbdf`.
- **Collision resolution's push-out direction in concave regions — fixed**
  (card `1e252575-2b86-4ba5-89f7-bcf0ae9685ba`, the deferred half of card
  `c9ff95a5-6269-4c82-8789-08113a9dc9d3` that was explicitly deprioritized
  when tunneling shipped). A full-corpus run against real garments (22
  meshes across 9 FBX files) measured the residual this caused directly:
  9 of 22 ended with 50+ vertices still penetrating the body after fit,
  concentrated in concave/self-occluding regions (straps, hoods, layered
  pieces, armpit/crotch folds); the other 13 (simple, mostly-convex
  garments) already reached exactly 0. Root cause: `resolve_collisions()`
  decided a push-out *direction* from the locally-nearest triangle's own
  face normal, which in a concave pocket can belong to a different fold
  of the surface than the one the vertex is actually meant to clear, and
  so can point sideways or back into the body. Fixed, per an Architect
  consult on this card, three ways together:
  - **Push-out normal source** — `resolve_collisions()` now pushes along
    `anchor_normal` (`core.solver.ProjectionResult.anchor_normals`, the
    binding's own per-vertex reference direction, already used by the
    tunneling fix below) instead of the locally-nearest triangle's face
    normal. `hit_location` (the nearest surface point) is still the
    position the push originates from — only the direction source
    changed.
  - **Bounded re-query loop** — a single push along a fixed direction can
    still leave a vertex inside a concave pocket (or move it into a
    different fold of the same pocket), so `_push_out_locally()` in
    `core/collision.py` re-runs the inside/outside test after each push,
    up to 3 attempts, falling back to `anchor_position + anchor_normal *
    collision_margin` — the same guaranteed-correct-by-construction point
    the tunneling fix already relies on — if still inside after that many.
    Every vertex this test flags now resolves to a definite, correct-side
    answer in bounded time. The bound is small deliberately: collision
    resolution is the cheap side of the pipeline relative to smoothing
    (~0.25s vs. ~4.73s at comparable scale, see the performance entry
    above), and only vertices actually flagged as interpenetrating pay for
    extra attempts.
  - **Post-smoothing collision re-pass** — smoothing (step 3) has no
    notion of the target body and can drag an already-cleared vertex back
    into it; nothing previously re-checked collision after smoothing ran.
    `operators/op_fit.py` now runs `resolve_collisions()` a second time on
    smoothing's output, reusing the same anchors from the original
    projection (unaffected by smoothing moving vertices around), when both
    collision resolution and smoothing are enabled.

  Re-measured on the same real corpus, all nine previously-failing
  garments dropped substantially (see `tests/test_collision.py`'s
  synthetic concave-pocket regression for the checked-in repro — the real
  `Test_Items/` assets are gitignored third-party meshes and cannot be
  checked in). Not claimed as a complete fix for every conceivable
  concave topology: the bounded re-query/fallback guarantees a
  correct-side answer, not a minimum-margin-satisfying one on the very
  first local push, so extremely convoluted geometry (self-intersecting
  folds nested several layers deep) could still need more than the
  fallback's single anchor-snap to look ideal, though it will not be left
  penetrating.

  **Tunneling is fixed** (same card, prioritized half, done in
  `fix/collision-tunneling`): a vertex that tunnels all the way through
  thin geometry (e.g. wrist/ankle) is no longer left in place. The fix
  does not make the inside/outside test on the vertex's own final
  position smarter — a vertex sitting well past the far wall of a thin
  slab is genuinely, correctly outside the solid by any point-containment
  test (nearest-point sign, ray-parity, winding number alike), so no such
  test can flag it without being wrong. Instead, `core/solver.py`'s
  `project_mode_a`/`project_mode_b` now return the per-vertex anchor
  point (and its normal) on the target body's surface that the binding
  offset was actually measured from — the surface the vertex is meant to
  be hugging, independent of how far the offset then carried it — via a
  `ProjectionResult` dataclass, instead of discarding it after computing
  the offset. `resolve_collisions()` (now
  `resolve_collisions(fitted_positions, anchor_positions, anchor_normals,
  target_body_obj, collision_margin)`) uses that anchor for a second,
  bounded `BVHTree.ray_cast` per vertex — only when the existing
  nearest-point test didn't already flag it — checking whether the
  straight segment from anchor to fitted position crosses the target
  body's own surface at all. That can only happen if the offset carried
  the vertex through solid material, which is exactly what "tunneled"
  means; a vertex caught this way is pushed back to
  `anchor_position + anchor_normal * collision_margin` (the near surface)
  rather than whatever the nearest-point query would find on the far
  side. One extra bounded ray-cast per vertex, same single BVH build per
  call as before — no meaningful perf regression at the scales this
  pipeline targets (verified: ~30k vertices against a ~65k-triangle body
  in ~0.25s). Known limitation of this approach, accepted as out of
  scope: on sufficiently convoluted/bumpy geometry the anchor-to-fitted
  segment can graze an unrelated nearby fold of the body and produce a
  false-positive tunneling detection — the same class of blind spot as
  the concave push-out-direction issue above, not a new one. Separately,
  worth flagging for whoever picks up Smoothing (not a defect here): because
  the corrected vertex is snapped to `anchor_position + anchor_normal *
  collision_margin`, a pure normal-offset point, its tangential/bitangent
  offset is collapsed to zero — the correct, intentional trade-off for
  collision safety, but it makes a tunnel-corrected vertex a categorically
  different kind of displacement (larger, differently shaped) than the
  ordinary sub-margin jitter the rest of the pipeline produces. Validated by
  an Architect consult on this card before implementation (the anchor
  point was already being computed by `solver.py` and thrown away, so
  this needed no new binding-time data and no widening of
  `core/collision.py`'s module boundary beyond taking two more
  already-computed lists as parameters).

- **Smoothing's edge-length constraint now iterates internally per
  outer iteration, rather than running a single relaxation sweep.**
  `core/smoothing.py`'s `relax()` runs one damped Laplacian step
  followed by `_EDGE_CORRECTION_SUBSTEPS` (16) internal Gauss-Seidel
  sub-sweeps over all edges pulling each back toward its original
  (base-mesh) length, per `smoothing_iterations`. A single sweep per
  iteration was found (Tester report, Architect-confirmed) to leave
  enough residual edge-length error that the next iteration's Laplacian
  step compounded a fresh contraction on top of it: on a completely
  clean, unperturbed, unpinned cylindrical/tube-shaped garment (zero
  noise, zero pins — the textbook case section 1's anti-shrinkwrap goal
  exists to protect) this produced ~9% radius shrinkage after 10
  `smoothing_iterations`, a straightforward regression against that
  goal, not an edge case. Looping the edge-length correction internally
  fixes this: on this card's own re-measured synthetic tube repro
  (32-segment, 20-ring cylinder, zero noise, zero pins), radius
  shrinkage at 10 iterations dropped from ~9% to ~0.58%, and at 40
  iterations it was ~0.575% — confirming the residual plateaus rather
  than continuing to compound as `smoothing_iterations` grows. (The
  Architect's own tuning pass, on a different synthetic mesh, measured
  ~0.2% at the same sub-sweep count; the exact residual is mesh-
  dependent, but the qualitative behavior — low-single-digit-percent or
  better, non-compounding — matches.) `relax(iterations=...)`'s public
  signature and semantics are unchanged: it still counts outer
  Laplacian+constraint iterations exactly as before, and a fully-pinned
  vertex (`pin_weight == 1.0`) is still exactly untouched. **Correction
  (Architect consult, post-merge):** this section originally claimed the
  ~16x increase in inner-loop work was "cheap relative to the pipeline's
  per-vertex BVH collision work." That was measured wrong. Actual
  numbers on a ~33k-vertex synthetic tube at `smoothing_iterations=10`:
  ~4.73s with this fix, versus ~0.50s before it. Measured against the
  collision pass's own documented figure at comparable scale (~30k
  vertices against a ~65k-triangle body in ~0.25s, cited above), the
  fixed smoothing pass is now roughly **19x more expensive than
  collision**, not cheap relative to it. The fixed sub-sweep count also
  means this cost is linear in batch collection size — it scales
  directly with however many target bodies a real Batch run processes,
  and hasn't yet been measured at that scale. An adaptive/early-exit
  sub-sweep variant (stopping once residual edge-length error falls
  under some threshold instead of always running all 16) is a known,
  unvalidated candidate to revisit if real Batch runtimes demand it —
  left in Backlog as a conditional future item, not being built now.
  Tracked as Backlog card `5b232224-901f-4c7a-a991-42cb29b5627d`.
  This also fully re-verified clean against the collision pass's
  anchor-based tunneling correction (see above): a vertex snapped by
  `anchor_position + anchor_normal * collision_margin` next to neighbors
  that keep their full authored offset is a genuinely larger,
  differently-shaped discontinuity than ordinary projection/collision
  jitter, and the harder-converging edge-length constraint still keeps
  a thin-geometry tunneling-correction scenario finite with bounded edge
  lengths through smoothing, no blow-up — re-tested on this card, not
  just assumed unaffected by the internal-loop change. A garment/body
  pairing that triggers tunneling correction on many neighboring
  vertices at once may still show a locally tauter or slower-to-relax
  patch near the correction compared to ordinary noise elsewhere. Not a
  bug; not solved further here.

- **Partial pin weights now blend roughly linearly (largely fixed; was
  closer to binary than a smooth gradient — one measured residual
  remains, at the bottom of this entry).** Section 6 describes pin weight as
  blending a vertex between "fully solved" and "rigid, unchanged." That
  was accurate for the damped Laplacian step alone (which scales each
  vertex's own displacement directly by `(1 - pin_weight)`) but not for
  the combination with the edge-length correction sub-sweeps:
  `core/smoothing.py`'s `_edge_length_step()` used to distribute each
  edge's correction between its two endpoints by free-weight-sharing
  (`free_a / (free_a + free_b)`, where `free_x = 1 - pin_weight_x`)
  rather than applying `(1 - pin_weight)` to each vertex's own share
  independently. In aggregate this pulled a partially-pinned vertex much
  closer to unpinned behavior than its weight alone suggested — a vertex
  at `pin_weight = 0.5` moved roughly 0.76x-0.96x of an unpinned vertex's
  displacement, not the ~0.5x the section 6 description implied. Only
  `pin_weight == 0.0` and `pin_weight == 1.0` behaved as documented.

  **Fixed** (bug card `1638a2d4-45d5-4264-9bc0-4e0ac339936b`): pin
  weighting moved out of the per-edge/per-vertex math entirely and into
  `relax()`'s outer loop. Each outer iteration now computes an entirely
  unpinned "fully solved" candidate (the same `_laplacian_step` +
  `_edge_length_step` internals, called with every pin weight forced to
  `0.0`), then blends every vertex between its own pre-iteration position
  and that candidate by its own `(1 - pin_weight)` —
  `new = old * pin + candidate * (1 - pin)`. This is a direct
  implementation of the section 6 language rather than an approximation
  of it. `_laplacian_step`/`_edge_length_step` themselves are unchanged
  (still pin-aware, still correct standalone building blocks); `relax()`
  simply no longer calls them with the real per-vertex pin array.

  An intermediate fix was tried and rejected before landing this one:
  scaling `_edge_length_step`'s per-edge weight-sharing by each vertex's
  own `(1 - pin_weight)` directly (splitting each edge's correction pool
  50/50 between endpoints, then damping each endpoint's own half by its
  own free weight) — Architect-recommended as the natural mirror of the
  Laplacian step's self-referential scaling. It is correct for a single
  isolated step given fixed neighbor positions, but empirically produced
  a non-linear and even non-monotonic aggregate blend across multiple
  outer iterations: on a disconnected-chain test isolating a single
  pinned vertex from cross-talk, 10 outer iterations measured
  pin_weight=0.25 moving *more* than pin_weight=0.5 (ratios 1.16 and 1.17
  respectively against an unpinned baseline — both **above** the
  unpinned vertex's own displacement), because a free neighbor's
  correction share was capped independent of the pinned vertex's own
  resistance, letting the neighbor "wind up" against the slower-moving
  pinned vertex over repeated iterations faster than the reduced
  per-step correction could cancel. The outer-iteration blend adopted
  instead avoids this because pin weighting never participates in the
  per-edge/per-neighbor math at all — it's a pure per-vertex
  old/candidate interpolation applied once per iteration, so it cannot
  introduce this kind of cross-vertex feedback.

  Re-measured on this fix (`core/smoothing.py`'s `relax()`, disconnected-
  chain and 2D-grid test meshes, `smoothing_iterations` 1-10):
  - **Isolated pinned vertex** (single pinned vertex, unpinned
    neighbors): pin_weight 0.25/0.5/0.75 moved ~0.70-0.91x / ~0.44-0.80x
    / ~0.21-0.60x of an otherwise-identical unpinned vertex's
    displacement across 1-10 outer iterations — exactly linear at 1
    iteration (0.75/0.50/0.25 to 4 decimal places), drifting somewhat
    further from exact as iterations and neighbor feedback accumulate,
    but always monotonic in pin weight, and bounded by the unpinned
    baseline in every isolated-vertex configuration tested (see the
    graded-boundary caveat below for a configuration where this bound
    does not hold).
  - **Continuous pinned band** (a realistic `Pin_Hem`-style selection
    where every pinned vertex's neighbors are also pinned): pin_weight
    0.25/0.5/0.75 measured ~0.84x/~0.68x/~0.47x at 10 outer iterations —
    still monotonic, and bounded by the unpinned baseline in every
    uniform-band configuration tested (again, see the caveat below), but
    a visibly softer blend than an isolated pin at the same weight and
    iteration count, since neighboring pinned vertices' unpinned
    candidates reinforce each other's advancement iteration over
    iteration. Still a large improvement over the pre-fix 0.76x-0.96x
    near-binary plateau, and worth knowing when tuning a specific
    garment's pinned regions.
  - **Boundaries preserved exactly**: `pin_weight == 1.0` still produces
    bit-for-bit zero movement (including through overlapping-`Pin_*`-
    group sum-and-clamp to exactly 1.0), and `pin_weight == 0.0` is
    bit-for-bit identical to pre-fix behavior (the candidate computation
    is the same zero-pin code path as before).
  - **Curvature-shrink fix unaffected**: the zero-pin tube/cylinder
    shrinkage re-test (32-segment, 20-ring cylinder) measured ~0.56% at
    10 iterations and ~0.56% at 40 (plateauing, matching the ~0.58%/
    ~0.575% figures above within measurement noise) — expected, since
    with all pins at `0.0` the candidate computation is exactly the
    pre-fix code path, unchanged.
  - **Known residual, NOT fully bounded: a graded pin-weight region near
    a mesh boundary, combined with input position noise, can exceed the
    unpinned baseline.** The isolated-pin and continuous-band bounds
    above hold in every configuration tested, but neither covers a
    *graded* pin region (neighboring vertices at different pin weights)
    sitting near the mesh's own free boundary with some vertex-position
    jitter present. That combination is not a contrived corner case — a
    weight feathering out toward zero at a garment's free edge, combined
    with the ordinary positional noise a real post-collision-resolution
    mesh already has, is close to the literal definition of a real
    `Pin_Hem`/`Pin_Cuff` selection. Tester found one such counterexample
    (7x7 grid, radial graded band, one seed, 15 outer iterations): a
    `pin_weight = 0.25` vertex moved ~6% more than the most-displaced
    `pin_weight = 0.0` vertex in the same run. Reviewer independently
    reproduced this on a broader sweep (flat-panel and cylindrical
    hem-ring topologies, varying grid size/grading width/jitter
    amplitude/seed/iteration count): the overshoot appears in roughly
    3-4% of graded-boundary-plus-jitter configurations tried (0/24 with
    zero jitter — noise is necessary to trigger it; it also vanishes on
    interior, non-boundary-adjacent graded regions), and can be
    considerably larger than the Tester's single data point — up to
    ~46% on a flat panel and ~32% on a cylindrical hem-ring, both well
    above the initial ~6% report. It does not grow monotonically with
    iteration count (e.g. 26%/46%/11% overshoot at 10/15/20 iterations
    on the same seed). Likely cause: each outer iteration's "fully
    unpinned candidate" is computed from every vertex's own *current*,
    already partially-blended position (and its neighbors' likewise
    partially-blended positions), not from a truly independent, fully-
    relaxed simulation — at a pin-weight gradient the edge-length
    correction can assume more elasticity in a lagging neighbor than
    that neighbor will actually exhibit once its own blend is applied,
    producing a genuine (not measurement-noise) transient overshoot. For
    context: the identical adversarial sweep run against the pre-fix
    (`3ccbcac`) code fails far more often (48% of configurations vs.
    3.9% here) and far more severely (worst-case 218% overshoot vs. 46%
    here) — so despite this residual, the fix is a substantial
    improvement over prior behavior even in the specific scenario that
    exposes it, not only in the typical case. Not fixed here: tightening
    this further looks like it needs a different candidate-computation
    strategy (one that doesn't let an un-relaxed neighbor's lag leak into
    the correction math at a pin gradient), not a small tweak to the
    current approach — i.e. another design iteration, best done with a
    fresh Architect look, rather than something to block this fix on.
    Tracked as Backlog card `8432ee45-20a9-47da-be6a-53e3beee39e6`.

## 8. Batch/automated extension

`OT_batch_fit` is the intended batch entry point: point it at a
Collection of target body objects and it runs the full per-target
pipeline (project → collision → smooth → bake) once per object, writing
one `Fitted` shape key per target. It is a thin orchestration layer over
the same `core/` modules the single-target `OT_fit_garment` uses — no
separate batch-specific solver logic — so correctness fixes to the core
pipeline apply to both paths automatically.

## 9. Testing

Blender 5.2.1 LTS is available in the development environment
(`C:/Program Files/Blender Foundation/Blender 5.2/blender.exe`), so
every card from here on is verified against a real Blender, not just
statically. Earlier cards (including the two most numerically delicate
passes — collision resolution and smoothing) predate this and shipped
without a Tester able to run anything; this section exists so that gap
doesn't recur and so every quantitative claim added below (or above, in
section 7) has a checked-in script behind it, not just testimony from a
session that's since gone.

**Where tests live:** `tests/` at the repo root, next to `sculpt_tool/`.
Stdlib `unittest`, not pytest — pytest isn't vendored into Blender's
bundled Python and this avoids needing to maintain that.

- `tests/run_tests.py` — the one runner. Discovers and runs every
  `tests/test_*.py` module and exits non-zero on any failure/error, so
  it's a real pass/fail gate:

  ```
  blender --background --factory-startup --python tests/run_tests.py
  ```

  Every future Tester should run this exact command rather than writing
  a fresh throwaway script — that's what let section 7's numbers drift
  into unreproducible testimony the first time.
- `tests/common.py` — shared synthetic-mesh builders (`make_grid`,
  `make_tube`, pin-group helpers) and a `update_scene()` helper for a
  Blender scripting gotcha the harness ran into repeatedly: a plain
  `obj.location = ...` or `v.co = ...` mutation doesn't synchronously
  update `matrix_world`/the evaluated depsgraph the way a `bpy.ops`
  operator call implicitly does, so a test calling `core/` functions
  directly (no operator in between) must force that sync itself before
  reading world-space positions.
- `tests/test_*.py` — the suite itself: tube-shrinkage, pin-weight
  boundary/monotonicity, the checked-in graded-boundary adversarial
  sweep, thin-slab tunneling, Mode B reconstruction round-trip, Mode A
  refit determinism/shape-key/base-mesh checks, and the registration
  smoke test.
- `tests/perf.py` — **opt-in only, not run by `run_tests.py`.**
  33k-vertex-garment / 65k-triangle-body scale timing, matching section
  7's own repro scale. Run explicitly (`blender --background
  --factory-startup --python tests/perf.py`) when re-validating a
  performance claim before it goes into this document.

**Testable-with-plain-data core.** `_laplacian_step`, `_edge_length_step`
(`core/smoothing.py`), `_barycentric_weights`, `_triangle_frame`,
`_local_frame` (`core/binding.py`) already took plain data (`Vector`s,
tuples) with no `bpy` object dependency. This card extended that pattern
to the two remaining pipeline stages the seed tests needed:
`core.smoothing.relax_positions` is the plain-data core `relax()` now
wraps (adjacency + original-edge-length data instead of a `garment_obj`),
and `core.collision.resolve_collisions` now takes `target_positions`/
`target_triangles` directly instead of a `target_body_obj` (the caller,
`operators/op_fit.py`, does the one `bpy`-facing evaluation call). This
is the same extraction the pipeline/geometry card needs more broadly —
coordinate with it rather than duplicating; this card only extracted the
minimum needed to make the seed tests possible, not a full
`core/geometry.py`/`core/pipeline.py` split.

`core.binding.reconstruct_mode_b_position` was dead in production code
(referenced only from a docstring — `core.solver.project_mode_b`
re-derives against a *different*, target body rather than reconstructing
the bind-time source position) and existed purely to make the round-trip
verifiable. It has moved to `tests/test_binding.py` accordingly.

**Standing rule:** every quantitative claim added to this document from
now on must ship with a checked-in script (a test under `tests/`, or
`tests/perf.py` for a timing figure) that reproduces it. Section 7's
0.58% shrinkage, ~4.73s/~0.25s timings, 46%/1.46x overshoot figure, and
the 0.70-0.91x/etc. pin-blend table all came from scripts that were
never checked in, and whose sessions are gone — that's what this rule
exists to prevent happening again. Where this card could reproduce one
of those figures with a fresh, checked-in test, it did (tube shrinkage,
tunneling, Mode B round-trip); where a figure was itself a seeded
adversarial sweep whose exact original script/parameters were never
recorded, the checked-in replacement
(`test_smoothing.GradedBoundaryAdversarialSweepTest`) is a fresh
reproduction in the same regime (documented in its own docstring as
such, with its own measured ceiling), not a re-assertion of the original
unreproducible number.
