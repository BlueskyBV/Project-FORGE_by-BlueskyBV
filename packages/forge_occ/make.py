"""The OpenCascade operations every builder is made of, each with its flags read and its history kept.

docs/V2-stage3.md, sections 4 and 7.1: booleans run through the pave filler
and ``BOPAlgo_BOP`` (whose error and warning flags are bound), exact (fuzzy
value 0), single-threaded and non-destructive; faces on one surface are then
merged, with the merge's history; fillets and chamfers say which edges they
really rounded (OpenCascade runs on along tangent edges); every result is
validated by the caller's after-check.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from OCP.BOPAlgo import BOPAlgo_BOP, BOPAlgo_Operation, BOPAlgo_PaveFiller
from OCP.BRep import BRep_Builder
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.Message import Message_Gravity
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopoDS import TopoDS, TopoDS_Compound

from .errors import BooleanFlagError, OccError, OperationError
from .geom import Vector, vec
from .names import History
from .occt import boundary, edges, faces, is_valid, shape_list, solids, tightened

__all__ = [
    "FUZZY",
    "Boolean",
    "Rounded",
    "boolean",
    "compound",
    "prism",
    "round_edges",
    "unify",
]

#: The fuzzy value every boolean runs with: exact, inside OpenCascade's own 1e-7 mm.
FUZZY = 0.0

#: Warnings a boolean may give and still be right, each with why. Any other fails the step.
ALLOWED_WARNINGS: dict[str, str] = {
    "BOPAlgo_AlertUnableToOrientTheShape": (
        "raised where one solid's face only touches the other at a point (a box's face "
        "tangent to a sphere at its pole); the result is still held to everything every "
        "result is: valid, each solid enclosing positive volume, the operation's volume "
        "bounds, and the second kernel's agreement"
    ),
}

_OPERATIONS = {
    "union": BOPAlgo_Operation.BOPAlgo_FUSE,
    "subtract": BOPAlgo_Operation.BOPAlgo_CUT,
    "intersect": BOPAlgo_Operation.BOPAlgo_COMMON,
}


def _alerts(algorithm: Any, gravity: Any) -> list[str]:
    found = []
    for alert in algorithm.GetReport().GetAlerts(gravity):
        found.append(alert.DynamicType().Name())
    return found


@dataclass(frozen=True)
class Boolean:
    shape: Any
    history: History
    warnings: tuple[str, ...]


def boolean(
    kind: str,
    arguments: Sequence[Any],
    tools: Sequence[Any],
    *,
    also_allowed: frozenset[str] = frozenset(),
) -> Boolean:
    """``union``, ``subtract`` or ``intersect`` of the arguments with the tools; flags read.

    ``also_allowed``: warnings the caller takes, besides :data:`ALLOWED_WARNINGS`,
    because it checks the result another way (a test's exact model of a
    generated part, held to that part's own membership): never Forge's own
    building, which takes only the warnings shown to leave a result right.
    """
    if kind not in _OPERATIONS:
        raise OperationError("not a boolean", kind=kind)
    with boundary(f"a {kind}"):
        filler = BOPAlgo_PaveFiller()
        filler.SetArguments(shape_list([*arguments, *tools]))
        filler.SetRunParallel(False)
        filler.SetFuzzyValue(FUZZY)
        filler.SetNonDestructive(True)
        filler.Perform()
        if filler.HasErrors():
            raise BooleanFlagError(
                f"OpenCascade could not intersect the {kind}'s solids",
                errors=_alerts(filler, Message_Gravity.Message_Fail),
            )
        op = BOPAlgo_BOP()
        for shape in arguments:
            op.AddArgument(shape)
        for shape in tools:
            op.AddTool(shape)
        op.SetOperation(_OPERATIONS[kind])
        op.SetRunParallel(False)
        op.SetNonDestructive(True)
        op.PerformWithFiller(filler)
        if op.HasErrors():
            raise BooleanFlagError(
                f"OpenCascade's {kind} failed",
                errors=_alerts(op, Message_Gravity.Message_Fail),
            )
        warnings = tuple(
            _alerts(filler, Message_Gravity.Message_Warning)
            + _alerts(op, Message_Gravity.Message_Warning)
        )
        refused = sorted(
            {w for w in warnings if w not in ALLOWED_WARNINGS and w not in also_allowed}
        )
        if refused:
            raise BooleanFlagError(f"OpenCascade's {kind} warned", warnings=refused)
        return Boolean(tightened(op.Shape()), History(op.History()), warnings)


@dataclass(frozen=True)
class Unified:
    shape: Any
    history: History


class _Unchanged:
    """The history of an operation that changed nothing."""

    def Modified(self, _shape: Any) -> list[Any]:  # noqa: N802 - OpenCascade's interface
        return []

    def IsRemoved(self, _shape: Any) -> bool:  # noqa: N802
        return False

    def Generated(self, _shape: Any) -> list[Any]:  # noqa: N802
        return []


def unify(shape: Any) -> Unified:
    """Faces (and edges) on one surface merged into one, with the merge's history.

    Merging only tidies the faces; where OpenCascade's merge would leave an
    invalid solid (it can, at a face that only touches another at a point), the
    shape is kept as it was, valid, its faces unmerged.
    """
    with boundary("merging faces on one surface"):
        merger = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
        merger.AllowInternalEdges(False)
        merger.Build()
        merged = merger.Shape()
    if not is_valid(merged) and is_valid(shape):
        return Unified(shape, History(_Unchanged()))
    return Unified(tightened(merged), History(merger.History()))


@dataclass(frozen=True)
class Prism:
    shape: Any
    first: Any  # the face it started from (at the low end)
    last: Any  # the face it ended at
    history: Any  # the maker, for Generated: edge → side face


def prism(face: Any, along: Vector) -> Prism:
    with boundary("extruding a profile"):
        maker = BRepPrimAPI_MakePrism(face, vec(along), True)
        maker.Build()
        if not maker.IsDone():
            raise OperationError("OpenCascade could not extrude the profile")
        return Prism(maker.Shape(), maker.FirstShape(), maker.LastShape(), maker)


@dataclass(frozen=True)
class Rounded:
    shape: Any
    history: History
    #: Every edge really rounded, the asked ones and those OpenCascade ran on to along tangents.
    rounded: tuple[Any, ...]
    #: The faces made, per contour.
    new_faces: tuple[Any, ...]
    #: The size each rounded edge was rounded by, in the order of ``rounded``.
    sizes: tuple[float, ...] = ()


def round_edges(
    shape: Any,
    chosen: Iterable[Any],
    size: float | Sequence[float],
    *,
    bevel: bool = False,
) -> Rounded:
    """A fillet of radius ``size`` (or a chamfer of distance ``size``) on ``chosen`` edges of ``shape``; one size, or one an edge."""
    chosen = list(chosen)
    if not chosen:
        raise OperationError("no edges to round")
    sizes = (
        [float(size)] * len(chosen)
        if isinstance(size, int | float)
        else [float(s) for s in size]
    )
    if len(sizes) != len(chosen):
        raise OperationError("one size an edge", edges=len(chosen), sizes=len(sizes))
    what = "a chamfer" if bevel else "a fillet"
    with boundary(what, size=max(sizes)):
        maker: Any = (
            BRepFilletAPI_MakeChamfer(shape)
            if bevel
            else BRepFilletAPI_MakeFillet(shape)
        )
        for edge, each in zip(chosen, sizes, strict=True):
            maker.Add(each, TopoDS.Edge(edge))
        maker.Build()
        if not maker.IsDone():
            raise OperationError(
                f"OpenCascade could not make {what} of {max(sizes):g} mm here"
            )
        rounded: list[Any] = []
        each_size: list[float] = []
        new: list[Any] = []
        for contour in range(1, maker.NbContours() + 1):
            these = [
                maker.Edge(contour, index)
                for index in range(1, maker.NbEdges(contour) + 1)
            ]
            # A contour takes the size of the asked edge it runs through (the largest, if several).
            asked = [
                s
                for e, s in zip(chosen, sizes, strict=True)
                if any(e.IsSame(t) for t in these)
            ]
            rounded.extend(these)
            each_size.extend([max(asked, default=max(sizes))] * len(these))
            if not bevel:
                new.extend(maker.NewFaces(contour))
        return Rounded(
            maker.Shape(), History(maker), tuple(rounded), tuple(new), tuple(each_size)
        )


@dataclass(frozen=True)
class Fitted:
    """Edges rounded each by as much of the size asked as it takes: the result, and each edge's size (0: left sharp)."""

    made: Rounded | None
    sizes: tuple[float, ...]
    #: The most each edge takes alone (an edge left sharp only because it won't round with the rest has one).
    alone: tuple[float, ...] = ()


#: How finely the most an edge takes is found: halving the interval this many times.
_FIT_STEPS = 10


def _takes(shape: Any, edge: Any, size: float, bevel: bool) -> bool:
    try:
        made = round_edges(shape, [edge], size, bevel=bevel)
    except OccError:
        return False
    return is_valid(made.shape)


def round_fitted(
    shape: Any, chosen: Sequence[Any], size: float, *, bevel: bool = False
) -> Fitted:
    """The edges rounded by ``size``; where OpenCascade can't, each edge by the most of ``size`` it takes alone.

    A blend asked of an edge whose face beside it is narrower than the size
    (a 3 mm root blend on an ear 2 mm from the plate's edge) can't be a
    fillet of that size: the ball rolls off the face. Each such edge is
    rounded by the largest size that fits it (found to a thousandth of the
    size), the edges that take none left sharp, and all are rounded at once;
    or, where edges meeting at a corner won't take different sizes, the least
    of them; or every edge the least of all; or, last, as many as will round
    together, the rest left sharp. Each edge's size is returned (0: sharp).
    """
    try:
        made = round_edges(shape, chosen, size, bevel=bevel)
        if is_valid(made.shape):
            return Fitted(made, (size,) * len(chosen))
    except OccError:
        pass
    sizes = []
    for edge in chosen:
        if _takes(shape, edge, size, bevel):
            sizes.append(size)
            continue
        lo, hi = 0.0, size
        for _ in range(_FIT_STEPS):
            middle = (lo + hi) / 2.0
            if _takes(shape, edge, middle, bevel):
                lo = middle
            else:
                hi = middle
        sizes.append(lo)
    # Edges meeting at a corner may not take different sizes together: then each set of edges joined
    # through corners takes the least of its sizes; then every edge the least of all.
    for attempt in (sizes, _least_per_cluster(chosen, sizes), [min((s for s in sizes if s > 0.0), default=0.0)
                                                                if s > 0.0 else 0.0 for s in sizes]):  # fmt: skip
        kept = [(e, s) for e, s in zip(chosen, attempt, strict=True) if s > 0.0]
        if not kept:
            return Fitted(None, tuple(attempt), tuple(sizes))
        try:
            made = round_edges(
                shape, [e for e, _ in kept], [s for _, s in kept], bevel=bevel
            )
        except OccError:
            continue
        if is_valid(made.shape):
            return Fitted(made, tuple(attempt), tuple(sizes))
    # Last, as many edges as round together, each by the most it takes: an edge that stops the rest
    # rounding (where three blends meet at a corner OpenCascade can't make) is left sharp. Each set of
    # edges joined through corners is settled alone (its largest subset that rounds), then all together.
    picked: list[int] = []
    for cluster in _clusters(chosen):
        live = [k for k in cluster if sizes[k] > 0.0]
        for subset in _subsets(live, sizes):
            if _rounds(shape, chosen, sizes, subset, bevel) is not None:
                picked.extend(subset)
                break
    together = _rounds(shape, chosen, sizes, sorted(picked), bevel) if picked else None
    if together is None:
        picked = []
    final = tuple(sizes[k] if k in picked else 0.0 for k in range(len(chosen)))
    return Fitted(together, final, tuple(sizes))


#: A set of corner-joined edges larger than this is settled by dropping its edges one at a time, not by trying every subset.
_SUBSETS_UP_TO = 8


def _subsets(live: Sequence[int], sizes: Sequence[float]) -> list[list[int]]:
    """Subsets of ``live`` to try, the most edges first (then the most rounding)."""
    from itertools import combinations

    if len(live) > _SUBSETS_UP_TO:
        by_size = sorted(live, key=lambda k: sizes[k])
        return [sorted(by_size[drop:]) for drop in range(len(by_size) + 1)]
    out = [list(c) for n in range(len(live), 0, -1) for c in combinations(live, n)]
    out.sort(key=lambda c: (-len(c), -sum(sizes[k] for k in c)))
    return out


def _rounds(shape: Any, chosen: Sequence[Any], sizes: Sequence[float], subset: Sequence[int],
            bevel: bool) -> Rounded | None:  # fmt: skip
    if not subset:
        return None
    try:
        made = round_edges(
            shape, [chosen[k] for k in subset], [sizes[k] for k in subset], bevel=bevel
        )
    except OccError:
        return None
    return made if is_valid(made.shape) else None


def _clusters(chosen: Sequence[Any]) -> list[list[int]]:
    """The edges in sets joined through shared corners."""
    parent = list(range(len(chosen)))

    def root(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    corners = [vertices_of(e) for e in chosen]
    for i in range(len(chosen)):
        for j in range(i + 1, len(chosen)):
            if any(a.IsSame(b) for a in corners[i] for b in corners[j]):
                parent[root(i)] = root(j)
    groups: dict[int, list[int]] = {}
    for k in range(len(chosen)):
        groups.setdefault(root(k), []).append(k)
    return list(groups.values())


def _least_per_cluster(chosen: Sequence[Any], sizes: Sequence[float]) -> list[float]:
    """Each edge's size the least of those of the edges joined to it through shared corners."""
    out = [0.0] * len(chosen)
    for cluster in _clusters(chosen):
        live = [sizes[k] for k in cluster if sizes[k] > 0.0]
        for k in cluster:
            out[k] = min(live) if live and sizes[k] > 0.0 else 0.0
    return out


def vertices_of(shape: Any) -> list[Any]:
    from .occt import vertices

    return vertices(shape)


def compound(shapes: Iterable[Any]) -> Any:
    out = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(out)
    for shape in shapes:
        builder.Add(out, shape)
    return out


def one_solid(shape: Any) -> Any:
    """The shape's only solid; a compound of one is that solid."""
    found = solids(shape)
    if len(found) == 1:
        return found[0]
    return shape


def edges_of(face: Any) -> list[Any]:
    return edges(face)


def face_count(shape: Any) -> int:
    return len(faces(shape))
