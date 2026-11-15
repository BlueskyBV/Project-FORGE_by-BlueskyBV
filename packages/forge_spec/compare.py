"""Two drafts of one brief, compared by the part they describe (plan, section 4.2).

Published work found that items two independent readings of a document agree
on are right far more often than the ones they disagree on: disagreement is a
good misread detector. So a brief may be drafted twice, and where the drafts
differ, the person is asked. Agreement proves nothing (two drafts from one
model share blind spots); it only means nothing was found.

The drafts are compared by what they would build, never by how they are
written: their ids, their order, the kinds they use for one shape (a post or
a block standing on a plate; a tube, or a rod with a hole down it), the faces
they name and the way the part is turned may all differ while the part is
the same. Each draft's layout (:mod:`forge_spec.placement`) is reduced to
features, each one shape of the part placed in the frame:

- a solid: a box, a rod, a cone, a ball or a dome, a round-ended tab, a
  region's envelope, with its sizes, its centre and the way it points;
- a cut: a round or a square-edged one, by its mouth and how deep it goes,
  or, right through, by the line it runs along (where it enters is then no
  matter: one hole through a plate is one, drilled from either side); a
  counterbore or countersink by its own place, at the mouth it widens; and
  letters by where they are and which way they read;
- each rounded or chamfered edge, a hollow and its openings, a thread on its
  rod: by where each is on the part.

The second is turned every way a solid can be turned (the 24 rotations,
never a mirror image, which is another part) and moved every way that lines
one of its shapes up with one of the first's, and the way that matches most
is kept: so a size that differs moves nothing else. What is left unmatched
is the difference, each paired with its likeliest counterpart and said of the
first draft's item and field where it can be, so the person can answer there.
A rounding, a hollow or a thread that only follows a changed item is no
difference of its own. Shapes are compared one by one: a solid split into
others (one block, or two stacked flush) reads as a difference until the
compiled parts are compared as geometry (stage 4), and the person answers
it "right as drafted".

- :func:`differences`: the questions the second draft raises about the first.
- :func:`features`: a layout reduced to what it builds.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .checks import SpecReport
from .geometry import EPS, Vec
from .items.compare import COMPARE
from .items.compare._common import Feature, _add, _mid, _r, _sub
from .problems import pointer

__all__ = ["Difference", "Feature", "differences", "features"]

#: How close two sizes or places must be to be the same, in mm (and two unit
#: directions, in each component).
TOLERANCE = 1e-3


class Shape(StrEnum):
    """The shapes features are compared as, which aren't item kinds even where they share a name (a region's envelope, letters).

    A solid of a kind with no shape of its own is its kind's name.
    """

    BOX = "box"
    ROUND_ENDED_TAB = "round-ended tab"
    REGION = "region"
    ROD = "rod"
    CONE = "cone"
    DOME = "dome"
    BALL = "ball"
    ROUND_CUT = "round cut"
    SQUARE_CUT = "square cut"
    RIM = "rim"
    TEXT = "text"
    EDGE = "edge"
    HOLLOW = "hollow"
    THREAD = "thread"


@dataclass(frozen=True)
class Difference:
    """Where the second draft reads the brief otherwise: said of the first draft's field, or of the spec."""

    at: str
    message: str


# ----------------------------------------------------------------------
# What a layout builds
# ----------------------------------------------------------------------
def features(report: SpecReport) -> tuple[Feature, ...]:
    """Every shape a checked draft builds: its solids, its cuts, and its rounded edges, hollows and threads."""
    spec, layout = report.spec, report.layout
    if spec is None or layout is None:
        return ()
    found: list[Feature] = []
    for n, item in enumerate(spec.items):
        found += COMPARE[item.kind].features(n, item, layout)
    return tuple(found)


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


# ----------------------------------------------------------------------
# Turning one draft onto the other
# ----------------------------------------------------------------------
Rotation = tuple[
    tuple[int, int, int], tuple[int, int, int]
]  # (where each axis comes from, its sign)


