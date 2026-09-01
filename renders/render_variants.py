"""Showcase: assorted clothing retargeted onto assorted bases via the real
operators (placement + conform). Each garment (authored for the vrbase
Egirl) is retargeted onto a different base to exercise variety + scale."""
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
CLOTH = [(0.26, 0.55, 0.72, 1.0), (0.66, 0.34, 0.50, 1.0), (0.40, 0.68, 0.48, 1.0)]
CLOTHING = R.TEST_ITEMS / "Clothing"
BODY = R.TEST_ITEMS / "Body"
SRC_FBX, SRC_OBJ = "vrbase_Egirl_Heeled Foot.fbx", "BODY"

# (garment fbx, {mesh names}, target body fbx, target obj, label)
ENTRIES = [
    ("bodysuit.fbx", {"bodysuit by skulli"}, "Project Venus_v2.02.fbx", "Body", "bodysuit -> Venus"),
    ("Summer SET.fbx", {"Set"}, "vrbase_Fantasy_Heeled Foot.fbx", "BODY", "Summer Set -> Fantasy"),
    ("cybercroptopfinalizedUVedRigged.fbx", {"Body"}, "RP Female Base_Heeled Foot.fbx", "Body", "cyber crop -> RP Female"),
    ("E-girl.fbx", {"Tech top .001", "Tech Pants .001"}, "Project Venus_v2.02.fbx", "Body", "E-girl set -> Venus"),
    ("Cyber Bunny Outfit by Yukina - E-girl.fbx", {"Bunny Suit"}, "vrbase_Fantasy_Heeled Foot.fbx", "BODY", "Bunny Suit -> Fantasy"),
    ("Cyber Bunny Outfit by Yukina - E-girl.fbx", {"Hood Crop"}, "RP Female Base_Heeled Foot.fbx", "Body", "Hood Crop -> RP Female"),
]


def do_entry(idx, garment_fbx, mesh_names, tgt_fbx, tgt_obj, xoff):
    src = R.import_group(BODY / SRC_FBX, {SRC_OBJ})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(BODY / tgt_fbx, {tgt_obj})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)
    garment = R.import_group(CLOTHING / garment_fbx, mesh_names)
    color = CLOTH[idx % len(CLOTH)]
    for gm in [o for o in garment if o.type == 'MESH']:
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
        rb = bpy.ops.sculpttool.bind_garment()
        rf = bpy.ops.sculpttool.fit_garment()
        gm.color = color
        print(f"{garment_fbx} {gm.name}: bind={rb} fit={rf}")
    for o in src:
        bpy.data.objects.remove(o, do_unlink=True)
    R.offset_group(base + garment, (xoff, 0, 0))
    base_body.color = SKIN
    return [base_body] + [o for o in garment if o.type == 'MESH']


meshes = []
for i, (gf, mn, tf, to, label) in enumerate(ENTRIES):
    meshes += do_entry(i, gf, mn, tf, to, i * 1.5)

R.setup_workbench(resolution=(2400, 760))
center, radius, mins, maxs = R._scene_bounds(meshes)
R.add_label("Clothing x base variety -- assorted garments retargeted via armature placement + conform",
            (center.x, mins.y - 0.3, maxs.z + 0.2), size=0.08, color=(0.96,0.96,0.98))
for i, (gf, mn, tf, to, label) in enumerate(ENTRIES):
    R.add_label(label, (i * 1.5, mins.y - 0.3, mins.z - 0.12), size=0.052, color=(0.82,0.88,0.95))

R.frame_camera(meshes, azimuth_deg=0, elevation_deg=5, zoom=1.06)
out = Path(__file__).parent / "out" / "variants.png"
out.parent.mkdir(exist_ok=True)
R.render_to(out)
