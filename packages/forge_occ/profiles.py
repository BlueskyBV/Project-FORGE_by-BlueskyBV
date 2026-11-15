"""2D outlines, exactly: lines, true arcs, Bézier pieces, and B-splines fitted to a curve within 1e-6 mm.

Each V1 profile kind is read from V1's builder as a definition
(docs/V2-stage3.md, 7.2) and drawn here independently of ``forge_geom``,
whose outlines are polygons:

- a rectangle's corners are true arcs or chamfer lines; a side whose arcs
  meet leaves no zero-length line; both a radius and a chamfer is the
  rounded rectangle cut by the chamfer lines, as V1's field takes the larger;
- a slot is two lines and two arcs along ``rotation`` (a circle when it is
  as long as it is wide);
- a polygon's sides have outward normals at ``rotation + 2πi/n``, its
  corners at ``rotation + (2i+1)π/n``; ``corner_radius`` rounds each corner
  with the sides kept where they are;
- a sketch's corners are cut back by ``r / tan(θ/2)``, never past half a
  side (the radius shrunk to fit), a closing point written twice taken
  once; ``smooth`` is the closed Catmull-Rom curve through the points,
  exactly, as cubic Bézier pieces;
- a gear is V1's tooth with true involute flanks.

A :class:`Profile` is an outline in its own (u, v) coordinates; it becomes a
planar face in any frame (:meth:`Profile.face`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeWire,
)
from OCP.collections import Array1_double as TColStd_Array1OfReal
from OCP.collections import Array1_gp_Pnt as TColgp_Array1OfPnt
from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment
from OCP.Geom import Geom_BezierCurve
from OCP.GeomAbs import GeomAbs_C2
from OCP.GeomAPI import GeomAPI_PointsToBSpline, GeomAPI_ProjectPointOnCurve
from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pln, gp_Pnt
from OCP.TopoDS import TopoDS, TopoDS_Face

from .errors import DesignError, OperationError
from .geom import Frame
from .occt import boundary, faces, surface_area

__all__ = ["Profile", "green_area", "outline", "profile_of", "v_extremes"]

P2 = tuple[float, float]

#: Two points nearer than this are one (mm).
SAME = 1e-9
#: How close a fitted B-spline must stay to the curve it stands for (mm).
FIT = 1e-6


@dataclass(frozen=True)
class Line:
    a: P2
    b: P2


@dataclass(frozen=True)
class Arc:
    """From ``a`` to ``b`` through ``mid``, all on one circle."""

    a: P2
    mid: P2
    b: P2


@dataclass(frozen=True)
class Circle:
    centre: P2
    radius: float


@dataclass(frozen=True)
class Bezier:
    poles: tuple[P2, P2, P2, P2]


@dataclass(frozen=True)
class Fitted:
    """A smooth curve given by points along it (dense enough to fit within :data:`FIT`) and the curve itself, to check the fit."""

    points: tuple[P2, ...]
    curve: Callable[[float], P2] = field(compare=False)
    span: tuple[float, float] = (0.0, 1.0)


Segment = Line | Arc | Circle | Bezier | Fitted


def _start(s: Segment) -> P2:
    if isinstance(s, (Line, Arc)):
        return s.a
    if isinstance(s, Bezier):
        return s.poles[0]
    if isinstance(s, Fitted):
        return s.points[0]
    return (s.centre[0] + s.radius, s.centre[1])


def _end(s: Segment) -> P2:
    if isinstance(s, (Line, Arc)):
        return s.b
    if isinstance(s, Bezier):
        return s.poles[3]
    if isinstance(s, Fitted):
        return s.points[-1]
    return _start(s)


def _signed_area(outline: Sequence[Segment]) -> float:
    """Twice-integrated area of the closed outline, by dense sampling (its sign is what matters)."""
    pts: list[P2] = []
    for s in outline:
        pts.extend(_sample(s, 64))
    area = 0.0
    for (u0, v0), (u1, v1) in zip(pts, pts[1:] + pts[:1], strict=True):
        area += u0 * v1 - u1 * v0
    return area / 2.0


def _sample(s: Segment, n: int) -> list[P2]:
    """Points along a segment, its start included and its end not."""
    if isinstance(s, Line):
        return [(s.a[0] + (s.b[0] - s.a[0]) * k / n, s.a[1] + (s.b[1] - s.a[1]) * k / n)
                for k in range(n)]  # fmt: skip
    if isinstance(s, Circle):
        return [(s.centre[0] + s.radius * math.cos(2 * math.pi * k / n),
                 s.centre[1] + s.radius * math.sin(2 * math.pi * k / n)) for k in range(n)]  # fmt: skip
    if isinstance(s, Arc):
        centre, radius = _circle_through(s.a, s.mid, s.b)
        a0 = math.atan2(s.a[1] - centre[1], s.a[0] - centre[0])
        am = math.atan2(s.mid[1] - centre[1], s.mid[0] - centre[0])
        a1 = math.atan2(s.b[1] - centre[1], s.b[0] - centre[0])
        sweep = (a1 - a0) % (2 * math.pi)
        if (am - a0) % (2 * math.pi) > sweep:  # it goes the other way round
            sweep -= 2 * math.pi
        return [(centre[0] + radius * math.cos(a0 + sweep * k / n),
                 centre[1] + radius * math.sin(a0 + sweep * k / n)) for k in range(n)]  # fmt: skip
    if isinstance(s, Bezier):
        p = np.asarray(s.poles, dtype=np.float64)
        out = []
        for k in range(n):
            t = k / n
            q = ((1 - t) ** 3 * p[0] + 3 * (1 - t) ** 2 * t * p[1] + 3 * (1 - t) * t * t * p[2]
                 + t**3 * p[3])  # fmt: skip
            out.append((float(q[0]), float(q[1])))
        return out
    lo, hi = s.span
    return [s.curve(lo + (hi - lo) * k / n) for k in range(n)]


def _circle_through(a: P2, b: P2, c: P2) -> tuple[P2, float]:
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-300:
        raise DesignError("an arc's three points lie on a line")
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d  # fmt: skip
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d  # fmt: skip
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def _reversed(outline: Sequence[Segment]) -> list[Segment]:
    out: list[Segment] = []
    for s in reversed(outline):
        if isinstance(s, Line):
            out.append(Line(s.b, s.a))
        elif isinstance(s, Arc):
            out.append(Arc(s.b, s.mid, s.a))
        elif isinstance(s, Bezier):
            out.append(Bezier((s.poles[3], s.poles[2], s.poles[1], s.poles[0])))
        elif isinstance(s, Fitted):
            lo, hi = s.span
            out.append(Fitted(tuple(reversed(s.points)), s.curve, (hi, lo)))
        else:
            out.append(s)  # a full circle is made counter-clockwise either way
    return out


def _closed(outline: Sequence[Segment]) -> list[Segment]:
    """The outline with its zero-length lines taken out, checked to close."""
    kept = [
        s for s in outline if not (isinstance(s, Line) and math.dist(s.a, s.b) <= SAME)
    ]
    if not kept:
        raise DesignError("an outline with nothing in it")
    for s, t in zip(kept, kept[1:] + kept[:1], strict=True):
        if math.dist(_end(s), _start(t)) > 1e-7:
            raise OperationError(
                "an outline that doesn't close", gap=math.dist(_end(s), _start(t))
            )
    return kept


@dataclass(frozen=True)
class Profile:
    """A closed outline in (u, v), counter-clockwise, optionally cut by other outlines (the part inside all)."""

    outline: tuple[Segment, ...]
    cut_by: tuple[tuple[Segment, ...], ...] = ()

    def face(self, frame: Frame, *, within: Profile | None = None) -> Any:
        """The outline as a planar face in ``frame`` (its normal the frame's z); only the part inside ``within`` if given."""
        face = _face(self.outline, frame)
        for other in (*self.cut_by, *((within.outline,) if within else ())):
            face = _common(face, _face(other, frame))
        return face

    def area(self) -> float:
        return surface_area(self.face(Frame((0.0, 0.0, 0.0))))

    def bounds(self) -> tuple[float, float, float, float]:
        pts = np.asarray(
            [p for s in self.outline for p in _sample(s, 256)], dtype=np.float64
        )
        return (
            float(pts[:, 0].min()),
            float(pts[:, 0].max()),
            float(pts[:, 1].min()),
            float(pts[:, 1].max()),
        )


def _to_3d(frame: Frame, p: P2) -> gp_Pnt:
    return gp_Pnt(*frame.at(p[0], p[1]))


def _edge(frame: Frame, s: Segment) -> Any:
    with boundary("drawing an outline"):
        if isinstance(s, Line):
            return BRepBuilderAPI_MakeEdge(
                GC_MakeSegment(_to_3d(frame, s.a), _to_3d(frame, s.b)).Value()
            ).Edge()
        if isinstance(s, Arc):
            arc = GC_MakeArcOfCircle(
                _to_3d(frame, s.a), _to_3d(frame, s.mid), _to_3d(frame, s.b)
            )
            return BRepBuilderAPI_MakeEdge(arc.Value()).Edge()
        if isinstance(s, Circle):
            centre = _to_3d(frame, s.centre)
            circle = gp_Circ(
                gp_Ax2(centre, gp_Dir(*frame.z), gp_Dir(*frame.x)), s.radius
            )
            return BRepBuilderAPI_MakeEdge(circle).Edge()
        if isinstance(s, Bezier):
            poles = TColgp_Array1OfPnt(1, 4)
            for i, p in enumerate(s.poles):
                poles.SetValue(i + 1, _to_3d(frame, p))
            return BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles)).Edge()
        return BRepBuilderAPI_MakeEdge(_fit(frame, s)).Edge()


