"""A hole, a boss or a post on a ball's or a dome's surface (place.md, "On a ball's surface"; sphere.md; schema 1.6;
V2-stage4b-0c.md, 3.4, item 3b's second step).

- **Read in schema 1.6 only:** ``place.latitude`` in an older draft is a
  fault that names the version.
- **Placed as at its pole, then turned about its centre** down to its
  latitude and round its pole to its angle: its point, its direction; every
  program's layout agrees.
- **What isn't built yet is said:** a tab on a ball, a hole right through a
  dome, a foot past a dome's rim.
- **What is built is what was placed.** A boss and a post on a ball, a
  post on a dome, a circle of holes round a ball's pole, a hole right
  through a ball, a boss at its pole, on a ball and a dome standing on a
  plate, round a ball standing on the plate's side; a boss's joint with the
  ball rounded, a hole's mouth bevelled, a post's edges rounded: built by
  the build loop, every face accounted for both ways, every check its spec
  compiles to passing.
- **A wrong turn is caught:** each turned half a degree more fails the
  judge.
- **The second kernel agrees** with the exact part.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, cite, draft, mm
from v2_occ import needs_occ

_TEXT = "A plate 100 mm long, 60 mm wide and 8 mm thick. A ball on it has a boss, a post and a hole."
#: A ball's own brief, where the ball is the first body.
_BALL = "A ball has a boss, a post and a hole."


def _plate(b: Any) -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 100, "100 mm"),
            "width": mm(b, 60, "60 mm"), "height": mm(b, 8, "8 mm")}  # fmt: skip


def _ball(b: Any, portion: str = "whole", on: str | None = None, face: str = "+z", across: float = 40.0) -> dict[str, Any]:
    found = {"id": "ball", "kind": "sphere", "words": cite(b, "ball"), "diameter": assumed("across", across),
             "portion": {"choose": portion, "from": {"assumed": "so"}}}  # fmt: skip
    if on is not None:
        found["on"] = {"item": on, "face": face}
    return found


def _on(b: Any, kind: str, latitude: float | None, angle: float | None = None, *, item: str | None = None,
        count: int | None = None, depth: float | None = 5.0, **fields: Any) -> dict[str, Any]:  # fmt: skip
    """A hole, a boss or a post on the ball's surface, at ``latitude`` and ``angle`` round its pole."""
    sizes = {"boss": {"diameter": assumed("across", 6.0), "height": assumed("tall", 5.0)},
             "post": {"length": assumed("long", 6.0), "width": assumed("wide", 4.0), "height": assumed("tall", 5.0)},
             "hole": {"diameter": assumed("across", 4.0),
                      "depth": {"through": True, "from": {"assumed": "through"}} if depth is None
                      else assumed("deep", depth)},
             "tab": {"length": assumed("out", 6.0), "width": assumed("wide", 5.0), "thickness": assumed("thick", 2.0),
                     "thickness_along": {"choose": "x", "from": {"assumed": "across"}},
                     "end": {"choose": "round", "from": {"assumed": "round"}}}}[kind]  # fmt: skip
    place: dict[str, Any] = {}
    if latitude is not None:
        place["latitude"] = assumed("up", latitude, "deg")
    if angle is not None:
        place["angle"] = assumed("round", angle, "deg")
    found = {"id": item or kind, "kind": kind, "words": cite(b, "boss" if kind == "tab" else kind),
             "on": {"item": "ball", "face": "surface"}, **sizes, **fields}  # fmt: skip
    if count is not None:
        place["pattern"] = {"circle": {"count": {"count": count, "from": {"assumed": "so many"}}}}
        found["count"] = {"count": count, "from": {"assumed": "so many"}}
    if place:
        found["place"] = place
    return found


def _rounding(b: Any, of: str, which: str, kind: str = "fillet", size: float = 0.8, **more: Any) -> dict[str, Any]:
    return {"id": "round", "kind": kind, "words": cite(b, "boss"), ("radius" if kind == "fillet" else "size"):
            assumed("small", size), "edges": {"of": of, "which": which, **more}}  # fmt: skip


