"""The check compiler: every leaf field of every item gives a check, or says why it can't (rule R1).

From a confirmed spec, the judge's own placement (:mod:`forge_checks.place`)
and the spec's own shape (:mod:`forge_checks.oracle`), :func:`compile_checks`
makes a :class:`~forge_checks.checks.Check` for every leaf field
(:func:`leaves`) of every copy of every item, each measuring the built part
through a kind of :mod:`forge_checks.kinds` at a target the placement puts
where the definitions say, always between built things. A leaf it can't
check is a :class:`NotChecked` with its reason, shown before building and
in the report. What the spec assumes (a position or angle left out, a
circle's start, a thread's whole length) is checked as the spec records it.

The leaves, by the field they are under (``id`` ``<item>/<field>[/<copy>]``):

- sizes (``length``, ``width``, ``height``, ``thickness``, ``depth``, ...):
  two fitted planes (``size``, ``depth``, ``wall``), a fitted round surface
  (``diameter``), a fitted cone or ball; a height or depth on a round side
  from the side's fitted axis, less its radius; a round wall between two
  fitted round surfaces or balls (``wall``);
- ``on``: told from the item on each other face of its host (``on``);
- ``place.<axis>``: from the host face's built edges or centre to the
  item's built centre or edge (``position``); round a side, from the side's
  ends; ``place.angle``: round a side's fitted axis (``angle``);
  ``place.concentric``: from the other item's built centre;
  ``place.pattern.<kind>.<value>``: pitches between built centres, a circle
  through them, its start and step round its centre, insets (``pattern``,
  ``angle``, ``position``); counts (``count``); its axis, told;
- choices (round or square ends, rectangle or circle, which axis, which
  edges, which faces a shell leaves open, the whole ball or the dome): told
  from each other choice's shape (``choice``);
- roundings and chamfers along each edge they round (``rounding``); a
  thread's profile, pitch, hand and length (``thread``).

An item's centre is its fitted axis (a round item's, a cone's), its fitted
centre (a ball's), or the middle of its two fitted sides (a box's, a
pocket's, a slot's). Where the spec's surface a check measures is nowhere on
the part's surface (a face all covered by what stands on it), the check
can't be made that way: it says so, and is not made.

The coverage radius the checks measure at is, at each place, half the
smallest feature whose item is there, and never more than 0.5 mm
(docs/V2-stage2.md, 5.4 and 5.8; docs/V2-stage4.md, 13.10).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from forge_spec.draft import (
    AxisPosition,
    Choice,
    Counterbore,
    Countersink,
    EdgeSet,
    Item,
    On,
    PartSpec,
    Pattern,
    Place,
)
from forge_spec.ends import ThroughAll, end_of
from forge_spec.schema import KINDS
from forge_spec.values import Count, Value
from numpy.typing import NDArray

from . import rounds
from .checks import Check
from .classes import (
    LINEAR,
    RADIUS,
    Tolerance,
    VerificationClass,
    general,
    general_angle,
    tolerance_of,
)
from .csg import pieces
from .items.compile import COMPILE
from .items.compile._common import (
    _PLAIN,
    _RAYS,
    _STRAIGHT,
    _WALL_REACH,
    Buried,
    _deg,
    _mm,
    _t,
    _v,
    leaves,
    rim_refs,
)
from .items.compile.pattern import PATTERN_COMPILE
from .kinds.angle import Turns
from .kinds.count import Copies
from .kinds.depth import Open
from .kinds.pattern import Circle, Pitches
from .kinds.position import (
    BallCentre,
    Centre,
    ConeRim,
    Hub,
    Mean,
    Middle,
    Position,
    Ref,
    RoundEdge,
    Spot,
)
from .kinds.rounding import Bevel, RoundBevel
from .kinds.size import Between
from .kinds.surfaces import Ball, Cone, Plane, Round, Tube
from .kinds.told import Told
from .measure import basis
from .oracle import Oracle, Rounded
from .outlines import Arc as OutlineArc
from .outlines import Segment
from .place import (
    Copy,
    FlatFace,
    Placed,
    RoundSide,
    material_at,
    section_of,
    unit,
)
from .telling import Alternative, clearance_for, tells
from .view import Box, Capability, Resolution, Side

__all__ = ["CheckSuite", "Finer", "NotChecked", "compile_checks", "leaves"]

Vec = tuple[float, float, float]
Array = NDArray[np.float64]
#: How far off a plane the part is asked which side it is, to tell a face of the part from one pressed against
#: another (mm): well past the oracle's band for on, well short of any feature.
_PARTING = 1e-3
_WALL_SPOTS = 9
#: How many of a plane's points :meth:`_Compiler.seen` asks about at once, spread over it, stopping at one on the part's surface.
_LOOKED_AT = 256

#: The coverage radius is half the smallest feature where it is, never more than this (mm).
LARGEST_RADIUS = 0.5
_FIT = frozenset({Capability.COVERAGE, Capability.CLASSIFY})
_SIDES = frozenset({Capability.CLASSIFY})


@dataclass(frozen=True)
class NotChecked:
    """A leaf field the compiler gives no check of its own, and why: shown before building and in the report.

    ``held_by`` names what holds it instead, where something does (its
    walls' checks hold a shell's ``of``; face accounting holds the places of
    copies too few to fit a circle through): such a field is checked
    otherwise, and leaves nothing of the spec unchecked (docs/V2-stage4.md,
    9.3). None where nothing does: the field is unchecked.
    """

    item: str
    field: str
    why: str
    held_by: str | None = None


@dataclass(frozen=True)
class Finer:
    """A box where the checks measure finer than everywhere: round one of ``item``'s solids, at half its smallest size."""

    item: str
    box: Box
    radius: float


@dataclass(frozen=True)
class CheckSuite:
    """Every check of a spec, what isn't checked, and the coverage they measure at: ``radius`` everywhere, finer in ``finer``."""

    checks: tuple[Check, ...]
    unchecked: tuple[NotChecked, ...]
    radius: float
    finer: tuple[Finer, ...] = ()

    @property
    def resolution(self) -> Resolution:
        """The coverage's radius everywhere and in each finer box (docs/V2-stage4.md, 13.10)."""
        return Resolution(self.radius, tuple((f.box, f.radius) for f in self.finer))


#: Why a revolution's end has no edges of its own to measure from: its rim is on a rounded side.
_ROUNDED_RIM = "the face's rim is on a rounded side: not fitted, for now"


def _unseen_edge(axis: str, sign: float) -> Buried:
    """Why a face's edge on one side isn't measured from: the spec's part has no surface there (what is joined there covers it)."""
    return Buried(
        f"the face's {'+' if sign > 0 else '-'}{axis} edge isn't on the part's surface"
    )


def _between(low: Ref | str, high: Ref | str) -> tuple[Ref | str, Ref | str, Ref | str]:
    """A face's two edges along an axis and the middle between them (measured along +axis: a rounded edge's far side is on the side the way points to at the +axis edge, and away from it at the -axis edge); the middle needs both, and without one has its reason."""
    if isinstance(low, str):
        return low, high, low
    if isinstance(high, str):
        return low, high, high
    far: Ref = RoundEdge(high.round, 1.0) if isinstance(high, RoundEdge) else high
    return low, high, Middle(far, low)


