"""Opt-in perf sanity check at the scale ARCHITECTURE.md section 7 cites
(~33k-vertex garment, ~65k-triangle target body).

NOT part of the fast suite (``run_tests.py`` does not discover this --
its assertions here are generous/sanity-only, not tight regression
gates, and the meshes are big enough that this alone can take a while).
Run it explicitly when re-validating a performance claim before it goes
into ARCHITECTURE.md (the Testing section's standing rule: no
quantitative claim without a checked-in script that reproduces it) --
this is that script for section 7's collision/smoothing timing figures.

Usage (from the repo root)::

    blender --background --factory-startup --python tests/perf.py
"""

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
for path in (REPO_ROOT, TESTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import common  # noqa: E402

from sculpt_tool.core import binding, collision, smoothing  # noqa: E402

# ~33k vertices, matching the smoothing entry's own repro scale.
GARMENT_SEGMENTS = 150
GARMENT_RINGS = 220  # 150 * 220 = 33,000 vertices

# ~65k triangles, matching the collision entry's own repro scale.
BODY_X_SEGMENTS = 180
BODY_Y_SEGMENTS = 181  # 180*181 = 32,580 quads = 65,160 triangles

SMOOTHING_ITERATIONS = 10
COLLISION_MARGIN = 0.01

# Generous ceilings -- this is a sanity check that the pipeline hasn't
# regressed by an order of magnitude, not a tight perf assertion (see
# module docstring: real numbers vary by machine).
COLLISION_CEILING_SECONDS = 10.0
SMOOTHING_CEILING_SECONDS = 60.0


def main():
    common.clear_scene()

    print(f"Building garment tube: {GARMENT_SEGMENTS} segments x {GARMENT_RINGS} rings "
          f"({GARMENT_SEGMENTS * GARMENT_RINGS} vertices)...")
    garment = common.make_tube(
        "PerfGarment",
        segments=GARMENT_SEGMENTS,
        rings=GARMENT_RINGS,
        radius=1.0,
        height=2.0,
    )
    garment_positions = common.world_positions(garment)
    vertex_count = len(garment_positions)
    print(f"  {vertex_count} vertices.")

    print(f"Building target body grid: {BODY_X_SEGMENTS}x{BODY_Y_SEGMENTS} segments...")
    body = common.make_grid(
        "PerfBody", x_segments=BODY_X_SEGMENTS, y_segments=BODY_Y_SEGMENTS, size=4.0
    )
    body.location = (0.0, 0.0, -3.0)  # keep it clear of the garment tube
    target_positions, target_triangles = binding._world_space_triangles(body)
    print(f"  {len(target_positions)} vertices, {len(target_triangles)} triangles.")

    # Anchors coincide with the fitted positions -- this benchmark is
    # about raw per-vertex query cost, not a realistic tunneling
    # scenario (see tests/test_collision.py for correctness coverage).
    anchor_positions = list(garment_positions)
    anchor_normals = [pos.normalized() for pos in garment_positions]

    start = time.perf_counter()
    resolved = collision.resolve_collisions(
        garment_positions,
        anchor_positions,
        anchor_normals,
        target_positions,
        target_triangles,
        COLLISION_MARGIN,
    )
    collision_elapsed = time.perf_counter() - start
    print(f"resolve_collisions: {collision_elapsed:.2f}s for {vertex_count} vertices "
          f"against {len(target_triangles)} triangles.")

    start = time.perf_counter()
    smoothing.relax(garment, resolved, pin_weights=None, iterations=SMOOTHING_ITERATIONS)
    smoothing_elapsed = time.perf_counter() - start
    print(f"relax (iterations={SMOOTHING_ITERATIONS}): {smoothing_elapsed:.2f}s "
          f"for {vertex_count} vertices.")

    ok = True
    if collision_elapsed > COLLISION_CEILING_SECONDS:
        print(f"FAIL: collision took {collision_elapsed:.2f}s > "
              f"{COLLISION_CEILING_SECONDS}s ceiling.")
        ok = False
    if smoothing_elapsed > SMOOTHING_CEILING_SECONDS:
        print(f"FAIL: smoothing took {smoothing_elapsed:.2f}s > "
              f"{SMOOTHING_CEILING_SECONDS}s ceiling.")
        ok = False

    if ok:
        print("OK: both passes within generous sanity ceilings.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
