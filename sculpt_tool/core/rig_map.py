"""Canonical humanoid bone mapping across rig naming conventions.

Roadmap R2 (Bear PR Process card 1b7b56eb-dd3f-4334-b872-0f213f3a856a,
anchor bug 9df4bc00). Consumed by the pose-transfer stage (R3): it matches
a garment rig's bones to a target-base rig's bones **despite different
naming conventions**, which -- as DECISIONS.md section 6e establishes --
is the substantive difference between these rigs. Naive string equality
does NOT work.

**The naming families this normalizes** (measured from the real
``Test_Items`` rigs -- see DECISIONS.md section 6e):

    | Rig family      | Separator | Arm chain              | Leg chain              |
    |-----------------|-----------|------------------------|------------------------|
    | RP Female/TechSet | .L/.R   | Arm / Elbow / Wrist    | Leg / Knee / Foot      |
    | vrbase/bodysuit | _L/_R     | Arm_L / Elbow_L / ...  | Leg_L / Knee_L / ...   |
    | Project Venus   | .L/.R     | Upper_Arm / Lower_Arm / Hand | Upper_Leg / Lower_Leg / Foot |

All three are the same humanoid hierarchy (Hips -> Spine -> Chest ->
Shoulders/Arms/Hands + Neck/Head; Hips -> Legs -> Feet -> Toes) plus
per-rig helper bones (twist / jiggle / breast / butt / pussy / hip-dip /
``*_end`` leaf tips) with no cross-rig counterpart. Those helper bones are
deliberately **left unmapped and surfaced**, never force-fit onto a
primary joint (the card's "unmatched bones are surfaced rather than
silently dropped").

**How it works.** Each bone name is reduced to a :class:`CanonicalBone`
``(joint, side, segment)`` by :func:`canonicalize` -- a side extractor
(trailing ``.L``/``_L``/``.R``/``_R``) plus a separator-insensitive joint
lookup (``Upper_Arm``/``Arm`` -> ``UpperArm``, ``Wrist``/``Hand`` ->
``Hand``, ``Toes``/``Toe`` -> ``Toe``, ...). Two bones from two rigs that
canonicalize to the same :class:`CanonicalBone` are the same body joint,
so they map to each other regardless of source spelling.
:func:`build_bone_map` runs that over both rigs' bone-name lists and pairs
up the joints present in both.

Like the rest of ``core/``, this is **pure string/data logic** -- it takes
lists of bone names (not ``bpy`` armatures), has no ``bpy`` import and no
``bpy.context`` access, and is fully testable outside Blender
(``tests/test_rig_map.py``). ``operators/op_bones.py`` bridges a real
``bpy`` armature to it via ``core.rig.bone_names``.
"""

import re
from dataclasses import dataclass, field

# --- Canonical joint vocabulary -------------------------------------------
# The "primary deform chain" every humanoid rig in the corpus shares. These
# are the canonical joint labels a per-rig name resolves onto.
CENTRAL_JOINTS = ("Hips", "Spine", "Chest", "Neck", "Head")
SIDED_JOINTS = (
    "Shoulder",
    "UpperArm",
    "LowerArm",
    "Hand",
    "UpperLeg",
    "LowerLeg",
    "Foot",
    "Toe",
)
FINGER_JOINTS = ("Thumb", "Index", "Middle", "Ring", "Little")

# The canonical primary chain (central + sided), as CanonicalBone keys --
# what a pair of humanoid rigs is expected to fully resolve between. Built
# at import time (see bottom of module).

# Normalized-token -> canonical joint. A token is normalized by lowercasing
# and stripping every non-alphanumeric character (so ``Upper_Arm``,
# ``upper arm`` and ``UpperArm`` all become ``upperarm``). Whole-token
# matching (not substring) is what keeps helper bones like ``Elbow_Twist``
# ("elbowtwist") or ``Thigh_Jiggle`` ("thighjiggle") from being pulled onto
# ``LowerArm``/``UpperLeg`` -- they simply don't equal any key here.
_JOINT_ALIASES = {
    # central
    "hips": "Hips", "hip": "Hips", "pelvis": "Hips",
    "spine": "Spine", "spine1": "Spine",
    "chest": "Chest", "upperchest": "Chest", "spine2": "Chest",
    "neck": "Neck",
    "head": "Head",
    # arm chain
    "shoulder": "Shoulder", "clavicle": "Shoulder", "collar": "Shoulder",
    "arm": "UpperArm", "upperarm": "UpperArm",
    "elbow": "LowerArm", "lowerarm": "LowerArm", "forearm": "LowerArm",
    "wrist": "Hand", "hand": "Hand",
    # leg chain
    "leg": "UpperLeg", "upperleg": "UpperLeg", "thigh": "UpperLeg",
    "knee": "LowerLeg", "lowerleg": "LowerLeg", "shin": "LowerLeg", "calf": "LowerLeg",
    "foot": "Foot", "ankle": "Foot",
    "toe": "Toe", "toes": "Toe",
}

