"""A zoo of shapes, each drawn right, each checked by Forge to the end.

Twenty small parts written the way a designer answers a brief -- a flange
with a hub, a cup with a drain, a bent strip, a coil spring, a metre-long
box with 3 mm walls -- each a correct design. Every one must come out of
the designer's settle and the verifier with no critical check failing:
a correct part held back by Forge's own checks is Forge's defect.

What the zoo found, and is tested here as it was met:

- openings read laid flat were sampled at a quarter, half and three
  quarters through the part, so a flange's bolt holes under a tall hub, and
  holes under counterbores deeper than a quarter of the plate, were never
  found;
- "bent 90 degrees in the middle, with a 6 mm hole 15 mm from each end"
  was read as two bends 15 mm from each end, and the one hole as centred;
- the design's own `angle` was turned into a second claim on the bend's
  angle, beside the record's, and one of the two was left unmeasured;
- a cup's floor and depth were read on the line through its drain hole;
- a 3 mm wall on a metre-long box lay between the mesher's samples, and the
  part "had no surface";
- `standing_at:20x15:centre`, `openings_of_size:6`: claims written next to
  their grammar, left unmeasured instead of read as they mean;
- on big parts, small features measured on grids sized to the whole part:
  a 4 mm hole's diameter "drove nothing", 3 mm holes read 4.2 by 2.8, a
  10 mm boss three steps across;
- "1/2 inch" read as 2 inches.

And parts made at random (`shape_generator`) found more: a hole "in each
corner" counted as one, "an upright 60 mm tall" read as the base standing
up, neighbouring counterbores failed for touching, a bend's "halfway along"
taken for the holes' and their "from each end" for the bend's.
"""

from __future__ import annotations

import glob
import os
import pathlib
import sys
import unittest

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from test_real_answers import _design, _load  # noqa: E402

_HERE = pathlib.Path(__file__).parent
_ZOO = sorted(
    os.path.basename(f)[:-5]
    for f in glob.glob(str(_HERE / "fixtures" / "real_runs" / "zoo2_*.json")))


def _held_back(report) -> dict[str, str]:
    """Every check that keeps a part from release: a critical gate that
    failed or could not run, and a requirement nothing measured."""
    held = {}
    for result in report.gate_results:
        status = result.status.value
        if status in ("FAIL", "BLOCKED") and result.gate.critical:
            held[result.gate.identifier] = status
        elif status == "NOT_TESTED" and result.gate.identifier.startswith(
                "REQ_"):
            held[result.gate.identifier] = status
    return held


class EveryShapeInTheZooPasses(unittest.TestCase):
    """Each correct design passes every critical check, measured at the
    depth a run uses."""

    def test_the_zoo_is_there(self) -> None:
        self.assertGreaterEqual(len(_ZOO), 20)

    def test_each_shape(self) -> None:
        from forge_pipeline import verify_component

        for name in _ZOO:
            with self.subTest(shape=name):
                draft = _design(_load(name))
                report = verify_component(
                    draft.document, draft.document.components[0],
                    measurement_depth=8)
                self.assertEqual(_held_back(report), {}, name)


class PartsMadeAtRandom(unittest.TestCase):
    """Forty right answers made by `shape_generator` -- plates, discs, bent
    strips, open boxes, collars, L-brackets, counterbored plates, tubes,
    each brief phrased one of several ways -- and every one must pass. A
    random sample found what twenty written cases had not: a hole "in each
    corner" counted as one, "the upright" read as the base standing up,
    two neighbouring counterbores failed for touching."""

    SEEDS = range(40)

    def test_each_part(self) -> None:
        from forge_pipeline import verify_component
        from shape_generator import a_case

        for seed in self.SEEDS:
            case = a_case(seed)
            with self.subTest(seed=seed, brief=case["brief"]):
                draft = _design(case)
                report = verify_component(
                    draft.document, draft.document.components[0],
                    measurement_depth=8)
                self.assertEqual(_held_back(report), {})


