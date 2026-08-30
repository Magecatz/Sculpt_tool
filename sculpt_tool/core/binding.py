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

The shared geometry primitives this module used to define privately
(``_local_frame``, ``_triangle_frame``, ``_world_space_positions_and_
normals``, ``_world_space_triangles``) now live in ``core/geometry.py`` as
public functions — ``core/solver.py`` and ``operators/op_fit.py`` were
both already reaching into this module's private API for them (Bear PR
Process card cd0d1569-36ad-4d79-a82b-6d1115a0bcda), which is a sign they
were never really binding.py-internal. ``bind_mode_a``/``bind_mode_b``
now take a ``depsgraph`` parameter (instead of resolving Blender's
current evaluated depsgraph internally) for the same reason
``core/geometry.py``'s functions do — see that module's docstring.
"""

from dataclasses import dataclass

from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from . import geometry

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


def bind_mode_a(garment_obj, source_body_obj, depsgraph):
    """Compute a Mode A (same-topology) binding.

    For every garment vertex (evaluated, world space), finds the
    nearest source-body vertex via a KDTree nearest-vertex search (per
    ARCHITECTURE.md section 4) and stores the garment vertex's position
    as a normal/tangent/bitangent delta relative to that body vertex's
    local frame, plus the body vertex's index.

    ``depsgraph`` is a resolved ``bpy.types.Depsgraph`` (the caller —
    ``operators/op_bind.py`` — obtains it via ``context.
    evaluated_depsgraph_get()``; see ``core/geometry.py``'s module
    docstring for why this module doesn't resolve it itself).

    Returns a :class:`ModeABindResult` with one entry per garment
    vertex, in vertex-index order.
    """
    body_positions, body_normals = geometry.world_space_positions_and_normals(
        source_body_obj, depsgraph
    )
    if not body_positions:
        raise ValueError(f"Source body '{source_body_obj.name}' has no vertices.")

    kd = KDTree(len(body_positions))
    for i, co in enumerate(body_positions):
        kd.insert(co, i)
    kd.balance()

    garment_positions, _ = geometry.world_space_positions_and_normals(
        garment_obj, depsgraph
    )

    body_vertex_index = []
    normal_offset = []
    tangent_offset = []
    bitangent_offset = []

    for garment_co in garment_positions:
        _, body_index, _ = kd.find(garment_co)
        body_co = body_positions[body_index]
        normal, tangent, bitangent = geometry.local_frame(body_normals[body_index])

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


def bind_mode_b(garment_obj, source_body_obj, depsgraph):
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
    vertex position to within floating-point precision — verified by the
    round-trip regression test in ``tests/test_binding.py`` (this
    reconstruction has no production call site of its own; ``core.solver.
    project_mode_b`` re-derives the fitted position against a *different*
    (target) body instead, per that module's docstring).

    ``depsgraph`` is a resolved ``bpy.types.Depsgraph`` — see
    :func:`bind_mode_a`.

    Returns a :class:`ModeBBindResult` with one entry per garment
    vertex, in vertex-index order.
    """
    body_positions, body_triangles = geometry.world_space_triangles(
        source_body_obj, depsgraph
    )
    if not body_positions:
        raise ValueError(f"Source body '{source_body_obj.name}' has no vertices.")
    if not body_triangles:
        raise ValueError(
            f"Source body '{source_body_obj.name}' has no triangulatable faces."
        )

    bvh = BVHTree.FromPolygons(body_positions, body_triangles)

    garment_positions, _ = geometry.world_space_positions_and_normals(
        garment_obj, depsgraph
    )

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
        normal, tangent, bitangent = geometry.triangle_frame(a, b, c)
        u, v, w = geometry.barycentric_weights(hit_location, a, b, c)

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
