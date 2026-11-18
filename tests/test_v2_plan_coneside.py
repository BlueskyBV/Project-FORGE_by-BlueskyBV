"""A hole, a boss or a post on a cone's side (place.md, "On a cone's side"; cone.md; V2-stage4b-0c.md, 3.4, item 3b's
third step).

- **Placed as round a side, square to the cone:** a hole along the side's
  normal at its point; a boss or a post as at the frame axis at or below
  its angle, standing out along the radius there, then leaned with the
  slope and turned about the axis by the rest: its point, its direction;
  every program's layout agrees.
- **What isn't built yet, or doesn't fit, is said:** a tab on a cone, a hole
  right through its side, a latitude, the face's own u and v, a boss past
  its end, one as wide as the cone where it is, a hole deeper than the cone
  under it.
- **What is built is what was placed.** A boss at 30 degrees, a post at 200
  along the side, a hole, a circle of holes, an arc of posts, a boss at 0
  (leaned only), measured from its end, on a cone standing on the plate,
  on a cone pointing down, on one lying along x on the plate's side, on a
  cone standing on a turned block's side, on a cone widening upwards, on
  one coming to a point; a boss's joint rounded, its rim rounded, a hole's
  mouth bevelled: built by the build loop, every face accounted for both
  ways, every check its spec compiles to passing.
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

_TEXT = "A plate 100 mm long, 60 mm wide and 8 mm thick. A cone on it has a boss, a post and a hole."
#: A cone's own brief, where the cone is the first body.
_CONE = "A cone has a boss, a post and a hole."


def _plate(b: Any) -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 100, "100 mm"),
            "width": mm(b, 60, "60 mm"), "height": mm(b, 8, "8 mm")}  # fmt: skip


def _block(b: Any) -> dict[str, Any]:
    return {"id": "box", "kind": "block", "words": cite(b, "plate"), "on": {"item": "plate", "face": "+z"},
            "length": assumed("long", 50.0), "width": assumed("wide", 40.0), "height": assumed("tall", 10.0),
            "place": {"turn": assumed("turned", 30.0, "deg")}}  # fmt: skip


def _cone(b: Any, base: float = 30.0, top: float = 10.0, length: float = 30.0, on: str | None = None,
          face: str = "+z") -> dict[str, Any]:  # fmt: skip
    found = {"id": "cone", "kind": "cone", "words": cite(b, "cone"), "base_diameter": assumed("base", base),
             "top_diameter": assumed("top", top), "length": assumed("long", length)}  # fmt: skip
    if on is not None:
        found["on"] = {"item": on, "face": face}
    return found


def _on(b: Any, kind: str, angle: float | None = None, along: float | None = None, *, item: str | None = None,
        count: int | None = None, depth: float = 4.0, axis: str = "z", **fields: Any) -> dict[str, Any]:  # fmt: skip
    """A hole, a boss or a post on the cone's side, at ``angle`` round it and ``along`` from its middle."""
    sizes = {"boss": {"diameter": assumed("across", 5.0), "height": assumed("tall", 4.0)},
             "post": {"length": assumed("long", 5.0), "width": assumed("wide", 3.0), "height": assumed("tall", 4.0)},
             "hole": {"diameter": assumed("across", 3.0), "depth": assumed("deep", depth)},
             "tab": {"length": assumed("out", 6.0), "width": assumed("wide", 5.0), "thickness": assumed("thick", 2.0),
                     "thickness_along": {"choose": "x", "from": {"assumed": "across"}},
                     "end": {"choose": "round", "from": {"assumed": "round"}}}}[kind]  # fmt: skip
    place: dict[str, Any] = {}
    if angle is not None:
        place["angle"] = assumed("round", angle, "deg")
    if along is not None:
        place[axis] = {"offset": assumed("along", along)}
    found = {"id": item or kind, "kind": kind, "words": cite(b, "boss" if kind == "tab" else kind),
             "on": {"item": "cone", "face": "side"}, **sizes, **fields}  # fmt: skip
    if count is not None:
        place["pattern"] = {"circle": {"count": {"count": count, "from": {"assumed": "so many"}}}}
        found["count"] = {"count": count, "from": {"assumed": "so many"}}
    if place:
        found["place"] = place
    return found


def _rounding(b: Any, of: str, which: str, kind: str = "fillet", size: float = 0.5, **more: Any) -> dict[str, Any]:
    return {"id": "round", "kind": kind, "words": cite(b, "boss"), ("radius" if kind == "fillet" else "size"):
            assumed("small", size), "edges": {"of": of, "which": which, **more}}  # fmt: skip


def _arc(b: Any) -> dict[str, Any]:
    found = _on(b, "post", 15.0)
    found["count"] = {"count": 3, "from": {"assumed": "so many"}}
    found["place"]["pattern"] = {"arc": {"count": {"count": 3, "from": {"assumed": "so many"}},
                                         "step": assumed("step", 40.0, "deg")}}  # fmt: skip
    return found


def _from_end(b: Any) -> dict[str, Any]:
    found = _on(b, "boss", 30.0)
    found["place"]["z"] = {"side": "+z", "distance": assumed("from the top", 5.0), "to": "edge"}
    return found


