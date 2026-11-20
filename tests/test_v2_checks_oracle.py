"""The spec's own shape (forge_checks.oracle).

- **Reference parts** (tests/v2_reference.py): each spec's oracle against the
  same part built by hand from the definitions with manifold3d. Every point
  farther from the mesh than its polygons can be from the true surfaces must
  be on the same side of both.
- **Points on several surfaces at once:** settled exactly, and the same as
  the points just off them in every direction say.
- **Letters:** the pinned font's outlines, exactly: every point where it puts it.
- **What isn't known exactly:** regions, between their limits.
"""

from __future__ import annotations

import math
import random
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
from forge_checks import oracle as oracle_module
from forge_checks.letters import Ink
from forge_checks.mesh import MeshView
from forge_checks.oracle import (
    COARSE_PITCH,
    OFF,
    CannotMakeError,
    Oracle,
    Step,
    _alike,
    _apart_revolved,
    _assemble,
    oracle,
    probes,
    thread_pitch,
)
from forge_checks.place import place
from forge_checks.shapes import Frame, Patch, Polygon, Prism, Revolved
from forge_checks.view import Box, Resolution, Side
from forge_spec.font import text_width
from forge_spec.placement import solve
from forge_spec.tables import TAPPED
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_meshes import HAVE_MANIFOLD, nearest_within, triangles, view
from v2_reference import MARGIN, PARTS, TOPOLOGY, mesh_box
from v2_specs import SAY, WORDS, a, pick, random_specs, read

Array = NDArray[np.float64]


def item(item_id: str, kind: str, **fields: object) -> dict[str, object]:
    return {"id": item_id, "kind": kind, "words": WORDS, **fields}


PLATE = item("plate", "block", length=a(80), width=a(50), height=a(5))


def _known_round(part: Oracle, points: Array) -> NDArray[np.bool_]:
    """Whether the oracle knows what is at each point and at the points the mesh's margin away along each axis."""
    known = part.classify(points) != Side.UNKNOWN
    for step in np.vstack([np.eye(3), -np.eye(3)]) * MARGIN:
        known &= part.classify(points + step) != Side.UNKNOWN
    return np.asarray(known, dtype=np.bool_)


def _spread(
    soup: NDArray[np.float64], count: int, rng: np.random.Generator
) -> NDArray[np.float64]:
    """Points spread over a mesh's surface, each triangle getting its share by area."""
    a, b, c = soup[:, 0], soup[:, 1], soup[:, 2]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    pick = rng.choice(len(soup), count, p=area / area.sum())
    r1, r2 = rng.random(count), rng.random(count)
    flip = r1 + r2 > 1
    r1, r2 = np.where(flip, 1 - r1, r1), np.where(flip, 1 - r2, r2)
    return np.asarray(
        a[pick] + r1[:, None] * (b[pick] - a[pick]) + r2[:, None] * (c[pick] - a[pick])
    )


@dataclass(frozen=True)
class Made:
    """A reference part: its oracle, and its mesh made by hand."""

    part: Oracle
    mesh: Any
    soup: NDArray[np.float64]
    reference: MeshView


_MADE: dict[str, Made] = {}


def made(name: str) -> Made:
    if name not in _MADE:
        items, build = PARTS[name]()
        spec = read(items)
        mesh = build()
        soup = triangles(mesh)
        _MADE[name] = Made(oracle(spec, place(spec)), mesh, soup, view(soup))
    return _MADE[name]


@unittest.skipUnless(HAVE_MANIFOLD, "the reference parts are made with manifold3d")
class ReferenceParts(unittest.TestCase):
    def test_the_reference_meshes_are_the_parts_they_should_be(self) -> None:
        for name in PARTS:
            with self.subTest(part=name):
                t = made(name).reference.topology()
                self.assertTrue(t.sound, (name, t))
                self.assertEqual((t.solids, t.voids, t.genus[0]), TOPOLOGY[name], name)

    def test_every_reference_part(self) -> None:
        rng = np.random.default_rng(7)
        for name, make in PARTS.items():
            with self.subTest(part=name):
                items, _ = make()
                self.assertEqual(solve(read(items)).issues, [], name)
                m = made(name)
                part = m.part
                lo, hi = mesh_box(m.mesh)
                # Everywhere round the part, and densely round every step: no item is missed.
                around = [rng.uniform(lo - 4, hi + 4, size=(8000, 3))]
                for step in part.steps:
                    around.append(
                        rng.uniform(
                            np.array(step.lo) - 1, np.array(step.hi) + 1, size=(1500, 3)
                        )
                    )
                points = np.concatenate(around)
                far = m.reference.distance(points) > MARGIN
                points = points[far]
                expected = m.reference.classify(points)
                found = part.classify(points)
                # Where a rounding is only bounded (round a corner), the oracle doesn't say.
                known = found != Side.UNKNOWN
                self.assertLess(int((~known).sum()), 0.1 * len(points), name)
                wrong = np.flatnonzero(known & (found != expected))
                self.assertEqual(
                    len(wrong),
                    0,
                    (
                        name,
                        points[wrong[:5]].tolist(),
                        found[wrong[:5]].tolist(),
                        expected[wrong[:5]].tolist(),
                    ),
                )
                self.assertGreater(int((expected == Side.IN).sum()), 200, name)
                self.assertEqual(part.unchecked, ())

    def test_the_surfaces_are_the_meshes(self) -> None:
        """Every point the oracle covers its surface with is on the mesh; every piece of the mesh is near one, and has a witness."""
        rng = np.random.default_rng(11)
        radius = 1.0
        for name in PARTS:
            with self.subTest(part=name):
                m = made(name)
                cover = m.part.coverage(radius)
                self.assertLessEqual(
                    float(m.reference.distance(cover.points).max()), MARGIN, name
                )
                # The mesh's own points: its corners and its triangles' middles (not within the mesh's
                # margin of where a rounding or a thread is only bounded: the oracle doesn't say where the
                # surface is there, and the mesh's facets stray that far either way).
                middles, ends = m.soup.mean(axis=1), m.soup.reshape(-1, 3)
                own = np.concatenate(
                    [
                        _spread(m.soup, 20000, rng),
                        middles[
                            rng.choice(
                                len(middles), min(5000, len(middles)), replace=False
                            )
                        ],
                        ends[
                            rng.choice(len(ends), min(5000, len(ends)), replace=False)
                        ],
                    ]
                )
                own = own[_known_round(m.part, own)]
                self.assertGreater(len(own), 5000, name)
                gap = nearest_within(cover.points, own, 1.1 * radius)
                self.assertLessEqual(float(gap.max()), radius + MARGIN, name)
                corners = np.unique(m.soup.reshape(-1, 3), axis=0)
                corners = corners[_known_round(m.part, corners)]
                corners = corners[
                    rng.choice(len(corners), min(200, len(corners)), replace=False)
                ]
                found = m.part.witness(corners, MARGIN)
                self.assertTrue(found.all(), (name, corners[~found][:3].tolist()))

    def test_the_volume_holds_the_meshes(self) -> None:
        for name in PARTS:
            with self.subTest(part=name):
                m = made(name)
                volume = m.part.volume(budget=1_000_000)
                # The mesh's corners are on the true surfaces: it is off the true volume by
                # at most MARGIN across its surface.
                slack = MARGIN * float(m.mesh.surface_area())
                self.assertLessEqual(volume.lo - slack, float(m.mesh.volume()), name)
                self.assertGreaterEqual(volume.hi + slack, float(m.mesh.volume()), name)

    def test_the_voids_are_the_meshes(self) -> None:
        for name in PARTS:
            with self.subTest(part=name):
                topology = made(name).part.expected_topology()
                self.assertEqual(topology.solids, 1)
                self.assertEqual(
                    topology.voids, TOPOLOGY[name][1], (name, topology.unchecked)
                )


