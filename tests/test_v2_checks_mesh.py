"""V2 stage 2: the mesh view (forge_checks.mesh), on meshes whose answers are known exactly.

- a box, whose sides, distances, crossings and volume are known in closed
  form, including at points exactly on its faces, edges and corners;
- convex hulls of random points, whose inside is decided exactly by the
  sign of each face's plane;
- solids with holes, hollows and islands made by manifold3d, whose
  topology is known, and on which the two ways of telling a point's side
  (the normal at its nearest point, and three rays) must agree everywhere,
  above all next to edges and corners;
- every mesh-integrity mutant: each must be found unsound, by the count
  that names its fault, and then classify nothing.
"""

from __future__ import annotations

import functools
import math
import unittest
from typing import Any

import numpy as np
from forge_checks.mesh import ON_BAND, Mesh, MeshView, box_mesh
from forge_checks.predicates import orient3d
from forge_checks.view import Box, Side
from numpy.typing import NDArray
from v2_meshes import (
    HAVE_MANIFOLD,
    KNOWN,
    box_soup,
    nearest_within,
    shapes,
    triangles,
    view,
)

Array = NDArray[np.float64]
LO, HI = np.array([0.0, 0.0, 0.0]), np.array([10.0, 20.0, 30.0])


def box_view() -> MeshView:
    return MeshView(box_mesh((0, 0, 0), (10, 20, 30)), source="mesh", deflection=0.0)


def box_distance(p: Array) -> Array:
    outside = np.maximum(np.maximum(LO - p, p - HI), 0.0)
    out = np.linalg.norm(outside, axis=1)
    inside = np.minimum(p - LO, HI - p).min(axis=1)
    return np.where((outside > 0).any(axis=1), out, np.maximum(inside, 0.0))


def check_near(
    case: unittest.TestCase,
    mesh: MeshView,
    rng: np.random.Generator,
    span: tuple[float, float],
) -> None:
    """``near`` is ``distance <= t`` exactly: at points of the surface, round it and anywhere, for any t, and t
    the distance itself or a hair less."""
    cover = mesh.coverage(1.0)
    off = cover.points + rng.normal(scale=0.05, size=cover.points.shape)
    points = np.concatenate([cover.points, off, rng.uniform(*span, size=(2000, 3))])
    d = mesh.distance(points)
    for t in (
        rng.uniform(0.0, 0.2, len(points)),
        d,
        np.maximum(np.nextafter(d, -np.inf), 0.0),
        np.zeros(len(points)),
    ):
        case.assertEqual(mesh.near(points, t).tolist(), (d <= t).tolist())


