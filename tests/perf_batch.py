"""Opt-in per-stage, per-target Batch Fit timing, at TWO scales: the
established stress-test scale ``tests/perf.py`` already uses (~33k-vertex
garment / ~65k-triangle target body, matching ARCHITECTURE.md section 7's
collision/smoothing repro), and a smaller "realistic garment" scale
(~2,000 garment vertices, matching this project's own real Test_Items
corpus citation -- see e.g. ``core/geometry.py``'s
``world_space_positions_and_normals`` docstring, "2,087 vertices") with a
proportionally smaller target body.

NOT part of the fast suite (``run_tests.py`` does not discover this),
matching ``tests/perf.py``'s own convention -- run explicitly:

    blender --background --factory-startup --python tests/perf_batch.py

Measures project / collision / smooth / bake as four separate stages
(the collision stage total includes BOTH collision passes when smoothing
is enabled, matching ``core.pipeline.fit_once``'s own "second pass after
smoothing" step -- see that module's docstring) for a fixed number of
targets, at ``smoothing_iterations`` 0 and 10, then extrapolates a
100-target batch-run total from the measured per-target averages, at
each scale. This is the checked-in script backing the Batch/automated-
fitting Bear PR Process card's PR write-up (its 100-target projection and
the trigger-check conclusion for Backlog card
5b232224-901f-4c7a-a991-42cb29b5627d), per ARCHITECTURE.md section 9's
standing rule that no quantitative claim gets added to project
documentation without a reproducible script behind it.

This script measures each pipeline STAGE directly via ``core/`` calls
(not through ``operators/op_batch.py``'s ``bpy.ops`` layer, to keep
per-stage boundaries precise) but mirrors ``core.pipeline.fit_once`` and
``operators/op_batch.py``'s own call sequence exactly, including reusing
one ``core.smoothing.RelaxContext`` across every target (the batch
operator's own structural optimization -- see ``operators/op_batch.py``'s
docstring) and one ``core.geometry.TargetContext`` per target (built
fresh every target, exactly as ``fit_once`` does).
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

import bpy  # noqa: E402

from sculpt_tool.core import binding, collision, geometry, smoothing, solver, storage  # noqa: E402

# (label, garment_segments, garment_rings, body_x_segments, body_y_segments)
# "stress" matches tests/perf.py exactly (see that module's own comments
# for the vertex/triangle-count derivation). "realistic" targets roughly
# this project's own cited real-garment vertex count (~2,087, the
# Test_Items bodysuit named in several core/ docstrings) with a
# proportionally smaller target body.
SCALES = (
    ("stress (perf.py scale)", 150, 220, 180, 181),
    ("realistic (~2k-vertex garment)", 40, 50, 90, 91),
)

COLLISION_MARGIN = 0.01
N_TARGETS = 3  # per-target timings averaged over this many targets
PROJECTED_BATCH_SIZE = 100


def _build_target_body(name, x_segments, y_segments, z_offset):
    """A same-topology "shape variant" target body: a fresh grid, same
    segment counts as the source body (Mode A requires matching vertex
    count), offset in Z so it's a genuinely different shape per target,
    matching how a body-shape-library batch collection would look."""
    body = common.make_grid(name, x_segments=x_segments, y_segments=y_segments, size=4.0)
    body.location = (0.0, 0.0, -3.0 + z_offset)
    return body


def _time_one_target(garment, target_body, depsgraph, relax_ctx, smoothing_iterations):
    """Run project -> collision -> smooth -> (collision again if smoothing
    ran) -> bake against ONE target, timing each stage. Mirrors
    core.pipeline.fit_once's exact sequence and operators/op_batch.py's
    bake step, with explicit timing checkpoints fit_once itself doesn't
    expose."""
    stage_times = {}

    t0 = time.perf_counter()
    # TargetContext.build's eager positions/normals cost is charged to
    # "project" -- it's a per-target cost incurred exactly where
    # fit_once/op_batch.py incur it, on the first thing that needs the
    # target body at all.
    target_ctx = geometry.TargetContext.build(target_body, depsgraph)
    projection = solver.project_garment(garment, target_ctx, offset_scale=1.0)
    stage_times["project"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    fitted = collision.resolve_collisions(
        projection.fitted_positions,
        projection.anchor_positions,
        projection.anchor_normals,
        target_ctx.bvh,
        COLLISION_MARGIN,
    )
    stage_times["collision"] = time.perf_counter() - t0

    stage_times["smooth"] = 0.0
    if smoothing_iterations > 0:
        t0 = time.perf_counter()
        fitted = smoothing.relax_positions(
            fitted,
            relax_ctx.neighbors,
            relax_ctx.original_edges,
            relax_ctx.pin_weights,
            smoothing_iterations,
        )
        stage_times["smooth"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        fitted = collision.resolve_collisions(
            fitted,
            projection.anchor_positions,
            projection.anchor_normals,
            target_ctx.bvh,
            COLLISION_MARGIN,
        )
        stage_times["collision"] += time.perf_counter() - t0

    t0 = time.perf_counter()
    matrix_inverse = garment.matrix_world.inverted_safe()
    fitted_local = [matrix_inverse @ co for co in fitted]
    mesh = garment.data
    key_name = f"Fitted_{target_body.name}"
    key_block = mesh.shape_keys.key_blocks.get(key_name)
    if key_block is None:
        key_block = garment.shape_key_add(name=key_name, from_mix=False)
    flat_coords = [component for co in fitted_local for component in co]
    key_block.data.foreach_set("co", flat_coords)
    stage_times["bake"] = time.perf_counter() - t0

    return stage_times


def _run_at(garment, targets, depsgraph, smoothing_iterations):
    relax_ctx = None
    if smoothing_iterations > 0:
        t0 = time.perf_counter()
        relax_ctx = smoothing.RelaxContext.build(garment)
        relax_ctx_build_time = time.perf_counter() - t0
    else:
        relax_ctx_build_time = 0.0

    per_target = []
    for target in targets:
        per_target.append(
            _time_one_target(garment, target, depsgraph, relax_ctx, smoothing_iterations)
        )

    return per_target, relax_ctx_build_time


def _print_table(smoothing_iterations, per_target, relax_ctx_build_time):
    print(f"\n--- smoothing_iterations={smoothing_iterations} "
          f"({len(per_target)} targets) ---")
    print("target  project  collision  smooth   bake     total")
    totals = []
    for i, stages in enumerate(per_target):
        total = sum(stages.values())
        totals.append(total)
        print(
            f"{i:>6}  {stages['project']:7.3f}  {stages['collision']:9.3f}  "
            f"{stages['smooth']:7.3f}  {stages['bake']:7.3f}  {total:6.3f}"
        )

    avg_total = sum(totals) / len(totals)
    avg_project = sum(s["project"] for s in per_target) / len(per_target)
    avg_collision = sum(s["collision"] for s in per_target) / len(per_target)
    avg_smooth = sum(s["smooth"] for s in per_target) / len(per_target)
    avg_bake = sum(s["bake"] for s in per_target) / len(per_target)
    print(
        f"{'avg':>6}  {avg_project:7.3f}  {avg_collision:9.3f}  "
        f"{avg_smooth:7.3f}  {avg_bake:7.3f}  {avg_total:6.3f}"
    )
    if smoothing_iterations > 0:
        print(f"RelaxContext.build (once per batch run, not per target): "
              f"{relax_ctx_build_time:.3f}s")

    projected_total = avg_total * PROJECTED_BATCH_SIZE + relax_ctx_build_time
    print(
        f"Projected {PROJECTED_BATCH_SIZE}-target batch total at "
        f"smoothing_iterations={smoothing_iterations}: {projected_total:.1f}s "
        f"({projected_total / 60.0:.1f} min)"
    )
    return avg_total, projected_total


def _run_scale(label, garment_segments, garment_rings, body_x, body_y):
    print(f"\n===== Scale: {label} =====")
    common.clear_scene()

    print(f"Building garment tube: {garment_segments} segments x {garment_rings} rings...")
    garment = common.make_tube(
        "PerfGarment", segments=garment_segments, rings=garment_rings, radius=1.0, height=2.0,
    )
    print(f"  {len(garment.data.vertices)} vertices.")

    print(f"Building source body grid: {body_x}x{body_y} segments...")
    source_body = common.make_grid("PerfSourceBody", x_segments=body_x, y_segments=body_y, size=4.0)
    source_body.location = (0.0, 0.0, -3.0)
    print(f"  {len(source_body.data.vertices)} vertices, "
          f"{2 * body_x * body_y} triangles.")

    depsgraph = bpy.context.evaluated_depsgraph_get()

    print("Binding garment to source body (Mode A)...")
    t0 = time.perf_counter()
    result = binding.bind_mode_a(garment, source_body, depsgraph)
    storage.write_mode_a_binding(garment, source_body, result)
    print(f"  bind_mode_a: {time.perf_counter() - t0:.3f}s")

    garment.shape_key_add(name="Basis", from_mix=False)

    print(f"Building {N_TARGETS} same-topology target bodies...")
    targets = [
        _build_target_body(f"PerfTarget{i}", body_x, body_y, z_offset=0.05 * i)
        for i in range(N_TARGETS)
    ]

    results = {}
    for smoothing_iterations in (0, 10):
        per_target, relax_build_time = _run_at(garment, targets, depsgraph, smoothing_iterations)
        avg_total, projected_total = _print_table(
            smoothing_iterations, per_target, relax_build_time
        )
        results[smoothing_iterations] = (avg_total, projected_total)

    return results


def main():
    all_results = {}
    for label, garment_segments, garment_rings, body_x, body_y in SCALES:
        all_results[label] = _run_scale(label, garment_segments, garment_rings, body_x, body_y)

    print("\n=== Summary (all scales) ===")
    for label, results in all_results.items():
        for smoothing_iterations, (avg_total, projected_total) in results.items():
            print(
                f"[{label}] smoothing_iterations={smoothing_iterations}: "
                f"avg {avg_total:.3f}s/target -> projected {PROJECTED_BATCH_SIZE}-target "
                f"total {projected_total:.1f}s ({projected_total / 60.0:.1f} min)"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
