"""Validate OT_batch_conform end to end (dev tooling): import the full
five-piece Tech Set onto Venus, set each piece's settings, select them all,
and conform the whole outfit in ONE sculpttool.batch_conform call, then
render. Confirms the batch operator (selection -> per-garment run_conform)
produces the same outfit as the per-piece views loop.

  blender --background --factory-startup --python renders/batch_demo.py
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
TECH_SET = "FBX-Tech Set by Vinuzhka.fbx"
SOURCE = ("ZinPia_Fit Base HEELED Foot High Poly.fbx", "ZIN_FIT BASE")
TARGET = ("Project Venus_v2.02.fbx", "Body")
PIECES = ["pasties by Vinuzhka", "Top by Vinuzhka", "Sweater by Vinuzhka",
          "pants by Vinuzhka", "Straps by Vinuzhka"]
SKIN = (0.80, 0.63, 0.54, 1.0)
CLOTH = [(0.26, 0.55, 0.72, 1.0), (0.66, 0.34, 0.50, 1.0), (0.40, 0.68, 0.48, 1.0)]


def main():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

    src = R.import_group(BODY / SOURCE[0], {SOURCE[1]})
    src_body = next(o for o in src if o.type == 'MESH')
    base = R.import_group(BODY / TARGET[0], {TARGET[1]})
    base_body = next(o for o in base if o.type == 'MESH')
    base_rig = rig.deforming_armature(base_body)

    garments = []
    for i, name in enumerate(PIECES):
        piece = R.import_group(CLOTHING / TECH_SET, {name})
        gm = next(o for o in piece if o.type == 'MESH')
        s = gm.sculpt_tool
        s.source_body = src_body
        s.target_body = base_body
        s.target_base_armature = base_rig
        gm.color = CLOTH[i % len(CLOTH)]
        garments.append(gm)

    # Select all garments and fire ONE batch call.
    bpy.ops.object.select_all(action='DESELECT')
    for gm in garments:
        gm.select_set(True)
    bpy.context.view_layer.objects.active = garments[0]
    result = bpy.ops.sculpttool.batch_conform()
    print(f"  [batch] operator result: {result}")

    for o in src:
        bpy.data.objects.remove(o, do_unlink=True)
    base_body.color = SKIN
    meshes = [base_body] + garments

    R.setup_workbench(resolution=(1000, 1300))
    for az, name in [(0, "front"), (40, "three-quarter")]:
        for o in list(bpy.data.objects):
            if o.type in {'FONT', 'CAMERA'}:
                bpy.data.objects.remove(o, do_unlink=True)
        c, _, mn, _ = R._scene_bounds(meshes)
        R.add_label(f"Batch Conform: full outfit -> Venus  ({name})",
                    (c.x, mn.y - 0.3, mn.z - 0.12), size=0.06,
                    color=(0.95, 0.95, 0.98), face_deg=az)
        R.frame_camera(meshes, azimuth_deg=az, elevation_deg=6, zoom=0.95)
        R.render_to(R.OUT_DIR / f"batch_{name}.png")


if __name__ == "__main__":
    main()
