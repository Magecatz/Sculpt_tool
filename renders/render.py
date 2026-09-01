"""One parametric showcase renderer for the retarget pipeline (dev tooling).

Replaces the pile of one-off ``render_r*.py`` / ``render_*_fix.py`` /
``render_variants.py`` scripts: it retargets real ``Test_Items`` garments
onto real bases through the deployed operators (bind + placement + conform)
and renders a solid Workbench image. Two modes:

    # multi-view of one outfit (default: full Tech Set -> Egirl)
    blender --background --factory-startup --python renders/render.py -- views

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

if not hasattr(bpy.types.Object, "sculpt_tool"):
    sculpt_tool.register()

SKIN = (0.80, 0.63, 0.54, 1.0)
CLOTH = [(0.26, 0.55, 0.72, 1.0), (0.66, 0.34, 0.50, 1.0), (0.40, 0.68, 0.48, 1.0)]
BODY = R.TEST_ITEMS / "Body"
CLOTHING = R.TEST_ITEMS / "Clothing"

# Base key -> (fbx, mesh object name). The source base a garment was authored
# for is RP Female Base; the target base is whichever the user retargets onto.
BASES = {
    "Egirl": ("vrbase_Egirl_Heeled Foot.fbx", "BODY"),
    "Fantasy": ("vrbase_Fantasy_Heeled Foot.fbx", "BODY"),
    "Venus": ("Project Venus_v2.02.fbx", "Body"),
}
SOURCE_RP = ("RP Female Base_Heeled Foot.fbx", "Body")
TECH_SET = "FBX-Tech Set by Vinuzhka.fbx"


def _clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def _fit(garment_objs, src_body, base_body, base_rig, color):
    """Bind + place + conform every mesh in ``garment_objs`` onto the base."""
    for gm in [o for o in garment_objs if o.type == 'MESH']:
        s = gm.sculpt_tool
        s.source_body = src_body
        s.target_body = base_body
        s.bind_mode_override = 'MODE_B'
        s.target_base_armature = base_rig
        s.use_collision_resolution = True
        s.smoothing_iterations = R.SMOOTHING_ITERATIONS
        s.skip_alignment_check = True
        bpy.context.view_layer.objects.active = gm
        gm.select_set(True)
        bpy.ops.sculpttool.bind_garment()
        bpy.ops.sculpttool.fit_garment()
        gm.color = color


def render_views(garment_meshes, base_key):
    """One outfit from ``FBX-Tech Set`` onto one base, rendered from four
    camera angles (front / three-quarter / side / back)."""
    _clear()
    base_fbx, base_obj = BASES[base_key]
    src = R.import_group(BODY / SOURCE_RP[0], {SOURCE_RP[1]})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(BODY / base_fbx, {base_obj})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)

    gobjs = []
    for i, mesh_name in enumerate(garment_meshes):
        piece = R.import_group(CLOTHING / TECH_SET, {mesh_name})
        _fit(piece, src_body, base_body, base_rig, CLOTH[i % len(CLOTH)])
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
    """A row of assorted garment x base pairings, each via the full fit."""
    _clear()
    src_fbx, src_obj = SOURCE_RP
    meshes = []
    for i, (gf, mesh_names, base_key, label) in enumerate(COMBO_ENTRIES):
        src = R.import_group(BODY / src_fbx, {src_obj})
        src_body = next(o for o in src if o.type == 'MESH')
        base_fbx, base_obj = BASES[base_key]
        base = R.import_group(BODY / base_fbx, {base_obj})
        base_body = next(o for o in base if o.type == 'MESH')
        base_rig = rig.deforming_armature(base_body)
        garment = R.import_group(CLOTHING / gf, mesh_names)
        _fit(garment, src_body, base_body, base_rig, CLOTH[i % len(CLOTH)])
        for o in src:
            bpy.data.objects.remove(o, do_unlink=True)
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
        render_views(garment_meshes, base_key)


if __name__ == "__main__":
    main()
