"""``fit_once`` -- the full per-target fit pipeline as one reusable function.

Per ARCHITECTURE.md section 3 (project -> collision -> smooth) and
section 8 (Batch is "a thin orchestration layer over the same ``core/``
modules the single-target ``OT_fit_garment`` uses -- no separate
batch-specific solver logic"). Before this card, that pipeline sequence
only existed inline inside ``operators/op_fit.py``'s ``execute()``, so a
future Batch operator could only honor section 8's "no duplicate pipeline
logic" instruction by copy-pasting it. ``fit_once`` is that sequence,
extracted: ``operators/op_fit.py`` becomes setup + ``fit_once`` + bake +
report, and a future ``operators/op_batch.py`` can call ``fit_once`` once
per target body in its own loop with no duplicated logic (Bear PR Process
card cd0d1569-36ad-4d79-a82b-6d1115a0bcda).

``fit_once`` takes a ``depsgraph`` parameter rather than resolving
Blender's current evaluated depsgraph itself, matching every other
``core/`` module's convention after this card (see ``core/geometry.py``'s
docstring for why: ``core/`` must not assume there's a well-defined
"current context" to evaluate against, which matters for correctness
inside an unattended batch loop, not just for unit-test isolation). The
caller (an operator) resolves the depsgraph once and passes it in.

Does NOT bake to a Shape Key -- that's Blender-object-mutating,
operator-layer work (creating/overwriting a key block, converting back to
the garment's local space) that stays out of ``core/``'s pure-logic scope,
matching every other module here. ``operators/op_fit.py`` is the sole
production caller and does that step itself with ``fit_once``'s output.
"""

from dataclasses import dataclass

from mathutils import Vector

from . import collision, geometry, smoothing, solver, storage

# Boundary-loop straighten passes applied to a placed garment's open edges
# in conform_placed (see there). A few is enough to remove collision-rim
# spikes with negligible rim shrink.
_BOUNDARY_RELAX_ITERATIONS = 5

# conform_placed's offset-reprojection blend (fix B2). A vertex authored to
# sit within _REPROJECT_NEAR_FRAC of the body (as a fraction of the target
# body's bounding-box diagonal) is fully reprojected onto the target surface
# -- that's where girth mismatches interpenetrate and where reprojection is
# stable and wanted. A vertex authored FARTHER off than _REPROJECT_FAR_FRAC
# (a loose strap, an open hanging jacket panel) keeps its armature-placed
# position instead: its nearest-body-surface correspondence is unstable
# (adjacent loose verts snap to different body regions, scattering the rim),
# and the skeleton already carries it correctly. Between the two the weight
# ramps smoothly so there's no seam.
_REPROJECT_NEAR_FRAC = 0.012
_REPROJECT_FAR_FRAC = 0.06


@dataclass
class FitParams:
    """The user-facing Fit parameters (``obj.sculpt_tool``'s numeric/
    toggle settings), collected into one plain-data object so
    ``fit_once`` takes a single ``params`` argument instead of four
    separate ones -- and so a future Batch operator can build one
    ``FitParams`` per run (or per target, if it ever needs per-target
    overrides) without touching ``bpy`` settings objects inside a loop.
    """

    offset_scale: float = 1.0
    use_collision_resolution: bool = True
    collision_margin: float = 0.01
    smoothing_iterations: int = 0


