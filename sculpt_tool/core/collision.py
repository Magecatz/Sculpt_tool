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

1. **Local nearest-point / normal-sign test**: ``BVHTree.find_nearest``
   against the target body's (evaluated, world-space, triangulated)
   surface gives the nearest surface point and that triangle's face
   normal. The sign of ``(vertex - nearest_point) . normal`` distinguishes
   inside from outside — this assumes the target body has consistent
   outward-facing normals, the same assumption ``core.binding``'s Mode B
   correspondence already relies on for its own normal-offset sign. This
   test correctly handles ordinary (non-tunneled) interpenetration: a
   vertex that has pushed a short way into the body reads as "inside"
   relative to the nearest wall.

   **Push-out direction** (measured residual fixed by this card,
   1e252575-2b86-4ba5-89f7-bcf0ae9685ba — see ARCHITECTURE.md section 7's
   "push-out direction is still unreliable in concave regions" entry): the
   original implementation pushed along the nearest triangle's own face
   normal (``hit_normal``). In a concave pocket (armpit, crotch, under a
   strap, inside a hood) the nearest triangle can belong to a different
   fold of the surface than the one the vertex is actually meant to clear,
   so its face normal can point sideways or even back into the body —
   confirmed by a full-corpus run leaving 50+ residual penetrating
   vertices on 9 of 22 real garments, concentrated in exactly these
   regions. Fixed (per an Architect consult on this card) by pushing along
   ``anchor_normal`` instead — the binding's own per-vertex reference
   direction (``core.solver.ProjectionResult.anchor_normals``), already
   used below for the tunneling test's push-out and unaffected by which
   nearby triangle happens to be geometrically nearest. ``hit_location``
   (the nearest surface point itself) is still used as the position the
   push originates from — only the direction changed.

   A single push is not always enough: pushing a vertex out of one fold
   of a concave pocket along ``anchor_normal`` can still leave it inside
   (or move it into a different piece of the same pocket), since
   ``anchor_normal`` is a single fixed direction and the local geometry
   near the push destination can differ from the geometry near the
   original position. ``_push_out_locally`` therefore re-queries
   (re-runs the nearest-point/normal-sign test) after each push, up to
   ``_MAX_LOCAL_PUSH_ATTEMPTS`` times. If the vertex is still flagged
   inside after that many attempts, it falls back to
   ``anchor_position + anchor_normal * collision_margin`` — the same
   guaranteed-correct near-surface point the tunneling test below already
   relies on (see its own comment for why that point is unconditionally
   safe by construction) — so every vertex this test flags resolves to a
   definite, correct-side answer in bounded time, never an unresolved
   bounce between folds. The bound is small (3) deliberately: collision
   resolution is the cheap side of the pipeline relative to smoothing
   (~0.25s vs. ~4.73s at comparable scale, per ARCHITECTURE.md section 7),
   and only vertices actually flagged as interpenetrating pay for extra
   attempts.

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

   Known limitation, accepted as out of scope for this card: the
   anchor-to-fitted segment can, on sufficiently convoluted/bumpy
   geometry, graze an unrelated nearby fold of the body surface that has
   nothing to do with the vertex's own offset direction, producing a
   false-positive tunneling detection. This is a distinct blind spot from
   test (1)'s push-out-direction issue fixed above (that one was about
   which way to push once a vertex is known to be inside; this one is
   about the ray-cast itself picking up an unrelated surface) and does
   not affect the simple/smooth-body cases this fix is verified against.

A vertex resolved by either test is pushed to a point derived from
``anchor_normal`` (never the local ``hit_normal``) — see test (1)'s
comment above for why, and ``_push_out_locally`` for the bounded
re-query/fallback that guarantees a correct-side answer.

Only a vertex found interpenetrating (by either test) is moved; a vertex
that fails both is returned completely unchanged — the exact same value,
not a recomputed copy — no matter how close to the surface it sits. A
"clearance top-up" for near-but-not-interpenetrating vertices is
explicitly out of scope, matching the card's literal "any interpenetrating
vertex" wording and keeping the pass from moving vertices it doesn't need
to.

