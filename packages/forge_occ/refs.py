"""References by query: faces and edges found by what made them, told apart by geometry, held to a match (docs/V2-stage3.md, 6.2, 9.4).

1. Candidates: the faces carrying ``(created_by, role)``; for edges, the
   edges of those faces, or the edges between the two sets.
2. ``where`` keeps the candidates that pass every test; each one dropped is
   recorded with the test it failed.
3. For a fillet or chamfer, the edges are closed under tangency: an edge
   meeting a chosen one smoothly is added (OpenCascade would round it
   anyway), and the trace says so.
4. ``match``: the count must be in range, and ``covers`` hold.

Otherwise :class:`~forge_occ.errors.RefError`, listing every candidate, its
geometry, and why it was kept or dropped: never "take the first one".
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from forge_ir.v2 import EdgeQuery, FaceQuery, Match, Reference, Where
from forge_numeric import vector as fv
from OCP.Bnd import Bnd_Box
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.collections import (
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape,
)
from OCP.GeomAbs import (
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Line,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
from OCP.TopoDS import TopoDS

from .errors import RefError
from .occt import boundary, box_limits, edges, plane_of
from .products import SolidProduct

__all__ = [
    "Resolved",
    "describe_edge",
    "describe_face",
    "resolve_edges",
    "resolve_faces",
    "resolve_reference",
]

LENGTH = 1e-6
ANGLE = 1e-9

_SURFACES = {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone",
             GeomAbs_Sphere: "sphere", GeomAbs_Torus: "torus"}  # fmt: skip
_CURVES = {GeomAbs_Line: "line", GeomAbs_Circle: "circle"}


def _xyz(v: Any) -> Any:
    return np.array([v.X(), v.Y(), v.Z()], dtype=np.float64)


@dataclass(frozen=True)
class Facts:
    """What a face or edge is, for the tests: its kind, axis or normal, radius, a point on its axis, its box."""

    kind: str
    axis: Any | None
    radius: float | None
    point: Any | None
    lo: Any
    hi: Any

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.axis is not None:
            out["axis"] = [round(float(c), 6) for c in self.axis]
        if self.radius is not None:
            out["radius_mm"] = round(self.radius, 6)
        out["box"] = [
            [round(float(c), 4) for c in self.lo],
            [round(float(c), 4) for c in self.hi],
        ]
        return out


def _box(shape: Any) -> tuple[Any, Any]:
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, bounds, False, False)
    x0, y0, z0, x1, y1, z1 = box_limits(bounds)
    return np.array([x0, y0, z0]), np.array([x1, y1, z1])


def describe_face(face: Any) -> Facts:
    surface = BRepAdaptor_Surface(TopoDS.Face(face))
    kind = _SURFACES.get(surface.GetType(), "other")
    axis = radius = point = None
    if kind == "plane":
        found = plane_of(face)
        assert found is not None
        point, axis = np.array(found[0]), np.array(found[1])
    elif kind in ("cylinder", "cone", "sphere", "torus"):
        geometry = {"cylinder": surface.Cylinder, "cone": surface.Cone, "sphere": surface.Sphere,
                    "torus": surface.Torus}[kind]()  # fmt: skip
        if kind == "sphere":
            point = _xyz(geometry.Location())
            radius = float(geometry.Radius())
        else:
            axis = _xyz(geometry.Axis().Direction())
            point = _xyz(geometry.Axis().Location())
            if kind == "cylinder":
                radius = float(geometry.Radius())
            elif kind == "torus":
                radius = float(geometry.MinorRadius())
    lo, hi = _box(face)
    return Facts(kind, axis, radius, point, lo, hi)


def describe_edge(edge: Any) -> Facts:
    curve = BRepAdaptor_Curve(TopoDS.Edge(edge))
    kind = _CURVES.get(curve.GetType(), "other")
    axis = radius = point = None
    if kind == "line":
        line = curve.Line()
        axis, point = _xyz(line.Direction()), _xyz(line.Location())
    elif kind == "circle":
        circle = curve.Circle()
        axis, point, radius = (
            _xyz(circle.Axis().Direction()),
            _xyz(circle.Location()),
            float(circle.Radius()),
        )
    lo, hi = _box(edge)
    return Facts(kind, axis, radius, point, lo, hi)


def _fails(facts: Facts, where: Where) -> str | None:
    """Which test of ``where`` these facts fail, or None."""
    if where.kind is not None and facts.kind != where.kind:
        return f"kind is {facts.kind}, not {where.kind}"
    if where.axis is not None:
        wanted = np.asarray(where.axis) / fv.norm(where.axis)
        if facts.axis is None or facts.kind == "plane":
            return (
                "has no axis" if facts.axis is None else "is a plane, not round an axis"
            )
        if abs(abs(float(fv.matmul(facts.axis, wanted))) - 1.0) > ANGLE:
            return "its axis runs another way"
    if where.normal is not None:
        wanted = np.asarray(where.normal) / fv.norm(where.normal)
        if (
            facts.kind != "plane"
            or facts.axis is None
            or float(fv.matmul(facts.axis, wanted)) < 1.0 - ANGLE
        ):
            return "doesn't face that way"
    if where.radius_mm is not None and (
        facts.radius is None or abs(facts.radius - where.radius_mm) > LENGTH
    ):
        return f"radius is {facts.radius}, not {where.radius_mm}"
    if where.centre is not None:
        c = np.asarray(where.centre, dtype=np.float64)
        if facts.kind not in ("circle", "sphere") or facts.point is None:
            return f"is a {facts.kind}, which has no centre"
        if float(fv.norm(c - facts.point)) > LENGTH:
            return "its centre isn't the point"
    if where.through is not None:
        p = np.asarray(where.through, dtype=np.float64)
        if facts.point is None:
            return "has no axis or plane to pass through the point"
        if facts.kind == "plane" and facts.axis is not None:
            if abs(float(fv.matmul(p - facts.point, facts.axis))) > LENGTH:
                return "its plane misses the point"
        elif facts.axis is not None:
            off = p - facts.point
            if float(fv.norm(off - (fv.matmul(off, facts.axis)) * facts.axis)) > LENGTH:
                return "its axis misses the point"
        elif float(fv.norm(p - facts.point)) > LENGTH:
            return "its centre isn't the point"
    return None


def _side(
    items: list[tuple[Any, Facts]], side: str
) -> tuple[list[tuple[Any, Facts]], list[tuple[Any, Facts]]]:
    end, axis = side.split("_")
    k = "xyz".index(axis)
    if end == "max":
        best = max(float(f.hi[k]) for _, f in items)
        return ([i for i in items if float(i[1].hi[k]) >= best - LENGTH],
                [i for i in items if float(i[1].hi[k]) < best - LENGTH])  # fmt: skip
    best = min(float(f.lo[k]) for _, f in items)
    return ([i for i in items if float(i[1].lo[k]) <= best + LENGTH],
            [i for i in items if float(i[1].lo[k]) > best + LENGTH])  # fmt: skip


@dataclass(frozen=True)
class Resolved:
    faces: tuple[Any, ...] = ()
    edges: tuple[Any, ...] = ()
    notes: tuple[str, ...] = ()


def _outside(facts: Facts, where: Where) -> float:
    """How far a piece's box reaches past ``where.within`` (0 within it)."""
    if where.within is None:
        return 0.0
    lo, hi = (np.asarray(c, dtype=np.float64) for c in where.within)
    return float(max(np.max(lo - facts.lo), np.max(facts.hi - hi), 0.0))


