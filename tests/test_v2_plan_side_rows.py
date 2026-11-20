"""A row of copies along a round side's axis (place.md, "On a round side"; pattern ``row``).

Holes along a tube or a rod (a drip line, an adjustable stay) were refused:
round a side, only a circle or an arc of copies went. A row along the
side's axis is placed now, by every program alike: its copies all at
``place.angle``, ``pitch`` apart along the axis, from an end to its nearest
copy or else by its centre. What these hold:

- **Where its copies are:** centred, offset, from either end, to a copy's
  centre or its edge; a row along another axis is the writer's fault.
- **Every program's layout agrees.**
- **What is built is what was placed:** built, every face accounted for,
  every check passing; a row built a pitch off, or off its place, caught.
- **The generator draws them** (a stream of its own), its truth where the
  solver and the judge put them.
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

_TEXT = "A rod with a row of holes along it."


def _rod(b: Any, kind: str = "cylinder") -> dict[str, Any]:
    found = {"id": "rod", "kind": kind, "words": cite(b, "rod"), "axis": {"choose": "z", "from": {"assumed": "up"}},
             "length": assumed("long", 40.0)}  # fmt: skip
    if kind == "tube":
        found.update(outer_diameter=assumed("across", 20.0), inner_diameter=assumed("bore", 14.0))
    else:
        found["diameter"] = assumed("across", 12.0)
    return found


def _row(b: Any, z: dict[str, Any] | None = None, *, count: int = 3, pitch: float = 10.0, axis: str = "z",
         angle: float = 30.0, diameter: float = 3.0) -> dict[str, Any]:  # fmt: skip
    place: dict[str, Any] = {"angle": {"value": angle, "unit": "deg", "from": {"assumed": "round it"}},
                             "pattern": {"row": {"axis": {"choose": axis, "from": {"assumed": "along it"}},
                                                 "count": {"count": count, "from": {"assumed": "a few"}},
                                                 "pitch": assumed("apart", pitch)}}}  # fmt: skip
    if z is not None:
        place["z"] = z
    return {"id": "holes", "kind": "hole", "words": cite(b, "holes"), "on": {"item": "rod", "face": "side"},
            "diameter": assumed("across", diameter), "depth": {"through": True, "from": {"assumed": "through"}},
            "count": {"count": count, "from": {"assumed": "a few"}}, "place": place}  # fmt: skip


def _report(items: Any) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    brief = number_words(_TEXT)
    return check_draft(brief, draft("rod", items(brief)), strict=False)


def _planned(items: Any) -> tuple[Any, Any]:
    from forge_plan import plan
    from forge_spec.lock import lock
    from forge_spec.words import number_words

    report = _report(items)
    assert not report.problems, [p.message for p in report.problems]
    spec = lock(report, number_words(_TEXT), by="draft", strict=False)
    return spec, plan(spec)


#: Each row, and where its copies' centres are along the rod's axis (its -end at 0).
CASES: dict[str, tuple[Any, list[float]]] = {
    "centred": (lambda b: [_rod(b), _row(b)], [10.0, 20.0, 30.0]),
    "offset": (lambda b: [_rod(b), _row(b, {"offset": assumed("off its middle", 4.0)})], [14.0, 24.0, 34.0]),
    "from its -end to a copy's centre": (
        lambda b: [_rod(b), _row(b, {"side": "-z", "distance": assumed("in", 5.0), "to": "centre"})], [5.0, 15.0, 25.0]),
    "from its +end to a copy's edge": (
        lambda b: [_rod(b), _row(b, {"side": "+z", "distance": assumed("in", 2.0), "to": "edge"}, count=2)],
        [26.5, 36.5]),
    "through a tube's wall": (lambda b: [_rod(b, "tube"), _row(b, count=4, diameter=4.0)], [5.0, 15.0, 25.0, 35.0]),
}  # fmt: skip


class WhereItsCopiesAre(unittest.TestCase):
    def test_along_the_axis(self) -> None:
        for name, (make, alongs) in CASES.items():
            with self.subTest(name):
                report = _report(make)
                self.assertEqual(report.problems, ())
                copies = report.layout.instances["holes"]
                self.assertEqual([round(c.origin[2], 9) for c in copies], alongs)
                at = {(round(c.origin[0], 9), round(c.origin[1], 9)) for c in copies}  # all at one angle round it
                self.assertEqual(len(at), 1)
                (x, y), = at
                self.assertAlmostEqual(math.degrees(math.atan2(y, x)), 30.0)

    def test_along_another_axis_or_past_its_end(self) -> None:
        wrong = _report(lambda b: [_rod(b), _row(b, axis="x")])
        self.assertIn("a row runs along the side's axis", " ".join(p.message for p in wrong.problems))
        long = _report(lambda b: [_rod(b), _row(b, count=5)])
        self.assertIn("runs past the end of rod", " ".join(p.message for p in long.problems))

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, (make, _) in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


@needs_occ
class BuiltAsPlaced(unittest.TestCase):
    def test_every_case(self) -> None:
        from forge_checks.classes import Verdict
        from test_v2_plan_build import judged_plan

        for name, (make, _) in CASES.items():
            with self.subTest(name):
                spec, planned = _planned(make)
                built, accounting, failed = judged_plan(spec.spec, planned)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_a_wrong_row_is_caught(self) -> None:
        from forge_checks.classes import Verdict
        from test_v2_plan_build import judged_plan

        asked, _ = _planned(CASES["from its -end to a copy's centre"][0])
        for made in (lambda b: [_rod(b), _row(b, {"side": "-z", "distance": assumed("in", 5.0), "to": "centre"},
                                              pitch=10.6)],
                     lambda b: [_rod(b), _row(b, {"side": "-z", "distance": assumed("in", 5.6), "to": "centre"})]):  # fmt: skip
            _, planned = _planned(made)
            _, accounting, failed = judged_plan(asked.spec, planned)
            self.assertTrue(accounting.verdict is Verdict.FAIL or failed)


class TheGeneratorDrawsThem(unittest.TestCase):
    def test_from_a_stream_of_their_own(self) -> None:
        import numpy as np
        from forge_checks.place import place
        from forge_eval.generator import draft_of, generate
        from forge_spec.draft import read_draft
        from forge_spec.placement import solve

        case = generate(51)  # a rod's side, four holes along it
        rows = [f for f in case.plan if f.pattern is not None and f.pattern.kind == "row" and f.on == ("body", "side")]
        self.assertEqual([(f.pattern.counts["count"], f.pattern.axis) for f in rows if f.pattern], [(4, "z")])
        spec, problems = read_draft(draft_of(case.items))
        assert spec is not None and not problems.faults
        assert case.truth is not None
        layout, placed = solve(spec), place(spec)
        for item, copies in case.truth.copies.items():
            for truth, mine, theirs in zip(copies, placed.copies[item], layout.instances[item], strict=True):
                np.testing.assert_allclose(truth.point, mine.point, atol=1e-6)
                np.testing.assert_allclose(truth.point, theirs.origin, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
