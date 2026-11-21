"""Outlines in a face's plane (forge_checks.outlines), checked against brute force.

Every answer that comes from a closed form here is compared with one found
the slow way, written independently in this file: membership from the
definitions of the shapes, distances from boundaries traced point by point,
and nearest points of overlaps from fine grids.
"""

from __future__ import annotations

import math
import random
import unittest
from collections.abc import Callable

from forge_checks.outlines import TOL, Outline, nearest_common, nearest_point, overlap

Point = tuple[float, float]


def inside(o: Outline, p: Point) -> bool:
    """Membership straight from the shapes' definitions (this file's own)."""
    dx, dy = p[0] - o.centre[0], p[1] - o.centre[1]
    if o.shape == "disc":
        return math.hypot(dx, dy) <= o.half[0]
    if o.shape == "ring":
        return o.inner <= math.hypot(dx, dy) <= o.half[0]
    h1, h2 = o.half
    if abs(dx) > h1 or abs(dy) > h2:
        return False
    for (s1, s2), r in zip(
        ((1, 1), (-1, 1), (-1, -1), (1, -1)), o.corners, strict=True
    ):
        cx, cy = s1 * (h1 - r), s2 * (h2 - r)
        if (
            r > 0
            and s1 * dx > s1 * cx
            and s2 * dy > s2 * cy
            and math.hypot(dx - cx, dy - cy) > r
        ):
            return False
    return True


def near_or_in(o: Outline, p: Point, tol: float = 1e-7) -> bool:
    """In the outline, or within ``tol`` of a point that is."""
    return any(
        inside(
            o,
            (
                p[0] + tol * math.cos(k * math.pi / 4),
                p[1] + tol * math.sin(k * math.pi / 4),
            ),
        )
        for k in range(8)
    ) or inside(o, p)


def boundary(o: Outline, step: float = 0.01) -> list[Point]:
    """Points along the outline's edge, ``step`` apart or closer."""
    found: list[Point] = []

    def circle(c: Point, r: float, a0: float, a1: float) -> None:
        k = max(int(r * (a1 - a0) / step), 8)
        found.extend(
            (
                c[0] + r * math.cos(a0 + (a1 - a0) * i / k),
                c[1] + r * math.sin(a0 + (a1 - a0) * i / k),
            )
            for i in range(k + 1)
        )

    def line(p: Point, q: Point) -> None:
        k = max(int(math.dist(p, q) / step), 1)
        found.extend(
            (p[0] + (q[0] - p[0]) * i / k, p[1] + (q[1] - p[1]) * i / k)
            for i in range(k + 1)
        )

    c1, c2 = o.centre
    if o.shape != "rect":
        circle(o.centre, o.half[0], 0, 2 * math.pi)
        if o.shape == "ring":
            circle(o.centre, o.inner, 0, 2 * math.pi)
        return found
    h1, h2 = o.half
    r1, r2, r3, r4 = o.corners
    for (s1, s2), r, k in zip(
        ((1, 1), (-1, 1), (-1, -1), (1, -1)), o.corners, range(4), strict=True
    ):
        if r > 0:
            circle(
                (c1 + s1 * (h1 - r), c2 + s2 * (h2 - r)),
                r,
                k * math.pi / 2,
                (k + 1) * math.pi / 2,
            )
    line((c1 + h1 - r1, c2 + h2), (c1 - h1 + r2, c2 + h2))
    line((c1 - h1, c2 + h2 - r2), (c1 - h1, c2 - h2 + r3))
    line((c1 - h1 + r3, c2 - h2), (c1 + h1 - r4, c2 - h2))
    line((c1 + h1, c2 - h2 + r4), (c1 + h1, c2 + h2 - r1))
    return found


def random_outline(rng: random.Random, near: float = 10.0) -> Outline:
    centre = (rng.uniform(-near, near), rng.uniform(-near, near))
    shape = rng.choice(["rect", "rect", "disc", "ring", "stadium", "tab"])
    if shape == "disc":
        return Outline.disc(rng.uniform(1, 10), centre)
    if shape == "ring":
        r = rng.uniform(2, 10)
        return Outline.ring(r, r * rng.uniform(0.2, 0.8), centre)
    if shape == "stadium":
        width = rng.uniform(1, 8)
        return Outline.stadium(
            width * rng.uniform(1, 3),
            width,
            along_first=rng.random() < 0.5,
            centre=centre,
        )
    h1, h2 = rng.uniform(0.5, 10), rng.uniform(0.5, 10)
    if shape == "tab":  # two corners at one end rounded to the half width
        r = h2
        h1 = max(h1, r / 2)
        return Outline.rect(h1, h2, centre, (r, 0.0, 0.0, r))
    r = rng.uniform(0, min(h1, h2))
    corners = tuple(r if rng.random() < 0.7 else 0.0 for _ in range(4))
    return Outline.rect(
        h1, h2, centre, (corners[0], corners[1], corners[2], corners[3])
    )


