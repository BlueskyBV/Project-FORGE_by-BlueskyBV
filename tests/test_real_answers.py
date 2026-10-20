"""Real model answers from real runs, replayed through Forge as it is now.

Every fixture under ``fixtures/real_runs`` is an answer a laptop model gave
on a real run -- the requirements it wrote, the design it drew, or the
document the run ended with -- together with the brief and the record it was
given. They are frozen here because the failures that cost the most were all
of one kind: a helper tested in isolation, correct in isolation, and wrong on
the path a real answer takes through ``parse``. A synthetic test says what
Forge was meant to do. These say what it does with what the model actually
writes.

Each case states the outcome the answer deserves: parsed, and then either
PASS, or FAIL on exactly the gates that are the design's own fault.
"""

from __future__ import annotations

import json
import pathlib
import unittest

HERE = pathlib.Path(__file__).parent / "fixtures" / "real_runs"


def _load(name: str) -> dict:
    return json.loads((HERE / f"{name}.json").read_text())


def _intent(case: dict):
    from forge_roles.library import Intent

    i = case.get("intent") or {}
    return Intent(
        summary=i.get("summary", ""), part_kind=i.get("part_kind", ""),
        stated=tuple(i.get("stated", ())), implied=tuple(i.get("implied", ())),
        unstated=tuple(i.get("unstated", ())))


def _requirements(case: dict):
    from forge_roles import RequirementsEngineer

    return RequirementsEngineer().parse(case["requirements"], brief=case["brief"])


def _design(case: dict):
    from forge_roles import ForgeIRDesigner

    return ForgeIRDesigner().parse(
        case["answer"], requirements=_requirements(case), intent=_intent(case),
        brief=case["brief"], document_id="", project_id="", answers={})


def _verify(draft):
    from forge_pipeline import verify_component

    return verify_component(
        draft.document, draft.document.components[0], measurement_depth=6)


def _not_passing(report) -> dict[str, str]:
    return {
        r.gate.identifier: r.status.value for r in report.gate_results
        if r.status.value not in ("PASS", "NOT_APPLICABLE")
    }


class TheCollarAnswersNowBuildTheCollar(unittest.TestCase):
    """Two set screws, 90 degrees apart, through the wall into the bore.

    Across the collar runs the model got that relationship wrong four
    different ways, each time on an otherwise correct design. Each is now the
    collar the brief describes, gated and passing.
    """

    def _passes(self, name: str) -> None:
        case = _load(name)
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {}, name)
        self.assertEqual(report.overall_status.value, "PASS", name)
        self.assertEqual(report.measurements["part"]["open_holes"], 3, name)

    def test_the_angle_in_degrees_written_as_a_spacing(self) -> None:
        self._passes("collar_angle_in_degrees_as_a_spacing")

    def test_the_angle_in_millimetres_written_as_a_spacing(self) -> None:
        self._passes("collar_angle_in_millimetres_as_a_spacing")

    def test_the_screws_drilled_down_the_shaft(self) -> None:
        self._passes("collar_screws_down_the_shaft")

    def test_the_screws_drilled_down_the_shaft_with_a_spacing(self) -> None:
        self._passes("collar_screws_down_the_shaft_with_a_spacing")

    def test_the_screws_drilled_parallel_across_the_body(self) -> None:
        """This run was released. Its screws were parallel: 0 degrees."""
        self._passes("collar_parallel_screws_across_the_body")

    def test_the_correct_answer_stays_correct(self) -> None:
        self._passes("collar_correct")

    def test_the_collar_that_left_out_its_bore(self) -> None:
        """Screws right, and no bore: `bore_diameter` declared, measured and
        read by nothing, three attempts running. Blocked after 5,200 s."""
        self._passes("collar_without_its_bore")

    def test_the_bore_is_declared_too_when_the_design_never_named_it(
        self,
    ) -> None:
        case = _load("collar_without_its_bore")
        component = case["answer"]["document"]["components"][0]
        component["parameters"] = [p for p in component["parameters"]
                                   if p["id"] != "bore_diameter"]
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.measurements["part"]["open_holes"], 3)


class ABoreIsNeverInvented(unittest.TestCase):
    """The bore repair acts only where nothing about the bore is a choice."""

    def _notes(self, name, brief, features, parameters):
        from forge_roles.library import (
            RequirementSet, _the_bore_the_record_measures)

        component = {"id": "c", "features": features,
                     "parameters": parameters}
        record = RequirementSet(requirements=({
            "id": "R", "measurement": f"parameter:{name}",
            "comparison": "equals",
            "threshold": {"magnitude": 6.0, "unit": "mm"}},),
            assumptions=(), unknowns=())
        return _the_bore_the_record_measures(component, record, brief), component

    BODY = {"id": "body", "kind": "cylinder", "parameters": {
        "diameter": {"magnitude": 25.0, "unit": "mm"},
        "height": {"magnitude": 10.0, "unit": "mm"}}}

    def test_mounting_holes_are_not_a_bore(self) -> None:
        notes, _ = self._notes(
            "mounting_hole_diameter", "A disc with a bore through it.",
            [dict(self.BODY)], [])
        self.assertEqual(notes, [])

    def test_a_brief_with_no_bore_gets_none(self) -> None:
        notes, _ = self._notes(
            "hole_diameter", "A disc 25 mm across with a 6 mm hole.",
            [dict(self.BODY)], [])
        self.assertEqual(notes, [])

    def test_two_round_bodies_are_two_axes(self) -> None:
        other = {"id": "boss", "kind": "cylinder", "parameters": {
            "diameter": {"magnitude": 10.0, "unit": "mm"},
            "height": {"magnitude": 5.0, "unit": "mm"},
            "origin": {"vector": [8, 0, 10], "unit": "mm"}}}
        notes, _ = self._notes(
            "bore_diameter", "A hub with a bore through it.",
            [dict(self.BODY), other,
             {"id": "u", "kind": "union", "inputs": ["body", "boss"]}], [])
        self.assertEqual(notes, [])

    def test_a_bore_already_drilled_is_left_alone(self) -> None:
        drilled = {"id": "h", "kind": "hole", "inputs": ["body"], "parameters": {
            "diameter": {"magnitude": 6.0, "unit": "mm"},
            "position": {"vector": [0, 0, 5], "unit": "mm"},
            "axis": [0.0, 0.0, 1.0]}}
        notes, _ = self._notes(
            "bore_diameter", "A disc with a bore through it.",
            [dict(self.BODY), drilled], [])
        self.assertEqual(notes, [])

    def test_the_plain_case_is_drilled_on_the_axis(self) -> None:
        notes, component = self._notes(
            "bore_diameter", "A disc with a 6 mm bore through it.",
            [dict(self.BODY)], [])
        self.assertTrue(notes)
        bore = component["features"][-1]
        self.assertEqual(bore["kind"], "hole")
        self.assertEqual(bore["inputs"], ["body"])
        self.assertEqual(bore["parameters"]["axis"], [0.0, 0.0, 1.0])
        self.assertEqual(bore["parameters"]["position"]["vector"][:2], [0, 0])


class TheSquareCollarIsStillCaught(unittest.TestCase):
    def test_a_block_is_not_a_collar(self) -> None:
        """A 25 by 25 by 15 block, centred on the origin, with its set screws
        at `thickness / 2` -- its top face. Square, and notched rather than
        drilled: both are the design's faults, and both are named."""
        case = _load("collar_square_block")
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {
            "REQ_ROUND": "FAIL", "GEOM_HOLES_ARE_HOLES": "FAIL",
        # A notch is not a hole: set screws cut along the top edge are not
        # the 4 mm holes the brief asks for.
        "REQ_HOLES_4MM": "FAIL"})
        notched = next(r for r in report.gate_results
                       if r.gate.identifier == "GEOM_HOLES_ARE_HOLES")
        self.assertEqual(
            sorted(n["feature"] for n in notched.evidence.detail["notched"]),
            ["set_screw_hole_1", "set_screw_hole_2"])


class TheSpacerAnswers(unittest.TestCase):
    def test_two_names_for_one_thickness(self) -> None:
        """`base_height` (4 mm, declared, measured) in the plate's Y slot and
        `base_thickness` used everywhere and declared nowhere. The plate is
        now square and reads one name for its thickness."""
        case = _load("spacer_two_names_for_one_thickness")
        draft = _design(case)
        base = draft.payload["components"][0]["features"][0]
        self.assertEqual(base["parameters"]["size"]["vector"],
                         ["base_width", "base_width", "base_height"])
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})

    def test_the_spacer_that_was_released_as_a_bar(self) -> None:
        """Released: `[base_width, base_height, base_thickness]` at 30, 4, 4
        -- a 30 by 4 bar under the post, where the brief said a 30 mm square
        plate. Both 4 mm names are the thickness; the record measures one and
        the features read the other."""
        case = _load("spacer_released_as_a_bar")
        draft = _design(case)
        component = draft.payload["components"][0]
        base = component["features"][0]
        self.assertEqual(base["parameters"]["size"]["vector"],
                         ["base_width", "base_width", "base_height"])
        self.assertNotIn("base_thickness",
                         [p["id"] for p in component["parameters"]])
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        envelope = report.measurements["part"]["envelope_mm"]
        self.assertAlmostEqual(envelope[0], envelope[1], delta=0.5)

    def test_the_correct_answers_stay_correct(self) -> None:
        for name in ("spacer_correct", "spacer_correct_earlier"):
            report = _verify(_design(_load(name)))
            self.assertEqual(_not_passing(report), {}, name)


class TheRequirementsAnswers(unittest.TestCase):
    def test_forge_s_own_roundness_claim_does_not_end_the_run(self) -> None:
        """The run that died in 293 s: Forge's REQ_ROUND, rejected by a stale
        copy of the vocabulary and charged to the model."""
        from forge_roles import RequirementsEngineer

        case = _load("collar_requirements_forge_round_rejected")
        record = RequirementsEngineer().parse(case["answer"], brief=case["brief"])
        bindings = {r["id"]: r.get("measurement") for r in record.requirements}
        self.assertEqual(bindings.get("REQ_ROUND"), "roundness")
        self.assertFalse(any("FORGE DEFECT" in n for n in record.notes))

    def test_a_record_of_parameters_gains_the_geometry(self) -> None:
        from forge_roles import RequirementsEngineer

        case = _load("collar_requirements_all_parameters")
        record = RequirementsEngineer().parse(case["answer"], brief=case["brief"])
        bindings = [str(r.get("measurement", "")) for r in record.requirements]
        self.assertIn("roundness", bindings)
        self.assertTrue(any(b.startswith("angle_between:") for b in bindings))
        self.assertTrue(any(b.startswith("bounding_box_") for b in bindings))

    def test_a_standoff_on_a_square_plate_is_not_claimed_round(self) -> None:
        """25 mm across is the standoff; the part's footprint is the 50 mm
        square plate. REQ_ROUND there would fail a correct part."""
        record = _requirements(_load("standoff_pieces_on_one_extent"))
        bindings = [str(r.get("measurement", "")) for r in record.requirements]
        self.assertNotIn("roundness", bindings)
        self.assertNotIn("roundness_about_z", bindings)

    def test_pieces_of_the_part_move_off_the_whole_part_extent(self) -> None:
        record = _requirements(_load("standoff_pieces_on_one_extent"))
        bindings = {r["id"]: r.get("measurement") for r in record.requirements}
        self.assertEqual(bindings["REQ_STANDOFF_HEIGHT"],
                         "parameter:standoff_height")
        self.assertEqual(bindings["REQ_BASE_PLATE_THICKNESS"],
                         "parameter:base_plate_thickness")

    def test_a_bound_on_the_whole_part_stays_on_it(self) -> None:
        record = _requirements(_load("motor_mount_plate_thickness_on_the_extent"))
        bindings = {r["id"]: r.get("measurement") for r in record.requirements}
        self.assertEqual(bindings["REQ_MAX_HEIGHT"], "bounding_box_z")
        self.assertEqual(bindings["REQ_BASE_PLATE_THICKNESS"],
                         "parameter:base_plate_thickness")


class OneVocabulary(unittest.TestCase):
    """Every binding the vocabulary names has one place that says its unit."""

    def test_every_binding_has_a_unit_entry(self) -> None:
        from forge_ir.measurements import (
            MEASURED_IN, PARAMETERISED_MEASUREMENTS, SIMPLE_MEASUREMENTS)

        for name in SIMPLE_MEASUREMENTS + PARAMETERISED_MEASUREMENTS:
            self.assertIn(name, MEASURED_IN, name)

    def test_the_designer_and_the_engineer_see_every_binding(self) -> None:
        from forge_roles.library import _ALL_BINDINGS

        for name in ("angle_between", "roundness", "roundness_about_z",
                     "feature_count", "parameter"):
            self.assertIn(name, _ALL_BINDINGS)

    def test_dimensionless_is_read_from_the_table(self) -> None:
        from forge_ir.measurements import is_dimensionless

        self.assertTrue(is_dimensionless("roundness"))
        self.assertTrue(is_dimensionless("feature_count:hole:x"))
        self.assertFalse(is_dimensionless("bounding_box_x"))
        self.assertFalse(is_dimensionless("angle_between:hole:x"))


class ForgeAnswersForItsOwnAdditions(unittest.TestCase):
    """A requirement Forge added or rebound is never charged to the model."""

    def test_a_broken_addition_is_dropped_and_recorded(self) -> None:
        from unittest import mock

        from forge_roles import RequirementsEngineer
        from forge_roles import library

        def broken(brief, requirements):
            requirements.append({
                "id": "REQ_FORGE_BROKEN", "measurement": "roundness",
                "comparison": "at_least",
                "threshold": {"magnitude": 0.95, "unit": "furlong"},
                "statement": "x", "source": "user"})
            return ["added REQ_FORGE_BROKEN"]

        answer = {"requirements": [{
            "id": "REQ_OD", "measurement": "parameter:outer_diameter",
            "comparison": "equals",
            "threshold": {"magnitude": 25.0, "unit": "mm"},
            "statement": "OD", "type": "geometric",
            "verification": "exact_geometry", "strength": "hard",
            "source": "user", "state": "accepted"}],
            "assumptions": [], "unknowns": []}
        with mock.patch.object(library, "_a_round_part_has_to_be_round", broken):
            record = RequirementsEngineer().parse(
                answer, brief="A collar with an outer diameter of 25 mm.")
        ids = {r["id"] for r in record.requirements}
        self.assertNotIn("REQ_FORGE_BROKEN", ids)
        self.assertIn("REQ_OD", ids)
        self.assertTrue(any("FORGE DEFECT" in n and "REQ_FORGE_BROKEN" in n
                            for n in record.notes))


class ARoundPartIsRoundWhicheverWayItLies(unittest.TestCase):
    @staticmethod
    def _measure(solid, which):
        from forge_pipeline import measure

        class Part:
            pass

        part = Part()
        part.solid = solid
        measured = getattr(measure, which)(part)
        assert measured.ok, measured.blocked_reason
        return measured.value.magnitude.midpoint

    def test_a_pin_lying_along_x(self) -> None:
        from forge_geom.sdf import CylinderSDF

        pin = CylinderSDF(base=(-30, 0, 0), axis=(1, 0, 0), radius=6.0,
                          height=60.0)
        self.assertGreater(self._measure(pin, "_roundness"), 0.95)
        self.assertLess(self._measure(pin, "_roundness_about_z"), 0.5)

    def test_a_block_is_square_every_way(self) -> None:
        from forge_geom.sdf import BoxSDF

        block = BoxSDF(centre=(0, 0, 7.5), half_extent=(12.5, 12.5, 7.5))
        self.assertLess(self._measure(block, "_roundness"), 0.8)


class HolesUnionedBackTogether(unittest.TestCase):
    def test_they_are_chained_instead(self) -> None:
        from forge_roles.library import _holes_unioned_back_together

        features = [
            {"id": "body", "kind": "box", "parameters": {}},
            {"id": "h1", "kind": "hole", "inputs": ["body"], "parameters": {}},
            {"id": "h2", "kind": "hole", "inputs": ["body"], "parameters": {}},
            {"id": "h3", "kind": "hole", "inputs": ["body"], "parameters": {}},
            {"id": "joined", "kind": "union", "inputs": ["h1", "h2", "h3"]},
            {"id": "after", "kind": "hole", "inputs": ["joined"],
             "parameters": {}},
        ]
        notes = _holes_unioned_back_together(features)
        self.assertTrue(notes)
        by_id = {f["id"]: f for f in features}
        self.assertNotIn("joined", by_id)
        self.assertEqual(by_id["h2"]["inputs"], ["h1"])
        self.assertEqual(by_id["h3"]["inputs"], ["h2"])
        self.assertEqual(by_id["after"]["inputs"], ["h3"])

    def test_a_union_of_patterns_is_left_alone(self) -> None:
        from forge_roles.library import _holes_unioned_back_together

        features = [
            {"id": "body", "kind": "box", "parameters": {}},
            {"id": "p1", "kind": "pattern_linear", "inputs": ["body"]},
            {"id": "p2", "kind": "mirror", "inputs": ["body"]},
            {"id": "joined", "kind": "union", "inputs": ["p1", "p2"]},
        ]
        self.assertEqual(_holes_unioned_back_together(features), [])
        self.assertEqual(len(features), 4)


class AHoleIsNotANotch(unittest.TestCase):
    """GEOM_HOLES_ARE_HOLES: material all the way round, somewhere."""

    def _report(self, z):
        from forge_ir import Document
        from forge_pipeline import verify_component

        document = Document.from_json(json.dumps({
            "schema_version": "1.0.0", "revision": 1, "name": "t",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "document_id": "00000000-0000-5000-8000-000000000000",
            "project_id": "00000000-0000-5000-8000-000000000001",
            "components": [{"id": "c", "parameters": [], "features": [
                {"id": "block", "kind": "box", "parameters": {
                    "size": {"vector": [25.0, 25.0, 15.0], "unit": "mm"},
                    "centered": True}},
                {"id": "cross", "kind": "hole", "inputs": ["block"],
                 "parameters": {
                     "diameter": {"magnitude": 4.0, "unit": "mm"},
                     "position": {"vector": [0, 0, z], "unit": "mm"},
                     "axis": [1.0, 0.0, 0.0]}}]}]}))
        report = verify_component(document, document.components[0],
                                  measurement_depth=6)
        return next(r for r in report.gate_results
                    if r.gate.identifier == "GEOM_HOLES_ARE_HOLES")

    def test_a_hole_through_the_middle_is_a_hole(self) -> None:
        self.assertEqual(self._report(0.0).status.value, "PASS")

    def test_a_hole_on_the_top_face_is_a_notch(self) -> None:
        self.assertEqual(self._report(7.5).status.value, "FAIL")

    def test_a_hole_near_but_inside_the_face_is_a_hole(self) -> None:
        self.assertEqual(self._report(4.5).status.value, "PASS")


class AQuantityInTheWrongKindOfField(unittest.TestCase):
    """Said at parse, to the designer, not by the compiler to a repair round."""

    def test_an_angle_in_a_position_is_named(self) -> None:
        from forge_roles import ForgeIRDesigner
        from forge_roles.base import RoleOutputError
        from forge_roles.library import Intent, RequirementSet

        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse(
                {"rationale": "x", "document": {"name": "P", "components": [{
                    "id": "p", "parameters": [
                        {"id": "w", "value": {"magnitude": 30.0, "unit": "mm"}},
                        {"id": "tilt", "value": {"magnitude": 30.0,
                                                 "unit": "deg"}}],
                    "features": [
                        {"id": "plate", "kind": "box", "parameters": {
                            "size": {"vector": ["w", "w", 4.0], "unit": "mm"},
                            "centered": True}},
                        {"id": "h", "kind": "hole", "inputs": ["plate"],
                         "parameters": {
                             "diameter": {"magnitude": 3.0, "unit": "mm"},
                             "position": {"vector": ["tilt", 0, 0],
                                          "unit": "mm"}}}]}]}},
                requirements=RequirementSet(requirements=(), assumptions=(),
                                            unknowns=()),
                intent=Intent(summary="A plate.", part_kind="plate", stated=(),
                              implied=(), unstated=()),
                brief="A 30 mm square plate with one 3 mm hole.",
                document_id="", project_id="")
        said = " ".join(caught.exception.problems)
        self.assertIn("`tilt` (30 deg)", said)
        self.assertIn("An angle is not a position", said)


class RoundOnlyWhenSomethingSaysRound(unittest.TestCase):
    """`across` says how wide, both ways. It does not say which shape."""

    @staticmethod
    def _carried(brief):
        from forge_roles.library import _normalise_requirements

        answer, _, _ = _normalise_requirements(
            {"requirements": [], "assumptions": [], "unknowns": []}, brief)
        return [str(r.get("measurement", "")) for r in answer["requirements"]]

    def test_a_block_across_is_not_claimed_round(self) -> None:
        self.assertNotIn("roundness", self._carried(
            "A block 60 mm across, 10 mm thick, with a 10 mm hole."))

    def test_a_plate_across_is_not_claimed_round(self) -> None:
        self.assertNotIn("roundness", self._carried(
            "A plate 60 mm across and 5 mm thick."))

    def test_round_things_are(self) -> None:
        for brief in (
            "A gear blank 60 mm across, 10 mm thick, with a 10 mm bore.",
            "A collar 25 mm across with a 12 mm bore.",
            "A washer with 10 mm inner diameter and 20 mm outer diameter, "
            "2 mm thick.",
            "A disc 40 mm in diameter and 6 mm thick.",
        ):
            self.assertIn("roundness", self._carried(brief), brief)

    def test_a_round_piece_of_a_square_part_is_not_the_part(self) -> None:
        carried = self._carried(
            "A cylindrical standoff 30 mm tall and 25 mm across, sitting on a "
            "50 mm square base plate 5 mm thick.")
        self.assertNotIn("roundness", carried)


class ASmallHoleIsADimension(unittest.TestCase):
    """GEOM_DIMENSIONS_DRIVE_THE_PART failed a 3 mm hole in a 2 mm plate.

    Nudged to 3.5 mm it moved 0.16 per cent of the volume -- under the
    thousandth that counts -- and no sample of a 4 mm lattice. The commonest
    feature there is, reported as a dimension the part does not have.
    """

    def _dimensions(self, width, thickness):
        from forge_ir import Document
        from forge_pipeline import verify_component

        document = Document.from_json(json.dumps({
            "schema_version": "1.0.0", "revision": 1, "name": "t",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "document_id": "00000000-0000-5000-8000-000000000000",
            "project_id": "00000000-0000-5000-8000-000000000001",
            "components": [{"id": "c", "parameters": [
                {"id": "w", "value": {"magnitude": width, "unit": "mm"}},
                {"id": "t", "value": {"magnitude": thickness, "unit": "mm"}},
                {"id": "h", "value": {"magnitude": 3.0, "unit": "mm"}}],
                "features": [
                    {"id": "plate", "kind": "box", "parameters": {
                        "size": {"vector": ["w", "w", "t"], "unit": "mm"},
                        "centered": True}},
                    {"id": "hole", "kind": "hole", "inputs": ["plate"],
                     "parameters": {
                         "diameter": {"expression": "h", "unit": "mm"},
                         "position": {"vector": [5, 5, 0], "unit": "mm"},
                         "axis": [0.0, 0.0, 1.0]}}]}]}))
        report = verify_component(document, document.components[0],
                                  measurement_depth=6)
        gate = next(r for r in report.gate_results
                    if r.gate.identifier == "GEOM_DIMENSIONS_DRIVE_THE_PART")
        return gate.status.value

    def test_in_a_thin_plate(self) -> None:
        self.assertEqual(self._dimensions(40.0, 2.0), "PASS")

    def test_in_a_big_plate(self) -> None:
        self.assertEqual(self._dimensions(150.0, 3.0), "PASS")


def _openings_round_the_outside(solid, z=7.5, radius=12.3) -> int:
    """Separate gaps in a ring just inside the collar's outer skin."""
    import numpy as np

    angles = np.linspace(0.0, 2.0 * np.pi, 720, endpoint=False)
    ring = np.stack([radius * np.cos(angles), radius * np.sin(angles),
                     np.full_like(angles, z)], axis=1)
    empty = np.asarray(solid(ring)) > 0
    return sum(1 for i in range(len(empty)) if empty[i] and not empty[i - 1])


class ASetScrewGoesThroughOneWall(unittest.TestCase):
    """Released with every gate green and four screw holes round the outside:
    each set screw drilled in one side and out the other. The brief asked for
    two, from the outside into the bore."""

    def test_the_released_collar_now_has_two_openings(self) -> None:
        report = _verify(_design(_load("collar_with_four_openings")))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(_openings_round_the_outside(report.part.solid), 2)

    def test_every_collar_answer_has_two(self) -> None:
        for name in ("collar_angle_in_degrees_as_a_spacing",
                     "collar_screws_down_the_shaft",
                     "collar_parallel_screws_across_the_body",
                     "collar_without_its_bore", "collar_correct"):
            report = _verify(_design(_load(name)))
            self.assertEqual(
                _openings_round_the_outside(report.part.solid), 2, name)

    def test_a_cross_hole_goes_right_across(self) -> None:
        from forge_roles.library import _a_set_screw_goes_through_one_wall

        component = {"id": "c", "parameters": [], "features": [
            {"id": "body", "kind": "cylinder", "parameters": {
                "diameter": {"expression": "od", "unit": "mm"},
                "height": {"magnitude": 30.0, "unit": "mm"}}},
            {"id": "bore", "kind": "hole", "inputs": ["body"], "parameters": {
                "diameter": {"magnitude": 8.0, "unit": "mm"},
                "position": {"vector": [0, 0, 15], "unit": "mm"},
                "axis": [0.0, 0.0, 1.0]}},
            {"id": "x", "kind": "hole", "inputs": ["bore"], "parameters": {
                "diameter": {"magnitude": 3.0, "unit": "mm"},
                "position": {"vector": [0, 0, 15], "unit": "mm"},
                "axis": [1.0, 0.0, 0.0]}}]}
        self.assertEqual(_a_set_screw_goes_through_one_wall(
            component, "A shaft with an 8 mm bore and a 3 mm cross hole into "
            "the bore."), [])
        self.assertEqual(_a_set_screw_goes_through_one_wall(
            component, "A pin with a 3 mm hole through it."), [])
        self.assertNotIn("depth", component["features"][2]["parameters"])


class EveryHoleTheBriefSizesIsCounted(unittest.TestCase):
    """A collar released with every claim green and no collar in it.

    Both set screws were drawn at the bore's 12 mm, across the part, and
    there was no bore. `parameter:bore_diameter` passed because a hole read
    it; the angle passed because the two holes were 90 degrees apart; the
    4 mm was "not checked" and said so. Nothing counted the holes.
    """

    def test_the_released_document_now_fails_on_its_holes(self) -> None:
        from forge_ir import Document
        from forge_pipeline import verify_component

        case = _load("collar_with_its_screws_at_the_bores_size")
        document = dict(case["answer"]["document"])
        document["requirements"] = [
            dict(r) for r in _requirements(case).requirements]
        built = Document.from_json(json.dumps(document))
        report = verify_component(built, built.components[0],
                                  measurement_depth=6)
        failing = _not_passing(report)
        self.assertEqual(failing.get("REQ_HOLES_4MM"), "FAIL")
        self.assertEqual(failing.get("REQ_HOLES_12MM_ON_AXIS"), "FAIL")

    def test_and_its_answer_now_builds_the_collar(self) -> None:
        report = _verify(_design(_load("collar_with_its_screws_at_the_bores_size")))
        self.assertEqual(_not_passing(report), {})
        holes = sorted(h["diameter_mm"] for h in
                       report.measurements["part"]["holes"])
        self.assertEqual(holes, [4.0, 4.0, 12.0])
        self.assertEqual(_openings_round_the_outside(report.part.solid), 2)

    def test_the_spacer_that_passed_live_still_passes(self) -> None:
        report = _verify(_design(_load("spacer_first_live_pass")))
        self.assertEqual(_not_passing(report), {})
        gates = {r.gate.identifier: r for r in report.gate_results}
        self.assertEqual(gates["REQ_HOLES_5MM"].status.value, "PASS")
        self.assertEqual(gates["REQ_HOLES_3MM"].status.value, "PASS")

    @staticmethod
    def _counted(brief):
        from forge_roles.library import _normalise_requirements

        answer, _, _ = _normalise_requirements(
            {"requirements": [], "assumptions": [], "unknowns": []}, brief)
        return {str(r["measurement"]): r["threshold"]["magnitude"]
                for r in answer["requirements"]
                if str(r["measurement"]).startswith("holes_of_diameter")}

    def test_what_the_brief_counts(self) -> None:
        self.assertEqual(self._counted(
            "A shaft collar. The outer diameter is 25 mm and it is 15 mm "
            "long. A 12 mm bore runs all the way through on the axis. Two "
            "4 mm set screw holes pass through the wall into the bore."),
            {"holes_of_diameter:12:on_axis": 1, "holes_of_diameter:4": 2})
        self.assertEqual(self._counted(
            "A plate 60 mm long, 40 mm wide and 6 mm thick. An 8 mm shaft "
            "bore runs through it. Four 4.5 mm mounting holes pass through "
            "the plate."),
            {"holes_of_diameter:8": 1, "holes_of_diameter:4.5": 4})

    def test_a_hole_said_twice_is_one_hole(self) -> None:
        self.assertEqual(self._counted(
            "A 40 mm square plate 5 mm thick with a 6 mm hole in the middle. "
            "The 6 mm hole is countersunk."), {"holes_of_diameter:6": 1})

    def test_a_brief_with_no_sized_holes_counts_none(self) -> None:
        self.assertEqual(self._counted(
            "A bracket that holds a 20 mm shaft 32 mm above a flat plate it "
            "bolts to with four M5 bolts."), {})

    def test_the_vocabulary_refuses_a_hole_with_no_size(self) -> None:
        from forge_ir.measurements import MeasurementError, parse_measurement

        self.assertEqual(parse_measurement("holes_of_diameter:4.5").argument,
                         "4.5")
        self.assertEqual(
            parse_measurement("holes_of_diameter:12:on_axis").sub_argument,
            "on_axis")
        for bad in ("holes_of_diameter:big", "holes_of_diameter:4:sideways"):
            with self.assertRaises(MeasurementError):
                parse_measurement(bad)

    def test_a_resize_needs_one_reading(self) -> None:
        """Three alike holes where two are counted: which two is a choice."""
        from forge_roles.library import (
            RequirementSet, _holes_sized_as_the_record_counts)

        def hole(i):
            return {"id": i, "kind": "hole", "inputs": ["body"], "parameters": {
                "diameter": {"magnitude": 12.0, "unit": "mm"},
                "position": {"vector": [0, 0, i == "a" and 1 or 2],
                             "unit": "mm"},
                "axis": [1.0, 0.0, 0.0]}}
        component = {"id": "c", "parameters": [], "features": [
            {"id": "body", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 25.0, "unit": "mm"},
                "height": {"magnitude": 15.0, "unit": "mm"}}},
            hole("a"), hole("b"), hole("c")]}
        record = RequirementSet(requirements=({
            "id": "R", "measurement": "holes_of_diameter:4",
            "comparison": "equals",
            "threshold": {"magnitude": 2, "unit": ""}},),
            assumptions=(), unknowns=())
        self.assertEqual(
            _holes_sized_as_the_record_counts(component, record), [])


class TheSpacerThatDeclaredNothing(unittest.TestCase):
    """Every dimension written as a name and not one declared; the plate's
    4 mm under three names (`plate_thickness`, `base_thickness`, and the
    record's `base_height`); the 5 mm hole drawn twice, sideways, from both
    ends. The same answer twice, and the run ended with no part."""

    def test_it_now_builds_the_spacer(self) -> None:
        draft = _design(_load("spacer_with_nothing_declared"))
        component = draft.payload["components"][0]
        base = next(f for f in component["features"] if f["id"] == "base")
        self.assertEqual(base["parameters"]["size"]["vector"],
                         ["base_width", "base_width", "base_height"])
        holes = [f for f in component["features"] if f["kind"] == "hole"]
        self.assertEqual(len(holes), 3)
        centre = next(h for h in holes if h["id"] == "hole_1")
        self.assertEqual(centre["parameters"]["axis"], [0.0, 0.0, 1.0])
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})

    def test_a_name_is_matched_by_what_stands_beside_the_figure(self) -> None:
        """`plate_thickness` is the 4 mm ("plate 4 mm thick"), not the post's
        10 mm, although the post's sentence also mentions the plate."""
        from forge_roles.library import RequirementSet, _a_name_the_brief_sizes

        def claim(name, figure):
            return {"id": name, "measurement": f"parameter:{name}",
                    "comparison": "equals",
                    "threshold": {"magnitude": figure, "unit": "mm"}}
        component = {"id": "c", "parameters": [], "features": [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, "plate_thickness"],
                         "unit": "mm"}}}]}
        notes = _a_name_the_brief_sizes(
            component, RequirementSet(requirements=(
                claim("base_height", 4.0), claim("post_height", 10.0)),
                assumptions=(), unknowns=()),
            "The base is a 30 mm square plate 4 mm thick. A 12 mm post 10 mm "
            "tall stands on it, filleted where the post meets the plate.")
        self.assertTrue(notes)
        self.assertEqual(
            component["features"][0]["parameters"]["size"]["vector"][2],
            "base_height")

    def test_a_cross_hole_through_a_shaft_stays_across(self) -> None:
        from forge_roles.library import _a_hole_through_the_post_runs_down_it

        component = {"id": "c", "parameters": [], "features": [
            {"id": "shaft", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 12.0, "unit": "mm"},
                "height": {"magnitude": 100.0, "unit": "mm"}}},
            {"id": "x", "kind": "hole", "inputs": ["shaft"], "parameters": {
                "diameter": {"magnitude": 3.0, "unit": "mm"},
                "position": {"vector": [0, 0, 10], "unit": "mm"},
                "axis": [1.0, 0.0, 0.0]}}]}
        self.assertEqual(_a_hole_through_the_post_runs_down_it(
            component, "A 12 mm shaft, 100 mm long, with a 3 mm cross hole "
            "through the shaft 10 mm from one end."), [])
        self.assertEqual(component["features"][1]["parameters"]["axis"],
                         [1.0, 0.0, 0.0])


