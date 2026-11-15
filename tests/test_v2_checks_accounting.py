"""V2 stage 2, step 4: face accounting, topology and volume, on reference parts correct and damaged.

Every reference part (tests/v2_reference.py), built by hand with manifold3d,
must be accounted for exactly: every built point on a spec surface, every
spec point built. Damaged on purpose, each must fail, and fail where the
damage is: an extra pin, an unasked chamfer, a sealed void, a skin over a
hole, a bump or a dent of twice the tolerance, a missing hole or
counterbore, a rounding of the wrong radius or a chamfer for a fillet, a
mesh coarser than it says. Near-misses must pass: a coarser mesh that says
so, vertices jittered within the deflection, coordinates in float32, the
part moved by less than its tolerance.
"""

from __future__ import annotations

import functools
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
from forge_checks.accounting import FLOOR, MARGIN, Accounting, account_faces
from forge_checks.classes import Verdict
from forge_checks.mesh import Mesh, MeshView
from forge_checks.oracle import Oracle, oracle
from forge_checks.place import place
from forge_checks.topology import judge_topology, judge_volume
from forge_checks.view import ViewProxy
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v2_reference
from v2_meshes import HAVE_MANIFOLD, triangles
from v2_occ import needs_occ
from v2_reference import MARGIN as DEFLECTION
from v2_reference import PARTS, ball, box, corner, item, on, rod, through
from v2_specs import a, read

Array = NDArray[np.float64]

#: The coverage radius the reference parts are accounted to.
RADIUS = 1.0
#: The tolerance a reference mesh's points get: its deflection and a tenth.
T = DEFLECTION * (1 + MARGIN)
#: The reference parts whose topology and volume are judged here.
WEIGHED = ("plate with holes", "tray", "closed box", "two hollows", "rounded block")


def view_of(solid: Any, deflection: float = DEFLECTION) -> ViewProxy:
    return ViewProxy(
        MeshView(
            Mesh.from_triangles(triangles(solid)),
            source="mesh-file",
            deflection=deflection,
        )
    )


def part_of(items: list[dict[str, Any]]) -> Oracle:
    spec = read(items)
    return oracle(spec, place(spec))


# A small plate: 40 x 30 x 5, a through hole of 6 at its middle, a blind
# hole of 4, 2 deep, at x = 10, and a counterbored hole at x = -10.
PLATE = [
    item("plate", "block", length=a(40), width=a(30), height=a(5)),
    item("through", "hole", on=on("plate", "+z"), diameter=a(6), depth=through()),
    item("blind", "hole", on=on("plate", "+z"), diameter=a(4), depth=a(2), place={"x": {"offset": a(10)}}),
    item("bored", "hole", on=on("plate", "+z"), diameter=a(3), depth=through(),
         counterbore={"diameter": a(6), "depth": a(1.5)}, place={"x": {"offset": a(-10)}}),
]  # fmt: skip


def plate(
    *, blind: bool = True, counterbore: bool = True, through_hole: bool = True
) -> Any:
    """The small plate as the definitions make it, or with something left out."""
    solid = box((-20, -15, 0), (20, 15, 5))
    if through_hole:
        solid -= rod((0, 0, -1), (0, 0, 1), 7, 3)
    if blind:
        solid -= rod((10, 0, 3), (0, 0, 1), 3, 2)
    solid -= rod((-10, 0, -1), (0, 0, 1), 7, 1.5)
    if counterbore:
        solid -= rod((-10, 0, 3.5), (0, 0, 1), 3, 3)
    return solid


@functools.cache
def plate_part() -> Oracle:
    """The small plate's oracle, made once."""
    return part_of(PLATE)


def misses_within(found: Accounting, side: str, lo: Array, hi: Array) -> bool:
    """Whether there are misses on this side, and all of them lie in the box."""
    points = np.array([m.point for m in found.misses if m.side == side])
    return bool(len(points)) and bool(np.all((points >= lo) & (points <= hi)))


