"""Conform a single named garment piece onto a target base and render it
(dev tooling). Source-free fallback (no source base), so it exercises the
same path the combos use.

  blender --background --factory-startup --python renders/one_piece.py -- \
      "Cyber Bunny Outfit by Yukina - E-girl.fbx" "Bunny Suit" Venus
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
}
SKIN = (0.80, 0.63, 0.54, 1.0)
CLOTH = (0.40, 0.68, 0.48, 1.0)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    fbx, mesh_name, base_key = argv[0], argv[1], (argv[2] if len(argv) > 2 else "Venus")
    slug = mesh_name.split(" ")[0].lower()

    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

    base_fbx, base_obj = BASES[base_key]
    base = R.import_group(BODY / base_fbx, {base_obj})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)

    piece = R.import_group(CLOTHING / fbx, {mesh_name})
    for gm in [o for o in piece if o.type == 'MESH']:
        s = gm.sculpt_tool
        s.target_body = base_body
        s.target_base_armature = base_rig
        bpy.context.view_layer.objects.active = gm
        gm.select_set(True)
        bpy.ops.sculpttool.conform()
        gm.color = CLOTH

    base_body.color = SKIN
    meshes = [base_body] + [o for o in piece if o.type == 'MESH']
    R.setup_workbench(resolution=(1000, 1300))
    for az, name in [(0, "front"), (40, "three-quarter")]:
        for o in list(bpy.data.objects):
            if o.type in {'FONT', 'CAMERA'}:
                bpy.data.objects.remove(o, do_unlink=True)
        _, _, mn, _ = R._scene_bounds(meshes)
        center, _, _, _ = R._scene_bounds(meshes)
        R.add_label(f"{mesh_name} -> {base_key}  ({name})",
                    (center.x, mn.y - 0.3, mn.z - 0.12), size=0.05,
                    color=(0.95, 0.95, 0.98), face_deg=az)
        R.frame_camera(meshes, azimuth_deg=az, elevation_deg=6, zoom=0.98)
        R.render_to(R.OUT_DIR / f"piece_{slug}_{base_key}_{name}.png")


if __name__ == "__main__":
    main()
