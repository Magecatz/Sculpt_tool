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
transforms to apply. It does NOT mutate the scene -- ``operators/op_pose.py``
applies the result (setting pose-bone transforms is scene mutation,
operator-layer work, like every other ``core/`` module's split). No
``bpy.context`` access.

**Rotation vs. full placement.** :func:`compute_pose_rotations` (R3)
transfers only the per-bone *rotation* -- enough to point the limbs the
right way, but it does not move or resize the garment, so a garment
authored for one base lands too low / wrongly sized on a base with
different proportions (measured across the real bases: hips differ ~10cm,
limb bones 25-60%, width up to ~25%). :func:`compute_bone_placements` (R7)
is the fuller transform: it also translates each bone to the target base
bone's position and stretches it to the target bone's length, so each
clothing region is positioned AND scaled to the new base. Girth (across-
bone thickness) is left to the surface fit (card R8).
"""


def _parent_first(armature_obj):
    """Bones of ``armature_obj`` in parent-before-child order, so a caller
    setting each bone's world matrix in turn (with a depsgraph update
    between) has the parent's posed transform available when it sets a
    child."""
    order = []

    def walk(bone):
        order.append(bone)
        for child in bone.children:
            walk(child)

    for bone in armature_obj.data.bones:
        if bone.parent is None:
            walk(bone)
    return order


def compute_bone_placements(garment_arm, target_arm, bone_pairs):
    """Full per-bone PLACEMENT (position + rotation + length-scale) mapping
    the garment's skeleton onto the target base's skeleton (roadmap R7).

    Where :func:`compute_pose_rotations` transfers only rotation, this
    makes each garment bone coincide with the target base bone's current
    (posed) world position, orientation, AND length -- so the garment,
    deformed through its own skin weights, is moved to the right place,
    turned the right way, and stretched to the right size for the target
    base. This is what fixes a garment authored for one base landing too
    low / wrongly sized on another (measured: hips differ ~10cm, limb bones
    25-60%, across the real bases).

    Returns an ordered list of ``(garment_bone_name, world_rigid_matrix,
    length_scale)`` in parent-first order (see :func:`_parent_first`):

    - ``world_rigid_matrix`` is an **orthonormal** rotation + translation
      (the target bone's world position and orientation) -- no scale baked
      in, so a caller can set it via ``pose_bone.matrix`` cleanly.
    - ``length_scale`` is ``target_bone_length / garment_bone_rest_length``
      (both in world units) -- the along-bone (Y) stretch the caller applies
      separately via ``pose_bone.scale.y``. Girth (X/Z) is left at rest; the
      surface fit refines thickness (card R8).

    Keeping rotation and scale separate avoids a non-orthonormal matrix that
    Blender's decomposition would mangle into the wrong axis. Pure reads; no
    scene mutation. Rotation-only :func:`compute_pose_rotations` is retained
    for the Fit/Batch stage-0 integration until R8 switches it over.
    """
    target_world = target_arm.matrix_world
    garment_world = garment_arm.matrix_world
    pairs = dict(bone_pairs)

    placements = []
    for garment_bone in _parent_first(garment_arm):
        target_name = pairs.get(garment_bone.name)
        if target_name is None:
            continue
        target_pose_bone = target_arm.pose.bones.get(target_name)
        if target_pose_bone is None:
            continue

        head = target_world @ target_pose_bone.head
        tail = target_world @ target_pose_bone.tail
        target_length = (tail - head).length
        if target_length < 1e-9:
            continue

        # Orthonormal rotation from the target bone's world orientation.
        rotation = (target_world @ target_pose_bone.matrix).to_quaternion()
        world_rigid = rotation.to_matrix().to_4x4()
        world_rigid.translation = head

        rest_head = garment_world @ garment_bone.head_local
        rest_tail = garment_world @ garment_bone.tail_local
        rest_length = (rest_tail - rest_head).length
        length_scale = target_length / rest_length if rest_length > 1e-9 else 1.0

        placements.append((garment_bone.name, world_rigid, length_scale))
    return placements


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
