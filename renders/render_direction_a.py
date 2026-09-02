"""Full-outfit Direction-A render (dev tooling, NOT part of the add-on).

Direction A (source-anchored deformation transfer) is experimental -- it is
NOT the shipped conform (that's Direction B / ``op_conform``). This script
renders the whole five-piece Tech Set conformed via A onto a target base, as
a like-for-like counterpart to ``render.py``'s Direction-B ``views``, so the
two can be compared on the full outfit.

A per garment vertex: displace it by the local ZinPia->target body-surface
displacement (k-nearest ZinPia verts, inverse-distance weighted) -- the same
transfer validated in ``ab_conform_experiment.py``. No armature placement, no
target-surface projection.

Run:
  blender --background --factory-startup --python renders/render_direction_a.py -- Venus
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy

sys.path.insert(0, str(R.REPO_ROOT))
from sculpt_tool.core import geometry, rig, rig_map  # noqa: E402
from morph_experiment import reconstruct_onto  # noqa: E402
from ab_conform_experiment import direction_a, _world_rest, _baked_copy  # noqa: E402

BODY = R.TEST_ITEMS / "Body"
CLOTHING = R.TEST_ITEMS / "Clothing"
TECH_SET = "FBX-Tech Set by Vinuzhka.fbx"
SOURCE = ("ZinPia_Fit Base HEELED Foot High Poly.fbx", "ZIN_FIT BASE")
TARGETS = {
    "Egirl": ("vrbase_Egirl_Heeled Foot.fbx", "BODY"),
    "Fantasy": ("vrbase_Fantasy_Heeled Foot.fbx", "BODY"),
    "Venus": ("Project Venus_v2.02.fbx", "Body"),
}
PIECES = [
    "pasties by Vinuzhka",
    "Top by Vinuzhka",
    "Sweater by Vinuzhka",
    "pants by Vinuzhka",
    "Straps by Vinuzhka",
]
SKIN = (0.80, 0.63, 0.54, 1.0)
COLORS = [
    (0.72, 0.40, 0.55, 1.0),
    (0.66, 0.34, 0.50, 1.0),
    (0.40, 0.68, 0.48, 1.0),
    (0.26, 0.55, 0.72, 1.0),
    (0.85, 0.70, 0.35, 1.0),
]


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    target_key = argv[0] if argv else "Venus"
    target_fbx, target_name = TARGETS[target_key]
    print(f"\n=== DIRECTION A full outfit: Tech Set -> {target_key} ===")

    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

    src = R.import_group(BODY / SOURCE[0], {SOURCE[1]})
    zin_mesh = next(o for o in src if o.type == 'MESH')
    zin_arm = rig.deforming_armature(zin_mesh)
    tgt = R.import_group(BODY / target_fbx, {target_name})
    tgt_mesh = next(o for o in tgt if o.type == 'MESH')
    tgt_arm = rig.deforming_armature(tgt_mesh)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    tgt_ctx = geometry.TargetContext.build(tgt_mesh, depsgraph)

    # ZinPia vertex -> corresponding target-surface point (skeletal reconstruct
    # onto the target rig, then snap to the target surface), and the resulting
    # per-vertex displacement A transfers to the garment.
    pairs = rig_map.build_bone_map(rig.bone_names(zin_arm), rig.bone_names(tgt_arm)).as_pairs()
    recon = reconstruct_onto(zin_mesh, zin_arm, tgt_arm, pairs)
    zin_rest = _world_rest(zin_mesh)
    zin_to_tgt = []
    for i, p in enumerate(recon):
        loc, _n, idx, _d = tgt_ctx.bvh.find_nearest(p)
        zin_to_tgt.append((loc if idx is not None else p) - zin_rest[i])

    garment_meshes = []
    for i, piece in enumerate(PIECES):
        objs = R.import_group(CLOTHING / TECH_SET, {piece})
        gm = next(o for o in objs if o.type == 'MESH')
        a_positions = direction_a(_world_rest(gm), zin_rest, zin_to_tgt)
        baked = _baked_copy(gm, a_positions, f"A_{piece}", COLORS[i % len(COLORS)])
        garment_meshes.append(baked)
        # drop the imported original (+ its armature) so only the baked copy remains
        for o in objs:
            bpy.data.objects.remove(o, do_unlink=True)
        print(f"  [A] {piece}: conformed")

    tgt_mesh.color = SKIN
    meshes = [tgt_mesh] + garment_meshes

    R.setup_workbench(resolution=(1000, 1300))
    for az, name in [(0, "front"), (40, "three-quarter"), (90, "side"), (180, "back")]:
        for o in list(bpy.data.objects):
            if o.type in {'FONT', 'CAMERA'}:
                bpy.data.objects.remove(o, do_unlink=True)
        _, _, mn, _ = R._scene_bounds(meshes)
        center, _, _, _ = R._scene_bounds(meshes)
        R.add_label(f"Tech Set -> {target_key}  (Direction A, {name})",
                    (center.x, mn.y - 0.3, mn.z - 0.12),
                    size=0.06, color=(0.95, 0.95, 0.98), face_deg=az)
        R.frame_camera(meshes, azimuth_deg=az, elevation_deg=6, zoom=0.95)
        R.render_to(R.OUT_DIR / f"dirA_{target_key}_{name}.png")


if __name__ == "__main__":
    main()
