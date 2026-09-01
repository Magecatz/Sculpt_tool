"""R3 render + real-asset validation: pose transfer on the real rigs.

The Egirl target base is posed arms-DOWN (a genuine pose gap vs the garment's
authored T-pose). LEFT: the garment (Tech Set sweater, RP naming) left at
rest -> its sleeves stick straight out where the arms no longer are (the
'sleeve floats off the arm' failure). RIGHT: the SAME garment after pose
transfer -> its sleeves follow the target base's arms down. Same core.pose
code the operator uses, on the real TechSet->Egirl bone map."""
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(R.REPO_ROOT))
from sculpt_tool.core import rig, rig_map, pose  # noqa

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

SKIN = (0.80, 0.64, 0.55, 1.0)
CLOTH = (0.30, 0.45, 0.72, 1.0)
GARMENT = "Sweater by Vinuzhka"


def point_bone_along(arm, bone_name, world_dir):
    pb = arm.pose.bones.get(bone_name)
    if pb is None:
        return
    bone = arm.data.bones[bone_name]
    d = Vector(world_dir).normalized()
    rest = arm.matrix_world @ bone.matrix_local
    rest_axis = (rest.to_3x3() @ Vector((0, 1, 0))).normalized()
    swing = rest_axis.rotation_difference(d)
    # express desired world orientation, convert to armature space
    desired_world = (swing.to_matrix() @ rest.to_3x3()).to_4x4()
    desired_world.translation = rest.translation
    pb.matrix = arm.matrix_world.inverted() @ desired_world
    bpy.context.view_layer.update()


def load_side(xoff, do_transfer):
    body = R.import_group(R.TEST_ITEMS / "Body" / "vrbase_Egirl_Heeled Foot.fbx", {"BODY"})
    garment = R.import_group(R.TEST_ITEMS / "Clothing" / "FBX-Tech Set by Vinuzhka.fbx", {GARMENT})
    body_mesh = next(o for o in body if o.type == 'MESH')
    gar_mesh = next(o for o in garment if o.type == 'MESH')
    body_rig = rig.deforming_armature(body_mesh)
    gar_rig = rig.deforming_armature(gar_mesh)

    # Pose the TARGET base arms DOWN (and slightly out).
    point_bone_along(body_rig, "Arm_L", (0.35, 0.0, -0.94))
    point_bone_along(body_rig, "Arm_R", (-0.35, 0.0, -0.94))
    bpy.context.view_layer.update()

    if do_transfer:
        bmap = rig_map.build_bone_map(rig.bone_names(gar_rig), rig.bone_names(body_rig))
        rots = pose.compute_pose_rotations(gar_rig, body_rig, bmap.as_pairs())
        for bname, q in rots.items():
            pb = gar_rig.pose.bones.get(bname)
            if pb:
                pb.rotation_mode = 'QUATERNION'
                pb.rotation_quaternion = q
        bpy.context.view_layer.update()
        print(f"transfer: posed {len(rots)} garment bones; pairs={len(bmap.as_pairs())}")

    R.offset_group(body + garment, (xoff, 0, 0))
    body_mesh.color = SKIN
    gar_mesh.color = CLOTH
    return body_mesh, gar_mesh


lb, lg = load_side(0.0, do_transfer=False)
rb, rg = load_side(1.7, do_transfer=True)

R.setup_workbench(resolution=(1500, 1200))
meshes = [lb, lg, rb, rg]
center, radius, mins, maxs = R._scene_bounds(meshes)
R.add_label("R3: Pose Transfer -- garment follows the target base's limbs before fitting",
            (center.x, mins.y - 0.3, maxs.z + 0.2), size=0.082, color=(0.96,0.96,0.98))
R.add_label("BEFORE -- sleeves stick out (T-pose garment on arms-down base)",
            (0.0, mins.y - 0.3, mins.z - 0.1), size=0.058, color=(0.95,0.7,0.6))
R.add_label("AFTER pose transfer -- sleeves follow the arms down",
            (1.7, mins.y - 0.3, mins.z - 0.1), size=0.058, color=(0.6,0.9,0.65))

R.frame_camera(meshes, azimuth_deg=0, elevation_deg=6, zoom=1.12)
out = Path(__file__).parent / "out" / "r3_pose_transfer.png"
out.parent.mkdir(exist_ok=True)
R.render_to(out)
