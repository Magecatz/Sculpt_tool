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
