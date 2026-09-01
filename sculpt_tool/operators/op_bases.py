"""OT_detect_rigs -- auto-fill the source/target base armature pickers.

Roadmap R1 (Bear PR Process card 062cfedd-eb70-4e55-9500-ef00b03b6b72).
Convenience operator behind the "Detect Rigs" button in the Base
Retargeting UI section: it resolves the garment's source-base rig and the
target base's rig from the meshes already picked (Source Body / Target
Body), so the user rarely has to pick armatures by hand. Pure discovery --
it does not pose, match, or bind anything (that's R2/R3).

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

from ..core import rig


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


_classes = (
    SCULPTTOOL_OT_detect_rigs,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
