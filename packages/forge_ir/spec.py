"""The model-facing contract, generated from the feature catalogue itself.

A language model asked to emit ForgeIR needs to be told what ForgeIR is. The
obvious way to do that is to write a prompt describing the feature kinds and
their parameters. The obvious way is wrong, and it fails in a specific and
expensive manner: the prose drifts from the code. Someone adds a feature kind
and forgets the prompt. Someone renames a parameter and the prompt still names
the old one. The model then emits documents that are perfectly reasonable
readings of its instructions and that the compiler rejects, and every one of
those is a wasted round trip that looks like a model failure and is not.

So the contract is *generated*. :func:`authoring_guide` walks
:data:`~forge_ir.features.FEATURE_SPECS` and emits the description the model
sees; :func:`document_schema` emits the JSON Schema. Both derive from the same
declarations the compiler validates against, so they cannot disagree with it.
Adding a feature kind updates the model's instructions in the same commit, with
no separate step to forget.

The guide is deliberately compact. Model attention is a budget like any other,
and a 20,000-token specification spends it on reading rather than on designing.
What is included is what the compiler will actually reject a document for.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from forge_units import known_units

from .document import SCHEMA_VERSION
from .features import FEATURE_SPECS, FeatureSpec, ParameterSpec, SemanticOutput
from .measurements import vocabulary_help

_MEASUREMENT_HELP = vocabulary_help()

#: Units worth showing the model. The registry holds around sixty; listing all of
#: them crowds out the parts of the guide that carry more information per token.
_ILLUSTRATIVE_UNITS = (
    "mm", "cm", "m", "in",
    "kg", "g",
    "deg", "rad",
    "N", "kN", "lbf",
    "MPa", "GPa", "psi",
    "Nm", "Nmm",
    "s", "K", "degC",
    "kg/m^3", "W/(m*K)",
)


#: The JSON each parameter sort accepts, keyed by the sort the catalogue prints.
#:
#: The catalogue named the sorts -- `count`, `displacement` -- and never said
#: what JSON any of them took. Every worked example shows `{"magnitude", "unit"}`,
#: so that is what gets written everywhere, and a model that designed a correct
#: bracket lost it on `count: {"magnitude": 4, "unit": ""}` and a scalar
#: `spacing`. Naming a sort without showing its shape is half a specification.
#:
#: Verified against the decoder by ``TheParameterSortsAreShownNotJustNamed``: a
#: legend that drifts from what the compiler accepts is worse than none.
_SORT_FORMS: Mapping[str, str] = {
    "length": '{"magnitude": 12.0, "unit": "mm"} or {"expression": "wall * 2", '
    '"unit": "mm"} -- never a bare number',
    "angle": '{"magnitude": 45.0, "unit": "deg"}',
    "count": "4 -- a bare integer, or {\"expression\": \"bolt_count\"} to drive "
    "it from a parameter; it must resolve to an exact whole number "
    '(a count in a COMPONENT parameter is {"magnitude": 4, "unit": ""})',
    "displacement": '{"vector": [10.0, 0, 0], "unit": "mm"} -- a vector, not a '
    "scalar; an element may be an expression string",
    "direction": "[0, 0, 1] -- a bare 3-vector; only its direction is used",
    "points": '{"points": [[0, 0], [40, 0], [40, 20, 5]], "unit": "mm"} -- '
    "a list of points; an element may be an expression string",
    "flag": "true or false",
    "enum": '"symmetric" -- one of the names listed for that parameter',
    "dimensionless": '6.5 -- a plain number, or {"expression": "n_turns"}',
}


def parameter_sort_legend(sorts: Iterable[str] | None = None) -> str:
    """What JSON each parameter sort takes, for the sorts actually in use."""
    if sorts is None:
        sorts = {p.sort for spec in FEATURE_SPECS.values() for p in spec.parameters}
    lines = [
        "### Feature parameter sorts, and the JSON each one takes",
        "",
        "These forms are for the `parameters` of a **feature**. A **component**",
        'parameter\'s `value` is always the object form -- {"magnitude": .., '
        '"unit": ..} or {"expression": "..", "unit": ..} -- including counts,',
        'which take an empty unit: {"magnitude": 4, "unit": ""}. A bare number',
        "is never a component parameter's value.",
        "",
    ]
    lines.extend(
        f"  - {sort:13s} {_SORT_FORMS[sort]}"
        for sort in sorted(sorts)
        if sort in _SORT_FORMS
    )
    return "\n".join(lines)


#: Sorts whose JSON shape is not guessable from the sort name, shown inline on
#: the parameter itself rather than only in the legend above the catalogue.
#:
#: A legend twenty pages from the entry is not where a model is looking. Told
#: three times that `spacing` is a vector, qwen2.5-coder wrote
#: `{"expression": "bolt_spacing", "unit": "mm"}` three times -- the habit every
#: other parameter teaches, against one line it had scrolled past. The shape
#: costs about ten tokens where it is needed, and the repair round it saves
#: costs six minutes.
_INLINE_FORMS: Mapping[str, str] = {
    "displacement": '{"vector": [x, y, z], "unit": "mm"}',
    "direction": "[x, y, z]",
    "count": '4 or {"expression": "n"}',
    "points": '{"points": [[u, v], ...], "unit": "mm"}',
}


def _render_parameter(parameter: ParameterSpec) -> str:
    bits = [f"`{parameter.name}`", f"({parameter.sort}"]
    if not parameter.required:
        bits[-1] += ", optional"
    bits[-1] += ")"
    inline = _INLINE_FORMS.get(parameter.sort)
    if inline:
        bits.append(inline)
    if parameter.options:
        bits.append("one of " + " | ".join(parameter.options))
    if parameter.minimum is not None:
        bits.append(f"min {parameter.minimum}")
    if parameter.description:
        bits.append("- " + parameter.description)
    return " ".join(bits)


def _render_output(output: SemanticOutput) -> str:
    suffix = f"`.{output.suffix}`"
    text = f"{suffix} ({output.entity_type}"
    if output.optional:
        text += ", may be absent"
    text += ")"
    if output.description:
        text += f" - {output.description}"
    return text


def _render_feature(spec: FeatureSpec) -> str:
    lines = [f"### `{spec.kind}` -> {spec.produces}"]
    if spec.summary:
        lines.append(spec.summary)

    if spec.variadic_input is not None:
        lines.append(
            f"Inputs: {spec.minimum_inputs} or more `{spec.variadic_input}`."
        )
    elif spec.inputs:
        rendered = ", ".join(f"`{kind}`" for kind in spec.inputs)
        lines.append(f"Inputs (in order): {rendered}.")
    else:
        lines.append("Inputs: none.")

    if spec.parameters:
        lines.append("Parameters:")
        lines.extend(f"  - {_render_parameter(p)}" for p in spec.parameters)

    if spec.emits:
        lines.append("Publishes:")
        lines.extend(f"  - {_render_output(o)}" for o in spec.emits)

    if spec.notes:
        lines.append(f"Note: {spec.notes}")
    return "\n".join(lines)


def feature_catalogue(kinds: Iterable[str] | None = None) -> str:
    """The feature reference, generated from the specs the compiler enforces."""
    selected = sorted(kinds) if kinds is not None else sorted(FEATURE_SPECS)
    grouped: dict[str, list[str]] = {}
    for kind in selected:
        spec = FEATURE_SPECS[kind]
        grouped.setdefault(spec.produces, []).append(kind)

    order = ["datum_plane", "datum_axis", "datum_point", "profile", "solid"]
    sections: list[str] = []
    for produces in order:
        kinds_here = grouped.pop(produces, [])
        if not kinds_here:
            continue
        sections.extend(_render_feature(FEATURE_SPECS[k]) for k in kinds_here)
    for remaining in sorted(grouped):
        sections.extend(
            _render_feature(FEATURE_SPECS[k]) for k in grouped[remaining]
        )
    return "\n\n".join(sections)


#: A complete, minimal document, shown in the authoring guide.
#:
#: Deliberately a spacer and not a bracket: the example exists to show the
#: *shape* of a document -- a derived parameter, a feature consuming another
#: feature, an interface naming published geometry, a requirement bound to what
#: measures it -- and an example that resembles the thing being asked for tends
#: to get copied rather than read.
#:
#: It is exercised by the test suite, which compiles and verifies it. The guide
#: therefore cannot show a document the compiler would reject.
EXAMPLE_DOCUMENT: Mapping[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "document_id": "00000000-0000-4000-8000-000000000001",
    "project_id": "00000000-0000-4000-8000-0000000000ff",
    "revision": 1,
    "name": "Shaft spacer",
    "description": "Minimal example: a sleeve that sets an axial gap on a shaft.",
    "risk_class": "low",
    "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
    "requirements": [
        {
            "id": "REQ_BORE",
            "statement": "The bore shall be 10 mm in diameter.",
            "type": "interface",
            "strength": "hard",
            "verification": "exact_geometry",
            "threshold": {"magnitude": 10.0, "unit": "mm"},
            "comparison": "equals",
            "measurement": "interface_size:shaft_port",
            "source": "user",
            "state": "accepted",
        },
        {
            "id": "REQ_WALL",
            "statement": "No wall shall be thinner than 2 mm.",
            "type": "manufacturing",
            "strength": "hard",
            "verification": "exact_geometry",
            "threshold": {"magnitude": 2.0, "unit": "mm"},
            "comparison": "at_least",
            "measurement": "minimum_wall_thickness",
            "source": "derived",
            "state": "not_tested",
        },
    ],
    "assumptions": [],
    "components": [
        {
            "id": "spacer",
            "name": "Shaft spacer",
            "material": "aluminium_6061_t6",
            "parameters": [
                {
                    "id": "bore_diameter",
                    "value": {"magnitude": 10.0, "unit": "mm"},
                    "description": "Shaft diameter this sleeve fits over",
                },
                {
                    "id": "wall",
                    "value": {"magnitude": 3.0, "unit": "mm"},
                    "bounds": {
                        "min": {"magnitude": 2.0, "unit": "mm"},
                        "max": {"magnitude": 6.0, "unit": "mm"},
                    },
                    "optimizable": True,
                },
                {
                    "id": "outer_diameter",
                    "expression": "bore_diameter + 2 * wall",
                    "unit": "mm",
                    "description": "Derived, so changing the wall moves it",
                },
                {"id": "length", "value": {"magnitude": 14.0, "unit": "mm"}},
            ],
            "features": [
                {
                    "id": "body",
                    "kind": "cylinder",
                    "role": "body",
                    "parameters": {
                        "diameter": {"expression": "outer_diameter", "unit": "mm"},
                        "height": {"expression": "length", "unit": "mm"},
                        "origin": {"vector": [0, 0, 0], "unit": "mm"},
                    },
                },
                {
                    "id": "shaft_hole",
                    "kind": "hole",
                    "role": "shaft",
                    "inputs": ["body"],
                    "parameters": {
                        "diameter": {"expression": "bore_diameter", "unit": "mm"},
                        "position": {
                            "vector": [0, 0, "length / 2"],
                            "unit": "mm",
                        },
                        "axis": [0, 0, 1],
                        "fit": "clearance_normal",
                    },
                },
            ],
            "interfaces": [
                {
                    "id": "shaft_port",
                    "type": "bore",
                    "geometry": "shaft.bore",
                    "nominal_size": {"magnitude": 10.0, "unit": "mm"},
                    "fit": "clearance_normal",
                }
            ],
        }
    ],
}


def example_document_json() -> str:
    """The worked example as a whole document, for docs and tests."""
    return json.dumps(EXAMPLE_DOCUMENT, indent=2)


#: What the designer actually returns: the fields it designs, and nothing else.
DESIGNER_ANSWER_FIELDS = ("name", "description", "components")


def designer_answer_json() -> str:
    """The worked example trimmed to the shape of a designer's answer.

    The guide used to show the whole document -- requirements, assumptions,
    ids, units -- while the instructions said to return none of them. An
    example that contradicts the instruction wins, because it is concrete and
    the instruction is a sentence. So the example shows an answer, not a
    document, and the parts the orchestrator fills in are visibly absent.
    """
    return json.dumps(
        {
            key: value
            for key, value in EXAMPLE_DOCUMENT.items()
            if key in DESIGNER_ANSWER_FIELDS
        },
        indent=2,
    )


AUTHORING_RULES = f"""\
# Authoring a ForgeIR document

