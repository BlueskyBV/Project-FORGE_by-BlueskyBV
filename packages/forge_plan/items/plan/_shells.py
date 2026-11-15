"""Helpers the ``plan`` role's kinds and program share (a leaf: it imports neither the kinds' modules nor the program), moved at stage 4b.0b's step 3."""

from __future__ import annotations

import math
from collections.abc import Mapping

from forge_spec.draft import Faces, Item
from forge_spec.placement import Instance
from forge_spec.values import Value

from forge_plan.errors import GapError, PlanError
from forge_plan.items.plan._edges import Queries
from forge_plan.write import Chain, Done, RoundingOp, Vec, axis_of, length


class HollowGapError(GapError):
    """A hollow no construction is written for: where two walls of different thickness meet at a rounded edge."""


def _mm(item: Item, name: str) -> float:
    value = item.get(name)
    if not isinstance(value, Value):
        raise PlanError(f"its {name} is no size", item=item.id)
    return value.made_in("mm")


def _open(shell: Item) -> set[str]:
    opened = shell.get("open")
    return set(opened.faces) if isinstance(opened, Faces) else set()


def _walls(shell: Item, opposites: Mapping[str, str]) -> dict[str, float]:
    """Each face's wall: none where open, the floor opposite an open face, else the thickness."""
    t = _mm(shell, "thickness")
    floor = shell.get("floor")
    f = floor.made_in("mm") if isinstance(floor, Value) else t
    opened = _open(shell)
    return {
        d: 0.0 if d in opened else (f if opposites[d] in opened else t)
        for d in opposites
    }


def _inner(earlier: Done, t: float) -> float:
    """What a rounding of an edge between two walls ``t`` thick leaves on the hollow's edge under it."""
    return earlier.size - (2 - math.sqrt(2)) * t if earlier.bevel else earlier.size - t


def _span(
    centre: Vec, u: Vec, low: float, high: float, halves: Mapping[str, float]
) -> tuple[Vec, Vec]:
    up = axis_of(u)
    lo, hi = list(centre), list(centre)
    for axis, half in halves.items():
        k = "xyz".index(axis)
        lo[k], hi[k] = centre[k] - half, centre[k] + half
    k = "xyz".index(up)
    a, b = centre[k] + u[k] * low, centre[k] + u[k] * high
    lo[k], hi[k] = min(a, b), max(a, b)
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _round(chain: Chain, shell: Item, copy: Instance, tool: str, earlier: Done, size: float,
           queries: Queries, n: int) -> str:  # fmt: skip
    op, name = (
        (RoundingOp.CHAMFER, "distance")
        if earlier.bevel
        else (RoundingOp.FILLET, "radius")
    )
    step = chain.step(f"{shell.id}.{copy.index}.inner_{n}", op,
                      {name: length(size), "edges": {"queries": queries.found, "at_least": 1}},
                      item=shell.id, inputs=(tool,))  # fmt: skip
    return step


def _check_walls(shell: Item, pair: frozenset[str], walls: Mapping[str, float]) -> bool:
    """Whether the hollow follows a rounding of this edge: both its faces walls, of one thickness."""
    faces = sorted(pair)
    thick = [walls.get(f) for f in faces]
    if any(w is None for w in thick):
        return False
    if any(w == 0.0 for w in thick):
        return False  # a rim, rounded after the hollow
    if thick[0] != thick[1]:
        raise HollowGapError(f"its {faces[0]}-{faces[1]} edge is rounded where walls of different thickness meet "
                        "(shell.md: the hollow there is what the walls' distances leave)", item=shell.id)  # fmt: skip
    return True
