"""BVH-based penetration test + push-out.

Per ARCHITECTURE.md section 3, step 2: given the garment's post-projection
(fitted) world-space vertex positions and a target body object, test each
vertex for interpenetration with the body and push any interpenetrating
vertex out along the local surface normal so it clears the body surface by
at least ``collision_margin``. Runs after ``core.solver``'s project step
and before ``operators/op_fit.py``'s Shape Key bake — pure logic operating
on mesh data (testable outside the UI), matching ``core/solver.py`` and
``core/binding.py``'s convention of separating pure math from the
Blender-facing operator layer.

Two independent tests are run per vertex, in order:

1. **Local nearest-point / normal-sign test** (unchanged from the
   original implementation): ``BVHTree.find_nearest`` against the target
   body's (evaluated, world-space, triangulated) surface gives the
   nearest surface point and that triangle's face normal. The sign of
   ``(vertex - nearest_point) . normal`` distinguishes inside from
   outside — this assumes the target body has consistent outward-facing
   normals, the same assumption ``core.binding``'s Mode B correspondence
   already relies on for its own normal-offset sign. This test correctly
   handles ordinary (non-tunneled) interpenetration: a vertex that has
   pushed a short way into the body reads as "inside" relative to the
   nearest wall and gets pushed back out from there.

2. **Anchor-to-fitted tunneling test** (new — fixes ARCHITECTURE.md
   section 7's "deep pass-through / tunneling not detected" blind spot):
   test (1) is a point-containment test on the fitted position alone, and
   a vertex that has tunneled all the way through thin geometry (e.g. a
   wrist/ankle) and now sits beyond the FAR wall is genuinely, correctly
   outside the body by that test — there is no way to call that position
   "inside" without it being a wrong answer, so no amount of making test
   (1) smarter (multi-ray parity, winding number, etc.) can catch this
   case; it is asking the position a question it cannot answer about
   itself. What's needed instead is a reference the position can be
   checked *against*: ``core.solver.ProjectionResult.anchor_positions``/
   ``anchor_normals`` (per an Architect consult on this card) give
   exactly that — for each garment vertex, the point on the target body's
   surface its binding offset was actually measured from, i.e. the
   surface it is supposed to be hugging, independent of how far the
   offset then carried it. A vertex has tunneled if the straight segment
   from its anchor to its fitted position crosses the target body's own
   surface at all: that can only happen if the offset carried the vertex
   through solid material rather than out into open space. Implemented
   as one bounded ``BVHTree.ray_cast`` per vertex (only run when test (1)
   didn't already flag the vertex), reusing the same BVH — no separate
   solid/parity pass, no extra tree builds. A vertex caught this way is
   pushed to ``anchor_position + anchor_normal * collision_margin`` (the
   near surface, not whatever test (1)'s own nearest-point query would
   have found for the far side).

   Known limitation, accepted as out of scope for this card (the
   concave-region push-out-direction half of ARCHITECTURE.md section 7,
   deprioritized by the Architect): the anchor-to-fitted segment can, on
   sufficiently convoluted/bumpy geometry, graze an unrelated nearby
   fold of the body surface that has nothing to do with the vertex's own
   offset direction, producing a false-positive tunneling detection. This
   mirrors the concave push-out-direction issue already flagged as a
   known blind spot rather than introducing a new one, and does not
   affect the simple/smooth-body cases this fix is verified against.

Only a vertex found interpenetrating (by either test) is moved; a vertex
that fails both is returned completely unchanged — the exact same value,
not a recomputed copy — no matter how close to the surface it sits. A
"clearance top-up" for near-but-not-interpenetrating vertices is
explicitly out of scope, matching the card's literal "any interpenetrating
vertex" wording and keeping the pass from moving vertices it doesn't need
to.

The BVH is built once per call (not once per garment vertex, and not
separately for the two tests), so a single ``resolve_collisions`` call
stays cheap even at tens-of-thousands-of-body-vertex scale — see
ARCHITECTURE.md section 7's performance risk note. Batch-scale
optimization (vectorized NumPy bulk access across many target bodies) is
explicitly out of scope for this card, per ARCHITECTURE.md section 8.
"""

