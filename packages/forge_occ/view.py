"""``BrepView``: the exact view of a built part, answering the whole ``GeometryView`` protocol (docs/V2-stage3.md, section 11).

| Question | How |
|---|---|
| ``classify`` | ``BRepClass3d_SolidClassifier`` per solid, ON within 1e-6 mm |
| ``distance`` | ``BRepExtrema_DistShapeShape`` to the compound of the faces (to the solid itself, a point inside is at 0) |
| ``crossings`` | ``IntCurvesFace_ShapeIntersector``; entering from the face's outward normal; a ray through an edge or a corner, or along a face, grazed |
| ``volume`` | OpenCascade's integral at 1e-12, as an interval of ±1e-6 relative |
| ``bounds`` | ``BRepBndLib.AddOptimal``, without tolerances |
| ``coverage`` | each face gridded in its own parameters by a bound on its surface's derivatives, the grid's points on the face kept, its edges sampled by length; within a box, only the grid's cells and the edges' samples that may stand for a point in it (:func:`_near_box`) |
| ``topology`` | exact counts on the B-rep |
| ``faces``, ``edges`` | surface and curve types and parameters, areas, lengths, boxes |

A STEP file read back is the same view with source ``"step-file"``.

**The coverage's guarantee.** Each face's grid is fine enough that
``Lu·Δu ≤ 0.6r`` and ``Lv·Δv ≤ 0.6r``, ``Lu`` and ``Lv`` bounds on
``|∂S/∂u|`` and ``|∂S/∂v|`` over the face's parameters; its edges are
sampled at most 0.6r apart along their length, so every point of an edge is
within 0.3r of a sample. A point of the face lies in some cell, within half
the cell each way of the cell's nearest corner, so within 0.6r of it (along
u, then along v). If that corner is on the face (kept), that's all; if not,
the face's boundary crosses the cell between the point and the corner, so
the point is within 0.6r of a point of an edge (and its tolerance), and
within 0.9r of an edge's sample. Every point of the face is within ``r`` of
a sample, with 0.1r to spare for the edges' tolerances. Which grid points
are on the face is :mod:`forge_occ.uvclass`'s answer, OpenCascade's own
classifier's where the boundary isn't straight or circular.

The speed bounds are :mod:`forge_occ.speeds`'s: proved for every kind of
surface but an offset of a B-spline, whose speed is measured (and doubled).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from functools import cached_property
from typing import Any

import numpy as np
from forge_checks.mesh import MeshView
from forge_checks.view import (
    Box,
    Capability,
    Coverage,
    Crossings,
    EdgeFacts,
    FaceFacts,
    Side,
    Topology,
    held,
)
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from forge_units import Interval
from numpy.typing import NDArray
from OCP.Bnd import Bnd_Box
from OCP.BOPAlgo import BOPAlgo_CheckerSI
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_MakeVertex
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d, BRepClass3d_SolidClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape, BRepExtrema_IsInFace
from OCP.BRepGProp import BRepGProp
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepTools import BRepTools
from OCP.collections import (
    IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedDataMapOfShapeListOfShape,
)
from OCP.collections import (
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape,
)
from OCP.collections import List_TopoDS_Shape as TopTools_ListOfShape
from OCP.GCPnts import GCPnts_AbscissaPoint, GCPnts_UniformAbscissa
from OCP.GeomAbs import (
    GeomAbs_BezierCurve,
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Line,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_SurfaceOfExtrusion,
    GeomAbs_Torus,
)
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.IntCurveSurface import IntCurveSurface_In, IntCurveSurface_Out
from OCP.IntTools import IntTools_FClass2d
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_IN,
    TopAbs_ON,
    TopAbs_OUT,
    TopAbs_REVERSED,
    TopAbs_VERTEX,
    TopAbs_WIRE,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS

from .aftercheck import open_edges
from .make import compound
from .measure import VOLUME_RELATIVE, volume_interval
from .occt import (
    INTEGRATION,
    boundary,
    box_limits,
    edges,
    faces,
    plane_of,
    shells,
    solids,
    surface_area,
    vertices,
)
from .speeds import Pieces, nodes, speeds
from .uvclass import FINE, Boundary, in_face, on_grid, read
from .uvclass import ON as ON_FACE

__all__ = [
    "ON",
    "SOURCES",
    "VOLUME_RELATIVE",
    "BrepView",
    "edge_facts",
    "face_facts",
    "may_reach",
]

Array = NDArray[np.float64]

#: A point this close to the surface is on it (mm).
ON = 1e-6
#: The self-interference checker's level: vertices, edges and faces against each other, all but face against face.
_CHECKED_LEVEL = 4
_ANALYTIC = (
    GeomAbs_Plane,
    GeomAbs_Cylinder,
    GeomAbs_Cone,
    GeomAbs_Sphere,
    GeomAbs_SurfaceOfExtrusion,
    GeomAbs_Torus,
)
#: Classifying at least this many points at once on a part with a B-spline face, the view meshes the part to read the far points' sides.
_ACCELERATE = 256
#: The ways a point's rays are cast (:meth:`BrepView._by_rays`): unit vectors along no axis, face diagonal or
#: cube diagonal, nor in a plane of two axes, so that a ray seldom runs along a face of a part or through
#: one of its edges.
_RAYS = tuple(
    np.asarray(v, dtype=np.float64) / fv.norm(v)
    for v in (
        (0.2672, 0.5345, 0.8018),
        (-0.6213, 0.1706, 0.7648),
        (0.4472, -0.8177, 0.3627),
    )
)
#: Where a B-rep view may come from.
SOURCES = frozenset({"brep", "step-file"})
#: The surface's derivatives' cross product this small (in mm², or relative to their lengths' product where that
#: is more than one) is at or by a singular point (a sphere's pole, a cone's apex): its normal there is found as
#: :func:`_at_singular` finds it. A face's bounds may reach OpenCascade's confusion distance (1e-7 mm) past an apex,
#: onto the cone's other nappe, where the derivatives give the normal facing the other way (generated part 244).
_SINGULAR = 1e-5
#: A coverage's grid cells and edge samples, as a share of its radius (the module's docstring).
_CELL = 0.6


def _xyz(p: Any) -> Array:
    return np.array([p.X(), p.Y(), p.Z()], dtype=np.float64)


def _box_of(shape: Any) -> Box:
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    x0, y0, z0, x1, y1, z1 = box_limits(box)
    return Box((x0, y0, z0), (x1, y1, z1))


def _distinct(shapes: Any) -> list[Any]:
    found: list[Any] = []
    for s in shapes:
        if not any(s.IsSame(f) for f in found):
            found.append(s)
    return found


class BrepView:
    """The exact view of a solid, or a compound of solids, as OpenCascade holds it."""

    capabilities = frozenset(Capability)

    def __init__(self, shape: Any, *, source: str = "brep") -> None:
        if source not in SOURCES:
            raise ValueError(
                f"a B-rep view comes from one of {sorted(SOURCES)}, not {source!r}"
            )
        if shape is None or shape.IsNull() or not solids(shape):
            raise ValueError("a B-rep view needs a solid")
        self.shape = shape
        self.source = source
        self._faces = [TopoDS.Face(f) for f in faces(shape)]
        self._accelerator: tuple[MeshView, float] | None = None
        #: Each whole coverage made, by its radius: the checks' probe and face accounting cover alike.
        self._covered: dict[tuple[float, Box | None], Coverage] = {}
        self._grids: dict[tuple[int, float], _FaceGrid] = {}
        #: OpenCascade's classifier of each face asked so far, by its index (:meth:`near`).
        self._face_classifiers: dict[int, Any] = {}
        #: Each face's boundary read again with its bands narrowed, by its index, where a foot was left in one.
        self._fine_boundaries: dict[int, Boundary | None] = {}

    @cached_property
    def _corners(self) -> TopTools_IndexedDataMapOfShapeListOfShape:
        return _corner_reach(self.shape)

    # --- classify, distance, crossings ----------------------------------------------
    @cached_property
    def _classifiers(self) -> list[Any]:
        return [BRepClass3d_SolidClassifier(s) for s in solids(self.shape)]

    @cached_property
    def _by_nearest(self) -> bool:
        """Whether a point's side is read from its nearest point first: on a part with a face that isn't
        analytic, where OpenCascade's classifier (casting rays at B-splines) can take 70 ms a point."""
        return any(
            BRepAdaptor_Surface(f, False).GetType() not in _ANALYTIC
            for f in self._faces
        )

    def accelerate(self, mesh: MeshView, error: float) -> None:
        """Read the sides of points far from the surface from ``mesh``: a sound mesh of this part, measured within ``error`` of it."""
        if not mesh.topology().sound:
            raise ValueError("only a sound mesh can stand for the part's sides")
        self._accelerator = (mesh, float(error))

    @cached_property
    def _mesh_for_sides(self) -> tuple[MeshView, float] | None:
        if self._accelerator is not None:
            return self._accelerator
        if not self._by_nearest:
            return None
        from .export import _triangulate, deviation

        size = float(max(self.bounds().size))
        deflection = min(max(size * 2e-4, 1e-3), 2e-2)
        mesh, owner, uv = _triangulate(self.shape, deflection, 0.1)
        view = MeshView(mesh, source="mesh-file", deflection=0.0)
        if not view.topology().sound:
            return None
        found, _ = deviation(self.shape, mesh.vertices[mesh.faces], owner, uv, enough=deflection, view=self,
                             mesh_view=view)  # fmt: skip
        return view, found + 1e-6

    def classify(self, points: Array) -> NDArray[np.int8]:
        """Each point's side.

        On a part whose faces are all analytic, by three rays cast from the
        point (:meth:`_by_rays`), and where they don't agree or a ray meets a
        face at its boundary or starts on one, by OpenCascade's classifier:
        its one ray at a time was seen to put a point most of a millimetre
        from every face inside (generated part 76, next to raised letters),
        where every ray Forge casts finds it outside.
        On a part with a B-spline face, where OpenCascade's classifier is both
        slow (70 ms a point on a coil) and, a few millimetres' hundredths off a
        fitted face, sometimes wrong (seen on mapped bends, against two other
        ways of telling): a point more than twice its measured deviation from
        a sound mesh of the part is on the mesh's side; a point nearer, on the
        side of the outward normal at its nearest point of the part, where
        that lies inside one face (the point is off the surface along the
        normal there); the classifier decides the rest (a nearest point on an
        edge or a corner, or several).
        """
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        out = np.full(len(points), Side.UNKNOWN, dtype=np.int8)
        todo = np.arange(len(points))
        accelerator = (
            self._mesh_for_sides
            if self._by_nearest and len(points) >= _ACCELERATE
            else self._accelerator
        )
        if accelerator is not None and len(points):
            mesh, error = accelerator
            far = mesh.distance(points) > 2.0 * error
            sides = mesh.classify(points[far])
            decided = np.flatnonzero(far)[(sides == Side.IN) | (sides == Side.OUT)]
            out[decided] = sides[(sides == Side.IN) | (sides == Side.OUT)]
            todo = np.setdiff1d(todo, decided)
        if not self._by_nearest and len(todo):
            by_rays = self._by_rays(points[todo])
            told = by_rays != Side.UNKNOWN
            out[todo[told]] = by_rays[told]
            todo = todo[~told]
        with boundary("classifying points"):
            for k in todo:
                p = points[k]
                where = gp_Pnt(float(p[0]), float(p[1]), float(p[2]))
                found = self._nearest_side(where) if self._by_nearest else None
                out[k] = found if found is not None else self._classified(where)
        return out

    def _by_rays(self, points: Array) -> NDArray[np.int8]:
        """Each point's side from the rays of :data:`_RAYS` cast from it: inside where the first face each ray crosses is left, outside where it is entered or none is crossed; UNKNOWN unless every ray tells, and they agree.

        A ray tells nothing where it meets a face at its boundary or runs
        along one (``Crossings.grazed``), or where its first crossing is
        within :data:`ON` of the point either way (the point is on the
        surface, for the classifier to say). Each ray starts that far behind
        the point, so a face through the point itself, which a crossing
        ahead of it doesn't see, is crossed.
        """
        n = len(points)
        votes = np.zeros((len(_RAYS), n), dtype=np.int8)
        for r, way in enumerate(_RAYS):
            hits = self.crossings(points - ON * way, np.tile(way, (n, 1)))
            vote = np.full(n, int(Side.OUT), dtype=np.int8)
            rays, first = np.unique(hits.ray, return_index=True)
            vote[rays] = np.where(hits.entering[first], int(Side.OUT), int(Side.IN))
            vote[rays[hits.t[first] <= 2 * ON]] = 0
            vote[hits.grazed] = 0
            votes[r] = vote
        agreed = np.all(votes == votes[0], axis=0) & (votes[0] != 0)
        return np.where(agreed, votes[0], int(Side.UNKNOWN)).astype(np.int8)

    def _classified(self, where: Any) -> int:
        found = Side.OUT
        for classifier in self._classifiers:
            classifier.Perform(where, ON)
            state = classifier.State()
            if state == TopAbs_IN:
                return Side.IN
            if state == TopAbs_ON:
                found = Side.ON
            elif state != TopAbs_OUT and found == Side.OUT:
                found = Side.UNKNOWN
        return found

    def _nearest_side(self, where: Any) -> int | None:
        meter = self._meter
        meter.LoadS1(BRepBuilderAPI_MakeVertex(where).Vertex())
        meter.Perform()
        if not meter.IsDone():
            return None
        gap = float(meter.Value())
        if gap <= ON:
            return Side.ON
        p = _xyz(where)
        sides = set()
        for i in range(1, meter.NbSolution() + 1):
            if meter.SupportTypeShape2(i) != BRepExtrema_IsInFace:
                return None
            face = TopoDS.Face(meter.SupportOnShape2(i))
            u, v = meter.ParOnFaceS2(i)
            along = float(
                fv.matmul(
                    p - _xyz(meter.PointOnShape2(i)),
                    _outward(face, BRepAdaptor_Surface(face, False), u, v),
                )
            )
            if abs(along) < 0.5 * gap:
                return None
            sides.add(Side.OUT if along > 0.0 else Side.IN)
        return sides.pop() if len(sides) == 1 else None

    @cached_property
    def _meter(self) -> Any:
        meter = BRepExtrema_DistShapeShape()
        meter.LoadS2(compound(self._faces))
        return meter

    def distance(self, points: Array) -> Array:
        """Each point's distance to the surface: OpenCascade's (``BRepExtrema_DistShapeShape``), or nearer.

        Nearer where the point's foot on a face whose box is within that
        distance is surely on the face (:meth:`_sure_feet`): OpenCascade's
        own classifier counts a point within its tolerance of a curved edge
        as on the edge, and measures to the edge (a point 4.9e-6 mm inside a
        letter's top, by a Bézier edge: 4.9e-6, not 0). A sure foot is a
        point of the surface, so the distance is never less than the true
        one.
        """
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        out = self._measured(points)
        with boundary("measuring distances"):
            for k in range(len(self._faces)):
                lo, hi = self._face_boxes[k]
                reach = out[:, None]
                ask = np.flatnonzero(
                    np.all((points >= lo - reach) & (points <= hi + reach), axis=1)
                )
                if len(ask):
                    nearer = self._sure_feet(k, points[ask], out[ask])
                    out[ask] = np.minimum(out[ask], nearer)
        return out

    def _measured(self, points: Array) -> Array:
        """OpenCascade's distance from each point to the shape."""
        out = np.empty(len(points))
        meter = self._meter
        with boundary("measuring distances"):
            for k, p in enumerate(points):
                meter.LoadS1(
                    BRepBuilderAPI_MakeVertex(
                        gp_Pnt(float(p[0]), float(p[1]), float(p[2]))
                    ).Vertex()
                )
                meter.Perform()
                if not meter.IsDone():
                    raise RuntimeError("OpenCascade could not measure a distance")
                out[k] = meter.Value()
        return out

    def near(self, points: Array, tolerances: Array) -> NDArray[np.bool_]:
        """Whether each point is within its tolerance of the surface: exactly, with a certificate first.

        A point is near if some face has a point within its tolerance of it.
        For each face whose box (grown by the tolerance) holds the point, the
        point's foot on the face's surface is worked out in closed form
        (planes, cylinders, cones, spheres, tori); if the face's boundary
        puts the foot's parameters on the face for sure (in it, or within
        :data:`~forge_occ.uvclass.ON` of a straight or circular edge, read by
        :mod:`forge_occ.uvclass`: never by a classifier's tolerance, which
        would count a foot past a loose edge) and the foot is within the
        tolerance, the point is near: the foot is a point of the part's
        surface (:meth:`_sure_feet`). A point in no face's box grown by its
        tolerance is far (every point of a face is in its box). Any other
        point is asked OpenCascade's distance: no sure foot is within its
        tolerance, so :meth:`distance` is OpenCascade's for it. So the answer
        is :meth:`distance`'s, and a part as built (each point of its spec's
        surface at a foot on some face) is answered without one OpenCascade
        distance per point: 2.9 ms a point by a thread's helical edges
        (generated part 171: 50,489 of them, 62% of its judging, before its
        unsure feet were settled so).
        """
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        t = np.broadcast_to(np.asarray(tolerances, dtype=np.float64), (len(points),))
        out = np.zeros(len(points), dtype=bool)
        if not len(points):
            return out
        # A point in no face's box grown by its tolerance has no face within it: far, exactly.
        seen = np.zeros(len(points), dtype=bool)
        with boundary("certifying points near the surface"):
            for k in range(len(self._faces)):
                todo = np.flatnonzero(~out)
                if not len(todo):
                    break
                lo, hi = self._face_boxes[k]
                reach = t[todo, None]
                inside = np.all(
                    (points[todo] >= lo - reach) & (points[todo] <= hi + reach), axis=1
                )
                ask = todo[inside]
                seen[ask] = True
                if len(ask):
                    out[ask] = self._sure_feet(k, points[ask], t[ask]) <= t[ask]
        rest = np.flatnonzero(~out & seen)
        if len(rest):
            out[rest] = self._measured(points[rest]) <= t[rest]
        return out

    def _sure_feet(self, k: int, points: Array, within: Array) -> Array:
        """Each point's distance to its foot on the k-th face's surface, where the foot is within ``within`` and surely on the face; inf elsewhere.

        The foot is worked out in closed form (planes, cylinders, cones,
        spheres, tori; any other surface has none here). It is surely on the
        face if the face's boundary puts its parameters there (in it, or
        within :data:`~forge_occ.uvclass.ON` of a straight or circular edge,
        read by :mod:`forge_occ.uvclass`: never by a classifier's tolerance,
        which would count a foot past a loose edge); where the boundary as
        read leaves it unsure (within the band round a curve it follows by a
        polygon, as a boolean's intersection curves and a letter's Bezier
        edges are), as the boundary read again with its bands narrowed
        (:data:`~forge_occ.uvclass.FINE`) puts it; where that still leaves
        it unsure, or the boundary can't be read, if OpenCascade's
        classifier says IN (:func:`~forge_occ.uvclass.in_face`; its ON may
        lie past the face, and it calls ON a point 7e-6 mm inside a letter's
        top by a Bezier edge: generated part 1057).
        """
        out = np.full(len(points), np.inf)
        found = _feet(self._surfaces[k], points)
        if found is None:
            return out
        feet, u, v = found
        d = fv.norm(points - feet, axis=1)
        close = np.flatnonzero(d <= within)
        if not len(close):
            return out
        edges = self._boundaries[k]
        on: NDArray[np.bool_] = np.zeros(len(close), dtype=bool)
        unsure: NDArray[np.bool_] = np.ones(len(close), dtype=bool)
        if edges is not None:
            on, unsure = edges.points(u[close], v[close])
            if unsure.any():
                fine = self._fine_boundary(k)
                if fine is not None:
                    settled, still = fine.points(u[close][unsure], v[close][unsure])
                    on[unsure] = settled
                    unsure[unsure] = still
        if unsure.any():
            on[unsure] = in_face(
                self._classifier(k), u[close][unsure], v[close][unsure]
            )
        out[close[on]] = d[close[on]]
        return out

    def _fine_boundary(self, k: int) -> Boundary | None:
        """The k-th face's boundary read with its bands narrowed (:data:`~forge_occ.uvclass.FINE`), made once: only where a foot was left in a band."""
        if k not in self._fine_boundaries:
            self._fine_boundaries[k] = read(self._faces[k], FINE)
        return self._fine_boundaries[k]

    def _classifier(self, k: int) -> Any:
        """OpenCascade's classifier of the k-th face, made once."""
        if k not in self._face_classifiers:
            self._face_classifiers[k] = IntTools_FClass2d(self._faces[k], ON_FACE)
        return self._face_classifiers[k]

    @cached_property
    def _face_boxes(self) -> list[tuple[Array, Array]]:
        found = []
        for face in self._faces:
            box = Bnd_Box()
            BRepBndLib.AddOptimal_s(face, box, False, False)
            x0, y0, z0, x1, y1, z1 = box_limits(box)
            found.append((np.array([x0, y0, z0]), np.array([x1, y1, z1])))
        return found

    @cached_property
    def _surfaces(self) -> list[Any]:
        return [BRepAdaptor_Surface(face, True) for face in self._faces]

    @cached_property
    def _boundaries(self) -> list[Boundary | None]:
        return [read(face) for face in self._faces]

    @cached_property
    def _intersector(self) -> Any:
        hits = IntCurvesFace_ShapeIntersector()
        hits.Load(self.shape, 1e-9)
        return hits

    def first_hits(self, origins: Array, directions: Array) -> tuple[Array, Array]:
        """How far ahead of each ray (unit ``directions``) it first meets the part's surface, and the outward normal of the face there; inf and NaN where it meets none."""
        far = np.full(len(origins), math.inf)
        normals = np.full((len(origins), 3), math.nan)
        hits = self._intersector
        with boundary("casting rays"):
            for k, (o, d) in enumerate(zip(origins, directions, strict=True)):
                hits.Perform(
                    gp_Lin(gp_Pnt(*map(float, o)), gp_Dir(*map(float, d))),
                    0.0,
                    math.inf,
                )
                first = 0
                for i in range(1, hits.NbPnt() + 1):
                    t = float(hits.WParameter(i))
                    if 0.0 < t < far[k]:
                        far[k], first = t, i
                if first:
                    face = hits.Face(first)
                    normals[k] = _outward(
                        face,
                        BRepAdaptor_Surface(face, False),
                        hits.UParameter(first),
                        hits.VParameter(first),
                    )
        return far, normals

    def crossings(self, origins: Array, directions: Array) -> Crossings:
        """Every crossing ahead of each ray, entering where the ray runs against the face's outward normal.

        A ray is grazed where it meets a face on the face's boundary (an edge
        or a corner), runs along a face (no clear side), or OpenCascade's own
        transition there disagrees with the side the normal gives.
        """
        rays: list[int] = []
        ts: list[float] = []
        entering: list[bool] = []
        grazed = np.zeros(len(origins), dtype=bool)
        hits = self._intersector
        with boundary("casting rays"):
            for k, (o, d) in enumerate(zip(origins, directions, strict=True)):
                way = np.asarray(d, dtype=np.float64)
                hits.Perform(
                    gp_Lin(gp_Pnt(*map(float, o)), gp_Dir(*map(float, way))),
                    0.0,
                    math.inf,
                )
                found: list[tuple[float, bool]] = []
                for i in range(1, hits.NbPnt() + 1):
                    t = float(hits.WParameter(i))
                    if t <= 0.0:
                        continue
                    face = hits.Face(i)
                    normal = _outward(
                        face,
                        BRepAdaptor_Surface(face, False),
                        hits.UParameter(i),
                        hits.VParameter(i),
                    )
                    along = float(fv.matmul(way, normal))
                    transition = hits.Transition(i)
                    told = transition in (IntCurveSurface_In, IntCurveSurface_Out)
                    if hits.State(i) == TopAbs_ON or abs(along) <= 1e-9 or not told \
                            or (transition == IntCurveSurface_In) != (along < 0.0):  # fmt: skip
                        grazed[k] = True
                    found.append((t, along < 0.0))
                found.sort(key=lambda hit: hit[0])
                for t, inward in found:
                    rays.append(k)
                    ts.append(t)
                    entering.append(inward)
        return Crossings(
            np.asarray(rays, dtype=np.int64), np.asarray(ts, dtype=np.float64),
            np.asarray(entering, dtype=bool), grazed,
        )  # fmt: skip

    # --- volume, bounds -----------------------------------------------------------------
    def volume(self) -> Interval:
        return volume_interval(self.shape)

    def bounds(self) -> Box:
        return _box_of(self.shape)

    # --- coverage -----------------------------------------------------------------------
    def coverage(self, radius: float, within: Box | None = None) -> Coverage:
        """Points on every face (only near ``within``, of the faces meeting it): every point of each face (in the box) within ``radius`` of one.

        A coverage is made once for each radius and box, and kept, read-only:
        the checks and face accounting cover the same finer boxes.
        """
        key = (float(radius), within)
        if key not in self._covered:
            self._covered[key] = held(self._cover(key[0], within))
        return self._covered[key]

    def _cover(self, r: float, within: Box | None) -> Coverage:
        points: list[Array] = []
        normals: list[Array] = []
        patch: list[NDArray[np.int64]] = []
        tolerance: list[Array] = []
        with boundary("covering the surface", radius=r):
            for index, face in enumerate(self._faces):
                if within is not None and not _box_meets(
                    self._face_boxes[index], within
                ):
                    continue
                grid = None if within is None else self._grid(index, r)
                p, n, tol = _cover_face(face, r, self._corners, within, grid)
                points.append(p)
                normals.append(n)
                patch.append(np.full(len(p), index, dtype=np.int64))
                tolerance.append(tol)
        if not points:
            return Coverage(
                np.zeros((0, 3)),
                np.zeros((0, 3)),
                np.zeros(0, dtype=np.int64),
                np.zeros(0),
                r,
            )
        return Coverage(np.concatenate(points), np.concatenate(normals), np.concatenate(patch),
                        np.concatenate(tolerance), r)  # fmt: skip

    def _grid(self, index: int, r: float) -> _FaceGrid:
        """What covering the face at ``r`` needs, whatever the box (made once: a part's finer boxes cover its faces many times)."""
        key = (index, r)
        if key not in self._grids:
            self._grids[key] = _face_grid(self._faces[index], r, self._corners)
        return self._grids[key]

    # --- topology -----------------------------------------------------------------------
    def topology(self) -> Topology:
        with boundary("counting the topology"):
            return self._topology

    @cached_property
    def _topology(self) -> Topology:
        loose = open_edges(self.shape)
        bad_edges = _bad_edges(self.shape)
        bad_vertices = _bad_vertices(self.shape)
        bad_faces = sum(
            1
            for f in self._faces
            if surface_area(f) <= 0.0 or not BRepCheck_Analyzer(f, True).IsValid()
        )
        crossing = _self_intersections(self.shape, self._faces)
        topology = Topology(
            shells=len(shells(self.shape)), solids=None, voids=None, open_edges=loose, bad_edges=bad_edges,
            bad_vertices=bad_vertices, bad_triangles=bad_faces, self_intersections=crossing,
            misnested=None, genus=(),
        )  # fmt: skip
        if loose or bad_edges or bad_vertices or bad_faces or crossing:
            return topology
        return _nesting(self.shape, topology)

    # --- faces, edges -------------------------------------------------------------------
    def faces(self) -> tuple[FaceFacts, ...]:
        return tuple(face_facts(f) for f in self._faces)

    def edges(self) -> tuple[EdgeFacts, ...]:
        found = (TopoDS.Edge(e) for e in edges(self.shape))
        return tuple(edge_facts(e) for e in found if not BRep_Tool.Degenerated_s(e))


