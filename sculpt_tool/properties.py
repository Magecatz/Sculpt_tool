"""Per-object Sculpt Tool settings.

Per ARCHITECTURE.md sections 4 and 6: a PropertyGroup attached to the
garment Object so settings travel with the object, not just the scene.

Scaffold only — just the source/target body pointers for now. Later
cards add offset/thickness scale, collision margin, smoothing
iterations, pin vertex-group references, and the bind-mode override.
"""

import bpy


class SCULPTTOOL_PG_settings(bpy.types.PropertyGroup):
    source_body: bpy.props.PointerProperty(
        name="Source Body",
        description="Body mesh the garment was originally authored/bound to",
        type=bpy.types.Object,
    )
    target_body: bpy.props.PointerProperty(
        name="Target Body",
        description="Body mesh to fit the garment onto",
        type=bpy.types.Object,
    )


_classes = (
    SCULPTTOOL_PG_settings,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.sculpt_tool = bpy.props.PointerProperty(
        type=SCULPTTOOL_PG_settings,
    )


def unregister():
    del bpy.types.Object.sculpt_tool

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
