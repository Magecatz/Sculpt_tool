"""Before/after for bust conformance (two files: bust_before/bust_after).
E-girl Tech top retargeted onto Venus via the full fit. BEFORE: breast bones
unmapped -> the top keeps its authored cups (balloons/gaps over Venus's
bust). AFTER: breast bones mapped -> placement sizes/positions the bust
region to Venus's breasts. Toggled via rig_map.MAP_BREAST_BONES."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy

sys.path.insert(0, str(R.REPO_ROOT))
import sculpt_tool  # noqa
from sculpt_tool.core import rig, rig_map  # noqa

if not hasattr(bpy.types.Object, "sculpt_tool"):
    sculpt_tool.register()

SKIN = (0.82, 0.66, 0.57, 1.0)
BODY = R.TEST_ITEMS / "Body"
CLOTHING = R.TEST_ITEMS / "Clothing"


def render_one(map_breast, color, label, path):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    rig_map.MAP_BREAST_BONES = map_breast
    src = R.import_group(BODY / "vrbase_Egirl_Heeled Foot.fbx", {"BODY"})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(BODY / "Project Venus_v2.02.fbx", {"Body"})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)
    garment = R.import_group(CLOTHING / "E-girl.fbx", {"Tech top .001"})
    gm = next(o for o in garment if o.type == 'MESH')

    s = gm.sculpt_tool
    s.source_body = src_body
    s.target_body = base_body
    s.bind_mode_override = 'MODE_B'
    s.target_base_armature = base_rig
    s.use_collision_resolution = True
    s.smoothing_iterations = R.SMOOTHING_ITERATIONS
    s.skip_alignment_check = True
    bpy.context.view_layer.objects.active = gm
    gm.select_set(True)
    bpy.ops.sculpttool.bind_garment()
    bpy.ops.sculpttool.fit_garment()
    for o in src:
        bpy.data.objects.remove(o, do_unlink=True)
    base_body.color = SKIN
    gm.color = color

    meshes = [base_body, gm]
    R.setup_workbench(resolution=(950, 1150))
    c, r, mins, maxs = R._scene_bounds(meshes)
    # Frame on the upper body (bust) -- camera aimed at chest height.
    R.add_label(label, (c.x, mins.y - 0.3, mins.z - 0.12), size=0.055, color=color[:3])
    R.frame_camera(meshes, azimuth_deg=0, elevation_deg=3, zoom=0.7)
    R.render_to(path)


render_one(False, (0.80, 0.44, 0.38, 1.0), "BEFORE -- breast bones unmapped", R.OUT_DIR / "bust_before.png")
render_one(True, (0.34, 0.62, 0.78, 1.0), "AFTER -- breast bones mapped", R.OUT_DIR / "bust_after.png")
