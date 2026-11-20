"""V2 stage 1: faces, fits, copies, walls and depths in the placement solver.

These drafts test the solver (forge_spec.placement), not the reading of the
brief: values say they come from the brief but cite the same two words, which
the solver doesn't check and the spec checks would. Values the writer
assumed are made with ``guess``. Briefs, where one is needed, are from V1's
corpus (validation/SUITE.md). Each test pins a rule the solver must keep:

- every face has one name, the one the schema declares, and a face that can't
  be used says why;
- whether a feature fits on its face is decided exactly: round ends, rounded
  corners, discs and rings, not bounding boxes;
- a body may overhang what it stands on, but must meet it; a feature may not
  overhang, unasked;
- every value given is used, or it is a fault;
- a problem that rests on an assumed value goes back to the writer;
- no draft, however malformed, makes the reader or the checks raise.
"""

from __future__ import annotations

import copy
import math
import random
import sys
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.draft import read_draft
from forge_spec.geometry import FlatFace, SideFace
from forge_spec.placement import MAX_COPIES, Layout, solve
from forge_spec.schema import KINDS

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_drafts import assumed, choose, draft

BRIEF = number_words(
    "An aluminium mounting plate 70 mm long, 50 mm wide and 4 mm thick. Four 4 mm holes pass "
    "through the plate, one near each corner, with their centres on a 56 mm by 36 mm rectangle. "
    "It carries no load, so there is no load case."
)
WORDS = [2, 3]  # "mounting plate"
ASSUMED = " (it rests on an assumed value: choose one that fits)"


def a(value: float, unit: str = "mm") -> dict[str, Any]:
    """A value as if the brief gave it."""
    return {"value": value, "unit": unit, "from": {"words": WORDS}}


def guess(value: float, unit: str = "mm") -> dict[str, Any]:
    """A value the spec writer assumed."""
    return assumed("for the test", value, unit)


def n(count: int) -> dict[str, Any]:
    return {"count": count, "from": {"words": WORDS}}


def pick(value: str) -> dict[str, Any]:
    return choose(value, assumed("for the test"))


def said(value: str) -> dict[str, Any]:
    """A choice as if the brief made it."""
    return choose(value, {"words": WORDS})


def item(item_id: str, kind: str, **fields: Any) -> dict[str, Any]:
    return {"id": item_id, "kind": kind, "words": WORDS, **fields}


def on(host: str, face: str) -> dict[str, str]:
    return {"item": host, "face": face}


def through() -> dict[str, Any]:
    """Through, as if the brief said so."""
    return {"through": True, "from": {"words": WORDS}}


def centred() -> dict[str, Any]:
    return {"centred": assumed("for the test")}


def at(side: str, distance: float, to: str = "centre") -> dict[str, Any]:
    return {"side": side, "distance": a(distance), "to": to}


def opened(*faces: str) -> dict[str, Any]:
    return {"faces": list(faces), "from": assumed("for the test")}


PLATE = item("plate", "block", length=a(70), width=a(50), height=a(4))


def layout_of(*items: dict[str, Any]) -> Layout:
    spec, read = read_draft(draft("test", list(items)))
    assert spec is not None and not read.faults, [str(p) for p in read.faults]
    return solve(spec)


def issues(layout: Layout) -> list[tuple[str, str]]:
    return [(i.kind, i.message) for i in layout.issues]


def kinds(layout: Layout) -> list[str]:
    return [i.kind for i in layout.issues]


def hole(host: str, face: str, d: float, **fields: Any) -> dict[str, Any]:
    return item(fields.pop("id", "h"), "hole", on=on(host, face), diameter=a(d),
                depth=fields.pop("depth", through()), **fields)  # fmt: skip


def shell(of: str, thickness: float, *faces: str, **fields: Any) -> dict[str, Any]:
    return item(
        "hollow", "shell", of=of, thickness=a(thickness), open=opened(*faces), **fields
    )


# One placed example of every kind that has faces, and how to place it.
EXAMPLES: dict[str, list[dict[str, Any]]] = {
    "block": [PLATE],
    "cylinder": [item("c", "cylinder", diameter=a(20), length=a(10), axis=pick("z"))],
    "tube": [item("c", "tube", outer_diameter=a(20), inner_diameter=a(10), length=a(10), axis=pick("z"))],
    "sphere": [item("c", "sphere", diameter=a(20), portion=pick("upper_half"))],
    "cone": [item("c", "cone", base_diameter=a(20), top_diameter=a(10), length=a(10), axis=pick("z"))],
    "pocket": [PLATE, item("c", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(20),
                           width=a(10), depth=a(2))],
    "boss": [PLATE, item("c", "boss", on=on("plate", "+z"), diameter=a(10), height=a(5))],
    "post": [PLATE, item("c", "post", on=on("plate", "+z"), length=a(10), width=a(8), height=a(5))],
    "tab": [PLATE, item("c", "tab", on=on("plate", "+x"), length=a(10), width=a(8), thickness=a(2),
                        thickness_along=pick("z"), end=pick("square"))],
    "rib": [PLATE, item("c", "rib", on=on("plate", "+z"), length=a(30), thickness=a(2), height=a(5),
                        along=pick("x"))],
}  # fmt: skip

HOLLOWED = {
    "block": [
        item("c", "block", length=a(60), width=a(40), height=a(30)),
        shell("c", 2, "+z"),
    ],
    "cylinder": [
        item("c", "cylinder", diameter=a(60), length=a(80), axis=pick("z")),
        shell("c", 2, "+end"),
    ],
}


