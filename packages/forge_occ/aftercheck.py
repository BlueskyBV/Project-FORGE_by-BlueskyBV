"""After every step: is it a valid solid, and did the operation do what it should (docs/V2-stage3.md, section 8).

**Every step** (:func:`validate`): the result is a solid or a compound of
solids, non-empty and valid by ``BRepCheck_Analyzer``; its volume is finite
and positive; no shell is open; every solid encloses positive volume; and no
face, edge or vertex carries a tolerance above 1e-4 mm (a checker passes a
vertex whose tolerance OpenCascade widened over a gap of centimetres).

**What each operation must do**: each builder states what it expects (a
volume interval, a wall at a distance, a face per edge rounded) and the
checks here hold it to that. A failure says the operation did not do what it
should, and what was expected and found; not whose fault it is.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.collections import (
    IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedDataMapOfShapeListOfShape,
)
from OCP.collections import (
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape,
)
from OCP.gp import gp_Pnt, gp_Pnt2d
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS

from .errors import AfterCheckError, InvalidResultError
from .make import compound
from .occt import boundary, faces, is_valid, loosest_tolerance, solids, volume

__all__ = [
    "TOLERANCE",
    "VOLUME",
    "blend_bounds",
    "blend_section",
    "check_blend",
    "check_distance",
    "check_volume",
    "points_on",
    "too_loose",
    "validate",
]

#: How closely a volume must meet what the operation expects (relative), beyond integration error.
VOLUME = 1e-6
#: The loosest tolerance a step's solid may carry anywhere (mm). OpenCascade widens a vertex's or
#: an edge's tolerance to cover any gap it finds; a wide one is a gap nothing else reports.
TOLERANCE = 1e-4


def too_loose(tolerance: float) -> bool:
    """Whether OpenCascade holds a shape more loosely than :data:`TOLERANCE`: above it, not at it (a tolerance it sets to 1e-4 carries its own rounding, 1.0000000000000003e-4)."""
    return tolerance > TOLERANCE * (1.0 + 1e-9)


def validate(shape: Any) -> float:
    """The checks every step's result must pass; its volume."""
    if shape is None or shape.IsNull():
        raise InvalidResultError("the operation made nothing")
    found = solids(shape)
    if not found:
        raise InvalidResultError("the operation made no solid")
    if not is_valid(shape):
        raise InvalidResultError(
            "the operation made an invalid solid (BRepCheck_Analyzer rejects it)"
        )
    if open_edges(shape):
        raise InvalidResultError(
            "the operation left a shell open", open_edges=open_edges(shape)
        )
    loosest = loosest_tolerance(shape)
    if too_loose(loosest):
        raise InvalidResultError(
            "the operation made a solid OpenCascade holds only loosely: a tolerance of "
            f"{loosest:.3g} mm on it, where at most {TOLERANCE:g} mm is accepted", tolerance=loosest)  # fmt: skip
    for solid in found:
        v = volume(solid)
        if not (math.isfinite(v) and v > 0.0):
            raise InvalidResultError(
                "the operation made a solid with no volume, or inside out", volume=v
            )
    return (
        volume(found[0])
        if len(found) == 1 and found[0].IsSame(shape)
        else volume(shape)
    )


def open_edges(shape: Any) -> int:
    """Edges that bound one face only (a seam, which bounds its face twice, and a degenerate edge excepted)."""
    around = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, around)
    count = 0
    for i in range(1, around.Extent() + 1):
        edge = TopoDS.Edge(around.FindKey(i))
        if BRep_Tool.Degenerated_s(edge):
            continue
        adjacent: list[Any] = []
        for face in around.FindFromIndex(i):
            if not any(face.IsSame(f) for f in adjacent):
                adjacent.append(face)
        if len(adjacent) == 1 and not BRep_Tool.IsClosed_s(
            edge, TopoDS.Face(adjacent[0])
        ):
            count += 1
    return count


