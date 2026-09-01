"""R2 render: canonical bone mapping. Draws the primary deform chain of the
RP Female source rig (.L/.R, 'Arm'/'Wrist') and the Egirl target rig
(_L/_R, 'Arm_L'/'Wrist_L'), each bone colored by its CANONICAL joint. Same
color on both skeletons = the two differently-named bones the mapper paired."""
import colorsys
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy
from mathutils import Vector

sys.path.insert(0, str(R.REPO_ROOT))
from sculpt_tool.core import rig, rig_map  # noqa

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

SKIN = (0.78, 0.62, 0.54, 1.0)


def bone_color(canonical):
    # Stable hue per canonical joint label (ignore side so L/R share a hue).
    key = canonical.joint
    joints = list(rig_map.CENTRAL_JOINTS) + list(rig_map.SIDED_JOINTS)
    idx = joints.index(key) if key in joints else 0
    h = (idx / max(1, len(joints)))
    r, g, b = colorsys.hsv_to_rgb(h, 0.85, 1.0)
    return (r, g, b, 1.0)


def add_bone_gizmo(a, b, radius, color, name="bone"):
    vec = b - a
    length = vec.length
    if length < 1e-6:
        return None
    bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=radius, depth=length,
                                        location=(a + b) * 0.5)
    obj = bpy.context.active_object
    obj.name = name
    z = Vector((0, 0, 1))
    axis = z.cross(vec.normalized())
    angle = math.acos(max(-1, min(1, z.dot(vec.normalized()))))
    if axis.length > 1e-6:
        obj.rotation_mode = 'AXIS_ANGLE'
        obj.rotation_axis_angle = (angle, *axis.normalized())
    obj.color = color
    return obj


def draw_chain(arm, bone_names_for_pairs, radius):
    drawn = []
    for canonical, bone_name in bone_names_for_pairs:
        bone = arm.data.bones.get(bone_name)
        if bone is None:
            continue
        head = arm.matrix_world @ bone.head_local
        tail = arm.matrix_world @ bone.tail_local
        g = add_bone_gizmo(head, tail, radius, bone_color(canonical), name=bone_name)
        if g:
            drawn.append(g)
    return drawn


# Source: RP Female body + rig. Target: Egirl body + rig (offset).
src = R.import_group(R.TEST_ITEMS / "Body" / "RP Female Base_Heeled Foot.fbx", {"Body"})
src_body = next(o for o in src if o.type == 'MESH')
src_rig = rig.deforming_armature(src_body)

tgt = R.import_group(R.TEST_ITEMS / "Body" / "vrbase_Egirl_Heeled Foot.fbx", {"BODY"})
R.offset_group(tgt, (1.6, 0, 0))
tgt_body = next(o for o in tgt if o.type == 'MESH')
tgt_rig = rig.deforming_armature(tgt_body)

bmap = rig_map.build_bone_map(rig.bone_names(src_rig), rig.bone_names(tgt_rig))
print("pairs:", len(bmap.pairs), "primary gaps:", len(rig_map.missing_primary_bones(bmap)))

# Only draw the primary chain, colored by canonical joint.
primary = set(rig_map.PRIMARY_CHAIN)
src_pairs = [(c, s) for (s, t, c) in bmap.pairs if c in primary]
tgt_pairs = [(c, t) for (s, t, c) in bmap.pairs if c in primary]

# Bone radius scaled to body size.
_, radius_scene, _, _ = R._scene_bounds([src_body])
br = radius_scene * 0.022
draw_chain(src_rig, src_pairs, br)
draw_chain(tgt_rig, tgt_pairs, br)

for o in (src_body, tgt_body):
    o.color = SKIN

R.setup_workbench(resolution=(1400, 1200))
# X-ray the bodies so the colored skeleton shows through.
sh = bpy.context.scene.display.shading
sh.show_xray = True
sh.xray_alpha = 0.28
sh.show_cavity = False
meshes = [src_body, tgt_body]
center, radius, mins, maxs = R._scene_bounds(meshes)
R.add_label("R2: Canonical Bone Map -- same color = same joint, mapped across naming", (center.x, mins.y - 0.3, maxs.z + 0.18), size=0.09, color=(0.96,0.96,0.98))
R.add_label("Source rig: RP Female  ('.L' / Arm / Wrist)", (0.0, mins.y - 0.3, mins.z - 0.1), size=0.07, color=(0.9,0.9,0.95))
R.add_label("Target rig: Egirl  ('_L' / Arm_L / Wrist_L)", (1.6, mins.y - 0.3, mins.z - 0.1), size=0.07, color=(0.9,0.9,0.95))

R.frame_camera(meshes, azimuth_deg=0, elevation_deg=6, zoom=1.12)
out = Path(__file__).parent / "out" / "r2_bone_map.png"
out.parent.mkdir(exist_ok=True)
R.render_to(out)