class EveryFaceHasOneName(unittest.TestCase):
    def check_offered(
        self, kind: str, items: list[dict[str, Any]], key_id: str
    ) -> None:
        layout = layout_of(*items)
        self.assertEqual(issues(layout), [], kind)
        key = (key_id, 0)
        offered, closed = (
            set(layout.faces.get(key, {})),
            set(layout.closed.get(key, {})),
        )
        self.assertEqual(offered | closed, set(KINDS[kind].faces), kind)
        self.assertFalse(offered & closed, kind)

    def test_the_solver_offers_exactly_the_declared_faces(self) -> None:
        for kind, items in EXAMPLES.items():
            self.check_offered(kind, items, items[-1]["id"])
        for kind, items in HOLLOWED.items():
            self.check_offered(kind, items, "c")

    def test_every_kind_with_faces_has_an_example(self) -> None:
        placeable = {k for k, spec in KINDS.items() if spec.faces} - {
            "extrusion",
            "revolution",
        }
        self.assertEqual(placeable, set(EXAMPLES))

    def test_a_face_the_kind_does_not_have(self) -> None:
        for face in ("top", "side", "+end"):
            layout = layout_of(PLATE, hole("plate", face, 4))
            self.assertEqual(kinds(layout), ["fault"], face)
            self.assertIn("a block's faces are", issues(layout)[0][1])

    def test_nothing_goes_into_a_hole(self) -> None:
        layout = layout_of(PLATE, item("big", "hole", on=on("plate", "+z"), diameter=a(20), depth=a(2)),
                           hole("big", "bottom", 4))  # fmt: skip
        self.assertIn(
            ("fault", "nothing stands on or cuts into a hole"), issues(layout)
        )

    def test_a_joined_face_says_so(self) -> None:
        upright = item(
            "upright",
            "block",
            on=on("plate", "+z"),
            length=a(5),
            width=a(50),
            height=a(30),
        )
        layout = layout_of(PLATE, upright, hole("upright", "-z", 3))
        self.assertIn(("fault", "upright's -z face is joined to plate"), issues(layout))
        layout = layout_of(*EXAMPLES["boss"], hole("c", "-end", 3))
        self.assertIn(
            ("fault", "a boss's faces are ['+end', 'side'], not '-end'"), issues(layout)
        )

    def test_faces_that_can_t_be_used(self) -> None:
        cases = [
            (EXAMPLES["sphere"], "surface", "unable"),
            (EXAMPLES["cone"], "side", "unable"),
            ([item("c", "sphere", diameter=a(20), portion=pick("whole"))], "-end", "fault"),
            ([item("c", "cone", base_diameter=a(20), top_diameter=a(0), length=a(10))], "+end", "fault"),
            ([PLATE, item("c", "pocket", on=on("plate", "+z"), shape=pick("circle"), diameter=a(10),
                          depth=through())], "bottom", "fault"),
            ([item("c", "block", length=a(10), width=a(10), height=a(10))], "inner -z", "fault"),
        ]  # fmt: skip
        for items, face, kind in cases:
            layout = layout_of(*items, hole("c", face, 2))
            self.assertEqual(kinds(layout), [kind], (face, issues(layout)))

    def test_nothing_stands_on_a_region(self) -> None:
        region = item("r", "region", on=on("plate", "+z"), length=a(20), width=a(20), height=a(20),
                      describe={"text": "mounting plate", "from": {"words": WORDS}})  # fmt: skip
        layout = layout_of(PLATE, region, hole("r", "+z", 3))
        self.assertIn(
            ("fault", "nothing stands on or cuts into a region"), issues(layout)
        )


