"""The edges a rounding or chamfer names, as references the build resolves (docs/V2-stage4.md 4.7).

Written from docs/definitions/edges.md and each kind's page, on its own: the
solver's ``edges_of`` covers bodies only (for its order) and the judge's
edge sets are the judge's. Each edge of an edge set, on each copy of the
item it rounds, becomes one query:

- **between** the two faces it lies between, each as the chain names it
  (:mod:`forge_plan.write`: the steps that made the face, by its plane);
- held by **where** to the line or circle it lies on (a line's direction and
  a point on it; a circle's axis, centre and radius) and to its **extent**,
  the box of the segment or arc the spec's edge is: a piece the build finds
  there that runs on past it (onto an item joined flush) is an error, never
  quietly taken;
- matching **0 to n** pieces (an edge another item cut across is still one
  edge, every piece of it rounded; one taken away has none), the list as a
  whole at least one.

Where an earlier rounding of the same item has rounded a face's corners,
an edge set running round that face follows its edge as the rounding left
it (edges.md): the arcs or bevels at those corners are named too, so the
tangent closure the build makes adds nothing unnamed.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from forge_spec.draft import Choice, EdgeSet, Faces, Item, Profile
from forge_spec.geometry import FlatFace, SideFace
from forge_spec.outline import Shape, turned_extremes, turned_rims
from forge_spec.placement import Instance
from forge_spec.schema import DIRECTIONS

from .errors import GapError, PlanError
from .write import (
    DATUMS,
    PLANE_AXES,
    Box,
    Chain,
    Done,
    Ref,
    Vec,
    add,
    axis_of,
    num,
    ordered,
    unit,
)

__all__ = [
    "Queries",
    "box_pairs",
    "box_queries",
    "circle_where",
    "edge_reference",
    "opposite",
    "pairs_for",
]

#: The faces that are round: a cut's rim on one, or a joint on one, is a curve, not in one plane.
_ROUND = ("side", "bore", "inner side", "surface")

#: How far an extent's box is grown each way, beyond the build's own 1e-6 mm.
_EXTENT = 1e-5


def opposite(direction: str) -> str:
    return ("-" if direction[0] == "+" else "+") + direction[1]


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


# ----------------------------------------------------------------------
# Edge sets of box-like items, by their two faces
# ----------------------------------------------------------------------
def box_pairs(kind: str, which: str, up: str) -> list[tuple[str, str]]:
    """The edges a box-like item's edge set names, each by the two faces it lies between (block.md, post.md, rib.md, tab.md)."""
    down = opposite(up)
    sides = [d for d in DIRECTIONS if d[1] != up[1]]
    vertical = [
        (a, b) for n, a in enumerate(sides) for b in sides[n + 1 :] if a[1] != b[1]
    ]
    sets: dict[str, list[tuple[str, str]]] = {
        "vertical": vertical,
        "top": [(up, s) for s in sides],
    }
    if kind == "block":
        sets["bottom"] = [(down, s) for s in sides]
        sets["all"] = sets["vertical"] + sets["top"] + sets["bottom"]
    if which not in sets:
        raise PlanError(f"a {kind} has no {which!r} edges")
    return sets[which]


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


# ----------------------------------------------------------------------
# The reference
# ----------------------------------------------------------------------
def pairs_for(item: Item, copy: Instance, which: str) -> list[tuple[str, str]]:
    up = _up(copy)
    return box_pairs(item.kind, which, up)


def _up(copy: Instance) -> str:
    axis = axis_of(copy.normal)
    return ("+" if copy.normal["xyz".index(axis)] > 0 else "-") + axis