class SpecPointsTolerances(unittest.TestCase):
    def test_only_the_built_points_above_the_floor_are_looked_for(self) -> None:
        """Each spec point's tolerance is what every built point near it makes it, though only those above the floor are searched."""
        from forge_checks.accounting import (
            _nearby_greatest,
            _spec_tolerance,
            _tolerance,
        )
        from forge_checks.view import Coverage

        rng = np.random.default_rng(7)
        points = rng.uniform(0.0, 6.0, (3000, 3))
        normals = np.tile([0.0, 0.0, 1.0], (len(points), 1))
        queries = rng.uniform(-0.5, 6.5, (5000, 3))
        below = FLOOR / (1 + MARGIN)
        for share in (0.0, 0.002, 0.3, 1.0):
            with self.subTest(share=share):
                above = rng.uniform(size=len(points)) < share
                tolerance = np.where(
                    above,
                    rng.uniform(below, 0.05, len(points)),
                    rng.uniform(0.0, below, len(points)),
                )
                built = Coverage(
                    points,
                    normals,
                    np.zeros(len(points), dtype=np.int64),
                    tolerance,
                    0.25,
                )
                t_built = _tolerance(tolerance)
                every = _tolerance(
                    _nearby_greatest(
                        points, tolerance, queries, 0.25 + float(t_built.max())
                    )
                )
                found = _spec_tolerance(built, t_built, queries)
                np.testing.assert_array_equal(found, every)
                if share == 0.0:
                    self.assertTrue(np.all(found == FLOOR))
                else:
                    self.assertGreater(float(found.max()), FLOOR)