ForgeIR describes a mechanical part as a graph of typed features over named
parameters. A compiler validates it strictly and tells you exactly where it is
wrong, so prefer emitting your best attempt over hedging.

## Which way is up

**Z is up. X is width, Y is depth, Z is height**, and a `box`'s `size` vector is
`[x, y, z]` in that order. This is a convention, not something the compiler can
check for you: every ordering builds, so a part in the wrong plane compiles
cleanly, measures cleanly, passes every gate and is still the wrong part.

It follows that:

- **A flat plate's thickness is its Z.** A 30 mm square plate 4 mm thick is
  `"size": {{"vector": [30, 30, 4]}}` -- never `[30, 4, 30]`, which stands the
  plate on its edge. Put the thinnest dimension last unless the part is
  genuinely a vertical web.
- **A square part uses ONE parameter twice, not two parameters.** Written
  parametrically, that plate is
  `"size": {{"vector": ["plate_size", "plate_size", "plate_thickness"]}}` --
  `plate_size` in X and again in Y. Two parameters means choosing a number for
  the second one, and it will not be the first: `["base_width", "base_height",
  "base_thickness"]` on a square plate produced a plate 30 by 12, and then a
  plate 30 by 4. A round part is the same rule -- one `diameter` sets both X
  and Y. The example further down is a 60 by 40 bracket and rightly has a
  separate name per side; copy its shape, not its parameter count.