#: Each part: its items, the first its first body (a cone, or the plate it stands on).
CASES: dict[str, Any] = {
    "a boss at 30 degrees": lambda b: [_cone(b), _on(b, "boss", 30.0)],
    "a post at 200 along the side": lambda b: [_cone(b), _on(b, "post", 200.0, 5.0)],
    "a hole": lambda b: [_cone(b), _on(b, "hole", 90.0, -4.0)],
    "a circle of holes": lambda b: [_cone(b), _on(b, "hole", 10.0, count=3)],
    "an arc of posts": lambda b: [_cone(b), _arc(b)],
    "a boss at 0, leaned only": lambda b: [_cone(b), _on(b, "boss", 0.0)],
    "measured from its end": lambda b: [_cone(b), _from_end(b)],
    "on a cone standing on the plate": lambda b: [_plate(b), _cone(b, 24.0, 8.0, 25.0, on="plate"),
                                                  _on(b, "boss", 45.0), _on(b, "hole", 160.0, 3.0)],
    "on a cone pointing down": lambda b: [_plate(b), _cone(b, 20.0, 8.0, 15.0, on="plate", face="-z"),
                                          _on(b, "boss", 30.0), _on(b, "hole", 200.0)],
    "on a cone lying along x": lambda b: [_plate(b), _cone(b, 20.0, 6.0, 20.0, on="plate", face="+x"),
                                          _on(b, "boss", 60.0, axis="x"), _on(b, "post", 250.0, axis="x")],
    "on a cone standing on a turned block's side": lambda b: [
        _plate(b), _block(b), {**_cone(b, 16.0, 6.0, 15.0), "on": {"item": "box", "face": "+x"}},
        _on(b, "boss", 30.0, 2.0, axis="x"), _on(b, "hole", 200.0, axis="x")],
    "on a cone widening upwards": lambda b: [_cone(b, 10.0, 30.0), _on(b, "boss", 30.0), _on(b, "hole", 150.0)],
    "on a cone coming to a point": lambda b: [_cone(b, 30.0, 0.0, 30.0), _on(b, "boss", 120.0, -5.0)],
    "a boss's joint rounded": lambda b: [_cone(b), _on(b, "boss", 30.0), _rounding(b, "boss", "joint", where_meets="cone")],
    "its rim rounded": lambda b: [_cone(b), _on(b, "boss", 30.0), _rounding(b, "boss", "top")],
    "a hole's mouth bevelled": lambda b: [_cone(b), _on(b, "hole", 30.0), _rounding(b, "hole", "top", "chamfer", 0.3)],
}


def _report(make: Any) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    items = make(number_words(_TEXT))
    b = number_words(_TEXT if items[0]["id"] == "plate" else _CONE)
    return b, check_draft(b, draft(items[0]["id"], make(b)), strict=False)


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


class PlacedRoundItSquareToTheCone(unittest.TestCase):
    def test_a_hole_and_a_boss(self) -> None:
        _, report = _report(lambda b: [_cone(b), _on(b, "hole", 30.0), _on(b, "boss", 120.0, 3.0)])
        self.assertEqual([p for p in report.problems if p.kind in ("fault", "unable", "cant", "question")], [])
        # The side leans in by its half angle: 10 mm in over its 30 mm, from radius 15 at its foot to 5 at its top.
        q = math.hypot(1.0, 1.0 / 3.0)
        for name, angle, along in (("hole", 30.0, 0.0), ("boss", 120.0, 3.0)):
            (copy,) = report.layout.instances[name]
            c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            r = 10.0 - along / 3.0
            want_point = (r * c, r * s, 15.0 + along)
            want_normal = (c / q, s / q, (1.0 / 3.0) / q)
            for got, want in ((copy.origin, want_point), (copy.normal, want_normal)):
                for g, w in zip(got, want, strict=True):
                    self.assertAlmostEqual(g, w, places=9)
        boss = report.layout.instances["boss"][0]
        assert boss.local is not None  # placed as at 90 degrees, standing out along +y, then leaned and turned
        for got, want in ((boss.local.normal, (0.0, 1.0, 0.0)), (boss.local.origin, (0.0, 9.0, 18.0))):
            for g, w in zip(got, want, strict=True):
                self.assertAlmostEqual(g, w, places=9)

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, make in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


class WhatIsntBuiltYetOrDoesntFitIsSaid(unittest.TestCase):
    def test_each(self) -> None:
        through = {"through": True, "from": {"assumed": "through"}}
        for make, kind, words in (
            (lambda b: [_cone(b), _on(b, "tab", 30.0)], "unable", "Forge cuts round holes and stands bosses and posts"),
            (lambda b: [_cone(b), {**_on(b, "hole", 30.0), "depth": through}], "unable", "blind hole into a cone's side"),
            (lambda b: [_cone(b), {**_on(b, "boss"), "place": {"latitude": assumed("up", 30.0, "deg")}}], "fault",
             "a latitude places on a ball's surface"),
            (lambda b: [_cone(b), {**_on(b, "boss"), "place": {"u": {"offset": assumed("o", 2.0)}}}], "fault",
             "u and v name a flat face's own axes"),
            (lambda b: [_cone(b), _on(b, "boss", 30.0, 13.0)], ("question", "fault"), "runs past the end"),
            (lambda b: [_cone(b, 30.0, 4.0), _on(b, "boss", 30.0, 12.0, diameter=assumed("across", 6.0))],
             ("question", "fault"), "is as wide as the side of cone"),
            (lambda b: [_cone(b), _on(b, "hole", 30.0, 0.0, depth=40.0)], ("question", "fault"), "of material"),
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

        for name in ("a boss at 30 degrees", "a boss at 0, leaned only", "on a cone lying along x"):
            with self.subTest(name), mock.patch.object(moved, "transform_params", more):
                built, accounting, _ = _judged(CASES[name])
                self.assertIsNone(built.gap)
                self.assertIs(accounting.verdict, Verdict.FAIL)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_on_a_cone(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("a boss at 30 degrees", "a circle of holes", "on a cone standing on the plate",
                     "on a cone lying along x", "a boss's joint rounded"):  # fmt: skip
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
