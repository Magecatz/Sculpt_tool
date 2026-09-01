"""Tests for ``operators/op_batch.py``'s ``OT_batch_fit``, added by the
Batch/automated-fitting Bear PR Process card.

Covers this card's acceptance criteria: distinguishable per-target
output (both Mode A and Mode B), graceful per-target failure without
aborting the rest of the batch run, deterministic (no cloth-sim/other
nondeterministic pass) output, and the two structural reuse invariants
(the garment's RelaxContext built exactly once per BATCH run, not once
per target; each target's TargetContext built exactly once per TARGET,
not twice) -- mirroring ``tests/test_pipeline.py``'s
``TargetContextBuiltOnceTest``/``FitOnceEquivalenceTest`` pattern, but
across a whole batch run instead of a single ``fit_once`` call.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import binding, geometry, pipeline, smoothing, storage  # noqa: E402


def _register_case(cls):
    """setUpClass/tearDownClass pair shared by every TestCase below --
    matches tests/test_pipeline.py's own repeated pattern exactly."""

    @classmethod
    def setUpClass(inner_cls):
        inner_cls._was_registered = hasattr(bpy.types.Object, "sculpt_tool")
        if not inner_cls._was_registered:
            sculpt_tool.register()

    @classmethod
    def tearDownClass(inner_cls):
        if not inner_cls._was_registered:
            sculpt_tool.unregister()

    cls.setUpClass = setUpClass
    cls.tearDownClass = tearDownClass
    return cls


def _move_to_collection(obj, collection):
    """Unlink ``obj`` from every Collection it's currently in (whatever
    ``bpy.context.collection`` resolved to for ``common.make_grid``'s own
    link call -- not necessarily ``scene.collection`` directly) and link
    it into ``collection`` only, so a test's target Collection contains
    exactly the objects it's meant to and nothing gets left dangling in
    whatever collection it was created in."""
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    collection.objects.link(obj)


def _make_mode_a_scene(n_targets=3, pin_group=None):
    """SourceBody + Garment bound Mode A, plus ``n_targets`` same-topology
    (shape-key-variant-style) target bodies collected into a fresh
    Collection named 'Targets'. Returns
    (garment, source_body, targets, collection)."""
    source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)

    garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)
    garment.location = (0.0, 0.0, 0.5)
    if pin_group:
        common.make_pin_group(garment, *pin_group)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    result = binding.bind_mode_a(garment, source_body, depsgraph)
    storage.write_mode_a_binding(garment, source_body, result)

    collection = bpy.data.collections.new("Targets")
    bpy.context.scene.collection.children.link(collection)

    targets = []
    for i in range(n_targets):
        target = common.make_grid(
            f"Target{i}", x_segments=4, y_segments=4, size=2.0
        )
        for v in target.data.vertices:
            v.co.z += 0.2 + 0.15 * i  # distinct shape variant per target
        target.data.update()
        common.update_scene()
        _move_to_collection(target, collection)
        targets.append(target)

    return garment, source_body, targets, collection


def _run_batch(garment, collection, offset_scale=1.0, use_collision_resolution=True,
                collision_margin=0.02, smoothing_iterations=0):
    settings = garment.sculpt_tool
    settings.batch_target_collection = collection
    settings.offset_scale = offset_scale
    settings.use_collision_resolution = use_collision_resolution
    settings.collision_margin = collision_margin
    settings.smoothing_iterations = smoothing_iterations

    bpy.context.view_layer.objects.active = garment
    garment.select_set(True)
    return bpy.ops.sculpttool.batch_fit()


