"""Tests for ``core/rig_map.py`` -- canonical humanoid bone mapping (R2).

The rig bone-name lists below are the REAL names measured from the
gitignored ``Test_Items`` rigs (headless import, Blender 5.2), pasted here
so the mapping logic is exercised against genuine naming conventions
without needing the assets present. Covers the card's definition of done:
"given any two of the four Test_Items/Body rigs (and the Tech Set /
bodysuit clothing rigs), the mapper resolves the full primary deform chain
correctly, and unmatched bones are surfaced rather than silently dropped."
"""

import sys
import unittest
from itertools import permutations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sculpt_tool.core import rig_map  # noqa: E402
from sculpt_tool.core.rig_map import CanonicalBone  # noqa: E402

# --- Real bone-name lists (measured) --------------------------------------
RP_FEMALE = ["Hips", "Spine", "Chest", "Shoulder.L", "Arm.L", "Elbow.L", "Wrist.L", "Index Finger.L", "Index Finger Left 02.L", "Index Finger 03.L", "Middle Finger.L", "Middle Finger 02.L", "Middle Finger 03.L", "Ring Finger .L", "Ring Finger 02.L", "Ring Finger 03.L", "Little Finger.L", "Little Finger 02.L", "Little Finger 03.L", "Thumb .L", "Thumb 02.L", "Thumb 03.L", "Wrist_Twist.L", "Elbow_Twist.L", "Neck", "Head", "Shoulder.R", "Arm.R", "Elbow.R", "Wrist.R", "Index Finger.R", "Index Finger Left 02.R", "Index Finger 03.R", "Middle Finger.R", "Middle Finger 02.R", "Middle Finger 03.R", "Ring Finger .R", "Ring Finger 02.R", "Ring Finger 03.R", "Little Finger.R", "Little Finger 02.R", "Little Finger 03.R", "Thumb .R", "Thumb 02.R", "Thumb 03.R", "Wrist_Twist.R", "Elbow_Twist.R", "Boob_Root", "Boob.L", "Nipple.L", "Boob.R", "Nipple.R", "Tummy", "Leg.L", "Knee.L", "Foot.L", "Toe.L", "Thumb Toe.L", "Index Toe.L", "Middle Toe.L", "Ring Toe.L", "Little Toe.L", "Knee_Twist.L", "Twist_Butt.L", "Thigh_Jiggle.L", "Leg.R", "Knee.R", "Foot.R", "Toe.R", "Little Toe.R", "Thumb Toe.R", "Index Toe.R", "Middle Toe.R", "Ring Toe.R", "Knee_Twist.R", "Twist_Butt.R", "Thigh_Jiggle.R", "Butt_Root", "Butt.L", "Butt.R", "Hip_Dip", "Pussy Power Root", "Pussy Touch.R", "Pussy Touch.L"]
VRBASE = ["Hips", "Spine", "Chest", "Neck", "Head", "Shoulder_L", "Arm_L", "Elbow_L", "Wrist_L", "Index Finger_L", "Index Finger 02_L", "Index Finger 03_L", "Middle Finger_L", "Middle Finger 02_L", "Middle Finger 03_L", "Ring Finger _L", "Ring Finger 02_L", "Ring Finger 03_L", "Little Finger_L", "Little Finger 02_L", "Little Finger 03_L", "Thumb_L", "Thumb 01_L", "Thumb 03_L", "Elbow_Twist_L", "Boob_Root", "Boob_L", "Boob_R", "Shoulder_R", "Arm_R", "Elbow_R", "Wrist_R", "Index Finger_R", "Index Finger 02_R", "Index Finger 03_R", "Middle Finger_R", "Middle Finger 02_R", "Middle Finger 03_R", "Ring Finger _R", "Ring Finger 02_R", "Ring Finger 03_R", "Little Finger_R", "Little Finger 02_R", "Little Finger 03_R", "Thumb_R", "Thumb 01_R", "Thumb 03_R", "Elbow_Twist_R", "Butt_Root", "Butt_L", "Butt_R", "Coochy_Root", "Coochy_L", "Coochy_R", "Tummy Jiggle", "Leg_L", "Knee_L", "Foot_L", "Toe_L", "Thigh Jiggle_L", "Leg_R", "Knee_R", "Foot_R", "Toe_R", "Thigh Jiggle_R", "Hips Dips"]
VENUS = ["Hips", "Spine", "Chest", "Neck", "Head", "Root_Breast.R", "Breast_1.R", "Breast_2.R", "Root_Breast.L", "Breast_1.L", "Breast_2.L", "Shoulder.L", "Upper_Arm.L", "Lower_Arm.L", "Hand.L", "Thumb0.L", "Thumb1.L", "Thumb2.L", "IndexFinger1.L", "IndexFinger2.L", "IndexFinger3.L", "MiddleFinger1.L", "MiddleFinger2.L", "MiddleFinger3.L", "RingFinger1.L", "RingFinger2.L", "RingFinger3.L", "LittleFinger1.L", "LittleFinger2.L", "LittleFinger3.L", "Twist_Lower_Arm_1.L", "Twist_Lower_Arm_2.L", "Twist_Lower_Arm_3.L", "PV_Elbow_1.L", "PV_Elbow_2.L", "Twist_Upper_Arm_1.L", "Twist_Upper_Arm_2.L", "Twist_Upper_Arm_3.L", "Shoulder.R", "Upper_Arm.R", "Lower_Arm.R", "Hand.R", "Thumb0.R", "Thumb1.R", "Thumb2.R", "IndexFinger1.R", "IndexFinger2.R", "IndexFinger3.R", "MiddleFinger1.R", "MiddleFinger2.R", "MiddleFinger3.R", "RingFinger1.R", "RingFinger2.R", "RingFinger3.R", "LittleFinger1.R", "LittleFinger2.R", "LittleFinger3.R", "Twist_Lower_Arm_1.R", "Twist_Lower_Arm_2.R", "Twist_Lower_Arm_3.R", "PV_Elbow_1.R", "PV_Elbow_2.R", "Twist_Upper_Arm_1.R", "Twist_Upper_Arm_2.R", "Twist_Upper_Arm_3.R", "Upper_Leg.L", "Lower_Leg.L", "Foot.L", "Toe.L", "Twist_Lower_Leg_1.L", "Twist_Lower_Leg_2.L", "PV_Knee_1.L", "PV_Knee_2.L", "Wiggle_Upper_Leg.L", "Twist_Upper_Leg_1.L", "Twist_Upper_Leg_2.L", "Upper_Leg.R", "Lower_Leg.R", "Foot.R", "Toe.R", "Twist_Lower_Leg_1.R", "Twist_Lower_Leg_2.R", "PV_Knee_1.R", "PV_Knee_2.R", "Wiggle_Upper_Leg.R", "Twist_Upper_Leg_1.R", "Twist_Upper_Leg_2.R", "PV_Butt.L", "PV_Butt.R", "PV_Spine_1", "Root_Butt_Wiggle.L", "Butt_Wiggle_1.L", "Belly_Wiggle", "Root_Butt_Wiggle.R", "Butt_Wiggle_1.R", "Coochie", "PV_Hips.L", "PV_Hips.R"]
TECHSET = ["Hips", "Spine", "Chest", "Shoulder.L", "Arm.L", "Elbow.L", "Wrist.L", "Index Finger.L", "Index Finger Left 02.L", "Index Finger 03.L", "Index Finger 03.L_end", "Middle Finger.L", "Middle Finger 02.L", "Middle Finger 03.L", "Middle Finger 03.L_end", "Ring Finger .L", "Ring Finger 02.L", "Ring Finger 03.L", "Ring Finger 03.L_end", "Little Finger.L", "Little Finger 02.L", "Little Finger 03.L", "Little Finger 03.L_end", "Thumb .L", "Thumb 02.L", "Thumb 03.L", "Thumb 03.L_end", "Neck", "Head", "Head_end", "Shoulder.R", "Arm.R", "Elbow.R", "Wrist.R", "Index Finger.R", "Index Finger Left 02.R", "Index Finger 03.R", "Index Finger 03.R_end", "Middle Finger.R", "Middle Finger 02.R", "Middle Finger 03.R", "Middle Finger 03.R_end", "Ring Finger .R", "Ring Finger 02.R", "Ring Finger 03.R", "Ring Finger 03.R_end", "Little Finger.R", "Little Finger 02.R", "Little Finger 03.R", "Little Finger 03.R_end", "Thumb .R", "Thumb 02.R", "Thumb 03.R", "Thumb 03.R_end", "Boob_Root", "Boob.L", "Nipple.L", "Nipple.L_end", "Boob.R", "Nipple.R", "Nipple.R_end", "Leg.L", "Knee.L", "Foot.L", "Toes.L", "Toes.L_end", "Twist_Butt.L", "Twist_Butt.L_end", "Leg.R", "Knee.R", "Foot.R", "Toes.R", "Toes.R_end", "Twist_Butt.R", "Twist_Butt.R_end", "Butt_Root", "Butt.L", "Butt.L.001", "Butt.L.001_end", "Butt.L.001_end_end", "Butt.R", "Butt.R.001", "Butt.R.001_end", "Butt.R.001_end_end", "Hip-Dips", "Hip-Dips_end", "Hip-Dips_end_end", "Tummy", "Tummy_end"]
BODYSUIT = ["Hips", "Spine", "Chest", "Neck", "Head", "Head_end", "Shoulder_L", "Arm_L", "Elbow_L", "Wrist_L", "Index Finger_L", "Index Finger 02_L", "Index Finger 03_L", "Index Finger 03_L_end", "Middle Finger_L", "Middle Finger 02_L", "Middle Finger 03_L", "Middle Finger 03_L_end", "Ring Finger _L", "Ring Finger 02_L", "Ring Finger 03_L", "Ring Finger 03_L_end", "Little Finger_L", "Little Finger 02_L", "Little Finger 03_L", "Little Finger 03_L_end", "Thumb_L", "Thumb 01_L", "Thumb 03_L", "Thumb 03_L_end", "Elbow_Twist_L", "Elbow_Twist_L_end", "Boob_Root", "Boob_L", "Boob_L_end", "Boob_R", "Boob_R_end", "Shoulder_R", "Arm_R", "Elbow_R", "Wrist_R", "Index Finger_R", "Index Finger 02_R", "Index Finger 03_R", "Index Finger 03_R_end", "Middle Finger_R", "Middle Finger 02_R", "Middle Finger 03_R", "Middle Finger 03_R_end", "Ring Finger _R", "Ring Finger 02_R", "Ring Finger 03_R", "Ring Finger 03_R_end", "Little Finger_R", "Little Finger 02_R", "Little Finger 03_R", "Little Finger 03_R_end", "Thumb_R", "Thumb 01_R", "Thumb 03_R", "Thumb 03_R_end", "Elbow_Twist_R", "Elbow_Twist_R_end", "Butt_Root", "Butt_L", "Butt_L_end", "Butt_R", "Butt_R_end", "Coochy_Root", "Coochy_L", "Coochy_L_end", "Coochy_R", "Coochy_R_end", "Tummy Jiggle", "Tummy Jiggle_end", "Leg_L", "Knee_L", "Foot_L", "Toe_L", "Toe_L_end", "Thigh Jiggle_L", "Thigh Jiggle_L_end", "Leg_R", "Knee_R", "Foot_R", "Toe_R", "Toe_R_end", "Thigh Jiggle_R", "Thigh Jiggle_R_end", "Hips Dips", "Hips Dips_end"]

