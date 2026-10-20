"""The golden clevis, end to end, plus deliberate sabotage.

Two halves, and the second matters more.

The first half checks that a correct design verifies correctly. That is table
stakes, and any system that produces geometry will pass it.

The second half injects faults -- a bore that does not line up, ears too close
together, a wall machined away, a mass over budget, a fillet that cannot fit --
and requires each one to be *caught*. A verification system that cannot fail is
not a verification system, and the metric the build specification cares about is
not how often it passes but how often it wrongly passes. Every fault below is
asserted to produce ``FAIL``, ``BLOCKED`` or ``INCONCLUSIVE`` -- never ``PASS``.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Callable

from forge_evidence import Status
from forge_ir import Document, SchemaError, SchemaErrorGroup
from forge_kernel import CompileError, Compiler
from forge_pipeline import LoadCase, verify_component
from forge_units import Q

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "clevis" / "clevis.forgeir.json"
LOAD_CASE = LoadCase(
    "bench_worst_case", Q(500, "N"), Q(35, "mm"), assumption_id="ASM_DESIGN_LOAD"
)


def _payload() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text())


def _set_parameter(payload: dict[str, Any], identifier: str, magnitude: float) -> None:
    for parameter in payload["components"][0]["parameters"]:
        if parameter["id"] == identifier:
            parameter["value"]["magnitude"] = magnitude
            return
    raise AssertionError(f"no parameter named {identifier}")


def _accept_assumptions(payload: dict[str, Any]) -> None:
    for assumption in payload["assumptions"]:
        assumption["approved"] = True


def _verify(payload: dict[str, Any], **kwargs: Any):
    document = Document.from_json(json.dumps(payload))
    return verify_component(
        document, document.component("clevis"), load_case=LOAD_CASE, **kwargs
    )


class GoldenBaseline(unittest.TestCase):
    """The clevis as shipped."""

    def test_every_gate_passes(self) -> None:
        report = _verify(_payload())
        failures = [
            result.gate.identifier
            for result in report.gate_results
            if result.status is not Status.PASS
        ]
        self.assertEqual(failures, [], f"unexpected non-passing gates: {failures}")

    def test_unapproved_assumptions_block_release_anyway(self) -> None:
        """Passing every check is not the same as being ready to release.

        The design was verified against a 500 N load nobody accepted. Reporting
        that as a pass with a footnote is how an unexamined assumption ends up
        in a released design, so it is reported as BLOCKED instead.
        """
        report = _verify(_payload())
        self.assertIs(report.overall_status, Status.BLOCKED)
        self.assertTrue(
            any("ASM_DESIGN_LOAD" in reason for reason in report.release_reasons)
        )

    def test_accepting_the_assumptions_clears_the_block(self) -> None:
        payload = _payload()
        _accept_assumptions(payload)
        report = _verify(payload)
        self.assertIs(report.overall_status, Status.PASS)
        self.assertEqual(report.release_reasons, ())

    def test_measurements_are_intervals_not_point_estimates(self) -> None:
        report = _verify(_payload())
        for key in ("volume", "mass", "minimum_wall"):
            self.assertIn(
                "±",
                report.measurements[key],
                f"{key} was reported without its uncertainty",
            )

    def test_two_backends_agree_on_volume(self) -> None:
        report = _verify(_payload())
        cross = next(
            result
            for result in report.gate_results
            if result.gate.identifier == "GEOM_CROSS_BACKEND"
        )
        self.assertIs(cross.status, Status.PASS)

    def test_evidence_records_its_own_limitations(self) -> None:
        report = _verify(_payload())
        analytical = [
            node for node in report.evidence if node.method.value == "analytical"
        ]
        self.assertTrue(analytical)
        for node in analytical:
            self.assertTrue(
                node.limitations,
                f"{node.identifier} reports a number with no stated limitations",
            )

    def test_evidence_is_append_only(self) -> None:
        report = _verify(_payload())
        node = next(iter(report.evidence))
        with self.assertRaises(ValueError):
            report.evidence.add(node)

    def test_report_serialises(self) -> None:
        report = _verify(_payload())
        encoded = json.dumps(report.as_dict())
        self.assertIn("overall_status", encoded)
        self.assertGreater(len(encoded), 2000)


class InjectedFaults(unittest.TestCase):
    """Each of these must be caught. None may report PASS."""

    def _assert_caught(
        self,
        mutate: Callable[[dict[str, Any]], None],
        *,
        gate: str,
        expected: tuple[Status, ...] = (Status.FAIL, Status.INCONCLUSIVE),
    ) -> None:
        payload = _payload()
        _accept_assumptions(payload)  # isolate the injected fault
        mutate(payload)
        report = _verify(payload)
        result = next(
            (r for r in report.gate_results if r.gate.identifier == gate), None
        )
        self.assertIsNotNone(result, f"gate {gate} was not evaluated at all")
        self.assertIn(
            result.status,  # type: ignore[union-attr]
            expected,
            f"{gate} reported {result.status} for a design with an injected "  # type: ignore[union-attr]
            f"fault; expected one of {[s.value for s in expected]}",
        )
        self.assertIsNot(
            report.overall_status,
            Status.PASS,
            "the overall verdict was PASS despite an injected fault",
        )

    def test_ear_spacing_too_narrow_is_caught(self) -> None:
        self._assert_caught(
            lambda payload: _set_parameter(payload, "ear_gap", 9.0),
            gate="REQ_EAR_SPACING",
        )

    def test_ear_spacing_too_wide_is_caught(self) -> None:
        self._assert_caught(
            lambda payload: _set_parameter(payload, "ear_gap", 15.0),
            gate="REQ_EAR_SPACING",
        )

    def test_wrong_bore_diameter_is_caught(self) -> None:
        self._assert_caught(
            lambda payload: _set_parameter(payload, "pivot_diameter", 9.5),
            gate="REQ_PIVOT_BORE",
        )

    def test_base_envelope_change_is_caught_by_the_declared_dimension(self) -> None:
        self._assert_caught(
            lambda payload: _set_parameter(payload, "base_length", 72.0),
            gate="REQ_BASE_X",
        )

    def test_base_envelope_change_is_caught_by_measuring_the_solid(self) -> None:
        """The same fault, caught a second way, on purpose.

        ``REQ_BASE_X`` reads the declared parameter, which catches a value that
        changed. ``REQ_ENVELOPE_X`` measures the finished solid, which also
        catches material that arrives from somewhere the declared dimension does
        not describe -- a feature placed past the plate edge, a blend that puffs
        out. Checking the document and checking the part are different claims,
        and only the second one is about the object.
        """
        self._assert_caught(
            lambda payload: _set_parameter(payload, "base_length", 72.0),
            gate="REQ_ENVELOPE_X",
        )

    def test_thin_wall_around_an_oversized_bore_is_caught(self) -> None:
        """An 18 mm bore in a 20 mm crown leaves a 1 mm ring of metal.

        This is the fault a dimensional check alone would miss entirely: every
        declared dimension is still exactly what the document says, the part
        compiles cleanly, and the geometry is perfectly valid. What is wrong is
        an emergent property of two dimensions interacting, and only measuring
        the finished solid finds it.
        """
        self._assert_caught(
            lambda payload: _set_parameter(payload, "pivot_diameter", 18.0),
            gate="REQ_MIN_WALL",
        )

    def test_an_ear_at_the_bottom_of_its_bound_is_still_legal(self) -> None:
        """The complement of the fault tests: a valid design must not be failed.

        A verifier that fails everything is as useless as one that passes
        everything. A 4 mm ear satisfies a 3 mm minimum-wall rule and must be
        reported as satisfying it.
        """
        payload = _payload()
        _accept_assumptions(payload)
        _set_parameter(payload, "ear_thickness", 4.0)
        report = _verify(payload)
        wall = next(
            r for r in report.gate_results if r.gate.identifier == "REQ_MIN_WALL"
        )
        self.assertIs(wall.status, Status.PASS)

    def test_mass_over_budget_is_caught(self) -> None:
        def fatten(payload: dict[str, Any]) -> None:
            _set_parameter(payload, "base_thickness", 20.0)
            _set_parameter(payload, "base_length", 90.0)

        self._assert_caught(fatten, gate="REQ_MASS_BUDGET")

    def test_infeasible_fillet_is_refused_by_bounds(self) -> None:
        payload = _payload()
        _set_parameter(payload, "root_blend", 40.0)
        document = Document.from_json(json.dumps(payload))
        with self.assertRaises(CompileError) as caught:
            Compiler().compile_component(document.component("clevis"))
        self.assertIn("root_blend", caught.exception.detail["parameters"])

    def test_zero_thickness_is_refused_not_built(self) -> None:
        payload = _payload()
        _set_parameter(payload, "ear_height", 0.0)
        document = Document.from_json(json.dumps(payload))
        with self.assertRaises(CompileError):
            Compiler().compile_component(document.component("clevis"))

    def test_missing_material_blocks_rather_than_guesses(self) -> None:
        payload = _payload()
        _accept_assumptions(payload)
        payload["components"][0]["material"] = "aluminium"  # a family, not a grade
        report = _verify(payload)
        mass = next(
            r for r in report.gate_results if r.gate.identifier == "REQ_MASS_BUDGET"
        )
        self.assertIs(mass.status, Status.BLOCKED)
        self.assertIsNot(report.overall_status, Status.PASS)

    def test_burying_an_interface_face_fails_that_interface(self) -> None:
        payload = _payload()
        _accept_assumptions(payload)
        component = payload["components"][0]
        component["features"].append(
            {
                "id": "pad",
                "kind": "box",
                "role": "pad",
                "parameters": {
                    "size": {"vector": ["base_length", "base_width", 8], "unit": "mm"},
                    "origin": {"vector": [0, 0, -8], "unit": "mm"},
                    "centered": False,
                },
            }
        )
        component["features"].append(
            {
                "id": "with_pad",
                "kind": "union",
                "role": "with_pad",
                "inputs": ["pivot", "pad"],
            }
        )
        report = _verify(payload)
        mounting = next(
            r for r in report.gate_results if r.gate.identifier == "IFACE_MOUNTING_FACE"
        )
        self.assertIs(mounting.status, Status.FAIL)
        self.assertIsNot(report.overall_status, Status.PASS)


class MalformedDocuments(unittest.TestCase):
    """Invalid documents are refused with a location, never partially accepted."""

    def _assert_rejected(self, mutate: Callable[[dict[str, Any]], None]) -> SchemaError:
        payload = _payload()
        mutate(payload)
        with self.assertRaises((SchemaError, SchemaErrorGroup)) as caught:
            Document.from_json(json.dumps(payload))
        return caught.exception

    def test_unknown_field_is_refused(self) -> None:
        error = self._assert_rejected(
            lambda payload: payload["components"][0].update({"colour": "red"})
        )
        self.assertIn("colour", str(error))

    def test_missing_required_field_is_refused(self) -> None:
        error = self._assert_rejected(
            lambda payload: payload.pop("document_id")
        )
        self.assertIn("document_id", str(error))

    def test_future_schema_version_is_refused(self) -> None:
        error = self._assert_rejected(
            lambda payload: payload.update({"schema_version": "9.0.0"})
        )
        self.assertIn("9.0.0", str(error))

    def test_cyclic_parameters_are_refused(self) -> None:
        def make_cycle(payload: dict[str, Any]) -> None:
            for parameter in payload["components"][0]["parameters"]:
                if parameter["id"] == "ear_offset":
                    parameter["expression"] = "outer_width / 2"
                if parameter["id"] == "outer_width":
                    parameter["expression"] = "ear_gap + 2 * ear_offset"

        payload = _payload()
        make_cycle(payload)
        document = Document.from_json(json.dumps(payload))
        with self.assertRaises(CompileError) as caught:
            Compiler().compile_component(document.component("clevis"))
        self.assertIn("cycle", str(caught.exception).lower())

    def test_dangling_feature_input_is_refused(self) -> None:
        error = self._assert_rejected(
            lambda payload: payload["components"][0]["features"][-1].update(
                {"inputs": ["does_not_exist"]}
            )
        )
        self.assertIn("does_not_exist", str(error))

    def test_wrong_product_kind_as_input_is_refused(self) -> None:
        def feed_a_datum_to_a_hole(payload: dict[str, Any]) -> None:
            features = payload["components"][0]["features"]
            features.insert(
                0,
                {
                    "id": "plane",
                    "kind": "datum_plane",
                    "role": "plane",
                    "parameters": {"base": "XY"},
                },
            )
            for feature in features:
                if feature["id"] == "pivot":
                    feature["inputs"] = ["plane"]

        error = self._assert_rejected(feed_a_datum_to_a_hole)
        self.assertIn("product kind", str(error))

    def test_an_expression_cannot_reach_the_interpreter(self) -> None:
        """Documents are untrusted input; the expression allowlist is a boundary."""
        for hostile in (
            "__import__('os').system('id')",
            "().__class__.__mro__[1].__subclasses__()",
            "open('/etc/passwd').read()",
        ):
            with self.subTest(expression=hostile):
                payload = _payload()
                for parameter in payload["components"][0]["parameters"]:
                    if parameter["id"] == "outer_width":
                        parameter["expression"] = hostile
                with self.assertRaises((SchemaError, SchemaErrorGroup, Exception)):
                    Document.from_json(json.dumps(payload))


def _standoff(*, cut_last: bool, depth: float | None = None) -> dict[str, Any]:
    """A post on a plate with an axial bore, built two ways.

    ``cut_last=False`` is the document a model actually produced: the bore is
    cut into the post, and the post is *then* unioned with its base plate,
    which refills the bottom of the bore. Every dimension is right, the solid
    is watertight, and the part prints as a post with a blind pocket.
    """
    features: list[dict[str, Any]] = [
        {
            "id": "base_plate",
            "kind": "box",
            "parameters": {
                "size": {
                    "vector": ["plate_size", "plate_size", "plate_thickness"],
                    "unit": "mm",
                },
                "centered": True,
            },
        },
        {
            "id": "post",
            "kind": "cylinder",
            "parameters": {
                "diameter": {"expression": "post_diameter"},
                "height": {"expression": "post_height"},
                "origin": {
                    "vector": [0, 0, "plate_thickness / 2"],
                    "unit": "mm",
                },
            },
        },
    ]
    bore: dict[str, Any] = {
        "id": "bore",
        "kind": "hole",
        "inputs": [],
        "parameters": {
            "diameter": {"expression": "bore_diameter"},
            "position": {"vector": [0, 0, 0], "unit": "mm"},
        },
    }
    if depth is not None:
        bore["parameters"]["depth"] = {"magnitude": depth, "unit": "mm"}
    if cut_last:
        features.append(
            {"id": "body", "kind": "union", "inputs": ["base_plate", "post"]}
        )
        bore["inputs"] = ["body"]
        features.append(bore)
    else:
        bore["inputs"] = ["post"]
        features.append(bore)
        features.append(
            {"id": "body", "kind": "union", "inputs": ["base_plate", "bore"]}
        )
    return {
        "schema_version": "1.0.0",
        "document_id": "doc_standoff",
        "project_id": "proj_test",
        "revision": 1,
        "units": {"length": "mm", "mass": "g", "angle": "deg"},
        "risk_class": "low",
        "requirements": [],
        "assumptions": [],
        "components": [
            {
                "id": "standoff",
                "name": "Standoff",
                "material": "pla",
                "parameters": [
                    {"id": "plate_size", "value": {"magnitude": 50, "unit": "mm"}},
                    {
                        "id": "plate_thickness",
                        "value": {"magnitude": 5, "unit": "mm"},
                    },
                    {"id": "post_height", "value": {"magnitude": 30, "unit": "mm"}},
                    {
                        "id": "post_diameter",
                        "value": {"magnitude": 20, "unit": "mm"},
                    },
                    {
                        "id": "bore_diameter",
                        "value": {"magnitude": 8, "unit": "mm"},
                    },
                ],
                "features": features,
                "interfaces": [],
            }
        ],
    }


class ThroughHolesAreActuallyThrough(unittest.TestCase):
    """A hole with no ``depth`` must be open in the finished part.

    This is the one defect every other check in the pipeline waves through. The
    volume is plausible, the mesh is watertight and manifold, the cross-backend
    measurement agrees with itself, and every dimensional requirement passes --
    because every dimension *is* right. Only the bore is blocked, and only a
    measurement taken along the bore's own centre line can say so.
    """

    def _gate(self, payload: dict[str, Any]):
        document = Document.from_json(json.dumps(payload))
        report = verify_component(document, document.component("standoff"))
        return next(
            (
                result
                for result in report.gate_results
                if result.gate.identifier == "GEOM_THROUGH_HOLES_OPEN"
            ),
            None,
        )

    def test_a_bore_refilled_by_a_later_union_fails(self) -> None:
        result = self._gate(_standoff(cut_last=False))
        self.assertIsNotNone(result)
        self.assertIs(result.status, Status.FAIL)
        blocked = result.evidence.detail["blocked"]
        self.assertEqual([entry["feature"] for entry in blocked], ["bore"])
        # The plate is 5 mm thick and centred on z=0, so that is exactly the
        # span of material the union put back into the bore.
        self.assertAlmostEqual(blocked[0]["from"][2], -2.5, places=2)
        self.assertAlmostEqual(blocked[0]["to"][2], 2.5, places=2)
        self.assertAlmostEqual(blocked[0]["blocked_length_mm"], 5.0, places=2)
        self.assertEqual(blocked[0]["obstructions"], 1)

    def test_the_failure_says_how_to_fix_it(self) -> None:
        result = self._gate(_standoff(cut_last=False))
        hint = result.evidence.detail["hint"]
        self.assertIn("`bore`", hint)
        self.assertIn("cut LAST", hint)
        self.assertIn("depth", hint)

    def test_the_gate_is_critical_so_the_loop_repairs_it(self) -> None:
        result = self._gate(_standoff(cut_last=False))
        self.assertTrue(result.gate.critical)

    def test_the_same_part_cut_in_the_right_order_passes(self) -> None:
        result = self._gate(_standoff(cut_last=True))
        self.assertIs(result.status, Status.PASS)
        self.assertEqual(result.evidence.detail["blocked"], [])
        self.assertEqual(result.evidence.detail["checked"], ["bore"])

    def test_a_hole_with_a_declared_depth_is_not_a_through_hole(self) -> None:
        """A blind hole is blind on purpose, and must not be flagged.

        Its material sits on the centre line by design, which is precisely the
        condition this gate fails on -- so the gate must read the document's
        intent from `depth`, not the geometry alone.
        """
        self.assertIsNone(self._gate(_standoff(cut_last=False, depth=20.0)))

    def test_a_document_with_no_holes_does_not_raise_the_gate(self) -> None:
        payload = _standoff(cut_last=True)
        features = payload["components"][0]["features"]
        payload["components"][0]["features"] = [
            feature for feature in features if feature["kind"] != "hole"
        ]
        self.assertIsNone(self._gate(payload))

    def test_the_evidence_states_what_it_could_have_missed(self) -> None:
        result = self._gate(_standoff(cut_last=True))
        self.assertTrue(result.evidence.limitations)
        self.assertTrue(
            any("centre line" in text for text in result.evidence.limitations)
        )


class AFailingCheckExplainsItselfInTheReport(unittest.TestCase):
    """``evidence.txt`` is where a person looks first, so the why goes there.

    "FAIL  every through hole is open  = 1  (required <= 0)" is true, complete
    and useless: it sends the reader into the run's JSON to find out which hole
    and what to do, and most readers stop at the text file.
    """

    def _graph(self, status_value, **detail):
        from forge_evidence import EvidenceGraph, Gate, Method, ToolIdentity

        gate = Gate(
            identifier="SOME_CHECK",
            claim="the thing holds",
            comparison="at_most",
            threshold=Q(0),
        )
        graph = EvidenceGraph()
        graph.add(
            gate.evaluate(
                Q(status_value),
                method=Method.EXACT_GEOMETRY,
                tool=ToolIdentity("test", "0"),
                detail=detail,
            )
        )
        return graph

    def test_a_failed_check_prints_its_hint(self) -> None:
        text = self._graph(1, hint="do the thing differently").render()
        self.assertIn("-> do the thing differently", text)

    def test_a_passing_check_does_not(self) -> None:
        """A passing check has nothing to explain, and saying so is noise."""
        text = self._graph(0, hint="do the thing differently").render()
        self.assertNotIn("do the thing differently", text)

    def test_a_long_hint_is_wrapped_not_truncated(self) -> None:
        hint = " ".join(["word"] * 60)
        text = self._graph(1, hint=hint).render()
        self.assertIn("word", text)
        self.assertTrue(all(len(line) <= 100 for line in text.splitlines()))


class Determinism(unittest.TestCase):
    def test_the_same_document_produces_the_same_part_hash(self) -> None:
        hashes = set()
        for _ in range(3):
            document = Document.from_json(EXAMPLE.read_text())
            part = Compiler().compile_component(document.component("clevis"))
            hashes.add(part.part_hash)
        self.assertEqual(len(hashes), 1)

    def test_serialisation_round_trips_losslessly(self) -> None:
        original = Document.from_json(EXAMPLE.read_text())
        restored = Document.from_json(original.to_json())
        self.assertEqual(restored.to_json(), original.to_json())

        first = Compiler().compile_component(original.component("clevis"))
        second = Compiler().compile_component(restored.component("clevis"))
        self.assertEqual(first.part_hash, second.part_hash)

    def test_evidence_content_hash_is_reproducible(self) -> None:
        a = _verify(_payload())
        b = _verify(_payload())
        for left, right in zip(a.evidence, b.evidence):
            self.assertEqual(left.content_hash, right.content_hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)


def _counted_standoff(*, tag_them: bool, binding: str, threshold: float,
                      comparison: str = "equals") -> dict[str, Any]:
    """The standoff, plus two extra holes and a requirement that counts."""
    payload = _standoff(cut_last=True)
    component = payload["components"][0]
    component["parameters"].append(
        {"id": "vent_diameter", "value": {"magnitude": 3, "unit": "mm"}}
    )
    previous = "bore"
    for index, x in enumerate((-18.0, 18.0), start=1):
        feature: dict[str, Any] = {
            "id": f"vent_{index}",
            "kind": "hole",
            "inputs": [previous],
            "parameters": {
                "diameter": {"expression": "vent_diameter"},
                "position": {"vector": [x, 0, 0], "unit": "mm"},
            },
        }
        if tag_them:
            feature["tags"] = ["vent"]
        component["features"].append(feature)
        previous = feature["id"]
    payload["requirements"] = [
        {
            "id": "REQ_VENTS",
            "statement": "There shall be two vent holes.",
            "type": "geometric",
            "strength": "hard",
            "verification": "exact_geometry",
            "threshold": {"magnitude": threshold, "unit": ""},
            "comparison": comparison,
            "measurement": binding,
            "source": "user",
            "state": "accepted",
        }
    ]
    return payload


class CountingOnlyTheFeaturesTheRequirementMeans(unittest.TestCase):
    """`feature_count:hole` counts the bore too, and that is a false alarm.

    A plate with a central bore and four bolt holes has five `hole` features.
    "There shall be four mounting holes" bound to `feature_count:hole` measures
    five and fails a correct design -- and the repair loop, told only that a
    count is wrong, will helpfully delete a hole. The same shape of error as
    binding a plate's thickness to `bounding_box_z`: the measurement is
    faithful and the question was wrong.
    """

    def _gate(self, payload: dict[str, Any]):
        document = Document.from_json(json.dumps(payload))
        report = verify_component(
            document, document.component("standoff"), measurement_depth=6,
            mesh_resolution=48,
        )
        return next(
            r for r in report.gate_results if r.gate.identifier == "REQ_VENTS"
        )

    def test_an_untagged_count_sees_every_hole_of_that_kind(self) -> None:
        """Stated as the trap it is: three holes, and the answer is three."""
        result = self._gate(
            _counted_standoff(
                tag_them=True, binding="feature_count:hole", threshold=2
            )
        )
        self.assertIs(result.status, Status.FAIL)
        self.assertEqual(str(result.evidence.result), "3")

    def test_a_tagged_count_sees_only_those(self) -> None:
        result = self._gate(
            _counted_standoff(
                tag_them=True, binding="feature_count:hole:vent", threshold=2
            )
        )
        self.assertIs(result.status, Status.PASS)
        self.assertEqual(str(result.evidence.result), "2")

    def test_a_tag_nothing_carries_is_blocked_not_counted_as_zero(self) -> None:
        """Measuring zero would read as "the design forgot the vents"."""
        result = self._gate(
            _counted_standoff(
                tag_them=False, binding="feature_count:hole:vent", threshold=2
            )
        )
        self.assertIs(result.status, Status.BLOCKED)
        self.assertIn("vent", result.evidence.detail.get("hint", ""))

    def test_counting_exactly_does_not_end_the_run_in_a_traceback(self) -> None:
        """`equals 2` on a count declares no tolerance, and used to raise.

        The gate refuses exact equality without a tolerance, rightly: between
        measured quantities it is never satisfiable. A count is not a measured
        quantity in that sense -- there are two holes or there are not -- so
        the tolerance is zero, and the run survives.
        """
        result = self._gate(
            _counted_standoff(
                tag_them=True, binding="feature_count:hole:vent", threshold=2
            )
        )
        self.assertIsNotNone(result.gate.tolerance)
        self.assertIs(result.status, Status.PASS)


class ARequirementThatCannotBeCheckedIsEvidenceNotACrash(unittest.TestCase):
    """`equals` with no tolerance on something that is not a length.

    The gate raises ValueError, by design: exact equality between measured
    quantities is never satisfiable. Raising it from inside the verifier took
    down the whole run -- every measurement already made, the compiled part,
    the mesh -- over one badly written requirement, and the repair loop never
    saw it. It is a fact about the requirement, so it is reported as one.
    """

    def test_the_run_survives_and_names_the_requirement(self) -> None:
        payload = _standoff(cut_last=True)
        payload["requirements"] = [
            {
                "id": "REQ_SF",
                "statement": "The part shall enclose exactly 24000 cubic mm.",
                "type": "geometric",
                "strength": "hard",
                "verification": "exact_geometry",
                "threshold": {"magnitude": 24000.0, "unit": "mm^3"},
                "comparison": "equals",
                "measurement": "volume",
                "source": "user",
                "state": "accepted",
            }
        ]
        document = Document.from_json(json.dumps(payload))
        report = verify_component(
            document, document.component("standoff"), measurement_depth=6,
            mesh_resolution=48,
        )
        result = next(
            r for r in report.gate_results if r.gate.identifier == "REQ_SF"
        )
        self.assertIs(result.status, Status.BLOCKED)
        self.assertIn("tolerance", result.evidence.detail["hint"])

    def test_the_other_gates_still_reported(self) -> None:
        """The point of not raising: nothing measured is thrown away."""
        payload = _standoff(cut_last=True)
        payload["requirements"] = [
            {
                "id": "REQ_SF",
                "statement": "The part shall enclose exactly 24000 cubic mm.",
                "type": "geometric",
                "strength": "hard",
                "verification": "exact_geometry",
                "threshold": {"magnitude": 24000.0, "unit": "mm^3"},
                "comparison": "equals",
                "measurement": "volume",
                "source": "user",
                "state": "accepted",
            }
        ]
        document = Document.from_json(json.dumps(payload))
        report = verify_component(
            document, document.component("standoff"), measurement_depth=6,
            mesh_resolution=48,
        )
        identifiers = {r.gate.identifier for r in report.gate_results}
        self.assertIn("GEOM_WATERTIGHT", identifiers)
        self.assertIn("GEOM_THROUGH_HOLES_OPEN", identifiers)


class AHoleThatIsNotInThePart(unittest.TestCase):
    """A bore that is entirely interior is a hole that was filled back in.

    `GEOM_BURIED_ENTITIES` knew. It listed `shaft.bore` as 100% interior and
    reported PASS, because it is a counter compared `at_least 0` and cannot
    fail. The run completed green on a spacer block with no holes in it.

    Burial itself is usually the design working -- a post's base disappears
    into the plate it stands on. A *bore* is different: the bore is the hole.
    """

    def _payload(self, seal: bool) -> dict[str, Any]:
        features: list[dict[str, Any]] = [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 6], "unit": "mm"},
                "centered": True}},
            {"id": "bore", "kind": "hole", "inputs": ["plate"], "parameters": {
                "diameter": {"magnitude": 8.0, "unit": "mm"},
                "position": {"vector": [0, 0, 0], "unit": "mm"}}},
        ]
        if seal:
            # A solid unioned back into the bore after it was cut: the bore
            # surface is gone entirely, and nothing downstream can tell unless
            # it looks. This is what a blend did on the live run.
            features.append({"id": "plug", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 8.0, "unit": "mm"},
                "height": {"magnitude": 6.0, "unit": "mm"},
                "origin": {"vector": [0, 0, -3], "unit": "mm"}}})
            features.append(
                {"id": "body", "kind": "union", "inputs": ["bore", "plug"]}
            )
        return {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-00000000f001",
            "project_id": "00000000-0000-4000-8000-00000000f0ff",
            "revision": 1,
            "units": {"length": "mm", "mass": "g", "angle": "deg"},
            "risk_class": "low", "requirements": [], "assumptions": [],
            "components": [{
                "id": "part", "name": "Part", "parameters": [],
                "features": features, "interfaces": [],
            }],
        }

    def _report(self, seal: bool):
        document = Document.from_json(json.dumps(self._payload(seal)))
        return verify_component(
            document, document.components[0],
            measurement_depth=6, mesh_resolution=48,
        )

    def _gate(self, report, identifier):
        return next(
            (r for r in report.gate_results if r.gate.identifier == identifier),
            None,
        )

    def test_a_sealed_bore_fails(self) -> None:
        result = self._gate(self._report(seal=True), "GEOM_BORES_SURVIVE")
        self.assertIsNotNone(result, "the gate did not run at all")
        self.assertIs(result.status, Status.FAIL)
        self.assertIn("bore", result.evidence.detail["hint"])

    def test_it_is_critical_so_the_verdict_is_not_pass(self) -> None:
        report = self._report(seal=True)
        self.assertIsNot(report.overall_status, Status.PASS)

    def test_an_open_bore_raises_nothing(self) -> None:
        self.assertIsNone(self._gate(self._report(seal=False), "GEOM_BORES_SURVIVE"))

    def test_burial_of_something_that_is_not_a_bore_is_still_only_reported(
        self,
    ) -> None:
        """A post's base inside its plate is the design working, not a fault."""
        payload = self._payload(seal=False)
        payload["components"][0]["features"] = [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 6], "unit": "mm"},
                "centered": True}},
            {"id": "post", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 10.0, "unit": "mm"},
                "height": {"magnitude": 8.0, "unit": "mm"},
                "origin": {"vector": [0, 0, 0], "unit": "mm"}}},
            {"id": "body", "kind": "union", "inputs": ["plate", "post"]},
        ]
        document = Document.from_json(json.dumps(payload))
        report = verify_component(
            document, document.components[0],
            measurement_depth=6, mesh_resolution=48,
        )
        self.assertIsNone(self._gate(report, "GEOM_BORES_SURVIVE"))
        self.assertIsNotNone(self._gate(report, "GEOM_BURIED_ENTITIES"))