# --- feet on analytic surfaces ------------------------------------------------------


def _frame_of(position: Any) -> tuple[Array, Array, Array, Array]:
    """A surface's frame (gp_Ax3): its origin and its x, y and z directions."""
    o = position.Location()
    x, y, z = position.XDirection(), position.YDirection(), position.Direction()
    return (np.array([o.X(), o.Y(), o.Z()]), np.array([x.X(), x.Y(), x.Z()]),
            np.array([y.X(), y.Y(), y.Z()]), np.array([z.X(), z.Y(), z.Z()]))  # fmt: skip


def _feet(surface: Any, points: Array) -> tuple[Array, Array, Array] | None:
    """Each point's nearest point on an analytic surface (untrimmed), with its parameters; None for any other surface.

    In each surface's own frame (OpenCascade's parametrisations):

    - plane: u, v along its x and y;
    - cylinder of radius R: (R cos u, R sin u, v);
    - cone, reference radius R, half-angle a: ((R + v sin a) cos u, (R + v sin a) sin u, v cos a);
    - sphere of radius R: (R cos v cos u, R cos v sin u, R sin v);
    - torus, radii R and r: ((R + r cos v) cos u, (R + r cos v) sin u, r sin v).

    A point on the axis of a surface of revolution (or a sphere's centre)
    has no one nearest point: its foot is taken at u = 0, which is a point of
    the surface, so a certificate made from it is still sound.
    """
    kind = surface.GetType()
    if kind == GeomAbs_Plane:
        o, x, y, z = _frame_of(surface.Plane().Position())
        d = points - o
        u, v = fv.matmul(d, x), fv.matmul(d, y)
        return o + u[:, None] * x + v[:, None] * y, u, v
    if kind == GeomAbs_Cylinder:
        cyl = surface.Cylinder()
        o, x, y, z = _frame_of(cyl.Position())
        r = cyl.Radius()
        d = points - o
        u = np.mod(fv.arctan2(fv.matmul(d, y), fv.matmul(d, x)), 2 * math.pi)
        v = fv.matmul(d, z)
        radial = fv.cos(u)[:, None] * x + fv.sin(u)[:, None] * y
        return o + v[:, None] * z + r * radial, u, v
    if kind == GeomAbs_Cone:
        cone = surface.Cone()
        o, x, y, z = _frame_of(cone.Position())
        r, a = cone.RefRadius(), cone.SemiAngle()
        d = points - o
        u = np.mod(fv.arctan2(fv.matmul(d, y), fv.matmul(d, x)), 2 * math.pi)
        rho = fv.hypot(fv.matmul(d, x), fv.matmul(d, y))
        h = fv.matmul(d, z)
        # In the half-plane at angle u, the generator is (r + v sin a, v cos a): the foot on that line.
        v = (rho - r) * fs.sin(a) + h * fs.cos(a)
        radial = fv.cos(u)[:, None] * x + fv.sin(u)[:, None] * y
        return (
            o + (r + v * fs.sin(a))[:, None] * radial + (v * fs.cos(a))[:, None] * z,
            u,
            v,
        )
    if kind == GeomAbs_Sphere:
        sphere = surface.Sphere()
        o, x, y, z = _frame_of(sphere.Position())
        r = sphere.Radius()
        d = points - o
        u = np.mod(fv.arctan2(fv.matmul(d, y), fv.matmul(d, x)), 2 * math.pi)
        length = fv.norm(d, axis=1)
        v = fv.arcsin(
            np.clip(
                np.where(
                    length > 0,
                    (fv.matmul(d, z)) / np.where(length > 0, length, 1.0),
                    0.0,
                ),
                -1.0,
                1.0,
            )
        )
        way = (
            fv.cos(v)[:, None] * (fv.cos(u)[:, None] * x + fv.sin(u)[:, None] * y)
            + fv.sin(v)[:, None] * z
        )
        return o + r * way, u, v
    if kind == GeomAbs_Torus:
        torus = surface.Torus()
        o, x, y, z = _frame_of(torus.Position())
        big, small = torus.MajorRadius(), torus.MinorRadius()
        d = points - o
        u = np.mod(fv.arctan2(fv.matmul(d, y), fv.matmul(d, x)), 2 * math.pi)
        radial = fv.cos(u)[:, None] * x + fv.sin(u)[:, None] * y
        rho = fv.hypot(fv.matmul(d, x), fv.matmul(d, y))
        v = np.mod(fv.arctan2(fv.matmul(d, z), rho - big), 2 * math.pi)
        way = fv.cos(v)[:, None] * radial + fv.sin(v)[:, None] * z
        return o + big * radial + small * way, u, v
    if kind == GeomAbs_SurfaceOfExtrusion:
        return _extrusion_feet(surface, points)
    return None