@unittest.skipUnless(HAVE_MANIFOLD, "the reference parts are made with manifold3d")
class FaceAccounting(unittest.TestCase):
    def account(self, solid: Any, deflection: float = DEFLECTION) -> Accounting:
        return account_faces(plate_part(), view_of(solid, deflection), RADIUS)

    def test_every_reference_part_is_what_its_spec_asks(self) -> None:
        """At its honest deflection: its widest circle's polygon's, with room (v2_reference.deflection)."""
        for name, make in PARTS.items():
            with self.subTest(part=name):
                items, build = make()
                honest = v2_reference.deflection(items)
                found = account_faces(part_of(items), view_of(build(), honest), RADIUS)
                self.assertEqual(found.verdict, Verdict.PASS, (name, found.misses[:3]))
                self.assertGreater(found.built.points, 1000, name)
                self.assertGreater(found.spec.points, 1000, name)
                self.assertEqual(found.built.passed, found.built.points, name)
                self.assertEqual(found.radius, RADIUS)
                self.assertAlmostEqual(
                    found.tolerance[1], max(honest * (1 + MARGIN), FLOOR), delta=1e-12
                )

    def test_the_small_plate_is_what_it_asks(self) -> None:
        found = self.account(plate())
        self.assertEqual(found.verdict, Verdict.PASS, found.misses[:3])

    def test_what_isn_t_asked_is_found(self) -> None:
        """Built where the spec has nothing: each fails, and its misses are on the damage."""
        damaged: dict[str, tuple[Any, tuple[float, ...], tuple[float, ...]]] = {
            "a pin": (plate() + rod((5, 8, 4.9), (0, 0, 1), 1.1, 0.5), (4.4, 7.4, 4.9), (5.6, 8.6, 6.1)),
            "a sealed void": (plate() - ball((-5, -8, 2.5), 0.5), (-5.6, -8.6, 1.9), (-4.4, -7.4, 3.1)),
            "a bump twice the tolerance": (
                plate() + rod((5, -8, 4.9), (0, 0, 1), 0.1 + 2 * T, 2), (2.9, -10.1, 4.9), (7.1, -5.9, 5.1)
            ),
            "a skin over the through hole": (
                plate(through_hole=False) - rod((0, 0, 0.01), (0, 0, 1), 6, 3), (-3.1, -3.1, -0.1), (3.1, 3.1, 0.1)
            ),
        }  # fmt: skip
        for what, (solid, lo, hi) in damaged.items():
            with self.subTest(damage=what):
                found = self.account(solid)
                self.assertEqual(found.verdict, Verdict.FAIL, what)
                self.assertTrue(
                    misses_within(found, "built", np.array(lo), np.array(hi)),
                    (what, found.misses[:3]),
                )

    def test_an_unasked_chamfer_is_found(self) -> None:
        """0.3 mm, well within the design tolerance of the plate's sizes, but not asked for."""
        chamfered = plate() - corner(
            (-20, 15, 5), (20, 15, 5), (0, 0, 1), (0, 1, 0), 0.3, False
        )
        found = self.account(chamfered)
        self.assertEqual(found.verdict, Verdict.FAIL)
        lo, hi = np.array([-20.1, 14.6, 4.6]), np.array([20.1, 15.1, 5.1])
        self.assertTrue(misses_within(found, "built", lo, hi), found.misses[:3])
        self.assertTrue(misses_within(found, "spec", lo, hi), found.misses[:3])

    def test_what_is_asked_and_missing_is_found(self) -> None:
        """Spec surfaces nothing built is near: each fails, and its misses are where the item should be."""
        damaged: dict[str, tuple[Any, tuple[float, ...], tuple[float, ...]]] = {
            "no blind hole": (plate(blind=False), (7.9, -2.1, 2.9), (12.1, 2.1, 5.1)),
            "no counterbore": (plate(counterbore=False), (-13.1, -3.1, 3.4), (-6.9, 3.1, 5.1)),
            "a dent twice the tolerance": (
                plate() - rod((5, -8, 5 - 2 * T - 0.001), (0, 0, 1), 1, 2), (2.9, -10.1, 4.9), (7.1, -5.9, 5.1)
            ),
        }  # fmt: skip
        for what, (solid, lo, hi) in damaged.items():
            with self.subTest(damage=what):
                found = self.account(solid)
                self.assertEqual(found.verdict, Verdict.FAIL, what)
                self.assertTrue(
                    misses_within(found, "spec", np.array(lo), np.array(hi)),
                    (what, found.misses[:3]),
                )

    def test_a_wrong_rounding_is_found(self) -> None:
        items, _ = v2_reference.rounded_block()
        part = part_of(items)

        def block(
            top: Callable[
                [
                    tuple[float, ...],
                    tuple[float, ...],
                    tuple[float, ...],
                    tuple[float, ...],
                ],
                Any,
            ],
        ) -> Any:
            solid = box((-20, -15, 0), (20, 15, 20))
            z = (0.0, 0.0, 1.0)
            for sx in (-1, 1):
                solid -= top(
                    (20 * sx, -15, 20), (20 * sx, 15, 20), z, (float(sx), 0.0, 0.0)
                )
            for sy in (-1, 1):
                solid -= top(
                    (-20, 15 * sy, 20), (20, 15 * sy, 20), z, (0.0, float(sy), 0.0)
                )
            for sx in (-1, 1):
                for sy in (-1, 1):
                    solid -= corner((20 * sx, 15 * sy, 0), (20 * sx, 15 * sy, 20),
                                    (float(sx), 0, 0), (0, float(sy), 0), 2, False)  # fmt: skip
            return solid

        wrong = {
            "a fillet of 3.5 for 3": lambda p0, p1, n1, n2: corner(p0, p1, n1, n2, 3.5),
            "a chamfer for the fillet": lambda p0, p1, n1, n2: corner(
                p0, p1, n1, n2, 3, False
            ),
        }
        for what, top in wrong.items():
            with self.subTest(damage=what):
                found = account_faces(part, view_of(block(top)), RADIUS)
                self.assertEqual(found.verdict, Verdict.FAIL, what)
                self.assertGreater(found.spec.missed, 0, what)

    def test_a_mesh_coarser_than_it_says_fails_and_one_that_says_so_passes(
        self,
    ) -> None:
        items, build = v2_reference.dome()
        part = part_of(items)
        with mock.patch.object(v2_reference, "SEGMENTS", 32):
            coarse = build()
        # The dome's facets stray up to about the side's square over six times the radius.
        side = 2 * 20 * np.sin(np.pi / 32)
        strays = side**2 / (6 * 20)
        found = account_faces(part, view_of(coarse, strays / 4), RADIUS)
        self.assertEqual(found.verdict, Verdict.FAIL)
        self.assertGreater(found.built.missed, 0)
        honest = account_faces(part, view_of(coarse, 2 * strays), RADIUS)
        self.assertEqual(honest.verdict, Verdict.PASS, honest.misses[:3])

    def test_near_misses_pass(self) -> None:
        soup = triangles(plate())
        mesh = Mesh.from_triangles(soup)
        rng = np.random.default_rng(3)
        jitter = rng.uniform(-1, 1, mesh.vertices.shape) * (DEFLECTION / 2 / np.sqrt(3))
        near = {
            "vertices jittered within the deflection": (
                Mesh(mesh.vertices + jitter, mesh.faces),
                1.5 * DEFLECTION,
            ),
            "coordinates in float32": (
                Mesh(mesh.vertices.astype(np.float32).astype(np.float64), mesh.faces),
                DEFLECTION,
            ),
            "moved by half the tolerance": (
                Mesh(
                    mesh.vertices + np.array([1.0, 1.0, 1.0]) * (T / 2 / np.sqrt(3)),
                    mesh.faces,
                ),
                DEFLECTION,
            ),
        }
        for what, (moved, deflection) in near.items():
            with self.subTest(near=what):
                v = ViewProxy(
                    MeshView(moved, source="mesh-file", deflection=deflection)
                )
                found = account_faces(plate_part(), v, RADIUS)
                self.assertEqual(found.verdict, Verdict.PASS, (what, found.misses[:3]))
        far = Mesh(mesh.vertices + np.array([0.0, 0.0, 3 * T]), mesh.faces)
        found = account_faces(
            plate_part(),
            ViewProxy(MeshView(far, source="mesh-file", deflection=DEFLECTION)),
            RADIUS,
        )
        self.assertEqual(found.verdict, Verdict.FAIL)

    def test_the_tolerance_never_goes_below_the_floor(self) -> None:
        found = self.account(plate(), deflection=0.0)
        self.assertEqual(found.tolerance, (FLOOR, FLOOR))

    def test_a_part_far_off_as_a_whole_fails_at_once(self) -> None:
        """Drawn in inches (25.4 times too large), or moved off by more than :data:`GROSS`: failed from its box, before its surface is covered."""
        for name, solid in (
            ("in inches", plate().scale((25.4, 25.4, 25.4))),
            ("moved 1.5 mm", plate().translate((0.0, 1.5, 0.0))),
        ):
            with (
                self.subTest(name),
                mock.patch.object(
                    ViewProxy, "coverage", side_effect=AssertionError("covered")
                ),
            ):
                found = account_faces(part_of(PLATE), view_of(solid), 1.0)
                self.assertIs(found.verdict, Verdict.FAIL)
                self.assertEqual(len(found.misses), 1)
                self.assertIn("past all the spec's material", found.misses[0].why)
        # Moved by less, it is covered and fails there.
        found = self.account(plate().translate((0.0, 0.5, 0.0)))
        self.assertIs(found.verdict, Verdict.FAIL)
        self.assertGreater(len(found.misses), 1)