``resolve_collisions`` takes a pre-built ``target_bvh`` (a
``mathutils.bvhtree.BVHTree``) rather than raw target-body positions/
triangles, and does not build one itself — the caller
(``core.pipeline.fit_once``) builds it exactly once per fit via
``core.geometry.TargetContext`` and reuses the SAME tree across both
collision passes (the second one runs after smoothing, per
``operators/op_fit.py``'s docstring) and Mode B's own projection step, so
a single fit no longer triangulates/BVH-builds the target body multiple
times over (Bear PR Process card cd0d1569-36ad-4d79-a82b-6d1115a0bcda —
previously this function built its own BVH from ``target_positions``/
``target_triangles`` on every call, on top of ``core.solver.
project_mode_b``'s own separate build of the same target body for Mode B
fits). This keeps a single call cheap even at tens-of-thousands-of-body-
vertex scale — see ARCHITECTURE.md section 7's performance risk note.
Batch-scale optimization beyond that (vectorized NumPy bulk access across
many DIFFERENT target bodies) is explicitly out of scope for this card,
per ARCHITECTURE.md section 8.
"""

# Minimum anchor-to-fitted travel distance worth testing for tunneling.
# Below this, the vertex barely moved off its anchor at all, so there is
# no meaningful segment to cross anything with -- skip the extra ray_cast
# rather than spend it on noise-level displacement.
_MIN_TUNNEL_TEST_DISTANCE = 1e-9

# Bound on test (1)'s local push/re-query loop (see module docstring). A
# vertex still flagged "inside" after this many pushes falls back to the
# anchor-based point instead of looping further.
_MAX_LOCAL_PUSH_ATTEMPTS = 3


def _push_out_locally(co, anchor, anchor_normal, bvh, collision_margin):
    """Resolve a vertex already flagged as locally interpenetrating.

    Pushes ``co`` along ``anchor_normal`` (not the local nearest-hit
    normal -- see the module docstring's test (1) entry for why) from the
    nearest surface point, then re-queries the inside/outside test against
    the new position; a concave pocket can leave a single push still
    inside, or move it into a different fold of the same pocket, so this
    repeats up to ``_MAX_LOCAL_PUSH_ATTEMPTS`` times. If the vertex is
    still flagged inside after that many attempts, falls back to
    ``anchor + anchor_normal * collision_margin`` -- guaranteed correct by
    construction (the anchor sits on the target body's own near surface;
    see the tunneling test's push-out for the same guarantee), so this
    always returns a definite, correct-side answer in bounded time.

    ``anchor_normal`` must already be normalized.
    """
    current = co
    for _ in range(_MAX_LOCAL_PUSH_ATTEMPTS):
        hit_location, hit_normal, hit_tri_index, _hit_distance = bvh.find_nearest(current)
        if hit_tri_index is None or (current - hit_location).dot(hit_normal) >= 0.0:
            return current
        current = hit_location + anchor_normal * collision_margin
    return anchor + anchor_normal * collision_margin


def resolve_collisions(
    fitted_positions,
    anchor_positions,
    anchor_normals,
    target_bvh,
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

    ``target_bvh`` is a pre-built ``mathutils.bvhtree.BVHTree`` over the
    target body's evaluated, world-space, triangulated surface --
    ``core.geometry.TargetContext.build(target_body_obj, depsgraph).bvh``.
    This function takes a plain ``BVHTree`` (not a Blender object, and not
    raw positions/triangles to build one from) so it is testable with a
    synthetic BVH and has no ``bpy`` dependency of its own, matching
    ``_laplacian_step``/``barycentric_weights``/``triangle_frame``/
    ``local_frame``'s convention elsewhere in ``core/`` -- and so the SAME
    tree, built once, is reused across every call in a single fit (see
    module docstring).

    Returns a new list of the same length and order: a vertex found
    interpenetrating (by either the local nearest-point test or the
    anchor-based tunneling test) is replaced with a position on the
    relevant surface offset outward by ``collision_margin`` along that
    surface point's normal; every other vertex is passed through
    completely unchanged.
    """
    bvh = target_bvh
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
            normal_at_anchor = anchor_normal.normalized()
            resolved.append(
                _push_out_locally(co, anchor, normal_at_anchor, bvh, collision_margin)
            )
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
