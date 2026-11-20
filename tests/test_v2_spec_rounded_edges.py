"""V2: what a later rounding or bevel of a body's edges would run into (edges.md; checks._common.reached_into).

A rounding is made after what is on the faces either side of its edges
(frame.md). Four holes 3 mm in from the edges of a plate whose top edges
are rounded 2 mm were accepted: OpenCascade couldn't make the rounding, and
where it could (all edges rounded, holes 3.5 mm in) the part failed its
rounding's checks. It is asked about now, before anything is built. The
briefs are written here, not taken from any blind set.
"""

from __future__ import annotations

import unittest
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft
from v2_drafts import assumed, cite, count, draft, mm

RUNS_INTO = "would run into it"


def asked(brief: str, items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    report = check_draft(number_words(brief), draft("part", items))
    return [(p.kind, p.message) for p in report.problems]


PLATE = ("A plate 60 x 40 x 5 mm with four {d} mm holes through it, one in each corner {inset} mm in from both edges, "
         "its {which} edges {how} {size} mm.")  # fmt: skip


def plate(inset: float, which: str, size: float, *, bevel: bool = False, d: int = 4,
          counterbore: bool = False) -> list[tuple[str, str]]:  # fmt: skip
    brief = PLATE.format(d=d, inset=f"{inset:g}", which=which, how="bevelled" if bevel else "rounded",
                         size=f"{size:g}")  # fmt: skip
    if counterbore:
        brief += " Each hole is counterbored 8 mm across and 2 mm deep."
    b = number_words(brief)
    inset_value = mm(b, inset, f"{inset:g} mm in from")
    holes: dict[str, Any] = {
        "id": "holes", "kind": "hole", "words": cite(b, f"four {d} mm holes") + cite(b, "one in each corner"),
        "on": {"item": "plate", "face": "+z"},
        "diameter": mm(b, d, f"{d} mm holes"), "depth": {"through": True, "from": {"words": cite(b, "through it")}},
        "count": count(b, 4, "four"),
        "place": {"pattern": {"corners": {"inset_u": inset_value, "inset_v": {**inset_value}}}},
    }  # fmt: skip
    if counterbore:
        holes["counterbore"] = {"diameter": mm(b, 8, "8 mm across"), "depth": mm(b, 2, "2 mm deep")}
    edge: dict[str, Any] = {"id": "edge", "kind": "chamfer" if bevel else "fillet",
                            "words": cite(b, f"its {which} edges"),
                            "edges": {"of": "plate", "which": which, "words": cite(b, f"its {which} edges")},
                            "size" if bevel else "radius": mm(b, size, f"{size:g} mm", 2 if size == 5 else 1)}  # fmt: skip
    return asked(brief, [
        {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60"),
         "width": mm(b, 40, "40"), "height": mm(b, 5, "5 mm")},
        holes, edge,
    ])  # fmt: skip


ROD = "A rod 40 mm across and 30 mm long, its top rim rounded 3 mm, with a 4 mm hole {} {} mm {}."


def rod(face: str, at: float) -> list[tuple[str, str]]:
    where = ("in its top" if face == "+end" else "through its side",
             f"{at:g}", "from its centre" if face == "+end" else "down from its top")  # fmt: skip
    brief = ROD.format(*where)
    b = number_words(brief)
    place: dict[str, Any] = (
        {"x": {"offset": mm(b, at, f"{at:g} mm from its centre")}, "y": {"centred": assumed("on a diameter")}}
        if face == "+end" else
        {"z": {"side": "+z", "distance": mm(b, at, f"{at:g} mm down from its top"), "to": "centre"},
         "angle": {"value": 0, "unit": "deg", "from": {"assumed": "facing +x"}}}
    )  # fmt: skip
    depth = {"value": 5, "unit": "mm", "from": {"assumed": "a short hole"}} if face == "+end" else {
        "through": True, "from": {"words": cite(b, "through its side")}}  # fmt: skip
    return asked(brief, [
        {"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "axis": {"choose": "z", "from": assumed("up")},
         "diameter": mm(b, 40, "40 mm across"), "length": mm(b, 30, "30 mm long")},
        {"id": "hole", "kind": "hole", "words": cite(b, "4 mm hole"), "on": {"item": "rod", "face": face},
         "diameter": mm(b, 4, "4 mm hole"), "place": place, "depth": depth},
        {"id": "rim", "kind": "fillet", "words": cite(b, "its top rim rounded"),
         "edges": {"of": "rod", "which": "top", "words": cite(b, "its top rim")}, "radius": mm(b, 3, "3 mm")},
    ])  # fmt: skip


def runs_into(found: list[tuple[str, str]]) -> list[str]:
    return [kind for kind, message in found if RUNS_INTO in message]


class WhatALaterRoundingRunsInto(unittest.TestCase):
    def test_holes_near_a_plates_rounded_top_edges(self) -> None:
        self.assertEqual(plate(5, "top", 2), [])
        self.assertEqual(runs_into(plate(3, "top", 2)), ["question"])

    def test_holes_near_a_plates_rounded_corners(self) -> None:
        self.assertEqual(plate(4, "vertical", 8), [])  # 7.66 mm from the corner's centre: inside its 8 mm round
        self.assertEqual(runs_into(plate(3, "vertical", 8)), ["question"])

    def test_counterbores_near_a_bevel(self) -> None:
        self.assertEqual(plate(6, "top", 1.5, bevel=True, counterbore=True), [])
        self.assertEqual(runs_into(plate(5, "top", 1.5, bevel=True, counterbore=True)), ["question"])

    def test_a_rods_end_and_side_near_its_rounded_rim(self) -> None:
        self.assertEqual(rod("+end", 15), [])
        self.assertEqual(runs_into(rod("+end", 17)), ["question"])  # its edge 19 mm out, the rim's round from 17
        self.assertEqual(rod("side", 8), [])
        self.assertEqual(runs_into(rod("side", 4)), ["question"])  # its edge 2 mm from the top, the round 3 mm


CONE = "A cone 40 mm across at its base, 30 mm across at its top and 30 mm tall, its top rim rounded 3 mm, with a 2 mm hole {}."


def cone(face: str, at: int) -> list[tuple[str, str]]:
    where = (f"3 mm deep in its top {at} mm from its centre" if face == "+end" else
             f"3 mm deep in its side {at} mm down from its top")  # fmt: skip
    brief = CONE.format(where)
    b = number_words(brief)
    place: dict[str, Any] = (
        {"x": {"offset": mm(b, at, f"{at} mm from")}, "y": {"centred": assumed("on a diameter")}} if face == "+end" else
        {"z": {"side": "+z", "distance": mm(b, at, f"{at} mm down"), "to": "centre"},
         "angle": {"value": 0, "unit": "deg", "from": {"assumed": "facing +x"}}}
    )  # fmt: skip
    return asked(brief, [
        {"id": "cone", "kind": "cone", "words": cite(b, "cone"), "axis": {"choose": "z", "from": assumed("up")},
         "base_diameter": mm(b, 40, "40 mm across"), "top_diameter": mm(b, 30, "30 mm across"),
         "length": mm(b, 30, "30 mm tall")},
        {"id": "hole", "kind": "hole", "words": cite(b, "2 mm hole"), "on": {"item": "cone", "face": face},
         "diameter": mm(b, 2, "2 mm hole"), "depth": mm(b, 3, "3 mm deep"), "place": place},
        {"id": "rim", "kind": "fillet", "words": cite(b, "its top rim rounded"),
         "edges": {"of": "cone", "which": "top", "words": cite(b, "its top rim")}, "radius": mm(b, 3, "3 mm", 1)},
    ])  # fmt: skip


class OnACone(unittest.TestCase):
    """Its narrower end's round reaches less far back than its radius: 2.54 mm for 3 mm, the material there at 90
    degrees and the cone's half angle (9.5)."""

    def test_its_top(self) -> None:
        self.assertEqual(cone("+end", 11), [])  # its edge 12 mm out, the round from 12.46
        self.assertEqual(runs_into(cone("+end", 12)), ["question"])

    def test_its_side(self) -> None:
        self.assertEqual(cone("side", 6), [])
        self.assertEqual(runs_into(cone("side", 3)), ["question"])


BOSS = ("A plate 60 x 40 x 5 mm with a boss 10 mm across and 8 mm tall in its middle, filleted 2 mm where it meets the "
        "plate, and a 4 mm hole through the plate {} mm from the boss's centre.")  # fmt: skip


def boss(at: int) -> list[tuple[str, str]]:
    brief = BOSS.format(at)
    b = number_words(brief)
    return asked(brief, [
        {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60"),
         "width": mm(b, 40, "40"), "height": mm(b, 5, "5 mm")},
        {"id": "boss", "kind": "boss", "words": cite(b, "boss"), "on": {"item": "plate", "face": "+z"},
         "diameter": mm(b, 10, "10 mm across"), "height": mm(b, 8, "8 mm tall"),
         "place": {"x": {"centred": {"words": cite(b, "in its middle")}}, "y": {"centred": {"words": cite(b, "in its middle")}}}},
        {"id": "hole", "kind": "hole", "words": cite(b, "4 mm hole"), "on": {"item": "plate", "face": "+z"},
         "diameter": mm(b, 4, "4 mm hole"), "depth": {"through": True, "from": {"words": cite(b, "through the plate")}},
         "place": {"x": {"offset": mm(b, at, f"{at} mm from")}, "y": {"centred": assumed("in line with it")}}},
        {"id": "joint", "kind": "fillet", "words": cite(b, "filleted"),
         "edges": {"of": "boss", "which": "joint", "where_meets": "plate", "words": cite(b, "where it meets the plate")},
         "radius": mm(b, 2, "2 mm", 1)},
    ])  # fmt: skip


class RoundWhatStandsThere(unittest.TestCase):
    def test_a_hole_near_a_filleted_boss(self) -> None:
        self.assertEqual(boss(10), [])  # 3 mm clear of its foot
        self.assertEqual(runs_into(boss(8)), ["question"])  # 1 mm clear: the fillet's 2 mm would fill over it


STUD = "A stud: a rod 8 mm across and 30 mm long, with an M8 thread {} and a 1 mm chamfer on its {}."


def stud(threaded: str, ends: str, chamfer_first: bool) -> list[tuple[str, str]]:
    brief = STUD.format(threaded, ends)
    b = number_words(brief)
    which = {"both ends": "both", "top": "top", "bottom": "bottom"}[ends]
    thread: dict[str, Any] = {"id": "thread", "kind": "thread", "words": cite(b, "M8 thread"), "of": "rod",
                              "designation": {"text": "M8", "from": {"words": cite(b, "M8")}},
                              "hand": {"choose": "right", "from": {"assumed": "a standard thread"}}}  # fmt: skip
    if threaded != "all along it":
        thread["length"] = mm(b, 20, "20 mm")
    chamfer = {"id": "chamfer", "kind": "chamfer", "words": cite(b, "1 mm chamfer"),
               "edges": {"of": "rod", "which": which, "words": cite(b, f"its {ends}")}, "size": mm(b, 1, "1 mm")}  # fmt: skip
    rod = {"id": "rod", "kind": "cylinder", "words": cite(b, "rod"), "axis": {"choose": "z", "from": assumed("up")},
           "diameter": mm(b, 8, "8 mm across"), "length": mm(b, 30, "30 mm long")}  # fmt: skip
    return asked(brief, [rod, chamfer, thread] if chamfer_first else [rod, thread, chamfer])


class AThreadedEnd(unittest.TestCase):
    """A thread is cut into a bevelled end: the chamfer comes before the thread in the spec (made in its order), or
    the writer is told to put it there (made after, it would bevel the thread's own end, which isn't built)."""

    def test_the_chamfer_before_the_thread(self) -> None:
        self.assertEqual(stud("all along it", "both ends", chamfer_first=True), [])
        self.assertEqual(stud("20 mm from its top", "top", chamfer_first=True), [])

    def test_after_it_where_the_thread_reaches(self) -> None:
        for threaded, ends in (("all along it", "both ends"), ("20 mm from its top", "top"),
                               ("all along it", "bottom")):  # fmt: skip
            with self.subTest(threaded=threaded, ends=ends):
                found = stud(threaded, ends, chamfer_first=False)
                self.assertEqual([k for k, m in found if "comes after the thread" in m], ["fault"], found)

    def test_after_it_where_it_doesnt(self) -> None:
        self.assertEqual(stud("20 mm from its top", "bottom", chamfer_first=False), [])


BLOCK = "A block 60 x 40 x 20 mm, its vertical edges {} {} mm, and then its {} edges {} {} mm."


def block(vertical: tuple[str, float], then: tuple[str, str, float]) -> list[tuple[str, str]]:
    (first_how, first_size), (which, how, size) = vertical, then
    brief = BLOCK.format(first_how, f"{first_size:g}", which, how, f"{size:g}")
    b = number_words(brief)

    def edge(n: int, id_: str, set_: str, how_: str, value: float) -> dict[str, Any]:
        bevel = how_ == "bevelled"
        return {"id": id_, "kind": "chamfer" if bevel else "fillet", "words": cite(b, f"its {set_} edges"),
                "edges": {"of": "block", "which": set_, "words": cite(b, f"its {set_} edges")},
                "size" if bevel else "radius": mm(b, value, f"{value:g} mm", n)}  # fmt: skip

    second = 2 if f"{size:g} mm" == f"{first_size:g} mm" else 1
    return asked(brief, [
        {"id": "block", "kind": "block", "words": cite(b, "block"), "length": mm(b, 60, "60"),
         "width": mm(b, 40, "40"), "height": mm(b, 20, "20 mm")},
        edge(1, "corners", "vertical", first_how, first_size),
        edge(second, "rim", which, how, size),
    ])  # fmt: skip


class RoundCornersRoundedBefore(unittest.TestCase):
    """Edges running round corners an earlier rounding has rounded follow them: no bigger than they are (the judge
    couldn't make a bigger one); round bevelled corners, not made yet (built, the part failed its checks); and an edge
    another has rounded already isn't rounded again (all of a box's edges, then its top's, wasn't built)."""

    def test_no_bigger_than_the_corners(self) -> None:
        self.assertEqual(block(("rounded", 3), ("top", "rounded", 3)), [])
        found = block(("rounded", 2), ("top", "rounded", 3))
        self.assertEqual([k for k, m in found if "no bigger than they are" in m], ["cant"], found)

    def test_round_bevelled_corners(self) -> None:
        for how in ("rounded", "bevelled"):
            with self.subTest(how):
                found = block(("bevelled", 2), ("top", how, 1))
                self.assertEqual([k for k, m in found if "corners another bevels" in m], ["unable"], found)

    def test_an_edge_rounded_twice(self) -> None:
        found = block(("rounded", 2), ("vertical", "rounded", 1))
        self.assertEqual([k for k, m in found if "rounded or bevelled once" in m], ["fault"], found)


if __name__ == "__main__":
    unittest.main()
