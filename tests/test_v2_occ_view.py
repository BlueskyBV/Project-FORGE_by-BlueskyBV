"""V2 stage 3: ``BrepView``, the exact view of a built part (forge_occ.view; docs/V2-stage3.md, section 11).

Every question of the protocol against analytic answers, points inside
included; the proxy's contract; the coverage's guarantee against a far finer
sampling, on analytic and B-spline faces (rational ones, a fillet, a coil, a
mapped bend); the volume's interval on analytic solids made B-splines; the
topology's faults found; and the topology equal to the mesh view's on a fine
mesh of the same part.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np
from v2_occ import build, needs_occ, zoo

try:
    from forge_checks.view import Box, Capability, Side, ViewError, ViewProxy
    from forge_occ.measure import VOLUME_RELATIVE
    from forge_occ.occt import edges, faces, shells
    from forge_occ.view import BrepView
    from OCP.BRep import BRep_Builder
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_NurbsConvert,
    )
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.BRepPrimAPI import (
        BRepPrimAPI_MakeBox,
        BRepPrimAPI_MakeCone,
        BRepPrimAPI_MakeCylinder,
        BRepPrimAPI_MakePrism,
        BRepPrimAPI_MakeSphere,
        BRepPrimAPI_MakeTorus,
    )
    from OCP.BRepTools import BRepTools
    from OCP.collections import HArray1_gp_Pnt as TColgp_HArray1OfPnt
    from OCP.GeomAbs import GeomAbs_BSplineCurve
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Pnt2d, gp_Vec
    from OCP.IntTools import IntTools_FClass2d
    from OCP.TopAbs import TopAbs_OUT
    from OCP.TopoDS import TopoDS, TopoDS_Solid
except ImportError:  # no OpenCascade here: every class below is skipped
    pass


def box(
    lo: tuple[float, float, float] = (0.0, 0.0, 0.0),
    size: tuple[float, float, float] = (20.0, 30.0, 40.0),
) -> Any:
    return BRepPrimAPI_MakeBox(gp_Pnt(*lo), *size).Shape()


def hollow() -> Any:
    """A 20 mm cube about the origin with a 5 mm spherical hollow in it."""
    return BRepAlgoAPI_Cut(
        box((-10.0, -10.0, -10.0), (20.0, 20.0, 20.0)),
        BRepPrimAPI_MakeSphere(5.0).Shape(),
    ).Shape()


def finer(face: Any, step: int) -> Any:
    """Points of the face on a grid far finer than any coverage here (in its parameters)."""
    surface = BRepAdaptor_Surface(face, False)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    inside = IntTools_FClass2d(face, 1e-9)
    out = []
    p = gp_Pnt()
    for u in np.linspace(u0, u1, step):
        for v in np.linspace(v0, v1, step):
            if inside.Perform(gp_Pnt2d(float(u), float(v))) != TopAbs_OUT:
                surface.D0(float(u), float(v), p)
                out.append((p.X(), p.Y(), p.Z()))
    return np.asarray(out).reshape(-1, 3)


def nearest(points: Any, samples: Any) -> Any:
    """Each point's distance to the nearest of ``samples`` (brute force, in chunks)."""
    out = np.empty(len(points))
    for start in range(0, len(points), 512):
        chunk = points[start : start + 512]
        out[start : start + 512] = np.sqrt(
            ((chunk[:, None, :] - samples[None, :, :]) ** 2).sum(axis=2)
        ).min(axis=1)
    return out


