"""Registration/unregistration smoke test under Blender 5.2.1.

Every card to date was verified statically ("no Blender/bpy in this
env"); this is the first check that the add-on actually registers and
unregisters cleanly against a real Blender, not just that its Python
parses.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402


class RegistrationSmokeTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        # Leave the addon unregistered before this test's own assertions,
        # regardless of what an earlier test module in the same
        # --background process left behind.
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def test_register_exposes_expected_surface(self):
        sculpt_tool.register()
        try:
            # bpy.types exposes a registered RNA class by its Python class
            # name -- a reliable register()/unregister() signal, unlike
            # bpy.ops: bpy.ops.<category>.<name> resolves lazily and does
            # NOT reliably reflect whether that operator id is actually
            # registered via hasattr (only *calling*/polling it does), so
            # it's not used here as a presence check.
            self.assertTrue(hasattr(bpy.types.Object, "sculpt_tool"))
            self.assertTrue(hasattr(bpy.types, "SCULPTTOOL_OT_bind_garment"))
            self.assertTrue(hasattr(bpy.types, "SCULPTTOOL_OT_fit_garment"))
            self.assertTrue(hasattr(bpy.types, "SCULPTTOOL_OT_batch_fit"))

            obj = common.make_grid("Probe", x_segments=1, y_segments=1)
            self.assertTrue(hasattr(obj, "sculpt_tool"))
            self.assertIsNone(obj.sculpt_tool.source_body)

            # The operator is genuinely callable too, not just present in
            # the RNA registry: poll() should run without raising (it may
            # legitimately return False -- Probe has no source_body set).
            bpy.context.view_layer.objects.active = obj
            self.assertFalse(bpy.ops.sculpttool.bind_garment.poll())
        finally:
            sculpt_tool.unregister()

    def test_unregister_removes_expected_surface(self):
        sculpt_tool.register()
        sculpt_tool.unregister()
        self.assertFalse(hasattr(bpy.types.Object, "sculpt_tool"))
        self.assertFalse(hasattr(bpy.types, "SCULPTTOOL_OT_bind_garment"))
        self.assertFalse(hasattr(bpy.types, "SCULPTTOOL_OT_fit_garment"))
        self.assertFalse(hasattr(bpy.types, "SCULPTTOOL_OT_batch_fit"))

    def test_register_unregister_is_repeatable(self):
        # A Tester re-running this suite in the same Blender session (or
        # a live addon reload) must not hit a "class already registered"
        # RNA error.
        for _ in range(3):
            sculpt_tool.register()
            sculpt_tool.unregister()


if __name__ == "__main__":
    unittest.main()
