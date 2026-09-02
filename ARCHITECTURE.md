# Sculpt Tool — Architecture

Blender add-on that retargets a clothing/garment mesh from the body it
was authored for onto a *different* body. Every garment is modelled to
fit one specific rigged body — its **base** (e.g. `FBX-Tech Set by
Vinuzhka` is authored for the base `RP Female Base_Heeled Foot.fbx`).
The tool's job is to make that garment properly wear on a different
target base (e.g. `vrbase_Egirl_Heeled Foot.fbx`) automatically —
replacing the manual re-sculpt an artist would otherwise do by hand (the
`Test_Items/Example1.blend` reference is exactly such a hand-fit). It
does this by: posing the garment onto the target base through the two
rigs' shared skeleton, then conforming its surface — pushing the garment
out of interpenetration, following the target base's contours, and
preserving the garment's own volume and silhouette (sleeves, collars,
hems stay garment-shaped rather than collapsing flat). Designed to also
support batch/automated use — retargeting one garment across many bases
without a manual sculpt pass per pair.

**Intended end-to-end pipeline is two stages: pose, then sculpt.**

1. **Pose** (skeleton does the gross placement) — match the garment
   rig's bones to the target base rig's bones and transfer the base's
   pose onto the garment via its own skin weights, so each sleeve lands
   on the matching arm before any surface math runs.
2. **Sculpt** (surface does the fine conforming) — the bind → project →
   collision → smooth → bake pipeline documented below conforms the
   posed garment to the base's actual proportions.

**Stage 1 is not built yet** — this is the single most important gap in
the tool as it currently stands: without it the sculpt stage alone can
only slide vertices onto the nearest body surface, which puts a sleeve on
the torso whenever the garment and base don't already share a pose. It is
scoped across roadmap cards R1–R6 (board anchor: card `9df4bc00`); see
section 1's alternatives note, section 7 row 18, and DECISIONS.md §6.
Everything from section 2 onward describes the sculpt stage, which is
what exists today.

This started as the project's first architecture document, written
before any add-on code existed. That is no longer true: `sculpt_tool/`
is now 3,000+ lines of Python across `core/`, `operators/`, and the UI
panel, plus a `tests/` suite (see section 9). Each numbered module below
maps to one or more Bear PR Process cards on the shared board (project
`Sculpt_tool`); section 7 tracks current known risks and section 9
covers testing.

> **⚠️ Conform-rebuild restart (2026-09).** The surface-conform stage was
> **rebuilt from scratch** — the old binding + fit pipeline (Mode A/B bind,
> project against a frozen anchor, collision push-out, smoothing relaxation)
> made unrecoverable mistakes on fitted garments and was **discarded**. The
> **placement spine** (rig detection, canonical bone map, armature placement)
> is retained and was improved. This document has been updated for the new
> design; **`RESTART_SCOPE.md` is the authoritative account** of what was
> kept, what was thrown out, the experiments that drove the decision, and the
> two placement-stage bugs (rest-pose transfer, joint-span scaling) fixed
> along the way. Sections 2/3/5/6 below describe the current lean conform;
> `DECISIONS.md` still carries the historical record of the removed pipeline.

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
- **Armature-driven initial posing as a pre-stage** — *now Stage 1 (see
  the intro and section 3 step 0), implemented, not a rejected
  alternative.* Transfers the target base's pose onto the garment through
  the two rigs' shared skeleton (bone-name-matched via `core/rig_map.py`,
  normalizing naming differences across rig families) and the garment's own
  skin weights, before the surface-projection refinement runs. This is how
  a real clothing pipeline gets a garment *grossly* into place — the
  skeleton carries the fabric along each limb — after which the sculpt
  stage refines the drape. Built and wired as the fit's stage 0 across
  roadmap cards R1–R5 (`core/rig.py`, `core/rig_map.py`, `core/pose.py`,
  `operators/op_pose.py`; anchor card `9df4bc00`). One remaining coupling
  keeps this from being a *complete* retarget onto a non-rest base — the
  surface projection still uses the frozen bind-time correspondence rather
  than re-deriving it from the posed garment — tracked as a follow-up; see
  section 3 step 0, section 7 row 18, and DECISIONS.md §6.

The chosen approach reuses Blender's low-level geometry primitives
(`BVHTree` nearest-surface queries, barycentric coordinates,
`mathutils` vector/normal math) rather than any one high-level modifier,
because no single built-in modifier captures "preserve per-region
garment offset while following a different body's contours."