@dataclass
class _Compiler:
    spec: PartSpec
    placed: Placed
    part: Oracle
    checks: list[Check] = field(default_factory=list)
    unchecked: list[NotChecked] = field(default_factory=list)
    #: Each feature's size, and the item it is a size of.
    smallest: list[tuple[str, float]] = field(default_factory=list)
    #: What :meth:`seen` has found, by plane and rectangle: each plane is asked about often.
    _seen: dict[tuple[Plane, tuple[float, float] | None], bool] = field(
        default_factory=dict
    )

    # --- emitting -----------------------------------------------------
    def check(
        self,
        item: Item,
        name: str,
        kind: str,
        nominal: float,
        tolerance: Tolerance | None,
        target: object,
        copy: int | None = None,
        needs: frozenset[Capability] = _FIT,
    ) -> None:
        klass = {
            "exact": VerificationClass.EXACT,
            "bounded": VerificationClass.BOUNDED,
            "constrained": VerificationClass.CONSTRAINED,
        }[KINDS[item.kind].verification]
        at = f"{item.id}/{name}" + ("" if copy is None else f"/{copy}")
        again = sum(1 for c in self.checks if c.id == at or c.id.startswith(at + "."))
        if again:
            at += f".{again}"  # another measurement of the same copy's field (along another axis)
        self.checks.append(
            Check(at, item.id, name, kind, klass, needs, nominal, tolerance, target)
        )

    def skip(self, item: Item, name: str, why: str, held_by: str | None = None) -> None:
        """Note a field given no check of its own, and why: held by ``held_by`` where something else holds it (face accounting, where its faces are :class:`Buried`)."""
        if held_by is None and isinstance(why, Buried):
            held_by = "face accounting"
        self.unchecked.append(NotChecked(item.id, name, str(why), held_by))

    def size(self, item: Item, value: float) -> None:
        """Note a size of one of ``item``'s features, for the coverage radius where the item is."""
        if value > 0 and math.isfinite(value):
            self.smallest.append((item.id, value))

    # --- what the oracle says -----------------------------------------
    def seen(self, plane: Plane, half: tuple[float, float] | None = None) -> bool:
        """Whether any of the spec's plane is on the part's surface: within its reach of its point, or its own rectangle, or a rectangle of these half sizes round it.

        A rectangle given here has its sides along the plane's own two frame
        axes, in order (a face's axes); the points tried are at most a
        quarter of a millimetre apart, so a wall's rim a millimetre wide is
        found. A point of the plane is on the part's surface where the
        oracle has it on the surface, with the part behind it and air
        ahead (:data:`_PARTING` either way): a side of one item pressed
        against another's is on the surface of each and not the part's.
        The points are asked about a batch at a time, spread over the plane,
        until one is.
        """
        key = (plane, half)
        if key not in self._seen:
            self._seen[key] = self._looked_at(plane, half)
        return self._seen[key]

    def _looked_at(self, plane: Plane, half: tuple[float, float] | None) -> bool:
        n = _v(plane.normal)
        n /= float(fv.norm(n))
        k = int(np.argmax(np.abs(n)))
        if plane.first is not None and plane.half is not None and half is None:
            e1 = _v(plane.first) / float(fv.norm(plane.first))
            e2 = np.asarray(np.cross(n, e1), dtype=np.float64)
            half = plane.half
        elif abs(abs(float(n[k])) - 1.0) < 1e-12:
            e1, e2 = (_v(unit("+" + "xyz"[i])) for i in range(3) if i != k)
        else:
            _, e1, e2 = basis(n)
        if half is None:
            r = plane.reach if math.isfinite(plane.reach) else 1.0
            half = (r, r)
        counts = [int(min(200, max(25, math.ceil(2 * h / 0.25) + 1))) for h in half]
        a, b = np.meshgrid(
            np.linspace(-half[0], half[0], counts[0]),
            np.linspace(-half[1], half[1], counts[1]),
        )
        points = _v(plane.point) + a.reshape(-1, 1) * e1 + b.reshape(-1, 1) * e2
        if math.isfinite(plane.reach):
            points = points[fv.norm(points - _v(plane.point), axis=1) <= plane.reach]
        # A batch at a time, in an order spread over the plane (a fixed one): the answer is
        # whether any point is on the part's surface, found as soon as one is.
        spread = points[fv.Draws(len(points)).permutation(len(points))]
        for start in range(0, len(spread), _LOOKED_AT):
            batch = spread[start : start + _LOOKED_AT]
            on = batch[self.part.classify(batch) == Side.ON]
            if not len(on):
                continue
            ahead = self.part.classify(on + _PARTING * n) == Side.OUT
            behind = self.part.classify(on - _PARTING * n) == Side.IN
            if np.any(ahead & behind):
                return True
        return False

    def seen_round(self, surface: Round) -> bool:
        """Whether any of the spec's round surface is on the part's surface: tried every 15 degrees round it, at nine places along it."""
        w, e1, e2 = basis(surface.axis)
        turns = np.linspace(0.0, 2 * math.pi, 24, endpoint=False)
        along = np.linspace(surface.start, surface.end, 11)[1:-1]
        a, t = np.meshgrid(along, turns)
        points = (
            _v(surface.centre)
            + a.reshape(-1, 1) * w
            + surface.radius
            * (fv.cos(t).reshape(-1, 1) * e1 + fv.sin(t).reshape(-1, 1) * e2)
        )
        return bool(np.any(self.part.classify(points) == Side.ON))

    def seen_ball(self, ball: Ball) -> bool:
        """Whether any of the spec's ball is on the part's surface: tried at 400 points spread over it."""
        k = np.arange(400) + 0.5
        polar = fv.arccos(1 - 2 * k / 400)
        turn = math.pi * (1 + math.sqrt(5)) * k
        way = np.stack(
            [fv.cos(turn) * fv.sin(polar), fv.sin(turn) * fv.sin(polar), fv.cos(polar)],
            axis=1,
        )
        points = _v(ball.centre) + ball.radius * way
        return bool(np.any(self.part.classify(points) == Side.ON))

    def _wall_spot(self, face: FlatFace, wall: float) -> Array:
        """Where on a flat face a wall's thickness is measured: its centre, or, where something on the wall takes any of it, the place nearest the centre whose whole disc :data:`_WALL_REACH` across is the part's surface both sides (the face's, and the hollow's behind it), else the one most of whose disc is.

        A wall is measured between two discs, one on each of its faces; where
        an item on either face covered all but a sliver of a disc (generated
        part 4050: a round pocket 8 mm across on a shell's inner wall, 2 mm
        off its centre), the measurement rested on that sliver, and a file's
        mesh, coarser than the part, had no point on it. The places tried are
        a grid over the face, inset by the disc's reach; at each, points over
        both discs, the part's surface where the oracle has them on it.
        """
        n = _v(face.frame.n)
        e1, e2 = (_v(face.frame.u), _v(face.frame.v))
        centre = _v(face.centre)
        r = _WALL_REACH
        ring = np.array([(0.0, 0.0)] + [(f * r * fs.cos(t), f * r * fs.sin(t))
                                        for f in (0.5, 0.95) for t in np.linspace(0, 2 * math.pi, 12, endpoint=False)])  # fmt: skip

        def share(at: Array) -> float:
            disc = at + ring[:, :1] * e1 + ring[:, 1:] * e2
            both = np.concatenate([disc, disc - wall * n])
            return float(np.mean(self.part.classify(both) == Side.ON))

        if share(centre) >= 1.0:
            return centre
        h1, h2 = face.half
        steps = [
            np.linspace(-(h - r), h - r, _WALL_SPOTS) if h > r else np.zeros(1)
            for h in (h1, h2)
        ]
        best, best_key = centre, (share(centre), 0.0)
        for a in steps[0]:
            for b in steps[1]:
                at = centre + a * e1 + b * e2
                key = (share(at), -fs.hypot(a, b))
                if key > best_key:
                    best, best_key = at, key
        return best

    def face_plane(self, face: FlatFace, reach: float = math.inf) -> Plane:
        return Plane(face.centre, face.frame.n, reach)

    def face_rect(self, face: FlatFace) -> Plane:
        """A face's plane within its own rectangle (its outline's half sizes along its axes): a fit of it takes no point of another face beside it that is near its plane (a body's bottom 0.66 mm under a post's, within the window a pattern's pitch is fitted in)."""
        return Plane(
            face.centre,
            face.frame.n,
            first=face.frame.u,
            half=face.half,
        )

    def edge_plane(self, face: FlatFace, axis: str, sign: float) -> Plane:
        """The plane of the host face's edge on the ``sign`` side along ``axis``: the wall there, facing out of the material.

        A face's edge is where its outline ends: the side face of the body
        it is on (facing away from the face), or a wall of the recess it is
        the floor of (facing back across it). Which, the oracle says: just
        past the edge, under the face's level, is air (a side face) or
        material (a wall), as the part is before its roundings and
        chamfers: a joint's fill under an overhang sits just there.
        """
        a = _v(unit("+" + axis))
        k = 0 if face.axes[0] == axis else 1
        at = _v(face.centre) + sign * face.outline.half[k] * a
        return self.wall_at(face, at, a, sign, min(face.outline.half[1 - k], 4.0))

    def wall_at(
        self, face: FlatFace, at: Array, a: Array, sign: float, span: float
    ) -> Plane:
        """The wall at the face's edge through ``at``, square to ``a`` on the ``sign`` side: facing out of the material (air beyond: a body's side) or back across the face (material beyond: a recess's wall), as the oracle says."""
        n = _v(face.frame.n)
        held = self.part.held(at - 1e-3 * n, (sign * a)[None, :], finished=False)
        if held is not None:
            air = not bool(held[1][0])
        else:
            probe = at + sign * 1e-3 * a - 1e-3 * n
            air = int(self.part.classify(probe[None, :])[0]) == Side.OUT
        facing = sign * a if air else -sign * a
        return Plane(_t(at - 0.5 * min(span, 1.0) * n), _t(facing), max(span, 1.0))

    def outline_edge(
        self, face: FlatFace, axis: str, sign: float
    ) -> Plane | RoundEdge | str:
        """An outline face's edge on the ``sign`` side along ``axis`` (extrusion.md: where its box ends): the wall along a straight side there, or the round side of an arc reaching it; a reason where only a corner does."""
        k = 0 if face.axes[0] == axis else 1
        a = _v(unit("+" + axis))
        n = _v(face.frame.n)
        extreme = face.outline.centre[k] + sign * face.outline.half[k]
        first, second = ("xyz".index(x) for x in face.axes)

        def placed(p: tuple[float, float]) -> Array:
            found = _v(face.centre)
            found[first], found[second] = p
            return found

        lines = [q for q in face.outline.pieces() if isinstance(q, Segment)
                 and abs(q.a[k] - extreme) <= 1e-9 and abs(q.b[k] - extreme) <= 1e-9]  # fmt: skip
        if lines:
            line = max(lines, key=lambda q: fs.dist(q.a, q.b))
            middle = ((line.a[0] + line.b[0]) / 2, (line.a[1] + line.b[1]) / 2)
            return self.wall_at(
                face, placed(middle), a, sign, min(fs.dist(line.a, line.b) / 2, 4.0)
            )
        quadrant = (0.0 if k == 0 else math.pi / 2) + (0.0 if sign > 0 else math.pi)
        arcs = [q for q in face.outline.pieces() if isinstance(q, OutlineArc) and q.holds(quadrant)
                and abs(q.centre[k] + sign * q.radius - extreme) <= 1e-9]  # fmt: skip
        if not arcs:
            return f"the outline's edge along {'+' if sign > 0 else '-'}{axis} is a corner: nothing there to fit, for now"
        arc = max(arcs, key=lambda q: q.radius)
        depth = material_at(face.material, arc.centre)
        surface = Round(
            _t(placed(arc.centre)),
            _t(-n),
            arc.radius,
            0.0,
            min(max(depth, 0.0), 4.0),
            False,
        )
        return RoundEdge(surface, -1.0)

    def round_edge(self, face: FlatFace, axis: str, sign: float) -> RoundEdge | None:
        """The host face's edge on the ``sign`` side along ``axis`` where its outline's rounded corners leave less than :data:`_STRAIGHT` of it straight (a round-ended tab's far edge): a corner's round side or wall, as measured from it into the face; None where enough of the edge is straight.

        The edge's plane touches such a face along a short stretch or one
        line only, so it is measured from the rounding instead: the larger
        corner's, which reaches the edge as the other does. As
        :meth:`edge_plane` tells, a body's side there faces out of the
        material under the face, and a recess's wall faces into the recess.
        """
        k = 0 if face.axes[0] == axis else 1
        outline = face.outline
        if outline.shape != "rect":
            return None
        quadrants = ((1, 1), (-1, 1), (-1, -1), (1, -1))
        at_edge = [
            (r, q[1 - k])
            for r, q in zip(outline.corners, quadrants, strict=True)
            if q[k] == sign
        ]
        h, other = outline.half[k], outline.half[1 - k]
        if 2 * other - sum(r for r, _ in at_edge) >= _STRAIGHT:
            return None
        r, side = max(at_edge)
        if r <= 0:
            return (
                None  # a short edge between square corners: its plane is all there is
            )
        a = _v(unit("+" + axis))
        b = _v((face.frame.u, face.frame.v)[1 - k])
        n = _v(face.frame.n)
        centre = _v(face.centre) + sign * (h - r) * a + side * (other - r) * b
        # Just past the middle of the corner's quarter-circle, just under the face: air beyond
        # a body's side, the wall's material beyond a recess's floor (its ends may lie on
        # whatever the face's item stands on, as a half-disc tab's do).
        out = (sign * a + side * b) / math.sqrt(2.0)
        probe = centre + (r + 1e-3) * out - 1e-3 * n
        body = int(self.part.classify(probe[None, :])[0]) == Side.OUT
        # A body's side runs down through the material under the face; a
        # recess's wall up from its floor, as high as it may be (points past
        # its top aren't on its rounding, and are never measured).
        first, second = ("xyz".index(x) for x in face.axes)
        under = (float(centre[first]), float(centre[second]))
        depth = material_at(face.material, under) if body else 1.0
        surface = Round(
            _t(centre),
            _t(-n if body else n),
            r,
            0.0,
            min(max(depth, 0.0), 4.0),
            not body,
        )
        return RoundEdge(surface, -1.0)

    @staticmethod
    def cut_wall(
        copy: Copy, way: Array, at: float, across: Array, half: float
    ) -> Plane:
        """A cut's flat wall ``at`` from its centre along ``way``, facing back into the cut, as its own rectangle: ``half`` each way along ``across``, and from its mouth down to its floor."""
        assert copy.span is not None
        n = _v(copy.direction)
        depth = copy.span[1]
        centre = _v(copy.point) - depth / 2 * n + at * way
        return Plane(_t(centre), _t(-way), first=_t(across), half=(half, depth / 2))

    # --- tolerances ---------------------------------------------------
    @staticmethod
    def tol(value: object, column: str = LINEAR) -> Tolerance:
        if isinstance(value, Value):
            return tolerance_of(value, column)
        raise TypeError(f"a tolerance is a value's: {value!r}")

    # --- the item kinds -----------------------------------------------
    def item(self, item: Item) -> None:
        COMPILE[item.kind].checks(self, item)

    def copies(self, item: Item) -> tuple[Copy, ...]:
        return self.placed.copies.get(item.id, ())

    def faces(self, item_id: str, index: int) -> dict[str, FlatFace | RoundSide]:
        return dict(self.placed.faces.get((item_id, index), {}))

    def _not_placed(self, item: Item, why: str) -> None:
        for name in leaves(item):
            self.skip(item, name, why)

    def _profile(self, item: Item) -> None:
        """An outline of sides: each side's length, or an arc's radius and length, is a feature size; face accounting holds every point of it."""
        for side in section_of(item).pieces():
            if isinstance(side, OutlineArc):
                self.size(item, min(side.radius, side.radius * side.sweep))
            else:
                self.size(item, fs.dist(side.a, side.b))
        self.skip(item, "profile", "an outline has no single size: face accounting holds every point of the "
                  "built faces to it", held_by="face accounting")  # fmt: skip

    # Bodies -----------------------------------------------------------
    def _base(self, copy: Copy, reach: float) -> Plane | None:
        """The plane a standing body's base sits on: its host face round its foot."""
        if copy.host is None:
            return None
        face = self.placed.face(copy.host)
        if not isinstance(face, FlatFace):
            return None
        return Plane(copy.point, face.frame.n, reach)

    def _height(self, item: Item, name: str, copy: Copy, top: Plane, bottom: Plane | None, value: float,
                footprint: float) -> None:  # fmt: skip
        """A body's size along the way it grows: from its base (its own face, or the host face round its foot) to its top (the caller has seen it)."""
        if bottom is None:
            host_face = self.placed.face(copy.host) if copy.host is not None else None
            if isinstance(host_face, RoundSide):
                # From the side's fitted axis to its top, less the side's radius: on a rod's
                # outside it grows away from the axis, inside a bore towards it (place.md).
                side = Round(
                    host_face.start,
                    host_face.frame.n,
                    host_face.radius,
                    0.0,
                    host_face.length,
                    not host_face.outward,
                )
                less = host_face.radius if host_face.outward else -host_face.radius
                self.check(item, name, "size", value, self.tol(item.get(name)),
                           Position(copy.direction, Centre(side), top, less), copy.index)  # fmt: skip
                return
            base = self._base(copy, footprint + 4.0)
            if base is None:
                self.skip(item, name, "it stands on no flat face")
                return
            if not self.seen(base):
                self.skip(item, name, "the face it stands on isn't seen round its foot")
                return
            bottom = base
        self.check(item, name, "size", value, self.tol(item.get(name)),
                   Between(top, bottom, copy.direction), copy.index)  # fmt: skip

    def _box_body(
        self,
        item: Item,
        sizes: Callable[[Copy], dict[str, tuple[str, float]]],
        height: str | None,
    ) -> None:
        """A block, post, rib or tab: its sizes across (by frame axis, each copy's own) and its height along the way it grows.

        Each side's plane is where the box round the copy puts it (a face a
        shell leaves open still has its walls' rims there), and only its own
        rectangle of that plane is measured: a side flush with its host's (an
        upright spanning the base it stands on) is the item's own size only
        where the item is, and the host's side beside it says nothing of it. A
        side with none of it on the part's surface can't be measured that way.
        Each copy's sizes run along its own axes: copies round a side face
        different ways.
        """
        for copy in self.copies(item):
            assert copy.lo is not None and copy.hi is not None
            lo, hi = _v(copy.lo), _v(copy.hi)
            middle = (lo + hi) / 2
            extent = (hi - lo) / 2
            up = _v(copy.direction)
            k_up = int(np.argmax(np.abs(up)))
            for name, (axis, value) in sizes(copy).items():
                k = "xyz".index(axis)
                a = _v(unit("+" + axis))
                others = [i for i in range(3) if i != k]
                half = (float(extent[others[0]]), float(extent[others[1]]))
                first = _t(unit("+" + "xyz"[others[0]]))
                plus = Plane(
                    _t(np.where(np.arange(3) == k, hi, middle)),
                    _t(a),
                    first=first,
                    half=half,
                )
                minus = Plane(
                    _t(np.where(np.arange(3) == k, lo, middle)),
                    _t(-a),
                    first=first,
                    half=half,
                )
                if not (self.seen(plus, half) and self.seen(minus, half)):
                    self.skip(
                        item,
                        name,
                        Buried(f"its {axis} faces aren't both on the part's surface"),
                    )
                    continue
                self.check(
                    item,
                    name,
                    "size",
                    value,
                    self.tol(item.get(name)),
                    Between(plus, minus, _t(a)),
                    copy.index,
                )
                self.size(item, value)
            if height is None:
                continue
            top_at = hi if up[k_up] > 0 else lo
            low_at = lo if up[k_up] > 0 else hi
            across = [i for i in range(3) if i != k_up]
            top = Plane(_t(np.where(np.arange(3) == k_up, top_at, middle)), _t(up),
                        first=_t(unit("+" + "xyz"[across[0]])),
                        half=(float(extent[across[0]]), float(extent[across[1]])))  # fmt: skip
            bottom = (
                Plane(_t(np.where(np.arange(3) == k_up, low_at, middle)), _t(-up))
                if copy.host is None
                else None
            )
            value = _mm(item.get(height))
            self.size(item, value)
            footprint = float(max(extent[across[0]], extent[across[1]]))
            if bottom is not None and not self.seen(bottom, (footprint, footprint)):
                self.skip(
                    item, height, Buried("its base is nowhere on the part's surface")
                )
                continue
            if not self.seen(top, (float(extent[across[0]]), float(extent[across[1]]))):
                self.skip(
                    item, height, Buried("its top is nowhere on the part's surface")
                )
                continue
            self._height(item, height, copy, top, bottom, value, footprint)

    def _round_end(self, item: Item) -> None:
        """A round-ended tab's width (its end's diameter) and length (from the face it stands on to its end's outermost point)."""
        width, length = (_mm(item.get(n)) for n in ("width", "length"))
        r = width / 2
        self.size(item, r)
        for copy in self.copies(item):
            end = self._tab_end(item, copy)
            self.check(
                item,
                "width",
                "diameter",
                width,
                self.tol(item.get("width")),
                end,
                copy.index,
            )
            base = self._base(copy, r + 4.0)
            if base is None or not self.seen(base):
                self.skip(
                    item, "length", "the face it stands on isn't seen round its foot"
                )
                continue
            self.check(item, "length", "size", length, self.tol(item.get("length")),
                       Position(copy.direction, base, RoundEdge(end, 1.0)), copy.index)  # fmt: skip

    def _plain(self, item: Item) -> float:
        """How far a rod's round side runs from its base before its thread starts (thread.md: a thread runs its length from the free end); its whole length or height where nothing threads it."""
        whole = _mm(item.get(COMPILE[item.kind].rod_length))
        for other in self.spec.items:
            if COMPILE[other.kind].threads and other.get("of") == item.id:
                threaded = other.get("length")
                return whole - _mm(threaded) if threaded is not None else 0.0
        return whole

    def _round_body(
        self, item: Item, diameter: str, length: str, bore: str | None = None
    ) -> None:
        """A cylinder's, a tube's or a boss's diameters (its side and bore, fitted) and its length or height, from its base to its far end (where a shell opens it, its walls' rim).

        A threaded rod's side is fitted only where it is plain, from its base
        to where its thread starts; threaded all but :data:`_PLAIN` of it, its
        diameter is held by its thread's check (the thread's crests are its
        major diameter, the rod's).
        """
        radius = _mm(item.get(diameter)) / 2
        inner = _mm(item.get(bore)) / 2 if bore is not None else 0.0
        value = _mm(item.get(length))
        plain = self._plain(item) if COMPILE[item.kind].threadable else value
        self.size(item, radius)
        if bore is not None:
            self.size(item, inner)
        if plain < _PLAIN:
            self.skip(item, diameter, "its side is threaded all along: the thread's crests are its diameter",
                      "its thread's check")  # fmt: skip
        for copy in self.copies(item):
            up = _v(copy.direction)
            if plain >= _PLAIN:
                self.check(item, diameter, "diameter", 2 * radius, self.tol(item.get(diameter)),
                           Round(copy.point, copy.direction, radius, 0.0, plain, False), copy.index)  # fmt: skip
            if bore is not None:
                self.check(item, bore, "diameter", 2 * inner, self.tol(item.get(bore)),
                           Round(copy.point, copy.direction, inner, 0.0, value, True), copy.index)  # fmt: skip
            top = Plane(_t(_v(copy.point) + value * up), copy.direction, radius)
            if not self.seen(top):
                self.skip(
                    item, length, Buried("its far end is nowhere on the part's surface")
                )
                continue
            bottom = None
            if copy.host is None:
                bottom = Plane(copy.point, _t(-up), radius)
                if not self.seen(bottom):
                    self.skip(
                        item,
                        length,
                        Buried("its base is nowhere on the part's surface"),
                    )
                    continue
            self._height(item, length, copy, top, bottom, value, radius)

    def _axis(self, item: Item) -> None:
        """A first body's axis, told from the other axes."""
        if item.get("axis") is not None:
            self._choice(item, "axis")

    def _standing_fields(self, item: Item) -> None:
        """A body's or standing feature's ``on`` and ``place``, if it stands on a face."""
        if item.get("on") is not None:
            self._on(item)
            self._place(item)

    # Cuts -------------------------------------------------------------
    def _cut_depth(
        self,
        item: Item,
        copy: Copy,
        radius: float,
        reach: float,
        depth: float,
        outline: tuple[str, float, float] | None = None,
    ) -> None:
        """A cut's depth: right through (lines down its axis), or to its floor (two planes).

        The floor is looked for over its own outline, a rectangle's (its
        first axis, and its half sizes along it and the other), or a disc
        within ``reach`` of its centre.
        """
        if isinstance(end_of(item), ThroughAll):
            self.check(item, "depth", "depth", depth, None, Open(copy.point, _t(-_v(copy.direction)), depth, radius),
                       copy.index, _RAYS)  # fmt: skip
            return
        at = _t(_v(copy.point) - depth * _v(copy.direction))
        floor = (
            Plane(at, copy.direction, first=unit("+" + outline[0]), half=outline[1:])
            if outline is not None
            else Plane(at, copy.direction, reach)
        )
        self._floor(
            item, "depth", copy, floor, depth, self.tol(item.get("depth")), reach
        )

    def _floor(self, item: Item, name: str, copy: Copy, floor: Plane, depth: float, tolerance: Tolerance,
               reach: float) -> None:  # fmt: skip
        host_face = self.placed.face(copy.host) if copy.host is not None else None
        if isinstance(host_face, RoundSide):
            # From the side's surface at its centre: from the side's fitted axis, less its radius
            # (out from a rod's outside the floor is nearer the axis; out from a bore, farther).
            side = Round(host_face.start, host_face.frame.n, host_face.radius, 0.0, host_face.length,
                         not host_face.outward)  # fmt: skip
            if not self.seen(floor):
                self.skip(item, name, "its floor isn't on the part's surface")
                return
            less = -host_face.radius if host_face.outward else host_face.radius
            self.check(item, name, "depth", depth, tolerance,
                       Position(_t(-_v(copy.direction)), Centre(side), floor, less), copy.index)  # fmt: skip
            self.size(item, depth)
            return
        if host_face is None:  # pragma: no cover - a cut is always on a face
            return
        mouth = Plane(copy.point, copy.direction, reach + 4.0)
        if not (self.seen(mouth) and self.seen(floor)):
            self.skip(
                item,
                name,
                "its floor or the face round its mouth isn't on the part's surface",
            )
            return
        self.check(
            item,
            name,
            "depth",
            depth,
            tolerance,
            Between(mouth, floor, copy.direction),
            copy.index,
        )
        self.size(item, depth)

    def _cut_fields(self, item: Item) -> None:
        self._on(item)
        self._place(item)
        self._count(item)

    # Placing ------------------------------------------------------------
    def _main(self, item: Item, copy: Copy) -> Ref | None:
        """What a copy's centre is measured from: its fitted axis, or the middle of its fitted sides."""
        return COMPILE[item.kind].main(self, item, copy)

    def _own_outline(
        self, item: Item, copy: Copy, axis: str
    ) -> tuple[Ref, Ref, Ref] | None:
        """An extrusion's own edges along ``axis`` and their middle, from its far end's outline (as its host face's are found)."""
        face = self.faces(item.id, copy.index).get("+end")
        if not isinstance(face, FlatFace) or axis not in face.axes:
            return None
        refs = self._outline_refs(face, axis)
        return None if isinstance(refs, str) else refs

    def _shift(self, item: Item, copy: Copy, axis: str) -> float:
        """How far along ``axis`` the centre :meth:`_centre_ref` finds is from the point ``place`` puts the item at: an extrusion's box's middle is off its point (0, 0)."""
        return COMPILE[item.kind].shift(self, item, copy, axis)

    def _turned_pieces(
        self, item: Item
    ) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        """A revolution's straight sides that turn into round sides or cones: each from its lower end to its upper (distance, height)."""
        found = []
        for q in section_of(item).pieces():
            if isinstance(q, Segment):
                low, high = sorted((q.a, q.b), key=lambda p: p[1])
                if high[1] - low[1] > 1e-9 and max(low[0], high[0]) > 1e-9:
                    found.append((low, high))
        return found

    def _turned_axis(self, item: Item, copy: Copy) -> Ref | None:
        """A revolution's axis, fitted: of its straight side along the axis (a round side) with the most surface, else of its sloping one (a cone) with the most; None where its side is all arcs.

        The most surface, not the longest: the most of the part's surface to
        fit a circle to. Generated part 8032, a pulley turned from 0.016 mm
        off its axis: its longest round side was the bore down its middle,
        0.032 mm across, which no circle can be fitted to at the judge's
        resolution (its built points there lie on one line), and both
        its place checks held the part as asked; its rims, 6.276 mm across
        and 1.112 mm long, fix the same axis.
        """
        pieces = self._turned_pieces(item)
        upright = [(low, high) for low, high in pieces if abs(low[0] - high[0]) <= 1e-9]
        if upright:
            (r, h0), (_, h1) = max(upright, key=lambda p: p[0][0] * (p[1][1] - p[0][1]))
            return Centre(
                Round(
                    copy.point,
                    copy.direction,
                    r,
                    h0,
                    h1,
                    self._turned_inside(item, r, (h0 + h1) / 2),
                )
            )
        if pieces:
            (r0, h0), (r1, h1) = max(
                pieces, key=lambda p: (p[0][0] + p[1][0]) * fs.dist(*p)
            )
            cone = Cone(
                copy.point,
                copy.direction,
                (r0, r1),
                (h0, h1),
                self._turned_inside(item, (r0 + r1) / 2, (h0 + h1) / 2),
            )
            return ConeRim(cone, h0, 0.0)
        return None

    def _turned_inside(self, item: Item, r: float, h: float) -> bool:
        """Whether a revolution's side at (r, h) has its material further out (a bore): the outline holds the point just outside it."""
        section = section_of(item)
        return section.contains((r + 1e-6, h), tol=0.0) and not section.contains(
            (r - 1e-6, h), tol=0.0
        )

    def _turned_edge(self, item: Item, copy: Copy) -> Ref | None:
        """A revolution's edge where it reaches furthest from its axis (place.md: its widest), as measured from outside: its widest straight side along the axis, or the rim of a cone at its widest; None where only an arc reaches there."""
        section = section_of(item)
        widest = section.centre[0] + section.half[0]
        pieces = self._turned_pieces(item)
        upright = [
            (low, high)
            for low, high in pieces
            if abs(low[0] - widest) <= 1e-9 and abs(high[0] - widest) <= 1e-9
        ]
        if upright:
            (r, h0), (_, h1) = max(upright, key=lambda p: p[1][1] - p[0][1])
            return RoundEdge(Round(copy.point, copy.direction, r, h0, h1, False), -1.0)
        for (r0, h0), (r1, h1) in pieces:
            if max(r0, r1) >= widest - 1e-9:
                cone = Cone(copy.point, copy.direction, (r0, r1), (h0, h1), False)
                return ConeRim(cone, h0 if r0 >= r1 else h1, -1.0)
        return None

    def _recess(self, item: Item, radius: float) -> float:
        bore, sink = item.get("counterbore"), item.get("countersink")
        if isinstance(bore, Counterbore):
            return _mm(bore.depth)
        if isinstance(sink, Countersink):
            return (_mm(sink.diameter) / 2 - radius) / fs.tan(
                math.radians(_deg(sink.angle) / 2)
            )
        return 0.0

    def _sides_along(
        self, item: Item, copy: Copy, axis: str
    ) -> tuple[Plane, Plane] | None:
        """A rectangular item's two fitted sides across ``axis`` (+ first), facing out of its material; None where they are all arc (:meth:`_round_ends`)."""
        return COMPILE[item.kind].sides(self, item, copy, axis)

    def _box_sides(
        self, item: Item, copy: Copy, axis: str
    ) -> tuple[Plane, Plane] | None:
        """A box item's two sides across ``axis`` (+ first) from the box round its copy, each a disc in the middle of the side as wide as the side allows: a box standing round a side has no faces of its own to take things.

        A round-ended tab's sides stop where its rounding starts: each disc
        is round the middle of their straight part.
        """
        if copy.lo is None or copy.hi is None:
            return None
        lo, hi = _v(copy.lo), _v(copy.hi)
        k = "xyz".index(axis)
        middle = (lo + hi) / 2
        reach = float(min(hi[i] - lo[i] for i in range(3) if i != k)) / 2
        straight = COMPILE[item.kind].straight(self, item)
        if straight is not None:
            up = _v(copy.direction)
            j = int(np.argmax(np.abs(up)))
            middle[j] = float((_v(copy.point) + straight / 2 * up)[j])
            reach = min(reach, straight / 2)
        a = _v(unit("+" + axis))
        at = np.arange(3) == k
        return (
            Plane(_t(np.where(at, hi, middle)), _t(a), reach),
            Plane(_t(np.where(at, lo, middle)), _t(-a), reach),
        )

    def _centre_ref(self, item: Item, copy: Copy, axis: str) -> Ref | None:
        """A copy's built centre along ``axis``: its fitted axis, or the middle of its fitted sides (where they are all arc, of their axes).

        An extrusion's is the middle of its box's edges, which is
        :meth:`_shift` from its point along ``axis``.
        """
        return COMPILE[item.kind].centre_ref(self, item, copy, axis)

    def _no_centre(self, item: Item, group: list[Copy], axis: str) -> str:
        """Why no copy's centre along ``axis`` is found: a box's sides there aren't on the part's surface (:class:`Buried`), or it can't be fitted."""
        return COMPILE[item.kind].no_centre(self, item, group, axis)

    def _edge_ref(self, item: Item, copy: Copy, axis: str, sign: float) -> Ref | None:
        """A copy's edge on the ``sign`` side along ``axis``, as measured from that side's face edge inwards (along ``-sign`` times the axis).

        A hole's is its widest circle's (place.md): its counterbore's, or its
        countersink's rim at the mouth, where it has one.
        """
        return COMPILE[item.kind].edge_ref(self, item, copy, axis, sign)

    def _round_ends(
        self, item: Item, copy: Copy, axis: str
    ) -> tuple[Round, Round] | None:
        """An item's two sides across ``axis`` (the -axis one first) where each is all arc, or flat for less than :data:`_STRAIGHT`: a round surface of each that reaches as far; None where they are flat (or the item is round itself).

        A round-ended slot's ends, along it; across it too, when it is about
        as long as it is wide. A rectangular pocket's ends where its corners
        are rounded to (about) half its size across them: an end's corner on
        the other axis's + side. A round-ended tab's sides across its width,
        when it is (about) all half-disc: its end's rounding, which is
        tangent to them where it starts. A flat side's plane would touch an
        arc along one line only, and so short a flat stretch has too few
        built points to fit.
        """
        if copy.axes is None or axis not in copy.axes:
            return None
        return COMPILE[item.kind].round_ends(self, item, copy, axis)

    def _tab_end(self, item: Item, copy: Copy) -> Round:
        """A round-ended tab's rounding: the half-cylinder across its thickness, its axis ``length`` less half its width out from the face (tab.md)."""
        thin = self._choice_value(item, "thickness_along")
        width, length, thickness = (
            _mm(item.get(k)) for k in ("width", "length", "thickness")
        )
        r = width / 2
        out = _v(copy.point) + (length - r) * _v(copy.direction)
        return Round(
            _t(out), unit("+" + str(thin)), r, -thickness / 2, thickness / 2, False
        )

    def _outline_edge_ref(self, face: FlatFace, axis: str, sign: float) -> Ref | str:
        """An outline face's edge on one side along ``axis``: its box's edge there (extrusion.md), or why it isn't found."""
        side = self.outline_edge(face, axis, sign)
        if isinstance(side, str):
            return side
        if isinstance(side, RoundEdge):
            seen = isinstance(side.round, Round) and self.seen_round(side.round)
        else:
            seen = self.seen(side)
        return side if seen else _unseen_edge(axis, sign)

    def _outline_refs(self, face: FlatFace, axis: str) -> tuple[Ref, Ref, Ref] | str:
        """An outline face's edges along ``axis`` and the middle between them: its box's edges and centre (extrusion.md)."""
        low, high, middle = _between(
            *(self._outline_edge_ref(face, axis, sign) for sign in (-1.0, 1.0))
        )
        for ref in (low, high, middle):
            if isinstance(ref, str):
                return ref
        assert (
            not isinstance(low, str)
            and not isinstance(high, str)
            and not isinstance(middle, str)
        )
        return low, high, middle

    def _turned_rim(
        self, owner: Item, copy: Copy, end: str
    ) -> tuple[Ref | str, Ref | str, Ref] | str:
        """A revolution's flat end's outer rim, and its centre (revolution.md): where the outline's side meets the end there, the round side it turns (a straight side along the axis) or the cone (a sloping one)."""
        section = section_of(owner)
        height = section.centre[1] + (
            section.half[1] if end == "+end" else -section.half[1]
        )
        flat = [q for q in section.pieces() if isinstance(q, Segment) and abs(q.a[1] - height) <= 1e-9
                and abs(q.b[1] - height) <= 1e-9]  # fmt: skip
        if len(flat) != 1:
            return "it has no flat end there"
        rim = max(flat[0].a, flat[0].b, key=lambda p: p[0])
        beside = [q for q in section.pieces() if q is not flat[0]
                  and any(fs.dist(p, rim) <= 1e-9 for p in q.ends())]  # fmt: skip
        q = beside[0] if len(beside) == 1 else None
        if isinstance(q, Segment):
            (r0, h0), (r1, h1) = sorted((q.a, q.b), key=lambda p: p[1])
            if h1 - h0 > 1e-9 and abs(r1 - r0) <= 1e-9:
                side = Round(copy.point, copy.direction, rim[0], h0, h1, False)
                return RoundEdge(side, -1.0), RoundEdge(side, -1.0), Centre(side)
            if h1 - h0 > 1e-9:
                cone = Cone(copy.point, copy.direction, (r0, r1), (h0, h1), False)
                rim_edge = ConeRim(cone, height, -1.0)
                return rim_edge, rim_edge, ConeRim(cone, height, 0.0)
        # Its rim is on a rounded side: its axis alone is fitted.
        axis = self._turned_axis(owner, copy)
        if axis is None:
            return "its rim and its axis are on rounded sides: not fitted, for now"
        return _ROUNDED_RIM, _ROUNDED_RIM, axis

    def _seam(self, host: tuple[str, int, str], axis: str) -> tuple[float, Ref] | None:
        """Where a face runs on smoothly into a round surface, along ``axis``: which side (1 or -1) and the round surface's fitted axis, the line it starts on; None where it doesn't.

        A round-ended tab's narrow side stops where its end's rounding
        starts (tab.md), with no edge built there: the rounding's axis is
        level with it.
        """
        owner = self.spec.item(host[0])
        if owner is None:
            return None
        return COMPILE[owner.kind].seam(self, owner, host, axis)

    def _face_refs(
        self, host: tuple[str, int, str], face: FlatFace, axis: str
    ) -> tuple[Ref | str, Ref | str, Ref | str] | str:
        """A host face's built edges along ``axis`` (the -axis one, the +axis one, each as measured from it into the face) and its built centre; each, or why it isn't found.

        A rectangle's edges are the fitted planes of the walls or sides
        there; a round face's, the fitted round side or cone of what it is
        the end of (or the ball a dome's flat face is cut from), and its
        centre that side's axis. A revolution's end whose rim is on a rounded
        side has its centre (the revolution's axis) but no edges. Each edge
        stands alone: a position measured from one edge needs only that edge
        built where the spec has it (its other edge may be inside something
        joined there); the centre needs both.
        """
        if face.outline.shape == "profile":
            return _between(
                *(self._outline_edge_ref(face, axis, sign) for sign in (-1.0, 1.0))
            )
        if face.outline.shape == "rect":
            seam = self._seam(host, axis)
            edges: list[Ref | str] = []
            for sign in (-1.0, 1.0):
                if seam is not None and seam[0] == sign:
                    edges.append(seam[1])
                    continue
                rounded = self.round_edge(face, axis, sign)
                if rounded is not None:
                    assert isinstance(rounded.round, Round)
                    edges.append(
                        rounded
                        if self.seen_round(rounded.round)
                        else _unseen_edge(axis, sign)
                    )
                    continue
                plane = self.edge_plane(face, axis, sign)
                edges.append(plane if self.seen(plane) else _unseen_edge(axis, sign))
            return _between(*edges)
        owner = self.spec.item(host[0])
        if owner is None:
            return "its host isn't in the spec"
        owner_copy = self.copies(owner)[host[1]]
        inside = self.faces(host[0], host[1]).get("inner side")
        if host[2].startswith("inner") and isinstance(inside, RoundSide):
            # A hollow's inner end: its edges are the hollow's own side (place.md: a face's edges are its own).
            return rim_refs(
                Round(
                    inside.start,
                    inside.frame.n,
                    inside.radius,
                    0.0,
                    inside.length,
                    True,
                )
            )
        found = COMPILE[owner.kind].face_refs(self, owner, owner_copy, host[2])
        if found is None:
            return f"a round face of a {owner.kind}: its edge isn't fitted, for now"
        return found

    def _place(self, item: Item) -> None:
        """Where the item is on the face it is on: as its place gives it, and where that gives nothing, centred (or at 0 degrees round a side), the assumptions the spec records (place.md)."""
        copies = self.copies(item)
        if not copies or copies[0].host is None:
            return  # a first body sits on the origin
        if COMPILE[item.kind].threadable and self._plain(item) < _PLAIN:
            for name in leaves(item):
                if name.startswith("place."):
                    self.skip(item, name, "its side is threaded all along: the thread's profile is held about its axis",
                              "its thread's check")  # fmt: skip
            return
        given = item.get("place")
        place = given if isinstance(given, Place) else Place({}, None, None, None, None)
        face = self.placed.face(copies[0].host)
        if place.concentric:
            self._concentric(item, place)
            return
        if isinstance(face, RoundSide):
            self._round_place(item, place, face)
            return
        pattern = place.pattern
        fixed = (
            PATTERN_COMPILE[pattern.kind].fixed_axes(pattern, face.axes)
            if pattern is not None
            else set()
        )
        centred = AxisPosition("centred", None, None, "centre", None)
        axes = {
            **{axis: centred for axis in face.axes if axis not in fixed},
            **place.axes,
        }
        for axis, position in axes.items():
            self._axis_position(item, axis, position, face, pattern)
        if place.angle is not None:
            self.skip(item, "place.angle", "an angle places an item round a round side")
        if pattern is not None:
            self._pattern(item, pattern, face)

    def _groups(self, item: Item) -> Iterator[list[Copy]]:
        """The copies, by the host copy they are on (a pattern's copies on one host together)."""
        by_host: dict[tuple[str, int, str] | None, list[Copy]] = {}
        for copy in self.copies(item):
            by_host.setdefault(copy.host, []).append(copy)
        yield from by_host.values()

    def _axis_position(self, item: Item, axis: str, position: AxisPosition, face: FlatFace,
                       pattern: Pattern | None) -> None:  # fmt: skip
        """A position along one axis of a flat face: from the face's built edge, or its built centre, to the item's built centre or edge (place.md).

        A pattern is placed by its centre (a row's, a grid's, a rectangle's,
        a circle's: the mean of its copies' built centres; an arc's: the
        centre of the circle through them), except that from an edge a row,
        grid or rectangle is measured to its nearest copy.
        """
        name = f"place.{axis}"
        a = _v(unit("+" + axis))
        for group in self._groups(item):
            host = group[0].host
            assert host is not None
            host_face = self.placed.face(host)
            assert isinstance(host_face, FlatFace)
            refs = self._face_refs(host, host_face, axis)
            if isinstance(refs, str):
                self.skip(item, name, refs)
                return
            minus, plus, middle = refs
            whole = pattern is not None and PATTERN_COMPILE[pattern.kind].round
            if position.mode == "side":
                assert position.side is not None and position.distance is not None
                sign = 1.0 if position.side[0] == "+" else -1.0
                edge = plus if sign > 0 else minus
                if isinstance(edge, str):
                    self.skip(item, name, edge)
                    return
                inward = _t(-sign * a)
                if whole:
                    ref: Ref | str | None = self._pattern_centre(
                        item, group, axis, pattern
                    )
                    copy = group[0]
                else:
                    copy = sorted(
                        group, key=lambda c: -sign * float(fv.dot(c.point, a))
                    )[0]
                    ref = (
                        self._edge_ref(item, copy, axis, sign)
                        if position.to == "edge"
                        else self._centre_ref(item, copy, axis)
                    )
                if ref is None or isinstance(ref, str):
                    self.skip(item, name, ref or "the item can't be fitted there")
                    return
                less = (
                    0.0
                    if position.to == "edge" and not whole
                    else -sign * self._shift(item, copy, axis)
                )
                self.check(item, name, "position", _mm(position.distance), self.tol(position.distance),
                           Position(inward, edge, ref, less), copy.index)  # fmt: skip
                continue
            if isinstance(middle, str):
                self.skip(item, name, middle)
                return
            ref = (
                self._centre_ref(item, group[0], axis)
                if len(group) == 1
                else self._pattern_centre(item, group, axis, pattern)
            )
            if ref is None or isinstance(ref, str):
                self.skip(item, name, ref or self._no_centre(item, group, axis))
                return
            if position.mode == "offset" and position.distance is not None:
                offset, tolerance = _mm(position.distance), self.tol(position.distance)
            else:
                k = 0 if host_face.axes[0] == axis else 1
                offset, tolerance = 0.0, general(host_face.outline.half[k])
            less = self._shift(item, group[0], axis)
            self.check(
                item,
                name,
                "position",
                offset,
                tolerance,
                Position(_t(a), middle, ref, less),
                group[0].index,
            )

    def _spots(
        self, item: Item, group: list[Copy], face: FlatFace
    ) -> tuple[Spot, ...] | str:
        """Each copy's built centre in the face's plane (along its first axis and its second), or why they can't all be found."""
        spots = []
        for copy in group:
            first, second = (self._centre_ref(item, copy, axis) for axis in face.axes)
            if first is None or second is None:
                return "the copies' centres can't be fitted"
            spots.append(Spot(first, second))
        return tuple(spots)

    def _pattern_centre(
        self, item: Item, group: list[Copy], axis: str, pattern: Pattern | None
    ) -> Ref | str | None:
        """A pattern's built centre along ``axis``: the mean of its copies' built centres, or an arc's: the centre of the circle through them."""
        if pattern is not None and PATTERN_COMPILE[pattern.kind].centre_from_circle:
            host = group[0].host
            assert host is not None
            face = self.placed.face(host)
            assert isinstance(face, FlatFace)
            if len(group) < 3:
                return "an arc of fewer than three copies doesn't fix its centre: its place is told by face accounting"
            spots = self._spots(item, group, face)
            if isinstance(spots, str):
                return spots
            plane = (face.frame.u, face.frame.v)
            return Hub(spots, (plane[0], plane[1]))
        centres = [self._centre_ref(item, copy, axis) for copy in group]
        if any(c is None for c in centres):
            return None
        return Mean(tuple(c for c in centres if c is not None))

    def _concentric(self, item: Item, place: Place) -> None:
        """Concentric with another item: along each of the face's axes, from that item's built centre to this one's."""
        partner = self.spec.item(str(place.concentric))
        made = 0
        for copy in self.copies(item):
            others = self.copies(partner) if partner is not None else ()
            match = [
                o
                for o in others
                if np.allclose(
                    np.cross(_v(o.point) - _v(copy.point), _v(copy.direction)),
                    0,
                    atol=1e-6,
                )
            ]
            if partner is None or not match or copy.axes is None:
                continue
            for axis in copy.axes:
                mine = self._centre_ref(item, copy, axis)
                theirs = self._centre_ref(partner, match[0], axis)
                if mine is None or theirs is None:
                    continue
                self.check(item, "place.concentric", "position", 0.0, general(0.0),
                           Position(unit("+" + axis), theirs, mine), copy.index)  # fmt: skip
                made += 1
        if not made:
            self.skip(item, "place.concentric", "the two centres can't both be fitted")

    def _round_copy(
        self, item: Item, copy: Copy, side: RoundSide
    ) -> tuple[Round | Middle, float, float] | None:
        """A copy round a side, as its angle is measured: its fitted axis, or a post's two sides square to the way round; its size round the side; and its middle's distance from the side's axis."""
        return COMPILE[item.kind].round_copy(self, item, copy, side)

    def _round_place(self, item: Item, place: Place, side: RoundSide) -> None:
        """Round a side: the copies' angles round the side's fitted axis, seen along it (a circle's or an arc's first at ``place.angle``, an arc's step), their counts, and their places along the axis from the side's built ends."""
        pattern = place.pattern
        for group in self._groups(item):
            host = group[0].host
            assert host is not None
            face = self.placed.face(host)
            assert isinstance(face, RoundSide)
            axis = face.frame.n
            zero = face.frame.u
            quarter = np.cross(_v(axis), _v(zero))
            found = [self._round_copy(item, copy, face) for copy in group]
            names = ["place.angle"] + (
                [f"place.pattern.{pattern.kind}.step"]
                if pattern is not None and "step" in pattern.values
                else []
            )
            if any(f is None for f in found):
                for name in names:
                    self.skip(
                        item,
                        name,
                        f"a {item.kind}'s place round a side isn't fitted, for now: told by face accounting",
                        "face accounting",
                    )
                continue
            copies = tuple(f[0] for f in found if f is not None)
            size = min(f[1] for f in found if f is not None)
            reach = min(f[2] for f in found if f is not None)
            radial = _v(group[0].direction) * (1.0 if face.outward else -1.0)
            first = math.degrees(
                fs.atan2(
                    float(fv.matmul(radial, quarter)),
                    float(fv.matmul(radial, _v(zero))),
                )
            )
            told: tuple[int, ...]
            if pattern is None:
                spacing, told = 0.0, (0,)
            else:
                mode = PATTERN_COMPILE[pattern.kind]
                spacing, told = (
                    mode.round_step(pattern, len(group)),
                    mode.told(len(group)),
                )
            hub = Round(
                face.start, axis, face.radius, 0.0, face.length, not face.outward
            )
            for name in names:
                value = (
                    place.angle
                    if name == "place.angle"
                    else pattern.values["step"]
                    if pattern
                    else None
                )
                tolerance = (
                    tolerance_of(value, shorter_side=size)
                    if isinstance(value, Value)
                    else general_angle(size)
                )
                step = name != "place.angle"
                self.check(item, name, "angle", spacing if step else first, tolerance,
                           Turns(face.start, axis, zero, copies, hub, first, spacing, step, told, reach),
                           group[0].index)  # fmt: skip
            if pattern is not None:
                for count_name, count in pattern.counts.items():
                    self._count_of(
                        item,
                        f"place.pattern.{pattern.kind}.{count_name}",
                        count.n,
                        group,
                        count_name,
                    )
        for name, position in place.axes.items():
            self._along_side(item, f"place.{name}", position, side)
        if not place.axes:
            self._along_side(
                item,
                f"place.{side.axis}",
                AxisPosition("centred", None, None, "centre", None),
                side,
            )

    def _side_ends(
        self, host: tuple[str, int, str], side: RoundSide
    ) -> dict[float, Plane]:
        """A round side's two ends, by which way along its axis they are (+1, -1): the faces there (a hollow's inside, its inner ends), or where there is none, the face a standing body is joined to round its foot, or the rim of the walls a shell leaves open."""
        a = _v(side.frame.n)
        middle = _v(side.start) + side.length / 2 * a
        inner = side.name.startswith("inner")
        faces = self.faces(host[0], host[1])
        planes: dict[float, Plane] = {}
        for end_name in ("+end", "-end"):
            f = faces.get(f"inner {end_name}" if inner else end_name)
            if isinstance(f, FlatFace):
                sign = 1.0 if float(fv.matmul(_v(f.centre) - middle, a)) > 0 else -1.0
                planes[sign] = self.face_plane(f, f.outline.half[0])
        body = self.spec.item(host[0])
        body_copy = self.copies(body)[host[1]] if body is not None else None
        reach = max(side.radius, side.other)
        for sign in (1.0, -1.0):
            if sign in planes:
                continue
            at = middle + sign * side.length / 2 * a
            base = self._base(body_copy, reach + 4.0) if body_copy is not None else None
            if base is not None and float(fv.norm(_v(base.point) - at)) < 1e-6:
                planes[sign] = base
            else:
                planes[sign] = Plane(_t(at), _t(sign * a), reach)
        return planes

    def _along_side(
        self, item: Item, name: str, position: AxisPosition, side: RoundSide
    ) -> None:
        """A place along a round side's axis: from its built ends (the end faces of what it is the side of)."""
        a = _v(side.frame.n)
        for copy in self.copies(item):
            host = copy.host
            assert host is not None
            planes = self._side_ends(host, side)
            ref = self._centre_ref(item, copy, side.axis)
            if (
                len(planes) < 2
                or ref is None
                or not all(self.seen(plane) for plane in planes.values())
            ):
                self.skip(item, name, "the side's ends or the item can't be fitted")
                return
            if position.mode == "side":
                assert position.side is not None and position.distance is not None
                sign = 1.0 if position.side[0] == "+" else -1.0
                item_ref = (
                    self._edge_ref(item, copy, side.axis, sign)
                    if position.to == "edge"
                    else ref
                )
                if item_ref is None:
                    self.skip(item, name, "the item's edge can't be fitted")
                    return
                self.check(item, name, "position", _mm(position.distance), self.tol(position.distance),
                           Position(_t(-sign * a), planes[sign], item_ref), copy.index)  # fmt: skip
                continue
            if position.mode == "offset" and position.distance is not None:
                offset, tolerance = _mm(position.distance), self.tol(position.distance)
            else:
                offset, tolerance = 0.0, general(side.length / 2)
            self.check(item, name, "position", offset, tolerance,
                       Position(_t(a), Middle(planes[1.0], planes[-1.0]), ref), copy.index)  # fmt: skip

    def _pattern(self, item: Item, pattern: Pattern, face: FlatFace) -> None:
        """A pattern's values and counts on a flat face, between its copies as built; its axis, told from the face's other."""
        prefix = f"place.pattern.{pattern.kind}"
        for group in self._groups(item):
            # Each host copy's own face: its copies are on it, its edges theirs.
            host = group[0].host
            here = self.placed.face(host) if host is not None else face
            face_here = here if isinstance(here, FlatFace) else face
            for name, value in pattern.values.items():
                at = f"{prefix}.{name}"
                PATTERN_COMPILE[pattern.kind].value_checks(
                    self, item, at, pattern, name, value, group, face_here
                )
            if PATTERN_COMPILE[pattern.kind].round and "start" not in pattern.values:
                # Started at 0 degrees: the assumption the spec records.
                self._circle(
                    item, f"{prefix}.start", pattern, "start", None, group, face_here
                )
            for name, count in pattern.counts.items():
                self._count_of(item, f"{prefix}.{name}", count.n, group, name)
        if pattern.axis is not None:
            self._pattern_axis(item, pattern, face)

    def _pitches(self, item: Item, at: str, pattern: Pattern, name: str, value: Value,
                 group: list[Copy]) -> None:  # fmt: skip
        """A row's, a grid's or a rectangle's pitch: between each pair of copies it runs between, along it, from one's built centre to the other's."""
        axis = PATTERN_COMPILE[pattern.kind].pitch_axis(pattern, name)
        a = _v(unit("+" + axis))
        step = _mm(value)
        if PATTERN_COMPILE[pattern.kind].in_a_line:
            pairs = tuple((k, k + 1) for k in range(len(group) - 1))
        else:
            pairs = tuple(
                (i, j) for i in range(len(group)) for j in range(len(group))
                if np.allclose(_v(group[j].point) - _v(group[i].point), step * a, atol=1e-6)
            )  # fmt: skip
        if not pairs:
            self.skip(
                item,
                at,
                "no two copies are a pitch apart along it: it makes one copy along it",
            )
            return
        refs = [self._centre_ref(item, copy, axis) for copy in group]
        if any(r is None for r in refs):
            self.skip(item, at, "the copies' centres can't be fitted")
            return
        self.check(item, at, "pattern", step, self.tol(value), Pitches(tuple(r for r in refs if r is not None), pairs, _t(a)),
                   group[0].index)  # fmt: skip

    def _circle(self, item: Item, at: str, pattern: Pattern, name: str, value: Value | None, group: list[Copy],
                face: FlatFace) -> None:  # fmt: skip
        """A circle's or an arc's diameter (the circle through its copies' built centres), and its start and step (their angles round that circle's centre, from the face's first axis towards its second)."""
        if len(group) < 3:
            self.skip(item, at, "fewer than three copies don't fix the circle they are round: their places are told by "
                      "face accounting", "face accounting")  # fmt: skip
            return
        spots = self._spots(item, group, face)
        if isinstance(spots, str):
            self.skip(item, at, spots)
            return
        plane = (face.frame.u, face.frame.v)
        if name == "diameter":
            assert value is not None
            self.check(
                item,
                at,
                "pattern",
                _mm(value),
                self.tol(value),
                Circle(spots, plane),
                group[0].index,
            )
            return
        diameter = pattern.values.get("diameter")
        if (
            diameter is None
        ):  # pragma: no cover - on a flat face a circle or an arc has its diameter
            self.skip(item, at, "the circle has no diameter")
            return
        radius = _mm(diameter) / 2
        start = _deg(pattern.values["start"]) if "start" in pattern.values else 0.0
        count = pattern.counts["count"].n if "count" in pattern.counts else len(group)
        spacing = PATTERN_COMPILE[pattern.kind].round_step(pattern, count)
        a1, a2 = (_v(face.frame.u), _v(face.frame.v))
        turn = math.radians(start)
        centre = _v(group[0].point) - radius * (fs.cos(turn) * a1 + fs.sin(turn) * a2)
        told = PATTERN_COMPILE[pattern.kind].told(len(group))
        step = name == "step"
        tolerance = (
            tolerance_of(value, shorter_side=radius)
            if value is not None
            else general_angle(radius)
        )
        axis = _t(np.asarray(np.cross(a1, a2), dtype=np.float64))
        self.check(item, at, "angle", spacing if step else start, tolerance,
                   Turns(_t(centre), axis, _t(a1), spots, None, start, spacing, step, told, radius),
                   group[0].index)  # fmt: skip

    def _pattern_axis(self, item: Item, pattern: Pattern, face: FlatFace) -> None:
        """A row's or ends' axis: told from the shape with the pattern along the face's other axis."""
        place = item.get("place")
        assert isinstance(place, Place)
        alternatives = [
            Alternative(
                f"along {axis}",
                replace(item, fields={**item.fields, "place": replace(place, pattern=replace(pattern, axis=axis))}),
            )
            for axis in face.axes
            if axis != pattern.axis
        ]  # fmt: skip
        self._told(item, f"place.pattern.{pattern.kind}.axis", "choice", alternatives)

    def _insets(self, item: Item, at: str, name: str, value: Value, group: list[Copy], face: FlatFace,
                pattern: Pattern) -> None:  # fmt: skip
        """Corners' and ends' insets: from the face's built edge on each copy's side to the copy's built centre."""
        axes = (
            [name[len("inset_") :]]
            if name.startswith("inset_")
            else [str(pattern.axis)]
        )
        for axis in axes:
            for copy in group:
                a = _v(unit("+" + axis))
                sign = (
                    1.0
                    if float(fv.dot(_v(copy.point) - _v(face.centre), a)) > 0
                    else -1.0
                )
                edge = self.edge_plane(face, axis, sign)
                ref = self._centre_ref(item, copy, axis)
                if ref is None or not self.seen(edge):
                    self.skip(
                        item, at, "the copy or the face's edge can't be fitted there"
                    )
                    return
                self.check(item, at, "position", _mm(value), self.tol(value), Position(_t(-sign * a), edge, ref),
                           copy.index)  # fmt: skip

    def _count_of(
        self, item: Item, at: str, n: int, group: list[Copy], name: str
    ) -> None:
        surfaces: list[Round | Plane | Ball] = []
        for copy in group:
            main = self._main(item, copy)
            if isinstance(main, Centre):
                surfaces.append(main.round)
                continue
            if isinstance(main, BallCentre):
                surfaces.append(main.ball)
                continue
            ends = self._round_ends(item, copy, copy.axes[0]) if copy.axes else None
            if ends is not None:
                surfaces.append(ends[1])
                continue
            sides = self._sides_along(item, copy, copy.axes[0]) if copy.axes else None
            if sides is None:
                self.skip(item, at, "the copies' own surfaces can't be found")
                return
            surfaces.append(sides[0])
        expected = n if name == "count" else len(group)
        self.check(
            item,
            at,
            "count",
            float(expected),
            None,
            Copies(tuple(surfaces)),
            group[0].index,
            _SIDES,
        )

    def _count(self, item: Item) -> None:
        count = item.get("count")
        if not isinstance(count, Count):
            return
        copies = list(self.copies(item))
        self._count_of(item, "count", count.n, copies, "count")

    # Choices and faces -------------------------------------------------
    def _choice_value(self, item: Item, name: str) -> str | None:
        value = item.get(name)
        return value.value if isinstance(value, Choice) else None

    def _bands(self, item: Item) -> list[float]:
        bands = []
        for value in item.fields.values():
            if isinstance(value, Value) and value.quantity.unit.symbol != "deg":
                try:
                    bands.append(tolerance_of(value).band)
                except ValueError:
                    continue
        return bands

    def _told(
        self, item: Item, name: str, kind: str, alternatives: list[Alternative]
    ) -> None:
        found = tells(
            self.spec,
            self.part,
            item,
            name,
            alternatives,
            clearance_for(self._bands(item)),
        )
        if found.untold:
            # The other shape differs by no more than the part may: no point tells it, and no PASS may say it doesn't
            # differ. Face accounting holds every built face to the spec's, and so holds the choice.
            self.skip(item, name, f"{' and '.join(found.untold)} would differ from it by less than the part's "
                      "tolerances: no point tells them apart", held_by="face accounting")  # fmt: skip
        if found.told or not found.untold:
            self.check(item, name, kind, 0.0, None, Told(found.told), None, _SIDES)

    def _choice(self, item: Item, name: str) -> None:
        value = item.get(name)
        if not isinstance(value, Choice):
            return
        options = KINDS[item.kind].field(name).choices
        alternatives = [
            Alternative(
                f"{name} {o}",
                replace(item, fields={**item.fields, name: replace(value, value=o)}),
            )
            for o in options
            if o != value.value
        ]
        self._told(item, name, "choice", alternatives)

    def _on(self, item: Item) -> None:
        on = item.get("on")
        if not isinstance(on, On):
            return
        host = self.spec.item(on.item)
        faces = KINDS[host.kind].faces if host is not None else ()
        alternatives = [
            Alternative(
                f"on {f}",
                replace(item, fields={**item.fields, "on": replace(on, face=f)}),
            )
            for f in faces
            if f != on.face
        ]
        self._told(item, "on", "on", alternatives)

    # Changes to other items --------------------------------------------
    def _still_on(self, stretch: Rounded) -> Rounded | None:
        """A straight stretch as far as its rounding is still on the part's surface; None where none of it is.

        The oracle records a stretch as its rounding is made; one made later
        may take part of it away (a box's vertical edges rounded, then its
        bottom edges bevelled up most of its height: generated part 868,
        whose fillets were left 1.3 mm of 6.8). So the middle of its
        section is asked to be on the part at :data:`_ALONG_STRETCH` points
        along it, and the longest run of them that is kept: where the
        oracle has it on the part, or can't tell (where roundings meet, a
        post's joint at its corners); only air or material there says a
        later step took it away.
        """
        edge = stretch.edge
        if not isinstance(edge, rounds.StraightEdge):
            return stretch
        t1, t2 = rounds.touches(edge, stretch.size, stretch.fillet)
        if stretch.fillet:
            sec = rounds.section(edge.corner(), edge.b1, edge.b2, stretch.size, True)
            assert sec.circle is not None
            centre, radius = sec.circle
            c = _v(centre)
            out = (_v(t1) - c) + (_v(t2) - c)
            middle = c + radius * out / float(fv.norm(out))
        else:
            middle = (_v(t1) + _v(t2)) / 2
        o, u, v, along = (_v(x) for x in (edge.origin, edge.u, edge.v, edge.along))
        step = (stretch.b - stretch.a) / _ALONG_STRETCH
        at = stretch.a + step * (np.arange(_ALONG_STRETCH) + 0.5)
        points = o + middle[0] * u + middle[1] * v + at[:, None] * along
        still = np.isin(self.part.classify(points), (Side.ON, Side.UNKNOWN))
        if still.all():
            return stretch
        best, start = (0, 0), None
        for k, kept in enumerate([*still.tolist(), False]):
            if kept and start is None:
                start = k
            elif not kept and start is not None:
                if k - start > best[1] - best[0]:
                    best = (start, k)
                start = None
        if best[1] == best[0]:
            return None
        return replace(
            stretch, a=stretch.a + best[0] * step, b=stretch.a + best[1] * step
        )

    def _rounding(self, item: Item, value_name: str) -> None:
        """A fillet's radius or a chamfer's size, along every stretch of edge the oracle rounds exactly; its edges, told from the other edge sets."""
        edges = item.get("edges")
        assert isinstance(edges, EdgeSet)
        body = self.spec.item(edges.of)
        size = _mm(item.get(value_name))
        self.size(item, size)
        tolerance = self.tol(item.get(value_name), RADIUS)
        made = 0
        for found in self.part.rounded:
            if found.item != item.id:
                continue
            stretch = self._still_on(found)
            if stretch is None:
                continue
            target = _rounding_target(stretch)
            if target is None:
                continue
            self.check(item, value_name, "rounding", size, tolerance, target, made)
            made += 1
        if not made:
            self.skip(
                item,
                value_name,
                "none of its stretches is along a straight edge between flat faces, or round a rim between a flat face and a round one",
            )
        if body is None:
            return
        alternatives = [
            Alternative(
                f"edges {which}",
                replace(
                    item, fields={**item.fields, "edges": replace(edges, which=which)}
                ),
            )
            for which in KINDS[body.kind].edges
            if which != edges.which and which != "joint"
        ]
        self._told(item, "edges", "choice", alternatives)