def _fit(frame: Frame, s: Fitted) -> Any:
    """A B-spline through the curve's points, with each point's own parameter, checked within :data:`FIT`."""
    n = len(s.points)
    poles = TColgp_Array1OfPnt(1, n)
    params = TColStd_Array1OfReal(1, n)
    lo, hi = s.span
    for i, p in enumerate(s.points):
        poles.SetValue(i + 1, _to_3d(frame, p))
        params.SetValue(i + 1, i / (n - 1))
    curve = GeomAPI_PointsToBSpline(poles, params, 3, 8, GeomAbs_C2, FIT / 10.0).Curve()
    worst = 0.0
    for k in range(4 * n + 1):
        t = lo + (hi - lo) * k / (4 * n)
        projection = GeomAPI_ProjectPointOnCurve(_to_3d(frame, s.curve(t)), curve)
        worst = max(
            worst, projection.LowerDistance() if projection.NbPoints() else math.inf
        )
    if worst > FIT:
        raise OperationError(
            "a curve could not be fitted closely enough", worst=worst, needed=FIT
        )
    return curve


def _face(outline: Sequence[Segment], frame: Frame) -> TopoDS_Face:
    segments = _closed(outline)
    if _signed_area(segments) < 0.0:
        segments = _reversed(segments)
    with boundary("making a profile's face"):
        wire = BRepBuilderAPI_MakeWire()
        for s in segments:
            wire.Add(_edge(frame, s))
        if not wire.IsDone():
            raise OperationError("an outline's edges don't join into a wire")
        maker = BRepBuilderAPI_MakeFace(gp_Pln(frame.ax3()), wire.Wire(), True)
        if not maker.IsDone():
            raise OperationError("an outline doesn't make a face")
        return maker.Face()


