"""V2 stage 2: the orientation predicates' signs are exact (forge_checks.predicates).

Each sign is checked against the determinant worked out in rationals, on
points chosen to be hard: exactly on a plane or a line, an ulp off it, far
from the origin, very small and very large, so that the floating-point pass
is unsure and the exact pass decides.
"""

from __future__ import annotations

import random
import unittest
from collections.abc import Sequence
from fractions import Fraction

import numpy as np
from forge_checks.predicates import (
    SMALLEST,
    orient2d,
    orient2d_filtered,
    orient2d_one,
    orient3d,
    orient3d_filtered,
    orient3d_one,
)

Point = tuple[float, float, float]


def exact3(*points: Sequence[float]) -> int:
    a, b, c, d = ([Fraction(x) for x in p] for p in points)
    m = [
        [a[i] - d[i] for i in range(3)],
        [b[i] - d[i] for i in range(3)],
        [c[i] - d[i] for i in range(3)],
    ]
    det = (
        m[0][2] * (m[1][0] * m[2][1] - m[2][0] * m[1][1])
        + m[1][2] * (m[2][0] * m[0][1] - m[0][0] * m[2][1])
        + m[2][2] * (m[0][0] * m[1][1] - m[1][0] * m[0][1])
    )
    return int(det > 0) - int(det < 0)


def exact2(*points: Sequence[float]) -> int:
    a, b, c = ([Fraction(x) for x in p] for p in points)
    det = (a[0] - c[0]) * (b[1] - c[1]) - (a[1] - c[1]) * (b[0] - c[0])
    return int(det > 0) - int(det < 0)


def hard_points(rng: random.Random, n: int) -> list[tuple[Point, ...]]:
    """Quadruples of points on (or an ulp off) a random plane, at random scales and offsets."""
    out: list[tuple[Point, ...]] = []
    for _ in range(n):
        scale = 10.0 ** rng.randint(-6, 4)
        offset = rng.choice([0.0, 1.0, 1000.0, -12345.678])
        normal = [rng.uniform(-1, 1) for _ in range(3)]
        points: list[Point] = []
        for _k in range(4):
            u, v = rng.uniform(-1, 1) * scale, rng.uniform(-1, 1) * scale
            x, y = offset + u, offset + v
            z = offset - (normal[0] * u + normal[1] * v) / (normal[2] or 1.0)
            if rng.random() < 0.3:
                z = float(np.nextafter(z, rng.choice([-np.inf, np.inf])))
            points.append((x, y, z))
        if rng.random() < 0.3:  # exactly on an axis plane
            points = [(p[0], p[1], offset) for p in points]
        if rng.random() < 0.2:  # repeated points
            points[3] = points[rng.randrange(3)]
        out.append(tuple(points))
    return out


class SignsAreExact(unittest.TestCase):
    def test_orient3d_on_hard_points(self) -> None:
        cases = hard_points(random.Random(1), 3000)
        a, b, c, d = (np.array([q[k] for q in cases]) for k in range(4))
        got = orient3d(a, b, c, d)
        _, sure = orient3d_filtered(a, b, c, d)
        self.assertGreater(
            int((~sure).sum()), 300, "the cases must reach the exact pass"
        )
        for k, q in enumerate(cases):
            want = exact3(*q)
            self.assertEqual(int(got[k]), want, q)
            self.assertEqual(orient3d_one(*q), want, q)

    def test_orient2d_on_hard_points(self) -> None:
        rng = random.Random(2)
        cases = []
        for _ in range(3000):
            scale = 10.0 ** rng.randint(-6, 4)
            offset = rng.choice([0.0, 3.0, 1000.0])
            slope = rng.uniform(-3, 3)
            pts = []
            for _k in range(3):
                t = rng.uniform(-1, 1) * scale
                y = offset + slope * t
                if rng.random() < 0.3:
                    y = float(np.nextafter(y, rng.choice([-np.inf, np.inf])))
                pts.append((offset + t, y))
            cases.append(tuple(pts))
        a, b, c = (np.array([q[k] for q in cases]) for k in range(3))
        got = orient2d(a, b, c)
        _, sure = orient2d_filtered(a, b, c)
        self.assertGreater(int((~sure).sum()), 300)
        for k, q in enumerate(cases):
            self.assertEqual(int(got[k]), exact2(*q), q)
            self.assertEqual(orient2d_one(*q), exact2(*q), q)

    def test_a_sure_float_sign_is_the_true_sign(self) -> None:
        rng = np.random.default_rng(3)
        a, b, c, d = (
            rng.normal(size=(20000, 3)) * 10.0 ** rng.integers(-3, 4, (20000, 1))
            for _ in range(4)
        )
        signs, sure = orient3d_filtered(a, b, c, d)
        for k in np.flatnonzero(sure)[:4000]:
            self.assertEqual(int(signs[k]), exact3(a[k], b[k], c[k], d[k]))

    def test_the_orientation_convention(self) -> None:
        a, b, c = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
        self.assertEqual(orient3d_one(a, b, c, (0.0, 0.0, -1.0)), 1)  # below: positive
        self.assertEqual(orient3d_one(a, b, c, (0.0, 0.0, 1.0)), -1)
        self.assertEqual(
            orient2d_one((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)), 1
        )  # anticlockwise

    def test_the_smallest_coordinate_keeps_products_from_underflowing(self) -> None:
        # Three differences of size SMALLEST multiply to 1e-150: far above the
        # smallest float, so the floating-point pass's bound holds.
        self.assertGreater(SMALLEST**3, 1e-300)
        tiny = SMALLEST
        a, b, c = (0.0, 0.0, 0.0), (tiny, 0.0, 0.0), (0.0, tiny, 0.0)
        self.assertEqual(orient3d_one(a, b, c, (0.0, 0.0, -tiny)), 1)
        signs = orient3d(*(np.array([p]) for p in (a, b, c, (0.0, 0.0, -tiny))))
        self.assertEqual(signs.tolist(), [1])


if __name__ == "__main__":
    unittest.main()
