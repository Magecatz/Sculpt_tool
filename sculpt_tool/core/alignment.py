"""Gross garment/base pose-or-position mismatch guard.

Roadmap R4 (Bear PR Process card 812a0a6a-57b6-43cf-a0d0-0583e5d6aa61,
anchor bug 9df4bc00). The interim, cheapest win against the tool's worst
behavior: reporting ``FINISHED`` on an unusable result. Today the pipeline
assumes the garment is already positioned/posed to sit on its body and
never checks (ARCHITECTURE.md section 7 rows 2 and 18 -- the
"unvalidated-input-precondition" family). When that assumption is false --
a garment fed against a target base it isn't posed/positioned to match --
nearest-surface projection produces garbage and the operator still says it
worked.

This module refuses that case with an actionable message instead. It is
**not** the real fix (that's the pose-transfer stage, R3) -- it's a guard
so a gross mismatch fails loudly and early rather than silently. It is
deliberately **lenient**: it only trips on *gross* mismatches (a garment
nowhere near the body, at the wrong scale, or on average far off its
surface), never on an ordinary loose garment or an intentionally detached
design feature (e.g. the Vinuzhka cuff, DECISIONS.md section 6c). A
per-object escape hatch (``skip_alignment_check``) lets a user force past
a false positive.

Pure logic (operates on world-space positions + an optional BVH), no
``bpy``/``bpy.context`` -- callers (``operators/op_bind.py``,
``operators/op_fit.py`` via a small bridge) supply the geometry.
``core.geometry.TargetContext`` already gives everything needed (evaluated
world positions + a lazily-built BVH), so the check reuses that rather
than evaluating the body a second time.

**Faceless targets.** The surface-distance half of the check needs the
body's triangulated BVH. A body with vertices but no faces (the case card
e6763cc5 fixed for Mode A) has none, so the check falls back to the
bounding-box/position half only and never forces a BVH build -- preserving
the faceless-Mode-A path exactly.
"""

from dataclasses import dataclass

# A garment vertex is "far" from the body if its nearest-surface distance
# exceeds this fraction of the body's bounding-box diagonal (~12% of a ~2m
# body is ~24cm off the surface -- clearly detached, not ordinary looseness).
FAR_DIST_FRACTION = 0.12
# Refuse if more than this fraction of sampled garment vertices are "far"
# (catches a garment mostly off the body -- gross position/pose mismatch).
MAX_FAR_FRACTION = 0.5
# Refuse if the MEAN nearest-surface distance exceeds this fraction of the
# body diagonal (an aligned garment hugs the surface -- mean ratio is a few
# percent; this only trips when the garment sits well off the body overall).
MAX_MEAN_DIST_FRACTION = 0.12
# Refuse if the garment's centroid is farther from the body's centroid than
# this fraction of the body's bounding-box diagonal -- catches a garment
# floating well beside/away from the body (gross position/scale mismatch).
# Robust to thin/planar geometry, unlike a bbox-volume-overlap test (a
# garment sitting a little above a flat body still shares its centroid). A
# garment authored on its body shares its centroid closely; 0.75 only trips
# when the garment sits most of a body-length off-center.
MAX_CENTROID_FRACTION = 0.75
# Cap how many garment vertices the surface-distance sampling walks, so the
# check stays cheap on a 50k-vertex garment (stride-sampled, deterministic).
SAMPLE_CAP = 4000


@dataclass
class AlignmentReport:
    """Result of an alignment check.

    ``aligned`` is False only on a *gross* mismatch. ``reason`` is an
    empty string when aligned, else an actionable message naming what's
    wrong and pointing at the fix (pose transfer / repositioning). The
    numeric fields are the measured signals, kept for the message and for
    tests to assert against.
    """

    aligned: bool
    reason: str = ""
    far_fraction: float = 0.0
    mean_dist_ratio: float = 0.0
    centroid_dist_ratio: float = 0.0
    checked_surface: bool = False


def _bounds(positions):
    xs = [p.x for p in positions]
    ys = [p.y for p in positions]
    zs = [p.z for p in positions]
    return (
        (min(xs), min(ys), min(zs)),
        (max(xs), max(ys), max(zs)),
    )


def _diagonal(lo, hi):
    return ((hi[0] - lo[0]) ** 2 + (hi[1] - lo[1]) ** 2 + (hi[2] - lo[2]) ** 2) ** 0.5


