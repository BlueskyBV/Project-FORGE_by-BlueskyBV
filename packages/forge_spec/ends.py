"""A cut's end condition: how far it goes into the material (4b.0c item 2a; V2-stage4b-0c.md, 3.5).

Today's: **blind** to a depth, **through all** the material under its
mouth, as each program's own model of the material defines it, and (item
2b's first step, schema 1.7) **through everything** made so far behind its
mouth and **up to a face**'s plane, which each program decides from its
own faces and boxes. Every
program reads a cut's end through :func:`end_of`, so item 2b's conditions
(through the next face that covers it, up to a face, a vertex or a body,
an offset from a face, from one to another, symmetric about its face; in
two directions, from a stated start) are each one more kind here, read the
same way. The spec still writes them as ``depth`` (a length, or
``{"through": true}``) until the schema's 2.0 migration.
"""

from __future__ import annotations

from dataclasses import dataclass

from .draft import Item, On, Through, UpTo
from .values import Value

__all__ = ["Blind", "End", "ThroughAll", "ThroughEverything", "UpToFace", "end_of"]


@dataclass(frozen=True)
class Blind:
    """To a depth, measured from the face it is cut into."""

    depth: Value


@dataclass(frozen=True)
class ThroughAll:
    """Through all the material under its mouth (``"through": true``), as each program's model of it defines it."""

    through: Through


@dataclass(frozen=True)
class ThroughEverything:
    """Through all of the part made so far behind its mouth along its axis, cavities and all (``"through_all": true``;
    item 2b's first step): as far as everything made before it reaches."""

    through: Through


@dataclass(frozen=True)
class UpToFace:
    """Its floor in the plane of a flat face of an item made before it, square to the cut, ``offset`` back towards its
    mouth (item 2b's first step): as deep as that plane is from its point, less the offset."""

    face: On
    offset: Value | None
    up_to: UpTo


End = Blind | ThroughAll | ThroughEverything | UpToFace


def end_of(item: Item) -> End | None:
    """A cut's end condition; None for an item with no depth (what stands, or a cut whose depth isn't given)."""
    depth = item.get("depth")
    if isinstance(depth, Through):
        return ThroughEverything(depth) if depth.everything else ThroughAll(depth)
    if isinstance(depth, UpTo):
        return UpToFace(depth.face, depth.offset, depth)
    if isinstance(depth, Value):
        return Blind(depth)
    return None