class Shapes(unittest.TestCase):
    def test_what_can_t_be_an_outline(self) -> None:
        bad: Callable[[], Outline]
        for bad in (
            lambda: Outline.rect(0, 1),
            lambda: Outline.rect(1, -1),
            lambda: Outline.rect(
                1, 1, corners=(1.5, 0, 0, 1.5)
            ),  # overlapping along a side
            lambda: Outline.rect(
                1, 1, corners=(1, 1.5, 0, 0)
            ),  # two corners overlapping along a side
            lambda: Outline.rect(1, 1, corners=(-0.1, 0, 0, 0)),
            lambda: Outline.disc(0),
            lambda: Outline.ring(5, 5),
            lambda: Outline.ring(5, 0),
            lambda: Outline.stadium(2, 3, along_first=True),
            lambda: Outline.rect(math.nan, 1),
            lambda: Outline("square", (0, 0), (1, 1)),
        ):
            with self.assertRaises(ValueError):
                bad()

    def test_a_corner_may_be_wider_than_half_the_shape(self) -> None:
        # A round-ended tab shorter than it is wide: two corners take a whole side.
        tab = Outline.rect(1, 2, corners=(2, 0, 0, 2))
        self.assertTrue(tab.contains((-0.9, 0)))
        self.assertTrue(tab.contains((1, 0)))  # the tip of the round end
        self.assertFalse(tab.contains((0.9, 1.9)))
        self.assertAlmostEqual(
            tab.farthest((-1, 0)), 2.0, places=12
        )  # a half-disc round (-1, 0)
        self.assertAlmostEqual(tab.farthest((1, 0)), math.sqrt(8), places=12)

    def test_a_stadium_is_a_rectangle_with_its_corners_rounded_to_half_its_width(
        self,
    ) -> None:
        slot = Outline.stadium(20, 6, along_first=False, centre=(1, 2))
        self.assertEqual(slot, Outline.rect(3, 10, (1, 2), (3, 3, 3, 3)))
        self.assertTrue(slot.contains((1, 12)))
        self.assertFalse(slot.contains((3.9, 11.9)))  # cut off by the round end

    def test_membership_and_signed_distance_agree_with_the_definitions(self) -> None:
        rng = random.Random(5)
        for _ in range(150):
            o = random_outline(rng)
            edge = boundary(o, 0.02)
            for _ in range(60):
                p = (rng.uniform(-22, 22), rng.uniform(-22, 22))
                d = o.signed_distance(p)
                truth = min(math.dist(p, q) for q in edge)
                self.assertLessEqual(abs(abs(d) - truth), 0.02, (o, p))
                if abs(d) > 1e-9:
                    self.assertEqual(d < 0, inside(o, p), (o, p, d))
                    self.assertEqual(o.contains(p), inside(o, p), (o, p))

    def test_points_on_the_edge_are_in_it(self) -> None:
        rng = random.Random(6)
        for _ in range(100):
            o = random_outline(rng)
            for p in boundary(o, 0.5):
                self.assertTrue(o.contains(p), (o, p))
                self.assertLessEqual(abs(o.signed_distance(p)), 1e-9, (o, p))

    def test_farthest_and_nearest(self) -> None:
        rng = random.Random(7)
        for _ in range(150):
            o = random_outline(rng)
            c = (rng.uniform(-25, 25), rng.uniform(-25, 25))
            edge = boundary(o, 0.01)
            self.assertAlmostEqual(
                o.farthest(c), max(math.dist(c, q) for q in edge), delta=0.01
            )
            expected = 0.0 if inside(o, c) else min(math.dist(c, q) for q in edge)
            self.assertAlmostEqual(o.nearest(c), expected, delta=0.01)


