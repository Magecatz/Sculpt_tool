"""OT_bind_garment.

Computes and stores a binding between the active garment object and its
declared source body (the ``obj.sculpt_tool.source_body`` pointer from
properties.py), per ARCHITECTURE.md sections 2, 4, and 6.

Mode is chosen by ``obj.sculpt_tool.bind_mode_override``: ``'AUTO'`` (the
default) delegates to ``core.binding.detect_bind_mode`` — Mode A
(same-topology) when Source Body and the declared Target Body share a
vertex count, else Mode B (cross-topology, BVH nearest-surface
projection) — while ``'MODE_A'``/``'MODE_B'`` force that choice
regardless of what auto-detection would have picked, per section 6's
escape hatch for topology-mismatch coincidences. As of the bind-time-
freeze card (Part C), ``detect_bind_mode`` raises ``ValueError`` instead
of defaulting to Mode A when no Target Body is set yet — caught here and
reported as a normal bind error, same as any other.

``core.binding.bind_mode_a``/``bind_mode_b`` take a resolved depsgraph
rather than resolving one internally (Bear PR Process card
cd0d1569-36ad-4d79-a82b-6d1115a0bcda — see ``core/geometry.py``'s module
docstring), so this operator resolves it once via ``context.
evaluated_depsgraph_get()`` and passes it down.

Part B (bind-time-freeze card): ARCHITECTURE.md section 2's rule "no
output of this add-on may ever be an input to it" is enforced here, not
in ``core/``, because it needs an explicit ``context.view_layer.update()``
to make the depsgraph catch up with a shape-key mute/unmute mid-``execute()``
— a Blender-context concern ``core/`` deliberately stays free of (see
``core/geometry.py``'s docstring). See :func:`_bind_time_evaluation`.
"""

import contextlib

import bpy

from ..core import alignment, binding, geometry, storage


@contextlib.contextmanager
def _bind_time_evaluation(context, *objs):
    """Temporarily mute the add-on's own ``Fitted`` shape key (if present
    and unmuted) on every object in ``objs``, for the duration of the
    bind-time evaluated-mesh read.

    Enforces ARCHITECTURE.md section 2's rule that no output of this
    add-on may ever be read back as an input to it. The concrete,
    empirically-verified failure this closes (card 1f8e8594): re-binding
    a garment after fitting it read the garment's own evaluated mesh,
    which includes the ``Fitted`` shape key's contribution at its current
    (post-fit) value — so the "original, authored" garment vertex
    positions ``core.binding.bind_mode_a``/``bind_mode_b`` compute from
    were quietly this add-on's own prior output, not what the garment
    actually looked like before Bind. The same failure mode applies, less
    commonly, to a source body that was itself fit as some other
    garment's target — hence muting on every object passed in, not just
    the garment.

    Garment-side MODIFIERS and every other shape key are left exactly as
    they are; only this add-on's own bake is excluded. Restores every
    muted key block's ``mute`` flag on exit, even if the ``with`` body
    raises.
    """
    key_blocks = []
    for obj in objs:
        mesh = getattr(obj, "data", None)
        shape_keys = getattr(mesh, "shape_keys", None) if mesh is not None else None
        if shape_keys is None:
            continue
        key_block = shape_keys.key_blocks.get(storage.FITTED_SHAPE_KEY_NAME)
        if key_block is not None and not key_block.mute:
            key_blocks.append(key_block)

    if not key_blocks:
        yield
        return

    for key_block in key_blocks:
        key_block.mute = True
    context.view_layer.update()
    try:
        yield
    finally:
        for key_block in key_blocks:
            key_block.mute = False
        context.view_layer.update()


class SCULPTTOOL_OT_bind_garment(bpy.types.Operator):
    bl_idname = "sculpttool.bind_garment"
    bl_label = "Bind Garment"
    bl_description = (
        "Bind the active garment to its Source Body (Mode A: same-topology, "
        "or Mode B: cross-topology BVH projection — auto-detected or forced "
        "via Bind Mode). Overwrites any previous binding on this garment"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != 'MESH':
            return False
        settings = getattr(obj, "sculpt_tool", None)
        return bool(
            settings
            and settings.source_body
            and settings.source_body.type == 'MESH'
        )

    def execute(self, context):
        garment_obj = context.object
        settings = garment_obj.sculpt_tool
        source_body_obj = settings.source_body

        if source_body_obj is None or source_body_obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh Source Body before binding.")
            return {'CANCELLED'}

        if source_body_obj == garment_obj:
            self.report(
                {'ERROR'}, "Source Body must be a different object from the garment."
            )
            return {'CANCELLED'}

        if len(garment_obj.data.vertices) == 0:
            self.report({'ERROR'}, "Garment mesh has no vertices.")
            return {'CANCELLED'}

        if len(source_body_obj.data.vertices) == 0:
            self.report({'ERROR'}, "Source Body mesh has no vertices.")
            return {'CANCELLED'}

        override = getattr(settings, "bind_mode_override", 'AUTO')
        if override == 'MODE_A':
            mode = binding.MODE_A
        elif override == 'MODE_B':
            mode = binding.MODE_B
        else:
            try:
                mode = binding.detect_bind_mode(source_body_obj, settings.target_body)
            except ValueError as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}

        # Part B: mute this add-on's own 'Fitted' shape key (garment and
        # source body alike) for the duration of the evaluated-mesh reads
        # below, so a prior Fit's baked output is never read back in as
        # though it were the original authored mesh -- see
        # _bind_time_evaluation's docstring.
        with _bind_time_evaluation(context, garment_obj, source_body_obj):
            depsgraph = context.evaluated_depsgraph_get()

            # Roadmap R4: refuse a garment grossly out of pose/position for
            # its SOURCE body at bind time -- subsumes ARCHITECTURE.md
            # section 7 row 2 (Mode B silently produces a garbage binding if
            # the garment isn't reasonably positioned near its source body).
            if not getattr(settings, "skip_alignment_check", False):
                try:
                    source_ctx = geometry.TargetContext.build(source_body_obj, depsgraph)
                    garment_positions, _ = geometry.world_space_positions_and_normals(
                        garment_obj, depsgraph
                    )
                    report = alignment.check_against_body(
                        garment_positions, source_ctx,
                        label=f"source body '{source_body_obj.name}'",
                    )
                except ValueError:
                    # An empty/degenerate source body is reported by the
                    # bind logic below with its own specific error -- don't
                    # pre-empt that with a generic alignment failure.
                    report = alignment.AlignmentReport(aligned=True)
                if not report.aligned:
                    self.report({'ERROR'}, report.reason)
                    return {'CANCELLED'}

            if mode == binding.MODE_A:
                result = binding.bind_mode_a(garment_obj, source_body_obj, depsgraph)
                storage.write_mode_a_binding(garment_obj, source_body_obj, result)
                vertex_count = len(result.body_vertex_index)
            else:
                result = binding.bind_mode_b(garment_obj, source_body_obj, depsgraph)
                storage.write_mode_b_binding(garment_obj, source_body_obj, result)
                vertex_count = len(result.triangle_index)

        self.report(
            {'INFO'},
            f"Bound '{garment_obj.name}' to '{source_body_obj.name}' "
            f"({vertex_count} vertices, Mode {mode}).",
        )
        return {'FINISHED'}


_classes = (
    SCULPTTOOL_OT_bind_garment,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
