"""The judge's own placement (forge_checks.place), from the written definitions.

Three kinds of test:

- **worked examples:** every number expected here was worked out by hand from
  docs/definitions (frame.md, place.md and the kinds' pages), not from either
  program: first bodies, positions and patterns, round sides, concentric
  copies, hollows, pocket floors, the material under faces and how deep
  ``through`` goes, the order the part is made in, and what isn't placed;
- **brute force:** the most and least material under a mouth against the
  material at points sampled across it;
- **the two placements against each other:** random specs the solver
  accepts, placed by both, with no difference allowed (and every layout
  any other test makes is compared too: tests/conftest.py).
"""

from __future__ import annotations

import math
import random
import re
import sys
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

from forge_checks.outlines import Outline, Segment
from forge_checks.place import (
    FLAT_AXES,
    TURN_AXES,
    Dome,
    FlatFace,
    Less,
    Material,
    Over,
    Placed,
    PlaceError,
    RoundBall,
    RoundCone,
    RoundSide,
    Solid,
    Taper,
    Turned,
    compare_layouts,
    least,
    material_at,
    most,
    place,
    turn,
)
from forge_spec.draft import On, Place
from forge_spec.placement import solve

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v2_layouts  # every layout any test makes is compared, under any runner
from v2_specs import SAY, WORDS, a, n, pick, random_specs, read

DEFINITIONS = Path(__file__).resolve().parent.parent / "docs" / "definitions"


def item(item_id: str, kind: str, **fields: Any) -> dict[str, Any]:
    return {"id": item_id, "kind": kind, "words": WORDS, **fields}


def on(host: str, face: str) -> dict[str, str]:
    return {"item": host, "face": face}


def through() -> dict[str, Any]:
    return {"through": True, "from": SAY}


def side(direction: str, distance: float, to: str | None = None) -> dict[str, Any]:
    found: dict[str, Any] = {"side": direction, "distance": a(distance)}
    if to is not None:
        found["to"] = to
    return found


def placed(*items: dict[str, Any]) -> Placed:
    return place(read(list(items)))


def points(p: Placed, item_id: str) -> list[tuple[float, ...]]:
    return [tuple(round(v, 9) + 0.0 for v in c.point) for c in p.copies[item_id]]


def flat(p: Placed, item_id: str, face: str, index: int = 0) -> FlatFace:
    found = p.faces[(item_id, index)][face]
    assert isinstance(found, FlatFace)
    return found


def round_side(p: Placed, item_id: str, face: str, index: int = 0) -> RoundSide:
    found = p.faces[(item_id, index)][face]
    assert isinstance(found, RoundSide)
    return found


PLATE = item("plate", "block", length=a(80), width=a(50), height=a(5))
ROD = item("rod", "cylinder", diameter=a(20), length=a(40))


def hole(host: str, face: str, d: float, **fields: Any) -> dict[str, Any]:
    return item(fields.pop("id", "h"), "hole", on=on(host, face), diameter=a(d), depth=fields.pop("depth", through()), **fields)  # fmt: skip


class TheFrameTablesAreTheDefinitions(unittest.TestCase):
    """The placement's own copies of the tables in frame.md and place.md."""

    def table(self, page: str, heading: str) -> list[list[str]]:
        """The rows of the table whose heading row is ``heading``, the heading first."""
        text = (DEFINITIONS / page).read_text(encoding="utf-8")
        found = []
        for line in text[text.index(heading) :].splitlines():
            if not line.strip().startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not set(cells[0]) <= {"-", " "}:
                found.append(cells)
        return found

    def test_a_flat_face_s_axes(self) -> None:
        rows = self.table("frame.md", "| face | first axis | second axis |")[1:]
        self.assertEqual(len(rows), 3)
        for faces, first, second in rows:
            for name in re.findall(r"[+-][xyz]", faces):
                self.assertEqual(FLAT_AXES[name[1]], (first, second), name)

    def test_the_angle_round_a_side(self) -> None:
        rows = self.table("place.md", "| side's axis | 0 degrees | 90 degrees |")[1:]
        self.assertEqual(len(rows), 3)
        for axis, zero, quarter in rows:
            self.assertEqual(TURN_AXES[axis], (zero[1], quarter[1]), axis)


class Turns(unittest.TestCase):
    def test_quarter_turns_are_exact(self) -> None:
        for k in range(-12, 13):
            c, s = turn(90.0 * k)
            self.assertIn((c, s), [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)])
            self.assertEqual(
                (c, s), ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[k % 4]
            )

    def test_other_angles_are_accurate(self) -> None:
        rng = random.Random(1)
        for _ in range(2000):
            d = rng.uniform(-1000, 1000)
            c, s = turn(d)
            self.assertAlmostEqual(
                c, math.cos(math.radians(d)), delta=4e-16 * max(1, abs(d) / 90)
            )
            self.assertAlmostEqual(
                s, math.sin(math.radians(d)), delta=4e-16 * max(1, abs(d) / 90)
            )
        self.assertEqual(
            turn(90 + 1e-10), (0.0, 1.0)
        )  # within QUARTER_SNAP of a quarter turn
        with self.assertRaises(ValueError):
            turn(math.inf)


