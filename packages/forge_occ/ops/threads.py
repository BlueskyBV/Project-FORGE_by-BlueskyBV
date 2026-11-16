"""An outside thread cut into a rod, ISO 68-1's basic profile (docs/definitions/thread.md; docs/V2-stage4.md, 7.2).

``thread``: the rod along ``axis`` from ``axis_origin``, ``rod_start`` to
``rod_end`` along it (its free end), its major diameter ``major_diameter``.
Over ``length`` from the free end its round side is cut into the basic
profile: flanks at 60 degrees, a crest flat P/8 wide at the major radius, a
root flat P/4 wide 5/8 of the sharp triangle's height H = √3/2 P in, wound at
the ``pitch`` P, right- or left-handed (``hand``) about the axis from start to
end.

**The groove** is what the thread takes from the rod: in the half-plane
through the axis, a trapezoid P/4 wide at the minor radius, its flanks at 30
degrees to the radius, carried out past the major radius by ``c`` = P/20 (so
no face of it lies on the rod's). It is swept along the helix of its root
(``BRepOffsetAPI_MakePipeShell``, the binormal held along the axis, so the
section is carried by the screw motion itself and stays in a half-plane
through the axis) from half a pitch and its own half-width before the
threaded length to as far past the free end. The groove is then cut down to
the cylinder of radius R + 2c between the threaded length's start and the
free end, and taken from the part: the thread's end at the threaded length is
square to the axis (its run-out, which thread.md leaves to the build), and the
groove reaches nothing beyond the rod's own ends.

Faces: ``flank``, ``root``, ``runout`` (the groove's end at the threaded
length).

**After-check.** Each cross-section of the cut-down groove square to the axis
is the same region turned, so its volume is the threaded length times that
region's area, ∫ 2πr f(r) dr from the minor radius to R + c, f(r) the share
of a turn the groove takes at radius r (a quarter at the root, 7/8 at the
major radius, straight between); and points on its flanks and root lie on
the profile, in the half-plane through the axis at each, within
:data:`TOLERANCE` (the sweep's surfaces are B-splines: OpenCascade has no
helicoid). The volume taken from the part is the part's inside the groove,
measured, and no more than the threaded length times the area the groove
takes from a whole rod (to the major radius).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepLib import BRepLib
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.GC import GC_MakeSegment2d
from OCP.Geom import Geom_CylindricalSurface
from OCP.gp import gp_Ax2, gp_Ax3, gp_Dir, gp_Pnt, gp_Pnt2d
from OCP.TopAbs import TopAbs_IN
from OCP.TopoDS import TopoDS

from ..errors import AfterCheckError, BooleanFlagError, DesignError, OperationError
from ..geom import unit
from ..make import boolean, one_solid, unify
from ..names import Name, carry, named_by
from ..occt import boundary, faces, plane_of, solids, surface_area, volume
from ..products import Context, Product, SolidProduct

__all__ = ["BUILDERS", "TOLERANCE", "groove", "groove_area"]

#: How far the groove's flanks and root may be from the true helicoids (mm): the sweep's B-splines.
TOLERANCE = 1e-5
#: The sweep's own tolerance (mm): its surfaces are fitted this closely to the swept section.
_SWEEP = 1e-6
#: Points measured on each face of the groove, a side.
_SAMPLES = 9
_TAN30 = fs.tan(math.radians(30.0))


def _depth(pitch: float) -> float:
    """The basic profile's depth: 5/8 of the sharp 60 degree triangle's height."""
    return 5.0 / 8.0 * math.sqrt(3.0) / 2.0 * pitch


def _share(rho: float, minor: float, pitch: float) -> float:
    """The share of a turn the groove takes at radius ``rho`` (from the minor radius out): a quarter at the root, widening by 2 tan 30° per mm out."""
    return 0.25 + 2.0 * (rho - minor) * _TAN30 / pitch


def groove_area(minor: float, outer: float, pitch: float) -> float:
    """The area the groove takes from a cross-section square to the axis, from the ``minor`` radius out to ``outer``: ∫ 2πr f(r) dr, exactly.

    >>> round(groove_area(4.0 - 5 / 8 * math.sqrt(3) / 2 * 1.25, 4.0, 1.25), 9)  # an M8's
    8.905825215
    """
    a = 0.25 - 2.0 * minor * _TAN30 / pitch  # f(r) = a + b r
    b = 2.0 * _TAN30 / pitch

    def primitive(rho: float) -> float:
        return 2.0 * math.pi * (a * (rho * rho) / 2.0 + b * (rho * rho * rho) / 3.0)

    return primitive(outer) - primitive(minor)


@dataclass(frozen=True)
class _Helix:
    """The thread's frame and sizes: the axis through ``origin`` along ``z`` (``x``, ``y`` square to it), the groove's section about the axis at ``turn`` from ``x`` (radians), its middle at ``low`` along the axis there."""

    origin: Any
    x: Any
    y: Any
    z: Any
    radius: float
    pitch: float
    hand: float
    first: float
    end: float
    turn: float

    @property
    def depth(self) -> float:
        return _depth(self.pitch)

    @property
    def minor(self) -> float:
        return self.radius - self.depth

    @property
    def carried(self) -> float:
        """How far the groove runs on past the major radius: so no face of it lies on the rod's."""
        return self.pitch / 20.0

    @property
    def half(self) -> float:
        """The groove's half-width at its outer side."""
        return self.pitch / 8.0 + (self.depth + self.carried) * _TAN30

    @property
    def low(self) -> float:
        return self.first - self.half - self.pitch / 2.0

    @property
    def turns(self) -> float:
        return (self.end + self.half + self.pitch / 2.0 - self.low) / self.pitch

    def way(self, angle: float) -> Any:
        """The unit vector square to the axis at ``angle`` past the groove's start."""
        a = self.turn + angle
        return fs.cos(a) * self.x + fs.sin(a) * self.y

    def at(self, rho: float, s: float, angle: float = 0.0) -> gp_Pnt:
        p = self.origin + rho * self.way(angle) + s * self.z
        return gp_Pnt(float(p[0]), float(p[1]), float(p[2]))

    def coordinates(self, points: Any) -> tuple[Any, Any]:
        """Each point's radius, and its place along the axis less the helix's rise to it, from the groove's middle (-P/2 to P/2)."""
        d = points - self.origin
        s = fv.matmul(d, self.z)
        theta = fv.arctan2(fv.matmul(d, self.y), fv.matmul(d, self.x)) - self.turn
        rise = self.hand * theta * self.pitch / (2.0 * math.pi)
        u = (
            np.mod(s - self.low - rise + self.pitch / 2.0, self.pitch)
            - self.pitch / 2.0
        )
        return np.sqrt(fv.sq(fv.matmul(d, self.x)) + fv.sq(fv.matmul(d, self.y))), u

    def points(self, rho: Any, u: Any, angle: Any) -> Any:
        """The points at radius ``rho``, ``u`` along the axis from the groove's middle, ``angle`` round from the start."""
        s = self.low + self.hand * angle * self.pitch / (2.0 * math.pi) + u
        a = self.turn + angle
        way = fv.cos(a)[:, None] * self.x + fv.sin(a)[:, None] * self.y
        return self.origin + rho[:, None] * way + s[:, None] * self.z


