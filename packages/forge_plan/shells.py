"""A shell's hollow, as a tool taken from the part (docs/V2-stage4.md 4.8; docs/definitions/shell.md).

The hollow is every point of the body at least its wall's thickness from
each of its closed faces: each wall ``thickness`` thick, the floor (the wall
opposite an open face) ``floor`` thick, an open face no wall at all. The
body is made whole first, its own roundings and chamfers that border no
open face included, and the hollow follows them: where an edge is rounded by
``r`` between two walls both ``t`` thick, the points at least ``t`` from
both walls and from the rounding are those within ``r - t`` of its axis, so
the hollow's edge there is rounded by ``r - t`` (sharp where that is 0 or
less); a chamfer of ``c`` moved in by ``t`` meets the inner walls
``c - (2 - √2) t`` back from their corner. The hollow's own edges are
rounded in the order the body's were, so where its roundings meet they meet
as the body's do. Where the two walls of a rounded edge differ (a floor of
its own beside a rounded floor edge) the hollow is what the two distances
leave, not an offset of either: no construction is written for it
(:class:`HollowGapError`, a gap of the plan).
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from forge_spec.draft import Choice, Faces, Item
from forge_spec.placement import Instance
from forge_spec.schema import DIRECTIONS
from forge_spec.values import Value

from .edges import Queries, box_queries, circle_where, opposite
from .errors import GapError, PlanError
from .write import (
    Box,
    Chain,
    Done,
    Hollow,
    Ref,
    Vec,
    add,
    axis_of,
    length,
    ordered,
    role_of,
)

__all__ = ["HollowGapError", "hollow_tool"]


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
    op, name = ("chamfer", "distance") if earlier.bevel else ("fillet", "radius")
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


def hollow_tool(chain: Chain, shell: Item, body: Item, copy: Instance,
                cavity: tuple[Vec, Vec] | None) -> str:  # fmt: skip
    """One copy's hollow: a tool to take from the part, its inside faces named on the body."""
    if body.kind == "block":
        return _block(chain, shell, body, copy, cavity)
    if body.kind == "cylinder":
        return _cylinder(chain, shell, body, copy)
    if body.kind == "sphere":
        return _sphere(chain, shell, body, copy)
    raise PlanError(f"a {body.kind} can't be hollowed", item=shell.id)


def _block(
    chain: Chain,
    shell: Item,
    body: Item,
    copy: Instance,
    cavity: tuple[Vec, Vec] | None,
) -> str:
    if cavity is None:
        raise PlanError("the layout has no hollow for it", item=shell.id)
    key = (body.id, copy.index)
    t = _mm(shell, "thickness")
    walls = _walls(shell, {d: opposite(d) for d in DIRECTIONS})
    lo, hi = cavity
    box = f"{shell.id}.{copy.index}.hollow"
    tool = chain.box(box, lo, hi, item=shell.id)
    names: dict[str, tuple[Ref, ...]] = {d: (Ref(box, role_of(d)),) for d in DIRECTIONS}
    made: list[Done] = []
    for n, earlier in enumerate(chain.rounded.get(key, [])):
        size = _inner(earlier, t)
        pairs = [
            pair
            for pair in ordered(earlier.pairs)
            if _check_walls(shell, frozenset(pair), walls)
        ]
        if size <= 1e-9 or not pairs:
            continue
        queries = Queries()
        box_queries(
            queries, lo, hi, [(a, b) for a, b in pairs], names, made, lambda _w: (1, 1)
        )
        tool = _round(chain, shell, copy, tool, earlier, size, queries, n)
        made.append(
            Done(tool, earlier.bevel, size, frozenset(frozenset(p) for p in pairs))
        )
    for d in DIRECTIONS:
        if walls[d] > 0.0:
            chain.name(body.id, copy.index, f"inner {d}", *names[d])
    chain.hollows[key] = Hollow(lo, hi, rounded=tuple(made))
    chain.cut_box(Box(lo, hi, shell.id, copy.index))
    return tool