def _rotations() -> tuple[Rotation, ...]:
    """The 24 rotations of a solid, the identity first: each axis goes to an axis, signed.

    A turn keeps the part's handedness: its determinant, the permutation's
    parity times the signs, is +1. A mirror image (-1) is another part.
    """
    found: list[Rotation] = []
    for perm in itertools.permutations(range(3)):
        swaps = sum(1 for i in range(3) for j in range(i + 1, 3) if perm[i] > perm[j])
        for signs in itertools.product((1, -1), repeat=3):
            if (-1) ** swaps * signs[0] * signs[1] * signs[2] == 1:
                found.append(
                    ((perm[0], perm[1], perm[2]), (signs[0], signs[1], signs[2]))
                )
    return tuple(found)


_ROTATIONS = _rotations()


def _turn(rotation: Rotation, v: Vec) -> Vec:
    perm, signs = rotation
    return (signs[0] * v[perm[0]], signs[1] * v[perm[1]], signs[2] * v[perm[2]])


@dataclass(frozen=True)
class _Move:
    """A turn, then a shift: where the second draft's frame lies in the first's."""

    rotation: Rotation
    shift: Vec


_STILL = _Move(_ROTATIONS[0], (0.0, 0.0, 0.0))


@dataclass(frozen=True)
class _Placed:
    """A feature in the first draft's frame: its sizes, its directions, and the point that stands for its place."""

    feature: Feature
    sizes: Vec | None
    directions: tuple[tuple[Vec, bool], ...]
    key: Vec | None


def _placed(feature: Feature, move: _Move) -> _Placed:
    sizes: Vec | None = None
    if feature.sizes is not None:
        turned = _turn(move.rotation, feature.sizes)
        sizes = (abs(turned[0]), abs(turned[1]), abs(turned[2]))
    directions = tuple(
        (_turn(move.rotation, d), signed) for d, signed in feature.directions
    )
    key = (
        None
        if feature.point is None
        else _add(_turn(move.rotation, feature.point), move.shift)
    )
    if key is not None and feature.line and directions:
        # A line stands for its place by its point nearest the frame's origin.
        u = directions[0][0]
        key = _add(key, u, -_dot(key, u))
    return _Placed(feature, sizes, directions, key)


def _close(a: object, b: object) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= TOLERANCE
    return a == b


def _alike(a: Sequence[object], b: Sequence[object]) -> bool:
    return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b, strict=True))


def _same(a: _Placed, b: _Placed, *, places: bool = True) -> bool:
    """Whether two placed features are one shape: alike, sized, pointing and (``places``) placed alike."""
    fa, fb = a.feature, b.feature
    if fa.shape != fb.shape or fa.line != fb.line or not _alike(fa.detail, fb.detail):
        return False
    if (a.sizes is None) != (b.sizes is None) or (a.key is None) != (b.key is None):
        return False
    if (
        a.sizes is not None
        and b.sizes is not None
        and any(abs(a.sizes[k] - b.sizes[k]) > TOLERANCE for k in range(3))
    ):
        return False
    if len(a.directions) != len(b.directions):
        return False
    for (u, signed), (v, _) in zip(a.directions, b.directions, strict=True):
        apart = max(abs(u[k] - v[k]) for k in range(3))
        if signed and apart > TOLERANCE:
            return False
        if (
            not signed
            and min(apart, max(abs(u[k] + v[k]) for k in range(3))) > TOLERANCE
        ):
            return False
    if places and a.key is not None and b.key is not None:
        return all(abs(a.key[k] - b.key[k]) <= TOLERANCE for k in range(3))
    return True


Cell = tuple[str, tuple[int, int, int] | None]

#: The cells next to a cell, itself included: two places within TOLERANCE
#: of each other always lie in neighbouring cells.
_NEAR = tuple(itertools.product((-1, 0, 1), repeat=3))


