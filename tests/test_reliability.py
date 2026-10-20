"""A run is not ended by one bad answer.

Two runs on Claude, 13 October 2026: a stepper plate one gate from release
ended "internal error" because the failure analyst's patches came back as a
list of strings; a calf shell ended "two requirements disagree" because one
repair fixed the opening and broke the pivots -- with rounds still in hand.
"""

from __future__ import annotations

import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from fixtures.bracket_responses import (  # noqa: E402
    BRIEF,
    DESIGNER_VALID,
    INTERPRETER,
    REQUIREMENTS,
)

from forge_models import ScriptedProvider  # noqa: E402
from forge_orchestrator import Orchestrator, OrchestratorConfig  # noqa: E402

FAST = OrchestratorConfig(measurement_depth=6, mesh_resolution=48)


def _one_figure_off() -> dict:
    answer = copy.deepcopy(DESIGNER_VALID)
    for parameter in answer["document"]["components"][0]["parameters"]:
        if parameter["id"] == "lever_arm":
            parameter["value"]["magnitude"] = 40.0
    return answer


def _patch(name: str, magnitude: float) -> dict:
    return {"op": "replace",
            "pointer": f"/components/0/parameters/{name}/value",
            "value": {"magnitude": magnitude, "unit": "mm"},
            "reason": "the brief's figure"}


FIXES_ONE_BREAKS_ANOTHER = {
    "diagnosis": "lever_arm is 40, the brief says 32; and a bigger bore.",
    "strategy": "set lever_arm to 32 and the bore to 25",
    "confidence": "medium", "abandon": False,
    "patches": [_patch("lever_arm", 32.0), _patch("bore_diameter", 25.0)],
}
FIXES_ONE = {
    "diagnosis": "lever_arm is 40, the brief says 32.",
    "strategy": "set lever_arm to 32",
    "confidence": "high", "abandon": False,
    "patches": [_patch("lever_arm", 32.0)],
}
PATCHES_AS_TEXT = {
    "diagnosis": "lever_arm is 40, the brief says 32.",
    "strategy": "set lever_arm to 32",
    "confidence": "high", "abandon": False,
    "patches": ["replace /components/0/parameters/lever_arm/value with 32 mm"],
}


def _run(*analyst):
    provider = ScriptedProvider([INTERPRETER, REQUIREMENTS, _one_figure_off(),
                                 *analyst])
    run = Orchestrator(provider, config=FAST).design(BRIEF)
    calls = [r for r in provider.requests if r.purpose == "failure_analyst"]
    return run, calls


class OneBadRepairIsNotAConflict(unittest.TestCase):
    def test_it_is_taken_back_and_the_analyst_told_what_it_broke(self) -> None:
        run, calls = _run(FIXES_ONE_BREAKS_ANOTHER, FIXES_ONE)
        self.assertNotEqual((run.failure or {}).get("code"),
                            "OR1005_TRADED_FAILURE", run.render())
        self.assertTrue(run.repairs[0].outcome.startswith(
            "reverted: it broke REQ_BORE_DIAMETER"), run.repairs[0].outcome)
        self.assertIn("(it did fix REQ_SHAFT_HEIGHT)", run.repairs[0].outcome)
        self.assertEqual(len(calls), 2)
        self.assertIn("reverted: it broke REQ_BORE_DIAMETER",
                      calls[1].messages[0].content)
        failing = {g.gate.identifier for g in run.report.gate_results
                   if g.status.value == "FAIL"}
        self.assertNotIn("REQ_SHAFT_HEIGHT", failing)
        self.assertNotIn("REQ_BORE_DIAMETER", failing)

    def test_the_same_requirement_broken_twice_is_a_conflict(self) -> None:
        again = copy.deepcopy(FIXES_ONE_BREAKS_ANOTHER)
        again["patches"][1]["value"]["magnitude"] = 26.0
        run, _ = _run(FIXES_ONE_BREAKS_ANOTHER, again)
        self.assertEqual(run.failure["code"], "OR1005_TRADED_FAILURE")


class PatchesWrittenAsText(unittest.TestCase):
    def test_are_asked_for_again_not_a_crash(self) -> None:
        run, calls = _run(PATCHES_AS_TEXT, FIXES_ONE)
        self.assertNotEqual((run.failure or {}).get("code"),
                            "OR1004_INTERNAL", run.render())
        self.assertEqual(len(calls), 2)
        said = calls[1].messages[-1].content
        self.assertIn("`patches[0]` must be an object", said)


if __name__ == "__main__":
    unittest.main()