ALL_RIGS = {
    "RP_Female": RP_FEMALE,
    "vrbase": VRBASE,
    "Venus": VENUS,
    "TechSet": TECHSET,
    "bodysuit": BODYSUIT,
}


class CanonicalizeTest(unittest.TestCase):
    def test_central_bones(self):
        for name, joint in [("Hips", "Hips"), ("Spine", "Spine"),
                            ("Chest", "Chest"), ("Neck", "Neck"), ("Head", "Head")]:
            cb = rig_map.canonicalize(name)
            self.assertEqual(cb, CanonicalBone(joint=joint))

    def test_arm_chain_across_conventions(self):
        # RP/vrbase call the upper arm "Arm"; Venus "Upper_Arm" -- both ->
        # UpperArm. Wrist (RP/vrbase) and Hand (Venus) -> Hand.
        self.assertEqual(rig_map.canonicalize("Arm.L"), CanonicalBone("UpperArm", "L"))
        self.assertEqual(rig_map.canonicalize("Arm_L"), CanonicalBone("UpperArm", "L"))
        self.assertEqual(rig_map.canonicalize("Upper_Arm.L"), CanonicalBone("UpperArm", "L"))
        self.assertEqual(rig_map.canonicalize("Elbow_R"), CanonicalBone("LowerArm", "R"))
        self.assertEqual(rig_map.canonicalize("Lower_Arm.R"), CanonicalBone("LowerArm", "R"))
        self.assertEqual(rig_map.canonicalize("Wrist.L"), CanonicalBone("Hand", "L"))
        self.assertEqual(rig_map.canonicalize("Hand.L"), CanonicalBone("Hand", "L"))

    def test_side_as_leading_or_trailing_word(self):
        # "Left arm" / "Right elbow" -- side as a whole word, not a .L/_R
        # suffix (measured on the Cyber Bunny outfit; its unmapped arm chain
        # left the wrist cuffs floating at the T-pose rest position).
        self.assertEqual(rig_map.canonicalize("Left arm"), CanonicalBone("UpperArm", "L"))
        self.assertEqual(rig_map.canonicalize("Right elbow"), CanonicalBone("LowerArm", "R"))
        self.assertEqual(rig_map.canonicalize("Left wrist"), CanonicalBone("Hand", "L"))
        self.assertEqual(rig_map.canonicalize("Right leg"), CanonicalBone("UpperLeg", "R"))
        self.assertEqual(rig_map.canonicalize("arm Right"), CanonicalBone("UpperArm", "R"))
        # A plain central bone with no side word stays central.
        self.assertEqual(rig_map.canonicalize("Chest"), CanonicalBone("Chest", None))

    def test_leg_chain_and_toes(self):
        self.assertEqual(rig_map.canonicalize("Leg_L"), CanonicalBone("UpperLeg", "L"))
        self.assertEqual(rig_map.canonicalize("Upper_Leg.L"), CanonicalBone("UpperLeg", "L"))
        self.assertEqual(rig_map.canonicalize("Knee.R"), CanonicalBone("LowerLeg", "R"))
        self.assertEqual(rig_map.canonicalize("Lower_Leg.R"), CanonicalBone("LowerLeg", "R"))
        self.assertEqual(rig_map.canonicalize("Foot.L"), CanonicalBone("Foot", "L"))
        self.assertEqual(rig_map.canonicalize("Toe.L"), CanonicalBone("Toe", "L"))
        self.assertEqual(rig_map.canonicalize("Toes.L"), CanonicalBone("Toe", "L"))

    def test_helper_bones_unmapped(self):
        # NB: Boob.L / Breast_1.L now map (see BreastMappingTest); the breast
        # ROOT and NIPPLE bones remain unmapped.
        for name in ["Boob_Root", "Nipple.L", "Root_Breast.L", "Elbow_Twist.L",
                    "Wrist_Twist.R", "Thigh_Jiggle.L", "Twist_Upper_Arm_1.L",
                    "PV_Elbow_1.L", "Butt_Root", "Coochy_L", "Tummy",
                    "Hips Dips", "PV_Spine_1", "Head_end", "Toes.L_end"]:
            self.assertIsNone(rig_map.canonicalize(name), f"{name!r} should be unmapped")

    def test_toe_fingers_not_hand_fingers(self):
        # "Index Toe.L" must NOT resolve as a hand Index finger.
        self.assertIsNone(rig_map.canonicalize("Index Toe.L"))
        self.assertIsNone(rig_map.canonicalize("Thumb Toe.R"))

    def test_finger_segments(self):
        self.assertEqual(rig_map.canonicalize("Index Finger.L"), CanonicalBone("Index", "L", 1))
        self.assertEqual(rig_map.canonicalize("Index Finger 02_L"), CanonicalBone("Index", "L", 2))
        self.assertEqual(rig_map.canonicalize("IndexFinger3.R"), CanonicalBone("Index", "R", 3))
        self.assertEqual(rig_map.canonicalize("Ring Finger .L"), CanonicalBone("Ring", "L", 1))


