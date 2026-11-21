"""V2 stage 3: export, and every file read back before it is handed over (forge_occ.export; docs/V2-stage3.md, section 12).

STEP, STL and 3MF each written and read back and held to the part; meshes
welded by the part's own edges (a sphere's pole, a seam); triangles the
mesher left too far from their face split until they aren't; a mesh too far
from the surface remade, then refused; a file altered after it was written caught;
an inch STEP file read in millimetres, and refused as Forge's own; an
assembly's names and placements read back.
"""

from __future__ import annotations

import math
import struct
import unittest
from typing import Any
from unittest import mock

import numpy as np
from v2_occ import CLEVIS_PIN, build, needs_occ, v2, zoo

try:
    from forge_checks.mesh import MeshView
    from forge_checks.readers import read_3mf, read_stl
    from forge_checks.view import Box
    from forge_occ import export
    from forge_occ.assembly import build_assembly, check_mates_read_back
    from forge_occ.errors import OperationError
    from forge_occ.export import (
        ExportTolerance,
        StepPart,
        check_mesh_file,
        check_step,
        mesh_part,
        plate_shift,
        read_step,
        stl_bytes,
        threemf_bytes,
        write_step,
    )
    from forge_occ.geom import Motion
    from forge_occ.measure import properties, volume_interval
    from forge_occ.view import BrepView
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import (
        BRepPrimAPI_MakeBox,
        BRepPrimAPI_MakeCone,
        BRepPrimAPI_MakePrism,
        BRepPrimAPI_MakeSphere,
        BRepPrimAPI_MakeTorus,
    )
    from OCP.Geom import Geom_BezierSurface
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec
except ImportError:  # no OpenCascade here: every class below is skipped
    pass


def _poles(rows: list[list[tuple[float, float, float]]]) -> Any:
    from OCP.collections import Array2_gp_Pnt as TColgp_Array2OfPnt

    poles = TColgp_Array2OfPnt(1, len(rows), 1, len(rows[0]))
    for i, row in enumerate(rows, start=1):
        for j, (x, y, z) in enumerate(row, start=1):
            poles.SetValue(i, j, gp_Pnt(x, y, z))
    return poles


def _part(seed: int) -> Any:
    """A generated part kept as a regression, as Forge builds it, built afresh."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from forge_eval.generator import render
    from v2_exit4 import _built, _spec
    from v2_regressions import REGRESSIONS

    _, built = _built(_spec(render(REGRESSIONS[seed][1]).items))
    return built.result.shape


def _part_6950() -> Any:
    """Generated part 6950: a block whose small through bores meet big blind holes."""
    return _part(6950)


def _shortest_edge(shape: Any) -> float:
    """The length of the shape's shortest edge (mm)."""
    from forge_occ.occt import edges
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_AbscissaPoint

    return min(
        GCPnts_AbscissaPoint.Length_s(BRepAdaptor_Curve(e))
        for e in edges(shape)
        if not BRep_Tool.Degenerated_s(e)
    )


def shapes() -> list[tuple[str, Any]]:
    hollow = BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(gp_Pnt(-10, -10, -10), 20.0, 20.0, 20.0).Shape(),
                             BRepPrimAPI_MakeSphere(5.0).Shape()).Shape()  # fmt: skip
    return [
        ("box", BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()),
        ("sphere", BRepPrimAPI_MakeSphere(gp_Pnt(3.0, 4.0, 5.0), 6.0).Shape()),
        ("cone", BRepPrimAPI_MakeCone(4.0, 0.0, 9.0).Shape()),
        ("torus", BRepPrimAPI_MakeTorus(15.0, 3.0).Shape()),
        ("hollow", hollow),
    ]


