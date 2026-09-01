"""Tests for pose transfer wired into Fit/Batch as stage 0 (roadmap R5).

Verifies: Fit auto-poses the garment onto the target base before fitting
when rigs are present; it's a no-op when the target base is at the
garment's pose (co-posed happy path unchanged); the toggle disables it;
and Batch poses per target base.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import storage  # noqa: E402

_GARMENT_BONES = [
    ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
    ("Arm.L", (0.2, 0.0, 1.1), (1.2, 0.0, 1.1), "Hips"),
]
_TARGET_BONES = [
    ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
    ("Arm_L", (0.2, 0.0, 1.1), (1.2, 0.0, 1.1), "Hips"),
]


def _arm_is_posed(armature_obj, bone_name="Arm.L"):
    """True if the bone has swung away from its rest +X direction."""
    direction = common.posed_bone_direction(armature_obj, bone_name)
    return direction.dot((1.0, 0.0, 0.0)) < 0.9


class FitStage0Test(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def _scene(self):
        source = common.make_grid("Source", x_segments=4, y_segments=4)
        target = common.make_grid("Target", x_segments=4, y_segments=4)
        garment = common.make_grid("Garment", x_segments=4, y_segments=4)
        garment_rig = common.make_armature("GRig", _GARMENT_BONES)
        target_rig = common.make_armature("TRig", _TARGET_BONES)
        common.skin_mesh_all_to_bone(garment, garment_rig, "Arm.L")

        s = garment.sculpt_tool
        s.source_body = source
        s.target_body = target
        s.bind_mode_override = 'MODE_A'
        s.target_base_armature = target_rig
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)
        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        return garment, garment_rig, target_rig

    def test_rest_target_is_noop(self):
        garment, garment_rig, target_rig = self._scene()
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})
        # Target base at rest -> pose transfer identity -> garment unposed.
        self.assertFalse(_arm_is_posed(garment_rig))

    def test_posed_target_poses_the_garment(self):
        garment, garment_rig, target_rig = self._scene()
        common.point_bone_along(target_rig, "Arm_L", (0.0, 0.0, -1.0))
        garment.sculpt_tool.skip_alignment_check = True  # pose moves garment off the flat target
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})
        self.assertTrue(_arm_is_posed(garment_rig))  # stage 0 ran

    def test_toggle_off_disables_pose_stage(self):
        garment, garment_rig, target_rig = self._scene()
        common.point_bone_along(target_rig, "Arm_L", (0.0, 0.0, -1.0))
        garment.sculpt_tool.auto_pose_transfer = False
        garment.sculpt_tool.skip_alignment_check = True
        self.assertEqual(bpy.ops.sculpttool.fit_garment(), {'FINISHED'})
        self.assertFalse(_arm_is_posed(garment_rig))  # not posed


class BatchStage0Test(unittest.TestCase):
    def setUp(self):
        common.clear_scene()
        if not hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.register()

    def tearDown(self):
        if hasattr(bpy.types.Object, "sculpt_tool"):
            sculpt_tool.unregister()

    def test_batch_poses_per_target_and_bakes_each(self):
        source = common.make_grid("Source", x_segments=4, y_segments=4)
        garment = common.make_grid("Garment", x_segments=4, y_segments=4)
        garment_rig = common.make_armature("GRig", _GARMENT_BONES)
        common.skin_mesh_all_to_bone(garment, garment_rig, "Arm.L")

        collection = bpy.data.collections.new("Targets")
        bpy.context.scene.collection.children.link(collection)
        targets = []
        for i in range(2):
            t = common.make_grid(f"T{i}", x_segments=4, y_segments=4)
            for v in t.data.vertices:
                v.co.z += 0.15 * i
            t.data.update()
            t_rig = common.make_armature(f"TRig{i}", _TARGET_BONES)
            # Give the second target a non-rest pose.
            if i == 1:
                common.point_bone_along(t_rig, "Arm_L", (0.0, 0.0, -1.0))
            # Skin the target body to its rig so it's the target's rig.
            common.bind_mesh_to_armature(t, t_rig)
            # Move target into the collection only.
            for coll in list(t.users_collection):
                coll.objects.unlink(t)
            collection.objects.link(t)
            targets.append(t)

        s = garment.sculpt_tool
        s.source_body = source
        s.bind_mode_override = 'MODE_A'
        s.batch_target_collection = collection
        s.skip_alignment_check = True
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)
        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})

        result = bpy.ops.sculpttool.batch_fit()
        self.assertEqual(result, {'FINISHED'})
        # One baked shape key per target.
        keys = garment.data.shape_keys.key_blocks
        self.assertIn("Fitted_T0", keys)
        self.assertIn("Fitted_T1", keys)
        # The garment rig ended posed toward the last (posed) target.
        self.assertTrue(_arm_is_posed(garment_rig))


if __name__ == "__main__":
    unittest.main()
