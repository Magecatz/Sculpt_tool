"""Project step: apply binding to a target body.

Per ARCHITECTURE.md section 3, step 1: re-evaluate each garment vertex's
stored binding against a target body's current geometry, producing a raw
fitted world-space position per garment vertex. Step 4 (the Shape Key
bake) is done by ``operators/op_fit.py`` using this module's output; this
module is pure logic operating on mesh data (testable outside the UI),
matching ``core/binding.py``'s convention.

Mode A (same-topology): direct index lookup, but the local
(normal, tangent, bitangent) frame is rebuilt from the TARGET body's
CURRENT evaluated vertex normal — not the source body's, and not a
frame cached from bind time — so the fit follows however the target
body has since moved or deformed (e.g. via its own shape keys). This is
what makes Fit meaningfully different from just re-copying the bind-time
offset, and mirrors ``core.binding.bind_mode_a``'s own frame
construction (``binding._local_frame``), reused here so both are built
the exact same deterministic way.

Mode B (cross-topology): resolved per an Architect consult on this card
(Bear PR Process board, card 7601dd7f-8c5d-4484-96f7-4be9cfe6cef3).
``triangle_index``/``barycentric`` are indices into the SOURCE body's
own triangulation (see ``binding.bind_mode_b``) and have no meaning
against a different-topology target body's unrelated triangle list, so
they cannot be looked up directly against the target. Instead:

  1. Reconstruct the bind-time anchor point on the SOURCE body only
     (``triangle_index``/``barycentric`` against the source body's own
     triangulation — stable, since source body geometry doesn't change
     between bind and fit).
  2. Find the nearest-surface point to that anchor on the TARGET body's
     BVH — this is the literal "re-evaluated against the target body's
     BVH at fit time" from ARCHITECTURE.md section 2.
  3. Apply the stored ``normal_offset``/``tangent_offset_2d`` relative to
     the NEW local frame found on the target body at that hit point,
     built the same deterministic way bind time does
     (``binding._triangle_frame``).

This requires the source body object to still exist in the scene
(looked up by name via ``storage.PROP_SOURCE_BODY_NAME``) to serve as
the stable reference for step 1. Per the Architect: acceptable for v1
given the current schema, but fragile (a renamed/deleted source body, or
one edited after bind, silently breaks fitting) — flagged as a follow-up
card (persist the anchor in the source body's own local object space at
bind time instead) rather than blocking this one.

Both modes also compute, per garment vertex, the point on the TARGET
body's surface the stored offset is actually applied from (Mode A:
``target_positions[body_index]``; Mode B: the ``find_nearest`` hit on the
target BVH) before adding the offset -- this "anchor" is returned
alongside the fitted position (see :class:`ProjectionResult`) rather than
discarded, per an Architect consult on card
``c9ff95a5-6269-4c82-8789-08113a9dc9d3``: it's the one non-local
reference point that's unconditionally on the correct (near) surface by
construction, and ``core.collision.resolve_collisions`` uses it to catch
a garment vertex that has tunneled all the way through thin geometry --
something no test of the fitted position in isolation can detect, since
such a vertex is genuinely outside the body from its own local point of
view.
"""

from dataclasses import dataclass

import bpy
from mathutils.bvhtree import BVHTree

from . import binding, storage


@dataclass
class ProjectionResult:
    """Per-garment-vertex projection output, in vertex-index order.

    ``anchor_positions``/``anchor_normals`` are the point-on-target-body
    surface (and that point's normal) each vertex's stored offset was
    applied from -- i.e. the surface point this garment vertex is meant
    to hug, before the offset carries it away by however much. This is
    NOT the same as "the fitted position's own nearest surface point":
    it's a reference that stays correct even when the fitted position
    itself has ended up somewhere the offset math didn't intend (e.g.
    tunneled through thin geometry). See ``core.collision.
    resolve_collisions``, the sole consumer.
    """

    fitted_positions: list
    anchor_positions: list
    anchor_normals: list


def _resolve_source_body(binding_info):
    """Look up the Mode B binding's source body object by its stored name.

    Raises ``ValueError`` (rather than silently producing a garbage fit)
    if the source body is missing or no longer a mesh — see the module
    docstring's note on this being a known v1 limitation.
    """
    name = binding_info.get("source_body_name")
    obj = bpy.data.objects.get(name) if name else None
    if obj is None or obj.type != 'MESH':
        raise ValueError(
            f"Mode B binding's source body '{name}' was not found in the "
            "scene (renamed or deleted?). It is required at fit time to "
            "reconstruct the bind-time reference point — re-bind against "
            "a source body that still exists to fix this."
        )
    return obj


