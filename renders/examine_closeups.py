"""Close-up single-figure renders for inspecting fit/sculpting quality.
Renders each chosen garment->base retarget large + front-on so penetration,
poke-through, gaps, or over-smoothing collapse are visible."""
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

SKIN = (0.82, 0.66, 0.57, 1.0)
CLOTH = (0.30, 0.60, 0.78, 1.0)
CLOTHING = R.TEST_ITEMS / "Clothing"
BODY = R.TEST_ITEMS / "Body"
SRC_FBX, SRC_OBJ = "vrbase_Egirl_Heeled Foot.fbx", "BODY"

CASES = [
    ("egirl_pants_venus", "E-girl.fbx", {"Tech Pants .001", "Tech top .001"}, "Project Venus_v2.02.fbx", "Body"),
    ("cybercrop_rp", "cybercroptopfinalizedUVedRigged.fbx", {"Body"}, "RP Female Base_Heeled Foot.fbx", "Body"),
    ("bodysuit_venus", "bodysuit.fbx", {"bodysuit by skulli"}, "Project Venus_v2.02.fbx", "Body"),
    ("summerset_fantasy", "Summer SET.fbx", {"Set"}, "vrbase_Fantasy_Heeled Foot.fbx", "BODY"),
]


def render_case(tag, garment_fbx, mesh_names, tgt_fbx, tgt_obj):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    src = R.import_group(BODY / SRC_FBX, {SRC_OBJ})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(BODY / tgt_fbx, {tgt_obj})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)
    garment = R.import_group(CLOTHING / garment_fbx, mesh_names)
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
        gm.color = CLOTH
    for o in src:
        bpy.data.objects.remove(o, do_unlink=True)
    base_body.color = SKIN
    meshes = [base_body] + [o for o in garment if o.type == 'MESH']

    R.setup_workbench(resolution=(900, 1300))
    R.frame_camera(meshes, azimuth_deg=0, elevation_deg=4, zoom=0.82)
    R.render_to(R.OUT_DIR / f"examine_{tag}.png")


for tag, gf, mn, tf, to in CASES:
    render_case(tag, gf, mn, tf, to)
