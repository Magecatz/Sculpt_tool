"""Operator package for Sculpt Tool.

Registers each operator submodule per ARCHITECTURE.md section 5.

Conform-rebuild restart: the target-anchored conform operators
(``op_bind`` / ``op_fit`` / ``op_batch``) were removed with the rest of the
surface-conform stage (see RESTART_SCOPE.md). What remains is the placement
spine and its supporting UI helpers:

- ``op_bases.py`` -- OT_detect_rigs + bone-map ops (roadmap R1/R2).
- ``op_pose.py`` -- OT_pose_to_target, the placement stage (position +
  rotation + scale via the canonical bone map).
- ``op_pin_groups.py`` -- ``Pin_*`` vertex-group helpers (add/remove/assign/
  select), retained as anchor authoring for the elastic conform to come.
"""

from . import op_bases
from . import op_pin_groups
from . import op_pose

_modules = (
    op_pin_groups,
    op_bases,
    op_pose,
)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
