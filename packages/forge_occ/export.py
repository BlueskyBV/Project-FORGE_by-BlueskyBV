"""Export: STEP, STL and 3MF, each read back and checked before it is handed over (docs/V2-stage3.md, section 12).

**Meshes.** A copy of the part is meshed (the copy carries no mesh, so no old
one is reused) at the export tolerance's deflection, and the mesh is then
*measured*, because OpenCascade's mesher aims at its deflection and doesn't
promise it: ten points of every triangle (its corners, centre, sides' middles, and
halfway from its centre to each corner) are measured from the exact surface
of the face the triangle was made from, and every point of a coverage of
the exact surface from the mesh. A triangle measured too far is split, its
new points on the surface (:func:`refine`: on a fitted B-spline face the
mesher can leave one several times its deflection away however fine it is
asked to mesh); a mesh still measured further from the surface than the
tolerance is made again at half the deflection, up to four times, then
refused.

**STL** is binary, in millimetres. **3MF** is written with lib3mf, in
millimetres, one object, its build item placing the part on the plate (its
lowest point at z = 0; turned by the orientation given, identity in stage 3).
Each is read back by ``forge_checks``' own reader (NumPy only, no
OpenCascade) and must be sound, hold the exact volume within its interval,
and measure within the tolerance of the exact surface again (the file's
float32 or decimal rounding included).

**STEP** is AP242 in millimetres, written by OpenCascade's XCAF writer so
every part, assembly and instance is named, each instance with its
placement. It is read back by OpenCascade's STEP reader: it must say
millimetres (an inch file is read in mm), hold the same solids, valid, with
the same volume, area, centre and box to 1e-6 relative, the same faces by
surface kind, and the assembly's names and placements as written.
"""

from __future__ import annotations

import math
import os
import re
import struct
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Context, Decimal
from typing import Any