def check_volume(shape: Any, expected: tuple[float, float], why: str) -> None:
    """The shape's volume is within ``expected`` (lo, hi), widened by :data:`VOLUME` relative."""
    v = volume(shape)
    lo, hi = expected
    slack = VOLUME * max(abs(lo), abs(hi), abs(v)) + 1e-9
    if not lo - slack <= v <= hi + slack:
        raise AfterCheckError(
            f"the operation did not do what it should: {why}",
            volume=round(v, 9),
            expected=[round(lo, 9), round(hi, 9)],
        )


def points_on(shape: Any, per_face: int = 16) -> Any:
    """Points spread over every face of ``shape``, inside each face's trimming (for measuring walls)."""
    out = []
    for face in faces(shape):
        f = TopoDS.Face(face)
        surface = BRepAdaptor_Surface(f)
        u0, u1, v0, v1 = (surface.FirstUParameter(), surface.LastUParameter(),
                          surface.FirstVParameter(), surface.LastVParameter())  # fmt: skip
        classifier = BRepClass_FaceClassifier()
        side = max(2, math.ceil(math.sqrt(per_face)) + 1)
        for i in range(side):
            for j in range(side):
                u = u0 + (u1 - u0) * (i + 0.5) / side
                v = v0 + (v1 - v0) * (j + 0.5) / side
                classifier.Perform(f, gp_Pnt2d(u, v), BRep_Tool.Tolerance_s(f))
                if classifier.State() not in (TopAbs_IN,):
                    continue
                p = surface.Value(u, v)
                out.append((p.X(), p.Y(), p.Z()))
    return np.asarray(out, dtype=np.float64).reshape(-1, 3)


def distances_to(points: Any, shape: Any) -> Any:
    """Each point's distance to the faces of ``shape`` (not to its inside: a point inside a solid is at the surface's distance)."""
    target = compound(faces(shape))
    found = np.empty(len(points))
    with boundary("measuring distances"):
        meter = BRepExtrema_DistShapeShape()
        meter.LoadS2(target)
        for k, p in enumerate(points):
            meter.LoadS1(BRepBuilderAPI_MakeVertex(gp_Pnt(*p)).Vertex())
            meter.Perform()
            if not meter.IsDone():
                raise AfterCheckError("a distance could not be measured")
            found[k] = meter.Value()
    return found


def check_distance(
    points: Any, shape: Any, expected: float, tolerance: float, why: str
) -> None:
    """Every point is ``expected`` from the faces of ``shape``, to ``tolerance``."""
    if not len(points):
        raise AfterCheckError(
            f"the operation did not do what it should: {why} (no surface to measure)"
        )
    d = distances_to(points, shape)
    worst = float(np.max(np.abs(d - expected)))
    if worst > tolerance:
        k = int(np.argmax(np.abs(d - expected)))
        raise AfterCheckError(
            f"the operation did not do what it should: {why}",
            expected=expected,
            found=round(float(d[k]), 6),
            at=[round(float(c), 4) for c in points[k]],
        )


#: Points along an edge where its faces' angle, its convexity and its curvature are measured.
_ALONG = 9
#: Faces meeting within this angle of flat move almost nothing either way, and their side isn't probed.
_FLAT = math.radians(3.0)


def blend_section(alpha: float, size: float, *, bevel: bool) -> float:
    """The area a fillet of radius ``size`` (or a chamfer of distance ``size``) moves across an edge whose faces meet at ``alpha``.

    A fillet: the kite between the edge and the two tangent lines, less the
    arc's sector, r²(cot(θ/2) - (π - θ)/2), θ the angle the faces meet at. A
    chamfer: the triangle its cut makes, c² sin(θ)/2.
    """
    alpha = min(max(alpha, 1e-3), math.pi - 1e-9)
    if bevel:
        return size * size * math.sin(alpha) / 2.0
    return size * size * (1.0 / math.tan(alpha / 2.0) - (math.pi - alpha) / 2.0)


