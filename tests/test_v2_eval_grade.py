"""V2 stage 4: a built part graded against the generator's model of it, both ways (forge_eval.grade; docs/V2-stage4.md, 12.3).

The truth's surface found where a grid's lines cross it; a part graded
against its own truth's exact model passes every test; and a part that is
another (a hole moved a twentieth of a millimetre, a pocket a little
shallower, a hole left out) fails the tests that see it, with the points.
The built part can't excuse its own faces (two halves of a plate not
joined, a skin in the air, a face turned inside out each fail); a knife
edge of material passes, its material found round the edge, and so do two
blocks touching along a line, the air found round it.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
from forge_checks.view import ViewProxy
from forge_eval.grade import Grade, grade, surface_of, unsaid_volume
from forge_eval.truth import Prism, Step, Truth

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_occ import needs_occ

#: A plate 40 x 30 x 10 mm, a hole 6 mm across through it at (8, 5), a pocket 10 x 6 x 3 deep at (-10, -6).
Z = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
PLATE = Step(
    "plate",
    0,
    True,
    Prism((0.0, 0.0, 0.0), *Z, (0.0, 0.0, 1.0), (20.0, 15.0), 0.0, 0.0, 10.0),
)
BORE = Prism((8.0, 5.0, 10.0), *Z, (0.0, 0.0, -1.0), (3.0, 3.0), 3.0, 0.0, 10.0)
HOLE = Step("hole", 0, False, BORE, (0.05, 0.05))
DUG = Prism((-10.0, -6.0, 10.0), *Z, (0.0, 0.0, -1.0), (5.0, 3.0), 0.0, 0.0, 3.0)
POCKET = Step("pocket", 0, False, DUG, (0.05, 0.0))


def part(*steps: Step) -> Truth:
    from forge_eval.truth import Copy

    copies = {
        s.item: (Copy(s.item, 0, None, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), ("x", "y")),)
        for s in steps
    }
    return Truth(copies, steps)


class TheTruthsSurface(unittest.TestCase):
    def test_found_where_the_grid_crosses_it(self) -> None:
        truth = part(PLATE, HOLE)
        found = surface_of(truth, 0.5)
        x, y, z = found.T
        on_box = np.minimum.reduce(
            [np.abs(np.abs(x) - 20), np.abs(np.abs(y) - 15), np.abs(z), np.abs(z - 10)]
        )
        on_hole = np.abs(np.hypot(x - 8, y - 5) - 3)
        self.assertLess(float(np.minimum(on_box, on_hole).max()), 1e-6)
        # Every face is found: the plate's six and the hole's wall, at about the grid's spacing.
        for near in (np.abs(x - 20), np.abs(x + 20), np.abs(y - 15), np.abs(y + 15), np.abs(z), np.abs(z - 10),
                     on_hole):  # fmt: skip
            self.assertGreater(int((near < 1e-6).sum()), 50)

    def test_nothing_in_a_zone(self) -> None:
        zone = ((-25.0, -20.0, 8.0), (25.0, 20.0, 12.0))
        found = surface_of(replace(part(PLATE), zones=(zone,)), 0.5)
        self.assertTrue(len(found) and (found[:, 2] < 8.0).all())

    def test_what_the_zones_leave_unsaid(self) -> None:
        zone = ((0.0, 0.0, 0.0), (1.0, 2.0, 3.0))
        self.assertEqual(unsaid_volume(replace(part(PLATE), zones=(zone, zone))), 12.0)


def box_triangles(
    lo: tuple[float, float, float], hi: tuple[float, float, float]
) -> list[list[list[float]]]:
    """A box's twelve triangles, each wound so its normal points out."""
    x = (lo[0], hi[0])
    y = (lo[1], hi[1])
    z = (lo[2], hi[2])
    found = []
    for axis in range(3):
        for side in (0, 1):
            corners = []
            for a, b in ((0, 0), (1, 0), (1, 1), (0, 1)):
                c = [0, 0, 0]
                c[axis] = side
                c[(axis + 1) % 3], c[(axis + 2) % 3] = a, b
                corners.append([(x, y, z)[k][c[k]] for k in range(3)])
            if side == 0:
                corners.reverse()
            found += [
                [corners[0], corners[1], corners[2]],
                [corners[0], corners[2], corners[3]],
            ]
    return found