class PointsOnSurfaces(unittest.TestCase):
    """Where steps' surfaces meet or lie on each other, settled from every direction round the point."""

    def test_worked_points(self) -> None:
        post = item(
            "post",
            "post",
            on={"item": "plate", "face": "+z"},
            length=a(10),
            width=a(10),
            height=a(5),
        )
        hole = item("h", "hole", on={"item": "plate", "face": "+z"}, diameter=a(6), depth={"through": True, "from": SAY},
                    place={"x": {"offset": a(20)}})  # fmt: skip
        spec = read([PLATE, post, hole])
        part = oracle(spec, place(spec))
        points = np.array([
            [0, 0, 5],  # under the post's foot, on the plate's top: inside the part
            [5, 0, 5],  # the edge where the post's side meets the plate's top: on the surface
            [5, 5, 5],  # the post's corner on the plate: on the surface
            [5, 0, 7],  # the post's side
            [20, 0, 0],  # the hole's floor in the plate's bottom face: not the part
            [23, 0, 0],  # the hole's rim on the bottom face
            [40, 25, 0],  # the plate's corner
            [20, 0, 5],  # the hole's mouth in the plate's top: not the part
        ], dtype=float)  # fmt: skip
        self.assertEqual(part.classify(points).tolist(), [1, 0, 0, 0, -1, 0, 0, -1])

    def test_points_alike_are_found_alike_to_the_bit(self) -> None:
        """Points are settled once per distinct model: rows alike to the bit, however their hash falls."""
        rng = np.random.default_rng(5)
        signs = rng.choice([-1.0, 1.0], size=(40, 6))
        # Rows that differ only in the signs of two columns (whose bits differ only at the top).
        table = np.concatenate([signs, signs * np.array([-1, -1, 1, 1, 1, 1]), signs])
        table = np.concatenate([table, rng.integers(0, 3, size=(200, 6)).astype(float)])
        # As it is, and with every row's hash the same.
        for mix in (oracle_module._MIX, np.uint64(0)):
            with mock.patch("forge_checks.oracle._MIX", mix):
                first, which = _alike(table)
            self.assertTrue(np.array_equal(table[first[which]], table))
            distinct = {row.tobytes() for row in table}
            self.assertEqual(len(first), len(distinct))
            self.assertEqual(len({table[k].tobytes() for k in first}), len(first))

    def test_settled_points_agree_with_their_neighbours(self) -> None:
        """At a point on surfaces, IN means every point just off it is in, OUT every one out."""
        rng = random.Random(4)
        for name, make in PARTS.items():
            items, _ = make()
            spec = read(items)
            part = oracle(spec, place(spec))
            corners = []
            for step in part.steps:
                lo, hi = np.array(step.lo), np.array(step.hi)
                for _ in range(40):
                    corners.append(
                        [
                            rng.choice((lo[k], hi[k], (lo[k] + hi[k]) / 2))
                            for k in range(3)
                        ]
                    )
            points = np.array(corners)
            sides = part.classify(points)
            directions = np.array(
                [[rng.gauss(0, 1) for _ in range(3)] for _ in range(64)]
            )
            directions /= np.linalg.norm(directions, axis=1)[:, None]
            for p, side in zip(points, sides, strict=True):
                if side in (Side.ON, Side.UNKNOWN):
                    continue
                around = part.classify(p + 1e-6 * directions)
                self.assertTrue(
                    np.all((around == side) | (around == Side.ON)),
                    (name, p.tolist(), int(side), around.tolist()),
                )


class SettledAtOnce(unittest.TestCase):
    """Points on one surface or on an edge are settled together, exactly as one by one; points' sets of steps are grouped exactly."""

    def test_the_same_as_one_by_one(self) -> None:
        one_by_one = mock.patch.object(
            oracle_module._Settle,
            "_plain",
            lambda self, kept, rows, sides: np.zeros(len(rows), dtype=bool),
        )
        rng = random.Random(7)
        for name, make in PARTS.items():
            items, _ = make()
            spec = read(items)
            part = oracle(spec, place(spec))
            cover = part.coverage(2.0)
            # Its surface's points, and the corners and middles of its steps' boxes.
            corners = [
                [
                    rng.choice((lo, hi, (lo + hi) / 2))
                    for lo, hi in zip(step.lo, step.hi, strict=True)
                ]
                for step in part.steps
                for _ in range(40)
            ]
            points = np.concatenate([cover.points, np.array(corners)])
            together = part.limits(points)
            with one_by_one:
                alone = part.limits(points)
            with self.subTest(part=name):
                self.assertTrue(np.array_equal(together[0], alone[0]))
                self.assertTrue(np.array_equal(together[1], alone[1]))

    def test_sets_of_steps_are_grouped_exactly(self) -> None:
        rng = np.random.default_rng(3)
        n, steps = 300, 12
        pairs = [(p, s) for p in range(n) for s in range(steps) if rng.random() < 0.3]
        pairs += pairs[:50]  # a pair found twice
        point_of = np.array([p for p, _ in pairs], dtype=np.int64)
        step_of = np.array([s for _, s in pairs], dtype=np.int64)
        rows = np.arange(0, n, 2, dtype=np.int64)
        allowed = np.array([s % 5 != 0 for s in range(steps)])
        expected = [
            tuple(sorted({s for p, s in pairs if p == r and allowed[s]})) for r in rows
        ]
        # As it is, and with every set's signature the same but for its size.
        zero = (np.uint64(0), np.uint64(0))
        for mixes in (oracle_module._SET_MIX, zero):
            with mock.patch("forge_checks.oracle._SET_MIX", mixes):
                group, sets = oracle_module._step_sets(
                    point_of, step_of, rows, allowed, n
                )
            self.assertEqual([sets[g] for g in group], expected)
            self.assertEqual(len(sets), len(set(expected)))


class Along(unittest.TestCase):
    """The part along segments: every piece between two places is one side all along, and each place is what it says."""

    def test_pieces_and_places_against_points(self) -> None:
        rng = np.random.default_rng(5)
        for name, make in PARTS.items():
            with self.subTest(part=name):
                items, _ = make()
                spec = read(items)
                part = oracle(spec, place(spec))
                lo, hi = np.array(part.lo), np.array(part.hi)
                n = 120
                origins = rng.uniform(lo - 2, hi + 2, size=(n, 3))
                directions = rng.normal(size=(n, 3))
                # Many along the frame's axes, where faces lie across them.
                directions[:50] = np.eye(3)[rng.integers(0, 3, 50)]
                directions /= np.linalg.norm(directions, axis=1)[:, None]
                lengths = np.full(n, float(np.linalg.norm(hi - lo)) + 4)
                found = part.along(origins, directions, lengths)
                for i in range(n):
                    t = found.t[found.start[i] : found.start[i + 1]]
                    pieces = found.pieces[
                        found.start[i] + i : found.start[i + 1] + i + 1
                    ]
                    self.assertTrue(np.all(np.diff(t) > 0))
                    u = rng.uniform(0, lengths[i], 200)
                    if len(t):
                        u = u[np.min(np.abs(u[:, None] - t[None, :]), axis=1) > 1e-7]
                    sides = part.classify(origins[i] + u[:, None] * directions[i])
                    self.assertEqual(
                        sides.tolist(), pieces[np.searchsorted(t, u)].tolist()
                    )
                    if len(t):
                        at = found.at[found.start[i] : found.start[i + 1]]
                        direct = part.classify(origins[i] + t[:, None] * directions[i])
                        self.assertEqual(at.tolist(), direct.tolist())

    def test_a_hole_runs_on_into_the_air(self) -> None:
        """Through a plate's hole: its mouth and its floor are air, not surfaces (the hole goes on into the air)."""
        hole = item(
            "h",
            "hole",
            on={"item": "plate", "face": "+z"},
            diameter=a(6),
            depth={"through": True, "from": SAY},
        )
        spec = read([PLATE, hole])
        part = oracle(spec, place(spec))
        found = part.along(np.array([[1.0, 0.5, -3.0], [10.0, 0.5, -3.0]]), np.array([[0.0, 0, 1], [0, 0, 1]]),
                           np.array([11.0, 11.0]))  # fmt: skip
        self.assertEqual(found.t.tolist(), [3.0, 8.0, 3.0, 8.0])
        self.assertEqual(found.at.tolist(), [Side.OUT, Side.OUT, Side.ON, Side.ON])
        self.assertEqual(
            found.pieces.tolist(), [Side.OUT] * 3 + [Side.OUT, Side.IN, Side.OUT]
        )

    def test_segments_are_checked(self) -> None:
        spec = read([PLATE])
        part = oracle(spec, place(spec))
        with self.assertRaises(ValueError):
            part.along(np.zeros((1, 3)), np.array([[0.0, 0, 2]]), np.array([1.0]))
        with self.assertRaises(ValueError):
            part.along(np.zeros((1, 3)), np.array([[0.0, 0, 1]]), np.array([-1.0]))
        empty = part.along(np.zeros((0, 3)), np.zeros((0, 3)), np.zeros(0))
        self.assertEqual(
            (len(empty.t), len(empty.pieces), empty.start.tolist()), (0, 0, [0])
        )


