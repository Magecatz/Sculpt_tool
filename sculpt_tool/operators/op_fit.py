"""OT_fit_garment.

Runs the full fit pipeline (ARCHITECTURE.md section 3, steps 1-4) against
the active garment's declared Target Body (``obj.sculpt_tool.
target_body``): ``core.solver.project_garment`` re-evaluates the stored
binding (Mode A or B) against the target body's current geometry, then
— when ``obj.sculpt_tool.use_collision_resolution`` is enabled (the
default) — ``core.collision.resolve_collisions`` pushes any
interpenetrating vertex back out to at least ``obj.sculpt_tool.
collision_margin`` clearance, then — when ``obj.sculpt_tool.
smoothing_iterations`` is greater than zero — ``core.smoothing.relax``
runs that many pin-weighted relaxation passes to smooth noise left by
the earlier steps without shrink-wrapping the garment toward the body
(ARCHITECTURE.md section 1's anti-goal), then this operator writes the
result into a ``Fitted`` Shape Key on the garment — created fresh the
first time, overwritten in place on subsequent runs (never duplicated),
per ARCHITECTURE.md section 4's non-destructive-bake rationale. Base
mesh data is never touched.

``smoothing_iterations == 0`` is a true no-op: this operator does not
call into ``core.smoothing`` at all in that case (not even to build the
adjacency/neighbor structure or look up ``Pin_*`` vertex groups), so
output is bit-identical to the collision-resolution-only pipeline. With
collision resolution also disabled, this reproduces the original
(project + bake only) card's raw, possibly-interpenetrating output
exactly.
"""

import bpy

from ..core import collision, smoothing, solver, storage

SHAPE_KEY_NAME = "Fitted"


class SCULPTTOOL_OT_fit_garment(bpy.types.Operator):
    bl_idname = "sculpttool.fit_garment"
    bl_label = "Fit Garment"
    bl_description = (
        "Project the active garment's binding onto its Target Body and bake "
        "the result into a 'Fitted' Shape Key (overwrites any existing one; "
        "base mesh data is never modified)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != 'MESH':
            return False
        if not storage.is_bound(obj):
            return False
        settings = getattr(obj, "sculpt_tool", None)
        return bool(
            settings
            and settings.target_body
            and settings.target_body.type == 'MESH'
        )

    def execute(self, context):
        garment_obj = context.object
        settings = garment_obj.sculpt_tool
        target_body_obj = settings.target_body

        if target_body_obj is None or target_body_obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh Target Body before fitting.")
            return {'CANCELLED'}

        if target_body_obj == garment_obj:
            self.report(
                {'ERROR'}, "Target Body must be a different object from the garment."
            )
            return {'CANCELLED'}

        offset_scale = getattr(settings, "offset_scale", 1.0)

        try:
            projection = solver.project_garment(garment_obj, target_body_obj, offset_scale)
            fitted_world = projection.fitted_positions

            if getattr(settings, "use_collision_resolution", True):
                collision_margin = getattr(settings, "collision_margin", 0.01)
                fitted_world = collision.resolve_collisions(
                    fitted_world,
                    projection.anchor_positions,
                    projection.anchor_normals,
                    target_body_obj,
                    collision_margin,
                )

            smoothing_iterations = getattr(settings, "smoothing_iterations", 0)
            if smoothing_iterations > 0:
                pin_weights = smoothing.compute_pin_weights(garment_obj)
                fitted_world = smoothing.relax(
                    garment_obj,
                    fitted_world,
                    pin_weights,
                    smoothing_iterations,
                )
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        mesh = garment_obj.data
        vertex_count = len(mesh.vertices)
        if len(fitted_world) != vertex_count:
            self.report(
                {'ERROR'},
                f"Solver produced {len(fitted_world)} positions, expected "
                f"{vertex_count} (one per garment vertex).",
            )
            return {'CANCELLED'}

        # Shape key point coordinates are stored in the garment's own
        # object-local space (same space as mesh.vertices[i].co), so the
        # solver's world-space output has to be brought back into that
        # space before writing it into the Fitted key block.
        matrix_inverse = garment_obj.matrix_world.inverted_safe()
        fitted_local = [matrix_inverse @ co for co in fitted_world]

        if mesh.shape_keys is None:
            garment_obj.shape_key_add(name="Basis", from_mix=False)

        key_block = mesh.shape_keys.key_blocks.get(SHAPE_KEY_NAME)
        if key_block is None:
            key_block = garment_obj.shape_key_add(name=SHAPE_KEY_NAME, from_mix=False)

        flat_coords = [component for co in fitted_local for component in co]
        key_block.data.foreach_set("co", flat_coords)
        key_block.value = 1.0
        mesh.update()

        self.report(
            {'INFO'},
            f"Fitted '{garment_obj.name}' to '{target_body_obj.name}' "
            f"({vertex_count} vertices).",
        )
        return {'FINISHED'}


_classes = (
    SCULPTTOOL_OT_fit_garment,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
