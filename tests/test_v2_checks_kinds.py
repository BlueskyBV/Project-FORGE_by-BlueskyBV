"""V2 stage 2, step 5: the check kinds, each on parts built right and on its mutants and near-misses.

Every kind is run on small parts built by hand with manifold3d (the
plate below, with parameters), whose sizes are known: each check must pass
on the part as asked, measure close to the true value with an uncertainty
fine enough for its tolerance, pass at the near-misses its kind generates
(``2u`` inside each limit) and fail at its mutants (``2u`` outside), and
fail where the surface it measures isn't built.
"""

from __future__ import annotations

import functools
import itertools
import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
from forge_checks.accounting import account_faces
from forge_checks.checks import Check, Evidence
from forge_checks.classes import (
    RADIUS,
    Tolerance,
    Verdict,
    VerificationClass,
    fine_enough,
    general,
    general_angle,
)
from forge_checks.kinds import MEASURES, MUTANTS
from forge_checks.kinds.angle import Turns
from forge_checks.kinds.count import Copies
from forge_checks.kinds.depth import Open
from forge_checks.kinds.pattern import Circle, Pitches
from forge_checks.kinds.position import Centre, Hub, Middle, Position, RoundEdge, Spot
from forge_checks.kinds.size import Between
from forge_checks.kinds.surfaces import Cone, Plane, Round
from forge_checks.kinds.told import Tells, Told
from forge_checks.measure import MOST_POINTS, Probe, fit_circle, fit_cone, fit_sphere
from forge_checks.mesh import Mesh, MeshView
from forge_checks.oracle import Oracle, oracle
from forge_checks.place import place
from forge_checks.view import Box, Capability, Resolution, ViewProxy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_meshes import HAVE_MANIFOLD, triangles
from v2_reference import MARGIN as DEFLECTION
from v2_reference import box, item, on, rod, through
from v2_specs import a, n, pick, read

#: The coverage radius the probes take.
COVER = 1.0

PLATE = [
    item("plate", "block", length=a(40), width=a(30), height=a(5)),
    item("through", "hole", on=on("plate", "+z"), diameter=a(6), depth=through()),
    item("blind", "hole", on=on("plate", "+z"), diameter=a(4), depth=a(2), place={"x": {"offset": a(10)}}),
    item("bored", "hole", on=on("plate", "+z"), diameter=a(3), depth=through(),
         counterbore={"diameter": a(6), "depth": a(1.5)}, place={"x": {"offset": a(-10)}}),
    item("edge", "hole", on=on("plate", "+z"), diameter=a(5), depth=through(),
         place={"x": {"offset": a(17)}, "y": {"offset": a(9)}}),
    item("boss", "boss", on=on("plate", "+z"), diameter=a(8), height=a(4), place={"y": {"offset": a(-8)}}),
]  # fmt: skip


#: The plate's sizes as the spec asks: each round surface's radius, and its other sizes.
SIZES = {
    "through": 3.0, "blind": 2.0, "bored": 1.5, "counterbore": 3.0, "edge": 2.5, "boss": 4.0,
    "length": 40.0, "width": 30.0, "height": 5.0,
    "blind depth": 2.0, "counterbore depth": 1.5, "boss height": 4.0,
    "skin": 0.0,  # left across the through hole's far end
}  # fmt: skip


def plate(**given: float) -> Any:
    """The plate, built by hand, with its sizes as given (else as the spec asks): see :data:`SIZES`."""
    v = {**SIZES, **{k.replace("_", " "): x for k, x in given.items()}}
    top = v["height"]
    solid = box(
        (-v["length"] / 2, -v["width"] / 2, 0), (v["length"] / 2, v["width"] / 2, top)
    )
    if v["skin"]:
        solid -= rod((0, 0, v["skin"]), (0, 0, 1), top + 1, v["through"])
    else:
        solid -= rod((0, 0, -1), (0, 0, 1), top + 2, v["through"])
    solid -= rod(
        (10, 0, top - v["blind depth"]), (0, 0, 1), v["blind depth"] + 1, v["blind"]
    )
    solid -= rod((-10, 0, -1), (0, 0, 1), top + 2, v["bored"])
    solid -= rod(
        (-10, 0, top - v["counterbore depth"]),
        (0, 0, 1),
        v["counterbore depth"] + 1,
        v["counterbore"],
    )
    solid -= rod((17, 9, -1), (0, 0, 1), top + 2, v["edge"])
    solid += rod((0, -8, top - 0.05), (0, 0, 1), v["boss height"] + 0.05, v["boss"])
    return solid


@functools.cache
def plate_part() -> Oracle:
    spec = read(PLATE)
    return oracle(spec, place(spec))


def probe_of(solid: Any) -> Probe:
    view = ViewProxy(
        MeshView(
            Mesh.from_triangles(triangles(solid)),
            source="mesh-file",
            deflection=DEFLECTION,
        )
    )
    return Probe(view, plate_part(), COVER)


