"""Parts no live run has asked for, carrying the mistakes the model makes.

Every repair Forge has was earned on a shaft collar or a printed spacer, and
every one is written against geometry and the record -- a round body, a thin
plate, a pair of holes, a figure the brief states -- never against a part's
name. These check that claim on parts Forge has never been shown: a flange, an
oblong mounting plate and a pulley hub, each drawn the way the model draws
when it goes wrong. Each should come out as the part its brief describes.
"""

from __future__ import annotations

import unittest


def _requirement(identifier, statement, binding, figure, unit="mm"):
    return {
        "id": identifier, "statement": statement, "measurement": binding,
        "comparison": "equals",
        "threshold": {"magnitude": figure, "unit": unit},
        "type": "geometric", "verification": "exact_geometry",
        "strength": "hard", "source": "user", "state": "accepted",
    }


def _build(brief, requirements, document):
    from forge_pipeline import verify_component
    from forge_roles import ForgeIRDesigner, RequirementsEngineer
    from forge_roles.library import Intent

    record = RequirementsEngineer().parse(
        {"risk_class": "low", "requirements": requirements,
         "assumptions": [], "unknowns": []}, brief=brief)
    draft = ForgeIRDesigner().parse(
        {"rationale": "unseen", "document": document}, requirements=record,
        intent=Intent(summary="", part_kind="", stated=(), implied=(),
                      unstated=()),
        brief=brief, document_id="", project_id="", answers={})
    report = verify_component(
        draft.document, draft.document.components[0], measurement_depth=6)
    return draft, report


def _not_passing(report):
    return {r.gate.identifier: r.status.value for r in report.gate_results
            if r.status.value not in ("PASS", "NOT_APPLICABLE")}


def _holes(report):
    return {h["feature"]: h for h in report.measurements["part"]["holes"]}


class AFlange(unittest.TestCase):
    """Nothing declared, no bore, and both bolt holes drawn at the centre,
    one drilled along x and one along y."""

    BRIEF = ("A steel flange disc 60 mm across and 8 mm thick. A 20 mm bore "
             "runs through the centre. Two 6 mm bolt holes pass all the way "
             "through the disc, 40 mm apart. It carries no load.")

    def test_it_is_the_flange(self) -> None:
        requirements = [
            _requirement("REQ_D", "The flange diameter is 60 mm",
                         "parameter:flange_diameter", 60),
            _requirement("REQ_T", "The flange thickness is 8 mm",
                         "parameter:flange_thickness", 8),
            _requirement("REQ_B", "The bore diameter is 20 mm",
                         "parameter:bore_diameter", 20),
            _requirement("REQ_BH", "The bolt hole diameter is 6 mm",
                         "parameter:bolt_hole_diameter", 6),
            _requirement("REQ_S", "The bolt holes are 40 mm apart",
                         "parameter:bolt_hole_spacing", 40),
        ]

        def bolt(i, axis):
            return {"id": f"bolt_hole_{i}", "kind": "hole", "parameters": {
                "diameter": {"expression": "bolt_hole_diameter", "unit": "mm"},
                "position": {"vector": [0, 0, "flange_thickness / 2"],
                             "unit": "mm"},
                "axis": axis}}

        document = {"name": "Flange", "components": [{"id": "flange",
                    "features": [
            {"id": "disc", "kind": "cylinder", "parameters": {
                "diameter": {"expression": "flange_diameter", "unit": "mm"},
                "height": {"expression": "flange_thickness", "unit": "mm"}}},
            bolt(1, [1.0, 0.0, 0.0]), bolt(2, [0.0, 1.0, 0.0])]}]}
        _, report = _build(self.BRIEF, requirements, document)
        self.assertEqual(_not_passing(report), {})
        holes = _holes(report)
        self.assertEqual(len(holes), 3)
        self.assertTrue(all(h["present"] for h in holes.values()))
        self.assertAlmostEqual(holes["bore"]["diameter_mm"], 20.0)
        self.assertEqual(sorted(round(holes[f"bolt_hole_{i}"]["centre_mm"][0], 6)
                                for i in (1, 2)), [-20.0, 20.0])