class TheBendAndItsHoles(unittest.TestCase):
    """A place said of a hole is the hole's, not the bend's."""

    def test_holes_from_each_end_are_not_bends(self) -> None:
        from forge_roles.library import _the_bends_the_brief_describes

        bends = _the_bends_the_brief_describes(
            "A steel strip 3 mm thick, 30 mm wide and 80 mm long, bent 90 "
            "degrees in the middle, with a 6 mm hole 15 mm from each end.")
        self.assertEqual(len(bends), 1)
        self.assertTrue(bends[0].get("middle"))
        self.assertNotIn("from_end", bends[0])

    def test_the_hole_s_clause_before_the_bend(self) -> None:
        from forge_roles.library import _the_bends_the_brief_describes

        bends = _the_bends_the_brief_describes(
            "A strip with a 6 mm hole 15 mm from each end, and bent 90 "
            "degrees in the middle.")
        self.assertEqual([b.get("middle") for b in bends], [True])

    def test_the_holes_clause_carries_on_after_a_comma(self) -> None:
        from forge_roles.library import _the_bends_the_brief_describes

        for brief in (
                "A steel strip 150 by 25 mm, 3 mm thick, having two 6 mm "
                "holes, one 15 mm from each end and with a 60 degree bend "
                "halfway along.",
                "A stainless steel strip 80 mm long, 25 mm wide and 2 mm "
                "thick, with two 6 mm holes, one 10 mm from each end and "
                "folded 45 degrees at its centre."):
            with self.subTest(brief=brief):
                bends = _the_bends_the_brief_describes(brief)
                self.assertEqual(len(bends), 1)
                self.assertTrue(bends[0].get("middle"))

    def test_folds_at_each_end_are_still_two(self) -> None:
        from forge_roles.library import _the_bends_the_brief_describes

        bends = _the_bends_the_brief_describes(
            "A strip with two 90 degree folds, 10 mm from each end.")
        self.assertEqual([b["from_end"] for b in bends], [10.0, 10.0])
        bends = _the_bends_the_brief_describes(
            "A bracket 80 mm long, bent 90 degrees 30 mm from one end, with "
            "two 5 mm holes.")
        self.assertEqual([b["from_end"] for b in bends], [30.0])

    def test_the_middle_is_the_bend_s_not_the_hole_s(self) -> None:
        from forge_roles.library import _where_the_brief_places_its_openings

        plate = "A steel plate 100 mm long, 80 mm wide and 5 mm thick"
        cases = {
            "A steel strip 3 mm thick, 30 mm wide and 80 mm long, bent 90 "
            "degrees in the middle, with a 6 mm hole 15 mm from each end.": [],
            plate + " with a 16 mm cable hole in the centre.":
                ["opening_at:16:mid,mid"],
            plate + ". In the centre of the plate, a 16 mm hole.":
                ["opening_at:16:mid,mid"],
            plate + " with a 10 mm hole and a 90 degree bend in the middle.":
                [],
        }
        for brief, wanted in cases.items():
            with self.subTest(brief=brief):
                requirements: list = []
                _where_the_brief_places_its_openings(brief, requirements)
                self.assertEqual(
                    [r["measurement"] for r in requirements], wanted)


class TheBendIsClaimedOnce(unittest.TestCase):
    """"Bent 90 degrees": the record's own `bend_angle`, and the design's
    `angle` = 90 deg. Forge turned the second into a second `bend_angle`,
    one binding carrying two claims, and one of the two was left unmeasured
    -- a correct strip held back as NOT_TESTED."""

    def test_a_curve_measured_already_is_not_claimed_again(self) -> None:
        from forge_roles.library import _a_bent_part_measured

        requirements = [
            {"id": "REQ_ANGLE", "statement": "the bend", "measurement":
             "bend_angle", "comparison": "equals",
             "threshold": {"magnitude": 90, "unit": "deg"}},
            {"id": "REQ_P_ANGLE", "statement": "angle", "measurement":
             "parameter:angle", "comparison": "equals",
             "threshold": {"magnitude": 90, "unit": "deg"}},
        ]
        _a_bent_part_measured(
            "A steel strip 3 mm thick, 30 mm wide and 80 mm long, bent 90 "
            "degrees in the middle.", requirements)
        claims = [r["measurement"] for r in requirements]
        self.assertEqual(claims.count("bend_angle"), 1)
        self.assertIn("parameter:angle", claims)

    def test_the_design_s_angle_is_measured_when_nothing_else_is(self) -> None:
        from forge_roles.library import _a_bent_part_measured

        requirements = [
            {"id": "REQ_P_ANGLE", "statement": "angle", "measurement":
             "parameter:bend_angle", "comparison": "equals",
             "threshold": {"magnitude": 90, "unit": "deg"}}]
        _a_bent_part_measured(
            "A steel strip 3 mm thick, 30 mm wide and 80 mm long, bent 90 "
            "degrees in the middle.", requirements)
        self.assertEqual(
            [r["measurement"] for r in requirements].count("bend_angle"), 1)


