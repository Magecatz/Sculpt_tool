"""Per-object Sculpt Tool settings.

A PropertyGroup attached to the garment Object so settings travel with the
object, not just the scene.

Conform-rebuild restart (RESTART_SCOPE.md): the old bind/fit pipeline's
settings (bind-mode override, offset/thickness scale, collision toggle +
margin, smoothing iterations, the alignment-check escape hatch, and the
batch target Collection) were removed with that pipeline -- the lean
Direction-B conform (``operators/op_conform.py``) takes no numeric
parameters. What remains is the Source/Target body pointers, the source/
target base rig pointers, the canonical bone-map overrides + summary, and
the auto-pose toggle. Removed settings return with the features that need
them (e.g. a batch Collection when the Batch operator is re-added).
"""

import bpy


def _is_armature(self, obj):
    """PointerProperty poll: restrict a rig picker to Armature objects.

    Used by ``source_base_armature``/``target_base_armature`` below so the
    UI's rig dropdowns only offer Armature objects, not every object in the
    scene (roadmap R1 -- the "base" concept's source/target rig pickers).
    """
    return obj.type == 'ARMATURE'


class SCULPTTOOL_PG_bone_override(bpy.types.PropertyGroup):
    """One manual bone-map override row (roadmap R2).

    Lets a user force a garment-rig bone to pair with a specific
    target-base-rig bone, or -- with an empty ``target_bone`` -- explicitly
    leave the source bone unmapped, correcting or supplementing
    ``core.rig_map.build_bone_map``'s auto-resolution. Stored as a
    CollectionProperty on the garment's settings and passed to
    ``build_bone_map(..., overrides=...)`` by the pose-transfer stage.
    """

    source_bone: bpy.props.StringProperty(
        name="Garment Bone",
        description="Bone name on the garment/source rig to override the mapping for",
    )
    target_bone: bpy.props.StringProperty(
        name="Target Bone",
        description=(
            "Bone name on the target base rig to map it to. Leave empty to "
            "explicitly leave the garment bone unmapped"
        ),
    )


class SCULPTTOOL_PG_settings(bpy.types.PropertyGroup):
    source_body: bpy.props.PointerProperty(
        name="Source Body",
        description="Body mesh the garment was originally authored/bound to",
        type=bpy.types.Object,
    )
    target_body: bpy.props.PointerProperty(
        name="Target Body",
        description="Body mesh to fit the garment onto",
        type=bpy.types.Object,
    )
    # --- "Base" retargeting rigs (roadmap R1, card 062cfedd) ------------
    # A "base" is a rigged body a garment is authored for (DECISIONS.md
    # section 6d). These two pointers make the tool AWARE of the garment's
    # source-base rig and the chosen target-base rig -- the foundation
    # every later pose-transfer card (R2 bone mapping, R3 pose transfer)
    # builds on. R1 only records/selects them; nothing here poses or
    # matches bones yet. Auto-filled from the Source/Target Body's own
    # Armature modifier by SCULPTTOOL_OT_detect_rigs (operators/
    # op_bases.py), or picked by hand. Restricted to Armature objects via
    # the module-level ``_is_armature`` poll.
    source_base_armature: bpy.props.PointerProperty(
        name="Source Base Rig",
        description=(
            "Armature of the base body this garment was authored for. The "
            "garment is skinned to a rig sharing this base's bone-naming "
            "convention. Auto-detected from the Source Body (or the garment "
            "itself) by Detect Rigs; used by the pose-transfer stage"
        ),
        type=bpy.types.Object,
        poll=_is_armature,
    )
    target_base_armature: bpy.props.PointerProperty(
        name="Target Base Rig",
        description=(
            "Armature of the target base body to retarget the garment onto "
            "-- its pose is what a later stage transfers onto the garment. "
            "Auto-detected from the Target Body by Detect Rigs, or picked "
            "by hand. Paired with Target Body as the target base"
        ),
        type=bpy.types.Object,
        poll=_is_armature,
    )
    # --- Manual bone-map overrides + last-computed summary (R2) ---------
    bone_map_overrides: bpy.props.CollectionProperty(
        type=SCULPTTOOL_PG_bone_override,
        name="Bone Map Overrides",
        description=(
            "Manual corrections to the auto-resolved garment<->target-base "
            "bone map, applied by the pose-transfer stage"
        ),
    )
    bone_map_overrides_index: bpy.props.IntProperty(
        name="Active Override",
        default=0,
    )
    bone_map_summary: bpy.props.StringProperty(
        name="Bone Map Summary",
        description="Result of the last Compute Bone Map run (read-only)",
        default="",
    )
    auto_pose_transfer: bpy.props.BoolProperty(
        name="Auto Pose Transfer",
        description=(
            "Before fitting, automatically pose the garment onto the target "
            "base via the canonical bone map (roadmap R5 -- pose is stage 0 "
            "of the pipeline). Runs only when a garment rig and a target-base "
            "rig are both present; a no-op when the target base is already in "
            "the garment's pose. Batch poses per target base"
        ),
        default=True,
    )


_classes = (
    SCULPTTOOL_PG_bone_override,
    SCULPTTOOL_PG_settings,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.sculpt_tool = bpy.props.PointerProperty(
        type=SCULPTTOOL_PG_settings,
    )


def unregister():
    del bpy.types.Object.sculpt_tool

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
