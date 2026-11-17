"""Generated parts built exactly: the generator's truth (forge_eval.truth), made with OpenCascade (docs/V2-stage3.md, 11.2).

The same parts tests/v2_truth.py makes as meshes with manifold3d, made here
as B-reps by forge_occ's own helpers: each prism its outline (a rectangle,
its chosen corners rounded by true arcs, or a disc) extruded along its
normal, each frustum a cone or a cylinder about its axis, each carried on
past its ends as far as its step allows, and added or taken away in order;
faces on one surface merged at the end. So the stage-2 judge can be run on
:class:`~forge_occ.view.BrepView` over the very parts it was run on as
meshes, and any check that passes one and fails the other found.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
from forge_eval.truth import (
    QUADRANTS,
    Corner,
    Frustum,
    Kept,
    Letters,
    Outline2,
    Prism,
    Pushed,
    RingCorner,
    Step,
    Threaded,
    Truth,
    Turned,
    line_contours,
)

__all__ = ["build"]


def _outline(prism: Prism, rounded: tuple[bool, ...]) -> Any:
    from forge_occ.profiles import Arc, Circle, Line, Profile

    h1, h2 = prism.half
    r = prism.corner
    if r > 0 and r >= h1 - 1e-12 and r >= h2 - 1e-12 and all(rounded):
        return Profile((Circle((0.0, 0.0), r),))
    ends: list[
        tuple[tuple[float, float], tuple[float, float]]
    ] = []  # each corner's way in and way out
    arcs: list[Any] = []
    for k, ((q1, q2), on) in enumerate(zip(QUADRANTS, rounded, strict=True)):
        if on and r > 0:
            cx, cy = q1 * (h1 - r), q2 * (h2 - r)

            def at(angle: float, cx: float = cx, cy: float = cy) -> tuple[float, float]:
                return cx + r * math.cos(angle), cy + r * math.sin(angle)

            start, end = at(math.pi / 2 * k), at(math.pi / 2 * (k + 1))
            arcs.append(Arc(start, at(math.pi / 2 * (k + 0.5)), end))
            ends.append((start, end))
        else:
            arcs.append(None)
            corner = (q1 * h1, q2 * h2)
            ends.append((corner, corner))
    segments: list[Any] = []
    for k in range(4):
        if arcs[k] is not None:
            segments.append(arcs[k])
        a, b = ends[k][1], ends[(k + 1) % 4][0]
        if math.dist(a, b) > 1e-9:
            segments.append(Line(a, b))
    return Profile(tuple(segments))


def _profile(outline: Outline2) -> Any:
    """An outline of sides and arcs as forge_occ draws one: lines, and each arc through its middle."""
    from forge_occ.profiles import Arc, Line, Profile

    segments: list[Any] = []
    for a, b, centre, r, a0, sweep in outline.pieces():
        if centre is None:
            segments.append(Line(a, b))
        else:
            middle = (
                centre[0] + r * math.cos(a0 + sweep / 2),
                centre[1] + r * math.sin(a0 + sweep / 2),
            )
            segments.append(Arc(a, middle, b))
    return Profile(tuple(segments))


def _letters(q: Letters, low: float, high: float) -> Any:
    """A line of letters as OpenCascade solids: each contour a wire of its own curves (lines, quadratic Béziers), their faces laid over each other (the general fuse), and each piece kept where the truth itself says the letters are (a point inside it, from its mesh), pushed along the normal."""
    from forge_occ.make import compound, prism, unify
    from forge_occ.occt import boundary, faces
    from forge_spec.font import CAP_HEIGHT
    from OCP.BOPAlgo import BOPAlgo_Builder
    from OCP.BRep import BRep_Builder, BRep_Tool
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_Transform,
    )
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.collections import Array1_gp_Pnt as TColgp_Array1OfPnt
    from OCP.Geom import Geom_BezierCurve
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS, TopoDS_Compound

    scale = q.height / CAP_HEIGHT
    contours, length = line_contours(q.text)
    c, r, u, n = (
        np.asarray(v, dtype=np.float64) for v in (q.centre, q.right, q.up, q.normal)
    )

    def at(p: tuple[float, float]) -> Any:
        x = c + (p[0] - length / 2) * scale * r + (p[1] * scale - q.height / 2) * u
        return gp_Pnt(float(x[0]), float(x[1]), float(x[2]))

    plane = gp_Pln(
        gp_Ax3(gp_Pnt(*map(float, c)), gp_Dir(*map(float, n)), gp_Dir(*map(float, r)))
    )
    laid = []
    with boundary("a truth's letters"):
        for run in contours:
            wire = BRepBuilderAPI_MakeWire()
            for a, k, b in run:
                if a == b:
                    continue
                if (
                    abs((k[0] - a[0]) * (b[1] - a[1]) - (k[1] - a[1]) * (b[0] - a[0]))
                    <= 1e-12
                ):
                    wire.Add(BRepBuilderAPI_MakeEdge(at(a), at(b)).Edge())
                    continue
                poles = TColgp_Array1OfPnt(1, 3)
                for j, p in enumerate((a, k, b), start=1):
                    poles.SetValue(j, at(p))
                wire.Add(BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles)).Edge())
            laid.append(BRepBuilderAPI_MakeFace(plane, wire.Wire(), True).Face())
        if len(laid) > 1:
            fuse = BOPAlgo_Builder()
            for face in laid:
                fuse.AddArgument(face)
            fuse.Perform()
            cells = faces(fuse.Shape())
        else:
            cells = laid
        kept = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(kept)
        for cell in cells:
            BRepMesh_IncrementalMesh(cell, 0.01)
            mesh = BRep_Tool.Triangulation_s(TopoDS.Face(cell), TopLoc_Location())
            tri = mesh.Triangle(1)
            i, j, k = tri.Get()
            corner = [mesh.Node(m) for m in (i, j, k)]
            inner = np.mean([[p.X(), p.Y(), p.Z()] for p in corner], axis=0)
            if q.contains(inner[None, :] + 0.5 * (q.low + q.high) * n)[0]:
                builder.Add(kept, cell)
        region = faces(unify(kept).shape)
    along = n * ((q.high + high) - (q.low - low))
    tools = []
    for face in region:
        moved = prism(face, tuple(float(x) for x in along)).shape
        shift = gp_Trsf()
        shift.SetTranslation(gp_Vec(*map(float, n * (q.low - low))))
        tools.append(BRepBuilderAPI_Transform(moved, shift, True).Shape())
    return compound(tools)


#: How far a rounding's piece runs on behind the two faces it rounds (into the air an outside edge has there, or
#: the material an inside one has), so neither face of the part is one of its own (mm).
_HAIR = 0.05


def _section(
    size: float,
    round_: bool,
    at: Callable[[float, float], tuple[float, float]] = lambda u, v: (u, v),
    flipped: bool = False,
) -> Outline2:
    """A rounding's (or a bevel's) section in a right-angled corner, from the edge along the two faces (``u``, ``v``), placed by ``at`` (which turns it over when ``flipped``): the corner up to the round touching both faces ``size`` back, or the bevel's line; run on a hair behind both faces."""
    e = _HAIR
    # Round the round's centre clockwise (from along one face to along the other, past the corner), as placed.
    turn = (at(size, size), not flipped) if round_ else (None, False)
    return Outline2(
        at(-e, -e),
        (
            (at(size, -e), None, False),
            (at(size, 0.0), None, False),
            (at(0.0, size), turn[0], turn[1]),
            (at(-e, size), None, False),
            (at(-e, -e), None, False),
        ),
    )


