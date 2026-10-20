"""Model responses for the end-to-end tests, written as the model would.

These are not mocks in the usual sense. Each is a plausible, complete answer to
the *actual generated prompt* for its role, authored to exercise the loop
honestly: the design in :data:`DESIGNER_VALID` is a real bracket that really
compiles, and the one in :data:`DESIGNER_BROKEN` fails in the way models actually
fail -- a parameter borrowed from the wrong feature kind, a missing unit, an
interface pointing at geometry that does not exist.

Writing them by hand rather than recording them has one advantage worth the
effort: a recorded fixture tells you the loop worked once, while a hand-written
one lets you choose precisely which failure the loop has to survive.

The brief they answer:

    A bracket that holds a 20 mm shaft. It bolts to a flat plate with four M5
    bolts. The shaft sits 32 mm above the mounting surface and carries 300 N
    downwards. Make it from 6061-T6 aluminium.
"""

from __future__ import annotations

from typing import Any

BRIEF = (
    "A bracket that holds a 20 mm shaft. It bolts to a flat plate with four M5 "
    "bolts. The shaft sits 32 mm above the mounting surface and carries 300 N "
    "downwards. Make it from 6061-T6 aluminium."
)

BRIEF_UNDERSPECIFIED = (
    "I need a bracket to hold a shaft. Make it strong enough."
)


# ----------------------------------------------------------------------
INTERPRETER: dict[str, Any] = {
    "summary": (
        "A shaft-support bracket that bolts to a flat surface and carries a "
        "20 mm shaft 32 mm above it under a 300 N downward load."
    ),
    "part_kind": "bracket",
    "suggested_name": "Shaft support bracket",
    "stated": [
        "Holds a 20 mm shaft",
        "Bolts to a flat plate with four M5 bolts",
        "Shaft axis sits 32 mm above the mounting surface",
        "Carries 300 N downwards",
        "Material is 6061-T6 aluminium",
    ],
    "implied": [
        "Bolting to a flat plate implies a flat mounting face on the underside",
        "A 20 mm shaft implies a bore that receives it, so the bore is a "
        "functional interface with a fit class",
        "'Carries 300 N downwards' implies the load acts at the shaft axis, "
        "producing a moment about the bracket root equal to 300 N x 32 mm",
    ],
    "unstated": [
        "The fit between shaft and bore - clearance, transition or interference",
        "Whether the shaft rotates in the bracket or is clamped",
        "The bolt circle geometry: spacing and edge distances on the mounting face",
        "Whether the 300 N is static, or includes shock or fatigue cycles",
        "Required safety factor",
        "Envelope limits - how much space the bracket may occupy",
        "Surface finish and any corrosion requirement",
    ],
    "out_of_scope": [
        "The shaft itself, its bearings and the bolts are separate components"
    ],
    "risk_signals": [],
}


