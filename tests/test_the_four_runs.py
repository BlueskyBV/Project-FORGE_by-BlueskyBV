"""Four runs on Claude Sonnet 5, the evening of 13 October 2026: a stepper
plate, a calf shell, a shaft collar and an L-bracket.

The plate released, and its last look cost two calls to say "matches". The
collar passed every check and then crashed: its last look rewrote a correct
set screw as `through: first_wall`, a repair Forge runs on set screws gave it
a `depth` back, the two together do not compile, and the last look did not
expect a change that does not build. The calf shell was blocked by Forge's
own checks: a 200 mm cutter through one 8 mm wall judged "buried", six holes
through the rear wall judged blocked by the front wall, the cutter's reach
judged a dimension the part lacks, and a tab rounded across its 12 mm side
-- which Forge then clamped again after every repair. The L-bracket was
offered a bend for the word "L-bracket", folded about the wrong line, and
the analyst, reading `along` the same way, wrote it back unchanged.

Each is tested here as the run met it.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
import unittest

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from fixtures.bracket_responses import (  # noqa: E402
    BRIEF,
    DESIGNER_VALID,
    INTERPRETER,
    REQUIREMENTS,
)
from test_eyes import (  # noqa: E402
    FAST,
    _a_design_one_figure_off,
    _SeeingProvider,
)
from test_unusual_briefs import _designed, _load, _record  # noqa: E402

from forge_models import ScriptedProvider  # noqa: E402
from forge_orchestrator import Orchestrator, OrchestratorConfig  # noqa: E402


def _document(component: dict, requirements: list | None = None) -> dict:
    return {
        "schema_version": "1.0.0", "revision": 1, "name": "probe",
        "document_id": "00000000-0000-5000-8000-000000000000",
        "project_id": "00000000-0000-5000-8000-000000000000",
        "units": {"length": "mm", "mass": "kg", "time": "s", "angle": "deg",
                  "force": "N", "stress": "MPa"},
        "risk_class": "low", "components": [component],
        "requirements": requirements or [], "assumptions": [],
    }


def _mm(value: float) -> dict:
    return {"magnitude": value, "unit": "mm"}


def _expr(text: str) -> dict:
    return {"expression": text, "unit": "mm"}


def _a_box_open_at_the_back(reach: float = 100.0) -> dict:
    """A hollow box, 80 x 60 x 40 with 4 mm walls: a 30 x 20 opening cut
    through its rear wall by an extrude from the middle, much longer than
    the wall; two 5 mm holes through the rear wall only."""
    features = [
        {"id": "outer", "kind": "box", "parameters": {
            "size": {"vector": ["length", "width", "height"], "unit": "mm"},
            "centered": True, "origin": {"vector": [0, 0, 0], "unit": "mm"}}},
        {"id": "inner", "kind": "box", "parameters": {
            "size": {"vector": ["length - 2 * wall", "width - 2 * wall",
                                "height - 2 * wall"], "unit": "mm"},
            "centered": True, "origin": {"vector": [0, 0, 0], "unit": "mm"}}},
        {"id": "hollow", "kind": "subtract", "inputs": ["outer", "inner"]},
        {"id": "mid", "kind": "datum_plane",
         "parameters": {"base": "XZ", "offset": _mm(0)}},
        {"id": "outline", "kind": "profile_rectangle", "inputs": ["mid"],
         "parameters": {"width": _expr("opening_width"),
                        "height": _expr("opening_height")}},
        {"id": "cutter", "kind": "extrude", "inputs": ["outline"],
         "parameters": {"distance": _expr("reach"), "mode": "normal"}},
        {"id": "opened", "kind": "subtract", "tags": ["rear_opening"],
         "inputs": ["hollow", "cutter"]},
        {"id": "hole_left", "kind": "hole", "inputs": ["opened"],
         "parameters": {"diameter": _expr("hole_diameter"),
                        "position": {"vector": [-25, 0, 0], "unit": "mm"},
                        "axis": [0, -1, 0], "through": "first_wall"}},
        {"id": "hole_right", "kind": "hole", "inputs": ["hole_left"],
         "parameters": {"diameter": _expr("hole_diameter"),
                        "position": {"vector": [25, 0, 0], "unit": "mm"},
                        "axis": [0, -1, 0], "through": "first_wall"}},
    ]
    parameters = [{"id": k, "value": _mm(v)} for k, v in (
        ("length", 80.0), ("width", 60.0), ("height", 40.0), ("wall", 4.0),
        ("opening_width", 30.0), ("opening_height", 20.0), ("reach", reach),
        ("hole_diameter", 5.0))]
    component = {"id": "box", "name": "box", "parameters": parameters,
                 "features": features,
                 "interfaces": [{"id": "rear_opening", "type": "custom",
                                 "geometry": "cutter.side"}]}
    requirements = [{
        "id": "REQ_ONE_OPENING", "statement": "One opening in the rear wall.",
        "measurement": "feature_count:hole:rear_opening",
        "comparison": "equals", "threshold": {"magnitude": 1, "unit": ""},
        "type": "geometric", "verification": "exact_geometry",
        "strength": "hard", "source": "user", "state": "accepted"}]
    return _document(component, requirements)


def _verified(payload: dict, depth: int = 6):
    from forge_ir import Document
    from forge_pipeline import verify_component

    document = Document.from_json(json.dumps(payload))
    return verify_component(document, document.components[0],
                            measurement_depth=depth, mesh_resolution=48)


def _failing(report) -> dict:
    return {r.gate.identifier: r.status.value for r in report.gate_results
            if r.status.value not in ("PASS", "NOT_APPLICABLE")}


class AHollowPartWithACutterThroughOneWall(unittest.TestCase):
    """The calf shell's three false failures, on a box small enough to
    measure in seconds."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.report = _verified(_a_box_open_at_the_back())

    def test_it_passes(self) -> None:
        self.assertEqual(_failing(self.report), {})

    def test_the_cutter_s_side_is_on_the_part(self) -> None:
        entity = self.report.part.geometry_map.get("cutter.side")
        self.assertEqual(entity.status.value, "live", entity.note)
        self.assertIn("cutter", entity.note)
        facts = self.report.measurements["part"]
        self.assertEqual(facts["features_without_a_surface"], [])

    def test_holes_through_one_wall_are_open_through_it(self) -> None:
        gate = next(r for r in self.report.gate_results
                    if r.gate.identifier == "GEOM_THROUGH_HOLES_OPEN")
        self.assertEqual(gate.status.value, "PASS", gate.evidence.detail)

    def test_the_cutter_s_reach_is_not_a_missing_dimension(self) -> None:
        said = self.report.measurements["part"]["dimensions"]
        reach = next(d for d in said if d.startswith("reach:"))
        self.assertIn("how far a cutter reaches", reach)

    def test_the_opening_is_counted_by_the_cut_that_carries_its_tag(
            self) -> None:
        gate = next(r for r in self.report.gate_results
                    if r.gate.identifier == "REQ_ONE_OPENING")
        self.assertEqual(gate.status.value, "PASS", gate.evidence.detail)

    def test_a_cutter_that_cuts_nothing_is_still_absent(self) -> None:
        # The cutter's own fraction is no longer the test -- a patch of it on
        # the part is -- so a cutter that never reaches the wall must still
        # be found out.
        short = _a_box_open_at_the_back(reach=10.0)
        report = _verified(short)
        failing = _failing(report)
        self.assertIn("IFACE_REAR_OPENING", failing)
        self.assertIn("cutter", report.measurements["part"][
            "features_without_a_surface"])


