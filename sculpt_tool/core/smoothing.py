"""Pin-weighted relaxation pass.

Per ARCHITECTURE.md section 3, step 3: a Laplacian-style smoothing pass
over the garment's post-collision-resolution vertex positions, run
``smoothing_iterations`` times (``operators/op_fit.py``, after
``core.collision.resolve_collisions`` and before the Shape Key bake).
For each vertex, a displacement toward its edge-connected neighbors'
average is computed, and each OUTER iteration's combined result (see
below) is blended against the vertex's pre-iteration position by
``(1 - pin_weight)`` — ``pin_weight`` is that vertex's combined weight
across every vertex group whose name starts with ``Pin_``
(ARCHITECTURE.md section 6: e.g. ``Pin_Collar``, ``Pin_Cuff_L``,
``Pin_Cuff_R``, ``Pin_Hem``), clamped to ``[0, 1]``, so a fully-pinned
vertex (weight 1.0) is blended entirely toward its own pre-iteration
position and never moves. This card reads those vertex groups by
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
This is a per-edge, mass-weighted correction (the same family of
technique as a position-based-dynamics distance constraint), run as
several internal Gauss-Seidel sub-sweeps per smoothing iteration (see
``_EDGE_CORRECTION_SUBSTEPS``) rather than exactly one — a single sweep
per iteration was found to leave enough residual edge-length error for
the next iteration's Laplacian step to compound into a several-percent
radius shrink on curved (tube/sleeve-shaped) geometry even with zero
noise and zero pins, which is exactly the shrink-wrap failure mode this
correction exists to prevent. Iterating the sub-sweep internally lets
each outer iteration re-satisfy edge lengths close enough to their
authored values that the residual plateaus instead of compounding as
``smoothing_iterations`` grows, while still stopping short of a full
constraint solver.

Pin weighting is applied ONCE PER OUTER ITERATION, at the ``relax()``
level, rather than woven into the Laplacian/edge-length math itself:
each outer iteration first computes what the Laplacian step + all edge-
length sub-sweeps would produce if NO vertex were pinned at all (an
entirely unpinned "fully solved" candidate, using the exact same
:func:`_laplacian_step`/:func:`_edge_length_step` internals, called with
an all-``0.0`` pin array), then blends each vertex between its own
pre-iteration position and that candidate by its own ``(1 - pin_weight)``
— a direct, literal implementation of ARCHITECTURE.md section 6's
"blends a vertex between fully solved and rigid, unchanged" language.
See :func:`relax` for why this replaced an earlier per-edge weighting
scheme that turned out not to produce a linear aggregate blend (bug card
1638a2d4-45d5-4264-9bc0-4e0ac339936b).

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

    ``pin_weights`` is accepted and honored here (a ``pin_weight == 1.0``
    vertex is skipped entirely, matching this function's own docstring),
    but :func:`relax` always calls this with an all-``0.0`` array now —
    pin weighting moved to the outer-iteration blend in :func:`relax`
    (bug card 1638a2d4-45d5-4264-9bc0-4e0ac339936b). Kept pin-aware
    rather than hard-coded to "no pins" so this stays a correct, reusable
    building block on its own.
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


# Number of internal Gauss-Seidel sweeps _edge_length_step runs per outer
# relax() iteration. A single sweep does not fully re-satisfy every edge
# before the next outer iteration's Laplacian step compounds a fresh
# contraction on top of whatever length error is left over -- on curved
# geometry (e.g. a cylindrical/tube-shaped garment) that residual error
# accumulates iteration over iteration instead of canceling, producing
# several-percent radius shrinkage over a typical smoothing_iterations
# run even with zero noise and zero pins on a perfectly clean mesh (an
# Architect-confirmed regression against ARCHITECTURE.md section 1's
# anti-shrinkwrap goal). Looping this sweep internally lets each outer
# iteration re-converge edge lengths much closer to their original
# values before the next Laplacian step runs, so the residual plateaus
# instead of compounding as `iterations` grows. 16 was the Architect's
# own tested figure (~0.2% shrinkage at both 10 and 40 outer iterations
# on a synthetic tube case, confirming a plateau rather than continued
# growth) and stays cheap relative to the pipeline's per-vertex BVH
# collision work even at this ~16x increase in sweep count.
_EDGE_CORRECTION_SUBSTEPS = 16


def _edge_length_step(positions, original_edges, pin_weights):
    """``_EDGE_CORRECTION_SUBSTEPS`` mass-weighted distance-constraint
    sweeps toward original edge lengths.

    Each sub-sweep is a sequential ("Gauss-Seidel-style") update over
    ``original_edges`` in a fixed (mesh edge index) order: each edge's
    correction is applied immediately, so later edges in the same
    sub-sweep see earlier edges' corrections, and each sub-sweep after
    the first sees the previous sub-sweep's corrections. This is
    standard for this class of constraint solver and converges faster
    than a simultaneous update would; running several sub-sweeps here
    (rather than exactly one) is what lets edge lengths re-converge close
    to their original values within a single outer `relax()` iteration
    instead of leaving a residual for the next iteration's Laplacian step
    to compound (see :data:`_EDGE_CORRECTION_SUBSTEPS`).

    ``pin_weights`` is accepted and honored here (mass-weighted split by
    each endpoint's own ``(1 - pin_weight)``), but :func:`relax` always
    calls this with an all-``0.0`` array now — pin weighting moved to the
    outer-iteration blend in :func:`relax` (bug card
    1638a2d4-45d5-4264-9bc0-4e0ac339936b: the mass-weighted split here
    made a vertex's absorbed share of each edge's correction depend on
    its NEIGHBOR's pin weight as much as its own, which did not produce a
    linear aggregate blend — see :func:`relax` for what replaced it).
    Kept pin-aware rather than hard-coded to "no pins" so this stays a
    correct, reusable building block on its own.
    """
    result = list(positions)
    for _ in range(_EDGE_CORRECTION_SUBSTEPS):
        for a, b, original_length in original_edges:
            free_a = 1.0 - pin_weights[a]
            free_b = 1.0 - pin_weights[b]
            total_free = free_a + free_b
            if total_free <= 0.0:
                # Both endpoints fully pinned -- no correction is allowed
                # to move either of them.
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

    Each outer iteration: run one damped Laplacian step (see
    :func:`_laplacian_step`) followed by several internal edge-length
    correction sub-sweeps (see :func:`_edge_length_step`) with NO vertex
    treated as pinned, producing an entirely unpinned "fully solved"
    candidate position for every vertex; then blend each vertex between
    its own pre-iteration position and that candidate by its own
    ``(1 - pin_weight)`` (``new = old * pin + candidate * (1 - pin)``).
    A vertex at ``pin_weight == 1.0`` is therefore blended entirely back
    to its own pre-iteration position every outer iteration — it comes
    out of ``relax()`` bit-for-bit identical to how it went in, regardless
    of ``iterations``. A vertex at ``pin_weight == 0.0`` gets exactly the
    candidate position (identical to today's zero-pin behavior, since the
    candidate itself is computed by the same zero-pin code path).

    This blend is applied ONCE PER OUTER ITERATION rather than woven into
    the Laplacian/edge-length math itself (bug card
    1638a2d4-45d5-4264-9bc0-4e0ac339936b — see module docstring and
    :func:`_edge_length_step`): an earlier version scaled each vertex's
    share of the per-edge length correction directly, which made a
    partially-pinned vertex's absorbed correction depend on its
    neighbor's pin weight too, and empirically produced a non-linear,
    even non-monotonic aggregate blend across multiple outer iterations
    (measured moving 0.76x-0.96x of an unpinned vertex's displacement at
    pin_weight=0.5, instead of ~0.5x, and in some configurations MORE
    than an unpinned vertex — see the fix's PR for the full measurement).
    Blending once per outer iteration is a direct, literal reading of
    ARCHITECTURE.md section 6 ("blends a vertex between fully solved and
    rigid, unchanged") and measures much closer to linear in practice:
    on an isolated pinned vertex, aggregate displacement at pin_weight
    0.25/0.5/0.75 measured ~0.70-0.91x / ~0.44-0.80x / ~0.21-0.60x of an
    otherwise-identical unpinned vertex's displacement (range across 1-10
    outer iterations; exactly linear at 1 iteration, drifting further
    from exact as outer iterations and inter-vertex coupling increase,
    but always monotonic and never exceeding the unpinned baseline). A
    continuous pinned band (e.g. a realistic ``Pin_Hem`` selection, where
    every pinned vertex's neighbors are also pinned) drifts somewhat
    further from exact linearity at higher iteration counts than an
    isolated pinned vertex does, since neighboring pinned vertices'
    unpinned "candidate" positions reinforce each other's advancement
    iteration over iteration — still monotonic and bounded by the
    unpinned baseline, just a softer blend than a single isolated pin at
    the same weight. Not a regression against this fix's own goal (which
    was fixing the 0.76x-0.96x near-binary plateau, not guaranteeing
    exact linearity under every topology), but worth knowing when
    reasoning about a specific garment's pinned-region behavior.

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
    zero_pins = [0.0] * vertex_count

    current = list(positions)
    for _ in range(iterations):
        candidate = _laplacian_step(current, neighbors, zero_pins)
        candidate = _edge_length_step(candidate, original_edges, zero_pins)
        current = [
            current[i] * pin_weights[i] + candidate[i] * (1.0 - pin_weights[i])
            for i in range(vertex_count)
        ]

    return current
