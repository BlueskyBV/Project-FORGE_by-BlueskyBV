"""Exact solids (forge_checks.shapes), against their surfaces sampled point by point.

Each solid's surface is traced here from its own definition (a box's six
faces, a frustum's side and caps, a torus's tube), independently of the
module; signed distances, nearest points, normals and the first-order
models near the surface are checked against it.
"""

from __future__ import annotations

import math
import random
import sys
import unittest
from collections.abc import Callable
from pathlib import Path

import numpy as np
from forge_checks.csg import Inter, Minus, Node, Union, bound, pieces
from forge_checks.shapes import (
    INSIDE,
    ON,
    OUTSIDE,
    SINGULAR,
    SURFACE,
    Ball,
    Complement,
    Disc,
    FlatPatch,
    Frame,
    Frustum,
    Halfspace,
    Polygon,
    Prism,
    Revolved,
    Round,
    RoundRect,
    Solid,
    Torus,
    patches,
)
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_meshes import nearest_within

Array = NDArray[np.float64]


def ring(n: int) -> Array:
    return np.linspace(0.0, 2 * math.pi, n, endpoint=False, dtype=np.float64)


def surface_of_prism(p: Prism, step: float) -> Array:
    """The prism's surface from its outline: the outline's edge pushed along, and its two caps."""
    edge = []
    for kind, data in p.shape.pieces():
        if kind == "seg":
            x0, y0, x1, y1 = data
            k = max(int(math.hypot(x1 - x0, y1 - y0) / step), 1)
            edge += [
                (x0 + (x1 - x0) * i / k, y0 + (y1 - y0) * i / k) for i in range(k + 1)
            ]
        else:
            cx, cy, r, start, sweep = data
            k = max(int(r * sweep / step), 4)
            edge += [
                (
                    cx + r * math.cos(start + sweep * i / k),
                    cy + r * math.sin(start + sweep * i / k),
                )
                for i in range(k + 1)
            ]
    e = np.array(edge)
    k = max(int((p.t1 - p.t0) / step), 1)
    found = [
        p.frame.world(e[:, 0], e[:, 1], np.full(len(e), p.t0 + (p.t1 - p.t0) * i / k))
        for i in range(k + 1)
    ]
    lo, hi = p.shape.lo, p.shape.hi
    grid = np.array(
        [
            (a, b)
            for a in np.arange(lo[0], hi[0] + step, step)
            for b in np.arange(lo[1], hi[1] + step, step)
        ]
    )
    grid = grid[p.shape.inside(grid[:, 0], grid[:, 1])]
    for t in (p.t0, p.t1):
        found.append(p.frame.world(grid[:, 0], grid[:, 1], np.full(len(grid), t)))
    return np.concatenate(found)


def surface_of_frustum(f: Frustum, step: float) -> Array:
    found = []
    slant = math.hypot(f.r1 - f.r0, f.t1 - f.t0)
    for i in range(max(int(slant / step), 2) + 1):
        s = i / max(int(slant / step), 2)
        r, t = f.r0 + (f.r1 - f.r0) * s, f.t0 + (f.t1 - f.t0) * s
        k = max(int(2 * math.pi * r / step), 1)
        th = ring(k)
        found.append(f.frame.world(r * np.cos(th), r * np.sin(th), np.full(k, t)))
    for r, t in ((f.r0, f.t0), (f.r1, f.t1)):
        for j in range(int(r / step) + 1):
            rr = j * step
            k = max(int(2 * math.pi * rr / step), 1)
            th = ring(k)
            found.append(f.frame.world(rr * np.cos(th), rr * np.sin(th), np.full(k, t)))
    return np.concatenate(found)


def surface_of_torus(t: Torus, step: float) -> Array:
    """Its tube's circle turned round the axis: only where the circle is off the axis' far side."""
    k1, k2 = int(2 * math.pi * (t.big + t.r) / step), int(2 * math.pi * t.r / step)
    a, b = np.meshgrid(ring(k1), np.linspace(-math.pi, math.pi, k2))
    a, b = a.ravel(), b.ravel()
    rho = t.big + t.r * np.cos(b)
    keep = rho >= 0
    return t.frame.world(
        (rho * np.cos(a))[keep], (rho * np.sin(a))[keep], (t.r * np.sin(b))[keep]
    )


def surface_of_revolved(rv: Revolved, step: float) -> Array:
    """Each side of the outline off the axis, turned round it."""
    found = []
    for _, (x0, y0, x1, y1) in rv.section.pieces():
        if x0 == 0 and x1 == 0:
            continue  # inside the solid
        k = max(int(math.hypot(x1 - x0, y1 - y0) / step), 1)
        for i in range(k + 1):
            rho, z = x0 + (x1 - x0) * i / k, y0 + (y1 - y0) * i / k
            n = max(int(2 * math.pi * rho / step), 3)
            th = ring(n)
            found.append(
                rv.frame.world(rho * np.cos(th), rho * np.sin(th), np.full(n, z))
            )
    return np.concatenate(found)