class FirstBodies(unittest.TestCase):
    """frame.md, "The frame"."""

    def test_a_block_has_its_bottom_face_centred_on_the_origin(self) -> None:
        p = placed(PLATE)
        (copy,) = p.copies["plate"]
        self.assertEqual(
            (copy.point, copy.direction), ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        )
        self.assertEqual((copy.lo, copy.hi), ((-40.0, -25.0, 0.0), (40.0, 25.0, 5.0)))
        top = flat(p, "plate", "+z")
        self.assertEqual(
            (top.centre, top.normal, top.axes, top.half),
            ((0.0, 0.0, 5.0), "+z", ("x", "y"), (40.0, 25.0)),
        )
        self.assertEqual(top.material, Solid(5.0))
        end = flat(p, "plate", "-x")
        self.assertEqual(
            (end.centre, end.axes, end.half, end.material),
            ((-40.0, 0.0, 2.5), ("y", "z"), (25.0, 2.5), Solid(80.0)),
        )
        self.assertEqual(
            set(p.faces[("plate", 0)]), {"+x", "-x", "+y", "-y", "+z", "-z"}
        )
        self.assertTrue(
            all(name.startswith("inner ") for name in p.closed[("plate", 0)])
        )

    def test_a_rod_along_x_starts_at_the_origin(self) -> None:
        p = placed(
            item("rod", "cylinder", diameter=a(20), length=a(30), axis=pick("x"))
        )
        (copy,) = p.copies["rod"]
        self.assertEqual(
            (copy.direction, copy.lo, copy.hi),
            ((1.0, 0.0, 0.0), (0.0, -10.0, -10.0), (30.0, 10.0, 10.0)),
        )
        end = flat(p, "rod", "+end")
        self.assertEqual(
            (end.centre, end.normal, end.axes, end.outline.shape, end.half),
            ((30.0, 0.0, 0.0), "+x", ("y", "z"), "disc", (10.0, 10.0)),
        )
        side_ = round_side(p, "rod", "side")
        self.assertEqual(
            (side_.axis, side_.start, side_.length, side_.radius, side_.outward),
            ("x", (0.0, 0.0, 0.0), 30.0, 10.0, True),
        )
        self.assertEqual(side_.material, 20.0)

    def test_a_cone_to_a_point_has_no_top_and_tapers_under_its_base(self) -> None:
        p = placed(
            item("cone", "cone", base_diameter=a(40), top_diameter=a(0), length=a(30))
        )
        self.assertIn("+end", p.closed[("cone", 0)])
        side = p.faces[("cone", 0)]["side"]  # its tapered side takes things (item 3b's third step)
        assert isinstance(side, RoundCone)
        self.assertEqual((side.axis, side.start, side.length, side.start_radius, side.end_radius, side.joined),
                         ("z", (0.0, 0.0, 0.0), 30.0, 20.0, 0.0, None))  # fmt: skip
        base = flat(p, "cone", "-end")
        self.assertEqual(base.normal, "-z")
        self.assertEqual(material_at(base.material, (0, 0)), 30.0)
        self.assertAlmostEqual(material_at(base.material, (10, 0)), 15.0, places=12)
        self.assertEqual(material_at(base.material, (20, 0)), 0.0)

    def test_a_ball_rests_on_the_origin_and_a_dome_stands_on_it(self) -> None:
        ball = placed(item("ball", "sphere", diameter=a(20), portion=pick("whole")))
        (copy,) = ball.copies["ball"]
        self.assertEqual((copy.lo, copy.hi), ((-10.0, -10.0, 0.0), (10.0, 10.0, 20.0)))
        (surface,) = ball.faces[("ball", 0)].values()  # its curved surface takes things (item 3b's second step)
        assert isinstance(surface, RoundBall)
        self.assertEqual((surface.centre, surface.up, surface.radius, surface.dome), ((0.0, 0.0, 10.0), "+z", 10.0, False))
        dome = placed(
            item("dome", "sphere", diameter=a(20), portion=pick("upper_half"))
        )
        flat_face = flat(dome, "dome", "-end")
        self.assertEqual((flat_face.normal, flat_face.outline.radius), ("-z", 10.0))
        self.assertAlmostEqual(material_at(flat_face.material, (6, 0)), 8.0, places=12)