class AnOblongPlate(unittest.TestCase):
    """Every size a number, and both holes drawn at the centre. 50 mm apart
    fits along the 80 mm length and not across the 40 mm width, so there is
    one way to place them."""

    BRIEF = ("An aluminium mounting plate 80 mm long, 40 mm wide and 5 mm "
             "thick. Two 5 mm holes pass through the plate, 50 mm apart. It "
             "carries no load.")

    def _requirements(self):
        return [
            _requirement("REQ_L", "The plate length is 80 mm",
                         "parameter:plate_length", 80),
            _requirement("REQ_W", "The plate width is 40 mm",
                         "parameter:plate_width", 40),
            _requirement("REQ_T", "The plate thickness is 5 mm",
                         "parameter:plate_thickness", 5),
            _requirement("REQ_H", "The hole diameter is 5 mm",
                         "parameter:hole_diameter", 5),
            _requirement("REQ_S", "The holes are 50 mm apart",
                         "parameter:hole_spacing", 50),
        ]

    @staticmethod
    def _document(length=80):
        def hole(i):
            return {"id": f"hole_{i}", "kind": "hole", "parameters": {
                "diameter": {"magnitude": 5, "unit": "mm"},
                "position": {"vector": [0, 0, 0], "unit": "mm"}}}
        return {"name": "Plate", "components": [{"id": "plate", "features": [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [length, 40, 5], "unit": "mm"},
                "centered": True}},
            hole(1), hole(2)]}]}

    def test_it_is_the_plate(self) -> None:
        draft, report = _build(self.BRIEF, self._requirements(),
                               self._document())
        self.assertEqual(_not_passing(report), {})
        holes = _holes(report)
        self.assertEqual(sorted(round(h["centre_mm"][0], 6)
                                for h in holes.values()), [-25.0, 25.0])
        size = draft.payload["components"][0]["features"][0]["parameters"][
            "size"]["vector"]
        # A 5 mm thickness and a 5 mm hole are two dimensions: the plate's
        # third side is its thickness, never a hole's diameter.
        self.assertEqual(size, ["plate_length", "plate_width",
                                "plate_thickness"])

    def test_where_both_ways_fit_it_is_a_choice(self) -> None:
        """A 60 by 58 plate holds the pair either way, and the two are not
        the same part: the designer is told where the holes are."""
        from forge_roles.base import RoleOutputError

        requirements = self._requirements()
        requirements[0]["threshold"]["magnitude"] = 60
        requirements[1]["threshold"]["magnitude"] = 58
        document = self._document(length=60)
        document["components"][0]["features"][0]["parameters"]["size"][
            "vector"][1] = 58
        brief = self.BRIEF.replace("80 mm long, 40 mm wide",
                                   "60 mm long, 58 mm wide")
        with self.assertRaises(RoleOutputError) as caught:
            _build(brief, requirements, document)
        self.assertIn("are both drawn at", " ".join(caught.exception.problems))