def _clear_of(facts: Facts, where: Where) -> bool:
    """Whether a piece's box is clear of ``where.within``: apart from it by more than :data:`LENGTH` along some axis."""
    if where.within is None:
        return False
    lo, hi = (np.asarray(c, dtype=np.float64) for c in where.within)
    return bool(np.any(facts.lo > hi + LENGTH) or np.any(facts.hi < lo - LENGTH))


def _filter(
    items: list[tuple[Any, Facts]], where: Where, dropped: list[dict[str, Any]]
) -> list[tuple[Any, Facts]]:
    """The items passing ``where``; each one dropped recorded in ``dropped`` with the test it failed."""
    kept = []
    for item in items:
        why = _fails(item[1], where)
        if why is None:
            kept.append(item)
        else:
            dropped.append({**item[1].summary(), "dropped": why})
    if where.side is not None and kept:
        kept, gone = _side(kept, where.side)
        dropped.extend(
            {**f.summary(), "dropped": f"not the {where.side}"} for _, f in gone
        )
    return kept


def _candidate_faces(part: SolidProduct, query: FaceQuery) -> list[Any]:
    return part.names.faces_named(query.created_by, query.role)


def resolve_faces(part: SolidProduct, query: FaceQuery) -> Resolved:
    """The faces a face query finds, held to its match if it has one."""
    found = [(f, describe_face(f)) for f in _candidate_faces(part, query)]
    dropped: list[dict[str, Any]] = []
    kept = _filter(found, query.where, dropped)
    if query.match is not None:
        _check(query.match, [f for _, f in kept], dropped, what=f"faces {query.created_by}.{query.role}",
               pointer=query.pointer, edges_=None, named=(f"{query.created_by}.{query.role}",))  # fmt: skip
    return Resolved(faces=tuple(f for f, _ in kept))


