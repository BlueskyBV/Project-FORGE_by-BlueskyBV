"""Six runs on Claude Sonnet 5, 14 October 2026: an L-bracket, a lower-leg
shell, a stepper plate, a curved arm plate, a dome and a shaft collar.

Five reported PASS and one was held for approval. Three of the five were
not what they looked like, and the cause was Forge's own:

- the L-bracket passed turned a quarter-turn wrong: a layout repair took
  the plate's longer side for the leg's length, where the brief gives the
  base as 60 wide and 50 long, and the analyst then made the rest agree;
- the dome passed sealed: shelled after it was halved, every face kept, a
  hollow ball-half with no way in -- and the record held no claim that it
  was hollow at all, because the wall assumption carried its figure in its
  statement only;
- the stepper plate spent two analyst rounds, one on slots Forge itself had
  recut from an envelope swollen by a blend, one on a chamfer trim that
  clipped the boss;
- the curved plate passed everything and was held for a material nobody
  measures anything by.

The leg shell's two rounds were the model's own (a cutter extruded the
wrong way, a pivot formula whose arithmetic it got wrong), and the collar
was right. Each is tested here as the run met it.
"""

from __future__ import annotations

import json
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


def _inside(report, points) -> list[bool]:
    return [bool(v < 0.0) for v in
            np.asarray(report.part.solid(np.array(points, dtype=float)))]


def _tight_box(report):
    from forge_pipeline.verify import measure_mass_properties, refine_extents

    properties = refine_extents(report.part.solid, measure_mass_properties(
        report.part.solid, max_depth=6))
    lo = [float(q.magnitude.lo) for q in properties.bounding_box_lo]
    hi = [float(q.magnitude.hi) for q in properties.bounding_box_hi]
    return lo, hi