class PrimaryChainCoverageTest(unittest.TestCase):
    """The card's DoD: the full primary deform chain resolves between any
    two rigs, across all naming families."""

    def test_every_rig_pair_resolves_full_primary_chain(self):
        for a, b in permutations(ALL_RIGS, 2):
            bone_map = rig_map.build_bone_map(ALL_RIGS[a], ALL_RIGS[b])
            missing = rig_map.missing_primary_bones(bone_map)
            self.assertEqual(
                missing, [],
                f"{a}->{b} left primary bones unmapped: "
                f"{[cb.label() for cb in missing]}",
            )

    def test_pairs_are_correct_bones_rp_to_venus(self):
        # Spot-check the actual bone names paired, not just the count.
        bone_map = rig_map.build_bone_map(RP_FEMALE, VENUS)
        s2t = bone_map.source_to_target()
        self.assertEqual(s2t["Arm.L"], "Upper_Arm.L")   # Arm -> Upper_Arm
        self.assertEqual(s2t["Elbow.L"], "Lower_Arm.L")  # Elbow -> Lower_Arm
        self.assertEqual(s2t["Wrist.L"], "Hand.L")       # Wrist -> Hand
        self.assertEqual(s2t["Leg.R"], "Upper_Leg.R")
        self.assertEqual(s2t["Knee.R"], "Lower_Leg.R")
        self.assertEqual(s2t["Hips"], "Hips")

    def test_garment_rig_maps_to_body_rig(self):
        # TechSet (garment, RP-naming) -> Egirl (vrbase-naming): the real
        # retarget R3 will run.
        bone_map = rig_map.build_bone_map(TECHSET, VRBASE)
        self.assertEqual(rig_map.missing_primary_bones(bone_map), [])
        s2t = bone_map.source_to_target()
        self.assertEqual(s2t["Arm.L"], "Arm_L")
        self.assertEqual(s2t["Toes.L"], "Toe_L")  # Toes -> Toe


