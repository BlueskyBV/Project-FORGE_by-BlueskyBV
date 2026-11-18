"""Random specs with their truth: parts no one picked, and where the definitions put every copy of them.

The generator chooses a part's items as a **plan** (each item's kind, the
face it is on, its sizes, its depth, its position along each axis or round a
side, its pattern), then :func:`render` works out from the field
definitions alone (docs/definitions) where every copy goes and what solid
each makes (:mod:`forge_eval.truth`), and writes the part's brief, one
sentence per item, and the draft whose fields say so, each value citing the
brief's words for it as a person's spec writer would
(:mod:`forge_eval.brief`). Nothing here reads the solver's or the judge's
placement, or the oracle (rule R2).

- **Valid parts** (:func:`generate`): every item lies wholly on its face,
  clear of what else is on it; a blind cut fits in the material under its
  mouth; a cut through the material comes out where nothing stands. Items
  stand on and cut into each other: a hole through a boss and the plate it
  stands on, a hole in a post's side, a pocket in a block standing on the
  first one, a hole through a lug (a tab, square or round-ended). Shapes at
  the ends of their ranges are made on purpose: a pocket whose corners round
  its ends all across, a slot as long as it is wide, a tab all half-disc.
- **Impossible ones** (:func:`impossible`): a valid part with one item made
  not to fit (run off its face, cut deeper than its material, its copies
  overlapping), whose expected ending is CAN'T, with the reason.
- **One leaf changed** (:func:`mutants`): for every leaf field of every item,
  the part with that one value moved beyond its tolerance (a count one
  fewer, a choice the other way, a depth through made blind), still a valid
  part; its draft differs from the original's in that leaf alone. Built, it
  is the part a mistake in that one field would make, and the original
  spec's check of that field must reject it (rule R1).

Values are on a 0.001 mm grid (angles on 0.5 degrees), so the fields written
are exactly the values the truth is made from, and two solids' faces seldom
meet in one plane by chance.
"""

from __future__ import annotations

import functools
import math
import random
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cache
from typing import TYPE_CHECKING, Any

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from numpy.typing import NDArray

from .brief import Mark, Writer, number
from .truth import (
    QUADRANTS,
    Copy,
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
    bounds,
    ink_box,
    line_pieces,
    unit_of,
)

__all__ = [
    "Case",
    "DoesNotFitError",
    "Feature",
    "Pattern",
    "Plan",
    "Position",
    "generate",
    "impossible",
    "mutants",
    "render",
]

Vec = tuple[float, float, float]
Array = NDArray[np.float64]

#: How far apart things are kept: from a face's edge, and from each other (mm).
GAP = 0.5
#: How far a solid is carried on into air or into what it is joined to, for a mesh (mm): no
#: plane of it then lies in another's, and, short of the gap, it meets nothing else on the way.
REACH = 0.05
#: The frame table (frame.md): each flat face's first and second axes.
FACE_AXES = {"z": ("x", "y"), "x": ("y", "z"), "y": ("x", "z")}
#: Round a side (place.md): each axis's 0 degree and 90 degree directions.
TURN_AXES = {"z": ("x", "y"), "x": ("y", "z"), "y": ("z", "x")}


if TYPE_CHECKING:
    # The registries' entries, asked when called (below), never when this module is imported.
    from .items.brief.pattern import PatternBrief
    from .items.brief.protocol import BriefKind
    from .items.draw.pattern import PatternDraw
    from .items.draw.protocol import DrawKind
    from .items.truth.protocol import TruthKind


def _truth(kind: str) -> TruthKind:
    """The kind's entry in the ``truth`` registry, asked when called, never when this module is imported: the kinds' modules use this module's own vocabulary."""
    from .items.truth import TRUTH

    return TRUTH[kind]


def _brief(kind: str) -> BriefKind:
    """The kind's entry in the ``brief`` registry, asked when called, never when this module is imported: the kinds' modules use this module's own vocabulary."""
    from .items.brief import BRIEF

    return BRIEF[kind]


def _draw(kind: str) -> DrawKind:
    """The kind's entry in the ``draw`` registry, asked when called, never when this module is imported: the kinds' modules use this module's own vocabulary."""
    from .items.draw import DRAW

    return DRAW[kind]


class DoesNotFitError(ValueError):
    """A plan that doesn't make a valid part, and why."""


# ----------------------------------------------------------------------
# Plans
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Position:
    """Where along one axis: ``none`` (centred, assumed), ``centred``, ``offset`` by ``distance``, or ``side`` (``distance`` from that edge, to the item's ``centre`` or ``edge``)."""

    mode: str
    distance: float = 0.0
    side: str = ""
    to: str = "centre"


@dataclass(frozen=True)
class Pattern:
    """A pattern of copies: its kind, values (mm, degrees for ``start``), counts and axis."""

    kind: str
    values: Mapping[str, float]
    counts: Mapping[str, int]
    axis: str = ""


@dataclass(frozen=True)
class Feature:
    """One item of a plan: a first body, a body or feature standing on a face, or a cut into one.

    ``sizes`` are its values by field name (mm); ``depth`` None for a cut
    through; ``choices`` its choices by field name; ``recess`` a
    counterbore's (``("counterbore", diameter, depth)``) or a countersink's
    (``("countersink", diameter, angle)``); ``place`` its position along each
    axis, ``angle`` round a side, ``pattern`` its copies.
    """

    id: str
    kind: str
    sizes: Mapping[str, float]
    on: tuple[str, str] | None = None
    depth: float | None = None
    choices: Mapping[str, str] = field(default_factory=dict)
    recess: tuple[str, float, float] | None = None
    place: Mapping[str, Position] = field(default_factory=dict)
    angle: float | None = None
    pattern: Pattern | None = None
    #: An extrusion's outline or a revolution's half outline: its shape's name and its sizes (mm).
    outline: tuple[str, tuple[tuple[str, float], ...]] | None = None
    #: A line of letters' words (text.md), exactly as written; a thread's designation (M8, M8x1).
    words: str | None = None
    #: What a change to another item changes: the rod a thread is cut into, the body a shell hollows.
    of: str | None = None
    #: A shell's open faces (none: sealed).
    faces: tuple[str, ...] | None = None
    #: How far it is turned in its flat face's plane, from the face's first axis towards its second (degrees;
    #: ``place.turn``, V2-stage4b-0c.md 3.3, 1b's first move): a slot, a rectangular pocket, a rib, a tab, a block, a
    #: post or a line of letters.
    turn: float | None = None
    #: How far it leans from square to its flat face (degrees), and towards which of the face's axes, + or -
    #: (``tilt`` and ``tilt_towards``, V2-stage4b-0c.md 3.3, 1b's second move): a hole, a boss or a post.
    tilt: tuple[float, str] | None = None
    #: Its face's axes as the part names them, where the draft names them by the face's own, ``u`` and ``v``
    #: (schema 1.4; V2-stage4b-0c.md 3.3, 1b's third move): on a turned face always, now and then on any flat face.
    own_axes: tuple[str, str] | None = None
    #: On a ball's or a dome's surface, how far up from its equator towards its pole (degrees; schema 1.6, item 3b's
    #: second step); ``angle`` is then how far round its pole.
    latitude: float | None = None


Plan = tuple[Feature, ...]


@dataclass(frozen=True)
class Case:
    """A generated part: its brief, its draft's items citing it, its truth (None if it is impossible), and why it is impossible."""

    plan: Plan
    brief: str
    items: tuple[dict[str, Any], ...]
    truth: Truth | None
    cant: str | None = None


# ----------------------------------------------------------------------
# Faces as the generator keeps them
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class _Foot:
    """A footprint on a flat face, in the frame's coordinates along the face's two axes: a rectangle with its corners rounded."""

    at: tuple[float, float]
    half: tuple[float, float]
    corner: float

    def clear_of(self, other: _Foot, gap: float) -> bool:
        """Whether the two are at least ``gap`` apart (their boxes, or their circles when both are discs)."""
        du, dv = abs(self.at[0] - other.at[0]), abs(self.at[1] - other.at[1])
        if self._disc() and other._disc():
            return fs.hypot(du, dv) >= self.half[0] + other.half[0] + gap
        return (
            du >= self.half[0] + other.half[0] + gap
            or dv >= self.half[1] + other.half[1] + gap
        )

    def _disc(self) -> bool:
        return self.half[0] == self.half[1] == self.corner


class _FaceFrame:
    """A face's frame as the generator reads it (4b.0c item 1a; V2-stage4b-0c.md, 3.3): its origin, its first and second axes and its normal.

    Round a side, ``u`` and ``v`` are the ways out at 0 and 90 degrees and
    ``n`` its axis. Coordinates in its plane are measured along ``u`` and
    ``v`` from the part's origin, as the generator's footprints are. An
    aligned frame (each axis one of the part's) is applied by choosing
    coordinates and their signs, never a product with 0 or 1, so the numbers
    are those the axis names gave; any other by its products (item 1b). The
    generator's own, made from the definitions (R2). Its axes are handed out
    as fresh arrays.
    """

    def __init__(self, origin: Array, u: Vec, v: Vec, n: Vec) -> None:
        self.origin = origin
        self._u, self._v, self._n = u, v, n
        self._axes = tuple(_aligned_axis(d) for d in (u, v, n))

    @staticmethod
    def of_names(origin: Array, u: str, v: str, n: str) -> _FaceFrame:
        return _FaceFrame(
            origin, *(unit_of(a if a[0] in "+-" else "+" + a) for a in (u, v, n))
        )

    @property
    def u(self) -> Array:
        return _v(self._u)

    @property
    def v(self) -> Array:
        return _v(self._v)

    @property
    def n(self) -> Array:
        return _v(self._n)

    def plane(self, p: Array) -> tuple[float, float]:
        """Where ``p`` is in the face's plane, along ``u`` and ``v`` from the part's origin."""
        found = []
        for j, d in ((0, self._u), (1, self._v)):
            axis = self._axes[j]
            if axis is not None:
                k, plus = axis
                found.append(float(p[k]) if plus else -float(p[k]))
            else:
                found.append(float(p[0] * d[0] + p[1] * d[1] + p[2] * d[2]))
        return found[0], found[1]

    def components(self, d: Array) -> tuple[float, float, float]:
        """A direction's parts along ``u``, ``v`` and ``n``."""
        found = []
        for j, e in enumerate((self._u, self._v, self._n)):
            axis = self._axes[j]
            if axis is not None:
                k, plus = axis
                found.append(float(d[k]) if plus else -float(d[k]))
            else:
                found.append(float(d[0] * e[0] + d[1] * e[1] + d[2] * e[2]))
        return found[0], found[1], found[2]

    def point(self, at: tuple[float, float]) -> Array:
        """The point of the face's plane at ``at`` in it (:meth:`plane`'s inverse there)."""
        p = self.origin.copy()
        for j, (d, value) in enumerate(((self._u, at[0]), (self._v, at[1]))):
            axis = self._axes[j]
            if axis is not None:
                k, plus = axis
                p[k] = value if plus else -value
            else:
                p = p + (value - float(p[0] * d[0] + p[1] * d[1] + p[2] * d[2])) * _v(d)
        return p


def _aligned_axis(d: Vec) -> tuple[int, bool] | None:
    """(which coordinate, whether the + way) of a vector that is exactly one of +-x, +-y, +-z; else None."""
    for k in range(3):
        if abs(d[k]) == 1.0 and all(d[j] == 0.0 for j in range(3) if j != k):
            return k, d[k] > 0.0
    return None


@dataclass
class _Flat:
    """A flat face: centre, outward normal, axes, its outline (``rect`` half sizes or a ``disc``'s radius), the material under it, and where a cut through it comes out.

    ``corners``: a rectangle's corner radii, in the order of
    :data:`~forge_eval.truth.QUADRANTS` (a round-ended tab's broad face has
    two, its half width).
    """

    key: tuple[str, int, str]
    centre: Array
    normal: Array
    axes: tuple[str, str]
    shape: str
    half: tuple[float, float]
    material: float
    exit: tuple[str, int, str] | None
    taken: list[_Foot] = field(default_factory=list)
    #: The blind cuts into it, and how deep: one from the far side may break into them, never all but.
    dug: list[tuple[_Foot, float]] = field(default_factory=list)
    corners: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    #: A ``profile`` face's outline, in the frame's coordinates along its axes.
    outline: Outline2 | None = None
    #: A ``ring``'s inner radius.
    inner: float = 0.0
    #: A ``profile`` face's widest disc within it, about (its radius): what is put on it is sized from that.
    widest: float = 0.0
    #: A dome's flat face: the dome's radius, its material under a point the dome's height over it (frame.md).
    dome: float = 0.0
    #: A cone's top wider than its base (cone.md): the base's radius and the cone's length. Past the base's radius
    #: what is under the top is the cone alone, down to its flank: its length there, less as the flank rises.
    flare: tuple[float, float] = (0.0, 0.0)
    #: How far things may rise out of it: in a hollow, to the wall it faces (a standing item stays ``GAP``
    #: short of it); a face within a hollow, other than one facing that way, nothing stands on.
    room: float = math.inf
    #: The hollow it faces, by its body's copy: what stands on it stands in that hollow, clear of the rest there.
    hollow: tuple[str, int] | None = None
    #: How much further than the gap things keep in from each of a rectangle's sides (its low side and its high
    #: along its first axis, then along its second): what a rounding of the edge there takes of the face.
    margin: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    #: How much further than the gap things keep in from a disc's or a ring's rim: a rounding of it.
    rim: float = 0.0
    #: The same material under all of it, as the solver reads it (forge_spec.geometry.uniform): a first block's
    #: faces, a first cylinder's ends, the sides of a box standing on a face. Only there does an item lean.
    level: bool = False
    #: A turned item's far face, and what stands on one (place.md, "A turned item's far face"): its axes turned in its
    #: plane by this many degrees from the part's ``axes``, the first towards the second.
    turn: float = 0.0
    #: A turned item's other faces (place.md, "A turned item's faces"): its first and second axes on the part, its
    #: ``axes`` naming them as they are with the item upright; its ``normal`` is the part's.
    oriented: tuple[Vec, Vec] | None = None

    @property
    def turned(self) -> bool:
        """Whether its axes aren't the part's: a turned item's face."""
        return self.turn != 0.0 or self.oriented is not None

    @functools.cached_property
    def frame(self) -> _FaceFrame:
        """Its centre, its first and second axes and its outward normal, turned in its plane by its ``turn``."""
        if self.oriented is not None:
            return _FaceFrame(self.centre, self.oriented[0], self.oriented[1], _t(self.normal))
        e1, e2 = unit_of("+" + self.axes[0]), unit_of("+" + self.axes[1])
        if self.turn != 0.0:
            c, s = _cos_sin(self.turn)
            e1, e2 = (_t(c * _v(e1) + s * _v(e2) + 0.0), _t(c * _v(e2) - s * _v(e1) + 0.0))
        return _FaceFrame(self.centre, e1, e2, _t(self.normal))

    def coords(self) -> tuple[float, float]:
        return self.frame.plane(self.centre)

    def frame_at(self, at: tuple[float, float]) -> _FaceFrame:
        """The face's frame at the point of its plane at ``at`` (item 3a's placeable face)."""
        frame = self.frame
        return _FaceFrame(frame.point(at), frame._u, frame._v, frame._n)

    # Item 3a's placeable face, second part: what an item covers on it, and the material under that.
    def foot(self, f: Feature, at: tuple[float, float]) -> _Foot:
        """What a copy of ``f`` centred at ``at`` covers on the face: its outline; letters, their ink's box (it
        reaches past the line's); a cone wider at its top than its base, its top's circle; turned, the box round its
        turned outline (what is clear of that is clear of it)."""
        if f.turn is not None:
            return _Foot(at, _turned_half(f, self.axes, _draw(f.kind).foot_of(f, self, (0.0, 0.0))), 0.0)
        return _draw(f.kind).foot_of(f, self, at)

    def material_under(self, foot: _Foot) -> float:
        """The least material under a footprint on the face: the face's; under a dome's flat face the dome's height
        over the footprint's farthest point from its centre (frame.md); on a flared cone's top, past its base's
        radius, the cone's own height over that point, from its flank up (generated part 3375).

        The farthest point is bounded by the footprint's box's corner.
        """
        if self.dome <= 0 and self.flare[1] <= 0:
            return self.material
        cu, cv = self.coords()
        widest = fs.hypot(abs(foot.at[0] - cu) + foot.half[0], abs(foot.at[1] - cv) + foot.half[1])
        if self.flare[1] > 0:
            base, length = self.flare
            if widest <= base:
                return self.material
            top = self.half[0]
            return length * max(top - widest, 0.0) / (top - base)
        return math.sqrt(max(self.dome * self.dome - widest * widest, 0.0))

    @property
    def uniform(self) -> bool:
        """Whether an item may lean on it: the same material under all of it (``level``), a rectangle or a disc, no
        dome or flared cone under it, out of any hollow, a cut through it coming out on its far face."""
        return (
            self.level
            and self.shape in ("rect", "disc")
            and self.dome <= 0
            and self.flare[1] <= 0
            and self.hollow is None
            and math.isinf(self.room)
            and self.exit is not None
            and not self.exit[2].startswith("inner")
        )

    def holds(
        self,
        foot: _Foot,
        gap: float = GAP,
        flush: frozenset[tuple[int, float]] = frozenset(),
        beyond: frozenset[tuple[int, float]] = frozenset(),
    ) -> bool:
        """Whether the footprint lies wholly on the face, ``gap`` in from its edge.

        A footprint is the rectangle between its corners' centres grown by
        its corner radius ``r``; so it lies within the face shrunk by ``gap``
        when that rectangle's corners lie within the face shrunk by
        ``gap + r``: a rectangle (a disc, a square) whose sides are that much
        in, each rounded corner rounded that much less about the same centre
        (or sharp, where that leaves nothing of it). On a rectangle, a side the
        footprint is ``flush`` with (its axis's index and which end, -1 or 1)
        it may touch: no gap there, nor any margin; a side it reaches
        ``beyond`` (a body overhanging the face: :func:`_overhang`) bounds it
        nowhere.
        """
        cu, cv = self.coords()
        r = foot.corner
        if self.shape == "profile":
            assert self.outline is not None
            return _within_outline(self.outline, foot, gap)
        if self.shape == "ring":
            near = _rounded_rect_distance(foot, (cu, cv))
            far = max(fs.hypot(foot.at[0] - cu + su * (foot.half[0] - r), foot.at[1] - cv + sv * (foot.half[1] - r))
                      for su, sv in QUADRANTS) + r  # fmt: skip
            return near >= self.inner + gap and far <= self.half[0] - gap - self.rim
        shrink = gap + r + (self.rim if self.shape == "disc" else 0.0)
        radii = (self.half[0],) * 4 if self.shape == "disc" else self.corners
        # How far in from each side (its low end and high along the first axis, then the second) it must keep.
        keep = [shrink + m for m in self.margin]
        for sides, at in ((flush, r), (beyond, -math.inf)):
            for k, end in sides:
                # Flush with, or over, only a rectangle's side that nothing has taken.
                if self.shape != "rect" or self.margin[2 * k + (end > 0)] > 0:
                    return False
                keep[2 * k + (end > 0)] = at
        lo1, hi1, lo2, hi2 = keep
        for su, sv in QUADRANTS:
            u = foot.at[0] - cu + su * (foot.half[0] - r)
            v = foot.at[1] - cv + sv * (foot.half[1] - r)
            if not (-(self.half[0] - lo1) - 1e-9 <= u <= self.half[0] - hi1 + 1e-9):
                return False
            if not (-(self.half[1] - lo2) - 1e-9 <= v <= self.half[1] - hi2 + 1e-9):
                return False
            for (q1, q2), radius in zip(QUADRANTS, radii, strict=True):
                du, dv = (
                    q1 * u - (self.half[0] - radius),
                    q2 * v - (self.half[1] - radius),
                )
                # The corner's arc shrunk as much as the more kept of the two sides it joins.
                most = max(hi1 if q1 > 0 else lo1, hi2 if q2 > 0 else lo2)
                if (
                    radius > most
                    and du > 0
                    and dv > 0
                    and fs.hypot(du, dv) > radius - most
                ):
                    return False
        return True


def _rounded_rect_distance(foot: _Foot, p: tuple[float, float]) -> float:
    """How far a point is outside a footprint (negative within it): its rounded rectangle's signed distance."""
    r = foot.corner
    qu = abs(p[0] - foot.at[0]) - (foot.half[0] - r)
    qv = abs(p[1] - foot.at[1]) - (foot.half[1] - r)
    return fs.hypot(max(qu, 0.0), max(qv, 0.0)) + min(max(qu, qv), 0.0) - r


#: How far apart the points an outline is followed by are, to see that a footprint keeps clear of it (mm).
_FOLLOW = 0.02


def _within_outline(outline: Outline2, foot: _Foot, gap: float) -> bool:
    """Whether a footprint lies in an outline, ``gap`` in from its sides: its centre in it, and every side of it at least ``gap`` from the footprint.

    The sides are followed every :data:`_FOLLOW` mm and each point held
    :data:`_FOLLOW` further off than ``gap``: a footprint's signed distance
    changes no faster than the point moves, so between two of them the side
    keeps more than ``gap`` away too. It errs one way only: a footprint it
    passes is on the face.
    """
    if not outline.inside(np.array([foot.at[0]]), np.array([foot.at[1]]))[0]:
        return False
    points = outline.followed(_FOLLOW)
    r = foot.corner
    qu = np.abs(points[:, 0] - foot.at[0]) - (foot.half[0] - r)
    qv = np.abs(points[:, 1] - foot.at[1]) - (foot.half[1] - r)
    distance = (
        fv.hypot(np.maximum(qu, 0.0), np.maximum(qv, 0.0))
        + np.minimum(np.maximum(qu, qv), 0.0)
        - r
    )
    return bool(np.all(distance >= gap + _FOLLOW))


@dataclass
class _Round:
    """A rod's round side: its axis (by name), its base and far end, radius and the material a cut along the radius meets (its diameter)."""

    key: tuple[str, int, str]
    axis: str
    start: Array
    length: float
    radius: float
    #: The holes round it: along its axis, angle round it, radius, depth (None: through).
    taken: list[tuple[float, float, float, float | None]] = field(default_factory=list)
    #: A tube's bore radius: a cut through its side goes through its wall only (hole.md); 0 for a solid rod.
    bore: float = 0.0
    #: Where along it the bore is (from its start): all of it, but in a hollowed cylinder, between its ends' walls.
    bored: tuple[float, float] = (-math.inf, math.inf)
    #: How much further than the gap holes keep from its start and its end: what a rounding of its rim there takes.
    margin: tuple[float, float] = (0.0, 0.0)
    #: The stretches along it items standing round it take (from its start): a rounding of its rim or a thread
    #: made after keeps clear of them.
    standing: list[tuple[float, float]] = field(default_factory=list)

    @functools.cached_property
    def frame(self) -> _FaceFrame:
        """Its start; the ways out at 0 and 90 degrees round it; its axis."""
        u, v = TURN_AXES[self.axis]
        return _FaceFrame.of_names(self.start, u, v, self.axis)

    def frame_at(self, out: Array, along: float) -> _FaceFrame:
        """The side's frame at a point on it (item 3a): ``out`` the way out there (a unit radial), ``along`` from its start."""
        w = self.frame.n
        p = self.start + along * w + self.radius * out
        return _FaceFrame(p, _t(np.cross(w, out)), _t(w), _t(out))


@dataclass
class _Ball:
    """A ball's or a dome's surface (item 3b's second step; sphere.md): its centre, the way its pole lies, its radius;
    a dome's (the half on its pole's side) or a whole ball's, standing on a face or not (a whole one standing on a face
    has its lower half in it). A point on it is at a latitude from its equator and an angle round its pole from its
    frame's ``u``."""

    key: tuple[str, int, str]
    centre: Array
    up: str
    radius: float
    dome: bool
    standing: bool
    #: What is on it: each copy's angle round its pole and latitude (degrees), and how far round the ball its foot
    #: reaches from its point (degrees).
    taken: list[tuple[float, float, float]] = field(default_factory=list)

    @functools.cached_property
    def frame(self) -> _FaceFrame:
        """Its centre; ``u`` its zero meridian's way out at its equator, ``v`` a quarter round its pole, ``n`` its pole's
        way."""
        u, v = TURN_AXES[self.up[1]]
        return _FaceFrame.of_names(self.centre, "+" + u, self.up[0] + v, self.up)

    @property
    def lowest(self) -> float:
        """How far down (latitude) what is on it may reach: a dome's rim, a standing ball's equator."""
        return 0.0 if self.dome or self.standing else -90.0

    def ways(self, angle: float, latitude: float) -> tuple[Array, Array, Array]:
        """Its way out at a point on it, and east and south there (an item's first and second axes, as the solver's)."""
        f = self.frame
        cl, sl = _cos_sin(angle)
        cp, sp = _cos_sin(latitude)
        level = cl * f.u + sl * f.v
        out = cp * level + sp * f.n + 0.0
        east = -sl * f.u + cl * f.v + 0.0
        south = sp * level - cp * f.n + 0.0
        return out, east, south


@dataclass
class _Cone:
    """A cone's tapered side (item 3b's third step; cone.md): its axis (by name), the centre of its end at the smaller
    coordinate along it, its length and its radius there and at its other end. A point on it is at an angle round its
    axis, from its frame's ``u``, and a distance from its start along it; its normal leans from the radius there
    towards its narrower end by its half angle."""

    key: tuple[str, int, str]
    axis: str
    start: Array
    length: float
    start_radius: float
    end_radius: float
    #: What is on it: each copy's angle round it (degrees), how far round it its foot reaches either way from its point
    #: (degrees, at its narrowest), where along it (from its start) and how far along its axis either way.
    taken: list[tuple[float, float, float, float]] = field(default_factory=list)

    @functools.cached_property
    def frame(self) -> _FaceFrame:
        """Its start; the ways out at 0 and 90 degrees round it; its axis."""
        u, v = TURN_AXES[self.axis]
        return _FaceFrame.of_names(self.start, u, v, self.axis)

    @property
    def lean(self) -> tuple[float, float]:
        """The cosine and sine of its half angle, from a radius's way out to its normal (towards its narrower end)."""
        k = (self.end_radius - self.start_radius) / self.length
        q = math.sqrt(1.0 + k * k)
        return 1.0 / q, k / q

    def radius_at(self, along: float) -> float:
        """Its radius ``along`` from its start."""
        return self.start_radius + (self.end_radius - self.start_radius) * along / self.length

    def ways(self, angle: float, along: float) -> tuple[Array, Array, Array, Array]:
        """Its point at an angle round it and ``along`` from its start; there its normal, its way round (an item's
        first axis) and its way up its slope (its second)."""
        f = self.frame
        c, s = _cos_sin(angle)
        radial = c * f.u + s * f.v + 0.0
        lc, ls = self.lean
        p = self.start + along * f.n + self.radius_at(along) * radial
        normal = lc * radial - ls * f.n + 0.0
        around = -s * f.u + c * f.v + 0.0
        slant = lc * f.n + ls * radial + 0.0
        return p, normal, around, slant

    def inside(self, points: Array, by: float = 0.0) -> NDArray[np.bool_]:
        """Which of the points are in the cone, ``by`` in from its surface and its ends."""
        f = self.frame
        d = points - self.start
        along = fv.matmul(d, f.n)
        radial = d - along[:, None] * f.n
        rho = np.sqrt(fv.dot(radial, radial))
        r = self.start_radius + (self.end_radius - self.start_radius) * along / self.length
        return np.asarray((along >= by) & (along <= self.length - by) & (rho <= r - by / self.lean[0]), dtype=bool)

    def exit(self, points: Array, way: Array) -> Array:
        """How far from each point along ``way`` it is last in the cone (0 where it never is), asked a hundredth of a
        millimetre at a time and settled to a micron."""
        step, reach = 1e-2, 2.0 * (self.length + 2 * max(self.start_radius, self.end_radius))
        t = np.arange(0.0, reach, step)
        found = np.zeros(len(points))
        for k, p in enumerate(points):
            on = self.inside(p[None, :] + t[:, None] * way[None, :])
            if not on.any():
                continue
            last = int(np.nonzero(on)[0][-1])
            lo, hi = t[last], t[last] + step
            for _ in range(14):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if bool(self.inside((p + mid * way)[None, :])[0]) else (lo, mid)
            found[k] = lo
        return found


def _v(a: Any) -> Array:
    return np.asarray(a, dtype=np.float64)


def _t(a: Array) -> Vec:
    return (float(a[0]) + 0.0, float(a[1]) + 0.0, float(a[2]) + 0.0)


