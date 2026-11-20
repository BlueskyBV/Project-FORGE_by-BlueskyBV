"""V2: what writing the field definitions found (docs/definitions), pinned.

Writing down what every field means, so that three programs can each be
coded from the text alone, turned up places where the code and the meaning
parted. Each is pinned here, with the meaning the definitions now give.
Drafts here are built for the tests, never from the blind sets.

The make order and the material:

- the next item made is the earliest in the spec whose dependencies are all
  made; a hollowed body is made whole, its own roundings before its hollow;
  every other rounding, chamfer and thread comes last, in the spec's order;
- a cone wider at its top has only its own material beyond its foot;
- a cut through goes as deep as the most material under its mouth;
- a standing item's far face has its host's material under it where it is
  over the host's face, and a pocket's floor what was under it less its
  depth.

Shapes and faces:

- a round-ended tab's broad faces are rounded by half its width;
- a whole ball's hollow, or a dome's open underneath, has no floor;
- a countersink as deep as its hole leaves none below it;
- the rim of an open hollow is judged by the way its body stands;
- a rounding of edges that aren't there is turned back, never skipped, and a
  dome's joint may be rounded;
- nothing stands wholly over a cut's mouth, nor does a cut take away all a
  thing stands on; a pocket's floor with a bore through it takes nothing.

Places:

- from an edge, a row, grid or rectangle is measured to its nearest copy, a
  circle to its centre and only its centre; the wording says so;
- an unsaid "to" is the centre, recorded as an assumption;
- round a side, a blind hole fits the least material under its mouth, and a
  hole as wide as a tube's bore is asked about.

Letters and outlines:

- letters are set in the pinned font: their real width decides whether they
  fit, a letter the font lacks ends UNABLE, a line break is a fault, and
  embossed letters never sever the part;
- two drafts' letters are compared by the way they really read;
- an arc ends on its circle, an outline never crosses or touches itself, and
  a revolution's outline never crosses its axis.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any

from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.draft import Profile, read_draft
from forge_spec.geometry import (
    FlatFace,
    SideFace,
    disc,
    material_at,
    part_on_face,
    side_most_material,
)
from forge_spec.placement import Layout, solve
from forge_spec.render import render
from forge_spec.render_views import _cut_span, render_views
from forge_spec.wire import to_wire

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_spec_placement import (
    PLATE,
    a,
    at,
    hole,
    issues,
    item,
    layout_of,
    n,
    on,
    pick,
    shell,
)
from test_v2_spec_review5 import centred as c5
from test_v2_spec_review5 import chose as chose5
from test_v2_spec_review5 import compared, given, slab, thing
from v2_drafts import draft

#: A brief with nothing to account for, so a draft's problems are the shape's own.
PART = number_words("A part.")


def g(value: float, unit: str = "mm") -> dict[str, Any]:
    """A value the writer assumed: nothing in the brief to cite."""
    return {"value": value, "unit": unit, "from": {"assumed": "for the test"}}


def x(kind: str, item_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": item_id, "kind": kind, "words": [1], **fields}


def choice(value: str) -> dict[str, Any]:
    return {"choose": value, "from": {"assumed": "for the test"}}


def problems(*items: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (p.kind, p.message) for p in check_draft(PART, draft("t", list(items))).problems
    ]


def faces(layout: Layout, key: tuple[str, int]) -> dict[str, FlatFace | SideFace]:
    return layout.faces[key]


class TheMakeOrder(unittest.TestCase):
    def test_the_earliest_ready_item_next(self) -> None:
        # b2 is listed before b1, which it stands on: it is made as soon as b1
        # is, before the hole listed after it.
        layout = layout_of(PLATE, item("b2", "block", on=on("b1", "+x"), length=a(20), width=a(20), height=a(20)),
                           item("b1", "block", on=on("plate", "+z"), length=a(10), width=a(10), height=a(10)),
                           hole("plate", "+z", 4, place={"x": {"offset": a(25)}}))  # fmt: skip
        self.assertEqual(layout.order, ["plate", "b1", "b2", "h"])

    def test_roundings_chamfers_and_threads_last_in_the_spec_s_order(self) -> None:
        edges = {"of": "rod", "which": "top", "words": [2]}
        layout = layout_of(item("ch", "chamfer", edges=edges, size=a(1)),
                           item("rod", "cylinder", diameter=a(8), length=a(30), axis=pick("z")),
                           item("t", "thread", of="rod", designation={"text": "M8", "from": {"words": [2]}},
                                hand=pick("right")),
                           item("f", "fillet", edges=dict(edges, which="bottom"), radius=a(1)))  # fmt: skip
        self.assertEqual(layout.order, ["rod", "ch", "t", "f"])

    def test_a_hollowed_body_is_made_whole_its_own_roundings_first(self) -> None:
        # So a tray's walls follow its rounded corners (docs/definitions/shell.md).
        layout = layout_of(item("box", "block", length=a(80), width=a(60), height=a(30)),
                           item("joint", "fillet", radius=a(1),
                                edges={"of": "p", "which": "joint", "where_meets": "box", "words": [2]}),
                           item("p", "post", on=on("box", "inner -z"), length=a(4), width=a(4), height=a(5)),
                           shell("box", 2, "+z"),
                           item("corners", "fillet", edges={"of": "box", "which": "vertical", "words": [2]},
                                radius=a(5)))  # fmt: skip
        self.assertEqual(layout.order, ["box", "corners", "hollow", "p", "joint"])


class TheMaterialUnderAFace(unittest.TestCase):
    def test_an_upside_down_cone_has_only_its_own_beyond_its_foot(self) -> None:
        plate = item("plate", "block", length=a(70), width=a(50), height=a(5))
        layout = layout_of(plate, item("c", "cone", on=on("plate", "+z"), base_diameter=a(10), top_diameter=a(20),
                                       length=a(10)))  # fmt: skip
        top = faces(layout, ("c", 0))["+end"]
        assert isinstance(top, FlatFace)
        self.assertAlmostEqual(
            material_at(top, 2.0, 0.0, 0.0), 15.0
        )  # over its foot: the plate too
        self.assertAlmostEqual(
            material_at(top, 7.5, 0.0, 0.0), 5.0
        )  # halfway out the slope: the cone's own half

    def test_through_goes_as_deep_as_the_most_under_the_mouth(self) -> None:
        # A hole 10 off the axis of a cone's base: 20 mm of cone out to r 5,
        # nothing at r 15; under the hole's mouth, r from 8 to 12.
        spec, _ = read_draft(draft("t", [item("c", "cone", base_diameter=a(30), top_diameter=a(10), length=a(20),
                                              axis=pick("z")),
                                         hole("c", "-end", 4, place={"x": {"offset": a(10)}})]))  # fmt: skip
        assert spec is not None
        layout = solve(spec)
        deep, exits = _cut_span(spec.items[1], layout.instances["h"][0], layout)
        self.assertAlmostEqual(deep, 20 * (15 - 8) / 10)
        self.assertTrue(exits)


class OverAHostAndOverAnOverhang(unittest.TestCase):
    """frame.md: a standing item's far face has its host's material under it where it is over the host's face.

    A 20 mm block 10 high stands 30 along x on the 70 x 4 plate: from x = 20
    to 40, over the plate to x = 35, over air beyond. A disc turned 10 out
    and 4 high stands at the same place; a pocket 2 deep sinks into the
    block's top.
    """

    BLOCK = item("blk", "block", on=on("plate", "+z"), length=a(20), width=a(20), height=a(10),
                 place={"x": {"offset": a(30)}})  # fmt: skip
    DISC = item("disc", "revolution", on=on("plate", "+z"), place={"x": {"offset": a(30)}},
                profile={"start": [0, 0], "from": {"assumed": "t"},
                         "segments": [{"line_to": [10, 0]}, {"line_to": [10, 4]}, {"line_to": [0, 4]},
                                      {"line_to": [0, 0]}]})  # fmt: skip
    POCKET = item("pk", "pocket", on=on("blk", "+z"), shape=pick("rectangle"), length=a(18), width=a(10),
                  depth=a(2))  # fmt: skip

    def span(self, *items: dict[str, Any]) -> tuple[float, bool]:
        spec, read = read_draft(draft("t", [PLATE, *items]))
        assert spec is not None and not read.faults, read.faults
        layout = solve(spec)
        self.assertEqual(issues(layout), [])
        return _cut_span(spec.items[-1], layout.instances["h"][0], layout)

    def test_through_goes_through_the_host_too_where_it_is_over_it(self) -> None:
        for host, face, x, deep in (("blk", "+z", -5, 14.0), ("blk", "+z", 4.5, 14.0),
                                    ("blk", "+z", 8, 10.0), ("disc", "+end", -5, 8.0),
                                    ("disc", "+end", 4.5, 8.0), ("disc", "+end", 7, 4.0)):  # fmt: skip
            standing = self.BLOCK if host == "blk" else self.DISC
            # A hole 2 across, from x - 1 to x + 1 along the face from its middle.
            with self.subTest(host=host, x=x):
                h = hole(host, face, 2, place={"x": {"offset": a(x)}})
                self.assertEqual(self.span(standing, h), (deep, True))

    def test_a_blind_cut_fits_the_least_under_its_mouth(self) -> None:
        for host, face, x, depth, asked in (("blk", "+z", -5, 13, False), ("blk", "+z", 4.5, 11, True),
                                            ("disc", "+end", -5, 7, False), ("disc", "+end", 4.5, 5, True)):  # fmt: skip
            standing = self.BLOCK if host == "blk" else self.DISC
            with self.subTest(host=host, x=x):
                h = hole(host, face, 2, depth=a(depth), place={"x": {"offset": a(x)}})
                found = issues(layout_of(PLATE, standing, h))
                self.assertEqual(any("mm deep in" in m for _, m in found), asked, found)

    def test_a_pocket_s_floor_is_what_was_under_it_less_its_depth(self) -> None:
        for x, deep in ((-5, 12.0), (8, 8.0)):
            with self.subTest(x=x):
                h = hole("pk", "bottom", 1, place={"x": {"offset": a(x)}})
                self.assertEqual(self.span(self.BLOCK, self.POCKET, h), (deep, True))


class ShapesAndFaces(unittest.TestCase):
    def test_a_round_ended_tabs_broad_face(self) -> None:
        layout = layout_of(PLATE, item("t", "tab", on=on("plate", "+z"), length=a(6), width=a(10), thickness=a(2),
                                       thickness_along=pick("y"), end=pick("round")))  # fmt: skip
        face = faces(layout, ("t", 0))["+y"]
        assert isinstance(face, FlatFace)
        self.assertEqual(face.corners, (5.0, 5.0, 0.0, 0.0))
        # Its half-circle is centred 1 mm up from its foot (z 5), radius 5.
        for point, inside in (
            ((4.5, 8.0), False),
            ((0.0, 9.99), True),
            ((4.99, 4.5), True),
            ((3.0, 9.0), True),
        ):
            u = (point[0] - face.centre[0], point[1] - face.centre[2])
            self.assertEqual(part_on_face(face, disc(0.0), *u), inside, point)

    def test_a_floor_no_hollow_has(self) -> None:
        ball = item("b", "sphere", diameter=a(20), portion=pick("whole"))
        dome = item("b", "sphere", diameter=a(20), portion=pick("upper_half"))
        self.assertIn("a whole ball: its hollow has no floor; leave the floor out",
                      issues(layout_of(ball, shell("b", 2, floor=a(3))))[0][1])  # fmt: skip
        self.assertIn("open underneath: its hollow has no floor",
                      issues(layout_of(dome, shell("b", 2, "-end", floor=a(3))))[0][1])  # fmt: skip
        self.assertEqual(issues(layout_of(dome, shell("b", 2, floor=a(3)))), [])

    def test_a_countersink_as_deep_as_its_hole(self) -> None:
        sink = {"diameter": a(9), "angle": a(90, "deg")}
        found = issues(
            layout_of(PLATE, hole("plate", "+z", 3, depth=a(2), countersink=sink))
        )
        self.assertIn(("question", "the countersink (3 mm deep) is as deep as the hole (2 mm): there's no hole "
                                   "left below it"), found)  # fmt: skip

    def test_the_rim_of_an_open_hollow_by_the_way_it_stands(self) -> None:
        # A box standing on the plate's +x face rises along +x: its +z face is
        # one of its sides, so its vertical edges run past the open rim, whose
        # outside and inside edges both take the rounding: half the wall each.
        def rounded(radius: float) -> list[str]:
            return [m for _, m in problems(x("block", "plate", length=g(70), width=g(50), height=g(20)),
                                           x("block", "box", on={"item": "plate", "face": "+x"}, length=g(30),
                                             width=g(20), height=g(30)),
                                           x("shell", "hollow", of="box", thickness=g(2),
                                             open={"faces": ["+z"], "from": {"assumed": "t"}}),
                                           x("fillet", "r", edges={"of": "box", "which": "vertical", "words": [1]},
                                             radius=g(radius)))]  # fmt: skip

        rim = "on both edges of the 2 mm wall at the open rim of box doesn't fit (at most 1 mm)"
        self.assertTrue(any(rim in m for m in rounded(1.5)), rounded(1.5))
        # Half the wall each: the two meet in the rim's middle, which OpenCascade can't make (asked; revision 18).
        self.assertTrue(any("open rim of box rounds it right over" in m for m in rounded(1.0)), rounded(1.0))
        self.assertFalse(any("open rim" in m for m in rounded(0.9)), rounded(0.9))

    def test_a_hollowed_body_s_roundings_either_side_of_its_hollow(self) -> None:
        # The tray's corners are rounded before its hollow (its walls follow
        # them); its open top's rim after it; "all" is both.
        def order(which: str) -> list[str]:
            return layout_of(item("box", "block", length=a(80), width=a(60), height=a(30)), shell("box", 2, "+z"),
                             item("r", "fillet", edges={"of": "box", "which": which, "words": [2]},
                                  radius=a(1))).order  # fmt: skip

        self.assertEqual(order("vertical"), ["box", "r", "hollow"])
        self.assertEqual(order("top"), ["box", "hollow", "r"])
        self.assertEqual(order("all"), ["box", "r", "hollow", "r"])


class EdgesThatArentThere(unittest.TestCase):
    PLATE = x("block", "plate", length=g(70), width=g(50), height=g(5))

    def rounded(self, target: str, which: str, *items: dict[str, Any]) -> list[str]:
        return [m for _, m in problems(*items, x("fillet", "r", edges={"of": target, "which": which, "words": [1]},
                                                 radius=g(1)))]  # fmt: skip

    def test_the_base_of_a_block_standing_wholly_on_a_face(self) -> None:
        on_it = x(
            "block",
            "b",
            on={"item": "plate", "face": "+z"},
            length=g(10),
            width=g(10),
            height=g(10),
        )
        self.assertTrue(
            any(
                "its base has no outside edges" in m
                for m in self.rounded("b", "bottom", self.PLATE, on_it)
            )
        )
        over = x(
            "block",
            "b",
            on={"item": "plate", "face": "+z"},
            length=g(100),
            width=g(10),
            height=g(10),
        )
        self.assertFalse(
            any(
                "no outside edges" in m
                for m in self.rounded("b", "bottom", self.PLATE, over)
            )
        )

    def test_a_whole_ball_has_no_rim(self) -> None:
        ball = x("sphere", "b", diameter=g(20), portion=choice("whole"))
        self.assertIn(
            "b is a whole ball: it has no rim to round",
            self.rounded("b", "bottom", ball),
        )

    def test_a_dome_s_joint(self) -> None:
        dome = x(
            "sphere",
            "d",
            on={"item": "plate", "face": "+z"},
            diameter=g(20),
            portion=choice("upper_half"),
        )
        found = [m for _, m in problems(self.PLATE, dome, x("fillet", "r", radius=g(1),
                                        edges={"of": "d", "which": "joint", "where_meets": "plate", "words": [1]}))]  # fmt: skip
        self.assertFalse(any("edges are" in m for m in found), found)


class NothingHeldUpByNothing(unittest.TestCase):
    POST = item(
        "p", "post", on=on("plate", "+z"), length=a(4), width=a(4), height=a(10)
    )

    def test_standing_wholly_over_a_mouth_either_way_round(self) -> None:
        self.assertEqual(issues(layout_of(PLATE, hole("plate", "+z", 20), self.POST)),
                         [("question", "p copy 1 stands wholly over the mouth of h copy 1: nothing would hold it up")])  # fmt: skip
        self.assertEqual(issues(layout_of(PLATE, self.POST, hole("plate", "+z", 20))),
                         [("question", "h copy 1 takes away all that p copy 1 stands on: nothing would hold it up")])  # fmt: skip

    def test_partly_over_it_is_held(self) -> None:
        self.assertEqual(
            issues(layout_of(PLATE, hole("plate", "+z", 5), self.POST)), []
        )

    def test_over_a_slot_s_round_end(self) -> None:
        slot = item("s", "slot", on=on("plate", "+z"), width=a(6), length=a(30), along=pick("x"), ends=pick("round"),
                    depth=a(2))  # fmt: skip
        post = item("p", "post", on=on("plate", "+z"), length=a(4), width=a(4), height=a(10),
                    place={"x": {"offset": a(12)}})  # fmt: skip
        self.assertEqual(len(issues(layout_of(PLATE, slot, post))), 1)

    def test_a_pocket_floor_with_the_bore_through_it(self) -> None:
        tube = item(
            "t",
            "tube",
            outer_diameter=a(40),
            inner_diameter=a(20),
            length=a(30),
            axis=pick("z"),
        )
        pocket = item(
            "k",
            "pocket",
            on=on("t", "+end"),
            shape=pick("rectangle"),
            length=a(25),
            width=a(25),
            depth=a(5),
        )
        post = item(
            "p", "post", on=on("k", "bottom"), length=a(4), width=a(4), height=a(3)
        )
        self.assertIn(("unable", "k's floor has the bore through it: Forge doesn't place on that yet"),
                      issues(layout_of(tube, pocket, post)))  # fmt: skip


class PlacesFromAnEdge(unittest.TestCase):
    def row(self, **x_place: Any) -> list[float]:
        holes = hole("plate", "+z", 4, place={"x": x_place, "pattern": {"row": {"axis": pick("x"), "pitch": a(10),
                                                                           "count": n(3)}}})  # fmt: skip
        return [round(i.origin[0], 6) for i in layout_of(PLATE, holes).instances["h"]]

    def test_a_row_to_its_nearest_copy(self) -> None:
        self.assertEqual(self.row(**at("-x", 5)), [-30.0, -20.0, -10.0])
        self.assertEqual(self.row(**at("-x", 5, "edge")), [-28.0, -18.0, -8.0])
        self.assertEqual(self.row(**at("+x", 5)), [10.0, 20.0, 30.0])
        self.assertEqual(self.row(offset=a(3)), [-7.0, 3.0, 13.0])

    def test_a_circle_by_its_centre_only(self) -> None:
        circle = {"circle": {"count": n(4), "diameter": a(10)}}
        layout = layout_of(
            PLATE, hole("plate", "+z", 2, place={"x": at("-x", 15), "pattern": circle})
        )
        self.assertAlmostEqual(
            min(i.origin[0] for i in layout.instances["h"]), -35 + 15 - 5
        )
        layout = layout_of(
            PLATE,
            hole(
                "plate", "+z", 2, place={"x": at("-x", 15, "edge"), "pattern": circle}
            ),
        )
        self.assertEqual(issues(layout)[0][0], "fault")
        self.assertIn("placed by its centre", issues(layout)[0][1])

    def test_said_and_drawn_as_measured(self) -> None:
        brief = number_words("A part.")
        raw = draft("t", [x("block", "plate", length=g(70), width=g(50), height=g(4)),
                          x("hole", "h", on={"item": "plate", "face": "+z"}, diameter=g(4), depth=g(2),
                            place={"x": {"side": "-x", "distance": g(5), "to": "centre"},
                                   "pattern": {"row": {"axis": choice("x"), "pitch": g(10),
                                                       "count": {"count": 3, "from": {"assumed": "t"}}}}})])  # fmt: skip
        report = check_draft(brief, raw)
        self.assertIn(
            "5 mm (assumed) from the -x edge to the nearest one's centre",
            " ".join(render(report, brief).lines),
        )
        (line,) = [
            d
            for v in render_views(report).views
            for d in v.dimensions
            if d.fields == ("place.x",)
        ]
        self.assertEqual(line.measured, 5.0)

    def test_an_unsaid_to_is_the_centre_assumed(self) -> None:
        raw = draft("t", [x("block", "plate", length=g(70), width=g(50), height=g(4)),
                          x("hole", "h", on={"item": "plate", "face": "+z"}, diameter=g(4), depth=g(2),
                            place={"x": {"side": "-x", "distance": g(5)}, "y": {"centred": {"assumed": "t"}}})])  # fmt: skip
        spec, _ = read_draft(raw)
        assert spec is not None
        layout = solve(spec)
        self.assertEqual(layout.instances["h"][0].origin[0], -30.0)
        self.assertIn("h: measured from the -x edge to its centre, along x; the brief doesn't say to its centre or "
                      "its near edge", [s.message for s in layout.assumptions])  # fmt: skip
        self.assertNotIn(
            "to", to_wire(spec)["items"][1]["place"]["x"]
        )  # written back as it was given


class RoundSides(unittest.TestCase):
    ROD = item("c", "cylinder", diameter=a(20), length=a(40), axis=pick("z"))
    TUBE = item(
        "c",
        "tube",
        outer_diameter=a(40),
        inner_diameter=a(20),
        length=a(40),
        axis=pick("z"),
    )

    def test_a_wide_hole_breaks_out_of_a_rod_at_its_edge(self) -> None:
        radial = {"z": {"centred": {"assumed": "t"}}, "angle": a(0, "deg")}
        # 10 + sqrt(10^2 - 8^2) = 16 mm across at the hole's edge.
        self.assertIn("deep in 16 mm of material",
                      issues(layout_of(self.ROD, hole("c", "side", 16, depth=a(19), place=radial)))[0][1])  # fmt: skip
        self.assertEqual(
            issues(
                layout_of(self.ROD, hole("c", "side", 16, depth=a(15), place=radial))
            ),
            [],
        )

    def test_a_hole_as_wide_as_the_bore(self) -> None:
        radial = {"z": {"centred": {"assumed": "t"}}, "angle": a(0, "deg")}
        found = issues(layout_of(self.TUBE, hole("c", "side", 20, place=radial)))
        self.assertTrue(any("as wide as the bore of c" in m for _, m in found), found)
        self.assertEqual(
            issues(layout_of(self.TUBE, hole("c", "side", 10, place=radial))), []
        )

    def test_through_a_tube_s_wall_until_in_the_bore_all_across(self) -> None:
        layout = layout_of(
            self.TUBE, hole("c", "side", 10, place={"angle": a(0, "deg")})
        )
        side = faces(layout, ("c", 0))["side"]
        assert isinstance(side, SideFace)
        self.assertAlmostEqual(
            side_most_material(side, 5.0), 20 - (10**2 - 5**2) ** 0.5
        )


class Letters(unittest.TestCase):
    def lettered(self, text: str, height: float = 8, mode: str = "engrave", depth: float = 1,
                 plate: float = 4) -> list[tuple[str, str]]:  # fmt: skip
        return problems(x("block", "plate", length=g(60), width=g(40), height=g(plate)),
                        x("text", "t", on={"item": "plate", "face": "+z"},
                          text={"text": text, "from": {"assumed": "t"}}, height=g(height), depth=g(depth),
                          mode=choice(mode), place={"x": {"centred": {"assumed": "t"}}, "y": {"centred": {"assumed": "t"}}}))  # fmt: skip

    def test_their_real_width_decides_whether_they_fit(self) -> None:
        self.assertTrue(
            any("larger than the face" in m for _, m in self.lettered("SERIAL 42"))
        )
        self.assertEqual(self.lettered("SN 42"), [])

    def test_a_letter_the_font_lacks_and_a_line_break(self) -> None:
        self.assertIn(
            ("unable", "Forge's font (DejaVu Sans Bold) has no '中', for now"),
            self.lettered("A中"),
        )
        self.assertIn(
            ("fault", "the text must be plain printable text"), self.lettered("A\nB")
        )

    def test_embossed_letters_never_sever_the_part(self) -> None:
        found = self.lettered("ABCDEFG", height=5, mode="emboss", depth=2, plate=2)
        self.assertFalse(
            any(k == "cant" or "cut the part in two" in m for k, m in found), found
        )

    def test_compared_by_the_way_they_read(self) -> None:
        def lettered(face: str, offset: float | None = None) -> list[dict[str, Any]]:
            place = (
                {"x": {"offset": given(offset)}, "y": c5()}
                if offset is not None
                else {"x": c5(), "y": c5()}
            )
            return [slab(), thing("t", "text", on={"item": "plate", "face": face}, place=place, mode=chose5("engrave"),
                                  text={"text": "FORGE", "from": {"assumed": "t"}}, height=given(5), depth=given(0.5))]  # fmt: skip

        self.assertEqual(
            compared(lettered("+z"), lettered("-z")), []
        )  # the same part, turned over
        self.assertEqual(compared(lettered("+z", 10), lettered("-z", -10)), [])
        self.assertNotEqual(compared(lettered("+z", 10), lettered("-z", 10)), [])


class Outlines(unittest.TestCase):
    def outline(self, *segments: dict[str, Any], kind: str = "extrusion") -> list[str]:
        profile = {
            "start": [0, 0],
            "segments": list(segments),
            "from": {"assumed": "t"},
        }
        fields: dict[str, Any] = {"profile": profile, "axis": pick("z")}
        if kind == "extrusion":
            fields["length"] = a(5)
        return [
            p.message
            for p in read_draft(draft("t", [item("e", kind, **fields)]))[1].faults
        ]

    def test_an_arc_ends_on_its_circle(self) -> None:
        self.assertIn("an arc ends on its circle: its end is not as far from its centre as its start is",
                      self.outline({"line_to": [10, 0]}, {"arc_to": [0, 6], "centre": [5, 0]}, {"line_to": [0, 0]}))  # fmt: skip

    def test_an_arc_is_the_circle_through_both_its_ends(self) -> None:
        # Its end written to three places, 0.0002 mm off its circle: the centre is read on the line square to
        # the chord through its middle, nearest the one written, so both ends are on the circle read.
        written = {"start": [10, 0], "segments": [{"arc_to": [7.071, 7.071], "centre": [0, 0]}, {"line_to": [0, 0]},
                                                  {"line_to": [10, 0]}], "from": {"assumed": "t"}}  # fmt: skip
        spec, found = read_draft(
            draft(
                "t",
                [item("e", "extrusion", profile=written, length=a(5), axis=pick("z"))],
            )
        )
        assert spec is not None and not found.faults
        profile = spec.items[0].get("profile")
        assert isinstance(profile, Profile)
        centre = profile.segments[0].centre
        assert centre is not None
        self.assertAlmostEqual(
            math.dist((10, 0), centre), math.dist((7.071, 7.071), centre), places=12
        )
        self.assertLess(math.dist(centre, (0, 0)), 0.001)
        self.assertNotEqual(centre, (0.0, 0.0))
        # Read back from its wire form, the same centre: the reading moves a centre no further once read.
        again, _ = read_draft(to_wire(spec))
        assert again is not None
        self.assertEqual(again.items[0].get("profile"), profile)

    def test_never_turning_straight_back(self) -> None:
        # A line to (12, 6), then an arc leaving it back the way it came (clockwise from below its centre):
        # the outline meets itself at no angle there.
        cusp = ({"line_to": [12, 0]}, {"arc_to": [14, 2], "centre": [12, 2], "clockwise": True},
                {"line_to": [14, 6]}, {"line_to": [0, 6]}, {"line_to": [0, 0]})  # fmt: skip
        self.assertIn("an outline doesn't touch itself: it turns straight back where this segment starts",
                      self.outline(*cusp))  # fmt: skip
        smooth = ({"line_to": [12, 0]}, {"arc_to": [14, 2], "centre": [12, 2]}, {"line_to": [14, 6]},
                  {"line_to": [0, 6]}, {"line_to": [0, 0]})  # fmt: skip
        self.assertEqual(self.outline(*smooth), [])

    def test_never_crossing_or_touching_itself(self) -> None:
        bow_tie = (
            {"line_to": [10, 10]},
            {"line_to": [10, 0]},
            {"line_to": [0, 10]},
            {"line_to": [0, 0]},
        )
        self.assertIn(
            "an outline doesn't cross or touch itself: this segment meets another one",
            self.outline(*bow_tie),
        )
        # A half-circle bowed into a 10 by 5 rectangle reaches its bottom edge.
        dipped = ({"line_to": [10, 0]}, {"line_to": [10, 5]}, {"arc_to": [0, 5], "centre": [5, 5], "clockwise": True},
                  {"line_to": [0, 0]})  # fmt: skip
        self.assertTrue(self.outline(*dipped))
        bowed = (
            {"line_to": [10, 0]},
            {"line_to": [10, 5]},
            {"arc_to": [0, 5], "centre": [5, 5]},
            {"line_to": [0, 0]},
        )
        self.assertEqual(self.outline(*bowed), [])

    def test_a_revolution_never_crosses_its_axis(self) -> None:
        found = problems(x("revolution", "r", axis=choice("z"),
                           profile={"start": [0, 0], "from": {"assumed": "t"},
                                    "segments": [{"line_to": [5, 0]}, {"line_to": [5, 10]}, {"line_to": [-2, 10]},
                                                 {"line_to": [0, 0]}]}))  # fmt: skip
        self.assertTrue(any("never below 0" in m for _, m in found), found)

    def test_where_an_outline_runs_on_smoothly_there_is_no_edge_to_round(self) -> None:
        def rounded(
            kind: str,
            which: str,
            *segments: dict[str, Any],
            start: tuple[float, float] = (0, 0),
        ) -> list[str]:
            fields: dict[str, Any] = {"length": g(5)} if kind == "extrusion" else {}
            body = x(kind, "k", axis=choice("z"), profile={"start": list(start), "from": {"assumed": "t"},
                                                         "segments": list(segments)}, **fields)  # fmt: skip
            found = problems(
                body, x("fillet", "f", edges={"of": "k", "which": which}, radius=g(0.5))
            )
            return [m for _, m in found if "edge" in m or "rim" in m]

        # A knob: its rounded rim runs on smoothly into its top; its stem meets its foot at a corner.
        knob = ({"line_to": [4, 0]}, {"line_to": [4, 2]}, {"arc_to": [2, 4], "centre": [2, 2]}, {"line_to": [0, 4]},
                {"line_to": [0, 0]})  # fmt: skip
        self.assertEqual(rounded("revolution", "top", *knob),
                         ["k's side runs on smoothly into its +end: where they meet is no edge to round"])  # fmt: skip
        self.assertEqual(rounded("revolution", "bottom", *knob), [])
        # A ring whose outside runs on smoothly into its top: its bore's rim is still an edge.
        ring = ({"line_to": [6, 0]}, {"line_to": [6, 2]}, {"arc_to": [4, 4], "centre": [4, 2]}, {"line_to": [1, 4]},
                {"line_to": [1, 0]})  # fmt: skip
        self.assertEqual(rounded("revolution", "top", *ring, start=(1, 0)), [])
        # A pointed top has no flat end at all.
        cone = ({"line_to": [4, 0]}, {"line_to": [0, 4]}, {"line_to": [0, 0]})
        self.assertEqual(
            rounded("revolution", "top", *cone),
            ["k has no flat +end, so no rim there to round"],
        )
        # A slot's outline, round at both ends: no corners along its length; an L has six.
        slot = ({"line_to": [10, 0]}, {"arc_to": [10, 4], "centre": [10, 2]}, {"line_to": [0, 4]},
                {"arc_to": [0, 0], "centre": [0, 2]})  # fmt: skip
        self.assertEqual(rounded("extrusion", "vertical", *slot),
                         ["k's outline runs on smoothly all round, with no corners: it has no edges along its length "
                          "to round"])  # fmt: skip
        self.assertEqual(rounded("extrusion", "top", *slot), [])
        angle = ({"line_to": [10, 0]}, {"line_to": [10, 3]}, {"line_to": [3, 3]}, {"line_to": [3, 10]},
                 {"line_to": [0, 10]}, {"line_to": [0, 0]})  # fmt: skip
        self.assertEqual(rounded("extrusion", "vertical", *angle), [])


if __name__ == "__main__":
    unittest.main()
