# Restart Scope — Retarget Conform Rebuild

Status: **DRAFT for review** (2026-09-01). Supersedes the R8 conform
approach. Placement spine (R1–R7) is retained; the surface-conform stage
(fit/bind/collision/smoothing) is discarded and rebuilt.

This document is the "what we keep, what we throw out, and where we're
going" for the re-evaluation. It is grounded in three render experiments run
on the real `Test_Items` corpus (see `renders/`): placement-only, full
pipeline, and the standalone body-morph experiment.

---

## 1. Why we're restarting

The full pipeline makes **unrecoverable** mistakes to fitted garments. The
decisive evidence is the complete five-piece Tech Set → Egirl render: the
`Top` (2,347 verts) balloons into a lumpy mass over the chest and swallows
the `pasties` entirely. No parameter tuning recovers a shape that has been
inflated like that.

**Root cause.** The conform stage established each garment vertex's
correspondence by nearest-point **on the target body**. For a tight piece
whose girth differs from the target, that correspondence is unstable —
adjacent vertices snap to different body regions — and the collision
push-out then inflates the piece. It solved correspondence against the one
surface where correspondence is *least* reliable.

The A/B2/C/D fixes layered onto that stage treated symptoms and made the
code harder to reason about without addressing the root instability.

## 2. Reframed problem statement

The project is **not** "fit a garment to a body." It is **retarget a garment
between two known bodies**, imitating how a designer works:

1. **Position + scale** the garment onto the target using the garment's own
   armature. *(Works today.)*
2. **Elastic grab-sculpt** the cloth to the new base — pull in where the body
   is smaller, push out where it's larger — **while preserving the garment's
   authored shape**. *(This is what we rebuild.)*

Available inputs, per the design intent: the garment's **armature**, the
**garment mesh**, the **base meshes** (source and/or target), and the
garment's existing **weight painting**.

### Correction: the source base

