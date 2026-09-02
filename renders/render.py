"""One parametric showcase renderer for the retarget pipeline (dev tooling).

Replaces the pile of one-off ``render_r*.py`` / ``render_*_fix.py`` /
``render_variants.py`` scripts: it retargets real ``Test_Items`` garments
onto real bases through the deployed operators (bind + placement + conform)
and renders a solid Workbench image. Two modes:

    # multi-view of one outfit (default: full Tech Set -> Egirl)
    blender --background --factory-startup --python renders/render.py -- views

    # PLACEMENT ONLY -- position + scale + pose via the armature, no surface
    # conform (bind/collision/smoothing). Same args as ``views``.
    blender --background --factory-startup --python renders/render.py -- place

    # grid of assorted garment x base pairings
    blender --background --factory-startup --python renders/render.py -- combos

``views`` also takes optional overrides after the mode:
    ... -- views "Sweater by Vinuzhka,pants by Vinuzhka" Egirl
where the second arg is a comma-separated mesh list from
``FBX-Tech Set by Vinuzhka.fbx`` and the third is a base key (Egirl /
Fantasy / Venus). Output PNGs go to ``renders/out/`` (gitignored).

Everything imports ``renderlib`` for the shared path/config/camera helpers,
so nothing hard-codes a machine path. ``renderlib.SMOOTHING_ITERATIONS``
controls the smoothing passes the showcase fits use.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy

sys.path.insert(0, str(R.REPO_ROOT))
import sculpt_tool  # noqa: E402
from sculpt_tool.core import rig  # noqa: E402
from sculpt_tool.operators import op_bases, op_pose  # noqa: E402

if not hasattr(bpy.types.Object, "sculpt_tool"):
    sculpt_tool.register()

SKIN = (0.80, 0.63, 0.54, 1.0)
CLOTH = [(0.26, 0.55, 0.72, 1.0), (0.66, 0.34, 0.50, 1.0), (0.40, 0.68, 0.48, 1.0)]
BODY = R.TEST_ITEMS / "Body"
CLOTHING = R.TEST_ITEMS / "Clothing"

# Base key -> (fbx, mesh object name). The target base is whichever the user
# retargets onto. Venus is a different creator's rig (cross-creator test).
BASES = {
    "Egirl": ("vrbase_Egirl_Heeled Foot.fbx", "BODY"),
    "Fantasy": ("vrbase_Fantasy_Heeled Foot.fbx", "BODY"),
    "Venus": ("Project Venus_v2.02.fbx", "Body"),
}
# The Tech Set was authored for ZinPia (its rig shares ZinPia's bone naming),
# so ZinPia is its Source Base for the standoff measurement (RESTART_SCOPE.md).
SOURCE_ZIN = ("ZinPia_Fit Base HEELED Foot High Poly.fbx", "ZIN_FIT BASE")
TECH_SET = "FBX-Tech Set by Vinuzhka.fbx"


def _clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def _conform(garment_objs, src_body, base_body, base_rig, color):
    """Place + conform every mesh in ``garment_objs`` onto the base via the
    rebuilt Direction-B operator (``sculpttool.conform``). ``src_body`` is the
    garment's Source Base for authored-standoff (or ``None`` to use the
    source-free fallback)."""
    for gm in [o for o in garment_objs if o.type == 'MESH']:
        s = gm.sculpt_tool
        s.source_body = src_body
        s.target_body = base_body
        s.target_base_armature = base_rig
        bpy.context.view_layer.objects.active = gm
        gm.select_set(True)
        bpy.ops.sculpttool.conform()
        gm.color = color


def _place(garment_objs, base_rig, color):
    """PLACEMENT ONLY -- position + rotation(pose) + length-scale each mesh in
    ``garment_objs`` onto ``base_rig`` via the garment's own armature, and
    leave the Armature modifier live so the placement deforms the mesh at
    render time. No bind, no conform, no collision, no smoothing -- this is
    the R7 placement stage on its own (``op_pose.place_garment_onto_rig``),
    the "positioning, scaling, posing" the tool is trusted to get right."""
    for gm in [o for o in garment_objs if o.type == 'MESH']:
        s = gm.sculpt_tool
        s.target_base_armature = base_rig
        garment_arm = op_bases.garment_rig(gm, s)
        gm.color = color
        if garment_arm is None:
            print(f"  [place] {gm.name!r}: no garment rig found -- left unplaced")
            continue
        placed = op_pose.place_garment_onto_rig(bpy.context, garment_arm, base_rig, [])
        print(f"  [place] {gm.name!r}: {placed} bones (position + rotation + scale)")


def render_place_views(garment_meshes, base_key):
    """One outfit from ``FBX-Tech Set`` PLACED onto one base (armature
    position + scale + pose only -- no surface conform), rendered from four
    camera angles. The placement-only counterpart of :func:`render_views`,
    for judging whether the placement stage alone lands the garment."""
    _clear()
    base_fbx, base_obj = BASES[base_key]
    base = R.import_group(BODY / base_fbx, {base_obj})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)

    gobjs = []
    for i, mesh_name in enumerate(garment_meshes):
        piece = R.import_group(CLOTHING / TECH_SET, {mesh_name})
        _place(piece, base_rig, CLOTH[i % len(CLOTH)])
        gobjs.extend(piece)
    base_body.color = SKIN
    meshes = [base_body] + [o for o in gobjs if o.type == 'MESH']

    R.setup_workbench(resolution=(1000, 1300))
    for az, name in [(0, "front"), (40, "three-quarter"), (90, "side"), (180, "back")]:
        for o in list(bpy.data.objects):
            if o.type in {'FONT', 'CAMERA'}:
                bpy.data.objects.remove(o, do_unlink=True)
        _, _, mn, _ = R._scene_bounds(meshes)
        center, _, _, _ = R._scene_bounds(meshes)
        R.add_label(f"Tech Set -> {base_key}  (placed: pos+scale+pose, {name})",
                    (center.x, mn.y - 0.3, mn.z - 0.12),
                    size=0.06, color=(0.95, 0.95, 0.98), face_deg=az)
        R.frame_camera(meshes, azimuth_deg=az, elevation_deg=6, zoom=0.95)
        R.render_to(R.OUT_DIR / f"place_{name}.png")


def render_views(garment_meshes, base_key):
    """One outfit from ``FBX-Tech Set`` onto one base, rendered from four
    camera angles (front / three-quarter / side / back)."""
    _clear()
    base_fbx, base_obj = BASES[base_key]
    src = R.import_group(BODY / SOURCE_ZIN[0], {SOURCE_ZIN[1]})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(BODY / base_fbx, {base_obj})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)

    gobjs = []
    for i, mesh_name in enumerate(garment_meshes):
        piece = R.import_group(CLOTHING / TECH_SET, {mesh_name})
        _conform(piece, src_body, base_body, base_rig, CLOTH[i % len(CLOTH)])
        gobjs.extend(piece)
    for o in src:
        bpy.data.objects.remove(o, do_unlink=True)
    base_body.color = SKIN
    meshes = [base_body] + [o for o in gobjs if o.type == 'MESH']

    R.setup_workbench(resolution=(1000, 1300))
    for az, name in [(0, "front"), (40, "three-quarter"), (90, "side"), (180, "back")]:
        for o in list(bpy.data.objects):
            if o.type in {'FONT', 'CAMERA'}:
                bpy.data.objects.remove(o, do_unlink=True)
        _, _, mn, _ = R._scene_bounds(meshes)
        center, _, _, _ = R._scene_bounds(meshes)
        R.add_label(f"Tech Set -> {base_key}  ({name})", (center.x, mn.y - 0.3, mn.z - 0.12),
                    size=0.06, color=(0.95, 0.95, 0.98), face_deg=az)
        R.frame_camera(meshes, azimuth_deg=az, elevation_deg=6, zoom=0.95)
        R.render_to(R.OUT_DIR / f"view_{name}.png")


# (garment fbx, {meshes}, base key, label) -- assorted pairings, each garment
# on a base it wasn't authored for.
COMBO_ENTRIES = [
    ("bodysuit.fbx", {"bodysuit by skulli"}, "Fantasy", "bodysuit -> Fantasy"),
    ("Summer SET.fbx", {"Set"}, "Venus", "Summer Set -> Venus"),
    ("cybercroptopfinalizedUVedRigged.fbx", {"Body"}, "Egirl", "cyber crop -> Egirl"),
    ("E-girl.fbx", {"Tech top .001", "Tech Pants .001"}, "Fantasy", "E-girl set -> Fantasy"),
    ("Cyber Bunny Outfit by Yukina - E-girl.fbx", {"Bunny Suit"}, "Venus", "Bunny Suit -> Venus"),
    ("Cyber Bunny Outfit by Yukina - E-girl.fbx", {"Hood Crop"}, "Egirl", "Hood Crop -> Egirl"),
]


def render_combos():
    """A row of assorted garment x base pairings. These garments are NOT the
    Tech Set and their original source bases aren't in the corpus, so they
    exercise the source-free standoff fallback (``src_body=None``)."""
    _clear()
    meshes = []
    for i, (gf, mesh_names, base_key, label) in enumerate(COMBO_ENTRIES):
        base_fbx, base_obj = BASES[base_key]
        base = R.import_group(BODY / base_fbx, {base_obj})
        base_body = next(o for o in base if o.type == 'MESH')
        base_rig = rig.deforming_armature(base_body)
        garment = R.import_group(CLOTHING / gf, mesh_names)
        _conform(garment, None, base_body, base_rig, CLOTH[i % len(CLOTH)])
        R.offset_group(base + garment, (i * 1.5, 0, 0))
        base_body.color = SKIN
        meshes += [base_body] + [o for o in garment if o.type == 'MESH']

    R.setup_workbench(resolution=(2400, 780))
    center, _, mins, maxs = R._scene_bounds(meshes)
    R.add_label("Assorted garments on swapped bases (three-quarter view)",
                (center.x, mins.y - 0.3, maxs.z + 0.2), size=0.08,
                color=(0.96, 0.96, 0.98), face_deg=30)
    for i, (gf, mesh_names, base_key, label) in enumerate(COMBO_ENTRIES):
        R.add_label(label, (i * 1.5, mins.y - 0.3, mins.z - 0.12), size=0.05,
                    color=(0.82, 0.88, 0.95), face_deg=30)
    R.frame_camera(meshes, azimuth_deg=30, elevation_deg=6, zoom=1.06)
    R.render_to(R.OUT_DIR / "combos_3q.png")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    mode = argv[0] if argv else "views"
    if mode == "combos":
        render_combos()
    else:
        garment_meshes = (argv[1].split(",") if len(argv) > 1
                          else ["Sweater by Vinuzhka", "pants by Vinuzhka"])
        base_key = argv[2] if len(argv) > 2 else "Egirl"
        if mode == "place":
            render_place_views(garment_meshes, base_key)
        else:
            render_views(garment_meshes, base_key)


if __name__ == "__main__":
    main()