def _extrusion_feet(surface: Any, points: Array) -> tuple[Array, Array, Array] | None:
    """Each point's nearest point on a surface of linear extrusion whose curve is a line or a polynomial Bézier of degree two at most (letters' walls); None for any other.

    The surface is C(u) + v D (D the unit direction). Square to D the point's
    foot on it is its foot on the curve projected there: for a quadratic
    curve, B(u) = P0 + 2 b u + a u² (a = P0 - 2 P1 + P2, b = P1 - P0), a root
    of the cubic (a·a) u³ + 3 (a·b) u² + (2 b·b + a·d) u + b·d (d = P0 - p),
    every component taken square to D: its three roots (the companion
    matrix's eigenvalues, the real part of each), each polished by Newton's
    method, and the curve's ends, the nearest of them kept, within the
    curve's own parameters. Then v is the point's place along D past that
    point of the curve. Every foot is a point of the surface, at the
    parameters returned.
    """
    curve = surface.BasisCurve()
    kind = curve.GetType()
    first, last = curve.FirstParameter(), curve.LastParameter()
    if kind == GeomAbs_Line:
        line = curve.Line()
        o, way = line.Location(), line.Direction()
        poles = np.array(
            [[o.X(), o.Y(), o.Z()], [o.X() + way.X(), o.Y() + way.Y(), o.Z() + way.Z()]]
        )
        start, span = (
            0.0,
            1.0,
        )  # the line's own parameter is its length from its location
    elif kind == GeomAbs_BezierCurve:
        bezier = curve.Bezier()
        if bezier.IsRational() or bezier.Degree() > 2:
            return None
        poles = np.array(
            [
                [q.X(), q.Y(), q.Z()]
                for q in (bezier.Pole(k) for k in range(1, bezier.NbPoles() + 1))
            ]
        )
        start, span = 0.0, 1.0
    else:
        return None
    d_ = surface.Direction()
    direction = np.array([d_.X(), d_.Y(), d_.Z()])
    if len(poles) == 2:  # straight: as a quadratic with its control point midway
        poles = np.array([poles[0], (poles[0] + poles[1]) / 2.0, poles[1]])

    def square(x: Array) -> Array:
        found: Array = x - (fv.matmul(x, direction))[..., None] * direction
        return found

    p0, p1, p2 = poles
    a, b = square(p0 - 2.0 * p1 + p2), square(p1 - p0)
    d = square(p0 - points)
    c3 = float(fv.matmul(a, a))
    c2 = 3.0 * float(fv.matmul(a, b))
    c1 = 2.0 * float(fv.matmul(b, b)) + fv.matmul(d, a)
    c0 = fv.matmul(d, b)
    n = len(points)
    if c3 > 1e-30 * fv.sq(max(1.0, float(fv.matmul(b, b)))):
        # The cubic's real roots (the distance's turning points); NaN where it has one.
        monic = np.stack([np.ones(n), np.full(n, c2 / c3), c1 / c3, c0 / c3], axis=1)
        roots = fv.real_roots(monic)
    else:  # straight and evenly paced: the root of c1 u + c0
        roots = np.where(c1 != 0.0, -c0 / np.where(c1 != 0.0, c1, 1.0), 0.0)[:, None]
    lo, hi = (first - start) / span, (last - start) / span
    roots = np.where(np.isnan(roots), lo, roots)  # (the ends are tried anyway)
    tries = np.concatenate(
        [np.clip(roots, lo, hi), np.full((n, 1), lo), np.full((n, 1), hi)], axis=1
    )
    # Newton's method on the cubic, kept within the curve's parameters.
    for _ in range(2):
        g = ((c3 * tries + c2) * tries + c1[:, None]) * tries + c0[:, None]
        dg = (3.0 * c3 * tries + 2.0 * c2) * tries + c1[:, None]
        step = np.where(dg != 0.0, g / np.where(dg != 0.0, dg, 1.0), 0.0)
        tries = np.where(np.isfinite(step), np.clip(tries - step, lo, hi), tries)

    def at(t: Array) -> Array:
        found: Array = (
            p0
            + 2.0 * t[..., None] * (p1 - p0)
            + (t * t)[..., None] * (p0 - 2.0 * p1 + p2)
        )
        return found

    gaps = fv.norm(square(at(tries) - points[:, None, :]), axis=2)
    t = tries[np.arange(n), np.argmin(gaps, axis=1)]
    on_curve = at(t)
    v = fv.matmul(points - on_curve, direction)
    return on_curve + v[:, None] * direction, start + span * t, v


