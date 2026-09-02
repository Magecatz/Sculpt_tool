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

# Loose-vertex ramp (see project_to_target). A garment vertex authored within
# _LOOSE_NEAR_FRAC of the body (as a fraction of the target's bounding-box
# diagonal) is fully projected onto the target surface -- that's where girth
# mismatch interpenetrates and where nearest-surface correspondence is stable
# and wanted. A vertex authored farther off than _LOOSE_FAR_FRAC (a draped
# sleeve, an open jacket panel, a loose strap) KEEPS its armature-placed
# position instead: projecting it scatters the piece (adjacent loose verts snap
# to different body regions), and the skeleton already carries the loose shape
# correctly. Between the two the weight ramps smoothly so there's no seam.
_LOOSE_NEAR_FRAC = 0.012
_LOOSE_FAR_FRAC = 0.06


def _bbox_diagonal(positions):
    """Bounding-box diagonal length of a set of positions, or 0.0 if empty."""
    if not positions:
        return 0.0
    lo = [min(p[i] for p in positions) for i in range(3)]
    hi = [max(p[i] for p in positions) for i in range(3)]
    return ((hi[0] - lo[0]) ** 2 + (hi[1] - lo[1]) ** 2 + (hi[2] - lo[2]) ** 2) ** 0.5


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


def placed_standoff(placed_positions, target_ctx):
    """Fallback standoff when no source base is available: how far each
    already-placed garment vertex sits OUTSIDE the target surface, with
    interpenetration (negative) clamped to ``0``.

    Without the source body we cannot recover the authored standoff (a placed
    vertex's distance from the target conflates the authored offset with the
    girth error). This approximation keeps what we *can* trust: a vertex the
    armature placed genuinely off the body -- a loose strap, an open panel --
    stays that far off (positive standoff preserved), while a vertex the
    placement left inside the target (girth interpenetration) is pulled onto
    the surface (clamped to 0). Tight garments conform cleanly; loose
    silhouettes are approximated rather than lost.

    Prefer :func:`authored_standoff` with a real source base whenever one is
    available -- this is the degraded path (see RESTART_SCOPE.md section 5).
    """
    bvh = target_ctx.bvh
    standoff = []
    for position in placed_positions:
        placed = Vector(position)
        location, normal, index, _distance = bvh.find_nearest(placed)
        standoff.append(max(0.0, (placed - location).dot(normal)) if index is not None else 0.0)
    return standoff


def project_to_target(placed_positions, standoff, target_ctx, keep_loose=True):
    """Conform armature-PLACED garment vertices to the target body (Direction
    B, minimal).

    For each placed vertex, find the nearest point on the target surface and
    put the vertex that vertex's authored ``standoff`` off it, along the target
    surface normal there. That single step both resolves girth (a fatter/
    thinner target moves the surface, and the garment follows) and preserves a
    tight garment's silhouette -- with no collision push-out or smoothing to
    inflate or shrink-wrap it.

    ``keep_loose`` (default) adds the loose-vertex ramp: the projection above
    scatters vertices authored FAR off the body (draped sleeves, open jacket
    panels, loose straps), because adjacent loose verts snap to different body
    regions. So a vertex whose ``abs(standoff)`` exceeds
    :data:`_LOOSE_FAR_FRAC` of the target's bounding-box diagonal keeps its
    armature-PLACED position instead (the skeleton already carries the loose
    shape); a vertex within :data:`_LOOSE_NEAR_FRAC` is fully projected; between
    the two the result is a smooth lerp. This is what lets a tight top/pants and
    a loose open jacket conform correctly in the same pass. Pass
    ``keep_loose=False`` for the pure projection (every vertex projected).

    ``placed_positions`` are world-space garment vertices after armature
    placement; ``standoff`` is :func:`authored_standoff`'s output (or
    :func:`placed_standoff`'s, or any per-vertex signed standoff); ``target_ctx``
    is a ``core.geometry.TargetContext`` for the target body. A vertex whose
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

    near = far = span = 0.0
    if keep_loose:
        diagonal = _bbox_diagonal(target_ctx.positions)
        near = _LOOSE_NEAR_FRAC * diagonal
        far = _LOOSE_FAR_FRAC * diagonal
        span = max(far - near, 1e-9)

    fitted = []
    for position, offset in zip(placed_positions, standoff):
        placed = Vector(position)
        location, normal, index, _distance = bvh.find_nearest(placed)
        if index is None:
            fitted.append(placed)
            continue
        projected = location + normal * offset
        if not keep_loose:
            fitted.append(projected)
            continue
        # Ramp: 1 (fully project) when authored tight, 0 (keep placed) when loose.
        magnitude = abs(offset)
        if magnitude <= near:
            weight = 1.0
        elif magnitude >= far:
            weight = 0.0
        else:
            weight = 1.0 - (magnitude - near) / span
        fitted.append(placed.lerp(projected, weight))
    return fitted
