"""Per-object Sculpt Tool settings.

Per ARCHITECTURE.md sections 4 and 6: a PropertyGroup attached to the
garment Object so settings travel with the object, not just the scene.

Source/target body pointers, plus the bind-mode override (section 6 —
lets a user force Mode A or B when the auto-detect heuristic's
vertex-count coincidence would misclassify; see
``core.binding.detect_bind_mode``). Later cards add offset/thickness
scale, collision margin, smoothing iterations, and pin vertex-group
references.
"""

import bpy

BIND_MODE_OVERRIDE_ITEMS = (
    ('AUTO', "Auto-Detect", "Choose Mode A or B automatically based on source/target body topology"),
    ('MODE_A', "Force Mode A", "Force same-topology (vertex-index) binding regardless of auto-detection"),
    ('MODE_B', "Force Mode B", "Force cross-topology (BVH nearest-surface) binding regardless of auto-detection"),
)


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
    bind_mode_override: bpy.props.EnumProperty(
        name="Bind Mode",
        description=(
            "Auto-detect picks Mode A when Source Body and Target Body share "
            "vertex count (else Mode B). Force an option to override that "
            "heuristic when a topology-mismatch coincidence would misclassify it"
        ),
        items=BIND_MODE_OVERRIDE_ITEMS,
        default='AUTO',
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
