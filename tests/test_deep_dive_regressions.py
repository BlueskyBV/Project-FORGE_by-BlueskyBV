"""Regressions from the 14 October 2026 deep dive.

Each test here is a failure that cost a live run, or that a replay showed
would have, fixed the same day. They are kept apart from the suites they
belong to so the fix and its reason can be read in one place.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Mapping
from unittest import mock

from forge_ir import Document, SchemaError, SchemaErrorGroup


def _document_with_parameter_expression(expression: str) -> str:
    return json.dumps({
        "schema_version": "1.0.0", "document_id": "d", "project_id": "p",
        "name": "x", "revision": 1,
        "units": {"length": "mm", "mass": "kg", "angle": "deg", "force": "N"},
        "requirements": [], "assumptions": [], "risk_class": "low",
        "components": [{
            "id": "c", "name": "c", "material": "",
            "parameters": [
                {"id": "a", "value": {"magnitude": 10, "unit": "mm"}},
                {"id": "b", "expression": expression, "unit": "mm"},
            ],
            "features": [{"id": "box", "kind": "box", "parameters": {
                "size": {"vector": ["a", "a", "a"], "unit": "mm"}}}],
            "interfaces": [],
        }],
    })


class AComponentParameterExpressionIsRefusedAsASchemaError(unittest.TestCase):
    """`Document.from_json` raises SchemaError for anything malformed.

    A component parameter whose expression would not parse -- `a *`, an
    empty string, `a.b` -- escaped as the expression engine's own exception.
    The designer's judge catches SchemaError and turns it into a correction
    the model can act on; anything else became a generic "Forge could not
    read this answer" retry carrying a Forge traceback, which cost a paid
    model round and told the model nothing about its mistake.
    """

    def test_each_malformed_expression_is_a_pointed_schema_error(self) -> None:
        for expression in ("a *", "a +", "2 ** ", "a if", "",
                           "__import__('os')", "a.b", "a[0]"):
            with self.subTest(expression=expression):
                with self.assertRaises((SchemaError, SchemaErrorGroup)) as held:
                    Document.from_json(
                        _document_with_parameter_expression(expression))
                error = held.exception
                errors = (list(error.errors)
                          if isinstance(error, SchemaErrorGroup) else [error])
                pointers = [e.pointer for e in errors]
                self.assertTrue(
                    any(p.endswith("/parameters/1/expression") for p in pointers),
                    pointers)

    def test_a_figure_with_its_unit_still_parses(self) -> None:
        document = Document.from_json(
            _document_with_parameter_expression("360 deg / 4"))
        self.assertEqual(document.components[0].identifier, "c")


class AHollowDomeKeepsItsWallClaim(unittest.TestCase):
    """The record's wall claim on a dome is rebound, never duplicated.

    The model writes `REQ_WALL_THICKNESS` bound to `wall_thickness`, a box's
    measurement; Forge knows a shell's wall is `minimum_wall_thickness` and
    appended its own claim under the same id. The duplicate was then refused
    by Forge's own validation and BOTH were dropped -- recorded as a FORGE
    DEFECT -- so a 3 mm shell drawn any thickness at all had nothing left to
    fail it.
    """

    BRIEF = ("A PLA dome: exactly half of a 70 mm sphere, hollow on the inside "
             "with 3 mm walls, sitting flat side down. It carries no load, so "
             "there is no load case.")

    def _record(self, *extra: Mapping[str, Any]) -> Any:
        from forge_roles.library import RequirementsEngineer

        structured = {
            "risk_class": "low", "unknowns": [], "assumptions": [],
            "requirements": [
                {"id": "REQ_DIAMETER", "statement": "70 mm across.",
                 "measurement": "bounding_box_x", "comparison": "equals",
                 "threshold": {"magnitude": 70, "unit": "mm"},
                 "source": "user"},
                *extra,
            ]}
        return RequirementsEngineer().parse(structured, brief=self.BRIEF)

    def test_the_models_box_style_claim_is_rebound(self) -> None:
        record = self._record({
            "id": "REQ_WALL_THICKNESS", "statement": "3 mm walls.",
            "measurement": "wall_thickness", "comparison": "equals",
            "threshold": {"magnitude": 3, "unit": "mm"}, "source": "user"})
        walls = [r for r in record.requirements
                 if r.get("measurement") == "minimum_wall_thickness"]
        self.assertEqual(len(walls), 1, record.requirements)
        self.assertEqual(walls[0]["id"], "REQ_WALL_THICKNESS")
        self.assertEqual(walls[0]["threshold"]["magnitude"], 3)
        self.assertFalse(any("FORGE DEFECT" in n for n in record.notes),
                         record.notes)

    def test_a_record_without_a_wall_claim_gets_one(self) -> None:
        record = self._record()
        walls = [r for r in record.requirements
                 if r.get("measurement") == "minimum_wall_thickness"]
        self.assertEqual(len(walls), 1)
        self.assertFalse(any("FORGE DEFECT" in n for n in record.notes),
                         record.notes)

    def test_an_id_already_taken_is_never_reused(self) -> None:
        record = self._record({
            "id": "REQ_WALL_THICKNESS", "statement": "the flange diameter",
            "measurement": "bounding_box_y", "comparison": "equals",
            "threshold": {"magnitude": 70, "unit": "mm"}, "source": "user"})
        ids = [r["id"] for r in record.requirements]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertTrue(any(r.get("measurement") == "minimum_wall_thickness"
                            for r in record.requirements))
        self.assertFalse(any("FORGE DEFECT" in n for n in record.notes),
                         record.notes)


class AFaultInOneMeasurementReaderIsEvidenceNotACrash(unittest.TestCase):
    """A reader that raises blocks its own claim and nothing else.

    `verify_component` measures every requirement through thirty-odd
    readers. One raising on a part it had not seen used to leave the whole
    verification as a bare exception: the orchestrator recorded an internal
    error, and a run that had built and measured a part ended with no
    evidence. Now the claim is BLOCKED, says it is Forge's defect, and the
    rest of the part is still reported.
    """

    def test_the_claim_is_blocked_and_the_others_still_measured(self) -> None:
        from forge_evidence import Status
        from forge_ir.spec import EXAMPLE_DOCUMENT
        from forge_pipeline import verify as verify_module
        from forge_pipeline import verify_component

        document = Document.from_json(json.dumps(EXAMPLE_DOCUMENT))
        component = document.components[0]
        bound = [r for r in document.requirements if r.measurement]
        self.assertGreater(len(bound), 1)
        victim = bound[0]
        real = verify_module.resolve_measurement

        def failing(binding: str, **kwargs: Any) -> Any:
            if binding == victim.measurement:
                raise RuntimeError("a reader tripped")
            return real(binding, **kwargs)

        with mock.patch.object(verify_module, "resolve_measurement", failing):
            report = verify_component(document, component,
                                      measurement_depth=5, mesh_resolution=40)
        by_id = {r.gate.identifier: r for r in report.gate_results}
        blocked = by_id[victim.identifier]
        self.assertIs(blocked.status, Status.BLOCKED)
        self.assertIn("FORGE DEFECT", blocked.evidence.detail["blocked_reason"])
        self.assertIn("a reader tripped", blocked.evidence.detail["forge_defect"])
        self.assertIsNot(report.overall_status, Status.PASS)
        others = [by_id[r.identifier] for r in bound[1:]]
        self.assertTrue(any(r.status is Status.PASS for r in others),
                        [(r.gate.identifier, r.status) for r in others])


class AnAnswerWithNoStructureIsRepairedNotCrashed(unittest.TestCase):
    """A response carrying no structured answer costs a repair, not the run.

    Every live adapter raises for this; a replayed fixture or an adapter
    that does not used to reach `require_structured`, whose ValueError no
    caller catches, and the run ended as an internal error.
    """

    def test_the_role_asks_again_and_then_reports_exhaustion(self) -> None:
        from forge_models import (
            ModelRequest, ModelResponse, Provider, ProviderInfo, StopReason,
            Usage, user,
        )
        from forge_roles import RepairExhaustedError
        from forge_roles.base import Role

        class Empty(Provider):
            calls = 0

            @property
            def info(self) -> ProviderInfo:
                return ProviderInfo(name="empty", model="none",
                                    supports_structured_output=True,
                                    is_remote=False)

            def _send(self, request: ModelRequest) -> ModelResponse:
                Empty.calls += 1
                return ModelResponse(
                    text="", structured=None, usage=Usage(1, 1),
                    provider="empty", model="none",
                    stop_reason=StopReason.COMPLETE, latency_seconds=0.0,
                    request_fingerprint=request.fingerprint())

        class Echo(Role[dict]):
            name = "echo"

            def system_prompt(self) -> str:
                return "echo"

            def output_schema(self, **_: Any) -> Mapping[str, Any]:
                return {"type": "object",
                        "properties": {"a": {"type": "string"}},
                        "required": ["a"]}

            def build_messages(self, **_: Any) -> tuple:
                return (user("say a"),)

            def parse(self, structured: Mapping[str, Any], **_: Any) -> dict:
                return dict(structured)

        with self.assertRaises(RepairExhaustedError):
            Echo().run(Empty())
        self.assertGreaterEqual(Empty.calls, 2)


def _clevis() -> dict:
    import pathlib

    path = pathlib.Path(__file__).parent.parent / "examples" / "clevis" / \
        "clevis.forgeir.json"
    return json.loads(path.read_text(encoding="utf-8"))


class AnUnapprovedHighRiskAssumptionBlocksHoweverItIsSpelled(unittest.TestCase):
    """`risk` is validated and folded, so spelling cannot bypass approval.

    `requires_explicit_approval` tests `risk in ("high", "critical")`.
    Unvalidated, an unapproved assumption written `"risk": "HIGH"` decoded
    cleanly and vanished from the blocking list -- the one human gate in
    the system, bypassed by capitalisation.
    """

    def test_an_upper_case_high_still_blocks(self) -> None:
        payload = _clevis()
        for assumption in payload["assumptions"]:
            assumption["risk"] = "HIGH"
            assumption["approved"] = False
        document = Document.from_json(json.dumps(payload))
        blocking = {a.identifier for a in
                    document.unapproved_blocking_assumptions()}
        self.assertEqual(blocking,
                         {a["id"] for a in payload["assumptions"]})

    def test_a_risk_outside_the_vocabulary_is_refused(self) -> None:
        payload = _clevis()
        payload["assumptions"][0]["risk"] = "severe"
        with self.assertRaises((SchemaError, SchemaErrorGroup)):
            Document.from_json(json.dumps(payload))

    def test_a_comparison_outside_the_vocabulary_is_refused_at_decode(
            self) -> None:
        payload = _clevis()
        payload["requirements"][0]["comparison"] = "bigger"
        with self.assertRaises((SchemaError, SchemaErrorGroup)):
            Document.from_json(json.dumps(payload))


class HostileDocumentsAreRefusedAsSchemaErrors(unittest.TestCase):
    """Every malformed input `Document.from_json` can meet is a SchemaError.

    Each case here escaped as something else -- an OverflowError from the
    unit parser, an AttributeError from a quantity's interval, the
    expression engine's own errors from a reserved or illegal parameter id,
    the parameter graph's from a duplicate id -- and an escaped exception
    is a wasted paid retry that names a Forge traceback instead of the
    mistake.
    """

    def _refused(self, mutate: Any) -> None:
        payload = _clevis()
        mutate(payload)
        with self.assertRaises((SchemaError, SchemaErrorGroup)):
            Document.from_json(json.dumps(payload))

    def test_a_unit_whose_exponent_overflows(self) -> None:
        self._refused(lambda p: p["units"].__setitem__("length", "km^99999"))

    def test_a_unit_nested_two_thousand_deep(self) -> None:
        self._refused(lambda p: p["components"][0]["parameters"][0]
                      .__setitem__("value", {"magnitude": 1,
                                             "unit": "(" * 2000 + "mm"
                                             + ")" * 2000}))

    def test_an_interval_that_is_not_an_object(self) -> None:
        self._refused(lambda p: p["components"][0]["parameters"][0]
                      .__setitem__("value", {"interval": "abc", "unit": "mm"}))

    def test_an_infinite_magnitude(self) -> None:
        self._refused(lambda p: p["components"][0]["parameters"][0]
                      .__setitem__("value", {"magnitude": 1e400, "unit": "mm"}))

    def test_a_reserved_parameter_name(self) -> None:
        self._refused(lambda p: p["components"][0]["parameters"][0]
                      .__setitem__("id", "pi"))

    def test_a_parameter_id_python_cannot_name(self) -> None:
        self._refused(lambda p: p["components"][0]["parameters"][0]
                      .__setitem__("id", "a-b"))

    def test_duplicate_parameter_ids(self) -> None:
        def twice(p: dict) -> None:
            parameters = p["components"][0]["parameters"]
            parameters.append(dict(parameters[0]))
        self._refused(twice)

    def test_duplicate_requirement_ids(self) -> None:
        def twice(p: dict) -> None:
            p["requirements"].append(dict(p["requirements"][0]))
        self._refused(twice)

    def test_an_expression_too_deep_to_parse(self) -> None:
        self._refused(lambda p: p["components"][0]["parameters"]
                      .append({"id": "deep", "expression": "-" * 5000 + "1",
                               "unit": "mm"}))

    def test_a_bound_in_another_dimension(self) -> None:
        self._refused(lambda p: p["components"][0]["parameters"][0]
                      .__setitem__("bounds", {"min": {"magnitude": 1,
                                                      "unit": "kg"}}))

    def test_the_clevis_itself_still_decodes(self) -> None:
        self.assertEqual(len(Document.from_json(
            json.dumps(_clevis())).components), 1)


class AnInsertAtIndexZeroDoesNotShiftLaterPatches(unittest.TestCase):
    """An `add` at array index 0 is an insert, applied after the rest.

    `(index or -1) >= 0` read index 0 as "no index", so the insert ran first
    in the given order and a `replace` of `/features/1` beside it edited
    what had been feature 0 -- the applier silently editing the wrong node,
    which is the one failure ADR-0010 says it exists to prevent.
    """

    def test_the_replace_lands_on_the_feature_it_named(self) -> None:
        from forge_roles import Patch, apply_patches

        payload = {"components": [{"id": "c", "features": [
            {"id": "a", "kind": "box", "description": "first"},
            {"id": "b", "kind": "box", "description": "second"},
        ]}]}
        patched = apply_patches(payload, [
            Patch.from_dict({"op": "add", "pointer": "/components/0/features/0",
                             "value": {"id": "e", "kind": "box"}}),
            Patch.from_dict({"op": "replace",
                             "pointer": "/components/0/features/1/description",
                             "value": "X"}),
        ])
        features = patched["components"][0]["features"]
        self.assertEqual([f["id"] for f in features], ["e", "a", "b"])
        self.assertEqual(features[1]["description"], "first")
        self.assertEqual(features[2]["description"], "X")


class IntervalArithmeticStaysSoundAtZeroAndAcrossTheCut(unittest.TestCase):
    def test_a_zero_lower_bound_is_not_widened_below_zero(self) -> None:
        from forge_units import Q
        from forge_units.interval import Interval
        from forge_units.mathfns import hypot, sqrt

        self.assertEqual((Interval(0.0, 1.0) * 2).lo, 0.0)
        self.assertEqual((Interval(0.0, 1.0) + Interval(0.0, 1.0)).lo, 0.0)
        sqrt(Q(Interval(0.0, 1.0), "mm") * 2)
        hypot(Q(Interval(0.0, 1.0), "mm"), Q(0.0, "mm"))

    def test_atan2_contains_pi_when_x_reaches_below_zero(self) -> None:
        import math

        from forge_units import Q
        from forge_units.interval import Interval
        from forge_units.mathfns import atan2

        result = atan2(Q(Interval(-1.0, 1.0), "mm"), Q(Interval(-2.0, 1.0), "mm"))
        self.assertLessEqual(result.magnitude.lo, -math.pi + 1e-12)
        self.assertGreaterEqual(result.magnitude.hi, math.pi - 1e-12)

    def test_a_negative_fractional_power_reaching_zero_is_refused_by_name(
            self) -> None:
        from forge_units.errors import IntervalError
        from forge_units.interval import Interval

        with self.assertRaises(IntervalError):
            Interval(0.0, 4.0) ** -0.5

    def test_superscript_minus_and_greek_mu_parse(self) -> None:
        from forge_units import parse_unit

        self.assertEqual(parse_unit("s⁻¹").dimension,
                         parse_unit("1/s").dimension)
        self.assertEqual(parse_unit("μm").scale, parse_unit("um").scale)


class TheTransportKeepsItsAccounts(unittest.TestCase):
    def test_a_retried_response_keeps_its_notes(self) -> None:
        from forge_models import ModelResponse, StopReason, Usage
        from forge_models.provider import _with_attempts

        response = ModelResponse(
            text="", structured={"a": 1}, usage=Usage(1, 1), provider="p",
            model="m", stop_reason=StopReason.COMPLETE, latency_seconds=0.0,
            request_fingerprint="f", notes=("cut short at its ceiling",))
        self.assertEqual(_with_attempts(response, 2).notes,
                         ("cut short at its ceiling",))
        self.assertEqual(_with_attempts(response, 2).attempts, 2)

    def test_a_cost_budget_on_unpriced_calls_is_refused_not_ignored(
            self) -> None:
        from forge_models import Budget, BudgetExceededError, ModelRequest, \
            Usage, user

        budget = Budget(max_cost_usd=1.0)
        request = ModelRequest(system="s", messages=(user("u"),))
        budget.check_before(request)
        budget.record(Usage(10, 10))
        with self.assertRaises(BudgetExceededError):
            budget.check_before(request)

    def test_a_retry_after_that_is_not_a_delay_falls_back_to_backoff(
            self) -> None:
        import math

        from forge_models import RetryPolicy

        policy = RetryPolicy(jitter=False)
        for bad in (float("nan"), -5.0, float("-inf")):
            delay = policy.delay_for(1, retry_after=bad)
            self.assertTrue(math.isfinite(delay) and delay >= 0.0, delay)

    def test_the_fingerprint_sees_the_tool_description(self) -> None:
        from forge_models import ModelRequest, user

        one = ModelRequest(system="s", messages=(user("u"),), schema={},
                           schema_description="one")
        two = ModelRequest(system="s", messages=(user("u"),), schema={},
                           schema_description="two")
        self.assertNotEqual(one.fingerprint(), two.fingerprint())


class TheKernelsEnclosuresContainTheTruth(unittest.TestCase):
    """Each is a measured enclosure that did not contain the analytic answer.

    A partial revolve's wedge term was `-radius` inside and `+radius`
    outside -- not a distance, discontinuous across the cut planes, so the
    octree decided cells it had no right to decide and a 60-degree
    revolution measured [5144.8, 6159.9] mm^3 against a true 6283.2. A
    chamfered boolean over three operands declared sqrt(2) where the fold
    measures 1.707. A drafted extrusion declared 1 where it measures
    sqrt(1 + sin(draft)). A sweep's envelope was 1.13 mm short of its own
    material.
    """

    def test_a_partial_revolve_encloses_its_analytic_volume(self) -> None:
        import math

        from forge_geom import RectangleProfile, Revolve, measure_mass_properties

        profile = RectangleProfile(centre=(15.0, 10.0), half_width=10.0,
                                   half_height=10.0)
        for degrees in (30.0, 60.0, 90.0, 270.0):
            angle = math.radians(degrees)
            solid = Revolve(profile=profile, origin=(0, 0, 0), axis=(0, 0, 1),
                            reference=(1, 0, 0), angle=angle)
            true = (angle / 2.0) * (25.0 ** 2 - 5.0 ** 2) * 20.0
            volume = measure_mass_properties(solid, max_depth=7).volume.magnitude
            with self.subTest(degrees=degrees):
                self.assertLessEqual(volume.lo, true)
                self.assertGreaterEqual(volume.hi, true)

    def test_a_chamfer_over_three_operands_compounds_its_constant(self) -> None:
        from forge_geom.sdf import Intersection, SphereSDF

        sphere = SphereSDF(centre=(0, 0, 0), radius=10.0)
        three = Intersection(operands=(sphere, sphere, sphere), chamfer=2.0)
        two = Intersection(operands=(sphere, sphere), chamfer=2.0)
        self.assertAlmostEqual(two.lipschitz, 2 ** 0.5, places=6)
        self.assertGreaterEqual(three.lipschitz, 1.707)

    def test_a_drafted_extrusion_declares_more_than_one(self) -> None:
        import math

        from forge_geom import RectangleProfile
        from forge_geom.sdf import ExtrusionSDF

        profile = RectangleProfile(centre=(0.0, 0.0), half_width=10.0,
                                   half_height=10.0)
        drafted = ExtrusionSDF(profile=profile, origin=(0, 0, 0),
                               u_axis=(1, 0, 0), v_axis=(0, 1, 0),
                               w_axis=(0, 0, 1), distance=20.0,
                               taper=math.tan(math.radians(30.0)))
        self.assertAlmostEqual(drafted.lipschitz,
                               math.sqrt(1 + math.sin(math.radians(30.0))),
                               places=6)

    def test_a_sweeps_envelope_contains_all_of_its_material(self) -> None:
        import numpy as np

        from forge_geom import RectangleProfile
        from forge_geom.sdf import SweepSDF

        sweep = SweepSDF(
            profile=RectangleProfile(centre=(0.0, 0.0), half_width=10.0,
                                     half_height=10.0),
            path=((0, 0, 0), (20, 0, 0), (20, 20, 0)))
        grid = np.linspace(-30, 50, 81)
        points = np.array(np.meshgrid(grid, grid, np.linspace(-15, 15, 31),
                                      indexing="ij")).reshape(3, -1).T
        inside = points[np.asarray(sweep(points)) < 0]
        self.assertGreater(len(inside), 1000)
        lo, hi = np.asarray(sweep.envelope.lo), np.asarray(sweep.envelope.hi)
        self.assertFalse(((inside < lo) | (inside > hi)).any())


class TwoIdenticalFeaturesEachPublishTheirOwnGeometry(unittest.TestCase):
    """The compiler's cache served one feature another feature's entities.

    Two features of the same kind, parameters and inputs share a content
    hash, and the cached product carried the first's entity names and
    tokens: `boss_b.lateral` was absent from the geometry map and any
    interface or binding naming it raised SelectionError on a valid design.
    """

    def test_the_second_boss_has_its_own_faces(self) -> None:
        from forge_kernel import Compiler

        payload = _clevis()
        component = payload["components"][0]
        component["parameters"].append(
            {"id": "boss_diameter", "value": {"magnitude": 8.0, "unit": "mm"}})
        component["parameters"].append(
            {"id": "boss_height", "value": {"magnitude": 8.0, "unit": "mm"}})
        for name in ("boss_a", "boss_b"):
            component["features"].append({
                "id": name, "kind": "cylinder", "parameters": {
                    "diameter": {"expression": "boss_diameter", "unit": "mm"},
                    "height": {"expression": "boss_height", "unit": "mm"},
                    "origin": {"vector": [0, 0, 0], "unit": "mm"}}})
        last = component["features"][-3]["id"]
        component["features"].append({
            "id": "with_bosses", "kind": "union",
            "inputs": [last, "boss_a", "boss_b"], "parameters": {}})
        document = Document.from_json(json.dumps(payload))
        part = Compiler().compile_component(document.components[0],
                                            validate_geometry=False)
        names = set(part.geometry_map.names())
        self.assertTrue(any(n.startswith("boss_a.") for n in names), names)
        self.assertTrue(any(n.startswith("boss_b.") for n in names), names)


class AValidSolidMetAtASlantIsNotFailedForTheGridsSake(unittest.TestCase):
    """Surface nets can draw a manifold solid non-manifold on every grid.

    A cylinder along (1, 2, 2) came out with 14 edges shared by four faces
    at the verification resolution, and `GEOM_WATERTIGHT` -- critical --
    FAILED a valid primitive and sent the analyst to repair it. Closed but
    non-manifold on every grid is now reported as the range it is, so the
    gate is INCONCLUSIVE: it still holds the release, and it no longer
    calls a right part wrong.
    """

    def test_the_watertight_gate_does_not_fail(self) -> None:
        from forge_evidence import Status
        from forge_pipeline import verify_component

        payload = _clevis()
        payload["requirements"] = []
        payload["assumptions"] = []
        component = payload["components"][0]
        component["interfaces"] = []
        component["parameters"] = [
            {"id": "d", "value": {"magnitude": 6.0, "unit": "mm"}},
            {"id": "h", "value": {"magnitude": 10.0, "unit": "mm"}}]
        component["features"] = [{
            "id": "rod", "kind": "cylinder", "parameters": {
                "diameter": {"expression": "d", "unit": "mm"},
                "height": {"expression": "h", "unit": "mm"},
                "origin": {"vector": [0, 0, 0], "unit": "mm"},
                "axis": {"vector": [1, 2, 2], "unit": "mm"}}}]
        document = Document.from_json(json.dumps(payload))
        report = verify_component(document, document.components[0],
                                  measurement_depth=5, mesh_resolution=110)
        gate = {r.gate.identifier: r for r in report.gate_results}["GEOM_WATERTIGHT"]
        self.assertIsNot(gate.status, Status.FAIL, gate.evidence.limitations)


class APatternCountHasACeiling(unittest.TestCase):
    """A count of a thousand million was accepted and the pattern's field
    looped over it for ever: the compiler hung where it should refuse."""

    def _with_count(self, count: int) -> str:
        payload = _clevis()
        component = payload["components"][0]
        last = component["features"][-1]["id"]
        component["features"].append({
            "id": "many", "kind": "pattern_linear", "inputs": [last],
            "parameters": {"count": count,
                           "spacing": {"vector": [1, 0, 0], "unit": "mm"}}})
        return json.dumps(payload)

    def test_a_sane_count_still_decodes(self) -> None:
        Document.from_json(self._with_count(4))

    def test_a_thousand_million_copies_is_refused_for_the_count(self) -> None:
        with self.assertRaises((SchemaError, SchemaErrorGroup)) as held:
            Document.from_json(self._with_count(1_000_000_000))
        self.assertIn("count", str(held.exception))
        self.assertIn("maximum", str(held.exception))


if __name__ == "__main__":
    unittest.main()
