"""One hard brief, all the way through, with the model's part written by hand.

Every other suite tests a stage. This one tests that the stages still compose:
a brief with twelve stated quantities becomes a requirement set that covers all
of them, becomes a document that passes every role-level check, compiles,
measures, and clears eighteen gates without a single failure or block.

It exists because "each part works" and "the thing works" are different claims,
and only the second one is what a user gets. Every fix in this system was made
against a run that failed somewhere in the seams: a requirement bound to the
wrong measurement, a hole cut before the union that filled it in, a count that
matched five holes when the user meant four, a component the verifier never
looked at. A test that only ever exercises the happy path of one stage cannot
see any of those.

The model's answers are written out here as a competent model would write them.
That is the point: it fixes what "good" looks like for this brief, so a change
that makes a correct answer unacceptable fails here rather than in front of
somebody watching a local model think for an hour.
"""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from forge_evidence import Status
from forge_ir import Document
from forge_pipeline import verify_component
from forge_roles import ForgeIRDesigner, RequirementsEngineer

BRIEF = (
    "A 3D-printed motor mount plate in PLA. The base plate is 60 mm long, "
    "40 mm wide and 6 mm thick. A cylindrical boss 18 mm in diameter and "
    "25 mm tall stands in the middle of the plate, with a 2 mm fillet where "
    "the boss meets the plate. An 8 mm shaft bore runs all the way through "
    "the boss and the plate, on the boss axis. Four 4.5 mm mounting holes "
    "pass all the way through the plate on a 44 mm by 24 mm rectangular "
    "pattern centred on the plate. The finished part must stand no taller "
    "than 32 mm and weigh no more than 30 g. It carries no structural load - "
    "it is a printed fixture, so there is no load case."
)


def _requirement(
    identifier: str,
    statement: str,
    magnitude: float,
    unit: str,
    measurement: str,
    comparison: str = "equals",
    requirement_type: str = "geometric",
) -> dict[str, Any]:
    return {
        "id": identifier,
        "statement": statement,
        "type": requirement_type,
        "strength": "hard",
        "verification": "exact_geometry",
        "threshold": {"magnitude": magnitude, "unit": unit},
        "comparison": comparison,
        "measurement": measurement,
        "source": "user",
        "state": "accepted",
    }


REQUIREMENTS_ANSWER: dict[str, Any] = {
    "risk_class": "low",
    "requirements": [
        _requirement("REQ_PLATE_LENGTH", "The base plate shall be 60 mm long.",
                     60.0, "mm", "parameter:plate_length"),
        _requirement("REQ_PLATE_WIDTH", "The base plate shall be 40 mm wide.",
                     40.0, "mm", "parameter:plate_width"),
        _requirement("REQ_PLATE_THICKNESS", "The base plate shall be 6 mm thick.",
                     6.0, "mm", "parameter:plate_thickness"),
        _requirement("REQ_BOSS_DIAMETER", "The boss shall be 18 mm in diameter.",
                     18.0, "mm", "parameter:boss_diameter"),
        _requirement("REQ_BOSS_HEIGHT", "The boss shall stand 25 mm tall.",
                     25.0, "mm", "parameter:boss_height"),
        _requirement("REQ_FILLET", "The boss shall meet the plate with a 2 mm fillet.",
                     2.0, "mm", "parameter:fillet_radius"),
        _requirement("REQ_SHAFT_BORE", "The shaft bore shall be 8 mm in diameter.",
                     8.0, "mm", "parameter:shaft_bore"),
        _requirement("REQ_BOLT_DIAMETER", "Each mounting hole shall be 4.5 mm.",
                     4.5, "mm", "parameter:bolt_hole_diameter"),
        _requirement("REQ_BOLT_PITCH_X", "The holes shall be 44 mm apart along x.",
                     44.0, "mm", "parameter:bolt_pitch_x"),
        _requirement("REQ_BOLT_PITCH_Y", "The holes shall be 24 mm apart along y.",
                     24.0, "mm", "parameter:bolt_pitch_y"),
        _requirement("REQ_BOLT_COUNT", "There shall be four mounting holes.",
                     4.0, "", "feature_count:hole:mounting"),
        _requirement("REQ_HEIGHT", "The part shall stand no taller than 32 mm.",
                     32.0, "mm", "bounding_box_z", "at_most", "performance"),
        _requirement("REQ_MASS", "The part shall weigh no more than 30 g.",
                     30.0, "g", "mass", "at_most", "performance"),
    ],
    "assumptions": [],
    "unknowns": [],
}


