"""V2 stage 2, step 5: the rounding and wall kinds, on parts built right and on their mutants and near-misses.

A block with its top edges filleted and its vertical edges chamfered, a
rod with its top rim filleted and its bottom rim chamfered, a hollowed box,
a hollowed rod open at its top (a cup) and a hollowed ball: each built by
hand with manifold3d, its mesh declared as far from the true surface as it
is (face accounting holds it to that), each check passing as asked, failing
``2u`` beyond each limit, passing ``2u`` within.
"""

from __future__ import annotations

import functools
import math
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

from forge_checks.accounting import account_faces
from forge_checks.checks import Check
from forge_checks.classes import (
    RADIUS,
    Tolerance,
    Verdict,
    VerificationClass,
    fine_enough,
    general,
)
from forge_checks.kinds import MUTANTS
from forge_checks.kinds.rounding import Bevel, RoundBevel
from forge_checks.kinds.size import Between
from forge_checks.kinds.surfaces import Ball, Cone, Plane, Round, Tube
from forge_checks.kinds.wall import Annulus
from forge_checks.measure import Probe
from forge_checks.mesh import Mesh, MeshView
from forge_checks.oracle import Oracle, oracle
from forge_checks.place import place
from forge_checks.view import Capability, ViewProxy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_meshes import HAVE_MANIFOLD, triangles
from v2_reference import ball, box, corner, deflection, item, turned
from v2_specs import SAY, a, pick, read

#: The coverage radius the probes take.
COVER = 1.0

BLOCK = [
    item("box", "block", length=a(40), width=a(30), height=a(20)),
    item("round", "fillet", edges={"of": "box", "which": "top"}, radius=a(3)),
    item("bevel", "chamfer", edges={"of": "box", "which": "vertical"}, size=a(2)),
]
ROD = [
    item("rod", "cylinder", diameter=a(30), length=a(20)),
    item("round", "fillet", edges={"of": "rod", "which": "top"}, radius=a(3)),
    item("bevel", "chamfer", edges={"of": "rod", "which": "bottom"}, size=a(2)),
]
BOX = [
    item("box", "block", length=a(60), width=a(40), height=a(20)),
    item(
        "hollow",
        "shell",
        of="box",
        thickness=a(2),
        open={"faces": ["+z"], "from": SAY},
        floor=a(3),
    ),
]


CUP = [
    item("cup", "cylinder", diameter=a(30), length=a(20)),
    item(
        "hollow",
        "shell",
        of="cup",
        thickness=a(2),
        open={"faces": ["+end"], "from": SAY},
    ),
]
BALL = [
    item("ball", "sphere", diameter=a(30), portion=pick("whole")),
    item("hollow", "shell", of="ball", thickness=a(2), open={"faces": [], "from": SAY}),
]
SPECS = {"block": BLOCK, "rod": ROD, "box": BOX, "cup": CUP, "ball": BALL}
#: How far each part's mesh is from its true surface: its widest circle 256-sided, with room.
DEFLECTION = {name: deflection(items) for name, items in SPECS.items()}


def block(fillet: float = 3.0, chamfer: float = 2.0, chamfered: bool = False) -> Any:
    """The block, its top edges filleted (or chamfered, the same size) and its vertical edges chamfered."""
    solid = box((-20, -15, 0), (20, 15, 20))
    z = (0.0, 0.0, 1.0)
    for sx in (-1, 1):
        solid -= corner(
            (20 * sx, -15, 20),
            (20 * sx, 15, 20),
            z,
            (float(sx), 0.0, 0.0),
            fillet,
            not chamfered,
        )
    for sy in (-1, 1):
        solid -= corner(
            (-20, 15 * sy, 20),
            (20, 15 * sy, 20),
            z,
            (0.0, float(sy), 0.0),
            fillet,
            not chamfered,
        )
    for sx in (-1, 1):
        for sy in (-1, 1):
            solid -= corner((20 * sx, 15 * sy, 0), (20 * sx, 15 * sy, 20),
                            (float(sx), 0, 0), (0, float(sy), 0), chamfer, False)  # fmt: skip
    return solid


def rod(fillet: float = 3.0, chamfer: float = 2.0) -> Any:
    """The rod, turned from its section: its bottom rim chamfered, its top rim filleted."""
    arc = [
        (
            15 - fillet + fillet * math.cos(math.pi / 2 * k / 64),
            20 - fillet + fillet * math.sin(math.pi / 2 * k / 64),
        )
        for k in range(65)
    ]
    section = [(0.0, 0.0), (15 - chamfer, 0.0), (15.0, chamfer), *arc, (0.0, 20.0)]
    return turned(section, (0.0, 0.0, 0.0))


def hollow_box(thickness: float = 2.0, floor: float = 3.0) -> Any:
    t = thickness
    return box((-30, -20, 0), (30, 20, 20)) - box(
        (-30 + t, -20 + t, floor), (30 - t, 20 - t, 21)
    )


def cup(thickness: float = 2.0) -> Any:
    """The cup, turned from its section: its side ``thickness`` thick, its floor 2."""
    inner = 15 - thickness
    return turned(
        [
            (0.0, 0.0),
            (15.0, 0.0),
            (15.0, 20.0),
            (inner, 20.0),
            (inner, 2.0),
            (0.0, 2.0),
        ],
        (0.0, 0.0, 0.0),
    )