def _named(direction: Array) -> str:
    """The frame direction a unit vector along an axis is: ``+x``."""
    k = int(np.argmax(np.abs(direction)))
    return ("+" if direction[k] > 0 else "-") + "xyz"[k]


def _flat_axes(name: str) -> tuple[str, str]:
    return FACE_AXES[name[-1]]


# ----------------------------------------------------------------------
# Drafting values
# ----------------------------------------------------------------------
def _q(x: float, step: float = 0.001) -> float:
    return round(round(x / step) * step, 6) + 0.0


# ----------------------------------------------------------------------
# Rendering a plan: where every copy goes, the solids, the draft
# ----------------------------------------------------------------------
@dataclass
class _Part:
    copies: dict[str, list[Copy]] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    flats: dict[tuple[str, int, str], _Flat] = field(default_factory=dict)
    rounds: dict[tuple[str, int, str], _Round] = field(default_factory=dict)
    #: Balls' and domes' surfaces (item 3b's second step).
    balls: dict[tuple[str, int, str], _Ball] = field(default_factory=dict)
    #: Cones' sides (item 3b's third step).
    cones: dict[tuple[str, int, str], _Cone] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    #: What stands in each hollow: each copy's item and its box (low and high corners).
    inside: dict[tuple[str, int], list[tuple[str, Array, Array]]] = field(
        default_factory=dict
    )
    #: The steps made last, in the plan's order: roundings, chamfers and threads (frame.md).
    late: list[Step] = field(default_factory=list)
    #: Where roundings leave the shape to the making (Truth.zones).
    zones: list[tuple[Vec, Vec]] = field(default_factory=list)
    #: The boxes round roundings' pieces (and what rounds them), grown by half the gap: nothing made after may
    #: reach into one (an edge another item cuts across, or stands over, is rounded only where it is left, which
    #: the truth doesn't follow).
    #: Each with the item whose own steps, and those of what stands on it or is cut into it, may reach into it
    #: (an overhang's), or None (a rounding's: nothing may).
    kept: list[tuple[str, Array, Array, str | None]] = field(default_factory=list)
    #: Each thread's rod's material that must stay whole: the thread's id, and points round its stretch from a
    #: wall in from its root out (:func:`_threaded_clear`); what is made after it is held to them too.
    threads: list[tuple[str, Array]] = field(default_factory=list)


def _footprint(f: Feature, axes: tuple[str, str]) -> tuple[tuple[float, float], float]:
    """An item's outline on a face with these axes, about its centre: half sizes and corner radius (frame.md, place.md)."""
    return _draw(f.kind).footprint(f, axes)


def _turn_of(f: Feature) -> tuple[float, float] | None:
    """The cosine and sine of an item's turn in its face's plane, exact on the quarter turns; None if it isn't turned."""
    return None if f.turn is None else _cos_sin(f.turn)


def _cos_sin(degrees: float) -> tuple[float, float]:
    """The cosine and sine of an angle in degrees, exact on the quarter turns."""
    quarters = degrees / 90.0
    if abs(quarters - round(quarters)) < 1e-12:
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[round(quarters) % 4]
    t = math.radians(degrees)
    return fs.cos(t), fs.sin(t)


def _turned_half(
    f: Feature, axes: tuple[str, str], foot: _Foot | None = None
) -> tuple[float, float]:
    """The half sizes, along the face's axes, of the box about its point round a turned item's outline (its
    footprint), or round ``foot`` (what it covers, placed at its point: letters' ink's box, off their line's
    middle): its rectangle's corners' circles' centres turned, and their radius past them (a rounded rectangle
    is its inner rectangle widened by its corner's radius all round)."""
    if foot is None:
        (h1, h2), r = _footprint(f, axes)
        m1, m2 = 0.0, 0.0
    else:
        (h1, h2), r, (m1, m2) = foot.half, foot.corner, foot.at
    turn = _turn_of(f)
    assert turn is not None
    c, s = turn
    reach = [0.0, 0.0]
    for q1 in (-1.0, 1.0):
        for q2 in (-1.0, 1.0):
            x, y = m1 + q1 * (h1 - r), m2 + q2 * (h2 - r)
            reach = [max(reach[0], abs(c * x - s * y)), max(reach[1], abs(s * x + c * y))]
    return reach[0] + r, reach[1] + r


def _turned_frame(f: Feature, e1: Array, e2: Array) -> tuple[Array, Array]:
    """An item's own first and second ways on its face, turned from the face's first axis towards its second."""
    turn = _turn_of(f)
    if turn is None:
        return e1, e2
    c, s = turn
    return c * e1 + s * e2 + 0.0, c * e2 - s * e1 + 0.0


#: How often the generator turns in a flat face's plane an item that can be (DrawKind.turnable).
_TURNED = 0.2


def _turned_now_and_then(rng: random.Random, f: Feature, face: _Flat) -> Feature | None:
    """Now and then a slot, a rectangular pocket, a rib, a tab, a block, a post or a line of letters on a flat face turned in
    its plane (place.turn), from a stream of its own: a share of turns by quarters' halves, the rest anywhere on a
    half-degree grid, between 0 and 180 degrees (each outline is the same turned half a turn), or for letters all
    the way round (upside down, they read otherwise); None when it isn't turned. A disc (a slot as long as it is
    wide) isn't: it is the same turned."""
    if rng.random() >= _TURNED or not _draw(f.kind).turnable or f.on is None or f.on[1] == "side":
        return None
    (h1, h2), corner = _footprint(f, face.axes)
    if h1 == h2 == corner:  # a disc (a round pocket's, a slot as long as it is wide): the same turned
        return None
    if _draw(f.kind).turns_all_round:
        nice, most = (30.0, 45.0, 90.0, 180.0, 270.0, 315.0), 359.5
    else:
        nice, most = (30.0, 45.0, 60.0, 120.0, 135.0, 150.0), 179.5
    turn = rng.choice(nice) if rng.random() < 0.5 else _q(rng.uniform(0.5, most), 0.5)
    return replace(f, turn=turn)


# ----------------------------------------------------------------------
# Leaning from square to the face (tilt; place.md, "Leaning on the face"; V2-stage4b-0c.md 3.3, 1b's second move)
# ----------------------------------------------------------------------
#: How often the generator leans an item that can (DrawKind.leans), and the most it leans one (degrees).
_LEANED = 0.2
_MOST_LEAN = 75.0


@dataclass(frozen=True)
class _Lean:
    """How an item leans on its flat face: ``tilt`` degrees (its cosine ``c`` and sine ``s``) towards ``way``, a unit
    vector in the face's two coordinates (turned with the item where it is turned); ``along_first``: its lean is
    along its own first axis, else its second."""

    tilt: float
    c: float
    s: float
    way: tuple[float, float]
    along_first: bool

    @property
    def tan(self) -> float:
        return self.s / self.c

    def in_part(self, face: _Flat) -> Array:
        """Its way as a direction in the part, along the face."""
        return self.way[0] * face.frame.u + self.way[1] * face.frame.v + 0.0

    def direction(self, face: _Flat) -> Array:
        """Its direction: the face's outward normal turned ``tilt`` towards its way (place.md)."""
        return self.c * face.normal + self.s * self.in_part(face) + 0.0


def _lean_of(f: Feature, axes: tuple[str, str]) -> _Lean:
    """How a leaning item leans on a flat face with these axes (a :class:`DoesNotFitError` where it leans towards
    neither)."""
    assert f.tilt is not None
    tilt, towards = f.tilt
    if towards[1] not in axes:
        raise DoesNotFitError(f"{f.id} leans towards {towards}, which isn't one of its face's axes {axes}")
    if not 0.0 < tilt < 90.0:
        raise DoesNotFitError(f"{f.id} leans {tilt:g} degrees: a lean is more than 0 and less than 90")
    sign = 1.0 if towards[0] == "+" else -1.0
    first = towards[1] == axes[0]
    way = (sign, 0.0) if first else (0.0, sign)
    turn = _turn_of(f)
    if turn is not None:  # turned with it: its lean is along its own axis
        ct, st = turn
        way = (ct * way[0] - st * way[1] + 0.0, st * way[0] + ct * way[1] + 0.0)
    t = math.radians(tilt)
    return _Lean(tilt, fs.cos(t), fs.sin(t), way, first)


def _own_halves(f: Feature, axes: tuple[str, str], lean: _Lean) -> tuple[float, float]:
    """A leaning item's half sizes square to its direction, along its lean and across it: a post's own; a boss's
    radius; a hole's widest (its counterbore's, where that is wider), both ways."""
    (h1, h2), _ = _footprint(f, axes)
    if not _draw(f.kind).leans_round:  # a post's or a block's own
        return (h1, h2) if lean.along_first else (h2, h1)
    return h1, h1


def _lean_box(lean: _Lean, at: tuple[float, float], offset: float, along: float, across: float) -> _Foot:
    """The box along the face's axes round a rectangle on it running along a lean's way: ``along`` its half size
    that way, ``across`` its other, its middle ``offset`` along the way from ``at``."""
    w1, w2 = abs(lean.way[0]), abs(lean.way[1])
    centre = (at[0] + offset * lean.way[0], at[1] + offset * lean.way[1])
    return _Foot(centre, (w1 * along + w2 * across, w2 * along + w1 * across), 0.0)


def _leaning_foot(f: Feature, axes: tuple[str, str]) -> tuple[float, float]:
    """The half sizes of the box round a leaning item's foot about its point (place.md: its cross-section's section
    by the face, drawn out along its lean by 1 / cos(tilt)), along the face's two axes: what it is placed by."""
    lean = _lean_of(f, axes)
    along, across = _own_halves(f, axes, lean)
    return _lean_box(lean, (0.0, 0.0), 0.0, along / lean.c, across).half




def _on_flat_leaning(f: Feature, face: _Flat, index: int, part: _Part, strict: bool) -> list[Copy]:
    """Every copy of a hole, a boss or a post leaning on one copy of a flat face (place.md, "Leaning on the face").

    Its direction ``u`` is the face's outward normal turned ``tilt`` towards
    its way; its cross-section, square to ``u``, is what it is unleaning. A
    boss or a post is that cross-section run along ``u`` from far enough back
    that all of it is past the face's plane, out to its height, and kept on
    the face's open side; a hole (and its counterbore) its circle run along
    ``-u`` into the material, its depth, or right through: on until all of it
    is past the far face, ``(T + r sin) / cos``, and kept within the face's
    ``T`` of material, which is the same under all of it (``_level``).

    What it covers, as the generator keeps it clear of everything else (and
    the face's edges, and its far face's): the box round all of it seen
    along the face's normal, from its foot (its cross-section's section by
    the face, ``1 / cos(tilt)`` longer along its lean) to its top's
    cross-section, ``height sin(tilt)`` along its lean (a cut: to its floor
    or the far face, against it). Placed by its foot's box, as the solver
    places it; its faces take nothing yet; it is neither rounded nor
    threaded.
    """
    if not _draw(f.kind).leans:
        raise DoesNotFitError(f"{f.id}: the generator leans a hole, a boss or a post")
    if f.recess is not None and f.recess[0] == "countersink":
        raise DoesNotFitError(f"{f.id}: a countersunk hole doesn't lean yet")
    if f.turn is not None and not _draw(f.kind).turnable:
        raise DoesNotFitError(f"{f.id}: the generator turns a post that leans, not a {f.kind}")
    if f.pattern is not None and _pattern_draw(f.pattern.kind).at_the_corners and face.shape != "rect":
        raise DoesNotFitError(f"{f.id}: corners are a rectangle's")
    if f.pattern is not None and not _names_the_axes(f.pattern, face.axes):
        raise DoesNotFitError(f"{f.id}: its pattern's values don't run along {face.key}'s axes {face.axes}")
    for axis in (f.pattern.axis if f.pattern is not None else None, *f.place):
        if axis and axis not in face.axes:
            raise DoesNotFitError(f"{f.id}: {axis} isn't one of {face.key}'s axes {face.axes}")
    if not face.uniform:
        raise DoesNotFitError(f"{f.id} leans on {face.key}, which hasn't the same material under all of it")
    lean = _lean_of(f, face.axes)
    if strict and lean.tilt > _MOST_LEAN:
        raise DoesNotFitError(f"{f.id} leans more than {_MOST_LEAN:g} degrees")
    thick = face.material
    along, across = _own_halves(f, face.axes, lean)
    cut = _draw(f.kind).cut_out
    # A cut's bores: the hole's, then its counterbore's, each its radius and its depth along its axis (None: right
    # through); how far each reaches against the lean, seen along the normal: to its floor's far side, or the far
    # face's section of it.
    bores: list[tuple[float, float | None]] = []
    if cut:
        bores.append((f.sizes["diameter"] / 2, f.depth))
        if f.recess is not None:
            bores.append((f.recess[1] / 2, f.recess[2]))
        # Its foot's far side back against the lean, too: a shallow cut's floor may reach less far (generated part 669's
        # neighbour, a boss's foot, was held apart from a leaning foot by less than the foot).
        low = min(-along / lean.c, *(-thick * lean.tan - r / lean.c if d is None else -d * lean.s - r * lean.c
                                     for r, d in bores))  # fmt: skip
        high = along / lean.c
        deepest = max(thick if d is None else d * lean.c + r * lean.s for r, d in bores)
    else:
        height = f.sizes[_draw(f.kind).stand_height]
        # Its foot's front, too: a short one's top may reach less far along the lean than its foot (generated part
        # 669: two bosses 2 mm tall leaning 45 degrees along their row, their feet overlapping).
        low, high = -along / lean.c, max(along / lean.c, height * lean.s + along * lean.c)
        deepest = 0.0
    spots = _flat_spots(f, face)
    covers = [_lean_box(lean, at, (low + high) / 2, (high - low) / 2, across) for at in spots]
    out = part.flats.get(face.exit) if face.exit is not None else None
    if strict:
        for k, cover in enumerate(covers):
            if not face.holds(cover, GAP):
                raise DoesNotFitError(f"{f.id} copy {k}, leaning, doesn't lie wholly over {face.key}")
            for other in face.taken + covers[:k]:
                if not cover.clear_of(other, GAP):
                    raise DoesNotFitError(f"{f.id} copy {k}, leaning, meets something else on {face.key}")
        if not cut and along * lean.tan > thick - GAP:
            # It reaches back into the face from its foot (the solver asks for that much material under it).
            raise DoesNotFitError(f"{f.id} leans further back into {face.key} than its material")
        if cut:
            for r, d in bores:
                if d is not None and d * lean.c + r * lean.s > thick - GAP:
                    raise DoesNotFitError(f"{f.id}, leaning, is deeper than the material under {face.key}")
            if f.recess is not None and f.depth is not None and f.recess[2] > f.depth - GAP:
                raise DoesNotFitError(f"{f.id}'s counterbore is as deep as it is")
            if out is None:
                raise DoesNotFitError(f"{f.id} would come out where {face.exit} is pressed against another")
            for k, near in enumerate(covers):
                cover = _on_exit(face, out, near)
                # Over its far face all the way, as on its own: none of it comes near the part's other sides.
                if not out.holds(cover, GAP):
                    raise DoesNotFitError(f"{f.id} copy {k}, leaning, doesn't lie wholly over {face.exit}")
                for foot in out.taken if f.depth is None else ():
                    if not cover.clear_of(foot, GAP):
                        raise DoesNotFitError(f"{f.id} comes out through {face.exit} where something is")
                for foot, deep in out.dug:
                    if not cover.clear_of(foot, 0.0) and abs(deepest + deep - thick) < 0.3:
                        raise DoesNotFitError(f"{f.id} all but breaks into a cut from the far side")
    n = face.normal
    w = lean.in_part(face)
    u = lean.direction(face)
    tilted = lean.c * w - lean.s * n + 0.0  # its lean's way square to its direction
    side = np.asarray(np.cross(n, w), dtype=np.float64) + 0.0  # across its lean: (tilted, side, u) right-handed
    made = []
    first = len(part.steps)
    for k, at in enumerate(spots):
        p = _point(face, at)
        copy_index = index + k
        made.append(Copy(f.id, copy_index, face.key, _t(p), _t(n), face.axes, lean=_t(u)))
        if cut:
            for r, d in bores:
                back = r * lean.tan + 1.0  # all of its circle past the face's plane
                if d is None:
                    run, keep, reach = (thick + r * lean.s) / lean.c + 1.0, (-thick, 0.0), (REACH, REACH)
                else:
                    run, keep, reach = d, (-(d * lean.c + r * lean.s) - 1.0, 0.0), (0.0, REACH)
                rod = Prism(_t(p), _t(tilted), _t(side), _t(u), (r, r), r, -run, back)
                part.steps.append(Step(f.id, copy_index, False, Kept(rod, _t(p), _t(n), *keep), reach))
        else:
            height = f.sizes[_draw(f.kind).stand_height]
            corner = along if _draw(f.kind).leans_round else 0.0
            body = Prism(_t(p), _t(tilted), _t(side), _t(u), (along, across), corner, -(along * lean.tan + 1.0),
                         height)  # fmt: skip
            top = height * lean.c + along * lean.s + 1.0
            part.steps.append(Step(f.id, copy_index, True, Kept(body, _t(p), _t(n), 0.0, top), (REACH, 0.0)))
    if strict and not cut:
        _stands_in_air(f, made, part.steps[first:], (*part.steps[:first], *part.late))
    for k, at in enumerate(spots):
        face.taken.append(covers[k])
        if cut and f.depth is None and out is not None:
            r = f.sizes["diameter"] / 2
            out.taken.append(_on_exit(face, out, _lean_box(lean, at, -thick * lean.tan, r / lean.c, r)))
        elif cut:
            face.dug.append((covers[k], deepest))
    return made


def _leaned_now_and_then(rng: random.Random, f: Feature, face: _Flat) -> Feature | None:
    """Now and then a hole (plain or counterbored), a boss, a post, a block or a cylinder (turned or not; a body in schema
    1.5) on a face with the same material
    under all of it leaning (tilt, tilt_towards), from a stream of its own: a share of leans by nice angles, the rest
    anywhere on a half-degree grid up to the most Forge leans one, towards either way of either of the face's axes;
    None when it doesn't lean."""
    if rng.random() >= _LEANED or not _draw(f.kind).leans or f.on is None or f.on[1] == "side":
        return None
    if not face.uniform or f.angle is not None or (f.recess is not None and f.recess[0] == "countersink"):
        return None
    tilt = rng.choice((10.0, 15.0, 20.0, 30.0, 45.0, 60.0)) if rng.random() < 0.5 else _q(rng.uniform(0.5, _MOST_LEAN), 0.5)
    towards = rng.choice(("+", "-")) + rng.choice(face.axes)
    return replace(f, tilt=(tilt, towards))


def _turns_with(f: Feature, face: _Flat) -> bool:
    """Whether the generator puts an item on a turned face (place.md, "A turned item's far face"), turned with it: a
    cut whose faces it keeps none of, or one standing as a box or a rod does (its own far face, turned so)."""
    from .items.draw.protocol import DrawKind

    entry = _draw(f.kind)
    if entry.cut_out:
        return entry.cuts_turned_faces
    return type(entry).stand_flat is DrawKind.stand_flat


def _turned_sides(part: _Part, item: str, index: int, p: Array, up: str, axes: tuple[str, str],
                  sizes: tuple[float, float, float], turn: float) -> None:  # fmt: skip
    """A turned box's sides (place.md, "A turned item's faces"): each its own face, named as with the box upright, its
    axes turned with it, the box's own size across it under it, a cut through it coming out on the side across."""
    c, s = _cos_sin(turn)
    e1, e2 = _v(unit_of("+" + axes[0])), _v(unit_of("+" + axes[1]))
    ways = {axes[0]: c * e1 + s * e2 + 0.0, axes[1]: c * e2 - s * e1 + 0.0, up[1]: _v(unit_of("+" + up[1]))}
    length, width, height = sizes
    extent = {axes[0]: length, axes[1]: width, up[1]: height}
    n = _v(unit_of(up))
    middle = p + height / 2 * n
    for axis in axes:
        for sign in ("+", "-"):
            name, other = sign + axis, ("-" if sign == "+" else "+") + axis
            d = (1.0 if sign == "+" else -1.0) * ways[axis]
            b1, b2 = _flat_axes(name)
            part.flats[(item, index, name)] = _Flat(
                (item, index, name), middle + extent[axis] / 2 * d, d, (b1, b2), "rect",
                (extent[b1] / 2, extent[b2] / 2), extent[axis], (item, index, other), level=True,
                oriented=(_t(ways[b1]), _t(ways[b2])))  # fmt: skip


def _profile_box(f: Feature) -> tuple[tuple[float, float], tuple[float, float]]:
    """The box round an extrusion's outline or a revolution's half outline: its least and greatest coordinates."""
    assert f.outline is not None
    return outline_of(f.outline[0], dict(f.outline[1])).box()


def _extent(
    f: Feature, axes: tuple[str, str]
) -> tuple[tuple[float, float], tuple[float, float]]:
    """How far an item reaches back and forth along a face's two axes from the point it is placed by (place.md): an extrusion's outline, from its point (0, 0); anything else, its footprint about its centre; turned, the box round its turned outline; leaning, the box round its foot (its cross-section's section by the face)."""
    if f.tilt is not None:
        h1, h2 = _leaning_foot(f, axes)
        return (-h1, h1), (-h2, h2)
    if f.turn is not None:
        h1, h2 = _turned_half(f, axes)
        return (-h1, h1), (-h2, h2)
    return _draw(f.kind).extent(f, axes)


def _line_length(f: Feature) -> float:
    """A line of letters' length (text.md): its letters' advances, its capitals ``height`` tall."""
    from forge_spec.font import CAP_HEIGHT

    assert f.words is not None
    return line_pieces(f.words)[1] * f.sizes["height"] / CAP_HEIGHT


def _right(face: _Flat) -> Array:
    """The way letters on a flat face run: its up (the face's second axis) across its outward normal (text.md)."""
    return np.asarray(np.cross(face.frame.v, face.normal), dtype=np.float64)






def _pattern_draw(mode: str) -> PatternDraw:
    """The pattern mode's entry in the ``draw`` role's modes, asked when drawing (as :func:`_draw`)."""
    from .items.draw.pattern import PATTERN_DRAW

    return PATTERN_DRAW[mode]


def _offsets(pattern: Pattern | None, face: _Flat | None) -> list[tuple[float, float]]:
    """Each copy's offset from the pattern's centre along the face's two axes, in the order they are numbered (place.md)."""
    if pattern is None:
        return [(0.0, 0.0)]
    v, c, kind = pattern.values, pattern.counts, pattern.kind
    return _pattern_draw(kind).offsets(pattern, face, v, c, kind)


def _names_the_axes(pattern: Pattern, axes: tuple[str, str]) -> bool:
    """Whether a pattern's values and counts that run along an axis name the face's two (place.md): a grid's pitches and counts, a rectangle's sides, the corners' insets."""
    a1, a2 = axes
    want = _pattern_draw(pattern.kind).axis_names(a1, a2)
    if want is None:
        return True
    return set(pattern.values) == want[0] and set(pattern.counts) == want[1]


def _centre_along(
    face: _Flat,
    k: int,
    pos: Position,
    offsets: list[float],
    extent: tuple[float, float],
    whole: bool,
) -> float:
    """The pattern's centre along the face's ``k``-th axis (place.md, "On a flat face"): from an edge to the item's point, or to its edge, ``extent`` (how far it reaches back and forth from its point) away."""
    centre = face.coords()[k]
    half = face.half[
        k
    ]  # a disc's and a ring's are its radius both ways; an outline's, its box's
    if pos.mode in ("none", "centred"):
        return centre
    if pos.mode == "offset":
        return centre + pos.distance
    sign = 1.0 if pos.side[0] == "+" else -1.0
    edge = centre + sign * half
    if whole:  # a circle is measured to its centre
        return edge - sign * pos.distance
    nearest = max(offsets) if sign > 0 else min(offsets)
    reach = (extent[1] if sign > 0 else extent[0]) if pos.to == "edge" else 0.0
    return edge - sign * pos.distance - reach - nearest


def _flat_spots(f: Feature, face: _Flat) -> list[tuple[float, float]]:
    """Where each copy's centre is on a flat face, along its two axes."""
    pattern = f.pattern
    extent = _extent(f, face.axes)
    if pattern is not None and _pattern_draw(pattern.kind).at_the_corners:
        cu, cv = face.coords()
        i1, i2 = (
            pattern.values[f"inset_{face.axes[0]}"],
            pattern.values[f"inset_{face.axes[1]}"],
        )
        h1, h2 = face.half
        return [
            (cu + s1 * (h1 - i1), cv + s2 * (h2 - i2))
            for s1 in (-1, 1)
            for s2 in (-1, 1)
        ]
    offsets = _offsets(pattern, face)
    whole = pattern is not None and _pattern_draw(pattern.kind).round_whole
    centre = [
        _centre_along(
            face,
            k,
            f.place.get(axis, Position("none")),
            [o[k] for o in offsets],
            extent[k],
            whole,
        )
        for k, axis in enumerate(face.axes)
    ]
    return [(centre[0] + o[0], centre[1] + o[1]) for o in offsets]


def _point(face: _Flat, at: tuple[float, float]) -> Array:
    return face.frame_at(at).origin


def _on_exit(face: _Flat, out: _Flat, foot: _Foot) -> _Foot:
    """A footprint on a face as the face a cut through it comes out on reads it: the same where their axes run the same
    ways; else (a turned item's far face, its cuts coming out on its host's far face) at the same point along the
    cut, the box round it along the far face's axes, a disc a disc (exit run 1436: a hole through a turned tab's far
    face came out under a block standing on the far end, its place read in the tab's coordinates)."""
    near, far = face.frame, out.frame
    if near._u == far._u and near._v == far._v:
        return foot
    at = far.plane(near.point(foot.at))
    if foot._disc():
        return _Foot(at, foot.half, foot.corner)
    (a1, a2, _), (b1, b2, _) = far.components(near.u), far.components(near.v)
    h1, h2 = foot.half
    return _Foot(at, (abs(a1) * h1 + abs(b1) * h2, abs(a2) * h1 + abs(b2) * h2), 0.0)


def _register_box(part: _Part, item: str, index: int, base: Array, up: str, axes: tuple[str, str],
                  sizes: tuple[float, float, float], under: float, exit_key: tuple[str, int, str] | None) -> None:  # fmt: skip
    """A box's faces (a block's or a post's): its far face over its host's material, its sides across it."""
    length, width, height = sizes
    n = _v(unit_of(up))
    e = {axes[0]: length, axes[1]: width, up[1]: height}
    middle = base + height / 2 * n
    for axis in "xyz":
        for sign in (1.0, -1.0):
            name = ("+" if sign > 0 else "-") + axis
            if name == ("-" if up[0] == "+" else "+") + up[1]:
                continue  # the face it is joined by
            d = _v(unit_of(name))
            centre = middle + e[axis] / 2 * d
            fa = _flat_axes(name)
            half = (e[fa[0]] / 2, e[fa[1]] / 2)
            if name == up:
                material, out = height + under, exit_key
            else:
                material, out = (
                    e[axis],
                    (item, index, ("-" if sign > 0 else "+") + axis),
                )
            part.flats[(item, index, name)] = _Flat(
                (item, index, name), centre, d, fa, "rect", half, material, out, level=name != up
            )


def _first(f: Feature, part: _Part) -> None:
    _draw(f.kind).first(f, part)


# ----------------------------------------------------------------------
# Outlines (extrusion.md, revolution.md; docs/V2-stage4.md, 6.6)
# ----------------------------------------------------------------------
#: The outlines an extrusion's first body is drawn with, and the half outlines a revolution's.
PUSHED = ("L", "T", "stadium", "corner")
TURNED = ("flange", "knob", "pulley")


