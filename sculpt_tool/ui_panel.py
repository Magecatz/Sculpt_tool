"""N-sidebar UI for Sculpt Tool.

Per ARCHITECTURE.md section 4: a single panel in the 3D Viewport's
"Sculpt Tool" tab with sections for Binding, Fit, Parameters, Pin
Regions, and Batch.

Binding section is wired to OT_bind_garment (operators/op_bind.py); Fit
section (plus the offset/thickness-scale, collision-resolution toggle,
collision-margin, and smoothing-iterations fields in Parameters) is
wired to OT_fit_garment (operators/op_fit.py). Pin Regions lists the
active object's ``Pin_*`` vertex groups (``core.smoothing.
PIN_GROUP_PREFIX`` is the naming source of truth) and is wired to the
add/remove/assign/select helpers in operators/op_pin_groups.py, laid
out the same way Blender's own Object Data Properties > Vertex Groups
panel is (a filtered ``UIList`` + side add/remove column + an
Assign/Select row using the same ``scene.tool_settings.
vertex_group_weight`` the built-in panel uses). Batch is still a
stubbed/disabled placeholder — a later card wires OT_batch_fit.
"""

import bpy

from .core import storage
from .core.smoothing import PIN_GROUP_PREFIX


class SCULPTTOOL_UL_pin_groups(bpy.types.UIList):
    """Vertex-group list filtered down to ``Pin_*`` groups only.

    ``SCULPTTOOL_PT_main.draw()`` binds this to the object's real
    ``vertex_groups`` collection and its real ``active_index`` --
    filtering only affects which rows are visible, so selecting a
    visible row sets the actual active vertex group, exactly as
    Blender's own filtered UILists work.
    """

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "name", text="", emboss=False, icon='GROUP_VERTEX')

    def filter_items(self, context, data, propname):
        vertex_groups = getattr(data, propname)
        flags = [
            self.bitflag_filter_item if vg.name.startswith(PIN_GROUP_PREFIX) else 0
            for vg in vertex_groups
        ]
        return flags, []


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
        if obj is not None and obj.type == 'MESH':
            list_row = pins_box.row()
            list_row.template_list(
                "SCULPTTOOL_UL_pin_groups", "",
                obj, "vertex_groups",
                obj.vertex_groups, "active_index",
                rows=4,
            )
            list_buttons = list_row.column(align=True)
            list_buttons.operator("sculpttool.pin_group_add", icon='ADD', text="")
            list_buttons.operator("sculpttool.pin_group_remove", icon='REMOVE', text="")

            assign_row = pins_box.row(align=True)
            assign_row.operator("sculpttool.pin_group_assign", text="Assign")
            assign_row.operator("sculpttool.pin_group_select", text="Select")
            pins_box.prop(context.scene.tool_settings, "vertex_group_weight", text="Weight")
        else:
            pins_box.label(text="Select a mesh object to manage Pin Regions.")

        batch_box = layout.box()
        batch_box.label(text="Batch", icon='RENDERLAYERS')
        batch_box.enabled = False
        batch_box.label(text="Target Collection: (not yet implemented)")
        batch_box.label(text="Run Batch (not yet implemented)", icon='RENDERLAYERS')


_classes = (
    SCULPTTOOL_UL_pin_groups,
    SCULPTTOOL_PT_main,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