@needs_occ
class EveryQuestionAgainstAnalyticAnswers(unittest.TestCase):
    def test_classify_a_box_with_a_hollow(self) -> None:
        view = ViewProxy(BrepView(hollow()))
        points = np.array(
            [
                [8.0, 0, 0],
                [0, 0, 0],
                [0, 0, 5.0],
                [0, 0, 10.0],
                [11.0, 0, 0],
                [0, 7.0, 0],
            ]
        )
        sides = view.classify(points)
        self.assertEqual(
            list(sides), [Side.IN, Side.OUT, Side.ON, Side.ON, Side.OUT, Side.IN]
        )

    def test_distance_inside_outside_and_in_the_hollow(self) -> None:
        view = ViewProxy(BrepView(hollow()))
        points = np.array(
            [[9.0, 0, 0], [0, 0, 2.0], [15.0, 0, 0], [0, 7.0, 0.0], [13.0, 14.0, 0]]
        )
        expected = [1.0, 3.0, 5.0, 2.0, 5.0]
        np.testing.assert_allclose(view.distance(points), expected, atol=1e-9)

    def test_crossings_along_a_line(self) -> None:
        view = ViewProxy(BrepView(hollow()))
        found = view.crossings(
            np.array([[-20.0, 0.3, 0.4]]), np.array([[1.0, 0.0, 0.0]])
        )
        r = math.sqrt(25.0 - 0.25)
        np.testing.assert_allclose(found.t, [10.0, 20.0 - r, 20.0 + r, 30.0], atol=1e-7)
        self.assertEqual(list(found.entering), [True, False, True, False])
        self.assertFalse(found.grazed[0])

    def test_the_first_hit_ahead_of_a_ray(self) -> None:
        """How far a ray goes to the surface, and the face's outward normal there: from the material out through the box's side, or into the hollow (its normal into the hollow); none, looking away from the part."""
        view = BrepView(hollow())
        far, normals = view.first_hits(
            np.array([[8.0, 0, 0], [8.0, 0, 0], [15.0, 0, 0]]),
            np.array([[1.0, 0, 0], [-1.0, 0, 0], [1.0, 0, 0]]),
        )
        np.testing.assert_allclose(far[:2], [2.0, 3.0], atol=1e-9)
        np.testing.assert_allclose(normals[:2], [[1.0, 0, 0], [-1.0, 0, 0]], atol=1e-9)
        self.assertEqual(far[2], math.inf)
        self.assertTrue(np.all(np.isnan(normals[2])))

    def test_a_ray_through_an_edge_is_grazed(self) -> None:
        view = ViewProxy(BrepView(box()))
        found = view.crossings(np.array([[-5.0, 0.0, 0.0], [-5.0, 10.0, 20.0]]),
                               np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]))  # fmt: skip
        self.assertTrue(found.grazed[0])
        self.assertFalse(found.grazed[1])

    def test_volumes_hold_the_analytic_ones(self) -> None:
        cases = [
            (box(), 20.0 * 30.0 * 40.0),
            (hollow(), 8000.0 - 4.0 / 3.0 * math.pi * 125.0),
            (BRepPrimAPI_MakeTorus(20.0, 5.0).Shape(), 2.0 * math.pi**2 * 20.0 * 25.0),
            (
                BRepPrimAPI_MakeCone(10.0, 0.0, 20.0).Shape(),
                math.pi * 100.0 * 20.0 / 3.0,
            ),
            (BRepPrimAPI_MakeCylinder(3.0, 7.0).Shape(), math.pi * 9.0 * 7.0),
        ]
        for shape, volume in cases:
            found = ViewProxy(BrepView(shape)).volume()
            self.assertLessEqual(found.lo, volume)
            self.assertLessEqual(volume, found.hi)

    def test_bounds(self) -> None:
        found = ViewProxy(
            BrepView(BRepPrimAPI_MakeSphere(gp_Pnt(1.0, 2.0, 3.0), 4.0).Shape())
        ).bounds()
        np.testing.assert_allclose(found.lo, (-3.0, -2.0, -1.0), atol=1e-6)
        np.testing.assert_allclose(found.hi, (5.0, 6.0, 7.0), atol=1e-6)

    def test_faces_and_edges_by_their_geometry(self) -> None:
        view = ViewProxy(BrepView(BRepPrimAPI_MakeCylinder(3.0, 7.0).Shape()))
        kinds = sorted(f.kind for f in view.faces())
        self.assertEqual(kinds, ["cylinder", "plane", "plane"])
        cylinder = next(f for f in view.faces() if f.kind == "cylinder")
        np.testing.assert_allclose(
            cylinder.surface, (0, 0, 0, 0, 0, 1, 3.0), atol=1e-12
        )
        self.assertAlmostEqual(cylinder.area, 2 * math.pi * 3.0 * 7.0, places=9)
        tops = sorted(f.surface for f in view.faces() if f.kind == "plane")
        np.testing.assert_allclose(tops, [(0, 0, -1, 0), (0, 0, 1, 7.0)], atol=1e-12)
        circles = [e for e in view.edges() if e.kind == "circle"]
        self.assertEqual(len(circles), 2)
        self.assertTrue(all(abs(e.curve[-1] - 3.0) < 1e-12 for e in circles))
        self.assertTrue(all(abs(e.length - 2 * math.pi * 3.0) < 1e-9 for e in circles))

    def test_topology_counts(self) -> None:
        cases = [
            (box(), 1, 1, 0, (0,)),
            (hollow(), 2, 1, 1, (0,)),
            (BRepPrimAPI_MakeTorus(20.0, 5.0).Shape(), 1, 1, 0, (1,)),
            (BRepAlgoAPI_Cut(box(), BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(10.0, 15.0, -1.0), gp_Dir(0, 0, 1)),
                                                            4.0, 50.0).Shape()).Shape(), 1, 1, 0, (1,)),
        ]  # fmt: skip
        for shape, shell_count, solid_count, voids, genus in cases:
            found = ViewProxy(BrepView(shape)).topology()
            self.assertTrue(found.sound)
            self.assertEqual((found.shells, found.solids, found.voids, found.genus),
                             (shell_count, solid_count, voids, genus))  # fmt: skip


