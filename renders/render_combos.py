"""New garment x base combinations (different pairings from render_variants),
each via the full placement+conform fit. Shows the retarget generalizing:
each garment on a base it wasn't paired with before."""
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
BODY = R.TEST_ITEMS / "Body"
CLOTHING = R.TEST_ITEMS / "Clothing"
SRC = ("vrbase_Egirl_Heeled Foot.fbx", "BODY")

# (garment fbx, {meshes}, target fbx, target obj, label) -- bases swapped vs
# render_variants so these are fresh pairings.
ENTRIES = [
    ("bodysuit.fbx", {"bodysuit by skulli"}, "vrbase_Fantasy_Heeled Foot.fbx", "BODY", "bodysuit -> Fantasy"),
    ("Summer SET.fbx", {"Set"}, "Project Venus_v2.02.fbx", "Body", "Summer Set -> Venus"),
    ("cybercroptopfinalizedUVedRigged.fbx", {"Body"}, "vrbase_Egirl_Heeled Foot.fbx", "BODY", "cyber crop -> Egirl"),
    ("E-girl.fbx", {"Tech top .001", "Tech Pants .001"}, "vrbase_Fantasy_Heeled Foot.fbx", "BODY", "E-girl set -> Fantasy"),
    ("Cyber Bunny Outfit by Yukina - E-girl.fbx", {"Bunny Suit"}, "Project Venus_v2.02.fbx", "Body", "Bunny Suit -> Venus"),
    ("Cyber Bunny Outfit by Yukina - E-girl.fbx", {"Hood Crop"}, "vrbase_Egirl_Heeled Foot.fbx", "BODY", "Hood Crop -> Egirl"),
]


def do_entry(idx, gf, mns, tf, to, xoff):
    src = R.import_group(BODY / SRC[0], {SRC[1]})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(BODY / tf, {to})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)
    garment = R.import_group(CLOTHING / gf, mns)
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
        bpy.ops.sculpttool.bind_garment()
        bpy.ops.sculpttool.fit_garment()
        gm.color = color
    for o in src:
        bpy.data.objects.remove(o, do_unlink=True)
    R.offset_group(base + garment, (xoff, 0, 0))
    base_body.color = SKIN
    return [base_body] + [o for o in garment if o.type == 'MESH']


meshes = []
for i, (gf, mns, tf, to, label) in enumerate(ENTRIES):
    meshes += do_entry(i, gf, mns, tf, to, i * 1.5)

R.setup_workbench(resolution=(2400, 780))
center, radius, mins, maxs = R._scene_bounds(meshes)
R.add_label("New combinations -- assorted garments on swapped bases (three-quarter view)",
            (center.x, mins.y - 0.3, maxs.z + 0.2), size=0.08, color=(0.96, 0.96, 0.98), face_deg=30)
for i, (gf, mns, tf, to, label) in enumerate(ENTRIES):
    R.add_label(label, (i * 1.5, mins.y - 0.3, mins.z - 0.12), size=0.05,
                color=(0.82, 0.88, 0.95), face_deg=30)

R.frame_camera(meshes, azimuth_deg=30, elevation_deg=6, zoom=1.06)
R.render_to(R.OUT_DIR / "combos_3q.png")
