"""Shared geometry primitives, plus per-fit target-body context.

Promoted out of ``core/binding.py``'s underscore-prefixed helpers (Bear PR
Process card cd0d1569-36ad-4d79-a82b-6d1115a0bcda): ``core/solver.py``
called ``binding._world_space_positions_and_normals``, ``binding.
_local_frame``, ``binding._triangle_frame``, and ``binding.
_world_space_triangles``; ``operators/op_fit.py`` called ``binding.
_world_space_triangles`` too. Three (soon four, once Batch lands)
consumers reaching into another module's private API is a sign these are
shared geometry primitives, not ``binding.py``-internal details -- they
live here instead, as public functions, so no module outside
``binding.py`` needs a ``binding._``-prefixed name.

``world_space_positions_and_normals``/``world_space_triangles`` take an
already-resolved ``depsgraph`` parameter rather than resolving Blender's
current evaluated depsgraph themselves (the previous behavior, inherited
unchanged from ``binding.py``). ARCHITECTURE.md section 5 claims
``core/`` is "pure logic ... testable outside the UI"; reaching for
Blender's own live UI context silently assumes there's a well-defined
"current context" to evaluate against, which is not a safe assumption
inside a long unattended batch loop. Callers (``operators/``, or
``core/pipeline.py``) resolve the depsgraph once, via ``context.
evaluated_depsgraph_get()`` on whatever ``bpy.types.Context`` they were
given, and pass it down explicitly.

:class:`TargetContext` addresses a related, separate problem noted on the
same card: a target body was being evaluated, triangulated, and BVH-built
TWICE per fit (once inside ``core.solver.project_mode_b``, again inside
``core.collision.resolve_collisions`` -- and a THIRD time if smoothing
triggers collision's second pass). ``TargetContext.build`` does that work
exactly once per fit, from a single evaluated-mesh read, and the result
(positions/normals for Mode A's direct index lookup, triangles/BVH for
Mode B's projection and both collision passes) is threaded through
``core.pipeline.fit_once`` to every step that needs it.
"""

from dataclasses import dataclass

from mathutils import Vector
from mathutils.bvhtree import BVHTree


def local_frame(normal):
    """Build a deterministic orthonormal (normal, tangent, bitangent) frame.

    Reused at fit time from a (possibly shape-key-changed) body vertex's
    new normal, so the frame rotates along with the body's deformation
    instead of needing its own stored tangent -- that's what makes a Mode
    A binding "reapply correctly when the body's shape changes via shape
    keys" per ARCHITECTURE.md.

    No UV dependency (per ARCHITECTURE.md section 2 / Risks): the
    tangent is derived from an arbitrary but fixed reference axis, with
    a fallback axis for the near-parallel case so the frame never
    degenerates.
    """
    normal = normal.normalized()

    reference = Vector((0.0, 0.0, 1.0))
    if abs(normal.z) > 0.99:
        reference = Vector((1.0, 0.0, 0.0))

    tangent = reference - normal * normal.dot(reference)
    if tangent.length_squared < 1e-12:
        reference = Vector((0.0, 1.0, 0.0))
        tangent = reference - normal * normal.dot(reference)
    tangent.normalize()

    bitangent = normal.cross(tangent)
    return normal, tangent, bitangent


def triangle_frame(a, b, c):
    """Deterministic orthonormal (normal, tangent, bitangent) frame for a triangle.

    Derived purely from the triangle's own vertices (edge ``a->b`` as the
    tangent axis, face normal via cross product) rather than an external
    reference -- the same construction can be reproduced at fit time from
    just the (target-body) triangle's vertices, with no need to store a
    tangent separately, mirroring how :func:`local_frame` is reproducible
    from just a body vertex normal.

    Falls back to :func:`local_frame`'s arbitrary-reference construction
    for a degenerate (zero-area) triangle so this never raises/divides by
    zero on garbage input.
    """
    edge_ab = b - a
    edge_ac = c - a
    normal = edge_ab.cross(edge_ac)

    if normal.length_squared < 1e-12 or edge_ab.length_squared < 1e-12:
        return local_frame(Vector((0.0, 0.0, 1.0)))

    normal.normalize()
    tangent = edge_ab.normalized()
    bitangent = normal.cross(tangent)
    return normal, tangent, bitangent


