"""Pose transfer -- the missing Stage 1 (armature-driven initial posing).

Roadmap R3 (Bear PR Process card cfa7e4aa-c7f8-42d9-acd0-2ce966e67293), the
concrete fix for the anchor bug (9df4bc00). Depends on R1 (rig awareness,
``core.rig``) and R2 (bone mapping, ``core.rig_map``).

**What it does.** Copies the target base's *pose* -- the per-bone rotations
that carry each limb into place -- onto the garment's own armature, bone by
bone through R2's canonical mapping, so that when the garment deforms
through its **own existing skin weights** (its Armature modifier, evaluated
by Blender) it is grossly posed onto the target base *before* the existing
surface-fit pipeline runs. The skeleton does the gross placement (each
sleeve onto the matching arm, each leg onto the matching leg); the existing
bind -> project -> collision -> smooth pipeline then conforms the surface
(DECISIONS.md section 6f, ARCHITECTURE.md section 1's Stage-1 note).

**Why per-bone LOCAL rotations (not world matrices).** A pose is, at heart,
a set of per-bone local rotations composed up a shared hierarchy. Both rigs
are the same humanoid hierarchy (that's what R2 established), so copying
each target bone's *local pose rotation relative to its own rest* onto the
mapped garment bone reproduces the same overall pose shape -- independent of
the two rigs' differing bone lengths, rest positions, or proportions (the
fit pipeline handles those). Working in local pose space means the per-bone
results are independent: they can be applied in any order with a single
depsgraph update, with no fragile parent-before-child world-matrix
sequencing.

**Rest-orientation compensation.** The two rigs don't share bone-local axis
conventions (bone roll / rest orientation differ across rig families). A
target bone's local rotation ``q_t`` therefore can't be copied onto the
garment bone verbatim -- it must be re-expressed in the garment bone's rest
frame. Writing ``R_t`` / ``R_g`` for the two bones' rest *world*
orientations, the world rotation the target bone underwent is
``R_t · q_t · R_t⁻¹``; the garment-local rotation reproducing that same
world rotation is ``R_g⁻¹ · (that) · R_g`` = ``C · q_t · C⁻¹`` with the
change-of-basis ``C = R_g⁻¹ · R_t``. When the rest frames already match,
``C`` is identity and the target's local rotation is copied straight across.
When the target rig is itself at rest (``q_t`` identity), every result is
identity -- so a garment and target base already in the same pose come out
unchanged (the co-posed happy path the card requires stays a no-op).

Pure computation: this module reads armature/pose data and returns the
rotations to apply, as ``{garment_bone_name: mathutils.Quaternion}``. It
does NOT mutate the scene -- ``operators/op_pose.py`` applies the result
(setting pose-bone rotations is scene mutation, operator-layer work, like
every other ``core/`` module's split). No ``bpy.context`` access.
"""


def compute_pose_rotations(garment_arm, target_arm, bone_pairs):
    """Compute the garment armature's per-bone local pose rotations that
    reproduce ``target_arm``'s current pose, via ``bone_pairs``.

    ``bone_pairs`` is an iterable of ``(garment_bone_name,
    target_bone_name)`` (from ``core.rig_map.BoneMap.as_pairs()``). Returns
    ``{garment_bone_name: mathutils.Quaternion}`` -- the local pose rotation
    (bone-local, relative to rest) to set on each mapped garment pose bone.
    A pair whose bones don't both exist is skipped. Bones the target holds
    at rest yield an identity quaternion (harmless to apply).

    Rotation-only by design (translation/scale are not transferred): a pose
    is carried by rotations, and gross limb placement -- this stage's whole
    job -- is a rotation problem. See the module docstring for the
    change-of-basis ``C = R_g⁻¹ · R_t`` derivation.
    """
    garment_world = garment_arm.matrix_world
    target_world = target_arm.matrix_world

    rotations = {}
    for garment_bone_name, target_bone_name in bone_pairs:
        garment_bone = garment_arm.data.bones.get(garment_bone_name)
        target_bone = target_arm.data.bones.get(target_bone_name)
        target_pose_bone = target_arm.pose.bones.get(target_bone_name)
        if garment_bone is None or target_bone is None or target_pose_bone is None:
            continue

        # Rest WORLD orientations (rotation only -- .to_quaternion() drops
        # translation and any uniform scale the FBX import baked in).
        target_rest_rot = (target_world @ target_bone.matrix_local).to_quaternion()
        garment_rest_rot = (garment_world @ garment_bone.matrix_local).to_quaternion()

        # Target bone's local pose rotation, relative to its own rest.
        target_local = target_pose_bone.matrix_basis.to_quaternion()

        # Re-express it in the garment bone's rest frame:
        #   C = R_g⁻¹ · R_t ,   q_g = C · q_t · C⁻¹
        change_of_basis = garment_rest_rot.inverted() @ target_rest_rot
        garment_local = change_of_basis @ target_local @ change_of_basis.inverted()

        rotations[garment_bone_name] = garment_local.normalized()

    return rotations
