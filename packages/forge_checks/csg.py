"""Solids made of solids: unions, intersections and differences of the exact solids (forge_checks.shapes).

The oracle's steps (:mod:`forge_checks.oracle`) and the roundings
(:mod:`forge_checks.rounds`) are made of these.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from .shapes import Local, Solid

__all__ = ["Inter", "Minus", "Node", "Union", "bound", "box", "leaves", "toward"]

Array = NDArray[np.float64]
Vec = tuple[float, float, float]


# ----------------------------------------------------------------------
# Solids made of solids
# ----------------------------------------------------------------------
# Each keeps the box round it, as a solid does (``lo``, ``hi``): a union's
# holds its parts' boxes, an intersection's is where they all overlap (it may
# be empty: lo above hi), a difference's is its whole's.
@dataclass(frozen=True)
class Union:
    parts: tuple[Node, ...]
    lo: Vec = field(init=False, repr=False, compare=False)
    hi: Vec = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.parts:
            raise ValueError("a union is of something")
        los, his = [p.lo for p in self.parts], [p.hi for p in self.parts]
        object.__setattr__(self, "lo", _corner(min, los))
        object.__setattr__(self, "hi", _corner(max, his))


@dataclass(frozen=True)
class Inter:
    parts: tuple[Node, ...]
    lo: Vec = field(init=False, repr=False, compare=False)
    hi: Vec = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.parts:
            raise ValueError("an intersection is of something")
        los, his = [p.lo for p in self.parts], [p.hi for p in self.parts]
        object.__setattr__(self, "lo", _corner(max, los))
        object.__setattr__(self, "hi", _corner(min, his))


@dataclass(frozen=True)
class Minus:
    whole: Node
    less: Node
    lo: Vec = field(init=False, repr=False, compare=False)
    hi: Vec = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "lo", self.whole.lo)
        object.__setattr__(self, "hi", self.whole.hi)


Node = Solid | Union | Inter | Minus


def _corner(pick: Callable[[Iterable[float]], float], corners: list[Vec]) -> Vec:
    return (
        pick(c[0] for c in corners),
        pick(c[1] for c in corners),
        pick(c[2] for c in corners),
    )


def bound(node: Node, points: Array, enough: float = math.inf) -> Array:
    """A signed distance whose sign is exact and whose size is at most the distance to the surface.

    A solid's own is exact; a union's is the least of its parts', an
    intersection's the greatest, a difference's the greater of its whole's
    and its part taken away's, negated (each 1-Lipschitz, like its parts).

    With ``enough``, a node whose box is more than that from a point is not
    asked there: its value is the distance to its box (the node is within
    its box, so the point is outside it by at least that much). The answer
    is still such a bound, its sign exact and its size at most the distance
    to the surface, but no longer 1-Lipschitz; and a point within
    ``enough`` of the surface has a value within ``enough``, as any such
    bound does.
    """
    if math.isinf(enough):
        return _bound(node, points)
    return _bound_near(node, points, enough)


def _bound(node: Node, points: Array) -> Array:
    if isinstance(node, Solid):
        return node.signed_distance(points)
    if isinstance(node, Union):
        return np.asarray(np.minimum.reduce([_bound(p, points) for p in node.parts]))
    if isinstance(node, Inter):
        return np.asarray(np.maximum.reduce([_bound(p, points) for p in node.parts]))
    return np.maximum(_bound(node.whole, points), -_bound(node.less, points))


def _bound_near(node: Node, points: Array, enough: float) -> Array:
    lo, hi = np.asarray(node.lo), np.asarray(node.hi)
    out = np.maximum(np.maximum(lo - points, points - hi), 0.0)
    gap: Array = np.sqrt((out * out).sum(axis=1))
    near = np.flatnonzero(gap <= enough)
    if len(near) == len(points):
        return _bound_inside(node, points, enough)
    if len(near):
        gap[near] = _bound_inside(node, points[near], enough)
    return gap


def _bound_inside(node: Node, points: Array, enough: float) -> Array:
    if isinstance(node, Solid):
        return node.signed_distance(points)
    if isinstance(node, Union):
        return np.asarray(
            np.minimum.reduce([_bound_near(p, points, enough) for p in node.parts])
        )
    if isinstance(node, Inter):
        return np.asarray(
            np.maximum.reduce([_bound_near(p, points, enough) for p in node.parts])
        )
    return np.maximum(
        _bound_near(node.whole, points, enough), -_bound_near(node.less, points, enough)
    )


def box(node: Node) -> tuple[Vec, Vec]:
    """The box round a node (finite for every node a step makes)."""
    return node.lo, node.hi


def toward(node: Node, models: Iterator[Local], directions: Array) -> NDArray[np.bool_]:
    """Whether the node holds the points just off a point along each direction, from its leaves' models there (in order)."""
    if isinstance(node, Solid):
        return next(models).toward(directions)
    if isinstance(node, Union):
        found = np.zeros(len(directions), dtype=bool)
        for p in node.parts:
            found |= toward(p, models, directions)
        return found
    if isinstance(node, Inter):
        found = np.ones(len(directions), dtype=bool)
        for p in node.parts:
            found &= toward(p, models, directions)
        return found
    whole = toward(node.whole, models, directions)
    return whole & ~toward(node.less, models, directions)