## 2. Data model — the source base and the standoff

*(The old Mode A / Mode B binding data model — a per-vertex correspondence
record frozen on the garment mesh at bind time — was removed in the conform
rebuild. There is no bind step and no persisted binding attributes. The
historical writeup is kept in `DECISIONS.md` §4.)*

The retarget is now framed as **between two known bodies**: the garment fits
a **source base** (the body it was authored for) and is retargeted onto a
**target base**. The only per-garment "authoring" datum the conform needs is
the **standoff** — the signed distance each garment vertex was authored to
sit off its own body, along the body-surface normal (positive = loose/off the
body; ~0 = hugging; negative = cinched into the surface). It is computed
**on demand at conform time**, not stored:

- **Source-measured (preferred).** When the user supplies the source base
  mesh (`settings.source_body`), each garment vertex's standoff is measured
  against the source body's surface (`core.conform.authored_standoff`, via a
  `TargetContext` BVH). This is the faithful value — a loose strap keeps its
  large standoff, a tight waistband ~0.
- **Source-free fallback.** When no source base is available, standoff is
  approximated from the *placed* garment against the target: how far each
  placed vertex sits **outside** the target surface, with interpenetration
  clamped to 0 (`core.conform.placed_standoff`). Loose regions genuinely off
  the body are preserved; girth interpenetration is pulled onto the surface.

Nothing is persisted on the garment mesh except the conform **output** — a
`Fitted` shape key (section 3). The source base is a live input, not a frozen
snapshot, so there is no schema-version or bind-time-freeze machinery.

## 3. Conform pipeline (applied per target body)

The pipeline (`operators/op_conform.py`, `OT_conform`) is deliberately small:
**place → standoff → project → bake.** No collision push-out, no smoothing
relaxation — the A-vs-B experiment showed those were the cause of the old
pipeline's inflation, not the correspondence itself (RESTART_SCOPE.md §5).

