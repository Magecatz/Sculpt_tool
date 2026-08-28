"""Pin-weighted relaxation pass.

Per ARCHITECTURE.md section 3, step 3: a Laplacian-style smoothing pass
over the garment's post-collision-resolution vertex positions, run
``smoothing_iterations`` times (``operators/op_fit.py``, after
``core.collision.resolve_collisions`` and before the Shape Key bake).
For each vertex, a displacement toward its edge-connected neighbors'
average is computed and scaled by ``(1 - pin_weight)`` — ``pin_weight``
is that vertex's combined weight across every vertex group whose name
starts with ``Pin_`` (ARCHITECTURE.md section 6: e.g. ``Pin_Collar``,
``Pin_Cuff_L``, ``Pin_Cuff_R``, ``Pin_Hem``), clamped to ``[0, 1]``, so a
fully-pinned vertex (weight 1.0) has its displacement multiplied by
exactly ``0.0`` and never moves. This card reads those vertex groups by
name/weight directly — it does not need the future pin-region-management
UI to exist.

A plain Laplacian pass alone would progressively drag every vertex
toward its neighbors' average, which — run for enough iterations — is
exactly the shrink-wrap failure mode ARCHITECTURE.md section 1 names as
an explicit anti-goal (sleeves/collars/hems collapsing flat instead of
keeping their authored silhouette). To avoid that, each iteration also
runs a distance-constraint correction pass that pulls every edge back
toward its ORIGINAL length — measured on the garment's own BASE mesh
(``garment_obj.data``, pre-bind/pre-fit, not the evaluated/depsgraph
mesh and not anything already touched by projection or collision) in
world space, to match the world-space positions this module operates on.
This is a single-sweep, per-edge, mass-weighted correction (the same
family of technique as a position-based-dynamics distance constraint,
one relaxation sweep per call rather than iterating to full convergence
within a single smoothing iteration) — good enough to keep edge lengths
close to their authored values without turning this module into a full
constraint solver; repeated smoothing iterations let it converge further
if needed. Both the Laplacian step and the edge-length correction step
scale by ``(1 - pin_weight)`` per endpoint, so a fully-pinned vertex is
untouched by either.

Pure logic operating on mesh data (testable outside the UI), matching
``core/solver.py``/``core/collision.py``'s convention: no Blender-
operator/UI code lives here.

``relax()`` returns its input completely unchanged (same list) when
``iterations <= 0`` — the module-level guard exists so this stays
correct as a standalone entry point, but ``operators/op_fit.py`` itself
skips calling into this module at all when ``smoothing_iterations == 0``
so that case does not even build the adjacency/neighbor structure or
look up vertex groups.
"""

from mathutils import Vector

PIN_GROUP_PREFIX = "Pin_"

# Damping factor on the Laplacian step. A vertex is not fully snapped to
# its neighbors' average in one shot (lambda = 1.0 would be maximally
# aggressive and the most prone to overshoot/oscillation on irregular
# topology across repeated iterations); 0.5 is a conventional, stable
# choice for uniform Laplacian smoothing, leaving `smoothing_iterations`
# as the user's control over how much total smoothing is applied.
_LAMBDA = 0.5

# Below this edge length, direction is meaningless (coincident points) --
# skip the length correction rather than divide by ~zero.
_MIN_EDGE_LENGTH = 1e-12


def compute_pin_weights(garment_obj):
    """Per-vertex combined ``Pin_*`` vertex-group weight, in ``[0, 1]``.

    Returns a list with one entry per garment vertex (vertex-index
    order, matching every other per-vertex list in this pipeline). A
    vertex's weight is the SUM of its weight across every vertex group
    on ``garment_obj`` whose name starts with :data:`PIN_GROUP_PREFIX`
    (``"Pin_"``), clamped to ``1.0`` so overlapping pin groups can never
    push a vertex's effective pin weight past "fully pinned" (which
    would otherwise invert the ``(1 - pin_weight)`` scale into a
    negative number and flip displacement direction). A vertex in no
    ``Pin_*`` group at all gets ``0.0`` (fully free), and a garment with
    no ``Pin_*`` groups at all gets an all-``0.0`` list without needing
    special-casing by the caller.
    """
    mesh = garment_obj.data
    pin_group_indices = {
        vg.index for vg in garment_obj.vertex_groups if vg.name.startswith(PIN_GROUP_PREFIX)
    }

    weights = [0.0] * len(mesh.vertices)
    if not pin_group_indices:
        return weights

    for i, vertex in enumerate(mesh.vertices):
        total = 0.0
        for group_element in vertex.groups:
            if group_element.group in pin_group_indices:
                total += group_element.weight
        weights[i] = min(1.0, total)

    return weights


def _build_adjacency(mesh):
    """Edge-connected neighbor vertex indices, one list per vertex."""
    neighbors = [[] for _ in range(len(mesh.vertices))]
    for edge in mesh.edges:
        a, b = edge.vertices[0], edge.vertices[1]
        neighbors[a].append(b)
        neighbors[b].append(a)
    return neighbors


