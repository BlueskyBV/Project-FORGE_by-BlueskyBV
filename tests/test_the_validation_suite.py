"""The V1 validation suite's regression tier on Claude Sonnet 5, 17 October
2026: twelve of fourteen as expected, two not -- both Forge's.

- R10, the loaded cantilever, failed before a design was asked for: the
  record assumed "6061-T6 aluminium" as `ASM_MATERIAL_GRADE`, and Forge,
  not recognising the grade in those words, appended its own assumption
  under the same id. The document refuses two of one id.
- R12, the two-set-screw collar, passed every check and was held BLOCKED
  for `ASM_SOLID_COLLAR`: "a solid (non-split) cylinder ... with no slit or
  clamping flange", moderate risk, marked irreversible. The brief never
  mentions a split; Forge draws what the brief describes and nothing more.

Tier P, the same day: thirteen of fourteen. P11, the torus, was released
wrong with every claim passing: "an 8 mm round section bent into a full
ring 40 mm across at the centre line of the section" is a ring 48 mm
across, and Forge claimed 40 on X and Y. The first design was right and
failed those claims; the redesign built the ring on a 32 mm middle under a
parameter still called 40.

Tier H: nine of ten graded OK, and one of the nine was wrong. H03's plate
was released with one counterbore where the brief asked for two: Forge read
"two counterbored holes ...: each a 5.5 mm through hole with a 10 mm
counterbore" as one, the repair took the second off to obey, and the last
look, which saw it and put it back, was reverted. H07, three holes crossing
at the centre, passed every check and was held for an assumption that said
the brief back in other words.

Tier C, 18 October: eleven of sixteen, and every one of the five was
Forge's. The shaft and the dumbbell were blended where the brief asked for
no blend, then held for assumptions that said the brief back (or that the
part is one piece, which Forge always builds); the dumbbell's bar was also
stood up by Forge's `lies` against the design's own placements. The cup was
held for its own claims said twice. The tray's walls were read along its
divider. The clevis's pin holes, one per ear, were re-aimed down the ears
by Forge three times, and its record read the ears' 25 mm as the part's
height. And the hydra's six rods, one pattern, were counted as one.

Tier A: five of eight, and of the three, two were Forge's and one the
suite's. The dented cube was held for a question the brief answers -- where
the sphere's centre is, "centred on the middle of the top face". Three
balls in a row were held to be one ball. The bead was right: a hole through
a ball takes its poles off, and the suite expected 40 mm along the hole.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from test_real_answers import _load  # noqa: E402


def _record(case: dict, assumptions=None):
    from forge_roles import RequirementsEngineer

    raw = json.loads(json.dumps(case["requirements"]))
    if assumptions is not None:
        raw["assumptions"] = assumptions(raw["assumptions"])
    return RequirementsEngineer().parse(raw, brief=case["brief"])


class TheCantileverIsHeldForItsGradeOnce(unittest.TestCase):

    def setUp(self) -> None:
        self.case = _load("validation_r10_cantilever_grade_twice")

    def test_the_record_s_own_grade_is_the_one_held(self) -> None:
        record = _record(self.case, lambda found: [
            a for a in found if "only grade of it Forge" not in a["statement"]])
        ids = [a["id"] for a in record.assumptions]
        self.assertEqual(len(ids), len(set(ids)), ids)
        grade = [a for a in record.assumptions
                 if a["id"] == "ASM_MATERIAL_GRADE"]
        self.assertEqual(len(grade), 1)
        self.assertIn("6061", grade[0]["statement"])
        self.assertEqual(grade[0]["risk"], "high")
        self.assertFalse(grade[0]["approved"])

    def test_two_of_one_id_are_two_ids(self) -> None:
        record = _record(self.case)
        ids = [a["id"] for a in record.assumptions]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertIn("ASM_MATERIAL_GRADE_2", ids)

    def test_a_grade_said_another_way_is_recognised(self) -> None:
        from forge_roles.library import _the_grade_a_margin_rests_on

        answer = {"requirements": [{"id": "SF",
                                    "measurement": "safety_factor:bending"}],
                  "assumptions": [{"id": "ASM_MATERIAL_GRADE",
                                   "statement": "The bracket is 6061 T6 "
                                                "aluminium alloy.",
                                   "risk": "moderate", "reversible": True,
                                   "approved": False}]}
        notes = _the_grade_a_margin_rests_on(
            "An aluminium cantilever, safety factor of at least 2.", answer)
        self.assertEqual(len(answer["assumptions"]), 1)
        self.assertEqual(answer["assumptions"][0]["risk"], "high")
        self.assertTrue(notes)

    def test_an_unknown_absorbed_under_a_taken_id_gets_its_own(self) -> None:
        from types import SimpleNamespace

        from forge_orchestrator.orchestrator import _absorb_unknowns
        from forge_roles.library import RequirementSet

        record = RequirementSet(
            requirements=(), assumptions=({"id": "ASM_UNRESOLVED_UNK_A",
                                           "statement": "s"},),
            unknowns=(), risk_class="low")
        unknown = SimpleNamespace(identifier="UNK_A", question="q?",
                                  why_it_matters="w", blocks=())
        absorbed = _absorb_unknowns(record, [unknown])
        ids = [a["id"] for a in absorbed.assumptions]
        self.assertEqual(len(ids), len(set(ids)), ids)


class TheCollarIsNotHeldForASplitNobodyAskedFor(unittest.TestCase):

    def setUp(self) -> None:
        self.case = _load("validation_r12_collar_held_for_no_split")

    def test_the_solid_collar_no_longer_holds_the_part(self) -> None:
        record = _record(self.case)
        solid = [a for a in record.assumptions if a["id"] == "ASM_SOLID_COLLAR"]
        self.assertEqual(len(solid), 1)
        self.assertTrue(solid[0]["reversible"])
        self.assertEqual(solid[0]["risk"], "moderate")
        holding = [a["id"] for a in record.assumptions
                   if not a.get("approved") and (
                       a["risk"] in ("high", "critical")
                       or a.get("reversible") is False)]
        self.assertEqual(holding, [])

    def _eased(self, brief: str, statement: str, risk: str = "moderate"):
        from forge_roles.library import _an_absence_the_brief_never_asks_about

        answer = {"assumptions": [{"id": "A", "statement": statement,
                                   "risk": risk, "reversible": False,
                                   "approved": False}]}
        _an_absence_the_brief_never_asks_about(brief, answer)
        return answer["assumptions"][0]["reversible"]

    def test_only_an_absence_the_brief_never_mentions(self) -> None:
        brief = "A shaft collar, 25 mm across, with a 12 mm bore."
        self.assertTrue(self._eased(brief, "The collar has no keyway."))
        # The brief mentions it: what it says about it is the brief's call.
        self.assertFalse(self._eased(
            "A split shaft collar, 25 mm across.",
            "The collar is non-split, with no slit."))
        # Not an absence at all.
        self.assertFalse(self._eased(brief, "The collar is anodised black."))
        # High risk is a person's to decide whatever it says.
        self.assertFalse(self._eased(brief, "The collar has no keyway.",
                                     risk="high"))
        # The body, the surroundings, a material: a person decides.
        self.assertFalse(self._eased(
            brief, "The brace has no padding where it touches the skin."))
        self.assertFalse(self._eased(
            brief, "The part has no coating against outdoor UV exposure."))

    def test_a_choice_is_not_an_absence(self) -> None:
        # Real assumptions from earlier runs, each a choice that only has a
        # "no" or a "not" in it somewhere.
        cube = "A 50 mm cube, hollow, with one open face."
        self.assertFalse(self._eased(
            cube, "The stated 50 mm cube dimension refers to the outer "
                  "envelope of the part, not the internal cavity."))
        self.assertFalse(self._eased(
            "A PLA dome, hollow, 60 mm across.",
            "The walls are 2 mm thick: the brief says the part is hollow "
            "and does not say how thick its walls are."))
        self.assertFalse(self._eased(
            "A rigid side rail with a pivot hole.",
            "Edges of the rail are rounded with a nominal 2 mm fillet "
            "radius, without being a stated requirement."))
        self.assertFalse(self._eased(
            "A hollow shell lofted through five sections.",
            "The loft is smooth and continuous, not a sequence of abrupt "
            "steps."))
        # "None is specified" is about the brief, not the part.
        self.assertFalse(self._eased(
            cube, "A standard surface finish is assumed, as none is "
                  "specified."))

    def test_a_feature_the_brief_names_is_the_brief_s_call(self) -> None:
        brief = ("A plate with four 5.5 mm corner holes counterbored 10 mm "
                 "across.")
        self.assertFalse(self._eased(
            brief, "All holes are plain through-holes, not counterbored."))
        self.assertTrue(self._eased(
            brief, "All holes are plain through-holes, not threaded."))
        self.assertTrue(self._eased(
            "A PLA dome, hollow, 60 mm across.",
            "The rim is left as a plain edge -- no chamfer or fillet."))


class TheRingIsMeasuredToTheMiddleOfItsSection(unittest.TestCase):

    def setUp(self) -> None:
        self.case = _load("validation_p11_ring_given_at_its_centre_line")

    def test_the_first_design_was_right_and_now_passes(self) -> None:
        from test_real_answers import _design, _not_passing, _verify

        report = _verify(_design(self.case))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")

    def test_the_released_ring_fails_its_width(self) -> None:
        from test_real_answers import _design, _not_passing, _verify

        case = dict(self.case, answer=self.case["answer_redesigned"])
        failing = _not_passing(_verify(_design(case)))
        self.assertEqual(failing, {"REQ_RING_ACROSS_X": "FAIL",
                                   "REQ_RING_ACROSS_Y": "FAIL"})

    def test_the_record_claims_the_outside(self) -> None:
        record = _record(self.case)
        across = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in record.requirements
                  if r["measurement"].startswith("bounding_box_")}
        self.assertEqual(across, {"bounding_box_x": 48.0,
                                  "bounding_box_y": 48.0})
        self.assertIn("roundness", {r["measurement"]
                                    for r in record.requirements})

    def test_a_misread_extent_is_corrected(self) -> None:
        case = json.loads(json.dumps(self.case))
        case["requirements"]["requirements"].append({
            "id": "REQ_OD_X", "statement": "The ring is 40 mm across X.",
            "measurement": "bounding_box_x", "comparison": "equals",
            "threshold": {"magnitude": 40, "unit": "mm"}, "rationale": "r",
            "type": "geometric", "verification": "exact_geometry",
            "strength": "hard", "source": "user"})
        record = _record(case)
        across = {r["id"]: r["threshold"]["magnitude"]
                  for r in record.requirements
                  if r["measurement"].startswith("bounding_box_")}
        self.assertEqual(across, {"REQ_OD_X": 48.0,
                                  "REQ_RING_ACROSS_Y": 48.0})

    def test_every_way_of_saying_the_middle(self) -> None:
        from forge_roles.library import (
            _a_number_that_is_two_extents, _the_ring_the_brief_describes)

        for brief, ring, said in (
            (self.case["brief"], (40.0, 8.0), 40.0),
            ("A torus with a centreline diameter of 40 mm and an 8 mm tube.",
             (40.0, 8.0), 40.0),
            ("A torus, 40 mm centreline diameter, 8 mm section.", (40.0, 8.0),
             40.0),
            ("An O-ring with a 20 mm inner diameter and a 3 mm section.",
             (23.0, 3.0), 20.0),
        ):
            self.assertEqual(_the_ring_the_brief_describes(brief), ring, brief)
            # Not the part's outside, so not two of its extents.
            self.assertNotIn((said, "mm"), _a_number_that_is_two_extents(brief),
                             brief)
        # A bare "across" is the outside, as before.
        brief = "A PLA torus 50 mm across with a 6 mm round section."
        self.assertEqual(_the_ring_the_brief_describes(brief), (44.0, 6.0))
        self.assertIn((50.0, "mm"), _a_number_that_is_two_extents(brief))

    def test_a_circle_of_holes_or_an_inside_is_not_the_part(self) -> None:
        from forge_roles.library import _a_number_that_is_two_extents

        for brief, extents in (
            ("A flange 80 mm in diameter with six holes on a 60 mm diameter "
             "bolt circle.", [(80.0, "mm")]),
            ("A disc 60 mm across with four holes on a 40 mm pitch circle "
             "diameter.", [(60.0, "mm")]),
            ("A tube whose inner diameter is 24 mm and outer diameter is 30 "
             "mm.", [(30.0, "mm")]),
            # A comma ends the phrase: the disc is still 50 across.
            ("A disc 50 mm across, at the centre a 10 mm hole.",
             [(50.0, "mm")]),
        ):
            self.assertEqual(_a_number_that_is_two_extents(brief), extents,
                             brief)

    def test_a_ring_given_only_across_is_left_to_the_size_reading(
        self,
    ) -> None:
        from forge_roles.library import (
            _a_ring_is_as_wide_as_its_middle_and_section)

        requirements: list = []
        self.assertEqual(_a_ring_is_as_wide_as_its_middle_and_section(
            "A PLA torus 50 mm across with a 6 mm round section.",
            requirements), [])
        self.assertEqual(requirements, [])


class ThePlateHasBothItsCounterbores(unittest.TestCase):

    def setUp(self) -> None:
        self.case = _load("validation_h03_each_of_two_counterbored_holes")

    def test_each_is_counted_back_to_the_two(self) -> None:
        record = _record(self.case)
        claimed = {r["measurement"]: r["threshold"]["magnitude"]
                   for r in record.requirements}
        self.assertEqual(claimed["counterbores:5.5:10x5,top"], 2)
        self.assertEqual(claimed["holes_of_diameter:5.5"], 2)

    def test_the_first_design_passes_and_the_released_one_fails(
        self,
    ) -> None:
        from test_real_answers import _design, _not_passing, _verify

        self.assertEqual(_not_passing(_verify(_design(self.case))), {})
        released = dict(self.case, answer=self.case["answer_released"])
        self.assertEqual(_not_passing(_verify(_design(released))),
                         {"REQ_COUNTERBORED_5_5MM": "FAIL"})

    def test_what_each_refers_back_to(self) -> None:
        from forge_roles.library import _the_count_each_refers_back_to

        for said, count in (
            ("two counterbored holes, 40 mm apart: each ", 2),
            ("four 5 mm holes, each ", 4),
            ("the two holes, each being ", 2),
            ("12 holes: each ", 12),
            # A figure with a unit is a size, not a count.
            ("a plate 40 mm wide, each ", None),
            # Not said for each of them.
            ("two holes and a ", None),
            ("each ", None),
        ):
            self.assertEqual(_the_count_each_refers_back_to(said), count,
                             said)


class TheCrossingHolesAreNotHeldForTheBriefsOwnWords(unittest.TestCase):

    def test_the_alignment_is_the_brief_s(self) -> None:
        case = _load("validation_h07_holes_held_for_the_brief_s_words")
        record = _record(case)
        ids = {a["id"] for a in record.assumptions}
        self.assertNotIn("ASM_HOLE_ALIGNMENT", ids)
        holding = [a["id"] for a in record.assumptions
                   if not a.get("approved") and (
                       a["risk"] in ("high", "critical")
                       or a.get("reversible") is False)]
        self.assertEqual(holding, [])

    def test_x_y_and_z_only_where_the_brief_says_each_axis(self) -> None:
        from forge_roles.library import _an_assumption_the_brief_states

        said = ("The three 10 mm holes are mutually orthogonal, through "
                "the cube's centre along the X, Y and Z axes.")
        for brief, kept in (
            ("A 30 mm cube with three 10 mm holes through its centre, one "
             "along each axis.", False),
            # Which way they run is the record's reading, not the brief's.
            ("A 30 mm cube with three 10 mm holes through its centre.",
             True),
        ):
            answer = {"assumptions": [{"id": "A", "statement": said,
                                       "risk": "moderate",
                                       "reversible": False,
                                       "approved": False}]}
            _an_assumption_the_brief_states(brief, answer)
            self.assertEqual(bool(answer["assumptions"]), kept, brief)


def _passes_unheld(test: unittest.TestCase, name: str, answer: str = "answer"):
    from test_real_answers import _design, _not_passing, _verify

    case = _load(name)
    record = _record(case)
    holding = [a["id"] for a in record.assumptions
               if not a.get("approved") and (
                   a["risk"] in ("high", "critical")
                   or a.get("reversible") is False)]
    test.assertEqual(holding, [], name)
    draft = _design(dict(case, answer=case[answer]))
    report = _verify(draft)
    test.assertEqual(_not_passing(report), {}, name)
    return case, record, draft, report


def _mesh_volume(report) -> float:
    return float(str(report.measurements["mesh_volume"]).split()[0])


class NoRoundingTheBriefDoesNotAskFor(unittest.TestCase):

    def test_the_stepped_shaft(self) -> None:
        import math

        case, record, draft, report = _passes_unheld(
            self, "validation_c04_shaft_blended_and_held")
        self.assertNotIn("ASM_FILLET", {a["id"] for a in record.assumptions})
        body = next(f for f in draft.document.components[0].features
                    if f.identifier == "body")
        self.assertIsNone(body.parameters.get("blend_radius"))
        exact = math.pi * (100 * 30 + 36 * 40)
        self.assertLess(abs(_mesh_volume(report) - exact) / exact, 0.005)

    def test_the_dumbbell(self) -> None:
        case, record, draft, report = _passes_unheld(
            self, "validation_c15_dumbbell_blended_and_turned")
        # The bar is left lying along X, where its balls are.
        envelope = report.measurements["part"]["envelope_mm"]
        self.assertGreater(envelope[0], 60)
        self.assertLess(abs(_mesh_volume(report) - 7922.0) / 7922.0, 0.01)

    def test_a_brief_that_asks_for_one_keeps_it(self) -> None:
        from forge_roles.library import _rounding_nobody_asked_for

        def blended():
            return {"features": [{"id": "u", "kind": "union",
                                  "inputs": ["a", "b"], "parameters": {
                                      "blend_radius": {"magnitude": 3,
                                                       "unit": "mm"}}}]}
        for brief, kept in (
            ("A boss with a 3 mm fillet at its root.", True),
            ("A plate with rounded corners.", True),
            ("A plate with a chamfer on its top edge.", True),
            ("A round post 20 mm across on a plate.", False),
            ("A bar with a ball on each end.", False),
        ):
            component = blended()
            _rounding_nobody_asked_for(component, None, brief)
            self.assertEqual(
                "blend_radius" in component["features"][0]["parameters"],
                kept, brief)


class AnAssumptionTheBriefOrForgeAlreadySettles(unittest.TestCase):

    def _eased(self, brief, statement, risk="low"):
        from forge_roles.library import (
            _an_assumption_forge_checks_or_the_brief_states)

        answer = {"assumptions": [{"id": "A", "statement": statement,
                                   "risk": risk, "reversible": False,
                                   "approved": False}]}
        _an_assumption_forge_checks_or_the_brief_states(brief, answer)
        return answer["assumptions"][0]["reversible"]

    def test_which(self) -> None:
        shaft = "A stepped shaft on one axis: 20 mm and 12 mm sections."
        self.assertTrue(self._eased(
            shaft, "The two sections are coaxial on a single shared axis, as "
                   "described by the brief's single-axis stepped shaft "
                   "language."))
        self.assertTrue(self._eased(
            "A PLA dumbbell.", "The dumbbell is produced as a single, "
            "continuous printed part, not an assembly of separate "
            "components.", risk="moderate"))
        # A figure of its own, a load, a person: still a person's call.
        self.assertFalse(self._eased(
            shaft, "The shaft is ground to 0.4 micrometres, as described by "
                   "the brief."))
        self.assertFalse(self._eased(
            shaft, "The part is one piece and carries the motor's load."))
        self.assertFalse(self._eased(
            shaft, "The sections are coaxial, as the brief says.",
            risk="high"))


class TheHydraCountsItsSixRods(unittest.TestCase):

    def test_a_pattern_counts_as_many_as_its_count_says(self) -> None:
        _passes_unheld(self, "validation_c06_hydra_pattern_counted_once")


class TheCupIsClaimedOnce(unittest.TestCase):

    def test_the_same_claim_twice_is_one_claim(self) -> None:
        case, record, _, _ = _passes_unheld(
            self, "validation_c09_cup_claims_said_twice")
        ids = [r["id"] for r in record.requirements]
        self.assertNotIn("REQ_WALL_THICKNESS_2", ids)
        self.assertNotIn("REQ_FLOOR_THICKNESS_2", ids)

    def test_a_load_case_is_not_a_case(self) -> None:
        from forge_roles.library import _BOX_LIKE

        self.assertFalse(_BOX_LIKE.search(
            "a cup. it carries no load, so there is no load case."))
        self.assertTrue(_BOX_LIKE.search("a phone case 70 mm long"))


class TheTrayWallsAreReadBesideItsDivider(unittest.TestCase):

    def test_the_released_tray_measures_its_walls(self) -> None:
        from forge_ir import Document
        from test_real_answers import _not_passing
        from forge_pipeline import verify_component

        case = _load("validation_c10_tray_divider_on_the_wall_line")
        document = Document.from_json(json.dumps(case["document_released"]))
        report = verify_component(document, document.components[0],
                                  measurement_depth=6)
        self.assertEqual(_not_passing(report), {})


class TheClevis(unittest.TestCase):

    def setUp(self) -> None:
        self.case = _load("validation_c13_clevis_pin_holes_re_aimed")

    def test_the_ears_stand_on_the_block(self) -> None:
        record = _record(self.case)
        height = [r for r in record.requirements
                  if r["measurement"] == "bounding_box_z"]
        self.assertEqual([h["threshold"]["magnitude"] for h in height],
                         [35.0])

    def test_each_pin_hole_goes_through_its_own_ear(self) -> None:
        from test_real_answers import _design, _not_passing, _verify

        draft = _design(dict(self.case, answer=self.case["answer_right"]))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        holes = report.measurements["part"]["holes"]
        self.assertEqual(sorted(h["centre_mm"][0] for h in holes),
                         [-17.0, 17.0])
        self.assertTrue(all(h["centre_mm"][2] == 27.0 for h in holes))
        self.assertLess(abs(_mesh_volume(report) - 13396.8) / 13396.8, 0.01)

    def test_holes_down_one_line_through_one_solid_are_still_re_aimed(
        self,
    ) -> None:
        from forge_roles.library import _re_aim_holes_that_became_one_line

        component = {
            "parameters": [{"id": "s", "value": {"magnitude": 20,
                                                 "unit": "mm"}}],
            "features": [
                {"id": "plate", "kind": "box", "parameters": {
                    "size": {"vector": [60, 40, 5], "unit": "mm"},
                    "centered": True}},
                {"id": "h1", "kind": "hole", "inputs": ["plate"],
                 "parameters": {"diameter": {"magnitude": 4, "unit": "mm"},
                                "position": {"vector": ["s", 0, 0],
                                             "unit": "mm"},
                                "axis": [1, 0, 0]}},
                {"id": "h2", "kind": "hole", "inputs": ["h1"],
                 "parameters": {"diameter": {"magnitude": 4, "unit": "mm"},
                                "position": {"vector": ["-s", 0, 0],
                                             "unit": "mm"},
                                "axis": [1, 0, 0]}}]}
        notes = _re_aim_holes_that_became_one_line(
            component["features"], component)
        self.assertTrue(notes)
        for hole in component["features"][1:]:
            self.assertEqual(hole["parameters"]["axis"], [0.0, 0.0, 1.0])
            self.assertNotIn("through", hole["parameters"])

    def test_first_wall_from_inside_a_wall_goes_through_all_of_it(
        self,
    ) -> None:
        from forge_ir import Document
        from forge_pipeline import verify_component
        from test_the_thinking_runs import _document

        document = Document.from_json(json.dumps(_document([], [
            {"id": "slab", "kind": "box", "parameters": {
                "size": {"vector": [6, 20, 20], "unit": "mm"},
                "centered": True}},
            {"id": "h", "kind": "hole", "inputs": ["slab"], "parameters": {
                "diameter": {"magnitude": 8, "unit": "mm"},
                "position": {"vector": [0, 0, 0], "unit": "mm"},
                "axis": [1, 0, 0], "through": "first_wall"}}])))
        report = verify_component(document, document.components[0],
                                  measurement_depth=6)
        self.assertEqual(report.measurements["part"]["open_holes"], 1)
        import math
        exact = 6 * 20 * 20 - math.pi * 16 * 6
        self.assertLess(abs(_mesh_volume(report) - exact) / exact, 0.01)


class WhereTheBriefPutsABall(unittest.TestCase):

    def test_a_centre_on_a_face_is_not_a_question(self) -> None:
        case, record, _, report = _passes_unheld(
            self, "validation_a02_dent_centred_on_the_top_face")
        self.assertEqual(record.unknowns, ())
        dent = [r for r in record.requirements
                if r["measurement"] == "opening_depth"]
        self.assertEqual([d["threshold"]["magnitude"] for d in dent], [15.0])
        self.assertLess(abs(_mesh_volume(report) - 56931.4) / 56931.4, 0.005)

    def test_a_void_inside_the_cube_fails_the_dent(self) -> None:
        from test_real_answers import _design, _not_passing, _verify

        case = json.loads(json.dumps(_load(
            "validation_a02_dent_centred_on_the_top_face")))
        sphere = next(f for f in case["answer"]["document"]["components"][0]
                      ["features"] if f["kind"] == "sphere")
        sphere["parameters"]["origin"]["vector"] = [0, 0, 0]
        failing = _not_passing(_verify(_design(case)))
        self.assertIn("REQ_DENT_DEPTH", failing)

    def test_three_balls_are_not_a_ball(self) -> None:
        from forge_roles.library import _the_part_is_a_ball

        _passes_unheld(self, "validation_a03_three_balls_held_to_be_one")
        record = _record(_load("validation_a03_three_balls_held_to_be_one"))
        self.assertNotIn("roundness_every_way",
                         {r["measurement"] for r in record.requirements})
        for brief, one in (
            ("A PLA sphere 40 mm in diameter.", True),
            ("A 40 mm PLA ball with a 10 mm hole through its centre.", True),
            ("Three 20 mm PLA balls in a row, fused into one piece.", False),
            ("Two 10 mm spheres joined side by side.", False),
        ):
            self.assertEqual(_the_part_is_a_ball(brief), one, brief)


class TheSpecSheetPlateIsNotRound(unittest.TestCase):

    def test_the_released_plate_passes_unheld(self) -> None:
        _, record, _, _ = _passes_unheld(
            self, "validation_v03_spec_sheet_plate_held_round")
        self.assertNotIn("roundness",
                         {r["measurement"] for r in record.requirements})

    def test_a_count_and_a_word_before_the_hole_is_still_a_hole(self) -> None:
        from forge_roles.library import _a_number_that_is_two_extents

        self.assertEqual(_a_number_that_is_two_extents(
            "Features: 4x diameter 4 mm through holes on a 56 x 36 mm "
            "pattern, centred."), [])

    def test_a_round_size_only_up_z_is_not_the_part(self) -> None:
        from forge_roles.library import _a_round_part_has_to_be_round

        def box(x, y, z):
            return [{"id": "REQ_" + a.upper(),
                     "measurement": "bounding_box_" + a,
                     "threshold": {"magnitude": v, "unit": "mm"}}
                    for a, v in (("x", x), ("y", y), ("z", z))]

        for brief, size, round_ in (
            ("A 70 by 50 mm plate, thickness 4 mm, with four holes of "
             "diameter 4 mm.", (70, 50, 4), False),
            ("A PLA shaft collar, 25 mm outside diameter, 10 mm bore, "
             "12 mm long.", (25, 25, 12), True),
            ("A 30 mm diameter roller, 40 mm long, lying along X.",
             (40, 30, 30), True),
        ):
            self.assertEqual(
                bool(_a_round_part_has_to_be_round(brief, box(*size))),
                round_, brief)


class AHeightLimitIsALimit(unittest.TestCase):

    def test_the_post_on_its_base_passes_at_45(self) -> None:
        _, record, _, report = _passes_unheld(
            self, "validation_l07_height_limit_read_as_the_height")
        height = next(r for r in record.requirements
                      if r["measurement"] == "bounding_box_z")
        self.assertEqual(height["comparison"], "at_most")
        self.assertEqual(height["threshold"]["magnitude"], 50.0)

    def test_a_comparison_is_a_bound_however_it_is_worded(self) -> None:
        from forge_roles.library import _A_COUNT_BOUND, _A_SIZE_BOUND

        for sentence, bound in (
            ("the whole part must be no taller than 50 mm", True),
            ("it must not be wider than 40 mm", True),
            ("keep it shorter than 120 mm", True),
            ("its height must not exceed 50 mm", True),
            ("a 50 mm height limit", True),
            ("height \u2264 50 mm", True),
            ("height <= 50 mm", True),
            ("no more than three holes", True),
            ("fewer than five slots", True),
            ("a cube 30 mm on each side", False),
            ("other than the bore it is solid, 40 mm long", False),
            ("a plate 70 mm long rather than 60 mm", False),
            ("a limit switch bracket 40 mm long", False),
            ("an end cap 30 mm across", False),
            ("from 60 mm -> 70 mm", False),
        ):
            self.assertEqual(bool(_A_SIZE_BOUND.search(sentence)), bound,
                             sentence)
            self.assertEqual(bool(_A_COUNT_BOUND.search(sentence)), bound,
                             sentence)


class NothingSealedInsideAPartTheBriefDoesNotHollow(unittest.TestCase):

    def setUp(self) -> None:
        self.case = _load("validation_l05_steel_cube_shelled_to_its_weight")

    def test_the_record_claims_nothing_sealed_inside(self) -> None:
        record = _record(self.case)
        sealed = [r for r in record.requirements
                  if r["measurement"] == "sealed_voids"]
        self.assertEqual(len(sealed), 1)
        self.assertEqual(sealed[0]["comparison"], "at_most")
        self.assertEqual(sealed[0]["threshold"]["magnitude"], 0)

    def test_the_solid_cube_fails_only_its_weight(self) -> None:
        from test_real_answers import _design, _not_passing, _verify

        report = _verify(_design(self.case))
        self.assertEqual(_not_passing(report), {"REQ_MASS": "FAIL"})
        self.assertEqual(report.measurements["sealed_voids_mm3"], [])

    def test_the_shelled_cube_fails_for_what_it_hides(self) -> None:
        from test_real_answers import _design, _not_passing, _verify

        report = _verify(_design(dict(self.case,
                                      answer=self.case["shelled"])))
        self.assertEqual(_not_passing(report).get(
            "REQ_NOTHING_SEALED_INSIDE"), "FAIL")
        [void] = report.measurements["sealed_voids_mm3"]
        self.assertLess(abs(void - 14 ** 3) / 14 ** 3, 0.03)

    def test_a_brief_that_makes_the_part_hollow_is_not_claimed(self) -> None:
        from forge_roles.library import _nothing_sealed_inside_unless_asked

        limit = " It must weigh no more than 50 g."
        for brief, claimed in (
            ("A 20 mm cube of 1018 steel." + limit, True),
            ("A PLA cube 20 mm on each side." + limit, True),
            ("A sealed hollow PLA cube 40 mm on the outside with 2 mm walls "
             "on every side, completely closed." + limit, False),
            ("A PLA ball 40 mm across with a 3 mm shell." + limit, False),
            ("A closed PLA box 40 mm on each side with 2 mm walls." + limit,
             False),
            ("A PLA float 30 mm across." + limit, False),
        ):
            requirements: list = [{
                "id": "REQ_MASS", "measurement": "mass",
                "comparison": "at_most",
                "threshold": {"magnitude": 50, "unit": "g"}}]
            _nothing_sealed_inside_unless_asked(brief, requirements)
            self.assertEqual(len(requirements) == 2, claimed, brief)

    def test_without_a_weight_limit_nothing_is_added(self) -> None:
        from forge_roles.library import _nothing_sealed_inside_unless_asked

        requirements: list = [{
            "id": "REQ_X", "measurement": "bounding_box_x",
            "comparison": "equals",
            "threshold": {"magnitude": 20, "unit": "mm"}}]
        self.assertEqual(_nothing_sealed_inside_unless_asked(
            "A PLA cube 20 mm on each side.", requirements), [])
        self.assertEqual(len(requirements), 1)

    def test_a_void_closed_in_by_a_cut_is_counted(self) -> None:
        from forge_ir import Document
        from forge_pipeline import verify_component
        from test_the_thinking_runs import _document

        def report(inner_z: float):
            document = Document.from_json(json.dumps(_document([], [
                {"id": "outer", "kind": "box", "parameters": {
                    "size": {"vector": [30, 30, 30], "unit": "mm"},
                    "centered": True}},
                {"id": "inner", "kind": "box", "parameters": {
                    "size": {"vector": [20, 20, inner_z], "unit": "mm"},
                    "centered": True}},
                {"id": "body", "kind": "subtract",
                 "inputs": ["outer", "inner"]}])))
            return verify_component(document, document.components[0],
                                    measurement_depth=6)

        closed = report(20).measurements["sealed_voids_mm3"]
        self.assertEqual(len(closed), 1)
        self.assertLess(abs(closed[0] - 8000) / 8000, 0.03)
        # Cut right through, top to bottom: a tube, no air closed in.
        self.assertEqual(report(40).measurements["sealed_voids_mm3"], [])


class TheBoltsHeadIsDrawnInDegrees(unittest.TestCase):

    def test_cos_30_is_thirty_degrees(self) -> None:
        from test_real_answers import _design, _verify

        case = _load("validation_x03_bolt_head_drawn_with_cos_30")
        report = _verify(_design(case))
        envelope = sorted(report.measurements["part"]["envelope_mm"])
        # 13 across the flats, 15.01 across the corners, 5.5 + 40 long.
        self.assertLess(abs(envelope[0] - 13.0), 0.1)
        self.assertLess(abs(envelope[1] - 15.01), 0.1)
        self.assertLess(abs(envelope[2] - 45.5), 0.1)

    def test_a_bare_figure_is_degrees_only_where_it_cannot_be_radians(
        self,
    ) -> None:
        from forge_expr import evaluate
        from forge_expr.errors import EvaluationError
        from forge_units import Q

        def value(text, **context):
            return float(evaluate(text, context).magnitude.midpoint)

        self.assertAlmostEqual(value("cos(30)"), 0.8660254, places=6)
        self.assertAlmostEqual(value("sin(90)"), 1.0, places=9)
        self.assertAlmostEqual(value("tan(45)"), 1.0, places=9)
        self.assertAlmostEqual(value("cos(360 / 6)"), 0.5, places=9)
        self.assertAlmostEqual(value("cos(30 deg)"), 0.8660254, places=6)
        self.assertAlmostEqual(value("cos(pi / 6)"), 0.8660254, places=6)
        self.assertAlmostEqual(value("cos(0)"), 1.0, places=9)
        # A name says nothing about which: `step = 2 * pi / n` is radians.
        self.assertAlmostEqual(
            value("cos(step)", step=Q(1.0471975512, "")), 0.5, places=6)
        for ambiguous in ("cos(0.5236)", "sin(1)"):
            with self.assertRaises(EvaluationError, msg=ambiguous):
                evaluate(ambiguous, {})


class APartTheBriefGivesNoSizeIsAskedFor(unittest.TestCase):

    def test_which_briefs(self) -> None:
        from forge_roles.library import _a_part_the_brief_gives_no_size

        for brief, asked in (
            ("Make a washer.", True),
            ("A PLA hook strong enough to hang a coat on.", True),
            ("Make me something cool.", True),
            ("An M10 washer.", False),
            ("A two inch PLA cube.", False),
            ("A PLA washer 30 mm across.", False),
            ("", False),
        ):
            answer: dict = {"unknowns": []}
            _a_part_the_brief_gives_no_size(brief, answer)
            self.assertEqual(bool(answer["unknowns"]), asked, brief)
            if asked:
                [unknown] = answer["unknowns"]
                self.assertTrue(unknown["critical"])

    def test_a_size_already_asked_is_not_asked_twice(self) -> None:
        from forge_roles.library import _a_part_the_brief_gives_no_size

        answer = {"unknowns": [{"id": "UNK_OD", "critical": True,
                                "question": "What outer diameter?"}]}
        _a_part_the_brief_gives_no_size("Make a washer.", answer)
        self.assertEqual([u["id"] for u in answer["unknowns"]], ["UNK_OD"])

    def test_the_washer_is_held_for_its_size(self) -> None:
        record = _record(_load("validation_x01_washer_nobody_sized"))
        self.assertIn("UNK_PART_SIZE",
                      [u.identifier for u in record.critical_unknowns])


class NothingIsDesignedForABriefThatAsksForNoPart(unittest.TestCase):

    def _run(self, is_a_part):
        from forge_models import ScriptedProvider
        from forge_orchestrator import Orchestrator, OrchestratorConfig

        provider = ScriptedProvider([{
            "summary": "A request for a poem about bridges; no part.",
            "part_kind": "none", "stated": ["Write me a poem about bridges."],
            "implied": [], "unstated": [], "is_a_part": is_a_part,
            "out_of_scope": ["A poem is not a part."]}])
        run = Orchestrator(provider, config=OrchestratorConfig()).design(
            "Write me a poem about bridges.")
        return run, provider

    def test_the_run_ends_at_the_reading(self) -> None:
        from forge_orchestrator import State

        run, provider = self._run(False)
        self.assertIs(run.state, State.FAILED)
        self.assertEqual(run.failure["code"], "OR1008_NOT_A_PART")
        self.assertEqual(len(provider.requests), 1)
        self.assertIsNone(run.report)

    def test_a_missing_answer_is_a_part(self) -> None:
        from forge_roles import BriefInterpreter

        intent = BriefInterpreter().parse({
            "summary": "A washer.", "part_kind": "washer", "stated": [],
            "implied": [], "unstated": ["size"]})
        self.assertTrue(intent.is_a_part)
        self.assertFalse(BriefInterpreter().parse({
            "summary": "A poem.", "part_kind": "none", "stated": [],
            "implied": [], "unstated": [], "is_a_part": "false"}).is_a_part)


class ACoilCountsItsTurns(unittest.TestCase):

    def test_a_spring_of_ten_turns_is_ten_coils(self) -> None:
        # Read off the design, as the count is: measuring the whole spring
        # takes minutes, and the count does not need it.
        from forge_pipeline.measure import resolve_measurement
        from test_real_answers import _design

        case = _load("validation_x05_spring_of_ten_coils_counted_as_one")
        document = _design(case).document
        count = resolve_measurement(
            "feature_count:coil:total", component=document.components[0],
            part=None, properties=None)
        self.assertEqual(float(count.value.magnitude.midpoint), 10.0)
        self.assertIn("turns", count.detail["note"])


class ASolidMetAtASlantIsToldFromOneMeetingItself(unittest.TestCase):

    @staticmethod
    def _shared_edges(solid, resolution=96):
        import numpy as np
        from forge_geom.mesh import _extracted

        mesh, _ = _extracted(solid, resolution, 0.02, 0.0)
        shared = mesh.non_manifold_edges()
        lengths = np.linalg.norm(mesh.vertices[mesh.faces[:, 1]]
                                 - mesh.vertices[mesh.faces[:, 0]], axis=1)
        return mesh.vertices[shared].mean(axis=1), float(np.median(lengths))

    @staticmethod
    def _solid(features):
        from forge_ir import Document
        from forge_kernel import Compiler
        from test_the_thinking_runs import _document

        document = Document.from_json(json.dumps(_document([], features)))
        return Compiler().compile_component(
            document.components[0], validate_geometry=False).solid

    def test_the_held_spring_meets_itself_nowhere(self) -> None:
        from forge_geom.mesh import meets_itself_at
        from forge_ir import Document
        from forge_kernel import Compiler

        case = _load("validation_x05_spring_of_ten_coils_counted_as_one")
        document = Document.from_json(json.dumps(case["held"]))
        solid = Compiler().compile_component(document.components[0]).solid
        where, cell = self._shared_edges(solid)
        self.assertGreater(len(where), 0)
        self.assertFalse(meets_itself_at(solid, where, cell).any())

    def test_two_blocks_touching_along_a_line_are_found(self) -> None:
        from forge_evidence import Status
        from forge_geom.mesh import meets_itself_at
        from forge_ir import Document
        from forge_pipeline import verify_component
        from test_the_thinking_runs import _document

        def box(name, lo):
            return {"id": name, "kind": "box", "parameters": {
                "size": {"vector": [10, 10, 10], "unit": "mm"},
                "centered": False, "origin": {"vector": lo, "unit": "mm"}}}

        features = [box("a", [0, 0, 0]), box("b", [10, 10, 0]),
                    {"id": "u", "kind": "union", "inputs": ["a", "b"]}]
        where, cell = self._shared_edges(self._solid(features))
        self.assertTrue(meets_itself_at(self._solid(features), where,
                                        cell).all())
        document = Document.from_json(json.dumps(_document([], features)))
        report = verify_component(document, document.components[0],
                                  measurement_depth=5, mesh_resolution=96)
        gate = {r.gate.identifier: r
                for r in report.gate_results}["GEOM_WATERTIGHT"]
        self.assertIs(gate.status, Status.FAIL)

    def test_a_rod_along_a_slant_is_one_sheet(self) -> None:
        from forge_geom.mesh import meets_itself_at

        solid = self._solid([{"id": "rod", "kind": "cylinder", "parameters": {
            "diameter": {"magnitude": 6, "unit": "mm"},
            "height": {"magnitude": 10, "unit": "mm"},
            "origin": {"vector": [0, 0, 0], "unit": "mm"},
            "axis": {"vector": [1, 2, 2], "unit": "mm"}}}])
        where, cell = self._shared_edges(solid, 110)
        self.assertGreater(len(where), 0)
        self.assertFalse(meets_itself_at(solid, where, cell).any())


class AnOpenSideIsNotDrawnShut(unittest.TestCase):
    """The hollow dome of 19 October: released with every check passing,
    and its STL closed across the open side by a skin of no thickness --
    a slicer showed a filled disc. The cavity was cut by the very plane
    that cuts the dome, the field touched nought across the opening, and
    the grid's samples lay on that plane."""

    @staticmethod
    def _box(name, lo, size):
        return {"id": name, "kind": "box", "parameters": {
            "size": {"vector": size, "unit": "mm"},
            "centered": False, "origin": {"vector": lo, "unit": "mm"}}}

    @staticmethod
    def _dome():
        from forge_ir import Document
        from forge_kernel import Compiler

        case = _load("validation_dome_open_side_drawn_shut")
        document = Document.from_json(json.dumps(case["document"]))
        return document, Compiler().compile_component(
            document.components[0]).solid

    def _open_and_whole(self, mesh, volume, tolerance=0.01):
        pieces, hollows = mesh.pieces_and_hollows()
        self.assertEqual(hollows, [])
        self.assertEqual(len(pieces), 1)
        self.assertAlmostEqual(pieces[0][0], volume, delta=tolerance * volume)
        self.assertEqual(mesh.surfaces_on_each_other(), 0)
        self.assertTrue(mesh.is_watertight()[0])

    def test_the_dome_is_open_in_the_mesh_it_ships(self) -> None:
        import math

        from forge_geom import extract_manifold_surface

        _, solid = self._dome()
        shell = 2.0 / 3.0 * math.pi * (35.0 ** 3 - 33.0 ** 3)
        # The artefact's grid, and verification's.
        for resolution in (96, 110):
            self._open_and_whole(
                extract_manifold_surface(solid, resolution=resolution), shell)

    def test_a_tray_cut_flush_with_its_top_is_open(self) -> None:
        from forge_geom import extract_manifold_surface

        # Half as tall as it is wide, its top on a plane of samples: drawn
        # as a closed box of 62,500 mm^3 round a sealed 42,577, before.
        solid = ASolidMetAtASlantIsToldFromOneMeetingItself._solid([
            self._box("body", [0, 0, 0], [50, 50, 25]),
            self._box("pocket", [3, 3, 3], [44, 44, 22]),
            {"id": "tray", "kind": "subtract", "inputs": ["body", "pocket"]}])
        self._open_and_whole(extract_manifold_surface(solid, resolution=96),
                             50 * 50 * 25 - 44 * 44 * 22)

    def test_blocks_touching_face_to_face_stay_one_solid(self) -> None:
        from forge_geom import extract_manifold_surface

        solid = ASolidMetAtASlantIsToldFromOneMeetingItself._solid([
            self._box("a", [0, 0, 0], [30, 60, 30]),
            self._box("b", [30, 0, 0], [30, 60, 30]),
            {"id": "u", "kind": "union", "inputs": ["a", "b"]}])
        mesh = extract_manifold_surface(solid, resolution=96)
        self._open_and_whole(mesh, 60 * 60 * 30)
        # No sheet left between them: the outside of one block, and no more.
        self.assertAlmostEqual(mesh.surface_area(), 2 * (3600 + 1800 + 1800),
                               delta=0.02 * 14400)

    def test_two_sheets_drawn_on_each_other_are_no_solid(self) -> None:
        import numpy as np

        from forge_geom.mesh import TriangleMesh

        corners = np.array([[x, y, z] for x in (0, 1) for y in (0, 1)
                            for z in (0, 1)], dtype=float)
        faces = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5],
                          [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                          [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
        cube = TriangleMesh(vertices=corners, faces=faces)
        self.assertEqual(cube.is_watertight(),
                         (True, {"boundary_edges": 0, "non_manifold_edges": 0,
                                 "total_edges": 18}))
        twice = TriangleMesh(vertices=np.vstack([corners, corners]),
                             faces=np.vstack([faces, faces[:, ::-1] + 8]))
        closed, stats = twice.is_watertight()
        self.assertFalse(closed)
        self.assertEqual(stats["edges_drawn_twice"], 18)

    def test_a_skin_drawn_anyway_is_found_and_another_grid_tried(self) -> None:
        import math
        from unittest import mock

        import numpy as np

        from forge_geom import extract_manifold_surface

        _, solid = self._dome()
        as_before = mock.patch(
            "forge_geom.mesh._material_only_where_material_is",
            lambda solid, points, values, step: np.array(values, dtype=float))
        with as_before:
            mesh = extract_manifold_surface(solid, resolution=96)
        self._open_and_whole(
            mesh, 2.0 / 3.0 * math.pi * (35.0 ** 3 - 33.0 ** 3))

    def test_the_gate_fails_a_surface_drawn_twice(self) -> None:
        from unittest import mock

        import numpy as np

        from forge_evidence import Status
        from forge_geom.mesh import _extracted
        from forge_pipeline import verify_component

        document, solid = self._dome()
        with mock.patch(
                "forge_geom.mesh._material_only_where_material_is",
                lambda solid, points, values, step: np.array(values,
                                                             dtype=float)):
            skinned, _ = _extracted(solid, 96, 0.02, 0.0)
        self.assertGreater(skinned.surfaces_on_each_other(), 0)
        with mock.patch("forge_pipeline.verify.extract_manifold_surface",
                        lambda *a, **k: skinned):
            report = verify_component(document, document.components[0],
                                      measurement_depth=5, mesh_resolution=96)
        gate = {r.gate.identifier: r
                for r in report.gate_results}["GEOM_WATERTIGHT"]
        self.assertIs(gate.status, Status.FAIL)
        self.assertIn("skin of no thickness",
                      " ".join(gate.evidence.limitations))


class TheSTLTakesItsOwnBolts(unittest.TestCase):
    """The exo arm's upper rail, 19 October: every claim passed on the
    design, and the STL beside the run had 8.2 mm holes 7.3 mm across --
    meshed in the 3 mm cells that find the surface of a 287 mm part."""

    @staticmethod
    def _rail():
        from forge_ir import Document
        from forge_kernel import Compiler

        case = _load("exo_upper_rail_holes_meshed_undersize")
        document = Document.from_json(json.dumps(case["document"]))
        return Compiler().compile_component(document.components[0]).solid

    @staticmethod
    def _clear_across(mesh, x, y, nominal, z0=4.0, z1=16.0):
        """The narrowest a hole at (x, y) is on the mesh: twice the nearest
        any of its wall's facet centres or edge middles comes to its axis."""
        import numpy as np

        tri = mesh.vertices[mesh.faces]
        points = np.concatenate([tri.mean(axis=1), (tri[:, 0] + tri[:, 1]) / 2,
                                 (tri[:, 1] + tri[:, 2]) / 2,
                                 (tri[:, 2] + tri[:, 0]) / 2])
        r = np.hypot(points[:, 0] - x, points[:, 1] - y)
        wall = (r < nominal * 0.75) & (points[:, 2] > z0) & (points[:, 2] < z1)
        return 2.0 * float(r[wall].min())

    def test_the_bolt_holes_print_their_size(self) -> None:
        from forge_geom import extract_print_surface, surface_deviation

        solid = self._rail()
        mesh = extract_print_surface(solid)
        self.assertIsNotNone(mesh)
        self.assertTrue(mesh.is_watertight()[0])
        for y in (85, 115, 225, 245):
            self.assertAlmostEqual(self._clear_across(mesh, 0, y, 8.2), 8.2,
                                   delta=0.1)
        # The bearing pockets, 22.1 mm for a 22 mm bearing, 7 mm deep from
        # each face; and the 15 mm counterbores, 5 mm deep from the bottom.
        self.assertAlmostEqual(
            self._clear_across(mesh, 0, 0, 22.1, z0=1.0, z1=6.0), 22.1,
            delta=0.1)
        self.assertAlmostEqual(
            self._clear_across(mesh, 0, 225, 15.0, z0=0.5, z1=4.5), 15.0,
            delta=0.1)
        self.assertLess(surface_deviation(solid, mesh, quantile=0.99), 0.05)

    def test_the_mesh_the_checks_read_was_not_fit_to_print(self) -> None:
        from forge_geom import extract_manifold_surface

        coarse = extract_manifold_surface(self._rail(), resolution=96)
        self.assertLess(self._clear_across(coarse, 0, 85, 8.2), 7.9)

    def test_the_run_writes_the_fine_one_and_says_so(self) -> None:
        import tempfile
        from types import SimpleNamespace

        from forge_cli import design
        from forge_geom.mesh import TriangleMesh
        import numpy as np
        import struct

        report = SimpleNamespace(part=SimpleNamespace(solid=self._rail()),
                                 component_id="upper_arm_link", mesh=None)
        with tempfile.TemporaryDirectory() as folder:
            path = design._write_mesh(report, pathlib.Path(folder))
            data = path.read_bytes()
        count = struct.unpack("<I", data[80:84])[0]
        tri = np.frombuffer(data[84:84 + 50 * count], dtype=np.dtype(
            [("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))["v"]
        vertices = tri.reshape(-1, 3).astype(float)
        mesh = TriangleMesh(vertices=vertices,
                            faces=np.arange(len(vertices)).reshape(-1, 3))
        self.assertAlmostEqual(self._clear_across(mesh, 0, 115, 8.2), 8.2,
                               delta=0.1)
        self.assertIn("mm facets for printing", design._MESH_NOTES[str(path)])

    def test_a_large_part_is_meshed_as_finely_as_the_budget_allows(self) -> None:
        from unittest import mock

        from forge_geom import extract_print_surface
        from forge_geom import mesh as meshing

        solid = ASolidMetAtASlantIsToldFromOneMeetingItself._solid([
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [300, 200, 10], "unit": "mm"}}}])
        with mock.patch.object(meshing, "_PRINT_FACES", 40_000):
            mesh = extract_print_surface(solid)
        self.assertIsNotNone(mesh)
        self.assertTrue(mesh.is_watertight()[0])
        self.assertLess(mesh.face_count, 60_000)


class ARoundEndIsAShapeNotAFillet(unittest.TestCase):
    """The exo arm's upper rail came back with an 8 mm blend where its round
    end meets the bar. Its brief has "round end", "fully rounded far end"
    and nothing that asks for a fillet."""

    def test_the_rail_s_blend_is_taken_off(self) -> None:
        from forge_roles.library import _rounding_nobody_asked_for

        case = _load("exo_upper_rail_holes_meshed_undersize")
        component = json.loads(json.dumps(case["document"]["components"][0]))
        said = _rounding_nobody_asked_for(component, None, case["brief"])
        union = next(f for f in component["features"]
                     if f["id"] == "hub_bar_union")
        self.assertNotIn("blend_radius", union.get("parameters", {}))
        self.assertTrue(said)

    def test_words_that_name_a_shape_ask_for_no_rounding(self) -> None:
        from forge_roles.library import _rounding_asked_for

        for brief, asked in (
            ("A strip with both ends fully rounded.", False),
            ("A PLA obround plate 20 mm wide with fully rounded ends.", False),
            ("A lug ending in a semicircle of radius 12 mm.", False),
            ("Curve the plate with an inside radius of 60 mm.", False),
            ("Curve the plate with an inside radius of 60 mm. Round the four "
             "corners with a 12 mm radius.", True),
            ("A bar with rounded ends and a 2 mm fillet where the post meets "
             "it.", True),
            ("A 40 mm cube with 3 mm rounded edges.", True),
            ("A plate with rounded corners.", True),
        ):
            self.assertEqual(_rounding_asked_for(brief), asked, brief)


class ASizeOfAPieceIsNotThePartsSize(unittest.TestCase):
    """The exo arm's upper rail, run again on 19 October, was held on
    roundness Forge claimed: "one end of the bar is a round end 48 mm in
    diameter" was read as the part being 48 mm round, and a correct 287 mm
    flat rail measured 0.385."""

    def test_the_rail_is_not_claimed_round(self) -> None:
        record = _record(_load("exo_upper_rail_held_round"))
        ids = {r["id"] for r in record.requirements}
        self.assertNotIn("REQ_ROUND", ids)
        self.assertNotIn("REQ_BOUNDING_BOX_X", ids)
        self.assertIn("REQ_BOUNDING_BOX_Y", ids)

    def test_sizes_said_of_pieces_and_of_parts(self) -> None:
        from forge_roles.library import _how_the_brief_describes_that_size

        for brief, sizes in (
            ("A PLA upper-arm rail: a flat bar 36 mm wide and 20 mm thick. One "
             "end of the bar is a round end 48 mm in diameter. At the pivot, "
             "cut a round pocket 22.1 mm in diameter.", set()),
            ("A PLA stand: a base plate 60 mm long, 40 mm wide and 6 mm thick, "
             "with a round post 20 mm across and 30 mm tall standing on top of "
             "it, centred.", set()),
            ("A PLA plate 80 mm long with four 3.2 mm holes on a 30.5 mm square "
             "of centres.", set()),
            ("A steel pipe flange. It is a disc 80 mm across and 10 mm thick, "
             "with a 30 mm bore through the centre.", {80.0}),
            ("An aluminium pulley hub. A flange disc 50 mm across and 6 mm "
             "thick, with a round hub 25 mm across and 15 mm tall standing on "
             "top of it, centred.", {50.0, 25.0}),
            ("A PLA spacer tube with an outside diameter of 11.5 mm and 6 mm "
             "long.", {11.5}),
            ("A 30 mm square PLA plate 4 mm thick.", {30.0}),
        ):
            found = {m for (m, _) in _how_the_brief_describes_that_size(brief)}
            self.assertEqual(found, sizes, brief)

    def test_an_assumption_about_a_round_end_is_kept(self) -> None:
        from forge_roles.library import _a_rounding_nobody_asked_for_assumed

        brief = ("A flat bar 36 mm wide with a fully rounded far end. Its "
                 "strength is checked outside Forge, so there is no load case.")
        for statement, dropped in (
            ("The fully rounded far end is a semicircle of radius 18 mm, half "
             "the bar's width.", False),
            ("The edges are not rounded.", False),
            ("A small transition fillet blends the end into the bar.", True),
            ("All edges are rounded off with a 1 mm radius.", True),
        ):
            answer = {"assumptions": [{"id": "ASM_X", "statement": statement}]}
            self.assertEqual(
                bool(_a_rounding_nobody_asked_for_assumed(brief, answer)),
                dropped, statement)


class ACountTheBriefStatesNeedsNoUnit(unittest.TestCase):

    def test_the_bracket_s_record_is_taken(self) -> None:
        from forge_roles import RequirementsEngineer

        case = _load("instrument_bracket_count_with_no_unit")
        for answer in (case["answers"][0], case["answers"][2]):
            record = RequirementsEngineer().parse(
                json.loads(json.dumps(answer)), brief=case["brief"])
            coils = next(r for r in record.requirements
                         if r["id"] == "REQ_SPRING_COIL_COUNT")
            self.assertEqual(coils["threshold"]["unit"], "")

    def test_a_length_with_no_unit_is_still_refused(self) -> None:
        from forge_roles import RequirementsEngineer
        from forge_roles.base import RoleOutputError

        answer = {"risk_class": "low", "assumptions": [], "unknowns": [],
                  "requirements": [
                      {"id": "REQ_T", "statement": "6 thick.",
                       "measurement": "parameter:thickness",
                       "comparison": "equals",
                       "threshold": {"magnitude": 6, "unit": ""}},
                      {"id": "REQ_X", "statement": "40 long.",
                       "measurement": "bounding_box_x",
                       "comparison": "equals",
                       "threshold": {"magnitude": 40, "unit": "mm"}}]}
        with self.assertRaises(RoleOutputError) as refused:
            RequirementsEngineer().parse(
                answer, brief="A PLA plate 40 mm long and 6 mm thick.")
        self.assertTrue(any("REQ_T" in p for p in refused.exception.problems))

    def test_which_figures_are_counts(self) -> None:
        from forge_roles.library import _a_count_the_brief_states

        brief = ("A spring of 1.5 mm wire, 12 mm outside diameter, 6 coils "
                 "and 24 mm long, on a plate with four holes.")
        self.assertTrue(_a_count_the_brief_states(brief, 6))
        self.assertTrue(_a_count_the_brief_states(brief, 4))
        self.assertFalse(_a_count_the_brief_states(brief, 12))
        self.assertFalse(_a_count_the_brief_states(brief, 24))
        self.assertFalse(_a_count_the_brief_states(brief, 1.5))
        self.assertFalse(_a_count_the_brief_states("x = 17, y = 0", 17))


class APieceOnThePartIsNotThePart(unittest.TestCase):

    def test_the_bracket_is_not_a_container(self) -> None:
        record = _record(_load("instrument_bracket_read_as_a_container"))
        bindings = {r["measurement"] for r in record.requirements}
        self.assertFalse(bindings & {"wall_thickness", "floor_thickness",
                                     "opening_depth"}, bindings)
        self.assertFalse(any(b.startswith(("windows_of_size",
                                           "walls_crossed", "standing_at"))
                             for b in bindings), bindings)
        self.assertIn("openings_of_size:20x8", bindings)
        self.assertIn("openings_of_size:12x4", bindings)

    def test_whose_wall_it_is(self) -> None:
        from forge_roles.library import _the_container_the_brief_describes

        for brief, wall in (
            ("A sealed hollow PLA cube 40 mm on the outside with 2 mm walls "
             "on every side, completely closed.", 2.0),
            ("A 60 mm cube box, open at the top, with 2 mm walls and a 2 mm "
             "floor.", 2.0),
            ("A sealed hollow PLA ball 40 mm across with a 3 mm wall.", 3.0),
            ("A PLA plate 60 by 40 by 5 mm with a hollow boss 20 mm across "
             "and 15 mm tall with 2 mm walls.", None),
            ("A PLA bracket. On it, a sealed hollow ball 16 mm across with a "
             "2 mm wall.", None),
        ):
            self.assertEqual(
                _the_container_the_brief_describes(brief).get("wall"), wall,
                brief)

    def test_the_middle_of_the_boss_s_top_is_not_the_centre(self) -> None:
        from forge_roles.library import _the_boss_the_brief_places

        for brief, claimed in (
            ("A hexagonal boss 19 mm across flats and 12 mm tall at x = 22, "
             "y = -18, with an M8 hole 12 mm deep in the middle of its top.",
             False),
            ("A steel plate. On top, in the centre of the plate, a "
             "cylindrical boss 36 mm in diameter standing 6 mm proud of the "
             "plate.", True),
        ):
            requirements: list = []
            _the_boss_the_brief_places(brief, requirements)
            self.assertEqual(bool(requirements), claimed, brief)


class WhatARoleWroteBeforeTheBudgetRanOutIsKept(unittest.TestCase):

    def test_the_refused_document_and_its_problems_are_on_file(self) -> None:
        import copy
        from fixtures.bracket_responses import (
            BRIEF, DESIGNER_VALID, INTERPRETER, REQUIREMENTS)
        from forge_models import Budget, ScriptedProvider
        from forge_orchestrator import Orchestrator, OrchestratorConfig, State

        refused = copy.deepcopy(DESIGNER_VALID)
        refused["document"]["components"][0]["features"][0]["kind"] = "blob"
        provider = ScriptedProvider(
            [INTERPRETER, REQUIREMENTS, refused, DESIGNER_VALID],
            budget=Budget(max_calls=3))
        run = Orchestrator(provider, config=OrchestratorConfig(
            measurement_depth=5, mesh_resolution=48)).design(BRIEF)
        self.assertIs(run.state, State.FAILED)
        detail = run.failure["detail"]
        self.assertEqual(detail["role"], "forgeir_designer")
        self.assertEqual(len(detail["refused_answers"]), 1)
        self.assertTrue(any("blob" in p for p in run.failure["problems"]))
        self.assertIn("refused answer(s) kept", run.render())


class AConsoleThatCannotShowTheBriefDoesNotStopTheRun(unittest.TestCase):

    def test_a_console_that_is_not_utf8_is_written_plain(
        self,
    ) -> None:
        import io
        import sys
        from forge_cli.cli import _a_console_that_cannot_fail

        raw = io.BytesIO()
        console = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
        saved = sys.stdout
        sys.stdout = console
        try:
            _a_console_that_cannot_fail()
            print("A plate \u2265 4 mm \u2192 \u021b, 70.0068 \u00b1 0.007 mm")
            console.flush()
        finally:
            sys.stdout = saved
        self.assertEqual(raw.getvalue(),
                         b"A plate >= 4 mm -> ?, 70.0068 +/- 0.007 mm\n")

    def test_a_utf8_console_is_left_as_it_is(self) -> None:
        import io
        import sys
        from forge_cli.cli import _a_console_that_cannot_fail

        raw = io.BytesIO()
        console = io.TextIOWrapper(raw, encoding="utf-8", newline="\n")
        saved = sys.stdout
        sys.stdout = console
        try:
            _a_console_that_cannot_fail()
            print("70.0068 \u00b1 0.007 mm")
            console.flush()
        finally:
            sys.stdout = saved
        self.assertEqual(raw.getvalue().decode("utf-8"),
                         "70.0068 \u00b1 0.007 mm\n")


def _lug_part(edges: str, radius: float = 12.0, chamfer: float = 0.0):
    """A lone box 24 along x, 22 along y and 16 tall, its corner at the
    origin, with one end rounded or chamfered."""
    import numpy as np  # noqa: F401 - the caller probes it

    from test_v1_complete import _build

    parameters = {"size": {"vector": [24, 22, 16], "unit": "mm"},
                  "edges": edges}
    if chamfer:
        parameters["edge_chamfer"] = {"magnitude": chamfer, "unit": "mm"}
    else:
        parameters["edge_radius"] = {"magnitude": radius, "unit": "mm"}
    _, part = _build([{"id": "lug", "kind": "box", "parameters": parameters}])
    return part


def _inside(part, *point) -> bool:
    import numpy as np

    return float(part.solid(np.array([point], float))[0]) <= 1e-9


class AnEndRoundedInPlan(unittest.TestCase):
    """`vertical_<face>`: the two upright edges of one face, the rest of the
    box square -- a flat lug's free end, its root where it joins."""

    def test_a_full_round_at_each_end(self) -> None:
        # Each face: its middle reached, its corners cut, the far face square.
        for edges, tip, cut, square in (
                ("vertical_y_max", (12, 21.9, 8), (0.5, 21.5, 8),
                 (0.2, 0.2, 8)),
                ("vertical_y_min", (12, 0.1, 8), (0.5, 0.5, 8),
                 (0.2, 21.8, 8))):
            part = _lug_part(edges)
            self.assertTrue(_inside(part, *tip), edges)
            self.assertFalse(_inside(part, *cut), edges)
            self.assertTrue(_inside(part, *square), edges)
        # Across y, 22 wide: a radius of 11 is its full round.
        for edges, tip, cut, square in (
                ("vertical_x_max", (23.9, 11, 8), (23.5, 0.5, 8),
                 (0.2, 0.2, 8)),
                ("vertical_x_min", (0.1, 11, 8), (0.5, 21.5, 8),
                 (23.8, 21.8, 8))):
            part = _lug_part(edges, radius=11.0)
            self.assertTrue(_inside(part, *tip), edges)
            self.assertFalse(_inside(part, *cut), edges)
            self.assertTrue(_inside(part, *square), edges)

    def test_the_round_is_the_radius_about_its_centre(self) -> None:
        import math

        part = _lug_part("vertical_y_max")
        # The semicircle about (12, 10): every point of it at 12 mm.
        for angle in (0.1, 0.6, 1.2, 1.57, 2.2, 3.0):
            x = 12 + 11.9 * math.cos(angle)
            y = 10 + 11.9 * math.sin(angle)
            self.assertTrue(_inside(part, x, y, 15.9), angle)
            x = 12 + 12.1 * math.cos(angle)
            y = 10 + 12.1 * math.sin(angle)
            self.assertFalse(_inside(part, x, y, 0.1), angle)

    def test_a_chamfered_end(self) -> None:
        part = _lug_part("vertical_y_max", chamfer=5.0)
        self.assertFalse(_inside(part, 0.5, 21.5, 8))
        self.assertTrue(_inside(part, 5.5, 21.5, 8))
        self.assertTrue(_inside(part, 0.5, 16.5, 8))

    def test_a_radius_past_half_the_face_is_refused(self) -> None:
        from forge_kernel import CompileError
        from forge_geom import DegenerateGeometryError

        with self.assertRaises((CompileError, DegenerateGeometryError)):
            _lug_part("vertical_y_max", radius=12.5)


class ALugEndsWhereItIsFree(unittest.TestCase):
    """The exo arm's forearm rail, 19 October: "a lug ... ends in a
    semicircle of radius 12 mm", drawn as a 24 by 22 box 16 thick rounded
    `top_along_y` at 12. Clamped to 8 on those edges, it came out square in
    plan with its top edges rounded, the boss on it overhanging -- and 34 of
    34 checks passed."""

    @classmethod
    def setUpClass(cls) -> None:
        from test_unusual_briefs import _designed

        cls.draft = _designed(_load("exo_forearm_rail_lug_clamped"))

    def _lug(self, component=None):
        component = component or json.loads(
            self.draft.document.to_json())["components"][0]
        return next(f for f in component["features"]
                    if f["id"] in ("lug_tab", "lug"))

    def test_the_lug_is_rounded_in_plan_at_its_free_end(self) -> None:
        lug = self._lug()["parameters"]
        self.assertEqual(lug["edges"], "vertical_y_max")
        self.assertEqual(lug["edge_radius"]["expression"],
                         "lug_semicircle_radius")

    def test_the_lug_built_is_the_semicircle_under_its_boss(self) -> None:
        from test_unusual_briefs import _part

        part = _part(self.draft)
        # Its tip 40 from the centreline, 12 beyond the hole's centre at 28.
        self.assertTrue(_inside(part, 46, 39.9, 8))
        # Its far corners gone, its root corners kept.
        self.assertFalse(_inside(part, 34.5, 39.5, 8))
        self.assertFalse(_inside(part, 57.5, 39.5, 8))
        self.assertTrue(_inside(part, 34.2, 18.5, 8))
        # The 20 mm boss stands on lug all round, at the top of the lug.
        for x, y in ((36.2, 28), (55.8, 28), (46, 37.8)):
            self.assertTrue(_inside(part, x, y, 15.9), (x, y))

    def test_the_rail_passes_as_settled(self) -> None:
        from test_unusual_briefs import _failing, _verify

        self.assertEqual(_failing(_verify(self.draft)), {})

    def _bar_and_lug(self, lug_length: float, edges: str, holed: bool):
        features = [
            {"id": "bar", "kind": "box", "parameters": {
                "size": {"vector": [200, 36, 16], "unit": "mm"},
                "origin": {"vector": [0, -18, 0], "unit": "mm"}}},
            {"id": "lug", "kind": "box", "parameters": {
                "size": {"vector": [24, lug_length, 16], "unit": "mm"},
                "origin": {"vector": [34, 18, 0], "unit": "mm"},
                "edges": edges,
                "edge_radius": {"magnitude": 12, "unit": "mm"}}},
            {"id": "body", "kind": "union", "inputs": ["bar", "lug"]}]
        if holed:
            features.append({"id": "pin", "kind": "hole", "inputs": ["body"],
                             "parameters": {
                                 "diameter": {"magnitude": 6.4, "unit": "mm"},
                                 "position": {"vector": [
                                     46, 18 + lug_length - 12, 8],
                                     "unit": "mm"},
                                 "axis": [0, 0, 1]}})
        return {"parameters": [], "features": features}

    def test_either_sign_finds_the_free_end(self) -> None:
        from forge_roles.library import _a_corner_rounder_than_its_side

        for holed in (True, False):
            for edges in ("top_along_y", "along_x", "vertical"):
                component = self._bar_and_lug(22, edges, holed)
                self.assertTrue(_a_corner_rounder_than_its_side(component))
                self.assertEqual(self._lug(component)["parameters"]["edges"],
                                 "vertical_y_max", (holed, edges))

    def test_a_lug_long_enough_for_both_ends_keeps_its_root(self) -> None:
        # Twelve fits both ends of a 30 mm reach; its root rounded full round
        # would meet the bar at a line.
        from forge_roles.library import _a_corner_rounder_than_its_side

        component = self._bar_and_lug(30, "along_y", False)
        self.assertTrue(_a_corner_rounder_than_its_side(component))
        self.assertEqual(self._lug(component)["parameters"]["edges"],
                         "vertical_y_max")

    def test_a_box_with_no_sign_of_its_ends_is_left_as_it_was(self) -> None:
        from forge_roles.library import _a_corner_rounder_than_its_side

        lone = {"parameters": [], "features": [
            self._bar_and_lug(22, "top_along_y", False)["features"][1]]}
        self.assertTrue(_a_corner_rounder_than_its_side(lone))
        lug = self._lug(lone)["parameters"]
        self.assertEqual(lug["edges"], "top_along_y")
        self.assertTrue(lug["edge_radius"]["expression"].startswith("min("))
        link = {"parameters": [], "features": [
            self._bar_and_lug(30, "along_y", False)["features"][1]]}
        _a_corner_rounder_than_its_side(link)
        self.assertEqual(self._lug(link)["parameters"]["edges"], "vertical")


class AClaimedFigureCutShort(unittest.TestCase):
    """A `min` that takes a checked parameter below its own figure: the
    claim passes on the parameter table and the part does not have it."""

    def _component(self, limit: str):
        return {"parameters": [
            {"id": "end_radius", "value": {"magnitude": 12.0, "unit": "mm"}},
            {"id": "thick", "value": {"magnitude": 16.0, "unit": "mm"}}],
            "features": [{"id": "lug", "kind": "box", "parameters": {
                "size": {"vector": [24, 22, "thick"], "unit": "mm"},
                "edges": "top_along_y",
                "edge_radius": {"expression": f"min(end_radius, {limit})",
                                "unit": "mm"}}}]}

    def _claims(self, *names):
        from types import SimpleNamespace

        return SimpleNamespace(requirements=[
            {"measurement": f"parameter:{n}"} for n in names])

    def test_a_claimed_radius_clamped_is_sent_back(self) -> None:
        from forge_roles.library import _a_measured_figure_cut_short

        said = _a_measured_figure_cut_short(
            self._component("thick / 2"), self._claims("end_radius"))
        self.assertEqual(len(said), 1)
        self.assertIn("`lug.edge_radius`", said[0])
        self.assertIn("8 mm where the part is built", said[0])

    def test_what_is_not_claimed_or_not_cut_is_left(self) -> None:
        from forge_roles.library import _a_measured_figure_cut_short

        self.assertEqual(_a_measured_figure_cut_short(
            self._component("thick / 2"), self._claims("thick")), [])
        self.assertEqual(_a_measured_figure_cut_short(
            self._component("thick"), self._claims("end_radius")), [])
        # Held under half a side by a hundredth: the figure, to 0.05 mm.
        self.assertEqual(_a_measured_figure_cut_short(
            self._component("24 * mm / 2 - 0.01 * mm"),
            self._claims("end_radius")), [])


class ALastLookThatSawAFault(unittest.TestCase):
    """The forearm rail's last look saw its lug rounded 8 mm where the brief
    says 12, wrote "correct the edge_radius cap" and no patch -- and was
    recorded "looked at the part against the brief: nothing to change"."""

    FAULT = {"diagnosis": "The lug ends rounded 8 mm, not the 12 mm the "
                          "brief gives its semicircle.",
             "strategy": "Correct the edge radius so the tip rounds to the "
                         "full 12 mm.",
             "confidence": "high", "abandon": False, "patches": []}

    def test_its_fix_in_words_is_asked_for_as_patches(self) -> None:
        from forge_roles import FailureAnalyst, RoleOutputError

        with self.assertRaises(RoleOutputError) as raised:
            FailureAnalyst().parse(dict(self.FAULT),
                                   failure={"kind": "last_look"},
                                   document_slice={})
        self.assertIn("Write the patches", " ".join(raised.exception.problems))

    def test_a_look_that_changes_nothing_is_still_one_call(self) -> None:
        from forge_roles import FailureAnalyst

        for strategy in ("", "none", "No change -- release as built.",
                         "Release it as built."):
            proposal = FailureAnalyst().parse(
                {"diagnosis": "Everything matches the brief.",
                 "strategy": strategy, "abandon": False, "patches": []},
                failure={"kind": "last_look"}, document_slice={})
            self.assertTrue(proposal.abandon, strategy)
            self.assertTrue(proposal.found_nothing, strategy)

    def test_a_fault_given_up_on_is_said_as_that(self) -> None:
        from test_the_four_runs import TheCollarsLastLook

        look = TheCollarsLastLook()
        run, looks = look._look(dict(self.FAULT), dict(self.FAULT))
        self.assertEqual(len(looks), 2)
        self.assertEqual(run.repairs[-1].outcome,
                         "saw a fault and wrote no edit for it")
        said = [e.summary for e in run.events]
        self.assertTrue(any(s.startswith("the last look saw a fault")
                            for s in said), said)
        self.assertFalse(any("nothing to change" in s for s in said), said)


class AStripsRoundEndsAreItsShape(unittest.TestCase):
    """The exo arm's wrist link strip, 19 October: "both ends fully
    rounded". The designer drew a box rounded `width / 2` on its upright
    edges; Forge took that off as a fillet nobody asked for, nothing
    measured the ends, the last look called square ends round, and the
    strip passed 25 of 25 square-ended."""

    @classmethod
    def setUpClass(cls) -> None:
        from test_unusual_briefs import _designed

        cls.case = _load("exo_wrist_strip_ends_taken_off")
        cls.draft = _designed(cls.case)

    def test_the_designers_round_ends_are_kept(self) -> None:
        component = json.loads(self.draft.document.to_json())["components"][0]
        body = next(f for f in component["features"] if f["id"] == "body")
        self.assertEqual(body["parameters"]["edges"], "vertical")
        self.assertEqual(body["parameters"]["edge_radius"]["expression"],
                         "width / 2")
        self.assertFalse(any("took off" in n for n in self.draft.notes))

    def test_the_ends_are_claimed_and_the_strip_passes(self) -> None:
        from test_unusual_briefs import _failing, _record, _verify

        record = _record(self.case)
        ends = [r for r in record.requirements if r["id"] == "REQ_ENDS_ROUND"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["measurement"], "ends_round:8")
        report = _verify(self.draft)
        self.assertEqual(_failing(report), {})
        self.assertIn("REQ_ENDS_ROUND",
                      {r.gate.identifier for r in report.gate_results})

    def test_square_ends_fail_the_claim(self) -> None:
        import copy

        from test_unusual_briefs import _designed, _failing, _verify

        square = copy.deepcopy(self.case["document"])
        body = next(f for f in square["components"][0]["features"]
                    if f["id"] == "body")
        body["parameters"].pop("edge_radius")
        body["parameters"].pop("edges")
        report = _verify(_designed(self.case, square))
        self.assertEqual(_failing(report), {"REQ_ENDS_ROUND": "FAIL"})

    def test_the_slot_port_is_the_extrudes_side(self) -> None:
        component = json.loads(self.draft.document.to_json())["components"][0]
        port = next(i for i in component["interfaces"]
                    if i["id"] == "guide_slot_port")
        self.assertEqual(port["geometry"], "slot_extrude.side")

    def test_which_roundings_draw_an_end(self) -> None:
        from forge_roles.library import _a_rounding_that_draws_an_end

        for kind, parameters, draws in (
                ("box", {"edges": "vertical"}, True),
                ("box", {"edges": "vertical_y_max"}, True),
                ("box", {"edges": "top_along_x"}, True),
                ("box", {}, False),
                ("box", {"edges": "top"}, False),
                ("profile_rectangle", {"corner_radius": 3}, True),
                ("union", {"blend_radius": 8}, False),
                ("extrude", {"end_radius": 1}, False)):
            self.assertEqual(_a_rounding_that_draws_an_end(
                {"kind": kind, "parameters": parameters}), draws,
                (kind, parameters))

    def test_the_ends_claim_is_made_only_where_it_fits(self) -> None:
        from forge_roles.library import _both_ends_round_measured

        for brief, radius in (
                (self.case["brief"], 8.0),
                ("A PLA obround plate 20 mm wide, 60 mm long and 4 mm thick "
                 "with fully rounded ends.", 10.0),
                ("A PLA link 75 mm long, 12 mm wide and 5 mm thick, both "
                 "ends fully rounded, with an 8 mm hole at each end.", 6.0),
                ("A PLA strip 80 mm long, 10 mm wide and 2 mm thick with "
                 "rounded ends.", None),
                ("A PLA upper-arm rail: a flat bar 36 mm wide and 20 mm "
                 "thick. One end of the bar is a round end 48 mm in "
                 "diameter; the far end is fully rounded.", None),
                ("A PLA bar 80 mm long, 12 mm wide and 4 mm thick with both "
                 "ends fully rounded and a tab sticking out of one side.",
                 None),
                ("A curved PLA strap 100 mm long, 20 mm wide and 2 mm thick, "
                 "both ends fully rounded, curved with an inside radius of "
                 "40 mm.", None)):
            requirements: list = []
            _both_ends_round_measured(brief, requirements)
            if radius is None:
                self.assertEqual(requirements, [], brief)
            else:
                self.assertEqual([r["measurement"] for r in requirements],
                                 [f"ends_round:{radius:g}"], brief)


class AHoleOnEachThingPlacedPerCorner(unittest.TestCase):
    """The exo arm's switch box, 19 October: "In each of the four inside
    corners, a square post ... with a 2.8 mm hole 12 mm deep down into the
    middle of its top." Forge counted one 2.8 mm hole, the design had the
    four asked for, the analyst refused to delete three, and the run was
    blocked after a redesign -- $1.40 on a correct part."""

    def test_the_box_is_held_to_four_and_passes(self) -> None:
        from test_unusual_briefs import _designed, _failing, _record, _verify

        case = _load("exo_switch_box_holes_per_corner")
        record = _record(case)
        counts = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in record.requirements
                  if r["measurement"].startswith("holes_of_diameter")}
        self.assertEqual(counts, {"holes_of_diameter:2.8": 4,
                                  "holes_of_diameter:8": 1})
        self.assertEqual(_failing(_verify(_designed(case))), {})

    def test_holes_counted_per_place_and_one_by_one(self) -> None:
        from forge_roles.library import _the_holes_the_brief_states

        for brief, counts in (
                ("A PLA bar 100 mm long, 20 mm wide and 5 mm thick. At each "
                 "end, a round lug 20 mm across with a 6 mm hole through it.",
                 {"6": 2}),
                ("A PLA bracket 60 mm long with a tab at each end, with a "
                 "6 mm hole in the middle of the plate.", {"6": 1}),
                ("A plate 80 by 60 by 4 mm with a 5 mm hole in each corner "
                 "and a 10 mm hole in the centre.", {"5": 4, "10": 1}),
                ("A plate with a 10 mm hole in the centre and a 5 mm hole in "
                 "each corner.", {"10": 1, "5": 4}),
                ("In each corner of the plate there is a 5 mm hole, and a "
                 "10 mm hole goes through the centre.", {"5": 4, "10": 1}),
                ("On each tab, a boss with a 4 mm hole.", {})):
            requirements: list = []
            _the_holes_the_brief_states(brief, requirements)
            self.assertEqual(
                {r["measurement"].split(":")[1]: r["threshold"]["magnitude"]
                 for r in requirements}, counts, brief)


if __name__ == "__main__":
    unittest.main()
