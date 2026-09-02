"""Core logic package for Sculpt Tool.

Each module here is pure logic operating on mesh data (testable outside
the UI) per ARCHITECTURE.md section 5. None of these resolve Blender's own
current UI context — a resolved depsgraph is always passed in by the
operator layer instead (see geometry.py's module docstring).

Conform-rebuild restart (RESTART_SCOPE.md): the surface-conform modules
(binding.py, solver.py, collision.py, pipeline.py) were removed with the
rest of the target-anchored conform stage. What remains is the placement
spine and its substrate:

- ``rig.py`` / ``rig_map.py`` / ``pose.py`` — rig awareness, canonical bone
  map, and per-bone placement (position + rotation + scale).
- ``geometry.py`` — shared mesh primitives + ``TargetContext``.
- ``smoothing.py`` — pin-weighted relaxation (to be repurposed as the
  elastic-conform engine).
- ``alignment.py`` — the gross mismatch guard (kept; re-wired later).
- ``storage.py`` / ``quality.py`` — persisted metadata and acceptance
  metrics.

Some kept modules' docstrings still narrate the old bind→project→collision→
smooth pipeline; those are updated as the new conform lands.
"""