@_register_case
class BatchFitDistinguishableOutputTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()

    def test_each_target_gets_its_own_correct_distinguishable_shape_key(self):
        garment, source_body, targets, collection = _make_mode_a_scene(n_targets=3)

        result = _run_batch(garment, collection, smoothing_iterations=0)
        self.assertEqual(result, {'FINISHED'})

        key_blocks = garment.data.shape_keys.key_blocks
        baked = {}
        for target in targets:
            key_name = f"Fitted_{target.name}"
            self.assertIn(key_name, key_blocks.keys())
            baked[target.name] = common.set_shape_key_active_positions(garment, key_name)

        # Every target's baked result must match fit_once() called
        # directly against that SAME target (correctness), and must
        # differ from every OTHER target's baked result (distinguishable
        # -- each target is a different shape).
        depsgraph = bpy.context.evaluated_depsgraph_get()
        params = pipeline.FitParams(
            offset_scale=1.0, use_collision_resolution=True,
            collision_margin=0.02, smoothing_iterations=0,
        )
        for target in targets:
            expected_world = pipeline.fit_once(garment, target, params, depsgraph)
            matrix_inverse = garment.matrix_world.inverted_safe()
            expected_world_via_local = [
                garment.matrix_world @ (matrix_inverse @ co) for co in expected_world
            ]
            diff = common.max_component_diff(baked[target.name], expected_world_via_local)
            self.assertLess(diff, 1e-5, f"{target.name}'s baked result diverged by {diff}")

        names = list(baked.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                diff = common.max_component_diff(baked[names[i]], baked[names[j]])
                self.assertGreater(
                    diff, 1e-4,
                    f"{names[i]} and {names[j]} produced indistinguishable results",
                )


@_register_case
class BatchFitModeBDistinguishableOutputTest(unittest.TestCase):
    """Same distinguishable-output claim, but for a Mode B (cross-
    topology) binding, and with the targets themselves at DIFFERENT
    topologies from each other too -- Mode B, unlike Mode A, has no
    same-topology requirement between garment/source/targets at all, so
    this is the natural place to exercise a genuinely heterogeneous
    batch collection."""

    def setUp(self):
        common.clear_scene()

    def test_mode_b_batch_produces_distinguishable_results_across_mixed_topologies(self):
        source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)
        garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)
        garment.location = (0.0, 0.0, 0.4)

        depsgraph = bpy.context.evaluated_depsgraph_get()
        result = binding.bind_mode_b(garment, source_body, depsgraph)
        storage.write_mode_b_binding(garment, source_body, result)
        self.assertEqual(garment.get(storage.PROP_BIND_MODE), storage.MODE_B)

        collection = bpy.data.collections.new("MixedTargets")
        bpy.context.scene.collection.children.link(collection)

        target_a = common.make_grid("TargetA", x_segments=6, y_segments=6, size=2.2)
        for v in target_a.data.vertices:
            v.co.z += 0.2
        target_a.data.update()

        target_b = common.make_grid("TargetB", x_segments=5, y_segments=8, size=2.6)
        for v in target_b.data.vertices:
            v.co.z += 0.5
        target_b.data.update()

        for target in (target_a, target_b):
            common.update_scene()
            _move_to_collection(target, collection)

        result_dict = _run_batch(garment, collection, smoothing_iterations=2)
        self.assertEqual(result_dict, {'FINISHED'})

        key_blocks = garment.data.shape_keys.key_blocks
        self.assertIn("Fitted_TargetA", key_blocks.keys())
        self.assertIn("Fitted_TargetB", key_blocks.keys())

        pos_a = common.set_shape_key_active_positions(garment, "Fitted_TargetA")
        pos_b = common.set_shape_key_active_positions(garment, "Fitted_TargetB")
        diff = common.max_component_diff(pos_a, pos_b)
        self.assertGreater(diff, 1e-4, "Mode B batch produced indistinguishable results")


@_register_case
class BatchFitGracefulFailureTest(unittest.TestCase):
    """Acceptance criterion: "A target body with no valid binding
    correspondence ... fails gracefully for that target with a clear
    error/warning, without aborting the rest of the batch run."""

    def setUp(self):
        common.clear_scene()

    def test_mode_a_topology_mismatch_target_is_skipped_not_fatal(self):
        garment, source_body, targets, collection = _make_mode_a_scene(n_targets=2)

        # A cross-topology target: Mode A binding requires the target's
        # vertex count to match the SOURCE body's (25 here); this one has
        # a different vertex count and cannot be projected under Mode A.
        bad_target = common.make_grid("BadTarget", x_segments=7, y_segments=7, size=2.0)
        common.update_scene()
        _move_to_collection(bad_target, collection)

        result = _run_batch(garment, collection, smoothing_iterations=0)
        self.assertEqual(result, {'FINISHED'})

        key_blocks = garment.data.shape_keys.key_blocks
        for target in targets:
            self.assertIn(f"Fitted_{target.name}", key_blocks.keys())
        self.assertNotIn("Fitted_BadTarget", key_blocks.keys())

    def test_all_targets_failing_reports_error_and_cancels(self):
        garment, source_body, targets, collection = _make_mode_a_scene(n_targets=0)

        bad_target = common.make_grid("BadTarget", x_segments=9, y_segments=9, size=2.0)
        common.update_scene()
        _move_to_collection(bad_target, collection)

        with self.assertRaises(RuntimeError):
            _run_batch(garment, collection, smoothing_iterations=0)


