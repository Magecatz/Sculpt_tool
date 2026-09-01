"""Tests for ``core/rig.py`` and the Detect Rigs operator (roadmap R1).

Covers the "base"-concept foundation: resolving the armature that deforms
a mesh (via modifier and via parent), reading a rig's bone names, the
``RigInfo`` summary, and ``OT_detect_rigs`` auto-filling the source/target
base rig pickers from the Source/Target Body (with the garment's own rig
as the source-side fallback). No armature-driven posing or bone matching
is exercised here -- that's roadmap R2/R3; this card only makes the tool
*aware* of rigs.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import rig  # noqa: E402

# A small synthetic humanoid-ish bone spec: (name, head, tail, parent).
_HUMANOID_BONES = [
    ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
    ("Spine", (0.0, 0.0, 1.2), (0.0, 0.0, 1.5), "Hips"),
    ("Arm.L", (0.2, 0.0, 1.5), (0.6, 0.0, 1.5), "Spine"),
    ("Arm.R", (-0.2, 0.0, 1.5), (-0.6, 0.0, 1.5), "Spine"),
    ("Leg.L", (0.1, 0.0, 1.0), (0.1, 0.0, 0.5), "Hips"),
    ("Leg.R", (-0.1, 0.0, 1.0), (-0.1, 0.0, 0.5), "Hips"),
]


class RigAwarenessTest(unittest.TestCase):
    """Pure ``core.rig`` logic -- no addon registration needed (builds
    armatures directly, mirroring the other ``core/`` tests)."""

    def setUp(self):
        common.clear_scene()

    def test_deforming_armature_via_modifier(self):
        mesh = common.make_grid("Garment", x_segments=2, y_segments=2)
        arm = common.make_armature("Rig", _HUMANOID_BONES)
        common.bind_mesh_to_armature(mesh, arm)
        self.assertIs(rig.deforming_armature(mesh), arm)

    def test_deforming_armature_via_parent(self):
        mesh = common.make_grid("Garment", x_segments=2, y_segments=2)
        arm = common.make_armature("Rig", _HUMANOID_BONES)
        # Parented to the armature but with NO armature modifier.
        mesh.parent = arm
        common.update_scene()
        self.assertIs(rig.deforming_armature(mesh), arm)

    def test_deforming_armature_none_for_unrigged_mesh(self):
        mesh = common.make_grid("Static", x_segments=2, y_segments=2)
        self.assertIsNone(rig.deforming_armature(mesh))

    def test_deforming_armature_none_for_none(self):
        self.assertIsNone(rig.deforming_armature(None))

    def test_modifier_wins_over_parent(self):
        # A mesh both parented to one armature AND modifier-driven by
        # another resolves to the modifier's armature (most specific).
        mesh = common.make_grid("Garment", x_segments=2, y_segments=2)
        parent_rig = common.make_armature("ParentRig", _HUMANOID_BONES)
        modifier_rig = common.make_armature("ModifierRig", _HUMANOID_BONES)
        mesh.parent = parent_rig
        common.bind_mesh_to_armature(mesh, modifier_rig)
        self.assertIs(rig.deforming_armature(mesh), modifier_rig)

    def test_bone_names_in_order(self):
        arm = common.make_armature("Rig", _HUMANOID_BONES)
        names = rig.bone_names(arm)
        self.assertEqual(set(names), {b[0] for b in _HUMANOID_BONES})
        self.assertEqual(len(names), len(_HUMANOID_BONES))

    def test_bone_names_empty_for_non_armature(self):
        mesh = common.make_grid("Static", x_segments=1, y_segments=1)
        self.assertEqual(rig.bone_names(mesh), [])
        self.assertEqual(rig.bone_names(None), [])

    def test_riginfo_describe(self):
        arm = common.make_armature("Rig", _HUMANOID_BONES)
        info = rig.RigInfo.describe(arm)
        self.assertIsNotNone(info)
        self.assertEqual(info.name, "Rig")
        self.assertEqual(info.bone_count, len(_HUMANOID_BONES))
        # Only "Hips" has no parent in the spec.
        self.assertEqual(info.root_bones, ["Hips"])

    def test_riginfo_describe_none_for_non_armature(self):
        mesh = common.make_grid("Static", x_segments=1, y_segments=1)
        self.assertIsNone(rig.RigInfo.describe(mesh))
        self.assertIsNone(rig.RigInfo.describe(None))


class DetectRigsOperatorTest(unittest.TestCase):
    """``OT_detect_rigs`` auto-fill behavior -- needs the addon registered
    (it drives ``obj.sculpt_tool`` and ``bpy.ops.sculpttool.detect_rigs``)."""

    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def _activate(self, obj):
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

    def test_detect_fills_both_base_rigs_from_bodies(self):
        garment = common.make_grid("Garment", x_segments=2, y_segments=2)
        source_body = common.make_grid("SourceBody", x_segments=3, y_segments=3)
        target_body = common.make_grid("TargetBody", x_segments=3, y_segments=3)
        source_rig = common.make_armature("SourceRig", _HUMANOID_BONES)
        target_rig = common.make_armature("TargetRig", _HUMANOID_BONES)
        common.bind_mesh_to_armature(source_body, source_rig)
        common.bind_mesh_to_armature(target_body, target_rig)

        garment.sculpt_tool.source_body = source_body
        garment.sculpt_tool.target_body = target_body
        self._activate(garment)

        result = bpy.ops.sculpttool.detect_rigs()
        self.assertEqual(result, {'FINISHED'})
        self.assertIs(garment.sculpt_tool.source_base_armature, source_rig)
        self.assertIs(garment.sculpt_tool.target_base_armature, target_rig)

    def test_detect_source_falls_back_to_garment_rig(self):
        # Source Body has no rig -> the source side falls back to the
        # garment's own deforming armature.
        garment = common.make_grid("Garment", x_segments=2, y_segments=2)
        garment_rig = common.make_armature("GarmentRig", _HUMANOID_BONES)
        common.bind_mesh_to_armature(garment, garment_rig)
        source_body = common.make_grid("SourceBody", x_segments=3, y_segments=3)

        garment.sculpt_tool.source_body = source_body  # un-rigged
        self._activate(garment)

        result = bpy.ops.sculpttool.detect_rigs()
        self.assertEqual(result, {'FINISHED'})
        self.assertIs(garment.sculpt_tool.source_base_armature, garment_rig)

    def test_detect_cancels_when_nothing_found(self):
        garment = common.make_grid("Garment", x_segments=2, y_segments=2)
        self._activate(garment)
        result = bpy.ops.sculpttool.detect_rigs()
        self.assertEqual(result, {'CANCELLED'})
        self.assertIsNone(garment.sculpt_tool.source_base_armature)
        self.assertIsNone(garment.sculpt_tool.target_base_armature)

    def test_base_armature_pointers_accept_armature_objects(self):
        garment = common.make_grid("Garment", x_segments=2, y_segments=2)
        arm = common.make_armature("Rig", _HUMANOID_BONES)
        garment.sculpt_tool.source_base_armature = arm
        garment.sculpt_tool.target_base_armature = arm
        self.assertIs(garment.sculpt_tool.source_base_armature, arm)
        self.assertIs(garment.sculpt_tool.target_base_armature, arm)


# Two rigs with DIFFERENT naming conventions but the same joints, so the
# canonical mapper (R2) has something real to normalize.
_DOT_RIG = [
    ("Hips", (0, 0, 1.0), (0, 0, 1.2), None),
    ("Arm.L", (0.2, 0, 1.5), (0.6, 0, 1.5), None),
    ("Leg.L", (0.1, 0, 1.0), (0.1, 0, 0.5), None),
]
_USCORE_RIG = [
    ("Hips", (0, 0, 1.0), (0, 0, 1.2), None),
    ("Arm_L", (0.2, 0, 1.5), (0.6, 0, 1.5), None),
    ("Leg_L", (0.1, 0, 1.0), (0.1, 0, 0.5), None),
]


class ComputeBoneMapOperatorTest(unittest.TestCase):
    """``OT_compute_bone_map`` + override add/remove -- roadmap R2's UI
    bridge from a real ``bpy`` armature to ``core.rig_map``."""

    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def _setup_garment(self):
        garment = common.make_grid("Garment", x_segments=2, y_segments=2)
        garment_rig = common.make_armature("GarmentRig", _DOT_RIG)
        target_rig = common.make_armature("TargetRig", _USCORE_RIG)
        common.bind_mesh_to_armature(garment, garment_rig)
        garment.sculpt_tool.target_base_armature = target_rig
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)
        return garment, garment_rig, target_rig

    def test_compute_reports_and_stores_summary(self):
        garment, _gr, _tr = self._setup_garment()
        result = bpy.ops.sculpttool.compute_bone_map()
        self.assertEqual(result, {'FINISHED'})
        self.assertIn("pairs", garment.sculpt_tool.bone_map_summary)

    def test_compute_cancels_without_target_rig(self):
        garment = common.make_grid("Garment", x_segments=2, y_segments=2)
        common.bind_mesh_to_armature(garment, common.make_armature("GarmentRig", _DOT_RIG))
        bpy.context.view_layer.objects.active = garment
        result = bpy.ops.sculpttool.compute_bone_map()
        self.assertEqual(result, {'CANCELLED'})

    def test_override_add_and_remove(self):
        garment, _gr, _tr = self._setup_garment()
        self.assertEqual(len(garment.sculpt_tool.bone_map_overrides), 0)
        bpy.ops.sculpttool.bone_override_add()
        self.assertEqual(len(garment.sculpt_tool.bone_map_overrides), 1)
        garment.sculpt_tool.bone_map_overrides[0].source_bone = "Arm.L"
        garment.sculpt_tool.bone_map_overrides[0].target_bone = "Arm_L"
        bpy.ops.sculpttool.bone_override_remove()
        self.assertEqual(len(garment.sculpt_tool.bone_map_overrides), 0)


if __name__ == "__main__":
    unittest.main()