_CENTRAL_SET = set(CENTRAL_JOINTS)
_SIDED_SET = set(SIDED_JOINTS)

# Trailing side token: a separator (``.``/``_``/space) then L or R at the
# very end. Greedy so it strips the LAST such token (a name like
# ``Ring Finger .L`` keeps its internal space and loses only the ``.L``).
_SIDE_RE = re.compile(r"^(.*)[._ ]([LlRr])$")

_FINGER_KEYWORDS = (
    ("thumb", "Thumb"),
    ("index", "Index"),
    ("middle", "Middle"),
    ("ring", "Ring"),
    ("little", "Little"),
    ("pinky", "Little"),
    ("pinkie", "Little"),
)


@dataclass(frozen=True)
class CanonicalBone:
    """A normalized humanoid joint identity, comparable across rigs.

    ``joint`` is a canonical label (e.g. ``"UpperArm"``, ``"Hips"``,
    ``"Index"``). ``side`` is ``"L"``/``"R"`` for a limb/finger, ``None``
    for a central spine bone. ``segment`` is a 1-based finger-segment index
    (1..3) for finger joints, ``None`` otherwise. Frozen so it can be a
    dict key (two rigs' bones that produce an equal ``CanonicalBone`` are
    the same joint).
    """

    joint: str
    side: "str | None" = None
    segment: "int | None" = None

    def label(self):
        """Human-readable label for UI/console (e.g. ``UpperArm.L``,
        ``Index.R.2``, ``Hips``)."""
        parts = [self.joint]
        if self.side is not None:
            parts.append(self.side)
        if self.segment is not None:
            parts.append(str(self.segment))
        return ".".join(parts)


def _normalize(token):
    return re.sub(r"[^a-z0-9]", "", token.lower())


def _extract_side(name):
    """Split a trailing ``.L``/``_R``/... side token off ``name``.

    Returns ``(core, side)`` with ``side`` in ``{"L", "R", None}``. Only a
    side token preceded by a separator is stripped, so a plain ``Head`` or
    ``Chest`` (ending in a letter that isn't a separated L/R) is never
    misread as sided.
    """
    match = _SIDE_RE.match(name)
    if match is None:
        return name.strip(), None
    return match.group(1).strip(), match.group(2).upper()


def _parse_finger(core):
    """If ``core`` names a finger, return ``(family, segment)``; else
    ``(None, None)``.

    Toe-fingers (``Index Toe``, ``Thumb Toe`` -- real bones on the RP rig)
    are explicitly NOT treated as hand fingers: any name containing "toe"
    returns ``(None, None)`` here so it never collides with a hand finger
    (the main ``Toe`` bone is handled by the plain-joint table, not here).
    """
    n = _normalize(core)
    if "toe" in n:
        return None, None

    family = None
    if "thumb" in n:
        family = "Thumb"
    elif "finger" in n:
        for keyword, canon in _FINGER_KEYWORDS[1:]:
            if keyword in n:
                family = canon
                break
    if family is None:
        return None, None

    digits = re.findall(r"\d+", n)
    if digits:
        segment = int(digits[-1])
        if segment <= 0:
            segment = 1
        elif segment > 3:
            segment = 3
    else:
        segment = 1
    return family, segment


def canonicalize(bone_name):
    """Reduce a rig bone name to a :class:`CanonicalBone`, or ``None`` if it
    isn't a recognized primary-chain/finger deform bone.

    ``None`` covers helper bones (twist/jiggle/breast/butt/...), ``*_end``
    leaf tips, and anything else with no cross-rig humanoid meaning -- these
    are surfaced as "unmapped" by :func:`build_bone_map` rather than
    force-fit onto a joint.
    """
    if bone_name is None:
        return None
    name = bone_name.strip()
    if not name or name.lower().endswith("_end"):
        return None

    core, side = _extract_side(name)

    family, segment = _parse_finger(core)
    if family is not None:
        # Fingers are inherently sided; an unsided finger name is ambiguous.
        if side is None:
            return None
        return CanonicalBone(joint=family, side=side, segment=segment)

    joint = _JOINT_ALIASES.get(_normalize(core))
    if joint is None:
        return None

    if joint in _CENTRAL_SET:
        # A central spine bone must be unsided; a sided one (e.g. a
        # hypothetical "Spine.L") is not a recognized primary bone.
        return CanonicalBone(joint=joint) if side is None else None

    # Sided limb joint: requires a side to be meaningful.
    if side is None:
        return None
    return CanonicalBone(joint=joint, side=side)


@dataclass
class RigResolution:
    """The result of canonicalizing one rig's bone names.

    ``mapped`` is ``{CanonicalBone: bone_name}`` (first bone to claim a
    canonical key wins). ``ambiguous`` is ``{CanonicalBone: [extra
    bone_names]}`` for canonical keys more than one bone resolved to (kept
    visible rather than silently dropped -- e.g. some rigs' inconsistent
    thumb segment numbering). ``unmapped`` is every bone name with no
    canonical identity (helper bones), in input order.
    """

    mapped: dict = field(default_factory=dict)
    ambiguous: dict = field(default_factory=dict)
    unmapped: list = field(default_factory=list)