class FeaturesFitExactly(unittest.TestCase):
    def test_into_the_floor_of_a_pocket(self) -> None:
        pocket = item("p", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(20),
                      width=a(10), depth=a(3))  # fmt: skip
        layout = layout_of(PLATE, pocket, hole("p", "bottom", 4))
        self.assertEqual(issues(layout), [])
        self.assertEqual(layout.instances["h"][0].origin, (0.0, 0.0, 1.0))
        layout = layout_of(PLATE, pocket, hole("p", "bottom", 4, depth=a(1.5)))
        self.assertIn("1.5 mm deep in 1 mm of material", issues(layout)[0][1])

    def test_a_rounded_pocket_floor(self) -> None:
        pocket = item("p", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(20),
                      width=a(20), corner_radius=a(8), depth=a(2))  # fmt: skip
        corner = {
            "x": at("+x", 2),
            "y": at("+y", 2),
        }  # 2 mm in from each side: inside the box only
        layout = layout_of(PLATE, pocket, hole("p", "bottom", 2, place=corner))
        self.assertIn("runs past the edge", issues(layout)[0][1])
        middle = {"x": at("+x", 2), "y": centred()}  # 2 mm in from a straight side
        self.assertEqual(
            issues(layout_of(PLATE, pocket, hole("p", "bottom", 2, place=middle))), []
        )

    def test_a_corner_radius_too_big_for_its_pocket(self) -> None:
        pocket = item("p", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(20),
                      width=a(10), corner_radius=a(8), depth=a(2))  # fmt: skip
        self.assertEqual(kinds(layout_of(PLATE, pocket)), ["cant"])
        pocket["corner_radius"] = guess(8)
        self.assertEqual(kinds(layout_of(PLATE, pocket)), ["fault"])

    def test_through_a_round_ended_tab(self) -> None:
        lug = item("lug", "tab", on=on("plate", "+z"), length=a(20), width=a(16), thickness=a(4),
                   thickness_along=pick("y"), end=pick("round"))  # fmt: skip
        # The face is 16 wide (x) and 20 tall (z); its top is a semicircle of radius 8.
        concentric = {"x": centred(), "z": at("+z", 8)}
        layout = layout_of(PLATE, lug, hole("lug", "+y", 8, place=concentric))
        self.assertEqual(issues(layout), [])
        self.assertEqual(layout.instances["h"][0].origin, (0.0, 2.0, 16.0))
        near_corner = {
            "x": at("+x", 3),
            "z": at("+z", 3),
        }  # inside the box, outside the round end
        layout = layout_of(PLATE, lug, hole("lug", "+y", 4, place=near_corner))
        self.assertIn("runs past the edge", issues(layout)[0][1])
        # Its round end takes a blind hole, as a round side over its half (item 3b's fourth step); not one through.
        self.assertIn(("unable", "Forge cuts a blind hole into a tab's round end, or one through the next face, for now: give the hole "
                       "into lug a depth"),
                      issues(layout_of(PLATE, lug, hole("lug", "+z", 2))))  # fmt: skip
        side = layout_of(PLATE, lug, hole("lug", "+x", 2)).faces[("lug", 0)]["+x"]
        assert isinstance(side, FlatFace)
        self.assertEqual(
            side.half, (2.0, 6.0)
        )  # the flat side stops where the round end starts

    def test_a_round_end_needs_the_length(self) -> None:
        stub = item("lug", "tab", on=on("plate", "+z"), length=a(4), width=a(16), thickness=a(4),
                    thickness_along=pick("y"), end=said("round"))  # fmt: skip
        self.assertEqual(kinds(layout_of(PLATE, stub)), ["cant"])
        stub["end"] = pick("round")
        self.assertEqual(kinds(layout_of(PLATE, stub)), ["fault"])

    def test_a_square_pocket_on_a_disc(self) -> None:
        disc = EXAMPLES["cylinder"][0]  # 20 mm across
        square = {"shape": pick("rectangle"), "depth": a(2)}
        fits = item(
            "p", "pocket", on=on("c", "+end"), length=a(14), width=a(14), **square
        )  # corners at 9.9
        self.assertEqual(issues(layout_of(disc, fits)), [])
        off_centre = item(
            "p",
            "pocket",
            on=on("c", "+end"),
            length=a(13),
            width=a(13),
            place={"x": {"offset": a(1.5)}, "y": centred()},
            **square,
        )  # a corner at 10.3
        self.assertIn("runs past the edge", issues(layout_of(disc, off_centre))[0][1])
        too_big = item(
            "p", "pocket", on=on("c", "+end"), length=a(15), width=a(15), **square
        )
        self.assertEqual(
            kinds(layout_of(disc, too_big)), ["question"]
        )  # fits nowhere, blind
        too_big["depth"] = through()
        self.assertEqual(
            kinds(layout_of(disc, too_big)), ["cant"]
        )  # ...and through: it severs the disc

    def test_a_round_ended_slot_on_a_disc(self) -> None:
        disc = EXAMPLES["cylinder"][0]
        slot = item("s", "slot", on=on("c", "+end"), width=a(6), length=a(19.5), along=pick("x"),
                    ends=pick("round"), depth=a(2))  # fmt: skip
        self.assertEqual(
            issues(layout_of(disc, slot)), []
        )  # its box's corners would stick out
        square = copy.deepcopy(slot)
        square["ends"] = pick("square")
        self.assertEqual(kinds(layout_of(disc, square)), ["question"])

    def test_a_ring_end(self) -> None:
        ring = EXAMPLES["tube"][0]  # 20 outside, 10 bore: a 5 mm wall
        self.assertEqual(
            issues(
                layout_of(ring, hole("c", "+end", 4, place={"x": {"offset": a(7.5)}}))
            ),
            [],
        )
        layout = layout_of(ring, hole("c", "+end", 4, place={"x": {"offset": a(6)}}))
        self.assertIn("breaks into the hole in the middle", issues(layout)[0][1])
        self.assertIn(
            "would cut nothing", issues(layout_of(ring, hole("c", "+end", 6)))[0][1]
        )
        step = layout_of(
            ring, hole("c", "+end", 15, depth=a(3))
        )  # a step round the bore
        self.assertEqual(issues(step), [])
        self.assertEqual(kinds(layout_of(ring, hole("c", "+end", 22))), ["cant"])

    def test_a_cut_touching_the_edge_from_inside(self) -> None:
        """A round cut that touches its face's edge pinches the material there to nothing (no kernel builds it soundly): a question. A straight side along the edge only opens the cut."""
        touching = hole(
            "plate", "+z", 10, place={"x": {"offset": a(30)}}
        )  # the plate is 70 x 50
        self.assertEqual(issues(layout_of(PLATE, touching)),
                         [("question", "h copy 1 touches the edge of face +z: the wall between them would be "
                                       "nothing there")])  # fmt: skip
        clear = hole("plate", "+z", 10, place={"x": {"offset": a(29.9)}})
        self.assertEqual(issues(layout_of(PLATE, clear)), [])
        # A rebate along the edge, and a square-ended slot along it: a straight side along it only opens them.
        rebate = item("p", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(10), width=a(20),
                      depth=a(2), place={"x": {"offset": a(30)}})  # fmt: skip
        slot = item("s", "slot", on=on("plate", "+z"), width=a(6), length=a(30), along=pick("x"),
                    ends=pick("square"), depth=a(2), place={"y": {"offset": a(22)}})  # fmt: skip
        self.assertEqual(issues(layout_of(PLATE, rebate)), [])
        self.assertEqual(issues(layout_of(PLATE, slot)), [])
        # Its corners rounded, or its ends round, they meet the edge just where its side does: a knife edge there,
        # the wall growing from nothing (built, and held).
        rounded = item("p", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(10), width=a(20),
                       corner_radius=a(3), depth=a(2), place={"x": {"offset": a(30)}})  # fmt: skip
        self.assertIn("touches the edge", issues(layout_of(PLATE, rounded))[0][1])
        slot["ends"] = pick("round")
        self.assertIn("touches the edge", issues(layout_of(PLATE, slot))[0][1])
        # Its round end against the edge, it touches.
        slot["place"] = {"x": {"offset": a(20)}}
        self.assertIn("touches the edge", issues(layout_of(PLATE, slot))[0][1])
        # A disc's rim from inside; a ring's bore from outside; a step round the bore touches nothing.
        disc, ring = (
            EXAMPLES["cylinder"][0],
            EXAMPLES["tube"][0],
        )  # 20 across; 20 across, a 10 mm bore
        for host, offset in ((disc, 8), (ring, 7), (ring, 8)):
            found = issues(
                layout_of(
                    host, hole("c", "+end", 4, place={"x": {"offset": a(offset)}})
                )
            )
            self.assertIn("touches the edge of face +end", found[0][1])
        self.assertEqual(issues(layout_of(ring, hole("c", "+end", 20, depth=a(3)))), [])
        # A boss standing against the edge is no pinch: it adds material.
        boss = item(
            "b",
            "boss",
            on=on("plate", "+z"),
            diameter=a(10),
            height=a(5),
            place={"x": {"offset": a(30)}},
        )
        self.assertEqual(issues(layout_of(PLATE, boss)), [])

    def test_a_through_cut_coming_out_under_something(self) -> None:
        """Through is through the body cut into: something standing over its far mouth would close it, a question. Out into a hollow, or a tube's bore, it is open."""
        boss = item(
            "b",
            "boss",
            on=on("plate", "+z"),
            diameter=a(20),
            height=a(5),
            place={"x": {"offset": a(10)}},
        )
        under = hole("plate", "-z", 6, place={"x": {"offset": a(12)}})
        self.assertEqual(issues(layout_of(PLATE, boss, under)),
                         [("question", "h copy 1 goes right through plate and comes out under b copy 1 on +z: should "
                                       "it go on through b, or stop?")])  # fmt: skip
        beside = hole("plate", "-z", 6, place={"x": {"offset": a(-20)}})
        self.assertEqual(issues(layout_of(PLATE, boss, beside)), [])
        # Into a hollowed block's floor it comes out into the hollow, whatever stands on its top.
        hollow = [item("c", "block", length=a(60), width=a(40), height=a(30)), shell("c", 2),
                  item("p", "post", on=on("c", "+z"), length=a(10), width=a(10), height=a(5))]  # fmt: skip
        self.assertEqual(issues(layout_of(*hollow, hole("c", "-z", 4))), [])
        # Into a tube's bore standing over it, it comes out into the bore.
        tube = item(
            "t",
            "tube",
            on=on("plate", "+z"),
            outer_diameter=a(20),
            inner_diameter=a(12),
            length=a(10),
        )
        self.assertEqual(issues(layout_of(PLATE, tube, hole("plate", "-z", 10))), [])
        self.assertIn(
            "comes out under t",
            issues(layout_of(PLATE, tube, hole("plate", "-z", 14)))[0][1],
        )

    def test_too_big_for_the_face(self) -> None:
        self.assertEqual(kinds(layout_of(PLATE, hole("plate", "+z", 60))), ["cant"])
        self.assertEqual(
            kinds(layout_of(PLATE, hole("plate", "+z", 60, depth=a(1)))), ["question"]
        )
        boss = item("b", "boss", on=on("plate", "+z"), diameter=a(60), height=a(5))
        self.assertEqual(kinds(layout_of(PLATE, boss)), ["question"])

    def test_the_estimate_of_a_text_never_ends_a_run(self) -> None:
        text = item("t", "text", on=on("plate", "+z"), text={"text": "I" * 30, "from": {"words": WORDS}},
                    height=a(10), depth=a(1), mode=pick("engrave"))  # fmt: skip
        self.assertEqual(kinds(layout_of(PLATE, text)), ["question"])

    def test_a_body_may_overhang_what_it_stands_on_but_must_meet_it(self) -> None:
        shank = item("shank", "cylinder", diameter=a(8), length=a(30), axis=pick("z"))
        head = item(
            "head", "cylinder", on=on("shank", "+end"), diameter=a(13), length=a(5)
        )
        layout = layout_of(shank, head)
        self.assertEqual(issues(layout), [])
        self.assertEqual(layout.extent(), ((-6.5, -6.5, 0.0), (6.5, 6.5, 35.0)))
        adrift = item("b", "block", on=on("plate", "+z"), length=a(10), width=a(10), height=a(10),
                      place={"x": {"offset": a(100)}, "y": centred()})  # fmt: skip
        self.assertIn(
            "doesn't meet the +z face it stands on",
            issues(layout_of(PLATE, adrift))[0][1],
        )

    def test_a_body_flush_to_an_edge_uses_its_own_size(self) -> None:
        upright = item("u", "block", on=on("plate", "+z"), length=a(5), width=a(50), height=a(30),
                       place={"x": at("+x", 0, "edge"), "y": centred()})  # fmt: skip
        placed = layout_of(PLATE, upright).instances["u"][0]
        self.assertEqual(
            (placed.lo, placed.hi), ((30.0, -25.0, 4.0), (35.0, 25.0, 34.0))
        )

    def test_an_orientation_that_doesn_t_lie_in_the_face(self) -> None:
        slot = item("s", "slot", on=on("plate", "+z"), width=a(4), length=a(20), along=pick("z"),
                    ends=pick("round"), depth=through())  # fmt: skip
        self.assertIn(("fault", "along is z, which doesn't lie in face +z; it has x and y"),
                      issues(layout_of(PLATE, slot)))  # fmt: skip