import numpy as np
from forge_checks.mesh import Mesh, MeshView
from forge_checks.readers import MeshFileError, read_3mf, read_stl
from forge_checks.view import Box
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from numpy.typing import NDArray
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.collections import (
    IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedDataMapOfShapeListOfShape,
)
from OCP.collections import (
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape,
)
from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
from OCP.Extrema import Extrema_GenLocateExtPS
from OCP.GeomAbs import (
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
from OCP.gp import gp_Pnt
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_Controller
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_FORWARD,
    TopAbs_REVERSED,
    TopAbs_VERTEX,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool

from .errors import OperationError
from .geom import Motion
from .measure import Properties, properties, surface_distance, volume_interval
from .occt import boundary, copy, faces, is_valid, loosest_tolerance, solids
from .view import BrepView, may_reach

__all__ = [
    "REMESHES",
    "ExportTolerance",
    "PartMesh",
    "StepFile",
    "StepPart",
    "check_mesh_file",
    "check_step",
    "deviation",
    "deviations",
    "exchanged",
    "face_tolerances",
    "file_view",
    "mesh_part",
    "plate_shift",
    "read_step",
    "refine",
    "refine_each",
    "refined",
    "refined_each",
    "stl_bytes",
    "threemf_bytes",
    "triangles_meet",
    "write_step",
]

Array = NDArray[np.float64]

_ANALYTIC = (
    GeomAbs_Plane,
    GeomAbs_Cylinder,
    GeomAbs_Cone,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
#: How many times a mesh found too far from the surface (once its far triangles are split) is made again, at half the deflection each time.
REMESHES = 4
#: How closely a part read back from STEP must match it (relative: volume to volume, area to area, lengths to its size).
STEP_MATCH = 1e-6
#: How closely a placement read back must match the one written (mm, and as a rotation matrix's entries).
PLACEMENT_MATCH = 1e-9


@dataclass(frozen=True)
class ExportTolerance:
    """How far a mesh may stray from the exact surface: ``linear`` mm, and ``angular`` radians between neighbouring triangles; in each box of ``finer``, its own linear tolerance (docs/V2-stage4.md, 13.10)."""

    linear: float = 0.01
    angular: float = 0.1
    finer: tuple[tuple[Box, float], ...] = ()

    def __post_init__(self) -> None:
        for name in ("linear", "angular"):
            value = getattr(self, name)
            if not (
                isinstance(value, int | float) and math.isfinite(value) and value > 0.0
            ):
                raise ValueError(
                    f"an export tolerance's {name} must be a positive number, not {value!r}"
                )
        for box, linear in self.finer:
            if type(box) is not Box or not (
                math.isfinite(linear) and 0.0 < linear < self.linear
            ):
                raise ValueError(
                    f"an export tolerance's finer boxes are Boxes, each finer than its linear: {box!r}, {linear!r}"
                )

    @property
    def finest(self) -> float:
        """The least linear tolerance anywhere."""
        return min((self.linear, *(d for _, d in self.finer)))

    def of_triangles(self, triangles: Array) -> Array:
        """Each triangle's tolerance, as a mesh file's reader works it out: the least of ``linear`` and each finer box's that the triangle meets (:func:`triangles_meet`).

        A triangle that meets a finer box lies on a face meshed at that box's
        tolerance, or finer (:func:`face_tolerances`). Its corners' box is not
        the triangle: a long triangle on a turned block's side spans a box
        round its hole that the side never comes near (the corpus's turned
        block).
        """
        triangles = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
        found = np.full(len(triangles), float(self.linear))
        for box, linear in self.finer:
            meets = triangles_meet(triangles, box)
            found[meets] = np.minimum(found[meets], linear)
        return found


def triangles_meet(triangles: Array, box: Box) -> NDArray[np.bool_]:
    """Whether each triangle (n, 3, 3) meets the box, edges and corners included: no axis of the box's, of its plane's or across one of its edges and one of the box's separates them (the separating axis theorem)."""
    triangles = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    lo, hi = np.asarray(box.lo, dtype=np.float64), np.asarray(box.hi, dtype=np.float64)
    half = (hi - lo) / 2.0
    corners = triangles - (lo + hi) / 2.0
    edges = np.roll(corners, -1, axis=1) - corners
    axes = [np.broadcast_to(np.eye(3)[i], (len(corners), 3)) for i in range(3)]
    axes.append(np.cross(edges[:, 0], edges[:, 1]))
    axes += [np.cross(np.eye(3)[i], edges[:, j]) for i in range(3) for j in range(3)]
    meets = np.ones(len(corners), dtype=bool)
    for axis in axes:
        on = np.sum(corners * axis[:, None, :], axis=2)
        reach = np.sum(half * np.abs(axis), axis=1)
        meets &= (on.min(axis=1) <= reach) & (on.max(axis=1) >= -reach)
    return meets


def face_tolerances(shape: Any, tolerance: ExportTolerance) -> Array:
    """Each face's tolerance, the mesh is made and measured to: the least of ``tolerance.linear`` and each finer box's that the face's surface may come within ``linear`` of (:func:`~forge_occ.view.may_reach`).

    Every triangle of a face is within the face's tolerance of its surface,
    so within ``linear`` of it: a triangle that meets a finer box is on a
    face held to that box's tolerance, or finer.
    """
    shape_faces = faces(shape)
    found = np.full(len(shape_faces), float(tolerance.linear))
    for box, linear in tolerance.finer:
        grown = box.grown(tolerance.linear)
        for k, face in enumerate(shape_faces):
            if linear < found[k] and may_reach(TopoDS.Face(face), grown):
                found[k] = linear
    return found


# --- meshes ----------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class PartMesh:
    """A part's mesh: welded, outward; which face each triangle was made from; how far it was measured from the surface."""

    mesh: Mesh
    face: NDArray[np.int64]
    #: Each triangle's corners in its face's parameters, (n, 3, 2), in the mesh's triangle order.
    uv: Array
    deviation: float
    deflection: float
    measured: int = field(default=0)
    #: Each face's tolerance, by the shape's faces (:func:`face_tolerances`); None: the deflection's everywhere.
    tolerance: Array | None = field(default=None)


def _triangulate(
    shape: Any, deflection: float | Array, angular: float
) -> tuple[Mesh, NDArray[np.int64], Array]:
    """A mesh of a copy of the part: its faces' triangles, welded where the faces meet, by the part's own edges.

    ``deflection``: the part's, or each face's (by the shape's faces): the
    faces asking for finer are meshed first, in groups where they meet
    (:func:`_finer_groups`), then the whole part at the coarsest;
    OpenCascade's mesher keeps a face's mesh, and its edges' polygons, where
    they are finer than it is asked for.

    A face's nodes along an edge are the edge's own discretisation, one for
    every face the edge bounds, so the faces either side of an edge have the
    same nodes there, in the same order, but not always at exactly the same
    coordinates (a sphere's pole is two nodes). So they are welded by what
    they are, not where: the k-th node along an edge is one vertex for every
    face the edge bounds, an edge's end is the part's vertex there, and a
    degenerate edge (a pole, an apex) is its vertex throughout. A triangle the
    weld leaves with two corners the same had no area: it is dropped.
    """
    work = copy(shape)
    each = np.asarray(deflection, dtype=np.float64)
    coarsest = float(each.max())
    with boundary("meshing the part", deflection=coarsest):
        if each.ndim:
            mine = faces(work)
            for group, finer in _finer_groups(work, each):
                together = TopoDS_Compound()
                builder = BRep_Builder()
                builder.MakeCompound(together)
                for k in group:
                    builder.Add(together, mine[k])
                meshed = BRepMesh_IncrementalMesh(
                    together, finer, False, angular, False
                )
                if not meshed.IsDone():
                    raise OperationError("OpenCascade could not mesh faces of the part",
                                         faces=group, deflection=finer)  # fmt: skip
        mesher = BRepMesh_IncrementalMesh(work, coarsest, False, angular, False)
        if not mesher.IsDone():
            raise OperationError(
                "OpenCascade could not mesh the part", deflection=coarsest
            )
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(work, TopAbs_EDGE, edge_map)
    vertex_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(work, TopAbs_VERTEX, vertex_map)
    places: dict[Any, int] = {}
    points: list[Array] = []
    triangles: list[NDArray[np.int64]] = []
    owner: list[NDArray[np.int64]] = []
    params: list[Array] = []
    for k, face in enumerate(faces(work)):
        f = TopoDS.Face(face)
        where = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(f, where)
        if poly is None:
            raise OperationError(
                "a face came out of the mesher without triangles", face=k
            )
        if not poly.HasUVNodes():
            raise OperationError(
                "a face came out of the mesher without its triangles' parameters",
                face=k,
            )
        trsf = where.Transformation()
        count = poly.NbNodes()
        nodes = np.array(
            [_xyz(poly.Node(i).Transformed(trsf)) for i in range(1, count + 1)]
        )
        uv = np.array(
            [(q.X(), q.Y()) for q in (poly.UVNode(i) for i in range(1, count + 1))]
        )
        keys: list[Any] = [("face", k, i) for i in range(count)]
        explorer = TopExp_Explorer(f, TopAbs_EDGE)
        while explorer.More():
            edge = TopoDS.Edge(explorer.Current())
            explorer.Next()
            line = BRep_Tool.PolygonOnTriangulation_s(edge, poly, where)
            if line is None:
                raise OperationError(
                    "an edge came out of the mesher without its nodes on a face", face=k
                )
            along = [line.Nodes().Value(i) - 1 for i in range(1, line.NbNodes() + 1)]
            ts = (
                [line.Parameter(i) for i in range(1, line.NbNodes() + 1)]
                if line.HasParameters()
                else None
            )
            if ts is not None and ts[0] > ts[-1]:
                along, ts = along[::-1], ts[::-1]
            forward = TopoDS.Edge(edge.Oriented(TopAbs_FORWARD))
            first, last = TopExp.FirstVertex_s(forward), TopExp.LastVertex_s(forward)
            e = edge_map.FindIndex(edge)
            if BRep_Tool.Degenerated_s(edge):
                for node in along:
                    keys[node] = ("vertex", vertex_map.FindIndex(first))
                continue
            for j, node in enumerate(along):
                if j == 0:
                    keys[node] = ("vertex", vertex_map.FindIndex(first))
                elif j == len(along) - 1:
                    keys[node] = ("vertex", vertex_map.FindIndex(last))
                else:
                    keys[node] = ("edge", e, j)
        index = np.empty(count, dtype=np.int64)
        for i, key in enumerate(keys):
            found = places.get(key)
            if found is None:
                found = places[key] = len(points)
                points.append(nodes[i])
            index[i] = found
        corners = (
            np.array(
                [poly.Triangle(i).Get() for i in range(1, poly.NbTriangles() + 1)],
                dtype=np.int64,
            )
            - 1
        )
        if f.Orientation() == TopAbs_REVERSED:
            corners = corners[:, [0, 2, 1]]
        triangles.append(index[corners])
        params.append(uv[corners])
        owner.append(np.full(len(corners), k, dtype=np.int64))
    corners = np.concatenate(triangles)
    # A triangle between two nodes the weld made one (a sliver at a pole) has no area left: it goes.
    keep = (
        (corners[:, 0] != corners[:, 1])
        & (corners[:, 1] != corners[:, 2])
        & (corners[:, 2] != corners[:, 0])
    )
    return (
        Mesh(np.asarray(points), corners[keep]),
        np.concatenate(owner)[keep],
        np.concatenate(params)[keep],
    )


def _xyz(p: Any) -> Array:
    return np.array([p.X(), p.Y(), p.Z()], dtype=np.float64)


#: Where each triangle is measured from the surface, by its corners' weights: the corners, the centre, the sides' middles, and halfway from the centre to each corner.
_WEIGHTS = np.array([
    [1, 0, 0], [0, 1, 0], [0, 0, 1], [1 / 3, 1 / 3, 1 / 3], [1 / 2, 1 / 2, 0], [0, 1 / 2, 1 / 2], [1 / 2, 0, 1 / 2],
    [2 / 3, 1 / 6, 1 / 6], [1 / 6, 2 / 3, 1 / 6], [1 / 6, 1 / 6, 2 / 3],
])  # fmt: skip


def _samples(corners: Array) -> Array:
    """Each triangle's points measured from the surface: (n, 10, 3)."""
    found: Array = fv.matmul(_WEIGHTS, corners)
    return found


def _face_deviation(face: Any, samples: Array, uv: Array, enough: float) -> Array:
    """How far each sample of a mesh of the face is from the face's surface, at most.

    Exactly for planes, cylinders, cones, spheres and tori. For any other
    surface, first its distance from the surface's point at the sample's own
    parameters (the same weights of its triangle's corners' parameters), an
    upper bound on its distance from the surface; where that exceeds
    ``enough``, its distance from the nearest point of the surface found by
    searching from there (a local search: still at least the true distance);
    and where that still exceeds it, from the nearest found over the face's
    parameters (OpenCascade's projection: a point of the surface too, so
    still at least the true distance). The local search can stop where it
    starts: on a letter's side, the extrusion of a Bézier curve whose speed
    falls tenfold along it, a triangle's parameters put a sample's point
    0.092 mm from it, and the search went nowhere from there; the sample was
    1e-14 mm from the surface (generated part 7470).
    """
    surface = BRepAdaptor_Surface(face, False)
    if surface.GetType() in _ANALYTIC:
        return surface_distance(face, samples)
    out = np.empty(len(samples))
    p = gp_Pnt()
    for k, (a, b) in enumerate(uv.tolist()):
        surface.D0(a, b, p)
        out[k] = fs.dist(samples[k], (p.X(), p.Y(), p.Z()))
    far = np.flatnonzero(out > enough)
    if far.size:
        search = Extrema_GenLocateExtPS(surface, 1e-12, 1e-12)
        with boundary("measuring a mesh from its surface"):
            for k in far:
                search.Perform(
                    gp_Pnt(*map(float, samples[k])),
                    float(uv[k, 0]),
                    float(uv[k, 1]),
                    True,
                )
                if search.IsDone():
                    out[k] = min(out[k], math.sqrt(max(search.SquareDistance(), 0.0)))
        still = far[out[far] > enough]
        if still.size:
            out[still] = np.minimum(out[still], _projected(face, samples[still]))
    return out


def _projected(face: Any, points: Array) -> Array:
    """Each point's distance from the nearest point of the face's surface over the face's parameters that
    OpenCascade's projection finds (inf where it finds none)."""
    from OCP.BRepTools import BRepTools
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf

    out = np.full(len(points), np.inf)
    with boundary("measuring a mesh from its surface"):
        surface = BRep_Tool.Surface_s(face)
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        for k, point in enumerate(points.tolist()):
            projection = GeomAPI_ProjectPointOnSurf(
                gp_Pnt(*point), surface, u0, u1, v0, v1
            )
            if projection.NbPoints():
                out[k] = float(projection.LowerDistance())
    return out


def deviation(shape: Any, triangles: Array, owner: NDArray[np.int64], uv: Array, *, enough: float | Array,
              view: BrepView | None = None, mesh_view: MeshView | None = None,
              radius: float | None = None, mesh_to_surface: float | Array | None = None) -> tuple[float, int]:  # fmt: skip
    """The largest distance measured between a mesh of ``shape`` and its exact surface (at most), and how many points were measured (:func:`deviations`, the largest of each face's)."""
    by_face, count = deviations(shape, triangles, owner, uv, enough=enough, view=view, mesh_view=mesh_view,
                                radius=radius, mesh_to_surface=mesh_to_surface)  # fmt: skip
    return float(by_face.max(initial=0.0)), count


def deviations(shape: Any, triangles: Array, owner: NDArray[np.int64], uv: Array, *, enough: float | Array,
               view: BrepView | None = None, mesh_view: MeshView | None = None,
               radius: float | None = None, mesh_to_surface: float | Array | None = None) -> tuple[Array, int]:  # fmt: skip
    """The largest distance measured between a mesh of ``shape`` and each of its faces (at most), by the shape's faces, and how many points were measured.

    Mesh to surface: ten points of each triangle (its corners, centre, sides'
    middles, and halfway from its centre to each corner) from the surface of
    the face it was made from (:func:`_face_deviation`; ``enough``, the
    part's or each face's, is the distance below which a bound needn't be
    refined), unless already measured (``mesh_to_surface``, as :func:`refine`
    measures it: the largest, or each triangle's). Surface to mesh: every
    point of the exact surface's coverage (at ``radius``, a fortieth of the
    part's size by default) from the mesh, as its face's.
    """
    shape_faces = faces(shape)
    by_face = np.zeros(len(shape_faces))
    count = 0
    each = np.asarray(enough, dtype=np.float64)
    if mesh_to_surface is not None:
        measured = np.asarray(mesh_to_surface, dtype=np.float64)
        if measured.ndim:
            np.maximum.at(by_face, owner, measured)
        else:
            by_face[np.unique(owner)] = float(measured)
        count = len(triangles) * len(_WEIGHTS)
    else:
        samples = _samples(triangles)
        params = fv.matmul(_WEIGHTS, uv)
        for k in np.unique(owner):
            mine = owner == k
            found = _face_deviation(TopoDS.Face(shape_faces[int(k)]), samples[mine].reshape(-1, 3),
                                    params[mine].reshape(-1, 2), float(each[k] if each.ndim else each))  # fmt: skip
            by_face[k] = max(by_face[k], float(found.max()))
            count += len(found)
    exact = view if view is not None else BrepView(shape)
    if mesh_view is None:
        mesh_view = MeshView(
            Mesh.from_triangles(triangles), source="mesh-file", deflection=0.0
        )
    size = float(max(exact.bounds().size))
    cover = exact.coverage(radius if radius is not None else max(size / 40.0, 1e-3))
    if len(cover.points):
        np.maximum.at(by_face, cover.patch, mesh_view.distance(cover.points))
        count += len(cover.points)
    return by_face, count


def _finer_groups(shape: Any, each: Array) -> list[tuple[list[int], float]]:
    """The faces asking for finer than the coarsest (by the shape's faces), in groups of those that meet along an edge, each with its faces' finest; the finest group first.

    Each group is meshed as one. OpenCascade's mesher, meshing a face on its
    own, discretises its edges afresh to that face's deflection, not taking
    the polygon a neighbour meshed finer left on an edge: two faces meeting
    along an edge, meshed apart at two deflections, have different nodes
    along it, and the weld by the edge's nodes tears (part 4180: a
    countersink in one finer box, the face round it reaching a finer one).
    Meshed together, an edge two of a group's faces share is discretised
    once, for both. A face a group meets outside it is meshed with the whole
    part, at the coarsest, and takes the group's nodes along their edges.
    """
    coarsest = float(each.max(initial=0.0))
    finer = {int(k) for k in np.flatnonzero(each < coarsest)}
    known = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, known)
    around = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, around)
    parent = list(range(len(each)))

    def root(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i in range(1, around.Extent() + 1):
        meeting = sorted(
            {known.FindIndex(f) - 1 for f in around.FindFromIndex(i)} & finer
        )
        for k in meeting[1:]:
            parent[root(k)] = root(meeting[0])
    groups: dict[int, list[int]] = {}
    for k in sorted(finer):
        groups.setdefault(root(k), []).append(k)
    return sorted(
        ((group, float(each[group].min())) for group in groups.values()),
        key=lambda found: (found[1], found[0]),
    )


#: How many times the triangles measured too far from the surface are split before the mesh is taken as it is.
REFINES = 12


def refine(shape: Any, mesh: Mesh, owner: NDArray[np.int64], uv: Array, enough: float | Array,
           rounds: int = REFINES) -> tuple[Mesh, NDArray[np.int64], Array, float]:  # fmt: skip
    """:func:`refine_each`'s mesh, owners and parameters, and the largest distance measured from the surface."""
    fine, fine_owner, fine_uv, each = refine_each(
        shape, mesh, owner, uv, enough, rounds
    )
    return fine, fine_owner, fine_uv, float(each.max(initial=0.0))


def refine_each(shape: Any, mesh: Mesh, owner: NDArray[np.int64], uv: Array, enough: float | Array,
                rounds: int = REFINES) -> tuple[Mesh, NDArray[np.int64], Array, Array]:  # fmt: skip
    """The mesh with every triangle measured further than ``enough`` (the part's, or each face's) from its face split, until none is or ``rounds`` run out.

    OpenCascade's mesher doesn't always meet its deflection: on a fitted
    B-spline face it can leave a triangle several times its deflection from
    the surface however fine it is asked to mesh. So each triangle is
    measured (ten points, :func:`_face_deviation`), and each one too far is
    split: each of its sides inside its face at the side's middle, found on
    the surface by the middle of its ends' parameters (a neighbour sharing a
    split side is split with it, so the mesh stays watertight); a triangle
    none of whose sides can be split (each on the part's edges, a seam or a
    pole) at its centre. The part's edges are never split, so the faces stay
    welded as they were. Returns the mesh, owners and parameters, and each
    triangle's distance measured from the surface.
    """
    shape_faces = [TopoDS.Face(f) for f in faces(shape)]
    surfaces: dict[int, Any] = {}
    vertices, corners = (
        np.asarray(mesh.vertices, dtype=np.float64),
        np.asarray(mesh.faces, dtype=np.int64),
    )
    owner, uv = np.asarray(owner, dtype=np.int64), np.asarray(uv, dtype=np.float64)
    allowed = np.asarray(enough, dtype=np.float64)

    def enough_for(k: int) -> float:
        return float(allowed[k] if allowed.ndim else allowed)

    def measure(which: NDArray[np.int64]) -> Array:
        out = np.zeros(len(which))
        samples = _samples(vertices[corners[which]])
        params = fv.matmul(_WEIGHTS, uv[which])
        for k in np.unique(owner[which]):
            mine = owner[which] == k
            found = _face_deviation(
                shape_faces[int(k)],
                samples[mine].reshape(-1, 3),
                params[mine].reshape(-1, 2),
                enough_for(int(k)),
            )
            out[mine] = found.reshape(-1, len(_WEIGHTS)).max(axis=1)
        return out

    def on_surface(k: int, at: Array) -> Array:
        if k not in surfaces:
            surfaces[k] = BRepAdaptor_Surface(shape_faces[k], False)
        p = gp_Pnt()
        surfaces[k].D0(float(at[0]), float(at[1]), p)
        return _xyz(p)

    deviations = measure(np.arange(len(corners)))
    for _ in range(rounds):
        bad = np.flatnonzero(deviations > (allowed[owner] if allowed.ndim else allowed))
        if not bad.size:
            break
        before = float(deviations.max())
        vertices, corners, owner, uv, deviations, fresh = _split(
            vertices, corners, owner, uv, deviations, bad, on_surface
        )
        deviations[fresh] = measure(fresh)
        if float(deviations.max()) > _GAINS * before:
            break  # what is left is on the part's edges (their own discretisation), which splitting can't reach
    return Mesh(vertices, corners), owner, uv, deviations


#: A round of splitting that leaves the worst triangle more than this of what it was gains nothing more.
_GAINS = 0.75


def refined(shape: Any, mesh: Mesh, owner: NDArray[np.int64], uv: Array, enough: float | Array, *,
            sound: bool = True) -> tuple[Mesh, NDArray[np.int64], Array, float | None, MeshView]:  # fmt: skip
    """:func:`refined_each`, with the largest distance measured from the surface."""
    fine, fine_owner, fine_uv, each, view = refined_each(
        shape, mesh, owner, uv, enough, sound=sound
    )
    return (
        fine,
        fine_owner,
        fine_uv,
        None if each is None else float(each.max(initial=0.0)),
        view,
    )


def refined_each(shape: Any, mesh: Mesh, owner: NDArray[np.int64], uv: Array, enough: float | Array, *,
                 sound: bool = True) -> tuple[Mesh, NDArray[np.int64], Array, Array | None, MeshView]:  # fmt: skip
    """:func:`refine_each`'s mesh if it is sound (or soundness isn't asked), else OpenCascade's own; and its view.

    Splitting puts new points on the surface, beside the part's edges as the
    mesher discretised them; where those are much coarser than ``enough``
    the new triangles can fold through a neighbour's. Then the mesh as made
    is kept, measured afresh (the distances from the surface returned are
    None), for remaking finer. A mesh unsound as made is refused.
    """
    fine, fine_owner, fine_uv, near = refine_each(shape, mesh, owner, uv, enough)
    view = MeshView(fine, source="mesh-file", deflection=0.0)
    if not sound or view.topology().sound:
        return fine, fine_owner, fine_uv, near, view
    view = MeshView(mesh, source="mesh-file", deflection=0.0)
    topology = view.topology()
    if not topology.sound:
        # Each face's tolerance, where given, shown as the finest and the coarsest (an array has no place in a message).
        raise OperationError("OpenCascade's mesh of the part is not watertight",
                             enough=(float(np.min(enough)), float(np.max(enough))),
                             open_edges=topology.open_edges, bad_edges=topology.bad_edges)  # fmt: skip
    return mesh, owner, uv, None, view


#: The sides of a triangle, as pairs of its corners.
_SIDES = ((0, 1), (1, 2), (2, 0))


def _split(vertices: Array, corners: NDArray[np.int64], owner: NDArray[np.int64], uv: Array, deviations: Array,
           bad: NDArray[np.int64], on_surface: Any) -> tuple[Array, NDArray[np.int64], NDArray[np.int64], Array, Array,
                                                             NDArray[np.int64]]:  # fmt: skip
    """One round of :func:`refine`: the bad triangles split, and their neighbours along the sides split."""
    n = len(corners)
    ends = np.concatenate(
        [corners[:, [a, b]] for a, b in _SIDES]
    )  # side s of triangle t at s * n + t
    ends_uv = np.concatenate([uv[:, [a, b]] for a, b in _SIDES])
    flip = ends[:, 0] > ends[:, 1]
    key = np.where(flip[:, None], ends[:, ::-1], ends)
    key_uv = np.where(flip[:, None, None], ends_uv[:, ::-1], ends_uv)
    sides, side_of, count = np.unique(
        key, axis=0, return_inverse=True, return_counts=True
    )
    side_of = side_of.reshape(-1)
    # A side can be split where it lies inside one face: two triangles of that face, which read its ends'
    # parameters alike (on a seam or at a pole they don't; on the part's edges the faces differ).
    first = np.full(len(sides), -1, dtype=np.int64)
    second = np.full(len(sides), -1, dtype=np.int64)
    for h in range(3 * n):
        s = side_of[h]
        if first[s] < 0:
            first[s] = h
        else:
            second[s] = h
    splittable = (count == 2) & (second >= 0)
    both = np.flatnonzero(splittable)
    t1, t2 = first[both] % n, second[both] % n
    alike = (owner[t1] == owner[t2]) & np.all(
        key_uv[first[both]] == key_uv[second[both]], axis=(1, 2)
    )
    splittable[both[~alike]] = False
    triangle_sides = side_of.reshape(3, n).T  # (n, 3): each triangle's sides
    chosen = np.zeros(len(sides), dtype=bool)
    centred: list[int] = []
    for t in bad.tolist():
        mine = triangle_sides[t][splittable[triangle_sides[t]]]
        if mine.size:
            chosen[mine] = True
        else:
            centred.append(t)
    new_points: list[Array] = []
    middle = np.full(len(sides), -1, dtype=np.int64)
    middle_uv = np.zeros((len(sides), 2))
    for s in np.flatnonzero(chosen).tolist():
        h = first[s]
        t = h % n
        at = key_uv[h].mean(axis=0)
        middle[s] = len(vertices) + len(new_points)
        middle_uv[s] = at
        new_points.append(on_surface(int(owner[t]), at))
    centre: dict[int, tuple[int, Array]] = {}
    for t in centred:
        at = uv[t].mean(axis=0)
        centre[t] = (len(vertices) + len(new_points), at)
        new_points.append(on_surface(int(owner[t]), at))
    vertices = np.concatenate([vertices, np.asarray(new_points).reshape(-1, 3)])
    touched = np.flatnonzero(
        chosen[triangle_sides].any(axis=1) | np.isin(np.arange(n), centred)
    )
    keep = np.ones(n, dtype=bool)
    keep[touched] = False
    made_corners: list[list[int]] = []
    made_uv: list[Array] = []
    made_owner: list[int] = []
    for t in touched.tolist():
        a, b, c = corners[t].tolist()
        pa, pb, pc = uv[t]
        children: list[tuple[tuple[int, Array], ...]]
        if t in centre:
            g, pg = centre[t]
            children = [
                ((a, pa), (b, pb), (g, pg)),
                ((b, pb), (c, pc), (g, pg)),
                ((c, pc), (a, pa), (g, pg)),
            ]
        else:
            split = [bool(chosen[triangle_sides[t][i]]) for i in range(3)]
            mids = [
                (int(middle[triangle_sides[t][i]]), middle_uv[triangle_sides[t][i]])
                for i in range(3)
            ]
            children = _children([(a, pa), (b, pb), (c, pc)], split, mids, vertices)
        for child in children:
            made_corners.append([v for v, _ in child])
            made_uv.append(np.array([q for _, q in child]))
            made_owner.append(int(owner[t]))
    fresh = np.arange(int(keep.sum()), int(keep.sum()) + len(made_corners))
    corners = np.concatenate(
        [corners[keep], np.asarray(made_corners, dtype=np.int64).reshape(-1, 3)]
    )
    uv = np.concatenate([uv[keep], np.asarray(made_uv).reshape(-1, 3, 2)])
    owner = np.concatenate([owner[keep], np.asarray(made_owner, dtype=np.int64)])
    deviations = np.concatenate([deviations[keep], np.full(len(made_corners), np.nan)])
    return vertices, corners, owner, uv, deviations, fresh


def _children(corner: list[tuple[int, Array]], split: list[bool], mids: list[tuple[int, Array]],
              vertices: Array) -> list[tuple[tuple[int, Array], ...]]:  # fmt: skip
    """A triangle's pieces, its corners in its own turning order, for the sides split (side i from corner i to i + 1)."""
    k = sum(split)
    if k == 3:
        m0, m1, m2 = mids
        a, b, c = corner
        return [(a, m0, m2), (m0, b, m1), (m2, m1, c), (m0, m1, m2)]
    # Turned so the split sides come first: side 0 for one, sides 0 and 1 for two.
    turn = next(i for i in range(3) if split[i] and (k == 1 or split[(i + 1) % 3]))
    a, b, c = (corner[(turn + j) % 3] for j in range(3))
    m0, m1 = mids[turn], mids[(turn + 1) % 3]
    if k == 1:
        return [(a, m0, c), (m0, b, c)]
    # Two: the corner between them cut off, and the rest by the shorter diagonal.
    if fv.norm(vertices[a[0]] - vertices[m1[0]]) <= fv.norm(
        vertices[m0[0]] - vertices[c[0]]
    ):
        return [(m0, b, m1), (a, m0, m1), (a, m1, c)]
    return [(m0, b, m1), (a, m0, c), (m0, m1, c)]


def mesh_part(
    shape: Any, tolerance: ExportTolerance | None = None, *, sound: bool = True
) -> PartMesh:
    """A mesh of the part measured within its tolerance of its exact surface, or refused; closed and oriented too, unless ``sound`` is False (a mesh only measured from).

    Each face is meshed, refined and measured to its own tolerance
    (:func:`face_tolerances`): ``tolerance.linear``, or finer where a finer
    box asks for it.
    """
    tolerance = tolerance if tolerance is not None else ExportTolerance()
    allowed = face_tolerances(shape, tolerance)
    scale = 1.0
    view = BrepView(shape)
    found: list[float] = []
    for _ in range(REMESHES + 1):
        deflection = allowed * scale if tolerance.finer else tolerance.linear * scale
        made = _triangulate(shape, deflection, tolerance.angular)
        mesh, owner, uv, near, mesh_view = refined_each(
            shape, *made, allowed / 2.0, sound=sound
        )
        by_face, measured = deviations(shape, mesh.vertices[mesh.faces], owner, uv, enough=allowed / 2.0,
                                       view=view, mesh_view=mesh_view, mesh_to_surface=near)  # fmt: skip
        found.append(float((by_face / allowed).max(initial=0.0)) * tolerance.linear)
        if np.all(by_face <= allowed):
            return PartMesh(mesh, owner, uv, float(by_face.max(initial=0.0)), tolerance.linear * scale, measured,
                            allowed if tolerance.finer else None)  # fmt: skip
        scale /= 2.0
    raise OperationError("the part's mesh stays further from its surface than the tolerance", tolerance=tolerance.linear,
                         measured=[round(w, 6) for w in found])  # fmt: skip


# --- STL and 3MF -----------------------------------------------------------------------


def file_view(mesh: Mesh, tolerance: ExportTolerance) -> MeshView:
    """A mesh file's view as the judge has it: each triangle as far from the true surface as :meth:`ExportTolerance.of_triangles` works out, from the spec alone."""
    if not tolerance.finer:
        return MeshView(mesh, source="mesh-file", deflection=tolerance.linear)
    each = tolerance.of_triangles(mesh.vertices[mesh.faces])
    return MeshView(mesh, source="mesh-file", deflection=each)


def stl_bytes(mesh: Mesh, name: str = "forge part") -> bytes:
    """A binary STL of the mesh, in millimetres."""
    corners = mesh.vertices[mesh.faces]
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    lengths = fv.norm(normals, axis=1)
    normals = np.where(
        lengths[:, None] > 0.0,
        normals / np.where(lengths > 0.0, lengths, 1.0)[:, None],
        0.0,
    )
    header = f"Forge STL, millimetres: {name}".encode("ascii", "replace")[:80].ljust(
        80, b" "
    )
    record = np.zeros(
        len(corners), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]
    )
    record["n"] = normals
    record["v"] = corners
    return header + struct.pack("<I", len(corners)) + record.tobytes()


