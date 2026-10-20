"""The V1 capabilities that complete single-part design.

Where an opening is, measured on the part; every placement the brief states
checked there; and the shapes a single part of any kind needs.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_real_answers import _design, _load, _not_passing, _requirements, _verify  # noqa: E402


class WhereAnOpeningIs(unittest.TestCase):
    """`opening_at`: the distance from where the brief puts an opening to
    the nearest one of its size on the built part, laid flat."""

    def test_the_binding_reads_and_refuses(self) -> None:
        from forge_ir.measurements import MeasurementError, parse_measurement

        binding = parse_measurement("opening_at:8.2:hi18,mid")
        self.assertEqual((binding.kind, binding.argument, binding.sub_argument),
                         ("opening_at", "8.2", "hi18,mid"))
        self.assertEqual(parse_measurement("opening_at:28x5:end22,mid-3")
                         .sub_argument, "end22,mid-3")
        for wrong in ("opening_at:8.2", "opening_at:8.2:hi18",
                      "opening_at:big:hi18,mid", "opening_at:8.2:top,mid"):
            with self.assertRaises(MeasurementError, msg=wrong):
                parse_measurement(wrong)

    def _plate(self, *cuts):
        from forge_ir import Document
        from forge_kernel import Compiler

        features = [{"id": "plate", "kind": "box", "parameters": {
            "size": {"vector": [100, 60, 5], "unit": "mm"}, "centered": True}}]
        previous = "plate"
        for index, (x, y, d) in enumerate(cuts):
            features.append({"id": f"h{index}", "kind": "hole",
                             "inputs": [previous], "parameters": {
                                 "diameter": {"magnitude": d, "unit": "mm"},
                                 "position": {"vector": [x, y, 0], "unit": "mm"}}})
            previous = f"h{index}"
        document = Document.from_json(json.dumps({
            "schema_version": "1.0.0",
            "document_id": "00000000-0000-5000-8000-000000000000",
            "project_id": "00000000-0000-5000-8000-000000000000",
            "revision": 1, "name": "p",
            "units": {"length": "mm", "mass": "kg", "time": "s", "angle": "deg",
                      "force": "N", "stress": "MPa"},
            "risk_class": "low",
            "components": [{"id": "c", "features": features}],
            "requirements": [], "assumptions": [],
            "provenance": {"created_by": "", "tool_version": ""}}))
        return Compiler().compile_component(document.components[0])

    def test_it_reads_where_each_hole_is(self) -> None:
        from forge_ir.measurements import parse_measurement
        from forge_pipeline.measure import _an_opening_at

        part = self._plate((32, 0, 6), (-40, 15, 4))

        def gap(binding: str) -> float:
            m = _an_opening_at(part, parse_measurement(binding))
            self.assertTrue(m.ok, binding)
            return float(m.value.magnitude.midpoint)

        self.assertLess(gap("opening_at:6:hi18,mid"), 0.2)
        self.assertLess(gap("opening_at:6:end18,mid"), 0.2)
        self.assertAlmostEqual(gap("opening_at:6:lo18,mid"), 64.0, delta=0.3)
        self.assertLess(gap("opening_at:4:lo10,mid+15"), 0.2)
        self.assertLess(gap("opening_at:4:end10,side15"), 0.2)
        self.assertAlmostEqual(gap("opening_at:4:lo10,mid"), 15.0, delta=0.3)
        missing = _an_opening_at(part, parse_measurement("opening_at:9:mid,mid"))
        self.assertFalse(missing.ok)

    def test_the_record_checks_every_placement_the_brief_states(self) -> None:
        requirements = _requirements(_load("plate_pillow_drilled_along_its_length"))
        placed = sorted(dict(r)["measurement"] for r in requirements.requirements
                        if dict(r)["measurement"].startswith("opening_at"))
        self.assertEqual(placed, [
            "opening_at:28x5:hi22,mid", "opening_at:28x5:lo22,mid",
            "opening_at:8.2:end18,mid", "opening_at:8.2:end48,mid"])
        requirements = _requirements(
            _load("plate_holes_on_a_rectangle_drawn_as_a_solid"))
        placed = sorted(dict(r)["measurement"] for r in requirements.requirements
                        if dict(r)["measurement"].startswith("opening_at"))
        self.assertEqual(placed, [
            "opening_at:4:mid+28,mid+18", "opening_at:4:mid+28,mid-18",
            "opening_at:4:mid-28,mid+18", "opening_at:4:mid-28,mid-18"])

    def test_a_correct_plate_passes_its_placements(self) -> None:
        draft = _design(_load("plate_holes_on_a_rectangle_drawn_as_a_solid"))
        report = _verify(draft)
        placed = [r for r in report.gate_results
                  if r.gate.identifier.startswith("REQ_AT_")]
        self.assertEqual(len(placed), 4)
        self.assertEqual(_not_passing(report), {})

    def test_a_bolt_circle_is_checked_on_the_part(self) -> None:
        case = _load("flange_bolt_circle_never_placed")
        requirements = _requirements(case)
        self.assertIn("openings_on_circle:8:60", [
            dict(r)["measurement"] for r in requirements.requirements])
        report = _verify(_design(case))
        on = next(r for r in report.gate_results
                  if r.gate.identifier == "REQ_ON_THE_CIRCLE")
        self.assertEqual(on.status.value, "PASS")
        for gap in on.evidence.detail["angles_between_deg"]:
            self.assertAlmostEqual(gap, 90.0, delta=0.5)

    def test_a_brief_that_places_nothing_gets_no_placement(self) -> None:
        from forge_roles.library import _where_the_brief_places_its_openings

        record: list = []
        self.assertEqual(_where_the_brief_places_its_openings(
            "A 30 mm cube with a 6 mm hole through it.", record), [])
        self.assertEqual(record, [])


def _build(features, parameters=()):
    from forge_ir import Document
    from forge_kernel import Compiler

    document = Document.from_json(json.dumps({
        "schema_version": "1.0.0",
        "document_id": "00000000-0000-5000-8000-000000000000",
        "project_id": "00000000-0000-5000-8000-000000000000",
        "revision": 1, "name": "p",
        "units": {"length": "mm", "mass": "kg", "time": "s", "angle": "deg",
                  "force": "N", "stress": "MPa"},
        "risk_class": "low",
        "components": [{"id": "c", "material": "pla_fdm",
                        "features": features, "parameters": list(parameters)}],
        "requirements": [], "assumptions": [],
        "provenance": {"created_by": "", "tool_version": ""}}))
    return document, Compiler().compile_component(document.components[0])


def _volume(part) -> float:
    from forge_geom import measure_mass_properties

    properties = measure_mass_properties(part.solid, max_depth=7)
    return float(properties.volume.magnitude.midpoint)


def _encloses(case: unittest.TestCase, part, exact: float,
              width: float = 0.3) -> None:
    """The measured volume's enclosure holds the exact figure -- the
    measurement is an interval, and its claim is that the truth is in it."""
    from forge_geom import measure_mass_properties

    volume = measure_mass_properties(part.solid, max_depth=8).volume.magnitude
    case.assertLessEqual(float(volume.lo), exact)
    case.assertGreaterEqual(float(volume.hi), exact)
    case.assertLess(float(volume.hi - volume.lo), width * exact)


def _mm(value):
    return {"magnitude": value, "unit": "mm"}


_XY = {"id": "xy", "kind": "datum_plane", "parameters": {"base": "XY"}}


class EveryShapeASinglePartNeeds(unittest.TestCase):
    """The shapes added so that any single part can be drawn: each builds,
    measures what its geometry says, and passes the part's own checks."""

    def _passes(self, document) -> None:
        from forge_pipeline import verify_component

        report = verify_component(document, document.components[0],
                                  measurement_depth=5)
        self.assertEqual(_not_passing(report), {})

    def test_a_box_with_rounded_edges(self) -> None:
        import math

        document, part = _build([{"id": "b", "kind": "box", "parameters": {
            "size": {"vector": [40, 30, 20], "unit": "mm"}, "centered": True,
            "edge_radius": _mm(4)}}])
        r = 4.0
        # A box rounded on every edge: the core, its faces' slabs, its
        # edges' quarter cylinders and its corners' eighth spheres.
        a, b, c = 40 - 2 * r, 30 - 2 * r, 20 - 2 * r
        exact = (a * b * c + 2 * r * (a * b + b * c + a * c)
                 + math.pi * r * r * (a + b + c) + 4 / 3 * math.pi * r ** 3)
        _encloses(self, part, exact)
        self._passes(document)

    def test_a_box_chamfered_round_its_top_only(self) -> None:
        _, part = _build([{"id": "b", "kind": "box", "parameters": {
            "size": {"vector": [40, 30, 20], "unit": "mm"},
            "edge_chamfer": _mm(3), "edges": "top"}}])
        # Four 3 mm chamfers round the top: prisms of 4.5 mm^2 section, the
        # corners where two meet counted once.
        exact = 40 * 30 * 20 - 4.5 * (2 * 40 + 2 * 30) + 4 * 9.0
        _encloses(self, part, exact)

    def test_a_sketched_outline_of_any_shape(self) -> None:
        document, part = _build([
            _XY,
            {"id": "s", "kind": "profile_sketch", "inputs": ["xy"],
             "parameters": {"points": {"points": [[0, 0], [60, 0], [60, 20],
                                                  [20, 20], [20, 50], [0, 50]],
                                       "unit": "mm"}}},
            {"id": "e", "kind": "extrude", "inputs": ["s"],
             "parameters": {"distance": _mm(6)}}])
        _encloses(self, part, (60 * 20 + 20 * 30) * 6)
        self._passes(document)

    def test_a_rounded_sketch_corner_is_an_arc(self) -> None:
        import math

        from forge_geom import SketchProfile, sketch_outline

        square = SketchProfile(sketch_outline(
            [[0, 0], [20, 0], [20, 20], [0, 20]], corner_radius=5,
            steps=64))
        u_lo, u_hi, v_lo, v_hi = square.bounds()
        self.assertEqual((u_lo, u_hi, v_lo, v_hi), (0.0, 20.0, 0.0, 20.0))
        # The corner's arc is 5 mm from its centre all along it.
        import numpy as np
        angle = np.linspace(0, math.pi / 2, 9)
        u = 15 + 5 * np.cos(angle) * 0.999
        v = 15 + 5 * np.sin(angle) * 0.999
        self.assertTrue(np.all(square.distance(u, v) < 0))
        self.assertGreater(square.distance(np.array([19.9]),
                                           np.array([19.9]))[0], 0)

    def test_a_spur_gear(self) -> None:
        import numpy as np

        from forge_geom import GearProfile, SketchProfile, gear_outline

        gear = GearProfile(module=2, teeth=20)
        reference = SketchProfile(gear_outline(2, 20))
        points = np.random.default_rng(3).uniform(-25, 25, (5000, 2))
        self.assertLess(float(np.max(np.abs(
            gear.distance(points[:, 0], points[:, 1])
            - reference.distance(points[:, 0], points[:, 1])))), 1e-9)
        self.assertEqual(gear.bounds()[1], 22.0)  # m (z + 2) / 2
        # On the pitch circle half the circumference is tooth.
        angle = np.linspace(0, 2 * np.pi, 4000, endpoint=False)
        inside = gear.distance(20 * np.cos(angle), 20 * np.sin(angle)) < 0
        self.assertAlmostEqual(float(inside.mean()), 0.5, delta=0.02)

    def test_a_tube_bent_along_a_path(self) -> None:
        import math

        document, part = _build([{"id": "t", "kind": "pipe", "parameters": {
            "diameter": _mm(20), "inner_diameter": _mm(16),
            "path": {"points": [[0, 0, 0], [100, 0, 0]], "unit": "mm"}}}])
        # A 2 mm wall is thin for the octree: the enclosure is wide, and
        # still holds the figure.
        _encloses(self, part, math.pi * (10 ** 2 - 8 ** 2) * 100, width=3.0)
        self._passes(document)

    def test_a_handle_bent_round(self) -> None:
        document, part = _build([{"id": "h", "kind": "pipe", "parameters": {
            "diameter": _mm(10), "bend_radius": _mm(10),
            "path": {"points": [[0, 0, 0], [0, 0, 30], [80, 0, 30],
                                [80, 0, 0]], "unit": "mm"}}}])
        lo, hi = part.solid.envelope.lo, part.solid.envelope.hi
        self.assertEqual(tuple(round(v, 6) for v in lo), (-5.0, -5.0, -5.0))
        self.assertEqual(tuple(round(v, 6) for v in hi), (85.0, 5.0, 35.0))
        self._passes(document)

    def test_a_spring(self) -> None:
        import math

        _, part = _build([{"id": "s", "kind": "coil", "parameters": {
            "diameter": _mm(20), "wire_diameter": _mm(2), "pitch": _mm(5),
            "turns": 3}}])
        wire = math.hypot(math.pi * 20, 5) * 3
        # Drawn as straight runs between points on the helix: a fraction
        # of a per cent short of the true helix.
        exact = math.pi * 1.0 ** 2 * wire
        self.assertAlmostEqual(_volume(part), exact, delta=0.08 * exact)

    def test_a_square_to_round_loft(self) -> None:
        _, part = _build([
            _XY,
            {"id": "top", "kind": "datum_plane",
             "parameters": {"base": "XY", "offset": _mm(40)}},
            {"id": "sq", "kind": "profile_rectangle", "inputs": ["xy"],
             "parameters": {"width": _mm(40), "height": _mm(40)}},
            {"id": "ci", "kind": "profile_circle", "inputs": ["top"],
             "parameters": {"diameter": _mm(20)}},
            {"id": "l", "kind": "loft", "inputs": ["sq", "ci"]}])
        volume = _volume(part)
        # Between the circle's cylinder and the square's prism.
        self.assertGreater(volume, 3.14159 * 100 * 40)
        self.assertLess(volume, 1600 * 40)
        box = part.solid.envelope
        self.assertEqual((box.lo[2], box.hi[2]), (0.0, 40.0))

    def test_a_profile_swept_along_a_path(self) -> None:
        _, part = _build([
            _XY,
            {"id": "p", "kind": "profile_rectangle", "inputs": ["xy"],
             "parameters": {"width": _mm(12), "height": _mm(6)}},
            {"id": "s", "kind": "sweep", "inputs": ["p"], "parameters": {
                "path": {"points": [[0, 0, 0], [60, 0, 0]], "unit": "mm"}}}])
        _encloses(self, part, 12 * 6 * 60)

    def test_a_countersunk_and_a_counterbored_hole(self) -> None:
        import math

        import numpy as np

        _, part = _build([
            {"id": "b", "kind": "box", "parameters": {
                "size": {"vector": [60, 40, 8], "unit": "mm"},
                "centered": True}},
            {"id": "h1", "kind": "hole", "inputs": ["b"], "parameters": {
                "diameter": _mm(5), "countersink_diameter": _mm(10),
                "position": {"vector": [-15, 0, 0], "unit": "mm"}}},
            {"id": "h2", "kind": "hole", "inputs": ["h1"], "parameters": {
                "diameter": _mm(5), "counterbore_diameter": _mm(9),
                "counterbore_depth": _mm(3),
                "position": {"vector": [15, 0, 0], "unit": "mm"}}}])
        solid = part.solid
        # The counterbore is 3 mm deep from the face the hole enters by,
        # not from the point it was declared through.
        def inside(x, y, z):
            return float(solid(np.array([[x, y, z]]))[0]) < 0
        self.assertFalse(inside(15 + 4.0, 0, -3.5))   # in the counterbore
        self.assertTrue(inside(15 + 4.0, 0, -0.5))    # below it, solid
        # The countersink: 10 mm across at the face, 90 degrees.
        self.assertFalse(inside(-15 + 4.8, 0, -3.95))
        self.assertTrue(inside(-15 + 4.8, 0, -1.0))
        removed = 60 * 40 * 8 - _volume(part)
        bore = math.pi * 2.5 ** 2 * 8
        self.assertGreater(removed, 2 * bore)

    def test_a_drafted_boss_and_a_chamfered_joint(self) -> None:
        import math

        _, part = _build([
            _XY,
            {"id": "c", "kind": "profile_circle", "inputs": ["xy"],
             "parameters": {"diameter": _mm(30)}},
            {"id": "e", "kind": "extrude", "inputs": ["c"], "parameters": {
                "distance": _mm(20),
                "draft_angle": {"magnitude": 5, "unit": "deg"}}}])
        top = 15 - 20 * math.tan(math.radians(5))
        _encloses(self, part, math.pi * 20 / 3 * (15 ** 2 + 15 * top + top ** 2))
        import numpy as np

        def joint(chamfer):
            parameters = {"chamfer": _mm(chamfer)} if chamfer else {}
            return _build([
                {"id": "a", "kind": "box", "parameters": {
                    "size": {"vector": [60, 40, 5], "unit": "mm"}}},
                {"id": "b", "kind": "box", "parameters": {
                    "size": {"vector": [5, 40, 30], "unit": "mm"}}},
                {"id": "u", "kind": "union", "inputs": ["a", "b"],
                 "parameters": parameters}])[1].solid

        crease = np.array([[5.5, 20.0, 5.5]])
        self.assertGreater(float(joint(0)(crease)[0]), 0)
        self.assertLess(float(joint(3)(crease)[0]), 0)
        # A 45 degree chamfer of 3 mm: its face passes 1.5 mm from the crease
        # along the diagonal, and no further.
        self.assertGreater(float(joint(3)(np.array([[7.2, 20.0, 7.2]]))[0]), 0)


