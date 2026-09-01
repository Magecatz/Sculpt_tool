"""R6 capstone render: the full Tech Set (Sweater + Pants) retargeted onto
all three bases through the real operators -- the regression this card
locks in, visualized. Egirl / Fantasy / Venus, three naming families, one
garment set, via bone map -> pose stage 0 -> Mode B bind/fit/collision."""
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
BASES = [
    ("vrbase_Egirl_Heeled Foot.fbx", "BODY", "Egirl  (_L / Arm_L)"),
    ("vrbase_Fantasy_Heeled Foot.fbx", "BODY", "Fantasy  (_L / Arm_L)"),
    ("Project Venus_v2.02.fbx", "Body", "Venus  (.L / Upper_Arm)"),
]


def fit_piece(garment_objs, obj_name, src_body, base_body, base_rig, color):
    garment = R.import_group(R.TEST_ITEMS / "Clothing" / "FBX-Tech Set by Vinuzhka.fbx", {obj_name})
    gm = next(o for o in garment if o.type == 'MESH')
    s = gm.sculpt_tool
    s.source_body = src_body
    s.target_body = base_body
    s.bind_mode_override = 'MODE_B'
    s.target_base_armature = base_rig
    s.use_collision_resolution = True
    s.smoothing_iterations = R.SMOOTHING_ITERATIONS
    bpy.context.view_layer.objects.active = gm
    gm.select_set(True)
    bpy.ops.sculpttool.bind_garment()
    r = bpy.ops.sculpttool.fit_garment()
    gm.color = color
    garment_objs.extend(garment)
    return gm, r


def retarget(base_fbx, base_obj, xoff):
    src = R.import_group(R.TEST_ITEMS / "Body" / "RP Female Base_Heeled Foot.fbx", {"Body"})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(R.TEST_ITEMS / "Body" / base_fbx, {base_obj})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)

    gobjs = []
    _, r1 = fit_piece(gobjs, "Sweater by Vinuzhka", src_body, base_body, base_rig, TOPC)
    _, r2 = fit_piece(gobjs, "pants by Vinuzhka", src_body, base_body, base_rig, PANTC)
    print(f"{base_obj}: sweater={r1} pants={r2}")

    for o in src:
        bpy.data.objects.remove(o, do_unlink=True)
    R.offset_group(base + gobjs, (xoff, 0, 0))
    base_body.color = SKIN
    return [base_body] + [o for o in gobjs if o.type == 'MESH']


meshes = []
for i, (fbx, name, label) in enumerate(BASES):
    meshes += retarget(fbx, name, i * 1.55)

R.setup_workbench(resolution=(1600, 1200))
center, radius, mins, maxs = R._scene_bounds(meshes)
R.add_label("Feature complete: full Tech Set retargeted across three rig families (R1-R6)",
            (center.x, mins.y - 0.3, maxs.z + 0.2), size=0.076, color=(0.96,0.96,0.98))
for i, (_f, _n, label) in enumerate(BASES):
    R.add_label(label, (i * 1.55, mins.y - 0.3, mins.z - 0.12), size=0.06, color=(0.8,0.88,0.95))

R.frame_camera(meshes, azimuth_deg=0, elevation_deg=6, zoom=1.1)
out = Path(__file__).parent / "out" / "r6_feature_complete.png"
out.parent.mkdir(exist_ok=True)
R.render_to(out)
