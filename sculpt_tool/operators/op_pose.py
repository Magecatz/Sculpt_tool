"""OT_pose_to_target -- the placement stage (roadmap R3 pose, R7 placement).

Places the garment's own armature onto the Target Base Rig via the R2
canonical bone map, so the garment (deformed through its own skin weights
by its Armature modifier) is grossly placed onto the target base before Fit
runs -- the missing Stage 1 (see ``core.pose`` and DECISIONS.md section
6f). As of R7 this is a full PLACEMENT -- position + rotation + length-scale
per bone (``core.pose.compute_bone_placements`` via
:func:`place_garment_onto_rig`) -- so each clothing region is moved and
sized to the target base, not just rotated. The rotation-only transfer
(:func:`pose_garment_onto_rig`, ``core.pose.compute_pose_rotations``) is
retained for the Fit/Batch stage-0 integration until R8 switches it over.

This operator is setup + apply: it resolves the rigs and bone map, calls
the pure ``core.pose`` computation, and writes the result onto the garment
armature's pose bones. The standalone "Place onto Target Base" button lets
the stage be run and inspected on its own.
"""

import bpy
from mathutils import Quaternion, Vector

from . import op_bases
from ..core import pose, rig, rig_map


def set_armature_deform_visible(garment_obj, visible):
    """Show/hide the garment's Armature modifier deformation, and report
    whether any was changed. After a placement fit bakes the placed garment
    into the Fitted Shape Key, the live Armature modifier is hidden so it
    doesn't deform that bake a second time (roadmap R8 -- placement is
    already captured in the key). Reversible (re-enable to get the rig back)."""
    changed = False
    for modifier in garment_obj.modifiers:
        if modifier.type == 'ARMATURE':
            modifier.show_viewport = visible
            modifier.show_render = visible
            changed = True
    return changed


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
    """Rotation-only pose transfer (roadmap R3/R5). Poses ``garment_arm`` to
    match ``target_arm``'s pose via the R2 bone map, resetting to rest
    first. Returns the number of bones posed. Retained for the Fit/Batch
    stage-0 integration until R8 switches it to full placement; see
    :func:`place_garment_onto_rig`."""
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


def place_garment_onto_rig(context, garment_arm, target_arm, overrides=()):
    """Full PLACEMENT (position + rotation + length-scale) of ``garment_arm``
    onto ``target_arm`` via the R2 bone map (roadmap R7).

    Resets the garment armature to rest, then for each mapped bone (parent-
    first) sets its pose so it coincides with the target base bone's world
    position, orientation, and length -- moving and scaling each clothing
    region to the target base, not just rotating it. A depsgraph update
    between bones lets each child be placed relative to its already-placed
    parent. Returns the number of bones placed."""
    bone_map = rig_map.build_bone_map(
        rig.bone_names(garment_arm), rig.bone_names(target_arm), overrides=overrides
    )
    placements = pose.compute_bone_placements(garment_arm, target_arm, bone_map.as_pairs())

    reset_pose(garment_arm)
    context.view_layer.update()
    armature_world_inv = garment_arm.matrix_world.inverted()
    placed = 0
    for bone_name, world_rigid, length_scale in placements:
        pose_bone = garment_arm.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        # Each placed bone is sized to its OWN target length; disable scale
        # inheritance so a chain (upper arm -> forearm -> hand) doesn't
        # compound its ancestors' stretches.
        pose_bone.bone.inherit_scale = 'NONE'
        # Position + orientation (orthonormal) via matrix, then the along-
        # bone (Y) length stretch via an explicit scale -- kept separate so
        # the matrix stays clean (see core.pose.compute_bone_placements).
        pose_bone.matrix = armature_world_inv @ world_rigid
        pose_bone.scale = (1.0, length_scale, 1.0)
        context.view_layer.update()  # so children place against the placed parent
        placed += 1
    return placed


class SCULPTTOOL_OT_pose_to_target(bpy.types.Operator):
    bl_idname = "sculpttool.pose_to_target"
    bl_label = "Place onto Target Base"
    bl_description = (
        "Place the garment's armature onto the Target Base Rig (via the "
        "canonical bone map): move, rotate, and scale each clothing region "
        "to the matching part of the target base, so the garment sits at the "
        "right height and size. Run Fit afterwards to conform the surface"
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
        placed = place_garment_onto_rig(context, garment_arm, target_arm, overrides)
        if not placed:
            self.report(
                {'WARNING'},
                "Placement resolved no shared bones -- check the bone map "
                "(Compute Bone Map).",
            )
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Placed '{garment_arm.name}' onto '{target_arm.name}' "
            f"({placed} bones: position + rotation + scale). "
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