def diameter_check(name: str, centre: tuple[float, float, float], radius: float,
                   start: float, end: float, inside: bool = True) -> Check:  # fmt: skip
    axis = (0.0, 0.0, -1.0) if inside else (0.0, 0.0, 1.0)
    return Check(
        f"{name}/diameter/0",
        name,
        "diameter",
        "diameter",
        VerificationClass.EXACT,
        frozenset({Capability.COVERAGE, Capability.CLASSIFY}),
        2 * radius,
        general(2 * radius),
        Round(centre, axis, radius, start, end, inside),
    )


#: Each round surface of the plate: its check, and the radius it has in :func:`plate`.
DIAMETERS = {
    "through": diameter_check("through", (0, 0, 5), 3.0, 0, 5),
    "blind": diameter_check("blind", (10, 0, 5), 2.0, 0, 2),
    "bored": diameter_check("bored", (-10, 0, 5), 1.5, 1.5, 5),
    "counterbore": diameter_check("bored", (-10, 0, 5), 3.0, 0, 1.5),
    "edge": diameter_check("edge", (17, 9, 5), 2.5, 0, 5),
    "boss": diameter_check("boss", (0, -8, 5), 4.0, 0, 4, inside=False),
}


@unittest.skipUnless(HAVE_MANIFOLD, "the parts are made with manifold3d")
class Diameter(unittest.TestCase):
    def run_on(self, check: Check, solid: Any) -> Evidence:
        return check.run(probe_of(solid))

    def test_every_round_surface_of_the_plate_as_asked(self) -> None:
        probe = probe_of(plate())
        for name, check in DIAMETERS.items():
            with self.subTest(surface=name):
                found = check.run(probe)
                self.assertIs(found.verdict, Verdict.PASS, found)
                assert found.measured is not None and check.tolerance is not None
                self.assertTrue(found.measured.contains(check.nominal), found)
                u = found.measured.width / 2
                self.assertTrue(fine_enough(u, check.tolerance), (name, u))

    def test_mutants_fail_and_near_misses_pass(self) -> None:
        probe = probe_of(plate())
        for name, check in DIAMETERS.items():
            found = check.run(probe)
            assert found.measured is not None
            u = found.measured.width / 2
            for diameter, verdict in MUTANTS["diameter"](
                check.nominal, check.tolerance, u
            ):
                with self.subTest(surface=name, diameter=diameter):
                    built = self.run_on(check, plate(**{name: diameter / 2}))
                    self.assertIs(built.verdict, verdict, built)

    def test_a_surface_not_built_fails(self) -> None:
        check = DIAMETERS["blind"]
        solid = box((-20, -15, 0), (20, 15, 5)) - rod((0, 0, -1), (0, 0, 1), 7, 3)
        found = self.run_on(check, solid)
        self.assertIs(found.verdict, Verdict.FAIL)
        self.assertIsNone(found.measured)
        self.assertIn("no built round surface", found.reason)
        # Built far off its size, it isn't found at all: the asked surface is missing.
        found = self.run_on(check, plate(blind=2.6))
        self.assertIs(found.verdict, Verdict.FAIL)

    def test_too_coarse_to_judge_says_so(self) -> None:
        check = DIAMETERS["through"]
        tight = Check(check.id, check.item, check.field, check.kind, check.klass, check.needs,
                      check.nominal, Tolerance(0.005, 0.005), check.target)  # fmt: skip
        found = tight.run(probe_of(plate(through=3.004)))
        self.assertIs(found.verdict, Verdict.INCONCLUSIVE)
        self.assertIn("too coarse", found.reason)

    def test_an_unknown_kind_is_refused(self) -> None:
        check = DIAMETERS["through"]
        with self.assertRaises(ValueError):
            Check(check.id, check.item, check.field, "colour", check.klass, check.needs,
                  check.nominal, check.tolerance, check.target)  # fmt: skip


def check(
    name: str, kind: str, nominal: float, target: object, tolerance: Tolerance | None
) -> Check:
    return Check(f"{name}/{kind}/0", name, kind, kind, VerificationClass.EXACT,
                 frozenset({Capability.COVERAGE, Capability.CLASSIFY, Capability.CROSSINGS}),
                 nominal, tolerance, target)  # fmt: skip


def up(x: float, y: float, z: float, reach: float = math.inf) -> Plane:
    return Plane((x, y, z), (0.0, 0.0, 1.0), reach)