1. **Armature placement** — when the garment and target base are both rigged
   and `auto_pose_transfer` is on, the garment's own armature is placed onto
   the target base's skeleton, bone by bone through the canonical humanoid
   bone map (`core/rig_map.py`), the garment deforming through its own skin
   weights. Placement is a full per-bone transform — **position + rotation +
   along-bone length-scale** (`core/pose.compute_bone_placements`) — so each
   clothing region is moved, turned, and sized to the matching part of the
   target base. Two properties matter for cross-base correctness:

   - **Rotation aims along the target bone's direction** via a minimal-arc
     swing from the garment bone's own rest direction — so a garment authored
     in one **rest pose** (T-pose) correctly follows a target base in a
     *different* rest pose (A-pose), while copying none of the target's
     roll/axis convention (no skinned-region twist). Co-posed bones get an
     identity swing and are unchanged. *(Fixes the "sleeves floated off the
     arms on Venus" bug — RESTART_SCOPE.md §9.)*
   - **Length-scale uses the target's joint-to-joint span**, not the target
     bone's own length, so a base whose primary bones stop short of the next
     joint (the segment carried by twist bones, e.g. Venus's forearm) does
     not under-scale the garment. `max`-guarded so bases that already span
     their segments are unchanged. *(Fixes "sleeves/pants too short".)*

2. **Standoff** — the garment's authored body-relative standoff (section 2):
   source-measured when a source base is set, else the source-free placed
   approximation.

3. **Project** — each placed vertex is projected onto the nearest target-body
   surface point and its standoff reapplied along that surface normal
   (`core.conform.project_to_target`). This single step resolves girth (a
   fatter/thinner target moves the surface and the garment follows) and
   preserves the garment's silhouette (tight stays tight, loose stays loose).

4. **Bake** — result is written to a Shape Key named `Fitted` on the garment
   object (created fresh or overwritten), never mutating base mesh data, and
   the garment's live Armature modifier is muted so the placement (already in
   the bake) is not applied twice. A Shape Key is Blender's idiomatic
   non-destructive equivalent of a live modifier (the Python API cannot
   author a new C-level modifier-stack entry) — undoable, blendable with
   animation, no custom plumbing.

*(Optional collision/elastic polish for genuinely-loose or deeply-
interpenetrating garments is deferred until a specific case demonstrably
needs it — RESTART_SCOPE.md §5. A boundary-only rim relax was trialled and
declined: the residual raggedness on the test garment is mostly authored
frayed-edge detail, not a conform defect.)*

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
  - `OT_detect_rigs` + `OT_compute_bone_map` (+ bone-override add/remove) —
    rig detection and the canonical garment↔target-base bone map
    (`operators/op_bases.py`).
  - `OT_pose_to_target` — the standalone placement stage (position + rotation
    + scale), runnable on its own for inspection (`operators/op_pose.py`).
  - `OT_conform` — the full conform pipeline (place → standoff → project →
    bake) against a chosen target body (`operators/op_conform.py`).
  - Small helper operators for pin vertex-group management (create/assign/
    remove a pin group from the active selection).

  *(The old `OT_bind_garment` / `OT_fit_garment` / `OT_batch_fit` were removed
  with the binding + fit pipeline. A Batch path over `OT_conform` is planned —
  section 8.)*
- **UI:** a single N-sidebar panel (3D Viewport, "Sculpt Tool" tab) with
  sections for Base Retargeting (source/target base rig pickers, Detect Rigs,
  Compute Bone Map + manual overrides, Place onto Target Base), Conform
  (Target Body + optional Source Base pickers, Conform button), and Pin
  Regions (vertex-group list, standard Blender weight-painting workflow).
- **Settings:** a `PropertyGroup` (`properties.SCULPTTOOL_PG_settings`)
  holding the source/target body pointers, the source/target base-rig
  pointers, the bone-map overrides + summary, and the `auto_pose_transfer`
  toggle, attached to the garment `Object` so settings travel with the
  object, not just the scene. *(The old bind-mode override and the fit
  numeric parameters — offset scale, collision margin, smoothing iterations —
  were removed with the pipeline that used them; the conform takes no numeric
  parameters.)* It does **not** hold pin
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
  properties.py           PropertyGroup: source/target body + base-rig refs, bone-map overrides, auto_pose_transfer (no pin-group field -- see section 4)
  ui_panel.py             N-sidebar panel: Base Retargeting / Conform / Pin Regions
  operators/
    op_bases.py            OT_detect_rigs + OT_compute_bone_map + bone-override ops
    op_pose.py              OT_pose_to_target (placement stage) + place_garment_onto_rig
    op_conform.py           OT_conform (place -> standoff -> project -> bake)
    op_pin_groups.py        pin vertex-group helper operators
  core/
    rig.py                  rig/armature awareness (deforming-armature resolution, bone names)
    rig_map.py              canonical humanoid bone map across naming conventions
    pose.py                 compute_bone_placements (swing rotation + joint-span scale) + compute_pose_rotations
    geometry.py             shared geometry primitives + TargetContext (target body's evaluated geometry/BVH, built once per conform)
    conform.py              authored_standoff / placed_standoff / project_to_target (Direction-B conform)
    smoothing.py            pin-weighted relaxation + boundary helpers (retained; not used by the default conform)
    alignment.py            gross pose/position mismatch guard (retained pure logic; not currently wired)
    quality.py              surface-quality metrics
    storage.py              Fitted shape-key name + residual attribute helpers
```

*(Removed in the rebuild: `binding.py`, `solver.py`, `collision.py`,
`pipeline.py` — the old bind/project/collision/fit pipeline.)*

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

- **Source / Target Body** — the meshes the garment was authored for (used
  for source-measured standoff; optional) and the body to retarget onto.
- **Source / Target Base Rig** — the armatures the placement bridges (usually
  auto-filled by Detect Rigs), plus manual bone-map overrides.
- **Auto Pose Transfer** — whether Conform runs the armature placement stage
  before the surface conform (on by default; a no-op for a co-posed pair).

  *(The old fit numeric parameters — offset/thickness scale, collision margin,
  smoothing iterations — were removed with the pipeline that used them.)*
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
| 3 | Mode A wrongly requires target body to have triangulatable faces | Closed | `e6763cc5` (Deployed, PR [#19](https://github.com/Magecatz/Sculpt_tool/pull/19)) | Regression from the geometry/pipeline extraction; lazy `TargetContext` triangle/BVH construction fixes it. See DECISIONS.md §5. |
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
| 18 | No armature-driven initial posing / placement (Stage 1) | **Implemented** + deformation fixes (A/B2/C) | R1–R8 deployed: `062cfedd`/`1b7b56eb`/`cfa7e4aa`/`812a0a6a`/`450bdee9`/`c342ccc2`/`19fe6586`/`a541e4cb`; deformation fixes A/B2/C (DECISIONS.md §7) | Stage 1 exists and is wired as the fit's stage 0: rig awareness (`core/rig.py`) + canonical bone mapping across naming families (`core/rig_map.py`) + **full placement** — position + rotation + along-bone length-scale (`core/pose.py`/`op_pose.py`, R7). **Fix A** made the placement rotation rest-orientation-compensated (was slamming absolute target orientation → up to ~143° twist on helper bones; the main cause of mangled renders). **Fix B2** made `conform_placed` re-derive correspondence from the placed positions and reapply the garment's authored standoff (loose stays loose, tight conforms) instead of shrink-wrapping. **Fix C** added a surface-quality regression gate (`core/quality.py`: edge distortion + looseness preservation; `tests/test_quality.py`, real-asset gate in `tests/retarget_repro.py`, and the placement twist test in `tests/test_placement.py`). Real-asset regression (`tests/retarget_repro.py`): all 9 Tech-Set×base retargets on-body, looseness preserved 0.54–0.89 (floor 0.40, was ~0.27 pre-B2); retargeted Top lands 0.46% of body-diagonal from the manual `Example1.blend` fit (manual's own standoff 0.67%). **Remaining:** girth is handled by the surface passes, not the armature; loose open boundaries still carry residual distortion. See DECISIONS.md §6–§7 and section 3 step 0. |

**Note on rows 1, 2, 7-10, 18:** these are long-standing v1 design-scope
limitations rather than defects found in already-built behavior. Rows
1, 2, 7-10 have never had dedicated tracking cards — they're recorded
here as known, accepted gaps a future card could pick up. Row 18 is the
same shape (an assumed-but-unenforced precondition on the *input*, a
close relative of row 2's overlap gap) but now has a card (`9df4bc00`),
because it was surfaced as a concrete usability failure on real rigged
assets rather than reasoned about in the abstract — see DECISIONS.md §6
for that investigation and an honest calibration of how far the failure
actually goes.

**Note on row 3:** PR #19 has since merged and card `e6763cc5` is
Deployed — this row was corrected during Review (2026-08-31) from the
Developer's original "Open, PR unmerged" text, which had gone stale
between when the Developer's worktree branched and when this restructure
reached Review. See DECISIONS.md §5.

## 8. Batch/automated extension

> **Status: not yet reimplemented.** `OT_batch_fit` and its shared
> `place_and_conform` sequence were removed with the old fit pipeline. A Batch
> path over `OT_conform` is planned but not built. The design intent below is
> retained as the target for that work — a thin orchestration layer that calls
> the same `core.conform` per target with no batch-specific logic.

`OT_batch_fit` is the intended batch entry point: point it at a
Collection of target body objects and it runs the full per-target
pipeline (pose → project → collision → smooth → bake) once per object,
writing one `Fitted_<target>` shape key per target. It is a thin
orchestration layer over the same `core/` modules the single-target
`OT_fit_garment` uses — no separate batch-specific solver logic — so
correctness fixes to the core pipeline apply to both paths automatically.

As of roadmap R5, batch also runs the pose-transfer stage 0 (section 3
step 0) **per target base**: for each target body it resolves that body's
own rig, resets the garment armature to rest, and poses the garment onto
that target base before its fit — so one garment retargets across a
Collection of differently-posed bases in a single run, one posed-and-
fitted shape key each. A no-op for a target base already in the garment's
pose (the whole rest-pose corpus), so batch output there is unchanged.

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
- `tests/corpus_repro.py` / `tests/retarget_repro.py` — **opt-in only**,
  needing the gitignored `Test_Items/` assets (they exit 0 with SKIPPED
  when absent). `corpus_repro.py` is the collision-residual A/B; and
  `retarget_repro.py` (roadmap R6) is the real-asset retarget regression:
  it retargets the Tech Set onto all three bases (Egirl / Fantasy / Venus,
  exercising the dot / underscore / Venus naming families) through the full
  deployed pipeline via the operators, and gates on bone-map coverage,
  bind/fit completion, on-body placement, and a lenient residual-
  penetration ceiling. Its always-run companion is `tests/test_retarget.py`
  (a synthetic two-rig, two-naming fixture) so the naming-mapping-in-
  retarget path can't silently regress even without the real assets.

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