class Around(unittest.TestCase):
    """The part round circles: between two places it gives, the part is one side all round."""

    def test_pieces_against_points(self) -> None:
        rng = np.random.default_rng(7)
        for name, make in PARTS.items():
            with self.subTest(part=name):
                items, _ = make()
                spec = read(items)
                part = oracle(spec, place(spec))
                lo, hi = np.array(part.lo), np.array(part.hi)
                # The heights faces are at, where circles run along them.
                levels = sorted({round(float(x), 9) for step in part.steps for x in (step.lo[2], step.hi[2])
                                 if math.isfinite(x)})  # fmt: skip
                for k in range(30):
                    centre = rng.uniform(lo, hi)
                    if k < 20:
                        centre[2] = levels[int(rng.integers(len(levels)))]
                        u, v = np.array([1.0, 0, 0]), np.array([0.0, 1, 0])
                    else:
                        u = rng.normal(size=3)
                        u /= np.linalg.norm(u)
                        v = np.cross(u, rng.normal(size=3))
                        v /= np.linalg.norm(v)
                    radius = float(rng.uniform(0.5, max(hi - lo) / 2))
                    found = part.around(centre, u, v, radius)
                    self.assertTrue(np.all(np.diff(found) > 0))
                    self.assertTrue(np.all((found >= 0) & (found < 2 * math.pi)))
                    t = rng.uniform(0, 2 * math.pi, 300)
                    if len(found):
                        gap = np.abs(t[:, None] - found[None, :])
                        gap = np.minimum(gap, 2 * math.pi - gap)
                        t = t[np.min(gap, axis=1) * radius > 1e-7]
                    points = centre + radius * (
                        np.cos(t)[:, None] * u + np.sin(t)[:, None] * v
                    )
                    sides = part.classify(points)
                    piece = np.searchsorted(found, t) % max(len(found), 1)
                    for p in np.unique(piece).tolist():
                        self.assertEqual(
                            len(set(sides[piece == p].tolist())), 1, (name, k, p)
                        )

    def test_a_wall_too_thin_to_sample(self) -> None:
        """A rib 0.05 mm thick standing on the plate: a circle in the plate's face passes under it in four places."""
        rib = item("rib", "rib", on={"item": "plate", "face": "+z"}, length=a(20), thickness=a(0.05),
                   height=a(3), along=pick("x"))  # fmt: skip
        spec = read([PLATE, rib])
        part = oracle(spec, place(spec))
        found = part.around(
            np.array([0.0, 0, 5]), np.array([1.0, 0, 0]), np.array([0.0, 1, 0]), 5.0
        )
        a0 = math.asin(0.025 / 5)
        expected = [a0, math.pi - a0, math.pi + a0, 2 * math.pi - a0]
        self.assertEqual(len(found), 4)
        self.assertLess(float(np.max(np.abs(found - expected))), 1e-12)

    def test_circles_are_checked(self) -> None:
        spec = read([PLATE])
        part = oracle(spec, place(spec))
        x, y = np.array([1.0, 0, 0]), np.array([0.0, 1, 0])
        for centre, u, v, r in (((0, 0, 0), x, x, 1.0), ((0, 0, 0), x, 2 * y, 1.0), ((0, 0, 0), x, y, 0.0),
                                ((0, 0, math.nan), x, y, 1.0)):  # fmt: skip
            with self.assertRaises(ValueError):
                part.around(np.array(centre, dtype=float), u, v, r)