def _cell(placed: _Placed) -> Cell:
    key, shape = placed.key, placed.feature.shape
    if key is None or not all(math.isfinite(c / TOLERANCE) for c in key):
        return (shape, None)
    return (
        shape,
        (
            round(key[0] / TOLERANCE),
            round(key[1] / TOLERANCE),
            round(key[2] / TOLERANCE),
        ),
    )


def _match(
    first: Sequence[_Placed], second: Sequence[Feature], move: _Move
) -> tuple[list[int], list[int]]:
    """Pair the features one to one, the second's moved onto the first's; return each draft's left unpaired.

    The second's features are filed by shape and place, so each of the
    first's is tried only against those near it: a pattern of hundreds of
    holes compares in about as many steps, not hundreds squared.
    """
    moved = [_placed(f, move) for f in second]
    cells: dict[Cell, list[int]] = {}
    for j, b in enumerate(moved):
        cells.setdefault(_cell(b), []).append(j)
    taken: set[int] = set()
    unpaired: list[int] = []
    for i, a in enumerate(first):
        here = _cell(a)
        near = [here] if here[1] is None else [
            (here[0], (here[1][0] + d[0], here[1][1] + d[1], here[1][2] + d[2])) for d in _NEAR
        ]  # fmt: skip
        partner = next(
            (
                j
                for cell in near
                for j in cells.get(cell, ())
                if j not in taken and _same(a, moved[j])
            ),
            None,
        )
        if partner is None:
            unpaired.append(i)
        else:
            taken.add(partner)
    return unpaired, [j for j in range(len(second)) if j not in taken]


def _centre(report: SpecReport) -> Vec:
    extent = report.layout.extent() if report.layout is not None else None
    return _mid(*extent) if extent is not None else (0.0, 0.0, 0.0)


def _signature(f: Feature) -> str:
    """What a feature is, but not where: its shape, its sizes (unturned, sorted) and its detail."""
    sizes = sorted(_r(x) for x in f.sizes) if f.sizes is not None else None
    return repr((f.shape, sizes, f.detail))


def _moves(
    a: Sequence[Feature], b: Sequence[Feature], first: SpecReport, second: SpecReport
) -> list[_Move]:
    """Every way worth trying to lay the second draft on the first.

    For each of the 24 turns: as both drafts place their first body (on the
    origin), centred on each other, and with each of a few of the first's
    shapes lined up with each like shape of the second's. Lining shapes up
    is what lets one size differ without moving everything else.
    """
    signatures: dict[str, list[Feature]] = {}
    for f in a:
        if f.point is not None and not f.line and not f.of:
            signatures.setdefault(_signature(f), []).append(f)
    # The rarest shapes first: each lines the drafts up in the fewest ways.
    anchors = [
        fs[0]
        for _, fs in sorted(signatures.items(), key=lambda kv: (len(kv[1]), kv[0]))[:4]
    ]
    candidates = [f for f in b if f.point is not None and not f.line and not f.of]
    centres = (_centre(first), _centre(second))
    found: list[_Move] = []
    seen: set[tuple[Rotation, tuple[int, int, int]]] = set()
    for rotation in _ROTATIONS:
        shifts = [(0.0, 0.0, 0.0), _sub(centres[0], _turn(rotation, centres[1]))]
        turned = _Move(rotation, (0.0, 0.0, 0.0))
        for anchor in anchors:
            here = _placed(anchor, _STILL)
            assert here.key is not None
            for other in candidates:
                there = _placed(other, turned)
                if there.key is not None and _same(here, there, places=False):
                    shifts.append(_sub(here.key, there.key))
        for shift in shifts:
            key = (
                rotation,
                (
                    round(shift[0] / TOLERANCE),
                    round(shift[1] / TOLERANCE),
                    round(shift[2] / TOLERANCE),
                ),
            )
            if key not in seen:
                seen.add(key)
                found.append(_Move(rotation, shift))
    return found