class TheFirstCollarToPassTruly(unittest.TestCase):
    def test_it_is_the_collar(self) -> None:
        report = _verify(_design(_load("collar_first_true_pass")))
        self.assertEqual(_not_passing(report), {})
        holes = sorted(h["diameter_mm"] for h in
                       report.measurements["part"]["holes"])
        self.assertEqual(holes, [4.0, 4.0, 12.0])
        self.assertEqual(_openings_round_the_outside(report.part.solid), 2)


class AHoleTheRecordCountsOnceIsOneHole(unittest.TestCase):
    """The 5 mm hole written twice, identical, pointing the same way, where
    the record counts one. Sent back twice with "these are the same hole",
    the same answer twice, no part."""

    def test_the_copy_goes_and_the_spacer_builds(self) -> None:
        draft = _design(_load("spacer_hole_written_twice"))
        ids = [f["id"] for f in draft.payload["components"][0]["features"]]
        self.assertIn("hole_1", ids)
        self.assertNotIn("hole_2", ids)
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})

    def test_without_a_count_the_copy_is_still_reported(self) -> None:
        """Two copies pointing the same way may be two holes the design meant
        to put apart. With no count to settle it, the model is told."""
        from forge_roles.library import RequirementSet, _one_hole_written_twice

        def hole(i):
            return {"id": i, "kind": "hole", "inputs": ["body"], "parameters": {
                "diameter": {"magnitude": 3.0, "unit": "mm"},
                "position": {"vector": [0, 0, 0], "unit": "mm"},
                "axis": [0.0, 0.0, 1.0]}}
        component = {"id": "c", "parameters": [], "features": [
            {"id": "body", "kind": "box", "parameters": {}},
            hole("a"), hole("b")]}
        self.assertEqual(_one_hole_written_twice(
            component, RequirementSet(requirements=(), assumptions=(),
                                      unknowns=())), [])
        self.assertEqual(len(component["features"]), 3)
        # And where the record counts TWO of them, they are two holes.
        self.assertEqual(_one_hole_written_twice(
            component, RequirementSet(requirements=({
                "id": "R", "measurement": "holes_of_diameter:3",
                "comparison": "equals",
                "threshold": {"magnitude": 2, "unit": ""}},),
                assumptions=(), unknowns=())), [])


class ARepairedBindingIsReadRepaired(unittest.TestCase):
    """A correct collar, blocked as NOT_TESTED over Forge's own ordering.

    The model counted `feature_count:set_screw_hole:mounting`. Forge built
    its angle claim from that count before correcting it, so the angle came
    out as `angle_between:set_screw_hole:mounting` -- no such feature kind --
    and was unbound, while the count was corrected a moment later. The part
    was right; the report could not say so.
    """

    def test_the_angle_is_built_from_the_corrected_count(self) -> None:
        record = _requirements(_load("collar_count_named_by_its_own_word"))
        bindings = {r["id"]: r.get("measurement") for r in record.requirements}
        self.assertEqual(bindings["REQ_ANGLE"], "angle_between:hole:set_screw")
        self.assertEqual(bindings["REQ_MOUNTING_SET_SCREW_HOLE_COUNT"],
                         "feature_count:hole:set_screw")

    def test_and_the_collar_passes_every_claim(self) -> None:
        report = _verify(_design(_load("collar_count_named_by_its_own_word")))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        angle = next(r for r in report.gate_results
                     if r.gate.identifier == "REQ_ANGLE")
        self.assertAlmostEqual(
            angle.evidence.result.to("deg").magnitude.midpoint, 90.0, places=6)

    def test_an_angle_names_a_kind_the_same_way(self) -> None:
        from forge_roles.library import _repairable_binding

        repaired, _ = _repairable_binding("angle_between:set_screw_hole:x")
        self.assertEqual(repaired, "angle_between:hole:set_screw")
        repaired, _ = _repairable_binding("angle_between:screws:set_screw")
        self.assertEqual(repaired, "angle_between:hole:set_screw")


    def test_an_angle_claim_with_no_binding_is_bound(self) -> None:
        """The run's own record, re-read: REQ_ANGLE carried 90 deg and no
        measurement. There is one binding for it."""
        import glob  # noqa: F401 - kept local, as the other helpers are
        from forge_roles.library import _an_angle_the_brief_states_and_nothing_checks

        brief = _load("collar_count_named_by_its_own_word")["brief"]
        claims = [{"id": "REQ_ANGLE", "statement": "90 apart",
                   "comparison": "equals",
                   "threshold": {"magnitude": 90.0, "unit": "deg"}}]
        notes = _an_angle_the_brief_states_and_nothing_checks(brief, claims)
        self.assertTrue(notes)
        self.assertEqual(claims[0]["measurement"], "angle_between:hole:spaced")


class TwoHolesAtOnePointAreSpreadByTheirSpacing(unittest.TestCase):
    """"Two 3 mm mounting holes pass all the way through the plate, 20 mm
    apart." The design drew both at the plate's centre, one drilled along x
    and one along y, and read the spacing nowhere. Told to declare
    `mounting_hole_distance`, it returned the same answer: 17 minutes, no
    part. The parameter was never what was missing; the distance was."""

    CASE = "spacer_mounting_holes_at_one_point"

    def test_it_now_builds_the_spacer(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        holes = {h["feature"]: h for h in report.measurements["part"]["holes"]}
        self.assertTrue(all(h["present"] for h in holes.values()))
        for name, x in (("mounting_hole_1", 10.0), ("mounting_hole_2", -10.0)):
            self.assertAlmostEqual(holes[name]["centre_mm"][0], x, places=6)
            self.assertAlmostEqual(holes[name]["centre_mm"][1], 0.0, places=6)
        features = {f["id"]: f for f in
                    draft.payload["components"][0]["features"]}
        for name in ("mounting_hole_1", "mounting_hole_2", "bore"):
            self.assertEqual(features[name]["parameters"]["axis"],
                             [0.0, 0.0, 1.0])

    def _parse(self, brief: str | None = None, mutate=None):
        from forge_roles import ForgeIRDesigner
        from forge_roles.base import RoleOutputError

        case = _load(self.CASE)
        if mutate:
            mutate(case["answer"]["document"]["components"][0])
        try:
            ForgeIRDesigner().parse(
                case["answer"], requirements=_requirements(case),
                intent=_intent(case), brief=brief or case["brief"],
                document_id="", project_id="", answers={})
        except RoleOutputError as error:
            return list(error.problems)
        return []

    def test_diagonally_is_a_choice_and_is_reported_with_positions(
        self,
    ) -> None:
        brief = _load(self.CASE)["brief"].replace(
            "20 mm apart", "20 mm apart diagonally")
        problems = " ".join(self._parse(brief))
        self.assertIn("`mounting_hole_1` and `mounting_hole_2` are both drawn "
                      "at (0, 0, base_height / 2)", problems)
        self.assertIn("`mounting_hole_distance / 2`", problems)

    def test_an_oblong_plate_is_a_choice(self) -> None:
        def oblong(component):
            component["features"][0]["parameters"]["size"]["vector"][0] = (
                "base_width * 4 / 3")
        problems = " ".join(self._parse(mutate=oblong))
        self.assertIn("are both drawn at", problems)

    def test_an_off_centre_post_is_a_choice(self) -> None:
        def off_centre(component):
            component["features"][1]["parameters"]["origin"]["vector"][1] = 3
        problems = " ".join(self._parse(mutate=off_centre))
        self.assertIn("are both drawn at", problems)


class AHoleThroughAPlateRunsThroughItsThickness(unittest.TestCase):
    """The re-aim acts on "through the plate" and nothing that puts the hole
    edgeways."""

    @staticmethod
    def _component(axis):
        return {"id": "c", "parameters": [], "features": [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"},
                "centered": True}},
            {"id": "h", "kind": "hole", "inputs": ["base"], "parameters": {
                "diameter": {"magnitude": 3.0, "unit": "mm"},
                "position": {"vector": [10, 0, 0], "unit": "mm"},
                "axis": axis}}]}

    def _aim(self, brief, axis=None):
        from forge_roles.library import (
            _a_hole_through_the_plate_runs_through_its_thickness)

        component = self._component(axis or [1.0, 0.0, 0.0])
        notes = _a_hole_through_the_plate_runs_through_its_thickness(
            component, brief)
        return notes, component["features"][1]["parameters"]["axis"]

    def test_through_the_plate_is_through_its_thickness(self) -> None:
        notes, axis = self._aim("A plate. A 3 mm hole through the plate.")
        self.assertTrue(notes)
        self.assertEqual(axis, [0.0, 0.0, 1.0])

    def test_through_its_edge_is_left_alone(self) -> None:
        for brief in ("A 3 mm hole through the edge of the plate.",
                      "A 3 mm hole drilled across the plate.",
                      "A 3 mm hole through the plate, sideways."):
            notes, axis = self._aim(brief)
            self.assertEqual(notes, [], brief)
            self.assertEqual(axis, [1.0, 0.0, 0.0], brief)

    def test_a_hole_of_another_size_is_left_alone(self) -> None:
        notes, _ = self._aim("A 4 mm hole through the plate.")
        self.assertEqual(notes, [])

    def test_a_decimal_size_is_one_sentence(self) -> None:
        from forge_roles.library import _sentences_of

        self.assertEqual(
            _sentences_of("A 2.5 mm hole runs through the post. Then 3."),
            ["a 2.5 mm hole runs through the post", "then 3"])


class TheCollarThatDeclaredNothing(unittest.TestCase):
    """No parameter declared, no bore drawn, the set screws drilled straight
    across, and the bore port written on the body -- `body.bore`, which a
    cylinder does not have. Returned identically twice: 710 s, no part.

    Every piece of it had a repair already, and none of them fired: each
    resolves the body's size from declared parameters, the design declared
    none, so each read the body as unknown and declined."""

    CASE = "collar_nothing_declared_and_no_bore"

    def test_it_now_builds_the_collar(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        self.assertEqual(report.measurements["part"]["open_holes"], 3)
        component = draft.payload["components"][0]
        features = {f["id"]: f for f in component["features"]}
        self.assertEqual(features["bore"]["parameters"]["axis"],
                         [0.0, 0.0, 1.0])
        for name in ("set_screw_hole_1", "set_screw_hole_2"):
            self.assertIn("depth", features[name]["parameters"])
        self.assertEqual(component["interfaces"][0]["geometry"], "bore.bore")


class ADesignThatDeclaresNothingIsTheSameDesign(unittest.TestCase):
    """The root cause behind the collar above, checked across the answers.

    A name the record measures, used by the features and not declared, is a
    missing line with a known value. Leaving it out must not change the part
    Forge builds -- every repair has to see the same sizes either way."""

    PASSING = (
        "collar_correct", "collar_without_its_bore",
        "collar_with_its_screws_at_the_bores_size", "spacer_correct",
        "spacer_released_as_a_bar", "spacer_first_live_pass",
        "spacer_mounting_holes_at_one_point", "flange_without_its_bolt_holes",
        "spacer_holes_spread_through_the_thickness",
        "plate_holes_on_a_rectangle_drawn_as_a_solid",
        "flange_bolt_circle_never_placed",
        "flange_two_names_and_holes_on_the_axis",
        "hub_floating_on_its_flange_and_unwired",
        "collar_drawn_as_one_cylinder",
        "open_top_box_drawn_as_a_plate",
        "open_top_box_cut_through_the_middle",
        "l_bracket_upright_lying_flat",
        "l_bracket_both_plates_standing",
        "l_bracket_holes_cut_before_the_union",
        "hub_floating_above_a_centre_written_flange",
        "plate_rectangle_bound_as_spacing_and_depth",
        "plate_rectangle_drawn_as_a_slab_with_a_port",
        "spacer_one_bore_written_as_two_holes",
    )

    def test_each_answer_builds_the_same_without_its_declarations(
        self,
    ) -> None:
        for name in self.PASSING:
            with self.subTest(name=name):
                case = _load(name)
                measured = {
                    str(r.get("measurement", "")).partition(":")[2]
                    for r in case["requirements"]["requirements"]
                    if str(r.get("measurement", "")).startswith("parameter:")
                }
                document = case["answer"].get("document") or case["answer"]
                component = document["components"][0]
                component["parameters"] = [
                    p for p in component.get("parameters") or []
                    if p.get("id") not in measured]
                report = _verify(_design(case))
                self.assertEqual(_not_passing(report), {})
                self.assertEqual(report.overall_status.value, "PASS")


class ARepairedDesignIsLeftAsItIs(unittest.TestCase):
    """Every repair, run again on what it produced, changes nothing.

    The released pulley hub, parsed again, was refused: the bolt-circle
    repair had placed the holes at `hole_spacing / 2`, and on the second
    pass `hole_spacing` -- now read by the holes -- no longer counted as the
    circle, so the holes were rewritten in plain millimetres and the
    parameter was left reading nothing. A repair that does not recognise its
    own work undoes it."""

    def test_each_answer_settles_once(self) -> None:
        from forge_roles import ForgeIRDesigner

        for name in ADesignThatDeclaresNothingIsTheSameDesign.PASSING:
            with self.subTest(name=name):
                case = _load(name)
                first = _design(case)
                again = ForgeIRDesigner().parse(
                    {"rationale": "x", "document": first.payload},
                    requirements=_requirements(case), intent=_intent(case),
                    brief=case["brief"], document_id="", project_id="",
                    answers={})
                self.assertEqual(
                    again.payload["components"][0]["features"],
                    first.payload["components"][0]["features"])


class ADesignWrittenInNumbersIsTheSameDesign(unittest.TestCase):
    """The other half of the same root cause: every size the record measures
    written out as a number instead of a name.

    Before, a collar written that way was refused -- and the refusal was
    Forge's own doing: the set screws were given a `depth` of the body's
    diameter, copied as the number 25, and that second 25 made the body's
    own 25 no longer the one place `outer_diameter` could go."""

    PASSING = ADesignThatDeclaresNothingIsTheSameDesign.PASSING + (
        "collar_nothing_declared_and_no_bore", "collar_first_true_pass",
        "spacer_with_nothing_declared",
    )

    @staticmethod
    def _in_numbers(case: dict) -> None:
        figures = {
            str(r["measurement"]).partition(":")[2]: float(
                r["threshold"]["magnitude"])
            for r in case["requirements"]["requirements"]
            if str(r.get("measurement", "")).startswith("parameter:")
            and (r.get("threshold") or {}).get("unit") == "mm"
        }

        def walk(value):
            if isinstance(value, dict):
                if value.get("expression") in figures:
                    value["magnitude"] = figures[value.pop("expression")]
                    value.setdefault("unit", "mm")
                for inner in value.values():
                    walk(inner)
            elif isinstance(value, list):
                for i, inner in enumerate(value):
                    if isinstance(inner, str) and inner in figures:
                        value[i] = figures[inner]
                    else:
                        walk(inner)

        document = case["answer"].get("document") or case["answer"]
        component = document["components"][0]
        walk(component["features"])
        component["parameters"] = [
            p for p in component.get("parameters") or []
            if p.get("id") not in figures]

    def test_each_answer_builds_the_same_in_numbers(self) -> None:
        for name in self.PASSING:
            with self.subTest(name=name):
                case = _load(name)
                self._in_numbers(case)
                report = _verify(_design(case))
                self.assertEqual(_not_passing(report), {})
                self.assertEqual(report.overall_status.value, "PASS")


class ANumberWrittenMoreThanOnce(unittest.TestCase):
    """Several fields holding a measured figure are linked only when they are
    plainly one dimension written more than once."""

    @staticmethod
    def _link(features, name, figure):
        from forge_roles.library import (
            RequirementSet, _declare_what_the_requirements_measure)

        payload = {"components": [{"id": "c", "parameters": [],
                                   "features": features}]}
        notes = _declare_what_the_requirements_measure(
            payload, RequirementSet(requirements=({
                "id": "R", "measurement": f"parameter:{name}",
                "comparison": "equals",
                "threshold": {"magnitude": figure, "unit": "mm"}},),
                assumptions=(), unknowns=()))
        return notes, payload["components"][0]["features"]

    @staticmethod
    def _hole(i, size, **more):
        return {"id": i, "kind": "hole", "parameters": {
            "diameter": {"magnitude": size, "unit": "mm"}, **more}}

    def test_the_holes_the_name_points_at(self) -> None:
        notes, features = self._link([
            self._hole("mounting_hole_1", 3.0), self._hole("mounting_hole_2", 3.0),
        ], "mounting_hole_diameter", 3.0)
        self.assertTrue(notes)
        for f in features:
            self.assertEqual(f["parameters"]["diameter"],
                             {"expression": "mounting_hole_diameter"})

    def test_not_the_hole_it_does_not_point_at(self) -> None:
        notes, features = self._link([
            self._hole("mounting_hole_1", 3.0), self._hole("mounting_hole_2", 3.0),
            self._hole("bore", 3.0),
        ], "mounting_hole_diameter", 3.0)
        self.assertTrue(notes)
        self.assertEqual(features[2]["parameters"]["diameter"],
                         {"magnitude": 3.0, "unit": "mm"})

    def test_a_width_is_never_a_depth(self) -> None:
        notes, features = self._link([
            {"id": "body", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 25.0, "unit": "mm"},
                "height": {"magnitude": 15.0, "unit": "mm"}}},
            self._hole("s", 4.0, depth={"magnitude": 25.0, "unit": "mm"}),
        ], "outer_diameter", 25.0)
        self.assertTrue(notes)
        self.assertEqual(features[0]["parameters"]["diameter"],
                         {"expression": "outer_diameter"})
        self.assertEqual(features[1]["parameters"]["depth"],
                         {"magnitude": 25.0, "unit": "mm"})

    def test_a_plate_s_sides(self) -> None:
        notes, features = self._link([
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"}}},
        ], "base_width", 30.0)
        self.assertTrue(notes)
        self.assertEqual(features[0]["parameters"]["size"]["vector"],
                         ["base_width", "base_width", 4])

    def test_two_unrelated_features_are_still_a_judgement(self) -> None:
        notes, features = self._link([
            self._hole("a", 3.0), self._hole("b", 3.0),
        ], "mounting_hole_diameter", 3.0)
        self.assertEqual(notes, [])


class AnInterfaceOnAFaceItsOwnerLacks(unittest.TestCase):
    """Re-pointed only where one face on the part can be meant."""

    @staticmethod
    def _component(sizes, nominal=12.0):
        features = [{"id": "body", "kind": "cylinder", "parameters": {
            "diameter": {"magnitude": 25.0, "unit": "mm"},
            "height": {"magnitude": 15.0, "unit": "mm"}}}]
        for i, size in enumerate(sizes):
            features.append({"id": f"h{i}", "kind": "hole", "parameters": {
                "diameter": {"magnitude": size, "unit": "mm"}}})
        interface = {"id": "bore", "type": "bore", "geometry": "body.bore"}
        if nominal is not None:
            interface["nominal_size"] = {"magnitude": nominal, "unit": "mm"}
        return {"id": "c", "parameters": [], "features": features,
                "interfaces": [interface]}

    def _geometry(self, component):
        from forge_roles.library import _an_interface_on_a_face_its_owner_lacks

        _an_interface_on_a_face_its_owner_lacks(component)
        return component["interfaces"][0]["geometry"]

    def test_the_one_face_of_its_size(self) -> None:
        self.assertEqual(self._geometry(self._component([4.0, 12.0, 4.0])),
                         "h1.bore")

    def test_the_only_face_of_that_name(self) -> None:
        self.assertEqual(self._geometry(self._component([12.0], None)),
                         "h0.bore")

    def test_two_of_its_size_is_a_choice(self) -> None:
        self.assertEqual(self._geometry(self._component([12.0, 12.0])),
                         "body.bore")

    def test_none_of_its_size_is_left_for_the_designer(self) -> None:
        self.assertEqual(self._geometry(self._component([4.0, 5.0])),
                         "body.bore")

    def test_a_stated_size_is_never_put_on_another(self) -> None:
        self.assertEqual(self._geometry(self._component([4.0])), "body.bore")

    def test_several_and_no_size_is_a_choice(self) -> None:
        self.assertEqual(self._geometry(self._component([4.0, 12.0], None)),
                         "body.bore")


class TheOblongSpacerBlockedOnWhatTheBriefSaid(unittest.TestCase):
    """A correct spacer, blocked, over three things the brief had settled.

    - `ASM_DESIGN_LOAD`: "The 300 N acts downwards at the shaft axis,
      statically" -- the prompt's worked example, copied whole, on a brief
      that said it carries no load. No load word in it, so it survived.
    - `UNKNOWN_WEIGHT`: "What is the weight of the spacer block?" -- asked of
      the user, about the part, on a brief that said "no more than 10 g".
      And the 10 g was never checked: Forge looked for the figure by its
      digits and found the "10" of "a 10 mm diameter post" first.
    - "Two 3 mm mounting holes" recorded as at least two, which the design's
      three `mounting`-tagged holes -- the bore among them -- satisfied.
    """

    CASE = "spacer_blocked_by_a_copied_load"

    def test_the_record_holds_what_the_brief_said(self) -> None:
        record = _requirements(_load(self.CASE))
        self.assertEqual(list(record.assumptions), [])
        self.assertEqual(list(record.unknowns), [])
        claims = {r["id"]: r for r in record.requirements}
        self.assertEqual(claims["REQ_MASS"]["comparison"], "at_most")
        self.assertEqual(claims["REQ_MASS"]["threshold"],
                         {"magnitude": 10.0, "unit": "g"})
        self.assertEqual(claims["REQ_MOUNTING_HOLE_COUNT"]["comparison"],
                         "equals")

    def test_and_the_spacer_is_released(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        tags = {f["id"]: f.get("tags") for f in
                draft.payload["components"][0]["features"]}
        self.assertFalse(tags["hole"])

    def test_a_load_is_known_by_its_figure(self) -> None:
        from forge_roles.library import _about_a_load

        self.assertTrue(_about_a_load(
            {"statement": "The 300 N acts downwards, statically."},
            "statement"))
        self.assertTrue(_about_a_load(
            {"id": "ASM_DESIGN_LOAD", "statement": "It acts statically."},
            "statement"))
        self.assertFalse(_about_a_load(
            {"statement": "Screws are tightened to 2 N m."}, "statement"))
        self.assertFalse(_about_a_load(
            {"statement": "The part is printed in PLA."}, "statement"))

    def test_a_count_with_a_bound_stays_a_bound(self) -> None:
        from forge_roles.library import _a_count_the_brief_states_exactly

        claims = [{"id": "R", "measurement": "feature_count:hole:mounting",
                   "comparison": "at_least",
                   "threshold": {"magnitude": 2, "unit": ""}}]
        _a_count_the_brief_states_exactly(
            "A plate. At least two mounting holes pass through it.", claims)
        self.assertEqual(claims[0]["comparison"], "at_least")
        _a_count_the_brief_states_exactly(
            "A plate. Two mounting holes pass through it.", claims)
        self.assertEqual(claims[0]["comparison"], "equals")


class TwoHolesSpreadDownTheirOwnAxis(unittest.TestCase):
    """The oblong spacer's rerun: the mounting holes drilled along x and
    spread apart by `mounting_hole_distance` along z -- 15 mm above and below
    a 5 mm plate, cutting nothing. Once they are drilled through the plate
    they are one line with the bore. Sent back twice as "the same hole",
    returned identically, no part.

    The spacing was written, only on the wrong axis. Across the part, 30 mm
    fits along the 40 mm length and not across the 25 mm width."""

    CASE = "spacer_holes_spread_through_the_thickness"

    def test_it_now_builds_the_spacer(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        holes = {h["feature"]: h for h in report.measurements["part"]["holes"]}
        self.assertTrue(all(h["present"] for h in holes.values()))
        self.assertEqual(sorted(round(holes[n]["centre_mm"][0], 6) for n in (
            "mounting_hole_1", "mounting_hole_2")), [-15.0, 15.0])
        features = {f["id"]: f for f in
                    draft.payload["components"][0]["features"]}
        for name in ("mounting_hole_1", "mounting_hole_2"):
            self.assertEqual(features[name]["parameters"]["axis"],
                             [0.0, 0.0, 1.0])


class AMaterialNamedByItsFamily(unittest.TestCase):
    """"A stainless steel shaft collar" came out with no material: the word
    "steel" named the carbon steel too, and two candidates meant none. A
    name inside a longer name of another grade is not a mention of its own.
    """

    def _material(self, said: str):
        from forge_roles.library import Intent, _name_the_material_the_brief_names

        payload = {"components": [{"id": "c"}]}
        _name_the_material_the_brief_names(payload, Intent(
            summary=said, part_kind="", stated=(), implied=(), unstated=()),
            None)
        return payload["components"][0].get("material")

    def test_each_family_names_its_grade(self) -> None:
        self.assertEqual(self._material("A stainless steel shaft collar"),
                         "stainless_304")
        self.assertEqual(self._material("A steel flange disc"), "steel_1018_cd")
        self.assertEqual(self._material("A machined aluminium collar"),
                         "aluminium_6061_t6")
        self.assertEqual(self._material("An aluminum plate"),
                         "aluminium_6061_t6")
        self.assertEqual(self._material("A 3D-printed PLA spacer"), "pla_fdm")

    def test_two_materials_is_still_a_question(self) -> None:
        self.assertIsNone(self._material("A steel and aluminium assembly"))
        self.assertIsNone(self._material("A plastic part"))


class TheFlangeWithoutItsBoltHoles(unittest.TestCase):
    """"Two 6 mm bolt holes pass all the way through the disc, 40 mm apart."
    Three designer attempts, each told the bolt-hole parameters drove
    nothing; none drew a bolt hole. The run built a disc with a bore, failed
    two gates, and the failure analyst's patch -- one hole, diameter `"6"`,
    at the bore's own position -- was refused raw."""

    CASE = "flange_without_its_bolt_holes"

    def test_it_now_builds_the_flange(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        holes = {h["feature"]: h for h in report.measurements["part"]["holes"]}
        self.assertEqual(len(holes), 3)
        self.assertTrue(all(h["present"] for h in holes.values()))
        bolts = sorted(h["centre_mm"][0] for n, h in holes.items()
                       if abs(h["diameter_mm"] - 6.0) < 1e-9)
        self.assertEqual([round(x, 6) for x in bolts], [-20.0, 20.0])
        for feature in draft.payload["components"][0]["features"]:
            if feature["kind"] == "hole" and feature["id"] != "bore":
                self.assertEqual(feature["parameters"]["axis"], [0.0, 0.0, 1.0])
                self.assertEqual(feature["parameters"]["diameter"],
                                 {"expression": "bolt_hole_diameter",
                                  "unit": "mm"})

    def test_where_to_put_them_is_still_a_choice_on_an_oblong_plate(
        self,
    ) -> None:
        """A 60 by 58 plate holds two holes 40 mm apart either way; nothing is
        added, and the designer is told."""
        from forge_roles.library import (
            RequirementSet, _a_pair_of_holes_the_design_left_out)

        component = {"id": "c", "parameters": [], "features": [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [60, 58, 6], "unit": "mm"},
                "centered": True}}]}
        record = RequirementSet(requirements=(
            {"id": "S", "measurement": "parameter:hole_spacing",
             "comparison": "equals",
             "threshold": {"magnitude": 40.0, "unit": "mm"}},
            {"id": "N", "measurement": "holes_of_diameter:6",
             "comparison": "equals",
             "threshold": {"magnitude": 2, "unit": ""}}),
            assumptions=(), unknowns=())
        brief = "A plate. Two 6 mm holes pass through the plate, 40 mm apart."
        self.assertEqual(
            _a_pair_of_holes_the_design_left_out(component, record, brief), [])
        self.assertEqual(len(component["features"]), 1)
        # And where only one way fits, they are drilled.
        component["features"][0]["parameters"]["size"]["vector"] = [60, 30, 6]
        self.assertTrue(
            _a_pair_of_holes_the_design_left_out(component, record, brief))
        self.assertEqual(len(component["features"]), 3)

    def test_an_analyst_patch_is_settled_like_a_designer_answer(self) -> None:
        import copy

        from forge_orchestrator.orchestrator import Orchestrator
        from forge_orchestrator.run import DesignRun
        from forge_roles import ForgeIRDesigner

        case = _load(self.CASE)
        payload = copy.deepcopy(case["answer"]["document"])
        payload["requirements"] = case["requirements"]["requirements"]
        payload["components"][0]["features"].append(case["analyst_patch"])
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator._roles = {"designer": ForgeIRDesigner()}
        run = DesignRun(case["brief"])
        run.intent = _intent(case)
        settled = orchestrator._settle(run, payload)
        added = next(f for f in settled["components"][0]["features"]
                     if f["id"] == "hole_2")
        # `"6"`, a dimensionless expression, is 6 mm now.
        self.assertEqual(added["parameters"]["diameter"],
                         {"unit": "mm", "magnitude": 6.0})
        self.assertTrue(any("hole_2" in e.summary for e in run.events))


class TheSpacerWhoseMountingHolesWereNeverDrawn(unittest.TestCase):
    """An old failure, now built: the 5 mm hole drawn twice and both copies
    tagged `mounting`, no 3 mm hole anywhere, and `mounting_hole_diameter`
    and `mounting_hole_distance` each defined as itself. Four repairs in one
    answer: the self-definitions take the record's figures, the two missing
    holes are drilled and spread, the extra copy goes, and the tag moves to
    the holes that are the mounting holes."""

    def test_it_is_the_spacer(self) -> None:
        report = _verify(_design(_load("spacer_mounting_holes_never_drawn")))
        self.assertEqual(_not_passing(report), {})
        holes = {h["feature"]: h for h in report.measurements["part"]["holes"]}
        self.assertEqual(sorted(round(h["diameter_mm"], 6)
                                for h in holes.values()), [3.0, 3.0, 5.0])
        self.assertTrue(all(h["present"] for h in holes.values()))


class ARectangleOfHoleCentresIsWhereTheHolesGo(unittest.TestCase):
    """"Four 4 mm holes pass through the plate, one near each corner, with
    their centres on a 56 mm by 36 mm rectangle." The record named the two
    figures `rectangle_length` and `rectangle_width`; the designer built a
    rectangle -- a 56 mm cylinder 36 mm tall on the plate's corner, welded
    on -- and drew the holes at the plate's own corners, where they cut
    nothing. The analyst then proposed removing features 0 to 63 of a
    7-feature document, twice."""

    CASE = "plate_holes_on_a_rectangle_drawn_as_a_solid"

    def test_the_record_names_the_figures_as_hole_spacings(self) -> None:
        record = _requirements(_load(self.CASE))
        bindings = {r["id"]: r["measurement"] for r in record.requirements}
        self.assertEqual(bindings["REQ_RECTANGLE_LENGTH"],
                         "parameter:hole_centres_length")
        self.assertEqual(bindings["REQ_RECTANGLE_WIDTH"],
                         "parameter:hole_centres_width")

    def test_it_now_builds_the_plate(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        ids = [f["id"] for f in draft.payload["components"][0]["features"]]
        self.assertNotIn("rectangle", ids)
        holes = report.measurements["part"]["holes"]
        self.assertEqual(sorted((round(h["centre_mm"][0], 6),
                                 round(h["centre_mm"][1], 6)) for h in holes),
                         [(-28.0, -18.0), (-28.0, 18.0),
                          (28.0, -18.0), (28.0, 18.0)])
        self.assertTrue(all(h["present"] for h in holes))
        envelope = report.measurements["part"]["envelope_mm"]
        self.assertLess(abs(envelope[2] - 4.0), 0.2)  # measured at depth 6

    def test_an_analyst_patch_naming_nothing_is_refused_with_why(
        self,
    ) -> None:
        from forge_roles.base import RoleOutputError
        from forge_roles.library import FailureAnalyst

        case = _load(self.CASE)
        component = case["answer"]["document"]["components"][0]
        with self.assertRaises(RoleOutputError) as caught:
            FailureAnalyst().parse(
                {"diagnosis": "d", "strategy": "s",
                 "patches": case["analyst_patches"]},
                document_slice={"/components/0": component})
        problems = caught.exception.problems
        self.assertLessEqual(len(problems), 4)
        self.assertIn("numbered 0 to", problems[0])
        # And an edit that names what is there is not.
        FailureAnalyst().parse(
            {"diagnosis": "d", "strategy": "s", "patches": [
                {"op": "remove", "pointer": "/components/0/features/1"}]},
            document_slice={"/components/0": component})


class HolesEquallySpacedOnABoltCircle(unittest.TestCase):
    """"Four 8 mm bolt holes pass all the way through the disc, equally
    spaced on a 60 mm bolt circle." The record dropped the 60 mm ("not
    checked against 60 mm"); the design drew no bore, two bolt holes at the
    disc's centre and two 60 mm off its axis -- outside an 80 mm disc -- all
    drilled sideways. The same answer twice, no part."""

    CASE = "flange_bolt_circle_never_placed"

    def test_the_record_carries_the_circle(self) -> None:
        record = _requirements(_load(self.CASE))
        claims = {r["id"]: r for r in record.requirements}
        self.assertEqual(claims["REQ_BOLT_CIRCLE_DIAMETER"]["measurement"],
                         "parameter:bolt_circle_diameter")
        self.assertEqual(claims["REQ_BOLT_CIRCLE_DIAMETER"]["threshold"],
                         {"magnitude": 60.0, "unit": "mm"})

    def test_it_now_builds_the_flange(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        holes = report.measurements["part"]["holes"]
        self.assertTrue(all(h["present"] for h in holes))
        bolts = sorted((round(h["centre_mm"][0], 6), round(h["centre_mm"][1], 6))
                       for h in holes if abs(h["diameter_mm"] - 8.0) < 1e-9)
        self.assertEqual(bolts, [(-30.0, 0.0), (0.0, -30.0),
                                 (0.0, 30.0), (30.0, 0.0)])
        bore = [h for h in holes if abs(h["diameter_mm"] - 30.0) < 1e-9]
        self.assertEqual(len(bore), 1)

    def test_the_circle_in_the_next_sentence_is_read(self) -> None:
        from forge_roles.library import _the_hole_circle_the_brief_states

        circle = _the_hole_circle_the_brief_states(
            "A disc. Three 5 mm holes pass through it. They are equally "
            "spaced on a 40 mm pitch circle.")
        self.assertEqual((circle["count"], circle["diameter"],
                          circle["circle"]), (3, 5.0, 40.0))
        self.assertIsNone(_the_hole_circle_the_brief_states(
            "A disc. Three 5 mm holes on a 40 mm circle."))  # not equally

    def test_three_holes_on_a_disc_are_120_degrees_apart(self) -> None:
        from forge_roles.library import RequirementSet, _holes_on_a_bolt_circle

        component = {"id": "c", "parameters": [], "features": [
            {"id": "disc", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 60, "unit": "mm"},
                "height": {"magnitude": 6, "unit": "mm"}}}]}
        record = RequirementSet(requirements=({
            "id": "C", "measurement": "parameter:bolt_circle_diameter",
            "comparison": "equals",
            "threshold": {"magnitude": 40.0, "unit": "mm"}},),
            assumptions=(), unknowns=())
        notes = _holes_on_a_bolt_circle(
            component, record, "A disc. Three 5 mm holes pass through it, "
            "equally spaced on a 40 mm bolt circle.")
        self.assertTrue(notes)
        holes = [f for f in component["features"] if f["kind"] == "hole"]
        self.assertEqual(len(holes), 3)
        self.assertEqual(holes[1]["parameters"]["position"]["vector"][0],
                         "-0.5 * bolt_circle_diameter / 2")

    def test_a_square_plate_is_a_choice(self) -> None:
        """Turned 45 degrees, four holes on a circle on a square plate are
        another part -- nearer the corners or nearer the edges."""
        from forge_roles.library import RequirementSet, _holes_on_a_bolt_circle

        component = {"id": "c", "parameters": [], "features": [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [80, 80, 6], "unit": "mm"},
                "centered": True}}]}
        record = RequirementSet(requirements=(), assumptions=(), unknowns=())
        self.assertEqual(_holes_on_a_bolt_circle(
            component, record, "A plate. Four 5 mm holes pass through it, "
            "equally spaced on a 50 mm bolt circle."), [])


