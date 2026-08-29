"""End-to-end Mode A fit pipeline tests, via the real operators.

Exercises ``bpy.ops.sculpttool.bind_garment`` / ``fit_garment`` directly
(not just ``core.solver`` in isolation) because "no duplicate Fitted
keys" and "base mesh untouched" are properties of ``operators/op_fit.py``'s
Shape Key bake, not of ``core.solver`` alone.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import solver  # noqa: E402


class ModeARefitPipelineTest(unittest.TestCase):
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

        self.source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)
        self.target_body = common.make_grid("TargetBody", x_segments=4, y_segments=4, size=2.0)
        # Same topology (Mode A requirement) but a genuinely different
        # shape, so refitting actually moves the garment.
        for v in self.target_body.data.vertices:
            v.co.z += 0.3
        self.target_body.data.update()

        self.garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)
        self.garment.location = (0.0, 0.0, 0.5)

        settings = self.garment.sculpt_tool
        settings.source_body = self.source_body
        settings.target_body = self.target_body
        settings.bind_mode_override = 'MODE_A'
        settings.offset_scale = 1.0
        settings.use_collision_resolution = False
        settings.smoothing_iterations = 0

        bpy.context.view_layer.objects.active = self.garment
        self.garment.select_set(True)

    def _bind(self):
        result = bpy.ops.sculpttool.bind_garment()
        self.assertEqual(result, {'FINISHED'})

    def _fit(self):
        result = bpy.ops.sculpttool.fit_garment()
        self.assertEqual(result, {'FINISHED'})

    def test_base_mesh_untouched_by_fit(self):
        self._bind()
        before = [tuple(v.co) for v in self.garment.data.vertices]
        self._fit()
        after = [tuple(v.co) for v in self.garment.data.vertices]
        self.assertEqual(before, after)

    def test_no_duplicate_fitted_key_on_repeat_fit(self):
        self._bind()
        self._fit()
        self._fit()
        self._fit()

        key_blocks = self.garment.data.shape_keys.key_blocks
        fitted_names = [kb.name for kb in key_blocks if kb.name == "Fitted"]
        self.assertEqual(
            fitted_names,
            ["Fitted"],
            f"expected exactly one 'Fitted' key block, got key blocks: "
            f"{[kb.name for kb in key_blocks]}",
        )

    def test_refit_is_deterministic(self):
        self._bind()
        self._fit()
        first = common.set_shape_key_active_positions(self.garment, "Fitted")
        self._fit()
        second = common.set_shape_key_active_positions(self.garment, "Fitted")

        diff = common.max_component_diff(first, second)
        self.assertEqual(diff, 0.0, f"repeat Fit produced a different result (diff {diff})")

    def test_core_project_mode_a_is_deterministic(self):
        """Same claim, one layer down: calling core.solver directly twice
        with unchanged inputs must be bit-identical."""
        self._bind()
        first = solver.project_mode_a(self.garment, self.target_body, 1.0)
        second = solver.project_mode_a(self.garment, self.target_body, 1.0)
        diff = common.max_component_diff(first.fitted_positions, second.fitted_positions)
        self.assertEqual(diff, 0.0)


if __name__ == "__main__":
    unittest.main()