class ASizeWrittenAsABareList(unittest.TestCase):
    """ForgeIR takes `"size": [120, 80, 8]`; one of Forge's readers took only
    `{"vector": [...]}` and a stepper plate's first answer ended the run."""

    def test_a_design_with_bare_vectors_is_read(self) -> None:
        import json

        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from test_unusual_briefs import _designed, _load

        case = _load("stepper_plate_chamfer_box_claude")
        document = copy.deepcopy(case["document"])
        for feature in document["components"][0]["features"]:
            for name in ("size", "origin", "position"):
                value = (feature.get("parameters") or {}).get(name)
                if isinstance(value, dict) and "vector" in value:
                    feature["parameters"][name] = value["vector"]
        # An orphaned length too, so the reader that crashed is reached.
        document["components"][0]["parameters"].append(
            {"id": "plate_margin", "value": {"magnitude": 3, "unit": "mm"}})
        try:
            draft = _designed(case, document)
        except Exception as error:  # noqa: BLE001
            from forge_roles.base import RoleOutputError

            self.assertIsInstance(error, RoleOutputError)
            self.assertFalse(any("Forge could not read" in p
                                 for p in error.problems), error.problems)
        else:
            plate = next(f for f in draft.document.components[0].features
                         if f.identifier == "plate")
            self.assertIsNotNone(plate)
        self.assertTrue(json.dumps(document))

    def test_the_two_forms_build_the_same_part(self) -> None:
        import json

        from forge_ir import Document
        from forge_kernel import Compiler

        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from test_unusual_briefs import _load

        full = _load("stepper_plate_chamfer_box_claude")["document"]
        bare = copy.deepcopy(full)
        for feature in bare["components"][0]["features"]:
            value = (feature.get("parameters") or {}).get("size")
            if isinstance(value, dict):
                feature["parameters"]["size"] = value["vector"]
        hashes = [Compiler().compile_component(Document.from_json(
            json.dumps(d)).components[0]).solid.envelope for d in (full, bare)]
        self.assertEqual(hashes[0], hashes[1])


class AFaultInForgesReadingIsARetry(unittest.TestCase):
    def test_the_model_is_asked_again_and_the_fault_is_said(self) -> None:
        from forge_roles import BriefInterpreter
        from forge_roles.base import RepairExhaustedError

        class Tripping(BriefInterpreter):
            calls = 0

            def parse(self, structured, **inputs):
                Tripping.calls += 1
                if Tripping.calls == 1:
                    return [].get("x")  # a reader written for another shape
                return super().parse(structured, **inputs)

        provider = ScriptedProvider([INTERPRETER, INTERPRETER])
        try:
            result = Tripping().run(provider, brief=BRIEF)
        except RepairExhaustedError as error:  # pragma: no cover
            self.fail(f"not retried: {error}")
        self.assertEqual(result.attempts, 2)
        said = result.problems_seen[0][0]
        self.assertIn("Forge could not read this answer -- AttributeError", said)
        self.assertIn("(test_reliability.py:", said)


class EveryVectorInOneForm(unittest.TestCase):
    def test_settling_writes_a_bare_size_in_full(self) -> None:
        from forge_roles.library import _vectors_written_in_full

        component = {"features": [
            {"id": "b", "kind": "box", "parameters": {"size": [1, 2, 3],
                                                      "origin": [0, 0, "t"]}},
            {"id": "h", "kind": "hole", "inputs": ["b"], "parameters": {
                "diameter": {"magnitude": 2, "unit": "mm"},
                "position": [0, 0, 0], "axis": [0, 0, 1]}}]}
        _vectors_written_in_full(component)
        box, hole = component["features"]
        self.assertEqual(box["parameters"]["size"],
                         {"vector": [1, 2, 3], "unit": "mm"})
        self.assertEqual(box["parameters"]["origin"],
                         {"vector": [0, 0, "t"], "unit": "mm"})
        self.assertEqual(hole["parameters"]["position"],
                         {"vector": [0, 0, 0], "unit": "mm"})
        # A direction is not a displacement and stays as written.
        self.assertEqual(hole["parameters"]["axis"], [0, 0, 1])


