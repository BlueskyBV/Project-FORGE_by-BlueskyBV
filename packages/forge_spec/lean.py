"""Items leaning from square to their flat face: ``tilt`` and ``tilt_towards`` (schema 1.3; V2-stage4b-0c.md 3.3, 1b's second move).

A hole, a boss or a post on a flat face may lean ``tilt`` from square to it
(more than 0, at most :data:`MOST` degrees) towards ``tilt_towards``, one of
the face's two axes, + or -, turned with it where ``place.turn`` turns it.
Its **direction** is the face's outward normal turned that far towards that
way: a boss or a post stands out along it, its height along it; a hole's way
out of its mouth is along it, so the hole goes in against it, its depth
along it. Its cross-section (square to its direction) is what it is
unleaning; its **foot** on the face (what lies on the face, is held apart
from what else is there and is measured to an edge) is that cross-section's
section by the face's plane: drawn out along the lean by 1 / cos(tilt).

The material under a leaning item is measured along its direction, on a face
with the same material under all of it (a slab ``T`` thick): a blind cut of
radius ``r`` and depth ``D`` along its axis stays in it while
``D cos(tilt) + r sin(tilt) <= T``; one right through goes on until its
whole circle is past the far side, ``(T + r sin(tilt)) / cos(tilt)``, and
comes out there ``T tan(tilt)`` from its point, against the lean.

A round foot's section is an ellipse; Forge's outlines are lines and arcs,
so it is drawn as the polygon of :data:`SIDES` tangents round it, with the
four that touch it where it reaches farthest along the face's axes: no
point of the ellipse is outside it, and its box along the face's axes is
the ellipse's own, so a position measured to an edge is exact; elsewhere it
reaches past the ellipse by less than ``a (1 / cos(pi / SIDES) - 1)``, ``a``
the ellipse's longer half size (3 parts in 10,000 of it): what fits within
that of an edge or of something else is taken not to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from forge_numeric import scalar as fs

from .draft import Choice, Item, Place
from .geometry import Vec
from .items.solve._common import _turn, degrees
from .outline import Line, Shape
from .values import Value

__all__ = ["MOST", "SIDES", "Lean", "ellipse", "lean_of", "leaning"]

#: The most a lean may be, for now (degrees).
MOST = 75.0

#: The sides of the polygon an ellipse is drawn as.
SIDES = 128

Point = tuple[float, float]


@dataclass(frozen=True)
class Lean:
    """How an item leans on a flat face: ``tilt`` degrees (its cosine ``c`` and sine ``s``), towards ``way`` (a unit
    vector in the face's two coordinates); ``along_first``: whether the lean is along the item's own first axis
    (else its second), as turned with it."""

    tilt: float
    c: float
    s: float
    way: Point
    along_first: bool

    def direction(self, n: Vec, a1: Vec, a2: Vec) -> Vec:
        """Its direction in the part: the face's outward normal ``n`` turned ``tilt`` towards ``way`` (along ``a1`` and
        ``a2``, the face's axes)."""
        w1, w2 = self.way
        return tuple(self.c * n[k] + self.s * (w1 * a1[k] + w2 * a2[k]) + 0.0 for k in range(3))  # type: ignore[return-value]

    @property
    def stretch(self) -> float:
        """How much longer its foot is along the lean than its cross-section: 1 / cos(tilt)."""
        return 1.0 / self.c

    @property
    def tan(self) -> float:
        return self.s / self.c


def leaning(item: Item) -> bool:
    """Whether an item says it leans."""
    return isinstance(item.get("tilt"), Value)


def lean_of(item: Item, axes: tuple[str, str]) -> Lean | None:
    """How an item leans on a flat face with these axes; None if it doesn't, or its way isn't one of the face's axes
    (the solver reports that)."""
    tilt, towards = item.get("tilt"), item.get("tilt_towards")
    if not isinstance(tilt, Value) or not isinstance(towards, Choice):
        return None
    sign, axis = (1.0 if towards.value[0] == "+" else -1.0), towards.value[1]
    if axis not in axes:
        return None
    first = axis == axes[0]
    way = (sign, 0.0) if first else (0.0, sign)
    place = item.get("place")
    if isinstance(place, Place) and place.turn is not None:
        ct, st = _turn(degrees(place.turn))
        way = (ct * way[0] - st * way[1], st * way[0] + ct * way[1])
    t = degrees(tilt)
    c, s = _turn(t)
    return Lean(t, c, s, way, first)


def ellipse(a: float, b: float, way: Point, sides: int = SIDES) -> Shape:
    """The polygon round an ellipse about the origin, half size ``a`` along ``way`` (a unit vector) and ``b`` across it:
    its tangents at ``sides`` points evenly round it in its own parameter and at the four where it reaches farthest
    along each coordinate, each side between two that follow (the module's docstring)."""
    w1, w2 = way
    p1, p2 = -w2, w1  # across it, anticlockwise from it

    # A point at parameter t: a cos t along the way, b sin t across it. Its first coordinate is extreme where
    # -a sin t w1 + b cos t p1 = 0, its second where -a sin t w2 + b cos t p2 = 0.
    turns = [2.0 * math.pi * k / sides for k in range(sides)]
    for x, y in ((a * w1, b * p1), (a * w2, b * p2)):
        t = fs.atan2(y, x)
        turns += [t % (2.0 * math.pi), (t + math.pi) % (2.0 * math.pi)]
    turns.sort()
    kept = [t for k, t in enumerate(turns) if k == 0 or t - turns[k - 1] > 1e-9]
    if 2.0 * math.pi - kept[-1] + kept[0] <= 1e-9:
        kept.pop()
    corners = []
    for k, t in enumerate(kept):
        u = kept[(k + 1) % len(kept)] + (2.0 * math.pi if k + 1 == len(kept) else 0.0)
        m, d = (t + u) / 2.0, (u - t) / 2.0
        # Where the tangents at t and u meet: (a cos m, b sin m) / cos d in the ellipse's own frame.
        x, y = a * fs.cos(m) / fs.cos(d), b * fs.sin(m) / fs.cos(d)
        corners.append((x * w1 + y * p1, x * w2 + y * p2))
    return Shape(tuple(Line(corners[k], corners[(k + 1) % len(corners)]) for k in range(len(corners))))