def _original_world_edges(garment_obj):
    """``(vertex_a, vertex_b, original_world_space_length)`` per mesh edge.

    Read from ``garment_obj.data`` (the BASE mesh, i.e. the garment as
    originally authored) rather than an evaluated/depsgraph mesh, and
    from ``garment_obj.matrix_world`` rather than local space, so these
    lengths are directly comparable to the world-space positions
    ``relax()`` operates on (``core.collision.resolve_collisions``'s
    output, pre-shape-key-bake).
    """
    mesh = garment_obj.data
    matrix = garment_obj.matrix_world
    positions = [matrix @ v.co for v in mesh.vertices]

    edges = []
    for edge in mesh.edges:
        a, b = edge.vertices[0], edge.vertices[1]
        length = (positions[b] - positions[a]).length
        edges.append((a, b, length))
    return edges


def _laplacian_step(positions, neighbors, pin_weights):
    """One damped, pin-weighted Laplacian pass.

    Simultaneous ("Jacobi-style") update: every vertex's new position is
    computed from the INPUT ``positions`` only, never from another
    vertex's already-updated position within the same step, so the
    result doesn't depend on vertex iteration order.
    """
    result = list(positions)
    for i, neighbor_indices in enumerate(neighbors):
        pin = pin_weights[i]
        if pin >= 1.0 or not neighbor_indices:
            continue

        average = Vector((0.0, 0.0, 0.0))
        for j in neighbor_indices:
            average += positions[j]
        average /= len(neighbor_indices)

        displacement = (average - positions[i]) * (_LAMBDA * (1.0 - pin))
        result[i] = positions[i] + displacement

    return result


def _edge_length_step(positions, original_edges, pin_weights):
    """One mass-weighted distance-constraint sweep toward original edge lengths.

    Sequential ("Gauss-Seidel-style") update over ``original_edges`` in a
    fixed (mesh edge index) order: each edge's correction is applied
    immediately, so later edges in the same sweep see earlier edges'
    corrections. This is standard for this class of constraint solver
    and converges faster than a simultaneous update would.
    """
    result = list(positions)
    for a, b, original_length in original_edges:
        free_a = 1.0 - pin_weights[a]
        free_b = 1.0 - pin_weights[b]
        total_free = free_a + free_b
        if total_free <= 0.0:
            # Both endpoints fully pinned -- no correction is allowed to
            # move either of them.
            continue

        delta = result[b] - result[a]
        current_length = delta.length
        if current_length < _MIN_EDGE_LENGTH:
            continue

        direction = delta / current_length
        correction = (current_length - original_length) * direction

        result[a] = result[a] + correction * (free_a / total_free)
        result[b] = result[b] - correction * (free_b / total_free)

    return result


def relax(garment_obj, positions, pin_weights=None, iterations=1):
    """Run ``iterations`` pin-weighted relaxation passes over ``positions``.

    ``positions`` is a list of world-space ``Vector`` positions, one per
    garment vertex, in vertex-index order (``core.collision.
    resolve_collisions``'s output). ``garment_obj`` supplies the topology
    (edge adjacency) and the original edge lengths this pass is
    constrained against, both read from its base mesh (see module
    docstring). ``pin_weights``, if given, is a per-vertex ``[0, 1]``
    list — typically :func:`compute_pin_weights`'s output; if omitted, an
    all-``0.0`` (nothing pinned) list is used.

    Each iteration is one damped Laplacian step (see
    :func:`_laplacian_step`) followed by one edge-length correction
    sweep (see :func:`_edge_length_step`); both scale every vertex's
    movement by ``(1 - pin_weight)``, so a vertex at ``pin_weight == 1.0``
    is added to across both steps with an exactly-zero vector every
    time — it comes out of ``relax()`` bit-for-bit identical to how it
    went in, regardless of ``iterations``.

    Returns a new list of the same length/order. ``iterations <= 0``
    returns ``positions`` unchanged (see module docstring for why
    callers should prefer not to call this function at all in that case).

    Raises ``ValueError`` if ``positions`` doesn't have exactly one entry
    per garment vertex.
    """
    if iterations <= 0:
        return positions

    mesh = garment_obj.data
    vertex_count = len(mesh.vertices)
    if len(positions) != vertex_count:
        raise ValueError(
            f"Got {len(positions)} positions, expected one per garment "
            f"vertex ({vertex_count})."
        )

    if pin_weights is None:
        pin_weights = [0.0] * vertex_count

    neighbors = _build_adjacency(mesh)
    original_edges = _original_world_edges(garment_obj)

    current = list(positions)
    for _ in range(iterations):
        current = _laplacian_step(current, neighbors, pin_weights)
        current = _edge_length_step(current, original_edges, pin_weights)

    return current
