"""Read/write binding data as mesh custom attributes.

Per ARCHITECTURE.md section 2: binding data is persisted as custom
attributes on the garment mesh (``bpy.types.Mesh.attributes``) plus
object-level custom properties recording the source body's name,
binding mode, and a schema version. This module defines that naming
scheme — it is the contract Mode B's future bind implementation and
``core/solver.py`` (fit-time) both rely on, so attribute names/types
below should not change without bumping ``SCHEMA_VERSION`` and updating
every reader.

Domain: every per-vertex binding attribute lives on the mesh's ``POINT``
(vertex) domain — one value per garment vertex, in vertex-index order
(this is exactly what Mode A's direct ``body_vertex_index``
correspondence assumes, and what Mode A's fit-time reader relies on).
"""

import bpy

# Bump whenever the attribute layout below changes in a way existing
# readers would misinterpret.
SCHEMA_VERSION = 1

ATTR_PREFIX = "sculpt_tool_bind_"

# --- Mode A (same-topology) attributes ------------------------------------
ATTR_BODY_VERTEX_INDEX = ATTR_PREFIX + "body_vertex_index"  # INT
ATTR_NORMAL_OFFSET = ATTR_PREFIX + "normal_offset"          # FLOAT
ATTR_TANGENT_OFFSET = ATTR_PREFIX + "tangent_offset"        # FLOAT
ATTR_BITANGENT_OFFSET = ATTR_PREFIX + "bitangent_offset"    # FLOAT

# --- Mode B (cross-topology) attributes ------------------------------------
# Names reserved now so Mode A and Mode B attributes never collide on a
# garment mesh. Not written by this card's Mode A bind — a future card
# implements the Mode B writer/reader using these.
ATTR_TRIANGLE_INDEX = ATTR_PREFIX + "triangle_index"        # INT
ATTR_BARYCENTRIC = ATTR_PREFIX + "barycentric"              # FLOAT_VECTOR (u, v, w)
ATTR_TANGENT_OFFSET_2D = ATTR_PREFIX + "tangent_offset_2d"  # FLOAT2 (in-plane u, v)

_ALL_BIND_ATTRIBUTES = (
    ATTR_BODY_VERTEX_INDEX,
    ATTR_NORMAL_OFFSET,
    ATTR_TANGENT_OFFSET,
    ATTR_BITANGENT_OFFSET,
    ATTR_TRIANGLE_INDEX,
    ATTR_BARYCENTRIC,
    ATTR_TANGENT_OFFSET_2D,
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

MODE_A = "A"
MODE_B = "B"


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

    for key in (PROP_SOURCE_BODY_NAME, PROP_BIND_MODE, PROP_BIND_VERSION):
        if key in garment_obj.keys():
            del garment_obj[key]


def write_mode_a_binding(garment_obj, source_body_obj, result):
    """Persist a Mode A bind result onto ``garment_obj``.

    ``result`` is a ``core.binding.ModeABindResult`` (or any object with
    matching ``body_vertex_index`` / ``normal_offset`` /
    ``tangent_offset`` / ``bitangent_offset`` sequences, one entry per
    garment vertex). Cleanly overwrites any previous binding first, so
    rebinding never leaves duplicate/orphaned attribute layers.
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


def read_mode_a_binding(garment_obj):
    """Read back a Mode A binding written by :func:`write_mode_a_binding`.

    Returns a dict with ``body_vertex_index`` / ``normal_offset`` /
    ``tangent_offset`` / ``bitangent_offset`` lists (one entry per
    garment vertex, in vertex order) plus ``source_body_name`` / ``mode``
    / ``version``, or ``None`` if ``garment_obj`` carries no Sculpt Tool
    binding data (or an incomplete/foreign one).
    """
    if not is_bound(garment_obj):
        return None

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