def _frame(axis: Any) -> tuple[Any, Any, Any]:
    """A frame about a thread's axis: the axis, and two directions square to it (the groove starts along the first)."""
    z = unit(axis, "a thread's axis")
    helper = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = unit(np.cross(z, helper))
    return x, np.cross(z, x), z


def groove(origin: Any, axis: Any, major_diameter: float, pitch: float, hand: str, first: float,
           end: float) -> list[Any]:  # fmt: skip
    """A thread's groove as this builds it (its first try), in pieces of a turn: what a thread from ``first`` to ``end`` along the axis takes from a rod (for a part made outside a build: a reference)."""
    x, y, z = _frame(axis)
    helix = _Helix(np.asarray(origin, dtype=np.float64), x, y, z, major_diameter / 2.0, pitch,
                   1.0 if hand == "right" else -1.0, first, end, _ATTEMPTS[0][1])  # fmt: skip
    return _pieces(helix, _ATTEMPTS[0][0])


def _thread(ctx: Context) -> Product:
    radius = ctx.length("major_diameter") / 2.0
    pitch, length = ctx.length("pitch"), ctx.length("length")
    start, end = ctx.length("rod_start"), ctx.length("rod_end")
    hand = 1.0 if ctx.option("hand", "right") == "right" else -1.0
    if not (pitch > 0.0 and length > 0.0 and radius - _depth(pitch) > 0.0):
        raise ctx.fail(DesignError("a thread needs a pitch, a length, and a rod thicker than its depth",
                                   pitch=pitch, length=length, major_diameter=2.0 * radius))  # fmt: skip
    if length > end - start + 1e-9:
        raise ctx.fail(
            DesignError(
                "a thread is no longer than its rod", length=length, rod=end - start
            )
        )
    x, y, z = _frame(ctx.vector("axis"))
    origin = np.asarray(ctx.vector("axis_origin"), dtype=np.float64)
    part = ctx.solid(0)
    failures: list[str] = []
    for per, turn in _ATTEMPTS:
        helix = _Helix(origin, x, y, z, radius, pitch, hand, end - length, end, turn)
        try:
            return _cut(ctx, part, helix, per)
        except (_MissedError, BooleanFlagError, OperationError) as missed:
            failures.append(
                f"{per:g} turn a piece, started {math.degrees(turn):g}° round: {missed}"
            )
    raise ctx.fail(
        AfterCheckError(
            "OpenCascade couldn't cut the thread so that it holds", tries=failures
        )
    )