class TheSystemKnowsWhatItBuilt(unittest.TestCase):
    """A part fact sheet: measured, deterministic, no model anywhere near it.

    The system had no sense of the object it made. It wrote a document blind,
    and everything downstream reported on numbers *in that document* -- which
    is how a part with its plate in the wrong plane and no holes in it passed
    seven dimensional requirements and was called a release candidate.

    Two things follow from having it. A person reading the verdict sees the
    real shape beside it, and the repair analyst -- which until now got gate
    names and numbers and had to infer the shape from them -- is handed the
    part it actually built.
    """

    def _payload(self, seal: bool) -> dict[str, Any]:
        features: list[dict[str, Any]] = [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 6], "unit": "mm"},
                "centered": True}},
            {"id": "bore", "kind": "hole", "inputs": ["plate"], "parameters": {
                "diameter": {"magnitude": 8.0, "unit": "mm"},
                "position": {"vector": [0, 0, 0], "unit": "mm"}}},
        ]
        if seal:
            features += [
                {"id": "plug", "kind": "cylinder", "parameters": {
                    "diameter": {"magnitude": 8.0, "unit": "mm"},
                    "height": {"magnitude": 6.0, "unit": "mm"},
                    "origin": {"vector": [0, 0, -3], "unit": "mm"}}},
                {"id": "body", "kind": "union", "inputs": ["bore", "plug"]},
            ]
        return {
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-4000-8000-00000000f011",
            "project_id": "00000000-0000-4000-8000-00000000f0ff",
            "revision": 1,
            "units": {"length": "mm", "mass": "g", "angle": "deg"},
            "risk_class": "low", "requirements": [], "assumptions": [],
            "components": [{
                "id": "part", "name": "Part", "parameters": [],
                "features": features, "interfaces": [],
            }],
        }

    def _report(self, seal: bool):
        document = Document.from_json(json.dumps(self._payload(seal)))
        return verify_component(
            document, document.components[0],
            measurement_depth=6, mesh_resolution=48,
        )

    def test_the_fact_sheet_is_always_measured(self) -> None:
        facts = self._report(seal=False).measurements["part"]
        self.assertEqual(len(facts["envelope_mm"]), 3)
        self.assertGreater(facts["volume_mm3"], 0)

    def test_it_counts_the_holes_that_are_really_there(self) -> None:
        self.assertEqual(self._report(seal=False).measurements["part"]["open_holes"], 1)
        self.assertEqual(self._report(seal=True).measurements["part"]["open_holes"], 0)

    def test_it_names_a_hole_that_is_not_in_the_part(self) -> None:
        facts = self._report(seal=True).measurements["part"]
        hole = facts["holes"][0]
        self.assertFalse(hole["present"])
        self.assertIn("filled in", hole["note"])

    def test_it_names_features_that_left_no_surface(self) -> None:
        facts = self._report(seal=True).measurements["part"]
        self.assertIn("bore", facts["features_without_a_surface"])

    def test_the_report_shows_it_beside_the_verdict(self) -> None:
        """Buried in the JSON is not the same as visible."""
        rendered = self._report(seal=True).render()
        self.assertIn("The part as built and measured", rendered)
        self.assertIn("NOT IN THE PART", rendered)
        self.assertIn("envelope", rendered)

    def test_a_feature_that_changes_nothing_fails_the_run(self) -> None:
        report = self._report(seal=True)
        result = next(
            (r for r in report.gate_results
             if r.gate.identifier == "GEOM_FEATURES_CONTRIBUTE"), None
        )
        self.assertIsNotNone(result)
        self.assertIs(result.status, Status.FAIL)
        self.assertIsNot(report.overall_status, Status.PASS)

    def test_a_healthy_part_passes_it(self) -> None:
        report = self._report(seal=False)
        result = next(
            (r for r in report.gate_results
             if r.gate.identifier == "GEOM_FEATURES_CONTRIBUTE"), None
        )
        self.assertIsNotNone(result)
        self.assertIs(result.status, Status.PASS)

    def test_legitimate_burial_does_not_fail_it(self) -> None:
        """A post's base inside its plate loses one face, not all of them."""
        payload = self._payload(seal=False)
        payload["components"][0]["features"] = [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 6], "unit": "mm"}, "centered": True}},
            {"id": "post", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 10.0, "unit": "mm"},
                "height": {"magnitude": 8.0, "unit": "mm"},
                "origin": {"vector": [0, 0, 0], "unit": "mm"}}},
            {"id": "body", "kind": "union", "inputs": ["plate", "post"]},
        ]
        document = Document.from_json(json.dumps(payload))
        report = verify_component(
            document, document.components[0],
            measurement_depth=6, mesh_resolution=48,
        )
        result = next(
            r for r in report.gate_results
            if r.gate.identifier == "GEOM_FEATURES_CONTRIBUTE"
        )
        self.assertIs(result.status, Status.PASS)