def edge_reference(chain: Chain, rounding: Item, *, items: Mapping[str, Item],
                   copies: Mapping[str, Sequence[Instance]], shells: Mapping[str, Item],
                   part: str | None,
                   faces: Mapping[tuple[str, int], Mapping[str, FlatFace | SideFace]] | None = None,
                   ) -> tuple[dict[str, Any], dict[tuple[str, int], frozenset[frozenset[str]]]]:  # fmt: skip
    """The reference of a rounding's edges, and on each copy of the item it rounds, which edges (by their faces) it names.

    ``part`` is ``"before"`` or ``"after"`` for a rounding of a hollowed
    body made in two places (frame.md): the edges bordering no open face,
    or those bordering one; None for the rest.
    """
    edges = rounding.get("edges")
    if not isinstance(edges, EdgeSet):
        raise PlanError("a rounding names its edges", item=rounding.id)
    target = items.get(edges.of)
    if target is None:
        raise PlanError(
            f"it rounds {edges.of!r}, which the spec hasn't", item=rounding.id
        )
    queries = Queries()
    named: dict[tuple[str, int], frozenset[frozenset[str]]] = {}
    if edges.which == "joint":
        meets = items.get(edges.where_meets or "")
        if meets is None:
            raise PlanError("a joint is where the item meets another", item=rounding.id)
        _joint(chain, queries, target, meets, copies, faces or {})
    elif target.kind in ("hole", "slot", "pocket"):
        _cut_rims(chain, queries, target, edges.which, copies[target.id])
    else:
        for copy in copies[target.id]:
            named[(target.id, copy.index)] = _own(chain, queries, target, copy, edges.which,
                                                  shells.get(target.id), part)  # fmt: skip
    if not queries.found:
        raise PlanError("it names no edge the part has", item=rounding.id)
    return {"queries": queries.found, "at_least": 1}, named


def _open_faces(shell: Item | None) -> set[str]:
    if shell is None:
        return set()
    opened = shell.get("open")
    return set(opened.faces) if isinstance(opened, Faces) else set()


