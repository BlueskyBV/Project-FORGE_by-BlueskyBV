"""What the check compiler's kinds share (the ``compile`` role's leaf: it imports neither the kinds' modules nor ``compiler.py``).

Moved from ``compiler.py`` at stage 4b.0b's step 3, unchanged: the small
geometry every kind's checks are written with.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np
from forge_numeric import vector as fv
from forge_spec.draft import Counterbore, Countersink, Item, Place
from forge_spec.values import Value
from numpy.typing import NDArray

from forge_checks.kinds.position import BallCentre, Centre, Middle, Ref, RoundEdge
from forge_checks.kinds.surfaces import Ball, Plane, Round
from forge_checks.place import Copy, FlatFace, RoundSide, unit
from forge_checks.view import Capability

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext

Vec = tuple[float, float, float]
Array = NDArray[np.float64]


# ----------------------------------------------------------------------
# Small geometry
# ----------------------------------------------------------------------
def _v(a: Sequence[float]) -> Array:
    return np.asarray(a, dtype=np.float64)


def _t(a: Array | Sequence[float]) -> Vec:
    return (float(a[0]), float(a[1]), float(a[2]))


def _mm(value: object) -> float:
    """A size as it is made, the middle of its tolerance: a check's nominal, held to the band about it (tolerance_of)."""
    assert isinstance(value, Value)
    return value.made_in("mm")


#: How far round its spot a wall's thickness is measured on each of its faces (mm), and how many spots a side
#: of the face are tried for it where its middle is taken.
_WALL_REACH = 2.0


_RAYS = frozenset({Capability.CROSSINGS})


#: A side or a face's edge whose rounded corners leave a flat stretch of it shorter than this (mm) is
#: measured from its rounding, which reaches as far: so short a stretch has too few built points to fit.
_STRAIGHT = 0.5


#: The least plain stretch of a threaded rod's side its diameter and centre are fitted on (mm); less, and its thread's check holds them.
_PLAIN = 1.0


class Buried(str):
    """Why a field has no check of its own: a face that fixes it isn't on the part's surface, as the spec has the part.

    It is inside the part, or pressed against another item's face (a
    divider flush with a box's walls, a bar's ends in the balls on them).
    Built otherwise, such a face changes the part's surface only where it
    comes out of the material, and there it is a surface the spec doesn't
    have: face accounting holds every point of the surface, both ways, to
    the build's tolerance, so it holds the field (``held_by`` "face
    accounting"). Built otherwise and still inside, the part is the same.
    """

    __slots__ = ()


def _deg(value: object) -> float:
    """An angle as it is made, the middle of its tolerance."""
    assert isinstance(value, Value)
    return value.made_in("deg")


def leaves(item: Item) -> tuple[str, ...]:
    """The item's leaf fields, as checks name them: a counterbore's or countersink's values one by one, and a place's.

    A place's leaves are its position along each axis (side, distance and
    ``to`` together: where the item is), its angle, what it is concentric
    with, and its pattern's values, counts and axis
    (``place.pattern.<kind>.<name>``). Every other field is one leaf: a fit
    (its kind, size and grade give one size), an edge set, a face, a choice.
    """
    found: list[str] = []
    for name, value in item.fields.items():
        if isinstance(value, Counterbore):
            found += [f"{name}.diameter", f"{name}.depth"]
        elif isinstance(value, Countersink):
            found += [f"{name}.diameter", f"{name}.angle"]
        elif isinstance(value, Place):
            found += [f"place.{axis}" for axis in value.axes]
            if value.angle is not None:
                found.append("place.angle")
            if value.concentric is not None:
                found.append("place.concentric")
            pattern = value.pattern
            if pattern is not None:
                prefix = f"place.pattern.{pattern.kind}"
                found += [f"{prefix}.{k}" for k in (*pattern.values, *pattern.counts)]
                if pattern.axis is not None:
                    found.append(f"{prefix}.axis")
        else:
            found.append(name)
    return tuple(found)


