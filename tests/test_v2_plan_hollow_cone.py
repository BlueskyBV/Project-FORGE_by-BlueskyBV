"""A hollowed cone (shell.md, "cone"): a cup, a funnel, a sealed cone.

Blind set 1 refused a cup that widens to its rim (Forge hollowed blocks,
cylinders and balls only). What these hold:

- **Its hollow:** a cone of its own, its side ``thickness`` in from the
  cone's square to it (its radius the cone's less the thickness times the
  side's slant over its length), each end's wall in from that end, none
  where open, ``floor`` opposite an opening. Walls that leave no hollow are
  a CAN'T. A cone that comes to a point, its side, an open end's rim and its
  edges wait.
- **Its ends take what an end takes,** the wall under them: a hole through
  its floor comes out into the hollow; a boss or a pocket on a sealed top.
- **Every program's layout agrees.**
- **What is built is what was placed:** each part built by the build loop,
  every face accounted for both ways, every check passing; its floor and
  end walls held between their faces.
- **A wrong hollow is caught:** walls 0.3 mm thicker or thinner, a floor
  0.3 mm off.
- **The second kernel agrees** with the exact part.
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

_TEXT = "A cone, hollow inside."


def _cone(b: Any, base: float = 40.0, top: float = 50.0, length: float = 60.0) -> dict[str, Any]:
    return {"id": "cone", "kind": "cone", "words": cite(b, "cone"), "axis": {"choose": "z", "from": {"assumed": "up"}},
            "base_diameter": assumed("across its base", base), "top_diameter": assumed("across its top", top),
            "length": assumed("tall", length)}  # fmt: skip


def _shell(b: Any, thickness: float = 2.0, floor: float | None = 3.0, opened: tuple[str, ...] = ("+end",)) -> dict[str, Any]:
    found: dict[str, Any] = {"id": "hollow", "kind": "shell", "words": cite(b, "hollow"), "of": "cone",
                             "thickness": assumed("walls", thickness),
                             "open": {"faces": list(opened), "from": {"assumed": "open"}}}  # fmt: skip
    if floor is not None:
        found["floor"] = assumed("its bottom", floor)
    return found


#: Each part: a cone and its shell.
CASES: dict[str, Any] = {
    "a cup, wider at its rim": lambda b: [_cone(b), _shell(b)],
    "a cup, narrower at its rim": lambda b: [_cone(b, 50.0, 30.0), _shell(b)],
    "a funnel, open at both ends": lambda b: [_cone(b, 10.0, 50.0, 40.0), _shell(b, 1.5, None, ("+end", "-end"))],
    "sealed": lambda b: [_cone(b, 30.0, 20.0, 30.0), _shell(b, 2.0, None, ())],
    "upside down, open at its base": lambda b: [_cone(b, 50.0, 30.0), _shell(b, 2.0, 4.0, ("-end",))],
}


def _report(make: Any) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    brief = number_words(_TEXT)
    return check_draft(brief, draft("cone", make(brief)), strict=False)


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


class ItsHollow(unittest.TestCase):
    def test_a_cup(self) -> None:
        report = _report(CASES["a cup, wider at its rim"])
        self.assertEqual(report.problems, ())
        lo, hi = report.layout.cavities[("cone", 0)]
        slant = math.hypot(60.0, 5.0) / 60.0
        self.assertAlmostEqual(lo[2], 3.0)
        self.assertAlmostEqual(hi[2], 60.0)
        self.assertAlmostEqual(hi[0], 25.0 - 2.0 * slant)  # its widest: at its rim
        self.assertEqual(report.layout.faces[("cone", 0)]["-end"].depth_below, 3.0)
        closed = report.layout.closed[("cone", 0)]
        self.assertEqual(sorted(closed), ["+end", "side"])

    def test_walls_that_leave_no_hollow(self) -> None:
        report = _report(lambda b: [_cone(b, 10.0, 6.0, 20.0), _shell(b, 3.5, None, ())])
        # A CAN'T, sent back to the writer here as its sizes are assumed.
        self.assertEqual([(p.at, "leave no hollow" in p.message) for p in report.problems], [("/items/1/thickness", True)])

    def test_a_point_waits_and_so_do_its_edges(self) -> None:
        # A hollow coming to a point inside the cone: face accounting can't yet tell either side of its point.
        report = _report(lambda b: [_cone(b, 40.0, 0.0, 50.0), _shell(b, 2.0, None, ("-end",))])
        self.assertEqual([p.kind for p in report.problems], ["unable"])
        report = _report(lambda b: [_cone(b, 40.0, 0.0, 50.0), _shell(b, 2.0, None, ("+end",))])
        self.assertIn("fault", [p.kind for p in report.problems])  # it has no +end to leave open
        def rounded(b: Any) -> list[dict[str, Any]]:
            return [_cone(b), _shell(b), {"id": "ease", "kind": "fillet", "words": cite(b, "cone"),
                                          "edges": {"of": "cone", "which": "bottom"}, "radius": assumed("eased", 1.0)}]
        self.assertIn("unable", [p.kind for p in _report(rounded).problems])

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

    def test_its_volume(self) -> None:
        from forge_checks.oracle import oracle
        from forge_checks.place import place

        spec, _ = _planned(CASES["a cup, wider at its rim"])
        made = oracle(spec.spec, place(spec.spec))
        slant = math.hypot(60.0, 5.0) / 60.0

        def frustum(h: float, a: float, b: float) -> float:
            return math.pi * h * (a * a + a * b + b * b) / 3

        a, b = 20.0 + 5.0 * 3.0 / 60.0 - 2.0 * slant, 25.0 - 2.0 * slant
        expected = frustum(60.0, 20.0, 25.0) - frustum(57.0, a, b)
        held = made.volume()  # an interval that holds it: wide, the walls being thin beside the cells
        self.assertTrue(held.lo <= expected <= held.hi, (held, expected))
        self.assertLess(held.hi, frustum(60.0, 20.0, 25.0) / 3)  # the hollow is taken


def _on(b: Any, kind: str, face: str, x: float = 0.0, **fields: Any) -> dict[str, Any]:
    found = {"id": kind, "kind": kind, "words": cite(b, "cone"), "on": {"item": "cone", "face": face},
             "place": {"x": {"offset": assumed("off its axis", x)}, "y": {"centred": {"assumed": "on its axis"}}}}
    for name, value in fields.items():
        found[name] = value if isinstance(value, dict) else assumed(name, value)
    return found


#: What its closed ends take, the wall under them: a hole through its floor comes out into the hollow.
ON_ITS_ENDS: dict[str, Any] = {
    "a drain hole through its floor": lambda b: [_cone(b), _shell(b), _on(
        b, "hole", "-end", 0.0, diameter=4.0, depth={"through": True, "from": {"assumed": "a drain"}})],
    "a hole off its axis into its floor": lambda b: [_cone(b), _shell(b), _on(b, "hole", "-end", 10.0, diameter=3.0,
                                                                              depth=2.0)],
    "a boss on its sealed top": lambda b: [_cone(b, 30.0, 20.0, 30.0), _shell(b, 2.0, None, ()),
                                           _on(b, "boss", "+end", 2.0, diameter=8.0, height=5.0)],
    "a pocket in its sealed top": lambda b: [_cone(b, 30.0, 20.0, 30.0), _shell(b, 2.0, None, ()),
                                             _on(b, "pocket", "+end", 0.0, length=6.0, width=4.0, depth=1.0,
                                                 shape={"choose": "rectangle", "from": {"assumed": "square"}})],
}


def _drawn(seed: int) -> Any:
    """A hollow cone drawn at random: wider or narrower at its top, open at one end, both or none, a floor or not."""
    import random

    rng = random.Random(f"hollow cones {seed}")
    base = round(rng.uniform(12.0, 60.0), 1)
    top = round(base * rng.uniform(0.4, 1.8), 1)
    length = round(rng.uniform(8.0, 70.0), 1)
    thickness = round(rng.uniform(0.8, min(base, top) / 6), 1)
    opened = rng.choice(((), ("+end",), ("+end",), ("-end",), ("+end", "-end")))
    floored = len(opened) == 1 and rng.random() < 0.5
    floor = round(rng.uniform(0.8, length / 5), 1) if floored else None
    return lambda b: [_cone(b, base, top, length), _shell(b, thickness, floor, opened)]


@needs_occ
class ItsEndsTakeWhatAnEndTakes(unittest.TestCase):
    def test_built_as_placed(self) -> None:
        from forge_checks.classes import Verdict
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve
        from test_v2_plan_build import judged_plan

        for name, make in ON_ITS_ENDS.items():
            with self.subTest(name):
                spec, planned = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())
                built, accounting, failed = judged_plan(spec.spec, planned)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_its_side_and_an_open_rim_take_nothing_yet(self) -> None:
        for face in ("side", "+end"):
            with self.subTest(face):
                report = _report(lambda b, face=face: [_cone(b), _shell(b), _on(b, "hole", face, 0.0, diameter=3.0,
                                                                                    depth=1.0)])
                self.assertEqual([p.kind for p in report.problems], ["unable"], report.problems)


@needs_occ
class DrawnAtRandom(unittest.TestCase):
    def test_built_as_placed(self) -> None:
        from forge_checks.classes import Verdict
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve
        from test_v2_plan_build import judged_plan

        for seed in range(8):
            with self.subTest(seed=seed):
                make = _drawn(seed)
                report = _report(make)
                if report.problems:  # walls that leave no hollow: a CAN'T, as drawn
                    self.assertTrue(all("leave no hollow" in p.message for p in report.problems), report.problems)
                    continue
                spec, planned = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())
                built, accounting, failed = judged_plan(spec.spec, planned)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])


@needs_occ
class AWrongHollowIsCaught(unittest.TestCase):
    def test_thicker_thinner_or_its_floor_off(self) -> None:
        from unittest import mock

        import forge_plan.items.plan.cone as planned_cone
        from forge_checks.classes import Verdict
        from test_v2_plan_build import judged_plan

        real_mm, real_walls = planned_cone._mm, planned_cone._walls

        def off(by_wall: float, by_floor: float) -> tuple[Any, Any]:
            def mm(item: Any, name: str) -> float:
                return real_mm(item, name) + (by_wall if item.kind == "shell" and name == "thickness" else 0.0)

            def walls(shell: Any, opposites: Any) -> dict[str, float]:
                found = real_walls(shell, opposites)
                found["-end"] += by_floor
                return found

            return mm, walls

        for name, wall, floor, check in (("walls 0.3 mm thicker", 0.3, 0.0, "hollow/thickness/"),
                                         ("walls 0.3 mm thinner", -0.3, 0.0, "hollow/thickness/"),
                                         ("its floor 0.3 mm thicker", 0.0, 0.3, "hollow/floor/")):  # fmt: skip
            mm, walls = off(wall, floor)
            with self.subTest(name), mock.patch.object(planned_cone, "_mm", mm), \
                    mock.patch.object(planned_cone, "_walls", walls):  # fmt: skip
                spec, planned = _planned(CASES["a cup, wider at its rim"])
                built, accounting, failed = judged_plan(spec.spec, planned)
                self.assertIsNone(built.gap)
                self.assertIs(accounting.verdict, Verdict.FAIL)
                # The wall's own check fails too: the side wall measured square to the side (wall.py).
                self.assertTrue(any(f.startswith(check) for f in failed), (name, failed))


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_a_cup_and_a_point(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("a cup, wider at its rim", "sealed", "a funnel, open at both ends"):
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