def _best(
    a: Sequence[Feature], b: Sequence[Feature], moves: Sequence[_Move]
) -> tuple[list[int], list[int]]:
    """The fewest features left unpaired over every move: weighed first on the solids alone, when there are many."""
    first = [_placed(f, _STILL) for f in a]
    if len(moves) > 6 and len(a) + len(b) > 64:
        solids_a = [
            p
            for p in first
            if p.feature.sizes is not None and not p.feature.line and not p.feature.of
        ]
        solids_b = [f for f in b if f.sizes is not None and not f.line and not f.of]

        def left(move: _Move) -> int:
            unpaired = _match(solids_a, solids_b, move)
            return len(unpaired[0]) + len(unpaired[1])

        moves = sorted(moves, key=left)[:6]
    best: tuple[list[int], list[int]] | None = None
    for move in moves:
        unpaired = _match(first, b, move)
        if best is None or len(unpaired[0]) + len(unpaired[1]) < len(best[0]) + len(
            best[1]
        ):
            best = unpaired
        if not unpaired[0] and not unpaired[1]:
            break
    assert best is not None
    return best


# ----------------------------------------------------------------------
# The differences
# ----------------------------------------------------------------------
def differences(first: SpecReport, second: SpecReport) -> tuple[Difference, ...]:
    """What the second draft builds otherwise than the first, said of the first's items and fields.

    Empty when the two build the same part, however each is written or
    turned. Neither draft is taken as right: the person settles each one.
    Only drafts the person could confirm are compared: one with a fault is
    the writer's to fix first, and one that can't be made (CAN'T, UNABLE)
    ends its run; neither builds anything yet (ValueError).
    """
    for report in (first, second):
        if report.spec is None or any(
            p.kind in ("fault", "cant", "unable") for p in report.problems
        ):
            raise ValueError(
                "only drafts that check clean, and can be made, are compared"
            )
    a, b = features(first), features(second)
    found: dict[str, list[str]] = {}
    if a or b:
        only_first, only_second = _best(a, b, _moves(a, b, first, second))
        left_a, left_b = [a[i] for i in only_first], [b[j] for j in only_second]
        pairs = _pairs(left_a, left_b)
        # Roundings, hollows and threads follow the item they are on: where
        # it differs, they move or grow with it, and say nothing new.
        changed = {
            left_a[i].item for i, _ in pairs if i is not None and not left_a[i].of
        }
        for i, j in pairs:
            if i is not None and j is not None:
                if left_a[i].of in changed and _what(left_a[i]) == _what(left_b[j]):
                    continue
                at, said = _contrast(left_a[i], left_b[j], first)
                found.setdefault(at, []).append(said)
            elif i is not None and left_a[i].shape == "rim":
                rim = left_a[i]
                found.setdefault(pointer("items", rim.index, rim.field), []).append(
                    f"{rim.item} has a {rim.field} ({_rim(rim)}) here, none in the second draft")  # fmt: skip
            elif i is not None:
                mine = left_a[i]
                found.setdefault(pointer("items", mine.index), []).append(
                    f"the second draft has no {mine.kind} like {mine.item}{_describe(mine)}")  # fmt: skip
            elif j is not None:
                extra = left_b[j]
                found.setdefault("", []).append(
                    f"the second draft has a {extra.kind}{_describe(extra)} that this one hasn't")  # fmt: skip
    ours, theirs = (_material(r) for r in (first, second))
    if _named(ours) != _named(theirs):
        found.setdefault(pointer("requirements", "material"), []).append(
            f"the material is {repr(ours) if ours else 'not given'} here, "
            f"{repr(theirs) if theirs else 'not given'} in the second draft")  # fmt: skip
    return tuple(
        Difference(at, "; ".join(dict.fromkeys(messages)))
        for at, messages in found.items()
    )


def _what(f: Feature) -> str:
    """What a follower is, whatever its place and size: a rounding of one radius on one kind of edge."""
    return repr((f.shape, f.kind, f.detail, len(f.directions)))