def plate_shift(mesh: Mesh) -> tuple[float, float, float]:
    """The translation putting the part on the plate: its lowest point at z = 0."""
    return 0.0, 0.0, -float(mesh.vertices[:, 2].min())


def threemf_bytes(mesh: Mesh, name: str, shift: tuple[float, float, float]) -> bytes:
    """A 3MF of one part, in millimetres, its build item moving it by ``shift``."""
    import lib3mf

    wrapper = lib3mf.get_wrapper()
    model = wrapper.CreateModel()
    model.SetUnit(lib3mf.ModelUnit.MilliMeter)
    part = model.AddMeshObject()
    part.SetName(name)
    vertices = []
    for v in mesh.vertices:
        p = lib3mf.Position()
        p.Coordinates[0], p.Coordinates[1], p.Coordinates[2] = (float(c) for c in v)
        vertices.append(p)
    triangles = []
    for f in mesh.faces:
        t = lib3mf.Triangle()
        t.Indices[0], t.Indices[1], t.Indices[2] = (int(i) for i in f)
        triangles.append(t)
    part.SetGeometry(vertices, triangles)
    if not part.IsManifoldAndOriented():
        raise OperationError("lib3mf finds the part's mesh not closed and oriented")
    placement = lib3mf.Transform()
    for i in range(4):
        for j in range(3):
            placement.Fields[i][j] = 1.0 if i == j else 0.0
    for j in range(3):
        placement.Fields[3][j] = float(shift[j])
    model.AddBuildItem(part, placement)
    return bytes(model.QueryWriter("3mf").WriteToBuffer())


