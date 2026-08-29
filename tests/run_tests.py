"""Headless Blender test runner -- THE suite every Tester should run.

Usage (from the repo root)::

    blender --background --factory-startup --python tests/run_tests.py

Discovers and runs every ``tests/test_*.py`` module (stdlib ``unittest``,
not pytest -- pytest isn't vendored into Blender's bundled Python and
this avoids needing to) and exits non-zero if anything failed or errored,
so it's a real pass/fail gate, not just a script that prints output.

See ARCHITECTURE.md's Testing section for the standing rule this
enforces: every quantitative claim added to the docs ships with a
checked-in script (i.e. a test in here) that reproduces it.

``tests/perf.py`` (33k-vertex-scale timing scenarios) is intentionally
NOT discovered here -- it's opt-in only, run separately:

    blender --background --factory-startup --python tests/perf.py
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent

for path in (REPO_ROOT, TESTS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def main():
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(TESTS_DIR),
        pattern="test_*.py",
        top_level_dir=str(TESTS_DIR),
    )
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