class TheFlangeWithTwoNamesForItsSizes(unittest.TestCase):
    """The pipe flange again, the bolt circle now in the record. The design
    declared `diameter` and `thickness` and built the disc from
    `outer_diameter` and `length`, declared nowhere; all four bolt holes sat
    on the axis inside the bore. `outer_diameter` was not taken for
    `diameter` because `bore_diameter` looked just as much like the part's
    own diameter -- "bore" was read only as a kind of size."""

    CASE = "flange_two_names_and_holes_on_the_axis"

    def test_it_now_builds_the_flange(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        disc = draft.payload["components"][0]["features"][0]["parameters"]
        self.assertEqual(disc["diameter"]["expression"], "diameter")
        self.assertEqual(disc["height"]["expression"], "thickness")
        bolts = sorted((round(h["centre_mm"][0], 6), round(h["centre_mm"][1], 6))
                       for h in report.measurements["part"]["holes"]
                       if abs(h["diameter_mm"] - 8.0) < 1e-9)
        self.assertEqual(bolts, [(-30.0, 0.0), (0.0, -30.0),
                                 (0.0, 30.0), (30.0, 0.0)])

    def test_the_bore_is_never_the_whole_part(self) -> None:
        from forge_roles.library import RequirementSet, _a_name_the_brief_sizes

        def measure(name, figure):
            return {"id": name, "measurement": f"parameter:{name}",
                    "comparison": "equals",
                    "threshold": {"magnitude": figure, "unit": "mm"}}

        component = {"id": "c", "parameters": [], "features": [
            {"id": "disc", "kind": "cylinder", "parameters": {
                "diameter": {"expression": "outer_diameter", "unit": "mm"},
                "height": {"magnitude": 5, "unit": "mm"}}}]}
        record = RequirementSet(requirements=(measure("bore_diameter", 20.0),),
                                assumptions=(), unknowns=())
        self.assertEqual(_a_name_the_brief_sizes(component, record, ""), [])


def _inside(report, points) -> list[bool]:
    import numpy as np

    return [bool(v < 0) for v in report.part.solid(np.array(points, dtype=float))]


class TheHubThatFloatedAboveItsFlange(unittest.TestCase):
    """"A flange disc 50 mm across and 6 mm thick, with a round hub 25 mm
    across and 15 mm tall standing on top of it ... a 10 mm bore runs through
    both ... three 5 mm holes pass through the flange only, equally spaced on
    a 38 mm circle." Returned twice, no part: every origin written as the
    cylinder's centre, the bore and holes naming nothing to cut, two of the
    three holes at the centre drilled sideways, the circle unread. Repaired
    step by step, the hub still floated 4.5 mm above the flange -- and every
    gate passed."""

    CASE = "hub_floating_on_its_flange_and_unwired"

    def test_it_now_builds_the_hub(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        features = {f["id"]: f for f in draft.payload["components"][0]["features"]}
        self.assertEqual(features["flange_disc"]["parameters"]["origin"]["vector"],
                         [0, 0, 0])
        self.assertEqual(features["hub"]["parameters"]["origin"]["vector"],
                         [0, 0, "flange_thickness"])
        self.assertEqual(features["body"]["inputs"], ["flange_disc", "hub"])
        bolts = sorted((round(h["centre_mm"][0], 2), round(h["centre_mm"][1], 2))
                       for h in report.measurements["part"]["holes"]
                       if abs(h["diameter_mm"] - 5.0) < 1e-9)
        self.assertEqual(bolts, [(-9.5, -16.45), (-9.5, 16.45), (19.0, 0.0)])

    def test_the_part_is_where_the_brief_puts_it(self) -> None:
        report = _verify(_design(_load(self.CASE)))
        self.assertEqual(_inside(report, [
            (0, 0, 3), (0, 0, 15),        # the bore, through both
            (19, 0, 3), (-9.5, 16.45, 3),  # two bolt holes
            (15, 0, 10),                  # beside the hub, above the flange
            (0, 0, 21.5),                 # above the hub
        ]), [False] * 6)
        self.assertEqual(_inside(report, [
            (8, 0, 6.2), (8, 0, 20.8),    # the hub, from the flange to 21 mm
            (23, 0, 3), (0, 19, 3),       # the flange, between its holes
        ]), [True] * 4)

    def test_floating_apart_fails_the_part(self) -> None:
        """Without the stacking repairs, the one-piece gate is what says so."""
        from unittest import mock

        with mock.patch("forge_roles.library._cylinders_placed_by_their_centres",
                        return_value=[]), mock.patch(
                "forge_roles.library._pieces_stacked_as_the_brief_says",
                return_value=[]):
            report = _verify(_design(_load(self.CASE)))
        # And the record's height for the stack: 6 and 15, one on the
        # other, is not the height of a hub floating above its flange.
        self.assertEqual(_not_passing(report), {
            "GEOM_ONE_PIECE": "FAIL", "REQ_STACKED_HEIGHT": "FAIL"})

    def test_the_same_hub_written_in_numbers(self) -> None:
        from forge_roles.library import _cylinders_placed_by_their_centres

        component = {"id": "c", "parameters": [], "features": [
            {"id": "flange", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 50, "unit": "mm"},
                "height": {"magnitude": 6, "unit": "mm"},
                "origin": {"vector": [0, 0, 3], "unit": "mm"}}},
            {"id": "hub", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 25, "unit": "mm"},
                "height": {"magnitude": 15, "unit": "mm"},
                "origin": {"vector": [0, 0, 13.5], "unit": "mm"}}}]}
        self.assertTrue(_cylinders_placed_by_their_centres(component))
        self.assertEqual([f["parameters"]["origin"]["vector"][2]
                          for f in component["features"]], [0, 6])

    def test_a_stack_already_in_one_piece_is_left_alone(self) -> None:
        from forge_roles.library import _cylinders_placed_by_their_centres

        component = {"id": "c", "parameters": [
            {"id": "t", "value": {"magnitude": 6, "unit": "mm"}},
            {"id": "h", "value": {"magnitude": 15, "unit": "mm"}}],
            "features": [
            {"id": "flange", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 50, "unit": "mm"},
                "height": {"expression": "t", "unit": "mm"}}},
            {"id": "hub", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 25, "unit": "mm"},
                "height": {"expression": "h", "unit": "mm"},
                "origin": {"vector": [0, 0, "t"], "unit": "mm"}}}]}
        self.assertEqual(_cylinders_placed_by_their_centres(component), [])

    def test_apart_with_no_mark_of_a_centre_is_left_to_the_gate(self) -> None:
        """Two pieces, and nothing says which convention put them there."""
        from forge_roles.library import _cylinders_placed_by_their_centres

        component = {"id": "c", "parameters": [], "features": [
            {"id": "a", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 20, "unit": "mm"},
                "height": {"magnitude": 5, "unit": "mm"}}},
            {"id": "b", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 20, "unit": "mm"},
                "height": {"magnitude": 5, "unit": "mm"},
                "origin": {"vector": [0, 0, 20], "unit": "mm"}}}]}
        self.assertEqual(_cylinders_placed_by_their_centres(component), [])

    def test_one_centre_in_a_stack_is_read_as_one(self) -> None:
        """The flange written by its centre and the hub by its base: as
        written they overlap by 3 mm and the part is 18 mm tall, in one piece,
        with nothing to fail it. Read as its centre, the flange lands on the
        origin's plane and the hub on its top face."""
        from forge_roles.library import _cylinders_placed_by_their_centres

        component = {"id": "c", "parameters": [
            {"id": "t", "value": {"magnitude": 6, "unit": "mm"}},
            {"id": "h", "value": {"magnitude": 15, "unit": "mm"}}],
            "features": [
            {"id": "flange", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 50, "unit": "mm"},
                "height": {"expression": "t", "unit": "mm"},
                "origin": {"vector": [0, 0, "t / 2"], "unit": "mm"}}},
            {"id": "hub", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 25, "unit": "mm"},
                "height": {"expression": "h", "unit": "mm"},
                "origin": {"vector": [0, 0, "t"], "unit": "mm"}}}]}
        notes = _cylinders_placed_by_their_centres(component)
        self.assertIn("run into one another", notes[0])
        self.assertEqual([f["parameters"]["origin"]["vector"][2]
                          for f in component["features"]], [0, "t"])

    def test_a_mark_that_does_not_land_is_left_alone(self) -> None:
        """A post on a plate centred about the origin: `post_height / 2`
        read as a centre puts its base at 0, inside the 4 mm plate and on no
        face of it. That is not a stack, so nothing moves."""
        from forge_roles.library import _cylinders_placed_by_their_centres

        component = {"id": "c", "parameters": [
            {"id": "post_height", "value": {"magnitude": 10, "unit": "mm"}}],
            "features": [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [40, 40, 4], "unit": "mm"},
                "centered": True}},
            {"id": "post", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 10, "unit": "mm"},
                "height": {"expression": "post_height", "unit": "mm"},
                "origin": {"vector": [0, 0, "post_height / 2"],
                           "unit": "mm"}}}]}
        self.assertEqual(_cylinders_placed_by_their_centres(component), [])

    def test_one_of_four_holes_drawn_is_three_left_out(self) -> None:
        from forge_roles.library import RequirementSet, _holes_on_a_bolt_circle

        component = {"id": "c", "parameters": [
            {"id": "pcd_figure", "value": {"magnitude": 40, "unit": "mm"}}],
            "features": [
            {"id": "disc", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 60, "unit": "mm"},
                "height": {"magnitude": 6, "unit": "mm"}}},
            {"id": "h", "kind": "hole", "inputs": ["disc"], "parameters": {
                "diameter": {"magnitude": 5, "unit": "mm"},
                "position": {"vector": [0, 0, 3], "unit": "mm"}}}]}
        record = RequirementSet(requirements=(), assumptions=(), unknowns=())
        notes = _holes_on_a_bolt_circle(
            component, record, "A disc 60 mm across. Four 5 mm holes pass "
            "through it, equally spaced on a 40 mm circle.")
        holes = [f for f in component["features"] if f["kind"] == "hole"]
        self.assertEqual(len(holes), 4, notes)
        self.assertEqual([h["inputs"] for h in holes],
                         [["disc"], ["h"], ["bolt_hole_2"], ["bolt_hole_3"]])
        self.assertEqual(holes[0]["parameters"]["position"]["vector"],
                         ["pcd_figure / 2", 0, 3.0])
        self.assertIn("drew 1 of the 4", notes[0])

    def test_more_holes_than_the_circle_takes_is_a_choice(self) -> None:
        from forge_roles.library import RequirementSet, _holes_on_a_bolt_circle

        component = {"id": "c", "parameters": [], "features": [
            {"id": "disc", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 60, "unit": "mm"},
                "height": {"magnitude": 6, "unit": "mm"}}}] + [
            {"id": f"h{i}", "kind": "hole", "inputs": ["disc"], "parameters": {
                "diameter": {"magnitude": 5, "unit": "mm"},
                "position": {"vector": [0, 0, 3], "unit": "mm"}}}
            for i in range(3)]}
        record = RequirementSet(requirements=(), assumptions=(), unknowns=())
        self.assertEqual(_holes_on_a_bolt_circle(
            component, record, "A disc. Two 5 mm holes pass through it, "
            "equally spaced on a 40 mm circle."), [])


class TheCollarDrawnAsOneCylinder(unittest.TestCase):
    """The collar rerun: one cylinder carrying the `set_screw` tag, nothing
    declared, no bore, no set screws -- the same answer twice. Forge drilled
    the bore and then told the model only that no `hole` carried the tag."""

    CASE = "collar_drawn_as_one_cylinder"

    def test_it_now_builds_the_collar(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        screws = [f for f in draft.payload["components"][0]["features"]
                  if f["id"].startswith("set_screw_hole")]
        self.assertEqual([s["parameters"]["axis"] for s in screws],
                         [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        self.assertTrue(all(s["tags"] == ["set_screw"] for s in screws))
        # One wall each: open at +x and +y, whole at -x and -y.
        self.assertEqual(_inside(report, [
            (11, 0, 7.5), (0, 11, 7.5), (-11, 0, 7.5), (0, -11, 7.5),
            (0, 0, 7.5), (11, 0, 3)]),
            [False, False, True, True, False, True])

    def test_one_grub_screw(self) -> None:
        from forge_roles.library import (
            RequirementSet, _set_screws_the_design_left_out)

        component = self._body()
        notes = _set_screws_the_design_left_out(
            component, RequirementSet(requirements=(), assumptions=(),
                                      unknowns=()),
            "A pulley 30 mm across and 20 mm long with an 8 mm bore. A 3 mm "
            "grub screw hole goes into the bore, halfway along.")
        screws = component["features"][2:]
        self.assertEqual(len(screws), 1, notes)
        self.assertEqual(screws[0]["parameters"]["position"]["vector"],
                         [0, 0, 10.0])
        self.assertEqual(screws[0]["parameters"]["depth"],
                         {"magnitude": 30.0, "unit": "mm"})

    def test_three_equally_spaced(self) -> None:
        from forge_roles.library import (
            RequirementSet, _set_screws_the_design_left_out)

        component = self._body()
        _set_screws_the_design_left_out(
            component, RequirementSet(requirements=(), assumptions=(),
                                      unknowns=()),
            "A hub 30 mm across, 20 mm long, 8 mm bore. Three 3 mm set screw "
            "holes, equally spaced, go into the bore midway along its length.")
        axes = [f["parameters"]["axis"] for f in component["features"][2:]]
        self.assertEqual(len(axes), 3)
        self.assertAlmostEqual(axes[1][0], -0.5)
        self.assertAlmostEqual(axes[2][1], -(3 ** 0.5) / 2)

    def test_what_it_will_not_guess(self) -> None:
        from forge_roles.library import (
            RequirementSet, _set_screws_the_design_left_out)

        record = RequirementSet(requirements=(), assumptions=(), unknowns=())
        for brief in (
            # nowhere along the body
            "Two 3 mm set screw holes into the bore, 90 degrees apart.",
            # through both walls
            "Two 3 mm cross holes right through the part, halfway along, "
            "90 degrees apart.",
            # two, and no angle between them
            "Two 3 mm set screw holes into the bore, halfway along.",
        ):
            with self.subTest(brief=brief):
                component = self._body()
                self.assertEqual(_set_screws_the_design_left_out(
                    component, record, brief), [])
        component = self._body()
        component["features"] = component["features"][:1]  # no bore
        self.assertEqual(_set_screws_the_design_left_out(
            component, record, "A 3 mm set screw hole into the bore, "
            "halfway along."), [])

    def test_the_model_is_told_the_holes_are_missing(self) -> None:
        """Where Forge cannot drill them, it says the holes are missing -- not
        only that no `hole` carries the tag the cylinder already carried."""
        from forge_roles.base import RoleOutputError

        case = _load(self.CASE)
        case["brief"] = case["brief"].replace(
            ", both halfway along the length", "")
        with self.assertRaises(RoleOutputError) as raised:
            _design(case)
        problem = " ".join(raised.exception.problems)
        self.assertIn("the set screw holes themselves are missing", problem)
        self.assertIn("The tag on `cylinder`", problem)

    @staticmethod
    def _body() -> dict:
        return {"id": "c", "parameters": [], "features": [
            {"id": "body", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 30, "unit": "mm"},
                "height": {"magnitude": 20, "unit": "mm"}}},
            {"id": "bore", "kind": "hole", "inputs": ["body"], "parameters": {
                "diameter": {"magnitude": 8, "unit": "mm"},
                "position": {"vector": [0, 0, 10], "unit": "mm"}}}]}


class APartInTwoPieces(unittest.TestCase):
    """The one-piece gate: two bodies that do not touch fail; a hollow
    sealed inside a single body is not a second piece."""

    @staticmethod
    def _report(features):
        from forge_ir import Document
        from forge_pipeline import verify_component

        document = Document.from_json(json.dumps({
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1, "name": "t",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [],
            "components": [{"id": "c", "name": "c", "parameters": [],
                            "features": features}]}))
        report = verify_component(document, document.components[0],
                                  measurement_depth=5)
        return {r.gate.identifier: r.status.value for r in report.gate_results}

    def test_two_blocks_apart_fail(self) -> None:
        gates = self._report([
            {"id": "a", "kind": "box", "parameters": {
                "size": {"vector": [10, 10, 10], "unit": "mm"}}},
            {"id": "b", "kind": "box", "parameters": {
                "size": {"vector": [10, 10, 10], "unit": "mm"},
                "origin": {"vector": [20, 0, 0], "unit": "mm"}}},
            {"id": "u", "kind": "union", "inputs": ["a", "b"]}])
        self.assertEqual(gates["GEOM_ONE_PIECE"], "FAIL")

    def test_two_blocks_touching_pass(self) -> None:
        gates = self._report([
            {"id": "a", "kind": "box", "parameters": {
                "size": {"vector": [10, 10, 10], "unit": "mm"}}},
            {"id": "b", "kind": "box", "parameters": {
                "size": {"vector": [10, 10, 10], "unit": "mm"},
                "origin": {"vector": [9, 0, 0], "unit": "mm"}}},
            {"id": "u", "kind": "union", "inputs": ["a", "b"]}])
        self.assertEqual(gates["GEOM_ONE_PIECE"], "PASS")

    def test_a_sealed_hollow_is_not_a_second_piece(self) -> None:
        gates = self._report([
            {"id": "a", "kind": "sphere", "parameters": {
                "diameter": {"magnitude": 30, "unit": "mm"}}},
            {"id": "b", "kind": "sphere", "parameters": {
                "diameter": {"magnitude": 15, "unit": "mm"}}},
            {"id": "s", "kind": "subtract", "inputs": ["a", "b"]}])
        self.assertEqual(gates["GEOM_ONE_PIECE"], "PASS")


class TheOpenTopBoxDrawnAsAPlate(unittest.TestCase):
    """"A PLA open-top box, 60 mm long, 40 mm wide and 30 mm tall on the
    outside, with 2 mm walls and a 2 mm thick floor. The top is completely
    open." The record held the extents as bounds and carried nothing about
    the walls, the floor or the open top; the PLA the brief states was an
    unapproved assumption that would have blocked release; the intent
    inferred the box open at the bottom. The design was a 40 by 30 by 2
    plate, three times."""

    CASE = "open_top_box_drawn_as_a_plate"

    def test_the_record_measures_the_box(self) -> None:
        record = _requirements(_load(self.CASE))
        claims = {r["measurement"]: (r["comparison"],
                                     r["threshold"]["magnitude"])
                  for r in record.requirements}
        self.assertEqual(claims["bounding_box_x"], ("equals", 60.0))
        self.assertEqual(claims["bounding_box_z"], ("equals", 30.0))
        self.assertEqual(claims["wall_thickness"], ("equals", 2.0))
        self.assertEqual(claims["floor_thickness"], ("equals", 2.0))
        self.assertEqual(claims["opening_depth"], ("equals", 28.0))
        self.assertEqual(record.assumptions, ())

    def test_the_inference_against_the_floor_is_dropped(self) -> None:
        from forge_roles import BriefInterpreter

        case = _load(self.CASE)
        intent = BriefInterpreter().parse(case["intent"], brief=case["brief"])
        self.assertEqual(intent.implied, ())

    def test_it_now_builds_the_box(self) -> None:
        report = _verify(_design(_load(self.CASE)))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        # Centred on the origin: 60 by 40, from z = -15 to 15.
        self.assertEqual(_inside(report, [
            (0, 0, -14), (-29, 0, 0), (29, 0, 0), (0, -19, 0), (0, 19, 0),
        ]), [True] * 5)
        self.assertEqual(_inside(report, [
            (0, 0, -12.9), (0, 0, 14.9), (-27.9, 0, 0), (0, 17.9, 14.9),
        ]), [False] * 4)

    def test_a_shell_is_a_sealed_box_and_is_replaced(self) -> None:
        from forge_roles.library import _an_open_top_box_left_solid

        component = {"id": "c", "parameters": [
            {"id": "wall_thickness", "value": {"magnitude": 2, "unit": "mm"}}],
            "features": [
            {"id": "outer", "kind": "box", "parameters": {
                "size": {"vector": [60, 40, 30], "unit": "mm"}}},
            {"id": "hollow", "kind": "shell", "inputs": ["outer"],
             "parameters": {"thickness": {"expression": "wall_thickness",
                                          "unit": "mm"}}}]}
        notes = _an_open_top_box_left_solid(
            component, None, "An open-top box with 2 mm walls and a 3 mm "
            "floor.")
        self.assertIn("sealed box", notes[0])
        kinds = [(f["id"], f["kind"]) for f in component["features"]]
        self.assertEqual(kinds, [("outer", "box"), ("cavity", "box"),
                                 ("hollow", "subtract")])
        self.assertEqual(
            component["features"][1]["parameters"]["origin"]["vector"],
            ["wall_thickness", "wall_thickness", "floor_thickness"])

    def test_a_cup_left_solid(self) -> None:
        from forge_roles.library import _an_open_top_box_left_solid

        component = {"id": "c", "parameters": [], "features": [
            {"id": "body", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 50, "unit": "mm"},
                "height": {"magnitude": 40, "unit": "mm"}}}]}
        self.assertTrue(_an_open_top_box_left_solid(
            component, None, "An open-top cup 50 mm across, 40 mm tall, with "
            "2 mm walls and a 3 mm thick floor."))
        cavity = component["features"][1]
        self.assertEqual(cavity["kind"], "cylinder")
        self.assertEqual(cavity["parameters"]["diameter"]["expression"],
                         "50 * mm - 2 * wall_thickness")

    def test_what_it_will_not_build(self) -> None:
        from forge_roles.library import _an_open_top_box_left_solid

        def box():
            return {"id": "c", "parameters": [], "features": [
                {"id": "b", "kind": "box", "parameters": {
                    "size": {"vector": [60, 40, 30], "unit": "mm"}}}]}

        for brief in (
            "A box with 2 mm walls and a 2 mm floor.",       # top not open
            "An open-top box with 2 mm walls.",              # no floor
            "An open-top box with a 2 mm floor.",            # no walls
        ):
            with self.subTest(brief=brief):
                self.assertEqual(_an_open_top_box_left_solid(
                    box(), None, brief), [])

    def test_the_box_size_needs_a_name_for_the_whole_part(self) -> None:
        """A claimed extent can be the model's misreading; it is only taken
        for the box's side when a whole-part size the brief states holds it."""
        from forge_roles.library import (
            RequirementSet, _the_only_box_is_the_part_s_size)

        def claim(binding, figure):
            return {"id": binding, "measurement": binding,
                    "comparison": "equals",
                    "threshold": {"magnitude": figure, "unit": "mm"}}

        component = {"id": "c", "parameters": [
            {"id": "hole_diameter", "value": {"magnitude": 5, "unit": "mm"}}],
            "features": [{"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"}}}]}
        record = RequirementSet(requirements=(
            claim("bounding_box_z", 5.0),), assumptions=(), unknowns=())
        self.assertEqual(_the_only_box_is_the_part_s_size(
            component, record, "A 30 mm square plate 4 mm thick with a 5 mm "
            "hole."), [])


class AnExactSizeIsNotABound(unittest.TestCase):
    def test_a_fit_stays_a_bound(self) -> None:
        from forge_roles.library import _an_exact_size_written_as_a_bound

        claims = [{"id": "X", "measurement": "bounding_box_x",
                   "comparison": "at_most",
                   "threshold": {"magnitude": 60.0, "unit": "mm"}}]
        self.assertEqual(_an_exact_size_written_as_a_bound(
            "A bracket that fits inside a 60 mm slot.", claims), [])
        self.assertEqual(claims[0]["comparison"], "at_most")
        self.assertTrue(_an_exact_size_written_as_a_bound(
            "A bracket 60 mm long.", claims))
        self.assertEqual(claims[0]["comparison"], "equals")


class ContainerMeasurements(unittest.TestCase):
    """Walls, floor and opening, measured on the built part."""

    @staticmethod
    def _measure(features, binding):
        from forge_ir import Document
        from forge_pipeline.measure import resolve_measurement
        from forge_geom import measure_mass_properties
        from forge_kernel import Compiler

        document = Document.from_json(json.dumps({
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "revision": 1, "name": "t",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [],
            "components": [{"id": "c", "name": "c", "parameters": [],
                            "features": features}]}))
        part = Compiler().compile_component(document.components[0])
        properties = measure_mass_properties(part.solid, max_depth=6)
        return resolve_measurement(binding, component=document.components[0],
                                   part=part, properties=properties)

    OUTER = {"id": "o", "kind": "box", "parameters": {
        "size": {"vector": [60, 40, 30], "unit": "mm"}}}

    def _inner(self, height, wall_x=2.0):
        return {"id": "i", "kind": "box", "parameters": {
            "size": {"vector": [60 - 2 * wall_x, 36, height], "unit": "mm"},
            "origin": {"vector": [wall_x, 2, 3], "unit": "mm"}}}

    def test_an_open_box(self) -> None:
        features = [self.OUTER, self._inner(40),
                    {"id": "s", "kind": "subtract", "inputs": ["o", "i"]}]
        for binding, figure in (("wall_thickness", 2.0),
                                ("floor_thickness", 3.0),
                                ("opening_depth", 27.0)):
            with self.subTest(binding=binding):
                value = self._measure(features, binding).value
                self.assertAlmostEqual(value.magnitude.midpoint, figure,
                                       places=3)

    def test_a_sealed_box_is_not_open(self) -> None:
        features = [self.OUTER, self._inner(24),
                    {"id": "s", "kind": "subtract", "inputs": ["o", "i"]}]
        value = self._measure(features, "opening_depth").value
        self.assertAlmostEqual(value.magnitude.midpoint, 0.0, places=3)

    def test_one_thick_wall_is_a_range(self) -> None:
        features = [self.OUTER, self._inner(40, wall_x=3.0),
                    {"id": "s", "kind": "subtract", "inputs": ["o", "i"]}]
        value = self._measure(features, "wall_thickness").value
        self.assertAlmostEqual(value.magnitude.lo, 2.0, places=3)
        self.assertAlmostEqual(value.magnitude.hi, 3.0, places=3)

    def test_a_solid_block_has_no_floor_to_speak_of(self) -> None:
        value = self._measure([self.OUTER], "floor_thickness").value
        self.assertAlmostEqual(value.magnitude.midpoint, 30.0, places=3)


class TheOpenTopBoxCutThroughTheMiddle(unittest.TestCase):
    """The rerun. The design cut its box with `floor_box` -- the whole
    footprint by the floor's 2 mm, through the middle -- and blended the cut
    by 2 mm: two slabs, released as a box. The first attempt read
    `floor_thickness` and declared nothing, and was sent back for it."""

    CASE = "open_top_box_cut_through_the_middle"

    def test_it_now_builds_the_box(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        cut = {f["id"]: f for f in draft.payload["components"][0]["features"]}
        self.assertNotIn("blend_radius", cut["floor"].get("parameters", {}))
        self.assertEqual(_inside(report, [
            (0, 0, -14), (-29, 0, 0), (0, 19, 14.9)]), [True] * 3)
        self.assertEqual(_inside(report, [
            (0, 0, -12.9), (0, 0, 0), (0, 0, 14.9)]), [False] * 3)

    def test_the_first_attempt_is_settled_too(self) -> None:
        case = _load(self.CASE)
        component = case["answer"]["document"]["components"][0]
        component["parameters"] = [p for p in component["parameters"]
                                   if p["id"] != "floor_thickness"]
        draft = _design(case)
        self.assertIn("declared `floor_thickness` = 2 mm",
                      " ".join(draft.notes))
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_a_cut_that_is_already_the_space_is_left_alone(self) -> None:
        from forge_roles.library import _an_open_top_box_left_solid

        component = {"id": "c", "parameters": [], "features": [
            {"id": "o", "kind": "box", "parameters": {
                "size": {"vector": [60, 40, 30], "unit": "mm"}}},
            {"id": "s", "kind": "subtract", "inputs": ["o", "i"]},
            {"id": "i", "kind": "box", "parameters": {
                "size": {"vector": [56, 36, 28], "unit": "mm"},
                "origin": {"vector": [2, 2, 2], "unit": "mm"}}}]}
        before = json.dumps(component, sort_keys=True)
        self.assertEqual(_an_open_top_box_left_solid(
            component, None, "An open-top box with 2 mm walls and a 2 mm "
            "floor."), [])
        self.assertEqual(json.dumps(component, sort_keys=True), before)

    def test_a_cut_it_cannot_read_as_the_space_is_left_alone(self) -> None:
        from forge_roles.library import _an_open_top_box_left_solid

        def box(origin):
            return {"id": "c", "parameters": [], "features": [
                {"id": "o", "kind": "box", "parameters": {
                    "size": {"vector": [60, 40, 30], "unit": "mm"}}},
                {"id": "s", "kind": "subtract", "inputs": ["o", "i"]},
                {"id": "i", "kind": "box", "parameters": {
                    "size": {"vector": [20, 20, 28], "unit": "mm"},
                    "origin": {"vector": origin, "unit": "mm"}}}]}

        brief = "An open-top box with 2 mm walls and a 2 mm floor."
        self.assertEqual(_an_open_top_box_left_solid(
            box([2, 2, 2]), None, brief), [], "off the middle")
        self.assertEqual(_an_open_top_box_left_solid(
            box([20, 10, 2]), None, brief + " A slot is cut in one wall."),
            [], "the brief cuts something else")


class TheLBracketWithItsUprightLyingFlat(unittest.TestCase):
    """"A PLA L-bracket 40 mm wide, made of 5 mm thick plate. The base leg is
    50 mm long and lies flat; the upright leg stands on the back end of the
    base and is 40 mm tall overall." Two holes through each leg, placed by
    the brief. The design laid the upright flat inside the base and drilled
    all four holes down Z; refused twice over one undeclared name."""

    CASE = "l_bracket_upright_lying_flat"

    def test_the_record_measures_the_height(self) -> None:
        claims = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in _requirements(_load(self.CASE)).requirements}
        self.assertEqual(claims["bounding_box_z"], 40.0)

    def test_it_now_builds_the_bracket(self) -> None:
        report = _verify(_design(_load(self.CASE)))
        self.assertEqual(_not_passing(report), {})
        holes = {h["feature"]: [round(c, 1) for c in h["centre_mm"]]
                 for h in report.measurements["part"]["holes"]}
        self.assertEqual(holes["base_hole_1"], [-10.0, 0.0, 0.0])
        self.assertEqual(holes["upright_hole_2"][0::2], [10.0, 22.5])
        # The base from y -25 to 25; the upright on its back 5 mm, from the
        # floor at z -2.5 to 37.5.
        self.assertEqual(_inside(report, [
            (0, -24, 0), (0, 22.5, 37), (19, 24, -2), (0, 22.5, 22.5)]),
            [True] * 4)
        self.assertEqual(_inside(report, [
            (0, 0, 3), (0, 19, 10), (0, 22.5, 38), (10, 22.5, 22.5),
            (-10, 0, 0)]), [False] * 5)

    def test_one_parameter_for_two_equal_spacings_is_checked(self) -> None:
        from unittest import mock

        with mock.patch(
                "forge_roles.library._holes_placed_where_the_brief_puts_them",
                return_value=[]):
            draft = _design(_load(self.CASE))
        self.assertIn("drives both equal dimensions with one parameter",
                      " ".join(draft.notes))

    def test_a_standing_plate_already_standing_is_left_alone(self) -> None:
        from forge_roles.library import _plates_as_the_brief_lays_them

        component = {"id": "c", "parameters": [], "features": [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": [40, 50, 5], "unit": "mm"}}},
            {"id": "upright", "kind": "box", "parameters": {
                "size": {"vector": [40, 5, 40], "unit": "mm"},
                "origin": {"vector": [0, 45, 0], "unit": "mm"}}}]}
        self.assertEqual(_plates_as_the_brief_lays_them(
            component, None, "The base lies flat; the upright stands on "
            "the back end of the base."), [])

    def test_holes_the_brief_places_nowhere_are_left_alone(self) -> None:
        from forge_roles.library import _holes_placed_where_the_brief_puts_them

        component = {"id": "c", "parameters": [], "features": [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": [40, 50, 5], "unit": "mm"}}},
            {"id": "base_hole_1", "kind": "hole", "inputs": ["base"],
             "parameters": {"diameter": {"magnitude": 5, "unit": "mm"},
                            "position": {"vector": [5, 5, 2.5], "unit": "mm"}}},
            {"id": "base_hole_2", "kind": "hole", "inputs": ["base_hole_1"],
             "parameters": {"diameter": {"magnitude": 5, "unit": "mm"},
                            "position": {"vector": [35, 5, 2.5], "unit": "mm"}}}]}
        self.assertEqual(_holes_placed_where_the_brief_puts_them(
            component, None, "Two 5 mm holes pass through the base, 30 mm "
            "apart."), [])


