"""A rounding made as its regions (docs/V2-stage4.md 5.6).

Along a straight edge between two flat faces at right angles, a rounding
changes exactly one region (5.5): taking an outside edge away, ``K``, the
corner's square of the rounding's size less the quarter disc about its far
corner (a fillet) or its triangle (a chamfer); filling an inside one, ``F``,
the same on the air's side. Made so, a rounding is the part less every
``K`` (or with every ``F``), each a prism along its stretch of edge: the
square's prism, a box, less the round's cylinder; or the triangle's prism,
a sketch pushed along the edge. Along each stretch it is the definition's
own round. Where stretches meet (a box's corner, a post's, where a joint
runs off a face under an overhang) the definitions leave the shape to the
zones the oracle bounds, taking all of what either rounds away in the inner
form and keeping it all in the outer: the prisms there are within them.
The reference parts the oracle is tested against are made the same way.

Each prism reaches :data:`MARGIN` past the faces it rounds into what it
leaves as it is (``K`` into the air beyond them, ``F`` into the material
behind them), and ``K`` as far past each end of its stretch where the air
there is shown clear, so no face of a tool lies in one of the part's.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from forge_spec.draft import EdgeSet, Item
from forge_spec.geometry import FlatFace, SideFace
from forge_spec.placement import Instance

from .edges import box_pairs, followed, opposite
from .errors import PlanError
from .items.plan import PLAN
from .write import DATUMS, PLANE_AXES, Box, Chain, Done, Ref, Vec, axis_of, num, unit

__all__ = [
    "MARGIN",
    "Stretch",
    "joint_stretches",
    "own_stretches",
    "region_applies",
    "region_tools",
]

#: How far a region's prism reaches past the faces it rounds, and past an open end of its stretch (mm).
MARGIN = 0.05
#: How far an edge's own box is shrunk at its ends, and grown across, to find what covers it.
_TOUCH = 1e-9


@dataclass(frozen=True)
class Stretch:
    """A straight edge between two flat faces at right angles, from ``p0`` to ``p1``.

    ``n1`` and ``n2`` are the faces' outward normals, by name (``+x``);
    ``fill``: an inside corner (the region on the air's side), else an
    outside one (the region in the material). ``faces``: the two faces'
    names on the item whose edge it is.
    """

    p0: Vec
    p1: Vec
    n1: str
    n2: str
    fill: bool
    faces: tuple[str, str]

    @property
    def axis(self) -> str:
        k = next(i for i in range(3) if abs(self.p1[i] - self.p0[i]) > 0.0)
        return "xyz"[k]


def _box_of(lo: Sequence[float], hi: Sequence[float]) -> tuple[Vec, Vec]:
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def region_box(
    stretch: Stretch,
    size: float,
    *,
    margin: float = 0.0,
    ends: tuple[float, float] = (0.0, 0.0),
) -> tuple[Vec, Vec]:
    """The box of a stretch's region: its corner's square, ``margin`` past its faces, ``ends`` past its ends."""
    lo, hi = list(stretch.p0), list(stretch.p0)
    sign = (
        1.0 if stretch.fill else -1.0
    )  # the region lies along +n (the air's side) or -n (the material's)
    for name in (stretch.n1, stretch.n2):
        i = "xyz".index(name[1])
        v = unit(name)[i]
        a, b = stretch.p0[i] + sign * v * size, stretch.p0[i] - sign * v * margin
        lo[i], hi[i] = min(a, b), max(a, b)
    k = "xyz".index(stretch.axis)
    lo[k] = min(stretch.p0[k], stretch.p1[k]) - ends[0]
    hi[k] = max(stretch.p0[k], stretch.p1[k]) + ends[1]
    return _box_of(lo, hi)


def _slab(stretch: Stretch, size: float, name: str, depth: float) -> tuple[Vec, Vec]:
    """The slab a region reaches past (``K``) or behind (``F``) the face facing ``name``: its margin there."""
    lo, hi = (list(c) for c in region_box(stretch, size))
    i = "xyz".index(name[1])
    v = unit(name)[i]
    face = stretch.p0[i]
    beyond = face + v * depth if not stretch.fill else face - v * depth
    lo[i], hi[i] = min(face, beyond), max(face, beyond)
    return _box_of(lo, hi)


def _corner(stretch: Stretch, size: float, depth: float) -> tuple[Vec, Vec]:
    """The square a region's margins make together, past (``K``) or behind (``F``) both its faces."""
    lo, hi = (list(c) for c in region_box(stretch, size))
    for name in (stretch.n1, stretch.n2):
        i = "xyz".index(name[1])
        v = unit(name)[i]
        face = stretch.p0[i]
        beyond = face + v * depth if not stretch.fill else face - v * depth
        lo[i], hi[i] = min(face, beyond), max(face, beyond)
    return _box_of(lo, hi)


def _end(stretch: Stretch, size: float, which: int, depth: float) -> tuple[Vec, Vec]:
    """The slab past one end of a stretch's region and its margins."""
    lo, hi = (list(c) for c in region_box(stretch, size, margin=depth))
    k = "xyz".index(stretch.axis)
    if which == 0:
        hi[k] = lo[k]
        lo[k] = lo[k] - depth
    else:
        lo[k] = hi[k]
        hi[k] = hi[k] + depth
    return _box_of(lo, hi)


def _meets(box: tuple[Vec, Vec], others: Sequence[Box], by: float = 0.0) -> bool:
    probe = Box(box[0], box[1], "", -1)
    return any(probe.meets(other, by=by) for other in others)


def _within(box: tuple[Vec, Vec], outer: Box) -> bool:
    return all(outer.lo[i] <= box[0][i] and box[1][i] <= outer.hi[i] for i in range(3))


# ----------------------------------------------------------------------
# Which stretches
# ----------------------------------------------------------------------
def _up(copy: Instance) -> str:
    axis = axis_of(copy.normal)
    return ("+" if copy.normal["xyz".index(axis)] > 0 else "-") + axis


def _own_box(chain: Chain, item: str, copy: int) -> Box:
    for box in chain.added:
        if (box.item, box.copy) == (item, copy):
            return box
    raise PlanError(f"{item}#{copy} has no box in the part")


def own_stretches(
    chain: Chain, item: Item, copy: Instance, which: str
) -> list[Stretch]:
    """A box-like item's own edges of a set, each its whole length between its two faces (outside edges)."""
    box = _own_box(chain, item.id, copy.index)
    found = []
    for f1, f2 in box_pairs(item.kind, which, _up(copy)):
        p0, p1 = list(box.lo), list(box.hi)
        for f in (f1, f2):
            i = "xyz".index(f[1])
            p0[i] = p1[i] = box.hi[i] if f[0] == "+" else box.lo[i]
        found.append(
            Stretch(_box_of(p0, p1)[0], _box_of(p0, p1)[1], f1, f2, False, (f1, f2))
        )
    return found


def joint_stretches(
    chain: Chain, standing: Item, copy: Instance, face: FlatFace
) -> list[Stretch]:
    """Where a box-like item stands on a rectangular face: its sides within the face, and under where it hangs over the face's edges (inside edges).

    A side flush with the face's edge has no corner along it (edges.md).
    """
    assert copy.host is not None
    box = _own_box(chain, standing.id, copy.index)
    host = _own_box(chain, copy.host[0], copy.host[1])
    up = _up(copy)
    k = "xyz".index(up[1])
    plane = copy.origin[k]
    extent: dict[str, tuple[float, float]] = {}
    for n, axis in enumerate(face.axes):
        i = "xyz".index(axis)
        extent[axis] = (face.centre[i] - face.half[n], face.centre[i] + face.half[n])
    found = []
    for axis in face.axes:
        run = next(a for a in face.axes if a != axis)
        i, j = "xyz".index(axis), "xyz".index(run)
        start, stop = max(box.lo[j], extent[run][0]), min(box.hi[j], extent[run][1])
        if stop - start <= 1e-9:
            continue
        for sign in "+-":
            side = box.hi[i] if sign == "+" else box.lo[i]
            p0, p1 = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            p0[k] = p1[k] = plane
            p0[j], p1[j] = start, stop
            if (
                extent[axis][0] + 1e-9 < side < extent[axis][1] - 1e-9
            ):  # a side standing within the face
                p0[i] = p1[i] = side
                lo, hi = _box_of(p0, p1)
                found.append(
                    Stretch(lo, hi, sign + axis, up, True, (sign + axis, copy.host[2]))
                )
            edge = extent[axis][1] if sign == "+" else extent[axis][0]
            hangs = box.hi[i] > edge + 1e-9 if sign == "+" else box.lo[i] < edge - 1e-9
            on_host = abs((host.hi[i] if sign == "+" else host.lo[i]) - edge) <= 1e-9
            if (
                hangs and on_host
            ):  # under the overhang: between the host's side and the item's underside
                p0[i] = p1[i] = edge
                lo, hi = _box_of(p0, p1)
                found.append(
                    Stretch(
                        lo,
                        hi,
                        sign + axis,
                        opposite(up),
                        True,
                        (sign + axis, opposite(up)),
                    )
                )
    return found


# ----------------------------------------------------------------------
# The proof
# ----------------------------------------------------------------------
def region_applies(chain: Chain, stretches: Sequence[Stretch], size: float, *, own: tuple[str, int],
                   host: tuple[str, int] | None = None) -> bool:  # fmt: skip
    """Whether every stretch's region makes what the definition makes there (5.6).

    Taking away (``K``), as 5.5: no other tool added so far meets ``K``'s
    box, none covers the edge itself, and the air its margins reach into
    past the faces is clear. Filling (``F``): no tool but the two it fills
    between meets ``F``'s box, no cut made so far meets it, and its
    margins behind the faces lie within those two.
    """
    if not stretches:
        return False
    others = [b for b in chain.added if (b.item, b.copy) not in (own, host)]
    own_box = _own_box(chain, *own)
    for stretch in stretches:
        region = region_box(stretch, size)
        if stretch.fill:
            if host is None or _meets(region, others):
                return False
            whole = region_box(stretch, size, margin=MARGIN)
            if _meets(whole, chain.cut):
                return False
            host_box = _own_box(chain, *host)
            behind = [
                _slab(stretch, size, name, MARGIN) for name in (stretch.n1, stretch.n2)
            ]
            if not all(
                _within(b, own_box) or _within(b, host_box)
                for b in (*behind, _corner(stretch, size, MARGIN))
            ):
                return False
        else:
            if _meets(region, others):
                return False
            lo, hi = list(stretch.p0), list(stretch.p1)
            k = "xyz".index(stretch.axis)
            lo[k] += 2 * _TOUCH
            hi[k] -= 2 * _TOUCH
            if _meets(_box_of(lo, hi), others, by=_TOUCH):
                return False
            past = [
                _slab(stretch, size, name, MARGIN) for name in (stretch.n1, stretch.n2)
            ]
            if any(
                _meets(b, chain.added) for b in (*past, _corner(stretch, size, MARGIN))
            ):
                return False
    return True


# ----------------------------------------------------------------------
# The tools
# ----------------------------------------------------------------------
def _carried_ends(chain: Chain, stretch: Stretch, size: float) -> tuple[float, float]:
    """How far a region's prism runs on past each end: into the air where shown clear, else not at all (a filled corner never)."""
    if stretch.fill:
        return 0.0, 0.0
    return tuple(
        MARGIN if not _meets(_end(stretch, size, n, MARGIN), chain.added) else 0.0
        for n in (0, 1)
    )  # type: ignore[return-value]


def region_tools(chain: Chain, rounding: Item, key: str, stretches: Sequence[Stretch], size: float,
                 bevel: bool) -> tuple[list[str], list[Ref]]:  # fmt: skip
    """Each stretch's region as a tool, and the faces of the round or bevel they leave."""
    tools: list[str] = []
    faces: list[Ref] = []
    for n, stretch in enumerate(stretches):
        ends = _carried_ends(chain, stretch, size)
        lo, hi = region_box(stretch, size, margin=MARGIN, ends=ends)
        k = "xyz".index(stretch.axis)
        name = f"{key}.{n}"
        if not bevel:
            square = chain.box(f"{name}.square", lo, hi, item=rounding.id)
            sign = 1.0 if stretch.fill else -1.0
            centre = list(stretch.p0)
            for normal in (stretch.n1, stretch.n2):
                i = "xyz".index(normal[1])
                centre[i] += sign * unit(normal)[i] * size
            centre[k] = lo[k] - 1.0
            round_ = chain.cylinder(f"{name}.round", centre, unit("+" + stretch.axis), 2 * size,
                                    hi[k] - lo[k] + 2.0, item=rounding.id)  # fmt: skip
            tools.append(
                chain.boolean(
                    f"{name}.region", "subtract", [square, round_], item=rounding.id
                )
            )
            faces.append(Ref(round_, "lateral"))
            continue
        tools.append(_triangle(chain, rounding, name, stretch, size, lo[k], hi[k]))
        faces.append(Ref(tools[-1], "side"))
    return tools, faces


def _triangle(chain: Chain, rounding: Item, name: str, stretch: Stretch, size: float, start: float,
              stop: float) -> str:  # fmt: skip
    """A chamfer's region: its triangle, with its margins, pushed along the stretch from ``start`` to ``stop``."""
    axis = stretch.axis
    base, datum_sign = DATUMS[axis]
    a1, a2 = PLANE_AXES[base]
    sign = 1.0 if stretch.fill else -1.0
    t1, t2 = (tuple(sign * c for c in unit(n)) for n in (stretch.n1, stretch.n2))
    m = MARGIN
    corners = []
    for s1, s2 in ((-m, -m), (size + m, -m), (-m, size + m)):
        p = [stretch.p0[i] + s1 * t1[i] + s2 * t2[i] for i in range(3)]
        corners.append([p["xyz".index(a1)], p["xyz".index(a2)]])
    plane = chain.datum(f"{name}.plane", axis, start, item=rounding.id)
    outline = chain.profile(f"{name}.outline", "profile_sketch", plane,
                            {"points": {"points": [[num(c) for c in q] for q in corners], "unit": "mm"}},
                            item=rounding.id)  # fmt: skip
    mode = "normal" if datum_sign > 0 else "reverse"
    return chain.extrude(
        f"{name}.region", outline, stop - start, mode, item=rounding.id
    )


def made_as_regions(chain: Chain, rounding: Item, key: str, stretches_of: dict[tuple[str, int], list[Stretch]],
                    size: float, bevel: bool) -> None:  # fmt: skip
    """Write the rounding: the part less (or with) each region in turn, and on each copy of an item whose own edges it rounds, the rounding noted as made."""
    every = [stretch for stretches in stretches_of.values() for stretch in stretches]
    tools, faces = region_tools(chain, rounding, key, every, size, bevel)
    # One region at a time: neighbouring regions overlap round a corner, and OpenCascade settles
    # two tools that overlap each other less surely in one boolean than one tool in each.
    for n, tool in enumerate(tools):
        (chain.join if every[0].fill else chain.take)(
            key, [tool], item=rounding.id, copy=n
        )
    assert chain.head is not None
    for (item, index), stretches in stretches_of.items():
        if stretches and not stretches[0].fill:
            pairs = frozenset(frozenset(s.faces) for s in stretches)
            chain.rounded.setdefault((item, index), []).append(
                Done(chain.head, bevel, size, pairs, tuple(faces), rounding.id))  # fmt: skip
        for stretch in stretches:
            chain.note(Box(*region_box(stretch, size), rounding.id, -1))


def box_like(item: Item) -> bool:
    """Whether an item is a box: a block, a post, a rib or a straight-ended tab."""
    return PLAN[item.kind].box_like(item)


def follows_a_rounding(chain: Chain, item: Item, copy: Instance, which: str) -> bool:
    """Whether the set's edges would follow an earlier rounding of the item round its faces' corners (4.7): not straight all along."""
    pairs = box_pairs(item.kind, which, _up(copy))
    return bool(followed(pairs, chain.rounded.get((item.id, copy.index), [])))


def edge_set(rounding: Item) -> EdgeSet:
    edges = rounding.get("edges")
    if not isinstance(edges, EdgeSet):
        raise PlanError("a rounding names its edges", item=rounding.id)
    return edges


def on_flat(face: FlatFace | SideFace | None) -> FlatFace | None:
    return face if isinstance(face, FlatFace) and face.shape == "rect" else None
