"""OT_batch_fit.

Runs the same project -> collision -> smooth -> bake pipeline as
``OT_fit_garment`` (``operators/op_fit.py``) once per object in a target
Collection (``obj.sculpt_tool.batch_target_collection``), per
ARCHITECTURE.md section 8: "a thin orchestration layer over the same
``core/`` modules the single-target ``OT_fit_garment`` uses -- no
separate batch-specific solver logic". This operator therefore contains
NO pipeline math of its own -- every step below is either bookkeeping
(resolving the target list, building a per-target Shape Key name,
progress reporting) or a direct call into ``core.pipeline.fit_once``,
exactly as ``operators/op_fit.py`` calls it for a single target.

Output naming: rather than overwriting the single-Fit ``Fitted`` Shape
Key (``core.storage.FITTED_SHAPE_KEY_NAME``) once per target -- which
would leave only the LAST target's result on the garment -- each target
gets its own uniquely-named key, ``Fitted_<target_object_name>`` (see
:func:`_batch_shape_key_name`), so a Collection of N targets produces N
distinguishable Shape Keys the user can inspect/export individually
after the run. Re-running Batch Fit against the same Collection
overwrites each target's own key in place (same lookup-by-name-first
pattern as ``operators/op_fit.py``'s bake step), never duplicating it.

Structural performance invariants this operator is responsible for
(ARCHITECTURE.md section 8, and the acceptance criteria of the Bear PR
Process card that added this file -- NumPy vectorization was
investigated and rejected for this pipeline, see
``core/geometry.py``/``core/smoothing.py`` docstrings and DECISIONS.md
Sec 2, so the performance story here is entirely about NOT doing
redundant work rather than about bulk-array math):

- The garment's own per-run invariants -- adjacency, original edge
  lengths, and ``Pin_*`` weights, none of which depend on which target
  body is being fit against -- are built exactly ONCE per batch run
  (``core.smoothing.RelaxContext.build``, called here before the loop
  starts) and passed into every ``fit_once`` call as ``relax_ctx``,
  instead of once per target. ``core.pipeline.fit_once`` already
  supports this via its optional ``relax_ctx`` parameter (added
  alongside ``fit_once`` itself specifically for this future card -- see
  that module's docstring). Only built at all when
  ``params.smoothing_iterations > 0``, matching ``fit_once``'s own
  zero-smoothing guarantee of not touching ``RelaxContext`` when
  smoothing is off.
- The garment's world-to-local matrix inverse (``matrix_world.
  inverted_safe()``, needed to bring each target's world-space fitted
  result back into the garment's local space for the Shape Key bake) is
  likewise a per-garment invariant -- it does not depend on the target
  body either -- and is computed exactly once, before the loop, rather
  than once per target as a naive per-target copy of
  ``operators/op_fit.py``'s bake step would.
- Each TARGET's evaluated mesh, triangulation, and BVH, by contrast,
  genuinely IS per-target work (a different target body is different
  geometry) and cannot be hoisted the same way -- ``core.pipeline.
  fit_once`` builds one fresh ``core.geometry.TargetContext`` per call
  (see that module's docstring), so calling it once per target here
  already gives exactly-once-per-target construction with no extra work
  needed in this operator. ``tests/test_batch.py`` verifies this
  structurally (a ``TargetContext.build`` call-count spy across a whole
  batch run), not just by inspection.

Per-target failure isolation: a ``ValueError`` from ``core.pipeline.
fit_once`` (garment not bound, a target body with no valid binding
correspondence -- e.g. a cross-topology target against a Mode-A-only
binding, a target with no triangulatable faces when collision resolution
needs them, a solver output length mismatch) is caught PER TARGET and
reported as a warning; the loop continues to the next target rather than
aborting the whole batch run, per this card's acceptance criteria. A
batch run where every target fails still reports an overall error and
returns ``{'CANCELLED'}``; a run with at least one success returns
``{'FINISHED'}`` even if some targets were skipped, so a partially
successful batch's output is not thrown away.

No cloth-simulation or other nondeterministic refinement pass is
introduced by this operator, and none exists anywhere in ``core/`` for
it to opt into (ARCHITECTURE.md section 1 / row 9 of the risk table:
cloth sim is explicitly out of the default deterministic pipeline,
precisely because unattended batch use is one of the reasons it's kept
opt-in-only). This operator's ``fit_once`` calls are therefore
deterministic by construction, not by an extra guard here.
"""

import bpy

from . import _shapekeys, op_bases, op_pose
from ..core import alignment, geometry, pipeline, rig, smoothing, storage

