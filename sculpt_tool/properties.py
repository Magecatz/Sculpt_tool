"""Per-object Sculpt Tool settings.

Per ARCHITECTURE.md sections 4 and 6: a PropertyGroup attached to the
garment Object so settings travel with the object, not just the scene.

Source/target body pointers, the bind-mode override (section 6 — lets a
user force Mode A or B when the auto-detect heuristic's vertex-count
coincidence would misclassify; see ``core.binding.detect_bind_mode``),
the offset/thickness-scale fit parameter (section 6 — a global
multiplier on the stored binding offset, applied by
``core.solver.project_garment`` / ``operators/op_fit.py``, letting a
user tighten/loosen the fit without re-binding), and the collision
parameters (section 3 step 2 / section 6 — ``use_collision_resolution``
toggles ``core.collision.resolve_collisions`` on/off for
``operators/op_fit.py``'s pipeline, ``collision_margin`` is the minimum
garment-to-body clearance that pass enforces), and the smoothing
parameter (section 3 step 3 / section 6 — ``smoothing_iterations`` is
the iteration count for ``core.smoothing.relax``'s pin-weighted
relaxation pass; ``0`` disables the pass entirely, and
``operators/op_fit.py`` treats that as a true no-op rather than calling
into ``core.smoothing`` at all). A later card adds pin vertex-group
references, and a still-later card (this one) adds
``batch_target_collection`` -- the Collection of target body objects
``operators/op_batch.py``'s ``OT_batch_fit`` iterates, one
``core.pipeline.fit_once`` call per member object, reusing every other
setting above (offset scale, collision toggle/margin, smoothing
iterations) unchanged per target.
"""

import bpy


def _is_armature(self, obj):
    """PointerProperty poll: restrict a rig picker to Armature objects.

    Used by ``source_base_armature``/``target_base_armature`` below so the
    UI's rig dropdowns only offer Armature objects, not every object in the
    scene (roadmap R1 -- the "base" concept's source/target rig pickers).
    """
    return obj.type == 'ARMATURE'


BIND_MODE_OVERRIDE_ITEMS = (
    ('AUTO', "Auto-Detect", "Choose Mode A or B automatically based on source/target body topology"),
    ('MODE_A', "Force Mode A", "Force same-topology (vertex-index) binding regardless of auto-detection"),
    ('MODE_B', "Force Mode B", "Force cross-topology (BVH nearest-surface) binding regardless of auto-detection"),
)


class SCULPTTOOL_PG_bone_override(bpy.types.PropertyGroup):
    """One manual bone-map override row (roadmap R2).

    Lets a user force a garment-rig bone to pair with a specific
    target-base-rig bone, or -- with an empty ``target_bone`` -- explicitly
    leave the source bone unmapped, correcting or supplementing
    ``core.rig_map.build_bone_map``'s auto-resolution. Stored as a
    CollectionProperty on the garment's settings and passed to
    ``build_bone_map(..., overrides=...)`` by the pose-transfer stage.
    """

    source_bone: bpy.props.StringProperty(
        name="Garment Bone",
        description="Bone name on the garment/source rig to override the mapping for",
    )
    target_bone: bpy.props.StringProperty(
        name="Target Bone",
        description=(
            "Bone name on the target base rig to map it to. Leave empty to "
            "explicitly leave the garment bone unmapped"
        ),
    )


