"""Opt-in real-asset retarget regression for card c342ccc2 (roadmap R6).

Retargets **FBX-Tech Set by Vinuzhka** (authored for RP Female Base) onto
all three target bases -- **vrbase_Egirl**, **vrbase_Fantasy**, **Project
Venus** -- exercising all three bone-naming families (dot / underscore /
Venus joint names) through the full deployed pipeline (canonical bone map
-> pose stage 0 -> Mode B bind/project -> collision -> bake), driven by the
real operators exactly as a user clicks them.

NOT part of the fast suite (``run_tests.py`` does not discover this --
matches ``tests/perf.py`` / ``tests/corpus_repro.py``). It needs the real
gitignored ``Test_Items/`` assets; absent those it exits 0 with SKIPPED.
The fast-suite naming-mapping-in-retarget guard is ``tests/test_retarget.py``.

Usage (from the repo root)::

    blender --background --factory-startup --python tests/retarget_repro.py

WHAT IT CHECKS (the card's "usable result across all three naming families")
per (garment piece x base):
  1. the canonical bone map resolves the FULL primary humanoid chain
     (0 gaps) between the garment rig and that base's rig;
  2. Bind and Fit both complete (FINISHED) through the operators;
  3. the fitted garment stays ON the base (centroid inside the base bbox)
     and its residual body penetration -- measured with an INDEPENDENT ray-
     parity test, not collision.py's own -- is below a lenient ceiling.
A regression in any of these fails the run (exit 1).

GROUND TRUTH: ``Test_Items/Example1.blend`` holds the user's manual fit
(``Tech Outfit`` on a posed Egirl ``BODY``). A rigorous vertex comparison
isn't yet feasible -- the manual outfit is one 52k combined mesh on a
POSED body, and a fully-correct fit onto a non-rest base is the tracked
follow-up (board card a541e4cb, ARCHITECTURE.md sec 7 row 18). So the
Example1 section is INFORMATIONAL: it prints the ground-truth garment's
mean standoff from the body as a reference for what a good fit looks like.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
for _p in (REPO_ROOT, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import common  # noqa: E402

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import geometry, quality, rig, rig_map, storage  # noqa: E402

SOURCE_FBX = "RP Female Base_Heeled Foot.fbx"
SOURCE_OBJ = "Body"

# (fbx, base body object name, display name)
BASES = [
    ("vrbase_Egirl_Heeled Foot.fbx", "BODY", "Egirl (_L/_R)"),
    ("vrbase_Fantasy_Heeled Foot.fbx", "BODY", "Fantasy (_L/_R)"),
    ("Project Venus_v2.02.fbx", "Body", "Venus (Upper_Arm/.L)"),
]
# Tech Set pieces exercised (torso + sleeves + legs).
GARMENTS = [
    ("Top by Vinuzhka", "Top"),
    ("Sweater by Vinuzhka", "Sweater"),
    ("pants by Vinuzhka", "Pants"),
]

# Lenient ceilings: catch gross regressions, not normal variation.
MAX_PENETRATION_FRACTION = 0.25
# Surface-quality gate (fix C): looseness preservation. For garments with a
# genuinely loose region (open panels, straps standing well off the body),
# the median fitted/authored standoff of those loose vertices must stay
# above this floor -- i.e. the fit must NOT shrink-wrap the loose geometry
# flat onto the body (the pre-B2 failure). Measured Tech Set sweater -> Egirl:
# ~0.27 before fix B2, ~0.54 after; floor set between them with headroom.
# Only gated for pieces that actually have >= MIN_LOOSE_VERTS loose vertices
# (a tight piece has no loose region to preserve, so it's n/a, not a fail).
MIN_LOOSENESS_PRESERVED = 0.40
MIN_LOOSE_VERTS = 100
# Edge-length distortion is REPORTED (Distort% column) as a tracking number
# but not gated: it's a clean signal for stretch/scatter, but on a loose
# OPEN garment an over-smoothed collapse can score as low as a clean fit, so
# it doesn't cleanly separate good from bad there. The looseness floor above
# and tests/test_placement's twist test are the real fix-A/B2 gates.
_PARITY_DIR = Vector((1.0, 2.0, 3.0)).normalized()


def _find_test_items():
    env = os.environ.get("SCULPT_TOOL_TEST_ITEMS")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(REPO_ROOT / "Test_Items")
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=True,
        )
        common_dir = proc.stdout.strip()
        if common_dir:
            candidates.append(Path(common_dir).resolve().parent / "Test_Items")
    except Exception:
        pass
    for c in candidates:
        if (c / "Body").is_dir() and (c / "Clothing").is_dir():
            return c
    return None


def _base_name(name):
    stem, sep, suffix = name.rpartition(".")
    return stem if (sep and suffix.isdigit()) else name


def _import_named(fbx_path, object_name):
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(filepath=str(fbx_path))
    imported = [o for o in bpy.data.objects if o.name not in before]
    match = next((o for o in imported if o.name == object_name), None)
    if match is None:
        match = next((o for o in imported if _base_name(o.name) == object_name), None)
    if match is None:
        raise RuntimeError(f"{object_name!r} not in {fbx_path.name}")
    # Keep the matched mesh AND its deforming armature; drop the rest.
    keep = {match}
    arm = rig.deforming_armature(match)
    if arm is not None:
        keep.add(arm)
    for o in imported:
        if o not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    return match, arm


def _parity_inside(point, bvh, max_hits=64):
    origin = point
    hits = 0
    for _ in range(max_hits):
        loc, _n, idx, _d = bvh.ray_cast(origin, _PARITY_DIR)
        if idx is None:
            break
        hits += 1
        origin = loc + _PARITY_DIR * 1e-6
    return hits % 2 == 1


def _fitted_world(garment):
    key = garment.data.shape_keys.key_blocks.get(storage.FITTED_SHAPE_KEY_NAME)
    if key is None:
        return None
    m = garment.matrix_world
    return [m @ kp.co for kp in key.data]


def _centroid(points):
    n = len(points)
    return Vector((sum(p.x for p in points) / n,
                   sum(p.y for p in points) / n,
                   sum(p.z for p in points) / n))


def main():
    test_items = _find_test_items()
    if test_items is None:
        print("SKIPPED: Test_Items/ not found -- opt-in real-asset regression.")
        return 0

    was_registered = hasattr(bpy.types.Object, "sculpt_tool")
    if not was_registered:
        sculpt_tool.register()

    rows = []
    ok = True
    try:
        for base_fbx, base_obj, base_label in BASES:
            source_body, _sa = _import_named(test_items / "Body" / SOURCE_FBX, SOURCE_OBJ)
            source_body.name = "SourceRP"
            base_body, base_rig = _import_named(test_items / "Body" / base_fbx, base_obj)

            for obj_name, disp in GARMENTS:
                garment, garment_rig = _import_named(
                    test_items / "Clothing" / "FBX-Tech Set by Vinuzhka.fbx", obj_name
                )

                # 1) bone-map coverage on the REAL rigs.
                bmap = rig_map.build_bone_map(
                    rig.bone_names(garment_rig), rig.bone_names(base_rig)
                )
                gaps = rig_map.missing_primary_bones(bmap)

                # 2) retarget through the operators.
                s = garment.sculpt_tool
                s.source_body = source_body
                s.target_body = base_body
                s.bind_mode_override = 'MODE_B'
                s.target_base_armature = base_rig
                s.use_collision_resolution = True
                # Recommended config: a few smoothing passes relax the
                # residual reprojection/collision noise the offset-preserving
                # conform (fix B2) leaves (raw = 0 is measurably rougher).
                s.smoothing_iterations = 8
                bpy.context.view_layer.objects.active = garment
                garment.select_set(True)
                try:
                    bind_r = bpy.ops.sculpttool.bind_garment()
                    fit_r = bpy.ops.sculpttool.fit_garment()
                except RuntimeError as exc:
                    bind_r, fit_r = "RAISED", str(exc)[:40]

                # 3) usability: on-body + residual penetration + surface quality.
                pen_frac = float("nan")
                cz_frac = float("nan")
                dist_frac = float("nan")
                loose_preserved = None  # None = no loose region to gate
                on_body = False
                fitted = _fitted_world(garment) if fit_r == {'FINISHED'} else None
                if fitted:
                    depsgraph = bpy.context.evaluated_depsgraph_get()
                    ctx = geometry.TargetContext.build(base_body, depsgraph)
                    bvh = ctx.bvh
                    lo = Vector((min(p[i] for p in ctx.positions) for i in range(3)))
                    hi = Vector((max(p[i] for p in ctx.positions) for i in range(3)))
                    c = _centroid(fitted)
                    on_body = all(lo[i] - 0.1 <= c[i] <= hi[i] + 0.1 for i in range(3))
                    # Position/scale (R9): the fitted garment's centroid height
                    # as a fraction of the target BASE's height -- placement
                    # should put it at a sensible on-body height (not down at
                    # the feet / floating), tracking the target's proportions.
                    body_height = hi.z - lo.z
                    cz_frac = (c.z - lo.z) / body_height if body_height > 1e-6 else 0.0
                    stride = max(1, len(fitted) // 3000)
                    sample = fitted[::stride]
                    pen = sum(1 for p in sample if _parity_inside(p, bvh))
                    pen_frac = pen / len(sample)

                    # Surface quality (fix C): per-edge length distortion of
                    # the fitted garment vs its own authored mesh. Reference
                    # and fitted are both world-space, so the object matrix
                    # cancels; the median absorbs the placement's overall
                    # scaling, leaving only LOCAL mangling (twist boundaries,
                    # scatter, shrink-wrap collapse).
                    matrix = garment.matrix_world
                    reference = [matrix @ v.co for v in garment.data.vertices]
                    edges = [(e.vertices[0], e.vertices[1]) for e in garment.data.edges]
                    dist_frac = quality.edge_distortion(reference, fitted, edges).distorted_fraction

                    # Looseness preservation (fix B2 gate): loose authored
                    # vertices must not be collapsed onto the target body.
                    binding = storage.read_mode_b_binding(garment)
                    authored = [abs(n) for n in binding["normal_offset"]]
                    fitted_standoff = []
                    for p in fitted:
                        loc, _n, idx, _d = bvh.find_nearest(p)
                        fitted_standoff.append((p - loc).length if idx is not None else 0.0)
                    body_diag = (hi - lo).length
                    loose_preserved = quality.looseness_preservation(
                        authored, fitted_standoff, loose_fraction_of=body_diag,
                        min_loose=MIN_LOOSE_VERTS,
                    )

                height_ok = 0.1 <= cz_frac <= 0.98
                # Only gate looseness when there IS a loose region (None = n/a).
                looseness_ok = loose_preserved is None or loose_preserved >= MIN_LOOSENESS_PRESERVED
                passed = (
                    not gaps and bind_r == {'FINISHED'} and fit_r == {'FINISHED'}
                    and on_body and height_ok and pen_frac <= MAX_PENETRATION_FRACTION
                    and looseness_ok
                )
                ok = ok and passed
                rows.append((base_label, disp, len(gaps), bind_r == {'FINISHED'},
                             fit_r == {'FINISHED'}, on_body, cz_frac, pen_frac,
                             dist_frac, loose_preserved, passed))

                bpy.data.objects.remove(garment, do_unlink=True)
                bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

            common.clear_scene()

        # --- Report ------------------------------------------------------
        print("\n" + "=" * 92)
        print("Real-asset retarget regression -- Tech Set -> Egirl/Fantasy/Venus (card c342ccc2)")
        print("Pipeline: canonical bone map -> pose stage 0 -> Mode B bind/fit/collision, via operators")
        print("=" * 92)
        hdr = (f"{'Base':<22}{'Garment':<10}{'MapGaps':>8}{'Bind':>6}{'Fit':>5}"
               f"{'OnBody':>8}{'HeightF':>9}{'Penet%':>8}{'Distort%':>9}{'Loose':>7}{'':>4}")
        print(hdr)
        print("-" * len(hdr))
        for (base_label, disp, gaps, bind_ok, fit_ok, on_body,
             cz_frac, pen_frac, dist_frac, loose_preserved, passed) in rows:
            pen = "n/a" if pen_frac != pen_frac else f"{pen_frac*100:.1f}"
            czf = "n/a" if cz_frac != cz_frac else f"{cz_frac:.2f}"
            dst = "n/a" if dist_frac != dist_frac else f"{dist_frac*100:.1f}"
            lse = "n/a" if loose_preserved is None else f"{loose_preserved:.2f}"
            print(f"{base_label:<22}{disp:<10}{gaps:>8}{('Y' if bind_ok else 'N'):>6}"
                  f"{('Y' if fit_ok else 'N'):>5}{('Y' if on_body else 'N'):>8}{czf:>9}{pen:>8}"
                  f"{dst:>9}{lse:>7}{('  OK' if passed else ' XX'):>4}")
        print("-" * len(hdr))
        print("HeightF = fitted garment centroid height as a fraction of the "
              "target base height (a torso/leg piece should sit mid-body, not at 0).")
        print("Distort% = fraction of edges distorted >2x the placement scaling "
              "(tracking only -- see MODULE header, not a gate).")
        print(f"Loose = median fitted/authored standoff of loose vertices "
              f"(fix-B2 gate, floor {MIN_LOOSENESS_PRESERVED:.2f}; n/a = no loose region).")

        # --- Ground-truth comparison (Example1.blend) --------------------
        _example_comparison(test_items)

        print("\n" + ("OK: retarget usable across all three naming families."
                       if ok else "FAIL: at least one retarget regressed (see XX rows)."))
        return 0 if ok else 1
    finally:
        if not was_registered:
            sculpt_tool.unregister()


def _mesh_bvh(obj, depsgraph):
    ctx = geometry.TargetContext.build(obj, depsgraph)
    return ctx


def _mean_nearest_distance(points, bvh):
    total = 0.0
    hits = 0
    for p in points:
        loc, _n, idx, _d = bvh.find_nearest(p)
        if idx is not None:
            total += (p - loc).length
            hits += 1
    return (total / hits) if hits else float("nan")


def _example_comparison(test_items):
    """Quantitative comparison against the user's manual fit (roadmap R9).

    Opens ``Example1.blend`` (manual ``Tech Outfit`` on a POSED Egirl BODY),
    retargets the Tech Set Top onto that same posed BODY through the deployed
    pipeline (placement + conform), and reports how close the retarget lands
    to the manual ground truth -- now feasible because placement handles the
    pose/position/scale gap. Informational (posed-base fit polish is still
    improving), but a real number the pipeline can be tracked against."""
    example = test_items / "Example1.blend"
    if not example.exists():
        return
    try:
        bpy.ops.wm.open_mainfile(filepath=str(example))
    except Exception as exc:
        print(f"\n(Example1 comparison skipped: {exc})")
        return
    body = bpy.data.objects.get("BODY")
    outfit = bpy.data.objects.get("Tech Outfit")
    if body is None or outfit is None:
        print("\n(Example1: BODY + 'Tech Outfit' not found -- skipping)")
        return

    if not hasattr(bpy.types.Object, "sculpt_tool"):
        sculpt_tool.register()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    body_ctx = _mesh_bvh(body, depsgraph)
    outfit_ctx = _mesh_bvh(outfit, depsgraph)
    lo = Vector((min(p[i] for p in body_ctx.positions) for i in range(3)))
    hi = Vector((max(p[i] for p in body_ctx.positions) for i in range(3)))
    diag = (hi - lo).length

    # Ground-truth reference: the manual outfit's own standoff from the body.
    om = outfit.matrix_world
    outfit_pts = [om @ v.co for v in outfit.data.vertices]
    stride = max(1, len(outfit_pts) // 3000)
    gt_standoff = _mean_nearest_distance(outfit_pts[::stride], body_ctx.bvh)

    # Retarget the Tech Set Top onto this posed BODY.
    source_body, _sa = _import_named(test_items / "Body" / SOURCE_FBX, SOURCE_OBJ)
    source_body.name = "SourceRP_ex"
    garment, _ga = _import_named(
        test_items / "Clothing" / "FBX-Tech Set by Vinuzhka.fbx", "Top by Vinuzhka"
    )
    s = garment.sculpt_tool
    s.source_body = source_body
    s.target_body = body
    s.bind_mode_override = 'MODE_B'
    s.target_base_armature = rig.deforming_armature(body)
    s.skip_alignment_check = True
    s.use_collision_resolution = True
    s.smoothing_iterations = 8
    bpy.context.view_layer.objects.active = garment
    garment.select_set(True)
    try:
        bind_r = bpy.ops.sculpttool.bind_garment()
        fit_r = bpy.ops.sculpttool.fit_garment()
    except RuntimeError as exc:
        print(f"\n(Example1 comparison: retarget failed -- {str(exc)[:60]})")
        return

    print("\nGround-truth comparison (Example1.blend -- posed manual fit):")
    if bind_r == {'FINISHED'} and fit_r == {'FINISHED'}:
        fitted = _fitted_world(garment)
        # Nearest distance from our retargeted Top to the manual outfit surface.
        stride2 = max(1, len(fitted) // 3000)
        to_gt = _mean_nearest_distance(fitted[::stride2], outfit_ctx.bvh)
        print(f"  Retargeted Top -> manual 'Tech Outfit' surface: mean distance "
              f"{to_gt:.4f} ({to_gt / diag * 100:.2f}% of body diagonal).")
        print(f"  (Reference: manual outfit's own standoff from the body is "
              f"{gt_standoff:.4f} / {gt_standoff / diag * 100:.2f}%.)")
        print("  Lower = closer to how the user hand-fitted it. Posed-base fit "
              "polish (girth/smoothing) is still improving; this is the tracked number.")
    else:
        print(f"  Retarget did not complete (bind={bind_r}, fit={fit_r}).")


if __name__ == "__main__":
    sys.exit(main())