def barycentric_weights(p, a, b, c):
    """Barycentric weights ``(u, v, w)`` of point ``p`` w.r.t. triangle ``a, b, c``.

    Standard area-ratio formula (assumes ``p`` lies in the triangle's
    plane, which the BVH nearest-surface hit point always does -- on
    interior, edge, or vertex cases alike). ``p == u*a + v*b + w*c``, and
    ``u + v + w == 1``. Falls back to pinning all weight on ``a`` for a
    degenerate (zero-area) triangle rather than dividing by zero.
    """
    v0 = b - a
    v1 = c - a
    v2 = p - a

    d00 = v0.dot(v0)
    d01 = v0.dot(v1)
    d11 = v1.dot(v1)
    d20 = v2.dot(v0)
    d21 = v2.dot(v1)

    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-12:
        return (1.0, 0.0, 0.0)

    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    u = 1.0 - v - w
    return (u, v, w)


def world_space_positions_and_normals(obj, depsgraph):
    """Evaluated (modifiers applied), world-space vertex positions/normals.

    ``depsgraph`` is a resolved ``bpy.types.Depsgraph`` (typically
    ``context.evaluated_depsgraph_get()``, obtained by the caller -- see
    module docstring for why this function does not resolve it itself).

    NOT vectorized with NumPy, despite Bear PR Process card
    1f564161-82f9-4d5d-bd63-665d98790e8a's own "honest scope" listing
    this as an "easy win" -- verified, empirically, not to be one. The
    per-vertex ``matrix @ v.co`` / ``(normal_matrix @ v.normal).
    normalized()`` this does is a REDUCTION (dot product) and a
    transcendental (``sqrt``, inside ``normalized()``); a from-scratch
    NumPy re-implementation of either, checked bit-for-bit against
    ``mathutils``'s own per-vertex result on this project's actual
    Test_Items corpus (which has non-zero, if small, rotation from FBX
    import) diverges by 1 ULP on a real fraction of vertices -- observed
    ~9% for a body/garment pair, worse (~60%) once that error propagates
    through a downstream bind+fit. A single-elementwise-op function
    (cross product) matched bit-for-bit in the same check; dot product,
    matrix-vector multiply, and ``normalized()`` all did not, across
    several candidate summation orders and both float32- and
    float64-accumulator variants tried. See the card's PR for the full
    numeric writeup. This card's acceptance bar is bit-identical output
    (verified zero-diff, this project's own existing convention -- see
    e.g. ``tests/test_geometry.py``'s ``assertEqual(diff, 0.0)``), so
    this function is intentionally left exactly as it was rather than
    shipping a vectorization that would fail that bar on real assets.
    """
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()

    matrix = obj.matrix_world
    normal_matrix = matrix.inverted_safe().transposed().to_3x3()

    positions = [matrix @ v.co for v in mesh.vertices]
    normals = [(normal_matrix @ v.normal).normalized() for v in mesh.vertices]

    eval_obj.to_mesh_clear()
    return positions, normals


def world_space_triangles(obj, depsgraph):
    """Evaluated, world-space (vertex_positions, triangle_vertex_indices).

    ``triangle_vertex_indices`` is a list of ``(a, b, c)`` index tuples
    into ``vertex_positions``, taken from the mesh's triangulated
    ``loop_triangles`` (built even for a quad/ngon mesh) so every entry
    is an actual 3-vertex triangle suitable for barycentric coordinates.
    The list's order/indexing matches what a BVH built via
    ``BVHTree.FromPolygons(vertex_positions, triangle_vertex_indices)``
    reports back as its nearest-hit "polygon" index -- that's what makes
    a stored ``triangle_index`` reproducible: recomputing
    ``loop_triangles`` on the (possibly different) body at read time and
    indexing into it the same way reconstructs the same triangle.

    ``depsgraph`` is a resolved ``bpy.types.Depsgraph`` -- see module
    docstring and :func:`world_space_positions_and_normals`.

    ``triangle_vertex_indices`` was tried, vectorized, as part of Bear PR
    Process card 1f564161-82f9-4d5d-bd63-665d98790e8a: a single bulk
    ``mesh.loop_triangles.foreach_get("vertices", ...)`` read plus a
    reshape, replacing the per-triangle ``[tuple(lt.vertices) for lt in
    mesh.loop_triangles]`` Python loop below. Unlike the position half
    (see :func:`world_space_positions_and_normals`'s docstring), this one
    IS exactly -- not just numerically-close -- equivalent to the loop it
    would replace: integer vertex-index data, no floating-point
    arithmetic anywhere in the path. It was reverted anyway, for the same
    reason ``core/smoothing.py``'s ``_laplacian_step`` was: measured, not
    assumed, performance. Benchmarked against the unvectorized loop below
    at both this project's real Test_Items body (23,153 verts / ~44k
    triangles) and ``tests/perf.py``'s larger synthetic scale (65,160
    triangles), the "vectorized" version was a statistical wash at best
    (within ~10% either way across repeated runs) and slightly SLOWER
    more often than not -- the ``[tuple(t) for t in flat.reshape(-1,
    3).tolist()]`` step needed to hand back the same list-of-int-tuples
    shape callers (``BVHTree.FromPolygons``, per-triangle vertex-index
    lookups elsewhere in ``core/``) rely on costs about as much
    Python-level work as the loop it replaces. See the card's PR for the
    full numbers.
    """
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    mesh.calc_loop_triangles()

    matrix = obj.matrix_world
    positions = [matrix @ v.co for v in mesh.vertices]
    triangles = [tuple(lt.vertices) for lt in mesh.loop_triangles]

    eval_obj.to_mesh_clear()
    return positions, triangles


