"""Rig / armature awareness -- the "base" concept's foundation layer.

Roadmap R1 (Bear PR Process card 062cfedd-eb70-4e55-9500-ef00b03b6b72,
anchor bug 9df4bc00). This module gives the add-on its first notion that a
garment and a body are *rigged* -- that each is skinned to an armature --
which every later pose-transfer card builds on. It does NOT pose or match
anything: bone-name matching across naming conventions is roadmap R2
(``core/rig_map.py``), and transferring a pose is R3. This card only makes
the tool *aware* of source-vs-target base rigs and lets the user select
them (see ARCHITECTURE.md section 1's Stage-1 note and DECISIONS.md
section 6f).

**Vocabulary (ARCHITECTURE.md, DECISIONS.md section 6d).** A *base* is a
rigged body a garment is authored for. Every garment in the corpus is
designed for one base (e.g. ``FBX-Tech Set by Vinuzhka`` is authored for
``RP Female Base_Heeled Foot.fbx``). The tool's job is to let the user put
that garment on a *different* base. So there are two bases in play:

- the **source base** -- the body (mesh + armature) the garment was
  authored for; the garment is itself skinned to a rig sharing that base's
  bone-naming convention (DECISIONS.md section 6e).
- the **target base** -- the body (mesh + armature) the user wants the
  garment retargeted onto.

Like the rest of ``core/``, this module is pure logic operating on Blender
data (object relations and armature data), with no ``bpy.context`` access
and no scene mutation -- it only reads. It is testable outside the UI
(``tests/test_rig.py``), matching every other ``core/`` module's
convention (ARCHITECTURE.md section 5).
"""

from dataclasses import dataclass, field


def deforming_armature(mesh_obj):
    """The Armature Object that deforms ``mesh_obj`` (its rig), or ``None``.

    Resolution order, most-specific first:

    1. An **Armature modifier** whose ``.object`` is set -- the normal way
       a skinned mesh is driven in Blender (and what the FBX importer
       creates for the real ``Test_Items`` clothing/body meshes). The
       first such modifier wins if there is more than one.
    2. A direct **parent of type ARMATURE** -- some rigs parent the mesh to
       the armature without a modifier (or in addition to one); used as a
       fallback so a mesh rigged that way still resolves.

    Returns ``None`` for a mesh with neither (an un-rigged static mesh),
    for ``None``, or for a non-mesh object -- callers treat "no rig" as a
    normal, non-error state (a static garment/body simply has no pose to
    transfer), not something to raise on.
    """
    if mesh_obj is None:
        return None

    for modifier in getattr(mesh_obj, "modifiers", ()):
        if modifier.type == 'ARMATURE' and modifier.object is not None:
            return modifier.object

    parent = getattr(mesh_obj, "parent", None)
    if parent is not None and getattr(parent, "type", None) == 'ARMATURE':
        return parent

    return None


def bone_names(armature_obj):
    """Deform-bone names on ``armature_obj``, in the armature's own bone
    order, or ``[]`` for ``None``/a non-armature object.

    This is every bone in ``armature_obj.data.bones`` -- the tool does not
    yet distinguish "deform" from "helper/control" bones (that
    normalization is R2's job); R1 only needs the raw name set so the UI
    can report a bone count and a later card has something to map.
    """
    if armature_obj is None or getattr(armature_obj, "type", None) != 'ARMATURE':
        return []
    return [bone.name for bone in armature_obj.data.bones]


@dataclass
class RigInfo:
    """A read-only snapshot describing one armature, for UI display and as
    the input a later bone-mapping card (R2) consumes.

    ``root_bones`` are the bones with no parent (a well-formed humanoid rig
    has a single root, usually the hips/root bone, but some rigs carry
    several -- e.g. a separate IK-target or breast/jiggle root -- so this
    is a list, not a single value). ``name`` is the armature object's own
    name, kept so a caller can describe the rig without holding the ``bpy``
    object.
    """

    name: str
    bone_count: int
    bone_names: list = field(default_factory=list)
    root_bones: list = field(default_factory=list)

    @classmethod
    def describe(cls, armature_obj):
        """Build a :class:`RigInfo` for ``armature_obj``.

        Returns ``None`` for ``None``/a non-armature object, so a caller
        can pass ``deforming_armature(...)``'s result straight in and get
        ``None`` back for an un-rigged mesh rather than an empty-but-real
        ``RigInfo``.
        """
        if armature_obj is None or getattr(armature_obj, "type", None) != 'ARMATURE':
            return None
        names = bone_names(armature_obj)
        roots = [bone.name for bone in armature_obj.data.bones if bone.parent is None]
        return cls(
            name=armature_obj.name,
            bone_count=len(names),
            bone_names=names,
            root_bones=roots,
        )