class Overlaps(unittest.TestCase):
    def test_the_nearest_point_of_an_overlap(self) -> None:
        rng = random.Random(8)
        tried = 0
        while tried < 120:
            outlines = [random_outline(rng, 4) for _ in range(rng.choice([1, 2, 2, 3]))]
            c = (rng.uniform(-20, 20), rng.uniform(-20, 20))
            step = 0.05
            lo = [max(o.centre[k] - o.half[k] for o in outlines) for k in (0, 1)]
            hi = [min(o.centre[k] + o.half[k] for o in outlines) for k in (0, 1)]
            grid = [
                (lo[0] + i * step, lo[1] + j * step)
                for i in range(int((hi[0] - lo[0]) / step) + 1)
                for j in range(int((hi[1] - lo[1]) / step) + 1)
            ]
            shared = [p for p in grid if all(inside(o, p) for o in outlines)]
            point = nearest_point(c, outlines)
            if len(shared) < 20:
                continue  # touching or nearly: the grid can't stand for it
            tried += 1
            assert point is not None, (outlines, c)
            # It is in every outline, and no point of the grid that is is nearer.
            self.assertTrue(
                all(near_or_in(o, point) for o in outlines), (outlines, c, point)
            )
            truth = min(math.dist(c, p) for p in shared)
            self.assertLessEqual(math.dist(c, point), truth + 1e-9, (outlines, c))
            self.assertEqual(nearest_common(c, outlines), math.dist(c, point))

    def test_outlines_that_only_touch_share_where_they_touch(self) -> None:
        a = Outline.rect(5, 5)
        b = Outline.disc(2, (7, 0))
        self.assertTrue(overlap([a, b]))
        self.assertAlmostEqual(nearest_common((20, 0), [a, b]) or -1, 15.0, places=9)
        self.assertIsNone(nearest_common((0, 0), [a, Outline.disc(2, (7 + 1e-6, 0))]))
        self.assertTrue(overlap([a, Outline.disc(2, (7 + TOL / 2, 0))]))
        ring = Outline.ring(10, 4)
        self.assertIsNone(nearest_common((0, 0), [ring, Outline.disc(3.5)]))
        self.assertAlmostEqual(
            nearest_common((0, 0), [ring, Outline.disc(4)]) or -1, 4.0, places=9
        )

    def test_a_ring_round_a_point_at_its_centre(self) -> None:
        self.assertAlmostEqual(
            nearest_common((0, 0), [Outline.ring(10, 4)]) or -1, 4.0, places=12
        )
        self.assertAlmostEqual(
            nearest_common((0, 0), [Outline.ring(10, 4), Outline.rect(10, 1, (0, -5))])
            or -1,
            4.0,
            places=9,
        )


class LyingWithin(unittest.TestCase):
    def test_within_agrees_with_points_of_both(self) -> None:
        rng = random.Random(9)
        decided = {True: 0, False: 0}
        for _ in range(600):
            outer = random_outline(rng, 3)
            inner = random_outline(rng, 3)
            if inner.shape == "ring":
                continue
            scale = rng.uniform(0.2, 1.0)
            r1, r2, r3, r4 = (r * scale for r in inner.corners)
            inner = Outline(
                inner.shape,
                inner.centre,
                (inner.half[0] * scale, inner.half[1] * scale),
                (r1, r2, r3, r4),
            )
            verdict = inner.within(outer)
            points = boundary(inner, 0.01) + [
                (
                    inner.centre[0] + inner.half[0] * i / 20,
                    inner.centre[1] + inner.half[1] * j / 20,
                )
                for i in range(-20, 21)
                for j in range(-20, 21)
            ]
            points = [p for p in points if near_or_in(inner, p)]
            if verdict:
                self.assertTrue(
                    all(near_or_in(outer, p) for p in points), (inner, outer)
                )
            else:
                self.assertTrue(
                    any(not inside(outer, p) for p in points), (inner, outer)
                )
            decided[verdict] += 1
        self.assertGreater(min(decided.values()), 50, decided)

    def test_a_disc_in_a_ring_must_miss_the_ring_s_opening(self) -> None:
        ring = Outline.ring(10, 4)
        self.assertTrue(Outline.disc(2, (7, 0)).within(ring))
        self.assertFalse(Outline.disc(2, (5, 0)).within(ring))
        self.assertFalse(Outline.disc(2, (9, 0)).within(ring))

    def test_a_ring_is_asked_as_its_outer_disc(self) -> None:
        """A tube's end face over its host (generated part 9126, a block turned on a tube's end: the judge stopped there): a ring lies within what its outer disc does; in a ring whose opening its own takes in, it isn't found to (a bound)."""
        ring = Outline.ring(10, 4)
        self.assertTrue(ring.within(Outline.disc(20)))
        self.assertTrue(ring.within(Outline.rect(10, 12)))
        self.assertFalse(ring.within(Outline.disc(8)))
        self.assertFalse(ring.within(Outline.ring(12, 3)))

    def test_a_disc_in_a_rounded_corner(self) -> None:
        pocket = Outline.rect(10, 10, corners=(5, 5, 5, 5))
        self.assertTrue(
            Outline.disc(1, (7.5, 7.5)).within(pocket)
        )  # 3.5 mm from the corner's centre
        self.assertFalse(
            Outline.disc(1.5, (8.5, 8.5)).within(pocket)
        )  # it reaches past the arc


if __name__ == "__main__":
    unittest.main()
