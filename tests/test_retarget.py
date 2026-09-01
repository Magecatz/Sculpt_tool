"""Fast-suite end-to-end retarget guard across a bone-naming difference
(roadmap R6's always-run half).

A small synthetic two-rig fixture: a garment rigged with '.L'-convention
bones retargeted onto a target base rigged with '_L'-convention bones. This
is the checked-in, asset-free guard that the pose->bind->fit retarget flow
resolves the canonical bone map across naming families and completes -- so
a future change can't silently regress the naming-mapping-in-retarget path
without the real ``Test_Items`` corpus present. The heavier real-asset
regression (Tech Set -> Egirl/Fantasy/Venus) lives opt-in in
``tests/retarget_repro.py``.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import rig, rig_map, storage  # noqa: E402

# Two rigs, same skeleton, DIFFERENT naming conventions.
_DOT_RIG = [
    ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
    ("Arm.L", (0.2, 0.0, 1.1), (1.2, 0.0, 1.1), "Hips"),
    ("Leg.L", (0.1, 0.0, 1.0), (0.1, 0.0, 0.4), "Hips"),
]
_USCORE_RIG = [
    ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
    ("Arm_L", (0.2, 0.0, 1.1), (1.2, 0.0, 1.1), "Hips"),
    ("Leg_L", (0.1, 0.0, 1.0), (0.1, 0.0, 0.4), "Hips"),
]


class SyntheticRetargetTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def test_bone_map_resolves_across_naming(self):
        garment_rig = common.make_armature("GRig", _DOT_RIG)
        target_rig = common.make_armature("TRig", _USCORE_RIG)
        bone_map = rig_map.build_bone_map(
            rig.bone_names(garment_rig), rig.bone_names(target_rig)
        )
        s2t = bone_map.source_to_target()
        self.assertEqual(s2t["Arm.L"], "Arm_L")
        self.assertEqual(s2t["Leg.L"], "Leg_L")
        self.assertEqual(s2t["Hips"], "Hips")

    def test_end_to_end_retarget_completes_and_stays_on_body(self):
        # Cross-topology (Mode B) source/target so this exercises the real
        # retarget mode, with the garment rigged '.L' and the target base
        # rigged '_L'.
        source = common.make_tube("Source", segments=12, rings=6, radius=1.0, height=2.0)
        target = common.make_tube("Target", segments=16, rings=8, radius=1.1, height=2.0)
        garment = common.make_tube("Garment", segments=10, rings=5, radius=1.15, height=1.6)
        garment_rig = common.make_armature("GRig", _DOT_RIG)
        target_rig = common.make_armature("TRig", _USCORE_RIG)
        common.skin_mesh_all_to_bone(garment, garment_rig, "Arm.L")

        s = garment.sculpt_tool
        s.source_body = source
        s.target_body = target
        s.bind_mode_override = 'MODE_B'
        s.target_base_armature = target_rig  # enables pose stage 0 (no-op: target rig at rest)
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})

        key = garment.data.shape_keys.key_blocks.get(storage.FITTED_SHAPE_KEY_NAME)
        self.assertIsNotNone(key)
        # Fitted result stays near the target body (retarget didn't fly off):
        # every fitted point within the target's bounding sphere + margin.
        target_pts = common.world_positions(target)
        cx = sum(p.x for p in target_pts) / len(target_pts)
        cy = sum(p.y for p in target_pts) / len(target_pts)
        cz = sum(p.z for p in target_pts) / len(target_pts)
        matrix = garment.matrix_world
        for kp in key.data:
            w = matrix @ kp.co
            dist = ((w.x - cx) ** 2 + (w.y - cy) ** 2 + (w.z - cz) ** 2) ** 0.5
            self.assertLess(dist, 3.0, "fitted vertex flew off the target body")


if __name__ == "__main__":
    unittest.main()