class EveryValueIsUsed(unittest.TestCase):
    def test_an_angle_on_a_flat_face(self) -> None:
        layout = layout_of(PLATE, hole("plate", "+z", 4, place={"angle": a(90, "deg")}))
        self.assertEqual(kinds(layout), ["fault"])

    def test_a_pattern_value_along_an_axis_the_face_lacks(self) -> None:
        rectangle = {"rectangle": {"x": a(56), "y": a(36), "z": a(99)}}
        layout = layout_of(PLATE, hole("plate", "+z", 4, place={"pattern": rectangle}))
        self.assertIn(
            ("fault", "z runs along z, which face +z doesn't have; it has x and y"),
            issues(layout),
        )

    def test_a_position_a_pattern_already_sets(self) -> None:
        corners = {"corners": {"inset_x": a(6), "inset_y": a(6)}}
        place = {"x": {"offset": a(10)}, "pattern": corners}
        self.assertIn(("fault", "the corners pattern sets where copies are along x; leave place.x out"),
                      issues(layout_of(PLATE, hole("plate", "+z", 4, place=place))))  # fmt: skip

    def test_fields_for_another_shape_and_the_first_body_s_place(self) -> None:
        round_pocket = item("p", "pocket", on=on("plate", "+z"), shape=pick("circle"), diameter=a(10),
                            length=a(56), depth=a(1))  # fmt: skip
        _, read = read_draft(draft("t", [PLATE, round_pocket]))
        self.assertIn(
            "a pocket's length applies only when its shape is rectangle",
            [p.message for p in read.faults],
        )
        placed = copy.deepcopy(PLATE)
        placed["place"] = {"x": {"offset": a(500)}}
        _, read = read_draft(draft("t", [placed]))
        self.assertIn(
            "a block's place applies only when it has an on",
            [p.message for p in read.faults],
        )


