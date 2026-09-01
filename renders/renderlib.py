"""Reusable headless-Blender render helpers for Sculpt Tool showcase renders.

These scripts import the real (gitignored) ``Test_Items`` FBX assets, run
the add-on through its real operators, and render a solid Workbench image so
each stage of the retarget pipeline can be seen. They are DEV TOOLING, not
part of the shipped add-on and not run by the test suite -- opt-in, like
``tests/perf.py`` / ``tests/corpus_repro.py`` (they need the local asset
corpus). Kept in the repo so they don't have to be re-created each time.

Run pattern (from anywhere)::

    blender --background --factory-startup --python renders/render_r8.py

Each ``render_*.py`` does ``sys.path.insert(0, <this dir>); import renderlib
as R`` and uses ``R.REPO_ROOT`` / ``R.TEST_ITEMS`` / ``R.SMOOTHING_ITERATIONS``
so nothing hard-codes a machine path. Output PNGs go to ``renders/out/``
(gitignored).
"""
import os
import subprocess
import sys
from pathlib import Path

import bpy
from mathutils import Vector

# renders/ sits at the repo root, so the repo root is this file's grandparent.
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "out"

# How many pin-weighted smoothing iterations the showcase fits use. Set to 0
# for raw fits; a few iterations clean projection/collision noise. Override
# per script with `R.SMOOTHING_ITERATIONS = N` before fitting if needed.
SMOOTHING_ITERATIONS = 6

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _find_test_items():
    """Locate the gitignored ``Test_Items`` corpus -- checked, in order: the
    ``SCULPT_TOOL_TEST_ITEMS`` env var, ``<repo>/Test_Items``, then
    ``Test_Items`` next to the main git worktree (so a linked worktree that
    lacks its own copy still finds it). Same strategy as
    ``tests/corpus_repro.py``. Returns a ``Path`` (which may not exist)."""
    candidates = []
    env = os.environ.get("SCULPT_TOOL_TEST_ITEMS")
    if env:
        candidates.append(Path(env))
    candidates.append(REPO_ROOT / "Test_Items")
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=True,
        )
        common_dir = proc.stdout.strip()
        if common_dir:
            candidates.append(Path(common_dir).resolve().parent / "Test_Items")
    except Exception:
        pass
    for candidate in candidates:
        if (candidate / "Body").is_dir() and (candidate / "Clothing").is_dir():
            return candidate
    return candidates[-1] if candidates else (REPO_ROOT / "Test_Items")


TEST_ITEMS = _find_test_items()


def _base_name(name):
    stem, sep, suffix = name.rpartition(".")
    if sep and suffix.isdigit():
        return stem
    return name


def import_named(fbx_path, object_name, keep_armature=False):
    """Import an FBX and return (mesh_obj, armature_obj_or_None) matching
    object_name. Optionally keeps the armature that deforms it; removes
    everything else the import brought in."""
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(filepath=str(fbx_path))
    imported = [o for o in bpy.data.objects if o.name not in before]

    match = None
    for o in imported:
        if o.name == object_name:
            match = o
            break
    if match is None:
        for o in imported:
            if _base_name(o.name) == object_name:
                match = o
                break
    if match is None:
        names = [o.name for o in imported]
        raise RuntimeError(f"{object_name!r} not in {fbx_path.name}; got {names[:20]}")

    armature = None
    if keep_armature:
        for mod in match.modifiers:
            if mod.type == 'ARMATURE' and mod.object is not None:
                armature = mod.object
                break
        if armature is None and match.parent and match.parent.type == 'ARMATURE':
            armature = match.parent

    for o in imported:
        if o is match or (keep_armature and o is armature):
            continue
        bpy.data.objects.remove(o, do_unlink=True)

    return match, armature


def import_group(fbx_path, keep_mesh_names):
    """Import an FBX and keep only the named meshes plus any armature/parent
    they depend on; return the list of kept objects. Removes the rest."""
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(filepath=str(fbx_path))
    imported = [o for o in bpy.data.objects if o.name not in before]

    keep = set()
    for o in imported:
        if o.type == 'MESH' and (o.name in keep_mesh_names or _base_name(o.name) in keep_mesh_names):
            keep.add(o)
            for m in o.modifiers:
                if m.type == 'ARMATURE' and m.object is not None:
                    keep.add(m.object)
            p = o.parent
            while p is not None:
                keep.add(p)
                p = p.parent
    for o in imported:
        if o not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    return [o for o in imported if o in keep]


def offset_group(objects, delta):
    """Translate a group by delta, moving only the parentless roots so a
    parented mesh/armature hierarchy isn't double-moved."""
    objset = set(objects)
    for o in objects:
        if o.parent not in objset:
            o.location = o.location + Vector(delta)
    bpy.context.view_layer.update()


def add_label(text, location, size=0.12, color=(0.95, 0.95, 0.97)):
    """A 3D text object standing up in the XZ plane (facing -Y, the camera)."""
    import math
    curve = bpy.data.curves.new(type="FONT", name="Label")
    curve.body = text
    curve.align_x = 'CENTER'
    curve.size = size
    obj = bpy.data.objects.new("Label", curve)
    obj.location = location
    obj.rotation_euler = (math.radians(90), 0, 0)
    mat = bpy.data.materials.new("LabelMat")
    mat.diffuse_color = (*color, 1.0)
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.update()
    return obj


def _scene_bounds(objects):
    mins = Vector((1e18, 1e18, 1e18))
    maxs = Vector((-1e18, -1e18, -1e18))
    for obj in objects:
        for corner in obj.bound_box:
            wc = obj.matrix_world @ Vector(corner)
            for i in range(3):
                mins[i] = min(mins[i], wc[i])
                maxs[i] = max(maxs[i], wc[i])
    center = (mins + maxs) * 0.5
    radius = (maxs - mins).length * 0.5
    return center, radius, mins, maxs


def frame_camera(objects, azimuth_deg=0.0, elevation_deg=8.0, zoom=1.05):
    """Place a camera looking at the objects from the front (-Y), framing
    the full bounding sphere. azimuth rotates around Z."""
    import math

    center, radius, _, _ = _scene_bounds(objects)
    cam_data = bpy.data.cameras.new("RenderCam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("RenderCam", cam_data)
    bpy.context.collection.objects.link(cam)

    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    dist = radius * 3.2 * zoom
    direction = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    cam.location = center + direction * dist

    look = (center - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = cam
    return cam


def setup_workbench(resolution=(1000, 1300), light='STUDIO'):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    shading = scene.display.shading
    shading.light = light
    shading.color_type = 'OBJECT'
    shading.single_color = (0.72, 0.73, 0.78)
    shading.show_shadows = True
    shading.show_cavity = True
    shading.cavity_type = 'BOTH'
    scene.display.render_aa = '8'
    scene.render.resolution_x = resolution[0]
    scene.render.resolution_y = resolution[1]
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'Standard'
    world = bpy.data.worlds.new("W") if not bpy.data.worlds else bpy.data.worlds[0]
    world.use_nodes = False
    world.color = (0.05, 0.055, 0.07)
    scene.world = world


def render_to(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(path)
    bpy.context.scene.render.image_settings.file_format = 'PNG'
    bpy.ops.render.render(write_still=True)
    print("WROTE", path)
