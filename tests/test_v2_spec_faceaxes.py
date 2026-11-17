"""Positions along a face's own axes, and a turned item's far face, as the solver places them (place.u, place.v;
schema 1.4; V2-stage4b-0c.md, 3.3, 1b's third move; place.md, "On a flat face" and "A turned item's far face").

- **The face's own axes are read, written and cited:** ``u`` and ``v`` in a
  position and its side, a pattern's values, counts and axis, an ``along``,
  a ``thickness_along`` and a lean's way; only in schema 1.4 drafts, and an
  item names its face's axes one way.
- **On a face whose axes are the part's, ``u`` and ``v`` are its axes' other
  names:** the same item said either way is placed the same, on every face.
- **A turned item's far face takes things:** turned with it, its own height
  of material under it and its host's, where it stands on a face with the
  same material under all of it; closed on any other. On it, positions are
  along its own axes, and the part's are a fault there; what is placed on it
  is turned with it (as placed, an item turned by both turns on an aligned
  plane), turns add, a round item is the same turned, an outline that
  doesn't turn waits for a later step.
- **Every program reads it alike:** the judge's own placement agrees (every
  layout any test makes is held to it, tests/v2_layouts.py), and the views
  name what the draft names.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

from forge_spec.checks import check_draft
from forge_spec.placement import placed_spec
from forge_spec.wire import to_wire
from forge_spec.words import number_words
from v2_drafts import assumed, cite, draft, mm

BRIEF = number_words(
    "A plate 100 mm long, 60 mm wide and 8 mm thick. A post 30 mm long, 20 mm wide and 10 mm tall stands on it. "
    "A hole 6 mm across goes through it. A slot 4 mm wide and 12 mm long. A boss 8 mm across and 5 mm tall."
)
B = BRIEF
C30, S30 = math.cos(math.radians(30)), math.sin(math.radians(30))


def _plate() -> dict[str, Any]:
    return {"id": "plate", "kind": "block", "words": cite(B, "plate"), "length": mm(B, 100, "100 mm"),
            "width": mm(B, 60, "60 mm"), "height": mm(B, 8, "8 mm")}  # fmt: skip


def _post(turn: float | None = 30.0, *, on: str = "plate", face: str = "+z", item: str = "post",
          sizes: tuple[float, float, float] = (30.0, 20.0, 10.0)) -> dict[str, Any]:  # fmt: skip
    length, width, height = sizes
    found = {"id": item, "kind": "post", "words": cite(B, "post"), "on": {"item": on, "face": face},
             "length": assumed("long", length), "width": assumed("wide", width), "height": assumed("tall", height)}  # fmt: skip
    if turn is not None:
        found["place"] = {"turn": assumed("turned", turn, "deg")}
    return found


def _hole(place: dict[str, Any] | None = None, *, on: str = "post", face: str = "+z", **fields: Any) -> dict[str, Any]:
    found = {"id": "hole", "kind": "hole", "words": cite(B, "hole"), "on": {"item": on, "face": face},
             "diameter": mm(B, 6, "6 mm"), "depth": {"through": True, "from": {"assumed": "through"}}, **fields}  # fmt: skip
    if place is not None:
        found["place"] = place
    return found


def _slot(along: str = "u", *, on: str = "post", **fields: Any) -> dict[str, Any]:
    return {"id": "slot", "kind": "slot", "words": cite(B, "slot"), "on": {"item": on, "face": "+z"},
            "width": mm(B, 4, "4 mm"), "length": mm(B, 12, "12 mm"), "depth": assumed("deep", 3.0),
            "along": {"choose": along, "from": {"assumed": "along it"}},
            "ends": {"choose": "round", "from": {"assumed": "round"}}, **fields}  # fmt: skip


def _boss(on: str = "post") -> dict[str, Any]:
    return {"id": "boss", "kind": "boss", "words": cite(B, "boss"), "on": {"item": on, "face": "+z"},
            "diameter": mm(B, 8, "8 mm"), "height": mm(B, 5, "5 mm")}  # fmt: skip


def _report(*items: dict[str, Any], version: str = "1.4") -> Any:
    found = draft("plate", [_plate(), *items])
    found["schema_version"] = version
    return check_draft(B, found, strict=False)


def _placing(report: Any) -> list[str]:
    """The problems placing the items finds (not the brief's numbers the spec leaves unused)."""
    return [p.message for p in report.problems
            if "nothing in the spec uses it" not in p.message and "nothing in the spec comes from" not in p.message]  # fmt: skip


def _faults(report: Any) -> list[str]:
    return [p.at for p in report.problems if p.kind == "fault"]


def _origin(report: Any, item: str, k: int = 0) -> tuple[float, float, float]:
    return report.layout.instances[item][k].origin


def _close(test: unittest.TestCase, a: Any, b: Any, places: int = 9) -> None:
    for x, y in zip(a, b, strict=True):
        test.assertAlmostEqual(x, y, places=places)


class TheFacesOwnAxesAreReadWrittenAndCited(unittest.TestCase):
    def test_read_and_written(self) -> None:
        place = {"u": {"side": "-u", "distance": assumed("in", 10.0), "to": "edge"}, "v": {"offset": assumed("up", 5.0)}}
        report = _report(_hole(place, on="plate"))
        self.assertEqual(_placing(report), [])
        held = report.spec.item("hole").get("place")
        self.assertEqual((sorted(held.axes), held.axes["u"].side), (["u", "v"], "-u"))
        wire = to_wire(report.spec)["items"][1]["place"]
        self.assertEqual((wire["u"]["side"], wire["v"]["offset"]["value"]), ("-u", 5))

    def test_patterns_choices_and_ways(self) -> None:
        grid = {"pattern": {"grid": {"pitch_u": assumed("apart", 20.0), "pitch_v": assumed("apart", 15.0),
                                     "count_u": {"count": 2, "from": {"assumed": "two"}},
                                     "count_v": {"count": 2, "from": {"assumed": "two"}}}}}  # fmt: skip
        hole = _hole(grid, on="plate", count={"count": 4, "from": {"assumed": "four"}})
        report = _report(hole, _slot("v", on="plate"))
        self.assertEqual(_placing(report), [])
        wire = to_wire(report.spec)["items"]
        self.assertEqual(sorted(wire[1]["place"]["pattern"]["grid"]), ["count_u", "count_v", "pitch_u", "pitch_v"])
        self.assertEqual(wire[2]["along"]["choose"], "v")

    def test_only_in_schema_1_4(self) -> None:
        report = _report(_hole({"u": {"offset": assumed("right", 5.0)}}, on="plate"), version="1.3")
        self.assertIn("/items/1/place/u", _faults(report))

    def test_one_way_or_the_other(self) -> None:
        mixed = _slot("x", on="plate", place={"u": {"offset": assumed("right", 5.0)}})
        self.assertIn("/items/1/along", _faults(_report(mixed)))


class OnAnAlignedFaceTheyAreItsAxesOtherNames(unittest.TestCase):
    def test_the_same_item_said_either_way_is_placed_the_same(self) -> None:
        ways = {
            "+z": ({"u": {"side": "+u", "distance": assumed("in", 12.0), "to": "edge"}, "v": {"offset": assumed("o", -7.0)}},
                   {"x": {"side": "+x", "distance": assumed("in", 12.0), "to": "edge"}, "y": {"offset": assumed("o", -7.0)}}),
            "-x": ({"u": {"side": "-u", "distance": assumed("in", 20.0)}, "v": {"offset": assumed("o", 0.5)}},
                   {"y": {"side": "-y", "distance": assumed("in", 20.0)}, "z": {"offset": assumed("o", 0.5)}}),
            "+y": ({"u": {"offset": assumed("o", -20.0)}}, {"x": {"offset": assumed("o", -20.0)}}),
        }  # fmt: skip
        for face, (own, part) in ways.items():
            with self.subTest(face=face):
                a = _report(_hole(own, on="plate", face=face))
                b = _report(_hole(part, on="plate", face=face))
                self.assertEqual((_placing(a), _placing(b)), ([], []))
                self.assertEqual(_origin(a, "hole"), _origin(b, "hole"))

    def test_choices_and_patterns(self) -> None:
        def row(axis: str) -> dict[str, Any]:
            return {"pattern": {"row": {"count": {"count": 3, "from": {"assumed": "three"}}, "pitch": assumed("p", 15.0),
                                        "axis": {"choose": axis, "from": {"assumed": "along"}}}}}  # fmt: skip

        for own, part in (("u", "x"), ("v", "y")):
            with self.subTest(along=own):
                a = _report(_slot(own, on="plate", place=row(own), count={"count": 3, "from": {"assumed": "three"}}))
                b = _report(_slot(part, on="plate", place=row(part), count={"count": 3, "from": {"assumed": "three"}}))
                self.assertEqual((_placing(a), _placing(b)), ([], []))
                self.assertEqual([c.origin for c in a.layout.instances["slot"]],
                                 [c.origin for c in b.layout.instances["slot"]])  # fmt: skip
                # As every program after the solver reads it: along the part's names for the face's axes.
                self.assertEqual(placed_spec(a.spec, a.layout).item("slot").get("along").value, part)

    def test_said_back_as_said(self) -> None:
        # What the solver assumes is said along the axis as the item names it, on any face.
        for items in ((_hole({"u": {"centred": {"assumed": "in the middle"}}}, on="plate"),),
                      (_post(), _hole({"u": {"offset": assumed("right", 8.0)}}))):  # fmt: skip
            report = _report(*items)
            self.assertIn("hole: centred along v on +z; the brief doesn't say where",
                          [a.message for a in report.assumptions])  # fmt: skip


class ATurnedItemsFarFaceTakesThings(unittest.TestCase):
    def test_its_far_face_turned_with_it(self) -> None:
        report = _report(_post())
        self.assertEqual(_placing(report), [])
        faces = report.layout.faces[("post", 0)]
        self.assertEqual(list(faces), ["+z"])
        top = faces["+z"]
        self.assertEqual((top.turn, top.half, top.depth_below), (30.0, (15.0, 10.0), 18.0))
        _close(self, top.frame.u, (C30, S30, 0.0))
        self.assertIn("+x", report.layout.closed[("post", 0)])

    def test_placed_along_its_own_axes(self) -> None:
        report = _report(_post(), _hole({"u": {"offset": assumed("right", 8.0)}, "v": {"offset": assumed("up", -2.0)}}))
        self.assertEqual(_placing(report), [])
        _close(self, _origin(report, "hole"), (8 * C30 + 2 * S30, 8 * S30 - 2 * C30, 18.0))
        edge = _report(_post(), _hole({"u": {"side": "+u", "distance": assumed("in", 4.0), "to": "edge"}}))
        _close(self, _origin(edge, "hole"), ((15 - 4 - 3) * C30, (15 - 4 - 3) * S30, 18.0))

    def test_the_parts_axes_are_a_fault_there(self) -> None:
        report = _report(_post(), _hole({"x": {"offset": assumed("right", 8.0)}}))
        self.assertIn("/items/2/place/x", _faults(report))
        self.assertIn("/items/2/along", _faults(_report(_post(), _slot("x"))))

    def test_what_is_on_it_turns_with_it(self) -> None:
        report = _report(_post(), _slot("u"))
        self.assertEqual(_placing(report), [])
        slot = placed_spec(report.spec, report.layout).item("slot")
        self.assertEqual((slot.get("along").value, slot.get("place").turn.made_in("deg")), ("x", 30.0))
        turned = _report(_post(), _slot("v", place={"turn": assumed("turned", 15.0, "deg")}))
        self.assertEqual(_placing(turned), [])
        slot = placed_spec(turned.spec, turned.layout).item("slot")
        self.assertEqual((slot.get("along").value, slot.get("place").turn.made_in("deg")), ("y", 45.0))

    def test_turns_add(self) -> None:
        upper = _post(20.0, on="post", item="upper", sizes=(10.0, 6.0, 4.0))
        report = _report(_post(), upper)
        self.assertEqual(_placing(report), [])
        top = report.layout.faces[("upper", 0)]["+z"]
        self.assertEqual((top.turn, top.depth_below), (50.0, 4.0 + 10.0 + 8.0))
        hole = _hole({"u": {"offset": assumed("right", 2.0)}}, on="upper")
        _close(self, _origin(_report(_post(), upper, hole), "hole"),
               (2 * math.cos(math.radians(50)), 2 * math.sin(math.radians(50)), 22.0))  # fmt: skip

    def test_a_round_item_is_the_same_turned(self) -> None:
        report = _report(_post(), _boss())
        self.assertEqual(_placing(report), [])
        faces = report.layout.faces[("boss", 0)]
        top = next(f for f in faces.values() if f.normal == "+z")
        self.assertEqual((top.turn, top.depth_below), (30.0, 5.0 + 10.0 + 8.0))
        self.assertTrue(report.layout.closed[("boss", 0)])

    def test_closed_over_a_face_without_the_same_material_under_all_of_it(self) -> None:
        # A block over the plate's edge has the plate's material under its far face only where it is over the plate.
        ledge = {"id": "ledge", "kind": "block", "words": cite(B, "plate"), "on": {"item": "plate", "face": "+z"},
                 "length": assumed("long", 20.0), "width": assumed("wide", 20.0), "height": assumed("tall", 6.0),
                 "place": {"x": {"offset": assumed("over the edge", 45.0)}}}  # fmt: skip
        report = _report(ledge, _post(on="ledge", sizes=(4.0, 3.0, 2.0)))
        self.assertEqual(_placing(report), [])
        self.assertIn("far face in a later move", report.layout.closed[("post", 0)]["+z"][1])
        # Wholly over its host, a boss has the same under all of its far face: a turned post's there takes things.
        report = _report(_boss(on="plate"), _post(on="boss", face="+end", sizes=(4.0, 3.0, 2.0)))
        self.assertEqual(report.layout.faces[("post", 0)]["+z"].depth_below, 2.0 + 5.0 + 8.0)

    def test_an_outline_that_doesnt_turn_waits(self) -> None:
        extrusion = {"id": "ridge", "kind": "extrusion", "words": cite(B, "post"), "on": {"item": "post", "face": "+z"},
                     "length": assumed("out", 3.0),
                     "profile": {"start": [0, 0], "segments": [{"line_to": [4, 0]}, {"line_to": [4, 2]},
                                                              {"line_to": [0, 2]}, {"line_to": [0, 0]}],
                                 "unit": "mm", "from": {"assumed": "drawn"}}}  # fmt: skip
        report = _report(_post(), extrusion)
        self.assertIn("unable", [p.kind for p in report.problems if p.at.startswith("/items/2")] or
                      [i.kind for i in report.layout.issues if i.at.startswith("/items/2")])  # fmt: skip

    def test_a_round_sides_axes_are_not_u_and_v(self) -> None:
        rod = {"id": "rod", "kind": "cylinder", "words": cite(B, "post"), "on": {"item": "plate", "face": "+z"},
               "diameter": assumed("rod", 20.0), "length": assumed("rod", 20.0)}  # fmt: skip
        hole = _hole({"u": {"offset": assumed("o", 2.0)}}, on="rod", face="side")
        self.assertIn("/items/2/place/u", _faults(_report(rod, hole)))

    def test_leaning_and_in_a_pattern_on_it(self) -> None:
        lean = {"tilt": assumed("leaning", 20.0, "deg"), "tilt_towards": {"choose": "+u", "from": {"assumed": "that way"}}}
        report = _report(_post(), _hole(None, depth=assumed("deep", 4.0), **lean))
        self.assertEqual(_placing(report), [])
        (copy_,) = report.layout.instances["hole"]
        c, s = math.cos(math.radians(20)), math.sin(math.radians(20))
        _close(self, copy_.direction, (s * C30, s * S30, c))
        row = {"pattern": {"row": {"count": {"count": 2, "from": {"assumed": "two"}}, "pitch": assumed("p", 12.0),
                                   "axis": {"choose": "u", "from": {"assumed": "along"}}}}}  # fmt: skip
        two = _report(_post(), _hole(row, count={"count": 2, "from": {"assumed": "two"}}))
        self.assertEqual(_placing(two), [])
        _close(self, _origin(two, "hole", 0), (-6 * C30, -6 * S30, 18.0))
        _close(self, _origin(two, "hole", 1), (6 * C30, 6 * S30, 18.0))


class WhatTheViewsAndWordsSay(unittest.TestCase):
    def test_every_value_named_as_the_draft_names_it(self) -> None:
        from forge_spec.render_views import render_views
        from test_v2_spec_views import check_every_value_shown

        for items in ((_hole({"u": {"side": "-u", "distance": assumed("in", 9.0)}}, on="plate"),),
                      (_post(), _hole({"u": {"offset": assumed("right", 8.0)}})),
                      (_post(), _slot("v", place={"turn": assumed("turned", 15.0, "deg")}))):  # fmt: skip
            report = _report(*items)
            check_every_value_shown(self, report, render_views(report), items[-1]["id"])


if __name__ == "__main__":
    unittest.main()