class OnARoundSide(unittest.TestCase):
    collar = item(
        "c",
        "tube",
        outer_diameter=a(30),
        inner_diameter=a(16),
        length=a(12),
        axis=pick("z"),
    )
    rod = item("c", "cylinder", diameter=a(30), length=a(12), axis=pick("z"))

    def test_a_radial_hole(self) -> None:
        place = {"z": centred(), "angle": a(90, "deg")}
        layout = layout_of(self.collar, hole("c", "side", 5, depth=a(6), place=place))
        self.assertEqual(issues(layout), [])
        h = layout.instances["h"][0]
        self.assertAlmostEqual(h.origin[0], 0.0)
        self.assertEqual((round(h.origin[1], 9), h.origin[2]), (15.0, 6.0))

    def test_past_the_end_counts_the_hole_s_size(self) -> None:
        near_end = {"z": at("+z", 1), "angle": a(0, "deg")}
        layout = layout_of(
            self.collar, hole("c", "side", 5, depth=a(6), place=near_end)
        )
        self.assertIn(("question", "h runs past the end of c"), issues(layout))

    def test_wider_than_the_body_or_longer_than_it(self) -> None:
        for d in (30, 13):
            layout = layout_of(
                self.collar, hole("c", "side", d, place={"angle": a(0, "deg")})
            )
            self.assertEqual(kinds(layout), ["cant"], d)

    def test_deeper_than_the_wall(self) -> None:
        radial = {"z": centred(), "angle": a(0, "deg")}
        layout = layout_of(self.collar, hole("c", "side", 5, depth=a(9), place=radial))
        self.assertIn("9 mm deep in 7 mm of material", issues(layout)[0][1])
        # As deep as the wall, its floor would only touch the bore along its middle: asked too.
        layout = layout_of(self.collar, hole("c", "side", 5, depth=a(7), place=radial))
        self.assertIn("7 mm deep in 7 mm of material, its floor just touching the far side", issues(layout)[0][1])
        # Across a solid rod, a hole meets the far side first at its edge:
        # 15 + sqrt(15^2 - 2.5^2) mm from where it goes in.
        layout = layout_of(self.rod, hole("c", "side", 5, depth=a(40), place=radial))
        self.assertIn("40 mm deep in 29.7902 mm of material", issues(layout)[0][1])

    def test_only_holes_are_cut_into_a_round_side(self) -> None:
        pocket = item(
            "p",
            "pocket",
            on=on("c", "side"),
            shape=pick("circle"),
            diameter=a(4),
            depth=a(1),
        )
        self.assertEqual(kinds(layout_of(self.collar, pocket)), ["unable"])

    def test_a_circle_round_the_side_takes_only_a_count(self) -> None:
        holes = hole("c", "side", 4, depth=a(6), count=n(2),
                     place={"z": centred(), "angle": a(90, "deg"),
                            "pattern": {"circle": {"count": n(2), "start": a(90, "deg")}}})  # fmt: skip
        self.assertEqual(kinds(layout_of(self.collar, holes)), ["fault"])
        del holes["place"]["pattern"]["circle"]["start"]
        layout = layout_of(self.collar, holes)
        self.assertEqual(issues(layout), [])
        angles = sorted(
            round(math.degrees(math.atan2(i.origin[1], i.origin[0])))
            for i in layout.instances["h"]
        )
        self.assertEqual(angles, [-90, 90])

    def test_what_stands_on_a_side_is_oriented_the_way_it_is_built(self) -> None:
        # Standing out of +x on a z rod, a post's length runs along y and its width along z.
        post = item("p", "post", on=on("c", "side"), length=a(20), width=a(4), height=a(5),
                    place={"z": centred(), "angle": a(0, "deg")})  # fmt: skip
        layout = layout_of(self.rod, post)
        self.assertEqual(issues(layout), [])
        placed = layout.instances["p"][0]
        assert placed.lo is not None and placed.hi is not None
        self.assertEqual((placed.lo[1:], placed.hi[1:]), ((-10.0, 4.0), (10.0, 8.0)))
        long_way = copy.deepcopy(post)
        long_way["length"], long_way["width"] = a(4), a(20)  # 20 mm along a 12 mm rod
        self.assertEqual(kinds(layout_of(self.rod, long_way)), ["question"])

    def test_a_tab_s_thickness_must_lie_across_its_face(self) -> None:
        tab = item("t", "tab", on=on("c", "side"), length=a(10), width=a(8), thickness=a(2),
                   thickness_along=pick("x"), end=pick("round"), place={"z": centred(), "angle": a(0, "deg")})  # fmt: skip
        self.assertEqual(
            kinds(layout_of(self.rod, tab)), ["fault"]
        )  # out of +x, it can't be thin along x
        tab["thickness_along"] = pick("z")
        self.assertEqual(issues(layout_of(self.rod, tab)), [])

    def test_a_boss_reaching_across_a_bore(self) -> None:
        boss = item("b", "boss", on=on("c", "bore"), diameter=a(3), height=a(20),
                    place={"z": centred(), "angle": a(0, "deg")})  # fmt: skip
        self.assertIn(
            "reaches across the bore", issues(layout_of(self.collar, boss))[0][1]
        )