def fit_once(garment_obj, target_body_obj, params, depsgraph, relax_ctx=None, target_ctx=None):
    """Run the full project -> collision -> smooth pipeline once.

    Mirrors ``operators/op_fit.py``'s pre-card pipeline exactly (see that
    module's docstring for the full step-by-step rationale, still
    accurate): ``core.solver.project_garment`` re-evaluates the garment's
    stored binding against ``target_body_obj``, then -- when
    ``params.use_collision_resolution`` -- ``core.collision.
    resolve_collisions`` pushes any interpenetrating vertex back out to at
    least ``params.collision_margin`` clearance, then -- when
    ``params.smoothing_iterations > 0`` -- ``core.smoothing.
    relax_positions`` runs that many pin-weighted relaxation passes, then
    -- when BOTH collision resolution and smoothing ran -- collision
    resolution runs a SECOND time on the smoothed result (smoothing has no
    notion of the target body and can drag an already-cleared vertex back
    into it; see ``operators/op_fit.py``'s docstring for the full
    rationale and the card that fixed it, 1e252575-2b86-4ba5-89f7-
    bcf0ae9685ba). The second pass reuses the SAME
    ``projection.anchor_positions``/``anchor_normals`` as the first: the
    anchor is a property of the binding's correspondence to the target
    body, not of the garment's current position, so smoothing moving
    vertices around does not invalidate it.

    A single ``core.geometry.TargetContext`` is built once, up front, from
    ``target_body_obj`` and ``depsgraph``, and reused for every step above
    that needs the target body's evaluated geometry (Mode B projection,
    both collision passes) -- this is what makes the target body's
    evaluation happen exactly once per ``fit_once`` call, no matter how
    many pipeline steps query it or how many times collision resolution
    runs (Bear PR Process card cd0d1569-36ad-4d79-a82b-6d1115a0bcda).
    ``TargetContext.bvh``/``.triangles`` are themselves built lazily (see
    ``core.geometry.TargetContext``'s docstring) and cached on first
    access, so a Mode A fit with collision resolution disabled -- which
    never reads either -- never triangulates or BVH-builds the target
    body at all, and never requires it to have any faces (Bear PR Process
    card e6763cc5-d3cf-4021-8541-f5e5dd4a23aa, fixing a regression this
    card's own extraction introduced). Mode B fits and both collision
    passes still access ``target_ctx.bvh`` and get the same "no
    triangulatable faces" ``ValueError`` as before if the target has none.

    ``relax_ctx``, if given, is a pre-built ``core.smoothing.
    RelaxContext`` for ``garment_obj`` -- skips rebuilding the garment's
    adjacency/original-edge-length/pin-weight arrays (constant across an
    entire batch run against the SAME garment; see ``RelaxContext``'s
    docstring). Built internally via ``RelaxContext.build(garment_obj)``
    when omitted and smoothing actually runs; never built at all when
    ``params.smoothing_iterations <= 0``, matching ``operators/op_fit.py``
    's pre-card guarantee that the zero-smoothing-iterations case doesn't
    even build the adjacency/neighbor structure or look up ``Pin_*``
    vertex groups.

    ``target_ctx``, if given, is a pre-built ``core.geometry.TargetContext``
    for ``target_body_obj`` -- built internally via
    ``TargetContext.build(target_body_obj, depsgraph)`` when omitted. An
    operator that already needs the target context for its own purposes
    before the fit (e.g. ``operators/op_fit.py``'s roadmap-R4 alignment
    guard, or a batch loop reusing it) passes it in so the target body is
    evaluated/triangulated/BVH-built exactly once, not once for the
    pre-check and again here.

    Returns the fitted WORLD-SPACE positions, one ``mathutils.Vector`` per
    garment vertex, in vertex-index order -- ready for a caller to convert
    to the garment's local space and bake into a Shape Key (or for a
    batch caller to do the same, once per target).

    Raises ``ValueError`` on any of the same conditions ``core.solver``/
    ``core.geometry``/``core.collision`` already raise it for (garment not
    bound, target body with no vertices/faces, a stale/missing Mode B
    source body, a solver output length mismatch) -- callers should catch
    it exactly as ``operators/op_fit.py`` always has.
    """
    if target_ctx is None:
        target_ctx = geometry.TargetContext.build(target_body_obj, depsgraph)

    projection = solver.project_garment(garment_obj, target_ctx, params.offset_scale)
    fitted = projection.fitted_positions

    if params.use_collision_resolution:
        fitted = collision.resolve_collisions(
            fitted,
            projection.anchor_positions,
            projection.anchor_normals,
            target_ctx.bvh,
            params.collision_margin,
        )

    if params.smoothing_iterations > 0:
        if relax_ctx is None:
            relax_ctx = smoothing.RelaxContext.build(garment_obj)

        fitted = smoothing.relax_positions(
            fitted,
            relax_ctx.neighbors,
            relax_ctx.original_edges,
            relax_ctx.pin_weights,
            params.smoothing_iterations,
        )

        if params.use_collision_resolution:
            # Smoothing has no notion of the target body and can push an
            # already-cleared vertex back into it -- re-run collision
            # resolution on the smoothed result, reusing the same anchors
            # and the same target_ctx.bvh (no rebuild) as the first pass.
            fitted = collision.resolve_collisions(
                fitted,
                projection.anchor_positions,
                projection.anchor_normals,
                target_ctx.bvh,
                params.collision_margin,
            )

    return fitted