def compile_checks(spec: PartSpec, placed: Placed, part: Oracle) -> CheckSuite:
    """Every check of the spec, and every leaf it can't check with the reason (see the module's docstring)."""
    compiler = _Compiler(spec, placed, part)
    for item in spec.items:
        compiler.item(item)
    radius, finer = _resolution(compiler.smallest, part)
    return CheckSuite(tuple(compiler.checks), tuple(compiler.unchecked), radius, finer)


def _resolution(
    sizes: Sequence[tuple[str, float]], part: Oracle
) -> tuple[float, tuple[Finer, ...]]:
    """The coverage radius everywhere, and the finer boxes (docs/V2-stage4.md, 13.10).

    Each size holds where its item is: round each of the solids each of the
    item's steps is made of, cut to the boxes round what holds it
    (:func:`~.csg.pieces`: the step's surface is on theirs; a rounding's
    stretches along its edges, not the body they are cut from), grown by
    :data:`LARGEST_RADIUS` and the size itself (a wall's far face); round
    the step's box itself where it is made of more than :data:`_PIECES`.
    There the radius is half the item's smallest size. A size whose item
    makes no solid holds everywhere. Never more than :data:`LARGEST_RADIUS`.
    """
    boxes: dict[str, list[tuple[Vec, Vec]]] = {}
    for step in part.steps:
        found = boxes.setdefault(step.item, [])
        held = list(pieces(step.node))
        for lo, hi in held if len(held) <= _PIECES else [(step.lo, step.hi)]:
            if (lo, hi) not in found:
                found.append((lo, hi))
    radius = LARGEST_RADIUS
    least: dict[str, float] = {}
    for item, size in sizes:
        if size / 2 >= LARGEST_RADIUS:
            continue
        if item in boxes:
            least[item] = min(least.get(item, size), size)
        else:
            radius = min(radius, size / 2)
    finer: list[Finer] = []
    for item, size in least.items():
        if size / 2 >= radius:
            continue
        grow = LARGEST_RADIUS + size
        for lo, hi in boxes[item]:
            box = Box(_t(_v(lo) - grow), _t(_v(hi) + grow))
            finer.append(Finer(item, box, size / 2))
    return radius, tuple(finer)