from mathutils.bvhtree import BVHTree

# Minimum anchor-to-fitted travel distance worth testing for tunneling.
# Below this, the vertex barely moved off its anchor at all, so there is
# no meaningful segment to cross anything with -- skip the extra ray_cast
# rather than spend it on noise-level displacement.
_MIN_TUNNEL_TEST_DISTANCE = 1e-9


def resolve_collisions(
    fitted_positions,
    anchor_positions,
    anchor_normals,
    target_positions,
    target_triangles,
    collision_margin,
):
    """Push any garment vertex found inside the target body back out.

    ``fitted_positions`` is a list of world-space ``Vector`` positions, one
    per garment vertex, in vertex-index order (``core.solver.
    ProjectionResult.fitted_positions``). ``anchor_positions``/
    ``anchor_normals`` are that same ``ProjectionResult``'s per-vertex
    surface reference point/normal -- the point on the target body each
    fitted position's offset was actually measured from -- used by the
    tunneling test described in the module docstring; all three lists
    must be the same length, in the same vertex-index order.

    ``target_positions``/``target_triangles`` are the target body's
    evaluated, world-space, triangulated surface --
    ``core.binding._world_space_triangles(target_body_obj)``'s output.
    This function takes plain geometry data rather than a Blender object
    (the caller, ``operators/op_fit.py``, does the ``bpy``-facing
    evaluation) so it is testable with synthetic data and has no ``bpy``
    dependency of its own, matching ``_laplacian_step``/
    ``_barycentric_weights``/``_triangle_frame``/``_local_frame``'s
    convention elsewhere in ``core/``.

    Returns a new list of the same length and order: a vertex found
    interpenetrating (by either the local nearest-point test or the
    anchor-based tunneling test) is replaced with a position on the
    relevant surface offset outward by ``collision_margin`` along that
    surface point's normal; every other vertex is passed through
    completely unchanged.

    Raises ``ValueError`` if ``target_positions``/``target_triangles`` is
    empty (mirrors ``core.solver.project_mode_b``'s handling of the same
    situation on the caller side).
    """
    if not target_positions or not target_triangles:
        raise ValueError("Target body has no triangulatable faces.")

    bvh = BVHTree.FromPolygons(target_positions, target_triangles)

    resolved = []
    for co, anchor, anchor_normal in zip(fitted_positions, anchor_positions, anchor_normals):
        hit_location, hit_normal, hit_tri_index, _hit_distance = bvh.find_nearest(co)
        if hit_tri_index is None:
            # No nearest surface point found (e.g. a degenerate/empty
            # BVH) -- leave the vertex exactly as the projection step
            # produced it rather than guessing at a push-out direction.
            resolved.append(co)
            continue

        is_inside = (co - hit_location).dot(hit_normal) < 0.0
        if is_inside:
            normal = hit_normal.normalized()
            resolved.append(hit_location + normal * collision_margin)
            continue

        # Test (1) says outside. Check whether it got there by tunneling
        # through the body from its own anchor point.
        to_fitted = co - anchor
        distance = to_fitted.length
        if distance <= _MIN_TUNNEL_TEST_DISTANCE:
            resolved.append(co)
            continue

        direction = to_fitted / distance
        normal_at_anchor = anchor_normal.normalized()
        # Nudge the ray's start a hair along the direction of travel so it
        # doesn't immediately self-intersect the anchor's own triangle
        # (the anchor sits exactly on the target surface).
        epsilon = min(distance * 1e-6, 1e-6)
        origin = anchor + direction * epsilon
        remaining_distance = distance - epsilon

        tunnel_hit_location, _tunnel_hit_normal, tunnel_hit_index, _tunnel_hit_distance = (
            bvh.ray_cast(origin, direction, remaining_distance)
        )
        if tunnel_hit_index is None:
            resolved.append(co)
            continue

        # The segment from the anchor (known to be on the correct/near
        # surface) to the fitted position crosses the body's own surface
        # -- the offset carried this vertex through solid material.
        # Correct it back to the anchor's surface, not to whatever
        # test (1)'s nearest-point query found near the far side.
        resolved.append(anchor + normal_at_anchor * collision_margin)

    return resolved
