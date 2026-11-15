"""Points that tell the spec's shape from the shape another choice would make (for the ``on`` and ``choice`` kinds).

A choice (which face an item is on, round or square ends, cut in or
standing out, which edges are rounded, which faces a shell leaves open)
makes one shape where another choice would make another. The other
choice's shape is the oracle's for the spec with that one field changed,
placed by the judge's own placement; where it can't be made, it is no
alternative. Where the two shapes differ by more than the part may (a
clearance from both their surfaces, in both their forms), a point is inside
one and outside the other: it tells them apart.

The points are drawn round where the item's steps are in either shape
(from a seed fixed by the item and the field, so the checks are the same on
every run), and the ones that tell are spread out and kept.

Two shapes may differ only by less than the part may: a small tab's round
end and its square one, where every point between them is nearer a surface
than the tolerances allow. No point tells them, and that is said (the
choice is *untold*), never taken to mean the other choice makes the same
shape: the field is then held by face accounting, which holds every built
face to the spec's far more tightly.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace

import numpy as np
from forge_spec.draft import Item, PartSpec
from numpy.typing import NDArray

from .kinds.told import Tells
from .oracle import INNER, OUTER, CannotMakeError, Oracle, OracleError, oracle
from .place import PlaceError, place
from .view import Side

__all__ = ["Alternative", "Telling", "clearance_for", "tells"]

Array = NDArray[np.float64]

#: Points drawn round the item, for each other choice.
_DRAWN = 6000
#: Points kept that tell, at most, for each other choice.
_KEPT = 24


@dataclass(frozen=True)
class Alternative:
    """Another choice for one field of one item: its name (as the report says it) and the item as it would be."""

    name: str
    item: Item


@dataclass(frozen=True)
class Telling:
    """What the points found, for each other choice: the points that tell it from the spec's (``told``), or that its shape differs from the spec's by no more than the part may, so that no point can (``untold``, by name)."""

    told: tuple[Tells, ...]
    untold: tuple[str, ...] = ()


def _with(spec: PartSpec, item: Item) -> PartSpec:
    return replace(
        spec, items=tuple(item if i.id == item.id else i for i in spec.items)
    )


def _region(parts: Iterable[Oracle], item_id: str) -> tuple[Array, Array] | None:
    """The box round every step of the item in any of the shapes."""
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for part in parts:
        for step in part.steps:
            if step.item == item_id:
                lo = np.minimum(lo, step.lo)
                hi = np.maximum(hi, step.hi)
    if not (np.all(np.isfinite(lo)) and np.all(np.isfinite(hi))):
        return None
    return lo, hi


def _clear(part: Oracle, points: Array, clearance: float) -> NDArray[np.bool_]:
    """Whether each point is at least ``clearance`` from both forms' surfaces."""
    clear = np.ones(len(points), dtype=bool)
    for form in (INNER, OUTER):
        clear &= np.abs(part.bound(points, form, clearance)) >= clearance
    return clear


def _seed(item_id: str, field: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{item_id}/{field}".encode()).digest()[:8], "little"
    )


def _spread(points: Array, keep: int) -> NDArray[np.int64]:
    """Up to ``keep`` of the points, each the farthest from those already kept."""
    if len(points) <= keep:
        return np.arange(len(points))
    chosen = [0]
    gap = np.linalg.norm(points - points[0], axis=1)
    for _ in range(keep - 1):
        k = int(np.argmax(gap))
        chosen.append(k)
        gap = np.minimum(gap, np.linalg.norm(points - points[k], axis=1))
    return np.array(chosen, dtype=np.int64)


def tells(
    spec: PartSpec,
    part: Oracle,
    item: Item,
    field: str,
    alternatives: Iterable[Alternative],
    clearance: float,
) -> Telling:
    """For each other choice that can be made and makes a different shape, the points that tell the spec's from it; or that none can."""
    found: list[Tells] = []
    untold: list[str] = []
    rng = np.random.default_rng(_seed(item.id, field))
    for other in alternatives:
        changed = _with(spec, other.item)
        try:
            theirs = oracle(changed, place(changed))
        except (PlaceError, OracleError, CannotMakeError):
            continue
        region = _region((part, theirs), item.id)
        if region is None:
            continue
        lo, hi = region
        pad = 2 * clearance
        points = rng.uniform(lo - pad, hi + pad, size=(_DRAWN, 3))
        mine = part.classify(points)
        other_side = theirs.classify(points)
        sure = (np.isin(mine, (Side.IN, Side.OUT))) & (
            np.isin(other_side, (Side.IN, Side.OUT))
        )
        differ = np.flatnonzero(sure & (mine != other_side))
        if not len(differ):
            continue
        candidates = points[differ]
        clear = _clear(part, candidates, clearance) & _clear(
            theirs, candidates, clearance
        )
        candidates, sides = candidates[clear], mine[differ][clear]
        if not len(candidates):
            untold.append(other.name)
            continue
        kept = _spread(candidates, _KEPT)
        found.append(
            Tells(
                other.name,
                tuple(
                    (float(p[0]), float(p[1]), float(p[2])) for p in candidates[kept]
                ),
                tuple(int(s) for s in sides[kept]),
            )
        )
    return Telling(tuple(found), tuple(untold))


def clearance_for(bands: Iterable[float]) -> float:
    """How far from both shapes' surfaces a telling point must be: the widest tolerance band among the item's sizes (at least 0.1 mm), and 0.05 mm for the view."""
    return max([0.1, *bands]) + 0.05
