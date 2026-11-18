"""A turned item's far face over a host without the same material under all of it (place.md, "A turned item's far
face"; frame.md; V2-stage4b-0c.md, 3.3, 1b's step 5, with item 2b).

- **Its host's material where it is over it:** a turned post's far face has
  its own height under it and, where a footprint on it is wholly over its
  host's face, the host's there too, read along the host's axes: over a
  ledge standing off the plate's edge, the plate's too where it is over the
  plate and only the ledge's past its edge; in a pocket, the floor's; on a
  leaning post's far face, the leaning post's own back along its axis. A
  blind cut deeper than that is asked about; one right through goes as deep
  as the most under it.
- **Every program's layout agrees.**
- **What is built is what was placed:** each part built by the build loop,
  every face accounted for both ways, every check its spec compiles to
  passing.
- **The second kernel agrees** with the exact part.
- **The generator draws it:** a turned box's far face on a face without the
  same material under all of it, its own height and the least of its host's
  under its foot, and what goes on it.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan_faceaxes import _hole, _judged, _planned, _plate, _post
from test_v2_plan_leanfar import _leaning
from v2_drafts import assumed, cite
from v2_occ import needs_occ

C30, S30 = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))


def _ledge(b: Any, x: float = 45.0) -> dict[str, Any]:
    """A block 20 mm square and 6 mm tall on the plate, ``x`` along it from its middle: at 45, half of it past the
    plate's edge at 50."""
    return {"id": "ledge", "kind": "block", "words": cite(b, "plate"), "on": {"item": "plate", "face": "+z"},
            "length": assumed("long", 20.0), "width": assumed("wide", 20.0), "height": assumed("tall", 6.0),
            "place": {"x": {"offset": assumed("along", x)}}}  # fmt: skip


def _pocket(b: Any) -> dict[str, Any]:
    """A pocket 40 by 30 mm and 3 mm deep in the plate."""
    return {"id": "pocket", "kind": "pocket", "words": cite(b, "pocket"), "on": {"item": "plate", "face": "+z"},
            "shape": {"choose": "rectangle", "from": {"assumed": "square"}}, "length": assumed("long", 40.0),
            "width": assumed("wide", 30.0), "depth": assumed("deep", 3.0)}  # fmt: skip


def _in_pocket(b: Any) -> dict[str, Any]:
    """A post 8 by 6 mm and 2 mm tall, turned 30 degrees, on the pocket's floor."""
    return {**_post(b, on="pocket", sizes=(8.0, 6.0, 2.0)), "on": {"item": "pocket", "face": "bottom"}}


def _on_ledge(b: Any, x: float = 5.0) -> dict[str, Any]:
    """A post 8 by 6 mm and 2 mm tall, turned 30 degrees, on the ledge ``x`` along it: at 5, across the plate's edge."""
    post = _post(b, on="ledge", sizes=(8.0, 6.0, 2.0))
    return {**post, "place": {**post["place"], "x": {"offset": assumed("along", x)}}}


def _small(b: Any, u: float, depth: float | None = None) -> dict[str, Any]:
    """A hole 1 mm across on the post, ``u`` along its own first axis."""
    return _hole(b, {"u": {"offset": assumed("along", u)}}, depth=depth, diameter=assumed("across", 1.0))


#: Each part, a hole on the turned post's far face, and the least material under the hole there.
CASES: dict[str, tuple[Any, float]] = {
    # The post's middle at 50: 3 mm back along its first axis is over the plate, 3 mm on past its edge.
    "over a ledge, over the plate": (lambda b: [_ledge(b), _on_ledge(b), _small(b, -3.0, 15.0)], 2.0 + 6.0 + 8.0),
    "over a ledge, past the plate's edge": (lambda b: [_ledge(b), _on_ledge(b), _small(b, 3.0, 7.5)], 2.0 + 6.0),
    "over a ledge, right through": (lambda b: [_ledge(b), _on_ledge(b), _small(b, -3.0)], 2.0 + 6.0 + 8.0),
    "in a pocket": (lambda b: [_pocket(b), _in_pocket(b), _small(b, 2.0, 6.5)],
                    2.0 + 8.0 - 3.0),
    # Its first axis turned 30 degrees from the leaning post's, which leans 20 degrees along it: under the hole's
    # farthest point that way, 1 mm along the post's first axis and half a millimetre round, the leaning post's own.
    "on a leaning post's far face": (lambda b: [_leaning(b, "post"), _post(b, on="lean", sizes=(4.0, 3.0, 2.0)),
                                                _small(b, 1.0, 6.0)],
                                     2.0 + 20.0 - math.tan(math.radians(20.0)) * (C30 + 0.5)),
}  # fmt: skip


def _report(make: Any) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words
    from test_v2_plan_faceaxes import _TEXT
    from v2_drafts import draft

    brief = number_words(_TEXT)
    return check_draft(brief, draft("plate", [_plate(brief), *make(brief)]), strict=False)


class ItsHostsMaterialWhereItIsOverIt(unittest.TestCase):
    def test_the_least_under_each_hole(self) -> None:
        from forge_spec.geometry import Part

        for name, (make, least) in CASES.items():
            with self.subTest(name):
                report = _report(make)
                self.assertEqual(report.problems, ())
                copy = report.layout.instances["hole"][0]
                host = report.layout.instances["post"][0]
                top = report.layout.faces[("post", 0)]["+z"]
                p1, p2 = top.frame.on(copy.origin)
                self.assertAlmostEqual(top.material_under((Part((0.0, 0.0), (0.5, 0.5), True),), (p1, p2)), least,
                                       places=9)  # fmt: skip
                self.assertEqual(top.turn, 30.0)
                self.assertIsNotNone(host.lo)

    def test_deeper_is_asked_about(self) -> None:
        for make, words in (
            (lambda b: [_ledge(b), _on_ledge(b), _small(b, 3.0, 9.0)], "9 mm deep in 8 mm of material"),
            (lambda b: [_pocket(b), _in_pocket(b), _small(b, 2.0, 8.0)],
             "8 mm deep in 7 mm of material"),
        ):  # fmt: skip
            with self.subTest(words):
                report = _report(make)
                self.assertTrue(any(words in p.message for p in report.problems), [p.message for p in report.problems])

    def test_right_through_as_deep_as_the_most_under_it(self) -> None:
        report = _report(CASES["over a ledge, right through"][0])
        self.assertEqual(report.problems, ())

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

        for name, (make, _) in CASES.items():
            with self.subTest(name):
                built, accounting, failed = _judged(make)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_over_a_ledge(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("over a ledge, right through", "in a pocket"):
            with self.subTest(name):
                _, planned = _planned(CASES[name][0])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
