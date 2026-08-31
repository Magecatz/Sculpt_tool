"""Read/write binding data as mesh custom attributes.

Per ARCHITECTURE.md section 2: binding data is persisted as custom
attributes on the garment mesh (``bpy.types.Mesh.attributes``) plus
object-level custom properties recording the source body's name,
binding mode, and a schema version. This module defines that naming
scheme for both Mode A and Mode B (mode is recorded per-object via
``PROP_BIND_MODE``, so only one mode's attribute set is populated/read
per garment at a time, but both shapes are defined here) — it is the
contract ``core/solver.py`` relies on at fit time, so attribute
names/types below should not change without bumping ``SCHEMA_VERSION``
and updating every reader.

Domain: every per-vertex binding attribute lives on the mesh's ``POINT``
(vertex) domain — one value per garment vertex, in vertex-index order
(this is exactly what Mode A's direct ``body_vertex_index``
correspondence assumes, and what Mode A's fit-time reader relies on).
"""

import bpy
from mathutils import Matrix, Vector

# Bump whenever the attribute layout below changes in a way existing
# readers would misinterpret. v2 (this card): Mode B stores a frozen
# bind-time source-body anchor (ATTR_SOURCE_ANCHOR_LOCAL /
# PROP_SOURCE_BIND_MATRIX, Part A) and Mode A stores the source body's
# bind-time vertex count (PROP_SOURCE_VERTEX_COUNT, Part C) -- neither
# exists in a v1 binding, so read_mode_a_binding/read_mode_b_binding raise
# BindingVersionError (a ValueError subclass) rather than misreading one.
SCHEMA_VERSION = 2

# Add-on's own baked fit output (operators/op_fit.py). Named here, not
# just there, because operators/op_bind.py also needs it: it must mute
# this exact key block on the garment (and source body) around any
# bind-time evaluated-mesh read (Part B -- "no output of this add-on may
# ever be an input to it").
FITTED_SHAPE_KEY_NAME = "Fitted"

ATTR_PREFIX = "sculpt_tool_bind_"

# --- Mode A (same-topology) attributes ------------------------------------
ATTR_BODY_VERTEX_INDEX = ATTR_PREFIX + "body_vertex_index"  # INT
ATTR_NORMAL_OFFSET = ATTR_PREFIX + "normal_offset"          # FLOAT
ATTR_TANGENT_OFFSET = ATTR_PREFIX + "tangent_offset"        # FLOAT
ATTR_BITANGENT_OFFSET = ATTR_PREFIX + "bitangent_offset"    # FLOAT

# --- Mode B (cross-topology) attributes ------------------------------------
# Mode B reuses ATTR_NORMAL_OFFSET above (a single normal-offset concept
# serves both modes) rather than defining a second one; these three are
# Mode-B-only.
ATTR_TRIANGLE_INDEX = ATTR_PREFIX + "triangle_index"        # INT
ATTR_BARYCENTRIC = ATTR_PREFIX + "barycentric"              # FLOAT_VECTOR (u, v, w)
ATTR_TANGENT_OFFSET_2D = ATTR_PREFIX + "tangent_offset_2d"  # FLOAT2 (in-plane u, v)
# Part A (bind-time freeze): the bind-time anchor point (the same BVH
# nearest-surface hit used to compute normal_offset/tangent_offset_2d),
# frozen in the SOURCE BODY's LOCAL object space at bind time. This is now
# the AUTHORITATIVE anchor for fit-time reconstruction --
# core.solver.project_mode_b computes PROP_SOURCE_BIND_MATRIX @
# ATTR_SOURCE_ANCHOR_LOCAL and never reads the source body's mesh at fit
# time. ATTR_TRIANGLE_INDEX/ATTR_BARYCENTRIC above are kept only as
# diagnostics from here on (see core.binding.bind_mode_b's docstring),
# no longer read by the fit-time solver.
ATTR_SOURCE_ANCHOR_LOCAL = ATTR_PREFIX + "source_anchor_local"  # FLOAT_VECTOR (source-body local space)

_ALL_BIND_ATTRIBUTES = (
    ATTR_BODY_VERTEX_INDEX,
    ATTR_NORMAL_OFFSET,
    ATTR_TANGENT_OFFSET,
    ATTR_BITANGENT_OFFSET,
    ATTR_TRIANGLE_INDEX,
    ATTR_BARYCENTRIC,
    ATTR_TANGENT_OFFSET_2D,
    ATTR_SOURCE_ANCHOR_LOCAL,
)