def _common(a: TopoDS_Face, b: TopoDS_Face) -> TopoDS_Face:
    with boundary("cutting a profile"):
        op = BRepAlgoAPI_Common(a, b)
        op.SetRunParallel(False)
        op.Build()
        found = faces(op.Shape())
    if len(found) != 1:
        raise DesignError(
            "a profile cut into pieces or into nothing", pieces=len(found)
        )
    return TopoDS.Face(found[0])


# --- the V1 profile kinds ----------------------------------------------------------------


def _arc(centre: P2, radius: float, a0: float, a1: float) -> Arc:
    """The arc of the circle from angle a0 to a1 (radians, the way from a0 to a1 given by the sign of a1 - a0)."""
    mid = (a0 + a1) / 2.0

    def at(t: float) -> P2:
        return centre[0] + radius * math.cos(t), centre[1] + radius * math.sin(t)

    return Arc(at(a0), at(mid), at(a1))


def rectangle(
    centre: P2,
    width: float,
    height: float,
    corner_radius: float = 0.0,
    corner_chamfer: float = 0.0,
) -> Profile:
    hw, hh = width / 2.0, height / 2.0
    if hw <= 0.0 or hh <= 0.0:
        raise DesignError(
            "a rectangle needs a width and a height", width=width, height=height
        )
    limit = min(hw, hh)
    if corner_chamfer < 0.0 or corner_chamfer > 2 * limit + 1e-9:
        raise DesignError(
            "a corner chamfer is at most the shorter side",
            corner_chamfer=corner_chamfer,
        )
    if corner_radius < 0.0 or corner_radius > limit + 1e-9:
        raise DesignError(
            "a corner radius is at most half the shorter side",
            corner_radius=corner_radius,
        )
    cu, cv = centre
    r = min(corner_radius, limit)
    corners = (
        (1, 1),
        (-1, 1),
        (-1, -1),
        (1, -1),
    )  # counter-clockwise from the top right
    outline: list[Segment] = []
    if r > 0.0:
        for i, (su, sv) in enumerate(corners):
            c = (cu + su * (hw - r), cv + sv * (hh - r))
            # The arc at each corner turns a quarter, counter-clockwise.
            a0 = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2][i]
            outline.append(_arc(c, r, a0, a0 + math.pi / 2))
        closed: list[Segment] = []
        for s, t in zip(outline, outline[1:] + outline[:1], strict=True):
            closed.append(s)
            closed.append(Line(_end(s), _start(t)))
        rounded = Profile(tuple(closed))
    else:
        pts = [(cu + su * hw, cv + sv * hh) for su, sv in corners]
        rounded = Profile(
            tuple(Line(a, b) for a, b in zip(pts, pts[1:] + pts[:1], strict=True))
        )
    if corner_chamfer <= 0.0:
        return rounded
    cut = corner_chamfer
    octagon: list[P2] = []
    for su, sv in corners:
        # Each corner cut by the line through the points `cut` back from it along both sides.
        octagon.append(
            (cu + su * hw, cv + sv * (hh - cut))
            if su * sv > 0
            else (cu + su * (hw - cut), cv + sv * hh)
        )
        octagon.append(
            (cu + su * (hw - cut), cv + sv * hh)
            if su * sv > 0
            else (cu + su * hw, cv + sv * (hh - cut))
        )
    chamfered = tuple(
        Line(a, b) for a, b in zip(octagon, octagon[1:] + octagon[:1], strict=True)
    )
    if r <= 0.0:
        return Profile(chamfered)
    return Profile(rounded.outline, cut_by=(chamfered,))


