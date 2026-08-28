"""N-sidebar UI for Sculpt Tool.

Per ARCHITECTURE.md section 4: a single panel in the 3D Viewport's
"Sculpt Tool" tab with sections for Binding, Fit, Parameters, Pin
Regions, and Batch.

Scaffold only — sections are placeholder labels (plus the source/target
body pickers already backed by properties.py). No operators exist yet,
so there are no functional buttons; later cards wire OT_bind_garment,
OT_fit_garment, OT_batch_fit, and the pin-group helpers in here.
"""

import bpy


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
        binding_box.label(text="(Bind button — coming soon)")

        fit_box = layout.box()
        fit_box.label(text="Fit", icon='MOD_SHRINKWRAP')
        if settings:
            fit_box.prop(settings, "target_body")
        fit_box.label(text="(Fit button — coming soon)")

        params_box = layout.box()
        params_box.label(text="Parameters", icon='PROPERTIES')
        params_box.label(text="(Offset, collision margin, smoothing — coming soon)")

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
