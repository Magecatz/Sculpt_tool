"""Tests for ``core/geometry.py``, added alongside the module by Bear PR
Process card cd0d1569-36ad-4d79-a82b-6d1115a0bcda (promoting
``core/binding.py``'s private geometry helpers to a shared, public
module, plus the new ``TargetContext``)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bmesh  # noqa: E402
import bpy  # noqa: E402

from sculpt_tool.core import geometry  # noqa: E402


class TargetContextBuildTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()

    def test_positions_and_triangles_match_world_space_triangles(self):
        """TargetContext.build's own single evaluated-mesh read must
        produce the exact same positions/triangles a separate
        world_space_triangles call on the same object/depsgraph would --
        it's meant to be a drop-in replacement for that call (plus
        normals plus a BVH), not a different evaluation path."""
        body = common.make_grid("Body", x_segments=4, y_segments=4, size=2.0)
        depsgraph = bpy.context.evaluated_depsgraph_get()

        ctx = geometry.TargetContext.build(body, depsgraph)
        positions, triangles = geometry.world_space_triangles(body, depsgraph)

        self.assertEqual(len(ctx.positions), len(positions))
        diff = common.max_component_diff(ctx.positions, positions)
        self.assertEqual(diff, 0.0)
        self.assertEqual(ctx.triangles, triangles)

    def test_positions_match_world_space_positions_and_normals(self):
        body = common.make_grid("Body", x_segments=4, y_segments=4, size=2.0)
        depsgraph = bpy.context.evaluated_depsgraph_get()

        ctx = geometry.TargetContext.build(body, depsgraph)
        positions, normals = geometry.world_space_positions_and_normals(body, depsgraph)

        diff = common.max_component_diff(ctx.positions, positions)
        self.assertEqual(diff, 0.0)
        normal_diff = common.max_component_diff(ctx.normals, normals)
        self.assertEqual(normal_diff, 0.0)

    def test_bvh_matches_positions_and_triangles(self):
        """The BVH TargetContext.build hands back must actually be built
        from its own positions/triangles -- a nearest-surface query
        against a known point should land on the expected face."""
        body = common.make_grid("Body", x_segments=1, y_segments=1, size=2.0)
        depsgraph = bpy.context.evaluated_depsgraph_get()

        ctx = geometry.TargetContext.build(body, depsgraph)
        from mathutils import Vector

        hit_location, hit_normal, hit_index, hit_distance = ctx.bvh.find_nearest(
            Vector((0.0, 0.0, 1.0))
        )
        self.assertIsNotNone(hit_index)
        self.assertLess(abs(hit_location.z), 1e-9)

    def test_empty_mesh_raises_value_error(self):
        bm = bmesh.new()
        empty = common.link_object("Empty", bm)
        depsgraph = bpy.context.evaluated_depsgraph_get()

        with self.assertRaises(ValueError):
            geometry.TargetContext.build(empty, depsgraph)


if __name__ == "__main__":
    unittest.main()
