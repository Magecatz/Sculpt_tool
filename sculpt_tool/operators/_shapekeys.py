"""Shared operator helper: mute the add-on's own baked output shape keys
around an evaluated-mesh read.

Enforces ARCHITECTURE.md section 2's rule "no output of this add-on may
ever be an input to it" (bind-time-freeze card, Part B) for every
evaluated-garment read, not just bind's. The garment carries this add-on's
own baked ``Fitted`` shape key -- and, after a Batch Fit, several
``Fitted_<target>`` keys, which the batch operator leaves at value 1.0 and
which therefore STACK in the evaluated mesh. Any code that reads the
garment's evaluated world positions (bind's correspondence capture; the
roadmap-R4 alignment guard's garment-vs-body distance check) must exclude
those, or it reads a garment displaced by the add-on's own prior output
rather than the authored (optionally armature-posed) garment.

``muted_addon_output`` mutes every key block whose name starts with
``storage.FITTED_SHAPE_KEY_NAME`` (so both the single-fit ``Fitted`` and
the batch ``Fitted_<target>`` keys) on each passed object, for the
duration of the ``with`` body, restoring each key's ``mute`` flag on exit
(even if the body raises). Non-``Fitted`` shape keys and all modifiers
(e.g. the garment's Armature deform) are left untouched -- only the
add-on's own bake is excluded.
"""

import contextlib

from ..core import storage


@contextlib.contextmanager
def muted_addon_output(context, *objs):
    """Temporarily mute every ``Fitted*`` shape key on ``objs`` for an
    evaluated-mesh read. See module docstring."""
    prefix = storage.FITTED_SHAPE_KEY_NAME
    muted = []
    for obj in objs:
        mesh = getattr(obj, "data", None)
        shape_keys = getattr(mesh, "shape_keys", None) if mesh is not None else None
        if shape_keys is None:
            continue
        for key_block in shape_keys.key_blocks:
            if key_block.name.startswith(prefix) and not key_block.mute:
                muted.append(key_block)

    if not muted:
        yield
        return

    for key_block in muted:
        key_block.mute = True
    context.view_layer.update()
    try:
        yield
    finally:
        for key_block in muted:
            key_block.mute = False
        context.view_layer.update()