class WhatTheBuiltPartCantExcuse(unittest.TestCase):
    """A face of the built part inside the truth's material, in its air, or facing the wrong way fails the built surface's test, whatever the built part says of its own segment."""

    def graded(self, triangles: list[list[list[float]]]) -> Grade:
        from forge_checks.mesh import Mesh, MeshView

        view = MeshView(
            Mesh.from_triangles(np.array(triangles)), source="mesh-file", deflection=0.0
        )
        return grade(part(PLATE), ViewProxy(view))

    def test_the_plate_itself_passes(self) -> None:
        g = self.graded(box_triangles((-20, -15, 0), (20, 15, 10)))
        self.assertEqual(len(g.failed["built surface"]), 0, g.problems())

    def test_two_halves_not_joined(self) -> None:
        g = self.graded(
            box_triangles((-20, -15, 0), (0, 15, 10))
            + box_triangles((0, -15, 0), (20, 15, 10))
        )
        wrong = g.failed["built surface"]
        self.assertGreater(len(wrong), 100)
        self.assertTrue(np.all(np.abs(wrong[:, 0]) < 1e-9))

    def test_a_skin_in_the_air(self) -> None:
        skin = [
            [[-2, -2, 12], [2, -2, 12], [2, 2, 12]],
            [[-2, -2, 12], [2, 2, 12], [-2, 2, 12]],
        ]
        skin += [[t[0], t[2], t[1]] for t in skin]
        g = self.graded(box_triangles((-20, -15, 0), (20, 15, 10)) + skin)
        wrong = g.failed["built surface"]
        self.assertGreater(len(wrong), 10)
        self.assertTrue(np.all(np.abs(wrong[:, 2] - 12) < 1e-9))

    def test_a_face_turned_inside_out(self) -> None:
        plate = box_triangles((-20, -15, 0), (20, 15, 10))
        turned = [
            [t[0], t[2], t[1]] if all(c[2] == 10 for c in t) else t for t in plate
        ]
        wrong = self.graded(turned).failed["built surface"]
        self.assertGreater(len(wrong), 100)
        self.assertTrue(np.all(np.abs(wrong[:, 2] - 10) < 1e-9))


@needs_occ
class AKnifeEdge(unittest.TestCase):
    """A wedge of material 20 degrees across, built exactly: along the line of its edge, a point's segment behind runs out of the material whichever face it is on, and the truth's material is found round it, so the right part passes; looked for behind alone, it wouldn't."""

    def test_the_wedge_passes(self) -> None:
        from unittest import mock

        import forge_eval.grade as grading
        from forge_eval.truth import Outline2, Pushed
        from forge_occ.view import BrepView
        from v2_truth_occ import build

        h = 20 * float(np.tan(np.radians(20.0)))
        outline = Outline2(
            (0.0, 0.0),
            (
                ((20.0, 0.0), None, False),
                ((20.0, h), None, False),
                ((0.0, 0.0), None, False),
            ),
        )
        wedge = Pushed(
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            outline,
            0.0,
            10.0,
        )
        truth = part(Step("wedge", 0, True, wedge))
        view = ViewProxy(BrepView(build(truth)))
        g = grade(truth, view)
        self.assertEqual(len(g.failed["built surface"]), 0, g.problems())
        with (
            mock.patch.object(grading, "_LOOK", np.zeros((0, 3))),
            mock.patch.object(
                grading, "_edge_ways", lambda n: np.zeros((len(n), 0, 3))
            ),
        ):
            wrong = grade(truth, view).failed["built surface"]
        self.assertGreater(len(wrong), 0)
        self.assertTrue(np.all(np.hypot(wrong[:, 0], wrong[:, 1]) < 1e-6))