def random_section(rng: random.Random) -> Polygon:
    """A convex outline off the axis, or touching it at a corner or along a side: a triangle or a quadrilateral."""
    touching = rng.random()
    corners: tuple[tuple[float, float], ...]
    while True:
        rho0, z0 = rng.uniform(0.3, 4), rng.uniform(-3, 2)
        if touching < 0.2:
            rho0 = 0.0  # a corner on the axis (a cone's point, or a disc's middle)
        elif touching < 0.35:
            w, h = rng.uniform(0.3, 3), rng.uniform(0.3, 3)
            corners = (
                (0.0, z0),
                (w, z0 + rng.uniform(-1, 1)),
                (w + rng.uniform(-0.5, 0.5), z0 + h),
                (0.0, z0 + h),
            )
            try:
                return Polygon(corners)  # a side on the axis
            except ValueError:
                continue
        w, h = rng.uniform(0.3, 3), rng.uniform(0.3, 3)
        if rng.random() < 0.5:
            corners = (
                (rho0, z0),
                (rho0 + w, z0 + rng.uniform(-1, 1)),
                (rho0 + rng.uniform(0, w), z0 + h),
            )
        else:
            corners = ((rho0, z0), (rho0 + w, z0), (rho0 + w + rng.uniform(-0.2, 0.2), z0 + h),
                       (rho0 + rng.uniform(-0.2, 0.2), z0 + h * rng.uniform(0.8, 1.2)))  # fmt: skip
        if touching < 0.2:
            corners = tuple((max(x, 0.0), z) for x, z in corners)
        try:
            return Polygon(corners)
        except ValueError:
            continue


def surface_of_ball(b: Ball, step: float) -> Array:
    k = int(4 * math.pi * b.r * b.r / step**2)
    i = np.arange(k) + 0.5
    phi = np.arccos(1 - 2 * i / k)
    theta = math.pi * (1 + 5**0.5) * i
    unit = np.stack(
        [np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1
    )
    return np.asarray(b.centre) + b.r * unit


def random_frame(rng: random.Random) -> Frame:
    axis = rng.choice(
        [
            (0, 0, 1),
            (0, 0, -1),
            (1, 0, 0),
            (0, -1, 0),
            (rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)),
        ]
    )
    return Frame.along(
        (rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)), axis
    )


def random_shape(rng: random.Random) -> Prism:
    kind = rng.choice(["disc", "rect", "rounded", "tab", "polygon"])
    if kind == "disc":
        shape: Disc | RoundRect | Polygon = Disc(rng.uniform(0.5, 5))
    elif kind == "rect":
        shape = RoundRect(rng.uniform(0.5, 5), rng.uniform(0.5, 5))
    elif kind == "rounded":
        h1, h2 = rng.uniform(0.5, 5), rng.uniform(0.5, 5)
        r = rng.uniform(0, min(h1, h2))
        shape = RoundRect(h1, h2, (r, r, 0.0, r))
    elif kind == "tab":
        h2 = rng.uniform(0.5, 4)
        shape = RoundRect(rng.uniform(h2 / 2, 5), h2, (h2, 0.0, 0.0, h2))
    else:
        shape = Polygon(
            ((0.0, 0.0), (rng.uniform(1, 5), 0.0), (0.0, rng.uniform(1, 5)))
        )
    t0 = rng.uniform(-3, 0)
    return Prism(random_frame(rng), shape, t0, t0 + rng.uniform(0.5, 6))


def random_solid(rng: random.Random) -> tuple[Solid, Callable[[float], Array]]:
    kind = rng.choice(["prism", "prism", "frustum", "ball", "torus", "revolved"])
    if kind == "revolved":
        rv = Revolved(random_frame(rng), random_section(rng))
        return rv, lambda step: surface_of_revolved(rv, step)
    if kind == "prism":
        p = random_shape(rng)
        return p, lambda step: surface_of_prism(p, step)
    if kind == "frustum":
        t0 = rng.uniform(-3, 0)
        f = Frustum(
            random_frame(rng),
            t0,
            t0 + rng.uniform(0.5, 6),
            rng.choice([0.0, rng.uniform(0.5, 4)]),
            rng.uniform(0.5, 4),
        )
        return f, lambda step: surface_of_frustum(f, step)
    if kind == "ball":
        b = Ball(
            (rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)),
            rng.uniform(0.5, 5),
        )
        return b, lambda step: surface_of_ball(b, step)
    big = rng.uniform(1, 5)
    if rng.random() < 0.3:
        # The tube crosses the axis (a rounding nearly as big as its rim), or just meets it.
        r = rng.uniform(0.5, 3)
        big = rng.choice([r * rng.uniform(0.05, 0.95), r, 0.0])
        t = Torus(random_frame(rng), big, r)
    else:
        t = Torus(random_frame(rng), big, rng.uniform(0.2, big * 0.9))
    return t, lambda step: surface_of_torus(t, step)


