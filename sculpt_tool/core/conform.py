"""Direction-B minimal conform (conform-rebuild restart).

The surface-conform stage, rebuilt from scratch per RESTART_SCOPE.md after the
old target-anchored pipeline (project against a frozen bind-time anchor, then
collision push-out, then smoothing relaxation) made unrecoverable mistakes --
inflating fitted pieces into blobs. The A-vs-B experiment
(``renders/ab_conform_experiment.py``) showed that the inflation came from the
**collision + smoothing loop**, not from target-anchored correspondence: a
single clean projection with the authored standoff reapplied conforms a
garment to a differently-proportioned target while preserving its shape.

So this module is deliberately tiny. Pure functions, no collision, no
smoothing, no BVH-anchor bookkeeping:

- :func:`authored_standoff` -- how far off its own body each garment vertex
  was authored to sit (measured against the source body it was designed for).
- :func:`placed_standoff` -- the source-free fallback standoff (measured from
  the placed garment against the target) when no source base is supplied.
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

# Minimum clearance the source-free fallback holds the garment off the target
# surface, as a fraction of the target's bounding-box diagonal. Without a
# source base an interpenetrating vertex is clamped to the surface; landing it
# at EXACTLY zero clearance makes the garment co-planar with the body and
# z-fights (the mottled belly on the source-free Bunny Suit). A few-mm lift
# removes that without a visible gap. Not used on the source-measured path,
# where a vertex authored to hug (standoff ~0) must stay hugging.
_MIN_CLEARANCE_FRAC = 0.002

# Loose-vertex ramp (see project_to_target). A garment vertex whose standoff is
# within _LOOSE_NEAR_FRAC of the body (as a fraction of the target bbox
# diagonal) is fully projected onto the target surface -- that's where girth
# mismatch interpenetrates and nearest-surface correspondence is stable. A
# vertex farther off than _LOOSE_FAR_FRAC (a flared pant leg, a draped sleeve,
# an open panel) KEEPS its armature-placed position instead: projecting loose
# geometry scatters it (adjacent loose verts snap to different body regions,
# projecting in different directions), and the skeleton already carries the
# loose shape correctly. Between the two the weight ramps smoothly.
_LOOSE_NEAR_FRAC = 0.012
_LOOSE_FAR_FRAC = 0.06

# Spatial-coherence smoothing of the project/keep-placed weight field. A purely
# per-vertex ramp tears a garment where adjacent verts straddle the near/far
# band (one projects, its neighbour keeps placed). Diffusing the weight over
# the mesh adjacency this many Laplacian passes makes the boundary a gradual
# band rather than a per-vertex step.
_WEIGHT_SMOOTH_ITERATIONS = 15


def build_vertex_neighbors(edge_pairs, vertex_count):
    """Adjacency list (one list of neighbour vertex indices per vertex) from
    ``edge_pairs`` -- ``(v0, v1)`` index tuples, e.g. a mesh's edges. Pure
    data, so :func:`project_to_target`'s weight smoothing stays testable
    outside Blender; the operator builds ``edge_pairs`` from the garment mesh.
    """
    neighbors = [[] for _ in range(vertex_count)]
    for a, b in edge_pairs:
        if a == b:
            continue
        neighbors[a].append(b)
        neighbors[b].append(a)
    return neighbors


def _smooth_weights(weights, neighbors, iterations):
    """Laplacian-diffuse a per-vertex scalar ``weights`` field over
    ``neighbors`` for ``iterations`` passes (each vertex -> mean of its
    neighbours), so the project/keep-placed boundary is gradual, not a step."""
    for _ in range(iterations):
        updated = weights[:]
        for i, adjacent in enumerate(neighbors):
            if adjacent:
                updated[i] = sum(weights[j] for j in adjacent) / len(adjacent)
        weights = updated
    return weights


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
    placement left inside the target (girth interpenetration) is pulled to a
    small minimum clearance off the surface (``_MIN_CLEARANCE_FRAC`` of the
    target bbox diagonal) rather than exactly onto it, so the garment doesn't
    end up co-planar with the body and z-fight. Tight garments conform
    cleanly; loose silhouettes are approximated rather than lost.

    Prefer :func:`authored_standoff` with a real source base whenever one is
    available -- this is the degraded path (see RESTART_SCOPE.md section 5).
    """
    bvh = target_ctx.bvh
    min_clearance = _MIN_CLEARANCE_FRAC * _bbox_diagonal(target_ctx.positions)
    standoff = []
    for position in placed_positions:
        placed = Vector(position)
        location, normal, index, _distance = bvh.find_nearest(placed)
        outside = (placed - location).dot(normal) if index is not None else 0.0
        standoff.append(max(min_clearance, outside))
    return standoff


