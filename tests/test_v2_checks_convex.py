"""V2 stage 4: an outline of lines and arcs taken apart into convex pieces (forge_checks.convex; docs/V2-stage4.md, 6.6).

Each outline's pieces, put back together (the polygons and the bulges the
outline holds, less those it doesn't), hold exactly the points the outline
holds, at random points clear of every edge; their area is the outline's;
every polygon is convex and anticlockwise; and an outline that crosses
itself is refused.
"""

from __future__ import annotations

import math
import random
import unittest

from forge_checks.convex import ConvexError, Pieces, convex_pieces
from forge_checks.outlines import Arc, Outline, Segment

Point = tuple[float, float]
Step = tuple[Point, Point | None, bool]


def outline(start: Point, *steps: Step) -> Outline:
    """Sides as the definitions write them: to a point, straight or round a centre (anticlockwise unless clockwise)."""
    sides: list[Segment | Arc] = []
    here = start
    for to, centre, clockwise in steps:
        if centre is None:
            sides.append(Segment(here, to))
        else:
            first = math.atan2(here[1] - centre[1], here[0] - centre[0])
            last = math.atan2(to[1] - centre[1], to[0] - centre[0])
            sweep = ((first - last) if clockwise else (last - first)) % (2 * math.pi)
            whole = sweep <= 1e-12
            sweep = 2 * math.pi if whole else sweep
            begin = last if clockwise and not whole else first
            sides.append(Arc(centre, math.dist(here, centre), begin, sweep))
        here = to
    return Outline.profile(sides)


def line(to: Point) -> Step:
    return (to, None, False)


def arc(to: Point, centre: Point, clockwise: bool = False) -> Step:
    return (to, centre, clockwise)


SHAPES: dict[str, Outline] = {
    "L": outline((0, 0), line((30, 0)), line((30, 5)), line((5, 5)), line((5, 20)), line((0, 20)), line((0, 0))),
    "stadium": outline((-10, -10), line((10, -10)), arc((10, 10), (10, 0)), line((-10, 10)), arc((-10, -10), (-10, 0))),
    "notched clockwise": outline((-10, -10), line((-10, 10)), line((-4, 10)), arc((4, 10), (0, 10)), line((10, 10)),
                                 line((10, -10)), line((-10, -10))),
    "circle": outline((10, -2), arc((10, -2), (3, -2))),
    "half disc": outline((10, 0), arc((-10, 0), (0, 0)), line((10, 0))),
    "flange": outline((3, 0), line((20, 0)), line((20, 4)), line((8, 4)), line((8, 15)), line((3, 15)), line((3, 0))),
    "pulley": outline((0, 0), line((15, 0)), line((15, 2)), arc((15, 8), (15, 5), True), line((15, 10)),
                      line((0, 10)), line((0, 0))),
    "dome": outline((0, 0), line((10, 0)), arc((0, 10), (0, 0)), line((0, 0))),
    "rounded corner": outline((0, 0), line((40, 0)), line((40, 22)), arc((32, 30), (32, 22)), line((0, 30)),
                              line((0, 0))),
    "T": outline((-20, 20), line((-20, 14)), line((-4, 14)), line((-4, -20)), line((4, -20)), line((4, 14)),
                 line((20, 14)), line((20, 20)), line((-20, 20))),
    # A plate with a deep round bite between two lugs: the bite's arc is near the far lug.
    "bitten": outline((0, 0), line((30, 0)), line((30, 20)), line((24, 20)), arc((6, 20), (15, 20), True),
                      line((0, 20)), line((0, 0))),
    # Arcs meeting arcs: a wavy edge, each wave a half circle the other way.
    "wavy": outline((0, 0), line((24, 0)), line((24, 10)), arc((18, 10), (21, 10)), arc((12, 10), (15, 10), True),
                    arc((6, 10), (9, 10)), arc((0, 10), (3, 10), True), line((0, 0))),
    # A knob: a disc with a rounded rim and a stem, its half outline.
    "knob": outline((0, 0), line((4, 0)), line((4, 6)), line((12, 6)), arc((14, 8), (12, 8), True),
                    line((14, 10)), arc((12, 12), (12, 10)), line((0, 12)), line((0, 0))),
}  # fmt: skip


