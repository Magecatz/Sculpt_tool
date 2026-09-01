"""Shared test helpers: repo-root path setup, synthetic mesh builders.

Imported by every ``tests/test_*.py`` module (and ``tests/perf.py``).
Not itself a ``test_*`` module, so ``unittest``'s discovery in
``run_tests.py`` does not try to collect tests from it.

Every builder here makes small, synthetic, checked-in-safe meshes via
``bmesh`` -- none of this touches ``Test_Items/`` (gitignored, real
third-party creator assets, never used by the fast suite; see
``tests/perf.py`` for where a real asset could be pointed at manually).
"""

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def update_scene():
    """Force ``matrix_world`` and the evaluated depsgraph to catch up with
    any plain-Python mutation (``obj.location = ...``, ``v.co.z = ...`` +
    ``mesh.update()``, etc.).

    A ``bpy.ops`` operator call implicitly triggers this as part of its
    own execution (which is why ``test_solver.py``, driving the pipeline
    via ``bpy.ops.sculpttool.*``, never needs it explicitly) -- but a
    test calling ``core/`` functions directly, with no operator in
    between, can otherwise read a stale ``matrix_world`` or stale
    evaluated-mesh positions/normals right after such a mutation. Call
    this after any manual position mutation and before reading world-
    space positions or calling into ``core/`` directly. ``make_grid``/
    ``make_tube``/``world_positions``/``set_shape_key_active_positions``
    below all call this themselves already; it's only additional manual
    mutations (moving an object, editing ``v.co`` after creation) that
    need an explicit call.
    """
    bpy.context.view_layer.update()


def clear_scene():
    """Remove every object (and its mesh data) from the current scene.

    Call at the start of every test that creates objects, so tests don't
    leak state into each other via the shared ``bpy.data``/scene that
    persists for the whole ``--background`` process.
    """
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def link_object(name, bm):
    """Build a mesh Object named ``name`` from a ``bmesh.types.BMesh``,
    link it into the current scene, and free the bmesh."""
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def make_grid(name, x_segments=4, y_segments=4, size=1.0, location=(0.0, 0.0, 0.0)):
    """A flat, open (non-closed-boundary) quad grid -- the general-purpose
    small synthetic mesh used by most non-tube tests."""
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=x_segments, y_segments=y_segments, size=size)
    obj = link_object(name, bm)
    obj.location = location
    update_scene()
    return obj


def make_tube(name, segments=32, rings=20, radius=1.0, height=2.0, location=(0.0, 0.0, 0.0)):
    """An open-ended (no caps), quad tube: ``rings`` rings of ``segments``
    vertices each, wrapped around the Z axis -- the cylindrical/sleeve-
    shaped synthetic mesh ARCHITECTURE.md section 7's shrinkage
    measurement uses (32-segment, 20-ring by default, matching the
    documented repro exactly).
    """
    bm = bmesh.new()
    ring_verts = []
    for r in range(rings):
        z = -height / 2.0 + height * r / (rings - 1)
        row = []
        for s in range(segments):
            angle = 2.0 * math.pi * s / segments
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            row.append(bm.verts.new((x, y, z)))
        ring_verts.append(row)
    bm.verts.ensure_lookup_table()

    for r in range(rings - 1):
        for s in range(segments):
            s2 = (s + 1) % segments
            v1 = ring_verts[r][s]
            v2 = ring_verts[r][s2]
            v3 = ring_verts[r + 1][s2]
            v4 = ring_verts[r + 1][s]
            bm.faces.new((v1, v2, v3, v4))

    obj = link_object(name, bm)
    obj.location = location
    update_scene()
    return obj


def make_valley(name, arm_length=2.0, y0=-1.0, y1=1.0, location=(0.0, 0.0, 0.0)):
    """A V-shaped concave crease (two large flat quads meeting at a fold
    along the line x=0, z=0, extruded along Y) -- a minimal stand-in for a
    body's concave regions (armpit, crotch) where two surface folds meet
    at an inward angle. Solid material fills ``z <= -x`` for ``x <= 0``
    and ``z <= x`` for ``x >= 0`` (i.e. everything "below" the fold, the
    ordinary convention for a body's outer surface); the crease at the
    origin line is the concave feature.

    Left quad spans ``x`` in ``[-arm_length, 0]`` with outward normal
    ``(1, 0, 1)/sqrt(2)``; right quad spans ``x`` in ``[0, arm_length]``
    with outward normal ``(-1, 0, 1)/sqrt(2)`` -- both point "up and
    toward the crease", i.e. away from the solid on their own local
    surface, which is exactly what makes a vertex sitting near the crease
    ambiguous: the two nearby surfaces disagree considerably on push-out
    direction. See ``tests/test_collision.py``'s
    ``ConcavePushOutDirectionTest`` for how this reproduces the residual
    penetration measured on real garments in concave/self-occluding
    regions (card 1e252575-2b86-4ba5-89f7-bcf0ae9685ba).
    """
    bm = bmesh.new()
    lA1 = bm.verts.new((-arm_length, y0, arm_length))
    lA2 = bm.verts.new((0.0, y0, 0.0))
    lA3 = bm.verts.new((0.0, y1, 0.0))
    lA4 = bm.verts.new((-arm_length, y1, arm_length))
    bm.faces.new((lA1, lA2, lA3, lA4))

    rA1 = bm.verts.new((0.0, y0, 0.0))
    rA2 = bm.verts.new((arm_length, y0, arm_length))
    rA3 = bm.verts.new((arm_length, y1, arm_length))
    rA4 = bm.verts.new((0.0, y1, 0.0))
    bm.faces.new((rA1, rA2, rA3, rA4))
    bm.normal_update()

    obj = link_object(name, bm)
    obj.location = location
    update_scene()
    return obj


