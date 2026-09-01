"""R7 render: armature-driven position + scale placement, on real assets.
The Tech Set sweater (authored for RP Female) shown on the Egirl base.
LEFT: rotation-only transfer (R3) -> garment keeps RP's position/size, sits
too low and wrongly sized on Egirl. RIGHT: full placement (R7) -> each
region moved and scaled to Egirl's skeleton (hips ~10cm higher, arms longer)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy

sys.path.insert(0, str(R.REPO_ROOT))
import sculpt_tool  # noqa
from sculpt_tool import operators  # noqa
from sculpt_tool.operators import op_pose  # noqa
from sculpt_tool.core import rig  # noqa

if not hasattr(bpy.types.Object, "sculpt_tool"):
    sculpt_tool.register()

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

SKIN = (0.80, 0.63, 0.54, 1.0)
OLD = (0.80, 0.42, 0.36, 1.0)   # rotation-only (problem)
NEW = (0.34, 0.62, 0.80, 1.0)   # placement (fixed)
GARMENT = "Sweater by Vinuzhka"


def build(xoff, mode):
    base = R.import_group(R.TEST_ITEMS / "Body" / "vrbase_Egirl_Heeled Foot.fbx", {"BODY"})
    base_mesh = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_mesh)
    garment = R.import_group(R.TEST_ITEMS / "Clothing" / "FBX-Tech Set by Vinuzhka.fbx", {GARMENT})
    gm = next(o for o in garment if o.type == 'MESH')
    gr = rig.deforming_armature(gm)

    if mode == "rot":
        op_pose.pose_garment_onto_rig(bpy.context, gr, base_rig)   # rotation only (R3)
        gm.color = OLD
    else:
        op_pose.place_garment_onto_rig(bpy.context, gr, base_rig)  # position+rotation+scale (R7)
        gm.color = NEW
    bpy.context.view_layer.update()

    R.offset_group(base + garment, (xoff, 0, 0))
    base_mesh.color = SKIN
    return base_mesh, gm


meshes = []
lb, lg = build(0.0, "rot")
rb, rg = build(1.6, "place")
meshes = [lb, lg, rb, rg]

R.setup_workbench(resolution=(1400, 1250))
center, radius, mins, maxs = R._scene_bounds(meshes)
R.add_label("R7: armature-driven position + scale (garment authored for RP Female, shown on Egirl)",
            (center.x, mins.y - 0.3, maxs.z + 0.2), size=0.07, color=(0.96,0.96,0.98))
R.add_label("BEFORE -- rotation only: too low, wrong size", (0.0, mins.y - 0.3, mins.z - 0.1),
            size=0.058, color=OLD[:3])
R.add_label("AFTER -- placed + scaled to Egirl's skeleton", (1.6, mins.y - 0.3, mins.z - 0.1),
            size=0.058, color=NEW[:3])

R.frame_camera(meshes, azimuth_deg=0, elevation_deg=6, zoom=1.12)
out = Path(__file__).parent / "out" / "r7_placement.png"
out.parent.mkdir(exist_ok=True)
R.render_to(out)
