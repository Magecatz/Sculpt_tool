"""OT_conform -- the rebuilt surface-conform operator (Direction B).

Replaces the removed OT_fit_garment. The pipeline is deliberately small
(RESTART_SCOPE.md section 5):

  1. PLACE the garment onto the target base via the placement spine
     (``op_pose.place_garment_onto_rig`` -- position + rotation + scale by the
     canonical bone map), when both a garment rig and a target-base rig exist.
  2. STANDOFF -- how far off its own body each garment vertex was authored to
     sit. Measured from the **source base** the garment was designed for
     (``settings.source_body``) when the user has supplied it; otherwise
     approximated from the placed garment against the target
     (``core.conform.placed_standoff``, the source-free fallback).
  3. PROJECT each placed vertex onto the nearest target surface and reapply
     that standoff (``core.conform.project_to_target``). No collision, no
     smoothing -- those inflated fitted pieces in the old pipeline.
  4. BAKE the result into a ``Fitted`` Shape Key (world -> garment-local),
     then hide the live Armature modifier so the already-baked placement is
     not applied a second time.

Setup + core + bake + report; the geometry lives in ``core.conform`` /
``core.geometry`` (pure logic), this operator owns the scene interaction.
"""

import bpy

from . import op_bases, op_pose
from ..core import conform, geometry, storage

SHAPE_KEY_NAME = storage.FITTED_SHAPE_KEY_NAME


class ConformError(Exception):
    """A garment can't be conformed as set up (no/invalid Target Body, an
    unusable Source Base, a pipeline length mismatch). Carries a
    human-readable reason; the single operator reports it and cancels, Batch
    records it as a per-garment skip and continues."""


def run_conform(context, garment_obj):
    """Place + conform + bake one garment onto its Target Body (the full
    Direction-B pipeline: place -> standoff -> project -> bake). Returns a
    short info string on success. Raises :class:`ConformError` for a bad
    setup and ``ValueError`` for a pipeline failure.

    This is the single source of the conform sequence -- both
    ``OT_conform`` (active object) and ``OT_batch_conform`` (each selected
    garment) call it, so Batch adds no pipeline logic of its own
    (ARCHITECTURE.md section 8)."""
    settings = garment_obj.sculpt_tool
    target_body_obj = getattr(settings, "target_body", None)
    if target_body_obj is None or target_body_obj.type != 'MESH':
        raise ConformError("no mesh Target Body set")
    if target_body_obj == garment_obj:
        raise ConformError("Target Body must be a different object from the garment")

    mesh = garment_obj.data
    vertex_count = len(mesh.vertices)

    # Authored (rest) world positions from basis coords, so a previous Fitted
    # key never feeds back in as input.
    rest_world = [garment_obj.matrix_world @ v.co for v in mesh.vertices]

    depsgraph = context.evaluated_depsgraph_get()
    target_ctx = geometry.TargetContext.build(target_body_obj, depsgraph)

    # Stage 1: placement (only when both skeletons are present).
    garment_arm = (
        op_bases.garment_rig(garment_obj, settings)
        if getattr(settings, "auto_pose_transfer", True)
        else None
    )
    target_arm = getattr(settings, "target_base_armature", None)
    placed_via_armature = garment_arm is not None and target_arm is not None

    if mesh.shape_keys is not None:
        existing = mesh.shape_keys.key_blocks.get(SHAPE_KEY_NAME)
        if existing is not None:
            existing.value = 0.0

    if placed_via_armature:
        op_pose.set_armature_deform_visible(garment_obj, True)
        overrides = [
            (o.source_bone, o.target_bone)
            for o in getattr(settings, "bone_map_overrides", ())
            if o.source_bone
        ]
        op_pose.place_garment_onto_rig(context, garment_arm, target_arm, overrides)
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        placed_world, _ = geometry.world_space_positions_and_normals(garment_obj, depsgraph)
    else:
        placed_world = list(rest_world)

    # Stage 2: standoff -- source-measured when a source base is set, else the
    # source-free placed approximation.
    source_body_obj = getattr(settings, "source_body", None)
    used_source = source_body_obj is not None and source_body_obj.type == 'MESH'
    if used_source:
        source_ctx = geometry.TargetContext.build(source_body_obj, depsgraph)
        standoff = conform.authored_standoff(rest_world, source_ctx)
    else:
        standoff = conform.placed_standoff(placed_world, target_ctx)

    # Stage 3: project onto the target surface, loose-vertex ramp made
    # spatially coherent over the garment's own edge adjacency.
    neighbors = conform.build_vertex_neighbors(
        [(e.vertices[0], e.vertices[1]) for e in mesh.edges], vertex_count
    )
    fitted_world = conform.project_to_target(
        placed_world, standoff, target_ctx, neighbors=neighbors
    )
    if len(fitted_world) != vertex_count:
        raise ValueError(
            f"Conform produced {len(fitted_world)} positions, expected {vertex_count}."
        )

    # Stage 4: bake into the Fitted Shape Key (world -> garment-local).
    matrix_inverse = garment_obj.matrix_world.inverted_safe()
    fitted_local = [matrix_inverse @ co for co in fitted_world]
    if mesh.shape_keys is None:
        garment_obj.shape_key_add(name="Basis", from_mix=False)
    key_block = mesh.shape_keys.key_blocks.get(SHAPE_KEY_NAME)
    if key_block is None:
        key_block = garment_obj.shape_key_add(name=SHAPE_KEY_NAME, from_mix=False)
    key_block.data.foreach_set("co", [c for co in fitted_local for c in co])
    key_block.value = 1.0
    mesh.update()

    if placed_via_armature:
        op_pose.set_armature_deform_visible(garment_obj, False)
        context.view_layer.update()

    return (
        f"{vertex_count} vertices, "
        f"{'source-measured' if used_source else 'source-free'} standoff"
        f"{', placed via armature' if placed_via_armature else ''}"
    )


