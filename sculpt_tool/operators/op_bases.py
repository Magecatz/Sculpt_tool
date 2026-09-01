"""Base-retargeting operators: rig detection (R1) + bone mapping (R2).

- ``OT_detect_rigs`` (roadmap R1, card 062cfedd) auto-fills the source/
  target base armature pickers from the Source/Target Body.
- ``OT_compute_bone_map`` + ``OT_bone_override_add``/``_remove`` (roadmap
  R2, card 1b7b56eb) build and report the canonical garment<->target-base
  bone correspondence via ``core.rig_map``, honoring the user's manual
  override rows. Still no posing -- that's R3; these only resolve and
  surface the mapping the pose transfer will consume.

``OT_detect_rigs`` -- the "Detect Rigs" button: it resolves the garment's
source-base rig and the target base's rig from the meshes already picked
(Source Body / Target Body), so the user rarely has to pick armatures by
hand. Pure discovery -- it does not pose, match, or bind anything.

Resolution (via ``core.rig.deforming_armature``):

- ``source_base_armature`` <- the Source Body's own deforming armature, or
  -- when the Source Body has no rig (or none is set yet) -- the garment's
  own deforming armature. The garment is skinned to a rig sharing its
  source base's naming convention (DECISIONS.md section 6e), so the
  garment's own rig is a sound fallback for "the source-base naming
  convention" when a standalone source-base body rig isn't available.
- ``target_base_armature`` <- the Target Body's own deforming armature.

Anything it can't resolve is left untouched (so a hand-picked value isn't
clobbered by a detect run that found nothing), and the operator reports
what it did/didn't find rather than failing outright.
"""

import bpy

from ..core import rig, rig_map


