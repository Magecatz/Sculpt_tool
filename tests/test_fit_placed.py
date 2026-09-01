"""Tests for the fit consuming the armature-placed garment (roadmap R8).

Verifies that when a target base rig is present, Fit places the garment
(position + scale), conforms the PLACED garment, bakes it, and mutes the
garment's Armature modifier so the placement isn't applied twice (no
double-deformation).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import storage  # noqa: E402

# Garment rig and a target rig shifted UP by 0.4 (a taller base).
_GARMENT_RIG = [("Hips", (0.0, 0.0, 0.0), (0.0, 0.0, 0.2), None)]
_TARGET_RIG = [("Hips", (0.0, 0.0, 0.4), (0.0, 0.0, 0.6), None)]


class FitConsumesPlacedTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def _eval_positions(self, obj):
        common.update_scene()
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        mesh = ev.to_mesh()
        mw = obj.matrix_world
        pts = [mw @ v.co for v in mesh.vertices]
        ev.to_mesh_clear()
        return pts

    def _scene(self):
        source = common.make_grid("Source", x_segments=4, y_segments=4)
        garment = common.make_grid("Garment", x_segments=4, y_segments=4,
                                   location=(0.0, 0.0, 0.1))
        target = common.make_grid("Target", x_segments=4, y_segments=4,
                                  location=(0.0, 0.0, 0.4))  # body matches taller rig
        garment_rig = common.make_armature("GRig", _GARMENT_RIG)
        target_rig = common.make_armature("TRig", _TARGET_RIG)
        common.skin_mesh_all_to_bone(garment, garment_rig, "Hips")

        s = garment.sculpt_tool
        s.source_body = source
        s.target_body = target
        s.bind_mode_override = 'MODE_A'
        s.target_base_armature = target_rig
        s.skip_alignment_check = True
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)
        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        return garment, garment_rig

    def test_fit_bakes_placed_garment_and_mutes_armature(self):
        garment, garment_rig = self._scene()
        before_z = sum(p.z for p in self._eval_positions(garment)) / 25

        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})

        # Armature deform hidden so the baked placement isn't applied twice.
        arm_mods = [m for m in garment.modifiers if m.type == 'ARMATURE']
        self.assertTrue(arm_mods and not arm_mods[0].show_viewport)

        # The garment moved UP with the taller target rig (~+0.4): the fit
        # consumed the placement, not a frozen source-body projection.
        after = common.set_shape_key_active_positions(garment, storage.FITTED_SHAPE_KEY_NAME)
        after_z = sum(p.z for p in after) / len(after)
        self.assertGreater(after_z, before_z + 0.25)

    def test_no_double_deformation(self):
        garment, garment_rig = self._scene()
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})

        # With the armature muted, the evaluated garment equals the Fitted
        # key exactly -- the placement is applied ONCE (baked), not again by
        # a live armature. (If the armature were still deforming the baked
        # key, these would diverge.)
        evaluated = self._eval_positions(garment)
        key_world = common.set_shape_key_active_positions(garment, storage.FITTED_SHAPE_KEY_NAME)
        self.assertEqual(len(evaluated), len(key_world))
        self.assertLess(common.max_component_diff(evaluated, key_world), 1e-4)

    def test_refit_is_stable(self):
        # A second fit re-enables the armature, re-places, and re-bakes to
        # the same result -- no drift/accumulation.
        garment, garment_rig = self._scene()
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})
        first = common.set_shape_key_active_positions(garment, storage.FITTED_SHAPE_KEY_NAME)
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})
        second = common.set_shape_key_active_positions(garment, storage.FITTED_SHAPE_KEY_NAME)
        self.assertLess(common.max_component_diff(first, second), 1e-4)


if __name__ == "__main__":
    unittest.main()
