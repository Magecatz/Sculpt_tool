"""Regression: smoothing_iterations > 0 with a FACELESS Mode A target
(Backlog card 9aeffb26).

The faceless-target fix (card e6763cc5, lazy TargetContext.triangles/.bvh)
was tested for Mode A + collision-off and Mode B + faceless, but NOT for the
combination smoothing_iterations > 0 + faceless target + collision off.
fit_once dispatches smoothing with no reference to the target body, so it
should be unaffected -- this test pins that down: a Mode A fit onto a
vertexed-but-faceless target, collision off, smoothing on, completes and
never triangulates/BVH-builds the (faceless) target.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bmesh  # noqa: E402
import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import storage  # noqa: E402


def _faceless_like(name, source_obj, dz=0.0):
    """A verts-only (no faces) mesh with the SAME vertex positions as
    ``source_obj`` (so a Mode A binding's vertex-count/index match holds),
    optionally shifted in Z."""
    bm = bmesh.new()
    for v in source_obj.data.vertices:
        bm.verts.new((v.co.x, v.co.y, v.co.z + dz))
    obj = common.link_object(name, bm)
    common.update_scene()
    return obj


class FacelessSmoothingTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def test_mode_a_faceless_target_with_smoothing(self):
        source = common.make_grid("Source", x_segments=4, y_segments=4)
        garment = common.make_grid("Garment", x_segments=4, y_segments=4)
        target = _faceless_like("FacelessTarget", source, dz=0.05)
        self.assertEqual(len(target.data.polygons), 0)  # genuinely faceless

        s = garment.sculpt_tool
        s.source_body = source
        s.target_body = target
        s.bind_mode_override = 'MODE_A'
        s.use_collision_resolution = False   # so the BVH is never needed
        s.smoothing_iterations = 3           # the untested-with-faceless knob
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        # The combination that was previously untested: Mode A + faceless
        # target + collision off + smoothing on -> completes, no "no
        # triangulatable faces" error.
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})
        self.assertIsNotNone(
            garment.data.shape_keys.key_blocks.get(storage.FITTED_SHAPE_KEY_NAME)
        )

    def test_collision_on_faceless_target_still_errors(self):
        # Sanity contrast: turning collision ON against a faceless target
        # DOES need the BVH and fails cleanly (unchanged behavior).
        source = common.make_grid("Source", x_segments=4, y_segments=4)
        garment = common.make_grid("Garment", x_segments=4, y_segments=4)
        target = _faceless_like("FacelessTarget", source, dz=0.05)

        s = garment.sculpt_tool
        s.source_body = source
        s.target_body = target
        s.bind_mode_override = 'MODE_A'
        s.use_collision_resolution = True
        s.smoothing_iterations = 3
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)
        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        with self.assertRaises(RuntimeError):   # "no triangulatable faces"
            bpy.ops.sculpttool.fit_garment()


if __name__ == "__main__":
    unittest.main()
