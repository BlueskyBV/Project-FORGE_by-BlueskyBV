"""Helpers the ``plan`` role's kinds and program share (a leaf: it imports neither the kinds' modules nor the program), moved at stage 4b.0b's step 3."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from forge_spec.draft import Choice, Item, Profile
from forge_spec.placement import Instance

from forge_plan.errors import PlanError
from forge_plan.write import Box, Chain, Done, Ref, Vec, add, num, ordered, unit

#: How far an extent's box is grown each way, beyond the build's own 1e-6 mm.
_EXTENT = 1e-5


@dataclass
class Queries:
    found: list[dict[str, Any]] = field(default_factory=list)

    def add(self, a: Sequence[Ref], b: Sequence[Ref], *, where: Mapping[str, Any],
            count: tuple[int, int]) -> None:  # fmt: skip
        if not a or not b:
            raise PlanError("an edge lies on a face the part has no name for")
        self.found.append({
            "between": [_faces(a), _faces(b)],
            "where": dict(where),
            "match": {"count": [count[0], count[1]]},
        })  # fmt: skip


def _faces(refs: Sequence[Ref]) -> Any:
    listed = [r.as_json() for r in sorted(set(refs))]
    return listed[0] if len(listed) == 1 else listed


def _vec(v: Sequence[float]) -> list[float]:
    return [num(c) for c in v]


def _within(lo: Sequence[float], hi: Sequence[float]) -> list[list[float]]:
    return [_vec([c - _EXTENT for c in lo]), _vec([c + _EXTENT for c in hi])]


def _crossing(
    chain: Chain, lo: Sequence[float], hi: Sequence[float], owner: tuple[str, int]
) -> int:
    """How many other tools' boxes meet an edge's box: each can split it once."""
    probe = Box((lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2]), "", -1)
    others = [b for b in (*chain.added, *chain.cut) if (b.item, b.copy) != owner]
    return sum(1 for b in others if probe.meets(b, by=_EXTENT))


def _count(
    chain: Chain, where: Mapping[str, Any], owner: tuple[str, int]
) -> tuple[int, int]:
    lo, hi = where["within"]
    crossing = _crossing(chain, lo, hi, owner)
    return (0 if crossing else 1, 1 + 2 * crossing)


def _profile(target: Item) -> Profile:
    profile = target.get("profile")
    if not isinstance(profile, Profile):
        raise PlanError("it has no outline", item=target.id)
    return profile


def _sides(
    profile: Profile,
) -> list[
    tuple[tuple[float, float], tuple[float, float], tuple[float, float] | None, bool]
]:
    """An outline's sides in turn: each from, to, its centre (None: straight) and whether it turns clockwise."""
    found = []
    here = profile.start
    for seg in profile.segments:
        found.append((here, seg.to, seg.centre, seg.clockwise))
        here = seg.to
    return found


def _tangent(side: tuple[tuple[float, float], tuple[float, float], tuple[float, float] | None, bool],
             at_end: bool) -> tuple[float, float]:  # fmt: skip
    a, b, centre, clockwise = side
    if centre is None:
        length = math.dist(a, b)
        return ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
    x = b if at_end else a
    dx, dy = x[0] - centre[0], x[1] - centre[1]
    r = math.hypot(dx, dy)
    return (dy / r, -dx / r) if clockwise else (-dy / r, dx / r)


