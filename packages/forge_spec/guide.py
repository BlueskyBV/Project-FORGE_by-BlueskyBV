"""The spec writer's guide: what it is told, and the JSON Schema it answers with.

Both are generated from the one declaration of the format: the item kinds of
:mod:`forge_spec.schema`, with the patterns and fits of :mod:`forge_spec.draft`
and the sources of :mod:`forge_spec.values`. So the writer's instructions,
the tool schema it fills in, the reader that checks its answer and the
wording the person confirms can't disagree about what a field means (rule
R8).

Nothing here decides anything. The schema makes a well-formed first answer
likely; the reader and the spec checks (:func:`forge_spec.checks.check_draft`)
are the contract, and a draft that passes the schema can still be refused
there. What must never happen is a draft the schema can't express: every
draft the reader takes in its one written form, the schema takes (a test
holds it to that, over generated drafts of every kind and field). The reader
also forgives a few other spellings of the same content that the schema
doesn't teach: a unit's long name ("millimetre"), an optional field given as
null, an empty grade on a fit that has none, an empty list of edge words,
text padded with spaces, and a tolerance's minus written negative (with a
note). They read as the one form would, so they change nothing that is
checked.

- :func:`draft_schema`: the JSON Schema of a draft (draft 2020-12).
- :func:`instructions`: the system prompt of the spec writer, for a person's
  run or an automatic one.
- :func:`brief_message`: the brief, numbered, as the writer is given it.

What to fix after a check is the role's repair message
(:class:`forge_roles.spec_writer.SpecWriter`), built from the same report.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Mapping
from typing import Any

from forge_units import known_units, parse_unit
from forge_units.dimension import LENGTH

from . import schema as _schema_module
from .draft import (
    FITS,
    GRADES,
    PATTERN_ANGLES,
    PATTERN_FIELDS,
    PATTERN_REQUIRED,
)
from .items.words.pattern import PATTERN_WORDS
from .problems import MAX_NAME, MAX_REASON
from .schema import (
    AXES,
    KINDS,
    MATERIAL_WORDS,
    NON_SHAPE_WORDS,
    NUMBER_SOURCES,
    PRESENT,
    STATED_SOURCES,
    VALUE_SOURCES,
    FieldSpec,
    FieldType,
    KindSpec,
)
from .values import MAX_COUNT
from .versions import CURRENT, written
from .words import NumberedBrief, number_words

__all__ = [
    "EXAMPLE_BRIEF",
    "EXAMPLE_DRAFT",
    "GUIDE_VERSION",
    "brief_message",
    "draft_schema",
    "instructions",
]

#: Changes whenever what the writer is told changes, so a recorded answer is
#: never replayed against instructions it wasn't written for.
GUIDE_VERSION = 6

#: The worked example the writer is shown: a brief written for it (not from
#: the corpus or a blind set), and a draft the checks pass with no problem,
#: which a test holds it to.
EXAMPLE_BRIEF = (
    "A PETG bracket plate 80 mm long, 30 mm wide and 6 mm thick. Two 5 mm holes pass through it, "
    "60 mm apart along its length. Its vertical edges are rounded to 3 mm. It holds a small sensor."
)
EXAMPLE_DRAFT: Mapping[str, Any] = {
    "schema_version": written(CURRENT),
    "name": "bracket plate",
    "items": [
        {"id": "plate", "kind": "block", "words": [2, 3],
         "length": {"value": 80, "unit": "mm", "from": {"words": [4, 5, 6]}},
         "width": {"value": 30, "unit": "mm", "from": {"words": [7, 8, 9]}},
         "height": {"value": 6, "unit": "mm", "from": {"words": [11, 12, 13]}}},
        {"id": "holes", "kind": "hole", "words": [17, 24, 25, 26],
         "on": {"item": "plate", "face": "+z"},
         "diameter": {"value": 5, "unit": "mm", "from": {"words": [15, 16]}},
         "depth": {"through": True, "from": {"words": [18, 19]}},
         "count": {"count": 2, "from": {"words": [14]}},
         "place": {"x": {"centred": {"assumed": "the brief doesn't say where along the length"}},
                   "y": {"centred": {"assumed": "the brief doesn't place them across the width"}},
                   "pattern": {"row": {"axis": {"choose": "x", "from": {"assumed": "its length runs along X"}},
                                       "pitch": {"value": 60, "unit": "mm", "from": {"words": [21, 22, 23]}},
                                       "count": {"count": 2, "from": {"words": [14]}}}}}},
        {"id": "corners", "kind": "fillet", "words": [27, 28, 29, 30, 31],
         "edges": {"of": "plate", "which": "vertical", "words": [28, 29]},
         "radius": {"value": 3, "unit": "mm", "from": {"words": [33, 34]}}},
    ],
    "silent": [{"sentence": 3, "reason": "it says what the part is for"}],
    "requirements": {"material": {"text": "PETG", "from": {"words": [1]}}},
}  # fmt: skip

_ID_PATTERN = "^[a-z][a-z0-9_]{0,39}$"
_ANGLE_UNITS = ("deg", "rad", "rev", "arcmin", "arcsec")


def _length_units() -> list[str]:
    return sorted(u for u in known_units() if parse_unit(u).dimension == LENGTH)


# ----------------------------------------------------------------------
# The JSON Schema
# ----------------------------------------------------------------------
def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/$defs/{name}"}


def _obj(
    properties: Mapping[str, Any], required: tuple[str, ...] = (), description: str = ""
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
        "additionalProperties": False,
    }
    if required:
        out["required"] = list(required)
    if description:
        out["description"] = description
    return out


def _sources(allow: tuple[str, ...]) -> dict[str, Any]:
    return {"oneOf": [_ref(f"from_{kind}") for kind in allow]}


def _defs() -> dict[str, Any]:
    words = {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1,
             "description": "word numbers of the numbered brief, the [n] before each word"}  # fmt: skip
    reason = {"type": "string", "minLength": 1, "maxLength": MAX_REASON}
    defs: dict[str, Any] = {
        "words": words,
        "id": {
            "type": "string",
            "pattern": _ID_PATTERN,
            "description": "the id of an item of this draft",
        },
        "from_words": _obj(
            {"words": _ref("words")}, ("words",), "the brief says it, in these words"
        ),
        "from_table": _obj(
            {
                "table": {"type": "string", "description": _TABLE_FORMS},
                "words": _ref("words"),
            },
            ("table", "words"),
            "a standard table's entry for the part these words name",
        ),
        "from_formula": _obj(
            {
                "formula": {"type": "string", "maxLength": MAX_REASON},
                "words": _ref("words"),
            },
            ("formula", "words"),
            "worked out from the numbers of these words",
        ),
        "from_assumed": _obj(
            {"assumed": reason}, ("assumed",), "not in the brief: your choice, and why"
        ),
        "tolerance": _obj(
            {
                "plus": {"type": "number", "minimum": 0},
                "minus": {"type": "number", "minimum": 0},
            },
            (),
            "only as the brief states it, right next to the value",
        ),
        "length": _obj(
            {
                "value": {"type": "number", "minimum": 0},
                "unit": {"enum": _length_units()},
                "tolerance": _ref("tolerance"),
                "from": _sources(VALUE_SOURCES),
            },
            ("value", "unit", "from"),
            "a size",
        ),
        "signed_length": _obj(
            {
                "value": {"type": "number"},
                "unit": {"enum": _length_units()},
                "tolerance": _ref("tolerance"),
                "from": _sources(VALUE_SOURCES),
            },
            ("value", "unit", "from"),
            "a distance that may be negative",
        ),
        "angle": _obj(
            {
                "value": {"type": "number"},
                "unit": {"enum": list(_ANGLE_UNITS)},
                "tolerance": _ref("tolerance"),
                "from": _sources(NUMBER_SOURCES),
            },
            ("value", "unit", "from"),
            "an angle, with its unit",
        ),
        "count": _obj(
            {
                "count": {"type": "integer", "minimum": 0, "maximum": MAX_COUNT},
                "from": _sources(NUMBER_SOURCES),
            },
            ("count", "from"),
            "a number of things, with no unit",
        ),
        "stated": _sources(STATED_SOURCES),
        "through": _obj(
            {"through": {"const": True}, "from": _ref("stated")},
            ("through", "from"),
            "right through the material under the face: out of its far side all across the mouth",
        ),
        "depth": {"oneOf": [_ref("length"), _ref("through")]},
        "fit": {
            "oneOf": [
                _obj(
                    {
                        "fit": {"const": fit},
                        "for": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 40,
                            "description": "the part it fits: M4, M8x1 (a fine pitch), 608",
                        },
                        **(
                            {"grade": {"enum": [g for g in GRADES[fit] if g]}}
                            if any(GRADES[fit])
                            else {}
                        ),
                        "from": _ref("stated"),
                    },
                    ("fit", "for", "from"),
                )
                for fit in sorted(FITS)
            ]
        },
        "diameter": {"oneOf": [_ref("length"), _ref("fit")]},
        "on": _obj(
            {
                "item": _ref("id"),
                "face": {
                    "type": "string",
                    "description": "a face name of that item's kind",
                },
            },
            ("item", "face"),
        ),
        "text": _obj(
            {"text": {"type": "string", "minLength": 1}, "from": _ref("stated")},
            ("text", "from"),
        ),
        "edges": _obj(
            {
                "of": _ref("id"),
                "which": {"enum": _all_edges()},
                "where_meets": _ref("id"),
                "words": _ref("words"),
            },
            ("of", "which"),
            "which edges; where_meets only for a joint",
        ),
        "point": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        },
        "profile": _obj(
            {
                "start": _ref("point"),
                "segments": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "oneOf": [
                            _obj({"line_to": _ref("point")}, ("line_to",)),
                            _obj(
                                {
                                    "arc_to": _ref("point"),
                                    "centre": _ref("point"),
                                    "clockwise": {"type": "boolean"},
                                },
                                ("arc_to", "centre"),
                            ),
                        ]
                    },
                },
                "unit": {"const": "mm"},
                "from": _ref("stated"),
            },
            ("start", "segments", "from"),
            "a closed outline in mm: the last segment ends at the start",
        ),
        "faces": _obj(
            {
                "faces": {
                    "type": "array",
                    "items": {"type": "string"},
                    "uniqueItems": True,
                },
                "from": _ref("stated"),
            },
            ("faces", "from"),
        ),
        "counterbore": _obj(
            {"diameter": _ref("length"), "depth": _ref("length")}, ("diameter", "depth")
        ),
        "countersink": _obj(
            {"diameter": _ref("length"), "angle": _ref("angle")}, ("diameter", "angle")
        ),
        "pattern": {"oneOf": [_pattern_schema(kind) for kind in PATTERN_FIELDS]},
        "concentric": _obj(
            {"item": _ref("id"), "from": _ref("stated")}, ("item", "from")
        ),
        "place": _obj(
            {
                **{axis: _ref(f"position_{axis}") for axis in AXES},
                "angle": _ref("angle"),
                "turn": _ref("angle"),
                "pattern": _ref("pattern"),
                "concentric": _ref("concentric"),
            },
            (),
            "where on the face; along an axis it doesn't give, an item is centred (an assumption)",
        ),
    }
    for axis in AXES:
        defs[f"position_{axis}"] = {"oneOf": [
            _obj({"centred": _ref("stated")}, ("centred",)),
            _obj({"offset": _ref("signed_length")}, ("offset",), "from the face's centre to the item's"),
            _obj({"side": {"enum": [f"+{axis}", f"-{axis}"]}, "distance": _ref("length"),
                  "to": {"enum": ["centre", "edge"]}}, ("side", "distance"),
                 "from that edge of the face to the item's centre, or to its near edge"),
        ]}  # fmt: skip
    return defs


def _pattern_schema(kind: str) -> dict[str, Any]:
    values, counts, needs_axis = PATTERN_FIELDS[kind]
    properties: dict[str, Any] = {
        name: _ref("angle") if name in PATTERN_ANGLES else _ref("length")
        for name in values
    }
    properties.update({name: _ref("count") for name in counts})
    required = list(PATTERN_REQUIRED.get(kind, ()))
    if needs_axis:
        properties["axis"] = _choice_schema(AXES)
        required.append("axis")
    return _obj(
        {kind: _obj(properties, tuple(required))}, (kind,), PATTERN_WORDS[kind].meaning
    )


def _choice_schema(choices: tuple[str, ...]) -> dict[str, Any]:
    return _obj(
        {"choose": {"enum": list(choices)}, "from": _ref("stated")}, ("choose", "from")
    )


_FIELD_DEFS: Mapping[FieldType, str] = {
    FieldType.LENGTH: "length",
    FieldType.ANGLE: "angle",
    FieldType.COUNT: "count",
    FieldType.DEPTH: "depth",
    FieldType.DIAMETER: "diameter",
    FieldType.ON: "on",
    FieldType.ITEM: "id",
    FieldType.TEXT: "text",
    FieldType.DESIGNATION: "text",
    FieldType.PLACE: "place",
    FieldType.EDGES: "edges",
    FieldType.PROFILE: "profile",
    FieldType.FACES: "faces",
    FieldType.COUNTERBORE: "counterbore",
    FieldType.COUNTERSINK: "countersink",
}


def _field_schema(spec: FieldSpec) -> dict[str, Any]:
    if spec.type is FieldType.CHOICE:
        out = _choice_schema(spec.choices)
    else:
        out = {"allOf": [_ref(_FIELD_DEFS[spec.type])]}
    out["description"] = spec.meaning + _when(spec)
    return out


def _when(spec: FieldSpec) -> str:
    if spec.only_when is None:
        return ""
    other, when = spec.only_when
    return (
        f" (only when it has an {other})"
        if when == PRESENT
        else f" (only when its {other} is {when})"
    )


def _item_schema(spec: KindSpec) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": _ref("id"),
        "kind": {"const": spec.kind},
        "words": {
            "allOf": [_ref("words")],
            "description": "the words this item comes from",
        },
    }
    properties.update({f.name: _field_schema(f) for f in spec.fields})
    required = (
        "id",
        "kind",
        "words",
        *(f.name for f in spec.fields if f.required and f.only_when is None),
    )
    return _obj(properties, required, spec.summary)


def _all_edges() -> list[str]:
    return sorted({edge for spec in KINDS.values() for edge in spec.edges})


@functools.cache
def _draft_schema_text() -> str:
    body = _obj({
        "schema_version": {"const": written(CURRENT)},
        "name": {"type": "string", "minLength": 1, "maxLength": MAX_NAME, "description": "a short name for the part"},
        "items": {"type": "array", "minItems": 1, "items": {"oneOf": [_item_schema(s) for s in KINDS.values()]}},
        "not_modelled": {"type": "array", "items": _obj(
            {"words": _ref("words"), "reason": {"type": "string", "minLength": 1, "maxLength": MAX_REASON}},
            ("words", "reason"), "what the brief says that the part won't have, and why")},
        "silent": {"type": "array", "items": _obj(
            {"sentence": {"type": "integer", "minimum": 0},
             "reason": {"type": "string", "minLength": 1, "maxLength": MAX_REASON}},
            ("sentence", "reason"), "a sentence that says nothing about the shape, and why")},
        "requirements": _obj({"material": _ref("text")}, (), "what the part must be beyond its shape"),
    }, ("schema_version", "name", "items"), "a part spec drafted from a brief")  # fmt: skip
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **body,
        "$defs": _defs(),
    }
    return json.dumps(document, sort_keys=True, ensure_ascii=False)


def draft_schema() -> dict[str, Any]:
    """The JSON Schema of a draft: a fresh copy each call, the same every time."""
    loaded: dict[str, Any] = json.loads(_draft_schema_text())
    return loaded


# ----------------------------------------------------------------------
# The instructions
# ----------------------------------------------------------------------
_TABLE_FORMS = (
    "clearance:M4 (or clearance:M4:fine, :normal, :coarse), tapped:M4, tapped:M8x1 (a fine pitch), "
    "bearing:608:outer, bearing:608:width or bearing:608:bore"
)

_EDGE_MEANINGS: Mapping[str, str] = {
    "top": "round the face it rises to (a block's +z as the first body; a round body's +end)",
    "bottom": "round its base, as outside edges (where it stands on a face, only where it overhangs; the corner it "
    "is joined by is its joint)",
    "both": "round both ends",
    "vertical": "the edges running up its sides",
    "all": "every edge",
    "outer": "a tube's outside edges, at both ends",
    "bore": "a tube's bore edges, at both ends",
    "joint": "the inside corner where it meets the item in where_meets (one stands on the other)",
}


def _frame() -> str:
    """The frame, taken from the schema module's own description of it."""
    doc = _schema_module.__doc__ or ""
    start = doc.index("The frame\n---------\n") + len("The frame\n---------\n")
    end = doc.index("Where a value may come from")
    text = doc[start:end].strip()
    return text.replace("``", "")