@dataclass(frozen=True)
class MeshFileCheck:
    """What reading a mesh file back found."""

    kind: str
    triangles: int
    deviation: float
    volume: tuple[float, float]
    exact_volume: float


def check_mesh_file(data: bytes, shape: Any, part: PartMesh, tolerance: ExportTolerance, *,
                    shift: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> MeshFileCheck:  # fmt: skip
    """Read an STL or 3MF back with ``forge_checks``' own reader and hold it to the exact part (moved by ``shift``)."""
    try:
        found = read_3mf(data) if data[:4] == b"PK\x03\x04" else read_stl(data)
    except MeshFileError as error:
        raise OperationError(f"the file written can't be read back: {error}") from error
    if found.kind == "3mf" and found.unit != "millimeter":
        raise OperationError("the 3MF read back isn't in millimetres", unit=found.unit)
    if len(found.triangles) != len(part.face):
        raise OperationError("the file read back has another number of triangles",
                             written=len(part.face), read=len(found.triangles))  # fmt: skip
    triangles = found.triangles - np.asarray(shift)
    mesh = Mesh.from_triangles(triangles)
    view = file_view(mesh, tolerance)
    topology = view.topology()
    if not topology.sound:
        raise OperationError("the file read back isn't a closed, oriented surface", kind=found.kind,
                             open_edges=topology.open_edges, bad_edges=topology.bad_edges)  # fmt: skip
    exact = volume_interval(shape)
    held = view.volume()
    if not (held.lo <= exact.lo and exact.hi <= held.hi):
        raise OperationError("the file read back doesn't hold the part's volume",
                             exact=[exact.lo, exact.hi], read=[held.lo, held.hi])  # fmt: skip
    allowed = (
        part.tolerance
        if part.tolerance is not None
        else np.full(len(faces(shape)), float(tolerance.linear))
    )
    by_face, _ = deviations(shape, triangles, part.face, part.uv, enough=allowed / 2.0,
                            mesh_view=view.with_deflection(0.0))  # fmt: skip
    worst = float(by_face.max(initial=0.0))
    if np.any(by_face > allowed):
        raise OperationError("the file read back is further from the part's surface than the tolerance",
                             tolerance=tolerance.linear, measured=worst)  # fmt: skip
    # Each triangle within its face's tolerance, so within the one a reader works out for it, or finer.
    if np.any(allowed[part.face] > tolerance.of_triangles(triangles) * (1 + 1e-12)):
        raise OperationError("a triangle read back is held to a finer tolerance than its face was meshed to",
                             tolerance=tolerance.linear)  # fmt: skip
    if found.kind == "3mf":
        # lib3mf holds coordinates and transforms as 32-bit floats: on the plate to their rounding.
        rounding = (
            8.0
            * 2.0**-24
            * (float(np.abs(found.triangles).max()) + float(np.abs(shift).max()))
        )
        if abs(float(found.triangles[:, :, 2].min())) > rounding:
            raise OperationError(
                "the 3MF's part isn't on the plate",
                lowest=float(found.triangles[:, :, 2].min()),
            )
    return MeshFileCheck(
        found.kind,
        len(found.triangles),
        worst,
        (held.lo, held.hi),
        (exact.lo + exact.hi) / 2.0,
    )


# --- STEP ------------------------------------------------------------------------------


@dataclass(frozen=True)
class StepPart:
    """A part written to STEP: its name and its solid (in the part's own coordinates)."""

    name: str
    shape: Any


@dataclass(frozen=True)
class StepInstance:
    """A placed copy of a part in the assembly."""

    name: str
    part: str
    motion: Motion


@dataclass(frozen=True)
class StepFile:
    """A STEP file read back: its parts by name, and its assembly's instances (none for a single part)."""

    parts: dict[str, Any]
    instances: tuple[StepInstance, ...]
    assembly: str | None


def _application() -> Any:
    return XCAFApp_Application.GetApplication_s()


def _document() -> Any:
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    _application().InitDocument(doc)
    return doc


def _name(label: Any, text: str) -> None:
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(text))