@needs_occ
class TheProxysContract(unittest.TestCase):
    def test_every_question_answers_within_the_contract(self) -> None:
        view = ViewProxy(BrepView(hollow()))
        self.assertEqual(view.capabilities, frozenset(Capability))
        points = np.random.default_rng(1).uniform(-12.0, 12.0, (64, 3))
        view.classify(points)
        view.distance(points)
        view.crossings(points, np.tile([0.3, 0.4, 0.5], (64, 1)))
        view.volume()
        view.bounds()
        view.coverage(2.0)
        view.coverage(2.0, view.bounds())
        view.topology()
        view.faces()
        view.edges()

    def test_a_step_file_is_its_own_source_and_nothing_else_is(self) -> None:
        self.assertEqual(
            ViewProxy(BrepView(box(), source="step-file")).source, "step-file"
        )
        with self.assertRaises(ValueError):
            BrepView(box(), source="mesh-file")
        with self.assertRaises(ValueError):
            BrepView(TopoDS_Solid())

    def test_a_coverage_never_comes_back_coarser_than_asked(self) -> None:
        found = ViewProxy(BrepView(box())).coverage(1.5)
        self.assertLessEqual(found.radius, 1.5)


@needs_occ
class NearIsTheExactDistances(unittest.TestCase):
    """``near`` says what ``distance(p) <= t`` says, at points on the surface, just off it either way, and far."""

    def check(self, shape: Any) -> None:
        view = BrepView(shape)
        rng = np.random.default_rng(2)
        cover = view.coverage(1.0)
        on = cover.points
        t = rng.uniform(1e-6, 1e-3, len(on))
        # On it; off it along the normal by less than t, by more, either way; and anywhere round it.
        off = rng.choice([-1.0, 1.0], len(on)) * t * rng.choice([0.5, 2.0], len(on))
        box = view.bounds()
        anywhere = rng.uniform(
            np.asarray(box.lo) - 2, np.asarray(box.hi) + 2, (2000, 3)
        )
        points = np.concatenate([on, on + off[:, None] * cover.normals, anywhere])
        tolerances = np.concatenate([t, t, rng.uniform(1e-6, 1.0, len(anywhere))])
        found = ViewProxy(view).near(points, tolerances)
        exact = view.distance(points) <= tolerances
        self.assertEqual(int((found != exact).sum()), 0)
        self.assertTrue(found[: len(on)].all())

    def test_analytic_faces_a_fillet_and_the_zoo(self) -> None:
        rounded = box()
        maker = BRepFilletAPI_MakeFillet(rounded)
        for edge in edges(rounded)[:4]:
            maker.Add(4.0, TopoDS.Edge(edge))
        parts = zoo()
        for shape in (
            hollow(),
            BRepPrimAPI_MakeTorus(20.0, 5.0).Shape(),
            BRepPrimAPI_MakeCone(10.0, 0.0, 20.0).Shape(),
            maker.Shape(),
            build(parts["golden_clevis"]).shape,
            build(parts["zoo2_flange_hub"]).shape,
        ):
            self.check(shape)

    def test_by_a_curve_its_boundary_follows(self) -> None:
        """A plate's top round a hole whose rim is a B-spline: the boundary follows the rim by a polygon, a band
        round it left unsure; OpenCascade's classifier settles a foot there (generated part 171's thread: 2.9 ms
        an exact distance for each of 50,489 points)."""
        lobes = TColgp_HArray1OfPnt(1, 24)
        for k in range(24):
            a = 2 * math.pi * k / 24
            r = 10.0 + 1.5 * math.cos(3 * a)
            lobe = gp_Pnt(30 + r * math.cos(a), 20 + r * math.sin(a), -1)
            lobes.SetValue(k + 1, lobe)
        curve = GeomAPI_Interpolate(lobes, True, 1e-9)
        curve.Perform()
        wire = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(curve.Curve()).Edge())
        tool = BRepPrimAPI_MakePrism(
            BRepBuilderAPI_MakeFace(wire.Wire()).Face(), gp_Vec(0, 0, 12)
        ).Shape()
        shape = BRepAlgoAPI_Cut(box((0, 0, 0), (60, 40, 10)), tool).Shape()
        self.check(shape)
        view = BrepView(shape)
        widest = max(float(b.band.max()) for b in view._boundaries if b)
        self.assertGreater(widest, 1e-6)
        rim = next(c for c in (BRepAdaptor_Curve(TopoDS.Edge(e)) for e in edges(shape))
                   if c.GetType() == GeomAbs_BSplineCurve and abs(c.Value(c.FirstParameter()).Z() - 10) < 1e-9)  # fmt: skip
        points = []
        # Clear of the rim's one vertex, where OpenCascade's classifier says ON.
        step = (rim.LastParameter() - rim.FirstParameter()) / 500
        for x in rim.FirstParameter() + step * (np.arange(500) + 0.5):
            p, d = gp_Pnt(), gp_Vec()
            rim.D1(float(x), p, d)
            at = np.array([p.X(), p.Y(), p.Z()])
            away = np.cross([d.X(), d.Y(), d.Z()], [0.0, 0.0, 1.0])
            away *= np.sign(away @ (at - (30, 20, 10))) / np.linalg.norm(away)
            points.append(at + widest / 4 * away)  # on the top, in the rim's band
        asked: list[int] = []
        exact = view.distance
        view.distance = lambda p: asked.append(len(p)) or exact(p)  # type: ignore[method-assign]
        on_top = np.array(points)
        self.assertTrue(ViewProxy(view).near(on_top, 1e-4).all())
        above = on_top + np.array([0.0, 0.0, 2e-4])
        self.assertFalse(ViewProxy(view).near(above, 1e-4).any())
        self.assertEqual(sum(asked), 0)

    def test_a_sure_foot_nearer_than_opencascade_measures(self) -> None:
        """Where OpenCascade's distance overshoots, a foot surely on a face is nearer, and taken.

        Its classifier calls a point on a face within its tolerance of a
        curved edge on the edge, and it measures to the edge: on embossed
        letters' tops, a point 4.9e-6 mm in from where two Bézier edges join
        measured 4.9e-6, not 0 (this module's letters' walls). Here its
        distance is made to overshoot everywhere.
        """
        view = BrepView(box())
        view._measured = lambda p: np.full(len(p), 0.5)  # type: ignore[method-assign]
        points = np.array([[5.0, 15.0, 40.0001], [25.0, 15.0, 40.0001]])
        np.testing.assert_allclose(view.distance(points), [1e-4, 0.5], atol=1e-12)
        self.assertEqual(ViewProxy(view).near(points, 2e-4).tolist(), [True, False])

    def test_letters_walls(self) -> None:
        # Surfaces of linear extrusion of the font's straight pieces and quadratic arcs: their feet in closed form.
        from forge_occ.make import boolean, prism
        from forge_occ.ops.letters import letters_region

        region, _ = letters_region("Ç&j@S", 8.0, (20, 10, 5), (0, 1, 0), (1, 0, 0))
        tools = [prism(face, (0.0, 0.0, -1.0)).shape for face in region]
        plate = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 40.0, 20.0, 5.0).Shape()
        self.check(boolean("subtract", [plate], tools).shape)
        self.check(
            boolean(
                "union",
                [plate],
                [prism(face, (0.0, 0.0, 1.0)).shape for face in region],
            ).shape
        )

    def test_a_foot_left_in_a_band_is_settled_by_a_finer_reading(self) -> None:
        """Generated part 1057: a point of the part's top 7e-6 mm from a letter's Bezier edge, outside the letter. The boundary as first read leaves it in a band (7.5e-5 mm), OpenCascade's classifier calls it ON and its distance is to the edge; read again with its bands narrowed, the foot is surely on the face and the distance is none."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import v2_exit4
        from forge_eval.generator import render
        from v2_regressions import REGRESSIONS

        spec = v2_exit4._spec(render(REGRESSIONS[1057][1]).items)
        _, built = v2_exit4._built(spec)
        view = BrepView(built.result.shape)
        point = np.array([[3.245367, -0.856901, 16.441]])
        self.assertAlmostEqual(float(view._measured(point)[0]), 7.0e-6, delta=1e-7)
        self.assertLess(float(view.distance(point)[0]), 1e-9)
        self.assertTrue(ViewProxy(view).near(point, 1e-6)[0])


@needs_occ
class TheCoveragesGuarantee(unittest.TestCase):
    """Every point of every face within the radius of a coverage's point, checked against a far finer sampling."""

    def assert_covers(self, shape: Any, radius: float, fine: int = 220) -> None:
        view = BrepView(shape)
        cover = ViewProxy(view).coverage(radius)
        for k, face in enumerate(view._faces):
            mine = cover.points[cover.patch == k]
            dense = finer(TopoDS.Face(face), fine)
            if not len(dense):
                continue
            self.assertGreater(len(mine), 0)
            worst = float(nearest(dense, mine).max())
            self.assertLessEqual(
                worst, radius, f"face {k}: {worst} against a radius of {radius}"
            )

    def test_analytic_faces(self) -> None:
        for shape in (
            hollow(),
            BRepPrimAPI_MakeTorus(20.0, 5.0).Shape(),
            BRepPrimAPI_MakeCone(10.0, 2.0, 20.0).Shape(),
        ):
            self.assert_covers(shape, 1.5)

    def test_rational_b_spline_faces(self) -> None:
        for shape in (BRepPrimAPI_MakeTorus(20.0, 5.0).Shape(), BRepPrimAPI_MakeSphere(6.0).Shape(),
                      BRepPrimAPI_MakeCone(10.0, 2.0, 20.0).Shape()):  # fmt: skip
            self.assert_covers(BRepBuilderAPI_NurbsConvert(shape, True).Shape(), 1.5)

    def test_a_fillet(self) -> None:
        rounded = box()
        maker = BRepFilletAPI_MakeFillet(rounded)
        for edge in edges(rounded)[:4]:
            maker.Add(4.0, TopoDS.Edge(edge))
        self.assert_covers(maker.Shape(), 1.0)

    def test_a_coil_and_a_mapped_bend(self) -> None:
        parts = zoo()
        for name in ("zoo2_spring", "zoo2_bent_strip"):
            shape = build(parts[name]).shape
            size = max(BrepView(shape).bounds().size)
            self.assert_covers(shape, size / 25.0, fine=160)

    def test_within_a_box_the_points_the_whole_has_there_and_few_others(self) -> None:
        """Covered within a box, each face gives the very points its whole coverage has in the box, so every point of
        the surface there within the radius of one, and few others: the pieces of its parameters that may reach the
        box, its edges' samples near it (docs/V2-stage4.md, 13.10)."""
        drilled = BRepAlgoAPI_Cut(
            box((0.0, 0.0, 0.0), (100.0, 80.0, 10.0)),
            BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(30.0, 30.0, -1.0), gp_Dir(0.0, 0.0, 1.0)), 4.0, 12.0
            ).Shape(),
        ).Shape()
        ball = BRepPrimAPI_MakeSphere(gp_Pnt(50.0, 50.0, 50.0), 30.0).Shape()
        cases = (
            (drilled, Box((25.0, 25.0, 8.0), (36.0, 36.0, 12.0))),  # round the hole's rim
            (drilled, Box((60.0, -1.0, -1.0), (62.0, 2.0, 3.0))),  # across an edge
            (ball, Box((45.0, 45.0, 75.0), (55.0, 55.0, 85.0))),  # round its pole
            (ball, Box((75.0, 45.0, 45.0), (85.0, 55.0, 55.0))),  # across its seam
            (BRepBuilderAPI_NurbsConvert(ball, True).Shape(), Box((45.0, 45.0, 75.0), (55.0, 55.0, 85.0))),
        )  # fmt: skip
        for shape, within in cases:
            view = BrepView(shape)
            whole, near = view.coverage(0.25), ViewProxy(view).coverage(0.25, within)
            lo, hi = np.asarray(within.lo), np.asarray(within.hi)
            mine = np.all((near.points >= lo) & (near.points <= hi), axis=1)
            all_of = np.all((whole.points >= lo) & (whole.points <= hi), axis=1)
            self.assertGreater(int(mine.sum()), 100)
            self.assertEqual(sorted(map(tuple, near.points[mine].tolist())),
                             sorted(map(tuple, whole.points[all_of].tolist())))  # fmt: skip
            self.assertLess(len(near.points), 3 * int(mine.sum()))

    def test_normals_are_unit_and_outward(self) -> None:
        for shape in (hollow(), BRepPrimAPI_MakeTorus(20.0, 5.0).Shape()):
            view = BrepView(shape)
            cover = view.coverage(2.0)
            np.testing.assert_allclose(
                np.linalg.norm(cover.normals, axis=1), 1.0, atol=1e-12
            )
            pick = np.random.default_rng(2).choice(
                len(cover.points), 300, replace=False
            )
            out = view.classify(cover.points[pick] + 1e-3 * cover.normals[pick])
            inside = view.classify(cover.points[pick] - 1e-3 * cover.normals[pick])
            # On an edge a point moved along one face's normal may land on the next face: never the wrong side.
            self.assertFalse((out == Side.IN).any())
            self.assertFalse((inside == Side.OUT).any())
            self.assertGreater(float((out == Side.OUT).mean()), 0.5)
            self.assertGreater(float((inside == Side.IN).mean()), 0.5)

    def test_a_pointed_cone_s_normals_at_its_apex_too(self) -> None:
        # Generated part 244's needle: its face's bounds reach 1.2e-7 mm past the apex, onto the other nappe,
        # whose derivatives (and OpenCascade's own normal there) face the other way.
        radius, length = 1.574, 12.495
        # The outward normal's share along the cone's axis.
        rise = radius / math.hypot(radius, length)
        for low, high, way in ((radius, 0.0, 1.0), (0.0, radius, -1.0)):
            cover = ViewProxy(
                BrepView(BRepPrimAPI_MakeCone(low, high, length).Shape())
            ).coverage(0.5)
            on_side = (np.abs(cover.normals[:, 2]) < 0.99) & (
                np.abs(cover.points[:, 2] - length / 2) < length / 2 + 1e-6
            )
            n, p = cover.normals[on_side], cover.points[on_side]
            apex = np.abs(p[:, 2] - (length if way > 0 else 0.0)) < 1e-6
            self.assertGreater(int(apex.sum()), 4)
            np.testing.assert_allclose(n[:, 2], way * rise, atol=1e-6)
            # Away from the apex, the radial part points away from the axis.
            radial = np.linalg.norm(p[:, :2], axis=1) > 1e-3
            outward = np.einsum("ij,ij->i", n[radial, :2], p[radial, :2])
            self.assertTrue((outward > 0).all())