# Shape key name prefix for a batch target's own output -- see module
# docstring's "Output naming" section. Built from storage.
# FITTED_SHAPE_KEY_NAME (not a separate literal) so a future rename of
# the single-Fit key name stays consistent with this one.
_BATCH_KEY_PREFIX = storage.FITTED_SHAPE_KEY_NAME + "_"

# Blender caps most ID/RNA string names (including a ShapeKey's own
# ``name``) at 63 usable characters (``MAX_NAME`` internally is 66, with
# a few bytes reserved) -- silently truncating past that raises deep
# inside bpy's RNA layer rather than failing cleanly. Truncating here
# defensively converts an unreasonably long target-object name into a
# shorter Shape Key name instead of an operator crash; two DIFFERENT
# target names that happen to share the same first 63-ish characters of
# "Fitted_<name>" is an accepted, documented edge case this does not try
# to disambiguate further (not worth the added complexity for a name
# collision this unlikely).
_MAX_SHAPE_KEY_NAME_LENGTH = 63


def _batch_shape_key_name(target_name):
    """The uniquely-named Shape Key a given target body's result bakes
    into -- see module docstring's "Output naming" section."""
    return (_BATCH_KEY_PREFIX + target_name)[:_MAX_SHAPE_KEY_NAME_LENGTH]


def _resolve_targets(collection, garment_obj):
    """Mesh objects in ``collection`` (including nested child Collections,
    via ``all_objects``, so a user organizing target bodies into
    sub-collections still gets them all) that are actual fit candidates:
    ``MESH`` type, and not the garment itself (guards against a garment
    accidentally left inside its own target Collection). Non-mesh members
    (lights, empties, cameras) are silently skipped -- not every object in
    a scene Collection is necessarily a body to fit against, and that is
    not itself an error worth surfacing per-target.

    Order matches ``collection.all_objects``'s own iteration order;
    duplicates (an object reachable via more than one nested Collection
    path) are removed while preserving first-seen order, so a given
    target body is never fit -- and never has its Shape Key double-baked
    for the same run -- more than once.
    """
    seen = set()
    targets = []
    for obj in collection.all_objects:
        if obj.type != 'MESH' or obj == garment_obj:
            continue
        if obj.name in seen:
            continue
        seen.add(obj.name)
        targets.append(obj)
    return targets