def outline_of(shape: str, p: Mapping[str, float]) -> Outline2:
    """An outline the generator draws, from its sizes; a :class:`DoesNotFitError` where they don't make one.

    - ``L``: ``a`` along the first axis, ``b`` along the second, legs ``t`` thick;
    - ``T``: a bar ``w`` wide and ``t`` thick on a stem ``s`` wide, ``h`` high in all;
    - ``stadium``: ``l`` long, ``w`` wide, its ends round;
    - ``corner``: ``a`` by ``b``, its (+, +) corner rounded to ``r`` and its (-, +) corner cut back ``c``;
    - ``flange`` (turned): a disc ``R`` in radius and ``t`` thick, a hub ``rh`` in radius rising to ``h``,
      a bore ``rb`` in radius (0: none);
    - ``knob`` (turned): a stem ``rs`` in radius to ``h1``, a disc ``R`` in radius from ``h1`` to ``h2``,
      its rim rounded ``c`` above and below;
    - ``pulley`` (turned): ``R`` in radius and ``h`` high, a groove ``g`` in radius round its rim at
      half its height, a bore ``rb`` in radius.
    """

    def need(*conditions: bool) -> None:
        if not all(conditions):
            raise DoesNotFitError(f"a {shape} outline isn't made by {dict(p)}")

    def straight(
        *points: tuple[float, float],
    ) -> tuple[tuple[tuple[float, float], None, bool], ...]:
        return tuple((q, None, False) for q in points)

    if shape == "L":
        a, b, t = p["a"], p["b"], p["t"]
        need(0 < t < a - 1, t < b - 1)
        return Outline2(
            (0.0, 0.0), straight((a, 0.0), (a, t), (t, t), (t, b), (0.0, b), (0.0, 0.0))
        )
    if shape == "T":
        w, t, s_, h = p["w"], p["t"], p["s"], p["h"]
        need(0 < s_ < w - 1, 0 < t < h - 1)
        return Outline2((-s_ / 2, 0.0), straight((s_ / 2, 0.0), (s_ / 2, h - t), (w / 2, h - t), (w / 2, h), (-w / 2, h),
                                                 (-w / 2, h - t), (-s_ / 2, h - t), (-s_ / 2, 0.0)))  # fmt: skip
    if shape == "stadium":
        length, w = p["l"], p["w"]
        need(length > w + 1, w > 1)
        r, x = w / 2, length / 2 - w / 2
        return Outline2((-x, -r), (((x, -r), None, False), ((x, r), (x, 0.0), False), ((-x, r), None, False),
                                   ((-x, -r), (-x, 0.0), False)))  # fmt: skip
    if shape == "corner":
        a, b, r, c = p["a"], p["b"], p["r"], p["c"]
        need(0 < r < min(a, b) / 2, 0 < c < min(a, b) / 2)
        return Outline2((0.0, 0.0), (((a, 0.0), None, False), ((a, b - r), None, False), ((a - r, b), (a - r, b - r), False),
                                     ((c, b), None, False), ((0.0, b - c), None, False), ((0.0, 0.0), None, False)))  # fmt: skip
    if shape == "flange":
        rb, big, t, rh, h = p["rb"], p["R"], p["t"], p["rh"], p["h"]
        need(0 <= rb < rh - 1, rh < big - 1, 0 < t < h - 1)
        return Outline2(
            (rb, 0.0),
            straight((big, 0.0), (big, t), (rh, t), (rh, h), (rb, h), (rb, 0.0)),
        )
    if shape == "knob":
        rs, h1, big, c, h2 = p["rs"], p["h1"], p["R"], p["c"], p["h2"]
        need(0 < rs < big - c - 1, h1 > 0, h1 + 2 * c < h2 - 0.5, c > 0)
        return Outline2((0.0, 0.0), (((rs, 0.0), None, False), ((rs, h1), None, False), ((big - c, h1), None, False),
                                     ((big, h1 + c), (big - c, h1 + c), False), ((big, h2 - c), None, False),
                                     ((big - c, h2), (big - c, h2 - c), False), ((0.0, h2), None, False),
                                     ((0.0, 0.0), None, False)))  # fmt: skip
    if shape == "pulley":
        rb, big, g, h = p["rb"], p["R"], p["g"], p["h"]
        need(0 < rb < big - g - 1, 0 < g < h / 2 - 0.5)
        m = h / 2
        return Outline2((rb, 0.0), (((big, 0.0), None, False), ((big, m - g), None, False), ((big, m + g), (big, m), True),
                                    ((big, h), None, False), ((rb, h), None, False), ((rb, 0.0), None, False)))  # fmt: skip
    raise DoesNotFitError(f"no outline {shape!r}")


def _turned_ends(
    shape: str, p: Mapping[str, float]
) -> dict[str, tuple[float, float, float, float, bool]]:
    """A revolution's flat ends, each (its height, inner radius, outer radius, the least material under it, whether every line down through it runs right through to the other end)."""
    if shape == "flange":
        return {
            "+end": (p["h"], p["rb"], p["rh"], p["h"], True),
            "-end": (0.0, p["rb"], p["R"], p["t"], False),
        }
    if shape == "knob":
        return {"+end": (p["h2"], 0.0, p["R"] - p["c"], p["h2"] - p["h1"], False),
                "-end": (0.0, 0.0, p["rs"], p["h2"], True)}  # fmt: skip
    least = p["h"] / 2 - p["g"]
    return {
        "+end": (p["h"], p["rb"], p["R"], least, False),
        "-end": (0.0, p["rb"], p["R"], least, False),
    }


def _first_extrusion(f: Feature, part: _Part) -> None:
    """An extrusion as the first body: its outline in x and y from the origin, pushed ``length`` up z (extrusion.md)."""
    assert f.outline is not None
    shape = outline_of(f.outline[0], dict(f.outline[1]))
    length = f.sizes["length"]
    part.copies[f.id] = [
        Copy(f.id, 0, None, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), ("x", "y"))
    ]
    part.steps.append(Step(f.id, 0, True, Pushed((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                                                  shape, 0.0, length)))  # fmt: skip
    (l1, l2), (h1, h2) = shape.box()
    middle = ((l1 + h1) / 2, (l2 + h2) / 2)
    widest = _widest(shape)
    for name, z, sign, other in (
        ("+end", length, 1.0, "-end"),
        ("-end", 0.0, -1.0, "+end"),
    ):
        part.flats[(f.id, 0, name)] = _Flat((f.id, 0, name), _v((middle[0], middle[1], z)), _v((0.0, 0.0, sign)),
                                            ("x", "y"), "profile", ((h1 - l1) / 2, (h2 - l2) / 2), length,
                                            (f.id, 0, other), outline=shape, widest=widest)  # fmt: skip


def _widest(shape: Outline2) -> float:
    """About how wide the widest disc in an outline is (its radius): the farthest from its sides of a grid of points in it."""
    (l1, l2), (h1, h2) = shape.box()
    u, v = np.meshgrid(np.linspace(l1, h1, 41), np.linspace(l2, h2, 41))
    u, v = u.ravel(), v.ravel()
    inside = shape.inside(u, v)
    if not np.any(inside):
        return 0.0
    sides = shape.followed(0.5)
    gaps = np.min(
        fv.hypot(
            u[inside, None] - sides[None, :, 0], v[inside, None] - sides[None, :, 1]
        ),
        axis=1,
    )
    return float(gaps.max())


def _first_revolution(f: Feature, part: _Part) -> None:
    """A revolution as the first body: its half outline turned about z through the origin (revolution.md); its flat ends discs or rings."""
    assert f.outline is not None
    name, values = f.outline[0], dict(f.outline[1])
    shape = outline_of(name, values)
    part.copies[f.id] = [
        Copy(f.id, 0, None, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), ("x", "y"))
    ]
    part.steps.append(
        Step(f.id, 0, True, Turned((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), shape))
    )
    for end, (height, inner, outer, least, through) in _turned_ends(
        name, values
    ).items():
        other = "-end" if end == "+end" else "+end"
        part.flats[(f.id, 0, end)] = _Flat((f.id, 0, end), _v((0.0, 0.0, height)), _v((0.0, 0.0, 1.0 if end == "+end" else -1.0)),
                                           ("x", "y"), "ring" if inner > 0 else "disc", (outer, outer), least,
                                           (f.id, 0, other) if through else None, inner=inner)  # fmt: skip


def _outline_draft(f: Feature, source: dict[str, Any]) -> dict[str, Any]:
    """An outline as the draft writes it (extrusion.md): its start and each side, to a point, round a centre where an arc; ``source`` where it comes from."""
    assert f.outline is not None
    shape = outline_of(f.outline[0], dict(f.outline[1]))
    segments: list[dict[str, Any]] = []
    for to, centre, clockwise in shape.sides:
        if centre is None:
            segments.append({"line_to": [to[0], to[1]]})
        else:
            segments.append(
                {
                    "arc_to": [to[0], to[1]],
                    "centre": [centre[0], centre[1]],
                    **({"clockwise": True} if clockwise else {}),
                }
            )
    return {
        "start": [shape.start[0], shape.start[1]],
        "segments": segments,
        "from": source,
    }


def _on_flat(
    f: Feature, face: _Flat, index: int, part: _Part, strict: bool
) -> list[Copy]:
    """Every copy of a feature on one copy of a flat face: its copies, solids and new faces."""
    if f.angle is not None:
        raise DoesNotFitError(
            f"{f.id}: an angle places an item round a side, not on a flat face"
        )
    if f.tilt is not None:
        return _on_flat_leaning(f, face, index, part, strict)
    if (
        f.pattern is not None
        and _pattern_draw(f.pattern.kind).at_the_corners
        and face.shape != "rect"
    ):
        raise DoesNotFitError(f"{f.id}: corners are a rectangle's")
    if f.pattern is not None and not _names_the_axes(f.pattern, face.axes):
        raise DoesNotFitError(
            f"{f.id}: its pattern's values don't run along {face.key}'s axes {face.axes}"
        )
    for axis in (
        f.choices.get("along"),
        f.choices.get("thickness_along"),
        f.pattern.axis if f.pattern is not None else None,
        *f.place,
    ):
        if axis and axis not in face.axes:
            raise DoesNotFitError(
                f"{f.id}: {axis} isn't one of {face.key}'s axes {face.axes}"
            )
    if f.turn is not None and (f.on is None or not _draw(f.kind).turnable):
        raise DoesNotFitError(f"{f.id}: the generator turns a slot, a pocket, a rib, a tab, a block, a post or letters on a flat face")
    if face.turned and not _turns_with(f, face):
        raise DoesNotFitError(f"{f.id}: on a turned face, the generator puts a hole, a slot, a pocket, a boss, a "
                              "cylinder, a block, a post or a rib")  # fmt: skip
    half, corner = _footprint(f, face.axes)
    if f.turn is not None:  # what it covers, as the generator keeps it: the box round its turned outline
        half, corner = _turned_half(f, face.axes), 0.0
    spots = _flat_spots(f, face)
    feet = [face.foot(f, at) for at in spots]
    # Turned, or on a turned face, it is wholly on its face, clear of its edges by the gap: flush with none, over none.
    plain = f.turn is None and not face.turned
    flush = _flush(f, face) if plain else frozenset()
    beyond = _overhang(f, face, feet, strict) if plain else frozenset()
    if strict:
        for k, foot in enumerate(feet):
            if not face.holds(foot, GAP, flush, beyond):
                raise DoesNotFitError(
                    f"{f.id} copy {k} doesn't lie wholly on {face.key}"
                )
            for other in face.taken + feet[:k]:
                if not foot.clear_of(other, GAP):
                    raise DoesNotFitError(
                        f"{f.id} copy {k} meets something else on {face.key}"
                    )
    standing = _draw(f.kind).stands(f)
    rise = _rise(f) if standing else 0.0
    if strict and standing:
        _stays_in_room(f, face, feet, rise, part)
    before = set(part.flats)
    n = face.normal
    e1, e2 = _turned_frame(f, face.frame.u, face.frame.v)
    made = []
    first = len(part.steps)
    for k, at in enumerate(spots):
        p = _point(face, at)
        copy_index = index + k
        made.append(Copy(f.id, copy_index, face.key, _t(p), _t(n), face.axes))
        cut = _draw(f.kind).cut_out
        if cut:
            depth = face.material if f.depth is None else f.depth
            if strict and f.depth is not None and f.depth > face.material - GAP:
                raise DoesNotFitError(
                    f"{f.id} is deeper than the material under {face.key}"
                )
            if strict and _recess_depth(f) > face.material - GAP:
                raise DoesNotFitError(
                    f"{f.id}'s {f.recess[0] if f.recess else ''} is deeper than the material under {face.key}"
                )
            if (
                strict
                and f.depth is not None
                and face.dome > 0
                and f.depth > face.material_under(_Foot(at, half, corner)) - GAP
            ):
                # Under a dome's flat face the material is the dome's height over a point: least at the cut's
                # farthest from the centre (its box's corner, a bound).
                raise DoesNotFitError(f"{f.id} is deeper than the dome over it")
            if strict and face.flare[1] > 0:
                room = face.material_under(_Foot(at, half, corner))
                if f.depth is None and room < face.material:
                    # Past a flared cone's base, a line down comes out of its flank into the air under it, and
                    # in again further down: right through has no one meaning (generated part 3375).
                    raise DoesNotFitError(
                        f"{f.id} can't go right through {face.key} past its cone's base"
                    )
                if f.depth is not None and f.depth > room - GAP:
                    raise DoesNotFitError(
                        f"{f.id} is deeper than the cone over its flank"
                    )
                if _recess_depth(f) > room - GAP:
                    raise DoesNotFitError(
                        f"{f.id}'s recess is deeper than the cone over its flank"
                    )
            through = f.depth is None
            if strict and through and face.exit is None:
                # Not every line down through the face comes out on another (a flange's foot, its hub deeper
                # than its rim): what is under it isn't one depth, and right through has no one meaning
                # (generated part 771's mutant, a hole moved to its revolution's other end).
                raise DoesNotFitError(f"{f.id} can't go right through {face.key}")
            if strict and face.exit is not None and face.exit not in part.flats:
                # The far face is pressed against something (a box flush with a hollow's wall): there is no face
                # there for a cut to come out on, only what it is pressed against.
                if through:
                    raise DoesNotFitError(
                        f"{f.id} would come out where {face.exit} is pressed against another"
                    )
            elif strict and face.exit is not None:
                out = part.flats[face.exit]
                mine = _on_exit(face, out, _Foot(at, half, corner))
                if through and not out.holds(mine):
                    raise DoesNotFitError(
                        f"{f.id} doesn't come out wholly on {face.exit}"
                    )
                for foot in out.taken if through else ():
                    if not mine.clear_of(foot, GAP):
                        raise DoesNotFitError(
                            f"{f.id} comes out through {face.exit} where something is"
                        )
                for foot, deep in out.dug:
                    if (
                        not mine.clear_of(foot, 0.0)
                        and abs(depth + deep - face.material) < 0.3
                    ):
                        raise DoesNotFitError(
                            f"{f.id} all but breaks into a cut from the far side"
                        )
            low_reach = REACH if through else 0.0
            solid, radius = _draw(f.kind).cut_solid(f, p, e1, e2, n, depth, face)
            part.steps.append(Step(f.id, copy_index, False, solid, (low_reach, REACH)))
            if f.recess is not None:
                what, d, third = f.recess
                if what == "counterbore":
                    part.steps.append(Step(f.id, copy_index, False,
                                           Prism(_t(p), _t(e1), _t(e2), _t(n), (d / 2, d / 2), d / 2, -third, 0.0), (0.0, REACH)))  # fmt: skip
                else:
                    recess = (d / 2 - radius) / fs.tan(math.radians(third / 2))
                    # Carried on into the hole (air), and out of its mouth only as far
                    # as it widens within the gap round it: out there may be the wall
                    # of what its face stands beside.
                    part.steps.append(
                        Step(f.id, copy_index, False, Frustum(_t(p), _t(-n), (d / 2, radius), recess), (REACH, 0.2))
                    )  # fmt: skip
        else:
            _draw(f.kind).stand_flat(
                f, copy_index, p, n, e1, e2, face, part, strict, feet, k, beyond, flush
            )
    if strict and standing:
        _stands_in_air(f, made, part.steps[first:], (*part.steps[:first], *part.late))
    _in_room(face, before, part)
    if standing and face.hollow is not None:
        for k, foot in enumerate(feet):
            part.inside.setdefault(face.hollow, []).append(
                (f"{f.id} {index + k}", *_box_over(face, foot, rise))
            )
    for at in spots:
        face.taken.append(face.foot(f, at))
        _draw(f.kind).marks(f, face, at, half, corner, part)
    return made


#: How far past a face's edge, at least, a body that overhangs it reaches; and how much of it, at least, stays
#: over the face across that edge (mm).
_OVERHANG = (GAP, 1.0)
#: How far in from the block's sides and the face's edges an overhanging block's foot is kept (mm): none of
#: its sides then lies within a rounding error of a side of theirs, for a mesh.
_FOOT_IN = 0.001


def _overhang(
    f: Feature, face: _Flat, feet: list[_Foot], strict: bool
) -> frozenset[tuple[int, float]]:
    """The sides of a rectangle a single block standing on it reaches past, each its axis's index and which end (frame.md: a body may overhang the face it stands on, but must meet it).

    It reaches past by ``_OVERHANG[0]`` at least, and stays over the face by
    ``_OVERHANG[1]``; the face is a plain rectangle (no corner or side a
    rounding has taken: what is under the overhang there would be air), out
    of any hollow.
    """
    return _draw(f.kind).overhang(f, face, feet, strict)


def _flush(f: Feature, face: _Flat) -> frozenset[tuple[int, float]]:
    """The sides of a face an item stands flush with (place.md: ``0`` from that edge, to its edge): a box's side in the plane of the face's side there, or a boss's round side touching the edge (tangent to it), its axis's index and which end; only a block, a post or a boss, one copy, here."""
    found = frozenset(
        (k, 1.0 if pos.side[0] == "+" else -1.0)
        for k, axis in enumerate(face.axes)
        if (pos := f.place.get(axis)) is not None
        and pos.mode == "side"
        and pos.distance == 0
        and pos.to == "edge"
    )
    if found and (not _draw(f.kind).stands_flush or f.pattern is not None):
        raise DoesNotFitError(
            f"{f.id}: the generator stands only a single box or boss flush with a face's edge"
        )
    if found and _draw(f.kind).falls_flush and face.key[2].startswith("inner"):
        # Inside a hollow the next wall rises from the edge: the boss would lie along it, touching it on a line.
        raise DoesNotFitError(
            f"{f.id}: a boss touches only an edge its face falls away from"
        )
    return found


def _touches_falling_edges(f: Feature, p: Array, frame: tuple[Array, Array, Array], radius: float, height: float,
                           flush: frozenset[tuple[int, float]], part: _Part) -> None:  # fmt: skip
    """A boss flush with a face's edge touches the edge along a line: only an edge the face falls away from, with nothing in front of the face just past it (generated part 1566: a boss on a standing block's side, flush with the block's foot, lay along the plate the block stands on, touching it on a line: two solids meeting along an edge, no solid).

    The part as made so far is asked about points :data:`_PAST` beyond the
    edge, along the line where the boss touches it.
    """
    e1, e2, n = frame
    along = np.linspace(0.1, 0.9, 9) * height
    so_far = Truth({}, (*part.steps[:-1], *part.late))
    for j, end in flush:
        out = end * (e1, e2)[j]
        points = p + (radius + _PAST) * out + along[:, None] * n
        if np.any(so_far.inside(points)):
            raise DoesNotFitError(
                f"{f.id}: a boss touches only an edge its face falls away from"
            )


#: How far past a face's edge a boss flush with it is asked to have nothing in front of the face (mm).
_PAST = 0.01


def _overhanging(f: Feature, index: int, p: Array, frame: tuple[Array, Array, Array], half: tuple[float, float],
                 height: float, face: _Flat, part: _Part, strict: bool) -> None:  # fmt: skip
    """A block overhanging the face it stands on: itself from the face's plane up, and, where it is over the face, its foot run a hair into the face and out of it, its sides a hair in from the block's and the face's edges (:data:`_FOOT_IN`), so a mesh of the two is joined there and none of its faces hangs under the overhang.

    What it hangs over past each edge is kept clear of everything made
    before or after, but what stands on it or is cut into it (a post on the
    plate below, taller than the plate it stands on, would run into it).
    """
    e1, e2, n = frame
    block = Prism(_t(p), _t(e1), _t(e2), _t(n), half, 0.0, 0.0, height)
    part.steps.append(Step(f.id, index, True, block))
    centre, at = face.coords(), face.frame.plane(p)
    lo = [max(at[k] - half[k], centre[k] - face.half[k]) for k in (0, 1)]
    hi = [min(at[k] + half[k], centre[k] + face.half[k]) for k in (0, 1)]
    middle = p + ((lo[0] + hi[0]) / 2 - at[0]) * e1 + ((lo[1] + hi[1]) / 2 - at[1]) * e2
    foot = Prism(
        _t(middle),
        _t(e1),
        _t(e2),
        _t(n),
        ((hi[0] - lo[0]) / 2 - _FOOT_IN, (hi[1] - lo[1]) / 2 - _FOOT_IN),
        0.0,
        -REACH,
        REACH,
    )
    part.steps.append(Step(f.id, index, True, foot))
    box_lo, box_hi = bounds(block)
    for k in (0, 1):
        i = "xyz".index(face.axes[k])
        for end, edge in (
            (-1.0, centre[k] - face.half[k]),
            (1.0, centre[k] + face.half[k]),
        ):
            if end * (at[k] - edge) + half[k] <= 0:
                continue
            # What hangs past this edge, a hair in from its own faces.
            a, b = box_lo.copy(), box_hi.copy()
            if end > 0:
                a[i] = edge
            else:
                b[i] = edge
            a, b = a + 1e-6, b - 1e-6
            if strict:
                for other in (*part.steps[:-2], *part.late):
                    c, d = bounds(other.solid)
                    if other.item != f.id and np.all(a <= d) and np.all(c <= b):
                        raise DoesNotFitError(f"{f.id} overhangs {other.item}")
            part.kept.append((f"{f.id}'s overhang", a, b, f.id))


def _rise(f: Feature) -> float:
    """How far a standing item rises out of the face it stands on: its height, its length, a ball's radius, a revolution's greatest height, embossed letters' depth."""
    return _draw(f.kind).rise(f)


def _box_over(face: _Flat, foot: _Foot, rise: float) -> tuple[Array, Array]:
    """The box a standing copy takes up over a face: its footprint, out of the face as far as it rises."""
    lo, hi = np.empty(3), np.empty(3)
    for a, at, h in zip(face.axes, foot.at, foot.half, strict=True):
        lo["xyz".index(a)], hi["xyz".index(a)] = at - h, at + h
    k = int(np.argmax(np.abs(face.normal)))
    plane = float(face.centre[k])
    out = plane + rise * float(face.normal[k])
    lo[k], hi[k] = min(plane, out), max(plane, out)
    return lo, hi


def _stays_in_room(
    f: Feature, face: _Flat, feet: list[_Foot], rise: float, part: _Part
) -> None:
    """A standing item in a hollow keeps ``GAP`` short of the wall across it, and its box ``GAP`` clear of the boxes of the rest standing there (all but the copy it stands on)."""
    if rise > face.room - GAP:
        raise DoesNotFitError(
            f"{f.id} rises to the wall across the hollow from {face.key}"
        )
    if face.hollow is None:
        return
    host = f"{face.key[0]} {face.key[1]}"
    for foot in feet:
        lo, hi = _box_over(face, foot, rise)
        for who, a, b in part.inside.get(face.hollow, []):
            if who != host and not np.any((lo >= b + GAP) | (a >= hi + GAP)):
                raise DoesNotFitError(
                    f"{f.id} meets what stands in {face.hollow[0]}'s hollow"
                )


def _stands_in_air(
    f: Feature, copies: list[Copy], new: Sequence[Step], earlier: Sequence[Step]
) -> None:
    """What stands on a face stands in air: no point within it, above its face past its foot, is in what was made before (generated part 2404: a block on the lower of two stacked copies of a block ran up into the upper one, and a hole through it ran on into that one's material).

    And what of it lies under the face, past the ``REACH`` its foot is carried
    on into the face by, lies in what was made before, as a rod's foot does
    (:func:`_foot_in_material`): it adds nothing there (generated part 2995:
    a whole ball sunk to its middle in a block's top, over a hole drilled
    right through the block, refilled 4 mm of the hole, which then went
    through only by its definitions' order).

    Above, asked at the middles of a grid of cells over each copy's solids'
    box; under, where anything is (a whole ball's lower half), at most
    :data:`_UNDER_STEP` apart over the box's part under the face.
    """
    made_before = Truth({}, tuple(earlier))
    for copy in copies:
        mine = tuple(s for s in new if s.index == copy.index and s.add)
        if not mine:
            continue
        boxes = [bounds(s.solid) for s in mine]
        lo = np.min([b[0] for b in boxes], axis=0)
        hi = np.max([b[1] for b in boxes], axis=0)
        cells = [
            (lo[k] + (np.arange(_AIR_CELLS) + 0.5) * (hi[k] - lo[k]) / _AIR_CELLS)
            for k in range(3)
        ]
        grid = np.stack(np.meshgrid(*cells, indexing="ij"), axis=-1).reshape(-1, 3)
        point, up = _v(copy.point), _v(copy.direction)
        above = grid[fv.matmul(grid - point, up) > REACH + 1e-3]
        within = above[Truth({}, mine).inside(above)]
        if len(within) and np.any(made_before.inside(within)):
            raise DoesNotFitError(f"{f.id} runs into something made before it")
        corners = np.array(
            [[(lo, hi)[(k >> j) & 1][j] for j in range(3)] for k in range(8)]
        )
        if float(np.min(fv.matmul(corners - point, up))) >= -(REACH + 1e-3):
            continue  # nothing of it under its face but its foot
        # Over the whole box, and finer over where each cut made before meets it: a hole's air is
        # looked at by points a tenth of its box apart, however large what is sunk over it.
        regions = [(lo, hi, max(_SUNK_STEP, float(np.max(hi - lo)) / _SUNK_CELLS))]
        for step in earlier:
            if step.add:
                continue
            a, b = bounds(step.solid)
            a, b = np.maximum(a, lo), np.minimum(b, hi)
            if np.all(b > a):
                regions.append((a, b, min(_SUNK_STEP, float(np.min(b - a)) / 10)))
        under = np.concatenate([_grid(a, b, h) for a, b, h in regions])
        under = under[fv.matmul(under - point, up) < -(REACH + 1e-3)]
        within = under[Truth({}, mine).inside(under)]
        if len(within) and not np.all(made_before.inside(within)):
            raise DoesNotFitError(
                f"{f.id} would fill what is cut into or lies past {copy.host}"
            )


def _grid(lo: Array, hi: Array, h: float) -> Array:
    """Points ``h`` apart at most over a box, its sides included, each axis at most :data:`_SUNK_CELLS` + 1 of them."""
    axes = [
        np.linspace(
            lo[k], hi[k], min(_SUNK_CELLS, max(1, math.ceil((hi[k] - lo[k]) / h))) + 1
        )
        for k in range(3)
    ]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


#: How many cells a side the grid :func:`_stands_in_air` asks at the middles of has.
_AIR_CELLS = 12
#: How far apart, at most, the points under a standing item's face are asked at (mm), and how many a side.
_SUNK_STEP = 0.25
_SUNK_CELLS = 64


def _in_room(face: _Flat, before: set[tuple[str, int, str]], part: _Part) -> None:
    """The faces made by what stands on a face in a hollow are in it too: a face facing the same way has the room left above it; any other, none (what stood on it might meet the hollow's walls)."""
    if face.hollow is None and math.isinf(face.room):
        return
    for key in set(part.flats) - before:
        new = part.flats[key]
        new.hollow = face.hollow
        if float(fv.matmul(new.normal, face.normal)) > 0.5:
            new.room = face.room - float(
                fv.matmul(new.centre - face.centre, face.normal)
            )
        else:
            new.room = 0.0 if face.hollow is not None else math.inf


def _on_round(
    f: Feature, side: _Round, index: int, part: _Part, strict: bool
) -> list[Copy]:
    """Holes round a rod's side: at an angle round its axis (a circle of them), along it from its ends; a boss or a post standing round it (:func:`_standing_round`)."""
    if f.tilt is not None:
        raise DoesNotFitError(f"{f.id}: an item leans on a flat face, not round a side")
    return _draw(f.kind).on_round(f, side, index, part, strict)


def _along(pos: Position, side: _Round | _Cone, half: float) -> float:
    """Where along a rod's side (from its start) a position puts an item's centre, ``half`` its extent along the axis."""
    if pos.mode in ("none", "centred"):
        return side.length / 2
    if pos.mode == "offset":
        return side.length / 2 + pos.distance
    to_edge = half if pos.to == "edge" else 0.0
    if pos.side[0] == "+":
        return side.length - pos.distance - to_edge
    return pos.distance + to_edge