class PositionsOnAFlatFace(unittest.TestCase):
    """place.md, "On a flat face" and "Patterns", on an 80 x 50 mm plate's top."""

    def at(self, d: float = 6.0, **place_: Any) -> list[tuple[float, ...]]:
        return points(placed(PLATE, hole("plate", "+z", d, place=place_)), "h")

    def test_from_a_side_to_the_centre_or_the_near_edge(self) -> None:
        self.assertEqual(self.at(x=side("-x", 10)), [(-30.0, 0.0, 5.0)])
        self.assertEqual(self.at(x=side("-x", 10, "edge")), [(-27.0, 0.0, 5.0)])
        self.assertEqual(self.at(y=side("+y", 8, "edge")), [(0.0, 14.0, 5.0)])
        self.assertEqual(
            self.at(x={"offset": a(-5)}, y={"centred": SAY}), [(-5.0, 0.0, 5.0)]
        )

    def test_corners(self) -> None:
        got = self.at(pattern={"corners": {"inset_x": a(6), "inset_y": a(5)}})
        self.assertEqual(
            got,
            [
                (-34.0, -20.0, 5.0),
                (-34.0, 20.0, 5.0),
                (34.0, -20.0, 5.0),
                (34.0, 20.0, 5.0),
            ],
        )

    def test_a_rectangle_measured_from_an_edge_to_its_nearest_copy(self) -> None:
        got = self.at(x=side("-x", 5), pattern={"rectangle": {"x": a(56), "y": a(36)}})
        self.assertEqual(
            got,
            [
                (-35.0, -18.0, 5.0),
                (-35.0, 18.0, 5.0),
                (21.0, -18.0, 5.0),
                (21.0, 18.0, 5.0),
            ],
        )

    def test_ends_and_a_row(self) -> None:
        self.assertEqual(self.at(y={"offset": a(3)}, pattern={"ends": {"axis": pick("x"), "inset": a(8)}}),
                         [(-32.0, 3.0, 5.0), (32.0, 3.0, 5.0)])  # fmt: skip
        got = self.at(
            x=side("+x", 4, "edge"),
            pattern={"row": {"axis": pick("x"), "count": n(4), "pitch": a(10)}},
        )
        self.assertEqual(
            got, [(3.0, 0.0, 5.0), (13.0, 0.0, 5.0), (23.0, 0.0, 5.0), (33.0, 0.0, 5.0)]
        )

    def test_a_grid_runs_along_its_second_axis_for_each_step_along_its_first(
        self,
    ) -> None:
        got = self.at(
            d=2,
            pattern={
                "grid": {
                    "count_x": n(2),
                    "count_y": n(3),
                    "pitch_x": a(20),
                    "pitch_y": a(10),
                }
            },
        )
        self.assertEqual(
            [c[:2] for c in got],
            [
                (-10.0, -10.0),
                (-10.0, 0.0),
                (-10.0, 10.0),
                (10.0, -10.0),
                (10.0, 0.0),
                (10.0, 10.0),
            ],
        )

    def test_circles_and_arcs(self) -> None:
        circle = {"count": n(4), "diameter": a(30), "start": a(45, "deg")}
        p = placed(PLATE, hole("plate", "+z", 2, place={"pattern": {"circle": circle}}))
        r = 15 * math.sqrt(0.5)
        for copy, (sx, sy) in zip(
            p.copies["h"], [(1, 1), (-1, 1), (-1, -1), (1, -1)], strict=True
        ):
            found = copy.point
            self.assertAlmostEqual(found[0], sx * r, places=12)
            self.assertAlmostEqual(found[1], sy * r, places=12)
        got = self.at(
            d=2,
            x=side("-x", 20),
            pattern={"arc": {"count": n(3), "diameter": a(20), "step": a(90, "deg")}},
        )
        self.assertEqual(
            [c[:2] for c in got], [(-10.0, 0.0), (-20.0, 10.0), (-30.0, 0.0)]
        )
        with self.assertRaises(PlaceError):
            self.at(
                x=side("-x", 20, "edge"),
                pattern={"circle": {"count": n(3), "diameter": a(20)}},
            )

    def test_what_a_flat_face_doesn_t_take(self) -> None:
        for bad in (
            {"z": side("-z", 1)},  # an axis the face doesn't have
            {"angle": a(30, "deg")},
            {
                "x": side("-x", 5),
                "pattern": {"corners": {"inset_x": a(5), "inset_y": a(5)}},
            },
            {
                "pattern": {
                    "grid": {
                        "count_x": n(2),
                        "count_z": n(2),
                        "pitch_x": a(5),
                        "pitch_z": a(5),
                    }
                }
            },
            {"pattern": {"row": {"axis": pick("z"), "count": n(2), "pitch": a(5)}}},
            {
                "pattern": {
                    "row": {
                        "axis": pick("x"),
                        "count": n(2),
                        "pitch": a(5),
                        "each": n(2),
                    }
                }
            },
        ):
            with self.assertRaises(PlaceError, msg=str(bad)):
                self.at(**bad)