class SCULPTTOOL_OT_conform(bpy.types.Operator):
    bl_idname = "sculpttool.conform"
    bl_label = "Conform to Target"
    bl_description = (
        "Place the active garment onto its Target Body (position + scale + "
        "pose via the bone map), then conform its surface to the target and "
        "bake the result into a 'Fitted' Shape Key. Uses the Source Base to "
        "preserve the garment's authored standoff when one is set; otherwise "
        "approximates it. Base mesh data is never modified"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != 'MESH':
            return False
        settings = getattr(obj, "sculpt_tool", None)
        return bool(settings and settings.target_body and settings.target_body.type == 'MESH')

    def execute(self, context):
        garment_obj = context.object
        try:
            info = run_conform(context, garment_obj)
        except (ConformError, ValueError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Conformed '{garment_obj.name}' to "
            f"'{garment_obj.sculpt_tool.target_body.name}' ({info}).",
        )
        return {'FINISHED'}


class SCULPTTOOL_OT_batch_conform(bpy.types.Operator):
    bl_idname = "sculpttool.batch_conform"
    bl_label = "Conform Selected"
    bl_description = (
        "Conform every SELECTED mesh garment onto its own Target Body in one "
        "pass (fit a whole multi-piece outfit at once). Each garment uses its "
        "own settings; one that isn't set up (no Target Body, unusable Source "
        "Base) is skipped with a warning rather than aborting the rest"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):
        garments = [o for o in context.selected_objects if o.type == 'MESH'
                    and getattr(o, "sculpt_tool", None)]
        done, skipped = 0, []
        for garment_obj in garments:
            try:
                run_conform(context, garment_obj)
                done += 1
            except (ConformError, ValueError) as exc:
                skipped.append(f"{garment_obj.name} ({exc})")
        if done == 0 and skipped:
            self.report({'ERROR'}, "Batch Conform: nothing conformed. " + "; ".join(skipped))
            return {'CANCELLED'}
        msg = f"Batch Conform: {done} garment(s) conformed"
        if skipped:
            msg += f"; {len(skipped)} skipped -- " + "; ".join(skipped)
        self.report({'WARNING'} if skipped else {'INFO'}, msg + ".")
        return {'FINISHED'}


_classes = (SCULPTTOOL_OT_conform, SCULPTTOOL_OT_batch_conform)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