class Copies(unittest.TestCase):
    def test_an_assumption_is_said_once_for_every_copy_of_the_host(self) -> None:
        bosses = item("b", "boss", on=on("plate", "+z"), diameter=a(10), height=a(5),
                      place={"pattern": {"rectangle": {"x": a(40), "y": a(30)}}})  # fmt: skip
        layout = layout_of(PLATE, bosses, hole("b", "+end", 3, depth=a(4)))
        self.assertEqual(len(layout.instances["h"]), 4)
        centring = [x for x in layout.assumptions if x.at == "/items/2"]
        self.assertEqual(len(centring), 2)  # x and y, once each, not once per boss

    def test_a_blind_hole_in_a_boss_runs_on_into_the_plate(self) -> None:
        boss = item("b", "boss", on=on("plate", "+z"), diameter=a(10), height=a(5))
        self.assertEqual(
            issues(layout_of(PLATE, boss, hole("b", "+end", 3, depth=a(7)))), []
        )  # 5 + 4 mm
        self.assertEqual(
            kinds(layout_of(PLATE, boss, hole("b", "+end", 3, depth=a(10)))),
            ["question"],
        )

    def test_too_many_copies(self) -> None:
        grid = {
            "grid": {
                "count_x": n(1000),
                "pitch_x": a(0.05),
                "count_y": n(1000),
                "pitch_y": a(0.04),
            }
        }
        layout = layout_of(PLATE, hole("plate", "+z", 0.01, place={"pattern": grid}))
        self.assertEqual(kinds(layout), ["unable"])
        self.assertIn(f"at most {MAX_COPIES:,}", issues(layout)[0][1])

    def test_a_pattern_of_none(self) -> None:
        row = {
            "row": {
                "axis": pick("x"),
                "pitch": a(5),
                "count": {"count": 0, "from": assumed("t")},
            }
        }
        _, read = read_draft(
            draft("t", [PLATE, hole("plate", "+z", 3, place={"pattern": row})])
        )
        self.assertIn("a pattern places at least one", [p.message for p in read.faults])

    def test_a_position_says_one_thing(self) -> None:
        for position in ({"centred": assumed("t"), "side": "+x", "distance": a(3)},
                         {"offset": a(3), "to": "edge"}, {"side": "+x"}, {"centred": assumed("t"), "to": "edge"}):  # fmt: skip
            _, read = read_draft(
                draft("t", [PLATE, hole("plate", "+z", 3, place={"x": position})])
            )
            self.assertTrue(
                any(p.at.endswith("/place/x") for p in read.faults), position
            )

    def test_copies_that_overlap(self) -> None:
        def problems_with(pattern: dict[str, Any]) -> list[tuple[str, str]]:
            return issues(
                layout_of(PLATE, hole("plate", "+z", 4, place={"pattern": pattern}))
            )

        self.assertIn(
            "overlap",
            problems_with({"row": {"axis": pick("x"), "pitch": a(3), "count": n(3)}})[
                0
            ][1],
        )
        self.assertIn(
            "land on each other",
            problems_with({"rectangle": {"x": a(0), "y": a(20)}})[0][1],
        )
        self.assertIn(
            "would meet or cross",
            problems_with({"corners": {"inset_x": a(40), "inset_y": a(6)}})[0][1],
        )
        tight = {
            "circle": {"diameter": a(10), "count": n(8)}
        }  # a chord of 3.8 mm between 4 mm holes
        self.assertIn("overlap", problems_with(tight)[0][1])
        touching = {"row": {"axis": pick("x"), "pitch": a(4), "count": n(3)}}
        self.assertEqual(problems_with(touching), [])

    def test_concentric_with_each_copy_of_its_host(self) -> None:
        bosses = item("b", "boss", on=on("plate", "+z"), diameter=a(10), height=a(5),
                      place={"pattern": {"rectangle": {"x": a(40), "y": a(30)}}})  # fmt: skip
        holes = hole("b", "+end", 3, depth=a(4), count=n(4),
                     place={"concentric": {"item": "b", "from": assumed("a hole in each boss")}})  # fmt: skip
        layout = layout_of(PLATE, bosses, holes)
        self.assertEqual(issues(layout), [])
        self.assertEqual(sorted(h.origin[:2] for h in layout.instances["h"]),
                         [(-20.0, -15.0), (-20.0, 15.0), (20.0, -15.0), (20.0, 15.0)])  # fmt: skip

    def test_concentric_needs_a_shared_axis(self) -> None:
        pin = item("pin", "boss", on=on("plate", "+z"), diameter=a(6), height=a(10))
        side = hole(
            "plate",
            "-x",
            3,
            depth=a(5),
            place={"concentric": {"item": "pin", "from": assumed("t")}},
        )
        self.assertIn(
            "axis doesn't run through face -x",
            issues(layout_of(PLATE, pin, side))[0][1],
        )


class Hollows(unittest.TestCase):
    # V1 corpus C10: a tray 100 x 60 x 25 mm, 2 mm walls and floor, open top, a divider across the middle.
    tray = item("tray", "block", length=a(100), width=a(60), height=a(25))
    hollow = shell("tray", 2, "+z")

    def test_a_divider_stands_on_the_floor_inside(self) -> None:
        divider = item(
            "divider",
            "post",
            on=on("tray", "inner -z"),
            length=a(2),
            width=a(56),
            height=a(23),
        )
        layout = layout_of(self.tray, self.hollow, divider)
        self.assertEqual(issues(layout), [])
        placed = layout.instances["divider"][0]
        self.assertEqual(
            (placed.lo, placed.hi), ((-1.0, -28.0, 2.0), (1.0, 28.0, 25.0))
        )

    def test_nothing_stands_in_an_open_faces_mouth(self) -> None:
        # Its rim takes things (shell.md, "The rim"); its middle is the hollow's mouth.
        boss = item("b", "boss", on=on("tray", "+z"), diameter=a(5), height=a(5))
        self.assertIn(
            "runs past the edge of face +z",
            issues(layout_of(self.tray, self.hollow, boss))[0][1],
        )

    def test_a_hole_through_the_floor_meets_the_floor_s_thickness(self) -> None:
        self.assertEqual(
            issues(layout_of(self.tray, self.hollow, hole("tray", "-z", 3))), []
        )
        layout = layout_of(self.tray, self.hollow, hole("tray", "-z", 3, depth=a(3)))
        self.assertIn("3 mm deep in 2 mm of material", issues(layout)[0][1])

    def test_walls_that_leave_a_hollow(self) -> None:
        def block(x: float, y: float, z: float) -> dict[str, Any]:
            return item("c", "block", length=a(x), width=a(y), height=a(z))

        cases = [
            ([block(100, 100, 6), shell("c", 3, "+z")], []),
            ([block(50, 50, 2), shell("c", 5, "+z", "-z")], []),
            ([block(30, 30, 10), shell("c", 6, "+z", floor=a(2))], []),
            ([block(30, 30, 10), shell("c", 2, "+z", floor=a(12))], ["cant"]),
            ([block(40, 40, 40), shell("c", 2)], []),
            ([item("c", "sphere", diameter=a(40), portion=pick("whole")), shell("c", 3)], []),
            ([item("c", "sphere", diameter=a(20), portion=pick("upper_half")), shell("c", 6)], ["cant"]),
            ([item("c", "sphere", diameter=a(20), portion=pick("upper_half")), shell("c", 3, "-end")], []),
            ([item("c", "tube", outer_diameter=a(30), inner_diameter=a(24), length=a(80)), shell("c", 3)], ["fault"]),
            ([item("c", "cone", base_diameter=a(40), top_diameter=a(50), length=a(60)), shell("c", 2, "+end")], []),
            ([item("c", "cone", base_diameter=a(40), top_diameter=a(0), length=a(60)), shell("c", 2, "-end")],
             ["unable"]),  # a cone that comes to a point isn't hollowed yet (shell.md, "cone")
            ([item("c", "cylinder", diameter=a(60), length=a(80)), shell("c", 2, "+end", floor=a(3))], []),
            ([item("c", "cylinder", diameter=a(60), length=a(80)), shell("c", 2, "side")], ["fault"]),
        ]  # fmt: skip
        for items, expected in cases:
            self.assertEqual(kinds(layout_of(*items)), expected, items)

    def test_a_cup_s_inside(self) -> None:
        # V1 corpus: a cup 60 mm across and 80 mm tall, 2 mm walls and a 3 mm floor, open at the top.
        cup = [item("c", "cylinder", diameter=a(60), length=a(80), axis=pick("z")),
               shell("c", 2, "+end", floor=a(3))]  # fmt: skip
        layout = layout_of(*cup)
        floor = layout.faces[("c", 0)]["inner -end"]
        inside = layout.faces[("c", 0)]["inner side"]
        assert isinstance(floor, FlatFace) and isinstance(inside, SideFace)
        self.assertEqual(
            (floor.centre, floor.normal, floor.half),
            ((0.0, 0.0, 3.0), "+z", (28.0, 28.0)),
        )
        self.assertEqual(
            (inside.start, inside.length, inside.radius), ((0.0, 0.0, 3.0), 77.0, 28.0)
        )
        self.assertIn("inner +end", layout.closed[("c", 0)])