class ABoxAnswersExactly(unittest.TestCase):
    def test_sides_on_a_grid_through_its_faces_edges_and_corners(self) -> None:
        axes = [np.array([-1.0, 0.0, 0.5 * h, h, h + 2.0]) for h in HI]
        grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
        rng = np.random.default_rng(1)
        points = np.concatenate([grid, rng.uniform(-5, 35, size=(3000, 3))])
        within = ((points >= LO) & (points <= HI)).all(axis=1)
        strictly = ((points > LO) & (points < HI)).all(axis=1)
        want = np.where(strictly, Side.IN, np.where(within, Side.ON, Side.OUT))
        self.assertEqual(box_view().classify(points).tolist(), want.tolist())

    def test_distances(self) -> None:
        rng = np.random.default_rng(2)
        points = np.concatenate(
            [rng.uniform(-10, 40, size=(3000, 3)), rng.uniform(0, 10, size=(500, 3))]
        )
        np.testing.assert_allclose(
            box_view().distance(points), box_distance(points), atol=1e-12
        )

    def test_near_is_the_distances(self) -> None:
        check_near(self, box_view(), np.random.default_rng(5), (-10.0, 40.0))

    def test_crossings_along_and_across(self) -> None:
        v = box_view()
        # Off the faces' diagonals, where two triangles meet.
        origins = np.array(
            [[3.0, 12.0, -5.0], [3.0, 12.0, 15.0], [-1.0, 5.0, 7.0], [3.0, 12.0, 40.0]]
        )
        directions = np.array([[0, 0, 1.0], [0, 0, 1.0], [1.0, 0, 0], [0, 0, 1.0]])
        found = v.crossings(origins, directions)
        self.assertEqual(found.ray.tolist(), [0, 0, 1, 2, 2])
        np.testing.assert_allclose(found.t, [5.0, 35.0, 15.0, 1.0, 11.0], atol=1e-12)
        self.assertEqual(found.entering.tolist(), [True, False, False, True, False])
        self.assertEqual(found.grazed.tolist(), [False] * 4)

    def test_a_ray_through_an_edge_grazes(self) -> None:
        v = box_view()
        across_a_diagonal = v.crossings(
            np.array([[5.0, 10.0, -5.0]]), np.array([[0.0, 0.0, 1.0]])
        )
        self.assertEqual(across_a_diagonal.grazed.tolist(), [True])
        corner = np.array([[0.0, 0.0, -5.0]])
        through_edge = v.crossings(
            np.array([[-5.0, 10.0, -5.0]]), np.array([[1.0, 0.0, 1.0]])
        )
        through_corner = v.crossings(
            corner + np.array([[-1.0, -1.0, 0.0]]), np.array([[1.0, 1.0, 5.0]])
        )
        self.assertEqual(through_edge.grazed.tolist(), [True])
        self.assertEqual(through_corner.grazed.tolist(), [True])

    def test_volume_bounds_and_topology(self) -> None:
        v = box_view()
        self.assertTrue(v.volume().contains(6000.0))
        self.assertLess(v.volume().width, 1e-9)
        self.assertEqual(
            (v.bounds().lo, v.bounds().hi), ((0.0, 0.0, 0.0), (10.0, 20.0, 30.0))
        )
        t = v.topology()
        self.assertTrue(t.sound)
        self.assertEqual((t.shells, t.solids, t.voids, t.genus), (1, 1, 0, (0,)))


class ConvexHullsAgreeWithTheirPlanes(unittest.TestCase):
    @unittest.skipUnless(HAVE_MANIFOLD, "manifold3d makes the hulls")
    def test_inside_is_below_every_face(self) -> None:
        import manifold3d as m3

        rng = np.random.default_rng(3)
        for trial in range(6):
            cloud = rng.normal(size=(60, 3)) * rng.uniform(
                0.5, 20.0, size=3
            ) + rng.uniform(-100, 100, 3)
            soup = triangles(m3.Manifold.hull_points(cloud))
            v = view(soup)
            self.assertTrue(v.topology().sound, trial)
            lo, hi = soup.reshape(-1, 3).min(0), soup.reshape(-1, 3).max(0)
            points = rng.uniform(lo - 2, hi + 2, size=(1500, 3))
            points = np.concatenate(
                [points, soup[:, 0] + rng.normal(scale=1e-5, size=(len(soup), 3))]
            )
            far = v.distance(points) > 1e-7
            points = points[far]
            n = len(points)
            a, b, c = (
                np.repeat(soup[None, :, k], n, 0).reshape(-1, 3) for k in range(3)
            )
            p = np.repeat(points, len(soup), 0)
            below = orient3d(a, b, c, p).reshape(n, len(soup))
            want = np.where((below > 0).all(axis=1), Side.IN, Side.OUT)
            self.assertEqual(v.classify(points).tolist(), want.tolist(), trial)


def tetrahedron(a: Any, b: Any, c: Any, d: Any) -> Array:
    """A tetrahedron's four triangles, each wound to face out."""
    p = np.array([a, b, c, d], dtype=np.float64)
    soup = []
    for i, j, k, far in ((0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 3, 1), (1, 2, 3, 0)):
        tri = p[[i, j, k]]
        if (
            float(np.dot(np.cross(tri[1] - tri[0], tri[2] - tri[0]), p[far] - tri[0]))
            > 0
        ):
            tri = tri[[0, 2, 1]]
        soup.append(tri)
    return np.array(soup)


