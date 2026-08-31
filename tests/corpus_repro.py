"""Opt-in real-corpus repro for card 1e252575-2b86-4ba5-89f7-bcf0ae9685ba
("Collision resolution leaves 50+ penetrating vertices on 9 of 22 real
garments (concave/strap regions)").

NOT part of the fast suite (``run_tests.py`` does not discover this --
matches ``tests/perf.py``'s pattern exactly) -- it depends on the real
avatar body + garment meshes under the gitignored ``Test_Items/``
directory (third-party creator assets that cannot be checked in), so it
will not run in an environment that doesn't have that folder populated
locally. Per ARCHITECTURE.md's Testing section standing rule ("every
quantitative claim ships with a checked-in script that reproduces it"),
this is that script for the card's before/after residual-penetration
table and for ARCHITECTURE.md section 7's "all nine previously-failing
garments dropped substantially" claim.

WHAT THIS REPRODUCES
---------------------
The card's own repro setup: the real avatar body (``Test_Items/Body``)
duplicated into a Source Body (all shape keys at Basis -- the pose the
garments were authored against) and a Target Body with ``Boobs+``,
``Butt +``, ``Hips +``, ``Thigh +`` all dialed to 1.0, all 22 named
garment meshes across the 9 real ``Test_Items/Clothing`` FBX files bound
in Mode A and fit onto the Target Body, collision resolution ON,
smoothing 0 (isolates the collision pass's own residual from any
smoothing interaction -- matches the card's own stated repro).

Residual penetration is measured with an independent ray-parity
(even/odd crossing count) inside/outside test -- NOT ``collision.py``'s
own nearest-point/normal-sign test -- matching the "independent parity
ray-cast test" method the card, Tester, and Reviewer all used for their
own measurements, so this script isn't just checking that the production
code agrees with itself.

Both the OLD (pre-fix) and NEW (this branch's) collision algorithm are
run in the SAME pass against the SAME projected ("raw") positions, so the
before/after comparison is a real A/B, not two separately-run
measurements. The OLD algorithm is reimplemented inline below from
``git diff origin/master...871d2bf -- sculpt_tool/core/collision.py``
(the fix's own diff): pre-fix, test (1)'s push-out direction was the
LOCAL nearest-hit triangle's own face normal, a single push with no
re-query/fallback loop; test (2), the anchor-based tunneling ray-cast, is
byte-for-byte unchanged by this card's fix (only test (1)'s push-out
direction/loop changed), so it is reused verbatim rather than duplicated.

Usage (from the repo root)::

    blender --background --factory-startup --python tests/corpus_repro.py

``Test_Items/`` is located automatically -- checked, in order: the
``SCULPT_TOOL_TEST_ITEMS`` environment variable (if set), ``<repo
root>/Test_Items``, then ``Test_Items`` next to the *main* git worktree
(useful when running from a linked worktree, like this card's own
``fix/concave-collision-residual`` branch, that doesn't have its own
copy of the gitignored assets). If none of those exist, the script exits
0 with a SKIPPED message rather than failing -- absence of local assets
is not a bug.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
for _path in (REPO_ROOT, TESTS_DIR):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

import common  # noqa: E402

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import collision, geometry, solver  # noqa: E402

BODY_FBX_NAME = "vrbase_Egirl_Heeled Foot.fbx"
BODY_OBJECT_NAME = "BODY"

# Card's own repro dial-in.
SHAPE_KEYS_DIALED = ("Boobs+", "Butt +", "Hips +", "Thigh +")

COLLISION_MARGIN = 0.01
OFFSET_SCALE = 1.0

# (fbx filename under Test_Items/Clothing, object name inside it, the
# card's display name, expected vertex count). Vertex counts are a
# sanity cross-check only, verified once against the real assets via a
# one-off inspection import -- if an asset changes these will visibly
# mismatch (a printed WARNING) and the run should be treated with
# suspicion rather than trusted blindly.
#
# The nine garments the card found leaving 50+ residual vertices:
FAILING_GARMENTS = [
    ("Cyber Bunny Outfit by Yukina - E-girl.fbx", "Bunny Suit", "Bunny Suit", 6935),
    ("Cyber Bunny Outfit by Yukina - E-girl.fbx", "Socks & Harness", "Socks & Harness", 13292),
    ("cybercroptopfinalizedUVedRigged.fbx", "Body", "cybercroptop Body", 5757),
    ("FBX-Tech Set by Vinuzhka.fbx", "pants by Vinuzhka", "pants by Vinuzhka", 18188),
    ("FBX-Tech Set by Vinuzhka.fbx", "Straps by Vinuzhka.001", "Straps by Vinuzhka", 9126),
    ("LingerieR.fbx", "Cube.012", "Cube.012 (Lingerie)", 49454),
    ("FBX-Tech Set by Vinuzhka.fbx", "Sweater by Vinuzhka", "Sweater", 10900),
    ("Zip Up.fbx", "Zip Up", "Zip Up", 5853),
    ("Cyber Bunny Outfit by Yukina - E-girl.fbx", "Hood Crop", "Hood Crop", 8276),
]

# The other 13 (of the card's full 22-mesh corpus) that were not on the
# failing-9 list above pre-fix -- NOT uniformly 0, despite an earlier
# version of ARCHITECTURE.md sect. 7 claiming so. A run against the real
# Test_Items/ corpus (see this card's write-up) saw old-algo-after
# residuals of: Body tape 0, tech Belt 0, panties 0, Summer Set 52,
# pasties 0, Legg Strap 0, Earrings 0, Top 0, bra 0, bodysuit 114,
# Tech Harness 8, Tech Pants 60, Tech top 28 -- only 8 of the 13 actually
# reached exactly 0, and 3 of the 5 nonzero ones (Summer Set, bodysuit,
# Tech Pants) are individually above the 50-vertex mark that separated
# this table from FAILING_GARMENTS in the first place. These numbers are
# illustrative only, from one run, and can drift if the corpus changes --
# re-run this script for the current, regenerable numbers (printed in
# the "old_after" column). Included as a no-regression check (new_after
# <= old_after for each), not part of the card's own failing-9 table.
CLEAN_GARMENTS = [
    ("E-girl.fbx", "Body tape.001", "Body tape", 580),
    ("E-girl.fbx", "tech Belt .001", "tech Belt", 2435),
    ("babydoll bra + panties.fbx", "panties", "panties", 1588),
    ("Summer SET.fbx", "Set", "Summer Set", 3571),
    ("FBX-Tech Set by Vinuzhka.fbx", "pasties by Vinuzhka", "pasties", 210),
    ("E-girl.fbx", "Legg Strap .001", "Legg Strap", 1380),
    ("E-girl.fbx", "Earrings .001", "Earrings", 928),
    ("FBX-Tech Set by Vinuzhka.fbx", "Top by Vinuzhka", "Top", 2347),
    ("babydoll bra + panties.fbx", "bra", "bra", 1428),
    ("bodysuit.fbx", "bodysuit by skulli", "bodysuit", 2087),
    ("E-girl.fbx", "Tech Harness .001", "Tech Harness", 4212),
    ("E-girl.fbx", "Tech Pants .001", "Tech Pants", 5874),
    ("E-girl.fbx", "Tech top .001", "Tech top", 1389),
]

GARMENTS = FAILING_GARMENTS + CLEAN_GARMENTS

# The two garments at the center of the Tester/Reviewer dispute over the
# card's rejection (see the card's agents.tester / agents.reviewer
# fields): Tester found these two roughly unchanged/worse under the fix,
# Reviewer's own independent re-measurement of the same two found both
# improved.
DISPUTED_NAMES = {"pants by Vinuzhka", "Cube.012 (Lingerie)"}

# Fixed, non-axis-aligned ray direction for the independent parity test
# (see module docstring) -- (1, 2, 3) normalized, chosen only to avoid
# accidentally lining up with any axis-aligned or mirror-symmetric
# feature of the body mesh.
_PARITY_DIRECTION = Vector((1.0, 2.0, 3.0)).normalized()


def _find_test_items():
    env = os.environ.get("SCULPT_TOOL_TEST_ITEMS")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(REPO_ROOT / "Test_Items")
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        common_dir = proc.stdout.strip()
        if common_dir:
            main_root = Path(common_dir).resolve().parent
            candidates.append(main_root / "Test_Items")
    except Exception:
        pass

    for candidate in candidates:
        if (candidate / "Body").is_dir() and (candidate / "Clothing").is_dir():
            return candidate
    return None


def _base_name(name):
    """Strip Blender's automatic ``.001``/``.002``/... disambiguation
    suffix, so a second import of an object named e.g. ``BODY`` (which
    Blender will call ``BODY.001``) still matches the object name as
    authored in the FBX file."""
    stem, sep, suffix = name.rpartition(".")
    if sep and suffix.isdigit():
        return stem
    return name


def _import_named_object(fbx_path, object_name):
    """Import ``fbx_path`` fresh and return the single object matching
    ``object_name`` (ignoring Blender's disambiguation suffix). Every
    other object the import brought in is removed immediately, so
    ``bpy.data`` doesn't accumulate the rest of that FBX's contents
    (rigs, accessories, other garments in the same file) across 22+
    imports."""
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(filepath=str(fbx_path))
    imported = [obj for obj in bpy.data.objects if obj.name not in before]

    # Match the exact authored name first -- some assets legitimately have
    # a literal ".001" etc. in their authored object name (e.g. "Straps by
    # Vinuzhka.001"), which is indistinguishable from Blender's own
    # disambiguation suffix by string shape alone. Only fall back to the
    # suffix-stripped comparison (for a second import of the same file,
    # where Blender appends its own real disambiguation suffix on top of
    # whatever the FBX already had) if no exact match exists.
    match = None
    for obj in imported:
        if obj.name == object_name:
            match = obj
            break
    if match is None:
        for obj in imported:
            if _base_name(obj.name) == object_name:
                match = obj
                break
    if match is None:
        raise RuntimeError(f"Object {object_name!r} not found in {fbx_path}")

    for obj in imported:
        if obj is not match:
            bpy.data.objects.remove(obj, do_unlink=True)

    return match


def _resolve_collisions_old(fitted_positions, anchor_positions, anchor_normals, bvh, collision_margin):
    """Pre-fix ``collision.resolve_collisions``, reimplemented inline from
    ``git diff origin/master...871d2bf -- sculpt_tool/core/collision.py``
    (this card's own fix commit). Test (1)'s push-out direction here is
    the LOCAL nearest-hit triangle's own face normal (``hit_normal``), a
    single push with no re-query/fallback loop -- exactly what
    ``collision.py`` did before this card. Test (2) (the anchor-based
    tunneling ray-cast) is untouched by the fix, so it's reused verbatim
    here rather than forked -- this card only changed test (1)'s
    push-out direction/loop.

    Takes a prebuilt ``bvh`` (rather than raw target geometry) since the
    caller already needs one BVH per target body for the parity count
    too, and the target body is the same object across every garment in
    this script's corpus.
    """
    resolved = []
    for co, anchor, anchor_normal in zip(fitted_positions, anchor_positions, anchor_normals):
        hit_location, hit_normal, hit_tri_index, _hit_distance = bvh.find_nearest(co)
        if hit_tri_index is None:
            resolved.append(co)
            continue

        is_inside = (co - hit_location).dot(hit_normal) < 0.0
        if is_inside:
            normal = hit_normal.normalized()
            resolved.append(hit_location + normal * collision_margin)
            continue

        to_fitted = co - anchor
        distance = to_fitted.length
        if distance <= collision._MIN_TUNNEL_TEST_DISTANCE:
            resolved.append(co)
            continue

        direction = to_fitted / distance
        normal_at_anchor = anchor_normal.normalized()
        epsilon = min(distance * 1e-6, 1e-6)
        origin = anchor + direction * epsilon
        remaining_distance = distance - epsilon

        _tunnel_hit_location, _tunnel_hit_normal, tunnel_hit_index, _tunnel_hit_distance = (
            bvh.ray_cast(origin, direction, remaining_distance)
        )
        if tunnel_hit_index is None:
            resolved.append(co)
            continue

        resolved.append(anchor + normal_at_anchor * collision_margin)

    return resolved


def _parity_inside(point, direction, bvh, max_hits=64):
    """Independent inside/outside test via ray parity (the even/odd
    crossing rule): count how many times a ray from ``point`` along
    ``direction`` crosses the target body's surface before it leaves the
    BVH entirely; an odd count means ``point`` started inside. Uses
    ``BVHTree.ray_cast`` (a pure geometric raycast), NOT
    ``collision.py``'s own nearest-point/normal-sign test -- see module
    docstring."""
    direction = direction.normalized()
    origin = point
    hits = 0
    for _ in range(max_hits):
        hit_location, _hit_normal, hit_index, _hit_distance = bvh.ray_cast(origin, direction)
        if hit_index is None:
            break
        hits += 1
        origin = hit_location + direction * 1e-6
    return hits % 2 == 1


def _count_penetrating(positions, bvh, direction=_PARITY_DIRECTION):
    return sum(1 for p in positions if _parity_inside(p, direction, bvh))


def _fmt(n):
    return f"{n:,}"


def main():
    test_items = _find_test_items()
    if test_items is None:
        print(
            "SKIPPED: Test_Items/ not found locally (checked "
            "$SCULPT_TOOL_TEST_ITEMS, "
            f"{REPO_ROOT / 'Test_Items'}, and the main git worktree's "
            "Test_Items/). This script is opt-in and requires the real "
            "(gitignored) asset corpus -- see the module docstring."
        )
        return 0

    was_registered = hasattr(bpy.types.Object, "sculpt_tool")
    if not was_registered:
        sculpt_tool.register()

    try:
        common.clear_scene()

        body_path = test_items / "Body" / BODY_FBX_NAME
        clothing_dir = test_items / "Clothing"

        source_body = _import_named_object(body_path, BODY_OBJECT_NAME)
        source_body.name = "SourceBody"

        target_body = _import_named_object(body_path, BODY_OBJECT_NAME)
        target_body.name = "TargetBody"
        key_blocks = target_body.data.shape_keys.key_blocks
        for key_name in SHAPE_KEYS_DIALED:
            key_blocks[key_name].value = 1.0
        common.update_scene()

        depsgraph = bpy.context.evaluated_depsgraph_get()
        target_ctx = geometry.TargetContext.build(target_body, depsgraph)
        target_bvh = target_ctx.bvh

        rows = []
        for fbx_name, object_name, display_name, expected_verts in GARMENTS:
            fbx_path = clothing_dir / fbx_name
            garment = _import_named_object(fbx_path, object_name)
            garment.name = f"Garment_{display_name}"

            vertex_count = len(garment.data.vertices)
            if vertex_count != expected_verts:
                print(
                    f"WARNING: {display_name!r} has {vertex_count} vertices, "
                    f"expected {expected_verts} -- Test_Items/ asset may have "
                    "changed; treat this run with suspicion."
                )

            garment.sculpt_tool.source_body = source_body
            garment.sculpt_tool.target_body = target_body
            garment.sculpt_tool.bind_mode_override = 'MODE_A'

            bpy.context.view_layer.objects.active = garment
            garment.select_set(True)

            bind_result = bpy.ops.sculpttool.bind_garment()
            if bind_result != {'FINISHED'}:
                raise RuntimeError(f"bind failed for {display_name}: {bind_result}")

            projection = solver.project_garment(garment, target_ctx, OFFSET_SCALE)
            raw_positions = projection.fitted_positions

            before_count = _count_penetrating(raw_positions, target_bvh)

            old_resolved = _resolve_collisions_old(
                raw_positions,
                projection.anchor_positions,
                projection.anchor_normals,
                target_bvh,
                COLLISION_MARGIN,
            )
            old_after_count = _count_penetrating(old_resolved, target_bvh)

            new_resolved = collision.resolve_collisions(
                raw_positions,
                projection.anchor_positions,
                projection.anchor_normals,
                target_bvh,
                COLLISION_MARGIN,
            )
            new_after_count = _count_penetrating(new_resolved, target_bvh)

            rows.append(
                {
                    "name": display_name,
                    "verts": vertex_count,
                    "before": before_count,
                    "old_after": old_after_count,
                    "new_after": new_after_count,
                    "failing": display_name in {g[2] for g in FAILING_GARMENTS},
                }
            )

            bpy.data.objects.remove(garment, do_unlink=True)
            bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

        # --- Report ------------------------------------------------------
        print()
        print("=" * 100)
        print(
            "Real-corpus collision residual repro -- card 1e252575-2b86-4ba5-89f7-bcf0ae9685ba"
        )
        print(
            "Setup: Boobs+/Butt +/Hips +/Thigh + = 1.0 target body, Mode A bind, "
            "collision ON, smoothing 0."
        )
        print(
            "Residual = independent ray-parity inside/outside count (NOT collision.py's own test)."
        )
        print("=" * 100)
        header = (
            f"{'Garment':<24}{'Verts':>10}{'Before':>10}{'Old-Algo After':>18}"
            f"{'New-Algo After':>18}{'Old %':>9}{'New %':>9}"
        )
        print(header)
        print("-" * len(header))

        def _pct(after, before):
            if before == 0:
                return 0.0
            return 100.0 * after / before

        failing_totals = {"before": 0, "old_after": 0, "new_after": 0}
        clean_totals = {"before": 0, "old_after": 0, "new_after": 0}

        print("-- Previously-failing (9, per the card's original table) --")
        for row in rows:
            if not row["failing"]:
                continue
            for key in failing_totals:
                failing_totals[key] += row[key]
            print(
                f"{row['name']:<24}{_fmt(row['verts']):>10}{_fmt(row['before']):>10}"
                f"{_fmt(row['old_after']):>18}{_fmt(row['new_after']):>18}"
                f"{_pct(row['old_after'], row['before']):>8.1f}%"
                f"{_pct(row['new_after'], row['before']):>8.1f}%"
            )
        print(
            f"{'TOTAL (9 failing)':<24}{'':>10}{_fmt(failing_totals['before']):>10}"
            f"{_fmt(failing_totals['old_after']):>18}{_fmt(failing_totals['new_after']):>18}"
            f"{_pct(failing_totals['old_after'], failing_totals['before']):>8.1f}%"
            f"{_pct(failing_totals['new_after'], failing_totals['before']):>8.1f}%"
        )

        print()
        print("-- Previously-clean (13) -- no-regression check --")
        for row in rows:
            if row["failing"]:
                continue
            for key in clean_totals:
                clean_totals[key] += row[key]
            print(
                f"{row['name']:<24}{_fmt(row['verts']):>10}{_fmt(row['before']):>10}"
                f"{_fmt(row['old_after']):>18}{_fmt(row['new_after']):>18}"
                f"{_pct(row['old_after'], row['before']):>8.1f}%"
                f"{_pct(row['new_after'], row['before']):>8.1f}%"
            )
        print(
            f"{'TOTAL (13 clean)':<24}{'':>10}{_fmt(clean_totals['before']):>10}"
            f"{_fmt(clean_totals['old_after']):>18}{_fmt(clean_totals['new_after']):>18}"
            f"{_pct(clean_totals['old_after'], clean_totals['before']):>8.1f}%"
            f"{_pct(clean_totals['new_after'], clean_totals['before']):>8.1f}%"
        )

        print()
        print("-" * 100)
        print("DISPUTED GARMENTS (Tester vs. Reviewer on the previous review pass):")
        ok = True
        for row in rows:
            if row["name"] not in DISPUTED_NAMES:
                continue
            delta = row["new_after"] - row["old_after"]
            direction = "IMPROVED" if delta < 0 else ("REGRESSED" if delta > 0 else "UNCHANGED")
            pct_change = (
                100.0 * delta / row["old_after"] if row["old_after"] else 0.0
            )
            print(
                f"  {row['name']}: old-algo after={row['old_after']}, "
                f"new-algo after={row['new_after']} ({direction}, {pct_change:+.1f}%)"
            )
            if direction == "REGRESSED":
                ok = False

        print("-" * 100)

        no_regression = True
        for row in rows:
            if not row["failing"] and row["new_after"] > row["old_after"]:
                no_regression = False
                print(
                    f"REGRESSION on previously-clean garment {row['name']!r}: "
                    f"old-algo after={row['old_after']}, new-algo after={row['new_after']}"
                )

        if not no_regression:
            ok = False

        if ok:
            print("OK: no regression detected on previously-clean garments; see disputed-garment section above.")
        return 0 if ok else 1
    finally:
        if not was_registered:
            sculpt_tool.unregister()


if __name__ == "__main__":
    sys.exit(main())
