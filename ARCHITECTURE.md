# Sculpt Tool — Architecture

Blender add-on that automatically fits a clothing/garment mesh onto a
target body mesh: pushes the garment out of interpenetration, follows the
target body's surface contours, and preserves the garment's own volume
and silhouette (sleeves, collars, hems stay garment-shaped rather than
collapsing flat onto the body). Designed to also support batch/automated
use — fitting one garment across many body variants without a manual
sculpt pass per pair.

This started as the project's first architecture document, written
before any add-on code existed. That is no longer true: `sculpt_tool/`
is now 3,000+ lines of Python across `core/`, `operators/`, and the UI
panel, plus a `tests/` suite (see section 9). Each numbered module below
maps to one or more Bear PR Process cards on the shared board (project
`Sculpt_tool`); section 7 tracks current known risks and section 9
covers testing.

## 1. Chosen approach

**A custom BVH-based bind/solve pipeline, built from first principles on
top of Blender's own Python primitives (`mathutils.bvhtree`,
`mathutils.kdtree`, mesh custom attributes), not a single built-in
modifier.** (`bmesh` was originally planned for here but is not actually
used anywhere in the codebase — see section 4.)

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
  `BVHTree.FromPolygons` (over the source body's triangulated
  `loop_triangles`) nearest-surface projection: each garment vertex
  stores a signed `normal_offset` (distance off the surface) and a
  `tangent_offset` (2D, in-plane component) to reduce misassignment near
  seams and thin geometry, plus (as of the bind-time-freeze card, schema
  v2) the bind-time anchor point itself — frozen in the **source body's
  own local object space** — and the source body's `matrix_world` at that
  same moment. The BVH nearest-surface hit's `triangle_index`/barycentric
  weights are also stored, but as **diagnostics only**: they index into
  the source body's own triangulation at bind time and are never read
  back at fit time (see below). Re-evaluated against the target body's
  BVH at fit time by transforming the frozen local anchor back to world
  space with the frozen bind-time matrix — no read of the source body's
  mesh at fit time at all.
- **Mode A's "no Target Body set" trap (schema v2 fix).** A Mode A
  binding also now stores the source body's vertex count at bind time.
  Auto-detection needs a Target Body to compare topology against at all;
  see below.

Binding data is persisted as **custom attributes on the garment mesh**
(`bpy.types.Mesh.attributes`), plus object-level custom properties
recording the source body's name, binding mode, and a schema version.
This means a bound garment stays bound across file save/reload with no
external cache file, and undo works normally. No dependency is taken on
UV-space correspondence for v1 (see Risks — noted as a possible future
Mode C).

**Binding is bind-time-frozen — no add-on output may re-enter as input
(schema v2, closes cards 089ab86f, 1f8e8594, and a third, previously
uncarded defect in the same family; see DECISIONS.md §4 for the full
writeup of all three, and section 7 row 11 for current status):**

- **Mode B's anchor is a bind-time snapshot, not a live re-derivation.**
  `project_mode_b` never reads the source body's mesh, never resolves the
  source body object by name, and never fails because the source body was
  renamed, deleted, or edited after bind — the frozen local-space anchor
  plus the frozen bind-time `matrix_world` are the only Mode B fit-time
  inputs besides the target body. Editing/re-sculpting/deleting/renaming
  the source body after bind has **no effect at all** on a Mode B fit.