def _nearest_anchors(positions, bvh):
    """For each world position, the nearest point on ``bvh`` and its normal
    -- the fresh surface correspondence a placed garment conforms against
    (replacing the frozen bind-time anchor when the armature has already
    placed the garment). A position with no hit keeps itself as its own
    anchor (an up normal), so it's simply left where it is."""
    anchor_positions = []
    anchor_normals = []
    for position in positions:
        location, normal, index, _distance = bvh.find_nearest(position)
        if index is None:
            anchor_positions.append(position)
            anchor_normals.append(Vector((0.0, 0.0, 1.0)))
        else:
            anchor_positions.append(location)
            anchor_normals.append(normal)
    return anchor_positions, anchor_normals


def _read_authored_offsets(garment_obj):
    """Per garment vertex, the authored body-relative offset ``(normal,
    tangent, bitangent)`` recorded at bind time, in vertex-index order --
    or ``None`` if the garment carries no readable binding.

    This is the "how far off its body, and in which in-plane direction,
    was this vertex authored to sit" data both bind modes store (a loose
    strap has a large ``normal`` offset; a tight waistband ~0). Mode A
    keeps an explicit ``(normal, tangent, bitangent)`` triple; Mode B keeps
    ``normal`` plus a 2D in-plane ``(u, v)`` -- both reduce to the same
    orthonormal-frame triple, reapplied by :func:`conform_placed` in the
    TARGET surface frame at each vertex's placed correspondence (the same
    way ``core.solver.project_mode_b`` reapplies it, just anchored to the
    placed position instead of the frozen bind-time anchor).
    """
    mode = garment_obj.get(storage.PROP_BIND_MODE)
    if mode == storage.MODE_A:
        info = storage.read_mode_a_binding(garment_obj)
        if info is None:
            return None
        return list(
            zip(info["normal_offset"], info["tangent_offset"], info["bitangent_offset"])
        )
    if mode == storage.MODE_B:
        info = storage.read_mode_b_binding(garment_obj)
        if info is None:
            return None
        return [
            (normal, uv[0], uv[1])
            for normal, uv in zip(info["normal_offset"], info["tangent_offset_2d"])
        ]
    return None


def _bbox_diagonal(positions):
    """Bounding-box diagonal length of a set of world positions (the scale
    ``conform_placed`` measures its near/far reprojection thresholds
    against), or ``0.0`` for an empty set."""
    if not positions:
        return 0.0
    lo = [min(p[i] for p in positions) for i in range(3)]
    hi = [max(p[i] for p in positions) for i in range(3)]
    return ((hi[0] - lo[0]) ** 2 + (hi[1] - lo[1]) ** 2 + (hi[2] - lo[2]) ** 2) ** 0.5


