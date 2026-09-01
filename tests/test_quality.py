"""Tests for core.quality.edge_distortion (fix C).

The metric a surface-quality regression gate stands on: it must read ~0 for
a uniformly placed/scaled garment (the legitimate case placement produces)
and high for local twist/scatter (the failure the aggregate metrics miss).
Pure-data, no Blender needed beyond the mathutils Vector type.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mathutils import Vector  # noqa: E402

from sculpt_tool.core import quality  # noqa: E402


def _grid(n, spacing=0.1):
    """An n x n lattice of vertices with 4-neighbour edges."""
    positions = [Vector((x * spacing, y * spacing, 0.0)) for y in range(n) for x in range(n)]
    edges = []
    for y in range(n):
        for x in range(n):
            idx = y * n + x
            if x + 1 < n:
                edges.append((idx, idx + 1))
            if y + 1 < n:
                edges.append((idx, idx + n))
    return positions, edges


class EdgeDistortionTest(unittest.TestCase):
    def test_identity_has_zero_distortion(self):
        positions, edges = _grid(6)
        result = quality.edge_distortion(positions, positions, edges)
        self.assertAlmostEqual(result.median_ratio, 1.0, places=6)
        self.assertEqual(result.distorted_fraction, 0.0)
        self.assertAlmostEqual(result.max_normalized, 1.0, places=6)

    def test_uniform_scale_is_not_distortion(self):
        # A garment placed onto a 1.7x-larger base scales every edge equally
        # -- that is correct placement, not surface damage: median absorbs
        # it, distorted_fraction stays 0.
        positions, edges = _grid(6)
        fitted = [p * 1.7 for p in positions]
        result = quality.edge_distortion(positions, fitted, edges)
        self.assertAlmostEqual(result.median_ratio, 1.7, places=6)
        self.assertEqual(result.distorted_fraction, 0.0)

    def test_local_scatter_is_flagged(self):
        # Fling a handful of interior vertices far off the lattice (the
        # scatter a loose panel shows under nearest-surface reprojection):
        # the edges touching them blow past the tolerance.
        positions, edges = _grid(8)
        fitted = list(positions)
        for idx in (18, 27, 36, 45):
            fitted[idx] = fitted[idx] + Vector((0.0, 0.0, 1.0))  # 10x a grid step
        result = quality.edge_distortion(positions, fitted, edges)
        self.assertGreater(result.distorted_fraction, 0.02)
        self.assertGreater(result.max_normalized, 2.0)

    def test_local_shrink_is_flagged(self):
        # Collapse a sub-block toward its centroid to ~0.25 size -- the
        # shrink-wrap-flat failure the surface passes produced on loose
        # geometry. Its internal edges drop to ~1/4 of the median, well past
        # the tolerance, so the block is flagged.
        n = 8
        positions, edges = _grid(n)
        block = [y * n + x for y in range(2, 5) for x in range(2, 5)]
        centroid = sum((positions[i] for i in block), Vector((0, 0, 0))) / len(block)
        fitted = list(positions)
        for i in block:
            fitted[i] = centroid + (positions[i] - centroid) * 0.25
        result = quality.edge_distortion(positions, fitted, edges)
        self.assertGreater(result.distorted_fraction, 0.0)
        self.assertGreater(result.max_normalized, 2.0)

    def test_rigid_rotation_is_not_flagged(self):
        # Honest limitation, asserted so it's documented: a RIGID fold/twist
        # preserves every edge length, so edge distortion cannot see it. Pure
        # rigid placement twist (the R7 bug) is caught upstream by
        # test_placement.test_rest_orientation_difference_injects_no_twist;
        # this metric targets the stretch/shrink/scatter damage instead.
        import math
        positions, edges = _grid(6)
        c, s = math.cos(math.radians(37)), math.sin(math.radians(37))
        fitted = [Vector((c * p.x - s * p.y, s * p.x + c * p.y, p.z)) for p in positions]
        result = quality.edge_distortion(positions, fitted, edges)
        self.assertEqual(result.distorted_fraction, 0.0)

    def test_looseness_preservation(self):
        authored = [0.001, 0.002, 0.05, 0.06, 0.07, 0.08]  # last four are "loose"
        # Preserved: fitted standoff ~= authored -> ratio ~1.
        preserved = quality.looseness_preservation(
            authored, [0.001, 0.002, 0.05, 0.06, 0.07, 0.08],
            loose_threshold=0.03, min_loose=3)
        self.assertAlmostEqual(preserved, 1.0, places=6)
        # Collapsed onto the body: fitted standoff ~1/4 -> ratio ~0.25.
        collapsed = quality.looseness_preservation(
            authored, [0.001, 0.002, 0.0125, 0.015, 0.0175, 0.02],
            loose_threshold=0.03, min_loose=3)
        self.assertLess(collapsed, 0.3)

    def test_looseness_none_when_no_loose_region(self):
        # A tight garment (no vertex past the loose threshold) => None, not
        # a failure, so a tight-garment fit isn't gated on a loose metric.
        authored = [0.001, 0.002, 0.003]
        self.assertIsNone(
            quality.looseness_preservation(authored, authored, loose_threshold=0.03, min_loose=1)
        )

    def test_empty_and_degenerate(self):
        self.assertEqual(quality.edge_distortion([], [], []).distorted_fraction, 0.0)
        # A zero-length reference edge is skipped, not divided by.
        p = [Vector((0, 0, 0)), Vector((0, 0, 0)), Vector((1, 0, 0))]
        f = [Vector((0, 0, 0)), Vector((0.5, 0, 0)), Vector((1, 0, 0))]
        result = quality.edge_distortion(p, f, [(0, 1), (0, 2)])
        self.assertAlmostEqual(result.median_ratio, 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
