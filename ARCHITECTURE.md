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
   along the local normal by at least the user's collision-margin
   parameter. Thin-geometry tunneling is fixed via a second, anchor-based
   `BVHTree.ray_cast` check (see §7); the push-out direction in concave
   regions remains an open, known blind spot that step 3 does not
   compensate for — see §7.
3. **Smoothing / relaxation** — Laplacian-style relaxation pass, weighted
   by `(1 - pin_weight)` per vertex so pinned regions don't move, and
   constrained against the garment's own original edge lengths so the
   pass smooths noise from steps 1–2 without shrink-wrapping the garment
   flat.
4. **Bake** — result is written to a Shape Key named `Fitted` on the
   garment object (created fresh or overwritten), never mutating base
   mesh data. This sidesteps a hard platform limitation: Blender's Python
   API cannot author a new entry in the traditional C-level modifier
   stack, so "live modifier" is not achievable in pure `bpy`. A Shape Key
   is the idiomatic non-destructive equivalent — it's undoable, can be
   blended with existing shape keys/animation, and requires no custom
   modifier plumbing.

Steps 2 and 3 are independently toggleable per the parameters below.

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
  hems garment-shaped even under aggressive fitting elsewhere.
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
- **Performance on dense meshes / large batch runs.** Per-vertex BVH
  queries are the dominant cost; fine at moderate (tens-of-thousands
  vertex) counts for interactive single-target use, but a batch job
  fitting one garment across hundreds of target bodies risks becoming
  slow if implemented with naive per-vertex Python loops. The batch
  operator must use NumPy-vectorized bulk vertex access
  (`foreach_get`/`foreach_set`) rather than per-vertex loops to be
  viable at scale — called out explicitly on that card.
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
- **Collision resolution's push-out direction is still unreliable in
  concave regions.** (Tunneling — see below — is fixed; this half of
  card `c9ff95a5-6269-4c82-8789-08113a9dc9d3` was explicitly deprioritized
  by the Architect and deliberately not addressed by that fix.)
  `resolve_collisions()` in `core/collision.py` still decides ordinary
  (non-tunneled) interpenetration using nearest-point distance plus the
  local face-normal sign, which is independently unreliable at picking a
  push-out direction in concave regions (armpits, crotch) — related to,
  but distinct from, the Mode B concave-region issue above (that one is a
  binding-math problem; this is the collision pass's own geometry test).
  Not solved in v1 — a multi-sample/averaged local normal, or an explicit
  flag+report-don't-silently-fix approach for vertices in ambiguous local
  geometry, were the two directions suggested when this was filed;
  neither is implemented yet. Remains tracked under the same card.

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
  vertex (`pin_weight == 1.0`) is still exactly untouched. The ~16x
  increase in inner-loop work is linear in sub-sweep count and cheap
  relative to the pipeline's per-vertex BVH collision work, so this is
  not a real performance concern at the scales this pipeline targets.
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

## 8. Batch/automated extension

`OT_batch_fit` is the intended batch entry point: point it at a
Collection of target body objects and it runs the full per-target
pipeline (project → collision → smooth → bake) once per object, writing
one `Fitted` shape key per target. It is a thin orchestration layer over
the same `core/` modules the single-target `OT_fit_garment` uses — no
separate batch-specific solver logic — so correctness fixes to the core
pipeline apply to both paths automatically.
