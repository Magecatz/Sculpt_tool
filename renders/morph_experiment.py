"""Standalone body-morph experiment (dev tooling, NOT part of the add-on).

Question it answers: is the SOURCE->TARGET correspondence through the shared
skeleton trustworthy enough to drive a deformation field? (Direction A of the
restart re-eval.) No garment is involved -- this morphs the source *body*
(ZinPia, the base the Tech Set was authored for) onto the *target* base
skeleton (Egirl) via the canonical bone map, then shows it against the real
target body.

Method -- skinning-space reconstruction (reverse LBS across rigs):
  For each source-body vertex, express its rest world position in the local
  rest frame of every bone that skins it, then rebuild that local geometry on
  the *mapped target bone's* rest frame and blend by the same skin weights.
  This carries the source surface onto the target skeleton's proportions and
  pose. It preserves the source's radial thickness (girth), so where the
  reconstructed source (S') pokes OUT of / sinks INTO the real target body is
  exactly the girth difference a conform step must still close.

Renders (Workbench, renders/out/):
  morph_row_{front,three-quarter}.png -- [ZinPia | S' on Egirl frame | Egirl]
  morph_overlay_{front,three-quarter}.png -- S' (green) superimposed on the
      real Egirl body (skin), to read the residual girth field directly.

Run:
  blender --background --factory-startup --python renders/morph_experiment.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import renderlib as R
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(R.REPO_ROOT))
from sculpt_tool.core import rig, rig_map  # noqa: E402

BODY = R.TEST_ITEMS / "Body"
SOURCE = ("ZinPia_Fit Base HEELED Foot High Poly.fbx", "ZIN_FIT BASE")

# Target base key -> (fbx, mesh name). Venus is the cross-CREATOR test: the
# other bases are all ZinPia products (shared rig lineage), so ZinPia->Venus
# is the one that shows whether the skeletal correspondence generalizes past
# a single author's conventions.
TARGETS = {
    "Egirl": ("vrbase_Egirl_Heeled Foot.fbx", "BODY"),
    "Fantasy": ("vrbase_Fantasy_Heeled Foot.fbx", "BODY"),
    "Venus": ("Project Venus_v2.02.fbx", "Body"),
    "RP": ("RP Female Base_Heeled Foot.fbx", "Body"),
}

SKIN = (0.80, 0.63, 0.54, 1.0)
MORPH = (0.40, 0.68, 0.48, 1.0)   # S' reconstruction -- green
SOURCE_COL = (0.66, 0.55, 0.85, 1.0)  # original source -- lilac


def _clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def _bone_world_rest(arm):
    """name -> world-space rest matrix of each bone (armature world @ the
    bone's armature-space rest matrix)."""
    return {b.name: arm.matrix_world @ b.matrix_local for b in arm.data.bones}


def reconstruct_onto(src_mesh, src_arm, tgt_arm, pairs):
    """World positions of ``src_mesh``'s vertices rebuilt on ``tgt_arm``'s
    skeleton via ``pairs`` [(src_bone, tgt_bone)], blended by skin weight.
    A vertex with no mapped/weighted bone is left at its source position
    (flags a correspondence gap in the render)."""
    src2tgt = dict(pairs)
    src_rest = _bone_world_rest(src_arm)
    tgt_rest = _bone_world_rest(tgt_arm)
    src_rest_inv = {n: m.inverted() for n, m in src_rest.items()}
    m_world = src_mesh.matrix_world
    vg_name = {i: vg.name for i, vg in enumerate(src_mesh.vertex_groups)}

    out = []
    gaps = 0
    for v in src_mesh.data.vertices:
        p_world = m_world @ v.co
        acc = Vector((0.0, 0.0, 0.0))
        wsum = 0.0
        for g in v.groups:
            name = vg_name.get(g.group)
            tgt = src2tgt.get(name)
            if tgt is None or name not in src_rest or tgt not in tgt_rest or g.weight <= 0.0:
                continue
            local = src_rest_inv[name] @ p_world
            acc += g.weight * (tgt_rest[tgt] @ local)
            wsum += g.weight
        if wsum > 1e-6:
            out.append(acc / wsum)
        else:
            out.append(p_world)
            gaps += 1
    print(f"  [reconstruct] {len(out)} verts, {gaps} with no mapped-bone weight")
    return out


def _baked_copy(src_mesh, world_positions, name, color):
    """A standalone mesh object (identity world matrix, no armature) whose
    vertices are ``world_positions`` -- so it renders exactly as reconstructed."""
    me = src_mesh.data.copy()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    obj.matrix_world = Matrix.Identity(4)
    for i, co in enumerate(world_positions):
        me.vertices[i].co = co
    me.update()
    obj.color = color
    for mod in list(obj.modifiers):
        obj.modifiers.remove(mod)
    return obj


def _dup(obj, name, color, dx):
    me = obj.data.copy()
    d = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(d)
    d.matrix_world = Matrix.Translation((dx, 0, 0)) @ obj.matrix_world
    d.color = color
    return d


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    target_key = argv[0] if argv else "Egirl"
    target_fbx, target_mesh_name = TARGETS[target_key]
    print(f"\n=== BODY MORPH: ZinPia -> {target_key} ===")

    _clear()

    src = R.import_group(BODY / SOURCE[0], {SOURCE[1]})
    src_mesh = next(o for o in src if o.type == 'MESH')
    src_arm = rig.deforming_armature(src_mesh)

    tgt = R.import_group(BODY / target_fbx, {target_mesh_name})
    tgt_mesh = next(o for o in tgt if o.type == 'MESH')
    tgt_arm = rig.deforming_armature(tgt_mesh)

    bone_map = rig_map.build_bone_map(
        rig.bone_names(src_arm), rig.bone_names(tgt_arm)
    )
    pairs = bone_map.as_pairs()
    print(f"  [bone map] {len(pairs)} paired bones "
          f"(source {len(rig.bone_names(src_arm))}, target {len(rig.bone_names(tgt_arm))})")

    world = reconstruct_onto(src_mesh, src_arm, tgt_arm, pairs)
    morphed = _baked_copy(src_mesh, world, "ZinPia_on_Egirl", MORPH)

    tgt_mesh.color = SKIN
    src_mesh.color = SOURCE_COL

    # width for row spacing
    _, _, mn, mx = R._scene_bounds([tgt_mesh])
    gap = (mx.x - mn.x) * 1.7

    # ---- Panel 1: row [source | reconstruction | target] --------------
    src_row = _dup(src_mesh, "src_row", SOURCE_COL, -gap)
    tgt_row = _dup(tgt_mesh, "tgt_row", SKIN, +gap)
    row = [src_row, morphed, tgt_row]
    R.setup_workbench(resolution=(2000, 1300))
    for az, name in [(0, "front"), (40, "three-quarter")]:
        for o in list(bpy.data.objects):
            if o.type in {'FONT', 'CAMERA'}:
                bpy.data.objects.remove(o, do_unlink=True)
        c, _, mn2, _ = R._scene_bounds(row)
        R.add_label(f"ZinPia (source)          reconstructed -> {target_key} skeleton          {target_key} (target)",
                    (c.x, mn2.y - 0.3, mn2.z - 0.15), size=0.07,
                    color=(0.95, 0.95, 0.98), face_deg=az)
        R.frame_camera(row, azimuth_deg=az, elevation_deg=6, zoom=1.02)
        R.render_to(R.OUT_DIR / f"morph_{target_key}_row_{name}.png")
    bpy.data.objects.remove(src_row, do_unlink=True)
    bpy.data.objects.remove(tgt_row, do_unlink=True)

    # ---- Panel 2: overlay S' (green) on real Egirl (skin) -------------
    overlay = [tgt_mesh, morphed]
    R.setup_workbench(resolution=(1000, 1300))
    for az, name in [(0, "front"), (40, "three-quarter")]:
        for o in list(bpy.data.objects):
            if o.type in {'FONT', 'CAMERA'}:
                bpy.data.objects.remove(o, do_unlink=True)
        c, _, mn2, _ = R._scene_bounds(overlay)
        R.add_label(f"S' (green) over {target_key} (skin): green out = source thicker, skin out = source thinner",
                    (c.x, mn2.y - 0.3, mn2.z - 0.12), size=0.045,
                    color=(0.95, 0.95, 0.98), face_deg=az)
        R.frame_camera(overlay, azimuth_deg=az, elevation_deg=6, zoom=0.98)
        R.render_to(R.OUT_DIR / f"morph_{target_key}_overlay_{name}.png")


if __name__ == "__main__":
    main()
