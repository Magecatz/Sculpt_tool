"""Four-view showcase of one garment (or outfit) conformed onto one base
(dev tooling). Renders front / three-quarter / side / back of a single
garment x base combo through the deployed operators.

  blender --background --factory-startup --python renders/showcase.py -- \
      <fbx> "<mesh1,mesh2,...>" <BaseKey> [SourceKey]

``SourceKey`` (optional) picks a Source Base for source-measured standoff
(e.g. ZinPia for the Tech Set); omit it for the source-free fallback.
Output: out/show_<slug>_<Base>_{front,three-quarter,side,back}.png
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

BODY = R.TEST_ITEMS / "Body"
CLOTHING = R.TEST_ITEMS / "Clothing"
BASES = {
    "Egirl": ("vrbase_Egirl_Heeled Foot.fbx", "BODY"),
    "Fantasy": ("vrbase_Fantasy_Heeled Foot.fbx", "BODY"),
    "Venus": ("Project Venus_v2.02.fbx", "Body"),
    "RP": ("RP Female Base_Heeled Foot.fbx", "Body"),
    "ZinPia": ("ZinPia_Fit Base HEELED Foot High Poly.fbx", "ZIN_FIT BASE"),
}
SOURCES = {"ZinPia": ("ZinPia_Fit Base HEELED Foot High Poly.fbx", "ZIN_FIT BASE")}
SKIN = (0.80, 0.63, 0.54, 1.0)
CLOTH = [(0.26, 0.55, 0.72, 1.0), (0.66, 0.34, 0.50, 1.0), (0.40, 0.68, 0.48, 1.0),
         (0.85, 0.70, 0.35, 1.0), (0.72, 0.40, 0.55, 1.0)]
VIEWS = [(0, "front"), (40, "three-quarter"), (90, "side"), (180, "back")]


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    fbx, mesh_names = argv[0], [m for m in argv[1].split(",") if m]
    base_key = argv[2] if len(argv) > 2 else "Venus"
    source_key = argv[3] if len(argv) > 3 else None
    slug = mesh_names[0].split(" ")[0].lower()

    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

    src_body = None
    if source_key and source_key in SOURCES:
        sfbx, sname = SOURCES[source_key]
        src = R.import_group(BODY / sfbx, {sname})
        src_body = next(o for o in src if o.type == 'MESH')

    base_fbx, base_obj = BASES[base_key]
    base = R.import_group(BODY / base_fbx, {base_obj})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)

    garments = []
    for i, name in enumerate(mesh_names):
        piece = R.import_group(CLOTHING / fbx, {name})
        for gm in [o for o in piece if o.type == 'MESH']:
            s = gm.sculpt_tool
            s.source_body = src_body
            s.target_body = base_body
            s.target_base_armature = base_rig
            gm.color = CLOTH[i % len(CLOTH)]
            bpy.context.view_layer.objects.active = gm
            gm.select_set(True)
            bpy.ops.sculpttool.conform()
            garments.append(gm)

    if src_body is not None:
        for o in list(bpy.data.objects):
            if o is src_body:
                bpy.data.objects.remove(o, do_unlink=True)
    base_body.color = SKIN
    meshes = [base_body] + garments

    R.setup_workbench(resolution=(1000, 1300))
    for az, name in VIEWS:
        for o in list(bpy.data.objects):
            if o.type in {'FONT', 'CAMERA'}:
                bpy.data.objects.remove(o, do_unlink=True)
        c, _, mn, _ = R._scene_bounds(meshes)
        R.add_label(f"{slug} -> {base_key}  ({name})",
                    (c.x, mn.y - 0.3, mn.z - 0.12), size=0.06,
                    color=(0.95, 0.95, 0.98), face_deg=az)
        R.frame_camera(meshes, azimuth_deg=az, elevation_deg=6, zoom=0.95)
        R.render_to(R.OUT_DIR / f"show_{slug}_{base_key}_{name}.png")
    print(f"  [showcase] {slug} -> {base_key}: {len(garments)} garment(s), 4 views")


if __name__ == "__main__":
    main()
