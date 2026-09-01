"""Before/after for the open-edge boundary straighten (conform_placed).
LEFT: boundary pass OFF -> ragged/frilly free edges. RIGHT: boundary pass
ON -> straightened rims. Same garment/base, toggled via the pipeline knob."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy

sys.path.insert(0, str(R.REPO_ROOT))
import sculpt_tool  # noqa
from sculpt_tool.core import rig, pipeline  # noqa

if not hasattr(bpy.types.Object, "sculpt_tool"):
    sculpt_tool.register()

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

SKIN = (0.82, 0.66, 0.57, 1.0)
OLD = (0.80, 0.44, 0.38, 1.0)
NEW = (0.32, 0.62, 0.78, 1.0)
CLOTHING = R.TEST_ITEMS / "Clothing"
BODY = R.TEST_ITEMS / "Body"


def build(xoff, boundary_iters, color):
    src = R.import_group(BODY / "vrbase_Egirl_Heeled Foot.fbx", {"BODY"})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(BODY / "RP Female Base_Heeled Foot.fbx", {"Body"})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)
    garment = R.import_group(CLOTHING / "cybercroptopfinalizedUVedRigged.fbx", {"Body"})
    gm = next(o for o in garment if o.type == 'MESH')

    pipeline._BOUNDARY_RELAX_ITERATIONS = boundary_iters  # toggle the fix
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
    return base_body, gm


meshes = []
meshes += build(0.0, 0, OLD)
meshes += build(1.6, 5, NEW)

R.setup_workbench(resolution=(1500, 1150))
c, r, mins, maxs = R._scene_bounds(meshes)
R.add_label("Open-edge boundary straighten (cybercrop sleeves -> RP Female)",
            (c.x, mins.y - 0.3, maxs.z + 0.2), size=0.075, color=(0.96, 0.96, 0.98))
R.add_label("BEFORE -- ragged/frilly free edges", (0.0, mins.y - 0.3, mins.z - 0.1),
            size=0.055, color=OLD[:3])
R.add_label("AFTER -- boundary loops straightened", (1.6, mins.y - 0.3, mins.z - 0.1),
            size=0.055, color=NEW[:3])
R.frame_camera(meshes, azimuth_deg=0, elevation_deg=8, zoom=1.0)
R.render_to(R.OUT_DIR / "boundary_fix.png")
