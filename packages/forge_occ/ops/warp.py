"""V1's bend wrap applied to a zone that isn't a prism (a hole or slot crosses it): every face, edge and vertex mapped (docs/V2-stage3.md, 7.3).

A copy of the zone is changed in place, geometry only (its topology, and so
its faces' names, unchanged):

- every vertex moves to its image;
- every edge's curve is refitted through its mapped points at its own
  parameters (:mod:`forge_occ.fit`), and every face's surface likewise, so
  each face's trimming curves keep their meaning;
- the zone's two cut faces, and the edges and vertices on them, move exactly:
  the first not at all, the last by the rigid motion the part past the zone
  gets, so the zone meets the parts either side of it exactly.

The fit's largest error is measured and becomes the step's stated tolerance.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from forge_numeric import vector as fv
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepLib import BRepLib
from OCP.BRepTools import BRepTools
from OCP.collections import (
    IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedDataMapOfShapeListOfShape,
)
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopAbs import TopAbs_FORWARD as _FORWARD
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

from ..errors import InvalidResultError
from ..fit import fit_curve, fit_surface
from ..names import Names
from ..occt import boundary, edges, faces, is_valid, vertices
from ..products import SolidProduct

__all__ = ["wrapped"]

#: How closely a mapped curve or surface must follow the map (mm).
FIT = 1e-6


def _map(spec: Any, points: Any) -> Any:
    """V1's zone wrap, vectorised: flat points of the zone to their bent places."""
    e1, e2, e3 = spec.frame
    origin = np.asarray(spec.position, dtype=np.float64)
    rel = np.asarray(points, dtype=np.float64).reshape(-1, 3) - origin
    x, y, z = fv.matmul(rel, e1), fv.matmul(rel, e2), fv.matmul(rel, e3)
    inside, _, start, middle = spec.layout
    cx, cz = start, inside + spec.radius
    phi = (x - start) / middle
    r = cz - z
    out_x = cx + r * fv.sin(phi)
    out_z = cz - r * fv.cos(phi)
    return origin + np.outer(out_x, e1) + np.outer(y, e2) + np.outer(out_z, e3)


def _on_cut(spec: Any, x_cut: float, shape: Any) -> bool:
    """Whether every vertex of ``shape`` lies on the cut plane x = x_cut."""
    e1 = spec.frame[0]
    origin = np.asarray(spec.position)
    for v in vertices(shape):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex(v))
        if (
            abs(float(fv.matmul(np.array([p.X(), p.Y(), p.Z()]) - origin, e1)) - x_cut)
            > 1e-7
        ):
            return False
    return True


def _closes(surface: Any, direction: str, span: float) -> bool:
    """Whether a face spans its periodic surface's whole period in ``direction`` (it closes on itself there)."""
    periodic = surface.IsUPeriodic() if direction == "u" else surface.IsVPeriodic()
    if not periodic:
        return False
    period = float(surface.UPeriod() if direction == "u" else surface.VPeriod())
    return abs(span - period) <= 1e-9 * max(1.0, period)