class RoundSides(unittest.TestCase):
    """place.md, "On a round side", and hole.md's depths through it."""

    def test_a_hole_through_a_rod(self) -> None:
        p = placed(
            ROD,
            hole("rod", "side", 4, place={"angle": a(90, "deg"), "z": side("+z", 5)}),
        )
        (copy,) = p.copies["h"]
        self.assertEqual(
            (copy.point, copy.direction, copy.axes),
            ((0.0, 10.0, 35.0), (0.0, 1.0, 0.0), None),
        )
        self.assertEqual(
            copy.span, (0.0, 20.0)
        )  # in, across the axis, out of the far side

    def test_through_a_tube_s_wall_and_out_through_it_from_the_bore(self) -> None:
        tube = item(
            "tube",
            "tube",
            outer_diameter=a(30),
            inner_diameter=a(20),
            length=a(40),
            axis=pick("y"),
        )
        p = placed(tube, hole("tube", "side", 6))
        (copy,) = p.copies["h"]
        self.assertEqual(copy.point, (0.0, 20.0, 15.0))  # 0 degrees round y is +z
        assert copy.span is not None
        self.assertAlmostEqual(
            copy.span[1], 15 - math.sqrt(100 - 9), places=12
        )  # into the bore all across its mouth
        p = placed(tube, hole("tube", "bore", 6, place={"angle": a(90, "deg")}))
        (copy,) = p.copies["h"]
        self.assertEqual(
            (copy.point, copy.direction), ((10.0, 20.0, 0.0), (-1.0, 0.0, 0.0))
        )
        self.assertEqual(
            copy.span, (-10.0, 5.0)
        )  # from the side's axis, out through the wall

    def test_a_post_round_a_rod(self) -> None:
        post = item(
            "p", "post", on=on("rod", "side"), length=a(6), width=a(4), height=a(5)
        )
        p = placed(ROD, post)
        (copy,) = p.copies["p"]
        self.assertEqual(
            (copy.point, copy.direction, copy.axes),
            ((10.0, 0.0, 20.0), (1.0, 0.0, 0.0), ("y", "z")),
        )
        foot = 10 - math.sqrt(100 - 9)
        self.assertAlmostEqual(copy.foot, foot, places=12)
        assert copy.lo is not None and copy.hi is not None
        self.assertAlmostEqual(copy.lo[0], 10 - foot, places=12)
        self.assertEqual((copy.lo[1:], copy.hi), ((-3.0, 18.0), (15.0, 3.0, 22.0)))
        self.assertEqual(
            set(p.faces[("p", 0)]), {"+x"}
        )  # only its far face takes anything
        top = flat(p, "p", "+x")
        self.assertEqual(
            (top.centre, top.axes, top.half, top.material),
            ((15.0, 0.0, 20.0), ("y", "z"), (3.0, 2.0), Solid(25.0)),
        )

    def test_a_boss_in_a_bore_stands_towards_the_axis(self) -> None:
        tube = item(
            "tube",
            "tube",
            outer_diameter=a(30),
            inner_diameter=a(20),
            length=a(40),
            axis=pick("y"),
        )
        p = placed(
            tube, item("b", "boss", on=on("tube", "bore"), diameter=a(4), height=a(3))
        )
        (copy,) = p.copies["b"]
        self.assertEqual(
            (copy.point, copy.direction, copy.foot),
            ((0.0, 20.0, 10.0), (0.0, 0.0, -1.0), 0.0),
        )
        top = flat(p, "b", "+end")
        self.assertEqual(
            (top.centre, top.normal, top.axes, top.material),
            ((0.0, 20.0, 7.0), "-z", ("x", "y"), Solid(8.0)),
        )

    def test_a_circle_of_copies_round_a_side(self) -> None:
        p = placed(
            ROD,
            hole(
                "rod",
                "side",
                3,
                place={"angle": a(30, "deg"), "pattern": {"circle": {"count": n(3)}}},
            ),
        )
        for copy, angle in zip(p.copies["h"], (30, 150, 270), strict=True):
            self.assertAlmostEqual(
                copy.point[0], 10 * math.cos(math.radians(angle)), places=12
            )
            self.assertAlmostEqual(
                copy.point[1], 10 * math.sin(math.radians(angle)), places=12
            )
        with self.assertRaises(PlaceError):
            placed(
                ROD,
                hole(
                    "rod",
                    "side",
                    3,
                    place={
                        "pattern": {
                            "row": {"axis": pick("z"), "count": n(2), "pitch": a(5)}
                        }
                    },
                ),
            )
        # A standing feature at an angle that isn't a frame axis's (item 3b's first step): placed as at the one at or
        # below it, then turned with the side about its axis by the rest.
        (boss,) = placed(ROD, item("b", "boss", on=on("rod", "side"), diameter=a(3), height=a(2),
                                   place={"angle": a(45, "deg")})).copies["b"]  # fmt: skip
        for got, want in zip(boss.direction, (math.sqrt(0.5), math.sqrt(0.5), 0.0), strict=True):
            self.assertAlmostEqual(got, want, places=12)
        assert boss.local is not None and boss.frame is not None
        self.assertEqual(boss.local.direction, (1.0, 0.0, 0.0))


