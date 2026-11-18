"""A hole, a boss or a post on a round-ended tab's end (place.md, "On a round-ended tab's end"; tab.md;
V2-stage4b-0c.md, 3.4, item 3b's fourth step).

- **Placed as round a side over its half:** at its tip unless an angle is
  given, by its position along the tab's thickness and an angle round it;
  every program's layout agrees.
- **What doesn't fit, or isn't built yet, is said:** a boss off the half, a
  circle of copies, a hole right through, one deeper than the tab holds, a
  turned tab's end.
- **What is built is what was placed.** A hole at its tip and at an angle,
  a boss, a post, an arc of holes, a tab thick along x, one on the plate's
  side, one all round end, a deep hole, a hole in each of a row of two tabs'
  ends, a boss's joint and rim and a hole's mouth rounded: built by the
  build loop, every face accounted for both ways, every check its spec
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
from test_v2_plan_faceaxes import _TEXT, _judged, _planned, _plate
from v2_drafts import assumed, cite, draft
from v2_occ import needs_occ


def _tab(b: Any, thick: str = "y", length: float = 14.0, width: float = 12.0, face: str = "+z",
         turn: float | None = None) -> dict[str, Any]:  # fmt: skip
    found = {"id": "tab", "kind": "tab", "words": cite(b, "post"), "on": {"item": "plate", "face": face},
             "length": assumed("out", length), "width": assumed("wide", width), "thickness": assumed("thick", 8.0),
             "thickness_along": {"choose": thick, "from": {"assumed": "across"}},
             "end": {"choose": "round", "from": {"assumed": "round"}}}  # fmt: skip
    if turn is not None:
        found["place"] = {"turn": assumed("turned", turn, "deg")}
    return found


def _on(b: Any, kind: str, angle: float | None = None, *, item: str | None = None, depth: float = 3.0,
        face: str = "+z", **fields: Any) -> dict[str, Any]:  # fmt: skip
    """A hole, a boss or a post on the tab's round end, at ``angle`` round it."""
    sizes = {"boss": {"diameter": assumed("across", 3.0), "height": assumed("tall", 3.0)},
             "post": {"length": assumed("long", 3.0), "width": assumed("wide", 2.0), "height": assumed("tall", 3.0)},
             "hole": {"diameter": assumed("across", 2.0), "depth": assumed("deep", depth)}}[kind]  # fmt: skip
    found = {"id": item or kind, "kind": kind, "words": cite(b, "post"), "on": {"item": "tab", "face": face},
             **sizes, **fields}  # fmt: skip
    if angle is not None:
        found["place"] = {"angle": assumed("round", angle, "deg")}
    return found


def _rounding(b: Any, of: str, which: str, kind: str = "fillet", size: float = 0.4, **more: Any) -> dict[str, Any]:
    return {"id": "round", "kind": kind, "words": cite(b, "post"), ("radius" if kind == "fillet" else "size"):
            assumed("small", size), "edges": {"of": of, "which": which, **more}}  # fmt: skip


def _row(tab: dict[str, Any]) -> dict[str, Any]:
    """Two of the tab, 20 mm apart along x (the place along each one's end is from its own: the check compiler
    measured every copy's from the first's once)."""
    return {**tab, "count": {"count": 2, "from": {"assumed": "two"}},
            "place": {"pattern": {"row": {"count": {"count": 2, "from": {"assumed": "two"}},
                                          "pitch": assumed("apart", 20.0),
                                          "axis": {"choose": "x", "from": {"assumed": "along"}}}}}}  # fmt: skip


def _arc(b: Any, step: float = -40.0, pattern: str = "arc") -> dict[str, Any]:
    found = _on(b, "hole", 50.0)
    found["count"] = {"count": 3, "from": {"assumed": "so many"}}
    body: dict[str, Any] = {"count": {"count": 3, "from": {"assumed": "so many"}}}
    if pattern == "arc":
        body["step"] = assumed("step", step, "deg")
    found["place"]["pattern"] = {pattern: body}
    return found