class TheLBracketWithBothPlatesStanding(unittest.TestCase):
    """The rerun: this time both plates stood, centred on each other."""

    CASE = "l_bracket_both_plates_standing"

    def test_it_now_builds_the_bracket(self) -> None:
        report = _verify(_design(_load(self.CASE)))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(_inside(report, [
            (0, -24, 0), (0, 22.5, 37), (19, 24, -2), (0, 22.5, 22.5)]),
            [True] * 4)
        self.assertEqual(_inside(report, [
            (0, 0, 3), (0, 19, 10), (0, 22.5, 38), (10, 22.5, 22.5),
            (-10, 0, 0)]), [False] * 5)


class TheLayoutTheBriefDescribes(unittest.TestCase):
    """The brief's own words for how each piece lies and where it stands."""

    def _read(self, brief):
        from forge_roles.library import _the_layout_the_brief_describes

        return _the_layout_the_brief_describes(brief)

    def test_an_l_bracket(self) -> None:
        self.assertEqual(self._read(
            "The base leg is 50 mm long and lies flat; the upright leg "
            "stands on the back end of the base and is 40 mm tall overall."),
            {"base": {"lies": "flat"},
             "upright": {"lies": "standing", "on": "base", "ends": ["back"]}})

    def test_two_walls_on_two_ends(self) -> None:
        self.assertEqual(self._read(
            "The base plate lies flat. Two side walls stand on the front and "
            "back ends of the base.")["side"]["ends"], ["front", "back"])
        self.assertEqual(self._read(
            "The base lies flat. Two walls stand on both ends of the base.")
            ["wall"]["ends"], ["front", "back"])

    def test_on_top(self) -> None:
        self.assertEqual(self._read(
            "A post stands on top of the base, centred.")["post"],
            {"lies": "standing", "on": "base", "ends": ["top"]})

    def test_a_piece_with_another_on_top_of_it(self) -> None:
        """Run 20260929T214308: read as a flange standing on "it"."""
        self.assertEqual(self._read(
            "An aluminium pulley hub. A flange disc 50 mm across and 6 mm "
            "thick, with a round hub 25 mm across and 15 mm tall standing on "
            "top of it, centred."),
            # A disc given a thickness and no height lies flat.
            {"flange": {"lies": "flat"},
             "hub": {"lies": "standing", "on": "flange", "ends": ["top"]}})

    def test_the_part_s_own_name_is_not_a_piece_standing(self) -> None:
        self.assertEqual(self._read(
            "A PLA stand: a base plate 60 mm long and 6 mm thick, with a "
            "round post 20 mm across standing on top of it, centred."),
            {"base": {"lies": "flat"},
             "post": {"lies": "standing", "on": "base", "ends": ["top"]}})

    def test_a_piece_said_to_do_both_is_left_out(self) -> None:
        self.assertEqual(self._read(
            "The plate lies flat. The plate stands up."), {})


class PiecesLaidAsTheBriefSays(unittest.TestCase):
    """The solver on parts it has never seen: a U-channel and a stand."""

    @staticmethod
    def _box(i, size, origin=None):
        p = {"size": {"vector": size, "unit": "mm"}, "centered": True}
        if origin is not None:
            p["origin"] = {"vector": origin, "unit": "mm"}
        return {"id": i, "kind": "box", "parameters": p}

    @staticmethod
    def _record(**figures):
        from forge_roles.library import RequirementSet

        return RequirementSet(requirements=tuple(
            {"id": k, "measurement": k if k.startswith("bounding") else
             f"parameter:{k}", "comparison": "equals",
             "threshold": {"magnitude": v, "unit": "mm"}}
            for k, v in figures.items()), assumptions=(), unknowns=())

    def test_a_u_channel(self) -> None:
        from forge_roles.library import _plates_as_the_brief_lays_them

        component = {"id": "u", "parameters": [
            {"id": k, "value": {"magnitude": v, "unit": "mm"}} for k, v in (
                ("base_length", 60), ("width", 30), ("thickness", 4),
                ("wall_height", 25))], "features": [
            self._box("base", ["width", "base_length", "thickness"]),
            self._box("side_wall_1", ["width", "wall_height", "thickness"]),
            self._box("side_wall_2", ["width", "wall_height", "thickness"])]}
        notes = _plates_as_the_brief_lays_them(
            component, self._record(bounding_box_z=25.0),
            "The base plate lies flat. Two side walls stand on the front and "
            "back ends of the base; each is 25 mm tall overall.")
        self.assertEqual(len(notes), 4, notes)
        walls = component["features"][1:]
        self.assertEqual([w["parameters"]["size"]["vector"] for w in walls],
                         [["width", "thickness", "wall_height"]] * 2)
        self.assertEqual(walls[0]["parameters"]["origin"]["vector"],
                         ["-width / 2", "-base_length / 2", "-thickness / 2"])
        self.assertEqual(walls[1]["parameters"]["origin"]["vector"][1],
                         "base_length / 2 - thickness")

    def test_a_post_on_top(self) -> None:
        from forge_roles.library import _plates_as_the_brief_lays_them

        component = {"id": "s", "parameters": [
            {"id": k, "value": {"magnitude": v, "unit": "mm"}} for k, v in (
                ("base_size", 50), ("base_thickness", 5), ("post_size", 10),
                ("post_height", 30))], "features": [
            self._box("base", ["base_size", "base_size", "base_thickness"]),
            self._box("post", ["post_size", "post_size", "post_height"])]}
        _plates_as_the_brief_lays_them(
            component, None, "The base plate lies flat. A post stands on top "
            "of the base, centred.")
        self.assertEqual(
            component["features"][1]["parameters"]["origin"]["vector"],
            ["-post_size / 2", "-post_size / 2", "base_thickness / 2"])

    def test_a_piece_already_placed_is_left_alone(self) -> None:
        from forge_roles.library import _plates_as_the_brief_lays_them

        component = {"id": "s", "parameters": [], "features": [
            self._box("base", [50, 50, 5]),
            {"id": "post", "kind": "box", "parameters": {
                "size": {"vector": [10, 10, 30], "unit": "mm"},
                "origin": {"vector": [-5, -5, 2.5], "unit": "mm"}}}]}
        before = json.dumps(component, sort_keys=True)
        self.assertEqual(_plates_as_the_brief_lays_them(
            component, None, "The base lies flat. A post stands on top of "
            "the base, centred."), [])
        self.assertEqual(json.dumps(component, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()


# ----------------------------------------------------------------------------
# Placement in words: the designer says where, Forge computes the coordinates.
# ----------------------------------------------------------------------------
def _mm(**values) -> list[dict]:
    return [{"id": k, "value": {"magnitude": v, "unit": "mm"}}
            for k, v in values.items()]


def _stated(id_: str, parameter: str, value: float, unit: str = "mm") -> dict:
    return {"id": id_, "statement": f"{parameter} is {value} {unit}",
            "measurement": f"parameter:{parameter}", "comparison": "equals",
            "threshold": {"magnitude": value, "unit": unit},
            "type": "geometric", "verification": "exact_geometry",
            "strength": "hard", "source": "user", "state": "accepted"}


def _case(brief: str, requirements: list[dict], features: list[dict],
          parameters: list[dict]) -> dict:
    return {"brief": brief,
            "requirements": {"risk_class": "low", "requirements": requirements,
                             "assumptions": [], "unknowns": []},
            "answer": {"rationale": "", "document": {"name": "part", "components": [
                {"id": "part", "parameters": parameters,
                 "features": features}]}}}


def _cylinder(id_: str, diameter: str, height: str, **more) -> dict:
    return {"id": id_, "kind": "cylinder", "parameters": {
        "diameter": {"expression": diameter, "unit": "mm"},
        "height": {"expression": height, "unit": "mm"}}, **more}


def _placed_hole(id_: str, diameter: str, place: dict, after: str,
                 **more) -> dict:
    return {"id": id_, "kind": "hole", "inputs": [after], "place": place,
            "parameters": {"diameter": {"expression": diameter, "unit": "mm"}},
            **more}


class PlacementInWords(unittest.TestCase):
    """Every part of the test plan, written with `lies` and `place` only.

    No origin, position or axis anywhere: each of these is the design a weak
    model can write, because it is the brief's own sentence in JSON. Forge
    turns each into the exact part, and the gates pass it.
    """

    L_BRIEF = (
        "A PLA L-bracket 40 mm wide, made of 5 mm thick plate. The base leg is "
        "50 mm long and lies flat; the upright leg stands on the back end of "
        "the base and is 40 mm tall overall. Two 5 mm holes pass through the "
        "base, 20 mm apart across its width, centred 25 mm from the front end. "
        "Two 5 mm holes pass through the upright, 20 mm apart across its "
        "width, centred 25 mm above the bottom. It carries no load.")

    def _l_bracket(self, base_size=("width", "base_length", "thickness"),
                   upright_size=("width", "thickness", "upright_height"),
                   on="base") -> dict:
        requirements = [
            _stated("W", "width", 40), _stated("T", "thickness", 5),
            _stated("L", "base_length", 50), _stated("H", "upright_height", 40),
            _stated("S", "hole_spacing", 20), _stated("D", "base_hole_offset", 25),
            _stated("E", "upright_hole_height", 25), _stated("HD", "hole_diameter", 5)]
        features = [
            {"id": "base", "kind": "box", "lies": "flat", "parameters": {
                "size": {"vector": list(base_size), "unit": "mm"}}},
            {"id": "upright", "kind": "box", "lies": "standing",
             "place": {"on": on, "at": "back_end", "from": "floor"},
             "parameters": {"size": {"vector": list(upright_size), "unit": "mm"}}},
            {"id": "body", "kind": "union", "inputs": ["base", "upright"]},
            _placed_hole("base_hole", "hole_diameter", {
                "through": "base", "count": 2, "spacing": "hole_spacing",
                "across": "width", "from": "front",
                "distance": "base_hole_offset"}, "body"),
            _placed_hole("upright_hole", "hole_diameter", {
                "through": "upright", "count": 2, "spacing": "hole_spacing",
                "across": "width", "from": "bottom",
                "distance": "upright_hole_height"}, "base_hole")]
        return _case(self.L_BRIEF, requirements, features, _mm(
            width=40, thickness=5, base_length=50, upright_height=40,
            hole_spacing=20, base_hole_offset=25, upright_hole_height=25,
            hole_diameter=5))

    def _holes(self, report) -> list[tuple]:
        return sorted(tuple(round(c, 3) for c in h["centre_mm"])
                      for h in report.measurements["part"]["holes"]
                      if h["present"])

    def test_an_l_bracket(self) -> None:
        report = _verify(_design(self._l_bracket()))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        self.assertEqual(report.measurements["part"]["open_holes"], 4)
        for got, wanted in zip(report.measurements["part"]["envelope_mm"],
                               (40, 50, 40)):
            self.assertAlmostEqual(got, wanted, delta=1.0)

    def test_an_l_bracket_whose_sizes_are_written_in_any_order(self) -> None:
        reference = _verify(_design(self._l_bracket()))
        turned = _verify(_design(self._l_bracket(
            base_size=("thickness", "width", "base_length"),
            upright_size=("upright_height", "width", "thickness"))))
        self.assertEqual(_not_passing(turned), {})
        # The same bracket; lying flat, its length may run along X or Y.
        swapped = sorted((y, x, z) for x, y, z in self._holes(turned))
        self.assertIn(self._holes(reference), (self._holes(turned), swapped))
        self.assertAlmostEqual(turned.measurements["part"]["volume_mm3"],
                               reference.measurements["part"]["volume_mm3"],
                               delta=1.0)

    def test_a_flange(self) -> None:
        case = _case(
            "A steel pipe flange. It is a disc 80 mm across and 10 mm thick, "
            "with a 30 mm bore through the centre. Four 8 mm bolt holes pass "
            "all the way through the disc, equally spaced on a 60 mm bolt "
            "circle. It carries no load.",
            [_stated("D", "diameter", 80), _stated("T", "thickness", 10),
             _stated("B", "bore_diameter", 30),
             _stated("H", "bolt_hole_diameter", 8),
             _stated("C", "bolt_circle_diameter", 60)],
            [_cylinder("disc", "diameter", "thickness"),
             _placed_hole("bore", "bore_diameter", {"through": "disc"}, "disc"),
             _placed_hole("bolt_hole", "bolt_hole_diameter", {
                 "through": "disc", "circle": "bolt_circle_diameter",
                 "count": 4}, "bore")],
            _mm(diameter=80, thickness=10, bore_diameter=30,
                bolt_hole_diameter=8, bolt_circle_diameter=60))
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.measurements["part"]["open_holes"], 5)
        radii = sorted(round((h["centre_mm"][0] ** 2 + h["centre_mm"][1] ** 2)
                             ** 0.5, 3) for h in
                       report.measurements["part"]["holes"])
        self.assertEqual(radii, [0.0, 30.0, 30.0, 30.0, 30.0])

    def _collar(self, place: dict) -> dict:
        angle = dict(_stated("A", "x", 90, "deg"),
                     measurement="angle_between:hole:set_screw")
        count = dict(_stated("C", "x", 2, ""),
                     measurement="feature_count:hole:set_screw")
        return _case(
            "A machined aluminium shaft collar. The outer diameter is 25 mm "
            "and it is 15 mm long. A 12 mm bore runs all the way through on "
            "the axis. Two 4 mm set screw holes pass through the wall from "
            "the outside into the bore, 90 degrees apart, both halfway along "
            "the length. It carries no load.",
            [_stated("D", "outer_diameter", 25), _stated("L", "length", 15),
             _stated("B", "bore_diameter", 12),
             _stated("S", "set_screw_diameter", 4), angle, count],
            [_cylinder("body", "outer_diameter", "length"),
             _placed_hole("bore", "bore_diameter", {"through": "body"}, "body"),
             _placed_hole("set_screw", "set_screw_diameter", place, "bore",
                          tags=["set_screw"])],
            _mm(outer_diameter=25, length=15, bore_diameter=12,
                set_screw_diameter=4))

    def test_a_collar_with_two_set_screws(self) -> None:
        report = _verify(_design(self._collar(
            {"into": "body", "count": 2, "apart": 90, "at": "middle"})))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        self.assertEqual(report.measurements["part"]["open_holes"], 3)

    def test_a_hub_standing_on_its_flange(self) -> None:
        case = _case(
            "An aluminium pulley hub. A flange disc 50 mm across and 6 mm "
            "thick, with a round hub 25 mm across and 15 mm tall standing on "
            "top of it, centred. A 10 mm bore runs through both the flange "
            "and the hub. Three 5 mm holes pass through the flange only, "
            "equally spaced on a 38 mm circle. It carries no load.",
            [_stated("FD", "flange_diameter", 50),
             _stated("FT", "flange_thickness", 6),
             _stated("HD", "hub_diameter", 25), _stated("HH", "hub_height", 15),
             _stated("B", "bore_diameter", 10), _stated("H", "hole_diameter", 5),
             _stated("C", "bolt_circle_diameter", 38)],
            [_cylinder("flange", "flange_diameter", "flange_thickness"),
             _cylinder("hub", "hub_diameter", "hub_height",
                       place={"on": "flange", "at": "top"}),
             {"id": "body", "kind": "union", "inputs": ["flange", "hub"]},
             _placed_hole("bore", "bore_diameter", {"through": "hub"}, "body"),
             _placed_hole("bolt_hole", "hole_diameter", {
                 "through": "flange", "circle": "bolt_circle_diameter",
                 "count": 3}, "bore")],
            _mm(flange_diameter=50, flange_thickness=6, hub_diameter=25,
                hub_height=15, bore_diameter=10, hole_diameter=5,
                bolt_circle_diameter=38))
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {})
        # Hub on the flange, not floating or buried; the bore through both.
        self.assertEqual(_inside(report, [(8, 0, 3), (8, 0, 15), (8, 0, 20.5)]),
                         [True, True, True])
        self.assertEqual(_inside(report, [(0, 0, 3), (0, 0, 15), (8, 0, 21.5),
                                          (15, 0, 10)]), [False] * 4)

    def test_the_words_never_reach_the_document(self) -> None:
        draft = _design(self._l_bracket())
        text = json.dumps(draft.document.to_json() if hasattr(
            draft.document, "to_json") else str(draft.document))
        self.assertNotIn('"place"', text)
        self.assertNotIn('"lies"', text)

    def test_an_unknown_solid_is_named_back(self) -> None:
        from forge_roles.base import RoleOutputError

        with self.assertRaises(RoleOutputError) as caught:
            _design(self._l_bracket(on="plate"))
        said = " ".join(caught.exception.problems)
        self.assertIn("`on: plate`", said)
        self.assertIn("`base`", said)

    def test_two_set_screws_without_an_angle_are_asked_about(self) -> None:
        from forge_roles.base import RoleOutputError

        with self.assertRaises(RoleOutputError) as caught:
            _design(self._collar({"into": "body", "count": 2, "at": "middle"}))
        self.assertIn("`apart`", " ".join(caught.exception.problems))

    def test_only_the_designer_is_offered_the_words(self) -> None:
        from forge_roles import ForgeIRDesigner
        from forge_ir.spec import document_schema

        offered = json.dumps(ForgeIRDesigner().output_schema(brief=self.L_BRIEF))
        self.assertIn('"place"', offered)
        self.assertIn('"lies"', offered)
        self.assertNotIn('"place"', json.dumps(document_schema()))

    def _stand(self, hole: dict, extra: list[dict], **figures) -> dict:
        return _case(
            "An aluminium stand: a base plate 60 mm long, 40 mm wide and 6 mm "
            "thick, with a round post 20 mm across and 30 mm tall standing on "
            "top of it, centred. An 8 mm hole is drilled 20 mm deep into the "
            "top of the post. It carries no load.",
            [_stated("L", "plate_length", 60), _stated("W", "plate_width", 40),
             _stated("T", "plate_thickness", 6),
             _stated("PD", "post_diameter", 20), _stated("PH", "post_height", 30),
             _stated("HD", "hole_diameter", 8)] + extra,
            [{"id": "plate", "kind": "box", "lies": "flat", "parameters": {
                "size": {"vector": ["plate_length", "plate_width",
                                    "plate_thickness"], "unit": "mm"}}},
             _cylinder("post", "post_diameter", "post_height",
                       place={"on": "plate", "at": "top"}),
             {"id": "body", "kind": "union", "inputs": ["plate", "post"]},
             hole],
            _mm(plate_length=60, plate_width=40, plate_thickness=6,
                post_diameter=20, post_height=30, hole_diameter=8, **figures))

    def test_a_blind_hole_is_drilled_from_the_top(self) -> None:
        hole = _placed_hole("bore", "hole_diameter", {"through": "post"}, "body")
        hole["parameters"]["depth"] = {"expression": "hole_depth", "unit": "mm"}
        report = _verify(_design(self._stand(
            hole, [_stated("DD", "hole_depth", 20)], hole_depth=20)))
        self.assertEqual(_not_passing(report), {})
        # Plate and post solid below the hole; empty for its 20 mm.
        self.assertEqual(_inside(report, [(30, 20, 3), (30, 20, 12),
                                          (30, 20, 20), (30, 20, 33),
                                          (37, 20, 33)]),
                         [True, True, False, False, True])

    def test_a_depth_as_deep_as_the_solid_is_a_through_hole(self) -> None:
        hole = _placed_hole("bore", "hole_diameter", {"through": "post"}, "body")
        hole["parameters"]["depth"] = {"expression": "post_height", "unit": "mm"}
        draft = _design(self._stand(hole, []))
        cut = next(f for f in draft.document.components[0].features
                   if f.identifier == "bore")
        self.assertNotIn("depth", cut.parameters)

    def test_one_hole_in_the_middle_and_one_from_the_left(self) -> None:
        case = _case(
            "An aluminium plate 60 mm long, 40 mm wide and 5 mm thick. A 10 mm "
            "hole passes through the middle. A 4 mm hole passes through the "
            "plate 8 mm from the left end. It carries no load.",
            [_stated("L", "length", 60), _stated("W", "width", 40),
             _stated("T", "thickness", 5),
             _stated("C", "centre_hole_diameter", 10),
             _stated("S", "small_hole_diameter", 4),
             _stated("O", "small_hole_offset", 8)],
            [{"id": "plate", "kind": "box", "lies": "flat", "parameters": {
                "size": {"vector": ["length", "width", "thickness"],
                         "unit": "mm"}}},
             _placed_hole("centre", "centre_hole_diameter",
                          {"through": "plate"}, "plate"),
             _placed_hole("small", "small_hole_diameter", {
                 "through": "plate", "from": "left",
                 "distance": "small_hole_offset"}, "centre")],
            _mm(length=60, width=40, thickness=5, centre_hole_diameter=10,
                small_hole_diameter=4, small_hole_offset=8))
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(self._holes(report),
                         [(8.0, 20.0, 2.5), (30.0, 20.0, 2.5)])

    def test_a_u_channel(self) -> None:
        wall = lambda id_, end: {  # noqa: E731
            "id": id_, "kind": "box", "lies": "standing",
            "place": {"on": "base", "at": end, "from": "floor"},
            "parameters": {"size": {"vector": ["thickness", "width",
                                               "wall_height"], "unit": "mm"}}}
        case = _case(
            "A steel U-channel. The base plate is 80 mm long, 40 mm wide and "
            "4 mm thick and lies flat. Two side walls, each 4 mm thick and "
            "30 mm tall overall, stand on the left and right ends of the "
            "base. It carries no load.",
            [_stated("L", "length", 80), _stated("W", "width", 40),
             _stated("T", "thickness", 4), _stated("H", "wall_height", 30)],
            [{"id": "base", "kind": "box", "lies": "flat", "parameters": {
                "size": {"vector": ["length", "width", "thickness"],
                         "unit": "mm"}}},
             wall("left_wall", "left_end"), wall("right_wall", "right_end"),
             {"id": "body", "kind": "union",
              "inputs": ["base", "left_wall", "right_wall"]}],
            _mm(length=80, width=40, thickness=4, wall_height=30))
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(_inside(report, [(2, 20, 28), (78, 20, 28), (40, 20, 2),
                                          (40, 20, 10)]),
                         [True, True, True, False])

    def test_a_wall_along_the_back_edge(self) -> None:
        case = _case(
            "A PLA shelf: a base plate 80 mm long, 30 mm deep and 4 mm thick "
            "lies flat, with a back wall 4 mm thick and 25 mm tall overall "
            "standing along its back edge. It carries no load.",
            [_stated("L", "length", 80), _stated("D", "depth", 30),
             _stated("T", "thickness", 4), _stated("H", "wall_height", 25)],
            [{"id": "base", "kind": "box", "lies": "flat", "parameters": {
                "size": {"vector": ["length", "depth", "thickness"],
                         "unit": "mm"}}},
             {"id": "wall", "kind": "box", "lies": "standing",
              "place": {"on": "base", "at": "back_edge", "from": "floor"},
              "parameters": {"size": {"vector": ["length", "thickness",
                                                 "wall_height"], "unit": "mm"}}},
             {"id": "body", "kind": "union", "inputs": ["base", "wall"]}],
            _mm(length=80, depth=30, thickness=4, wall_height=25))
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(_inside(report, [(2, 28, 22), (78, 28, 22),
                                          (40, 2, 2), (40, 10, 10)]),
                         [True, True, True, False])


class ThePlacementExampleIsReal(unittest.TestCase):
    """The example the designer is shown builds the part its brief describes."""

    def _case(self, component) -> dict:
        from forge_roles.library import PLACEMENT_EXAMPLE_BRIEF

        requirements = [
            _stated("L", "length", 60), _stated("D", "depth", 30),
            _stated("T", "thickness", 4), _stated("H", "wall_height", 25),
            _stated("HD", "hole_diameter", 4), _stated("S", "hole_spacing", 30),
            _stated("O", "hole_offset", 12), _stated("E", "wall_hole_height", 15),
            dict(_stated("B", "x", 2, ""), measurement="feature_count:hole:base"),
            dict(_stated("W", "x", 1, ""), measurement="feature_count:hole:wall")]
        return {"brief": PLACEMENT_EXAMPLE_BRIEF,
                "requirements": {"risk_class": "low",
                                 "requirements": requirements,
                                 "assumptions": [], "unknowns": []},
                "answer": {"rationale": "", "document": {
                    "name": "shelf bracket",
                    "components": [json.loads(json.dumps(component))]}}}

    def test_it_builds_and_passes(self) -> None:
        from forge_roles.library import PLACEMENT_EXAMPLE

        report = _verify(_design(self._case(PLACEMENT_EXAMPLE)))
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")
        holes = sorted(tuple(round(c) for c in h["centre_mm"])
                       for h in report.measurements["part"]["holes"])
        self.assertEqual([h[0] for h in holes], [15, 30, 45])
        self.assertEqual(sorted(h[1] for h in holes if h[0] != 30), [12, 12])
        self.assertEqual(_inside(report, [(2, 28, 22), (58, 28, 22),
                                          (30, 10, 2), (30, 10, 10),
                                          (30, 28, 15)]),
                         [True, True, True, False, False])

    def test_it_is_rendered_whole_in_the_prompt(self) -> None:
        from forge_roles import ForgeIRDesigner
        from forge_roles.library import PLACEMENT_EXAMPLE

        prompt = ForgeIRDesigner().system_prompt()
        for feature in PLACEMENT_EXAMPLE["features"]:
            self.assertIn(json.dumps(feature), prompt)
        for parameter in PLACEMENT_EXAMPLE["parameters"]:
            self.assertIn(json.dumps(parameter), prompt)

    def test_returning_it_is_refused(self) -> None:
        from forge_roles.base import RoleOutputError
        from forge_roles.library import PLACEMENT_EXAMPLE

        from forge_roles import ForgeIRDesigner

        case = self._case(PLACEMENT_EXAMPLE)
        with self.assertRaises(RoleOutputError) as caught:
            ForgeIRDesigner().parse(
                case["answer"], requirements=_requirements(case),
                intent=_intent(case), brief=PlacementInWords.L_BRIEF,
                document_id="", project_id="", answers={})
        self.assertIn("shelf bracket", " ".join(caught.exception.problems))


class APieceTheDesignNeverBuilt(unittest.TestCase):
    """The L-bracket answered twice with its base and no upright."""

    CASE = "l_bracket_without_its_upright"

    def test_the_missing_piece_is_named_first(self) -> None:
        from forge_roles.base import RoleOutputError

        with self.assertRaises(RoleOutputError) as caught:
            _design(_load(self.CASE))
        first = caught.exception.problems[0]
        self.assertIn("Nothing in it is the `upright`", first)
        self.assertIn('"lies": "standing"', first)
        self.assertIn('"on": "base_plate", "at": "back_end"', first)

    def test_a_whole_design_is_not_told_so(self) -> None:
        for name in ("l_bracket_upright_lying_flat",
                     "l_bracket_both_plates_standing"):
            report = _verify(_design(_load(name)))
            self.assertEqual(_not_passing(report), {}, name)

    def test_a_block_carved_into_shape_is_left_alone(self) -> None:
        from forge_roles.library import _pieces_the_design_left_out

        component = {"features": [
            {"id": "block", "kind": "box"}, {"id": "cut", "kind": "box"},
            {"id": "body", "kind": "subtract", "inputs": ["block", "cut"]}]}
        self.assertEqual(_pieces_the_design_left_out(
            component, PlacementInWords.L_BRIEF), [])


class EveryFigureWithItsWords(unittest.TestCase):
    """The requirements engineer is shown each figure where the brief says it.

    Run 20260929T184133: shown `20 mm` and `25 mm` bare, the first answer
    left out the holes' spacing and offset, and cost a three-minute round."""

    def test_each_occurrence_with_its_words(self) -> None:
        from forge_roles.library import _each_figure_where_the_brief_says_it

        lines = _each_figure_where_the_brief_says_it(PlacementInWords.L_BRIEF)
        self.assertEqual(len(lines), 10)
        self.assertTrue(any("20 mm apart across its width" in l for l in lines))
        self.assertTrue(any("25 mm from the front end" in l for l in lines))
        self.assertTrue(any("25 mm above the bottom" in l for l in lines))

    def test_the_prompt_carries_them(self) -> None:
        from forge_roles import RequirementsEngineer
        from forge_roles.library import Intent

        messages = RequirementsEngineer().build_messages(
            brief=PlacementInWords.L_BRIEF, intent=Intent(
                summary="", part_kind="", stated=(), implied=(), unstated=()))
        text = messages[0].content
        self.assertIn("places or spaces something", text)
        self.assertIn("25 mm above the bottom", text)


class HolesCutFromTheWholePart(unittest.TestCase):
    """A hole cut before the solid its line crosses is joined on."""

    def test_the_l_bracket_answer_builds(self) -> None:
        draft = _design(_load("l_bracket_holes_cut_before_the_union"))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.measurements["part"]["open_holes"], 4)
        self.assertTrue(any("cut before it was there" in n for n in draft.notes))

    def _plate_and_post(self, hole_input: str, hole_at, axis=(0, 0, 1)):
        from forge_roles.library import _holes_cut_from_the_whole_part

        component = {"parameters": [], "features": [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [40, 40, 5], "unit": "mm"}}},
            {"id": "post", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 10, "unit": "mm"},
                "height": {"magnitude": 20, "unit": "mm"},
                "origin": {"vector": [20, 20, 5], "unit": "mm"}}},
            {"id": "hole", "kind": "hole", "inputs": [hole_input], "parameters": {
                "diameter": {"magnitude": 4, "unit": "mm"},
                "position": {"vector": list(hole_at), "unit": "mm"},
                "axis": list(axis)}},
            {"id": "body", "kind": "union",
             "inputs": ["hole" if hole_input == "plate" else "plate",
                        "post" if hole_input == "plate" else "hole"]}]}
        return component, _holes_cut_from_the_whole_part(component, None)

    def test_a_bore_cut_in_the_post_alone_is_cut_through_both(self) -> None:
        component, notes = self._plate_and_post("post", (20, 20, 10))
        self.assertTrue(notes)
        self.assertEqual([f["id"] for f in component["features"]],
                         ["plate", "post", "body", "hole"])
        self.assertEqual(component["features"][3]["inputs"], ["body"])

    def test_a_hole_cut_where_its_solid_is_is_left_alone(self) -> None:
        component, notes = self._plate_and_post("plate", (5, 5, 2))
        self.assertEqual(notes, [])
        self.assertEqual(component["features"][2]["inputs"], ["plate"])

    def test_a_hole_in_the_wrong_place_is_not_rewired(self) -> None:
        component, notes = self._plate_and_post("plate", (60, 60, 2))
        self.assertEqual(notes, [])


class HolePositionsTheBriefStates(unittest.TestCase):
    """Run 20260929T195704: the requirements engineer's first answer, again,
    carried every size of the L-bracket and neither the holes' 20 mm spacing
    nor their 25 mm offset -- three runs out of three, three and a half
    minutes a round to be sent back for it."""

    FIRST_ANSWER = [
        _stated("REQ_WIDTH", "width", 40), _stated("REQ_THICKNESS", "thickness", 5),
        _stated("REQ_BASE_LENGTH", "base_length", 50),
        _stated("REQ_UPRIGHT_HEIGHT", "upright_height", 40),
        dict(_stated("REQ_BASE_HOLE_COUNT", "x", 2, ""),
             measurement="feature_count:hole:base"),
        dict(_stated("REQ_UPRIGHT_HOLE_COUNT", "x", 2, ""),
             measurement="feature_count:hole:upright")]

    def _parse(self, requirements):
        from forge_roles import RequirementsEngineer

        return RequirementsEngineer().parse(
            {"risk_class": "low", "requirements": requirements,
             "assumptions": [], "unknowns": []}, brief=PlacementInWords.L_BRIEF)

    def test_the_first_answer_is_no_longer_sent_back(self) -> None:
        record = self._parse([dict(r) for r in self.FIRST_ANSWER])
        carried = {r["measurement"]: r["threshold"]["magnitude"]
                   for r in record.requirements}
        self.assertEqual(carried["parameter:base_hole_spacing"], 20)
        self.assertEqual(carried["parameter:base_hole_offset"], 25)
        self.assertEqual(carried["parameter:upright_hole_spacing"], 20)
        self.assertEqual(carried["parameter:upright_hole_offset"], 25)

    def test_figures_the_model_carried_are_not_added_twice(self) -> None:
        full = [dict(r) for r in self.FIRST_ANSWER] + [
            _stated("REQ_S", "hole_distance", 20),
            _stated("REQ_O", "hole_center_distance_base", 25)]
        record = self._parse(full)
        self.assertFalse(any("hole_spacing" in r["measurement"]
                             or "hole_offset" in r["measurement"]
                             for r in record.requirements))


class TheHubAboveACentreWrittenFlange(unittest.TestCase):
    """Run 20260929T214308: the flange's origin written as its centre and the
    hub's as the flange plus the hub's whole height -- the hub 12 mm in the
    air, the part in two pieces, and the analyst's repair deleting a hole."""

    CASE = "hub_floating_above_a_centre_written_flange"

    def test_it_now_builds_the_hub(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.measurements["part"]["open_holes"], 4)
        # Hub on the flange's top face, the bore through both, not above.
        self.assertEqual(_inside(report, [(15, 0, 7), (8, 0, 10), (8, 0, 23.5)]),
                         [True, True, True])
        self.assertEqual(_inside(report, [(8, 0, 24.5), (0, 0, 12),
                                          (19, 0, 6)]), [False] * 3)

    def test_a_piece_already_on_top_is_left_where_it_is(self) -> None:
        from forge_roles.library import _pieces_stacked_as_the_brief_says

        brief = _load(self.CASE)["brief"]
        component = {"parameters": [], "features": [
            {"id": "flange", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 50, "unit": "mm"},
                "height": {"magnitude": 6, "unit": "mm"}}},
            {"id": "hub", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 25, "unit": "mm"},
                "height": {"magnitude": 15, "unit": "mm"},
                "origin": {"vector": [0, 0, 6], "unit": "mm"}}},
            {"id": "body", "kind": "union", "inputs": ["flange", "hub"]}]}
        self.assertEqual(_pieces_stacked_as_the_brief_says(
            component, None, brief), [])