#: Each size of the plate, by its key in :data:`SIZES`, and its check.
PLANES = {
    "length": check("plate", "size", 40, Between(Plane((20, 0, 2.5), (1, 0, 0)), Plane((-20, 0, 2.5), (-1, 0, 0)), (1, 0, 0)), general(40)),
    "width": check("plate", "size", 30, Between(Plane((0, 15, 2.5), (0, 1, 0)), Plane((0, -15, 2.5), (0, -1, 0)), (0, 1, 0)), general(30)),
    "height": check("plate", "size", 5, Between(up(0, 0, 5), Plane((0, 0, 0), (0, 0, -1)), (0, 0, 1)), general(5)),
    "boss height": check("boss", "size", 4, Between(up(0, -8, 9, 3.5), up(0, -8, 5, 8), (0, 0, 1)), general(4)),
    "blind depth": check("blind", "depth", 2, Between(up(10, 0, 5, 4), up(10, 0, 3, 1.8), (0, 0, 1)), general(2)),
    "counterbore depth": check("bored", "depth", 1.5, Between(up(-10, 0, 5, 5), up(-10, 0, 3.5, 2.8), (0, 0, 1)), general(1.5)),
}  # fmt: skip


@unittest.skipUnless(HAVE_MANIFOLD, "the parts are made with manifold3d")
class SizeAndDepth(unittest.TestCase):
    def test_every_size_of_the_plate_as_asked(self) -> None:
        probe = probe_of(plate())
        for name, c in PLANES.items():
            with self.subTest(size=name):
                found = c.run(probe)
                self.assertIs(found.verdict, Verdict.PASS, found)
                assert found.measured is not None and c.tolerance is not None
                self.assertTrue(found.measured.contains(c.nominal), found)
                self.assertTrue(
                    fine_enough(found.measured.width / 2, c.tolerance), found
                )

    def test_mutants_fail_and_near_misses_pass(self) -> None:
        probe = probe_of(plate())
        for name, c in PLANES.items():
            found = c.run(probe)
            assert found.measured is not None
            u = found.measured.width / 2
            for value, verdict in MUTANTS[c.kind](c.nominal, c.tolerance, u):
                with self.subTest(size=name, value=value):
                    built = c.run(probe_of(plate(**{name.replace(" ", "_"): value})))
                    self.assertIs(built.verdict, verdict, built)

    def test_right_through(self) -> None:
        c = check("through", "depth", 5, Open((0, 0, 5), (0, 0, -1), 5, 3), None)
        found = c.run(probe_of(plate()))
        self.assertIs(found.verdict, Verdict.PASS, found)
        for first, verdict in MUTANTS["depth"](5, None, DEFLECTION):
            with self.subTest(first=first):
                skin = 0.0 if math.isinf(first) else 5 - first
                self.assertIs(c.run(probe_of(plate(skin=skin))).verdict, verdict)
        # A blind hole where a through one is asked.
        blind = c.run(probe_of(plate(skin=2.0)))
        self.assertIs(blind.verdict, Verdict.FAIL)
        assert blind.measured is not None
        self.assertAlmostEqual(blind.measured.midpoint, 3.0, delta=1e-9)

    def test_a_face_not_built_fails(self) -> None:
        c = PLANES["blind depth"]
        found = c.run(
            probe_of(plate(blind_depth=4.0))
        )  # the floor is 2 mm too deep: not found
        self.assertIs(found.verdict, Verdict.FAIL)
        self.assertIn("no built face", found.reason)


# A second plate: a row of holes, a ring of them, an arc of them, a countersunk hole, a pocket,
# a row of two small pockets and a slot.
HOLES = [
    item("plate", "block", length=a(60), width=a(40), height=a(6)),
    item("row", "hole", on=on("plate", "+z"), diameter=a(4), depth=through(),
         place={"y": {"offset": a(10)}, "pattern": {"row": {"axis": pick("x"), "count": n(3), "pitch": a(15)}}}),
    item("ring", "hole", on=on("plate", "+z"), diameter=a(3), depth=through(),
         place={"x": {"offset": a(-15)}, "y": {"offset": a(-8)}, "pattern": {"circle": {"diameter": a(16), "count": n(6)}}}),
    item("sunk", "hole", on=on("plate", "+z"), diameter=a(4), depth=through(),
         countersink={"diameter": a(8), "angle": a(90, "deg")}, place={"x": {"offset": a(15)}, "y": {"offset": a(-8)}}),
    item("pocket", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(12), width=a(8),
         corner_radius=a(2), depth=a(2), place={"x": {"offset": a(2)}, "y": {"offset": a(-11)}}),
    item("slot", "slot", on=on("plate", "+z"), width=a(4), length=a(14), along=pick("x"), ends=pick("round"),
         depth=a(3)),
    item("arc", "hole", on=on("plate", "+z"), diameter=a(2), depth=through(),
         place={"x": {"offset": a(24)}, "y": {"offset": a(5)},
                "pattern": {"arc": {"diameter": a(8), "count": n(3), "start": a(90, "deg"), "step": a(45, "deg")}}}),
    item("pockets", "pocket", on=on("plate", "+z"), shape=pick("rectangle"), length=a(3), width=a(3), depth=a(1),
         place={"x": {"offset": a(-25)}, "y": {"offset": a(11)},
                "pattern": {"row": {"axis": pick("y"), "count": n(2), "pitch": a(6)}}}),
]  # fmt: skip

