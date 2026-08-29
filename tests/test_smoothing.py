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
    the garment's own free boundary, combined with position noise, can
    let a partially-pinned vertex move MORE than the most-displaced
    fully-unpinned vertex in the same run. This is the seeded, checked-in
    regression guard for that residual.

    History of fix attempts on this card (see ``core/smoothing.py``'s
    ``relax()``/``relax_positions()`` docstrings and ARCHITECTURE.md
    section 7 for the full writeup):

    1. **Shipped fix (current code):** passing the real per-vertex pin
       array into ``_edge_length_step`` for the outer-iteration candidate
       (instead of an all-``0.0`` array), so a lagging neighbor's own
       resistance to movement is visible to the edge-length correction
       split. Reduces the overshoot substantially versus the original
       pre-fix behavior but does not eliminate it, and less so on
       topologies wider than the original single 7x7 grid it was first
       checked against -- see the real, freshly-measured per-topology
       figures on each test method below.
    2. **Fully pin-independent dual-trajectory (prototyped, REJECTED):** a
       persistent ``free`` trajectory whose ``_laplacian_step`` AND
       ``_edge_length_step`` calls were BOTH always given an all-``0.0``
       pin array, blended into ``current`` fresh every iteration instead
       of re-deriving a candidate from ``current``'s own state. Measured
       WORSE than the shipped fix on all three topologies below (worst
       ratio 1.39x/1.32x/1.55x, incidence 65.6%/32.3%/72.2%).
    3. **Hybrid dual-trajectory (prototyped, REJECTED):** same persistent,
       never-blended ``free`` trajectory, but its ``_edge_length_step``
       call given the real pin array (only its ``_laplacian_step`` call
       stayed at all-``0.0``). Measured far worse still (worst ratio
       6.75x/5.94x/3.67x, incidence 93.0%/93.8%/85.4%) and broke
       ``PinBlendMonotonicityTest`` outright. Root cause (Architect-
       confirmed): nothing ever resets a persistent, un-blended ``free``
       trajectory back toward the pin anchor each iteration the way the
       shipped design's single-trajectory blend resets ``current`` --
       without that reset, a highly-pinned vertex's ``free`` position
       still gets dragged toward its neighbors every iteration by the
       always-unpinned Laplacian step, with nothing bounding the drift.

    Both dual-trajectory variants are reverted; only the shipped fix
    (item 1) is live in ``core/smoothing.py``. Per the Architect's stop
    condition, no third structural redesign was attempted -- the residual
    is accepted and tracked (Backlog card, see ARCHITECTURE.md section 7)
    rather than converged on further here.

    This test sweeps THREE topologies -- a 7x7 flat grid (the original,
    narrowest repro), a 12x12 flat grid, and a cylindrical hem-ring (an
    open-ended tube graded from one free boundary ring) -- because the
    Reviewer's broader sweep in the previous round found the 7x7-grid-only
    ceiling was topology-specific, not a real bound: a plain 12x12 grid
    alone busted it with no exotic topology needed. Each topology gets its
    own ceiling below rather than forcing one number to honestly cover all
    three -- they do NOT converge to the same worst case (the cylindrical
    hem-ring is meaningfully worse than either flat grid on both
    magnitude and incidence). Both worst-case RATIO and INCIDENCE
    (fraction of swept configurations showing any overshoot at all) are
    measured and asserted per topology, per the Reviewer's instruction
    not to report magnitude alone. Ceilings below are this test's own
    freshly-measured worst case per topology plus a small margin -- NOT
    the Reviewer's own differently-measured ~1.28x/20-35x-incidence
    figures from the previous round, which used a different sweep
    methodology and are not directly comparable.
    """

    def setUp(self):
        common.clear_scene()

    def _worst_ratio(self, obj, cols_or_segments, seed, grading_width, jitter_amplitude, iterations):
        """Grade pin weight from 1.0 at index-group 0 (a free boundary of
        ``obj``) down to 0.0 over ``grading_width`` index-groups, where an
        "index-group" is a grid row (flat topology) or a tube ring
        (cylindrical topology) -- both are ``vertex_index //
        cols_or_segments`` given how ``common.make_grid``/``common.make_tube``
        create vertices (row/ring-major order). Returns the worst
        partially-pinned vertex's displacement divided by the worst
        fully-unpinned vertex's displacement (>1.0 means overshoot)."""
        vertex_count = len(obj.data.vertices)
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

        pin_weights = [0.0] * vertex_count
        for i in range(vertex_count):
            group = i // cols_or_segments
            if group < grading_width:
                pin_weights[i] = max(0.0, 1.0 - group / grading_width)

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

    def _sweep(self, obj_factory, cols_or_segments, seeds, grading_widths, jitter_amplitudes, iterations_list):
        """Run the full seed/grading-width/jitter/iterations grid against
        one topology (rebuilding the mesh once per combination, since
        ``relax()`` mutates nothing but the test still wants a fresh
        ``bpy`` object per ``clear_scene()`` cycle is unnecessary here --
        a single object is reused across the whole sweep for speed).
        Returns ``(worst_ratio, incidence_fraction, affected, total)``."""
        obj = obj_factory()
        worst = 0.0
        affected = 0
        total = 0
        for seed in seeds:
            for grading_width in grading_widths:
                for jitter_amplitude in jitter_amplitudes:
                    for iterations in iterations_list:
                        ratio = self._worst_ratio(
                            obj,
                            cols_or_segments,
                            seed=seed,
                            grading_width=grading_width,
                            jitter_amplitude=jitter_amplitude,
                            iterations=iterations,
                        )
                        total += 1
                        if ratio > 1.0:
                            affected += 1
                        worst = max(worst, ratio)
        incidence = affected / total if total else 0.0
        return worst, incidence, affected, total

    def _assert_topology(self, label, worst, incidence, affected, total, ratio_ceiling, incidence_ceiling):
        self.assertLessEqual(
            worst,
            ratio_ceiling,
            f"{label}: worst partial/unpinned ratio {worst:.3f}x exceeded "
            f"the {ratio_ceiling}x regression ceiling ({affected}/{total} "
            f"configurations affected, {incidence:.1%} incidence) -- "
            "re-check relax_positions()'s pin-weighted candidate blend "
            "against ARCHITECTURE.md section 7's known residual before "
            "assuming this is expected drift.",
        )
        self.assertLessEqual(
            incidence,
            incidence_ceiling,
            f"{label}: incidence {incidence:.1%} ({affected}/{total}) "
            f"exceeded the {incidence_ceiling:.1%} regression ceiling -- "
            "core/smoothing.py's relax() may have regressed on this "
            "topology.",
        )
        # The known residual is a real, reproducible overshoot on every
        # topology tested so far -- confirm the sweep actually exercises
        # it rather than trivially passing because nothing overshot.
        self.assertGreater(
            worst,
            1.0,
            f"{label}: sweep found no overshoot at all -- it may no "
            "longer be exercising the graded-boundary residual described "
            "in ARCHITECTURE.md section 7 (check grading/jitter "
            "parameters).",
        )

    def test_flat_grid_7x7_stays_under_ceiling(self):
        # x_segments=6 -> 7 verts per row/column.
        worst, incidence, affected, total = self._sweep(
            obj_factory=lambda: common.make_grid("Grid7", x_segments=6, y_segments=6, size=2.0),
            cols_or_segments=7,
            seeds=range(16),
            grading_widths=(2, 3, 4, 5),
            jitter_amplitudes=(0.03, 0.05),
            iterations_list=(10, 15, 20),
        )
        self._assert_topology(
            # Freshly measured on the shipped fix: worst=1.1935x,
            # incidence=25.0% (96/384).
            "7x7 flat grid", worst, incidence, affected, total,
            ratio_ceiling=1.22, incidence_ceiling=0.30,
        )

    def test_flat_grid_12x12_stays_under_ceiling(self):
        # x_segments=11 -> 12 verts per row/column. Reduced seed count
        # relative to the 7x7 sweep to keep runtime reasonable -- this
        # topology exists specifically because the Reviewer found the
        # 7x7-only sweep did not generalize, not to be exhaustively swept
        # itself.
        worst, incidence, affected, total = self._sweep(
            obj_factory=lambda: common.make_grid("Grid12", x_segments=11, y_segments=11, size=3.0),
            cols_or_segments=12,
            seeds=range(8),
            grading_widths=(2, 3, 4, 6),
            jitter_amplitudes=(0.03, 0.05),
            iterations_list=(10, 15, 20),
        )
        self._assert_topology(
            # Freshly measured on the shipped fix: worst=1.2990x,
            # incidence=25.5% (49/192).
            "12x12 flat grid", worst, incidence, affected, total,
            ratio_ceiling=1.35, incidence_ceiling=0.32,
        )

    def test_cylindrical_hem_ring_stays_under_ceiling(self):
        # An open-ended tube's ring 0 is a genuine free mesh boundary
        # (make_tube caps neither end), so grading pin weight outward from
        # ring 0 is a literal "Pin_Hem feathering toward a garment's free
        # edge on curved geometry" repro, per ARCHITECTURE.md section 7.
        worst, incidence, affected, total = self._sweep(
            obj_factory=lambda: common.make_tube("HemRing", segments=16, rings=10, radius=1.0, height=1.5),
            cols_or_segments=16,
            seeds=range(8),
            grading_widths=(2, 3, 4),
            jitter_amplitudes=(0.03, 0.05),
            iterations_list=(10, 15, 20),
        )
        self._assert_topology(
            # Freshly measured on the shipped fix: worst=1.4312x,
            # incidence=52.1% (75/144) -- meaningfully worse than either
            # flat-grid topology on both axes, hence its own wider
            # ceiling rather than sharing one number with the grids.
            "cylindrical hem-ring", worst, incidence, affected, total,
            ratio_ceiling=1.50, incidence_ceiling=0.58,
        )


if __name__ == "__main__":
    unittest.main()