# ----------------------------------------------------------------------
REQUIREMENTS: dict[str, Any] = {
    "risk_class": "low",
    "requirements": [
        {
            "id": "REQ_BORE_DIAMETER",
            "statement": "The shaft bore shall be 20 mm in diameter.",
            "type": "interface",
            "strength": "hard",
            "verification": "exact_geometry",
            "threshold": {"magnitude": 20.0, "unit": "mm"},
            "comparison": "equals",
            "measurement": "interface_size:shaft_port",
            "source": "user",
            "state": "accepted",
        },
        {
            "id": "REQ_SHAFT_HEIGHT",
            "statement": (
                "The shaft axis shall sit 32 mm above the mounting face."
            ),
            "type": "geometric",
            "strength": "hard",
            "verification": "exact_geometry",
            "threshold": {"magnitude": 32.0, "unit": "mm"},
            "comparison": "equals",
            "measurement": "parameter:lever_arm",
            "source": "user",
            "state": "accepted",
        },
        {
            "id": "REQ_MIN_WALL",
            "statement": (
                "No wall shall be thinner than 3 mm, so the part can be "
                "machined without distortion."
            ),
            "type": "manufacturing",
            "strength": "hard",
            "verification": "exact_geometry",
            "threshold": {"magnitude": 3.0, "unit": "mm"},
            "comparison": "at_least",
            "measurement": "minimum_wall_thickness",
            "source": "derived",
            "state": "not_tested",
        },
        {
            "id": "REQ_MASS",
            "statement": "The bracket should weigh no more than 400 g.",
            "type": "performance",
            "strength": "soft",
            "verification": "exact_geometry",
            "threshold": {"magnitude": 400.0, "unit": "g"},
            "comparison": "at_most",
            "measurement": "mass",
            "source": "derived",
            "state": "not_tested",
        },
        {
            "id": "REQ_BEARING_MARGIN",
            "statement": (
                "Bearing stress at the shaft bore shall keep a safety factor of "
                "at least 2 against yield."
            ),
            "type": "performance",
            "strength": "hard",
            "verification": "analytical",
            "threshold": {"magnitude": 2.0, "unit": ""},
            "comparison": "at_least",
            "measurement": "safety_factor:bearing",
            "source": "derived",
            "state": "not_tested",
        },
        # Forge's own, with a weight budget in the record: the budget is not
        # met by air sealed inside the part.
        {
            "id": "REQ_NOTHING_SEALED_INSIDE",
            "statement": (
                "Nothing shall be sealed inside the part: no pocket of air it "
                "closes in on every side."
            ),
            "type": "geometric",
            "strength": "hard",
            "verification": "exact_geometry",
            "threshold": {"magnitude": 0, "unit": ""},
            "comparison": "at_most",
            "measurement": "sealed_voids",
            "source": "derived",
            "state": "not_tested",
        },
    ],
    "assumptions": [
        {
            "id": "ASM_DESIGN_LOAD",
            "statement": (
                "The 300 N acts downwards at the shaft axis, statically, in the "
                "worst-case direction."
            ),
            "value": {"magnitude": 300.0, "unit": "N"},
            "rationale": "The brief gives a magnitude and a direction but no duty cycle.",
            "consequence_if_wrong": (
                "If the load is dynamic or shock-loaded, the static margin here "
                "does not apply and the bracket could fail in service."
            ),
            "risk": "high",
            "reversible": False,
            "approved": False,
        },
        {
            "id": "ASM_SAFETY_FACTOR",
            "statement": "A safety factor of 2 against yield is targeted.",
            "rationale": "Conventional for a static, non-critical machine bracket.",
            "consequence_if_wrong": (
                "A higher required factor would demand more material at the root."
            ),
            "risk": "moderate",
            "reversible": True,
            "approved": False,
        },
        {
            "id": "ASM_FIT",
            "statement": (
                "The bore is a normal clearance fit; the shaft is not intended "
                "to rotate directly in the aluminium."
            ),
            "rationale": "Nothing in the brief suggests a bearing or press fit.",
            "consequence_if_wrong": (
                "A rotating shaft in an aluminium bore would gall; a bearing or "
                "bushing would be needed."
            ),
            "risk": "moderate",
            "reversible": True,
            "approved": False,
        },
    ],
    "unknowns": [
        {
            "id": "UNK_DUTY",
            "question": (
                "Is the 300 N a static load, or does it cycle or shock-load?"
            ),
            "why_it_matters": (
                "A cyclic load requires fatigue assessment, and the allowable "
                "stress drops substantially."
            ),
            "blocks": ["REQ_MASS"],
            "critical": False,
            "suggested_default": "static",
        },
        {
            "id": "UNK_ENVELOPE",
            "question": "Is there a size limit on the bracket?",
            "why_it_matters": "Bounds how much material can be added at the root.",
            "blocks": [],
            "critical": False,
            "suggested_default": "no constraint",
        },
    ],
}