def circle(centre: P2, diameter: float) -> Profile:
    if diameter <= 0.0:
        raise DesignError("a circle needs a diameter", diameter=diameter)
    return Profile((Circle(centre, diameter / 2.0),))


def slot(centre: P2, length: float, width: float, rotation: float = 0.0) -> Profile:
    if width <= 0.0 or length < width:
        raise DesignError(
            "a slot is at least as long as it is wide", length=length, width=width
        )
    radius = width / 2.0
    half = length / 2.0 - radius
    if half <= SAME:
        return Profile((Circle(centre, radius),))
    d = (math.cos(rotation), math.sin(rotation))
    n = (-d[1], d[0])
    cu, cv = centre
    right = (cu + d[0] * half, cv + d[1] * half)
    left = (cu - d[0] * half, cv - d[1] * half)

    def at(base: P2, du: float, dn: float) -> P2:
        return base[0] + d[0] * du + n[0] * dn, base[1] + d[1] * du + n[1] * dn

    return Profile((
        Line(at(left, 0, -radius), at(right, 0, -radius)),
        Arc(at(right, 0, -radius), at(right, radius, 0), at(right, 0, radius)),
        Line(at(right, 0, radius), at(left, 0, radius)),
        Arc(at(left, 0, radius), at(left, -radius, 0), at(left, 0, -radius)),
    ))  # fmt: skip