- **Something standing *on* a plate has its base at the plate's top face**, not
  at the origin. With a `centered` plate that face is at `plate_thickness / 2`,
  so a post's `origin` is `[0, 0, "plate_thickness / 2"]`. A post written at
  `[0, 0, 0]` starts at the plate's mid-plane and is buried inside it.
  A cylinder's `origin` is its BASE, never its centre: a 6 mm disc from the
  origin up and a hub standing on it are `[0, 0, 0]` and
  `[0, 0, "disc_thickness"]`. Adding half the cylinder's own height floats it.
- **A plate that STANDS -- an upright, a wall, the vertical leg of an L -- has
  its height in Z.** Its `size` is `["width", "thickness", "height"]`;
  `["width", "height", "thickness"]` lays it flat. Standing on the back end of
  a centred base, from the floor, it is not centred: its `origin` is
  `["-width / 2", "base_length / 2 - thickness", "-thickness / 2"]`.
- **A box, tray or cup open at the top is an outer solid minus an inner one.**
  `shell` keeps EVERY face, the top included: it builds a sealed box. Open at
  the top is the outer `box` of the outside size, an inner `box` sized
  `["length - 2 * wall_thickness", "width - 2 * wall_thickness", "height"]`
  raised by `floor_thickness` so it runs out through the top, and a
  `subtract` of the inner from the outer.
