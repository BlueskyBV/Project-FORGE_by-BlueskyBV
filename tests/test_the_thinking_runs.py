"""The first runs with Claude thinking first, 14 and 15 October 2026.

Thinking made the designs right more often -- the L-bracket, the dome and
the stepper plate all came out correct the first time -- and made the runs
slow enough to break the transport: a lower-leg shell ran 65 minutes and
ended blocked because its designer, its analyst and its redesign were each
cut off at 600 s and sent again from the start. What was left was Forge's:

- a reply written for minutes was read whole, and timed out; it is now
  streamed, and the timeout is the longest silence, not the longest answer;
- every role thought at the model's full effort: the side rail's record
  cost 43 700 output tokens; each role now asks for the effort its job
  needs;
- a plain number in a slot declared in degrees was read as radians: the
  stepper plate's `360 / count` bolt-circle step came out 3437.7 degrees
  and an analyst round was spent rewriting it;
- a correct shell failed a "thinnest wall anywhere equals 8 mm" claim on
  the web between its opening and the holes the brief put beside it, and
  the wall measurement read 0.006 mm where a ray grazed out of the top rim.
"""

from __future__ import annotations

import io
import json
import math
import pathlib
import sys
import unittest

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from test_real_answers import (  # noqa: E402
    _design,
    _load,
    _not_passing,
    _requirements,
    _verify,
)


def _document(parameters, features=None):
    return {
        "schema_version": "1.0.0",
        "document_id": "00000000-0000-5000-8000-000000000000",
        "project_id": "00000000-0000-5000-8000-000000000000",
        "revision": 1, "name": "t",
        "units": {"length": "mm", "mass": "kg", "time": "s", "angle": "deg",
                  "force": "N", "stress": "MPa"},
        "risk_class": "low",
        "components": [{"id": "c", "parameters": parameters,
                        "features": features or [
                            {"id": "b", "kind": "box", "parameters": {
                                "size": {"vector": [10, 10, 10],
                                         "unit": "mm"}}}]}],
        "requirements": [], "assumptions": []}


class APlainNumberInADegreeSlotIsDegrees(unittest.TestCase):

    def _resolved(self, parameters):
        from forge_ir import Document

        document = Document.from_json(json.dumps(_document(parameters)))
        values = document.components[0].parameters.resolve().values
        return {k: v for k, v in values.items()}

    def _degrees(self, quantity) -> float:
        from forge_units import parse_unit

        return float(quantity.to(parse_unit("deg")).magnitude.midpoint)

    def test_a_step_round_a_circle(self) -> None:
        values = self._resolved([
            {"id": "count", "value": {"magnitude": 6, "unit": ""}},
            {"id": "step", "expression": "360 / count", "unit": "deg"},
            {"id": "radius", "value": {"magnitude": 28, "unit": "mm"}},
            {"id": "x2", "expression": "radius * cos(1 * step)",
             "unit": "mm"}])
        self.assertAlmostEqual(self._degrees(values["step"]), 60.0)
        self.assertAlmostEqual(float(values["x2"].magnitude.midpoint), 14.0,
                               places=6)

    def test_a_value_given_as_a_plain_number(self) -> None:
        values = self._resolved([
            {"id": "tilt", "value": {"magnitude": 45, "unit": ""},
             "unit": "deg"}])
        self.assertAlmostEqual(self._degrees(values["tilt"]), 45.0)

    def test_radians_worked_with_pi_stay_radians(self) -> None:
        values = self._resolved([
            {"id": "count", "value": {"magnitude": 6, "unit": ""}},
            {"id": "in_rad", "expression": "2 * pi / count", "unit": "rad"},
            {"id": "in_deg", "expression": "2 * pi / count", "unit": "deg"}])
        self.assertAlmostEqual(self._degrees(values["in_rad"]), 60.0)
        self.assertAlmostEqual(self._degrees(values["in_deg"]), 60.0)

    def test_a_number_added_to_an_angle_is_in_its_unit(self) -> None:
        from forge_expr import Expression
        from forge_units import Q

        known = {"alpha": Q(30, "deg"), "beta": Q(0.5, "rad")}
        for source, degrees in (("alpha + 10", 40.0), ("180 - 2 * alpha", 120.0),
                                ("alpha * 2", 60.0), ("alpha + pi / 6", 60.0),
                                ("10 + alpha", 40.0)):
            value = Expression.parse(source).evaluate_quantity(known)
            self.assertAlmostEqual(self._degrees(value), degrees, msg=source)
        radians = Expression.parse("beta + 1").evaluate_quantity(known)
        self.assertAlmostEqual(self._degrees(radians), math.degrees(1.5))

    def test_lengths_are_untouched(self) -> None:
        values = self._resolved([
            {"id": "w", "value": {"magnitude": 30, "unit": "mm"}},
            {"id": "half", "expression": "w / 2", "unit": "mm"}])
        self.assertAlmostEqual(float(values["half"].magnitude.midpoint), 15.0)

    def test_the_stepper_plate_s_bolt_circle_is_even(self) -> None:
        case = _load("stepper_bolt_circle_step_in_degrees_claude")
        report = _verify(_design(case))
        self.assertEqual(_not_passing(report), {})
        holes = [h for h in report.measurements["part"]["holes"]
                 if abs(h["diameter_mm"] - 4.5) < 1e-6]
        self.assertEqual(len(holes), 6)
        angles = sorted(math.degrees(math.atan2(h["centre_mm"][1],
                                                h["centre_mm"][0])) % 360
                        for h in holes)
        steps = [b - a for a, b in zip(angles, angles[1:])]
        for step in steps:
            self.assertAlmostEqual(step, 60.0, delta=0.5)


