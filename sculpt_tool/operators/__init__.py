"""Operator package for Sculpt Tool.

Registers each operator submodule per ARCHITECTURE.md section 5.
op_bind.py (OT_bind_garment), op_fit.py (OT_fit_garment), and
op_pin_groups.py (pin vertex-group helpers: add/remove/assign/select)
have real logic; op_batch.py (OT_batch_fit) is still an empty
placeholder and is not registered here yet — a later card adds its
register()/unregister() to ``_modules`` below.
"""

from . import op_bind
from . import op_fit
from . import op_pin_groups

_modules = (
    op_bind,
    op_fit,
    op_pin_groups,
)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
