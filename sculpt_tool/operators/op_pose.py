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
from mathutils import Quaternion, Vector

from . import op_bases
from ..core import pose, rig, rig_map


def reset_pose(armature_obj):
    """Return every pose bone of ``armature_obj`` to rest (identity basis).

    Called before applying a transferred pose so a previous run (or, in a
    batch, a previous target base) doesn't linger -- each pose transfer
    starts from the garment's authored rest, making the result idempotent
    and per-target-correct."""
    for pose_bone in armature_obj.pose.bones:
        pose_bone.rotation_mode = 'QUATERNION'
        pose_bone.rotation_quaternion = Quaternion()
        pose_bone.location = Vector((0.0, 0.0, 0.0))
        pose_bone.scale = Vector((1.0, 1.0, 1.0))


def pose_garment_onto_rig(context, garment_arm, target_arm, overrides=()):
    """Pose ``garment_arm`` onto ``target_arm``'s current pose via the R2
    canonical bone map, resetting to rest first. Returns the number of
    bones posed (0 if no shared bones resolve). Shared by the standalone
    Pose operator and the Fit/Batch stage-0 integration (roadmap R5)."""
    bone_map = rig_map.build_bone_map(
        rig.bone_names(garment_arm), rig.bone_names(target_arm), overrides=overrides
    )
    rotations = pose.compute_pose_rotations(garment_arm, target_arm, bone_map.as_pairs())

    reset_pose(garment_arm)
    posed = 0
    for bone_name, quaternion in rotations.items():
        pose_bone = garment_arm.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        pose_bone.rotation_mode = 'QUATERNION'
        pose_bone.rotation_quaternion = quaternion
        posed += 1
    context.view_layer.update()
    return posed


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

        overrides = [
            (o.source_bone, o.target_bone)
            for o in getattr(settings, "bone_map_overrides", ())
            if o.source_bone
        ]
        posed = pose_garment_onto_rig(context, garment_arm, target_arm, overrides)
        if not posed:
            self.report(
                {'WARNING'},
                "Pose transfer resolved no shared bones to pose -- check the "
                "bone map (Compute Bone Map).",
            )
            return {'CANCELLED'}

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