def make_pin_group(obj, name, vertex_weights):
    """Create a ``Pin_``-prefixed vertex group on ``obj``.

    ``vertex_weights`` is ``{vertex_index: weight}``; vertices not named
    default to no membership in the group at all (i.e. weight 0 via
    ``core.smoothing.compute_pin_weights``'s "not in any Pin_ group"
    handling, not an explicit 0.0 group entry).
    """
    group = obj.vertex_groups.new(name=name)
    for index, weight in vertex_weights.items():
        group.add([index], weight, 'REPLACE')
    return group


def make_armature(name, bones, location=(0.0, 0.0, 0.0)):
    """Build an Armature Object named ``name`` from a bone spec and link it.

    ``bones`` is a list of ``(bone_name, head, tail, parent_name_or_None)``
    tuples -- optionally with a 5th ``roll`` element (radians) to give a
    bone a non-default roll (used by the pose-transfer tests to build two
    rigs whose bones share a rest direction but differ in roll). ``head``/
    ``tail`` are 3-tuples in armature-local space, and ``parent_name`` (if
    given) must name an earlier bone in the list. Returns the Armature
    Object (in Object mode).
    """
    arm_data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, arm_data)
    bpy.context.collection.objects.link(obj)

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    created = {}
    for spec in bones:
        bone_name, head, tail, parent_name = spec[0], spec[1], spec[2], spec[3]
        roll = spec[4] if len(spec) > 4 else 0.0
        edit_bone = arm_data.edit_bones.new(bone_name)
        edit_bone.head = head
        edit_bone.tail = tail
        edit_bone.roll = roll
        if parent_name is not None:
            edit_bone.parent = created[parent_name]
        created[bone_name] = edit_bone
    bpy.ops.object.mode_set(mode='OBJECT')

    obj.location = location
    update_scene()
    return obj


def bind_mesh_to_armature(mesh_obj, armature_obj):
    """Attach an Armature modifier on ``mesh_obj`` driven by
    ``armature_obj`` (the normal way a skinned mesh is rigged), and return
    the modifier. Does not create vertex-group skin weights -- callers that
    need weights add them separately."""
    modifier = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
    modifier.object = armature_obj
    update_scene()
    return modifier


def skin_mesh_all_to_bone(mesh_obj, armature_obj, bone_name):
    """Skin every vertex of ``mesh_obj`` to a single ``bone_name`` (weight
    1.0) and attach an Armature modifier -- the minimal rigged mesh the
    pose-transfer tests (roadmap R3) need to see a garment follow a posed
    bone. Returns the created vertex group."""
    group = mesh_obj.vertex_groups.new(name=bone_name)
    group.add(list(range(len(mesh_obj.data.vertices))), 1.0, 'REPLACE')
    modifier = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
    modifier.object = armature_obj
    update_scene()
    return group


def point_bone_along(armature_obj, bone_name, world_dir):
    """Pose ``bone_name`` so it points along ``world_dir`` (armature assumed
    at identity world rotation, as ``make_armature`` builds it). Sets the
    pose bone's armature-space matrix and returns nothing. Used by the
    pose-transfer tests to put a target rig into a known, non-rest pose
    (Blender bones point along their local +Y, so posing by a raw local
    quaternion is a twist, not a swing -- this avoids that gotcha)."""
    from mathutils import Matrix, Vector

    world_dir = Vector(world_dir).normalized()
    pose_bone = armature_obj.pose.bones[bone_name]
    bone = armature_obj.data.bones[bone_name]
    rest = bone.matrix_local
    rest_axis = (rest.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
    swing = rest_axis.rotation_difference(world_dir)
    new_rotation = (swing.to_matrix() @ rest.to_3x3()).to_4x4()
    pose_bone.matrix = Matrix.Translation(rest.to_translation()) @ new_rotation
    update_scene()


def posed_bone_direction(armature_obj, bone_name):
    """World-space (tail - head) direction of a pose bone in its CURRENT
    pose -- for asserting that a bone actually rotated to follow a pose."""
    update_scene()
    pose_bone = armature_obj.pose.bones[bone_name]
    matrix = armature_obj.matrix_world
    head = matrix @ pose_bone.head
    tail = matrix @ pose_bone.tail
    return (tail - head).normalized()


def world_positions(obj):
    """World-space ``Vector`` position per vertex, in vertex-index order."""
    update_scene()
    matrix = obj.matrix_world
    return [matrix @ v.co for v in obj.data.vertices]


def set_shape_key_active_positions(obj, key_name):
    """Return the world-space positions a named Shape Key block holds,
    for asserting against post-fit output without re-running the solver."""
    update_scene()
    key_block = obj.data.shape_keys.key_blocks[key_name]
    matrix = obj.matrix_world
    return [matrix @ Vector(key_block.data[i].co) for i in range(len(key_block.data))]


def max_component_diff(a, b):
    """Largest per-component absolute difference between two equal-length
    lists of ``Vector``s -- used for bit-identical/near-identical asserts."""
    worst = 0.0
    for va, vb in zip(a, b):
        for ca, cb in zip(va, vb):
            worst = max(worst, abs(ca - cb))
    return worst
