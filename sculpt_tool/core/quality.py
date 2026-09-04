"""Surface-quality metric for a fitted garment (fix C).

The retarget pipeline's aggregate acceptance metrics -- centroid height,
mean standoff, a lenient residual-penetration ceiling -- are all blind to
LOCAL surface damage: a region twisted inside-out (the R7 placement bug), a
loose panel scattered into noise, a rim shrink-wrapped flat. Every one of
those preserves the centroid and the mean body distance while ruining the
actual garment, which is why the tool passed its own tests while producing
visibly mangled renders. This module measures that damage directly, so a
regression test -- and, later, an optional post-fit warning -- can gate on
it.

The signal is **per-edge length distortion**. A well-conformed fit is the
SAME mesh moved onto a different body: neighbouring edges stretch or
compress by roughly the same local factor, even where the garment as a
whole was scaled onto a larger/smaller base. A twisted or scattered region,
by contrast, stretches some edges far more than their neighbours. Dividing
each edge's ``fitted / reference`` length ratio by the *median* ratio
(which absorbs the garment's overall placement scaling) leaves a
distribution tightly clustered around 1.0 for a clean fit and heavy-tailed
for a mangled one. :func:`edge_distortion` reports that spread;
``distorted_fraction`` is the headline number a gate uses.

**What it does and does not catch.** Edge-length distortion sees stretch,
shrink (shrink-wrap-flat), and scatter -- the dominant, most visible fit
damage. It is blind to a *rigid* fold/twist by construction (a rigid
rotation preserves every edge length), so the R7 placement-twist bug is
locked separately and decisively by
``tests/test_placement.test_rest_orientation_difference_injects_no_twist``;
in practice a real skinned twist also stretches the edges at its blend
boundary, which this metric does register. Kept a single-signal metric on
purpose -- a dihedral/normal-consistency companion could be added later if
a rigid-fold regression ever slips past the placement test.

Pure data in, pure numbers out -- no ``bpy`` (it takes positions and an
edge list), matching every other ``core/`` module's
testable-without-Blender convention (ARCHITECTURE.md section 5).
"""

from dataclasses import dataclass

MAX_DISTORTED_FRACTION = 0.05  # warn above; provisional, calibrate in Layer 2
MIN_LOOSENESS_RATIO = 0.4      # warn below (when a loose region exists)


@dataclass
class EdgeDistortion:
    """Result of :func:`edge_distortion`.

    - ``median_ratio`` -- median ``fitted/reference`` edge-length ratio, i.e.
      the garment's overall placement scaling (1.0 = same size as authored).
    - ``distorted_fraction`` -- fraction of edges whose length changed by
      more than ``tolerance`` times the median ratio in either direction;
      the headline surface-damage number (0.0 = perfectly uniform).
    - ``max_normalized`` -- the single worst edge's distortion factor away
      from the median scaling (>= 1.0).
    """

    median_ratio: float
    distorted_fraction: float
    max_normalized: float


def looseness_preservation(authored_standoffs, fitted_standoffs, loose_fraction_of=None,
                           loose_threshold=None, min_loose=50):
    """How well a fit keeps authored-LOOSE vertices standing off the body
    (fix B2's whole purpose), as the median ``fitted / authored`` standoff
    ratio over the loose vertices -- or ``None`` if there are too few.

    ``authored_standoffs`` is each garment vertex's authored distance off its
    own body (``abs`` of the binding's stored ``normal_offset``);
    ``fitted_standoffs`` is the same vertex's distance from the target body
    after fitting (nearest-surface). A vertex counts as *loose* when its
    authored standoff exceeds ``loose_threshold`` -- given directly, or as
    ``loose_fraction_of`` (e.g. the target body's bbox diagonal) times a
    default 3%. Fewer than ``min_loose`` loose vertices returns ``None`` (a
    tight garment simply has no loose region to preserve -- not a failure).

    A ratio near 1.0 means the loose geometry kept its authored standoff
    (silhouette preserved); near 0 means it was collapsed onto the body
    (shrink-wrapped flat -- the pre-B2 failure). Measured on the real Tech
    Set sweater onto Egirl: ~0.27 before fix B2, ~0.54 after.
    """
    if loose_threshold is None:
        if loose_fraction_of is None:
            raise ValueError("Pass loose_threshold or loose_fraction_of.")
        loose_threshold = 0.03 * loose_fraction_of

    ratios = [
        fitted / authored
        for authored, fitted in zip(authored_standoffs, fitted_standoffs)
        if authored > loose_threshold
    ]
    if len(ratios) < min_loose:
        return None
    return _median(ratios)


