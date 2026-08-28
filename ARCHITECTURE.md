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
   parameter.
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

## 8. Batch/automated extension

`OT_batch_fit` is the intended batch entry point: point it at a
Collection of target body objects and it runs the full per-target
pipeline (project → collision → smooth → bake) once per object, writing
one `Fitted` shape key per target. It is a thin orchestration layer over
the same `core/` modules the single-target `OT_fit_garment` uses — no
separate batch-specific solver logic — so correctness fixes to the core
pipeline apply to both paths automatically.