class Concentric(unittest.TestCase):
    """place.md, "Concentric": which copy goes with which."""

    BOSSES = item("b", "boss", on=on("plate", "+z"), diameter=a(10), height=a(5),
                  place={"pattern": {"rectangle": {"x": a(40), "y": a(30)}}})  # fmt: skip

    def test_one_host_copy_takes_one_on_the_axis_of_every_partner(self) -> None:
        under = hole("plate", "-z", 3, place={"concentric": {"item": "b", "from": SAY}})
        got = points(placed(PLATE, self.BOSSES, under), "h")
        self.assertEqual(
            got,
            [
                (-20.0, -15.0, 0.0),
                (-20.0, 15.0, 0.0),
                (20.0, -15.0, 0.0),
                (20.0, 15.0, 0.0),
            ],
        )

    def test_concentric_with_the_item_it_is_on(self) -> None:
        bore = hole("b", "+end", 3, place={"concentric": {"item": "b", "from": SAY}})
        got = points(placed(PLATE, self.BOSSES, bore), "h")
        self.assertEqual(
            got,
            [
                (-20.0, -15.0, 10.0),
                (-20.0, 15.0, 10.0),
                (20.0, -15.0, 10.0),
                (20.0, 15.0, 10.0),
            ],
        )

    def test_one_partner_on_each_host_copy_and_copy_n_with_copy_n(self) -> None:
        # Two bosses round a rod, either side; a hole across the rod between them: each boss's top
        # takes a hole on that one hole's axis.
        across = hole("rod", "side", 4, id="x")
        bosses = item("b", "boss", on=on("rod", "side"), diameter=a(6), height=a(3),
                      place={"pattern": {"circle": {"count": n(2)}}})  # fmt: skip
        on_each = hole("b", "+end", 2, place={"concentric": {"item": "x", "from": SAY}})
        got = points(placed(ROD, across, bosses, on_each), "h")
        self.assertEqual(got, [(13.0, 0.0, 20.0), (-13.0, 0.0, 20.0)])
        under = item("u", "boss", on=on("plate", "-z"), diameter=a(4), height=a(2),
                     place={"pattern": {"rectangle": {"x": a(40), "y": a(30)}}})  # fmt: skip
        paired = hole("u", "+end", 2, place={"concentric": {"item": "b", "from": SAY}})
        got = points(placed(PLATE, self.BOSSES, under, paired), "h")
        self.assertEqual(
            [g[:2] for g in got],
            [(-20.0, -15.0), (-20.0, 15.0), (20.0, -15.0), (20.0, 15.0)],
        )

    def test_what_concentric_can_t_be(self) -> None:
        three = item("t", "boss", on=on("plate", "-z"), diameter=a(4), height=a(2),
                     place={"pattern": {"row": {"axis": pick("x"), "count": n(3), "pitch": a(10)}}})  # fmt: skip
        mismatched = hole(
            "b", "+end", 2, place={"concentric": {"item": "t", "from": SAY}}
        )
        with self.assertRaises(PlaceError):
            placed(PLATE, self.BOSSES, three, mismatched)
        with self.assertRaises(
            PlaceError
        ):  # concentric fixes the position: no pattern with it
            placed(PLATE, self.BOSSES, hole("plate", "-z", 2, place={"concentric": {"item": "b", "from": SAY},
                                                                     "pattern": {"circle": {"count": n(2), "diameter": a(5)}}}))  # fmt: skip
        side_hole = hole("rod", "side", 2, place={"angle": a(30, "deg")})
        with self.assertRaises(
            PlaceError
        ):  # its axis isn't at right angles to the face
            placed(
                ROD,
                side_hole,
                hole(
                    "rod",
                    "+end",
                    2,
                    id="g",
                    place={"concentric": {"item": "h", "from": SAY}},
                ),
            )


class Hollows(unittest.TestCase):
    """shell.md: walls, floors, open faces and inner faces."""

    def test_a_tray(self) -> None:
        box = item("box", "block", length=a(100), width=a(60), height=a(30))
        shell = item(
            "s",
            "shell",
            of="box",
            thickness=a(2),
            open={"faces": ["+z"], "from": SAY},
            floor=a(3),
        )
        p = placed(box, shell)
        hollow = p.hollows[("box", 0)]
        self.assertEqual(
            (hollow.lo, hollow.hi), ((-48.0, -28.0, 3.0), (48.0, 28.0, 30.0))
        )
        rim = flat(p, "box", "+z")  # its rim, a frame round the hollow's mouth (shell.md, "The rim")
        self.assertEqual((rim.outline.shape, rim.outline.half), ("profile", (50.0, 30.0)))
        self.assertTrue(rim.outline.contains((49.0, 0.0)) and not rim.outline.contains((0.0, 0.0)))
        self.assertIn("inner +z", p.closed[("box", 0)])
        floor = flat(p, "box", "inner -z")
        self.assertEqual(
            (floor.centre, floor.normal, floor.half, floor.material),
            ((0.0, 0.0, 3.0), "+z", (48.0, 28.0), Solid(3.0)),
        )
        wall = flat(p, "box", "inner +x")
        self.assertEqual((wall.centre, wall.normal, wall.axes, wall.half, wall.material),
                         ((48.0, 0.0, 16.5), "-x", ("y", "z"), (28.0, 13.5), Solid(2.0)))  # fmt: skip
        self.assertEqual(
            (flat(p, "box", "-z").material, flat(p, "box", "+x").material),
            (Solid(3.0), Solid(2.0)),
        )

    def test_a_cup_and_a_hole_into_it(self) -> None:
        cup = item("cup", "cylinder", diameter=a(40), length=a(50))
        shell = item(
            "s",
            "shell",
            of="cup",
            thickness=a(3),
            open={"faces": ["+end"], "from": SAY},
        )
        p = placed(cup, shell, hole("cup", "side", 4))
        inside = round_side(p, "cup", "inner side")
        self.assertEqual(
            (inside.radius, inside.outward, inside.start, inside.length),
            (17.0, False, (0.0, 0.0, 3.0), 47.0),
        )
        floor = flat(p, "cup", "inner -end")
        self.assertEqual(
            (floor.centre, floor.normal, floor.outline.radius, floor.material),
            ((0.0, 0.0, 3.0), "+z", 17.0, Solid(3.0)),
        )
        (copy,) = p.copies["h"]
        assert copy.span is not None
        self.assertAlmostEqual(copy.span[1], 20 - math.sqrt(17**2 - 4), places=12)

    def test_a_sealed_dome(self) -> None:
        dome = item("dome", "sphere", diameter=a(40), portion=pick("upper_half"))
        p = placed(
            dome,
            item(
                "s", "shell", of="dome", thickness=a(2), open={"faces": [], "from": SAY}
            ),
        )
        self.assertEqual(flat(p, "dome", "-end").material, Solid(2.0))
        hollow = p.hollows[("dome", 0)]
        self.assertEqual(
            (hollow.lo, hollow.hi), ((-18.0, -18.0, 2.0), (18.0, 18.0, 18.0))
        )

    def test_what_a_shell_can_t_do(self) -> None:
        box = item("box", "block", length=a(10), width=a(10), height=a(10))
        for shell in (
            item(
                "s", "shell", of="box", thickness=a(5), open={"faces": [], "from": SAY}
            ),  # no room left
            item(
                "s",
                "shell",
                of="box",
                thickness=a(1),
                open={"faces": [], "from": SAY},
                floor=a(2),
            ),  # no floor
            item(
                "s",
                "shell",
                of="box",
                thickness=a(1),
                open={"faces": ["+end"], "from": SAY},
            ),
        ):
            with self.assertRaises(PlaceError, msg=str(shell)):
                placed(box, shell)