def _rounding(step: Step) -> Any:
    """A rounding's (or a bevel's) piece: a straight edge's section pushed along it, carried on past its ends as the step allows; a rim's section turned round its axis (all of it, or its quarter turn)."""
    from forge_occ.geom import Frame, ax1
    from forge_occ.make import prism as extrude
    from forge_occ.occt import boundary
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol

    low, high = step.reach
    if isinstance(step.solid, Corner):
        c = step.solid
        a, b, w = (np.asarray(v, dtype=np.float64) for v in (c.a, c.b, c.along))
        origin = np.asarray(c.start, dtype=np.float64) - low * w
        face = _profile(_section(c.size, c.round_)).face(
            Frame.through(origin, a, b, np.cross(a, b))
        )
        return extrude(face, w * (c.length + low + high)).shape
    r = step.solid
    assert isinstance(r, RingCorner)

    def at(u: float, v: float) -> tuple[float, float]:
        return (r.radius + u * r.a[0] + v * r.b[0], r.height + u * r.a[1] + v * r.b[1])

    flipped = r.a[0] * r.b[1] - r.a[1] * r.b[0] < 0
    w = np.asarray(r.axis, dtype=np.float64)
    if r.first is None:
        helper = (
            np.array([1.0, 0.0, 0.0]) if abs(w[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        )
        first = np.cross(helper, w)
        first /= np.linalg.norm(first)
        start, sweep = 0.0, 2 * math.pi
    else:
        assert r.turn is not None
        first = np.asarray(r.first, dtype=np.float64)
        start, sweep = r.turn[0], r.turn[1] - r.turn[0]
    u = math.cos(start) * first + math.sin(start) * np.cross(w, first)
    centre = np.asarray(r.centre, dtype=np.float64)
    face = _profile(_section(r.size, r.round_, at, flipped)).face(
        Frame.through(centre, u, w, np.cross(u, w))
    )
    with boundary("a truth's rounded rim"):
        maker = BRepPrimAPI_MakeRevol(face, ax1(tuple(centre), tuple(w)), sweep)
        maker.Build()
        return maker.Shape()


def _kept(step: Step) -> Any:
    """A kept prism: its prism (carried on past neither end) in common with the slab between its two planes, each
    carried on as the step allows, as wide as the prism's box is across."""
    from dataclasses import replace

    from forge_eval.truth import bounds
    from forge_occ.occt import boundary
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    low, high = step.reach
    k = step.solid
    assert isinstance(k, Kept)
    prism = _solid(replace(step, solid=k.solid, reach=(0.0, 0.0)))
    n = np.asarray(k.normal, dtype=np.float64)
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    a = np.cross(helper, n)
    a /= np.linalg.norm(a)
    b = np.cross(n, a)
    lo, hi = bounds(k.solid)
    big = float(np.linalg.norm(hi - lo)) + float(np.linalg.norm(0.5 * (lo + hi) - np.asarray(k.origin))) + 10.0
    corner = np.asarray(k.origin, dtype=np.float64) + (k.low - low) * n - big * a - big * b
    with boundary("a truth's kept prism"):
        slab = BRepPrimAPI_MakeBox(gp_Ax2(gp_Pnt(*corner), gp_Dir(*n), gp_Dir(*a)), 2 * big, 2 * big,
                                   (k.high + high) - (k.low - low)).Shape()  # fmt: skip
        common = BRepAlgoAPI_Common(prism, slab)
        common.Build()
        return common.Shape()


def _solid(step: Step) -> Any:
    from forge_occ.geom import Frame
    from forge_occ.make import prism as extrude
    from forge_occ.occt import boundary
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.Precision import Precision

    low, high = step.reach
    if isinstance(step.solid, (Corner, RingCorner)):
        return _rounding(step)
    if isinstance(step.solid, Letters):
        return _letters(step.solid, low, high)
    if isinstance(step.solid, Threaded):
        # The thread's groove as the build cuts one (its points, in the thread's zone, aren't graded).
        from forge_occ.ops.threads import groove

        t = step.solid
        pieces = groove(
            t.base,
            t.axis,
            2 * t.radius,
            t.pitch,
            "right" if t.hand > 0 else "left",
            t.start,
            t.end,
        )
        return pieces  # taken away together, each piece a tool of its own
    if isinstance(step.solid, Pushed):
        q = step.solid
        e1, e2, n = (
            np.asarray(v, dtype=np.float64) for v in (q.first, q.second, q.normal)
        )
        origin = np.asarray(q.origin, dtype=np.float64) + (q.low - low) * n
        face = _profile(q.outline).face(Frame.through(origin, e1, e2, np.cross(e1, e2)))
        return extrude(face, n * ((q.high + high) - (q.low - low))).shape
    if isinstance(step.solid, Turned):
        from forge_occ.geom import ax1
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol

        turned = step.solid
        w = np.asarray(turned.axis, dtype=np.float64)
        helper = (
            np.array([1.0, 0.0, 0.0]) if abs(w[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        )
        u = np.cross(helper, w)
        u /= np.linalg.norm(u)
        # The half outline in the plane of the axis and u: its first coordinate along u, its second along the axis.
        face = _profile(turned.outline).face(
            Frame.through(
                np.asarray(turned.base, dtype=np.float64), u, w, np.cross(u, w)
            )
        )
        with boundary("a truth's revolution"):
            maker = BRepPrimAPI_MakeRevol(face, ax1(tuple(turned.base), tuple(w)))
            maker.Build()
            return maker.Shape()
    if isinstance(step.solid, Kept):
        return _kept(step)
    if isinstance(step.solid, Prism):
        p = step.solid
        e1, e2, n = (
            np.asarray(v, dtype=np.float64) for v in (p.first, p.second, p.normal)
        )
        rounded: tuple[bool, ...] = p.rounded
        if float(np.dot(np.cross(e1, e2), n)) < 0:  # keep the frame right-handed
            e2 = -e2
            rounded = (
                rounded[3],
                rounded[2],
                rounded[1],
                rounded[0],
            )  # each corner's mirror across the first axis
        origin = np.asarray(p.centre, dtype=np.float64) + (p.low - low) * n
        face = _outline(p, rounded).face(Frame.through(origin, e1, e2, n))
        return extrude(face, n * ((p.high + high) - (p.low - low))).shape
    f = step.solid
    assert isinstance(f, Frustum)
    r0, r1 = f.radii
    slope = (r1 - r0) / f.length
    start, end = -low, f.length + high
    if slope < 0:  # narrowing: carried no further than the apex
        end = min(end, -r0 / slope)
    elif slope > 0:
        start = max(start, -r0 / slope)
    w = np.asarray(f.axis, dtype=np.float64)
    base = np.asarray(f.base, dtype=np.float64) + start * w
    frame = gp_Ax2(gp_Pnt(*base), gp_Dir(*w))
    # An end's radius OpenCascade can't tell from nothing (a pointed cone's tip, worked out
    # as a rounding error from it: part 1101's 4e-16 mm) is nothing; it refuses one between.
    a, b = (
        r if r >= Precision.Confusion_s() else 0.0
        for r in (r0 + slope * start, r0 + slope * end)
    )
    with boundary("a truth's frustum"):
        if abs(a - b) <= 1e-12:
            return BRepPrimAPI_MakeCylinder(frame, a, end - start).Shape()
        return BRepPrimAPI_MakeCone(frame, a, b, end - start).Shape()


#: Points a boolean's result is held to the truth's own membership at, where OpenCascade warned (about its tool).
HELD_AT = 4000
#: How far from the result's surface a point must be to be held so (mm): nearer, either side may be right.
HELD_CLEAR = 1e-4


def build(truth: Truth) -> Any:
    """The part, as an OpenCascade solid: its steps added and taken away in order, faces on one surface merged.

    A boolean OpenCascade warns about (two pieces of a rounding meeting at a
    face, edges it found no use for) is taken only if what it made is valid
    and is the truth's own shape so far: on the same side as the truth at
    :data:`HELD_AT` points round the step's solid, clear of the surface
    (:func:`_held_to`); else the warning stands, and the part has no exact
    model.
    """
    from dataclasses import replace

    from forge_occ.errors import BooleanFlagError
    from forge_occ.make import boolean, unify
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.BRepCheck import BRepCheck_Analyzer

    part = None
    for k, step in enumerate(truth.steps):
        solid = _solid(step)
        tools = solid if isinstance(solid, list) else [solid]
        if part is None:
            part = solid
            continue
        kind = "union" if step.add else "subtract"
        try:
            part = boolean(kind, [part], tools).shape
        except BooleanFlagError as error:
            warned = frozenset(error.detail.get("warnings", ()))
            if not warned or error.detail.get("errors"):
                raise
            made = boolean(kind, [part], tools, also_allowed=warned).shape
            _held_to(made, replace(truth, steps=truth.steps[: k + 1]), step, error)
            part = made
    assert part is not None
    # Its faces on one surface merged, where that leaves a valid solid: merging can fail on faces a turned cut
    # crosses (generated part 477: a slot turned 120 degrees in a block's side, crossed by a slot through the block;
    # every boolean valid, the merged solid not), and a solid that isn't valid makes no exact boolean with another.
    # The merging changes what it shares with the solid it is given, so it is given a copy.
    merged = unify(BRepBuilderAPI_Copy(part).Shape()).shape
    return merged if BRepCheck_Analyzer(merged).IsValid() else part


def _held_to(made: Any, truth: Truth, step: Any, error: Exception) -> None:
    """Raise ``error`` unless ``made`` is valid and on the truth's side at points round the step's solid, clear of its surface."""
    import numpy as np
    from forge_checks.view import Side, ViewProxy
    from forge_eval.truth import bounds
    from forge_occ.view import BrepView
    from OCP.BRepCheck import BRepCheck_Analyzer

    if not BRepCheck_Analyzer(made).IsValid():
        raise error
    lo, hi = bounds(step.solid)
    points = np.random.default_rng(0).uniform(
        np.asarray(lo) - 0.5, np.asarray(hi) + 0.5, (HELD_AT, 3)
    )
    view = ViewProxy(BrepView(made))
    clear = (view.distance(points) > HELD_CLEAR) & ~truth.unsure(points)
    if not clear.sum() or np.any(
        (view.classify(points[clear]) == Side.IN) != truth.inside(points[clear])
    ):
        raise error
