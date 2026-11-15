"""V2 stage 2: whether two triangles meet where they aren't joined (forge_checks.intersect).

Checked against an independent, exact oracle: two closed triangles share a
point exactly when a small linear system in their barycentric coordinates
has a solution, which Fourier-Motzkin elimination over rationals decides.
"Beyond what they share" is one strict inequality more: off the shared
corner, or off the shared side. The cases are drawn to be degenerate as
often as not -- small whole-number coordinates, points in one plane, on one
line, and tilted planes rounded to floats with ulp-sized nudges.
"""

from __future__ import annotations

import random
import unittest
from collections.abc import Sequence
from fractions import Fraction

import numpy as np
from forge_checks.intersect import pairs_meet
from forge_checks.predicates import orient2d_one
from numpy.typing import NDArray

Constraint = tuple[list[Fraction], Fraction, str]  # sum c_i x_i + c0  (= | >= | >)  0
Point = tuple[float, ...]
Case = tuple[
    list[Point], list[Point], int
]  # two triangles, and how many corners they share


def feasible(constraints: list[Constraint], variables: int) -> bool:
    """Exact Fourier-Motzkin elimination: has the system a solution?"""
    cons = list(constraints)
    while True:
        eq = next((c for c in cons if c[2] == "=" and any(c[0])), None)
        if eq is None:
            break
        k = next(i for i, v in enumerate(eq[0]) if v != 0)
        new = []
        for c in cons:
            if c is eq:
                continue
            f = c[0][k] / eq[0][k]
            new.append(
                (
                    [a - f * b for a, b in zip(c[0], eq[0], strict=True)],
                    c[1] - f * eq[1],
                    c[2],
                )
            )
        cons = new
    if any(c[2] == "=" and c[1] != 0 for c in cons):
        return False
    cons = [c for c in cons if c[2] != "="]
    for k in range(variables):
        positive = [c for c in cons if c[0][k] > 0]
        negative = [c for c in cons if c[0][k] < 0]
        kept = {(tuple(c[0]), c[1]): c for c in cons if c[0][k] == 0}
        for p in positive:
            for n in negative:
                a, b = -n[0][k], p[0][k]
                co = [a * x + b * y for x, y in zip(p[0], n[0], strict=True)]
                kind = ">" if ">" in (p[2], n[2]) else ">="
                key = (tuple(co), a * p[1] + b * n[1])
                if key not in kept or kind == ">":
                    kept[key] = (co, key[1], kind)
        cons = list(kept.values())
    return all((c[1] >= 0) if c[2] == ">=" else (c[1] > 0) for c in cons)


def meet_exactly(
    t1: list[tuple[float, ...]], t2: list[tuple[float, ...]], shared: int
) -> bool:
    """``shared`` 0; 1 (t1[0] is t2[0]); or 2 (t1[0], t1[1] are t2[0], t2[1])."""
    a0, a1, a2 = ([Fraction(c) for c in p] for p in t1)
    b0, b1, b2 = ([Fraction(c) for c in p] for p in t2)
    one, zero = Fraction(1), Fraction(0)
    cons: list[Constraint] = []
    for ax in range(3):
        cons.append(
            (
                [a1[ax] - a0[ax], a2[ax] - a0[ax], b0[ax] - b1[ax], b0[ax] - b2[ax]],
                a0[ax] - b0[ax],
                "=",
            )
        )
    cons += [
        ([one, zero, zero, zero], zero, ">="),
        ([zero, one, zero, zero], zero, ">="),
        ([-one, -one, zero, zero], one, ">="),
        ([zero, zero, one, zero], zero, ">="),
        ([zero, zero, zero, one], zero, ">="),
        ([zero, zero, -one, -one], one, ">="),
    ]
    if shared == 1:
        cons.append(([one, one, zero, zero], zero, ">"))  # not the shared corner
    elif shared == 2:
        cons.append(([zero, one, zero, zero], zero, ">"))  # off the shared side
    return feasible(cons, 4)


def collinear(a: tuple[float, ...], b: tuple[float, ...], c: tuple[float, ...]) -> bool:
    return all(
        orient2d_one((a[i], a[j]), (b[i], b[j]), (c[i], c[j])) == 0
        for i, j in ((0, 1), (1, 2), (0, 2))
    )