# --- coverage of one face ------------------------------------------------------------


def _box_meets(box: tuple[Array, Array], within: Box) -> bool:
    """Whether a box (its least and greatest corners) meets ``within``."""
    return bool(
        np.all(box[0] <= np.asarray(within.hi))
        and np.all(box[1] >= np.asarray(within.lo))
    )


def _meets(shape: Any, within: Box) -> bool:
    """Whether the shape's box (a face's, an edge's) meets ``within``."""
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, False)
    x0, y0, z0, x1, y1, z1 = box_limits(box)
    return bool(np.all(np.array([x0, y0, z0]) <= np.asarray(within.hi))
                and np.all(np.array([x1, y1, z1]) >= np.asarray(within.lo)))  # fmt: skip


def _outward(
    face: Any,
    surface: Any,
    u: float,
    v: float,
    centre: tuple[float, float] | None = None,
) -> Array:
    """The face's outward unit normal at (u, v); at or by a singular point as :func:`_at_singular` finds it."""
    p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
    surface.D1(u, v, p, du, dv)
    n = du.Crossed(dv)
    if _regular(n, du, dv):
        found = _xyz(n)
    else:
        if centre is None:
            u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
            centre = ((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        found = _at_singular(surface, u, v, centre)
    found = np.asarray(found / fv.norm(found))
    return -found if face.Orientation() == TopAbs_REVERSED else found


def _regular(n: Any, du: Any, dv: Any) -> bool:
    """Whether the derivatives' cross product ``n`` is clear of a singular point (:data:`_SINGULAR`)."""
    return bool(n.Magnitude() > _SINGULAR * max(1.0, du.Magnitude() * dv.Magnitude()))


def _at_singular(
    surface: Any, u: float, v: float, centre: tuple[float, float]
) -> Array:
    """The surface's normal at or by a pole or an apex, facing the way the surface's do just inside the face.

    OpenCascade's own (from the surface's higher derivatives where the first
    vanish) gives its line, but not which way it faces: just past a cone's
    apex, on the other nappe, it faces the other way. The normal a step from
    the point towards the face's middle (the parameters' centre), clear of the
    singular point, settles that; it is the normal itself where OpenCascade
    finds none.
    """
    p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
    inside: Array | None = None
    for share in (1e-5, 1e-3, 1e-1):
        surface.D1(u + share * (centre[0] - u), v + share * (centre[1] - v), p, du, dv)
        n = du.Crossed(dv)
        if _regular(n, du, dv):
            inside = _xyz(n)
            break
    props = BRepLProp_SLProps(surface, u, v, 2, 1e-9)
    if props.IsNormalDefined():
        found = _xyz(props.Normal())
        return (
            -found
            if inside is not None and float(fv.matmul(found, inside)) < 0.0
            else found
        )
    if inside is None:
        raise RuntimeError("a face has no normal near a point of it")
    return inside


def _corner_reach(shape: Any) -> TopTools_IndexedDataMapOfShapeListOfShape:
    """Each vertex of the shape, and the edges that meet at it: how far an edge's end may be from the surfaces there."""
    found = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_VERTEX, TopAbs_EDGE, found)
    return found


def _face_reach(
    face: Any, corners: TopTools_IndexedDataMapOfShapeListOfShape | None
) -> float:
    """How far any point of a face may be from the part's true surface: its own tolerance, and its boundary's.

    A face is exactly on its surface, but where it ends is known only as well
    as its edges are: a point at (or by) its edge where two surfaces cross
    along a curve that approximates their crossing may lie past the other
    surface by the edge's tolerance; one at a corner, by what the edges
    meeting there allow (:func:`_end_tolerance`).
    """
    found = float(BRep_Tool.Tolerance_s(face))
    explorer = TopExp_Explorer(face, TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge(explorer.Current())
        explorer.Next()
        found = max(found, float(BRep_Tool.Tolerance_s(edge)))
        for vertex in (TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge)):
            if not vertex.IsNull():
                found = max(found, _end_tolerance(vertex, corners))
    return found


def _end_tolerance(
    vertex: Any, corners: TopTools_IndexedDataMapOfShapeListOfShape | None
) -> float:
    """How far an edge's end at ``vertex`` may be from the part's true surfaces: twice the vertex's tolerance (the end
    within it of the vertex, the vertex within it of every other edge's end) and the loosest edge meeting there (that
    edge's end within its tolerance of its faces)."""
    vertex_tol = float(BRep_Tool.Tolerance_s(vertex))
    edges = 0.0
    if corners is not None:
        k = corners.FindIndex(vertex)
        if k:
            edges = max((float(BRep_Tool.Tolerance_s(TopoDS.Edge(e))) for e in corners.FindFromIndex(k)),
                        default=0.0)  # fmt: skip
    return 2.0 * vertex_tol + edges


@dataclass(frozen=True)
class _FaceGrid:
    """What covering a face at one radius needs, whatever the box: its surface, its parameters' centre, its tolerance, its grid, and each edge's samples (the edge, its curve on the face, the samples' parameters and points)."""

    surface: Any
    centre: tuple[float, float]
    tolerance: float
    pieces: Pieces
    us: Array
    vs: Array
    edges: tuple[tuple[Any, Any, Array, Array], ...]


def _face_grid(
    face: Any, r: float, corners: TopTools_IndexedDataMapOfShapeListOfShape | None
) -> _FaceGrid:
    surface = BRepAdaptor_Surface(face, False)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    pieces = speeds(face, surface, (u0, u1, v0, v1), _CELL * r)
    edges = []
    explorer = TopExp_Explorer(face, TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge(explorer.Current())
        explorer.Next()
        if BRep_Tool.Degenerated_s(edge):
            continue
        curve = BRepAdaptor_Curve(edge)
        along = np.asarray(_by_length(curve, _CELL * r), dtype=np.float64)
        at = np.array([_xyz(curve.Value(float(t))) for t in along]).reshape(-1, 3)
        edges.append(
            (curve, BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0), along, at)
        )
    return _FaceGrid(
        surface,
        ((u0 + u1) / 2.0, (v0 + v1) / 2.0),
        _face_reach(face, corners),
        pieces,
        nodes(pieces.u, pieces.lu, _CELL * r),
        nodes(pieces.v, pieces.lv, _CELL * r),
        tuple(edges),
    )


def _cover_face(
    face: Any,
    r: float,
    corners: TopTools_IndexedDataMapOfShapeListOfShape | None = None,
    within: Box | None = None,
    grid: _FaceGrid | None = None,
) -> tuple[Array, Array, Array]:
    """Points on the face (its grid's points on it, and its edges' samples, their ends included), their outward normals
    and tolerances: each how far the face may be from the part's true surface (:func:`_face_reach`). ``within``: only
    the grid's points and the samples that may stand for a point of the face in the box (:func:`_near_box`), from the
    face's ``grid`` at ``r`` where it is given (:func:`_face_grid`)."""
    if within is not None:
        return _cover_near(
            face, r, within, grid if grid is not None else _face_grid(face, r, corners)
        )
    surface = BRepAdaptor_Surface(face, False)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    centre = ((u0 + u1) / 2.0, (v0 + v1) / 2.0)
    face_tol = _face_reach(face, corners)
    pieces = speeds(face, surface, (u0, u1, v0, v1), _CELL * r)
    us, vs = (
        nodes(pieces.u, pieces.lu, _CELL * r),
        nodes(pieces.v, pieces.lv, _CELL * r),
    )
    grid_u, grid_v = np.repeat(us, len(vs)), np.tile(vs, len(us))
    # OpenCascade's ON may reach past the face's neighbour: its edges, sampled below, stand for its boundary.
    kept = on_grid(face, us, vs, strict=True).ravel()
    grid_u, grid_v = grid_u[kept], grid_v[kept]
    return _points_on(
        face, surface, centre, face_tol, grid_u, grid_v, _edge_samples(face, r)
    )


def _edge_samples(face: Any, r: float) -> list[tuple[Any, Any, list[float]]]:
    """Each edge of the face (not degenerate): its curve, its curve on the face, and its samples' parameters, 0.6r apart."""
    found = []
    explorer = TopExp_Explorer(face, TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge(explorer.Current())
        explorer.Next()
        if BRep_Tool.Degenerated_s(edge):
            continue
        curve = BRepAdaptor_Curve(edge)
        pcurve = BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0)
        found.append((curve, pcurve, _by_length(curve, _CELL * r)))
    return found


def _cover_near(
    face: Any, r: float, within: Box, grid: _FaceGrid
) -> tuple[Array, Array, Array]:
    """:func:`_cover_face` within a box, from the face's grid at ``r``."""
    grid_u, grid_v = _near_box(
        face, grid.surface, grid.pieces, grid.us, grid.vs, within, _CELL * r
    )
    # A point of the face in the box within 0.9r of a sample (the module's docstring): one within r of it.
    reach = within.grown(r)
    lo, hi = np.asarray(reach.lo), np.asarray(reach.hi)
    samples = []
    for curve, pcurve, along, at in grid.edges:
        inside = np.all((at >= lo) & (at <= hi), axis=1)
        if inside.any():
            samples.append((curve, pcurve, along[inside].tolist()))
    return _points_on(
        face, grid.surface, grid.centre, grid.tolerance, grid_u, grid_v, samples
    )


def _points_on(face: Any, surface: Any, centre: tuple[float, float], face_tol: float, grid_u: Array, grid_v: Array,
               samples: list[tuple[Any, Any, list[float]]]) -> tuple[Array, Array, Array]:  # fmt: skip
    """The grid's points at these parameters and the edges' samples: their places, outward normals and tolerances."""
    found = _analytic(surface, grid_u, grid_v)
    points: list[Array] = []
    normals: list[Array] = []
    if found is not None:
        at, du, dv = found
        cross = np.cross(du, dv)
        size = fv.norm(cross, axis=1)
        regular = size > _SINGULAR * np.maximum(
            1.0, fv.norm(du, axis=1) * fv.norm(dv, axis=1)
        )
        unit_normals = cross / np.where(regular, size, 1.0)[:, None]
        if face.Orientation() == TopAbs_REVERSED:
            unit_normals = -unit_normals
        for k in np.flatnonzero(
            ~regular
        ):  # a pole or an apex: its normal found as anywhere else's
            unit_normals[k] = _outward(
                face, surface, float(grid_u[k]), float(grid_v[k]), centre
            )
        points.append(np.asarray(at, dtype=np.float64).reshape(-1, 3))
        normals.append(np.asarray(unit_normals, dtype=np.float64).reshape(-1, 3))
    else:
        p = gp_Pnt()
        some: list[Array] = []
        ways: list[Array] = []
        for a, b in zip(grid_u.tolist(), grid_v.tolist(), strict=True):
            surface.D0(a, b, p)
            some.append(_xyz(p))
            ways.append(_outward(face, surface, a, b, centre))
        points.append(np.asarray(some, dtype=np.float64).reshape(-1, 3))
        normals.append(np.asarray(ways, dtype=np.float64).reshape(-1, 3))
    for curve, pcurve, along in samples:
        some, ways = [], []
        for t in along:
            uv = pcurve.Value(t)
            some.append(_xyz(curve.Value(t)))
            ways.append(_outward(face, surface, uv.X(), uv.Y(), centre))
        points.append(np.asarray(some, dtype=np.float64).reshape(-1, 3))
        normals.append(np.asarray(ways, dtype=np.float64).reshape(-1, 3))
    found_points = np.concatenate(points)
    return (
        found_points,
        np.concatenate(normals),
        np.full(len(found_points), float(face_tol)),
    )


#: How many times :func:`_near_box` may halve a face's parameters' pieces looking for the box.
_HALVINGS = 64


def _near_box(face: Any, surface: Any, pieces: Pieces, us: Array, vs: Array, box: Box,
              step: float) -> tuple[Array, Array]:  # fmt: skip
    """The points of the face's grid (``us`` by ``vs``, ``step`` by the speed bounds) on the face that may stand for a point of it in the box.

    Every point of the face in the box is in a piece of its parameters
    :func:`_pieces_near` keeps (no wider than a quarter of the box, or a grid
    step), and so in a grid cell that meets one: the grid's points kept are
    every corner of every such cell, on the face, each as the whole grid has
    it. Where a speed bound isn't finite, the whole grid.
    """
    kept_pieces = _pieces_near(surface, pieces, box, max(max(box.size) / 4.0, step))
    if kept_pieces is None:
        kept = on_grid(face, us, vs, strict=True)
        i, j = np.nonzero(kept)
        return us[i], vs[j]
    if not len(kept_pieces):
        return np.zeros(0), np.zeros(0)
    found: list[NDArray[np.int64]] = []
    runs_u, runs_v = _runs(kept_pieces[:, :2]), _runs(kept_pieces[:, 2:])
    pairs = {(_run_of(runs_u, p[0]), _run_of(runs_v, p[2])) for p in kept_pieces}
    for a, b in sorted(pairs):
        i0, i1 = _nodes_round(us, *runs_u[a])
        j0, j1 = _nodes_round(vs, *runs_v[b])
        on = on_grid(face, us[i0:i1], vs[j0:j1], strict=True)
        i, j = np.nonzero(on)
        found.append((i + i0) * len(vs) + (j + j0))
    which = np.unique(np.concatenate(found))
    return us[which // len(vs)], vs[which % len(vs)]


def _pieces_near(surface: Any, pieces: Pieces, box: Box, enough: float) -> Array | None:
    """The pieces of a surface's parameters (u0, u1, v0, v1) that may reach the box; None where a speed bound isn't finite.

    The parameters are halved, the way the surface runs farther: a piece's
    points are within ``(Lu·Δu + Lv·Δv)/2`` of its middle's (along u, then
    along v), so a piece whose middle is farther than that from the box has
    no point in it and is dropped; the rest are halved until no wider than
    ``enough``. Every point of the surface in the box is in a piece kept.
    """
    if not (np.all(np.isfinite(pieces.lu)) and np.all(np.isfinite(pieces.lv))):
        return None
    lo, hi = np.asarray(box.lo), np.asarray(box.hi)
    left = np.array([[pieces.u[0], pieces.u[-1], pieces.v[0], pieces.v[-1]]])
    done: list[Array] = []
    for _ in range(_HALVINGS):
        if not len(left):
            break
        lu = np.array([_fastest(pieces.u, pieces.lu, a, b) for a, b in left[:, :2]])
        lv = np.array([_fastest(pieces.v, pieces.lv, a, b) for a, b in left[:, 2:]])
        run_u, run_v = lu * (left[:, 1] - left[:, 0]), lv * (left[:, 3] - left[:, 2])
        reach = (run_u + run_v) / 2.0
        middle = _points_at(
            surface, (left[:, 0] + left[:, 1]) / 2.0, (left[:, 2] + left[:, 3]) / 2.0
        )
        gap = fv.norm(np.maximum(np.maximum(lo - middle, middle - hi), 0.0), axis=1)
        meets = gap <= reach * (1.0 + 1e-9) + 1e-9
        left, reach, run_u, run_v = (
            left[meets],
            reach[meets],
            run_u[meets],
            run_v[meets],
        )
        small = reach <= enough
        done.append(left[small])
        left, run_u, run_v = left[~small], run_u[~small], run_v[~small]
        by_u = run_u >= run_v
        half_u, half_v = (
            (left[:, 0] + left[:, 1]) / 2.0,
            (left[:, 2] + left[:, 3]) / 2.0,
        )
        first, second = left.copy(), left.copy()
        first[by_u, 1] = second[by_u, 0] = half_u[by_u]
        first[~by_u, 3] = second[~by_u, 2] = half_v[~by_u]
        left = np.concatenate([first, second])
    done.append(left)
    return np.concatenate(done)


def may_reach(face: Any, box: Box) -> bool:
    """Whether any point of the face's surface over its parameters may be in the box: False only where none is, surely (:func:`_pieces_near`, down to a quarter of the box)."""
    if not _meets(face, box):
        return False
    surface = BRepAdaptor_Surface(face, False)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    enough = max(max(box.size) / 4.0, 1e-6)
    near = _pieces_near(
        surface, speeds(face, surface, (u0, u1, v0, v1), enough), box, enough
    )
    return near is None or bool(len(near))


def _fastest(breaks: Array, bounds: Array, a: float, b: float) -> float:
    """The greatest speed bound of the pieces from ``a`` to ``b``."""
    first = min(max(int(np.searchsorted(breaks, a, "right")) - 1, 0), len(bounds) - 1)
    last = min(max(int(np.searchsorted(breaks, b, "left")) - 1, first), len(bounds) - 1)
    return float(bounds[first : last + 1].max())


def _runs(spans: Array) -> list[tuple[float, float]]:
    """Spans of parameters, overlapping or touching ones joined, in order."""
    found: list[tuple[float, float]] = []
    for a, b in sorted(spans.tolist()):
        if found and a <= found[-1][1]:
            found[-1] = (found[-1][0], max(found[-1][1], b))
        else:
            found.append((a, b))
    return found


def _run_of(runs: list[tuple[float, float]], at: float) -> int:
    return next(k for k, (a, b) in enumerate(runs) if a <= at <= b)


def _nodes_round(nodes: Array, a: float, b: float) -> tuple[int, int]:
    """The slice of the grid's nodes from the last at or before ``a`` to the first at or after ``b``."""
    first = max(int(np.searchsorted(nodes, a, "right")) - 1, 0)
    last = min(int(np.searchsorted(nodes, b, "left")), len(nodes) - 1)
    return first, last + 1


def _points_at(surface: Any, u: Array, v: Array) -> Array:
    """The surface's points at many parameters."""
    found = _analytic(surface, u, v)
    if found is not None:
        return found[0]
    p = gp_Pnt()
    out = np.empty((len(u), 3))
    for k, (a, b) in enumerate(zip(u.tolist(), v.tolist(), strict=True)):
        surface.D0(a, b, p)
        out[k] = _xyz(p)
    return out


def _analytic(surface: Any, u: Array, v: Array) -> tuple[Array, Array, Array] | None:
    """Points and both derivatives of an analytic surface at many parameters at once (OpenCascade's own parameterisations); None for any other surface."""
    kind = surface.GetType()
    if kind not in (
        GeomAbs_Plane,
        GeomAbs_Cylinder,
        GeomAbs_Cone,
        GeomAbs_Sphere,
        GeomAbs_Torus,
    ):
        return None
    geometry = {GeomAbs_Plane: surface.Plane, GeomAbs_Cylinder: surface.Cylinder, GeomAbs_Cone: surface.Cone,
                GeomAbs_Sphere: surface.Sphere, GeomAbs_Torus: surface.Torus}[kind]()  # fmt: skip
    frame = geometry.Position()
    o, x, y, z = (_xyz(frame.Location()), _xyz(frame.XDirection()), _xyz(frame.YDirection()),
                  _xyz(frame.Direction()))  # fmt: skip
    cu, su = fv.cos(u)[:, None], fv.sin(u)[:, None]
    radial, around = cu * x + su * y, -su * x + cu * y
    if kind == GeomAbs_Plane:
        return (
            o + u[:, None] * x + v[:, None] * y,
            np.tile(x, (len(u), 1)),
            np.tile(y, (len(u), 1)),
        )
    if kind == GeomAbs_Cylinder:
        r = geometry.Radius()
        return o + r * radial + v[:, None] * z, r * around, np.tile(z, (len(u), 1))
    if kind == GeomAbs_Cone:
        r, a = geometry.RefRadius(), geometry.SemiAngle()
        reach = (r + v * fs.sin(a))[:, None]
        return (
            o + reach * radial + (v * fs.cos(a))[:, None] * z,
            reach * around,
            fs.sin(a) * radial + fs.cos(a) * z,
        )
    cv, sv = fv.cos(v)[:, None], fv.sin(v)[:, None]
    if kind == GeomAbs_Sphere:
        r = geometry.Radius()
        return (
            o + r * cv * radial + r * sv * z,
            r * cv * around,
            r * (-sv * radial + cv * z),
        )
    big, small = geometry.MajorRadius(), geometry.MinorRadius()
    reach = big + small * cv
    return (
        o + reach * radial + small * sv * z,
        reach * around,
        small * (-sv * radial + cv * z),
    )


def _by_length(curve: Any, spacing: float) -> list[float]:
    """Parameters along the curve at most ``spacing`` apart by length, its ends included.

    A curve no longer than ``spacing`` is its ends: an edge a reader made
    1.7e-8 mm long, where a boss's rim touches a block's edge (generated part
    3500 read back from STEP), OpenCascade's division by length can't divide.
    """
    first, last = curve.FirstParameter(), curve.LastParameter()
    length = GCPnts_AbscissaPoint.Length_s(curve, first, last, 1e-9)
    count = max(2, math.ceil(length / spacing) + 1)
    if count == 2:
        return [first, last]
    uniform = GCPnts_UniformAbscissa(curve, count, first, last, 1e-9)
    if not uniform.IsDone() or uniform.NbPoints() < 2:
        raise RuntimeError("an edge could not be divided by length")
    found = {float(uniform.Parameter(i)) for i in range(1, uniform.NbPoints() + 1)}
    return sorted(found | {first, last})


# --- topology ------------------------------------------------------------------------


def _bad_edges(shape: Any) -> int:
    """Edges with three or more faces, or with two using them the same way round."""
    around = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, around)
    bad = 0
    for i in range(1, around.Extent() + 1):
        edge = around.FindKey(i)
        if BRep_Tool.Degenerated_s(TopoDS.Edge(edge)):
            continue
        uses = _distinct(around.FindFromIndex(i))
        if len(uses) >= 3:
            bad += 1
        elif len(uses) == 2:
            a, b = (_uses(face, edge) for face in uses)
            if len(a) == 1 and len(b) == 1 and a[0] == b[0]:
                bad += 1
    return bad


def _uses(face: Any, edge: Any) -> list[Any]:
    """The orientations the face uses the edge with (two for a seam)."""
    found = []
    explorer = TopExp_Explorer(face, TopAbs_EDGE)
    while explorer.More():
        if explorer.Current().IsSame(edge):
            found.append(explorer.Current().Orientation())
        explorer.Next()
    return found


def _bad_vertices(shape: Any) -> int:
    """Vertices whose faces don't make one fan: not all joined to each other through edges at the vertex."""
    vertex_faces = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_VERTEX, TopAbs_FACE, vertex_faces)
    vertex_edges = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_VERTEX, TopAbs_EDGE, vertex_edges)
    edge_faces = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_faces)
    bad = 0
    for i in range(1, vertex_faces.Extent() + 1):
        vertex = vertex_faces.FindKey(i)
        around = _distinct(vertex_faces.FindFromIndex(i))
        if len(around) <= 1:
            continue
        parent = list(range(len(around)))
        k = vertex_edges.FindIndex(vertex)
        for edge in vertex_edges.FindFromIndex(k) if k else ():
            if BRep_Tool.Degenerated_s(TopoDS.Edge(edge)):
                continue
            beside = edge_faces.FindFromKey(edge)
            joined = [
                j for j, f in enumerate(around) if any(f.IsSame(g) for g in beside)
            ]
            for j in joined[1:]:
                parent[_root(parent, j)] = _root(parent, joined[0])
        if len({_root(parent, j) for j in range(len(around))}) > 1:
            bad += 1
    return bad