def _standing_round(f: Feature, side: _Round, index: int, part: _Part, strict: bool) -> list[Copy]:  # fmt: skip
    """A boss or a post standing round a rod's side (place.md): out along the radius at any angle (item 3b's first step;
    at 0, 90, 180 or 270 degrees before it), or a circle of them, its length round the side and its width along its
    axis; one copy, or a circle. At an angle that isn't a frame axis's, its far face is named as at the frame axis at
    or below it, its axes turned with it (``oriented``).

    Its height is from its point on the side's surface. Its truth runs on
    into the rod past where the side curves away under its foot (the
    surface's sag across its round extent, and :data:`REACH`), all of it in
    the rod's material (a tube's wall must hold it). What stands out is kept
    clear of everything else made before or after but what stands on it or
    is cut into it; a rounding of the rod's rim, or a thread on it, keeps
    clear of its stretch.
    """
    if f.pattern is not None and not _pattern_draw(f.pattern.kind).round_whole:
        raise DoesNotFitError(f"{f.id}: round a side, copies go round it (a circle)")
    if set(f.place) - {side.axis}:
        raise DoesNotFitError(f"{f.id}: round a side, placed along its axis")
    s = f.sizes
    entry = _draw(f.kind)
    if entry.round_foot:
        rounded, wide, height = s["diameter"] / 2, s["diameter"] / 2, s["height"]
    else:
        rounded, wide, height = s["length"] / 2, s["width"] / 2, s["height"]
    start = f.angle or 0.0
    n = f.pattern.counts["count"] if f.pattern is not None else 1
    angles = [start + k * 360.0 / n for k in range(n)]
    along = _along(f.place.get(side.axis, Position("none")), side, wide)
    sag = side.radius - math.sqrt(
        max(side.radius * side.radius - rounded * rounded, 0.0)
    )
    carry = sag + REACH
    if strict:
        if (
            along - wide < GAP + side.margin[0]
            or along + wide > side.length - GAP - side.margin[1]
        ):
            raise DoesNotFitError(
                f"{f.id} runs past the side's end, or onto a rounding of its rim"
            )
        if rounded > side.radius / 2:
            raise DoesNotFitError(f"{f.id} is too wide for the rod, here")
        if side.bore > 0 and carry + REACH > side.radius - side.bore - GAP:
            raise DoesNotFitError(f"{f.id}'s foot would reach the tube's bore")
        mine = [(along, a, fs.hypot(rounded, wide), carry) for a in angles]
        for k, here in enumerate(mine):
            for other in side.taken + mine[:k]:
                if not _holes_apart(here, other, side.radius):
                    raise DoesNotFitError(f"{f.id} meets something else round the side")
    w = side.frame.n
    zero, quarter = side.frame.u, side.frame.v
    # What else is on this side is kept apart above; the rod itself is what it stands on.
    beside = {
        c.item for copies in part.copies.values() for c in copies if c.host == side.key
    }
    beside.add(side.key[0])
    made = []
    for k, a in enumerate(angles):
        square = abs(a / 90.0 - round(a / 90.0)) <= 1e-9
        below = a if square else 90.0 * math.floor(a / 90.0)
        u = (
            np.round(fs.cos(math.radians(below)) * zero + fs.sin(math.radians(below)) * quarter)
            + 0.0
        )
        third = "xyz"[int(np.argmax(np.abs(np.cross(u, w))))]
        e = _v(unit_of("+" + third))
        up = _named(u)
        oriented: tuple[Vec, Vec] | None = None
        if not square:  # its own ways turned with the side about its axis by the rest (item 3b's first step)
            sign = float(fv.dot(e, np.cross(u, w)))
            u = fs.cos(math.radians(a)) * zero + fs.sin(math.radians(a)) * quarter + 0.0
            e = sign * np.asarray(np.cross(u, w), dtype=np.float64) + 0.0
            ways = {third: e, side.axis: w}
            oriented = (_t(ways[_flat_axes(up)[0]]), _t(ways[_flat_axes(up)[1]]))
        p = side.frame_at(u, along).origin
        copy_index = index + k
        if entry.round_foot:
            solid: Prism = Prism(
                _t(p), _t(e), _t(w), _t(u), (rounded, rounded), rounded, -carry, height
            )
        else:
            solid = Prism(
                _t(p), _t(e), _t(w), _t(u), (rounded, wide), 0.0, -carry, height
            )
        lo, hi = bounds(replace(solid, low=0.0))  # what stands out of the rod
        if strict:
            _foot_in_material(f, solid, side, w, part)
            for earlier in (*part.steps, *part.late):
                c, d = bounds(earlier.solid)
                if earlier.item not in beside and np.all(lo <= d) and np.all(c <= hi):
                    raise DoesNotFitError(f"{f.id} stands into {earlier.item}")
        part.steps.append(Step(f.id, copy_index, True, solid, (REACH, 0.0)))
        part.kept.append(
            (f"{f.id} round {side.key[0]}'s side", lo - GAP / 2, hi + GAP / 2, f.id)
        )
        made.append(Copy(f.id, copy_index, side.key, _t(p), _t(u), (third, side.axis)))
        # Only its far face takes anything (place.md, for now), over its own height.
        fa = _flat_axes(up)
        if entry.round_far_end:
            far = (f.id, copy_index, "+end")
            part.flats[far] = _Flat(
                far,
                p + height * u,
                u.copy(),
                fa,
                "disc",
                (rounded, rounded),
                height,
                None,
                oriented=oriented,
            )
        else:
            far = (f.id, copy_index, up)
            half = {third: rounded, side.axis: wide}
            part.flats[far] = _Flat(far, p + height * u, u.copy(), fa, "rect", (half[fa[0]], half[fa[1]]), height,
                                    None, oriented=oriented)  # fmt: skip
    side.taken += [(along, a, fs.hypot(rounded, wide), carry) for a in angles]
    side.standing.append((along - wide, along + wide))
    return made


def _on_ball(f: Feature, ball: _Ball, index: int, part: _Part, strict: bool) -> list[Copy]:
    """A hole, a boss or a post on a ball's or a dome's surface (item 3b's second step; place.md, "On a ball's
    surface"): at its latitude (90, its pole, where it gives none) and its angle round the pole, or a circle of them
    there; along the ball's radius, a hole's depth from its point, a standing one's height out of it, its foot carried
    into the ball past where the surface curves away under it. Its faces take nothing, for now. What it is made of is
    kept clear of everything else made but the ball and what the ball stands on."""
    entry = _draw(f.kind)
    if not entry.on_curved:
        raise DoesNotFitError(f"{f.id}: on a ball's surface, a hole, a boss or a post")
    if f.pattern is not None and not _pattern_draw(f.pattern.kind).round_whole:
        raise DoesNotFitError(f"{f.id}: round a ball's pole, copies go round it (a circle)")
    if f.place or f.turn is not None or f.tilt is not None or f.recess is not None:
        raise DoesNotFitError(f"{f.id}: on a ball's surface, a latitude and an angle round its pole only")
    latitude = 90.0 if f.latitude is None else f.latitude
    start = f.angle or 0.0
    n = f.pattern.counts["count"] if f.pattern is not None else 1
    angles = [start + k * 360.0 / n for k in range(n)]
    s = f.sizes
    cut = entry.cut_out
    if cut or entry.round_foot:
        h1 = h2 = s["diameter"] / 2
    else:
        h1, h2 = s["length"] / 2, s["width"] / 2
    r = ball.radius
    reach = fs.hypot(h1, h2) if not (cut or entry.round_foot) else h1
    if reach >= r / 2:
        raise DoesNotFitError(f"{f.id} is too wide for the ball, here")
    spread = math.degrees(fs.asin(reach / r))
    margin = math.degrees(GAP / r)
    through = cut and f.depth is None
    if strict:
        if latitude - spread < ball.lowest + 2 * margin or latitude > 90.0:
            raise DoesNotFitError(f"{f.id} runs past where the ball's surface ends")
        if through and (ball.dome or ball.standing):
            raise DoesNotFitError(f"{f.id}: right through a whole ball standing on nothing only")
        if cut and f.depth is not None:
            least = r + math.sqrt(r * r - reach * reach)
            if ball.dome:
                c, sp = _cos_sin(latitude)
                least = min(least, r - reach * c / sp)
            if f.depth > least - GAP:
                raise DoesNotFitError(f"{f.id} is deeper than the ball under it")
        # Apart from the rest on the ball where they come closest: at their feet, and holes where they reach deepest.
        deep = r - (2 * r if through else (f.depth or 0.0)) if cut else r
        mine = [(a, latitude, spread) for a in angles]
        for k, here in enumerate(mine):
            for other in ball.taken + mine[:k]:
                (c1, s1), (c2, s2) = _cos_sin(here[1]), _cos_sin(other[1])
                apart = fs.acos(min(1.0, max(-1.0, s1 * s2 + c1 * c2 * _cos_sin(here[0] - other[0])[0])))
                if math.degrees(apart) < here[2] + other[2] + 2 * margin:
                    raise DoesNotFitError(f"{f.id} meets something else on {ball.key[0]}'s surface")
                if cut and other in mine and deep > GAP and 2 * deep * fs.sin(apart / 2) < 2 * reach + GAP:
                    raise DoesNotFitError(f"{f.id}'s copies meet inside {ball.key[0]}")
    host = ball.key[0]
    beside = {host, *(c.host[0] for c in part.copies.get(host, []) if c.host is not None)}
    made = []
    for k, a in enumerate(angles):
        out, east, south = ball.ways(a, latitude)
        p = ball.centre + r * out
        copy_index = index + k
        if cut:
            depth = 2 * r if through else float(f.depth or 0.0)
            solid = Prism(_t(p), _t(east), _t(south), _t(out), (h1, h2), h1, -depth, 0.0)
            step = Step(f.id, copy_index, False, solid, (REACH if through else 0.0, REACH))
        else:
            sag = r - math.sqrt(max(r * r - reach * reach, 0.0))
            corner = h1 if entry.round_foot else 0.0
            solid = Prism(_t(p), _t(east), _t(south), _t(out), (h1, h2), corner, -(sag + REACH), s["height"])
            step = Step(f.id, copy_index, True, solid, (REACH, 0.0))
        if strict:
            lo, hi = bounds(replace(solid, low=0.0)) if not cut else bounds(solid)
            for earlier in (*part.steps, *part.late):
                its_lo, its_hi = bounds(earlier.solid)
                if earlier.item not in beside and np.all(lo <= its_hi) and np.all(its_lo <= hi):
                    raise DoesNotFitError(f"{f.id} {'cuts' if cut else 'stands'} into {earlier.item}")
            if not cut:
                _foot_in_ball(f, solid, ball, part)
        part.steps.append(step)
        if not cut:
            lo, hi = bounds(replace(solid, low=0.0))
            part.kept.append((f"{f.id} on {host}'s surface", lo - GAP / 2, hi + GAP / 2, f.id))
        meridian, east_name = TURN_AXES[ball.up[1]]
        made.append(Copy(f.id, copy_index, ball.key, _t(p), _t(out), (east_name, meridian)))
    ball.taken += [(a, latitude, spread) for a in angles]
    return made


def _on_cone(f: Feature, cone: _Cone, index: int, part: _Part, strict: bool) -> list[Copy]:
    """A hole, a boss or a post on a cone's side (item 3b's third step; place.md, "On a cone's side"): at its angle round
    the axis and its place along it, as round a side, or a circle of them there; along the cone's normal, a hole's
    depth from its point, a standing one's height out of it, its foot carried into the cone twice as far as the side
    falls away under its farthest reach, at its narrowest. Its faces take nothing, for now. A hole is blind. What it is
    made of is kept clear of everything else made but the cone and what the cone stands on."""
    entry = _draw(f.kind)
    if not entry.on_curved:
        raise DoesNotFitError(f"{f.id}: on a cone's side, a hole, a boss or a post")
    if f.pattern is not None and not _pattern_draw(f.pattern.kind).round_whole:
        raise DoesNotFitError(f"{f.id}: round a cone, copies go round it (a circle)")
    if set(f.place) - {cone.axis} or f.turn is not None or f.tilt is not None or f.recess is not None:
        raise DoesNotFitError(f"{f.id}: on a cone's side, a place along its axis and an angle round it only")
    if f.latitude is not None:
        raise DoesNotFitError(f"{f.id}: a latitude is a ball's")
    cut = entry.cut_out
    if cut and f.depth is None:
        raise DoesNotFitError(f"{f.id}: a hole into a cone's side is blind")
    s = f.sizes
    if cut or entry.round_foot:
        h1 = h2 = s["diameter"] / 2
    else:
        h1, h2 = s["length"] / 2, s["width"] / 2
    reach = fs.hypot(h1, h2) if not (cut or entry.round_foot) else h1
    lc, ls = cone.lean
    reach_along = h2 * lc
    along = _along(f.place.get(cone.axis, Position("none")), cone, reach_along)
    narrowest = min(cone.radius_at(along - reach_along), cone.radius_at(along + reach_along))
    curve = narrowest / lc
    sag = curve - math.sqrt(max(curve * curve - reach * reach, 0.0))
    carry = 2 * sag + REACH
    start = f.angle or 0.0
    n = f.pattern.counts["count"] if f.pattern is not None else 1
    angles = [start + k * 360.0 / n for k in range(n)]
    if narrowest <= 0.0 or reach >= narrowest / 2:
        raise DoesNotFitError(f"{f.id} is too wide for the cone, here")
    spread = math.degrees(fs.asin(min(h1 / narrowest, 1.0)))
    if strict:
        foot = reach_along + carry * abs(ls)
        if along - foot < 2 * GAP or along + foot > cone.length - 2 * GAP:
            raise DoesNotFitError(f"{f.id} runs past the end of {cone.key[0]}'s side")
        margin = math.degrees(GAP / narrowest)
        if cut:
            p, normal, around, slant = cone.ways(0.0, along)
            rim = [p + h1 * (c * around + si * slant) for c, si in (_cos_sin(a) for a in range(0, 360, 5))]
            least = float(np.min(cone.exit(np.asarray(rim), -normal)))
            if float(f.depth or 0.0) > least - GAP:
                raise DoesNotFitError(f"{f.id} is deeper than the cone under it")
        # Apart from the rest on the cone where they come closest: at their feet, and holes where they reach deepest.
        deep = narrowest - float(f.depth or 0.0) * lc if cut else narrowest
        mine = [(a, spread, along, foot) for a in angles]
        for k, here in enumerate(mine):
            for other in cone.taken + mine[:k]:
                if abs(here[2] - other[2]) >= here[3] + other[3] + GAP:
                    continue  # apart along it
                apart = abs(math.remainder(here[0] - other[0], 360.0))
                if apart < here[1] + other[1] + 2 * margin:
                    raise DoesNotFitError(f"{f.id} meets something else on {cone.key[0]}'s side")
                if cut and other in mine and deep > GAP and 2 * deep * fs.sin(math.radians(apart) / 2) < 2 * h1 + GAP:
                    raise DoesNotFitError(f"{f.id}'s copies meet inside {cone.key[0]}")
    host = cone.key[0]
    beside = {host, *(c.host[0] for c in part.copies.get(host, []) if c.host is not None)}
    made = []
    for k, a in enumerate(angles):
        p, normal, around, slant = cone.ways(a, along)
        copy_index = index + k
        corner = h1 if (cut or entry.round_foot) else 0.0
        if cut:
            solid = Prism(_t(p), _t(around), _t(slant), _t(normal), (h1, h2), corner, -float(f.depth or 0.0), 0.0)
            step = Step(f.id, copy_index, False, solid, (0.0, REACH))
        else:
            solid = Prism(_t(p), _t(around), _t(slant), _t(normal), (h1, h2), corner, -carry, s["height"])
            step = Step(f.id, copy_index, True, solid, (REACH, 0.0))
        if strict:
            lo, hi = bounds(replace(solid, low=0.0)) if not cut else bounds(solid)
            for earlier in (*part.steps, *part.late):
                its_lo, its_hi = bounds(earlier.solid)
                if earlier.item not in beside and np.all(lo <= its_hi) and np.all(its_lo <= hi):
                    raise DoesNotFitError(f"{f.id} {'cuts' if cut else 'stands'} into {earlier.item}")
            if not cut:
                _foot_in_cone(f, solid, cone, part)
        part.steps.append(step)
        if not cut:
            lo, hi = bounds(replace(solid, low=0.0))
            part.kept.append((f"{f.id} on {host}'s side", lo - GAP / 2, hi + GAP / 2, f.id))
        below = 90.0 * math.floor(a / 90.0 + 1e-9)
        c, si = _cos_sin(below)
        up = _named(c * cone.frame.u + si * cone.frame.v)
        made.append(Copy(f.id, copy_index, cone.key, _t(p), _t(normal),
                         (next(x for x in "xyz" if x not in (up[1], cone.axis)), cone.axis)))  # fmt: skip
    cone.taken += [(a, spread, along, reach_along + carry * abs(ls)) for a in angles]
    return made


def _foot_in_cone(f: Feature, solid: Prism, cone: _Cone, part: _Part) -> None:
    """A standing item's foot lies all in its cone (carried in, it comes out of no end, nor out through the side
    beyond it), and what of it lies within the cone's side lies in the part made so far: it fills no hole drilled into
    the cone there."""
    centre, first, second, n = (_v(x) for x in (solid.centre, solid.first, solid.second, solid.normal))
    h1, h2 = solid.half
    a, b = np.meshgrid(np.linspace(-h1, h1, 15), np.linspace(-h2, h2, 15), indexing="ij")
    if solid.corner >= min(h1, h2):  # a boss: a disc
        keep = a * a + b * b <= solid.corner * solid.corner
        a, b = a[keep], b[keep]
    across = centre + a.reshape(-1, 1) * first + b.reshape(-1, 1) * second
    if not np.all(cone.inside(across + solid.low * n, 1e-3)):
        raise DoesNotFitError(f"{f.id}'s foot would come out of {cone.key[0]}")
    depth = np.linspace(solid.low, 0.0, 8)
    points = (across[:, None, :] + depth[None, :, None] * n).reshape(-1, 3)
    within = points[cone.inside(points, 1e-3)]
    if len(within) and not np.all(Truth({}, (*part.steps, *part.late)).inside(within)):
        raise DoesNotFitError(f"{f.id}'s foot would fill what is cut into {cone.key[0]}")


def _foot_in_ball(f: Feature, solid: Prism, ball: _Ball, part: _Part) -> None:
    """What of a standing item's foot lies within its ball's surface lies in the part made so far (as a rod's:
    :func:`_foot_in_material`): its foot fills no hole drilled into the ball there."""
    centre, first, second, n = (_v(x) for x in (solid.centre, solid.first, solid.second, solid.normal))
    h1, h2 = solid.half
    a, b = np.meshgrid(np.linspace(-h1, h1, 15), np.linspace(-h2, h2, 15), indexing="ij")
    if solid.corner >= min(h1, h2):  # a boss: a disc
        keep = a * a + b * b <= solid.corner * solid.corner
        a, b = a[keep], b[keep]
    across = centre + a.reshape(-1, 1) * first + b.reshape(-1, 1) * second
    depth = np.linspace(solid.low, 0.0, 8)
    points = (across[:, None, :] + depth[None, :, None] * n).reshape(-1, 3)
    d = points - ball.centre
    within = points[fv.dot(d, d) < fv.sq(ball.radius - 1e-3)]
    if len(within) and not np.all(Truth({}, (*part.steps, *part.late)).inside(within)):
        raise DoesNotFitError(f"{f.id}'s foot would fill what is cut into {ball.key[0]}")


def _foot_in_material(
    f: Feature, solid: Prism, side: _Round, w: Array, part: _Part
) -> None:
    """What of a standing item's foot lies within its rod's surface lies in the part made so far (generated part 2115: a post's foot, carried into a tube's wall under the side's curve, over a hole drilled along the wall from its end, would have filled the hole's air).

    Asked at points through the foot, a hair within the surface.
    """
    centre, first, second, n = (
        _v(x) for x in (solid.centre, solid.first, solid.second, solid.normal)
    )
    h1, h2 = solid.half
    a, b = np.meshgrid(
        np.linspace(-h1, h1, 15), np.linspace(-h2, h2, 15), indexing="ij"
    )
    if solid.corner >= min(h1, h2):  # a boss: a disc
        keep = a * a + b * b <= solid.corner * solid.corner
        a, b = a[keep], b[keep]
    across = centre + a.reshape(-1, 1) * first + b.reshape(-1, 1) * second
    depth = np.linspace(solid.low, 0.0, 8)
    points = (across[:, None, :] + depth[None, :, None] * n).reshape(-1, 3)
    d = points - side.start
    off = d - np.outer(fv.matmul(d, w), w)
    within = points[fv.dot(off, off) < fv.sq(side.radius - 1e-3)]
    if len(within) and not np.all(Truth({}, (*part.steps, *part.late)).inside(within)):
        raise DoesNotFitError(
            f"{f.id}'s foot would fill what is cut into {side.key[0]}"
        )


def _ball(f: Feature) -> Outline2:
    """A sphere's half outline about its axis, from its point (sphere.md): a whole ball's, its centre at the point; a dome's, its flat face there.

    A dome standing on a face runs on a hair into it (``REACH``) as the
    ball it is part of, so its rim is no circle in the face's plane; a whole
    ball's arc is drawn in two, split a little below its equator, so a
    polygon of either arc has no corner on the face it stands on.
    """
    r = f.sizes["diameter"] / 2
    if f.choices["portion"] == "whole":
        split = (r * fs.cos(0.3), -r * fs.sin(0.3))
        return Outline2(
            (0.0, -r),
            (
                (split, (0.0, 0.0), False),
                ((0.0, r), (0.0, 0.0), False),
                ((0.0, -r), None, False),
            ),
        )
    if f.on is None:
        return Outline2(
            (0.0, 0.0),
            (
                ((r, 0.0), None, False),
                ((0.0, r), (0.0, 0.0), False),
                ((0.0, 0.0), None, False),
            ),
        )
    foot = (math.sqrt(r * r - REACH * REACH), -REACH)
    return Outline2(
        (0.0, -REACH),
        (
            (foot, None, False),
            ((0.0, r), (0.0, 0.0), False),
            ((0.0, -REACH), None, False),
        ),
    )


def _standing_cone(
    f: Feature,
    index: int,
    base: Array,
    n: Array,
    face: _Flat,
    part: _Part,
    under: float,
) -> None:
    """A cone standing on a face (cone.md): its -end centred on its point, its radius changing straight from its base's to its top's as it rises its length; its top a disc (none where it comes to a point), over its length and the face's ``under`` material. Its foot runs on into the face."""
    s = f.sizes
    rb, rt, length = s["base_diameter"] / 2, s["top_diameter"] / 2, s["length"]
    part.steps.append(
        Step(
            f.id, index, True, Frustum(_t(base), _t(n), (rb, rt), length), (REACH, 0.0)
        )
    )
    if rt > 0:
        far = (f.id, index, "+end")
        part.flats[far] = _Flat(far, base + length * n, n.copy(), _flat_axes(_named(n)), "disc", (rt, rt),
                                length + under, face.exit, flare=(rb, length) if rt > rb else (0.0, 0.0))  # fmt: skip
    way = _named(n)
    if not face.turned and abs(float(n["xyz".index(way[1])])) == 1.0:  # its side takes things (item 3b's third step)
        key = (f.id, index, "side")
        forward = way[0] == "+"
        part.cones[key] = _Cone(key, way[1], base.copy() if forward else base + length * n, length,
                                rb if forward else rt, rt if forward else rb)  # fmt: skip


def _standing_profile(
    f: Feature,
    index: int,
    base: Array,
    n: Array,
    face: _Flat,
    part: _Part,
    under: float,
) -> None:
    """An extrusion or a revolution standing on a face (extrusion.md, revolution.md), its foot run on a hair into it.

    An extrusion: its outline along the face's axes from its point, pushed
    out of the face its length; its +end that outline, over its length and
    the face's ``under`` material. A revolution: its half outline turned
    about the line out of the face through its point; its +end, where it has
    one, a disc or a ring over the least material under it in the
    revolution, and the face's too where every line down through it runs
    right through to the face.
    """
    _draw(f.kind).standing_profile(f, index, base, n, face, part, under)


def _moved(outline: Outline2, du: float, dv: float) -> Outline2:
    """An outline moved ``du`` along its first coordinate and ``dv`` along its second."""

    def at(q: tuple[float, float]) -> tuple[float, float]:
        return (q[0] + du, q[1] + dv)

    return Outline2(
        at(outline.start),
        tuple(
            (at(to), None if centre is None else at(centre), clockwise)
            for to, centre, clockwise in outline.sides
        ),
    )


def _sunk(outline: Outline2, by: float) -> Outline2:
    """A half outline that meets the face it stands on (its height 0) run ``by`` on into it: each of its points at height 0 moved that far down (the straight sides there; no arc ends there)."""

    def at(q: tuple[float, float]) -> tuple[float, float]:
        return (q[0], -by) if abs(q[1]) < 1e-12 else q

    sides = []
    before = outline.start
    for to, centre, clockwise in outline.sides:
        if centre is not None and (abs(before[1]) < 1e-12 or abs(to[1]) < 1e-12):
            raise DoesNotFitError(
                "an arc of a standing revolution's outline ends on the face it stands on"
            )
        sides.append((at(to), centre, clockwise))
        before = to
    return Outline2(at(outline.start), tuple(sides))


def _standing_tube(
    f: Feature, index: int, base: Array, n: Array, face: _Flat, part: _Part
) -> None:
    """A tube standing on a face (tube.md): every point between its bore's radius and its outside's from its axis, from the face out to its length; its bore open down to the face. Its foot runs on into the face; its far end is a ring, its side round with a wall a cut through goes through."""
    s = f.sizes
    r, inner, length = s["outer_diameter"] / 2, s["inner_diameter"] / 2, s["length"]
    corners = ((r, -REACH), (r, length), (inner, length), (inner, -REACH))
    ring = Outline2((inner, -REACH), tuple((c, None, False) for c in corners))
    part.steps.append(Step(f.id, index, True, Turned(_t(base), _t(n), ring)))
    up = _named(n)
    far = (f.id, index, "+end")
    part.flats[far] = _Flat(far, base + length * n, n.copy(), _flat_axes(up), "ring", (r, r), length, None,
                            inner=inner)  # fmt: skip
    # The side runs along its frame axis from its end with the lesser coordinate (it may grow either way along it).
    start = base.copy() if up[0] == "+" else base + length * n
    part.rounds[(f.id, index, "side")] = _Round(
        (f.id, index, "side"), up[1], start, length, r, bore=inner
    )


def _round_tab(
    f: Feature,
    index: int,
    base: Array,
    n: Array,
    face: _Flat,
    part: _Part,
    turned: tuple[Array, Array] | None = None,
) -> None:
    """A round-ended tab (tab.md): seen along its thickness a rectangle ``length`` out from the face, its far corners rounded to half its width; its broad faces with that outline, its narrow sides as far as its rounding starts, no far face.

    Its solid runs on into the face it stands on (``REACH``), so its foot is
    no plane of the face's.
    """
    s = f.sizes
    thin = f.choices["thickness_along"]
    other = face.axes[1] if thin == face.axes[0] else face.axes[0]
    t, w, length = s["thickness"], s["width"], s["length"]
    r = w / 2
    if length < r:
        raise DoesNotFitError(
            f"{f.id}: a round-ended tab sticks out at least half its width"
        )
    up = _named(n)
    e_thin, e_other = _v(unit_of("+" + thin)), _v(unit_of("+" + other))
    if turned is not None:  # turned in its face's plane: its own axes, the face's turned (1b's first move)
        e1, e2 = turned
        e_thin, e_other = (e1, e2) if thin == face.axes[0] else (e2, e1)
    centre = base + (length - REACH) / 2 * n
    part.steps.append(Step(f.id, index, True, Prism(_t(centre), _t(n), _t(e_other), _t(e_thin), ((length + REACH) / 2, r),
                                                    r, -t / 2, t / 2, (True, False, False, True))))  # fmt: skip
    if turned is not None:
        return  # its faces take nothing yet (a later move): none is kept
    size = {thin: t, other: w, up[1]: length}
    for sign in (1.0, -1.0):
        name = ("+" if sign > 0 else "-") + thin
        axes = _flat_axes(name)
        k = axes.index(up[1])
        way = 1 if up[0] == "+" else -1
        corners = tuple(r if q[k] == way else 0.0 for q in QUADRANTS)
        part.flats[(f.id, index, name)] = _Flat(
            (f.id, index, name), base + length / 2 * n + sign * t / 2 * e_thin, sign * e_thin, axes, "rect",
            (size[axes[0]] / 2, size[axes[1]] / 2), t, (f.id, index, ("-" if sign > 0 else "+") + thin),
            corners=(corners[0], corners[1], corners[2], corners[3]))  # fmt: skip
    straight = length - r
    if straight <= 0:
        return  # all half-disc: no narrow side
    for sign in (1.0, -1.0):
        name = ("+" if sign > 0 else "-") + other
        axes = _flat_axes(name)
        half = tuple(straight / 2 if a == up[1] else t / 2 for a in axes)
        part.flats[(f.id, index, name)] = _Flat(
            (f.id, index, name), base + straight / 2 * n + sign * r * e_other, sign * e_other, axes, "rect",
            (half[0], half[1]), w, (f.id, index, ("-" if sign > 0 else "+") + other))  # fmt: skip