def project_mode_a(garment_obj, target_body_obj, offset_scale=1.0):
    """Re-evaluate a Mode A binding against ``target_body_obj``.

    Returns a :class:`ProjectionResult`.
    """
    info = storage.read_mode_a_binding(garment_obj)
    if info is None:
        raise ValueError(f"'{garment_obj.name}' has no Mode A binding to fit.")

    target_positions, target_normals = binding._world_space_positions_and_normals(
        target_body_obj
    )
    if not target_positions:
        raise ValueError(f"Target body '{target_body_obj.name}' has no vertices.")

    body_vertex_index = info["body_vertex_index"]
    normal_offset = info["normal_offset"]
    tangent_offset = info["tangent_offset"]
    bitangent_offset = info["bitangent_offset"]

    target_vertex_count = len(target_positions)
    fitted = []
    anchor_positions = []
    anchor_normals = []
    for i, body_index in enumerate(body_vertex_index):
        if body_index >= target_vertex_count:
            raise ValueError(
                f"Mode A binding references target-body vertex {body_index}, "
                f"but '{target_body_obj.name}' only has {target_vertex_count} "
                "vertices — Mode A requires the target body to share the "
                "source body's topology."
            )
        body_co = target_positions[body_index]
        normal, tangent, bitangent = binding._local_frame(target_normals[body_index])

        offset_vec = (
            normal * normal_offset[i]
            + tangent * tangent_offset[i]
            + bitangent * bitangent_offset[i]
        )
        fitted.append(body_co + offset_vec * offset_scale)
        anchor_positions.append(body_co)
        anchor_normals.append(normal)

    return ProjectionResult(
        fitted_positions=fitted,
        anchor_positions=anchor_positions,
        anchor_normals=anchor_normals,
    )


def project_mode_b(garment_obj, target_body_obj, offset_scale=1.0):
    """Re-evaluate a Mode B binding against ``target_body_obj``.

    See the module docstring for the algorithm. Returns a
    :class:`ProjectionResult`.
    """
    info = storage.read_mode_b_binding(garment_obj)
    if info is None:
        raise ValueError(f"'{garment_obj.name}' has no Mode B binding to fit.")

    source_body_obj = _resolve_source_body(info)

    source_positions, source_triangles = binding._world_space_triangles(source_body_obj)
    if not source_positions or not source_triangles:
        raise ValueError(
            f"Source body '{source_body_obj.name}' has no triangulatable faces."
        )

    target_positions, target_triangles = binding._world_space_triangles(target_body_obj)
    if not target_positions or not target_triangles:
        raise ValueError(
            f"Target body '{target_body_obj.name}' has no triangulatable faces."
        )

    target_bvh = BVHTree.FromPolygons(target_positions, target_triangles)

    triangle_index = info["triangle_index"]
    barycentric = info["barycentric"]
    normal_offset = info["normal_offset"]
    tangent_offset_2d = info["tangent_offset_2d"]

    source_triangle_count = len(source_triangles)
    fitted = []
    anchor_positions = []
    anchor_normals = []
    for i, tri_idx in enumerate(triangle_index):
        if tri_idx >= source_triangle_count:
            raise ValueError(
                f"Mode B binding references source-body triangle {tri_idx}, "
                f"but '{source_body_obj.name}' only has "
                f"{source_triangle_count} triangles now — has its mesh "
                "changed since bind?"
            )

        tri = source_triangles[tri_idx]
        a, b, c = (
            source_positions[tri[0]],
            source_positions[tri[1]],
            source_positions[tri[2]],
        )
        u, v, w = barycentric[i]
        source_anchor = a * u + b * v + c * w

        hit_location, _hit_normal, hit_tri_index, _hit_distance = target_bvh.find_nearest(
            source_anchor
        )
        if hit_tri_index is None:
            raise ValueError(
                f"No nearest surface point found on '{target_body_obj.name}' "
                "for a Mode B garment vertex."
            )

        tri2 = target_triangles[hit_tri_index]
        a2, b2, c2 = (
            target_positions[tri2[0]],
            target_positions[tri2[1]],
            target_positions[tri2[2]],
        )
        normal2, tangent2, bitangent2 = binding._triangle_frame(a2, b2, c2)

        tangent_u, tangent_v = tangent_offset_2d[i]
        offset_vec = (
            normal2 * normal_offset[i]
            + tangent2 * tangent_u
            + bitangent2 * tangent_v
        )
        fitted.append(hit_location + offset_vec * offset_scale)
        anchor_positions.append(hit_location)
        anchor_normals.append(normal2)

    return ProjectionResult(
        fitted_positions=fitted,
        anchor_positions=anchor_positions,
        anchor_normals=anchor_normals,
    )


def project_garment(garment_obj, target_body_obj, offset_scale=1.0):
    """Re-evaluate ``garment_obj``'s stored binding against ``target_body_obj``.

    Dispatches to :func:`project_mode_a` or :func:`project_mode_b` based
    on the garment's stored bind mode (``storage.PROP_BIND_MODE``).
    Returns a :class:`ProjectionResult` — ready for
    ``operators/op_fit.py`` to pass to ``core.collision.
    resolve_collisions`` and to convert ``.fitted_positions`` to the
    garment's local space for the Shape Key bake.
    """
    mode = garment_obj.get(storage.PROP_BIND_MODE)
    if mode == storage.MODE_A:
        return project_mode_a(garment_obj, target_body_obj, offset_scale)
    elif mode == storage.MODE_B:
        return project_mode_b(garment_obj, target_body_obj, offset_scale)
    else:
        raise ValueError(
            f"'{garment_obj.name}' is not bound (or has an unrecognized "
            "bind mode) — run Bind before Fit."
        )
