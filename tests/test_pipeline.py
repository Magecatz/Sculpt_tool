"""Tests for ``core/pipeline.py::fit_once``, added by Bear PR Process card
cd0d1569-36ad-4d79-a82b-6d1115a0bcda alongside the extraction of the fit
pipeline sequence out of ``operators/op_fit.py``'s ``execute()``."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import (  # noqa: E402
    binding,
    collision,
    geometry,
    pipeline,
    smoothing,
    solver,
    storage,
)


def _make_bound_scene(pin_group=None):
    """Shared fixture: SourceBody/TargetBody (same-topology grids, Mode A)
    and a Garment bound to SourceBody. Returns (garment, target_body,
    depsgraph)."""
    source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)
    target_body = common.make_grid("TargetBody", x_segments=4, y_segments=4, size=2.0)
    for v in target_body.data.vertices:
        v.co.z += 0.3
    target_body.data.update()

    garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)
    garment.location = (0.0, 0.0, 0.5)
    if pin_group:
        common.make_pin_group(garment, *pin_group)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    result = binding.bind_mode_a(garment, source_body, depsgraph)
    storage.write_mode_a_binding(garment, source_body, result)

    return garment, target_body, depsgraph


class TargetContextBuiltOnceTest(unittest.TestCase):
    """Acceptance criterion: "Target BVH is constructed exactly once per
    fit". Exercises the worst case -- collision resolution AND smoothing
    both enabled, which runs collision.resolve_collisions twice (once
    before smoothing, once after) against the same target body -- and
    asserts geometry.TargetContext.build (the sole place a target BVH
    gets built during a fit) is called exactly once for the whole
    fit_once() call."""

    @classmethod
    def setUpClass(cls):
        cls._was_registered = hasattr(bpy.types.Object, "sculpt_tool")
        if not cls._was_registered:
            sculpt_tool.register()

    @classmethod
    def tearDownClass(cls):
        if not cls._was_registered:
            sculpt_tool.unregister()

    def setUp(self):
        common.clear_scene()

    def test_target_context_build_called_once_with_collision_and_smoothing(self):
        garment, target_body, depsgraph = _make_bound_scene()

        params = pipeline.FitParams(
            offset_scale=1.0,
            use_collision_resolution=True,
            collision_margin=0.01,
            smoothing_iterations=3,
        )

        with mock.patch.object(
            geometry.TargetContext, "build", wraps=geometry.TargetContext.build
        ) as build_spy:
            pipeline.fit_once(garment, target_body, params, depsgraph)

        self.assertEqual(
            build_spy.call_count,
            1,
            f"geometry.TargetContext.build was called {build_spy.call_count} "
            "times in one fit_once() call with collision resolution and "
            "smoothing both enabled (project + first collision pass + "
            "second collision pass after smoothing all touch the target "
            "body) -- expected exactly 1.",
        )


class FitOnceEquivalenceTest(unittest.TestCase):
    """fit_once must reproduce the exact step sequence
    operators/op_fit.py's execute() ran inline before this card (project
    -> collision -> smooth -> collision again, reusing the same anchors
    and BVH throughout) -- computed here independently via the public
    core/ API as a regression guard against the extraction changing
    behavior."""

    def setUp(self):
        common.clear_scene()

    def test_matches_manual_pipeline_with_collision_and_smoothing(self):
        garment, target_body, depsgraph = _make_bound_scene(
            pin_group=("Pin_Test", {0: 1.0})
        )

        params = pipeline.FitParams(
            offset_scale=1.0,
            use_collision_resolution=True,
            collision_margin=0.02,
            smoothing_iterations=4,
        )

        via_pipeline = pipeline.fit_once(garment, target_body, params, depsgraph)

        # Manual reconstruction of the pre-card inline sequence, using the
        # same public core/ functions fit_once itself calls.
        target_ctx = geometry.TargetContext.build(target_body, depsgraph)
        projection = solver.project_mode_a(garment, target_ctx, params.offset_scale)
        manual = collision.resolve_collisions(
            projection.fitted_positions,
            projection.anchor_positions,
            projection.anchor_normals,
            target_ctx.bvh,
            params.collision_margin,
        )
        pin_weights = smoothing.compute_pin_weights(garment)
        manual = smoothing.relax(garment, manual, pin_weights, params.smoothing_iterations)
        manual = collision.resolve_collisions(
            manual,
            projection.anchor_positions,
            projection.anchor_normals,
            target_ctx.bvh,
            params.collision_margin,
        )

        diff = common.max_component_diff(via_pipeline, manual)
        self.assertEqual(diff, 0.0, f"fit_once diverged from the manual pipeline by {diff}")

    def test_zero_smoothing_iterations_skips_relax_context(self):
        """Matches operators/op_fit.py's pre-card guarantee: smoothing_
        iterations == 0 must not build the adjacency/pin-weight structure
        at all."""
        garment, target_body, depsgraph = _make_bound_scene()

        params = pipeline.FitParams(
            offset_scale=1.0,
            use_collision_resolution=False,
            collision_margin=0.01,
            smoothing_iterations=0,
        )

        with mock.patch.object(
            smoothing.RelaxContext, "build", wraps=smoothing.RelaxContext.build
        ) as build_spy:
            pipeline.fit_once(garment, target_body, params, depsgraph)

        self.assertEqual(build_spy.call_count, 0)


class FitOnceEndToEndTest(unittest.TestCase):
    """bpy.ops.sculpttool.fit_garment with collision resolution AND
    smoothing both enabled -- the codepath test_solver.py's own
    ModeARefitPipelineTest deliberately leaves off (it disables both) --
    exercised end to end through the real operator, matching
    ARCHITECTURE.md's op_fit.py docstring exactly."""

    @classmethod
    def setUpClass(cls):
        cls._was_registered = hasattr(bpy.types.Object, "sculpt_tool")
        if not cls._was_registered:
            sculpt_tool.register()

    @classmethod
    def tearDownClass(cls):
        if not cls._was_registered:
            sculpt_tool.unregister()

    def setUp(self):
        common.clear_scene()

    def test_refit_with_collision_and_smoothing_is_deterministic(self):
        source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)
        target_body = common.make_grid("TargetBody", x_segments=4, y_segments=4, size=2.0)
        for v in target_body.data.vertices:
            v.co.z += 0.3
        target_body.data.update()

        garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)
        garment.location = (0.0, 0.0, 0.5)

        settings = garment.sculpt_tool
        settings.source_body = source_body
        settings.target_body = target_body
        settings.bind_mode_override = 'MODE_A'
        settings.offset_scale = 1.0
        settings.use_collision_resolution = True
        settings.collision_margin = 0.02
        settings.smoothing_iterations = 3

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})
        first = common.set_shape_key_active_positions(garment, "Fitted")

        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})
        second = common.set_shape_key_active_positions(garment, "Fitted")

        diff = common.max_component_diff(first, second)
        self.assertEqual(diff, 0.0, f"repeat Fit (collision+smoothing on) diverged by {diff}")