def _reproject_authored_offset(placed_positions, offsets, target_ctx, offset_scale):
    """Re-derive each placed vertex's correspondence on the target body and
    reapply its authored *standoff* there, blended against the armature
    placement by how loose the vertex was authored (roadmap R8 / fix B2).

    For each placed vertex, the nearest point on the target surface is the
    fresh correspondence the armature placement earned (a sleeve placed near
    the arm now finds the arm, not the torso -- the whole reason placement
    runs first). The vertex's authored ``normal_offset`` (its standoff from
    its own body, the single most reliable "how loose is this" signal both
    bind modes record) is reapplied along that surface's outward normal.

    The reprojected candidate is then **blended with the placed position** by
    a weight that depends on the authored standoff, measured as a fraction of
    the target body's bounding-box diagonal (see ``_REPROJECT_NEAR_FRAC`` /
    ``_REPROJECT_FAR_FRAC``): tight vertices (small standoff) are fully
    reprojected -- that's where a fatter/thinner target body needs the
    garment pushed out/in and where nearest-surface correspondence is stable;
    loose vertices (large standoff -- open hanging panels, straps, rolled
    cuffs) keep their armature-placed position, because reprojecting a
    surface far from the body scatters the rim (adjacent verts snap to
    different body regions) and the skeleton already carries the loose shape
    correctly. The in-plane tangent components are intentionally dropped:
    they are small authored residuals whose bind-time in-plane direction has
    no stable meaning in the target's (different) surface frame, and keeping
    them only adds scatter.

    Returns ``(fitted, anchor_positions, anchor_normals)`` -- the anchors
    being the nearest-surface hit points/normals, for the collision passes.
    """
    bvh = target_ctx.bvh
    positions = target_ctx.positions
    triangles = target_ctx.triangles

    diagonal = _bbox_diagonal(positions)
    near = _REPROJECT_NEAR_FRAC * diagonal
    far = _REPROJECT_FAR_FRAC * diagonal
    span = max(far - near, 1e-9)

    fitted = []
    anchor_positions = []
    anchor_normals = []
    for placed, (normal_offset, _tangent_u, _tangent_v) in zip(placed_positions, offsets):
        hit_location, _hit_normal, tri_index, _distance = bvh.find_nearest(placed)
        if tri_index is None:
            fitted.append(placed)
            anchor_positions.append(placed)
            anchor_normals.append(Vector((0.0, 0.0, 1.0)))
            continue
        tri = triangles[tri_index]
        a, b, c = positions[tri[0]], positions[tri[1]], positions[tri[2]]
        normal, _tangent, _bitangent = geometry.triangle_frame(a, b, c)

        reprojected = hit_location + normal * (normal_offset * offset_scale)

        # Blend weight: 1 (fully reproject) when authored tight, ramping to
        # 0 (keep the armature placement) when authored loose.
        standoff = abs(normal_offset) * offset_scale
        if standoff <= near:
            weight = 1.0
        elif standoff >= far:
            weight = 0.0
        else:
            weight = 1.0 - (standoff - near) / span

        fitted.append(placed.lerp(reprojected, weight))
        anchor_positions.append(hit_location)
        anchor_normals.append(normal)
    return fitted, anchor_positions, anchor_normals