class TheDesignerIsOfferedWhatTheBriefNeeds(unittest.TestCase):
    def test_kinds_come_with_the_words_for_them(self) -> None:
        from forge_roles.library import _the_kinds_the_brief_asks_for

        self.assertEqual(_the_kinds_the_brief_asks_for(
            "A PLA spur gear, module 2, 20 teeth."), ["profile_gear"])
        self.assertIn("coil", _the_kinds_the_brief_asks_for(
            "A compression spring 20 mm across, 6 turns."))
        self.assertIn("pipe", _the_kinds_the_brief_asks_for(
            "A grab handle bent from 10 mm rod."))
        self.assertIn("loft", _the_kinds_the_brief_asks_for(
            "A square-to-round duct adapter."))
        self.assertEqual(_the_kinds_the_brief_asks_for(
            "A 30 mm cube with a 6 mm hole through it."), [])

    def test_the_brief_s_kinds_reach_the_designer(self) -> None:
        from forge_roles import ForgeIRDesigner
        from forge_roles.library import Intent, RequirementSet

        messages = ForgeIRDesigner().build_messages(
            intent=Intent(summary="A spring", part_kind="spring", stated=(),
                          implied=(), unstated=()),
            requirements=RequirementSet(requirements=(), assumptions=(),
                                        unknowns=(), risk_class="low"),
            brief="A steel compression spring, 20 mm across, 6 turns.")
        text = "\n".join(m.content for m in messages)
        self.assertIn("Further features this part may need", text)
        self.assertIn("`coil`", text)
        self.assertNotIn("`profile_gear`", text)


