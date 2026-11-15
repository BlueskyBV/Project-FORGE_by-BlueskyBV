"""V2 stage 4: which grid points lie on a face, all at once (forge_occ.uvclass; docs/V2-stage4.md 13.2).

The answer must be OpenCascade's own classifier's (``IntTools_FClass2d``, ``BRepTopAdaptor_FClass2d`` before OpenCascade 8,
IN or ON) at every grid point: on every face of the shape zoo and the golden
clevis (fillets, a coil, a bend, intersection curves, cones, spheres, tori),
on grids over the face's parameter box that run through the boundary's own
vertices. Past the box a point is off the face (OpenCascade's classifier
moves one by a period onto a periodic face: the coverage never asks there).
A gap between two edges is closed by a banded piece; a grid that doesn't
ascend is refused.
"""

from __future__ import annotations

import unittest
from typing import Any

import numpy as np
from v2_occ import build, needs_occ, zoo

try:
    from forge_occ import uvclass
    from forge_occ.occt import edges, faces
    from forge_occ.uvclass import on_grid
    from OCP.BRep import BRep_Tool
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.BRepPrimAPI import (
        BRepPrimAPI_MakeBox,
        BRepPrimAPI_MakeCone,
        BRepPrimAPI_MakeCylinder,
        BRepPrimAPI_MakeSphere,
        BRepPrimAPI_MakeTorus,
    )
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Pnt2d
    from OCP.IntTools import IntTools_FClass2d
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_OUT
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
except ImportError:  # no OpenCascade here: every class below is skipped
    pass


def grid(face: Any, n: int = 41) -> tuple[Any, Any]:
    """A grid over the face's parameter box, through every vertex of its boundary."""
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    us = list(np.linspace(u0, u1, n))
    vs = list(np.linspace(v0, v1, n))
    explorer = TopExp_Explorer(face, TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge(explorer.Current())
        explorer.Next()
        pcurve = BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0)
        if pcurve is None:
            continue
        for t in BRep_Tool.Range_s(edge, face):
            p = pcurve.Value(t)
            us.append(p.X())
            vs.append(p.Y())
    return np.unique(np.array(us)), np.unique(np.array(vs))


def opencascade(face: Any, us: Any, vs: Any) -> Any:
    classifier = IntTools_FClass2d(face, 1e-9)
    return np.array(
        [
            [classifier.Perform(gp_Pnt2d(float(u), float(v))) != TopAbs_OUT for v in vs]
            for u in us
        ]
    )


def shapes() -> dict[str, Any]:
    plate = BRepPrimAPI_MakeBox(gp_Pnt(-20, -15, 0), 40.0, 30.0, 5.0).Shape()
    for x in (-10.0, 0.0, 10.0):
        hole = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(x, 0, -1), gp_Dir(0, 0, 1)), 3.0, 7.0
        ).Shape()
        plate = BRepAlgoAPI_Cut(plate, hole).Shape()
    rod = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 10.0, 40.0
    ).Shape()
    side = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(-20, 0, 20), gp_Dir(1, 0, 0)), 4.0, 40.0
    ).Shape()
    cube = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    rounded = BRepFilletAPI_MakeFillet(cube)
    for edge in edges(cube):
        rounded.Add(2.0, edge)
    return {
        "plate with holes": plate,
        "rod with a side hole": BRepAlgoAPI_Cut(rod, side).Shape(),
        "ball": BRepPrimAPI_MakeSphere(5.0).Shape(),
        "ring": BRepPrimAPI_MakeTorus(20.0, 5.0).Shape(),
        "cone": BRepPrimAPI_MakeCone(10.0, 0.0, 20.0).Shape(),
        "cube rounded all round": rounded.Shape(),
    }


@needs_occ
class OpenCascadesAnswerEverywhere(unittest.TestCase):
    def check(self, name: str, shape: Any) -> None:
        for k, face in enumerate(faces(shape)):
            us, vs = grid(face)
            found, expected = on_grid(face, us, vs), opencascade(face, us, vs)
            with self.subTest(shape=name, face=k):
                self.assertEqual(found.shape, (len(us), len(vs)))
                self.assertEqual(int((found != expected).sum()), 0)
                self.assertTrue(found.any())

    def test_analytic_and_blended_faces(self) -> None:
        for name, shape in shapes().items():
            self.check(name, shape)

    def test_the_shape_zoo(self) -> None:
        for name, text in zoo().items():
            self.check(name, build(text).shape)

    def test_points_anywhere_moved_by_a_period(self) -> None:
        """Scattered points, past the box too: OpenCascade's answer (moving a point by a period first) wherever this one is sure."""
        rng = np.random.default_rng(6)
        for name, shape in [
            *shapes().items(),
            *((n, build(t).shape) for n, t in zoo().items()),
        ]:
            for k, face in enumerate(faces(shape)):
                boundary = uvclass.read(face)
                if boundary is None:
                    continue
                u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
                du, dv = u1 - u0, v1 - v0
                u = rng.uniform(u0 - du / 2, u1 + du / 2, 400)
                v = rng.uniform(v0 - dv / 2, v1 + dv / 2, 400)
                on, unsure = boundary.points(u, v)
                classifier = IntTools_FClass2d(face, 1e-9)
                expected = np.array([classifier.Perform(gp_Pnt2d(float(a), float(b)), True) != TopAbs_OUT
                                     for a, b in zip(u, v, strict=True)])  # fmt: skip
                with self.subTest(shape=name, face=k):
                    self.assertEqual(int((on != expected)[~unsure].sum()), 0)


@needs_occ
class TheBoundary(unittest.TestCase):
    def test_a_gap_between_edges_is_closed_by_a_banded_piece(self) -> None:
        found = uvclass._Pieces()
        starts = [np.array([0.0, 0.0]), np.array([1.0, 0.0])]
        ends = [np.array([1.0, 1e-8]), np.array([0.0, 0.0])]
        uvclass._close(found, starts, ends, 1.0)
        self.assertEqual(len(found.a), 1)
        np.testing.assert_array_equal(found.a[0], [1.0, 1e-8])
        np.testing.assert_array_equal(found.b[0], [1.0, 0.0])
        self.assertGreater(found.band[0], 1e-8)

    def test_a_wide_gap_leaves_the_face_to_opencascade(self) -> None:
        starts = [np.array([0.0, 0.0]), np.array([1.0, 0.0])]
        ends = [np.array([1.0, 0.1]), np.array([0.0, 0.0])]
        with self.assertRaises(uvclass._UnreadError):
            uvclass._close(uvclass._Pieces(), starts, ends, 1.0)

    def test_a_grid_must_ascend(self) -> None:
        face = faces(BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape())[0]
        with self.assertRaises(ValueError):
            on_grid(face, np.array([0.5, 0.2]), np.array([0.1]))

    def test_past_the_parameter_box_is_off_the_face(self) -> None:
        face = faces(BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape())[0]
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        found = on_grid(
            face,
            np.array([u0 - 0.5, (u0 + u1) / 2, u1 + 0.5]),
            np.array([v0 - 0.5, (v0 + v1) / 2]),
        )
        self.assertEqual(
            found.tolist(), [[False, False], [False, True], [False, False]]
        )

    def test_points_on_the_boundary_are_on_the_face(self) -> None:
        face = faces(BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape())[0]
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        found = on_grid(face, np.array([u0, (u0 + u1) / 2, u1]), np.array([v0, v1]))
        self.assertTrue(found.all())


if __name__ == "__main__":
    unittest.main()