#: Each part: the plate, a round-ended tab on it, and what is on the tab's end. Thick along y on +z, the end's angles
#: are measured round y from +z towards +x: its half is from -90 to 90 degrees.
CASES: dict[str, Any] = {
    "a hole at its tip": lambda b: [_tab(b), _on(b, "hole")],
    "a hole at 60 degrees": lambda b: [_tab(b), _on(b, "hole", 60.0)],
    "a boss at -40": lambda b: [_tab(b), _on(b, "boss", -40.0)],
    "a post at 30": lambda b: [_tab(b), _on(b, "post", 30.0)],
    "an arc of holes": lambda b: [_tab(b), _arc(b)],
    "a tab thick along x": lambda b: [_tab(b, "x"), _on(b, "boss", 60.0), _on(b, "hole", 120.0, item="h2")],
    "a tab on the plate's side": lambda b: [_tab(b, "z", face="+x"), _on(b, "boss", 30.0, face="+x")],
    "a tab all round end": lambda b: [_tab(b, length=6.0), _on(b, "hole", 70.0)],
    "a deep hole": lambda b: [_tab(b), _on(b, "hole", 10.0, depth=12.0)],
    "a row of two tabs, a hole in each's end": lambda b: [_row(_tab(b)), _on(b, "hole", 20.0)],
    "a boss's joint rounded": lambda b: [_tab(b), _on(b, "boss", 20.0), _rounding(b, "boss", "joint", where_meets="tab")],
    "a boss's rim rounded": lambda b: [_tab(b), _on(b, "boss", 45.0), _rounding(b, "boss", "top")],
    "a hole's mouth bevelled": lambda b: [_tab(b), _on(b, "hole", -30.0), _rounding(b, "hole", "top", "chamfer", 0.3)],
}


def _report(make: Any) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    b = number_words(_TEXT)
    return check_draft(b, draft("plate", [_plate(b), *make(b)]), strict=False)


class PlacedRoundItsHalf(unittest.TestCase):
    def test_at_its_tip_and_at_an_angle(self) -> None:
        report = _report(lambda b: [_tab(b), _on(b, "hole"), _on(b, "hole", 60.0, item="h2")])
        self.assertEqual([p for p in report.problems if p.kind in ("fault", "unable", "cant", "question")], [])
        self.assertTrue(any("at the tip of tab's round end" in a.message for a in report.assumptions))
        # The tab's end: its axis along y through (0, *, 16): the plate's top at 8, and the tab's 14 less its 6 mm radius.
        for name, angle in (("hole", 0.0), ("h2", 60.0)):
            (copy,) = report.layout.instances[name]
            c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            for got, want in ((copy.origin, (6.0 * s, 0.0, 16.0 + 6.0 * c)), (copy.normal, (s, 0.0, c))):
                for g, w in zip(got, want, strict=True):
                    self.assertAlmostEqual(g, w, places=9)

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, make in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


class WhatDoesntFitOrIsntBuiltYetIsSaid(unittest.TestCase):
    def test_each(self) -> None:
        through = {"through": True, "from": {"assumed": "through"}}
        for make, kind, words in (
            (lambda b: [_tab(b), _on(b, "boss", 200.0)], ("question", "fault"), "runs off the round end of tab"),
            (lambda b: [_tab(b), _arc(b, pattern="circle")], "fault", "copies go in an arc over its half"),
            (lambda b: [_tab(b), {**_on(b, "hole", 10.0), "depth": through}], "unable", "a blind hole into a tab's"),
            (lambda b: [_tab(b, length=8.0), _on(b, "hole", 10.0, depth=30.0)], ("question", "fault"), "of material"),
            (lambda b: [_tab(b, turn=30.0), _on(b, "hole", 10.0)], "unable", "tab is turned in"),
        ):  # fmt: skip
            with self.subTest(words):
                report = _report(make)
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

        for name in ("a boss at -40", "a post at 30"):
            with self.subTest(name), mock.patch.object(moved, "transform_params", more):
                built, accounting, _ = _judged(CASES[name])
                self.assertIsNone(built.gap)
                self.assertIs(accounting.verdict, Verdict.FAIL)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_on_a_tabs_end(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("a hole at 60 degrees", "a boss at -40", "a tab thick along x", "a boss's joint rounded"):
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
