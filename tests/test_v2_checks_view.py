"""V2 stage 2: the proxy every check sees a view through (forge_checks.view).

The proxy passes on the protocol's questions and nothing else, refuses the
ones a view doesn't declare, and holds a view to its contract: an answer of
the wrong shape or with impossible values is a :class:`ViewError`, never
quietly used.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

import numpy as np
from forge_checks.mesh import MeshView, box_mesh
from forge_checks.view import (
    Box,
    Capability,
    Coverage,
    Crossings,
    NotAnswerableError,
    Resolution,
    Side,
    ViewError,
    ViewProxy,
    covered,
)
from forge_units import Interval
from v2_meshes import nearest_within

PROTOCOL = {
    "source", "capabilities", "classify", "distance", "near", "crossings", "volume",
    "bounds", "coverage", "topology", "faces", "edges",
}  # fmt: skip


def box() -> MeshView:
    return MeshView(box_mesh((0, 0, 0), (1, 1, 1)), source="mesh-file", deflection=0.0)


class Broken:
    """A view that answers everything wrongly."""

    source = "broken"
    capabilities = frozenset(Capability)
    secret = "how the part was made"

    def classify(self, points: Any) -> Any:
        return np.full(len(points), 7, dtype=np.int8)

    def distance(self, points: Any) -> Any:
        return -np.ones(len(points))

    def crossings(self, origins: Any, directions: Any) -> Any:
        return Crossings(
            np.zeros(0, np.int64), np.zeros(0), np.zeros(0, bool), np.zeros(1, bool)
        )

    def volume(self) -> Any:
        return 3.0

    def bounds(self) -> Any:
        return ((0, 0, 0), (1, 1, 1))

    def coverage(self, radius: float, within: Any = None) -> Any:
        return Coverage(
            np.zeros((1, 3)),
            np.array([[0, 0, 1.0]]),
            np.zeros(1, np.int64),
            np.zeros(1),
            radius * 2,
        )

    def topology(self) -> Any:
        return "fine"

    def faces(self) -> Any:
        return ["a face"]

    def edges(self) -> Any:
        return None


class NothingReachesRoundTheProxy(unittest.TestCase):
    def test_no_check_looks_inside_a_proxy(self) -> None:
        # The proxy's closure holds the view: Python can't hide it, so the rule
        # is kept on the source. Only view.py may name these.
        forbidden = re.compile(
            r"_answer|__closure__|cell_contents|__self__|__globals__|__code__|__dict__"
            r"|^\s*(import|from)\s+(gc|inspect|ctypes)\b",
            re.MULTILINE,
        )
        package = Path(__file__).resolve().parent.parent / "packages" / "forge_checks"
        files = sorted(package.rglob("*.py"))
        self.assertTrue(files)
        for path in files:
            if path.name == "view.py":
                continue
            found = forbidden.findall(path.read_text(encoding="utf-8"))
            self.assertEqual(found, [], path)


class TheProxy(unittest.TestCase):
    def test_it_passes_on_the_protocol_and_nothing_else(self) -> None:
        proxy = ViewProxy(box())
        public = {n for n in dir(proxy) if not n.startswith("_")}
        self.assertEqual(public, PROTOCOL)
        self.assertFalse(hasattr(proxy, "mesh"))
        self.assertFalse(hasattr(ViewProxy(Broken()), "secret"))
        with self.assertRaises(AttributeError):
            proxy.source = "changed"

    def test_it_answers_through_the_view(self) -> None:
        proxy = ViewProxy(box())
        points = np.array([[0.5, 0.5, 0.5], [2, 2, 2]], dtype=float)
        self.assertEqual(proxy.classify(points).tolist(), [Side.IN, Side.OUT])
        self.assertEqual(proxy.distance(points).tolist()[0], 0.5)
        found = proxy.crossings(
            np.array([[0.3, 0.4, -1.0]]), np.array([[0.0, 0.0, 7.0]])
        )
        np.testing.assert_allclose(found.t, [1.0, 2.0])  # directions are made unit
        self.assertTrue(proxy.volume().contains(1.0))
        self.assertEqual(proxy.bounds(), Box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
        self.assertLessEqual(proxy.coverage(0.25).radius, 0.25)
        self.assertTrue(proxy.topology().sound)

    def test_it_refuses_what_the_view_does_not_answer(self) -> None:
        proxy = ViewProxy(box())
        with self.assertRaises(NotAnswerableError):
            proxy.faces()
        with self.assertRaises(NotAnswerableError):
            proxy.edges()

    def test_it_tidies_what_is_asked(self) -> None:
        proxy = ViewProxy(box())
        with self.assertRaises(ValueError):
            proxy.classify(np.array([[np.nan, 0, 0]]))
        with self.assertRaises(ValueError):
            proxy.classify(np.array([0.0, 0.0, 0.0]))
        with self.assertRaises(ValueError):
            proxy.crossings(np.zeros((1, 3)), np.zeros((1, 3)))
        with self.assertRaises(ValueError):
            proxy.coverage(0.0)
        with self.assertRaises(ValueError):
            proxy.coverage(1.0, ((0, 0, 0), (1, 1, 1)))  # type: ignore[arg-type]

    def test_it_holds_a_view_to_its_contract(self) -> None:
        proxy = ViewProxy(Broken())
        points = np.zeros((2, 3))
        for ask in (
            lambda: proxy.classify(points),
            lambda: proxy.distance(points),
            lambda: proxy.crossings(points, np.ones((2, 3))),
            proxy.volume,
            proxy.bounds,
            lambda: proxy.coverage(1.0),
            proxy.topology,
            proxy.faces,
            proxy.edges,
        ):
            with self.assertRaises(ViewError):
                ask()

    def test_answers_are_frozen(self) -> None:
        cover = ViewProxy(box()).coverage(0.5)
        with self.assertRaises(ValueError):
            cover.points[0, 0] = 9.0

    def test_contract_types_check_themselves(self) -> None:
        with self.assertRaises(ValueError):
            Box((0.0, 0.0, 1.0), (1.0, 1.0, 0.0))
        with self.assertRaises(ViewError):
            Crossings(
                np.array([0]), np.array([-1.0]), np.array([True]), np.array([False])
            )
        with self.assertRaises(ViewError):
            Crossings(
                np.array([0, 0]),
                np.array([2.0, 1.0]),
                np.array([True, False]),
                np.array([False]),
            )
        with self.assertRaises(ViewError):
            Coverage(
                np.zeros((1, 3)),
                np.array([[0, 0, 2.0]]),
                np.zeros(1, np.int64),
                np.zeros(1),
                1.0,
            )
        self.assertIsInstance(Interval(0, 1), Interval)


class FinerWhereAsked(unittest.TestCase):
    """A coverage at a resolution: its radius everywhere, finer in its finer boxes (docs/V2-stage4.md, 13.10)."""

    plate = Box((0.0, 0.0, 0.0), (100.0, 80.0, 10.0))
    corner = Box((-1.0, -1.0, 8.0), (6.0, 5.0, 11.0))

    def view(self) -> ViewProxy:
        return ViewProxy(
            MeshView(
                box_mesh(self.plate.lo, self.plate.hi),
                source="mesh-file",
                deflection=0.0,
            )
        )

    def test_the_radius_at_a_place(self) -> None:
        both = Resolution(
            0.5, ((self.corner, 0.1), (Box((0.0, 0.0, 9.0), (1.0, 1.0, 11.0)), 0.02))
        )
        points = np.array([[3.0, 3.0, 10.0], [0.5, 0.5, 10.0], [50.0, 50.0, 10.0]])
        self.assertEqual(both.at(points).tolist(), [0.1, 0.02, 0.5])
        # A box that comes within the reach counts.
        self.assertEqual(both.at(np.array([[6.5, 3.0, 10.0]]), 0.6).tolist(), [0.1])
        self.assertEqual(both.finest, 0.02)
        self.assertEqual(both.within(Box((5.0, 4.0, 9.0), (7.0, 7.0, 10.0))), 0.1)
        self.assertEqual(both.within(Box((50.0, 4.0, 9.0), (70.0, 7.0, 10.0))), 0.5)
        self.assertEqual(both.scaled(4.0).at(points).tolist(), [0.025, 0.005, 0.125])
        with self.assertRaises(ValueError):
            Resolution(0.5, ((self.corner, 0.5),))
        with self.assertRaises(ValueError):
            Resolution(0.0)

    def test_every_point_within_the_radius_there_and_few_more(self) -> None:
        view = self.view()
        resolution = Resolution(0.5, ((self.corner, 0.05),))
        cover = covered(view, resolution)
        self.assertEqual(cover.radius, 0.5)
        everywhere, finer = view.coverage(0.5), view.coverage(0.05, self.corner)
        self.assertLess(len(cover.points), len(everywhere.points) + len(finer.points))
        self.assertLess(len(cover.points), len(view.coverage(0.05).points) / 50)
        # The top face sampled densely: within the finer radius in the box, the radius elsewhere.
        rng = np.random.default_rng(3)
        n = 400000
        top = np.column_stack(
            [rng.uniform(0, 100, n), rng.uniform(0, 80, n), np.full(n, 10.0)]
        )
        inside = np.all((top >= self.corner.lo) & (top <= self.corner.hi), axis=1)
        self.assertGreater(int(inside.sum()), 1000)
        near = nearest_within(cover.points, top[inside], 0.05 * (1 + 1e-9))
        self.assertTrue(np.isfinite(near).all())
        self.assertTrue(np.isfinite(nearest_within(cover.points, top, 0.5)).all())
        # Points of the coarser coverage deep in the finer box are left out.
        deep = np.all(
            (everywhere.points > np.add(self.corner.lo, 0.5))
            & (everywhere.points < np.subtract(self.corner.hi, 0.5)),
            axis=1,
        )
        self.assertGreater(int(deep.sum()), 10)
        kept = {tuple(p) for p in cover.points.tolist()}
        fine = {tuple(p) for p in finer.points.tolist()}
        # (A corner of the plate is a point of both.)
        self.assertFalse(
            any(tuple(p) in kept - fine for p in everywhere.points[deep].tolist())
        )

    def test_with_no_finer_box_it_is_the_view_s_coverage(self) -> None:
        view = self.view()
        np.testing.assert_array_equal(
            covered(view, Resolution(0.4)).points, view.coverage(0.4).points
        )


if __name__ == "__main__":
    unittest.main()