#: The second plate's values as the spec asks.
HOLE_SIZES = {
    "pitch": 15.0, "ring": 16.0, "sunk x": 15.0, "sink": 8.0, "angle": 90.0, "corner": 2.0,
    "square ends": 0.0, "slot below": 0.0, "missing": -1.0,
    "turn": 0.0,  # the ring's first hole's angle
    "arc step": 45.0, "arc x": 24.0, "pocket pitch": 6.0,
}  # fmt: skip


def holes(**given: float) -> Any:
    """The second plate, built by hand, with its values as given (else as the spec asks): see :data:`HOLE_SIZES`."""
    v = {**HOLE_SIZES, **{k.replace("_", " "): x for k, x in given.items()}}
    z = (0.0, 0.0, 1.0)
    solid = box((-30, -20, 0), (30, 20, 6))
    for k in range(3):
        if k != v["missing"]:
            solid -= rod(((k - 1) * v["pitch"], 10, -1), z, 8, 2)
    for k in range(6):
        turn = math.radians(v["turn"] + 60 * k)
        solid -= rod(
            (
                -15 + v["ring"] / 2 * math.cos(turn),
                -8 + v["ring"] / 2 * math.sin(turn),
                -1,
            ),
            z,
            8,
            1.5,
        )
    sx = v["sunk x"]
    half = math.radians(v["angle"] / 2)
    deep = (v["sink"] / 2 - 2) / math.tan(half)
    solid -= rod((sx, -8, -1), z, 8, 2)
    solid -= rod((sx, -8, 6 - deep), z, deep + 1, 2, top=v["sink"] / 2 + math.tan(half))
    # The pocket, 12 x 8 at (2, -11), its corners rounded, 2 deep.
    r = v["corner"]
    pocket = box((-4, -15 + r, 4), (8, -7 - r, 7)) + box(
        (-4 + r, -15, 4), (8 - r, -7, 7)
    )
    for cx in (-4 + r, 8 - r):
        for cy in (-15 + r, -7 - r):
            pocket += rod((cx, cy, 4), z, 3, r)
    solid -= pocket
    # The arc: three holes of 2, the first at 90 degrees round (arc x, 5) on a circle of 8.
    for k in range(3):
        turn = math.radians(90 + k * v["arc step"])
        solid -= rod(
            (v["arc x"] + 4 * math.cos(turn), 5 + 4 * math.sin(turn), -1), z, 8, 1
        )
    # The two small pockets, 3 x 3 and 1 deep, round (-25, 11) along y.
    for y in (11 - v["pocket pitch"] / 2, 11 + v["pocket pitch"] / 2):
        solid -= box((-26.5, y - 1.5, 5), (-23.5, y + 1.5, 7))
    # The slot, 14 x 4 along x at the middle, 3 deep: round ends or square, from the top or the bottom.
    lo, hi = (-1.0, 3.0) if v["slot below"] else (3.0, 7.0)
    if v["square ends"]:
        solid -= box((-7, -2, lo), (7, 2, hi))
    else:
        solid -= (
            box((-5, -2, lo), (5, 2, hi))
            + rod((-5, 0, lo), z, hi - lo, 2)
            + rod((5, 0, lo), z, hi - lo, 2)
        )
    return solid


@functools.cache
def holes_part() -> Oracle:
    spec = read(HOLES)
    return oracle(spec, place(spec))


#: How far the second plate's mesh is from its true surface: its widest circle (r 4.4) is 256-sided,
#: so 4.4 (1 - cos(pi / 256)) = 0.0003 mm; declared with room (face accounting holds it to it).
HOLES_DEFLECTION = 0.001


def holes_probe(solid: Any) -> Probe:
    view = ViewProxy(
        MeshView(
            Mesh.from_triangles(triangles(solid)),
            source="mesh-file",
            deflection=HOLES_DEFLECTION,
        )
    )
    return Probe(view, holes_part(), COVER)


def bore(
    x: float, y: float, radius: float, start: float = 0.0, end: float = 6.0
) -> Round:
    return Round((x, y, 6.0), (0.0, 0.0, -1.0), radius, start, end, True)


ROW = tuple(bore(15.0 * (k - 1), 10, 2) for k in range(3))
RING = tuple(
    bore(
        -15 + 8 * math.cos(math.radians(60 * k)),
        -8 + 8 * math.sin(math.radians(60 * k)),
        1.5,
    )
    for k in range(6)
)
ARC = tuple(
    bore(24 + 4 * math.cos(math.radians(90 + 45 * k)), 5 + 4 * math.sin(math.radians(90 + 45 * k)), 1.0)
    for k in range(3)
)  # fmt: skip
SUNK = bore(15, -8, 2, 2, 6)
SINK = Cone((15.0, -8.0, 6.0), (0.0, 0.0, -1.0), (4.0, 2.0), (0.0, 2.0), True)
SIDES = Middle(Plane((30, 0, 3), (1, 0, 0)), Plane((-30, 0, 3), (-1, 0, 0)))
#: The two small pockets' built centres along y: the middle of each one's walls across y (each a disc as wide as the wall).
POCKETS = tuple(
    Middle(Plane((-25.0, y + 1.5, 5.5), (0.0, -1.0, 0.0), 1.5), Plane((-25.0, y - 1.5, 5.5), (0.0, 1.0, 0.0), 1.5))
    for y in (8.0, 14.0)
)  # fmt: skip
UP = (0.0, 0.0, 1.0)
#: The plate's top: its first axis and its second.
TOP = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))