def _own(chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
         shell: Item | None, part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
    """An item's own edges (not a joint): a box-like item's, a round item's rims, a dome's, a round tab's."""
    names = chain.names_of(target.id, copy.index)
    key = (target.id, copy.index)
    kind = target.kind
    open_faces = _open_faces(shell)
    if kind in ("block", "post", "rib") or (
        kind == "tab" and _choice(target, "end") != "round"
    ):
        box = _box(chain, key)
        pairs = pairs_for(target, copy, which)
        if part is not None:
            pairs = [p for p in pairs if bool(open_faces & set(p)) == (part == "after")]
        counted = lambda where: _count(chain, where, key)  # noqa: E731
        box_queries(
            queries, box.lo, box.hi, pairs, names, chain.rounded.get(key, []), counted
        )
        if open_faces and key in chain.hollows:
            _inner_rims(chain, queries, target, copy, pairs, open_faces)
        return frozenset(frozenset(p) for p in pairs)
    if kind == "tab":
        return _round_tab(chain, queries, target, copy, which)
    if kind in ("cylinder", "boss", "cone", "tube"):
        return _rims(chain, queries, target, copy, which, open_faces, part)
    if kind == "sphere":
        return _dome(chain, queries, target, copy, which, open_faces, part)
    if kind == "extrusion":
        return _extrusion_edges(chain, queries, target, copy, which)
    if kind == "revolution":
        return _turned_rims(chain, queries, target, copy, which)
    raise PlanError(f"a {kind}'s edges aren't compiled", item=target.id)


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


def _extrusion_edges(chain: Chain, queries: Queries, target: Item, copy: Instance,
                     which: str) -> frozenset[frozenset[str]]:  # fmt: skip
    """An extrusion's edges (extrusion.md): round each end, a line or an arc's circle for each side of its outline; along its axis, a line at each corner where two sides meet at an angle."""
    if which not in ("top", "bottom", "vertical", "all"):
        raise PlanError(f"an extrusion has no {which!r} edges", item=target.id)
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    o, u = copy.origin, copy.normal
    # Its outline's axes: the face's it stands on, or (the first body) its -end plane's.
    a1, a2 = (
        unit("+" + a) for a in (copy.face_axes or PLANE_AXES[DATUMS[axis_of(u)][0]])
    )
    length = _mm(target, "length")
    sides = _sides(_profile(target))

    def world(p: tuple[float, float], height: float) -> Vec:
        return add(add(add(o, a1, p[0]), a2, p[1]), u, height)

    pairs: list[tuple[str, str]] = []
    for end, height in (("+end", length), ("-end", 0.0)):
        if which not in ({"+end": "top", "-end": "bottom"}[end], "all"):
            continue
        pairs.append((end, "side"))
        for a, b, centre, clockwise in sides:
            if centre is None:
                start, stop = world(a, height), world(b, height)
                run = math.dist(a, b)
                where = {"kind": "line", "axis": _vec([(stop[i] - start[i]) / run for i in range(3)]),
                         "through": _vec(start), "within": _within(*_box_of(start, stop))}  # fmt: skip
            else:
                (l1, l2), (h1, h2) = _arc_box(a, b, centre, clockwise)
                where = {**circle_where(world(centre, height), u, math.dist(a, centre)),
                         "within": _within(*_box_of(world((l1, l2), height), world((h1, h2), height)))}  # fmt: skip
            queries.add(
                names[end], names["side"], where=where, count=_count(chain, where, key)
            )
    if which in ("vertical", "all"):
        pairs.append(("side", "side"))
        for k, side in enumerate(sides):
            after = sides[(k + 1) % len(sides)]
            t_in, t_out = _tangent(side, True), _tangent(after, False)
            if t_in[0] * t_out[0] + t_in[1] * t_out[1] > 1.0 - 1e-9:
                continue  # they run on smoothly: no edge
            foot, top = world(side[1], 0.0), world(side[1], length)
            where = {
                "kind": "line",
                "axis": _vec(u),
                "through": _vec(foot),
                "within": _within(*_box_of(foot, top)),
            }
            queries.add(
                names["side"],
                names["side"],
                where=where,
                count=_count(chain, where, key),
            )
    return frozenset(frozenset(p) for p in pairs)


def _box_of(p: Vec, q: Vec) -> tuple[Vec, Vec]:
    return (min(p[0], q[0]), min(p[1], q[1]), min(p[2], q[2])), (
        max(p[0], q[0]),
        max(p[1], q[1]),
        max(p[2], q[2]),
    )


def _turned_rims(chain: Chain, queries: Queries, target: Item, copy: Instance,
                 which: str) -> frozenset[frozenset[str]]:  # fmt: skip
    """A revolution's rims (revolution.md): round each flat end, a circle where it meets the side next to it at an angle, off the axis."""
    ends = {"top": ["+end"], "bottom": ["-end"]}.get(which)
    if ends is None:
        raise PlanError(f"a revolution has no {which!r} edges", item=target.id)
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    o, u = copy.origin, copy.normal
    shape = Shape.of_profile(_profile(target))
    for end in ends:
        found, rims = (
            turned_extremes(shape, end == "+end"),
            turned_rims(shape, end == "+end"),
        )
        if found is None or rims is None or end not in names:
            raise PlanError(f"it has no flat {end}: no edges there", item=target.id)
        if not rims:
            raise PlanError(
                f"its side runs on smoothly into its {end}: no edges there",
                item=target.id,
            )
        for radius in rims:  # a rim the side runs on smoothly into is no edge
            where = circle_where(add(o, u, found[0]), u, radius)
            queries.add(
                names[end], names["side"], where=where, count=_count(chain, where, key)
            )
    return frozenset(frozenset((end, "side")) for end in ends)


def _choice(item: Item, name: str) -> str | None:
    value = item.get(name)
    return value.value if isinstance(value, Choice) else None


def _box(chain: Chain, key: tuple[str, int]) -> Box:
    for box in chain.added:
        if (box.item, box.copy) == key:
            return box
    raise PlanError(f"{key[0]}#{key[1]} has no box in the part")


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


def _inner_rims(chain: Chain, queries: Queries, target: Item, copy: Instance,
                pairs: Sequence[tuple[str, str]], open_faces: set[str]) -> None:  # fmt: skip
    """A rim's inside edges: where an open face's ring meets the hollow's walls, round the hollow's own corners (shell.md, edges.md)."""
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    hollow = chain.hollows.get(key)
    if hollow is None:
        raise PlanError("an open face's rim, and no hollow", item=target.id)
    outer = _box(chain, key)
    for f1, f2 in pairs:
        if {f1, f2} <= open_faces or not open_faces & {f1, f2}:
            continue
        opened, side = (f1, f2) if f1 in open_faces else (f2, f1)
        inner = names.get(f"inner {side}")
        if inner is None:
            raise PlanError(
                f"its {opened} is open, and the hollow's {side} wall has no name",
                item=target.id,
            )
        lo, hi = list(hollow.lo), list(hollow.hi)
        k = "xyz".index(opened[1])
        lo[k] = hi[k] = outer.hi[k] if opened[0] == "+" else outer.lo[k]
        box_queries(queries, (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2]), [(opened, side)],
                    {opened: names[opened], side: inner}, (), lambda w: _count(chain, w, key))  # fmt: skip
    # The hollow's own rounded corners, where its walls meet, round the ring's inside too.
    rims = [
        (f1, f2)
        for f1, f2 in pairs
        if open_faces & {f1, f2} and not {f1, f2} <= open_faces
    ]
    for opened in sorted({f for p in rims for f in p if f in open_faces}):
        lo, hi = list(hollow.lo), list(hollow.hi)
        k = "xyz".index(opened[1])
        lo[k] = hi[k] = outer.hi[k] if opened[0] == "+" else outer.lo[k]
        sides = [f for p in rims if opened in p for f in p if f != opened]
        inner_names = {opened: names[opened], **{s: names[f"inner {s}"] for s in sides}}
        for earlier in hollow.rounded:
            for c1, c2 in ordered(earlier.pairs):
                if c1 in sides and c2 in sides and c1[1] != c2[1]:
                    where = _corner_where(
                        (lo[0], lo[1], lo[2]),
                        (hi[0], hi[1], hi[2]),
                        opened,
                        c1,
                        c2,
                        earlier,
                    )
                    queries.add(inner_names[opened], earlier.refs, where=where,
                                count=_count(chain, where, key))  # fmt: skip


