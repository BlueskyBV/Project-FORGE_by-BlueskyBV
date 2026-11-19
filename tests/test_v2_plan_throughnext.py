"""A cut through the next face, found by the preview and checked again by the judge (sizes.md, "Through the next
face"; V2-stage4b-0c.md, 3.5, item 2b's second step; schema 1.8).

- **Read and written:** ``{"through_next": true}``, with how deep the
  preview found it goes (``reaches``), read as the end it says and written
  back the same; below 1.8 it is a fault, and so is a ``reaches`` that is
  no depth.
- **The preview finds how deep:** on what is made before the cut, built:
  a solid box right through, a hollow box's top wall only, on through a
  boss made before under it, out into a pocket cut from the far side, a
  pocket on through a boss, a row of two; copies that come out at
  different depths are said, and given none; and past where it comes out,
  0.1 mm of air under all its mouth, or none found (its end is carried
  into it).
- **The spec can't be confirmed without it,** and a body made after it in
  its way is asked about.
- **What is built is what the preview found.** Each part built by the
  build loop, every face accounted for both ways, every check its spec
  compiles to passing; the judge finds the same depth on the oracle's
  shape.
- **A wrong depth is caught:** one the preview didn't find is refused by
  the judge, and one never found (the material under the face, as through
  all) fails it where the shape goes on.
- **The second kernel agrees** with the exact part.
- **The generator draws it:** its drafts say 1.8, and its own shape stops
  where it first comes out.
- **Round a side, on a ball's surface, on a cone's side** (item 2b's third
  step): a hole through the next face, how deep as the preview finds it
  along its axis, its mouth a disc square to it: a rod right across, a
  tube's wall into its bore, a dome out of its flat face, a ball seated in
  a plate on through it, a cone's side, one standing on a plate; built and
  judged; up to a face there, and from inside a bore, still said; the
  generator draws it on a ball or a cone.
- **On a turned or a leaning item's face** (item 2b's third step): placed
  as with the face upright, how deep along its axis where it is moved to:
  a hole and a pocket out through a leaning boss's or post's far face and
  on through the plate it leans on, a hole down through a turned post and
  the plate, one across it from its side; built and judged; the generator
  draws a hole so.
- **And through everything there** (item 2b's third step): as far as
  everything made before it reaches along its axis from its point, each
  copy from its own: round a rod, on a dome and a ball seated in a plate,
  a cone's side, out through a leaning boss and the plate, down through a
  turned post and the plate; every program's layout agrees, built and
  judged; a body made after it in its way is asked about; the second
  kernel agrees; the generator draws it round a side, on a ball or a
  cone, and on a turned item's face.
- **And up to a face from a turned or leaning item's face** (item 2b's third
  step): to that face's plane, square to the cut where it is moved to, less
  its offset: down through a turned post to the plate's bottom or top, from
  a leaning post's side to the plate's side; built and judged; one from a
  leaning item's far face, at a slant to every face, is said; the generator
  draws it on a leaning box's side.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan_throughall import _TEXT, _boss, _box, _hole, _hollow, _row
from v2_drafts import assumed, cite, draft
from v2_occ import needs_occ

NEXT = {"through_next": True, "from": {"assumed": "through to the next face"}}


def _next() -> dict[str, Any]:
    """A depth through the next face, a draft's own (its ``reaches`` is written into it)."""
    return {"through_next": True, "from": {"assumed": "through to the next face"}}


def _under(b: Any, item: str = "rod", d: float = 12.0, x: float = 0.0) -> dict[str, Any]:
    """A boss 10 mm tall standing under the box (on its -z face), ``x`` along from its middle."""
    return {**_boss(b), "id": item, "on": {"item": "box", "face": "-z"}, "diameter": assumed("across", d),
            "place": {"x": {"offset": assumed("off", x)}}}  # fmt: skip


def _far_pocket(b: Any, deep: float = 10.0) -> dict[str, Any]:
    return {"id": "far", "kind": "pocket", "words": cite(b, "pocket"), "on": {"item": "box", "face": "-z"},
            "shape": {"choose": "rectangle", "from": {"assumed": "square"}}, "length": assumed("long", 16.0),
            "width": assumed("wide", 16.0), "depth": assumed("deep", deep)}  # fmt: skip


