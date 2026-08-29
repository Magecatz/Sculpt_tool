"""Tests for ``core/collision.py``."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

from mathutils import Vector  # noqa: E402

from sculpt_tool.core import binding, collision  # noqa: E402


class ThinSlabTunnelingTest(unittest.TestCase):
    """ARCHITECTURE.md section 7: a vertex whose offset carried it all the
    way through thin geometry (e.g. wrist/ankle) is pushed back to
    ``anchor_position + anchor_normal * collision_margin`` -- not left in
    place, and not resolved via the far-side nearest-point test."""

    def setUp(self):
        common.clear_scene()

    def test_tunneled_vertex_snapped_to_anchor_plus_margin(self):
        # A thin slab: 2x2 in X/Y, 0.05 thick in Z (top at z=+0.025,
        # bottom at z=-0.025) -- stands in for a thin wrist/ankle
        # cross-section.
        import bmesh

        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=2.0)
        bmesh.ops.scale(bm, vec=(1.0, 1.0, 0.025), verts=bm.verts)
        slab = common.link_object("Slab", bm)

        target_positions, target_triangles = binding._world_space_triangles(slab)

        anchor = Vector((0.0, 0.0, 0.025))  # on the slab's near (top) surface
        anchor_normal = Vector((0.0, 0.0, 1.0))
        # Fitted position tunneled all the way through to well past the
        # far (bottom) wall.
        fitted = Vector((0.0, 0.0, -0.5))
        collision_margin = 0.01

        resolved = collision.resolve_collisions(
            [fitted],
            [anchor],
            [anchor_normal],
            target_positions,
            target_triangles,
            collision_margin,
        )

        expected = anchor + anchor_normal * collision_margin
        diff = (resolved[0] - expected).length
        self.assertLess(
            diff,
            1e-6,
            f"tunneled vertex resolved to {tuple(resolved[0])}, expected "
            f"anchor+normal*margin {tuple(expected)} (diff {diff})",
        )

    def test_non_tunneled_vertex_passes_through_unchanged(self):
        """Sanity check alongside the tunneling test: a vertex that never
        entered the body at all is untouched (same object, not a
        recomputed copy) -- matches the module docstring's "any vertex
        that fails both tests is returned completely unchanged" contract."""
        import bmesh

        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=2.0)
        bmesh.ops.scale(bm, vec=(1.0, 1.0, 0.025), verts=bm.verts)
        slab = common.link_object("Slab", bm)

        target_positions, target_triangles = binding._world_space_triangles(slab)

        anchor = Vector((0.0, 0.0, 0.025))
        anchor_normal = Vector((0.0, 0.0, 1.0))
        fitted = Vector((0.0, 0.0, 0.5))  # well clear, above the slab

        resolved = collision.resolve_collisions(
            [fitted],
            [anchor],
            [anchor_normal],
            target_positions,
            target_triangles,
            0.01,
        )

        self.assertIs(resolved[0], fitted)


def _inside_valley_solid(point, epsilon=1e-9):
    """Independent inside/outside check for ``common.make_valley``'s solid,
    derived directly from the geometry's definition (``z <= -x`` for
    ``x <= 0``, ``z <= x`` for ``x >= 0``) rather than from
    ``collision.py``'s own BVH-based test -- mirrors the card's own
    "independent parity ray-cast test, not the add-on's own inside/outside
    test" verification approach, so this test doesn't just check that
    ``resolve_collisions`` agrees with itself."""
    if point.x <= 0:
        return point.z <= -point.x + epsilon
    return point.z <= point.x + epsilon