class TheMaterialUnderAFace(unittest.TestCase):
    """frame.md, "The material under a face", and how deep "through" goes."""

    def span(self, p: Placed, item_id: str = "h") -> float:
        (copy,) = p.copies[item_id]
        assert copy.span is not None
        return copy.span[1]

    def test_over_a_host_and_over_an_overhang(self) -> None:
        block = item(
            "blk",
            "block",
            on=on("plate", "+z"),
            length=a(20),
            width=a(20),
            height=a(10),
            place={"x": {"offset": a(35)}},
        )
        part = hole(
            "blk", "+z", 4, place={"x": side("+x", 2, "edge")}
        )  # x from 39 to 43: partly over the plate
        self.assertEqual(self.span(placed(PLATE, block, part)), 15.0)
        out = hole(
            "blk", "+z", 2, place={"x": side("+x", 0.5, "edge")}
        )  # x from 42.5 to 44.5: over the overhang
        self.assertEqual(self.span(placed(PLATE, block, out)), 10.0)

    def test_a_cone_s_wide_top(self) -> None:
        cone = item(
            "cone",
            "cone",
            on=on("plate", "+z"),
            base_diameter=a(20),
            top_diameter=a(40),
            length=a(30),
        )
        off = hole(
            "cone", "+end", 4, place={"x": {"offset": a(15)}}
        )  # 13 to 17 mm out: the taper only
        self.assertAlmostEqual(
            self.span(placed(PLATE, cone, off)), 30 * (20 - 13) / 10, places=12
        )
        self.assertEqual(
            self.span(placed(PLATE, cone, hole("cone", "+end", 4))), 35.0
        )  # within its smaller end

    def test_a_dome_s_flat_face(self) -> None:
        dome = item("dome", "sphere", diameter=a(40), portion=pick("upper_half"))
        h = hole("dome", "-end", 4, place={"x": {"offset": a(12)}})
        self.assertAlmostEqual(
            self.span(placed(dome, h)), math.sqrt(400 - 100), places=12
        )

    def test_a_pocket_s_floor(self) -> None:
        pocket = item(
            "pk",
            "pocket",
            on=on("plate", "+z"),
            shape=pick("rectangle"),
            length=a(20),
            width=a(10),
            depth=a(2),
        )
        p = placed(PLATE, pocket, hole("pk", "bottom", 3))
        floor = flat(p, "pk", "bottom")
        self.assertEqual(
            (floor.centre, floor.normal, floor.half),
            ((0.0, 0.0, 3.0), "+z", (10.0, 5.0)),
        )
        self.assertEqual(self.span(p), 3.0)
        for depth in (a(5), through()):  # as deep as the material, or through: no floor
            deep = dict(pocket, depth=depth)
            self.assertIn("bottom", placed(PLATE, deep).closed[("pk", 0)])
        tube = item(
            "tube", "tube", outer_diameter=a(30), inner_diameter=a(10), length=a(20)
        )
        recess = item(
            "pk",
            "pocket",
            on=on("tube", "+end"),
            shape=pick("circle"),
            diameter=a(16),
            depth=a(2),
        )
        self.assertIn(
            "bottom", placed(tube, recess).closed[("pk", 0)]
        )  # it covers the ring's opening

    def test_a_round_ended_tab(self) -> None:
        tab = item("t", "tab", on=on("plate", "+z"), length=a(10), width=a(8), thickness=a(2),
                   thickness_along=pick("y"), end=pick("round"))  # fmt: skip
        p = placed(PLATE, tab)
        end = p.faces[("t", 0)]["+z"]  # its round end: a round side over its half (item 3b's fourth step)
        assert isinstance(end, RoundSide)
        self.assertEqual((end.axis, end.start, end.length, end.radius, end.half, end.middle),
                         ("y", (0.0, -1.0, 11.0), 2.0, 4.0, "+z", 0.0))  # fmt: skip
        broad = flat(p, "t", "+y")
        self.assertEqual(
            (broad.centre, broad.half, broad.outline.corners),
            ((0.0, 1.0, 10.0), (4.0, 5.0), (4.0, 4.0, 0.0, 0.0)),
        )
        narrow = flat(p, "t", "+x")
        self.assertEqual(
            (narrow.centre, narrow.half), ((4.0, 0.0, 8.0), (1.0, 3.0))
        )  # it stops where the rounding starts
        short = dict(tab, length=a(4))
        self.assertIn("+x", placed(PLATE, short).closed[("t", 0)])  # all round end