- **A hole through a plate runs along the plate's thickness.** For a flat plate
  that is `"axis": [0, 0, 1]`. A hole drilled across the plate's width instead
  is still "open", and still wrong.
- **Holes in a pattern are placed by expression, not by a number you worked
  out.** Two holes 20 mm apart sit at `"mounting_hole_spacing / 2"` and
  `"-mounting_hole_spacing / 2"`. Writing `15.0` there gives a part whose holes
  move when nothing else does, and a requirement measuring the spacing
  parameter will report PASS on holes that are not that far apart.
- **An angle is not a position.** A value in `deg` written into a millimetre
  vector is a dimension error and will not compile, and an angle the brief
  states that no feature reads is a parameter that proves nothing -- the design
  is refused for it. An angle reaches the geometry one of two ways:

  - **Two holes an angle apart through the wall of a round body are two
    `hole`s that differ only in their `axis`.** Two 4 mm set screws 90 degrees
    apart, halfway along a collar: both at
    `"position": {{"vector": [0, 0, "length / 2"]}}` -- on the CENTRE LINE, not
    out on the skin -- one with `"axis": [1, 0, 0]` and the other with
    `"axis": [0, 1, 0]`. The 90 degrees is the angle between those two axes.
    A set screw goes through ONE wall, so give each one
    `"depth": {{"expression": "outer_diameter"}}`: a hole with a `depth` is
    cut from its position along its axis only, so from the centre line it
    opens one side into the bore. Without `depth` it is a through hole -- in
    one side and out the other, two openings per screw.
    Note that a hole through a wall runs ACROSS the body while the bore runs
    ALONG it: if both your set screws have the bore's `[0, 0, 1]`, you have
    drilled down the shaft instead of into it.
  - To make the stated angle actually drive the part, write the second axis as
    the first one turned: `"axis": ["cos(screw_angle)", "sin(screw_angle)", 0]`
    with `screw_angle` declared as 90 deg. `cos` and `sin` take an angle
    parameter directly. Forge will do this substitution for you when two
    features carrying the same tag are already exactly that angle apart.
  - **Repeated copies** of a shape around an axis are a `pattern_circular`:
    `"count": {{"magnitude": 2, "unit": ""}}` and
    `"step_angle": {{"magnitude": 90, "unit": "deg"}}`. It repeats a *solid*,
    so to repeat a cut, pattern the cutting primitive and `subtract` the
    result.
  - **Angles in expressions.** In a slot declared in `deg`, a plain number is
    that many degrees: `"expression": "360 / hole_count"` is 60 degrees for
    six holes, and `"angle + 10"` adds ten degrees. Write `pi` by name, never
    `3.14159`: a figure worked out with `pi` is taken as radians. `asin`,
    `acos`, `atan` and `atan2` return radians; write `deg(atan2(y, x))` to
    have the result in degrees, never `atan2(y, x) * 180 / pi`.

## Rules the compiler enforces

1. **Every component parameter's value is an object carrying a unit.** Write
   `{{"magnitude": 6.0, "unit": "mm"}}`. A bare number is rejected -- and that
   includes a count, which takes the empty unit: `{{"magnitude": 4, "unit": ""}}`.
2. **Expressions instead of arithmetic you did yourself.** Write
   `{{"expression": "ear_gap + 2 * ear_thickness", "unit": "mm"}}`. A parameter
   whose value is a consequence of others must say so, so that changing the
   inputs changes it. Operators: `+ - * / // % ^`, comparisons, `and or not`,
   and `a if cond else b`. `^` is exponentiation.
3. **Unknown fields are rejected**, not ignored. Do not invent field names.
4. **Each component has exactly one terminal solid** - one feature that nothing
   else consumes. Combine stray bodies with a boolean.
5. **Reference geometry by published name**, never by index. A feature with
   `"role": "pivot"` and kind `hole` publishes `pivot.bore` and `pivot.axis`.
   Interfaces must name something a feature actually publishes.
6. **Every feature that takes an input must name it.** There is no "current
   body" and no implied order: a feature acts on what its `inputs` name and on
   nothing else. A `hole` after a `cylinder` must say
   `"inputs": ["<that cylinder>"]`, and three holes in a row are a chain -
   each one cuts the result of the last, so the last hole is the terminal
   solid. Only primitives (`box`, `cylinder`, `sphere`) take none. The kinds
   must match too: an `extrude` takes a `profile`; a boolean takes `solid`s.