def _arc_box(a: tuple[float, float], b: tuple[float, float], centre: tuple[float, float],
             clockwise: bool) -> tuple[tuple[float, float], tuple[float, float]]:  # fmt: skip
    """The box round an arc from ``a`` to ``b`` about ``centre``: its ends, and its circle's points furthest along each axis that it passes."""
    r = math.dist(a, centre)
    a0 = math.atan2(a[1] - centre[1], a[0] - centre[0])
    a1 = math.atan2(b[1] - centre[1], b[0] - centre[0])
    sweep = ((a0 - a1) if clockwise else (a1 - a0)) % (2 * math.pi)
    points = [a, b]
    for k in range(4):
        angle = k * math.pi / 2
        along = ((a0 - angle) if clockwise else (angle - a0)) % (2 * math.pi)
        if along <= sweep:
            points.append(
                (centre[0] + r * math.cos(angle), centre[1] + r * math.sin(angle))
            )
    return (min(p[0] for p in points), min(p[1] for p in points)), (
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _box_of(p: Vec, q: Vec) -> tuple[Vec, Vec]:
    return (min(p[0], q[0]), min(p[1], q[1]), min(p[2], q[2])), (
        max(p[0], q[0]),
        max(p[1], q[1]),
        max(p[2], q[2]),
    )


def _choice(item: Item, name: str) -> str | None:
    value = item.get(name)
    return value.value if isinstance(value, Choice) else None


def circle_where(centre: Vec, axis: Vec, radius: float) -> dict[str, Any]:
    spread = [radius * math.sqrt(max(1.0 - a * a, 0.0)) for a in axis]
    lo = [centre[i] - spread[i] for i in range(3)]
    hi = [centre[i] + spread[i] for i in range(3)]
    return {"kind": "circle", "axis": _vec(axis), "centre": _vec(centre), "radius_mm": num(radius),
            "within": _within(lo, hi)}  # fmt: skip


def _rims(chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
          open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
    """A round body's or boss's rims: each end's circle with its side (or a tube's bore)."""
    from forge_plan.items.plan import PLAN

    kind = target.kind
    entry = PLAN[kind]
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    o, u = copy.origin, copy.normal
    long = _mm(target, entry.rod_length)
    sets: Mapping[str, Sequence[tuple[str, str]]] = {
        "top": [("+end", "side")] + ([("+end", "bore")] if entry.bored else []),
        "bottom": [("-end", "side")] + ([("-end", "bore")] if entry.bored else []),
    }
    if which == "both":
        pairs = [*sets["top"], *sets["bottom"]]
    elif which == "outer":
        pairs = [("+end", "side"), ("-end", "side")]
    elif which == "bore":
        pairs = [("+end", "bore"), ("-end", "bore")]
    elif which in sets:
        pairs = list(sets[which])
    else:
        raise PlanError(f"a {kind} has no {which!r} edges", item=target.id)
    if part is not None:
        pairs = [p for p in pairs if bool(open_faces & set(p)) == (part == "after")]
    for end, side in pairs:
        at = add(o, u, long) if end == "+end" else o
        radius = entry.rim_radius(target, end, side)
        if radius <= 0.0:
            continue  # a point: no rim
        where = circle_where(at, u, radius)
        queries.add(
            names[end], names[side], where=where, count=_count(chain, where, key)
        )
        if end in open_faces and side == "side":
            hollow = chain.hollows.get(key)
            inner = names.get("inner side")
            if hollow is None or inner is None:
                raise PlanError(
                    f"its {end} is open, and the hollow's side has no name",
                    item=target.id,
                )
            where = circle_where(at, u, hollow.radius)
            queries.add(names[end], inner, where=where, count=_count(chain, where, key))
    return frozenset(frozenset(p) for p in pairs)


def _mm(item: Item, name: str) -> float:
    from forge_spec.values import Value

    value = item.get(name)
    if not isinstance(value, Value):
        raise PlanError(f"its {name} is no size", item=item.id)
    return value.made_in("mm")


def opposite(direction: str) -> str:
    return ("-" if direction[0] == "+" else "+") + direction[1]


def _line(lo: Vec, hi: Vec, f1: str, f2: str) -> tuple[int, Vec, Vec, Vec]:
    """The box's edge between faces ``f1`` and ``f2``: its axis, a point on it, and its segment's ends."""
    i1, i2 = "xyz".index(f1[1]), "xyz".index(f2[1])
    k = 3 - i1 - i2
    start, end = [0.0] * 3, [0.0] * 3
    for i, f in ((i1, f1), (i2, f2)):
        start[i] = end[i] = hi[i] if f[0] == "+" else lo[i]
    start[k], end[k] = lo[k], hi[k]
    return (
        k,
        (start[0], start[1], start[2]),
        (start[0], start[1], start[2]),
        (end[0], end[1], end[2]),
    )


def _line_where(lo: Vec, hi: Vec, f1: str, f2: str) -> dict[str, Any]:
    k, point, a, b = _line(lo, hi, f1, f2)
    axis = [0.0, 0.0, 0.0]
    axis[k] = 1.0
    box_lo = tuple(min(a[i], b[i]) for i in range(3))
    box_hi = tuple(max(a[i], b[i]) for i in range(3))
    return {
        "kind": "line",
        "axis": axis,
        "through": _vec(point),
        "within": _within(box_lo, box_hi),
    }


def followed(pairs: Sequence[tuple[str, str]], done: Sequence[Done],
             names: Mapping[str, Sequence[Ref]] | None = None) -> list[tuple[str, str, str, Done]]:  # fmt: skip
    """Where an earlier rounding of a corner meets a face whose edges are rounded now (edges.md): each (face, corner's two faces, the rounding)."""
    found: list[tuple[str, str, str, Done]] = []
    faces_now = {f for p in pairs for f in p}
    for earlier in done:
        for corner in ordered(earlier.pairs):
            if len(corner) != 2:
                continue
            c1, c2 = corner
            if names is not None and (c1 not in names or c2 not in names):
                continue
            if c1[1] == c2[1]:
                continue
            for face in sorted(faces_now - {c1, c2}):
                if face[1] in (c1[1], c2[1]):
                    continue
                if not ((face, c1) in pairs or (c1, face) in pairs) or not (
                        (face, c2) in pairs or (c2, face) in pairs):  # fmt: skip
                    continue
                found.append((face, c1, c2, earlier))
    return found


def box_queries(queries: Queries, lo: Vec, hi: Vec, pairs: Sequence[tuple[str, str]],
                names: Mapping[str, Sequence[Ref]], done: Sequence[Done],
                counted: Callable[[Mapping[str, Any]], tuple[int, int]]) -> None:  # fmt: skip
    """A box's edges, each between its two faces, and where an earlier rounding of a corner meets a face whose edges are rounded now, that corner's arc or bevel (edges.md)."""
    for f1, f2 in pairs:
        where = _line_where(lo, hi, f1, f2)
        queries.add(names[f1], names[f2], where=where, count=counted(where))
    for face, c1, c2, earlier in followed(pairs, done, names):
        where = _corner_where(lo, hi, face, c1, c2, earlier)
        queries.add(names[face], earlier.refs, where=where, count=counted(where))


def _corner_where(
    lo: Vec, hi: Vec, face: str, c1: str, c2: str, earlier: Done
) -> dict[str, Any]:
    """The arc (a rounded corner) or line (a bevelled one) where face ``face`` meets an earlier rounding of edge ``c1``-``c2``."""
    k = "xyz".index(face[1])
    plane = hi[k] if face[0] == "+" else lo[k]
    corner = [0.0, 0.0, 0.0]
    corner[k] = plane
    for c in (c1, c2):
        i = "xyz".index(c[1])
        corner[i] = hi[i] if c[0] == "+" else lo[i]
    s = earlier.size
    inward1 = [-v for v in unit(c1)]
    inward2 = [-v for v in unit(c2)]
    a = add(corner, inward1, s)
    b = add(corner, inward2, s)
    near = [min(a[i], b[i], corner[i]) for i in range(3)]
    far = [max(a[i], b[i], corner[i]) for i in range(3)]
    if earlier.bevel:  # the bevel's own line, across the corner: never one of the face's straight edges
        run = math.dist(a, b)
        across = [(b[i] - a[i]) / run for i in range(3)]
        return {
            "kind": "line",
            "axis": _vec(across),
            "through": _vec(a),
            "within": _within(near, far),
        }
    centre = add(add(corner, inward1, s), inward2, s)
    axis = [0.0, 0.0, 0.0]
    axis[k] = 1.0
    return {"kind": "circle", "axis": axis, "centre": _vec(centre), "radius_mm": num(s),
            "within": _within(near, far)}  # fmt: skip
