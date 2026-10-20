"""Claims on the finished part that used to pass whatever the part was.

Each class here is a check that read back a number, or measured too loosely
to tell right from wrong, and now measures the part.
"""

from __future__ import annotations

import copy
import json
import pathlib
import unittest

HERE = pathlib.Path(__file__).parent / "fixtures" / "real_runs"


def _load(name: str) -> dict:
    return json.loads((HERE / f"{name}.json").read_text())


def _compiled(document: dict):
    from forge_ir import Document
    from forge_kernel import Compiler

    return Compiler().compile_component(
        Document.from_json(json.dumps(document)).components[0])


def _compiled_full(document: dict):
    """A design as the designer leaves it: filled in, then compiled."""
    from forge_roles import ForgeIRDesigner, RequirementsEngineer
    from forge_roles.library import Intent

    case = _load("stepper_plate_hand_built")
    record = RequirementsEngineer().parse(case["requirements_answer"],
                                          brief=case["brief"])
    draft = ForgeIRDesigner().parse(
        {"rationale": "", "document": document}, requirements=record,
        intent=Intent(summary="", part_kind="plate", stated=(), implied=(),
                      unstated=()),
        brief=case["brief"], document_id="", project_id="", answers={})
    from forge_kernel import Compiler

    return Compiler().compile_component(draft.document.components[0])


class APlateIsMeasuredToItsThickness(unittest.TestCase):
    """The flight-controller plate measured 3.675 +/- 0.525 mm thick, so a
    claim of 4 mm passed -- and would have for a 3.5 mm plate."""

    def _sizes(self, thickness: float):
        from forge_geom import measure_mass_properties, refine_extents

        document = copy.deepcopy(_load("fc_plate_document")["document"])
        for p in document["components"][0]["parameters"]:
            if p["id"] == "plate_thickness":
                p["value"]["magnitude"] = thickness
        part = _compiled(document)
        rough = measure_mass_properties(part.solid, max_depth=7)
        return rough, refine_extents(part.solid, rough)

    def test_every_face_is_closed_in_on(self) -> None:
        rough, fine = self._sizes(4.0)
        for axis, true in enumerate((80.0, 60.0, 4.0)):
            size = fine.bounding_box_size()[axis].magnitude
            self.assertLessEqual(size.lo, true + 1e-6)
            self.assertGreaterEqual(size.hi, true - 1e-6)
            self.assertLess(size.hi - size.lo, 0.05)
            self.assertLessEqual(
                size.hi - size.lo,
                rough.bounding_box_size()[axis].magnitude.hi
                - rough.bounding_box_size()[axis].magnitude.lo)

    def test_a_thinner_plate_is_told_apart(self) -> None:
        _, fine = self._sizes(3.5)
        size = fine.bounding_box_size()[2].magnitude
        self.assertLess(size.hi, 3.6)
        self.assertGreater(size.lo, 3.4)

    def test_a_box_with_no_cell_proved_inside_is_not_reported_exact(self) -> None:
        """A bent arm plate at depth 6: no cell wholly inside, and the box
        came back as exactly 126 x 79 x 53 mm."""
        from forge_geom import measure_mass_properties

        part = _compiled(_load("fc_plate_document")["document"])
        coarse = measure_mass_properties(part.solid, max_depth=2)
        for size in coarse.bounding_box_size():
            self.assertGreaterEqual(size.magnitude.lo, 0.0)
            self.assertLess(size.magnitude.lo, size.magnitude.hi)


class ABentPartsFieldIsBoundedByItsRadii(unittest.TestCase):
    """Outside its wedge, a bend's zone was bounded only by the wedge's two
    planes -- zero all the way to the bend axis -- so no slab beside a bent
    part could be proved empty, and its box stayed millimetres wide."""

    def test_the_bounds_never_misclassify_a_cell(self) -> None:
        """What the octree and the extents rest on: a cell bounded above
        zero holds no material, one bounded below it is all material."""
        import numpy as np

        from forge_geom.sdf import Bend

        part = _compiled(_load("arm_mount_plate_bent")["document"])
        bend = part.solid
        while not isinstance(bend, Bend):
            bend = next(getattr(bend, k) for k in bend.__dataclass_fields__
                        if hasattr(getattr(bend, k), "_evaluate"))
        rng = np.random.default_rng(3)
        envelope = bend.envelope
        lo, hi = np.array(envelope.lo), np.array(envelope.hi)
        for size in (0.3, 2.0, 15.0):
            centres = lo + (hi - lo) * rng.random((400, 3))
            half = size * rng.random((400, 3))
            low, high = bend.bounds((centres - half, centres + half))
            for _ in range(10):
                points = centres + half * (2 * rng.random((400, 3)) - 1)
                field = bend(points)
                self.assertFalse(np.any((low > 0.0) & (field < 0.0)))
                self.assertFalse(np.any((high < 0.0) & (field > 0.0)))

    def test_its_box_is_the_part_s(self) -> None:
        from forge_geom import measure_mass_properties, refine_extents

        part = _compiled(_load("arm_mount_plate_bent")["document"])
        fine = refine_extents(part.solid,
                              measure_mass_properties(part.solid, max_depth=7))
        # 120 long; across, the outer radius 66 at 34.1 degrees each way;
        # up, from the inside edge at the ends to the crown.
        import math
        half = math.radians(68.209) / 2
        truth = (120.0, 2 * 66 * math.sin(half), 66 - 60 * math.cos(half))
        for axis, true in enumerate(truth):
            size = fine.bounding_box_size()[axis].magnitude
            self.assertLessEqual(size.lo, true + 0.02)
            self.assertGreaterEqual(size.hi, true - 0.02)
            self.assertLess(size.hi - size.lo, 0.3)