def spots(rounds: tuple[Round, ...]) -> tuple[Spot, ...]:
    """Round copies' built centres: each one's fitted axis."""
    return tuple(Spot(Centre(r), Centre(r)) for r in rounds)


#: Each value of the second plate, by its key in :data:`HOLE_SIZES`, and its check.
MEASURED = {
    "sunk x": check("sunk", "position", 15, Position((1, 0, 0), SIDES, Centre(SUNK)), general(15)),
    "pitch": check("row", "pattern", 15, Pitches(tuple(Centre(r) for r in ROW), ((0, 1), (1, 2)), (1, 0, 0)),
                   general(15)),
    "ring": check("ring", "pattern", 16, Circle(spots(RING), TOP), general(16)),
    "turn": check("ring", "angle", 0, Turns((-15.0, -8.0, 6.0), UP, TOP[0], spots(RING), None, 0.0, 60.0,
                                            told=tuple(range(6)), reach=8.0), general_angle(8)),
    "arc step": check("arc", "angle", 45, Turns((24.0, 5.0, 6.0), UP, TOP[0], spots(ARC), None, 90.0, 45.0, step=True,
                                                reach=4.0), general_angle(4)),
    "arc x": check("arc", "position", 24, Position((1, 0, 0), SIDES, Hub(spots(ARC), TOP)), general(24)),
    "pocket pitch": check("pockets", "pattern", 6, Pitches(POCKETS, ((0, 1),), (0, 1, 0)), general(6)),
    "angle": check("sunk", "angle", 90, SINK, general_angle(2 * math.sqrt(2))),
    "sink": check("sunk", "diameter", 8, SINK, general(8)),
    "corner": check("pocket", "corner", 2, Round((6.0, -9.0, 6.0), (0.0, 0.0, -1.0), 2.0, 0.0, 2.0, True),
                    general(2, RADIUS)),
}  # fmt: skip