`FBX-Tech Set by Vinuzhka` was authored for **ZinPia_Fit Base HEELED Foot
High Poly** (`ZIN_FIT BASE`), **not** RP Female Base. ZinPia is now in
`Test_Items/Body/`. The garment rig shares ZinPia's bone-naming convention
(`Arm.L`, `Elbow.L`, …); the garment's 89-bone armature is a superset of
ZinPia's 65 bones. The garment's weights therefore live in ZinPia's bone
space. The source base becomes a **first-class input** to conform (it was
effectively unused before — the old bind froze per-vertex offsets instead of
using the source body's actual shape).

**Action item (independent of everything else):** `renders/render.py`
hardcodes `SOURCE_RP = ("RP Female Base_Heeled Foot.fbx", …)`. For the Tech
Set that source is wrong and must be `ZinPia_Fit Base HEELED Foot High
Poly.fbx` / `ZIN_FIT BASE`, or every conform experiment misjudges the field.

## 3. Keep / discard inventory

### Keep — the placement spine (does what's expected)

| Module | Why |
|---|---|
| `core/rig.py` | Rig detection / deforming-armature resolution |
| `core/rig_map.py` | Canonical bone map — *proven necessary* (source `Arm.L` vs target `Arm_L`) |
| `core/pose.py` | `compute_bone_placements` — position + rotation + length-scale |
| `operators/op_pose.py` | `place_garment_onto_rig` — the placement operator |
| `operators/op_bases.py` | Rig/body pickers, garment-rig resolution |
| `core/geometry.py` | Evaluated-mesh / BVH / triangle-frame helpers (reusable substrate) |
| `operators/op_pin_groups.py` | Pin-group concept — becomes anchor/pin authoring for the elastic engine |
| `renders/` harness + `place` mode + `morph_experiment.py` | Our visual regression harness |

### Discard / rebuild — the target-anchored conform (inflates)

| Module | Disposition |
|---|---|
| `core/solver.py` | **Discard.** Mode A/B projection against frozen bind-time anchors. |
| `core/binding.py`, `operators/op_bind.py` | **Reconceive.** "Bind" stops meaning "freeze per-vertex offsets" and starts meaning "record the source base + garment↔source correspondence." |
| `core/pipeline.py` (`fit_once`, `conform_placed`) | **Rewrite** as the new elastic conform. |
| `core/collision.py` | **Demote** to a final thin safety clip only — never a shaping mechanism. |
| `core/smoothing.py` | **Repurpose.** The relax machinery becomes the elastic/ARAP propagation engine (or is replaced by one). |
| `core/alignment.py` | **Keep as guard**, re-evaluate thresholds. |
| `operators/op_fit.py`, `operators/_fit_common.py` | **Rewrite** the conform call; keep the placement-then-conform-then-bake skeleton. |
| `operators/op_batch.py` | **Keep** the orchestration pattern (thin layer over core). |

## 4. Experiment results that drive the direction

**Placement-only render** — garment lands in the right region on every piece
*and keeps its authored shape*; girth is not solved (body pokes through).
Confirms the spine is sound and independent of the broken part.

**Full-pipeline render** — pants improve, but `Top`/`pasties` are destroyed.
Confirms the conform stage does unrecoverable damage to fitted pieces.

**Body-morph experiment** (`renders/morph_experiment.py`, ZinPia → {Egirl,
Venus}, no garment) — reconstructing the source body onto the target skeleton
through the bone map mapped ~22,000/22,033 verts and produced a **smooth,
coherent girth field** over torso/hips/legs, **and it held cross-creator**
(ZinPia → Venus, a different author's 98-bone rig, still 51 paired primary
bones). Caveat: the crude independent-per-bone transfer drooped/splayed the
arms (rest-pose / bone-roll mismatch) — the field is unreliable near the
shoulders unless computed in the placed frame with roll normalization.

**A-vs-B conform experiment** (`renders/ab_conform_experiment.py`, ZinPia →
Venus, on `Top` and `pants`) — the decisive one. A minimal **Direction B**
(place → single nearest-target-surface projection → reapply authored standoff,
**no collision, no smoothing**) produced a clean, girth-correct, shape-
preserving fit on **both** pieces, including the `Top` the old pipeline
destroyed. **Direction A** (source-anchored transfer) also resolved girth but
dragged shoulder/arm "wings" from the crude field and was noisier. Conclusion:
the old inflation came from the **collision + smoothing loop**, not from
target-anchoring; B-minimal is the primary conform (see section 5).

## 5. Direction decision — B-minimal primary (revised)

> **Revised after the A-vs-B experiment** (`renders/ab_conform_experiment.py`,
> ZinPia → Venus, cross-creator, on the two stress pieces `Top` and `pants`).
> The earlier draft made Direction A the quality provider with B as fallback.
> The renders inverted that; the decision below is what we build.

**Primary conform = Direction B, minimal.** Per garment vertex:

1. **Place** the garment on the target via the armature (position + rotation
   + scale) — the existing placement spine.
2. **Project** each placed vertex onto the nearest target-body surface point.
3. **Reapply the authored standoff** — the signed distance the vertex was
   authored to sit off its own body — along the target surface normal, so
   tight pieces stay tight and loose pieces stay loose.

Nothing else. **No collision push-out, no smoothing loop.** That is the whole
mechanism, and on both stress pieces it produces a clean, girth-correct,
shape-preserving fit on the cross-creator target — including the `Top` that
the old pipeline inflated into a blob.

**Key finding — the actual culprit.** The old pipeline's unrecoverable
inflation was NOT caused by target-anchored correspondence. It was caused by
the **collision-resolution push-out + smoothing relaxation loop** layered on
top of it. Removing those and doing a single clean projection fixes the
failure. So:

- **Collision / elastic (C) are OPTIONAL polish, off by default.** They return
  only for a specific demonstrated case (deep interpenetration a single
  projection leaves, or residual surface noise), always gated behind the
  "loses authored identity" acceptance test. They are the thing that broke it
  last time; they are guilty until proven necessary per-case.
- **Direction A is demoted to a secondary tool** for cases where the
  target-nearest correspondence is genuinely ambiguous (layered/overlapping
  garments, deep concavities) — and only where the source base exists AND the
  source→target field is cleaned up (arm-roll normalization; A currently drags
  "wings" from the crude reconstruction near the shoulders). Its theoretical
  stability advantage did not beat a clean target projection on real pieces.

**Standoff and the source base — honest nuance.** The standoff in step 3 was
measured from the **source base** (ZinPia) in the experiment, so B as tested
is not fully source-independent. Because armature placement preserves the
garment's body-relative offset, the standoff can instead be measured from the
**placed** garment against the target at placement time — source-free. That
source-free variant is validated in P2 below; source-measured standoff is the
high-quality path when the source base is available.

**Placement spine** — unchanged.

## 6. Phased rebuild plan (revised to B-minimal)

- **P0 — Harness truth.** Fix the source base in the render harness (ZinPia
  for Tech Set). *(The `place` and `ab_conform` render modes already exist and
  judge on the real corpus.)*
- **P1 — Core B conform (pure logic).** `core/conform.py`, testable outside
  Blender: `authored_standoff(rest_positions, source_ctx)` and
  `project_to_target(placed_positions, standoff, target_ctx)` →
  fitted world positions. Single projection, no collision/smoothing. Unit
  tests on synthetic tubes/grids (girth up/down, tight vs loose standoff).
- **P2 — Operator + source-free standoff.** New `op_conform` (place via the
  spine → `core.conform` → bake Shape Key), wired into `ui_panel`. Validate
  the **source-free** standoff variant (measured from the placed garment)
  against the source-measured one on Tech Set → {Egirl, Venus}; keep whichever
  holds, or keep both with source as the quality path.
- **P3 — Full-outfit acceptance.** Run the whole five-piece Tech Set → Venus
  and {Egirl, Fantasy} through `op_conform`; every piece must keep its
  authored identity (the `Top`-balloon gate). Add a `conform` render mode.
- **P4 — Optional polish, off by default.** Re-introduce collision clip /
  light elastic ONLY for a specific piece that P3 shows a single projection
  can't handle, each behind the acceptance gate.
- **P5 — Batch + cleanup.** Re-add a Batch path over `op_conform`; prune
  now-dead settings/props and the stale pipeline prose in kept docstrings.

## 7. Open questions / tests

- **Source-free standoff (P2).** Does standoff measured from the *placed*
  garment against the target match the source-measured standoff closely
  enough to drop the source-base dependency for tight/loose authoring?
- **Open-edge rims under a single projection.** Necklines/hems/cuffs are the
  places a bare projection is most likely to leave a ragged rim (no smoothing
  to relax it). Watch these specifically in P3; a boundary-only relax may be
  the one piece of "polish" that earns its way back in first.
- **Deep interpenetration / concavities.** Where a single nearest-surface
  projection maps two garment layers to the same body point (armpits, crotch,
  overlapping straps) — does B alone hold, or is this the case that needs
  optional collision/elastic polish (P4)?
- **A field cleanup (only if A is needed).** Arm-roll normalization + placed-
  frame computation to remove the shoulder "wings", should a secondary
  A path be required for ambiguous-correspondence garments.

## 8. Validation harness

Every phase is judged **visually on the full five-piece Tech Set**, with
`Top`/`pasties`/`Straps` explicitly watched (they were omitted from the
original two-piece renders and hid the worst failure). Render modes:

- `place` — placement only (baseline; already added).
- `morph_experiment.py` — source→target field sanity (already added).
- `conform` (P0) — the new elastic conform, per phase.

A piece is "regressed" if it loses authored identity (the `Top`-balloon
test). That is the acceptance gate the old pipeline failed.