def circle_where(centre: Vec, axis: Vec, radius: float) -> dict[str, Any]:
    spread = [radius * math.sqrt(max(1.0 - a * a, 0.0)) for a in axis]
    lo = [centre[i] - spread[i] for i in range(3)]
    hi = [centre[i] + spread[i] for i in range(3)]
    return {"kind": "circle", "axis": _vec(axis), "centre": _vec(centre), "radius_mm": num(radius),
            "within": _within(lo, hi)}  # fmt: skip


def _rims(chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
          open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
    """A round body's or boss's rims: each end's circle with its side (or a tube's bore)."""
    kind = target.kind
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    o, u = copy.origin, copy.normal
    long = _mm(target, "height" if kind == "boss" else "length")
    sets: Mapping[str, Sequence[tuple[str, str]]] = {
        "top": [("+end", "side")] + ([("+end", "bore")] if kind == "tube" else []),
        "bottom": [("-end", "side")] + ([("-end", "bore")] if kind == "tube" else []),
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
        radius = _rim_radius(target, end, side)
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


def _rim_radius(target: Item, end: str, side: str) -> float:
    kind = target.kind
    if side == "bore":
        return _mm(target, "inner_diameter") / 2
    if kind == "cone":
        return _mm(target, "top_diameter" if end == "+end" else "base_diameter") / 2
    if kind == "tube":
        return _mm(target, "outer_diameter") / 2
    return _mm(target, "diameter") / 2


def _dome(chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
          open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
    if which != "bottom" or _choice(target, "portion") != "upper_half":
        raise PlanError(
            "only a dome's rim (bottom) can be rounded on a ball", item=target.id
        )
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    if part == "after" or (part is None and "-end" in open_faces):
        hollow = chain.hollows.get(key)
        inner = names.get("inner surface")
        if hollow is None or inner is None:
            raise PlanError(
                "its flat face is open, and the hollow has no name", item=target.id
            )
        where = circle_where(copy.origin, copy.normal, hollow.radius)
        queries.add(names["-end"], inner, where=where, count=_count(chain, where, key))
    if part != "after":
        where = circle_where(copy.origin, copy.normal, _mm(target, "diameter") / 2)
        queries.add(
            names["-end"],
            names["surface"],
            where=where,
            count=_count(chain, where, key),
        )
    return frozenset({frozenset({"-end", "surface"})})


def _round_tab(chain: Chain, queries: Queries, target: Item, copy: Instance,
               which: str) -> frozenset[frozenset[str]]:  # fmt: skip
    """A round-ended tab's ``top``: the two half-circles where its rounding meets its broad faces.

    Its ``vertical`` edges run on smoothly into those half-circles (tab.md):
    a rounding can't stop there, so they are not compiled (a gap).
    """
    if which != "top":
        raise GapError("a round-ended tab's vertical edges run on smoothly into its rounding: "
                        "no construction rounds them and stops there", item=target.id)  # fmt: skip
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    thin = _choice(target, "thickness_along")
    assert thin is not None
    width, thickness, long = (
        _mm(target, "width"),
        _mm(target, "thickness"),
        _mm(target, "length"),
    )
    r = width / 2
    centre = add(copy.origin, copy.normal, long - r)
    for sign in ("+", "-"):
        face = sign + thin
        at = add(centre, unit(face), thickness / 2)
        where = circle_where(at, unit("+" + thin), r)
        queries.add(
            names[face], names["end"], where=where, count=_count(chain, where, key)
        )
    return frozenset({frozenset({"+" + thin, "end"}), frozenset({"-" + thin, "end"})})


def _mm(item: Item, name: str) -> float:
    from forge_spec.values import Value

    value = item.get(name)
    if not isinstance(value, Value):
        raise PlanError(f"its {name} is no size", item=item.id)
    return value.made_in("mm")


# ----------------------------------------------------------------------
# Cuts' rims and pockets' floors
# ----------------------------------------------------------------------
def _cut_rims(chain: Chain, queries: Queries, target: Item, which: str,
              copies: Iterable[Instance]) -> None:  # fmt: skip
    for copy in copies:
        key = (target.id, copy.index)
        names = chain.names_of(target.id, copy.index)
        box = next((b for b in chain.cut if (b.item, b.copy) == key), None)
        if box is None:
            raise PlanError(
                f"{target.id}#{copy.index} has no box in the part", item=target.id
            )
        if copy.host is None:
            raise PlanError("a cut is on a face", item=target.id)
        host = chain.names_of(copy.host[0], copy.host[1]).get(copy.host[2], ())
        if which == "top":
            walls = (
                names.get("counterbore_wall")
                or names.get("countersink")
                or names["wall"]
            )
            mouth_lo, mouth_hi = _flat_at(box, copy)
            where: dict[str, Any] = {"within": _within(mouth_lo, mouth_hi)}
            queries.add(
                walls,
                host,
                where=where,
                count=(
                    0,
                    2 * _pieces(target) + 2 * _crossing(chain, mouth_lo, mouth_hi, key),
                ),
            )
        elif which == "bottom":
            if target.kind != "pocket":
                raise PlanError(f"a {target.kind} has no bottom edges", item=target.id)
            floor = names.get("bottom", ())
            where = {"within": _within(box.lo, box.hi)}
            queries.add(
                names["wall"],
                floor,
                where=where,
                count=(
                    0,
                    2 * _pieces(target) + 2 * _crossing(chain, box.lo, box.hi, key),
                ),
            )
        else:
            raise PlanError(f"a {target.kind} has no {which!r} edges", item=target.id)


def _pieces(cut: Item) -> int:
    """How many lines and arcs a cut's outline is made of (each may be split once more where a seam crosses it)."""
    if cut.kind == "hole":
        return 1
    if cut.kind == "slot":
        return 4
    if _choice(cut, "shape") == "circle":
        return 1
    corner = cut.get("corner_radius")
    return 8 if corner is not None else 4


def _flat_at(box: Box, copy: Instance) -> tuple[list[float], list[float]]:
    """The box flattened to the plane of the face the copy is on, through its point; round a side, the whole box (the curve dips into it)."""
    lo, hi = list(box.lo), list(box.hi)
    if copy.host is not None and copy.host[2] in _ROUND:
        return lo, hi
    k = "xyz".index(axis_of(copy.normal))
    lo[k] = hi[k] = copy.origin[k]
    return lo, hi


# ----------------------------------------------------------------------
# Joints
# ----------------------------------------------------------------------
def _joint(chain: Chain, queries: Queries, target: Item, meets: Item, copies: Mapping[str, Sequence[Instance]],
           faces: Mapping[tuple[str, int], Mapping[str, FlatFace | SideFace]]) -> None:  # fmt: skip
    """The inside corner where one item stands on the other (edges.md, "joint").

    A side flush with an edge of the face has no corner along it (edges.md):
    it is left out, so the face's own edge on past it is never taken for
    the joint.
    """
    standing, host = None, None
    for s, h in ((target, meets), (meets, target)):
        if any(c.host is not None and c.host[0] == h.id for c in copies.get(s.id, ())):
            standing, host = s, h
            break
    if standing is None or host is None:
        raise PlanError(f"{target.id} and {meets.id} don't meet: a joint is where one stands on the other",
                        item=target.id)  # fmt: skip
    for copy in copies[standing.id]:
        if copy.host is None or copy.host[0] != host.id:
            continue
        key = (standing.id, copy.index)
        names = chain.names_of(standing.id, copy.index)
        face = chain.names_of(copy.host[0], copy.host[1]).get(copy.host[2], ())
        box = _box(chain, key)
        host_face = faces.get((copy.host[0], copy.host[1]), {}).get(copy.host[2])
        flush = _flush_sides(box, host_face)
        sides = [refs for name, refs in names.items()
                 if name in ("side", "surface", *DIRECTIONS) and name not in _ends(copy) and name not in flush]  # fmt: skip
        earlier = [
            Ref(d.step, "bevel" if d.bevel else "round")
            for d in chain.rounded.get(key, [])
        ]
        foot_lo, foot_hi = _flat_at(box, copy)
        where = {"within": _within(foot_lo, foot_hi)}
        side_refs = tuple(r for refs in sides for r in refs) + tuple(earlier)
        queries.add(
            side_refs,
            face,
            where=where,
            count=(0, 8 + 2 * _crossing(chain, foot_lo, foot_hi, key)),
        )
        # Under where it hangs over the face's edge: between its underside and the host's sides.
        base = names.get(_base(copy), ())
        host_names = chain.names_of(copy.host[0], copy.host[1])
        host_sides = tuple(r for name, refs in host_names.items() if name in DIRECTIONS
                           and name not in (copy.host[2], opposite(copy.host[2])) for r in refs)  # fmt: skip
        if base and host_sides:
            queries.add(base, host_sides, where=where, count=(0, 8))


def _flush_sides(box: Box, face: FlatFace | SideFace | None) -> set[str]:
    """The sides of a box-like item standing on a rectangular face that lie in the planes of the face's edges."""
    if not isinstance(face, FlatFace) or face.shape != "rect":
        return set()
    found: set[str] = set()
    for i, axis in enumerate(face.axes):
        k = "xyz".index(axis)
        for sign, side, edge in (("+", box.hi[k], face.centre[k] + face.half[i]),
                                 ("-", box.lo[k], face.centre[k] - face.half[i])):  # fmt: skip
            if abs(side - edge) <= 1e-9:
                found.add(sign + axis)
    return found


def _ends(copy: Instance) -> tuple[str, ...]:
    up = _up(copy)
    return (up, opposite(up), "+end", "-end")


def _base(copy: Instance) -> str:
    return opposite(_up(copy))
