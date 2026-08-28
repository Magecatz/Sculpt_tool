"""Mode A + Mode B bind computation.

Per ARCHITECTURE.md section 2. This module is pure logic operating on
mesh data (evaluated, world-space vertex positions/normals) so it is
testable outside the UI; it has no knowledge of how a bind result gets
persisted — see ``core/storage.py`` for that.

Mode A (same-topology, KDTree nearest-vertex) and Mode B (cross-topology,
BVH nearest-surface triangle/barycentric projection) are both
implemented. ``detect_bind_mode`` implements the auto-detection heuristic
from ARCHITECTURE.md sections 2/6 (vertex-count match -> Mode A, else
Mode B); ``operators/op_bind.py`` is what wires that (plus the
user-facing override) to an actual bind call.
"""

from dataclasses import dataclass

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

MODE_A = 'A'
MODE_B = 'B'


@dataclass
class ModeABindResult:
    """One entry per garment vertex, in vertex-index order."""

    body_vertex_index: list
    normal_offset: list
    tangent_offset: list
    bitangent_offset: list


@dataclass
class ModeBBindResult:
    """One entry per garment vertex, in vertex-index order.

    ``barycentric`` and ``tangent_offset_2d`` are lists of 3-tuples /
    2-tuples respectively (component order matches the attribute layout
    in ``core/storage.py``).
    """

    triangle_index: list
    barycentric: list
    normal_offset: list
    tangent_offset_2d: list


def _local_frame(normal):
    """Build a deterministic orthonormal (normal, tangent, bitangent) frame.

    The same construction is reused at fit time from the (possibly
    shape-key-changed) body vertex's new normal, so the frame rotates
    along with the body's deformation instead of needing its own stored
    tangent — that's what makes a Mode A binding "reapply correctly when
    the body's shape changes via shape keys" per ARCHITECTURE.md.

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


def _world_space_positions_and_normals(obj):
    """Evaluated (modifiers applied), world-space vertex positions/normals."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()

    matrix = obj.matrix_world
    normal_matrix = matrix.inverted_safe().transposed().to_3x3()

    positions = [matrix @ v.co for v in mesh.vertices]
    normals = [(normal_matrix @ v.normal).normalized() for v in mesh.vertices]

    eval_obj.to_mesh_clear()
    return positions, normals


def bind_mode_a(garment_obj, source_body_obj):
    """Compute a Mode A (same-topology) binding.

    For every garment vertex (evaluated, world space), finds the
    nearest source-body vertex via a KDTree nearest-vertex search (per
    ARCHITECTURE.md section 4) and stores the garment vertex's position
    as a normal/tangent/bitangent delta relative to that body vertex's
    local frame, plus the body vertex's index.

    Returns a :class:`ModeABindResult` with one entry per garment
    vertex, in vertex-index order.
    """
    body_positions, body_normals = _world_space_positions_and_normals(source_body_obj)
    if not body_positions:
        raise ValueError(f"Source body '{source_body_obj.name}' has no vertices.")

    kd = KDTree(len(body_positions))
    for i, co in enumerate(body_positions):
        kd.insert(co, i)
    kd.balance()

    garment_positions, _ = _world_space_positions_and_normals(garment_obj)

    body_vertex_index = []
    normal_offset = []
    tangent_offset = []
    bitangent_offset = []

    for garment_co in garment_positions:
        _, body_index, _ = kd.find(garment_co)
        body_co = body_positions[body_index]
        normal, tangent, bitangent = _local_frame(body_normals[body_index])

        delta = garment_co - body_co
        body_vertex_index.append(body_index)
        normal_offset.append(delta.dot(normal))
        tangent_offset.append(delta.dot(tangent))
        bitangent_offset.append(delta.dot(bitangent))

    return ModeABindResult(
        body_vertex_index=body_vertex_index,
        normal_offset=normal_offset,
        tangent_offset=tangent_offset,
        bitangent_offset=bitangent_offset,
    )