def _pocket_next(b: Any) -> dict[str, Any]:
    return {"id": "hole", "kind": "pocket", "words": cite(b, "pocket"), "on": {"item": "box", "face": "+z"},
            "shape": {"choose": "rectangle", "from": {"assumed": "square"}}, "length": assumed("long", 8.0),
            "width": assumed("wide", 6.0), "depth": _next()}  # fmt: skip


#: Each part, and how deep its cut through the next face goes, as the preview finds it (mm).
CASES: dict[str, tuple[Any, float]] = {
    "a solid box": (lambda b: [_box(b), _hole(b, _next())], 30.0),
    "a hollow box's top wall": (lambda b: [_box(b), _hollow(b), _hole(b, _next())], 3.0),
    "on through a boss made before under it": (lambda b: [_box(b), _under(b), _hole(b, _next())], 40.0),
    "out into a pocket from the far side": (lambda b: [_box(b), _far_pocket(b), _hole(b, _next())], 20.0),
    "a pocket on through a boss": (lambda b: [_box(b), _under(b, d=20.0), _pocket_next(b)], 40.0),
    "a row of two over a wide boss": (lambda b: [_box(b), _under(b, d=36.0), _row(_hole(b, _next()))], 40.0),
}


def _draft(make: Any, version: str = "1.8") -> dict[str, Any]:
    from forge_spec.words import number_words

    found = draft("box", make(number_words(_TEXT)))
    found["schema_version"] = version
    return found


def _report(found: dict[str, Any]) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words

    return check_draft(number_words(_TEXT), found, strict=False)


def _reaches(found: dict[str, Any]) -> list[float | None]:
    return [item["depth"].get("reaches") for item in found["items"]
            if isinstance(item.get("depth"), dict) and "through_next" in item["depth"]]  # fmt: skip


class ReadAndWritten(unittest.TestCase):
    def test_the_end_and_its_depth(self) -> None:
        from forge_spec.draft import Through, read_draft
        from forge_spec.ends import ThroughAll, ThroughNext, end_of
        from forge_spec.wire import to_wire

        found = _draft(CASES["a solid box"][0])
        found["items"][-1]["depth"] = {**NEXT, "reaches": 30.0}
        spec, problems = read_draft(found)
        assert spec is not None and not problems.faults, problems.faults
        hole = spec.items[-1]
        self.assertIsInstance(hole.get("depth"), Through)
        self.assertTrue(hole.get("depth").next)
        end = end_of(hole)
        self.assertIsInstance(end, ThroughNext)
        self.assertIsInstance(end, ThroughAll)  # to what reads the model of the material, a through all
        self.assertEqual(end.reaches, 30.0)
        again, read = read_draft(to_wire(spec))
        self.assertFalse(read.faults)
        self.assertEqual(again, spec)

    def test_what_is_a_fault(self) -> None:
        from forge_spec.draft import read_draft

        for name, change, words in (
            ("below 1.8", lambda d: d.update(schema_version="1.7"), "schema 1.8"),
            ("a reaches of 0", lambda d: d["items"][-1]["depth"].update(reaches=0), "reaches is how deep"),
            ("a reaches that is words", lambda d: d["items"][-1]["depth"].update(reaches="deep"), "reaches is how deep"),
        ):  # fmt: skip
            with self.subTest(name):
                found = _draft(CASES["a solid box"][0])
                found["items"][-1]["depth"] = dict(NEXT)
                change(found)
                _, problems = read_draft(found)
                self.assertTrue(any(words in str(p) for p in problems.faults), [str(p) for p in problems.faults])


