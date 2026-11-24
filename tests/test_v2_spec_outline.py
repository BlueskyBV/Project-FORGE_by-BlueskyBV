"""V2 stage 4: the solver's outlines of lines and arcs (forge_spec.outline; docs/V2-stage4.md, 6.6).

Inside, the signed distance, the box and the area against worked numbers and
against the outline followed by a fine polygon, at random points clear of it;
where pieces meet; what lies in an outline (rectangles, discs, other
outlines); and a revolution's ends and the material under them.
"""

from __future__ import annotations

import math
import random
import unittest
from collections.abc import Mapping, Sequence

from forge_spec.outline import (
    Arc,
    Line,
    Shape,
    boundary_within,
    meet,
    turned_depth,
    turned_extremes,
)

Point = tuple[float, float]


def outline(start: Point, *segments: tuple[Point, Point | None, bool]) -> Shape:
    return Shape.of(start, list(segments))


def line(to: Point) -> tuple[Point, None, bool]:
    return (to, None, False)


def arc(to: Point, centre: Point, clockwise: bool = False) -> tuple[Point, Point, bool]:
    return (to, centre, clockwise)


#: An L: 30 x 5 along the first axis, 5 x 20 up the second.
L = outline(
    (0, 0),
    line((30, 0)),
    line((30, 5)),
    line((5, 5)),
    line((5, 20)),
    line((0, 20)),
    line((0, 0)),
)
#: A plate 40 x 20 with round ends: two half circles of radius 10.
STADIUM = outline(
    (-10, -10),
    line((10, -10)),
    arc((10, 10), (10, 0)),
    line((-10, 10)),
    arc((-10, -10), (-10, 0)),
)
#: A 20 x 20 square with a half-disc notch of radius 4 bitten out of its top, drawn clockwise.
NOTCHED = outline((-10, -10), line((-10, 10)), line((-4, 10)), arc((4, 10), (0, 10)), line((10, 10)),
                  line((10, -10)), line((-10, -10)))  # fmt: skip
#: A disc of radius 7 about (3, -2): an arc back to its start.
CIRCLE = outline((10, -2), arc((10, -2), (3, -2)))


def polygon(shape: Shape, per_degree: int = 2) -> list[Point]:
    """The outline followed by a fine polygon (each arc every half degree)."""
    points: list[Point] = []
    for q in shape.pieces:
        if isinstance(q, Line):
            points.append(q.a)
        else:
            steps = max(2, int(abs(math.degrees(q.sweep)) * per_degree))
            points += [q.at(k / steps) for k in range(steps)]
    return points


def poly_inside(points: list[Point], p: Point) -> bool:
    inside = False
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True):
        if (y0 > p[1]) != (y1 > p[1]) and x0 + (p[1] - y0) * (x1 - x0) / (y1 - y0) > p[
            0
        ]:
            inside = not inside
    return inside


def poly_area(points: list[Point]) -> float:
    return (
        abs(
            sum(
                x0 * y1 - x1 * y0
                for (x0, y0), (x1, y1) in zip(
                    points, points[1:] + points[:1], strict=True
                )
            )
        )
        / 2
    )