def _holes_apart(
    one: tuple[float, float, float, float | None],
    other: tuple[float, float, float, float | None],
    radius: float,
) -> bool:
    """Whether two holes round a rod (along, angle, radius, depth or through) stay apart: their mouths (a hole through has two) and, blind, their insides; holes through may meet only at the axis (place.md)."""
    (s1, a1, r1, d1), (s2, a2, r2, d2) = one, other
    reach = r1 + r2 + GAP
    if abs(s1 - s2) >= reach:
        return True

    def chord(x: float, y: float) -> float:
        return 2 * radius * abs(fs.sin(math.radians((x - y) / 2)))

    mouths1 = [a1] if d1 is not None else [a1, a1 + 180.0]
    mouths2 = [a2] if d2 is not None else [a2, a2 + 180.0]
    if any(chord(x, y) < reach for x in mouths1 for y in mouths2):
        return False
    turn = math.radians(abs(a1 - a2) % 360.0)
    if d1 is not None and d2 is not None:
        inner = max(radius - d1, radius - d2)
        return (
            2 * inner * abs(fs.sin(turn / 2)) >= reach or abs(fs.cos(turn / 2)) < 1e-9
        )
    if (
        d1 is not None or d2 is not None
    ):  # a blind one beside one through: its end from the other's line
        depth = d1 if d1 is not None else d2
        assert depth is not None
        return (radius - depth) * abs(fs.sin(turn)) >= reach
    return True


# ----------------------------------------------------------------------
# The brief, and the draft citing it (docs/V2-stage4.md, 12.1)
# ----------------------------------------------------------------------
#: What the brief calls the items after their kind ("Hole Alpha"; the first body is "the body"), in plan
#: order: words that are no number, unit, axis or option of any field.
NAMES = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Theta", "Iota", "Kappa", "Lambda", "Omicron",
         "Sigma", "Upsilon", "Omega", "Vega", "Rigel", "Altair", "Deneb", "Spica", "Castor", "Pollux", "Sirius",
         "Antares", "Mira")  # fmt: skip
#: What a size says it measures, by its field's name.
_MEASURES = {"length": "long", "width": "wide", "height": "tall", "diameter": "across", "thickness": "thick",
             "base_diameter": "across at its base", "top_diameter": "across at its top",
             "outer_diameter": "across outside", "inner_diameter": "across inside"}  # fmt: skip
#: An outline in words: its sizes are the drawing's, which the brief points to (a draft's outline cites no
#: number).
_OUTLINE_WORDS = {"L": "an L-shaped outline", "T": "a T-shaped outline", "stadium": "a stadium-shaped outline",
                  "corner": "a plate outline with a corner rounded and a corner cut back",
                  "flange": "a flange's outline", "knob": "a knob's outline", "pulley": "a pulley's outline"}  # fmt: skip
#: Each edge set in words (edges.md).
_EDGE_WORDS = {"all": "all the edges of {of}", "top": "the top edges of {of}", "bottom": "the bottom edges of {of}",
               "vertical": "the vertical edges of {of}", "both": "the edges at each end of {of}",
               "joint": "the joint where {of} meets {meets}"}  # fmt: skip
#: Marks that would end a quotation, or a sentence, inside letters the brief quotes.
_UNQUOTABLE = frozenset("\"'\u201c\u201d\u2018\u2019\u00ab\u00bb`.!?;")
#: Where a line of letters no quotation can hold comes from.
_DRAWN = {"assumed": "the letters as drawn with the brief"}


def _names(plan: Plan) -> dict[str, str]:
    """What the brief calls each item: the first body "the body", any other its kind and a name of its own."""
    names: dict[str, str] = {}
    for f in plan:
        if f.id == "body":
            names[f.id] = "the body"
            continue
        k = sum(1 for g in names if g != "body")
        own = NAMES[k % len(NAMES)]
        if k >= len(NAMES):
            own = f"{NAMES[k // len(NAMES) - 1]} {own}"
        names[f.id] = f"{f.kind.capitalize()} {own}"
    return names


def _mm(w: Writer, v: float, *, before: str = "", after: str = "", unit: str = "mm") -> dict[str, Any]:  # fmt: skip
    """A value, said as ``before``, its number and its unit, then ``after``: those words cited."""
    word = "degrees" if unit == "deg" else unit
    said = w.cite(f"{before}{number(v)} {word}{after}")
    return {"value": v, "unit": unit, "from": {"words": said}}


def _counted(w: Writer, n: int, after: str = "") -> dict[str, Any]:
    return {"count": n, "from": {"words": w.cite(f"{n}{after}")}}


def _chosen(w: Writer, option: str, words: str) -> dict[str, Any]:
    return {"choose": option, "from": {"words": w.cite(words)}}


def _quotable(text: str) -> bool:
    """Whether letters can be quoted in the brief: no mark in them ends the quotation or the sentence, and some are letters or figures, which make words."""
    return not _UNQUOTABLE & set(text) and any(ch.isalnum() for ch in text)


def _draft(f: Feature, w: Writer, names: Mapping[str, str]) -> dict[str, Any]:
    """The item as the draft writes it, and its sentence of the brief: every value cites the words that say it, the rest of the sentence is the item's own."""
    return _brief(f.kind).draft(f, w, names)


def _rounding_said(f: Feature, w: Writer, names: Mapping[str, str], found: dict[str, Any]) -> None:  # fmt: skip
    _brief(f.kind).rounding_said(f, w, names, found)


def _words_value(words: str, said: object) -> dict[str, object]:
    """A text value as the draft writes it: its words, and where the brief says them (or that they were drawn)."""
    return {"text": words, "from": said}


def _item_said(f: Feature, w: Writer, names: Mapping[str, str], found: dict[str, Any]) -> None:  # fmt: skip
    """A body, an item standing on a face or a cut into one: what it is and its sizes, then its choices, where it stands, where it is on its face and its copies."""
    s, kind = f.sizes, f.kind
    own = _brief(kind)
    profile = None
    if f.outline is not None:
        profile = {"words": Mark()}
        found["profile"] = _outline_draft(f, profile)
    w.say(own.article)
    for choice, words in own.option_words.items():
        option = f.choices[choice]
        found[choice] = _chosen(w, option, words[option])
        w.say(" ")
    if own.names_itself:
        w.say(kind + " ")
    own.words_said(f, w, found)
    said = own.sizes_said(f)
    said = [entry for entry in said if entry[0] != "corner_radius"]
    if own.cut_out and f.depth is not None:
        said.append(("depth", f.depth, "", " deep"))
    for k, (size, v, before, after) in enumerate(said):
        w.say("" if not k else " and " if k == len(said) - 1 else ", ")
        found[size] = _mm(w, v, before=before, after=after)
    if own.cut_out and f.depth is None:
        w.say(", ")
        found["depth"] = {"through": True, "from": {"words": w.cite("right through")}}
    if "corner_radius" in s:
        w.say(", ")
        found["corner_radius"] = _mm(w, s["corner_radius"], before="its corners rounded to ")  # fmt: skip
    if profile is not None:
        w.say(" of " if s else "")
        assert f.outline is not None
        w.cite(
            _OUTLINE_WORDS[f.outline[0]] + " drawn with this brief", profile["words"]
        )
    if f.recess is not None:
        what, d, third = f.recess
        w.say(f", with a {what} ")
        recess = {"diameter": _mm(w, d, after=" across")}
        if what == "counterbore":
            w.say(" and ")
            recess["depth"] = _mm(w, third, after=" deep")
        else:
            w.say(" at ")
            recess["angle"] = _mm(w, third, unit="deg")
        found[what] = recess
    for choice, option in f.choices.items():
        if choice in own.option_words:
            continue
        w.say(", ")
        if choice in ("along", "thickness_along"):
            option = _spelled(f, option)
        phrase = {"along": f"along {option}", "thickness_along": f"its thickness along {option}",
                  "ends": f"with {option} ends", "end": f"with a {option} end"}[choice]  # fmt: skip
        found[choice] = _chosen(w, option, phrase)
    if f.on is not None:
        host, face = f.on
        found["on"] = {"item": host, "face": face}
        w.say(f", on the {face}{'' if face in ('side', 'surface') else ' face'} of {names[host]}")
        if f.tilt is not None:
            tilt, towards = f.tilt
            w.say(", ")
            found["tilt"] = _mm(w, tilt, before="leaning ", unit="deg")
            w.say(" ")
            towards = towards[0] + _spelled(f, towards[1])
            found["tilt_towards"] = _chosen(w, towards, f"towards {towards}")
    elif own.axial:
        # The generator's first body stands upright.
        w.say(", ")
        found["axis"] = _chosen(w, "z", "its axis along z")
    place = _place_said(f, w)
    if place:
        found["place"] = place


def _pattern_brief(mode: str) -> PatternBrief:
    """The pattern mode's entry in the ``brief`` role's modes, asked when writing (as :func:`_brief`)."""
    from .items.brief.pattern import PATTERN_BRIEF

    return PATTERN_BRIEF[mode]


def _place_said(f: Feature, w: Writer) -> dict[str, Any]:
    """Where on its face an item is, along each axis the plan says and round a side, and its copies."""
    place: dict[str, Any] = {}
    for named, pos in f.place.items():
        if pos.mode == "none":
            continue  # left unsaid: the solver assumes it centred, as a person's would be
        axis = _spelled(f, named)
        if pos.side:
            pos = replace(pos, side=pos.side[0] + _spelled(f, pos.side[1:]))
        w.say(", ")
        if pos.mode == "centred":
            place[axis] = {"centred": {"words": w.cite(f"centred along {axis}")}}
        elif pos.mode == "offset":
            place[axis] = {"offset": _mm(w, pos.distance, before="offset ", after=f" along {axis}")}  # fmt: skip
        else:
            distance = _mm(w, pos.distance, before=f"its {pos.to} ", after=f" from the {pos.side} edge")  # fmt: skip
            place[axis] = {"side": pos.side, "distance": distance, "to": pos.to}
    if f.latitude is not None:  # on a ball's surface (item 3b's second step)
        w.say(", ")
        place["latitude"] = _mm(w, f.latitude, before="at latitude ", unit="deg")
        if f.angle is not None:
            w.say(", ")
            place["angle"] = _mm(w, f.angle, after=" round its pole", unit="deg")
    elif f.angle is not None:
        w.say(", ")
        place["angle"] = _mm(w, f.angle, before="at ", after=" round the side", unit="deg")  # fmt: skip
    if f.turn is not None:
        w.say(", ")
        place["turn"] = _mm(w, f.turn, before="turned ", after=" in its face", unit="deg")
    p = f.pattern
    if p is None:
        return place
    body: dict[str, Any] = {}
    w.say(", ")
    if f.own_axes is not None:  # its values along the face's axes, and its axis, by the face's own names
        names = {f.own_axes[0]: "u", f.own_axes[1]: "v"}

        def spelled(name: str) -> str:
            before, _, last = name.rpartition("_")
            return name if last not in names else (before + "_" if before else "") + names[last]

        p = replace(p, values={spelled(k): v for k, v in p.values.items()},
                    counts={spelled(k): c for k, c in p.counts.items()}, axis=names.get(p.axis, p.axis))  # fmt: skip
    _pattern_brief(p.kind).said(p, w, body)
    place["pattern"] = {p.kind: body}
    return place


def _spelled(f: Feature, axis: str) -> str:
    """An axis of an item's face as its draft names it: by the face's own, ``u`` and ``v``, where it names them so."""
    if f.own_axes is None or axis not in f.own_axes:
        return axis
    return "u" if axis == f.own_axes[0] else "v"


def _sizes_hold(f: Feature) -> None:
    """The definitions' own limits on an item's sizes (each kind's page): a :class:`DoesNotFitError` where one is broken."""
    s = f.sizes
    entry = _draw(f.kind)
    sizes = {name: v for name, v in s.items() if name not in entry.may_be_zero}
    if any(not v > 0 for v in sizes.values()) or (
        f.depth is not None and not f.depth > 0
    ):
        raise DoesNotFitError(f"{f.id}: every size is more than 0")
    entry.limits(f)
    if f.outline is not None:
        outline_of(f.outline[0], dict(f.outline[1]))
    if f.recess is not None:
        what, d, third = f.recess
        if not (d > s["diameter"] and third > 0):
            raise DoesNotFitError(f"{f.id}: a {what} is wider than its hole")
        # GAP past it, as the generator makes them (a value on the 0.001 grid may round below).
        if f.depth is not None and f.depth < _recess_depth(f) + GAP - 0.001:
            raise DoesNotFitError(f"{f.id}: a blind hole goes on past its {what}")


def _recess_depth(f: Feature) -> float:
    """How deep a hole's counterbore or countersink goes (none: 0)."""
    if f.recess is None:
        return 0.0
    what, d, third = f.recess
    if what == "counterbore":
        return third
    return (d - f.sizes["diameter"]) / 2 / fs.tan(math.radians(third / 2))


def _build(plan: Plan, strict: bool) -> _Part:
    part = _Part()
    for f in plan:
        part.kinds[f.id] = f.kind
        _sizes_hold(f)
        made = (len(part.steps), len(part.late))
        threads = list(part.threads)
        _build_one(f, plan, part, strict)
        if strict:
            new = (*part.steps[made[0] :], *part.late[made[1] :])
            _threads_whole(f, threads, new, part)
        # A shell's hollow is made to follow its body's roundings (_shell); everything else keeps clear of them.
        if strict and not _draw(f.kind).follows_roundings:
            chain = _chain(f, plan)
            for step in (*part.steps[made[0] :], *part.late[made[1] :]):
                lo, hi = bounds(step.solid)
                for who, a, b, root in part.kept:
                    if root not in chain and np.all(lo <= b) and np.all(a <= hi):
                        raise DoesNotFitError(f"{f.id} reaches into {who}")
    return part


def _threads_whole(
    f: Feature, threads: list[tuple[str, Array]], new: Sequence[Step], part: _Part
) -> None:
    """Every thread made before ``f`` still has its rod's material whole round it (``part.threads``), where what ``f`` made reaches (generated part 1574: a letter engraved in a stud's end, after its thread)."""
    for thread, points in threads:
        reached = False
        for step in new:
            lo, hi = bounds(step.solid)
            reached |= bool(np.any(np.all((points >= lo) & (points <= hi), axis=1)))
        if not reached:
            continue
        every = (*part.steps, *part.late)
        rest = tuple(s for s in every if not isinstance(s.solid, Threaded))
        if not np.all(Truth({}, rest).inside(points)):
            raise DoesNotFitError(f"{f.id} is cut where {thread} is")


def _chain(f: Feature, plan: Plan) -> set[str]:
    """An item and what it stands on, is cut into or changes, and so on down to the first body."""
    found = {f.id}
    below: Feature | None = f
    while below is not None and (below.on is not None or below.of is not None):
        name = below.on[0] if below.on is not None else below.of
        below = next((g for g in plan if g.id == name), None)
        if below is not None:
            found.add(below.id)
    return found


def _build_one(f: Feature, plan: Plan, part: _Part, strict: bool) -> None:
    """One item of a plan: its copies, its solids and the faces it makes or changes."""
    _draw(f.kind).build_one(f, plan, part, strict)


#: Each face a shell may leave open, and its opposite (shell.md).
OPPOSITE = {
    "+x": "-x",
    "-x": "+x",
    "+y": "-y",
    "-y": "+y",
    "+z": "-z",
    "-z": "+z",
    "+end": "-end",
    "-end": "+end",
}


def _shell(f: Feature, plan: Plan, part: _Part) -> None:
    """A shell of the first body, or of a block standing on a face (shell.md; step 5.1): its hollow taken away just after it is made, before anything stands on it or cuts into it.

    Each closed face's wall is ``thickness`` thick, the floor (the wall
    opposite an open face) ``floor`` when given; the material under each
    closed face, and under each inside face of a block's or a cylinder's
    walls, is its wall, and a cut through it comes out into the hollow (on the
    inside face, which must take all of it). A face left open takes nothing.
    A cylinder's side becomes a tube's: a hole through it goes through its
    wall. A dome's flat face is its floor all across.
    """
    body = next((g for g in plan if g.id == f.of), None)
    standing = body is not None and body.on is not None  # a block standing on a face (step 5.1)
    if (
        body is None
        or not _draw(body.kind).openable
        or not _draw(body.kind).may_hollow(body)
    ):
        raise DoesNotFitError(
            f"{f.id}: the generator hollows its first body: a block, a cylinder or a dome"
        )
    t = f.sizes["thickness"]
    opened = set(f.faces or ())
    if not opened <= set(_draw(body.kind).openable):
        raise DoesNotFitError(
            f"{f.id}: a {body.kind} may leave open {_draw(body.kind).openable}, not {sorted(opened)}"
        )
    floored = _draw(body.kind).floored(opened)
    if "floor" in f.sizes and not floored:
        raise DoesNotFitError(f"{f.id}: a floor is the wall opposite an opening")
    floor = f.sizes.get("floor", t)

    def wall(name: str) -> float:
        return 0.0 if name in opened else floor if OPPOSITE[name] in opened else t

    if standing:
        _draw(body.kind).hollow_standing(f, body, plan, part, t, floor, opened, wall)
        return
    _draw(body.kind).hollow(f, body, plan, part, t, floor, opened, wall)


def _hollow_cylinder(f: Feature, body: Feature, part: _Part, t: float, wall: Callable[[str], float],
                     opened: set[str]) -> None:  # fmt: skip
    """A cylinder's hollow (shell.md): a cylinder ``t`` less in radius, its ends in by their walls; its ends' inside faces discs."""
    r, length = body.sizes["diameter"] / 2, body.sizes["length"]
    top, bottom = wall("+end"), wall("-end")
    inside = r - t
    if inside < 2 * GAP + 1.0 or length - top - bottom < 2 * GAP + 1.0:
        raise DoesNotFitError(f"{f.id}'s walls leave too little hollow in {body.id}")
    z = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    part.steps.append(Step(f.id, 0, False, Prism(*z, (inside, inside), inside, bottom, length - top),
                           (REACH if "-end" in opened else 0.0, REACH if "+end" in opened else 0.0)))  # fmt: skip
    key = (body.id, 0)
    for name, height, depth in (("+end", length - top, top), ("-end", bottom, bottom)):
        outer = (body.id, 0, name)
        if name in opened:
            del part.flats[outer]
            continue
        inner = (body.id, 0, f"inner {name}")
        face = part.flats[outer]
        face.material, face.exit = depth, inner
        room = math.inf if OPPOSITE[name] in opened else length - top - bottom
        part.flats[inner] = _Flat(inner, _v((0.0, 0.0, height)), -face.normal, ("x", "y"), "disc", (inside, inside),
                                  depth, outer, room=room, hollow=key)  # fmt: skip
    side = part.rounds[(body.id, 0, "side")]
    side.bore = inside
    side.bored = (
        -math.inf if "-end" in opened else bottom,
        math.inf if "+end" in opened else length - top,
    )


def _hollow_dome(
    f: Feature, body: Feature, part: _Part, t: float, floor: float, opened: bool
) -> None:
    """A dome's hollow (shell.md): within ``t`` less than its radius of its flat face's centre, above its floor (from its flat face when that is open, carried on out through it)."""
    r = body.sizes["diameter"] / 2
    inside = r - t
    base = -REACH if opened else floor
    if inside - max(base, 0.0) < 2 * GAP + 1.0:
        raise DoesNotFitError(f"{f.id}'s walls leave too little hollow in {body.id}")
    rim = (math.sqrt(inside * inside - base * base), base)
    hollow = Outline2(
        (0.0, base),
        (
            (rim, None, False),
            ((0.0, inside), (0.0, 0.0), False),
            ((0.0, base), None, False),
        ),
    )
    part.steps.append(
        Step(f.id, 0, False, Turned((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), hollow))
    )
    flat = (body.id, 0, "-end")
    if opened:
        del part.flats[flat]
        return
    part.flats[flat].material, part.flats[flat].dome = (
        floor,
        0.0,
    )  # its floor all across (shell.md)


# ----------------------------------------------------------------------
# Roundings and chamfers (fillet.md, chamfer.md, edges.md)
# ----------------------------------------------------------------------
#: A rounded corner holds all a bevel of a corner takes when its radius is this many times the bevel's legs
#: (1 + 1/sqrt 2, and room).
_BEVEL = 1.75
#: How far a zone where roundings meet reaches from the corner: this many times the roundings' size, and
#: :data:`_ZONE` more (a mesh of the part may leave the corner a little past the size unrounded).
_CORNER = 1.25
_ZONE = 0.1


def _rounding(f: Feature, plan: Plan, part: _Part, strict: bool) -> None:
    """A rounding or a bevel of an item's edge set, on every copy of it (fillet.md, chamfer.md).

    Its pieces are made last, in the plan's order (frame.md): exact along a
    straight edge between faces at right angles (:class:`Corner`) and round
    a rim (:class:`RingCorner`); where two rounded straight edges meet at a
    corner the definitions bound the shape rather than give it, and the
    truth leaves a zone there. From then on the faces it takes keep the
    rest clear of it: a rounded edge's face keeps things further in, a
    rounded joint, mouth or rim takes up room round what it rounds.
    """
    target = next((g for g in plan if g.id == f.of), None)
    which = f.choices["which"]
    if target is None or which not in _draw(target.kind).roundable(target.on is None):
        raise DoesNotFitError(
            f"{f.id}: the generator doesn't round {which!r} edges of {f.of}"
        )
    if _draw(target.kind).round_rim and (
        target.recess is not None or target.on is None or target.on[1] == "side"
    ):
        raise DoesNotFitError(
            f"{f.id}: the generator rounds a plain cut's rim on a flat face"
        )
    for shell in (g for g in plan if _draw(g.kind).hollows and g.of == target.id):
        # A hollowed body's own vertical edges, rounded or bevelled before its hollow, whose walls follow them
        # (frame.md); nothing else of a body it hollows, for now.
        if which != "vertical" or set(shell.faces or ()) - {"+z", "-z"}:
            raise DoesNotFitError(
                f"{f.id}: the generator rounds only the vertical edges of a body it hollows"
            )
    size = f.sizes[_draw(f.kind).rounding_size]
    made = len(part.late)
    for copy in part.copies.get(target.id, []):
        host = part.flats.get(copy.host) if copy.host is not None else None
        if copy.host is not None and (host is None or host.hollow is not None):
            raise DoesNotFitError(
                f"{f.id}: the generator rounds only what stands on, or is cut in, a flat face out of any hollow"
            )
        _draw(target.kind).rounded(
            f, target, copy, which, size, part, host, strict, plan
        )
    _draw(target.kind).after_rounding(f, target, part, made, strict)
    # What it rounds stays clear of everything else made, before it and after: what it rounds, and what that
    # stands on or is cut into, and so on down to the first body, apart.
    own = {target.id, *(g.id for g in plan if _draw(g.kind).hollows and g.of == target.id),
           *(g.id for g in plan[: plan.index(f)] if _draw(g.kind).rounds_edges and g.of == target.id)}  # fmt: skip
    below = target
    while below.on is not None:
        below = next(g for g in plan if g.id == below.on[0])
        own.add(below.id)
    for step in part.late[made:]:
        lo, hi = bounds(step.solid)
        lo, hi = lo - GAP / 2, hi + GAP / 2
        if strict:
            for other in (*part.steps, *part.late[:made]):
                if other.item in own:
                    continue
                a, b = bounds(other.solid)
                if np.all(lo <= b) and np.all(a <= hi):
                    raise DoesNotFitError(f"{f.id} rounds an edge {other.item} reaches")
        part.kept.append((f"{f.id}'s rounding", lo, hi, None))


#: How far past a rounded box edge, outside both its faces, the part made so far is asked whether it is there (mm).
_COVER = 1e-3
#: At how many places along the edge.
_COVER_STATIONS = 21


def _drop_covered(
    f: Feature, target: Feature, part: _Part, made: int, strict: bool
) -> None:
    """Of the edges just rounded on a box (``part.late`` from ``made``), those the part made so far lies against: no edge of the part there, and nothing rounded.

    The definition rounds an item's edges on the part made so far (fillet.md),
    and an edge with something lying flush against it, outside both its
    faces, is no edge of the part: a post lying along a cylinder's end, its
    two lower edges on the end (generated part 9906). Asked just outside the
    edge, past both its faces, at places all along it. Where something lies
    against only part of an edge, the rounding ends where it does, which the
    truth doesn't follow: a strict plan draws something else.
    """
    so_far = Truth({}, tuple(part.steps))
    at = (np.arange(_COVER_STATIONS) + 0.5) / _COVER_STATIONS
    kept: list[Step] = []
    for step in part.late[made:]:
        piece = step.solid
        if step.add or not isinstance(piece, Corner):
            kept.append(step)
            continue
        start, along, a, b = (
            np.asarray(v, dtype=float)
            for v in (piece.start, piece.along, piece.a, piece.b)
        )
        out = -(a + b) / fv.norm(a + b)
        covered = so_far.inside(
            start + np.outer(at * piece.length, along) + _COVER * out
        )
        if covered.all():
            continue
        if covered.any() and strict:
            raise DoesNotFitError(
                f"{f.id}: something lies against part of an edge of {target.id} it rounds"
            )
        kept.append(step)
    part.late[made:] = kept


def _corner_zone(part: _Part, at: Array, size: float, more: float = 0.0) -> None:
    """A zone round a corner where roundings meet: a cube a little more than ``size`` (and ``more``) each way."""
    reach = _CORNER * size + more + _ZONE
    part.zones.append((_t(at - reach), _t(at + reach)))


def _keep_clear(f: Feature, face: _Flat, old: _Foot, new: _Foot, strict: bool) -> None:
    """What a rounding fills or takes round something on a face: its footprint grown, on the face and clear of the rest there."""
    if strict:
        others = [foot for foot in face.taken if foot != old]
        if not face.holds(new) or any(not new.clear_of(other, GAP) for other in others):
            raise DoesNotFitError(
                f"{f.id} runs into something else on {face.key}, or off it"
            )
    face.taken[face.taken.index(old)] = new


def _margin(face: _Flat, axis: str, sign: float, by: float) -> None:
    """A rectangle's side along ``axis`` (its ``sign`` end) taken ``by`` further in."""
    if axis not in face.axes:
        return
    k = 2 * face.axes.index(axis) + (1 if sign > 0 else 0)
    margin = list(face.margin)
    margin[k] = max(margin[k], by)
    face.margin = (margin[0], margin[1], margin[2], margin[3])


def _earlier_vertical(f: Feature, target: Feature, plan: Plan) -> float:
    """The radius a box's vertical edges are rounded by before ``f`` (0: they are sharp); a :class:`DoesNotFitError` where an earlier rounding of the box already has edges ``f`` rounds, or bevels its vertical edges and ``f`` would round those it joins."""
    which = f.choices["which"]
    edges = {"all": {"vertical", "top", "bottom"}}
    mine = edges.get(which, {which})
    radius = 0.0
    for g in plan[: plan.index(f)]:
        if not _draw(g.kind).rounds_edges or g.of != target.id:
            continue
        theirs = edges.get(g.choices["which"], {g.choices["which"]})
        if theirs & mine:
            raise DoesNotFitError(
                f"{f.id}: {g.id} rounds those edges of {target.id} already"
            )
        if "vertical" in theirs:
            if _draw(g.kind).bevels:
                raise DoesNotFitError(
                    f"{f.id}: the generator rounds what meets bevelled edges only where they meet no corner"
                )
            radius = g.sizes["radius"]
    return radius