def _name_of(label: Any) -> str | None:
    found = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), found):
        return str(found.Get().ToExtString())
    return None


def _step_statics(unit: str) -> None:
    STEPControl_Controller.Init_s()
    for key, value in (
        ("write.step.schema", "AP242DIS"),
        ("write.step.unit", unit),
        ("xstep.cascade.unit", "MM"),
    ):
        if not Interface_Static.SetCVal_s(key, value):
            raise OperationError(
                "OpenCascade's STEP settings could not be set", setting=key, value=value
            )
    # The file's uncertainty is the part's loosest tolerance, not their average: a reader that sets every
    # tolerance from it never takes the part for nearer its true surface than it is.
    if not Interface_Static.SetIVal_s("write.precision.mode", 1):
        raise OperationError(
            "OpenCascade's STEP settings could not be set",
            setting="write.precision.mode",
        )


#: How near a closed face's split may bring the part's corners (mm): its new edges no shorter, its new corners no
#: nearer each other. Well over what a reader holds a corner to: twice the loosest tolerance a step's solid may carry
#: is 2e-4 mm, and a reader widened a vertex at the end of a split's 6e-5 mm edge to 1.9e-4 mm (generated part 1130).
SPLIT_CLEARANCE = 1e-3

#: The splits tried, each until one is clear of the part's corners and reads back tight: in halves, thirds, quarters,
#: fifths, sixths, sevenths. A face is split across the middle of its parameters first, and a part's features often sit
#: right there (a hole at a round angle); part 1130, its holes carried, read back loose halved, in thirds and in fifths,
#: and tight in quarters.
_SPLIT_POINTS = (1, 2, 3, 4, 5, 6)