class AClaimOnAFigureNobodyWrote(unittest.TestCase):
    """Run 20260929T224332: "halfway along the length" written as a claim of
    0.5 with no unit. Sent back twice, returned twice, and the collar --
    built correctly on every other run -- ended with no part at all."""

    CASE = "collar_requirements_with_a_fraction"

    def test_the_answer_is_accepted_without_it(self) -> None:
        from forge_roles import RequirementsEngineer

        case = _load(self.CASE)
        record = RequirementsEngineer().parse(
            case["requirements_answer"], brief=case["brief"])
        ids = {r["id"] for r in record.requirements}
        self.assertNotIn("REQ_SET_SCREW_HOLE_POSITION", ids)
        self.assertIn("REQ_OUTER_DIAMETER", ids)
        self.assertTrue(any("dropped REQ_SET_SCREW_HOLE_POSITION" in n
                            for n in record.notes))

    def test_every_collar_answer_still_builds_against_it(self) -> None:
        from forge_roles import ForgeIRDesigner, RequirementsEngineer

        case = _load(self.CASE)
        record = RequirementsEngineer().parse(
            case["requirements_answer"], brief=case["brief"])
        for name in ("collar_correct", "collar_without_its_bore",
                     "collar_drawn_as_one_cylinder"):
            with self.subTest(name=name):
                answer = _load(name)
                draft = ForgeIRDesigner().parse(
                    answer["answer"], requirements=record,
                    intent=_intent(answer), brief=case["brief"],
                    document_id="", project_id="", answers={})
                report = _verify(draft)
                self.assertEqual(_not_passing(report), {})
                self.assertEqual(report.measurements["part"]["open_holes"], 3)

    def test_a_malformed_claim_on_a_stated_figure_still_goes_back(self) -> None:
        from forge_roles import RequirementsEngineer
        from forge_roles.base import RoleOutputError

        case = _load(self.CASE)
        answer = json.loads(json.dumps(case["requirements_answer"]))
        answer["requirements"]["dimensions"][0]["threshold"]["unit"] = ""
        with self.assertRaises(RoleOutputError) as caught:
            RequirementsEngineer().parse(answer, brief=case["brief"])
        self.assertIn("empty `unit`", " ".join(caught.exception.problems))


class TheRectangleBoundAsASpacingAndADepth(unittest.TestCase):
    """Run 20260930T172446: "centres on a 56 mm by 36 mm rectangle" carried
    as `hole_spacing` = 56 and `hole_depth` = 36 -- a 36 mm deep hole through
    a 4 mm plate. The designer was told to declare both, returned the same
    corner holes twice, and the run ended with no part."""

    CASE = "plate_rectangle_bound_as_spacing_and_depth"

    def test_the_record_names_the_rectangle(self) -> None:
        record = _requirements(_load(self.CASE))
        carried = {r["measurement"]: r["threshold"]["magnitude"]
                   for r in record.requirements}
        self.assertEqual(carried["parameter:hole_centres_length"], 56)
        self.assertEqual(carried["parameter:hole_centres_width"], 36)
        self.assertNotIn("parameter:hole_depth", carried)

    def test_the_answer_now_builds_the_plate(self) -> None:
        report = _verify(_design(_load(self.CASE)))
        self.assertEqual(_not_passing(report), {})
        centres = sorted((round(h["centre_mm"][0], 2), round(h["centre_mm"][1], 2))
                         for h in report.measurements["part"]["holes"]
                         if h["present"])
        self.assertEqual(centres, [(-28, -18), (-28, 18), (28, -18), (28, 18)])

    def test_a_plate_side_with_the_same_figure_is_not_renamed(self) -> None:
        from forge_roles.library import _a_hole_rectangle_named_as_what_it_is

        requirements = [_stated("W", "plate_width", 36),
                        _stated("S", "spacing_y", 36)]
        _a_hole_rectangle_named_as_what_it_is(_load(self.CASE)["brief"],
                                              requirements)
        self.assertEqual(requirements[0]["measurement"], "parameter:plate_width")


class SalvageSeesTheSettledDesign(unittest.TestCase):
    """The salvage asked which parameters a design declares of the answer as
    written -- before Forge declared the names its features already read.
    A design that declared nothing had every claim unbound, the re-parse
    failed, and the run ended with no part."""

    def test_a_design_that_declares_nothing_is_salvaged(self) -> None:
        from unittest import mock

        from forge_roles import ForgeIRDesigner
        from forge_roles.base import RoleOutputError

        case = _load("plate_rectangle_bound_as_spacing_and_depth")
        with mock.patch(
                "forge_roles.library._a_hole_rectangle_named_as_what_it_is",
                return_value=[]):
            record = _requirements(case)
            inputs = dict(requirements=record, intent=_intent(case),
                          brief=case["brief"], document_id="", project_id="",
                          answers={})
            role = ForgeIRDesigner()
            with self.assertRaises(RoleOutputError) as caught:
                role.parse(json.loads(json.dumps(case["answer"])), **inputs)
            draft = role.salvage(json.loads(json.dumps(case["answer"])),
                                 caught.exception.problems, **inputs)
        self.assertIsNotNone(draft)
        self.assertTrue(any("lost its binding" in n for n in draft.notes))
        bound = {r["id"]: r.get("measurement")
                 for r in draft.payload["requirements"]}
        # Only the two claims nothing can read lose their binding.
        self.assertEqual(bound["REQ_PLATE_LENGTH"], "parameter:plate_length")
        self.assertIsNone(bound["REQ_HOLE_DEPTH"])
        self.assertIsNone(bound["REQ_HOLE_SPACING"])


class TheRectangleDrawnAsASlabWithAPort(unittest.TestCase):
    """Run 20260930T201916: the rectangle the holes' centres lie on drawn as
    a box `[rectangle_length, rectangle_width, plate_thickness]`, with a
    `bore` port on it, the four holes each cut from the plate and joined back
    together by the union that welded the slab on."""

    CASE = "plate_rectangle_drawn_as_a_slab_with_a_port"

    def test_it_now_builds_the_plate(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        centres = sorted((round(h["centre_mm"][0], 2), round(h["centre_mm"][1], 2))
                         for h in report.measurements["part"]["holes"]
                         if h["present"])
        self.assertEqual(centres, [(-28, -18), (-28, 18), (28, -18), (28, 18)])
        ids = {f["id"] for f in draft.payload["components"][0]["features"]}
        self.assertNotIn("rectangle", ids)
        ports = {i["id"] for i in draft.payload["components"][0]["interfaces"]}
        self.assertNotIn("rectangle_port", ports)
        self.assertEqual(len(ports), 4)

    def test_holes_joined_back_together_are_chained(self) -> None:
        from forge_roles.library import _holes_cut_from_the_whole_part

        def hole(i, x):
            return {"id": i, "kind": "hole", "inputs": ["plate"], "parameters": {
                "diameter": {"magnitude": 4, "unit": "mm"},
                "position": {"vector": [x, 5, 2], "unit": "mm"},
                "axis": [0, 0, 1]}}
        component = {"parameters": [], "features": [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [40, 10, 4], "unit": "mm"}}},
            hole("a", 10), hole("b", 30),
            {"id": "body", "kind": "union", "inputs": ["a", "b"]}]}
        notes = _holes_cut_from_the_whole_part(component, None)
        self.assertTrue(notes)
        self.assertEqual([(f["id"], f.get("inputs")) for f in
                          component["features"]],
                         [("plate", None), ("a", ["plate"]), ("b", ["a"])])


class OneBoreWrittenAsTwoHoles(unittest.TestCase):
    """Run 20261001T194600: "a 5 mm hole runs all the way through the post
    and the plate" written as `base_hole` at the plate's mid-height and
    `post_hole` at the post's, both down Z on the centre line, and the two
    3 mm mounting holes left out. The decoder refused the pair as one hole;
    Forge re-aimed both sideways, which made them two cross holes, and the
    run ended with no part."""

    CASE = "spacer_one_bore_written_as_two_holes"

    def test_it_now_builds_the_spacer(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        holes = sorted((h["diameter_mm"], round(h["centre_mm"][0], 2),
                        round(h["centre_mm"][1], 2))
                       for h in report.measurements["part"]["holes"]
                       if h["present"])
        self.assertEqual(holes, [(3.0, -10.0, 0.0), (3.0, 10.0, 0.0),
                                 (5.0, 0.0, 0.0)])
        self.assertFalse(any("Re-aimed" in n or "re-aimed" in n
                             for n in draft.notes))

    def test_two_holes_meant_apart_along_their_axis_are_still_re_aimed(
            self) -> None:
        from forge_roles.library import _re_aim_holes_that_became_one_line

        def hole(i, x):
            return {"id": i, "kind": "hole", "parameters": {
                "diameter": {"magnitude": 3, "unit": "mm"},
                "position": {"vector": [x, 0, 2], "unit": "mm"},
                "axis": [1, 0, 0]}}
        features = [{"id": "plate", "kind": "box", "parameters": {
            "size": {"vector": [30, 30, 4], "unit": "mm"}, "centered": True}},
            hole("a", "spacing / 2"), hole("b", "-spacing / 2")]
        notes = _re_aim_holes_that_became_one_line(features, {"features": features})
        self.assertTrue(notes)
        self.assertEqual(features[1]["parameters"]["axis"], [0.0, 0.0, 1.0])


class TheLoadedCantilever(unittest.TestCase):
    """Run 20261002T124224, prompt 10: "An aluminium cantilever bracket: a
    60 mm long, 20 mm wide, 6 mm thick bar fixed at one end by two 5 mm bolt
    holes 15 mm apart near that end. A load of 150 N pushes straight down on
    the free end. It must have a safety factor of at least 2."

    Four things stood between it and a part: both bolt holes drawn at one
    point; the 15 mm spacing carried by nothing; the load written in words
    with no value; and the safety factor bound to bearing at the holes --
    about 55 here -- instead of the bending at the support, which is what a
    cantilever's margin is."""

    CASE = "cantilever_bolt_holes_at_one_point"

    def test_the_record_carries_what_the_brief_states(self) -> None:
        record = _requirements(_load(self.CASE))
        bound = {r["measurement"]: r["threshold"]["magnitude"]
                 for r in record.requirements}
        self.assertEqual(bound["parameter:hole_spacing"], 15)
        self.assertEqual(bound["safety_factor:bending"], 2)
        self.assertNotIn("safety_factor:bearing", bound)
        load = next(a for a in record.assumptions
                    if a["id"] == "ASM_DESIGN_LOAD")
        self.assertEqual(load["value"], {"magnitude": 150.0, "unit": "N"})
        grade = next(a for a in record.assumptions
                     if a["id"] == "ASM_MATERIAL_GRADE")
        self.assertIn("aluminium_6061_t6", grade["statement"])
        self.assertFalse(grade["approved"])

    def test_it_builds_the_bar_and_computes_its_bending_margin(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        # Every claim measured and met; the run is held only for the user to
        # approve the load and the grade.
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "BLOCKED")
        centres = sorted((round(h["centre_mm"][0], 2), round(h["centre_mm"][1], 2))
                         for h in report.measurements["part"]["holes"]
                         if h["present"])
        self.assertEqual(centres, [(7.5, 0.0), (22.5, 0.0)])
        margin = next(g for g in report.gate_results
                      if g.gate.identifier == "REQ_SF_BEARING")
        self.assertEqual(margin.status.value, "PASS")
        detail = margin.evidence.detail
        self.assertEqual(detail["arm_mm"], 37.5)
        self.assertEqual(detail["section_mm"], [15.0, 6.0])
        # 150 N x 37.5 mm on a 15 x 6 section: 62.5 MPa, against 6061-T6.
        self.assertIn("62.5 MPa", detail["demand"])

    def test_approved_it_releases(self) -> None:
        from forge_ir import Document
        from forge_pipeline import verify_component

        draft = _design(_load(self.CASE))
        payload = json.loads(json.dumps(draft.payload))
        for assumption in payload["assumptions"]:
            assumption["approved"] = True
        document = Document.from_json(json.dumps(payload))
        report = verify_component(document, document.components[0],
                                  measurement_depth=6)
        self.assertEqual(report.overall_status.value, "PASS")

    def test_the_same_bar_in_pla_is_too_weak_and_says_so(self) -> None:
        case = _load(self.CASE)
        case["brief"] = case["brief"].replace("An aluminium", "A PLA")
        report = _verify(_design(case))
        margin = next(g for g in report.gate_results
                      if g.gate.identifier == "REQ_SF_BEARING")
        self.assertEqual(margin.status.value, "FAIL")

    def test_a_brief_with_a_pin_keeps_its_bearing_margin(self) -> None:
        from forge_roles.library import _the_margin_the_brief_means

        requirements = [dict(_stated("SF", "x", 2, ""),
                             measurement="safety_factor:bearing",
                             comparison="at_least")]
        notes = _the_margin_the_brief_means(
            "A bracket fixed at one end with a 10 mm bore for a pin at the "
            "free end, carrying 300 N. Safety factor of at least 2.",
            requirements)
        self.assertEqual(notes, [])
        self.assertEqual(requirements[0]["measurement"], "safety_factor:bearing")

    def test_bending_is_not_computed_for_what_is_not_a_bar(self) -> None:
        from forge_pipeline.measure import _bending_of_a_bar
        from forge_analysis import lookup
        from forge_kernel import Compiler
        from forge_units import Q

        draft = _design(_load("l_bracket_holes_cut_before_the_union"))
        component = draft.document.components[0]
        part = Compiler().compile_component(component, validate_geometry=False)
        result = _bending_of_a_bar(component, part, Q(150, "N"),
                                   lookup("pla_fdm"))
        self.assertIsNone(result.value)
        self.assertIn("straight bar", result.blocked_reason)


class TheCantileverWithItsLoadDrawnAsASolid(unittest.TestCase):
    """Run 20261002T150340: prompt 10 again, a different answer. The load
    drawn as a cylinder "150 N" tall with a bore port on it, both bolt holes
    at one point, their diameter a name nothing declared."""

    CASE = "cantilever_with_its_load_drawn_as_a_solid"

    def test_it_builds_the_bar(self) -> None:
        draft = _design(_load(self.CASE))
        ids = {f["id"] for f in draft.payload["components"][0]["features"]}
        self.assertNotIn("load", ids)
        self.assertEqual(draft.payload["components"][0].get("interfaces"), [])
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        centres = sorted(round(h["centre_mm"][0], 2)
                         for h in report.measurements["part"]["holes"]
                         if h["present"])
        self.assertEqual(centres, [7.5, 22.5])

    def test_a_size_in_millimetres_is_not_taken_for_a_load(self) -> None:
        from forge_roles.library import (
            _a_solid_sized_by_something_that_is_not_a_length)

        component = {"features": [{"id": "post", "kind": "cylinder",
                                   "parameters": {
                                       "diameter": {"magnitude": 5, "unit": "mm"},
                                       "height": {"magnitude": 15, "unit": "mm"}}}]}
        self.assertEqual(
            _a_solid_sized_by_something_that_is_not_a_length(component), [])
        self.assertEqual(len(component["features"]), 1)

    def test_a_hole_size_of_two_counted_sizes_is_not_guessed(self) -> None:
        from forge_roles.library import (
            RequirementSet, _a_hole_size_named_and_never_declared)

        record = RequirementSet(requirements=(
            dict(_stated("A", "x", 2, ""), measurement="holes_of_diameter:3"),
            dict(_stated("B", "x", 2, ""), measurement="holes_of_diameter:5")),
            assumptions=(), unknowns=())
        hole = lambda i: {"id": i, "kind": "hole", "parameters": {  # noqa: E731
            "diameter": {"expression": "d", "unit": "mm"}}}
        component = {"parameters": [], "features": [hole("a"), hole("b")]}
        self.assertEqual(_a_hole_size_named_and_never_declared(
            component, record), [])


class TheCantileverWithItsBoltHolesWrittenTwice(unittest.TestCase):
    """Run 20261002T215613: prompt 10 a third time. Four bolt holes -- the
    two the brief asks for, each written twice -- all at one point, placed
    with `place` words that put one of each pair off the bar."""

    CASE = "cantilever_bolt_holes_written_twice"

    def test_it_builds_the_bar_with_two_holes(self) -> None:
        draft = _design(_load(self.CASE))
        holes = [f["id"] for f in draft.payload["components"][0]["features"]
                 if f["kind"] == "hole"]
        self.assertEqual(len(holes), 2)
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        centres = sorted(round(h["centre_mm"][0], 2)
                         for h in report.measurements["part"]["holes"]
                         if h["present"])
        self.assertEqual(centres, [7.5, 22.5])

    def test_copies_stop_at_the_count_the_record_wants(self) -> None:
        from forge_roles.library import RequirementSet, _one_hole_written_twice

        record = RequirementSet(requirements=(
            dict(_stated("A", "x", 2, ""), measurement="holes_of_diameter:5"),),
            assumptions=(), unknowns=())
        hole = lambda i: {"id": i, "kind": "hole", "parameters": {  # noqa: E731
            "diameter": {"magnitude": 5, "unit": "mm"},
            "position": {"vector": [0, 0, 0], "unit": "mm"}}}
        component = {"parameters": [], "features": [
            hole("a"), hole("b"), hole("c")]}
        _one_hole_written_twice(component, record)
        self.assertEqual(len(component["features"]), 2)
        self.assertEqual(component["features"][0]["id"], "a")

    def test_the_labels_read_as_sentences(self) -> None:
        record = _requirements(_load("cantilever_bolt_holes_at_one_point"))
        spacing = next(r for r in record.requirements
                       if r["measurement"] == "parameter:hole_spacing")
        self.assertEqual(spacing["statement"], "The holes shall be 15 mm apart.")
        grade = next(a for a in record.assumptions
                     if a["id"] == "ASM_MATERIAL_GRADE")
        self.assertIn("6061 T6 (`aluminium_6061_t6`)", grade["statement"])


class TheFalsePassesTheSuiteFound(unittest.TestCase):
    """Three runs that completed, released, and were the wrong part.

    Graded against the validation suite's geometry, three stored answers
    passed every gate Forge had while being built wrong: an L-bracket whose
    upright was as long as the base instead of as wide as the part, and two
    spacers -- one with its base standing on its edge, one with its base as
    thick as the fillet. Each is now the part the brief describes, and the
    record measures what would have caught it.
    """

    def _part(self, name: str):
        draft = _design(_load(name))
        report = _verify(draft)
        return draft, report

    def assertEnvelope(self, report, wanted: list[float]) -> None:
        # The envelope is measured off the tessellated part: to within the
        # suite's own tolerance, a millimetre or 3%.
        got = sorted(report.measurements["part"]["envelope_mm"])
        for g, w in zip(got, sorted(wanted)):
            self.assertAlmostEqual(g, w, delta=max(1.0, 0.03 * w),
                                   msg=f"{got} vs {wanted}")

    def test_the_l_bracket_is_as_wide_as_the_brief_says(self) -> None:
        draft, report = self._part("l_bracket_upright_as_long_as_the_base")
        self.assertEqual(_not_passing(report), {})
        self.assertEnvelope(report, [40, 40, 50])
        claims = {r.identifier: str(r.measurement)
                  for r in draft.document.requirements}
        # The record's bare `length` claim checks the base leg's length,
        # the one dimension of that name and figure the design has.
        self.assertEqual(claims["REQ_LENGTH"], "parameter:base_leg_length")

    def test_the_spacer_on_its_edge_lies_flat(self) -> None:
        _, report = self._part("spacer_base_standing_on_its_edge")
        self.assertEqual(_not_passing(report), {})
        self.assertEnvelope(report, [14, 30, 30])

    def test_the_spacer_a_fillet_thick_is_its_plate_thick(self) -> None:
        draft, report = self._part("spacer_base_a_fillet_thick")
        self.assertEqual(_not_passing(report), {})
        self.assertEnvelope(report, [14, 30, 30])
        base = next(f for f in draft.payload["components"][0]["features"]
                    if f["id"] == "base")
        self.assertEqual(base["parameters"]["size"]["vector"],
                         ["base_width", "base_width", "base_height"])

    def test_the_record_measures_how_tall_the_stack_is(self) -> None:
        record = _requirements(_load("spacer_base_a_fillet_thick"))
        stacked = [r for r in record.requirements
                   if r["id"] == "REQ_STACKED_HEIGHT"]
        self.assertEqual(len(stacked), 1)
        self.assertEqual(stacked[0]["measurement"], "bounding_box_z")
        self.assertEqual(stacked[0]["threshold"]["magnitude"], 14.0)

    def test_a_stack_with_more_on_it_is_not_summed(self) -> None:
        from forge_roles.library import (
            _the_height_of_a_stack_the_brief_describes as stack)

        for brief in (
            "A PLA stand: a base plate 60 mm long, 40 mm wide and 6 mm "
            "thick, with a round post 20 mm across and 30 mm tall standing "
            "on top of it, centred. A 12 mm ball sits on top of the post.",
            "A base plate 60 mm long, 40 mm wide and 6 mm thick, with a "
            "round post 20 mm across and 30 mm tall standing on top of it. "
            "A peg 10 mm long hangs below the plate.",
            "The base is a 30 mm square plate 4 mm thick. A post 10 mm tall "
            "stands in the middle of it. The part is 20 mm tall overall.",
        ):
            requirements: list = []
            stack(brief, requirements)
            self.assertEqual(requirements, [], brief)
        requirements = []
        stack("A PLA stand: a base plate 60 mm long, 40 mm wide and 6 mm "
              "thick, with a round post 20 mm across and 30 mm tall standing "
              "on top of it, centred.", requirements)
        self.assertEqual(requirements[0]["threshold"]["magnitude"], 36.0)

    def test_the_layout_reads_plates_posts_and_what_is_cut(self) -> None:
        from forge_roles.library import _the_layout_the_brief_describes

        self.assertEqual(_the_layout_the_brief_describes(
            "A machined aluminium mounting bracket. The base is a 60 mm by "
            "40 mm plate 8 mm thick. A 20 mm diameter boss 15 mm tall rises "
            "from the middle, with a 3 mm fillet at its root. Four 6 mm "
            "bolt holes pass through the plate."),
            {"base": {"lies": "flat"},
             "boss": {"lies": "standing", "on": "base", "ends": ["top"]}})
        # Holes are cut from the part; they are never pieces of it.
        layout = _the_layout_the_brief_describes(
            "A PLA L-bracket 40 mm wide, made of 5 mm thick plate. The base "
            "leg is 50 mm long and lies flat; the upright leg stands on the "
            "back end of the base and is 40 mm tall overall. Two 5 mm holes "
            "pass through the upright, 20 mm apart across its width.")
        self.assertEqual(set(layout), {"base", "upright"})


class TheRowMeasuredFromThePlatesCorner(unittest.TestCase):
    """Run 20260915T120842: the mounting holes at `plate_width / 2 -/+
    spacing / 2` on a plate built about its middle -- one in the post's
    wall, one off the part."""

    CASE = "spacer_holes_measured_from_the_corner"

    def test_the_row_is_centred_on_the_plate(self) -> None:
        draft = _design(_load(self.CASE))
        holes = {f["id"]: f["parameters"]["position"]["vector"][0]
                 for f in draft.payload["components"][0]["features"]
                 if f["id"].startswith("mounting_hole")}
        self.assertEqual(holes, {"mounting_hole_1": "-mounting_hole_spacing / 2",
                                 "mounting_hole_2": "mounting_hole_spacing / 2"})
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})

    def test_a_row_that_cuts_the_part_is_left_where_it_is(self) -> None:
        from forge_roles.library import _a_row_centred_on_an_edge

        hole = lambda i, x: {"id": i, "kind": "hole", "inputs": ["plate"],  # noqa: E731
                             "parameters": {
                                 "diameter": {"magnitude": 3, "unit": "mm"},
                                 "position": {"vector": [x, 0, 0], "unit": "mm"},
                                 "axis": [0, 0, 1]}}
        component = {"parameters": [], "features": [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"},
                "centered": True}},
            {"id": "tab", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"},
                "origin": {"vector": [15, -15, -2], "unit": "mm"}}},
            {"id": "body", "kind": "union", "inputs": ["plate", "tab"]},
            # Centred on the plate's edge -- where the tab joins it -- and
            # each cutting the part: a row the design meant there, not one
            # measured from a corner.
            hole("a", 10), hole("b", 20)]}
        for h in component["features"][-2:]:
            h["inputs"] = ["body"]
        self.assertEqual(_a_row_centred_on_an_edge(component, None), [])

    def test_a_union_of_a_chained_row_is_the_chain_s_end(self) -> None:
        """The same answer with the holes' inputs left out: Forge wires
        each to the one before, and the union of that chain is refilled."""
        import copy

        case = copy.deepcopy(_load(self.CASE))
        for f in case["answer"]["document"]["components"][0]["features"]:
            if f["kind"] == "hole":
                f.pop("inputs", None)
        draft = _design(case)
        features = draft.payload["components"][0]["features"]
        self.assertNotIn("body_2", [f["id"] for f in features])
        self.assertEqual(_not_passing(_verify(draft)), {})


class ThePairDrawnAtTheWrongDistance(unittest.TestCase):
    """Run 20260915T172355: "Two 3 mm mounting holes ... 20 mm apart",
    drawn at x = +/-15 on a 30 mm plate, `mounting_hole_spacing` read by
    nothing."""

    CASE = "spacer_holes_at_the_plate_edges"

    def test_the_pair_is_the_brief_s_distance_apart(self) -> None:
        draft = _design(_load(self.CASE))
        spots = sorted(
            f["parameters"]["position"]["vector"][0]
            for f in draft.payload["components"][0]["features"]
            if f["id"].startswith("mounting_hole"))
        self.assertEqual(spots, ["-mounting_hole_spacing / 2",
                                 "mounting_hole_spacing / 2"])
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        centres = sorted(round(h["centre_mm"][0], 2)
                         for h in report.measurements["part"]["holes"]
                         if h["present"] and h["diameter_mm"] < 4)
        self.assertEqual(centres, [-10.0, 10.0])


class TheCubeWithItsFacesCounted(unittest.TestCase):
    """Run 20261003T090441: "A 30 mm cube in PLA." Refused twice.

    The record counted six faces -- `feature_count:face:top` and five more,
    each at least 1 -- and nothing measured the cube. Forge unbound the
    counts it could not read, then told the model their empty unit was
    wrong and to "bind them to `feature_count:`", which they already were;
    the model, reasonably, sent the same answer back.
    """

    CASE = "cube_with_its_faces_counted"

    def test_the_record_measures_the_cube_and_not_its_faces(self) -> None:
        record = _requirements(_load(self.CASE))
        claims = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in record.requirements}
        for axis in "xyz":
            self.assertEqual(claims[f"bounding_box_{axis}"], 30.0)
        self.assertFalse([m for m in claims if "face" in m])
        self.assertFalse([m for m in claims if m.startswith("safety_factor")])
        self.assertEqual(record.assumptions, ())

    def test_a_cube_built_to_it_passes(self) -> None:
        report = _verify(_design(_load(self.CASE)))
        self.assertEqual(_not_passing(report), {})

    def test_a_count_forge_unbinds_is_not_sent_back_for_its_unit(self) -> None:
        """A count of slots the brief asks for, of no kind Forge knows: kept
        and reported NOT_TESTED, and not refused over its empty unit."""
        from forge_roles import RequirementsEngineer

        answer = {"risk_class": "low", "assumptions": [], "unknowns": [],
                  "requirements": {
                      "whole_part": {"bounding_box_x": {
                          "statement": "60 mm long.", "comparison": "equals",
                          "threshold": {"magnitude": 60.0, "unit": "mm"}}},
                      "counts": [{
                          "feature_kind": "groove", "tag": "grip",
                          "statement": "Two grooves.", "comparison": "equals",
                          "threshold": {"magnitude": 2, "unit": ""}}]}}
        record = RequirementsEngineer().parse(
            answer, brief="A PLA handle 60 mm long with two grooves for grip.")
        kept = [r for r in record.requirements if "GROOVE" in r["id"]]
        self.assertEqual(len(kept), 1)
        self.assertNotIn("measurement", kept[0])

    def test_one_figure_sizes_a_ball_every_way_and_not_two_cubes(self) -> None:
        from forge_roles.library import _the_part_s_own_size_measured as measure

        claims: list = []
        measure("A 40 mm PLA ball with a 10 mm hole drilled straight through "
                "its centre.", claims)
        self.assertEqual(sorted(c["measurement"] for c in claims),
                         ["bounding_box_x", "bounding_box_y", "bounding_box_z"])
        for brief in ("Two separate PLA cubes, 20 mm each, 10 mm apart.",
                      "A 30 mm cube with a 10 mm post sticking out of one "
                      "face.",
                      "An abstract PLA shape: a 30 mm cube and a 36 mm sphere "
                      "sharing the same centre."):
            claims = []
            measure(brief, claims)
            self.assertEqual(claims, [], brief)


class ARepairForgeMadeIsNeverWhatGetsADesignRefused(unittest.TestCase):
    """The class behind the cube: Forge refusing an answer over its own edit.

    Every repair is written for one reading of a mistake. On a design that
    did not make that mistake, the repair is the mistake -- and the model,
    told to fix something it never wrote, returns the same answer. When the
    settled design is refused, each repair that changed it is taken back in
    turn; if the design validates without one, that is the design.
    """

    CASE = "spacer_base_a_fillet_thick"

    def test_a_repair_that_breaks_the_design_is_taken_back(self) -> None:
        from unittest import mock

        def _a_row_centred_on_an_edge(component, requirements):  # noqa: ANN001
            # A repair gone wrong: it sizes a hole by a name nobody declares.
            for feature in component["features"]:
                if feature["kind"] == "hole":
                    feature["parameters"]["diameter"] = {
                        "expression": "nobody_declared_this", "unit": "mm"}
                    return ["moved a hole"]
            return []

        with mock.patch("forge_roles.library._a_row_centred_on_an_edge",
                        new=_a_row_centred_on_an_edge):
            draft = _design(_load(self.CASE))
        self.assertTrue(any("took back its own repair `_a_row_centred_on_an_edge`"
                            in n for n in draft.notes))
        self.assertNotIn("nobody_declared_this", json.dumps(draft.payload))
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_the_model_s_own_mistake_still_goes_back_to_it(self) -> None:
        import copy

        from forge_roles import RoleOutputError

        case = copy.deepcopy(_load(self.CASE))
        hole = next(f for f in case["answer"]["document"]["components"][0][
            "features"] if f["kind"] == "hole")
        hole["parameters"]["diameter"] = {"expression": "a_name_never_declared",
                                          "unit": "mm"}
        with self.assertRaises(RoleOutputError) as caught:
            _design(case)
        # The hole reads a name of the model's own, which Forge declares from
        # the record's count -- and the record's own `hole_diameter` is then
        # read by nothing. That is the model's to fix, and it is told so.
        problems = " ".join(caught.exception.problems)
        self.assertIn("`hole_diameter`", problems)
        self.assertNotIn("took back", problems)


