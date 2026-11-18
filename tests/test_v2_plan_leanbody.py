"""A block or a cylinder leaning on its face (tilt, tilt_towards on a body; schema 1.5; V2-stage4b-0c.md, 3.3, 1b's
third move, step 3; place.md, "Leaning on the face").

- **Read in schema 1.5 only:** a body's lean in an older draft is a fault
  that names the version; a hole's, a boss's and a post's stay 1.3's.
- **Placed as a post or a boss leans:** its direction the face's normal
  turned towards its way, its height (a cylinder's length) along it, its
  box round it so; its faces take nothing yet, its edges aren't rounded and
  it isn't hollowed, for now. Two drafts compare it as the post or boss of
  its shape leaning.
- **What is built is what was placed.** A block leaning, turned and
  leaning, on a block's side; a cylinder leaning: built by the build loop,
  every face accounted for both ways, every check its spec compiles to
  passing.
- **A wrong lean is caught:** the same plan leaning half a degree more fails
  the judge.
- **A leaning rod is threaded along its lean** (step 5.4), from its far end
  and clear of its foot; threaded square to its face instead, the judge's
  checks fail.
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
from test_v2_plan_faceaxes import _judged, _planned
from v2_drafts import assumed, cite
from v2_occ import needs_occ


def _block(b: Any, tilt: float = 20.0, way: str = "+x", *, face: str = "+z",
           sizes: tuple[float, float, float] = (20.0, 10.0, 8.0), **more: Any) -> dict[str, Any]:  # fmt: skip
    return {"id": "leaning", "kind": "block", "words": cite(b, "post"), "on": {"item": "plate", "face": face},
            "length": assumed("long", sizes[0]), "width": assumed("wide", sizes[1]), "height": assumed("tall", sizes[2]),
            "tilt": assumed("leaning", tilt, "deg"), "tilt_towards": {"choose": way, "from": {"assumed": "that way"}},
            **more}  # fmt: skip


def _cylinder(b: Any, tilt: float = 30.0, way: str = "-y") -> dict[str, Any]:
    return {"id": "leaning", "kind": "cylinder", "words": cite(b, "post"), "on": {"item": "plate", "face": "+z"},
            "diameter": assumed("across", 8.0), "length": assumed("long", 12.0), "tilt": assumed("leaning", tilt, "deg"),
            "tilt_towards": {"choose": way, "from": {"assumed": "that way"}}, "place": {"x": {"offset": assumed("o", 30.0)}}}  # fmt: skip


#: Each part: what leans on the plate.
CASES: dict[str, Any] = {
    "a block leaning": lambda b: [_block(b)],
    "a block turned and leaning": lambda b: [_block(b, 25.0, "-y", place={"turn": assumed("turned", 30.0, "deg")})],
    "a block leaning on the plate's side": lambda b: [_block(b, 15.0, "+z", face="+y", sizes=(20.0, 6.0, 5.0))],
    "a cylinder leaning": lambda b: [_cylinder(b)],
}


class ABodysLeanIsSchema15s(unittest.TestCase):
    def _report(self, version: str, *items: dict[str, Any]) -> Any:
        from forge_spec.checks import check_draft
        from forge_spec.words import number_words
        from test_v2_plan_faceaxes import _TEXT, _plate
        from v2_drafts import draft

        brief = number_words(_TEXT)
        found = draft("plate", [_plate(brief), *(make(brief) for make in items)])
        found["schema_version"] = version
        return check_draft(brief, found, strict=False)

    def test_read_in_1_5_a_fault_before(self) -> None:
        old = self._report("1.4", lambda b: _block(b))
        faults = [p for p in old.problems if p.kind == "fault"]
        self.assertIn("/items/1/tilt", [p.at for p in faults])
        self.assertTrue(any('"schema_version": "1.5"' in p.message for p in faults))
        new = self._report("1.5", lambda b: _block(b), lambda b: {**_cylinder(b), "id": "rod"})
        self.assertEqual([p for p in new.problems if p.kind == "fault"], [])

    def test_placed_as_a_post_leans(self) -> None:
        report = self._report("1.5", lambda b: _block(b))
        (copy_,) = report.layout.instances["leaning"]
        c, s = math.cos(math.radians(20)), math.sin(math.radians(20))
        for got, want in zip(copy_.direction, (s, 0.0, c), strict=True):
            self.assertAlmostEqual(got, want, places=9)
        self.assertAlmostEqual(copy_.hi[2], 8.0 + 8.0 * c + 10.0 * s, places=9)  # its top's far corner, half its length along its lean
        # Only its far face takes anything (place.md, "A leaning item's far face").
        self.assertIn("+z", report.layout.faces[("leaning", 0)])
        self.assertNotIn("+z", report.layout.closed[("leaning", 0)])
        self.assertIn("+x", report.layout.closed[("leaning", 0)])

    def test_compared_as_a_post_or_a_boss_leaning(self) -> None:
        from forge_spec.compare import differences

        def differ(a: Any, b: Any) -> bool:
            return bool(differences(self._report("1.5", a), self._report("1.5", b)))

        def post(b: Any) -> dict[str, Any]:
            return {**_block(b), "kind": "post"}

        def boss(b: Any) -> dict[str, Any]:
            found = {**_cylinder(b), "kind": "boss", "height": _cylinder(b)["length"]}
            del found["length"]
            return found

        self.assertFalse(differ(lambda b: _block(b), lambda b: _block(b)))
        self.assertTrue(differ(lambda b: _block(b), lambda b: _block(b, 25.0)))
        self.assertFalse(differ(lambda b: _block(b), post))  # one shape, said either way
        self.assertFalse(differ(lambda b: _cylinder(b), boss))
        self.assertTrue(differ(lambda b: _cylinder(b), lambda b: _cylinder(b, way="+y")))


@needs_occ
class LeaningBodiesAreBuiltAsPlaced(unittest.TestCase):
    def test_every_case(self) -> None:
        from forge_checks.classes import Verdict

        for name, make in CASES.items():
            with self.subTest(name):
                built, accounting, failed = _judged(make)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])


@needs_occ
class AWrongLeanIsCaught(unittest.TestCase):
    def test_leaning_half_a_degree_more(self) -> None:
        import forge_plan.items.plan._tools as tools
        from forge_checks.classes import Verdict

        real = tools._leaning

        def more(copy: Any, face: Any) -> Any:
            _, n, w, c, s = real(copy, face)
            t = math.atan2(s, c) + math.radians(0.5)
            c, s = math.cos(t), math.sin(t)
            return tuple(c * n[k] + s * w[k] for k in range(3)), n, w, c, s

        for name in ("a block leaning", "a cylinder leaning"):
            with self.subTest(name), mock.patch.object(tools, "_leaning", more):
                built, accounting, _ = _judged(CASES[name])
                self.assertIsNone(built.gap)
                self.assertIs(accounting.verdict, Verdict.FAIL)


def _thread(b: Any, of: str, long: float, size: str) -> dict[str, Any]:
    return {"id": "thread", "kind": "thread", "words": cite(b, "post"), "of": of, "length": assumed("long", long),
            "designation": {"text": size, "from": {"assumed": size}}, "hand": {"choose": "right", "from": {"assumed": "r"}}}  # fmt: skip


#: A leaning rod threaded from its far end (step 5.4).
THREADED: dict[str, Any] = {
    "a leaning boss": lambda b: [{"id": "leaning", "kind": "boss", "words": cite(b, "boss"),
                                  "on": {"item": "plate", "face": "+z"}, "diameter": assumed("across", 8.0),
                                  "height": assumed("tall", 14.0), "tilt": assumed("leaning", 20.0, "deg"),
                                  "tilt_towards": {"choose": "+y", "from": {"assumed": "that way"}}},
                                 _thread(b, "leaning", 8.0, "M8")],
    "a leaning cylinder": lambda b: [{**_cylinder(b), "diameter": assumed("across", 10.0)}, _thread(b, "leaning", 6.0, "M10")],
}


@needs_occ
class ALeaningRodIsThreadedAlongItsLean(unittest.TestCase):
    def test_built_as_asked(self) -> None:
        from forge_checks.classes import Verdict

        for name, make in THREADED.items():
            with self.subTest(name):
                built, accounting, failed = _judged(make)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_threaded_square_to_its_face_is_caught(self) -> None:
        from dataclasses import replace

        import forge_plan.planner as planner

        real = planner.thread_step

        def square(chain: Any, ctx: Any, item: Any, copy: Any) -> Any:
            return real(chain, ctx, item, replace(copy, direction=None))  # along its face's normal, not its lean

        with mock.patch.object(planner, "thread_step", square):
            built, _, failed = _judged(THREADED["a leaning boss"])
        self.assertIsNone(built.gap)
        self.assertTrue(failed)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_a_block_and_a_cylinder(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("a block turned and leaning", "a cylinder leaning"):
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