class ABindingSpelledNearItsGrammar(unittest.TestCase):

    def test_each_is_read_as_it_means(self) -> None:
        from forge_roles.library import _repairable_binding

        for written, meant in {
            "standing_at:20x15:centre": "standing_at:20x15:mid,mid",
            "standing_at:20 by 15 mm:middle": "standing_at:20x15:mid,mid",
            "openings_of_size:6": "openings_of_size:6x6",
            "holes_of_diameter:6mm": "holes_of_diameter:6",
            "opening_at:6:centre,lo10": "opening_at:6:mid,lo10",
        }.items():
            with self.subTest(written=written):
                self.assertEqual(_repairable_binding(written)[0], meant)

    def test_a_good_binding_is_left_alone(self) -> None:
        from forge_roles.library import _repairable_binding

        for good in ("bounding_box_x", "parameter:width",
                     "standing_at:20x15:mid,mid", "openings_of_size:28x5"):
            self.assertEqual(_repairable_binding(good), ("", ""))


class ThinWallsOnABigPart(unittest.TestCase):
    """A wall thinner than the mesher's cell is still meshed."""

    def test_a_metre_box_with_3_mm_walls_has_its_surface(self) -> None:
        from forge_geom import extract_manifold_surface
        from forge_geom.sdf import BoxSDF, Difference

        outer = BoxSDF(centre=(0.0, 0.0, 200.0), half_extent=(500.0, 300.0, 200.0))
        inner = BoxSDF(centre=(0.0, 0.0, 203.0),
                       half_extent=(497.0, 297.0, 200.0))
        box = Difference(outer, (inner,))
        mesh = extract_manifold_surface(box, resolution=110)
        watertight, _ = mesh.is_watertight()
        self.assertTrue(watertight)
        volume = 1000 * 600 * 400 - 994 * 594 * 397
        self.assertAlmostEqual(abs(mesh.signed_volume()) / volume, 1.0,
                               delta=0.03)

    def test_an_ordinary_part_is_meshed_as_before(self) -> None:
        from forge_geom.mesh import _the_thinnest_the_grid_misses
        from forge_geom.sdf import BoxSDF

        box = BoxSDF(centre=(0.0, 0.0, 0.0), half_extent=(30.0, 20.0, 5.0))
        lo = np.array([-32.0, -22.0, -7.0])
        spacing = 0.6
        counts = np.ceil(np.array([64.0, 44.0, 14.0]) / spacing).astype(int) + 1
        axes = [lo[i] + spacing * np.arange(counts[i]) for i in range(3)]
        grid = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
        field = box(grid).reshape(counts)
        self.assertIsNone(_the_thinnest_the_grid_misses(box, lo, spacing, field))