# --- Object-level custom properties -----------------------------------
# Plain ID properties on the garment Object (obj["..."]), i.e. NOT the
# sculpt_tool.source_body PointerProperty from properties.py. That
# pointer is live/editable UI state (whatever the user currently has
# selected in the panel); these record what the *last successful Bind*
# actually used, so a binding stays self-describing even if the user
# later changes the source_body picker without rebinding.
PROP_SOURCE_BODY_NAME = "sculpt_tool_bind_source_body"  # STRING — body Object name
PROP_BIND_MODE = "sculpt_tool_bind_mode"                # STRING — "A" or "B"
PROP_BIND_VERSION = "sculpt_tool_bind_version"          # INT — SCHEMA_VERSION at bind time
# Part A -- Mode B only: source body's matrix_world AT BIND TIME,
# flattened to 16 floats (row-major -- see _matrix_to_list/_list_to_matrix
# below). Frozen: never re-read from the source body at fit time, which
# is what lets the source body be edited, reshaped, renamed, or deleted
# after bind with no effect on (or crash in) Mode B fitting.
PROP_SOURCE_BIND_MATRIX = "sculpt_tool_bind_source_matrix"  # FLOAT[16]
# Part C -- Mode A only: source body's evaluated vertex count AT BIND
# TIME. project_mode_a refuses outright when the target body's vertex
# count doesn't match this, instead of only guarding individual
# out-of-range body_vertex_index values -- which stays silent whenever
# the target body happens to have MORE vertices than the source body did
# (the no-Target-Body-set trap this card's Part C closes).
PROP_SOURCE_VERTEX_COUNT = "sculpt_tool_bind_source_vertex_count"  # INT

MODE_A = "A"
MODE_B = "B"


class BindingVersionError(ValueError):
    """A garment's stored binding was written by an incompatible Sculpt
    Tool schema version (see SCHEMA_VERSION's docstring above).

    Subclasses ValueError so every existing ``except ValueError`` at the
    fit-time call site (operators/op_fit.py) keeps working unchanged -- it
    reports this exception's message as a normal fit error, no
    special-casing needed.
    """


def _check_schema_version(garment_obj):
    """Raise :class:`BindingVersionError` if ``garment_obj`` carries
    binding data from an older, incompatible schema version.

    Called by :func:`read_mode_a_binding`/:func:`read_mode_b_binding`
    (after confirming the garment is bound at all) so a stale v1 binding
    fails loudly and specifically -- "re-bind, the schema changed" --
    rather than either being silently misread (a v1 Mode B binding has no
    ATTR_SOURCE_ANCHOR_LOCAL/PROP_SOURCE_BIND_MATRIX for Part A to use) or
    falling back to a generic "not bound" message that doesn't explain why
    a binding that clearly exists doesn't work anymore.
    """
    version = garment_obj.get(PROP_BIND_VERSION)
    if version is not None and version != SCHEMA_VERSION:
        raise BindingVersionError(
            f"'{garment_obj.name}' was bound with Sculpt Tool binding "
            f"schema v{version}, which this version of the add-on "
            f"(schema v{SCHEMA_VERSION}) can no longer fit from -- v2 "
            "freezes the Mode B bind-time source-body reference and "
            "records the Mode A source vertex count, neither of which "
            "exists in a v1 binding. Run Bind again on this garment to "
            "re-bind under the current schema."
        )


def _matrix_to_list(matrix):
    """Flatten a ``mathutils.Matrix`` to 16 floats (row-major) for storage
    in a plain ID-property float array -- see :func:`_list_to_matrix`."""
    return [component for row in matrix for component in row]


def _list_to_matrix(values):
    """Inverse of :func:`_matrix_to_list`: rebuild a ``mathutils.Matrix``
    from 16 stored floats (row-major)."""
    values = list(values)
    return Matrix([values[0:4], values[4:8], values[8:12], values[12:16]])


