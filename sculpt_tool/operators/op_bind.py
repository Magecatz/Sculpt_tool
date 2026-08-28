"""OT_bind_garment.

Computes and stores a Mode A (same-topology) binding between the active
garment object and its declared source body (the
``obj.sculpt_tool.source_body`` pointer from properties.py), per
ARCHITECTURE.md sections 2 and 4.

Mode auto-detection (topology match -> Mode A, else Mode B) and the
bind-mode override parameter are not implemented yet — this card only
ships Mode A. Mode B, auto-detect, and the override live on a future
card.
"""

import bpy

from ..core import binding, storage


class SCULPTTOOL_OT_bind_garment(bpy.types.Operator):
    bl_idname = "sculpttool.bind_garment"
    bl_label = "Bind Garment"
    bl_description = (
        "Bind the active garment to its Source Body (Mode A: same-topology "
        "correspondence). Overwrites any previous binding on this garment"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != 'MESH':
            return False
        settings = getattr(obj, "sculpt_tool", None)
        return bool(
            settings
            and settings.source_body
            and settings.source_body.type == 'MESH'
        )

    def execute(self, context):
        garment_obj = context.object
        source_body_obj = garment_obj.sculpt_tool.source_body

        if source_body_obj is None or source_body_obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh Source Body before binding.")
            return {'CANCELLED'}

        if source_body_obj == garment_obj:
            self.report(
                {'ERROR'}, "Source Body must be a different object from the garment."
            )
            return {'CANCELLED'}

        if len(garment_obj.data.vertices) == 0:
            self.report({'ERROR'}, "Garment mesh has no vertices.")
            return {'CANCELLED'}

        if len(source_body_obj.data.vertices) == 0:
            self.report({'ERROR'}, "Source Body mesh has no vertices.")
            return {'CANCELLED'}

        result = binding.bind_mode_a(garment_obj, source_body_obj)
        storage.write_mode_a_binding(garment_obj, source_body_obj, result)

        self.report(
            {'INFO'},
            f"Bound '{garment_obj.name}' to '{source_body_obj.name}' "
            f"({len(result.body_vertex_index)} vertices, Mode A).",
        )
        return {'FINISHED'}


_classes = (
    SCULPTTOOL_OT_bind_garment,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
