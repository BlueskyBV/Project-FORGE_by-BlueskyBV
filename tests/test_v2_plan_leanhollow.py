"""A leaning block hollowed (shell.md; place.md, "Leaning on the face"; V2-stage4b-0c.md, 3.3, 1b's step 5.5, with item
2b).

- **Hollowed as it stands upright, its floor raised, then leaned:** its
  hollow as with it upright, its floor raised by as much as the face it
  leans on rises under the hollow's far side along its lean (its half size
  along it less its wall there, times its tilt's tan), so the floor is its
  thickness where it is thinnest; its walls the material under its sides
  and its far face, its inside faces leaned with it, the material under its
  floor its own back along its axis to the face it leans on. Every
  program's layout agrees.
- **What goes on it:** a hole into its floor as deep as the material under
  it there, deeper asked about, right through it said; a hole through an
  inside wall, through a side and through its sealed far face, each coming
  out in or out of the hollow; a boss on its floor.
- **What is built is what was placed:** each part built by the build loop,
  every face accounted for both ways, every check its spec compiles to
  passing.
- **A wrong lean is caught:** its hollow leaned half a degree more fails the
  judge.
- **The second kernel agrees** with the exact part.
- **What isn't yet is said:** a leaning cylinder hollowed, and a block
  turned and leaning.
- **The generator draws it:** a leaning block hollowed, sealed or open, its
  floor thicker, as its own shape, its faces as the solver has them.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan_faceaxes import _judged, _planned
from test_v2_plan_leanbody import _block, _cylinder
from test_v2_plan_turnedover import _report
from v2_drafts import assumed, cite
from v2_occ import needs_occ


def _shell(b: Any, floor: float | None = None, opened: tuple[str, ...] = ("+z",), of: str = "leaning") -> dict[str, Any]:
    found = {"id": "hollow", "kind": "shell", "words": cite(b, "post"), "of": of, "thickness": assumed("thick", 1.5),
             "open": {"faces": list(opened), "from": {"assumed": "open at the top"}}}  # fmt: skip
    if floor is not None:
        found["floor"] = assumed("floor", floor)
    return found


def _hole(b: Any, face: str, depth: float | None = None, d: float = 2.0, **place: Any) -> dict[str, Any]:
    found = {"id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "leaning", "face": face},
             "diameter": assumed("across", d)}  # fmt: skip
    found["depth"] = {"through": True, "from": {"assumed": "through"}} if depth is None else assumed("deep", depth)
    if place:
        found["place"] = place
    return found


def _boss(b: Any, face: str) -> dict[str, Any]:
    return {"id": "hole", "kind": "boss", "words": cite(b, "boss"), "on": {"item": "leaning", "face": face},
            "diameter": assumed("across", 3.0), "height": assumed("tall", 2.0)}  # fmt: skip


def _leaning(b: Any, tilt: float = 20.0, way: str = "+x") -> dict[str, Any]:
    """A block 20 by 10 mm and 12 mm tall leaning on the plate."""
    return _block(b, tilt, way, sizes=(20.0, 10.0, 12.0))


#: Each part: a leaning block hollowed, and what is done with it.
CASES: dict[str, Any] = {
    "open at its top": lambda b: [_leaning(b), _shell(b)],
    "sealed": lambda b: [_leaning(b, 30.0, "-y"), _shell(b, opened=())],
    "a thicker floor": lambda b: [_leaning(b, 15.0, "+y"), _shell(b, 2.0)],
    "a hole into its floor": lambda b: [_leaning(b), _shell(b), _hole(b, "inner -z", 4.0)],
    "a hole through an inside wall": lambda b: [_leaning(b), _shell(b), _hole(b, "inner +y")],
    "a hole through a side": lambda b: [_leaning(b), _shell(b), _hole(b, "-x")],
    "a hole through its sealed far face": lambda b: [_leaning(b), _shell(b, opened=()), _hole(b, "+z")],
    "a boss on its floor": lambda b: [_leaning(b), _shell(b), _boss(b, "inner -z")],
}


class HollowedUprightItsFloorRaisedThenLeaned(unittest.TestCase):
    def test_its_hollow_and_faces(self) -> None:
        tan = math.tan(math.radians(20.0))
        report = _report(CASES["open at its top"])
        self.assertEqual(report.problems, ())
        # Upright from the plate's top at 8: its floor 1.5 thick over where the plate rises under the hollow's far side,
        # 10 - 1.5 along its lean from its axis.
        lo, hi = report.layout.cavities[("leaning", 0)]
        for got, want in zip((*lo, *hi), (-8.5, -3.5, 8.0 + 8.5 * tan + 1.5, 8.5, 3.5, 20.0), strict=True):
            self.assertAlmostEqual(got, want, places=9)
        faces = report.layout.faces[("leaning", 0)]
        floor = faces["inner -z"]
        self.assertAlmostEqual(floor.depth_below, 1.5 + 8.5 * tan, places=9)
        self.assertEqual((floor.depth_model.way, floor.depth_model.tan), ((1.0, 0.0), tan))  # type: ignore[union-attr]
        for name in ("+x", "-y", "inner +x", "inner -y"):
            self.assertEqual(faces[name].depth_below, 1.5)
        c, s = math.cos(math.radians(20.0)), math.sin(math.radians(20.0))
        for name, way in (("inner -z", (s, 0.0, c)), ("inner +x", (-c, 0.0, s)), ("+x", (c, 0.0, -s))):
            for got, want in zip(faces[name].frame.n, way, strict=True):
                self.assertAlmostEqual(got, want, places=9)
        self.assertIn("+z", report.layout.closed[("leaning", 0)])  # open: its rim takes nothing yet
        sealed = _report(CASES["sealed"]).layout.faces[("leaning", 0)]
        self.assertEqual((sealed["+z"].depth_below, sealed["+z"].depth_model), (1.5, None))

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, make in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


class WhatGoesOnIt(unittest.TestCase):
    def test_into_its_floor_as_deep_as_the_material_there(self) -> None:
        # 6 mm along its lean from its middle the floor is 1.5 + (8.5 - 6) tan 20 mm thick, less the hole's half
        # across along its lean.
        report = _report(lambda b: [_leaning(b), _shell(b), _hole(b, "inner -z", 4.5, u={"offset": assumed("o", 6.0)})])
        least = 1.5 + (8.5 - 6.0 - 1.0) * math.tan(math.radians(20.0))
        self.assertTrue(any(f"4.5 mm deep in {least:g} mm of material" in p.message for p in report.problems),
                        [p.message for p in report.problems])  # fmt: skip

    def test_right_through_its_floor_is_said(self) -> None:
        report = _report(lambda b: [_leaning(b), _shell(b), _hole(b, "inner -z")])
        self.assertTrue(any("would come out on the face it leans on" in p.message for p in report.problems))

    def test_each_case_placed(self) -> None:
        for name, make in CASES.items():
            with self.subTest(name):
                self.assertEqual(_report(make).problems, ())


class WhatIsntYetIsSaid(unittest.TestCase):
    def test_each(self) -> None:
        from forge_checks.place import PlaceError, place
        from forge_spec.checks import check_draft
        from forge_spec.words import number_words
        from test_v2_plan_faceaxes import _TEXT, _plate
        from v2_drafts import draft

        turned = {"place": {"turn": assumed("turned", 30.0, "deg")}}
        for make in (lambda b: [_cylinder(b), _shell(b, opened=("+end",))],
                     lambda b: [_block(b, 25.0, "-y", sizes=(20.0, 10.0, 12.0), **turned), _shell(b)]):  # fmt: skip
            report = _report(make)
            self.assertTrue(any("Forge hollows a leaning block" in p.message for p in report.problems),
                            [p.message for p in report.problems])  # fmt: skip
            brief = number_words(_TEXT)
            found = check_draft(brief, draft("plate", [_plate(brief), *make(brief)]), strict=False)
            with self.assertRaises(PlaceError):
                place(found.spec)


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
class AWrongLeanIsCaught(unittest.TestCase):
    def test_its_hollow_leaned_half_a_degree_more(self) -> None:
        import forge_plan.moved as moved
        from forge_checks.classes import Verdict

        real = moved.transform_params

        def more(motion: Any) -> dict[str, Any]:
            found = real(motion)
            angle = found["rotate_angle"]
            return {**found, "rotate_angle": {**angle, "magnitude": angle["magnitude"] + 0.5}}

        for name in ("open at its top", "a hole into its floor"):
            with self.subTest(name), mock.patch.object(moved, "transform_params", more):
                built, accounting, failed = _judged(CASES[name])
                self.assertIsNone(built.gap)
                self.assertTrue(accounting.verdict is Verdict.FAIL or failed, failed)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_hollowed(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("sealed", "a hole through an inside wall"):
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


class TheGeneratorDrawsIt(unittest.TestCase):
    def _plans(self) -> list[Any]:
        from forge_eval.generator import Feature

        body = Feature("body", "block", {"length": 60.0, "width": 40.0, "height": 10.0})
        found = []
        for tilt, opened, floor in (((20.0, "+x"), ("+z",), None), ((30.0, "-y"), (), None),
                                    ((15.0, "+y"), ("+z",), 2.0)):  # fmt: skip
            lean = Feature("i0", "block", {"length": 20.0, "width": 14.0, "height": 16.0}, ("body", "+z"), tilt=tilt)
            sizes = {"thickness": 1.5, **({} if floor is None else {"floor": floor})}
            found.append((body, lean, Feature("hollow1", "shell", sizes, of="i0", faces=opened)))
        return found

    def test_its_faces(self) -> None:
        from forge_eval.generator import _build

        flats = _build(self._plans()[0], True).flats
        tan = math.tan(math.radians(20.0))
        floor = flats[("i0", 0, "inner -z")]
        self.assertAlmostEqual(floor.material, 1.5 + 8.5 * tan, places=9)
        self.assertEqual(floor.slant, ((1.0, 0.0), tan))
        for name in ("+x", "-y", "inner +x", "inner -y"):
            self.assertEqual((flats[("i0", 0, name)].material, flats[("i0", 0, name)].leans), (1.5, True))
        self.assertEqual(flats[("i0", 0, "+x")].exit, ("i0", 0, "inner +x"))
        self.assertNotIn(("i0", 0, "+z"), flats)  # open

    @needs_occ
    def test_its_own_shape(self) -> None:
        from forge_eval.generator import render
        from v2_exit4 import _built, _graded, _spec

        for plan in self._plans():
            with self.subTest(tilt=plan[1].tilt):
                case = render(plan)
                _, built = _built(_spec(case.items))
                self.assertIsNone(built.gap, built.refusals)
                self.assertEqual(_graded(built.result.shape, case.truth, 0), [])


if __name__ == "__main__":
    unittest.main()