class ASmallFeatureOnABigPart(unittest.TestCase):
    """A 4 mm hole in a 1000 by 600 mm plate: its diameter drives the part,
    though no sample of the evenly sampled surface lands on its wall."""

    def test_the_hole_s_diameter_drives_the_part(self) -> None:
        from forge_pipeline import verify_component

        size = {"length": 1000, "width": 600, "thickness": 3, "hole": 4}
        document = {"name": "big_plate", "components": [{
            "id": "part",
            "parameters": [{"id": k, "value": {"magnitude": v, "unit": "mm"}}
                           for k, v in size.items()],
            "features": [
                {"id": "plate", "kind": "box", "parameters": {
                    "size": {"vector": ["length", "width", "thickness"],
                             "unit": "mm"},
                    "centered": True,
                    "origin": {"vector": [0, 0, "thickness / 2"],
                               "unit": "mm"}}},
                {"id": "h1", "kind": "hole", "inputs": ["plate"],
                 "parameters": {
                     "diameter": {"expression": "hole", "unit": "mm"},
                     "position": {"vector": [200, 100, 0], "unit": "mm"},
                     "axis": [0, 0, 1]}}]}]}
        requirements = [
            {"id": "REQ_HOLE", "statement": "one 4 mm hole",
             "measurement": "holes_of_diameter:4", "comparison": "equals",
             "threshold": {"magnitude": 1, "unit": ""}}] + [
            {"id": f"REQ_P_{k.upper()}", "statement": k,
             "measurement": f"parameter:{k}", "comparison": "equals",
             "threshold": {"magnitude": v, "unit": "mm"}}
            for k, v in size.items()]
        case = {
            "brief": "A steel plate 1000 x 600 x 3 mm with one 4 mm hole. It "
                     "carries no load, so there is no load case.",
            "intent": {"summary": "plate", "part_kind": "plate",
                       "stated": [], "implied": [], "unstated": []},
            "requirements": {"risk_class": "low",
                             "requirements": requirements,
                             "assumptions": [], "unknowns": []},
            "answer": {"rationale": "", "document": document},
        }
        draft = _design(case)
        report = verify_component(draft.document, draft.document.components[0],
                                  measurement_depth=8)
        self.assertEqual(_held_back(report), {})


class SmallHolesOnABigPlateLaidFlat(unittest.TestCase):
    """Openings read laid flat on a grid sized to the part: a 3 mm hole on a
    1000 mm plate was read 4.2 by 2.8, a 5 mm one on a 2000 mm plate not at
    all. Each is now read again closely."""

    def _case(self, length: float, width: float, hole: float) -> dict:
        size = {"length": length, "width": width, "thickness": 3,
                "hole": hole}
        holes = [
            {"id": "h1", "kind": "hole", "inputs": ["plate"], "parameters": {
                "diameter": {"expression": "hole", "unit": "mm"},
                "position": {"vector": ["-length / 2 + 20",
                                        "-width / 2 + 20", 0], "unit": "mm"},
                "axis": [0, 0, 1]}},
            {"id": "h2", "kind": "hole", "inputs": ["h1"], "parameters": {
                "diameter": {"expression": "hole", "unit": "mm"},
                "position": {"vector": ["length / 2 - 20",
                                        "width / 2 - 20", 0], "unit": "mm"},
                "axis": [0, 0, 1]}}]
        document = {"name": "plate", "components": [{
            "id": "part",
            "parameters": [{"id": k, "value": {"magnitude": v, "unit": "mm"}}
                           for k, v in size.items()],
            "features": [{"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": ["length", "width", "thickness"],
                         "unit": "mm"},
                "centered": True,
                "origin": {"vector": [0, 0, "thickness / 2"],
                           "unit": "mm"}}}] + holes}]}
        requirements = [
            {"id": f"REQ_P_{k.upper()}", "statement": k,
             "measurement": f"parameter:{k}", "comparison": "equals",
             "threshold": {"magnitude": v, "unit": "mm"}}
            for k, v in size.items()] + [
            {"id": "REQ_SIZE", "statement": "two holes",
             "measurement": f"openings_of_size:{hole:g}x{hole:g}",
             "comparison": "equals", "threshold": {"magnitude": 2, "unit": ""}}]
        return {
            "brief": f"A steel plate {length:g} x {width:g} x 3 mm with two "
                     f"{hole:g} mm holes, each centred 20 mm in from two sides "
                     "at opposite corners. It carries no load, so there is no "
                     "load case.",
            "intent": {"summary": "plate", "part_kind": "plate",
                       "stated": [], "implied": [], "unstated": []},
            "requirements": {"risk_class": "low", "requirements": requirements,
                             "assumptions": [], "unknowns": []},
            "answer": {"rationale": "", "document": document},
        }

    def test_each_plate(self) -> None:
        from forge_pipeline import verify_component

        for length, width, hole in ((1000, 600, 3), (2000, 1500, 5),
                                    (120, 80, 3)):
            with self.subTest(plate=(length, width, hole)):
                draft = _design(self._case(length, width, hole))
                report = verify_component(
                    draft.document, draft.document.components[0],
                    measurement_depth=8)
                self.assertEqual(_held_back(report), {})