if __name__ == "__main__":
    unittest.main()


class ARepairThePartMeasuresWorseWithIsTakenBack(unittest.TestCase):
    def test_a_draft_knows_its_repairs_and_can_be_settled_without_one(self) -> None:
        from forge_roles import ForgeIRDesigner
        from test_real_answers import _intent

        case = _load("l_bracket_holes_named_for_their_places")
        inputs = dict(requirements=_requirements(case), intent=_intent(case),
                      brief=case["brief"], document_id="", project_id="",
                      answers={})
        designer = ForgeIRDesigner()
        draft = designer.parse(case["answer"], **inputs)
        self.assertIn("_holes_placed_where_the_brief_puts_them",
                      draft.repairs_made)
        self.assertIsNotNone(draft.answer)
        # Without the reading that declares the bracket's width, the design
        # does not validate: nothing to offer instead.
        self.assertIsNone(designer.without(
            draft, "_a_size_the_brief_gives_the_part", **inputs))

    def _report(self, *failing):
        from types import SimpleNamespace as N

        from forge_evidence import Status

        return N(gate_results=[
            N(status=Status.FAIL, gate=N(identifier=g, critical=True))
            for g in failing])

    def _orchestrator(self, outcomes):
        from types import SimpleNamespace as N

        from forge_orchestrator import Orchestrator

        tried = []

        class Designer:
            def without(self, draft, name, **_):
                tried.append(name)
                return N(document=N(components=[N(identifier=name)]),
                         payload={}, repairs_made=())

        fake = N(_roles={"designer": Designer()},
                 _REPAIRS_TRIED_WITHOUT=Orchestrator._REPAIRS_TRIED_WITHOUT,
                 _verify=lambda document, component: outcomes[component])
        return fake, tried

    def test_only_a_strictly_better_part_without_breaking_anything(self) -> None:
        from types import SimpleNamespace as N

        from forge_orchestrator import Orchestrator

        events = []
        run = N(record=lambda *a, **k: events.append(a))
        before = self._report("A", "B")
        draft = N(repairs_made=("first", "second", "third"))
        outcomes = {"third": self._report("A", "B", "C"),   # breaks C
                    "second": self._report("A", "B"),       # no better
                    "first": self._report("A")}             # better
        fake, tried = self._orchestrator(outcomes)
        found = Orchestrator._without_a_repair_that_hurt(fake, run, draft, before)
        self.assertEqual(tried, ["third", "second", "first"])
        self.assertIsNotNone(found)
        self.assertEqual(found[0].document.components[0].identifier, "first")
        self.assertIn("took back Forge's own repair `first`", events[-1][1])
        outcomes = {"third": self._report("A", "B", "C"),
                    "second": self._report("A", "B"),
                    "first": self._report("B", "D")}
        fake, _ = self._orchestrator(outcomes)
        self.assertIsNone(
            Orchestrator._without_a_repair_that_hurt(fake, run, draft, before))


