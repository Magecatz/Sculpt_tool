"""R5 render: the wired end-to-end pipeline via the REAL operators. One
garment (Tech Set Top, authored for RP Female) retargeted onto all three
target bases (Egirl / Fantasy / Venus) through a single Fit each -- pose
stage 0 (a no-op on these rest-pose bases) + bind/project/collision/smooth/
bake. Uses bpy.ops the same way a user clicks the buttons."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy
from mathutils import Vector

sys.path.insert(0, str(R.REPO_ROOT))
import sculpt_tool  # noqa
from sculpt_tool.core import rig  # noqa

if not hasattr(bpy.types.Object, "sculpt_tool"):
    sculpt_tool.register()

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

SKIN = (0.80, 0.63, 0.54, 1.0)
CLOTH = (0.24, 0.52, 0.42, 1.0)
GARMENT = "Top by Vinuzhka"
BASES = [
    ("vrbase_Egirl_Heeled Foot.fbx", "BODY", "Egirl"),
    ("vrbase_Fantasy_Heeled Foot.fbx", "BODY", "Fantasy"),
    ("Project Venus_v2.02.fbx", "Body", "Venus"),
]


def retarget_onto(base_fbx, base_obj_name, xoff):
    src = R.import_group(R.TEST_ITEMS / "Body" / "RP Female Base_Heeled Foot.fbx", {"Body"})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(R.TEST_ITEMS / "Body" / base_fbx, {base_obj_name})
    base_body = next(o for o in base if o.type == 'MESH')
    garment = R.import_group(R.TEST_ITEMS / "Clothing" / "FBX-Tech Set by Vinuzhka.fbx", {GARMENT})
    gar_mesh = next(o for o in garment if o.type == 'MESH')

    s = gar_mesh.sculpt_tool
    s.source_body = src_body
    s.target_body = base_body
    s.bind_mode_override = 'MODE_B'
    s.target_base_armature = rig.deforming_armature(base_body)
    s.use_collision_resolution = True
    s.smoothing_iterations = R.SMOOTHING_ITERATIONS
    bpy.context.view_layer.objects.active = gar_mesh
    gar_mesh.select_set(True)
    r1 = bpy.ops.sculpttool.bind_garment()
    r2 = bpy.ops.sculpttool.fit_garment()
    print(f"{base_obj_name}: bind={r1} fit={r2} verts={len(gar_mesh.data.vertices)}")

    # Hide the RP source body from the render (keep only base + fitted garment).
    for o in src:
        bpy.data.objects.remove(o, do_unlink=True)
    R.offset_group(base + garment, (xoff, 0, 0))
    base_body.color = SKIN
    gar_mesh.color = CLOTH
    return base_body, gar_mesh


meshes = []
for i, (fbx, name, label) in enumerate(BASES):
    bm, gm = retarget_onto(fbx, name, i * 1.55)
    meshes += [bm, gm]

R.setup_workbench(resolution=(1550, 1180))
center, radius, mins, maxs = R._scene_bounds(meshes)
R.add_label("R5: Pose -> Fit wired end-to-end -- one garment retargeted onto three bases",
            (center.x, mins.y - 0.3, maxs.z + 0.2), size=0.08, color=(0.96,0.96,0.98))
for i, (_f, _n, label) in enumerate(BASES):
    R.add_label(label, (i * 1.55, mins.y - 0.3, mins.z - 0.12), size=0.075, color=(0.75,0.9,0.8))

R.frame_camera(meshes, azimuth_deg=0, elevation_deg=6, zoom=1.12)
out = Path(__file__).parent / "out" / "r5_pipeline.png"
out.parent.mkdir(exist_ok=True)
R.render_to(out)
