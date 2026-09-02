"""Sleeve-clip diagnostic (dev tooling). Sweater -> Venus, two conform
variants side by side over the Venus body, to see whether the sleeve clip is
the loose-ramp keeping the sleeve at its (clipping) placed position:

  keep_loose=True  (current op_conform)  -- loose verts keep placed position
  keep_loose=False (pure projection)     -- every vert projected to the arm

Run: blender --background --factory-startup --python renders/sleeve_diag.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(R.REPO_ROOT))
from sculpt_tool.core import conform, geometry, rig  # noqa: E402
from sculpt_tool.operators import op_pose  # noqa: E402
from ab_conform_experiment import _baked_copy  # noqa: E402

if not hasattr(bpy.types.Object, "sculpt_tool"):
    import sculpt_tool
    sculpt_tool.register()

BODY = R.TEST_ITEMS / "Body"
CLOTHING = R.TEST_ITEMS / "Clothing"
SKIN = (0.80, 0.63, 0.54, 1.0)


def main():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

    zin = R.import_group(BODY / "ZinPia_Fit Base HEELED Foot High Poly.fbx", {"ZIN_FIT BASE"})
    zin_mesh = next(o for o in zin if o.type == 'MESH')
    venus = R.import_group(BODY / "Project Venus_v2.02.fbx", {"Body"})
    venus_mesh = next(o for o in venus if o.type == 'MESH')
    venus_arm = rig.deforming_armature(venus_mesh)

    g = R.import_group(CLOTHING / "FBX-Tech Set by Vinuzhka.fbx", {"Sweater by Vinuzhka"})
    sweater = next(o for o in g if o.type == 'MESH')
    garm_arm = rig.deforming_armature(sweater)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    zin_ctx = geometry.TargetContext.build(zin_mesh, depsgraph)
    venus_ctx = geometry.TargetContext.build(venus_mesh, depsgraph)

    rest_world = [sweater.matrix_world @ v.co for v in sweater.data.vertices]
    standoff = conform.authored_standoff(rest_world, zin_ctx)

    op_pose.set_armature_deform_visible(sweater, True)
    op_pose.place_garment_onto_rig(bpy.context, garm_arm, venus_arm, [])
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    placed, _ = geometry.world_space_positions_and_normals(sweater, depsgraph)

    neighbors = conform.build_vertex_neighbors(
        [(e.vertices[0], e.vertices[1]) for e in sweater.data.edges], len(rest_world)
    )
    keep = conform.project_to_target(placed, standoff, venus_ctx, neighbors=neighbors)
    proj = conform.project_to_target(placed, standoff, venus_ctx, keep_loose=False)

    venus_mesh.color = SKIN
    _, _, mn, mx = R._scene_bounds([venus_mesh])
    gap = (mx.x - mn.x) * 1.6

    panels = []
    for dx, positions, tag in [(-gap, placed, "placed"),
                               (0.0, keep, "keep_loose=True"),
                               (gap, proj, "keep_loose=False")]:
        body = venus_mesh.data.copy()
        b = bpy.data.objects.new(f"venus_{tag}", body)
        bpy.context.collection.objects.link(b)
        b.matrix_world = Matrix.Translation((dx, 0, 0)) @ venus_mesh.matrix_world
        b.color = SKIN
        gm = _baked_copy(sweater, [Vector(p) + Vector((dx, 0, 0)) for p in positions],
                         f"sweater_{tag}", (0.40, 0.68, 0.48, 1.0))
        panels += [b, gm]

    R.setup_workbench(resolution=(2100, 1300))
    for az, name in [(0, "front"), (40, "three-quarter")]:
        for o in list(bpy.data.objects):
            if o.type in {'FONT', 'CAMERA'}:
                bpy.data.objects.remove(o, do_unlink=True)
        c, _, mn2, _ = R._scene_bounds(panels)
        R.add_label("Sweater -> Venus:   placed        keep_loose=True        keep_loose=False (pure project)",
                    (c.x, mn2.y - 0.3, mn2.z - 0.12), size=0.05,
                    color=(0.95, 0.95, 0.98), face_deg=az)
        R.frame_camera(panels, azimuth_deg=az, elevation_deg=6, zoom=1.03)
        R.render_to(R.OUT_DIR / f"sleeve_{name}.png")


if __name__ == "__main__":
    main()
