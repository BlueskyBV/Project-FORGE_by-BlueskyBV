"""A hexagonal pocket: a nut trap (pocket.md; schema 1.9).

- **Its outline:** a regular hexagon ``across_flats`` between each two
  opposite sides, two of its corners on the face's first axis; placed by
  its centre or by its edge (a corner along the first axis, a flat along
  the second), turned in the face as a rectangle is; its floor a face of
  its own, the hexagon. Below schema 1.9 it is a fault.
- **Every program's layout agrees.**
- **What is built is what was placed:** each part built by the build loop,
  every face accounted for both ways, every check its spec compiles to
  passing; across its flats held between each pair of opposite sides, its
  place along its corners' axis from where its sides meet.
- **A wrong hexagon is caught:** one moved 0.3 mm either way, turned five
  degrees, or 0.2 mm smaller across its flats fails the judge.
- **Through the next face:** out of a plate and the boss under it, as the
  preview finds, turned or not.
- **The second kernel agrees** with the exact part.
- **The words, the views and the comparison say it:** a hexagonal pocket,
  across its flats; a draft with a rectangle of its box instead is another
  part.
- **The generator draws it:** blind, right through, turned, its rims
  rounded or bevelled, its floor's edge rounded, as its own shape; its
  draft says 1.9.
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

_TEXT = "A plate with a hexagonal nut trap and a pocket."
_ROOT3 = math.sqrt(3.0)


def _plate(b: Any) -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": assumed("long", 60.0),
            "width": assumed("wide", 40.0), "height": assumed("thick", 10.0)}  # fmt: skip


def _trap(b: Any, flats: float = 5.5, depth: float | None = 3.0, *, turn: float | None = None,
          place: dict[str, Any] | None = None, count: int | None = None) -> dict[str, Any]:  # fmt: skip
    found: dict[str, Any] = {"id": "trap", "kind": "pocket", "words": cite(b, "nut"),
                             "on": {"item": "plate", "face": "+z"},
                             "shape": {"choose": "hexagon", "from": {"assumed": "a nut's"}},
                             "across_flats": assumed("an M3 nut's", flats)}  # fmt: skip
    found["depth"] = {"through": True, "from": {"assumed": "through"}} if depth is None else assumed("deep", depth)
    where: dict[str, Any] = dict(place or {})
    if turn is not None:
        where["turn"] = assumed("turned", turn, "deg")
    if count is not None:
        many = {"count": count, "from": {"assumed": "a row"}}
        where["pattern"] = {"row": {"count": many, "axis": {"choose": "x", "from": {"assumed": "a row"}},
                                    "pitch": assumed("apart", 12.0)}}  # fmt: skip
        found["count"] = many
    if where:
        found["place"] = where
    return found


def _edge(b: Any, which: str, kind: str = "fillet", size: float = 0.5) -> dict[str, Any]:
    return {"id": "eased", "kind": kind, "words": cite(b, "nut"), "edges": {"of": "trap", "which": which},
            "radius" if kind == "fillet" else "size": assumed("eased", size)}  # fmt: skip


def _near(axis: str, side: str, distance: float, to: str = "edge") -> dict[str, Any]:
    return {axis: {"side": side, "distance": assumed("near", distance), "to": to}}


#: Each part: a plate and its hexagonal pocket.
CASES: dict[str, Any] = {
    "a nut trap": lambda b: [_plate(b), _trap(b)],
    "turned 20 degrees": lambda b: [_plate(b), _trap(b, turn=20.0)],
    "right through": lambda b: [_plate(b), _trap(b, depth=None)],
    "a row of three": lambda b: [_plate(b), _trap(b, count=3)],
    "near two edges": lambda b: [_plate(b), _trap(b, place={**_near("x", "-x", 2.0), **_near("y", "+y", 1.5)})],
    "its rim rounded": lambda b: [_plate(b), _trap(b), _edge(b, "top")],
    "its rim bevelled": lambda b: [_plate(b), _trap(b), _edge(b, "top", "chamfer", 0.4)],
    "its floor's edge rounded": lambda b: [_plate(b), _trap(b), _edge(b, "bottom")],
}


def _report(make: Any, version: str = "1.9") -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    brief = number_words(_TEXT)
    items = make(brief)
    found = draft(items[0]["id"], items)
    found["schema_version"] = version
    return check_draft(brief, found, strict=False)


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


class ItsOutline(unittest.TestCase):
    def test_where_it_goes_and_its_floor(self) -> None:
        from forge_spec.geometry import FlatFace

        report = _report(CASES["a nut trap"])
        self.assertEqual(report.problems, ())
        (copy,) = report.layout.instances["trap"]
        self.assertEqual(copy.origin, (0.0, 0.0, 10.0))
        floor = report.layout.faces[("trap", 0)]["bottom"]
        assert isinstance(floor, FlatFace) and floor.profile is not None
        self.assertEqual((floor.shape, floor.centre, floor.depth_below), ("profile", (0.0, 0.0, 7.0), 7.0))
        corners = [q.a for q in floor.profile.pieces]
        self.assertEqual(len(corners), 6)
        self.assertAlmostEqual(corners[0][0], 5.5 / _ROOT3, places=12)
        self.assertEqual(corners[0][1], 0.0)
        self.assertEqual({round(abs(c[1]), 12) for c in corners}, {0.0, 2.75})

    def test_by_its_edge_a_corner_or_a_flat(self) -> None:
        # 2 mm in from -x to its corner, 1.5 mm in from +y to its flat.
        (copy,) = _report(CASES["near two edges"]).layout.instances["trap"]
        self.assertAlmostEqual(copy.origin[0], -30.0 + 2.0 + 5.5 / _ROOT3, places=12)
        self.assertAlmostEqual(copy.origin[1], 20.0 - 1.5 - 2.75, places=12)

    def test_off_its_face_or_before_1_9(self) -> None:
        off = _report(lambda b: [_plate(b), _trap(b, place=_near("x", "-x", 2.0, "centre"))])
        self.assertTrue(any("trap copy 1 runs off face +z" in p.message for p in off.problems),
                        [p.message for p in off.problems])  # fmt: skip
        early = _report(CASES["a nut trap"], "1.8")
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

    def test_through_the_next_face(self) -> None:
        # Out of the plate and the boss under it, as the preview finds; turned too.
        from forge_checks.classes import Verdict
        from forge_plan import plan
        from forge_spec.checks import check_draft
        from forge_spec.lock import lock
        from forge_spec.words import number_words
        from test_v2_plan_build import judged_plan
        from v2_exit4 import resolved

        def boss(b: Any) -> dict[str, Any]:
            return {"id": "boss", "kind": "boss", "words": cite(b, "plate"), "on": {"item": "plate", "face": "-z"},
                    "diameter": assumed("round", 16.0), "height": assumed("tall", 6.0)}  # fmt: skip

        def out(b: Any, turn: float | None) -> dict[str, Any]:
            return {**_trap(b, turn=turn), "depth": {"through_next": True, "from": {"assumed": "out"}}}

        brief = number_words(_TEXT)
        for turn in (None, 10.0):
            with self.subTest(turn=turn):
                found = draft("plate", [_plate(brief), boss(brief), out(brief, turn)])
                found["schema_version"] = "1.9"
                report = check_draft(brief, resolved(found), strict=False)
                self.assertEqual(report.problems, ())
                spec = lock(report, brief, by="draft", strict=False)
                (copy,) = report.layout.instances["trap"]
                self.assertAlmostEqual(copy.depth, 16.0, places=6)  # the plate's 10 and the boss's 6
                built, accounting, failed = judged_plan(spec.spec, plan(spec))
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_its_checks(self) -> None:
        from forge_checks.compiler import compile_checks
        from forge_checks.oracle import oracle
        from forge_checks.place import place

        for name, copies, held in (("a nut trap", 1, {"across_flats", "depth", "place.x", "place.y"}),
                                   ("a row of three", 3, {"across_flats", "place.pattern.row.pitch",
                                                          "place.pattern.row.count", "count"})):  # fmt: skip
            with self.subTest(name):
                spec, _ = _planned(CASES[name])
                placed = place(spec.spec)
                suite = compile_checks(spec.spec, placed, oracle(spec.spec, placed))
                found = {c.id.split("/")[1] for c in suite.checks if c.id.startswith("trap/")}
                self.assertLessEqual(held, found)
                # Across its flats between each of its three pairs of opposite sides, on each copy.
                flats = [c for c in suite.checks if c.id.startswith("trap/across_flats/")]
                self.assertEqual(len(flats), 3 * copies)
                self.assertEqual([u.field for u in suite.unchecked if u.item == "trap" and u.held_by is None], [])


@needs_occ
class AWrongHexagonIsCaught(unittest.TestCase):
    def test_moved_turned_or_smaller(self) -> None:
        from unittest import mock

        import forge_plan.tools as tools
        from forge_checks.classes import Verdict
        from forge_spec.outline import Shape
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
                             ("turned 5 degrees", lambda q: q.turned(c, s)),
                             ("0.2 mm smaller", lambda q: Shape.hexagon((0.0, 0.0), 5.3))):  # fmt: skip
            for case in ("a nut trap", "near two edges"):
                with self.subTest(name, case=case), mock.patch.object(tools, "turned_on", wrong(change)):
                    spec, planned = _planned(CASES[case])
                    built, accounting, failed = judged_plan(spec.spec, planned)
                    self.assertIsNone(built.gap)
                    self.assertTrue(accounting.verdict is Verdict.FAIL or failed, failed)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_a_nut_trap(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("a nut trap", "turned 20 degrees", "right through"):
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


class TheWordsViewsAndComparisonSayIt(unittest.TestCase):
    def test_words_and_views(self) -> None:
        from forge_spec.render import render
        from forge_spec.render_views import render_views
        from forge_spec.words import number_words
        from test_v2_spec_views import check_every_value_shown

        for name in ("a nut trap", "turned 20 degrees", "a row of three"):
            with self.subTest(name):
                report = _report(CASES[name])
                (line,) = [x for x in render(report, number_words(_TEXT)).lines if "trap" in x]
                self.assertIn("hexagonal pocket trap", line.lower())
                self.assertIn("5.5 mm (assumed) across its flats", line)
                check_every_value_shown(self, report, render_views(report), name)

    def test_a_rectangle_of_its_box_is_another_part(self) -> None:
        from forge_spec.compare import differences

        def box(b: Any) -> dict[str, Any]:
            found = _trap(b)
            del found["across_flats"]
            found.update(shape={"choose": "rectangle", "from": {"assumed": "r"}},
                         length=assumed("long", 11.0 / _ROOT3), width=assumed("wide", 5.5))  # fmt: skip
            return found

        same = _report(CASES["a nut trap"])
        self.assertEqual(differences(same, _report(CASES["a nut trap"])), ())
        self.assertEqual(differences(same, _report(lambda b: [_plate(b), _trap(b, turn=60.0)])), ())
        self.assertNotEqual(differences(same, _report(lambda b: [_plate(b), box(b)])), ())
        self.assertNotEqual(differences(same, _report(lambda b: [_plate(b), _trap(b, 5.0)])), ())
        self.assertNotEqual(differences(same, _report(CASES["turned 20 degrees"])), ())


class TheGeneratorDrawsIt(unittest.TestCase):
    def _plans(self) -> dict[str, Any]:
        from forge_eval.generator import Feature, Position

        plate = Feature("body", "block", {"length": 60.0, "width": 40.0, "height": 10.0})

        def trap(depth: float | None, turn: float | None = None) -> Any:
            return Feature("i0", "pocket", {"across_flats": 5.5}, ("body", "+z"), depth, {"shape": "hexagon"}, None,
                           {"x": Position("offset", 6.0)}, turn=turn)  # fmt: skip

        def edge(which: str, kind: str = "fillet", size: float = 0.5) -> Any:
            return Feature("i1", kind, {"radius" if kind == "fillet" else "size": size}, of="i0",
                           choices={"which": which})  # fmt: skip

        return {"blind": [plate, trap(3.0)], "right through": [plate, trap(None)], "turned": [plate, trap(3.0, 20.0)],
                "its rim rounded": [plate, trap(3.0), edge("top")],
                "its rim bevelled": [plate, trap(3.0), edge("top", "chamfer", 0.4)],
                "its floor's edge rounded": [plate, trap(3.0), edge("bottom")],
                "turned, its rim rounded": [plate, trap(3.0, 20.0), edge("top")]}  # fmt: skip

    def test_its_draft_and_brief(self) -> None:
        from forge_eval.generator import draft_of, render

        case = render(self._plans()["blind"])
        self.assertEqual(draft_of(case.items)["schema_version"], "1.9")
        self.assertIn("a hexagonal pocket 5.5 mm across its flats", case.brief)

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