class Coverage(unittest.TestCase):
    """Every point of the part's surface a line finds (where it passes from in to out) is near a coverage point."""

    def surface_points(
        self, part: Oracle, rng: np.random.Generator, n: int = 300
    ) -> Array:
        lo, hi = np.array(part.lo), np.array(part.hi)
        origins = rng.uniform(lo - 1, hi + 1, size=(n, 3))
        directions = rng.normal(size=(n, 3))
        directions[: n // 2] = np.eye(3)[rng.integers(0, 3, n // 2)]
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        found = part.along(
            origins, directions, np.full(n, float(np.linalg.norm(hi - lo)) + 2)
        )
        points = []
        for i in range(n):
            t = found.t[found.start[i] : found.start[i + 1]]
            pieces = found.pieces[found.start[i] + i : found.start[i + 1] + i + 1]
            for k in range(len(t)):
                if {int(pieces[k]), int(pieces[k + 1])} == {Side.IN, Side.OUT}:
                    points.append(origins[i] + t[k] * directions[i])
        return np.array(points).reshape(-1, 3)

    def covered(self, part: Oracle, radius: float, rng: np.random.Generator) -> None:
        # Within finest of a curve where two surfaces meet, cells that small are kept or not by their middles.
        finest = radius / 16
        points = self.surface_points(part, rng)
        cover = part.coverage(radius)
        gap = nearest_within(cover.points, points, radius + 3 * finest)
        self.assertTrue(
            np.all(gap <= radius + 2 * finest),
            points[~(gap <= radius + 2 * finest)][:3].tolist(),
        )

    def test_a_dome_under_a_plate(self) -> None:
        """The plate's face round a dome hanging under it (the dome's flat face lies on its box's top)."""
        rng = np.random.default_rng(1)
        dome = item(
            "dome",
            "sphere",
            on={"item": "plate", "face": "-z"},
            diameter=a(40),
            portion=pick("upper_half"),
        )
        for items in (
            [PLATE, dome],
            [
                PLATE,
                dome,
                item(
                    "hollow",
                    "shell",
                    of="dome",
                    thickness=a(2),
                    open={"faces": [], "from": SAY},
                ),
            ],
        ):
            spec = read(items)
            self.covered(oracle(spec, place(spec)), 1.0, rng)

    def test_a_share_of_the_cells_at_a_time_as_all_at_once(self) -> None:
        """The cells settled a share at a time give the same points, normals and surfaces, in the same order, as all at once."""
        parts = [read(make()[0]) for make in PARTS.values()]
        parts += list(random_specs(20261028, 3))
        for k, spec in enumerate(parts):
            try:
                part = oracle(spec, place(spec))
            except CannotMakeError:
                continue
            radius = max(float(max(np.array(part.hi) - np.array(part.lo))) / 25, 0.25)
            found = []
            for share in (10**12, 397):
                with mock.patch.object(oracle_module, "CELLS_AT_ONCE", share):
                    found.append(
                        oracle_module._coverage(part, Resolution(radius), radius / 16)
                    )
            whole, shared = found
            with self.subTest(part=k):
                self.assertGreater(len(whole.points), 0)
                for name in ("points", "normals", "surface"):
                    self.assertTrue(
                        np.array_equal(getattr(whole, name), getattr(shared, name)),
                        name,
                    )

    def test_finer_in_a_box(self) -> None:
        """At a resolution, every point of the surface within the radius there of one: finer in the box, and only
        there; with no finer box, the coverage at its radius to the bit (docs/V2-stage4.md, 13.10)."""
        rng = np.random.default_rng(3)
        dome = item("dome", "sphere", on={"item": "plate", "face": "-z"}, diameter=a(40),
                    portion=pick("upper_half"))  # fmt: skip
        spec = read([PLATE, dome])
        part = oracle(spec, place(spec))
        within = Box((-41.0, -26.0, -21.0), (-20.0, 0.0, 6.0))
        resolution = Resolution(1.0, ((within, 0.1),))
        cover = part.coverage(resolution)
        self.assertEqual(cover.finer, resolution.finer)
        self.assertLess(len(cover.points), len(part.coverage(0.1).points) / 3)
        points = self.surface_points(part, rng, 3000)
        inside = np.all((points >= within.lo) & (points <= within.hi), axis=1)
        self.assertGreater(int(inside.sum()), 100)
        local = resolution.at(points)
        gap = nearest_within(cover.points, points, 1.0 + 3 / 16)
        self.assertTrue(
            np.all(gap <= local + 2 * local / 16),
            points[~(gap <= local + 2 * local / 16)][:3],
        )
        same, plain = part.coverage(Resolution(1.0)), part.coverage(1.0)
        self.assertIs(same, plain)

    def test_random_specs(self) -> None:
        rng = np.random.default_rng(2)
        for k, spec in enumerate(random_specs(20261023, 16)):
            with self.subTest(spec=k):
                try:
                    part = oracle(spec, place(spec))
                except CannotMakeError:
                    continue
                self.covered(
                    part,
                    max(float(max(np.array(part.hi) - np.array(part.lo))) / 30, 0.25),
                    rng,
                )


class ApartFromASolidOfRevolution(unittest.TestCase):
    """A solid of revolution's surface shown clear of a cell from its signed distance's convexity in its own half-plane (oracle._apart_revolved), so a coverage needn't split to its finest beside one (generated part 1325: a revolution's arc taken away by a square round it 0.0005 mm under its base, 2.1 million points at 0.5 mm)."""

    OUTLINES = (
        ((0.0, 0.0), (8.0, 0.0), (8.0, 6.0), (0.0, 6.0)),  # a cylinder
        ((2.0, -1.0), (7.0, 0.5), (3.0, 4.0)),  # a ring of triangular section
        ((0.0, -3.0), (5.0, 0.0), (0.0, 3.0)),  # two cones' points on the axis
        ((1.0, 0.0), (4.0, -2.0), (9.0, 1.0), (6.0, 5.0), (2.0, 4.0)),
    )

    def test_a_cell_it_says_is_clear_keeps_one_side(self) -> None:
        rng = np.random.default_rng(11)
        claimed = 0
        for outline in self.OUTLINES:
            solid = Revolved(
                Frame.along((1.0, -2.0, 0.5), (0.3, 0.4, 0.866)), Polygon(outline)
            )
            n = 3000
            q, _ = solid.nearest(rng.uniform(-12, 12, size=(n, 3)))
            centres = q + rng.normal(scale=0.3, size=(n, 3)) * rng.uniform(
                0, 1, size=(n, 1)
            )
            normals = rng.normal(size=(n, 3))
            normals[: n // 2] = (
                solid.frame.w
            )  # cells square to the axis, as flat rings are
            normals /= np.linalg.norm(normals, axis=1)[:, None]
            reach = rng.uniform(0.05, 2.0, size=n)
            near = np.abs(solid.signed_distance(centres)) <= reach
            apart = _apart_revolved(solid, centres, normals, reach, np.zeros(n)) & near
            claimed += int(apart.sum())
            for k in np.flatnonzero(apart):
                a = np.cross(
                    normals[k],
                    [1.0, 0.0, 0.0] if abs(normals[k][0]) < 0.9 else [0.0, 1.0, 0.0],
                )
                a /= np.linalg.norm(a)
                b = np.cross(normals[k], a)
                s, t = rng.uniform(-1, 1, size=(2, 400)) * reach[k] / math.sqrt(2)
                f = solid.signed_distance(centres[k] + s[:, None] * a + t[:, None] * b)
                self.assertTrue(np.all(f > 0) or np.all(f < 0), (outline, k))
        self.assertGreater(claimed, 1000)

    def test_a_ring_just_above_a_flat_side(self) -> None:
        """The part's base, a flat ring, 0.0005 mm above the flat side of a solid of revolution it lies inside (1325)."""
        square = Revolved(Frame.along((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
                          Polygon(((12.0, -0.0005), (22.0, -0.0005), (12.0, 9.8))))  # fmt: skip
        centres = np.array([[14.0, 0.0, 0.0], [0.0, -15.0, 0.0]])
        up = np.array([[0.0, 0.0, -1.0], [0.0, 0.0, -1.0]])
        found = _apart_revolved(square, centres, up, np.full(2, 0.36), np.zeros(2))
        self.assertEqual(found.tolist(), [True, True])
        # And one the side crosses is not.
        crossing = _apart_revolved(square, np.array([[14.0, 0.0, 0.2]]), np.array([[1.0, 0.0, 0.0]]),
                                   np.full(1, 0.36), np.zeros(1))  # fmt: skip
        self.assertEqual(crossing.tolist(), [False])


class AConesPoint(unittest.TestCase):
    """A pointed cone's apex has no tangent plane, so no side of it is settled; where the rest of the part leaves it bare, the part's surface may be there (docs/V2-stage4.md, 13.4)."""

    def test_its_apex_bare(self) -> None:
        from forge_checks.oracle import _may_be_surface

        cone = item(
            "c",
            "cone",
            base_diameter=a(40),
            top_diameter=a(0),
            length=a(60),
            axis=pick("z"),
        )
        spec = read([cone])
        part = oracle(spec, place(spec))
        np.testing.assert_allclose(part.apexes, [[0.0, 0.0, 60.0]])
        at = np.array(
            [
                [0.0, 0.0, 60.0],
                [0.0, 0.0, 60.0 + 5e-7],
                [0.0, 0.0, 60.0 + 1e-3],
                [0.0, 0.0, 59.0],
            ]
        )
        self.assertEqual(
            [int(s) for s in part.classify(at)],
            [Side.UNKNOWN, Side.OUT, Side.OUT, Side.IN],
        )
        self.assertEqual(list(_may_be_surface(part, at)), [True, False, False, False])

    def test_a_chamfer_s_point_and_a_frustum_s_none(self) -> None:
        rod = item("c", "cylinder", diameter=a(30), length=a(20), axis=pick("z"))
        bevel = item("r", "chamfer", edges={"of": "c", "which": "top"}, size=a(15))
        spec = read([rod, bevel])
        self.assertEqual(oracle(spec, place(spec)).apexes.shape, (1, 3))
        frustum = item(
            "c",
            "cone",
            base_diameter=a(40),
            top_diameter=a(10),
            length=a(60),
            axis=pick("z"),
        )
        spec = read([frustum])
        self.assertEqual(oracle(spec, place(spec)).apexes.shape, (0, 3))


class Witnesses(unittest.TestCase):
    """A point of the part's surface found within reach of a point, as face accounting asks for one."""

    def test_at_a_corner_where_three_surfaces_meet(self) -> None:
        """A built corner a hair into the air beside the spec's has a witness: the corner itself (part 4118).

        A counterbore's floor, its bore and a pocket's rounded corner meet
        at a corner of the part, the material a thin wedge past it. A point
        a hair from it along the pocket's edge, inside the bore, has nothing
        on any one surface or where any two meet beside it: the edges into
        the corner run on its other side.
        """
        block = item("b", "block", length=a(60), width=a(40), height=a(15))
        hole = item("h", "hole", on={"item": "b", "face": "-z"}, diameter=a(3), depth=a(9),
                    counterbore={"diameter": a(8), "depth": a(1)},
                    place={"x": {"side": "+x", "distance": a(4), "to": "centre"},
                           "y": {"side": "+y", "distance": a(6), "to": "centre"}})  # fmt: skip
        pocket = item("p", "pocket", on={"item": "b", "face": "+x"}, shape=pick("rectangle"),
                      length=a(3.2), width=a(5), depth=a(50), corner_radius=a(0.6),
                      place={"y": {"side": "+y", "distance": a(7.3), "to": "edge"},
                             "z": {"side": "-z", "distance": a(0.8), "to": "edge"}})  # fmt: skip
        spec = read([block, hole, pocket])
        part = oracle(spec, place(spec))
        # The bore round (26, 14), radius 1.5, under the floor at z = 1; the
        # pocket's rounding round (y, z) = (12.1, 1.4), radius 0.6.
        y = 12.1 + math.sqrt(0.6**2 - 0.4**2)
        corner = np.array([26 + math.sqrt(1.5**2 - (14 - y) ** 2), y, 1.0])
        way = np.array([-1.0, 0.0, 0.0])  # along the pocket's edge, into the bore
        wedge = np.array([5.0, 1.0, 1.0])  # into the material's wedge past the corner
        at = np.array([corner, corner + 2e-8 * way, corner + 1e-5 * way])
        self.assertEqual(
            [int(s) for s in part.classify(np.vstack([at, [corner + 1e-4 * wedge]]))],
            [Side.ON, Side.OUT, Side.OUT, Side.IN],
        )
        self.assertEqual(part.witness(at, OFF).tolist(), [True, True, False])

    def test_where_a_rounded_corner_touches_a_wall(self) -> None:
        """Along the line where a pocket's rounded corner touches another pocket's wall, tangent, the part's surface has a witness (part 9213).

        A slot along x, its +y wall at y = 2, and a pocket up from the
        bottom whose -y wall is that plane: the two open into each other
        where their walls are one, and beside it each rounded corner leaves
        a cusp of material against the slot's wall, its edge along the line
        the corner touches the wall at (x = -1.5 and 1.5). Every facet there
        lies in one plane, so the part's first-order shape sees only the
        plane's two sides, both in the air; nor along the pieces, until they
        turn apart past what it tells apart (some 2e-6 mm from the line
        here). Walking along them from the line finds the cusp's surface;
        where the walls are one, no surface.
        """
        block = item("b", "block", length=a(60), width=a(40), height=a(20))
        slot = item("s", "pocket", on={"item": "b", "face": "-x"}, shape=pick("rectangle"),
                    length=a(4), width=a(8), depth=a(50),
                    place={"y": {"side": "+y", "distance": a(18), "to": "edge"},
                           "z": {"side": "-z", "distance": a(6), "to": "edge"}})  # fmt: skip
        pocket = item("p", "pocket", on={"item": "b", "face": "-z"}, shape=pick("rectangle"),
                      length=a(6), width=a(10), depth=a(16), corner_radius=a(1.5),
                      place={"x": {"side": "-x", "distance": a(27), "to": "edge"},
                             "y": {"side": "+y", "distance": a(8), "to": "edge"}})  # fmt: skip
        spec = read([block, slot, pocket])
        part = oracle(spec, place(spec))
        line = np.array(
            [[-1.5, 2.0, 6.5], [-1.5, 2.0, 10.0], [-1.5, 2.0, 13.5], [1.5, 2.0, 10.0]]
        )
        one_wall = np.array([[0.0, 2.0, 10.0], [-1.0, 2.0, 7.0], [1.0, 2.0, 12.0]])
        cusp = np.array([[-2.5, 2.0, 10.0], [-2.5, 2.0001, 10.0], [-2.5, 1.9999, 10.0]])
        self.assertEqual(
            [int(s) for s in part.classify(np.vstack([line, one_wall, cusp]))],
            [Side.OUT] * 7 + [Side.ON, Side.IN, Side.OUT],
        )
        self.assertEqual(part.witness(line, OFF).tolist(), [True] * 4)
        self.assertEqual(part.witness(one_wall, OFF).tolist(), [False] * 3)


class _Plane(Patch):
    """A whole plane, as a patch: all a meeting asks of a piece is its nearest point."""

    def __init__(self, origin: Any, normal: Any) -> None:
        self.origin = np.asarray(origin, dtype=float)
        way = np.asarray(normal, dtype=float)
        self.normal = way / math.sqrt(float((way * way).sum()))

    def foot(self, x: Any) -> Any:
        x = np.asarray(x, dtype=float)
        return x - float(((x - self.origin) * self.normal).sum()) * self.normal


class TwoPiecesMeeting(unittest.TestCase):
    """Where two pieces meet near a point: by projecting onto each in turn, or at a small angle by Newton's steps (part 1880)."""

    def test_at_a_small_angle(self) -> None:
        """Two planes meeting along the x axis at 0.002 rad: projecting in turn creeps, two hundred rounds leaving it far from the first; Newton's steps come to the nearest point where they meet."""
        from forge_checks.oracle import _meet, _meet_steeply

        angle = 0.002
        floor = _Plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        tilted = _Plane((0.0, 0.0, 0.0), (0.0, -math.sin(angle), math.cos(angle)))
        x = np.array([1.0, 0.3, 0.2])
        self.assertIsNone(_meet([floor, tilted], x))
        met = _meet_steeply(floor, tilted, x)
        assert met is not None
        np.testing.assert_allclose(met, [1.0, 0.0, 0.0], atol=1e-9)
        # From a point on either one (part 5035: a built point on a floor, beside a leaning hole's window).
        for on in ([1.0, 1e-6, 0.0], [1.0, 1e-6 * math.cos(angle), 1e-6 * math.sin(angle)]):
            for first, second in ((floor, tilted), (tilted, floor)):
                met = _meet_steeply(first, second, np.array(on))
                assert met is not None
                self.assertLessEqual(float(np.abs(first.foot(met) - met).max()), 1e-12)
                self.assertLessEqual(float(np.abs(second.foot(met) - met).max()), 1e-12)
                np.testing.assert_allclose(met, [1.0, 0.0, 0.0], atol=1e-9)

    def test_steeply_where_they_meet_squarely(self) -> None:
        from forge_checks.oracle import _meet, _meet_steeply

        floor = _Plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        wall = _Plane((0.0, 2.0, 0.0), (0.0, 1.0, 0.0))
        x = np.array([3.0, 2.5, 0.4])
        both = (_meet([floor, wall], x), _meet_steeply(floor, wall, x))
        for met in both:
            assert met is not None
            np.testing.assert_allclose(met, [3.0, 2.0, 0.0], atol=1e-9)

    def test_parallel_pieces_do_not_meet(self) -> None:
        from forge_checks.oracle import _meet, _meet_steeply

        floor = _Plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        above = _Plane((0.0, 0.0, 1.0), (0.0, 0.0, 1.0))
        x = np.array([0.5, 0.5, 0.25])
        self.assertIsNone(_meet([floor, above], x))
        self.assertIsNone(_meet_steeply(floor, above, x))


class Roundings(unittest.TestCase):
    """Roundings at their limits and where they meet other things, worked out by hand (found by review)."""

    def sides(
        self, items: list[dict[str, object]], points: list[tuple[float, float, float]]
    ) -> list[int]:
        spec = read(items)
        return [
            int(s)
            for s in oracle(spec, place(spec)).classify(np.array(points, dtype=float))
        ]

    def test_a_joint_is_rounded_by_its_own_copy_only(self) -> None:
        """Generated part 874: a boss's joint bevelled, on a face whose far edge a block hangs over. The face's edge is a corner under the block, and the joint's chain runs round it, but that corner is no part of the boss's joint."""
        from forge_eval.generator import render
        from v2_regressions import REGRESSIONS

        spec = read(list(render(REGRESSIONS[874][1]).items))
        stretches = [r for r in oracle(spec, place(spec)).rounded if r.item == "round2"]
        self.assertEqual([type(r.edge).__name__ for r in stretches], ["RoundEdge"])

    def test_a_chamfer_to_the_middle(self) -> None:
        """A bevel as wide as the rim's radius: what is left is a cone's point, not a cut slab."""
        rod = item("c", "cylinder", diameter=a(30), length=a(20))
        bevel = item("r", "chamfer", edges={"of": "c", "which": "top"}, size=a(15))
        # Kept: z <= 20 - rho. (0, 0, 19.5) and (10, 0, 8) in; (10, 0, 11) out; the point, a cone's apex, unknown.
        self.assertEqual(self.sides([rod, bevel], [(0, 0, 19.5), (0, 0, 10), (10, 0, 8), (10, 0, 11), (0, 0, 20)]),
                         [Side.IN, Side.IN, Side.IN, Side.OUT, Side.UNKNOWN])  # the point: a cone's apex  # fmt: skip
        cone = item("c", "cone", base_diameter=a(30), top_diameter=a(10), length=a(20))
        bevel = item("r", "chamfer", edges={"of": "c", "which": "top"}, size=a(5))
        self.assertEqual(
            self.sides([cone, bevel], [(0, 0, 19), (3, 0, 17), (6, 0, 16)]),
            [Side.IN] * 3,
        )
        dome = item("d", "sphere", diameter=a(20), portion=pick("upper_half"))
        bevel = item("r", "chamfer", edges={"of": "d", "which": "bottom"}, size=a(10))
        self.assertEqual(
            self.sides([dome, bevel], [(0, 0, 1), (0, 0, 5), (1, 0, 3)]), [Side.IN] * 3
        )

    def test_a_pocket_floor_bevelled_to_the_middle(self) -> None:
        """A round pocket's floor (10 across, 8 deep in 20) bevelled 5: the fill is z - 12 < rho, the rest air."""
        plate = item("plate", "block", length=a(80), width=a(50), height=a(20))
        pocket = item(
            "p",
            "pocket",
            on={"item": "plate", "face": "+z"},
            shape=pick("circle"),
            diameter=a(10),
            depth=a(8),
        )
        bevel = item("r", "chamfer", edges={"of": "p", "which": "bottom"}, size=a(5))
        self.assertEqual(self.sides([plate, pocket, bevel], [(0, 0, 13), (1, 0, 15), (0, 0, 16.9), (4, 0, 14)]),
                         [Side.OUT, Side.OUT, Side.OUT, Side.IN])  # fmt: skip

    def test_edges_named_on_some_copies_or_where_they_may_be(self) -> None:
        """Two rods on a plate, one hanging over its edge: only it has a bottom rim. Vertical edges inside the top's zones."""
        plate = item("plate", "block", length=a(60), width=a(40), height=a(5))
        rods = item("c", "cylinder", on={"item": "plate", "face": "+z"}, diameter=a(10), length=a(8),
                    place={"pattern": {"row": {"axis": pick("x"), "count": {"count": 2, "from": SAY}, "pitch": a(20)}},
                           "x": {"offset": a(24)}})  # fmt: skip
        rim = item("r", "fillet", edges={"of": "c", "which": "bottom"}, radius=a(1))
        spec = read([plate, rods, rim])
        oracle(spec, place(spec))
        block = item("box", "block", length=a(40), width=a(30), height=a(5))
        top = item("t", "fillet", edges={"of": "box", "which": "top"}, radius=a(3))
        vertical = item(
            "v", "fillet", edges={"of": "box", "which": "vertical"}, radius=a(1)
        )
        spec = read([block, top, vertical])
        part = oracle(spec, place(spec))
        self.assertEqual(
            part.classify(np.array([[0.0, 0, 2.5], [19.9, 14.9, 1.0]])).tolist(),
            [Side.IN, Side.UNKNOWN],
        )

    def test_a_round_ended_tab_s_edges_run_into_its_end(self) -> None:
        """Where a tab's straight edges run on into its round end, their rounding blends: bounded there."""
        tab = item("tab", "tab", on={"item": "plate", "face": "+z"}, length=a(20), width=a(10), thickness=a(4),
                   thickness_along=pick("x"), end=pick("round"))  # fmt: skip
        rounding = item(
            "f", "fillet", edges={"of": "tab", "which": "vertical"}, radius=a(1)
        )
        self.assertEqual(self.sides([PLATE, tab, rounding], [(1.95, 4.95, 19.99), (1.95, 4.95, 20.001), (1.95, 4.95, 10)]),
                         [Side.UNKNOWN, Side.UNKNOWN, Side.OUT])  # fmt: skip

    def test_a_round_that_runs_off_its_face(self) -> None:
        """A hole's rim half a millimetre from the plate's side, rounded 2: bounded where the round would run off the face."""
        hole = item("h", "hole", on={"item": "plate", "face": "+z"}, diameter=a(6), depth={"through": True, "from": SAY},
                    place={"x": {"side": "+x", "distance": a(3.5), "to": "centre"}})  # fmt: skip
        rim = item("f", "fillet", edges={"of": "h", "which": "top"}, radius=a(2))
        # Near the plate's side, unknown; across the hole, where the face is all there, the round is exact.
        self.assertEqual(self.sides([PLATE, hole, rim], [(39.9, 0, 4.0), (39.9, 0, 4.9), (33.6, 0, 4.9), (32.5, 0, 4.5)]),
                         [Side.UNKNOWN, Side.UNKNOWN, Side.OUT, Side.IN])  # fmt: skip

    def test_zones_stay_near_what_they_bound(self) -> None:
        """A blind hole's rim on a rod, rounded: nothing past the rod's axis is unknown. A dome's rim stopped by a block."""
        rod = item("rod", "cylinder", diameter=a(10), length=a(40), axis=pick("x"))
        hole = item(
            "h", "hole", on={"item": "rod", "face": "side"}, diameter=a(2), depth=a(2)
        )
        rim = item("f", "fillet", edges={"of": "h", "which": "top"}, radius=a(1))
        self.assertEqual(
            self.sides([rod, hole, rim], [(20, -2, 0), (20, -3, 0), (20, -4, 0)]),
            [Side.IN] * 3,
        )
        dome = item("d", "sphere", diameter=a(20), portion=pick("upper_half"))
        block = item(
            "b",
            "block",
            on={"item": "d", "face": "-end"},
            length=a(4),
            width=a(4),
            height=a(3),
            place={"x": {"offset": a(9)}},
        )
        rim = item("f", "fillet", edges={"of": "d", "which": "bottom"}, radius=a(4.9))
        # The rounding's ball (4.9, nearly half the dome) takes the rim back to 1.4 from the axis; its
        # zones where the block stops it (at (9.8, +-2, 0)) reach 16.9, its ball's touch on the dome 12 off.
        self.assertEqual(
            self.sides(
                [dome, block, rim],
                [(-9, 0, 1), (-9.5, 0, 0.3), (-8.5, 0, 0.2), (-1, 0, 3)],
            ),
            [Side.OUT, Side.OUT, Side.OUT, Side.UNKNOWN],
        )

    def test_a_tray_s_walls_behind_its_rounded_floor(self) -> None:
        """A tray's floor 4 thick, its walls 2, its floor's edges rounded 5 (or bevelled): against every face's distance (shell.md)."""
        box = item("box", "block", length=a(100), width=a(60), height=a(20))
        rng = np.random.default_rng(4)
        for fillet in (True, False):
            rounding = item("r", "fillet" if fillet else "chamfer", edges={"of": "box", "which": "bottom"},
                            **({"radius": a(5)} if fillet else {"size": a(5)}))  # fmt: skip
            tray = item(
                "s",
                "shell",
                of="box",
                thickness=a(2),
                floor=a(4),
                open={"faces": ["+z"], "from": SAY},
            )
            spec = read([box, rounding, tray])
            part = oracle(spec, place(spec))
            points = rng.uniform((-52, -32, -2), (52, 32, 22), size=(40000, 3))
            sides = part.classify(points)
            known = (sides == Side.IN) | (sides == Side.OUT)
            self.assertGreater(int(known.sum()), 30000)
            truth = np.array([_tray_truth(p, fillet) for p in points[known]])
            self.assertEqual(int(((sides[known] == Side.IN) != truth).sum()), 0, fillet)
            self.assertGreater(
                int((~truth & (np.abs(points[known, 2] - 3) < 1)).sum()), 100
            )

    def test_a_cup_and_a_dome_s_walls_behind_their_rounded_rims(self) -> None:
        """A cup (floor 4, wall 2, its floor's rim rounded 5) and a sealed dome (floor 3, wall 2, rim rounded 4), in the section through the axis."""
        rng = np.random.default_rng(5)
        cup = [item("c", "cylinder", diameter=a(30), length=a(40)),
               item("r", "fillet", edges={"of": "c", "which": "bottom"}, radius=a(5)),
               item("s", "shell", of="c", thickness=a(2), floor=a(4), open={"faces": ["+end"], "from": SAY})]  # fmt: skip
        dome = [item("d", "sphere", diameter=a(40), portion=pick("upper_half")),
                item("r", "fillet", edges={"of": "d", "which": "bottom"}, radius=a(4)),
                item("s", "shell", of="d", thickness=a(2), floor=a(3), open={"faces": [], "from": SAY})]  # fmt: skip
        for items, truth in ((cup, _cup_truth), (dome, _dome_truth)):
            spec = read(items)
            part = oracle(spec, place(spec))
            lo, hi = np.array(part.lo), np.array(part.hi)
            points = rng.uniform(lo - 1, hi + 1, size=(40000, 3))
            sides = part.classify(points)
            known = (sides == Side.IN) | (sides == Side.OUT)
            self.assertGreater(int(known.sum()), 30000)
            rho = np.hypot(points[known, 0], points[known, 1])
            want = np.array(
                [truth(r, z) for r, z in zip(rho, points[known, 2], strict=True)]
            )
            self.assertEqual(
                int(((sides[known] == Side.IN) != want).sum()), 0, items[0]["kind"]
            )


def _cup_truth(rho: float, z: float) -> bool:
    """In the cup above (radius 15, 40 long, floor's rim rounded 5): in it, and not at least each wall's thickness from every face."""
    if not (rho <= 15 and 0 <= z <= 40):
        return False
    dx, dz = rho - 10, z - 5
    sector = dx > 0 and dz < 0
    if sector and math.hypot(dx, dz) > 5:
        return False
    rounding = (
        abs(math.hypot(dx, dz) - 5)
        if sector
        else min(math.hypot(rho - 10, z), math.hypot(rho - 15, z - 5))
    )
    floor = math.hypot(max(rho - 10, 0.0), z)
    side = math.hypot(15 - rho, max(5 - z, 0.0))
    return not (floor >= 4 and side >= 2 and rounding >= 2)


def _dome_truth(rho: float, z: float) -> bool:
    """In the sealed dome above (radius 20, rim rounded 4): in it, and not at least each wall's thickness from every face."""
    r, big = 4.0, 20.0
    c = (math.sqrt((big - r) ** 2 - r * r), r)  # the rounding ball's centre
    touch_floor = (c[0], 0.0)
    touch_ball = (c[0] * big / (big - r), c[1] * big / (big - r))
    dx, dz = rho - c[0], z - c[1]
    # The rounding's sector: from straight down from its centre round to out along it from the dome's centre.
    sector = dx >= 0 and dx * c[1] >= dz * c[0]
    if math.hypot(rho, z) > big or z < 0:
        return False
    if sector and math.hypot(dx, dz) > r:
        return False
    rounding = (
        abs(math.hypot(dx, dz) - r)
        if sector
        else min(math.dist((rho, z), touch_floor), math.dist((rho, z), touch_ball))
    )
    floor = math.hypot(max(rho - c[0], 0.0), z)
    above = (
        rho * touch_ball[1] <= z * touch_ball[0]
    )  # within the cap the rounding leaves of the dome's face
    surface = big - math.hypot(rho, z) if above else math.dist((rho, z), touch_ball)
    return not (floor >= 3 and surface >= 2 and rounding >= 2)


def _tray_truth(p: Array, fillet: bool) -> bool:
    """Whether a point is in the tray of the test above: in the rounded box, and not at least each wall's thickness from every face."""
    x, y, z = (float(c) for c in p)
    if not (abs(x) <= 50 and abs(y) <= 30 and 0 <= z <= 20):
        return False

    def corner(across: float) -> tuple[bool, float]:
        """In the rounded box across a floor edge (``across``: how far past the edge's start), and the distance to the rounding's face."""
        if fillet:
            dx, dz = across - 45, z - 5
            if dx > 0 and dz < 0:
                r = math.hypot(dx, dz)
                return r <= 5, abs(r - 5)
            return True, min(math.hypot(across - 45, z), math.hypot(across - 50, z - 5))
        # The bevel from (45, 0) to (50, 5): kept where z >= across - 45.
        inside = z >= across - 45 - 1e-12
        t = min(max(((across - 45) + z) / 10, 0.0), 1.0)
        return inside, math.hypot(across - (45 + 5 * t), z - 5 * t)

    in_x, round_x = corner(abs(x)) if abs(x) > 40 else (True, math.inf)
    in_y, round_y = corner(abs(y) + 20) if abs(y) > 20 else (True, math.inf)
    if not (in_x and in_y):
        return False
    floor = math.hypot(max(abs(x) - 45, 0.0), math.hypot(max(abs(y) - 25, 0.0), z))
    side_x = math.hypot(50 - abs(x), max(5 - z, 0.0))
    side_y = math.hypot(30 - abs(y), max(5 - z, 0.0))
    hollow = floor >= 4 and min(side_x, side_y, round_x, round_y) >= 2
    return not hollow


class Voids(unittest.TestCase):
    """The sealed voids, where nothing sits too close to say."""

    BOX = item("box", "block", length=a(40), width=a(40), height=a(20))
    CLOSED = item(
        "hollow", "shell", of="box", thickness=a(2), open={"faces": [], "from": SAY}
    )

    def voids(
        self, items: list[dict[str, object]]
    ) -> tuple[int | None, tuple[str, ...]]:
        spec = read(items)
        self.assertEqual(solve(spec).issues, [])
        found = oracle(spec, place(spec)).expected_topology()
        return found.voids, found.unchecked

    def test_air_left_by_posts_filling_a_pocket(self) -> None:
        """Posts fill a covered pocket but for a 0.2 mm cube of air, far finer than the grid: still a void."""

        def at(x: float, y: float) -> dict[str, object]:
            return {"x": {"offset": a(x)}, "y": {"offset": a(y)}}

        floor = {"item": "pk", "face": "bottom"}
        items = [
            PLATE,
            item("pk", "pocket", on={"item": "plate", "face": "+z"}, shape=pick("rectangle"), length=a(10.15),
                 width=a(10.15), depth=a(3), place=at(0.075, 0.075)),
            item("p1", "post", on=floor, length=a(9.95), width=a(10.15), height=a(3), place=at(-0.1, 0.0)),
            item("p2", "post", on=floor, length=a(0.2), width=a(9.95), height=a(3), place=at(4.975, -0.1)),
            item("p3", "post", on=floor, length=a(0.2), width=a(0.2), height=a(2.8), place=at(4.975, 4.975)),
            item("lid", "block", on={"item": "plate", "face": "+z"}, length=a(14), width=a(14), height=a(1)),
        ]  # fmt: skip
        self.assertEqual(self.voids(items)[0], 1)

    def test_a_pipe_between_two_hollows(self) -> None:
        """Two hollows joined by a 0.2 mm pipe, left where blocks fill the wall cut between them: one void."""
        box = Prism.box
        steps = [
            Step("plate", 0, True, box((-40, -25, 0), (40, 25, 10))),
            Step("a", 0, False, box((-10, -5, 2), (-1.5, 6, 8))),
            Step("b", 0, False, box((1.5, -5, 2), (10, 6, 8))),
            Step("wall", 0, False, box((-1.5, -5, 2), (1.5, 6, 8))),
            Step("f1", 0, True, box((-1.5, -5, 2), (1.5, 4.95, 8))),
            Step("f2", 0, True, box((-1.5, 5.15, 2), (1.5, 6, 8))),
            Step("f3", 0, True, box((-1.5, 4.95, 2), (1.5, 5.15, 4.8))),
            Step("f4", 0, True, box((-1.5, 4.95, 5.0), (1.5, 5.15, 8))),
        ]
        self.assertEqual(_assemble(steps).expected_topology().voids, 1)

    def test_a_vent_opens_a_hollow(self) -> None:
        vent = item(
            "vent",
            "hole",
            on={"item": "box", "face": "-x"},
            diameter=a(3),
            depth={"through": True, "from": SAY},
        )
        self.assertEqual(self.voids([self.BOX, self.CLOSED, vent])[0], 0)
        self.assertEqual(self.voids([self.BOX, self.CLOSED])[0], 1)

    def test_a_thin_skin_is_left_unsaid(self) -> None:
        """A dimple leaving 0.1 mm of wall over the hollow: closed, but too thin to say on any grid allowed."""
        dimple = item(
            "dimple",
            "hole",
            on={"item": "box", "face": "+z"},
            diameter=a(6),
            depth=a(1.9),
        )
        voids, why = self.voids([self.BOX, self.CLOSED, dimple])
        self.assertIsNone(voids)
        self.assertIn("comes within", why[0])

    def test_a_large_thin_walled_box(self) -> None:
        big = item("box", "block", length=a(200), width=a(150), height=a(100))
        self.assertEqual(self.voids([big, self.CLOSED])[0], 1)

    def test_a_wedge_of_air_between_grid_points(self) -> None:
        """A cone flaring out over the plate it stands on: the air under its overhang thins to nothing, and is the outside."""
        cone = item(
            "cup",
            "cone",
            on={"item": "plate", "face": "+z"},
            base_diameter=a(20),
            top_diameter=a(40),
            length=a(30),
        )
        self.assertEqual(
            self.voids([PLATE, cone]), (0, ("through-holes are not counted yet",))
        )


class Probes(unittest.TestCase):
    def test_every_cell_of_the_planes_is_tried(self) -> None:
        rng = random.Random(9)
        for _ in range(300):
            k = rng.randint(1, 5)
            normals = [np.array([rng.gauss(0, 1) for _ in range(3)]) for _ in range(k)]
            if rng.random() < 0.3:
                normals.append(-normals[0])  # the same plane, the other way
            if rng.random() < 0.3 and k >= 2:
                normals.append(normals[0] + normals[1])  # three planes through one line
            found = probes(normals)
            signs = {
                tuple(np.sign(found[i] @ n) for n in normals) for i in range(len(found))
            }
            sample = np.array(
                [[rng.gauss(0, 1) for _ in range(3)] for _ in range(4000)]
            )
            seen = {tuple(np.sign(d @ n) for n in normals) for d in sample}
            self.assertLessEqual(seen, signs, normals)
            self.assertNotIn(0.0, {s for sig in signs for s in sig})


class Letters(unittest.TestCase):
    """A line of letters is the pinned font's outlines, exactly (docs/V2-stage4.md, 7.1)."""

    TEXT = "FoRGE&jÇ"

    def part(self, mode: str, face: str = "+z") -> Oracle:
        letters = item("t", "text", on={"item": "plate", "face": face}, text={"text": self.TEXT, "from": SAY},
                       height=a(10), depth=a(1), mode=pick(mode))  # fmt: skip
        spec = read([PLATE, letters])
        return oracle(spec, place(spec))

    def test_every_point_is_where_the_font_puts_it(self) -> None:
        # The plate is 80 x 50 x 5; the line's box centred on its +z face (on its -z face, reading the
        # right way round from below: along -x).
        rng = np.random.default_rng(3)
        points = rng.uniform([-40.5, -25.5, -1.5], [40.5, 25.5, 6.5], size=(20000, 3))
        x, y, z = points.T
        plate = (np.abs(x) <= 40) & (np.abs(y) <= 25) & (z >= 0) & (z <= 5)
        length = text_width(self.TEXT, 10.0)
        for mode, face, right in (
            ("engrave", "+z", 1.0),
            ("emboss", "+z", 1.0),
            ("engrave", "-z", -1.0),
        ):
            with self.subTest(mode=mode, face=face):
                ink = Ink.of(
                    self.TEXT, 10.0, right=right, at=(-right * length / 2, -5.0)
                )
                inside = ink.inside(x, y)
                if mode == "emboss":
                    expected = plate | (inside & (z >= 5) & (z <= 6))
                elif face == "+z":
                    expected = plate & ~(inside & (z > 4))
                else:
                    expected = plate & ~(inside & (z < 1))
                far = ink.distance(x, y) > 1e-6
                for level in (-1, 0, 1, 4, 5, 6):
                    far &= np.abs(z - level) > 1e-6
                found = self.part(mode, face).classify(points)
                self.assertFalse(np.any(found == Side.UNKNOWN))
                self.assertTrue(np.array_equal((found == Side.IN)[far], expected[far]))
        self.assertEqual(self.part("engrave").unchecked, ())

    def test_their_walls_floors_and_corners_are_on_the_surface(self) -> None:
        length = text_width(self.TEXT, 10.0)
        ink = Ink.of(self.TEXT, 10.0, at=(-length / 2, -5.0))
        part = self.part("engrave")
        rng = np.random.default_rng(4)
        x, y = rng.uniform(-length / 2, length / 2, 3000), rng.uniform(-6, 6, 3000)
        _, qa, qb, _, _ = ink.nearest(
            x, y
        )  # the edge's nearest points: on walls, and at corners
        _, inside_corner, _ = ink.facets(qa, qb, 1e-9)
        self.assertTrue(np.any(inside_corner))
        # Up a wall, at its foot (the floor) and its top (the face round it): on the surface, an inside
        # corner of the letters too (there the union of its two walls' half-spaces, met with the floor's).
        for level in (4.5, 4.0, 5.0):
            on = part.classify(np.stack([qa, qb, np.full_like(qa, level)], axis=1))
            self.assertTrue(np.all(on == Side.ON), level)


class WhatIsNotKnownExactly(unittest.TestCase):
    def test_regions_are_between_their_limits(self) -> None:
        region = item("r", "region", on={"item": "plate", "face": "-z"}, length=a(20), width=a(20), height=a(8),
                      describe={"text": "a grip", "from": SAY}, place={"x": {"offset": a(25)}})  # fmt: skip
        spec = read([PLATE, region])
        part = oracle(spec, place(spec))
        inner, outer = part.limits(np.array([[25, 0, -4], [0, 0, 2]], dtype=float))
        self.assertEqual(inner.tolist(), [-1, 1])
        self.assertEqual(outer.tolist(), [1, 1])
        self.assertEqual(
            part.classify(
                np.array([[25, 0, -4], [0, 0, 2], [0, 0, 6]], dtype=float)
            ).tolist(),
            [2, 1, -1],
        )
        self.assertEqual([u.item for u in part.unchecked], ["r"])

    def thread(self, designation: str, **fields: object) -> tuple[Oracle, Array, Array]:
        """A 10 mm rod 20 long, threaded: its oracle, and where its axis starts and the way it runs."""
        rod = item("rod", "cylinder", diameter=a(10), length=a(20))
        thread = item("t", "thread", of="rod", designation={"text": designation, "from": SAY},
                      hand=pick("right"), **fields)  # fmt: skip
        spec = read([rod, thread])
        placed = place(spec)
        copy = placed.copies["rod"][0]
        return (
            oracle(spec, placed),
            np.array(copy.point, dtype=float),
            np.array(copy.direction, dtype=float),
        )

    def test_a_thread_is_bounded_between_its_cylinders(self) -> None:
        """Over its length from the free end, the rod's material between its minor and major cylinders is unknown."""
        part, start, w = self.thread("M10", length=a(8))
        across = np.cross(w, [1.0, 0, 0] if abs(w[0]) < 0.9 else [0, 1.0, 0])
        across /= np.linalg.norm(across)
        minor = 5 - 5 / 8 * math.sqrt(3) / 2 * 1.5
        cases = [  # (distance from the axis, along it, what is there)
            (minor - 0.01, 15, Side.IN), (minor + 0.01, 15, Side.UNKNOWN), (5.0, 15, Side.UNKNOWN),
            (5.01, 15, Side.OUT), (4.6, 11.99, Side.IN), (4.6, 12.01, Side.UNKNOWN),
            (4.6, 20.0, Side.UNKNOWN), (2.0, 20.0, Side.ON), (4.6, 5.0, Side.IN), (5.0, 5.0, Side.ON),
            (2.0, 20.01, Side.OUT),
        ]  # fmt: skip
        points = np.array([start + z * w + r * across for r, z, _ in cases])
        self.assertEqual(part.classify(points).tolist(), [side for *_, side in cases])
        self.assertEqual(part.unchecked, ())

    def test_a_whole_thread_and_a_named_pitch(self) -> None:
        part, start, w = self.thread("M10x1")
        across = np.cross(w, [1.0, 0, 0] if abs(w[0]) < 0.9 else [0, 1.0, 0])
        across /= np.linalg.norm(across)
        minor = 5 - 5 / 8 * math.sqrt(3) / 2 * 1.0
        points = np.array(
            [
                start + z * w + r * across
                for r, z in ((minor - 0.01, 0.5), (minor + 0.01, 0.5), (4.6, 0.0))
            ]
        )
        self.assertEqual(
            part.classify(points).tolist(), [Side.IN, Side.UNKNOWN, Side.UNKNOWN]
        )

    def test_pitches(self) -> None:
        self.assertEqual(
            COARSE_PITCH, {size: pitch for size, (pitch, _) in TAPPED.items()}
        )
        self.assertEqual(
            [thread_pitch(d) for d in ("M8", "M8x1", "M2.5", "M7x1")],
            [1.25, 1.0, 0.45, 1.0],
        )
        with self.assertRaises(CannotMakeError):
            thread_pitch("M7")
        with self.assertRaises(CannotMakeError):
            self.thread("M7")


class RandomSpecs(unittest.TestCase):
    """The oracle on random specs of every kind (tests/v2_specs.py): made, or a CAN'T, and its answers agree with each other."""

    def test_random_specs(self) -> None:
        rng = np.random.default_rng(3)
        made, cant = 0, 0
        # The CAN'Ts random sizes run into (a 0.3 mm rounding on a 0.05 mm boss, an M8 on it).
        reasons = ("is bigger than the round edge it rounds", "none of the edges it names is left",
                   "thread is deeper than", "doesn't fit", "is as big as")  # fmt: skip
        for k, spec in enumerate(random_specs(20261022, 60)):
            with self.subTest(spec=k):
                try:
                    part = oracle(spec, place(spec))
                except CannotMakeError as e:
                    self.assertTrue(any(r in str(e) for r in reasons), str(e))
                    cant += 1
                    continue
                made += 1
                lo, hi = np.array(part.lo), np.array(part.hi)
                points = rng.uniform(lo - 1, hi + 1, size=(2000, 3))
                inner, outer = part.limits(points)
                # What the part must hold, it may hold.
                self.assertFalse(np.any((inner == Side.IN) & (outer == Side.OUT)))
                sides = part.classify(points)
                self.assertTrue(np.all(inner[sides == Side.IN] == Side.IN))
                self.assertTrue(np.all(outer[sides == Side.OUT] == Side.OUT))
                # Along random lines, each piece is one side all along.
                origins = rng.uniform(lo - 1, hi + 1, size=(20, 3))
                directions = rng.normal(size=(20, 3))
                directions[:10] = np.eye(3)[rng.integers(0, 3, 10)]
                directions /= np.linalg.norm(directions, axis=1)[:, None]
                lengths = np.full(20, float(np.linalg.norm(hi - lo)) + 2)
                found = part.along(origins, directions, lengths)
                for i in range(20):
                    t = found.t[found.start[i] : found.start[i + 1]]
                    pieces = found.pieces[
                        found.start[i] + i : found.start[i + 1] + i + 1
                    ]
                    u = rng.uniform(0, lengths[i], 100)
                    if len(t):
                        u = u[np.min(np.abs(u[:, None] - t[None, :]), axis=1) > 1e-7]
                    on_line = part.classify(origins[i] + u[:, None] * directions[i])
                    self.assertEqual(
                        on_line.tolist(), pieces[np.searchsorted(t, u)].tolist()
                    )
        self.assertGreater(made, 2 * cant)

    def test_coverage_and_voids_of_random_specs(self) -> None:
        self.coverage_and_voids(0)

    def test_coverage_and_voids_of_more_random_specs(self) -> None:
        self.coverage_and_voids(5)

    def coverage_and_voids(self, which: int) -> None:
        for k, spec in enumerate(random_specs(20261022, 60)):
            if k % 10 != which:
                continue
            with self.subTest(spec=k):
                try:
                    part = oracle(spec, place(spec))
                except CannotMakeError:
                    continue
                lo, hi = np.array(part.lo), np.array(part.hi)
                cover = part.coverage(max(float(max(hi - lo)) / 30, 0.25))
                behind = part.classify(cover.points - OFF * cover.normals)
                ahead = part.classify(cover.points + OFF * cover.normals)
                self.assertTrue(np.all((behind == Side.IN) & (ahead == Side.OUT)))
                topology = part.expected_topology()
                self.assertEqual(topology.solids, 1)
                self.assertTrue(topology.voids is not None or topology.unchecked[0])


class Speed(unittest.TestCase):
    def test_a_plate_of_two_thousand_holes(self) -> None:
        holes = item("h", "hole", on={"item": "plate", "face": "+z"}, diameter=a(1), depth={"through": True, "from": SAY},
                     place={"pattern": {"grid": {"count_x": {"count": 50, "from": SAY}, "count_y": {"count": 40, "from": SAY},
                                                  "pitch_x": a(1.5), "pitch_y": a(1.2)}}})  # fmt: skip
        big = item("plate", "block", length=a(100), width=a(60), height=a(5))
        spec = read([big, holes])
        part = oracle(spec, place(spec))
        points = np.random.default_rng(1).uniform(
            (-50, -30, -1), (50, 30, 6), size=(200_000, 3)
        )
        import time

        start = time.perf_counter()
        sides = part.classify(points)
        self.assertLess(time.perf_counter() - start, 60.0)
        self.assertGreater(int((sides == Side.IN).sum()), 50_000)
        self.assertTrue(math.isfinite(part.hi[0]))


if __name__ == "__main__":
    unittest.main()