@needs_occ
class ABoreGrazingAFace(unittest.TestCase):
    """Generated part 8675: a bore along a block's face, 0.001 mm into it, takes a strip 0.18 mm wide from the face, and along the strip's edges the face and the bore meet at 1.3 degrees. At a point there the truth's material lies in that wedge, which none of the sphere's ways (some 13 degrees apart) enters: 45 points of the right part were graded wrong there (here, 141). The ways just off the point's own plane find it, and the part passes."""

    def test_the_strip_s_edges_pass(self) -> None:
        from unittest import mock

        import forge_eval.grade as grading
        from forge_eval.truth import Copy
        from forge_occ.view import BrepView
        from v2_truth_occ import build

        r, into = 4.0585, 0.001
        block = Step(
            "block",
            0,
            True,
            Prism((0.0, 0.0, 0.0), *Z, (0.0, 0.0, 1.0), (10.0, 10.0), 0.0, 0.0, 10.0),
        )
        bore = Step("bore", 0, False, Prism((-11.0, -10.0 + r - into, 5.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                                            (1.0, 0.0, 0.0), (r, r), r, 0.0, 22.0))  # fmt: skip
        steps = (block, bore)
        copies = {s.item: (Copy(s.item, 0, None, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), ("x", "y")),) for s in steps}  # fmt: skip
        truth = Truth(copies, steps)
        view = ViewProxy(BrepView(build(truth)))
        g = grade(truth, view)
        self.assertEqual(len(g.failed["built surface"]), 0, g.problems())
        with mock.patch.object(
            grading, "_edge_ways", lambda n: np.zeros((len(n), 0, 3))
        ):
            wrong = grade(truth, view).failed["built surface"]
        self.assertGreater(len(wrong), 0)
        # Each on the strip's edge, where the bore leaves the face: sqrt(2 r into) from its axis's height.
        self.assertTrue(
            np.allclose(
                np.abs(wrong[:, 2] - 5.0), np.sqrt(r * r - (r - into) ** 2), atol=1e-6
            )
        )


@needs_occ
class ARoundedCornerTouchingAWall(unittest.TestCase):
    """Generated part 9213: a pocket's rounded corners touch a slot's wall, tangent, each leaving a cusp of material against it whose edge runs along the line the corner touches the wall at. At s from the edge the cusp is s / 2r across, under every tilt of part 8675's; and from the corner's face, which turns away from the wall, the material lies ahead of the point's plane, not behind it. Ways tilted less, and a step along the normal from the material found to the air, pass it (on the grader before them, 104 points failed here)."""

    def test_the_cusps_edges_pass(self) -> None:
        from unittest import mock

        import forge_eval.grade as grading
        from forge_occ.view import BrepView
        from v2_truth_occ import build

        block = Step("block", 0, True, Prism((0.0, 0.0, 0.0), *Z, (0.0, 0.0, 1.0), (10.0, 10.0), 0.0, 0.0, 10.0))  # fmt: skip
        # A slot along x, its +y wall at y = 0; a pocket up from the bottom, its -y wall there too, its corners
        # rounded to 1.5: they touch the wall at x = -1.5 and 1.5.
        slot = Step("slot", 0, False, Prism((-2.5, -1.0, 3.0), *Z, (0.0, 0.0, 1.0), (8.5, 1.0), 0.0, 0.0, 4.0))  # fmt: skip
        pocket = Step("pocket", 0, False, Prism((0.0, 3.0, -1.0), *Z, (0.0, 0.0, 1.0), (3.0, 3.0), 1.5, 0.0, 9.0))  # fmt: skip
        truth = part(block, slot, pocket)
        view = ViewProxy(BrepView(build(truth)))
        g = grade(truth, view)
        self.assertEqual(len(g.failed["built surface"]), 0, g.problems())
        with mock.patch.object(
            grading, "_TILTS", np.radians([10.0, 3.0, 1.0, 0.3, 0.1])
        ):
            wrong = grade(truth, view).failed["built surface"]
        self.assertGreater(len(wrong), 0)
        # Each on a line where a corner touches the wall.
        self.assertTrue(np.allclose(np.abs(wrong[:, 0]), 1.5, atol=1e-6))
        self.assertTrue(np.allclose(wrong[:, 1], 0.0, atol=1e-6))