class Balls(unittest.TestCase):
    def test_a_ball_on_a_face_is_centred_on_it(self) -> None:
        rod = item("rod", "cylinder", diameter=a(8), length=a(50), axis=pick("z"))
        ball = item(
            "ball",
            "sphere",
            on=on("rod", "+end"),
            diameter=a(12),
            portion=pick("whole"),
        )
        layout = layout_of(rod, ball)
        self.assertEqual(issues(layout), [])
        placed = layout.instances["ball"][0]
        self.assertEqual((placed.lo, placed.hi), ((-6.0, -6.0, 44.0), (6.0, 6.0, 56.0)))

    def test_a_dome_stands_on_its_flat_face(self) -> None:
        dome = item(
            "dome",
            "sphere",
            on=on("plate", "+z"),
            diameter=a(20),
            portion=pick("upper_half"),
        )
        placed = layout_of(PLATE, dome).instances["dome"][0]
        self.assertEqual(
            (placed.lo, placed.hi), ((-10.0, -10.0, 4.0), (10.0, 10.0, 14.0))
        )


class Depths(unittest.TestCase):
    def test_into_a_cone_s_base_and_a_dome_s_flat(self) -> None:
        cone = item(
            "c",
            "cone",
            base_diameter=a(20),
            top_diameter=a(10),
            length=a(3),
            axis=pick("z"),
        )
        self.assertIn(
            "10 mm deep in 3 mm",
            issues(layout_of(cone, hole("c", "-end", 4, depth=a(10))))[0][1],
        )
        rim = {
            "x": {"offset": a(7)},
            "y": centred(),
        }  # 7..9 mm out: 0.6 mm of cone at its outer edge
        self.assertEqual(
            kinds(layout_of(cone, hole("c", "-end", 4, depth=a(2), place=rim))),
            ["question"],
        )
        dome = item("c", "sphere", diameter=a(20), portion=pick("upper_half"))
        self.assertEqual(issues(layout_of(dome, hole("c", "-end", 4, depth=a(9)))), [])
        self.assertEqual(
            kinds(layout_of(dome, hole("c", "-end", 4, depth=a(9.9)))), ["question"]
        )

    def test_counterbores_countersinks_and_engraving(self) -> None:
        bore = {"diameter": a(8), "depth": a(6)}
        layout = layout_of(PLATE, hole("plate", "+z", 4, counterbore=bore))
        self.assertIn("counterbore is 6 mm deep in 4 mm", issues(layout)[0][1])
        sink = {"diameter": a(18), "angle": a(90, "deg")}  # a 7 mm deep cone
        self.assertIn(
            "countersink is 7 mm deep",
            issues(layout_of(PLATE, hole("plate", "+z", 4, countersink=sink)))[0][1],
        )
        for angle in (0, 180, 270):
            sunk = hole(
                "plate",
                "+z",
                4,
                countersink={"diameter": a(8), "angle": a(angle, "deg")},
            )
            _, read = read_draft(draft("t", [PLATE, sunk]))
            self.assertTrue(read.faults, angle)
        text = item("t", "text", on=on("plate", "+z"), text={"text": "AB", "from": assumed("t")}, height=a(5),
                    depth=a(6), mode=pick("engrave"))  # fmt: skip
        self.assertIn("6 mm deep in 4 mm", issues(layout_of(PLATE, text))[0][1])
        text["mode"] = pick("emboss")
        self.assertEqual(issues(layout_of(PLATE, text)), [])


class Routing(unittest.TestCase):
    def test_an_assumed_value_that_doesn_t_fit_goes_back_to_the_writer(self) -> None:
        layout = layout_of(
            PLATE,
            item(
                "h", "hole", on=on("plate", "+z"), diameter=guess(60), depth=through()
            ),
        )
        self.assertEqual(issues(layout)[0], ("fault", "h (60 x 60 mm) is larger than the face it is on (+z, 70 x 50 "
                                             "mm): cut through, it would cut the part apart" + ASSUMED))  # fmt: skip

    def test_an_assumed_centre_is_not_blamed(self) -> None:
        holes = hole("plate", "+z", 4, place={"x": centred(), "y": centred(),
                                              "pattern": {"rectangle": {"x": a(68), "y": a(36)}}})  # fmt: skip
        self.assertEqual(kinds(layout_of(PLATE, holes)), ["question"])


class TheOrder(unittest.TestCase):
    def test_a_long_chain_is_ordered_without_recursion(self) -> None:
        chain = [PLATE] + [item(f"b{k}", "boss", on=on("plate" if k == 0 else f"b{k - 1}", "+end" if k else "+z"),
                                diameter=a(5), height=a(1)) for k in range(2000)]  # fmt: skip
        layout = layout_of(*reversed(chain))
        self.assertEqual(issues(layout), [])
        extent = layout.extent()
        assert extent is not None
        self.assertEqual(extent[1][2], 2004.0)

    def test_a_loop_is_reported_once(self) -> None:
        loop = [PLATE, item("p", "boss", on=on("q", "+end"), diameter=a(5), height=a(1)),
                item("q", "boss", on=on("p", "+end"), diameter=a(5), height=a(1))]  # fmt: skip
        self.assertEqual(
            issues(layout_of(*loop)),
            [("fault", "items depend on each other in a loop: p, q")],
        )


def _junk(rng: random.Random, depth: int = 0) -> Any:
    choices: list[Any] = [None, True, -1, 0, 3, 1e308, 10**400, float("nan"), "", "x", "+z", "mm", [], {},
                          "\ud800"]  # fmt: skip
    if depth < 3:
        choices += [[_junk(rng, depth + 1)], {"value": _junk(rng, depth + 1)},
                    {"from": _junk(rng, depth + 1)}, [1, 2], {"words": [10**9]}, {1: 2}]  # fmt: skip
    return rng.choice(choices)


