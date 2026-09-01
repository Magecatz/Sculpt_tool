"""Operator package for Sculpt Tool.

Registers each operator submodule per ARCHITECTURE.md section 5.
op_bind.py (OT_bind_garment), op_fit.py (OT_fit_garment),
op_pin_groups.py (pin vertex-group helpers: add/remove/assign/select),
op_batch.py (OT_batch_fit, added by the Batch/automated-fitting card),
op_bases.py (OT_detect_rigs + bone-map ops, roadmap R1/R2), and
op_pose.py (OT_pose_to_target, the roadmap-R3 pose-transfer stage) all
have real logic and are registered below.
"""

from . import op_bases
from . import op_batch
from . import op_bind
from . import op_fit
from . import op_pin_groups
from . import op_pose

_modules = (
    op_bind,
    op_fit,
    op_pin_groups,
    op_batch,
    op_bases,
    op_pose,
)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