def _centroid(positions):
    n = len(positions)
    sx = sum(p.x for p in positions)
    sy = sum(p.y for p in positions)
    sz = sum(p.z for p in positions)
    return (sx / n, sy / n, sz / n)


def _distance(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def evaluate_alignment(garment_positions, body_positions, body_bvh, label="target base"):
    """Judge whether ``garment_positions`` are grossly mis-posed/mis-placed
    relative to a body.

    ``garment_positions``/``body_positions`` are world-space ``Vector``
    lists; ``body_bvh`` is the body's ``BVHTree`` (for the surface-distance
    signal) or ``None`` when the body has no faces (bounding-box/position
    signal only). ``label`` names the body in the returned message.

    Returns an :class:`AlignmentReport`. Never raises -- a caller decides
    whether to refuse based on ``report.aligned``.
    """
    if not garment_positions or not body_positions:
        # Nothing to compare -- treat as aligned (other guards handle empty
        # meshes with their own, more specific errors).
        return AlignmentReport(aligned=True)

    b_lo, b_hi = _bounds(body_positions)
    body_diag = _diagonal(b_lo, b_hi)
    if body_diag < 1e-9:
        return AlignmentReport(aligned=True)

    centroid_dist = _distance(_centroid(garment_positions), _centroid(body_positions))
    centroid_ratio = centroid_dist / body_diag
    if centroid_ratio > MAX_CENTROID_FRACTION:
        return AlignmentReport(
            aligned=False,
            reason=(
                f"The garment sits well off the {label} in space (its center "
                f"is {centroid_ratio * 100:.0f}% of the body's size away from "
                "the body's center). It looks like the garment isn't "
                "positioned on the body (wrong location or scale). "
                "Position/scale the garment onto the base first (a "
                "pose-transfer stage will automate this), or enable 'Skip "
                "Alignment Check' to force the fit."
            ),
            centroid_dist_ratio=centroid_ratio,
        )

    if body_bvh is None:
        # No faces to measure surface distance against -- position check
        # passed, so accept (can't do better without a surface).
        return AlignmentReport(
            aligned=True, centroid_dist_ratio=centroid_ratio, checked_surface=False
        )

    far_threshold = FAR_DIST_FRACTION * body_diag
    count = len(garment_positions)
    stride = max(1, count // SAMPLE_CAP)
    sampled = 0
    far = 0
    dist_sum = 0.0
    for i in range(0, count, stride):
        location, _normal, index, _dist = body_bvh.find_nearest(garment_positions[i])
        if index is None:
            continue
        distance = (garment_positions[i] - location).length
        dist_sum += distance
        sampled += 1
        if distance > far_threshold:
            far += 1

    if sampled == 0:
        return AlignmentReport(aligned=True, centroid_dist_ratio=centroid_ratio, checked_surface=False)

    far_fraction = far / sampled
    mean_dist_ratio = (dist_sum / sampled) / body_diag

    if far_fraction > MAX_FAR_FRACTION or mean_dist_ratio > MAX_MEAN_DIST_FRACTION:
        return AlignmentReport(
            aligned=False,
            reason=(
                f"The garment is grossly out of pose/position for the {label}: "
                f"{far_fraction * 100:.0f}% of its vertices sit far off the "
                f"body surface (mean offset {mean_dist_ratio * 100:.0f}% of the "
                "body's size). Nearest-surface fitting will produce garbage "
                "across a gap like this (e.g. a sleeve collapsing onto the "
                "torso). Pose the garment onto the base first (a pose-transfer "
                "stage will automate this), or enable 'Skip Alignment Check' "
                "to force the fit anyway."
            ),
            far_fraction=far_fraction,
            mean_dist_ratio=mean_dist_ratio,
            centroid_dist_ratio=centroid_ratio,
            checked_surface=True,
        )

    return AlignmentReport(
        aligned=True,
        far_fraction=far_fraction,
        mean_dist_ratio=mean_dist_ratio,
        centroid_dist_ratio=centroid_ratio,
        checked_surface=True,
    )


def check_against_body(garment_positions, body_ctx, label="target base"):
    """Convenience bridge: run :func:`evaluate_alignment` against a
    :class:`core.geometry.TargetContext`.

    Uses the body's BVH only when the body actually has triangulatable
    faces (``body_ctx._triangles``), so a faceless body never triggers a
    BVH build here -- preserving the faceless-Mode-A path (card e6763cc5).
    """
    body_bvh = body_ctx.bvh if body_ctx._triangles else None
    return evaluate_alignment(
        garment_positions, body_ctx.positions, body_bvh, label=label
    )
