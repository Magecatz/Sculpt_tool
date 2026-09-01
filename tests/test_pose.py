"""Tests for the pose-transfer stage (roadmap R3).

Covers the card's DoD at the mechanism level: a garment posed onto a
differently-posed target base comes out following the target's limbs
(a bone rotated down carries its skinned garment down), across a bone-name
difference; and the co-posed happy path (target at rest) is a no-op.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import pose  # noqa: E402

# A garment rig ('.L' naming) and a target rig ('_L' naming) that share the
# same rest skeleton: Hips + a left arm pointing along +X.
_GARMENT_BONES = [
    ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
    ("Arm.L", (0.2, 0.0, 1.1), (1.2, 0.0, 1.1), "Hips"),
]
_TARGET_BONES = [
    ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
    ("Arm_L", (0.2, 0.0, 1.1), (1.2, 0.0, 1.1), "Hips"),
]
_PAIRS = [("Hips", "Hips"), ("Arm.L", "Arm_L")]


def _pose_bone(arm, bone_name, quaternion):
    pb = arm.pose.bones[bone_name]
    pb.rotation_mode = 'QUATERNION'
    pb.rotation_quaternion = quaternion
    common.update_scene()


class ComputePoseRotationsTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()

    def test_identity_when_target_at_rest(self):
        garment = common.make_armature("GarmentRig", _GARMENT_BONES)
        target = common.make_armature("TargetRig", _TARGET_BONES)
        rotations = pose.compute_pose_rotations(garment, target, _PAIRS)
        for q in rotations.values():
            # ~identity quaternion (w~1, xyz~0)
            self.assertAlmostEqual(abs(q.w), 1.0, places=5)
            self.assertAlmostEqual(q.x, 0.0, places=5)
            self.assertAlmostEqual(q.y, 0.0, places=5)
            self.assertAlmostEqual(q.z, 0.0, places=5)

    def test_garment_arm_follows_target_arm_direction(self):
        garment = common.make_armature("GarmentRig", _GARMENT_BONES)
        target = common.make_armature("TargetRig", _TARGET_BONES)
        # Pose the TARGET arm downward (points -Z).
        common.point_bone_along(target, "Arm_L", (0.0, 0.0, -1.0))
        target_dir = common.posed_bone_direction(target, "Arm_L")
        self.assertLess(target_dir.z, -0.9)  # sanity: target really swung down

        rotations = pose.compute_pose_rotations(garment, target, _PAIRS)
        _pose_bone(garment, "Arm.L", rotations["Arm.L"])
        garment_dir = common.posed_bone_direction(garment, "Arm.L")

        # The garment arm now points the same world direction as the posed
        # target arm (limb followed) -- and clearly downward (z < -0.9).
        self.assertGreater(garment_dir.dot(target_dir), 0.999)
        self.assertLess(garment_dir.z, -0.9)

    def test_rest_orientation_compensation(self):
        # Both arms rest along +X (as real T-pose rigs do), but the two rigs
        # give the bone a DIFFERENT ROLL -- the realistic cross-family rest
        # difference the change-of-basis exists for. It must still land the
        # garment arm at the same world direction as the posed target arm.
        import math
        garment = common.make_armature("GarmentRig", [
            ("Hips", (0, 0, 1), (0, 0, 1.2), None),
            ("Arm.L", (0.2, 0, 1.1), (1.2, 0, 1.1), "Hips", math.radians(50)),
        ])
        target = common.make_armature("TargetRig", [
            ("Hips", (0, 0, 1), (0, 0, 1.2), None),
            ("Arm_L", (0.2, 0, 1.1), (1.2, 0, 1.1), "Hips", 0.0),
        ])
        common.point_bone_along(target, "Arm_L", (0.0, 0.0, -1.0))
        target_dir = common.posed_bone_direction(target, "Arm_L")
        self.assertLess(target_dir.z, -0.9)

        rotations = pose.compute_pose_rotations(garment, target, _PAIRS)
        _pose_bone(garment, "Arm.L", rotations["Arm.L"])
        garment_dir = common.posed_bone_direction(garment, "Arm.L")

        self.assertGreater(garment_dir.dot(target_dir), 0.999)

    def test_skinned_garment_mesh_follows_pose(self):
        garment_rig = common.make_armature("GarmentRig", _GARMENT_BONES)
        target_rig = common.make_armature("TargetRig", _TARGET_BONES)
        # A small mesh out along the arm, skinned entirely to Arm.L.
        garment = common.make_grid("Garment", x_segments=2, y_segments=2, size=0.3,
                                   location=(0.8, 0.0, 1.1))
        common.skin_mesh_all_to_bone(garment, garment_rig, "Arm.L")

        before = common.world_positions(garment)  # evaluated? use eval below
        depsgraph = bpy.context.evaluated_depsgraph_get()

        def eval_positions():
            common.update_scene()
            dg = bpy.context.evaluated_depsgraph_get()
            ev = garment.evaluated_get(dg)
            m = ev.to_mesh()
            mw = garment.matrix_world
            pts = [mw @ v.co for v in m.vertices]
            ev.to_mesh_clear()
            return pts

        before = eval_positions()
        common.point_bone_along(target_rig, "Arm_L", (0.0, 0.0, -1.0))
        rotations = pose.compute_pose_rotations(garment_rig, target_rig, _PAIRS)
        _pose_bone(garment_rig, "Arm.L", rotations["Arm.L"])
        after = eval_positions()

        mean_before_z = sum(p.z for p in before) / len(before)
        mean_after_z = sum(p.z for p in after) / len(after)
        # Arm swung down -> the skinned garment mesh dropped in Z.
        self.assertLess(mean_after_z, mean_before_z - 0.3)


class PoseOperatorTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def test_pose_to_target_operator_end_to_end(self):
        garment_rig = common.make_armature("GarmentRig", _GARMENT_BONES)
        target_rig = common.make_armature("TargetRig", _TARGET_BONES)
        common.point_bone_along(target_rig, "Arm_L", (0.0, 0.0, -1.0))

        garment = common.make_grid("Garment", x_segments=2, y_segments=2, size=0.3,
                                   location=(0.8, 0.0, 1.1))
        common.skin_mesh_all_to_bone(garment, garment_rig, "Arm.L")
        garment.sculpt_tool.target_base_armature = target_rig

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)
        result = bpy.ops.sculpttool.pose_to_target()
        self.assertEqual(result, {'FINISHED'})
        # The garment's Arm.L bone actually rotated (non-identity now).
        garment_dir = common.posed_bone_direction(garment_rig, "Arm.L")
        self.assertLess(garment_dir.z, -0.9)


if __name__ == "__main__":
    unittest.main()
