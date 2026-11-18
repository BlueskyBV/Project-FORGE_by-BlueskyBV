"""A cut through everything, and one up to a face (sizes.md, "Through everything, and up to a face"; frame.md;
V2-stage4b-0c.md, 3.5, item 2b's first step; schema 1.7).

- **Read and written:** ``{"through_all": true}`` and ``{"up_to": {...},
  "offset": ...}`` read as the ends they say, written back the same; a
  draft below 1.7 that gives one is a fault.
- **Placed as deep as it goes:** through everything, past all that is made
  before it behind its mouth; up to a face, to its plane less the offset;
  every program's layout agrees.
- **What isn't so is said:** a face not behind the mouth, one not parallel,
  no such item or face, an item with two copies, a leaning cut, one round a
  side, one deeper than the material under it, a counterbore as deep as the
  hole goes; a body made after a cut through everything in its way is
  asked about (made before it, it is cut through).
- **What is built is what was placed.** Through everything a hollow box's
  two walls (down and from its side), a plate and the block it stands on,
  a hollow box and a boss made before under it, a row of two, a slot; up
  to a face, a hole, a pocket down to a ledge's base, a turned pocket:
  built by the build loop, every face accounted for both ways, every check
  its spec compiles to passing.
- **A wrong end is caught:** one wall built where everything is asked, two
  where one is, and a floor a millimetre off its face's plane each fail the
  judge.
- **The second kernel agrees** with the exact part.
- **The generator draws them:** its drafts say 1.7, a cut through
  everything goes out of a hollow's far wall in its own model, and nothing
  made after it that adds to the part stands in its way.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, cite, draft, mm
from v2_occ import needs_occ

_TEXT = "A box 60 mm long, 40 mm wide and 30 mm tall, hollow, with a hole through it and a pocket down to the ledge."
ALL = {"through_all": True, "from": {"assumed": "through it"}}
THROUGH = {"through": True, "from": {"assumed": "through it"}}


def _box(b: Any) -> dict[str, Any]:
    return {"id": "box", "kind": "block", "words": cite(b, "box"), "length": mm(b, 60, "60 mm"),
            "width": mm(b, 40, "40 mm"), "height": mm(b, 30, "30 mm")}  # fmt: skip


def _hollow(b: Any) -> dict[str, Any]:
    return {"id": "hollow", "kind": "shell", "words": cite(b, "hollow"), "of": "box",
            "thickness": assumed("thick", 3.0), "open": {"faces": [], "from": {"assumed": "sealed"}}}  # fmt: skip


def _hole(b: Any, depth: Any, face: str = "+z", item: str = "hole", on: str = "box", d: float = 6.0,
          **place: Any) -> dict[str, Any]:  # fmt: skip
    found = {"id": item, "kind": "hole", "words": cite(b, "hole"), "on": {"item": on, "face": face},
             "diameter": assumed("across", d), "depth": depth}  # fmt: skip
    if place:
        found["place"] = place
    return found


def _up_to(item: str, face: str, offset: float | None = None) -> dict[str, Any]:
    found: dict[str, Any] = {"up_to": {"item": item, "face": face}, "from": {"assumed": "down to it"}}
    if offset is not None:
        found["offset"] = assumed("short", offset)
    return found


def _ledge(b: Any) -> dict[str, Any]:
    return {"id": "ledge", "kind": "block", "words": cite(b, "ledge"), "on": {"item": "box", "face": "+z"},
            "length": assumed("long", 20.0), "width": assumed("wide", 40.0), "height": assumed("tall", 5.0),
            "place": {"x": {"side": "-x", "distance": assumed("in", 0.0), "to": "edge"}}}  # fmt: skip


def _pocket(b: Any, depth: Any, on: str = "box", **place: Any) -> dict[str, Any]:
    found = {"id": "pocket", "kind": "pocket", "words": cite(b, "pocket"), "on": {"item": on, "face": "+z"},
             "shape": {"choose": "rectangle", "from": {"assumed": "square"}}, "length": assumed("long", 10.0),
             "width": assumed("wide", 6.0), "depth": depth}  # fmt: skip
    if place:
        found["place"] = place
    return found


def _slot(b: Any, depth: Any) -> dict[str, Any]:
    return {"id": "slot", "kind": "slot", "words": cite(b, "hole"), "on": {"item": "box", "face": "+z"},
            "length": assumed("long", 16.0), "width": assumed("wide", 5.0), "depth": depth,
            "along": {"choose": "x", "from": {"assumed": "along"}},
            "ends": {"choose": "round", "from": {"assumed": "round"}}}  # fmt: skip


def _boss(b: Any) -> dict[str, Any]:
    return {"id": "rod", "kind": "boss", "words": cite(b, "hole"), "on": {"item": "box", "face": "+z"},
            "diameter": assumed("across", 12.0), "height": assumed("tall", 10.0)}  # fmt: skip


def _row(found: dict[str, Any]) -> dict[str, Any]:
    two = {"count": 2, "from": {"assumed": "two"}}
    return {**found, "count": two, "place": {"pattern": {"row": {"count": two, "pitch": assumed("apart", 20.0),
                                                                  "axis": {"choose": "x", "from": {"assumed": "along"}}}}}}  # fmt: skip


#: Each part, and how deep its one cut goes from its point, as every program places it (mm): through everything a
#: millimetre past all of the part behind its mouth (the solver's own margin), up to a face to its plane less the
#: offset.
CASES: dict[str, tuple[Any, float]] = {
    "through all a hollow box": (lambda b: [_box(b), _hollow(b), _hole(b, ALL)], 31.0),
    "through all a hollow box from its side": (lambda b: [_box(b), _hollow(b), _hole(b, ALL, face="+x")], 61.0),
    "through all a plate and its block": (lambda b: [_box(b), _ledge(b), _hole(b, ALL, on="ledge")], 36.0),
    "through all a hollow box and a boss under it": (
        lambda b: [_box(b), _hollow(b), {**_boss(b), "on": {"item": "box", "face": "-z"}}, _hole(b, ALL)], 41.0),
    "a row of two through all": (lambda b: [_box(b), _hollow(b), _row(_hole(b, ALL))], 31.0),
    "a slot through all": (lambda b: [_box(b), _hollow(b), _slot(b, ALL)], 31.0),
    "a hole up to the bottom less 4": (lambda b: [_box(b), _hole(b, _up_to("box", "-z", 4.0))], 26.0),
    "a pocket down to the ledge's base less 2": (
        lambda b: [_box(b), _ledge(b), _pocket(b, _up_to("box", "+z", 2.0), on="ledge")], 3.0),
    "a turned pocket up to the bottom less 10": (
        lambda b: [_box(b), _pocket(b, _up_to("box", "-z", 10.0), turn=assumed("turned", 30.0, "deg"))], 20.0),
}


def _report(make: Any, version: str = "1.7") -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    b = number_words(_TEXT)
    found = draft("box", make(b))
    found["schema_version"] = version
    return check_draft(b, found, strict=False)


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


def _cut(spec: Any) -> str:
    return next(item.id for item in spec.spec.items if item.kind in ("hole", "pocket", "slot"))


class ReadAndWritten(unittest.TestCase):
    def test_the_ends(self) -> None:
        from forge_spec.draft import Through, UpTo
        from forge_spec.ends import ThroughEverything, UpToFace, end_of

        spec, _ = _planned(CASES["through all a hollow box"][0])
        (hole,) = [i for i in spec.spec.items if i.id == "hole"]
        self.assertIsInstance(hole.get("depth"), Through)
        self.assertTrue(hole.get("depth").everything)
        self.assertIsInstance(end_of(hole), ThroughEverything)
        spec, _ = _planned(CASES["a hole up to the bottom less 4"][0])
        (hole,) = [i for i in spec.spec.items if i.id == "hole"]
        self.assertIsInstance(hole.get("depth"), UpTo)
        end = end_of(hole)
        self.assertIsInstance(end, UpToFace)
        self.assertEqual((end.face.item, end.face.face), ("box", "-z"))

    def test_written_back_the_same(self) -> None:
        from forge_spec.draft import read_draft
        from forge_spec.wire import to_wire

        for name in ("through all a hollow box", "a hole up to the bottom less 4", "a pocket down to the ledge's base less 2"):
            with self.subTest(name):
                spec, _ = _planned(CASES[name][0])
                again, problems = read_draft(to_wire(spec.spec))
                self.assertFalse(problems.faults)
                self.assertEqual(again, spec.spec)

    def test_below_17_is_a_fault(self) -> None:
        for name in ("through all a hollow box", "a hole up to the bottom less 4"):
            with self.subTest(name):
                report = _report(CASES[name][0], "1.6")
                self.assertTrue(any(p.kind == "fault" and "schema 1.7" in p.message for p in report.problems),
                                [(p.kind, p.message) for p in report.problems])  # fmt: skip


class PlacedAsDeepAsItGoes(unittest.TestCase):
    def test_its_depth(self) -> None:
        from forge_spec.placement import cut_depth

        for name, (make, deep) in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                cut = _cut(spec)
                item = next(i for i in spec.spec.items if i.id == cut)
                layout = _report(make).layout
                for copy in layout.instances[cut]:
                    self.assertAlmostEqual(cut_depth(item, copy, layout), deep, places=9)

    def test_every_programs_layout_agrees(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, (make, _) in CASES.items():
            with self.subTest(name):
                spec, _ = _planned(make)
                self.assertEqual(compare_layouts(place(spec.spec), solve(spec.spec)), ())


class WhatIsntSoIsSaid(unittest.TestCase):
    def test_each(self) -> None:
        leaning = {"tilt": assumed("leaning", 10.0, "deg"), "tilt_towards": {"choose": "+x", "from": {"assumed": "x"}}}
        for make, kind, words in (
            (lambda b: [_box(b), _hole(b, _up_to("box", "+z"))], "question", "isn't behind hole's mouth"),
            (lambda b: [_box(b), _hole(b, _up_to("box", "+x"))], "unable", "isn't square to hole"),
            (lambda b: [_box(b), _hole(b, _up_to("nothing", "+z"))], "fault", "no item 'nothing' to cut up to"),
            (lambda b: [_box(b), _hole(b, _up_to("box", "top"))], "fault", "box has no face 'top'"),
            (lambda b: [_box(b), _row({**_ledge(b), "kind": "post", "place": {}}), _hole(b, _up_to("ledge", "+z"), face="-z")],
             "unable", "has 2 copies"),
            (lambda b: [_box(b), {**_hole(b, ALL), **leaning}], "unable", "a leaning item through everything"),
            (lambda b: [_box(b), _boss(b), _hole(b, ALL, on="rod", face="side")], "unable", "not round a side"),
            (lambda b: [_box(b), _hollow(b), _hole(b, _up_to("box", "-z", 4.0))], "fault", "mm of material"),
            (lambda b: [_box(b), {**_hole(b, _up_to("box", "-z", 26.0)), "counterbore": {
                "diameter": assumed("across", 10.0), "depth": assumed("deep", 5.0)}}], "fault",
             "the counterbore (5 mm deep) is as deep as the hole goes"),
        ):  # fmt: skip
            with self.subTest(words):
                report = _report(make)
                self.assertTrue(any(p.kind == kind and words in p.message for p in report.problems),
                                [(p.kind, p.message) for p in report.problems])  # fmt: skip


class ABodyMadeAfterInItsWayIsAsked(unittest.TestCase):
    def test_under_its_way_out_and_beside_it(self) -> None:
        def boss(b: Any, x: float) -> dict[str, Any]:
            return {**_boss(b), "on": {"item": "box", "face": "-z"}, "place": {"x": {"offset": assumed("off", x)}}}

        for x, asked in ((0.0, True), (4.0, True), (12.0, False)):
            with self.subTest(x=x):
                report = _report(lambda b, x=x: [_box(b), _hollow(b), _hole(b, ALL), boss(b, x)])
                said = [p for p in report.problems if "stands in its way" in p.message]
                self.assertEqual(bool(said), asked, [(p.kind, p.message) for p in report.problems])
        # Made before it, it is cut through: nothing to ask.
        report = _report(lambda b: [_box(b), _hollow(b), boss(b, 0.0), _hole(b, ALL)])
        self.assertFalse([p for p in report.problems if p.kind in ("fault", "unable", "cant", "question")],
                         [(p.kind, p.message) for p in report.problems])  # fmt: skip


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


def _cross(judge: Any, build: Any) -> tuple[Any, list[str]]:
    """The part ``build`` makes, judged against the spec ``judge`` says."""
    from forge_checks.accounting import account_faces
    from forge_checks.classes import Verdict
    from forge_checks.compiler import compile_checks
    from forge_checks.measure import Probe
    from forge_checks.oracle import oracle
    from forge_checks.place import place
    from forge_checks.view import ViewProxy
    from forge_occ.planned import build_plan
    from forge_occ.view import BrepView

    _, planned = _planned(build)
    built = build_plan(planned)
    assert built.result is not None, built.refusals
    spec, _ = _planned(judge)
    placed = place(spec.spec)
    part = oracle(spec.spec, placed)
    view = ViewProxy(BrepView(built.result.shape))
    accounting = account_faces(part, view, 1.0)
    suite = compile_checks(spec.spec, placed, part)
    probe = Probe(view, part, suite.resolution)
    return accounting.verdict, [c.id for c in suite.checks if c.run(probe).verdict is not Verdict.PASS]


@needs_occ
class AWrongEndIsCaught(unittest.TestCase):
    def test_each(self) -> None:
        from forge_checks.classes import Verdict

        for name, judge, build in (
            ("one wall built, everything asked", lambda b: [_box(b), _hollow(b), _hole(b, ALL)],
             lambda b: [_box(b), _hollow(b), _hole(b, THROUGH)]),
            ("everything built, one wall asked", lambda b: [_box(b), _hollow(b), _hole(b, THROUGH)],
             lambda b: [_box(b), _hollow(b), _hole(b, ALL)]),
            ("a hole's floor a millimetre short", lambda b: [_box(b), _hole(b, _up_to("box", "-z", 4.0))],
             lambda b: [_box(b), _hole(b, _up_to("box", "-z", 5.0))]),
            ("a pocket's floor a millimetre deep", lambda b: [_box(b), _ledge(b), _pocket(b, _up_to("box", "+z", 2.0), on="ledge")],
             lambda b: [_box(b), _ledge(b), _pocket(b, _up_to("box", "+z", 1.0), on="ledge")]),
        ):  # fmt: skip
            with self.subTest(name):
                verdict, failed = _cross(judge, build)
                self.assertTrue(verdict is Verdict.FAIL or failed, (verdict, failed))


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_through_everything_and_up_to_a_face(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("through all a hollow box", "a pocket down to the ledge's base less 2",
                     "a turned pocket up to the bottom less 10"):  # fmt: skip
            with self.subTest(name):
                _, planned = _planned(CASES[name][0])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


class TheGeneratorDrawsThem(unittest.TestCase):
    def test_its_drafts_say_17(self) -> None:
        from forge_eval.generator import draft_of

        for depth in (ALL, _up_to("body", "-z", 2.0)):
            with self.subTest(next(iter(depth))):
                self.assertEqual(draft_of([{"id": "h", "kind": "hole", "depth": depth}])["schema_version"], "1.7")
        self.assertNotEqual(draft_of([{"id": "h", "kind": "hole", "depth": THROUGH}]).get("schema_version"), "1.7")

    def test_through_everything_out_of_a_hollows_far_wall(self) -> None:
        from forge_eval.generator import Feature, render

        body = Feature("body", "block", {"length": 60.0, "width": 40.0, "height": 30.0})
        shell = Feature("i0", "shell", {"thickness": 3.0}, of="body", faces=())
        hole = Feature("i1", "hole", {"diameter": 6.0}, ("body", "+z"))
        cases = {"through": render((body, shell, hole)), "everything": render((body, shell, _everything(hole)))}
        floor = [(0.0, 0.0, 1.5), (2.0, 0.0, 1.5)]  # in the bottom wall, under the hole
        self.assertTrue(all(cases["through"].truth.inside(floor)))
        self.assertFalse(any(cases["everything"].truth.inside(floor)))
        self.assertEqual(cases["everything"].items[-1]["depth"]["through_all"], True)


class TheGeneratorKeepsItsWayClear(unittest.TestCase):
    def test_nothing_made_after_stands_in_it(self) -> None:
        from forge_eval.generator import DoesNotFitError, Feature, Position, render

        # A hole through everything across a post under the body, its way on past the post under the body; a block
        # under the body there, made after it, would stand in it.
        body = Feature("body", "block", {"length": 60.0, "width": 40.0, "height": 30.0})
        post = Feature("i0", "block", {"length": 10.0, "width": 10.0, "height": 12.0}, ("body", "-z"))
        hole = _everything(Feature("i1", "hole", {"diameter": 4.0}, ("i0", "+y")))

        def block(x: float) -> Feature:
            return Feature("i2", "block", {"length": 6.0, "width": 4.0, "height": 10.0}, ("body", "-z"),
                           place={"x": Position("offset", x), "y": Position("offset", -12.0)})  # fmt: skip

        with self.assertRaises(DoesNotFitError) as caught:
            render((body, post, hole, block(0.0)))
        self.assertIn("stands in the way of i1", str(caught.exception))
        render((body, post, hole, block(15.0)))  # beside its way, it stands
        render((body, post, block(0.0), hole))  # made before it, it is cut through


def _everything(f: Any) -> Any:
    from dataclasses import replace

    from forge_eval.generator import End

    return replace(f, end=End())


if __name__ == "__main__":
    unittest.main()