#: A step whose surface is held by more pieces than this asks for its finer coverage round its own box (:func:`_resolution`).
_PIECES = 256

#: Points along a straight stretch of rounding its surface is asked to be on the part at (:meth:`_Compiler._still_on`).
_ALONG_STRETCH = 64


def _rounding_target(stretch: Rounded) -> object | None:
    """What a stretch of rounding is measured as: an arc (a fillet) or a bevel (a chamfer), along a straight edge or round a rim.

    The rounding's section across its edge (:func:`~forge_checks.rounds.section`)
    gives the arc's centre or the bevel's ends; the material's side gives
    which way the surface faces: an outside edge rounded away leaves the
    material round the arc's centre (facing away from it), an inside corner
    filled leaves the air round it (facing it).
    """
    edge = stretch.edge
    if not stretch.fillet and not all(
        isinstance(b, rounds.Line2) for b in (edge.b1, edge.b2)
    ):
        return None  # a chamfer beside a ball's surface: its leg there is an arc, not measured this way, for now
    k = edge.corner()
    sec = rounds.section(k, edge.b1, edge.b2, stretch.size, stretch.fillet)
    t1, t2 = rounds.touches(edge, stretch.size, stretch.fillet)
    if isinstance(edge, rounds.StraightEdge):
        o, u, v, along = (_v(x) for x in (edge.origin, edge.u, edge.v, edge.along))

        def at(p: tuple[float, float]) -> Array:
            return o + p[0] * u + p[1] * v

        if stretch.fillet:
            assert sec.circle is not None
            centre, radius = sec.circle
            return Round(
                _t(at(centre)), _t(along), radius, stretch.a, stretch.b, stretch.fill
            )
        chord = _v((t2[0] - t1[0], t2[1] - t1[1]))
        normal2 = _v((-chord[1], chord[0])) / float(fv.norm(chord))
        towards_corner = float(fv.dot(_v(k) - _v(t1), normal2)) > 0
        if towards_corner == stretch.fill:
            normal2 = -normal2
        m = normal2[0] * u + normal2[1] * v
        middle = (stretch.a + stretch.b) / 2
        point = at(((t1[0] + t2[0]) / 2, (t1[1] + t2[1]) / 2)) + middle * along
        legs = tuple(
            _t(
                ((p[0] - k[0]) * u + (p[1] - k[1]) * v)
                / fs.hypot(p[0] - k[0], p[1] - k[1])
            )
            for p in (t1, t2)
        )
        return Bevel(
            Plane(_t(point), _t(m), (stretch.b - stretch.a) / 2), (legs[0], legs[1])
        )
    hub, axis = _v(edge.centre), _v(edge.axis)
    if stretch.fillet:
        assert sec.circle is not None
        (c_rho, c_z), radius = sec.circle
        angles = [fs.atan2(t[1] - c_z, t[0] - c_rho) for t in (t1, t2)]
        start, end = (
            (angles[0], angles[1])
            if (angles[1] - angles[0]) % (2 * math.pi) <= math.pi
            else (angles[1], angles[0])
        )
        return Tube(
            _t(hub + c_z * axis), _t(axis), c_rho, radius, (start, end), stretch.fill
        )
    (r1, z1), (r2, z2) = sorted((t1, t2), key=lambda t: t[1])
    if z2 - z1 < 1e-9:
        return None  # a bevel square to the axis: a flat ring, not a cone
    chord = _v((r2 - r1, z2 - z1))
    normal2 = _v((-chord[1], chord[0])) / float(fv.norm(chord))
    towards_corner = float(fv.dot(_v(k) - _v((r1, z1)), normal2)) > 0
    if towards_corner == stretch.fill:
        normal2 = -normal2
    inside = bool(normal2[0] < 0)  # facing the axis: the material is outside the cone
    legs2 = tuple(
        (
            float((p[0] - k[0]) / fs.hypot(p[0] - k[0], p[1] - k[1])),
            float((p[1] - k[1]) / fs.hypot(p[0] - k[0], p[1] - k[1])),
        )
        for p in (t1, t2)
    )
    return RoundBevel(
        Cone(_t(hub), _t(axis), (r1, r2), (z1, z2), inside),
        (float(k[0]), float(k[1])),
        (legs2[0], legs2[1]),
    )