def toward_all(node: Node, held: Iterator[NDArray[np.bool_]]) -> NDArray[np.bool_]:
    """:func:`toward` for many points and directions at once: from each leaf's answer (in order), arrays of one shape."""
    if isinstance(node, Solid):
        return next(held)
    if isinstance(node, (Union, Inter)):
        parts = [toward_all(p, held) for p in node.parts]
        found: NDArray[np.bool_] = parts[0].copy()
        for part in parts[1:]:
            found = found | part if isinstance(node, Union) else found & part
        return found
    whole = toward_all(node.whole, held)
    return whole & ~toward_all(node.less, held)


#: The most boxes :func:`pieces` keeps for one node before it takes the node's own box instead.
_MOST_PIECES = 256

_Boxes = list[tuple[Vec, Vec]]


def pieces(node: Node) -> _Boxes:
    """Boxes that hold every point of the node's surface, each round a piece of one of its solids' surfaces.

    A solid's surface counts only where the rest of the node lets it be the
    node's: within an intersection, where each other part may be (its
    pieces' boxes); a difference's taken part, where its whole may be. A
    node whose pieces would be more than :data:`_MOST_PIECES` is held by its
    own box.
    """
    return _surface(node)


def _cut(a: tuple[Vec, Vec], b: tuple[Vec, Vec]) -> tuple[Vec, Vec] | None:
    """The common part of two boxes; None where they don't meet."""
    lo = (max(a[0][0], b[0][0]), max(a[0][1], b[0][1]), max(a[0][2], b[0][2]))
    hi = (min(a[1][0], b[1][0]), min(a[1][1], b[1][1]), min(a[1][2], b[1][2]))
    return None if any(x > y for x, y in zip(lo, hi, strict=True)) else (lo, hi)


def _cuts(these: _Boxes, those: _Boxes) -> _Boxes:
    return [c for a in these for b in those if (c := _cut(a, b)) is not None]


def _held(node: Node, found: _Boxes) -> _Boxes:
    """``found``, or the node's own box where they are too many."""
    return found if len(found) <= _MOST_PIECES else [(node.lo, node.hi)]


def _region(node: Node) -> _Boxes:
    """Boxes that hold all of the node (its material)."""
    if isinstance(node, Solid):
        return [(node.lo, node.hi)]
    if isinstance(node, Union):
        return _held(node, [b for p in node.parts for b in _region(p)])
    if isinstance(node, Inter):
        found = _region(node.parts[0])
        for p in node.parts[1:]:
            found = _held(node, _cuts(found, _region(p)))
        return found
    return _region(node.whole)


def _surface(node: Node) -> _Boxes:
    if isinstance(node, Solid):
        return [(node.lo, node.hi)]
    if isinstance(node, Union):
        return _held(node, [b for p in node.parts for b in _surface(p)])
    if isinstance(node, Inter):
        found: _Boxes = []
        for k, p in enumerate(node.parts):
            others = node.parts[:k] + node.parts[k + 1 :]
            where = _region(Inter(others)) if len(others) > 1 else _region(others[0])
            found += _cuts(_surface(p), where)
        return _held(node, found)
    return _held(
        node, _surface(node.whole) + _cuts(_surface(node.less), _region(node.whole))
    )


def leaves(node: Node) -> Iterator[Solid]:
    """The solids a node is made of."""
    if isinstance(node, Solid):
        yield node
    elif isinstance(node, (Union, Inter)):
        for p in node.parts:
            yield from leaves(p)
    else:
        yield from leaves(node.whole)
        yield from leaves(node.less)