def _parameter(identifier: str, magnitude: float) -> dict[str, Any]:
    return {"id": identifier, "value": {"magnitude": magnitude, "unit": "mm"}}


def _hole(
    identifier: str, previous: str, diameter: str, x: Any, y: Any,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    feature: dict[str, Any] = {
        "id": identifier,
        "kind": "hole",
        "inputs": [previous],
        "parameters": {
            "diameter": {"expression": diameter},
            "position": {"vector": [x, y, 0], "unit": "mm"},
        },
    }
    if tags:
        feature["tags"] = tags
    return feature


DESIGNER_ANSWER: dict[str, Any] = {
    "rationale": "A plate and a boss unioned with a fillet, then every hole "
                 "cut from the finished body.",
    "document": {
        "name": "Motor mount plate",
        "components": [
            {
                "id": "mount",
                "name": "Motor mount plate",
                "material": "pla_fdm",
                "parameters": [
                    _parameter("plate_length", 60),
                    _parameter("plate_width", 40),
                    _parameter("plate_thickness", 6),
                    _parameter("boss_diameter", 18),
                    _parameter("boss_height", 25),
                    _parameter("fillet_radius", 2),
                    _parameter("shaft_bore", 8),
                    _parameter("bolt_hole_diameter", 4.5),
                    _parameter("bolt_pitch_x", 44),
                    _parameter("bolt_pitch_y", 24),
                ],
                "features": [
                    {"id": "plate", "kind": "box", "parameters": {
                        "size": {"vector": ["plate_length", "plate_width",
                                            "plate_thickness"], "unit": "mm"},
                        "centered": True}},
                    {"id": "boss", "kind": "cylinder", "parameters": {
                        "diameter": {"expression": "boss_diameter"},
                        "height": {"expression": "boss_height"},
                        "origin": {"vector": [0, 0, "plate_thickness / 2"],
                                   "unit": "mm"}}},
                    {"id": "body", "kind": "union", "inputs": ["plate", "boss"],
                     "parameters": {
                         "blend_radius": {"expression": "fillet_radius"}}},
                    _hole("shaft_hole", "body", "shaft_bore", 0, 0),
                    _hole("bolt_1", "shaft_hole", "bolt_hole_diameter",
                          "-bolt_pitch_x / 2", "-bolt_pitch_y / 2", ["mounting"]),
                    _hole("bolt_2", "bolt_1", "bolt_hole_diameter",
                          "bolt_pitch_x / 2", "-bolt_pitch_y / 2", ["mounting"]),
                    _hole("bolt_3", "bolt_2", "bolt_hole_diameter",
                          "-bolt_pitch_x / 2", "bolt_pitch_y / 2", ["mounting"]),
                    _hole("bolt_4", "bolt_3", "bolt_hole_diameter",
                          "bolt_pitch_x / 2", "bolt_pitch_y / 2", ["mounting"]),
                ],
                "interfaces": [],
            }
        ],
    },
}


class TheWholeChainOnOneHardBrief(unittest.TestCase):
    """Brief to verdict, with only the model's two answers written by hand."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.requirements = RequirementsEngineer().parse(
            REQUIREMENTS_ANSWER, brief=BRIEF
        )
        draft = ForgeIRDesigner().parse(
            DESIGNER_ANSWER,
            requirements=cls.requirements,
            document_id="00000000-0000-4000-8000-00000000c001",
            project_id="00000000-0000-4000-8000-00000000c0ff",
        )
        payload = dict(draft.payload)
        payload["requirements"] = [dict(r) for r in cls.requirements.requirements]
        payload["assumptions"] = []
        cls.document = Document.from_json(json.dumps(payload))
        cls.report = verify_component(
            cls.document,
            cls.document.components[0],
            measurement_depth=7,
            mesh_resolution=64,
        )

    def test_every_number_in_the_brief_is_covered(self) -> None:
        from forge_roles.library import _covers, _numbers_the_brief_states

        thresholds = [
            r.threshold for r in self.document.requirements
            if r.threshold is not None
        ]
        for quantity in _numbers_the_brief_states(BRIEF):
            self.assertTrue(
                _covers(quantity, thresholds),
                f"{quantity} was stated in the brief and nothing checks it",
            )

    def test_it_is_one_component(self) -> None:
        self.assertEqual(len(self.document.components), 1)

    def test_the_holes_are_cut_from_the_finished_body(self) -> None:
        """The defect that printed a pocket instead of a hole."""
        result = next(
            r for r in self.report.gate_results
            if r.gate.identifier == "GEOM_THROUGH_HOLES_OPEN"
        )
        self.assertIs(result.status, Status.PASS)
        self.assertEqual(len(result.evidence.detail["checked"]), 5)

    def test_the_count_sees_four_holes_and_not_five(self) -> None:
        """Four mounting holes and a shaft bore is five `hole` features."""
        result = next(
            r for r in self.report.gate_results
            if r.gate.identifier == "REQ_BOLT_COUNT"
        )
        self.assertIs(result.status, Status.PASS)
        self.assertEqual(str(result.evidence.result), "4")

    def test_nothing_fails_and_nothing_is_blocked(self) -> None:
        not_passing = [
            f"{r.gate.identifier}={r.status.value}"
            for r in self.report.gate_results
            if r.status is not Status.PASS
        ]
        self.assertEqual(not_passing, [])

    def test_the_verdict_is_a_release_candidate(self) -> None:
        self.assertIs(self.report.overall_status, Status.PASS)
        self.assertEqual(self.report.release_reasons, ())

    def test_there_is_a_part_to_open(self) -> None:
        """The whole point: a closed solid somebody can slice."""
        self.assertTrue(self.report.measurements["watertight"])
        mesh_volume = float(self.report.measurements["mesh_volume"].split()[0])
        self.assertGreater(mesh_volume, 10_000.0)
        self.assertLess(mesh_volume, 30_000.0)


# ----------------------------------------------------------------------
# The same chain on a smaller part.
#
# The motor mount above is the hard case. This is the one to hand somebody
# whose model takes a quarter of an hour per attempt: two thirds of the
# features, three quarters of the numbers, and every path the hard one
# exercises -- a boolean joining two solids, a fillet on it, through holes cut
# after it, a tagged count, a named-parameter binding for every dimension, a
# material that has to resolve to a real grade for the mass to be computable.
# ----------------------------------------------------------------------
QUICK_BRIEF = (
    "A 3D-printed PLA spacer block. The base is a 30 mm square plate 4 mm "
    "thick. A 12 mm diameter post 10 mm tall stands in the middle of it, with "
    "a 2 mm fillet where the post meets the plate. A 5 mm hole runs all the "
    "way through the post and the plate. Two 3 mm mounting holes pass all the "
    "way through the plate, 20 mm apart. It must weigh no more than 8 g. It "
    "carries no load - it is a printed spacer, so there is no load case."
)


def _quick_hole(
    identifier: str, previous: str, diameter: str, x: Any,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    feature: dict[str, Any] = {
        "id": identifier, "kind": "hole", "inputs": [previous],
        "parameters": {
            "diameter": {"expression": diameter},
            "position": {"vector": [x, 0, 0], "unit": "mm"},
        },
    }
    if tags:
        feature["tags"] = tags
    return feature


QUICK_REQUIREMENTS: dict[str, Any] = {
    "risk_class": "low", "assumptions": [], "unknowns": [],
    "requirements": [
        _requirement("REQ_PLATE_SIZE", "The base plate shall be 30 mm square.",
                     30.0, "mm", "parameter:plate_size"),
        _requirement("REQ_PLATE_THICKNESS", "The plate shall be 4 mm thick.",
                     4.0, "mm", "parameter:plate_thickness"),
        _requirement("REQ_POST_DIAMETER", "The post shall be 12 mm across.",
                     12.0, "mm", "parameter:post_diameter"),
        _requirement("REQ_POST_HEIGHT", "The post shall stand 10 mm tall.",
                     10.0, "mm", "parameter:post_height"),
        _requirement("REQ_FILLET", "The junction shall carry a 2 mm fillet.",
                     2.0, "mm", "parameter:fillet_radius"),
        _requirement("REQ_BORE", "The central hole shall be 5 mm.",
                     5.0, "mm", "parameter:bore_diameter"),
        _requirement("REQ_BOLT_DIAMETER", "Each mounting hole shall be 3 mm.",
                     3.0, "mm", "parameter:bolt_diameter"),
        _requirement("REQ_BOLT_SPACING", "The holes shall be 20 mm apart.",
                     20.0, "mm", "parameter:bolt_spacing"),
        _requirement("REQ_BOLT_COUNT", "There shall be two mounting holes.",
                     2.0, "", "feature_count:hole:mounting"),
        _requirement("REQ_MASS", "The part shall weigh no more than 8 g.",
                     8.0, "g", "mass", "at_most", "performance"),
    ],
}

QUICK_DESIGN: dict[str, Any] = {
    "rationale": "Plate and post unioned with a fillet, then the holes.",
    "document": {"name": "Spacer block", "components": [{
        "id": "spacer", "name": "Spacer block", "material": "pla_fdm",
        "parameters": [
            _parameter("plate_size", 30), _parameter("plate_thickness", 4),
            _parameter("post_diameter", 12), _parameter("post_height", 10),
            _parameter("fillet_radius", 2), _parameter("bore_diameter", 5),
            _parameter("bolt_diameter", 3), _parameter("bolt_spacing", 20),
        ],
        "features": [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": ["plate_size", "plate_size",
                                    "plate_thickness"], "unit": "mm"},
                "centered": True}},
            {"id": "post", "kind": "cylinder", "parameters": {
                "diameter": {"expression": "post_diameter"},
                "height": {"expression": "post_height"},
                "origin": {"vector": [0, 0, "plate_thickness / 2"],
                           "unit": "mm"}}},
            {"id": "body", "kind": "union", "inputs": ["plate", "post"],
             "parameters": {"blend_radius": {"expression": "fillet_radius"}}},
            _quick_hole("bore", "body", "bore_diameter", 0),
            _quick_hole("bolt_1", "bore", "bolt_diameter",
                        "-bolt_spacing / 2", ["mounting"]),
            _quick_hole("bolt_2", "bolt_1", "bolt_diameter",
                        "bolt_spacing / 2", ["mounting"]),
        ],
        "interfaces": [],
    }]},
}


class TheSameChainOnASmallerPart(unittest.TestCase):
    """The brief to hand somebody whose model thinks for a quarter of an hour."""

    @classmethod
    def setUpClass(cls) -> None:
        requirements = RequirementsEngineer().parse(
            QUICK_REQUIREMENTS, brief=QUICK_BRIEF
        )
        draft = ForgeIRDesigner().parse(
            QUICK_DESIGN,
            requirements=requirements,
            document_id="00000000-0000-4000-8000-00000000d001",
            project_id="00000000-0000-4000-8000-00000000d0ff",
        )
        payload = dict(draft.payload)
        payload["requirements"] = [dict(r) for r in requirements.requirements]
        payload["assumptions"] = []
        cls.document = Document.from_json(json.dumps(payload))
        cls.report = verify_component(
            cls.document, cls.document.components[0],
            measurement_depth=7, mesh_resolution=64,
        )

    def test_every_number_in_the_brief_is_covered(self) -> None:
        from forge_roles.library import _covers, _numbers_the_brief_states

        thresholds = [
            r.threshold for r in self.document.requirements
            if r.threshold is not None
        ]
        for quantity in _numbers_the_brief_states(QUICK_BRIEF):
            self.assertTrue(
                _covers(quantity, thresholds),
                f"{quantity} was stated and nothing checks it",
            )

    def test_it_exercises_what_the_hard_brief_exercises(self) -> None:
        """Smaller must not mean it stops testing the things that broke."""
        kinds = [f.kind for f in self.document.components[0].features]
        self.assertIn("union", kinds)
        self.assertEqual(kinds.count("hole"), 3)
        self.assertEqual(kinds.index("union"), min(
            index for index, kind in enumerate(kinds) if kind == "hole"
        ) - 1, "the holes must be cut after the union")
        self.assertEqual(self.document.components[0].material, "pla_fdm")

    def test_nothing_fails_and_nothing_is_blocked(self) -> None:
        not_passing = [
            f"{r.gate.identifier}={r.status.value}"
            for r in self.report.gate_results
            if r.status is not Status.PASS
        ]
        self.assertEqual(not_passing, [])
        self.assertIs(self.report.overall_status, Status.PASS)

    def test_the_count_sees_two_and_not_three(self) -> None:
        result = next(
            r for r in self.report.gate_results
            if r.gate.identifier == "REQ_BOLT_COUNT"
        )
        self.assertEqual(str(result.evidence.result), "2")


# ----------------------------------------------------------------------
# The spacer block: the brief that took a week, with the model's real answers
# ----------------------------------------------------------------------
SPACER_BRIEF = (
    "A 3D-printed PLA spacer block. The base is a 30 mm square plate 4 mm "
    "thick. A 12 mm diameter post 10 mm tall stands in the middle of it, with "
    "a 2 mm fillet where the post meets the plate. A 5 mm hole runs all the "
    "way through the post and the plate. Two 3 mm mounting holes pass all the "
    "way through the plate, 20 mm apart. It must weigh no more than 8 g. It "
    "carries no load - it is a printed spacer, so there is no load case."
)

SPACER_PAIRS = [
    ("plate_size_x", 30.0), ("plate_size_y", 30.0), ("plate_thickness", 4.0),
    ("post_diameter", 12.0), ("post_height", 10.0), ("fillet_thickness", 2.0),
    ("hole_diameter", 5.0), ("mounting_hole_diameter", 3.0),
    ("mounting_hole_distance", 20.0),
]

#: Exactly what qwen2.5-coder:3b returned, from the run record. Note what it
#: leaves out and gets wrong -- the empty `whole_part`, so nothing checks the
#: 8 g; the margin on a part the brief says carries no load. Both are Forge's
#: to settle, and this fixture exists to keep them settled.
SPACER_REQUIREMENTS_ANSWER = {
    "risk_class": "low", "assumptions": [], "unknowns": [],
    "requirements": {
        "whole_part": {},
        "dimensions": [
            {"parameter": name, "statement": f"{name} is {value} mm",
             "comparison": "equals",
             "threshold": {"magnitude": value, "unit": "mm"}}
            for name, value in SPACER_PAIRS
        ],
        "counts": [{
            "feature_kind": "hole", "tag": "mounting",
            "statement": "Two mounting holes.", "comparison": "equals",
            "threshold": {"magnitude": 2, "unit": ""}}],
        "safety_factors": [{
            "against": "bearing",
            "statement": "A bearing margin of at least 2.",
            "comparison": "at_least",
            "threshold": {"magnitude": 2.0, "unit": ""}}],
    },
}


def _spacer_hole(identifier, diameter, position, axis, tags=None):
    feature = {
        "id": identifier, "kind": "hole",
        "parameters": {
            "diameter": {"expression": diameter, "unit": "mm"},
            "position": {"vector": position, "unit": "mm"},
            "axis": axis, "fit": "clearance_normal"},
    }
    if tags:
        feature["tags"] = tags
    return feature


#: Also verbatim. Every parameter right, every dimension right -- and the two
#: mounting holes spread along x while drilled along x, which makes them one
#: line and refuses the document. No `material`, no `inputs` on the holes.
SPACER_DESIGNER_ANSWER = {
    "rationale": "A plate, a blended post, and three holes.",
    "document": {"name": "Spacer Block", "components": [{
        "id": "spacer_block",
        "parameters": [
            {"id": name, "value": {"magnitude": value, "unit": "mm"}}
            for name, value in SPACER_PAIRS
        ],
        "features": [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": ["plate_size_x", "plate_size_y",
                                    "plate_thickness"], "unit": "mm"},
                "centered": True}},
            {"id": "post", "kind": "cylinder", "parameters": {
                "diameter": {"expression": "post_diameter", "unit": "mm"},
                "height": {"expression": "post_height", "unit": "mm"},
                "origin": {"vector": [0, 0, "plate_thickness / 2"],
                           "unit": "mm"}}},
            {"id": "body", "kind": "union", "inputs": ["base", "post"],
             "parameters": {
                 "blend_radius": {"expression": "fillet_thickness"}}},
            _spacer_hole("hole", "hole_diameter",
                         [0, 0, "plate_thickness / 2"], [0.0, 0.0, 1.0]),
            _spacer_hole("mounting_hole_1", "mounting_hole_diameter",
                         ["mounting_hole_distance / 2", 0,
                          "plate_thickness / 2"],
                         [1.0, 0.0, 0.0], ["mounting"]),
            _spacer_hole("mounting_hole_2", "mounting_hole_diameter",
                         ["-mounting_hole_distance / 2", 0,
                          "plate_thickness / 2"],
                         [1.0, 0.0, 0.0], ["mounting"]),
        ],
    }]},
}


def _highest(quantity: Any) -> float:
    """The top of a measured quantity, whether or not it carries an interval.

    A dimension read off the parameter table is an exact number; a mass
    measured on an octree is an interval. Both arrive here as `Quantity`.
    """
    magnitude = quantity.magnitude
    return float(getattr(magnitude, "hi", magnitude))


class TheSpacerBlockTheUserActuallyAskedFor(unittest.TestCase):
    """The brief that took a week, driven by the model's real answers.

    Every other end-to-end test here is written by hand to be correct. This
    one is not: both answers are transcribed from run records, faults and
    all, because the faults are the point. Between them they exercise every
    repair Forge learned this week --

      * a margin on a part whose brief says there is no load case
      * an empty whole-part mass slot, on a brief that states a weight limit
      * two holes spread along the very axis they are drilled down
      * holes with no `inputs`, left hanging off the same body
      * no `material`, so no density, so no mass could be computed at all

    -- and the assertion is not that any one of them fired, but that the part
    comes out right.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from forge_roles.library import Intent

        cls.requirements = RequirementsEngineer().parse(
            copy.deepcopy(SPACER_REQUIREMENTS_ANSWER), brief=SPACER_BRIEF)
        cls.draft = ForgeIRDesigner().parse(
            copy.deepcopy(SPACER_DESIGNER_ANSWER),
            requirements=cls.requirements,
            intent=Intent(
                summary="A 3D-printed PLA spacer block", part_kind="spacer",
                stated=("A 3D-printed PLA spacer block",),
                implied=(), unstated=()),
            document_id="00000000-0000-4000-8000-00000000d001",
            project_id="00000000-0000-4000-8000-00000000d0ff",
        )
        payload = dict(cls.draft.payload)
        payload["requirements"] = [
            dict(r) for r in cls.requirements.requirements]
        payload["assumptions"] = []
        cls.document = Document.from_json(json.dumps(payload))
        cls.report = verify_component(
            cls.document, cls.document.components[0],
            measurement_depth=7, mesh_resolution=64)

    def test_the_part_passes(self) -> None:
        self.assertEqual(self.report.overall_status, Status.PASS)
        self.assertEqual(list(self.report.release_reasons or []), [])

    def test_nothing_failed(self) -> None:
        failed = [
            r.gate.identifier for r in self.report.gate_results
            if r.status is Status.FAIL
        ]
        self.assertEqual(failed, [])

    def test_all_three_holes_are_in_the_part(self) -> None:
        part = self.report.measurements["part"]
        self.assertEqual(part["open_holes"], 3)
        self.assertTrue(all(h["present"] for h in part["holes"]))
        self.assertEqual(part["features_without_a_surface"], [])

    def test_the_weight_limit_the_model_omitted_is_checked_and_met(
        self,
    ) -> None:
        """The model left the mass slot empty; Forge bound the brief's own
        limit. Without it nothing would have weighed the part at all."""
        mass = [
            r for r in self.report.gate_results
            if r.gate.identifier == "REQ_MASS"
        ]
        self.assertEqual(len(mass), 1)
        self.assertEqual(mass[0].status, Status.PASS)
        # The measured mass is an interval, so the whole of it must be under
        # the limit -- not just its midpoint.
        self.assertLess(_highest(mass[0].evidence.result), 8.0)

    def test_every_dimension_the_brief_states_is_measured_and_right(
        self,
    ) -> None:
        by_identifier = {
            r.gate.identifier: r for r in self.report.gate_results}
        for name, value in SPACER_PAIRS:
            identifier = f"REQ_{name.upper()}"
            with self.subTest(requirement=identifier):
                self.assertIn(identifier, by_identifier)
                result = by_identifier[identifier]
                self.assertEqual(result.status, Status.PASS)
                self.assertAlmostEqual(
                    _highest(result.evidence.result), value, places=3)

    def test_the_margin_on_a_part_with_no_load_is_gone(self) -> None:
        self.assertNotIn(
            "REQ_SF_BEARING",
            [dict(r)["id"] for r in self.requirements.requirements])

    def test_every_requirement_forge_produced_fits_the_document(self) -> None:
        """The invariant that would have caught the bug this test was written
        after: `REQ_MASS` was added by a repair that ran *after* the defaults
        pass, so it reached the document with no `type` and the whole design
        was refused at the last step -- blaming the requirements engineer for
        something Forge itself had added.

        Checked over every requirement rather than that one, so a repair
        added later cannot reintroduce it."""
        for requirement in self.requirements.requirements:
            entry = dict(requirement)
            with self.subTest(requirement=entry.get("id")):
                for field in ("type", "strength", "verification", "source",
                              "state"):
                    self.assertIn(field, entry)

    def test_forge_says_what_it_settled(self) -> None:
        """A document that differs from what the model wrote has to say so."""
        said = " ".join(self.draft.notes) + " " + " ".join(
            self.requirements.notes)
        for expected in ("one line", "material", "REQ_MASS", "no load"):
            with self.subTest(note=expected):
                self.assertIn(expected, said)


# ----------------------------------------------------------------------
# A part with nothing in common with the spacer, to keep the repairs honest
# ----------------------------------------------------------------------
BRACKET_BRIEF = (
    "A machined aluminium mounting bracket. The base is a 60 mm by 40 mm "
    "plate 8 mm thick. A 20 mm diameter boss 15 mm tall rises from the "
    "middle, with a 3 mm fillet at its root. A 10 mm bore runs through the "
    "boss and the plate. Four 6 mm bolt holes pass through the plate, 44 mm "
    "apart. It carries a static load at the boss."
)

BRACKET_PAIRS = [
    ("plate_length", 60.0), ("plate_width", 40.0), ("plate_thickness", 8.0),
    ("boss_diameter", 20.0), ("boss_height", 15.0), ("fillet_radius", 3.0),
    ("bore_diameter", 10.0), ("bolt_hole_diameter", 6.0),
    ("bolt_hole_spacing", 44.0),
]


class TheSameRepairsOnAPartWithNothingInCommon(unittest.TestCase):
    """Proof the repairs are rules, not memories of one brief.

    Different material, a real load case, four bolt holes instead of two, a
    different tag word, no weight limit at all -- and the design carries the
    same faults the local model actually makes. Every assertion here is about
    a repair either firing for the right reason or *declining* for the right
    reason, because a repair that fires everywhere is as bad as one that
    fires nowhere.

    This test earned its place immediately: the collinear-hole re-aim it was
    written to exercise did not fire at all. That repair compared every hole
    against the first one, so the central bore -- which differs from the bolt
    holes in two components at once -- merged into the comparison and no
    single offset direction came out of it. The spacer has only two mounting
    holes, so the group-wide comparison happened to be a pairwise one there
    and the bug was invisible. It reasons pairwise now.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from forge_roles.library import Intent

        def hole(identifier, diameter, position, inputs):
            return {
                "id": identifier, "kind": "hole", "inputs": inputs,
                "tags": ["bolt"],
                "parameters": {
                    "diameter": {"expression": diameter, "unit": "mm"},
                    "position": {"vector": position, "unit": "mm"},
                    # Spread over x and y, drilled along x: one line, twice.
                    "axis": [1.0, 0.0, 0.0]},
            }

        cls.requirements = RequirementsEngineer().parse({
            "risk_class": "moderate",
            "assumptions": [{
                "id": "ASM_LOAD",
                "statement": "A 400 N static load acts down on the boss.",
                "value": {"magnitude": 400.0, "unit": "N"}, "risk": "high",
                "reversible": False, "approved": False,
                "consequence_if_wrong": "Every margin is invalidated."}],
            "unknowns": [],
            "requirements": {
                "whole_part": {},
                "dimensions": [
                    {"parameter": name, "statement": name,
                     "comparison": "equals",
                     "threshold": {"magnitude": value, "unit": "mm"}}
                    for name, value in BRACKET_PAIRS],
                "counts": [{
                    "feature_kind": "hole", "tag": "bolt",
                    "statement": "Four bolt holes.", "comparison": "equals",
                    "threshold": {"magnitude": 4, "unit": ""}}],
                "safety_factors": [{
                    "against": "bearing",
                    "statement": "A bearing margin of at least 2.",
                    "comparison": "at_least",
                    "threshold": {"magnitude": 2.0, "unit": ""}}]}},
            brief=BRACKET_BRIEF)

        answer = {"rationale": "r", "document": {
            "name": "Bracket", "components": [{
                "id": "bracket",
                "parameters": [
                    {"id": name, "value": {"magnitude": value, "unit": "mm"}}
                    for name, value in BRACKET_PAIRS],
                "features": [
                    {"id": "plate", "kind": "box", "parameters": {
                        "size": {"vector": ["plate_length", "plate_width",
                                            "plate_thickness"], "unit": "mm"},
                        "centered": True}},
                    {"id": "boss", "kind": "cylinder", "parameters": {
                        "diameter": {"expression": "boss_diameter",
                                     "unit": "mm"},
                        "height": {"expression": "boss_height", "unit": "mm"},
                        "origin": {"vector": [0, 0, "plate_thickness / 2"],
                                   "unit": "mm"}}},
                    {"id": "body", "kind": "union",
                     "inputs": ["plate", "boss"], "parameters": {
                         "blend_radius": {"expression": "fillet_radius"}}},
                    hole("bore", "bore_diameter", [0, 0, 0], ["body"]),
                    hole("b1", "bolt_hole_diameter",
                         ["bolt_hole_spacing / 2", 12, 0], ["bore"]),
                    hole("b2", "bolt_hole_diameter",
                         ["-bolt_hole_spacing / 2", 12, 0], ["b1"]),
                    hole("b3", "bolt_hole_diameter",
                         ["bolt_hole_spacing / 2", -12, 0], ["b2"]),
                    hole("b4", "bolt_hole_diameter",
                         ["-bolt_hole_spacing / 2", -12, 0], ["b3"]),
                ]}]}}
        cls.draft = ForgeIRDesigner().parse(
            copy.deepcopy(answer), requirements=cls.requirements,
            intent=Intent(summary="A machined aluminium mounting bracket",
                          part_kind="bracket",
                          stated=("A machined aluminium mounting bracket",),
                          implied=(), unstated=()),
            document_id="00000000-0000-4000-8000-00000000e001",
            project_id="00000000-0000-4000-8000-00000000e0ff")
        cls.component = cls.draft.payload["components"][0]

    # -- what must fire ------------------------------------------------
    def test_four_collinear_bolt_holes_are_re_aimed(self) -> None:
        axes = {
            f["id"]: f["parameters"].get("axis")
            for f in self.component["features"] if f["kind"] == "hole"
        }
        for bolt in ("b1", "b2", "b3", "b4"):
            with self.subTest(hole=bolt):
                self.assertEqual(axes[bolt], [0.0, 0.0, 1.0])

    def test_the_bore_is_not_re_aimed_with_them(self) -> None:
        """It is not collinear with anything, so nothing about it is proven
        wrong. Re-aiming it would be Forge inventing a design decision."""
        axes = {
            f["id"]: f["parameters"].get("axis")
            for f in self.component["features"] if f["kind"] == "hole"
        }
        self.assertEqual(axes["bore"], [1.0, 0.0, 0.0])

    def test_the_over_applied_tag_is_trimmed_to_the_four(self) -> None:
        """A different tag word, a different count, the same structural rule:
        four features defined alike, one that is not."""
        tagged = [
            f["id"] for f in self.component["features"]
            if "bolt" in (f.get("tags") or [])
        ]
        self.assertEqual(sorted(tagged), ["b1", "b2", "b3", "b4"])

    # -- what must NOT fire --------------------------------------------
    def test_the_margin_survives_because_this_part_carries_a_load(
        self,
    ) -> None:
        """The same code that strips the margin from the spacer must leave it
        here. A repair that fires everywhere is as bad as one that never
        fires."""
        self.assertIn(
            "REQ_SF_BEARING",
            [dict(r)["id"] for r in self.requirements.requirements])

    def test_no_mass_requirement_is_invented(self) -> None:
        """This brief states no weight, so there is nothing to bind."""
        self.assertEqual(
            [], [dict(r)["id"] for r in self.requirements.requirements
                 if dict(r).get("measurement") == "mass"])

    def test_a_family_name_is_a_grade_to_approve_where_a_margin_depends_on_it(
        self,
    ) -> None:
        """"Aluminium" names a family whose strength varies threefold, and
        this part has a bearing margin. Forge does not quietly pick a grade:
        the one it knows is computed for under an assumption, unapproved and
        high risk, so the part is held until the user says it is that grade.
        (It used to leave the material empty, and the margin -- the one thing
        a loaded brief asks to be checked -- could not be computed at all.)"""
        self.assertEqual(self.component.get("material"), "aluminium_6061_t6")
        grade = next(dict(a) for a in self.requirements.assumptions
                     if dict(a)["id"] == "ASM_MATERIAL_GRADE")
        self.assertFalse(grade["approved"])
        self.assertEqual(grade["risk"], "high")

    def test_the_load_assumption_is_kept(self) -> None:
        self.assertEqual(
            [dict(a)["id"] for a in self.requirements.assumptions],
            ["ASM_LOAD", "ASM_MATERIAL_GRADE"])