class EveryFailedCheckReachesTheModelInOneShape(unittest.TestCase):
    def test_the_difference_where_and_what_moves_it(self) -> None:
        from types import SimpleNamespace as N

        from forge_evidence import Status
        from forge_orchestrator.orchestrator import _gate_failure
        from forge_units import Q

        result = N(
            status=Status.FAIL,
            gate=N(identifier="REQ_PART_LONG", claim="The part shall be 120 mm "
                   "long.", comparison="equals", threshold=Q(120.0, "mm")),
            evidence=N(result=Q(122.784, "mm"), limitations=(),
                       detail={"measurement": "flat_extent_side:120",
                               "axis": "x"}))
        told = _gate_failure(result)
        self.assertEqual(told["off_by"], "2.784 mm over")
        self.assertIn('"axis": "x"', told["where"])
        self.assertIn("laid flat", told["what_it_measures"])
        blocked = N(
            status=Status.BLOCKED,
            gate=N(identifier="REQ_AT_8_2_END18_MID", claim="...",
                   comparison="at_most", threshold=Q(0.5, "mm")),
            evidence=N(result=None, limitations=(),
                       detail={"measurement": "opening_at:8.2:end18,mid",
                               "blocked_reason": "the part has no opening "
                               "right through it of 8.2 mm"}))
        told = _gate_failure(blocked)
        self.assertEqual(told["status"], "BLOCKED")
        self.assertIn("no opening", told["why_it_could_not_be_measured"])