class ASmallBossOnABigPlate(unittest.TestCase):
    """A 10 mm boss on a 2000 mm plate is three grid steps across: read
    again closely, it is found where it stands and the size it is."""

    def test_the_boss_is_found(self) -> None:
        from forge_pipeline import verify_component

        size = {"length": 2000, "width": 1500, "thickness": 5, "boss": 10,
                "boss_height": 8}
        document = {"name": "p", "components": [{
            "id": "part",
            "parameters": [{"id": k, "value": {"magnitude": v, "unit": "mm"}}
                           for k, v in size.items()],
            "features": [
                {"id": "plate", "kind": "box", "parameters": {
                    "size": {"vector": ["length", "width", "thickness"],
                             "unit": "mm"},
                    "centered": True,
                    "origin": {"vector": [0, 0, "thickness / 2"],
                               "unit": "mm"}}},
                {"id": "post", "kind": "cylinder", "parameters": {
                    "diameter": {"expression": "boss", "unit": "mm"},
                    "height": {"expression": "boss_height", "unit": "mm"},
                    "origin": {"vector": [0, 0, "thickness"], "unit": "mm"}}},
                {"id": "body", "kind": "union", "inputs": ["plate", "post"]}]}]}
        requirements = [
            {"id": f"REQ_P_{k.upper()}", "statement": k,
             "measurement": f"parameter:{k}", "comparison": "equals",
             "threshold": {"magnitude": v, "unit": "mm"}}
            for k, v in size.items()] + [
            {"id": "REQ_BOSS", "statement": "boss",
             "measurement": "standing_at:10x8:mid,mid", "comparison": "at_most",
             "threshold": {"magnitude": 0.5, "unit": "mm"}}]
        case = {
            "brief": "A plate 2000 x 1500 x 5 mm with a 10 mm boss standing "
                     "8 mm proud in the centre. It carries no load, so there "
                     "is no load case.",
            "intent": {"summary": "plate", "part_kind": "plate",
                       "stated": [], "implied": [], "unstated": []},
            "requirements": {"risk_class": "low", "requirements": requirements,
                             "assumptions": [], "unknowns": []},
            "answer": {"rationale": "", "document": document},
        }
        draft = _design(case)
        report = verify_component(draft.document, draft.document.components[0],
                                  measurement_depth=8)
        self.assertEqual(_held_back(report), {})


