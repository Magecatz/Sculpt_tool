"""R8 render: the fit now consumes the armature-placed garment. Same Tech
Set sweater retargeted onto Egirl via the real bind+fit operators.
LEFT: auto-placement OFF -> old path (frozen bind-time projection, no
placement) = too low / mangled. RIGHT: auto-placement ON -> R7 placement +
R8 conform = positioned, scaled, and surface-cleaned onto Egirl."""
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
OLD = (0.80, 0.42, 0.36, 1.0)
NEW = (0.34, 0.66, 0.52, 1.0)
GARMENT = "Sweater by Vinuzhka"


def retarget(xoff, auto_place, color):
    src = R.import_group(R.TEST_ITEMS / "Body" / "RP Female Base_Heeled Foot.fbx", {"Body"})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(R.TEST_ITEMS / "Body" / "vrbase_Egirl_Heeled Foot.fbx", {"BODY"})
    base_body = next(o for o in base if o.type == 'MESH')
    garment = R.import_group(R.TEST_ITEMS / "Clothing" / "FBX-Tech Set by Vinuzhka.fbx", {GARMENT})
    gm = next(o for o in garment if o.type == 'MESH')

    s = gm.sculpt_tool
    s.source_body = src_body
    s.target_body = base_body
    s.bind_mode_override = 'MODE_B'
    s.target_base_armature = rig.deforming_armature(base_body)
    s.auto_pose_transfer = auto_place
    s.use_collision_resolution = True
    s.smoothing_iterations = R.SMOOTHING_ITERATIONS
    bpy.context.view_layer.objects.active = gm
    gm.select_set(True)
    r1 = bpy.ops.sculpttool.bind_garment()
    r2 = bpy.ops.sculpttool.fit_garment()
    print(f"auto_place={auto_place}: bind={r1} fit={r2}")

    for o in src:
        bpy.data.objects.remove(o, do_unlink=True)
    R.offset_group(base + garment, (xoff, 0, 0))
    base_body.color = SKIN
    gm.color = color
    return base_body, gm


meshes = []
meshes += retarget(0.0, False, OLD)
meshes += retarget(1.6, True, NEW)

R.setup_workbench(resolution=(1400, 1250))
center, radius, mins, maxs = R._scene_bounds(meshes)
R.add_label("R8: fit consumes the placed garment (Tech Set sweater -> Egirl, real operators)",
            (center.x, mins.y - 0.3, maxs.z + 0.2), size=0.072, color=(0.96,0.96,0.98))
R.add_label("BEFORE -- frozen projection, no placement", (0.0, mins.y - 0.3, mins.z - 0.1),
            size=0.055, color=OLD[:3])
R.add_label("AFTER -- placed + scaled + conformed", (1.6, mins.y - 0.3, mins.z - 0.1),
            size=0.055, color=NEW[:3])

R.frame_camera(meshes, azimuth_deg=0, elevation_deg=6, zoom=1.12)
out = Path(__file__).parent / "out" / "r8_fit_placed.png"
out.parent.mkdir(exist_ok=True)
R.render_to(out)