def _random_material(rng: random.Random, depth: int = 0) -> Material:
    roll = rng.random()
    centre = (rng.uniform(-3, 3), rng.uniform(-3, 3))
    if depth > 2 or roll < 0.25:
        return Solid(rng.uniform(1, 10))
    if roll < 0.4:
        flat_, edge = rng.uniform(0, 5), rng.uniform(5.5, 12)
        return Taper(centre, flat_, edge, rng.uniform(1, 10))
    if roll < 0.5:
        return Dome(centre, rng.uniform(4, 12))
    if roll < 0.6:
        base = _random_material(rng, depth + 1)
        return Less(base, rng.uniform(0, 1))
    host = _random_material(rng, depth + 1)
    over = [
        Outline.rect(
            rng.uniform(1, 6),
            rng.uniform(1, 6),
            centre=(rng.uniform(-3, 3), rng.uniform(-3, 3)),
        )
    ]
    if rng.random() < 0.3:
        r = rng.uniform(2, 6)
        over.append(
            Outline.ring(
                r, r * rng.uniform(0.2, 0.7), (rng.uniform(-3, 3), rng.uniform(-3, 3))
            )
        )
    own: Solid | Taper | Turned = Solid(rng.uniform(1, 10))
    kind = rng.random()
    if kind < 0.3:
        small = rng.uniform(1, 4)
        own = Taper(centre, small, small + rng.uniform(1, 6), rng.uniform(1, 10))
        over.append(Outline.disc(small, centre))
    elif kind < 0.6:
        own = _random_turned(rng, centre)
    return Over(own, tuple(over), host)


def _random_turned(rng: random.Random, centre: tuple[float, float]) -> Turned:
    """The top of a stepped disc turned about ``centre``: wide at its foot, a narrower boss on it, at times a bore."""
    wide, low = rng.uniform(4, 9), rng.uniform(1, 5)
    narrow, high = wide * rng.uniform(0.3, 0.8), low + rng.uniform(1, 5)
    bore = narrow * rng.uniform(0.1, 0.6) if rng.random() < 0.4 else 0.0
    corners = [
        (bore, 0.0),
        (wide, 0.0),
        (wide, low),
        (narrow, low),
        (narrow, high),
        (bore, high),
    ]
    sides = [
        Segment(p, q) for p, q in zip(corners, [*corners[1:], corners[0]], strict=True)
    ]
    return Turned(centre, Outline.profile(sides), high, True)


class MostAndLeastAgainstBruteForce(unittest.TestCase):
    def test_random_materials_and_mouths(self) -> None:
        rng = random.Random(3)
        for _ in range(160):
            material = _random_material(rng)
            mouth = rng.choice([
                Outline.disc(rng.uniform(0.3, 4), (rng.uniform(-6, 6), rng.uniform(-6, 6))),
                Outline.rect(rng.uniform(0.3, 4), rng.uniform(0.3, 4), (rng.uniform(-6, 6), rng.uniform(-6, 6))),
                Outline.stadium(4, 2, along_first=True, centre=(rng.uniform(-6, 6), rng.uniform(-6, 6))),
            ])  # fmt: skip
            sampled = [
                (
                    mouth.centre[0] + mouth.half[0] * i / 25,
                    mouth.centre[1] + mouth.half[1] * j / 25,
                )
                for i in range(-25, 26)
                for j in range(-25, 26)
            ]
            sampled = [p for p in sampled if mouth.contains(p)]
            values = [material_at(material, p) for p in sampled]
            hi, lo = most(material, [mouth]), least(material, mouth)
            self.assertGreaterEqual(hi, max(values) - 1e-9, material)
            self.assertLessEqual(lo, min(values) + 1e-9, material)
            # Sampled 1/25 of the mouth apart: the extremes are near a sample, or on a step
            # where a host's face ends (the closed face counts, from either side).
            self.assertLessEqual(lo, hi + 1e-12)


class TheOrderThePartIsMadeIn(unittest.TestCase):
    """frame.md, "The order the part is made in"."""

    def test_a_hollowed_body_is_made_whole(self) -> None:
        box = item("box", "block", length=a(60), width=a(40), height=a(30))
        shell = item(
            "s", "shell", of="box", thickness=a(2), open={"faces": ["+z"], "from": SAY}
        )
        corners = item(
            "rv", "fillet", edges={"of": "box", "which": "vertical"}, radius=a(3)
        )
        rim = item("rt", "fillet", edges={"of": "box", "which": "top"}, radius=a(0.5))
        both = item("ca", "chamfer", edges={"of": "box", "which": "all"}, size=a(0.5))
        later = hole("box", "-z", 3)
        p = placed(box, rim, later, shell, corners, both)
        self.assertEqual(
            [s.item for s in p.order], ["box", "rv", "ca", "s", "rt", "ca", "h"]
        )
        own, edge = p.order[2], p.order[5]
        assert own.edges is not None and edge.edges is not None
        self.assertEqual(len(own.edges[0]), 8)  # the vertical and bottom edges
        self.assertEqual(len(edge.edges[0]), 4)  # the rim's

    def test_a_body_standing_sideways_names_its_edges_from_the_way_it_rises(
        self,
    ) -> None:
        box = item(
            "box", "block", on=on("plate", "+x"), length=a(20), width=a(4), height=a(10)
        )
        shell = item(
            "s", "shell", of="box", thickness=a(1), open={"faces": ["+z"], "from": SAY}
        )
        rounding = item(
            "r", "fillet", edges={"of": "box", "which": "vertical"}, radius=a(0.5)
        )
        p = placed(PLATE, box, shell, rounding)
        self.assertEqual([s.item for s in p.order], ["plate", "box", "r", "s", "r"])
        layout = solve(read([PLATE, box, shell, rounding]))
        self.assertEqual(list(layout.order), ["plate", "box", "r", "s", "r"])

    def test_dependencies_come_first_and_changes_last(self) -> None:
        later = item("b", "boss", on=on("plate", "+z"), diameter=a(5), height=a(3))
        threaded = item(
            "t",
            "thread",
            of="rod",
            designation={"text": "M8", "from": SAY},
            hand=pick("right"),
        )
        rod = item("rod", "cylinder", on=on("b", "+end"), diameter=a(8), length=a(10))
        p = placed(rod, threaded, PLATE, later)
        self.assertEqual([s.item for s in p.order], ["plate", "b", "rod", "t"])