- **No output of this add-on may ever be an input to it.** Bind reads the
  garment's (and source body's) evaluated mesh; if either object's
  `Fitted` shape key (this add-on's own bake — see section 3 step 4) is
  present and active, that read must not include its contribution.
  `operators/op_bind.py` enforces this by temporarily muting the `Fitted`
  key block around the bind-time evaluated-mesh read and restoring it
  after, deliberately leaving garment-side *modifiers* (and every other
  shape key) untouched — only this add-on's own bake is excluded.
- **Auto-detect refuses rather than guesses with no Target Body
  declared.** `detect_bind_mode` raises rather than defaulting to Mode A
  when Target Body isn't set yet — there is nothing to compare topology
  against, so guessing Mode A here is exactly what let a mismatched Mode
  A bind through silently (see DECISIONS.md §4, Part C). A forced Mode A/B
  override still bypasses this function entirely, per its own escape
  hatch below.
- **Schema version is enforced, not just recorded.** `SCHEMA_VERSION` is
  2. A v1 binding (predates the frozen Mode B anchor and the Mode A
  source vertex count) is refused at fit time with a clear "re-bind"
  message (`storage.BindingVersionError`, a `ValueError` subclass) rather
  than being silently misread or falling back to degraded v1 behavior.

## 3. Fit pipeline (applied per target body)

1. **Project** — re-evaluate each garment vertex's stored binding against
   the target body's current BVH/vertex positions → raw fitted position.
2. **Collision resolution** — BVH-based penetration test against the
   target body; any garment vertex found inside the body is pushed out
   along the binding's own anchor normal (not the locally-nearest
   triangle's face normal — see DECISIONS.md §1b) by at least the user's
   collision-margin parameter, re-querying up to a small bounded number of
   times and falling back to the anchor point itself if still inside.
   Thin-geometry tunneling is fixed via a second, anchor-based
   `BVHTree.ray_cast` check (see DECISIONS.md §1a).
3. **Smoothing / relaxation** — Laplacian-style relaxation pass, weighted
   by `(1 - pin_weight)` per vertex so pinned regions don't move, and
   constrained against the garment's own original edge lengths so the
   pass smooths noise from steps 1–2 without shrink-wrapping the garment
   flat. Because this step has no notion of the target body and can push
   an already-cleared vertex back into it, step 2 (collision resolution)
   runs a second time on step 3's output when both are enabled — see
   DECISIONS.md §1b.
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

- **Target platform:** Blender 4.x, baseline 4.2 LTS (developed against
  and tested under 5.2.1 LTS — see section 9). Uses
  `mathutils.bvhtree.BVHTree` (Mode B binding/fit, both collision passes)
  and `mathutils.kdtree` (Mode A's primary bind-time mechanism — a direct
  nearest-vertex search, not a fallback), plus the mesh generic-attribute
  API. There is no `bmesh` usage anywhere in the codebase (verified:
  `grep -r bmesh sculpt_tool/` returns nothing) — an earlier version of
  this document listed it as a dependency; it was never actually used.
  NumPy bulk vertex access (`foreach_get`/`foreach_set`) for batch mode is
  **planned, not implemented** — there are currently zero `numpy` imports
  in the codebase. Split into its own card, `1f564161` (To-Do); see
  section 7.
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
- **Settings:** a `PropertyGroup` (`properties.SCULPTTOOL_PG_settings`)
  holding source/target object pointers, the bind-mode override, and
  numeric parameters, attached to the garment `Object` so settings travel
  with the object, not just the scene. It does **not** hold pin
  vertex-group references — there is deliberately no such field. Pin
  groups are discovered by name at read time: any vertex group on the
  garment whose name starts with `Pin_` (`core.smoothing.PIN_GROUP_PREFIX`)
  is treated as a pin group by `core.smoothing.compute_pin_weights`, and
  the UI (`ui_panel.py`'s `SCULPTTOOL_UL_pin_groups`) filters the
  object's vertex-group list down to that same prefix rather than reading
  it from a stored list. `Pin_` name-matching is the single source of
  truth for "which groups are pins" — a future UI card should read/write
  through it rather than adding a second, PropertyGroup-backed list that
  could drift out of sync with it.

## 5. Module breakdown

```
sculpt_tool/
  __init__.py            add-on registration (bl_info, register/unregister)
  properties.py           PropertyGroup: source/target refs, bind-mode override, numeric parameters (no pin-group field -- see section 4)
  ui_panel.py             N-sidebar panel: Binding / Fit / Parameters / Pin Regions / Batch
  operators/
    op_bind.py            OT_bind_garment
    op_fit.py              OT_fit_garment
    op_batch.py             OT_batch_fit
    op_pin_groups.py        pin vertex-group helper operators
  core/
    geometry.py             shared geometry primitives + TargetContext (target body's evaluated geometry/BVH, built once per fit)
    binding.py             Mode A + Mode B bind computation
    solver.py               project step: apply binding to a target body
    collision.py            BVH-based penetration test + push-out
    smoothing.py            pin-weighted relaxation pass + RelaxContext (garment's adjacency/edge/pin-weight invariants, built once per garment)
    pipeline.py             fit_once(garment, target, params, depsgraph) -> fitted positions -- the full project/collision/smooth sequence, reusable by both op_fit.py and (once it lands) op_batch.py
    storage.py               read/write binding data as mesh custom attributes
```

Each `core/` module is pure logic operating on mesh data (testable
outside the UI, and actually exercised that way — see section 9) and
takes an already-resolved `depsgraph` parameter for any evaluated-mesh
read rather than resolving Blender's own current context itself (Bear PR
Process card cd0d1569-36ad-4d79-a82b-6d1115a0bcda; verified currently
true via `grep -r bpy.context sculpt_tool/core/`, which returns nothing
— `operators/` and `ui_panel.py` are the thin Blender-facing layer that
resolves that context and wires user input to `core/`). `geometry.py`
also holds the handful of shared triangle/frame primitives that used to
be private to `binding.py` but were already being reached into by
`solver.py` and `operators/op_fit.py` — they're public functions there
now, so no module outside `binding.py` needs a `binding._`-prefixed name.
`core/pipeline.py::fit_once` is the single place a target body's
evaluated geometry gets triangulated and BVH-built per fit (via
`geometry.TargetContext`), shared across projection and both collision
passes instead of being rebuilt redundantly.

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
  which did not produce a linear blend (see DECISIONS.md §3a).

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
  the exception lives. See section 7 (row 4) for current status and
  DECISIONS.md §3b-3c for the full measurement, the comparison against
  pre-fix behavior on the same adversarial scenario, and the tracking
  cards (`8432ee45` — partial fix landed; `e893bfdd` — structural
  redesign still open).
- **Bind mode override** — force Mode A/B instead of auto-detect, for
  edge cases where topology matches by coincidence but shouldn't be
  treated as correspondence.

## 7. Known risks / limitations

Status table, current as of this writing. "Tracking card" is the Bear PR
Process board card (project `Sculpt_tool`); "—" means no card exists yet.
Full measurements, rejected approaches, and complete write-ups for every
closed/partially-fixed row below live in `DECISIONS.md`, appended to
after each future card — this table is the answer to "what's currently
broken," not the evidence for it.

| # | Risk / limitation | Status | Tracking card | One-line |
|---|---|---|---|---|
| 1 | Mode B accuracy on extreme shape changes | Open | — | Correspondence can misassign on large body-shape deltas near concave/thin geometry; not solved in v1. |
| 2 | No garment/source-body overlap validation | Open | — | Mode B silently produces a garbage binding if the garment isn't reasonably positioned near its source body at bind time. |
| 3 | Mode A wrongly requires target body to have triangulatable faces | **Open** | `e6763cc5` (Review — PR [#19](https://github.com/Magecatz/Sculpt_tool/pull/19) open, not yet merged) | Regression from the geometry/pipeline extraction; fix ready, not yet on `master`. See DECISIONS.md §5. |
| 4 | Graded pin-weight boundary overshoot | **Open** (partially fixed) | `8432ee45` (Deployed, partial fix) / `e893bfdd` (Backlog, structural redesign) | Worst-case 1.19x-1.43x depending on topology, 25-52% incidence; two dual-trajectory redesigns tried and rejected. See DECISIONS.md §3b-3c. |
| 5 | Batch mode has no NumPy vectorization | Planned, not implemented | `1f564161` (To-Do) | Zero `numpy` imports currently; the smoothing pass's Gauss-Seidel sub-sweeps aren't naively vectorizable regardless. See DECISIONS.md §2. |
| 6 | Smoothing is the pipeline's dominant per-target cost at scale (~19x collision) | Open, measured, unmitigated | `5b232224` (Backlog) | ~4.73s vs. ~0.25s at ~33k/~30k-vertex scale; not yet measured at real batch-collection scale. |
| 7 | Topology-mismatch misdetection (Target Body declared, vertex counts coincide) | Open (soft spot) | — | Two unrelated meshes sharing a vertex count could still misclassify as Mode A; the bind-mode override is the escape hatch. (The related no-Target-Body-declared case is fixed — row 11.) |
| 8 | No garment-vs-garment layering | By design (v1 scope) | — | Collision pass only resolves garment-vs-single-body; multiple layers (e.g. jacket over shirt) out of scope for v1. |
| 9 | Cloth-sim refinement is opt-in only | By design | — | Physically-simulated drape is nondeterministic/substep-sensitive; must never be part of the default unattended batch pipeline. |
| 10 | No UV-space binding (Mode C) | Not scoped | — | Off-body flat-pattern garments unsupported by Mode A or B; plausible future mode. |
| 11 | Bind-time reference geometry read live instead of frozen (Mode B stale source, re-bind reads own output, Mode A no-target trap) | Closed | `756f27f5` (Deployed, PR [#18](https://github.com/Magecatz/Sculpt_tool/pull/18)) | Binding schema v2 freezes all reference geometry at bind time. See DECISIONS.md §4. |
| 12 | Collision push-out direction wrong in concave regions | Closed (2 residuals noted) | `1e252575` (Deployed, PR [#15](https://github.com/Magecatz/Sculpt_tool/pull/15)) | Fixed for 7/9 previously-failing corpus garments; Cube.012 and pants residuals investigated, not newly broken. See DECISIONS.md §1b. |
| 13 | Thin-geometry tunneling | Closed | `c9ff95a5` (Deployed, PR [#7](https://github.com/Magecatz/Sculpt_tool/pull/7)) | Anchor-based ray-cast check pushes tunneled vertices back to the near surface. See DECISIONS.md §1a. |
| 14 | Smoothing curvature-driven shrinkage (~9% tube-radius regression) | Closed | `afefc553` / `4da4de1a` (Deployed, PR #9/#10/#12) | Internal 16-sub-sweep edge correction drops shrinkage to ~0.58%/~0.575% at 10/40 iterations. See DECISIONS.md §2. |
| 15 | Partial pin-weight blend was non-linear (0.76x-0.96x instead of ~weight) | Closed | `1638a2d4` (Deployed, PR [#11](https://github.com/Magecatz/Sculpt_tool/pull/11)) | Outer-iteration blend now matches section 6's documented "fully solved ↔ rigid" behavior. See DECISIONS.md §3a. |
| 16 | `core/` modules called `bpy.context` directly (broke the "pure/testable" claim) | Closed | `cd0d1569` (Deployed, PR [#17](https://github.com/Magecatz/Sculpt_tool/pull/17)) | Depsgraph is now injected by callers; verified zero `bpy.context` under `sculpt_tool/core/`. |
| 17 | No automated test suite | Closed | `3d1fc8bc` (Deployed, PR [#13](https://github.com/Magecatz/Sculpt_tool/pull/13)) | Headless Blender `unittest` harness under `tests/`; see section 9. |

**Note on rows 1, 2, 7-10:** these are long-standing v1 design-scope
limitations rather than defects found in already-built behavior, and
have never had dedicated tracking cards — they're recorded here as
known, accepted gaps a future card could pick up, not regressions.

**Note on row 3:** as of this writing PR #19 is open but unmerged, so
this defect is still live on `master` — a Mode A fit against a
faceless-but-vertexed target body fails where it used to succeed
pre-refactor. Re-check this row's status before relying on it.

## 8. Batch/automated extension

`OT_batch_fit` is the intended batch entry point: point it at a
Collection of target body objects and it runs the full per-target
pipeline (project → collision → smooth → bake) once per object, writing
one `Fitted` shape key per target. It is a thin orchestration layer over
the same `core/` modules the single-target `OT_fit_garment` uses — no
separate batch-specific solver logic — so correctness fixes to the core
pipeline apply to both paths automatically.

The project/collision/smooth sequence itself now lives in
`core/pipeline.py::fit_once(garment, target, params, depsgraph) -> fitted
positions` (Bear PR Process card cd0d1569-36ad-4d79-a82b-6d1115a0bcda),
extracted out of `operators/op_fit.py`'s `execute()` specifically so
`OT_batch_fit` can call it once per target body in its own loop — bake +
report per target is the only logic that needs to live in the batch
operator itself, matching the "no separate batch-specific solver logic"
requirement above literally rather than by convention. `core.smoothing.
RelaxContext.build(garment_obj)`, built once outside the per-target loop
and passed into every `fit_once` call as `relax_ctx`, avoids recomputing
the garment's own adjacency/original-edge-length/pin-weight arrays once
per target — those are constant across an entire batch run against the
same garment. (A per-target `core.geometry.TargetContext`, by contrast,
cannot be hoisted the same way: each target body is different geometry,
so `fit_once` builds one fresh per call, just exactly once per call
rather than multiple times as it used to.)

## 9. Testing

Blender 5.2.1 LTS is available in the development environment
(`C:/Program Files/Blender Foundation/Blender 5.2/blender.exe`), so
every card from here on is verified against a real Blender, not just
statically. Earlier cards (including the two most numerically delicate
passes — collision resolution and smoothing) predate this and shipped
without a Tester able to run anything; this section exists so that gap
doesn't recur and so every quantitative claim added below (or in
`DECISIONS.md`) has a checked-in script behind it, not just testimony
from a session that's since gone.

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
  a fresh throwaway script — that's what let this document's numbers
  drift into unreproducible testimony the first time (see
  `DECISIONS.md`, where those numbers now live).
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
  33k-vertex-garment / 65k-triangle-body scale timing, matching
  DECISIONS.md §2's own repro scale. Run explicitly (`blender --background
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

**Standing rule:** every quantitative claim added to this document or to
`DECISIONS.md` from now on must ship with a checked-in script (a test
under `tests/`, or `tests/perf.py` for a timing figure) that reproduces
it. The 0.58% shrinkage, ~4.73s/~0.25s timings, 46%/1.46x overshoot
figure, and the 0.70-0.91x/etc. pin-blend table now recorded in
`DECISIONS.md` all came from scripts that were never checked in, and
whose sessions are gone — that's what this rule exists to prevent
happening again. Where this card could reproduce one
of those figures with a fresh, checked-in test, it did (tube shrinkage,
tunneling, Mode B round-trip); where a figure was itself a seeded
adversarial sweep whose exact original script/parameters were never
recorded, the checked-in replacement
(`test_smoothing.GradedBoundaryAdversarialSweepTest`) is a fresh
reproduction in the same regime (documented in its own docstring as
such, with its own measured ceiling), not a re-assertion of the original
unreproducible number.
