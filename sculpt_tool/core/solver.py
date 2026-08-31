"""Project step: apply binding to a target body.

Per ARCHITECTURE.md section 3, step 1: re-evaluate each garment vertex's
stored binding against a target body's current geometry, producing a raw
fitted world-space position per garment vertex. Step 4 (the Shape Key
bake) is done by ``operators/op_fit.py`` (via ``core/pipeline.py``) using
this module's output; this module is pure logic operating on mesh data
(testable outside the UI), matching ``core/binding.py``'s convention.

Mode A (same-topology): direct index lookup, but the local
(normal, tangent, bitangent) frame is rebuilt from the TARGET body's
CURRENT evaluated vertex normal — not the source body's, and not a
frame cached from bind time — so the fit follows however the target
body has since moved or deformed (e.g. via its own shape keys). This is
what makes Fit meaningfully different from just re-copying the bind-time
offset, and mirrors ``core.binding.bind_mode_a``'s own frame
construction (``core.geometry.local_frame``), reused here so both are
built the exact same deterministic way.

Mode B (cross-topology): resolved per an Architect consult on this card
(Bear PR Process board, card 7601dd7f-8c5d-4484-96f7-4be9cfe6cef3), then
reworked by the bind-time-freeze card (Part A) to close the fragility
that resolution left open. ``triangle_index``/``barycentric`` are
indices into the SOURCE body's own triangulation (see
``binding.bind_mode_b``) and have no meaning against a
different-topology target body's unrelated triangle list, so they cannot
be looked up directly against the target — but they are also no longer
how the bind-time anchor is obtained at all (see below), so this is now
a moot point rather than something the fit-time solver has to work
around. Fit time now works as:

  1. Read the FROZEN bind-time anchor stored directly on the garment,
     in the source body's own local object space
     (``storage.ATTR_SOURCE_ANCHOR_LOCAL``), and multiply it back out to
     world space by the source body's ``matrix_world`` AT BIND TIME
     (``storage.PROP_SOURCE_BIND_MATRIX``, likewise frozen). No source
     body object lookup, no source body mesh evaluation, at fit time —
     the source body does not need to still exist in the scene at all.
  2. Find the nearest-surface point to that anchor on the TARGET body's
     BVH — this is the literal "re-evaluated against the target body's
     BVH at fit time" from ARCHITECTURE.md section 2.
  3. Apply the stored ``normal_offset``/``tangent_offset_2d`` relative to
     the NEW local frame found on the target body at that hit point,
     built the same deterministic way bind time does
     (``core.geometry.triangle_frame``).

Before Part A, step 1 instead reconstructed the anchor by re-evaluating
the SOURCE body's mesh at fit time via ``triangle_index``/``barycentric``
— which meant a renamed/deleted source body broke fitting outright, and
an edited/reshaped source body silently changed the fitted result with
no warning (ARCHITECTURE.md section 7, card 089ab86f-4247-42c4-9652-
9d30de33fbdf). Storing the already-computed world-space anchor directly
(frozen, in the source body's own local space) instead of re-deriving it
removes that whole class of failure: ``_resolve_source_body`` and its
error path no longer exist because there is nothing left in this module
that needs to resolve the source body object at all.

Both modes also compute, per garment vertex, the point on the TARGET
body's surface the stored offset is actually applied from (Mode A:
``target_ctx.positions[body_index]``; Mode B: the ``find_nearest`` hit on
the target BVH) before adding the offset -- this "anchor" is returned
alongside the fitted position (see :class:`ProjectionResult`) rather than
discarded, per an Architect consult on card
``c9ff95a5-6269-4c82-8789-08113a9dc9d3``: it's the one non-local
reference point that's unconditionally on the correct (near) surface by
construction, and ``core.collision.resolve_collisions`` uses it to catch
a garment vertex that has tunneled all the way through thin geometry --
something no test of the fitted position in isolation can detect, since
such a vertex is genuinely outside the body from its own local point of
view.

Both ``project_mode_a`` and ``project_mode_b`` take a pre-built
``core.geometry.TargetContext`` (rather than a target body object) so the
target body's evaluated geometry — and, for Mode B, its BVH — is
evaluated/triangulated/built exactly once per fit and shared with
``core.collision``'s two passes, instead of being rebuilt independently
here (Bear PR Process card cd0d1569-36ad-4d79-a82b-6d1115a0bcda; see
``core.geometry.TargetContext``'s docstring and
``core.pipeline.fit_once``, the sole place that builds one). Neither
function takes a ``depsgraph`` any more (Part A removed Mode B's only
use of one — evaluating the source body — so ``project_garment`` no
longer accepts or threads one through either).
"""

from dataclasses import dataclass

from . import geometry, storage


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


