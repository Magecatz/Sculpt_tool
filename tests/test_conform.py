"""Tests for ``core.conform`` -- the Direction-B minimal conform (restart).

Synthetic concentric tubes (all wrapped around Z, centred at the origin) make
the expected result exact: a garment vertex at radius ``r_g`` over a body of
radius ``r_b`` has authored standoff ``r_g - r_b``, and projecting it onto a
target body of radius ``r_t`` and reapplying that standoff lands it at radius
``r_t + (r_g - r_b)``. The source/target tubes are made TALLER than the
garment so every garment vertex projects radially (never off a rim), and the
assertions are on RADIUS -- robust to whichever way the tube faces wind (the
standoff sign and the target normal flip together, so the radius is the same).
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

from sculpt_tool.core import conform, geometry  # noqa: E402


def _radii(positions):
    return [math.hypot(p[0], p[1]) for p in positions]


def _mean(values):
    return sum(values) / len(values)


class ConformTubeTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()

    def _ctx(self, obj):
        depsgraph = bpy.context.evaluated_depsgraph_get()
        return geometry.TargetContext.build(obj, depsgraph)

    def _standoff(self, garment, source):
        return conform.authored_standoff(common.world_positions(garment), self._ctx(source))

    def test_authored_standoff_magnitude(self):
        source = common.make_tube("Source", radius=1.0, height=4.0)
        garment = common.make_tube("Garment", radius=1.2, height=2.0)
        standoff = self._standoff(garment, source)
        # 0.2 off the source wall, sign depends on face winding.
        self.assertAlmostEqual(abs(_mean(standoff)), 0.2, delta=0.02)

    def test_girth_up_preserves_standoff(self):
        # Garment authored 0.2 off a r=1.0 body, conformed onto a fatter
        # r=2.0 target -> should sit 0.2 off it, i.e. radius ~2.2.
        source = common.make_tube("Source", radius=1.0, height=4.0)
        garment = common.make_tube("Garment", radius=1.2, height=2.0)
        target = common.make_tube("Target", radius=2.0, height=4.0)

        standoff = self._standoff(garment, source)
        fitted = conform.project_to_target(
            common.world_positions(garment), standoff, self._ctx(target), keep_loose=False
        )
        self.assertAlmostEqual(_mean(_radii(fitted)), 2.2, delta=0.05)

    def test_girth_down_preserves_standoff(self):
        source = common.make_tube("Source", radius=1.0, height=4.0)
        garment = common.make_tube("Garment", radius=1.2, height=2.0)
        target = common.make_tube("Target", radius=0.5, height=4.0)

        standoff = self._standoff(garment, source)
        fitted = conform.project_to_target(
            common.world_positions(garment), standoff, self._ctx(target), keep_loose=False
        )
        self.assertAlmostEqual(_mean(_radii(fitted)), 0.7, delta=0.05)

    def test_tight_garment_hugs_target(self):
        # Garment == source radius -> ~0 standoff -> hugs the target wall.
        source = common.make_tube("Source", radius=1.0, height=4.0)
        garment = common.make_tube("Garment", radius=1.0, height=2.0)
        target = common.make_tube("Target", radius=2.0, height=4.0)

        standoff = self._standoff(garment, source)
        self.assertAlmostEqual(abs(_mean(standoff)), 0.0, delta=0.02)
        fitted = conform.project_to_target(
            common.world_positions(garment), standoff, self._ctx(target), keep_loose=False
        )
        self.assertAlmostEqual(_mean(_radii(fitted)), 2.0, delta=0.05)

    def test_inside_authored_vertex_stays_inside_target(self):
        # Garment authored INSIDE its body (r=0.9 vs r=1.0) must land inside
        # the target too (r=2.0 -> ~1.9), verifying the standoff SIGN carries.
        source = common.make_tube("Source", radius=1.0, height=4.0)
        garment = common.make_tube("Garment", radius=0.9, height=2.0)
        target = common.make_tube("Target", radius=2.0, height=4.0)

        standoff = self._standoff(garment, source)
        fitted = conform.project_to_target(
            common.world_positions(garment), standoff, self._ctx(target), keep_loose=False
        )
        self.assertAlmostEqual(_mean(_radii(fitted)), 1.9, delta=0.05)

    def test_loose_vertex_keeps_placed_position(self):
        # A vertex authored FAR off the body (standoff 0.6, well past the far
        # ramp threshold ~0.42 for this target) keeps its placed position (a
        # r=3.0 tube) instead of being pulled to the projected r=2.6.
        target = common.make_tube("Target", radius=2.0, height=4.0)
        placed = common.make_tube("Placed", radius=3.0, height=2.0)
        positions = common.world_positions(placed)
        fitted = conform.project_to_target(
            positions, [0.6] * len(positions), self._ctx(target)
        )  # keep_loose default True
        self.assertAlmostEqual(_mean(_radii(fitted)), 3.0, delta=0.05)

    def test_tight_vertex_projects_under_ramp(self):
        # A vertex authored tight (standoff 0.05, under the near threshold)
        # is fully projected even with keep_loose on: r=1.0 placed -> ~r=2.05.
        target = common.make_tube("Target", radius=2.0, height=4.0)
        placed = common.make_tube("Placed", radius=1.0, height=2.0)
        positions = common.world_positions(placed)
        fitted = conform.project_to_target(
            positions, [0.05] * len(positions), self._ctx(target)
        )
        self.assertAlmostEqual(_mean(_radii(fitted)), 2.05, delta=0.05)

    def test_placed_standoff_keeps_loose_region(self):
        # A garment the placement left OUTSIDE the target (r=2.5 over r=2.0)
        # keeps its ~0.5 standoff in the source-free fallback.
        target = common.make_tube("Target", radius=2.0, height=4.0)
        loose = common.make_tube("Loose", radius=2.5, height=2.0)
        placed = common.world_positions(loose)
        standoff = conform.placed_standoff(placed, self._ctx(target))
        self.assertAlmostEqual(_mean(standoff), 0.5, delta=0.05)
        fitted = conform.project_to_target(placed, standoff, self._ctx(target))
        self.assertAlmostEqual(_mean(_radii(fitted)), 2.5, delta=0.05)

    def test_placed_standoff_clamps_interpenetration(self):
        # A garment the placement left INSIDE the target (r=1.2 in r=2.0) is
        # clamped to 0 and pulled onto the surface (hug), not left inside.
        target = common.make_tube("Target", radius=2.0, height=4.0)
        inside = common.make_tube("Inside", radius=1.2, height=2.0)
        placed = common.world_positions(inside)
        standoff = conform.placed_standoff(placed, self._ctx(target))
        self.assertAlmostEqual(_mean(standoff), 0.0, delta=0.02)
        fitted = conform.project_to_target(placed, standoff, self._ctx(target))
        self.assertAlmostEqual(_mean(_radii(fitted)), 2.0, delta=0.05)

    def test_build_vertex_neighbors(self):
        neighbors = conform.build_vertex_neighbors([(0, 1), (1, 2), (2, 2)], 3)
        self.assertEqual([sorted(n) for n in neighbors], [[1], [0, 2], [1]])

    def test_spatial_coherence_reduces_tearing(self):
        # A sharp standoff split (top half loose, bottom half tight) makes the
        # raw per-vertex ramp jump hard at the boundary ring; smoothing the
        # weight over the mesh adjacency must reduce the worst adjacent gap.
        target = common.make_tube("Target", radius=2.0, height=4.0)
        garment = common.make_tube("Placed", radius=3.0, height=2.0)
        positions = common.world_positions(garment)
        standoff = [0.6 if p[2] > 0.0 else 0.0 for p in positions]
        edges = [(e.vertices[0], e.vertices[1]) for e in garment.data.edges]
        neighbors = conform.build_vertex_neighbors(edges, len(positions))
        ctx = self._ctx(target)

        raw = conform.project_to_target(positions, standoff, ctx)  # neighbors=None
        smoothed = conform.project_to_target(positions, standoff, ctx, neighbors=neighbors)

        def worst_gap(fitted):
            return max((fitted[a] - fitted[b]).length for a, b in edges)

        self.assertLess(worst_gap(smoothed), worst_gap(raw))

    def test_length_mismatch_raises(self):
        target = common.make_tube("Target", radius=2.0, height=4.0)
        garment = common.make_tube("Garment", radius=1.2, height=2.0)
        placed = common.world_positions(garment)
        with self.assertRaises(ValueError):
            conform.project_to_target(placed, [0.0] * (len(placed) - 1), self._ctx(target))


if __name__ == "__main__":
    unittest.main()
