"""Mode A + Mode B bind computation.

Per ARCHITECTURE.md section 2. This module is pure logic operating on
mesh data (evaluated, world-space vertex positions/normals) so it is
testable outside the UI; it has no knowledge of how a bind result gets
persisted — see ``core/storage.py`` for that.

Only Mode A (same-topology) ships with this card. Mode B
(cross-topology, BVH triangle/barycentric projection) is not
implemented yet.
"""

from dataclasses import dataclass

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree


@dataclass
class ModeABindResult:
    """One entry per garment vertex, in vertex-index order."""

    body_vertex_index: list
    normal_offset: list
    tangent_offset: list
    bitangent_offset: list


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
