"""OT_fit_garment.

Runs the full fit pipeline (ARCHITECTURE.md section 3) against the active
garment's declared Target Body (``obj.sculpt_tool.target_body``).

Roadmap R5 adds **stage 0**: when ``auto_pose_transfer`` is on and both a
garment rig and a target-base rig are present, the garment is first posed
onto the target base via the canonical bone map (``operators/op_pose.py``'s
``pose_garment_onto_rig``) so gross limb placement happens before the
surface fit. This is a no-op when the target base is already in the
garment's pose (identity transfer), so the co-posed happy path is
unchanged.

The surface pipeline itself — project, then (when
``obj.sculpt_tool.use_collision_resolution``) collision resolution, then
(when ``obj.sculpt_tool.smoothing_iterations > 0``) pin-weighted
smoothing, then a second collision pass if both ran — now lives in
``core.pipeline.fit_once`` (Bear PR Process card
cd0d1569-36ad-4d79-a82b-6d1115a0bcda; see that module's docstring for the
full step-by-step rationale, unchanged by the extraction). This operator
is setup (resolve/validate the garment and target body, collect
``FitParams`` from the object's settings) + ``fit_once`` + bake + report
— it contains no geometry pipeline logic of its own.

The bake: this operator writes ``fit_once``'s world-space output into a
``Fitted`` Shape Key on the garment — created fresh the first time,
overwritten in place on subsequent runs (never duplicated), per
ARCHITECTURE.md section 4's non-destructive-bake rationale. Base mesh
data is never touched.
"""

import bpy

from . import _shapekeys, op_bases, op_pose
from ..core import alignment, geometry, pipeline, storage

# The single source of truth for this name is core.storage
# (FITTED_SHAPE_KEY_NAME) -- operators/op_bind.py also needs it, to mute
# this exact key block around a bind-time evaluated-mesh read (Part B,
# bind-time-freeze card: "no output of this add-on may ever be an input
# to it"), so it isn't a private constant of this module any more.
SHAPE_KEY_NAME = storage.FITTED_SHAPE_KEY_NAME


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

        # Roadmap R5/R7/R8 -- stage 0: PLACE the garment onto the target base
        # (position + rotation + length-scale) via the canonical bone map,
        # when both a garment rig and the target base rig are present. A
        # no-op when the two skeletons already coincide, so a co-posed,
        # same-proportion pair is unchanged. When placement runs, the surface
        # fit conforms the PLACED garment (see below) instead of re-projecting
        # the frozen bind-time correspondence.
        garment_arm = op_bases.garment_rig(garment_obj, settings)
        target_arm = getattr(settings, "target_base_armature", None)
        placement_active = (
            getattr(settings, "auto_pose_transfer", True)
            and garment_arm is not None
            and target_arm is not None
        )
        if placement_active:
            # Ensure the Armature deform is live before placing (a prior
            # placement fit may have muted it -- see the post-bake step).
            op_pose.set_armature_deform_visible(garment_obj, True)
            overrides = [
                (o.source_bone, o.target_bone)
                for o in getattr(settings, "bone_map_overrides", ())
                if o.source_bone
            ]
            op_pose.place_garment_onto_rig(context, garment_arm, target_arm, overrides)

        params = pipeline.FitParams(
            offset_scale=getattr(settings, "offset_scale", 1.0),
            use_collision_resolution=getattr(settings, "use_collision_resolution", True),
            collision_margin=getattr(settings, "collision_margin", 0.01),
            smoothing_iterations=getattr(settings, "smoothing_iterations", 0),
        )

        depsgraph = context.evaluated_depsgraph_get()

        # Build the target context once (Roadmap R4) and reuse it for the
        # alignment guard and the fit.
        try:
            target_ctx = geometry.TargetContext.build(target_body_obj, depsgraph)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        # The garment's current world positions (placed / posed), with this
        # add-on's own Fitted* bakes muted so a re-fit doesn't read its own
        # output. Used for the alignment guard and -- in the placement path
        # -- as the very mesh the surface fit conforms.
        with _shapekeys.muted_addon_output(context, garment_obj):
            depsgraph = context.evaluated_depsgraph_get()
            garment_positions, _ = geometry.world_space_positions_and_normals(
                garment_obj, depsgraph
            )

        if not getattr(settings, "skip_alignment_check", False):
            report = alignment.check_against_body(
                garment_positions, target_ctx, label=f"target body '{target_body_obj.name}'"
            )
            if not report.aligned:
                self.report({'ERROR'}, report.reason)
                return {'CANCELLED'}

        try:
            if placement_active:
                # Conform the already-placed garment (collision/smooth on the
                # placed mesh), not the frozen bind-time projection.
                fitted_world = pipeline.conform_placed(
                    garment_positions, target_ctx, params, garment_obj
                )
            else:
                fitted_world = pipeline.fit_once(
                    garment_obj, target_body_obj, params, depsgraph, target_ctx=target_ctx
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
        #
        # NEITHER step below is vectorized with NumPy, despite Bear PR
        # Process card 1f564161-82f9-4d5d-bd63-665d98790e8a's own "honest
        # scope" calling this an "easy win". The world->local conversion
        # is the same matrix @ Vector reduction core/geometry.py's
        # world_space_positions_and_normals docstring already found does
        # not reproduce mathutils's float32 rounding bit-for-bit via a
        # from-scratch NumPy reimplementation -- checked directly against
        # THIS garment's own matrix_world/fitted_world on the real
        # Test_Items bodysuit (2,087 vertices): 1,243/2,087 vertices (60%)
        # diverged by 1 ULP. The flatten-for-foreach_set step (pure data
        # reshape, no arithmetic, no bit-identity risk at all) was still
        # tried on its own -- build a NumPy array from fitted_local and
        # reshape/flatten it instead of the nested list comprehension --
        # and measured, at a 33k-vertex scale (tests/perf.py's tube), as a
        # wash-to-slightly-slower (~9.1ms vs ~5.6ms per call for 20 calls),
        # the same NumPy/mathutils.Vector boundary-crossing overhead
        # core/smoothing.py's _laplacian_step docstring describes. See the
        # card's PR for the full numbers.
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

        # The placement is now baked into the Fitted key; hide the garment's
        # live Armature modifier so it doesn't deform that bake a second time
        # (roadmap R8). Re-enabled automatically on the next placement fit.
        if placement_active:
            op_pose.set_armature_deform_visible(garment_obj, False)
            context.view_layer.update()

        self.report(
            {'INFO'},
            f"Fitted '{garment_obj.name}' to '{target_body_obj.name}' "
            f"({vertex_count} vertices){' (placed via armature)' if placement_active else ''}.",
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