7. **A parameter's `bounds` are a contract.** A value outside its own bounds
   fails to compile, so set bounds you mean.
8. **You design the part, not the paperwork.** Return `name`, an optional
   `description`, and `components`. The requirements, assumptions, ids, units
   and schema version are filled in around your answer.

## Units

Compound units use `*`, `/`, `^` and parentheses: `N/mm^2`, `kg/m^3`,
`W/(m*K)`. Note that `W/(m*K)` and `W/m*K` are different units. Available
units include: {", ".join(f"`{u}`" for u in _ILLUSTRATIVE_UNITS)}.

## Modelling guidance

- Build from primitives (`box`, `cylinder`, `sphere`) and booleans where you
  can; they are exact and cheap. **A rectangular plate is a `box`. A round disc,
  post or boss is a `cylinder`.** Neither needs a profile, and a profile needs a
  `datum_plane` feature to be drawn on, so reaching for `profile_rectangle` +
  `extrude` to make a plate costs you two extra features and buys nothing.
  Profiles earn their cost on shapes a primitive cannot make: an L-section, a
  slot-ended arm, a polygon.
- A **fillet is a property of the boolean**, not a separate operation: give
  `union` or `subtract` a `blend_radius` and it produces a true circular fillet
  of that radius at the junction.
- A `hole` is a distinct feature rather than a subtracted cylinder, because the
  bore and axis it publishes are what mates, bearing loads and fit tolerances
  attach to. Use it.
- **Cut holes last.** A `hole` removes material only from the solid you hand it,
  and anything unioned on afterwards fills the bore straight back in. Drill a
  post and *then* union it to its base plate, and the plate seals the bottom of
  the hole: the part looks right, measures right, and prints with a pocket
  instead of a hole. Build the whole body first, hand that body to the `hole`,
  and let the hole be the last feature in the graph.
- Give a feature a `role` when anything will refer to its geometry.
- Name parameters for what they mean (`ear_thickness`, not `t1`), and give the
  ones a user might reasonably change a `bounds` range and `"optimizable": true`.

## What NOT to do

- Do not invent a load, a material grade, a safety factor, or a dimension the
  brief did not give you. Record it as an assumption with `risk` set, or leave
  the requirement blocked. A number you made up is worse than a missing one,
  because it looks checked.
- Do not write `"material": "aluminium"`. Name a specific grade and condition,
  or leave it empty.