def exchanged(shape: Any) -> Any:
    """The part as it is written to STEP: each face that closes on itself (round a seam) split apart.

    The same solid, its faces' surfaces unchanged; only where a face met
    itself along a seam it is two faces meeting along two edges. A face whose
    outline crosses its surface's seam (a sphere joined to another along a
    circle the sphere's axis doesn't stand square to) is read back wrong by
    older readers: FreeCAD 0.19, on OpenCascade 7.5, made of three fused
    balls one ball and two solids, and of a dumbbell a third of it lost. Split,
    both read back whole.

    A face is split in halves; where the cut passes a corner of the part
    nearer than :data:`SPLIT_CLEARANCE` (the cut made an edge or brought two
    corners nearer than that, and nearer than the part itself has any),
    in thirds, then quarters, and so on (:data:`_SPLIT_POINTS`). Generated part 7250: halved, a tube's outer
    face was cut 3.2e-5 mm from where a hole met it, and read back, the
    corner at the cut's end was held 6.2e-5 mm loosely, over its neighbour;
    the part read back met itself there. Where no split is clear, or one
    leaves anything but a valid solid of the same volume, the part is
    written as it is.

    Each split is also written and read back: one that reads back held more
    loosely than a step's solid may be, or not a valid solid, gives way to
    the next (part 1130, its holes carried: halves, thirds and fifths loose,
    quarters tight).

    The split is made of a copy: the faces the split leaves whole share
    their edges with the part, and making the new edges' curves agree with
    their faces would change the tolerances of those shared ones (generated
    part 1749: 112 of its tolerances, 36 made finer), so writing a part
    would change the part written.
    """
    clear: float | None = None
    for points in _SPLIT_POINTS:
        split = _closed_split(shape, points)
        if split is None:
            return shape
        if clear is None:
            clear = min(SPLIT_CLEARANCE, _clearance(shape))
        if (
            _clearance(split) >= clear
            and _sound_split(shape, split)
            and _reads_back(split, loosest_tolerance(shape))
        ):
            return split
    return shape


def _reads_back(split: Any, at_least: float) -> bool:
    """Whether the split part, written to STEP alone, reads back a valid solid held no more loosely than a step's
    solid may be (V2-stage3.md, 12: part 1130's halves, rebuilt with its holes carried, read back 3.4e-4 mm loose)."""
    from .aftercheck import too_loose

    data = _step_bytes([StepPart("part", split)], (), None, "MM", at_least=at_least)
    return all(
        is_valid(back) and not too_loose(loosest_tolerance(back))
        for back in read_step(data).parts.values()
    )