def _round_box(f: Feature, target: Feature, copy: Copy, which: str, size: float, part: _Part,
               host: _Flat | None, strict: bool, rounded: float = 0.0) -> None:  # fmt: skip
    """A box's edges (block.md, post.md): ``vertical`` along its up, ``top`` round its far face, ``bottom`` round its base (a first body's), ``all`` (a first body's twelve), ``joint`` the inside corner round its foot.

    Where its vertical edges are rounded already (``rounded``, the radius),
    the top's, the bottom's or the joint's edges follow the face's edge as
    that rounding left it (edges.md): straight runs, and round each corner a
    quarter of a ring about the corner's rounding's axis, smaller than it:
    all exact, the runs and the rings running on into each other.
    """
    round_ = not _draw(f.kind).bevels
    if rounded and strict and size > rounded - 0.2:
        raise DoesNotFitError(
            f"{f.id}: rounding round {target.id}'s rounded corners, smaller than they are"
        )
    p, n = _v(copy.point), _v(copy.direction)
    axes = copy.axes or ("x", "y")
    e1, e2 = (_v(unit_of("+" + a)) for a in axes)
    if host is not None:  # its own ways, turned with it where it is turned (edges.md, "A turned item's edges")
        e1, e2 = _turned_frame(target, host.frame.u, host.frame.v)
    starts: dict[tuple[float, float], float] = {}
    if copy.lean is not None:  # leaning (step 5.3): its ways leaned with it, its long edges from the face's plane
        if which not in ("top", "vertical"):
            raise DoesNotFitError(f"{f.id}: a leaning box's joint isn't rounded, for now")
        u = _v(copy.lean)
        hinge = np.asarray(np.cross(n, u), dtype=np.float64)
        hinge = hinge / fs.hypot(fs.hypot(float(hinge[0]), float(hinge[1])), float(hinge[2]))
        cos_t = float(fv.matmul(n, u))
        sin_t = math.sqrt(max(1.0 - cos_t * cos_t, 0.0))

        def leaned(d: Array) -> Array:
            return d * cos_t + np.asarray(np.cross(hinge, d)) * sin_t + hinge * float(fv.matmul(hinge, d)) * (1.0 - cos_t) + 0.0

        e1, e2 = leaned(e1), leaned(e2)
        n0, n = n, u
        half_ = (target.sizes["length"] / 2, target.sizes["width"] / 2)
        for s1 in (-1.0, 1.0):
            for s2 in (-1.0, 1.0):
                off = s1 * half_[0] * e1 + s2 * half_[1] * e2
                starts[(s1, s2)] = -float(fv.matmul(n0, off)) / cos_t
    s = target.sizes
    half = (s["length"] / 2, s["width"] / 2)
    height = s["height"]
    up = _named(n)
    down = ("-" if up[0] == "+" else "+") + up[1]

    def corner(s1: float, s2: float, t: float) -> Array:
        return p + s1 * half[0] * e1 + s2 * half[1] * e2 + t * n

    def faces(name: str) -> _Flat | None:
        return part.flats.get((target.id, copy.index, name))

    sets = {"all": ("vertical", "top", "bottom")}.get(which, (which,))
    if "vertical" in sets:
        for s1 in (-1.0, 1.0):
            for s2 in (-1.0, 1.0):
                t0 = starts.get((s1, s2), 0.0)  # leaning: where it meets the face's plane
                part.late.append(Step(f.id, copy.index, False, Corner(_t(corner(s1, s2, t0)), _t(n), height - t0,
                                                                      _t(-s2 * e2), _t(-s1 * e1), size, round_),
                                      (REACH if host is None else 0.0, REACH)))  # fmt: skip
        for name in (up, down):
            face = faces(name)
            if face is not None:
                k = size if round_ else _BEVEL * size
                face.corners = (k, k, k, k)
        for k, axis in enumerate(axes):
            other = axes[1 - k]
            for sign in (-1.0, 1.0):
                face = faces(("+" if sign > 0 else "-") + axis)
                if face is not None:
                    _margin(face, other, -1.0, size)
                    _margin(face, other, 1.0, size)
    for name, t, b in (("top", height, -1.0), ("bottom", 0.0, 1.0)):
        if name not in sets:
            continue
        _run_round(
            f,
            copy.index,
            part,
            corner,
            (e1, e2, n),
            half,
            t,
            size,
            round_,
            rounded,
            False,
            b,
        )
        face = faces(up if name == "top" else down)
        if face is not None:
            face.margin = tuple(max(m, size) for m in face.margin)  # type: ignore[assignment]
        for axis in axes:
            for sign in (-1.0, 1.0):
                face = faces(("+" if sign > 0 else "-") + axis)
                if face is not None:
                    _margin(face, up[1], (1.0 if up[0] == "+" else -1.0) * (-b), size)
    if which == "joint":
        assert host is not None
        at = host.frame.plane(p)
        old = host.foot(target, (at[0], at[1]))
        if _flush(target, host) or _overhang(target, host, [old], False):
            # A side flush with the face's edge has no corner along it, and under an overhang the corner is
            # between the overhang and the host's side (edges.md): the generator doesn't round those, for now.
            raise DoesNotFitError(
                f"{f.id}: {target.id} stands flush with an edge of the face, or over it"
            )
        # Round its rounded corners as far again out; at a sharp one a rounding's joint keeps within its size of
        # the corner, a bevel's may reach the corner of the box round it.
        grown = rounded + size if rounded else size if round_ else 0.0
        new = _Foot(old.at, (old.half[0] + size, old.half[1] + size), grown)
        _keep_clear(f, host, old, new, strict)
        _run_round(
            f,
            copy.index,
            part,
            corner,
            (e1, e2, n),
            half,
            0.0,
            size,
            round_,
            rounded,
            True,
            1.0,
        )
        for axis in axes:
            for sign in (-1.0, 1.0):
                face = faces(("+" if sign > 0 else "-") + axis)
                if face is not None:
                    _margin(face, up[1], -1.0 if up[0] == "+" else 1.0, size)


def _run_round(f: Feature, index: int, part: _Part, corner: Callable[[float, float, float], Array],
               frame: tuple[Array, Array, Array], half: tuple[float, float], t: float, size: float, round_: bool,
               rounded: float, inside: bool, b: float) -> None:  # fmt: skip
    """The pieces of a rounding round a box's face ``t`` along its up (its top, its base, its foot's joint), ``b`` the way along its up into its sides from the edge.

    Its four straight runs; where the box's vertical edges are rounded by
    ``rounded``, they stop where those roundings start, and a quarter of a
    ring about each corner's axis joins them (exact, no zone); else they run
    corner to corner, carried on into the zone round each corner where they
    meet (no end of one lies in a face of the box's).
    """
    e1, e2, n = frame
    sign = (
        1.0 if inside else -1.0
    )  # from the edge along the face: out over the host, or in over the box's own
    reach = (0.0, 0.0) if rounded else (REACH, REACH)
    for s2 in (-1.0, 1.0):
        if half[0] - rounded > 1e-9:
            part.late.append(Step(f.id, index, inside, Corner(_t(corner(-1.0, s2, t) + rounded * e1), _t(e1),
                                                              2 * (half[0] - rounded), _t(sign * s2 * e2), _t(b * n),
                                                              size, round_), reach))  # fmt: skip
    for s1 in (-1.0, 1.0):
        if half[1] - rounded > 1e-9:
            part.late.append(Step(f.id, index, inside, Corner(_t(corner(s1, -1.0, t) + rounded * e2), _t(e2),
                                                              2 * (half[1] - rounded), _t(sign * s1 * e1), _t(b * n),
                                                              size, round_), reach))  # fmt: skip
    for s1 in (-1.0, 1.0):
        for s2 in (-1.0, 1.0):
            if not rounded:
                _corner_zone(part, corner(s1, s2, t), size)
                continue
            axis = corner(s1, s2, t) - rounded * (s1 * e1 + s2 * e2)
            part.late.append(Step(f.id, index, inside, RingCorner(_t(axis), _t(n), rounded, 0.0, (sign, 0.0), (0.0, b),
                                                                  size, round_, _t(e1), _quarter(n, e1, s1 * e1 + s2 * e2))))  # fmt: skip


def _round_rod(f: Feature, target: Feature, copy: Copy, which: str, size: float, part: _Part,
               host: _Flat | None, strict: bool) -> None:  # fmt: skip
    """A rod's rims (cylinder.md, boss.md): ``top`` round its +end, ``bottom`` round its -end, ``both``; a boss's ``joint`` round its foot. Each a ring, exact."""
    round_ = not _draw(f.kind).bevels
    p, n = _v(copy.point), _v(copy.direction)
    if copy.lean is not None:  # leaning (step 5.3): its rim round its far end, square to its lean; its joint waits
        if which != "top":
            raise DoesNotFitError(f"{f.id}: a leaning rod's rim is rounded at its far end only, for now")
        n = _v(copy.lean)
    r = target.sizes["diameter"] / 2
    height = target.sizes[_draw(target.kind).rod_length]
    side = part.rounds.get((target.id, copy.index, "side"))
    far_is_high = n[int(np.argmax(np.abs(n)))] > 0
    for name, t, b in (("top", height, -1.0), ("bottom", 0.0, 1.0)):
        if which not in (name, "both"):
            continue
        part.late.append(
            Step(
                f.id,
                copy.index,
                False,
                RingCorner(_t(p), _t(n), r, t, (-1.0, 0.0), (0.0, b), size, round_),
            )
        )
        face = part.flats.get(
            (target.id, copy.index, "+end" if name == "top" else "-end")
        )
        if face is not None:
            face.rim = max(face.rim, size)
        if side is not None:
            k = 1 if (name == "top") == far_is_high else 0
            if strict and any(
                (lo < size + GAP) if k == 0 else (hi > side.length - size - GAP)
                for lo, hi in side.standing
            ):
                raise DoesNotFitError(
                    f"{f.id} would round under something standing round {target.id}'s side"
                )
            side.margin = (
                (max(side.margin[0], size), side.margin[1])
                if k == 0
                else (side.margin[0], max(side.margin[1], size))
            )
    if which == "joint":
        assert host is not None
        at = host.frame.plane(p)
        old = host.foot(target, (at[0], at[1]))
        _keep_clear(f, host, old, _Foot(old.at, (r + size, r + size), r + size), strict)
        part.late.append(
            Step(
                f.id,
                copy.index,
                True,
                RingCorner(_t(p), _t(n), r, 0.0, (1.0, 0.0), (0.0, 1.0), size, round_),
            )
        )


def _quarter(n: Array, e1: Array, d: Array) -> tuple[float, float]:
    """The quarter turn about ``n`` round the way ``d``, as angles from ``e1`` anticlockwise about ``n``."""
    angle = fs.atan2(float(fv.matmul(d, np.cross(n, e1))), float(fv.matmul(d, e1)))
    return angle - math.pi / 4, angle + math.pi / 4


def _round_cut(f: Feature, target: Feature, copy: Copy, which: str, size: float, part: _Part, host: _Flat,
               strict: bool) -> None:  # fmt: skip
    """A cut's rims (hole.md, pocket.md): ``top`` its mouth's (an outside edge, taken), ``bottom`` round a pocket's floor (an inside edge, filled). Straight runs and round corners exact; a sharp corner a zone."""
    round_ = not _draw(f.kind).bevels
    p, n = _v(copy.point), _v(copy.direction)
    depth = host.material if target.depth is None else target.depth
    if strict and size > depth / 2:
        raise DoesNotFitError(f"{f.id} is too big for the cut it rounds")
    at = host.frame.plane(p)
    circle = _draw(target.kind).round_mouth(target)
    if which == "bottom" and target.depth is None:
        raise DoesNotFitError(f"{f.id}: a pocket through has no floor")
    t, a, b, add = (
        (0.0, 1.0, -1.0, False) if which == "top" else (-depth, -1.0, 1.0, True)
    )
    if circle:
        r = target.sizes["diameter"] / 2
        if which == "bottom" and strict and size > r / 2:
            raise DoesNotFitError(f"{f.id} is too big for the pocket's floor")
        part.late.append(
            Step(
                f.id,
                copy.index,
                add,
                RingCorner(_t(p), _t(n), r, t, (a, 0.0), (0.0, b), size, round_),
            )
        )
    else:
        axes = copy.axes
        assert axes is not None
        e1, e2 = _turned_frame(target, host.frame.u, host.frame.v)  # turned with it, where it is turned
        (h1, h2), rc = _footprint(target, axes)
        if which == "bottom" and strict and (size > min(h1, h2) / 2 or 0 < rc < size):
            # Round a rounded corner, a floor's rounding is no bigger than the corner (its ball can't reach
            # past the corner's axis).
            raise DoesNotFitError(f"{f.id} is too big for the pocket's floor")
        # A corner's ring rounds a rounded corner where the ring is a whole one (on a floor, its radius past the
        # rounding's), and the straight runs end where it starts; else the definitions bound the corner, a zone,
        # and the runs are carried on into it.
        ringed = rc > 0 and (which == "top" or rc > size + 0.2)
        reach = (0.0, 0.0) if ringed else (REACH, REACH)
        for s2 in (-1.0, 1.0):
            if h1 - rc > 1e-9:
                part.late.append(Step(f.id, copy.index, add, Corner(_t(p - (h1 - rc) * e1 + s2 * h2 * e2 + t * n), _t(e1),
                                                                    2 * (h1 - rc), _t(a * s2 * e2), _t(b * n), size, round_), reach))  # fmt: skip
        for s1 in (-1.0, 1.0):
            if h2 - rc > 1e-9:
                part.late.append(Step(f.id, copy.index, add, Corner(_t(p + s1 * h1 * e1 - (h2 - rc) * e2 + t * n), _t(e2),
                                                                    2 * (h2 - rc), _t(a * s1 * e1), _t(b * n), size, round_), reach))  # fmt: skip
        for s1 in (-1.0, 1.0):
            for s2 in (-1.0, 1.0):
                centre = p + s1 * (h1 - rc) * e1 + s2 * (h2 - rc) * e2 + t * n
                if ringed:
                    part.late.append(Step(f.id, copy.index, add, RingCorner(_t(centre), _t(n), rc, 0.0, (a, 0.0), (0.0, b), size,
                                                                            round_, _t(e1), _quarter(n, e1, s1 * e1 + s2 * e2))))  # fmt: skip
                else:
                    _corner_zone(
                        part, p + s1 * h1 * e1 + s2 * h2 * e2 + t * n, size, rc
                    )
    if which == "top":
        # Round a round corner, as far again out; at a sharp one the mouth's two roundings meet in a mitre, and
        # what they take may reach the corner of the box round them.
        old = host.foot(target, (at[0], at[1]))
        grown = old.corner + size if old.corner > 0 else 0.0
        _keep_clear(
            f,
            host,
            old,
            _Foot(old.at, (old.half[0] + size, old.half[1] + size), grown),
            strict,
        )


#: ISO 261's coarse pitches (mm), the generator's own copy: a plain metric size's (thread.md).
COARSE = {
    "M3": 0.5,
    "M4": 0.7,
    "M5": 0.8,
    "M6": 1.0,
    "M8": 1.25,
    "M10": 1.5,
    "M12": 1.75,
}
#: The fine pitches a generated thread may name instead (ISO 261).
FINE = {"M8": 1.0, "M10": 1.25, "M12": 1.25}


def _thread_sizes(f: Feature) -> tuple[float, float]:
    """A thread's nominal diameter and pitch, from its designation (M8, M8x1)."""
    assert f.words is not None
    size, _, named = f.words.partition("x")
    if size not in COARSE:
        raise DoesNotFitError(f"{f.id}: the generator threads M3 to M12, not {f.words}")
    return float(size[1:]), float(named) if named else COARSE[size]


def _thread_on(f: Feature, plan: Plan, part: _Part, strict: bool) -> None:
    """A thread on every copy of its rod (thread.md): over its length from the rod's free end, the ring between the basic profile's minor radius and the rod's taken from what the part must hold (:class:`~forge_eval.truth.Threaded`)."""
    target = next((g for g in plan if g.id == f.of), None)
    if target is None or not _draw(target.kind).threadable:
        raise DoesNotFitError(f"{f.id}: a thread goes on a boss or a cylinder")
    nominal, pitch = _thread_sizes(f)
    radius = target.sizes["diameter"] / 2
    if strict and abs(2 * radius - nominal) > 1e-9:
        raise DoesNotFitError(
            f"{f.id}: an {f.words} thread goes on a rod {nominal:g} mm across"
        )
    whole = target.sizes[_draw(target.kind).rod_length]
    length = f.sizes.get("length", whole)
    if strict and length > whole + 1e-9:
        raise DoesNotFitError(f"{f.id} is longer than {target.id}")
    hand = 1 if f.choices.get("hand", "right") == "right" else -1
    for copy in part.copies.get(target.id, []):
        side = part.rounds.get((target.id, copy.index, "side"))
        if strict and side is not None and side.standing:
            raise DoesNotFitError(f"{f.id}: something stands round {target.id}'s side")
        if strict:
            _threaded_clear(
                f,
                target,
                copy,
                radius - 0.3 * pitch,
                (whole - length, whole),
                pitch,
                part,
            )
        part.late.append(Step(f.id, copy.index, False, Threaded(copy.point, copy.direction, radius, pitch, hand,
                                                                whole - length, whole)))  # fmt: skip


#: How far in from a rod's surface a basic thread's root is, in pitches (ISO 68-1: 5/8 of the sharp triangle's height).
_ROOT = 5 / 8 * math.sqrt(3) / 2


def _threaded_clear(f: Feature, rod: Feature, copy: Copy, rho: float, stretch: tuple[float, float], pitch: float,
                    part: _Part) -> None:  # fmt: skip
    """Nothing but the rod copy's own solid is where its thread's groove goes: points round it ``rho`` from its axis, along the threaded stretch (generated part 886: a boss on one of a row of blocks ran through the next, and the groove would have cut that too); and nothing cut into the rod there, from a wall's width in from the thread's root out."""
    w = _v(copy.direction)
    e1 = _v(unit_of("+" + "xyz"[int(np.argmin(np.abs(w)))]))
    e1 = e1 - (fv.matmul(e1, w)) * w
    e1 /= fv.norm(e1)
    e2 = np.cross(w, e1)
    angles = 2 * math.pi * np.arange(36) / 36
    along = np.linspace(stretch[0] + 0.1 * pitch, stretch[1] - 0.1 * pitch, 24)
    ring = rho * (fv.cos(angles)[:, None] * e1 + fv.sin(angles)[:, None] * e2)
    points = (_v(copy.point) + along[:, None, None] * w + ring[None, :, :]).reshape(
        -1, 3
    )
    # The part as made so far, the rod's own solid left out: its material there is something else's.
    others = tuple(
        s
        for s in (*part.steps, *part.late)
        if (s.item, s.index) != (rod.id, copy.index)
    )
    if np.any(Truth({}, others).inside(points)):
        raise DoesNotFitError(f"{f.id}: something else is where {rod.id}'s thread goes")
    # And the rod's own material is all there, from a wall in from the thread's root out to its crests: nothing
    # is cut into the stretch the thread is cut into (generated part 1574: a letter engraved in a stud's end
    # reached past the root, and its walls stood among the thread's flanks).
    root = rod.sizes["diameter"] / 2 - _ROOT * pitch
    rings = np.linspace(max(root - GAP, 0.25 * root), rho, 5)
    middle = _v(copy.point) + along[:, None, None] * w
    solid = np.concatenate([(middle + r / rho * ring).reshape(-1, 3) for r in rings])
    if not np.all(Truth({}, (*part.steps, *part.late)).inside(solid)):
        raise DoesNotFitError(f"{f.id}: something is cut where {rod.id}'s thread goes")
    part.threads.append((f.id, solid))


def _round_solids(
    steps: list[Step],
) -> list[tuple[str, Array, Array, float, float, float]]:
    """Each step's solid that is a round rod (a disc's prism): its item, a point on its axis and the axis, its radius, and how far along the axis it runs from that point."""
    found = []
    for step in steps:
        s = step.solid.solid if isinstance(step.solid, Kept) else step.solid  # a leaning one's whole rod
        if isinstance(s, Prism) and all(s.rounded) and s.corner >= max(s.half):
            found.append(
                (step.item, _v(s.centre), _v(s.normal), s.corner, s.low, s.high)
            )
    return found


def _cross_cleanly(steps: list[Step]) -> None:
    """Round solids of different items that meet cross cleanly (a :class:`DoesNotFitError` where they don't): their surfaces apart by ``GAP``, or one passing wholly within the other, ``GAP`` in.

    Where two round surfaces meet all but tangentially (two rods of about
    one size crossing, or one just grazing another), their intersection is
    steep to place: a mesh's polygons cross far from where the surfaces do,
    and no deflection their sag gives holds there.
    """
    rods = _round_solids(steps)
    for i, (item1, p1, w1, r1, lo1, hi1) in enumerate(rods):
        for item2, p2, w2, r2, lo2, hi2 in rods[i + 1 :]:
            if item1 == item2:
                continue
            across = np.cross(w1, w2)
            size = float(fv.norm(across))
            gap = p2 - p1
            if size < 1e-9:  # parallel: how far apart the axes are
                d = float(fv.norm(gap - (fv.matmul(gap, w1)) * w1))
                s1, s2 = (
                    (lo1, hi1),
                    (
                        float(fv.matmul(gap, w1)) + lo2 * float(fv.matmul(w1, w2)),
                        float(fv.matmul(gap, w1)) + hi2 * float(fv.matmul(w1, w2)),
                    ),
                )
                overlap = min(max(s1), max(s2)) > max(min(s1), min(s2))
            else:  # crossing: where the axes come nearest
                d = abs(float(fv.matmul(gap, across))) / size
                m = np.array(
                    [[1.0, -float(fv.matmul(w1, w2))], [float(fv.matmul(w1, w2)), -1.0]]
                )
                t1, t2 = fv.solve(
                    m, [float(fv.matmul(gap, w1)), float(fv.matmul(gap, w2))]
                )
                overlap = lo1 - r2 <= t1 <= hi1 + r2 and lo2 - r1 <= t2 <= hi2 + r1
            if not overlap:
                continue
            if abs(r1 - r2) - GAP < d < r1 + r2 + GAP:
                raise DoesNotFitError(f"{item1} and {item2} cross all but tangentially")


def _segment_gap(p1: Array, w1: Array, lo1: float, hi1: float, p2: Array, w2: Array, lo2: float,
                 hi2: float) -> float:  # fmt: skip
    """How near two stretches of line come: ``p1 + s w1`` for ``s`` from ``lo1`` to ``hi1``, and ``p2 + t w2`` for ``t``
    from ``lo2`` to ``hi2`` (unit ``w``): the least distance between them, each end where it is (Ericson, Real-Time
    Collision Detection, 5.1.9)."""
    a, b = p1 + lo1 * w1, p2 + lo2 * w2
    d1, d2 = (hi1 - lo1) * w1, (hi2 - lo2) * w2
    r = a - b
    e1, e2, f = float(fv.matmul(d1, d1)), float(fv.matmul(d2, d2)), float(fv.matmul(d2, r))
    c, cross = float(fv.matmul(d1, r)), float(fv.matmul(d1, d2))
    denominator = e1 * e2 - cross * cross
    s = min(max((cross * f - c * e2) / denominator, 0.0), 1.0) if denominator > 1e-12 * e1 * e2 else 0.0
    t = (cross * s + f) / e2
    if t < 0.0:
        t, s = 0.0, min(max(-c / e1, 0.0), 1.0)
    elif t > 1.0:
        t, s = 1.0, min(max((cross - c) / e1, 0.0), 1.0)
    return float(fv.norm((a + s * d1) - (b + t * d2)))


def _leaning_rods_cross_cleanly(steps: list[Step]) -> None:
    """A leaning rod (a hole's or a boss's, run along its direction: :func:`_on_flat_leaning`) and another item's round
    rod cross cleanly (:func:`_cross_cleanly`), measured between the stretches of their axes each runs along: the
    lines' nearest points may lie far past their ends where they are all but parallel (generated part 134, a hole
    leaning 1 degree beside one drilled from the face across, crossing it all but tangentially along 20 mm), and
    there it is the stretches that come near. A part with nothing leaning has no such rod: it is as it was."""
    leaning = {id(step.solid.solid) for step in steps if isinstance(step.solid, Kept)}
    if not leaning:
        return
    found = []
    for step in steps:
        s = step.solid.solid if isinstance(step.solid, Kept) else step.solid
        if isinstance(s, Prism) and all(s.rounded) and s.corner >= max(s.half):
            found.append((step.item, id(s) in leaning, _v(s.centre), _v(s.normal), s.corner, s.low, s.high))
    for i, (item1, lean1, p1, w1, r1, lo1, hi1) in enumerate(found):
        for item2, lean2, p2, w2, r2, lo2, hi2 in found[i + 1 :]:
            if item1 == item2 or not (lean1 or lean2):
                continue
            d = _segment_gap(p1, w1, lo1, hi1, p2, w2, lo2, hi2)
            if abs(r1 - r2) - GAP < d < r1 + r2 + GAP:
                raise DoesNotFitError(f"{item1} and {item2} cross all but tangentially")


#: How near a round surface may come to another item's flat wall it runs along, either side of it, and be taken
#: as touching it along a line (mm): far above OpenCascade's 1e-4 mm and the 5e-4 mm the sizes are written to.
_TOUCHING = 0.01


def _walls_crossed(plan: Plan, steps: list[Step]) -> None:
    """A round rod of one item and a flat wall of another's prism it runs along are apart, or cross (a :class:`DoesNotFitError` where they touch).

    Tangent to the wall along a stretch they both have, within
    :data:`_TOUCHING`, the rod leaves the part touching itself along a line,
    no solid at all (held-out seed 10849: a hole drilled down from a block's
    top, its side exactly on the wall of a pocket bored in from a boss's
    end). A boss flush with its own host's side is meant (_flushed), and
    stays. A wall a little thicker, or a crossing a little deeper, is a part,
    and is built and judged as such.
    """
    hosts = {f.id: (f.on[0] if f.on else None) for f in plan}
    adds = {step.item: step.add for step in steps}
    rods = _round_solids(steps)
    for step in steps:
        s = step.solid.solid if isinstance(step.solid, Kept) else step.solid  # a leaning one's whole prism
        if not isinstance(s, Prism) or (all(s.rounded) and s.corner >= max(s.half)):
            continue
        c, e1, e2, n = (_v(x) for x in (s.centre, s.first, s.second, s.normal))
        h1, h2 = s.half
        across1, across2, along = (e2, -h2, h2), (e1, -h1, h1), (n, s.low, s.high)
        walls = [(e1, h1, across1, along), (e1, -h1, across1, along), (e2, h2, across2, along),
                 (e2, -h2, across2, along), (n, s.low, across2, across1), (n, s.high, across2, across1)]  # fmt: skip
        for item, p, w, r, lo, hi in rods:
            if item == step.item or (adds.get(item) and hosts.get(item) == step.item):
                continue
            t = np.linspace(lo, hi, 64)
            for a, at, (b1, l1, u1), (b2, l2, u2) in walls:
                # From the wall's plane to the rod's axis:
                away = abs(float(fv.matmul(p - c, a)) - at)
                if abs(float(fv.matmul(w, a))) > 1e-9 or abs(away - r) >= _TOUCHING:
                    continue
                x1 = float(fv.matmul(p - c, b1)) + t * float(fv.matmul(w, b1))
                x2 = float(fv.matmul(p - c, b2)) + t * float(fv.matmul(w, b2))
                if np.any((x1 > l1) & (x1 < u1) & (x2 > l2) & (x2 < u2)):
                    where = f"{step.item}'s wall"
                    raise DoesNotFitError(f"{item} touches {where} along a line")


#: How far apart the points under a line of letters are looked at, at most (mm), and in how many layers.
_UNDER_STEP = 0.1
_UNDER_LAYERS = 6
#: How far under a line's floor its first layer is: off the floor itself, which is the letters' surface (mm).
_UNDER_OFF = 0.01


def _letters_stand(truth: Truth) -> None:
    """Each line of letters stands on material (a :class:`DoesNotFitError` where it doesn't): ``GAP`` of the part under its ink, under an engraving's floor or an embossed line's foot.

    A letter's inside (an O's, a D's) is held by what is under it alone:
    a cut from another face that breaks into the material there, or all but
    does, leaves it loose, or on a skin too thin to hold (generated part
    2511: a line engraved 1.363 mm into a block's top over round pockets
    from the block's side, their crests 0.53 mm under the top; each D's
    inside came away, the part four solids). The rules each cut is placed
    by keep it within its own face and clear of what is on that face; what
    is under a line, whatever made it, is looked at here: on a grid at most
    0.1 mm apart over the ink's box, in layers from just under the floor to
    ``GAP`` under it, every point in the part.
    """
    from forge_spec.font import CAP_HEIGHT

    for step in truth.steps:
        s = step.solid
        if not isinstance(s, Letters):
            continue
        box = ink_box(s.text, s.height)
        if box is None:
            continue
        (x0, y0), (x1, y1) = box
        middle = line_pieces(s.text)[1] * s.height / CAP_HEIGHT / 2
        u = np.linspace(x0, x1, max(2, math.ceil((x1 - x0) / _UNDER_STEP) + 1)) - middle
        v = (
            np.linspace(y0, y1, max(2, math.ceil((y1 - y0) / _UNDER_STEP) + 1))
            - s.height / 2
        )
        t = s.low - np.linspace(_UNDER_OFF, GAP, _UNDER_LAYERS)
        uu, vv, tt = (a.ravel() for a in np.meshgrid(u, v, t, indexing="ij"))
        way, up, n = (
            np.asarray(w, dtype=np.float64) for w in (s.right, s.up, s.normal)
        )
        points = (
            np.asarray(s.centre)
            + uu[:, None] * way
            + vv[:, None] * up
            + tt[:, None] * n
        )
        air = points[~truth.inside(points)]
        if len(air):
            by = sorted(
                {
                    o.item
                    for o in truth.steps
                    if not o.add and o.solid.contains(air).any()
                }
            )
            raise DoesNotFitError(
                f"{step.item}: what is under its letters is cut into"
                + (f" by {', '.join(by)}" if by else "")
                + ": their insides would come loose"
            )