class SCULPTTOOL_PG_settings(bpy.types.PropertyGroup):
    source_body: bpy.props.PointerProperty(
        name="Source Body",
        description="Body mesh the garment was originally authored/bound to",
        type=bpy.types.Object,
    )
    target_body: bpy.props.PointerProperty(
        name="Target Body",
        description="Body mesh to fit the garment onto",
        type=bpy.types.Object,
    )
    # --- "Base" retargeting rigs (roadmap R1, card 062cfedd) ------------
    # A "base" is a rigged body a garment is authored for (DECISIONS.md
    # section 6d). These two pointers make the tool AWARE of the garment's
    # source-base rig and the chosen target-base rig -- the foundation
    # every later pose-transfer card (R2 bone mapping, R3 pose transfer)
    # builds on. R1 only records/selects them; nothing here poses or
    # matches bones yet. Auto-filled from the Source/Target Body's own
    # Armature modifier by SCULPTTOOL_OT_detect_rigs (operators/
    # op_bases.py), or picked by hand. Restricted to Armature objects via
    # the module-level ``_is_armature`` poll.
    source_base_armature: bpy.props.PointerProperty(
        name="Source Base Rig",
        description=(
            "Armature of the base body this garment was authored for. The "
            "garment is skinned to a rig sharing this base's bone-naming "
            "convention. Auto-detected from the Source Body (or the garment "
            "itself) by Detect Rigs; used by the pose-transfer stage"
        ),
        type=bpy.types.Object,
        poll=_is_armature,
    )
    target_base_armature: bpy.props.PointerProperty(
        name="Target Base Rig",
        description=(
            "Armature of the target base body to retarget the garment onto "
            "-- its pose is what a later stage transfers onto the garment. "
            "Auto-detected from the Target Body by Detect Rigs, or picked "
            "by hand. Paired with Target Body as the target base"
        ),
        type=bpy.types.Object,
        poll=_is_armature,
    )
    bind_mode_override: bpy.props.EnumProperty(
        name="Bind Mode",
        description=(
            "Auto-detect picks Mode A when Source Body and Target Body share "
            "vertex count (else Mode B). Force an option to override that "
            "heuristic when a topology-mismatch coincidence would misclassify it"
        ),
        items=BIND_MODE_OVERRIDE_ITEMS,
        default='AUTO',
    )
    offset_scale: bpy.props.FloatProperty(
        name="Offset / Thickness Scale",
        description=(
            "Global multiplier on the stored binding offset, applied at fit "
            "time — tighten or loosen the garment's distance from the body "
            "surface without re-binding"
        ),
        default=1.0,
        soft_min=-2.0,
        soft_max=3.0,
    )
    use_collision_resolution: bpy.props.BoolProperty(
        name="Collision Resolution",
        description=(
            "After projecting the binding onto the Target Body and before "
            "the Shape Key bake, push any garment vertex found inside the "
            "Target Body back out to at least Collision Margin clearance"
        ),
        default=True,
    )
    collision_margin: bpy.props.FloatProperty(
        name="Collision Margin",
        description=(
            "Minimum garment-to-body clearance enforced by the collision "
            "resolution pass, when enabled"
        ),
        default=0.01,
        min=0.0,
        soft_max=0.1,
        unit='LENGTH',
    )
    smoothing_iterations: bpy.props.IntProperty(
        name="Smoothing Iterations",
        description=(
            "Number of pin-weighted Laplacian relaxation passes to run after "
            "collision resolution and before the Shape Key bake, to smooth "
            "noise left by projection/collision without shrink-wrapping the "
            "garment toward the body (constrained against the garment's own "
            "original edge lengths). 0 disables the pass entirely (true "
            "no-op)"
        ),
        default=0,
        min=0,
        soft_max=10,
    )
    # --- Manual bone-map overrides + last-computed summary (R2) ---------
    bone_map_overrides: bpy.props.CollectionProperty(
        type=SCULPTTOOL_PG_bone_override,
        name="Bone Map Overrides",
        description=(
            "Manual corrections to the auto-resolved garment<->target-base "
            "bone map, applied by the pose-transfer stage"
        ),
    )
    bone_map_overrides_index: bpy.props.IntProperty(
        name="Active Override",
        default=0,
    )
    bone_map_summary: bpy.props.StringProperty(
        name="Bone Map Summary",
        description="Result of the last Compute Bone Map run (read-only)",
        default="",
    )
    auto_pose_transfer: bpy.props.BoolProperty(
        name="Auto Pose Transfer",
        description=(
            "Before fitting, automatically pose the garment onto the target "
            "base via the canonical bone map (roadmap R5 -- pose is stage 0 "
            "of the pipeline). Runs only when a garment rig and a target-base "
            "rig are both present; a no-op when the target base is already in "
            "the garment's pose. Batch poses per target base"
        ),
        default=True,
    )
    skip_alignment_check: bpy.props.BoolProperty(
        name="Skip Alignment Check",
        description=(
            "By default, Bind and Fit refuse a garment that is grossly out "
            "of pose/position for its base (nowhere near the body surface) "
            "instead of silently producing garbage (roadmap R4). Enable this "
            "to force the operation past that guard -- e.g. for an unusual "
            "but intentional garment the check misjudges"
        ),
        default=False,
    )
    batch_target_collection: bpy.props.PointerProperty(
        name="Target Collection",
        description=(
            "Collection of target body objects for Batch Fit -- runs the "
            "same project/collision/smooth/bake pipeline as Fit once per "
            "mesh object in this Collection (excluding the garment itself), "
            "reusing Offset/Thickness Scale, Collision Resolution, "
            "Collision Margin, and Smoothing Iterations above for every "
            "target. A target with no valid binding correspondence (e.g. "
            "wrong topology for this garment's bind mode) is skipped with "
            "a warning rather than aborting the rest of the batch"
        ),
        type=bpy.types.Collection,
    )


_classes = (
    SCULPTTOOL_PG_bone_override,
    SCULPTTOOL_PG_settings,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.sculpt_tool = bpy.props.PointerProperty(
        type=SCULPTTOOL_PG_settings,
    )


def unregister():
    del bpy.types.Object.sculpt_tool

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
