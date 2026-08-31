"""``fit_once`` -- the full per-target fit pipeline as one reusable function.

Per ARCHITECTURE.md section 3 (project -> collision -> smooth) and
section 8 (Batch is "a thin orchestration layer over the same ``core/``
modules the single-target ``OT_fit_garment`` uses -- no separate
batch-specific solver logic"). Before this card, that pipeline sequence
only existed inline inside ``operators/op_fit.py``'s ``execute()``, so a
future Batch operator could only honor section 8's "no duplicate pipeline
logic" instruction by copy-pasting it. ``fit_once`` is that sequence,
extracted: ``operators/op_fit.py`` becomes setup + ``fit_once`` + bake +
report, and a future ``operators/op_batch.py`` can call ``fit_once`` once
per target body in its own loop with no duplicated logic (Bear PR Process
card cd0d1569-36ad-4d79-a82b-6d1115a0bcda).

``fit_once`` takes a ``depsgraph`` parameter rather than resolving
Blender's current evaluated depsgraph itself, matching every other
``core/`` module's convention after this card (see ``core/geometry.py``'s
docstring for why: ``core/`` must not assume there's a well-defined
"current context" to evaluate against, which matters for correctness
inside an unattended batch loop, not just for unit-test isolation). The
caller (an operator) resolves the depsgraph once and passes it in.

Does NOT bake to a Shape Key -- that's Blender-object-mutating,
operator-layer work (creating/overwriting a key block, converting back to
the garment's local space) that stays out of ``core/``'s pure-logic scope,
matching every other module here. ``operators/op_fit.py`` is the sole
production caller and does that step itself with ``fit_once``'s output.
"""

from dataclasses import dataclass

from . import collision, geometry, smoothing, solver


@dataclass
class FitParams:
    """The user-facing Fit parameters (``obj.sculpt_tool``'s numeric/
    toggle settings), collected into one plain-data object so
    ``fit_once`` takes a single ``params`` argument instead of four
    separate ones -- and so a future Batch operator can build one
    ``FitParams`` per run (or per target, if it ever needs per-target
    overrides) without touching ``bpy`` settings objects inside a loop.
    """

    offset_scale: float = 1.0
    use_collision_resolution: bool = True
    collision_margin: float = 0.01
    smoothing_iterations: int = 0


def fit_once(garment_obj, target_body_obj, params, depsgraph, relax_ctx=None):
    """Run the full project -> collision -> smooth pipeline once.

    Mirrors ``operators/op_fit.py``'s pre-card pipeline exactly (see that
    module's docstring for the full step-by-step rationale, still
    accurate): ``core.solver.project_garment`` re-evaluates the garment's
    stored binding against ``target_body_obj``, then -- when
    ``params.use_collision_resolution`` -- ``core.collision.
    resolve_collisions`` pushes any interpenetrating vertex back out to at
    least ``params.collision_margin`` clearance, then -- when
    ``params.smoothing_iterations > 0`` -- ``core.smoothing.
    relax_positions`` runs that many pin-weighted relaxation passes, then
    -- when BOTH collision resolution and smoothing ran -- collision
    resolution runs a SECOND time on the smoothed result (smoothing has no
    notion of the target body and can drag an already-cleared vertex back
    into it; see ``operators/op_fit.py``'s docstring for the full
    rationale and the card that fixed it, 1e252575-2b86-4ba5-89f7-
    bcf0ae9685ba). The second pass reuses the SAME
    ``projection.anchor_positions``/``anchor_normals`` as the first: the
    anchor is a property of the binding's correspondence to the target
    body, not of the garment's current position, so smoothing moving
    vertices around does not invalidate it.

    A single ``core.geometry.TargetContext`` is built once, up front, from
    ``target_body_obj`` and ``depsgraph``, and reused for every step above
    that needs the target body's evaluated geometry (Mode B projection,
    both collision passes) -- this is what makes the target body's
    evaluation happen exactly once per ``fit_once`` call, no matter how
    many pipeline steps query it or how many times collision resolution
    runs (Bear PR Process card cd0d1569-36ad-4d79-a82b-6d1115a0bcda).
    ``TargetContext.bvh``/``.triangles`` are themselves built lazily (see
    ``core.geometry.TargetContext``'s docstring) and cached on first
    access, so a Mode A fit with collision resolution disabled -- which
    never reads either -- never triangulates or BVH-builds the target
    body at all, and never requires it to have any faces (Bear PR Process
    card e6763cc5-d3cf-4021-8541-f5e5dd4a23aa, fixing a regression this
    card's own extraction introduced). Mode B fits and both collision
    passes still access ``target_ctx.bvh`` and get the same "no
    triangulatable faces" ``ValueError`` as before if the target has none.

    ``relax_ctx``, if given, is a pre-built ``core.smoothing.
    RelaxContext`` for ``garment_obj`` -- skips rebuilding the garment's
    adjacency/original-edge-length/pin-weight arrays (constant across an
    entire batch run against the SAME garment; see ``RelaxContext``'s
    docstring). Built internally via ``RelaxContext.build(garment_obj)``
    when omitted and smoothing actually runs; never built at all when
    ``params.smoothing_iterations <= 0``, matching ``operators/op_fit.py``
    's pre-card guarantee that the zero-smoothing-iterations case doesn't
    even build the adjacency/neighbor structure or look up ``Pin_*``
    vertex groups.

    Returns the fitted WORLD-SPACE positions, one ``mathutils.Vector`` per
    garment vertex, in vertex-index order -- ready for a caller to convert
    to the garment's local space and bake into a Shape Key (or for a
    batch caller to do the same, once per target).

    Raises ``ValueError`` on any of the same conditions ``core.solver``/
    ``core.geometry``/``core.collision`` already raise it for (garment not
    bound, target body with no vertices/faces, a stale/missing Mode B
    source body, a solver output length mismatch) -- callers should catch
    it exactly as ``operators/op_fit.py`` always has.
    """
    target_ctx = geometry.TargetContext.build(target_body_obj, depsgraph)

    projection = solver.project_garment(garment_obj, target_ctx, params.offset_scale)
    fitted = projection.fitted_positions

    if params.use_collision_resolution:
        fitted = collision.resolve_collisions(
            fitted,
            projection.anchor_positions,
            projection.anchor_normals,
            target_ctx.bvh,
            params.collision_margin,
        )

    if params.smoothing_iterations > 0:
        if relax_ctx is None:
            relax_ctx = smoothing.RelaxContext.build(garment_obj)

        fitted = smoothing.relax_positions(
            fitted,
            relax_ctx.neighbors,
            relax_ctx.original_edges,
            relax_ctx.pin_weights,
            params.smoothing_iterations,
        )

        if params.use_collision_resolution:
            # Smoothing has no notion of the target body and can push an
            # already-cleared vertex back into it -- re-run collision
            # resolution on the smoothed result, reusing the same anchors
            # and the same target_ctx.bvh (no rebuild) as the first pass.
            fitted = collision.resolve_collisions(
                fitted,
                projection.anchor_positions,
                projection.anchor_normals,
                target_ctx.bvh,
                params.collision_margin,
            )

    return fitted