def box_checks(c: CompileContext, item: Item) -> None:
    """A block's or a post's sizes along the face's axes, and its height."""

    def sizes(copy: Copy) -> dict[str, tuple[str, float]]:
        assert copy.axes is not None
        return {
            "length": (copy.axes[0], _mm(item.get("length"))),
            "width": (copy.axes[1], _mm(item.get("width"))),
        }

    if c.copies(item):
        c._box_body(item, sizes, "height")
    c._standing_fields(item)


def box_round_copy(
    c: CompileContext, item: Item, copy: Copy, side: RoundSide
) -> tuple[Middle, float, float] | None:
    """A box's copy round a side: its two sides square to the way round, its size round the side, its middle's distance from the side's axis."""
    if copy.axes is None:
        return None
    sides = c._box_sides(item, copy, copy.axes[0])
    if sides is None or not all(c.seen(s) for s in sides):
        return None
    assert copy.lo is not None and copy.hi is not None
    k = "xyz".index(copy.axes[0])
    middle = (_v(copy.lo) + _v(copy.hi)) / 2
    w = _v(unit("+" + side.axis))
    off = middle - _v(side.start)
    reach = float(fv.norm(off - (fv.matmul(off, w)) * w))
    return Middle(*sides), float(copy.hi[k] - copy.lo[k]), reach


def rim_refs(rim: Round | Ball) -> tuple[Ref, Ref, Ref]:
    """A round face's edges and centre from the round side or ball it is the end of."""
    centre: Ref = Centre(rim) if isinstance(rim, Round) else BallCentre(rim)
    return RoundEdge(rim, -1.0), RoundEdge(rim, -1.0), centre


def box_sides_along(
    c: CompileContext, item: Item, copy: Copy, axis: str
) -> tuple[Plane, Plane] | None:
    """A box's two fitted sides across ``axis`` (+ first), facing out of its material: its faces there, or the box round its copy's (:meth:`~forge_checks.compiler.CompileContext._box_sides`); None where they are all arc, or aren't on the part's surface."""
    if c._round_ends(item, copy, axis) is not None:
        return None
    faces = c.faces(item.id, copy.index)
    plus, minus = faces.get("+" + axis), faces.get("-" + axis)
    if isinstance(plus, FlatFace) and isinstance(minus, FlatFace):
        sides: tuple[Plane, Plane] | None = (
            c.face_rect(plus),
            c.face_rect(minus),
        )
    else:
        sides = c._box_sides(item, copy, axis)
    # A side pressed against another item (a post flush with a hollow's wall) is no face to fit.
    return sides if sides is not None and all(c.seen(side) for side in sides) else None


def box_no_centre(c: CompileContext, item: Item, group: list[Copy], axis: str) -> str:
    """Why no box copy's centre along ``axis`` is found: its sides there aren't on the part's surface (:class:`Buried`), or it can't be fitted."""
    for copy in group:
        if c._round_ends(item, copy, axis) is not None:
            continue
        faces = c.faces(item.id, copy.index)
        plus, minus = faces.get("+" + axis), faces.get("-" + axis)
        if isinstance(plus, FlatFace) and isinstance(minus, FlatFace):
            sides = (c.face_plane(plus), c.face_plane(minus))
        else:
            found = c._box_sides(item, copy, axis)
            if found is None:
                continue
            sides = found
        if not all(c.seen(side) for side in sides):
            return Buried(f"its {axis} sides aren't both on the part's surface")
    return "the item's centre can't be fitted"


def main_face_refs(
    c: CompileContext, owner: Item, copy: Copy
) -> tuple[Ref, Ref, Ref] | None:
    """A round face's edges and centre from its owner's fitted axis or ball: a rod's end, a dome's flat face, a round pocket's floor."""
    ref = c._main(owner, copy)
    if isinstance(ref, Centre):
        return rim_refs(ref.round)
    if isinstance(ref, BallCentre):
        return rim_refs(ref.ball)
    return None