# ----------------------------------------------------------------------
def _bracket_document(
    *, out_of_bounds: bool = False, malformed: bool = False
) -> dict[str, Any]:
    """The bracket, as the ForgeIR Designer would emit it.

    Geometry: a 70 x 50 x 8 mm base plate with an upright at one end carrying a
    20 mm bore whose axis is 32 mm above the mounting face, blended into the
    base, with four M5 clearance holes through the plate.
    """
    features: list[dict[str, Any]] = [
        {
            "id": "base_plate",
            "kind": "box",
            "role": "base",
            "description": "The mounting plate",
            "parameters": {
                "size": {
                    "vector": ["base_length", "base_width", "base_thickness"],
                    "unit": "mm",
                },
                "origin": {"vector": [0, 0, 0], "unit": "mm"},
                "centered": False,
            },
        },
        {
            "id": "upright",
            "kind": "box",
            "role": "upright",
            "description": "The web carrying the shaft bore",
            "parameters": {
                "size": {
                    "vector": ["upright_thickness", "base_width", "upright_height"],
                    "unit": "mm",
                },
                "origin": {"vector": [0, 0, "base_thickness"], "unit": "mm"},
                "centered": False,
            },
        },
        {
            "id": "crown",
            "kind": "cylinder",
            "role": "crown",
            "description": "Rounds the top of the upright about the bore axis",
            "parameters": {
                "diameter": {"expression": "boss_diameter", "unit": "mm"},
                "height": {"expression": "upright_thickness", "unit": "mm"},
                "origin": {
                    "vector": [0, "base_width / 2", "bore_z"],
                    "unit": "mm",
                },
                "axis": [1, 0, 0],
            },
        },
        {
            "id": "joined",
            "kind": "union",
            "role": "joined",
            "description": "Upright blended into the base; the blend is the root fillet",
            "inputs": ["base_plate", "upright", "crown"],
            "parameters": {"blend_radius": {"expression": "root_fillet", "unit": "mm"}},
        },
        {
            "id": "envelope",
            "kind": "box",
            "role": "envelope",
            "description": "Declared outer envelope, used to trim blend overspill",
            "parameters": {
                "size": {
                    "vector": [
                        "base_length",
                        "base_width",
                        "bore_z + boss_diameter / 2",
                    ],
                    "unit": "mm",
                },
                "origin": {"vector": [0, 0, 0], "unit": "mm"},
                "centered": False,
            },
        },
        {
            "id": "trimmed",
            "kind": "intersect",
            "role": "trimmed",
            "inputs": ["joined", "envelope"],
        },
        {
            "id": "shaft_bore",
            "kind": "hole",
            "role": "shaft",
            "description": "Receives the 20 mm shaft",
            "inputs": ["trimmed"],
            "parameters": {
                "diameter": {"expression": "bore_diameter", "unit": "mm"},
                "position": {
                    "vector": ["upright_thickness / 2", "base_width / 2", "bore_z"],
                    "unit": "mm",
                },
                "axis": [1, 0, 0],
                "fit": "clearance_normal",
            },
        },
    ]

    bolt_positions = [
        ("bolt_near_left", "bolt_x1", "bolt_y1"),
        ("bolt_near_right", "bolt_x1", "bolt_y2"),
        ("bolt_far_left", "bolt_x2", "bolt_y1"),
        ("bolt_far_right", "bolt_x2", "bolt_y2"),
    ]
    previous = "shaft_bore"
    for identifier, x_parameter, y_parameter in bolt_positions:
        features.append(
            {
                "id": identifier,
                "kind": "hole",
                "role": identifier,
                "description": "M5 clearance hole",
                "inputs": [previous],
                "parameters": {
                    "diameter": {"expression": "bolt_clearance", "unit": "mm"},
                    "position": {
                        "vector": [x_parameter, y_parameter, 0],
                        "unit": "mm",
                    },
                    "axis": [0, 0, 1],
                    "thread": "none",
                    "fit": "clearance_normal",
                },
            }
        )
        previous = identifier


    if malformed:
        # A decode-time failure: `diameter` belongs to `cylinder`, not `box`.
        # The *decoder* catches this, so the ForgeIR Designer repairs its own
        # output before anything is compiled.
        features[0]["parameters"]["diameter"] = {  # type: ignore[index]
            "magnitude": 40.0,
            "unit": "mm",
        }

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "document_id": "9a1d2f60-0000-4000-8000-000000000010",
        "project_id": "9a1d2f60-0000-4000-8000-0000000000aa",
        "revision": 1,
        "name": "Shaft support bracket",
        "description": (
            "A bracket carrying a 20 mm shaft 32 mm above its mounting face, "
            "bolted down with four M5 fasteners."
        ),
        "risk_class": "low",
        "units": {
            "length": "mm",
            "mass": "kg",
            "time": "s",
            "angle": "deg",
            "force": "N",
            "stress": "MPa",
        },
        "requirements": REQUIREMENTS["requirements"],
        "assumptions": REQUIREMENTS["assumptions"],
        "components": [
            {
                "id": "bracket",
                "name": "Shaft support bracket",
                "material": "aluminium_6061_t6",
                "description": "Base plate with an integral upright carrying the shaft bore.",
                "parameters": [
                    {
                        "id": "base_length",
                        "value": {"magnitude": 70.0, "unit": "mm"},
                        "description": "Overall length of the mounting plate",
                    },
                    {
                        "id": "base_width",
                        "value": {"magnitude": 50.0, "unit": "mm"},
                        "description": "Overall width of the mounting plate",
                    },
                    {
                        "id": "base_thickness",
                        "value": {"magnitude": 8.0, "unit": "mm"},
                        "bounds": {
                            "min": {"magnitude": 5.0, "unit": "mm"},
                            "max": {"magnitude": 14.0, "unit": "mm"},
                        },
                        "optimizable": True,
                        "description": "Plate thickness",
                    },
                    {
                        "id": "upright_thickness",
                        "value": {"magnitude": 12.0, "unit": "mm"},
                        "bounds": {
                            "min": {"magnitude": 8.0, "unit": "mm"},
                            "max": {"magnitude": 20.0, "unit": "mm"},
                        },
                        "optimizable": True,
                        "description": "Thickness of the upright web; the main structural variable",
                    },
                    {
                        "id": "bore_diameter",
                        "value": {"magnitude": 20.0, "unit": "mm"},
                        "description": "Shaft bore diameter",
                    },
                    {
                        "id": "lever_arm",
                        "value": {"magnitude": 32.0, "unit": "mm"},
                        "description": "Shaft axis height above the mounting face; the load's lever arm",
                    },
                    {
                        "id": "boss_diameter",
                        "value": {"magnitude": 36.0, "unit": "mm"},
                        "description": "Diameter of the boss around the bore",
                    },
                    {
                        "id": "root_fillet",
                        "value": {"magnitude": 6.0, "unit": "mm"},
                        "bounds": {
                            "min": {"magnitude": 2.0, "unit": "mm"},
                            "max": {"magnitude": 10.0, "unit": "mm"},
                        },
                        "optimizable": True,
                        "description": "Fillet where the upright meets the base",
                    },
                    {
                        "id": "bolt_clearance",
                        "value": {"magnitude": 5.5, "unit": "mm"},
                        "description": "M5 normal clearance hole",
                    },
                    {
                        "id": "bolt_x1",
                        "value": {"magnitude": 30.0, "unit": "mm"},
                        "description": "First bolt row, measured from the upright face",
                    },
                    {
                        "id": "bolt_x2",
                        "value": {"magnitude": 58.0, "unit": "mm"},
                    },
                    {
                        "id": "bolt_y1",
                        "value": {"magnitude": 12.0, "unit": "mm"},
                    },
                    {
                        "id": "bolt_y2",
                        "value": {"magnitude": 38.0, "unit": "mm"},
                    },
                    {
                        "id": "bore_z",
                        "expression": "base_thickness + lever_arm",
                        "unit": "mm",
                        "description": "Bore axis height in component coordinates",
                    },
                    {
                        "id": "upright_height",
                        "expression": "bore_z - base_thickness + boss_diameter / 2",
                        "unit": "mm",
                        "description": "Upright reaches the top of the boss",
                    },
                ],
                "features": features,
                "interfaces": [
                    {
                        "id": "shaft_port",
                        "type": "bore",
                        "geometry": "shaft.bore",
                        "nominal_size": {"magnitude": 20.0, "unit": "mm"},
                        "fit": "clearance_normal",
                        "load_transfer": "Bearing load from the shaft into the upright.",
                        "allowable_motion": ["rotation_about_axis"],
                        "description": "Receives the 20 mm shaft.",
                    },
                    {
                        "id": "mounting_face",
                        "type": "planar_mount",
                        "geometry": "base.z_min",
                        "load_transfer": "Reaction into the mounting plate.",
                        "description": "Underside of the base plate.",
                    },
                ],
            }
        ],
    }
    return document