def surface_standoffs(positions, target_ctx):
    """Unsigned nearest-target-surface distance per vertex.

    The abs-distance sibling of :func:`placed_standoff` with no min-clearance
    clamp: just how far each vertex sits from the target surface, used by the
    quality metrics (looseness preservation) rather than by conform itself.
    Returns one float per ``positions`` entry, in order; a vertex with no
    surface hit gets ``0.0``.
    """
    bvh = target_ctx.bvh
    out = []
    for position in positions:
        _location, _normal, index, distance = bvh.find_nearest(Vector(position))
        out.append(distance if index is not None else 0.0)
    return out


def project_to_target(placed_positions, standoff, target_ctx, keep_loose=True,
                      neighbors=None, weight_smooth_iterations=_WEIGHT_SMOOTH_ITERATIONS):
    """Conform armature-PLACED garment vertices to the target body (Direction B).

    For each placed vertex, find the nearest point on the target surface and
    put the vertex that vertex's ``standoff`` off it, along the target surface
    normal there. That single step resolves girth (a fatter/thinner target
    moves the surface and the garment follows) and preserves a tight garment's
    silhouette -- no collision push-out or smoothing to inflate/shrink-wrap it.

    ``keep_loose`` (default) adds the loose-vertex ramp: projecting a vertex
    authored/placed FAR off the body (a flared pant leg, a draped sleeve, an
    open panel) scatters it, because adjacent loose verts snap to different
    body regions. So a vertex whose ``abs(standoff)`` exceeds
    :data:`_LOOSE_FAR_FRAC` of the target bbox diagonal keeps its armature-
    PLACED position (the skeleton already carries the loose shape); within
    :data:`_LOOSE_NEAR_FRAC` it is fully projected; between, a smooth lerp.
    Pass ``keep_loose=False`` for pure projection (every vertex projected).

    ``neighbors`` (from :func:`build_vertex_neighbors`), when given, adds
    spatial coherence: the per-vertex ramp weight is Laplacian-diffused over
    the mesh adjacency ``weight_smooth_iterations`` passes before the blend, so
    the tight->loose transition is a gradual band, not a per-vertex step (which
    would tear the surface along the boundary).

    ``placed_positions`` are world-space garment vertices after armature
    placement; ``standoff`` is :func:`authored_standoff`'s / :func:`placed_standoff`'s
    output (or any per-vertex signed standoff); ``target_ctx`` is a
    ``core.geometry.TargetContext``. A vertex whose projection misses the
    surface keeps its placed position.

    Returns world-space fitted positions (``mathutils.Vector`` per vertex).
    Raises ``ValueError`` if ``standoff`` and ``placed_positions`` differ in
    length.
    """
    if len(standoff) != len(placed_positions):
        raise ValueError(
            f"standoff has {len(standoff)} entries but placed_positions has "
            f"{len(placed_positions)} (must be one standoff per placed vertex)."
        )
    bvh = target_ctx.bvh

    placed_vecs = [Vector(p) for p in placed_positions]
    projected = []
    for placed, offset in zip(placed_vecs, standoff):
        location, normal, index, _distance = bvh.find_nearest(placed)
        projected.append(placed if index is None else location + normal * offset)

    if not keep_loose:
        return projected

    diagonal = _bbox_diagonal(target_ctx.positions)
    near = _LOOSE_NEAR_FRAC * diagonal
    far = _LOOSE_FAR_FRAC * diagonal
    span = max(far - near, 1e-9)
    weights = []
    for offset in standoff:
        magnitude = abs(offset)
        if magnitude <= near:
            weights.append(1.0)
        elif magnitude >= far:
            weights.append(0.0)
        else:
            weights.append(1.0 - (magnitude - near) / span)

    if neighbors is not None and weight_smooth_iterations > 0:
        weights = _smooth_weights(weights, neighbors, weight_smooth_iterations)

    return [placed.lerp(proj, w) for placed, proj, w in zip(placed_vecs, projected, weights)]
