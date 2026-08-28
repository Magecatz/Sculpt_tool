"""Operator package for Sculpt Tool.

Registers each operator submodule per ARCHITECTURE.md section 5. Only
op_bind.py (OT_bind_garment) has real logic so far; op_fit.py
(OT_fit_garment), op_batch.py (OT_batch_fit), and op_pin_groups.py (pin
vertex-group helpers) are still empty placeholders and are not
registered here yet — later cards add their register()/unregister() to
``_modules`` below.
"""

from . import op_bind

_modules = (
    op_bind,
)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