@needs_occ
class TwoSolidsTouchingAlongALine(unittest.TestCase):
    """Two blocks meeting only along an edge (as two letters may at their corners), built exactly, pass: along that line the truth has air ahead of each face and material behind it, if not along the face's normal itself (generated part 108, tests/v2_regressions.py, is the case where it isn't)."""

    def test_the_two_pass(self) -> None:
        from forge_occ.view import BrepView
        from v2_truth_occ import build

        def block(item: str, x: float, y: float) -> Step:
            return Step(
                item,
                0,
                True,
                Prism((x, y, 0.0), *Z, (0.0, 0.0, 1.0), (5.0, 5.0), 0.0, 0.0, 10.0),
            )

        truth = part(block("a", -5.0, -5.0), block("b", 5.0, 5.0))
        g = grade(truth, ViewProxy(BrepView(build(truth))))
        self.assertEqual(len(g.failed["built surface"]), 0, g.problems())
        self.assertGreater(g.tried["built surface"], 1000)


@needs_occ
class APartAgainstItsTruth(unittest.TestCase):
    def view(self, truth: Truth) -> ViewProxy:
        from forge_occ.view import BrepView
        from v2_truth_occ import build

        return ViewProxy(BrepView(build(truth)))

    def graded(self, made: Truth, truth: Truth) -> Grade:
        return grade(truth, self.view(made), exact=self.view(truth))

    def test_its_own_model_passes_every_test(self) -> None:
        truth = part(PLATE, HOLE, POCKET)
        g = self.graded(truth, truth)
        self.assertTrue(g.passed, g.problems())
        self.assertGreater(min(g.tried.values()), 400)

    def test_a_hole_moved_a_twentieth_of_a_millimetre(self) -> None:
        truth = part(PLATE, HOLE, POCKET)
        moved = replace(HOLE, solid=replace(BORE, centre=(8.05, 5.0, 10.0)))
        g = self.graded(part(PLATE, moved, POCKET), truth)
        self.assertFalse(g.passed)
        problems = g.problems()
        self.assertTrue(any(p.startswith("built surface") for p in problems), problems)
        self.assertTrue(
            any(p.startswith("truth's surface") for p in problems), problems
        )

    def test_a_pocket_a_little_shallower(self) -> None:
        truth = part(PLATE, HOLE, POCKET)
        shallower = replace(POCKET, solid=replace(DUG, high=2.98))
        g = self.graded(part(PLATE, HOLE, shallower), truth)
        failed = {t for t, points in g.failed.items() if len(points)}
        self.assertLessEqual({"built surface", "truth's surface"}, failed)
        self.assertTrue(
            all(abs(p[2] - 7.0) < 0.03 for p in g.failed["truth's surface"])
        )

    def test_a_hole_left_out(self) -> None:
        truth = part(PLATE, HOLE, POCKET)
        g = self.graded(part(PLATE, POCKET), truth)
        failed = {t for t, points in g.failed.items() if len(points)}
        self.assertEqual(failed, {"built surface", "truth's surface", "copies' boxes"})
        assert g.volumes is not None
        self.assertFalse(g.volumes[0].overlaps(g.volumes[1]))


if __name__ == "__main__":
    unittest.main()
