"""OT_bind_garment.

Computes and stores a binding between the active garment object and its
declared source body (the ``obj.sculpt_tool.source_body`` pointer from
properties.py), per ARCHITECTURE.md sections 2, 4, and 6.

Mode is chosen by ``obj.sculpt_tool.bind_mode_override``: ``'AUTO'`` (the
default) delegates to ``core.binding.detect_bind_mode`` — Mode A
(same-topology) when Source Body and the declared Target Body share a
vertex count, else Mode B (cross-topology, BVH nearest-surface
projection) — while ``'MODE_A'``/``'MODE_B'`` force that choice
regardless of what auto-detection would have picked, per section 6's
escape hatch for topology-mismatch coincidences.
"""

import bpy

from ..core import binding, storage


class SCULPTTOOL_OT_bind_garment(bpy.types.Operator):
    bl_idname = "sculpttool.bind_garment"
    bl_label = "Bind Garment"
    bl_description = (
        "Bind the active garment to its Source Body (Mode A: same-topology, "
        "or Mode B: cross-topology BVH projection — auto-detected or forced "
        "via Bind Mode). Overwrites any previous binding on this garment"
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
        settings = garment_obj.sculpt_tool
        source_body_obj = settings.source_body

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

        override = getattr(settings, "bind_mode_override", 'AUTO')
        if override == 'MODE_A':
            mode = binding.MODE_A
        elif override == 'MODE_B':
            mode = binding.MODE_B
        else:
            mode = binding.detect_bind_mode(source_body_obj, settings.target_body)

        if mode == binding.MODE_A:
            result = binding.bind_mode_a(garment_obj, source_body_obj)
            storage.write_mode_a_binding(garment_obj, source_body_obj, result)
            vertex_count = len(result.body_vertex_index)
        else:
            result = binding.bind_mode_b(garment_obj, source_body_obj)
            storage.write_mode_b_binding(garment_obj, source_body_obj, result)
            vertex_count = len(result.triangle_index)

        self.report(
            {'INFO'},
            f"Bound '{garment_obj.name}' to '{source_body_obj.name}' "
            f"({vertex_count} vertices, Mode {mode}).",
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
