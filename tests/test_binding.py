"""Tests for ``core/binding.py``.

Includes the Mode B reconstruction round-trip: ``core.binding.
reconstruct_mode_b_position`` used to live in ``core/binding.py`` but was
dead in production (referenced only from a docstring -- ``core.solver.
project_mode_b`` re-derives against a *different*, target body instead of
reconstructing the bind-time source position). It's moved here as
``_reconstruct_mode_b_position`` because verifying the round-trip is
exactly what it was for.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

from sculpt_tool.core import binding  # noqa: E402


def _reconstruct_mode_b_position(body_obj, triangle_index, barycentric, normal_offset, tangent_offset_2d):
    """Reconstruct a garment vertex's world position from a Mode B binding
    entry against ``body_obj`` -- exact (to floating point) when
    ``body_obj`` is the same body the binding was computed against, per
    ``core.binding.bind_mode_b``'s docstring.
    """
    body_positions, body_triangles = binding._world_space_triangles(body_obj)
    tri = body_triangles[triangle_index]
    a, b, c = body_positions[tri[0]], body_positions[tri[1]], body_positions[tri[2]]
    normal, tangent, bitangent = binding._triangle_frame(a, b, c)

    u, v, w = barycentric
    hit_location = a * u + b * v + c * w

    tangent_u, tangent_v = tangent_offset_2d
    return hit_location + normal * normal_offset + tangent * tangent_u + bitangent * tangent_v


class ModeBReconstructRoundTripTest(unittest.TestCase):
    def setUp(self):
        common.clear_scene()

    def test_round_trip_to_1e_minus_6(self):
        source_body = common.make_grid("SourceBody", x_segments=8, y_segments=8, size=2.0)
        # Perturb Z so the surface has real curvature/non-planar normals,
        # not a degenerate flat plane.
        import math

        for v in source_body.data.vertices:
            v.co.z = 0.15 * math.sin(v.co.x * 2.0) * math.cos(v.co.y * 2.0)
        source_body.data.update()

        garment = common.make_grid("Garment", x_segments=5, y_segments=5, size=1.4)
        garment.location = (0.0, 0.0, 0.4)  # offset above the body's surface

        original_positions = common.world_positions(garment)

        result = binding.bind_mode_b(garment, source_body)

        worst = 0.0
        for i, original in enumerate(original_positions):
            reconstructed = _reconstruct_mode_b_position(
                source_body,
                result.triangle_index[i],
                result.barycentric[i],
                result.normal_offset[i],
                result.tangent_offset_2d[i],
            )
            diff = (reconstructed - original).length
            worst = max(worst, diff)

        self.assertLess(
            worst,
            1e-6,
            f"Mode B reconstruction round-trip drifted by up to {worst} "
            "(expected < 1e-6)",
        )


if __name__ == "__main__":
    unittest.main()
