"""Union, subtract and intersect; a blended or chamfered junction rounded as a fillet or chamfer (docs/V2-stage3.md, 7.2, 9.3).

The junction of a boolean is found on its own result, before faces on one
surface are merged: the edges lying between a face that came from exactly one
operand and a face that came from exactly one other, where the two meet at a
crease rather than smoothly. ``blend_radius`` fillets them, ``chamfer``
chamfers them (V1's round-union and round-difference are such a fillet where
the faces meet square).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
from forge_numeric import vector as fv
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.collections import (
    IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedDataMapOfShapeListOfShape,
)
from OCP.collections import (
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape,
)
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS

from ..aftercheck import blend_bounds
from ..errors import DesignError, InvalidResultError, OccError
from ..make import Boolean, Fitted, boolean, one_solid, round_edges, round_fitted, unify
from ..names import Name, carry
from ..occt import boundary, faces, is_valid, solids, volume
from ..products import Context, Product, SolidProduct

__all__ = ["BUILDERS", "combine", "junction"]


def _origins(operands: Sequence[SolidProduct], done: Boolean) -> list[set[int]]:
    """For each face of the result, which operands it came from."""
    result = faces(done.shape)
    index = TopTools_IndexedMapOfShape()
    for face in result:
        index.Add(face)
    origin: list[set[int]] = [set() for _ in result]
    for which, operand in enumerate(operands):
        for face in faces(operand.shape):
            became = done.history.modified(face)
            if not became and not done.history.removed(face):
                became = [face]
            for other in became:
                k = index.FindIndex(other)
                if k >= 1:
                    origin[k - 1].add(which)
    return origin


def _normal_at(face: Any, point: Any) -> Any | None:
    surface = BRep_Tool.Surface_s(TopoDS.Face(face))
    projection = GeomAPI_ProjectPointOnSurf(point, surface)
    if projection.NbPoints() < 1:
        return None
    u, v = projection.LowerDistanceParameters()
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    props = BRepLProp_SLProps(BRepAdaptor_Surface(TopoDS.Face(face)), u, v, 1, 1e-9)
    if not props.IsNormalDefined():
        return None
    n = props.Normal()
    normal = np.array([n.X(), n.Y(), n.Z()])
    if TopoDS.Face(face).Orientation() == TopAbs_REVERSED:
        normal = -normal
    return normal


def junction(operands: Sequence[SolidProduct], done: Boolean) -> list[Any]:
    """The edges between faces from two different operands that meet at a crease."""
    origin = _origins(operands, done)
    result_faces = faces(done.shape)
    index = TopTools_IndexedMapOfShape()
    for face in result_faces:
        index.Add(face)
    around = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(done.shape, TopAbs_EDGE, TopAbs_FACE, around)
    found = []
    for i in range(1, around.Extent() + 1):
        edge = TopoDS.Edge(around.FindKey(i))
        if BRep_Tool.Degenerated_s(edge):
            continue
        adjacent: list[Any] = []
        for face in around.FindFromIndex(i):
            if not any(face.IsSame(other) for other in adjacent):
                adjacent.append(face)
        if len(adjacent) != 2:
            continue
        a, b = (origin[index.FindIndex(f) - 1] for f in adjacent)
        if len(a) != 1 or len(b) != 1 or a == b:
            continue
        curve = BRepAdaptor_Curve(edge)
        middle = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2.0)
        na, nb = (_normal_at(f, middle) for f in adjacent)
        if na is None or nb is None or abs(float(fv.matmul(na, nb))) > 1.0 - 1e-9:
            continue  # meeting smoothly (or flat): no crease to round
        found.append(edge)
    return found


def combine(ctx: Context, kind: str, operands: Sequence[SolidProduct], *, blend: float = 0.0,
            chamfer: float = 0.0) -> SolidProduct:  # fmt: skip
    """``kind`` of the operands (the first the argument, the rest tools), the junction rounded if asked."""
    step = ctx.step
    done = boolean(kind, [operands[0].shape], [o.shape for o in operands[1:]])
    carried = carry([o.names for o in operands], done.shape, done.history,
                    fallback=(Name(step, "other"),))  # fmt: skip
    shape, names = done.shape, carried.names
    lost = set(carried.lost)
    notes: list[str] = []
    expect: tuple[float, float, str] | None = None
    if blend > 0.0 or chamfer > 0.0:
        edges = junction(operands, done)
        if not edges:
            notes.append(
                "the junction to round was not found: the operands don't meet at a crease"
            )
        else:
            role = "bevel" if chamfer > 0.0 else "round"
            failure: OccError | None = None
            try:
                made = round_edges(
                    shape,
                    edges,
                    chamfer if chamfer > 0.0 else blend,
                    bevel=chamfer > 0.0,
                )
                if not is_valid(made.shape):
                    failure = InvalidResultError(
                        "OpenCascade's fillet of the junction is invalid"
                    )
            except OccError as error:
                failure = error
            if failure is None:
                again = carry(
                    [names], made.shape, made.history, lambda _f: (Name(step, role),)
                )
                moved = blend_bounds(
                    done.shape, made.rounded, made.sizes, bevel=chamfer > 0.0
                )
                shape, names = made.shape, again.names
                lost |= again.lost
                notes.append(
                    f"{len(made.rounded)} junction edges {'chamfered' if chamfer else 'rounded'}"
                )
            else:
                size = chamfer if chamfer > 0.0 else blend
                webs = (
                    _webs(done.shape, edges, blend)
                    if kind == "union" and blend > 0.0
                    else None
                )
                fitted = (
                    round_fitted(shape, edges, size, bevel=chamfer > 0.0)
                    if webs is None
                    else None
                )
                if webs is not None:
                    joined = boolean("union", [shape], webs)
                    again = carry(
                        [names],
                        joined.shape,
                        joined.history,
                        lambda _f: (Name(step, role),),
                    )
                    moved = blend_bounds(
                        done.shape, edges, [blend] * len(edges), bevel=False
                    )
                    shape, names = joined.shape, again.names
                    lost |= again.lost
                    notes.append(
                        f"{len(edges)} junction edges rounded as rolling-ball webs (a boss on a face, "
                        "square to it), where OpenCascade's fillet failed"
                    )
                elif fitted is not None and fitted.made is not None:
                    again = carry(
                        [names],
                        fitted.made.shape,
                        fitted.made.history,
                        lambda _f: (Name(step, role),),
                    )
                    moved = blend_bounds(
                        done.shape,
                        fitted.made.rounded,
                        fitted.made.sizes,
                        bevel=chamfer > 0.0,
                    )
                    shape, names = fitted.made.shape, again.names
                    lost |= again.lost
                    notes.append(
                        _fitted_note(
                            fitted, size, "chamfered" if chamfer else "rounded"
                        )
                    )
                else:
                    raise ctx.fail(failure.where(edges=len(edges)))
            # The blend moved volume the right way from the plain result, and no further than it can.
            plain = volume(done.shape)
            expect = (plain - moved[0], plain + moved[1],
                      f"a {kind}'s junction {'chamfered' if chamfer else 'rounded'} moves no more than its section "
                      "along the junction, off a ridge or into a crease")  # fmt: skip
    merged = unify(shape)
    final = carry(
        [names], merged.shape, merged.history, fallback=(Name(step, "other"),)
    )
    solid = one_solid(merged.shape)
    if kind == "subtract" and volume(solid) >= volume(operands[0].shape) * (1.0 - 1e-9):
        notes.append("removed nothing: the tools don't meet the body")
    lumps = len(solids(solid))
    if lumps > 1:
        touch = _shared_edges(solid)
        notes.append(f"the {kind} is {lumps} solids: " + (
            f"they touch only along {touch} edges, without joining" if touch else "they don't touch"))  # fmt: skip
    return SolidProduct(
        solid,
        final.names.on(solid),
        notes=tuple(notes),
        lost=frozenset(lost),
        expect=expect,
    )


def _shared_edges(shape: Any) -> int:
    """How many edges more than two faces meet at: where solids touch along a line without joining."""
    around = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, around)
    count = 0
    for i in range(1, around.Extent() + 1):
        adjacent: list[Any] = []
        for face in around.FindFromIndex(i):
            if not any(face.IsSame(other) for other in adjacent):
                adjacent.append(face)
        count += len(adjacent) > 2
    return count


def _fitted_note(fitted: Fitted, size: float, done: str) -> str:
    """What a fitted rounding did, for the trace."""
    whole = sum(1 for s in fitted.sizes if s == size)
    less = sorted(round(s, 4) for s in fitted.sizes if 0.0 < s < size)
    refused = sum(
        1
        for s, alone in zip(fitted.sizes, fitted.alone, strict=True)
        if s == 0.0 and alone > 0.0
    )
    none = sum(
        1
        for s, alone in zip(fitted.sizes, fitted.alone, strict=True)
        if s == 0.0 and alone == 0.0
    )
    parts = [f"{whole} junction edges {done} by {size:g} mm"]
    if less:
        parts.append(f"{len(less)} by less, the most each takes ({', '.join(f'{s:g}' for s in less)} mm: "
                     "the face beside is narrower)")  # fmt: skip
    if refused:
        parts.append(
            f"{refused} left sharp (rounded alone, they stop the rest rounding: three blends at a corner)"
        )
    if none:
        parts.append(f"{none} left sharp (no size rounds it)")
    return "; ".join(parts)


def _webs(shape: Any, junction_edges: Sequence[Any], radius: float) -> list[Any] | None:
    """The rolling-ball fillet of each junction edge where a convex cylinder stands square on a plane face (a boss on a plate): a turned web, cut to the face's outline. None if any edge isn't such a junction."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol

    from ..geom import Frame, ax1
    from ..make import prism
    from ..profiles import Arc, Line, Profile
    from ..refs import describe_edge, describe_face

    around = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, around)
    webs = []
    for edge in junction_edges:
        k = around.FindIndex(edge)
        adjacent: list[Any] = []
        for face in around.FindFromIndex(k):
            if not any(face.IsSame(f) for f in adjacent):
                adjacent.append(face)
        if len(adjacent) != 2:
            return None
        facts = [describe_face(f) for f in adjacent]
        kinds = sorted(f.kind for f in facts)
        if kinds != ["cylinder", "plane"]:
            return None
        plane_face = adjacent[[f.kind for f in facts].index("plane")]
        plane, cylinder = (
            facts[[f.kind for f in facts].index(k)] for k in ("plane", "cylinder")
        )
        n, along, big, foot = plane.axis, cylinder.axis, cylinder.radius, plane.point
        if n is None or along is None or big is None or foot is None:
            return None
        if abs(abs(float(fv.matmul(along, n))) - 1.0) > 1e-9:
            return None
        curve = describe_edge(edge)
        if (
            curve.kind != "circle"
            or curve.radius is None
            or abs(curve.radius - big) > 1e-6
        ):
            return None
        cyl_face = adjacent[[f.kind for f in facts].index("cylinder")]
        # The boss stands on the face's outer side, and is convex (material inside its cylinder).
        middle = (cylinder.lo + cylinder.hi) / 2.0
        if float(fv.matmul(middle - foot, n)) <= 0.0:
            return None
        if TopoDS.Face(cyl_face).Orientation() == TopAbs_REVERSED:
            return None
        adaptor = BRepAdaptor_Curve(TopoDS.Edge(edge))
        circle = adaptor.Circle()
        t0, t1 = adaptor.FirstParameter(), adaptor.LastParameter()
        centre = np.array(
            [circle.Location().X(), circle.Location().Y(), circle.Location().Z()]
        )
        x_dir = np.array(
            [
                circle.XAxis().Direction().X(),
                circle.XAxis().Direction().Y(),
                circle.XAxis().Direction().Z(),
            ]
        )
        y_dir = np.array(
            [
                circle.YAxis().Direction().X(),
                circle.YAxis().Direction().Y(),
                circle.YAxis().Direction().Z(),
            ]
        )
        axis = np.cross(x_dir, y_dir)
        radial = x_dir * fv.cos(t0) + y_dir * fv.sin(t0)
        r = radius
        frame = Frame.through(centre, radial, n, np.cross(radial, n))
        corner = (big + r - r / np.sqrt(2.0), r - r / np.sqrt(2.0))
        section = Profile((Line((big, 0.0), (big + r, 0.0)), Arc((big + r, 0.0), corner, (big, r)),
                           Line((big, r), (big, 0.0))))  # fmt: skip
        face = section.face(frame)
        with boundary("a junction's web"):
            maker = BRepPrimAPI_MakeRevol(face, ax1(centre, axis), t1 - t0)
            maker.Build()
            web = maker.Shape()
        above = prism(plane_face, n * (r * 1.5)).shape
        clipped = boolean("intersect", [web], [above])
        if not faces(clipped.shape):
            continue
        webs.append(clipped.shape)
    return webs


def _boolean(kind: str) -> Callable[[Context], Product]:
    def build(ctx: Context) -> Product:
        operands = ctx.solids()
        if len(operands) < 2:
            raise ctx.fail(
                DesignError(f"a {kind} needs two solids at least", got=len(operands))
            )
        blend = ctx.length("blend_radius", 0.0)
        chamfer = ctx.length("chamfer", 0.0)
        if blend < 0.0 or chamfer < 0.0:
            raise ctx.fail(DesignError("a blend or chamfer can't be negative"))
        return combine(ctx, kind, operands, blend=blend, chamfer=chamfer)

    return build


BUILDERS: Mapping[str, Callable[[Context], Product]] = {
    "union": _boolean("union"),
    "subtract": _boolean("subtract"),
    "intersect": _boolean("intersect"),
}