@_register_case
class BatchFitDeterministicOutputTest(unittest.TestCase):
    """Acceptance criterion: "No cloth-simulation or other nondeterministic
    refinement pass is invoked by default in batch mode." Exercised
    behaviorally (matching tests/test_pipeline.py's
    FitOnceEquivalenceTest/ModeBFitOnceTest convention: bit-identical
    repeat-run output is the project's standing way of demonstrating "no
    hidden nondeterminism"), with collision resolution AND smoothing both
    enabled -- the combination most likely to surface any nondeterministic
    step, if one existed."""

    def setUp(self):
        common.clear_scene()

    def test_repeat_batch_runs_are_bit_identical(self):
        garment, source_body, targets, collection = _make_mode_a_scene(n_targets=2)

        self.assertEqual(
            _run_batch(garment, collection, smoothing_iterations=3), {'FINISHED'}
        )
        first = {
            t.name: common.set_shape_key_active_positions(garment, f"Fitted_{t.name}")
            for t in targets
        }

        self.assertEqual(
            _run_batch(garment, collection, smoothing_iterations=3), {'FINISHED'}
        )
        second = {
            t.name: common.set_shape_key_active_positions(garment, f"Fitted_{t.name}")
            for t in targets
        }

        for name in first:
            diff = common.max_component_diff(first[name], second[name])
            self.assertEqual(diff, 0.0, f"Batch Fit was non-deterministic for {name}")


@_register_case
class BatchFitStructuralInvariantsTest(unittest.TestCase):
    """The card's STRUCTURAL acceptance criteria, checked directly via
    call-count spies (same mocking technique as
    tests/test_pipeline.py::TargetContextBuiltOnceTest /
    FitOnceEquivalenceTest::test_zero_smoothing_iterations_skips_relax_context):

    - smoothing.RelaxContext.build must be called exactly ONCE for the
      whole batch run (the garment's adjacency/edge/pin invariants do not
      depend on the target body), not once per target.
    - geometry.TargetContext.build must be called exactly once PER
      TARGET (each target's own evaluated mesh/triangulation/BVH is
      genuinely per-target work), not twice per target and not once for
      the whole run.
    """

    def setUp(self):
        common.clear_scene()

    def test_relax_context_built_once_per_batch_run_not_once_per_target(self):
        garment, source_body, targets, collection = _make_mode_a_scene(n_targets=4)

        with mock.patch.object(
            smoothing.RelaxContext, "build", wraps=smoothing.RelaxContext.build
        ) as build_spy:
            result = _run_batch(garment, collection, smoothing_iterations=2)

        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(
            build_spy.call_count, 1,
            f"RelaxContext.build was called {build_spy.call_count} times across a "
            f"{len(targets)}-target batch run -- expected exactly 1 (built once, "
            "reused for every target).",
        )

    def test_relax_context_never_built_when_smoothing_disabled(self):
        garment, source_body, targets, collection = _make_mode_a_scene(n_targets=3)

        with mock.patch.object(
            smoothing.RelaxContext, "build", wraps=smoothing.RelaxContext.build
        ) as build_spy:
            result = _run_batch(garment, collection, smoothing_iterations=0)

        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(build_spy.call_count, 0)

    def test_target_context_built_exactly_once_per_target(self):
        garment, source_body, targets, collection = _make_mode_a_scene(n_targets=4)

        with mock.patch.object(
            geometry.TargetContext, "build", wraps=geometry.TargetContext.build
        ) as build_spy:
            result = _run_batch(
                garment, collection, use_collision_resolution=True, smoothing_iterations=2
            )

        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(
            build_spy.call_count, len(targets),
            f"TargetContext.build was called {build_spy.call_count} times across a "
            f"{len(targets)}-target batch run (collision+smoothing both on, so each "
            "target's fit_once runs the collision pass twice) -- expected exactly "
            f"{len(targets)} (once per target, never rebuilt within a single "
            "target's own fit).",
        )


if __name__ == "__main__":
    unittest.main()
