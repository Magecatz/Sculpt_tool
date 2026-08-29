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


if __name__ == "__main__":
    unittest.main()