class ABriefInInches(unittest.TestCase):
    """"Four 1/4 inch holes, 1/2 inch in from the edges": "1/2 inch" was
    read as 2 inches, a figure the user never wrote, and the record that
    carried the brief's every figure was refused for not carrying it."""

    def test_fractions_are_the_decimals_they_are(self) -> None:
        from forge_roles.library import _figures_written_as_decimals as said

        self.assertEqual(said("four 1/4 inch holes, 1/2 inch in"),
                         "four 0.25 inch holes, 0.5 inch in")
        self.assertEqual(said("a 1 1/2 inch pipe, 2\u00bc in long"),
                         "a 1.5 inch pipe, 2.25 in long")
        self.assertEqual(said("a 30/40 mm step"), "a 30/40 mm step")

    def test_an_inch_plate_passes(self) -> None:
        from forge_pipeline import verify_component

        corners = [("-", "-"), ("", "-"), ("", ""), ("-", "")]
        document = {"name": "p", "components": [{
            "id": "part",
            "parameters": [
                {"id": k, "value": {"magnitude": v, "unit": "in"}}
                for k, v in (("length", 4), ("width", 3), ("thickness", 0.25),
                             ("hole", 0.25), ("inset", 0.5))],
            "features": [{"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": ["length", "width", "thickness"],
                         "unit": "mm"},
                "centered": True,
                "origin": {"vector": [0, 0, "thickness / 2"], "unit": "mm"}}}]
            + [{"id": f"h{i}", "kind": "hole",
                "inputs": ["plate" if i == 1 else f"h{i - 1}"],
                "parameters": {
                    "diameter": {"expression": "hole", "unit": "mm"},
                    "position": {"vector": [f"{sx}(length / 2 - inset)",
                                            f"{sy}(width / 2 - inset)", 0],
                                 "unit": "mm"},
                    "axis": [0, 0, 1]}}
               for i, (sx, sy) in enumerate(corners, 1)]}]}
        requirements = [
            {"id": "REQ_L", "statement": "4 in long",
             "measurement": "bounding_box_x", "comparison": "equals",
             "threshold": {"magnitude": 4, "unit": "in"}},
            {"id": "REQ_W", "statement": "3 in wide",
             "measurement": "parameter:width", "comparison": "equals",
             "threshold": {"magnitude": 3, "unit": "in"}},
            {"id": "REQ_T", "statement": "1/4 in thick",
             "measurement": "parameter:thickness", "comparison": "equals",
             "threshold": {"magnitude": 0.25, "unit": "in"}},
            {"id": "REQ_H", "statement": "four 1/4 in holes",
             "measurement": "holes_of_diameter:6.35", "comparison": "equals",
             "threshold": {"magnitude": 4, "unit": ""}},
            {"id": "REQ_I", "statement": "1/2 in in from the edges",
             "measurement": "parameter:inset", "comparison": "equals",
             "threshold": {"magnitude": 0.5, "unit": "in"}}]
        case = {
            "brief": "A steel plate 4 x 3 x 1/4 inch with four 1/4 inch "
                     "holes, one in each corner, 1/2 inch in from the edges. "
                     "It carries no load, so there is no load case.",
            "intent": {"summary": "plate", "part_kind": "plate",
                       "stated": [], "implied": [], "unstated": []},
            "requirements": {"risk_class": "low", "requirements": requirements,
                             "assumptions": [], "unknowns": []},
            "answer": {"rationale": "", "document": document},
        }
        draft = _design(case)
        report = verify_component(draft.document, draft.document.components[0],
                                  measurement_depth=7)
        self.assertEqual(_held_back(report), {})


class ATubeIsMeasuredExactly(unittest.TestCase):
    """A coil's distance, worked out nearest group first, is the exact
    distance to its wire."""

    def test_against_every_run(self) -> None:
        from forge_geom.sdf import TubeSDF

        rng = np.random.default_rng(1)
        t = np.linspace(0, 2 * np.pi * 6, 300)
        path = np.stack([10 * np.cos(t), 10 * np.sin(t), t * 0.8], 1)
        tube = TubeSDF(tuple(map(tuple, path)), radius=1.2)
        points = rng.uniform(path.min(0) - 3, path.max(0) + 3, (5000, 3))
        starts, ends = path[:-1], path[1:]
        e = ends - starts
        lengths = np.linalg.norm(e, axis=1)
        tangents = e / lengths[:, None]
        w = points[:, None, :] - starts[None]
        h = np.einsum("pse,se->ps", w, tangents)
        r = np.sqrt(np.maximum((w * w).sum(-1) - h * h, 0))
        dx = r - 1.2
        dy = np.abs(h - lengths / 2) - lengths / 2
        d = np.minimum(np.maximum(dx, dy), 0) + np.sqrt(
            np.maximum(dx, 0) ** 2 + np.maximum(dy, 0) ** 2)
        ball = np.sqrt(((points[:, None, :] - starts[1:][None]) ** 2).sum(-1))
        want = np.minimum(d.min(1), ball.min(1) - 1.2)
        self.assertLess(float(np.abs(tube(points) - want).max()), 1e-9)


if __name__ == "__main__":
    unittest.main()
