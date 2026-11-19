"""A pocket of its own outline: a D-shaped hole, a window of any outline (pocket.md; schema 1.9).

- **Its outline:** a closed outline of lines and arcs, as an extrusion's,
  along the face's axes from the point ``place`` puts it at (which may lie
  off it); placed by that point, or measured to its edge by the box round
  it; turned in the face about that point; in a pattern; its floor a face
  of its own. Below schema 1.9 it is a fault; its edges aren't rounded or
  bevelled yet (said).
- **Every program's layout agrees.**
- **What is built is what was placed:** each part built by the build loop,
  every face accounted for both ways, every check its spec compiles to
  passing; its depth held, its outline and its place by face accounting.
- **A wrong one is caught:** moved 0.3 mm either way or turned five
  degrees, the judge fails it.
- **The second kernel agrees** with the exact part.
- **The words, the views and the comparison say it.**
- **The generator draws it:** an L, a T, a stadium, a plate's corner,
  blind or right through, as its own shape; its draft says 1.9.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, cite, draft
from v2_occ import needs_occ

_TEXT = "A plate with a D-shaped hole and an L-shaped pocket."


def _plate(b: Any) -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": assumed("long", 60.0),
            "width": assumed("wide", 40.0), "height": assumed("thick", 10.0)}  # fmt: skip


#: A shaft's D-shaped hole (5 mm, its flat 2 mm from its centre), an L, and a U whose notch is an arc.
_D: dict[str, Any] = {"start": [1.5, 2.0], "segments": [{"line_to": [-1.5, 2.0]},
                                                        {"arc_to": [1.5, 2.0], "centre": [0.0, 0.0]}]}  # fmt: skip
_L: dict[str, Any] = {"start": [0.0, 0.0], "segments": [{"line_to": [10.0, 0.0]}, {"line_to": [10.0, 3.0]},
                                                        {"line_to": [3.0, 3.0]}, {"line_to": [3.0, 8.0]},
                                                        {"line_to": [0.0, 8.0]}, {"line_to": [0.0, 0.0]}]}  # fmt: skip
_U: dict[str, Any] = {"start": [-6.0, -4.0], "segments": [{"line_to": [6.0, -4.0]}, {"line_to": [6.0, 4.0]},
                                                          {"line_to": [3.0, 4.0]},
                                                          {"arc_to": [-3.0, 4.0], "centre": [0.0, 4.0], "clockwise": True},
                                                          {"line_to": [-6.0, 4.0]}, {"line_to": [-6.0, -4.0]}]}  # fmt: skip


def _cutout(b: Any, outline: dict[str, Any], depth: float | None = 3.0, *, turn: float | None = None,
            place: dict[str, Any] | None = None, count: int | None = None) -> dict[str, Any]:  # fmt: skip
    found: dict[str, Any] = {"id": "cut", "kind": "pocket", "words": cite(b, "pocket"),
                             "on": {"item": "plate", "face": "+z"},
                             "shape": {"choose": "profile", "from": {"assumed": "as drawn"}},
                             "profile": {**outline, "unit": "mm", "from": {"assumed": "as drawn"}}}  # fmt: skip
    found["depth"] = {"through": True, "from": {"assumed": "through"}} if depth is None else assumed("deep", depth)
    where: dict[str, Any] = dict(place or {})
    if turn is not None:
        where["turn"] = assumed("turned", turn, "deg")
    if count is not None:
        many = {"count": count, "from": {"assumed": "a row"}}
        where["pattern"] = {"row": {"count": many, "axis": {"choose": "x", "from": {"assumed": "a row"}},
                                    "pitch": assumed("apart", 15.0)}}  # fmt: skip
        found["count"] = many
    if where:
        found["place"] = where
    return found


def _report(make: Any, version: str = "1.9") -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    brief = number_words(_TEXT)
    found = draft("plate", make(brief))
    found["schema_version"] = version
    return check_draft(brief, found, strict=False)


def _planned(make: Any) -> tuple[Any, Any]:
    from forge_plan import plan
    from forge_spec.lock import lock
    from forge_spec.words import number_words

    report = _report(make)
    assert not report.problems, [p.message for p in report.problems]
    spec = lock(report, number_words(_TEXT), by="draft", strict=False)
    planned = plan(spec)
    assert not planned.gaps, [g.reason for g in planned.gaps]
    return spec, planned


#: 2 mm from the face's -x edge to the box round its outline.
_EDGE: dict[str, Any] = {"x": {"side": "-x", "distance": assumed("in", 2.0), "to": "edge"}}

#: Each part: a plate and its pocket of its own outline.
CASES: dict[str, Any] = {
    "D blind": lambda b: [_plate(b), _cutout(b, _D)],
    "D through": lambda b: [_plate(b), _cutout(b, _D, None)],
    "L blind": lambda b: [_plate(b), _cutout(b, _L)],
    "L turned": lambda b: [_plate(b), _cutout(b, _L, turn=25.0)],
    "U through": lambda b: [_plate(b), _cutout(b, _U, None)],
    "U blind": lambda b: [_plate(b), _cutout(b, _U)],
    "D row": lambda b: [_plate(b), _cutout(b, _D, None, count=3)],
    "L edge": lambda b: [_plate(b), _cutout(b, _L, place=_EDGE)],
}


class ItsOutline(unittest.TestCase):
    def test_where_it_goes_and_its_floor(self) -> None:
        from forge_spec.geometry import FlatFace

        report = _report(CASES["L blind"])
        self.assertEqual(report.problems, ())
        (copy,) = report.layout.instances["cut"]
        self.assertEqual(copy.origin, (0.0, 0.0, 10.0))  # its point (0, 0), centred
        floor = report.layout.faces[("cut", 0)]["bottom"]
        assert isinstance(floor, FlatFace)
        self.assertEqual((floor.shape, floor.centre, floor.half), ("profile", (5.0, 4.0, 7.0), (5.0, 4.0)))
        # By its edge: 2 mm from -x to the box round it, whose low side is its point's.
        (copy,) = _report(CASES["L edge"]).layout.instances["cut"]
        self.assertEqual(copy.origin[0], -28.0)

    def test_what_isnt_yet_or_before_1_9(self) -> None:
        def rounded(b: Any) -> dict[str, Any]:
            return {"id": "eased", "kind": "fillet", "words": cite(b, "pocket"),
                    "edges": {"of": "cut", "which": "top"}, "radius": assumed("eased", 0.5)}  # fmt: skip

        report = _report(lambda b: [_plate(b), _cutout(b, _D), rounded(b)])
        self.assertEqual([p.kind for p in report.problems], ["unable"])
        early = _report(CASES["D blind"], "1.8")
        self.assertTrue(any("schema 1.9" in p.message for p in early.problems), [p.message for p in early.problems])

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
        from test_v2_plan_build import judged_plan

        for name, make in CASES.items():
            with self.subTest(name):
                spec, planned = _planned(make)
                built, accounting, failed = judged_plan(spec.spec, planned)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_its_checks(self) -> None:
        from forge_checks.compiler import compile_checks
        from forge_checks.oracle import oracle
        from forge_checks.place import place

        for name in ("D blind", "U through", "D row", "L edge"):
            with self.subTest(name):
                spec, _ = _planned(CASES[name])
                placed = place(spec.spec)
                suite = compile_checks(spec.spec, placed, oracle(spec.spec, placed))
                self.assertIn("depth", {c.id.split("/")[1] for c in suite.checks if c.id.startswith("cut/")})
                held = {u.field: u.held_by for u in suite.unchecked if u.item == "cut"}
                self.assertEqual(held.get("profile"), "face accounting")
                self.assertTrue(all(by == "face accounting" for by in held.values()), held)


@needs_occ
class AWrongOneIsCaught(unittest.TestCase):
    def test_moved_or_turned(self) -> None:
        from unittest import mock

        import forge_plan.tools as tools
        from forge_checks.classes import Verdict
        from test_v2_plan_build import judged_plan

        real = tools.turned_on

        def wrong(change: Any) -> Any:
            def outline(layout: Any, item: Any, face: Any) -> Any:
                shape = real(layout, item, face)
                return None if shape is None else change(shape)

            return outline

        c, s = math.cos(math.radians(5.0)), math.sin(math.radians(5.0))
        for name, change in (("0.3 mm along x", lambda q: q.moved(0.3, 0.0)),
                             ("0.3 mm along y", lambda q: q.moved(0.0, 0.3)),
                             ("turned 5 degrees", lambda q: q.turned(c, s))):  # fmt: skip
            for case in ("D blind", "U through"):
                with self.subTest(name, case=case), mock.patch.object(tools, "turned_on", wrong(change)):
                    spec, planned = _planned(CASES[case])
                    built, accounting, failed = judged_plan(spec.spec, planned)
                    self.assertIsNone(built.gap)
                    self.assertTrue(accounting.verdict is Verdict.FAIL or failed, failed)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_each(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("D blind", "U through", "L turned"):
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


class TheWordsViewsAndComparisonSayIt(unittest.TestCase):
    def test_each(self) -> None:
        from forge_spec.compare import differences
        from forge_spec.render import render
        from forge_spec.render_views import render_views
        from forge_spec.words import number_words
        from test_v2_spec_views import check_every_value_shown

        for name in ("D blind", "L turned", "D row"):
            with self.subTest(name):
                report = _report(CASES[name])
                (line,) = [x for x in render(report, number_words(_TEXT)).lines if "cut" in x]
                self.assertIn("pocket cut of its own outline", line.lower())
                check_every_value_shown(self, report, render_views(report), name)
        self.assertEqual(differences(_report(CASES["D blind"]), _report(CASES["D blind"])), ())
        self.assertNotEqual(differences(_report(CASES["D blind"]), _report(CASES["L blind"])), ())


class TheGeneratorDrawsIt(unittest.TestCase):
    def _plans(self) -> dict[str, Any]:
        from forge_eval.generator import Feature, Position

        plate = Feature("body", "block", {"length": 60.0, "width": 40.0, "height": 10.0})

        def cut(shape: str, values: dict[str, float], depth: float | None) -> Any:
            return Feature("i0", "pocket", {}, ("body", "+z"), depth, {"shape": "profile"}, None,
                           {"x": Position("offset", -6.0)}, outline=(shape, tuple(values.items())))  # fmt: skip

        return {"an L, blind": [plate, cut("L", {"a": 12.0, "b": 9.0, "t": 3.0}, 3.0)],
                "a T, right through": [plate, cut("T", {"w": 12.0, "h": 9.0, "t": 3.0, "s": 4.0}, None)],
                "a stadium": [plate, cut("stadium", {"l": 14.0, "w": 6.0}, 4.0)],
                "a plate's corner, right through": [plate, cut("corner", {"a": 12.0, "b": 9.0, "r": 2.0, "c": 2.5},
                                                                None)]}  # fmt: skip

    def test_its_draft_and_brief(self) -> None:
        from forge_eval.generator import draft_of, render

        case = render(self._plans()["an L, blind"])
        self.assertEqual(draft_of(case.items)["schema_version"], "1.9")
        self.assertIn("a shaped pocket 3 mm deep of an L-shaped outline drawn with this brief", case.brief)

    @needs_occ
    def test_its_own_shape(self) -> None:
        from forge_eval.generator import render
        from v2_exit4 import _built, _graded, _spec

        for name, plan in self._plans().items():
            with self.subTest(name):
                case = render(plan)
                _, built = _built(_spec(case.items))
                self.assertIsNone(built.gap, built.refusals)
                self.assertEqual(_graded(built.result.shape, case.truth, 0), [])


if __name__ == "__main__":
    unittest.main()