def polygon(
    centre: P2, circumscribed_diameter: float, sides: int, rotation: float = 0.0,
    corner_radius: float = 0.0,
) -> Profile:  # fmt: skip
    if sides < 3:
        raise DesignError("a polygon needs at least three sides", sides=sides)
    big = circumscribed_diameter / 2.0
    if big <= 0.0:
        raise DesignError(
            "a polygon needs a size", circumscribed_diameter=circumscribed_diameter
        )
    apothem = big * math.cos(math.pi / sides)
    if corner_radius < 0.0 or corner_radius >= apothem:
        raise DesignError(
            "a polygon's corner radius is under its inradius",
            corner_radius=corner_radius,
        )
    cu, cv = centre
    inner = apothem - corner_radius
    reach = inner / math.cos(math.pi / sides)
    corner_angles = [rotation + (2 * i + 1) * math.pi / sides for i in range(sides)]
    corners = [
        (cu + reach * math.cos(a), cv + reach * math.sin(a)) for a in corner_angles
    ]
    if corner_radius <= 0.0:
        return Profile(
            tuple(
                Line(a, b)
                for a, b in zip(corners, corners[1:] + corners[:1], strict=True)
            )
        )
    outline: list[Segment] = []
    for i, c in enumerate(corners):
        # Corner i lies between the sides whose normals are at rotation + 2πi/n and + 2π(i+1)/n.
        a0 = rotation + 2 * math.pi * i / sides
        outline.append(_arc(c, corner_radius, a0, a0 + 2 * math.pi / sides))
    closed: list[Segment] = []
    for s, t in zip(outline, outline[1:] + outline[:1], strict=True):
        closed.append(s)
        closed.append(Line(_end(s), _start(t)))
    return Profile(tuple(closed))


def sketch(
    points: Sequence[Sequence[float]], corner_radius: float = 0.0, smooth: bool = False
) -> Profile:
    if any(len(p) not in (2, 3) for p in points):
        raise DesignError("a sketch's points are [u, v], or [u, v, corner radius]")
    corners = [(float(p[0]), float(p[1])) for p in points]
    radii = [float(p[2]) if len(p) > 2 else corner_radius for p in points]
    if len(corners) > 3 and math.dist(corners[0], corners[-1]) < 1e-9:
        corners, radii = corners[:-1], radii[:-1]
    n = len(corners)
    if n < 3:
        raise DesignError("an outline needs at least three corners", corners=n)
    area = sum(corners[i][0] * corners[(i + 1) % n][1] - corners[(i + 1) % n][0] * corners[i][1]
               for i in range(n)) / 2.0  # fmt: skip
    if abs(area) < 1e-9:
        raise DesignError("the outline encloses no area", corners=n)
    if smooth:
        pieces: list[Segment] = []
        for i in range(n):
            p0, p1, p2, p3 = (np.asarray(corners[(i + k) % n]) for k in (-1, 0, 1, 2))
            m1, m2 = (p2 - p0) / 2.0, (p3 - p1) / 2.0
            poles = (p1, p1 + m1 / 3.0, p2 - m2 / 3.0, p2)
            pieces.append(Bezier(tuple((float(q[0]), float(q[1])) for q in poles)))  # type: ignore[arg-type]
        return Profile(tuple(pieces))
    joints: list[
        tuple[P2, P2, Arc | None]
    ] = []  # where each corner starts, ends, and its arc
    for i in range(n):
        here = np.asarray(corners[i])
        before = np.asarray(corners[i - 1])
        after = np.asarray(corners[(i + 1) % n])
        a, b = before - here, after - here
        la, lb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        r = radii[i]
        point = (float(here[0]), float(here[1]))
        if r <= 0.0 or la < 1e-12 or lb < 1e-12:
            joints.append((point, point, None))
            continue
        a, b = a / la, b / lb
        angle = math.acos(float(np.clip(np.dot(a, b), -1.0, 1.0)))
        if angle < 1e-6 or angle > math.pi - 1e-6:
            joints.append((point, point, None))
            continue
        cut = min(r / math.tan(angle / 2.0), la / 2.0, lb / 2.0)
        r = cut * math.tan(angle / 2.0)
        start, end = here + a * cut, here + b * cut
        bisector = (a + b) / float(np.linalg.norm(a + b))
        centre = here + bisector * (r / math.sin(angle / 2.0))
        middle = centre - bisector * r
        s = (float(start[0]), float(start[1]))
        e = (float(end[0]), float(end[1]))
        joints.append((s, e, Arc(s, (float(middle[0]), float(middle[1])), e)))
    outline: list[Segment] = []
    for i in range(n):
        _, end, arc = joints[i]
        if arc is not None:
            outline.append(arc)
        outline.append(Line(end, joints[(i + 1) % n][0]))
    return Profile(tuple(outline))