def _with_base_thickness(document: dict[str, Any], magnitude: float) -> dict[str, Any]:
    import copy

    copied = copy.deepcopy(document)
    for parameter in copied["components"][0]["parameters"]:
        if parameter["id"] == "base_thickness":
            parameter["value"]["magnitude"] = magnitude
    return copied


DESIGNER_VALID: dict[str, Any] = {
    "rationale": (
        "A base plate with an integral upright at one end. The bore height is "
        "driven by `lever_arm`, and `upright_height` follows from it so the boss "
        "always encloses the bore. The root fillet is a blended union, trimmed "
        "to the declared envelope so the outer dimensions stay exact. "
        "`upright_thickness` is the main structural variable and is bounded."
    ),
    "document": _bracket_document(),
}

#: A *decode-time* failure. The document never reaches the compiler; the
#: designer role's own validation rejects it and repairs it in place.
DESIGNER_MALFORMED: dict[str, Any] = {
    "rationale": "Base plate with an upright carrying the bore.",
    "document": _bracket_document(malformed=True),
}

#: A *compile-time* failure, and a realistic one: the model set a parameter
#: outside bounds it declared itself. Nothing about the document's shape is
#: wrong, so it decodes cleanly and fails when the compiler resolves the value.
DESIGNER_BROKEN: dict[str, Any] = {
    "rationale": "Base plate with an upright carrying the bore.",
    "document": _with_base_thickness(_bracket_document(), 20.0),
}