def _unique(shapes: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    for s in shapes:
        if not any(s.IsSame(t) for t in out):
            out.append(s)
    return out


def _named(faces: tuple[FaceQuery, ...]) -> str:
    return " or ".join(f"{q.created_by}.{q.role}" for q in faces)


def resolve_edges(
    part: SolidProduct, query: EdgeQuery, *, tangent: bool = False
) -> Resolved:
    """The edges an edge query finds (closed under tangency if asked), held to its match."""
    found, dropped, what = _edge_candidates(part, query)
    kept = found
    notes: list[str] = []
    chosen = [e for e, _ in kept]
    if tangent and chosen:
        closed = _tangent_closure(part.shape, chosen)
        added = [e for e in closed if not any(e.IsSame(c) for c in chosen)]
        if added:
            notes.append(f"{len(added)} edges added that meet the chosen ones smoothly")
            kept += [(e, describe_edge(e)) for e in added]
            chosen = closed
    _check(query.match, [f for _, f in kept], dropped, what=what, pointer=query.pointer,
           edges_=[e for e, _ in kept], named=tuple(f"{q.created_by}.{q.role}" for q in query.faces))  # fmt: skip
    return Resolved(edges=tuple(chosen), notes=tuple(notes))


def _edge_candidates(
    part: SolidProduct, query: EdgeQuery
) -> tuple[list[tuple[Any, Facts]], list[dict[str, Any]], str]:
    """The pieces an edge query finds before its match: (pieces, those dropped, what it names)."""
    if query.of is not None:
        faces = [f for q in query.of for f, _ in _filtered_faces(part, q)]
        candidates = _unique([e for f in faces for e in edges(f)])
        what = f"edges of {_named(query.of)}"
    else:
        assert query.between is not None
        a = [f for q in query.between[0] for f, _ in _filtered_faces(part, q)]
        b = [f for q in query.between[1] for f, _ in _filtered_faces(part, q)]
        in_b = TopTools_IndexedMapOfShape()
        for f in b:
            for e in edges(f):
                in_b.Add(e)
        candidates = _unique([e for f in a for e in edges(f) if in_b.Contains(e)])
        what = (
            f"edges between {_named(query.between[0])} and {_named(query.between[1])}"
        )
    found = [(e, describe_edge(e)) for e in candidates]
    dropped: list[dict[str, Any]] = []
    kept = _filter(found, query.where, dropped)
    # A piece wholly clear of the stretch meant is another edge on the same line or circle
    # (an outline's two sides in line, between the same two faces): not this one.
    elsewhere = [(e, f) for e, f in kept if _clear_of(f, query.where)]
    dropped.extend(
        {**f.summary(), "dropped": "elsewhere on its line or circle"}
        for _, f in elsewhere
    )
    kept = [(e, f) for e, f in kept if not _clear_of(f, query.where)]
    past = [(f, _outside(f, query.where)) for _, f in kept]
    beyond = [(f, d) for f, d in past if d > LENGTH]
    if beyond:
        raise RefError(
            f"{what}: an edge runs {max(d for _, d in beyond):.6g} mm past the stretch the reference "
            "means (onto what is joined to it)",
            found=[f.summary() for f, _ in beyond], pointer=query.pointer,
            within=[list(c) for c in query.where.within or ()],
            named=[f"{q.created_by}.{q.role}" for q in query.faces],
        )  # fmt: skip
    return kept, dropped, what


def resolve_reference(
    part: SolidProduct, reference: Reference, *, tangent: bool = False
) -> Resolved:
    """The edges a reference finds: one query (as :func:`resolve_edges`), or several made at once.

    Several (:class:`~forge_ir.v2.EdgeQueries`): each query is held to its
    own match on the pieces it finds, their union to ``at_least``, and then
    the union is closed under tangency once. An edge the closure adds that
    no query found is refused: the compiler that wrote the queries names
    every edge the definitions round (docs/V2-stage4.md 4.7), so an edge it
    didn't name would be rounded unasked.
    """
    if isinstance(reference, EdgeQuery):
        return resolve_edges(part, reference, tangent=tangent)
    chosen: list[Any] = []
    for query in reference.queries:
        kept, dropped, what = _edge_candidates(part, query)
        _check(query.match, [f for _, f in kept], dropped, what=what, pointer=query.pointer,
               edges_=[e for e, _ in kept], named=tuple(f"{q.created_by}.{q.role}" for q in query.faces))  # fmt: skip
        chosen += [e for e, _ in kept]
    chosen = _unique(chosen)
    if len(chosen) < reference.at_least:
        raise RefError(
            f"the queries together found {len(chosen)} edges, and at least {reference.at_least} are asked for",
            pointer=reference.pointer, named=sorted({s for q in reference.queries for s in q.steps}),
        )  # fmt: skip
    notes: list[str] = []
    if tangent and chosen:
        closed = _tangent_closure(part.shape, chosen)
        added = [e for e in closed if not any(e.IsSame(c) for c in chosen)]
        if added:
            raise RefError(
                f"{len(added)} edges meet the chosen ones smoothly and no query names them: "
                "rounding them would round what the spec doesn't ask",
                pointer=reference.pointer, found=[describe_edge(e).summary() for e in added[:20]],
            )  # fmt: skip
    return Resolved(edges=tuple(chosen), notes=tuple(notes))


def _filtered_faces(part: SolidProduct, query: FaceQuery) -> list[tuple[Any, Facts]]:
    found = [(f, describe_face(f)) for f in _candidate_faces(part, query)]
    dropped: list[dict[str, Any]] = []
    return _filter(found, query.where, dropped)


def _tangent_closure(shape: Any, chosen: Sequence[Any]) -> list[Any]:
    """The chosen edges with every edge OpenCascade's fillet would run on to along tangents."""
    with boundary("following tangent edges"):
        maker = BRepFilletAPI_MakeFillet(shape)
        for edge in chosen:
            maker.Add(1.0, TopoDS.Edge(edge))
        out: list[Any] = []
        for contour in range(1, maker.NbContours() + 1):
            out.extend(
                maker.Edge(contour, i) for i in range(1, maker.NbEdges(contour) + 1)
            )
    return _unique([*chosen, *out])


def _check(match: Match, kept: list[Facts], dropped: list[dict[str, Any]], *, what: str, pointer: str,
           edges_: list[Any] | None, named: tuple[str, ...] = ()) -> None:  # fmt: skip
    lo, hi = match.count
    detail = {
        "found": [f.summary() for f in kept],
        "dropped": dropped[:20],
        "pointer": pointer,
        "named": list(named),
    }
    if not lo <= len(kept) <= hi:
        raise RefError(
            f"{what}: found {len(kept)}, the reference allows {lo} to {hi}", **detail
        )
    if match.covers == "whole" and dropped:
        raise RefError(
            f"{what}: `where` left some out, and the reference asks for the whole of it",
            **detail,
        )
    if match.covers == "full_circle":
        if any(f.kind != "circle" for f in kept):
            raise RefError(
                f"{what}: a full circle is made of arcs, and these aren't all arcs",
                **detail,
            )
        first = kept[0]
        same = all(
            f.radius is not None and first.radius is not None and abs(f.radius - first.radius) <= LENGTH
            and f.point is not None and first.point is not None
            and float(fv.norm(f.point - first.point)) <= LENGTH
            and f.axis is not None and first.axis is not None
            and abs(abs(float(fv.matmul(f.axis, first.axis))) - 1.0) <= ANGLE
            for f in kept
        )  # fmt: skip
        if not same:
            raise RefError(f"{what}: the arcs aren't all on one circle", **detail)
        total = 0.0
        for edge in edges_ or ():
            curve = BRepAdaptor_Curve(TopoDS.Edge(edge))
            total += curve.LastParameter() - curve.FirstParameter()
        if abs(total - 2.0 * math.pi) > 1e-6:
            raise RefError(f"{what}: the arcs go {math.degrees(total):.4g} degrees round, not all the way",
                           **detail)  # fmt: skip