class FitsBoundedAsOne(unittest.TestCase):
    """How far a fit may be off (forge_checks.measure.Errors): a value made of several unknowns bounded as one, and every bound taken to second order."""

    #: A rounded pocket's corner (part 950's): a circle of radius 0.989, as a mesh 0.005 off it at most.
    RADIUS, OFF = 0.989, 0.005
    #: What the second order leaves out (the third), relative to a bound.
    THIRD = 1e-3

    def arc(self, degrees: float, moved: Any = 0.0) -> tuple[Any, Any]:
        """400 points on an arc of the circle ending where it reaches across (-x), each moved out by ``moved``; and their deflections."""
        angles = np.linspace(math.pi - math.radians(degrees), math.pi, 400)
        rho = self.RADIUS + np.broadcast_to(moved, angles.shape)
        points = np.stack([rho * np.cos(angles), rho * np.sin(angles)], axis=1)
        return points, np.full(len(angles), self.OFF)

    def fitted(self, degrees: float, moved: Any = 0.0) -> Any:
        fit = fit_circle(*self.arc(degrees, moved), (0.0, 0.0), self.RADIUS)
        assert fit is not None
        return fit

    def test_a_short_arc_s_edge_is_known_far_better_than_its_centre_and_radius(
        self,
    ) -> None:
        """Part 950: a pocket's length between its corners' far edges, through an STL, was ±0.156 from each corner's centre and radius bounded apart, and is ±0.024 bounded as one."""
        fit = self.fitted(90)
        # Where the arc reaches across: the centre less the radius; the length has two, judging ±0.1.
        edge = fit.uncertainty(1.0, 0.0, -1.0)
        self.assertLess(edge, 0.2 / 8 / 2)
        self.assertGreater(fit.u_centre[0] + fit.u_radius, 6 * edge)
        self.assertEqual(fit.uncertainty(0.0, 0.0, 1.0), fit.u_radius)
        self.assertEqual(fit.uncertainty(1.0, 0.0, 0.0), fit.u_centre[0])

    def test_the_worst_points_are_held_to_second_order(self) -> None:
        """Every point moved by its whole deflection, each the way that moves a value most (as far as the fit then says, again): the fit off by up to its bound, never more; an arc too short for its points' deflection fixes nothing."""
        units = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, -1.0))
        true = np.array([0.0, 0.0, self.RADIUS])
        anyhow = np.random.default_rng(950)
        for degrees in (360, 180, 90, 60, 45):
            exact = self.fitted(degrees)
            for unit, way in itertools.product(units, (1.0, -1.0)):
                a = np.array(unit)
                moved = way * np.sign(a @ exact.errors.spread) * self.OFF
                for _ in range(3):
                    fit = self.fitted(degrees, moved)
                    off = a @ (np.array([*fit.centre, fit.radius]) - true)
                    bound = fit.uncertainty(*unit) * (1 + self.THIRD)
                    with self.subTest(degrees=degrees, unit=unit, way=way):
                        self.assertLessEqual(abs(off), bound)
                    moved = np.sign(off) * np.sign(a @ fit.errors.spread) * self.OFF
            for _ in range(5):
                fit = self.fitted(degrees, anyhow.uniform(-self.OFF, self.OFF, 400))
                self.assertLessEqual(abs(fit.radius - self.RADIUS), fit.u_radius)
        for degrees in (40, 30):
            self.assertIsNone(fit_circle(*self.arc(degrees), (0.0, 0.0), self.RADIUS))

    def test_a_cone_s_and_a_ball_s(self) -> None:
        """A cone's radius away from its points, and a ball's top: never looser than their parts' bounds added up."""
        s = np.linspace(-1.0, 1.0, 21)
        angles = np.linspace(0.0, math.pi / 3, 30)
        across = np.array(
            [
                [(2 + 0.5 * h) * math.cos(t), (2 + 0.5 * h) * math.sin(t)]
                for h in s
                for t in angles
            ]
        )
        along = np.repeat(s, len(angles))
        cone = fit_cone(across, along, np.full(len(along), self.OFF), 2.0, 0.5)
        assert cone is not None
        for at in (0.0, 1.0, 6.0):
            self.assertLessEqual(
                cone.radius_at(at)[1], cone.u_a + abs(at - cone.at) * cone.u_b + 1e-12
            )
        self.assertEqual(cone.radius_at(cone.at)[1], cone.u_a)
        cap = np.array(
            [
                [math.sin(p) * math.cos(t), math.sin(p) * math.sin(t), math.cos(p)]
                for p in np.linspace(0.1, 0.8, 12)
                for t in np.linspace(0.0, 2 * math.pi, 24)
            ]
        )
        ball = fit_sphere(3 * cap, np.full(len(cap), self.OFF), (0.0, 0.0, 0.0), 3.0)
        assert ball is not None
        top = ball.uncertainty((0.0, 0.0, 1.0), 1.0)
        self.assertLess(top, ball.u_centre[2] + ball.u_radius)
        self.assertEqual(ball.uncertainty((0.0, 0.0, 0.0), 1.0), ball.u_radius)