@needs_occ
class TheVolumesInterval(unittest.TestCase):
    def test_analytic_solids_made_b_splines_are_well_inside_it(self) -> None:
        cases = [
            (BRepPrimAPI_MakeSphere(6.0).Shape(), 4.0 / 3.0 * math.pi * 216.0),
            (BRepPrimAPI_MakeTorus(20.0, 5.0).Shape(), 2.0 * math.pi**2 * 20.0 * 25.0),
            (
                BRepPrimAPI_MakeCone(10.0, 2.0, 20.0).Shape(),
                math.pi * 20.0 / 3.0 * (100.0 + 20.0 + 4.0),
            ),
        ]
        for shape, volume in cases:
            nurbs = BRepBuilderAPI_NurbsConvert(shape, True).Shape()
            found = BrepView(nurbs).volume()
            middle = (found.lo + found.hi) / 2.0
            self.assertLessEqual(abs(middle - volume) / volume, VOLUME_RELATIVE / 5.0)


@needs_occ
class TheTopologyFindsFaults(unittest.TestCase):
    def test_two_shells_that_cross_in_one_solid(self) -> None:
        solid = TopoDS_Solid()
        builder = BRep_Builder()
        builder.MakeSolid(solid)
        builder.Add(solid, shells(box())[0])
        builder.Add(solid, shells(box((5.0, 5.0, 5.0)))[0])
        found = BrepView(solid).topology()
        self.assertGreater(found.self_intersections, 0)
        self.assertFalse(found.sound)
        self.assertIsNone(found.solids)

    def test_a_shell_with_a_face_missing(self) -> None:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing

        sewing = BRepBuilderAPI_Sewing(1e-6)
        for face in faces(box())[:5]:
            sewing.Add(face)
        sewing.Perform()
        solid = TopoDS_Solid()
        builder = BRep_Builder()
        builder.MakeSolid(solid)
        builder.Add(solid, shells(sewing.SewedShape())[0])
        found = BrepView(solid).topology()
        self.assertEqual(found.open_edges, 4)
        self.assertFalse(found.sound)

    def test_two_boxes_meeting_at_a_corner(self) -> None:
        joined = BRepAlgoAPI_Fuse(
            box(size=(10.0, 10.0, 10.0)), box((10.0, 10.0, 10.0), (10.0, 10.0, 10.0))
        ).Shape()
        found = BrepView(joined).topology()
        self.assertFalse(found.sound)

    def test_two_corners_in_one_place_no_edge_joins(self) -> None:
        """Two boxes in one solid, a corner of each at the same point, not joined there: the surface meets itself."""
        solid = TopoDS_Solid()
        builder = BRep_Builder()
        builder.MakeSolid(solid)
        builder.Add(solid, shells(box(size=(10.0, 10.0, 10.0)))[0])
        builder.Add(solid, shells(box((10.0, 10.0, 10.0), (10.0, 10.0, 10.0)))[0])
        found = BrepView(solid).topology()
        self.assertGreater(found.self_intersections, 0)
        self.assertFalse(found.sound)