def resolve_rig(bone_names):
    """Canonicalize a list of bone names into a :class:`RigResolution`."""
    mapped = {}
    ambiguous = {}
    unmapped = []
    for name in bone_names:
        canonical = canonicalize(name)
        if canonical is None:
            unmapped.append(name)
            continue
        if canonical in mapped:
            ambiguous.setdefault(canonical, []).append(name)
        else:
            mapped[canonical] = name
    return RigResolution(mapped=mapped, ambiguous=ambiguous, unmapped=unmapped)


@dataclass
class BoneMap:
    """A source-rig <-> target-rig bone correspondence.

    ``pairs`` is a list of ``(source_bone, target_bone, canonical)`` for
    every canonical joint present in BOTH rigs (this is what R3 consumes).
    ``source_only``/``target_only`` are ``(bone_name, canonical)`` for
    joints resolved on one rig but absent on the other (surfaced, not
    dropped). ``source_unmapped``/``target_unmapped`` are the helper bones
    with no canonical identity on each side. ``overrides_applied`` records
    the manual ``(source_bone, target_bone)`` overrides that were merged
    in.
    """

    pairs: list = field(default_factory=list)
    source_only: list = field(default_factory=list)
    target_only: list = field(default_factory=list)
    source_unmapped: list = field(default_factory=list)
    target_unmapped: list = field(default_factory=list)
    overrides_applied: list = field(default_factory=list)

    def as_pairs(self):
        """``[(source_bone, target_bone), ...]`` -- the plain correspondence
        R3's pose transfer walks, override-adjusted, canonical order-stable."""
        return [(s, t) for (s, t, _c) in self.pairs]

    def source_to_target(self):
        """``{source_bone: target_bone}`` convenience view."""
        return {s: t for (s, t, _c) in self.pairs}


def build_bone_map(source_names, target_names, overrides=None):
    """Match ``source_names`` to ``target_names`` by canonical humanoid joint.

    ``overrides`` is an optional iterable of ``(source_bone, target_bone)``
    manual corrections (from the remap UI): each removes any auto-derived
    pair that used the same source or target bone, then -- unless
    ``target_bone`` is empty/``None`` (an explicit "leave this source
    unmapped") -- adds the forced pair. Overrides always win over
    auto-resolution, so a user can fix anything the resolver gets wrong or
    supply a pair it missed (the card's manual-override requirement).

    Returns a :class:`BoneMap`. Pair order follows the source rig's
    canonical resolution order (stable across runs).
    """
    source = resolve_rig(source_names)
    target = resolve_rig(target_names)

    pairs = []
    source_only = []
    for canonical, source_bone in source.mapped.items():
        target_bone = target.mapped.get(canonical)
        if target_bone is not None:
            pairs.append((source_bone, target_bone, canonical))
        else:
            source_only.append((source_bone, canonical))

    target_only = [
        (target_bone, canonical)
        for canonical, target_bone in target.mapped.items()
        if canonical not in source.mapped
    ]

    overrides_applied = []
    if overrides:
        forced_sources = set()
        forced_targets = set()
        forced_pairs = []
        for source_bone, target_bone in overrides:
            forced_sources.add(source_bone)
            if target_bone:
                forced_targets.add(target_bone)
                forced_pairs.append((source_bone, target_bone))
            overrides_applied.append((source_bone, target_bone))

        # Drop any auto pair colliding with a forced source or target, then
        # append the forced pairs (canonical unknown for a manual pair).
        pairs = [
            (s, t, c)
            for (s, t, c) in pairs
            if s not in forced_sources and t not in forced_targets
        ]
        for source_bone, target_bone in forced_pairs:
            pairs.append((source_bone, target_bone, None))

    return BoneMap(
        pairs=pairs,
        source_only=source_only,
        target_only=target_only,
        source_unmapped=source.unmapped,
        target_unmapped=target.unmapped,
        overrides_applied=overrides_applied,
    )


# The canonical primary-chain key set, for callers that want to assert full
# coverage (e.g. R6's regression, or a UI "primary chain fully mapped?"
# check). Central bones plus both sides of every sided joint.
PRIMARY_CHAIN = tuple(
    [CanonicalBone(joint=j) for j in CENTRAL_JOINTS]
    + [CanonicalBone(joint=j, side=s) for j in SIDED_JOINTS for s in ("L", "R")]
)


def missing_primary_bones(bone_map):
    """The :class:`CanonicalBone`\\ s in :data:`PRIMARY_CHAIN` that
    ``bone_map`` did NOT pair up -- empty when the whole primary humanoid
    chain resolved between the two rigs. Uses the auto-resolved canonical
    tags on the pairs (manual override pairs carry no canonical tag, so a
    chain completed only via overrides is reported by canonical absence,
    which is the honest, conservative answer)."""
    paired = {c for (_s, _t, c) in bone_map.pairs if c is not None}
    return [cb for cb in PRIMARY_CHAIN if cb not in paired]