@unittest.skipUnless(HAVE_MANIFOLD, "the parts are made with manifold3d")
class TakenAgainFiner(unittest.TestCase):
    """A measurement too uncertain for its tolerance is taken again where it looked, the view's coverage finer there."""

    def test_a_short_cone_too_coarse_at_first_is_judged_finer(self) -> None:
        view = holes_probe(holes()).view
        coarse = Probe(view, holes_part(), 2.5)
        tight = check("sunk", "angle", 90, SINK, Tolerance(0.2, 0.2))
        with coarse.watched() as looked:
            first = MEASURES["angle"](SINK, 90.0, tight.tolerance, coarse)
        assert first.value is not None and tight.tolerance is not None
        self.assertFalse(fine_enough(first.value.width / 2, tight.tolerance), first)
        self.assertFalse(first.value.lo > 89.8 and first.value.hi < 90.2, first)
        self.assertTrue(looked)
        found = tight.run(coarse)
        self.assertIs(found.verdict, Verdict.PASS, found)
        assert found.measured is not None
        self.assertLess(found.measured.width, first.value.width)
        # Finer only where it looked: far fewer points than the whole part at that radius.
        finer = coarse.finer(looked)
        assert finer is not None
        self.assertLess(finer.radius, coarse.radius / 3)
        self.assertLess(
            len(finer.points), len(Probe(view, holes_part(), finer.radius).points) / 4
        )

    def test_no_finer_than_the_finest_nor_over_too_much(self) -> None:
        view = holes_probe(holes()).view
        sunk = Box((10.0, -13.0, 3.0), (20.0, -3.0, 7.0))  # round the countersunk hole
        fine = Probe(view, holes_part(), 0.015, [sunk])
        with fine.watched() as looked:
            MEASURES["angle"](SINK, 90.0, Tolerance(0.5, 0.5), fine)
        self.assertTrue(looked)
        self.assertIsNone(fine.finer(looked))  # four times finer is past the finest
        self.assertIsNone(fine.finer([]))
        whole = Box((-30.0, -20.0, 0.0), (30.0, 20.0, 6.0))
        self.assertIsNone(Probe(view, holes_part(), 1.0, [sunk]).finer([whole], 40.0))

    def test_no_finer_where_the_faces_a_box_meets_would_be_too_many_points(
        self,
    ) -> None:
        """A view may cover every face (or triangle) a box meets whole, as views did: a speck of a broad face looked at again finer would cover all of it (generated parts 2063, 2072, 2077: a mutant's missing surface, 17 million points). The faces met are held to a bound still."""
        view = holes_probe(holes()).view
        coarse = Probe(view, holes_part(), 1.0)
        # A speck of the top face: round one of its points.
        top = int(np.argmax(coarse.points[:, 2] + 10.0 * (coarse.normals[:, 2] > 0.99)))
        at = tuple(float(v) for v in coarse.points[top])
        speck = Box(at, at)  # type: ignore[arg-type]
        finer = coarse.finer([speck])
        assert finer is not None
        # The faces the speck (grown by the radius) meets, at as many points as the probe has on them.
        near = np.all(np.abs(coarse.points - np.array(at)) <= coarse.radius, axis=1)
        met = int(np.isin(coarse.patch, np.unique(coarse.patch[near])).sum())
        self.assertGreater(len(finer.points), met)
        # So finer by a factor that would make those faces' points too many, it isn't.
        factor = math.sqrt(MOST_POINTS / met) * 1.01
        self.assertGreater(coarse.radius / factor, 0.005)
        self.assertIsNone(coarse.finer([speck], factor))
        self.assertIsNotNone(coarse.finer([speck], factor / 1.03))

    def test_an_empty_window_notes_where_it_searched(self) -> None:
        """A window that finds no point notes the box it searched, so a measurement taken again finer looks there: a sliver the coverage passed over is found (generated part 2010, its outer face all but 0.16 mm under a block, where the radius is 0.5 mm)."""
        probe = holes_probe(holes())
        with probe.watched() as looked:
            empty = probe.flat((0.0, 0.0, 50.0), (0.0, 0.0, 1.0), width=0.1, reach=2.0)
            ball = probe.ball((0.0, 0.0, 60.0), 1.0, width=0.1)
        self.assertEqual((len(empty), len(ball)), (0, 0))
        self.assertEqual(len(looked), 2)
        np.testing.assert_allclose(looked[0].lo, (-2.1, -2.1, 47.9), atol=1e-6)
        np.testing.assert_allclose(looked[0].hi, (2.1, 2.1, 52.1), atol=1e-6)
        np.testing.assert_allclose(looked[1].lo, (-1.1, -1.1, 58.9), atol=1e-6)
        with probe.watched() as anywhere:
            probe.flat((0.0, 0.0, 50.0), (0.0, 0.0, 1.0), width=0.1)
        self.assertEqual(anywhere, [])  # searched everywhere: nowhere to look again

    def test_a_window_takes_no_other_surface_s_points(self) -> None:
        """A wide window round a bore takes its neighbours' far sides too, facing its way; they are theirs, and left out (generated part 3767: a slot's wall in an angle's window put a bore's fitted axis 0.86 mm off, held to 1e-5)."""
        probe = holes_probe(holes())
        # The ring's first hole (r 1.5 at (-7, -8)); its neighbours, 8 mm off, are within 8 of its surface.
        centre = (-7.0, -8.0, 0.0)
        window = probe.round(
            centre, (0.0, 0.0, 1.0), 1.5, 1.0, 5.0, inside=True, width=8.0
        )
        across = np.linalg.norm(window.points[:, :2] - centre[:2], axis=1)
        self.assertGreater(len(window), 1000)
        np.testing.assert_allclose(across, 1.5, atol=HOLES_DEFLECTION)
        fit = fit_circle(
            window.points[:, :2] - centre[:2], window.deflection, (0.0, 0.0), 1.5
        )
        assert fit is not None
        self.assertLess(float(np.hypot(*fit.centre)), fit.u_centre[0] + fit.u_centre[1])
        # Taken for its own, the neighbours' points pull the circle 9 mm off, its bound a micron or two.
        with mock.patch.object(
            Probe, "_owned", lambda self, rows, feet: np.ones(len(rows), dtype=bool)
        ):
            every = probe.round(
                centre, (0.0, 0.0, 1.0), 1.5, 1.0, 5.0, inside=True, width=8.0
            )
        pulled = fit_circle(
            every.points[:, :2] - centre[:2], every.deflection, (0.0, 0.0), 1.5
        )
        assert pulled is not None
        self.assertGreater(float(np.hypot(*pulled.centre)), 1000 * pulled.u_centre[1])

    def test_finer_than_the_radius_where_it_looked(self) -> None:
        """A probe finer in a box looks again finer than that where it looked, and finer than its radius elsewhere (docs/V2-stage4.md, 13.10)."""
        view = holes_probe(holes()).view
        sunk = Box((10.0, -13.0, 3.0), (20.0, -3.0, 7.0))  # round the countersunk hole
        probe = Probe(view, holes_part(), Resolution(1.0, ((sunk, 0.25),)))
        self.assertEqual(probe.radius, 1.0)
        # A speck of the surface well inside the finer box, and one far from it.
        middle = (np.asarray(sunk.lo) + np.asarray(sunk.hi)) / 2
        gap = np.linalg.norm(probe.points - middle, axis=1)
        there, elsewhere = (
            Box(*(tuple(float(v) for v in probe.points[k]),) * 2)  # type: ignore[arg-type]
            for k in (int(np.argmin(gap)), int(np.argmax(gap)))
        )
        finer = probe.finer([there, elsewhere])
        assert finer is not None
        self.assertEqual(finer.resolution, Resolution(0.25, ((sunk, 0.0625),)))

        def round_(box: Box) -> int:
            return int(np.all(np.abs(finer.points - box.lo) <= 0.2, axis=1).sum())

        # Within 0.2 mm of each speck: sixteen times as many points where the radius is four times finer.
        self.assertGreater(round_(there), 6 * round_(elsewhere))
        self.assertGreater(round_(elsewhere), 0)


