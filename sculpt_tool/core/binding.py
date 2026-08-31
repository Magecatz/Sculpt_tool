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
    """One entry per garment vertex, in vertex-index order (except
    ``source_vertex_count``, one value for the whole result).

    ``source_vertex_count`` (Part C, bind-time-freeze card) is the number
    of evaluated source-body vertices at bind time -- stored via
    ``core.storage.PROP_SOURCE_VERTEX_COUNT`` so
    ``core.solver.project_mode_a`` can refuse outright, at fit time, when
    the target body's vertex count doesn't match it (closing the
    no-Target-Body-set trap: auto-detect used to default to Mode A with
    nothing to compare topology against, and the old per-index
    out-of-range guard alone stays silent whenever the target body
    happens to have MORE vertices than the source body did).
    """

    body_vertex_index: list
    normal_offset: list
    tangent_offset: list
    bitangent_offset: list
    source_vertex_count: int


@dataclass
class ModeBBindResult:
    """One entry per garment vertex, in vertex-index order (except
    ``source_bind_matrix``, one value for the whole result).

    ``barycentric`` and ``tangent_offset_2d`` are lists of 3-tuples /
    2-tuples respectively (component order matches the attribute layout
    in ``core/storage.py``).

    ``source_anchor_local``/``source_bind_matrix`` (Part A, bind-time-
    freeze card) are the bind-time-frozen reference this module's
    docstring describes: the same BVH nearest-surface hit point used to
    compute ``normal_offset``/``tangent_offset_2d``, expressed in the
    SOURCE BODY's own local object space, plus the source body's
    ``matrix_world`` at that same moment. Together they let
    ``core.solver.project_mode_b`` reconstruct the bind-time anchor
    (``source_bind_matrix @ source_anchor_local[i]``) at fit time with NO
    read of the source body's mesh at all -- ``triangle_index``/
    ``barycentric`` above are retained only as diagnostics from here on,
    since indices into the source body's OWN triangulation have no
    fit-time meaning against a different (target) body's triangle list
    (see :func:`bind_mode_b`'s docstring) and are no longer needed now
    that the anchor itself is stored directly.
    """

    triangle_index: list
    barycentric: list
    normal_offset: list
    tangent_offset_2d: list
    source_anchor_local: list
    source_bind_matrix: object


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
        source_vertex_count=len(body_positions),
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
    project_mode_b`` re-evaluates the frozen bind-time anchor against a
    *different* (target) body instead, per that module's docstring).

    Also computes (Part A, bind-time freeze card) ``source_anchor_local``
    — ``hit_point`` expressed in the source body's own LOCAL object
    space, via the source body's ``matrix_world`` AT THIS MOMENT — plus
    that same frozen ``matrix_world`` as ``source_bind_matrix``. This is
    what ``core.solver.project_mode_b`` uses at fit time instead of
    re-deriving ``hit_point`` from ``triangle_index``/``barycentric``
    against the source body's mesh: ``triangle_index``/``barycentric``
    are still computed and returned here, but are diagnostics only from
    this card on (see :class:`ModeBBindResult`'s docstring) — the source
    body's mesh is never read again after this call.

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

    # Part A (bind-time freeze): snapshot the source body's world matrix
    # now, at bind time, and use its inverse to express every anchor in
    # the source body's own LOCAL space. This is the value
    # core.solver.project_mode_b will multiply back by this same
    # (frozen, stored) matrix at fit time -- never anything read from the
    # source body again -- so an edit/reshape/rename/delete of the source
    # body after bind cannot change or break a Mode B fit.
    source_matrix_world = source_body_obj.matrix_world.copy()
    source_matrix_inverse = source_matrix_world.inverted_safe()

    triangle_index = []
    barycentric = []
    normal_offset = []
    tangent_offset_2d = []
    source_anchor_local = []

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
        source_anchor_local.append(source_matrix_inverse @ hit_location)

    return ModeBBindResult(
        triangle_index=triangle_index,
        barycentric=barycentric,
        normal_offset=normal_offset,
        tangent_offset_2d=tangent_offset_2d,
        source_anchor_local=source_anchor_local,
        source_bind_matrix=source_matrix_world,
    )


def detect_bind_mode(source_body_obj, target_body_obj):
    """Auto-detect Mode A vs. Mode B per ARCHITECTURE.md sections 2/6.

    Mode A (same-topology, cheap and exact) is preferred when a declared
    target body shares the source body's vertex count; otherwise Mode B
    (cross-topology, BVH nearest-surface projection) is used.

    Raises ``ValueError`` if no target body is declared yet (Part C,
    bind-time-freeze card — previously this silently defaulted to Mode A
    with nothing to compare topology against, which is exactly the "Mode
    A no-target trap": the UI panel lays out Source Body under Binding
    and Target Body below it under Fit, actively inviting a Bind before
    Target Body is set, and a Mode A binding built that way still fits
    "successfully" against ANY later-declared target body with at least
    as many vertices as the source body — silently wrong, no error, no
    warning, since the per-index fit-time guard only ever caught a
    target with FEWER vertices). Auto-detect has nothing to auto-detect
    against without a target, so it now refuses outright rather than
    guessing; ``operators/op_bind.py`` reports this as a normal bind
    error. The ``'MODE_A'``/``'MODE_B'`` override still bypasses this
    function entirely, per section 6's escape hatch, and is unaffected.

    This is otherwise a vertex-*count* heuristic only (matching
    ARCHITECTURE.md section 7's noted soft spot: two unrelated meshes
    that happen to share a vertex count could be misclassified) — the
    bind-mode override property exists specifically so a user can force
    the correct mode when that coincidence occurs.
    """
    if target_body_obj is None or target_body_obj.type != 'MESH':
        raise ValueError(
            "Auto-Detect needs a Target Body to compare topology against "
            "before choosing Mode A or B -- set Target Body first, or "
            "force a Bind Mode override, before Bind."
        )

    if len(source_body_obj.data.vertices) == len(target_body_obj.data.vertices):
        return MODE_A
    return MODE_B