def holds(pieces: Pieces, p: Point) -> bool:
    def in_polygon(corners: tuple[Point, ...]) -> bool:
        n = len(corners)
        return all(
            (corners[(k + 1) % n][0] - corners[k][0]) * (p[1] - corners[k][1])
            - (corners[(k + 1) % n][1] - corners[k][1]) * (p[0] - corners[k][0])
            >= 0
            for k in range(n)
        )

    def in_bulge(k: int) -> bool:
        b = pieces.bulges[k]
        nx, ny = b.outward
        return (
            math.dist(p, b.arc.centre) <= b.arc.radius
            and (p[0] - b.a[0]) * nx + (p[1] - b.a[1]) * ny >= 0
        )

    added = any(in_polygon(c) for c in pieces.polygons) or any(
        in_bulge(k) for k, b in enumerate(pieces.bulges) if b.adds
    )
    return added and not any(
        in_bulge(k) for k, b in enumerate(pieces.bulges) if not b.adds
    )


def turns_left(corners: tuple[Point, ...]) -> bool:
    n = len(corners)
    return all(
        (corners[k][0] - corners[k - 1][0]) * (corners[(k + 1) % n][1] - corners[k][1])
        - (corners[k][1] - corners[k - 1][1]) * (corners[(k + 1) % n][0] - corners[k][0])
        > 0
        for k in range(n)
    )


class PiecesPutBackTogether(unittest.TestCase):
    def test_every_point_as_the_outline(self) -> None:
        rng = random.Random(6)
        for name, shape in SHAPES.items():
            pieces = convex_pieces(shape)
            (c1, c2), (h1, h2) = shape.centre, shape.half
            tested = 0
            for _ in range(3000):
                p = (
                    rng.uniform(c1 - h1 - 2, c1 + h1 + 2),
                    rng.uniform(c2 - h2 - 2, c2 + h2 + 2),
                )
                if abs(shape.signed_distance(p)) < 1e-6:
                    continue
                tested += 1
                with self.subTest(name, p=p):
                    self.assertEqual(holds(pieces, p), shape.signed_distance(p) < 0)
            self.assertGreater(tested, 2900, name)

    def test_convex_polygons_and_the_area(self) -> None:
        for name, shape in SHAPES.items():
            pieces = convex_pieces(shape)
            with self.subTest(name):
                self.assertTrue(all(turns_left(c) for c in pieces.polygons))
                self.assertTrue(
                    all(b.arc.sweep <= math.pi / 2 + 1e-12 for b in pieces.bulges)
                )
        self.assertAlmostEqual(
            convex_pieces(SHAPES["stadium"]).area(), 400 + math.pi * 100, places=9
        )
        self.assertAlmostEqual(
            convex_pieces(SHAPES["notched clockwise"]).area(),
            400 - math.pi * 8,
            places=9,
        )
        half = convex_pieces(SHAPES["half disc"])
        self.assertEqual(len(half.bulges), 2)  # its half circle in two quarters, a triangle between them
        self.assertEqual(len(half.polygons), 1)
        self.assertAlmostEqual(half.area(), math.pi * 50, places=9)

    def test_a_polygon_needs_few_pieces(self) -> None:
        # Joined again after the ears are clipped: at most twice as many as its corners turning back, and one.
        for name, turning_back in (("L", 1), ("T", 2), ("flange", 1)):
            with self.subTest(name):
                self.assertLessEqual(len(convex_pieces(SHAPES[name]).polygons), 2 * turning_back + 1)
        self.assertEqual(len(convex_pieces(SHAPES["L"]).polygons), 2)


class RefusedOutlines(unittest.TestCase):
    def test_one_that_crosses_itself(self) -> None:
        bow = outline((0, 0), line((10, 10)), line((10, 0)), line((0, 10)), line((0, 0)))
        with self.assertRaises(ConvexError):
            convex_pieces(bow)

    def test_an_arc_through_another_side(self) -> None:
        crossed = outline((0, 0), line((20, 0)), line((20, 10)), arc((0, 10), (10, 8), True), line((0, 0)))
        with self.assertRaises(ConvexError):
            convex_pieces(crossed)  # the arc dips 2.2 below the bottom side

    def test_not_a_profile(self) -> None:
        with self.assertRaises(ConvexError):
            convex_pieces(Outline.rect(5, 5))


if __name__ == "__main__":
    unittest.main()