class SignedDistances(unittest.TestCase):
    def test_against_the_surface_point_by_point(self) -> None:
        rng = random.Random(11)
        for _ in range(60):
            solid, surface = random_solid(rng)
            step = 0.04
            cloud = surface(step)
            points = np.array(
                [[rng.uniform(-12, 12) for _ in range(3)] for _ in range(80)]
            )
            d = solid.signed_distance(points)
            for p, dp in zip(points, d, strict=True):
                truth = float(np.min(np.linalg.norm(cloud - p, axis=1)))
                self.assertLessEqual(abs(abs(float(dp)) - truth), step, (solid, p))

    def test_nearest_points_are_on_the_surface_and_as_far_as_it_says(self) -> None:
        rng = random.Random(12)
        for _ in range(80):
            solid, _ = random_solid(rng)
            points = np.array(
                [[rng.uniform(-12, 12) for _ in range(3)] for _ in range(60)]
            )
            q, n = solid.nearest(points)
            d = solid.signed_distance(points)
            np.testing.assert_allclose(
                np.abs(solid.signed_distance(q)), 0.0, atol=1e-12
            )
            np.testing.assert_allclose(
                np.linalg.norm(points - q, axis=1), np.abs(d), atol=1e-12
            )
            np.testing.assert_allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-12)
            # The normal points out of the solid: from outside, straight at the point; from
            # inside, straight back from it; and a little way along it is outside.
            away = (points - q) / np.where(d != 0, np.abs(d), 1.0)[:, None]
            np.testing.assert_allclose(away[d > 1e-9], n[d > 1e-9], atol=1e-9)
            np.testing.assert_allclose(away[d < -1e-9], -n[d < -1e-9], atol=1e-9)
            self.assertTrue(np.all(solid.signed_distance(q + 1e-6 * n) > 0), solid)

    def test_one_lipschitz(self) -> None:
        rng = random.Random(13)
        for _ in range(60):
            solid, _ = random_solid(rng)
            a = np.array([[rng.uniform(-10, 10) for _ in range(3)] for _ in range(200)])
            b = a + np.array([[rng.gauss(0, 1) for _ in range(3)] for _ in range(200)])
            gap = np.abs(solid.signed_distance(a) - solid.signed_distance(b))
            self.assertTrue(
                np.all(gap <= np.linalg.norm(a - b, axis=1) * (1 + 1e-12) + 1e-12)
            )

    def test_worked_cases(self) -> None:
        cone = Frustum(
            Frame.along((0, 0, 0), (0, 0, 1)), 0.0, 4.0, 3.0, 0.0
        )  # 3 wide at the base, to a point 4 up
        # A point straight out from the middle of the slant, 1 mm off it: the slant is a 3-4-5 line.
        mid = np.array([[1.5 + 0.8, 0.0, 2.0 + 0.6]])
        self.assertAlmostEqual(float(cone.signed_distance(mid)[0]), 1.0, places=12)
        self.assertAlmostEqual(
            float(cone.signed_distance(np.array([[0.0, 0.0, 5.0]]))[0]), 1.0, places=12
        )
        torus = Torus(Frame.along((1, 1, 1), (1, 0, 0)), 5.0, 1.0)
        self.assertAlmostEqual(
            float(torus.signed_distance(np.array([[1.0, 1.0, 1.0]]))[0]), 4.0, places=12
        )
        self.assertAlmostEqual(
            float(torus.signed_distance(np.array([[4.0, 6.0, 1.0]]))[0]),
            math.hypot(3, 0) - 1,
            places=12,
        )
        rod = Round(Frame.along((0, 0, 0), (0, 1, 0)), 2.0)
        self.assertEqual(
            rod.signed_distance(np.array([[3.0, 100.0, 4.0]])).tolist(), [3.0]
        )
        half = Halfspace((0, 0, 1), (0, 0, 2))
        self.assertEqual(
            half.signed_distance(np.array([[5.0, 5.0, 3.0]])).tolist(), [2.0]
        )
        self.assertEqual(
            Complement(half).signed_distance(np.array([[5.0, 5.0, 3.0]])).tolist(),
            [-2.0],
        )

    def test_what_can_t_be_a_solid(self) -> None:
        frame = Frame.along((0, 0, 0), (0, 0, 1))
        for bad in (
            lambda: Disc(0),
            lambda: RoundRect(1, 1, (1.5, 0, 0, 1.5)),
            lambda: Polygon(((0, 0), (0, 1), (1, 0))),  # clockwise
            lambda: Prism(frame, Disc(1), 1.0, 1.0),
            lambda: Frustum(frame, 0.0, 1.0, 0.0, 0.0),
            lambda: Torus(frame, -1.0, 1.0),
            lambda: Torus(frame, 1.0, 0.0),
            lambda: Revolved(
                frame, Polygon(((-0.1, 0), (1, 0), (1, 1)))
            ),  # a corner across the axis
            lambda: Ball((0, 0, 0), -1),
            lambda: Frame.along((0, 0, 0), (0, 0, 0)),
        ):
            with self.assertRaises(ValueError):
                bad()


def random_node(rng: random.Random, depth: int) -> Node:
    """A union, intersection or difference of random solids, ``depth`` levels deep at most."""
    if depth == 0 or rng.random() < 0.3:
        return random_solid(rng)[0]
    kind = rng.choice(["union", "inter", "minus"])
    if kind == "minus":
        return Minus(random_node(rng, depth - 1), random_node(rng, depth - 1))
    parts = tuple(random_node(rng, depth - 1) for _ in range(rng.randint(2, 3)))
    return Union(parts) if kind == "union" else Inter(parts)


