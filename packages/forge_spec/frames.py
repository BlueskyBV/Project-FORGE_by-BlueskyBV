"""The placement solver's frames: an origin and three axes, for a face, a round side or a placed copy (4b.0c item 1; V2-stage4b-0c.md, 3.3).

Each program keeps its own frame, made from the definitions
(docs/definitions/frame.md) and not from another program's (R2): this is the
solver's. A flat face's frame has its centre for origin, its first and
second axes ``u`` and ``v`` (the face's axes, frame.md's table) and its
outward normal ``n``; a round side's has the centre of the end its axis
starts from, ``n`` along the axis, and ``u`` and ``v`` the directions at 0
and 90 degrees round it. ``u x v`` is ``n`` on some faces and ``-n`` on
others, as the table gives them, so positions keep their signs.

A frame maps a point given in its own coordinates to the part's, and back.
An **aligned** frame, each of whose axes is one of the part's +-x, +-y, +-z,
is applied by choosing a coordinate and its sign, never by a product with 0
or 1, so its numbers are exactly those the axis names gave before frames (a
product would turn 0.0 into -0.0, which a digest sees). Any other frame is
applied by its products (item 1b's turned and tilted items).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

from forge_numeric import scalar as fs

__all__ = ["Frame", "Vec", "axis", "cos_sin", "name_of"]

Vec = tuple[float, float, float]

_INDEX = {"x": 0, "y": 1, "z": 2}


def axis(name: str) -> Vec:
    """The unit vector a direction names: ``"+x"``, ``"-z"``, or a bare ``"y"`` (its + way)."""
    sign = -1.0 if name[0] == "-" else 1.0
    found = [0.0, 0.0, 0.0]
    found[_INDEX[name[-1]]] = sign
    return (found[0], found[1], found[2])


def cos_sin(degrees: float) -> tuple[float, float]:
    """The cosine and sine of an angle in degrees, exact where they are 0 or 1.

    So copies a quarter turn apart sit exactly on the axes, not 1e-15 off them.
    """
    quarters = degrees / 90
    if abs(quarters - round(quarters)) < 1e-12:
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[round(quarters) % 4]
    t = math.radians(degrees)
    return fs.cos(t), fs.sin(t)


def _aligned(vector: Vec) -> tuple[int, bool] | None:
    """(which coordinate, whether it is the + way) of a vector that is exactly one of +-x, +-y, +-z; else None."""
    for k in range(3):
        if abs(vector[k]) == 1.0 and all(vector[j] == 0.0 for j in range(3) if j != k):
            return k, vector[k] > 0.0
    return None


def name_of(vector: Vec) -> str | None:
    """The direction an aligned unit vector names (``"+x"``), or None."""
    found = _aligned(vector)
    return None if found is None else ("+" if found[1] else "-") + "xyz"[found[0]]


@dataclass(frozen=True)
class Frame:
    """An origin and three unit axes ``u``, ``v``, ``n``, in the part's frame."""

    origin: Vec
    u: Vec
    v: Vec
    n: Vec

    @staticmethod
    def of_names(origin: Vec, u: str, v: str, n: str) -> Frame:
        """An aligned frame, its axes named as directions."""
        return Frame(origin, axis(u), axis(v), axis(n))

    @cached_property
    def _axes(
        self,
    ) -> tuple[tuple[int, bool], tuple[int, bool], tuple[int, bool]] | None:
        found = (_aligned(self.u), _aligned(self.v), _aligned(self.n))
        if found[0] is None or found[1] is None or found[2] is None:
            return None
        return found[0], found[1], found[2]

    @property
    def aligned(self) -> bool:
        """Whether every axis is one of the part's +-x, +-y, +-z."""
        return self._axes is not None

    def names(self) -> tuple[str, str, str] | None:
        """An aligned frame's axes as directions (``("+x", "+y", "+z")``); None for any other."""
        found = self._axes
        if found is None:
            return None
        return (
            ("+" if found[0][1] else "-") + "xyz"[found[0][0]],
            ("+" if found[1][1] else "-") + "xyz"[found[1][0]],
            ("+" if found[2][1] else "-") + "xyz"[found[2][0]],
        )

    def at(self, p1: float, p2: float, h: float | None = None) -> Vec:
        """The point at ``p1`` along ``u``, ``p2`` along ``v`` (and ``h`` along ``n``, when given) from the origin."""
        steps = ((p1, 0), (p2, 1)) if h is None else ((p1, 0), (p2, 1), (h, 2))
        found = list(self.origin)
        axes = self._axes
        if axes is not None:
            for p, j in steps:
                k, plus = axes[j]
                if plus:
                    found[k] += p
                else:
                    found[k] -= p
            return (found[0], found[1], found[2])
        vectors = (self.u, self.v, self.n)
        for p, j in steps:
            d = vectors[j]
            found = [found[k] + p * d[k] for k in range(3)]
        return (found[0], found[1], found[2])

    def on(self, point: Vec) -> tuple[float, float]:
        """Where ``point`` lies along ``u`` and ``v`` from the origin (seen along ``n``)."""
        axes = self._axes
        o = self.origin
        if axes is not None:
            (k1, plus1), (k2, plus2) = axes[0], axes[1]
            return (
                point[k1] - o[k1] if plus1 else o[k1] - point[k1],
                point[k2] - o[k2] if plus2 else o[k2] - point[k2],
            )
        d = (point[0] - o[0], point[1] - o[1], point[2] - o[2])
        return (
            d[0] * self.u[0] + d[1] * self.u[1] + d[2] * self.u[2],
            d[0] * self.v[0] + d[1] * self.v[1] + d[2] * self.v[2],
        )

    def across(self, vector: Vec) -> tuple[float, float, float]:
        """A direction's parts along ``u``, ``v`` and ``n``."""
        axes = self._axes
        if axes is not None:
            return (
                vector[axes[0][0]] if axes[0][1] else -vector[axes[0][0]],
                vector[axes[1][0]] if axes[1][1] else -vector[axes[1][0]],
                vector[axes[2][0]] if axes[2][1] else -vector[axes[2][0]],
            )
        return (
            vector[0] * self.u[0] + vector[1] * self.u[1] + vector[2] * self.u[2],
            vector[0] * self.v[0] + vector[1] * self.v[1] + vector[2] * self.v[2],
            vector[0] * self.n[0] + vector[1] * self.n[1] + vector[2] * self.n[2],
        )

    def turned(self, c: float, s: float) -> Frame:
        """The frame turned about its ``n`` by the angle whose cosine and sine are ``c`` and ``s``, ``u`` towards ``v``
        (a turned item's far face, schema 1.4): aligned again on a quarter turn."""
        return Frame(self.origin, self.radial(c, s), self.radial(-s, c), self.n)

    def radial(self, c: float, s: float) -> Vec:
        """``c u + s v``: round a side, the way out at the angle whose cosine and sine are ``c`` and ``s``."""
        axes = self._axes
        if axes is not None:
            found = [0.0, 0.0, 0.0]
            (k1, plus1), (k2, plus2) = axes[0], axes[1]
            found[k1] = c if plus1 else -c
            found[k2] = s if plus2 else -s
            return (found[0], found[1], found[2])
        return (
            c * self.u[0] + s * self.v[0],
            c * self.u[1] + s * self.v[1],
            c * self.u[2] + s * self.v[2],
        )