def _world_space_triangles(obj):
    """Evaluated, world-space (vertex_positions, triangle_vertex_indices).

    ``triangle_vertex_indices`` is a list of ``(a, b, c)`` index tuples
    into ``vertex_positions``, taken from the mesh's triangulated
    ``loop_triangles`` (built even for a quad/ngon mesh) so every entry
    is an actual 3-vertex triangle suitable for barycentric coordinates.
    The list's order/indexing matches what a BVH built via
    ``BVHTree.FromPolygons(vertex_positions, triangle_vertex_indices)``
    reports back as its nearest-hit "polygon" index — that's what makes
    a stored ``triangle_index`` reproducible: recomputing
    ``loop_triangles`` on the (possibly different) body at read time and
    indexing into it the same way reconstructs the same triangle.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    mesh.calc_loop_triangles()

    matrix = obj.matrix_world
    positions = [matrix @ v.co for v in mesh.vertices]
    triangles = [tuple(lt.vertices) for lt in mesh.loop_triangles]

    eval_obj.to_mesh_clear()
    return positions, triangles


def _triangle_frame(a, b, c):
    """Deterministic orthonormal (normal, tangent, bitangent) frame for a triangle.

    Derived purely from the triangle's own vertices (edge ``a->b`` as the
    tangent axis, face normal via cross product) rather than an external
    reference — the same construction can be reproduced at fit time from
    just the (target-body) triangle's vertices, with no need to store a
    tangent separately, mirroring how Mode A's ``_local_frame`` is
    reproducible from just a body vertex normal.

    Falls back to :func:`_local_frame`'s arbitrary-reference construction
    for a degenerate (zero-area) triangle so this never raises/divides by
    zero on garbage input.
    """
    edge_ab = b - a
    edge_ac = c - a
    normal = edge_ab.cross(edge_ac)

    if normal.length_squared < 1e-12 or edge_ab.length_squared < 1e-12:
        return _local_frame(Vector((0.0, 0.0, 1.0)))

    normal.normalize()
    tangent = edge_ab.normalized()
    bitangent = normal.cross(tangent)
    return normal, tangent, bitangent


def _barycentric_weights(p, a, b, c):
    """Barycentric weights ``(u, v, w)`` of point ``p`` w.r.t. triangle ``a, b, c``.

    Standard area-ratio formula (assumes ``p`` lies in the triangle's
    plane, which the BVH nearest-surface hit point always does — on
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


def bind_mode_b(garment_obj, source_body_obj):
    """Compute a Mode B (cross-topology) binding.

    For every garment vertex (evaluated, world space), uses
    ``mathutils.bvhtree.BVHTree.FromObject``-equivalent nearest-surface
    projection (built via ``BVHTree.FromPolygons`` over the source
    body's triangulated ``loop_triangles``, per ARCHITECTURE.md section
    2) to find the closest point on the source body's surface, then
    stores that triangle's index, the hit point's barycentric weights
    within it, a signed ``normal_offset`` (distance off the surface
    along the triangle's own normal), and a 2D ``tangent_offset``
    in-plane component (the residual when the closest point falls on a
    triangle edge/vertex rather than its interior, which is what keeps
    misassignment near seams/thin geometry from silently losing
    position). Because ``(normal, tangent, bitangent)`` is an orthonormal
    basis, ``hit_point + normal_offset*normal + tangent_offset_2d ·
    (tangent, bitangent)`` reconstructs the exact original garment
    vertex position — see :func:`reconstruct_mode_b_position`.

    Returns a :class:`ModeBBindResult` with one entry per garment
    vertex, in vertex-index order.
    """
    body_positions, body_triangles = _world_space_triangles(source_body_obj)
    if not body_positions:
        raise ValueError(f"Source body '{source_body_obj.name}' has no vertices.")
    if not body_triangles:
        raise ValueError(
            f"Source body '{source_body_obj.name}' has no triangulatable faces."
        )

    bvh = BVHTree.FromPolygons(body_positions, body_triangles)

    garment_positions, _ = _world_space_positions_and_normals(garment_obj)

    triangle_index = []
    barycentric = []
    normal_offset = []
    tangent_offset_2d = []

    for garment_co in garment_positions:
        hit_location, _hit_normal, hit_tri_index, _hit_distance = bvh.find_nearest(
            garment_co
        )
        if hit_tri_index is None:
            raise ValueError(
                f"No nearest surface point found on '{source_body_obj.name}' "
                "for a garment vertex."
            )

        tri = body_triangles[hit_tri_index]
        a, b, c = body_positions[tri[0]], body_positions[tri[1]], body_positions[tri[2]]
        normal, tangent, bitangent = _triangle_frame(a, b, c)
        u, v, w = _barycentric_weights(hit_location, a, b, c)

        delta = garment_co - hit_location
        triangle_index.append(hit_tri_index)
        barycentric.append((u, v, w))
        normal_offset.append(delta.dot(normal))
        tangent_offset_2d.append((delta.dot(tangent), delta.dot(bitangent)))

    return ModeBBindResult(
        triangle_index=triangle_index,
        barycentric=barycentric,
        normal_offset=normal_offset,
        tangent_offset_2d=tangent_offset_2d,
    )


def reconstruct_mode_b_position(body_obj, triangle_index, barycentric, normal_offset, tangent_offset_2d):
    """Reconstruct a garment vertex's world position from a Mode B binding entry.

    ``body_obj`` supplies the (evaluated, world-space, triangulated)
    surface the binding is being re-evaluated against — the source body
    at bind time, or a different target body at fit time. Recomputes the
    triangle frame the same deterministic way :func:`bind_mode_b` does,
    so this is exact (to floating point) when ``body_obj`` is the same
    body the binding was computed against.
    """
    body_positions, body_triangles = _world_space_triangles(body_obj)
    tri = body_triangles[triangle_index]
    a, b, c = body_positions[tri[0]], body_positions[tri[1]], body_positions[tri[2]]
    normal, tangent, bitangent = _triangle_frame(a, b, c)

    u, v, w = barycentric
    hit_location = a * u + b * v + c * w

    tangent_u, tangent_v = tangent_offset_2d
    return hit_location + normal * normal_offset + tangent * tangent_u + bitangent * tangent_v


def detect_bind_mode(source_body_obj, target_body_obj):
    """Auto-detect Mode A vs. Mode B per ARCHITECTURE.md sections 2/6.

    Mode A (same-topology, cheap and exact) is preferred when a declared
    target body is available and shares the source body's vertex count;
    otherwise Mode B (cross-topology, BVH nearest-surface projection) is
    used. With no target body declared yet, there is nothing to compare
    topology against, so this defaults to Mode A (matches the prior
    Mode-A-only card's behavior when Bind is used before Target Body is
    set).

    This is a vertex-*count* heuristic only (matching ARCHITECTURE.md
    section 7's noted soft spot: two unrelated meshes that happen to
    share a vertex count could be misclassified) — the bind-mode
    override property exists specifically so a user can force the
    correct mode when that coincidence occurs.
    """
    if target_body_obj is None or target_body_obj.type != 'MESH':
        return MODE_A

    if len(source_body_obj.data.vertices) == len(target_body_obj.data.vertices):
        return MODE_A
    return MODE_B
