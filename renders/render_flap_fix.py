"""Before/after for the stray-flap fix (two files: flap_before/flap_after).
E-girl Tech Pants placed onto Venus. BEFORE: unmapped helper bones inherit
the mapped leg's non-uniform stretch -> a region shears into a stray flap.
AFTER: scale inheritance off on all garment bones -> no shear, no flap.
Shows the armature placement directly (where the shear happens)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy

sys.path.insert(0, str(R.REPO_ROOT))
import sculpt_tool  # noqa
from sculpt_tool.core import rig, rig_map  # noqa
from sculpt_tool.operators import op_pose  # noqa

if not hasattr(bpy.types.Object, "sculpt_tool"):
    sculpt_tool.register()

SKIN = (0.82, 0.66, 0.57, 1.0)
BODY = R.TEST_ITEMS / "Body"
CLOTHING = R.TEST_ITEMS / "Clothing"


def render_one(shear, color, label, path):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    base = R.import_group(BODY / "Project Venus_v2.02.fbx", {"Body"})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)
    garment = R.import_group(CLOTHING / "E-girl.fbx", {"Tech Pants .001"})
    gm = next(o for o in garment if o.type == 'MESH')
    gr = rig.deforming_armature(gm)

    op_pose.place_garment_onto_rig(bpy.context, gr, base_rig)
    if shear:
        bmap = rig_map.build_bone_map(rig.bone_names(gr), rig.bone_names(base_rig))
        mapped = set(s for s, t in bmap.as_pairs())
        for b in gr.data.bones:
            if b.name not in mapped:
                b.inherit_scale = 'FULL'
        bpy.context.view_layer.update()

    base_body.color = SKIN
    gm.color = color
    meshes = [base_body, gm]
    R.setup_workbench(resolution=(900, 1250))
    c, r, mins, maxs = R._scene_bounds(meshes)
    R.add_label(label, (c.x, mins.y - 0.3, mins.z - 0.12), size=0.06, color=color[:3])
    R.frame_camera(meshes, azimuth_deg=0, elevation_deg=6, zoom=0.95)
    R.render_to(path)


render_one(True, (0.80, 0.44, 0.38, 1.0), "BEFORE -- helper shears into a flap", R.OUT_DIR / "flap_before.png")
render_one(False, (0.40, 0.66, 0.50, 1.0), "AFTER -- no shear, no flap", R.OUT_DIR / "flap_after.png")