@unittest.skipUnless(HAVE_MANIFOLD, "the parts are made with manifold3d")
class PlacesPatternsAndAngles(unittest.TestCase):
    def test_the_second_plate_is_within_its_declared_deflection(self) -> None:
        found = account_faces(holes_part(), holes_probe(holes()).view, COVER)
        self.assertIs(found.verdict, Verdict.PASS, found.misses[:3])

    def test_every_value_of_the_second_plate_as_asked(self) -> None:
        probe = holes_probe(holes())
        for name, c in MEASURED.items():
            with self.subTest(value=name):
                found = c.run(probe)
                self.assertIs(found.verdict, Verdict.PASS, found)
                assert found.measured is not None and c.tolerance is not None
                self.assertTrue(found.measured.contains(c.nominal), found)
                self.assertTrue(
                    fine_enough(found.measured.width / 2, c.tolerance), found
                )

    def test_mutants_fail_and_near_misses_pass(self) -> None:
        probe = holes_probe(holes())
        for name, c in MEASURED.items():
            found = c.run(probe)
            assert found.measured is not None
            u = found.measured.width / 2
            for value, verdict in MUTANTS[c.kind](c.nominal, c.tolerance, u):
                with self.subTest(value=name, at=value):
                    built = c.run(holes_probe(holes(**{name.replace(" ", "_"): value})))
                    self.assertIs(built.verdict, verdict, built)

    def test_from_an_edge_to_an_edge(self) -> None:
        """13 mm from the plate's +x face to the countersunk hole's near side."""
        c = check("sunk", "position", 13, Position((-1, 0, 0), Plane((30, 0, 3), (1, 0, 0)), RoundEdge(SUNK, -1)),
                  general(13))  # fmt: skip
        found = c.run(holes_probe(holes()))
        self.assertIs(found.verdict, Verdict.PASS, found)
        moved = c.run(holes_probe(holes(sunk_x=15.3)))
        self.assertIs(moved.verdict, Verdict.FAIL, moved)

    def test_a_copy_left_out_is_counted(self) -> None:
        c = check("row", "count", 3, Copies(ROW), None)
        self.assertIs(c.run(holes_probe(holes())).verdict, Verdict.PASS)
        for nominal, verdict in MUTANTS["count"](3, None, 0.0):
            with self.subTest(built=nominal):
                found = c.run(holes_probe(holes(missing=-1 if nominal == 3 else 1)))
                self.assertIs(found.verdict, verdict, found)
        found = c.run(holes_probe(holes(missing=1)))
        self.assertIn("copies [1]", found.reason)

    def test_a_choice_and_a_face_told_apart(self) -> None:
        corners = tuple((sx * 6.6, sy * 1.6, 4.5) for sx in (-1, 1) for sy in (-1, 1))
        ends = check(
            "slot",
            "choice",
            0,
            Told((Tells("square ends", corners, (1, 1, 1, 1)),)),
            None,
        )
        face = check(
            "slot",
            "on",
            0,
            Told((Tells("-z", ((0, 0, 4.5), (0, 0, 1.5)), (-1, 1)),)),
            None,
        )
        for c, other in ((ends, {"square_ends": 1.0}), (face, {"slot_below": 1.0})):
            with self.subTest(check=c.kind):
                self.assertIs(c.run(holes_probe(holes())).verdict, Verdict.PASS)
                found = c.run(holes_probe(holes(**other)))
                self.assertIs(found.verdict, Verdict.FAIL, found)
                self.assertIn("built as", found.reason)
        # Nothing to tell: the other choice makes the same shape.
        same = check("slot", "choice", 0, Told(()), None)
        self.assertIs(same.run(holes_probe(holes())).verdict, Verdict.PASS)


if __name__ == "__main__":
    unittest.main()