class _MissedError(Exception):
    """A try at the thread that doesn't hold: OpenCascade's boolean went wrong somewhere, silently."""


#: How the groove is swept and where it starts, in turn: OpenCascade's booleans go wrong, silently, with a
#: helical face of many turns against a rod's (some starts round the axis, not others); a piece of one turn
#: or less holds. Where a try is caught going wrong anyway, the next sweeps shorter pieces from elsewhere.
_ATTEMPTS = ((1.0, 0.0), (0.5, math.pi / 2.0), (0.25, math.pi))


def _pieces(helix: _Helix, per: float) -> list[Any]:
    """The groove swept along its helix in pieces of ``per`` turns or less, each just as far as it reaches the threaded length."""
    count = max(1, math.ceil(helix.turns / per - 1e-9))
    each = helix.turns / count
    found = []
    for k in range(count):
        middle = helix.low + k * each * helix.pitch
        if (
            middle + each * helix.pitch + helix.half <= helix.first
            or middle - helix.half >= helix.end
        ):
            continue  # wholly before the threaded length or past the free end
        angle = helix.hand * 2.0 * math.pi * k * each
        with boundary("sweeping the thread's groove"):
            surface = Geom_CylindricalSurface(
                gp_Ax3(
                    helix.at(0.0, 0.0),
                    gp_Dir(*map(float, helix.z)),
                    gp_Dir(*map(float, helix.way(0.0))),
                ),
                helix.minor,
            )
            line = GC_MakeSegment2d(
                gp_Pnt2d(angle, middle),
                gp_Pnt2d(
                    angle + helix.hand * 2.0 * math.pi * each,
                    middle + each * helix.pitch,
                ),
            ).Value()
            edge = BRepBuilderAPI_MakeEdge(line, surface).Edge()
            BRepLib.BuildCurves3d_s(edge, 1e-7)
            spine = BRepBuilderAPI_MakeWire(edge).Wire()
            polygon = BRepBuilderAPI_MakePolygon()
            outer = helix.radius + helix.carried
            for rho, s in ((helix.minor, middle - helix.pitch / 8.0), (outer, middle - helix.half),
                           (outer, middle + helix.half), (helix.minor, middle + helix.pitch / 8.0)):  # fmt: skip
                polygon.Add(helix.at(rho, s, angle))
            polygon.Close()
            sweep = BRepOffsetAPI_MakePipeShell(spine)
            sweep.SetMode(gp_Dir(*map(float, helix.z)))
            sweep.SetTolerance(_SWEEP, _SWEEP, 1e-4)
            sweep.Add(polygon.Wire(), False, False)
            sweep.Build()
            if not sweep.IsDone():
                raise OperationError("OpenCascade could not sweep the thread's groove")
            sweep.MakeSolid()
            piece = one_solid(sweep.Shape())
        if (
            middle - helix.half < helix.first
            or middle + each * helix.pitch + helix.half > helix.end
        ):
            bounds = BRepPrimAPI_MakeCylinder(
                gp_Ax2(helix.at(0.0, helix.first), gp_Dir(*map(float, helix.z))),
                helix.radius + 2.0 * helix.carried,
                helix.end - helix.first,
            ).Shape()
            with boundary("cutting the groove down to the threaded length"):
                piece = boolean("intersect", [piece], [bounds]).shape
            if not solids(piece):
                continue
        found.append(piece)
    return found