def _pairs(
    mine: Sequence[Feature], theirs: Sequence[Feature]
) -> list[tuple[int | None, int | None]]:
    """Each unpaired feature of the first with its likeliest counterpart in the second, or none.

    Of one shape, the likeliest differ in the fewest ways (their detail,
    their size), then lie nearest: so a hole that moved is said to have
    moved, not to have changed size with another that moved too.
    """
    costs: list[tuple[int, float, int, int]] = []
    if len(mine) * len(theirs) <= 40_000:
        for i, f in enumerate(mine):
            for j, g in enumerate(theirs):
                if f.shape == g.shape or (
                    f.kind == g.kind and "rim" not in (f.shape, g.shape)
                ):
                    ways, far = _apart(f, g)
                    costs.append((ways + 2 * (f.shape != g.shape), far, i, j))
        costs.sort()
    else:  # too many to weigh each against each: in order, shape by shape
        costs = [(0, 0.0, i, j) for i, j in zip(range(len(mine)), range(len(theirs)), strict=False)
                 if mine[i].shape == theirs[j].shape]  # fmt: skip
    used_i: set[int] = set()
    used_j: set[int] = set()
    found: list[tuple[int | None, int | None]] = []
    for _, _, i, j in costs:
        if i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            found.append((i, j))
    found.sort(key=lambda p: p[0] if p[0] is not None else -1)
    found += [(i, None) for i in range(len(mine)) if i not in used_i]
    found += [(None, j) for j in range(len(theirs)) if j not in used_j]
    return found


def _apart(f: Feature, g: Feature) -> tuple[int, float]:
    """In how many ways two features of one shape differ, and how far apart they lie (each in its own frame)."""
    ways = int(not _alike(f.detail, g.detail))
    if f.sizes is not None and g.sizes is not None:
        ways += int(sorted(_r(x) for x in f.sizes) != sorted(_r(x) for x in g.sizes))
    far = (
        math.dist(f.point, g.point)
        if f.point is not None and g.point is not None
        else 0.0
    )
    return ways, far


def _material(report: SpecReport) -> str:
    material = report.spec.requirements.material if report.spec is not None else None
    return material.text if material is not None else ""


def _named(text: str) -> str:
    """A material's name as compared: "PETG", "petg" and "PETG " are one."""
    return " ".join(text.split()).casefold()


