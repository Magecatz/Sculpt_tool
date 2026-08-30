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
    against the SAME target body, so ``core.pipeline.fit_once`` evaluates,
    triangulates, and BVH-builds the target body exactly once per fit, no
    matter how many pipeline steps query it.

    ``positions``/``normals`` are per-TARGET-vertex (vertex-index order),
    serving Mode A's direct index lookup. ``triangles``/``bvh`` are the
    triangulated surface (built from the SAME evaluated-mesh read, so
    ``positions`` here is identical content to what a separate
    :func:`world_space_triangles` call on the same object/depsgraph would
    return), serving Mode B's nearest-surface projection and both
    collision tests' BVH queries. ``name`` is the target object's name,
    kept only so error messages further down the pipeline can still name
    the target body without holding onto the ``bpy`` object itself.
    """

    name: str
    positions: list
    normals: list
    triangles: list
    bvh: BVHTree

    @classmethod
    def build(cls, target_body_obj, depsgraph):
        """Evaluate ``target_body_obj`` once and build its :class:`TargetContext`.

        Raises ``ValueError`` if the target body has no vertices or no
        triangulatable faces -- the same checks ``core.solver.
        project_mode_a``/``project_mode_b`` and ``core.collision.
        resolve_collisions`` used to make independently (and redundantly,
        against the same target, multiple times per fit) before this
        context existed.
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
        if not triangles:
            raise ValueError(
                f"Target body '{target_body_obj.name}' has no triangulatable faces."
            )

        bvh = BVHTree.FromPolygons(positions, triangles)
        return cls(
            name=target_body_obj.name,
            positions=positions,
            normals=normals,
            triangles=triangles,
            bvh=bvh,
        )