@dataclass
class TargetContext:
    """A target body's evaluated world-space geometry, built once per fit.

    Bundles what both ``core.solver`` (Mode B projection) and
    ``core.collision`` (both collision passes, including the second one
    after smoothing -- see ``operators/op_fit.py``'s docstring) need
    against the SAME target body, so ``core.pipeline.fit_once`` evaluates
    the target body exactly once per fit, no matter how many pipeline
    steps query it.

    ``positions``/``normals`` are per-TARGET-vertex (vertex-index order),
    serving Mode A's direct index lookup -- built eagerly in
    :meth:`build`, since every fit (Mode A or B) needs them.

    ``triangles``/``bvh`` serve Mode B's nearest-surface projection and
    both collision tests' BVH queries -- NEITHER is needed by a Mode A
    fit with collision resolution disabled, which has no notion of faces
    at all (see :meth:`build`'s docstring). They're therefore exposed as
    lazily-built properties instead of eager fields: the triangulated
    surface is computed, and the "no triangulatable faces" check raised,
    only the first time ``.triangles`` (or ``.bvh``, which needs
    ``.triangles``) is actually accessed -- by ``project_mode_b`` or by
    ``core.pipeline.fit_once``'s call into ``core.collision.
    resolve_collisions``. A pure Mode A fit against a faceless-but-
    vertexed target body never touches either, so it never pays that
    check. Once built, the result is cached on the instance -- still only
    evaluated/triangulated/BVH-built once per fit no matter how many
    times a step asks for it.

    ``name`` is the target object's name, kept only so error messages
    further down the pipeline can still name the target body without
    holding onto the ``bpy`` object itself.
    """

    name: str
    positions: list
    normals: list
    _triangles: list
    _bvh: "BVHTree | None" = None

    @property
    def triangles(self):
        """The target body's triangulated surface (loop-triangle vertex
        index tuples). Raises ``ValueError`` here, on first access, if
        the target body has no triangulatable faces -- see the class
        docstring for why this check is deferred rather than made
        unconditionally in :meth:`build`."""
        if not self._triangles:
            raise ValueError(f"Target body '{self.name}' has no triangulatable faces.")
        return self._triangles

    @property
    def bvh(self):
        """The target body's BVH tree, built lazily (and cached) from
        :attr:`triangles` on first access -- see the class docstring."""
        if self._bvh is None:
            self._bvh = BVHTree.FromPolygons(self.positions, self.triangles)
        return self._bvh

    @classmethod
    def build(cls, target_body_obj, depsgraph):
        """Evaluate ``target_body_obj`` once and build its :class:`TargetContext`.

        Raises ``ValueError`` immediately if the target body has no
        vertices -- every fit mode needs at least that. Does NOT raise
        for zero triangulatable faces here: that check is deferred to
        first access of ``.triangles``/``.bvh`` (see the class
        docstring), matching pre-refactor behavior where ``core.solver.
        project_mode_a`` only ever required target vertices and never
        touched triangles/BVH at all.
        """
        eval_obj = target_body_obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        mesh.calc_loop_triangles()

        matrix = target_body_obj.matrix_world
        normal_matrix = matrix.inverted_safe().transposed().to_3x3()

        positions = [matrix @ v.co for v in mesh.vertices]
        normals = [(normal_matrix @ v.normal).normalized() for v in mesh.vertices]
        triangles = [tuple(lt.vertices) for lt in mesh.loop_triangles]

        eval_obj.to_mesh_clear()

        if not positions:
            raise ValueError(f"Target body '{target_body_obj.name}' has no vertices.")

        return cls(
            name=target_body_obj.name,
            positions=positions,
            normals=normals,
            _triangles=triangles,
        )