@unittest.skipUnless(HAVE_MANIFOLD, "the reference parts are made with manifold3d")
class TopologyAndVolume(unittest.TestCase):
    def test_reference_parts_topology_and_volume(self) -> None:
        """A few, with no voids, one and two (tests/test_v2_checks_oracle.py counts every part's)."""
        for name, make in PARTS.items():
            if name not in WEIGHED:
                continue
            with self.subTest(part=name):
                items, build = make()
                part = part_of(items)
                v = view_of(build())
                found = judge_topology(part.expected_topology(), v.topology())
                self.assertEqual(found.verdict, Verdict.PASS, (name, found.findings))
                self.assertTrue(
                    any("through-holes" in why for why in found.unchecked), name
                )
                volume = judge_volume(part.volume(budget=1_000_000), v.volume())
                self.assertEqual(volume.verdict, Verdict.PASS, (name, volume))

    def test_damaged_topology_fails(self) -> None:
        part = part_of(PLATE)
        expected = part.expected_topology()
        chip = plate() + box((30, 0, 0), (31, 1, 1))
        found = judge_topology(expected, view_of(chip).topology())
        self.assertEqual(found.verdict, Verdict.FAIL)
        self.assertIn("solids", [f.what for f in found.findings])
        void = plate() - ball((-5, -8, 2.5), 0.5)
        found = judge_topology(expected, view_of(void).topology())
        self.assertEqual([f.what for f in found.findings], ["sealed voids"])
        soup = triangles(plate())
        cracked = ViewProxy(
            MeshView(
                Mesh.from_triangles(soup[1:]), source="mesh-file", deflection=DEFLECTION
            )
        )
        found = judge_topology(expected, cracked.topology())
        self.assertEqual(found.verdict, Verdict.FAIL)
        self.assertTrue(
            any("open edges" in f.what for f in found.findings), found.findings
        )
        # And a mesh that isn't sound can't be weighed.
        self.assertEqual(
            judge_volume(part.volume(), cracked.volume()).verdict, Verdict.INCONCLUSIVE
        )

    def test_a_solid_that_should_be_hollow_is_too_heavy(self) -> None:
        items, _ = v2_reference.tray()
        part = part_of(items)
        lo, hi = (np.array(x) for x in (part.lo, part.hi))
        full = box(tuple(lo), tuple(hi))
        found = judge_volume(part.volume(budget=1_000_000), view_of(full).volume())
        self.assertEqual(found.verdict, Verdict.FAIL)


