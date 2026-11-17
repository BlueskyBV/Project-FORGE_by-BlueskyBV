"""A turned block hollowed (shell.md; place.md, "Turned in the face"; V2-stage4b-0c.md, 3.3, 1b's third move, step 5.1).

- **Hollowed as it stands upright, then turned with it:** its walls, its
  floor and its inside faces turned with its sides, its open face closed
  as an upright one's is; every program's layout agrees.
- **What is built is what was placed.** Open at its top; with a thicker
  floor; its vertical edges rounded first, the hollow following them; a
  hole through an inside wall; its rim rounded: built by the build loop,
  every face accounted for both ways, every check its spec compiles to
  passing.
- **A wrong turn is caught:** its hollow turned half a degree more fails
  the judge.
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


def _box(b: Any, turn: float = 30.0) -> dict[str, Any]:
    return {"id": "box", "kind": "block", "words": cite(b, "post"), "on": {"item": "plate", "face": "+z"},
            "length": assumed("long", 30.0), "width": assumed("wide", 20.0), "height": assumed("tall", 12.0),
            "place": {"turn": assumed("turned", turn, "deg")}}  # fmt: skip


def _shell(b: Any, floor: float | None = None) -> dict[str, Any]:
    found = {"id": "hollow", "kind": "shell", "words": cite(b, "post"), "of": "box", "thickness": assumed("thick", 2.0),
             "open": {"faces": ["+z"], "from": {"assumed": "open at the top"}}}  # fmt: skip
    if floor is not None:
        found["floor"] = assumed("floor", floor)
    return found


def _rounding(b: Any, which: str, size: float, item: str = "round") -> dict[str, Any]:
    return {"id": item, "kind": "fillet", "words": cite(b, "post"), "radius": assumed("small", size),
            "edges": {"of": "box", "which": which}}  # fmt: skip


#: Each part: a turned block, hollowed, and what is done with it.
CASES: dict[str, Any] = {
    "open at its top": lambda b: [_box(b), _shell(b)],
    "a thicker floor": lambda b: [_box(b, 45.0), _shell(b, 3.0)],
    "its vertical edges rounded first": lambda b: [_box(b), _rounding(b, "vertical", 3.0), _shell(b)],
    "a hole through an inside wall": lambda b: [_box(b), _shell(b), {
        "id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": "box", "face": "inner +x"},
        "diameter": assumed("across", 3.0), "depth": {"through": True, "from": {"assumed": "through"}}}],
    "its rim rounded": lambda b: [_box(b), _shell(b), _rounding(b, "top", 0.6)],
}


class HollowedUprightThenTurned(unittest.TestCase):
    def test_its_faces(self) -> None:
        from forge_spec.checks import check_draft
        from forge_spec.words import number_words

        b = number_words(_TEXT)
        report = check_draft(b, draft("plate", [_plate(b), *CASES["open at its top"](b)]), strict=False)
        self.assertEqual([p for p in report.problems if p.kind in ("fault", "unable", "cant")], [])
        faces = report.layout.faces[("box", 0)]
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        for name, way in (("+x", (c, s, 0.0)), ("inner +x", (-c, -s, 0.0)), ("inner -z", (0.0, 0.0, 1.0))):
            for got, want in zip(faces[name].frame.n, way, strict=True):
                self.assertAlmostEqual(got, want, places=9)
        self.assertEqual((faces["+x"].depth_below, faces["inner -z"].centre[2]), (2.0, 10.0))
        self.assertIn("+z", report.layout.closed[("box", 0)])  # open: its rim takes nothing


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
    def test_its_hollow_turned_half_a_degree_more(self) -> None:
        import forge_plan.moved as moved
        from forge_checks.classes import Verdict

        real = moved.transform_params

        def more(motion: Any) -> dict[str, Any]:
            found = real(motion)
            angle = found["rotate_angle"]
            return {**found, "rotate_angle": {**angle, "magnitude": angle["magnitude"] + 0.5}}

        with mock.patch.object(moved, "transform_params", more):
            built, accounting, _ = _judged(CASES["open at its top"])
        self.assertIsNone(built.gap)
        self.assertIs(accounting.verdict, Verdict.FAIL)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_open_at_its_top(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        _, planned = _planned(CASES["open at its top"])
        built = build_plan(planned)
        self.assertIsNone(built.gap, built.refusals)
        report = agree(planned.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