class MadeOfSolids(unittest.TestCase):
    """Solids made of solids (forge_checks.csg): their boxes, and their bounds cut short by them."""

    def test_every_solid_is_in_its_box(self) -> None:
        rng = random.Random(21)
        for _ in range(60):
            solid, surface = random_solid(rng)
            cloud = surface(0.1)
            lo, hi = np.array(solid.lo), np.array(solid.hi)
            self.assertTrue(np.all((cloud >= lo - 1e-9) & (cloud <= hi + 1e-9)), solid)
            points = rng_points(rng, 400)
            inside = points[solid.signed_distance(points) <= 0]
            self.assertTrue(np.all((inside >= lo) & (inside <= hi)), solid)

    def test_a_union_or_intersection_is_of_something(self) -> None:
        for make in (Union, Inter):
            with self.assertRaises(ValueError):
                make(())

    def test_a_node_s_box_holds_it(self) -> None:
        rng = random.Random(22)
        for _ in range(80):
            node = random_node(rng, 3)
            points = rng_points(rng, 600)
            inside = points[bound(node, points) <= 0]
            lo, hi = np.array(node.lo), np.array(node.hi)
            self.assertTrue(np.all((inside >= lo) & (inside <= hi)), node)

    def test_bounds_cut_short_by_boxes_are_still_bounds(self) -> None:
        """The sign is the exact bound's, and the ball as big as the value round a point holds no surface."""
        rng = random.Random(23)
        directions = np.array([[rng.gauss(0, 1) for _ in range(3)] for _ in range(24)])
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        for _ in range(80):
            node = random_node(rng, 3)
            points = rng_points(rng, 300)
            exact = bound(node, points)
            for enough in (1e-9, 0.5, 3.0):
                cut = bound(node, points, enough)
                self.assertTrue(np.array_equal(np.sign(cut), np.sign(exact)), node)
                # Every point of the ball the value says is clear is on the point's side.
                scale = np.array([[rng.random()] for _ in range(len(directions))])
                ball = (
                    points[:, None, :]
                    + (0.999 * np.abs(cut))[:, None, None]
                    * (scale * directions)[None, :, :]
                )
                sides = np.sign(bound(node, ball.reshape(-1, 3))).reshape(
                    len(points), -1
                )
                held = (sides == np.sign(cut)[:, None]) | (cut == 0)[:, None]
                self.assertTrue(np.all(held), (node, points[~held.all(axis=1)][:3]))

    def test_every_point_of_a_node_s_surface_is_in_one_of_its_pieces(self) -> None:
        """The boxes round its solids, each cut to where the rest of the node lets its surface be the node's (forge_checks.csg.pieces): every surface point found between two points a sign apart lies in one."""
        rng = random.Random(24)
        found = 0
        for _ in range(80):
            node = random_node(rng, 3)
            boxes = pieces(node)
            lo = np.array([b[0] for b in boxes]).reshape(-1, 3)
            hi = np.array([b[1] for b in boxes]).reshape(-1, 3)
            points = rng_points(rng, 4000)
            way = np.array([[rng.gauss(0, 1) for _ in range(3)] for _ in range(4000)])
            way /= np.linalg.norm(way, axis=1)[:, None]
            step = 0.3
            crossed = np.sign(bound(node, points)) != np.sign(
                bound(node, points + step * way)
            )
            for p in points[crossed]:
                found += 1
                near = np.all((p >= lo - step) & (p <= hi + step), axis=1)
                self.assertTrue(near.any(), (node, p))
        self.assertGreater(found, 200)

    def test_a_rounding_s_pieces_run_along_its_edges(self) -> None:
        """A body's edges' strips, cut from the body: their pieces are the strips, not the body."""
        body = Prism.box((0.0, 0.0, 0.0), (100.0, 60.0, 20.0))
        strips = Union(tuple(Prism.box((x - 0.5, y - 0.5, 0.0), (x + 0.5, y + 0.5, 20.0))
                             for x in (0.0, 100.0) for y in (0.0, 60.0)))  # fmt: skip
        found = pieces(Inter((strips, body)))
        self.assertEqual(len(found), 8)
        self.assertTrue(
            all(
                np.prod(np.subtract(top, low)) <= 1.0 * 1.0 * 20.0 for low, top in found
            )
        )


def rng_points(rng: random.Random, n: int) -> Array:
    return np.array([[rng.uniform(-12, 12) for _ in range(3)] for _ in range(n)])


class Found(unittest.TestCase):
    """What review found, kept found."""

    def test_a_spindle_torus_s_depth_is_to_its_poles(self) -> None:
        """Inside a spindle torus near its axis the surface's nearest point is a pole: its depth is the distance there."""
        torus = Torus(Frame.along((0, 0, 0), (0, 0, 1)), 0.5, 1.0)
        rng = np.random.default_rng(3)
        points = np.concatenate(
            [rng.uniform(-1.6, 1.6, size=(4000, 3)), [[0.0, 0, 0], [0.1, 0, 0.2]]]
        )
        q, _ = torus.nearest(points)
        np.testing.assert_allclose(
            np.abs(torus.signed_distance(points)),
            np.linalg.norm(points - q, axis=1),
            atol=1e-12,
        )
        self.assertAlmostEqual(
            float(torus.signed_distance(np.zeros((1, 3)))[0]),
            -math.sqrt(0.75),
            places=12,
        )

    def test_a_frame_a_hair_off_an_axis_is_square(self) -> None:
        f = Frame.along((0, 0, 0), (4e-8, 0, 1))
        m = np.array([f.u, f.v, f.w])
        np.testing.assert_allclose(m @ m.T, np.eye(3), atol=1e-15)
        # A half-space a hair off a frame plane isn't bounded as if it were on it.
        h = Halfspace((0, 0, 0), (4e-8, 0, 1))
        self.assertEqual(h.hi[2], math.inf)

    def test_a_tiny_corner_s_facet_faces_out(self) -> None:
        """A corner rounded 1e-10: a point on the top side beside it has no facet facing in."""
        box = Prism(
            Frame.along((0, 0, 0), (0, 0, 1)),
            RoundRect(5.0, 3.0, (1e-10, 0, 0, 0)),
            0.0,
            2.0,
        )
        local = box.local([5 - 6e-10, 3.0, 1.0])
        # Its facets: the top side's, the side's beside it, the corner's (out between them).
        self.assertTrue(
            all(float(n[0]) >= -1e-12 and float(n[1]) >= -1e-12 for n in local.normals)
        )


class Frames(unittest.TestCase):
    def test_round_a_frame_axis_the_first_two_axes_turn_as_place_md_says(self) -> None:
        def axes(f: Frame) -> tuple[tuple[float, ...], ...]:
            return (f.u, f.v, f.w)

        self.assertEqual(
            axes(Frame.along((0, 0, 0), (0, 0, 1))),
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        )
        self.assertEqual(
            axes(Frame.along((0, 0, 0), (1, 0, 0))),
            ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
        )
        self.assertEqual(
            axes(Frame.along((0, 0, 0), (0, 1, 0))),
            ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        )

    def test_every_frame_is_right_handed_and_orthonormal(self) -> None:
        rng = random.Random(14)
        for _ in range(200):
            f = random_frame(rng)
            m = np.array([f.u, f.v, f.w])
            np.testing.assert_allclose(m @ m.T, np.eye(3), atol=1e-12)
            self.assertAlmostEqual(float(np.linalg.det(m)), 1.0, places=12)


