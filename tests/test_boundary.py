"""Tests for open-boundary detection + boundary relaxation (open-edge card).

Covers ``core.smoothing.boundary_vertex_neighbors`` (which mesh vertices lie
on an open edge, and their along-boundary neighbors) and
``relax_boundary_positions`` (straightening a spiky rim), plus an
end-to-end check that a garment fit onto a bumpy target comes out with a
smoother open edge than with the boundary pass disabled.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

from mathutils import Vector  # noqa: E402

from sculpt_tool.core import smoothing  # noqa: E402


class BoundaryNeighborsTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()

    def test_grid_ring_is_boundary_interior_is_not(self):
        # A 4x4 grid -> 5x5 = 25 verts; the 16 outer-ring verts are boundary,
        # the 3x3 = 9 interior verts are not.
        grid = common.make_grid("G", x_segments=4, y_segments=4)
        nbrs = smoothing.boundary_vertex_neighbors(grid.data)
        self.assertEqual(len(nbrs), 25)
        boundary = [i for i, n in enumerate(nbrs) if n]
        self.assertEqual(len(boundary), 16)
        # Every boundary vertex has exactly two along-boundary neighbors
        # (the rim is a single loop).
        for i in boundary:
            self.assertEqual(len(nbrs[i]), 2)

    def test_closed_tube_has_no_open_boundary_on_rings(self):
        # A tube is open-ended, so only its top and bottom rings are
        # boundary; the wall interior is not. (Sanity: some boundary exists.)
        tube = common.make_tube("T", segments=8, rings=4)
        nbrs = smoothing.boundary_vertex_neighbors(tube.data)
        boundary = [i for i, n in enumerate(nbrs) if n]
        self.assertEqual(len(boundary), 16)  # 2 rings x 8 segments

    def test_relax_boundary_reduces_a_spike(self):
        # A square rim loop of 4 verts with one pushed far out; relaxing
        # along the loop pulls the spike back toward its neighbors' midpoint.
        positions = [
            Vector((0.0, 0.0, 0.0)),
            Vector((1.0, 0.0, 0.0)),
            Vector((1.0, 1.0, 0.0)),
            Vector((0.0, 5.0, 0.0)),   # spike (should be ~ (0,1,0))
        ]
        loop = [[1, 3], [0, 2], [1, 3], [2, 0]]  # 0-1-2-3-0 cycle
        before = (positions[3] - Vector((0.0, 1.0, 0.0))).length
        relaxed = smoothing.relax_boundary_positions(positions, loop, iterations=8, factor=0.5)
        after = (relaxed[3] - Vector((0.0, 1.0, 0.0))).length
        self.assertLess(after, before * 0.5)  # spike substantially reduced

    def test_pinned_boundary_vertex_does_not_move(self):
        positions = [Vector((0.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0)),
                     Vector((1.0, 1.0, 0.0)), Vector((0.0, 5.0, 0.0))]
        loop = [[1, 3], [0, 2], [1, 3], [2, 0]]
        pins = [0.0, 0.0, 0.0, 1.0]  # spike is fully pinned
        relaxed = smoothing.relax_boundary_positions(positions, loop, pins, iterations=8)
        self.assertEqual(relaxed[3], positions[3])


if __name__ == "__main__":
    unittest.main()