def _median(values):
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        return 0.0
    mid = count // 2
    if count % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def edge_distortion(reference_positions, fitted_positions, edges, tolerance=2.0, min_length=1e-9):
    """Measure per-edge length distortion of ``fitted_positions`` against
    ``reference_positions`` over ``edges``.

    ``reference_positions``/``fitted_positions`` are equal-length sequences
    of ``mathutils.Vector`` (or any object supporting ``-`` and
    ``.length``), one per vertex in the same index order. ``edges`` is an
    iterable of ``(i, j)`` vertex-index pairs (e.g.
    ``[(e.vertices[0], e.vertices[1]) for e in mesh.edges]``). Edges whose
    reference length is below ``min_length`` are skipped (degenerate).

    An edge counts as *distorted* when its length ratio, normalised by the
    median ratio across all edges, exceeds ``tolerance`` (default 2.0) in
    either direction -- i.e. it stretched to more than 2x, or shrank to less
    than 1/2, of what the garment's overall placement scaling would predict.
    Returns an :class:`EdgeDistortion`.
    """
    ratios = []
    for i, j in edges:
        reference_length = (reference_positions[j] - reference_positions[i]).length
        if reference_length <= min_length:
            continue
        fitted_length = (fitted_positions[j] - fitted_positions[i]).length
        ratios.append(fitted_length / reference_length)

    if not ratios:
        return EdgeDistortion(median_ratio=0.0, distorted_fraction=0.0, max_normalized=0.0)

    median = _median(ratios)
    if median <= min_length:
        # The whole garment collapsed to a point -- maximally distorted.
        return EdgeDistortion(median_ratio=median, distorted_fraction=1.0, max_normalized=float("inf"))

    distorted = 0
    worst = 0.0
    for ratio in ratios:
        normalized = ratio / median
        # Symmetric distortion factor >= 1 (2x stretch and 1/2 shrink both
        # score 2.0), so the tolerance is direction-agnostic.
        factor = normalized if normalized >= 1.0 else (1.0 / normalized if normalized > 0 else float("inf"))
        worst = max(worst, factor)
        if factor > tolerance:
            distorted += 1

    return EdgeDistortion(
        median_ratio=median,
        distorted_fraction=distorted / len(ratios),
        max_normalized=worst,
    )


def quality_warning(edge_distortion, looseness):
    """Human-readable warning if a fit's metrics breach the provisional
    gates, else ``None``.

    ``edge_distortion`` is an :class:`EdgeDistortion`; ``looseness`` is the
    median loose-standoff ratio or ``None`` (no loose region -- never warned).
    Pure decision logic so both the single and batch operators share one
    tested threshold source (no ``bpy``).
    """
    problems = []
    if edge_distortion.distorted_fraction > MAX_DISTORTED_FRACTION:
        problems.append(
            f"{edge_distortion.distorted_fraction:.0%} of edges distorted "
            f"(max {MAX_DISTORTED_FRACTION:.0%})"
        )
    if looseness is not None and looseness < MIN_LOOSENESS_RATIO:
        problems.append(
            f"loose regions kept {looseness:.0%} of standoff "
            f"(min {MIN_LOOSENESS_RATIO:.0%})"
        )
    return "; ".join(problems) if problems else None