@needs_occ
class AReadersTinyEdges(unittest.TestCase):
    """Generated part 3500 read back from STEP: where a boss's rim touches the block's edge, OpenCascade's reader cut the block's edge and the rim there, 1.7e-8 mm apart, each piece between joining the same two corners.

    Those corners are within each other's tolerance, but an edge joins them:
    the surface doesn't meet itself there, and the part read back is sound.
    An edge that short is covered by its ends (dividing it by length, as
    every other edge is, OpenCascade couldn't).
    """

    @classmethod
    def setUpClass(cls) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from forge_eval.generator import render
        from forge_occ.export import StepPart, read_step, write_step
        from v2_exit4 import _built, _spec
        from v2_regressions import REGRESSIONS

        _, built = _built(_spec(render(REGRESSIONS[3500][1]).items))
        data = write_step([StepPart("part", built.result.shape)])
        cls.back = read_step(data).parts["part"]

    def test_the_reader_made_them(self) -> None:
        from OCP.BRep import BRep_Tool
        from OCP.GCPnts import GCPnts_AbscissaPoint

        lengths = [
            GCPnts_AbscissaPoint.Length_s(BRepAdaptor_Curve(e))
            for e in edges(self.back)
            if not BRep_Tool.Degenerated_s(e)
        ]
        self.assertEqual(sum(1 for length in lengths if length < 1e-6), 2)

    def test_corners_an_edge_joins_are_not_a_meeting(self) -> None:
        found = BrepView(self.back).topology()
        self.assertEqual(found.self_intersections, 0)
        self.assertTrue(found.sound)

    def test_an_edge_shorter_than_the_spacing_is_covered_by_its_ends(self) -> None:
        covered = BrepView(self.back).coverage(0.5)
        self.assertGreater(len(covered.points), 0)