class APulleyHub(unittest.TestCase):
    """One set screw drilled straight across, no bore, every size a number."""

    BRIEF = ("A pulley hub 40 mm in diameter and 20 mm long. An 8 mm bore "
             "runs all the way through on the axis. One 3 mm set screw hole "
             "passes through the wall into the bore, halfway along. It "
             "carries no load.")

    def test_it_is_the_hub(self) -> None:
        import numpy as np

        requirements = [
            _requirement("REQ_D", "The hub diameter is 40 mm",
                         "parameter:hub_diameter", 40),
            _requirement("REQ_L", "The hub length is 20 mm",
                         "parameter:hub_length", 20),
            _requirement("REQ_B", "The bore diameter is 8 mm",
                         "parameter:bore_diameter", 8),
            _requirement("REQ_S", "The set screw hole diameter is 3 mm",
                         "parameter:set_screw_hole_diameter", 3),
        ]
        document = {"name": "Hub", "components": [{"id": "hub", "features": [
            {"id": "hub", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 40, "unit": "mm"},
                "height": {"magnitude": 20, "unit": "mm"}}},
            {"id": "set_screw_hole", "kind": "hole", "parameters": {
                "diameter": {"magnitude": 3, "unit": "mm"},
                "position": {"vector": [0, 0, 10], "unit": "mm"},
                "axis": [1.0, 0.0, 0.0]}}]}]}
        _, report = _build(self.BRIEF, requirements, document)
        self.assertEqual(_not_passing(report), {})

        def openings(radius):
            turn = np.linspace(0, 2 * np.pi, 720, endpoint=False)
            ring = np.stack([radius * np.cos(turn), radius * np.sin(turn),
                             np.full_like(turn, 10.0)], 1)
            empty = np.asarray(report.part.solid(ring)) > 0
            return sum(1 for i in range(len(empty))
                       if empty[i] and not empty[i - 1])

        self.assertEqual(openings(19.3), 1, "one opening round the outside")
        self.assertEqual(openings(4.3), 1, "and it reaches the bore")


class FourHolesOnARectangle(unittest.TestCase):
    """The rectangle repair on a plate the model drew with no holes at all,
    and on a square plate where either way round is the same part."""

    BRIEF = ("An aluminium mounting plate 70 mm long, 50 mm wide and 4 mm "
             "thick. Four 4 mm holes pass through the plate, one near each "
             "corner, with their centres on a 56 mm by 36 mm rectangle. It "
             "carries no load, so there is no load case.")

    def _requirements(self):
        return [
            _requirement("REQ_L", "The plate length is 70 mm",
                         "parameter:plate_length", 70),
            _requirement("REQ_W", "The plate width is 50 mm",
                         "parameter:plate_width", 50),
            _requirement("REQ_T", "The plate thickness is 4 mm",
                         "parameter:plate_thickness", 4),
            _requirement("REQ_H", "The hole diameter is 4 mm",
                         "parameter:hole_diameter", 4),
            _requirement("REQ_RL", "The rectangle length is 56 mm",
                         "parameter:rectangle_length", 56),
            _requirement("REQ_RW", "The rectangle width is 36 mm",
                         "parameter:rectangle_width", 36),
        ]

    def test_holes_never_drawn_are_drilled_on_its_corners(self) -> None:
        document = {"name": "Plate", "components": [{"id": "plate",
                    "features": [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": ["plate_length", "plate_width",
                                    "plate_thickness"], "unit": "mm"},
                "centered": True}}]}]}
        draft, report = _build(self.BRIEF, self._requirements(), document)
        self.assertEqual(_not_passing(report), {})
        centres = sorted((round(h["centre_mm"][0], 6), round(h["centre_mm"][1], 6))
                         for h in report.measurements["part"]["holes"])
        self.assertEqual(centres, [(-28.0, -18.0), (-28.0, 18.0),
                                   (28.0, -18.0), (28.0, 18.0)])

    def test_a_rectangle_that_fits_either_way_on_an_oblong_plate_is_asked(
        self,
    ) -> None:
        from forge_roles.base import RoleOutputError

        brief = self.BRIEF.replace("56 mm by 36 mm", "30 mm by 20 mm")
        requirements = self._requirements()
        requirements[4]["threshold"]["magnitude"] = 30
        requirements[5]["threshold"]["magnitude"] = 20
        document = {"name": "Plate", "components": [{"id": "plate",
                    "features": [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": ["plate_length", "plate_width",
                                    "plate_thickness"], "unit": "mm"},
                "centered": True}}]}]}
        with self.assertRaises(RoleOutputError):
            _build(brief, requirements, document)


if __name__ == "__main__":
    unittest.main()
