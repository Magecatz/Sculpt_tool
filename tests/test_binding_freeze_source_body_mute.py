"""Tester-added regression test for the bind-time-freeze card (Part B).

``tests/test_binding_freeze.py`` (the Developer's own new test file)
covers Part B's "no output of this add-on may ever be an input to it"
rule only for the GARMENT side: every ``BindFitBindBitIdenticalTest``
case bakes the 'Fitted' key onto the garment being re-bound, never onto
the SOURCE BODY of a *different* bind.

But ``operators/op_bind.py``'s ``_bind_time_evaluation`` context manager
explicitly mutes the 'Fitted' key block on BOTH objects passed to it
(garment and source body alike) -- see its own docstring: "The same
failure mode applies, less commonly, to a source body that was itself
fit as some other garment's target -- hence muting on every object
passed in, not just the garment." That source-body branch has no test
exercising it anywhere in the new suite: every scenario's source body is
a plain, never-fitted grid with no 'Fitted' key block to mute at all, so
a test suite run with that branch deleted (i.e. muting only ``garment_
obj``, dropping ``source_body_obj`` from the ``_bind_time_evaluation``
call) would still pass 41/41.

This test manually bakes a 'Fitted' key onto a would-be source body
(bypassing the Fit operator entirely, so it exercises exactly the "any
pre-existing 'Fitted' key block" case _bind_time_evaluation actually
guards, not just the one Fit happens to produce), then binds a garment
against it and confirms the stored bind-time anchor reflects the source
body's ORIGINAL (Basis) authored geometry -- not the live evaluated
mesh a non-muted read would have picked up. It fails against the
pre-Part-B behavior (no muting at all) and would also fail if
``_bind_time_evaluation`` were narrowed to the garment only.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

import bpy  # noqa: E402

import sculpt_tool  # noqa: E402
from sculpt_tool.core import binding, storage  # noqa: E402


class SourceBodyOwnFittedKeyIsMutedAtBindTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._was_registered = hasattr(bpy.types.Object, "sculpt_tool")
        if not cls._was_registered:
            sculpt_tool.register()

    @classmethod
    def tearDownClass(cls):
        if not cls._was_registered:
            sculpt_tool.unregister()

    def setUp(self):
        common.clear_scene()

    def test_binding_against_a_source_body_with_its_own_fitted_key_uses_basis(self):
        source_body = common.make_grid(
            "SourceBody", x_segments=4, y_segments=4, size=2.0
        )

        # Manually bake a 'Fitted' key onto the would-be source body that
        # displaces it well away from its authored (Basis) shape -- as if
        # this object had itself previously been fit as some other
        # garment's target. Bypasses operators/op_fit.py entirely so this
        # exercises _bind_time_evaluation's general "any pre-existing
        # 'Fitted' key block" guard, not just Fit's own output shape.
        mesh = source_body.data
        original_coords = [tuple(v.co) for v in mesh.vertices]
        source_body.shape_key_add(name="Basis", from_mix=False)
        fitted_key = source_body.shape_key_add(
            name=storage.FITTED_SHAPE_KEY_NAME, from_mix=False
        )
        displaced = [(x, y, z + 0.75) for (x, y, z) in original_coords]
        fitted_key.data.foreach_set(
            "co", [c for co in displaced for c in co]
        )
        fitted_key.value = 1.0
        mesh.update()
        common.update_scene()

        # Sanity: the evaluated mesh really is displaced now (otherwise
        # this test would prove nothing).
        depsgraph = bpy.context.evaluated_depsgraph_get()
        from sculpt_tool.core import geometry

        live_positions, _ = geometry.world_space_positions_and_normals(
            source_body, depsgraph
        )
        self.assertGreater(
            common.max_component_diff(
                live_positions, [common.Vector(c) for c in original_coords]
            ),
            0.1,
            "test setup did not actually displace the source body's evaluated mesh",
        )

        garment = common.make_grid("Garment", x_segments=6, y_segments=6, size=1.2)
        garment.location = (0.0, 0.0, 0.4)

        settings = garment.sculpt_tool
        settings.source_body = source_body
        settings.bind_mode_override = 'MODE_B'  # bypass detect_bind_mode; no target needed to bind

        bpy.context.view_layer.objects.active = garment
        garment.select_set(True)

        self.assertEqual(bpy.ops.sculpttool.bind_garment(), {'FINISHED'})
        protected = storage.read_mode_b_binding(garment)

        # By now the operator has restored the source body's 'Fitted' key
        # to unmuted (see _bind_time_evaluation's docstring). Calling
        # core.binding.bind_mode_b directly, with no muting at all,
        # reproduces exactly what the OLD (pre-Part-B) bind path would
        # have computed: the anchor derived from the source body's live,
        # 'Fitted'-contaminated evaluated mesh.
        depsgraph = bpy.context.evaluated_depsgraph_get()
        contaminated = binding.bind_mode_b(garment, source_body, depsgraph)

        diff = common.max_component_diff(
            protected["source_anchor_local"], contaminated.source_anchor_local
        )
        self.assertGreater(
            diff,
            0.1,
            "bind_garment's stored anchor matches an unmuted (Fitted-"
            "contaminated) read of the source body -- the source body's "
            "own 'Fitted' key does not appear to have been muted during "
            "bind, only the garment's (or neither's)",
        )


if __name__ == "__main__":
    unittest.main()
