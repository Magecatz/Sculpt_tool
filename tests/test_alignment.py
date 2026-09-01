"""Tests for the gross pose/position mismatch guard (roadmap R4).

Covers the card's DoD: a deliberately mismatched garment/base pair is
refused with an actionable message; an aligned pair still runs. Exercises
both the pure ``core.alignment`` logic and the operator integration
(``OT_bind_garment`` / ``OT_fit_garment`` refuse; ``skip_alignment_check``
forces past the guard).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import alignment, geometry, storage  # noqa: E402


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


class AlignmentOperatorTest(unittest.TestCase):
    """Operator integration -- bind/fit refuse gross mismatches; the skip
    toggle forces past the guard."""

    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def _bind_modeA(self, garment, source):
        garment.sculpt_tool.source_body = source
        garment.sculpt_tool.target_body = source
        garment.sculpt_tool.bind_mode_override = 'MODE_A'
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)
        return bpy.ops.sculpttool.bind_garment()

    def test_bind_refuses_far_source(self):
        # bpy.ops raises RuntimeError (not a {'CANCELLED'} return) when an
        # operator reports {'ERROR'} -- matches test_binding_freeze's pattern.
        garment = common.make_grid("Garment", x_segments=4, y_segments=4)
        source = common.make_grid("SourceFar", x_segments=4, y_segments=4,
                                  location=(50.0, 0.0, 0.0))
        with self.assertRaises(RuntimeError) as ctx:
            self._bind_modeA(garment, source)
        self.assertIn("off the source body", str(ctx.exception).lower())
        self.assertFalse(storage.is_bound(garment))

    def test_fit_refuses_far_target_and_makes_no_shape_key(self):
        garment = common.make_grid("Garment", x_segments=4, y_segments=4)
        source = common.make_grid("Source", x_segments=4, y_segments=4)
        self.assertEqual(self._bind_modeA(garment, source), {'FINISHED'})

        far_target = common.make_grid("TargetFar", x_segments=4, y_segments=4,
                                      location=(50.0, 0.0, 0.0))
        garment.sculpt_tool.target_body = far_target
        with self.assertRaises(RuntimeError):
            bpy.ops.sculpttool.fit_garment()
        self.assertIsNone(
            garment.data.shape_keys.key_blocks.get(storage.FITTED_SHAPE_KEY_NAME)
            if garment.data.shape_keys else None
        )

    def test_fit_aligned_target_succeeds(self):
        garment = common.make_grid("Garment", x_segments=4, y_segments=4)
        source = common.make_grid("Source", x_segments=4, y_segments=4)
        self.assertEqual(self._bind_modeA(garment, source), {'FINISHED'})
        target = common.make_grid("Target", x_segments=4, y_segments=4)
        garment.sculpt_tool.target_body = target
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})

    def test_skip_toggle_forces_far_fit(self):
        garment = common.make_grid("Garment", x_segments=4, y_segments=4)
        source = common.make_grid("Source", x_segments=4, y_segments=4)
        self.assertEqual(self._bind_modeA(garment, source), {'FINISHED'})
        far_target = common.make_grid("TargetFar", x_segments=4, y_segments=4,
                                      location=(50.0, 0.0, 0.0))
        garment.sculpt_tool.target_body = far_target
        garment.sculpt_tool.skip_alignment_check = True
        # With the guard skipped, the fit runs to completion (it may be a
        # poor fit, but it is no longer refused for alignment).
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})


if __name__ == "__main__":
    unittest.main()