class SCULPTTOOL_OT_batch_fit(bpy.types.Operator):
    bl_idname = "sculpttool.batch_fit"
    bl_label = "Run Batch Fit"
    bl_description = (
        "Run Fit once per mesh object in Target Collection, baking each "
        "target's result into its own 'Fitted_<target name>' Shape Key on "
        "the garment. A target with no valid binding correspondence is "
        "skipped with a warning; the rest of the batch still runs"
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
        return bool(settings and settings.batch_target_collection)

    def execute(self, context):
        garment_obj = context.object
        settings = garment_obj.sculpt_tool
        collection = settings.batch_target_collection

        if collection is None:
            self.report({'ERROR'}, "Select a Target Collection before running Batch Fit.")
            return {'CANCELLED'}

        targets = _resolve_targets(collection, garment_obj)
        if not targets:
            self.report(
                {'ERROR'},
                f"Target Collection '{collection.name}' has no mesh objects to fit "
                "(besides the garment itself).",
            )
            return {'CANCELLED'}

        params = pipeline.FitParams(
            offset_scale=getattr(settings, "offset_scale", 1.0),
            use_collision_resolution=getattr(settings, "use_collision_resolution", True),
            collision_margin=getattr(settings, "collision_margin", 0.01),
            smoothing_iterations=getattr(settings, "smoothing_iterations", 0),
        )

        # Per-garment invariants, hoisted OUT of the per-target loop below
        # -- see module docstring's "Structural performance invariants"
        # section. Neither depends on which target body a given fit_once
        # call runs against.
        relax_ctx = None
        if params.smoothing_iterations > 0:
            relax_ctx = smoothing.RelaxContext.build(garment_obj)
        matrix_inverse = garment_obj.matrix_world.inverted_safe()

        mesh = garment_obj.data
        vertex_count = len(mesh.vertices)
        if mesh.shape_keys is None:
            garment_obj.shape_key_add(name="Basis", from_mix=False)

        depsgraph = context.evaluated_depsgraph_get()

        # Roadmap R4 alignment guard. The garment's world positions are a
        # per-garment invariant (constant across the batch's targets), so
        # they're computed once here, not once per target -- same hoisting
        # rationale as relax_ctx / matrix_inverse above.
        # Roadmap R5 -- pose transfer per target base. Each target body in
        # the collection has its own rig; the garment is posed onto that
        # rig's pose before its fit (reset to rest first, so targets don't
        # accumulate). A no-op for a target base at the garment's pose.
        auto_pose = getattr(settings, "auto_pose_transfer", True)
        garment_arm = op_bases.garment_rig(garment_obj, settings) if auto_pose else None
        pose_overrides = [
            (o.source_bone, o.target_bone)
            for o in getattr(settings, "bone_map_overrides", ())
            if o.source_bone
        ]

        check_alignment = not getattr(settings, "skip_alignment_check", False)

        successes = []
        failures = []

        wm = context.window_manager
        wm.progress_begin(0, len(targets))
        try:
            for index, target_obj in enumerate(targets):
                wm.progress_update(index)

                try:
                    target_ctx = geometry.TargetContext.build(target_obj, depsgraph)
                except ValueError as exc:
                    failures.append((target_obj.name, str(exc)))
                    self.report(
                        {'WARNING'}, f"Batch Fit: skipped '{target_obj.name}' -- {exc}"
                    )
                    continue

                # Stage 0: pose the garment onto THIS target base's rig.
                if garment_arm is not None:
                    target_rig = rig.deforming_armature(target_obj)
                    if target_rig is not None:
                        op_pose.pose_garment_onto_rig(
                            context, garment_arm, target_rig, pose_overrides
                        )

                if check_alignment:
                    # Read the (now-posed) garment, muted so a re-run's own
                    # stacked Fitted_<target> bakes aren't read back in.
                    with _shapekeys.muted_addon_output(context, garment_obj):
                        align_depsgraph = context.evaluated_depsgraph_get()
                        garment_positions, _ = geometry.world_space_positions_and_normals(
                            garment_obj, align_depsgraph
                        )
                    report = alignment.check_against_body(
                        garment_positions, target_ctx,
                        label=f"target body '{target_obj.name}'",
                    )
                    if not report.aligned:
                        failures.append((target_obj.name, report.reason))
                        self.report(
                            {'WARNING'},
                            f"Batch Fit: skipped '{target_obj.name}' -- {report.reason}",
                        )
                        continue

                try:
                    fitted_world = pipeline.fit_once(
                        garment_obj, target_obj, params, depsgraph,
                        relax_ctx=relax_ctx, target_ctx=target_ctx,
                    )
                except ValueError as exc:
                    failures.append((target_obj.name, str(exc)))
                    self.report(
                        {'WARNING'}, f"Batch Fit: skipped '{target_obj.name}' -- {exc}"
                    )
                    continue

                if len(fitted_world) != vertex_count:
                    message = (
                        f"Solver produced {len(fitted_world)} positions, expected "
                        f"{vertex_count} (one per garment vertex)."
                    )
                    failures.append((target_obj.name, message))
                    self.report(
                        {'WARNING'}, f"Batch Fit: skipped '{target_obj.name}' -- {message}"
                    )
                    continue

                # Same world -> garment-local conversion as
                # operators/op_fit.py's bake step (see that module's
                # docstring for why this stays un-vectorized).
                fitted_local = [matrix_inverse @ co for co in fitted_world]

                key_name = _batch_shape_key_name(target_obj.name)
                key_block = mesh.shape_keys.key_blocks.get(key_name)
                if key_block is None:
                    key_block = garment_obj.shape_key_add(name=key_name, from_mix=False)

                flat_coords = [component for co in fitted_local for component in co]
                key_block.data.foreach_set("co", flat_coords)
                key_block.value = 1.0

                successes.append(target_obj.name)
                self.report(
                    {'INFO'},
                    f"Batch Fit: fitted '{garment_obj.name}' to '{target_obj.name}' "
                    f"({index + 1}/{len(targets)}).",
                )

            wm.progress_update(len(targets))
        finally:
            wm.progress_end()

        mesh.update()

        summary = (
            f"Batch Fit on '{garment_obj.name}': {len(successes)}/{len(targets)} "
            "targets fitted successfully."
        )
        if failures:
            failed_names = ", ".join(name for name, _ in failures)
            summary += f" Skipped: {failed_names}."

        if not successes:
            self.report({'ERROR'}, summary)
            return {'CANCELLED'}

        self.report({'WARNING'} if failures else {'INFO'}, summary)
        return {'FINISHED'}


_classes = (
    SCULPTTOOL_OT_batch_fit,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