class TheHollowCubeOpenOnTheLeft(unittest.TestCase):
    """Run 20261003T102400: "A 30 mm cube in PLA, hollow on the inside, with
    the left face of the square missing. Open on the left side."

    No wall was stated, so the designer had nothing to size the space with:
    it drew a 30 x 30 x 0 box and a `subtract` with nothing to cut, and was
    refused three times in nineteen minutes over an arity. The record also
    carried "the cube shall have a left face" -- the opposite of the brief --
    as a count nothing can make.
    """

    CASE = "cube_hollow_open_on_the_left"

    def test_the_record_assumes_a_wall_and_measures_the_open_side(self) -> None:
        record = _requirements(_load(self.CASE))
        claims = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in record.requirements if r.get("measurement")}
        self.assertEqual(claims["wall_thickness:left"], 2.0)
        self.assertEqual(claims["floor_thickness:left"], 2.0)
        self.assertEqual(claims["opening_depth:left"], 28.0)
        self.assertFalse([r for r in record.requirements
                          if "FACE" in r["id"]])
        wall = next(a for a in record.assumptions
                    if a["id"] == "ASM_WALL_THICKNESS")
        # Shown, not held: a guess the user can see and change.
        self.assertEqual((wall["risk"], wall["reversible"]), ("moderate", True))

    def test_the_model_s_answer_builds_the_cube_it_asked_for(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        for got in report.measurements["part"]["envelope_mm"]:
            self.assertAlmostEqual(got, 30.0, delta=1.0)
        self.assertEqual(str(report.measurements["opening_depth:left"]),
                         "28 mm")

    def test_an_open_side_is_read_however_it_is_said(self) -> None:
        from forge_roles.library import _the_side_a_part_is_open_on as side

        for brief, wanted in (
            ("A hollow PLA cube 30 mm, open on the front.", "front"),
            ("A box with the right side missing.", "right"),
            ("A 40 mm box with no back wall.", "back"),
            ("A cube without its bottom face.", "bottom"),
            ("A PLA open-top box.", "top"),
            ("A box open on the left and on the right.", None),
            ("A steel plate with the left edge chamfered.", None),
        ):
            self.assertEqual(side(brief), wanted, brief)

    def test_a_wall_is_only_assumed_where_nothing_else_sizes_it(self) -> None:
        from forge_roles.library import _a_wall_the_brief_leaves_out as wall

        for brief in ("A hollow steel shaft 20 mm across with a 10 mm bore.",
                      "A hollow PLA cube 30 mm with 3 mm walls.",
                      "A box 40 mm with a 36 mm inside width, open on top.",
                      "A hollow PLA tube 30 mm across and 80 mm long."):
            answer: dict = {}
            self.assertIsNone(wall(brief, answer), brief)
            self.assertEqual(answer, {}, brief)


class AContainerOpenOnAnySide(unittest.TestCase):
    """`opening_depth:left` and its siblings, measured on built parts."""

    @staticmethod
    def _report(open_on: str, claims: dict):
        from forge_ir import Document
        from forge_ir.measurements import CONTAINER_SIDES
        from forge_pipeline import verify_component

        axis, sign = CONTAINER_SIDES[open_on]
        size = [26, 26, 26]
        size[axis] = 30
        origin = [0, 0, 0]
        origin[axis] = 2 * sign
        doc = {
            "schema_version": "1.0.0", "name": "c", "revision": 1,
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "document_id": "81936263-0fe7-57cd-ae1a-a6baeb3a0858",
            "project_id": "945dd5ce-6fe3-5ae6-84b5-59f417cafb03",
            "risk_class": "low", "assumptions": [],
            "requirements": [
                {"id": f"R{i}", "statement": "x", "measurement": m,
                 "comparison": "equals",
                 "threshold": {"magnitude": v, "unit": "mm"},
                 "type": "geometric", "verification": "exact_geometry",
                 "strength": "hard", "source": "user", "state": "accepted"}
                for i, (m, v) in enumerate(claims.items())],
            "components": [{"id": "cube", "name": "cube",
                            "material": "pla_fdm", "parameters": [],
                            "interfaces": [], "features": [
                {"id": "outer", "kind": "box", "parameters": {
                    "size": {"vector": [30, 30, 30], "unit": "mm"},
                    "centered": True}},
                {"id": "space", "kind": "box", "parameters": {
                    "size": {"vector": size, "unit": "mm"},
                    "origin": {"vector": origin, "unit": "mm"},
                    "centered": True}},
                {"id": "hollowed", "kind": "subtract",
                 "inputs": ["outer", "space"]}]}]}
        document = Document.from_json(json.dumps(doc))
        return verify_component(document, document.components[0],
                                measurement_depth=6)

    def test_every_side_measures_its_own_opening(self) -> None:
        for side in ("left", "right", "front", "back", "bottom"):
            report = self._report(side, {
                f"wall_thickness:{side}": 2, f"floor_thickness:{side}": 2,
                f"opening_depth:{side}": 28})
            self.assertEqual(_not_passing(report), {}, side)

    def test_the_wrong_side_is_closed(self) -> None:
        report = self._report("left", {"opening_depth:right": 28})
        self.assertEqual(set(_not_passing(report).values()), {"FAIL"})
        self.assertEqual(str(report.measurements["opening_depth:right"]),
                         "0 mm")

    def test_a_side_that_is_no_side_is_refused(self) -> None:
        from forge_ir.measurements import MeasurementError, parse_measurement

        self.assertEqual(parse_measurement("opening_depth:left").argument,
                         "left")
        with self.assertRaises(MeasurementError):
            parse_measurement("opening_depth:sideways")


class TheHollowCubeReleasedSolid(unittest.TestCase):
    """Run 20261003T112602: "A 30 mm cube in PLA, hollow on the inside with
    an open top." Completed, every check green -- and a solid block. With no
    wall stated, the record carried only the cube's size, which a solid
    cube has too."""

    CASE = "cube_hollow_open_top_released_solid"

    def test_the_same_answer_is_now_the_open_box(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(str(report.measurements["opening_depth"]), "28 mm")
        self.assertEqual(str(report.measurements["wall_thickness"]), "2 mm")

    def test_a_solid_cube_can_no_longer_pass_for_it(self) -> None:
        from unittest import mock

        with mock.patch("forge_roles.library._an_open_top_box_left_solid",
                        return_value=[]), mock.patch(
                "forge_roles.library._a_container_built_some_other_way",
                return_value=[]):
            report = _verify(_design(_load(self.CASE)))
        failed = _not_passing(report)
        self.assertEqual(failed.get("REQ_OPEN_TOP"), "FAIL")
        self.assertEqual(failed.get("REQ_WALL_THICKNESS"), "FAIL")


class TheHollowCubeWithItsThicknessSaidPlainly(unittest.TestCase):
    """Run 20261003T114651: "...hollow on the inside, with the left face of
    the square missing. 3mm Thickness Open on the left side."

    Forge read no wall in "3mm Thickness" and assumed 2 mm over the user's
    own 3; the designer drew a 30 x 30 x 3 plate and a `subtract` of a
    `body` that does not exist, and returned it twice.
    """

    CASE = "cube_hollow_open_left_3mm"

    def test_the_user_s_thickness_is_the_wall_and_nothing_is_assumed(self) -> None:
        record = _requirements(_load(self.CASE))
        claims = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in record.requirements if r.get("measurement")}
        self.assertEqual(claims["wall_thickness:left"], 3.0)
        self.assertEqual(claims["floor_thickness:left"], 3.0)
        self.assertEqual(claims["opening_depth:left"], 27.0)
        self.assertEqual(record.assumptions, ())

    def test_the_answer_builds_the_cube_with_3_mm_walls(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(str(report.measurements["wall_thickness:left"]),
                         "3 mm")
        # One name for the 3 mm: the record's `thickness`, read by the space.
        self.assertIn("thickness", json.dumps(
            draft.payload["components"][0]["features"]))

    def test_how_a_hollow_part_s_thickness_is_read(self) -> None:
        from forge_roles.library import _the_container_the_brief_describes as c

        self.assertEqual(c("A hollow cube 30 mm, wall thickness 3 mm.")["wall"],
                         3.0)
        self.assertEqual(c("A hollow cube with a thickness of 2.5 mm.")["wall"],
                         2.5)
        # A plate's thickness is not a wall, and a base's is its floor.
        self.assertEqual(c("A plate 4 mm thick."), {})
        self.assertEqual(c("An open-top box 50 mm with a 3 mm thick base."),
                         {"floor": 3.0, "open_top": True})


class TheHollowCubeDrawnAsPlatesAndHoles(unittest.TestCase):
    """Run 20261003T132456: the record stated the whole hollow cube -- 30
    mm, 3 mm walls, open on the left -- and the design was three 3 mm plates
    and two 30 mm holes. Blocked, honestly, after twenty-six minutes."""

    CASE = "cube_hollow_drawn_as_plates_and_holes"

    def test_the_part_the_record_states_is_built(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(str(report.measurements["opening_depth:left"]),
                         "27 mm")
        self.assertEqual(
            [f["id"] for f in draft.payload["components"][0]["features"]],
            ["body", "cavity", "hollowed"])

    def test_a_brief_that_says_more_is_left_to_the_design(self) -> None:
        import copy

        from forge_roles import RoleOutputError

        case = copy.deepcopy(_load(self.CASE))
        case["brief"] += " A 5 mm hole runs through the right face."
        try:
            draft = _design(case)
        except RoleOutputError:
            return
        self.assertNotIn("cavity", [
            f["id"] for f in draft.payload["components"][0]["features"]])

    def test_the_designer_is_shown_how_to_draw_one(self) -> None:
        from forge_roles import ForgeIRDesigner

        prompt = ForgeIRDesigner().system_prompt()
        self.assertIn("never plates and holes", prompt)


class TheDomeHalfASphere(unittest.TestCase):
    """Run 20261003T152857: "A PLA dome: exactly half of a 50 mm sphere,
    sitting flat side down." Refused twice: the record had `diameter` and
    `height` as parameters only, and nothing measuring the dome."""

    CASE = "dome_half_a_sphere"

    def test_the_record_measures_the_dome(self) -> None:
        record = _requirements(_load(self.CASE))
        claims = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in record.requirements}
        self.assertEqual((claims["bounding_box_x"], claims["bounding_box_y"],
                          claims["bounding_box_z"]), (50.0, 50.0, 25.0))
        self.assertEqual(record.assumptions, ())

    def test_half_a_sphere_passes(self) -> None:
        report = _verify(_design(_load(self.CASE)))
        self.assertEqual(_not_passing(report), {})

    def test_the_whole_sphere_is_cut_to_its_half(self) -> None:
        import copy

        case = copy.deepcopy(_load(self.CASE))
        component = case["answer"]["document"]["components"][0]
        component["features"] = component["features"][:1]
        component["parameters"] = component["parameters"][:1]
        draft = _design(case)
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        envelope = sorted(report.measurements["part"]["envelope_mm"])
        self.assertAlmostEqual(envelope[0], 25.0, delta=1.0)

    def test_how_half_a_sphere_is_said(self) -> None:
        from forge_roles.library import _the_part_s_own_size_measured as measure

        for brief in ("A 40 mm PLA hemisphere.",
                      "A PLA hemisphere 40 mm across.",
                      "A PLA dome: half of a 40 mm ball."):
            claims: list = []
            measure(brief, claims)
            self.assertEqual(
                sorted((c["measurement"], c["threshold"]["magnitude"])
                       for c in claims),
                [("bounding_box_x", 40.0), ("bounding_box_y", 40.0),
                 ("bounding_box_z", 20.0),
                 # Its flat face down: half the 40 mm disc, at least.
                 ("flat_face:bottom", 628.3)], brief)
        # On its side: upright, turned to the right -- every such way is
        # the same part turned about Z.
        claims = []
        measure("A 50 mm dome lying on its side.", claims)
        self.assertEqual(
            sorted((c["measurement"], c["threshold"]["magnitude"])
                   for c in claims),
            [("bounding_box_x", 25.0), ("bounding_box_y", 50.0),
             ("bounding_box_z", 50.0), ("flat_face:right", 981.7)])

    def test_a_bare_dimension_is_measured_when_nothing_else_is(self) -> None:
        from forge_roles import RequirementsEngineer

        answer = {"risk_class": "low", "assumptions": [], "unknowns": [],
                  "requirements": {"dimensions": [{
                      "parameter": "length", "statement": "60 mm long.",
                      "comparison": "equals",
                      "threshold": {"magnitude": 60.0, "unit": "mm"}}]}}
        record = RequirementsEngineer().parse(
            answer, brief="A PLA wand, 60 mm in length, like a lightsaber.")
        self.assertIn("extent_side:60",
                      [r.get("measurement") for r in record.requirements])


class TheDomeReleasedAsASphereAndABox(unittest.TestCase):
    """Run 20261003T203015: released as PASS, a whole 50 mm sphere welded to
    a 50 x 50 x 25 box. Two things let it through: the record's own Y claim
    was 25 -- the model's arithmetic, where half a 50 mm sphere is 50 across
    -- and both failing extent claims were excused as NOT_APPLICABLE because
    a declared `height` of 25 "already checked" the figure."""

    CASE = "dome_released_as_sphere_and_box"

    def test_it_is_built_as_half_the_sphere(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        envelope = sorted(report.measurements["part"]["envelope_mm"])
        self.assertAlmostEqual(envelope[0], 25.0, delta=1.0)
        self.assertAlmostEqual(envelope[2], 50.0, delta=1.5)

    def test_the_part_as_drawn_now_fails(self) -> None:
        from unittest import mock

        with mock.patch("forge_roles.library._half_a_sphere_drawn_whole",
                        return_value=[]):
            report = _verify(_design(_load(self.CASE)))
        # A whole sphere is too tall, and has no flat face at all.
        self.assertEqual(_not_passing(report), {"REQ_BOUNDING_BOX_Z": "FAIL",
                                                "REQ_FLAT_FACE": "FAIL"})

    def test_the_record_s_wrong_extent_is_put_right(self) -> None:
        record = _requirements(_load(self.CASE))
        claims = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in record.requirements}
        self.assertEqual(claims["bounding_box_y"], 50.0)

    def test_only_a_size_inside_the_part_excuses_an_extent(self) -> None:
        from forge_pipeline.verify import _a_size_inside_the_part

        for name in ("bore_diameter", "hole_spacing", "fillet_radius",
                     "inner_diameter"):
            self.assertTrue(_a_size_inside_the_part(name), name)
        for name in ("height", "diameter", "length", "dome_height",
                     "plate_thickness", "width"):
            self.assertFalse(_a_size_inside_the_part(name), name)


class TheHollowDome(unittest.TestCase):
    """Run 20261003T213643: "exactly half of a 50 mm sphere, sitting flat
    side up, hollow on the inside." Blocked: the record bound bounding
    boxes, a volume and a surface area as parameters, claimed the sphere's
    50 as the dome's height, and measured a shell's wall the way a box's is;
    the design was a solid sphere, and the half-sphere repair left it
    solid."""

    CASE = "dome_hollow_flat_side_up"

    def _case(self, flat: str = "up", closed: bool = False):
        import copy

        case = copy.deepcopy(_load(self.CASE))
        case["brief"] = case["brief"].replace("flat side up",
                                              f"flat side {flat}")
        if closed:
            case["brief"] = case["brief"].replace(
                " It carries", " It is closed all round. It carries")
        return case

    def test_the_record_measures_the_dome_and_nothing_invented(self) -> None:
        record = _requirements(self._case())
        claims = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in record.requirements}
        self.assertEqual(claims["bounding_box_z"], 25.0)
        self.assertEqual(claims["minimum_wall_thickness"], 2.0)
        self.assertEqual(claims["opening_depth"], 23.0)
        for gone in ("volume", "surface_area", "parameter:radius",
                     "parameter:bounding_box_x"):
            self.assertNotIn(gone, claims)

    def test_open_or_closed_flat_side_up_or_down(self) -> None:
        for flat in ("up", "down"):
            for closed in (False, True):
                report = _verify(_design(self._case(flat, closed)))
                self.assertEqual(_not_passing(report), {}, (flat, closed))
                volume = report.measurements["part"]["volume_mm3"]
                # Half a 50 mm shell 2 mm thick is some 7,200 mm^3; closed,
                # the flat side adds a 2 mm disc.
                self.assertLess(volume, 12500, (flat, closed))
                self.assertGreater(volume, 6500, (flat, closed))
                if not closed:
                    opening = ("opening_depth" if flat == "up"
                               else "opening_depth:bottom")
                    self.assertEqual(str(report.measurements[opening]),
                                     "23 mm")

    def test_a_solid_dome_cannot_pass_for_it(self) -> None:
        from unittest import mock

        with mock.patch("forge_roles.library._half_a_sphere_drawn_whole",
                        return_value=[]):
            report = _verify(_design(self._case()))
        self.assertEqual(_not_passing(report).get("REQ_WALL_THICKNESS"),
                         "FAIL")


class TheHollowDomeDrawnAsAShell(unittest.TestCase):
    """Run 20261003T225354: the hollow dome as a sphere and a `shell` that
    read `wall_thickness`, declared by nobody, beside a record asking for a
    `height` the design never drew -- the same answer twice."""

    CASE = "dome_hollow_drawn_as_a_shell"

    def test_it_is_built_as_the_open_hollow_half(self) -> None:
        draft = _design(_load(self.CASE))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(str(report.measurements["opening_depth"]), "23 mm")
        self.assertAlmostEqual(
            sorted(report.measurements["part"]["envelope_mm"])[0], 25.0,
            delta=1.0)


class AnEnclosureTooLooseToJudge(unittest.TestCase):
    """The octree's enclosure of a dome cut by a box was 38.6 +/- 13.9 mm
    tall, and equality to 25 and to 38 both passed inside it."""

    def test_the_extent_is_read_off_the_surface_instead(self) -> None:
        from forge_ir import Document
        from forge_pipeline import verify_component

        def claim(identifier, figure):
            return {"id": identifier, "statement": "x",
                    "measurement": "bounding_box_z", "comparison": "equals",
                    "threshold": {"magnitude": figure, "unit": "mm"},
                    "type": "geometric", "verification": "exact_geometry",
                    "strength": "hard", "source": "user", "state": "accepted"}

        def mm(*v):
            return {"vector": list(v), "unit": "mm"}

        doc = {
            "schema_version": "1.0.0", "name": "c", "revision": 1,
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "document_id": "81936263-0fe7-57cd-ae1a-a6baeb3a0858",
            "project_id": "945dd5ce-6fe3-5ae6-84b5-59f417cafb03",
            "risk_class": "low", "assumptions": [],
            "requirements": [claim("RIGHT", 25), claim("WRONG", 38)],
            "components": [{"id": "d", "name": "d", "material": "pla_fdm",
                            "parameters": [], "interfaces": [], "features": [
                {"id": "ball", "kind": "sphere", "parameters": {
                    "diameter": {"magnitude": 50, "unit": "mm"}}},
                {"id": "inside", "kind": "sphere", "parameters": {
                    "diameter": {"magnitude": 46, "unit": "mm"}}},
                {"id": "shell", "kind": "subtract",
                 "inputs": ["ball", "inside"]},
                {"id": "other", "kind": "box", "parameters": {
                    "size": mm(50, 50, 25), "origin": mm(-25, -25, 0)}},
                {"id": "dome", "kind": "subtract",
                 "inputs": ["shell", "other"]}]}]}
        document = Document.from_json(json.dumps(doc))
        report = verify_component(document, document.components[0],
                                  measurement_depth=6)
        status = {g.gate.identifier: g.status.value
                  for g in report.gate_results}
        self.assertEqual((status["RIGHT"], status["WRONG"]), ("PASS", "FAIL"))


class TheHollowDomeTurnedToTheRight(unittest.TestCase):
    """Run 20261003T235448: "exactly half of a 50 mm sphere, sitting flat
    side to the right side, hollow on the inside." Blocked. Forge only knew
    a dome flat side up or down: the record claimed it 25 tall and open at
    the bottom. The design was a 25 mm cylinder shelled both ways, which the
    contribute gate called absent; the analyst removed the cylinder from
    under its shell, and the invalid patch ended the run."""

    CASE = "dome_hollow_flat_side_right_as_a_cylinder"

    def test_the_record_turns_the_half_to_the_right(self) -> None:
        record = _requirements(_load(self.CASE))
        claims = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in record.requirements}
        self.assertEqual([claims[f"bounding_box_{a}"] for a in "xyz"],
                         [25.0, 50.0, 50.0])
        self.assertEqual(claims["opening_depth:right"], 23.0)
        self.assertNotIn("opening_depth:bottom", claims)
        self.assertEqual(claims["minimum_wall_thickness"], 2.0)

    def test_the_cylinder_is_drawn_as_the_half_sphere(self) -> None:
        draft = _design(_load(self.CASE))
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertNotIn("cylinder", kinds)
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(str(report.measurements["opening_depth:right"]),
                         "23 mm")
        volume = report.measurements["part"]["volume_mm3"]
        self.assertGreater(volume, 6500)
        self.assertLess(volume, 8000)


class TheWayAHalfFaces(unittest.TestCase):
    """Which side a half sphere's flat face is turned to, however said."""

    def test_each_way_of_saying_it(self) -> None:
        from forge_roles.library import _the_way_a_half_faces

        said = {
            "sitting flat side down": "bottom",
            "with its flat side on the bed": "bottom",
            "lying on its flat side": "bottom",
            "sitting flat side up": "top",
            "upside down": "top",
            "with the curved side down": "top",
            "resting on its curved side": "top",
            "sitting flat side to the right side": "right",
            "with the flat face turned to the right": "right",
            "with the curved side facing left": "right",
            "flat side facing +X": "right",
            "flat side to the left": "left",
            "flat side facing the front": "front",
            "with its flat side facing backwards": "back",
            "flat face to the rear": "back",
            "hollow, open on the left": "left",
            "": "",
            "a dome on the table": "",
        }
        for words, side in said.items():
            brief = f"A PLA dome: exactly half of a 50 mm sphere, {words}."
            self.assertEqual(_the_way_a_half_faces(brief), side, words)

    def test_two_ways_at_once_is_not_guessed(self) -> None:
        from forge_roles.library import _the_way_a_half_faces

        for words in ("flat side up and flat side left",
                      "flat face facing the front, curved side up"):
            brief = f"A PLA dome: exactly half of a 50 mm sphere, {words}."
            self.assertIsNone(_the_way_a_half_faces(brief), words)

    def test_on_its_side_is_turned_to_the_right_and_says_so(self) -> None:
        """Upright, and every such way is the same part turned about Z."""
        from forge_roles.library import _the_way_a_half_faces

        brief = ("A PLA dome: exactly half of a 50 mm sphere, lying on its "
                 "side. It carries no load, so there is no load case.")
        self.assertEqual(_the_way_a_half_faces(brief), "right")
        case = dict(_load(TheHollowDomeTurnedToTheRight.CASE), brief=brief)
        claim = next(r for r in _requirements(case).requirements
                     if r["measurement"].startswith("flat_face"))
        self.assertEqual(claim["measurement"], "flat_face:right")
        self.assertIn("on its side, not which", claim["statement"])

    def test_every_side_open_closed_or_solid_is_built_and_passes(self) -> None:
        import copy

        from forge_ir.measurements import CONTAINER_SIDES

        base = _load(TheHollowDomeTurnedToTheRight.CASE)
        for side in ("top", "bottom", "left", "right", "front", "back"):
            for kind, words in (("open", ", hollow on the inside"),
                                ("closed", ", hollow and closed all round"),
                                ("solid", "")):
                case = copy.deepcopy(base)
                case["brief"] = case["brief"].replace(
                    "flat side to the right side, hollow on the inside",
                    f"flat side facing {side}{words}")
                record = _requirements(case)
                claims = {r["measurement"]: r["threshold"]["magnitude"]
                          for r in record.requirements}
                want = [50.0, 50.0, 50.0]
                want[CONTAINER_SIDES[side][0]] = 25.0
                self.assertEqual(
                    [claims.get(f"bounding_box_{a}") for a in "xyz"], want,
                    (side, kind))
                report = _verify(_design(case))
                self.assertEqual(_not_passing(report), {}, (side, kind))
                if kind == "open":
                    key = "opening_depth" + (
                        "" if side == "top" else f":{side}")
                    self.assertEqual(str(report.measurements[key]), "23 mm",
                                     side)


class AShellBothWaysIsNotAMissingFeature(unittest.TestCase):
    """A solid shelled `both` ways has none of its own face left where it
    was -- every wall is a half-thickness either side of it -- and was
    reported as having contributed nothing to the part it is all of."""

    def test_the_solid_under_the_shell_contributes(self) -> None:
        from forge_ir import Document
        from forge_pipeline import verify_component

        for direction in ("inward", "outward", "both"):
            doc = {
                "name": "t", "schema_version": "1.0.0", "revision": 1,
                "units": {"length": "mm", "mass": "kg", "angle": "deg",
                          "force": "N"},
                "document_id": "683a7de3-90cd-5326-bbc8-b170220aa7b6",
                "project_id": "bef4f39b-4de5-58d1-ba81-09754c611172",
                "components": [{"id": "c", "material": "pla_fdm", "features": [
                    {"id": "base", "kind": "cylinder", "parameters": {
                        "diameter": {"magnitude": 30, "unit": "mm"},
                        "height": {"magnitude": 20, "unit": "mm"},
                        "origin": {"vector": [0, 0, 0], "unit": "mm"}}},
                    {"id": "sh", "kind": "shell", "inputs": ["base"],
                     "parameters": {"thickness": {"magnitude": 2, "unit": "mm"},
                                    "direction": direction}}]}]}
            document = Document.from_json(json.dumps(doc))
            report = verify_component(document, document.components[0],
                                      measurement_depth=6)
            self.assertEqual(_not_passing(report), {}, direction)


class TheDomeReleasedTheWrongWayUp(unittest.TestCase):
    """Found by sweeping every way a dome can be turned against every
    answer the model has given: "half of a 50 mm sphere, sitting flat side
    up", answered with the model's own half flat side down, passed every
    gate. Its three extents are the same either way up, and a
    `bounding_box_*` equality is read whichever way round the part lies:
    nothing measured which way its flat face was turned."""

    def _case(self, words: str):
        import copy

        case = copy.deepcopy(_load("dome_half_a_sphere"))
        case["brief"] = case["brief"].replace("sitting flat side down", words)
        return case

    def test_the_record_claims_the_flat_face_where_the_brief_puts_it(self):
        for words, side in (("sitting flat side down", "bottom"),
                            ("sitting flat side up", "top"),
                            ("upside down", "top"),
                            ("with its flat side facing the back", "back")):
            claims = {r["measurement"] for r in
                      _requirements(self._case(words)).requirements}
            self.assertIn(f"flat_face:{side}", claims, words)

    def test_the_wrong_way_up_fails_on_the_part(self) -> None:
        from unittest import mock

        with mock.patch("forge_roles.library._half_a_sphere_drawn_whole",
                        return_value=[]):
            report = _verify(_design(self._case("sitting flat side up")))
        self.assertEqual(_not_passing(report).get("REQ_FLAT_FACE"), "FAIL")
        self.assertLess(report.measurements["flat_face:top"].magnitude
                        .midpoint if hasattr(report.measurements[
                            "flat_face:top"], "magnitude") else float(
                            str(report.measurements["flat_face:top"]).split()[0]),
                        100)

    def test_and_is_drawn_the_right_way_up(self) -> None:
        for words in ("sitting flat side up", "with its flat side facing "
                      "the back", "lying on its side"):
            report = _verify(_design(self._case(words)))
            self.assertEqual(_not_passing(report), {}, words)

    def test_the_right_way_up_is_kept_as_drawn(self) -> None:
        draft = _design(self._case("sitting flat side down"))
        ids = [f.identifier for f in draft.document.components[0].features]
        self.assertEqual(ids, ["ball", "upper", "dome_body"])
        self.assertEqual(_not_passing(_verify(draft)), {})


class TheDomeNamedThreeWays(unittest.TestCase):
    """Run 20261004T021539: the hollow dome on its side, correct in every
    measurement, blocked. The record named the sphere's 50 three ways --
    `diameter`, `width`, `height` -- and Forge wired the sphere's
    `diameter` field to `height`, then refused the design twice for the
    other two reading nothing, and kept them NOT_TESTED."""

    CASE = "dome_named_three_ways"

    def test_the_first_answer_is_built_and_released(self) -> None:
        draft = _design(_load(self.CASE))
        sphere = next(f for f in draft.document.components[0].features
                      if f.identifier == "body")
        self.assertEqual(sphere.parameters["diameter"].expression.source,
                         "diameter")
        claims = {r.identifier: r.measurement
                  for r in draft.document.requirements}
        self.assertEqual(claims["REQ_WIDTH"], "footprint_side:50")
        self.assertEqual(claims["REQ_HEIGHT"], "extent_side:50")
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_a_field_goes_to_the_name_it_is_called(self) -> None:
        from forge_roles.library import _declare_what_the_requirements_measure

        case = _load(self.CASE)
        document = json.loads(json.dumps(case["answer"]["document"]))
        _declare_what_the_requirements_measure(document, _requirements(case))
        body = document["components"][0]["features"][0]
        self.assertEqual(body["parameters"]["diameter"]["expression"],
                         "diameter")


class TheCubeOpenOnTheBottom(unittest.TestCase):
    """Run 20261004T022801: "a 30 mm cube ... the bottom face completely
    missing. The cube's walls have a 10mm thickness." Failed as an
    internal error. The model's wall claim, measured from the top, and
    Forge's own on the open bottom took the same id and both were lost;
    the design was a 30 by 30 by 10 slab subtracted from itself, and the
    empty part crashed verification instead of failing a gate."""

    CASE = "cube_open_bottom_walls_lost"

    def test_the_record_measures_the_walls_from_the_open_side(self) -> None:
        record = _requirements(_load(self.CASE))
        ids = [r["id"] for r in record.requirements]
        self.assertEqual(len(ids), len(set(ids)))
        claims = {r["measurement"]: r["threshold"]["magnitude"]
                  for r in record.requirements}
        self.assertEqual(claims["wall_thickness:bottom"], 10.0)
        self.assertEqual(claims["floor_thickness:bottom"], 10.0)
        self.assertEqual(claims["opening_depth:bottom"], 20.0)
        self.assertNotIn("wall_thickness", claims)

    def test_it_is_built_as_the_cube_open_on_the_bottom(self) -> None:
        report = _verify(_design(_load(self.CASE)))
        self.assertEqual(_not_passing(report), {})
        # 30^3 less the 10 by 10 by 20 space.
        self.assertAlmostEqual(report.measurements["part"]["volume_mm3"],
                               25000, delta=1500)

    def test_an_empty_part_fails_a_gate_and_does_not_crash(self) -> None:
        from unittest import mock

        from forge_pipeline import verify_component

        with mock.patch(
                "forge_roles.library._a_container_built_some_other_way",
                return_value=[]):
            draft = _design(_load(self.CASE))
        report = verify_component(draft.document,
                                  draft.document.components[0],
                                  measurement_depth=8)
        # The slab taken from itself is empty to the last micrometre since
        # Forge took off the blend nobody asked for (the blend left a skin
        # the octree could prove was there): no surface to extract, and the
        # enclosure cannot prove a part of zero thickness absent.
        failing = _not_passing(report)
        self.assertIn("FAIL", {failing.get("GEOM_NON_EMPTY"),
                               failing.get("GEOM_SURFACE_EXISTS")}, failing)
        self.assertLessEqual(set(failing), {"GEOM_NON_EMPTY",
                                            "GEOM_SURFACE_EXISTS"})
        self.assertEqual(report.overall_status.value, "FAIL")


class EveryWayACubeIsOpen(unittest.TestCase):
    """Found by sweeping every side, every way of saying it is open and
    every way of giving its walls against every cube answer so far: a
    cube "with the top face missing" or "with no top wall" was measured as
    sealed, one "with the bottom face of the cube completely missing" as
    open at the top, and a rebuilt cube kept the model's own unread
    `thickness`, failing the gate on every dimension driving the part."""

    def test_the_side_however_it_is_said(self) -> None:
        from forge_roles.library import _the_container_the_brief_describes

        said = {
            "with the top face missing": {"open_top": True},
            "with no top wall": {"open_top": True},
            "and the top side is open": {"open_top": True},
            "with the bottom face of the cube completely missing":
                {"open_side": "bottom"},
            "with the left face entirely removed": {"open_side": "left"},
            "with no front wall": {"open_side": "front"},
        }
        for words, found in said.items():
            self.assertEqual(_the_container_the_brief_describes(
                f"A 30 mm cube in PLA, hollow on the inside, {words}."),
                found, words)

    def test_each_side_and_wall_is_built_and_measured(self) -> None:
        import copy

        base = _load("cube_hollow_drawn_as_plates_and_holes")
        for side, words, wall in (
                ("top", "with the top face missing", 2.0),
                ("bottom", "with the bottom face of the cube completely "
                 "missing. The walls are 3 mm thick", 3.0),
                ("front", "open on the front side. It has 5 mm walls", 5.0)):
            case = copy.deepcopy(base)
            case["brief"] = (f"A 30 mm cube in PLA, hollow on the inside, "
                             f"{words}. It carries no load, so there is no "
                             "load case.")
            suffix = "" if side == "top" else f":{side}"
            claims = {r["measurement"]: r["threshold"]["magnitude"]
                      for r in _requirements(case).requirements}
            self.assertEqual(claims[f"wall_thickness{suffix}"], wall, side)
            self.assertEqual(claims[f"opening_depth{suffix}"], 30 - wall,
                             side)
            report = _verify(_design(case))
            self.assertEqual(_not_passing(report), {}, side)


class TheFlangeDiscDrawnAsADrum(unittest.TestCase):
    """Run 20261004T154944, from the regression suite: "a steel flange disc
    60 mm across and 8 mm thick". The model drew its one cylinder `length`
    tall -- declared 60 -- and declared `thickness` 8 for nothing to read:
    a 60 mm drum with the holes in the right places. Forge caught it (the
    part's 8 mm thickness failed) but had no repair for a cylinder, only for
    a box, and the repair loop removed `thickness` and stopped."""

    CASE = "flange_disc_drawn_as_a_drum"

    def test_it_is_built_as_the_disc(self) -> None:
        draft = _design(_load(self.CASE))
        disc = next(f for f in draft.document.components[0].features
                    if f.identifier == "disc")
        self.assertEqual(disc.parameters["height"].expression.source,
                         "thickness")
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        envelope = sorted(report.measurements["part"]["envelope_mm"])
        self.assertAlmostEqual(envelope[0], 8.0, delta=0.5)
        self.assertAlmostEqual(envelope[2], 60.0, delta=1.5)

    def test_the_drum_as_drawn_fails_and_never_passes(self) -> None:
        from unittest import mock

        with mock.patch(
                "forge_roles.library._the_only_cylinder_is_the_part_s_size",
                return_value=[]):
            try:
                report = _verify(_design(_load(self.CASE)))
            except Exception:  # noqa: BLE001 - refused is not passed
                return
        self.assertNotEqual(_not_passing(report), {})

    def test_a_diameter_is_never_wired_into_a_height(self) -> None:
        import copy

        from forge_roles.library import _declare_what_the_requirements_measure

        case = copy.deepcopy(_load(self.CASE))
        component = case["answer"]["document"]["components"][0]
        disc = component["features"][0]
        disc["parameters"]["height"] = {"magnitude": 60.0, "unit": "mm"}
        component["parameters"] = [p for p in component["parameters"]
                                   if p["id"] != "outer_diameter"]
        disc["parameters"]["diameter"] = {"magnitude": 60.0, "unit": "mm"}
        _declare_what_the_requirements_measure(
            {"components": [component]}, _requirements(case))
        self.assertNotEqual(disc["parameters"]["height"].get("expression"),
                            "diameter")


class TheFlangeHolesOnTwoBranches(unittest.TestCase):
    """Run 20261004T231146, from the regression suite: the pipe flange.
    The bore hung off the disc beside a chain of four bolt holes. Forge
    chained the loose ends by re-pointing the bolt chain's END at the bore,
    which cut the three holes before it loose -- then refused the design
    for having two loose ends, with a hint the model had already followed.
    The same answer twice, and no part."""

    CASE = "flange_holes_on_two_branches"

    def test_it_is_built_as_the_flange(self) -> None:
        draft = _design(_load(self.CASE))
        features = {f.identifier: f for f in draft.document.components[0]
                    .features}
        # One chain: the bore, then the first bolt hole, through to the last.
        self.assertEqual(features["primary_bolt_hole_1"].inputs, ("bore",))
        self.assertEqual(features["primary_bolt_hole_4"].inputs,
                         ("primary_bolt_hole_3",))
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        envelope = sorted(report.measurements["part"]["envelope_mm"])
        self.assertAlmostEqual(envelope[0], 10.0, delta=0.5)
        self.assertAlmostEqual(envelope[2], 80.0, delta=2.0)

    def test_every_way_the_holes_can_be_wired(self) -> None:
        """One chain, a star off the body, branches split anywhere, with or
        without a union of the loose ends."""
        import copy

        base = _load(self.CASE)
        holes = ["bore"] + [f"primary_bolt_hole_{i}" for i in range(1, 5)]
        # A sample of the sixteen wirings; the sweep runs them all.
        for mask in ((0, 0, 0, 0), (1, 1, 1, 1), (0, 1, 1, 1), (1, 1, 1, 0),
                     (0, 1, 0, 1), (1, 0, 1, 0), (0, 0, 0, 1)):
            parents = ["body"] + [holes[i] if m else "body"
                                  for i, m in enumerate(mask)]
            for joined in (False, True):
                case = copy.deepcopy(base)
                component = case["answer"]["document"]["components"][0]
                features = [f for f in component["features"]
                            if f["kind"] != "union"]
                by = {f["id"]: f for f in features}
                for hole, parent in zip(holes, parents):
                    by[hole]["inputs"] = [parent]
                consumed = {x for f in features for x in f.get("inputs", [])}
                ends = [f["id"] for f in features if f["id"] not in consumed]
                if joined:
                    if len(ends) < 2:
                        continue
                    features.append({"id": "part_body", "kind": "union",
                                     "inputs": ends})
                component["features"] = features
                report = _verify(_design(case))
                self.assertEqual(_not_passing(report), {}, (parents, joined))