- Do not use a unit you are unsure of. Prefer `mm`, `N`, `MPa`, `deg`.
"""


#: Four features that show how a part made of more than one solid is assembled.
#:
#: The guide said "build from primitives and booleans" in prose and then showed
#: a worked example -- a spacer -- containing no boolean at all. So the only
#: composition pattern the designer had ever seen was a chain: each feature
#: takes the previous one and modifies it. Asked for a bracket, which is a
#: plate with something standing on it, qwen2.5-coder wrote
#: `{"kind": "cylinder", "inputs": ["shaft"]}` -- the chain habit applied to a
#: primitive, which takes no inputs. Three attempts, three identical answers,
#: against an error message that spelled out the fix in words.
#:
#: Words were not the missing thing. This fragment is, and it teaches all four
#: rules the designer kept breaking at once: primitives take no `inputs`, a
#: boolean is what joins them, later features consume the boolean, and exactly
#: one solid is left unconsumed at the end.
#:
#: Compiled and measured by ``TheCompositionExampleIsReal``, so it cannot drift
#: into showing something the compiler rejects.
COMPOSITION_EXAMPLE: tuple[Mapping[str, Any], ...] = (
    {
        "id": "base",
        "kind": "box",
        "parameters": {
            "size": {"vector": ["plate_width", "plate_depth", "plate"], "unit": "mm"},
            "centered": True,
        },
    },
    {
        "id": "post",
        "kind": "cylinder",
        "parameters": {
            "diameter": {"expression": "boss_diameter", "unit": "mm"},
            # Past the bore by the post's own radius, so the bore has wall
            # all the way round it. Stopping the post AT the bore's height
            # leaves the top half of the bore in open air: a cradle, not a
            # hole, and GEOM_HOLES_ARE_HOLES fails it. This example did
            # exactly that for as long as it existed, shown to every design.
            "height": {"expression": "stand_off + boss_diameter / 2",
                       "unit": "mm"},
            # On the plate's top face, not at the component origin. The
            # plate is `centered`, so its top is at `plate / 2`; a post
            # written at [0, 0, 0] starts at the plate's mid-plane and is
            # buried in it. A designer copied exactly that and returned a
            # post swallowed by its own base -- the example taught it.
            "origin": {"vector": [0, 0, "plate / 2"], "unit": "mm"},
        },
    },
    {
        "id": "body",
        "kind": "union",
        "inputs": ["base", "post"],
        "parameters": {"blend_radius": {"magnitude": 2.0, "unit": "mm"}},
    },
    {
        "id": "bore",
        "kind": "hole",
        "role": "shaft",
        "inputs": ["body"],
        "parameters": {
            "diameter": {"expression": "shaft_diameter", "unit": "mm"},
            "position": {"vector": [0, 0, "stand_off"], "unit": "mm"},
            "axis": [1, 0, 0],
            "fit": "clearance_normal",
        },
    },
)


#: The parameters the composition example's features refer to.
_COMPOSITION_PARAMETERS: tuple[Mapping[str, Any], ...] = (
    {"id": "plate_width", "value": {"magnitude": 60.0, "unit": "mm"}},
    {"id": "plate_depth", "value": {"magnitude": 40.0, "unit": "mm"}},
    {"id": "plate", "value": {"magnitude": 6.0, "unit": "mm"}},
    {"id": "boss_diameter", "value": {"magnitude": 30.0, "unit": "mm"}},
    {"id": "stand_off", "value": {"magnitude": 32.0, "unit": "mm"}},
    {"id": "shaft_diameter", "value": {"magnitude": 20.0, "unit": "mm"}},
)


def composition_component() -> Mapping[str, Any]:
    """The composition example as the component that contains it."""
    return {
        "id": "bracket",
        "name": "Bracket",
        "material": "aluminium_6061_t6",
        "parameters": [dict(p) for p in _COMPOSITION_PARAMETERS],
        "features": [dict(f) for f in COMPOSITION_EXAMPLE],
    }


def composition_example() -> str:
    """The multi-solid pattern, rendered for the guide.

    Rendered as the whole component rather than a bare list of features. Shown
    as a bare list it was read as a list of *components*: the designer returned
    `base` and `post` as separate components, each with its own parameters and
    features, and the answer ran past 19,000 characters before the output
    ceiling cut it off. An example has to show where it goes, not only what it
    contains.
    """
    return json.dumps(composition_component(), indent=2)


#: Feature kinds the reference leaves out until a brief asks for them --
#: each costs a few hundred tokens of every design prompt, and most parts
#: need none of them. The designer offers each with the brief that has a
#: word for it (`forge_roles.library._KINDS_A_BRIEF_ASKS_FOR`).
KINDS_OFFERED_ON_REQUEST: tuple[str, ...] = (
    "bend", "cone", "torus", "wedge", "profile_gear", "sweep", "pipe", "coil",
    "loft")


def authoring_guide(
    *, include_catalogue: bool = True, include_example: bool = True,
    exclude_kinds: Iterable[str] = KINDS_OFFERED_ON_REQUEST,
) -> str:
    """The complete instruction set handed to the ForgeIR Designer role."""
    parts = [AUTHORING_RULES]
    if include_example:
        parts.append(
            "## A part made of more than one solid\n\n"
            "Most parts are. A primitive (`box`, `cylinder`, `sphere`) takes no "
            "`inputs` -- it makes a solid out of nothing -- so two of them are "
            "joined by a **boolean** that consumes both, and later features "
            "consume the boolean's result.\n\n"
            "Here is one entry of `components`, entire. The part is a plate "
            "with a post standing on it and a bore through the post, and all "
            "of that is **one component**:\n\n"
            "```json\n" + composition_example() + "\n```\n\n"
            "Read three things from it:\n\n"
            "1. `base` and `post` are **features, not components**. A part is "
            "one component; its solids are features inside that component's "
            "`features` list. Only a genuine assembly of separable parts has "
            "more than one component, and this brief is one part.\n"
            "2. `post` does not list `base` as an input. A primitive never has "
            "inputs; `union` is what puts the two together.\n"
            "3. `base` and `post` are consumed by `body`, and `body` by "
            "`bore`, so `bore` is the single terminal solid the compiler "
            "requires."
        )
    if include_example:
        parts.append(
            "## A second part, and the whole of what you return\n\n"
            "A spacer, not a bracket: read it for the *shape* of an answer, "
            "not as a template to fill in. Note the derived `outer_diameter`, "
            "the hole consuming the body, and the interface naming geometry "
            "the hole publishes. Note also what is **not** here -- no "
            "`requirements`, no `assumptions`, no ids, no units. This is an "
            "answer entire.\n\n"
            "```json\n" + designer_answer_json() + "\n```"
        )
    if include_catalogue:
        parts.append(
            "## Feature reference\n\n"
            + parameter_sort_legend()
            + "\n\n"
            + feature_catalogue(
                k for k in FEATURE_SPECS if k not in set(exclude_kinds))
        )
    return "\n\n".join(parts)


# ----------------------------------------------------------------------
# JSON Schema
# ----------------------------------------------------------------------
_QUANTITY_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "description": "A dimensional value. Always carries a unit.",
    "properties": {
        "magnitude": {"type": "number"},
        "unit": {"type": "string", "description": "e.g. mm, N, MPa, deg"},
        "interval": {
            "type": "object",
            "properties": {"lo": {"type": "number"}, "hi": {"type": "number"}},
            "required": ["lo", "hi"],
            "additionalProperties": False,
        },
    },
    "required": ["magnitude", "unit"],
    "additionalProperties": False,
}

_EXPRESSION_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "description": "A value computed from other parameters.",
    "properties": {
        "expression": {"type": "string"},
        "unit": {"type": "string"},
    },
    "required": ["expression"],
    "additionalProperties": False,
}

_VALUE_SCHEMA: Mapping[str, Any] = {
    "oneOf": [dict(_QUANTITY_SCHEMA), dict(_EXPRESSION_SCHEMA)]
}

#: A feature parameter's value, without the descriptions and the tolerance
#: interval a component parameter may carry: repeated for every length of
#: every kind, the long form was half the designer's grammar. The decoder
#: is unchanged -- this is only what the grammar offers.
_FEATURE_VALUE_SCHEMA: Mapping[str, Any] = {
    "oneOf": [
        {"type": "object",
         "properties": {"magnitude": {"type": "number"},
                        "unit": {"type": "string"}},
         "required": ["magnitude", "unit"], "additionalProperties": False},
        {"type": "object",
         "properties": {"expression": {"type": "string"},
                        "unit": {"type": "string"}},
         "required": ["expression"], "additionalProperties": False},
    ]
}


def _feature_schema() -> Mapping[str, Any]:
    """One schema branch per feature kind, so the kind constrains its parameters.

    Emitting a single loose `parameters: object` would let the model produce a
    `box` with a `diameter`. Branching on `kind` moves that error from compile
    time to generation time, where it costs nothing.
    """
    branches: list[Mapping[str, Any]] = []
    for kind in sorted(FEATURE_SPECS):
        spec = FEATURE_SPECS[kind]
        properties: dict[str, Any] = {}
        required: list[str] = []
        for parameter in spec.parameters:
            properties[parameter.name] = _parameter_schema(parameter)
            if parameter.required:
                required.append(parameter.name)

        branch: dict[str, Any] = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "kind": {"const": kind},
                "role": {"type": "string"},
                "description": {"type": "string"},
                # `tags` was missing here while `additionalProperties` is
                # False, so the transport schema forbade the one thing the
                # designer's own validator demands: a requirement bound to
                # `feature_count:hole:mounting` is unmeasurable until the
                # features carry the tag, and under `--exact-schema` a
                # constrained endpoint could not emit one. Tagged features
                # decode fine -- only the wire contract refused them, which
                # made that pair of rules unsatisfiable together.
                "tags": {"type": "array", "items": {"type": "string"}},
                "inputs": {"type": "array", "items": {"type": "string"}},
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
            "required": ["id", "kind"] + (["parameters"] if required else []),
            "additionalProperties": False,
        }
        branches.append(branch)
    return {"oneOf": branches}


def _parameter_schema(parameter: ParameterSpec) -> Mapping[str, Any]:
    if parameter.sort == "count":
        return {
            "oneOf": [
                {"type": "integer", "minimum": 1},
                {
                    "type": "object",
                    "description": (
                        "A count driven by a parameter. Must resolve to an "
                        "exact whole number of at least 1."
                    ),
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"],
                    "additionalProperties": False,
                },
            ]
        }
    if parameter.sort == "flag":
        return {"type": "boolean"}
    if parameter.sort == "enum":
        return {"enum": list(parameter.options)}
    if parameter.sort in ("vector", "direction", "displacement"):
        return {
            "oneOf": [
                {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                {
                    "type": "object",
                    "properties": {
                        "vector": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {
                                "oneOf": [{"type": "number"}, {"type": "string"}]
                            },
                        },
                        "unit": {"type": "string"},
                        "normalise": {"type": "boolean"},
                    },
                    "required": ["vector"],
                    "additionalProperties": False,
                },
            ]
        }
    if parameter.sort == "points":
        return {
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "type": "array", "minItems": 2, "maxItems": 4,
                        "items": {"oneOf": [{"type": "number"},
                                            {"type": "string"}]},
                    },
                },
                "unit": {"type": "string"},
            },
            "required": ["points"],
            "additionalProperties": False,
        }
    return dict(_FEATURE_VALUE_SCHEMA)


def document_schema() -> dict[str, Any]:
    """JSON Schema for a complete ForgeIR document."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ForgeIR document",
        "type": "object",
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "document_id": {"type": "string"},
            "project_id": {"type": "string"},
            "revision": {"type": "integer", "minimum": 1},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "risk_class": {"enum": ["low", "moderate", "high", "critical"]},
            "units": {
                "type": "object",
                "properties": {
                    "length": {"type": "string"},
                    "mass": {"type": "string"},
                    "time": {"type": "string"},
                    "angle": {"type": "string"},
                    "force": {"type": "string"},
                    "stress": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "requirements": {"type": "array", "items": _requirement_schema()},
            "assumptions": {"type": "array", "items": _assumption_schema()},
            "components": {
                "type": "array",
                "minItems": 1,
                "items": _component_schema(),
            },
        },
        "required": [
            "schema_version",
            "document_id",
            "project_id",
            "revision",
            "name",
            "components",
        ],
        "additionalProperties": False,
    }