def clear_binding(garment_obj):
    """Remove any existing Sculpt Tool binding data from ``garment_obj``.

    Clears both the mesh's binding attributes and the object-level
    binding custom properties, so rebinding never leaves orphaned
    attribute layers or a stale source-body reference behind.
    """
    mesh = garment_obj.data
    for name in _ALL_BIND_ATTRIBUTES:
        attr = mesh.attributes.get(name)
        if attr is not None:
            mesh.attributes.remove(attr)

    for key in (
        PROP_SOURCE_BODY_NAME,
        PROP_BIND_MODE,
        PROP_BIND_VERSION,
        PROP_SOURCE_BIND_MATRIX,
        PROP_SOURCE_VERTEX_COUNT,
    ):
        if key in garment_obj.keys():
            del garment_obj[key]


def write_mode_a_binding(garment_obj, source_body_obj, result):
    """Persist a Mode A bind result onto ``garment_obj``.

    ``result`` is a ``core.binding.ModeABindResult`` (or any object with
    matching ``body_vertex_index`` / ``normal_offset`` /
    ``tangent_offset`` / ``bitangent_offset`` / ``source_vertex_count``
    sequences/values, one entry per garment vertex for the sequences).
    Cleanly overwrites any previous binding first, so rebinding never
    leaves duplicate/orphaned attribute layers.

    ``result.source_vertex_count`` (Part C) is the number of evaluated
    source-body vertices AT BIND TIME, stored as ``PROP_SOURCE_VERTEX_COUNT``
    so ``core.solver.project_mode_a`` can refuse outright at fit time when
    the target body's vertex count doesn't match it.
    """
    clear_binding(garment_obj)

    mesh = garment_obj.data
    vertex_count = len(mesh.vertices)
    if len(result.body_vertex_index) != vertex_count:
        raise ValueError(
            f"Mode A bind result has {len(result.body_vertex_index)} entries, "
            f"expected one per garment vertex ({vertex_count})."
        )

    index_attr = mesh.attributes.new(ATTR_BODY_VERTEX_INDEX, 'INT', 'POINT')
    normal_attr = mesh.attributes.new(ATTR_NORMAL_OFFSET, 'FLOAT', 'POINT')
    tangent_attr = mesh.attributes.new(ATTR_TANGENT_OFFSET, 'FLOAT', 'POINT')
    bitangent_attr = mesh.attributes.new(ATTR_BITANGENT_OFFSET, 'FLOAT', 'POINT')

    index_attr.data.foreach_set("value", result.body_vertex_index)
    normal_attr.data.foreach_set("value", result.normal_offset)
    tangent_attr.data.foreach_set("value", result.tangent_offset)
    bitangent_attr.data.foreach_set("value", result.bitangent_offset)

    mesh.update()

    garment_obj[PROP_SOURCE_BODY_NAME] = source_body_obj.name
    garment_obj[PROP_BIND_MODE] = MODE_A
    garment_obj[PROP_BIND_VERSION] = SCHEMA_VERSION
    garment_obj[PROP_SOURCE_VERTEX_COUNT] = result.source_vertex_count


