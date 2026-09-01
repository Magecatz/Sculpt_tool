"""N-sidebar UI for Sculpt Tool.

Per ARCHITECTURE.md section 4: a single panel in the 3D Viewport's
"Sculpt Tool" tab with sections for Binding, Base Retargeting, Fit,
Parameters, Pin Regions, and Batch.

The Base Retargeting section (roadmap R1, card 062cfedd) exposes the
source/target base rig pickers (``settings.source_base_armature`` /
``settings.target_base_armature``) and the Detect Rigs button
(operators/op_bases.py), plus a read-out of the garment's own rig and the
two base rigs' bone counts via ``core.rig``. It only records/selects rigs;
nothing here poses or matches bones (that's roadmap R2/R3).

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
vertex_group_weight`` the built-in panel uses). Batch is wired to
OT_batch_fit (operators/op_batch.py): a Target Collection picker
(``settings.batch_target_collection``) plus the Run Batch button, which
reuses every field already exposed in Parameters above -- there are
deliberately no separate batch-only offset/collision/smoothing fields,
per ARCHITECTURE.md section 8's "no separate batch-specific solver
logic".
"""

import bpy

from .core import rig, storage
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


class SCULPTTOOL_UL_bone_overrides(bpy.types.UIList):
    """Editable list of manual bone-map override rows (roadmap R2): each
    row is a garment-bone -> target-bone text pair the user can correct/
    supply where the auto-resolver missed."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "source_bone", text="", emboss=True)
        row.label(icon='FORWARD')
        row.prop(item, "target_bone", text="", emboss=True)


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

        base_box = layout.box()
        base_box.label(text="Base Retargeting", icon='ARMATURE_DATA')
        if settings:
            base_box.prop(settings, "source_base_armature")
            base_box.prop(settings, "target_base_armature")
            base_box.operator("sculpttool.detect_rigs", icon='BONE_DATA')
            # Read-out: the garment's own rig and the two base rigs' bone
            # counts, so the user can see at a glance that a rig was found
            # and roughly how big it is (a later card maps these bones).
            garment_rig = rig.deforming_armature(obj) if obj else None
            if garment_rig is not None:
                base_box.label(
                    text=f"Garment rig: '{garment_rig.name}' "
                    f"({len(rig.bone_names(garment_rig))} bones)",
                    icon='BONE_DATA',
                )
            for label, arm in (
                ("Source base", settings.source_base_armature),
                ("Target base", settings.target_base_armature),
            ):
                info = rig.RigInfo.describe(arm)
                if info is not None:
                    base_box.label(
                        text=f"{label}: '{info.name}' ({info.bone_count} bones)",
                        icon='CHECKMARK',
                    )

            # Bone Map (roadmap R2): compute the canonical garment<->target
            # correspondence, show its summary, and let the user override
            # individual pairs.
            map_col = base_box.column(align=True)
            map_col.operator("sculpttool.compute_bone_map", icon='BONE_DATA')
            if settings.bone_map_summary:
                map_col.label(text=settings.bone_map_summary, icon='INFO')

            map_col.label(text="Manual overrides:")
            override_row = map_col.row()
            override_row.template_list(
                "SCULPTTOOL_UL_bone_overrides", "",
                settings, "bone_map_overrides",
                settings, "bone_map_overrides_index",
                rows=2,
            )
            override_buttons = override_row.column(align=True)
            override_buttons.operator("sculpttool.bone_override_add", icon='ADD', text="")
            override_buttons.operator("sculpttool.bone_override_remove", icon='REMOVE', text="")

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
            params_box.prop(settings, "skip_alignment_check")

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
        if settings:
            batch_box.prop(settings, "batch_target_collection")
        batch_box.operator("sculpttool.batch_fit", icon='RENDERLAYERS')


_classes = (
    SCULPTTOOL_UL_pin_groups,
    SCULPTTOOL_UL_bone_overrides,
    SCULPTTOOL_PT_main,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