class BreastMappingTest(unittest.TestCase):
    """Breast/chest bones map across families so placement can position the
    garment's bust region to the target's breasts (bust-conformance card)."""

    def test_breast_bone_canonicalizes(self):
        self.assertEqual(rig_map.canonicalize("Boob.L"), CanonicalBone("Breast", "L", 1))
        self.assertEqual(rig_map.canonicalize("Boob_R"), CanonicalBone("Breast", "R", 1))
        self.assertEqual(rig_map.canonicalize("Breast_1.L"), CanonicalBone("Breast", "L", 1))
        self.assertEqual(rig_map.canonicalize("Breast_2.L"), CanonicalBone("Breast", "L", 2))

    def test_breast_root_and_nipple_excluded(self):
        for name in ["Boob_Root", "Root_Breast.L", "Nipple.L", "Nipple.R"]:
            self.assertIsNone(rig_map.canonicalize(name))

    def test_breast_maps_across_rig_families(self):
        # RP (Boob.L) <-> vrbase (Boob_L) <-> Venus (Breast_1.L)
        for src, tgt, s_bone, t_bone in [
            (RP_FEMALE, VRBASE, "Boob.L", "Boob_L"),
            (RP_FEMALE, VENUS, "Boob.L", "Breast_1.L"),
            (VRBASE, VENUS, "Boob_L", "Breast_1.L"),
        ]:
            s2t = rig_map.build_bone_map(src, tgt).source_to_target()
            self.assertEqual(s2t.get(s_bone), t_bone, f"{s_bone}->{t_bone}")

    def test_primary_chain_unaffected(self):
        # Breast is an EXTRA correspondence, not part of the required primary
        # chain -- every rig pair still resolves the full primary chain.
        for a, b in [(RP_FEMALE, VENUS), (VRBASE, TECHSET)]:
            bm = rig_map.build_bone_map(a, b)
            self.assertEqual(rig_map.missing_primary_bones(bm), [])