def _paths(node: Any, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    found = [path]
    if isinstance(node, dict):
        for key, value in node.items():
            found += _paths(value, (*path, key))
    elif isinstance(node, list):
        for k, value in enumerate(node):
            found += _paths(value, (*path, k))
    return found


class NoDraftMakesTheChecksRaise(unittest.TestCase):
    def test_random_damage_to_good_drafts(self) -> None:
        from forge_spec.render import render
        from test_v2_spec_partspec import bracket_draft, flange_draft, plate_draft

        rng = random.Random(20261021)
        goods = [plate_draft(), flange_draft(), bracket_draft()]
        goods += [
            (BRIEF, draft("t", copy.deepcopy(items)))
            for items in [*EXAMPLES.values(), *HOLLOWED.values()]
        ]
        for brief, good in goods:
            paths = _paths(good)[1:]
            for _ in range(150):
                bad = copy.deepcopy(good)
                for _ in range(rng.randint(1, 3)):
                    path = rng.choice(paths)
                    node = bad
                    try:
                        for key in path[:-1]:
                            node = node[key]
                        if rng.random() < 0.2 and isinstance(node, dict):
                            node.pop(path[-1], None)
                        else:
                            node[path[-1]] = _junk(rng)
                    except (KeyError, IndexError, TypeError):
                        continue
                try:
                    report = check_draft(brief, bad)
                    check_draft(brief, bad, strict=True)
                    render(report, brief).text()
                except (
                    Exception
                ) as exc:  # pragma: no cover - the failure being tested for
                    self.fail(f"{type(exc).__name__}: {exc} on {bad!r}")


if __name__ == "__main__":
    unittest.main()


class RoundingsAndThreads(unittest.TestCase):
    """What a rounding or a thread can go on, checked on the spec (forge_spec.checks)."""

    def check(self, *items: dict[str, Any]) -> list[tuple[str, str]]:
        """The problems these items have; not the citation faults their placeholder words give."""
        report = check_draft(BRIEF, draft("t", list(items)))
        return [(p.kind, p.message) for p in report.problems
                if p.at.startswith("/items") and not p.message.startswith("the cited words")]  # fmt: skip

    def rounding(
        self, of: str, which: str, size: float, kind: str = "fillet", **edges: Any
    ) -> dict[str, Any]:
        name = "radius" if kind == "fillet" else "size"
        return item(
            "r", kind, edges={"of": of, "which": which, **edges}, **{name: a(size)}
        )

    def cants(self, *items: dict[str, Any]) -> list[str]:
        return [m for k, m in self.check(*items) if k == "cant"]

    def test_a_block_s_top_edges_take_up_to_its_height(self) -> None:
        self.assertEqual(
            self.cants(PLATE, self.rounding("plate", "top", 3)), []
        )  # 3 mm on a 4 mm plate
        self.assertTrue(
            self.cants(PLATE, self.rounding("plate", "all", 3))
        )  # top and bottom: 2 mm at most
        self.assertTrue(self.cants(PLATE, self.rounding("plate", "top", 4.5)))

    def test_limits_for_bosses_posts_cones_and_holes(self) -> None:
        boss = item("b", "boss", on=on("plate", "+z"), diameter=a(10), height=a(8))
        self.assertTrue(self.cants(PLATE, boss, self.rounding("b", "top", 50)))
        post = item(
            "p", "post", on=on("plate", "+z"), length=a(8), width=a(8), height=a(8)
        )
        self.assertTrue(self.cants(PLATE, post, self.rounding("p", "vertical", 40)))
        cone = item(
            "cone", "cone", base_diameter=a(20), top_diameter=a(10), length=a(10)
        )
        self.assertTrue(self.cants(cone, self.rounding("cone", "bottom", 100)))
        self.assertTrue(
            self.cants(
                PLATE, hole("plate", "+z", 4), self.rounding("h", "top", 20, "chamfer")
            )
        )

    def test_a_tube_s_outer_edge_alone(self) -> None:
        tube = item(
            "t", "tube", outer_diameter=a(20), inner_diameter=a(14), length=a(30)
        )  # a 3 mm wall
        self.assertEqual(self.cants(tube, self.rounding("t", "outer", 2)), [])
        self.assertTrue(
            self.cants(tube, self.rounding("t", "top", 2))
        )  # two edges share the wall

    def test_a_joint_between_two_blocks(self) -> None:
        upright = item(
            "u", "block", on=on("plate", "+z"), length=a(5), width=a(50), height=a(30)
        )
        fillet = self.rounding("u", "joint", 3, where_meets="plate")
        self.assertEqual(self.check(PLATE, upright, fillet), [])

    def test_the_rim_of_a_side_left_open(self) -> None:
        box = item("box", "block", length=a(60), width=a(40), height=a(30))
        side_open = item("hollow", "shell", of="box", thickness=a(2), open=opened("+x"))
        messages = [
            m
            for k, m in self.check(box, side_open, self.rounding("box", "top", 3))
            if k == "question"
        ]
        self.assertTrue(any("open rim" in m for m in messages))

    def test_a_thread_goes_on_a_rod_it_fits(self) -> None:
        rod = item("rod", "cylinder", diameter=a(8), length=a(40))

        def thread(of: str, designation: str, **fields: Any) -> dict[str, Any]:
            return item("th", "thread", of=of, designation={"text": designation, "from": assumed("t")},
                        hand=pick("right"), **fields)  # fmt: skip

        self.assertEqual(self.check(rod, thread("rod", "M8")), [])
        self.assertEqual(
            [k for k, _ in self.check(rod, thread("ghost", "M8"))], ["fault"]
        )
        self.assertEqual(
            [k for k, _ in self.check(PLATE, thread("plate", "M8"))], ["fault"]
        )
        thick = item("rod", "cylinder", diameter=a(20), length=a(40))
        self.assertEqual(
            [k for k, _ in self.check(thick, thread("rod", "M8"))], ["fault"]
        )  # assumed text
        self.assertEqual(
            [k for k, _ in self.check(rod, thread("rod", "M8", length=a(90)))], ["cant"]
        )
        self.assertEqual(
            [k for k, _ in self.check(rod, thread("rod", "1/4-20"))], ["unable"]
        )