class FiguresWrittenAsARun(unittest.TestCase):
    """"104 x 64 mm" states 104 mm too; the first figure of every such run
    was missing from what the brief states, on three runs out of three."""

    def test_each_figure_of_a_run_is_stated(self) -> None:
        from forge_roles.library import _numbers_the_brief_states

        said = {str(q) for q in _numbers_the_brief_states(
            "Corner holes on a 104 x 64 mm rectangle, 28 × 5 mm slots, a "
            "30x20x3 mm pocket and an M3x10 mm screw.")}
        self.assertTrue({"104 mm", "64 mm", "28 mm", "5 mm", "30 mm", "20 mm",
                         "3 mm", "10 mm"} <= said)
        self.assertNotIn("3 mm", {str(q) for q in _numbers_the_brief_states(
            "an M3x10 mm screw")})


class TheStepperPlate(unittest.TestCase):
    """The hard brief, built by hand as a strong model would build it:
    a plate, a boss, a bore, a square and a circle of holes, counterbores
    and slots. Correct, it passes every claim; each way it can be wrong
    that no claim used to see is now seen."""

    def _verify(self, document: dict, answer: dict | None = None):
        from forge_pipeline import verify_component
        from forge_roles import ForgeIRDesigner, RequirementsEngineer
        from forge_roles.library import Intent

        case = _load("stepper_plate_hand_built")
        brief = case["brief"]
        record = RequirementsEngineer().parse(
            answer or case["requirements_answer"], brief=brief)
        draft = ForgeIRDesigner().parse(
            {"rationale": "", "document": document}, requirements=record,
            intent=Intent(summary="", part_kind="plate", stated=(),
                          implied=(), unstated=()),
            brief=brief, document_id="", project_id="", answers={})
        report = verify_component(draft.document, draft.document.components[0],
                                  measurement_depth=7)
        return record, {r.gate.identifier: r.status.value
                        for r in report.gate_results}

    def _features(self, document: dict) -> dict:
        return {f["id"]: f for f in document["components"][0]["features"]}

    def test_built_right_every_claim_passes(self) -> None:
        record, gates = self._verify(_load("stepper_plate_hand_built")["document"])
        measured = {r["measurement"] for r in record.requirements}
        for claim in ("counterbores:5.5:10x4,top", "standing_at:36x6:mid,mid",
                      "openings_on_circle:4.5:56", "bounding_box_z"):
            self.assertIn(claim, measured)
        self.assertEqual({k: v for k, v in gates.items()
                          if v not in ("PASS", "NOT_APPLICABLE")}, {})

    def test_a_fillet_at_the_boss_moves_no_opening(self) -> None:
        """The boss blended in with a 2 mm fillet grew the envelope by 2 mm,
        and both slots, drawn right, were measured 2 mm from where they are."""
        from forge_pipeline.measure import _the_openings_laid_flat

        document = _load("stepper_plate_hand_built")["document"]
        self.assertTrue(any(f.get("parameters", {}).get("blend_radius")
                            for f in self._features(document).values()))
        found = _the_openings_laid_flat(_compiled_full(document))
        a, b = found["axes"]
        self.assertAlmostEqual(found["lo"][a], -60.0, delta=0.2)
        self.assertAlmostEqual(found["hi"][a], 60.0, delta=0.2)

    def test_counterbores_drawn_on_the_bottom_are_turned_over(self) -> None:
        """Drilled up from the bottom, every counterbore lands underneath;
        the brief says from the top, and `entry` is turned to match."""
        document = copy.deepcopy(_load("stepper_plate_hand_built")["document"])
        for i in range(1, 5):
            self._features(document)[f"corner_hole_{i}"]["parameters"][
                "axis"] = [0, 0, 1]
        _, gates = self._verify(document)
        self.assertEqual(gates["REQ_COUNTERBORED_5_5MM"], "PASS")

    def test_counterbores_on_the_bottom_are_measured_as_such(self) -> None:
        """The measurement itself, with nothing turned over: four
        counterbores underneath are none from the top."""
        from forge_ir import Document
        from forge_pipeline import verify_component
        from forge_roles import ForgeIRDesigner, RequirementsEngineer
        from forge_roles.library import Intent

        case = _load("stepper_plate_hand_built")
        record = RequirementsEngineer().parse(case["requirements_answer"],
                                              brief=case["brief"])
        draft = ForgeIRDesigner().parse(
            {"rationale": "", "document": case["document"]},
            requirements=record,
            intent=Intent(summary="", part_kind="plate", stated=(),
                          implied=(), unstated=()),
            brief=case["brief"], document_id="", project_id="", answers={})
        payload = json.loads(json.dumps(draft.payload, default=str))
        for f in payload["components"][0]["features"]:
            if f["id"].startswith("corner_hole_"):
                f["parameters"]["axis"] = [0, 0, 1]
        built = Document.from_json(json.dumps(payload))
        report = verify_component(built, built.components[0],
                                  measurement_depth=7)
        gates = {r.gate.identifier: r.status.value for r in report.gate_results}
        self.assertEqual(gates["REQ_COUNTERBORED_5_5MM"], "FAIL")

    def test_a_boss_off_the_centre_does_not_pass(self) -> None:
        document = copy.deepcopy(_load("stepper_plate_hand_built")["document"])
        self._features(document)["boss"]["parameters"]["origin"] = {
            "vector": [10, 0, "plate_thickness"], "unit": "mm"}
        _, gates = self._verify(document)
        self.assertNotEqual(gates["REQ_BOSS_IN_THE_CENTRE"], "PASS")

    def test_the_plate_s_thickness_bound_to_the_part_s_height(self) -> None:
        """"8 mm thick" bound to `bounding_box_z` on a part the brief says
        is 14 mm tall overall failed the part the brief describes."""
        answer = copy.deepcopy(_load("stepper_plate_hand_built")[
            "requirements_answer"])
        for r in answer["requirements"]:
            if r["id"] == "REQ_PLATE_THICKNESS":
                r["measurement"] = "bounding_box_z"
        record, gates = self._verify(
            _load("stepper_plate_hand_built")["document"], answer)
        bindings = {r["id"]: r["measurement"] for r in record.requirements}
        self.assertEqual(bindings["REQ_PLATE_THICKNESS"],
                         "parameter:plate_thickness")
        self.assertEqual(bindings["REQ_OVERALL_HEIGHT"], "bounding_box_z")
        self.assertEqual({k: v for k, v in gates.items()
                          if v not in ("PASS", "NOT_APPLICABLE")}, {})

    def test_bolt_holes_bunched_on_the_circle_fail(self) -> None:
        """On the circle is half of "equally spaced on a 56 mm bolt circle"."""
        document = copy.deepcopy(_load("stepper_plate_hand_built")["document"])
        for i in range(6):
            self._features(document)[f"bolt_hole_{i + 1}"]["parameters"][
                "position"]["vector"][:2] = [
                    f"bolt_circle_diameter / 2 * cos({40 * i} * deg)",
                    f"bolt_circle_diameter / 2 * sin({40 * i} * deg)"]
        _, gates = self._verify(document)
        self.assertEqual(gates["REQ_ON_THE_CIRCLE"], "FAIL")

    def test_counterbores_drawn_as_a_second_hole_pass(self) -> None:
        """A 10 mm hole 4 mm deep over each 5.5 mm one: refused as "the same
        hole" until stepped holes were told apart from duplicates."""
        document = copy.deepcopy(_load("stepper_plate_hand_built")["document"])
        features = document["components"][0]["features"]
        out = []
        for f in features:
            if f["id"].startswith("corner_hole_"):
                p = f["parameters"]
                for key in ("counterbore_diameter", "counterbore_depth",
                            "entry"):
                    p.pop(key)
                out.append(f)
                out.append({
                    "id": f["id"].replace("corner_hole", "recess"),
                    "kind": "hole", "inputs": [f["id"]], "parameters": {
                        "diameter": {"expression": "counterbore_diameter",
                                     "unit": "mm"},
                        "position": {"vector": p["position"]["vector"][:2]
                                     + ["plate_thickness"], "unit": "mm"},
                        "axis": [0, 0, -1],
                        "depth": {"expression": "counterbore_depth",
                                  "unit": "mm"}}})
                continue
            out.append(f)
        ids = [f["id"] for f in out]
        for i, f in enumerate(out):
            # Each cut takes the one before it in the chain.
            if f["id"].startswith("corner_hole_") and f["id"] != "corner_hole_1":
                f["inputs"] = [out[i - 1]["id"]]
            if f["id"] == "slot_1":
                f["inputs"][0] = "recess_4"
        self.assertIn("recess_4", ids)
        document["components"][0]["features"] = out
        _, gates = self._verify(document)
        self.assertEqual(gates["REQ_COUNTERBORED_5_5MM"], "PASS")
        self.assertEqual({k: v for k, v in gates.items()
                          if v not in ("PASS", "NOT_APPLICABLE")}, {})