def _root(parent: list[int], k: int) -> int:
    """Union-find: the root of ``k``'s set, paths halved on the way."""
    while parent[k] != k:
        parent[k] = parent[parent[k]]
        k = parent[k]
    return k


def _self_intersections(shape: Any, shape_faces: list[Any]) -> int:
    """Places the surface meets itself where it isn't joined.

    OpenCascade's self-interference checker at every level but face against
    face (vertices, edges and faces against each other: a crossing that
    reaches a face's boundary is found here); then face against face, for
    the pairs that share no vertex and whose boxes meet, by their distance.
    The checker's own face-against-face level can take many minutes on one
    helical face; a crossing between two faces that share a vertex, never
    reaching either's boundary, is the one kind not looked for.

    Two vertices the checker finds within each other's tolerance are not
    counted where an edge joins them: they are the ends of an edge shorter
    than they are held to, joined by it (generated part 3500 read back from
    STEP: where a boss's rim touches a block's edge, the reader cut both
    there 1.7e-8 mm apart).
    """
    checker = BOPAlgo_CheckerSI()
    arguments = TopTools_ListOfShape()
    arguments.Append(shape)
    checker.SetArguments(arguments)
    checker.SetRunParallel(False)
    checker.SetNonDestructive(True)
    checker.SetLevelOfCheck(_CHECKED_LEVEL)
    checker.Perform()
    if checker.HasErrors():
        raise RuntimeError("OpenCascade's self-interference check failed")
    store = checker.DS()
    corners = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_VERTEX, corners)
    joined = _joined_corners(shape, corners)
    meetings = store.InterfVV()
    found = sum(
        1
        for k in range(meetings.Size())
        if frozenset(
            corners.FindIndex(store.Shape(i)) for i in meetings.Value(k).Indices()
        )
        not in joined
    )
    found += sum(
        getattr(store, kind)().Size()
        for kind in ("InterfVE", "InterfEE", "InterfVF", "InterfEF")
    )
    own = [frozenset(corners.FindIndex(v) for v in vertices(f)) for f in shape_faces]
    boxes = []
    for face in shape_faces:
        box = Bnd_Box()
        BRepBndLib.Add_s(face, box, False)
        boxes.append(box_limits(box))
    lo, hi = np.array(boxes)[:, :3], np.array(boxes)[:, 3:]
    for i in range(len(shape_faces)):
        meets = (
            np.flatnonzero(
                np.all(lo[i + 1 :] <= hi[i], axis=1)
                & np.all(hi[i + 1 :] >= lo[i], axis=1)
            )
            + i
            + 1
        )
        for j in meets:
            if own[i] & own[j]:
                continue
            gap = BRepExtrema_DistShapeShape(shape_faces[i], shape_faces[int(j)])
            reach = BRep_Tool.Tolerance_s(shape_faces[i]) + BRep_Tool.Tolerance_s(
                shape_faces[int(j)]
            )
            if not gap.IsDone() or gap.Value() <= reach:
                found += 1
    return int(found)