@needs_occ
class ARoundedCornerTouchingAWall(unittest.TestCase):
    """Generated part 9213: a pocket's rounded corners touch a slot's wall, tangent, and the B-rep, exact, has an edge along each line they touch at, the cusp of material beside it thinning to nothing there. Its points there are accounted for only by the oracle's walk along the surface to where the two can be told apart (:func:`forge_checks.oracle._cusps`)."""

    def test_the_cusps_edges_are_accounted_for(self) -> None:
        from forge_checks import oracle as oracle_module
        from forge_eval.truth import Copy, Prism, Step, Truth
        from forge_occ.view import BrepView
        from v2_specs import pick
        from v2_truth_occ import build

        block = item("b", "block", length=a(60), width=a(40), height=a(20))
        slot = item("s", "pocket", on={"item": "b", "face": "-x"}, shape=pick("rectangle"),
                    length=a(4), width=a(8), depth=a(50),
                    place={"y": {"side": "+y", "distance": a(18), "to": "edge"},
                           "z": {"side": "-z", "distance": a(6), "to": "edge"}})  # fmt: skip
        pocket = item("p", "pocket", on={"item": "b", "face": "-z"}, shape=pick("rectangle"),
                      length=a(6), width=a(10), depth=a(16), corner_radius=a(1.5),
                      place={"x": {"side": "-x", "distance": a(27), "to": "edge"},
                             "y": {"side": "+y", "distance": a(8), "to": "edge"}})  # fmt: skip
        part = part_of([block, slot, pocket])
        # The same part, built exactly: the slot's +y wall and the pocket's -y wall at y = 2, the pocket's
        # corners rounded to 1.5 touching it at x = -1.5 and 1.5.
        z = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        up = (0.0, 0.0, 1.0)
        steps = (
            Step("b", 0, True, Prism((0.0, 0.0, 0.0), *z, up, (30.0, 20.0), 0.0, 0.0, 20.0)),
            Step("s", 0, False, Prism((-5.5, 0.0, 6.0), *z, up, (25.5, 2.0), 0.0, 0.0, 8.0)),
            Step("p", 0, False, Prism((0.0, 7.0, -1.0), *z, up, (3.0, 5.0), 1.5, 0.0, 17.0)),
        )  # fmt: skip
        copies = {s.item: (Copy(s.item, 0, None, (0.0, 0.0, 0.0), up, ("x", "y")),) for s in steps}  # fmt: skip
        view = ViewProxy(BrepView(build(Truth(copies, steps))))
        found = account_faces(part, view, 1.0)
        self.assertIs(found.verdict, Verdict.PASS, found.misses[:3])
        with mock.patch.object(
            oracle_module, "_cusps", lambda *_: np.zeros(0, dtype=np.int64)
        ):
            found = account_faces(part, view, 1.0)
        self.assertIs(found.verdict, Verdict.FAIL)
        missed = np.array([m.point for m in found.misses if m.side == "built"])
        self.assertGreater(len(missed), 0)
        # Each on a line where a corner touches the wall.
        self.assertTrue(np.allclose(np.abs(missed[:, 0]), 1.5, atol=1e-6))
        self.assertTrue(np.allclose(missed[:, 1], 2.0, atol=1e-6))


if __name__ == "__main__":
    unittest.main()
