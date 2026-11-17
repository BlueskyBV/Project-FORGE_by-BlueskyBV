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

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from forge_spec.draft import EdgeSet, Faces, Item
from forge_spec.geometry import FlatFace, SideFace
from forge_spec.placement import Instance
from forge_spec.schema import DIRECTIONS

from .errors import PlanError
from .items.plan import PLAN
from .items.plan._edges import (
    Queries,
    _corner_where,
    _count,
    _crossing,
    _within,
    box_queries,
    circle_where,
    followed,
    opposite,
)
from .write import (
    Box,
    Chain,
    Ref,
    axis_of,
    ordered,
)

__all__ = [
    "Queries",
    "box_pairs",
    "box_queries",
    "circle_where",
    "edge_reference",
    "followed",
    "opposite",
    "pairs_for",
]

#: The faces that are round: a cut's rim on one, or a joint on one, is a curve, not in one plane.
_ROUND = ("side", "bore", "inner side", "surface")


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
    if PLAN[kind].bottom_edges:
        sets["bottom"] = [(down, s) for s in sides]
        sets["all"] = sets["vertical"] + sets["top"] + sets["bottom"]
    if which not in sets:
        raise PlanError(f"a {kind} has no {which!r} edges")
    return sets[which]


# ----------------------------------------------------------------------
# The reference
# ----------------------------------------------------------------------
def pairs_for(item: Item, copy: Instance, which: str) -> list[tuple[str, str]]:
    up = _rises(copy)
    return box_pairs(item.kind, which, up)


def _rises(copy: Instance) -> str:
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
    elif PLAN[target.kind].rimmed_cut:
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


class _Moved(Queries):
    """Queries found on a copy as it stands upright and unturned, each moved onto the part with it (edges.md, "A
    turned item's edges")."""

    def __init__(self, queries: Queries, motion: Any, chain: Chain, key: tuple[str, int]) -> None:
        super().__init__(queries.found)
        self.motion, self.chain, self.key = motion, chain, key

    def add(self, a: Sequence[Ref], b: Sequence[Ref], *, where: Mapping[str, Any], count: tuple[int, int]) -> None:
        from .moved import moved_where

        moved = moved_where(where, self.motion)
        if count == _count(self.chain, where, self.key):  # counted where it stands upright: count it where it is
            count = _count(self.chain, moved, self.key)
        super().add(a, b, where=moved, count=count)


def _own(chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
         shell: Item | None, part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
    """An item's own edges (not a joint): a box-like item's, a round item's rims, a dome's, a round tab's; a turned
    one's, or one's on a turned item's face, found as it stands upright and unturned, then moved."""
    names = chain.names_of(target.id, copy.index)
    key = (target.id, copy.index)
    kind = target.kind
    open_faces = _open_faces(shell)
    motion = None
    if key in chain.motions:
        lo, hi, motion = chain.motions[key]
        copy = replace(copy.local or copy, lo=lo, hi=hi)
        queries = _Moved(queries, motion, chain, key)
    if PLAN[kind].box_like(target):
        box = _box(chain, key) if motion is None else Box(copy.lo, copy.hi, target.id, copy.index)  # type: ignore[arg-type]
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
    return PLAN[kind].own_edges(chain, queries, target, copy, which, open_faces, part)


def _box(chain: Chain, key: tuple[str, int]) -> Box:
    for box in chain.added:
        if (box.item, box.copy) == key:
            return box
    raise PlanError(f"{key[0]}#{key[1]} has no box in the part")


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
        motion = None
        if key in chain.motions:  # on a turned item's face: found as it is cut upright, then moved
            lo, hi, motion = chain.motions[key]
            box, copy = Box(lo, hi, target.id, copy.index), copy.local or copy  # type: ignore[arg-type]
            queries = _Moved(queries, motion, chain, key)
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
            seen_lo, seen_hi = motion.box(mouth_lo, mouth_hi) if motion else (mouth_lo, mouth_hi)
            crossing = _crossing(chain, seen_lo, seen_hi, key)
            queries.add(walls, host, where=where, count=(0, 2 * _pieces(target) + 2 * crossing))
        elif which == "bottom":
            if not PLAN[target.kind].floored:
                raise PlanError(f"a {target.kind} has no bottom edges", item=target.id)
            floor = names.get("bottom", ())
            where = {"within": _within(box.lo, box.hi)}
            seen_lo, seen_hi = motion.box(box.lo, box.hi) if motion else (box.lo, box.hi)
            crossing = _crossing(chain, seen_lo, seen_hi, key)
            queries.add(names["wall"], floor, where=where, count=(0, 2 * _pieces(target) + 2 * crossing))
        else:
            raise PlanError(f"a {target.kind} has no {which!r} edges", item=target.id)


def _pieces(cut: Item) -> int:
    """How many lines and arcs a cut's outline is made of (each may be split once more where a seam crosses it)."""
    return PLAN[cut.kind].pieces(cut)


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
    up = _rises(copy)
    return (up, opposite(up), "+end", "-end")


def _base(copy: Instance) -> str:
    return opposite(_rises(copy))