def _requirement_schema() -> Mapping[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "statement": {"type": "string"},
            "type": {
                "enum": [
                    "functional", "geometric", "interface", "performance",
                    "manufacturing", "safety", "cost", "environmental",
                    "aesthetic", "regulatory",
                ]
            },
            "strength": {"enum": ["hard", "soft", "preference", "informational"]},
            "verification": {
                "enum": [
                    "exact_geometry", "analytical", "simulation", "visual_review",
                    "user_confirmation", "physical_test",
                    "external_certification", "none",
                ]
            },
            "threshold": dict(_QUANTITY_SCHEMA),
            "comparison": {
                "enum": ["at_least", "at_most", "equals", "within", "none"]
            },
            "measurement": {
                "type": "string",
                "description": (
                    "What measures this requirement. Required for any numeric "
                    "requirement, or it cannot be checked. e.g. `mass`, "
                    "`minimum_wall_thickness`, `parameter:base_width`, "
                    "`interface_size:shaft_port`, "
                    "`entity:shaft.bore:diameter`, `safety_factor:bearing`."
                ),
            },
            "source": {"type": "string"},
            "state": {
                "enum": [
                    "proposed", "accepted", "rejected", "superseded",
                    "satisfied", "failed", "blocked", "not_tested",
                ]
            },
            "rationale": {"type": "string"},
        },
        "required": ["id", "statement", "type", "strength", "verification"],
        "additionalProperties": False,
    }