#: How far past a cut's side the points asked whether it is built are (mm), and how many of them: round it, and
#: through its depth, in layers.
_SIDE_OFF = 0.02
_SIDE_ROUND = 64
_SIDE_LAYERS = 8
#: The least share of them that must be in the part.
_SIDE_BUILT = 0.1


def _cuts_sided(plan: Plan, truth: Truth) -> None:
    """Each hole's, pocket's and slot's side is built (a :class:`DoesNotFitError` where it isn't): a tenth at least of points just past it, spread round it and through its depth, in the part.

    Its diameter, its length and width, its place are measured on its side;
    where another cut from another face takes all but none of it (generated
    part 3151: a counterbored hole into a post's side, past its counterbore
    wholly within a pocket cut deep into the post from another side), none
    of it is built, and nothing measures the item. A hole's counterbore
    takes the side by its mouth, and is its own step after the hole's.
    """
    kinds = {f.id: f.kind for f in plan}
    seen: set[tuple[str, int]] = set()
    for step in truth.steps:
        s = step.solid
        kind = kinds.get(step.item)
        if (
            step.add
            or kind is None
            or not _truth(kind).sided
            or not isinstance(s, (Prism, Kept))
        ):
            continue
        if (step.item, step.index) in seen:
            continue  # a counterbore, after its hole's own step
        seen.add((step.item, step.index))
        if isinstance(s, Kept):  # leaning: its rod's side, where it is kept
            points = _past_side(s.solid)
            height = fv.matmul(points - np.asarray(s.origin), np.asarray(s.normal))
            points = points[(height > s.low) & (height < s.high)]
        else:
            points = _past_side(s)
        if float(np.mean(truth.inside(points))) < _SIDE_BUILT:
            raise DoesNotFitError(
                f"{step.item}'s side is all but nowhere built: what else is cut there takes it"
            )


def _past_side(s: Prism) -> Array:
    """Points :data:`_SIDE_OFF` past a prism's side, spread evenly round its outline and through its height."""
    h1, h2 = s.half
    r = s.corner
    # The outline grown by the offset: its four corners' quarter circles (a sharp corner's, the offset's own) in
    # turn, counterclockwise, the straight sides running between them.
    pieces: list[Array] = []
    for k, ((q1, q2), on) in enumerate(zip(QUADRANTS, s.rounded, strict=True)):
        cr = r if on else 0.0
        centre = np.array([q1 * (h1 - cr), q2 * (h2 - cr)])
        a = k * math.pi / 2 + np.linspace(0.0, math.pi / 2, 9)
        pieces.append(
            centre + (cr + _SIDE_OFF) * np.stack([fv.cos(a), fv.sin(a)], axis=1)
        )
    ring = np.concatenate(pieces)
    # Even spacing along the closed polygon.
    closed = np.vstack([ring, ring[:1]])
    lengths = fv.norm(np.diff(closed, axis=0), axis=1)
    at = np.concatenate([[0.0], np.cumsum(lengths)])
    want = np.linspace(0.0, at[-1], _SIDE_ROUND, endpoint=False)
    u = fv.interp(want, at, closed[:, 0])
    v = fv.interp(want, at, closed[:, 1])
    t = s.low + (np.arange(_SIDE_LAYERS) + 0.5) / _SIDE_LAYERS * (s.high - s.low)
    first, second, normal = (
        np.asarray(w, dtype=np.float64) for w in (s.first, s.second, s.normal)
    )
    uu, tt = np.meshgrid(u, t, indexing="ij")
    vv, _ = np.meshgrid(v, t, indexing="ij")
    return (
        np.asarray(s.centre)
        + uu.reshape(-1, 1) * first
        + vv.reshape(-1, 1) * second
        + tt.reshape(-1, 1) * normal
    )


def render(plan: Plan, strict: bool = True) -> Case:
    """The part a plan makes: every copy, the solids in the order made, and the draft; a :class:`DoesNotFitError` if it isn't valid (``strict``)."""
    part = _build(plan, strict)
    if strict:
        _cross_cleanly(part.steps)
        _leaning_rods_cross_cleanly(part.steps)
        _walls_crossed(plan, part.steps)
    truth = Truth(
        {k: tuple(v) for k, v in part.copies.items()},
        (*part.steps, *part.late),
        tuple(part.zones),
    )
    if strict:
        _letters_stand(truth)
        _cuts_sided(plan, truth)
    names = _names(plan)
    w = Writer()
    drafts = [_draft(f, w, names) for f in plan]
    brief, items = w.finish(drafts)
    return Case(plan, brief, items, truth)


def _names_own_axes(item: Mapping[str, Any]) -> bool:
    """Whether a drafted item names its face's axes by the face's own, ``u`` and ``v`` (schema 1.4)."""
    own = {"u", "v"}
    place = item.get("place")
    if isinstance(place, Mapping):
        if own & set(place):
            return True
        for body in (place.get("pattern") or {}).values():
            if any(k.rpartition("_")[2] in own for k in body) or (body.get("axis") or {}).get("choose") in own:
                return True
    return any((item.get(name) or {}).get("choose", " ")[-1] in own
               for name in ("along", "thickness_along", "tilt_towards"))  # fmt: skip


def draft_of(items: Iterable[Mapping[str, Any]], name: str = "generated") -> dict[str, Any]:
    """A generated part's draft: its items, in the least schema version that reads them (forge_spec.versions):
    1.6 where an item is on a ball's surface (place.latitude), 1.5 where a body leans on its face, 1.4 where an item names its face's own axes (u and v), 1.3 where one leans
    on its face (tilt), 1.2 where one is
    turned in it (place.turn), else the first, so a part that does none of these is read, and its spec's digest
    made, as it always was."""
    found = list(items)
    if any(isinstance(item.get("place"), Mapping) and "latitude" in item["place"] for item in found):
        return {"schema_version": "1.6", "name": name, "items": found}  # on a ball's surface (item 3b's second step)
    if any("tilt" in item and "kind" in item and _draw(item["kind"]).leans_since >= (1, 5) for item in found):
        return {"schema_version": "1.5", "name": name, "items": found}
    if any(_names_own_axes(item) for item in found):
        return {"schema_version": "1.4", "name": name, "items": found}
    if any("tilt" in item for item in found):
        return {"schema_version": "1.3", "name": name, "items": found}
    if any(isinstance(item.get("place"), Mapping) and "turn" in item["place"] for item in found):
        return {"schema_version": "1.2", "name": name, "items": found}
    return {"spec_format": 1, "name": name, "items": found}


# ----------------------------------------------------------------------
# Choosing a plan
# ----------------------------------------------------------------------
def _choose_first(rng: random.Random) -> Feature:
    roll = rng.random()
    if roll < 0.7:
        return Feature("body", "block", {"length": _q(rng.uniform(40, 120)), "width": _q(rng.uniform(30, 90)),
                                         "height": _q(rng.uniform(5, 30))})  # fmt: skip
    if roll < 0.85:
        return Feature(
            "body",
            "cylinder",
            {"diameter": _q(rng.uniform(30, 90)), "length": _q(rng.uniform(10, 50))},
        )
    if roll < 0.93:
        return _choose_pushed(rng)
    return _choose_turned(rng)


def _choose_shell(rng: random.Random, body: Feature) -> Feature:
    """A shell of the first body: sealed, open on a face (a tray, a cup) or on two across from each other, its walls 1 mm thick or more, and now and then a floor of its own."""
    least, opened, across = _draw(body.kind).shell_opening(rng, body)
    sizes_ = {"thickness": _q(rng.uniform(1.0, max(1.2, least / 6)))}
    floored = _draw(body.kind).floored(opened)
    if floored and rng.random() < 0.5:
        sizes_["floor"] = _q(rng.uniform(1.0, max(1.2, across / 5)))
    return Feature("hollow", "shell", sizes_, of=body.id, faces=opened)


def _choose_rounding(rng: random.Random, name: str, target: Feature) -> Feature | None:
    """A rounding (three times in four) or a bevel of one of an item's edge sets, a quarter of the most it could be or less (and 0.3 mm or more)."""
    sets = _draw(target.kind).roundable(target.on is None)
    if not sets:
        return None
    which = rng.choice(sets)
    which, most = _draw(target.kind).most_rounding(target, which)
    fillet = rng.random() < 0.75
    size = _q(rng.uniform(0.3, max(0.35, most / 4)))
    choices = {"which": which}
    if which == "joint":
        assert target.on is not None
        choices["where_meets"] = target.on[0]
    return Feature(name, "fillet" if fillet else "chamfer", {"radius" if fillet else "size": size}, of=target.id,
                   choices=choices)  # fmt: skip


def _round_now_and_then(
    seed: int, k: int | None, target: Feature, plan: list[Feature]
) -> None:
    """Now and then a rounding or a bevel of an item just drawn, from a stream of its own, kept where the part it makes is valid."""
    rng = random.Random(f"forge-eval roundings {seed}" + ("" if k is None else f" {k}"))
    if rng.random() >= _ROUNDED:
        return
    rounding = _choose_rounding(rng, "round_body" if k is None else f"round{k}", target)
    if rounding is None:
        return
    try:
        render((*plan, rounding))
    except DoesNotFitError:
        return
    plan.append(rounding)
    # Now and then, a box's vertical edges rounded, the edges round its top (its base, or its joint) too: they
    # follow its rounded corners (edges.md).
    if (
        not _draw(rounding.kind).bevels
        and rounding.choices["which"] == "vertical"
        and rng.random() < 0.4
    ):
        radius = rounding.sizes["radius"]
        if radius < 0.65:
            return
        which = rng.choice(("top", "bottom") if target.on is None else ("top", "joint"))
        size = _q(rng.uniform(0.3, radius - 0.25))
        kind = "fillet" if rng.random() < 0.75 else "chamfer"
        choices = {"which": which}
        if which == "joint":
            assert target.on is not None
            choices["where_meets"] = target.on[0]
        second = Feature(rounding.id + "_also", kind, {_draw(kind).rounding_size: size},
                         of=target.id, choices=choices)  # fmt: skip
        try:
            render((*plan, second))
        except DoesNotFitError:
            return
        plan.append(second)


def _choose_dome(rng: random.Random) -> Feature:
    """A dome as the first body: 30 to 100 mm across."""
    return Feature(
        "body",
        "sphere",
        {"diameter": _q(rng.uniform(30, 100))},
        choices={"portion": "upper_half"},
    )


def _choose_tube(rng: random.Random) -> Feature:
    """A tube as the first body: 30 to 90 mm across, its wall 3 mm or more and no more than 15, 10 to 50 mm long."""
    outer = _q(rng.uniform(30, 90))
    wall = _q(rng.uniform(3, max(3.5, min(15.0, outer / 2 - 6))))
    return Feature("body", "tube", {"outer_diameter": outer, "inner_diameter": _q(outer - 2 * wall),
                                    "length": _q(rng.uniform(10, 50))})  # fmt: skip


def _even(rng: random.Random, lo: float, hi: float) -> float:
    """A size on the 0.002 mm grid: its half is on the 0.001 grid too."""
    return _q(rng.uniform(lo, hi), 0.002)


def _choose_pushed(rng: random.Random) -> Feature:
    """An extrusion as the first body: an L, a T, a plate with round ends, or a plate with a corner rounded and one cut."""
    shape = rng.choice(PUSHED)
    if shape == "L":
        a, b = _q(rng.uniform(40, 100)), _q(rng.uniform(30, 80))
        values = {"a": a, "b": b, "t": _q(rng.uniform(8, min(a, b) / 2.5))}
    elif shape == "T":
        w, h = _even(rng, 40, 100), _even(rng, 30, 80)
        values = {
            "w": w,
            "h": h,
            "t": _even(rng, 8, h / 2.5),
            "s": _even(rng, 8, w / 2.5),
        }
    elif shape == "stadium":
        w = _even(rng, 20, 50)
        values = {"l": _even(rng, w + 10, w + 70), "w": w}
    else:
        a, b = _q(rng.uniform(40, 100)), _q(rng.uniform(30, 80))
        values = {
            "a": a,
            "b": b,
            "r": _q(rng.uniform(3, min(a, b) / 2.5)),
            "c": _q(rng.uniform(3, min(a, b) / 2.5)),
        }
    return Feature(
        "body",
        "extrusion",
        {"length": _q(rng.uniform(6, 30))},
        outline=(shape, tuple(values.items())),
    )


def _choose_turned(rng: random.Random) -> Feature:
    """A revolution as the first body: a flange, a knob with a rounded rim, or a pulley with a groove."""
    shape = rng.choice(TURNED)
    if shape == "flange":
        big = _q(rng.uniform(20, 45))
        rh = _q(rng.uniform(8, big - 4))
        h = _q(rng.uniform(15, 40))
        values = {"rb": _q(rng.uniform(2, rh - 3)) if rng.random() < 0.6 else 0.0, "R": big, "t": _q(rng.uniform(4, h / 2.5)),
                  "rh": rh, "h": h}  # fmt: skip
    elif shape == "knob":
        big = _q(rng.uniform(15, 40))
        c = _q(rng.uniform(1, 4))
        h1 = _q(rng.uniform(4, 15))
        values = {"rs": _q(rng.uniform(3, big - c - 3)), "h1": h1, "R": big, "c": c,
                  "h2": _q(h1 + 2 * c + rng.uniform(3, 15))}  # fmt: skip
    else:
        big = _q(rng.uniform(15, 40))
        h = _even(rng, 10, 30)
        g = _q(rng.uniform(1.5, h / 2 - 2))
        values = {"rb": _q(rng.uniform(2, big - g - 4)), "R": big, "g": g, "h": h}
    return Feature("body", "revolution", {}, outline=(shape, tuple(values.items())))


def _position(rng: random.Random, axis: str, room: float, whole: bool) -> Position:
    """A position along one axis, its distance a fair share of the room there is."""
    mode = rng.choice(["none", "centred", "offset", "offset", "side", "side"])
    if mode in ("none", "centred"):
        return Position(mode)
    if mode == "offset":
        return Position("offset", _q(rng.uniform(-room, room)))
    to = "centre" if whole or rng.random() < 0.5 else "edge"
    return Position(
        "side",
        _q(rng.uniform(GAP + 0.5, max(GAP + 1.0, room))),
        rng.choice(["+", "-"]) + axis,
        to,
    )


def _pattern(rng: random.Random, face: _Flat, size: float) -> Pattern | None:
    a1, a2 = face.axes
    roll = rng.random()
    if roll < 0.45:
        return None
    if roll < 0.62:
        axis = rng.choice(face.axes)
        return Pattern(
            "row",
            {"pitch": _q(size + rng.uniform(1.5, 8))},
            {"count": rng.randint(2, 4)},
            axis,
        )
    if roll < 0.72:
        return Pattern("grid", {f"pitch_{a1}": _q(size + rng.uniform(1.5, 6)), f"pitch_{a2}": _q(size + rng.uniform(1.5, 6))},
                       {f"count_{a1}": rng.randint(1, 3), f"count_{a2}": rng.randint(2, 3)})  # fmt: skip
    if roll < 0.80 and face.shape == "rect":
        # Each copy in its own corner: its inset less than half the face, less its own half size.
        insets = [_q(size / 2 + rng.uniform(1, 5)) for _ in (a1, a2)]
        if all(
            inset < h - size / 2 - GAP
            for inset, h in zip(insets, face.half, strict=True)
        ):
            return Pattern(
                "corners", {f"inset_{a1}": insets[0], f"inset_{a2}": insets[1]}, {}
            )
        return None
    if roll < 0.88:
        return Pattern(
            "rectangle",
            {a1: _q(size + rng.uniform(2, 15)), a2: _q(size + rng.uniform(2, 15))},
            {},
        )
    n = rng.randint(3, 6)
    d = _q(max(size / fs.sin(math.pi / n) + 2, rng.uniform(10, 40)))
    values: dict[str, float] = {"diameter": d}
    if rng.random() < 0.6:
        values["start"] = _q(rng.uniform(0, 90), 0.5)
    return Pattern("circle", values, {"count": n})


def _feature(
    rng: random.Random, k: int, host: str, face: _Flat, standing_ok: bool
) -> Feature:
    """A feature on a flat face, sized from it."""
    small = {
        "ring": (face.half[0] - face.inner) / 2,
        "disc": face.half[0],
        "profile": face.widest,
    }.get(face.shape, min(face.half))
    kind = rng.choice(
        _weighted("flat_weight", "flat_rank", lambda e: standing_ok or e.cut_out)
    )
    sizes: dict[str, float] = {}
    choices: dict[str, str] = {}
    recess = None
    depth: float | None = None
    top = max(1.6, min(12.0, small / 2))
    recess = _draw(kind).draw_on_flat(rng, face, top, sizes, choices)
    if _draw(kind).cut_out:
        if rng.random() < 0.5 and face.exit is not None:
            depth = None
        else:
            least = 0.5
            if recess is not None and recess[0] == "counterbore":
                least += recess[2]
            elif recess is not None:
                least += (
                    (recess[1] - sizes["diameter"])
                    / 2
                    / fs.tan(math.radians(recess[2] / 2))
                )
            depth = _q(rng.uniform(least, max(least + 0.1, face.material - GAP - 0.1)))
    f = Feature(f"i{k}", kind, sizes, (host, face.key[2]), depth, choices, recess)
    (h1, h2), _ = _footprint(f, face.axes)
    size = 2 * max(h1, h2)
    pattern = _pattern(rng, face, size)
    place = {}
    fixed = (
        set(face.axes)
        if pattern is not None and _pattern_draw(pattern.kind).at_the_corners
        else set()
    )
    whole = pattern is not None and _pattern_draw(pattern.kind).round_whole
    for i, axis in enumerate(face.axes):
        if axis not in fixed:
            room = (
                face.half[i] if face.shape in ("rect", "profile") else face.half[0]
            ) * 0.6
            place[axis] = _position(rng, axis, room, whole)
    return replace(f, place=place, pattern=pattern)


def _weighted(
    weight: str, rank: str, keep: Callable[[DrawKind], bool] | None = None
) -> list[str]:
    """The kinds a draw chooses among (those ``keep`` keeps), each as many times as its ``weight`` says, in its ``rank``'s order (today's): the list ``rng.choice`` takes, the same for every seed."""
    from .items.draw import DRAW

    entries = sorted(
        (e for e in DRAW.values() if getattr(e, weight) and (keep is None or keep(e))),
        key=lambda e: getattr(e, rank),
    )
    return [e.key for e in entries for _ in range(getattr(e, weight))]


def _standing_new(rng: random.Random, k: int, host: str, face: _Flat) -> Feature:
    """A rib, a cone or a tube standing on a flat face, sized from it: kinds stage 2 didn't draw (docs/V2-stage4.md, 12.2)."""
    small = {
        "ring": (face.half[0] - face.inner) / 2,
        "disc": face.half[0],
        "profile": face.widest,
    }.get(face.shape, min(face.half))
    top = max(1.6, min(12.0, small / 2))
    kind = rng.choice(_weighted("new_weight", "new_rank"))
    choices: dict[str, str] = {}
    sizes = _draw(kind).draw_new(rng, face, top, choices)
    place = {axis: _position(rng, axis, (face.half[i] if face.shape in ("rect", "profile") else face.half[0]) * 0.6,
                             False) for i, axis in enumerate(face.axes)}  # fmt: skip
    return Feature(
        f"i{k}", kind, sizes, (host, face.key[2]), None, choices, None, place
    )


def _standing_profiled(rng: random.Random, k: int, host: str, face: _Flat) -> Feature:
    """An extrusion or a revolution standing on a flat face (docs/V2-stage4.md, 12.2): one of the outlines a first body is drawn with, sized from the face."""
    room = {
        "ring": ((face.half[0] - face.inner) / 2,) * 2,
        "disc": (0.7 * face.half[0],) * 2,
        "profile": (face.widest,) * 2,
    }.get(face.shape, face.half)
    if rng.random() < 0.5:
        shape = rng.choice(PUSHED)
        a, b = (_q(2 * h * rng.uniform(0.3, 0.8)) for h in room)
        if shape == "L":
            values = {
                "a": a,
                "b": b,
                "t": _q(rng.uniform(min(a, b) / 6, min(a, b) / 2.5)),
            }
        elif shape == "T":
            w, h = _q(a, 0.002), _q(b, 0.002)
            values = {
                "w": w,
                "h": h,
                "t": _even(rng, h / 6, h / 2.5),
                "s": _even(rng, w / 6, w / 2.5),
            }
        elif shape == "stadium":
            w = _even(rng, 0.4 * b, b)
            values = {"l": _even(rng, w + 1.5, max(w + 1.6, a)), "w": w}
        else:
            values = {"a": a, "b": b, "r": _q(rng.uniform(min(a, b) / 8, min(a, b) / 2.5)),
                      "c": _q(rng.uniform(min(a, b) / 8, min(a, b) / 2.5))}  # fmt: skip
        sizes = {"length": _q(rng.uniform(2, 15))}
        kind = "extrusion"
    else:
        shape = rng.choice(TURNED)
        big = _q(min(room) * rng.uniform(0.3, 0.8))
        if shape == "flange":
            rh, h = _q(rng.uniform(0.3 * big, big - 1.2)), _q(rng.uniform(3, 15))
            values = {"rb": _q(rng.uniform(0.5, rh - 1.5)) if rh > 2.5 and rng.random() < 0.5 else 0.0, "R": big,
                      "t": _q(rng.uniform(1, h / 2.5)), "rh": rh, "h": h}  # fmt: skip
        elif shape == "knob":
            c, h1 = (
                _q(rng.uniform(0.4, max(0.5, min(2.0, big / 4)))),
                _q(rng.uniform(1.5, 8)),
            )
            values = {"rs": _q(rng.uniform(1, big - c - 1.2)), "h1": h1, "R": big, "c": c,
                      "h2": _q(h1 + 2 * c + rng.uniform(1, 8))}  # fmt: skip
        else:
            h = _even(rng, 4, 15)
            g = _q(rng.uniform(0.5, h / 2 - 1))
            values = {
                "rb": _q(rng.uniform(0.5, big - g - 1.5)),
                "R": big,
                "g": g,
                "h": h,
            }
        sizes = {}
        kind = "revolution"
    place = {axis: _position(rng, axis, (face.half[i] if face.shape in ("rect", "profile") else face.half[0]) * 0.4,
                             False) for i, axis in enumerate(face.axes)}  # fmt: skip
    return Feature(
        f"i{k}",
        kind,
        sizes,
        (host, face.key[2]),
        place=place,
        outline=(shape, tuple(values.items())),
    )


def _flushed(rng: random.Random, f: Feature, face: _Flat) -> Feature:
    """A box standing flush with one of a face's sides (place.md: 0 from that edge, to its own), or with two (in a corner); a boss so touches them."""
    axes = list(face.axes) if rng.random() < 0.3 else [rng.choice(face.axes)]
    place = dict(f.place)
    for axis in axes:
        place[axis] = Position("side", 0.0, rng.choice(["+", "-"]) + axis, "edge")
    return replace(f, place=place)


def _overhung(rng: random.Random, f: Feature, face: _Flat) -> Feature:
    """A block standing over one of a face's sides (frame.md: a body may overhang the face it stands on): offset along that axis so that it reaches past the edge by a fair share of itself, and stays over the face by more."""
    k = rng.randrange(2)
    axis = face.axes[k]
    half = _footprint(f, face.axes)[0][k]
    past = _q(
        rng.uniform(
            _OVERHANG[0] + 0.1, max(_OVERHANG[0] + 0.2, 0.6 * (2 * half - _OVERHANG[1]))
        )
    )
    sign = rng.choice([-1.0, 1.0])
    return replace(
        f,
        place={
            **f.place,
            axis: Position("offset", _q(sign * (face.half[k] - half + past))),
        },
    )


def _side_standing(rng: random.Random, k: int, host: str, side: _Round) -> Feature:
    """A boss or a post standing round a rod's side (place.md): out along a frame axis, one copy or (one in five) a circle of two or four, placed along the side's axis."""
    tall = _q(rng.uniform(2.0, max(2.5, min(12.0, side.radius))))
    if rng.random() < 0.6:
        kind = "boss"
        sizes = {
            "diameter": _q(
                rng.uniform(2.0, max(2.5, min(side.radius, side.length / 3)))
            ),
            "height": tall,
        }
    else:
        kind = "post"
        sizes = {"length": _q(rng.uniform(2.0, max(2.5, side.radius))),
                 "width": _q(rng.uniform(2.0, max(2.5, side.length / 3))), "height": tall}  # fmt: skip
    pattern = None
    if rng.random() < 0.2:
        pattern = Pattern("circle", {}, {"count": rng.choice([2, 4])})
    pos = _position(rng, side.axis, side.length * 0.25, False)
    return Feature(f"i{k}", kind, sizes, (host, "side"), None, {}, None, {side.axis: pos},
                   rng.choice([0.0, 90.0, 180.0, 270.0]), pattern)  # fmt: skip


#: How often a boss or a post drawn standing round a rod's side is put at any angle round it (item 3b's first step).
_ANGLED = 0.5


def _angled_now_and_then(rng: random.Random, f: Feature) -> Feature | None:
    """Now and then a boss or a post standing round a rod's side at any angle round it, on a half-degree grid, and now
    and then a circle of three, five or six of them (item 3b's first step), from a stream of its own; None when it is
    left as drawn (at 0, 90, 180 or 270 degrees)."""
    if rng.random() >= _ANGLED:
        return None
    angle = _q(rng.uniform(0.0, 360.0), 0.5)
    pattern = Pattern("circle", {}, {"count": rng.choice([3, 5, 6])}) if rng.random() < 0.3 else f.pattern
    return replace(f, angle=angle, pattern=pattern)


def _side_hole(rng: random.Random, k: int, host: str, side: _Round) -> Feature:
    r = _q(rng.uniform(0.75, max(0.8, min(side.radius / 2.5, side.length / 6))))
    depth = None if rng.random() < 0.5 else _q(rng.uniform(0.5, side.radius * 0.8))
    pattern = None
    if (
        depth is not None and rng.random() < 0.4
    ):  # through, copies of one size would touch at the axis
        pattern = Pattern("circle", {}, {"count": rng.choice([2, 3, 4, 6])})
    pos = _position(rng, side.axis, side.length * 0.25, False)
    return Feature(f"i{k}", "hole", {"diameter": _q(2 * r)}, (host, "side"), depth, {}, None,
                   {side.axis: pos}, _q(rng.uniform(0, 359), 0.5), pattern)  # fmt: skip


@cache
def _letters() -> tuple[str, ...]:
    """The letters a generated line is drawn from: the font's that have ink (a space goes only within a line)."""
    from forge_spec.font import ADVANCES
    from forge_spec.problems import clean_text

    return tuple(
        sorted(ch for ch in ADVANCES if ink_box(ch, 1.0) is not None and clean_text(ch))
    )


def _text(rng: random.Random, k: int, host: str, face: _Flat) -> Feature:
    """A line of 1 to 8 letters engraved or embossed on a flat face, a capital 3 to 10 mm tall and no taller than a fifth of the face's narrower way."""
    # Mostly capitals and figures, as most lettering is; now and then any letter the font has.
    letters = (
        _letters()
        if rng.random() < 0.3
        else tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    )
    count = rng.randint(1, 8)
    words = "".join(rng.choice(letters) for _ in range(count))
    if count >= 3 and rng.random() < 0.3:  # a space within the line, never at its ends
        at = rng.randint(1, count - 2)
        words = words[:at] + " " + words[at + 1 :]
    narrow = min(face.half) if face.shape in ("rect", "profile") else face.half[0]
    height = _q(rng.uniform(3.0, max(3.0, min(10.0, 0.4 * narrow))))
    engraved = rng.random() < 0.6
    most = max(0.3, min(1.5, face.material - GAP - 0.1)) if engraved else 1.5
    depth = _q(rng.uniform(0.3, most))
    place = {axis: _position(rng, axis, (face.half[i] if face.shape in ("rect", "profile") else face.half[0]) * 0.3,
                             False) for i, axis in enumerate(face.axes)}  # fmt: skip
    return Feature(f"i{k}", "text", {"height": height, "depth": depth}, (host, face.key[2]), None,
                   {"mode": "engrave" if engraved else "emboss"}, None, place, words=words)  # fmt: skip