def conform_placed(placed_positions, target_ctx, params, garment_obj):
    """Conform an already-armature-PLACED garment to the target body (roadmap R8,
    reworked by fix B2).

    The armature stage (R7) has already moved, rotated, and scaled the
    garment onto the target base. This does NOT re-project the *frozen
    bind-time* correspondence the way :func:`fit_once` does (that ignores
    the placement and can put a sleeve on the torso). Instead it uses the
    placement itself to establish a fresh, correct correspondence, then
    reapplies the garment's **authored body-relative offset** at that
    correspondence:

    1. **Offset-preserving reprojection** (:func:`_reproject_authored_offset`)
       -- for each placed vertex, find its nearest point on the target
       surface (a good correspondence *because* placement already put each
       region near the right body part) and reapply the authored
       ``normal``/tangent offset recorded at bind time. A vertex authored to
       sit far off its body (a loose strap, a rolled cuff) is put the same
       distance off the target; a vertex authored tight stays tight. This is
       the step that preserves the garment's silhouette instead of
       collapsing it onto the body -- the core of fix B2. When the garment
       has no readable binding offsets, it degrades to conforming the placed
       positions directly (``fitted = placed``), i.e. the pre-B2 behavior.
    2. **Collision resolution**, if enabled, pushes any vertex still inside
       the body (authored-negative offsets, concave pockets) back out along
       its anchor normal -- reusing the reprojection's own nearest-surface
       anchors.
    3. **Smoothing**, if enabled, relaxes residual correspondence noise --
       with rest edge lengths measured from the PLACED mesh (not the
       garment's authored base mesh), so a scaled placement is not dragged
       back toward its original, unscaled size. A second collision pass
       follows, as in ``fit_once``.
    4. **Boundary straighten** on open-edge rims, then a final collision
       clear -- as before.

    Returns world positions ready to bake. The caller (``operators/
    op_fit.py``) mutes the garment's Armature modifier around the bake so the
    placement -- already baked into these positions -- isn't applied twice.

    ``params.use_collision_resolution``/``smoothing_iterations`` gate the
    cleanup passes; with both off this returns the offset-reprojected
    positions (a pure placement + authored-offset conform).
    """
    offsets = _read_authored_offsets(garment_obj)
    needs_surface = params.use_collision_resolution or params.smoothing_iterations > 0

    if offsets is not None:
        # Offset-preserving reprojection (fix B2) -- the whole point of the
        # placement path, so it runs whether or not the cleanup passes do.
        # Needs the target BVH, so this lazily triangulates/builds it --
        # fine, a placed garment is being fitted to a real body with faces.
        fitted, anchor_positions, anchor_normals = _reproject_authored_offset(
            placed_positions, offsets, target_ctx, params.offset_scale
        )
    else:
        fitted = list(placed_positions)
        anchor_positions, anchor_normals = None, None

    bvh = target_ctx.bvh if needs_surface else None

    if params.use_collision_resolution:
        if anchor_positions is None:
            anchor_positions, anchor_normals = _nearest_anchors(fitted, bvh)
        fitted = collision.resolve_collisions(
            fitted, anchor_positions, anchor_normals, bvh, params.collision_margin
        )

    if params.smoothing_iterations > 0:
        neighbors = smoothing._build_adjacency(garment_obj.data)
        pin_weights = smoothing.compute_pin_weights(garment_obj)
        # Rest edge lengths from the PLACED mesh, so smoothing preserves the
        # placed/scaled shape instead of restoring the authored base size.
        placed_edges = [
            (edge.vertices[0], edge.vertices[1],
             (placed_positions[edge.vertices[1]] - placed_positions[edge.vertices[0]]).length)
            for edge in garment_obj.data.edges
        ]
        fitted = smoothing.relax_positions(
            fitted, neighbors, placed_edges, pin_weights, params.smoothing_iterations
        )
        if params.use_collision_resolution:
            anchor_positions, anchor_normals = _nearest_anchors(fitted, bvh)
            fitted = collision.resolve_collisions(
                fitted, anchor_positions, anchor_normals, bvh, params.collision_margin
            )

    # Straighten ragged open-edge rims (necklines/hems/cuffs/cutouts) that
    # per-vertex collision push-out leaves jagged -- a boundary-only
    # Laplacian along the free-edge loops, then a final collision clear so
    # nothing the straighten nudged is left inside the body. Only runs when
    # the garment actually has open boundaries and a surface to clear
    # against (open-edge boundary card).
    if needs_surface:
        boundary_neighbors = smoothing.boundary_vertex_neighbors(garment_obj.data)
        if any(boundary_neighbors):
            pin_weights = smoothing.compute_pin_weights(garment_obj)
            fitted = smoothing.relax_boundary_positions(
                fitted, boundary_neighbors, pin_weights,
                iterations=_BOUNDARY_RELAX_ITERATIONS,
            )
            if params.use_collision_resolution:
                anchor_positions, anchor_normals = _nearest_anchors(fitted, bvh)
                fitted = collision.resolve_collisions(
                    fitted, anchor_positions, anchor_normals, bvh, params.collision_margin
                )

    return fitted
