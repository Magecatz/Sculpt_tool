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
is the fuller transform used by the Fit/Batch stage 0: it also translates
each bone to the target base bone's position and stretches it to the target
bone's length, so each clothing region is positioned AND scaled to the new
base. Girth (across-bone thickness) is left to the surface fit (card R8).
Both apply the SAME rest-orientation-compensated rotation (identity when
the target is at rest); :func:`compute_bone_placements` carries it in world
space (see its "Rotation" note -- fix A), :func:`compute_pose_rotations` in
bone-local space. :func:`compute_pose_rotations` is retained as the
rotation-only primitive (used by the standalone pose tests and available
for a rotation-only workflow); the operators use the full placement.
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

    - ``world_rigid_matrix`` is an **orthonormal** rotation + translation:
      the target bone's world *position*, and an orientation that carries
      the target's *pose change* onto the garment bone's OWN rest
      orientation (see "Rotation" below) -- no scale baked in, so a caller
      can set it via ``pose_bone.matrix`` cleanly.
    - ``length_scale`` is ``target_bone_length / garment_bone_rest_length``
      (both in world units) -- the along-bone (Y) stretch the caller applies
      separately via ``pose_bone.scale.y``. Girth (X/Z) is left at rest; the
      surface fit refines thickness (card R8).

    **Rotation (aim along the target's direction).** Each garment bone is
    aimed so its length axis points along the TARGET bone's actual world
    direction (head->tail), via the **minimal-arc swing** from the garment
    bone's own rest direction:

        garment_dir = (garment rest tail - head), world, normalized
        target_dir  = (target posed tail - head), world, normalized
        swing       = rotation taking garment_dir -> target_dir (minimal arc)
        world_rot   = swing . R_garment_rest

    This points each limb the way the target's limb points -- so a garment
    authored in one **rest pose** (e.g. a T-pose, arms out) correctly follows
    a target base in a DIFFERENT rest pose (e.g. an A-pose, arms down), the
    case the earlier "pose-delta only" form silently failed: it transferred
    only the target's rotation *relative to the target's own rest*, so an
    A-pose target at rest left the garment's arms in the garment's T-pose.

    Crucially the swing copies only the target's *direction*, never its
    roll/axis convention, so it does NOT reintroduce the regression where
    slamming the target's absolute orientation twisted the skinned region
    (measured Tech Set -> Egirl: ``Boob`` 142.9deg, ``Thumb`` 40-55deg).
    When the two bones already point the same way (a co-posed pair), the
    swing is identity and the garment bone keeps its own rest orientation --
    so that happy path is unchanged, now for the right reason.

    Keeping rotation and scale separate avoids a non-orthonormal matrix that
    Blender's decomposition would mangle into the wrong axis. Pure reads; no
    scene mutation.
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
        target_bone = target_arm.data.bones.get(target_name)
        if target_pose_bone is None or target_bone is None:
            continue

        head = target_world @ target_pose_bone.head
        tail = target_world @ target_pose_bone.tail
        target_length = (tail - head).length
        if target_length < 1e-9:
            continue

        rest_head = garment_world @ garment_bone.head_local
        rest_tail = garment_world @ garment_bone.tail_local
        rest_length = (rest_tail - rest_head).length
        if rest_length < 1e-9:
            continue

        # Aim the garment bone along the TARGET bone's actual world direction
        # (head->tail) via the minimal-arc SWING from the garment bone's own
        # rest direction (see the "Rotation" note above). This points each limb
        # the way the target's limb points -- so a garment authored in one rest
        # pose (T-pose) follows a target base in a DIFFERENT rest pose (A-pose)
        # -- while copying none of the target's roll/axis convention, so the
        # skinned cross-section isn't spun. Co-posed bones (garment_dir ==
        # target_dir) get an identity swing and keep their rest orientation.
        garment_rest_rot = (garment_world @ garment_bone.matrix_local).to_quaternion()
        garment_dir = (rest_tail - rest_head).normalized()
        target_dir = (tail - head).normalized()
        swing = garment_dir.rotation_difference(target_dir)
        rotation = (swing @ garment_rest_rot).normalized()

        world_rigid = rotation.to_matrix().to_4x4()
        world_rigid.translation = head

        # Scale each garment bone to the target's joint-to-joint SPAN -- the
        # distance from this bone's head to the head of its aligned mapped
        # child (the next joint down the chain) -- not the target bone's own
        # length. A target rig whose primary bones stop short of the next joint
        # (the remaining segment carried by twist/helper bones) would otherwise
        # shrink the garment segment to the stub: measured on Venus, the
        # Lower_Arm bone is 0.099 but the forearm span is 0.198, halving the
        # sleeve. ``max`` keeps the plain bone length wherever the target bone
        # already spans its segment (Egirl/Fantasy), so the span only ever
        # LENGTHENS a stub and never changes a base that was already correct.
        axis = (rest_tail - rest_head).normalized()
        target_span = 0.0
        best_align = 0.0  # only children that continue the bone (align > 0)
        for child in garment_bone.children:
            child_target_name = pairs.get(child.name)
            if child_target_name is None:
                continue
            child_target = target_arm.pose.bones.get(child_target_name)
            if child_target is None:
                continue
            child_vec = (garment_world @ child.head_local) - rest_head
            if child_vec.length <= 1e-9:
                continue
            align = child_vec.normalized().dot(axis)
            if align > best_align:
                best_align = align
                target_span = ((target_world @ child_target.head) - head).length
        length_scale = max(target_length, target_span) / rest_length

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