@needs_occ
class AReadersTinyLoops(unittest.TestCase):
    """Generated part 3610 read back from STEP: where a boss's rim touches the block's edge, OpenCascade's reader cut a loop into the block's edge there, 5.5e-9 mm long and held to 1.5e-7 mm, which the rim and the boss's side pass through.

    The self-interference checker finds the rim and the side meeting that
    loop, and the rim meeting the side, all within it. An edge no longer
    than it is held to is a point: what meets there meets at it, and the
    part read back is sound. A meeting anywhere else is still counted.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from forge_eval.generator import render
        from forge_occ.export import StepPart, read_step, write_step
        from v2_exit4 import _built, _spec
        from v2_regressions import REGRESSIONS

        _, built = _built(_spec(render(REGRESSIONS[3610][1]).items))
        cls.written = built.result.shape
        cls.back = read_step(write_step([StepPart("part", cls.written)])).parts["part"]

    def test_the_reader_made_them(self) -> None:
        from forge_occ.view import _point_edges

        self.assertEqual(_point_edges(self.written), [])
        self.assertEqual(len(_point_edges(self.back)), 2)

    def test_what_meets_at_them_is_not_a_meeting(self) -> None:
        self.assertEqual(BrepView(self.written).topology().self_intersections, 0)
        found = BrepView(self.back).topology()
        self.assertEqual(found.self_intersections, 0)
        self.assertTrue(found.sound)

    def test_a_meeting_elsewhere_is_counted(self) -> None:
        """Two boxes' shells crossing in one solid: each meeting the checker finds is at a point edge put where it lies, and at none put away from it."""
        from forge_occ.view import _CHECKED_LEVEL, _at_a_point_edge
        from OCP.BOPAlgo import BOPAlgo_CheckerSI
        from OCP.collections import List_TopoDS_Shape

        solid = TopoDS_Solid()
        builder = BRep_Builder()
        builder.MakeSolid(solid)
        builder.Add(solid, shells(box())[0])
        builder.Add(solid, shells(box((5.0, 5.0, 5.0)))[0])
        checker = BOPAlgo_CheckerSI()
        arguments = List_TopoDS_Shape()
        arguments.Append(solid)
        checker.SetArguments(arguments)
        checker.SetRunParallel(False)
        checker.SetNonDestructive(True)
        checker.SetLevelOfCheck(_CHECKED_LEVEL)
        checker.Perform()
        store = checker.DS()
        met = [store.InterfEE().Value(k) for k in range(store.InterfEE().Size())]
        met += [store.InterfEF().Value(k) for k in range(store.InterfEF().Size())]
        self.assertGreater(len(met), 0)
        for meeting in met:
            self.assertFalse(_at_a_point_edge(store, meeting, [(np.array([-50.0, -50.0, -50.0]), 1e-7)]))
            self.assertFalse(_at_a_point_edge(store, meeting, []))
        # A point edge as wide as the whole of them: every meeting lies at it.
        self.assertTrue(all(_at_a_point_edge(store, m, [(np.array([7.5, 7.5, 7.5]), 100.0)]) for m in met))