@needs_occ
class ThePreviewFindsHowDeep(unittest.TestCase):
    def test_each(self) -> None:
        from forge_occ.resolve import resolve_draft

        for name, (make, deep) in CASES.items():
            with self.subTest(name):
                resolved = resolve_draft(_draft(make))
                self.assertEqual(resolved.notes, ())
                for found in _reaches(resolved.draft):
                    self.assertAlmostEqual(found, deep, places=6)

    def test_copies_that_come_out_apart_are_said(self) -> None:
        from forge_occ.resolve import resolve_draft

        # One of the row over a narrow boss, the other beside it: 40 mm and 30 mm.
        make = lambda b: [_box(b), _under(b, d=8.0, x=-10.0), _row(_hole(b, _next(), d=4.0))]  # noqa: E731
        resolved = resolve_draft(_draft(make))
        self.assertEqual(_reaches(resolved.draft), [None])
        self.assertTrue(any("different depths" in why for _, why in resolved.notes), resolved.notes)

    def test_past_where_it_comes_out_air_to_carry_its_end_into(self) -> None:
        from forge_occ.resolve import _first_out, _UnresolvedError

        # The stretches of material along it: out at 10 mm, in again 0.2 mm on, found; 0.06 mm on, too little air.
        self.assertEqual(_first_out([(0.0, 6.0), (6.0, 10.0), (10.2, 14.0)], 30.0), 10.0)
        self.assertEqual(_first_out([(0.0, 10.0)], 30.0), 10.0)
        with self.assertRaisesRegex(_UnresolvedError, "only 0.06 mm of air past it"):
            _first_out([(0.0, 10.0), (10.06, 14.0)], 30.0)


class TheSpecWaitsForIt(unittest.TestCase):
    def test_not_confirmed_without_it(self) -> None:
        from forge_spec.lock import LockError, lock
        from forge_spec.words import number_words

        report = _report(_draft(CASES["a solid box"][0]))
        self.assertEqual(report.problems, ())
        with self.assertRaises(LockError) as caught:
            lock(report, number_words(_TEXT), by="draft", strict=False)
        self.assertIn("build the preview", str(caught.exception))

    def test_a_body_made_after_in_its_way_is_asked(self) -> None:
        found = _draft(lambda b: [_box(b), _hole(b, _next()), _under(b)])
        found["items"][1]["depth"]["reaches"] = 30.0
        report = _report(found)
        self.assertTrue(any("stands in its way" in p.message for p in report.problems),
                        [(p.kind, p.message) for p in report.problems])  # fmt: skip


def _confirmed(found: dict[str, Any]) -> Any:
    from forge_spec.lock import lock
    from forge_spec.words import number_words

    report = _report(found)
    assert not report.problems, [p.message for p in report.problems]
    return lock(report, number_words(_TEXT), by="draft", strict=False)


@needs_occ
class BuiltAsThePreviewFound(unittest.TestCase):
    def test_every_case(self) -> None:
        from forge_checks.classes import Verdict
        from forge_checks.place import place
        from forge_occ.resolve import resolve_draft
        from forge_plan import plan
        from test_v2_plan_build import judged_plan

        for name, (make, deep) in CASES.items():
            with self.subTest(name):
                spec = _confirmed(resolve_draft(_draft(make)).draft)
                hole = next(c for c in place(spec.spec).copies["hole"])
                self.assertAlmostEqual(hole.span[1], deep, places=5)  # the judge's own, on the oracle's shape
                built, accounting, failed = judged_plan(spec.spec, plan(spec))
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])