def hollow_ball(thickness: float = 2.0) -> Any:
    """The ball, 30 across and resting on the origin, hollowed ``thickness`` thick."""
    return ball((0.0, 0.0, 15.0), 15.0) - ball((0.0, 0.0, 15.0), 15.0 - thickness)


@functools.cache
def part(name: str) -> Oracle:
    spec = read(SPECS[name])
    return oracle(spec, place(spec))


def probe(name: str, solid: Any) -> Probe:
    view = ViewProxy(
        MeshView(
            Mesh.from_triangles(triangles(solid)),
            source="mesh-file",
            deflection=DEFLECTION[name],
        )
    )
    return Probe(view, part(name), COVER)


def check(
    item_id: str, kind: str, nominal: float, target: object, tolerance: Tolerance
) -> Check:
    return Check(f"{item_id}/{kind}/0", item_id, kind, kind, VerificationClass.EXACT,
                 frozenset({Capability.COVERAGE, Capability.CLASSIFY}), nominal, tolerance, target)  # fmt: skip


S2 = math.sqrt(0.5)

#: Each check: the part it is on, how to build that part with the checked value changed, and the check.
CHECKS: dict[str, tuple[str, Callable[[float], Any], Check]] = {
    "fillet along a straight edge": (
        "block", lambda v: block(fillet=v),
        check("round", "rounding", 3, Round((17.0, 0.0, 17.0), (0.0, 1.0, 0.0), 3.0, -15.0, 15.0, False),
              general(3, RADIUS)),
    ),
    "chamfer of a straight edge": (
        "block", lambda v: block(chamfer=v),
        check("bevel", "rounding", 2, Bevel(Plane((19.0, 14.0, 10.0), (S2, S2, 0.0), 8.0), ((0, -1, 0), (-1, 0, 0))),
              general(2, RADIUS)),
    ),
    "fillet round a round edge": (
        "rod", lambda v: rod(fillet=v),
        check("round", "rounding", 3, Tube((0.0, 0.0, 17.0), (0.0, 0.0, 1.0), 12.0, 3.0, (0.0, math.pi / 2), False),
              general(3, RADIUS)),
    ),
    "chamfer round a round edge": (
        "rod", lambda v: rod(chamfer=v),
        check("bevel", "rounding", 2, RoundBevel(Cone((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (13.0, 15.0), (0.0, 2.0), False),
                                                 (15.0, 0.0), ((-1.0, 0.0), (0.0, 1.0))), general(2, RADIUS)),
    ),
    "a wall": (
        "box", lambda v: hollow_box(thickness=v),
        check("hollow", "wall", 2, Between(Plane((30, 0, 10), (1, 0, 0)), Plane((28, 0, 10), (-1, 0, 0)), (1, 0, 0)),
              general(2)),
    ),
    "a floor": (
        "box", lambda v: hollow_box(floor=v),
        check("hollow", "wall", 3, Between(Plane((0, 0, 3), (0, 0, 1)), Plane((0, 0, 0), (0, 0, -1)), (0, 0, 1)),
              general(3)),
    ),
    "a rod's round wall": (
        "cup", lambda v: cup(thickness=v),
        check("hollow", "wall", 2, Annulus(Round((0, 0, 0), (0, 0, 1), 15, 0, 20, False),
                                           Round((0, 0, 2), (0, 0, 1), 13, 0, 18, True)), general(2)),
    ),
    "a ball's wall": (
        "ball", lambda v: hollow_ball(thickness=v),
        check("hollow", "wall", 2, Annulus(Ball((0, 0, 15), 15), Ball((0, 0, 15), 13, True)), general(2)),
    ),
}  # fmt: skip

BUILT: dict[str, Callable[[], Any]] = {
    "block": block,
    "rod": rod,
    "box": hollow_box,
    "cup": cup,
    "ball": hollow_ball,
}


@unittest.skipUnless(HAVE_MANIFOLD, "the parts are made with manifold3d")
class RoundingsAndWalls(unittest.TestCase):
    def test_each_part_is_within_its_declared_deflection(self) -> None:
        for name, build in BUILT.items():
            with self.subTest(part=name):
                found = account_faces(part(name), probe(name, build()).view, COVER)
                self.assertIs(found.verdict, Verdict.PASS, found.misses[:3])

    def test_each_as_asked(self) -> None:
        for what, (name, _, c) in CHECKS.items():
            with self.subTest(check=what):
                found = c.run(probe(name, BUILT[name]()))
                self.assertIs(found.verdict, Verdict.PASS, found)
                assert found.measured is not None and c.tolerance is not None
                self.assertTrue(found.measured.contains(c.nominal), found)
                self.assertTrue(
                    fine_enough(found.measured.width / 2, c.tolerance), found
                )

    def test_mutants_fail_and_near_misses_pass(self) -> None:
        for what, (name, build, c) in CHECKS.items():
            found = c.run(probe(name, BUILT[name]()))
            assert found.measured is not None
            u = found.measured.width / 2
            for value, verdict in MUTANTS[c.kind](c.nominal, c.tolerance, u):
                with self.subTest(check=what, at=value):
                    built = c.run(probe(name, build(value)))
                    self.assertIs(built.verdict, verdict, built)

    def test_a_chamfer_for_a_fillet_fails(self) -> None:
        _, _, c = CHECKS["fillet along a straight edge"]
        found = c.run(probe("block", block(chamfered=True)))
        self.assertIs(found.verdict, Verdict.FAIL, found)


if __name__ == "__main__":
    unittest.main()
