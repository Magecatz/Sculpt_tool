"""Tests for ``core/smoothing.py``.

Transcribes the quantitative claims already written down in
ARCHITECTURE.md section 6/7 into checked-in, reproducible assertions
(the card that added this suite exists specifically because those claims
previously came from scripts that were never checked in).
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

from mathutils import Vector  # noqa: E402

from sculpt_tool.core import smoothing  # noqa: E402


class TubeShrinkageTest(unittest.TestCase):
    """ARCHITECTURE.md section 7: a clean, unperturbed, unpinned tube must
    not shrink more than about 1% at either 10 or 40 outer iterations
    (guards ``_EDGE_CORRECTION_SUBSTEPS`` -- PR #12's instruction not to
    re-tune it downward without re-running this exact test)."""

    def setUp(self):
        common.clear_scene()

    def _radius_shrinkage(self, iterations):
        obj = common.make_tube("Tube", segments=32, rings=20, radius=1.0, height=2.0)
        positions = common.world_positions(obj)

        result = smoothing.relax(obj, positions, pin_weights=None, iterations=iterations)

        # Average radial distance from the tube's own axis (Z), before vs.
        # after -- shrinkage is measured relative to the original radius,
        # matching how ARCHITECTURE.md's tube repro measured it.
        original_radius = sum(Vector((p.x, p.y, 0.0)).length for p in positions) / len(positions)
        new_radius = sum(Vector((p.x, p.y, 0.0)).length for p in result) / len(result)
        return abs(original_radius - new_radius) / original_radius

    def test_shrinkage_under_one_percent_at_10_iterations(self):
        shrinkage = self._radius_shrinkage(10)
        self.assertLess(shrinkage, 0.01, f"10-iteration shrinkage {shrinkage:.4%} >= 1%")

    def test_shrinkage_under_one_percent_at_40_iterations(self):
        shrinkage = self._radius_shrinkage(40)
        self.assertLess(shrinkage, 0.01, f"40-iteration shrinkage {shrinkage:.4%} >= 1%")


class PinWeightBoundaryTest(unittest.TestCase):
    """ARCHITECTURE.md section 6/7: the two exact boundaries of the pin
    blend must hold bit-for-bit, regardless of how much noise/iteration
    count is thrown at them."""

    def setUp(self):
        common.clear_scene()
        self.obj = common.make_grid("Grid", x_segments=5, y_segments=5, size=2.0)
        rng = random.Random(1234)
        base = common.world_positions(self.obj)
        # Perturb off the mesh's own rest positions so this isn't a
        # vacuous "nothing was going to move anyway" test.
        self.positions = [
            p + Vector((rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05)))
            for p in base
        ]

    def test_pin_weight_one_is_bit_identical(self):
        vertex_count = len(self.obj.data.vertices)
        pin_weights = [1.0] * vertex_count
        result = smoothing.relax(self.obj, self.positions, pin_weights, iterations=8)
        diff = common.max_component_diff(result, self.positions)
        self.assertEqual(diff, 0.0, f"pin_weight=1.0 moved a vertex by up to {diff}")

    def test_pin_weight_zero_matches_zero_pin_path(self):
        vertex_count = len(self.obj.data.vertices)
        explicit_zero = smoothing.relax(
            self.obj, self.positions, [0.0] * vertex_count, iterations=8
        )
        default_zero = smoothing.relax(self.obj, self.positions, None, iterations=8)
        diff = common.max_component_diff(explicit_zero, default_zero)
        self.assertEqual(diff, 0.0, f"explicit all-0.0 pin weights diverged from the default path by {diff}")


class PinBlendMonotonicityTest(unittest.TestCase):
    """ARCHITECTURE.md section 7: an isolated pinned vertex's displacement
    is monotonic (non-increasing) as its pin weight rises from 0 to 1, and
    bounded by the unpinned (0.0) baseline -- the "isolated pinned vertex"
    configuration the doc reports as holding in every case tested."""

    def setUp(self):
        common.clear_scene()

    def test_monotonic_across_0_025_05_075_1(self):
        obj = common.make_grid("Grid", x_segments=6, y_segments=6, size=2.0)
        vertex_count = len(obj.data.vertices)
        base = common.world_positions(obj)
        rng = random.Random(42)
        positions = [
            p + Vector((rng.uniform(-0.02, 0.02), rng.uniform(-0.02, 0.02), rng.uniform(-0.02, 0.02)))
            for p in base
        ]

        # A single interior vertex, isolated from any other pin -- find a
        # vertex with a full 4-neighbor valence so it isn't a boundary
        # artifact itself.
        interior_index = (len(obj.data.vertices)) // 2

        weights_to_test = (0.0, 0.25, 0.5, 0.75, 1.0)
        displacements = []
        for weight in weights_to_test:
            pin_weights = [0.0] * vertex_count
            pin_weights[interior_index] = weight
            result = smoothing.relax(obj, positions, pin_weights, iterations=10)
            displacement = (result[interior_index] - positions[interior_index]).length
            displacements.append(displacement)

        for earlier, later in zip(displacements, displacements[1:]):
            self.assertLessEqual(
                later,
                earlier + 1e-12,
                f"displacement increased with higher pin weight: {displacements}",
            )
        self.assertAlmostEqual(displacements[-1], 0.0, places=9)


class GradedBoundaryAdversarialSweepTest(unittest.TestCase):
    """ARCHITECTURE.md section 7 / bug card
    8432ee45-20a9-47da-be6a-53e3beee39e6: a graded pin-weight region near
    the garment's own free
    boundary, combined with position noise, can let a partially-pinned
    vertex move MORE than the most-displaced fully-unpinned vertex in the
    same run. This is the seeded, checked-in regression guard for that
    residual.

    **Fix applied (this card):** ``relax()`` (``core/smoothing.py``) now
    passes the real per-vertex pin-weight array to ``_edge_length_step``
    for its outer-iteration "candidate" computation, instead of an
    all-``0.0`` array (``_laplacian_step`` still gets an all-``0.0`` array
    -- only the edge-length correction's mass-weighted split changed).
    Architect-directed cheap experiment, tried before considering a
    structural "dual-trajectory" redesign: since the edge-length
    sub-sweeps already split each edge's correction by
    ``free_a / (free_a + free_b)``, feeding them the real pin weights
    means a neighbor's own resistance to movement is no longer hidden
    from the correction math at a pin gradient, which was the documented
    root cause of the overshoot. It does not change per-call cost (same
    sub-sweep count, same loop shape) and does not touch the
    ``pin_weight == 0.0`` / ``pin_weight == 1.0`` exact boundaries (see
    ``PinWeightBoundaryTest`` above, still green).

    The sweep below is a fresh reproduction (the original ad hoc script
    that produced ARCHITECTURE.md's ~46%/1.46x figure was never checked
    in), tuned to land in the same regime the doc describes (graded band
    feathering toward zero at a free boundary + jitter, a minority of
    configurations affected, an above-baseline overshoot on the worst
    one). It was widened on this card (more seeds, a wider grading-width
    and jitter-amplitude range) specifically because the fix reduces the
    overshoot enough that the original narrower grid stopped finding a
    worst case anywhere near the true one -- a regression guard needs to
    actually exercise the residual to be worth anything. Pre-fix, this
    wider grid measured a worst case of ~1.61x (52% of configurations
    showing at least some overshoot); post-fix, the same grid's worst
    case is ~1.19x (seed 13, grading width 4, jitter 0.05, 10
    iterations) with far fewer configurations affected. Both figures are
    checked-in-reproducible via this test and its ``_worst_ratio`` helper
    -- not re-asserting the original unreproducible 1.46x number, but a
    fresh measurement in the same regime, now on both sides of the fix.
    The ceiling below is the post-fix measured worst case plus a small
    margin.
    """

    CEILING = 1.22

    def setUp(self):
        common.clear_scene()

    def _worst_ratio(self, seed, grading_width, jitter_amplitude, iterations):
        obj = common.make_grid("Grid", x_segments=6, y_segments=6, size=2.0)
        vertex_count = len(obj.data.vertices)
        cols = 7  # x_segments=6 -> 7 verts per row/column

        base = common.world_positions(obj)
        rng = random.Random(seed)
        positions = [
            p
            + Vector(
                (
                    rng.uniform(-jitter_amplitude, jitter_amplitude),
                    rng.uniform(-jitter_amplitude, jitter_amplitude),
                    rng.uniform(-jitter_amplitude, jitter_amplitude),
                )
            )
            for p in base
        ]

        # Grade pin weight from 1.0 at row 0 (a free boundary edge of this
        # open grid) down to 0.0 over `grading_width` rows -- "a weight
        # feathering toward zero along a hem/cuff edge", per the doc.
        pin_weights = [0.0] * vertex_count
        for i in range(vertex_count):
            row = i // cols
            if row < grading_width:
                pin_weights[i] = max(0.0, 1.0 - row / grading_width)

        result = smoothing.relax(obj, positions, pin_weights, iterations=iterations)
        displacements = [(result[i] - positions[i]).length for i in range(vertex_count)]

        unpinned = [d for d, w in zip(displacements, pin_weights) if w == 0.0]
        partial = [d for d, w in zip(displacements, pin_weights) if 0.0 < w < 1.0]
        if not unpinned or not partial:
            return 0.0

        baseline = max(unpinned)
        worst_partial = max(partial)
        if baseline <= 1e-12:
            return 0.0
        return worst_partial / baseline

    def test_worst_case_ratio_stays_under_ceiling(self):
        worst = 0.0
        for seed in range(16):
            for grading_width in (2, 3, 4, 5):
                for jitter_amplitude in (0.03, 0.05):
                    for iterations in (10, 15, 20):
                        ratio = self._worst_ratio(
                            seed=seed,
                            grading_width=grading_width,
                            jitter_amplitude=jitter_amplitude,
                            iterations=iterations,
                        )
                        worst = max(worst, ratio)

        self.assertLessEqual(
            worst,
            self.CEILING,
            f"graded-boundary+jitter sweep's worst partial/unpinned ratio "
            f"{worst:.3f}x exceeded the {self.CEILING}x regression ceiling "
            "-- re-check the pin-blend outer-iteration math (relax()) "
            "against ARCHITECTURE.md section 7's known residual before "
            "assuming this is expected drift.",
        )
        # The known residual is a real, reproducible overshoot, not
        # measurement noise -- confirm the sweep actually exercises it
        # rather than trivially passing because nothing overshot at all.
        self.assertGreater(
            worst,
            1.0,
            "sweep found no overshoot at all -- it may no longer be "
            "exercising the graded-boundary residual described in "
            "ARCHITECTURE.md section 7 (check grading/jitter parameters).",
        )


if __name__ == "__main__":
    unittest.main()