def _joined_corners(
    shape: Any, corners: TopTools_IndexedMapOfShape
) -> set[frozenset[int]]:
    """The pairs of vertices (by their index in ``corners``) an edge joins: its two ends."""
    joined: set[frozenset[int]] = set()
    for edge in edges(shape):
        if BRep_Tool.Degenerated_s(edge):
            continue
        ends = frozenset(
            corners.FindIndex(v)
            for v in (TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge))
        )
        if len(ends) == 2:
            joined.add(ends)
    return joined


def _signed_volume(shape: Any) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, INTEGRATION, False)
    return float(props.Mass())


def _nesting(shape: Any, topology: Topology) -> Topology:
    """On an otherwise sound B-rep: its solids and voids, whether each shell lies where its orientation says, each solid's genus."""
    found = solids(shape)
    voids = 0
    misnested = 0
    outers: list[tuple[float, Any]] = []
    for solid in found:
        outer = BRepClass3d.OuterShell_s(TopoDS.Solid(solid))
        hull = BRepBuilderAPI_MakeSolid(outer).Solid()
        enclosed = _signed_volume(hull)
        if enclosed <= 0.0:
            misnested += 1
        outers.append((enclosed, outer))
        inside = BRepClass3d_SolidClassifier(hull)
        for shell in shells(solid):
            if shell.IsSame(outer):
                continue
            voids += 1
            inside.Perform(BRep_Tool.Pnt_s(TopoDS.Vertex(vertices(shell)[0])), ON)
            if _signed_volume(shell) >= 0.0 or inside.State() != TopAbs_IN:
                misnested += 1
    # A solid within another's material (not in a hollow of it) is misnested too.
    for k, solid in enumerate(found):
        point = BRep_Tool.Pnt_s(TopoDS.Vertex(vertices(solid)[0]))
        for j, other in enumerate(found):
            if j == k:
                continue
            classifier = BRepClass3d_SolidClassifier(other)
            classifier.Perform(point, ON)
            if classifier.State() == TopAbs_IN:
                misnested += 1
                break
    genus = tuple(
        _genus(outer) for _, outer in sorted(outers, key=lambda pair: -pair[0])
    )
    return replace(
        topology, solids=len(found), voids=voids, misnested=misnested, genus=genus
    )


