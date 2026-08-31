"""Tests for the bind-time-freeze card (binding schema v2).

Covers all four of the card's acceptance criteria in one file, since the
underlying defects (089ab86f, 1f8e8594, and the previously-uncarded Mode A
no-Target-Body-set trap) share ``storage.py`` and one schema version bump
-- see ARCHITECTURE.md section 7's "Bind-time reference geometry is now
frozen" entry for the full writeup:

  1. Editing/re-sculpting the source body after bind does not change Mode
     B fit output (Part A).
  2. Deleting or renaming the source body after bind no longer breaks fit
     at all (Part A).
  3. bind -> fit -> bind produces bit-identical stored bind attributes to
     the first bind (Part B), for both Mode A and Mode B.
  4. Binding with no Target Body set refuses with a clear message (Part
     C), rather than silently choosing Mode A.
  5. Mode A fit against a vertex-count-mismatched target refuses with a
     clear message (Part C).

Plus a schema-version-refusal regression (SCHEMA_VERSION bump to 2): a
binding written under an older schema version is refused at read time
with a clear message rather than silently misread.
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import binding, storage  # noqa: E402


def _make_mode_b_scene():
    """SourceBody/TargetBody with DIFFERENT vertex counts (forces Mode B
    under auto-detect) plus a Garment positioned above both."""
    source_body = common.make_grid("SourceBody", x_segments=5, y_segments=5, size=2.0)
    target_body = common.make_grid("TargetBody", x_segments=7, y_segments=7, size=2.2)
    for v in target_body.data.vertices:
        v.co.z += 0.2
    target_body.data.update()

    garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)
    garment.location = (0.0, 0.0, 0.4)

    return source_body, target_body, garment


class ModeBSourceBodyFrozenTest(unittest.TestCase):
    """Part A, acceptance criterion 1: editing the source body after bind
    must not change Mode B fit output."""

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

    def test_editing_source_body_after_bind_does_not_change_fit(self):
        source_body, target_body, garment = _make_mode_b_scene()

        settings = garment.sculpt_tool
        settings.source_body = source_body
        settings.target_body = target_body
        settings.bind_mode_override = 'AUTO'

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        self.assertEqual(garment.get(storage.PROP_BIND_MODE), storage.MODE_B)

        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})
        before = common.set_shape_key_active_positions(garment, "Fitted")

        # A real re-sculpt of the source body, not just moving the
        # object -- exactly the scenario ARCHITECTURE.md section 7 Part A
        # describes as previously silently changing the fit.
        for v in source_body.data.vertices:
            v.co.x += 0.5
            v.co.z += 0.3 * math.sin(v.co.y * 3.0)
        source_body.data.update()
        common.update_scene()

        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})
        after = common.set_shape_key_active_positions(garment, "Fitted")

        diff = common.max_component_diff(before, after)
        self.assertEqual(
            diff,
            0.0,
            f"editing the source body after bind changed the Mode B fit by {diff}",
        )


class ModeBSourceBodyMissingTest(unittest.TestCase):
    """Part A, acceptance criterion 2: deleting or renaming the source
    body after bind must no longer break fit at all."""

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

    def _bind(self, source_body, target_body, garment):
        settings = garment.sculpt_tool
        settings.source_body = source_body
        settings.target_body = target_body
        settings.bind_mode_override = 'AUTO'
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)
        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        self.assertEqual(garment.get(storage.PROP_BIND_MODE), storage.MODE_B)

    def test_deleting_source_body_after_bind_does_not_break_fit(self):
        source_body, target_body, garment = _make_mode_b_scene()
        self._bind(source_body, target_body, garment)

        bpy.data.objects.remove(source_body, do_unlink=True)

        result = bpy.ops.sculpttool.fit_garment()
        self.assertEqual(result, {'FINISHED'})

    def test_renaming_source_body_after_bind_does_not_break_fit(self):
        source_body, target_body, garment = _make_mode_b_scene()
        self._bind(source_body, target_body, garment)

        source_body.name = "RenamedSourceBody"

        result = bpy.ops.sculpttool.fit_garment()
        self.assertEqual(result, {'FINISHED'})


class BindFitBindBitIdenticalTest(unittest.TestCase):
    """Part B, acceptance criterion 3: bind -> fit -> bind must produce
    bit-identical stored bind attributes to the first bind, for both
    Mode A and Mode B -- the regression test for the empirically-verified
    089ab86f/1f8e8594-family defect (re-bind quietly reading this add-on's
    own prior 'Fitted' output as though it were the original mesh)."""

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

    def test_bind_fit_bind_is_bit_identical_mode_a(self):
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

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        first = storage.read_mode_a_binding(garment)

        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})

        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        second = storage.read_mode_a_binding(garment)

        self.assertEqual(first["body_vertex_index"], second["body_vertex_index"])
        self.assertEqual(first["normal_offset"], second["normal_offset"])
        self.assertEqual(first["tangent_offset"], second["tangent_offset"])
        self.assertEqual(first["bitangent_offset"], second["bitangent_offset"])
        self.assertEqual(first["source_vertex_count"], second["source_vertex_count"])

    def test_bind_fit_bind_is_bit_identical_mode_b(self):
        source_body, target_body, garment = _make_mode_b_scene()

        settings = garment.sculpt_tool
        settings.source_body = source_body
        settings.target_body = target_body
        settings.bind_mode_override = 'AUTO'

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        self.assertEqual(garment.get(storage.PROP_BIND_MODE), storage.MODE_B)
        first = storage.read_mode_b_binding(garment)

        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})

        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        second = storage.read_mode_b_binding(garment)

        self.assertEqual(first["triangle_index"], second["triangle_index"])
        self.assertEqual(first["barycentric"], second["barycentric"])
        self.assertEqual(first["normal_offset"], second["normal_offset"])
        self.assertEqual(first["tangent_offset_2d"], second["tangent_offset_2d"])

        anchor_diff = common.max_component_diff(
            first["source_anchor_local"], second["source_anchor_local"]
        )
        self.assertEqual(anchor_diff, 0.0)

        self.assertEqual(
            [tuple(row) for row in first["source_bind_matrix"]],
            [tuple(row) for row in second["source_bind_matrix"]],
        )


class NoTargetBodyTrapTest(unittest.TestCase):
    """Part C, acceptance criterion 4: binding with no Target Body set
    must refuse with a clear message rather than silently choosing
    Mode A."""

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

    def test_bind_with_no_target_body_refuses(self):
        source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)
        garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)

        settings = garment.sculpt_tool
        settings.source_body = source_body
        # settings.target_body intentionally left unset.
        settings.bind_mode_override = 'AUTO'

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        # bpy.ops raises RuntimeError (not a plain {'CANCELLED'} return)
        # when a REGISTER operator reports an ERROR and cancels -- Blender
        # surfaces the report as an exception to script callers rather
        # than silently returning a cancelled result set.
        with self.assertRaises(RuntimeError) as ctx:
            bpy.ops.sculpttool.bind_garment()
        self.assertIn("Target Body", str(ctx.exception))
        self.assertFalse(storage.is_bound(garment))

    def test_detect_bind_mode_raises_with_no_target(self):
        source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)
        with self.assertRaises(ValueError):
            binding.detect_bind_mode(source_body, None)

    def test_forced_mode_a_override_still_bypasses_the_check(self):
        """The 'MODE_A'/'MODE_B' override is an escape hatch that never
        calls detect_bind_mode at all -- unaffected by this fix."""
        source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)
        garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)

        settings = garment.sculpt_tool
        settings.source_body = source_body
        settings.bind_mode_override = 'MODE_A'

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        result = bpy.ops.sculpttool.bind_garment()
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(garment.get(storage.PROP_BIND_MODE), storage.MODE_A)


class ModeAVertexCountMismatchTest(unittest.TestCase):
    """Part C, acceptance criterion 5: Mode A fit against a
    vertex-count-mismatched target must refuse with a clear message."""

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

    def test_mode_a_fit_against_mismatched_target_refuses(self):
        source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)
        mismatched_target = common.make_grid(
            "Mismatched", x_segments=6, y_segments=6, size=2.2
        )
        garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)
        garment.location = (0.0, 0.0, 0.4)

        self.assertNotEqual(
            len(source_body.data.vertices), len(mismatched_target.data.vertices)
        )

        settings = garment.sculpt_tool
        settings.source_body = source_body
        settings.bind_mode_override = 'MODE_A'

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})

        settings.target_body = mismatched_target
        with self.assertRaises(RuntimeError) as ctx:
            bpy.ops.sculpttool.fit_garment()
        self.assertIn("Mode A", str(ctx.exception))
        self.assertIsNone(garment.data.shape_keys)


class SchemaVersionRefusalTest(unittest.TestCase):
    """SCHEMA_VERSION bump to 2: a binding written under an older schema
    version must be refused at read time with a clear message, not
    silently misread."""

    def setUp(self):
        common.clear_scene()

    def test_v1_binding_is_refused_with_clear_message(self):
        source_body = common.make_grid("SourceBody", x_segments=4, y_segments=4, size=2.0)
        garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=1.2)
        garment.location = (0.0, 0.0, 0.4)

        depsgraph = bpy.context.evaluated_depsgraph_get()
        result = binding.bind_mode_a(garment, source_body, depsgraph)
        storage.write_mode_a_binding(garment, source_body, result)

        # Simulate a binding saved by an older add-on version: downgrade
        # the stored version in place (write_mode_a_binding always writes
        # the current SCHEMA_VERSION).
        garment[storage.PROP_BIND_VERSION] = 1

        with self.assertRaises(storage.BindingVersionError):
            storage.read_mode_a_binding(garment)

    def test_v1_binding_error_is_a_value_error(self):
        """BindingVersionError must subclass ValueError so every existing
        fit-time ``except ValueError`` keeps working unchanged."""
        self.assertTrue(issubclass(storage.BindingVersionError, ValueError))


if __name__ == "__main__":
    unittest.main()
