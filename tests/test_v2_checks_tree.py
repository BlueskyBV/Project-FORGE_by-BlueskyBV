"""V2 stage 2: the box tree finds what a search of every triangle would (forge_checks.tree).

Each search is compared with the brute-force answer on triangle soups made
to be awkward: long thin triangles across the whole space, tiny ones in
dense clumps, triangles with exactly the same centre, and points far away,
near, and on the triangles themselves.
"""

from __future__ import annotations

import math
import unittest

import numpy as np
from forge_checks.tree import FEW, LEAF, Tree
from forge_checks.triangles import (
    DISTANCE_ERROR,
    closest_points,
    ray_hits,
    unit_normals,
)
from numpy.typing import NDArray
from v2_exact import distance2, exact

Array = NDArray[np.float64]


def soup(seed: int, count: int) -> Array:
    rng = np.random.default_rng(seed)
    centres = np.concatenate(
        [
            rng.uniform(-50, 50, size=(count // 2, 3)),
            rng.normal(0, 0.5, size=(count - count // 2 - 20, 3))
            + 10.0,  # a dense clump
            np.full((20, 3), 3.0),  # twenty with the same centre
        ]
    )
    sizes = np.where(
        rng.random(len(centres)) < 0.05, 80.0, rng.uniform(0.01, 3.0, len(centres))
    )
    offsets = rng.normal(size=(len(centres), 3, 3)) * sizes[:, None, None]
    offsets -= offsets.mean(
        axis=1, keepdims=True
    )  # the box centre stays near the centre
    return np.asarray(centres[:, None, :] + offsets, dtype=np.float64)


def boxes(t: Array) -> tuple[Array, Array]:
    return t.min(axis=1), t.max(axis=1)


class OnePointOrRayAndOneTriangle(unittest.TestCase):
    """closest_points and ray_hits, against answers worked out another way."""

    def test_the_nearest_point_is_nearest_to_within_its_stated_error(self) -> None:
        rng = np.random.default_rng(10)
        n = 3000
        a, b, c = (rng.normal(size=(n, 3)) for _ in range(3))
        width = 10.0 ** rng.uniform(-12, -3, (n, 1))
        c[:600] = (a[:600] + b[:600]) / 2 + width[:600] * rng.normal(
            size=(600, 3)
        )  # slivers
        c[600:1200] = b[600:1200] + width[600:1200] * rng.normal(
            size=(600, 3)
        )  # needles
        c[1200:1300] = (a[1200:1300] + b[1200:1300]) / 2  # no area at all
        offset = rng.uniform(-1e4, 1e4, (n, 1, 3)) * (rng.random((n, 1, 1)) < 0.3)
        a, b, c = a + offset[:, 0], b + offset[:, 0], c + offset[:, 0]
        p = (a + b + c) / 3 + rng.normal(size=(n, 3)) * 10.0 ** rng.uniform(
            -9, 1, (n, 1)
        )
        on = rng.random(n) < 0.2  # some points on the triangle itself
        w = rng.dirichlet((1, 1, 1), size=n)
        p[on] = (w[:, :1] * a + w[:, 1:2] * b + w[:, 2:] * c)[on]
        q, region = closest_points(p, a, b, c, unit_normals(a, b, c))
        d = np.linalg.norm(q - p, axis=1)
        size = np.linalg.norm(p, axis=1) + np.maximum.reduce(
            [np.linalg.norm(x, axis=1) for x in (a, b, c)]
        )
        for k in range(0, n, 3):
            want = math.sqrt(
                distance2(exact(p[k]), exact(a[k]), exact(b[k]), exact(c[k]))
            )
            self.assertLessEqual(abs(d[k] - want), DISTANCE_ERROR * size[k], k)
        self.assertTrue(np.isin(region, range(7)).all())

    def test_normals_far_out_and_very_small(self) -> None:
        """Past 2^200 or within 2^-200 a triangle's normal is still found (its cross product's square would overflow)."""
        a = np.array([[0.0, 0, 0]])
        for scale in (1e200, 1e-200):
            unit = unit_normals(
                a * scale,
                np.array([[1.0, 0, 0]]) * scale,
                np.array([[0.0, 1, 0]]) * scale,
            )
            self.assertEqual(unit.tolist(), [[0.0, 0.0, 1.0]])

    def test_normals_are_unit_and_true_however_thin(self) -> None:
        rng = np.random.default_rng(12)
        n = 2000
        a, b = rng.normal(size=(n, 3)), rng.normal(size=(n, 3))
        c = (a + b) / 2 + 10.0 ** rng.uniform(-14, 0, (n, 1)) * rng.normal(size=(n, 3))
        unit = unit_normals(a, b, c)
        np.testing.assert_allclose(np.linalg.norm(unit, axis=1), 1.0, atol=1e-15)
        for k in range(0, n, 7):
            ea, eb, ec = exact(a[k]), exact(b[k]), exact(c[k])
            u = [eb[i] - ea[i] for i in range(3)]
            v = [ec[i] - ea[i] for i in range(3)]
            cross = [
                u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0],
            ]
            length = math.sqrt(
                float(sum(x * x for x in cross) / max(abs(x) for x in cross) ** 2)
            )
            true = [float(x / max(abs(y) for y in cross)) / length for x in cross]
            self.assertLess(float(np.abs(unit[k] - true).max()), 64 * 2.0**-53, k)

    def test_a_ray_crosses_where_the_plane_says(self) -> None:
        rng = np.random.default_rng(11)
        n = 5000
        a, b, c = (rng.normal(size=(n, 3)) for _ in range(3))
        o = rng.normal(size=(n, 3)) * 4
        d = rng.normal(size=(n, 3))
        d /= np.linalg.norm(d, axis=1)[:, None]
        hit, t, grazed, front = ray_hits(o, d, a, b, c)
        normal = np.cross(b - a, c - a)
        along = np.einsum("ij,ij->i", d, normal)
        t_plane = np.einsum("ij,ij->i", a - o, normal) / along
        x = o + t_plane[:, None] * d
        # Inside by barycentric signs, well clear of the sides.
        signs = np.stack(
            [
                np.einsum("ij,ij->i", np.cross(v1 - x, v2 - x), normal)
                for v1, v2 in ((a, b), (b, c), (c, a))
            ],
            axis=1,
        )
        clear = np.abs(signs).min(axis=1) > 1e-6 * np.linalg.norm(normal, axis=1) ** 2
        inside = (signs > 0).all(axis=1) | (signs < 0).all(axis=1)
        want = inside & (t_plane > 0)
        self.assertEqual(hit[clear].tolist(), want[clear].tolist())
        np.testing.assert_allclose(
            t[clear & want], t_plane[clear & want], rtol=1e-9, atol=1e-12
        )
        self.assertEqual(
            front[clear & want].tolist(), (along[clear & want] < 0).tolist()
        )
        self.assertFalse(grazed[clear].any())


class TheTreeHoldsItsTriangles(unittest.TestCase):
    def test_every_node_s_box_holds_its_triangles_and_every_triangle_is_in_one_leaf(
        self,
    ) -> None:
        t = soup(1, 3000)
        lo, hi = boxes(t)
        tree = Tree.build(lo, hi)
        self.assertEqual(sorted(tree.order.tolist()), list(range(len(t))))
        leaves = np.flatnonzero(tree.left < 0)
        held = np.concatenate(
            [tree.order[tree.start[n] : tree.start[n] + tree.count[n]] for n in leaves]
        )
        self.assertEqual(sorted(held.tolist()), list(range(len(t))))
        for node in range(len(tree.lo)):
            mine = tree.order[tree.start[node] : tree.start[node] + tree.count[node]]
            self.assertTrue(
                (tree.lo[node] <= lo[mine]).all() and (hi[mine] <= tree.hi[node]).all()
            )
            if tree.left[node] >= 0:
                self.assertEqual(
                    tree.count[tree.left[node]] + tree.count[tree.right[node]],
                    tree.count[node],
                )
            else:
                same_centre = np.ptp((lo[mine] + hi[mine]) / 2, axis=0).max() == 0.0
                self.assertTrue(tree.count[node] <= LEAF or same_centre)


class SearchesFindWhatBruteForceFinds(unittest.TestCase):
    def test_nearest(self) -> None:
        t = soup(2, 2500)
        lo, hi = boxes(t)
        tree = Tree.build(lo, hi)
        rng = np.random.default_rng(3)
        points = np.concatenate(
            [
                rng.uniform(-200, 200, size=(150, 3)),
                rng.normal(10, 0.6, size=(150, 3)),
                t[rng.integers(0, len(t), 100), 0],  # on a corner
                t[rng.integers(0, len(t), 100)].mean(axis=1),  # on a face
            ]
        )
        normal = unit_normals(t[:, 0], t[:, 1], t[:, 2])
        found = tree.nearest(points, t[:, 0], t[:, 1], t[:, 2], normal)
        for k, p in enumerate(points):
            q, _ = closest_points(
                np.repeat(p[None], len(t), 0), t[:, 0], t[:, 1], t[:, 2], normal
            )
            d = np.linalg.norm(q - p, axis=1)
            self.assertAlmostEqual(
                found.distance[k], d.min(), delta=1e-15 * (1 + d.min())
            )
            self.assertAlmostEqual(
                float(np.linalg.norm(found.point[k] - p)), found.distance[k], delta=1e-9
            )

    def test_along_misses_no_triangle_a_ray_crosses(self) -> None:
        t = soup(4, 2500)
        lo, hi = boxes(t)
        tree = Tree.build(lo, hi)
        rng = np.random.default_rng(5)
        origins = rng.uniform(-60, 60, size=(300, 3))
        directions = rng.normal(size=(300, 3))
        directions[:40, 1:] = 0.0  # along an axis
        directions[40:80, 2] = 0.0  # in a coordinate plane
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        pairs = list(tree.along(origins, directions, pad=1e-9 * 200))
        ray = np.concatenate([r for r, _ in pairs])
        tri = np.concatenate([k for _, k in pairs])
        found = set(zip(ray.tolist(), tri.tolist(), strict=True))
        self.assertEqual(len(found), len(ray), "each pair once")
        for r in range(len(origins)):
            hit, _, grazed, _ = ray_hits(
                np.repeat(origins[r : r + 1], len(t), 0),
                np.repeat(directions[r : r + 1], len(t), 0),
                t[:, 0],
                t[:, 1],
                t[:, 2],
            )
            for k in np.flatnonzero(hit | grazed):
                self.assertIn((r, int(k)), found)

    def test_within_finds_every_triangle_near_enough(self) -> None:
        # Many boxes, walked down the tree; and few, each tried in turn (FEW).
        for many in (1500, FEW):
            t = soup(7, 1500)[:many]
            lo, hi = boxes(t)
            tree = Tree.build(lo, hi)
            rng = np.random.default_rng(8)
            points = rng.uniform(-60, 60, size=(200, 3))
            radius = rng.uniform(0, 20, size=200)
            found = set()
            for who, tri in tree.within(points, radius):
                found |= set(zip(who.tolist(), tri.tolist(), strict=True))
            for k in range(len(points)):
                gap = np.maximum(np.maximum(lo - points[k], points[k] - hi), 0.0)
                near = np.flatnonzero((gap**2).sum(axis=1) <= radius[k] ** 2)
                self.assertEqual({j for i, j in found if i == k}, set(near.tolist()))

    def test_touching_is_every_pair_of_touching_boxes(self) -> None:
        t = soup(6, 700)
        t[:50] = np.round(t[:50])  # boxes that touch exactly, face to face
        lo, hi = boxes(t)
        tree = Tree.build(lo, hi)
        pairs = list(tree.touching(lo, hi))
        i = np.concatenate([a for a, _ in pairs])
        j = np.concatenate([b for _, b in pairs])
        got = set(zip(i.tolist(), j.tolist(), strict=True))
        self.assertEqual(len(got), len(i), "each pair once")
        meet = np.all((lo[:, None] <= hi[None]) & (lo[None] <= hi[:, None]), axis=2)
        want = {(a, b) for a, b in zip(*np.nonzero(np.triu(meet, 1)), strict=True)}
        self.assertEqual(got, {(int(a), int(b)) for a, b in want})

    def test_one_triangle(self) -> None:
        t = np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]], dtype=np.float64)
        tree = Tree.build(*boxes(t))
        self.assertEqual(sum(len(i) for i, _ in tree.touching(*boxes(t))), 0)
        found = tree.nearest(
            np.array([[0.2, 0.2, 1.0]]),
            t[:, 0],
            t[:, 1],
            t[:, 2],
            unit_normals(t[:, 0], t[:, 1], t[:, 2]),
        )
        self.assertEqual(found.distance.tolist(), [1.0])


if __name__ == "__main__":
    unittest.main()