def blend_bounds(
    shape: Any, edges: Sequence[Any], sizes: Sequence[float], *, bevel: bool
) -> tuple[float, float]:
    """The most volume rounding (or chamfering) these edges of ``shape`` by these sizes can remove, and the most it can add.

    Each edge moves at most its section (:func:`blend_section`, at the least
    angle its faces meet at along it) times its length, the length taken on
    the far side of a curved edge (by 1 + κ·reach, reach how far from the
    edge the blend's faces start). A ridge (faces meeting convex) loses
    material, a crease gains it; an edge that is both along its length, or
    whose side can't be told, counts both ways. Where blends meet or end at a
    corner, each corner adds the cube four reaches wide round it.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.BRepLProp import BRepLProp_CLProps, BRepLProp_SLProps
    from OCP.GCPnts import GCPnts_AbscissaPoint
    from OCP.TopAbs import TopAbs_OUT, TopAbs_REVERSED

    around = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, around)
    classifier = BRepClass3d_SolidClassifier(shape)
    removed = added = 0.0
    corners: dict[int, tuple[float, set[str]]] = {}
    vertex_index = TopTools_IndexedMapOfShape()
    for edge, size in zip(edges, sizes, strict=True):
        if size <= 0.0:
            continue
        edge = TopoDS.Edge(edge)
        k = around.FindIndex(edge)
        adjacent: list[Any] = []
        if k >= 1:
            for face in around.FindFromIndex(k):
                if not any(face.IsSame(f) for f in adjacent):
                    adjacent.append(face)
        if len(adjacent) != 2 or BRep_Tool.Degenerated_s(edge):
            return (
                math.inf,
                math.inf,
            )  # not an edge between two faces: nothing can be said
        curve = BRepAdaptor_Curve(edge)
        t0, t1 = curve.FirstParameter(), curve.LastParameter()
        length = GCPnts_AbscissaPoint.Length_s(curve)
        pcurves = [BRepAdaptor_Curve2d(edge, TopoDS.Face(f)) for f in adjacent]
        surfaces = [BRepAdaptor_Surface(TopoDS.Face(f)) for f in adjacent]
        least, bend, kinds = math.pi, 0.0, set()
        for i in range(_ALONG):
            t = t0 + (t1 - t0) * (i + 0.5) / _ALONG
            props = BRepLProp_CLProps(curve, t, 2, 1e-9)
            p = props.Value()
            if props.IsTangentDefined():
                bend = max(bend, abs(props.Curvature()))
            normals = []
            for face, pcurve, surface in zip(adjacent, pcurves, surfaces, strict=True):
                uv = pcurve.Value(t)
                local = BRepLProp_SLProps(surface, uv.X(), uv.Y(), 1, 1e-9)
                if not local.IsNormalDefined():
                    break
                n = local.Normal()
                normal = np.array([n.X(), n.Y(), n.Z()])
                normals.append(
                    -normal if face.Orientation() == TopAbs_REVERSED else normal
                )
            if len(normals) != 2:
                kinds |= {"ridge", "crease"}
                least = min(least, 1e-3)
                continue
            c = float(np.clip(normals[0] @ normals[1], -1.0, 1.0))
            alpha = math.pi - math.acos(c)
            least = min(least, alpha)
            # Probe a point outside the first face's plane and inside the second's, a fiftieth of the size
            # off each: air at a ridge, material in a crease.
            off = size / 50.0
            if math.pi - alpha < _FLAT:
                kinds |= {"ridge", "crease"}
                continue
            q = np.array([p.X(), p.Y(), p.Z()]) + off / (1.0 - c) * (
                normals[0] - normals[1]
            )
            classifier.Perform(gp_Pnt(*q), off / 100.0)
            state = classifier.State()
            kinds |= (
                {"ridge"}
                if state == TopAbs_OUT
                else {"crease"}
                if state == TopAbs_IN
                else {"ridge", "crease"}
            )
        reach = size if bevel else size / math.tan(max(least, 1e-3) / 2.0)
        moved = blend_section(least, size, bevel=bevel) * length * (1.0 + bend * reach)
        if "ridge" in kinds:
            removed += moved
        if "crease" in kinds:
            added += moved
        for vertex in (TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge)):
            j = vertex_index.Add(vertex)
            widest, sides = corners.get(j, (0.0, set()))
            corners[j] = (max(widest, reach), sides | kinds)
    for widest, sides in corners.values():
        cube = (4.0 * widest) ** 3
        removed += cube if "ridge" in sides else 0.0
        added += cube if "crease" in sides else 0.0
    return removed, added


def check_blend(
    shape: Any, before: float, bounds: tuple[float, float], why: str
) -> None:
    """The volume moved the right way and no further than ``bounds`` (removed at most, added at most) allow."""
    removed, added = bounds
    check_volume(shape, (before - removed, before + added), why)


# --- what each operation must do ---------------------------------------------------------


def _volumes(inputs: Sequence[Any]) -> list[float]:
    return [volume(p.shape) for p in inputs if getattr(p, "kind", "") == "solid"]


def check_step(op: str, params: Any, inputs: Sequence[Any], product: Any) -> None:
    """Hold the step's result to what its operation must do (section 8.2)."""
    shape = product.shape
    if product.expect is not None:
        lo, hi, why = product.expect
        check_volume(shape, (lo, hi), why)
    p = params
    v_in = _volumes(inputs)
    if op == "cylinder":
        r, h = float(p["diameter"]) / 2.0, float(p["height"])
        check_volume(shape, (math.pi * r * r * h,) * 2, "a cylinder's volume is πr²h")
    elif op == "cone":
        r1, r2, h = (
            float(p["bottom_diameter"]) / 2.0,
            float(p["top_diameter"]) / 2.0,
            float(p["height"]),
        )
        v = math.pi * h * (r1 * r1 + r1 * r2 + r2 * r2) / 3.0
        check_volume(shape, (v, v), "a cone's volume is πh(r₁² + r₁r₂ + r₂²)/3")
    elif op == "sphere":
        r = float(p["diameter"]) / 2.0
        check_volume(
            shape, (4.0 / 3.0 * math.pi * r**3,) * 2, "a sphere's volume is 4πr³/3"
        )
    elif op == "torus":
        big, small = float(p["diameter"]) / 2.0, float(p["tube_diameter"]) / 2.0
        check_volume(
            shape,
            (2.0 * math.pi**2 * big * small * small,) * 2,
            "a ring's volume is 2π²Rr²",
        )
    elif op == "box":
        x, y, z = (float(c) for c in p["size"])
        rounded = (
            float(p.get("edge_radius") or 0.0) > 0.0
            or float(p.get("edge_chamfer") or 0.0) > 0.0
        )
        check_volume(
            shape,
            (0.0 if rounded else x * y * z, x * y * z),
            "a box's volume is its sides' product",
        )
    elif op == "wedge":
        x, y, z = (float(c) for c in p["size"])
        check_volume(shape, (x * y * z / 2.0,) * 2, "a wedge is half its box")
    elif op == "union":
        check_volume(shape, (max(v_in), sum(v_in)) if not _blended(p) else (0.0, math.inf),
                     "a union holds its largest operand and no more than all of them")  # fmt: skip
    elif op == "subtract" and not _blended(p):
        check_volume(shape, (v_in[0] - sum(v_in[1:]), v_in[0]),
                     "a cut keeps no more than the body, and loses no more than its tools")  # fmt: skip
    elif op == "intersect" and not _blended(p):
        check_volume(
            shape,
            (0.0, min(v_in)),
            "an intersection is no larger than its smallest operand",
        )
    elif op == "transform":
        check_volume(shape, (v_in[0], v_in[0]), "a move keeps the volume")
        if len(faces(shape)) != len(faces(inputs[0].shape)):
            raise AfterCheckError(
                "the operation did not do what it should: a move kept its faces"
            )
    elif op == "mirror":
        keep = bool(p.get("keep_original", True))
        check_volume(shape, (v_in[0], 2.0 * v_in[0]) if keep else (v_in[0], v_in[0]),
                     "a mirror holds the original, and its image no larger")  # fmt: skip
    elif op in ("pattern_linear", "pattern_circular"):
        n = int(p["count"])
        check_volume(
            shape,
            (v_in[0], n * v_in[0]),
            "a pattern holds its source, and no more than n copies",
        )


def _blended(p: Any) -> bool:
    return (
        float(p.get("blend_radius") or 0.0) > 0.0
        or float(p.get("chamfer") or 0.0) > 0.0
    )
