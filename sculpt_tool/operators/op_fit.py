"""OT_fit_garment.

Runs the fit pipeline's project + bake steps (ARCHITECTURE.md section 3,
steps 1 and 4) against the active garment's declared Target Body
(``obj.sculpt_tool.target_body``): ``core.solver.project_garment``
re-evaluates the stored binding (Mode A or B) against the target body's
current geometry, then this operator writes the result into a
``Fitted`` Shape Key on the garment — created fresh the first time,
overwritten in place on subsequent runs (never duplicated), per
ARCHITECTURE.md section 4's non-destructive-bake rationale. Base mesh
data is never touched.

Collision resolution and smoothing/relaxation (ARCHITECTURE.md section
3, steps 2-3) are separate future cards — this operator only runs
project + bake, so a raw projected (possibly interpenetrating) result is
expected for now.
"""

import bpy

from ..core import solver, storage

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
            fitted_world = solver.project_garment(garment_obj, target_body_obj, offset_scale)
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
