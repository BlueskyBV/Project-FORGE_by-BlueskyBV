"""A standing item round a side at any angle (place.md, "Round a side"; V2-stage4b-0c.md, 3.4, item 3b's first step).

- **Placed as at the frame axis at or below its angle, then turned with the
  side about its axis by the rest:** its point, its direction, its box and
  its far face where they are; every program's layout agrees.
- **What is built is what was placed.** A boss at 30 degrees round a rod,
  a post at 200, a circle of three bosses, a tab and a rib, a boss round a
  rod lying along x, a boss in a tube's bore, a hole in an angled boss's far
  face, its rim rounded, a post's top edges bevelled, its joint with the
  rod rounded: built by the build loop, every face accounted for both
  ways, every check its spec compiles to passing.
- **A wrong turn is caught:** each turned half a degree more fails the
  judge.
- **The second kernel agrees** with the exact part, a generated part's
  too (24's: a tool's face lost before it was turned is told on that
  step's part).
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan_faceaxes import _TEXT, _judged, _planned, _plate
from v2_drafts import assumed, cite, draft
from v2_occ import needs_occ


def _rod(b: Any, face: str = "+z", *, kind: str = "cylinder", item: str = "rod") -> dict[str, Any]:
    found = {"id": item, "kind": kind, "words": cite(b, "boss"), "on": {"item": "plate", "face": face},
             "length": assumed("long", 30.0)}  # fmt: skip
    if kind == "tube":
        found.update(outer_diameter=assumed("across", 40.0), inner_diameter=assumed("bore", 30.0))
    else:
        found["diameter"] = assumed("across", 20.0)
    return found


def _round(b: Any, angle: float, kind: str = "boss", *, item: str = "boss", on: str = "rod", face: str = "side",
           count: int | None = None, **fields: Any) -> dict[str, Any]:  # fmt: skip
    """A boss, a post, a tab or a rib standing round a side at ``angle`` (a circle of ``count`` of them, from it)."""
    sizes = {"boss": {"diameter": assumed("across", 6.0), "height": assumed("tall", 5.0)},
             "post": {"length": assumed("long", 6.0), "width": assumed("wide", 4.0), "height": assumed("tall", 5.0)},
             "tab": {"length": assumed("out", 6.0), "width": assumed("wide", 5.0), "thickness": assumed("thick", 2.0),
                     "thickness_along": {"choose": "z", "from": {"assumed": "across"}},
                     "end": {"choose": "round", "from": {"assumed": "round"}}},
             "rib": {"length": assumed("long", 12.0), "thickness": assumed("thick", 2.0), "height": assumed("tall", 3.0),
                     "along": {"choose": "z", "from": {"assumed": "along the rod"}}}}[kind]  # fmt: skip
    found = {"id": item, "kind": kind, "words": cite(b, "boss"), "on": {"item": on, "face": face},
             "place": {"angle": assumed("round", angle, "deg")}, **sizes, **fields}  # fmt: skip
    if count is not None:
        found["place"]["pattern"] = {"circle": {"count": {"count": count, "from": {"assumed": "so many"}}}}
        found["count"] = {"count": count, "from": {"assumed": "so many"}}
    return found


def _rounding(b: Any, of: str, which: str, kind: str = "fillet", size: float = 1.0, **more: Any) -> dict[str, Any]:
    return {"id": "round", "kind": kind, "words": cite(b, "post"), ("radius" if kind == "fillet" else "size"):
            assumed("small", size), "edges": {"of": of, "which": which, **more}}  # fmt: skip


#: Each part: a rod (or a tube) on the plate, and what stands round its side at an angle.
CASES: dict[str, Any] = {
    "a boss at 30 degrees": lambda b: [_rod(b), _round(b, 30.0)],
    "a post at 200 degrees": lambda b: [_rod(b), _round(b, 200.0, "post")],
    "a circle of three bosses": lambda b: [_rod(b), _round(b, 10.0, count=3)],
    "a tab at 45 degrees": lambda b: [_rod(b), _round(b, 45.0, "tab", item="tab")],
    "a rib along the rod at 120 degrees": lambda b: [_rod(b), _round(b, 120.0, "rib", item="rib")],
    "a boss round a rod lying along x": lambda b: [_rod(b, "+x"), _round(b, 60.0)],
    "a boss in a tube's bore": lambda b: [_rod(b, kind="tube", item="tube"),
                                          _round(b, 30.0, on="tube", face="bore", height=assumed("tall", 3.0),
                                                 diameter=assumed("across", 4.0))],
    "a hole in its far face": lambda b: [_rod(b), _round(b, 30.0), {
        "id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "boss", "face": "+end"},
        "diameter": assumed("across", 2.0), "depth": assumed("deep", 3.0)}],
    "its rim rounded": lambda b: [_rod(b), _round(b, 30.0), _rounding(b, "boss", "top", size=0.6)],
    "a post's top edges bevelled": lambda b: [_rod(b), _round(b, 75.0, "post"),
                                              _rounding(b, "boss", "top", "chamfer", 0.5)],
    "its joint rounded": lambda b: [_rod(b), _round(b, 30.0), _rounding(b, "boss", "joint", size=0.6, where_meets="rod")],
}


class PlacedAsAtTheAxisBelowThenTurned(unittest.TestCase):
    def test_a_boss_at_30_degrees(self) -> None:
        from forge_spec.checks import check_draft
        from forge_spec.words import number_words

        b = number_words(_TEXT)
        report = check_draft(b, draft("plate", [_plate(b), *CASES["a boss at 30 degrees"](b)]), strict=False)
        self.assertEqual([p for p in report.problems if p.kind in ("fault", "unable", "cant")], [])
        (copy,) = report.layout.instances["boss"]
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        for got, want in ((copy.origin, (10 * c, 10 * s, 23.0)), (copy.normal, (c, s, 0.0)),
                          (report.layout.faces[("boss", 0)]["+end"].centre, (15 * c, 15 * s, 23.0))):  # fmt: skip
            for g, w in zip(got, want, strict=True):
                self.assertAlmostEqual(g, w, places=9)
        assert copy.local is not None
        self.assertEqual((copy.local.origin, copy.local.normal), ((10.0, 0.0, 23.0), (1.0, 0.0, 0.0)))

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, make in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


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
class AWrongTurnIsCaught(unittest.TestCase):
    def test_turned_half_a_degree_more(self) -> None:
        import forge_plan.moved as moved
        from forge_checks.classes import Verdict

        real = moved.transform_params

        def more(motion: Any) -> dict[str, Any]:
            found = real(motion)
            angle = found["rotate_angle"]
            return {**found, "rotate_angle": {**angle, "magnitude": angle["magnitude"] + 0.5}}

        for name in ("a boss at 30 degrees", "a circle of three bosses", "a rib along the rod at 120 degrees"):
            with self.subTest(name), mock.patch.object(moved, "transform_params", more):
                built, accounting, _ = _judged(CASES[name])
                self.assertIsNone(built.gap)
                self.assertIs(accounting.verdict, Verdict.FAIL)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_a_boss_a_circle_and_a_tab(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("a boss at 30 degrees", "a circle of three bosses", "a tab at 45 degrees", "its rim rounded",
                     "its joint rounded"):  # fmt: skip
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))

    def test_a_kept_generated_part(self) -> None:
        """24's (tests/v2_regressions.py): two bosses round a drum, a hole down its end. Their tools' bases are lost
        trimming them to the drum, before they are turned round it: lost rightly, told on that step's part."""
        from forge_eval.generator import render
        from forge_occ.agreement import agree
        from v2_exit4 import _built, _spec
        from v2_regressions import REGRESSIONS

        planned, built = _built(_spec(render(REGRESSIONS[24][1]).items))
        self.assertIsNone(built.gap, built.refusals)
        report = agree(planned.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