class TheBracketStandsOnTheEndTheBriefNames(unittest.TestCase):
    """"60 mm wide ... the base leg is 50 mm long ... the upright stands on
    the back end of the base". The upright belongs across the 60, at one
    end of the 50."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.draft = _design(_load("bracket_leg_turned_on_its_long_side_claude"))
        cls.report = _verify(cls.draft)

    def test_it_passes(self) -> None:
        self.assertEqual(self.report.overall_status.value, "PASS",
                         _not_passing(self.report))

    def test_the_base_is_60_across_and_50_long(self) -> None:
        lo, hi = _tight_box(self.report)
        across, along = sorted((hi[0] - lo[0], hi[1] - lo[1]), reverse=True)
        self.assertAlmostEqual(across, 60.0, delta=0.1)
        self.assertAlmostEqual(along, 50.0, delta=0.1)
        self.assertAlmostEqual(hi[2] - lo[2], 40.0, delta=0.1)

    def test_the_upright_runs_across_the_width_at_one_end(self) -> None:
        lo, hi = _tight_box(self.report)
        wide = 0 if hi[0] - lo[0] > hi[1] - lo[1] else 1
        long_ = 1 - wide
        mid = (lo[2] + hi[2]) / 2
        ends = []
        for end in (lo[long_] + 1.0, hi[long_] - 1.0):
            points = []
            for t in np.linspace(lo[wide] + 3, hi[wide] - 3, 9):
                p = [0.0, 0.0, mid]
                p[wide], p[long_] = t, end
                # clear of the upright's two holes
                if abs(p[2] - (lo[2] + 25)) < 4:
                    p[2] += 8
                points.append(p)
            ends.append(sum(_inside(self.report, points)))
        self.assertEqual(sorted(ends), [0, 9],
                         "the upright is a wall across the width at exactly "
                         f"one end of the length: {ends}")


class TheStepperPlateSettlesWithoutAnAnalyst(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.draft = _design(_load("stepper_slots_recut_and_boss_trimmed_claude"))
        cls.report = _verify(cls.draft)

    def test_it_passes(self) -> None:
        self.assertEqual(self.report.overall_status.value, "PASS",
                         _not_passing(self.report))

    def test_the_slots_it_drew_are_not_cut_again(self) -> None:
        features = self.draft.document.components[0].features
        kinds = [f.kind for f in features]
        self.assertEqual(kinds.count("pattern_linear"), 1)
        slot_sized = [f for f in features if f.kind == "box"]
        self.assertEqual(len(slot_sized), 1, [f.identifier for f in features])
        # and the part has the two slots, 20 x 5, 14 mm from each end
        lo, hi = _tight_box(self.report)
        centres = [[lo[0] + 14.0, 0.0, 0.0], [hi[0] - 14.0, 0.0, 0.0],
                   [lo[0] + 14.0 + 9.0, 0.0, 0.0], [lo[0] + 14.0, 2.0, 0.0]]
        self.assertEqual(_inside(self.report, centres),
                         [False, False, False, False])

    def test_the_boss_stands_whole_on_the_chamfered_plate(self) -> None:
        lo, hi = _tight_box(self.report)
        self.assertAlmostEqual(hi[2] - lo[2], 14.0, delta=0.1)
        top = hi[2]
        # The boss ring, between the 22.5 mm bore and its 36 mm side, right
        # up to its top; the plate's own top edge, chamfered away.
        ring = [[r * np.cos(a), r * np.sin(a), top - 0.3]
                for r in (13.0, 16.5) for a in np.linspace(0, 2 * np.pi, 12,
                                                           endpoint=False)]
        self.assertTrue(all(_inside(self.report, ring)))
        plate_top = top - 6.0
        # "a 1 mm chamfer round its top edge": the corner of the plate's
        # top edge is gone, on the ends and on the sides, and just inside
        # it the plate is solid.
        self.assertEqual(_inside(self.report, [
            [hi[0] - 0.2, 0.0, plate_top - 0.2],
            [lo[0] + 0.2, 0.0, plate_top - 0.2],
            [0.0, hi[1] - 0.2, plate_top - 0.2],
            [hi[0] - 2.0, 0.0, plate_top - 0.5],
            [hi[0] - 0.2, 0.0, plate_top - 1.5]]),
            [False, False, False, True, True])

    def test_the_trim_is_said(self) -> None:
        self.assertTrue(any("the trim cut away what had been joined" in n
                            for n in self.draft.notes), self.draft.notes)


class TheDomeIsOpenAndHollow(unittest.TestCase):
    """"exactly half of a 70 mm sphere, sitting flat side to the right side,
    hollow on the inside"."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = _load("dome_shelled_after_its_cut_claude")
        cls.draft = _design(cls.case)
        cls.report = _verify(cls.draft)

    def test_the_record_claims_the_hollow(self) -> None:
        bindings = " ".join(
            str(r.get("binding", r)) if isinstance(r, dict) else str(r)
            for r in _requirements(self.case).requirements)
        self.assertIn("minimum_wall_thickness", bindings)
        self.assertIn("opening_depth", bindings)

    def test_it_passes(self) -> None:
        self.assertEqual(self.report.overall_status.value, "PASS",
                         _not_passing(self.report))

    def test_it_is_half_a_70_mm_ball_flat_to_the_right(self) -> None:
        lo, hi = _tight_box(self.report)
        self.assertAlmostEqual(hi[0] - lo[0], 35.0, delta=0.1)
        self.assertAlmostEqual(hi[1] - lo[1], 70.0, delta=0.1)
        self.assertAlmostEqual(hi[2] - lo[2], 70.0, delta=0.1)

    def test_its_inside_is_empty_and_reached_from_the_flat_side(self) -> None:
        lo, hi = _tight_box(self.report)
        flat = hi[0]
        centre = [flat, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2]
        inward = [[flat - d, centre[1], centre[2]] for d in (0.2, 5, 15, 30)]
        self.assertEqual(_inside(self.report, inward), [False] * 4,
                         "the cavity runs out through the flat face")
        wall = [[flat - 34.0, centre[1], centre[2]],
                [flat - 0.5, centre[1] + 34.0, centre[2]]]
        self.assertEqual(_inside(self.report, wall), [True, True])

    def test_the_seal_is_said(self) -> None:
        self.assertTrue(any("a shell keeps every face" in n
                            for n in self.draft.notes), self.draft.notes)