def project_mode_a(garment_obj, target_ctx, offset_scale=1.0):
    """Re-evaluate a Mode A binding against ``target_ctx``.

    ``target_ctx`` is a :class:`core.geometry.TargetContext` built once
    per fit (see module docstring). Returns a :class:`ProjectionResult`.

    Part C (bind-time-freeze card): refuses outright, before touching any
    per-vertex index, if ``target_ctx``'s vertex count doesn't match the
    source body's vertex count AT BIND TIME
    (``info["source_vertex_count"]``, ``storage.PROP_SOURCE_VERTEX_COUNT``).
    This closes the "Mode A no-target trap": a binding built with no
    Target Body set (so nothing to compare topology against) previously
    passed silently as long as the eventual target body had at least as
    many vertices as the source body, since the old guard below only ever
    caught an out-of-range index (a target with FEWER vertices) — never a
    same-or-larger target with completely different topology.
    """
    info = storage.read_mode_a_binding(garment_obj)
    if info is None:
        raise ValueError(f"'{garment_obj.name}' has no Mode A binding to fit.")

    target_positions = target_ctx.positions
    target_normals = target_ctx.normals
    target_vertex_count = len(target_positions)

    source_vertex_count = info.get("source_vertex_count")
    if source_vertex_count is not None and source_vertex_count != target_vertex_count:
        raise ValueError(
            f"'{garment_obj.name}' was bound (Mode A) against a source "
            f"body with {source_vertex_count} vertices, but target body "
            f"'{target_ctx.name}' has {target_vertex_count} — Mode A "
            "requires the target body to share the source body's exact "
            "topology (same vertex count/order). Re-bind with the "
            "correct Target Body set, or use Mode B instead."
        )

    body_vertex_index = info["body_vertex_index"]
    normal_offset = info["normal_offset"]
    tangent_offset = info["tangent_offset"]
    bitangent_offset = info["bitangent_offset"]

    fitted = []
    anchor_positions = []
    anchor_normals = []
    for i, body_index in enumerate(body_vertex_index):
        if body_index >= target_vertex_count:
            raise ValueError(
                f"Mode A binding references target-body vertex {body_index}, "
                f"but '{target_ctx.name}' only has {target_vertex_count} "
                "vertices — Mode A requires the target body to share the "
                "source body's topology."
            )
        body_co = target_positions[body_index]
        normal, tangent, bitangent = geometry.local_frame(target_normals[body_index])

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


def project_mode_b(garment_obj, target_ctx, offset_scale=1.0):
    """Re-evaluate a Mode B binding against ``target_ctx``.

    See the module docstring for the algorithm. ``target_ctx`` is a
    :class:`core.geometry.TargetContext` built once per fit. Returns a
    :class:`ProjectionResult`.

    Part A (bind-time freeze): the bind-time anchor comes from
    ``info["source_bind_matrix"] @ info["source_anchor_local"][i]`` —
    both frozen at bind time (``core.binding.bind_mode_b``) — not from
    re-deriving it against the source body's current mesh via
    ``triangle_index``/``barycentric``. No source body object is looked
    up, and no source body mesh is evaluated, here at all: a
    renamed/deleted/edited source body has no effect on this function.
    """
    info = storage.read_mode_b_binding(garment_obj)
    if info is None:
        raise ValueError(f"'{garment_obj.name}' has no Mode B binding to fit.")

    source_bind_matrix = info["source_bind_matrix"]
    source_anchor_local = info["source_anchor_local"]
    if source_bind_matrix is None:
        raise ValueError(
            f"'{garment_obj.name}' has a Mode B binding with no stored "
            "bind-time source-body reference — re-bind to fix this."
        )

    target_positions = target_ctx.positions
    target_triangles = target_ctx.triangles
    target_bvh = target_ctx.bvh

    normal_offset = info["normal_offset"]
    tangent_offset_2d = info["tangent_offset_2d"]

    fitted = []
    anchor_positions = []
    anchor_normals = []
    for i, local_anchor in enumerate(source_anchor_local):
        world_anchor = source_bind_matrix @ local_anchor

        hit_location, _hit_normal, hit_tri_index, _hit_distance = target_bvh.find_nearest(
            world_anchor
        )
        if hit_tri_index is None:
            raise ValueError(
                f"No nearest surface point found on '{target_ctx.name}' "
                "for a Mode B garment vertex."
            )

        tri2 = target_triangles[hit_tri_index]
        a2, b2, c2 = (
            target_positions[tri2[0]],
            target_positions[tri2[1]],
            target_positions[tri2[2]],
        )
        normal2, tangent2, bitangent2 = geometry.triangle_frame(a2, b2, c2)

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


def project_garment(garment_obj, target_ctx, offset_scale=1.0):
    """Re-evaluate ``garment_obj``'s stored binding against ``target_ctx``.

    Dispatches to :func:`project_mode_a` or :func:`project_mode_b` based
    on the garment's stored bind mode (``storage.PROP_BIND_MODE``).
    ``target_ctx`` is a :class:`core.geometry.TargetContext` built once
    per fit (see module docstring). Returns a :class:`ProjectionResult` —
    ready for ``core.pipeline.fit_once`` to pass to
    ``core.collision.resolve_collisions`` and, ultimately, for
    ``operators/op_fit.py`` to convert to the garment's local space for
    the Shape Key bake.

    No longer takes a ``depsgraph`` (Part A, bind-time-freeze card):
    neither projection mode reads any object's mesh at fit time anymore
    — Mode A only needs ``target_ctx`` (built once, up front, by
    ``core.pipeline.fit_once``), and Mode B's former need to
    separately evaluate the source body is gone along with the
    live-source-mesh read it existed to support.
    """
    mode = garment_obj.get(storage.PROP_BIND_MODE)
    if mode == storage.MODE_A:
        return project_mode_a(garment_obj, target_ctx, offset_scale)
    elif mode == storage.MODE_B:
        return project_mode_b(garment_obj, target_ctx, offset_scale)
    else:
        raise ValueError(
            f"'{garment_obj.name}' is not bound (or has an unrecognized "
            "bind mode) — run Bind before Fit."
        )