def gear(
    module: float, teeth: int, pressure_angle: float = math.radians(20.0),
    centre: P2 = (0.0, 0.0), rotation: float = 0.0,
) -> Profile:  # fmt: skip
    """V1's spur gear: involute flanks from the base (or root) circle to the tip, straight tip and root chords."""
    if teeth < 6 or module <= 0.0:
        raise DesignError("a spur gear needs at least 6 teeth and a positive module",
                          teeth=teeth, module=module)  # fmt: skip
    pitch = module * teeth / 2.0
    base = pitch * math.cos(pressure_angle)
    tip = pitch + module
    root = max(pitch - 1.25 * module, 0.2 * pitch)
    start = max(base, root)
    half_at_pitch = math.pi / (2.0 * teeth)

    def involute(phi: float) -> float:
        return math.tan(phi) - phi

    def half_angle(r: float) -> float:
        phi = math.acos(min(1.0, base / r))
        return half_at_pitch + involute(pressure_angle) - involute(phi)

    # Where the two flanks meet, if before the tip: the tooth ends in a point there.
    top = tip
    if half_angle(tip) < 0.0:
        lo, hi = start, tip
        for _ in range(200):
            mid = (lo + hi) / 2.0
            lo, hi = (mid, hi) if half_angle(mid) > 0.0 else (lo, mid)
        top = (lo + hi) / 2.0

    def at(r: float, angle: float) -> P2:
        angle += rotation
        return centre[0] + r * math.cos(angle), centre[1] + r * math.sin(angle)

    # The flank by its roll angle t (r = base·√(1 + t²)), in which the involute is smooth.
    t_lo = math.sqrt(max((start / base) ** 2 - 1.0, 0.0))
    t_hi = math.sqrt(max((top / base) ** 2 - 1.0, 0.0))

    def flank(c: float, sign: float, upward: bool) -> Fitted:
        def curve(t: float) -> P2:
            r = min(max(base * math.sqrt(1.0 + t * t), start), top)
            return at(r, c + sign * max(half_angle(r), 0.0))

        ts = [t_lo + (t_hi - t_lo) * k / 48 for k in range(49)]
        if not upward:
            ts = ts[::-1]
        return Fitted(tuple(curve(t) for t in ts), curve, (ts[0], ts[-1]))

    outline: list[Segment] = []
    pitch_angle = 2.0 * math.pi / teeth
    for k in range(teeth):
        c = k * pitch_angle
        up = flank(c, -1.0, True)
        down = flank(c, +1.0, False)
        if root < start:
            outline.append(Line(at(root, c - half_angle(start)), _start(up)))
        outline.append(up)
        if math.dist(_end(up), _start(down)) > SAME:
            outline.append(Line(_end(up), _start(down)))
        outline.append(down)
        if root < start:
            outline.append(Line(_end(down), at(root, c + half_angle(start))))
    closed: list[Segment] = []
    for s, t in zip(outline, outline[1:] + outline[:1], strict=True):
        closed.append(s)
        if math.dist(_end(s), _start(t)) > SAME:
            closed.append(Line(_end(s), _start(t)))
    return Profile(tuple(closed))


def outline(points: Sequence[Sequence[float]]) -> Profile:
    """A v2 ``profile_outline``: where it starts, then where each side ends, the last back at the start; a side of four numbers ``[u, v, mu, mv]`` is the circular arc to (u, v) through (mu, mv).

    Three straight sides enclose an area, and so do two sides one of which
    is an arc (a ring's round section, two half circles; a D).
    """
    if (
        len(points) < 3
        or len(points[0]) != 2
        or any(len(p) not in (2, 4) for p in points)
        or (len(points) < 4 and all(len(p) == 2 for p in points))
    ):
        raise DesignError("an outline's points are [u, v] (its start, and each straight side's end) "
                          "or [u, v, mu, mv] (an arc's end and its middle): three straight sides or more, "
                          "or two with an arc among them")  # fmt: skip
    start = (float(points[0][0]), float(points[0][1]))
    here = start
    pieces: list[Segment] = []
    for p in points[1:]:
        to = (float(p[0]), float(p[1]))
        pieces.append(
            Line(here, to) if len(p) == 2 else Arc(here, (float(p[2]), float(p[3])), to)
        )
        here = to
    if math.dist(here, start) > SAME:
        raise DesignError("an outline ends where it starts", gap=math.dist(here, start))
    return Profile(tuple(pieces))