def _contrast(mine: Feature, other: Feature, report: SpecReport) -> tuple[str, str]:
    """Where two features of one shape differ, as a pointer into the first draft, and how."""
    here = pointer("items", mine.index)
    name, shape = mine.item, mine.shape
    if shape in (Shape.ROUND_CUT, Shape.ROD) and not _close(
        mine.detail[0], other.detail[0]
    ):
        return here + pointer(mine.field or "diameter"), (
            f"{name} is Ø{_mm(mine.detail[0])} here, Ø{_mm(other.detail[0])} in the second draft")  # fmt: skip
    if shape in (Shape.ROUND_CUT, Shape.SQUARE_CUT):
        if mine.line != other.line or not _close(_cut_depth(mine), _cut_depth(other)):
            return here + pointer(
                "depth"
            ), f"{name} goes {_depth(mine)} here, {_depth(other)} in the second draft"
        if shape == Shape.SQUARE_CUT and not _close(mine.detail[-1], other.detail[-1]):
            field = COMPARE[mine.kind].corner_field
            return here + pointer(field), (f"{name}'s corners are rounded to {_mm(mine.detail[-1])} here, "
                                           f"{_mm(other.detail[-1])} in the second draft")  # fmt: skip
    if shape == Shape.EDGE:
        if not _close(mine.detail[1], other.detail[1]):
            return here + pointer(mine.field), (f"{name}'s {mine.field} is {_mm(mine.detail[1])} here, "
                                                f"{_mm(other.detail[1])} in the second draft")  # fmt: skip
        return here + pointer(
            "edges"
        ), f"{name} rounds other edges in the second draft: check which the brief means"
    if shape != other.shape:  # one item kind, built two ways: a square or a round end
        found = COMPARE[mine.kind].shape_differs(mine, other, here)
        if found is not None:
            return found
        return here, f"{name} is a {shape} here, a {other.shape} in the second draft"
    if shape == Shape.RIM:
        if _alike(mine.detail, other.detail):
            return here + pointer(
                mine.field
            ), f"{name}'s {mine.field} is on another side in the second draft"
        return here + pointer(mine.field), (f"{name}'s {mine.field} is {_rim(mine)} here, {_rim(other)} in the "
                                            "second draft")  # fmt: skip
    if shape == Shape.REGION:
        for k, field in enumerate(("describe", "min_wall")):
            if not _close(mine.detail[k], other.detail[k]):
                return here + pointer(field), (f"{name}'s {field} is {_shown(mine.detail[k])} here, "
                                               f"{_shown(other.detail[k])} in the second draft")  # fmt: skip
    if shape == Shape.TEXT:
        for k, field in enumerate(("text", "mode", "height", "depth")):
            if not _close(mine.detail[k], other.detail[k]):
                return here + pointer(field), (f"{name}'s {field} is {_shown(mine.detail[k])} here, "
                                               f"{_shown(other.detail[k])} in the second draft")  # fmt: skip
        return here + pointer(
            "place"
        ), f"{name} sits or reads another way in the second draft: check the brief"
    if shape == Shape.HOLLOW:
        if (
            mine.sizes is not None
            and other.sizes is not None
            and _box(mine.sizes) != _box(other.sizes)
        ):
            return here, (f"the hollow {name} leaves is {_box(mine.sizes)} here, {_box(other.sizes)} in the second "
                          "draft")  # fmt: skip
        return here + pointer(
            "open"
        ), f"{name} is open on other faces in the second draft: check the brief"
    if not _alike(mine.detail, other.detail):
        return (
            here,
            f"{name} is {_details(mine)} here, {_details(other)} in the second draft",
        )
    if (
        mine.sizes is not None
        and other.sizes is not None
        and (sorted(_r(x) for x in mine.sizes) != sorted(_r(x) for x in other.sizes))
    ):
        return (
            here,
            f"{name} is {_box(mine.sizes)} here, {_box(other.sizes)} in the second draft",
        )
    placed = (
        report.spec is not None and report.spec.items[mine.index].get("on") is not None
    )
    return (here + pointer("place") if placed else here), (
        f"{name} sits elsewhere, or points another way, in the second draft: check where the brief puts it")  # fmt: skip


def _rim(feature: Feature) -> str:
    """A counterbore or countersink in words: "Ø9, 1 mm deep", "Ø9 at 90°"."""
    kind, diameter, last = feature.detail[:3]
    if kind == "counterbore":
        return (
            f"\u00d8{diameter:g}, {last:g} mm deep"
            if isinstance(diameter, float) and isinstance(last, float)
            else "?"
        )
    return (
        f"\u00d8{diameter:g} at {last:g}\u00b0"
        if isinstance(diameter, float) and isinstance(last, float)
        else "?"
    )


def _cut_depth(feature: Feature) -> object:
    """How deep a cut goes: None right through."""
    if feature.line:
        return None
    return feature.detail[feature.detail.index("blind") + 1]


def _mm(x: object) -> str:
    return f"{x:g} mm" if isinstance(x, float) else str(x)


def _shown(x: object) -> str:
    if isinstance(x, float):
        return f"{x:g} mm"
    return "none" if x is None else repr(x) if isinstance(x, str) else str(x)


def _depth(feature: Feature) -> str:
    deep = _cut_depth(feature)
    return "right through" if deep is None else f"{_mm(deep)} deep"


def _box(sizes: Iterable[float]) -> str:
    return " x ".join(f"{x:.6g}" for x in sizes if x > EPS) + " mm"


def _describe(feature: Feature) -> str:
    if feature.sizes is None or not any(x > EPS for x in feature.sizes):
        return f" ({_details(feature)})"
    return f" ({_box(feature.sizes)})"


def _details(feature: Feature) -> str:
    shown = [
        f"{x:g}" if isinstance(x, float) else str(x)
        for x in feature.detail
        if x not in (None, ())
    ]
    return ", ".join(shown) or feature.kind
