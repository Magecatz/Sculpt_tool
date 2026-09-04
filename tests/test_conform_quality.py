"""run_conform returns a populated ConformReport, and a clean flat-grid
conform stays under the distortion gate (Layer 0 wiring)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import quality  # noqa: E402
from sculpt_tool.operators import op_conform  # noqa: E402


class ConformReportTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def test_run_conform_returns_populated_report(self):
        target = common.make_grid("Target", x_segments=6, y_segments=6, size=2.0)
        garment = common.make_grid("Garment", x_segments=4, y_segments=4,
                                   size=1.0, location=(0.0, 0.0, 0.1))
        garment.sculpt_tool.target_body = target
        bpy.context.view_layer.objects.active = garment

        report = op_conform.run_conform(bpy.context, garment)

        self.assertIsInstance(report, op_conform.ConformReport)
        self.assertIn("vertices", report.info)
        self.assertIsInstance(report.edge_distortion, quality.EdgeDistortion)
        # A regular grid projected onto a flat grid stays uniform.
        self.assertLess(report.edge_distortion.distorted_fraction,
                        quality.MAX_DISTORTED_FRACTION)


if __name__ == "__main__":
    unittest.main()