class SCULPTTOOL_OT_detect_rigs(bpy.types.Operator):
    bl_idname = "sculpttool.detect_rigs"
    bl_label = "Detect Rigs"
    bl_description = (
        "Auto-fill the Source Base Rig and Target Base Rig from the "
        "armatures deforming the Source Body / Target Body (or the garment "
        "itself for the source side). Does not pose or bind anything"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != 'MESH':
            return False
        return getattr(obj, "sculpt_tool", None) is not None

    def execute(self, context):
        garment_obj = context.object
        settings = garment_obj.sculpt_tool

        source_body = getattr(settings, "source_body", None)
        target_body = getattr(settings, "target_body", None)

        source_rig = rig.deforming_armature(source_body)
        if source_rig is None:
            # Fall back to the garment's own rig -- it shares the source
            # base's bone-naming convention (see module docstring).
            source_rig = rig.deforming_armature(garment_obj)
        target_rig = rig.deforming_armature(target_body)

        found = []
        if source_rig is not None:
            settings.source_base_armature = source_rig
            found.append(f"source '{source_rig.name}'")
        if target_rig is not None:
            settings.target_base_armature = target_rig
            found.append(f"target '{target_rig.name}'")

        if not found:
            self.report(
                {'WARNING'},
                "Detect Rigs found no armature deforming the garment, "
                "Source Body, or Target Body -- pick rigs by hand, or set "
                "Source/Target Body first.",
            )
            return {'CANCELLED'}

        self.report({'INFO'}, "Detected " + " and ".join(found) + " base rig(s).")
        return {'FINISHED'}


def garment_rig(garment_obj, settings):
    """The rig whose bones the pose transfer reads FROM on the garment side:
    the garment's own deforming armature, falling back to the explicitly
    picked Source Base Rig. Used by the bone-map compute op and (later) the
    pose-transfer stage."""
    own = rig.deforming_armature(garment_obj)
    if own is not None:
        return own
    return getattr(settings, "source_base_armature", None)


def compute_garment_to_target_map(garment_obj, settings):
    """Build the garment-rig -> target-base-rig :class:`core.rig_map.BoneMap`
    for ``garment_obj``, honoring the user's manual override rows, or return
    ``(None, reason)`` if a rig is missing. Shared by the compute operator
    and the pose-transfer stage so both derive the map identically."""
    source_rig = garment_rig(garment_obj, settings)
    target_rig = getattr(settings, "target_base_armature", None)
    if source_rig is None:
        return None, "no garment/source rig (run Detect Rigs, or rig the garment)"
    if target_rig is None:
        return None, "no Target Base Rig set (run Detect Rigs, or pick one)"

    overrides = [
        (o.source_bone, o.target_bone)
        for o in getattr(settings, "bone_map_overrides", ())
        if o.source_bone
    ]
    bone_map = rig_map.build_bone_map(
        rig.bone_names(source_rig), rig.bone_names(target_rig), overrides=overrides
    )
    return bone_map, None


class SCULPTTOOL_OT_compute_bone_map(bpy.types.Operator):
    bl_idname = "sculpttool.compute_bone_map"
    bl_label = "Compute Bone Map"
    bl_description = (
        "Match the garment rig's bones to the Target Base Rig's bones by "
        "canonical humanoid joint (normalizing naming differences), applying "
        "any manual overrides. Reports coverage and surfaces unmatched bones"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'MESH' and getattr(obj, "sculpt_tool", None) is not None

    def execute(self, context):
        garment_obj = context.object
        settings = garment_obj.sculpt_tool

        bone_map, reason = compute_garment_to_target_map(garment_obj, settings)
        if bone_map is None:
            settings.bone_map_summary = f"Cannot compute: {reason}"
            self.report({'WARNING'}, f"Compute Bone Map: {reason}.")
            return {'CANCELLED'}

        missing = rig_map.missing_primary_bones(bone_map)
        summary = (
            f"{len(bone_map.pairs)} pairs; "
            f"{len(missing)} primary-chain gaps; "
            f"{len(bone_map.source_unmapped)} garment helper bones unmatched"
        )
        settings.bone_map_summary = summary

        # Surface detail to the console (the board/UI stays terse).
        print("[Sculpt Tool] Bone map:", summary)
        if missing:
            print("  primary-chain gaps:", [cb.label() for cb in missing])
        if bone_map.source_only:
            print(
                "  garment joints with no target counterpart:",
                [f"{name}->{cb.label()}" for name, cb in bone_map.source_only],
            )

        level = {'WARNING'} if missing else {'INFO'}
        self.report(level, "Bone map: " + summary + ".")
        return {'FINISHED'}


class SCULPTTOOL_OT_bone_override_add(bpy.types.Operator):
    bl_idname = "sculpttool.bone_override_add"
    bl_label = "Add Bone Override"
    bl_description = "Add a manual garment->target bone-map override row"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and getattr(obj, "sculpt_tool", None) is not None

    def execute(self, context):
        settings = context.object.sculpt_tool
        settings.bone_map_overrides.add()
        settings.bone_map_overrides_index = len(settings.bone_map_overrides) - 1
        return {'FINISHED'}


class SCULPTTOOL_OT_bone_override_remove(bpy.types.Operator):
    bl_idname = "sculpttool.bone_override_remove"
    bl_label = "Remove Bone Override"
    bl_description = "Remove the selected manual bone-map override row"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        settings = getattr(obj, "sculpt_tool", None) if obj else None
        return bool(settings and settings.bone_map_overrides)

    def execute(self, context):
        settings = context.object.sculpt_tool
        index = settings.bone_map_overrides_index
        if 0 <= index < len(settings.bone_map_overrides):
            settings.bone_map_overrides.remove(index)
            settings.bone_map_overrides_index = min(
                index, len(settings.bone_map_overrides) - 1
            )
        return {'FINISHED'}


_classes = (
    SCULPTTOOL_OT_detect_rigs,
    SCULPTTOOL_OT_compute_bone_map,
    SCULPTTOOL_OT_bone_override_add,
    SCULPTTOOL_OT_bone_override_remove,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
