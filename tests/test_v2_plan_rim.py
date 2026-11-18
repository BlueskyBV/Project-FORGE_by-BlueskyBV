"""The rim of an open hollow (shell.md, "The rim"; V2-stage4b-0c.md, 3.3).

- **A ring or a frame round the hollow's mouth:** a cylinder a shell leaves
  open at an end keeps that end as a ring, its outer radius the cylinder's
  and its inner the hollow's; a block's open face a frame, its walls'
  thickness in from its edges, where the four walls round it are there;
  the wall under it all the way down (and what it stands on, under that).
  A hole, a circle of them or a boss goes on it; one reaching into the
  mouth runs off it.
- **Every program's layout agrees.**
- **What is built is what was placed:** a cup's rim with a blind hole, one
  right through its wall and out of its foot, a circle of them, a boss;
  a cylinder standing on the plate, hollowed open at its top, a hole into
  its rim as deep as its wall and the plate; an open box's rim, a blind hole
  and one right through a wall and the plate: each built by the build loop,
  every face accounted for both ways, every check its spec compiles to
  passing.
- **The second kernel agrees** with the exact part.
- **The generator draws it:** an open cylinder's rim a ring, a cut through
  it coming out on its other end, built as its own shape.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, cite, draft
from v2_occ import needs_occ

_TEXT = "A cup or a box, hollow and open at its top, its walls thick, on a plate, with a hole and a boss."


def _cup(b: Any, on: str | None = None) -> dict[str, Any]:
    found = {"id": "cup", "kind": "cylinder", "words": cite(b, "cup"), "diameter": assumed("across", 40.0),
             "length": assumed("tall", 30.0)}  # fmt: skip
    if on is not None:
        found["on"] = {"item": on, "face": "+z"}
    return found


def _plate(b: Any) -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": assumed("long", 100.0),
            "width": assumed("wide", 60.0), "height": assumed("thick", 8.0)}  # fmt: skip


def _shell(b: Any) -> dict[str, Any]:
    return {"id": "hollow", "kind": "shell", "words": cite(b, "walls"), "of": "cup", "thickness": assumed("thick", 4.0),
            "open": {"faces": ["+end"], "from": {"assumed": "open at its top"}}}  # fmt: skip


def _hole(b: Any, x: float = 18.0, depth: float | None = 5.0, d: float = 2.0, **more: Any) -> dict[str, Any]:
    found = {"id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "cup", "face": "+end"},
             "diameter": assumed("across", d), "place": {"x": {"offset": assumed("out", x)}}, **more}  # fmt: skip
    found["depth"] = {"through": True, "from": {"assumed": "through"}} if depth is None else assumed("deep", depth)
    return found


def _box(b: Any) -> dict[str, Any]:
    return {"id": "cup", "kind": "block", "words": cite(b, "box"), "on": {"item": "plate", "face": "+z"},
            "length": assumed("long", 30.0), "width": assumed("wide", 20.0), "height": assumed("tall", 12.0)}  # fmt: skip


def _box_shell(b: Any, opened: tuple[str, ...] = ("+z",)) -> dict[str, Any]:
    return {**_shell(b), "open": {"faces": list(opened), "from": {"assumed": "open at its top"}}}


def _on_box(b: Any, x: float, y: float, depth: float | None = 5.0, d: float = 2.0) -> dict[str, Any]:
    found = _hole(b, depth=depth, d=d)
    return {**found, "on": {"item": "cup", "face": "+z"},
            "place": {"x": {"offset": assumed("out", x)}, "y": {"offset": assumed("out", y)}}}  # fmt: skip


def _circle(b: Any) -> dict[str, Any]:
    many = {"count": 4, "from": {"assumed": "four"}}
    return {"id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "cup", "face": "+end"},
            "diameter": assumed("across", 2.0), "depth": assumed("deep", 6.0), "count": many,
            "place": {"pattern": {"circle": {"count": many, "diameter": assumed("round", 36.0)}}}}  # fmt: skip


def _boss(b: Any) -> dict[str, Any]:
    return {"id": "boss", "kind": "boss", "words": cite(b, "boss"), "on": {"item": "cup", "face": "+end"},
            "diameter": assumed("across", 3.0), "height": assumed("tall", 2.0),
            "place": {"y": {"offset": assumed("out", -18.0)}}}  # fmt: skip


#: Each part: the cup (on its own, or standing on the plate), hollowed open at its top, and what is on its rim.
CASES: dict[str, Any] = {
    "a blind hole": lambda b: [_cup(b), _shell(b), _hole(b)],
    "a hole right through its wall": lambda b: [_cup(b), _shell(b), _hole(b, depth=None)],
    "a circle of holes": lambda b: [_cup(b), _shell(b), _circle(b)],
    "a boss": lambda b: [_cup(b), _shell(b), _boss(b)],
    "standing on the plate, a hole into its wall and the plate": lambda b: [_plate(b), _cup(b, "plate"), _shell(b),
                                                                            _hole(b, depth=36.0)],
    "an open box's rim, a blind hole": lambda b: [_plate(b), _box(b), _box_shell(b), _on_box(b, 13.0, 0.0)],
    "an open box's rim, right through a wall and the plate": lambda b: [_plate(b), _box(b), _box_shell(b),
                                                                         _on_box(b, 0.0, 8.0, None)],
}  # fmt: skip


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


class ARingRoundTheHollowsMouth(unittest.TestCase):
    def test_its_face(self) -> None:
        report = _report(CASES["a blind hole"])
        self.assertEqual(report.problems, ())
        rim = report.layout.faces[("cup", 0)]["+end"]
        self.assertEqual((rim.shape, rim.half, rim.inner_radius, rim.depth_below), ("annulus", (20.0, 20.0), 16.0, 30.0))
        box = _report(CASES["an open box's rim, a blind hole"]).layout.faces[("cup", 0)]["+z"]
        self.assertEqual((box.shape, box.half, box.depth_below), ("profile", (15.0, 10.0), 12.0 + 8.0))
        assert box.profile is not None
        self.assertAlmostEqual(box.profile.area(), 30.0 * 20.0 - 22.0 * 12.0, places=9)
        standing = _report(CASES["standing on the plate, a hole into its wall and the plate"])
        self.assertEqual(standing.problems, ())
        self.assertEqual(standing.layout.faces[("cup", 0)]["+end"].depth_below, 30.0 + 8.0)

    def test_deeper_than_its_wall_is_asked_about_and_into_its_mouth_runs_off_it(self) -> None:
        deep = _report(lambda b: [_cup(b), _shell(b), _hole(b, depth=31.0)])
        self.assertTrue(any("31 mm deep in 30 mm of material" in p.message for p in deep.problems),
                        [p.message for p in deep.problems])  # fmt: skip
        mouth = _report(lambda b: [_cup(b), _shell(b), _hole(b, x=16.5)])
        self.assertTrue(any("breaks into the hole in the middle of face +end" in p.message for p in mouth.problems),
                        [p.message for p in mouth.problems])  # fmt: skip
        for make in (lambda b: [_plate(b), _box(b), _box_shell(b), _on_box(b, 11.5, 0.0)],
                     lambda b: [_plate(b), _box(b), _box_shell(b), _on_box(b, 0.0, 0.0, d=25.0)]):  # fmt: skip
            report = _report(make)
            self.assertTrue(any("runs past the edge of face +z" in p.message for p in report.problems),
                            [p.message for p in report.problems])  # fmt: skip
        deeper = _report(lambda b: [_plate(b), _box(b), _box_shell(b), _on_box(b, 13.0, 0.0, 21.0)])
        self.assertTrue(any("21 mm deep in 20 mm of material" in p.message for p in deeper.problems))

    def test_a_box_open_on_a_side_too_takes_nothing_on_its_rim_yet(self) -> None:
        report = _report(lambda b: [_plate(b), _box(b), _box_shell(b, ("+z", "+x")), _on_box(b, -13.0, 0.0)])
        self.assertTrue(any("rim of an open hollow yet" in p.message for p in report.problems))

    def test_right_through_its_wall_as_deep_as_it(self) -> None:
        report = _report(CASES["a hole right through its wall"])
        self.assertEqual(report.problems, ())

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


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_a_rim(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("a hole right through its wall", "a boss"):
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


class TheGeneratorDrawsIt(unittest.TestCase):
    def _plans(self) -> list[Any]:
        from forge_eval.generator import Feature, Position

        cup = Feature("body", "cylinder", {"diameter": 40.0, "length": 30.0})
        shell = Feature("hollow", "shell", {"thickness": 4.0}, of="body", faces=("+end",))
        out = {"x": Position("offset", 18.0)}
        return [(cup, shell, Feature("i0", "hole", {"diameter": 2.0}, ("body", "+end"), depth, place=out))
                for depth in (5.0, None)]  # fmt: skip

    def test_its_rim_a_ring(self) -> None:
        from forge_eval.generator import _build

        rim = _build(self._plans()[0][:2], True).flats[("body", 0, "+end")]
        self.assertEqual((rim.shape, rim.half, rim.inner, rim.material, rim.exit),
                         ("ring", (20.0, 20.0), 16.0, 30.0, ("body", 0, "-end")))  # fmt: skip

    @needs_occ
    def test_its_own_shape(self) -> None:
        from forge_eval.generator import render
        from v2_exit4 import _built, _graded, _spec

        for plan in self._plans():
            with self.subTest(depth=plan[2].depth):
                case = render(plan)
                _, built = _built(_spec(case.items))
                self.assertIsNone(built.gap, built.refusals)
                self.assertEqual(_graded(built.result.shape, case.truth, 0), [])


if __name__ == "__main__":
    unittest.main()
