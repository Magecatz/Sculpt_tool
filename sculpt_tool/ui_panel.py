"""N-sidebar UI for Sculpt Tool.

Per ARCHITECTURE.md section 4: a single panel in the 3D Viewport's
"Sculpt Tool" tab with sections for Binding, Fit, Parameters, Pin
Regions, and Batch.

Binding section is wired to OT_bind_garment (operators/op_bind.py); Fit
section (plus the offset/thickness-scale, collision-resolution toggle,
collision-margin, and smoothing-iterations fields in Parameters) is
wired to OT_fit_garment (operators/op_fit.py). Pin Regions and Batch are
still placeholder labels — later cards wire OT_batch_fit and the
pin-group helpers in here.
"""

import bpy

from .core import storage


class SCULPTTOOL_PT_main(bpy.types.Panel):
    bl_label = "Sculpt Tool"
    bl_idname = "SCULPTTOOL_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Sculpt Tool"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        settings = getattr(obj, "sculpt_tool", None) if obj else None

        binding_box = layout.box()
        binding_box.label(text="Binding", icon='MOD_MESHDEFORM')
        if settings:
            binding_box.prop(settings, "source_body")
            binding_box.prop(settings, "bind_mode_override")
        binding_box.operator("sculpttool.bind_garment", icon='MOD_MESHDEFORM')
        if obj is not None and obj.type == 'MESH' and storage.is_bound(obj):
            source_name, mode, version = storage.get_binding_info(obj)
            binding_box.label(
                text=f"Bound to '{source_name}' (Mode {mode}, v{version})",
                icon='CHECKMARK',
            )

        fit_box = layout.box()
        fit_box.label(text="Fit", icon='MOD_SHRINKWRAP')
        if settings:
            fit_box.prop(settings, "target_body")
        fit_box.operator("sculpttool.fit_garment", icon='MOD_SHRINKWRAP')

        params_box = layout.box()
        params_box.label(text="Parameters", icon='PROPERTIES')
        if settings:
            params_box.prop(settings, "offset_scale")
            params_box.prop(settings, "use_collision_resolution")
            collision_row = params_box.row()
            collision_row.enabled = settings.use_collision_resolution
            collision_row.prop(settings, "collision_margin")
            params_box.prop(settings, "smoothing_iterations")

        pins_box = layout.box()
        pins_box.label(text="Pin Regions", icon='GROUP_VERTEX')
        pins_box.label(text="(Pin vertex-group list — coming soon)")

        batch_box = layout.box()
        batch_box.label(text="Batch", icon='RENDERLAYERS')
        batch_box.label(text="(Target collection + Run Batch — coming soon)")


_classes = (
    SCULPTTOOL_PT_main,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