class ACurvedPlateIsNotHeldForAMaterialNothingRestsOn(unittest.TestCase):

    def test_the_material_is_a_guess_kept_and_not_a_hold(self) -> None:
        case = _load("curved_plate_held_for_a_material_claude")
        record = _requirements(case)
        material = [a for a in record.assumptions
                    if a.get("id") == "ASM_MATERIAL"]
        self.assertEqual(len(material), 1)
        self.assertEqual(material[0]["risk"], "moderate")
        self.assertTrue(material[0]["reversible"])
        self.assertFalse(material[0]["approved"])
        draft = _design(case)
        self.assertEqual(draft.document.unapproved_blocking_assumptions(), ())

    def test_a_material_something_is_measured_by_still_holds(self) -> None:
        case = _load("curved_plate_held_for_a_material_claude")
        raw = json.loads(json.dumps(case["requirements"]))
        raw["requirements"].append({
            "id": "REQ_MASS", "statement": "The plate weighs under 0.2 kg.",
            "measurement": "mass", "comparison": "at_most",
            "threshold": {"magnitude": 0.2, "unit": "kg"},
            "rationale": "r", "type": "physical",
            "verification": "measurement", "strength": "hard",
            "source": "user", "state": "accepted"})
        for assumption in raw.get("assumptions", []):
            if assumption.get("id") == "ASM_MATERIAL":
                assumption["risk"] = "high"
        from forge_roles import RequirementsEngineer

        record = RequirementsEngineer().parse(raw, brief=case["brief"])
        material = [a for a in record.assumptions
                    if a.get("id") == "ASM_MATERIAL"]
        self.assertEqual(material[0]["risk"], "high")

    def test_it_passes(self) -> None:
        report = _verify(_design(_load("curved_plate_held_for_a_material_claude")))
        self.assertEqual(report.overall_status.value, "PASS",
                         _not_passing(report))