@needs_occ
class AWindowsTip(unittest.TestCase):
    def test_the_built_point_there_is_accounted_for(self) -> None:
        """Generated part 5035: a hole leaning 5.5 degrees cuts a long window in a through pocket's floor. The exact kernel put the window's tip 1e-8 mm inside the hole, the spec's surface ends some 1e-7 mm along the floor from it, and the B-rep's coverage has a point there; its witness is the spec's tip, found where the floor and the hole meet at that small angle from a point on the floor."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from forge_checks.accounting import account_faces
        from forge_checks.classes import Verdict
        from forge_checks.judge import Judge
        from forge_eval.generator import render
        from v2_exit4 import _built, _spec
        from v2_regressions import REGRESSIONS

        spec = _spec(render(REGRESSIONS[5035][1]).items)
        _, built = _built(spec)
        judge = Judge.of(spec)
        found = account_faces(judge.part, ViewProxy(BrepView(built.result.shape)), judge.suite.resolution)
        self.assertIs(found.verdict, Verdict.PASS, found.misses[:2])


@needs_occ
class TheTopologyIsTheMeshViews(unittest.TestCase):
    """The same counts as the stage-2 mesh view of a fine mesh of the same part (11.1)."""

    def test_analytic_solids_and_the_zoo(self) -> None:
        from forge_checks.mesh import MeshView
        from forge_occ.export import ExportTolerance, mesh_part

        shapes = [box(), hollow(), BRepPrimAPI_MakeTorus(20.0, 5.0).Shape()]
        parts = zoo()
        shapes += [
            build(parts[name]).shape for name in sorted(parts) if name != "zoo2_spring"
        ]
        for shape in shapes:
            ours = BrepView(shape).topology()
            mesh = mesh_part(shape, ExportTolerance(linear=0.05)).mesh
            theirs = MeshView(mesh, source="mesh-file", deflection=0.05).topology()
            self.assertEqual(
                (
                    ours.sound,
                    ours.shells,
                    ours.solids,
                    ours.voids,
                    ours.genus,
                    ours.misnested,
                ),
                (
                    theirs.sound,
                    theirs.shells,
                    theirs.solids,
                    theirs.voids,
                    theirs.genus,
                    theirs.misnested,
                ),
            )

    def test_bosses_flush_with_a_faces_edges_make_no_through_hole(self) -> None:
        """Generated part 450: a boss flush with a face's edge, its circle touching the face's outline at a point. The face is one piece round it: counted by its wires alone, each such face lost one from the Euler characteristic, and two made a through-hole the part doesn't have (genus 12 for 11)."""
        from forge_checks.mesh import MeshView
        from forge_occ.export import ExportTolerance, mesh_part
        from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

        part = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
        # Radius 2: the circles touch the face's edges at y = 0 and y = 10.
        for y in (2.0, 8.0):
            axis = gp_Ax2(gp_Pnt(10.0, y, 5.0), gp_Dir(1.0, 0.0, 0.0))
            boss = BRepPrimAPI_MakeCylinder(axis, 2.0, 4.0).Shape()
            part = BRepAlgoAPI_Fuse(part, boss).Shape()
        ours = BrepView(part).topology()
        mesh = mesh_part(part, ExportTolerance(linear=0.05)).mesh
        theirs = MeshView(mesh, source="mesh-file", deflection=0.05).topology()
        self.assertTrue(ours.sound)
        self.assertEqual((ours.solids, ours.voids, ours.genus), (1, 0, (0,)))
        self.assertEqual(
            (ours.solids, ours.voids, ours.genus),
            (theirs.solids, theirs.voids, theirs.genus),
        )


@needs_occ
class TheViewIsRefusedWhatIsNoSolid(unittest.TestCase):
    def test_no_solid(self) -> None:
        with self.assertRaises(ValueError):
            BrepView(faces(box())[0])

    def test_a_failure_inside_is_a_view_error(self) -> None:
        view = ViewProxy(BrepView(box()))
        with self.assertRaises(ValueError):
            view.classify(np.array([[np.nan, 0.0, 0.0]]))
        self.assertTrue(issubclass(ViewError, Exception))


if __name__ == "__main__":
    unittest.main()