@needs_occ
class AWrongDepthIsCaught(unittest.TestCase):
    def test_one_the_preview_didnt_find(self) -> None:
        from forge_checks.place import PlaceError, place
        from forge_spec.draft import read_draft

        found = _draft(CASES["on through a boss made before under it"][0])
        found["items"][-1]["depth"]["reaches"] = 30.0
        spec, _ = read_draft(found)
        with self.assertRaises(PlaceError) as caught:
            place(spec)
        self.assertIn("on the oracle's shape it comes out 40 mm in", str(caught.exception))

    def test_one_never_found(self) -> None:
        from forge_checks.classes import Verdict
        from forge_plan.planner import _plan
        from forge_spec.placement import solve
        from test_v2_plan_build import judged_plan

        report = _report(_draft(CASES["on through a boss made before under it"][0]))
        planned = _plan(report.spec, solve(report.spec), digest=None)
        _, accounting, failed = judged_plan(report.spec, planned)
        self.assertTrue(accounting.verdict is Verdict.FAIL or failed, failed)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_through_the_next_face(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan
        from forge_occ.resolve import resolve_draft
        from forge_plan import plan

        for name in ("on through a boss made before under it", "out into a pocket from the far side"):
            with self.subTest(name):
                planned = plan(_confirmed(resolve_draft(_draft(CASES[name][0])).draft))
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


class TheGeneratorDrawsIt(unittest.TestCase):
    def test_its_drafts_say_18(self) -> None:
        from forge_eval.generator import draft_of

        self.assertEqual(draft_of([{"id": "h", "kind": "hole", "depth": NEXT}])["schema_version"], "1.8")

    def test_it_stops_where_it_first_comes_out(self) -> None:
        from dataclasses import replace

        from forge_eval.generator import End, Feature, render

        body = Feature("body", "block", {"length": 60.0, "width": 40.0, "height": 30.0})
        shell = Feature("i0", "shell", {"thickness": 3.0}, of="body", faces=())
        hole = replace(Feature("i1", "hole", {"diameter": 6.0}, ("body", "+z")), end=End(next=True))
        case = render((body, shell, hole))
        self.assertFalse(any(case.truth.inside([(0.0, 0.0, 28.5)])))  # out of the top wall
        self.assertTrue(all(case.truth.inside([(0.0, 0.0, 1.5)])))  # the floor under it is whole
        self.assertEqual(case.items[-1]["depth"]["through_next"], True)


_ROUND = "A rod, a tube, a ball on a plate and a cone, each with a hole right through."


def _round_hole(b: Any, on: str, face: str, **place: Any) -> dict[str, Any]:
    return {"id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": on, "face": face},
            "diameter": assumed("across", 4.0), "depth": _next(), "place": place}  # fmt: skip


def _rod(b: Any) -> dict[str, Any]:
    return {"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "diameter": assumed("across", 30.0),
            "length": assumed("long", 60.0)}  # fmt: skip


def _tube(b: Any) -> dict[str, Any]:
    return {"id": "rod", "kind": "tube", "words": cite(b, "tube"), "outer_diameter": assumed("across", 40.0),
            "inner_diameter": assumed("bore", 30.0), "length": assumed("long", 60.0)}  # fmt: skip


def _ball(b: Any, portion: str = "whole", on: str | None = None, across: float = 40.0) -> dict[str, Any]:
    found = {"id": "ball", "kind": "sphere", "words": cite(b, "ball"), "diameter": assumed("across", across),
             "portion": {"choose": portion, "from": {"assumed": "so"}}}  # fmt: skip
    if on is not None:
        found["on"] = {"item": on, "face": "+z"}
    return found


def _plate(b: Any) -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": assumed("long", 100.0),
            "width": assumed("wide", 60.0), "height": assumed("thick", 8.0)}  # fmt: skip


def _cone(b: Any, on: str | None = None) -> dict[str, Any]:
    found = {"id": "cone", "kind": "cone", "words": cite(b, "cone"), "base_diameter": assumed("base", 30.0),
             "top_diameter": assumed("top", 10.0), "length": assumed("long", 30.0)}  # fmt: skip
    if on is not None:
        found["on"] = {"item": on, "face": "+z"}
    return found


def _round(b: Any, latitude: float, angle: float) -> dict[str, Any]:
    return {"latitude": assumed("up", latitude, "deg"), "angle": assumed("round", angle, "deg")}


#: Each part (its first item first) and how deep its hole through the next face goes, as the preview finds it (mm).
ROUND: dict[str, tuple[Any, float]] = {
    "a rod right across": (lambda b: [_rod(b), _round_hole(b, "rod", "side", angle=assumed("round", 30.0, "deg"),
                                                           z={"offset": assumed("off", 5.0)})], 30.0),
    "a tube's wall, into its bore": (lambda b: [_tube(b), _round_hole(b, "rod", "side", angle=assumed("round", 30.0, "deg"),
                                                                      z={"offset": assumed("off", 5.0)})], 5.133931),
    "a dome, out of its flat face": (lambda b: [_ball(b, "upper_half"), _round_hole(b, "ball", "surface", **_round(b, 45.0, 30.0))],
                                     22.0),
    "a ball seated in a plate, on through it": (
        lambda b: [_plate(b), _ball(b, on="plate", across=30.0), _round_hole(b, "ball", "surface", **_round(b, 50.0, 100.0))],
        30.0),
    "a cone's side": (lambda b: [_cone(b), _round_hole(b, "cone", "side", angle=assumed("round", 30.0, "deg"))], 25.217083),
    "a cone standing on a plate": (
        lambda b: [_plate(b), _cone(b, on="plate"), _round_hole(b, "cone", "side", angle=assumed("round", 160.0, "deg"))],
        25.217083),
}