class TheCalfShellAsClaudeAnsweredIt(unittest.TestCase):
    """leg_rear_opening_claude: the designer's own answer, settled."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = _load("leg_rear_opening_claude")
        cls.draft = _designed(cls.case)

    def test_the_designer_is_not_sent_back(self) -> None:
        notes = " ".join(self.draft.notes)
        self.assertIn("`access_opening` is on the cut", notes)

    def test_the_tab_ends_are_rounded_across_their_width(self) -> None:
        component = json.loads(self.draft.document.to_json())["components"][0]
        tabs = {f["id"]: f["parameters"] for f in component["features"]
                if f["id"] in ("lower_tab_raw", "upper_tab_raw")}
        self.assertEqual(tabs["lower_tab_raw"]["edges"], "bottom_along_x")
        self.assertEqual(tabs["upper_tab_raw"]["edges"], "top_along_x")
        self.assertEqual(tabs["lower_tab_raw"]["edge_radius"]["expression"],
                         "tab_end_radius")

    def test_a_box_sized_by_a_derived_length_can_be_laid_down(self) -> None:
        # `lies` on a tab sized by `tab_total_length = overhang + embed`
        # read as "a size that does not resolve": two designer rounds.
        answer = copy.deepcopy(self.case["document"])
        for feature in answer["components"][0]["features"]:
            if feature["id"] == "lower_tab_raw":
                feature["lies"] = "standing"
        draft = _designed(self.case, answer)
        self.assertTrue(draft.document.components)

    def test_with_the_opening_turned_to_the_rear_it_passes(self) -> None:
        from forge_roles import ForgeIRDesigner
        from forge_roles.library import Intent
        from forge_roles.patch import Patch, apply_patches

        payload = json.loads(self.draft.document.to_json())
        turned = [{"op": "replace", "pointer": "/components/0/features/"
                   "access_cut_extrude/parameters/mode", "value": "normal"}]
        turned += [{"op": "replace", "pointer": f"/components/0/features/"
                    f"mount_hole_{k}/parameters/axis", "value": [0, -1, 0]}
                   for k in range(1, 7)]
        payload = apply_patches(payload, [Patch.from_dict(p) for p in turned])
        settled, _, _ = ForgeIRDesigner().settle(
            payload, intent=Intent(summary="s", part_kind="", stated=(),
                                   implied=(), unstated=()),
            requirements=_record(self.case), brief=self.case["brief"],
            answers={})
        report = _verified(settled, depth=6)
        self.assertEqual(_failing(report), {})


class TheCollarsLastLook(unittest.TestCase):
    def test_a_set_screw_through_the_first_wall_keeps_no_depth(self) -> None:
        from forge_roles.library import _a_set_screw_goes_through_one_wall

        component = {"parameters": [
            {"id": "od", "value": _mm(30.0)}], "features": [
            {"id": "body", "kind": "cylinder", "parameters": {
                "diameter": _expr("od"), "height": _mm(12.0)}},
            {"id": "bore", "kind": "hole", "inputs": ["body"], "parameters": {
                "diameter": _mm(16.0),
                "position": {"vector": [0, 0, 6], "unit": "mm"},
                "axis": [0, 0, 1]}},
            {"id": "screw", "kind": "hole", "inputs": ["bore"], "parameters": {
                "diameter": _mm(5.0),
                "position": {"vector": [0, 0, 6], "unit": "mm"},
                "axis": [1, 0, 0], "through": "first_wall"}}]}
        notes = _a_set_screw_goes_through_one_wall(
            component, "one 5 mm set screw hole passes through the wall from "
            "the outside into the bore")
        self.assertEqual(notes, [])
        self.assertNotIn("depth", component["features"][2]["parameters"])

    def test_first_wall_and_a_depth_together_keep_first_wall(self) -> None:
        from forge_roles.library import _a_first_wall_hole_given_a_depth

        component = {"features": [{"id": "h", "kind": "hole", "parameters": {
            "through": "first_wall", "depth": _mm(15.0)}}]}
        self.assertTrue(_a_first_wall_hole_given_a_depth(component))
        self.assertEqual(component["features"][0]["parameters"],
                         {"through": "first_wall"})

    def test_the_collar_as_answered_passes(self) -> None:
        draft = _designed(_load("collar_last_look_claude"))
        report = _verified(json.loads(draft.document.to_json()))
        self.assertEqual(_failing(report), {})

    def _look(self, *analyst):
        provider = _SeeingProvider([INTERPRETER, REQUIREMENTS, DESIGNER_VALID,
                                    *analyst])
        run = Orchestrator(provider, config=FAST).design(BRIEF)
        looks = [r for r in provider.requests
                 if r.purpose == "failure_analyst"]
        return run, looks

    def test_a_change_that_does_not_build_releases_the_part_as_passed(
            self) -> None:
        plain = Orchestrator(ScriptedProvider(
            [INTERPRETER, REQUIREMENTS, DESIGNER_VALID]),
            config=FAST).design(BRIEF)
        unbuildable = {
            "diagnosis": "The bore looks too wide.", "strategy": "shrink it",
            "confidence": "low", "abandon": False,
            "patches": [{"op": "replace", "pointer": "/components/0/"
                         "parameters/bore_diameter/value",
                         "value": {"magnitude": -4.0, "unit": "mm"}}]}
        run, _ = self._look(unbuildable)
        self.assertIs(run.state, plain.state)
        self.assertNotEqual((run.failure or {}).get("code"), "OR1004_INTERNAL")
        self.assertFalse(any("internal error" in e.summary
                             for e in run.events), run.render())

    def test_no_edit_and_no_abandon_is_nothing_to_change_in_one_call(
            self) -> None:
        said_nothing = {"diagnosis": "Everything matches the brief.",
                        "strategy": "No change -- release as built.",
                        "confidence": "high", "abandon": False, "patches": []}
        run, looks = self._look(said_nothing)
        self.assertEqual(len(looks), 1)
        self.assertEqual(run.repairs[-1].outcome, "looked: nothing to change")


class AnExtrudeWrittenTheOtherWay(unittest.TestCase):
    def test_a_negative_distance_turns_the_extrude(self) -> None:
        from forge_roles.library import _an_extrude_given_a_negative_distance

        component = {"parameters": [{"id": "reach", "value": _mm(200.0)}],
                     "features": [{"id": "cut", "kind": "extrude",
                                   "parameters": {"distance": _expr("-reach"),
                                                  "mode": "normal"}}]}
        self.assertTrue(_an_extrude_given_a_negative_distance(component))
        self.assertEqual(component["features"][0]["parameters"],
                         {"distance": _expr("reach"), "mode": "reverse"})

    def test_a_negative_name_that_is_positive_is_left_alone(self) -> None:
        from forge_roles.library import _an_extrude_given_a_negative_distance

        component = {"parameters": [{"id": "drop", "value": _mm(-20.0)}],
                     "features": [{"id": "cut", "kind": "extrude",
                                   "parameters": {"distance": _expr("-drop")}}]}
        self.assertEqual(_an_extrude_given_a_negative_distance(component), [])


class TheLBracket(unittest.TestCase):
    def test_a_bracket_with_no_word_for_a_bend_is_not_offered_one(
            self) -> None:
        from forge_roles.library import _the_kinds_the_brief_asks_for

        brief = _load("l_bracket_bend_claude")["brief"]
        self.assertNotIn("bend", _the_kinds_the_brief_asks_for(brief))
        self.assertIn("bend", _the_kinds_the_brief_asks_for(
            "A steel L-bracket from 3 mm plate, bent 90 degrees in the "
            "middle."))

    def test_along_written_as_the_crease_is_turned_by_the_record(
            self) -> None:
        from forge_kernel import Compiler

        draft = _designed(_load("l_bracket_bend_claude"))
        self.assertTrue(any("the crease's own direction" in n
                            for n in draft.notes), draft.notes)
        bend = next(f for f in json.loads(draft.document.to_json())[
            "components"][0]["features"] if f["kind"] == "bend")
        along = bend["parameters"]["along"]
        along = along.get("vector", along) if isinstance(along, dict) else along
        self.assertEqual([float(c.get("magnitude", c)) if isinstance(c, dict)
                          else float(c) for c in along], [0.0, 1.0, 0.0])
        part = Compiler().compile_component(draft.document.components[0])
        size = np.asarray(part.solid.envelope.hi) - np.asarray(
            part.solid.envelope.lo)
        self.assertAlmostEqual(float(size[0]), 60.0, places=1)
        self.assertLess(abs(float(size[1]) - 50.0), 2.0)
        self.assertLess(abs(float(size[2]) - 40.0), 2.0)

    def test_the_analyst_is_told_what_the_bend_does_in_numbers(self) -> None:
        from forge_orchestrator.orchestrator import _what_each_bend_does

        draft = _designed(_load("l_bracket_bend_claude"))
        report = _verified(json.loads(draft.document.to_json()))
        failing = [r for r in report.gate_results
                   if r.status.value == "FAIL"]
        said = _what_each_bend_does(report, failing)
        self.assertEqual(len(said), 1, _failing(report))
        self.assertIn("crease along x at y = 50 mm", said[0])
        self.assertIn("1.644 mm", said[0])
        self.assertIn("boxes joined by a `union`", said[0])


class AFailedDesignIsDesignedAgain(unittest.TestCase):
    GIVES_UP = {"diagnosis": "I cannot see what to change.",
                "strategy": "", "confidence": "low", "abandon": True,
                "abandon_reason": "no grounded edit", "patches": []}

    def _run(self, redesigns: int):
        provider = ScriptedProvider([
            INTERPRETER, REQUIREMENTS, _a_design_one_figure_off(),
            self.GIVES_UP, self.GIVES_UP, DESIGNER_VALID])
        config = OrchestratorConfig(measurement_depth=6, mesh_resolution=48,
                                    redesigns=redesigns)
        run = Orchestrator(provider, config=config).design(BRIEF)
        designs = [r for r in provider.requests
                   if r.purpose == "forgeir_designer"]
        return run, designs

    def test_off_it_stops_as_it_did(self) -> None:
        from forge_evidence import Status

        run, designs = self._run(0)
        self.assertIs(run.report.overall_status, Status.FAIL)
        self.assertEqual(len(designs), 1)

    def test_on_it_designs_again_told_what_failed_and_passes(self) -> None:
        from forge_evidence import Status

        run, designs = self._run(1)
        self.assertEqual(len(designs), 2)
        told = designs[1].messages[0].content
        self.assertIn("<a_design_that_failed>", told)
        self.assertIn("32 mm", told)
        # Every check passes; the bracket's load assumption still blocks
        # release, as it does for the design that passes first time.
        self.assertIsNot(run.report.overall_status, Status.FAIL, run.render())
        self.assertFalse(_failing(run.report).get("REQ_SHAFT_HEIGHT"))
        self.assertTrue(any("designing the part again" in e.summary
                            for e in run.events))

    def test_a_second_design_no_better_leaves_the_first(self) -> None:
        provider = ScriptedProvider([
            INTERPRETER, REQUIREMENTS, _a_design_one_figure_off(),
            self.GIVES_UP, self.GIVES_UP, _a_design_one_figure_off(),
            self.GIVES_UP, self.GIVES_UP])
        config = OrchestratorConfig(measurement_depth=6, mesh_resolution=48,
                                    redesigns=1)
        run = Orchestrator(provider, config=config).design(BRIEF)
        from forge_evidence import Status

        self.assertIs(run.report.overall_status, Status.FAIL)
        self.assertTrue(any("the first design stands" in e.summary
                            for e in run.events), run.render())


class TheAnalystHearsWhatItsEditDid(unittest.TestCase):
    def test_a_value_written_back_as_it_was_is_named(self) -> None:
        from forge_orchestrator.orchestrator import (
            _patches_that_change_nothing,
        )

        payload = copy.deepcopy(DESIGNER_VALID["document"])
        lever = next(p for p in payload["components"][0]["parameters"]
                     if p["id"] == "lever_arm")
        patches = [
            {"op": "replace",
             "pointer": "/components/0/parameters/lever_arm/value",
             "value": copy.deepcopy(lever["value"])},
            {"op": "replace",
             "pointer": "/components/0/parameters/lever_arm/value",
             "value": {"magnitude": 33.0, "unit": "mm"}},
        ]
        self.assertEqual(_patches_that_change_nothing(payload, patches), [0])


class TheEyesMarkABlockedHole(unittest.TestCase):
    def test_a_blocked_through_hole_is_marked_where_it_is_blocked(
            self) -> None:
        from forge_pipeline.render import marks_from_report

        report = _verified(_a_box_open_at_the_back())

        class _Gate:
            identifier = "GEOM_THROUGH_HOLES_OPEN"

        class _Status:
            value = "FAIL"

        class _Evidence:
            detail = {"blocked": [{"feature": "post_hole",
                                   "from": [1.0, 2.0, 3.0]}]}

        class _Result:
            gate, status, evidence = _Gate(), _Status(), _Evidence()

        class _Report:
            part = report.part
            gate_results = (_Result(),)

        marks = marks_from_report(_Report())
        self.assertEqual([(m.label, m.point) for m in marks],
                         [("post_hole BLOCKED", (1.0, 2.0, 3.0))])


class FasterAndTheSame(unittest.TestCase):
    """A chain of cuts is one difference, culled by where its tools are --
    the same field to the last bit, and the same decisions about cells."""

    def test_the_flattened_chain_is_the_same_field(self) -> None:
        from forge_geom.sdf import BoxSDF, CylinderSDF, Difference
        from forge_kernel.implicit_backend import _taken_from

        plate = BoxSDF((0.0, 0.0, 4.0), (60.0, 40.0, 4.0))
        holes = [CylinderSDF(base=(x, y, -10.0), axis=(0.0, 0.0, 1.0),
                             radius=2.5, height=30.0)
                 for x in (-45.0, -15.0, 15.0, 45.0) for y in (-25.0, 25.0)]
        nested = plate
        flat = plate
        for hole in holes:
            nested = Difference(nested, (hole,))
            flat = _taken_from(flat, (hole,))
        self.assertIsInstance(flat.base, BoxSDF)
        points = np.random.default_rng(3).uniform(
            (-70, -50, -5), (70, 50, 13), size=(20_000, 3))
        self.assertTrue(np.array_equal(nested(points), flat(points)))

    def test_bounds_still_enclose_the_field(self) -> None:
        from forge_geom.sdf import BoxSDF, CylinderSDF, Difference

        plate = BoxSDF((0.0, 0.0, 4.0), (60.0, 40.0, 4.0))
        holes = tuple(CylinderSDF(base=(x, y, -10.0), axis=(0.0, 0.0, 1.0),
                                  radius=2.5, height=30.0)
                      for x in np.linspace(-50, 50, 6)
                      for y in (-25.0, 25.0))
        solid = Difference(plate, holes)
        rng = np.random.default_rng(7)
        lo = rng.uniform((-70, -50, -5), (70, 50, 13), size=(4096, 3))
        hi = lo + rng.uniform(0.2, 6.0, size=(4096, 3))
        bound_lo, bound_hi = solid.bounds((lo, hi))
        for t in rng.uniform(0, 1, size=(6, 3)):
            values = solid(lo + (hi - lo) * t)
            self.assertTrue(np.all(values >= bound_lo - 1e-9))
            self.assertTrue(np.all(values <= bound_hi + 1e-9))


if __name__ == "__main__":
    unittest.main()
