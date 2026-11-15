"""The PartSpec format, declared once.

Every item kind a spec can contain is declared here as a :class:`KindSpec`:
its fields, which of them are required, what each one means, the faces other
items may stand on, and how the item adds to or cuts the part. Everything else
is generated from these declarations (rule R8):

- the reader that turns a draft into typed items (:mod:`forge_spec.draft`);
- the JSON Schema the spec writer fills in and the guide it reads
  (:mod:`forge_spec.guide`);
- the written definition of every field, which the oracle, the compiler and
  the random-spec generator are each coded from (plan, section 4.6);
- the fixed wording the person confirms (:mod:`forge_spec.render`).

So the validator, the model's instructions and the person's view of a spec
can never disagree about what a field means.

The frame
---------
X is the part's length, Y its width and Z its height; Z is up. The first body
sits with the centre of its bottom face at the origin. Every face is named by
the direction it faces (``+z`` is a block's top), or for round items by its
end (``+end``, ``-end``) or ``side`` (and a tube's ``bore``); a pocket's floor
is its ``bottom``. Each name means one face, and each face has one name. A
standing item's face that is joined to what it stands on can't be used. A face
has two axes of its own, used to place things on it and to orient what stands
on it:

========  ======  ======
face      first   second
========  ======  ======
+z / -z   x       y
+x / -x   y       z
+y / -y   x       z
========  ======  ======

An item standing on a face rises out of it. A block, post or region has its
length along the face's first axis, its width along the second and its height
out of the face. A rib runs its length along its ``along`` axis. A tab sticks
its length out of the face, its thickness along its ``thickness_along`` axis.
A cylinder, tube, cone or boss runs its length (a boss, its height) out of the
face. A hole, slot or pocket goes into the face. A whole ball standing on a
face is centred on it; a dome stands on its flat face.

A hollowed body (one a shell item hollows) also has the inside faces of its
walls: ``inner -z`` is the inside of a block's -z wall, a tray's floor, facing
up into the hollow; ``inner side`` is the inside of a hollowed cylinder's wall.
The faces a shell leaves open can't be stood on.

Where a value may come from
---------------------------
A size may come from the brief's words, a table of standard sizes, a formula
worked out from the brief's numbers, or an assumption. A count or an angle
may come from the brief, a formula or an assumption. Anything else (a
choice, a text, a "through", a list of faces, a position "centred") comes
from the brief's words or is an assumption: :data:`SOURCES` says which, per
field type, and the reader enforces it.

A field that applies only to one choice of another field (a pocket's length
only to a rectangular pocket) says so in ``only_when``; given for the other
choice, it is a fault, never silently ignored.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "AXES",
    "AXIS_WORDS",
    "DIRECTIONS",
    "FACE_AXES",
    "KINDS",
    "MATERIAL_PHRASES",
    "MATERIAL_WORDS",
    "NON_SHAPE_WORDS",
    "NUMBER_SOURCES",
    "PRESENT",
    "STATED_SOURCES",
    "VALUE_SOURCES",
    "Category",
    "FieldSpec",
    "FieldType",
    "KindSpec",
    "kind_spec",
    "material_words",
]

AXES = ("x", "y", "z")
DIRECTIONS = ("+x", "-x", "+y", "-y", "+z", "-z")

#: The two in-face axes of every flat face named by a direction.
FACE_AXES: Mapping[str, tuple[str, str]] = {
    "+z": ("x", "y"), "-z": ("x", "y"),
    "+x": ("y", "z"), "-x": ("y", "z"),
    "+y": ("x", "z"), "-y": ("x", "z"),
}  # fmt: skip


class FieldType(str, Enum):
    """What a field holds on the wire."""

    LENGTH = "length"  # a Value with a length unit
    ANGLE = "angle"  # a Value with an angle unit
    COUNT = "count"  # a Count
    DEPTH = "depth"  # a length Value, or {"through": true, "from": ...}
    DIAMETER = "diameter"  # a length Value, or a standard fit or thread
    ON = "on"  # {"item": id, "face": face}: where the item stands or cuts in
    ITEM = "item"  # the id of another item
    CHOICE = "choice"  # {"choose": one of the choices, "from": ...}
    TEXT = "text"  # {"text": "...", "from": ...}
    DESIGNATION = (
        "designation"  # {"text": "M8x1", "from": ...}: a standard part, by name
    )
    PLACE = "place"  # where on the face; see forge_spec.draft
    EDGES = "edges"  # {"of": id, "which": ..., "where_meets": id}
    PROFILE = "profile"  # a closed outline; see forge_spec.draft
    FACES = "faces"  # {"faces": [...], "from": ...}
    COUNTERBORE = "counterbore"  # {"diameter": length, "depth": length}
    COUNTERSINK = "countersink"  # {"diameter": length, "angle": angle}


#: Where a value of each field type may come from (see the module docstring).
VALUE_SOURCES = ("words", "table", "formula", "assumed")
NUMBER_SOURCES = ("words", "formula", "assumed")
STATED_SOURCES = ("words", "assumed")

#: Words that name each axis, for checking a choice of axis against its citation.
AXIS_WORDS: Mapping[str, tuple[str, ...]] = {
    axis: (axis, f"{axis}-axis", f"{axis}axis") for axis in AXES
}

#: Words that say nothing about a part's shape: materials, colours, finishes,
#: how it is made and what it is for. An automatic run (``--auto``) may leave
#: out as "not modelled" only a part of the brief made of these (and function
#: words); anything else there might be a shape, so it is a question.
#: Words that name a material. The material is a requirement of the part
#: (``requirements.material``), recorded for the strength and print checks:
#: never left out as "not modelled".
MATERIAL_WORDS = frozenset({
    "pla", "petg", "abs", "asa", "tpu", "tpe", "nylon", "pa", "pa6", "pa12", "pc", "polycarbonate",
    "pom", "acetal", "delrin", "hips", "pva", "pp", "polypropylene", "pe", "hdpe", "resin", "plastic",
    "steel", "stainless", "aluminium", "aluminum", "alloy", "brass", "bronze", "copper", "titanium",
    "iron", "metal", "wood", "wooden", "plywood", "mdf", "acrylic",
    "ptfe", "teflon", "peek", "pei", "ultem", "pvc", "pctg", "pmma", "perspex", "plexiglass", "plexiglas", "ldpe",
    "uhmw", "uhmwpe", "rubber", "silicone", "neoprene", "zinc", "nickel", "magnesium", "ceramic", "porcelain",
    "fibreglass", "fiberglass", "cfrp", "gfrp",
})  # fmt: skip

#: Two words that name a material together, though neither does alone.
MATERIAL_PHRASES = frozenset(
    {("carbon", "fibre"), ("carbon", "fiber"), ("glass", "fibre"), ("glass", "fiber")}
)


def material_words(texts: Sequence[str]) -> frozenset[int]:
    """Which of a run of words (a brief's, in order) name a material: "PETG", "carbon fibre".

    >>> sorted(material_words(["A", "carbon", "fibre", "PETG-CF", "plate", "on", "a", "steel", "rod"]))
    [1, 2, 3, 7]
    """
    tokens = [re.sub(r"[^0-9a-z]+", " ", text.lower()).split() for text in texts]
    found = {i for i, words in enumerate(tokens) if set(words) & MATERIAL_WORDS}
    for i in range(len(tokens) - 1):
        if (
            tokens[i]
            and tokens[i + 1]
            and (tokens[i][-1], tokens[i + 1][0]) in MATERIAL_PHRASES
        ):
            found |= {i, i + 1}
    return frozenset(found)


NON_SHAPE_WORDS = MATERIAL_WORDS | frozenset({
    # what a material is made of
    "mild", "carbon", "cast", "glass", "fibre", "fiber", "filled", "cf", "gf", "material", "materials",
    "grade",
    # colours and finishes
    "black", "white", "red", "blue", "green", "yellow", "grey", "gray", "orange", "purple",
    "pink", "brown", "silver", "gold", "clear", "transparent", "translucent", "opaque", "natural",
    "colour", "color", "coloured", "colored", "finish", "finished", "polished", "anodised",
    "anodized", "painted", "matte", "matt", "glossy", "gloss", "satin", "brushed", "sanded",
    "coated", "plated", "powder", "surface",
    # how it is made
    "machined", "milled", "moulded", "molded", "injection", "printing", "printer", "fdm", "sla",
    "sls", "infill", "layer", "layers", "nozzle", "supports", "3d", "3d-printed", "cnc",
    # what it is for, and loads
    "load", "loads", "loaded", "carries", "carry", "carrying", "weight", "used", "use", "uses",
    "purpose", "application", "locating", "outdoor", "outdoors", "indoor", "indoors", "food", "safe", "heat",
    "temperature", "uv", "resistant", "strong", "stiff", "lightweight", "cheap", "durable",
    "quantity", "copies", "spare", "spares", "case",
})  # fmt: skip

#: Something an ``only_when`` names: the other field is present at all.
PRESENT = "*"


class Category(str, Enum):
    BODY = "body"  # a solid of its own; bodies are joined together
    ADD = "add"  # stands on a face and adds material
    CUT = "cut"  # goes into a face and removes material
    MODIFY = "modify"  # rounds, chamfers or hollows what is there
    REGION = "region"  # a freeform region given by constraints


@dataclass(frozen=True)
class FieldSpec:
    """One field of an item kind.

    ``only_when`` is ``(other field, its choice)``, or ``(other field,
    PRESENT)``: the field applies only then; given otherwise, it is a fault.
    ``required`` holds only where the field applies. ``synonyms`` gives, for a
    choice, the brief's words that name each option: a choice citing words
    that name another option and not its own is a misreading.
    """

    name: str
    type: FieldType
    meaning: str
    required: bool = True
    choices: tuple[str, ...] = ()
    only_when: tuple[str, str] | None = None
    synonyms: Mapping[str, tuple[str, ...]] | None = None

    def __post_init__(self) -> None:
        if self.synonyms is not None and set(self.synonyms) != set(self.choices):
            raise ValueError(f"{self.name}: synonyms must name every choice")


@dataclass(frozen=True)
class KindSpec:
    """One kind of item: its fields, its faces, what it does to the part."""

    kind: str
    category: Category
    summary: str
    fields: tuple[FieldSpec, ...]
    #: The faces other items may stand on or cut into (and a shell may open).
    faces: tuple[str, ...] = ()
    edges: tuple[str, ...] = ()
    #: Whether a count of more than one makes sense ("4 holes"; not "2 shells").
    countable: bool = False
    #: The verification class of the item's own surfaces (plan, section 4.5).
    verification: str = "exact"

    def field(self, name: str) -> FieldSpec:
        for spec in self.fields:
            if spec.name == name:
                return spec
        raise KeyError(f"{self.kind} has no field {name!r}")

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)


def _f(name: str, type_: FieldType, meaning: str, *, required: bool = True,
       choices: tuple[str, ...] = (), only_when: tuple[str, str] | None = None,
       synonyms: Mapping[str, tuple[str, ...]] | None = None) -> FieldSpec:  # fmt: skip
    if type_ is FieldType.CHOICE and choices == AXES and synonyms is None:
        synonyms = AXIS_WORDS
    return FieldSpec(name, type_, meaning, required, choices, only_when, synonyms)


L, A, C = FieldType.LENGTH, FieldType.ANGLE, FieldType.COUNT
INNER_BOX_FACES = tuple(f"inner {d}" for d in DIRECTIONS)
INNER_ROUND_FACES = ("inner +end", "inner -end", "inner side")
BLOCK_FACES = (*DIRECTIONS, *INNER_BOX_FACES)
ROUND_FACES = ("+end", "-end", "side")
BOX_EDGES = ("vertical", "top", "bottom", "all", "joint")
ROUND_EDGES = ("top", "bottom", "both", "joint")
STANDING_BOX_EDGES = ("vertical", "top", "joint")

_ON_BODY = _f(
    "on", FieldType.ON,
    "the face of an earlier body this body stands on; leave it out for the first "
    "body, which sits on the origin",
    required=False,
)  # fmt: skip
_PLACE = _f("place", FieldType.PLACE, "where on the face it goes", required=False)
_BODY_PLACE = _f(
    "place", FieldType.PLACE,
    "where on that face it stands; the first body takes none",
    required=False, only_when=("on", PRESENT),
)  # fmt: skip
_AXIS = _f(
    "axis", FieldType.CHOICE,
    "the frame axis it runs along; a body standing on a face runs out of that "
    "face instead, and leaves this out",
    required=False, choices=AXES,
)  # fmt: skip
_COUNT = _f(
    "count", C,
    "how many there are in the whole part; must equal what the placement makes",
    required=False,
)  # fmt: skip
_ON = _f("on", FieldType.ON, "the face it stands on or cuts into")

KINDS: Mapping[str, KindSpec] = {
    spec.kind: spec
    for spec in (
        KindSpec(
            "block",
            Category.BODY,
            "a rectangular block, plate or bar",
            (
                _f("length", L, "size along X (or the face's first axis)"),
                _f("width", L, "size along Y (or the face's second axis)"),
                _f("height", L, "size along Z (or out of the face it stands on)"),
                _ON_BODY,
                _BODY_PLACE,
            ),
            faces=BLOCK_FACES,
            edges=BOX_EDGES,
        ),
        KindSpec(
            "cylinder",
            Category.BODY,
            "a solid round rod, disc or puck",
            (
                _f("diameter", L, "outside diameter"),
                _f("length", L, "length along its axis"),
                _AXIS,
                _ON_BODY,
                _BODY_PLACE,
            ),
            faces=(*ROUND_FACES, *INNER_ROUND_FACES),
            edges=ROUND_EDGES,
        ),
        KindSpec(
            "tube",
            Category.BODY,
            "a hollow round tube, ring or bushing",
            (
                _f("outer_diameter", L, "outside diameter"),
                _f(
                    "inner_diameter",
                    L,
                    "diameter of the bore, which goes all the way through",
                ),
                _f("length", L, "length along its axis"),
                _AXIS,
                _ON_BODY,
                _BODY_PLACE,
            ),
            faces=(*ROUND_FACES, "bore"),
            edges=("top", "bottom", "both", "outer", "bore", "joint"),
        ),
        KindSpec(
            "sphere",
            Category.BODY,
            "a ball, or half of one (a dome) with its flat side down",
            (
                _f("diameter", L, "diameter of the ball"),
                _f(
                    "portion",
                    FieldType.CHOICE,
                    "the whole ball, or the upper half (a dome)",
                    choices=("whole", "upper_half"),
                    synonyms={
                        "whole": ("ball", "sphere", "whole", "globe"),
                        "upper_half": (
                            "half",
                            "dome",
                            "hemisphere",
                            "hemispherical",
                            "half-ball",
                            "half-sphere",
                            "domed",
                        ),
                    },
                ),
                _ON_BODY,
                _BODY_PLACE,
            ),
            faces=("surface", "-end"),
            edges=("bottom", "joint"),
            verification="exact",
        ),
        KindSpec(
            "cone",
            Category.BODY,
            "a cone or truncated cone",
            (
                _f("base_diameter", L, "diameter at its base (the -end)"),
                _f("top_diameter", L, "diameter at its top (the +end); 0 for a point"),
                _f("length", L, "length along its axis"),
                _AXIS,
                _ON_BODY,
                _BODY_PLACE,
            ),
            faces=ROUND_FACES,
            edges=ROUND_EDGES,
        ),
        KindSpec(
            "extrusion",
            Category.BODY,
            "a flat outline pushed straight along an axis",
            (
                _f(
                    "profile",
                    FieldType.PROFILE,
                    "the outline, in the plane across the axis",
                ),
                _f("length", L, "how far the outline is pushed"),
                _AXIS,
                _ON_BODY,
                _BODY_PLACE,
            ),
            faces=("+end", "-end", "side"),
            edges=("vertical", "top", "bottom", "all"),
        ),
        KindSpec(
            "revolution",
            Category.BODY,
            "an outline turned about an axis (knobs, pulleys)",
            (
                _f(
                    "profile",
                    FieldType.PROFILE,
                    "the half outline: first coordinate the radius, second the height",
                ),
                _AXIS,
                _ON_BODY,
                _BODY_PLACE,
            ),
            faces=("+end", "-end", "side"),
            edges=("top", "bottom"),
        ),
        KindSpec(
            "hole",
            Category.CUT,
            "a round hole",
            (
                _ON,
                _PLACE,
                _f(
                    "diameter",
                    FieldType.DIAMETER,
                    "the hole's diameter, or a standard fit or thread",
                ),
                _f(
                    "depth",
                    FieldType.DEPTH,
                    "how deep, or right through the material under the face",
                ),
                _f(
                    "counterbore",
                    FieldType.COUNTERBORE,
                    "a wider, flat-bottomed recess at the top",
                    required=False,
                ),
                _f(
                    "countersink",
                    FieldType.COUNTERSINK,
                    "a cone-shaped recess at the top",
                    required=False,
                ),
                _COUNT,
            ),
            faces=(),
            edges=("top",),
            countable=True,
        ),
        KindSpec(
            "slot",
            Category.CUT,
            "a straight slot",
            (
                _ON,
                _PLACE,
                _f("width", L, "width across the slot"),
                _f("length", L, "overall length, end to end"),
                _f(
                    "along",
                    FieldType.CHOICE,
                    "the frame axis the slot runs along",
                    choices=AXES,
                ),
                _f(
                    "ends",
                    FieldType.CHOICE,
                    "round or square ends",
                    choices=("round", "square"),
                    synonyms={
                        "round": (
                            "round",
                            "rounded",
                            "radiused",
                            "semicircular",
                            "full-round",
                            "obround",
                        ),
                        "square": ("square", "squared", "rectangular"),
                    },
                ),
                _f(
                    "depth",
                    FieldType.DEPTH,
                    "how deep, or right through the material under the face",
                ),
                _COUNT,
            ),
            faces=(),
            edges=("top",),
            countable=True,
        ),
        KindSpec(
            "pocket",
            Category.CUT,
            "a flat-bottomed recess or cut-out, rectangular or round",
            (
                _ON,
                _PLACE,
                _f(
                    "shape",
                    FieldType.CHOICE,
                    "rectangle or circle",
                    choices=("rectangle", "circle"),
                    synonyms={
                        "rectangle": ("rectangle", "rectangular", "square", "oblong"),
                        "circle": ("circle", "circular", "round", "cylindrical"),
                    },
                ),
                _f(
                    "length",
                    L,
                    "size along the face's first axis",
                    only_when=("shape", "rectangle"),
                ),
                _f(
                    "width",
                    L,
                    "size along the face's second axis",
                    only_when=("shape", "rectangle"),
                ),
                _f("diameter", L, "its diameter", only_when=("shape", "circle")),
                _f(
                    "corner_radius",
                    L,
                    "rounding of its corners, seen from above",
                    required=False,
                    only_when=("shape", "rectangle"),
                ),
                _f(
                    "depth",
                    FieldType.DEPTH,
                    "how deep, or right through the material under the face",
                ),
                _COUNT,
            ),
            faces=("bottom",),
            edges=("top", "bottom"),
            countable=True,
        ),
        KindSpec(
            "boss",
            Category.ADD,
            "a round post or boss standing on a face",
            (
                _ON,
                _PLACE,
                _f("diameter", L, "outside diameter"),
                _f("height", L, "height out of the face"),
                _COUNT,
            ),
            faces=("+end", "side"),
            edges=("top", "joint"),
            countable=True,
        ),
        KindSpec(
            "post",
            Category.ADD,
            "a rectangular post, block or wall standing on a face",
            (
                _ON,
                _PLACE,
                _f("length", L, "size along the face's first axis"),
                _f("width", L, "size along the face's second axis"),
                _f("height", L, "height out of the face"),
                _COUNT,
            ),
            faces=DIRECTIONS,
            edges=STANDING_BOX_EDGES,
            countable=True,
        ),
        KindSpec(
            "tab",
            Category.ADD,
            "a flat tab or lug sticking out of a face, square or round ended",
            (
                _ON,
                _PLACE,
                _f("length", L, "how far it sticks out of the face"),
                _f("width", L, "its width across"),
                _f("thickness", L, "its thickness"),
                _f(
                    "thickness_along",
                    FieldType.CHOICE,
                    "the frame axis its thickness runs along",
                    choices=AXES,
                ),
                _f(
                    "end",
                    FieldType.CHOICE,
                    "square, or fully rounded (a semicircle)",
                    choices=("square", "round"),
                    synonyms={
                        "square": ("square", "squared", "flat"),
                        "round": (
                            "round",
                            "rounded",
                            "radiused",
                            "semicircular",
                            "full-round",
                        ),
                    },
                ),
                _COUNT,
            ),
            faces=DIRECTIONS,
            edges=STANDING_BOX_EDGES,
            countable=True,
        ),
        KindSpec(
            "rib",
            Category.ADD,
            "a thin straight rib or wall standing on a face",
            (
                _ON,
                _PLACE,
                _f("length", L, "length along the face"),
                _f("thickness", L, "thickness across"),
                _f("height", L, "height out of the face"),
                _f(
                    "along",
                    FieldType.CHOICE,
                    "the frame axis the rib runs along",
                    choices=AXES,
                ),
                _COUNT,
            ),
            faces=DIRECTIONS,
            edges=STANDING_BOX_EDGES,
            countable=True,
        ),
        KindSpec(
            "fillet",
            Category.MODIFY,
            "rounds edges",
            (
                _f("edges", FieldType.EDGES, "which edges"),
                _f("radius", L, "radius of the rounding"),
            ),
            verification="bounded",
        ),
        KindSpec(
            "chamfer",
            Category.MODIFY,
            "bevels edges at 45 degrees",
            (
                _f("edges", FieldType.EDGES, "which edges"),
                _f("size", L, "how far the bevel cuts back along each face"),
            ),
            verification="bounded",
        ),
        KindSpec(
            "shell",
            Category.MODIFY,
            "hollows a body, leaving walls of a thickness",
            (
                _f("of", FieldType.ITEM, "the body to hollow"),
                _f("thickness", L, "wall thickness"),
                _f(
                    "open",
                    FieldType.FACES,
                    "the faces left open; none for a sealed hollow",
                ),
                _f(
                    "floor",
                    L,
                    "a different thickness for the face opposite the opening",
                    required=False,
                ),
            ),
            verification="exact",
        ),
        KindSpec(
            "text",
            Category.CUT,
            "letters engraved into or embossed on a face",
            (
                _ON,
                _PLACE,
                _f(
                    "text",
                    FieldType.TEXT,
                    "the letters, exactly as the brief gives them",
                ),
                _f("height", L, "height of a capital letter"),
                _f("depth", L, "how deep they are cut, or how high they stand"),
                _f(
                    "mode",
                    FieldType.CHOICE,
                    "engraved (cut in) or embossed (raised)",
                    choices=("engrave", "emboss"),
                    synonyms={
                        "engrave": (
                            "engrave",
                            "engraved",
                            "engraving",
                            "etched",
                            "cut",
                            "recessed",
                            "debossed",
                            "sunk",
                            "incised",
                        ),
                        "emboss": ("emboss", "embossed", "raised", "relief", "proud"),
                    },
                ),
            ),
            verification="exact",
        ),
        KindSpec(
            "thread",
            Category.MODIFY,
            "an outside screw thread on a round body or boss",
            (
                _f("of", FieldType.ITEM, "the cylinder or boss to thread"),
                _f(
                    "designation",
                    FieldType.DESIGNATION,
                    "the thread, such as M8 or M8x1",
                ),
                _f("length", L, "threaded length from the free end", required=False),
                _f(
                    "hand",
                    FieldType.CHOICE,
                    "right or left handed",
                    choices=("right", "left"),
                    synonyms={
                        "right": ("right", "right-hand", "right-handed", "rh"),
                        "left": ("left", "left-hand", "left-handed", "lh"),
                    },
                ),
            ),
            verification="bounded",
        ),
        KindSpec(
            "region",
            Category.REGION,
            "a freeform shape given by constraints, designed later",
            (
                _ON,
                _PLACE,
                _f("length", L, "envelope size along the face's first axis"),
                _f("width", L, "envelope size along the face's second axis"),
                _f("height", L, "envelope size out of the face"),
                _f("min_wall", L, "no wall thinner than this", required=False),
                _f(
                    "describe",
                    FieldType.TEXT,
                    "what the shape is for, in the brief's words",
                ),
            ),
            verification="constrained",
        ),
    )
}


def kind_spec(kind: str) -> KindSpec:
    """The declaration of one kind, or a ``KeyError`` naming the known kinds."""
    try:
        return KINDS[kind]
    except KeyError:
        raise KeyError(
            f"unknown kind {kind!r}; known kinds: {', '.join(KINDS)}"
        ) from None
