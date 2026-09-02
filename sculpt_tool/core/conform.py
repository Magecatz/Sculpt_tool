"""Direction-B minimal conform (conform-rebuild restart).

The surface-conform stage, rebuilt from scratch per RESTART_SCOPE.md after the
old target-anchored pipeline (project against a frozen bind-time anchor, then
collision push-out, then smoothing relaxation) made unrecoverable mistakes --
inflating fitted pieces into blobs. The A-vs-B experiment
(``renders/ab_conform_experiment.py``) showed that the inflation came from the
**collision + smoothing loop**, not from target-anchored correspondence: a
single clean projection with the authored standoff reapplied conforms a
garment to a differently-proportioned target while preserving its shape.

So this module is deliberately tiny. Two pure functions, no collision, no
smoothing, no BVH-anchor bookkeeping:

- :func:`authored_standoff` -- how far off its own body each garment vertex
  was authored to sit (measured against the source body it was designed for).
- :func:`project_to_target` -- project each (already armature-placed) garment
  vertex onto the nearest target-body surface point and reapply that standoff
  along the target normal.

Like the rest of ``core/`` this is pure logic operating on geometry the caller
supplies (world-space vertex positions and a pre-built
``core.geometry.TargetContext``); it never touches ``bpy.context`` or mutates
the scene, so it is unit-testable on synthetic tubes/grids
(``tests/test_conform.py``). The operator layer owns armature placement (via
the placement spine), evaluating the placed mesh, and baking the result into a
Shape Key.
"""

from mathutils import Vector


def authored_standoff(rest_positions, source_ctx):
    """Signed distance each garment vertex sits off the SOURCE body surface,
    along the source surface normal at its nearest point -- the garment's
    authored "how far off its own body, and which side" value.

    ``rest_positions`` are the garment's world-space vertices as authored (on
    the source body); ``source_ctx`` is a ``core.geometry.TargetContext`` for
    that source body. Positive = outside the body (a loose strap, a standoff
    collar); ~0 = hugging; negative = authored to sit just inside the surface
    (a waistband cinched into the flesh). A vertex with no surface hit gets
    ``0.0`` (treated as hugging).

    Returned in vertex-index order, one float per ``rest_positions`` entry, so
    it lines up with :func:`project_to_target`'s ``placed_positions``.
    """
    bvh = source_ctx.bvh
    standoff = []
    for position in rest_positions:
        location, normal, index, _distance = bvh.find_nearest(Vector(position))
        standoff.append((Vector(position) - location).dot(normal) if index is not None else 0.0)
    return standoff


def project_to_target(placed_positions, standoff, target_ctx):
    """Conform armature-PLACED garment vertices to the target body (Direction
    B, minimal).

    For each placed vertex, find the nearest point on the target surface and
    put the vertex that vertex's authored ``standoff`` off it, along the target
    surface normal there. That single step both resolves girth (a fatter/
    thinner target moves the surface, and the garment follows) and preserves
    the garment's silhouette (tight stays tight, loose stays loose) -- with no
    collision push-out or smoothing to inflate or shrink-wrap it.

    ``placed_positions`` are world-space garment vertices after armature
    placement; ``standoff`` is :func:`authored_standoff`'s output (or any
    per-vertex signed standoff); ``target_ctx`` is a
    ``core.geometry.TargetContext`` for the target body. A vertex whose
    projection misses the surface keeps its placed position.

    Returns world-space fitted positions (``mathutils.Vector`` per vertex, in
    vertex-index order) ready for the operator layer to bake.

    Raises ``ValueError`` if ``standoff`` and ``placed_positions`` differ in
    length (a caller bug -- they must be the same garment's vertices).
    """
    if len(standoff) != len(placed_positions):
        raise ValueError(
            f"standoff has {len(standoff)} entries but placed_positions has "
            f"{len(placed_positions)} (must be one standoff per placed vertex)."
        )
    bvh = target_ctx.bvh
    fitted = []
    for position, offset in zip(placed_positions, standoff):
        placed = Vector(position)
        location, normal, index, _distance = bvh.find_nearest(placed)
        fitted.append(location + normal * offset if index is not None else placed)
    return fitted
