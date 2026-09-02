"""Tests for the gross pose/position mismatch guard (roadmap R4).

Pure ``core.alignment`` logic only. The operator-integration cases (bind/fit
refuse a mismatch; ``skip_alignment_check`` forces past it) were removed with
the conform operators in the conform-rebuild restart (RESTART_SCOPE.md); the
guard itself is kept and will be re-wired into the new conform.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

from sculpt_tool.core import alignment, geometry  # noqa: E402


class EvaluateAlignmentTest(unittest.TestCase):
    """Pure ``core.alignment.evaluate_alignment`` -- no operators."""

    def setUp(self):
        common.clear_scene()

    def _ctx(self, obj):
        depsgraph = bpy.context.evaluated_depsgraph_get()
        return geometry.TargetContext.build(obj, depsgraph)

    def test_aligned_garment_hugging_body(self):
        body = common.make_tube("Body", radius=1.0, height=2.0)
        garment = common.make_tube("Garment", radius=1.05, height=2.0)
        ctx = self._ctx(body)
        report = alignment.check_against_body(common.world_positions(garment), ctx)
        self.assertTrue(report.aligned, report.reason)

    def test_far_garment_refused_on_position(self):
        body = common.make_tube("Body", radius=1.0, height=2.0)
        garment = common.make_tube("Garment", radius=1.0, height=2.0,
                                   location=(20.0, 0.0, 0.0))
        ctx = self._ctx(body)
        report = alignment.check_against_body(common.world_positions(garment), ctx)
        self.assertFalse(report.aligned)
        self.assertGreater(report.centroid_dist_ratio, alignment.MAX_CENTROID_FRACTION)

    def test_surface_far_garment_refused(self):
        # A garment whose bbox overlaps the body's but which sits well off
        # the body surface on average -> refused via mean-distance/far-frac,
        # not bbox. A big loose tube around a small body.
        body = common.make_tube("Body", radius=0.3, height=2.0)
        garment = common.make_tube("Garment", radius=2.5, height=2.0)
        ctx = self._ctx(body)
        report = alignment.check_against_body(common.world_positions(garment), ctx)
        self.assertFalse(report.aligned)

    def test_faceless_body_position_only(self):
        # Body with vertices but no faces -> BVH is never touched; the
        # position check alone accepts an overlapping garment.
        import bmesh
        bm = bmesh.new()
        for i in range(20):
            bm.verts.new((0.1 * i - 1.0, 0.0, 0.1 * i - 1.0))
        faceless = common.link_object("Faceless", bm)
        common.update_scene()
        garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.0)
        ctx = self._ctx(faceless)
        self.assertEqual(ctx._triangles, [])  # genuinely faceless
        report = alignment.check_against_body(common.world_positions(garment), ctx)
        self.assertTrue(report.aligned)
        self.assertFalse(report.checked_surface)


if __name__ == "__main__":
    unittest.main()