@needs_occ
class FinerWhereAsked(unittest.TestCase):
    """A finer tolerance in a box: the faces whose surface comes near it meshed and measured to it, the rest to the part's; a mesh file's reader works out each triangle's from the spec alone (docs/V2-stage4.md, 13.10)."""

    def test_a_countersink_in_a_dome_s_base(self) -> None:
        dome = BRepAlgoAPI_Cut(
            BRepPrimAPI_MakeSphere(30.0).Shape(),
            BRepPrimAPI_MakeBox(gp_Pnt(-40, -40, -40), 80.0, 80.0, 40.0).Shape(),
        ).Shape()
        sink = BRepPrimAPI_MakeCone(
            gp_Ax2(gp_Pnt(10.0, 0.0, -1.0), gp_Dir(0.0, 0.0, 1.0)), 5.0, 0.0, 5.0
        ).Shape()
        part = BRepAlgoAPI_Cut(dome, sink).Shape()
        near = Box((4.0, -6.0, -2.0), (16.0, 6.0, 5.0))
        coarse, fine = (
            ExportTolerance(0.0025),
            ExportTolerance(0.0025, 0.1, ((near, 0.0005),)),
        )
        each = export.face_tolerances(part, fine)
        kinds = [f.kind for f in BrepView(part).faces()]
        self.assertEqual(sorted(zip(kinds, each.tolist(), strict=True)),
                         [("cone", 0.0005), ("plane", 0.0005), ("sphere", 0.0025)])  # fmt: skip
        made, plain = mesh_part(part, fine), mesh_part(part, coarse)
        self.assertLess(len(made.mesh.faces), 1.2 * len(plain.mesh.faces))
        self.assertTrue(
            MeshView(made.mesh, source="mesh-file", deflection=0.0).topology().sound
        )
        by_face, _ = export.deviations(
            part,
            made.mesh.vertices[made.mesh.faces],
            made.face,
            made.uv,
            enough=each / 2,
        )
        self.assertTrue(np.all(by_face <= each), (by_face, each))
        # Read back: each triangle held to what a reader works out for it, never looser than its face was made to.
        data = stl_bytes(made.mesh, "part")
        check_mesh_file(data, part, made, fine)
        triangles = read_stl(data).triangles
        told = fine.of_triangles(triangles)
        self.assertTrue(np.all(each[made.face] <= told * (1 + 1e-12)))
        self.assertEqual(set(told.tolist()), {0.0005, 0.0025})
        self.assertTrue(np.all(export.file_view(made.mesh, fine).deflections == fine.of_triangles(
            made.mesh.vertices[made.mesh.faces])))  # fmt: skip
        # A mesh made to the part's tolerance alone is refused as the finer one's.
        with self.assertRaises(OperationError):
            check_mesh_file(stl_bytes(plain.mesh, "part"), part, plain, fine)
        with self.assertRaises(ValueError):
            ExportTolerance(0.0025, 0.1, ((near, 0.0025),))

    def test_two_finer_faces_meeting_at_an_edge(self) -> None:
        """A countersink in one finer box, the face round it reaching a finer one: one mesh along their edge (part 4180).

        Meshed apart, each face's edge is discretised to its own
        deflection, and the weld by the edge's nodes tears.
        """
        block = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 40.0, 20.0, 10.0).Shape()
        sink = BRepPrimAPI_MakeCone(
            gp_Ax2(gp_Pnt(30.0, 10.0, 7.0), gp_Dir(0.0, 0.0, 1.0)), 0.0, 3.0, 3.0
        ).Shape()
        part = BRepAlgoAPI_Cut(block, sink).Shape()
        tolerance = ExportTolerance(0.005, 0.1, (
            (Box((3.0, 8.0, 9.0), (7.0, 12.0, 11.0)), 0.0005),
            (Box((26.0, 6.0, 6.0), (34.0, 14.0, 11.0)), 0.000664),
        ))  # fmt: skip
        each = export.face_tolerances(part, tolerance)
        kinds = [f.kind for f in BrepView(part).faces()]
        self.assertEqual(sorted(zip(kinds, each.tolist(), strict=True))[:2],
                         [("cone", 0.000664), ("plane", 0.0005)])  # fmt: skip
        mesh, _, _ = export._triangulate(part, each, tolerance.angular)
        self.assertEqual(
            MeshView(mesh, source="mesh-file", deflection=0.0).topology().open_edges, 0
        )
        made = mesh_part(part, tolerance)
        self.assertTrue(
            MeshView(made.mesh, source="mesh-file", deflection=0.0).topology().sound
        )
        check_mesh_file(stl_bytes(made.mesh, "part"), part, made, tolerance)

    def test_generated_part_4180(self) -> None:
        """Its top face in the finer box round its tube, a countersink in the box round itself: meshed to the tolerances its checks ask, closed, and read back held to them."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from forge_checks.judge import Judge
        from forge_cli.build import export_tolerance
        from forge_eval.generator import render
        from v2_exit4 import _built, _spec
        from v2_regressions import REGRESSIONS

        spec = _spec(render(REGRESSIONS[4180][1]).items)
        _, built = _built(spec)
        shape = built.result.shape
        tolerance = export_tolerance(Judge.of(spec).suite)
        self.assertEqual(len(tolerance.finer), 2)
        made = mesh_part(shape, tolerance)
        self.assertTrue(
            MeshView(made.mesh, source="mesh-file", deflection=0.0).topology().sound
        )
        check_mesh_file(stl_bytes(made.mesh, "part"), shape, made, tolerance)


@needs_occ
class MeshesAreWeldedAndMeasured(unittest.TestCase):
    def test_every_mesh_is_closed_and_within_the_tolerance(self) -> None:
        tolerance = ExportTolerance(linear=0.01)
        for name, shape in shapes():
            with self.subTest(name):
                part = mesh_part(shape, tolerance)
                self.assertTrue(
                    MeshView(part.mesh, source="mesh-file", deflection=0.0)
                    .topology()
                    .sound
                )
                self.assertLessEqual(part.deviation, tolerance.linear)
                self.assertEqual(len(part.face), len(part.mesh.faces))
                self.assertEqual(part.uv.shape, (len(part.mesh.faces), 3, 2))

    def test_a_mesher_that_stays_too_far_is_remade_then_refused(self) -> None:
        coarse = export._triangulate
        calls = []

        def always_coarse(shape: Any, deflection: float, angular: float) -> Any:
            calls.append(deflection)
            return coarse(shape, 2.0, 0.8)

        with (
            mock.patch.object(export, "_triangulate", always_coarse),
            self.assertRaises(OperationError),
        ):
            mesh_part(BRepPrimAPI_MakeSphere(6.0).Shape(), ExportTolerance(linear=0.01))
        self.assertEqual(len(calls), export.REMESHES + 1)
        self.assertEqual(calls, [0.01 / 2**k for k in range(export.REMESHES + 1)])

    def test_a_point_on_the_surface_is_measured_on_it_wherever_its_parameters_start(
        self,
    ) -> None:
        """Generated part 7470: a letter's side, the extrusion of a Bézier curve whose last two poles coincide (its speed falls to nothing at its end). A mesh's sample on it, at its triangle's parameters 0.092 mm from it, the local search went nowhere from; the sample was 1e-14 mm from the surface, and the mesh was refused at every refinement. It is measured on the surface."""
        from OCP.collections import Array1_gp_Pnt as TColgp_Array1OfPnt
        from OCP.Geom import Geom_BezierCurve, Geom_SurfaceOfLinearExtrusion

        poles = TColgp_Array1OfPnt(1, 3)
        for i, xyz in enumerate(
            [
                (-2.247699, 20.835566, 0.0),
                (-1.684259, 20.835566, 0.0),
                (-1.684259, 20.835566, 0.0),
            ],
            start=1,
        ):
            poles.SetValue(i, gp_Pnt(*xyz))
        side = Geom_SurfaceOfLinearExtrusion(
            Geom_BezierCurve(poles), gp_Dir(0.0, 0.0, 1.0)
        )
        face = BRepBuilderAPI_MakeFace(side, 0.0, 1.0, -0.409, 0.0, 1e-7).Face()
        on = side.Value(
            0.51, -0.4085
        )  # a point of the surface, its parameters 0.51 along the curve
        sample = np.array([[on.X(), on.Y(), on.Z()]])
        start = np.array(
            [[0.72265625, -0.4085]]
        )  # where its triangle's parameters put it
        found = export._face_deviation(face, sample, start, 1.25e-3)
        self.assertLess(float(found[0]), 1e-9)

    def test_triangles_left_too_far_from_their_face_are_split_until_they_arent(
        self,
    ) -> None:
        # A slab whose top and bottom are saddles, z = xy/10 over a 10 mm square: straight edges round
        # a curved inside, which the mesher at 0.5 mm leaves as a couple of triangles.
        saddle = Geom_BezierSurface(
            _poles([[(0, 0, 0), (0, 10, 0)], [(10, 0, 0), (10, 10, 10)]])
        )
        face = BRepPrimAPI_MakePrism(
            BRepBuilderAPI_MakeFace(saddle, 1e-7).Face(), gp_Vec(0.0, 0.0, 5.0)
        ).Shape()
        mesh, owner, uv = export._triangulate(face, 0.5, 0.8)
        before, _ = export.deviation(
            face, mesh.vertices[mesh.faces], owner, uv, enough=1e-3
        )
        self.assertGreater(before, 1e-3)
        fine, fine_owner, fine_uv, near = export.refine(face, mesh, owner, uv, 1e-3)
        self.assertLessEqual(near, 1e-3)
        again, _ = export.deviation(
            face, fine.vertices[fine.faces], fine_owner, fine_uv, enough=1e-3
        )
        self.assertLessEqual(again, 1e-3 + 1e-12)
        self.assertGreater(len(fine.faces), len(mesh.faces))

        # Still one sheet: every inside side between two triangles, running opposite ways; the rim as it was.
        def sides(m: Any) -> Any:
            f = m.faces
            return np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])

        directed = sides(fine)
        _, count = np.unique(np.sort(directed, axis=1), axis=0, return_counts=True)
        self.assertLessEqual(int(count.max()), 2)
        self.assertEqual(len({tuple(map(int, e)) for e in directed}), len(directed))

        def rim(m: Any) -> int:
            _, used = np.unique(np.sort(sides(m), axis=1), axis=0, return_counts=True)
            return int((used == 1).sum())

        self.assertEqual(rim(fine), rim(mesh))
        # Every new point is on the surface.
        self.assertLess(float(BrepView(face).distance(fine.vertices).max()), 1e-9)

    def test_splitting_beside_coarse_edges_falls_back_to_the_mesh_as_made(self) -> None:
        sphere = BRepPrimAPI_MakeSphere(6.0).Shape()
        made = export._triangulate(sphere, 2.0, 0.8)
        mesh, _, _, near, view = export.refined(sphere, *made, 1e-3)
        self.assertTrue(view.topology().sound)
        self.assertIsNone(near)
        self.assertEqual(len(mesh.faces), len(made[0].faces))

    def test_tolerances_must_be_positive(self) -> None:
        for bad in ({"linear": 0.0}, {"angular": -1.0}, {"linear": math.nan}):
            with self.assertRaises(ValueError):
                ExportTolerance(**bad)