#: Each part: its items, the first its first body (a ball, or the plate it stands on).
CASES: dict[str, Any] = {
    "a boss and a post on a ball": lambda b: [_ball(b), _on(b, "boss", 45.0, 30.0), _on(b, "post", 20.0, 200.0)],
    "a post on a dome": lambda b: [_ball(b, "upper_half"), _on(b, "post", 40.0, 75.0)],
    "a circle of holes round a ball's pole": lambda b: [_ball(b), _on(b, "hole", 60.0, 100.0, count=3, depth=8.0)],
    "a hole right through a ball": lambda b: [_ball(b), _on(b, "hole", 25.0, 130.0, depth=None)],
    "a boss at a ball's pole": lambda b: [_ball(b), _on(b, "boss", None)],
    "on a ball standing on the plate": lambda b: [_plate(b), _ball(b, on="plate", across=30.0),
                                                  _on(b, "boss", 50.0, 10.0), _on(b, "hole", 70.0, 250.0, depth=4.0)],
    "on a dome standing on the plate": lambda b: [_plate(b), _ball(b, "upper_half", on="plate", across=40.0),
                                                  _on(b, "post", 30.0, 300.0), _on(b, "hole", 80.0, 45.0, depth=6.0)],
    "round a ball standing on the plate's side": lambda b: [_plate(b), _ball(b, on="plate", face="+x", across=30.0),
                                                            _on(b, "boss", 35.0, 60.0), _on(b, "post", 30.0, 200.0),
                                                            _on(b, "hole", 60.0, 300.0, depth=4.0)],
    "a boss's joint rounded": lambda b: [_ball(b), _on(b, "boss", 45.0, 30.0),
                                         _rounding(b, "boss", "joint", where_meets="ball")],
    "a hole's mouth bevelled": lambda b: [_ball(b), _on(b, "hole", 45.0, 30.0), _rounding(b, "hole", "top", "chamfer", 0.5)],
    "a post's edges rounded": lambda b: [_ball(b), _on(b, "post", 45.0, 30.0), _rounding(b, "post", "vertical", size=0.5)],
}


def _report(make: Any, version: str = "1.6") -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    items = make(number_words(_TEXT))
    b = number_words(_TEXT if items[0]["id"] == "plate" else _BALL)
    items = make(b)
    found = draft(items[0]["id"], items)
    found["schema_version"] = version
    return b, check_draft(b, found, strict=False)


def _planned(make: Any) -> tuple[Any, Any]:
    from forge_plan import plan
    from forge_spec.lock import lock

    b, report = _report(make)
    assert not report.problems, [p.message for p in report.problems]
    spec = lock(report, b, by="draft", strict=False)
    planned = plan(spec)
    assert not planned.gaps, [g.reason for g in planned.gaps]
    return spec, planned


def _judged(make: Any) -> tuple[Any, Any, list[str]]:
    from test_v2_plan_build import judged_plan

    spec, planned = _planned(make)
    return judged_plan(spec.spec, planned)


class ALatitudeIsSchema16s(unittest.TestCase):
    def test_a_fault_before(self) -> None:
        _, old = _report(CASES["a boss and a post on a ball"], "1.5")
        faults = [p for p in old.problems if p.kind == "fault"]
        self.assertIn("/items/1/place/latitude", [p.at for p in faults])
        self.assertTrue(any('"schema_version": "1.6"' in p.message for p in faults))


class PlacedAsAtItsPoleThenTurned(unittest.TestCase):
    def test_a_boss_on_a_ball(self) -> None:
        _, report = _report(CASES["a boss and a post on a ball"])
        self.assertEqual([p for p in report.problems if p.kind in ("fault", "unable", "cant")], [])
        (copy,) = report.layout.instances["boss"]
        c, s = math.cos(math.radians(45)), math.sin(math.radians(45))
        out = (c * math.cos(math.radians(30)), c * math.sin(math.radians(30)), s)
        for got, want in ((copy.normal, out), (copy.origin, tuple(20 * x + (20.0 if k == 2 else 0.0)
                                                                  for k, x in enumerate(out)))):  # fmt: skip
            for g, w in zip(got, want, strict=True):
                self.assertAlmostEqual(g, w, places=9)
        assert copy.local is not None
        self.assertEqual((copy.local.origin, copy.local.normal), ((0.0, 0.0, 40.0), (0.0, 0.0, 1.0)))

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, make in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


class WhatIsntBuiltYetIsSaid(unittest.TestCase):
    def test_each(self) -> None:
        for make, kind, words in (
            (lambda b: [_ball(b), _on(b, "tab", 30.0)], "unable", "Forge cuts round holes and stands bosses and posts"),
            (lambda b: [_ball(b, "upper_half"), _on(b, "hole", 40.0, depth=None)], "unable", "a whole ball only"),
            (lambda b: [_ball(b, "upper_half"), _on(b, "boss", 5.0)], ("question", "fault"), "past the rim of the dome"),
        ):  # fmt: skip
            with self.subTest(words):
                _, report = _report(make)
                self.assertTrue(any(p.kind in kind and words in p.message for p in report.problems),
                                [(p.kind, p.message) for p in report.problems])  # fmt: skip


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

        for name in ("a boss and a post on a ball", "a circle of holes round a ball's pole", "a post on a dome"):
            with self.subTest(name), mock.patch.object(moved, "transform_params", more):
                built, accounting, _ = _judged(CASES[name])
                self.assertIsNone(built.gap)
                self.assertIs(accounting.verdict, Verdict.FAIL)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_on_a_ball_and_a_dome(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("a boss and a post on a ball", "a post on a dome", "a hole right through a ball",
                     "on a ball standing on the plate", "a boss's joint rounded"):  # fmt: skip
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