def draw(seed: int, count: int, reach: int, mode: str) -> list[Case]:
    rng = random.Random(seed)
    cases: list[Case] = []
    while len(cases) < count:
        shared = rng.choice([0, 1, 2])
        pts: list[tuple[float, ...]] = [
            tuple(float(rng.randint(-reach, reach)) for _ in range(3))
            for _ in range(6 - shared)
        ]
        if mode == "float":
            nudge = (0.0, 0.0, 1e-15, -1e-15, 1e-9)
            pts = [
                tuple(
                    c * 0.1 + (rng.choice(nudge) if rng.random() < 0.3 else 0.0)
                    for c in p
                )
                for p in pts
            ]
            sx, sy = rng.uniform(-1, 1), rng.uniform(-1, 1)
            pts = [(p[0], p[1], p[2] + sx * p[0] + sy * p[1]) for p in pts]
        if rng.random() < 0.5:  # most points into one plane
            pts = [(p[0], p[1], 0.0) if rng.random() < 0.8 else p for p in pts]
        if len(set(pts)) < len(pts):
            continue
        if shared == 0:
            t1, t2 = pts[0:3], pts[3:6]
        elif shared == 1:
            t1, t2 = pts[0:3], [pts[0], pts[3], pts[4]]
        else:
            t1, t2 = pts[0:3], [pts[0], pts[1], pts[3]]
        if collinear(*t1) or collinear(*t2):
            continue
        cases.append((t1, t2, shared))
    return cases


def as_mesh(cases: list[Case]) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Each pair as two faces, the shared corners shared by index, turned to different starts."""
    verts: list[tuple[float, ...]] = []
    faces: list[list[int]] = []
    for t1, t2, shared in cases:
        n = len(verts)
        if shared == 0:
            verts += t1 + t2
            faces += [[n, n + 1, n + 2], [n + 3, n + 4, n + 5]]
        elif shared == 1:
            verts += t1 + t2[1:]
            faces += [[n, n + 1, n + 2], [n + 3, n, n + 4]]
        else:
            verts += [*t1, t2[2]]
            faces += [[n, n + 1, n + 2], [n + 1, n + 3, n]]
    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int64)


class AgreesWithTheExactOracle(unittest.TestCase):
    def check(self, seed: int, count: int, reach: int, mode: str) -> None:
        cases = draw(seed, count, reach, mode)
        v, f = as_mesh(cases)
        n = len(cases)
        got = pairs_meet(v, f, np.arange(0, 2 * n, 2), np.arange(1, 2 * n, 2))
        seen = {(s, w) for (_, _, s), w in zip(cases, got.tolist(), strict=True)}
        self.assertEqual(len(seen), 6, "every kind of sharing, meeting and not")
        for k, (t1, t2, shared) in enumerate(cases):
            self.assertEqual(
                bool(got[k]), meet_exactly(t1, t2, shared), (t1, t2, shared)
            )

    def test_whole_numbers_in_a_small_box(self) -> None:
        self.check(1, 4000, 2, "int")
        self.check(2, 3000, 1, "int")

    def test_tilted_planes_rounded_and_nudged(self) -> None:
        self.check(3, 4000, 2, "float")
        self.check(4, 3000, 3, "float")


class NamedCases(unittest.TestCase):
    def meet(
        self, vertices: Sequence[Sequence[float]], one: list[int], two: list[int]
    ) -> bool:
        v = np.array(vertices, dtype=np.float64)
        f = np.array([one, two], dtype=np.int64)
        return bool(pairs_meet(v, f, np.array([0]), np.array([1]))[0])

    def test_the_same_triangle_twice(self) -> None:
        self.assertTrue(
            self.meet([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [0, 1, 2], [2, 1, 0])
        )

    def test_neighbours_in_one_plane_and_folded(self) -> None:
        v: list[list[float]] = [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [1, 1, 0],
            [0.2, 0.2, 0],
        ]
        self.assertFalse(self.meet(v, [0, 1, 2], [2, 1, 3]))  # flat neighbours
        self.assertTrue(self.meet(v, [0, 1, 2], [1, 2, 4]))  # folded back over

    def test_a_corner_resting_on_a_face(self) -> None:
        v: list[list[float]] = [
            [0, 0, 0],
            [2, 0, 0],
            [0, 2, 0],
            [0.5, 0.5, 0],
            [0.5, 0.5, 1],
            [1, 2, 1],
        ]
        self.assertTrue(self.meet(v, [0, 1, 2], [3, 4, 5]))

    def test_a_fan_s_far_triangles_meet_only_at_the_centre(self) -> None:
        v: list[list[float]] = [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [-1, 0, 0.5],
            [0, -1, 0.5],
        ]
        self.assertFalse(self.meet(v, [0, 1, 2], [0, 3, 4]))

    def test_a_saddle_s_crossing_triangles(self) -> None:
        # Two triangles at a shared corner, each crossing the other's plane, apart.
        v: list[list[float]] = [
            [0, 0, 0],
            [1, 0, 1],
            [1, 1, -1],
            [-1, 0, 1],
            [-1, -1, -1],
        ]
        self.assertFalse(self.meet(v, [0, 1, 2], [0, 3, 4]))
        # And through each other.
        w: list[list[float]] = [[0, 0, 0], [1, 0, 1], [1, 1, -1], [1, 1, 1], [1, 0, -1]]
        self.assertTrue(self.meet(w, [0, 1, 2], [0, 3, 4]))


if __name__ == "__main__":
    unittest.main()