class WhatIsNotPlaced(unittest.TestCase):
    def test_refusals(self) -> None:
        across = {  # a half outline reaching 2 mm across the axis it turns about
            "start": [-2, 0],
            "segments": [
                {"line_to": [10, 0]},
                {"line_to": [0, 10]},
                {"line_to": [-2, 0]},
            ],
            "from": SAY,
        }
        cases = [
            [item("r", "revolution", profile=across)],
            [
                PLATE,
                item("p2", "block", length=a(1), width=a(1), height=a(1)),
            ],  # two bodies on the origin
            [
                hole("plate", "+z", 3),
                PLATE,
                item("x", "hole", on=on("nothing", "+z"), diameter=a(1), depth=a(1)),
            ],
            [
                PLATE,
                hole("plate", "+z", 3, count=n(2)),
            ],  # the count isn't what is placed
            [PLATE, hole("plate", "+end", 3)],  # a face a block doesn't have
            [
                ROD,
                hole(
                    "rod",
                    "+end",
                    3,
                    place={"pattern": {"corners": {"inset_x": a(2), "inset_y": a(2)}}},
                ),
            ],  # corners on a disc
            [
                PLATE,
                hole("plate", "+z", 3, id="h"),
                hole("h", "+z", 1, id="g"),
            ],  # nothing stands on a hole
            [
                PLATE,
                item(
                    "s",
                    "slot",
                    on=on("plate", "+z"),
                    width=a(2),
                    length=a(5),
                    along=pick("z"),
                    ends=pick("round"),
                    depth=a(1),
                ),
            ],
            [
                PLATE,
                item(
                    "h",
                    "hole",
                    on=on("plate", "+z"),
                    diameter={"fit": "clearance", "for": "M7", "from": SAY},
                    depth=a(1),
                ),
            ],
            [item("z", "block", length=a(0), width=a(5), height=a(5))],
        ]
        for items in cases:
            spec = read(items)
            with self.assertRaises(PlaceError, msg=str([i["id"] for i in items])):
                place(spec)


class TheTwoPlacementsAgree(unittest.TestCase):
    """Random specs the solver accepts, placed by both: no difference at all."""

    def test_every_layout_any_test_makes_is_compared(self) -> None:
        import forge_spec.placement

        self.assertTrue(v2_layouts.ACTIVE)
        self.assertIs(forge_spec.placement.solve, v2_layouts._solve_and_compare)
        self.assertIs(solve, v2_layouts._solve_and_compare)

    def test_random_specs(self) -> None:
        seen: Counter[str] = Counter()
        for spec in random_specs(20261022, 120):
            layout = solve(spec)
            self.assertEqual(layout.issues, [])
            differences = compare_layouts(place(spec), layout)
            self.assertEqual(differences, (), [str(d) for d in differences])
            for it in spec.items:
                seen[it.kind] += 1
                where = it.get("place")
                if isinstance(where, Place):
                    seen["concentric"] += bool(where.concentric)
                    seen["angle"] += where.angle is not None
                    if where.pattern is not None:
                        seen[where.pattern.kind] += 1
                on_ = it.get("on")
                if isinstance(on_, On) and on_.face.startswith("inner"):
                    seen["inner face"] += 1
                if isinstance(on_, On) and on_.face in ("side", "bore", "inner side"):
                    seen["round side"] += 1
        wanted = ("block", "cylinder", "tube", "cone", "sphere", "hole", "slot", "pocket", "text", "boss", "post", "tab",
                  "rib", "region", "shell", "fillet", "chamfer", "thread", "concentric", "angle", "corners", "rectangle",
                  "ends", "row", "grid", "circle", "arc", "inner face", "round side")  # fmt: skip
        for what in wanted:
            self.assertGreaterEqual(seen[what], 5, (what, seen))

    def test_a_planted_bug_is_found(self) -> None:
        """The comparison sees a solver that swaps a post's length and width."""
        post = item(
            "p", "post", on=on("plate", "+z"), length=a(10), width=a(4), height=a(3)
        )
        spec = read([PLATE, post])
        layout = solve(spec)
        copy = layout.instances["p"][0]
        assert copy.lo is not None and copy.hi is not None
        swapped = (
            (copy.origin[0] - 2, copy.origin[1] - 5, copy.lo[2]),
            (copy.origin[0] + 2, copy.origin[1] + 5, copy.hi[2]),
        )
        layout.instances["p"][0] = type(copy)(
            copy.item,
            copy.index,
            copy.origin,
            copy.normal,
            copy.host,
            copy.face_axes,
            *swapped,
        )
        self.assertIn("box", [d.what for d in compare_layouts(place(spec), layout)])


if __name__ == "__main__":
    unittest.main()
