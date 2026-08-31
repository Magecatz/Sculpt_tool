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

    def test_faceless_body_build_succeeds_but_triangles_and_bvh_raise_lazily(self):
        """Regression test for Bear PR Process card
        e6763cc5-d3cf-4021-8541-f5e5dd4a23aa: a target body with vertices
        but zero faces (e.g. a loose-vertex mesh, or one with all its
        faces stripped) must NOT fail at ``build()`` time -- pre-refactor,
        ``core.solver.project_mode_a`` only ever required target
        vertices, never touched triangles/BVH, and this exact case
        succeeded. ``build()`` deferring the "no triangulatable faces"
        check to first access of ``.triangles``/``.bvh`` is what restores
        that: Mode A (which never accesses either) still works, while
        anything that genuinely needs the surface (Mode B, collision
        resolution) still gets the same ValueError as before, just at
        first access instead of unconditionally at build time."""
        body = common.make_grid("Body", x_segments=2, y_segments=2, size=2.0)
        bm = bmesh.new()
        bm.from_mesh(body.data)
        bmesh.ops.delete(bm, geom=list(bm.faces), context='FACES_ONLY')
        bm.to_mesh(body.data)
        bm.free()
        body.data.update()
        self.assertGreater(len(body.data.vertices), 0)
        self.assertEqual(len(body.data.polygons), 0)

        depsgraph = bpy.context.evaluated_depsgraph_get()

        # build() itself must not raise -- Mode A's own needs
        # (positions/normals) are unaffected by the missing faces.
        ctx = geometry.TargetContext.build(body, depsgraph)
        self.assertEqual(len(ctx.positions), len(body.data.vertices))
        self.assertEqual(len(ctx.normals), len(body.data.vertices))

        # Mode B / collision resolution genuinely need the surface --
        # they must still get the same error, just deferred to access.
        with self.assertRaises(ValueError):
            ctx.triangles
        with self.assertRaises(ValueError):
            ctx.bvh


if __name__ == "__main__":
    unittest.main()