class ACorrectShellIsNotFailedOnItsWebs(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = _load("leg_shell_thinnest_wall_at_its_webs_claude")
        cls.record = _requirements(cls.case)
        cls.report = _verify(_design(cls.case))

    def test_the_thinnest_wall_claim_at_the_walls_figure_is_dropped(self) -> None:
        bindings = [str(r.get("measurement", "")) for r in
                    self.record.requirements]
        self.assertNotIn("minimum_wall_thickness", bindings)
        self.assertIn("wall_thickness", " ".join(bindings))
        self.assertTrue(any("the web between them" in n
                            for n in self.record.notes), self.record.notes)

    def test_it_passes(self) -> None:
        self.assertEqual(_not_passing(self.report), {})

    def test_a_thinnest_wall_claim_without_cuts_is_kept(self) -> None:
        from forge_roles.library import \
            _a_thinnest_wall_where_the_brief_cuts_the_wall as drop

        claims = [{"id": "A", "measurement": "wall_thickness",
                   "comparison": "equals",
                   "threshold": {"magnitude": 2, "unit": "mm"}},
                  {"id": "B", "measurement": "minimum_wall_thickness",
                   "comparison": "equals",
                   "threshold": {"magnitude": 2, "unit": "mm"}}]
        self.assertEqual(drop("A PLA cup 60 mm tall with 2 mm walls.",
                              claims), [])
        self.assertEqual(len(claims), 2)
        self.assertTrue(drop("A PLA cup with 2 mm walls and a 5 mm hole "
                             "in its side.", claims))
        self.assertEqual([c["id"] for c in claims], ["A"])


class AWallIsMeasuredAcrossIt(unittest.TestCase):
    """A ray that grazes out through a neighbouring face at a convex edge
    is not a wall."""

    def test_a_flared_cup_reads_its_walls(self) -> None:
        """A cup whose sides lean out: at its rim, a ray in from the outside
        tilts up and out through the rim's top after a few microns."""
        import math

        from forge_geom.measure import minimum_wall_thickness, surface_samples
        from forge_geom.sdf import ConeSDF, Difference

        lean = math.radians(10)
        outer = ConeSDF(base=(0, 0, 0), axis=(0, 0, 1), bottom_radius=30.0,
                        top_radius=30.0 + 40 * math.tan(lean), height=40.0)
        wall = 8.0 / math.cos(lean)
        inner = ConeSDF(base=(0, 0, 8), axis=(0, 0, 1),
                        bottom_radius=30.0 - wall + 8 * math.tan(lean),
                        top_radius=30.0 - wall + 48 * math.tan(lean),
                        height=40.0)
        cup = Difference(base=outer, tools=(inner,))
        samples = surface_samples(cup, resolution=72)
        thickness, where = minimum_wall_thickness(cup, samples)
        self.assertGreater(float(thickness.magnitude.lo), 7.0, where)


class EachRoleThinksAsHardAsItsJobNeeds(unittest.TestCase):

    def test_the_roles_ask_for_their_effort(self) -> None:
        from forge_roles import (BriefInterpreter, FailureAnalyst,
                                 ForgeIRDesigner, RequirementsEngineer)

        self.assertEqual(BriefInterpreter().effort_for(), "low")
        self.assertEqual(RequirementsEngineer().effort_for(), "medium")
        self.assertEqual(ForgeIRDesigner().effort_for(), "")
        self.assertEqual(FailureAnalyst().effort_for(
            failure={"kind": "gate"}), "")
        self.assertEqual(FailureAnalyst().effort_for(
            failure={"kind": "last_look"}), "low")

    def _payload(self, **kwargs):
        from forge_models import AnthropicProvider
        from forge_models.types import ModelRequest, user

        request = ModelRequest(system="s", messages=(user("u"),),
                               schema={"type": "object", "properties": {
                                   "a": {"type": "string"}}},
                               effort=kwargs.pop("asked", ""))
        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5",
                                     **kwargs)
        return provider._build_payload(request)  # noqa: SLF001

    def test_the_effort_asked_for_goes_on_the_wire(self) -> None:
        self.assertEqual(self._payload(asked="low")["output_config"],
                         {"effort": "low"})
        self.assertNotIn("output_config", self._payload(asked=""))

    def test_the_run_s_own_effort_wins(self) -> None:
        self.assertEqual(self._payload(asked="low", effort="high")[
            "output_config"], {"effort": "high"})

    def test_an_older_model_thinks_less_for_a_low_effort(self) -> None:
        from forge_models import AnthropicProvider
        from forge_models.types import ModelRequest, user

        request = ModelRequest(system="s", messages=(user("u"),),
                               schema={"type": "object"}, effort="low")
        payload = AnthropicProvider(
            api_key="k", model="claude-sonnet-4-20250514")._build_payload(
                request)
        self.assertEqual(payload["thinking"]["budget_tokens"], 4096)

    def test_an_effort_the_model_refuses_is_dropped_for_the_run(self) -> None:
        from unittest import mock
        import urllib.error

        from forge_models import AnthropicProvider
        from forge_models.types import ModelRequest, user

        sent = []

        def fake(request, timeout=None):
            body = json.loads(request.data)
            sent.append(body)
            if "output_config" in body:
                raise urllib.error.HTTPError(
                    "u", 400, "bad", {}, io.BytesIO(json.dumps({
                        "type": "error", "error": {
                            "type": "invalid_request_error",
                            "message": "output_config.effort: low is not "
                            "supported"}}).encode()))
            reply = json.dumps({
                "content": [{"type": "tool_use", "name": "submit_result",
                             "input": {"a": "x"}}],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
            return mock.MagicMock(__enter__=lambda s: io.BytesIO(reply),
                                  __exit__=lambda s, *a: False)

        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5")
        request = ModelRequest(system="s", messages=(user("u"),),
                               schema={"type": "object"}, effort="low")
        with mock.patch("forge_models.anthropic.urllib.request.urlopen", fake):
            provider._send(request)  # noqa: SLF001
            provider._send(request)  # noqa: SLF001
        self.assertEqual(["output_config" in b for b in sent],
                         [True, False, False])

    def test_the_heartbeat_says_how_far_the_answer_has_got(self) -> None:
        from forge_models.anthropic import _read_the_reply

        stream = (
            'event: message_start\ndata: {"type": "message_start", '
            '"message": {"id": "m", "content": [], "usage": {}}}\n\n'
            'event: content_block_start\ndata: {"type": "content_block_start",'
            ' "index": 0, "content_block": {"type": "thinking", '
            '"thinking": ""}}\n\n'
            'event: content_block_delta\ndata: {"type": "content_block_delta",'
            ' "index": 0, "delta": {"type": "thinking_delta", "thinking": "'
            + "x" * 400 + '"}}\n\n'
            'event: message_delta\ndata: {"type": "message_delta", "delta": '
            '{"stop_reason": "end_turn"}, "usage": {"output_tokens": 100}}\n\n'
            'event: message_stop\ndata: {"type": "message_stop"}\n\n')
        seen = []
        message = _read_the_reply(io.BytesIO(stream.encode()),
                                  lambda n, phase: seen.append((n, phase)))
        self.assertEqual(seen[-1], (400, "thinking"))
        self.assertEqual(message["content"][0]["thinking"], "x" * 400)


class TheSecondRoundOfThinkingRuns(unittest.TestCase):
    """15 October, after streaming: a flight-controller plate and the lower-
    leg shell both passed first time with no repair. The shell still took
    20 minutes and $2.37: its designer thought past its room and was cut
    off after six minutes, then was asked again to delete an empty
    `through`; its last look spent 16 500 tokens saying "nothing to change".
    Then the account ran out of credit, said as "refused the request
    mid-answer"."""

    def _request(self, effort, max_output=16384):
        from forge_models.types import ModelRequest, user

        return ModelRequest(system="s", messages=(user("u"),),
                            schema={"type": "object"}, effort=effort,
                            max_output_tokens=max_output)

    def test_a_full_effort_design_has_room_to_think(self) -> None:
        from forge_models import AnthropicProvider

        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5")
        self.assertEqual(provider._build_payload(self._request(""))[  # noqa: SLF001
            "max_tokens"], 16384 + 32000)
        self.assertEqual(provider._build_payload(self._request("low"))[  # noqa: SLF001
            "max_tokens"], 16384 + 8000)
        self.assertEqual(provider._build_payload(self._request("medium"))[  # noqa: SLF001
            "max_tokens"], 16384 + 16000)

    def test_an_empty_balance_is_said_plainly_and_not_retried(self) -> None:
        import urllib.error
        from unittest import mock

        from forge_models import AnthropicProvider
        from forge_models.errors import RequestError

        said = ("Your credit balance is too low to access the Anthropic "
                "API. Please go to Plans & Billing to upgrade or purchase "
                "credits.")

        def refused(request, timeout=None):
            raise urllib.error.HTTPError(
                "u", 400, "bad", {}, io.BytesIO(json.dumps({
                    "type": "error", "error": {
                        "type": "invalid_request_error",
                        "message": said}}).encode()))

        def in_the_stream(request, timeout=None):
            body = (
                'event: error\ndata: {"type": "error", "error": {"type": '
                '"invalid_request_error", "message": "' + said + '"}}\n\n')
            return mock.MagicMock(
                __enter__=lambda s: io.BytesIO(body.encode()),
                __exit__=lambda s, *a: False)

        for fake in (refused, in_the_stream):
            provider = AnthropicProvider(api_key="k", model="claude-sonnet-5")
            with mock.patch("forge_models.anthropic.urllib.request.urlopen",
                            fake), self.assertRaises(RequestError) as caught:
                provider.complete(self._request(""))
            self.assertIn("out of credit", str(caught.exception))
            self.assertNotIn("mid-answer", str(caught.exception))
            self.assertFalse(caught.exception.retryable)

    def test_the_heartbeat_says_thinking_before_a_word_is_written(self) -> None:
        from unittest import mock

        from forge_models import AnthropicProvider

        seen = []
        body = (
            'event: message_start\ndata: {"type": "message_start", '
            '"message": {"id": "m", "content": [], "usage": {}}}\n\n'
            'event: content_block_start\ndata: {"type": '
            '"content_block_start", "index": 0, "content_block": {"type": '
            '"tool_use", "id": "t", "name": "submit_result", "input": {}}}\n\n'
            'event: content_block_delta\ndata: {"type": '
            '"content_block_delta", "index": 0, "delta": {"type": '
            '"input_json_delta", "partial_json": "{}"}}\n\n'
            'event: content_block_stop\ndata: {"type": "content_block_stop",'
            ' "index": 0}\n\n'
            'event: message_delta\ndata: {"type": "message_delta", "delta": '
            '{"stop_reason": "tool_use"}, "usage": {"output_tokens": 3}}\n\n'
            'event: message_stop\ndata: {"type": "message_stop"}\n\n')

        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5")

        def fake(request, timeout=None):
            seen.append(provider.phase_so_far)
            return mock.MagicMock(__enter__=lambda s: io.BytesIO(body.encode()),
                                  __exit__=lambda s, *a: False)

        with mock.patch("forge_models.anthropic.urllib.request.urlopen", fake):
            provider._send(self._request(""))  # noqa: SLF001
        self.assertEqual(provider.phase_so_far, "writing")

    def test_the_heartbeat_line_names_the_phase_before_any_tokens(self) -> None:
        import contextlib
        import threading

        from forge_cli.design import _Progress
        from forge_models.types import ModelRequest, user

        class Inner:
            tokens_so_far = 0
            phase_so_far = ""
            retry = budget = None
            observers: list = []

        lines = []
        for phase, expected in (("thinking", ", thinking"),
                                ("writing", ", writing the answer"),
                                ("", ", reading the prompt")):
            inner = Inner()
            inner.phase_so_far = phase
            progress = _Progress.__new__(_Progress)
            progress._inner = inner
            progress._interval = 0.01
            stop = threading.Event()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                worker = threading.Thread(target=progress._tick, args=(
                    ModelRequest(system="s", messages=(user("u"),),
                                 purpose="forgeir_designer"), stop))
                worker.start()
                import time
                time.sleep(0.05)
                stop.set()
                worker.join()
            first = out.getvalue().splitlines()[0]
            lines.append(first)
            self.assertTrue(first.endswith(expected), first)

    def test_a_hole_with_its_own_position_and_an_empty_through_stays(self) -> None:
        from forge_roles.library import _resolve_the_placements

        component = {"id": "c", "parameters": [], "features": [
            {"id": "shell", "kind": "loft", "inputs": []},
            {"id": "hole_1", "kind": "hole", "inputs": ["shell"],
             "place": {"through": ""},
             "parameters": {"diameter": {"magnitude": 4.5, "unit": "mm"},
                            "position": {"vector": [36, 0, 50], "unit": "mm"},
                            "axis": [0, -1, 0], "through": "first_wall"}}]}
        notes, problems = _resolve_the_placements(component, None)
        self.assertEqual(problems, [])
        hole = component["features"][1]
        self.assertNotIn("place", hole)
        self.assertEqual(hole["parameters"]["position"]["vector"], [36, 0, 50])
        self.assertTrue(any("stays where its position puts it" in n
                            for n in notes))


class TheAnalystWritesItsEditsBesideItsStrategy(unittest.TestCase):

    def test_patches_come_straight_after_the_strategy(self) -> None:
        from forge_roles import FailureAnalyst

        order = list(FailureAnalyst().output_schema()["properties"])
        self.assertEqual(order[:3], ["diagnosis", "strategy", "patches"])


class AMaterialQuestionNothingReadsDoesNotHoldThePart(unittest.TestCase):

    def _record(self, unknowns, assumptions=(), requirements=None):
        from forge_roles.library import _a_material_nothing_measured_rests_on

        answer = {"requirements": list(requirements or []),
                  "assumptions": [dict(a) for a in assumptions],
                  "unknowns": [dict(u) for u in unknowns]}
        notes = _a_material_nothing_measured_rests_on(answer)
        return answer, notes

    def test_an_unknown_material_becomes_an_open_question(self) -> None:
        answer, notes = self._record([{
            "id": "UNK_MATERIAL", "critical": True,
            "question": "What material and grade (with its yield strength) "
                        "is the rail to be made from?"}])
        self.assertEqual(answer["unknowns"], [])
        opened = [a for a in answer["assumptions"]
                  if a["id"] == "ASM_OPEN_UNK_MATERIAL"]
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["risk"], "moderate")
        self.assertTrue(opened[0]["reversible"])
        self.assertTrue(notes)

    def test_it_still_holds_where_a_mass_is_claimed(self) -> None:
        answer, notes = self._record(
            [{"id": "UNK_MATERIAL", "question": "What material is it?"}],
            requirements=[{"id": "M", "measurement": "mass"}])
        self.assertEqual(len(answer["unknowns"]), 1)
        self.assertEqual(notes, [])

    def test_material_around_a_hole_is_not_a_material(self) -> None:
        answer, notes = self._record([], assumptions=[{
            "id": "ASM_MIN_EDGE_DISTANCE", "risk": "high", "reversible": True,
            "statement": "The 'continuous material around every hole' "
                         "requirement is a web of one hole diameter."}])
        self.assertEqual(answer["assumptions"][0]["risk"], "high")
        self.assertEqual(notes, [])

    def test_a_load_question_is_left_to_the_load_rules(self) -> None:
        answer, _ = self._record([{
            "id": "UNK_LOAD", "question": "What load does the steel arm "
                                          "carry?"}])
        self.assertEqual(len(answer["unknowns"]), 1)


class TheSideRailRunIsRight(unittest.TestCase):

    def test_its_design_passes(self) -> None:
        report = _verify(_design(_load("side_rail_with_thinking_claude")))
        self.assertEqual(_not_passing(report), {})
        holes = report.measurements["part"]["holes"]
        self.assertEqual(sum(1 for h in holes if h["present"]), 3)


if __name__ == "__main__":
    unittest.main()
