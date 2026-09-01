"""Tests for armature-driven position + scale placement (roadmap R7).

Verifies the placement stage moves AND scales the garment to the target
base's skeleton -- not just rotating it -- fixing the "too low / wrong
size" retarget. Covers the pure ``core.pose.compute_bone_placements`` and
the ``OT_pose_to_target`` (now "Place onto Target Base") operator end to end.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import pose  # noqa: E402

# Garment rig: hips at z=1.0, a short (0.5) left arm at z=1.1.
_GARMENT = [
    ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
    ("Arm.L", (0.2, 0.0, 1.1), (0.7, 0.0, 1.1), "Hips"),
]
# Target base rig: hips ~0.4 HIGHER, a 2x-longer left arm, higher up.
_TARGET = [
    ("Hips", (0.0, 0.0, 1.4), (0.0, 0.0, 1.6), None),
    ("Arm_L", (0.25, 0.0, 1.5), (1.25, 0.0, 1.5), "Hips"),
]
_PAIRS = [("Hips", "Hips"), ("Arm.L", "Arm_L")]


class ComputePlacementTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()

    def test_placement_matches_target_position_and_length(self):
        garment = common.make_armature("GRig", _GARMENT)
        target = common.make_armature("TRig", _TARGET)
        placements = {n: (m, s) for n, m, s in
                      pose.compute_bone_placements(garment, target, _PAIRS)}

        # Arm.L placed at the target arm's head (position), stretched to the
        # target arm's length (garment 0.5 -> target 1.0 => scale 2.0).
        world_rigid, length_scale = placements["Arm.L"]
        head = world_rigid.to_translation()
        self.assertAlmostEqual(head.x, 0.25, places=4)
        self.assertAlmostEqual(head.z, 1.5, places=4)
        self.assertAlmostEqual(length_scale, 2.0, places=4)

    def test_identical_rigs_place_at_rest(self):
        # Placement onto a geometrically identical target = rest position,
        # unit length scale (no-op).
        garment = common.make_armature("GRig", _GARMENT)
        target = common.make_armature("TRig", [
            ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
            ("Arm_L", (0.2, 0.0, 1.1), (0.7, 0.0, 1.1), "Hips"),
        ])
        placements = {n: (m, s) for n, m, s in
                      pose.compute_bone_placements(garment, target, _PAIRS)}
        world_rigid, length_scale = placements["Arm.L"]
        self.assertAlmostEqual(world_rigid.to_translation().x, 0.2, places=4)
        self.assertAlmostEqual(length_scale, 1.0, places=4)


class PlaceOperatorTest(unittest.TestCase):
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

    def test_garment_moves_up_and_scales_to_target(self):
        garment_rig = common.make_armature("GRig", _GARMENT)
        target_rig = common.make_armature("TRig", _TARGET)
        # Garment mesh out along the (short, low) garment arm.
        garment = common.make_grid("Garment", x_segments=3, y_segments=3, size=0.15,
                                   location=(0.45, 0.0, 1.1))
        common.skin_mesh_all_to_bone(garment, garment_rig, "Arm.L")
        garment.sculpt_tool.target_base_armature = target_rig

        before = self._eval_positions(garment)
        bz = sum(p.z for p in before) / len(before)
        bx_span = max(p.x for p in before) - min(p.x for p in before)

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)
        self.assertEqual(bpy.ops.sculpttool.pose_to_target(), {'FINISHED'})

        after = self._eval_positions(garment)
        az = sum(p.z for p in after) / len(after)
        ax_span = max(p.x for p in after) - min(p.x for p in after)

        # Placed onto the higher target arm -> garment rose in Z...
        self.assertGreater(az, bz + 0.25)
        # ...and stretched along the now-longer (2x) arm -> wider X span.
        self.assertGreater(ax_span, bx_span * 1.4)

    def test_unmapped_child_bone_does_not_shear_into_a_flap(self):
        # A mapped Leg bone that stretches 3x, with an UNMAPPED "jiggle"
        # helper bone pointing sideways off it and a garment blob skinned to
        # that helper. The helper must FOLLOW the leg but NOT inherit its
        # along-bone stretch (which would shear the blob into a stray flap).
        garment_rig = common.make_armature("GRig", [
            ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
            ("Leg.L", (0.1, 0.0, 1.0), (0.1, 0.0, 0.7), "Hips"),        # -Z, len 0.3
            ("Jiggle_L", (0.1, 0.0, 0.9), (0.4, 0.0, 0.9), "Leg.L"),   # +X helper (unmapped)
        ])
        target_rig = common.make_armature("TRig", [
            ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), None),
            ("Leg_L", (0.1, 0.0, 1.0), (0.1, 0.0, 0.1), "Hips"),        # len 0.9 -> 3x
        ])
        pairs = [("Hips", "Hips"), ("Leg.L", "Leg_L")]  # Jiggle_L intentionally unmapped

        garment = common.make_grid("Blob", x_segments=2, y_segments=2, size=0.12,
                                   location=(0.35, 0.0, 0.9))
        common.skin_mesh_all_to_bone(garment, garment_rig, "Jiggle_L")
        garment.sculpt_tool.target_base_armature = target_rig
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        def diag(pts):
            lo = [min(p[i] for p in pts) for i in range(3)]
            hi = [max(p[i] for p in pts) for i in range(3)]
            return ((hi[0]-lo[0])**2 + (hi[1]-lo[1])**2 + (hi[2]-lo[2])**2) ** 0.5

        before = self._eval_positions(garment)
        before_diag = diag(before)
        before_c = sum((p.z for p in before)) / len(before)

        from sculpt_tool.operators import op_pose
        op_pose.place_garment_onto_rig(bpy.context, garment_rig, target_rig, pairs)

        after = self._eval_positions(garment)
        # It moved with the (now longer) leg...
        self.assertNotAlmostEqual(sum(p.z for p in after) / len(after), before_c, places=2)
        # ...but did NOT balloon/shear (the 3x leg stretch was not inherited).
        self.assertLess(diag(after), before_diag * 1.5)
        # Mechanism: scale inheritance is off on every garment bone.
        self.assertTrue(all(b.inherit_scale == 'NONE' for b in garment_rig.data.bones))

    def test_hip_height_fix(self):
        # A garment skinned to Hips rises when the target base's hips are
        # higher -- the "garment sits too low" fix.
        garment_rig = common.make_armature("GRig", _GARMENT)
        target_rig = common.make_armature("TRig", _TARGET)
        garment = common.make_grid("Belt", x_segments=3, y_segments=3, size=0.2,
                                   location=(0.0, 0.0, 1.0))
        common.skin_mesh_all_to_bone(garment, garment_rig, "Hips")
        garment.sculpt_tool.target_base_armature = target_rig
        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        before_z = sum(p.z for p in self._eval_positions(garment)) / 9
        self.assertEqual(bpy.ops.sculpttool.pose_to_target(), {'FINISHED'})
        after_z = sum(p.z for p in self._eval_positions(garment)) / 9
        self.assertGreater(after_z, before_z + 0.3)  # rose ~0.4 with the hips


if __name__ == "__main__":
    unittest.main()
