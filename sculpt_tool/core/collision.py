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

Interpenetration test: for each fitted position, ``BVHTree.find_nearest``
against the target body's (evaluated, world-space, triangulated) surface
gives the nearest surface point and that triangle's face normal. The sign
of ``(vertex - nearest_point) . normal`` distinguishes inside from
outside — this assumes the target body has consistent outward-facing
normals, the same assumption ``core.binding``'s Mode B correspondence
already relies on for its own normal-offset sign, so nothing new is being
asked of the input meshes.

Only a vertex found to be strictly inside the body is moved (pushed to
``nearest_point + normal * collision_margin``); a vertex already outside
is returned completely unchanged — the exact same value, not a
recomputed copy — no matter how close to the surface it sits. A
"clearance top-up" for near-but-not-interpenetrating vertices is
explicitly out of scope, matching the card's literal "any interpenetrating
vertex" wording and keeping the pass from moving vertices it doesn't need
to.

The BVH is built once per call (not once per garment vertex), so a single
``resolve_collisions`` call stays cheap even at tens-of-thousands-of-body-
vertex scale — see ARCHITECTURE.md section 7's performance risk note.
Batch-scale optimization (vectorized NumPy bulk access across many target
bodies) is explicitly out of scope for this card, per ARCHITECTURE.md
section 8.
"""

from mathutils.bvhtree import BVHTree

from . import binding


def resolve_collisions(fitted_positions, target_body_obj, collision_margin):
    """Push any garment vertex found inside ``target_body_obj`` back out.

    ``fitted_positions`` is a list of world-space ``Vector`` positions, one
    per garment vertex, in vertex-index order (e.g.
    ``core.solver.project_garment``'s output). Returns a new list of the
    same length and order: a vertex already outside the body is passed
    through completely unchanged; an interpenetrating vertex is replaced
    with a position on the body's surface offset outward by
    ``collision_margin`` along that surface point's normal.

    Raises ``ValueError`` if ``target_body_obj`` has no triangulatable
    faces to build a BVH from (mirrors ``core.solver.project_mode_b``'s
    handling of the same situation).
    """
    target_positions, target_triangles = binding._world_space_triangles(target_body_obj)
    if not target_positions or not target_triangles:
        raise ValueError(
            f"Target body '{target_body_obj.name}' has no triangulatable faces."
        )

    bvh = BVHTree.FromPolygons(target_positions, target_triangles)

    resolved = []
    for co in fitted_positions:
        hit_location, hit_normal, hit_tri_index, _hit_distance = bvh.find_nearest(co)
        if hit_tri_index is None:
            # No nearest surface point found (e.g. a degenerate/empty
            # BVH) -- leave the vertex exactly as the projection step
            # produced it rather than guessing at a push-out direction.
            resolved.append(co)
            continue

        is_inside = (co - hit_location).dot(hit_normal) < 0.0
        if not is_inside:
            resolved.append(co)
            continue

        normal = hit_normal.normalized()
        resolved.append(hit_location + normal * collision_margin)

    return resolved
