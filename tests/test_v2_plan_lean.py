"""Items leaning from square to their flat face, planned, built and judged (tilt; V2-stage4b-0c.md, 3.3, 1b's second
move; place.md, "Leaning on the face").

- **What is built is what was placed.** A leaning hole (right through, blind,
  counterbored, measured to its edge, in a row), boss or post (turned too) is
  its solid run along its direction, kept within the face's material or on
  its open side; built by the build loop, every face of it is accounted for
  both ways and every check its spec compiles to passes, on every face of a
  cube and leaning either way.
- **A wrong lean is caught.** The same plan leaning half a degree more, or
  the other way, fails the judge's face accounting.
- **The second kernel agrees** with the exact part, point by point, the
  post's rigid motion included.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, cite, draft, mm, said
from v2_occ import needs_occ

_PLATE = "A plate 100 mm long, 60 mm wide and 8 mm thick. "
_CUBE = "A cube 60 mm long, 60 mm wide and 60 mm tall. "

HOLE = "A hole 6 mm across goes through it."
BLIND = "A hole 6 mm across and 4 mm deep."
BORED = "A hole 6 mm across goes through it, counterbored 11 mm across and 3 mm deep."
EDGE = "A hole 6 mm across goes through it, 4 mm from the -x edge."
ROW = "Two holes 6 mm across, 30 mm apart, go through it."
BOSS = "A boss 10 mm across and 12 mm tall stands on it."
POST = "A post 6 mm long, 4 mm wide and 10 mm tall stands on it."
#: Its sizes each said once beside a hole's and a boss's.
POST2 = "A post 7 mm long, 5 mm wide and 9 mm tall stands on it."
#: Thin along its lean, wide across it (generated part 209).
POST3 = "A post 3.5 mm long, 20 mm wide and 10 mm tall stands on it."


def _lean(degrees: float, way: str) -> dict[str, Any]:
    return {"tilt": assumed("leaning", degrees, "deg"), "tilt_towards": {"choose": way, "from": {"assumed": "that way"}}}


def _body(brief: Any, cube: bool) -> dict[str, Any]:
    if cube:
        return {"id": "plate", "kind": "block", "words": cite(brief, "cube"), "length": mm(brief, 60, "60 mm"),
                "width": mm(brief, 60, "60 mm", 2), "height": mm(brief, 60, "60 mm", 3)}  # fmt: skip
    return {"id": "plate", "kind": "block", "words": cite(brief, "plate"), "length": mm(brief, 100, "100 mm"),
            "width": mm(brief, 60, "60 mm"), "height": mm(brief, 8, "8 mm")}  # fmt: skip


def _hole(brief: Any, degrees: float, way: str = "+x", *, face: str = "+z", **fields: Any) -> dict[str, Any]:
    found = {"id": "hole", "kind": "hole", "words": cite(brief, "holes" if "holes" in brief.text else "hole"),
             "on": {"item": "plate", "face": face}, "diameter": mm(brief, 6, "6 mm"), **_lean(degrees, way)}  # fmt: skip
    if "deep" in brief.text and "counterbored" not in brief.text:
        found["depth"] = mm(brief, 4, "4 mm")
    else:
        found["depth"] = {"through": True, "from": said(brief, "through")}
    found.update(fields)
    return found


def _boss(brief: Any, degrees: float, way: str = "+x", *, face: str = "+z") -> dict[str, Any]:
    return {"id": "boss", "kind": "boss", "words": cite(brief, "boss"), "on": {"item": "plate", "face": face},
            "diameter": mm(brief, 10, "10 mm"), "height": mm(brief, 12, "12 mm"), **_lean(degrees, way)}  # fmt: skip


def _post(brief: Any, degrees: float, way: str = "+x", *, turn: float | None = None,
          sizes: tuple[float, float, float] = (6, 4, 10)) -> dict[str, Any]:  # fmt: skip
    length, width, height = sizes
    found = {"id": "post", "kind": "post", "words": cite(brief, "post"), "on": {"item": "plate", "face": "+z"},
             "length": mm(brief, length, f"{length:g} mm"), "width": mm(brief, width, f"{width:g} mm"),
             "height": mm(brief, height, f"{height:g} mm"), **_lean(degrees, way)}  # fmt: skip
    if turn is not None:
        found["place"] = {"turn": assumed("turned", turn, "deg")}
    return found


def _planned(text: str, make: Any, *, cube: bool = False) -> tuple[Any, Any]:
    """The draft locked and planned: (the confirmed spec, the plan)."""
    from forge_plan import plan
    from forge_spec.checks import check_draft
    from forge_spec.lock import lock
    from forge_spec.words import number_words

    brief = number_words((_CUBE if cube else _PLATE) + text)
    found = draft("plate", [_body(brief, cube), *make(brief)])
    found["schema_version"] = "1.3"
    report = check_draft(brief, found, strict=False)
    assert not report.problems, [p.message for p in report.problems]
    spec = lock(report, brief, by="draft", strict=False)
    planned = plan(spec)
    assert not planned.gaps, [g.reason for g in planned.gaps]
    return spec, planned


def _judged(text: str, make: Any, *, cube: bool = False) -> tuple[Any, Any, list[str]]:
    from test_v2_plan_build import judged_plan

    spec, planned = _planned(text, make, cube=cube)
    return judged_plan(spec.spec, planned)


class WhatIsWrittenLeans(unittest.TestCase):
    def test_a_hole_along_its_direction_kept_in_the_material(self) -> None:
        _, planned = _planned(HOLE, lambda b: [_hole(b, 30)])
        steps = [s for s in planned.written().chain.steps if "hole" in s["for_items"]]
        # Its cylinder along its direction, in, kept within the plate's 8 mm by a box from its face, then taken away.
        self.assertEqual([s["op"] for s in steps], ["cylinder", "box", "intersect", "subtract"])
        t = math.radians(30)
        for g, want in zip(steps[0]["params"]["axis"]["vector"], (-math.sin(t), 0.0, -math.cos(t)), strict=True):
            self.assertAlmostEqual(float(g), want, places=9)
        self.assertEqual(steps[1]["params"]["size"]["vector"][2], 8.0)

    def test_a_post_by_a_rigid_motion(self) -> None:
        _, planned = _planned(POST, lambda b: [_post(b, 30)])
        ops = [s["op"] for s in planned.written().chain.steps if "post" in s["for_items"]]
        self.assertIn("transform", ops)


@needs_occ
class LeaningItemsAreBuiltAsPlaced(unittest.TestCase):
    def _passes(self, text: str, make: Any, *, cube: bool = False) -> None:
        from forge_checks.classes import Verdict

        built, accounting, failed = _judged(text, make, cube=cube)
        self.assertIsNone(built.gap, built.refusals)
        self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
        self.assertEqual(failed, [])

    def test_holes(self) -> None:
        cases = {
            "through": (HOLE, lambda b: [_hole(b, 30)]),
            "through, steep": (HOLE, lambda b: [_hole(b, 60, "-y")]),
            "blind": (BLIND, lambda b: [_hole(b, 30, "-x")]),
            "blind, its side nowhere all round": (BLIND, lambda b: [_hole(b, 55, "+y")]),
            "counterbored": (BORED, lambda b: [_hole(b, 20, "+y", counterbore={
                "diameter": mm(b, 11, "11 mm"), "depth": mm(b, 3, "3 mm")})]),
            "measured to its edge": (EDGE, lambda b: [_hole(b, 30, "-x", place={
                "x": {"side": "-x", "distance": mm(b, 4, "4 mm"), "to": "edge"}})]),
        }  # fmt: skip
        for name, (text, make) in cases.items():
            with self.subTest(name):
                self._passes(text, make)

    def test_copies(self) -> None:
        def row(b: Any) -> list[dict[str, Any]]:
            pattern = {"row": {"count": {"count": 2, "from": said(b, "Two")}, "pitch": mm(b, 30, "30 mm"),
                               "axis": {"choose": "x", "from": {"assumed": "along the plate"}}}}  # fmt: skip
            found = _hole(b, 40, "+x", place={"pattern": pattern})
            found["count"] = {"count": 2, "from": said(b, "Two")}
            return [found]

        self._passes(ROW, row)

    def test_standing(self) -> None:
        for degrees, way in ((30, "+x"), (15, "-y")):
            with self.subTest(boss=degrees, way=way):
                self._passes(BOSS, lambda b, d=degrees, w=way: [_boss(b, d, w)])
            with self.subTest(post=degrees, way=way):
                self._passes(POST, lambda b, d=degrees, w=way: [_post(b, d, w)])
        with self.subTest("a post turned and leaning"):
            self._passes(POST, lambda b: [_post(b, 30, "-y", turn=25.0)])
        with self.subTest("a post thin along its lean, wide across it"):
            self._passes(POST3, lambda b: [_post(b, 45, "-x", sizes=(3.5, 20, 10))])

    def test_every_face_and_either_way(self) -> None:
        ways = {"+z": "x", "-z": "y", "+x": "y", "-x": "z", "+y": "z", "-y": "x"}
        for face, axis in ways.items():
            for sign in "+-":
                with self.subTest(face=face, way=sign + axis):
                    self._passes(BLIND, lambda b, f=face, w=sign + axis: [_hole(b, 35, w, face=f)], cube=True)
            with self.subTest(face=face, boss=True):
                self._passes(BOSS, lambda b, f=face, w="+" + axis: [_boss(b, 25, w, face=f)], cube=True)


@needs_occ
class AWrongLeanIsCaught(unittest.TestCase):
    def test_leaning_more_or_the_other_way(self) -> None:
        import forge_plan.items.plan._tools as tools
        from forge_checks.classes import Verdict

        real = tools._leaning

        def more(copy: Any, face: Any) -> Any:
            _, n, w, c, s = real(copy, face)
            t = math.atan2(s, c) + math.radians(0.5)
            c, s = math.cos(t), math.sin(t)
            return tuple(c * n[k] + s * w[k] for k in range(3)), n, w, c, s

        def other_way(copy: Any, face: Any) -> Any:
            _, n, w, c, s = real(copy, face)
            w = (-w[0], -w[1], -w[2])
            return tuple(c * n[k] + s * w[k] for k in range(3)), n, w, c, s

        cases = {"a hole": (HOLE, lambda b: [_hole(b, 30)]), "a blind hole": (BLIND, lambda b: [_hole(b, 30)]),
                 "a boss": (BOSS, lambda b: [_boss(b, 30)]), "a post": (POST, lambda b: [_post(b, 30)])}  # fmt: skip
        for how, wrong in (("half a degree more", more), ("the other way", other_way)):
            for name, (text, make) in cases.items():
                with self.subTest(how=how, item=name), mock.patch.object(tools, "_leaning", wrong):
                    built, accounting, _ = _judged(text, make)
                    self.assertIsNone(built.gap)
                    self.assertIs(accounting.verdict, Verdict.FAIL)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_a_hole_a_boss_and_a_turned_post(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        text = BORED + " " + BOSS + " " + POST2

        def make(b: Any) -> list[dict[str, Any]]:
            hole = _hole(b, 25, "-x", counterbore={"diameter": mm(b, 11, "11 mm"), "depth": mm(b, 3, "3 mm")},
                         place={"x": {"offset": assumed("left", -25.0)}})  # fmt: skip
            boss = _boss(b, 20, "+y")
            post = _post(b, 30, "+x", turn=25.0, sizes=(7, 5, 9))
            post["place"]["x"] = {"offset": assumed("right", 30.0)}
            return [hole, boss, post]

        _, planned = _planned(text, make)
        built = build_plan(planned)
        self.assertIsNone(built.gap, built.refusals)
        report = agree(planned.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