class TheCurvedPlate(unittest.TestCase):
    """Run 20261004T233341, the first curved part: "a slightly curved
    aluminium mounting plate 70 mm long, 50 mm wide, 4 mm thick and curved
    at about 10 degrees", four corner holes. Forge had no way to bend a
    solid. The model drew the plate flat and the curve as a datum plane
    "offset 10 degrees", Forge welded the plane into the part, and the
    record measured a curved plate as a flat one."""

    CASE = "plate_curved_ten_degrees"

    def test_the_record_measures_the_curve_and_the_plate_laid_flat(self):
        claims = {r["measurement"]: (r["comparison"], r["threshold"]["magnitude"])
                  for r in _requirements(_load(self.CASE)).requirements}
        self.assertEqual(claims["bend_angle"], ("equals", 10.0))
        self.assertEqual(claims["bend_count"], ("equals", 1))
        self.assertEqual(claims["bend_off_centre"], ("equals", 0.0))
        self.assertEqual(claims["bend_spread"][0], "at_least")
        for side in (70, 50, 4):
            self.assertEqual(claims[f"flat_extent_side:{side}"],
                             ("equals", float(side)))
        self.assertNotIn("bounding_box_z", claims)

    def test_the_flat_answer_is_built_bent_and_passes(self) -> None:
        draft = _design(_load(self.CASE))
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertEqual(kinds[-1], "bend")
        self.assertNotIn("datum_plane", kinds)
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.measurements["part"]["open_holes"], 4)
        self.assertAlmostEqual(
            float(str(report.measurements["bend_angle"]).split()[0]), 10.0,
            delta=0.5)

    def test_a_flat_plate_cannot_pass_for_it(self) -> None:
        from unittest import mock

        with mock.patch("forge_roles.library._a_bend_the_design_left_out",
                        return_value=[]):
            report = _verify(_design(_load(self.CASE)))
        failing = _not_passing(report)
        self.assertEqual(failing.get("REQ_CURVATURE"), "FAIL")


class TheWaysABendIsSaid(unittest.TestCase):
    def test_each(self) -> None:
        from forge_roles.library import _the_bends_the_brief_describes as said

        cases = {
            "A plate curved at about 10 degrees.":
                [{"angle": 10.0, "shape": "curve"}],
            "A strip with a 90 degree bend in the middle.":
                [{"angle": 90.0, "shape": "fold", "middle": True}],
            "A bracket bent up 45 degrees 20 mm from one end.":
                [{"angle": 45.0, "shape": "fold", "from_end": 20.0}],
            "A plate with two 90 degree folds, 10 mm from each end.": [
                {"angle": 90.0, "shape": "fold", "from_end": 10.0, "end": 0},
                {"angle": 90.0, "shape": "fold", "from_end": 10.0, "end": 1}],
            "A plate curved 30 degrees at the centre with a 20 mm inside "
            "radius.": [{"angle": 30.0, "shape": "curve", "middle": True,
                         "radius": 20.0}],
        }
        for brief, bends in cases.items():
            self.assertEqual(said(brief), bends, brief)

    def test_an_angle_that_is_no_bend(self) -> None:
        from forge_roles.library import _the_bends_the_brief_describes as said

        for brief in ("Two set screws 90 degrees apart.",
                      "A 45 degree chamfer on each edge.",
                      "A plate angled at 30 degrees."):
            self.assertEqual(said(brief), [], brief)

    def test_no_bend_slots_for_a_part_that_does_not_bend(self) -> None:
        from forge_roles.library import _whole_part_slots_the_brief_can_fill

        slots = _whole_part_slots_the_brief_can_fill(
            "A shaft collar 25 mm across, two set screws 90 degrees apart.")
        self.assertFalse({"bend_angle", "bend_centre"} & set(slots))
        slots = _whole_part_slots_the_brief_can_fill(
            "A plate 70 mm long curved at 10 degrees.")
        self.assertIn("bend_angle", slots)


class ABendInTheKernel(unittest.TestCase):
    """The bend itself: volume kept, the field a lower bound on distance,
    and the turn read back off the finished surface."""

    def _plate(self):
        from forge_geom import BoxSDF

        return BoxSDF(centre=(0.0, 0.0, 0.0), half_extent=(35.0, 25.0, 2.0))

    def test_a_bend_keeps_the_volume_and_is_closed(self) -> None:
        import math

        from forge_geom import Bend, extract_manifold_surface

        for angle, radius in ((10, 399.1), (90, 4.0), (60, 30.0)):
            bent = Bend(self._plate(), position=(0, 0, 0), along=(1, 0, 0),
                        toward=(0, 0, 1), angle=math.radians(angle),
                        radius=radius)
            mesh = extract_manifold_surface(bent, resolution=110)
            self.assertTrue(mesh.is_watertight()[0], angle)
            self.assertAlmostEqual(abs(mesh.signed_volume()), 14000.0,
                                   delta=140.0)

    def test_the_cell_bounds_never_misclassify(self) -> None:
        import math

        import numpy as np

        from forge_geom import Bend
        from forge_geom.ibounds import cell_box

        bent = Bend(self._plate(), position=(5, 1, 0), along=(1, 0.2, 0),
                    toward=(0, 0.1, 1), angle=math.radians(40), radius=12)
        rng = np.random.default_rng(2)
        env = bent.envelope
        for half in (0.5, 2.0, 6.0):
            centres = rng.uniform(np.array(env.lo) - 3, np.array(env.hi) + 3,
                                  size=(1500, 3))
            lo, hi = bent.bounds(cell_box(centres, np.full(3, half)))
            for offset in rng.uniform(-1, 1, size=(10, 3)):
                value = bent(centres + offset * half)
                self.assertFalse(np.any((lo > 0) & (value <= 0)))
                self.assertFalse(np.any((hi < 0) & (value >= 0)))

    def test_a_tilted_holed_plate_meshes_closed(self) -> None:
        """Not the bend's: a plate turned 20 or 45 degrees to the grid has
        hole rims the surface nets cut ambiguously, and was reported not
        watertight. The grid is shifted until it is cut cleanly."""
        import math

        import numpy as np

        from forge_geom import (BoxSDF, CylinderSDF, Difference, Transform,
                                extract_manifold_surface)

        plate = Difference(self._plate(), tuple(
            CylinderSDF(base=(x, y, -5.0), axis=(0.0, 0.0, 1.0), radius=2.0,
                        height=10.0)
            for x, y in ((28, 18), (-28, 18), (-28, -18), (28, -18))))
        for angle in (20, 45):
            c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            turned = Transform(plate, (c, 0, -s, 0, 1, 0, s, 0, c), (0, 0, 0))
            mesh = extract_manifold_surface(turned, resolution=110)
            self.assertTrue(mesh.is_watertight()[0], angle)


class TheSphereDrawnAsADrum(unittest.TestCase):
    """Run 20261005T151727: "A PLA sphere with a 100mm diameter" released as
    a 100 by 100 cylinder. Round about its axis, 100 mm all three ways, and
    every claim passed -- a false pass. The record now claims the part is as
    wide every way, and the one cylinder standing in for the ball is drawn
    as the ball."""

    def test_the_ball_is_built_and_passes(self) -> None:
        case = _load("sphere_drawn_as_a_drum")
        draft = _design(case)
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertEqual(kinds, ["sphere"])
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})

    def test_the_drum_is_caught_without_the_repair(self) -> None:
        from unittest import mock

        from forge_roles import library

        case = _load("sphere_drawn_as_a_drum")
        with mock.patch.object(library, "_a_ball_drawn_as_something_else",
                               lambda *a: []):
            draft = _design(case)
        self.assertEqual(
            [f.kind for f in draft.document.components[0].features],
            ["cylinder"])
        self.assertEqual(_not_passing(_verify(draft)), {"REQ_BALL": "FAIL"})

    def test_the_record_claims_a_ball(self) -> None:
        requirements = _requirements(_load("sphere_drawn_as_a_drum"))
        claims = {dict(r)["measurement"]: dict(r)["threshold"]["magnitude"]
                  for r in requirements.requirements}
        self.assertEqual(claims["roundness_every_way"], 0.95)

    def test_the_designer_is_told_ball_not_cylinder(self) -> None:
        from forge_roles import ForgeIRDesigner

        case = _load("sphere_drawn_as_a_drum")
        messages = ForgeIRDesigner().build_messages(
            intent=_intent(case), requirements=_requirements(case),
            brief=case["brief"])
        text = "\n".join(m.content for m in messages)
        self.assertIn("This part is a BALL", text)
        self.assertNotIn("This part is ROUND, so that is ONE `cylinder`", text)


class WhatIsABall(unittest.TestCase):
    def test_wordings(self) -> None:
        from forge_roles.library import _the_part_is_a_ball

        for brief in ("A PLA sphere with a 100mm diameter",
                      "A 40 mm steel ball.",
                      "Make a 25 mm brass sphere with a 3 mm hole through it.",
                      "a spherical bead 12 mm across"):
            with self.subTest(brief=brief):
                self.assertTrue(_the_part_is_a_ball(brief))
        for brief in ("A dome: exactly half of a 50 mm sphere.",
                      "A ball joint socket 30 mm across.",
                      "A 30 mm cube with a 10 mm sphere on top.",
                      "A 20 mm ball on a 40 mm stem.",
                      "A sphere 50 mm across, flattened at the bottom.",
                      "A flange disc 60 mm across."):
            with self.subTest(brief=brief):
                self.assertFalse(_the_part_is_a_ball(brief))


class RoundEveryWay(unittest.TestCase):
    def test_a_ball_a_drum_and_a_block(self) -> None:
        from forge_geom import BoxSDF, CylinderSDF, SphereSDF
        from forge_pipeline.measure import _roundness_every_way

        class Part:
            def __init__(self, solid):
                self.solid = solid

        def value(solid):
            return float(_roundness_every_way(Part(solid)).value.magnitude.lo)

        self.assertGreater(value(SphereSDF((0, 0, 0), 50.0)), 0.99)
        self.assertAlmostEqual(value(CylinderSDF(
            (0, 0, -50), (0, 0, 1), 50.0, 100.0)), 0.707, delta=0.01)
        self.assertAlmostEqual(
            value(BoxSDF((0, 0, 0), (50, 50, 50))), 0.577, delta=0.01)


class TheDomeWhoseOpeningNamedNothing(unittest.TestCase):
    """Run 20261005T151214: half of a 70 mm sphere, flat side to the left,
    hollow. A `subtract` naming no inputs was refused twice and the run
    ended with no part. A boolean of the one solid where it sits is that
    solid; with it taken out, the half sphere is drawn as the brief says."""

    def test_it_is_built_and_passes(self) -> None:
        from forge_pipeline import verify_component

        case = _load("dome_flat_left_opening_named_nothing")
        draft = _design(case)
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertEqual(kinds, ["sphere", "box", "sphere", "subtract",
                                 "intersect"])
        report = verify_component(
            draft.document, draft.document.components[0], measurement_depth=9)
        self.assertEqual(_not_passing(report), {})


class ABooleanThatNamesNothing(unittest.TestCase):
    def _settle(self, features):
        from forge_roles.library import _a_boolean_that_names_nothing

        notes = _a_boolean_that_names_nothing(features)
        return features, notes

    def test_one_solid_is_that_solid(self) -> None:
        features, notes = self._settle([
            {"id": "a", "kind": "box"},
            {"id": "s", "kind": "shell", "inputs": ["a"]},
            {"id": "cut", "kind": "subtract"},
            {"id": "h", "kind": "hole", "inputs": ["cut"]}])
        self.assertEqual([f["id"] for f in features], ["a", "s", "h"])
        self.assertEqual(features[-1]["inputs"], ["s"])
        self.assertTrue(notes)

    def test_a_union_takes_every_loose_solid(self) -> None:
        features, _ = self._settle([
            {"id": "a", "kind": "box"}, {"id": "b", "kind": "cylinder"},
            {"id": "u", "kind": "union"}])
        self.assertEqual(features[-1]["inputs"], ["a", "b"])

    def test_a_subtract_takes_the_body_then_its_cutters(self) -> None:
        features, _ = self._settle([
            {"id": "a", "kind": "box"}, {"id": "c", "kind": "cylinder"},
            {"id": "cut", "kind": "subtract"}])
        self.assertEqual(features[-1]["inputs"], ["a", "c"])

    def test_a_subtract_of_two_bodies_is_left_to_ask(self) -> None:
        features, notes = self._settle([
            {"id": "a", "kind": "box"}, {"id": "b", "kind": "box"},
            {"id": "u", "kind": "union", "inputs": ["a", "b"]},
            {"id": "c", "kind": "box"}, {"id": "s", "kind": "shell",
                                         "inputs": ["c"]},
            {"id": "cut", "kind": "subtract"}])
        self.assertNotIn("inputs", features[-1])
        self.assertEqual(notes, [])


class TheCubeOpenOnTwoSides(unittest.TestCase):
    """Run 20261005T171148: "a 50 mm cube ... with the right face of the
    square missing. 3mm Thickness Open on the left side." Open both ways,
    and the record measured it as a box open at the top -- 26.5 mm of
    "floor" -- and the analyst's patch then crashed the run."""

    def test_the_record_measures_both_openings(self) -> None:
        requirements = _requirements(_load("cube_open_left_and_right"))
        claims = {dict(r)["measurement"]: dict(r)["threshold"]["magnitude"]
                  for r in requirements.requirements}
        self.assertEqual(claims["wall_thickness:left"], 3.0)
        self.assertEqual(claims["opening_depth:left"], 50.0)
        self.assertEqual(claims["opening_depth:right"], 50.0)
        self.assertFalse(any(m.startswith("floor_thickness") for m in claims))
        self.assertNotIn("wall_thickness", claims)

    def test_it_is_built_open_through_and_passes(self) -> None:
        from forge_pipeline import verify_component

        draft = _design(_load("cube_open_left_and_right"))
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertEqual(kinds, ["box", "box", "subtract"])
        report = verify_component(
            draft.document, draft.document.components[0], measurement_depth=8)
        self.assertEqual(_not_passing(report), {})

    def test_adjacent_sides(self) -> None:
        from forge_roles import RequirementsEngineer

        brief = ("A 40 mm cube in PLA, hollow, 2 mm thick, open on the top "
                 "and with the left face missing.")
        requirements = RequirementsEngineer().parse({
            "risk_class": "low", "requirements": [{
                "id": "REQ_SIDE", "statement": "The cube is 40 mm.",
                "measurement": "parameter:side", "comparison": "equals",
                "threshold": {"magnitude": 40, "unit": "mm"}}],
            "assumptions": [], "unknowns": []}, brief=brief)
        claims = {dict(r)["measurement"]: dict(r)["threshold"]["magnitude"]
                  for r in requirements.requirements}
        self.assertEqual(claims["opening_depth:top"], 38.0)
        self.assertEqual(claims["opening_depth:left"], 38.0)
        self.assertEqual(claims["floor_thickness:top"], 2.0)
        self.assertEqual(claims["floor_thickness:left"], 2.0)


class ANumberWrittenAsText(unittest.TestCase):
    """The analyst's patch for the cube wrote a blend radius as the text
    "3", which decoded as a dimensionless expression and crashed the
    compiler inside the gate loop."""

    def test_a_quoted_number_is_that_number(self) -> None:
        from forge_ir.values import Reader, decode_scalar

        value = decode_scalar(Reader({"magnitude": "3", "unit": "mm"}, "/x"))
        self.assertEqual(float(value.quantity.magnitude.lo), 3.0)
        self.assertEqual(value.quantity.unit.symbol, "mm")

    def test_a_name_is_still_an_expression(self) -> None:
        from forge_ir.values import ExpressionValue, Reader, decode_scalar

        value = decode_scalar(Reader({"magnitude": "wall", "unit": "mm"}, "/x"))
        self.assertIsInstance(value, ExpressionValue)


class ANumberAddedToALength(unittest.TestCase):
    def test_it_is_millimetres(self) -> None:
        from forge_roles.library import _a_number_added_to_a_length

        component = {"features": [{"id": "h", "kind": "hole", "parameters": {
            "diameter": {"expression": "d / 2 + 1", "unit": "mm"},
            "position": {"vector": ["length / 2 - offset - 30", 0, "t / 2"],
                         "unit": "mm"}}}]}
        self.assertTrue(_a_number_added_to_a_length(component))
        parameters = component["features"][0]["parameters"]
        self.assertEqual(parameters["diameter"]["expression"],
                         "d / 2 + 1 * mm")
        self.assertEqual(parameters["position"]["vector"][0],
                         "length / 2 - offset - 30 * mm")
        self.assertEqual(parameters["position"]["vector"][2], "t / 2")

    def test_a_ratio_is_left_alone(self) -> None:
        from forge_roles.library import _a_number_added_to_a_length

        component = {"features": [{"id": "b", "kind": "box", "parameters": {
            "size": {"vector": ["2 * w", "w / 3", "t"], "unit": "mm"}}}]}
        self.assertEqual(_a_number_added_to_a_length(component), [])


class TheCurvedPlateSizedTwice(unittest.TestCase):
    """Run 20261005T145317 passed -- after a repair round spent on a bend
    sized by both `radius` and `bend_length`, and with its four holes drilled
    straight down through the bent plate."""

    def test_built_flat_drilled_then_bent(self) -> None:
        from forge_pipeline import verify_component

        draft = _design(_load("plate_curved_sized_twice"))
        features = draft.document.components[0].features
        self.assertEqual([f.kind for f in features],
                         ["box", "hole", "hole", "hole", "hole", "bend"])
        bend = draft.payload["components"][0]["features"][-1]["parameters"]
        self.assertNotIn("radius", bend)
        self.assertEqual(bend.get("hold"), "middle")
        report = verify_component(
            draft.document, draft.document.components[0], measurement_depth=8)
        self.assertEqual(_not_passing(report), {})


class ThePlateArchedAcrossItsWidth(unittest.TestCase):
    """Run 20261005T180120: "Create a curved mounting plate, 120 mm long, 75
    mm wide and 6 mm thick. Curve the plate uniformly across its 75 mm width
    with an inside radius of 60 mm, with the curvature center directly below
    the longitudinal centerline. Round the four corners with a 12 mm radius.
    Add two 28 x 5 mm holes ... Add two 8.2 mm mounting holes ..." The
    record was refused twice for a count written as 22 mm, and the run
    ended."""

    def test_the_record_reads(self) -> None:
        requirements = _requirements(_load("plate_arched_across_its_width"))
        claims = {dict(r)["measurement"]: dict(r)["threshold"]["magnitude"]
                  for r in requirements.requirements}
        self.assertAlmostEqual(claims["bend_angle"], 68.209, places=2)
        self.assertEqual(claims["bent_along"], 75.0)
        self.assertEqual(claims["bend_convex"], 1)
        self.assertEqual(claims["bend_spread"], 75.0)
        self.assertEqual(claims["flat_extent_side:120"], 120.0)
        self.assertEqual(claims["openings_of_size:28x5"], 2)
        self.assertEqual(claims["holes_of_diameter:8.2"], 2)
        self.assertFalse(any(":centered" in m for m in claims))
        # No load was named, so there is none: the margin the record
        # claimed is dropped, and nothing is asked.
        self.assertFalse(any(m.startswith("safety_factor") for m in claims))
        self.assertEqual(requirements.unknowns, ())

    def test_the_plate_is_arched_level_and_rounded(self) -> None:
        import numpy as np

        from forge_geom import extract_manifold_surface
        from forge_kernel import Compiler

        draft = _design(_load("plate_arched_across_its_width"))
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertEqual(kinds[:3], ["datum_plane", "profile_rectangle",
                                     "extrude"])
        self.assertEqual(kinds[-1], "bend")
        report = _verify(draft)
        # The design drew no slots; the brief places them in full, so Forge
        # cuts them -- and then what fails is the brief's own collision,
        # the 8.2 mm hole 18 mm from the end inside the slot 22 mm from it.
        self.assertTrue(any(n.startswith("THE BRIEF'S OWN FIGURES OVERLAP")
                            for n in draft.notes))
        self.assertEqual(
            {k: v for k, v in _not_passing(report).items()
             }, {"GEOM_HOLES_ARE_HOLES": "FAIL", "REQ_OPENINGS_28X5": "FAIL",
                 "REQ_AT_28X5_HI22_MID": "FAIL",
                 "REQ_AT_8_2_END18_MID": "FAIL",
             # The notched holes are not counted as holes.
             "REQ_HOLES_8_2MM": "FAIL"})
        part = Compiler().compile_component(draft.document.components[0])
        mesh = extract_manifold_surface(part.solid)
        vertices = np.asarray(mesh.vertices)
        lo, hi = vertices.min(axis=0), vertices.max(axis=0)
        # Level: the middle stays where it was flat, both edges fall evenly.
        self.assertAlmostEqual(hi[2], 3.0, delta=0.5)
        self.assertAlmostEqual(lo[1], -hi[1], delta=0.6)
        self.assertAlmostEqual(hi[1] - lo[1], 74.0, delta=1.0)


class TheWaysACurveIsSaidByItsRadius(unittest.TestCase):
    def test_wordings(self) -> None:
        from forge_roles.library import _the_bends_the_brief_describes

        bends = _the_bends_the_brief_describes(
            "A plate 150 mm long, 60 mm wide and 5 mm thick, curved along "
            "its length with a 100 mm inside radius.")
        self.assertAlmostEqual(bends[0]["angle"], 83.847, places=2)
        bends = _the_bends_the_brief_describes(
            "A 100 mm long, 40 mm wide, 3 mm thick plate, curved 30 degrees "
            "across its width, dished.")
        self.assertEqual((bends[0]["along"], bends[0]["way"]), (40.0, "dish"))
        bends = _the_bends_the_brief_describes(
            "A 100 mm long, 40 mm wide, 3 mm thick plate, arched 30 degrees.")
        self.assertEqual(bends[0]["way"], "arch")
        self.assertEqual(_the_bends_the_brief_describes(
            "A plate 100 mm long, 40 mm wide and 3 mm thick with 5 mm "
            "radius corners."), [])


class ABendHeldLevel(unittest.TestCase):
    def test_the_middle_stays_where_it_was(self) -> None:
        import math

        import numpy as np

        from forge_geom import Bend, BoxSDF

        plate = BoxSDF((0, 0, 0), (50, 20, 2))
        bend = Bend(plate, position=(0, 0, 0), along=(1, 0, 0),
                    toward=(0, 0, 1), angle=math.radians(60), radius=40.0,
                    hold=math.radians(30))
        middle = np.array([[0.0, 0.0, 0.0]])
        self.assertTrue(np.allclose(bend.forward(middle), middle, atol=1e-9))
        ends = bend.forward(np.array([[-50.0, 0, 0], [50.0, 0, 0]]))
        self.assertAlmostEqual(ends[0][2], ends[1][2], places=6)
        self.assertAlmostEqual(ends[0][0], -ends[1][0], places=6)
        # The field and its bounds agree: the octree may trust them.
        points = np.random.default_rng(1).uniform(-60, 60, (2000, 3))
        values = bend(points)
        lo, hi = bend.bounds((points - 0.5, points + 0.5))
        self.assertTrue(np.all(lo <= values + 1e-9))
        self.assertTrue(np.all(values >= -1e6))


class AnOpeningOfALengthAndAWidth(unittest.TestCase):
    def test_slots_are_counted_by_their_size(self) -> None:
        from forge_kernel import Compiler
        from forge_pipeline.measure import _openings_of_size

        case = _load("plate_arched_across_its_width")
        document = case["answer"]["document"]
        document["components"][0]["features"] += [
            {"id": "slot_plane", "kind": "datum_plane", "parameters": {
                "base": "XY", "offset": {"magnitude": -10, "unit": "mm"}}},
            {"id": "slot_a", "kind": "profile_slot", "inputs": ["slot_plane"],
             "parameters": {"length": {"magnitude": 28, "unit": "mm"},
                            "width": {"magnitude": 5, "unit": "mm"},
                            "center_u": {"magnitude": -20, "unit": "mm"},
                            "rotation": {"magnitude": 90, "unit": "deg"}}},
            {"id": "slot_a_cut", "kind": "extrude", "inputs": ["slot_a"],
             "parameters": {"distance": {"magnitude": 20, "unit": "mm"}}},
            {"id": "slotted", "kind": "subtract",
             "inputs": ["mounting_hole_2", "slot_a_cut"]}]
        draft = _design(case)
        part = Compiler().compile_component(draft.document.components[0])
        self.assertEqual(
            int(_openings_of_size(part, "28x5").value.magnitude.lo), 1)
        # The two round holes are openings too, 8.2 both ways.
        self.assertEqual(
            int(_openings_of_size(part, "8.2x8.2").value.magnitude.lo), 2)
        self.assertEqual(
            int(_openings_of_size(part, "28x8").value.magnitude.lo), 0)


class CountsThatAreNotCounts(unittest.TestCase):
    def test_a_distance_in_a_count_is_dropped(self) -> None:
        from forge_roles.library import _a_count_written_in_a_unit

        requirements = [
            {"id": "A", "measurement": "feature_count:hole:centered",
             "threshold": {"magnitude": 22, "unit": "mm"}},
            {"id": "B", "measurement": "feature_count:hole",
             "threshold": {"magnitude": 4, "unit": "bolts"}},
            {"id": "C", "measurement": "safety_factor:bearing",
             "threshold": {"magnitude": 300, "unit": "N"}}]
        _a_count_written_in_a_unit(requirements)
        self.assertEqual([r["id"] for r in requirements], ["B", "C"])
        self.assertEqual(requirements[0]["threshold"]["unit"], "")

    def test_a_count_of_where_is_dropped(self) -> None:
        from forge_roles.library import _a_count_of_where_not_what

        requirements = [
            {"id": "A", "measurement": "feature_count:hole:centered"},
            {"id": "B", "measurement": "feature_count:hole:mounting"}]
        _a_count_of_where_not_what(requirements)
        self.assertEqual([r["id"] for r in requirements], ["B"])


class AMarginOnNoLoad(unittest.TestCase):
    def _unknowns(self, brief):
        from forge_roles.library import _a_margin_with_no_load_to_take_it_on

        answer = {"requirements": [{"id": "SF", "measurement":
                                    "safety_factor:bending"}],
                  "assumptions": [], "unknowns": []}
        _a_margin_with_no_load_to_take_it_on(brief, answer)
        return [u["id"] for u in answer["unknowns"]]

    def test_a_load_named_without_a_figure_is_asked_about(self) -> None:
        self.assertEqual(self._unknowns(
            "A plate 60 mm long. It must be strong."), ["UNK_LOAD"])

    def test_a_stated_force_is_not(self) -> None:
        self.assertEqual(self._unknowns(
            "A bar 60 mm long; 150 N pushes down on its end."), [])


class CornersTheBriefRounds(unittest.TestCase):
    def test_wordings(self) -> None:
        from forge_roles.library import _CORNERS_ROUNDED

        for brief, figure in (
                ("round the four corners with a 12 mm radius", "12"),
                ("with 5 mm radius corners", "5"),
                ("the corners are rounded to 3 mm", "3"),
                ("a corner radius of 8 mm", "8")):
            with self.subTest(brief=brief):
                found = _CORNERS_ROUNDED.search(brief)
                self.assertIsNotNone(found)
                self.assertEqual(next(g for g in found.groups() if g), figure)


class AKindWrittenAnotherWay(unittest.TestCase):
    def test_plural_case_and_spaces(self) -> None:
        from forge_roles.library import _a_kind_spelled_another_way

        component = {"features": [
            {"id": "a", "kind": "Boxes"}, {"id": "b", "kind": "holes"},
            {"id": "c", "kind": "pattern circular"},
            {"id": "d", "kind": "gizmo"}]}
        _a_kind_spelled_another_way(component)
        self.assertEqual([f["kind"] for f in component["features"]],
                         ["box", "hole", "pattern_circular", "gizmo"])

    def test_a_collar_with_its_hole_written_holes_still_builds(self) -> None:
        case = _load("collar_first_true_pass")
        component = (case["answer"].get("document")
                     or case["answer"])["components"][0]
        component["features"][2]["kind"] = "holes"
        self.assertEqual(_not_passing(_verify(_design(case))), {})


class ASizeWrittenWithoutItsUnit(unittest.TestCase):
    def test_text_bare_and_constant(self) -> None:
        from forge_roles.library import _a_number_written_without_its_unit

        component = {"features": [{"id": "h", "kind": "hole", "parameters": {
            "diameter": {"magnitude": "4.0", "unit": "mm"},
            "position": {"vector": ["0", 0, "t / 2"]},
            "axis": [0, 0, 1]}},
            {"id": "b", "kind": "bend", "parameters": {
                "angle": {"expression": "30"},
                "radius": {"magnitude": 5}}}]}
        _a_number_written_without_its_unit(component, {"length": "mm",
                                                       "angle": "deg"})
        hole = component["features"][0]["parameters"]
        bend = component["features"][1]["parameters"]
        self.assertEqual(hole["diameter"], {"magnitude": 4.0, "unit": "mm"})
        self.assertEqual(hole["position"]["vector"], [0.0, 0, "t / 2"])
        self.assertEqual(hole["position"]["unit"], "mm")
        self.assertEqual(bend["angle"], {"magnitude": 30.0, "unit": "deg"})
        self.assertEqual(bend["radius"], {"magnitude": 5, "unit": "mm"})


class ConesRingsAndWedges(unittest.TestCase):
    """Shapes the kernel had no way to draw: a cone or a frustum, a ring with
    a round section, a wedge. Each is built and passes, and a cylinder drawn
    in place of a cone or a ring is redrawn -- or, without the repair,
    caught by the volume its shape allows."""

    def _passes(self, name: str, kinds: list[str]) -> None:
        from forge_pipeline import verify_component

        draft = _design(_load(name))
        self.assertEqual([f.kind for f in draft.document.components[0].features],
                         kinds)
        report = verify_component(
            draft.document, draft.document.components[0], measurement_depth=8)
        self.assertEqual(_not_passing(report), {})

    def test_each_shape(self) -> None:
        for name, kinds in (("shape_cone", ["cone"]),
                            ("shape_frustum", ["cone"]),
                            ("shape_o_ring", ["torus"]),
                            ("shape_wedge_gusset", ["wedge"]),
                            ("shape_cone_drawn_as_a_cylinder", ["cone"]),
                            ("shape_o_ring_drawn_as_a_disc", ["torus"])):
            with self.subTest(name=name):
                self._passes(name, kinds)

    def test_the_stand_in_is_caught_without_the_repair(self) -> None:
        from unittest import mock

        from forge_pipeline import verify_component
        from forge_roles import library

        for name in ("shape_cone_drawn_as_a_cylinder",
                     "shape_o_ring_drawn_as_a_disc"):
            with self.subTest(name=name), mock.patch.object(
                    library, "_a_cone_or_a_ring_drawn_as_a_cylinder",
                    lambda *a: []):
                draft = _design(_load(name))
                report = verify_component(
                    draft.document, draft.document.components[0],
                    measurement_depth=8)
                self.assertEqual(_not_passing(report),
                                 {"REQ_SHAPE_VOLUME": "FAIL"})

    def test_the_readings(self) -> None:
        from forge_roles.library import (
            _the_cone_the_brief_describes, _the_ring_the_brief_describes)

        self.assertEqual(_the_cone_the_brief_describes(
            "A 40 mm diameter cone, 60 mm high."), (40.0, 60.0))
        self.assertIsNone(_the_cone_the_brief_describes(
            "A frustum 50 mm across at the bottom, 20 mm at the top."))
        self.assertIsNone(_the_cone_the_brief_describes(
            "A plate with a cone-shaped countersink 10 mm across."))
        self.assertEqual(_the_ring_the_brief_describes(
            "An O-ring with a 42 mm inside diameter and a 4 mm "
            "cross-section."), (46.0, 4.0))

    def test_the_kernel_shapes_are_exact(self) -> None:
        import numpy as np

        from forge_geom import ConeSDF, TorusSDF

        cone = ConeSDF((0, 0, 0), (0, 0, 1), 20.0, 0.0, 60.0)
        ring = TorusSDF((0, 0, 0), (0, 0, 1), 25.0, 2.0)
        rng = np.random.default_rng(3)
        points = rng.uniform(-40, 70, (3000, 3))
        moved = points + rng.normal(size=points.shape)
        for shape in (cone, ring):
            change = np.abs(shape(moved) - shape(points))
            self.assertTrue(np.all(change <= np.linalg.norm(
                moved - points, axis=1) + 1e-9))
        self.assertAlmostEqual(float(ring(np.array([[27.0, 0, 0]]))[0]), 0.0)
        self.assertAlmostEqual(float(cone(np.array([[0.0, 0, 60]]))[0]), 0.0)


class AZooOfCommonParts(unittest.TestCase):
    """Correct designs for parts people ask for -- a hex nut, a washer, a
    tube, a slotted plate, a flange with a bolt circle drawn as a pattern of
    one hole, a row of holes, a tray, a square tube, a cube with rounded
    edges -- each with the record Forge writes for its brief. Every one must
    pass: a Forge reading that fails a correct part is a defect."""

    NAMES = ("zoo_flange_pattern", "zoo_hex_nut", "zoo_knob",
             "zoo_l_bracket_bent", "zoo_plate_4_holes", "zoo_plate_hole_row",
             "zoo_rounded_cube", "zoo_rounded_plate", "zoo_slotted_plate",
             "zoo_square_tube", "zoo_standoff", "zoo_tray", "zoo_tube",
             "zoo_washer")

    def test_each_passes(self) -> None:
        from forge_pipeline import verify_component

        for name in self.NAMES:
            with self.subTest(name=name):
                draft = _design(_load(name))
                report = verify_component(
                    draft.document, draft.document.components[0],
                    measurement_depth=8)
                self.assertEqual(_not_passing(report), {})

    def test_a_pattern_of_a_hole_is_copies_of_the_hole(self) -> None:
        draft = _design(_load("zoo_flange_pattern"))
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertEqual(kinds, ["cylinder"] + ["hole"] * 7)

    def test_rounded_edges_are_the_box_s_own(self) -> None:
        draft = _design(_load("zoo_rounded_cube"))
        features = list(draft.document.components[0].features)
        self.assertEqual([f.kind for f in features], ["box", "hole"])
        self.assertIn("edge_radius", features[0].parameters)