class InsideAreaAndBox(unittest.TestCase):
    def test_worked_by_hand(self) -> None:
        self.assertAlmostEqual(L.area(), 30 * 5 + 5 * 15, places=12)
        self.assertAlmostEqual(STADIUM.area(), 20 * 20 + math.pi * 100, places=9)
        self.assertAlmostEqual(NOTCHED.area(), 400 - math.pi * 8, places=9)
        self.assertAlmostEqual(CIRCLE.area(), math.pi * 49, places=9)
        self.assertEqual(STADIUM.box(), ((-20.0, -10.0), (20.0, 10.0)))
        lo, hi = CIRCLE.box()
        for got, want in zip((*lo, *hi), (-4, -9, 10, 5), strict=True):
            self.assertAlmostEqual(got, want, places=12)
        self.assertTrue(NOTCHED.contains((0, 5.99)))
        self.assertFalse(NOTCHED.contains((0, 6.01)))
        self.assertTrue(NOTCHED.contains((0, 6.0)))  # on the notch's arc
        self.assertAlmostEqual(NOTCHED.signed_distance((0, 8)), 2.0, places=12)
        self.assertAlmostEqual(NOTCHED.signed_distance((0, 0)), -6.0, places=12)

    def test_against_a_fine_polygon_at_random_points(self) -> None:
        rng = random.Random(4)
        for name, shape in (
            ("L", L),
            ("stadium", STADIUM),
            ("notched", NOTCHED),
            ("circle", CIRCLE),
        ):
            points = polygon(shape)
            self.assertAlmostEqual(
                poly_area(points), shape.area(), delta=shape.area() * 1e-4, msg=name
            )
            (x0, y0), (x1, y1) = shape.box()
            tested = 0
            for _ in range(4000):
                p = (rng.uniform(x0 - 3, x1 + 3), rng.uniform(y0 - 3, y1 + 3))
                d = shape.distance(p)
                if d < 0.01:
                    continue  # the polygon's chords are within 0.002 of the arcs
                tested += 1
                with self.subTest(name, p=p):
                    self.assertEqual(shape.inside(p), poly_inside(points, p))
                    self.assertEqual(
                        shape.signed_distance(p) < 0, poly_inside(points, p)
                    )
            self.assertGreater(tested, 3500)

    def test_clockwise_or_not_the_same_region(self) -> None:
        reversed_notch = outline((-10, -10), line((10, -10)), line((10, 10)), line((4, 10)), arc((-4, 10), (0, 10), True),
                                 line((-10, 10)), line((-10, -10)))  # fmt: skip
        self.assertAlmostEqual(reversed_notch.area(), NOTCHED.area(), places=9)
        self.assertLess(
            reversed_notch.signed_area() * NOTCHED.signed_area(), 0
        )  # drawn the other way round


class WherePiecesMeet(unittest.TestCase):
    def test_each_pair(self) -> None:
        self.assertEqual(
            meet(Line((0, 0), (10, 0)), Line((5, -5), (5, 5))), [(5.0, 0.0)]
        )
        self.assertEqual(meet(Line((0, 0), (10, 0)), Line((5, 1), (5, 5))), [])
        self.assertEqual(
            sorted(meet(Line((0, 0), (10, 0)), Line((5, 0), (15, 0)))),
            [(5, 0), (10, 0)],
        )
        circle = Arc((0, 0), 5, 0, 2 * math.pi)
        found = sorted(meet(Line((-10, 3), (10, 3)), circle))
        self.assertEqual(
            [(round(x, 12), round(y, 12)) for x, y in found], [(-4.0, 3.0), (4.0, 3.0)]
        )
        self.assertEqual(len(meet(Line((-10, 5), (10, 5)), circle)), 1)  # touching
        upper = Arc((0, 0), 5, 0, math.pi)
        self.assertEqual(meet(Line((-10, -3), (10, -3)), upper), [])
        found = meet(Arc((0, 0), 5, 0, 2 * math.pi), Arc((6, 0), 5, 0, 2 * math.pi))
        self.assertEqual(
            sorted((round(x, 12), round(abs(y), 12)) for x, y in found),
            [(3.0, 4.0), (3.0, 4.0)],
        )


