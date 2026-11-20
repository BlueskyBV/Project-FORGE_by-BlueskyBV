"""V2 stage 1: V1 corpus briefs, drafted as a good spec writer would, check clean.

Each draft here is written the way the spec writer's guide says, from a V1
corpus brief (validation/SUITE.md), and must pass every check with nothing
left for the person but its assumptions. Several of these briefs once made
false passes (a review found R12, C05 and C10 among them): the holes of R12
were placed 180 degrees apart, C05's ball touched its rod at a point, C10's
divider stood on the tray's open top. They are the regression tests for
those fixes, and for what the schema can say: angles apart, inside floors,
hollows sealed or open, balls centred on a face.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import SpecReport, check_draft
from forge_spec.render import render

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, choose, cite, count, draft, made_of, mm, said

LOAD = "It carries no load, so there is no load case."


def derived(value: float, formula: str, words: list[int]) -> dict[str, Any]:
    return {"value": value, "unit": "mm", "from": {"formula": formula, "words": words}}


def problems(report: SpecReport) -> list[tuple[str, str, str]]:
    return [(p.kind, p.at, p.message) for p in report.problems]


class TheCorpusDraftsCheckClean(unittest.TestCase):
    def test_r12_two_set_screws_90_degrees_apart(self) -> None:
        b = number_words("A machined aluminium shaft collar. The outer diameter is 25 mm and it is 15 mm long. "
                         "A 12 mm bore runs all the way through on the axis. Two 4 mm set screw holes pass "
                         "through the wall from the outside into the bore, 90 degrees apart, both halfway "
                         "along the length. It carries no load - it is a locating collar, so there is no load case.")  # fmt: skip
        d = draft("collar", [
            {"id": "collar", "kind": "tube", "words": cite(b, "shaft collar"),
             "outer_diameter": mm(b, 25, "25 mm"), "inner_diameter": mm(b, 12, "12 mm"),
             "length": mm(b, 15, "15 mm"), "axis": choose("z", assumed("a collar is drawn standing up"))},
            {"id": "set_screws", "kind": "hole", "words": cite(b, "set screw holes"),
             "on": {"item": "collar", "face": "side"}, "diameter": mm(b, 4, "4 mm"),
             "depth": {"through_next": True, "from": said(b, "through the wall from the outside into the bore")},
             "count": count(b, 2, "Two"),
             "place": {"z": {"centred": said(b, "halfway along the length")},
                       "angle": assumed("the first screw's angle doesn't matter", 0, "deg"),
                       "pattern": {"arc": {"count": count(b, 2, "both"),
                                           "step": mm(b, 90, "90 degrees", unit="deg")}}}},
        ], material=made_of(b, "machined aluminium"),
           silent=[{"sentence": 4, "reason": "it says there is no load case"}])  # fmt: skip
        report = check_draft(b, d)
        self.assertEqual(problems(report), [])
        assert report.layout is not None
        angles = sorted(round(math.degrees(math.atan2(h.origin[1], h.origin[0]))) for h in
                        report.layout.instances["set_screws"])  # fmt: skip
        self.assertEqual(angles, [0, 90])
        self.assertIn("2 x hole set_screws", render(report, b).text())

    def test_c05_a_ball_centred_on_a_rod_s_end(self) -> None:
        b = number_words("A PLA pin: a 6 mm rod 50 mm long standing upright, with a 12 mm ball centred on its "
                         "top end. " + LOAD)  # fmt: skip
        d = draft("pin", [
            {"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "diameter": mm(b, 6, "6 mm"),
             "length": mm(b, 50, "50 mm"), "axis": choose("z", said(b, "standing upright"))},
            {"id": "ball", "kind": "sphere", "words": cite(b, "ball"), "on": {"item": "rod", "face": "+end"},
             "diameter": mm(b, 12, "12 mm"), "portion": choose("whole", said(b, "ball")),
             "place": {"x": {"centred": said(b, "centred on its top end")},
                       "y": {"centred": said(b, "centred on its top end")}}},
        ], material=made_of(b, "PLA"),
           silent=[{"sentence": 1, "reason": "it says there is no load case"}])  # fmt: skip
        report = check_draft(b, d)
        self.assertEqual(problems(report), [])
        assert report.layout is not None
        self.assertEqual(report.layout.extent(), ((-6.0, -6.0, 0.0), (6.0, 6.0, 56.0)))

    def test_c10_a_tray_with_a_divider_on_its_floor(self) -> None:
        b = number_words("A PLA tray 100 mm long, 60 mm wide and 25 mm tall on the outside, with 2 mm walls and "
                         "a 2 mm floor, open at the top, and one 2 mm thick divider wall across the middle "
                         "splitting it into two equal compartments. " + LOAD)  # fmt: skip
        d = draft("tray", [
            {"id": "tray", "kind": "block", "words": cite(b, "tray"), "length": mm(b, 100, "100 mm"),
             "width": mm(b, 60, "60 mm"), "height": mm(b, 25, "25 mm")},
            {"id": "hollow", "kind": "shell", "words": cite(b, "2 mm walls"), "of": "tray",
             "thickness": mm(b, 2, "2 mm walls"), "floor": mm(b, 2, "2 mm floor"),
             "open": {"faces": ["+z"], "from": said(b, "open at the top")}},
            {"id": "divider", "kind": "post", "words": cite(b, "divider wall"),
             "on": {"item": "tray", "face": "inner -z"}, "count": count(b, 1, "one"),
             "length": mm(b, 2, "2 mm thick"),
             "width": derived(56, "60 mm - 2 * 2 mm", cite(b, "60 mm") + cite(b, "2 mm walls")),
             "height": derived(23, "25 mm - 2 mm", cite(b, "25 mm") + cite(b, "2 mm floor")),
             "place": {"x": {"centred": said(b, "across the middle")},
                       "y": {"centred": assumed("it spans the tray from wall to wall")}}},
        ], material=made_of(b, "PLA"),
           not_modelled=[{"words": cite(b, "splitting it into two equal compartments"),
                          "reason": "follows from the divider being in the middle"}],
           silent=[{"sentence": 1, "reason": "it says there is no load case"}])  # fmt: skip
        report = check_draft(b, d)
        self.assertEqual(problems(report), [])
        assert report.layout is not None
        divider = report.layout.instances["divider"][0]
        self.assertEqual(
            (divider.lo, divider.hi), ((-1.0, -28.0, 2.0), (1.0, 28.0, 25.0))
        )

    def test_r08_an_open_top_box_and_c08_a_sealed_cube(self) -> None:
        b = number_words("A PLA open-top box, 60 mm long, 40 mm wide and 30 mm tall on the outside, with 2 mm "
                         "walls and a 2 mm thick floor. The top is completely open. " + LOAD)  # fmt: skip
        d = draft("box", [
            {"id": "box", "kind": "block", "words": cite(b, "open-top box"), "length": mm(b, 60, "60 mm"),
             "width": mm(b, 40, "40 mm"), "height": mm(b, 30, "30 mm")},
            {"id": "hollow", "kind": "shell", "words": cite(b, "walls"), "of": "box",
             "thickness": mm(b, 2, "2 mm walls"), "floor": mm(b, 2, "2 mm thick floor"),
             "open": {"faces": ["+z"], "from": said(b, "The top is completely open")}},
        ], material=made_of(b, "PLA"),
           silent=[{"sentence": 2, "reason": "it says there is no load case"}])  # fmt: skip
        self.assertEqual(problems(check_draft(b, d)), [])
        b = number_words("A sealed hollow PLA cube 40 mm on the outside with 2 mm walls on every side, "
                         "completely closed. " + LOAD)  # fmt: skip
        d = draft("cube", [
            {"id": "cube", "kind": "block", "words": cite(b, "cube"), "length": mm(b, 40, "40 mm"),
             "width": mm(b, 40, "40 mm"), "height": mm(b, 40, "40 mm")},
            {"id": "hollow", "kind": "shell", "words": cite(b, "sealed hollow"), "of": "cube",
             "thickness": mm(b, 2, "2 mm walls"), "open": {"faces": [], "from": said(b, "completely closed")}},
        ], material=made_of(b, "PLA"),
           silent=[{"sentence": 1, "reason": "it says there is no load case"}])  # fmt: skip
        report = check_draft(b, d)
        self.assertEqual(problems(report), [])
        self.assertIn("sealed all round", render(report, b).text())

    def test_c09_a_cup(self) -> None:
        b = number_words("A PLA cup: 60 mm outside diameter and 80 mm tall, with 2 mm walls and a 3 mm floor, "
                         "open at the top. " + LOAD)  # fmt: skip
        d = draft("cup", [
            {"id": "cup", "kind": "cylinder", "words": cite(b, "cup"), "diameter": mm(b, 60, "60 mm"),
             "length": mm(b, 80, "80 mm"), "axis": choose("z", assumed("a cup stands upright"))},
            {"id": "hollow", "kind": "shell", "words": cite(b, "walls"), "of": "cup",
             "thickness": mm(b, 2, "2 mm walls"), "floor": mm(b, 3, "3 mm floor"),
             "open": {"faces": ["+end"], "from": said(b, "open at the top")}},
        ], material=made_of(b, "PLA"),
           silent=[{"sentence": 1, "reason": "it says there is no load case"}])  # fmt: skip
        self.assertEqual(problems(check_draft(b, d)), [])

    def test_c15_a_ball_on_each_end_of_a_bar(self) -> None:
        b = number_words("A PLA dumbbell: a bar 50 mm long and 10 mm square, with a 16 mm ball centred on each "
                         "end of it. " + LOAD)  # fmt: skip

        def ball(item_id: str, face: str) -> dict[str, Any]:
            centre = said(b, "centred on each end")
            return {"id": item_id, "kind": "sphere", "words": cite(b, "ball"), "on": {"item": "bar", "face": face},
                    "diameter": mm(b, 16, "16 mm"), "portion": choose("whole", said(b, "ball")),
                    "place": {"y": {"centred": centre}, "z": {"centred": centre}}}  # fmt: skip

        d = draft("dumbbell", [
            {"id": "bar", "kind": "block", "words": cite(b, "bar"), "length": mm(b, 50, "50 mm"),
             "width": mm(b, 10, "10 mm square"), "height": mm(b, 10, "10 mm square")},
            ball("ball_plus", "+x"), ball("ball_minus", "-x"),
        ], material=made_of(b, "PLA"),
           silent=[{"sentence": 1, "reason": "it says there is no load case"}])  # fmt: skip
        report = check_draft(b, d)
        self.assertEqual(problems(report), [])
        assert report.layout is not None
        self.assertEqual(
            report.layout.extent(), ((-33.0, -8.0, -3.0), (33.0, 8.0, 13.0))
        )


if __name__ == "__main__":
    unittest.main()
