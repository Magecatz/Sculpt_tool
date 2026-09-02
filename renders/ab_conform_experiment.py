"""A-vs-B conform experiment (dev tooling, NOT part of the add-on).

Question it answers: on the cross-creator target (ZinPia garment -> Project
Venus base), does a SOURCE-anchored conform (Direction A) preserve a fitted
garment's shape better than a TARGET-anchored one (Direction B)? This is the
decision the restart's "C engine + A/B anchors" plan hinges on
(RESTART_SCOPE.md sections 5/7). The `Top` piece is the stress case -- it's
the small fitted piece the old target-anchored conform inflated into a blob.

Both strategies preserve the garment's authored standoff from its body; the
ONLY difference is where each anchors correspondence:

  Direction A (source-anchored deformation transfer)
    The garment fits ZinPia, so each garment vertex's nearest ZinPia vertex
    is a STABLE correspondence. Displace each garment vertex by the local
    ZinPia->Venus body-surface displacement (k-nearest ZinPia verts, inverse-
    distance weighted). Never projects the garment onto the target, so it
    cannot scatter/inflate. Needs the source base.

  Direction B (target-anchored, placement + surface projection)
    Place the garment on Venus via the armature, then project each placed
    vertex onto the nearest Venus surface point and reapply its authored
    standoff. This is the family the old conform belonged to. Needs no source
    base.

Renders (renders/out/): ab_<piece>_<front|three-quarter>.png -- a row
[placed only | Direction A | Direction B] over the Venus body.

Run:
  blender --background --factory-startup --python renders/ab_conform_experiment.py -- "Top by Vinuzhka"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

sys.path.insert(0, str(R.REPO_ROOT))
from sculpt_tool.core import geometry, rig, rig_map  # noqa: E402
from sculpt_tool.operators import op_pose  # noqa: E402
from morph_experiment import reconstruct_onto  # noqa: E402

BODY = R.TEST_ITEMS / "Body"
CLOTHING = R.TEST_ITEMS / "Clothing"
TECH_SET = "FBX-Tech Set by Vinuzhka.fbx"
SOURCE = ("ZinPia_Fit Base HEELED Foot High Poly.fbx", "ZIN_FIT BASE")
TARGET = ("Project Venus_v2.02.fbx", "Body")

SKIN = (0.80, 0.63, 0.54, 1.0)
PLACED_COL = (0.66, 0.55, 0.85, 1.0)   # placement only -- lilac
A_COL = (0.40, 0.68, 0.48, 1.0)        # Direction A -- green
B_COL = (0.72, 0.40, 0.55, 1.0)        # Direction B -- pink
K = 4                                  # k-nearest ZinPia verts for A


def _clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def _world_rest(mesh):
    m = mesh.matrix_world
    return [m @ v.co for v in mesh.data.vertices]


def _baked_copy(template_mesh, world_positions, name, color):
    """Standalone mesh (identity matrix, no modifiers) at world_positions."""
    me = template_mesh.data.copy()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    obj.matrix_world = Matrix.Identity(4)
    for i, co in enumerate(world_positions):
        me.vertices[i].co = co
    me.update()
    for mod in list(obj.modifiers):
        obj.modifiers.remove(mod)
    obj.color = color
    return obj


def _authored_standoff(garment_rest, zin_ctx):
    """Signed distance of each garment vertex off the ZinPia surface, along
    the ZinPia surface normal (its authored 'how far off the body' value)."""
    out = []
    for g in garment_rest:
        loc, nrm, idx, _ = zin_ctx.bvh.find_nearest(g)
        out.append((g - loc).dot(nrm) if idx is not None else 0.0)
    return out


def direction_a(garment_rest, zin_rest, zin_to_venus_disp):
    """Source-anchored transfer: displace each garment vertex by the local
    ZinPia->Venus body displacement (k-nearest ZinPia verts, inv-dist)."""
    kd = KDTree(len(zin_rest))
    for i, p in enumerate(zin_rest):
        kd.insert(p, i)
    kd.balance()
    out = []
    for g in garment_rest:
        disp = Vector((0.0, 0.0, 0.0))
        wsum = 0.0
        for _co, idx, dist in kd.find_n(g, K):
            w = 1.0 / (dist * dist + 1e-9)
            disp += w * zin_to_venus_disp[idx]
            wsum += w
        out.append(g + (disp / wsum if wsum > 0 else disp))
    return out


def direction_b(garment_obj, garment_arm, venus_arm, venus_ctx, standoff):
    """Target-anchored: place on Venus via armature, then project each placed
    vertex onto the nearest Venus surface and reapply the authored standoff."""
    op_pose.set_armature_deform_visible(garment_obj, True)
    op_pose.place_garment_onto_rig(bpy.context, garment_arm, venus_arm, [])
    depsgraph = bpy.context.evaluated_depsgraph_get()
    placed, _ = geometry.world_space_positions_and_normals(garment_obj, depsgraph)
    out = []
    for p, s in zip(placed, standoff):
        loc, nrm, idx, _ = venus_ctx.bvh.find_nearest(p)
        out.append(loc + nrm * s if idx is not None else p)
    # undo the placement so the object is back at rest for later reads
    op_pose.reset_pose(garment_arm)
    op_pose.set_armature_deform_visible(garment_obj, False)
    bpy.context.view_layer.update()
    return placed, out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    piece = argv[0] if argv else "Top by Vinuzhka"
    slug = piece.split(" ")[0].lower()
    print(f"\n=== A-vs-B CONFORM: '{piece}'  ZinPia -> Venus ===")

    _clear()
    src = R.import_group(BODY / SOURCE[0], {SOURCE[1]})
    zin_mesh = next(o for o in src if o.type == 'MESH')
    zin_arm = rig.deforming_armature(zin_mesh)

    tgt = R.import_group(BODY / TARGET[0], {TARGET[1]})
    venus_mesh = next(o for o in tgt if o.type == 'MESH')
    venus_arm = rig.deforming_armature(venus_mesh)

    garment_objs = R.import_group(CLOTHING / TECH_SET, {piece})
    garment = next(o for o in garment_objs if o.type == 'MESH')
    garment_arm = rig.deforming_armature(garment)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    zin_ctx = geometry.TargetContext.build(zin_mesh, depsgraph)
    venus_ctx = geometry.TargetContext.build(venus_mesh, depsgraph)

    # ZinPia vertex -> its corresponding Venus-surface point (skeletal
    # reconstruct onto the Venus rig, then snap to the Venus surface).
    pairs = rig_map.build_bone_map(rig.bone_names(zin_arm), rig.bone_names(venus_arm)).as_pairs()
    recon = reconstruct_onto(zin_mesh, zin_arm, venus_arm, pairs)
    zin_rest = _world_rest(zin_mesh)
    zin_to_venus_disp = []
    for i, p in enumerate(recon):
        loc, _n, idx, _d = venus_ctx.bvh.find_nearest(p)
        zin_to_venus_disp.append((loc if idx is not None else p) - zin_rest[i])

    garment_rest = _world_rest(garment)
    standoff = _authored_standoff(garment_rest, zin_ctx)

    a_positions = direction_a(garment_rest, zin_rest, zin_to_venus_disp)
    placed, b_positions = direction_b(garment, garment_arm, venus_arm, venus_ctx, standoff)

    # Bake three garment copies, offset into a row, over the Venus body.
    venus_mesh.color = SKIN
    _, _, mn, mx = R._scene_bounds([venus_mesh])
    gap = (mx.x - mn.x) * 1.6

    panels = []
    for dx, positions, col, tag in [
        (-gap, placed, PLACED_COL, "placed only"),
        (0.0, a_positions, A_COL, "A: source-anchored"),
        (gap, b_positions, B_COL, "B: target-anchored"),
    ]:
        body = venus_mesh.data.copy()
        bobj = bpy.data.objects.new(f"venus_{tag}", body)
        bpy.context.collection.objects.link(bobj)
        bobj.matrix_world = Matrix.Translation((dx, 0, 0)) @ venus_mesh.matrix_world
        bobj.color = SKIN
        g = _baked_copy(garment, [p + Vector((dx, 0, 0)) for p in positions],
                        f"garment_{tag}", col)
        panels += [bobj, g]

    R.setup_workbench(resolution=(2100, 1400))
    for az, name in [(0, "front"), (40, "three-quarter")]:
        for o in list(bpy.data.objects):
            if o.type in {'FONT', 'CAMERA'}:
                bpy.data.objects.remove(o, do_unlink=True)
        c, _, mn2, _ = R._scene_bounds(panels)
        R.add_label(f"'{piece}' -> Venus:   placed only        A: source-anchored        B: target-anchored",
                    (c.x, mn2.y - 0.3, mn2.z - 0.12), size=0.055,
                    color=(0.95, 0.95, 0.98), face_deg=az)
        R.frame_camera(panels, azimuth_deg=az, elevation_deg=6, zoom=1.02)
        R.render_to(R.OUT_DIR / f"ab_{slug}_{name}.png")


if __name__ == "__main__":
    main()