class WhatLiesInIt(unittest.TestCase):
    def test_rectangles_and_discs(self) -> None:
        self.assertTrue(L.holds_rect((15, 2.5), (14, 2.5)))  # flush with three sides
        self.assertFalse(L.holds_rect((6, 6), (1, 1)))  # in the L's corner, outside it
        self.assertFalse(L.holds_rect((4, 4), (2, 2)))  # across the inner corner
        self.assertTrue(L.holds_disc((2.5, 15), 2.5))
        self.assertFalse(L.holds_disc((2.5, 15), 2.6))
        # A rectangle that holds the notch's arc: the arc enters it though its corners are in the square.
        self.assertFalse(NOTCHED.holds_rect((0, 7), (5, 1.5)))
        self.assertTrue(NOTCHED.holds_rect((0, 2), (5, 3.9)))
        self.assertTrue(STADIUM.holds_disc((15, 0), 5))
        self.assertTrue(
            STADIUM.holds_rect((15, 0), (4, 4))
        )  # its corners 9.85 from the round end's centre
        self.assertFalse(
            STADIUM.holds_rect((15, 0), (4, 5))
        )  # its corners past the round end

    def test_an_outline_in_a_region(self) -> None:
        box = outline(
            (-50, -50),
            line((50, -50)),
            line((50, 50)),
            line((-50, 50)),
            line((-50, -50)),
        )
        self.assertTrue(boundary_within(L.pieces, box.contains, box.pieces))
        moved = L.moved(30, 0)
        self.assertFalse(boundary_within(moved.pieces, box.contains, box.pieces))
        flush = L.moved(20, 30)  # its far side along the box's
        self.assertTrue(boundary_within(flush.pieces, box.contains, box.pieces))
        # An L round the notch: its boundary crosses the notch's arc.
        self.assertFalse(
            boundary_within(L.moved(-3, -10).pieces, NOTCHED.contains, NOTCHED.pieces)
        )


#: A flange turned about its axis: a disc 40 across and 4 thick, a hub 16 across rising to 15, a bore 6 across.
FLANGE = outline(
    (3, 0),
    line((20, 0)),
    line((20, 4)),
    line((8, 4)),
    line((8, 15)),
    line((3, 15)),
    line((3, 0)),
)
#: A pulley 30 across and 10 thick with a groove of radius 3 round its rim at mid-height, solid to the axis.
PULLEY = outline((0, 0), line((15, 0)), line((15, 2)), arc((15, 8), (15, 5), True), line((15, 10)),
                 line((0, 10)), line((0, 0)))  # fmt: skip


class TurnedEndsAndMaterial(unittest.TestCase):
    def test_the_ends(self) -> None:
        self.assertEqual(turned_extremes(FLANGE, True), (15.0, 3.0, 8.0))  # a ring
        self.assertEqual(turned_extremes(FLANGE, False), (0.0, 3.0, 20.0))
        self.assertEqual(turned_extremes(PULLEY, True), (10.0, 0.0, 15.0))  # a disc
        dome = outline((0, 0), line((10, 0)), arc((0, 10), (0, 0)), line((0, 0)))
        self.assertIsNone(turned_extremes(dome, True))  # it comes to a point on its arc
        self.assertEqual(turned_extremes(dome, False), (0.0, 0.0, 10.0))

    def test_the_material_under_them(self) -> None:
        # Under the flange's bottom: 15 up through the hub, 4 in the disc beyond it.
        self.assertEqual(turned_depth(FLANGE, False, 3, 8), (15.0, 15.0))
        self.assertEqual(turned_depth(FLANGE, False, 5, 12), (4.0, 15.0))
        self.assertEqual(turned_depth(FLANGE, True, 3, 8), (15.0, 15.0))
        # Under the pulley's top: 10 everywhere but in the groove's reach, where it is 2 at the rim.
        least, most = turned_depth(PULLEY, True, 0, 15)
        self.assertAlmostEqual(least, 2.0, places=6)
        self.assertAlmostEqual(most, 10.0, places=12)
        least, _ = turned_depth(PULLEY, True, 0, 13)
        self.assertAlmostEqual(
            least, 10 - (5 + math.sqrt(9 - 4)), places=6
        )  # the groove's arc at 13 from the axis