def _cylinder(chain: Chain, shell: Item, body: Item, copy: Instance) -> str:
    key = (body.id, copy.index)
    t = _mm(shell, "thickness")
    o, u = copy.origin, copy.normal
    walls = _walls(shell, {"+end": "-end", "-end": "+end"})
    walls["side"] = t
    radius = _mm(body, "diameter") / 2 - t
    start = add(o, u, walls["-end"])
    height = _mm(body, "length") - walls["-end"] - walls["+end"]
    step = f"{shell.id}.{copy.index}.hollow"
    tool = chain.cylinder(step, start, u, 2 * radius, height, item=shell.id)
    ends = {"+end": (Ref(step, "top"),), "-end": (Ref(step, "base"),)}
    for n, earlier in enumerate(chain.rounded.get(key, [])):
        size = _inner(earlier, t)
        queries = Queries()
        for pair in map(frozenset, ordered(earlier.pairs)):
            if "side" not in pair or not _check_walls(shell, pair, walls):
                continue
            end = next(f for f in pair if f != "side")
            at = add(start, u, height) if end == "+end" else start
            where = circle_where(at, u, radius)
            queries.add(ends[end], (Ref(step, "lateral"),), where=where, count=(1, 1))
        if size > 1e-9 and queries.found:
            tool = _round(chain, shell, copy, tool, earlier, size, queries, n)
    chain.name(body.id, copy.index, "inner side", Ref(step, "lateral"))
    for end, refs in ends.items():
        if walls[end] > 0.0:
            chain.name(body.id, copy.index, f"inner {end}", *refs)
    across = {a: radius for a in "xyz" if a != axis_of(u)}
    lo, hi = _span(start, u, 0.0, height, across)
    chain.hollows[key] = Hollow(lo, hi, radius)
    chain.cut_box(Box(lo, hi, shell.id, copy.index))
    return tool


def _sphere(chain: Chain, shell: Item, body: Item, copy: Instance) -> str:
    key = (body.id, copy.index)
    t = _mm(shell, "thickness")
    r = _mm(body, "diameter") / 2
    inner = r - t
    o, u = copy.origin, copy.normal
    ball = f"{shell.id}.{copy.index}.ball"
    portion = body.get("portion")
    if not (isinstance(portion, Choice) and portion.value == "upper_half"):
        centre = add(o, u, r) if copy.host is None else o
        tool = chain.sphere(ball, centre, 2 * inner, item=shell.id)
        chain.name(body.id, copy.index, "inner surface", Ref(ball, "surface"))
        lo = (centre[0] - inner, centre[1] - inner, centre[2] - inner)
        hi = (centre[0] + inner, centre[1] + inner, centre[2] + inner)
        chain.hollows[key] = Hollow(lo, hi, inner)
        chain.cut_box(Box(lo, hi, shell.id, copy.index))
        return tool
    # A dome's floor is its flat face's own wall (shell.md): ``floor`` thick, or ``thickness`` when none is given;
    # none where the flat face is left open. (No face across from it is ever open.)
    given = shell.get("floor")
    floor = (
        0.0
        if "-end" in _open(shell)
        else given.made_in("mm")
        if isinstance(given, Value)
        else t
    )
    walls = {"-end": floor, "surface": t}
    up = axis_of(u)
    flat = ("-" if u["xyz".index(up)] > 0 else "+") + up
    chain.sphere(ball, o, 2 * inner, item=shell.id)
    lo, hi = _span(o, u, floor, r, {a: r for a in "xyz" if a != up})
    above = f"{shell.id}.{copy.index}.above"
    chain.box(above, lo, hi, item=shell.id)
    tool = chain.boolean(
        f"{shell.id}.{copy.index}.hollow", "intersect", [ball, above], item=shell.id
    )
    chain.name(body.id, copy.index, "inner surface", Ref(ball, "surface"))
    if floor > 0.0:
        chain.name(body.id, copy.index, "inner -end", Ref(above, role_of(flat)))
    for n, earlier in enumerate(chain.rounded.get(key, [])):
        pair = frozenset({"-end", "surface"})
        if pair not in earlier.pairs or not _check_walls(shell, pair, walls):
            continue
        size = _inner(earlier, t)
        if size <= 1e-9:
            continue
        queries = Queries()
        rim = math.sqrt(max(inner * inner - floor * floor, 0.0))
        queries.add((Ref(above, role_of(flat)),), (Ref(ball, "surface"),),
                    where=circle_where(add(o, u, floor), u, rim), count=(1, 1))  # fmt: skip
        tool = _round(chain, shell, copy, tool, earlier, size, queries, n)
    hlo, hhi = _span(o, u, floor, inner, {a: inner for a in "xyz" if a != up})
    chain.hollows[key] = Hollow(hlo, hhi, inner)
    chain.cut_box(Box(hlo, hhi, shell.id, copy.index))
    return tool