def _closed_split(shape: Any, points: int) -> Any | None:
    """A copy of the part, each face that closes on itself split at ``points`` places; None where none does."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.BRepLib import BRepLib
    from OCP.ShapeUpgrade import ShapeUpgrade_ShapeDivideClosed

    with boundary("splitting closed faces for STEP"):
        divider = ShapeUpgrade_ShapeDivideClosed(
            BRepBuilderAPI_Copy(shape, True, False).Shape()
        )
        divider.SetNbSplitPoints(points)
        if not divider.Perform():
            return None
        split = divider.Result()
        # The pieces' new edges get their curves on the faces either side made to agree, as a checker asks.
        BRepLib.SameParameter_s(split, 1e-7, True)
    return split


def _sound_split(shape: Any, split: Any) -> bool:
    """Whether the split part is the part: a valid solid (as many), held no more loosely than a step's solid may be
    once each new edge's tolerance is what its curves need along the whole edge (the file states the loosest), and of
    the same volume."""
    from .aftercheck import too_loose
    from .occt import loosest_tolerance, widened_to_curves

    if (
        split.IsNull()
        or not is_valid(split)
        or len(solids(split)) != len(solids(shape))
    ):
        return False
    widened_to_curves(split)
    if too_loose(loosest_tolerance(split)):
        return False
    before, after = properties(shape).volume, properties(split).volume
    return abs(after - before) <= 1e-9 * max(abs(before), 1.0)


def _clearance(shape: Any) -> float:
    """How near the part brings two of its corners (mm): its shortest edge, and its two nearest corners (distinct
    vertices; inf where it has neither)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_AbscissaPoint

    from .occt import edges, vertices

    nearest = math.inf
    with boundary("measuring how near a part's corners are"):
        for edge in edges(shape):
            if not BRep_Tool.Degenerated_s(edge):
                nearest = min(
                    nearest, GCPnts_AbscissaPoint.Length_s(BRepAdaptor_Curve(edge))
                )
        found = vertices(shape)
        corners = np.array(
            [[p.X(), p.Y(), p.Z()] for p in (BRep_Tool.Pnt_s(v) for v in found)],
            dtype=np.float64,
        )
    for start in range(0, len(corners) - 1, 128):
        block = corners[start : start + 128]
        apart = fv.norm(block[:, None, :] - corners[None, start + 1 :, :], axis=2)
        # Each corner against the ones after it only (itself and those before are measured already).
        later = (
            np.arange(start + 1, len(corners))[None, :]
            > np.arange(start, start + len(block))[:, None]
        )
        if later.any():
            nearest = min(nearest, float(np.min(apart[later])))
    return nearest


def write_step(parts: Sequence[StepPart], instances: Sequence[StepInstance] = (), *, assembly: str | None = None,
               unit: str = "MM") -> bytes:  # fmt: skip
    """A STEP file (AP242) of the parts, as one assembly of ``instances`` when there are any.

    Each face that closes on itself split in two (:func:`exchanged`), unless
    the file so written reads back held more loosely anywhere than a step's
    solid may be (:func:`~.aftercheck.too_loose`), or not a valid solid
    (generated part 3500: a plane and a cylinder of the halves read back with
    their wires turned against each other, though the split part was valid
    and its file read back loosely nowhere): then the parts as they are.
    """
    from .aftercheck import too_loose
    from .occt import loosest_tolerance

    if not parts:
        raise ValueError("a STEP file needs a part")
    if instances and not assembly:
        raise ValueError("an assembly needs a name")
    at_least = max(loosest_tolerance(part.shape) for part in parts)
    split = [StepPart(part.name, exchanged(part.shape)) for part in parts]
    data = _step_bytes(split, instances, assembly, unit, at_least=at_least)
    if all(s.shape is p.shape for s, p in zip(split, parts, strict=True)):
        return data
    back = read_step(data).parts.values()
    if not any(
        too_loose(loosest_tolerance(shape)) or not is_valid(shape) for shape in back
    ):
        return data
    return _step_bytes(parts, instances, assembly, unit, at_least=at_least)


def _step_bytes(parts: Sequence[StepPart], instances: Sequence[StepInstance], assembly: str | None,
                unit: str, *, at_least: float = 0.0) -> bytes:  # fmt: skip
    """The STEP file of the parts as they are given.

    Its uncertainty is their loosest tolerance, and no less than
    ``at_least``: the parts' as built, when these are their split copies,
    whose edges may be held more tightly (V2-stage3.md, 12).
    """
    doc = _document()
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels: dict[str, Any] = {}
    stated = _stated(max(at_least, *(loosest_tolerance(part.shape) for part in parts)), unit)
    with boundary("writing STEP"):
        for part in parts:
            label = tool.AddShape(part.shape, False, False)
            _name(label, part.name)
            labels[part.name] = label
        if instances:
            root = tool.NewShape()
            _name(root, str(assembly))
            for instance in instances:
                component = tool.AddComponent(
                    root, labels[instance.part], TopLoc_Location(instance.motion.trsf())
                )
                _name(component, instance.name)
            tool.UpdateAssemblies()
        _step_statics(unit)
        if not (
            Interface_Static.SetIVal_s("write.precision.mode", 2)
            and Interface_Static.SetRVal_s("write.precision.val", stated)
        ):
            raise OperationError(
                "OpenCascade's STEP settings could not be set",
                setting="write.precision.val",
            )
        writer = STEPCAFControl_Writer()
        writer.SetNameMode(True)
        if not writer.Transfer(doc):
            raise OperationError("OpenCascade could not translate the parts to STEP")
        handle, path = tempfile.mkstemp(suffix=".step")
        os.close(handle)
        try:
            if writer.Write(path) != IFSelect_RetDone:
                raise OperationError("OpenCascade could not write the STEP file")
            with open(path, "rb") as source:
                return source.read()
        finally:
            os.unlink(path)


def read_step(data: bytes) -> StepFile:
    """A STEP file read back in millimetres: its parts (by name) and its assembly's instances."""
    _step_statics("MM")
    doc = _document()
    handle, path = tempfile.mkstemp(suffix=".step")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        with boundary("reading STEP"):
            reader = STEPCAFControl_Reader()
            reader.SetNameMode(True)
            if reader.ReadFile(path) != IFSelect_RetDone:
                raise OperationError("OpenCascade could not read the STEP file")
            if not reader.Transfer(doc):
                raise OperationError("OpenCascade could not translate the STEP file")
    finally:
        os.unlink(path)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    free = TDF_LabelSequence()
    tool.GetFreeShapes(free)
    parts: dict[str, Any] = {}
    instances: list[StepInstance] = []
    assembly: str | None = None
    for i in range(1, free.Length() + 1):
        label = free.Value(i)
        if not tool.IsAssembly_s(label):
            parts[_name_of(label) or f"part {i}"] = tool.GetShape_s(label)
            continue
        assembly = _name_of(label)
        components = TDF_LabelSequence()
        tool.GetComponents_s(label, components)
        for j in range(1, components.Length() + 1):
            component = components.Value(j)
            referred = TDF_Label()
            tool.GetReferredShape_s(component, referred)
            part = _name_of(referred) or f"part {j}"
            parts.setdefault(part, tool.GetShape_s(referred))
            instances.append(
                StepInstance(
                    _name_of(component) or part,
                    part,
                    _motion(tool.GetLocation_s(component)),
                )
            )
    uncertainty = _uncertainty(data)
    for shape in parts.values():
        _measured_tolerances(shape, uncertainty)
    return StepFile(parts, tuple(instances), assembly)