class TheSideRailIsTheRailTheBriefDescribes(unittest.TestCase):
    """The brief: "180 mm long, 30 mm wide, and 8 mm thick, with rounded edges ...
    two 8.2 mm diameter mounting holes spaced 60 mm apart ... one 8.2 mm
    diameter pivot hole centered 15 mm from the lower end ... a circular
    boss 30 mm in diameter and 12 mm total thickness ... rounded triangular
    cutouts while maintaining continuous material around every hole."
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = _load("side_rail_holes_across_its_width_claude")
        cls.draft = _design(cls.case)
        cls.report = _verify(cls.draft)

    def test_every_check_passes(self) -> None:
        self.assertEqual(_not_passing(self.report), {})

    def test_the_mounting_holes_run_along_the_rail(self) -> None:
        holes = {h["feature"]: h for h in
                 self.report.measurements["part"]["holes"]}
        a, b = (holes["mounting_hole_1"]["centre_mm"],
                holes["mounting_hole_2"]["centre_mm"])
        self.assertTrue(holes["mounting_hole_1"]["present"])
        self.assertTrue(holes["mounting_hole_2"]["present"])
        self.assertAlmostEqual(abs(a[0] - b[0]), 60.0, delta=0.05)
        self.assertAlmostEqual(a[1], 0.0, delta=0.05)
        self.assertAlmostEqual(b[1], 0.0, delta=0.05)

    def test_its_ends_are_round_in_plan(self) -> None:
        lo, hi = _tight_box(self.report)
        # a square corner would be material at (end - 1, side - 1)
        self.assertEqual(_inside(self.report, [
            [hi[0] - 1.0, hi[1] - 1.0, 0.0], [lo[0] + 1.0, lo[1] + 1.0, 0.0],
            [hi[0] - 1.0, 0.0, 0.0]]), [False, False, True])

    def test_the_cutouts_go_right_through(self) -> None:
        component = self.draft.document.components[0]
        cut = [f for f in component.features if f.kind == "profile_polygon"]
        self.assertEqual(len(cut), 2)
        for profile in cut:
            self.assertIn("corner_radius", profile.parameters)
        lo, hi = _tight_box(self.report)
        taken = [h["centre_mm"][0] for h in
                 self.report.measurements["part"]["holes"]]
        # Straight down the rail's middle line, away from the holes: the
        # columns with no material in them at all are the two cutouts.
        through = []
        for x in np.linspace(lo[0] + 20, hi[0] - 20, 400):
            column = [[x, 0.0, z] for z in np.linspace(lo[2] + 0.3,
                                                         lo[2] + 7.7, 9)]
            if not any(_inside(self.report, column)) and all(
                    abs(x - t) > 6 for t in taken):
                through.append(x)
        runs = 1 + sum(1 for p, q in zip(through, through[1:]) if q - p > 1)
        self.assertGreaterEqual(len(through), 2)
        self.assertEqual(runs, 2, through)

    def test_its_second_design_settles_the_same_way(self) -> None:
        """Told what failed, the designer moved the pair to the rail's
        other end and kept it across the 30 mm: the same fault, settled the
        same way."""
        second = dict(self.case)
        second["answer"] = self.case["second_answer"]
        report = _verify(_design(second))
        self.assertEqual(_not_passing(report), {})

    def test_the_analyst_s_placeholder_is_sent_back(self) -> None:
        from forge_roles import FailureAnalyst
        from forge_roles.base import RoleOutputError

        answer = dict(self.case["analyst_answer"])
        structured = {"diagnosis": answer["diagnosis"],
                      "strategy": answer["strategy"],
                      "patches": answer["patches"], "abandon": False}
        with self.assertRaises(RoleOutputError) as caught:
            FailureAnalyst().parse(structured, failure={"kind": "gate"},
                                   document_slice={})
        self.assertIn("placeholder", " ".join(caught.exception.problems))
        self.assertIsNone(FailureAnalyst().salvage(structured, ["p"]))


def _mm(value):
    return {"magnitude": value, "unit": "mm"}


def _plate(length=180.0, width=30.0, thick=8.0, extra=None, holes=None):
    """A flat plate centred on the origin, and whatever is cut from it."""
    features = [{"id": "plate", "kind": "box", "parameters": {
        "size": {"vector": [length, width, thick], "unit": "mm"},
        "centered": True}}]
    last = "plate"
    for feature in extra or []:
        features.append(feature)
        if feature.get("kind") in ("subtract", "union"):
            last = feature["id"]
    for n, (x, y, d) in enumerate(holes or []):
        features.append({"id": f"hole_{n + 1}", "kind": "hole",
                         "inputs": [last], "parameters": {
                             "diameter": _mm(d),
                             "position": {"vector": [x, y, 0], "unit": "mm"},
                             "axis": [0, 0, 1]}})
        last = f"hole_{n + 1}"
    return {"id": "part", "parameters": [], "features": features}


def _solid(component):
    from forge_roles.library import _the_flat_body_built

    return _the_flat_body_built(component, None, solid_wanted=True)


class TheRepairsHoldOnOtherParts(unittest.TestCase):
    """Each repair the six runs needed, on parts that are not those runs:
    what it must change, and what it must leave alone."""

    def test_a_pair_across_a_narrow_bar_is_turned_along_it(self) -> None:
        from forge_roles.library import \
            _a_pair_spaced_across_a_side_too_short_for_it as turn

        bar = _plate(120, 20, 6, holes=[(10, 25, 5), (10, -25, 5)])
        notes = turn(bar, None)
        self.assertTrue(notes)
        solid = _solid(bar)
        # both holes open, 50 apart along x, on the bar's middle line
        self.assertEqual([bool(v > 0) for v in np.asarray(solid(np.array(
            [[-15, 0, 0], [35, 0, 0]], dtype=float)))], [True, True])

    def test_a_pair_that_fits_the_way_it_was_drawn_is_left(self) -> None:
        from forge_roles.library import \
            _a_pair_spaced_across_a_side_too_short_for_it as turn

        plate = _plate(120, 80, 6, holes=[(0, 25, 5), (0, -25, 5)])
        before = json.dumps(plate)
        self.assertEqual(turn(plate, None), [])
        self.assertEqual(json.dumps(plate), before)

    def test_a_pair_through_lugs_past_the_plate_is_left(self) -> None:
        from forge_roles.library import \
            _a_pair_spaced_across_a_side_too_short_for_it as turn

        lugs = [{"id": "lug_a", "kind": "cylinder", "parameters": {
                     "diameter": _mm(14), "height": _mm(6),
                     "origin": {"vector": [0, 25, -3], "unit": "mm"}}},
                {"id": "lug_b", "kind": "cylinder", "parameters": {
                     "diameter": _mm(14), "height": _mm(6),
                     "origin": {"vector": [0, -25, -3], "unit": "mm"}}},
                {"id": "body", "kind": "union",
                 "inputs": ["plate", "lug_a", "lug_b"]}]
        part = _plate(120, 20, 6, extra=lugs, holes=[(0, 25, 5), (0, -25, 5)])
        before = json.dumps(part)
        self.assertEqual(turn(part, None), [])
        self.assertEqual(json.dumps(part), before)

    def _pocketed(self, offset=3.0, distance=6.0):
        cut = [{"id": "sketch_plane", "kind": "datum_plane", "parameters": {
                    "base": "XY", "offset": _mm(offset)}},
               {"id": "window", "kind": "profile_polygon",
                "inputs": ["sketch_plane"], "parameters": {
                    "circumscribed_diameter": _mm(20), "sides": 6,
                    "center_u": _mm(0), "center_v": _mm(0)}},
               {"id": "window_cut", "kind": "extrude", "inputs": ["window"],
                "parameters": {"distance": _mm(distance),
                               "mode": "symmetric",
                               "end_radius": _mm(2)}},
               {"id": "plate_cut", "kind": "subtract",
                "inputs": ["plate", "window_cut"]}]
        return _plate(100, 60, 6, extra=cut)

    def test_a_cutout_cut_half_way_is_cut_through(self) -> None:
        from forge_roles.library import (
            _a_cutout_cut_part_way_through_a_plate as through,
            _rounded_polygons_the_brief_names as rounded)

        part = self._pocketed()
        brief = "A plate 100 x 60 x 6 mm with a rounded hexagonal cutout."
        self.assertTrue(rounded(part, brief))
        self.assertTrue(through(part, None, brief))
        solid = _solid(part)
        column = [[0, 0, z] for z in np.linspace(-2.9, 2.9, 7)]
        self.assertTrue(all(np.asarray(solid(np.array(column))) > 0))
        # the hexagon's corners rounded, 2 mm: just inside where a sharp
        # corner's tip would be, there is plate
        tip = [[9.85 * np.cos(np.pi / 6), 9.85 * np.sin(np.pi / 6), 0.0]]
        self.assertLess(float(np.asarray(solid(np.array(tip)))[0]), 0.0)

    def test_a_pocket_the_brief_asks_for_is_left(self) -> None:
        from forge_roles.library import \
            _a_cutout_cut_part_way_through_a_plate as through

        part = self._pocketed()
        before = json.dumps(part)
        brief = ("A plate 100 x 60 x 6 mm with a hexagonal pocket 3 mm deep, "
                 "and two cutouts.")
        self.assertEqual(through(part, None, brief), [])
        self.assertEqual(json.dumps(part), before)

    def test_a_cut_already_through_is_left(self) -> None:
        from forge_roles.library import \
            _a_cutout_cut_part_way_through_a_plate as through

        part = self._pocketed(offset=0.0, distance=10.0)
        before = json.dumps(part)
        self.assertEqual(through(part, None, "a plate with a cutout"), [])
        self.assertEqual(json.dumps(part), before)

    def test_a_rounding_half_the_width_on_end_edges_rounds_the_plan(self) -> None:
        from forge_roles.library import _a_corner_rounder_than_its_side

        link = _plate(60, 12, 6)
        link["features"][0]["parameters"].update(
            {"edge_radius": _mm(6), "edges": "along_x"})
        notes = _a_corner_rounder_than_its_side(link)
        self.assertTrue(notes)
        self.assertEqual(link["features"][0]["parameters"]["edges"],
                         "vertical")

    def test_a_rounding_that_fits_is_left(self) -> None:
        from forge_roles.library import _a_corner_rounder_than_its_side

        link = _plate(60, 12, 6)
        link["features"][0]["parameters"].update(
            {"edge_radius": _mm(2), "edges": "along_x"})
        self.assertEqual(_a_corner_rounder_than_its_side(link), [])

    def test_a_rounded_polygon_keeps_its_flats_and_loses_its_corners(self) -> None:
        import math

        from forge_geom.sdf import PolygonProfile

        sharp = PolygonProfile(centre=(0, 0), circumradius=10, sides=6)
        round_ = PolygonProfile(centre=(0, 0), circumradius=10, sides=6,
                                corner_radius=3)
        flat = 10 * math.cos(math.pi / 6)
        u, v = np.array([flat, 0.0]), np.array([0.0, 0.0])
        self.assertAlmostEqual(float(round_.distance(u[:1], v[:1])[0]), 0.0,
                               places=9)
        corner = (10 * math.cos(math.pi / 6), 10 * math.sin(math.pi / 6))
        self.assertAlmostEqual(float(sharp.distance(
            np.array([corner[0]]), np.array([corner[1]]))[0]), 0.0, places=9)
        self.assertGreater(float(round_.distance(
            np.array([corner[0]]), np.array([corner[1]]))[0]), 0.4)
        with self.assertRaises(Exception):
            PolygonProfile(centre=(0, 0), circumradius=10, sides=3,
                           corner_radius=6)


class TheAnalystIsNotAskedTwiceForWhatItWrote(unittest.TestCase):

    def _proposal(self, structured: dict, kind: str = "gate"):
        from forge_roles import FailureAnalyst

        return FailureAnalyst().parse(
            structured, failure={"kind": kind}, document_slice={})

    def test_an_abandon_with_its_reason_in_the_diagnosis(self) -> None:
        proposal = self._proposal(
            {"diagnosis": "The part matches the brief in every respect.",
             "strategy": "", "patches": [], "abandon": True}, kind="last_look")
        self.assertTrue(proposal.abandon)
        self.assertIn("matches the brief", proposal.abandon_reason)

    def test_patches_written_inside_the_strategy(self) -> None:
        from forge_roles.library import _patches_written_in_the_text

        structured = {
            "diagnosis": "the hole is 5 mm off",
            "strategy": 'Move it. {"patches": [{"op": "replace", "pointer": '
                        '"/components/0/parameters/hole_x/value", "value": '
                        '{"magnitude": 20, "unit": "mm"}, "reason": '
                        '"hole_x to 20"}]}',
            "patches": [], "abandon": False}
        found = _patches_written_in_the_text(structured)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["pointer"],
                         "/components/0/parameters/hole_x/value")

    def test_it_is_shown_what_its_expressions_come_to(self) -> None:
        from forge_roles import FailureAnalyst

        component = {"id": "leg", "parameters": [
            {"id": "tab_overhang", "value": {"magnitude": 50, "unit": "mm"}},
            {"id": "tab_embed_depth", "value": {"magnitude": 25, "unit": "mm"}},
            {"id": "z_bottom", "expression": "0 * mm - tab_overhang",
             "unit": "mm"},
            {"id": "z_top", "expression": "tab_embed_depth", "unit": "mm"},
            {"id": "pivot_z", "expression": "(z_bottom + z_top) / 2",
             "unit": "mm"}], "features": []}
        messages = FailureAnalyst().build_messages(
            failure={"kind": "gate"},
            document_slice={"/components/0": component})
        text = json.dumps([str(getattr(m, "content", m)) for m in messages])
        self.assertIn("pivot_z = (z_bottom + z_top) / 2 = -12.5 mm", text)


if __name__ == "__main__":
    unittest.main()
