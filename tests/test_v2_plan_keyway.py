"""A slot round a side: a keyway (slot.md, "Round a side"; place.md, "Round a side"; V2-stage4b-0c.md, 3.3, item 3b).

- **Along the side's axis, square to the plane touching it:** a slot cut
  into a rod's, a boss's or a tube's side from outside, its outline in the
  plane that touches the side along the line through its point, ``length``
  along the side's axis and ``width`` round it, going in square to that
  plane, towards the axis, to its depth from that plane, flat-bottomed;
  round or square ended; at any angle, a circle of them too; its rim
  rounded. Deeper than
  the material under it is asked about (into a solid rod, the far side
  comes first at its long edges); right through a tube's wall it opens
  into the bore, right through a solid rod it comes out of the far side.
- **Every program's layout agrees.**
- **What is built is what was placed:** each part built by the build loop,
  every face accounted for both ways, every check its spec compiles to
  passing.
- **A wrong keyway is caught:** one cut half a millimetre shallower, or
  turned five degrees round the side, fails the judge.
- **The second kernel agrees** with the exact part.
- **What isn't yet is said:** a slot round a side running round it, one
  from inside a bore, on a tab's round end, through the next face, through
  everything or up to a face.
- **The generator draws it:** a keyway into a rod's side, blind or right
  through, as its own shape.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, cite, draft
from v2_occ import needs_occ

_TEXT = "A shaft, or a tube, with a keyway milled along its side."


def _shaft(b: Any, kind: str = "cylinder") -> dict[str, Any]:
    found = {"id": "shaft", "kind": kind, "words": cite(b, "shaft"), "length": assumed("long", 60.0)}
    if kind == "tube":
        found.update(outer_diameter=assumed("across", 30.0), inner_diameter=assumed("bore", 20.0))
    else:
        found["diameter"] = assumed("across", 20.0)
    return found


def _keyway(b: Any, depth: float | None = 3.5, *, angle: float | None = 90.0, along: str = "z", ends: str = "round",
            z: float | None = 10.0, face: str = "side", count: int | None = None, width: float = 6.0,
            length: float = 20.0) -> dict[str, Any]:  # fmt: skip
    found = {"id": "key", "kind": "slot", "words": cite(b, "keyway"), "on": {"item": "shaft", "face": face},
             "width": assumed("wide", width), "length": assumed("long", length),
             "along": {"choose": along, "from": {"assumed": "along the shaft"}},
             "ends": {"choose": ends, "from": {"assumed": "milled"}}}  # fmt: skip
    found["depth"] = {"through": True, "from": {"assumed": "through"}} if depth is None else assumed("deep", depth)
    place: dict[str, Any] = {}
    if angle is not None:
        place["angle"] = assumed("round", angle, "deg")
    if z is not None:
        place["z"] = {"offset": assumed("along", z)}
    if count is not None:
        many = {"count": count, "from": {"assumed": "evenly round"}}
        place["pattern"] = {"circle": {"count": many}}
        found["count"] = many
    if place:
        found["place"] = place
    return found


def _rounded(b: Any) -> dict[str, Any]:
    return {"id": "rim", "kind": "fillet", "words": cite(b, "milled"), "edges": {"of": "key", "which": "top"},
            "radius": assumed("eased", 0.5)}  # fmt: skip


#: Each part: a shaft (or a tube) and its keyway.
CASES: dict[str, Any] = {
    "a keyway": lambda b: [_shaft(b), _keyway(b)],
    "square ended": lambda b: [_shaft(b), _keyway(b, ends="square")],
    "at 30 degrees": lambda b: [_shaft(b), _keyway(b, angle=30.0)],
    "a circle of four": lambda b: [_shaft(b), _keyway(b, angle=0.0, count=4, width=4.0)],
    "right through a tube's wall": lambda b: [_shaft(b, "tube"), _keyway(b, None)],
    "right through a solid rod": lambda b: [_shaft(b), _keyway(b, None, width=4.0)],
    "its rim rounded": lambda b: [_shaft(b), _keyway(b, angle=30.0), _rounded(b)],
}


def _report(make: Any) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    brief = number_words(_TEXT)
    items = make(brief)
    return check_draft(brief, draft(items[0]["id"], items), strict=False)


def _planned(make: Any) -> tuple[Any, Any]:
    from forge_plan import plan
    from forge_spec.lock import lock
    from forge_spec.words import number_words

    brief = number_words(_TEXT)
    report = _report(make)
    assert not report.problems, [p.message for p in report.problems]
    spec = lock(report, brief, by="draft", strict=False)
    planned = plan(spec)
    assert not planned.gaps, [g.reason for g in planned.gaps]
    return spec, planned


class AlongTheSidesAxisSquareToThePlaneTouchingIt(unittest.TestCase):
    def test_where_each_goes(self) -> None:
        # The shaft 20 across along z from 0 to 60: at 90 degrees its point on the side at +y, 10 along from the middle.
        report = _report(CASES["a keyway"])
        self.assertEqual(report.problems, ())
        (copy,) = report.layout.instances["key"]
        self.assertEqual((copy.origin, copy.normal), ((0.0, 10.0, 40.0), (0.0, 1.0, 0.0)))
        four = _report(CASES["a circle of four"]).layout.instances["key"]
        self.assertEqual([c.normal for c in four], [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)])

    def test_deeper_than_the_material_under_it_is_asked_about(self) -> None:
        # Into a solid rod the far side comes first along its long edges: 10 + sqrt(100 - 9) in for one 6 wide.
        least = 10.0 + (100.0 - 9.0) ** 0.5
        deep = _report(lambda b: [_shaft(b), _keyway(b, 19.6)])
        self.assertTrue(any(f"19.6 mm deep in {least:g} mm of material" in p.message for p in deep.problems),
                        [p.message for p in deep.problems])  # fmt: skip
        self.assertEqual(_report(lambda b: [_shaft(b), _keyway(b, 19.5)]).problems, ())
        wall = _report(lambda b: [_shaft(b, "tube"), _keyway(b, 5.5)])
        self.assertTrue(any("5.5 mm deep in 5 mm of material" in p.message for p in wall.problems),
                        [p.message for p in wall.problems])  # fmt: skip

    def test_through_as_wide_as_the_bore_is_asked_about(self) -> None:
        # Right through a tube's wall as wide as its bore (Ø20) it would open the far wall too: one wall, or both?
        wide = _report(lambda b: [_shaft(b, "tube"), _keyway(b, None, width=20.0)])
        self.assertTrue(any("as wide as the bore of shaft" in p.message for p in wide.problems),
                        [p.message for p in wide.problems])  # fmt: skip
        self.assertEqual(_report(lambda b: [_shaft(b, "tube"), _keyway(b, None, width=19.0)]).problems, ())

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, make in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


class WhatIsntYetIsSaid(unittest.TestCase):
    def test_each(self) -> None:
        from forge_checks.place import PlaceError, place

        for make, words in (
            (lambda b: [_shaft(b), _keyway(b, along="x")], "along the side's axis (z)"),
            (lambda b: [_shaft(b, "tube"), _keyway(b, face="bore")], "from outside"),
            (lambda b: [_shaft(b), {**_keyway(b), "depth": {"through_next": True, "from": {"assumed": "out"}}}],
             "to a depth or right through"),
            (lambda b: [_shaft(b), {**_keyway(b), "depth": {"through_all": True, "from": {"assumed": "out"}}}],
             "to a depth or right through"),
        ):  # fmt: skip
            with self.subTest(words):
                report = _report(make)
                self.assertTrue(any(words in p.message for p in report.problems), [p.message for p in report.problems])
                with self.assertRaises(PlaceError):
                    place(report.spec)


@needs_occ
class BuiltAsPlaced(unittest.TestCase):
    def test_every_case(self) -> None:
        from forge_checks.classes import Verdict
        from test_v2_plan_build import judged_plan

        for name, make in CASES.items():
            with self.subTest(name):
                spec, planned = _planned(make)
                built, accounting, failed = judged_plan(spec.spec, planned)
                self.assertIsNone(built.gap, built.refusals)
                self.assertEqual(built.made_by["key"], "carried")  # its mouth touches the side along a line (5.2)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_its_checks(self) -> None:
        from forge_checks.compiler import compile_checks
        from forge_checks.oracle import oracle
        from forge_checks.place import place

        spec, _ = _planned(CASES["a circle of four"])
        placed = place(spec.spec)
        suite = compile_checks(spec.spec, placed, oracle(spec.spec, placed))
        found = {c.id.split("/")[1] for c in suite.checks if c.id.startswith("key/")}
        self.assertLessEqual({"width", "length", "depth", "place.angle", "place.z", "place.pattern.circle.count",
                              "count"}, found)  # fmt: skip
        self.assertEqual([u.field for u in suite.unchecked if u.item == "key" and u.held_by is None], [])


@needs_occ
class AWrongKeywayIsCaught(unittest.TestCase):
    def test_shallower_or_turned(self) -> None:
        import math
        from unittest import mock

        import forge_plan.items.plan.slot as plan_slot
        from forge_checks.classes import Verdict
        from forge_spec.frames import Rigid
        from test_v2_plan_build import judged_plan

        real_frame, real_extrude = plan_slot.keyway_frame, plan_slot._extrude_along

        def turned(face: Any, copy: Any) -> Any:
            out, w, turn = real_frame(face, copy)
            more = Rigid.turn_about(face.frame.origin, face.frame.n, math.cos(math.radians(5)),
                                    math.sin(math.radians(5)))  # fmt: skip
            rows = tuple(tuple(sum(more.rows[i][k] * turn.rows[k][j] for k in range(3)) for j in range(3))
                         for i in range(3))  # fmt: skip
            return out, w, Rigid(rows, more.point(turn.shift))  # type: ignore[arg-type]

        def shallower(chain: Any, item: Any, k: int, normal: str, axes: Any, w: Any, depth: float, *rest: Any) -> Any:
            return real_extrude(chain, item, k, normal, axes, w, depth - 0.5, *rest)

        for name, patch in (("turned 5 degrees", mock.patch.object(plan_slot, "keyway_frame", turned)),
                            ("0.5 mm shallower", mock.patch.object(plan_slot, "_extrude_along", shallower))):  # fmt: skip
            for case in ("a keyway", "at 30 degrees"):
                with self.subTest(name, case=case), patch:
                    spec, planned = _planned(CASES[case])
                    built, accounting, failed = judged_plan(spec.spec, planned)
                    self.assertIsNone(built.gap)
                    self.assertTrue(accounting.verdict is Verdict.FAIL or failed, failed)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_a_keyway(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("at 30 degrees", "right through a tube's wall", "right through a solid rod"):
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


class TheGeneratorDrawsIt(unittest.TestCase):
    def _plans(self) -> list[Any]:
        from forge_eval.generator import Feature, Position

        rod = Feature("body", "cylinder", {"diameter": 20.0, "length": 50.0})
        tube = Feature("body", "tube", {"outer_diameter": 30.0, "inner_diameter": 20.0, "length": 50.0})

        def key(depth: float | None, angle: float = 90.0, ends: str = "round", wide: float = 5.0) -> Any:
            return Feature("i0", "slot", {"length": 16.0, "width": wide}, ("body", "side"), depth,
                           {"along": "z", "ends": ends}, None, {"z": Position("offset", 6.0)}, angle)  # fmt: skip

        return [(rod, key(3.0)), (rod, key(3.0, 30.0, "square")), (rod, key(None, wide=4.0)), (tube, key(None))]

    def test_its_side_taken(self) -> None:
        from forge_eval.generator import _build

        side = _build(self._plans()[0], True).rounds[("body", 0, "side")]
        self.assertEqual(len(side.taken), 1)
        along, angle, reach, deep = side.taken[0]
        self.assertEqual((along, angle, deep), (31.0, 90.0, 3.0))
        self.assertAlmostEqual(reach, (8.0**2 + 2.5**2) ** 0.5)

    @needs_occ
    def test_its_own_shape(self) -> None:
        from forge_eval.generator import render
        from v2_exit4 import _built, _graded, _spec

        for plan in self._plans():
            with self.subTest(angle=plan[1].angle, depth=plan[1].depth, body=plan[0].kind):
                case = render(plan)
                _, built = _built(_spec(case.items))
                self.assertIsNone(built.gap, built.refusals)
                self.assertEqual(_graded(built.result.shape, case.truth, 0), [])


if __name__ == "__main__":
    unittest.main()