def _stated(loosest: float, unit: str) -> float:
    """The uncertainty a STEP file states for its parts' loosest tolerance (mm): rounded up to what OpenCascade writes,
    six significant figures in the file's unit, so the file never states the part nearer its true surface than it is
    (generated part 0: a tolerance of 3.2656402e-06 mm written as 3.26564E-06)."""
    scale = 25.4 if unit == "INCH" else 1.0
    if not (math.isfinite(loosest) and loosest > 0.0):
        return loosest
    six = Context(prec=6, rounding=ROUND_CEILING)
    written = six.plus(Decimal(loosest / scale))
    while float(written) * scale < loosest:  # read back in millimetres, a hair under it: the next figure up
        written = six.next_plus(written)
    return float(written) * scale


#: A STEP file's stated uncertainty: its length measure (the file is in millimetres; check_step holds it to that).
_UNCERTAINTY = re.compile(
    rb"UNCERTAINTY_MEASURE_WITH_UNIT\s*\(\s*LENGTH_MEASURE\s*\(\s*([-+0-9.Ee]+)\s*\)"
)


def _uncertainty(data: bytes) -> float:
    """The loosest uncertainty a STEP file states, in millimetres (0 where it states none)."""
    found = [abs(float(m.group(1))) for m in _UNCERTAINTY.finditer(data)]
    scale = 25.4 if b"'INCH'" in data else 1.0
    return scale * max([0.0, *(u for u in found if math.isfinite(u))])


def _measured_tolerances(shape: Any, uncertainty: float = 0.0) -> None:
    """Give a part read from STEP the tolerances its geometry has: none finer than the file states, and each edge's and
    vertex's as far as its curves stray from its faces' surfaces and from each other.

    A STEP file holds exact curves and surfaces and one uncertainty for the
    whole file (Forge writes the part's loosest tolerance), and a reader
    sets tolerances its own way: an edge where two cylinders cross (its
    curve an approximation, 8e-6 mm off one of them) came back stating
    1e-7 mm, and a face's outline closing a gap of 1e-6 mm at a corner with
    it. A view of the part would then claim its surface nearer the truth
    than it is. Floored at the file's uncertainty, and measured edge by edge
    (each curve against its faces' along the whole edge, as
    :func:`~.occt.widened_to_curves` does: the reader's curves on faces,
    made again to follow their edges, stray most between the points it
    compares; each vertex against its edges' ends), the tolerances are the
    file's own.
    """
    from OCP.BRepLib import BRepLib
    from OCP.ShapeFix import ShapeFix_Edge, ShapeFix_ShapeTolerance
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    from .occt import widened_to_curves

    with boundary("measuring a STEP part's tolerances"):
        if uncertainty > 0.0:
            ShapeFix_ShapeTolerance().LimitTolerance(shape, uncertainty, 0.0)
        BRepLib.SameParameter_s(shape, 1e-7, True)
    widened_to_curves(shape)
    with boundary("measuring a STEP part's tolerances"):
        fixer = ShapeFix_Edge()
        explorer = TopExp_Explorer(shape, TopAbs_EDGE)
        while explorer.More():
            fixer.FixVertexTolerance(TopoDS.Edge(explorer.Current()))
            explorer.Next()
        BRepLib.UpdateTolerances_s(shape, False)


def _motion(location: Any) -> Motion:
    trsf = location.Transformation()
    rows = [[trsf.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)]
    translation = trsf.TranslationPart()
    return Motion.of(
        np.asarray(rows), (translation.X(), translation.Y(), translation.Z())
    )


def _face_kinds(shape: Any, *, written: bool = False) -> Counter[str]:
    """How many faces of each kind the part has; ``written``: as a STEP reader makes them, a spindle torus (its tube wider than its ring) the surface of revolution it is ("other")."""
    kinds = Counter(f.kind for f in BrepView(shape).faces())
    if written:
        spindles = sum(1 for face in faces(shape) if _spindle(face))
        kinds["torus"] -= spindles
        kinds["other"] += spindles
    return +kinds


def _spindle(face: Any) -> bool:
    """Whether a face lies on a spindle torus: one whose minor radius is more than its major (a corner where a rounding tighter than another's, and more than half as wide, turns round it)."""
    surface = BRepAdaptor_Surface(TopoDS.Face(face))
    if surface.GetType() != GeomAbs_Torus:
        return False
    torus = surface.Torus()
    return bool(torus.MinorRadius() > torus.MajorRadius())


@dataclass(frozen=True)
class StepCheck:
    """What reading a STEP file back found, per part: how far each property came back (relative)."""

    parts: dict[str, dict[str, float]]
    instances: int


def check_step(data: bytes, parts: Sequence[StepPart], instances: Sequence[StepInstance] = (), *,
               assembly: str | None = None) -> tuple[StepFile, StepCheck]:  # fmt: skip
    """Read a STEP file back and hold it to what was written."""
    if b"SI_UNIT(.MILLI.,.METRE.)" not in data or b"CONVERSION_BASED_UNIT" in data:
        raise OperationError("the STEP file doesn't say millimetres")
    found = read_step(data)
    if set(found.parts) != {p.name for p in parts}:
        raise OperationError("the STEP file read back has other parts", written=sorted(p.name for p in parts),
                             read=sorted(found.parts))  # fmt: skip
    report: dict[str, dict[str, float]] = {}
    for part in parts:
        back = found.parts[part.name]
        if len(solids(back)) != len(solids(part.shape)):
            raise OperationError("a part read back has another number of solids", part=part.name,
                                 written=len(solids(part.shape)), read=len(solids(back)))  # fmt: skip
        if not is_valid(back):
            raise OperationError(
                "a part read back from STEP is invalid", part=part.name
            )
        written: Properties = properties(part.shape)
        differences = written.differences(properties(back))
        if max(differences.values()) > STEP_MATCH:
            raise OperationError("a part read back from STEP isn't the part written", part=part.name,
                                 differences={k: f"{v:.2e}" for k, v in differences.items()})  # fmt: skip
        # Its closed faces split in two, or (where the split read back loose or invalid) as it is: see write_step.
        kinds = _face_kinds(back)
        sent = [_face_kinds(exchanged(part.shape), written=True),
                _face_kinds(part.shape, written=True)]  # fmt: skip
        if kinds not in sent:
            raise OperationError("a part read back from STEP has other faces", part=part.name,
                                 written=dict(sent[0]), read=dict(kinds))  # fmt: skip
        report[part.name] = differences
    if (found.assembly or None) != (assembly if instances else None):
        raise OperationError("the STEP file's assembly came back under another name", written=assembly,
                             read=found.assembly)  # fmt: skip
    if [(i.name, i.part) for i in found.instances] != [
        (i.name, i.part) for i in instances
    ]:
        raise OperationError("the STEP file's instances came back otherwise",
                             written=[(i.name, i.part) for i in instances],
                             read=[(i.name, i.part) for i in found.instances])  # fmt: skip
    for back, written_instance in zip(found.instances, instances, strict=True):
        if not _same_motion(back.motion, written_instance.motion):
            raise OperationError(
                "an instance's placement came back otherwise",
                instance=written_instance.name,
            )
    return found, StepCheck(report, len(found.instances))


def _same_motion(a: Motion, b: Motion) -> bool:
    return bool(np.allclose(a.matrix, b.matrix, atol=PLACEMENT_MATCH, rtol=0.0)
                and np.allclose(a.translation, b.translation, atol=PLACEMENT_MATCH * 1e3, rtol=0.0))  # fmt: skip