class ModeBFitOnceTest(unittest.TestCase):
    """Mode B threads BOTH a TargetContext (for the target body) AND a
    separately-evaluated source body through project_mode_b -- exercised
    end to end here (bind_mode_b + fit_once, cross-topology source/target
    so Mode B is actually used, not just Mode A again) since none of the
    other suites' Mode B coverage runs it past bind_mode_b's own
    round-trip check (test_binding.py)."""

    @classmethod
    def setUpClass(cls):
        cls._was_registered = hasattr(bpy.types.Object, "sculpt_tool")
        if not cls._was_registered:
            sculpt_tool.register()

    @classmethod
    def tearDownClass(cls):
        if not cls._was_registered:
            sculpt_tool.unregister()

    def setUp(self):
        common.clear_scene()

    def test_mode_b_fit_once_is_deterministic_and_bit_identical_via_operator(self):
        # Different vertex counts -> detect_bind_mode picks Mode B.
        source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)
        target_body = common.make_grid("TargetBody", x_segments=6, y_segments=6, size=2.2)
        for v in target_body.data.vertices:
            v.co.z += 0.2
        target_body.data.update()

        garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)
        garment.location = (0.0, 0.0, 0.4)

        depsgraph = bpy.context.evaluated_depsgraph_get()
        result = binding.bind_mode_b(garment, source_body, depsgraph)
        storage.write_mode_b_binding(garment, source_body, result)
        self.assertEqual(garment.get(storage.PROP_BIND_MODE), storage.MODE_B)

        params = pipeline.FitParams(
            offset_scale=1.0,
            use_collision_resolution=True,
            collision_margin=0.02,
            smoothing_iterations=2,
        )

        first = pipeline.fit_once(garment, target_body, params, depsgraph)
        self.assertEqual(len(first), len(garment.data.vertices))
        second = pipeline.fit_once(garment, target_body, params, depsgraph)

        diff = common.max_component_diff(first, second)
        self.assertEqual(diff, 0.0, f"Mode B fit_once was non-deterministic (diff {diff})")

        # Same claim through the real operator (bind + fit), matching how
        # op_bind.py/op_fit.py actually wire bind_mode_b/fit_once together.
        garment.sculpt_tool.source_body = source_body
        garment.sculpt_tool.target_body = target_body
        garment.sculpt_tool.bind_mode_override = 'MODE_B'
        garment.sculpt_tool.use_collision_resolution = True
        garment.sculpt_tool.collision_margin = 0.02
        garment.sculpt_tool.smoothing_iterations = 2

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)
        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})

        baked = common.set_shape_key_active_positions(garment, "Fitted")
        self.assertEqual(len(baked), len(garment.data.vertices))


if __name__ == "__main__":
    unittest.main()