class AnyShapeOfAnswerIsACorrectionNeverACrash(unittest.TestCase):
    """Fuzzed: every field of real designs and records replaced, one at a
    time, by values of the wrong kind. Each is now a correction the model is
    sent, or read as what it means -- none takes Forge down."""

    def _design(self, mutate):
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from test_unusual_briefs import _designed, _load

        case = _load("calf_tabs_and_opening_claude")
        document = copy.deepcopy(case["document"])
        mutate(document["components"][0])
        return _designed(case, document)

    def _refused(self, mutate) -> list[str]:
        from forge_roles.base import RoleOutputError

        with self.assertRaises(RoleOutputError) as raised:
            self._design(mutate)
        return list(raised.exception.problems)

    def test_a_feature_that_is_not_an_object(self) -> None:
        said = self._refused(lambda c: c["features"].append("a hole"))
        self.assertTrue(any("must be an object" in p for p in said), said)

    def test_parameters_that_are_not_an_object(self) -> None:
        def mutate(c):
            c["features"][5]["parameters"] = "wide"
        said = self._refused(mutate)
        self.assertTrue(any("keyed by parameter name" in p for p in said))

    def test_a_unit_that_is_not_a_unit(self) -> None:
        def mutate(c):
            c["parameters"][0]["value"]["unit"] = "plate_length"
        said = self._refused(mutate)
        self.assertTrue(any("is not a unit" in p for p in said), said)

    def test_a_flag_that_is_not_true_or_false(self) -> None:
        def mutate(c):
            box = next(f for f in c["features"] if f["kind"] == "box")
            box["parameters"]["centered"] = "yes"
        said = self._refused(mutate)
        self.assertTrue(any("true or false" in p for p in said), said)

    def test_one_name_declared_twice(self) -> None:
        def mutate(c):
            c["parameters"].append(copy.deepcopy(c["parameters"][0]))
        said = self._refused(mutate)
        self.assertTrue(any("more than once" in p for p in said), said)

    def test_parameters_as_name_value_pairs_are_read(self) -> None:
        def mutate(c):
            box = next(f for f in c["features"] if f["kind"] == "box")
            box["parameters"] = [{"name": k, "value": v}
                                 for k, v in box["parameters"].items()]
        self.assertIsNotNone(self._design(mutate))

    def test_component_parameters_keyed_by_name_are_read(self) -> None:
        def mutate(c):
            c["parameters"] = {p.pop("id"): p for p in c["parameters"]}
        self.assertIsNotNone(self._design(mutate))

    def test_a_threshold_that_is_a_bare_number(self) -> None:
        from forge_roles import RequirementsEngineer
        from forge_roles.base import RoleOutputError

        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from test_unusual_briefs import _load

        case = _load("calf_tabs_and_opening_claude")
        record = copy.deepcopy(case["requirements"])
        record["requirements"][0]["threshold"] = 430
        with self.assertRaises(RoleOutputError) as raised:
            RequirementsEngineer().parse(record, brief=case["brief"])
        self.assertIn("`requirements[0].threshold` must be an object",
                      raised.exception.problems[0])

    def test_a_patch_with_a_unit_that_is_not_one_is_a_schema_error(self):
        import json

        from forge_ir import Document
        from forge_ir.schema import SchemaError, SchemaErrorGroup

        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from test_unusual_briefs import _load

        document = copy.deepcopy(_load("calf_tabs_and_opening_claude")[
            "document"])
        hole = next(f for f in document["components"][0]["features"]
                    if f["kind"] == "hole")
        hole["parameters"]["diameter"] = {"magnitude": 5, "unit": "zz"}
        with self.assertRaises((SchemaError, SchemaErrorGroup)):
            Document.from_json(json.dumps(document))


class AnEmptyOrThinPartIsMeasuredNotCrashedOn(unittest.TestCase):
    def test_a_rod_thinner_than_the_mesh_cell_has_a_surface(self) -> None:
        from forge_geom import extract_manifold_surface
        from forge_geom.sdf import BoxSDF

        mesh = extract_manifold_surface(BoxSDF((0, 0, 0), (100, 0.5, 0.5)),
                                        resolution=64)
        self.assertTrue(mesh.is_watertight()[0])
        self.assertAlmostEqual(abs(mesh.signed_volume()), 200.0, delta=20.0)

    def test_a_size_whose_faces_cross_is_zero(self) -> None:
        from forge_geom.measure import MassProperties
        from forge_units import Interval, Q, Quantity, parse_unit

        mm = parse_unit("mm")

        def q(lo, hi):
            return Quantity(Interval(lo, hi), mm)

        properties = MassProperties(
            volume=Q(0, "mm^3"), centre_of_mass=(Q(0, "mm"),) * 3,
            bounding_box_lo=(q(0, 31.5),) * 3,
            bounding_box_hi=(q(-31.5, 0),) * 3,
            relative_uncertainty=1.0, depth_reached=1, cells_evaluated=1,
            converged=False)
        for size in properties.bounding_box_size():
            self.assertLess(float(size.magnitude.hi), 1e-300)


class AFigureWrittenWithItsUnit(unittest.TestCase):
    """`cos(60 deg)`: a stepper plate's designer spent two of its three
    attempts on angles written the way an engineer writes them."""

    def test_a_figure_and_its_unit_are_their_product(self) -> None:
        from forge_expr import Expression
        from forge_units import Q

        e = Expression.parse("bolt_circle_diameter / 2 * cos(60 deg)")
        value = e.evaluate({"bolt_circle_diameter": Q(56, "mm")})
        self.assertAlmostEqual(float(value.to("mm").magnitude.midpoint), 14.0)
        self.assertEqual(str(Expression.parse("4 mm^2").evaluate({})),
                         str(Expression.parse("4 * mm^2").evaluate({})))
        self.assertEqual(Expression.parse("2.5mm + a").source,
                         "(2.5 * mm) + a")

    def test_what_is_not_a_unit_is_still_refused(self) -> None:
        from forge_expr import Expression
        from forge_expr.errors import ExpressionSyntaxError

        with self.assertRaises(ExpressionSyntaxError):
            Expression.parse("3 plate_length")
        self.assertEqual(Expression.parse("10 if a else 2").source,
                         "10 if a else 2")