def write_mode_b_binding(garment_obj, source_body_obj, result):
    """Persist a Mode B bind result onto ``garment_obj``.

    ``result`` is a ``core.binding.ModeBBindResult`` (or any object with
    matching ``triangle_index`` / ``barycentric`` / ``normal_offset`` /
    ``tangent_offset_2d`` / ``source_anchor_local`` / ``source_bind_matrix``
    fields; the first five are one entry per garment vertex, with
    ``barycentric`` as (u, v, w) tuples, ``tangent_offset_2d`` as (u, v)
    tuples, and ``source_anchor_local`` as ``Vector``s in the source
    body's own local object space). Cleanly overwrites any previous
    binding first, so rebinding never leaves duplicate/orphaned attribute
    layers. Reuses the same ``normal_offset`` attribute Mode A writes
    (mode is recorded per-object, so only one mode's data is ever
    populated at a time).

    Part A: ``source_anchor_local``/``source_bind_matrix`` are the
    authoritative bind-time-frozen reference
    (``ATTR_SOURCE_ANCHOR_LOCAL``/``PROP_SOURCE_BIND_MATRIX``) that lets
    ``core.solver.project_mode_b`` reconstruct the bind-time anchor
    without ever reading the source body's mesh again.
    ``triangle_index``/``barycentric`` are still written (diagnostics
    only from here on -- see ``core.binding.bind_mode_b``'s docstring).
    """
    clear_binding(garment_obj)

    mesh = garment_obj.data
    vertex_count = len(mesh.vertices)
    if len(result.triangle_index) != vertex_count:
        raise ValueError(
            f"Mode B bind result has {len(result.triangle_index)} entries, "
            f"expected one per garment vertex ({vertex_count})."
        )

    index_attr = mesh.attributes.new(ATTR_TRIANGLE_INDEX, 'INT', 'POINT')
    barycentric_attr = mesh.attributes.new(ATTR_BARYCENTRIC, 'FLOAT_VECTOR', 'POINT')
    normal_attr = mesh.attributes.new(ATTR_NORMAL_OFFSET, 'FLOAT', 'POINT')
    tangent2d_attr = mesh.attributes.new(ATTR_TANGENT_OFFSET_2D, 'FLOAT2', 'POINT')
    anchor_attr = mesh.attributes.new(ATTR_SOURCE_ANCHOR_LOCAL, 'FLOAT_VECTOR', 'POINT')

    index_attr.data.foreach_set("value", result.triangle_index)
    barycentric_attr.data.foreach_set(
        "vector", [c for uvw in result.barycentric for c in uvw]
    )
    normal_attr.data.foreach_set("value", result.normal_offset)
    tangent2d_attr.data.foreach_set(
        "vector", [c for uv in result.tangent_offset_2d for c in uv]
    )
    anchor_attr.data.foreach_set(
        "vector", [c for anchor in result.source_anchor_local for c in anchor]
    )

    mesh.update()

    garment_obj[PROP_SOURCE_BODY_NAME] = source_body_obj.name
    garment_obj[PROP_BIND_MODE] = MODE_B
    garment_obj[PROP_BIND_VERSION] = SCHEMA_VERSION
    garment_obj[PROP_SOURCE_BIND_MATRIX] = _matrix_to_list(result.source_bind_matrix)


def read_mode_b_binding(garment_obj):
    """Read back a Mode B binding written by :func:`write_mode_b_binding`.

    Returns a dict with ``triangle_index`` / ``barycentric`` (list of
    (u, v, w) tuples) / ``normal_offset`` / ``tangent_offset_2d`` (list
    of (u, v) tuples) / ``source_anchor_local`` (list of ``Vector``s, in
    the source body's local object space) / ``source_bind_matrix`` (a
    ``mathutils.Matrix``, or ``None`` if absent) (one entry per garment
    vertex for the per-vertex fields, in vertex order) plus
    ``source_body_name`` / ``mode`` / ``version``, or ``None`` if
    ``garment_obj`` carries no Sculpt Tool binding data (or an
    incomplete/foreign one).

    Raises :class:`BindingVersionError` if ``garment_obj`` is bound but
    with an older, incompatible schema version (see that class's
    docstring) -- a v1 Mode B binding predates ``source_anchor_local``/
    ``source_bind_matrix`` entirely, so it cannot be read as a v2 one.
    """
    if not is_bound(garment_obj):
        return None
    _check_schema_version(garment_obj)

    mesh = garment_obj.data
    index_attr = mesh.attributes.get(ATTR_TRIANGLE_INDEX)
    barycentric_attr = mesh.attributes.get(ATTR_BARYCENTRIC)
    normal_attr = mesh.attributes.get(ATTR_NORMAL_OFFSET)
    tangent2d_attr = mesh.attributes.get(ATTR_TANGENT_OFFSET_2D)
    anchor_attr = mesh.attributes.get(ATTR_SOURCE_ANCHOR_LOCAL)
    if not (index_attr and barycentric_attr and normal_attr and tangent2d_attr and anchor_attr):
        return None

    vertex_count = len(mesh.vertices)
    triangle_index = [0] * vertex_count
    barycentric_flat = [0.0] * (vertex_count * 3)
    normal_offset = [0.0] * vertex_count
    tangent2d_flat = [0.0] * (vertex_count * 2)
    anchor_flat = [0.0] * (vertex_count * 3)

    index_attr.data.foreach_get("value", triangle_index)
    barycentric_attr.data.foreach_get("vector", barycentric_flat)
    normal_attr.data.foreach_get("value", normal_offset)
    tangent2d_attr.data.foreach_get("vector", tangent2d_flat)
    anchor_attr.data.foreach_get("vector", anchor_flat)

    barycentric = [
        tuple(barycentric_flat[i : i + 3]) for i in range(0, len(barycentric_flat), 3)
    ]
    tangent_offset_2d = [
        tuple(tangent2d_flat[i : i + 2]) for i in range(0, len(tangent2d_flat), 2)
    ]
    source_anchor_local = [
        Vector(anchor_flat[i : i + 3]) for i in range(0, len(anchor_flat), 3)
    ]

    bind_matrix_raw = garment_obj.get(PROP_SOURCE_BIND_MATRIX)
    source_bind_matrix = (
        _list_to_matrix(bind_matrix_raw) if bind_matrix_raw is not None else None
    )

    return {
        "triangle_index": [int(i) for i in triangle_index],
        "barycentric": barycentric,
        "normal_offset": list(normal_offset),
        "tangent_offset_2d": tangent_offset_2d,
        "source_anchor_local": source_anchor_local,
        "source_bind_matrix": source_bind_matrix,
        "source_body_name": garment_obj.get(PROP_SOURCE_BODY_NAME),
        "mode": garment_obj.get(PROP_BIND_MODE),
        "version": garment_obj.get(PROP_BIND_VERSION),
    }