def green_area(pieces: Sequence[Segment]) -> float:
    """The signed area a closed outline of lines and arcs encloses, by Green's theorem: each line's and each arc's share of the integral of (u dv - v du) / 2, worked out exactly."""
    found = 0.0
    for s in pieces:
        (ax, ay), (bx, by) = _start(s), _end(s)
        if isinstance(s, Line):
            found += (ax * by - bx * ay) / 2
        elif isinstance(s, Arc):
            (cx, cy), r = _circle_through(s.a, s.mid, s.b)
            a0 = math.atan2(ay - cy, ax - cx)
            am = math.atan2(s.mid[1] - cy, s.mid[0] - cx)
            a1 = math.atan2(by - cy, bx - cx)
            sweep = (a1 - a0) % (2 * math.pi)
            if (am - a0) % (2 * math.pi) > sweep:  # it goes the other way round
                sweep -= 2 * math.pi
            found += (r * r * sweep + cx * (by - ay) - cy * (bx - ax)) / 2
        else:
            raise DesignError("only lines and arcs have their area worked out exactly")
    return found


def profile_of(kind: str, p: Mapping[str, Any]) -> Profile:
    """The outline a V1 profile feature's resolved parameters (mm, radians) describe."""
    centre = (float(p.get("center_u", 0.0)), float(p.get("center_v", 0.0)))
    if kind == "profile_rectangle":
        return rectangle(centre, float(p["width"]), float(p["height"]),
                         float(p.get("corner_radius", 0.0)), float(p.get("corner_chamfer", 0.0)))  # fmt: skip
    if kind == "profile_circle":
        return circle(centre, float(p["diameter"]))
    if kind == "profile_slot":
        return slot(
            centre, float(p["length"]), float(p["width"]), float(p.get("rotation", 0.0))
        )
    if kind == "profile_polygon":
        return polygon(centre, float(p["circumscribed_diameter"]), int(p["sides"]),
                       float(p.get("rotation", 0.0)), float(p.get("corner_radius", 0.0)))  # fmt: skip
    if kind == "profile_sketch":
        return sketch(
            p.get("points") or (),
            float(p.get("corner_radius", 0.0)),
            bool(p.get("smooth", False)),
        )
    if kind == "profile_outline":
        return outline(p.get("points") or ())
    if kind == "profile_gear":
        return gear(float(p["module"]), int(p["teeth"]), float(p.get("pressure_angle", math.radians(20.0))),
                    centre, float(p.get("rotation", 0.0)))  # fmt: skip
    raise DesignError("not a profile", kind=kind)


def v_extremes(profile: Profile) -> tuple[float, float]:
    """The least and greatest v of the outline's part at u ≥ 0 (what a revolve turns): exactly, for its lines and arcs (their ends, and an arc's lowest and highest points where it has them); a curve's from its points."""
    found: list[float] = []
    for s in profile.outline:
        if isinstance(s, Line):
            points = [s.a, s.b]
        elif isinstance(s, Arc):
            (cx, cy), r = _circle_through(s.a, s.mid, s.b)
            points = [s.a, s.b]
            a0 = math.atan2(s.a[1] - cy, s.a[0] - cx)
            am = math.atan2(s.mid[1] - cy, s.mid[0] - cx)
            a1 = math.atan2(s.b[1] - cy, s.b[0] - cx)
            sweep = (a1 - a0) % (2 * math.pi)
            forward = (am - a0) % (2 * math.pi) <= sweep
            for angle, p in ((math.pi / 2, (cx, cy + r)), (-math.pi / 2, (cx, cy - r))):
                along = (
                    ((angle - a0) % (2 * math.pi))
                    if forward
                    else ((a0 - angle) % (2 * math.pi))
                )
                if along <= (sweep if forward else 2 * math.pi - sweep):
                    points.append(p)
        else:
            points = [*_sample(s, 256), _end(s)]
        found += [p[1] for p in points if p[0] >= -SAME]
    if not found:
        raise DesignError(
            "the outline lies wholly on the far side of the axis: nothing to turn"
        )
    return min(found), max(found)


def half_plane(v_lo: float, v_hi: float, reach: float) -> Profile:
    """The rectangle u in [0, reach], v in [v_lo, v_hi]: the part of a profile at u ≥ 0."""
    pts = [(0.0, v_lo), (reach, v_lo), (reach, v_hi), (0.0, v_hi)]
    return Profile(
        tuple(Line(a, b) for a, b in zip(pts, pts[1:] + pts[:1], strict=True))
    )