# A repair the Failure Analyst would propose for DESIGNER_BROKEN: remove the
# parameter that does not belong to a box.
# The repair the Failure Analyst would propose for DESIGNER_BROKEN: bring the
# value back inside the bounds the document itself declares.
ANALYST_FIX_BOUNDS: dict[str, Any] = {
    "diagnosis": (
        "`base_thickness` is set to 20 mm but its own declared bounds are "
        "5 mm to 14 mm. The bounds are part of the design contract, so the value "
        "is what is wrong, not the bounds. 12 mm sits comfortably inside the "
        "range and adds material at the root where the bending moment is highest."
    ),
    "strategy": "bring the value back inside its declared bounds",
    "confidence": "high",
    "abandon": False,
    "patches": [
        {
            "op": "replace",
            "pointer": "/components/0/parameters/2/value",
            "value": {"magnitude": 12.0, "unit": "mm"},
            "reason": "20 mm exceeded the declared maximum of 14 mm",
        }
    ],
}

ANALYST_GIVES_UP: dict[str, Any] = {
    "diagnosis": "The requirement cannot be met by this construction.",
    "strategy": "none",
    "confidence": "high",
    "abandon": True,
    "abandon_reason": (
        "The mass budget cannot be met while the envelope and wall-thickness "
        "requirements both hold; one of them has to change, and that is a "
        "decision for the user rather than a patch."
    ),
    "patches": [],
}

