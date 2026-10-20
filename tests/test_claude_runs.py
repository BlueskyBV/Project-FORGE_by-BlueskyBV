"""The first runs on Claude Sonnet 5 of briefs a local model had passed.

Each failed for something Forge did or read wrong, on a part that was right
or a slip Forge can take back: a blind hole's bore checked in the wrong
place, a roundness claimed about the wrong axis, fields a model wrote inside
another field, an analyst that counted array positions wrong, counterbores
on the face the brief does not name.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).parent / "fixtures" / "real_runs"


def _load(name: str) -> dict:
    return json.loads((HERE / f"{name}.json").read_text())


def _verify(document: dict):
    from forge_ir import Document
    from forge_pipeline import verify_component

    built = Document.from_json(json.dumps(document, default=str))
    return verify_component(built, built.components[0], measurement_depth=8)


def _failing(report) -> dict:
    return {r.gate.identifier: r.status.value for r in report.gate_results
            if r.status.value not in ("PASS", "NOT_APPLICABLE")}


class ASetScrewDrilledFromTheAxisOut(unittest.TestCase):
    """The collar: its set screw drilled from the axis out through the wall,
    `depth` the radius. In the part, plainly; reported "NOT IN THE PART"
    four ways, because a blind hole's bore was checked along the whole line
    through its position -- centred on the axis, in the empty main bore."""

    def test_the_hole_that_is_there_is_found(self) -> None:
        report = _verify(_load("collar_set_screw_from_the_axis_claude")[
            "document"])
        self.assertEqual(_failing(report), {})

    def test_a_blind_hole_into_solid_is_still_checked(self) -> None:
        """Drilled before the bore, into solid: still read where it cuts."""
        document = copy.deepcopy(_load(
            "collar_set_screw_from_the_axis_claude")["document"])
        features = document["components"][0]["features"]
        body, bore, screw = features
        screw["inputs"] = [body["id"]]
        bore["inputs"] = [screw["id"]]
        document["components"][0]["features"] = [body, screw, bore]
        self.assertNotIn("GEOM_BORES_SURVIVE", _failing(_verify(document)))


class ADomeOnItsSide(unittest.TestCase):
    """Half a sphere, flat side to the left: the record claimed it round
    about Z, at least 1. On its side it is round about X, and nothing
    measured is exactly 1."""

    def test_the_claim_is_read_as_the_part_can_meet_it(self) -> None:
        from forge_roles import RequirementsEngineer

        case = _load("dome_left_claude")
        record = RequirementsEngineer().parse(case["requirements"],
                                              brief=case["brief"])
        claim = next(r for r in record.requirements
                     if r["id"] == "REQ_ROUNDNESS_ABOUT_Z")
        self.assertEqual(claim["measurement"], "roundness")
        self.assertEqual(claim["threshold"]["magnitude"], 0.95)
        document = copy.deepcopy(case["document"])
        document["requirements"] = [dict(r) for r in record.requirements]
        self.assertEqual(_failing(_verify(document)), {})

    def test_a_dome_flat_side_down_keeps_its_axis(self) -> None:
        from forge_roles.library import _roundness_the_part_can_show

        claims = [{"id": "R", "measurement": "roundness_about_z",
                   "comparison": "at_least",
                   "threshold": {"magnitude": 0.95, "unit": ""}}]
        self.assertEqual(_roundness_the_part_can_show(
            "A dome, half of a 70 mm sphere, flat side down.", claims), [])
        self.assertEqual(claims[0]["measurement"], "roundness_about_z")


class FieldsWrittenInsideAnotherField(unittest.TestCase):
    """The interpreter's `stated` came back as one string holding every
    later field in tag form; Forge read 2464 one-character facts."""

    def test_the_interpreter_s_fields_are_put_back(self) -> None:
        from forge_models.leaks import recover_leaked_fields
        from forge_roles import BriefInterpreter

        case = _load("cube_intent_leaked_claude")
        role = BriefInterpreter()
        fixed = recover_leaked_fields(case["tool_input"], role.output_schema())
        intent = role.parse(fixed, brief=case["brief"])
        self.assertEqual(len(intent.stated), 6)
        self.assertEqual(len(intent.implied), 3)
        self.assertEqual(len(intent.unstated), 10)
        self.assertEqual(fixed["suggested_name"],
                         "Hollow PLA Cube Shell, Open-Face")

    def test_a_parameter_tag_inside_a_string(self) -> None:
        from forge_models.leaks import recover_leaked_fields
        from forge_roles import FailureAnalyst

        fixed = recover_leaked_fields(
            {"diagnosis": "Wrong side.</diagnosis>\n<parameter name="
             "\"strategy\">Flip entry.", "strategy": "", "patches": []},
            FailureAnalyst().output_schema())
        self.assertEqual(fixed["diagnosis"], "Wrong side.")
        self.assertEqual(fixed["strategy"], "Flip entry.")

    def test_prose_with_angle_brackets_is_left_alone(self) -> None:
        from forge_models.leaks import recover_leaked_fields
        from forge_roles import FailureAnalyst

        answer = {"diagnosis": "The margin is < 1 and the <b> tag is prose.",
                  "strategy": "s", "patches": []}
        self.assertEqual(recover_leaked_fields(
            answer, FailureAnalyst().output_schema()), answer)

    def test_a_list_field_written_as_one_string(self) -> None:
        from forge_roles.library import _strings_of

        self.assertEqual(_strings_of("one fact"), ("one fact",))
        self.assertEqual(_strings_of("a\nb"), ("a", "b"))
        self.assertEqual(_strings_of(["x", "y"]), ("x", "y"))


class TheAnalystsAddresses(unittest.TestCase):
    """Fixing four corner holes at positions 15 to 18, the analyst wrote 16
    to 19: one hole was never fixed, and the bore got a counterbore entry."""

    SLICE = {"/components/0": {"features": [
        {"id": "plate"}, {"id": "corner_hole_1"}, {"id": "corner_hole_2"}]}}

    def _parse(self, answer: dict):
        from forge_roles import FailureAnalyst

        return FailureAnalyst().parse(answer, document_slice=self.SLICE)

    def test_a_patch_aimed_at_the_wrong_feature_is_sent_back(self) -> None:
        from forge_roles.base import RoleOutputError

        with self.assertRaises(RoleOutputError) as caught:
            self._parse({"diagnosis": "d", "strategy": "s", "patches": [{
                "op": "replace",
                "pointer": "/components/0/features/2/parameters/entry",
                "value": "end", "reason": "corner_hole_1: from the top"}]})
        self.assertIn("corner_hole_1", " ".join(caught.exception.problems))

    def test_a_feature_addressed_by_its_id(self) -> None:
        from forge_roles.patch import Patch, apply_patches

        document = {"components": [{"features": [
            {"id": "plate", "parameters": {}},
            {"id": "corner_hole_1", "parameters": {"entry": "start"}}]}]}
        patched = apply_patches(document, [Patch(
            "replace", "/components/0/features/corner_hole_1/parameters/entry",
            "end")])
        self.assertEqual(patched["components"][0]["features"][1]["parameters"],
                         {"entry": "end"})

    def test_no_edit_is_asked_for_once_more_then_kept_as_an_abandon(
            self) -> None:
        """A diagnosis and no patches is asked again, its own strategy
        quoted back -- three runs ended on a fix written out in words and
        never made. Still no edit on the last attempt: an abandon, its
        diagnosis the reason."""
        from forge_roles import FailureAnalyst
        from forge_roles.base import RoleOutputError

        answer = {"diagnosis": "The design is right; the check reads the "
                  "wrong place.", "strategy": "Take the radius from the "
                  "shorter side.", "patches": []}
        with self.assertRaises(RoleOutputError) as raised:
            self._parse(answer)
        self.assertIn("Take the radius from the shorter side",
                      " ".join(raised.exception.problems))
        proposal = FailureAnalyst().salvage(answer, raised.exception.problems)
        self.assertTrue(proposal.abandon)
        self.assertIn("design is right", proposal.abandon_reason)

    def test_the_analyst_is_told_where_each_feature_is(self) -> None:
        from forge_roles import FailureAnalyst

        text = FailureAnalyst().build_messages(
            failure={}, document_slice=self.SLICE)[0].content
        self.assertIn("/components/0/features/1 = corner_hole_1", text)


class TheStepperPlateOnClaude(unittest.TestCase):
    """Claude's own stepper plate: every counterbore on the underside, the
    brief saying from the top. Turned over by Forge, it passes everything."""

    def test_it_passes_as_drawn_less_the_counterbores_face(self) -> None:
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from test_real_answers import _design, _not_passing
        from test_real_answers import _verify as verify

        draft = _design(_load("stepper_plate_claude_sonnet_5"))
        self.assertIn("_counterbores_on_the_face_the_brief_names",
                      draft.repairs_made)
        self.assertEqual(_not_passing(verify(draft)), {})