def _round_draft(make: Any) -> dict[str, Any]:
    from forge_spec.words import number_words

    items = make(number_words(_ROUND))
    found = draft(items[0]["id"], items)
    found["schema_version"] = "1.8"
    return found


def _round_confirmed(found: dict[str, Any]) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.lock import lock
    from forge_spec.words import number_words

    report = check_draft(number_words(_ROUND), found, strict=False)
    assert not report.problems, [p.message for p in report.problems]
    return lock(report, number_words(_ROUND), by="draft", strict=False)


@needs_occ
class RoundASideOnABallOrACone(unittest.TestCase):
    def test_the_preview_finds_how_deep(self) -> None:
        from forge_occ.resolve import resolve_draft

        for name, (make, deep) in ROUND.items():
            with self.subTest(name):
                resolved = resolve_draft(_round_draft(make))
                self.assertEqual(resolved.notes, ())
                self.assertEqual(len(_reaches(resolved.draft)), 1)
                self.assertAlmostEqual(_reaches(resolved.draft)[0], deep, places=5)

    def test_built_as_the_preview_found(self) -> None:
        from forge_checks.classes import Verdict
        from forge_checks.place import place
        from forge_occ.resolve import resolve_draft
        from forge_plan import plan
        from test_v2_plan_build import judged_plan

        for name, (make, deep) in ROUND.items():
            with self.subTest(name):
                spec = _round_confirmed(resolve_draft(_round_draft(make)).draft)
                (hole,) = place(spec.spec).copies["hole"]
                self.assertAlmostEqual(hole.span[1], deep, places=5)
                built, accounting, failed = judged_plan(spec.spec, plan(spec))
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_what_isnt_yet_is_said(self) -> None:
        from forge_spec.checks import check_draft
        from forge_spec.words import number_words

        up_to = {"up_to": {"item": "ball", "face": "surface"}, "from": {"assumed": "down to it"}}
        for make, words in (
            (lambda b: [_ball(b), {**_round_hole(b, "ball", "surface", **_round(b, 45.0, 30.0)), "depth": up_to}],
             "from a flat face, for now, not on a ball's surface"),
            (lambda b: [_tube(b), {**_round_hole(b, "rod", "bore"), "depth": _next()}], "the inside of a bore"),
        ):  # fmt: skip
            with self.subTest(words):
                found = _round_draft(make)
                report = check_draft(number_words(_ROUND), found, strict=False)
                self.assertTrue(any(words in p.message for p in report.problems), [p.message for p in report.problems])

    def test_the_second_kernel_agrees(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan
        from forge_occ.resolve import resolve_draft
        from forge_plan import plan

        for name in ("a dome, out of its flat face", "a cone's side"):
            with self.subTest(name):
                planned = plan(_round_confirmed(resolve_draft(_round_draft(ROUND[name][0])).draft))
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


def _moved_cases() -> dict[str, tuple[Any, float]]:
    """On a turned or a leaning item's face: each part, and how deep its cut through the next face goes (mm)."""
    from test_v2_plan_faceaxes import _hole as _on_post
    from test_v2_plan_faceaxes import _post
    from test_v2_plan_leanfar import _hole as _on_lean
    from test_v2_plan_leanfar import _leaning
    from test_v2_plan_leanfar import _pocket as _pocket_on_lean

    return {
        "a hole out through a leaning boss and the plate": (lambda b: [_leaning(b), {**_on_lean(b, "+end"), "depth": _next()}],
                                                             29.241363),
        "a pocket out through a leaning post and the plate": (
            lambda b: [_leaning(b, "post"), {**_pocket_on_lean(b, "+z"), "depth": _next()}], 29.969303),
        "a hole down through a turned post and the plate": (lambda b: [_post(b), {**_on_post(b), "depth": _next()}], 18.0),
        "a hole across a turned post from its side": (lambda b: [_post(b), {**_on_post(b, face="-y"), "depth": _next()}],
                                                      20.0),
        # Out of the side across, square to it: as wide as the post (place.md, "A leaning item's sides").
        "a hole across a leaning post from its side": (
            lambda b: [_leaning(b, "post"), {**_on_lean(b, "+y"), "depth": _next()}], 12.0),
    }  # fmt: skip


def _moved_draft(make: Any) -> dict[str, Any]:
    from forge_spec.words import number_words
    from test_v2_plan_faceaxes import _TEXT as _FACES
    from test_v2_plan_faceaxes import _plate

    b = number_words(_FACES)
    found = draft("plate", [_plate(b), *make(b)])
    found["schema_version"] = "1.8"
    return found


def _moved_confirmed(found: dict[str, Any]) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.lock import lock
    from forge_spec.words import number_words
    from test_v2_plan_faceaxes import _TEXT as _FACES

    report = check_draft(number_words(_FACES), found, strict=False)
    assert not report.problems, [p.message for p in report.problems]
    return lock(report, number_words(_FACES), by="draft", strict=False)


@needs_occ
class OnATurnedOrALeaningItemsFace(unittest.TestCase):
    def test_built_as_the_preview_found(self) -> None:
        from forge_checks.classes import Verdict
        from forge_checks.place import place
        from forge_occ.resolve import resolve_draft
        from forge_plan import plan
        from test_v2_plan_build import judged_plan

        for name, (make, deep) in _moved_cases().items():
            with self.subTest(name):
                resolved = resolve_draft(_moved_draft(make))
                self.assertEqual(resolved.notes, ())
                self.assertAlmostEqual(_reaches(resolved.draft)[0], deep, places=5)
                spec = _moved_confirmed(resolved.draft)
                (cut,) = place(spec.spec).copies["hole"]
                self.assertAlmostEqual(cut.span[1], deep, places=5)
                built, accounting, failed = judged_plan(spec.spec, plan(spec))
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_the_second_kernel_agrees(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan
        from forge_occ.resolve import resolve_draft
        from forge_plan import plan

        make = _moved_cases()["a hole out through a leaning boss and the plate"][0]
        planned = plan(_moved_confirmed(resolve_draft(_moved_draft(make)).draft))
        built = build_plan(planned)
        self.assertIsNone(built.gap, built.refusals)
        report = agree(planned.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))

    def test_the_generator_draws_a_hole_so(self) -> None:
        from forge_eval.generator import _build, generate

        case = generate(0)  # its hole on a turned item's face goes through the next face
        part = _build(case.plan, False)
        found = [f for f in case.plan if f.end is not None and f.end.next and f.on is not None
                 and (face := part.flats.get((f.on[0], 0, f.on[1]))) is not None and face.turned]  # fmt: skip
        self.assertTrue(found)
        self.assertTrue(all("through_next" in item["depth"] for item in case.items if item["id"] in {f.id for f in found}))


ALL = {"through_all": True, "from": {"assumed": "through everything"}}


def _everything_cases() -> dict[str, tuple[Any, str, float]]:
    """Through everything from a curved face, or a turned or leaning item's: each part, whether its draft is the round
    or the moved kind, and how deep its hole goes from its point as the solver places it (mm): as far as every item's
    box reaches behind it along its axis, and a millimetre on."""
    from test_v2_plan_faceaxes import _hole as _on_post
    from test_v2_plan_faceaxes import _post
    from test_v2_plan_leanfar import _hole as _on_lean
    from test_v2_plan_leanfar import _leaning

    return {
        # 15 mm to the rod's axis, and its box's corner 15 (cos 30 + sin 30) mm on.
        "round a rod": (lambda b: [_rod(b), {**_round_hole(b, "rod", "side", angle=assumed("round", 30.0, "deg"),
                                                           z={"offset": assumed("off", 5.0)}), "depth": ALL}],
                        "round", 15.0 + 15.0 * (3 ** 0.5 / 2 + 0.5) + 1.0),
        "a dome": (lambda b: [_ball(b, "upper_half"), {**_round_hole(b, "ball", "surface", **_round(b, 45.0, 30.0)),
                                                       "depth": ALL}], "round", 40.318517),
        "a ball seated in a plate": (
            lambda b: [_plate(b), _ball(b, on="plate", across=30.0),
                       {**_round_hole(b, "ball", "surface", **_round(b, 50.0, 100.0)), "depth": ALL}], "round", 46.699967),
        "a cone's side": (lambda b: [_cone(b), {**_round_hole(b, "cone", "side", angle=assumed("round", 30.0, "deg")),
                                                "depth": ALL}], "round", 34.669132),
        "out through a leaning boss and the plate": (lambda b: [_leaning(b), {**_on_lean(b, "+end"), "depth": ALL}],
                                                     "moved", 45.618548),
        # 10 mm of post and 8 of plate under its top, and a millimetre on.
        "down through a turned post and the plate": (lambda b: [_post(b), {**_on_post(b), "depth": ALL}], "moved", 19.0),
    }  # fmt: skip


def _everything_report(make: Any, kind: str) -> Any:
    from forge_spec.checks import check_draft
    from forge_spec.words import number_words
    from test_v2_plan_faceaxes import _TEXT as _FACES

    found, text = (_round_draft(make), _ROUND) if kind == "round" else (_moved_draft(make), _FACES)
    return check_draft(number_words(text), found, strict=False), number_words(text)


class ThroughEverythingFromACurvedOrAMovedFace(unittest.TestCase):
    def test_as_deep_as_everything_reaches(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, (make, kind, deep) in _everything_cases().items():
            with self.subTest(name):
                report, _ = _everything_report(make, kind)
                self.assertEqual(report.problems, ())
                (hole,) = report.layout.instances["hole"]
                self.assertAlmostEqual(hole.depth, deep, places=5)
                self.assertEqual(compare_layouts(place(report.spec), solve(report.spec)), ())

    def test_a_body_made_after_in_its_way_is_asked(self) -> None:
        # A boss under the plate, made after the hole through the seated ball and the plate, stands in its way; made
        # before it, it is cut through.
        def boss(b: Any) -> dict[str, Any]:
            return {"id": "under", "kind": "boss", "words": cite(b, "rod"), "on": {"item": "plate", "face": "-z"},
                    "diameter": assumed("across", 30.0), "height": assumed("tall", 10.0)}  # fmt: skip

        hole = _everything_cases()["a ball seated in a plate"][0]
        for make, asked in ((lambda b: [*hole(b), boss(b)], True), (lambda b: [*hole(b)[:2], boss(b), hole(b)[2]], False)):
            with self.subTest(asked=asked):
                report, _ = _everything_report(make, "round")
                said = [p for p in report.problems if "stands in its way" in p.message]
                self.assertEqual(bool(said), asked, [(p.kind, p.message) for p in report.problems])


@needs_occ
class ThroughEverythingBuiltAsPlaced(unittest.TestCase):
    def test_every_case(self) -> None:
        from forge_checks.classes import Verdict
        from forge_plan import plan
        from forge_spec.lock import lock
        from test_v2_plan_build import judged_plan

        for name, (make, kind, _) in _everything_cases().items():
            with self.subTest(name):
                report, brief = _everything_report(make, kind)
                spec = lock(report, brief, by="draft", strict=False)
                built, accounting, failed = judged_plan(spec.spec, plan(spec))
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_the_second_kernel_agrees(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan
        from forge_plan import plan
        from forge_spec.lock import lock

        for name in ("round a rod", "out through a leaning boss and the plate"):
            with self.subTest(name):
                make, kind, _ = _everything_cases()[name]
                report, brief = _everything_report(make, kind)
                planned = plan(lock(report, brief, by="draft", strict=False))
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report_ = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report_.holds, (report_.disagreements, report_.notes, report_.names, report_.topology))


def _up_to(item: str, face: str, offset: float | None = None) -> dict[str, Any]:
    found: dict[str, Any] = {"up_to": {"item": item, "face": face}, "from": {"assumed": "down to it"}}
    if offset is not None:
        found["offset"] = assumed("short", offset)
    return found


def _up_to_cases() -> dict[str, tuple[Any, float]]:
    """Up to a face from a turned or leaning item's face: each part, and how deep its hole goes from its point (mm)."""
    from test_v2_plan_faceaxes import _hole as _on_post
    from test_v2_plan_faceaxes import _post
    from test_v2_plan_leanfar import _hole as _on_lean
    from test_v2_plan_leanfar import _leaning

    return {
        # The turned post's top 18 mm over the plate's bottom, its plate's top 8.
        "down through a turned post to the plate's bottom, less 2": (
            lambda b: [_post(b), {**_on_post(b), "depth": _up_to("plate", "-z", 2.0)}], 16.0),
        "down a turned post to the plate's top, less 3": (
            lambda b: [_post(b), {**_on_post(b), "depth": _up_to("plate", "+z", 3.0)}], 7.0),
        # From the leaning post's +y side, 6 mm out from its axis, to the plate's -y side 30 mm the other way, less 25.
        "from a leaning post's side to the plate's side, less 25": (
            lambda b: [_leaning(b, "post"), {**_on_lean(b, "+y"), "depth": _up_to("plate", "-y", 25.0)}], 11.0),
    }  # fmt: skip


class UpToAFaceFromATurnedOrALeaningItemsFace(unittest.TestCase):
    def test_to_its_plane_where_it_is_moved_to(self) -> None:
        from forge_checks.place import compare_layouts, place
        from forge_spec.placement import solve

        for name, (make, deep) in _up_to_cases().items():
            with self.subTest(name):
                report, _ = _everything_report(make, "moved")
                self.assertEqual(report.problems, ())
                (hole,) = report.layout.instances["hole"]
                self.assertAlmostEqual(hole.depth, deep, places=9)
                self.assertEqual(compare_layouts(place(report.spec), solve(report.spec)), ())

    def test_from_a_leaning_far_face_it_is_said(self) -> None:
        from test_v2_plan_leanfar import _hole as _on_lean
        from test_v2_plan_leanfar import _leaning

        report, _ = _everything_report(lambda b: [_leaning(b), {**_on_lean(b, "+end"), "depth": _up_to("plate", "-z")}],
                                       "moved")  # fmt: skip
        self.assertTrue(any(p.kind == "unable" and "isn't square to hole" in p.message for p in report.problems),
                        [(p.kind, p.message) for p in report.problems])  # fmt: skip

    @needs_occ
    def test_built_and_judged(self) -> None:
        from forge_checks.classes import Verdict
        from forge_plan import plan
        from forge_spec.lock import lock
        from test_v2_plan_build import judged_plan

        for name, (make, _) in _up_to_cases().items():
            with self.subTest(name):
                report, brief = _everything_report(make, "moved")
                spec = lock(report, brief, by="draft", strict=False)
                built, accounting, failed = judged_plan(spec.spec, plan(spec))
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])

    def test_the_generator_draws_it(self) -> None:
        from forge_eval.generator import _build, generate

        case = generate(66)  # a hole into a leaning post's side, up to the block's side
        part = _build(case.plan, False)
        found = [f.end.face for f in case.plan if f.on is not None and f.end is not None and f.end.face is not None
                 and (key := (f.on[0], 0, f.on[1])) in part.flats and part.flats[key].leans]  # fmt: skip
        self.assertEqual(found, [("body", "-x")])


class TheGeneratorDrawsThroughEverythingThere(unittest.TestCase):
    def test_round_a_side_on_a_ball_or_a_cone_and_on_a_turned_face(self) -> None:
        from forge_eval.generator import _build, generate

        found = set()
        for seed in (0, 16, 29, 85):
            case = generate(seed)
            part = _build(case.plan, False)
            for f in case.plan:
                if f.on is None or f.end is None or f.end.face is not None or f.end.next:
                    continue
                key = (f.on[0], 0, f.on[1])
                found.add("round" if key in part.rounds else "ball" if key in part.balls else "cone" if key in part.cones
                          else "turned" if key in part.flats and part.flats[key].turned else "flat")  # fmt: skip
        self.assertTrue({"round", "ball", "cone", "turned"} <= found, found)


if __name__ == "__main__":
    unittest.main()