class SurfacingAndOverrideTest(unittest.TestCase):
    def test_helper_bones_are_surfaced_as_unmapped(self):
        bone_map = rig_map.build_bone_map(VENUS, VRBASE)
        # Venus's twist/PV/wiggle helpers have no vrbase counterpart and
        # must appear in source_unmapped, not vanish.
        self.assertIn("Twist_Upper_Arm_1.L", bone_map.source_unmapped)
        self.assertIn("PV_Elbow_1.L", bone_map.source_unmapped)
        self.assertTrue(len(bone_map.source_unmapped) > 0)

    def test_override_forces_a_pair(self):
        bone_map = rig_map.build_bone_map(
            RP_FEMALE, VRBASE,
            overrides=[("Tummy", "Tummy Jiggle")],
        )
        s2t = bone_map.source_to_target()
        self.assertEqual(s2t.get("Tummy"), "Tummy Jiggle")
        # Auto pairs still present.
        self.assertEqual(s2t["Arm.L"], "Arm_L")

    def test_override_empty_target_suppresses(self):
        bone_map = rig_map.build_bone_map(
            RP_FEMALE, VRBASE,
            overrides=[("Arm.L", "")],
        )
        s2t = bone_map.source_to_target()
        self.assertNotIn("Arm.L", s2t)  # explicitly unmapped
        self.assertEqual(s2t["Elbow.L"], "Elbow_L")  # others unaffected


if __name__ == "__main__":
    unittest.main()