def _cut(ctx: Context, part: SolidProduct, helix: _Helix, per: float) -> SolidProduct:
    step, length = ctx.step, helix.end - helix.first
    pieces = _pieces(helix, per)
    outer = helix.radius + helix.carried
    # The groove as swept: its volume is the threaded length times its cross-section, its sides on the profile.
    expected = length * groove_area(helix.minor, outer, helix.pitch)
    slack = TOLERANCE * sum(_sides(p) for p in pieces) + 1e-9 * expected
    made = sum(volume(p) for p in pieces)
    if abs(made - expected) > slack:
        raise ctx.fail(AfterCheckError("the thread's groove isn't the profile swept along its helix",
                                       volume=made, expected=expected))  # fmt: skip
    worst = max(_off_profile(p, helix) for p in pieces)
    if worst > TOLERANCE:
        raise ctx.fail(AfterCheckError("the thread's groove strays from the basic profile", by=worst,
                                       tolerance=TOLERANCE))  # fmt: skip

    def role(face: Any) -> tuple[Name, ...]:
        found = plane_of(face)
        if (
            found is not None
            and abs(abs(float(fv.dot(found[1], helix.z))) - 1.0) <= 1e-9
        ):
            return (Name(step, "runout"),)
        rho, _ = helix.coordinates(_samples(face))
        if np.all(np.abs(rho - helix.minor) <= TOLERANCE):
            return (Name(step, "root"),)
        return (Name(step, "flank"),)

    with boundary("the thread's subtract"):
        done = boolean("subtract", [part.shape], pieces)
    before = volume(part.shape)
    most = length * groove_area(helix.minor, helix.radius, helix.pitch)
    if _plain(part.shape, helix):
        # A whole rod there: the thread takes exactly its groove's share of every cross-section.
        taken = most
        if abs(before - volume(done.shape) - taken) > slack:
            raise _MissedError(
                f"it took {before - volume(done.shape):.6g} mm³ of a whole rod, not {taken:.6g}"
            )
    else:
        taken = volume(boolean("intersect", [part.shape], pieces).shape)
        _held(part.shape, done.shape, helix)
        if taken > most + slack:
            raise ctx.fail(AfterCheckError("the thread took more than its groove takes from a whole rod: "
                                           "something besides the rod was in its way", taken=taken, most=most))  # fmt: skip
    named = [named_by(p, role) for p in pieces]
    carried = carry(
        [part.names, *named], done.shape, done.history, fallback=(Name(step, "other"),)
    )
    merged = unify(done.shape)
    final = carry(
        [carried.names], merged.shape, merged.history, fallback=(Name(step, "other"),)
    )
    hands = "right" if helix.hand > 0 else "left"
    note = f"a {hands}-handed thread, pitch {helix.pitch:g} mm, {length:g} mm long: {taken:.6g} mm³ taken"
    why = "a thread takes the part inside its groove"
    return SolidProduct(
        merged.shape,
        final.names.on(merged.shape),
        notes=(note,),
        tolerance=TOLERANCE,
        lost=frozenset(carried.lost | final.lost),
        expect=(before - taken - slack, before - taken + slack, why),
    )


def _plain(shape: Any, helix: _Helix) -> bool:
    """Whether the part round the threaded length is the rod alone, whole: a cylinder of the major radius between its ends (its volume, and three faces)."""
    zone = BRepPrimAPI_MakeCylinder(
        gp_Ax2(helix.at(0.0, helix.first), gp_Dir(*map(float, helix.z))),
        helix.radius + 2.0 * helix.carried,
        helix.end - helix.first,
    ).Shape()
    with boundary("measuring the rod round the thread"):
        there = boolean("intersect", [shape], [zone]).shape
    rod = math.pi * (helix.radius * helix.radius) * (helix.end - helix.first)
    return len(faces(there)) == 3 and abs(volume(there) - rod) <= 1e-9 * rod


#: Points the cut is held at: in the groove and in the thread between, round the axis and along it.
_HELD = 96