# A repair that proposes the identical edit twice, to exercise oscillation
# detection.
#: A repair that does not actually fix the problem -- 18 mm is still outside the
#: 5-14 mm bounds -- and which the analyst then proposes again. Exercises
#: oscillation detection.
ANALYST_REPEATS: dict[str, Any] = {
    "diagnosis": "The base plate needs to be thicker at the root.",
    "strategy": "thicken the base",
    "confidence": "low",
    "abandon": False,
    "patches": [
        {
            "op": "replace",
            "pointer": "/components/0/parameters/2/value",
            "value": {"magnitude": 18.0, "unit": "mm"},
            "reason": "more material at the root",
        }
    ],
}

#: A patch that cannot apply: the pointer names a key no document has.
#:
#: Observed live on the first run to reach the gate loop -- "pointer names a key
#: that does not exist" on the first of two allowed rounds, after which the run
#: reported blocked with the second round unspent. A patch that will not apply
#: says nothing about whether the design can be fixed.
ANALYST_BAD_POINTER: dict[str, Any] = {
    "diagnosis": "The base is too thin at the root.",
    "strategy": "thicken the base",
    "confidence": "medium",
    "abandon": False,
    "patches": [
        {
            "op": "replace",
            # Addressed by a name no parameter has. (By a name one does
            # have -- `base_thickness` -- a pointer now resolves: a model
            # reads ids, and miscounting positions cost a counterbore.)
            "pointer": "/components/0/parameters/base_thikness/value",
            "value": {"magnitude": 12.0, "unit": "mm"},
            "reason": "addressed by a name nothing has",
        }
    ],
}


__all__ = [
    "BRIEF",
    "BRIEF_UNDERSPECIFIED",
    "INTERPRETER",
    "REQUIREMENTS",
    "DESIGNER_VALID",
    "DESIGNER_BROKEN",
    "DESIGNER_MALFORMED",
    "ANALYST_FIX_BOUNDS",
    "ANALYST_GIVES_UP",
    "ANALYST_REPEATS",
    "ANALYST_BAD_POINTER",
]


# ----------------------------------------------------------------------
# The underspecified path: a brief that cannot be designed honestly.
#
# Shared with the CLI tests, because "it asks instead of inventing" has to hold
# at the command line too -- that is where it would be least noticed if it
# stopped holding.
REQUIREMENTS_UNDERSPECIFIED: dict[str, Any] = {
    "risk_class": "moderate",
    "requirements": [
        {
            "id": "REQ_HOLDS_SHAFT",
            "statement": "The bracket shall retain a shaft.",
            "type": "functional",
            "strength": "hard",
            "verification": "exact_geometry",
            "source": "user",
            "state": "proposed",
        }
    ],
    "assumptions": [],
    "unknowns": [
        {
            "id": "UNK_SHAFT_DIAMETER",
            "question": "What diameter is the shaft?",
            "why_it_matters": "Every dimension of the bracket follows from it.",
            "blocks": ["REQ_HOLDS_SHAFT"],
            "critical": True,
        },
        {
            "id": "UNK_LOAD",
            "question": "What load does the shaft carry, and in what direction?",
            "why_it_matters": (
                "'Strong enough' is not checkable. Without a load there is "
                "nothing to size the bracket against."
            ),
            "blocks": ["REQ_HOLDS_SHAFT"],
            "critical": True,
        },
    ],
}

QUESTIONS: dict[str, Any] = {
    "questions": [
        {
            "id": "UNK_LOAD",
            "question": "What load does the shaft carry, and in what direction?",
            "why": "Nothing can be sized or verified without it.",
            "priority": 1.0,
        },
        {
            "id": "UNK_SHAFT_DIAMETER",
            "question": "What diameter is the shaft?",
            "why": "Sets the bore and drives every other dimension.",
            "options": ["8 mm", "10 mm", "12 mm", "20 mm"],
            "priority": 0.9,
        },
    ]
}
