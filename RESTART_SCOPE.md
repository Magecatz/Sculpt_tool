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

**Body-morph experiment** (`renders/morph_experiment.py`, ZinPia → Egirl, no
garment) — reconstructing the source body onto the target skeleton through
the bone map mapped 21,981/22,033 verts and produced a **smooth, coherent
girth field** over torso/hips/legs. This validates that a **source-anchored**
deformation field is well-behaved — the opposite of the old target-anchored
scatter. Caveat: the experiment's *crude independent-per-bone* transfer
drooped the arms (rest-pose / bone-roll mismatch); the production placement
operator already handles this via chained rigid+scale, so the field must be
computed **in the placed frame**, not by independent per-bone transfer.

## 5. Direction decision — C engine, A/B anchors

A **combination**, with graceful degradation when the source base is absent:

- **Engine — Direction C (elastic / ARAP grab-propagation).** Always
  available. Move a sparse set of anchor correspondences to the target and
  propagate through the mesh with as-rigid-as-possible / elastic falloff, so
  the rest of the surface follows smoothly and local shape is preserved.
  Needs only the garment mesh + target body. This is the always-on
  mechanism and matches the designer's grab-brush mental model.

- **Anchors — best available source:**
  - **Source base present** (Tech Set and most corpus) → **Direction A**
    supplies high-quality anchors from the smooth source→target field,
    computed in the placed frame. Best quality.
  - **Source base absent** → fall back to target-contact anchors (tight
    regions detected from the *placed* garment's proximity) plus **Direction
    B** weight-attribution to keep anchors regionally coherent.

- **Collision** — final thin clip only. Cannot shape, cannot inflate.

- **Placement spine** — unchanged.

Rationale: the same engine handles both the source-present and source-absent
cases; quality degrades instead of failing. This contains the "original base
isn't always available" risk, which is the main weakness of a pure Direction
A approach.

## 6. Phased rebuild plan

- **P0 — Harness truth.** Fix the source base in the render harness (ZinPia
  for Tech Set). Add a `conform` render mode next to `place`, so every step
  is judged on the full five-piece outfit with the small pieces watched.
- **P1 — Elastic engine (C), anchor-agnostic.** Build the ARAP/elastic
  propagation core in `core/` (pure logic, testable): given a mesh + a set of
  (vertex → target position) anchors + pin weights, produce a
  shape-preserving deformation. Prove it on synthetic anchors first.
- **P2 — Direction A anchor provider.** Compute the source→target field in
  the placed frame (reuse placement machinery; add bone-roll normalization).
  Feed it as anchors to P1. Validate on Tech Set → {Egirl, Fantasy, Venus}.
- **P3 — Source-absent fallback (B).** Target-contact + weight-attributed
  anchors for garments with no source base. Validate on a corpus piece whose
  source base we deliberately withhold.
- **P4 — Collision clip + boundary polish**, demoted to final safety only.
- **P5 — Wire operators.** Rewrite `op_fit` / `_fit_common` conform call;
  reconceive `op_bind` as source-correspondence recording; update Batch.

## 7. Open questions / tests

- **Weight-map-across assumption.** Does the garment's existing weight
  painting map acceptably onto the target base via the bone map? The
  placement renders suggest yes for gross deformation; needs explicit
  per-region validation before P2 leans on it.
- **Bone-roll normalization.** Required to compute the field in the placed
  frame without the arm-droop artifact seen in the experiment.
- **ARAP performance.** Largest pieces are ~18k verts (pants); confirm the
  elastic solve is interactive-ish or acceptable for a bake.
- **Anchor selection heuristic.** How sparse can anchors be before shape
  drifts? Where do we place them (tight-contact detection vs. uniform
  sampling vs. source-field-driven)?
- **Mix tuning.** When both source-field and contact anchors exist, how do we
  blend them? (Another thing to test, per the design discussion.)

## 8. Validation harness

Every phase is judged **visually on the full five-piece Tech Set**, with
`Top`/`pasties`/`Straps` explicitly watched (they were omitted from the
original two-piece renders and hid the worst failure). Render modes:

- `place` — placement only (baseline; already added).
- `morph_experiment.py` — source→target field sanity (already added).
- `conform` (P0) — the new elastic conform, per phase.

A piece is "regressed" if it loses authored identity (the `Top`-balloon
test). That is the acceptance gate the old pipeline failed.
