"""V2 stage 4: sizes made at the middle of their tolerance (sizes.md; docs/V2-stage4.md, 9.6).

A value whose own tolerance isn't the same both ways (10 mm +0.1/-0) is made
at the middle of its band, and held to the limits it was written with: so a
correct part is never made on a limit, where no measurement could show it
within. The value's made size; the spec's own checks refusing a size made
at or below 0; a part of one-sided tolerances planned, built and judged
passing, its sizes measured at their middles; and parts made outside the
written limits, or on one, judged by the same spec and held.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forge_spec.values import Provenance, Source, Tolerance, Value
from forge_units import Q
from v2_occ import needs_occ
from v2_reference import item, offset, on, through
from v2_specs import a, draft, pick


def told(number: float, plus: float, minus: float, unit: str = "mm") -> dict[str, Any]:
    """A size with its own tolerance."""
    value = a(number, unit)
    value["tolerance"] = {"plus": plus, "minus": minus}
    return value


def made(
    number: float, unit: str, plus: float | None = None, minus: float = 0.0
) -> Value:
    tolerance = None if plus is None else Tolerance(plus, minus)
    return Value(
        Q(number, unit), Provenance(Source.ASSUMED, reason="a test"), tolerance
    )


class AValueIsMadeAtItsMiddle(unittest.TestCase):
    def test_the_middle_of_its_band(self) -> None:
        self.assertEqual(made(10, "mm").made_in("mm"), 10.0)
        self.assertEqual(made(10, "mm", 0.1, 0.1).made_in("mm"), 10.0)
        self.assertAlmostEqual(made(10, "mm", 0.1).made_in("mm"), 10.05, places=12)
        self.assertAlmostEqual(made(6, "mm", 0.0, 0.2).made_in("mm"), 5.9, places=12)
        self.assertAlmostEqual(made(1, "in", 0.01).made_in("mm"), 25.527, places=12)
        self.assertAlmostEqual(
            made(90, "deg", 0.0, 1.0).made_in("deg"), 89.5, places=12
        )
        # The nominal is kept, for the spec's own text.
        self.assertEqual(made(10, "mm", 0.1).nominal_in("mm"), 10.0)
        self.assertEqual(made(10, "mm", 0.1).nominal, 10.0)


class TheSpecChecksJudgeTheMadeSize(unittest.TestCase):
    def problems(self, length: dict[str, Any]) -> list[str]:
        from forge_spec.checks import check_draft
        from test_v2_plan import BRIEF

        items = [item("plate", "block", length=length, width=a(10), height=a(5))]
        report = check_draft(BRIEF, draft(items), strict=False)
        return [
            f"{p.at}: {p.message}"
            for p in report.problems
            if p.at.startswith("/items/0/length")
        ]

    def test_a_size_made_at_or_below_zero_is_refused(self) -> None:
        for minus in (3.0, 2.0):  # made at -0.5 mm, and at 0
            with self.subTest(minus=minus):
                found = self.problems(told(1, 0.0, minus))
                self.assertTrue(found)
                self.assertIn("made at the middle of its tolerance", found[0])

    def test_a_size_made_above_zero_reads(self) -> None:
        self.assertEqual(self.problems(told(1, 0.0, 1.5)), [])


def _part(
    diameter: dict[str, Any], height: dict[str, Any], depth: dict[str, Any]
) -> list[dict[str, Any]]:
    """A plate with a pin's hole through it and a pocket, each size as given."""
    return [
        item("plate", "block", length=a(60), width=a(40), height=height),
        item("pin", "hole", on=on("plate", "+z"), diameter=diameter, depth=through()),
        item("cup", "pocket", on=on("plate", "+z"), shape=pick("circle"), diameter=a(12), depth=depth,
             place={"x": offset(15)}),
    ]  # fmt: skip


#: The part as asked: a 10 mm +0.1/-0 pin's hole, a 6 mm +0/-0.2 plate, a 3 mm +0.2/-0 pocket.
ASKED = _part(told(10, 0.1, 0.0), told(6, 0.0, 0.2), told(3, 0.2, 0.0))


@needs_occ
class APartOfOneSidedTolerances(unittest.TestCase):
    def test_is_made_at_the_middles_and_passes(self) -> None:
        from forge_checks.classes import Verdict
        from test_v2_plan import confirmed
        from test_v2_plan_build import judged

        built, accounting, failed = judged(ASKED)
        self.assertIsNone(built.gap, built.refusals)
        self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
        self.assertEqual(failed, [])
        # The plate's top at 5.9, the hole 10.05 across, the pocket's floor 3.1 below the top.
        from forge_occ.view import BrepView

        view = BrepView(built.result.shape)
        box = view.bounds()
        self.assertAlmostEqual(box.hi[2] - box.lo[2], 5.9, places=6)
        radii = sorted(
            {round(f.surface[6], 9) for f in view.faces() if f.kind == "cylinder"}
        )
        self.assertEqual(radii, [5.025, 6.0])
        floors = sorted(
            {round(f.bounds.lo[2], 9) for f in view.faces() if f.kind == "plane"}
        )
        self.assertEqual(floors, [0.0, 2.8, 5.9])
        diameter = confirmed(ASKED).spec.items[1].get("diameter")
        assert isinstance(diameter, Value)
        self.assertAlmostEqual(diameter.made_in("mm"), 10.05, places=12)

    def test_made_outside_or_on_a_limit_is_held(self) -> None:
        from forge_plan import plan
        from test_v2_plan import confirmed
        from test_v2_plan_build import judged_plan

        asked = confirmed(ASKED).spec
        cases = {
            # Made 10.12 across: past +0.1, a FAIL.
            "too wide": (_part(a(10.12), told(6, 0.0, 0.2), told(3, 0.2, 0.0)), "fail"),
            # Made 9.98 across: under -0, a FAIL.
            "too narrow": (
                _part(a(9.98), told(6, 0.0, 0.2), told(3, 0.2, 0.0)),
                "fail",
            ),
            # Made at 10.0, on its lower limit: no measurement can show it within.
            "on its limit": (
                _part(a(10), told(6, 0.0, 0.2), told(3, 0.2, 0.0)),
                "inconclusive",
            ),
        }
        for name, (items, verdict) in cases.items():
            with self.subTest(name):
                _, _, failed = judged_plan(asked, plan(confirmed(items)))
                pin = [line for line in failed if line.startswith("pin/diameter")]
                self.assertTrue(pin, failed)
                self.assertIn(f": {verdict}:", pin[0])


if __name__ == "__main__":
    unittest.main()
