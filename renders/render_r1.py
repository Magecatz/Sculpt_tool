"""R1 render: the tool is now rig-aware. Shows the Tech Set garment on its
SOURCE base (RP Female Base, 84-bone rig) and the TARGET base it will be
retargeted onto (Egirl, 66-bone rig) -- the retargeting scenario R1 makes
the tool aware of. No posing yet (that's R3)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

SKIN = (0.80, 0.62, 0.52, 1.0)
CLOTH = (0.20, 0.22, 0.30, 1.0)
WHITE = (0.96, 0.96, 0.98, 1.0)

# Source base + garment authored for it (RP Female Base).
src = R.import_group(R.TEST_ITEMS / "Body" / "RP Female Base_Heeled Foot.fbx", {"Body"})
garment = R.import_group(R.TEST_ITEMS / "Clothing" / "FBX-Tech Set by Vinuzhka.fbx",
                         {"Top by Vinuzhka", "pants by Vinuzhka"})
# Target base (Egirl), offset to the right.
tgt = R.import_group(R.TEST_ITEMS / "Body" / "vrbase_Egirl_Heeled Foot.fbx", {"BODY"})
R.offset_group(tgt, (1.5, 0, 0))

for o in src + tgt:
    if o.type == 'MESH':
        o.color = SKIN
for o in garment:
    if o.type == 'MESH':
        o.color = CLOTH

meshes = [o for o in src + garment + tgt if o.type == 'MESH']
R.setup_workbench(resolution=(1300, 1150))
for o in meshes:
    pass

# Labels (place relative to bounds).
center, radius, mins, maxs = R._scene_bounds(meshes)
top = maxs.z + 0.12
R.add_label("R1: Base Retargeting -- tool now knows both rigs", (center.x, mins.y - 0.3, top + 0.18), size=0.11, color=WHITE[:3])
l1 = R.add_label("Source base: RP Female  (Armature.001, 84 bones)", (0.0, mins.y - 0.3, mins.z - 0.12), size=0.075, color=(0.7,0.85,1.0))
l2 = R.add_label("Target base: Egirl  (Armature, 66 bones)", (1.5, mins.y - 0.3, mins.z - 0.12), size=0.075, color=(1.0,0.8,0.7))
for lo in (l1, l2):
    lo.color = WHITE

R.frame_camera(meshes, azimuth_deg=0, elevation_deg=6, zoom=1.15)
out = Path(__file__).parent / "out" / "r1_base_retargeting.png"
out.parent.mkdir(exist_ok=True)
R.render_to(out)