class ConcavePushOutDirectionTest(unittest.TestCase):
    """Card 1e252575-2b86-4ba5-89f7-bcf0ae9685ba: a full-corpus run on real
    garments found collision resolution leaving 50+ residual penetrating
    vertices on 9 of 22 meshes, concentrated in concave/self-occluding
    body regions (armpits, crotch, straps, hoods). Root cause: test (1)'s
    push-out direction came from the locally-nearest triangle's own face
    normal, which near a concave crease can point sideways or back into
    the body rather than away from it. ``common.make_valley`` reproduces
    the same failure mode with a minimal synthetic crease (two large
    quads meeting at a fold) -- real Test_Items/ garment assets are
    gitignored third-party meshes and cannot be checked in, per the
    card's acceptance criteria.

    Every case below was verified (see the card's implementation notes)
    to leave the vertex penetrating under the OLD algorithm (a single
    push along the locally-nearest triangle's face normal) -- these are
    not incidental passes, they specifically exercise the fix."""

    def setUp(self):
        common.clear_scene()

    def test_crease_adjacent_vertex_pushed_along_anchor_normal_not_local_normal(self):
        """The primary repro: a vertex sitting just inside the crease,
        nearest to one fold, whose LOCAL face normal points into the
        OTHER fold's solid if used for push-out (verified: pushing along
        the local nearest-hit normal here leaves the vertex embedded --
        (-0.0071, 0, 0.0071), which still satisfies z <= -x). Pushing
        along ``anchor_normal`` (the binding's own reference direction,
        here straight up -- as if the anchor was measured before the body
        deformed into this fold) clears it in a single push."""
        valley = common.make_valley("Valley")
        target_positions, target_triangles = binding._world_space_triangles(valley)

        co = Vector((0.0002, 0.0, -0.0005))
        anchor = Vector((co.x, co.y, 1.0))
        anchor_normal = Vector((0.0, 0.0, 1.0))
        collision_margin = 0.01

        resolved = collision.resolve_collisions(
            [co], [anchor], [anchor_normal], target_positions, target_triangles, collision_margin,
        )

        self.assertFalse(
            _inside_valley_solid(resolved[0]),
            f"vertex still penetrating the concave crease after resolution: {tuple(resolved[0])}",
        )

    def test_bounded_requery_resolves_case_a_single_push_would_miss(self):
        """A single push (even along the improved ``anchor_normal``) is
        not always enough near a crease -- the push destination can land
        on a different, still-interpenetrating fold. Here a slightly
        tilted ``anchor_normal`` (realistic: the bind-time frame is not
        guaranteed perfectly vertical) needs a second push/re-query to
        clear (verified: a single push alone lands at (-0.00045, 0,
        0.00155), which the local nearest-point test still flags as
        inside -- ``resolve_collisions`` must re-query and push again to
        finish the job)."""
        valley = common.make_valley("Valley")
        target_positions, target_triangles = binding._world_space_triangles(valley)

        co = Vector((-0.001, 0.0, 0.0001))
        anchor = Vector((co.x, co.y, 1.0))
        anchor_normal = Vector((0.1, 0.0, 0.994987428188324))  # already normalized
        collision_margin = 0.001

        resolved = collision.resolve_collisions(
            [co], [anchor], [anchor_normal], target_positions, target_triangles, collision_margin,
        )

        self.assertFalse(
            _inside_valley_solid(resolved[0]),
            f"vertex still penetrating after the bounded re-query loop: {tuple(resolved[0])}",
        )

    def test_exhausted_local_attempts_falls_back_to_anchor_plus_margin(self):
        """When the local push/re-query loop can't clear a vertex within
        its bounded attempt count (a strongly tilted ``anchor_normal``
        that keeps re-entering the OTHER fold's solid each time), the
        result must fall back to ``anchor + anchor_normal * margin`` --
        guaranteed correct by construction, same as the tunneling test's
        own push-out -- rather than leaving the vertex at whatever the
        last unresolved attempt produced."""
        valley = common.make_valley("Valley")
        target_positions, target_triangles = binding._world_space_triangles(valley)

        co = Vector((-0.001, 0.0, 0.0001))
        anchor = Vector((co.x, co.y, 1.0))
        anchor_normal = Vector((0.75, 0.0, 0.6614378094673157))  # already normalized
        collision_margin = 0.02

        resolved = collision.resolve_collisions(
            [co], [anchor], [anchor_normal], target_positions, target_triangles, collision_margin,
        )

        expected = anchor + anchor_normal * collision_margin
        diff = (resolved[0] - expected).length
        self.assertLess(
            diff,
            1e-6,
            f"expected the anchor-based fallback {tuple(expected)}, got {tuple(resolved[0])}",
        )
        self.assertFalse(
            _inside_valley_solid(resolved[0]),
            f"fallback point still penetrating the concave crease: {tuple(resolved[0])}",
        )


if __name__ == "__main__":
    unittest.main()