class NearTheSurface(unittest.TestCase):
    """The facets at a point, and the first-order model they make."""

    def test_faces_edges_and_corners_of_a_box(self) -> None:
        box = Prism.box((0, 0, 0), (10, 4, 2))
        self.assertEqual(len(box.facets((5, 2, 2)) or []), 1)
        self.assertEqual(len(box.facets((10, 2, 2)) or []), 2)
        self.assertEqual(len(box.facets((10, 4, 2)) or []), 3)
        self.assertEqual(box.facets((5, 2, 1)), [])
        self.assertEqual(box.local((5, 2, 1)).where, INSIDE)
        self.assertEqual(box.local((5, 2, 3)).where, OUTSIDE)
        self.assertEqual(box.local((5, 2, 2 + 5e-10)).where, SURFACE)

    def test_a_cone_s_apex_is_singular(self) -> None:
        cone = Frustum(Frame.along((0, 0, 0), (0, 0, 1)), 0.0, 4.0, 3.0, 0.0)
        self.assertIsNone(cone.facets((0, 0, 4)))
        self.assertEqual(cone.local((0, 0, 4)).where, SINGULAR)
        self.assertEqual(len(cone.facets((3, 0, 0)) or []), 2)  # the base's rim

    def test_the_first_order_model_says_what_is_just_off_the_point(self) -> None:
        rng = random.Random(15)
        checked = 0
        for _ in range(150):
            solid, surface = random_solid(rng)
            if rng.random() < 0.3:
                solid = Complement(solid)
            cloud = surface(0.3)
            for p in cloud[rng.sample(range(len(cloud)), min(len(cloud), 12))]:
                local = solid.local(p)
                if local.where == SINGULAR:
                    continue
                directions = np.array(
                    [[rng.gauss(0, 1) for _ in range(3)] for _ in range(40)]
                )
                directions /= np.linalg.norm(directions, axis=1)[:, None]
                if local.where == SURFACE:
                    # Not along a facet's plane, where only the curvature decides.
                    keep = (
                        np.min(
                            np.abs(np.stack([directions @ n for n in local.normals])),
                            axis=0,
                        )
                        > 0.05
                    )
                    directions = directions[keep]
                predicted = local.toward(directions)
                actual = solid.signed_distance(p + 1e-5 * directions) < 0
                self.assertTrue(np.array_equal(predicted, actual), (solid, p))
                checked += len(directions)
        self.assertGreater(checked, 10000)


