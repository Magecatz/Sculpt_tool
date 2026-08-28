"""Sculpt Tool — Blender add-on entry point.

Fits a garment mesh onto a target body mesh via a custom BVH-based
bind/solve pipeline. See ARCHITECTURE.md at the repo root for the full
design.

This module only wires up add-on registration (bl_info, register /
unregister). Solver logic lives in core/, operators in operators/, per-
object settings in properties.py, and the N-sidebar UI in ui_panel.py.
"""

bl_info = {
    "name": "Sculpt Tool",
    "author": "Sculpt Tool Project",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Sculpt Tool",
    "description": (
        "Fits a garment mesh onto a target body mesh while preserving "
        "the garment's own volume and silhouette."
    ),
    "category": "Object",
}

import bpy  # noqa: E402

from . import properties  # noqa: E402
from . import operators  # noqa: E402
from . import ui_panel  # noqa: E402

# Modules that expose register()/unregister(), applied in this order and
# torn down in reverse. core/ has no registerable content (pure logic,
# no bpy.types classes) so it is never listed here. properties.py must
# come first (operators/ui_panel read obj.sculpt_tool), operators/
# before ui_panel (the panel references the bind operator's bl_idname).
_modules = (
    properties,
    operators,
    ui_panel,
)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()


if __name__ == "__main__":
    register()
