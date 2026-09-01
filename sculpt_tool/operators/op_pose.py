"""OT_pose_to_target -- the pose-transfer stage (roadmap R3).

Poses the garment's own armature to match the Target Base Rig's pose, via
the R2 canonical bone map, so the garment (deformed through its own skin
weights by its Armature modifier) is grossly placed onto the target base
before Fit runs -- the missing Stage 1 (see ``core.pose`` and DECISIONS.md
section 6f). This operator is setup + apply: it resolves the rigs and bone
map, calls ``core.pose.compute_pose_rotations`` (pure), and writes the
result onto the garment armature's pose bones.

A later card (R5) calls this automatically as the first step of Bind/Fit/
Batch; here it's a standalone "Pose to Target Base" button so the stage can
be run and inspected on its own.
"""

import bpy

from . import op_bases
from ..core import pose


class SCULPTTOOL_OT_pose_to_target(bpy.types.Operator):
    bl_idname = "sculpttool.pose_to_target"
    bl_label = "Pose to Target Base"
    bl_description = (
        "Pose the garment's armature to match the Target Base Rig (via the "
        "canonical bone map), so the garment follows the target base's limbs "
        "before fitting. Run Fit afterwards to conform the surface"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != 'MESH':
            return False
        settings = getattr(obj, "sculpt_tool", None)
        if settings is None:
            return False
        # Needs both a garment rig and a target base rig to transfer between.
        return (
            op_bases.garment_rig(obj, settings) is not None
            and getattr(settings, "target_base_armature", None) is not None
        )

    def execute(self, context):
        garment_obj = context.object
        settings = garment_obj.sculpt_tool

        garment_arm = op_bases.garment_rig(garment_obj, settings)
        target_arm = settings.target_base_armature
        if garment_arm is None:
            self.report({'ERROR'}, "No garment/source rig found (run Detect Rigs, or rig the garment).")
            return {'CANCELLED'}
        if target_arm is None:
            self.report({'ERROR'}, "No Target Base Rig set (run Detect Rigs, or pick one).")
            return {'CANCELLED'}

        bone_map, reason = op_bases.compute_garment_to_target_map(garment_obj, settings)
        if bone_map is None:
            self.report({'ERROR'}, f"Cannot pose: {reason}.")
            return {'CANCELLED'}

        pairs = bone_map.as_pairs()
        rotations = pose.compute_pose_rotations(garment_arm, target_arm, pairs)
        if not rotations:
            self.report(
                {'WARNING'},
                "Pose transfer resolved no shared bones to pose -- check the "
                "bone map (Compute Bone Map).",
            )
            return {'CANCELLED'}

        posed = 0
        for bone_name, quaternion in rotations.items():
            garment_pose_bone = garment_arm.pose.bones.get(bone_name)
            if garment_pose_bone is None:
                continue
            garment_pose_bone.rotation_mode = 'QUATERNION'
            garment_pose_bone.rotation_quaternion = quaternion
            posed += 1

        context.view_layer.update()

        self.report(
            {'INFO'},
            f"Posed '{garment_arm.name}' to '{target_arm.name}' ({posed} bones). "
            "Run Fit to conform the surface.",
        )
        return {'FINISHED'}


_classes = (
    SCULPTTOOL_OT_pose_to_target,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