def wrapped(step: str, zone: SolidProduct, spec: Any) -> tuple[SolidProduct, float]:
    """The zone bent by V1's wrap, and the fit's largest error (mm)."""
    _, _, start, middle = spec.layout
    end = start + middle * spec.angle
    past = spec.past_motion()
    with boundary("copying a bend's zone"):
        shape = BRepBuilderAPI_Copy(zone.shape, True, False).Shape()
    builder = BRep_Builder()
    worst = 0.0
    zone_faces = faces(shape)

    def kind_of(sub: Any) -> str:
        if _on_cut(spec, start, sub):
            return "start"
        if _on_cut(spec, end, sub):
            return "end"
        return "zone"

    # 1. Every face's curves on its surface, read before any surface changes. Read and written
    # against the face turned forward: OpenCascade's reading of a seam's two curves follows the
    # face's orientation, and its writing doesn't, so on a reversed face they would swap.
    pcurves: list[tuple[Any, Any, Any, Any | None]] = []
    # And each face's parameters' bounds, which are read from those curves.
    bounds = [BRepTools.UVBounds_s(TopoDS.Face(face)) for face in zone_faces]
    for face in zone_faces:
        f = TopoDS.Face(face.Oriented(_FORWARD))
        for edge in edges(f):
            e = TopoDS.Edge(edge.Oriented(_FORWARD))
            if BRep_Tool.IsClosed_s(e, f):
                forward = BRep_Tool.CurveOnSurface_s(e, f, 0.0, 0.0)
                backward = BRep_Tool.CurveOnSurface_s(
                    TopoDS.Edge(e.Reversed()), f, 0.0, 0.0
                )
                pcurves.append((f, e, forward, backward))
            else:
                pcurves.append((f, e, BRep_Tool.CurveOnSurface_s(e, f, 0.0, 0.0), None))

    # The old curves on the old surfaces go: left in the edges' lists of curves they would still
    # be found by what reads every curve of an edge (tolerances, which they would inflate by as
    # far as the bend moves the face), though no face's surface is theirs any more.
    for f, e, _, backward in pcurves:
        tolerance = BRep_Tool.Tolerance_s(e)
        if backward is not None:
            builder.UpdateEdge(e, None, None, f, tolerance)
        else:
            builder.UpdateEdge(e, None, f, tolerance)

    # 2. Surfaces.
    for face, box in zip(zone_faces, bounds, strict=True):
        f = TopoDS.Face(face)
        where = kind_of(f)
        surface = BRep_Tool.Surface_s(f)
        if where == "start":
            continue
        if where == "end":
            new = surface.Transformed(past.trsf())
        else:
            u0, u1, v0, v1 = box
            adaptor = BRepAdaptor_Surface(f, False)
            # A little beyond the face's own bounds, so its outline lies inside the new surface
            # rather than on its border (OpenCascade classifies a face's wires by a point outside them);
            # but exactly round a face that closes on itself (a bore round its seam), so the new
            # surface closes too, its seam on its two borders: a surface running on past its seam
            # holds the seam's two curves inside it, and a STEP reader, finding the seam's place
            # on it again, finds one of them twice (the face read back has no area).
            du = 0.0 if _closes(adaptor, "u", u1 - u0) else 0.05 * (u1 - u0)
            dv = 0.0 if _closes(adaptor, "v", v1 - v0) else 0.05 * (v1 - v0)
            u0, u1, v0, v1 = u0 - du, u1 + du, v0 - dv, v1 + dv

            def points(us: Any, vs: Any, adaptor: Any = adaptor) -> Any:
                flat = np.array(
                    [
                        _xyz(adaptor.Value(float(a), float(b)))
                        for a, b in zip(us, vs, strict=True)
                    ]
                )
                return _map(spec, flat)

            fitted = fit_surface(points, (u0, u1), (v0, v1), FIT)
            worst = max(worst, fitted.error)
            new = fitted.geometry
        builder.UpdateFace(f, new, TopLoc_Location(), BRep_Tool.Tolerance_s(f))

    # 3. The curves on the new surfaces: the same curves, the surfaces keeping their parameters.
    for f, e, forward, backward in pcurves:
        if forward is None:
            continue
        tolerance = BRep_Tool.Tolerance_s(e)
        if backward is not None:
            builder.UpdateEdge(e, forward, backward, f, tolerance)
        else:
            builder.UpdateEdge(e, forward, f, tolerance)

    # 4. Edges' own curves.
    for edge in edges(shape):
        e = TopoDS.Edge(edge)
        if BRep_Tool.Degenerated_s(e):
            continue
        where = kind_of(e)
        curve = BRep_Tool.Curve_s(e, 0.0, 0.0)
        if where == "start" or curve is None:
            continue
        if where == "end":
            new = curve.Transformed(past.trsf())
        else:
            adaptor = BRepAdaptor_Curve(e)
            first, last = adaptor.FirstParameter(), adaptor.LastParameter()

            def along(t: float, adaptor: Any = adaptor) -> Any:
                return _map(spec, _xyz(adaptor.Value(t)))[0]

            fitted = fit_curve(along, first, last, FIT)
            worst = max(worst, fitted.error)
            new = fitted.geometry
        builder.UpdateEdge(e, new, TopLoc_Location(), BRep_Tool.Tolerance_s(e))

    # 5. Vertices.
    for vertex in vertices(shape):
        v = TopoDS.Vertex(vertex)
        p = _xyz(BRep_Tool.Pnt_s(v))
        where = kind_of(v)
        if where == "start":
            continue
        q = past.point(p) if where == "end" else _map(spec, p)[0]
        builder.UpdateVertex(v, gp_Pnt(*map(float, q)), BRep_Tool.Tolerance_s(v))

    # Each edge's curve and its curves on its faces are parameterised alike by construction
    # (all are the map of the same points at the same parameters): its tolerance is how far
    # apart they are found, measured, never OpenCascade's re-parameterisation of them.
    worst = max(worst, _settle(shape, builder))
    names = Names(shape, zone.names.table)
    if not is_valid(shape):
        shape, names = _reoriented(shape, names)
    if not is_valid(shape):
        raise InvalidResultError("the bent zone came out invalid", step=step)
    return SolidProduct(shape, names), worst


