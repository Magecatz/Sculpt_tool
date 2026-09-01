"""Shared stage-0-placement + surface-conform sequence for Fit and Batch.

``OT_fit_garment`` (single target) and ``OT_batch_fit`` (one per target in a
Collection) ran the *same* sequence inline -- place the garment onto the
target base's rig, read its placed world positions (muting this add-on's own
bakes so a re-fit never reads its own output), run the R4 alignment guard,
then conform (``core.pipeline.conform_placed`` when placed, else
``core.pipeline.fit_once``). ARCHITECTURE.md section 8 requires Batch to be
"a thin orchestration layer ... no separate batch-specific solver logic";
once the placement path (R7/R8) landed, that sequence was duplicated between
the two operators. :func:`place_and_conform` is that sequence, extracted, so
both operators call one implementation and a fix to it reaches both.

Lives in an underscore module (like ``operators/_shapekeys.py``), not in
``operators/op_bases.py``, to avoid an import cycle: ``op_pose`` imports
``op_bases``, so ``op_bases`` cannot import ``op_pose``, which this helper
needs. It is operator-layer (it mutates the scene -- posing bones, toggling
the Armature modifier), so it stays out of ``core/`` per that layer's
pure-logic split; the caller still owns the bake, the report, and the
post-bake Armature-modifier mute (which differs between the two operators --
once per single fit vs. once after a whole batch).
"""

from . import _shapekeys, op_pose
from ..core import alignment, geometry, pipeline


class AlignmentRejected(Exception):
    """The R4 alignment guard refused the garment/target pair. Carries the
    human-readable ``reason`` for the caller to report (Fit aborts;
    Batch records it as a per-target skip and continues)."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def place_and_conform(context, garment_obj, target_body_obj, target_ctx, params,
                      garment_arm, target_arm, overrides, check_alignment, relax_ctx=None):
    """Place ``garment_obj`` onto ``target_arm`` (when both a garment rig and
    a target rig are given) and conform it to ``target_body_obj``.

    Placement runs iff ``garment_arm`` AND ``target_arm`` are both non-None;
    otherwise this is the plain (unposed) fit path. Steps:

    1. If placing: make the garment's Armature deform live and place it onto
       the target rig via the canonical bone map (``op_pose.
       place_garment_onto_rig``).
    2. If placing or ``check_alignment``: read the garment's current world
       positions with this add-on's own ``Fitted*`` bakes muted (so a re-fit
       never reads its own output).
    3. If ``check_alignment``: run the R4 guard; raise :class:`AlignmentRejected`
       (with the guard's reason) if it refuses.
    4. Conform: ``pipeline.conform_placed`` on the placed positions when
       placed (fix B2 -- offset-preserving reprojection), else
       ``pipeline.fit_once`` (frozen bind-time projection), passing
       ``relax_ctx`` through to the latter.

    Returns ``(fitted_world, placed)``. Does NOT bake, report, or re-mute the
    Armature modifier -- the caller owns those (and must mute the modifier
    after baking a placed result so the placement isn't applied twice).
    Propagates ``ValueError`` from the pipeline unchanged.
    """
    placed = garment_arm is not None and target_arm is not None
    if placed:
        # Ensure the Armature deform is live before placing (a prior
        # placement fit may have muted it -- the caller re-mutes post-bake).
        op_pose.set_armature_deform_visible(garment_obj, True)
        op_pose.place_garment_onto_rig(context, garment_arm, target_arm, overrides)

    garment_positions = None
    if placed or check_alignment:
        with _shapekeys.muted_addon_output(context, garment_obj):
            depsgraph = context.evaluated_depsgraph_get()
            garment_positions, _ = geometry.world_space_positions_and_normals(
                garment_obj, depsgraph
            )

    if check_alignment:
        report = alignment.check_against_body(
            garment_positions, target_ctx, label=f"target body '{target_body_obj.name}'"
        )
        if not report.aligned:
            raise AlignmentRejected(report.reason)

    if placed:
        fitted_world = pipeline.conform_placed(
            garment_positions, target_ctx, params, garment_obj
        )
    else:
        depsgraph = context.evaluated_depsgraph_get()
        fitted_world = pipeline.fit_once(
            garment_obj, target_body_obj, params, depsgraph,
            relax_ctx=relax_ctx, target_ctx=target_ctx,
        )
    return fitted_world, placed