def read_mode_a_binding(garment_obj):
    """Read back a Mode A binding written by :func:`write_mode_a_binding`.

    Returns a dict with ``body_vertex_index`` / ``normal_offset`` /
    ``tangent_offset`` / ``bitangent_offset`` lists (one entry per
    garment vertex, in vertex order) plus ``source_vertex_count`` (Part C
    -- source body's evaluated vertex count at bind time, or ``None`` if
    absent) / ``source_body_name`` / ``mode`` / ``version``, or ``None``
    if ``garment_obj`` carries no Sculpt Tool binding data (or an
    incomplete/foreign one).

    Raises :class:`BindingVersionError` if ``garment_obj`` is bound but
    with an older, incompatible schema version (see that class's
    docstring).
    """
    if not is_bound(garment_obj):
        return None
    _check_schema_version(garment_obj)

    mesh = garment_obj.data
    index_attr = mesh.attributes.get(ATTR_BODY_VERTEX_INDEX)
    normal_attr = mesh.attributes.get(ATTR_NORMAL_OFFSET)
    tangent_attr = mesh.attributes.get(ATTR_TANGENT_OFFSET)
    bitangent_attr = mesh.attributes.get(ATTR_BITANGENT_OFFSET)
    if not (index_attr and normal_attr and tangent_attr and bitangent_attr):
        return None

    vertex_count = len(mesh.vertices)
    body_vertex_index = [0] * vertex_count
    normal_offset = [0.0] * vertex_count
    tangent_offset = [0.0] * vertex_count
    bitangent_offset = [0.0] * vertex_count

    index_attr.data.foreach_get("value", body_vertex_index)
    normal_attr.data.foreach_get("value", normal_offset)
    tangent_attr.data.foreach_get("value", tangent_offset)
    bitangent_attr.data.foreach_get("value", bitangent_offset)

    return {
        "body_vertex_index": [int(i) for i in body_vertex_index],
        "normal_offset": list(normal_offset),
        "tangent_offset": list(tangent_offset),
        "bitangent_offset": list(bitangent_offset),
        "source_vertex_count": garment_obj.get(PROP_SOURCE_VERTEX_COUNT),
        "source_body_name": garment_obj.get(PROP_SOURCE_BODY_NAME),
        "mode": garment_obj.get(PROP_BIND_MODE),
        "version": garment_obj.get(PROP_BIND_VERSION),
    }


def is_bound(garment_obj):
    """True if ``garment_obj`` carries Sculpt Tool binding metadata."""
    keys = garment_obj.keys()
    return (
        PROP_SOURCE_BODY_NAME in keys
        and PROP_BIND_MODE in keys
        and PROP_BIND_VERSION in keys
    )


def get_binding_info(garment_obj):
    """Return ``(source_body_name, mode, version)``, or ``None`` if unbound."""
    if not is_bound(garment_obj):
        return None
    return (
        garment_obj.get(PROP_SOURCE_BODY_NAME),
        garment_obj.get(PROP_BIND_MODE),
        garment_obj.get(PROP_BIND_VERSION),
    )
