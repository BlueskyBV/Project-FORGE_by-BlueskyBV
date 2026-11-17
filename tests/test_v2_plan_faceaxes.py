"""Items placed along a face's own axes, and on a turned item's faces, planned, built and judged (place.u, place.v;
schema 1.4; V2-stage4b-0c.md, 3.3, 1b's third move; place.md, "On a flat face", "A turned item's far face" and "A
turned item's faces").

- **What is built is what was placed.** On a face whose axes are the part's,
  an item placed along ``u`` and ``v``; on a turned post's or block's far
  face, a hole right through or blind, a slot along its own axis, a round
  pocket, a boss, a post turned again, a leaning hole and a row of holes;
  on a turned post's sides, a hole right through or blind, a slot, a round
  pocket, a boss, a post turned in it, a leaning hole and a row of holes,
  and a hole in the side of a post turned on a turned post's side: built by
  the build loop, every face of it is accounted for both ways and every
  check its spec compiles to passes.
- **A wrong turn is caught.** The same plan with what is on the far face,
  or on a side, turned half a degree more fails the judge's face
  accounting.
- **The second kernel agrees** with the exact part, point by point, and
  names what it names: on a turned post's far face and on its sides.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, cite, draft, mm
from v2_occ import needs_occ

_TEXT = "A plate 100 mm long, 60 mm wide and 8 mm thick. A post stands on it with a hole, a slot, a pocket and a boss."


def _plate(b: Any) -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 100, "100 mm"),
            "width": mm(b, 60, "60 mm"), "height": mm(b, 8, "8 mm")}  # fmt: skip


def _post(b: Any, turn: float | None = 30.0, *, kind: str = "post", on: str = "plate", item: str = "post",
          sizes: tuple[float, float, float] = (30.0, 20.0, 10.0)) -> dict[str, Any]:  # fmt: skip
    length, width, height = sizes
    found = {"id": item, "kind": kind, "words": cite(b, "post"), "on": {"item": on, "face": "+z"},
             "length": assumed("long", length), "width": assumed("wide", width), "height": assumed("tall", height)}  # fmt: skip
    if turn is not None:
        found["place"] = {"turn": assumed("turned", turn, "deg")}
    return found


def _hole(b: Any, place: dict[str, Any] | None = None, *, on: str = "post", depth: float | None = None, face: str = "+z",
          **fields: Any) -> dict[str, Any]:  # fmt: skip
    found = {"id": "hole", "kind": "hole", "words": cite(b, "hole"), "on": {"item": on, "face": face},
             "diameter": assumed("across", 6.0), **fields}  # fmt: skip
    found["depth"] = {"through": True, "from": {"assumed": "through"}} if depth is None else assumed("deep", depth)
    if place is not None:
        found["place"] = place
    return found


def _planned(make: Any) -> tuple[Any, Any]:
    """The draft locked and planned: (the confirmed spec, the plan)."""
    from forge_plan import plan
    from forge_spec.checks import check_draft
    from forge_spec.lock import lock
    from forge_spec.words import number_words

    brief = number_words(_TEXT)
    found = draft("plate", [_plate(brief), *make(brief)])
    report = check_draft(brief, found, strict=False)
    assert not report.problems, [p.message for p in report.problems]
    spec = lock(report, brief, by="draft", strict=False)
    planned = plan(spec)
    assert not planned.gaps, [g.reason for g in planned.gaps]
    return spec, planned


def _judged(make: Any) -> tuple[Any, Any, list[str]]:
    from test_v2_plan_build import judged_plan

    spec, planned = _planned(make)
    return judged_plan(spec.spec, planned)


def _right(u: float) -> dict[str, Any]:
    return {"u": {"offset": assumed("right", u)}}


def _on(found: dict[str, Any], face: str, item: str = "post") -> dict[str, Any]:
    return {**found, "on": {"item": item, "face": face}}


#: Each part: what stands on the plate and what is on it.
CASES: dict[str, Any] = {
    "along u and v on the plate": lambda b: [_hole(b, {"u": {"side": "-u", "distance": assumed("in", 20.0)},
                                                       "v": {"offset": assumed("up", 9.0)}}, on="plate")],
    "a hole right through": lambda b: [_post(b), _hole(b, _right(8.0))],
    "a blind hole": lambda b: [_post(b, 45.0), _hole(b, {"v": {"side": "+v", "distance": assumed("in", 5.0)}}, depth=6.0)],
    "a slot along its own axis": lambda b: [_post(b), {
        "id": "slot", "kind": "slot", "words": cite(b, "slot"), "on": {"item": "post", "face": "+z"},
        "width": assumed("wide", 4.0), "length": assumed("long", 12.0), "depth": assumed("deep", 3.0),
        "along": {"choose": "u", "from": {"assumed": "along"}}, "ends": {"choose": "round", "from": {"assumed": "r"}},
        "place": {"v": {"offset": assumed("up", 3.0)}}}],
    "a round pocket": lambda b: [_post(b, 60.0), {
        "id": "pocket", "kind": "pocket", "words": cite(b, "pocket"), "on": {"item": "post", "face": "+z"},
        "shape": {"choose": "circle", "from": {"assumed": "round"}}, "diameter": assumed("across", 8.0),
        "depth": assumed("deep", 4.0), "place": _right(-5.0)}],
    "a boss": lambda b: [_post(b), {"id": "boss", "kind": "boss", "words": cite(b, "boss"), "on": {"item": "post", "face": "+z"},
                                     "diameter": assumed("across", 8.0), "height": assumed("tall", 5.0), "place": _right(6.0)}],
    "a post turned again": lambda b: [_post(b), _post(b, 25.0, on="post", item="upper", sizes=(8.0, 5.0, 6.0))],
    "a block turned": lambda b: [_post(b, 20.0, kind="block", sizes=(30.0, 20.0, 10.0)), _hole(b, _right(-7.0))],
    "a leaning hole": lambda b: [_post(b), _hole(b, None, depth=5.0, tilt=assumed("leaning", 20.0, "deg"),
                                                 tilt_towards={"choose": "-v", "from": {"assumed": "that way"}})],
    "a hole in a turned pocket's floor": lambda b: [{
        "id": "pocket", "kind": "pocket", "words": cite(b, "pocket"), "on": {"item": "plate", "face": "+z"},
        "shape": {"choose": "rectangle", "from": {"assumed": "square"}}, "length": assumed("long", 30.0),
        "width": assumed("wide", 16.0), "corner_radius": assumed("round", 2.0), "depth": assumed("deep", 3.0),
        "place": {"turn": assumed("turned", 30.0, "deg")}},
        {**_hole(b, _right(6.0), on="pocket"), "on": {"item": "pocket", "face": "bottom"}}],
    "a row of holes": lambda b: [_post(b), _hole(b, {"pattern": {"row": {
        "count": {"count": 2, "from": {"assumed": "two"}}, "pitch": assumed("apart", 14.0),
        "axis": {"choose": "u", "from": {"assumed": "along"}}}}}, count={"count": 2, "from": {"assumed": "two"}})],
    # On its sides (step 2): placed on them upright, then turned with it.
    "a hole right through its side": lambda b: [_post(b), _hole(b, _right(2.0), face="+y")],
    "a blind hole in its side": lambda b: [_post(b), _hole(b, {**_right(3.0), "v": {"offset": assumed("up", 1.0)}},
                                                          depth=6.0, face="+x")],
    "a slot in its side": lambda b: [_post(b), _on({
        "id": "slot", "kind": "slot", "words": cite(b, "slot"), "width": assumed("wide", 3.0),
        "length": assumed("long", 10.0), "depth": assumed("deep", 2.0), "along": {"choose": "u", "from": {"assumed": "a"}},
        "ends": {"choose": "round", "from": {"assumed": "r"}}}, "-y")],
    "a round pocket in its side": lambda b: [_post(b, 45.0), _on({
        "id": "pocket", "kind": "pocket", "words": cite(b, "pocket"), "shape": {"choose": "circle", "from": {"assumed": "o"}},
        "diameter": assumed("across", 5.0), "depth": assumed("deep", 3.0), "place": _right(-6.0)}, "-x")],
    "a boss on its side": lambda b: [_post(b), _on({"id": "boss", "kind": "boss", "words": cite(b, "boss"),
                                                    "diameter": assumed("across", 6.0), "height": assumed("tall", 5.0)}, "-x")],
    "a post turned on its side": lambda b: [_post(b), _post(b, 20.0, on="post", item="upper", sizes=(6.0, 4.0, 5.0)) | {
        "on": {"item": "post", "face": "+y"}}],
    "a leaning hole in its side": lambda b: [_post(b), _hole(b, None, depth=5.0, face="-y", tilt=assumed("leaning", 20.0, "deg"),
                                                            tilt_towards={"choose": "+u", "from": {"assumed": "that way"}})],
    "a row of holes in its side": lambda b: [_post(b), _hole(b, {"pattern": {"row": {
        "count": {"count": 2, "from": {"assumed": "two"}}, "pitch": assumed("apart", 12.0),
        "axis": {"choose": "u", "from": {"assumed": "along"}}}}}, face="+x", count={"count": 2, "from": {"assumed": "two"}})],
    "a hole in the side of a post turned on its side": lambda b: [
        _post(b), _post(b, 20.0, on="post", item="upper", sizes=(8.0, 6.0, 5.0)) | {"on": {"item": "post", "face": "+x"}},
        _hole(b, None, on="upper", face="+y", depth=3.0) | {"diameter": assumed("across", 2.0)}],
}


class WhatIsWrittenTurnsWithTheFace(unittest.TestCase):
    def test_a_slot_on_a_turned_face_is_cut_as_one_turned_by_both(self) -> None:
        def written(make: Any) -> list[str]:
            _, planned = _planned(make)
            return [s["op"] for s in planned.written().chain.steps if "slot" in s["for_items"]]

        def on_the_plate(b: Any) -> list[dict[str, Any]]:
            slot = CASES["a slot along its own axis"](b)[1]
            return [{**slot, "on": {"item": "plate", "face": "+z"}, "along": {"choose": "x", "from": {"assumed": "a"}},
                     "place": {"turn": assumed("turned", 30.0, "deg")}}]  # fmt: skip

        self.assertEqual(written(CASES["a slot along its own axis"]), written(on_the_plate))


@needs_occ
class ItemsOnATurnedFaceAreBuiltAsPlaced(unittest.TestCase):
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
        from dataclasses import replace

        import forge_plan.planner as planner
        from forge_checks.classes import Verdict
        from forge_spec.values import Value
        from forge_units import Q

        real = planner.placed_spec

        def more(spec: Any, layout: Any) -> Any:
            """The planner's spec as placed, with what is on the post's far face turned half a degree more."""
            found = real(spec, layout)
            items = []
            for item in found.items:
                place, on = item.get("place"), item.get("on")
                if getattr(on, "item", None) == "post" and place is not None and place.turn is not None:
                    turn = Value(Q(place.turn.made_in("deg") + 0.5, "deg"), place.turn.provenance)
                    item = replace(item, fields={**item.fields, "place": replace(place, turn=turn)})
                items.append(item)
            return replace(found, items=tuple(items))

        for name in ("a slot along its own axis", "a post turned again"):
            with self.subTest(name), mock.patch.object(planner, "placed_spec", more):
                built, accounting, _ = _judged(CASES[name])
                self.assertIsNone(built.gap)
                self.assertIs(accounting.verdict, Verdict.FAIL)

    def test_what_is_on_its_side_turned_half_a_degree_more(self) -> None:
        import forge_plan.moved as moved
        from forge_checks.classes import Verdict

        real = moved.transform_params

        def more(motion: Any) -> dict[str, Any]:
            """The motion onto the part of what is on a turned post's side, turned half a degree more."""
            found = real(motion)
            angle = found["rotate_angle"]
            return {**found, "rotate_angle": {**angle, "magnitude": angle["magnitude"] + 0.5}}

        for name in ("a hole right through its side", "a boss on its side"):
            with self.subTest(name), mock.patch.object(moved, "transform_params", more):
                built, accounting, _ = _judged(CASES[name])
                self.assertIsNone(built.gap)
                self.assertIs(accounting.verdict, Verdict.FAIL)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_a_turned_post_and_what_is_on_its_faces(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        def make(b: Any) -> list[dict[str, Any]]:
            return [*CASES["a post turned again"](b), _hole(b, {"u": {"offset": assumed("left", -9.0)}})]

        # On its sides, what is cut or joined there is built upright and turned with it: the faces its tool had at
        # its mouth, where they are once turned, are in the air.
        for name, case in (("on its far face", make), ("on its sides", CASES["a hole right through its side"]),
                           ("on a post turned on its side", CASES["a hole in the side of a post turned on its side"])):  # fmt: skip
            with self.subTest(name):
                _, planned = _planned(case)
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