def _type_name(spec: FieldSpec) -> str:
    if spec.type is FieldType.CHOICE:
        return "choice of " + " | ".join(spec.choices)
    return {
        FieldType.LENGTH: "size",
        FieldType.ANGLE: "angle",
        FieldType.COUNT: "count",
        FieldType.DEPTH: "size or through",
        FieldType.DIAMETER: "size or standard fit",
        FieldType.ON: "face",
        FieldType.ITEM: "item id",
        FieldType.TEXT: "text",
        FieldType.DESIGNATION: "standard part",
        FieldType.PLACE: "place",
        FieldType.EDGES: "edges",
        FieldType.PROFILE: "outline",
        FieldType.FACES: "faces",
        FieldType.COUNTERBORE: "counterbore",
        FieldType.COUNTERSINK: "countersink",
    }[spec.type]


def _kinds() -> str:
    blocks = []
    for spec in KINDS.values():
        lines = [f"### {spec.kind} ({spec.category.value}): {spec.summary}"]
        for field in spec.fields:
            need = "required" if field.required else "optional"
            when = _when(field).strip()[1:-1]  # "only when its shape is rectangle"
            lines.append(
                f"- {field.name} ({_type_name(field)}, {need}{', ' + when if when else ''}): {field.meaning}"
            )
        if spec.faces:
            lines.append(f"- faces: {', '.join(spec.faces)}")
        if spec.edges:
            lines.append(
                f"- edges it can have rounded or chamfered: {', '.join(spec.edges)}"
            )
        if spec.countable:
            lines.append(
                "- may have many copies (a count, and a pattern to place them)"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _patterns() -> str:
    lines = []
    for kind, (values, counts, needs_axis) in PATTERN_FIELDS.items():
        given = [*values, *counts, *(["axis"] if needs_axis else [])]
        lines.append(
            f"- {kind}: {PATTERN_WORDS[kind].meaning}. Fields: {', '.join(given)}."
        )
    return "\n".join(lines)


@functools.cache
def instructions(*, strict: bool = False) -> str:
    """The spec writer's system prompt; ``strict`` adds the rules of an automatic run (--auto)."""
    edges = "\n".join(f"- {name}: {_EDGE_MEANINGS[name]}" for name in _all_edges())
    text = _INSTRUCTIONS.format(
        frame=_frame(), kinds=_kinds(), patterns=_patterns(), edges=edges, tables=_TABLE_FORMS,
        max_reason=MAX_REASON, length_units=", ".join(_length_units()), angle_units=", ".join(_ANGLE_UNITS),
        example_brief=number_words(EXAMPLE_BRIEF).for_the_model(),
        example_draft=json.dumps(EXAMPLE_DRAFT, ensure_ascii=False), version=written(CURRENT),
    )  # fmt: skip
    if strict:
        text += _AUTOMATIC.format(
            not_shapes=", ".join(sorted(NON_SHAPE_WORDS - MATERIAL_WORDS))
        )
    return text


_INSTRUCTIONS = """\
You are Forge's spec writer. A person describes a part in a brief; you turn \
the brief into a part spec: typed items (bodies, holes, pockets, roundings) \
that Forge builds exactly, after the person confirms them. You decide nothing \
the brief doesn't say without saying so: every value either comes from the \
brief's words, which you cite, or is an assumption with its reason, which the \
person sees first.

Code checks everything you write against the brief, so write only what you \
can stand behind. A value that doesn't follow from the words it cites, a \
number or sentence of the brief nothing uses, an item that doesn't fit where \
you put it: each comes back to you to fix, or goes to the person as a \
question. Don't guess to make a check pass. If the brief contradicts itself \
or can't be built, write what it says: Forge will ask the person.

## The brief

You get the brief one sentence per line, every word numbered: \
"S0: [0]A [1]plate [2]60 [3]mm [4]long". Cite words by those numbers only. \
Sentences that start "Answer about" or "Note from the person:" come after \
the brief: they are the person's answers to earlier questions. They say what \
the brief left open, and win over it. Follow them, and cite them as you cite \
the brief. Where one replaces something the brief says (a size, a count, the \
material), list the brief's words it replaces in not_modelled, with the \
reason "replaced by the person's answer". Every number of a note is used or listed, \
like the brief's own.

## Where every value comes from

Every value has a "from":
- {{"words": [2, 3, 4]}}: the brief says it, in those words. Cite the words of \
that number, its unit and what it measures ("60 mm long" is [2, 3, 4]), and \
never the words of another number. A number written over several words \
("1 1/2 in", "twenty four") is cited whole. Units convert \
("2 in" is 50.8 mm), but write the value in the brief's own unit.
- {{"table": "...", "words": [...]}}: a standard size, from Forge's tables: \
{tables}. Cite the words that name the part ("M4", "M8 x 1"), and nothing \
else; a pitch the brief gives must be in the name.
- {{"formula": "40 mm - 5 mm", "words": [...]}}: worked out from the brief's \
numbers. Write each number with its unit as the brief gives it, use each \
number of the cited words once, and only + - * / ** ( ) and sqrt, hypot, \
sin, cos, tan, asin, acos, atan, atan2. The one number a formula may add is \
a single 2 that halves, doubles or squares (a radius from a diameter). No \
comments, one line.
- {{"assumed": "why"}}: the brief doesn't say, so you chose. Say why in a few \
words (at most {max_reason} characters); the person reads it first. Assume \
only what a part needs and the brief leaves open: a hole goes through a \
mounting plate; a disc lies flat.

A size has a unit: {length_units}. An angle has one too: {angle_units}. A \
count has none. A tolerance ({{"plus": 0.1, "minus": 0.1}}) is given only \
where the brief writes one right next to the value ("10 mm \u00b10.1"), cited \
with it.

A choice ({{"choose": "round", "from": ...}}) cites the words that name it \
("round-ended"), or is assumed. Words that deny it ("not rounded") rule it \
out. A text (engraved letters, a description) is the brief's characters \
exactly, punctuation and all: a quotation is taken whole, without its quote \
marks. A standard part (a fit's "for", a thread's designation) is named as \
the brief names it: M8, M8x1, 608.

## Nothing in the brief is left out

Every number of the brief (digits, "four", "pair", "half") must be used by a \
value. Every sentence must feed an item, or be listed:
- "requirements": {{"material": {{"text": "PETG", "from": {{"words": [1]}}}}}}: \
the part's material, exactly as the brief names it ("aluminium 6061", grade \
and all), or assumed with its reason. It names a stock: cite no size or \
count with it. It is recorded for the strength and print checks, never left \
out as not modelled. Every other word that names a material is another \
thing's ("it slides on a steel rod"): list it in not_modelled, saying whose.
- "not_modelled": [{{"words": [...], "reason": "..."}}]: what the brief says \
that the part won't have: a colour, a finish, how it is made, what it is for, \
another thing's material.
- "silent": [{{"sentence": 2, "reason": "..."}}]: a sentence that says \
nothing about the shape ("It carries no load").
Never leave out a feature because it is hard: model what you can, and list \
what you can't in not_modelled with why. The person reads that list before \
confirming, so it must say plainly what the part won't have.

## The frame and faces

{frame}

## Where items go

"on" names the face an item stands on or cuts into: {{"item": "plate", \
"face": "+z"}}. The first body has no "on": it sits on the origin. "place" \
puts it on the face, along the face's two axes:
- {{"centred": {{"words": [...]}}}}: centred along that axis;
- {{"offset": size}}: its centre that far from the face's centre (negative \
towards the minus side);
- {{"side": "+x", "distance": size, "to": "centre"}}: measured in from that \
edge of the face to the item's centre (or "to": "edge", to its near edge).
An axis place doesn't give is centred, as an assumption Forge shows. On a \
round side, place gives the position along the rod's axis and an "angle" \
round it (0 deg towards the next axis: for a rod along z, +x; along x, +y; \
along y, +z). "concentric": {{"item": ..., "from": ...}} puts it on the axis \
of a round item (a hole down a boss). On a flat face, "turn": angle turns a \
slot, a rectangular pocket, a rib, a tab, a block, a post or a line of \
letters in the face's plane, from the face's first axis towards its second, \
about its own point ("schema_version": "1.2" or later); its edges are then not along \
the face's axes, so a position measured "to": "edge" is to its turned \
outline's farthest point along that axis. A turned item's own faces take \
nothing yet, and its edges aren't rounded.

A hole, a boss or a post on a flat face may lean: "tilt": angle (more than \
0, at most 75 deg) from square to the face, towards "tilt_towards", one of \
the face's two axes ("+x", "-y", ...; turned with it where "turn" turns it; \
"schema_version": "1.3"). A boss or a post leans that way as it rises; a \
hole's way out of its mouth does, so it goes in leaning the other way. Its \
height or depth is along it; its foot on the face is its section by the \
face (a round one's an ellipse), which is what fits, overlaps and is \
measured "to": "edge". It needs the same material under all of its face; \
nothing goes on its own faces, and it isn't rounded or threaded, yet.

Patterns place copies; the item's "count" is the whole part's number of \
copies and must match:
{patterns}
"each" (a count) says how many at each position; only 1 is built for now.

## Item kinds

{kinds}

## Edges

{edges}

## An example

The brief:
{example_brief}

A spec for it:
{example_draft}

## Before you answer

- Every item: an id (lower case, digits, _), its kind, the words it comes \
from, and its fields; nothing else.
- Every number and sentence of the brief is used, not modelled, or silent.
- Every value cites the words of its own number, or is assumed with a reason.
- Every count matches what its pattern places.
Answer with the whole spec, "schema_version": "{version}".
"""

_AUTOMATIC = """
## No person will confirm this spec

This is an automatic run: nobody reads the spec before it is built, so \
nothing may rest on judgement. On top of the rules above:
- Every word of the brief, not just its numbers and sentences, is used by an \
item or a value, or listed in not_modelled. Only common words such as "a", \
"the", "with" need nothing.
- not_modelled and silent may hold only what can't be a shape. Words such \
as these qualify: {not_shapes}; and another thing's material (the part's own \
is requirements.material). A sentence or a word that may say anything of the \
shape ("it holds a small sensor") stops the run for a person.
- Every assumption stops the run for a person, and so does every question. \
Assume only what the part can't be made without, and never to avoid one: an \
automatic run that stops honestly is better than one built on a guess.
In the example above, its three assumptions and its third sentence would \
each stop an automatic run.
"""


def brief_message(brief: NumberedBrief, *, second: bool = False) -> str:
    """The first message: the brief, numbered.

    ``second`` is the second, independent draft (plan, 4.2): it is shown the
    brief last sentence first, numbered as always, so that the two readings
    don't walk the brief the same way. Neither ever sees the other.
    """
    lines = brief.for_the_model().split("\n")
    order = ""
    if second:
        lines.reverse()
        order = ("It is listed last sentence first: read all of it before you write anything. Its words and "
                 "sentences keep their numbers.\n\n")  # fmt: skip
    return (
        f"Write the part spec for this brief. {order}" + "\n".join(lines) + "\n\n"
        f"(words 0 to {len(brief.words) - 1}, sentences 0 to {len(brief.sentences) - 1})"
    )