def _assumption_schema() -> Mapping[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "statement": {"type": "string"},
            # Described, not just typed. The field said "a dimensional value"
            # and a model assuming a material grade wrote
            # {"magnitude": 6061, "unit": "T6 aluminium alloy"} into it -- a
            # reasonable act by anyone who has a value and sees a slot for one.
            # Most assumptions have no measurable value at all, and saying so
            # here costs nothing.
            "value": dict(_QUANTITY_SCHEMA) | {
                "description": (
                    "Optional, and usually absent. Only for an assumption that "
                    "is genuinely a measured quantity -- a load in N, a "
                    "temperature in degC, a thickness in mm. A material grade, "
                    "a standard, a finish or a process is not measurable: say "
                    "it in `statement` and leave this out."
                )
            },
            "rationale": {"type": "string"},
            "consequence_if_wrong": {"type": "string"},
            "risk": {"enum": ["low", "moderate", "high", "critical"]},
            "reversible": {"type": "boolean"},
            "approved": {"type": "boolean"},
        },
        "required": ["id", "statement", "risk"],
        "additionalProperties": False,
    }


def _component_schema() -> Mapping[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "material": {"type": "string"},
            "parameters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "value": dict(_QUANTITY_SCHEMA),
                        "expression": {"type": "string"},
                        "unit": {"type": "string"},
                        "bounds": {
                            "type": "object",
                            "properties": {
                                "min": dict(_QUANTITY_SCHEMA),
                                "max": dict(_QUANTITY_SCHEMA),
                            },
                            "additionalProperties": False,
                        },
                        "optimizable": {"type": "boolean"},
                        "description": {"type": "string"},
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
            },
            "features": {
                "type": "array",
                "minItems": 1,
                "items": _feature_schema(),
            },
            "interfaces": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {
                            "enum": [
                                "bore", "shaft", "planar_mount", "bolt_pattern",
                                "keyway", "gear_pitch_surface", "slider_rail",
                                "electrical_placeholder", "fluid_placeholder",
                                "custom",
                            ]
                        },
                        "geometry": {"type": "string"},
                        "nominal_size": dict(_QUANTITY_SCHEMA),
                        "fit": {"type": "string"},
                        "load_transfer": {"type": "string"},
                        "allowable_motion": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["id", "type", "geometry"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["id", "features"],
        "additionalProperties": False,
    }


def write_schema(path: str) -> None:
    """Write the JSON Schema to disk, for external consumers and for diffing."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document_schema(), handle, indent=2, sort_keys=True)
        handle.write("\n")


def available_units() -> tuple[str, ...]:
    return tuple(sorted(known_units()))


__all__ = [
    "AUTHORING_RULES",
    "COMPOSITION_EXAMPLE",
    "EXAMPLE_DOCUMENT",
    "authoring_guide",
    "composition_example",
    "parameter_sort_legend",
    "feature_catalogue",
    "document_schema",
    "write_schema",
    "available_units",
]