def _stud(rng: random.Random, k: int, host: str, face: _Flat) -> list[Feature]:
    """A threaded stud: a boss of a metric size standing on a flat face, and its thread (M3 to M12, coarse or now and then fine, either hand, over its whole height or part of it)."""
    size = rng.choice(sorted(COARSE, key=lambda m: float(m[1:])))
    fine = size in FINE and rng.random() < 0.25
    pitch = FINE[size] if fine else COARSE[size]
    height = _q(rng.uniform(max(4.0, 4 * pitch), 20.0))
    place = {axis: _position(rng, axis, (face.half[i] if face.shape in ("rect", "profile") else face.half[0]) * 0.3,
                             False) for i, axis in enumerate(face.axes)}  # fmt: skip
    boss = Feature(
        f"i{k}",
        "boss",
        {"diameter": float(size[1:]), "height": height},
        (host, face.key[2]),
        place=place,
    )
    length = (
        {} if rng.random() < 0.4 else {"length": _q(rng.uniform(3 * pitch, height))}
    )
    thread = Feature(f"i{k + 1}", "thread", length, None, None, {"hand": "right" if rng.random() < 0.75 else "left"},
                     words=f"{size}x{pitch:g}" if fine else size, of=boss.id)  # fmt: skip
    return [boss, thread]


def _lettering(rng: random.Random, k: int, host: str, face: _Flat) -> list[Feature]:
    return [_text(rng, k, host, face)]


#: How often a generated part is lettered (one line, on a face of any item that takes things), and how often it has a threaded stud.
_LETTERED = 0.3
_STUDDED = 0.2


def _decorate(seed: int, plan: list[Feature], tries: int) -> None:
    """Items drawn after a part's others, from a stream of their own (so a seed's other items stay as they were drawn): a line of letters, a threaded stud, now and then.

    Each is placed on the part as made, clear of what is there, and kept
    only if the part it makes is valid.
    """
    rng = random.Random(f"forge-eval decorations {seed}")
    turns = random.Random(f"forge-eval decorations turned {seed}")
    lettered, studded = rng.random() < _LETTERED, rng.random() < _STUDDED
    for wanted, draw in ((studded, _stud), (lettered, _lettering)):
        if not wanted:
            continue
        part = _build(tuple(plan), True)
        # Not on a turned item's far face: what goes there is drawn from a stream of its own (_onto_turned).
        hosts = sorted(key for key, face in part.flats.items() if key[1] == 0 and not face.turned)
        for _ in range(tries if hosts else 0):
            key = rng.choice(hosts)
            candidates = draw(rng, _next_index(plan), key[0], part.flats[key])
            # A line of letters turned in its face now and then: tried first, and where it doesn't fit, as drawn.
            turned = [_turned_now_and_then(turns, c, part.flats[key]) if draw is _lettering else None
                      for c in candidates]  # fmt: skip
            if any(t is not None for t in turned):
                chosen = [t or c for t, c in zip(turned, candidates, strict=True)]
                try:
                    render((*plan, *chosen))
                except DoesNotFitError:
                    pass
                else:
                    plan.extend(chosen)
                    break
            try:
                render((*plan, *candidates))
            except DoesNotFitError:
                continue
            plan.extend(candidates)
            break


def _next_index(plan: list[Feature]) -> int:
    """The number of the next item's id: one past the greatest drawn (``i0``, ``i1``, ...; some numbers drawn found no place)."""
    return 1 + max(
        (int(f.id[1:]) for f in plan if f.id[:1] == "i" and f.id[1:].isdigit()),
        default=-1,
    )


#: How often the first body is a tube, or a dome; how often an item is a rib, a cone, a tube or a sphere standing
#: on a flat face, or (when it is none of those) an extrusion or a revolution; how often a first body that can
#: be is hollowed.
_TUBES = 0.08
_DOMES = 0.04
_NEW_STANDING = 0.12
_PROFILED = 0.07
_SHELLED = 0.15
#: How often a single block or post standing on a rectangle stands flush with one of its sides, or two (a corner).
_FLUSH = 0.25
#: How often a single block standing on a rectangle (and not flush with it) overhangs one of its sides.
_OVERHUNG = 0.35
#: How often a single boss standing on a rectangle touches one of its sides, or two (in a corner).
_TANGENT = 0.15
#: How often what is drawn round a rod's side is a boss or a post standing round it, not a hole.
_AROUND = 0.35
#: How often an item that can be (a box, a rod, a plain hole or pocket on a flat face) has an edge set rounded.
_ROUNDED = 0.15


def generate(seed: int, size: int = 6, tries: int = 12) -> Case:
    """A valid random part of up to ``size`` items besides its first body (and, now and then, a line of letters), from ``seed``."""
    rng = random.Random(seed)
    first = _choose_first(rng)
    # Kinds stage 2 didn't draw, chosen from a stream of their own: a seed they don't choose stays as it was.
    other = random.Random(f"forge-eval first bodies {seed}")
    roll = other.random()
    if roll < _TUBES:
        first = _choose_tube(other)
    elif roll < _TUBES + _DOMES:
        first = _choose_dome(other)
    plan: list[Feature] = [first]
    # Its own roundings are made before its hollow (frame.md): drawn first, and a shell must agree with them.
    _round_now_and_then(seed, None, first, plan)
    hollowed = random.Random(f"forge-eval shells {seed}")
    # A block whose vertical edges are rounded or bevelled is hollowed half the time: its walls follow them.
    rounded = any(
        _draw(f.kind).rounds_edges and f.choices.get("which") == "vertical"
        for f in plan
    )
    if _draw(first.kind).openable and hollowed.random() < (
        0.5 if rounded else _SHELLED
    ):
        shell = _choose_shell(hollowed, first)
        try:
            render((*plan, shell))
            plan.append(shell)
        except DoesNotFitError:
            pass
    for k in range(size):
        part = _build(tuple(plan), True)
        slot = random.Random(f"forge-eval items {seed} {k}")
        new = slot.random() < _NEW_STANDING
        profiles = random.Random(f"forge-eval profiles {seed} {k}")
        flush = random.Random(f"forge-eval flush {seed} {k}")
        hang = random.Random(f"forge-eval overhang {seed} {k}")
        touch = random.Random(f"forge-eval tangent {seed} {k}")
        around = random.Random(f"forge-eval round standing {seed} {k}")
        turns = random.Random(f"forge-eval turns {seed} {k}")
        leans = random.Random(f"forge-eval leans {seed} {k}")
        onto = random.Random(f"forge-eval turned faces {seed} {k}")
        spells = random.Random(f"forge-eval own axes {seed} {k}")
        angling = random.Random(f"forge-eval round angles {seed} {k}")
        outlined = not new and profiles.random() < _PROFILED
        if _onto_turned(onto, k, plan, part, len(plan) < size):
            continue
        if _onto_ball(random.Random(f"forge-eval on balls {seed} {k}"), k, plan, part, len(plan) < size):
            continue
        if _onto_cone(random.Random(f"forge-eval on cones {seed} {k}"), k, plan, part, len(plan) < size):
            continue
        before = len(plan)
        for _ in range(tries):
            # A turned item's far face takes things from a stream of its own (_onto_turned): a seed whose items
            # turn nothing, or put nothing on such a face, stays as it was drawn.
            hosts = [key for key, face in part.flats.items() if key[1] == 0 and not face.turned] + [
                key for key in part.rounds if key[1] == 0
            ]
            if not hosts:  # a dome open underneath: nothing takes anything
                break
            key = rng.choice(hosts)
            standing_ok = _draw(part.kinds[key[0]]).hosts_standing and len(plan) < size
            turned = leaned = None
            if key in part.rounds:
                candidate = _side_hole(rng, k, key[0], part.rounds[key])
                if standing_ok and around.random() < _AROUND:
                    candidate = _side_standing(around, k, key[0], part.rounds[key])
                    # At any angle round it now and then, from a stream of its own (item 3b's first step): tried
                    # first, and where it doesn't fit, as drawn.
                    turned = _angled_now_and_then(angling, candidate)
            else:
                candidate = _feature(rng, k, key[0], part.flats[key], standing_ok)
                # Flush with a side, over one or touching one, it isn't turned: it is placed by that side.
                plain = True
                if (
                    _draw(candidate.kind).drawn_flush
                    and candidate.pattern is None
                    and part.flats[key].shape == "rect"
                    and flush.random() < _FLUSH
                ):
                    candidate = _flushed(flush, candidate, part.flats[key])
                    plain = False
                elif (
                    _draw(candidate.kind).drawn_overhung
                    and candidate.pattern is None
                    and part.flats[key].shape == "rect"
                    and hang.random() < _OVERHUNG
                ):
                    candidate = _overhung(hang, candidate, part.flats[key])
                    plain = False
                elif (
                    _draw(candidate.kind).drawn_tangent
                    and candidate.pattern is None
                    and part.flats[key].shape == "rect"
                    and touch.random() < _TANGENT
                ):
                    candidate = _flushed(touch, candidate, part.flats[key])
                    plain = False
                # Drawn as stage 2 would, then one of the new kinds in its place.
                if new and standing_ok:
                    candidate = _standing_new(slot, k, key[0], part.flats[key])
                    plain = True
                elif outlined and standing_ok:
                    candidate = _standing_profiled(profiles, k, key[0], part.flats[key])
                # Turned in its face now and then, from a stream of its own: tried first, and where it
                # doesn't fit, the item as drawn (a seed that turns nothing stays as it was drawn).
                if plain:
                    turned = _turned_now_and_then(turns, candidate, part.flats[key])
                    # Leaning on its face now and then, from a stream of its own (turned too, where it is): tried
                    # before the rest, and where it doesn't fit, as it would be without it.
                    leaned = _leaned_now_and_then(leans, turned or candidate, part.flats[key])
            if leaned is not None:
                try:
                    render((*plan, leaned))
                except DoesNotFitError:
                    leaned = None
                else:
                    plan.append(leaned)
                    _round_now_and_then(seed, k, leaned, plan)  # its far end's edges leaned with it (edges.md)
                    break
            if turned is not None:
                try:
                    render((*plan, turned))
                except DoesNotFitError:
                    turned = None
                else:
                    plan.append(turned)
                    _round_now_and_then(seed, k, turned, plan)  # its edges turned with it (edges.md)
                    break
            try:
                render((*plan, candidate))
            except DoesNotFitError:
                continue
            plan.append(candidate)
            _round_now_and_then(seed, k, candidate, plan)
            break
        _spelled_now_and_then(spells, plan, part)
        if len(plan) > before:
            _hollowed_now_and_then(seed, k, plan[before], plan, part)
    _decorate(seed, plan, tries)
    return render(tuple(plan))


#: How often a block just drawn standing on a face is hollowed (V2-stage4b-0c.md, step 5.1).
_STANDING_SHELLED = 0.5


def _hollowed_now_and_then(seed: int, k: int, body: Feature, plan: list[Feature], part: _Part) -> None:
    """Now and then a block just drawn standing on a face hollowed, upright or turned in it (V2-stage4b-0c.md, step
    5.1), from a stream of its own (a seed that hollows nothing standing stays as it was drawn): sealed or open on
    its far face; kept where the part it makes is valid."""
    rng = random.Random(f"forge-eval standing shells {seed} {k}")
    face = part.flats.get((body.on[0], 0, body.on[1])) if body.on is not None else None
    if face is None or rng.random() >= _STANDING_SHELLED:
        return
    drawn = _draw(body.kind).standing_shell(rng, body, _named(face.normal))
    if drawn is None:
        return
    shell = Feature(f"hollow{k}", "shell", drawn[0], of=body.id, faces=drawn[1])
    try:
        render((*plan, shell))
    except DoesNotFitError:
        return
    plan.append(shell)


# ----------------------------------------------------------------------
# A face's own axes, and a turned item's far face (place.md; V2-stage4b-0c.md 3.3, 1b's third move)
# ----------------------------------------------------------------------
#: How often the generator puts an item on a turned item's far face, where there is one, and turns it there too.
_ON_TURNED = 0.7
#: How often the generator names an item's face's axes by the face's own, u and v, where it may (any flat face).
_SPELLED = 0.04


#: How often the generator puts a hole, a boss or a post on a ball's or a dome's surface, where there is one (item 3b's
#: second step).
_ON_BALL = 0.6


def _onto_ball(rng: random.Random, k: int, plan: list[Feature], part: _Part, standing_ok: bool) -> bool:
    """Now and then, from a stream of its own, a hole, a boss or a post on a ball's or a dome's surface (item 3b's second
    step), where the part has one: at a latitude and an angle round its pole, or a circle of them. Whether one was added
    to the plan."""
    balls = [key for key in part.balls if key[1] == 0]
    if not balls or rng.random() >= _ON_BALL:
        return False
    key = rng.choice(balls)
    ball = part.balls[key]
    for _ in range(10):
        candidate = _ball_item(rng, k, key[0], ball, standing_ok)
        try:
            render((*plan, candidate))
        except DoesNotFitError:
            continue
        plan.append(candidate)
        return True
    return False


def _ball_item(rng: random.Random, k: int, host: str, ball: _Ball, standing_ok: bool) -> Feature:
    """A hole (blind), a boss or a post on a ball's surface, sized to it: at a latitude from just clear of where its
    surface ends up to its pole, at an angle round its pole on a half-degree grid; one copy, or (one in four) a circle
    of two to six."""
    r = ball.radius
    kind = rng.choice(_weighted("curved_weight", "curved_rank", None if standing_ok else (lambda e: e.cut_out)))
    sizes, depth, reach = _draw(kind).curved_sizes(rng, r)
    spread = math.degrees(fs.asin(min(reach / r, 1.0)))
    low = min(ball.lowest + spread + 3.0, 89.0)
    latitude = _q(rng.uniform(low, 90.0), 0.5)
    angle = _q(rng.uniform(0.0, 360.0), 0.5)
    pattern = None
    if latitude < 80.0 and rng.random() < 0.25:
        pattern = Pattern("circle", {}, {"count": rng.choice([2, 3, 4, 6])})
    return Feature(f"i{k}", kind, sizes, (host, "surface"), depth, {}, None, {}, angle, pattern, latitude=latitude)


#: How often the generator puts a hole, a boss or a post on a cone's side, where there is one (item 3b's third step).
_ON_CONE = 0.6


def _onto_cone(rng: random.Random, k: int, plan: list[Feature], part: _Part, standing_ok: bool) -> bool:
    """Now and then, from a stream of its own, a hole, a boss or a post on a cone's side (item 3b's third step), where
    the part has one: at an angle round it and a place along it, or a circle of them. Whether one was added to the
    plan."""
    cones = [key for key in part.cones if key[1] == 0]
    if not cones or rng.random() >= _ON_CONE:
        return False
    key = rng.choice(cones)
    cone = part.cones[key]
    for _ in range(10):
        candidate = _cone_item(rng, k, key[0], cone, standing_ok)
        if candidate is None:
            continue
        try:
            render((*plan, candidate))
        except DoesNotFitError:
            continue
        plan.append(candidate)
        return True
    return False


def _cone_item(rng: random.Random, k: int, host: str, cone: _Cone, standing_ok: bool) -> Feature | None:
    """A hole (blind), a boss or a post on a cone's side, sized to it where it goes: halfway along it, offset from its
    middle or measured from an end (to its centre or its edge), at an angle round it on a half-degree grid; one copy,
    or (one in four) a circle of two to six. None where the cone is too short or too narrow there."""
    axis = cone.axis
    roll = rng.random()
    along = rng.uniform(0.25, 0.75) * cone.length
    if roll < 0.25:
        place, along = {}, cone.length / 2
    elif roll < 0.85:
        place = {axis: Position("offset", _q(along - cone.length / 2, 0.5))}
        along = cone.length / 2 + place[axis].distance
    else:
        side = rng.choice("+-") + axis
        near = cone.length - along if side[0] == "+" else along
        place = {axis: Position("side", _q(near, 0.5), side, "centre")}
        along = cone.length - place[axis].distance if side[0] == "+" else place[axis].distance
    r = cone.radius_at(along)
    if r < 2.0 or not 0.0 < along < cone.length:
        return None
    kind = rng.choice(_weighted("curved_weight", "curved_rank", None if standing_ok else (lambda e: e.cut_out)))
    sizes, depth, _ = _draw(kind).curved_sizes(rng, r)
    angle = _q(rng.uniform(0.0, 360.0), 0.5)
    pattern = None
    if rng.random() < 0.25:
        pattern = Pattern("circle", {}, {"count": rng.choice([2, 3, 4, 6])})
    return Feature(f"i{k}", kind, sizes, (host, "side"), depth, {}, None, place, angle, pattern)


def _onto_turned(rng: random.Random, k: int, plan: list[Feature], part: _Part, standing_ok: bool) -> bool:
    """Now and then, from a stream of its own, an item on a turned item's far face (place.md, "A turned item's far
    face"): placed along the face's own axes, u and v, turned with it, and now and then turned or leaning there too.
    Whether one was added to the plan."""
    faces = [key for key, face in part.flats.items() if key[1] == 0 and face.turned]
    if not faces or rng.random() >= _ON_TURNED:
        return False
    key = rng.choice(faces)
    face = part.flats[key]
    standing_ok = standing_ok and _draw(part.kinds[key[0]]).hosts_standing
    for _ in range(10):
        candidate = replace(_feature(rng, k, key[0], face, standing_ok), own_axes=face.axes)
        for more in (_leaned_now_and_then(rng, candidate, face), _turned_now_and_then(rng, candidate, face), None):
            try:
                render((*plan, more or candidate))
            except DoesNotFitError:
                continue
            plan.append(more or candidate)
            return True
    return False


def _spelled_now_and_then(rng: random.Random, plan: list[Feature], part: _Part) -> None:
    """Now and then, from a stream of its own, the item just added named along its flat face's own axes, u and v
    (schema 1.4): the same part, said otherwise."""
    f = plan[-1]
    if f.on is None or f.own_axes is not None or rng.random() >= _SPELLED:
        return
    face = part.flats.get((f.on[0], 0, f.on[1]))
    if face is not None:
        plan[-1] = replace(f, own_axes=face.axes)


# ----------------------------------------------------------------------
# Impossible on purpose
# ----------------------------------------------------------------------
def impossible(seed: int) -> Case:
    """A valid part with one item made not to fit, and why: off its face, deeper than its material, or its copies overlapping."""
    rng = random.Random(seed)
    for attempt in range(40):
        case = generate(seed * 1000 + attempt, 4)
        cuts = [f for f in case.plan if _draw(f.kind).misfits and f.on is not None and f.pattern is None
                and f.on[1] not in ("side", "surface") and f.turn is None and f.tilt is None]  # fmt: skip
        if not cuts:
            continue
        f = rng.choice(cuts)
        part = _build(case.plan[: case.plan.index(f)], True)
        face = part.flats[(f.on[0], 0, f.on[1])]  # type: ignore[index]
        # Deeper than the material under it only where that is known to the millimetre: through to the face a
        # cut right through comes out on. Elsewhere the face's material is only how deep cuts are drawn (a
        # boss's far end round a tube's side, its height: the tube's wall is under it too, generated
        # part 870's impossible part, built).
        ways = ["off", "overlap"] if face.exit is None else ["off", "deep", "overlap"]
        how = rng.choice(ways)
        (h1, _), _ = _footprint(f, face.axes)
        if how == "off":
            room = face.half[0]
            broken = replace(
                f,
                place={
                    **f.place,
                    face.axes[0]: Position("offset", _q(room - h1 + 1.0)),
                },
            )
            why = "it runs off its face"
        elif how == "deep":
            broken = replace(f, depth=_q(face.material + 1.0))
            why = "it is deeper than the material under it"
        else:
            broken = replace(
                f, pattern=Pattern("row", {"pitch": _q(h1)}, {"count": 2}, face.axes[0])
            )
            why = "its copies overlap"
        plan = tuple(broken if g.id == f.id else g for g in case.plan)
        try:
            render(plan)
        except DoesNotFitError:
            loose = render(plan, strict=False)
            return Case(plan, loose.brief, loose.items, None, why)
    raise RuntimeError(f"no impossible part found from seed {seed}")


# ----------------------------------------------------------------------
# One leaf changed
# ----------------------------------------------------------------------
_LINEAR = (
    (0.5, 0.05),
    (3, 0.1),
    (6, 0.1),
    (30, 0.2),
    (120, 0.3),
    (400, 0.5),
    (1000, 0.8),
)
_ANGLES = ((10, 1.0), (50, 0.5), (120, 1 / 3), (400, 1 / 6), (math.inf, 1 / 12))


def _general(value: float) -> float:
    """ISO 2768-m's linear tolerance for a size (sizes.md), and 0.05 under 0.5 mm."""
    v = abs(value)
    if v < 0.5:
        return 0.05
    for bound, t in _LINEAR[1:]:
        if v <= bound:
            return t
    return 1.2


def _general_angle(side: float) -> float:
    for bound, t in _ANGLES:
        if side <= bound:
            return t
    return 1 / 12


def mutants(case: Case) -> Iterator[tuple[tuple[str, str], Case]]:
    """For every leaf field of every item, the part with that one value changed beyond its tolerance, where some change of it still makes a valid part.

    Each change is tried in turn (a size or a place moved three times its
    general tolerance and 0.3 mm more, one way, the other, then twice as
    far; a count one fewer, or one more; a choice the other way; an item on
    another face of its host; through made blind) until one makes a valid
    part. A pocket's shape isn't changed (a circle has a diameter where a
    rectangle has a length and width), nor a pitch along which a grid has
    one copy (it moves nothing).
    """
    for f in case.plan:
        for leaf, changes in _changes(f, case.plan):
            for changed in changes:
                plan = tuple(changed if g.id == f.id else g for g in case.plan)
                try:
                    made = render(plan)
                except DoesNotFitError:
                    continue
                yield (f.id, leaf), made
                break


def _by(value: float) -> list[float]:
    """How far to move a size: beyond its general tolerance, both ways, then twice as far."""
    by = 3 * _general(value) + 0.3
    return [by, -by, 2 * by, -2 * by]


def _changes(f: Feature, plan: Plan) -> Iterator[tuple[str, list[Feature]]]:
    """Each leaf of a feature, and the changes of it to try in turn (an outline: each of its sizes moved, one at a time)."""
    if f.outline is not None:
        shape, values = f.outline
        yield (
            "profile",
            [replace(f, outline=(shape, tuple((k, _q(v + d) if k == name else v) for k, v in values)))
             for name, value in values if value > 0 for d in _by(value)],
        )  # fmt: skip
    for name, value in f.sizes.items():
        yield (
            name,
            [replace(f, sizes={**f.sizes, name: _q(value + d)}) for d in _by(value)],
        )
    if f.depth is not None:
        yield "depth", [replace(f, depth=_q(f.depth + d)) for d in _by(f.depth)]
    elif _draw(f.kind).cut_out:
        below = _recess_depth(f) + GAP
        yield "depth", [replace(f, depth=_q(below + d)) for d in (0.5, 0.1)]
    if f.recess is not None:
        what, d, third = f.recess
        yield (
            f"{what}.diameter",
            [replace(f, recess=(what, _q(d + m), third)) for m in _by(d)],
        )
        if what == "counterbore":
            yield (
                f"{what}.depth",
                [replace(f, recess=(what, d, _q(third + m))) for m in _by(third)],
            )
        else:
            yield (
                f"{what}.angle",
                [
                    replace(f, recess=(what, d, _q(third + m, 0.5)))
                    for m in (8.0, -8.0, 16.0, -16.0)
                ],
            )
    if _draw(f.kind).rounds_edges:
        # Another of the edge sets of what it rounds (a joint's needs what it meets; so none goes to or from one).
        target = next(g for g in plan if g.id == f.of)
        sets = _draw(target.kind).roundable(target.on is None)
        current = f.choices["which"]
        yield (
            "edges",
            [
                replace(f, choices={"which": w})
                for w in sets
                if w not in (current, "joint") and current != "joint"
            ],
        )
    for name, choice in f.choices.items():
        if name == "shape" or _draw(f.kind).rounds_edges:
            continue
        others = {
            "ends": ["round", "square"],
            "end": ["round", "square"],
            "along": ["x", "y", "z"],
            "thickness_along": ["x", "y", "z"],
            "mode": ["engrave", "emboss"],
            "hand": ["right", "left"],
            "portion": ["whole", "upper_half"],
        }[name]
        yield (
            name,
            [replace(f, choices={**f.choices, name: o}) for o in others if o != choice],
        )
    yield from _draw(f.kind).own_changes(f, plan)
    if f.on is not None:
        host = next(g for g in plan if g.id == f.on[0])
        yield (
            "on",
            [
                replace(f, on=(host.id, face))
                for face in _faces_of(host)
                if face != f.on[1]
            ],
        )
    for axis, pos in f.place.items():
        if pos.mode in ("offset", "side"):
            moved = [
                replace(pos, distance=_q(pos.distance + d)) for d in _by(pos.distance)
            ]
        else:  # centred, said or assumed: moved off the centre
            moved = [Position("offset", _q(d)) for d in _by(0.0)]
        yield f"place.{axis}", [replace(f, place={**f.place, axis: m}) for m in moved]
    if f.turn is not None:
        # Turned a little more or less in its face, or a quarter turn (unless it is the same so turned).
        turned = [f.turn + d for d in (5.0, -5.0, 20.0, -20.0)]
        most = 360.0 if _draw(f.kind).turns_all_round else 180.0
        yield "place.turn", [replace(f, turn=_q(t, 0.5)) for t in turned if 0.0 < t < most]
    if f.tilt is not None:
        # Leaning a little more or less (within what Forge leans), or another way along the face's axes.
        tilt, towards = f.tilt
        more = [tilt + d for d in (5.0, -5.0, 15.0, -15.0)]
        yield "tilt", [replace(f, tilt=(_q(t, 0.5), towards)) for t in more if 0.0 < t <= _MOST_LEAN]
        ways = [("-" if towards[0] == "+" else "+") + towards[1], *(s + a for a in "xyz" if a != towards[1]
                                                                     for s in "+-")]  # fmt: skip
        yield "tilt_towards", [replace(f, tilt=(tilt, way)) for way in ways]
    if f.latitude is not None:
        # On a ball's surface: a little further up or down it, and a little further round its pole.
        yield "place.latitude", [replace(f, latitude=_q(f.latitude + d, 0.5)) for d in (8.0, -8.0, 16.0, -16.0)]
        yield "place.angle", [replace(f, angle=_q((f.angle or 0.0) + d, 0.5)) for d in (15.0, -15.0, 40.0, -40.0)]
    elif f.angle is not None:
        # A hole turned a little round its side; something standing round it, a quarter or a half.
        turned = _draw(f.kind).turned(f.angle)
        yield "place.angle", [replace(f, angle=_q(a, 0.5)) for a in turned]
    if f.pattern is not None:
        yield from _pattern_changes(f, f.pattern)


def _faces_of(f: Feature) -> tuple[str, ...]:
    """The faces of an item that may take things, by name (frame.md and each kind's page)."""
    return _draw(f.kind).faces_of(f)


def _pattern_changes(f: Feature, p: Pattern) -> Iterator[tuple[str, list[Feature]]]:
    prefix = f"place.pattern.{p.kind}"
    for name, value in p.values.items():
        if (
            _pattern_draw(p.kind).counted_per_axis
            and p.counts.get("count_" + name[len("pitch_") :], 2) == 1
        ):
            continue  # one copy along it: its pitch moves nothing
        if name == "start":
            changes = [_q(value + d, 0.5) for d in (6.0, -6.0, 12.0, -12.0)]
        else:
            changes = [_q(value + d) for d in _by(value)]
        yield (
            f"{prefix}.{name}",
            [
                replace(f, pattern=replace(p, values={**p.values, name: v}))
                for v in changes
            ],
        )
    for name, n in p.counts.items():
        counts = [m for m in (n - 1, n + 1) if m >= 1]
        yield (
            f"{prefix}.{name}",
            [
                replace(f, pattern=replace(p, counts={**p.counts, name: m}))
                for m in counts
            ],
        )
    if p.axis:
        yield (
            f"{prefix}.axis",
            [replace(f, pattern=replace(p, axis=a)) for a in "xyz" if a != p.axis],
        )
