"""Pin vertex-group helper operators.

Per ARCHITECTURE.md sections 4 and 6: small operators backing the Pin
Regions section of ``ui_panel.py`` — add a new pin group, remove the
active one, and assign/select vertices against it. This mirrors
Blender's own built-in Object Data Properties > Vertex Groups workflow
deliberately: Assign and Select delegate straight to the built-in
``bpy.ops.object.vertex_group_assign`` / ``vertex_group_select``
operators (rather than reimplementing selection-state bookkeeping), so
behavior matches the built-in UI exactly, not just visually, and the
"Weight" value used by Assign is the same ``scene.tool_settings.
vertex_group_weight`` the built-in Vertex Groups panel uses.

``core.smoothing.PIN_GROUP_PREFIX`` (``"Pin_"``) is the single source of
truth for which vertex groups count as pin regions. These operators
read/write plain ``obj.vertex_groups`` entries by that name convention
only and add no new ``PropertyGroup`` state of their own (per Architect
scope note on this card) — anything created or renamed here is picked
up by ``core.smoothing.compute_pin_weights`` with no extra wiring, and
anything renamed to drop the prefix simply stops counting as a pin
region, exactly as it should.
"""

import bpy

from ..core.smoothing import PIN_GROUP_PREFIX

DEFAULT_PIN_GROUP_NAME = PIN_GROUP_PREFIX + "Region"


def _active_pin_group(obj):
    """The active vertex group on ``obj``, if it is a ``Pin_*`` group.

    Returns ``None`` for a non-mesh/``None`` object, an object with no
    active vertex group, or an active group whose name doesn't start
    with :data:`PIN_GROUP_PREFIX` — the Pin Regions section only ever
    operates on the latter, even though ``obj.vertex_groups.active`` is
    shared with any non-pin groups the object might also have.
    """
    if obj is None or obj.type != 'MESH':
        return None
    vg = obj.vertex_groups.active
    if vg is None or not vg.name.startswith(PIN_GROUP_PREFIX):
        return None
    return vg


class SCULPTTOOL_OT_pin_group_add(bpy.types.Operator):
    bl_idname = "sculpttool.pin_group_add"
    bl_label = "Add Pin Region"
    bl_description = (
        "Create a new Pin_* vertex group on the active object and make "
        "it active (name is auto-uniquified if it already exists, same "
        "as the built-in vertex group 'New' button)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        obj = context.object
        vg = obj.vertex_groups.new(name=DEFAULT_PIN_GROUP_NAME)
        obj.vertex_groups.active_index = vg.index
        self.report({'INFO'}, f"Added pin region '{vg.name}'.")
        return {'FINISHED'}


class SCULPTTOOL_OT_pin_group_remove(bpy.types.Operator):
    bl_idname = "sculpttool.pin_group_remove"
    bl_label = "Remove Pin Region"
    bl_description = (
        "Delete the active Pin_* vertex group entirely (not just "
        "unassign vertices from it)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_pin_group(context.object) is not None

    def execute(self, context):
        obj = context.object
        vg = _active_pin_group(obj)
        if vg is None:
            self.report({'ERROR'}, "No active Pin_* vertex group to remove.")
            return {'CANCELLED'}
        name = vg.name
        obj.vertex_groups.remove(vg)
        self.report({'INFO'}, f"Removed pin region '{name}'.")
        return {'FINISHED'}


class SCULPTTOOL_OT_pin_group_assign(bpy.types.Operator):
    bl_idname = "sculpttool.pin_group_assign"
    bl_label = "Assign"
    bl_description = (
        "Assign the selected vertices (Edit Mode) to the active Pin_* "
        "vertex group at the current Weight -- delegates to Blender's "
        "built-in Assign vertex-group operator"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (
            obj is not None
            and obj.mode == 'EDIT'
            and _active_pin_group(obj) is not None
        )

    def execute(self, context):
        return bpy.ops.object.vertex_group_assign()


class SCULPTTOOL_OT_pin_group_select(bpy.types.Operator):
    bl_idname = "sculpttool.pin_group_select"
    bl_label = "Select"
    bl_description = (
        "Select the vertices (Edit Mode) that belong to the active "
        "Pin_* vertex group -- delegates to Blender's built-in Select "
        "vertex-group operator"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (
            obj is not None
            and obj.mode == 'EDIT'
            and _active_pin_group(obj) is not None
        )

    def execute(self, context):
        return bpy.ops.object.vertex_group_select()


_classes = (
    SCULPTTOOL_OT_pin_group_add,
    SCULPTTOOL_OT_pin_group_remove,
    SCULPTTOOL_OT_pin_group_assign,
    SCULPTTOOL_OT_pin_group_select,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
