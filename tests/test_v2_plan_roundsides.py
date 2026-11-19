"""The flat sides of what stands round a side (place.md, "On a round side"; V2-stage4b-0c.md, 3.4, item 3b).

- **Its box's sides, from its point out:** a post or a tab standing round a
  rod's side, at a frame axis or turned round the rod, has its flat sides as
  its box's from its point out, clear of where its foot follows the curve;
  each has its size across it under it, a cut right through coming out on
  the side across (a lug's cross hole). Every program's layout agrees.
- **What is built is what was placed:** holes across a post and along the
  rod through it, at 0, 30 and 200 degrees, blind and right through, and
  one through a tab's broad face: built by the build loop, every face
  accounted for both ways, every check its spec compiles to passing.
- **The second kernel agrees** with the exact part.
- **What isn't yet is said:** a boss's round side.
- **The generator draws it:** a post's sides round a rod, oriented as it is
  turned, a cut on one now and then, built as its own shape.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan_faceaxes import _judged, _planned
from test_v2_plan_roundangle import _rod, _round
from test_v2_plan_turnedover import _report
from v2_drafts import assumed, cite
from v2_occ import needs_occ


def _hole(b: Any, face: str, depth: float | None = None, on: str = "boss") -> dict[str, Any]:
    found = {"id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": on, "face": face},
             "diameter": assumed("across", 1.5)}  # fmt: skip
    found["depth"] = {"through": True, "from": {"assumed": "through"}} if depth is None else assumed("deep", depth)
    return found


#: Each part: a rod on the plate, what stands round its side, and a hole into one of its flat sides.
CASES: dict[str, Any] = {
    "across a post at 0 degrees": lambda b: [_rod(b), _round(b, 0.0, "post"), _hole(b, "+y")],
    "along the rod through a post at 0 degrees": lambda b: [_rod(b), _round(b, 0.0, "post"), _hole(b, "+z")],
    "across a post at 30 degrees": lambda b: [_rod(b), _round(b, 30.0, "post"), _hole(b, "+y")],
    "blind along the rod into a post at 200 degrees": lambda b: [_rod(b), _round(b, 200.0, "post"), _hole(b, "-z", 2.0)],
    "through a tab's broad face at 45 degrees": lambda b: [_rod(b), _round(b, 45.0, "tab"), _hole(b, "+z")],
}  # fmt: skip


class ItsBoxsSidesFromItsPointOut(unittest.TestCase):
    def test_a_posts_sides(self) -> None:
        report = _report(CASES["across a post at 0 degrees"])
        self.assertEqual(report.problems, ())
        faces = report.layout.faces[("boss", 0)]
        self.assertEqual(sorted(faces), ["+x", "+y", "+z", "-y", "-z"])
        # The rod 20 across standing on the plate's top at 8, the post 6 round it, 4 along it and 5 tall at +x.
        across = faces["+y"]
        self.assertEqual((across.centre, across.axes, across.half, across.depth_below),
                         ((12.5, 3.0, 23.0), ("x", "z"), (2.5, 2.0), 6.0))  # fmt: skip

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, make in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


class WhatIsntYetIsSaid(unittest.TestCase):
    def test_a_bosss_round_side(self) -> None:
        report = _report(lambda b: [_rod(b), _round(b, 0.0), _hole(b, "side", 2.0)])
        self.assertTrue(any("only its far face and its flat sides take anything" in p.message for p in report.problems),
                        [p.message for p in report.problems])  # fmt: skip


@needs_occ
class BuiltAsPlaced(unittest.TestCase):
    def test_every_case(self) -> None:
        from forge_checks.classes import Verdict

        for name, make in CASES.items():
            with self.subTest(name):
                built, accounting, failed = _judged(make)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_a_cross_hole(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("across a post at 30 degrees", "along the rod through a post at 0 degrees"):
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


class TheGeneratorDrawsIt(unittest.TestCase):
    def _post(self, angle: float) -> tuple[Any, Any]:
        from forge_eval.generator import Feature

        rod = Feature("body", "cylinder", {"diameter": 20.0, "length": 30.0})
        return rod, Feature("i1", "post", {"length": 6.0, "width": 4.0, "height": 5.0}, ("body", "side"), angle=angle)

    def test_its_sides(self) -> None:
        from forge_eval.generator import _build

        flats = _build(self._post(0.0), True).flats
        side = flats[("i1", 0, "+y")]
        self.assertEqual((side.material, side.exit, side.footed, side.oriented), (6.0, ("i1", 0, "-y"), True, None))
        self.assertIsNotNone(_build(self._post(30.0), True).flats[("i1", 0, "+y")].oriented)

    @needs_occ
    def test_its_own_shape(self) -> None:
        from forge_eval.generator import Feature, Position, _build, render
        from v2_exit4 import _built, _graded, _spec

        # Off its middle along its first axis too, from its edge: turned round the rod, its way along each axis is
        # the way that axis's + side faces (generated part 77, a hole from its +x edge on a post at 234.5 degrees).
        edge = {"x": Position("side", 1.0, "+x", "edge")}
        for angle, name, place in ((0.0, "+y", {}), (0.0, "+z", {}), (30.0, "+y", {}), (200.0, "-z", {}),
                                   (234.5, "-z", edge), (90.0, "+z", {"y": Position("side", 1.0, "+y", "edge")})):  # fmt: skip
            for depth in (1.5, None):
                with self.subTest(angle=angle, face=name, depth=depth, place=bool(place)):
                    plan = self._post(angle)
                    face = _build(plan, True).flats[("i1", 0, name)]
                    case = render((*plan, Feature("i2", "hole", {"diameter": 1.5}, ("i1", name), depth,
                                                  place=place, own_axes=face.axes)))  # fmt: skip
                    _, built = _built(_spec(case.items))
                    self.assertIsNone(built.gap, built.refusals)
                    self.assertEqual(_graded(built.result.shape, case.truth, 0), [])


if __name__ == "__main__":
    unittest.main()
