"""OT_batch_conform operator test: conforms every selected garment that is
set up, skips those that aren't, and doesn't abort the batch on a skip.

Uses flat-grid garments over a flat-grid target (no rig -> the conform's
unposed path: placed == rest, source-free standoff, project + bake), so it
exercises the operator/selection wiring without needing the asset corpus.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import storage  # noqa: E402


class BatchConformTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def _has_fitted(self, obj):
        return (obj.data.shape_keys is not None
                and obj.data.shape_keys.key_blocks.get(storage.FITTED_SHAPE_KEY_NAME) is not None)

    def test_conforms_valid_and_skips_unconfigured(self):
        target = common.make_grid("Target", x_segments=6, y_segments=6, size=2.0)
        valid = common.make_grid("Valid", x_segments=4, y_segments=4, size=1.0,
                                  location=(0.0, 0.0, 0.1))
        valid.sculpt_tool.target_body = target
        unconfigured = common.make_grid("NoTarget", x_segments=4, y_segments=4,
                                        location=(0.0, 0.0, 0.1))  # no target_body set

        bpy.ops.object.select_all(action='DESELECT')
        valid.select_set(True)
        unconfigured.select_set(True)
        bpy.context.view_layer.objects.active = valid

        # A skip (the unconfigured garment) must NOT abort the batch: the valid
        # one still conforms, so the operator finishes.
        self.assertEqual(bpy.ops.sculpttool.batch_conform(), {'FINISHED'})
        self.assertTrue(self._has_fitted(valid))
        self.assertFalse(self._has_fitted(unconfigured))

    def test_all_unconfigured_errors(self):
        # Nothing set up at all -> nothing conformed. The operator reports
        # {'ERROR'} (so bpy.ops raises RuntimeError, per Blender), rather than
        # a silent FINISHED that did no work.
        a = common.make_grid("A", x_segments=3, y_segments=3)
        b = common.make_grid("B", x_segments=3, y_segments=3)
        bpy.ops.object.select_all(action='DESELECT')
        a.select_set(True)
        b.select_set(True)
        bpy.context.view_layer.objects.active = a
        with self.assertRaises(RuntimeError):
            bpy.ops.sculpttool.batch_conform()


if __name__ == "__main__":
    unittest.main()
