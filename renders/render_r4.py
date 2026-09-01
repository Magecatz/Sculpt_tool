"""R4 render: the alignment guard's verdict. Left = garment aligned to its
base (ACCEPTED, fit proceeds). Right = the same garment against a grossly
mis-posed base (REFUSED instead of silently baking garbage). Labels are
driven by the REAL core.alignment verdict, not hand-written."""
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy
from mathutils import Vector

sys.path.insert(0, str(R.REPO_ROOT))
from sculpt_tool.core import alignment, geometry, rig  # noqa

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

SKIN = (0.78, 0.62, 0.54, 1.0)
GOOD = (0.35, 0.75, 0.42, 1.0)
BAD = (0.85, 0.28, 0.28, 1.0)
GARMENT = "Top by Vinuzhka"


def load_pair(body_fbx, body_name, xoff, tilt_deg=0.0):
    body = R.import_group(R.TEST_ITEMS / "Body" / body_fbx, {body_name})
    garment = R.import_group(R.TEST_ITEMS / "Clothing" / "FBX-Tech Set by Vinuzhka.fbx", {GARMENT})
    body_mesh = next(o for o in body if o.type == 'MESH')
    gar_mesh = next(o for o in garment if o.type == 'MESH')
    if tilt_deg:
        # Tilt the TARGET base back about X -> the upright garment is now
        # grossly off its surface (a stand-in for a gross pose mismatch).
        piv = body_mesh.matrix_world.translation.copy()
        for o in body:
            if o.parent is None:
                o.rotation_euler = (math.radians(tilt_deg), 0, 0)
        bpy.context.view_layer.update()
    R.offset_group(body + garment, (xoff, 0, 0))
    return body_mesh, gar_mesh


def verdict(gar_mesh, body_mesh):
    dg = bpy.context.evaluated_depsgraph_get()
    ctx = geometry.TargetContext.build(body_mesh, dg)
    gpos, _ = geometry.world_space_positions_and_normals(gar_mesh, dg)
    return alignment.check_against_body(gpos, ctx, label="target base")


# Left: aligned. Right: tilted base (gross mismatch).
lb, lg = load_pair("vrbase_Egirl_Heeled Foot.fbx", "BODY", 0.0, tilt_deg=0.0)
rb, rg = load_pair("vrbase_Egirl_Heeled Foot.fbx", "BODY", 1.7, tilt_deg=55.0)

vl = verdict(lg, lb)
vr = verdict(rg, rb)
print("LEFT aligned:", vl.aligned, "far=%.2f mean=%.2f" % (vl.far_fraction, vl.mean_dist_ratio))
print("RIGHT aligned:", vr.aligned, "far=%.2f mean=%.2f" % (vr.far_fraction, vr.mean_dist_ratio))

lb.color = SKIN; rb.color = SKIN
lg.color = GOOD if vl.aligned else BAD
rg.color = GOOD if vr.aligned else BAD

R.setup_workbench(resolution=(1500, 1150))
meshes = [lb, lg, rb, rg]
center, radius, mins, maxs = R._scene_bounds(meshes)
R.add_label("R4: Alignment Guard -- refuse gross mismatch instead of silent garbage",
            (center.x, mins.y - 0.3, maxs.z + 0.2), size=0.085, color=(0.96,0.96,0.98))
lbl_l = "ACCEPTED -- fit proceeds" if vl.aligned else "REFUSED"
lbl_r = "REFUSED -- garment off the base" if not vr.aligned else "ACCEPTED"
R.add_label(lbl_l, (0.0, mins.y - 0.3, mins.z - 0.1), size=0.075,
            color=GOOD[:3] if vl.aligned else BAD[:3])
R.add_label(lbl_r, (1.7, mins.y - 0.3, mins.z - 0.1), size=0.075,
            color=BAD[:3] if not vr.aligned else GOOD[:3])
if not vr.aligned:
    R.add_label(f"({vr.far_fraction*100:.0f}% of vertices far off the body surface)",
                (1.7, mins.y - 0.3, mins.z - 0.24), size=0.05, color=(0.9,0.7,0.7))

R.frame_camera(meshes, azimuth_deg=0, elevation_deg=6, zoom=1.12)
out = Path(__file__).parent / "out" / "r4_alignment_guard.png"
out.parent.mkdir(exist_ok=True)
R.render_to(out)
