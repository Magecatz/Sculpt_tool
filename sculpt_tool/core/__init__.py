"""Core solver package for Sculpt Tool.

Each module here is pure logic operating on mesh data (testable outside
the UI) per ARCHITECTURE.md section 5: geometry.py (shared primitives +
TargetContext), binding.py, solver.py, collision.py, smoothing.py,
pipeline.py (fit_once, the full per-target pipeline), storage.py. None of
these resolve Blender's own current UI context — a resolved depsgraph is
always passed in by the operator layer instead (see geometry.py's module
docstring).
"""