class TheLBracketWithHolesNamedForTheirPlaces(unittest.TestCase):
    """Run 20261006T202330: the same L-bracket brief that passed five times,
    answered differently by the model -- a hole drawn for every figure of a
    row (`base_hole_centre` and `base_hole_distance` as diameters), both
    legs sized with an undeclared `base_width`, one hole where the brief has
    two. Refused three times; no part."""

    def test_it_is_the_bracket_the_brief_describes(self) -> None:
        case = _load("l_bracket_holes_named_for_their_places")
        draft = _design(case)
        component = draft.document.components[0]
        holes = [f for f in component.features if f.kind == "hole"]
        self.assertEqual(len(holes), 4)
        declared = {p["id"]: p["value"]["magnitude"] for p in json.loads(
            draft.document.to_json())["components"][0]["parameters"]}
        # The plate's width is the brief's 40, not the 5 mm hole it shares
        # the word "base" with.
        self.assertEqual(declared.get("base_width"), 40.0)
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_a_placement_is_dropped_only_on_another_hole_s_line(self) -> None:
        from forge_roles.library import _a_hole_sized_by_where_it_goes

        def hole(name, size, x):
            return {"id": name, "kind": "hole", "inputs": ["plate"],
                    "parameters": {"diameter": {"expression": size},
                                   "position": {"vector": [x, 0, 0]},
                                   "axis": [0, 0, 1]}}

        component = {"features": [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [50, 40, 5], "unit": "mm"},
                "centered": True}},
            hole("a", "hole_diameter", 0), hole("b", "hole_offset", 10)],
            "parameters": [
                {"id": "hole_diameter", "value": {"magnitude": 5, "unit": "mm"}},
                {"id": "hole_offset", "value": {"magnitude": 8, "unit": "mm"}}]}
        # Apart from every other hole, a hole sized by any name is the
        # design's to have -- nothing says it is a placement.
        self.assertEqual(_a_hole_sized_by_where_it_goes(component), [])
        component["features"][2]["parameters"]["position"]["vector"] = [0, 0, 0]
        self.assertTrue(_a_hole_sized_by_where_it_goes(component))
        self.assertEqual([f["id"] for f in component["features"]],
                         ["plate", "a"])


class ThePlateDrawnAsAPillow(unittest.TestCase):
    """Run 20261006T191845, its design with Forge's own repairs undone: the
    plate rounded by growing it 12 mm all round, the 28 x 5 slots drawn as
    28 mm holes, every hole drilled along the plate's length after the
    bend. It came out a pillow with four channels through it."""

    def test_built_as_the_brief_places_it_and_the_conflict_said(self) -> None:
        case = _load("plate_pillow_drilled_along_its_length")
        draft = _design(case)
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertNotIn("offset", kinds)
        self.assertEqual(kinds[-1], "bend")
        self.assertEqual(kinds.count("profile_slot"), 2)
        self.assertTrue(any(n.startswith("THE BRIEF'S OWN FIGURES OVERLAP")
                            for n in draft.notes))
        # Everything else holds: what fails is the brief's own collision --
        # the 8.2 mm hole 18 mm from the end sits inside the slot centred 22
        # mm from it.
        # Where each opening is, is checked too: the slot at the high end
        # and the hole 18 mm in are the two that run together.
        self.assertEqual(_not_passing(_verify(draft)), {
            "GEOM_HOLES_ARE_HOLES": "FAIL", "REQ_OPENINGS_28X5": "FAIL",
            "REQ_AT_28X5_HI22_MID": "FAIL", "REQ_AT_8_2_END18_MID": "FAIL",
            "REQ_HOLES_8_2MM": "FAIL"})

    def test_with_its_figures_apart_it_passes(self) -> None:
        case = _load("plate_pillow_drilled_along_its_length")
        case["brief"] = case["brief"].replace(
            "18 mm from the distal edge", "45 mm from the distal edge")
        for requirement in case["requirements"]["requirements"]:
            if requirement["id"] == "REQ_MOUNTING_HOLE_OFFSET":
                requirement["threshold"]["magnitude"] = 45.0
        draft = _design(case)
        self.assertFalse(any("OVERLAP" in n for n in draft.notes))
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_an_offset_that_rounds_a_shrunken_core_is_kept(self) -> None:
        from forge_roles.library import _an_offset_that_rounds_by_growing

        component = {"features": [
            {"id": "core", "kind": "box", "parameters": {
                "size": {"vector": ["40 * mm - 2 * r", "40 * mm - 2 * r",
                                    "40 * mm - 2 * r"], "unit": "mm"},
                "centered": True}},
            {"id": "body", "kind": "offset", "inputs": ["core"],
             "parameters": {"distance": {"expression": "r"}}}],
            "parameters": [{"id": "r", "value": {"magnitude": 3, "unit": "mm"}}]}
        brief = "A 40 mm cube with 3 mm rounded edges."
        self.assertEqual(
            _an_offset_that_rounds_by_growing(component, None, brief), [])
        component["features"][0]["parameters"]["size"]["vector"] = [40, 40, 40]
        self.assertTrue(
            _an_offset_that_rounds_by_growing(component, None, brief))
        self.assertEqual([f["id"] for f in component["features"]], ["core"])


class AHollowDomeDrawnAnyWay(unittest.TestCase):
    """Run 20261007T100515: "exactly half of a 70 mm sphere, sitting flat
    side to the left side, hollow on the inside". The design failed four
    checks; the analyst's patch set a sphere to 70 mm, and only then did
    Forge's half-a-sphere reading recognise the dome and redraw it. It
    passed -- by luck. These two answers are what that reading refused."""

    # A 2 mm shell 70 mm across: read at the depth a run reads it.
    def _verify_deep(self, draft):
        from forge_pipeline import verify_component

        return verify_component(draft.document, draft.document.components[0],
                                measurement_depth=8)

    def test_the_hollow_as_two_spheres(self) -> None:
        draft = _design(_load("dome_hollow_as_two_spheres"))
        self.assertEqual(_not_passing(self._verify_deep(draft)), {})

    def test_the_sphere_drawn_at_its_radius(self) -> None:
        draft = _design(_load("dome_sphere_drawn_at_its_radius"))
        self.assertEqual(_not_passing(self._verify_deep(draft)), {})


class ThePlateRevolvedToCurveIt(unittest.TestCase):
    """Run 20261007T105318: the curved plate drawn as the plate `revolve`d by
    the bend's angle and subtracted from itself -- refused for a revolve with
    one input, twice, and no part. It is the bend it means."""

    def test_it_is_the_bent_plate_and_only_the_brief_s_collision_fails(self) -> None:
        draft = _design(_load("plate_revolved_to_curve_it"))
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertNotIn("revolve", kinds)
        self.assertNotIn("offset", kinds)
        self.assertEqual(kinds[-1], "bend")
        self.assertEqual(_not_passing(_verify(draft)), {
            "GEOM_HOLES_ARE_HOLES": "FAIL", "REQ_OPENINGS_28X5": "FAIL",
            "REQ_AT_28X5_HI22_MID": "FAIL", "REQ_AT_8_2_END18_MID": "FAIL",
            "REQ_HOLES_8_2MM": "FAIL"})

    def test_with_its_figures_apart_it_passes(self) -> None:
        case = _load("plate_revolved_to_curve_it")
        case["brief"] = case["brief"].replace(
            "18 mm from the distal edge", "45 mm from the distal edge")
        # The record as that brief gives it: the offset at 45, the
        # placements read again from it -- and the model's own figure 45.
        record = case["requirements"]["requirements"]
        record[:] = [r for r in record if not r["id"].startswith("REQ_AT_")]
        for requirement in record:
            if requirement["id"] == "REQ_MOUNTING_HOLE_OFFSET":
                requirement["threshold"]["magnitude"] = 45.0
        for parameter in case["answer"]["document"]["components"][0][
                "parameters"]:
            if parameter["id"] == "mounting_hole_offset":
                parameter["value"]["magnitude"] = 45.0
        self.assertEqual(_not_passing(_verify(_design(case))), {})


class ThePlateRepeatedForItsHoles(unittest.TestCase):
    """Run 20261007T120516, the corrected curved-plate brief: the model drew
    its "holes" as three `pattern_circular` copies of the whole bent plate,
    turned 180 degrees about a corner. The part came out as plates in heaps,
    the bend never set, no 8.2 mm hole -- and "the first hole center 45 mm
    from one end" was not read, so nothing put the holes back."""

    def test_it_is_one_curved_plate_and_every_check_passes(self) -> None:
        draft = _design(_load("plate_curved_holes_drawn_as_copies"))
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertNotIn("pattern_circular", kinds)
        self.assertEqual(kinds[-1], "bend")
        self.assertEqual(kinds.count("hole"), 2)
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_the_holes_from_one_end_are_placed_and_checked(self) -> None:
        from forge_roles.library import _the_openings_the_brief_places

        case = _load("plate_curved_holes_drawn_as_copies")
        placed = [p for p in _the_openings_the_brief_places(case["brief"])
                  if p["shape"].get("round") == 8.2]
        self.assertEqual(len(placed), 1)
        self.assertEqual((placed[0]["count"], placed[0]["inset"],
                          placed[0]["pitch"]), (2, 45.0, 30.0))
        draft = _design(case)
        measured = {r.measurement for r in draft.document.requirements}
        self.assertTrue({"opening_at:8.2:end45,mid", "opening_at:8.2:end75,mid"}
                        <= {str(m) for m in measured}, measured)

    def test_a_pattern_whose_copies_overlap_is_kept(self) -> None:
        from forge_roles.library import _a_pattern_of_the_whole_part

        component = {"id": "c", "parameters": [], "features": [
            {"id": "bar", "kind": "box", "parameters": {
                "size": {"vector": [40, 10, 10], "unit": "mm"}}},
            {"id": "more", "kind": "pattern_linear", "inputs": ["bar"],
             "parameters": {"count": {"expression": "3"},
                            "spacing": {"vector": [20, 0, 0], "unit": "mm"}}}]}
        self.assertEqual(_a_pattern_of_the_whole_part(component), [])
        self.assertEqual(len(component["features"]), 2)

    def test_a_pattern_into_separate_pieces_is_taken_out(self) -> None:
        from forge_roles.library import _a_pattern_of_the_whole_part

        component = {"id": "c", "parameters": [], "features": [
            {"id": "bar", "kind": "box", "parameters": {
                "size": {"vector": [40, 10, 10], "unit": "mm"}}},
            {"id": "more", "kind": "pattern_linear", "inputs": ["bar"],
             "parameters": {"count": {"expression": "3"},
                            "spacing": {"vector": [60, 0, 0], "unit": "mm"}}}]}
        self.assertEqual(len(_a_pattern_of_the_whole_part(component)), 1)
        self.assertEqual([f["id"] for f in component["features"]], ["bar"])


class ThePlateWithItsSlotsSketchedOnIt(unittest.TestCase):
    """Run 20261007T160309: the slots drawn as `profile_slot` features on the
    bent plate itself -- an outline on a solid, read by nothing -- refused
    three times, and no part, though Forge had cut both slots where the brief
    puts them."""

    def test_it_is_one_curved_plate_and_every_check_passes(self) -> None:
        draft = _design(_load("plate_slots_sketched_on_the_part"))
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertEqual(kinds[-1], "bend")
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_an_outline_on_a_solid_and_extruded_is_drawn_on_a_plane(self) -> None:
        from forge_roles.library import _a_sketch_drawn_on_a_solid

        component = {"id": "c", "parameters": [], "features": [
            {"id": "block", "kind": "box", "parameters": {
                "size": {"vector": [40, 30, 10], "unit": "mm"}}},
            {"id": "ring", "kind": "profile_circle", "inputs": ["block"],
             "parameters": {"diameter": {"magnitude": 8, "unit": "mm"}}},
            {"id": "boss", "kind": "extrude", "inputs": ["ring"],
             "parameters": {"distance": {"magnitude": 5, "unit": "mm"}}}]}
        self.assertEqual(len(_a_sketch_drawn_on_a_solid(component, None, "")), 1)
        kinds = {f["id"]: f["kind"] for f in component["features"]}
        self.assertEqual(kinds[component["features"][1]["id"]], "datum_plane")
        self.assertEqual(component["features"][2]["inputs"],
                         [component["features"][1]["id"]])

    def test_an_outline_left_on_a_solid_is_cut_through_it(self) -> None:
        from forge_roles.library import _a_sketch_drawn_on_a_solid

        component = {"id": "c", "parameters": [], "features": [
            {"id": "block", "kind": "box", "parameters": {
                "size": {"vector": [40, 30, 10], "unit": "mm"},
                "centered": True}},
            {"id": "window", "kind": "profile_rectangle", "inputs": ["block"],
             "parameters": {"width": {"magnitude": 10, "unit": "mm"},
                            "height": {"magnitude": 6, "unit": "mm"}}}]}
        self.assertEqual(len(_a_sketch_drawn_on_a_solid(component, None, "")), 1)
        last = component["features"][-1]
        self.assertEqual(last["kind"], "subtract")
        self.assertEqual(last["inputs"][0], "block")


class ACountOfSlotsIsACountOfOpenings(unittest.TestCase):
    """Run 20261007T160309: "two 28 x 5 mm slots" bound to
    `feature_count:slot`. A slot is no kind of feature, so the claim was
    kept unbound and reported NOT_TESTED -- holding back a plate whose every
    other check passed. It counts the openings the brief sizes."""

    def test_it_is_read_as_the_openings_of_that_size(self) -> None:
        from forge_roles import RequirementsEngineer

        case = _load("plate_slots_sketched_on_the_part")
        record = json.loads(json.dumps(case["requirements"]))
        record["requirements"].append({
            "id": "REQ_LONGITUDINAL_SLOT_COUNT",
            "statement": "The plate shall have two 28 × 5 mm slots "
                         "running along its length.",
            "measurement": "feature_count:slot", "comparison": "at_least",
            "threshold": {"magnitude": 2, "unit": ""}, "type": "geometric",
            "verification": "exact_geometry", "strength": "hard",
            "source": "user", "state": "accepted"})
        for kept in (record["requirements"], [
                r for r in record["requirements"]
                if not r["id"].startswith(("REQ_OPENINGS", "REQ_AT_"))]):
            parsed = RequirementsEngineer().parse(
                {**record, "requirements": json.loads(json.dumps(kept))},
                brief=case["brief"])
            counting = [r["id"] for r in parsed.requirements
                        if r.get("measurement") == "openings_of_size:28x5"]
            self.assertEqual(len(counting), 1, counting)
            self.assertTrue(all(r.get("measurement") or not r.get("threshold")
                                for r in parsed.requirements
                                if "SLOT" in r["id"]))


class ThePlateStackedByPatternsNamedForOpenings(unittest.TestCase):
    """Run 20261007T180123: `slots` and `mounting_holes`, each a
    `pattern_linear` of the whole bent plate 22 and 30 mm up -- four plates
    stacked, touching where they curve. And the brief's own sentence about
    the curvature centre, carried as a critical assumption nobody approved,
    held the part back."""

    def test_it_is_one_curved_plate_and_every_check_passes(self) -> None:
        case = _load("plate_stacked_by_patterns_named_for_openings")
        draft = _design(case)
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertNotIn("pattern_linear", kinds)
        self.assertEqual(kinds[-1], "bend")
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_the_brief_s_own_sentence_is_no_assumption(self) -> None:
        from forge_roles import RequirementsEngineer

        case = _load("plate_stacked_by_patterns_named_for_openings")
        parsed = RequirementsEngineer().parse(
            json.loads(json.dumps(case["requirements"])), brief=case["brief"])
        self.assertEqual(tuple(parsed.assumptions), ())

    def test_an_assumption_of_its_own_is_kept(self) -> None:
        from forge_roles.library import _an_assumption_the_brief_states

        answer = {"assumptions": [{
            "id": "ASM_LOAD", "statement": "The plate carries a 50 N load at "
            "its centre.", "risk": "high", "approved": False}]}
        case = _load("plate_stacked_by_patterns_named_for_openings")
        self.assertEqual(_an_assumption_the_brief_states(case["brief"], answer),
                         [])
        self.assertEqual(len(answer["assumptions"]), 1)

    def test_the_figures_forge_checks_need_no_second_answer(self) -> None:
        from forge_roles import RequirementsEngineer

        case = _load("plate_stacked_by_patterns_named_for_openings")
        record = json.loads(json.dumps(case["requirements"]))
        record["requirements"] = [
            r for r in record["requirements"]
            if not r["id"].startswith(("REQ_AT_", "REQ_OPENINGS", "REQ_PART_",
                                       "REQ_BEND_", "REQ_HOLES_"))
            and (r.get("threshold") or {}).get("magnitude") not in (60, 12, 22,
                                                                   30)]
        # Forge adds its own claims back and they carry 60, 22 and 30 mm.
        RequirementsEngineer().parse(record, brief=case["brief"])


class TheCubeClaimedAsThickAsItsWalls(unittest.TestCase):
    """Run 20261007T222853: "A 50 mm cube ... 3mm Thickness. Open on the
    left and right sides." The record claimed the cube 3 mm up the Z -- the
    walls' figure -- the design followed it, and the part was a 50 by 50 by
    3 slab cut into four corners by a 50 mm hole."""

    def test_the_cube_is_its_figure_every_way(self) -> None:
        from forge_roles import RequirementsEngineer

        case = _load("cube_open_sides_claimed_as_thick_as_its_walls")
        parsed = RequirementsEngineer().parse(
            json.loads(json.dumps(case["requirements"])), brief=case["brief"])
        extents = {r["measurement"]: r["threshold"]["magnitude"]
                   for r in parsed.requirements
                   if str(r.get("measurement", "")).startswith("bounding_box_")}
        self.assertEqual(extents, {"bounding_box_x": 50.0,
                                   "bounding_box_y": 50.0,
                                   "bounding_box_z": 50.0})

    def test_it_is_built_open_both_sides_and_every_check_passes(self) -> None:
        draft = _design(_load("cube_open_sides_claimed_as_thick_as_its_walls"))
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_a_height_the_brief_gives_a_block_still_stands(self) -> None:
        from forge_roles.library import _a_solid_s_one_figure_measured

        requirements = [{"id": "REQ_Z", "measurement": "bounding_box_z",
                         "comparison": "equals", "statement": "z",
                         "threshold": {"magnitude": 20.0, "unit": "mm"}}]
        _a_solid_s_one_figure_measured(
            "A 50 mm cube cut down to 20 mm tall.", {"cube": [50.0]},
            requirements)
        self.assertEqual(requirements[0]["threshold"]["magnitude"], 20.0)


class ThePlateJoinedWithCopiesOfItself(unittest.TestCase):
    """Run 20261008T085157, first answer: `union(curved_face, slot_holes,
    mounting_hole_holes)`, the last two each a pattern of the first. The
    decoder refused it and named the chain as the fix; Forge makes it."""

    def test_the_first_answer_needs_no_second(self) -> None:
        draft = _design(_load("plate_joined_with_copies_of_itself"))
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertNotIn("union", kinds)
        self.assertEqual(kinds[-1], "bend")
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_a_union_of_unrelated_solids_is_left(self) -> None:
        from forge_roles.library import _a_union_of_a_solid_and_what_was_made_of_it

        features = [
            {"id": "a", "kind": "box", "parameters": {}},
            {"id": "b", "kind": "cylinder", "parameters": {}},
            {"id": "c", "kind": "union", "inputs": ["a", "b"]}]
        self.assertEqual(_a_union_of_a_solid_and_what_was_made_of_it(features), [])
        self.assertEqual(len(features), 3)


class TheLBracketWithItsBaseLegNamedTwice(unittest.TestCase):
    """Run 20261008T105449: `length` = 50 and `base_leg_length` = 50, one
    dimension under two names. The geometry read one, the claim measured
    the other, and the model was asked twice where to put it."""

    def test_it_is_one_dimension_and_every_check_passes(self) -> None:
        draft = _design(_load("l_bracket_its_base_leg_named_twice"))
        parameters = draft.document.components[0].parameters
        self.assertIn("base_leg_length", str(parameters["length"].expression))
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_a_figure_shared_by_two_dimensions_is_not_one(self) -> None:
        from forge_roles.library import _an_orphan_that_is_another_name

        component = {"parameters": [
            {"id": "width", "value": {"magnitude": 40.0, "unit": "mm"}},
            {"id": "upright_leg_height",
             "value": {"magnitude": 40.0, "unit": "mm"}}],
            "features": [{"id": "b", "kind": "box", "parameters": {
                "size": {"vector": ["width", "width", "width"], "unit": "mm"}}}]}
        notes, left = _an_orphan_that_is_another_name(
            component, ["upright_leg_height"])
        self.assertEqual((notes, left), ([], ["upright_leg_height"]))



class TheArmPlateWithStrapSlotsNearItsEdges(unittest.TestCase):
    """Four strap slots, "two at each end, with their centers 10 mm in from
    each long edge and 22 mm from each longitudinal end": off the
    centreline, which the openings Forge places had never been."""

    def test_they_are_read_as_four_two_each_way(self) -> None:
        from forge_roles.library import _the_openings_the_brief_places

        case = _load("plate_strap_slots_near_the_long_edges")
        slots = [p for p in _the_openings_the_brief_places(case["brief"])
                 if "slot" in p["shape"]][0]
        self.assertEqual(slots["count"], 4)
        self.assertEqual(slots["places"], [("lo", 22.0), ("hi", 22.0)])
        self.assertEqual(slots["across"], [("lo", 10.0), ("hi", 10.0)])

    def test_each_end_is_not_an_edge_on_the_side(self) -> None:
        from forge_roles.library import _FROM_EACH_END, _FROM_EACH_SIDE

        said = "10 mm in from each long edge and 22 mm from each longitudinal end"
        self.assertEqual(_FROM_EACH_END.findall(said), ["22"])
        self.assertEqual(_FROM_EACH_SIDE.findall(said), ["10"])

    def test_they_are_cut_there_and_every_check_passes(self) -> None:
        draft = _design(_load("plate_strap_slots_near_the_long_edges"))
        measured = {str(r.measurement) for r in draft.document.requirements}
        self.assertTrue({"opening_at:28x5:lo22,lo10", "opening_at:28x5:lo22,hi10",
                         "opening_at:28x5:hi22,lo10", "opening_at:28x5:hi22,hi10"}
                        <= measured, measured)
        self.assertEqual(_not_passing(_verify(draft)), {})


class TheArmPlateRoundedByExtrudingIt(unittest.TestCase):
    """Run 20261009T092758: `corner_rounding`, an `extrude` of the bent plate
    with `end_radius` 12 mm. An extrude sweeps an outline; the plate has
    none. Refused three times, and no part."""

    def test_it_is_taken_out_and_every_check_passes(self) -> None:
        draft = _design(_load("plate_corners_rounded_by_extruding_it"))
        ids = [f.identifier for f in draft.document.components[0].features]
        self.assertNotIn("corner_rounding", ids)
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertEqual(kinds[-1], "bend")
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_an_extrude_of_an_outline_is_left(self) -> None:
        from forge_roles.library import _a_solid_extruded

        component = {"features": [
            {"id": "p", "kind": "datum_plane", "parameters": {"base": "XY"}},
            {"id": "o", "kind": "profile_circle", "inputs": ["p"],
             "parameters": {"diameter": {"magnitude": 5, "unit": "mm"}}},
            {"id": "e", "kind": "extrude", "inputs": ["o"],
             "parameters": {"distance": {"magnitude": 5, "unit": "mm"}}}]}
        self.assertEqual(_a_solid_extruded(component), [])
        self.assertEqual(len(component["features"]), 3)


class TheArmPlateWithItsHolesFromTheBottomEnd(unittest.TestCase):
    """Run 20261009T121201: "the first hole center 15 mm from the bottom
    end". `bottom` named no end Forge knew: the holes were left where the
    model drew them, after the bend, and the bend was never set."""

    def test_the_bottom_end_is_an_end(self) -> None:
        from forge_roles.library import _the_openings_the_brief_places

        case = _load("plate_holes_from_the_bottom_end")
        holes = [p for p in _the_openings_the_brief_places(case["brief"])
                 if p["shape"].get("round") == 8.2][0]
        self.assertEqual(holes["places"], [("lo", 15.0), ("lo", 45.0)])

    def test_the_brief_s_corners_are_no_assumption(self) -> None:
        from forge_roles import RequirementsEngineer

        case = _load("plate_holes_from_the_bottom_end")
        parsed = RequirementsEngineer().parse(
            json.loads(json.dumps(case["requirements"])), brief=case["brief"])
        self.assertEqual(tuple(parsed.assumptions), ())

    def test_it_is_built_as_asked_and_every_check_passes(self) -> None:
        draft = _design(_load("plate_holes_from_the_bottom_end"))
        kinds = [f.kind for f in draft.document.components[0].features]
        self.assertEqual(kinds[-1], "bend")
        self.assertEqual(_not_passing(_verify(draft)), {})


class TheArmPlateDrawnAsItsOutlineAlone(unittest.TestCase):
    """Run 20261009T144100: the plate a `profile_sketch` 75 by 60 mm from a
    corner, handed straight to the bend -- never extruded, so never a
    solid. Refused three times, and no part."""

    def test_it_is_the_plate_and_every_check_passes(self) -> None:
        draft = _design(_load("plate_drawn_as_its_outline_alone"))
        features = {f.identifier: f.kind
                    for f in draft.document.components[0].features}
        self.assertEqual(features["base"], "extrude")
        self.assertEqual(features["base_outline"], "profile_rectangle")
        self.assertEqual(_not_passing(_verify(draft)), {})

    def test_an_outline_that_is_extruded_is_left(self) -> None:
        from forge_roles.library import _a_plate_drawn_as_its_outline_alone

        component = {"parameters": [], "features": [
            {"id": "p", "kind": "datum_plane", "parameters": {"base": "XY"}},
            {"id": "o", "kind": "profile_rectangle", "inputs": ["p"],
             "parameters": {"width": {"magnitude": 9, "unit": "mm"},
                            "height": {"magnitude": 9, "unit": "mm"}}},
            {"id": "e", "kind": "extrude", "inputs": ["o"],
             "parameters": {"distance": {"magnitude": 5, "unit": "mm"}}}]}
        self.assertEqual(_a_plate_drawn_as_its_outline_alone(
            component, None, "A plate 9 mm long, 9 mm wide and 5 mm thick."),
            [])
        self.assertEqual(len(component["features"]), 3)


class TheFlightControllerPlate(unittest.TestCase):
    """The brief for the first run on Claude: two squares of holes of
    different sizes, a hole in the middle and slots at each end, on a plate
    named in more words than Forge used to read past."""

    BRIEF = ("A 3D-printed PLA flight-controller mounting plate for a drone, "
             "80 mm long, 60 mm wide and 4 mm thick, with all four corners "
             "rounded to an 8 mm radius. Four 3.2 mm holes on a 30.5 mm square "
             "of centres, centred on the plate, for the flight-controller "
             "stack. Four 3.4 mm frame holes on a 64 x 44 mm rectangle of "
             "centres, centred on the plate. A 16 mm cable hole in the centre "
             "of the plate. Two 16 x 4 mm zip-tie slots running along the "
             "plate's length, centred across the width, with their centres "
             "14 mm from each end. It carries no load, so there is no load "
             "case.")

    def test_the_plate_is_sized_however_it_is_named(self) -> None:
        from forge_roles.library import _the_part_s_own_sizes

        self.assertEqual(_the_part_s_own_sizes(self.BRIEF),
                         {"long": [80.0], "wide": [60.0], "thick": [4.0]})

    def test_every_opening_is_placed_and_checked(self) -> None:
        from forge_roles.library import _where_the_brief_places_its_openings

        record: list = []
        _where_the_brief_places_its_openings(self.BRIEF, record)
        placed = {r["measurement"] for r in record}
        self.assertEqual(placed, {
            "opening_at:16x4:lo14,mid", "opening_at:16x4:hi14,mid",
            "opening_at:16:mid,mid",
            "opening_at:3.2:mid+15.25,mid+15.25",
            "opening_at:3.2:mid+15.25,mid-15.25",
            "opening_at:3.2:mid-15.25,mid+15.25",
            "opening_at:3.2:mid-15.25,mid-15.25",
            "opening_at:3.4:mid+32,mid+22", "opening_at:3.4:mid+32,mid-22",
            "opening_at:3.4:mid-32,mid+22", "opening_at:3.4:mid-32,mid-22"})

    def test_two_rectangles_of_one_size_are_neither(self) -> None:
        from forge_roles.library import _the_hole_rectangles_the_brief_states

        self.assertEqual(_the_hole_rectangles_the_brief_states(
            "A plate 90 mm long, 60 mm wide and 4 mm thick. Four 3 mm holes "
            "on a 30 mm square of centres. Four 3 mm holes on a 60 x 40 mm "
            "rectangle of centres."), [])


class TheFlightControllerPlateOnClaude(unittest.TestCase):
    """The first live run on Claude Sonnet 5, refused three times. Its third
    answer was correct; Forge recut its 16 mm cable hole as two 16 x 4 mm
    slots, because the slots were drawn as slot outlines and the cable hole
    shared their 16 mm, and then refused the design for the cable hole it no
    longer had. The first answer was refused for a union of the two slot
    cutters, which share only the datum plane they are sketched on. The
    second was its document wrapped twice."""

    CASE = "fc_plate_claude_sonnet_5"

    def _features(self, draft) -> dict:
        return {f["id"]: f for f in
                draft.payload["components"][0]["features"]}

    def test_the_answer_as_written_is_the_part_asked_for(self) -> None:
        case = _load(self.CASE)
        draft = _design(case)
        features = self._features(draft)
        self.assertEqual(features["cable_hole"]["kind"], "hole")
        self.assertNotIn("_openings_placed_where_the_brief_puts_them",
                         draft.repairs_made)
        report = _verify(draft)
        self.assertEqual(_not_passing(report), {})
        self.assertEqual(report.overall_status.value, "PASS")

    def test_the_slot_cutters_unioned_then_cut_once(self) -> None:
        case = _load(self.CASE)
        features = case["answer"]["document"]["components"][0]["features"]
        by_id = {f["id"]: f for f in features}
        by_id["plate_minus_slot_1"].update(
            id="ziptie_slots", kind="union",
            inputs=["ziptie_slot_1_cut", "ziptie_slot_2_cut"])
        by_id["plate_with_slots"]["inputs"] = ["base_plate", "ziptie_slots"]
        features.remove(by_id["plate_with_slots"])
        features.insert(features.index(by_id["plate_minus_slot_1"]) + 1,
                        by_id["plate_with_slots"])
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {})

    def test_the_answer_wrapped_twice(self) -> None:
        case = _load(self.CASE)
        case["answer"] = {"rationale": "", "document": case["answer"]}
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {})

    def test_a_hole_that_could_be_either_is_left_as_drawn(self) -> None:
        """A slot drawn as a 16 mm round hole beside the 16 mm cable hole:
        two holes of a size the brief counts once, and nothing says which is
        which. Neither is recut -- recutting the wrong one loses the cable
        hole -- and the built part's counts say what is wrong."""
        case = _load(self.CASE)
        component = case["answer"]["document"]["components"][0]
        features = component["features"]
        drop = {"ziptie_slot_plane", "ziptie_slot_1_profile",
                "ziptie_slot_1_cut", "plate_minus_slot_1",
                "ziptie_slot_2_profile", "ziptie_slot_2_cut",
                "plate_with_slots"}
        kept = [f for f in features if f["id"] not in drop]
        {f["id"]: f for f in kept}["fc_hole_1"]["inputs"] = ["slot_a"]
        component["features"] = kept[:1] + [
            {"id": "slot_a", "kind": "hole", "tags": ["zip_tie"],
             "inputs": ["base_plate"], "parameters": {
                 "diameter": {"expression": "ziptie_slot_length", "unit": "mm"},
                 "position": {"vector": [-26, 0, 0], "unit": "mm"},
                 "axis": [0, 0, 1]}}] + kept[1:]
        from forge_roles.library import (
            _openings_placed_where_the_brief_puts_them)

        before = json.dumps(component, sort_keys=True)
        notes = _openings_placed_where_the_brief_puts_them(
            component, _requirements(case), case["brief"])
        self.assertEqual(notes, [])
        self.assertEqual(json.dumps(component, sort_keys=True), before)

    def test_the_cable_hole_alone_is_never_taken_for_a_slot(self) -> None:
        """No slot outlines at all, and one 16 mm hole: it is the cable hole
        the record counts, not a slot."""
        case = _load(self.CASE)
        component = case["answer"]["document"]["components"][0]
        from forge_roles.library import (
            _openings_placed_where_the_brief_puts_them)

        component["features"] = [
            f for f in component["features"]
            if f.get("kind") != "profile_slot"]
        _openings_placed_where_the_brief_puts_them(
            component, _requirements(case), case["brief"])
        kinds = {f["id"]: f["kind"] for f in component["features"]}
        self.assertEqual(kinds["cable_hole"], "hole")


class WhatTheRunSaysAboutALoadNobodyNamed(unittest.TestCase):
    """The curved arm plate on Claude: its brief names no load, so the load
    questions were dropped -- by the user's rule, a brief that says nothing
    of a load has none -- and the run said "the brief states that this part
    carries no load", which it does not."""

    BRIEF = "Create a flat plate, 120 mm long."

    def _notes(self, brief: str) -> list:
        from forge_roles import RequirementsEngineer

        answer = {
            "risk_class": "low",
            "requirements": [{
                "id": "REQ_LENGTH", "statement": "The plate is 120 mm long.",
                "measurement": "bounding_box_x", "comparison": "equals",
                "threshold": {"magnitude": 120.0, "unit": "mm"},
                "rationale": "Stated.", "type": "geometric",
                "verification": "exact_geometry", "strength": "hard",
                "source": "user", "state": "accepted"}],
            "assumptions": [{
                "id": "ASM_LOAD", "statement": "The design load is a 50 N "
                "static force applied at the mounting holes.",
                "rationale": "No load is given.",
                "consequence_if_wrong": "The margin is wrong.",
                "risk": "high"}],
            "unknowns": [],
        }
        return [str(n) for n in RequirementsEngineer().parse(
            answer, brief=brief).notes if "load question" in str(n)]

    def test_a_brief_silent_on_load_is_not_quoted_as_saying_so(self) -> None:
        notes = self._notes(self.BRIEF)
        self.assertEqual(len(notes), 1)
        self.assertNotIn("states that this part carries no load", notes[0])
        self.assertIn("names no load", notes[0])

    def test_a_brief_that_says_so_is_quoted(self) -> None:
        notes = self._notes(self.BRIEF + " It carries no load.")
        self.assertEqual(len(notes), 1)
        self.assertIn("states that this part carries no load", notes[0])