class AnOutlinesSizesCited(unittest.TestCase):
    """A profile's cited words (docs/V2-stage4.md, 6.7): each number in them a size the outline has, and used."""

    DOUGHNUT = ("A PLA ring shaped like a doughnut: an 8 mm round section bent into a full ring 40 mm across at "
                "the centre line of the section. It carries no load, so there is no load case.")  # fmt: skip
    PRISM = "A PLA hexagonal prism, {} across the corners and 30 mm tall. It carries no load, so there is no load case."

    def problems(self, brief: str, kind: str, named: str, start: Point, segments: Sequence[Mapping[str, object]],
                 cited: str, *, strict: bool = False) -> list[tuple[str, str]]:  # fmt: skip
        """The draft's problems: the body ``named``, its outline citing the brief's text ``cited``."""
        import sys
        from pathlib import Path

        from forge_spec import number_words
        from forge_spec.checks import check_draft

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from v2_drafts import assumed, choose, draft, made_of, span

        b = number_words(brief)
        body = {"id": "body", "kind": kind, "words": span(b, named),
                "profile": {"start": list(start), "segments": list(segments), "from": {"words": span(b, cited)}},
                "axis": choose("z", assumed("it stands upright"))}  # fmt: skip
        if kind == "extrusion":
            body["length"] = {
                "value": 30,
                "unit": "mm",
                "from": {"words": span(b, "30 mm tall")},
            }
        d = draft("part", [body], material=made_of(b, "PLA"),
                  silent=[{"sentence": 1, "reason": "it says there is no load case"}])  # fmt: skip
        return [(p.kind, p.message) for p in check_draft(b, d, strict=strict).problems]

    def doughnut(self, middle: float, *, strict: bool = False) -> list[tuple[str, str]]:
        ring = [
            {"arc_to": [middle - 4, 0], "centre": [middle, 0]},
            {"arc_to": [middle + 4, 0], "centre": [middle, 0]},
        ]
        return self.problems(self.DOUGHNUT, "revolution", "ring shaped like a doughnut", (middle + 4, 0), ring,
                             "an 8 mm round section bent into a full ring 40 mm across at the centre line",
                             strict=strict)  # fmt: skip

    def hexagon(self, across: str, radius: float) -> list[tuple[str, str]]:
        h = radius * math.sqrt(3) / 2
        corners = [(radius / 2, h), (-radius / 2, h), (-radius, 0.0), (-radius / 2, -h), (radius / 2, -h),
                   (radius, 0.0)]  # fmt: skip
        segments = [{"line_to": [round(x, 4), round(y, 4)]} for x, y in corners]
        return self.problems(self.PRISM.format(across), "extrusion", "hexagonal prism", (radius, 0.0), segments,
                             f"hexagonal prism, {across} across the corners")  # fmt: skip

    def test_a_doughnut_s_section_and_its_middle(self) -> None:
        self.assertEqual(self.doughnut(20), [])

    def test_which_size_each_is_isn_t_read(self) -> None:
        # Drawn 40 across its outside on a 32 middle (V1's false pass 17): it has a 40 mm size too.
        self.assertEqual(self.doughnut(16), [])

    def test_an_automatic_run_stops_for_a_person(self) -> None:
        found = self.doughnut(20, strict=True)
        self.assertEqual(
            [m for k, m in found if k == "question" and "outline" in m],
            ["body.profile: the outline's sizes are each one it has, but which is which only a person can see: "
             "an automatic run can't confirm it"],
        )  # fmt: skip

    def test_a_hexagon_across_its_corners(self) -> None:
        self.assertEqual(self.hexagon("20 mm", 10.0), [])
        self.assertEqual(self.hexagon("2 cm", 10.0), [])  # converted

    def test_a_size_the_outline_hasn_t_is_a_fault(self) -> None:
        found = self.hexagon(
            "20 mm", 9.0
        )  # 18 across its corners, 15.6 across its flats
        self.assertIn(("fault", "the outline has no size of 20 mm: none across it, of a side, between parallel sides "
                                "or corners, of an arc, nor an angle it is drawn at"), found)  # fmt: skip

    def test_a_count_is_its_corners(self) -> None:
        self.assertEqual(self.hexagon("six-sided, 20 mm", 10.0), [])
        found = self.hexagon("five-sided, 20 mm", 10.0)
        # The number word named, so the writer can find it (eval fp24: "One end of the bar", three answers alike).
        self.assertTrue(
            any(
                k == "fault" and "no size of 5 (the brief's 'five-sided', word" in m
                for k, m in found
            ),
            found,
        )


if __name__ == "__main__":
    unittest.main()
