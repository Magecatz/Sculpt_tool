"""Multi-view: one fitted outfit rendered from several camera angles.
Fits the full Tech Set (sweater + pants) onto Egirl once, then renders
front / three-quarter / side / back (one file each) by re-framing the
camera -- so the same result can be inspected from every side."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy

sys.path.insert(0, str(R.REPO_ROOT))
import sculpt_tool  # noqa
from sculpt_tool.core import rig  # noqa

if not hasattr(bpy.types.Object, "sculpt_tool"):
    sculpt_tool.register()

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

SKIN = (0.80, 0.63, 0.54, 1.0)
TOPC = (0.24, 0.52, 0.72, 1.0)
PANTC = (0.62, 0.30, 0.46, 1.0)
BODY = R.TEST_ITEMS / "Body"
CLOTHING = R.TEST_ITEMS / "Clothing"


def fit_piece(obj_name, src_body, base_body, base_rig, color, out):
    garment = R.import_group(CLOTHING / "FBX-Tech Set by Vinuzhka.fbx", {obj_name})
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
    gm.color = color
    out.extend(garment)


src = R.import_group(BODY / "RP Female Base_Heeled Foot.fbx", {"Body"})
src_body = next(o for o in src if o.type == 'MESH')
base = R.import_group(BODY / "vrbase_Egirl_Heeled Foot.fbx", {"BODY"})
base_body = next(o for o in base if o.type == 'MESH')
base_rig = rig.deforming_armature(base_body)

gobjs = []
fit_piece("Sweater by Vinuzhka", src_body, base_body, base_rig, TOPC, gobjs)
fit_piece("pants by Vinuzhka", src_body, base_body, base_rig, PANTC, gobjs)
for o in src:
    bpy.data.objects.remove(o, do_unlink=True)
base_body.color = SKIN
meshes = [base_body] + [o for o in gobjs if o.type == 'MESH']

R.setup_workbench(resolution=(1000, 1300))
_, _, mins, maxs = R._scene_bounds(meshes)
for az, name in [(0, "front"), (40, "three-quarter"), (90, "side"), (180, "back")]:
    for o in list(bpy.data.objects):
        if o.type in {'FONT', 'CAMERA'}:
            bpy.data.objects.remove(o, do_unlink=True)
    center, radius, mn, mx = R._scene_bounds(meshes)
    R.add_label(f"Tech Set -> Egirl  ({name})", (center.x, mn.y - 0.3, mn.z - 0.12),
                size=0.06, color=(0.95, 0.95, 0.98), face_deg=az)
    R.frame_camera(meshes, azimuth_deg=az, elevation_deg=6, zoom=0.95)
    R.render_to(R.OUT_DIR / f"view_{name}.png")