#: Tetrahedra whose triangles exporters make too: needles, slivers, wide obtuse ones, big ones, far from the origin.
AWKWARD = {
    "needle": ((0, 0, 0), (40, 0, 0), (20, 0.02, 0), (20, 0.01, 0.015)),
    "sliver": ((0, 0, 0), (12, 0, 0), (6, 0.001, 0), (6, 0, 9)),
    "obtuse": ((0, 0, 0), (30, 0, 0), (29.5, 0.6, 0), (14, 0.3, 2)),
    "big": ((0, 0, 0), (60, 0, 0), (25, 50, 0), (30, 20, 40)),
    "far": ((1000, 1000, 1000), (1003, 1000, 1000), (1000, 1004, 1000), (1001, 1001, 1005)),
}  # fmt: skip


class CoverageOfAwkwardTriangles(unittest.TestCase):
    """Coverage on awkward triangles, each checked everywhere on a fine grid."""

    def check(self, soup: Array, radius: float) -> None:
        cover = view(soup).coverage(radius)
        self.assertLessEqual(cover.radius, radius)
        side = np.linalg.norm(soup - soup[:, [1, 2, 0]], axis=2).max(axis=1)
        area = (
            np.linalg.norm(
                np.cross(soup[:, 1] - soup[:, 0], soup[:, 2] - soup[:, 0]), axis=1
            )
            / 2
        )
        # No more points than rows of them need: a regression here is memory.
        most = float(np.sum(area / radius**2 + 4 * side / radius + 6))
        self.assertLessEqual(len(cover.points), most)
        # Each point lies on its own triangle.
        a, b, c = (soup[cover.patch, k] for k in range(3))
        normal = np.cross(b - a, c - a)
        normal /= np.linalg.norm(normal, axis=1)[:, None]
        d = cover.points - a
        self.assertLess(float(np.abs(np.einsum("ij,ij->i", d, normal)).max()), 1e-9)
        for x, y in ((a, b), (b, c), (c, a)):
            inward = np.einsum("ij,ij->i", np.cross(y - x, cover.points - x), normal)
            self.assertGreater(float(inward.min()), -1e-9)
        # Every point of every triangle, on a grid with its corners and sides,
        # two to the radius.
        for t, s in zip(soup, side, strict=True):
            n = min(math.ceil(2 * s / radius), 600)
            i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
            keep = i + j <= n
            u, v = i[keep] / n, j[keep] / n
            grid = (1 - u - v)[:, None] * t[0] + u[:, None] * t[1] + v[:, None] * t[2]
            gap = nearest_within(cover.points, grid, cover.radius * (1 + 1e-9))
            self.assertTrue(np.isfinite(gap).all())

    def test_every_point_is_within_the_radius(self) -> None:
        for name, corners in AWKWARD.items():
            for radius in (5.0, 0.7, 0.15):
                with self.subTest(shape=name, radius=radius):
                    self.check(tetrahedron(*corners), radius)

    def test_random_tetrahedra(self) -> None:
        rng = np.random.default_rng(11)
        for trial in range(30):
            corners = rng.normal(size=(4, 3)) * rng.uniform(0.01, 30, size=3)
            radius = float(rng.choice([3.0, 0.4, 0.12]))
            with self.subTest(trial=trial, radius=radius):
                self.check(tetrahedron(*corners), radius)


@functools.cache
def reference_solids() -> dict[str, Any]:
    """The reference solids, made once (not in setUpClass: any runner may run one test alone)."""
    return shapes()