def _genus(shell: Any) -> int:
    """A closed shell's through-holes, by Euler-Poincare: V - E + 2F - B = 2 - 2G, degenerate edges left out.

    B counts each face's boundary in pieces: its wires, two that meet at a
    vertex being one piece (:func:`_boundary_pieces`). A face is one piece
    of plane less a hole for each further piece, so it adds 2 - its pieces.
    Counted by wires alone, a boss flush with a face's edge, its circle
    touching the face's outline at a point, made a hole the face doesn't have
    (generated part 450: two such bosses, genus 12 for 11).
    """
    v = len(vertices(shell))
    e = sum(1 for x in edges(shell) if not BRep_Tool.Degenerated_s(TopoDS.Edge(x)))
    shell_faces = faces(shell)
    pieces = sum(_boundary_pieces(face) for face in shell_faces)
    chi = v - e + 2 * len(shell_faces) - pieces
    return max((2 - chi) // 2, 0)


def _boundary_pieces(face: Any) -> int:
    """How many pieces a face's boundary is in: its wires, joined where two share a vertex."""
    wires = []
    explorer = TopExp_Explorer(face, TopAbs_WIRE)
    while explorer.More():
        wires.append(explorer.Current())
        explorer.Next()
    if len(wires) < 2:
        return len(wires)
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(face, TopAbs_VERTEX, found)
    owner: dict[int, int] = {}
    parent = list(range(len(wires)))

    def root(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for k, wire in enumerate(wires):
        corners = TopExp_Explorer(wire, TopAbs_VERTEX)
        while corners.More():
            index = found.FindIndex(corners.Current())
            if index in owner:
                parent[root(k)] = root(owner[index])
            else:
                owner[index] = k
            corners.Next()
    return len({root(k) for k in range(len(wires))})


# --- faces and edges by their geometry -------------------------------------------------


def _canonical(direction: Array) -> Array:
    """A direction's sign fixed: its first component that isn't zero positive."""
    for c in direction:
        if abs(c) > 1e-12:
            return direction if c > 0 else -direction
    return direction


def face_facts(face: Any) -> FaceFacts:
    surface = BRepAdaptor_Surface(face, True)
    kind = surface.GetType()
    params: tuple[Any, ...] = ()
    name = "other"
    if kind == GeomAbs_Plane:
        found = plane_of(face)
        assert found is not None
        n = np.array(found[1])
        name, params = "plane", (*n, float(fv.matmul(n, np.array(found[0]))))
    elif kind == GeomAbs_Cylinder:
        cylinder = surface.Cylinder()
        axis, origin = (
            _canonical(_xyz(cylinder.Axis().Direction())),
            _xyz(cylinder.Axis().Location()),
        )
        name, params = (
            "cylinder",
            (*(origin - (fv.matmul(origin, axis)) * axis), *axis, cylinder.Radius()),
        )
    elif kind == GeomAbs_Cone:
        cone = surface.Cone()
        name, params = (
            "cone",
            (
                *_xyz(cone.Apex()),
                *_canonical(_xyz(cone.Axis().Direction())),
                abs(cone.SemiAngle()),
            ),
        )
    elif kind == GeomAbs_Sphere:
        sphere = surface.Sphere()
        name, params = "sphere", (*_xyz(sphere.Location()), sphere.Radius())
    elif kind == GeomAbs_Torus:
        torus = surface.Torus()
        name, params = "torus", (*_xyz(torus.Location()), *_canonical(_xyz(torus.Axis().Direction())),
                                 torus.MajorRadius(), torus.MinorRadius())  # fmt: skip
    return FaceFacts(
        name, tuple(float(value) for value in params), surface_area(face), _box_of(face)
    )


def edge_facts(edge: Any) -> EdgeFacts:
    curve = BRepAdaptor_Curve(edge)
    kind = curve.GetType()
    params: tuple[Any, ...] = ()
    name = "other"
    if kind == GeomAbs_Line:
        line = curve.Line()
        d, o = _canonical(_xyz(line.Direction())), _xyz(line.Location())
        name, params = "line", (*(o - (fv.matmul(o, d)) * d), *d)
    elif kind == GeomAbs_Circle:
        circle = curve.Circle()
        name, params = "circle", (*_xyz(circle.Location()), *_canonical(_xyz(circle.Axis().Direction())),
                                  circle.Radius())  # fmt: skip
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    return EdgeFacts(
        name,
        tuple(float(value) for value in params),
        float(props.Mass()),
        _box_of(edge),
    )