@needs_occ
class StlAndThreeMf(unittest.TestCase):
    def test_both_read_back_and_hold(self) -> None:
        tolerance = ExportTolerance()
        for name, shape in [*shapes(), ("clevis", build(zoo()["golden_clevis"]).shape)]:
            with self.subTest(name):
                part = mesh_part(shape, tolerance)
                stl = stl_bytes(part.mesh, name)
                self.assertEqual(len(stl), 84 + 50 * len(part.mesh.faces))
                self.assertEqual(
                    struct.unpack_from("<I", stl, 80)[0], len(part.mesh.faces)
                )
                found = check_mesh_file(stl, shape, part, tolerance)
                exact = volume_interval(shape)
                self.assertLessEqual(found.volume[0], exact.lo)
                self.assertLessEqual(exact.hi, found.volume[1])
                shift = plate_shift(part.mesh)
                threemf = threemf_bytes(part.mesh, name, shift)
                self.assertEqual(
                    check_mesh_file(threemf, shape, part, tolerance, shift=shift).kind,
                    "3mf",
                )
                read = read_3mf(threemf)
                self.assertEqual(read.unit, "millimeter")
                self.assertAlmostEqual(
                    float(read.triangles[:, :, 2].min()), 0.0, delta=1e-5
                )

    def test_a_file_altered_after_it_was_written_is_caught(self) -> None:
        tolerance = ExportTolerance()
        shape = BRepPrimAPI_MakeSphere(6.0).Shape()
        part = mesh_part(shape, tolerance)
        stl = bytearray(stl_bytes(part.mesh))
        # The first triangle's first corner moved 0.1 mm along x.
        x = struct.unpack_from("<f", stl, 84 + 12)[0]
        struct.pack_into("<f", stl, 84 + 12, x + 0.1)
        with self.assertRaises(OperationError):
            check_mesh_file(bytes(stl), shape, part, tolerance)

    def test_a_coarse_mesh_read_back_is_caught(self) -> None:
        tolerance = ExportTolerance(linear=0.01)
        shape = BRepPrimAPI_MakeSphere(6.0).Shape()
        fine = mesh_part(shape, tolerance)
        mesh, owner, uv = export._triangulate(shape, 0.5, 0.5)
        coarse = export.PartMesh(mesh, owner, uv, 0.0, 0.5)
        with self.assertRaises(OperationError):
            check_mesh_file(stl_bytes(mesh), shape, coarse, tolerance)
        self.assertLessEqual(fine.deviation, tolerance.linear)

    def test_a_wall_thinning_to_an_edge_is_accounted_for(self) -> None:
        """Generated part 1880: a hole through everything behind it grazes a tube's side under a dome, the wall between thinning to an edge round the window it cuts. The STL's triangles along that edge were 0.002 mm from it; the spec's surface there is found where the hole and the side meet, at so small an angle that projecting onto each in turn crept, and the file is accounted for as the part is."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from forge_checks.accounting import account_faces
        from forge_checks.classes import Verdict
        from forge_checks.judge import Judge
        from forge_checks.mesh import Mesh
        from forge_checks.view import ViewProxy
        from forge_cli.build import export_tolerance
        from forge_eval.generator import render
        from v2_exit4 import _built, _spec
        from v2_regressions import REGRESSIONS

        # As made when it was found: its hole through everything comes out of the dome's flat face through the tube's
        # wall standing there, which the generator draws no longer (generated part 5468).
        spec = _spec(render(REGRESSIONS[1880][1], strict=False).items)
        _, built = _built(spec)
        judge = Judge.of(spec)
        tolerance = export_tolerance(judge.suite)
        meshed = mesh_part(built.result.shape, tolerance)
        mesh = Mesh.from_triangles(read_stl(stl_bytes(meshed.mesh, "part")).triangles)
        found = account_faces(judge.part, ViewProxy(export.file_view(mesh, tolerance)), judge.suite.resolution)
        self.assertIs(found.verdict, Verdict.PASS, found.misses[:2])
        self.assertGreater(found.built.witnessed, 20)

    def test_the_mesh_read_back_is_the_mesh_written(self) -> None:
        part = mesh_part(BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape())
        read = read_stl(stl_bytes(part.mesh))
        np.testing.assert_allclose(
            read.triangles, part.mesh.vertices[part.mesh.faces], atol=1e-5
        )


@needs_occ
class Step(unittest.TestCase):
    def test_each_part_reads_back_as_it_was_written(self) -> None:
        for name, shape in [*shapes(), ("clevis", build(zoo()["golden_clevis"]).shape),
                            ("bent strip", build(zoo()["zoo2_bent_strip"]).shape)]:  # fmt: skip
            with self.subTest(name):
                data = write_step([StepPart(name, shape)])
                self.assertIn(b"SI_UNIT(.MILLI.,.METRE.)", data)
                self.assertIn(b"AP242", data)
                found, report = check_step(data, [StepPart(name, shape)])
                self.assertEqual(list(found.parts), [name])
                self.assertLessEqual(max(report.parts[name].values()), 1e-6)

    def test_a_part_read_back_states_no_finer_tolerance_than_its_geometry(self) -> None:
        """Where two cylinders cross, the file's curves are an approximation: read back, the part says so.

        The file states the part's loosest tolerance as its uncertainty, and
        nothing read back is said to be nearer its true surface than that:
        judged against its spec, the part read back passes face accounting at
        its own tolerances, as the part written does.
        """
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from forge_checks.accounting import account_faces
        from forge_checks.classes import Verdict
        from forge_checks.judge import Judge
        from forge_checks.view import ViewProxy
        from forge_eval.generator import generate
        from forge_occ.occt import loosest_tolerance
        from forge_occ.view import BrepView
        from OCP.BRep import BRep_Tool
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
        from OCP.TopExp import TopExp_Explorer
        from v2_exit4 import _built, _spec

        case = generate(0)  # holes round a rod's side, crossing it along curves
        spec = _spec(case.items)
        _, built = _built(spec)
        shape = built.result.shape
        data = write_step([StepPart("part", shape)])
        self.assertGreaterEqual(export._uncertainty(data), loosest_tolerance(shape))
        back = read_step(data).parts["part"]
        from OCP.TopoDS import TopoDS

        for kind, cast in (
            (TopAbs_FACE, TopoDS.Face),
            (TopAbs_EDGE, TopoDS.Edge),
            (TopAbs_VERTEX, TopoDS.Vertex),
        ):
            explorer = TopExp_Explorer(back, kind)
            while explorer.More():
                stated = BRep_Tool.Tolerance_s(cast(explorer.Current()))
                self.assertGreaterEqual(stated, export._uncertainty(data) * (1 - 1e-9))
                explorer.Next()
        judge = Judge.of(spec)
        found = account_faces(
            judge.part,
            ViewProxy(BrepView(back, source="step-file")),
            judge.suite.resolution,
        )
        self.assertIs(found.verdict, Verdict.PASS, found.misses[:2])

    def test_a_split_that_reads_back_loose_is_written_unsplit(self) -> None:
        """Generated part 1130: its bore's face halved 6e-5 mm from where a small hole met it, the reader widened the vertex at that short edge's end to 1.9e-4 mm, over its neighbour. Such a split is written unsplit, and the part reads back as tightly held as it was made, meeting itself nowhere. (The bore is now split clear of the hole, in thirds: the halves are made here as they were.)"""
        from forge_occ.aftercheck import too_loose
        from forge_occ.occt import faces, loosest_tolerance, widened_to_curves
        from forge_occ.view import BrepView

        shape = _part(1130)
        halves = export._closed_split(shape, 1)
        widened_to_curves(halves)
        split = read_step(export._step_bytes([StepPart("part", halves)], (), None, "MM")).parts["part"]  # fmt: skip
        self.assertTrue(too_loose(loosest_tolerance(split)))
        with mock.patch.object(export, "exchanged", return_value=halves):
            data = write_step([StepPart("part", shape)])
        back = read_step(data).parts["part"]
        self.assertEqual(len(faces(back)), len(faces(shape)))  # written unsplit
        self.assertFalse(too_loose(loosest_tolerance(back)))
        self.assertEqual(BrepView(back).topology().self_intersections, 0)
        check_step(data, [StepPart("part", shape)])

    def test_a_closed_face_is_split_clear_of_the_parts_corners(self) -> None:
        """Generated part 7250: halved, a tube's outer face was cut 3.2e-5 mm from where a hole met it, and read back, the corner at that short edge's end was held 6.2e-5 mm loosely, over its neighbour: the part read back met itself there. Each closed face is split where the cut passes no corner of the part nearer than 1e-3 mm (here in thirds; part 1130's bore too), and the part read back meets itself nowhere."""
        from forge_occ.occt import faces
        from forge_occ.view import BrepView

        for seed in (7250, 1130):
            with self.subTest(seed):
                shape = _part(seed)
                split = export.exchanged(shape)
                self.assertGreater(
                    len(faces(split)), len(faces(shape))
                )  # split, not written whole
                self.assertGreaterEqual(
                    _shortest_edge(split), min(1e-3, _shortest_edge(shape))
                )
                data = write_step([StepPart("part", shape)])
                back = read_step(data).parts["part"]
                self.assertEqual(len(faces(back)), len(faces(split)))
                self.assertEqual(BrepView(back).topology().self_intersections, 0)
                check_step(data, [StepPart("part", shape)])

    def test_a_split_that_reads_back_invalid_gives_way(self) -> None:
        """Generated part 3500: halved, a plane's and a cylinder's wires read back turned against each other (unorientable), though the halves were a valid solid and the file held tightly everywhere. The next split that reads back a valid solid is written instead, else the part unsplit: it reads back valid and as the part written."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from forge_eval.generator import render
        from forge_occ.aftercheck import too_loose
        from forge_occ.occt import is_valid, loosest_tolerance
        from v2_exit4 import _built, _spec
        from v2_regressions import REGRESSIONS

        _, built = _built(_spec(render(REGRESSIONS[3500][1]).items))
        shape = built.result.shape
        halves = [StepPart("part", export._closed_split(shape, 1))]
        self.assertIsNot(halves[0].shape, shape)
        self.assertTrue(is_valid(halves[0].shape))
        split = read_step(export._step_bytes(halves, (), None, "MM")).parts["part"]
        self.assertFalse(too_loose(loosest_tolerance(split)))
        self.assertFalse(is_valid(split))
        chosen = [StepPart("part", export.exchanged(shape))]
        self.assertIsNot(chosen[0].shape, halves[0].shape)
        back = read_step(export._step_bytes(chosen, (), None, "MM")).parts["part"]
        self.assertTrue(is_valid(back))
        data = write_step([StepPart("part", shape)])
        self.assertTrue(is_valid(read_step(data).parts["part"]))
        check_step(data, [StepPart("part", shape)])

    def test_a_spindle_torus_reads_back_as_the_surface_it_is(self) -> None:
        """Generated part 1340: a block's vertical edges rounded 1.351, then its top edges 0.879: each corner is a torus whose tube (0.879) is wider than its ring (0.472), and STEP brings it back a surface of revolution. The same surface: the part reads back as written."""
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS

        def rounded(shape: Any, radius: float, vertical: bool) -> Any:
            fillet = BRepFilletAPI_MakeFillet(shape)
            found = TopExp_Explorer(shape, TopAbs_EDGE)
            while found.More():
                edge = TopoDS.Edge(found.Current())
                curve = BRepAdaptor_Curve(edge)
                a = curve.Value(curve.FirstParameter())
                b = curve.Value(curve.LastParameter())
                upright = abs(a.X() - b.X()) < 1e-9 and abs(a.Y() - b.Y()) < 1e-9
                top = abs(a.Z() - 5.0) < 1e-9 and abs(b.Z() - 5.0) < 1e-9
                wanted = upright if vertical else top
                if wanted:
                    fillet.Add(radius, edge)
                found.Next()
            return fillet.Shape()

        box = BRepPrimAPI_MakeBox(10.0, 8.0, 5.0).Shape()
        shape = rounded(rounded(box, 1.351, True), 0.879, False)
        self.assertEqual(export._face_kinds(shape)["torus"], 4)
        data = write_step([StepPart("block", shape)])
        found, _ = check_step(data, [StepPart("block", shape)])
        self.assertEqual(export._face_kinds(found.parts["block"])["torus"], 0)

    def test_an_inch_file_is_read_in_millimetres_and_refused_as_ours(self) -> None:
        shape = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
        data = write_step([StepPart("box", shape)], unit="INCH")
        self.assertIn(b"INCH", data)
        back = read_step(data).parts["box"]
        self.assertAlmostEqual(properties(back).volume, 6000.0, delta=1e-6)
        with self.assertRaises(OperationError):
            check_step(data, [StepPart("box", shape)])

    def test_writing_a_part_leaves_it_as_it_was(self) -> None:
        """Generated part 6950: its bores' faces split for the file, the edges they share with faces left whole were made to agree with the halves in the part itself, 24 of its tolerances changed. The halves are made of a copy: the part written is the part as it was."""
        from forge_occ.occt import edges, faces, vertices
        from OCP.BRep import BRep_Tool

        shape = _part_6950()

        def stated() -> list[float]:
            return [BRep_Tool.Tolerance_s(s) for s in (*faces(shape), *edges(shape), *vertices(shape))]  # fmt: skip

        before = stated()
        data = write_step([StepPart("part", shape)])
        self.assertIsNot(export.exchanged(shape), shape)
        self.assertEqual(stated(), before)
        check_step(data, [StepPart("part", shape)])

    def test_a_part_read_back_is_held_as_loosely_as_its_curves_stray(self) -> None:
        """Generated part 6950: read back, a small bore's curve on its face, where it meets a big hole, strayed 3.9e-5 mm from the edge between the points OpenCascade compares, the edge stating 1e-7 mm, and a spec point 1.3e-6 mm from it fell outside the face. Measured along each whole edge, the part read back is held as loosely as it is, and judged against its spec at its own tolerances it passes face accounting, as the part written does."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from forge_checks.accounting import account_faces
        from forge_checks.classes import Verdict
        from forge_checks.judge import Judge
        from forge_checks.view import ViewProxy
        from forge_eval.generator import render
        from forge_occ.occt import faces
        from OCP.BRep import BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepLib import BRepLib_ValidateEdge
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        from v2_exit4 import _spec
        from v2_regressions import REGRESSIONS

        back = read_step(write_step([StepPart("part", _part_6950())])).parts["part"]
        loosest = 0.0
        for face in faces(back):
            explorer = TopExp_Explorer(face, TopAbs_EDGE)
            while explorer.More():
                edge = TopoDS.Edge(explorer.Current())
                explorer.Next()
                if BRep_Tool.Degenerated_s(edge):
                    continue
                # The greatest distance between the edge's curve and its curve on the face, found along all of it.
                measure = BRepLib_ValidateEdge(
                    BRepAdaptor_Curve(edge),
                    BRepAdaptor_Curve(edge, face).CurveOnSurface(),
                    BRep_Tool.SameParameter_s(edge),
                )
                measure.SetExactMethod(True)
                measure.Process()
                self.assertTrue(measure.IsDone())
                stray = measure.GetMaxDistance()
                loosest = max(loosest, stray)
                self.assertLessEqual(stray, BRep_Tool.Tolerance_s(edge))
        self.assertGreater(loosest, 1e-5)  # the stray curve is there, and measured
        judge = Judge.of(_spec(render(REGRESSIONS[6950][1]).items))
        found = account_faces(
            judge.part,
            ViewProxy(BrepView(back, source="step-file")),
            judge.suite.resolution,
        )
        self.assertIs(found.verdict, Verdict.PASS, found.misses[:2])

    def test_a_part_read_back_otherwise_is_refused(self) -> None:
        data = write_step(
            [StepPart("box", BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape())]
        )
        with self.assertRaises(OperationError):
            check_step(
                data, [StepPart("box", BRepPrimAPI_MakeBox(10.0, 20.0, 31.0).Shape())]
            )
        with self.assertRaises(OperationError):
            check_step(
                data, [StepPart("other", BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape())]
            )

    def test_an_assembly_its_names_placements_and_mates(self) -> None:
        document = v2(CLEVIS_PIN.read_text())
        assembly = build_assembly(document)
        self.assertTrue(assembly.holds)
        data = write_step(
            assembly.step_parts(), assembly.step_instances(), assembly=assembly.name
        )
        found, report = check_step(
            data,
            assembly.step_parts(),
            assembly.step_instances(),
            assembly=assembly.name,
        )
        self.assertEqual(found.assembly, assembly.name)
        self.assertEqual([i.name for i in found.instances], ["clevis_1", "pin_1"])
        self.assertEqual(report.instances, 2)
        mates = check_mates_read_back(document, assembly, found)
        self.assertTrue(all(m.holds for m in mates), mates)

    def test_a_moved_instance_read_back_is_caught(self) -> None:
        document = v2(CLEVIS_PIN.read_text())
        assembly = build_assembly(document)
        data = write_step(
            assembly.step_parts(), assembly.step_instances(), assembly=assembly.name
        )
        moved = [*assembly.step_instances()]
        moved[1] = export.StepInstance(moved[1].name, moved[1].part,
                                       moved[1].motion.then(Motion.of(np.eye(3), (0.0, 0.001, 0.0))))  # fmt: skip
        with self.assertRaises(OperationError):
            check_step(data, assembly.step_parts(), moved, assembly=assembly.name)


if __name__ == "__main__":
    unittest.main()
