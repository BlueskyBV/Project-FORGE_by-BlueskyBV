"""A turned item's edges, those of what is on a turned item's faces, and a leaning item's far end's and those along its
lean, rounded and chamfered (edges.md, "A turned item's edges", "A leaning item's edges"; V2-stage4b-0c.md, 3.3, 1b's
third move, steps 2c and 5.3).

- **What is built is what was asked.** A turned post's vertical, top and
  joint edges; a turned block's top edges bevelled and, turned a quarter
  turn, its vertical edges rounded; a turned rib's top edges; a turned
  pocket's floor and a turned slot's mouth; a boss's rim and a hole's mouth
  on a turned post's side; a block turned on a turned post's side, its top
  edges; and a post turned on a turned post's far face, its vertical edges:
  each read by the solver as an upright item's would be, built by the build
  loop, every face accounted for both ways, every check its spec compiles to
  passing.
- **An edge left sharp is caught.** The same plan with one of its edges'
  queries left out fails the judge.
- **The second kernel agrees** with the exact part and names alike.
- **A leaning box's long edges are rounded on the part only:** not early on
  its tool, nor as the regions round its box, neither of which is made for
  a leaning item (generated part 596: early was offered, and its tool
  refused it).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan_faceaxes import _hole, _judged, _on, _planned, _post, _right
from v2_drafts import assumed, cite
from v2_occ import needs_occ


def _rounding(b: Any, of: str, which: str, kind: str = "fillet", size: float = 1.0, **more: Any) -> dict[str, Any]:
    return {"id": "round", "kind": kind, "words": cite(b, "post"), ("radius" if kind == "fillet" else "size"):
            assumed("small", size), "edges": {"of": of, "which": which, **more}}  # fmt: skip


def _block(b: Any, turn: float, on: str = "plate", face: str = "+z", sizes: tuple[float, float, float] = (20, 12, 6),
           ) -> dict[str, Any]:  # fmt: skip
    return {"id": "block", "kind": "block", "words": cite(b, "post"), "on": {"item": on, "face": face},
            "length": assumed("long", sizes[0]), "width": assumed("wide", sizes[1]), "height": assumed("tall", sizes[2]),
            "place": {"turn": assumed("turned", turn, "deg")}}  # fmt: skip


def _turned_cut(b: Any, kind: str) -> dict[str, Any]:
    place = {"x": {"offset": assumed("over", 30.0)}, "turn": assumed("turned", 30.0, "deg")}
    if kind == "pocket":
        return {"id": "cut", "kind": "pocket", "words": cite(b, "pocket"), "on": {"item": "plate", "face": "+z"},
                "shape": {"choose": "rectangle", "from": {"assumed": "square"}}, "length": assumed("long", 20.0),
                "width": assumed("wide", 10.0), "corner_radius": assumed("round", 2.0), "depth": assumed("deep", 3.0),
                "place": place}  # fmt: skip
    return {"id": "cut", "kind": "slot", "words": cite(b, "slot"), "on": {"item": "plate", "face": "+z"},
            "width": assumed("wide", 4.0), "length": assumed("long", 12.0), "depth": assumed("deep", 3.0),
            "along": {"choose": "x", "from": {"assumed": "along"}}, "ends": {"choose": "round", "from": {"assumed": "r"}},
            "place": place}  # fmt: skip


def _leaning(b: Any, kind: str, tilt: float = 20.0, way: str = "+x", turn: float | None = None) -> dict[str, Any]:
    """A post, a block (12 by 8, 10 tall), a boss or a cylinder (10 across, 8 tall) leaning on the plate."""
    found = {"id": "leaning", "kind": kind, "words": cite(b, "post"), "on": {"item": "plate", "face": "+z"},
             "tilt": assumed("leaning", tilt, "deg"), "tilt_towards": {"choose": way, "from": {"assumed": "that way"}}}  # fmt: skip
    if kind in ("post", "block"):
        found |= {"length": assumed("long", 12.0), "width": assumed("wide", 8.0), "height": assumed("tall", 10.0)}
    else:
        found |= {"diameter": assumed("across", 10.0), ("height" if kind == "boss" else "length"): assumed("tall", 8.0)}
    if turn is not None:
        found["place"] = {"turn": assumed("turned", turn, "deg")}
    return found


#: Each part: what is turned, and what of it is rounded or bevelled.
CASES: dict[str, Any] = {
    "a turned post's vertical edges": lambda b: [_post(b), _rounding(b, "post", "vertical")],
    "a turned post's top edges": lambda b: [_post(b), _rounding(b, "post", "top")],
    "a turned post's joint": lambda b: [_post(b), _rounding(b, "post", "joint", where_meets="plate")],
    "a turned block's top edges, bevelled": lambda b: [_block(b, 40.0), _rounding(b, "block", "top", "chamfer", 0.8)],
    "a block turned a quarter turn, its vertical edges": lambda b: [_block(b, 90.0), _rounding(b, "block", "vertical", size=2.0)],
    "a turned rib's top edges": lambda b: [_post(b), _on({
        "id": "rib", "kind": "rib", "words": cite(b, "post"), "length": assumed("long", 12.0),
        "thickness": assumed("thick", 2.0), "height": assumed("tall", 3.0), "along": {"choose": "u", "from": {"assumed": "a"}},
        "place": {"turn": assumed("turned", 20.0, "deg")}}, "+z"), _rounding(b, "rib", "top", size=0.5)],
    "a turned pocket's floor": lambda b: [_turned_cut(b, "pocket"), _rounding(b, "cut", "bottom", size=0.5)],
    "a turned slot's mouth": lambda b: [_turned_cut(b, "slot"), _rounding(b, "cut", "top", "chamfer", 0.5)],
    "a boss's rim on a turned post's side": lambda b: [_post(b), _on({
        "id": "boss", "kind": "boss", "words": cite(b, "boss"), "diameter": assumed("across", 6.0),
        "height": assumed("tall", 4.0)}, "+x"), _rounding(b, "boss", "top", size=0.8)],
    "a hole's mouth on a turned post's side": lambda b: [_post(b), _hole(b, None, face="-y", depth=4.0),
                                                         _rounding(b, "hole", "top", "chamfer", 0.5)],
    "a hole's mouth on a turned post's far face": lambda b: [_post(b), _hole(b, _right(4.0)),
                                                             _rounding(b, "hole", "top", "chamfer", 0.5)],
    "a block turned on a turned post's side, its top edges": lambda b: [
        _post(b), _block(b, 15.0, on="post", face="-x", sizes=(6, 4, 3)), _rounding(b, "block", "top", size=0.5)],
    "a post turned on a turned post's far face, its vertical edges": lambda b: [
        _post(b), _post(b, 25.0, on="post", item="upper", sizes=(8.0, 5.0, 6.0)), _rounding(b, "upper", "vertical")],
    # A leaning item's (step 5.3): its far end's edges, and a box's along its lean, found upright, then leaned.
    "a leaning post's top edges": lambda b: [_leaning(b, "post"), _rounding(b, "leaning", "top", size=0.8)],
    "a leaning, turned post's edges along its lean, bevelled": lambda b: [
        _leaning(b, "post", 30.0, "-y", turn=40.0), _rounding(b, "leaning", "vertical", "chamfer", 0.6)],
    "a leaning post's edges along its lean, then round its top": lambda b: [
        _leaning(b, "post"), _rounding(b, "leaning", "vertical", size=1.5), {**_rounding(b, "leaning", "top", size=0.8), "id": "again"}],
    "a leaning boss's rim": lambda b: [_leaning(b, "boss", 25.0, "-y"), _rounding(b, "leaning", "top")],
    "a leaning block's top edges": lambda b: [_leaning(b, "block"), _rounding(b, "leaning", "top", size=0.8)],
    "a leaning cylinder's rim": lambda b: [_leaning(b, "cylinder", 30.0, "-y"), _rounding(b, "leaning", "top")],
}


class ALeaningBoxsLongEdgesAreRoundedOnThePart(unittest.TestCase):
    def test_no_other_construction_is_offered(self) -> None:
        for name, make in (
            ("a leaning post's", lambda b: [_leaning(b, "post"), _rounding(b, "leaning", "vertical")]),
            ("a leaning, turned block's, bevelled", lambda b: [_leaning(b, "block", 12.0, "-y", turn=60.0),
                                                                _rounding(b, "leaning", "vertical", "chamfer", 0.5)]),
        ):  # fmt: skip
            with self.subTest(name):
                _, planned = _planned(make)
                (rounding,) = [p for p in planned.items if p.item == "round"]
                self.assertEqual([c.name for c in rounding.constructions], ["on_the_part"])


@needs_occ
class ATurnedItemsEdgesAreRoundedAsAsked(unittest.TestCase):
    def test_every_case(self) -> None:
        from forge_checks.classes import Verdict

        for name, make in CASES.items():
            with self.subTest(name):
                built, accounting, failed = _judged(make)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])


@needs_occ
class AnEdgeLeftSharpIsCaught(unittest.TestCase):
    def test_one_query_left_out(self) -> None:
        import forge_plan.planner as planner
        from forge_checks.classes import Verdict

        real = planner.edge_reference

        def fewer(*args: Any, **kwargs: Any) -> Any:
            """The edges the rounding names, but the last."""
            found, named = real(*args, **kwargs)
            return {**found, "queries": found["queries"][:-1]}, named

        for name in ("a turned post's vertical edges", "a block turned on a turned post's side, its top edges",
                     "a leaning post's top edges", "a leaning, turned post's edges along its lean, bevelled"):  # fmt: skip
            with self.subTest(name), mock.patch.object(planner, "edge_reference", fewer):
                built, accounting, failed = _judged(CASES[name])
                self.assertIsNone(built.gap)
                self.assertTrue(accounting.verdict is Verdict.FAIL or failed)


@needs_occ
class TheSecondKernelAgrees(unittest.TestCase):
    def test_turned_and_on_a_turned_side(self) -> None:
        from forge_occ.agreement import agree
        from forge_occ.planned import build_plan

        for name in ("a turned post's vertical edges", "a block turned on a turned post's side, its top edges",
                     "a hole's mouth on a turned post's side", "a leaning post's top edges", "a leaning boss's rim"):  # fmt: skip
            with self.subTest(name):
                _, planned = _planned(CASES[name])
                built = build_plan(planned)
                self.assertIsNone(built.gap, built.refusals)
                report = agree(planned.document(built.choice), "part", exact=built.result)
                self.assertTrue(report.holds, (report.disagreements, report.notes, report.names, report.topology))


if __name__ == "__main__":
    unittest.main()
