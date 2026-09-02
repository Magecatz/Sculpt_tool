"""N-sidebar UI for Sculpt Tool.

Conform-rebuild restart (RESTART_SCOPE.md): the surface-conform stage was
removed, so this panel is trimmed to the **placement spine** plus the pin-
region authoring the coming elastic conform will consume. The Binding, Fit,
Parameters, and Batch sections (wired to the deleted OT_bind_garment /
OT_fit_garment / OT_batch_fit) are gone; they return with the new conform.

Remaining sections:

- **Base Retargeting** (roadmap R1/R2) -- source/target base rig pickers
  (``settings.source_base_armature`` / ``settings.target_base_armature``),
  the Detect Rigs button (operators/op_bases.py), a read-out of the garment's
  own rig and the two base rigs' bone counts via ``core.rig``, the canonical
  bone-map compute + manual overrides, and the **Place onto Target Base**
  button (operators/op_pose.py -- position + rotation + scale).
- **Pin Regions** -- the active object's ``Pin_*`` vertex groups
  (``core.smoothing.PIN_GROUP_PREFIX`` is the naming source of truth), wired
  to the add/remove/assign/select helpers in operators/op_pin_groups.py,
  laid out like Blender's own Vertex Groups panel.
"""

import bpy

from .core import rig
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

            # Placement (roadmap R3 pose + R7 position/scale): place the
            # garment onto the target base via the bone map -- move, rotate,
            # and scale each region to the matching part of the base -- before
            # fitting. Fit/Batch also run the stage-0 transfer automatically
            # when auto_pose_transfer is on.
            base_box.operator("sculpttool.pose_to_target", icon='POSE_HLT')
            base_box.prop(settings, "auto_pose_transfer")

        conform_box = layout.box()
        conform_box.label(text="Conform", icon='MOD_SHRINKWRAP')
        if settings:
            conform_box.prop(settings, "target_body")
            conform_box.prop(settings, "source_body", text="Source Base (optional)")
            # The Source Base is the body the garment was ORIGINALLY authored
            # for -- import that base's FBX and pick its body mesh here to
            # preserve the garment's authored standoff. Without it, standoff is
            # approximated from the placement (loose fits are less faithful).
            if settings.source_body is None:
                conform_box.label(
                    text="No Source Base: standoff approximated.", icon='INFO',
                )
        conform_box.operator("sculpttool.conform", icon='MOD_SHRINKWRAP')

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