def _held(before: Any, after: Any, helix: _Helix) -> None:
    """Points well inside the groove are out of the part after, and points well inside the thread's own material are as they were.

    Each a fifth of the thread's depth or more from every surface of the
    groove and from the threaded length's ends, spread along the threaded
    length and across the groove and the thread by the golden ratio's turns
    (none chosen by the build's own faces): what a boolean that went wrong
    silently (a groove kept, a face classified on the wrong side) can't pass.
    """
    k = np.arange(_HELD, dtype=np.float64)
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    margin = helix.depth / 5.0
    rho = (
        helix.minor
        + margin
        + (helix.depth - 2.0 * margin) * np.mod(k * golden * golden, 1.0)
    )
    along = helix.first + (helix.end - helix.first) * np.mod(k * golden, 1.0)
    angle = (
        helix.hand * 2.0 * math.pi * (along - helix.low) / helix.pitch
    )  # the groove's middle at ``along``
    groove = (
        helix.pitch / 8.0 + (rho - helix.minor) * _TAN30
    )  # the groove's half-width at each radius
    across = 2.0 * np.mod(k * 0.7548776662466927, 1.0) - 1.0
    slant = margin / fs.cos(
        math.radians(30.0)
    )  # a margin square to a flank, along the axis
    in_groove = helix.points(rho, (groove - slant) * across, angle)
    in_thread = helix.points(
        rho, helix.pitch / 2.0 + (helix.pitch / 2.0 - groove - slant) * across, angle
    )

    def kept(points: Any) -> Any:
        s = fv.matmul(points - helix.origin, helix.z)
        return points[(s > helix.first + margin) & (s < helix.end - margin)]

    in_groove, in_thread = kept(in_groove), kept(in_thread)
    if not np.array_equal(_inside(after, in_thread), _inside(before, in_thread)):
        raise _MissedError("the thread's own material isn't what it was")
    if np.any(_inside(after, in_groove)):
        raise _MissedError("material is left in the groove")


def _inside(shape: Any, points: Any) -> Any:
    """Whether each point is inside the shape (any of its solids), by OpenCascade's classifier."""
    found = np.zeros(len(points), dtype=bool)
    for solid in solids(shape):
        classifier = BRepClass3d_SolidClassifier(solid)
        for k, p in enumerate(points):
            if not found[k]:
                classifier.Perform(gp_Pnt(float(p[0]), float(p[1]), float(p[2])), 1e-7)
                found[k] = classifier.State() == TopAbs_IN
    return found


def _samples(face: Any) -> Any:
    """Points spread over a face's parameter box (a swept face's box is all of it)."""
    surface = BRepAdaptor_Surface(TopoDS.Face(face))
    u0, u1 = surface.FirstUParameter(), surface.LastUParameter()
    v0, v1 = surface.FirstVParameter(), surface.LastVParameter()
    found = []
    for u in np.linspace(u0, u1, _SAMPLES + 2)[1:-1]:
        for v in np.linspace(v0, v1, _SAMPLES + 2)[1:-1]:
            p = surface.Value(float(u), float(v))
            found.append((p.X(), p.Y(), p.Z()))
    return np.asarray(found, dtype=np.float64)


def _sides(tool: Any) -> float:
    """The groove's surface area: what its volume may be off by, per mm its surfaces are off."""
    return sum(surface_area(face) for face in faces(tool))


def _off_profile(piece: Any, helix: _Helix) -> float:
    """How far the farthest sample of a piece's swept faces is from the groove's section, in the half-plane through the axis at it."""
    half_in, outer = helix.pitch / 8.0, helix.radius + helix.carried
    worst = 0.0
    for face in faces(piece):
        if plane_of(face) is not None:
            continue
        points = _samples(face)
        s = fv.matmul(points - helix.origin, helix.z)
        points = points[(s > helix.first + 1e-6) & (s < helix.end - 1e-6)]
        if not len(points):
            continue
        rho, u = helix.coordinates(points)
        # The section's boundary in (r, |u|): the root (r = minor, |u| <= P/8), a flank (|u| = P/8 + (r - minor) tan 30°).
        flank = np.abs(np.abs(u) - half_in - (rho - helix.minor) * _TAN30) * fs.cos(
            math.radians(30.0)
        )
        root = np.where(np.abs(u) <= half_in, np.abs(rho - helix.minor), np.inf)
        side = np.where(np.abs(u) <= helix.half, np.abs(rho - outer), np.inf)
        worst = max(worst, float(np.max(np.minimum(np.minimum(flank, root), side))))
    return worst


BUILDERS: Mapping[str, Callable[[Context], Product]] = {"thread": _thread}