@unittest.skipUnless(HAVE_MANIFOLD, "manifold3d makes the reference solids")
class ReferenceSolids(unittest.TestCase):
    @property
    def solids(self) -> dict[str, Any]:
        return reference_solids()

    def test_topology_is_known(self) -> None:
        for name, solid in self.solids.items():
            t = view(triangles(solid)).topology()
            self.assertTrue(t.sound, name)
            self.assertEqual((t.solids, t.voids, t.genus), KNOWN[name], name)

    def test_volume_is_manifolds(self) -> None:
        for name, solid in self.solids.items():
            volume = view(triangles(solid)).volume()
            self.assertAlmostEqual(
                volume.midpoint, solid.volume(), delta=1e-6 * solid.volume(), msg=name
            )

    def test_near_is_the_distances(self) -> None:
        rng = np.random.default_rng(6)
        for name, solid in self.solids.items():
            with self.subTest(name):
                mine = view(triangles(solid))
                box = mine.bounds()
                check_near(self, mine, rng, (min(box.lo) - 2.0, max(box.hi) + 2.0))

    def test_the_normal_and_the_rays_agree_everywhere(self) -> None:
        rng = np.random.default_rng(4)
        for name, solid in self.solids.items():
            soup = triangles(solid)
            v = view(soup)
            lo, hi = soup.reshape(-1, 3).min(0), soup.reshape(-1, 3).max(0)
            corners = soup.reshape(-1, 3)
            edges = (soup[:, 0] + soup[:, 1]) / 2
            centres = soup.mean(axis=1)
            unit = np.cross(soup[:, 1] - soup[:, 0], soup[:, 2] - soup[:, 0])
            unit /= np.linalg.norm(unit, axis=1)[:, None]
            near = [
                rng.uniform(lo - 1, hi + 1, size=(2000, 3)),
                corners[rng.integers(0, len(corners), 800)]
                + rng.normal(size=(800, 3)) * 10.0 ** rng.uniform(-7, -1, (800, 1)),
                edges[rng.integers(0, len(edges), 800)]
                + rng.normal(size=(800, 3)) * 10.0 ** rng.uniform(-7, -1, (800, 1)),
                centres
                + unit
                * rng.choice([-1, 1], (len(unit), 1))
                * 10.0 ** rng.uniform(-8, -2, (len(unit), 1)),
            ]
            points = np.concatenate(near)
            sides = v.classify(points)
            off = sides != Side.ON
            self.assertFalse((sides == Side.UNKNOWN).any(), name)
            self.assertEqual(
                sides[off].tolist(), v.shape.sides_by_rays(points[off]).tolist(), name
            )
            # Just off a face's centre, the side is the normal's.
            k = len(near[0]) + len(near[1]) + len(near[2])
            tail = sides[k:]
            push = np.einsum("ij,ij->i", near[3] - centres, unit)
            want = np.where(push > 0, Side.OUT, Side.IN)
            sure = np.abs(push) > ON_BAND
            self.assertEqual(tail[sure].tolist(), want[sure].tolist(), name)

    def test_far_from_the_origin_and_in_float32(self) -> None:
        soup = triangles(self.solids["bracket"])
        rng = np.random.default_rng(5)
        points = rng.uniform(-5, 45, size=(3000, 3))
        base = view(soup).classify(points)
        moved = view(soup + 1000.0)
        self.assertTrue(moved.topology().sound)
        self.assertEqual(moved.classify(points + 1000.0).tolist(), base.tolist())
        rounded = view(soup.astype(np.float32).astype(np.float64))
        self.assertTrue(rounded.topology().sound)

    def test_coverage_reaches_every_point_of_the_surface(self) -> None:
        rng = np.random.default_rng(6)
        for name in ("box", "ball", "bracket"):
            soup = triangles(self.solids[name])
            v = view(soup, deflection=0.01)
            for radius in (2.0, 0.5):
                cover = v.coverage(radius)
                self.assertLessEqual(cover.radius, radius)
                self.assertTrue((cover.tolerance == 0.01).all())
                # Random points on the surface, spread by area.
                area = np.linalg.norm(
                    np.cross(soup[:, 1] - soup[:, 0], soup[:, 2] - soup[:, 0]), axis=1
                )
                pick = rng.choice(len(soup), size=3000, p=area / area.sum())
                w = rng.dirichlet((1, 1, 1), size=3000)
                surface = np.einsum("ij,ijk->ik", w, soup[pick])
                gap = nearest_within(cover.points, surface, cover.radius * (1 + 1e-9))
                self.assertTrue(np.isfinite(gap).all(), (name, radius))
                # Each point lies on its own patch: inside the triangle, in its plane.
                a, b, c = (soup[cover.patch, k] for k in range(3))
                u, w, d = b - a, c - a, cover.points - a
                uu, uw, ww = (
                    np.einsum("ij,ij->i", x, y) for x, y in ((u, u), (u, w), (w, w))
                )
                du, dw = np.einsum("ij,ij->i", d, u), np.einsum("ij,ij->i", d, w)
                det = uu * ww - uw * uw
                s_, t_ = (ww * du - uw * dw) / det, (uu * dw - uw * du) / det
                height = np.linalg.norm(d - s_[:, None] * u - t_[:, None] * w, axis=1)
                self.assertLess(float(height.max()), 1e-9, name)
                self.assertGreater(
                    float(np.minimum(np.minimum(s_, t_), 1 - s_ - t_).min()), -1e-9
                )
                # Its normal points out: a step along it leaves the part, a step back enters.
                some = rng.choice(
                    len(cover.points), size=min(4000, len(cover.points)), replace=False
                )
                at, out = cover.points[some], cover.normals[some]
                outside = v.classify(at + 1e-4 * out)
                inside = v.classify(at - 1e-4 * out)
                if name != "bracket":  # convex: every point's normal points cleanly out
                    self.assertTrue((outside == Side.OUT).all(), name)
                    self.assertTrue((inside == Side.IN).all(), name)
                else:
                    self.assertGreater(float((outside == Side.OUT).mean()), 0.99)
            # And the check above can fail: a big triangle's points taken away leave a gap.
            if name == "box":
                cover = v.coverage(0.5)
                lost = cover.patch == cover.patch[0]
                on_lost = soup[cover.patch[0]].mean(axis=0, keepdims=True)
                gap = nearest_within(cover.points[~lost], on_lost, cover.radius)
                self.assertTrue(np.isinf(gap).all())

    def test_coverage_within_a_box_reaches_every_point_of_the_surface_in_it(
        self,
    ) -> None:
        rng = np.random.default_rng(9)
        soup = triangles(self.solids["bracket"])
        v = view(soup, deflection=0.01)
        c = soup[len(soup) // 2].mean(axis=0)  # a box round a point of the surface
        box = Box(
            (float(c[0]) - 3, float(c[1]) - 3, float(c[2]) - 3),
            (float(c[0]) + 3, float(c[1]) + 3, float(c[2]) + 3),
        )
        whole, part = v.coverage(0.3), v.coverage(0.3, box)
        self.assertLessEqual(part.radius, 0.3)
        self.assertLess(len(part.points), len(whole.points))
        # Random points on the surface, in the box: each near a point of the coverage within it.
        area = np.linalg.norm(
            np.cross(soup[:, 1] - soup[:, 0], soup[:, 2] - soup[:, 0]), axis=1
        )
        pick = rng.choice(len(soup), size=60000, p=area / area.sum())
        w = rng.dirichlet((1, 1, 1), size=60000)
        surface = np.einsum("ij,ijk->ik", w, soup[pick])
        inside = np.all((surface >= box.lo) & (surface <= box.hi), axis=1)
        self.assertGreater(int(inside.sum()), 200)
        gap = nearest_within(part.points, surface[inside], part.radius * (1 + 1e-9))
        self.assertTrue(np.isfinite(gap).all())
        # A box the surface doesn't meet has none of it.
        far = Box((1e4, 1e4, 1e4), (1e4 + 1, 1e4 + 1, 1e4 + 1))
        self.assertEqual(len(v.coverage(0.3, far).points), 0)

    def test_within_a_box_only_pieces_of_big_triangles_near_it(self) -> None:
        """A 100 mm plate's faces are two triangles each: covered finely within a 6 mm box, only their pieces near it,
        every point of the surface in the box within the radius of one, each point on its own triangle with its face's
        normal (docs/V2-stage4.md, 13.10)."""
        v = MeshView(
            box_mesh((0, 0, 0), (100, 80, 10)), source="mesh-file", deflection=0.01
        )
        rng = np.random.default_rng(4)
        for within in (
            Box((20.0, 20.0, 9.0), (25.0, 26.0, 11.0)),
            Box((-1.0, -1.0, -1.0), (3.0, 3.0, 3.0)),
        ):
            part = v.coverage(0.05, within)
            self.assertLess(
                len(part.points), 40000
            )  # the whole surface at 0.05 mm: 7.9 million
            self.assertTrue((part.tolerance == 0.01).all())
            # Random points of the surface in the box: each near a point of the coverage.
            soup = v.shape._corners
            n = 200000
            found = []
            for k in range(12):
                a, b, c = (x[k] for x in soup)
                w = rng.dirichlet((1, 1, 1), size=n)
                p = w[:, :1] * a + w[:, 1:2] * b + w[:, 2:] * c
                found.append(p[np.all((p >= within.lo) & (p <= within.hi), axis=1)])
            surface = np.concatenate(found)
            self.assertGreater(len(surface), 100)
            gap = nearest_within(part.points, surface, part.radius * (1 + 1e-9))
            self.assertTrue(np.isfinite(gap).all())
            # On its own triangle's plane, with the plate's face's outward normal.
            a, b, c = (x[part.patch] for x in soup)
            normal = np.cross(b - a, c - a)
            normal /= np.linalg.norm(normal, axis=1)[:, None]
            self.assertLess(
                float(np.abs(np.einsum("ij,ij->i", part.points - a, normal)).max()),
                1e-9,
            )
            inner = np.abs(np.einsum("ij,ij->i", part.normals, normal) - 1) < 1e-12
            self.assertGreater(
                float(inner.mean()), 0.9
            )  # off the plate's edges and corners

    def test_with_deflection_keeps_everything_but_the_tolerance(self) -> None:
        v = view(triangles(self.solids["ring"]))
        w = v.with_deflection(0.05)
        self.assertIs(w.shape, v.shape)
        self.assertIs(w.topology(), v.topology())
        self.assertTrue((w.coverage(1.0).tolerance == 0.05).all())

    def test_a_deflection_for_each_triangle(self) -> None:
        """Each point of the coverage as far off as its own triangle may be; the volume widened by each triangle's area times its own."""
        soup = triangles(self.solids["ring"])
        v = view(soup)
        each = np.where(np.arange(len(soup)) % 3 == 0, 0.05, 0.01)
        w = v.with_deflection(each)
        self.assertEqual(w.deflection, 0.05)
        found = w.coverage(1.0)
        np.testing.assert_array_equal(found.tolerance, each[found.patch])
        sides = np.cross(soup[:, 1] - soup[:, 0], soup[:, 2] - soup[:, 0])
        areas = 0.5 * np.linalg.norm(sides, axis=1)
        own, widened = v.volume(), w.volume()
        self.assertAlmostEqual(
            widened.hi - own.hi, float(areas @ each), delta=1e-9 * float(areas.sum())
        )
        self.assertAlmostEqual(own.lo - widened.lo, widened.hi - own.hi, delta=1e-9)
        with self.assertRaises(ValueError):
            v.with_deflection(each[1:])
        with self.assertRaises(ValueError):
            v.with_deflection(-each)


def damaged(soup: Array) -> MeshView:
    return view(np.asarray(soup, dtype=np.float64))


@unittest.skipUnless(HAVE_MANIFOLD, "manifold3d makes the meshes damaged")
class MeshIntegrityMutants(unittest.TestCase):
    """Each damaged mesh is unsound, by the count that names its fault, and classifies nothing."""

    @property
    def soup(self) -> Array:
        return triangles(reference_solids()["bracket"])

    def unsound(self, v: MeshView, **counts: int) -> None:
        t = v.topology()
        self.assertFalse(t.sound)
        for name, least in counts.items():
            self.assertGreaterEqual(getattr(t, name), least, name)
        rng = np.random.default_rng(7)
        points = rng.uniform(-5, 45, size=(200, 3))
        self.assertTrue((v.classify(points) == Side.UNKNOWN).all())
        self.assertEqual((v.volume().lo, v.volume().hi), (-math.inf, math.inf))
        self.assertEqual(len(v.distance(points)), 200)  # distances are still answered

    def test_a_missing_triangle(self) -> None:
        self.unsound(damaged(self.soup[1:]), open_edges=3)

    def test_a_flipped_triangle(self) -> None:
        soup = self.soup.copy()
        soup[5] = soup[5][[0, 2, 1]]
        self.unsound(damaged(soup), bad_edges=3)

    def test_a_doubled_triangle(self) -> None:
        self.unsound(
            damaged(np.concatenate([self.soup, self.soup[:1]])),
            bad_edges=3,
            self_intersections=1,
        )

    def test_a_crack_at_a_t_junction(self) -> None:
        soup = self.soup.copy()
        a, b, c = soup[0]
        m = (a + b) / 2
        soup = np.concatenate([soup[1:], [[a, m, c], [m, b, c]]])
        self.unsound(damaged(soup), open_edges=2)

    def test_a_crack_too_fine_to_see(self) -> None:
        soup = self.soup.copy()
        soup[0, 0] = soup[0, 0] + 1e-12  # one corner, a hair from its neighbours
        self.unsound(damaged(soup), open_edges=2)

    def test_a_fold_through_itself(self) -> None:
        import manifold3d as m3

        ball = triangles(m3.Manifold.sphere(5, 32))
        top = ball.reshape(-1, 3)[:, 2].max()
        folded = ball.copy()
        folded[folded[..., 2] == top] *= np.array(
            [1.0, 1.0, -1.2]
        )  # the pole pushed through and out
        self.unsound(damaged(folded), self_intersections=1)

    def test_a_bad_vertex(self) -> None:
        one = box_soup((0, 0, 0), (1, 1, 1))
        two = box_soup((1, 1, 1), (2, 2, 2))  # touching the first at one corner
        self.unsound(damaged(np.concatenate([one, two])), bad_vertices=1)

    def test_an_inside_out_shell(self) -> None:
        self.unsound(damaged(self.soup[:, [0, 2, 1]]), misnested=1)

    def test_a_hollow_facing_out(self) -> None:
        outer = box_soup((0, 0, 0), (10, 10, 10))
        inner = box_soup((3, 3, 3), (6, 6, 6))  # a void must face inwards
        self.unsound(damaged(np.concatenate([outer, inner])), misnested=1)

    def test_two_overlapping_shells(self) -> None:
        soup = np.concatenate([self.soup, self.soup + np.array([5.0, 3.0, 1.0])])
        self.unsound(damaged(soup), self_intersections=1)

    def test_a_triangle_with_no_area(self) -> None:
        soup = self.soup.copy()
        a, b, _ = soup[0]
        soup = np.concatenate([soup, [[a, (a + b) / 2, b]]])
        self.unsound(damaged(soup), bad_triangles=1)

    def test_a_repeated_corner(self) -> None:
        soup = np.concatenate(
            [self.soup, [[self.soup[0, 0], self.soup[0, 0], self.soup[0, 1]]]]
        )
        self.unsound(damaged(soup), bad_triangles=1)

    def test_a_coordinate_that_is_not_a_number(self) -> None:
        for bad in (math.nan, math.inf):
            soup = self.soup.copy()
            soup[3, 1, 2] = bad
            self.unsound(damaged(soup), bad_triangles=1)

    def test_a_coordinate_too_small_to_compute_with(self) -> None:
        soup = box_soup((0, 0, 0), (1, 1, 1))
        soup[soup == 0.0] = 1e-60
        self.unsound(damaged(soup), bad_triangles=1)


class Welding(unittest.TestCase):
    def test_minus_zero_is_zero(self) -> None:
        soup = box_soup((0, 0, 0), (1, 1, 1))
        soup[::2][soup[::2] == 0.0] = -0.0
        self.assertTrue(view(soup).topology().sound)

    def test_a_list_of_triangles_welds_to_the_box(self) -> None:
        mesh = Mesh.from_triangles(box_soup((0, 0, 0), (1, 1, 1)))
        self.assertEqual((len(mesh.vertices), len(mesh.faces)), (8, 12))

    def test_an_empty_mesh_and_a_negative_deflection_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            MeshView(
                Mesh(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)),
                source="m",
                deflection=0,
            )
        with self.assertRaises(ValueError):
            view(box_soup((0, 0, 0), (1, 1, 1)), deflection=-1.0)


if __name__ == "__main__":
    unittest.main()