def _reoriented(shape: Any, names: Names) -> tuple[Any, Names]:
    """The faces' wires re-ordered and re-oriented on their new surfaces, with nothing else allowed to change.

    OpenCascade's checker can find a face's wires unorientable on a refitted
    surface though its shell is closed and consistent. Its shape fixer
    re-orients them; the result is kept only if it has the same faces, each of
    the same area, and the same volume, and each face keeps its names.
    """
    from OCP.ShapeFix import ShapeFix_Shape

    from ..occt import surface_area, volume

    with boundary("orienting a bent zone's faces"):
        fixer = ShapeFix_Shape(shape)
        fixer.Perform()
        fixed = fixer.Shape()
        context = fixer.Context()
    before, after = faces(shape), faces(fixed)
    if len(before) != len(after) or abs(volume(fixed) - volume(shape)) > 1e-9 * abs(
        volume(shape)
    ):
        return shape, names
    table: dict[int, frozenset[Any]] = {}
    index = dict(enumerate(after))
    for old, held in names.items():
        new = context.Apply(old)
        found = [k for k, f in index.items() if f.IsSame(new)]
        if len(found) != 1 or abs(
            surface_area(index[found[0]]) - surface_area(old)
        ) > 1e-9 * max(1.0, surface_area(old)):
            return shape, names
        table[found[0]] = held
    if len(table) != len(after):
        return shape, names
    return fixed, Names(fixed, tuple(table[k] for k in range(len(after))))


def _settle(shape: Any, builder: BRep_Builder) -> float:
    """Every edge's tolerance set to twice the farthest its curve is from its curves on its faces; the farthest found."""
    around = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, around)
    farthest = 0.0
    for i in range(1, around.Extent() + 1):
        e = TopoDS.Edge(around.FindKey(i).Oriented(_FORWARD))
        if BRep_Tool.Degenerated_s(e):
            continue
        curve = BRepAdaptor_Curve(e)
        first, last = curve.FirstParameter(), curve.LastParameter()
        gap = 0.0
        for face in around.FindFromIndex(i):
            f = TopoDS.Face(face.Oriented(_FORWARD))
            for which in (
                (e, TopoDS.Edge(e.Reversed())) if BRep_Tool.IsClosed_s(e, f) else (e,)
            ):
                pcurve = BRep_Tool.CurveOnSurface_s(which, f, 0.0, 0.0)
                surface = BRepAdaptor_Surface(f, False)
                for t in np.linspace(first, last, 33):
                    uv = pcurve.Value(float(t))
                    gap = max(
                        gap,
                        surface.Value(uv.X(), uv.Y()).Distance(curve.Value(float(t))),
                    )
        farthest = max(farthest, gap)
        builder.UpdateEdge(e, max(2.0 * gap, 1e-7))
        builder.SameParameter(e, True)
        builder.SameRange(e, True)
    BRepLib.UpdateTolerances_s(shape, False)
    return farthest


def _xyz(p: Any) -> Any:
    return np.array([p.X(), p.Y(), p.Z()], dtype=np.float64)