class Patches(unittest.TestCase):
    """Each solid's smooth pieces: on its surface, facing out, covering all of it, and measured in lengths."""

    def test_a_plane_s_piece_is_all_of_it_in_the_box(self) -> None:
        """A plane on any face of the box, through it, or a hair from a corner: its piece is the whole cut."""
        lo, hi = (0.0, 0.0, 0.0), (2.0, 3.0, 5.0)
        cases = [  # (point, normal, area of the cut)
            ((2, 3, 5), (0, 0, 1), 6.0), ((2, 3, 5), (1, 0, 0), 15.0), ((2, 3, 5), (0, 1, 0), 10.0),
            ((0, 0, 0), (0, 0, -1), 6.0), ((0, 0, 0), (-1, 0, 0), 15.0), ((0, 0, 0), (0, -1, 0), 10.0),
            ((1, 1.5, 2.5), (0, 0, 1), 6.0), ((2, 3, 5 - 1e-11), (0, 0, 1), 6.0),
            ((1, 1.5, 2.5), (0, 1e-3, 1), 6 * math.sqrt(1 + 1e-6)),
            ((1, 1.5, 2.5), (1, 1, 0), 2 * 5 * math.sqrt(2)),
        ]  # fmt: skip
        for point, normal, area in cases:
            with self.subTest(point=point, normal=normal):
                (piece,) = patches(Halfspace(point, normal), lo, hi)
                assert isinstance(piece, FlatPatch) and isinstance(piece.shape, Polygon)
                c = np.array(piece.shape.corners)
                found = 0.5 * abs(
                    c[:, 0] @ np.roll(c[:, 1], -1) - c[:, 1] @ np.roll(c[:, 0], -1)
                )
                self.assertAlmostEqual(found, area, delta=1e-6 * area)
        self.assertEqual(patches(Halfspace((2, 3, 5), (1, 1, 1)), lo, hi), [])

    def test_every_solid_s_pieces(self) -> None:
        rng = random.Random(31)
        nrng = np.random.default_rng(31)
        for _ in range(60):
            solid, surface = random_solid(rng)
            if rng.random() < 0.2:
                solid = Complement(solid)
            pieces = patches(solid, (-20.0, -20.0, -20.0), (20.0, 20.0, 20.0))
            fine = []
            for piece in pieces:
                su, sv = piece.size
                u = nrng.uniform(0, su, 2000)
                v = nrng.uniform(0, sv, 2000)
                q, n, valid = piece.at(u, v)
                q, n, u, v = q[valid], n[valid], u[valid], v[valid]
                d = solid.signed_distance
                self.assertLessEqual(float(np.abs(d(q)).max(initial=0)), 1e-9, piece)
                # Out along the normal, out of the solid; back along it, in: where the
                # surface is the only one near along the normal both ways.
                ahead, back = d(q + 1e-3 * n), d(q - 1e-3 * n)
                clear = (np.abs(np.abs(ahead) - 1e-3) < 1e-9) & (
                    np.abs(np.abs(back) - 1e-3) < 1e-9
                )
                self.assertTrue(np.all(ahead[clear] > 0), piece)
                self.assertTrue(np.all(back[clear] < 0), piece)
                self.assertGreater(int(clear.sum()), len(q) // 4, piece)
                # A step of a parameter moves the point no farther than the step.
                du = nrng.uniform(-0.05, 0.05, len(u))
                dv = nrng.uniform(-0.05, 0.05, len(u))
                inside = (u + du >= 0) & (u + du <= su) & (v + dv >= 0) & (v + dv <= sv)
                q2 = piece.at((u + du)[inside], (v + dv)[inside])[0]
                moved = np.linalg.norm(q2 - q[inside], axis=1)
                self.assertTrue(
                    np.all(moved <= np.hypot(du, dv)[inside] * (1 + 1e-9) + 1e-12),
                    piece,
                )
                # A point's foot on the piece is on it, and no farther than any of its points.
                for x in nrng.uniform(-8, 8, size=(10, 3)):
                    f = piece.foot(x)
                    self.assertLessEqual(abs(float(d(f[None, :])[0])), 1e-9)
                    self.assertLessEqual(
                        float(np.linalg.norm(f - x)),
                        float(np.linalg.norm(q - x, axis=1).min()) + 1e-9,
                    )
                gu, gv = np.meshgrid(
                    np.linspace(0, su, max(int(su / 0.05), 2)),
                    np.linspace(0, sv, max(int(sv / 0.05), 2)),
                )
                q, _, valid = piece.at(gu.ravel(), gv.ravel())
                fine.append(q[valid])
            # Together they cover the surface.
            cloud = surface(0.1)
            gap = nearest_within(np.concatenate(fine), cloud, 0.2)
            self.assertLessEqual(float(gap.max()), 0.1, solid)


def pieces_hold(
    solid: Solid, origin: Array, direction: Array, length: float
) -> list[str]:
    """Between the places a line meets the solid's surface: the solid's side is the same all along each piece.

    The side of a point: in, out, or on (within 1e-9 of the surface). The
    line is sampled densely within each piece, but not within 1e-3 of its
    ends: where a line grazes a surface, the points within 1e-9 of it reach
    some way along the line either side of the place it touches.
    """
    found = solid.crossings(origin[None, :], direction[None, :])[0]
    t = np.sort(found[np.isfinite(found) & (found > 0) & (found < length)])
    ends = np.concatenate([[0.0], t, [length]])
    wrong = []
    for k in range(len(ends) - 1):
        a, b = ends[k], ends[k + 1]
        if b - a < 3e-3:
            continue
        u = np.linspace(a + 1e-3, b - 1e-3, 2001)
        d = solid.signed_distance(origin + u[:, None] * direction)
        side = np.where(np.abs(d) <= 1e-9, 0, np.sign(d))
        if len(set(side.tolist())) > 1:
            wrong.append(
                f"{type(solid).__name__}: piece {a:.6g}..{b:.6g} along {origin} {direction} is {sorted(set(side.tolist()))}"
            )
    return wrong


class Crossings(unittest.TestCase):
    """Where lines meet each solid's surface: between those places, nothing changes."""

    def test_random_lines(self) -> None:
        rng = random.Random(21)
        nrng = np.random.default_rng(21)
        wrong: list[str] = []
        lines = 0
        for _ in range(60):
            solid, _ = random_solid(rng)
            if rng.random() < 0.25:
                solid = Complement(solid)
            origins = nrng.uniform(-9, 9, size=(40, 3))
            directions = nrng.normal(size=(40, 3))
            directions[:15] = np.eye(3)[nrng.integers(0, 3, 15)]
            directions /= np.linalg.norm(directions, axis=1)[:, None]
            for o, d in zip(origins, directions, strict=True):
                wrong += pieces_hold(solid, o, d, 30.0)
                lines += 1
        for solid in (
            Round(Frame.along((1, 0, 0), (1, 1, 0)), 2.0),
            Halfspace((0, 0, 1), (0.3, -0.2, 1)),
        ):
            for o, d in zip(
                nrng.uniform(-9, 9, size=(100, 3)),
                nrng.normal(size=(100, 3)),
                strict=True,
            ):
                wrong += pieces_hold(solid, o, d / np.linalg.norm(d), 30.0)
        self.assertEqual(wrong[:5], [])
        self.assertGreater(lines, 2000)

    def test_lines_on_and_along_surfaces(self) -> None:
        """Lines in a face, along a round side, along a cone's slope, through its apex, grazing a ball."""
        box = Prism.box((0, 0, 0), (10, 4, 2))
        rod = Prism(Frame.along((0, 0, 0), (0, 0, 1)), Disc(3.0), 0.0, 10.0)
        cone = Frustum(Frame.along((0, 0, 0), (0, 0, 1)), 0.0, 4.0, 3.0, 0.0)
        cup = Frustum(Frame.along((0, 0, 0), (0, 0, 1)), 0.0, 4.0, 1.0, 3.0)
        ball = Ball((0, 0, 0), 2.0)
        torus = Torus(Frame.along((0, 0, 0), (0, 0, 1)), 5.0, 1.0)
        slope = np.array([-3.0, 0.0, 4.0]) / 5.0
        cases = [
            (box, (-5, 2, 2), (1, 0, 0)),  # in the top face
            (box, (-5, 4, 2), (1, 0, 0)),  # along an edge
            (box, (5, 4, -3), (0, 0, 1)),  # in a side face, across the caps
            (rod, (3, 0, -5), (0, 0, 1)),  # along the round side
            (rod, (-5, 3, 4), (1, 0, 0)),  # touching it
            (cone, (3, 0, 0), tuple(slope)),  # along the slope to the apex and on
            (cone, (3, 0, 0) - 2 * slope, tuple(slope)),
            (cone, (0, 0, -3), (0, 0, 1)),  # through the apex along the axis
            (
                cone,
                (-2, -1, 2),
                tuple(np.array([2.0, 1.0, 2.0]) / 3.0),
            ),  # through the apex across
            (cup, (1, 0, -2), (0, 0, 1)),  # through the rim of the small end
            (ball, (-5, 2, 0), (1, 0, 0)),  # grazing
            (torus, (-9, 6, 0), (1, 0, 0)),  # grazing the outside
            (torus, (-9, 4, 1), (1, 0, 0)),  # along the top
            (torus, (-9, 0, 0), (1, 0, 0)),  # through the middle
        ]
        wrong: list[str] = []
        for solid, origin, direction in cases:
            o, d = np.array(origin, dtype=float), np.array(direction, dtype=float)
            d /= np.linalg.norm(d)
            for s in (solid, Complement(solid)):
                wrong += pieces_hold(s, o, d, 20.0)
        self.assertEqual(wrong, [])

    def test_a_place_a_line_crosses_at_is_on_its_root(self) -> None:
        """Where the line passes from one side to the other, along a line steeper than _STEEP: within ON of the place, not just of the surface (one step of Newton's method left 74 of these 4389 up to 8e-8 mm off, a sliver between them and the same place found exactly)."""
        rng = random.Random(21)
        nrng = np.random.default_rng(21)
        off: list[Array] = []
        for _ in range(60):
            solid, _ = random_solid(rng)
            o = nrng.uniform(-9, 9, size=(400, 3))
            d = nrng.normal(size=(400, 3))
            d /= np.linalg.norm(d, axis=1)[:, None]
            found = solid.crossings(o, d)
            line, column = np.nonzero(np.isfinite(found))
            t = found[line, column]
            before, after = (
                np.sign(solid.signed_distance(o[line] + (t + s)[:, None] * d[line]))
                for s in (-1e-5, 1e-5)
            )
            at = o[line] + t[:, None] * d[line]
            _, normal = solid.nearest(at)
            rate = np.abs(np.einsum("ij,ij->i", normal, d[line]))
            crossed = (before * after < 0) & (rate >= 1e-3)
            off.append(np.abs(solid.signed_distance(at[crossed])) / rate[crossed])
        found_off = np.concatenate(off)
        self.assertGreater(len(found_off), 4000)
        self.assertLessEqual(float(found_off.max()), ON)

    def test_where_a_line_meets_a_box(self) -> None:
        box = Prism.box((0, 0, 0), (10, 4, 2))
        found = box.crossings(
            np.array([[-5.0, 2, 1], [-5.0, 9, 1]]), np.array([[1.0, 0, 0], [1.0, 0, 0]])
        )
        self.assertEqual(sorted(found[0][np.isfinite(found[0])].tolist()), [5.0, 15.0])
        self.assertTrue(np.all(np.isnan(found[1])))

    def test_a_line_along_a_revolution_s_axis_meets_its_flat_ends(self) -> None:
        """Generated part 61's pulley: a flat side is a plane, met once, exactly (as a square, its double root came out a micrometre off, and was dropped)."""
        hub = Revolved(
            Frame((0.0, 39.2925, 4.8395), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            Polygon(((0.0, 10.186), (1.077, 5.043), (2.53, 5.043), (3.049, 5.562), (3.049, 9.667),
                     (2.53, 10.186))),
        )  # fmt: skip
        found = hub.crossings(
            np.array([[-1.30180525, -39.96405525, 4.68769475]]),
            np.array([[0.0, 1.0, 0.0]]),
        )
        met = sorted(found[0][np.isfinite(found[0])].tolist())
        self.assertEqual(len(met), 2, met)
        for t, height in zip(met, (5.043, 10.186), strict=True):
            self.assertAlmostEqual(t, 39.96405525 + 39.2925 + height, delta=1e-9)


def circle_pieces_hold(
    solid: Solid, centre: Array, u: Array, v: Array, radius: float
) -> list[str]:
    """Between the places a circle meets the solid's surface: the solid's side is the same all along each piece.

    As :func:`pieces_hold`, round the circle: sampled densely within each
    piece, but not within 1e-3 mm of its ends.
    """
    found = solid.circle_crossings(centre, u, v, radius)
    ends = np.concatenate([[0.0], found, [2 * math.pi]])
    wrong = []
    margin = 1e-3 / radius
    for k in range(len(ends) - 1):
        a, b = ends[k], ends[k + 1]
        if b - a < 3 * margin:
            continue
        t = np.linspace(a + margin, b - margin, 4001)
        d = solid.signed_distance(
            centre + radius * (np.cos(t)[:, None] * u + np.sin(t)[:, None] * v)
        )
        side = np.where(np.abs(d) <= 1e-9, 0, np.sign(d))
        if len(set(side.tolist())) > 1:
            wrong.append(
                f"{type(solid).__name__}: piece {a:.6g}..{b:.6g} round {centre} {u} {v} r {radius} "
                f"is {sorted(set(side.tolist()))}"
            )
    return wrong


def square_pair(rng: np.random.Generator) -> tuple[Array, Array]:
    """Two unit directions at right angles, at random."""
    u = rng.normal(size=3)
    u /= np.linalg.norm(u)
    v = rng.normal(size=3)
    v -= (v @ u) * u
    return u, v / np.linalg.norm(v)


class CircleCrossings(unittest.TestCase):
    """Where circles meet each solid's surface: between those places, nothing changes."""

    def test_random_circles(self) -> None:
        rng = random.Random(23)
        nrng = np.random.default_rng(23)
        wrong: list[str] = []
        circles = 0
        for _ in range(60):
            solid, _ = random_solid(rng)
            if rng.random() < 0.25:
                solid = Complement(solid)
            for k in range(20):
                if k < 6:
                    # Round a frame axis, as the edges roundings follow are.
                    e = np.eye(3)[nrng.integers(0, 3, 2)]
                    u, v = e[0], np.cross(np.eye(3)[nrng.integers(0, 3)], e[0])
                    if np.linalg.norm(v) == 0:
                        continue
                    v /= np.linalg.norm(v)
                else:
                    u, v = square_pair(nrng)
                centre = nrng.uniform(-6, 6, size=3)
                wrong += circle_pieces_hold(
                    solid, centre, u, v, float(nrng.uniform(0.5, 9))
                )
                circles += 1
        self.assertEqual(wrong[:5], [])
        self.assertGreater(circles, 1000)

    def test_circles_on_and_along_surfaces(self) -> None:
        """Circles in a face across its outline, round a side, on a ball, a torus, a cone, through an apex, touching."""
        z = np.array([0.0, 0.0, 1.0])
        x, y = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
        box = Prism.box((0, 0, 0), (10, 4, 2))
        rod = Prism(Frame.along((0, 0, 0), (0, 0, 1)), Disc(3.0), 0.0, 10.0)
        tile = Prism(
            Frame.along((0, 0, 0), (0, 0, 1)),
            RoundRect(5.0, 3.0, (1.5, 1.5, 1.5, 1.5)),
            0.0,
            2.0,
        )
        cone = Frustum(Frame.along((0, 0, 0), (0, 0, 1)), 0.0, 4.0, 3.0, 0.0)
        cup = Frustum(Frame.along((0, 0, 0), (0, 0, 1)), 0.0, 4.0, 1.0, 3.0)
        ball = Ball((0, 0, 0), 2.0)
        torus = Torus(Frame.along((0, 0, 0), (0, 0, 1)), 5.0, 1.0)
        spindle = Torus(Frame.along((0, 0, 0), (0, 0, 1)), 0.5, 1.0)
        ring = Revolved(
            Frame.along((0, 0, 0), (0, 0, 1)),
            Polygon(((2.0, 0.0), (4.0, 0.0), (4.0, 1.0), (2.0, 2.0))),
        )
        floor = Halfspace((0, 0, 0), (0, 0, 1))
        o = np.zeros(3)
        cases = [
            (
                box,
                np.array([5.0, 2, 2]),
                x,
                y,
                3.0,
            ),  # in the top face, across its long sides
            (
                box,
                np.array([0.0, 0, 2]),
                x,
                y,
                1.0,
            ),  # in the top face, round its corner
            (box, np.array([5.0, 4, 1]), x, z, 1.5),  # in a side face, across both caps
            (box, np.array([5.0, 4, 1]), x, z, 0.5),  # in a side face, all within it
            (rod, np.array([0.0, 0, 4]), x, y, 3.0),  # round the round side
            (rod, np.array([0.0, 0, 10]), x, y, 3.0),  # round the top rim
            (rod, np.array([0.0, 0, 10]), x, y, 2.0),  # in the top face
            (rod, np.array([3.0, 0, 5]), y, z, 2.0),  # touching it along its side
            (
                tile,
                np.array([0.0, 0, 2]),
                x,
                y,
                4.0,
            ),  # in the top face, across the rounded corners
            (tile, np.array([3.5, 1.5, 2]), x, y, 1.5),  # on a corner's round
            (cone, o, x, y, 3.0),  # round the base rim
            (cone, np.array([0.0, 0, 2]), x, y, 1.5),  # round the slope
            (cone, np.array([0.0, 0, 4]), x, z, 1.0),  # through the apex
            (cup, np.array([0.0, 0, 4]), x, y, 3.0),  # round the wide rim
            (ball, o, x, y, 2.0),  # its equator
            (ball, np.array([0.0, 0, 1]), x, y, math.sqrt(3)),  # a parallel
            (ball, np.array([0.0, 0, 3]), x, z, 1.0),  # touching it
            (torus, np.array([0.0, 0, 1]), x, y, 5.0),  # along its top
            (torus, o, x, y, 6.0),  # round its outside
            (torus, np.array([5.0, 0, 0]), x, z, 1.0),  # its tube's own circle
            (torus, np.array([5.0, 0, 0]), y, z, 1.0),  # across its tube
            (spindle, o, x, z, 1.2),  # through its poles' cone
            (ring, np.array([0.0, 0, 1]), x, y, 3.0),  # round its slope
            (ring, o, x, y, 3.0),  # in its floor
            (ring, np.array([3.0, 0, 0]), x, z, 1.0),  # across it
            (floor, np.array([1.0, 2, 0]), x, y, 3.0),  # in its plane
        ]
        wrong: list[str] = []
        for solid, centre, u, v, r in cases:
            for s in (solid, Complement(solid)):
                wrong += circle_pieces_hold(s, centre, u, v, r)
        self.assertEqual(wrong, [])

    def test_where_a_circle_meets_a_box(self) -> None:
        box = Prism.box((0, 0, 0), (10, 4, 2))
        found = box.circle_crossings(
            np.array([5.0, 2, 2]), np.array([1.0, 0, 0]), np.array([0.0, 1, 0]), 4.0
        )
        expected = sorted(
            a % (2 * math.pi)
            for a in (
                math.asin(0.5),
                math.pi - math.asin(0.5),
                -math.asin(0.5),
                math.pi + math.asin(0.5),
            )
        )
        self.assertEqual(len(found), 4)
        self.assertLess(float(np.max(np.abs(found - expected))), 1e-12)


if __name__ == "__main__":
    unittest.main()
